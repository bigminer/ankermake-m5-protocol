# INDEX — start here

**This is the front door.** Every other document defers to it. Read this before
`printer-findings.md`, before `method.md`, before touching the printer.

Its job is to stop you re-deriving what is already known, and to stop you
resurrecting what has already died. Both happened repeatedly before it existed.

**How to use it:** find your question in §3, take the one-line answer and its
status, then follow the pointer only if you need the depth. §4 and §5 are the
ones that save the most time — read them even if you think you know.

---

## 1. What this project is

**Keep an AnkerMake M5/M5C usable with only free software — no Anker slicer, no
mobile app, no cloud.** Replace Anker's MQTT service rather than proxy it, so the
printer keeps working with its cloud connection severed. The printer is
discontinued; this is preservation work.

It is **replication, not product design.** The original already made the
decisions. When behaviour is in question the first move is *what did the original
do?* — and go read it, not invent it.

Parent design for the control layer: issue #6.

## 2. What counts as evidence

Full hierarchy in [`method.md`](method.md). The one-line version, because getting
this wrong caused most of the damage this index exists to prevent:

| Tier | | Authority |
| --- | --- | --- |
| 0 | Supervised observation of this machine, incl. `captures/` | This unit, as built |
| 1 | Published first-party source; captured official-app traffic | Intended behaviour |
| 2 | Community reverse-engineering | Leads only — much targets the M5, not M5C |
| 3 | **This repo** — `specification/*.stf`, `libflagship/`, `web/`, `static/` | Only "what ankerctl does". **Never** "what the printer does" |

> **The rule that was missing:** our own `mqtt.stf` comments and generated opcode
> tables are *our guesses written down*. Citing them as proof once justified
> sending an unexercised opcode at the printer.

Three traps, each of which produced a wrong answer here:

- **There are THREE firmware config files** — `Configuration.h`,
  `Configuration_adv.h`, **and `src/inc/ANKER_Config.h`**. Reading two of three
  produced a `CONFIRMED` claim that was false.
- **Read the enclosing `#if`, never the matching line.** A code-search hit is not
  an answer; a `#define` inside a disabled block is dead.
- **Version skew.** Published source says `V8110_V3.0.21`; our printer runs
  **V3.1.56**. Firmware is strong evidence about intent, not guaranteed byte-truth.

## 3. Questions a session actually asks

Status uses the [`printer-findings.md`](printer-findings.md) legend. **Obs** =
directly observed. **Inf** = inference from observation or source. The
distinction matters: flattening it is how a wrong claim once became `CONFIRMED`
and spread into four documents.

### Telemetry and transport

| # | Question | Answer | Status | Depth |
| --- | --- | --- | --- | --- |
| F-001 | What does the printer push unprompted? | **Temperatures only** (`1003` nozzle, `1004` bed, ~3s). Plus a few *on-change* types during a job | Obs `CONFIRMED` | `captures/` |
| F-002 | Does anything report position? | **No push. `M114` only**, over MQTT `1043`. `APP_QUERY_STATUS` (1027) returns 13 non-temp types, **none a coordinate** | Obs `CONFIRMED` | findings, 2026-07-27 |
| F-003 | **Is fan state reported?** | **Yes — `1005` is fan speed, percent, published on change only.** Read 99 mid-print, 0 at completion | Obs `CONFIRMED`; "is fan speed" Inf **strong** | `captures/README.md` |
| F-004 | Is there a homing signal? | **`1026` is emitted as a notice after homing** — twice, both post-`G28`. Type is bidirectional; as a *command* `value 2` drove the nozzle into the plate | Obs `CONFIRMED`; semantics Inf `UNVERIFIED` | `captures/` |
| F-005 | What do state values mean? | `0` idle · `1` printing · `4` **finished or stopped** · `8` preparing (preheat/home/level, ~123s) | Obs `CONFIRMED` | `captures/` |
| F-006 | Can we see what the module sends Marlin? | **No.** Zero `1043` in an entire print. The module publishes status only; its serial link to Marlin is invisible over MQTT | Obs `CONFIRMED` | `captures/README.md` |
| F-007 | Why don't we *have* these facts? | `normalize()` maps only `1000/1001/1003/1004/1006/1052`. **Anything it does not name can never become a fact**, whatever the printer sends. No `1005` branch | Tier 3, `web/service/state.py` | — |

### Homing — the oldest problem, now largely explained

