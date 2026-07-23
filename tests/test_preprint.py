import contextlib
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from web import util


FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    def __init__(self, replies=None):
        self.commands = []
        self.replies = list(replies or [])
        self._mqtt = SimpleNamespace(disconnect=lambda: None)

    def command(self, payload):
        self.commands.append(payload["cmdData"])

    def fetch(self, timeout):
        if self.replies:
            reply = self.replies.pop(0)
        else:
            reply = {"commandType": util._GCODE_COMMAND, "reply": 0, "resData": "ok"}
        return [(None, [reply])]


class FakeFileTransfer:
    def __init__(self):
        self.data = None
        self.filename = None
        self.user_name = None

    def send_file(self, upload, user_name):
        self.data = upload.read()
        self.filename = upload.filename
        self.user_name = user_name


class FakeServiceManager:
    def __init__(self, filetransfer):
        self.filetransfer = filetransfer

    @contextlib.contextmanager
    def borrow(self, name):
        assert name == "filetransfer"
        yield self.filetransfer


class PreprintTests(unittest.TestCase):
    @staticmethod
    def upload(data, filename="test.gcode"):
        upload = io.BytesIO(data)
        upload.filename = filename
        return upload

    def test_extracts_resolved_temperatures(self):
        data = b"M104 S150\nM190 S55\nM109 S220\nG28\n"
        self.assertEqual(util.extract_preprint_temperatures(data), (55, 220))

    def test_rejects_unresolved_or_unsafe_temperatures(self):
        with self.assertRaisesRegex(ValueError, "could not find M190"):
            util.extract_preprint_temperatures(
                b"M190 S{first_layer_bed_temperature[0]}\nM109 S220\n"
            )
        with self.assertRaisesRegex(ValueError, "unsafe M109"):
            util.extract_preprint_temperatures(b"M190 S55\nM109 S500\n")

    def test_fixture_temperatures_match_live_validation_assets(self):
        self.assertEqual(
            util.extract_preprint_temperatures(
                (FIXTURES / "g36_resolved.gcode").read_bytes()
            ),
            (35, 150),
        )

        with self.assertRaisesRegex(ValueError, "could not find M190"):
            util.extract_preprint_temperatures(
                (FIXTURES / "preprint_unresolved.gcode").read_bytes()
            )

        with self.assertRaisesRegex(ValueError, "unsafe M109"):
            util.extract_preprint_temperatures(
                (FIXTURES / "preprint_unsafe_nozzle.gcode").read_bytes()
            )

    def test_runs_preprint_before_preserving_upload(self):
        client = FakeClient(
            replies=[
                {"commandType": util._GCODE_COMMAND, "reply": 0, "resData": "ok"},
                {"commandType": util._GCODE_COMMAND, "reply": 0, "resData": "ok"},
                {"commandType": util._BED_TEMPERATURE, "currentTemp": 5500},
                {"commandType": util._GCODE_COMMAND, "reply": 0, "resData": "ok"},
                {"commandType": util._NOZZLE_TEMPERATURE, "currentTemp": 22000},
                {"commandType": util._GCODE_COMMAND, "reply": 0, "resData": "ok"},
            ]
        )
        filetransfer = FakeFileTransfer()
        app = SimpleNamespace(
            config={
                "config": object(),
                "printer_index": 0,
                "insecure": False,
                "preprint_command_timeout": 300,
            },
            svc=FakeServiceManager(filetransfer),
        )
        data = b"M190 S55\nM109 S220\nG28\n"

        with patch("web.util.cli.mqtt.mqtt_open", return_value=client):
            util._run_preprint_upload(
                app,
                self.upload(data),
                "OrcaSlicer",
                55,
                220,
            )

        self.assertEqual(
            client.commands,
            [
                "M104 S150",
                "M400",
                "M140 S55",
                "M400",
                "M104 S220",
                "M400",
                "G36",
                "M400",
            ],
        )
        self.assertEqual(filetransfer.data, data)
        self.assertEqual(filetransfer.filename, "test.gcode")
        self.assertEqual(filetransfer.user_name, "OrcaSlicer")

    def test_failure_cools_down_and_does_not_upload(self):
        client = FakeClient(
            replies=[
                {"commandType": util._GCODE_COMMAND, "reply": 0, "resData": "ok"},
                {
                    "commandType": util._GCODE_COMMAND,
                    "reply": 1,
                    "resData": "Error: heating failed",
                },
                {"commandType": util._GCODE_COMMAND, "reply": 0, "resData": "ok"},
                {"commandType": util._GCODE_COMMAND, "reply": 0, "resData": "ok"},
            ]
        )
        filetransfer = FakeFileTransfer()
        app = SimpleNamespace(
            config={
                "config": object(),
                "printer_index": 0,
                "insecure": False,
                "preprint_command_timeout": 300,
            },
            svc=FakeServiceManager(filetransfer),
        )

        with patch("web.util.cli.mqtt.mqtt_open", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "heating failed"):
                util._run_preprint_upload(
                    app,
                    self.upload(b"data"),
                    "OrcaSlicer",
                    55,
                    220,
                )

        self.assertEqual(
            client.commands,
            [
                "M104 S150",
                "M400",
                "M140 S55",
                "M400",
                "M104 S0",
                "M400",
                "M140 S0",
                "M400",
            ],
        )
        self.assertIsNone(filetransfer.data)

    def test_orca_upload_identity_is_preserved_for_job_actions(self):
        filetransfer = FakeFileTransfer()
        remembered = []
        snapshots = SimpleNamespace(
            remember_job=lambda *args: remembered.append(args),
        )
        app = SimpleNamespace(
            config={"preprint_g36": False, "printer_index": 0},
            svc=FakeServiceManager(filetransfer),
            printer_snapshots=snapshots,
        )
        flask = Flask(__name__)

        with flask.test_request_context(headers={"User-Agent": "OrcaSlicer/2.3"}):
            util.upload_file_to_printer(app, self.upload(b"G4 S1\n", "cube 1.gcode"))

        self.assertEqual(filetransfer.user_name, "OrcaSlicer")
        self.assertEqual(
            remembered,
            [("printer-0", "cube_1.gcode", "OrcaSlicer", "slicer_upload")],
        )


if __name__ == "__main__":
    unittest.main()
