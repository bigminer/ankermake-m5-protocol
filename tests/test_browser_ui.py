import contextlib
import re
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
            .filter((item) => item.payload.mqtt && item.payload.mqtt.cmdData !== undefined
                && item.payload.requestId !== "printer-heartbeat")
            .map((item) => ({
                cmdData: item.payload.mqtt.cmdData,
                awaitResponse: !!item.payload.awaitResponse,
            }))
        """
    )


def test_login_page_renders_and_accepts_valid_token(page, live_http_server):
    page.goto(live_http_server + "/")

    # card headers are uppercased via CSS, so match case-insensitively
    assert "access token required" in page.locator("body").inner_text().lower()

    page.get_by_placeholder("Token").fill("shared-secret")
    page.get_by_role("button", name="Log in").click()

    page.wait_for_selector("#control-tab")
    page.click("#control-tab")
    assert "g-code terminal" in page.locator("body").inner_text().lower()


def test_static_assets_have_a_cache_busting_version(page, live_http_server):
    _login(page, live_http_server)
    src = page.locator("script[src*='ankersrv.js']").get_attribute("src")
    assert src is not None and re.search(r"\?v=\d+$", src)


def test_home_hides_transport_protocol_details(page, live_http_server):
    _login(page, live_http_server)
    home_text = page.locator("#home").inner_text()
    assert "MQTT" not in home_text
    assert "PPPP" not in home_text
    assert "CTRL" not in home_text
    assert page.locator("#printer-connection").count() == 0


def _make_printer_live(page):
    """Answer the heartbeat so the UI treats the printer as present.

    Controls gate on the printer answering, not on the ctrl socket being open --
    an open socket only proves we reached ankerctl, which can wedge and drop
    commands silently.
    """
    page.wait_for_function(
        "window.__wsSent.some((item) => item.payload.requestId === 'printer-heartbeat')"
    )
    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/ctrl"))
            .emit({requestId: "printer-heartbeat", mqttReply: {resData: "ok T:20"}});
        """
    )
    page.wait_for_function(
        "document.querySelector('#control-printer-state').textContent === 'Ready'"
    )


def test_control_buttons_require_a_live_printer(page, live_http_server):
    _login(page, live_http_server)

    page.click("#control-tab")
    page.wait_for_function("!document.querySelector('#fan-apply').disabled")

    # An open ctrl socket alone must not enable printer controls.
    assert page.locator("#z-offset-up").is_disabled()

    _make_printer_live(page)

    assert page.locator("#print-pause").is_disabled()
    assert page.locator("#fan-apply").is_enabled()
    assert page.locator("#jog-home").is_disabled()
    assert page.locator("#filament-extrude").is_disabled()
    assert page.locator("#z-offset-up").is_enabled()


def test_home_stays_disabled_and_sends_no_command(page, live_http_server):
    _login(page, live_http_server)
    page.click("#control-tab")

    assert page.locator("#jog-home").is_disabled()
    assert "does not safely engage" in page.locator("#jog-home").get_attribute("title")
    assert not any(
        frame.get("mqtt", {}).get("commandType") == 0x0402
        for frame in _ctrl_frames(page)
    )
    assert _commands(page) == []


def test_web_terminal_blocks_z_homing_but_allows_xy_homing(page, live_http_server):
    _login(page, live_http_server)
    page.click("#control-tab")
    page.wait_for_function("!document.querySelector('#gcode-input').disabled")
    _make_printer_live(page)

    page.fill("#gcode-input", "G28")
    page.press("#gcode-input", "Enter")
    page.fill("#gcode-input", "G28 Z")
    page.press("#gcode-input", "Enter")
    assert _commands(page) == []

    page.fill("#gcode-input", "G28 X Y")
    page.press("#gcode-input", "Enter")
    assert _commands(page) == [{"cmdData": "G28 X Y", "awaitResponse": True}]


def test_printer_state_requires_a_heartbeat_reply(page, live_http_server):
    _login(page, live_http_server)

    page.wait_for_function(
        "window.__wsSent.some((item) => item.payload.requestId === 'printer-heartbeat')"
    )
    assert page.locator("#control-printer-state").inner_text() == "Checking…"

    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/ctrl"))
            .emit({requestId: "printer-heartbeat", mqttReply: {resData: "ok T:20"}});
        """
    )
    page.wait_for_function(
        "document.querySelector('#control-printer-state').textContent === 'Ready'"
    )

    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/ctrl"))
            .emit({requestId: "printer-heartbeat", mqttReply: null});
        """
    )
    page.wait_for_function(
        "document.querySelector('#control-printer-state').textContent === 'Offline'"
    )


