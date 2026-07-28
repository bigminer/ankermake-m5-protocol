# INDEX — read before acting

Written for the agent session, not the browsing human. Everything here exists to
stop you spending a session re-deriving a known result, or reviving a dead one.
Both have happened repeatedly.

**Load order:** `CLAUDE.md` (auto) → this → only what §4 points you at.

---

## 1. Triggers — match your next action, read the cell, then proceed

If your next move appears here, the answer already exists. Do not derive it.

| You are about to… | Stop. Already known | Where |
| --- | --- | --- |
| grep firmware config for a `#define` | **There are THREE config files** — `Configuration.h`, `Configuration_adv.h`, **`src/inc/ANKER_Config.h`**. And a `#define` can sit inside a disabled `#if`. Read the enclosing block, not the matching line | §3 A-01, A-02 |
| cite `specification/mqtt.stf` or `libflagship/` as proof of printer behaviour | **That is not evidence.** It is our own reverse-engineering. It supports "what ankerctl does", never "what the printer does" | §2 |
| investigate whether the printer reports fan state | **It does.** `1005`, percent, on-change only | F-003 |
| explain why a fan action can't be confirmed | Not the printer — **we send raw `M106`, which the module never sees** | F-022 |
| design or implement jog confirmation | `M114` reports planner space. **Nothing on this printer proves physical motion** | F-020, F-021 |
| work out why standalone homing fails | Largely solved. Real homing needs `g36_running_flag`, which only `G36` sets | F-010, F-011 |
| explain the plate strikes | Traced: `G2001` → `home_z_safely()` → unguarded `homeaxis(Z_AXIS)` | F-012 |
| test homing with a hot nozzle | **Do not.** The premise is refuted; the descent path has no temperature guard | §6, F-013 |
| reason about `M119`'s `z_probe: open` | Meaningless — **the probe is not on that pin.** Strain gauge, nozzle board, UART | F-014 |
| capture MQTT to learn what the module sends Marlin | **Impossible.** Zero `1043` in a full print; that link is invisible | F-006 |
| add a "fresh state" gate to any action | The M5C **never pushes `state`**. It is stale 15s after a poll. This has broken two actions already | §5 |
| send an opcode we have never sent | Its payload is unknown and **there is no convention to infer from** — 4 shapes across 3 opcodes | §5 |
| conclude `print_start` sends `G36` ungated | **It does not.** `ANKERCTL_PREPRINT_G36` gates it via `extract_temperatures` at `web/__init__.py:776` — no temps, no `bed_celsius`, no preparation. An audit got this wrong by reading `printer_actions.py` alone | A-09, issue #25 |
| conclude anything from `M105` about the fan | No fan field, and `REPORT_FAN_CHANGE` is compiled out | F-022 |

## 2. Evidence rule

| Tier | Source | May support |
| --- | --- | --- |
| 0 | Supervised observation, incl. [`captures/`](captures/) | Anything about this unit |
| 1 | Published first-party source; captured official-app traffic | Intended behaviour |
| 2 | Community RE (Ankermgmt, HASS component, upstream) | Leads only — much is M5, not M5C |
| 3 | **This repo**: `specification/`, `libflagship/`, `web/`, `static/` | **Only "what ankerctl does"** |

Version skew: published source is `V8110_V3.0.21`, the printer runs **V3.1.56**.
Firmware is strong evidence of intent, not byte-truth. Full rules:
[`method.md`](method.md).

## 3. Anti-patterns — mistakes made here, in this repo

| # | Mistake | Cost |
| --- | --- | --- |
| A-01 | Grepped 2 of 3 config files, concluded a flag was undefined | `USE_Z_SENSORLESS` "dead code" — wrong; it is live |
| A-02 | Trusted a code-search snippet without the enclosing `#if` | "Probing is temperature-gated" — wrong; dead block |
| A-03 | Cited our own `mqtt.stf` comment as proof an opcode was safe | Nearly sent an unexercised opcode at the printer |
| A-04 | Inferred one opcode's payload from another's | `PRINT_CONTROL` takes two shapes; conflating them is the 2026-07-13 regression |
| A-05 | Recorded an inference over undecoded data as `CONFIRMED` | "No fan-state fact" spread to 4 docs + the operator's UI, wrong for weeks |
| A-06 | Ran a live test to answer what one grep answers | Printer time spent on a source question |
| A-07 | Searched only the Marlin repo, concluded a component was unpublished | Missed `eufyMake-linux-sdk`, `anker_gcode/`, `feature/anker/` |
| A-08 | Kept the scarier of two conflicting observations without reconciling | `G36` "wedges the queue" — one run said so, two later did not |
| A-09 | Concluded a gate was missing from one file's absence, without asking who fills the field it branches on | "`print_start` sends `G36` ungated" — wrong; the gate is one layer up, and a passing test already proved it |

