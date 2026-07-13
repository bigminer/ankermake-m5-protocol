# Printer Test Validation

This project has two test layers:

- Safe automated tests that run without a printer:

  ```sh
  .venv/bin/python -m pytest tests/ -v -m "not live_printer"
  ```

- Live-printer validation tests that run only with explicit opt-in flags and a
  physically present operator.

The configured live endpoint is:

```sh
export ANKERCTL_TEST_BASE_URL=http://127.0.0.1:4470
export ANKERCTL_TEST_TOKEN="<web-ui-token>"
```

## Live Safety Gates

All live tests require:

```sh
export ANKERCTL_TEST_ALLOW_LIVE=1
export ANKERCTL_TEST_SAFETY_CHECKLIST=operator_present,bed_clear,filament_safe,safe_clearance
```

Additional gates are required by risk category:

```sh
export ANKERCTL_TEST_ALLOW_HEATING=1
export ANKERCTL_TEST_ALLOW_MOTION=1
export ANKERCTL_TEST_ALLOW_PRINT=1
export ANKERCTL_TEST_ALLOW_G36=1
```

The G36 upload tests also require:

```sh
export ANKERCTL_TEST_CONFIRM_PREPRINT_G36_ENABLED=1
```

Set that only after temporarily enabling `ANKERCTL_PREPRINT_G36=true` for the
supervised session and restarting `com.ankerctl.webserver`. Disable it again
immediately after validation and restart the service.

## Suggested Commands

Preflight only:

```sh
.venv/bin/python -m pytest tests/test_live_printer.py -v \
  -m "live_printer and not heating and not motion and not print_job and not g36"
```

Heating, fan, and terminal checks:

```sh
.venv/bin/python -m pytest tests/test_live_printer.py -v \
  -m "live_printer and not motion and not print_job and not g36"
```

Motion checks:

```sh
.venv/bin/python -m pytest tests/test_live_printer.py -v -m "motion"
```

This test performs bounded 1 mm relative jogs only. It does not home any axis.
Web full/Z homing is disabled after the 2026-07-13 incidents described below.

Print lifecycle fixture upload:

```sh
.venv/bin/python -m pytest tests/test_live_printer.py -v -m "print_job and not g36"
```

Supervised G36 validation (currently blocked, see below):

```sh
.venv/bin/python -m pytest tests/test_live_printer.py -v -m "g36"
```

## G36 Validation Result (2026-07-09)

Two supervised G36 sessions were run on firmware V3.1.56 with
`ANKERCTL_PREPRINT_COMMAND_TIMEOUT=900`:

- The pre-print hook heated correctly (bed 35C, nozzle 150C confirmed by
  telemetry and the AnkerMake app) and dispatched `G36`.
- The printer acknowledged receipt but performed no leveling motion, reported
  `Idle / Ready to Print` while holding the heat targets, and never returned a
  completion `ok`. The hook timed out and the emergency cooldown worked
  (heater targets verified at 0 via telemetry).
- The invalid fixtures were correctly rejected before upload in both sessions.

This reproduces the behavior recorded under "Disabled G36 experiment" in
[local-macos-service.md](local-macos-service.md): production firmware does not
honor `G36` over MQTT. `ANKERCTL_PREPRINT_G36` must remain `false`, and the
G36 tests validate only fixture rejection and hook dispatch, not leveling.
Do not re-run the resolved-upload G36 test expecting completion until a
firmware-level command contract is confirmed (serial console visibility).

## Web homing disabled (incidents 2026-07-13)

Two supervised attempts drove the nozzle into the plate without the load-based
Z probe stopping the move: raw `G28`, then app-level `MOVE_ZERO` (`ct=1026`,
`value=2`). The operator cut power during both attempts. The Home button is
disabled, and `/ws/ctrl` rejects bare `G28`, any `G28` containing Z, and
`MOVE_ZERO` before they reach MQTT.

Do not add homing back to the live motion test. The published M5C firmware
shows that its specialized Z probing path depends on internal preparation
state; a homing opcode alone is not a safe probe sequence. Re-enable only from
a captured, complete official-app command flow followed by a new safety review.

## Follow-up: fix UI pause/resume/stop (incident 2026-07-10)

Incident: during an app-initiated print, the web UI Stop did not stop the
job. Root cause, confirmed against the published firmware source and a live
MQTT capture:

- The UI sends `M2022`/`M2023`/`M2024` as MQTT G-code (0x0413). The Marlin
  MCU honors them (`ak_gcode_parse` -> `anker_stop_deal`: clears queue,
  quick-stops steppers, disables all heaters), but the M5C communication
  module owns the job and keeps streaming G-code, so the print resumed with
  heaters off (cold extrusion). These M-codes cannot cancel a job.
