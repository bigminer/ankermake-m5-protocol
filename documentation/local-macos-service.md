# Local macOS Printer Service Runbook

This document describes the AnkerMake M5C service installed on Gary's Mac
mini, including the local `ankerctl` modifications, OrcaSlicer integration,
Tailscale access, iPad camera relay, routine operations, troubleshooting, and
recovery.

The paths and network names below describe the installation as of
2026-07-06. Credentials are intentionally omitted.

## Safety and security

- Never place account tokens, MQTT credentials, the web access token, Flask
  secret key, or TLS private keys in source control or documentation.
- The web UI is protected by `ANKERCTL_TOKEN`, but the OctoPrint-compatible
  slicer endpoints remain unauthenticated so OrcaSlicer can upload jobs.
- `ankerctl` listens on `0.0.0.0:4470`. Any device that can reach that port
  can call the exempt upload endpoint and start a print. Restrict access with
  the macOS firewall, network segmentation, or Tailscale ACLs.
- MediaMTX listens on all interfaces. Treat its publisher URL as a control
  endpoint: anyone who can reach it can replace the `ipadcam` stream.
- Do not enable the experimental `G36` pre-print hook. See
  [Disabled G36 experiment](#disabled-g36-experiment).
- Supervise the first print after changing G-code, firmware, printer profiles,
  upload logic, or network routing.

## Architecture

```text
OrcaSlicer
    |
    | OctoPrint-compatible HTTP upload
    v
ankerctl on 0.0.0.0:4470
    |                         |
    | PPPP file transfer      | Anker cloud MQTT
    v                         v
AnkerMake M5C <--------- telemetry and controls

iPad Safari camera
    |
    | Tailscale + encrypted WebRTC publish
    v
MediaMTX on :8889 / UDP :8189
    |
    | WebRTC viewer
    v
ankerctl embedded camera frame / remote browser
```

`ankerctl` uses MQTT for status and interactive controls. Print files are sent
to the printer over PPPP. It does not retain a permanent copy of an uploaded
G-code file.

## Component inventory

| Component | Location | Purpose |
| --- | --- | --- |
| `ankerctl` repository | `/Users/gary/ankermake-m5-protocol` | Printer service, web UI, MQTT and PPPP implementation |
| Python environment | `/Users/gary/ankermake-m5-protocol/.venv` | Runtime dependencies |
| Account/printer config | `/Users/gary/Library/Application Support/ankerctl/default.json` | Anker account, printer credentials, cached printer IP and webcam URL |
| `ankerctl` LaunchAgent | `/Users/gary/Library/LaunchAgents/com.ankerctl.webserver.plist` | Starts the web service at login |
| `ankerctl` log | `/Users/gary/ankermake-m5-protocol/ankerctl.log` | Web, MQTT, PPPP and upload events |
| MediaMTX directory | `/Users/gary/mediamtx` | WebRTC relay, certificates and logs |
| MediaMTX config | `/Users/gary/mediamtx/mediamtx.yml` | WebRTC listener and `ipadcam` path |
| MediaMTX LaunchAgent | `/Users/gary/Library/LaunchAgents/com.mediamtx.webrtc.plist` | Starts the camera relay at login |
| MediaMTX log | `/Users/gary/mediamtx/mediamtx.log` | Publisher, viewer and packet-loss events |
| Orca M5C preset | `/Users/gary/Library/Application Support/OrcaSlicer/user/default/machine/Anker M5C.json` | Printer host and start G-code |

Snapshot versions:

- `ankerctl` base commit: `88131a5`, plus local uncommitted modifications.
- Python: 3.12.13.
- OrcaSlicer: 2.4.1.
- MediaMTX: 1.19.2.
- Tailscale CLI: 1.96.4. The system extension was observed at 1.98.5; align
  these versions during the next Tailscale upgrade.
- Printer firmware observed through MQTT: V3.1.56.

## Network endpoints

| Endpoint | Use |
| --- | --- |
| `http://127.0.0.1:4470` | Local `ankerctl` web UI and Orca upload host |
| `http://192.168.68.55:4470` | Mac LAN web UI |
| `https://garys-mac-mini.tail55ce6a.ts.net:8889/ipadcam/publish` | iPad camera publisher |
| `https://garys-mac-mini.tail55ce6a.ts.net:8889/ipadcam` | Camera viewer |
| `100.115.64.31` | Mac Tailscale IPv4 address at time of documentation |
| `192.168.68.57` | Printer LAN address at time of documentation |

Relevant listeners:

| Port | Protocol | Process | Purpose |
| --- | --- | --- | --- |
| 4470 | TCP | Python / `ankerctl` | Web UI, API and WebSockets |
| 8889 | TCP | MediaMTX | HTTPS WebRTC signaling and viewer/publisher pages |
| 8189 | UDP | MediaMTX | WebRTC media |
| 8892 | TCP/UDP | MediaMTX | Additional MediaMTX listener observed at runtime; not explicitly configured in the current YAML |

Tailscale Serve also has unrelated proxies on ports 9119 and 9120. They are
not part of this printer stack.

## Initial installation

### Repository and virtual environment

```sh
cd /Users/gary
git clone https://github.com/Ankermgmt/ankermake-m5-protocol.git
cd ankermake-m5-protocol

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Import the Anker/eufyMake login configuration:

```sh
cd /Users/gary/ankermake-m5-protocol
.venv/bin/python ankerctl.py config import
.venv/bin/python ankerctl.py config show
```

The imported configuration is sensitive. Back it up securely and never
commit it.

### Web service LaunchAgent

The installed LaunchAgent runs:

```text
/Users/gary/ankermake-m5-protocol/.venv/bin/python
/Users/gary/ankermake-m5-protocol/ankerctl.py
--insecure webserver run --host 0.0.0.0
```

`--insecure` is required only for the private local-broker setup: its Mosquitto
certificate is self-signed. Do not use this option when connecting to an
untrusted broker or network.

It uses:

```text
Label:             com.ankerctl.webserver
WorkingDirectory:  /Users/gary/ankermake-m5-protocol
RunAtLoad:         true
KeepAlive:         true
Log:               /Users/gary/ankermake-m5-protocol/ankerctl.log
```

Environment variables:

| Variable | Purpose | Current policy |
| --- | --- | --- |
| `ANKERCTL_TOKEN` | Shared web UI login token | Required; value kept only in the plist |
| `ANKERCTL_SECRET_KEY` | Stable Flask session signing key | Required; random secret kept only in the plist |
| `ANKERCTL_PREPRINT_G36` | Experimental pre-upload preparation hook | Must remain `false` |
| `ANKERCTL_PREPRINT_COMMAND_TIMEOUT` | Experimental hook timeout | Present but unused while hook is disabled |
| `ANKERCTL_WEBCAM_URL` | Optional environment-level webcam URL | Not required when URL is saved in `default.json` |

Generate new secrets rather than reusing documented examples:

```sh
openssl rand -base64 32
openssl rand -base64 24
```

Load or reload the service:

```sh
plist="$HOME/Library/LaunchAgents/com.ankerctl.webserver.plist"
plutil -lint "$plist"
launchctl unload "$plist" 2>/dev/null || true
launchctl load -w "$plist"
```

The older `launchctl load/unload` commands are used here because `bootstrap`
returned an input/output error for this LaunchAgent on this Mac.

## Routine service operations

### Check service status

```sh
launchctl print "gui/$(id -u)/com.ankerctl.webserver" |
  grep -E 'state =|pid =|job state'

lsof -nP -iTCP:4470 -sTCP:LISTEN
curl -I http://127.0.0.1:4470/
```

An unauthenticated `curl` returning HTTP 302 to `/login` is healthy when the
access token is enabled.

### Follow logs

```sh
tail -f /Users/gary/ankermake-m5-protocol/ankerctl.log
```

Useful filters:

```sh
grep -E 'Going to upload|File upload complete|Successfully sent print job' \
  /Users/gary/ankermake-m5-protocol/ankerctl.log

grep -Ei 'error|failed|timeout|connection lost' \
  /Users/gary/ankermake-m5-protocol/ankerctl.log
```

### Restart only `ankerctl`

```sh
plist="$HOME/Library/LaunchAgents/com.ankerctl.webserver.plist"
launchctl unload "$plist"
launchctl load -w "$plist"
```

Restarting `ankerctl` does not restart the printer or MediaMTX.

### Verify printer reachability

```sh
ping -c 2 192.168.2.2

cd /Users/gary/ankermake-m5-protocol
.venv/bin/python ankerctl.py pppp lan-search
```

The printer may not answer immediately after a power cycle. Wait until PPPP
reaches `Running` before uploading.

## Web UI and authentication

The local web UI adds the following features to upstream `ankerctl`:

- Shared-token login.
- Authenticated MQTT, video, PPPP-state and control WebSockets.
- External webcam URL configuration.
- Embedded WebRTC camera viewer.
- Control tab showing state, progress, temperatures, speed and layer.
- Object preview image when supplied by printer telemetry.
- Fan, jog, home, temperature and raw G-code controls.

Authentication behavior:

- `/login` accepts `ANKERCTL_TOKEN` and creates a Flask session.
- `ANKERCTL_SECRET_KEY` keeps sessions valid across restarts.
- `/api/version`, `/api/files/local`, `/login`, and static assets are exempt.
- WebSocket handshakes reject unauthenticated clients with HTTP 401.

The upload exemption is required by the current Orca integration, but it is
also the main network security risk.

### Control tab warning

Raw G-code, fan, jog, home and temperature controls use the known
`GCODE_COMMAND` MQTT primitive.

The pause, resume and stop button values are best guesses and have not been
validated against this M5C firmware. Do not rely on those buttons for safety.
Use the printer/app controls or physical power switch when necessary.

## OrcaSlicer configuration

Configure the printer connection as an OctoPrint-compatible host:

```text
Host: http://127.0.0.1:4470
API key: not required
Operation: Send and Print
```

`127.0.0.1:4470` is the correct endpoint when Orca runs on the Mac. It is the
`ankerctl` HTTP service, not the printer (`192.168.2.2`) or Mosquitto (`:8789`).
The Orca connection test only requests `/api/version`; a real upload must appear
in `ankerctl.log` as `POST /api/files/local`.

The saved user preset is:

```text
/Users/gary/Library/Application Support/OrcaSlicer/user/default/machine/Anker M5C.json
```

The required machine start G-code is:

```gcode
M4899 T3 ; Enable v3 jerk and S-curve acceleration
M104 S150 ; Set hotend temp to 150 degrees to prevent ooze
M190 S{first_layer_bed_temperature[0]} ; set and wait for bed temp to stabilize
M109 S{first_layer_temperature[0]} ; set final nozzle temp to stabilize
G28 ;Home
;LAYER_COUNT:{total_layer_count}
```

Do not add `G36`, `M420 S1`, or the experimental pre-print block. The original
`G28` block is the known-good configuration.

After changing machine G-code, reslice the model. A previously generated
G-code file keeps the old commands.

### Expected print flow

1. Orca slices the model.
2. Orca posts the generated file to `/api/files/local`.
3. `ankerctl` reads the file and opens a PPPP file-transfer session.
4. The file is transferred to the M5C.
5. The file-transfer end message asks the printer to start the job.
6. MQTT telemetry reports job name, progress, remaining time, temperatures,
   speed, and layer.

Successful log sequence:

```text
Going to upload ... bytes as 'name.gcode'
File upload complete. Requesting print start of job.
Successfully sent print job
```

Each 32 KiB PPPP data block has a 15-second acknowledgement timeout. If PPPP
drops during a large upload, the request now fails instead of holding the
file-transfer service indefinitely. Interrupted uploads cannot resume and must
be resent from Orca after PPPP reconnects.

The service does not archive the uploaded G-code. Orca may keep a temporary
copy below `/private/var/folders/.../orcaslicer_model/...`, but that path is
ephemeral and may represent the currently loaded Orca plate rather than a job
started from the phone app.

## Account and printer configuration

The live config is:

```text
/Users/gary/Library/Application Support/ankerctl/default.json
```

It contains:

- Anker account identifiers and authentication tokens.
- MQTT credentials and encryption material.
- Printer identifiers and PPPP credentials.
- Cached printer LAN address.
- Optional external webcam URL.

Safe summary command:

```sh
cd /Users/gary/ankermake-m5-protocol
.venv/bin/python ankerctl.py config show
```

Do not paste the full JSON into chat, tickets, logs, or source control.

The local changes preserve `webcam_url` when account configuration is
re-imported or upgraded.

## iPad camera and MediaMTX

### Service configuration

MediaMTX runs from:

```text
/Users/gary/mediamtx/mediamtx
/Users/gary/mediamtx/mediamtx.yml
```

The current configuration enables only encrypted WebRTC:

```yaml
logLevel: info
api: no
metrics: no
rtsp: no
rtmp: no
hls: no
srt: no

webrtc: yes
webrtcAddress: :8889
webrtcEncryption: yes
webrtcServerCert: /Users/gary/mediamtx/tls.crt
webrtcServerKey: /Users/gary/mediamtx/tls.key
webrtcLocalUDPAddress: :8189
webrtcIPsFromInterfaces: no
webrtcAdditionalHosts:
  - 100.115.64.31
  - garys-mac-mini.tail55ce6a.ts.net

paths:
  ipadcam:
```

The certificate is issued for:

```text
garys-mac-mini.tail55ce6a.ts.net
```

Use the DNS hostname, not the Tailscale IP, when certificate validation
matters.

### Start and stop MediaMTX

```sh
plist="$HOME/Library/LaunchAgents/com.mediamtx.webrtc.plist"
plutil -lint "$plist"
launchctl unload "$plist" 2>/dev/null || true
launchctl load -w "$plist"
```

Status and logs:

```sh
launchctl print "gui/$(id -u)/com.mediamtx.webrtc"
tail -f /Users/gary/mediamtx/mediamtx.log
lsof -nP -iTCP:8889 -sTCP:LISTEN
lsof -nP -iUDP:8189
```

### Connect the iPad camera

1. Open Tailscale on the iPad.
2. Confirm the iPad shows online in the same tailnet.
3. Open Safari to:

   ```text
   https://garys-mac-mini.tail55ce6a.ts.net:8889/ipadcam/publish
   ```

4. Allow camera and microphone access.
5. Start publishing.
6. Keep Safari in the foreground and prevent the iPad from sleeping.

Viewer:

```text
https://garys-mac-mini.tail55ce6a.ts.net:8889/ipadcam
```

The viewer URL can be saved under **Setup → External Webcam URL** in the
`ankerctl` UI. It is stored as `webcam_url` in `default.json`.

### Camera diagnostics

Check tailnet devices:

```sh
tailscale status
tailscale ping 100.78.175.76
```

Check publisher status through logs:

```sh
grep -E "ipadcam|is publishing|stream is available|no stream is available" \
  /Users/gary/mediamtx/mediamtx.log | tail -n 50
```

Healthy publisher messages:

```text
[path ipadcam] stream is available and online
[WebRTC] ... is publishing to path 'ipadcam'
```

No publisher:

```text
no stream is available on path 'ipadcam'
```

Packet-loss symptoms:

```text
RTP packets lost
received a non-starting fragment
```

For persistent packet loss:

1. Keep the iPad awake and Safari foregrounded.
2. Confirm both devices have stable Wi-Fi.
3. Disable Low Power Mode on the iPad.
4. Reload the publisher page.
5. Restart MediaMTX only if a fresh publisher still fails.

## Tailscale operations

Mac identity at time of documentation:

```text
MagicDNS: garys-mac-mini.tail55ce6a.ts.net
IPv4:     100.115.64.31
```

Useful commands:

```sh
tailscale status
tailscale status --json | jq .
tailscale ping <peer-name-or-IP>
tailscale serve status
```

An iOS peer can appear offline while the app/VPN is suspended. Opening the
Tailscale app on the iPad usually reactivates it.

The Tailscale CLI and system-extension versions currently differ. This is not
the cause of the printer issues documented here, but they should be updated
together.

## Troubleshooting

### Orca says sent, but no print starts

1. Confirm the pre-print hook is disabled:

   ```sh
   launchctl print "gui/$(id -u)/com.ankerctl.webserver" |
     grep ANKERCTL_PREPRINT_G36
   ```

   Required value:

   ```text
   ANKERCTL_PREPRINT_G36 => false
   ```

2. Confirm the G-code contains the original `G28` block.
3. Check the three expected upload log messages.
4. Check PPPP state through `/api/ankerctl/status`.
5. Power-cycle the printer if it does not reconnect after a failed command.
6. Resend only after PPPP is `Running`.

### PPPP is `Starting` after a printer reboot

The printer may need 30–60 seconds to rejoin the `M5C-Local` hotspot.

```sh
ping -c 2 192.168.2.2
tail -f /Users/gary/ankermake-m5-protocol/ankerctl.log
```

Look for:

```text
Successfully connected to printer ... over pppp
Established pppp connection
PPPP connection established
```

### A large upload stops partway through

Look for an upload that reaches `Sending file contents` without reaching
`File upload complete`, followed by `PPPP connection lost`.

The current service aborts a transfer when a 32 KiB block is not acknowledged
within 15 seconds. Wait for PPPP to return to `Running`, then resend the
complete file. Partial transfers are not resumable.

### MQTT works but PPPP does not

In the local-broker topology, MQTT terminates on the Mac, while PPPP file
transfer still uses the printer's LAN address. Confirm the cached `ip_addr` in
`~/Library/Application Support/ankerctl/default.json` is the hotspot lease
(`192.168.2.2` here), then restart `ankerctl`.

Run:

```sh
.venv/bin/python ankerctl.py pppp lan-search
```

Then update/re-import configuration if the cached address is stale.

### Web UI redirects to login

This is expected when `ANKERCTL_TOKEN` is set. Use the configured access
token. Do not remove authentication merely to fix slicer uploads; the slicer
endpoints are already exempt.

### Orca cannot test the host

```sh
curl http://127.0.0.1:4470/api/version
lsof -nP -iTCP:4470 -sTCP:LISTEN
```

Use `127.0.0.1:4470` when Orca runs on this Mac. Use the Mac's LAN or
Tailscale address only when Orca runs on another machine.

### Printer command queue is stuck

Symptoms:

- Temperatures remain targeted but no motion occurs.
- Normal `M104 S0` / `M140 S0` commands do not change reported targets.
- MQTT returns stale or unrelated acknowledgements.

Recovery:

1. Do not send another print.
2. Disable the experimental hook if enabled.
3. Use the printer's physical power switch.
4. Leave it off for at least 10 seconds.
5. Power it on.
6. Verify both heater targets report 0°C.
7. Wait for PPPP to return to `Running`.
8. Resume only with the original Orca start G-code.

Do not trust an MQTT `ok` response as proof that a queued emergency command
executed. Verify the reported target temperatures.

## Disabled G36 experiment

The official eufyMake M5C Marlin source contains `G36` and internal wiping,
alignment and homing routines. That does not mean production firmware accepts
`G36` in every transport.

Observed behavior on firmware V3.1.56:

1. Embedding `G36` in uploaded G-code caused the job not to start.
2. Sending `G36` through MQTT after preheating was accepted but did not produce
   reliable motion/completion behavior.
3. The command queue became wedged.
4. Heater-off commands returned misleading acknowledgements while targets
   remained active.
5. A physical printer power cycle was required.

The local code contains an opt-in pre-print implementation in `web/util.py`
for research history, but the LaunchAgent sets:

```text
ANKERCTL_PREPRINT_G36=false
```

This must remain disabled. Do not re-enable it without a dedicated test
environment, serial-console visibility, and a confirmed production-firmware
command contract.

The supported configuration is the original `G28` start sequence.

## Tests and development checks

Run the focused local tests:

```sh
cd /Users/gary/ankermake-m5-protocol
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q web tests
git diff --check
```

Before editing:

```sh
git status --short
git diff
```

This checkout contains local changes. Do not reset, overwrite, or discard
unrelated modifications when upgrading.

## Backup and restore

Back up these items securely:

```text
/Users/gary/ankermake-m5-protocol
/Users/gary/Library/Application Support/ankerctl/default.json
/Users/gary/Library/LaunchAgents/com.ankerctl.webserver.plist
/Users/gary/mediamtx/mediamtx.yml
/Users/gary/mediamtx/tls.crt
/Users/gary/mediamtx/tls.key
/Users/gary/Library/LaunchAgents/com.mediamtx.webrtc.plist
/Users/gary/Library/Application Support/OrcaSlicer/user/default/machine/Anker M5C.json
```

The backup contains credentials and private keys. Encrypt it and restrict file
permissions.

Example permission audit:

```sh
ls -l \
  "$HOME/Library/Application Support/ankerctl/default.json" \
  "$HOME/Library/LaunchAgents/com.ankerctl.webserver.plist" \
  /Users/gary/mediamtx/tls.key
```

After restore:

1. Recreate or restore `.venv`.
2. Validate both plists with `plutil -lint`.
3. Load both LaunchAgents.
4. Confirm Tailscale is online.
5. Confirm port 4470 and MediaMTX ports are listening.
6. Confirm printer PPPP and MQTT services.
7. Test the camera publisher/viewer.
8. Run a small supervised test print.

## Upgrade procedure

1. Stop printing and ensure both heater targets are zero.
2. Back up the repository, config, plists and MediaMTX keys.
3. Review local changes:

   ```sh
   git status --short
   git diff
   ```

4. Fetch upstream without discarding local work.
5. Reconcile conflicts deliberately.
6. Update the virtual environment:

   ```sh
   .venv/bin/pip install -r requirements.txt
   ```

7. Run tests and syntax checks.
8. Restart `ankerctl`.
9. Verify login, MQTT, PPPP, Orca upload and camera relay.
10. Run a small supervised print.

Never use `git reset --hard` or replace the checkout without first preserving
the local changes.

## External source references

- Community protocol project:
  <https://github.com/Ankermgmt/ankermake-m5-protocol>
- Official M5C firmware source:
  <https://github.com/eufymake/eufyMake-Marlin-M5C>
- Official eufyMake PrusaSlicer source:
  <https://github.com/eufymake/eufyMake-PrusaSlicer-Release>
- MediaMTX:
  <https://github.com/bluenviron/mediamtx>
- Tailscale:
  <https://tailscale.com/kb>

## Daily checklist

Before printing:

- Printer is online and reachable.
- PPPP and MQTT services are `Running`.
- Orca start G-code contains `G28`, not `G36`.
- `ANKERCTL_PREPRINT_G36` is `false`.
- Build plate and toolhead path are clear.
- Camera publisher is online if remote monitoring is required.

After printing:

- Confirm the job completed normally.
- Confirm heater targets return to zero.
- Review logs if PPPP or camera connections dropped.
- Keep the iPad powered if it remains the monitoring camera.
