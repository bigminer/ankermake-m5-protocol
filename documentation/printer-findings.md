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
| `printer-findings.md` (this) | What we know + confidence. **Entry point.** |
| `local-macos-service.md` | Runbook: setup, topology, recovery procedures. |
| `printer-test-validation.md` | Test gates, live-test procedure, validation runs. |
| `local-control-research.md` | Long-form research narrative. |
| `CLAUDE.md` / `AGENTS.md` | Safety + secret rules. Binding. |

---

## Verified command reference

**Every row was run against this printer and the evidence is the actual reply.**
Timestamps are local (UTC-5). If a command isn't here, we have not verified it —
do not assume it behaves as stock Marlin does. `M401` is the cautionary tale: it
looked inert and moved the toolhead 14.9mm.

### Reads — safe, no motion, no heat

| Command | Does | Evidence (verbatim reply) | Verified |
| --- | --- | --- | --- |
| `M114` | Reports position **and raw stepper counts** | `X:-15.00 Y:232.50 Z:11.55 E:0.00 Count X:-1920 Y:29760 Z:4620` | 2026-07-15 00:38 |
| `M119` | Endstop pin states | `x_min: open` `y_max: open` `z_min: open` `z2_min: open` `z_probe: open` | 2026-07-15 01:03 |
| `M851` | Probe offset | `Probe Offset X0 Y0 Z0.02` | 2026-07-15 01:03 |
| `APP_QUERY_STATUS` — commandType **1027** (`0x403`), no payload | Bursts ~16 telemetry types the UI never asks for | `1039 {"breakPoint":1}`, `1072 {"isLeveled":1}`, `1052 {...}`, `1067 {button map}`, `1098 {"filamentType":["PLA"]}` | 2026-07-14 21:55 |

⚠️ **`M119` cannot see StallGuard.** `SENSORLESS_HOMING` is enabled; if Z detection
is stall-based it only registers **during motion**. `z_probe: open` on a stationary
nozzle — even one pressed hard into the plate — proves nothing. See `INVALID-TEST`
in Retracted claims.

### Writes — these move the printer. Operator confirmation required.

| Command | Does | Evidence | Verified |
| --- | --- | --- | --- |
| `M401` | ⚠️ **Lifts Z ~14.9mm** and sets `Z:2.00`. Does **not** arm the probe. | count `-5160`→`800` (+5960 = 14.9mm), camera confirmed ~15mm lift; `M119` still `z_probe: open` after. `Z:2.00` exactly matches `ANTHER_Z_RISE_DISTANCE 2` | 2026-07-15 01:01:57 |
| `G91` / `G1 Z<n>` / `G90` | Relative jog. **Send as three separate messages** — Marlin treats `;` as a comment, so `G91;G1...;G90` silently runs only `G91` | jog traces track exactly 400 counts/mm | 2026-07-15 00:38–01:01 |
| `G28 X Y` | Homes X/Y against **real** endstops (`x_min`, `y_max`). The only homing form `/ws/ctrl` permits | guard logic in `web/__init__.py`; endstops present in `M119` | **NOT run live** — `UNVERIFIED` |

### Known-dangerous — do not send

| Command | Why |
| --- | --- |
| `G28` (bare), `G28 Z`, any `G28` with Z | Drives nozzle into plate. Blocked at `/ws/ctrl`. |
| `MOVE_ZERO` (1026 / `0x0402`) | Same. Blocked at `/ws/ctrl`. |
| `G36` | ACKs, no motion, **wedges the command queue**, needs a power cycle. |
| `RECOVER_FACTORY` (1029 / `0x0405`) | Factory reset. Destroys printer config. |
| `M402` | Untested. Presumed inverse of `M401` — may **lower** Z ~15mm. |

### Unverified but likely useful

