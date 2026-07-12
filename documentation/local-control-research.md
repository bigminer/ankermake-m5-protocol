# Local Control Research: Decoupling from Anker

Goal: reclaim full, independent ownership of the AnkerMake M5C — run the printer
**entirely on the local network with Anker's cloud permanently severed**, so it
keeps working regardless of Anker's service status (shutdown, account lockout,
factory reset). This is a full replacement of the cloud, not merely reducing
reliance on it.

The key enabler, established below: `ankerctl` already has **full control
parity** with the official app (both drive the printer over the same MQTT
command set); the only remaining Anker dependency is the cloud *transport*.
So the work is transport redirection, not protocol reverse-engineering. This
document records what is already local, what was tested, and the evidence for
the recommended route — redirect the printer's MQTT to a local broker, with a
USB-UART serial G-code bridge as the guaranteed fallback. The concrete plan is
in [next-step-local-broker.md](next-step-local-broker.md).

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

## Step 2 — Official app LAN capture: control is cloud-MQTT-only (done 2026-07-11)

Question: does the official eufyMake app use any local channel to control the
printer, or does it go through Anker's cloud? If a local control protocol
exists, capturing the app would reveal it.

### Method

The eufyMake app was installed and run on the Mac mini itself, so its printer
traffic originates from this host and a plain `tcpdump` captures it — no
ARP-spoofing/MITM needed. Two operator-driven actions were captured live:
an **extrude** and a full **10-minute auto-level**. During each:

- `tcpdump -i en1 'host <printer> or port 8789'` recorded all Mac↔printer and
  cloud-MQTT traffic (`examples/decode-pppp-pcap.py` decodes the PPPP side).
- `ankerctl mqtt monitor` watched Anker cloud MQTT concurrently.
- `lsof` snapshotted the app process's live sockets.

### Result: the app never touches the printer locally

The app process is `FDMPrint`. Across both actions, including throughout the
10-minute auto-level:

- `lsof` showed `FDMPrint` holding **only** two TCP sockets, both to
  `make-mqtt.ankermake.com` (`166.117.17.78:8789`) — Anker cloud MQTT, the same
  server and port `ankerctl` uses. **Zero** UDP sockets, **zero** connections
  to the printer (`192.168.68.57`).
- The packet capture confirmed it: the only Mac↔printer traffic was
  `ankerctl`'s own PPPP keepalive session. Decoding the extrude-window pcap
  yields **0 application frames** — just 118 `PktAlive`/`PktAliveAck` pairs from
  `ankerctl`. The app contributed no local packets to the printer at all.
- The commands and their telemetry appeared on **cloud MQTT**: the extrude as
  `enter_or_quit_materiel` (0x3ff/1023) progressing 8→100 %, the auto-level as
  `event_notify` state `subType 1 value 5` with a `print_schedule` countdown.
  These are the same MQTT command/notice types `ankerctl` already speaks.

### Interpretation — the strategic pivot

There is **no local control protocol to discover.** The official app drives the
printer entirely through Anker's cloud MQTT, using the command set `ankerctl`
already implements. Locally, PPPP carries only camera/live and file upload.

The useful consequence: `ankerctl` already has **full control parity** with the
official app — it is simply equally cloud-dependent. Decoupling is therefore not
a protocol-reverse-engineering problem; it is a *transport-redirection* problem.
Everything (temps, motion, pause/resume/stop, extrude, leveling, G-code) is
available the moment the printer's MQTT session can be pointed at a broker we
control. That moves **"redirect the printer to a local MQTT broker"** from a
speculative option to the highest-leverage next experiment (see ranking below).

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

## Step 4 — Local broker redirect (in progress)

The plan is in [next-step-local-broker.md](next-step-local-broker.md).

### Phase 0 recon — printer cloud dependencies + DNS behavior (2026-07-11)

Method: half-duplex ARP poisoning of the printer (only its ARP entry for the
gateway spoofed, so it kept full connectivity) + `tcpdump` for 2 min, then ARP
and `sysctl` fully restored. Read-only with respect to the printer — no command
sent. Findings:

- **DNS:** the printer resolves via **`192.168.4.1`** (the eero, handed to it by
  the Deco as a DNS server) over plain **UDP:53** — no DoH. It honors
  DHCP-provided DNS (observed a `www.apple.com` connectivity check). → A DNS
  override is viable: if the printer's resolver answers
  `make-mqtt.ankermake.com` with our broker's IP, it will follow.
- **Outbound cloud connections in the window:**
  - `make-mqtt.ankermake.com:8789` (`166.117.252.238`, AWS Global Accelerator) —
    the persistent MQTT control/telemetry channel. **The redirect target.**
  - `34.223.135.175:32100` — Anker PPPP/P2P **WAN relay** (supernode) for
    cloud-relayed remote access; severable (LAN PPPP is used directly on-net).
  - No NTP (:123) or firmware HTTPS (:443) seen in 2 min — may occur on longer
    intervals; a longer capture would complete the full sever-list.
