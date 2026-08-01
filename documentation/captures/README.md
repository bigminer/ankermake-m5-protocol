# Captures

Raw, passively recorded MQTT traffic. **Primary evidence** — the findings derived
from it live in [`../printer-findings.md`](../printer-findings.md), but the
conclusions there should be checkable against these files rather than taken on
trust. Per [`../method.md`](../method.md) this is Tier 0: direct observation of
this machine.

Recorded with [`scripts/capture-mqtt.py`](../../scripts/capture-mqtt.py), which
only listens on `/ws/mqtt`. Nothing in a passive capture session is sent to the
printer.

⚠️ **One file here is an *active read* session, not a passive capture** —
[`2026-08-01-gcode-reply-truncation-probe.jsonl`](2026-08-01-gcode-reply-truncation-probe.jsonl).
It sent commands, each verified read-only against published firmware source
before sending. It is marked as such in its first record. Do not treat it as
evidence of what the printer volunteers unprompted.

## Format

JSONL, one message per line, as delivered by `/ws/mqtt`, plus two added fields:

| Field | Meaning |
| --- | --- |
| `_t` | seconds since capture start |
| `_wall` | local wall clock, `HH:MM:SS` |
| `_event` | collector lifecycle only (`connected`, `recv_failed`, …), not printer data |

## Sanitisation

**These files are redacted**, because the repo is shareable. Three fields carry
account- or user-linked identifiers and were replaced. Everything else — every
`commandType`, `value`, temperature, timestamp, and ordering — is untouched.

| Field | Replaced with |
| --- | --- |
| `task_id` | `<redacted-job-uuid>` |
| `modelId` | `<redacted-model-id>` |
| `name` (job filename) | `example_model_0.2mm_PLA_Anker_M5C.gcode` |

The substitute filename keeps the slicer's real naming shape
(`<model>_<layer height>_<material>_Anker_M5C.gcode`), which is the only
evidentially relevant part.

---

## `2026-07-28-orca-print-part1.jsonl` / `-part2.jsonl`

A complete Orca-started print on firmware V3.1.56, captured end to end: idle
baseline, job start, preheat, homing, all 43 layers, completion, and cooldown.
The operator started the print and was present throughout; this session issued no
command of any kind.

Two files because the first collector's window expired mid-print and a second was
started before it ended. **They overlap** — part 2 begins at `15:46:11` while part
1 runs to `15:50`. Deduplicate on `_wall` plus payload if merging.

Model was a small functional part in PLA, 43 layers, ~14 minutes.

### What these captured

| Observation | Where to look |
| --- | --- |
| **`1005` is fan speed** — `value: 99` early, `value: 0` at 100% | part 1 `_t≈311`; part 2 `_t≈528` |
| It is published **on change only** — 2 messages in ~25 minutes | grep `1005` across both |
| **`1026` correlates with homing** — once per capture, both after a `G28` | part 1 `_t≈261`; part 2 `_t≈540` |
| **State `8` = preparation**, held ~123s before state `1` | part 1, `1000/subType 1` |
| **State `4` follows normal completion**, not only Stop | part 2, after progress `10000` |
| **No module-originated `1043`** — part 1 has none; part 2 has exactly **one**, an `M105` reply (`ok T:36.00 /0.00 B:43.60 /0.00`) answering a poll our own web UI sends. ⚠️ Corrected 2026-08-01; this row previously read "zero in the entire run", which was false against the file | part2 line 1227 |
| `1052` and `1037` are sent once at job start | part 1, early |
| Preheat matched the slicer profile: nozzle 150 → 220, bed 60 | `1003`/`1004` targets |
| Cooldown to nozzle 38C / bed 46C with targets 0 | part 2, tail |

---

## `2026-08-01-gcode-reply-truncation-probe.jsonl`

**Active read session** (see the warning above). Eight G-code reads, each
repeated 2–4 times, recording the complete `1043` reply and whether it was
truncated. This is the primary evidence for INDEX F-040, F-041 and F-043.

| Observation | Where to look |
| --- | --- |
| **A reply is complete iff `resData` ends with `ok\n`** — holds on all 8 | `_ends_with_ok` vs `_semantically_complete` |
| **`resLen` does not predict completeness** — `M851` (45) and `M119` (108) complete; `M114` (64) truncated | compare `resLen` across records |
| **512 is the ceiling, never exceeded** — but most truncation is far below it | `M115`, `M503` |
| **Over the ceiling, replies are *spliced*, not just cut** | `M503` `_note` |
| The splice **drifts between runs** | `M503` `_identical_across_runs: false` |
| Byte loss is proven, not a firmware quirk | one `M503` frame holds both `echo:; PID settings:` and `; Controller Fan` |
| `M913` is the sole evidence for F-041 | `M913` record |

---

## `2026-08-01-live-print-1001-fields.jsonl`

**Passive** capture during a live ~3h print, operator present, nothing sent.
Filtered to `commandType 1001` only. Primary evidence for INDEX **F-044**.

| Observation | Where to look |
| --- | --- |
| **`time` is remaining MILLISECONDS** — `9472157` while ~2.6h remained | any record's `time` |
| **`time` is a re-estimate, not a countdown** — it rose +443/s over 288s | compare `time` at first and last record |
| **`totalTime` is overloaded** — `172` then `191` before printing (an estimate), then resets and counts elapsed seconds at 1.00/s | `totalTime` across the first ~40 records |
| **`progress` is hundredths of a percent** | `progress` vs elapsed |
| `startLeftTime` is stuck at `1` — not a countdown | any record |

This capture found a live UI defect: the raw `time` reached the dashboard as
seconds and rendered **`2631:07:34`**. Fixed in `web/service/state.py`, regression
test in `tests/test_state_normalize.py`.

### Useful one-liners

```sh
# every non-temperature message, in order
grep -vE '"commandType":100[34]' documentation/captures/2026-07-28-orca-print-part1.jsonl

# the fan events
grep '"commandType":1005' documentation/captures/*.jsonl

# state transitions only
grep '"commandType":1000' documentation/captures/*.jsonl | grep -oE '"value":[0-9]+' | uniq -c
```
