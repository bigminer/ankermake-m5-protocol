# Captures

Raw, passively recorded MQTT traffic. **Primary evidence** — the findings derived
from it live in [`../printer-findings.md`](../printer-findings.md), but the
conclusions there should be checkable against these files rather than taken on
trust. Per [`../method.md`](../method.md) this is Tier 0: direct observation of
this machine.

Recorded with [`scripts/capture-mqtt.py`](../../scripts/capture-mqtt.py), which
only listens on `/ws/mqtt`. Nothing in a capture session is sent to the printer.

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
| **Zero `1043` messages in the entire run** | `grep -c 1043` → 0 |
| `1052` and `1037` are sent once at job start | part 1, early |
| Preheat matched the slicer profile: nozzle 150 → 220, bed 60 | `1003`/`1004` targets |
| Cooldown to nozzle 38C / bed 46C with targets 0 | part 2, tail |

### Useful one-liners

```sh
# every non-temperature message, in order
grep -vE '"commandType":100[34]' documentation/captures/2026-07-28-orca-print-part1.jsonl

# the fan events
grep '"commandType":1005' documentation/captures/*.jsonl

# state transitions only
grep '"commandType":1000' documentation/captures/*.jsonl | grep -oE '"value":[0-9]+' | uniq -c
```