def test_controls_disable_when_the_printer_stops_answering(page, live_http_server):
    """An open ctrl socket only proves we reached ankerctl.  When the printer
    itself stops answering, the controls must go dead rather than accept clicks
    that are silently dropped."""
    _login(page, live_http_server)
    _make_printer_live(page)
    page.wait_for_function("!document.querySelector('.jog-btn').disabled")

    # Printer stops answering while the ctrl socket stays open.
    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/ctrl"))
            .emit({requestId: "printer-heartbeat", mqttReply: null});
        """
    )
    page.wait_for_function("document.querySelector('#control-printer-state').textContent === 'Offline'")
    assert page.locator(".jog-btn").first.is_disabled()
    assert page.locator("#z-offset-up").is_disabled()
    assert page.locator("#filament-extrude").is_disabled()


def test_offline_printer_refuses_to_send_but_still_heartbeats(page, live_http_server):
    """The send guard must block user commands when the printer is offline, yet
    let the heartbeat through -- it is what re-establishes liveness."""
    _login(page, live_http_server)
    page.click("#control-tab")
    _make_printer_live(page)

    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/ctrl"))
            .emit({requestId: "printer-heartbeat", mqttReply: null});
        """
    )
    page.wait_for_function("document.querySelector('#control-printer-state').textContent === 'Offline'")

    page.evaluate("window.__wsSent.length = 0")
    page.fill("#gcode-input", "M105")
    page.press("#gcode-input", "Enter")
    assert _commands(page) == [], "a command was sent to an offline printer"

    # The heartbeat must still be exempt from the guard.
    page.wait_for_function(
        "window.__wsSent.some((item) => item.payload.requestId === 'printer-heartbeat')"
    )


def test_print_controls_require_active_job_telemetry(page, live_http_server):
    _login(page, live_http_server)
    assert page.locator("#print-pause").is_disabled()

    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/state"))
            .emit({print: {name: "job.gcode"}});
        """
    )
    page.wait_for_function("!document.querySelector('#print-pause').disabled")

    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/state"))
            .emit({print: {name: ""}});
        """
    )
    page.wait_for_function("document.querySelector('#print-pause').disabled")


def test_printer_state_times_out_when_heartbeat_response_stalls(page, live_http_server):
    _login(page, live_http_server)
    page.wait_for_timeout(5500)
    assert page.locator("#control-printer-state").inner_text() == "Offline"


def test_printer_state_distinguishes_telemetry_from_control(page, live_http_server):
    _login(page, live_http_server)

    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/state"))
            .emit({nozzle: {current: 2000, target: 0}});
        window.__wsInstances.find((ws) => ws.url.includes("/ws/ctrl")).close();
        """
    )
    page.wait_for_function(
        "document.querySelector('#control-printer-state').textContent === 'Ready'"
    )


def test_attended_filament_and_z_controls_send_bounded_gcode(page, live_http_server):
    _login(page, live_http_server)
    page.click("#control-tab")
    page.wait_for_function("!document.querySelector('#fan-apply').disabled")
    page.on("dialog", lambda dialog: dialog.accept())

    page.evaluate(
        """
        const state = window.__wsInstances.find((ws) => ws.url.includes("/ws/state"));
        state.emit({state: "idle", nozzle: {current: 20000, target: 0}});
        """
    )
    page.wait_for_function("!document.querySelector('#filament-extrude').disabled")

    page.click("#filament-extrude")
    page.click("#filament-retract")
    page.click("#z-offset-up")
    page.click("#z-offset-down")

    assert _commands(page) == [
        {"cmdData": "M83", "awaitResponse": False},
        {"cmdData": "G1 E5 F300", "awaitResponse": False},
        {"cmdData": "M82", "awaitResponse": False},
        {"cmdData": "M83", "awaitResponse": False},
        {"cmdData": "G1 E-5 F300", "awaitResponse": False},
        {"cmdData": "M82", "awaitResponse": False},
        {"cmdData": "M290 Z0.05", "awaitResponse": False},
        {"cmdData": "M290 Z-0.05", "awaitResponse": False},
    ]

    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/state"))
            .emit({state: "printing"});
        """
    )
    page.wait_for_function("document.querySelector('#filament-extrude').disabled")
    assert page.locator("#z-offset-up").is_disabled()