| Command | Expected | Status |
| --- | --- | --- |
| `G92 Z0` | Declares current position as zero. **No motion** — a declaration, not a move. The mechanism for manual zeroing. | `UNVERIFIED` |
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
| Live read paths (`pos`/`endstops`/`status`/`watch`) | `UNVERIFIED` — printer went silent before they could be exercised. Built from scripts that worked at 00:38–01:03, but not proven in this form. **Test before trusting.** |

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
| `1043` traffic floods with temp polls | Something polls `M105` constantly. Filter replies starting `ok T:` or you'll drown. |
| Background monitors print nothing | Python buffers stdout to a file. Use `python -u`. |
| Playwright screenshots vanish | They land in the **repo root**, not the output dir. Move them out; keep the worktree clean. |
| `ankerctl mqtt monitor` fails to connect | It dials cloud (`make-mqtt.ankermake.com`). The printer is on the **local broker**. Use the running service's websockets instead. |
| Printer silent right after a power cycle | Needs 30–60s to rejoin the `M5C-Local` hotspot. Silence ≠ a result. `ping` the hotspot lease first. |
| Replies carry a `+ringbuf:N,512,M` suffix | Anker-specific. Ignore it when parsing. |
| **Sends fail *silently* when ankerctl is wedged** | No error, no timeout, no clue. Confirm telemetry is flowing *before* sending. `2026-07-15 01:25` |
| "The printer is silent" almost always means **ankerctl**, not the printer | Check `/opt/ankerm5c/logs/mosquitto.out.log` — it shows the printer's real PUBLISHes, independent of ankerctl. Restart ankerctl before diagnosing anything else. |

### ⚠️ FIRST: if the printer seems dead, restart ankerctl

```sh
launchctl kickstart -k gui/$(id -u)/com.ankerctl.webserver
```

`CONFIRMED` 2026-07-15 01:47. **ankerctl's MQTT and PPPP service threads wedge.**
They keep reporting `Running` while receiving nothing. Symptoms look exactly like a
dead printer: no telemetry, jog buttons do nothing, uploads stall at `Sending file
contents`, `M114` gets no reply. `/ws/pppp-state` throws `ServiceStoppedError`.

**The printer is probably fine.** Check what it's *actually* doing:
```sh
tail -f /opt/ankerm5c/logs/mosquitto.out.log   # printer's own PUBLISHes
```
If that's growing, the printer is healthy and ankerctl is the problem.

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

## Homing — the central open problem

**Nothing we can send makes this printer home Z. Four attempts, all failed.**

| Attempt | Result | Status |
| --- | --- | --- |
| Raw `G28` | Nozzle driven into plate, no probe engagement | `CONFIRMED` |
| `MOVE_ZERO` (`0x0402`/1026, value 2) | Same unsafe descent | `CONFIRMED` |
| `G36` after preheat | ACKed, no motion, timed out, queue wedged | `CONFIRMED` |
| `M401` (deploy probe) | Lifted Z ~14.9mm; **did not** arm probe | `CONFIRMED` |

**Failure cost (operator, 2026-07-14):** neither plate strike damaged the printer.
Extra pressure on plate and gantry, nothing more. Do not describe these as crashes
or imply damage — inflated framing distorted risk judgement for a whole session.

### Firmware facts (read from source, V8110_DVT `Configuration.h` / `_adv.h`)

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
| …but that block sits inside `#if ENABLED(USE_Z_SENSORLESS)` and **`USE_Z_SENSORLESS` is not defined in either config file** — may be dead code | grep of both headers | `UNVERIFIED` |

### The XY-is-fiction hypothesis (operator's insight, 2026-07-15)

`M114` reports `X:-15.00 Y:232.50` — **off the 220x220 bed**. Yet the operator
physically touched the plate with that nozzle. The firmware's XY belief and
physical reality disagree. XY was never homed this boot; the values are restored
park coordinates, and on a bed-slinger both axes move freely by hand when off.

Combined with `Z_SAFE_HOMING`'s "known and trusted" requirement, this is the best
current explanation for why probing never engages: **we have been asking the
printer to probe from a coordinate frame it does not trust.** A real print homes
XY first, which is why real prints probe fine.

Status: `STRONG`. **Untested.** The test is `G28 X Y` (safe — real endstops,
`x_min`/`y_max`; also the one form `/ws/ctrl` permits) → `M114` to see if the
position was lying → move to bed center → retry probe.

### Retracted claims — do not re-derive these

