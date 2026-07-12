import json
import struct
import importlib.util
import unittest
from pathlib import Path

from libflagship.pppp import PktDrw, Xzyh, P2PCmdType


# The decoder ships as a script under examples/; load it as a module.
_SPEC = importlib.util.spec_from_file_location(
    "decode_pppp_pcap",
    Path(__file__).resolve().parent.parent / "examples" / "decode-pppp-pcap.py",
)
decode = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(decode)


def _xzyh_json(obj):
    payload = json.dumps(obj).encode()
    return Xzyh(cmd=P2PCmdType.P2P_JSON_CMD, len=len(payload), data=payload,
               chan=0, unk0=0, unk1=0, sign_code=0, unk3=0, dev_type=0).pack()


def _udp(src, sport, dst, dport, payload):
    def ip4(s):
        return bytes(int(o) for o in s.split("."))
    udp = struct.pack(">HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = (bytes([0x45, 0, 0, 0, 0, 0, 0, 0, 64, 17, 0, 0]) + ip4(src) + ip4(dst))
    eth = b"\x00" * 6 + b"\x00" * 6 + struct.pack(">H", 0x0800)
    return eth + ip + udp


def _write_pcap(path, frames):
    with open(path, "wb") as fd:
        fd.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        for frame in frames:
            fd.write(struct.pack("<IIII", 0, 0, len(frame), len(frame)))
            fd.write(frame)


class DecodePpppPcapTests(unittest.TestCase):
    def test_parse_stream_extracts_json(self):
        buf = _xzyh_json({"commandType": 1013, "cmdData": "G28"})
        frames = decode.parse_stream(buf)

        self.assertEqual(len(frames), 1)
        kind, hdr, data = frames[0]
        self.assertEqual(kind, "XZYH")
        self.assertEqual(json.loads(data), {"commandType": 1013, "cmdData": "G28"})

    def test_parse_udp_reads_pppp_ports(self):
        frame = _udp("192.168.68.55", 40000, "192.168.68.57", 32108, b"\xf1\x30\x00\x00")
        src, sport, dst, dport, payload = decode.parse_udp(frame, 1)

        self.assertEqual((src, dst, dport), ("192.168.68.55", "192.168.68.57", 32108))
        self.assertEqual(payload[0], 0xF1)

    def test_full_pcap_decode_end_to_end(self):
        # a JSON command wrapped in a DRW, on an ephemeral (migrated) port
        drw = PktDrw(chan=0, index=0, data=_xzyh_json({"commandType": 1027})).pack()
        frame = _udp("192.168.68.55", 55000, "192.168.68.57", 15181, drw)

        pcap = Path(self._out())
        _write_pcap(pcap, [frame])

        # iter_pcap + parse_udp + reassembly path, mirroring main()
        from collections import defaultdict
        streams = defaultdict(dict)
        for _ts, lt, fr in decode.iter_pcap(str(pcap)):
            s, sp, d, dp, pl = decode.parse_udp(fr, lt)
            if pl[0] != 0xF1:
                continue
            from libflagship.pppp import Message, Type
            m = Message.parse(pl)[0]
            if m.type == Type.DRW:
                streams[(s, d, m.chan)][m.index] = m.data

        found = []
        for key, idxmap in streams.items():
            buf = b"".join(idxmap[i] for i in sorted(idxmap))
            found += decode.parse_stream(buf)

        self.assertEqual(len(found), 1)
        self.assertEqual(json.loads(found[0][2]), {"commandType": 1027})

    def _out(self):
        import tempfile
        fd = tempfile.NamedTemporaryFile(suffix=".pcap", delete=False)
        fd.close()
        return fd.name


if __name__ == "__main__":
    unittest.main()