## 4. Facts — with a command to verify each

`Obs` = observed. `Inf` = inferred. Both usable; do not conflate when recording
new claims (A-05).

### Telemetry

| # | Fact | Verify |
| --- | --- | --- |
| F-001 | Printer pushes **temperatures only** unprompted (`1003`/`1004`, ~3s), plus a few on-change types during a job. Obs `CONFIRMED` | `grep -c '"commandType":1003' documentation/captures/*.jsonl` |
| F-002 | **No position anywhere.** `APP_QUERY_STATUS` (1027) returns 13 non-temp types, none a coordinate. `M114` over `1043` is the only path. Obs `CONFIRMED` | findings §"APP_QUERY_STATUS enumerated" |
| F-003 | **`1005` is fan speed**, percent, published **on change only** — 99 mid-print, 0 at completion. Obs `CONFIRMED`; naming Inf strong | `grep '"commandType":1005' documentation/captures/*.jsonl` |
| F-004 | **`1026` is emitted after homing** (twice, both post-`G28`). Bidirectional: as a *command* `value 2` drove the nozzle into the plate. Obs `CONFIRMED`; semantics `UNVERIFIED` | `grep '"commandType":1026' documentation/captures/*.jsonl` |
| F-005 | States: `0` idle · `1` printing · `4` **finished or stopped** · `8` preparing (~123s). Obs `CONFIRMED` | `grep '"commandType":1000' documentation/captures/*.jsonl \| grep -oE '"value":[0-9]+' \| uniq -c` |
| F-006 | **Zero `1043` in a full print.** The module publishes status only; its Marlin serial link is invisible over MQTT. Obs `CONFIRMED` | `grep -c '"commandType":1043' documentation/captures/*.jsonl` → 0 |
| F-007 | `normalize()` maps `1000/1001/1003/1004/**1005**/1006/1052`. **Unnamed types can never become facts** — check here before concluding the printer does not report something. `1005`→`fan` wired 2026-07-28 | `grep -n 'ct ==' web/service/state.py` |
| F-008 | **`fan` is a tracked fact** in `FACT_PATHS`. ⚠️ Published on change only, so it reads `stale` for most of a print while staying accurate — same shape as `state`. **Do not gate an action on `fan` freshness** without reading F-003 | `grep -n 'fan' web/printer_snapshot.py` |

### Homing

| # | Fact | Verify |
| --- | --- | --- |
| F-010 | Real Z homing requires **nozzle ≥ 160C AND `g36_running_flag`**; else a branch sets `is_home_z` and moves nothing there. Tier 1 `CONFIRMED` | `G28.cpp:263` |
| F-011 | **Only `G36` sets that flag** (`anker_align.cpp:96`) — **and G36 calls `G28` itself** (`:100`). G36 is the homing entry point | `gh search code --repo eufymake/eufyMake-Marlin-M5C g36_running_flag` |
| F-012 | **The plate-strike descent**: `after_homing_action` → `G2001` → `home_z_safely()` → `homeaxis(Z_AXIS)` at `G28.cpp:185`. **No temperature or flag check.** On no-detect descends `1.5 × max_length(Z)` and marks the axis homed | findings §"The descent, traced" |
| F-013 | **Why the probe registers hot but not cold — UNKNOWN.** The code path is identical for a working print and a strike; only probe mode differs (`Probe_homeaxis(Z,2)` vs `(Z,1)`) | §6 item 1 |
| F-014 | Probe is a **strain gauge on a detached nozzle board**, CS1237 ADC over UART, armed per-descent with a threshold (650 homing / 600 leveling, settable via `M3020`). **Not an endstop pin** | `motion.cpp:2613-2614` |
| F-015 | **Failed alignment calls `kill()`** — hard halt, needs a reset | `anker_align.cpp:131` |
| F-016 | `NO_MOTION_BEFORE_HOMING` enabled → the `echo:Home X/Y` jog refusals. Tier 1 `CONFIRMED` | `Configuration.h:1368` |

### Motion and actions