| # | Question | Answer | Status | Depth |
| --- | --- | --- | --- | --- |
| F-010 | When does Z actually home? | Only when **nozzle ≥ `EXTRUDE_MINTEMP` (160C) AND `g36_running_flag`** — `G28.cpp:263`. Otherwise an `else` branch sets `is_home_z` and moves nothing *there* | Tier 1 `CONFIRMED` | findings, homing |
| F-011 | What sets that flag? | **`G36` alone** (`auto_align`, `anker_align.cpp:96`) — **and it calls `G28` itself** (`:100`). G36 is the entry point for homing, not a separate leveling command | Tier 1 `CONFIRMED` | — |
| F-012 | **What drove the nozzle into the plate?** | `homeaxis(Z_AXIS)` at `G28.cpp:185`, reached via `after_homing_action` → **`G2001`** → `home_z_safely()`. **That path checks neither temperature nor the flag.** On no-detect it descends `1.5 × max_length(Z)` and marks the axis homed anyway | Tier 1 `CONFIRMED` | findings, descent trace |
| F-013 | So why do normal prints home fine? | **Unknown — and the code path is not the difference.** A slicer print takes the identical route. Only the probe mode differs (`Probe_homeaxis(Z,2)` vs `(Z,1)`) | **`UNVERIFIED` — the live question** | §6 |
| F-014 | What *is* the probe? | A **strain gauge on a detached nozzle board**, read via a CS1237 load-cell ADC over UART, armed per-descent with a threshold (`HOMING_PROBE_VALUE 650` / `LEVEING_PROBE_VALUE 600`, runtime-settable via `M3020`). **Not an endstop pin** — so `M119`'s `z_probe: open` could never have meant anything | Tier 1 `CONFIRMED` | findings, probe chain |
| F-015 | Any hard failure mode? | **Yes — failed alignment calls `kill()`**, a Marlin halt needing a reset (`anker_align.cpp:131`) | Tier 1 `CONFIRMED` | — |
| F-016 | Why won't X/Y jog move? | **`NO_MOTION_BEFORE_HOMING` is enabled** (`Configuration.h:1368`). The `echo:Home X/Y` refusals are that feature, working as designed | Tier 1 `CONFIRMED` | — |

### Motion and confirmation

| # | Question | Answer | Status | Depth |
| --- | --- | --- | --- | --- |
| F-020 | Can `M114` prove the toolhead moved? | **No.** `M114_DETAIL`/`_REALTIME`/`_LEGACY` all compiled out, so it reports `current_position` and `planner.position` — the planner's intent. It can prove acceptance, refusal, and (with `M400`) queue completion. **Nothing on this printer can prove physical motion** | Tier 1 `CONFIRMED` | [`jog-confirmation-research.md`](jog-confirmation-research.md) |
| F-021 | Can a jog action be confirmed? | Up to "accepted, queued, drained" — never "moved". Contract needs designing; `FACT_PATHS` has no position entry | Inf `CONFIRMED` | issue #12 |
| F-022 | Can a fan action be confirmed? | **Yes in principle — see F-003.** Not as currently implemented: ankerctl sends raw `M106`, and `//#define REPORT_FAN_CHANGE` means the MCU never tells the module a G-code changed the fan | Inf **strong** | §5 |

## 4. Settled — do not re-derive

Each of these cost real time at least once.

- **The M5C never pushes `state`.** It exists only as an `APP_QUERY_STATUS` reply
  and is stale 15s later. Any design gating on "fresh state" inherits this; it is
  what produced `fresh_printer_state_required` fan rejections twice.
- **The lazy MQTT service ages facts between short-lived connections.** Do a
  warm-up `/ws/state` read immediately before submitting an action.
- **A fan observation with a hot hotend is not attributable** — the firmware runs
  its own hotend fan above a threshold. Establish silence from a cold machine.
- **`/ws/ctrl` replying `{"ankerctl":1}` is not the printer.** Real replies land
  on `/ws/mqtt` as `1043` with `resData`, plus a `+ringbuf:N,512,M` suffix.
- **"The printer is silent" usually means ankerctl** — but not always. Check
  `/opt/ankerm5c/logs/mosquitto.out.log` first and branch on whether printer
  PUBLISHes continue.
- **Stop and Pause/Resume payloads differ deliberately.** Pause/Resume need
  `userName` + `filePath`; Stop is global and identity-free. Conflating them is
  the 2026-07-13 regression.
- **`PRINT_CONTROL` payloads were captured and live-validated, never inferred.**
  There is no payload convention to extrapolate from — four shapes across three
  opcodes, one of which takes two.

## 5. Refuted — do not resurrect

Kept visible on purpose. Most died in the 2026-07-27/28 audit; several had been
propagating through four documents each.