| Claim | Why it died |
| --- | --- |
| "`z_probe: open` under load is the root cause" | `SENSORLESS_HOMING` is enabled. If Z detection is StallGuard, it only senses **during motion** — a stationary pressed nozzle produces no stall by design. The `M119`-while-holding test could not have measured what we thought. `INVALID-TEST`, not evidence of a fault. |
| "The probe is gated by Anker's comm module" | Plausible but never evidenced; `Z_SAFE_HOMING` + untrusted XY explains the same observations without inventing a gatekeeper. `UNVERIFIED` at best. |
| "This printer has no proprioception" | `M114` works fine and reports position + raw step counts. The *codebase* never asks; the firmware always knew. `REFUTED`. |
| "`M401` won't move anything (no servo)" | It lifted the toolhead 14.9mm off a plate it was pressed against. "No servo" ≠ "no motion". `REFUTED`. |
| "Leveling EEPROM was corrupted by the plate strikes" | `1072 isLeveled: 1`. Data intact. `REFUTED`. |

---

## Position and coordinate frame

| Finding | Evidence | Status |
| --- | --- | --- |
| `M114` works: reports X/Y/Z + raw stepper counts | `X:-15.00 Y:232.50 Z:11.55 Count X:-1920 Y:29760 Z:4620` | `CONFIRMED` |
| Z is **400 steps/mm** | Every 1mm jog = 400 counts; every 10mm = 4000, across a 51mm span | `CONFIRMED` |
| **X/Y counts survive a power cycle exactly; Z resets to 0** | Before/after reboot: X `-1920`→`-1920`, Y `29760`→`29760`, Z `4620`→`0` | `CONFIRMED` |
| Therefore **recording a Z number across a reboot is worthless** | Counter zeroes regardless of physical position | `CONFIRMED` |
| Reported Z is **not stable across commands** — track the **count** | `M401` cleared a `+0.25` offset; the same physical point went `-12.55` → `-12.80` | `CONFIRMED` |
| A `+0.25mm` offset exists below zero, origin unknown | count 0 → `Z:0.25`; cleared by `M401` | `UNVERIFIED` |
| `M851` reports `Probe Offset X0 Y0 Z0.02` | direct read | `CONFIRMED` |
| A stored Z offset can't be made durable without a Z home | An offset needs a repeatable datum; homing *is* the datum | `STRONG` |

### Manual zeroing works (2026-07-15)

The operator established a Z reference the probe could not: jog down, paper-drag
test, 0.1mm steps. **Plate found at count -5120.** `G28`/`MOVE_ZERO`/`G36`/`M401`
all failed to do this; hands and a sheet of paper took four minutes.

`SESSION-ONLY` — and unavoidably so. It works *because* the operator is the datum,
and a person's judgement can't be serialized to EEPROM. Per power cycle, redo it.
Mechanism is `G92 Z0` (a declaration, no motion), **not** record-and-replay: a
replayed Z from a dead frame is a plunge.

---

## Printer state and telemetry

| Finding | Evidence | Status |
| --- | --- | --- |
| `APP_QUERY_STATUS` (`0x403`/1027) is the **best diagnostic we have** | Unprompted, the printer sends only temps. This query returns ~16 types. | `CONFIRMED` |
| Persistent red blink = **suspended print**, not a fault | `1039 {"breakPoint": 1}` + `1052 {"real_print_layer": 6}` | `CONFIRMED` |
| A long-press on the physical button clears it | Red→green; `1039` stopped reporting; layer 6→0; 180C hold released | `CONFIRMED` |
| Power-cycling does **not** clear it — it's stored state, not a fault | Operator power-cycled; blink persisted | `CONFIRMED` |
| `1067` returns the physical button map (idle vs busy) | direct read | `CONFIRMED` |
| `1021 Z_AXIS_RECOUP: -5` is a **constant**, not crash damage | Unchanged across every state we've seen | `CONFIRMED` |
| `1072 isLeveled: 1` — leveling survived both plate strikes | direct read | `CONFIRMED` |

**Lesson worth more than any single reading: when this printer has a hard problem,
the answer has repeatedly been its own physical interface or the runbook — not a
command we inferred.** The button beat every opcode we considered.

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
