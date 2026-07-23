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

### System communication flow (current)

Every control path exits to Anker's cloud MQTT and comes back down to the
printer — no client on the LAN drives the printer directly. Verified by `lsof`
during a live OrcaSlicer print (2026-07-12): Orca holds **no** socket to the
printer; it hands the job to `ankerctl` on `localhost:4470`, and `ankerctl`'s
only outbound printer link is to `166.117.17.78:8789`
(`awsglobalaccelerator.com` — Anker cloud MQTT). Zero Mac→printer LAN sockets.

```
                          ☁  ANKER CLOUD (AWS)  ☁
        ┌───────────────────────────────────────────────────────────┐
        │   make-mqtt.ankermake.com          P2P / PPPP relay        │
        │   166.117.x.x : 8789  (MQTT/TLS)   34.223.135.175 : 32100  │
        │   [AWS Global Accelerator]         [rendezvous for video]  │
        └───────▲───────────────▲───────────────────▲───────────────┘
                │               │                   │
        MQTT/TLS│       MQTT/TLS│           PPPP/UDP │ (camera, file xfer,
        (control│       (control│           P2P      │  falls back to relay
         + tele)│        parity)│                    │  if no direct LAN P2P)
                │               │                   │
   ═════════════╪═══════════════╪═══════════════════╪═════════ INTERNET ═══
                │               │                   │
   ─────────────┼───────────────┼───────────────────┼──── YOUR LAN (192.168.1.x)
                │               │                   │
                │    ┌──────────┴───────────────────┴───────────────┐
                │    │   Mac mini  (192.168.1.10)                    │
                │    │                                               │
                │    │   ┌─────────────┐   localhost:4470            │
                │    │   │ OrcaSlicer  │──────────────┐              │
                │    │   └─────────────┘              ▼              │
                │    │                        ┌───────────────┐      │
                │    │   ┌─────────────┐      │   ankerctl    │      │
                │    │   │ eufyMake app│      │  webserver    │──────┼─► cloud MQTT
                │    │   └──────┬──────┘      │ (the "phone"  │      │
                │    │          │             │  MQTT client) │      │
                │    │          └────────────►└───────────────┘      │
                │    │        (also cloud MQTT, its own client)      │
                │    │                                               │
                │    │   ┌─────────────┐                             │
                │    │   │  mediamtx   │◄──── camera stream (via PPPP relay)
                │    │   └─────────────┘                             │
                │    └───────────────────────────────────────────────┘
                │
                │  ┌─────────────────────────────────────────────────┐
                └─►│  AnkerMake M5C  (192.168.1.50)                   │
                   │                                                  │
                   │   ┌────────────────┐      ┌───────────────────┐  │
                   │   │ Linux comm mod │◄────►│ STM32F4 / Marlin  │  │
                   │   │ (Wi-Fi, MQTT,  │ UART │ (motion, heat,    │  │
                   │   │  camera, PPPP) │ 912k │  the actual print)│  │
                   │   └────────────────┘      └───────────────────┘  │
                   │        ▲                                         │
                   │        └── DNS lookups → 192.168.4.1 (eero)      │
                   │            plain UDP:53, honors DHCP DNS         │
                   └─────────────────────────────────────────────────┘
```

The fully-local target collapses the cloud detour: point both the printer (via
DNS override) and `ankerctl` at a **local** MQTT broker on the Mac, so the
control rendezvous happens on the LAN with the internet unplugged. The one
unverified link is whether the printer's TLS will trust a local broker's cert
(Step 4).

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
  to the printer (`192.168.1.50`).
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
at a local `dnsmasq` on the Mac (`192.168.1.10`). Because both the Deco and eero
are app-managed consumer mesh, changing the DNS handed to the printer is done in
the **Deco app** (set custom DNS → `192.168.1.10`), which only the operator can
do. Broker + `dnsmasq` setup on the Mac is automatable; the DNS switch is manual.

