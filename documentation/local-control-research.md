# Local Control Research: Decoupling from Anker

Goal: reduce this application's dependence on Anker's cloud (account,
HTTPS, MQTT hosts) so the printer keeps working after an Anker shutdown or
factory reset. This document records what is already local, what was tested,
and the evidence for the recommended route.

## Current boundary (what is already local vs. cloud)

Already local, over PPPP on the LAN:

- Printer discovery and direct connection (`cli/pppp.py`, `web/service/pppp.py`).
- Print-file upload and print start (`web/service/filetransfer.py`,
  `cli/pppp.py:pppp_send_file`).
- Camera, light, and video quality (`web/service/video.py`), which use the
  `P2PSubCmdType` maker sub-command namespace inside a live session.

Still dependent on Anker cloud MQTT (`make-mqtt.ankermake.com`):

- Temperatures, progress, printer state (telemetry pushed to
  `/phone/maker/<sn>/notice`).
- Pause / resume / stop, jogging, fan, raw G-code (sent to
  `/device/maker/<sn>/command`).
- Initial account / printer provisioning (auth token, MQTT credentials,
  MQTT key, P2P DUID/DSK) via `cli/config.py:load_config_from_api`.

## Step 1 — Preserve provisioning data (done 2026-07-11)

A fresh setup after an Anker shutdown or factory reset is likely much harder
than keeping an already-provisioned printer working, so the live device data
was backed up first:

```
~/Library/Application Support/ankerctl/backups/2026-07-11/
  default.json   # account auth token, MQTT creds+key, SN, P2P DUID, DSK, hosts, cached IP
  com.ankerctl.webserver.plist  # web UI token, Flask secret
  README.txt
```

Directory and files are `0700`/`0600`. `default.json` in the live config
directory was also re-chmod'd to `0600`. Keep this backup offline; it contains
credentials and must never be committed. Restore per
[local-macos-service.md](local-macos-service.md).

## Step 3 — Read-only PPPP control/telemetry probe (done 2026-07-11)

Question: can control and telemetry be driven over the existing local PPPP
JSON channel (`P2P_JSON_CMD` = `0x06a4`), the same transport already used for
camera and uploads, instead of Anker MQTT?

### Method

Added a research command, `ankerctl pppp query <cmd> [key=value...]`
(`ankerctl.py`, helper `cli/pppp.py:pppp_listen`). It opens a LAN PPPP session,
sends one JSON `{"commandType": <cmd>, ...}` over `P2P_JSON_CMD`, and decodes
all channel traffic (XZYH / AABB / raw) for a listen window.

The printer was confirmed idle first (`ankerctl mqtt monitor`: only
`nozzle_temp`/`hotbed_temp` at target 0). The local `ankerctl` webserver
service was stopped during probing so it did not compete for the PPPP session.
A second process (`ankerctl mqtt monitor`) watched Anker cloud MQTT
concurrently, to detect whether any local command produced a cloud-visible
side effect.

Commands probed (all read-only): `FIRMWARE_VERSION` (1002), `LIGHT_STATE_GET`
/ `HOTBED_TEMP` id collision (1004), `APP_QUERY_STATUS` (1027), and an invalid
control (`60000`).

### Result: PPPP JSON control is not served for maker command types

- Local delivery works and is cloud-free. Every send got a PPPP transport ACK,
  and the printer replied on channel 0 — with the local `ankerctl` webserver
  stopped and no cloud round-trip involved.
- The reply is **not** a per-command answer. For every commandType — valid MQTT
  types, the video-namespace `LIGHT_STATE_GET`, and the invalid `60000` alike —
  the printer returned an identical fixed payload: `MAKER_SET_PAYLOAD`
  (`0x06a4`), length 36, all zero bytes, ~3 frames at ~1/s.
- Control discriminator: sending nothing and listening for 12 s yielded **0**
  frames; sending *any* JSON yielded the same 3 zero frames. So the zero-frame
  burst is a generic "maker payload" heartbeat emitted when the channel is
  written, carrying no telemetry — not a response to the query.
- No cloud side effects: across connect-only vs. send-command runs, the
  concurrent cloud MQTT stream showed the same background `nozzle_temp` /
  `hotbed_temp` notices and no extra events. The local commands neither
  reached Marlin nor were bridged to the cloud.

