# Prompt — Can the AnkerMake M5C be redirected to a local MQTT broker?

> **ARCHIVED PLAN — DO NOT EXECUTE AS A CURRENT RUNBOOK.** This document records
> the pre-implementation investigation prompt from 2026-07-11. The local-broker
> redirect was subsequently proven and implemented with a Mac-hosted printer
> hotspot, local Mosquitto/DNS/NTP, and default-deny egress. Its LAN topology,
> “remaining unknowns,” and rollback language are historical. Use
> [`local-macos-service.md`](local-macos-service.md) for operations and
> [`printer-findings.md`](printer-findings.md) for current confidence/status.

> Self-contained brief for any coding agent (Codex, Claude, or other) with shell
> access to the Mac mini and this repo checked out. It assumes no
> harness-specific behavior; everything needed is stated here or in the
> referenced files.

## Context (read first)
You are continuing the "local-control" effort in the `ankermake-m5-protocol`
repo, branch `local-control`. Before doing anything, read:
- `documentation/local-control-research.md`
- `documentation/local-macos-service.md`
- `CLAUDE.md` — project safety rules.

Established by prior experiments (2026-07-11), with evidence in those docs:
- The official eufyMake app **and** ankerctl control the M5C **entirely through
  Anker cloud MQTT** (`make-mqtt.ankermake.com:8789`, TLS). There is no local
  control protocol; local PPPP carries only camera + file upload.
- ankerctl already implements the **full** MQTT command/telemetry set
  (`libflagship/mqtt.py`, `libflagship/mqttapi.py`) and acts as the "phone"
  client: it publishes to `/device/maker/<sn>/command` and `/query`, and
  subscribes to `/phone/maker/<sn>/{notice,command/reply,query/reply}`. Payloads
  are MA-framed + AES using the printer's `mqtt_key` from the account config.

So decoupling from Anker is a **transport-redirection** problem, not protocol
reverse-engineering.

## The idea being tested
If the printer can be made to connect to an MQTT broker we control instead of
Anker's, then a stock broker (mosquitto) simply **routes** between two existing
clients — the printer and ankerctl — and we get full local control with zero new
protocol code. We do **not** need Anker's private key or to reimplement
anything. The only unknowns are whether the printer will (a) resolve/route to
our broker and (b) accept our broker's TLS.

## Objective
Determine, with evidence, whether the M5C will connect to a local MQTT broker
**without firmware root**, and exactly what its TLS trust requires. Produce a
clear go/no-go for the local-broker path vs. the USB-UART serial-bridge
fallback.

**End state is FULLY LOCAL** — a permanent replacement of Anker's cloud, not a
bridge. Success means the printer talks only to a broker we run, ankerctl
controls it through that broker, and Anker's cloud is severed. The eufyMake app
losing remote function is expected and acceptable. Two consequences follow:
1. The redirect must be **durable infrastructure** (permanent local DNS /
   routing that survives reboots), not a fragile ARP-spoof. ARP-spoofing is
   acceptable only as throwaway scaffolding to reach the Phase 2 answer fast.
2. MQTT is necessary but may not be sufficient. Inventory **all** of the
   printer's outbound cloud dependencies (DNS names + IPs: firmware-update
   checks, NTP, any HTTPS telemetry) so a truly independent setup can replace
   or firewall each one — not just MQTT.

## Environment / key facts
- Printer: AnkerMake M5C, IP `192.168.1.50`, SN `AK00000000000000`, DUID
  `USPRAKM-000000-XXXXX`, firmware V3.1.56, region US.
- Anker MQTT: `make-mqtt.ankermake.com` → AWS Global Accelerator
  (`166.117.17.78` / `166.117.252.238`), TCP 8789, TLS.
- `ssl/ankermake-mqtt.crt` is the CA that verifies Anker's **server** cert. We
  have the CA cert, **not** Anker's private key.
- Mac mini `192.168.1.10` (en1), same LAN, passwordless sudo; can run
  mosquitto / dnsmasq / tcpdump. The eufyMake desktop app (process `FDMPrint`)
  is installed here.
