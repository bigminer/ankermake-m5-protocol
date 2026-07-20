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

These tests prove only that the request path completes; the heating test does
not currently perform an `M105` target assertion after each write. Manual
2026-07-19 readback confirmed the low targets and later zero targets, but the
fixture should add the same check. It cannot prove fan state: neither `M105` nor
the broad status query exposes a fan field. The fan test sends 50% and then off
without an independent assertion.

Motion command-path exercise — **needs redesign/revalidation**:

```sh
.venv/bin/python -m pytest tests/test_live_printer.py -v -m "motion"
```

This test sends bounded 1 mm relative requests only. It does not home any axis
and currently asserts only that the websocket calls complete. On 2026-07-19,
unhomed X/Y requests up to 50 mm produced printer replies containing
`echo:Home X/Y` but no operator-observed movement. Z had moved in an earlier
session, so one generic “small jogs” test now conflates different axis behavior.
Do not use this test as proof of physical motion. Split it into axis-specific
tests with position/readback evidence before running it again. Web full/Z
homing remains disabled after the 2026-07-13 incidents described below.

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

Live revalidation on 2026-07-20 **failed for an Orca-started job**. The deployed
UI sent the minimal `PRINT_CONTROL value=0` payload plus `M2024` and received two
replies. `M2024` cooled both heaters, but print progress continued and layers
advanced from 21 through 25 until the operator used a physical square-button
long-press. Therefore the restored payload must not be described as generally
live-verified or safe. The earlier successful validation and this failure used
different job origins/identity contexts.

Pause failed in the same Orca run: publishes and replies were observed, but the
job advanced from layer 18 to 19 with no pause/park transition. This strengthens
the hypothesis that Pause used the wrong uploader identity, but does not prove
it until the new trusted upload-identity path is exercised live. This identity
requirement applies to Pause/Resume only. Stop remains a global, identity-free
protective action; adding job identity to Stop is a known regression.

UNVERIFIED: whether the printer requires `userName` to match the job's
original uploader. The one clean pause used a matching userName; a
filePath-only retest was confounded by leftover pause state and inconclusive.
If the match is strict, the UI buttons will only control jobs uploaded as
`"ankerctl"` (not app-initiated or browser-uploaded jobs). Confirm with a
clean supervised print: upload as userName X, pause with userName Y+filePath,
check `M114` for the `X-10 Y200` park.

Remaining:

1. Revalidate Pause/Resume using the uploader identity recorded by the server.
2. Revalidate global Stop independently; do not add identity fields to its
   payload. Capture the exact `1008` reply value and all subsequent state.
3. Use a supervised no-extrusion/no-homing fixture. Assert Pause/Resume against
   the same job and Stop against job-cleared, inactive-state, and zero-target
   telemetry. A reply without those transitions is not success.

The server-owned action path implements these gates offline. It is disabled
unless `ANKERCTL_ACTION_VALIDATION_MODE=true`, journals acceptance before
sending, never replays unresolved actions after restart, and reports
`accepted`, `confirmed`, `rejected`, `superseded`, or `indeterminate`. It still
`NEEDS LIVE REVALIDATION` before enabling normal UI use.

The first attended attempt on 2026-07-20 stopped before any named action was
sent. Several synthetic zero-motion files were accepted by the PPPP transfer
and caused a printer beep, but the printer stayed in state 0 and emitted no
1001 active-job notice. Those runs are `INVALID-TEST` for Pause/Resume/Stop.
They did expose and fix two preflight defects: state normalization now handles
1000/subType 1 `value`, and file transfer now rejects non-OK or malformed AABB
acknowledgements. Validation mode was disabled again after the attempt.

## Expected Live Flow

1. Confirm the bed is clear, filament path is safe, and an operator is present
   at the printer.
2. Confirm the webserver redirects unauthenticated `/` requests to `/login`.
3. Log in with `ANKERCTL_TEST_TOKEN`.
4. Confirm `/api/ankerctl/status` reports active services, but do not treat
   `Running` as printer reachability.
5. Check the local broker log for recent printer PUBLISHes and confirm the
   hotspot lease has a current neighbor/reply. A browser socket and an
   `ankerctl` broker connection are insufficient.
6. Use the Control websocket to send `M105`. A timeout is a failed observation,
   not evidence that the physical printer stopped.
7. Set fan to 50%, then 0%; record that fan state cannot be queried.
8. With heating allowed, set nozzle to 40C and bed to 35C, then cool both to
   0C.
9. Do not run the combined motion test until it is redesigned as described
   above. Do not web-home.
10. With print allowed, upload `tests/fixtures/tiny_safe.gcode`; it is a
    no-motion dwell/cooldown transport fixture, not a motion or extrusion test.
11. With G36 enabled only for this supervised session, upload
    `tests/fixtures/g36_resolved.gcode` and verify invalid G36 fixtures are
    rejected before upload. Note: completion is currently expected to fail;
    see "G36 Validation Result" above.
