import contextlib
import io
import json
import unittest
from datetime import datetime
from unittest import mock

from cli.model import Account, Config, Printer
from web import app, _require_token, ctrl_send_mqtt


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
        self.old_config = app.config.get("config")
        self.old_login = app.config.get("login")
        self.old_video_supported = app.config.get("video_supported")
        self.old_printer_index = app.config.get("printer_index")
        self.old_webcam_url = app.config.get("webcam_url")

        app.config["TESTING"] = True
        app.config["config"] = FakeConfigManager(make_config())
        app.config["login"] = True
        app.config["video_supported"] = False
        app.config["printer_index"] = 0
        app.config["webcam_url"] = ""

    def tearDown(self):
        app.config["TESTING"] = self.old_testing
        app.config["access_token"] = self.old_access_token
        app.config["config"] = self.old_config
        app.config["login"] = self.old_login
        app.config["video_supported"] = self.old_video_supported
        app.config["printer_index"] = self.old_printer_index
        app.config["webcam_url"] = self.old_webcam_url

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
        self.assertIn(b"GCode Terminal", resp.data)
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

    def test_webcam_setting_persists_in_config(self):
        app.config["access_token"] = "shared-secret"

        with self.client.session_transaction() as sess:
            sess["authed"] = True

        resp = self.client.post("/api/ankerctl/config/webcam", data={"webcam_url": "http://cam/new.mjpg"})

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(app.config["config"].cfg.webcam_url, "http://cam/new.mjpg")

    def test_ws_ctrl_requires_auth_when_token_enabled(self):
        app.config["access_token"] = "shared-secret"

        with app.test_request_context("/ws/ctrl"):
            result = _require_token()

        self.assertEqual(result[1], 401)

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
            client = fake_client

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


if __name__ == "__main__":
    unittest.main()