- Network topology (identified 2026-07-11): the printer's gateway and primary
  DNS is a **TP-Link Deco** mesh at `192.168.1.1` (LAN `192.168.1.0/24`);
  DHCP also hands out an **eero** at `192.168.4.1` as secondary DNS, which sits
  upstream (double-NAT: Deco WAN is on the eero's `192.168.4.0/24`). Both are
  consumer mesh systems.
- ankerctl runs as launchd `com.ankerctl.webserver`; keep it restorable.
- Credentials backup: `~/Library/Application Support/ankerctl/backups/2026-07-11/`.
  Never print or commit secrets.

## Method — phased; read-only first; each phase gates the next

**Phase 0 — Map the printer's cloud dependencies + how it finds its broker (no disruption)**
The printer is a separate device, so you must observe *its* traffic: prefer
router-level visibility (DNS query log / connection table); otherwise ARP-spoof
the printer↔gateway path from the Mac and tcpdump the printer's traffic.
Produce two things:
1. A full inventory of the printer's outbound connections — every DNS name it
   resolves and every IP:port it opens (MQTT :8789, plus NTP :123, firmware/
   HTTPS :443, etc.). This is the list of cloud ties to sever for "fully local".
2. Whether it reaches MQTT by DNS name (`make-mqtt.ankermake.com`) or a
   hardcoded IP — this decides the redirect mechanism (durable local DNS
   override vs. IP-level NAT/redirect of the AWS IPs at the router).
**Stop and report the inventory + mechanism before changing any DNS/routing.**

**Phase 1 — Logging broker, observe the handshake (publish nothing)**
Stand up mosquitto on :8789 with TLS, verbose logging, anonymous allowed, using
a self-signed cert with CN/SAN `make-mqtt.ankermake.com`. Steer the printer to
it. Watch tcpdump + mosquitto logs: does the printer open :8789, complete TLS,
and SUBSCRIBE? Capture the exact point of failure if not.

**Phase 2 — Characterize TLS trust**
From Phase 1, answer: does the printer validate the server cert at all? Against
a specific CA? Does it pin the hostname? Try the minimal variations needed.
- Printer completes TLS to our broker → local-broker path is **viable without
  root**; go to Phase 3.
- Printer validates/pins and rejects → needs firmware root to trust our CA.
  **Stop the broker path**, document the blocker, recommend the serial bridge.

**Phase 3 — (GATED: human present, printer supervised) prove full local control**
Point ankerctl at the same local broker (its `servertable`/host → the Mac).
Confirm telemetry flows (read-only) first. Then, only with a human at the
printer and per `CLAUDE.md`, issue ONE benign supervised command (e.g. a small
nozzle setpoint, then cool) and confirm the printer acts and replies. Finally,
with Anker firewalled off, run a small supervised print end-to-end to prove the
printer is fully controllable with **no** Anker connectivity.

**Make it durable + sever Anker (only after Phase 3 succeeds)**
Convert the redirect into permanent infrastructure and firewall the printer's
Anker endpoints/IPs so it cannot reach the cloud. Replace or stub the other
cloud dependencies found in Phase 0 (e.g. point NTP local). Document the final
config. Mechanism, given the TP-Link Deco + eero mesh (neither supports
per-hostname DNS records):
- Preferred, no new hardware: run `dnsmasq` on the Mac mini and set the **Deco's
  client DNS** to `192.168.1.10` (Deco supports a custom DNS server, the same
  hook Pi-hole users rely on). `dnsmasq` answers `make-mqtt.ankermake.com` →
  the local broker and forwards everything else. Add a firewall rule blocking
  the Anker MQTT IPs so a cached/hardcoded IP can't bypass DNS.
- Most robust, ~$30 hardware: put the printer behind a dedicated OpenWrt /
  GL.iNet router that we fully control (DNS + firewall), isolating it from the
  mesh entirely and surviving Mac downtime.
- Caveat resolved in Phase 0: if the printer ignores DHCP-provided DNS, pins a
  DNS server, or uses DoH, the DNS override fails and the redirect must happen
  at the IP layer (NAT/route the Anker IPs) or via the isolated-segment router.

**Rollback (safety net during testing)**
Until fully-local is proven and chosen, keep the ability to remove the override
so the printer reconnects to Anker and `ankerctl status` is healthy. Rollback is
the abort path, not the intended end state.

## Constraints
- **Safety rule (mandatory):** always confirm a human is present at the printer
  before issuing any command that can move it, heat it, or start/pause/resume/
  stop a job — over MQTT, PPPP, serial, or the web UI. Network, broker, and
  packet-capture work is fine unattended; publishing control is not. Physical
  actions carry heat/fire/motion risk and can wedge the firmware queue (needing
  a power cycle). This restates `CLAUDE.md`; obey it even if your harness does
  not load that file automatically.
- Read-only first: logging broker before any publish; telemetry before any
  command.
- Scope redirects to the printer IP where feasible so the app/ankerctl keep
  working during recon; don't disrupt the household network broadly.
- Preserve secrets; work on `local-control`; keep the webserver restorable.

## Deliverables
- `documentation/local-control-research.md` gains a "Step 4 — local broker
  redirect" section: redirect mechanism, the printer's TLS behavior, and a
  definitive go/no-go with evidence (captures, mosquitto logs).
- Helper config/scripts (mosquitto.conf, dnsmasq/redirect) saved and documented.
- A recommendation: pursue the local broker (with concrete ankerctl
  implementation steps) or fall back to the serial bridge.
- The outcome recorded in the repo docs (and in your own memory, if you keep one).

## First move
Do Phase 0 recon and STOP to report how the printer finds its broker before
changing any DNS or routing.
