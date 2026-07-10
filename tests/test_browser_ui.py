import contextlib
import socket
import threading
from datetime import datetime

import pytest
from werkzeug.serving import make_server

from cli.model import Account, Config, Printer
from web import app


pytestmark = pytest.mark.browser


playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright
PlaywrightError = playwright_sync.Error


class FakeConfigManager:

    def __init__(self, cfg):
        self.cfg = cfg

    @contextlib.contextmanager
    def open(self):
        yield self.cfg

    @contextlib.contextmanager
    def modify(self):
        yield self.cfg


def make_config(webcam_url=""):
    return Config(
        account=Account(
            auth_token="auth-token",
            region="us",
            user_id="user-id",
            email="test@example.com",
            country="US",
        ),
        printers=[
            Printer(
                id="1",
                sn="SN123",
                name="Test Printer",
                model="V8111",
                create_time=datetime.now(),
                update_time=datetime.now(),
                wifi_mac="00:11:22:33:44:55",
                ip_addr="192.168.1.10",
                mqtt_key=b"\x01\x02",
                api_hosts=[],
                p2p_hosts=[],
                p2p_duid="DUID123",
                p2p_key="key",
            )
        ],
        webcam_url=webcam_url,
    )


def _free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


@pytest.fixture()
def configured_app():
    old = {
        "TESTING": app.config.get("TESTING"),
        "access_token": app.config.get("access_token"),
        "config": app.config.get("config"),
        "login": app.config.get("login"),
        "video_supported": app.config.get("video_supported"),
        "printer_index": app.config.get("printer_index"),
        "webcam_url": app.config.get("webcam_url"),
        "preprint_g36": app.config.get("preprint_g36"),
    }

    app.config["TESTING"] = True
    app.config["access_token"] = "shared-secret"
    app.config["config"] = FakeConfigManager(make_config())
    app.config["login"] = True
    app.config["video_supported"] = False
    app.config["printer_index"] = 0
    app.config["webcam_url"] = ""
    app.config["preprint_g36"] = False

    yield app

    for key, value in old.items():
        app.config[key] = value


