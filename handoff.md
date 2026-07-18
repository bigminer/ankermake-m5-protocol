# Session handoff

Last updated: 2026-07-13

## Current repository state

- Working branch: `local-control`
- Remote branch: `origin/local-control`
- Upstream draft PR: [anselor/ankermake-m5-protocol#15](https://github.com/anselor/ankermake-m5-protocol/pull/15)
- Incident tracker: [bigminer/ankermake-m5-protocol#5](https://github.com/bigminer/ankermake-m5-protocol/issues/5)
- Latest pushed commit: `d1e7f0c` (`Restore minimal M5C stop payload`)
- The macOS web service was restarted after `d1e7f0c`; the Home lockout and
  corrected Stop payload are deployed.
- Last confirmed physical state: the operator powered the printer off after a
  failed UI Stop incident. Confirm its current state with the operator before
  assuming it is still off.

The worktree contains local user state that must not be modified, staged, or
committed without explicit instruction:

- `.env` is modified and contains local configuration.
- `.playwright-mcp/` is an untracked user/browser artifact directory.

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

## Validation completed

Latest non-live validation after the safety fixes:

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
new Stop correction has offline/browser coverage only and must not be described
as live-verified yet.

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
