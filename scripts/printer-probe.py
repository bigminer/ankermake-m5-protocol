#!/usr/bin/env python3
"""Read-first diagnostic CLI for the M5C, over the running ankerctl service.

Why this exists: the printer answers far more than the web UI asks, and every
session was re-deriving the payload shape, the reply routing, and the auth dance
from scratch. See documentation/printer-findings.md for what each command is
known to do, with evidence and dates.

Usage:
    scripts/printer-probe.py pos                 # M114 - position + stepper counts
    scripts/printer-probe.py endstops            # M119 + M851
    scripts/printer-probe.py status              # APP_QUERY_STATUS (1027) burst
    scripts/printer-probe.py watch [seconds]     # poll M114, print changes
    scripts/printer-probe.py gcode "M105"        # send arbitrary g-code

All subcommands except `gcode` are reads: no motion, no heat, no job control.
`gcode` can move the printer -- CLAUDE.md requires operator confirmation.
Known-dangerous commands are refused; see DANGEROUS below.
"""
import json
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

try:
    import websocket  # websocket-client
except ImportError:
    sys.exit("need websocket-client: .venv/bin/pip install websocket-client")

BASE = "http://127.0.0.1:4470"
WS = "ws://127.0.0.1:4470"
PLIST = "~/Library/LaunchAgents/com.ankerctl.webserver.plist"

GCODE = 1043      # 0x0413 ZZ_MQTT_CMD_GCODE_COMMAND
QUERY = 1027      # 0x0403 ZZ_MQTT_CMD_APP_QUERY_STATUS
TEMP_NOISE = {1003, 1004}

# Refused outright. Each drove this printer into the plate, wedged its queue, or
# would wipe its config. documentation/printer-findings.md has the incident record.
DANGEROUS = [
    (re.compile(r"^\s*(N\d+\s*)?G28(?!\s*[XY\s]*$)", re.I), "G28 with Z drives the nozzle into the plate"),
    (re.compile(r"^\s*(N\d+\s*)?G28\s*$", re.I), "bare G28 homes Z and drives the nozzle into the plate"),
    (re.compile(r"^\s*(N\d+\s*)?G36\b", re.I), "G36 wedges the command queue (needs a power cycle)"),
    (re.compile(r"^\s*(N\d+\s*)?M402\b", re.I), "M402 is untested and may lower Z ~15mm (M401 lifted it)"),
]

POS_RE = re.compile(r"X:(-?[\d.]+)\s+Y:(-?[\d.]+)\s+Z:(-?[\d.]+).*?"
                    r"Count X:(-?\d+)\s+Y:(-?\d+)\s+Z:(-?\d+)", re.S)


def auth():
    """Token lives in the LaunchAgent, not .env. Never printed."""
    tok = subprocess.run(
        ["plutil", "-extract", "EnvironmentVariables.ANKERCTL_TOKEN", "raw", "-o", "-",
         __import__("os").path.expanduser(PLIST)],
        capture_output=True, text=True,
    ).stdout.strip()
    if not tok:
        sys.exit(f"could not read ANKERCTL_TOKEN from {PLIST}")
    cj = urllib.request.HTTPCookieProcessor()
    urllib.request.build_opener(cj).open(
        f"{BASE}/login", urllib.parse.urlencode({"token": tok}).encode())
    return [f"Cookie: " + "; ".join(f"{c.name}={c.value}" for c in cj.cookiejar)]