| Dead claim | What killed it |
| --- | --- |
| "This printer publishes no fan-state fact" | `1005` observed at 99 then 0 across a print. **F-003** |
| "Production firmware does not honour `G36`" | The 2026-07-09 tests ran the nozzle at **150C**; `EXTRUDE_MINTEMP` is **160**. Never given a hot enough nozzle |
| "Standalone `G28` can never home Z" | The `else` branch *defers* homing to `G2001`; it descends. **F-012** |
| "Probing is temperature-gated / a hot nozzle would home" | `PREHEAT_BEFORE_PROBING` is commented out; `PROBING_NOZZLE_TEMP` sits in a dead `#if`. **Do not run a heated homing test on this reasoning** |
| "The Linux upper computer has never been published" | `eufyMake-linux-sdk` is public. The claim came from searching only the Marlin repo |
| "`USE_Z_SENSORLESS` is undefined, the probe block may be dead code" | Defined in `ANKER_Config.h:69` — the third config file |
| "`M114` reports raw stepper counts" | `Count X:` is `planner.position`. **F-020** |
| "The probe is gated by Anker's comm module" | The gate flag is set inside `G28.cpp`. Evidence against, though not fully closed |
| "This printer has no proprioception" | `M114` always worked; the codebase never asked |
| "`M401` won't move anything" | It lifted the toolhead 14.9mm |
| "`z_probe: open` under load proves a fault" | StallGuard senses only during motion — and the probe isn't on that pin at all. **F-014** |

## 6. Open, ranked

1. **F-013 — why the probe registers hot and not cold.** The one that gates any
   future homing work. Not answerable from MQTT (**F-006**); needs the module's
   own firmware (`eufyMake-linux-sdk`, unexamined) or serial access to the
   module↔Marlin UART.
2. **Wire `1005` and switch `fan_setting` to the native opcode** — makes the fan
   action genuinely confirmable. Closes the fan half of #15.
3. **`G36` in `print_start` (#25)** — ungated, and `ANKERCTL_PREPRINT_G36` does
   not reach that path. Blocks #18.
4. **Map the control layer to Tier 1 (#26)** — the ledger's firmware section read
   two of three config files, so any row may share the defect.
5. **Jog contract (#12)** — unblocked but undesigned; see F-020/F-021.

## 7. Safety — not subject to evidence

[`CLAUDE.md`](../CLAUDE.md) and [`AGENTS.md`](../AGENTS.md) bind regardless of how
good the evidence is. Reading source never authorises sending.

- Fresh, current-session operator confirmation before anything that moves, heats,
  or starts/pauses/resumes/stops. Read-only observation does not need it — and
  has produced more than any command we have sent.
- **Home stays disabled.** `G28` containing Z stays blocked at `/ws/ctrl`. F-012
  is why: it descends.
- **A hot nozzle is not a safety argument** — the temperature check guards only
  the G36 branch, not the path that moves.
- Never commit secrets or setup-specific values; run `./scripts/check-secrets.sh`
  before every stage, commit, or push.

## 8. Where everything lives

| Doc | Read it for |
| --- | --- |
| **`INDEX.md`** (this) | Orientation, settled/refuted, pointers |
| [`method.md`](method.md) | Source hierarchy, guardrails, conflict resolution |
| [`printer-findings.md`](printer-findings.md) | The canonical ledger — every claim with a confidence grade |
| [`captures/`](captures/) | **Primary evidence.** Raw MQTT JSONL + how to verify each finding |
| [`audit-2026-07-27.md`](audit-2026-07-27.md) | The contradiction sweep and its dispositions |
| [`jog-confirmation-research.md`](jog-confirmation-research.md) | What can confirm a jog (#12) |
| [`printer-test-validation.md`](printer-test-validation.md) | Test gates, live procedure, Stop/Pause/Resume contract |
| [`local-macos-service.md`](local-macos-service.md) | Runbook: setup, topology, recovery |
| [`local-control-research.md`](local-control-research.md) | Long-form research narrative |
| [`../CONTEXT.md`](../CONTEXT.md) | Printer-action vocabulary |
| [`../docs/adr/`](../docs/adr/) | Architecture decisions |
| [`../handoff.md`](../handoff.md) | Current session state and next steps |

## 9. Adding to this index

- **Pointers and status, not restated content.** Anything duplicated here will
  drift from its source. Where you assert, cite — file:line, a capture, or a date.
- **Say whether it is observation or inference.** They are both usable; conflating
  them is how a guess became `CONFIRMED` and spread.
- **Never delete a refuted entry.** Move it to §5 with what killed it. A visible
  wrong belief is far cheaper than one re-derived every third session.
- **Fact IDs are stable.** Supersede by editing the row and noting what changed;
  do not renumber.
