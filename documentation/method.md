# Method — goal, sources, guardrails

> **Start at [`INDEX.md`](INDEX.md), not here.** It summarises this document in
> one table and points at the rest. Come here for the full hierarchy and the
> conflict-resolution rules.

The ledger records *what* we believe and how much. This records *what counts as a
reason to believe it.* When the two conflict, this document sets the rule and the
ledger entry gets re-graded.

Written 2026-07-27, after an audit found that this project's own derived
artifacts were being cited as evidence about the printer. See
[`audit-2026-07-27.md`](audit-2026-07-27.md).

---

## 1. The goal

**Replicate the original AnkerMake software's behaviour locally, so the cloud
provider is not needed.**

Three consequences that decide most arguments:

- **The design decisions are already made.** This is replication, not product
  design. When a behaviour question arises the first move is *what did the
  original do?* — not *what would be reasonable?* A gap in the sources is a
  research task, not a decision to hand to the operator.
- **Divergence from the original is a defect, not a feature.** Where `ankerctl`
  does something the original does not — raw G-code where a dedicated opcode
  exists, a poll where the original pushes — that is a bug to be explained,
  even when it appears to work.
- **The printer is deprecated and the cloud is going away.** Local completeness
  matters more than elegance. Prefer the mechanism the original used.

The parent design for the control layer is issue #6.

---

## 2. Source hierarchy

Every claim about the printer cites a tier and a locator. **A lower tier number
wins.** This is the part that was missing and it is the point of the document.

### Tier 0 — the machine

Direct supervised observation of this physical printer: telemetry read back,
replies captured, what the operator saw or heard.

Authoritative about *this unit as built*, and nothing else. Expensive, often
ambiguous, and easy to misattribute — every Tier 0 claim must survive the
question in §4.

### Tier 1 — first-party published source

What the manufacturer actually shipped.