| # | Fact | Verify |
| --- | --- | --- |
| F-020 | **`M114` cannot prove motion.** `M114_DETAIL`/`_REALTIME`/`_LEGACY` compiled out; `Count X:` is `planner.position`. Proves acceptance, refusal, and with `M400` queue completion | [`jog-confirmation-research.md`](jog-confirmation-research.md) |
| F-021 | Jog is confirmable only to "accepted, queued, drained". `FACT_PATHS` has no position entry | `grep -A20 FACT_PATHS web/printer_snapshot.py` |
| F-022 | **Fan is confirmable in principle (F-003), still not as implemented.** The fact is now wired (F-007/F-008), but we send raw `M106` and `REPORT_FAN_CHANGE` is compiled out, so the MCU never tells the module and `1005` never fires for our own commands. **Remaining work: send native `FAN_SPEED` (`0x3ed`) instead of `M106`** — then the module updates, publishes 1005, and the action confirms | `grep -n 'M106' web/printer_actions.py` |

## 5. Settled — do not re-derive

- **`state` is never pushed.** Only an `APP_QUERY_STATUS` reply, stale 15s later.
  Any "fresh state" gate inherits this — it broke fan requests twice.
- **The lazy MQTT service ages facts between connections.** Warm-up `/ws/state`
  read immediately before submitting an action.
- **A fan observation with a hot hotend is unattributable** — the firmware runs
  its own hotend fan above a threshold. Establish silence cold.
- **`/ws/ctrl` replying `{"ankerctl":1}` is not the printer.** Real replies land
  on `/ws/mqtt` as `1043`, with a `+ringbuf:N,512,M` suffix to strip.
- **"Printer is silent" usually means ankerctl — but not always.** Check
  `/opt/ankerm5c/logs/mosquitto.out.log` and branch on whether PUBLISHes continue.
- **Stop vs Pause/Resume payloads differ deliberately.** Pause/Resume need
  `userName`+`filePath`; Stop is global and identity-free.
- **Every payload we trust was captured or live-validated, never inferred.**

## 6. Refuted — do not resurrect

| Dead claim | Killed by |
| --- | --- |
| "The printer publishes no fan-state fact" | `1005` = 99 then 0 across a print. F-003 |
| "Production firmware does not honour `G36`" | Tests ran the nozzle at 150C; `EXTRUDE_MINTEMP` is 160 |
| "Standalone `G28` can never home Z" | The else branch *defers* to `G2001`; it descends. F-012 |
| "Probing is temperature-gated / hot nozzle would home" | `PREHEAT_BEFORE_PROBING` commented out; constant in a dead `#if` |
| "The Linux upper computer has never been published" | `eufyMake-linux-sdk` is public |
| "`USE_Z_SENSORLESS` undefined, probe block may be dead" | Defined, `ANKER_Config.h:69` |
| "`M114` reports raw stepper counts" | `Count X:` is `planner.position`. F-020 |
| "The probe is gated by Anker's comm module" | Gate flag is set inside `G28.cpp` |
| "This printer has no proprioception" | `M114` always worked; we never asked |
| "`M401` won't move anything" | Lifted the toolhead 14.9mm |
| "`z_probe: open` under load proves a fault" | StallGuard senses only in motion — and the probe isn't on that pin. F-014 |

## 7. Distance to the goal

Goal: **the printer fully usable with no Anker cloud.** That is already largely
true — local broker, slicer upload, dashboard, print/monitor all work. What
remains is making control *trustworthy*, which is issue #6: named actions with
server-owned safety and honest confirmation.

Ordered by what actually unblocks the goal:

1. **#25 — ungated `G36` in `print_start`.** Offline, blocks #18. Cheapest real
   unblock.
2. **~~Wire `1005`~~ (done 2026-07-28); switch `fan_setting` to the native
   `FAN_SPEED` opcode.** The fact now exists (F-007/F-008) but nothing confirms
   against it yet, because raw `M106` never reaches the module's bookkeeping.
   Sending `0x3ed` is the remaining half — **its payload is unknown and must not
   be guessed** (A-04); capture the official app driving the fan. Closes the fan
   half of #15.
3. **#26 — map the control layer to Tier 1.** The ledger's firmware section read
   2 of 3 config files (A-01), so any row may be wrong.
4. **#12 — jog contract.** Needs design, not implementation. F-020 bounds what it
   can promise.
5. **#27 / F-013 — the probe discriminator.** Gates all homing work. Not
   answerable over MQTT (F-006); needs `eufyMake-linux-sdk` or serial access.
6. **#19 — contract the legacy path.** The finish line for #6; blocked on the
   validations above.

