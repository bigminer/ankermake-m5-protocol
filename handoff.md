# Session handoff

Last updated: 2026-07-19

## Current repository state

- Working branch: `local-control`
- Remote branch: `origin/local-control`
- Upstream draft PR: [anselor/ankermake-m5-protocol#15](https://github.com/anselor/ankermake-m5-protocol/pull/15)
- Incident tracker: [bigminer/ankermake-m5-protocol#5](https://github.com/bigminer/ankermake-m5-protocol/issues/5)
- Latest pushed commit: `d1e7f0c` (`Restore minimal M5C stop payload`)
- Local `HEAD`: `0d80e46` (`Harden local printer control safety`), one commit
  ahead of `origin/local-control`.
- The macOS web service was restarted after `d1e7f0c`; the Home lockout and
  corrected Stop payload are deployed.
- Last operator report: the supervised Orca job finished normally. The printer
  had been powered on, but afterward it disappeared from the Mac-hosted hotspot
  and stopped answering MQTT, ICMP, and known local service probes. Its current
  power and physical state were not reconfirmed after that observation. Always
  ask before a new physical action.

The worktree contains local user state that must not be modified, staged, or
committed without explicit instruction:

- `.env` is modified and contains local configuration.
- `.playwright-mcp/` is an untracked user/browser artifact directory.

The worktree also contains deliberate, uncommitted project changes from the
2026-07-19 observation-gap investigation and documentation audit:

- `static/ankersrv.js` — suppress redundant heartbeats while telemetry is fresh.
- `tests/test_browser_ui.py` — regression coverage for heartbeat suppression and
  stale-telemetry recovery.
- `HANDOFF.md` and `documentation/printer-findings.md` — complete session record
  and confidence ledger.
- `CLAUDE.md`, `CONTEXT.md`, `documentation/local-macos-service.md`,
  `documentation/printer-test-validation.md`,
  `documentation/local-control-research.md`,
  `documentation/next-step-local-broker.md`, and
  `deploy/local-broker/README.md` — contradiction/safety audit updates.

Do not stage `.env` or `.playwright-mcp/`. The project files listed above are the
intended scope if this follow-up is committed.

## Mandatory safety rules

Read `AGENTS.md` and `CLAUDE.md` before acting.

Never send a command that moves, heats, starts, pauses, resumes, or stops the
physical printer without fresh confirmation that the operator is at the
printer with a safe toolhead path and immediate access to the power switch.
Read-only telemetry is allowed.

Do not put secrets or personal setup values in tracked files, tool output,
commits, PRs, or issues. In particular, do not print the full LaunchAgent
configuration: it contains authentication material. Run
`./scripts/check-secrets.sh` before every stage, commit, or push.

## Session scope and completed work

The branch and PR contain a broad local-control/web-dashboard effort:

- Token-protected remote web access and slicer access controls.
- OrcaSlicer/local macOS service integration.
- External camera/WebRTC support used from mobile/Tailscale clients.
- Mobile UI, status heartbeat, refresh behavior, printer-state presentation,
  and removal of low-value protocol labels from the Live page.
- Control-page temperature pickers, fan controls, bounded jogs, filament
  retract/extrude, live Z adjustment, and print controls.
- Wi-Fi configuration UI work and related layout/polish.
- Server-side normalized printer state and transport separation work.
- Secret/personal-config sanitation and CI secret scanning.

The final part of the session focused on safety defects in Home and the print
controls. Those incidents take precedence over earlier assumptions or UI copy.

## 2026-07-19 supervised controls and observation-gap investigation

### Safety and scope

The operator explicitly confirmed being at the powered-on printer and cleared
each physical-action sequence before it ran. Actions were intentionally ordered
from low risk to higher observability: fan and low heater targets, shutdown,
then bounded X/Y requests. Later, the operator started a small job in Orca while
this project observed it read-only. The local implementation continued to avoid
the official eufyMake application.

No agent should treat that attendance as authorization for a future session.
Obtain fresh confirmation before moving, heating, starting, pausing, stopping,
power-cycling, or otherwise controlling the printer.

### Fan and low-temperature exercise

The first live `M105` timed out even though the web service was reachable.
Restarting `ankerctl` restored an immediate reply. Under operator supervision,
the control path then accepted:

- `M106 S128` — request 50% part fan.
- `M104 S40` — request a 40 C nozzle target.
- `M140 S35` — request a 35 C bed target.

The operator asked that these remain active while `ankerctl` was restarted.
After restart, `M105` reported nozzle `39.00/40.00 C` and bed
`26.16/35.00 C`, proving heater targets persist across an `ankerctl` service
restart. The protocol exposes no fan-state field, so the fan request was
accepted by the control path but could not be independently queried.

The supervised shutdown sent `M107`, `M104 S0`, and `M140 S0`. The immediate
readback was nozzle `40.00/0.00 C` and bed `34.87/0.00 C`: both heater targets
were cleared. Fan-off remains based on the accepted `M107`, because neither the
status burst nor `M105` reports fan state.

### X/Y request exercise: accepted commands, no physical motion

After repeated operator clearance, relative X/Y request pairs were attempted at
1 mm, 10 mm, and finally 50 mm, with the 50 mm sequence repeated three times.
Every leg used separate `G91`, bounded `G1 ... F3000`, and `G90` messages. The
reported coordinate frame returned to the same start after each sequence.

The operator observed no physical movement, including the repeated 50 mm test.
Replies to the axis requests included `echo:Home X` or `echo:Home Y`. Therefore:

- MQTT delivery and printer replies were real.
- Command acceptance and reported position do not prove motion.
- The production firmware appears to require axis homing/trusted coordinates
  before these raw X/Y moves, or otherwise declines them.
- Do not repeat larger moves merely to make them easier to see. Diagnose the
  gating condition first, and keep the existing official-app-free design.

### Orca-started print: what observation could read

The operator submitted a small job from Orca. Read-only observation saw:

1. A queued/start state with zero progress and zero completed layers.
2. Start-sequence heating: `M105` showed nozzle `149/150 C` and bed about
   `43/60 C`.
3. A transition into printing during the printer's own calibration sequence.
4. Decoded notices and normalized telemetry, including observed layers 4, 7,
   and 9 of 43.
5. The physical printer continuing and finishing after all MQTT observation had
   gone silent.

A direct `M105` could time out during the start sequence even while a broader
status query still returned printing state. This established that an empty or
timed-out request is not itself proof that the printer stopped. Passive notices
are normally the better source while they are flowing.

### Observation gap: proven failure boundary

The gap was not a decoder limitation. The broker timeline showed:

- Printer notices at roughly three-second cadence, followed by a valid query
  reply.
- Mac-side `ankerctl` commands continuing to enter the broker.
- At 2026-07-19 09:08:51 CDT, the printer's broker client disconnecting with
  `Host is down`.
- No observed printer reconnect attempt after that disconnect.
- Later commands still reaching the broker but no longer being forwarded to a
  printer subscriber, and no replies/notices returning.
- Restarting `ankerctl` after the completed print did not restore `M105`; the
  supervised read-only live test timed out twice.

This cleanly separates three states that older notes conflated:

1. Browser ↔ web service open: proves only the browser reached `ankerctl`.
2. `ankerctl` ↔ local broker open: proves only the phone-side MQTT client works.
3. Printer ↔ local broker present and publishing: the evidence required for
   actual printer observation/control.

Restarting `ankerctl` can repair state 1 or 2. It cannot force the remote printer
to rejoin Wi-Fi or reconnect its MQTT client when state 3 is absent. Before
restarting anything, inspect the local broker log: if printer publishes are
still growing, investigate `ankerctl`; if the printer client disconnected and
publishes stopped, investigate the hotspot/radio path.

### Network evidence and topology correction

The printer does not use the household access point for this local-control path.
It joins the Mac's `M5C-Local` Internet Sharing hotspot directly. An early probe
showed the Mac's upstream access-point path had 0% loss and sub-millisecond
latency, but that result is irrelevant to the direct Mac-to-printer radio leg.

The relevant checks found:

- All local components healthy when run with the required privileges:
  Mosquitto, dnsmasq, chrony, `bridge100`, DNS/NTP pf redirects, and the printer
  egress anchor all passed `deploy/local-broker/verify.sh`.
- The hotspot remained active on 2.4 GHz channel 11.
- The configured printer hotspot address had 100% packet loss, no ARP neighbor,
  and no response on known local service ports.
- macOS could not report a current printer RSSI because no hotspot client was
  associated. Unified Wi-Fi logs did not retain a useful disassociation/RSSI
  event for the failure window.

The leading root-cause hypothesis is therefore a weak or interrupted direct
Mac-hotspot ↔ printer Wi-Fi link. A changed printer lease/address is not fully
excluded, but the broker's `Host is down`, missing ARP entry, and lack of a
reconnect attempt all support printer-side hotspot disappearance. The local
broker stack itself was not down.

### Redundant heartbeat traffic and implemented mitigation

Offline packet packing showed `M105` and a typical `G1 X50` request are both
129-byte MQTT packets; `APP_QUERY_STATUS` is 97 bytes. Before the disconnect,
129-byte command publishes appeared about every 10–11 seconds, matching the web
UI heartbeat interval. The browser was sending `M105` at a fixed ten-second
cadence even while the printer already published telemetry every few seconds.

This was wasteful and a plausible stress multiplier, though it is not proven to
have caused the radio disconnect. The uncommitted fix in `static/ankersrv.js`:

- Treats recent `/ws/state` telemetry as stronger liveness evidence than a new
  `M105`.
- Cancels/skips a pending heartbeat while telemetry is younger than 15 seconds.
- Resumes one heartbeat probe at the next interval after telemetry becomes
  stale, retaining idle/disconnect detection.

The public-interface regression in `tests/test_browser_ui.py` drives normalized
state traffic into the browser websocket, proves that the next ten-second probe
is suppressed, then proves probing resumes after the stale threshold. This
mitigation reduces avoidable traffic during prints; it cannot recover an MQTT
client that has already fallen off the hotspot.

### Validation for the uncommitted mitigation

Completed after the change:

```text
20 browser tests passed
62 non-browser tests passed, 8 skipped, 20 deselected
node --check static/ankersrv.js passed
git diff --check passed
secret sweep passed
local-broker privileged verification: ALL OK
```

The focused regression was first observed red (`1` redundant heartbeat instead
of `0`) and then green after the minimal JavaScript change. There has been no
second live print with the change and improved radio placement, so prevention
of the original disconnect remains `UNVERIFIED`.

### Highest-value next test

1. With fresh operator confirmation, improve the direct radio path temporarily:
   move the Mac closer, reduce obstructions, or test with the printer and Mac in
   the same room. Reassociate or power-cycle only with explicit authorization.
2. Confirm the expected hotspot lease has an ARP entry and stable ping before
   opening the web controls.
3. Observe printer MQTT notices at the broker without sending commands.
4. Run a continuous, timestamped ping and broker-client monitor during another
   small Orca-started print; do not add fixed-rate manual `M105` queries.
5. If the print remains observable, treat radio placement as the root cause and
   pursue a durable access point/travel-router arrangement near the printer
   while preserving the isolated local-broker subnet and cloud egress block.
6. If it disconnects again with a strong link, capture the broker disconnect,
   hotspot association events, and packet cadence before changing more code.

Do not claim the observation gap is fully fixed until that live validation
passes. The current result is: failure boundary confirmed, network cause
strongly supported, redundant-polling defect fixed offline.

## Homing incident and current containment

Two standalone web homing approaches were unsafe on this M5C:

1. Raw `G28` drove the nozzle into the build plate and mechanically loaded the
   toolhead/gantry instead of stopping on the nozzle probe.
2. App-level `MOVE_ZERO` (`commandType: 1026`, `value: 2`) produced the same
   unsafe downward motion. The operator cut printer power.

A later normal print-start sequence performed controlled probing correctly
after heating. Read-only telemetry showed the print operating at a 220 C
nozzle target and 60 C bed target. This proves the physical nozzle/load probe
works, but it does not prove that standalone web homing is supported.

The published M5C Marlin source shows specialized probing paths guarded by
internal homing/alignment state. A raw homing opcode is therefore not evidence
of a complete probe-preparation sequence.

Current containment:

- The Home button is always disabled in the UI.
- `/ws/ctrl` rejects `MOVE_ZERO` before MQTT forwarding.
- `/ws/ctrl` rejects bare `G28`, line-numbered or multiline variants, and any
  `G28` containing Z.
- Explicit X/Y-only `G28 X Y` remains available for diagnostics, but it never
  establishes a Z home.
- Live-test fixtures no longer contain standalone homing.
- Do not re-enable Home based on another command/value guess.

Relevant commits:

- `22c8bd3` — disable unsafe standalone homing
- `14e34d2` — block direct web Z homing
- `e088c2c` — attempted app-level Home; live test proved it unsafe
- `12f726c` — restore UI lockout and add server-boundary rejection
- `ffaea8c` — remove homing from live-printer fixtures

## Print-control incident

The communication module owns streamed print execution. MCU G-code alone does
not reliably control the job:

- `M2022`/`M2023` do not reliably pause/resume a streamed job.
- `M2024` clears buffered MCU motion and cools the printer, but it does not
  necessarily cancel the communication-module job stream.
- `PRINT_CONTROL` (`commandType: 1008`) is required for job-level control.

Pause/Resume currently send values 1/2 with `userName` and `filePath`. A clean
earlier test showed Pause parking the head, but it remains unverified whether
the username must match the job's original uploader. Behavior may differ for
jobs originating from OrcaSlicer, the web uploader, or eufyMake.

Stop had originally been captured and live-validated with the minimal payload:

```json
{"commandType": 1008, "value": 0}
```

Stop also sends `M2024` to clear MCU-buffered motion.

A regression routed Stop through the Pause/Resume helper and added
`userName`/`filePath`. During this session's live print:

- The UI Stop did not cancel the communication-module job.
- `M2024` cooled/stopped the MCU side.
- Read-only telemetry still showed a present job and increasing progress.
- Nozzle telemetry fell from printing temperature toward 60 C while the job
  stream continued, creating a cold-extrusion hazard.
- The operator powered the printer off.

Commit `d1e7f0c` restores the exact minimal Stop payload plus `M2024`, updates
browser regression coverage, and records the incident. It is deployed but has
not yet been revalidated on a live print.

## Jog and live-fixture corrections

Marlin treats `;` as the beginning of a comment. The earlier string
`G91;G1 ...;G90` executed only `G91`, silently discarding the move and the
return to absolute mode. Jog commands now send `G91`, the bounded `G1`, and
`G90` as separate MQTT messages.

The live jog test follows the same pattern and restores `G90` in a `finally`
block. The formerly named “safe” print fixtures no longer contain cold `G28`
or XY motion; they use no-motion dwell commands.

## Validation completed before the 2026-07-19 follow-up

The committed Home/Stop safety work previously reported:

```text
79 passed, 8 deselected
```

Also completed:

- `node --check static/ankersrv.js`
- Browser/UI payload tests
- Server-side websocket homing rejection tests
- `git diff --check`
- `./scripts/check-secrets.sh`

No live Home validation is permitted under the current implementation. The
restored Stop correction has offline/browser coverage only and must not be
described as revalidated on a live print yet. Current validation for the newer,
uncommitted heartbeat mitigation is recorded in the July 19 section above.

## Recommended next work

Track the work in
[issue #5](https://github.com/bigminer/ankermake-m5-protocol/issues/5).

1. Keep Home disabled and the server rejection in place.
2. Capture a complete known-good official print-start/calibration flow,
   including the state that arms the nozzle probe. Reconcile it with the
   published firmware before designing a standalone workflow.
3. Accept that safe standalone Home may not be exposed by production firmware;
   if so, permanently omit the feature.
4. Determine Pause/Resume job-identity requirements for each upload origin.
5. Add UI acknowledgement/state-transition handling. MQTT delivery alone must
   not be presented as physical success.
6. Revalidate Stop only with a fresh operator confirmation and a supervised,
   no-extrusion/no-homing fixture. Verify that progress stops and printer state
   leaves printing; if it does not, instruct immediate physical power-off.
7. Update the GitHub issue with live evidence and only then adjust confidence
   messaging or control availability.

## Useful commands

Safe, non-live test suite:

```sh
PYTHONPATH=. .venv/bin/pytest -q -m 'not live_printer'
```

Secret and diff checks:

```sh
./scripts/check-secrets.sh
git diff --check
```

Local read-only service check:

```sh
curl -fsS http://127.0.0.1:4470/api/version
```

Do not run live-printer tests merely because their environment flags are
available. The operator confirmation in the current session is mandatory.