def test_control_buttons_send_expected_gcode_payloads(page, live_http_server):
    _login(page, live_http_server)
    page.click("#control-tab")
    page.on("dialog", lambda dialog: dialog.accept())

    # A running job supplies the filePath that PRINT_CONTROL needs.
    page.evaluate(
        """
        window.__wsInstances
            .find((ws) => ws.url.includes("/ws/state"))
            .emit({print: {name: "job.gcode"}});
        """
    )
    page.wait_for_function("!document.querySelector('#print-pause').disabled")

    page.click("#print-pause")
    page.click("#print-resume")
    page.click("#print-stop")
    assert page.locator("#jog-home").is_disabled()

    # Motion controls become available again once the job is no longer active.
    page.evaluate(
        """
        window.__wsInstances
            .find((ws) => ws.url.includes("/ws/state"))
            .emit({state: "idle", print: {name: ""}});
        """
    )
    page.wait_for_function("!document.querySelector('.jog-btn').disabled")
    assert page.locator("#jog-home").is_disabled()

    page.click("#fan-apply")
    page.locator("#fan-slider").evaluate(
        "el => { el.value = '50'; el.dispatchEvent(new Event('input')); }"
    )
    page.click("#fan-apply")
    page.select_option("#jog-step", "1")
    page.click(".jog-btn[data-axis='X'][data-dir='1']")
    page.click(".jog-btn[data-axis='X'][data-dir='-1']")
    page.click(".jog-btn[data-axis='Y'][data-dir='1']")
    page.click(".jog-btn[data-axis='Y'][data-dir='-1']")
    page.click(".jog-btn[data-axis='Z'][data-dir='1']")
    page.click(".jog-btn[data-axis='Z'][data-dir='-1']")
    page.click("#control-nozzle-input")
    page.wait_for_function(
        "document.querySelector('#temperature-picker').dataset.temperatureTarget === 'control-nozzle-input'"
    )
    assert page.locator("#temperature-picker-range").get_attribute("max") == "300"
    assert page.locator("#popupModalInputCustom").is_visible()
    page.locator("#temperature-picker-range").evaluate("el => el.value = '40'")
    page.click("#popupModalInputOK")
    page.wait_for_selector("#popupModalInput", state="hidden")
    page.click("#control-bed-input")
    page.wait_for_function(
        "document.querySelector('#temperature-picker').dataset.temperatureTarget === 'control-bed-input'"
    )
    assert page.locator("#temperature-picker-range").get_attribute("max") == "100"
    page.locator("#temperature-picker-range").evaluate("el => el.value = '35'")
    page.click("#popupModalInputOK")
    page.wait_for_selector("#popupModalInput", state="hidden")
    page.fill("#gcode-input", "M105")
    page.press("#gcode-input", "Enter")

    # Pause/Resume are job-identified PRINT_CONTROL messages. Stop's minimal
    # PRINT_CONTROL precedes M2024; none carry cmdData, so they are asserted
    # separately below.
    assert _commands(page) == [
        {"cmdData": command, "awaitResponse": False}
        for command in (
            "M2024", "M107", "M106 S128",
            "G91", "G1 X1 F3000", "G90",
            "G91", "G1 X-1 F3000", "G90",
            "G91", "G1 Y1 F3000", "G90",
            "G91", "G1 Y-1 F3000", "G90",
            "G91", "G1 Z1 F600", "G90",
            "G91", "G1 Z-1 F600", "G90",
            "M104 S40", "M140 S35",
        )
    ] + [
        {"cmdData": "M105", "awaitResponse": True},
    ]

    def print_control(value):
        return {
            "mqtt": {
                "commandType": 0x03F0,
                "value": value,
                "userName": "ankerctl",
                "filePath": "job.gcode",
            },
            "awaitResponse": False,
        }

    frames = _ctrl_frames(page)
    assert print_control(1) in frames  # pause
    assert print_control(2) in frames  # resume
    assert {
        "mqtt": {"commandType": 0x03F0, "value": 0},
        "awaitResponse": False,
    } in frames  # stop
    assert print_control(0) not in frames


def _ctrl_frames(page):
    return page.evaluate(
        """
        window.__wsSent
            .filter((item) => item.url.includes("/ws/ctrl")
                && item.payload.requestId !== "printer-heartbeat")
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


def test_temperature_modal_starts_with_an_empty_value(page, live_http_server):
    _login(page, live_http_server)
    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/state"))
            .emit({nozzle: {current: 2000, target: 0}});
        """
    )
    page.wait_for_function("!document.querySelector('#set-nozzle-temp').disabled")
    assert page.locator("#set-nozzle-temp").get_attribute("data-clear-on-open") == "true"
    page.click("#set-nozzle-temp")
    page.wait_for_selector("#temperature-picker:not(.d-none)")
    assert page.locator("#modal-input-elem").input_value() == ""


def test_temperature_modal_can_submit_slider_value(page, live_http_server):
    _login(page, live_http_server)
    page.evaluate(
        """
        window.__wsInstances.find((ws) => ws.url.includes("/ws/state"))
            .emit({nozzle: {current: 2000, target: 0}});
        """
    )
    page.wait_for_function("!document.querySelector('#set-nozzle-temp').disabled")
    page.click("#set-nozzle-temp")
    page.wait_for_selector("#temperature-picker:not(.d-none)")
    page.locator("#temperature-picker-range").evaluate(
        "el => { el.value = '200'; el.dispatchEvent(new Event('input')); }"
    )
    page.click("#popupModalInputOK")
    page.wait_for_selector("#popupModalInput", state="hidden")
    assert _commands(page) == [{"cmdData": "M104 S200", "awaitResponse": False}]


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
        const state = window.__wsInstances.find((ws) => ws.url.includes("/ws/state"));
        state.emit({
            state: "printing",
            print: {
                name: "cube.gcode",
                progress: 4200,
                elapsed: 65,
                remaining: 125,
                img: "http://printer.local/preview.jpg",
            },
        });
        state.emit({nozzle: {current: 21500, target: 4000}});
        state.emit({bed: {current: 3300, target: 3500}});
        state.emit({speed: 100});
        state.emit({print: {layer: {current: 3, total: 20}}});
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
