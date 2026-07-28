#!/usr/bin/env python3
"""Passively record the printer's MQTT stream to JSONL. Sends nothing.

Why this exists: the most valuable printer evidence this project has came from
watching a normal print rather than from commanding anything. Sessions kept
rewriting a throwaway collector; this is the durable one.

    scripts/capture-mqtt.py out.jsonl [seconds]      # default 900

Read-only. It opens `/ws/mqtt` and writes what arrives. It never publishes, so
it needs no operator-presence confirmation under CLAUDE.md -- but if you are
capturing *during* a print, the print itself does, and the operator starts it.

Each line is the message as delivered, plus:
    _t      seconds since capture start
    _wall   local HH:MM:SS
    _event  collector lifecycle only, not printer data

Reconnects on drop, so a capture survives a broker blip. Recorded output is
primary evidence -- see documentation/captures/README.md, and redact job
identifiers before committing any of it.
"""
import importlib.util
import json
import os
import sys
import time

_PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "printer-probe.py")
_spec = importlib.util.spec_from_file_location("printer_probe", _PROBE)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

try:
    import websocket  # websocket-client
except ImportError:
    sys.exit("need websocket-client: .venv/bin/pip install websocket-client")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out_path = sys.argv[1]
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 900

    printer = probe.Printer()
    started = time.time()
    count = 0

    with open(out_path, "w", buffering=1) as fh:
        def record(obj):
            obj["_t"] = round(time.time() - started, 3)
            obj["_wall"] = time.strftime("%H:%M:%S")
            fh.write(json.dumps(obj) + "\n")

        while time.time() - started < seconds:
            try:
                ws = websocket.create_connection(
                    f"{probe.WS}/ws/mqtt", header=printer.hdr, timeout=30
                )
            except Exception as exc:
                record({"_event": "connect_failed", "err": str(exc)})
                time.sleep(2)
                continue

            record({"_event": "connected"})
            while time.time() - started < seconds:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as exc:
                    record({"_event": "recv_failed", "err": str(exc)})
                    break
                try:
                    obj = json.loads(raw)
                except Exception:
                    obj = {"_raw": str(raw)[:2000]}
                record(obj)
                count += 1
            try:
                ws.close()
            except Exception:
                pass

    print(f"captured {count} messages over {int(time.time() - started)}s -> {out_path}")


if __name__ == "__main__":
    main()