class Printer:
    def __init__(self):
        self.hdr = auth()

    def send(self, mqtt):
        ws = websocket.create_connection(f"{WS}/ws/ctrl", header=self.hdr, timeout=10)
        ws.send(json.dumps({"mqtt": mqtt, "awaitResponse": False, "requestId": "probe"}))
        ws.close()
        # NOTE: /ws/ctrl answers {"ankerctl":1} -- that is NOT the printer.
        # The real reply lands on /ws/mqtt.

    def collect(self, seconds, keep):
        """Gather /ws/mqtt messages matching keep(obj) for `seconds`."""
        got = []
        ws = websocket.create_connection(f"{WS}/ws/mqtt", header=self.hdr, timeout=seconds + 2)
        end = time.time() + seconds
        while time.time() < end:
            try:
                ws.settimeout(max(0.3, end - time.time()))
                obj = json.loads(ws.recv())
            except Exception:
                break
            if keep(obj):
                got.append(obj)
        ws.close()
        return got

    def gcode(self, line, seconds=8):
        """Send a g-code line, return non-temperature replies."""
        out = []
        t = threading.Thread(
            target=lambda: out.extend(self.collect(
                seconds,
                lambda o: o.get("commandType") == GCODE
                and not str(o.get("resData", "")).startswith("ok T:"))))
        t.start()
        time.sleep(1.2)
        self.send({"commandType": GCODE, "cmdData": line, "cmdLen": len(line)})
        t.join()
        return [str(o.get("resData", "")) for o in out]


def cmd_pos(p):
    for r in p.gcode("M114"):
        m = POS_RE.search(r)
        if m:
            print(f"X:{m.group(1)}  Y:{m.group(2)}  Z:{m.group(3)}")
            print(f"count  X:{m.group(4)}  Y:{m.group(5)}  Z:{m.group(6)}")
            print(f"\n(Z is 400 steps/mm. Reported Z is NOT stable across commands -- "
                  f"track the count. See printer-findings.md.)")
            return
    print("no position reply -- is the printer connected? it needs 30-60s after a power cycle.")


def cmd_endstops(p):
    for line in p.gcode("M119"):
        print(line.strip())
    print()
    for line in p.gcode("M851"):
        print(line.strip())
    print("\n⚠️  M119 cannot see StallGuard. SENSORLESS_HOMING is enabled; if Z detection\n"
          "   is stall-based it only registers DURING MOTION. 'z_probe: open' on a\n"
          "   stationary nozzle proves nothing -- even pressed into the plate.")


def cmd_status(p):
    out = []
    t = threading.Thread(target=lambda: out.extend(p.collect(
        10, lambda o: o.get("commandType") not in TEMP_NOISE)))
    t.start()
    time.sleep(1.2)
    p.send({"commandType": QUERY})
    t.join()
    seen = {}
    for o in out:
        if o.get("commandType") != GCODE:
            seen.setdefault(o.get("commandType"), o)
    for ct, o in sorted(seen.items(), key=lambda kv: (kv[0] is None, kv[0])):
        note = {1039: "  <- breakPoint:1 = SUSPENDED PRINT (long-press the button to clear)",
                1072: "  <- isLeveled",
                1052: "  <- layers"}.get(ct, "")
        print(f"{ct:>5}: {json.dumps(o)}{note}")
    if not seen:
        print("nothing came back -- printer may not be connected yet.")


def cmd_watch(p, seconds=120):
    print(f"{'time':>8} {'Z (mm)':>9} {'count':>8} {'delta':>7}")
    prev = None
    end = time.time() + seconds
    while time.time() < end:
        for r in p.gcode("M114", seconds=3):
            m = POS_RE.search(r)
            if not m:
                continue
            z, cnt = float(m.group(3)), int(m.group(6))
            if z != prev:
                d = "" if prev is None else f"{z - prev:+.2f}"
                print(f"{time.strftime('%H:%M:%S'):>8} {z:>9.2f} {cnt:>8} {d:>7}", flush=True)
                prev = z
            break


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    action = sys.argv[1]
    p = Printer()
    if action == "pos":
        cmd_pos(p)
    elif action == "endstops":
        cmd_endstops(p)
    elif action == "status":
        cmd_status(p)
    elif action == "watch":
        cmd_watch(p, int(sys.argv[2]) if len(sys.argv) > 2 else 120)
    elif action == "gcode":
        if len(sys.argv) < 3:
            sys.exit('usage: printer-probe.py gcode "M105"')
        line = sys.argv[2]
        for pat, why in DANGEROUS:
            if pat.search(line):
                sys.exit(f"refused: {why}\nsee documentation/printer-findings.md")
        for r in p.gcode(line):
            print(r.strip())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