### Phase 1 — RESULT: printer accepts a local broker (PROVEN 2026-07-12) ✅

The pivotal question is answered: **the M5C's TLS is lax — it connects to a local
MQTT broker with a self-signed cert (`CN=make-mqtt.ankermake.com`) and requires no
Anker CA.** Full local control is feasible; no firmware root or serial bridge is
needed for the control path.

What did NOT work (dead ends, so future work skips them):

- **ARP-spoof + pf `rdr` to redirect the live cloud connection.** ARP poisoning
  reliably diverts the printer's traffic through the Mac, and a spoofed TCP RST
  reliably forces a fresh reconnect (fresh DNS lookup + SYN). But macOS pf `rdr`
  would **not** deliver that ARP-diverted/forwarded traffic to a local socket —
  neither `-> <LAN-IP>` nor `-> 127.0.0.1`. mosquitto never saw the connection.
  pf `rdr` on *transit* traffic to a local service is unreliable on macOS.

What worked — the winning architecture (Mac becomes the printer's router):

1. **macOS Internet Sharing**: Mac uplinks via **Ethernet** (`en0`) and shares out
   over **Wi-Fi** (`en1`) as a dedicated, printer-only hotspot (`M5C-Local`). The
   Mac is `192.168.2.1` on `bridge100`; the printer gets `192.168.2.2` via `bootpd`.
2. **Local DNS**: `dnsmasq` on `127.0.0.1:5354` answers
   `make-mqtt.ankermake.com → 192.168.2.1`, forwards everything else upstream.
   (`mDNSResponder` owns `*:53` and does not serve `/etc/hosts` to clients, so
   dnsmasq runs on a high port.)
3. **DNS interception without breaking NAT**: because the printer's `:53` query is
   addressed to the Mac's own IP (local, not transit), pf `rdr` works here. The
   rule is loaded into a `com.apple/anker_dns` sub-anchor (evaluated by the stock
   `rdr-anchor "com.apple/*"`), so it coexists with the Internet-Sharing NAT
   instead of flushing it: `rdr pass on bridge100 ... to 192.168.2.1 port 53 ->
   127.0.0.1 port 5354`.
4. **Broker**: mosquitto on `*:8789`, TLS with the self-signed
   `CN=make-mqtt.ankermake.com` cert, `allow_anonymous`.

#### Communication flow (fully local)

```
             ☁  ANKER CLOUD (AWS)  ☁          ✗ BYPASSED — no printer traffic
             make-mqtt.ankermake.com :8789     the printer never reaches it
   ══════════════════════════════════════════════════════ INTERNET ══════

   ┌──────────────────┐   WAN
   │  Deco / eero      │──────────► internet
   │  home router      │
   └────────┬──────────┘
            │ Ethernet (uplink only)
            ▼  en0 = 192.168.4.41
   ┌───────────────────────────────────────────────────────────────────┐
   │  MAC MINI  —  now the printer's router                             │
   │                                                                     │
   │   macOS Internet Sharing (NAT):  en0 ─────► Wi-Fi hotspot (en1)     │
   │   bridge100 = 192.168.2.1   SSID "M5C-Local" (WPA2)                 │
   │                                                                     │
   │   ┌─────────────┐   "make-mqtt?"     ┌──────────────┐              │
   │   │  pf rdr      │──────────────────►│  dnsmasq     │              │
   │   │  :53 → 5354  │◄──192.168.2.1─────│  :5354       │──► upstream  │
   │   │ (com.apple/  │                   │  make-mqtt = │    (other    │
   │   │  anker_dns)  │                   │  192.168.2.1 │     names)    │
   │   └─────────────┘                    └──────────────┘              │
   │                                                                     │
   │   ┌───────────────────────────────┐   ┌────────────────────────┐  │
   │   │  mosquitto  *:8789            │◄──│  ankerctl (the "phone" │  │
   │   │  TLS, self-signed             │──►│  client) — make-mqtt   │  │
   │   │  CN=make-mqtt.ankermake.com   │   │  → 192.168.2.1 too     │  │
   │   └───────────────────────────────┘   └────────────────────────┘  │
   │            ▲                                                        │
   └────────────┼────────────────────────────────────────────────────── ┘
                │ Wi-Fi (WPA2), DHCP lease 192.168.2.2
                │
                │  (1) DNS: make-mqtt? ─► gets 192.168.2.1 (the Mac)
                │  (2) MQTT/TLS :8789 ─► local broker, cert accepted (LAX)
                │  (3) SUBSCRIBE /device|smart|server/maker/<sn>/...command|query
                │  (4) PUBLISH   /phone/maker/<sn>/notice (temps/state) + replies
                ▼
   ┌─────────────────────────────────────────────────┐
   │  AnkerMake M5C  (192.168.2.2)                     │
   │   ┌────────────────┐      ┌───────────────────┐   │
   │   │ Linux comm mod │◄────►│  STM32F4 / Marlin │   │
   │   │ Wi-Fi + MQTT   │ UART │  motion / heat    │   │
   │   └────────────────┘      └───────────────────┘   │
   └─────────────────────────────────────────────────┘

   Control rendezvous now happens ON THE MAC: the printer and ankerctl both
   resolve make-mqtt to 192.168.2.1 and meet at the local broker. Anker's
   cloud is out of the loop for MQTT entirely.
```

Observed on the local broker (Anker cloud fully bypassed):

- TLS handshake completed; MQTT `CONNECT` accepted as client
  `dev_fdm_..._AK00000000000000` (user `eufy_fdm_AK00000000000000`, p4/c1/k40).
- Printer **subscribed** to its command topics
  (`/device/maker/<sn>/query`, `/smart/maker/<sn>/command`,
  `/server/maker/<sn>/command`).
- Printer **published** its full telemetry to us: `/phone/maker/<sn>/notice`
  every ~3 s, plus `/query/reply` (761 B) and `/command/reply`. Payloads are the
  usual MA-framed + AES (decodable with the printer's `mqtt_key`, which `ankerctl`
  already holds).

#### `ankerctl` integration and supervised print validation (2026-07-12)

The broker redirect also requires two `ankerctl` changes; neither is optional:

1. Set the cached `printer.ip_addr` in
   `~/Library/Application Support/ankerctl/default.json` to the hotspot lease
   (`192.168.2.2` in this installation). PPPP file transfer opens a direct LAN
   session to this stored address; it does not discover the printer through the
   local MQTT broker.
2. Add `--insecure` between `ankerctl.py` and `webserver` in the
   `com.ankerctl.webserver` LaunchAgent's `ProgramArguments`, then reload the
   LaunchAgent. The local broker uses a self-signed certificate, so stock
   `ankerctl` otherwise rejects its TLS connection. This option is acceptable
   only because the broker is private and reachable solely through the
   printer-only hotspot.

With those changes applied, the following were verified with an operator at the
printer:

- `ankerctl --insecure mqtt monitor` connected to the local broker and decoded
  live nozzle and bed telemetry.
- A raw `G28` command was accepted by Marlin (`xy trigger`, then `busy` reply).
  **Historical transport evidence only; do not repeat it.** Later supervised
  tests proved standalone raw `G28` drives the nozzle into the plate without the
  required probe preparation. It is now blocked by the web control boundary.
- OrcaSlicer using its OctoPrint-compatible `127.0.0.1:4470` endpoint uploaded
  a 7.5 MB G-code file. `ankerctl` connected to `192.168.2.2` over PPPP,
  completed all file blocks, requested the print start, and returned HTTP 200
  to Orca. The printer beeped when it accepted the request.

The expected upload confirmation is:

```text
Going to upload ... bytes as 'name.gcode'
File upload complete. Requesting print start of job.
Successfully sent print job
POST /api/files/local HTTP/1.1" 200
```

Historical remaining work at that point (completed/superseded later on
2026-07-12 by the LaunchDaemons and default-deny design below):

- Persist across reboots: Internet Sharing auto-start, `dnsmasq` + pf-anchor +
  mosquitto as launchd services.
- Sever the rest of Anker: block Anker domains at the Mac (it is now the printer's
  router), and address the P2P/PPPP relay (camera), NTP, and firmware/OTA ties.

#### Cloud block — defense-in-depth (implemented, then superseded 2026-07-12)

`SUPERSEDED`: the exact-IP rules in this subsection are retained as experiment
history. They are not the current firewall design and must not be reinstalled;
the default-deny egress allowlist in the next subsection replaced them.

Because the Mac is the printer's router, Anker is blocked *there*, scoped to the
printer (`192.168.2.2`) — the home router cannot target the printer (it's NAT'd
behind the Mac). Two layers:

- **DNS blackhole (dnsmasq):** `address=/ankermake.com/0.0.0.0` (+ `::`, +
  `eufylife.com`), with the more-specific `make-mqtt.ankermake.com → 192.168.2.1`
  winning. Catches any hostname-based cloud contact. Verified: `make-app` → 0.0.0.0,
  `make-mqtt` → 192.168.2.1, normal domains resolve.
- **pf IP block (`com.apple/anker_block` anchor, `quick`, printer-scoped):**
  `block drop quick on bridge100 from 192.168.2.2 to 34.223.135.175` (the Anker
  **P2P/PPPP WAN relay**, reached by hardcoded IP so DNS alone misses it) and
  `... to 166.117.0.0/16` (Anker MQTT Global-Accelerator range). Confirmed live:
  the printer retried the P2P relay and pf dropped the packets (counter > 0), while
  the local MQTT connection and telemetry were unaffected.

Net effect: the printer's only surviving cloud-shaped connection is MQTT — and
that now terminates on the **local** broker. The Anker cloud is severed for the
printer while it keeps running normally.

### Complete sever-list + egress-allowlist redesign (2026-07-12)

A ~7-hour DNS query log from the hotspot's logging resolver (13:25–20:21) gives
the printer's full outbound name set, completing the recon that the 2-minute
Phase-0 capture could not:

| Host | Queries | Role |
| --- | --- | --- |
| `make-app.ankermake.com` | 1934 | Anker app/cloud API |
| `www.anker.com` | 991 | Anker (a domain the old blackhole missed) |
| `p2p-mk-ohi/cal.eufylife.com` | 93 | P2P relay rendezvous |
| `make-mqtt(-eu).ankermake.com` | 8 | MQTT (redirect target) |
| `ota.eufylife.com` | 1 | **firmware/OTA — confirmed** |
| `time.nist.gov`, `pool.ntp.org` | 1 each | **NTP — confirmed** |
| `www.{google,microsoft,apple}.com` | ~1500 | internet-connectivity checks |

Two findings changed the block design:

1. **An IP blocklist cannot sever the cloud.** `make-mqtt`/`make-app`/`anker.com`
   are fronted by **AWS Global Accelerator**, which answers from rotating anycast
   IPs across AWS ranges — the printer was seen reaching `3.33.186.135` and
   `15.197.167.90` (both the same GA endpoint) as well as the earlier
   `166.117.x`. Chasing IPs is futile.
2. **The printer needs NTP and checks OTA.** Under a naive block these would
   fail; NTP silently must be handled or the clock drifts.

The block layer was therefore redesigned from specific-IP drops to a
**default-deny egress allowlist** for the printer: once fully local, its only
legitimate peers are on the hotspot subnet (broker, DNS, NTP, PPPP file transfer
all on the Mac at `192.168.2.1`), so `anker_block` passes
`192.168.2.2 → 192.168.2.0/24` and drops everything else off-subnet. This is
immune to GA rotation and also kills OTA and connectivity checks in one rule.
The printer's PPPP file-transfer/P2P path stays on the LAN subnet (unaffected);
only its cloud WAN relay is dropped, forcing direct-LAN P2P. The M5C has no
onboard camera. NTP is preserved by an `anker_dns`
rdr that rewrites the printer's `:123` to a **local chrony** on the Mac (run with
`-x` so it serves time without disciplining the Mac's own clock). `anker.com`
was added to the dnsmasq blackhole for defense-in-depth.

This design is implemented as boot-persistent LaunchDaemons in
[`deploy/local-broker/`](../deploy/local-broker/) (mosquitto, dnsmasq, chrony,
and a pf-loader), with `install.sh` / `verify.sh` / `uninstall.sh` and a runbook.

### USB-C is not an open control path (verified 2026-07-12)

Checked whether the printer's USB-C port could drive Marlin directly (which would
make control fully local over a cable, with no network at all). It cannot:

