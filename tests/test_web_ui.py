import contextlib
import io
import json
import time
import unittest
from datetime import datetime
from unittest import mock

from cli.model import Account, Config, Printer
from web import app, _require_token, _state_updates, ctrl_send_mqtt, ctrl_submit_action
from web.printer_actions import (
    BedTarget,
    FanSetting,
    HeaterOff,
    NozzleTarget,
    Pause,
)
from web.lib.service import RunState
from web.printer_snapshot import PrinterSnapshots


class FakeConfigManager:

    def __init__(self, cfg):
        self.cfg = cfg

    @contextlib.contextmanager
    def open(self):
        yield self.cfg

    @contextlib.contextmanager
    def modify(self):
        yield self.cfg


class FakeSocket:

    def __init__(self, messages):
        self.messages = messages
        self.sent = []

    def receive(self):
        if self.messages:
            return self.messages.pop(0)
        return None

    def send(self, payload):
        self.sent.append(payload)


class FakeServiceSet:

    def __init__(self, svcs):
        self.svcs = svcs


class FakeService:

    def __init__(self, state):
        self.state = state


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


class WebUiTestCase(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.old_testing = app.config.get("TESTING")
        self.old_access_token = app.config.get("access_token")
        self.old_slicer_token = app.config.get("slicer_token")
        self.old_max_content_length = app.config.get("MAX_CONTENT_LENGTH")
        self.old_config = app.config.get("config")
        self.old_login = app.config.get("login")
        self.old_video_supported = app.config.get("video_supported")
        self.old_printer_index = app.config.get("printer_index")
        self.old_webcam_url = app.config.get("webcam_url")
        self.old_preprint_g36 = app.config.get("preprint_g36")
        self.old_svc = app.svc
        self.old_printer_snapshots = getattr(app, "printer_snapshots", None)
        self.old_printer_actions = getattr(app, "printer_actions", None)

        app.config["TESTING"] = True
        app.config["config"] = FakeConfigManager(make_config())
        app.config["login"] = True
        app.config["video_supported"] = False
        app.config["printer_index"] = 0
        app.config["webcam_url"] = ""
        app.config["preprint_g36"] = False
        app.config["slicer_token"] = ""
        app.printer_snapshots = PrinterSnapshots(clock=lambda: 100.0)

    def tearDown(self):
        app.config["TESTING"] = self.old_testing
        app.config["access_token"] = self.old_access_token
        app.config["slicer_token"] = self.old_slicer_token
        app.config["MAX_CONTENT_LENGTH"] = self.old_max_content_length
        app.config["config"] = self.old_config
        app.config["login"] = self.old_login
        app.config["video_supported"] = self.old_video_supported
        app.config["printer_index"] = self.old_printer_index
        app.config["webcam_url"] = self.old_webcam_url
        app.config["preprint_g36"] = self.old_preprint_g36
        app.svc = self.old_svc
        app.printer_snapshots = self.old_printer_snapshots
        app.printer_actions = self.old_printer_actions

    def test_root_without_token_is_available(self):
        app.config["access_token"] = ""

        resp = self.client.get("/")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"control-tab", resp.data)

    def test_login_flow_and_exempt_routes(self):
        app.config["access_token"] = "shared-secret"
        app.config["config"] = FakeConfigManager(make_config(webcam_url="http://camera.local/mjpg"))

        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login?next=/", resp.location)

        resp = self.client.get(resp.location)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Access token required", resp.data)

        resp = self.client.post("/login?next=/", data={"token": "wrong", "next": "/"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid token", resp.data)

        resp = self.client.post("/login?next=/", data={"token": "shared-secret", "next": "/"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"G-Code Terminal", resp.data)
        self.assertIn(b"http://camera.local/mjpg", resp.data)

        version_resp = self.client.get("/api/version")
        self.assertEqual(version_resp.status_code, 200)
        self.assertEqual(version_resp.json["server"], "1.9.0")

        with mock.patch("web.util.upload_file_to_printer") as upload_file:
            upload_resp = self.client.post(
                "/api/files/local",
                data={
                    "print": "true",
                    "file": (io.BytesIO(b"G1 X1\n"), "test.gcode"),
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(upload_resp.status_code, 200)
        upload_file.assert_called_once()

    def test_login_rejects_external_next_redirects(self):
        app.config["access_token"] = "shared-secret"

        resp = self.client.post(
            "/login?next=https://example.invalid/phish",
            data={"token": "shared-secret"},
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.location, "/")

    def test_api_files_local_rejects_upload_only(self):
        resp = self.client.post(
            "/api/files/local",
            data={
                "print": "false",
                "file": (io.BytesIO(b"G1 X1\n"), "test.gcode"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(resp.status_code, 409)
        self.assertIn(b"Upload-only not supported", resp.data)

    def test_api_files_local_requires_file(self):
        resp = self.client.post("/api/files/local", data={"print": "true"})

        self.assertEqual(resp.status_code, 400)

    def test_api_files_local_reports_upload_failure(self):
        with mock.patch(
            "web.util.upload_file_to_printer",
            side_effect=ConnectionError("printer offline"),
        ):
            resp = self.client.post(
                "/api/files/local",
                data={
                    "print": "true",
                    "file": (io.BytesIO(b"G1 X1\n"), "test.gcode"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 503)
        self.assertIn(b"Cannot connect to printer", resp.data)
        self.assertIn(b"printer offline", resp.data)

    def test_api_files_local_success(self):
        with mock.patch("web.util.upload_file_to_printer") as upload_file:
            resp = self.client.post(
                "/api/files/local",
                data={
                    "print": "true",
                    "file": (io.BytesIO(b"G1 X1\n"), "test.gcode"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json, {})
        upload_file.assert_called_once()

    def test_api_files_local_requires_key_when_remote(self):
        app.config["slicer_token"] = "slicer-secret"

        with mock.patch("web.util.upload_file_to_printer") as upload_file:
            denied = self.client.post(
                "/api/files/local",
                data={"print": "true", "file": (io.BytesIO(b"G1 X1\n"), "test.gcode")},
                content_type="multipart/form-data",
                environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
            )
            allowed = self.client.post(
                "/api/files/local",
                data={"print": "true", "file": (io.BytesIO(b"G1 X1\n"), "test.gcode")},
                content_type="multipart/form-data",
                headers={"X-Api-Key": "slicer-secret"},
                environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
            )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        upload_file.assert_called_once()

    def test_api_files_local_rejects_oversize_request(self):
        app.config["MAX_CONTENT_LENGTH"] = 8

        resp = self.client.post(
            "/api/files/local",
            data={"print": "true", "file": (io.BytesIO(b"G1 X1\n"), "test.gcode")},
            content_type="multipart/form-data",
        )

        self.assertEqual(resp.status_code, 413)

    def test_status_reports_service_shape(self):
        app.svc = FakeServiceSet({
            "mqttqueue": FakeService(RunState.Running),
            "pppp": FakeService(RunState.Stopped),
        })

        resp = self.client.get("/api/ankerctl/status")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json["status"], "ok")
        self.assertEqual(resp.json["services"]["mqttqueue"]["online"], True)
        self.assertEqual(resp.json["services"]["pppp"]["state"], "Stopped")
        self.assertEqual(resp.json["possible_states"]["Running"], RunState.Running.value)
        self.assertEqual(resp.json["version"]["server"], "1.9.0")

    def test_status_reports_error_when_all_services_offline(self):
        app.svc = FakeServiceSet({
            "mqttqueue": FakeService(RunState.Stopped),
        })

        resp = self.client.get("/api/ankerctl/status")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json["status"], "error")

    def test_webcam_setting_persists_in_config(self):
        app.config["access_token"] = "shared-secret"

        with self.client.session_transaction() as sess:
            sess["authed"] = True

        resp = self.client.post("/api/ankerctl/config/webcam", data={"webcam_url": "http://cam/new.mjpg"})

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(app.config["config"].cfg.webcam_url, "http://cam/new.mjpg")

    def test_update_printer_ip_reports_no_printers_found(self):
        with self.client.session_transaction() as sess:
            sess["authed"] = True

        with mock.patch("cli.pppp.pppp_find_printer_ip_addresses", return_value=[]):
            resp = self.client.post("/api/ankerctl/config/updateip")

        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["_flashes"][-1][0], "danger")
            self.assertIn("No printers responded", sess["_flashes"][-1][1])

    def test_update_printer_ip_reports_update_failure(self):
        with self.client.session_transaction() as sess:
            sess["authed"] = True

        with mock.patch(
            "cli.pppp.pppp_find_printer_ip_addresses",
            return_value=[("DUID123", "192.168.1.50")],
        ), mock.patch("cli.config.update_printer_ip_addresses", return_value=None):
            resp = self.client.post("/api/ankerctl/config/updateip")

        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["_flashes"][-1], ("danger", "Internal error."))

    def test_ws_ctrl_requires_auth_when_token_enabled(self):
        app.config["access_token"] = "shared-secret"

        with app.test_request_context("/ws/ctrl"):
            result = _require_token()

        self.assertEqual(result[1], 401)

    def test_ws_state_immediately_sends_the_server_owned_snapshot(self):
        app.config["access_token"] = ""
        app.printer_snapshots.observe(
            "printer-0",
            {"state": "printing", "print": {"name": "job.gcode"}},
        )

        @contextlib.contextmanager
        def fake_borrow(name):
            self.assertEqual(name, "mqttqueue")
            yield object()

        with mock.patch.object(app.svc, "borrow", fake_borrow):
            payload = next(_state_updates())

        self.assertEqual(payload["cursor"], 1)
        self.assertEqual(payload["state"], "printing")
        self.assertEqual(payload["print"]["name"], "job.gcode")
        self.assertEqual(payload["facts"]["print.name"]["freshness"], "fresh")

    def test_named_action_adapter_derives_printer_and_job_context_on_the_server(self):
        app.config["printer_index"] = 0
        submitted = []

        class FakeActions:
            def submit(self, request):
                submitted.append(request)
                return SimpleNamespace(to_dict=lambda: {
                    "requestId": request.request_id,
                    "status": "accepted",
                })

        from types import SimpleNamespace
        app.printer_actions = FakeActions()
        socket = FakeSocket([])

        ctrl_submit_action(socket, {
            "requestId": "pause-1",
            "type": "pause",
            "printerId": "attacker-chosen",
            "userName": "attacker-chosen",
            "filePath": "attacker-chosen.gcode",
        })

        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0].request_id, "pause-1")
        self.assertEqual(submitted[0].printer_id, "printer-0")
        self.assertIsInstance(submitted[0].action, Pause)
        self.assertEqual(json.loads(socket.sent[0])["action"]["status"], "accepted")

    def test_named_thermal_action_adapter_builds_typed_server_requests(self):
        app.config["printer_index"] = 0
        submitted = []

        class FakeActions:
            def submit(self, request):
                submitted.append(request)
                return SimpleNamespace(to_dict=lambda: {
                    "requestId": request.request_id,
                    "status": "accepted",
                })

        from types import SimpleNamespace
        app.printer_actions = FakeActions()
        socket = FakeSocket([])

        messages = [
            {"requestId": "nozzle-1", "type": "nozzle_target", "celsius": 40},
            {"requestId": "bed-1", "type": "bed_target", "celsius": 35},
            {"requestId": "off-1", "type": "heater_off", "heater": "nozzle"},
            {"requestId": "fan-1", "type": "fan_setting", "percent": 50},
        ]
        for message in messages:
            ctrl_submit_action(socket, {**message, "printerId": "attacker-chosen"})

        self.assertEqual(
            [request.printer_id for request in submitted],
            ["printer-0"] * 4,
        )
        self.assertEqual(
            [request.action for request in submitted],
            [
                NozzleTarget(celsius=40),
                BedTarget(celsius=35),
                HeaterOff(heater="nozzle"),
                FanSetting(percent=50),
            ],
        )

    def test_ws_ctrl_gcode_command_round_trip(self):
        app.config["access_token"] = ""

        fake_client = mock.Mock()
        fake_socket = FakeSocket([])
        message = {
            "mqtt": {
                "commandType": 0x0413,
                "cmdData": "M104 S60",
                "cmdLen": 8,
            },
            "awaitResponse": True,
        }

        handlers = []

        class FakeMqttService:
            transport = fake_client

            @contextlib.contextmanager
            def tap(self, handler):
                handlers.append(handler)
                try:
                    yield self
                finally:
                    handlers.remove(handler)

        def deliver(cmd):
            # replies arrive via the service notify stream; include an
            # unrelated status message to exercise the reply filter
            for handler in handlers:
                handler({"commandType": 1003, "currentTemp": 21000})
                handler({"commandType": 0x0413, "resData": "ok"})

        fake_client.command.side_effect = deliver

        @contextlib.contextmanager
        def fake_borrow(name):
            self.assertEqual(name, "mqttqueue")
            yield FakeMqttService()

        with mock.patch.object(app.svc, "borrow", fake_borrow):
            ctrl_send_mqtt(fake_socket, message)

        fake_client.command.assert_called_once_with({
            "commandType": 0x0413,
            "cmdData": "M104 S60",
            "cmdLen": 8,
        })
        self.assertEqual(json.loads(fake_socket.sent[0])["mqttReply"]["resData"], "ok")
        self.assertEqual(handlers, [])

    def test_ws_ctrl_ignores_unrelated_replies_until_timeout(self):
        app.config["access_token"] = ""
        old_timeout = app.config.get("CTRL_MQTT_REPLY_TIMEOUT")

        fake_client = mock.Mock()
        fake_socket = FakeSocket([])
        message = {
            "mqtt": {
                "commandType": 0x0413,
                "cmdData": "M105",
                "cmdLen": 4,
            },
            "awaitResponse": True,
        }

        class FakeMqttService:
            transport = fake_client

            @contextlib.contextmanager
            def tap(self, handler):
                handler({"commandType": 1003, "currentTemp": 21000})
                yield self

        @contextlib.contextmanager
        def fake_borrow(name):
            self.assertEqual(name, "mqttqueue")
            yield FakeMqttService()

        with mock.patch.object(app.svc, "borrow", fake_borrow), \
                mock.patch("web.CTRL_MQTT_REPLY_TIMEOUT", 0.01):
            start = time.monotonic()
            ctrl_send_mqtt(fake_socket, message)

        self.assertLess(time.monotonic() - start, 1)
        self.assertIsNone(json.loads(fake_socket.sent[0])["mqttReply"])
        self.assertEqual(app.config.get("CTRL_MQTT_REPLY_TIMEOUT"), old_timeout)

    def test_ws_ctrl_no_response_command_does_not_wait(self):
        app.config["access_token"] = ""

        fake_client = mock.Mock()
        fake_socket = FakeSocket([])
        message = {
            "mqtt": {
                "commandType": 0x0413,
                "cmdData": "M107",
                "cmdLen": 4,
            },
            "awaitResponse": False,
        }

        class FakeMqttService:
            transport = fake_client

            @contextlib.contextmanager
            def tap(self, handler):
                raise AssertionError("tap should not be used without awaitResponse")

        @contextlib.contextmanager
        def fake_borrow(name):
            self.assertEqual(name, "mqttqueue")
            yield FakeMqttService()

        with mock.patch.object(app.svc, "borrow", fake_borrow):
            ctrl_send_mqtt(fake_socket, message)

        fake_client.command.assert_called_once_with(message["mqtt"])
        self.assertEqual(fake_socket.sent, [])

    def test_ws_ctrl_blocks_move_zero_before_transport(self):
        fake_socket = FakeSocket([])
        message = {
            "mqtt": {"commandType": 0x0402, "value": 2},
            "awaitResponse": False,
        }

        with mock.patch.object(app.svc, "borrow") as borrow:
            ctrl_send_mqtt(fake_socket, message)

        borrow.assert_not_called()
        response = json.loads(fake_socket.sent[0])
        self.assertEqual(response["commandType"], 0x0402)
        self.assertIn("disabled", response["ankerctlError"])

    def test_ws_ctrl_blocks_z_homing_but_allows_xy(self):
        fake_client = mock.Mock()
        fake_socket = FakeSocket([])

        class FakeMqttService:
            transport = fake_client

        @contextlib.contextmanager
        def fake_borrow(name):
            self.assertEqual(name, "mqttqueue")
            yield FakeMqttService()

        blocked = (
            "G28", "G28 Z", "G28 X Z", "G28 ; home",
            "G28 X Y\nG28 Z", "N20 G28 Z",
        )
        with mock.patch.object(app.svc, "borrow", fake_borrow):
            for command in blocked:
                ctrl_send_mqtt(fake_socket, {
                    "mqtt": {
                        "commandType": 0x0413,
                        "cmdData": command,
                        "cmdLen": len(command),
                    },
                    "awaitResponse": False,
                })
            ctrl_send_mqtt(fake_socket, {
                "mqtt": {
                    "commandType": 0x0413,
                    "cmdData": "G28 X Y",
                    "cmdLen": 7,
                },
                "awaitResponse": False,
            })

        self.assertEqual(len(fake_socket.sent), len(blocked))
        self.assertTrue(all(
            "ankerctlError" in json.loads(payload)
            for payload in fake_socket.sent
        ))
        fake_client.command.assert_called_once_with({
            "commandType": 0x0413,
            "cmdData": "G28 X Y",
            "cmdLen": 7,
        })

    def test_ws_ctrl_matching_reply_after_unrelated_reply(self):
        app.config["access_token"] = ""

        fake_client = mock.Mock()
        fake_socket = FakeSocket([])
        message = {
            "mqtt": {
                "commandType": 0x0413,
                "cmdData": "M105",
                "cmdLen": 4,
            },
            "awaitResponse": True,
        }
        handlers = []

        class FakeMqttService:
            transport = fake_client

            @contextlib.contextmanager
            def tap(self, handler):
                handlers.append(handler)
                try:
                    yield self
                finally:
                    handlers.remove(handler)

        def deliver(_cmd):
            for handler in handlers:
                handler({"commandType": 1003, "currentTemp": 21000})
                handler({"commandType": 0x0413, "resData": "ok T:21.0"})

        fake_client.command.side_effect = deliver

        @contextlib.contextmanager
        def fake_borrow(name):
            self.assertEqual(name, "mqttqueue")
            yield FakeMqttService()

        with mock.patch.object(app.svc, "borrow", fake_borrow):
            ctrl_send_mqtt(fake_socket, message)

        payload = json.loads(fake_socket.sent[0])
        self.assertEqual(payload["mqttReply"]["resData"], "ok T:21.0")


if __name__ == "__main__":
    unittest.main()