Raw evidence (probe of commandType 1027):

```
TX chan0 XZYH cmd=0x06a4 len=21 payload={"commandType": 1027}
RX chan0 XZYH cmd=0x06a4 len=36 payload=0000...0000   (36 zero bytes)
RX chan0 XZYH cmd=0x06a4 len=36 payload=0000...0000
RX chan0 XZYH cmd=0x06a4 len=36 payload=0000...0000
```

### Interpretation

The M5C's Linux "upper computer" bridges Anker MQTT to the Marlin MCU and owns
job execution (consistent with the pause/stop findings in
[printer-test-validation.md](printer-test-validation.md)). The LAN
`P2P_JSON_CMD` endpoint only meaningfully implements the camera/live
sub-command set (`P2PSubCmdType`: `START_LIVE`, `LIGHT_STATE_*`,
`LIVE_MODE_*`), and even those the app drives inside an active live session.
General maker control and telemetry (temps, motion, pause/resume/stop, G-code)
are **not** exposed as queryable PPPP commands. Reusing the MQTT command
namespace over PPPP does not work.

Caveat: the probes sent bare `{"commandType": N}` envelopes (matching how
`ankerctl mqtt send` builds commands), not the fuller app envelope with a
`data` object. The discriminator (identical reply for an invalid command)
shows the endpoint is not parsing the command at all, so a richer envelope is
unlikely to change the maker-command result — but it was not exhaustively
tested. What is proven: the naive "tunnel MQTT commandTypes over PPPP" path is
a dead end.

## Confidence ranking (updated with evidence)

| Approach | Status | Risk |
| --- | --- | --- |
| PPPP-only control by reusing MQTT command types | **Disproven** (this probe) | Low |
| Discover a real local control sub-protocol via official-app LAN capture | Unproven; next cheapest experiment | Low |
| PPPP + stock-Marlin serial bridge (USB-UART sidecar) | Strongest durable path | Medium |
| Redirect printer to a local MQTT broker | Low confidence without Linux root | Medium-high |
| Replace firmware (Klipper / custom Marlin) | Feasible, least mature | High |

## Recommended next steps

1. **Decouple the app from MQTT regardless of transport.** Introduce a
   `PrinterTransport` interface (commands, queries, events, uploads) and have
   the UI consume normalized printer state instead of `/ws/mqtt` directly. MQTT
   becomes one implementation. Add manual/local config so an Anker account is
   not required to run. This is useful under every route below and does not
   depend on the probe outcome.

2. **Capture the official eufyMake app's LOCAL (LAN) traffic** to the printer
   during pause/resume/stop and a temperature change. If the app sends control
   only to Anker's cloud MQTT (likely), that confirms there is no hidden local
   control channel and the serial bridge is required. If it uses a PPPP
   sub-protocol we have not mapped, capture the exact framing.

3. **Prototype the serial G-code bridge** (Codex's strongest-durable path). The
   official M5C Marlin source implements `M2022`/`M2023`/`M2024` and Anker's
   packet framing between the Linux board and Marlin. A Pi/ESP32/USB-UART
   sidecar could send G-code to stock Marlin, poll `M105`/`M114`/status, and
   expose a local HTTP/WebSocket (or local MQTT) API. Passively identify the
   UART with a logic analyzer first; never drive the same UART from two devices
   at once.

## Reproducing the probe

```sh
# confirm printer idle
.venv/bin/python ankerctl.py mqtt monitor        # expect only temp notices

# stop the webserver so it does not hold the PPPP session
launchctl unload ~/Library/LaunchAgents/com.ankerctl.webserver.plist

# probe (read-only). --pppp-dump captures raw packets for later decode.
.venv/bin/python ankerctl.py --pppp-dump /tmp/probe.dump \
  pppp query APP_QUERY_STATUS --listen 10

# restore the service and confirm health
launchctl load -w ~/Library/LaunchAgents/com.ankerctl.webserver.plist
curl -I http://127.0.0.1:4470/                    # expect 302 -> /login
```

Between probes, allow ~20 s: the printer refuses a new PPPP session
(`ConnectionRefusedError`) if sessions are cycled too quickly.