**#6 user story 7 needs revising**: it promises confirmation backed by physical
behaviour, achievable for thermal, impossible for jog and live-Z, and only now
possible for fan. Three of four classes need vocabulary the spec lacks.

## 8. Safety — not subject to evidence

[`CLAUDE.md`](../CLAUDE.md) binds regardless of how good the evidence is. Reading
source never authorises sending.

- Fresh current-session operator confirmation before anything that moves, heats,
  or starts/pauses/resumes/stops. **Read-only observation does not need it — and
  has produced more than any command we have sent.**
- **Home stays disabled.** `G28` containing Z stays blocked at `/ws/ctrl`
  (F-012 is why). **A hot nozzle is not a safety argument.**
- Run `./scripts/check-secrets.sh` before every stage, commit, push.

## 9. Map

| Doc | For |
| --- | --- |
| [`method.md`](method.md) | Full source hierarchy, conflict resolution |
| [`printer-findings.md`](printer-findings.md) | Canonical ledger, every claim graded |
| [`captures/`](captures/) | **Primary evidence** — raw MQTT JSONL |
| [`audit-2026-07-27.md`](audit-2026-07-27.md) | Contradiction sweep + dispositions |
| [`jog-confirmation-research.md`](jog-confirmation-research.md) | Jog confirmation (#12) |
| [`printer-test-validation.md`](printer-test-validation.md) | Test gates, Stop/Pause/Resume contract |
| [`local-macos-service.md`](local-macos-service.md) | Runbook: setup, topology, recovery |
| [`../CONTEXT.md`](../CONTEXT.md) | Printer-action vocabulary |
| [`../handoff.md`](../handoff.md) | Current session state |

## 10. Keeping this true

**It is checked, not trusted.** Run before every stage, commit, or push — and CI
runs it on every push and PR:

```sh
python scripts/check-docs.py
```

| Check | Catches |
| --- | --- |
| `REFUTED-LEAK` | A §6 claim reappearing in a doc **or an agent memory note**, with no correction near it |
| `VERIFY-ROT` | A fact's verify command finding nothing — it drifted from the code |
| `DEAD-LINK` | A pointer here going nowhere |
| `TIER-3-DRIFT` | Staged changes to `web/`/`static/`/`libflagship/` without touching this file (advisory) |

It found four leaks on its first run that a manual sweep had missed, including
one in the ledger itself. **If it fails, fix the contradiction — do not widen the
exclusion.** The one legitimate edit is the `MARKERS` vocabulary, when a passage
retires a claim in wording the regex does not yet recognise.

⚠️ **Memory coverage is local-only.** The 12 agent memory notes under
`~/.claude/projects/<slug>/memory` are checked when present — they matter most,
because they are auto-loaded into every session and arrive as background truth
without anyone asking. But **CI cannot see them**, so a green pipeline says
nothing about memory. Run this locally before committing.

### Rules

- **A code change that invalidates a fact row updates that row in the same
  commit.** Not the next one. An index that is confidently wrong is worse than no
  index — it will be trusted. This rule exists because F-007 went stale one
  commit after the index was created, in exactly the way §9's drift warning
  predicted.

- **Code comments are part of the system of record.** A comment asserting printer
  behaviour is a claim, and it is the one a future session reads *while editing
  the thing it describes* — so a stale one does the most damage. When a fact
  changes, grep the code for comments repeating the old version. Both offenders
  found on 2026-07-28 were in this class: `ankersrv.js` said "ankerctl has no fan
  reading" hours after the fan fact was wired, and `prepare_bed`'s docstring
  described `G36` completing a probing routine that has never been observed.
  Prefer citing a fact ID in the comment (`INDEX F-003`) over restating it.

  **Which rows drift: the ones describing *this repo*, because we change it.**
  Facts about the printer do not drift — we cannot edit firmware or past
  observations. So after touching `web/`, `static/`, or `libflagship/`, check the
  Tier 3 rows: **F-007, F-008, F-021, F-022**. Find them with:

  ```sh
  grep -nE 'web/|static/|libflagship/' documentation/INDEX.md
  ```

- **Add a trigger (§1) whenever you find yourself deriving something known.** That
  table is the mechanism; the rest is reference.
- **Add an anti-pattern (§3) when a method error costs time** — worth more than
  the finding it corrupted.
- Assert with a citation and a verify command. Mark Obs vs Inf.
- **Never delete from §6.** Move refuted claims there with what killed them.
- Fact IDs are stable. Supersede in place; do not renumber.