| Source | Covers |
| --- | --- |
| [`eufymake/eufyMake-Marlin-M5C`](https://github.com/eufymake/eufyMake-Marlin-M5C) | MCU firmware. **V8110 is the M5C.** Includes `Configuration/V8110/V8110_DVT/`, `src/gcode/anker_gcode/`, and `src/feature/anker/` (`anker_homing`, `anker_pause`, `anker_z_offset`, `anker_z_sensorless`, `anker_leveing`, `handshake`, `anker_m_cmdbuf`, …) |
| [`eufymake/eufyMake-linux-sdk`](https://github.com/eufymake/eufyMake-linux-sdk) | The upper computer's Linux BSP — bootloader, buildroot, kernel, drivers |
| [`eufymake/eufyMake-PrusaSlicer-Release`](https://github.com/eufymake/eufyMake-PrusaSlicer-Release) | Slicer, profiles, and what the original emits |
| Captured wire traffic from the **official eufyMake app** | First-party behaviour, observed. The only way to learn an opcode's payload |

Authoritative about intended behaviour. **Check the build config actually used** —
a feature present in Marlin may be compiled out for V8110_DVT, which is exactly
the fan case.

Three rules learned the hard way on 2026-07-28, all of which produced wrong
conclusions first:

- **There are THREE config files, not two.** `Configuration.h`,
  `Configuration_adv.h`, **and `src/inc/ANKER_Config.h`**, which holds the Anker
  feature switches. The ledger's firmware section read the first two and
  concluded `USE_Z_SENSORLESS` was undefined and its block dead. It is defined,
  in the third file, and the block is live.
- **Read the enclosing block, never the matching line.** `PROBING_NOZZLE_TEMP
  140` is uncommented — inside `#if ENABLED(PREHEAT_BEFORE_PROBING)`, which is
  off. A code-search hit showed it live; a page summariser said it was commented;
  both were misleading. **Fetch the file and read around the line.**
- **Mind the version skew.** `ANKER_Config.h` declares
  `SHORT_BUILD_VERSION "V8110_V3.0.21"` while our printer runs **V3.1.56**. The
  published source is older than the installed firmware. Tier 1 is strong
  evidence about intent and structure, not guaranteed byte-truth for the machine.

### Tier 2 — community reverse-engineering

`Ankermgmt/ankermake-m5-research`, `sondregronas/ankermake-hass-component`, the
`anselor` upstream, blog write-ups.

Useful for leads and corroboration. **Never sufficient alone.** Much of it
targets the **M5**, not the M5C, and the two differ.

### Tier 3 — this repository

`specification/*.stf`, `libflagship/`, `web/`, `static/`, and every generated
opcode table.

**These are not evidence about the printer.** They are our hypotheses, written
down. `specification/mqtt.stf` is a hand-maintained reverse-engineering artifact;
`libflagship/mqtt.py` is generated from it and says "DO NOT EDIT" because a tool
wrote it, not because anyone verified it.

A Tier 3 citation may only support a claim of the form *"this is what ankerctl
currently does."* It can never support *"this is what the printer does."*

> **The failure this replaces.** On 2026-07-27 the argument "the `0x3ed` opcode
> is solid because `mqtt.stf` declares it unhedged" was used to justify sending
> an unexercised command. The absence of a `?` marker records a prior
> reverse-engineer's confidence. It is not evidence. The whole spec is Tier 3.

---

## 3. Guardrails

### Safety is not part of this hierarchy

`CLAUDE.md` and `AGENTS.md` bind regardless of how good the evidence is. Fresh
current-session operator confirmation before anything that moves, heats, or
starts/pauses/resumes/stops. Reading source never authorises sending.

### Name the layer

Four layers, and conflating them has caused real regressions:

1. **Marlin MCU** — motion, heat, endstops. Speaks G-code over serial.
2. **Communication module** (Linux upper computer) — owns jobs, speaks MQTT
   command types, translates to G-code.
3. **`ankerctl`** — our server.
4. **Browser UI.**

A firmware fact constrains layer 1 only. `//#define REPORT_FAN_CHANGE` means the
MCU never volunteers a fan change; it says nothing directly about what the
communication module reports over MQTT. Conversely `M2024` reaching the MCU says
nothing about the module's job state — which is precisely the 2026-07-10 Stop
incident.

### Never infer a payload from another opcode's payload

There is no house convention. Four outbound shapes are in use across three
command types, and `PRINT_CONTROL` alone takes two of them depending on
operation — conflating those two is the documented 2026-07-13 regression.

Every payload we trust was **captured or live-validated**, never pattern-matched.
An unexercised opcode's payload is unknown until it is observed, and the way to
observe it is to capture the official app.

### Grade every claim, and cite

Use the `printer-findings.md` status legend. Add the tier and locator: a repo
path with a line number, a URL, or a dated observation. A claim with no locator
is not a finding.

### Ask whether the test could have measured what you think

The single most valuable entry in the ledger is an `INVALID-TEST`. Before
recording a result, name the confounds and say why they do not apply. Cold
printer for a fan test; established silence before an audible observation.

### Never delete a refuted entry

Mark it `REFUTED`, say what killed it. A visible wrong belief is cheaper than one
re-derived every three sessions.

---

## 4. Resolving a conflict

- **Tier 3 versus anything** — Tier 3 loses. It was never evidence.
- **Tier 2 versus Tier 1** — Tier 1 wins; check whether the Tier 2 source was
  describing the M5 rather than the M5C.
- **Tier 0 versus Tier 1** — this is a *finding*, not a tie-break. The shipped
  build differs from what the published source suggests, or the observation is
  confounded. Record both and investigate; never silently pick one.
- **Two Tier 0 observations** — the later one does not automatically win. Prefer
  the one with fewer confounds and say why.

When a conflict is resolved, fix **every** copy of the losing claim. The audit
found the same unsupported statement in four places, corrected in two.

---

## 5. Applying this to open questions

Not yet done — this is the backlog the audit implies, in dependency order.

1. ~~**Map the control layer to Tier 1.**~~ **Done 2026-07-28 (issue #26).** Every
   command `ankerctl` sends now has a cited implementation or an explicit "not
   determinable from source". See INDEX F-030…F-038 and `printer-findings.md`
   §"The control layer, mapped to published source". The load-bearing result is
   `ak_gcode_parse` (`queue.cpp:414`): the module's traffic is sorted into four
   classes before dispatch, so **an `ok` means something different per command**.
2. **Homing, against `src/feature/anker/`.** The oldest open problem, the one
   with physical consequences, and the standing "probe arming is unreachable"
   conclusion is a black-box inference about published code. **Partly advanced:**
   F-034 shows a real print takes the same descent path as the plate strike, so
   the question is now the `is_clean` preamble or probe arming — not the branch.
3. ~~**The upper computer.**~~ **Answered 2026-07-28: only the BSP.**
   `eufyMake-linux-sdk` is bootloader, kernel, buildroot and device drivers. It
   ships `paho-mqtt-c`/`-cpp`, so the upper computer speaks MQTT through paho,
   but the Anker application that owns job state and translates command types to
   G-code is not in the repository. **Opcode payloads are therefore not readable
   from source; capturing the official app is the only route.** INDEX F-033.

   ⚠️ **`gh search code` does not index that repo** — every query returns zero,
   including control terms certain to match. Enumerate the git tree instead, and
   run a control query before reading any zero-result as absence. INDEX A-10.

Only then is it worth spending printer time.