@pytest.fixture()
def live_http_server(configured_app):
    port = _free_port()
    server = make_server("127.0.0.1", port, configured_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture()
def page(live_http_server):
    script = """
        window.__wsSent = [];
        window.__wsInstances = [];
        class MockWebSocket extends EventTarget {
            constructor(url) {
                super();
                this.url = url;
                this.readyState = 1;
                window.__wsInstances.push(this);
                setTimeout(() => {
                    this.dispatchEvent(new Event("open"));
                    if (this.url.includes("/ws/ctrl")) {
                        this.emit({ankerctl: 1});
                    }
                }, 0);
            }
            send(payload) {
                window.__wsSent.push({
                    url: this.url,
                    payload: JSON.parse(payload),
                });
            }
            close() {
                this.readyState = 3;
                this.dispatchEvent(new Event("close"));
            }
            emit(data) {
                this.dispatchEvent(new MessageEvent("message", {
                    data: JSON.stringify(data),
                }));
            }
        }
        window.WebSocket = MockWebSocket;
        window.JMuxer = class {
            feed() {}
            destroy() {}
        };
    """

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Playwright Chromium is not installed: {exc}")

        browser_context = browser.new_context()
        browser_context.add_init_script(script)
        browser_page = browser_context.new_page()
        yield browser_page
        browser_context.close()
        browser.close()


def _login(page, base_url):
    page.goto(base_url + "/")
    page.get_by_placeholder("Token").fill("shared-secret")
    page.get_by_role("button", name="Log in").click()
    page.wait_for_selector("#control-tab")


def _commands(page):
    return page.evaluate(
        """
        window.__wsSent
            .filter((item) => item.payload.mqtt)
            .map((item) => ({
                cmdData: item.payload.mqtt.cmdData,
                awaitResponse: !!item.payload.awaitResponse,
            }))
        """
    )


def test_login_page_renders_and_accepts_valid_token(page, live_http_server):
    page.goto(live_http_server + "/")

    assert "Access token required" in page.locator("body").inner_text()

    page.get_by_placeholder("Token").fill("shared-secret")
    page.get_by_role("button", name="Log in").click()

    page.wait_for_selector("#control-tab")
    page.click("#control-tab")
    assert "GCode Terminal" in page.locator("body").inner_text()


def test_control_buttons_enable_when_ctrl_socket_opens(page, live_http_server):
    _login(page, live_http_server)

    page.click("#control-tab")
    page.wait_for_function("!document.querySelector('#print-pause').disabled")

    assert page.locator("#print-pause").is_enabled()
    assert page.locator("#fan-apply").is_enabled()
    assert page.locator("#jog-home").is_enabled()


def test_control_buttons_send_expected_gcode_payloads(page, live_http_server):
    _login(page, live_http_server)
    page.click("#control-tab")
    page.wait_for_function("!document.querySelector('#print-pause').disabled")
    page.on("dialog", lambda dialog: dialog.accept())

    page.click("#print-pause")
    page.click("#print-resume")
    page.click("#print-stop")
    page.click("#fan-apply")
    page.locator("#fan-slider").evaluate(
        "el => { el.value = '50'; el.dispatchEvent(new Event('input')); }"
    )
    page.click("#fan-apply")
    page.click("#jog-home")
    page.select_option("#jog-step", "1")
    page.click(".jog-btn[data-axis='X'][data-dir='1']")
    page.click(".jog-btn[data-axis='X'][data-dir='-1']")
    page.click(".jog-btn[data-axis='Y'][data-dir='1']")
    page.click(".jog-btn[data-axis='Y'][data-dir='-1']")
    page.click(".jog-btn[data-axis='Z'][data-dir='1']")
    page.click(".jog-btn[data-axis='Z'][data-dir='-1']")
    page.fill("#control-nozzle-input", "40")
    page.press("#control-nozzle-input", "Enter")
    page.fill("#control-bed-input", "35")
    page.press("#control-bed-input", "Enter")
    page.fill("#gcode-input", "M105")
    page.press("#gcode-input", "Enter")

    assert _commands(page) == [
        {"cmdData": "M2022", "awaitResponse": False},
        {"cmdData": "M2023", "awaitResponse": False},
        {"cmdData": "M2024", "awaitResponse": False},
        {"cmdData": "M107", "awaitResponse": False},
        {"cmdData": "M106 S128", "awaitResponse": False},
        {"cmdData": "G28", "awaitResponse": False},
        {"cmdData": "G91;G1 X1 F3000;G90", "awaitResponse": False},
        {"cmdData": "G91;G1 X-1 F3000;G90", "awaitResponse": False},
        {"cmdData": "G91;G1 Y1 F3000;G90", "awaitResponse": False},
        {"cmdData": "G91;G1 Y-1 F3000;G90", "awaitResponse": False},
        {"cmdData": "G91;G1 Z1 F600;G90", "awaitResponse": False},
        {"cmdData": "G91;G1 Z-1 F600;G90", "awaitResponse": False},
        {"cmdData": "M104 S40", "awaitResponse": False},
        {"cmdData": "M140 S35", "awaitResponse": False},
        {"cmdData": "M105", "awaitResponse": True},
    ]


def _ctrl_frames(page):
    return page.evaluate(
        """
        window.__wsSent
            .filter((item) => item.url.includes("/ws/ctrl"))
            .map((item) => item.payload)
        """
    )


def test_home_tab_light_and_quality_buttons_send_ctrl_payloads(page, live_http_server, configured_app):
    configured_app.config["video_supported"] = True
    _login(page, live_http_server)

    page.click("#light-on")
    page.click("#light-off")
    page.click("#quality-low")
    page.click("#quality-high")

    assert _ctrl_frames(page) == [
        {"light": True},
        {"light": False},
        {"quality": 0},
        {"quality": 1},
    ]


def _submit_preheat_modal(page, trigger, value):
    page.click(trigger)
    page.wait_for_function(
        "document.activeElement === document.querySelector('#modal-input-elem')"
    )
    page.fill("#modal-input-elem", value)
    page.click("#popupModalInputOK")
    page.wait_for_selector("#popupModalInput", state="hidden")


def test_home_tab_preheat_modal_sends_preheat_config(page, live_http_server):
    _login(page, live_http_server)
    # The mqtt socket only reports "opened" (enabling the preheat buttons)
    # once it receives a first message.
    page.evaluate(
        """
        window.__wsInstances
            .find((ws) => ws.url.includes("/ws/mqtt"))
            .emit({commandType: 1003, currentTemp: 2000, targetTemp: 0});
        """
    )
    page.wait_for_function("!document.querySelector('#set-nozzle-temp').disabled")

    _submit_preheat_modal(page, "#set-nozzle-temp", "210")
    _submit_preheat_modal(page, "#set-bed-temp", "60")

    assert _ctrl_frames(page) == [
        {"mqtt": {"commandType": 0x040E, "nozzle": 21000, "value": 1}},
        {"mqtt": {"commandType": 0x040E, "heatbed": 6000, "value": 1}},
    ]


def test_print_tab_upload_button_posts_gcode_file(page, live_http_server):
    _login(page, live_http_server)
    page.route(
        "**/api/ankerctl/file/upload",
        lambda route: route.fulfill(status=200, content_type="text/html", body="ok"),
    )

    page.click("#print-tab")
    page.set_input_files("#gcode_file", {
        "name": "tiny_safe.gcode",
        "mimeType": "text/x.gcode",
        "buffer": b"G28\nG1 X5 Y5 F3000\n",
    })
    with page.expect_request("**/api/ankerctl/file/upload") as request_info:
        page.click("#gcode-upload")

    request = request_info.value
    assert request.method == "POST"
    assert 'filename="tiny_safe.gcode"' in request.post_data
    assert "G28" in request.post_data


def test_mqtt_telemetry_updates_control_tab(page, live_http_server):
    _login(page, live_http_server)
    page.click("#control-tab")

    page.evaluate(
        """
        const mqtt = window.__wsInstances.find((ws) => ws.url.includes("/ws/mqtt"));
        mqtt.emit({
            commandType: 1001,
            name: "cube.gcode",
            progress: 4200,
            totalTime: 65,
            time: 125,
            img: "http://printer.local/preview.jpg",
            state: "printing",
        });
        mqtt.emit({commandType: 1003, currentTemp: 21500, targetTemp: 4000});
        mqtt.emit({commandType: 1004, currentTemp: 3300, targetTemp: 3500});
        mqtt.emit({commandType: 1006, value: 100});
        mqtt.emit({commandType: 1052, real_print_layer: 3, total_layer: 20});
        """
    )

    assert page.locator("#control-nozzle-current").inner_text() == "215°C"
    assert page.locator("#control-nozzle-target").inner_text() == "40°C"
    assert page.locator("#control-bed-current").inner_text() == "33°C"
    assert page.locator("#control-bed-target").inner_text() == "35°C"
    assert page.locator("#control-progress").inner_text() == "42%"
    assert page.locator("#control-layer").inner_text() == "3 / 20"
    assert page.locator("#control-print-speed").inner_text() == "100mm/s X2"
    assert page.locator("#control-printer-state").inner_text() == "printing"
    assert page.locator("#control-preview-wrap").is_visible()
    assert page.locator("#control-preview-img").get_attribute("src") == "http://printer.local/preview.jpg"
