#!/usr/bin/env python3
"""
Decode PPPP traffic from a pcap capture.

Reads a classic pcap file (as written by `tcpdump -w`), extracts the UDP PPPP
payloads (ports 32100 / 32108), reassembles the per-channel XZYH/AABB byte
streams in each direction, and prints the decoded frames -- most usefully the
JSON `commandType` messages the official app exchanges with the printer.

Usage:
    python3 examples/decode-pppp-pcap.py capture.pcap [--printer 192.168.1.50]

This is a research tool for mapping which commands the official eufyMake app
sends locally vs. through Anker's cloud. Point tcpdump at the traffic first:

    sudo tcpdump -i en1 -w capture.pcap \\
        '(udp port 32108 or udp port 32100) and host 192.168.1.50'
"""

import sys
import struct
import json
import argparse
from collections import defaultdict

sys.path.append(".")   # nopep8 -- allow running from the repo root
sys.path.append("..")  # nopep8 -- or from examples/

from libflagship.pppp import Message, Type, Xzyh, Aabb, P2PCmdType


def iter_pcap(path):
    """Yield (ts, linktype, frame_bytes) for each record in a classic pcap."""
    with open(path, "rb") as fd:
        hdr = fd.read(24)
        if len(hdr) < 24:
            raise ValueError("File too short to be a pcap")

        magic = hdr[:4]
        if magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
            endian = ">"
        elif magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
            endian = "<"
        else:
            raise ValueError(
                f"Unsupported pcap magic {magic.hex()} "
                "(pcapng is not supported; capture with classic 'tcpdump -w')"
            )

        linktype = struct.unpack(endian + "I", hdr[20:24])[0]

        while True:
            rec = fd.read(16)
            if len(rec) < 16:
                return
            ts_sec, ts_usec, incl_len, _orig = struct.unpack(endian + "IIII", rec)
            data = fd.read(incl_len)
            if len(data) < incl_len:
                return
            yield ts_sec + ts_usec / 1e6, linktype, data


def parse_udp(frame, linktype):
    """Return (src_ip, sport, dst_ip, dport, payload) for a UDP frame, else None."""
    if linktype == 1:            # DLT_EN10MB (Ethernet)
        if len(frame) < 14:
            return None
        etype = struct.unpack(">H", frame[12:14])[0]
        off = 14
        if etype == 0x8100:      # 802.1Q VLAN tag
            etype = struct.unpack(">H", frame[16:18])[0]
            off = 18
        if etype != 0x0800:      # IPv4 only
            return None
    elif linktype in (0, 8):     # DLT_NULL / DLT_LOOP (BSD loopback)
        off = 4
    else:
        return None

    ip = frame[off:]
    if len(ip) < 20 or (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ip[9] != 17:              # protocol must be UDP
        return None
    src_ip = ".".join(str(b) for b in ip[12:16])
    dst_ip = ".".join(str(b) for b in ip[16:20])

    udp = ip[ihl:]
    if len(udp) < 8:
        return None
    sport, dport, ulen = struct.unpack(">HHH", udp[:6])
    return src_ip, sport, dst_ip, dport, udp[8:ulen]


def parse_stream(buf):
    """Parse a reassembled channel byte stream into XZYH / AABB frames."""
    frames = []
    p = buf
    while len(p) >= 4:
        if p[:4] == b"XZYH":
            if len(p) < 16:
                break
            x = Xzyh.parse(p[:16])[0]
            if len(p) < 16 + x.len:
                break            # frame continues in a packet we did not capture
            frames.append(("XZYH", x, p[16:16 + x.len]))
            p = p[16 + x.len:]
        elif p[:2] == b"\xaa\xbb":
            if len(p) < 12:
                break
            a = Aabb.parse(p[:12])[0]
            if len(p) < 12 + a.len + 2:
                break
            frames.append(("AABB", a, p[12:12 + a.len]))
            p = p[12 + a.len + 2:]
        else:
            p = p[1:]            # resync on garbage (should not happen when aligned)
    return frames


def _fmt_xzyh(x, data):
    try:
        cmd = P2PCmdType(x.cmd).name
    except ValueError:
        cmd = f"0x{x.cmd:04x}"
    try:
        body = json.dumps(json.loads(data.decode()))
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = data[:512].hex()
    return f"XZYH cmd={cmd} len={x.len} data={body}"


def main():
    ap = argparse.ArgumentParser(description="Decode PPPP traffic from a pcap")
    ap.add_argument("pcap")
    ap.add_argument("--printer", help="Printer IP, to label direction", default=None)
    args = ap.parse_args()

    # Reassemble each channel's byte stream per direction. Key: (src, dst, chan).
    # DRW indices dedupe retransmits; sorting restores stream order.
    streams = defaultdict(dict)          # key -> {index: data}
    first_ts = {}                        # key -> earliest timestamp seen
    control_counts = defaultdict(int)    # non-DRW PPPP message types

    for ts, linktype, frame in iter_pcap(args.pcap):
        parsed = parse_udp(frame, linktype)
        if not parsed:
            continue
        src_ip, sport, dst_ip, dport, payload = parsed

        # Restrict to the printer if asked. A PPPP session starts on port
        # 32100/32108 but migrates to an ephemeral printer port, so identify
        # PPPP by its 0xf1 magic byte rather than by port.
        if args.printer and args.printer not in (src_ip, dst_ip):
            continue
        if not payload or payload[0] != 0xF1:
            continue
        try:
            msg = Message.parse(payload)[0]
        except Exception:
            continue

        if getattr(msg, "type", None) == Type.DRW:
            key = (src_ip, dst_ip, msg.chan)
            streams[key].setdefault(msg.index, msg.data)
            first_ts.setdefault(key, ts)
        else:
            control_counts[type(msg).__name__] += 1

    def direction(src, dst):
        if args.printer and dst == args.printer:
            return "app->printer"
        if args.printer and src == args.printer:
            return "printer->app"
        return f"{src}->{dst}"

    results = []
    for (src, dst, chan), idxmap in streams.items():
        buf = b"".join(idxmap[i] for i in sorted(idxmap))
        for kind, hdr, data in parse_stream(buf):
            if kind == "XZYH":
                text = _fmt_xzyh(hdr, data)
            else:
                text = f"AABB frametype={hdr.frametype} sn={hdr.sn} len={hdr.len} data={data[:64].hex()}"
            results.append((first_ts[(src, dst, chan)], direction(src, dst), chan, text))

    results.sort(key=lambda r: r[0])
    for ts, dirn, chan, text in results:
        print(f"[{dirn:14}] chan{chan} {text}")

    print("\n-- summary --", file=sys.stderr)
    print(f"application frames decoded: {len(results)}", file=sys.stderr)
    for name, n in sorted(control_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