- Community tooling (OctoPrint / Mainsail / Fluidd / SimplyPrint) lists the M5C
  as incompatible **specifically because it does not expose serial printing**.
- The published firmware confirms why: the STM32F4 Marlin uses only hardware
  UARTs — `SERIAL_PORT 1/2/3` = USART1/3/6 at 912600 / 1000000 / 115200 baud,
  which are internal MCU↔Linux-module links — with **no USB CDC serial**
  (`SERIAL_PORT` is never `-1`; no `SerialUSB`). The STM32's USB OTG is
  configured as a **host for USB flash drives** (the "print from USB stick"
  feature), not as a device a PC can drive. The external USB-C to a computer is
  handled by the Linux comm module via Anker's own file-transfer protocol.

So a USB-C cable to a computer yields Anker's file-drop, not open control. The
only wired control path is the invasive **serial bridge**: tap the internal
STM32↔Linux UART (the 912600-baud link) with a USB-UART adapter — opening the
printer, identifying the header (logic analyzer), and co-opting or replacing that
link (never both devices driving it at once). This keeps the MQTT-broker redirect
as the least-invasive path to try first.

## Confidence ranking (updated with evidence)

| Approach | Status | Risk |
| --- | --- | --- |
| PPPP-only control by reusing MQTT command types | **Disproven** (Step 3 probe) | Low |
| Discover a local control sub-protocol via official-app LAN capture | **Disproven** (Step 2: app is cloud-MQTT-only) | Low |
| Redirect printer to a local MQTT broker | **PROVEN & IMPLEMENTED (2026-07-12)** — printer accepts a self-signed local broker (lax TLS); full telemetry + command-topic subscriptions land on our broker via a Mac-hosted, printer-only hotspot with local DNS. Cloud MQTT bypassed. | Low (done) |
| PPPP + stock-Marlin serial bridge (USB-UART sidecar) | Strongest *guaranteed* durable path; needs hardware | Medium |
| Replace firmware (Klipper / custom Marlin) | Feasible, least mature | High |

The two "reverse-engineer a local protocol" ideas are both closed off: there is
no hidden local control channel (Step 2), and the generic PPPP JSON endpoint
does not serve maker commands (Step 3). The remaining paths all keep the
existing MQTT command set and change *where* the printer's MQTT session
terminates (local broker) or *how* G-code reaches Marlin (serial bridge).

## Recommended next steps

1. ~~**Test whether the printer will accept a redirected MQTT broker.**~~
   **DONE (2026-07-12) — printer accepts a self-signed local broker (lax TLS).**
   See "Phase 1 — RESULT" under Step 4 for the proven architecture (Mac-hosted
   hotspot + local DNS + mosquitto) and the remaining work to reach the durable
   fully-local end state (persist services across reboot and sever the remaining
   P2P/NTP/firmware ties).

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