- The correct job stop is `ZZ_MQTT_CMD_PRINT_CONTROL` (0x3f0 / 1008) with
  `value: 0`, captured live from the eufyMake app: reply arrives on
  `/command/reply` with `reply: 0`, and printer state (1000, subType 1)
  flips 1 (printing) -> 0 (stopped). Pause/resume `value` codes are still
  unknown — capture app presses the same way before implementing.

Fix applied and validated 2026-07-10:

- UI Stop now sends both `{"commandType": 1008, "value": 0}` (cancels the
  job on the communication module) and `M2024` (clears buffered MCU motion).
  Both are required: 1008 alone cannot stop already-buffered moves, M2024
  alone cannot cancel a streaming job. Validated live on a supervised
  streaming job: state 1 -> stop sent -> state 4 and head parked within
  ~25s (state notice granularity ~3s).
- Browser payload test updated for the dual-path Stop.

## Pause/Resume solved via PRINT_CONTROL (2026-07-10)

`M2022`/`M2023` MQTT G-code does not pause an onboard job (the communication
module owns job execution). Pause/Resume also go through
`ZZ_MQTT_CMD_PRINT_CONTROL` (0x3f0 / 1008), but unlike Stop they must
identify the job with `userName` and `filePath`:

```json
{"commandType": 1008, "value": 1, "userName": "...", "filePath": "<job>.gcode"}
```

- `value`: 1 = pause, 2 = resume, 0 = stop.
- Confirmed live (2026-07-10): value=1 with `userName`+`filePath` paused the
  print and parked the head at `X:-10 Y:200 Z:2` with a 0.8mm retract —
  exactly the firmware pause routine (`anker_pause.cpp:240` enqueues
  `G1 X-10 Y200 F9000`). This is distinct from home/center (`X:110 Y:110`),
  ruling out a disguised stop. A new state value 2 also appeared after pause.
- Bare `value` (no identity fields) is a no-op — that is why the earlier
  1,2,3 probes did nothing.

UI implementation: Pause/Resume send PRINT_CONTROL value 1/2; Stop sends the
minimal value 0 payload plus `M2024`. Pause/Resume's `filePath` comes from
print telemetry (1001 `name`), and `userName` is hardcoded `"ankerctl"`.
Those identity fields must not be added to Stop.

Regression observed 2026-07-13: Stop had been routed through the shared
Pause/Resume helper, producing value 0 plus `userName` and `filePath`. During a
live print it failed to cancel the communication-module job; `M2024` cooled the
nozzle while job progress continued, recreating the cold-extrusion hazard. The
operator powered the printer off. Stop now again uses the exact minimal payload
that was captured and live-validated on 2026-07-10.

UNVERIFIED: whether the printer requires `userName` to match the job's
original uploader. The one clean pause used a matching userName; a
filePath-only retest was confounded by leftover pause state and inconclusive.
If the match is strict, the UI buttons will only control jobs uploaded as
`"ankerctl"` (not app-initiated or browser-uploaded jobs). Confirm with a
clean supervised print: upload as userName X, pause with userName Y+filePath,
check `M114` for the `X-10 Y200` park.

Remaining:

1. Resolve the `userName`-match question above.
2. Automate the supervised live pause/resume/stop test using a fast-move
   fixture (e.g. regenerate `stream_stop_test.gcode`); assert the pause park
   via `M114` and state via 1000/subType 1.
3. Surface command delivery in the UI: Stop must confirm the printer's
   reply, and a dead `/ws/ctrl` socket must be unmistakable.

## Expected Live Flow

1. Confirm the bed is clear, filament path is safe, and an operator is present
   at the printer.
2. Confirm the webserver redirects unauthenticated `/` requests to `/login`.
3. Log in with `ANKERCTL_TEST_TOKEN`.
4. Confirm `/api/ankerctl/status` reports active services.
5. Use the Control websocket to send `M105`.
6. Set fan to 50%, then 0%.
7. With heating allowed, set nozzle to 40C and bed to 35C, then cool both to
   0C.
8. With motion allowed, run the bounded 1 mm jog checks. Do not web-home.
9. With print allowed, upload `tests/fixtures/tiny_safe.gcode`.
10. With G36 enabled only for this supervised session, upload
    `tests/fixtures/g36_resolved.gcode` and verify invalid G36 fixtures are
    rejected before upload. Note: completion is currently expected to fail;
    see "G36 Validation Result" above.
