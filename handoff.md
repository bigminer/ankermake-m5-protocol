# Session handoff

Last updated: 2026-07-20

## Current repository state

- Working branch: `local-control`
- Remote branch: `origin/local-control`
- Upstream draft PR: [anselor/ankermake-m5-protocol#15](https://github.com/anselor/ankermake-m5-protocol/pull/15)
- Parent design issue: [bigminer/ankermake-m5-protocol#6](https://github.com/bigminer/ankermake-m5-protocol/issues/6)
- The completed implementation and session-closeout history is pushed to
  `origin/local-control`; the existing upstream draft PR tracks that branch.
- The macOS web service is running the local code. Named-action validation mode
  was returned to `false`; the new Pause/Resume/Stop path is not enabled for
  normal use.
- Final observed printer state before shutdown: state 0, no active job, nozzle
  target 0, bed target 0. The synthetic upload attempts caused beeps but no
  active job, heating, homing, extrusion, or observed motion. The operator then
  powered the printer off. A subsequent 16-second read-only check saw zero new
  printer broker publishes and no response to three pings. No disconnect line
  arrived during that sample, so power-off is confirmed by the operator report
  plus network absence, not by a captured disconnect event.
- This session is closed with no active printer work. Always obtain new
  current-session operator confirmation before any later physical action.

The worktree contains local user state that must not be modified, staged, or
committed without explicit instruction:

- `.env` is modified and contains local configuration.
- `.playwright-mcp/` is an untracked user/browser artifact directory.

The Chrony PID-file repair and its documentation were committed in `261f8ce`.
Do not stage `.env` or `.playwright-mcp/`. Any documentation changes below are
the intended scope of the current live follow-up.

The current project work completed the issue #7 server-owned snapshot
foundation and the issue #8/#11 named Stop/Pause/Resume action path. Those
three implementation issues are closed. The action path remains disabled by
default and still needs supervised live validation in #9 and #16.

An attended follow-up found and fixed two additional preflight gaps: normalized
state omitted the real 1000/subType 1 `value`, and PPPP file transfer did not
check its one-byte acknowledgement result. Synthetic no-motion uploads received
valid transfer acknowledgements but never became active jobs, so no named
Pause/Resume/Stop action was sent. Final state was idle with both targets zero;
the local validation-mode setting was returned to `false`.

## Session closeout and GitHub disposition

This effort is deliberately done for now. There is no active monitoring,
validation, or printer action to resume automatically.

| Issue | Final session disposition |
| --- | --- |
| #5 — original Home/Pause/Stop incident | Already closed as not planned; received a final comment pointing to the replacement issue tree and the 2026-07-20 failure evidence |
| #6 — deep Printer-action module | Open parent; updated with the completed slices, safe-suite result, invalid synthetic fixture, and paused status |
| #7 — server-owned Printer snapshot | Closed completed |
| #8 — Protective Stop tracer bullet | Closed completed for offline implementation; #9 retains live validation |
| #9 — supervised Protective Stop | Open; synthetic attempt was invalid and no Stop was sent |
| #11 — Pause/Resume migration | Closed completed for offline implementation; #16 retains live validation |
| #16 — supervised Pause/Resume | Open; synthetic attempt was invalid and neither action was sent |

Issues #10 and #12-#19 remain open future slices under #6. No claim is made
that the whole parent design is complete. GitHub follow-up comments record that
the completed session history was published to `origin/local-control`.

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

## 2026-07-20 same-room and cold-boot follow-up

The operator moved the Mac into the printer's room and also power-cycled the Mac.
Those two changes are confounded: the printer's recovery may be due to stronger
signal, recreation of Internet Sharing during boot, or both.

The printer did rejoin the Mac-hosted hotspot and local broker. Fresh notices
arrived every three seconds, and passive `/ws/state` delivered nozzle 23 C with
target 0 C. The `ankerctl` cached PPPP address matched the live printer source.

An important test correction: `setup.local.conf` still named a household-LAN
address routed through `en0`. The first 30- and 120-packet samples tested that
wrong path and are `INVALID-TEST` for hotspot quality. The ignored local config
was corrected to the printer address taken directly from its broker connection.
The valid hotspot sample routed through `bridge100`: 30/30 replies, 0% loss,
3.34 ms average, 10.96 ms maximum. After daemon reload it remained 10/10 with a
2.60 ms average and fresh MQTT notices.

The cold boot exposed a separate persistence defect. Chrony crash-looped because
`/opt/ankerm5c/chronyd.pid` survived reboot with PID 309, while the new boot had
assigned PID 309 to `storagekitd`. UDP/123 therefore had no listener. A new
regression test reproduces the configuration error. The PID file now lives at
`/var/run/com.ankerm5c.chronyd.pid`, which is boot-cleared. After reinstall:

- the regression test passes;
- Chrony is `running`, one launch, with its runtime PID naming `chronyd`;
- privileged local-broker verification reports `ALL OK`;
- printer MQTT notices resumed immediately after the broker reload;
- the actual hotspot path remained lossless.

This proves the immediate repair. The PID-file fix still needs one additional
cold boot before boot persistence can be called `CONFIRMED`. The observation-gap
mitigation still needs a small print monitored from start to finish in the new
same-room placement.

## 2026-07-20 same-room live-print retest

### No-motion communications and heater/fan scenarios

With fresh operator clearance, repeated `M105` reads succeeded before and after
an `ankerctl` restart. The supervised sequence exercised 25%, 50%, and 100%
part-fan requests, 40 C nozzle and 35 C bed targets, 30-60 second idle periods,
and a service restart while targets remained active. Consecutive temperature
reads continued to reply. The final `M107`, `M104 S0`, and `M140 S0` requests
left both heater targets at 0. The operator heard the fan running but could not
distinguish the requested speed tiers, so fan operation is physically confirmed
for the sequence while speed accuracy remains unverified.

### Passive Orca-job monitor

The operator then started a 43-layer job from Orca. A persistent passive monitor
watched normalized state, raw broker traffic, disconnects, and a five-second
ping over the actual `bridge100` hotspot path. It deliberately sent no periodic
`M105` query. The monitor observed preheat, the printer's calibration phase,
and printing through layer 25. The operator physically observed nozzle probing;
the raw notice types seen during calibration contained no explicit probe-point
or contact field, so only the phase correlation and physical observation are
confirmed.

The earlier observation gap did not recur during this run. At monitor shutdown:

- 1,099 normalized state messages and 308 printer notices had arrived;
- the printer had zero observed broker disconnects;
- hotspot ping was 177/177 with 2.9 ms average and 20.9 ms maximum;
- updates remained current at roughly three-second cadence.

This is strong evidence that the same-room/hotspot setup can sustain observation,
but it is not a completed-print validation: the operator physically aborted the
job at layer 25 after the web-control failures below. Moving the Mac and rebooting
it remain confounded, so do not attribute recovery to signal strength alone.

### Pause and Stop failed on the Orca-started job

The web Pause attempts produced six outbound MQTT publishes and six printer
replies, but progress continued and the printer advanced from layer 18 to 19.
No pause/park state transition appeared.

The web Stop produced two additional publishes and replies, matching the UI's
minimal `PRINT_CONTROL value=0` plus `M2024` pair. The nozzle immediately cooled
from 220 C and the bed began cooling, proving the MCU-side stop/heater shutdown
acted, but the communication-module job continued: progress and elapsed time
increased and layers advanced through 25. This recreates the cold-extrusion
hazard even with the restored minimal Stop payload when the job originates from
Orca. A command reply is therefore not proof of a successful job transition.

The operator then held the physical square button. Telemetry reset from layer
25/43 to layer 0, job/progress frames ceased, and the toolhead moved to the
back-left with Z raised. That position is a confirmed physical observation but
is not established as firmware home. A later passive read showed nozzle 45 C
to 42 C with target 0 and bed about 48 C with target 0.

Pause/Resume now use the trusted identity recorded when the server accepts an
Orca upload. Stop remains deliberately global and identity-free: it must cancel
whatever job is active, regardless of origin. Treat both paths as unvalidated
for live use until the new server-owned confirmation path passes a supervised
fixture. The physical printer controls remain the tested recovery path.

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
browser regression coverage, and records the incident. The 2026-07-20 retest
documented above showed that it still fails to cancel an Orca-started job.

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
restored Stop correction and the newer named action path must not be described
as successfully revalidated on a live print. The complete session evidence is
recorded above and in `documentation/printer-findings.md`.

## Recommended next work

There is no scheduled next action. If the effort is resumed, track the design
under [issue #6](https://github.com/bigminer/ankermake-m5-protocol/issues/6),
Stop validation under [issue #9](https://github.com/bigminer/ankermake-m5-protocol/issues/9),
and Pause/Resume validation under
[issue #16](https://github.com/bigminer/ankermake-m5-protocol/issues/16).

1. Keep Home disabled and the server rejection in place.
2. Capture a complete known-good official print-start/calibration flow,
   including the state that arms the nozzle probe. Reconcile it with the
   published firmware before designing a standalone workflow.
3. Accept that safe standalone Home may not be exposed by production firmware;
   if so, permanently omit the feature.
4. Keep the named action path disabled outside supervised validation.
5. Before another Stop attempt, solve the fixture problem: #9 still forbids
   homing and unrelated motion, while this session's synthetic zero-motion files
   never became active jobs. Do not substitute a normal sliced print without a
   separate safety review or explicit revision of that validation contract.
6. If Pause/Resume validation resumes, use the exact server-recorded upload
   identity and a separately authorized, known-safe real print under #16.
7. Revalidate global Stop independently, capture its exact `1008` reply, and
   require job-cleared, inactive-state, and zero-target telemetry. Never add
   Pause/Resume identity fields to Stop.

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
