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
export ANKERCTL_TEST_BASE_URL=http://100.115.64.31:4470
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
- Pause/Resume remain `M2022`/`M2023`. Delivery caveat, observed live: MQTT
  G-code shares the comm-module-to-MCU serial pipe behind flow control, so
  a motion buffer full of very slow moves delays delivery by minutes. Real
  prints drain fast, keeping latency low.
- Browser payload test updated for the dual-path Stop.

Remaining:

1. Learn the app's Pause/Resume `PRINT_CONTROL` values (the app uses local
   PPPP when on the printer's LAN, so cloud MQTT capture only works when
   the phone is off-LAN) and consider switching Pause/Resume to them.
2. Automate the supervised live test using `tests/fixtures/slow_safe.gcode`
   (cold slow motion; note buffered-delivery latency makes assertions slow)
   or a fast-move streaming fixture; assert state via 1000/subType 1 and
   `APP_QUERY_STATUS` 0x403.
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
8. With motion allowed, home and run 1mm jog checks.
9. With print allowed, upload `tests/fixtures/tiny_safe.gcode`.
10. With G36 enabled only for this supervised session, upload
    `tests/fixtures/g36_resolved.gcode` and verify invalid G36 fixtures are
    rejected before upload. Note: completion is currently expected to fail;
    see "G36 Validation Result" above.
