# Printer Findings Ledger

**Read this before any printer work.** It is the canonical record of what we know
about this M5C, how we learned it, and — critically — **how much to trust each
claim**. Append to it as findings land. Never delete a refuted entry; mark it
`REFUTED` and say why. A wrong belief we can see is safer than one we re-derive.

## Status legend

| Status | Meaning |
| --- | --- |
| `CONFIRMED` | Directly observed, reproduced, or read from firmware source. |
| `STRONG` | Multiple consistent lines of evidence, no direct proof. |
| `UNVERIFIED` | Plausible, untested. Do not act as if true. |
| `INVALID-TEST` | We ran a test; the test could not have measured what we thought. |
| `REFUTED` | We believed it; evidence killed it. Kept so we don't re-derive it. |
| `SESSION-ONLY` | True until the next power cycle. Worthless after. |

## Document map

| Doc | Role |
| --- | --- |
| `method.md` | **Read first.** Goal, source hierarchy, guardrails. Decides what counts as evidence here. |
| `printer-findings.md` (this) | What we know + confidence. **Entry point for findings.** |
| `local-macos-service.md` | Runbook: setup, topology, recovery procedures. |
| `printer-test-validation.md` | Test gates, live-test procedure, validation runs. |
| `local-control-research.md` | Long-form research narrative. |
| `jog-confirmation-research.md` | What can confirm a jog (issue #12). Design input, not a ledger entry. |
| `next-step-local-broker.md` | Local-broker cutover notes. |
| `audit-2026-07-27.md` | Contradiction sweep and its dispositions. |
| `../CONTEXT.md` | Domain glossary for Printer-action language. |
| `../docs/adr/` | Architecture decisions (gating, no-replay, typed action interface). |
| `CLAUDE.md` / `AGENTS.md` | Safety + secret rules. Binding, regardless of evidence. |

---

## Verified command reference

**Every row was run against this printer and the evidence is the actual reply.**
Timestamps are local (UTC-5). If a command isn't here, we have not verified it —
do not assume it behaves as stock Marlin does. `M401` is the cautionary tale: it
looked inert and moved the toolhead 14.9mm.

### Reads — safe, no motion, no heat

| Command | Does | Evidence (verbatim reply) | Verified |
| --- | --- | --- | --- |
| `M114` | Reports position and planner counts — **not** live stepper reality; see the 2026-07-27 correction below | `X:-15.00 Y:232.50 Z:11.55 E:0.00 Count X:-1920 Y:29760 Z:4620` | 2026-07-15 00:38 |
| `M119` | Endstop pin states | `x_min: open` `y_max: open` `z_min: open` `z2_min: open` `z_probe: open` | 2026-07-15 01:03 |
| `M851` | Probe offset | `Probe Offset X0 Y0 Z0.02` | 2026-07-15 01:03 |
| `APP_QUERY_STATUS` — commandType **1027** (`0x403`), no payload | Bursts ~16 telemetry types the UI never asks for. **No position field** — fully enumerated in the 2026-07-27 entry below | `1039 {"breakPoint":1}`, `1072 {"isLeveled":1}`, `1052 {...}`, `1067 {button map}`, `1098 {"filamentType":["PLA"]}` | 2026-07-14 21:55; enumerated 2026-07-27 |

⚠️ **`M119` cannot see StallGuard.** `SENSORLESS_HOMING` is enabled; if Z detection
is stall-based it only registers **during motion**. `z_probe: open` on a stationary
nozzle — even one pressed hard into the plate — proves nothing. See `INVALID-TEST`
in Retracted claims.

### Writes — these move the printer. Operator confirmation required.

| Command | Does | Evidence | Verified |
| --- | --- | --- | --- |
| `M401` | ⚠️ **Lifts Z ~14.9mm** and sets `Z:2.00`. Does **not** arm the probe. | count `-5160`→`800` (+5960 = 14.9mm), camera confirmed ~15mm lift; `M119` still `z_probe: open` after. `Z:2.00` exactly matches `ANTHER_Z_RISE_DISTANCE 2` | 2026-07-15 01:01:57 |
| `G91` / `G1 Z<n>` / `G90` | Relative **Z** jog. **Send as three separate messages** — Marlin treats `;` as a comment, so `G91;G1...;G90` silently runs only `G91`. Do not generalize this result to X/Y: later unhomed X/Y requests replied `echo:Home X/Y` and did not move. | Z jog traces track exactly 400 counts/mm | 2026-07-15 00:38–01:01 |
| `G28 X Y` | Expected to home X/Y against **real** endstops (`x_min`, `y_max`). The only homing form `/ws/ctrl` permits | guard logic in `web/__init__.py`; endstops present in `M119` | behavior **NOT run live** — `UNVERIFIED`, not established safe |

### Known-dangerous — do not send

| Command | Why |
| --- | --- |
| `G28` (bare), `G28 Z`, any `G28` with Z | Drives nozzle into plate. Blocked at `/ws/ctrl`. |
| `MOVE_ZERO` (1026 / `0x0402`) | Same. Blocked at `/ws/ctrl`. |
| `G36` | ACKs, **never produces leveling motion, never returns a completion `ok`** — three sessions agree. Whether it also *wedges the queue and needs a power cycle* is **contested**: recorded in one early experiment, **not reproduced** in the two supervised 2026-07-09 sessions, which saw `Idle / Ready to Print` and a working heater cooldown. Not the command the working print flow uses — the slicer's start G-code homes with **`G28`**. |
| `RECOVER_FACTORY` (1029 / `0x0405`) | Factory reset. Destroys printer config. |
| `M402` | Untested. Presumed inverse of `M401` — may **lower** Z ~15mm. |

### Unverified but likely useful

| Command | Expected | Status |
| --- | --- | --- |
| `G92 Z0` | Expected to declare current position as zero without motion; proposed mechanism for manual logical zeroing. | `UNVERIFIED` — not yet sent/observed on this printer |
| `M290 Z<n>` | Babystep. **Invisible to `M114`** (shifts carriage without changing logical position) — will desync any position monitor. The UI's z-offset buttons use this; the jog buttons don't. | `STRONG`, inferred from `static/ankersrv.js` + count behaviour |
| `M500` / `M501` | Save/load EEPROM. Untouched. | `UNVERIFIED` |

---

## Tooling: `scripts/printer-probe.py`

Consolidates the throwaway scripts every session kept rewriting.

```sh
scripts/printer-probe.py pos          # M114 - position + stepper counts
scripts/printer-probe.py endstops     # M119 + M851 (prints the StallGuard caveat)
scripts/printer-probe.py status       # APP_QUERY_STATUS burst, annotated
scripts/printer-probe.py watch 120    # poll M114, print changes only
scripts/printer-probe.py gcode "M105" # arbitrary send; refuses the dangerous set
```

| Aspect | Status |
| --- | --- |
| Dangerous-command guard (`G28`/`G28 Z`/`G28 X Z`/`N20 G28 Z`/`g28 z`/`G36`/`M402` refused; `G28 X Y`/`G28 X`/`M114`/`M119`/`M851`/`G92 Z0` allowed) | `CONFIRMED` 2026-07-15 01:20 |
| `status` and `gcode` live paths | `CONFIRMED` 2026-07-27 — `status` run three times (one produced the full 1027 enumeration), `gcode` twice. Note `gcode` filters replies starting `ok T:`, so an `M105` sent through it prints nothing; that is the filter, not a failure. |
| `pos` / `endstops` / `watch` live paths | `UNVERIFIED` — still never exercised in this form. **Test before trusting.** |

## Transport quick reference

**Auth** (token is *not* in `.env` — it's in the LaunchAgent):
```sh
plutil -extract EnvironmentVariables.ANKERCTL_TOKEN raw -o - \
  ~/Library/LaunchAgents/com.ankerctl.webserver.plist
# then POST it to /login as `token=<value>` to get a session cookie.
# Pass via a body file, not argv — keeps it out of `ps` and out of logs.
```

**Send G-code** — `ws://127.0.0.1:4470/ws/ctrl`:
```json
{"mqtt": {"commandType": 1043, "cmdData": "M114", "cmdLen": 4},
 "awaitResponse": true, "requestId": "anything"}
```
`1043` = `0x0413` = `ZZ_MQTT_CMD_GCODE_COMMAND`. Shape mirrors `sendGcode()` in
`static/ankersrv.js`.

**Send a query** — same endpoint, no cmdData: `{"mqtt": {"commandType": 1027}}`

**Feeds:** `/ws/mqtt` = raw · `/ws/state` = normalized (nozzle/bed/print/speed/state)

### Gotchas that cost real time on 2026-07-14/15

| Gotcha | Reality |
| --- | --- |
| `/ws/ctrl` replies `{"ankerctl": 1}` | **That is not the printer's reply.** It's an ack from ankerctl. The real reply arrives on `/ws/mqtt` as commandType `1043` with `resData`. Listen there. |
| `1043` traffic floods with temp polls | Before the then-uncommitted 2026-07-19 mitigation (now merged into `main` through PR #20), the browser polled `M105` every 10s even while telemetry flowed. Filter replies starting `ok T:` when reading older captures. Fresh `/ws/state` traffic now suppresses the next poll in browser tests; live revalidation is still needed. |
| Background monitors print nothing | Python buffers stdout to a file. Use `python -u`. |
| Playwright screenshots vanish | They land in the **repo root**, not the output dir. Move them out; keep the worktree clean. |
| `ankerctl mqtt monitor` fails to connect | It dials cloud (`make-mqtt.ankermake.com`). The printer is on the **local broker**. Use the running service's websockets instead. |
| Printer silent right after a power cycle | Needs 30–60s to rejoin the `M5C-Local` hotspot. Silence ≠ a result. `ping` the hotspot lease first. |
| Replies carry a `+ringbuf:N,512,M` suffix | Anker-specific. Ignore it when parsing. |
| **Sends fail *silently* when ankerctl is wedged** | No error, no timeout, no clue. Confirm telemetry is flowing *before* sending. `2026-07-15 01:25` |
| "The printer is silent" means **ankerctl**, not the printer | `REFUTED` as a general rule on 2026-07-19. It described the 2026-07-15 wedge, but a later print lost the printer's broker client and hotspot neighbor while `ankerctl` and the local stack stayed healthy. Check the broker log first and branch on whether printer PUBLISHes continue. |

### ⚠️ FIRST: locate the silent layer before restarting anything

Check `/opt/ankerm5c/logs/mosquitto.out.log` first:

- Printer PUBLISHes are still growing but web state is stale: the printer and
  broker are alive; an `ankerctl` restart is a supported recovery attempt.
- The printer client disconnected and PUBLISHes stopped: restarting `ankerctl`
  cannot force the remote printer back onto the hotspot. Check ARP/ping,
  hotspot association, and radio placement. Any printer power cycle still
  requires a present operator and explicit authorization.

The restart-first account below is retained as a dated incident, not a general
runbook.

```sh
launchctl kickstart -k gui/$(id -u)/com.ankerctl.webserver
```

`CONFIRMED` 2026-07-15 01:47. **ankerctl's MQTT and PPPP service threads wedge.**
They keep reporting `Running` while receiving nothing. Symptoms look exactly like a
dead printer: no telemetry, jog buttons do nothing, uploads stall at `Sending file
contents`, `M114` gets no reply. `/ws/pppp-state` throws `ServiceStoppedError`.

**In that 2026-07-15 incident, the printer was fine.** The distinguishing check
was what the broker was actually receiving:
```sh
tail -f /opt/ankerm5c/logs/mosquitto.out.log   # printer's own PUBLISHes
```
If that is growing, the printer-to-broker path is healthy and `ankerctl` is the
likely problem. If it is not growing, do not infer the same diagnosis; the
2026-07-19 hotspot/MQTT disconnect requires separate network recovery.

This cost an hour on 2026-07-15 chasing pf anchors, dnsmasq, and mosquitto — **all
healthy**. The printer had rejoined the broker minutes after a power cycle and was
publishing every ~3s throughout. Do not repeat that.

### DEFECT (FIXED 2026-07-15): the UI reported success for commands that never landed

`CONFIRMED` 2026-07-15 01:30. With ankerctl wedged, the operator clicked jog Z+1mm
several times: buttons **enabled**, **no error**, nothing moved, nothing logged.

**Fix applied** (`static/ankersrv.js`): the heartbeat machinery already tracked
liveness (`lastPrinterHeartbeat` / `lastTelemetry`, 15s stale window) and
`updatePrinterState()` already resolved to `"Offline"` — the controls just never
consulted it. Now:

- `printerIsLive()` extracted as the single source of truth
- `updateAttendedControls()` gates on `ctrlReady() && printerIsLive()`
- controls re-evaluate on the heartbeat interval **and** on each heartbeat reply
  (liveness changes there, and nothing else re-ran them)
- `sendMqtt()` refuses non-heartbeat sends when offline — **the heartbeat is
  exempt**, since it is the probe that restores liveness; blocking it would make
  recovery impossible

Covered by `test_controls_disable_when_the_printer_stops_answering` and
`test_offline_printer_refuses_to_send_but_still_heartbeats`. Note
`test_control_buttons_enable_when_ctrl_socket_opens` was **renamed** to
`test_control_buttons_require_a_live_printer` — it asserted the old, buggy
contract (enabled purely because a socket opened).

Original analysis follows.

Cause (`static/ankersrv.js:426`):
```js
const controlReady = sockets.ctrl && sockets.ctrl.is_open;
```
That's the **browser's socket to ankerctl** — it says nothing about whether the
command reached the printer. `/api/ankerctl/status` has the same flaw: its
`Running` states describe ankerctl's threads. **Nothing in the stack tracks whether
the printer received anything.**

Note `filetransfer` is the one layer that *does* fail loudly — it waits for block
acks and aborts after 15s. That's the model for a fix: gate controls on evidence
the printer answered (e.g. last-telemetry age), not on socket state.

This is recommended-work item 5 from `handoff.md`, now evidenced. Independent of
the wedge bug: any dropped link produces the same silent failure.

### Stranded commands

Commands sent while ankerctl is wedged vanish. `G91`/`G1 Z1`/`G90` sent 2026-07-15
01:25 **never executed** — camera confirmed the toolhead unmoved after reconnect.
Whether the broker can queue commands across a session is `UNVERIFIED`; no evidence
of it so far. Still: confirm telemetry is flowing before sending anything.

---

## Homing — solved from source (2026-07-28)

**The central open problem has an answer, and it is not a missing opcode.**

`G28.cpp:224` `anker_home_z_safely()` is the routine this build's `G28` actually
calls for Z (via `WS1_HOMING_5X`, `G28.cpp:594`). It performs real Z homing only
when **two** conditions hold:

```cpp
if (thermalManager.degHotend(0) >= EXTRUDE_MINTEMP && anker_align.g36_running_flag == true)
{  homeaxis(Z_AXIS); ... Probe_homeaxis(Z_AXIS, 1); ... }
else
{  anker_homing.is_home_z = true; }        // no motion, no probing — only a flag
```

| Finding | Evidence | Status |
| --- | --- | --- |
| Real Z homing requires nozzle **≥ `EXTRUDE_MINTEMP`** *and* **`g36_running_flag`** | `G28.cpp:263` | `CONFIRMED` |
| `EXTRUDE_MINTEMP` is **160C** | `Configuration.h:719` | `CONFIRMED` |
| `g36_running_flag` is set `true` in **exactly one place** — `auto_align()`, i.e. **`G36`** | `anker_align.cpp:96`; cleared `:130`, `:175`, and in `anker_pause.cpp` | `CONFIRMED` |
| **`G36` calls `G28` itself** — it is the entry point for homing, not a separate leveling command | `anker_align.cpp:100` | `CONFIRMED` |
| ~~**Therefore a standalone `G28` can never home Z.** It takes the `else` branch and only marks `is_home_z=true`~~ | ~~follows from the above~~ | **`REFUTED` same day — see the descent trace below.** The `else` branch *defers* homing, it does not skip it |
| A failed alignment (`ABS(z1-z2)` over range, or overpressure) calls **`kill()`** — a hard halt needing a reset | `anker_align.cpp:122-131` | `CONFIRMED` |
| Z homes at **`"G1 X2 Y-23 F12000"`**, off the bed — not bed centre | `ANKER_Z_HOMING_SCRIPT`, `pins_ANKER_V8110_V0_4.h` | `CONFIRMED` |

**This explains every standalone homing failure.** Raw `G28`, `MOVE_ZERO`, all of
them took the `else` branch. The probe never engaged because the firmware never
asked it to. Not a gatekeeper, not an untrusted XY frame, not a missing opcode.

### 🔥 The `G36` experiments were 10C too cold

`EXTRUDE_MINTEMP` is **160**. The 2026-07-09 supervised G36 sessions heated the
nozzle to **150C** (`printer-test-validation.md:104`). So `auto_align()` armed the
flag, called `G28`, `anker_home_z_safely()` evaluated `150 >= 160` as false, took
the `else` branch, and returned without probing or completing — exactly the
recorded *"acknowledged receipt but performed no leveling motion… never returned a
completion `ok`."*

**`REFUTED`: "production firmware does not honor `G36`."** It was never given a
hot enough nozzle. That conclusion is still repeated in the README, the LaunchAgent
comment, and `printer-test-validation.md`, and all of them need revising.

The fixture used 150 because it is the *minimum* of our own clamp
(`web/util.py:24`) — a safe-looking low value that sits under the firmware floor.

**This also reconciles the contested "wedge".** The early experiment's wedged
queue and required power cycle is consistent with the `kill()` at
`anker_align.cpp:131` after a failed alignment; the 2026-07-09 runs never reached
probing, so they saw `Idle / Ready` and a clean cooldown. Both records are
accurate — different failure modes.

### ⚠️ Correction to the 2026-07-27 entry above

That entry says *"probing is NOT temperature-gated"* on the strength of
`//#define PREHEAT_BEFORE_PROBING`. **That is true of stock Marlin's preheat
feature and false of this machine** — the Anker path carries its own threshold at
`G28.cpp:263`. `REFUTED`. Right about the flag, wrong about the machine.

### The descent, traced (2026-07-28)

**Correcting the row above: the `else` branch defers Z homing, it does not skip
it.** The motion happens a few steps later, in a path with no guards at all.

```
G28
 └─ anker_home_z_safely()                              G28.cpp:594
     └─ else branch → is_home_z = true, no motion here       :295
 └─ anker_z_homing_options = true                            :595
 └─ after_homing_action()                                    :711
     └─ is_center_home() → true               anker_homing.cpp:173
     └─ process_subcommands "G2001"                          :220
         └─ G2001 → home_z_safely()                   G28.cpp:766
             └─ if (is_home_z) homeaxis(Z_AXIS)   ←── THE DESCENT :185
             └─ Probe_homeaxis(Z_AXIS, 2)                     :198
```

| Finding | Evidence | Status |
| --- | --- | --- |
| The plate-strike descent is `homeaxis(Z_AXIS)` inside `home_z_safely()`, reached via `G2001` | trace above | `CONFIRMED` |
| That path checks **neither** nozzle temperature **nor** `g36_running_flag` | `G28.cpp:174-194` | `CONFIRMED` |
| **A normal slicer print takes the same path.** Its `G28` runs hot but with `g36_running_flag` false, so it also goes `else` → `G2001` → `homeaxis(Z_AXIS)` | `G28.cpp:263`, slicer start G-code | `CONFIRMED` |
| **Therefore the code path is not the discriminator** between a successful home and a plate strike | follows | `CONFIRMED` |
| The two paths differ in probe mode: `Probe_homeaxis(Z_AXIS,2)` deferred vs `(Z_AXIS,1)` inside G36 | `G28.cpp:198`, `:285` | `CONFIRMED` |
| **Why the probe registers at print temperature and not cold** | — | **`UNVERIFIED` — the open question.** Candidates: the detached-nozzle strain board (`ADAPT_DETACHED_NOZZLE 1`, `anker_nozzle_board.cpp`), `ANKER_PROBE_SET`, and `Probe_homeaxis` in `motion.cpp` |

### What the probe actually is (2026-07-28)

The ledger has been reasoning about the probe as an endstop pin, because `M119`
reports `z_probe: open`. **It is not a pin.** It is a strain gauge on a separate
nozzle board, read through a load-cell ADC and spoken to over UART.

| Finding | Evidence | Status |
| --- | --- | --- |
| Probing is armed per-descent by two calls, immediately before the move | `motion.cpp:2613-2614` — `uart_nozzle_tx_point_type(POINT_G28, 1)` and `anker_probe_set.probe_start(anker_probe_set.leveing_value)` | `CONFIRMED` |
| The sensor is a **strain gauge on a detached nozzle board** — `ADAPT_DETACHED_NOZZLE 1` — not a switch on a pin | `ANKER_Config.h:67`; the UART nozzle protocol in `feature/interactive/` | `CONFIRMED` |
| It is read via a **CS1237** 24-bit load-cell ADC, with an init/tare value and a threshold | `anker_z_offset.cpp` (`cs1237_*`, `init_value`, `threshold`) | `CONFIRMED` |
| Two thresholds exist: `HOMING_PROBE_VALUE 650` and `LEVEING_PROBE_VALUE 600` | `anker_z_offset.h:58-59` | `CONFIRMED` |
| **`Probe_homeaxis` arms with `leveing_value` (600), not `homing_value` (650)** — even when homing | `motion.cpp:2614` | `CONFIRMED`; whether deliberate `UNVERIFIED` |
| Thresholds are **runtime-settable** — `M3020 V<n>` pushes a new value to the nozzle board | `feature/interactive/M3011_3100.cpp` | `CONFIRMED` |
| On no-detect the descent runs **`1.5 × max_length(Z)`** and then *sets the axis as homed anyway* | `motion.cpp:2609`, `:2616-2625` | `CONFIRMED` |

**This retires an old confusion.** `M119`'s `z_probe: open` was already marked
`INVALID-TEST` on StallGuard grounds. The deeper reason is that **the probe is not
on that pin at all** — a pin read can never say anything about a UART strain gauge.

**The heater save/restore in `Anker_Zoffset::run()` is dead code** here —
`ANKER_Z_OFFSET_FUNC` is `0` (`ANKER_Config.h:64`). Do not cite it.

### The probe chain, end to end (2026-07-28)

| Step | Where | Status |
| --- | --- | --- |
| 1. Marlin arms the board: `uart_nozzle_tx_point_type(POINT_G28, 1)` + `probe_start(leveing_value)` | `motion.cpp:2613-2614` | `CONFIRMED` |
| 2. Probe endstop enabled just before the move | `motion.cpp:1792` `anker_level_set_probing_paused(true, …)` | `CONFIRMED` |
| 3. Descend `1.5 × max_length(Z)` at `Z_PROBE_FEEDRATE_FAST` | `motion.cpp:2609`, `:2616` | `CONFIRMED` |
| 4. **The nozzle board** detects strain and sends an overpressure message over UART | `uart_nozzle_rx.cpp:332` | `CONFIRMED` |
| 5. Marlin acts on it **only if `endstops.z_probe_enabled`** → `planner.endstop_triggered(Z)` | `uart_nozzle_rx.cpp:333-336` | `CONFIRMED` |
| 6. No trigger → `set_axis_is_at_home()` is called **anyway**, returns 0, `G28` sets `is_again_probe_homing` and retries; after `ANKER_Z_AGAIN_HOMING_NUM`, `kill()` | `motion.cpp:2616-2625`; `anker_homing.cpp:224-234` | `CONFIRMED` |

**The architectural point: trigger detection lives on the nozzle co-processor**,
arrives asynchronously over UART, and is gated inside Marlin by
`endstops.z_probe_enabled`. It is not an endstop pin and never was. The board is
also told *which* operation is probing — `POINT_G28`, `POINT_G36`, `POINT_G29` —
so its behaviour can differ per operation.

The board is a capable peer, not a sensor: the UART surface includes probe
threshold set/get, raw ADC streaming on/off, PID autotune, hardware/software
version, and an error notify (`uart_nozzle_tx.h:65-80`).

### 🎯 The strongest remaining lead — and it is read-only

**The probe threshold is synchronised between Marlin and the board at runtime,
and something outside Marlin can set it.** `uart_nozzle_rx.cpp:292` receives a
value and assigns `anker_probe_set.leveing_value`, logging `echo:M3020 V%d`;
`M3011_3100.cpp` implements `M3020 V<n>` to push one down.

**Hypothesis:** the communication module sends `M3020` (or an equivalent
threshold/calibration step) as part of its job-start sequence, and never does so
for a standalone command. A board holding a wrong or uninitialised threshold
would accept the arm, never report a trigger, and let the descent run to
`1.5 × max_length` — exactly the observed plate strike.

**This is testable read-only**, with no command from us: capture the MQTT G-code
stream during a normal Orca-started print and look for `M3020`, other `M30xx`
traffic, or any probe/calibration command the module issues that we never send.
That single capture would also settle the wider "what does the module send at job
start" question. `UNVERIFIED` — worth doing before anything else.

### Still unanswered: the temperature discriminator

**No temperature term appears anywhere in the probe-arming or probe-sensing path
read so far.** The `>= EXTRUDE_MINTEMP` check exists only in
`anker_home_z_safely()`'s G36 branch (`G28.cpp:263`) and does not guard the
deferred descent that actually moves.

So *why a hot print homes and a cold standalone command plunges is still
`UNVERIFIED`,* and after reading the full probe chain **there is no evidence it is
temperature at all.** Nothing in arming, descent, or trigger handling references
nozzle temperature.

`handshake.cpp` was read and **does not support the earlier guess**: it is a
nozzle-*presence* interlock that gates `HEATER_EN_PIN` on a pin read, not a probe
initialisation or tare. That hypothesis is dropped.

The live candidate is now the threshold-synchronisation lead above.

### 🚫 What this does not license

**Nothing here justifies sending a homing command**, and the trace makes the case
stronger, not weaker:

- **The `/ws/ctrl` block on `G28` with Z must stay.** "Standalone `G28` does
  nothing" was wrong — it descends.
- **A hot nozzle is not a safety argument.** The threshold at `G28.cpp:263` gates
  only the G36 branch; the deferred path that actually descends has no
  temperature check.

Knowing the threshold does **not** make "heat to 160C and send `G36`" safe — a
failed alignment `kill()`s the printer, and the descent mechanism is unexplained.
Home stays disabled. See
[#27](https://github.com/bigminer/ankermake-m5-protocol/issues/27).

### The four failed attempts, and why

**Nothing we sent made this printer home Z. Four attempts, all failed** — now
explained by the gate above rather than by four separate mysteries.

| Attempt | Result | Status |
| --- | --- | --- |
| Raw `G28` | Nozzle driven into plate, no probe engagement | `CONFIRMED` |
| `MOVE_ZERO` (`0x0402`/1026, value 2) | Same unsafe descent | `CONFIRMED` |
| `G36` after preheat | ACKed, no motion, timed out, queue wedged | `CONFIRMED` |
| `M401` (deploy probe) | Lifted Z ~14.9mm; **did not** arm probe | `CONFIRMED` |

**Failure cost (operator, 2026-07-14):** neither plate strike damaged the printer.
Extra pressure on plate and gantry, nothing more. Do not describe these as crashes
or imply damage — inflated framing distorted risk judgement for a whole session.

**Containment commit trail:** `22c8bd3` disable unsafe standalone homing ·
`14e34d2` block direct web Z homing · `e088c2c` attempted app-level Home, live
test proved it unsafe · `12f726c` restore UI lockout and add the server-boundary
rejection · `ffaea8c` remove homing from live-printer fixtures. A later normal
print-start probed correctly after heating at a 220C nozzle / 60C bed target,
which proves the physical probe works but **not** that standalone web homing is
supported — the firmware's probing paths are guarded by internal
homing/alignment state, so a raw homing opcode is not a complete
probe-preparation sequence. Do not re-enable Home from another command or value
guess.

### 🔑 A third config file exists, and it changes the homing picture (2026-07-28)

**`release_marlin2.0/Marlin/src/inc/ANKER_Config.h`.** Every firmware fact below
was read from `Configuration.h` and `Configuration_adv.h` only. This third header
holds the Anker feature switches, and several conclusions rested on flags it
defines.

Read directly (fetched and grepped, not via a search tool — see the caveat at the
end of this section).

| Finding | Evidence | Status |
| --- | --- | --- |
| **`USE_Z_SENSORLESS` IS defined** — `#define USE_Z_SENSORLESS 1` | `ANKER_Config.h:69` | `CONFIRMED` |
| Therefore the `ANKER_PROBE_TIMEOUT` / `ANTHER_Z_DROP_DISTANCE -14` / `ANTHER_Z_RISE_DISTANCE 2` block is **live code, not dead code** | it is gated on `USE_Z_SENSORLESS` | **`REFUTED`** the earlier "may be dead code" row |
| The M5C uses a **custom Z-homing path**, not stock Marlin's | `WS1_HOMING_5X 1`, `EVT_HOMING_5X 1`; `G28.cpp:584-596` takes `anker_home_z_safely()` + `ANKER_Z_HOMING_SCRIPT` instead of `home_z_safely()` | `CONFIRMED` |
| Z homing **retries on failure and then kills** | `anker_homing.cpp:224-234` — `is_again_probe_homing` re-runs `G28 Z` up to `ANKER_Z_AGAIN_HOMING_NUM`, then `kill(MSG_KILL_HOMING_FAILED)` | `CONFIRMED` (live, given `USE_Z_SENSORLESS`) |
| **Overpressure reporting is OFF** — the feature that would "stop the down-probing function and report an error" | `ANKER_Config.h:79` `ANKER_OVERPRESSURE_REPORT 0` | `CONFIRMED` |
| `NO_MOTION_BEFORE_HOMING` is **enabled** | `Configuration.h:1368` | `CONFIRMED` |
| Therefore the `echo:Home X` / `echo:Home Y` refusals on every unhomed X/Y jog are **this feature**, not an Anker quirk | follows directly | root cause **`CONFIRMED`**, upgraded from `UNVERIFIED` |
| Other switches worth knowing: `ANKER_MAKE_API 1`, `ANKER_ANLIGN 1`, `ANKER_LEVEING 1`, `ANKER_PROBE_SET 1`, `ANKER_NOZZLE_PROBE_OFFSET 1`, `ANKER_SIMPLE_HOMING 1`, `NO_CHECK_Z_HOMING 1`, `ANKER_M_CMDBUF 1`. Disabled: `ANKER_Z_OFFSET_FUNC 0`, `ANKER_BELT_CHECK 0` | `ANKER_Config.h:51-84` | `CONFIRMED` |

**Probing is NOT temperature-gated.** `//#define PREHEAT_BEFORE_PROBING` is
commented out (`Configuration.h:1311`), so `PROBING_NOZZLE_TEMP 140` on line 1313
is inside a disabled `#if` and never applies. `REFUTED`: the idea that standalone
`G28` fails because the nozzle is cold, and that a hot nozzle would make it home.
**Do not run a heated standalone homing test on that reasoning** — it would drive
a hot nozzle at the plate on a premise the source contradicts.

⚠️ **`ANKER_OVERPRESSURE_REPORT 0` deserves attention** given two plate strikes.
The switch that would halt down-probing and raise an error on overpressure is off
in this build. That is a candidate explanation for why the nozzle kept pressing
rather than aborting. `UNVERIFIED` as a causal claim — nobody has read what the
flag actually guards.

⚠️ **Version skew, and it bounds everything in this section.** `ANKER_Config.h:49`
sets `SHORT_BUILD_VERSION "V8110_V3.0.21"`. **Our printer runs V3.1.56.** The
published source is an *older* build than the machine. Treat firmware facts as
strong evidence about intent and structure, not as guaranteed byte-truth for the
installed firmware.

⚠️ **Method note that nearly cost us this.** `gh search code` showed
`#define PROBING_NOZZLE_TEMP 140` looking live; a page-summarising fetch said it
was commented. Both were misleading — the line is uncommented but sits inside a
disabled `#if ENABLED(...)`. **For any config flag, fetch the file and read the
enclosing block.** A matching line is not an answer. This is the same trap that
produced the `USE_Z_SENSORLESS` error corrected above.

### Firmware facts (read from source, V8110_DVT `Configuration.h` / `_adv.h`)

⚠️ **This section read only two of the three config files.** See the
`ANKER_Config.h` entry above; at least one row below was wrong as a result.

Source: `github.com/eufymake/eufyMake-Marlin-M5C`, path
`release_marlin2.0/Marlin/Configuration/V8110/V8110_DVT/`. **V8110 is the M5C.**

| Finding | Evidence | Status |
| --- | --- | --- |
| The nozzle **is** the probe; no sensors in the plate | `#define NOZZLE_AS_PROBE` | `CONFIRMED` |
| Z homing requires **trusted XY** | `#define Z_SAFE_HOMING` — *"Allows Z homing only when XY positions are known and trusted"* | `CONFIRMED` |
| Z homes to center | `Z_SAFE_HOMING_X_POINT/Y_POINT = X_CENTER/Y_CENTER` | `CONFIRMED` |
| Marlin's probe-arming machinery is **off** | `//#define PROBE_TARE`, `//#define PROBE_ACTIVATION_SWITCH` — both commented | `CONFIRMED` |
| `PROBE_TARE` is exactly this hardware's mechanism | Its comment: *"Useful for a strain gauge or piezo sensor…"* | `CONFIRMED` |
| StallGuard homing is enabled | `#define SENSORLESS_HOMING`, `Z_STALL_SENSITIVITY 95` | `CONFIRMED` |
| Sensorless *probing* is off | `//#define SENSORLESS_PROBING` | `CONFIRMED` |
| Z homing uses the probe, on a dedicated pin | `#define USE_PROBE_FOR_Z_HOMING`; `//#define Z_MIN_PROBE_USES_Z_MIN_ENDSTOP_PIN` | `CONFIRMED` |
| `ANKER_PROBE_TIMEOUT 12000` / `ANTHER_Z_DROP_DISTANCE -14` / `ANTHER_Z_RISE_DISTANCE 2` exist | `Configuration_adv.h:2993+` | `CONFIRMED` |
| ~~…but that block sits inside `#if ENABLED(USE_Z_SENSORLESS)` and **`USE_Z_SENSORLESS` is not defined in either config file** — may be dead code~~ | ~~grep of both headers~~ | **`REFUTED` 2026-07-28** — `USE_Z_SENSORLESS` **is** defined, `ANKER_Config.h:69`. The grep covered two of three config files. The block is live code. |

### The XY-is-fiction hypothesis (operator's insight, 2026-07-15)

`M114` reports `X:-15.00 Y:232.50` — **off the 220x220 bed**. Yet the operator
physically touched the plate with that nozzle. The firmware's XY belief and
physical reality disagree. XY was never homed this boot; the values are restored
park coordinates, and on a bed-slinger both axes move freely by hand when off.

Combined with `Z_SAFE_HOMING`'s "known and trusted" requirement, this is the best
current explanation for why probing never engages: **we have been asking the
printer to probe from a coordinate frame it does not trust.** A real print homes
XY first, which is why real prints probe fine.

Status: `STRONG`. **Untested.** The proposed test starts with `G28 X Y` (real
`x_min`/`y_max` endstops; also the one form `/ws/ctrl` permits) followed by
`M114` to see if the position was lying. It has not been run live and must not
be called safe merely because the endstops exist. Any later move-to-center/probe
experiment needs a separate safety review and fresh operator confirmation; the
two known standalone Z-homing attempts remain blocked.

### Retracted claims — do not re-derive these

| Claim | Why it died |
| --- | --- |
| "`z_probe: open` under load is the root cause" | `SENSORLESS_HOMING` is enabled. If Z detection is StallGuard, it only senses **during motion** — a stationary pressed nozzle produces no stall by design. The `M119`-while-holding test could not have measured what we thought. `INVALID-TEST`, not evidence of a fault. |
| "The probe is gated by Anker's comm module" | Plausible but never evidenced; `Z_SAFE_HOMING` + untrusted XY explains the same observations without inventing a gatekeeper. `UNVERIFIED` at best. ⚠️ **Contested — see audit B2.** The memory note `m5c-homing-dead-ends` states this as the settled working model, which contradicts this retraction. Do not settle it by argument: `src/feature/anker/anker_homing.cpp`, `anker_z_sensorless.cpp`, and `anker_z_offset.cpp` are published Tier 1 and were never opened. |
| "This printer has no proprioception" | `M114` works fine and reports position + planner counts. The *codebase* never asks; the firmware always knew. `REFUTED`. (The "raw stepper counts" wording this row originally used is itself imprecise for this build — see the 2026-07-27 correction.) |
| "`M401` won't move anything (no servo)" | It lifted the toolhead 14.9mm off a plate it was pressed against. "No servo" ≠ "no motion". `REFUTED`. |
| "Leveling EEPROM was corrupted by the plate strikes" | `1072 isLeveled: 1`. Data intact. `REFUTED`. |

---

## Position and coordinate frame

| Finding | Evidence | Status |
| --- | --- | --- |
| `M114` works: reports X/Y/Z + planner counts (**not** live stepper reality — see the 2026-07-27 correction) | `X:-15.00 Y:232.50 Z:11.55 Count X:-1920 Y:29760 Z:4620` | `CONFIRMED` |
| Z is **400 steps/mm** | Every observed 1mm Z jog = 400 counts; every 10mm Z jog = 4000, across a 51mm Z span | `CONFIRMED` |
| **X/Y counts survive a power cycle exactly; Z resets to 0** | Before/after reboot: X `-1920`→`-1920`, Y `29760`→`29760`, Z `4620`→`0` | `CONFIRMED` |
| Therefore **recording a Z number across a reboot is worthless** | Counter zeroes regardless of physical position | `CONFIRMED` |
| Reported Z is **not stable across commands** — track the **count** | `M401` cleared a `+0.25` offset; the same physical point went `-12.55` → `-12.80` | `CONFIRMED` |
| A `+0.25mm` offset exists below zero, origin unknown | count 0 → `Z:0.25`; cleared by `M401` | `UNVERIFIED` |
| `M851` reports `Probe Offset X0 Y0 Z0.02` | direct read | `CONFIRMED` |
| A stored Z offset can't be made durable without a Z home | An offset needs a repeatable datum; homing *is* the datum | `STRONG` |
| Supervised 1mm X+/X-/Y+/Y- relative request pair left the reported frame unchanged | each `G91` → bounded `G1` → `G90` sequence was accepted; afterward `M114` reported X:-15.00, Y:232.50, Count X:-1920/Y:29760 | request/reply `CONFIRMED`; later operator review confirmed no physical motion |
| Supervised 10mm X+/X-/Y+/Y- relative request pair left the reported frame unchanged | each `G91` → `G1 … F3000` → `G90` sequence was accepted; afterward `M114` again reported X:-15.00, Y:232.50, Count X:-1920/Y:29760 | request/reply `CONFIRMED`; later operator review confirmed no physical motion |
| Supervised 50mm X+/X-/Y+/Y- relative request sequence repeated three times left the reported frame unchanged | operator confirmed clearance; all 12 bounded `G91` → `G1 … F3000` → `G90` legs were accepted; afterward `M114` reported X:-15.00, Y:232.50, Count X:-1920/Y:29760 | request/reply `CONFIRMED`; operator observed no physical motion |
| Raw relative X/Y jog requests did not produce observable motion | operator watched the earlier 1mm/10mm tests and the 3×50mm sequence; none moved despite broker delivery and printer replies. Each `G1 X…`/`G1 Y…` reply included `echo:Home X`/`echo:Home Y`. | `CONFIRMED` for the observed no-motion result; root cause `UNVERIFIED` |

### Manual plate finding works; logical zeroing needs revalidation (2026-07-15)

The operator established a physical Z reference the probe could not: jog down,
paper-drag test, 0.1mm steps. **Plate found at count -5120.**
`G28`/`MOVE_ZERO`/`G36`/`M401` all failed to do this; hands and a sheet of paper
took four minutes.

`SESSION-ONLY` — and unavoidably so. It works *because* the operator is the datum,
and a person's judgement can't be serialized to EEPROM. Per power cycle, redo it.
`G92 Z0` is the proposed declaration mechanism, but it was not validated in this
session and remains `UNVERIFIED`. Never record-and-replay the count: a replayed Z
from a dead frame is a plunge.

---

## Printer state and telemetry

| Finding | Evidence | Status |
| --- | --- | --- |
| `APP_QUERY_STATUS` (`0x403`/1027) is the **broadest diagnostic query we have** | Idle captures mainly emitted temperatures; this query returned ~16 types. It still cannot answer after the printer's MQTT client disconnects. | response breadth `CONFIRMED` |
| The persistent red blink observed in this incident represented a **suspended print**, not a fault | `1039 {"breakPoint": 1}` + `1052 {"real_print_layer": 6}` | this incident `CONFIRMED`; do not generalize every red indication |
| A long-press on the physical button clears it | Red→green; `1039` stopped reporting; layer 6→0; 180C hold released | `CONFIRMED` |
| Power-cycling does **not** clear it — it's stored state, not a fault | Operator power-cycled; blink persisted | `CONFIRMED` |
| `1067` returns the physical button map (idle vs busy) | direct read | `CONFIRMED` |
| `1021 Z_AXIS_RECOUP: -5` is a **constant**, not crash damage | Unchanged across every state we've seen | `CONFIRMED` |
| `1072 isLeveled: 1` — leveling survived both plate strikes | direct read | `CONFIRMED` |

### Supervised fan and low-temperature requests (2026-07-19)

After the operator confirmed attendance, a clear bed, and a safe toolhead path,
the live preflight showed that the web service was reachable but the initial
`M105` received no printer reply within 10 seconds. Restarting `ankerctl` made a
subsequent `M105` reply immediately available. The supervised control requests
then completed: part fan 50% then off (`M106 S128`, `M107`), nozzle target 40C
then 0C (`M104 S40`, `M104 S0`), and bed target 35C then 0C (`M140 S35`,
`M140 S0`).

| Finding | Evidence | Status |
| --- | --- | --- |
| The service can be reachable while a printer reply is absent; restarting `ankerctl` restored an `M105` reply | initial 10s `M105` timeout; retry passed after restart | `CONFIRMED` |
| Fan and low-temperature requests were accepted by the control path | supervised live tests completed without control errors | `CONFIRMED` |
| Both heater targets were cleared after the supervised check | follow-up `M105`: `T:21.00 /0.00 B:21.04 /0.00` (current / target) | `CONFIRMED` |
| The `M107` fan-off request was accepted; resulting fan state is unavailable | the status and `M105` replies expose no fan-state field | physical fan-off outcome `UNVERIFIED` |

Later in the same supervised session, the operator requested that the settings
remain active across an `ankerctl` restart. The control path accepted `M106
S128` (50% part fan), `M104 S40`, and `M140 S35`; after the restart, the broad
status query reported idle state and `M105` reported `T:39.00 /40.00 B:26.16
/35.00`. The restart therefore did not clear the heater targets.

| Finding | Evidence | Status |
| --- | --- | --- |
| Low heater targets persist across an `ankerctl` restart | post-restart `M105`: nozzle 39.00/40.00C, bed 26.16/35.00C | `CONFIRMED` |
| Whether the 50% part-fan request persists across an `ankerctl` restart | command was accepted, but no fan-state telemetry exists | `UNVERIFIED` |
| Supervised shutdown cleared both heater targets | `M107`, `M104 S0`, and `M140 S0` accepted; immediate `M105`: nozzle 40.00/0.00C, bed 34.87/0.00C | `CONFIRMED` |

### Orca-started job observation (2026-07-19)

The operator started a job through Orca while this session issued no printer
action. A read-only status query found an active queued job with zero progress
and zero completed layers. `M105` reported nozzle 149/150C and bed 42.94/60C,
consistent with the printer's preheat/start phase.

| Finding | Evidence | Status |
| --- | --- | --- |
| An Orca-started job reaches the printer through the local control setup | read-only status reported a queued job and its layer metadata | `CONFIRMED` |
| The printer owns its preheat targets during job start | `M105`: nozzle 149/150C, bed 42.94/60C | `CONFIRMED` |
| The job transitions from queued/start to printing during its own calibration sequence | subsequent read-only status reported printer state value 1, still at zero progress/layers | `CONFIRMED` |
| A direct `M105` request may time out while the start sequence is active | status query still returned printing state; the following `M105` received no reply within 10s | `CONFIRMED` for the timeout; cause `UNVERIFIED` |
| MQTT observation can stop while a job continues physically | operator observed the job continue and finish; broker notices stopped, direct local subscription received no packets, and the web state/reply paths timed out | `CONFIRMED` for the observation gap; cause `UNVERIFIED` |
| Restarting `ankerctl` after this job did not immediately restore an `M105` reply | authenticated `M105` still timed out after restart and a settling interval | `CONFIRMED` |
| The gap began when the printer's broker client disconnected; it made no observed reconnect attempt | broker logged the printer client disconnecting with `Host is down`; later control requests still reached the broker but had no printer subscriber and produced no reply | `CONFIRMED` |
| The Mac's local-broker/hotspot stack remained healthy while the printer disappeared from the hotspot | broker, DNS, NTP, Internet Sharing bridge, and pf checks all passed; the printer had 100% loss, no ARP entry, and no response on its known local service ports | observations `CONFIRMED`; weak/offline printer Wi-Fi or an address change `SUPPORTED`, not distinguished |
| Fixed-rate `M105` polling is redundant while normalized state telemetry is arriving | browser regression test shows fresh `/ws/state` traffic suppresses the next heartbeat; one probe resumes after the 15-second stale threshold | `CONFIRMED` in browser test; prevention of a printer Wi-Fi/MQTT disconnect `UNVERIFIED` |

### Same-room hotspot recovery and cold-boot follow-up (2026-07-20)

The operator moved the Mac into the printer's room and had to power the Mac down
and restart it. Placement and hotspot recreation therefore changed together;
the recovery cannot be attributed to distance alone.

| Finding | Evidence | Status |
| --- | --- | --- |
| The printer rejoined the Mac-hosted hotspot and local broker after the move/reboot | broker client source was on the Internet Sharing subnet; notices resumed every ~3s; passive `/ws/state` reported nozzle 23C with target 0C | recovery `CONFIRMED`; whether placement or reboot caused it `UNVERIFIED` |
| The first 120-packet “same-room” sample tested the wrong address | `setup.local.conf` still held a LAN address routed over `en0`, not the live broker client's hotspot address | `INVALID-TEST` for hotspot quality; do not use its latency figures |
| The actual same-room hotspot link was clean | broker-derived printer address routed over `bridge100`; 30/30 replies, 0% loss, 3.34ms average, 10.96ms maximum; later post-reload sample was 10/10 at 2.60ms average | current link quality `CONFIRMED`; long-print durability still needs revalidation |
| `ankerctl` cached the correct PPPP hotspot address, while the ignored diagnostic config was stale | cached `ip_addr` matched the live broker source; `setup.local.conf` did not and was corrected locally | `CONFIRMED` |
| The Mac cold boot exposed a persistent Chrony PID-file collision | launchd crash-looped; `/opt/ankerm5c/chronyd.pid` named PID 309, which belonged to `storagekitd`; no process listened on UDP/123 | root cause `CONFIRMED` |
| Moving Chrony's PID file to `/var/run` restores the installed NTP service | regression test failed on the persistent path and passed after the change; installed stack reported Chrony listening, runtime PID identified `chronyd`, and all verification checks passed | immediate fix `CONFIRMED`; another cold boot `NEEDS REVALIDATION` |

### Same-room communications and live-print retest (2026-07-20)

After fresh operator clearance, repeated no-motion communications remained
healthy across multiple fan/heater scenarios, 30-60 second pauses, and an
`ankerctl` restart. The operator heard the part fan, but could not distinguish
the requested 25%, 50%, and 100% tiers.

The operator then started a 43-layer Orca job while a passive monitor watched
the actual hotspot path and broker/state streams without periodic manual
`M105` queries. The job was physically aborted at layer 25 after the web Pause
and Stop controls failed; this was not a completed-print test.

| Finding | Evidence | Status |
| --- | --- | --- |
| Consecutive read/control communications survived long pauses and an `ankerctl` restart | repeated `M105` replies before/after restart and throughout 30-60s dwell scenarios; final targets read 0 | this run `CONFIRMED` |
| Part-fan operation occurred during the tiered scenario | operator heard the fan | operation `CONFIRMED`; 25/50/100% speed accuracy `UNVERIFIED` |
| Same-room passive observation remained continuous through the observed job | 1,099 normalized state messages, 308 notices, zero broker disconnects; 177/177 hotspot pings, 2.9ms average, 20.9ms maximum | through layer 25 `CONFIRMED`; full-job durability `UNVERIFIED` because job was aborted |
| No explicit nozzle-probing telemetry was identified | during physically observed probing, decoded traffic included the normal notice families but no probe point/contact field | absence in this capture `CONFIRMED`; a hidden/undecoded field remains possible |
| Web Pause did not pause this Orca-started job | six outbound publishes received six replies, but progress continued from layer 18 to 19 with no pause/park transition | this Orca job `CONFIRMED`; an uploader-identity mismatch is `SUPPORTED` but not yet live revalidated |
| Minimal web Stop plus `M2024` still failed to cancel this Orca-started job | two more publishes/replies; heaters cooled immediately, but progress/elapsed increased and layers advanced to 25 | this Orca job `CONFIRMED`; control is unsafe pending fix |
| Physical square-button long-press cleared the continuing job | telemetry reset 25/43 to 0; job frames ceased; toolhead moved back-left with Z raised; targets later read 0 | job clear `CONFIRMED`; calling the position "home" `UNVERIFIED` |

This run disproves the claim that restoring the minimal Stop payload is enough
for every upload origin. It had been live-validated in a different job context,
but failed against this Orca-started job. A successful MQTT reply only proves
message handling, not the required physical/job-state transition.

The server-owned action implementation now keeps these contracts separate:
Pause/Resume require the exact trusted upload identity, while Stop is always a
global, identity-free protective action. Stop sends the minimal `1008/value=0`
cancellation and `M2024` immediately, captures the `1008` acknowledgement for
diagnosis, and only reports confirmation after fresh telemetry shows an
inactive/cleared job and zero nozzle and bed targets. This is offline-tested but
still `NEEDS LIVE REVALIDATION`; it does not explain why the 2026-07-20 global
cancellation was acknowledged while the Orca stream continued.

### Named-action live preflight follow-up (2026-07-20)

With fresh operator clearance, validation mode was enabled only for this
attended attempt. No Pause, Resume, or Stop action was ultimately sent because
the synthetic no-motion uploads never produced an active job.

| Finding | Evidence | Status |
| --- | --- | --- |
| The new snapshot initially failed to expose the printer's actual state | broker traffic was current and forwarded to `ankerctl`; snapshot cursors advanced, but `state` remained unknown because command type 1000/subType 1 stores state in `value`, a shape the normalizer omitted | root cause `CONFIRMED`; regression test and fix added |
| Immediate unknown state after service restart is not itself a communication failure | `/ws/state` first returned cursor 0 with unknown facts; subsequent temperature notices advanced the cursor and a read-only 1027 query supplied state 0 | `CONFIRMED` |
| The file-transfer service did not validate its one-byte acknowledgement result | code waited for an AABB reply but accepted every byte as success; tests now distinguish `OK`, `ERR_BUSY`, and malformed replies | defect `CONFIRMED`; fixed offline |
| Synthetic zero-motion uploads cannot currently serve as a Pause/Resume/Stop fixture | simple dwell, firmware-backed `M109 R0`, and metadata-padded zero-displacement variants all received `OK` transfer acknowledgements and caused a beep, but raw status remained state 0 with no command type 1001 job notice | this fixture approach `INVALID-TEST`; why the communication module immediately completes/ignores it is `UNVERIFIED` |
| The aborted validation left the printer inactive and cold | final raw status: state 0, no active job, nozzle target 0, bed target 0; validation mode was then disabled and the service restarted | session outcome `CONFIRMED` |

Do not infer anything about the new Pause/Resume/Stop implementation from the
synthetic attempts: there was never an active job to act on. The next live test
requires separate authorization for a real slicer-generated job and must retain
the physical-control fallback.

### Named thermal/fan action validation (2026-07-23)

This attended run exercised only the bounded actions in issue #15 on the M5C
(V8110, firmware V3.1.56). Before the first live command, the operator confirmed
that they were at the printer, the bed and toolhead path were clear, the
filament path was safe, and the power switch was immediately accessible. No
motion, homing, upload, print start, or print-control action was attempted.

The initial `issue15-20260723-fan50-01` request was rejected with
`supervised_validation_required` because launchd had not reloaded the changed
validation-mode environment variable. It had no physical effect. After an
explicit unload/load and an authenticated rendered-mode check, the remaining
requests ran through the named-action path:

| Request | Evidence | Status |
| --- | --- | --- |
| `issue15-20260723-fan50-02` — fan 50% | server accepted; operator heard the part fan running; no fan-state fact exists, so the outcome became `indeterminate/confirmation_unavailable` | physical operation `CONFIRMED`; telemetry confirmation unavailable |
| `issue15-20260723-fan0-01` — fan 0% | server accepted; operator confirmed the part fan stopped; outcome became `indeterminate/confirmation_unavailable` | physical operation `CONFIRMED`; telemetry confirmation unavailable |
| `issue15-20260723-nozzle40-01` — nozzle 40C | accepted, then replaced immediately by the next nozzle target | `superseded/newer_target_submitted` `CONFIRMED` |
| `issue15-20260723-nozzle45-01` — nozzle 45C | new target telemetry reported 4500 centi-degrees and the action became `confirmed`; observed current rose from 25.00C to 51.00C during the bounded sample | target and heating response `CONFIRMED`; transient overshoot recorded |
| `issue15-20260723-bed35-01` — bed 35C | proceeded independently of the nozzle supersession; new target telemetry reported 3500 centi-degrees and the action became `confirmed`; observed current rose from 25.32C to 36.32C | independence, target, and heating response `CONFIRMED`; transient overshoot recorded |
| `issue15-20260723-heatersoff-stale-01` — all heaters off | before submission the lazy MQTT service reported `Stopped`, establishing the stale-state fixture; the Protective action was accepted, both new targets became 0, and the action became `confirmed` | stale-state eligibility and shutdown `CONFIRMED` |

The M5C has no numeric temperature display, so the operator correctly reported
that they had no way to visually compare the requested heater targets with the
telemetry. That part of issue #15's human-and-telemetry criterion was therefore
not measurable by this fixture. The fan direction was human-observable, but
fan speed remains absent from telemetry. These are evidence limitations, not
confirmation failures to paper over.

Validation mode was returned to `false` and the web service was reloaded. The
final read-only status was printer state 0, nozzle 40.00C with target 0, and bed
33.74C with target 0. The named thermal and fan actions remain gated for normal
operation pending disposition of the issue #15 evidence gaps.

### Thermal/fan validation with an external thermometer (2026-07-26)

Second attended run on this M5C (V8110, firmware V3.1.56). Before the first live
command the operator confirmed in-session that they were at the printer, the bed
and toolhead path were clear, and physical power was immediately accessible. No
motion, homing, upload, print start, or print-control action was attempted.

**This run closes the criterion-3 gap the 2026-07-23 run could not.** The
blocker was that the M5C has no numeric temperature display, so no human
observation could be compared against heater telemetry. An external calibrated
thermometer (Thermoworks Thermapen Mk4, ±0.2C, contact thermocouple) removed
that limitation. Both heaters agree with telemetry to within the instrument's
displayed resolution:

| Sensor | Telemetry | Thermapen | Delta |
| --- | --- | --- | --- |
| Bed at 35C target | 34.96C / 94.9F | 95F | 0.1F |
| Nozzle at 45C target | 45.00C / 113.0F | 113F | 0.0F |

Two measurement caveats worth keeping. An **ambient** comparison before heating
is nearly useless: bed, nozzle, and air are all genuinely at room temperature,
so agreement there proves only that nothing is grossly wrong. It did produce a
useful bound — the printer's own two sensors read 23.00C and 24.30C at a moment
when they were physically identical, so **inter-sensor spread is ~1.3C and no
agreement claim tighter than about ±2C is supportable** from this hardware. The
setpoint readings above are far tighter than that, which says the instrument,
not the printer, is the precise party. Contact technique matters: read the bed
surface and the heater-block body, not the polished nozzle tip.

| Request | Evidence | Status |
| --- | --- | --- |
| `issue15-20260726-gate-01` — fan 0% | first command after enabling validation mode; accepted where the identical request had been rejected minutes earlier | gate transition `CONFIRMED` |
| `issue15-20260726-nozzle40-01` — nozzle 40C | rejected `fresh_nozzle_temperature_required`; infrastructure artifact, see lazy-MQTT note below | invalid fixture, no physical effect |
| `issue15-20260726-nozzle45-01` — nozzle 45C | confirmed from new target telemetry; overshot to 56.00C before settling to exactly 45.00C and holding | target and heating response `CONFIRMED`; overshoot reproduces 2026-07-23 |
| `issue15-20260726-bed35-01` — bed 35C | confirmed; nozzle target held at 45.00C throughout | independent resource coordination `CONFIRMED` |
| `issue15-20260726-nozzle40-02` / `nozzle50-01` | 40C superseded by 50C with `newer_target_submitted`; 50C confirmed | same-resource supersession `CONFIRMED` |
| `issue15-20260726-fan50-01` — fan 50% | rejected `fresh_printer_state_required`; see state-is-never-pushed note below | invalid fixture, no physical effect |
| `issue15-20260726-fanoff-stale-01` — fan 0% | accepted under naturally stale state | Protective fan-off `CONFIRMED` |
| `issue15-20260726-heatersoff-stale-01` — all heaters off | accepted from stale state, both targets became 0, confirmed | stale-state eligibility and shutdown `CONFIRMED` |
| `issue15-20260726-fan50-02` — fan 50% | after an explicit status poll; operator heard the fan start from a silent baseline | physical operation `CONFIRMED`; telemetry confirmation unavailable |
| `issue15-20260726-fan0-02` — fan 0% | stale state; operator heard the fan stop | physical operation `CONFIRMED`; telemetry confirmation unavailable |

**The M5C never publishes `state`.** It pushes temperatures only. The `state`
fact exists solely as a reply to `APP_QUERY_STATUS` (1027), so it is stale
within the 15-second freshness window of any poll. `fan50-01` was rejected for
exactly this reason while temperatures were fresh. Consequence: **a fan request
in normal operation will fail its freshness gate unless something polls status
immediately beforehand.** Stale state is the M5C's default condition, not an
edge case — which is why fan-off must bypass that gate to remain reachable.
Both fan-off requests above were accepted under naturally stale state with
confirmed physical effect.

**The lazy MQTT service ages facts between requests.** Short-lived websocket
connections let the service stop, so the first action after an idle gap sees
stale telemetry. This is what invalidated `nozzle40-01`. A warm-up state read
immediately before submitting fixed it for every subsequent request. Same class
of infrastructure artifact as the 2026-07-23 launchd reload gap: the action
logic was never at fault in either case.

**A fan observation taken while the hotend is hot cannot be attributed.** The
firmware runs its own hotend cooling fan above a temperature threshold. An early
report of hearing the fan "on and off" arrived while the nozzle was at 50C and
while our only accepted fan command had been fan-*off* — so the sound cannot be
credited to our request. The run therefore turned the heaters off, waited for
the operator to confirm total silence, and only then commanded the fan. Both
subsequent observations are attributable against that silent baseline.

Validation mode was never written to the LaunchAgent for this run. The service
was stopped and a temporary loopback-only instance was run with the variable set
in its process environment, so **ungating died with the process** and the
persistent configuration never left `false`. Post-run verification: the restored
service rejected a named action with `supervised_validation_required`. Final
read-only state was printer state 0, nozzle 31.00C target 0, bed 30.24C target 0.

**Lesson worth more than any single reading: when this printer has a hard problem,
the answer has repeatedly been its own physical interface or the runbook — not a
command we inferred.** The button beat every opcode we considered.

### `APP_QUERY_STATUS` enumerated (2026-07-27)

Read-only. `scripts/printer-probe.py status` against an idle printer — a bare
1027 query, no G-code, no motion, no heat, no operator present. Run to settle
whether the burst carries position before designing the issue 12 jog contract.

Thirteen non-temperature types came back. The probe filters 1003/1004 as
temperature noise and skips 1043, and 1039 appears only under a suspended print,
which reconciles the earlier "~16" estimate:

| Type | Payload |
| --- | --- |
| 1000 | `{"subType": 1, "value": 0}` |
| 1005 | `{"value": 0}` |
| 1006 | `{"value": 0}` |
| 1021 | `{"value": -5}` |
| 1023 | `{"value": 0, "progress": 0, "stepLen": 0}` |
| 1037 | `{"value": 0}` |
| 1052 | `{"total_layer": 0, "real_print_layer": 25}` |
| 1055 | `{"max_print_speed": 250}` |
| 1067 | button map — idle/busy × signal_click/double_click/long_press |
| 1072 | `{"isLeveled": 1}` |
| 1093 | `{"nozzle_type": 0}` |
| 1097 | `{"value": 0}` |
| 1098 | `{"filamentType": ["PLA"]}` |

| Finding | Evidence | Status |
| --- | --- | --- |
| **`APP_QUERY_STATUS` carries no position field.** No X/Y/Z, no coordinate, in any of the thirteen types | full enumeration above | `CONFIRMED` |
| Therefore a jog contract cannot confirm against the status burst; `M114` over MQTT 1043 is the only position path | follows from the above plus the confirmed `M114` round trip | `CONFIRMED` |
| **Whether 1005 is fan speed remains open, and this run did not settle it** | see below; narrowed further by the attended test that follows | `UNVERIFIED` |
| `stepLen` in 1023 may relate to `MOVE_STEP` (`0x400`) jog step length | name only; 1023 was 0 throughout on an idle printer | `UNVERIFIED` |
| 1052 reported `real_print_layer: 25` with `total_layer: 0` on an idle printer with no job | enumeration above | staleness artifact, `UNVERIFIED` |

⚠️ **Could this test have measured what I think it measured? For 1005, no.**
An unattended-memory note has recorded 1005 as fan speed, which sits against this
file's own `CONFIRMED` claim that "the status and `M105` replies expose no
fan-state field." This run read `1005: 0` with the fan off — consistent with 1005
being fan speed, and equally consistent with it being any other zero-valued
field. **The reading does not discriminate**, and the earlier "no fan-state
field" conclusion now looks like an inference over unlabeled types rather than a
positive result. Downgrade confidence in it accordingly.

Consequence if 1005 *is* fan speed: `fan_setting` would stop being
unconfirmable-by-design, and the "permanent property of the protocol" framing
behind the 2026-07-27 fan-copy decision would need retracting. Cheap way to
settle it, requiring the operator present since it commands the fan: poll 1027,
command the fan to 50%, poll 1027 again, compare 1005. Until then, treat fan
confirmability as open rather than closed.

### Supervised fan-readback test — is 1005 fan state? (2026-07-27)

Attended. The operator confirmed presence at the printer before any command.
Fan only — no heat, no motion, no job. Conditions were unusually clean: nozzle
26.00C target 0, bed 26.04C target 0, printer state 0, no active job. **Cold, so
the firmware's own hotend fan was not running** — the confound that made the
2026-07-26 fan observations unattributable did not apply here.

Commands were sent as raw G-code over `1043`, the same path the `fan_setting`
action uses, deliberately: the question was what the *existing* action can
confirm against.

| Step | Firmware reply | Physical observation | `1005` |
| --- | --- | --- | --- |
| baseline | — | fan silent | `{"value": 0}` |
| `M106 S128` (50%) | `ok` | **operator heard the fan running** | `{"value": 0}` |
| `M107` (off) | `ok` | operator confirmed the fan stopped | `{"value": 0}` |

| Finding | Evidence | Status |
| --- | --- | --- |
| **`1005` does not track the fan when it is driven by raw G-code.** The fan physically ran and the value never moved | table above | `CONFIRMED` |
| Therefore the `fan_setting` action as currently implemented has nothing to confirm against | it sends `M106`/`M107` over 1043 | `CONFIRMED` |
| Whether the printer reports fan state *at all* | **still open — this test cannot decide it**, see below | `UNVERIFIED` |

⚠️ **This test does not establish that the printer publishes no fan state.** Two
hypotheses survive it and it does not discriminate between them:

- **(a)** `1005` is a command echo, not a status field. The printer never reports
  fan state, and "unconfirmable by design" is correct.
- **(b)** `1005` reflects only what the Linux upper computer mediates via its own
  `ZZ_MQTT_CMD_FAN_SPEED` opcode. Raw `M106` passes straight through to Marlin,
  so the upper computer's bookkeeping never updates — it does not know the fan
  changed.

Two facts keep (b) live and were the reason for running this at all:
`ZZ_MQTT_CMD_FAN_SPEED` is `0x3ed` = **1005 decimal** (`specification/mqtt.stf:77`)
— the type is named fan speed in the protocol's own table, not guessed at — and
its sibling `ZZ_MQTT_CMD_PRINT_SPEED` `0x3ee` = 1006 *is* read as an inbound
status value by `web/service/state.py`, which maps it to the live `speed` fact.
`normalize()` has no 1005 branch, so the value is discarded regardless.

**The decisive experiment is one command:** send `0x3ed` natively and re-poll.
If `1005` moves, it is (b) and the fix is to switch the action to the native
opcode; if it stays 0 with the fan audibly running, it is (a).

**Not run, and it should not be run blind.** The opcode number is solid — it is
declared unhedged as "Set fan speed" at `specification/mqtt.stf:77`, in a spec
that marks nineteen other entries with `?` or `(probably)`. **Its payload is
not**, and there is no convention to infer one from. The outbound shapes this
project actually sends are four, across three opcodes:

| Shape | Used by |
| --- | --- |
| `{commandType, value}` | Stop |
| `{commandType, value, userName, filePath}` | Pause / Resume |
| `{commandType, cmdData, cmdLen}` | all G-code (1043) |
| `{commandType}` alone | status query (1027) |

`PRINT_CONTROL` (1008) alone takes two of them depending on the operation, and
conflating those two variants is the documented 2026-07-13 regression. Nor were
any of these payloads inferred from a pattern — 1008's was established and
live-validated on 2026-07-10. An established payload for one command licenses
nothing about another.

For `FAN_SPEED` specifically, `value` alone may be incomplete: this machine
plausibly has part-cooling, hotend, and controller fans, so the command may want
a fan index or mode. A partial payload on a never-exercised opcode is undefined
behavior, not a mis-set fan speed.

**The way to get the payload is to capture the official eufyMake app driving the
fan through the local broker** — we observe, the app commands. That is the same
experiment jog needs for `MOVE_STEP`/`MOVE_DIRECTION`
([`jog-confirmation-research.md`](jog-confirmation-research.md), open question 2),
so one attended app-capture session settles both.

Until it is run, **"this printer publishes no fan-state" is not a supported
claim.** The supported claim is narrower: *ankerctl cannot confirm a fan request
it issues as raw G-code.*

**Correction to the `M114` row above.** That row calls `Count X:` "raw stepper
counts". On this build it is not: `M114_DETAIL`, `M114_REALTIME`, and
`M114_LEGACY` are all commented out in `Configuration_adv.h`, so `M114` falls
through to `report_current_position_projected()` — `X:/Y:/Z:` is
`current_position` (last *parsed* G-code) and `Count X:` is `planner.position`,
neither of which is live stepper reality, and it does not sync the planner.
`M114` can therefore prove acceptance, refusal, and — with `M400` — queue
completion, but **never physical motion**. The derived figures (400 steps/mm and
similar) are unaffected. Full citations in
[`jog-confirmation-research.md`](jog-confirmation-research.md).

---

## Camera

| Finding | Evidence | Status |
| --- | --- | --- |
| **The M5C has no onboard camera.** V8110 ∈ `PRINTERS_WITHOUT_CAMERA` | `web/__init__.py` | `CONFIRMED` |
| `/video` returns an **empty 200**, not an error, when unsupported | the generator returns silently | `CONFIRMED` |
| The camera is an external iPad → MediaMTX → WebRTC on **8889** | `local-macos-service.md` architecture section | `CONFIRMED` |
| **Only WebRTC.** HLS (8888) and RTSP (8554) are connection-refused | probed | `CONFIRMED` |
| ffmpeg cannot demux WHEP → **no curl/ffmpeg path to a still** | — | `CONFIRMED` |
| To grab a frame: drive a browser to `/ipadcam`, wait ~6s for ICE, screenshot | works | `CONFIRMED` |
| Camera resolves **~3 px/mm** | ~48px for a ~15mm gap | `CONFIRMED` |
| **Therefore it cannot detect contact** (0.1mm ≈ 0.3px) and must never be treated as a crash interlock | arithmetic | `CONFIRMED` |
| It *is* good for gross motion: did it move, direction, roughly how far | confirmed `M401`'s 14.9mm lift | `CONFIRMED` |
| Occlusion is **position-dependent** — the tip is hidden near the plate, visible when raised | two frames | `CONFIRMED` |

---

## How to add to this file

One row, in the right table, with a status. If you ran a test, ask **"could this
test have measured what I think it measured?"** before recording the result — the
single most valuable line in this document is an `INVALID-TEST`. If you're stating
a conclusion, state the evidence first; if the evidence is thin, the status is
`UNVERIFIED`, however good the story sounds.
