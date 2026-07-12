import json
import unittest

import cli.pppp

from libflagship.pppp import Xzyh, P2PCmdType
from libflagship.ppppapi import Channel


class _FakeApi:
    """Minimal stand-in exposing the .chans list pppp_listen reads from."""

    def __init__(self, nchans=8):
        self.chans = [Channel(n) for n in range(nchans)]


def _xzyh_bytes(payload, cmd=P2PCmdType.P2P_JSON_CMD, chan=0):
    return Xzyh(cmd=cmd, len=len(payload), data=payload, chan=chan,
               unk0=0, unk1=0, sign_code=0, unk3=0, dev_type=0).pack()


class PpppListenTests(unittest.TestCase):
    def test_returns_zero_without_traffic(self):
        api = _FakeApi()

        self.assertEqual(cli.pppp.pppp_listen(api, duration=0.1), 0)

    def test_decodes_a_json_xzyh_frame(self):
        api = _FakeApi()
        payload = json.dumps({"commandType": 1027}).encode()
        api.chans[0].rx.write(_xzyh_bytes(payload))

        with self.assertLogs(level="INFO") as logs:
            frames = cli.pppp.pppp_listen(api, duration=0.3)

        self.assertEqual(frames, 1)
        joined = "\n".join(logs.output)
        self.assertIn("chan0 XZYH", joined)
        self.assertIn("1027", joined)

    def test_consumes_frame_so_it_is_not_recounted(self):
        api = _FakeApi()
        api.chans[0].rx.write(_xzyh_bytes(b"{}"))

        # a single frame must be read exactly once even across many poll passes
        self.assertEqual(cli.pppp.pppp_listen(api, duration=0.3), 1)


if __name__ == "__main__":
    unittest.main()
