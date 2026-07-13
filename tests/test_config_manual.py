import contextlib
import tempfile
import unittest
from pathlib import Path

import cli.mqtt
from cli.config import build_manual_config, AnkerConfigManager
from cli.model import Config, Account, Printer


class _FakeDirs:
    def __init__(self, root):
        self.user_config_path = Path(root)


class _MemConfig:
    """Minimal config manager exposing .open() for mqtt_transport."""
    def __init__(self, cfg):
        self._cfg = cfg

    @contextlib.contextmanager
    def open(self):
        yield self._cfg


def _full():
    return build_manual_config(
        sn="AK0001", mqtt_key="a1b2c3", user_id="uid42", email="me@example.com",
        region="us", name="Garage M5C", model="M5C", ip_addr="192.168.2.2",
        p2p_duid="DUID-1", p2p_key="DSK-1",
    )


class BuildManualConfigTests(unittest.TestCase):

    def test_account_fields_and_derived_mqtt_creds(self):
        cfg = _full()
        self.assertEqual(cfg.account.user_id, "uid42")
        self.assertEqual(cfg.account.email, "me@example.com")
        self.assertEqual(cfg.account.region, "us")
        self.assertEqual(cfg.account.auth_token, "")
        # username/password derive from user_id/email (no API involved)
        self.assertEqual(cfg.account.mqtt_username, "eufy_uid42")
        self.assertEqual(cfg.account.mqtt_password, "me@example.com")

    def test_printer_fields_and_hex_key(self):
        cfg = _full()
        p = cfg.printers[0]
        self.assertEqual(p.sn, "AK0001")
        self.assertEqual(p.name, "Garage M5C")
        self.assertEqual(p.mqtt_key, b"\xa1\xb2\xc3")  # hex decoded
        self.assertEqual(p.ip_addr, "192.168.2.2")
        self.assertEqual(p.p2p_duid, "DUID-1")
        self.assertEqual(p.p2p_key, "DSK-1")

    def test_mqtt_only_defaults_leave_pppp_fields_empty(self):
        cfg = build_manual_config(sn="SN", mqtt_key="00", user_id="u", email="e@x")
        p = cfg.printers[0]
        self.assertEqual(p.ip_addr, "")
        self.assertEqual(p.p2p_duid, "")
        self.assertEqual(p.p2p_key, "")
        self.assertEqual(p.name, "printer")

    def test_invalid_region_rejected(self):
        with self.assertRaises(ValueError):
            build_manual_config(sn="SN", mqtt_key="00", user_id="u", email="e@x", region="zz")

    def test_save_load_roundtrip(self):
        cfg = _full()
        with tempfile.TemporaryDirectory() as d:
            mgr = AnkerConfigManager(_FakeDirs(d), classes=(Config, Account, Printer))
            mgr.save("default", cfg)
            # written 0600 (holds secrets)
            self.assertEqual(mgr.config_path("default").stat().st_mode & 0o777, 0o600)
            with mgr.open() as loaded:
                self.assertEqual(loaded.account.mqtt_username, "eufy_uid42")
                self.assertEqual(loaded.printers[0].sn, "AK0001")
                self.assertEqual(loaded.printers[0].mqtt_key, b"\xa1\xb2\xc3")


class ManualConfigDrivesTransportTests(unittest.TestCase):
    """The manual config is usable by the transport layer with no Anker API."""

    def test_mqtt_transport_built_from_manual_config(self):
        cfg = _full()
        transport = cli.mqtt.mqtt_transport(_MemConfig(cfg), 0, insecure=True)
        # transport carries the right destination + creds, unconnected
        self.assertEqual(transport._server, "make-mqtt.ankermake.com")
        self.assertEqual(transport._printersn, "AK0001")
        self.assertEqual(transport._username, "eufy_uid42")
        self.assertEqual(transport._password, "me@example.com")
        self.assertEqual(transport._key, b"\xa1\xb2\xc3")
        self.assertIsNone(transport.client)  # not connected, no network touched


if __name__ == "__main__":
    unittest.main()