- The MQTT connection was already established, so no fresh `make-mqtt` DNS lookup
  was captured; but the printer clearly uses DNS and its MQTT peer is a
  `make-mqtt.ankermake.com` Global Accelerator address, so DNS use is
  near-certain. Phase 1 (override) confirms it definitively.

**Gate — next action needs the operator.** Phase 1 points the printer's resolver
at a local `dnsmasq` on the Mac (`192.168.68.55`). Because both the Deco and eero
are app-managed consumer mesh, changing the DNS handed to the printer is done in
the **Deco app** (set custom DNS → `192.168.68.55`), which only the operator can
do. Broker + `dnsmasq` setup on the Mac is automatable; the DNS switch is manual.

## Confidence ranking (updated with evidence)

| Approach | Status | Risk |
| --- | --- | --- |
| PPPP-only control by reusing MQTT command types | **Disproven** (Step 3 probe) | Low |
| Discover a local control sub-protocol via official-app LAN capture | **Disproven** (Step 2: app is cloud-MQTT-only) | Low |
| Redirect printer to a local MQTT broker | **Now the highest-leverage path** — ankerctl already has full control parity over MQTT; only the transport is cloud-bound. Feasibility hinges on the printer's TLS trust (test next). | Medium-high |
| PPPP + stock-Marlin serial bridge (USB-UART sidecar) | Strongest *guaranteed* durable path; needs hardware | Medium |
| Replace firmware (Klipper / custom Marlin) | Feasible, least mature | High |

The two "reverse-engineer a local protocol" ideas are both closed off: there is
no hidden local control channel (Step 2), and the generic PPPP JSON endpoint
does not serve maker commands (Step 3). The remaining paths all keep the
existing MQTT command set and change *where* the printer's MQTT session
terminates (local broker) or *how* G-code reaches Marlin (serial bridge).

## Recommended next steps

1. **Test whether the printer will accept a redirected MQTT broker.** This is
   now the pivotal experiment. The printer connects outbound to
   `make-mqtt.ankermake.com:8789` over TLS. On a network where we control DNS
   (the printer's LAN), override that name to a local broker and observe what
   the printer requires:
   - Does it validate the server certificate against Anker's CA / hostname, or
     connect loosely? Stand up a local MQTT broker on `:8789`, first with the
     existing `ssl/ankermake-mqtt.crt` chain, and watch whether the printer
     completes the TLS handshake and subscribes to `/device/maker/<sn>/command`.
   - If TLS is strict and needs Anker's private key (we don't have it), the
     redirect requires firmware root to install our own CA — escalate to the
     serial bridge instead. If the printer is lax, this yields full local
     control with the command set `ankerctl` already implements.
   - Do this read-only first: a broker that only logs subscribe/connect
     attempts, before it ever publishes a command.

2. **Decouple the app from MQTT behind a `PrinterTransport` interface**
   (commands, queries, events, uploads) so the UI consumes normalized printer
   state instead of `/ws/mqtt` directly, and add manual/local config so an
   Anker account is not required to run. The cloud `AnkerMQTTClient` becomes one
   implementation; a local broker (step 1) or serial bridge (step 3) slots in
   behind the same interface. Useful under every route.

3. **Prototype the serial G-code bridge** as the guaranteed-durable fallback if
   the broker redirect proves infeasible. The official M5C Marlin source
   implements `M2022`/`M2023`/`M2024` and Anker's packet framing between the
   Linux board and Marlin. A Pi/ESP32/USB-UART sidecar could send G-code to
   stock Marlin, poll `M105`/`M114`/status, and expose a local HTTP/WebSocket
   (or local MQTT) API. Passively identify the UART with a logic analyzer first;
   never drive the same UART from two devices at once.

## Reproducing the probes

### Step 2 — capture the official app (app runs on the same host)

```sh
# app process is FDMPrint; confirm where it connects (expect only cloud MQTT)
lsof -nP -p "$(pgrep -x FDMPrint)" | grep -E 'TCP|UDP'

# capture Mac<->printer and cloud MQTT while operating the app
sudo tcpdump -i en1 -s0 -U -w /tmp/app.pcap 'host <printer-ip> or port 8789'
.venv/bin/python ankerctl.py mqtt monitor        # concurrent cloud view

# decode the local PPPP side (expect 0 application frames from the app)
.venv/bin/python examples/decode-pppp-pcap.py /tmp/app.pcap --printer <printer-ip>
```

### Step 3 — read-only PPPP JSON probe

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
