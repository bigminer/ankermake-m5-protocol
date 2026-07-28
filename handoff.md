# Session handoff

Last updated: 2026-07-28.

**Read [`documentation/INDEX.md`](documentation/INDEX.md) first.** It carries what
is *known* — settled facts, refuted claims, open questions, with verify commands.
This file carries only what is *current*: repo state, printer state, and what to
do next. If the two disagree, the index wins and this file is stale.

Facts do not belong here. When a session produces a finding, put it in the ledger
and the index, and leave a pointer.

---

## Repository and GitHub targeting

- Working repo is
  [`bigminer/ankermake-m5-protocol`](https://github.com/bigminer/ankermake-m5-protocol).
  `origin`; local `main` tracks `origin/main`. Every bare `#N` here means that repo.
- The `upstream` remote points at `anselor/ankermake-m5-protocol` — an external
  reference and the archive for old branches. **Not a merge or push destination.**
  Do not delete branches there.
- **`gh` must stay pinned:** `gh repo set-default bigminer/ankermake-m5-protocol`.
  Without it `gh` resolves to `upstream` and reports that plainly existing PRs
  cannot be found. Re-run after a fresh clone or any `.git/config` reset.

## Current repository state

- **`main` == `origin/main`, everything pushed.** No open PRs. The
  `chore-handoff-branch-state` and `fan-copy-and-jog-research` branches are fully
  merged and can be deleted with `git branch -d`.
- `origin` holds only `main`. Older branches were removed after confirming they
  were byte-identical to their `upstream` counterparts; `upstream` is the archive.
- **`.env` is tracked and permanently dirty** on `FLASK_HOST` only — the committed
  default is `127.0.0.1`, this machine binds elsewhere. Expected. **Never stage it.**
- Gates, all currently green: 172 offline tests, 28 browser tests,
  `./scripts/check-secrets.sh`, and `python scripts/check-docs.py`.

## Current printer state

**Idle and safe.** A full Orca print completed on 2026-07-28 and cooled out:
state `4`, nozzle and bed targets `0`, fan off. Nothing is running, nothing needs
resuming.

**The printer is gated.** `ANKERCTL_ACTION_VALIDATION_MODE` is `false` and
`ANKERCTL_VALIDATED_ACTION_CONTRACTS` is absent from the LaunchAgent, so every
named action returns `supervised_validation_required`.

Operator presence alone is not clearance. Before any motion, heat, fan, print, or
pause/resume/stop, get fresh confirmation that the bed and toolhead path are
clear, the filament path is safe where relevant, and power is immediately
accessible.

## What changed this session

Three days of work landed; the detail is in the index and ledger.

- **Homing is largely explained** — a gate nobody had read, not a missing opcode.
  See INDEX F-010 → F-016. The plate-strike descent is traced to a specific line.
- **`1005` is fan speed**, observed across a print and now wired into
  `normalize()` and `FACT_PATHS`. INDEX F-003, F-007, F-008.
- **A system of record**: `INDEX.md` as the single front door, `method.md` for the
  source hierarchy, `captures/` holding primary evidence, and
  `scripts/check-docs.py` enforcing it in CI.
- **An audit** found the same refuted claim living in four files; eleven dead
  claims are now listed in INDEX §6 so they stay dead.

## Next work

**Ordered in [`documentation/INDEX.md`](documentation/INDEX.md) §7 — use that, not
intuition.** Several open questions are interesting but not on the path to the
goal. Briefly:

| Next | Why | Needs printer? |
| --- | --- | --- |
| [#25](https://github.com/bigminer/ankermake-m5-protocol/issues/25) — ungated `G36` in `print_start` | Blocks #18; cheapest real unblock | No |
| [#28](https://github.com/bigminer/ankermake-m5-protocol/issues/28) — capture the official app | **The bottleneck.** Unblocks #29 *and* the payload half of #12 in one session | Yes — operator, plus a topology change |
| [#29](https://github.com/bigminer/ankermake-m5-protocol/issues/29) — `fan_setting` → native `FAN_SPEED` | Makes one action genuinely confirmable. Blocked by #28 | No, once #28 lands |
| [#26](https://github.com/bigminer/ankermake-m5-protocol/issues/26) — map control layer to firmware | The ledger's firmware section read 2 of 3 config files | No |
| [#30](https://github.com/bigminer/ankermake-m5-protocol/issues/30) — per-fact freshness | On-change facts read `stale` while accurate. Has already cost two runs | No |
| [#12](https://github.com/bigminer/ankermake-m5-protocol/issues/12) — jog contract | Needs design first; `needs-triage`, not agent-ready | No |
| [#27](https://github.com/bigminer/ankermake-m5-protocol/issues/27) — probe discriminator | Gates all homing work. Not answerable over MQTT | No |
| [#31](https://github.com/bigminer/ankermake-m5-protocol/issues/31) — CI Release step | Every `main` build shows a red X; trains everyone to ignore checks | No |

**#15 can close** once the operator adds three thermal contracts to the
LaunchAgent — `nozzle_target`, `bed_target`, `heater_off`. The fan half is
separate and now depends on the native-opcode work above.

### Issue disposition

| Issue | State |
| --- | --- |
| #6 | Open parent. **User story 7 needs revising** — it promises physically-backed confirmation that jog and live-Z cannot give |
| #9, #16 | Open, `ready-for-human`. Need the operator and the setup below |
| #12, #13 | **`needs-triage`** — were mislabelled agent-ready; specs are incomplete |
| #15 | Open; three thermal contracts away from closing |
| #17 | Open; **two acceptance criteria cannot pass as written** |
| #18 | Open; **blocked on #25** |
| #19 | Open; blocked on the validations |
| #25, #26, #27 | New, offline, unstarted |
| #28 | New. `ready-for-human` — needs the operator and a topology revert. **Blocks #29 and part of #12** |
| #29, #30, #31 | New, offline. #29 blocked by #28; #30 and #31 unblocked |
| #5, #7, #8, #10, #11, #14 | Closed |

**Every known task is now on the tracker.** Four items had been living only in
prose until 2026-07-28 — the native fan opcode, the app capture, per-fact
freshness, and the CI defect. If a session finds work that exists only in a
document, open an issue for it rather than leaving it here.

## Running a supervised validation

Established 2026-07-26. #9, #16, #17 and #18 all need this setup.

**Do not enable validation mode by editing the LaunchAgent.** Run a temporary
instance with the variable in its process environment:

1. `launchctl bootout gui/$(id -u)/com.ankerctl.webserver`
2. Read the plist's `EnvironmentVariables` with `plutil -convert json`, inject
   them into `os.environ` without printing them, override
   `ANKERCTL_ACTION_VALIDATION_MODE=true`, then `exec` `ankerctl.py --insecure
   webserver run --host 127.0.0.1`
3. Run the validation
4. Kill the process, then `launchctl bootstrap gui/$(id -u) <plist>`

Why: **ungating dies with the process.** Persistent configuration never leaves
`false`, so an interrupted run cannot leave the printer ungated — the failure
mode the plist approach has. Loopback also keeps a temporarily ungated server off
the network. Editing a LaunchAgent is a system-configuration change to hand back
to the operator, not perform.

Verify the gate before and after: a named action must return
`supervised_validation_required` outside the run.

Three conditions waste runs — all three have already cost one:

- **The M5C never publishes `state`.** It exists only as an `APP_QUERY_STATUS`
  reply and is stale 15s later, so an action with a freshness gate fails unless
  status was polled immediately before.
- **The lazy MQTT service ages facts between connections.** Warm-up `/ws/state`
  read immediately before submitting.
- **Physical observations need a baseline.** A fan observation with a hot hotend
  is unattributable — the firmware runs its own hotend fan above a threshold.
  Cool down and confirm silence first.

## Standing constraints

These outlive any session. Parent design is
[#6](https://github.com/bigminer/ankermake-m5-protocol/issues/6).

- **Home stays disabled**, in the UI and at the `/ws/ctrl` rejection. INDEX F-012
  is why: a `G28` containing Z descends via an unguarded path. **A hot nozzle is
  not a safety argument** — the temperature check guards only the G36 branch.
  Omitting standalone Home permanently remains an acceptable outcome.
- **Never add Pause/Resume identity fields to Stop.** Pause/Resume need the exact
  server-recorded upload identity; Stop is global and identity-free. Conflating
  them caused the 2026-07-13 regression.
- **#9 has an unsolved fixture problem.** Synthetic zero-motion files never become
  active jobs, so there is nothing to Stop. Do not substitute a normal sliced
  print without a separate safety review.
- **#16 needs a separately authorised, known-safe real print** and the exact
  server-recorded upload identity.
- **Actions are enabled per-action, never wholesale.**
  `ANKERCTL_VALIDATED_ACTION_CONTRACTS` for validated ones;
  `ANKERCTL_ACTION_VALIDATION_MODE` ungates everything and is only for an
  attended run.
- **Never guess an opcode payload.** There is no convention to infer from — four
  shapes across three opcodes. Capture the official app instead.

## Mandatory safety

[`CLAUDE.md`](CLAUDE.md) and [`AGENTS.md`](AGENTS.md) bind regardless of evidence
quality. Reading source never authorises sending. Read-only observation needs no
confirmation — and has produced more than any command we have sent.

Do not put secrets or personal setup values in tracked files, tool output,
commits, PRs, or issues. Never print the full LaunchAgent configuration; it
contains authentication material.

## Useful commands

```sh
PYTHONPATH=. .venv/bin/pytest -q -m 'not live_printer'
```

```sh
./scripts/check-secrets.sh && python scripts/check-docs.py
```

```sh
curl -fsS http://127.0.0.1:4470/api/version
```

Read-only printer observation — neither sends a control command:

```sh
.venv/bin/python scripts/printer-probe.py status
```

```sh
.venv/bin/python scripts/capture-mqtt.py out.jsonl 900
```

Do not run live-printer tests merely because their environment flags are
available. Current-session operator confirmation is mandatory.
