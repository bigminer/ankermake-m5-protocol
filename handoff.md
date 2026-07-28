# Session handoff

Last updated: 2026-07-26

## Repository identity and GitHub targeting

- The repository for this work is
  [`bigminer/ankermake-m5-protocol`](https://github.com/bigminer/ankermake-m5-protocol).
  Its Git remote is `origin`, and local `main` tracks `origin/main`.
- Unless a full repository URL says otherwise, every issue, pull request,
  branch, and `#N` reference in this handoff belongs to the `bigminer`
  repository.
- The Git remote named `upstream` currently points to
  `anselor/ankermake-m5-protocol`. It is an external repository reference, not
  the working repository or the default destination for merges and pushes.
- `anselor/ankermake-m5-protocol#15` was an external pull request sourced from
  the former `bigminer:local-control` branch. It closed unmerged when that
  fully merged source branch was removed. It is not “PR #15” in the working
  repository.
- [`bigminer/ankermake-m5-protocol#15`](https://github.com/bigminer/ankermake-m5-protocol/issues/15)
  is the open **issue** “Supervised validation: thermal and fan actions”; there
  is no pull request #15 in the working repository.
- `gh` is pinned to the fork via `gh repo set-default
  bigminer/ankermake-m5-protocol`, which writes `remote.origin.gh-resolved` to
  the untracked local `.git/config`. Without it `gh` resolves to `upstream`
  (`anselor/...`) and reports that plainly existing PRs cannot be found. Re-run
  it after a fresh clone or any `.git/config` reset.

## Current repository state

- `main` and `origin/main` are synchronized at `4d7268f`, the merge of
  [#24](https://github.com/bigminer/ankermake-m5-protocol/pull/24) (issue 14 —
  upload, preparation, and print start as a staged Compound action). Its branch
  was deleted locally and on the remote. Issue 14 is closed. No open pull
  requests, no other local branches.
- Earlier, `main` was at `df6f971`. Three PRs merged on
  2026-07-26: [#21](https://github.com/bigminer/ankermake-m5-protocol/pull/21)
  (thermal/fan actions plus two Protective fixes),
  [#22](https://github.com/bigminer/ankermake-m5-protocol/pull/22) (per-action
  contract ungating wired to configuration), and
  [#23](https://github.com/bigminer/ankermake-m5-protocol/pull/23) (2026-07-26
  validation evidence). Issue 10 is closed.
- Issue 10 delivered typed nozzle-target, bed-target, heater-off, and fan
  actions; server-owned validation, freshness, supersession, confirmation,
  journaling, and contract gating; validation-mode browser integration; and
  deterministic offline/browser coverage.
- Two Protective defects were found in review and fixed in `367346a`: a
  Protective Stop left pending heater targets to decay into
  `confirmation_timeout` (they now become `superseded/protective_stop_submitted`),
  and fan-off was gated on fresh state while heater-off was not. A pending *fan*
  request is deliberately still left alone by Stop, because Stop sends only
  `PRINT_CONTROL` and `M2024` and there is no evidence it halts the fan.
- `ANKERCTL_VALIDATED_ACTION_CONTRACTS` (`5342fba`) ungates individual validated
  actions. Before it, `ANKERCTL_ACTION_VALIDATION_MODE` was the only production
  lever and is all-or-nothing: graduating one validated action would have
  ungated unvalidated motion, upload, and print start at the same time. It fails
  closed on a typo and never aborts startup; see the runbook section in
  `documentation/local-macos-service.md`.
- Checks on `main`: 168 offline tests pass with 8 deselected; 28 browser tests
  pass; `git diff --check` and the secret sweep pass. PR #24's CI (build, test,
  secret-sweep) passed before merge.
- **`origin` now holds only `main`.** An earlier pass removed `local-control`,
  `master`, `exiles-1.1-rebased`, `pyinstaller`, and `treitmayr_mqtt-commands`
  as merged or patch-empty. The remaining four — `abale_print-stability-fix`,
  `exiles`, `exiles-1.1-defunct`, `parameterize_docker` — were deleted on
  2026-07-27.

  They had been kept on the grounds that they still contained unique commits.
  That was true but incomplete: unique to `main`, not unique to this fork. All
  four were byte-identical to their `upstream` counterparts, so deleting them
  from `origin` lost nothing. Restore any of them with:

  ```sh
  git push origin upstream/<branch>:refs/heads/<branch>
  ```

  Pre-deletion SHAs, if a restore needs verifying: `abale_print-stability-fix`
  `d71c2ab`, `exiles` `91eafbe`, `exiles-1.1-defunct` `e430b9a`,
  `parameterize_docker` `98335cc`.

  The `upstream` remote (`anselor/ankermake-m5-protocol`) is the archive for all
  of it. Do not delete branches there — it is not our repository.
- The post-PR-#20 `main` workflow built and published
  `ghcr.io/bigminer/ankermake-m5-protocol:latest`, but its final legacy Release
  step failed because it accepts semantic-version tag refs and was incorrectly
  invoked for `refs/heads/main`. This is a CI release-condition defect, not a
  code, test, secret-sweep, or container-build failure.

## Current printer state

- An attended thermal/fan validation ran on 2026-07-26. The operator confirmed
  presence, clear bed and toolhead path, and immediately accessible power before
  any live command. Final read-only state after the run: state 0, nozzle
  31.00C/target 0, bed 30.24C/target 0.
- **The printer is gated.** `ANKERCTL_ACTION_VALIDATION_MODE` is `false` and
  `ANKERCTL_VALIDATED_ACTION_CONTRACTS` is absent from the LaunchAgent, so every
  named action returns `supervised_validation_required`. Verified after the run.
- The run closed issue 15's criterion 3 for both heaters using an external
  calibrated thermometer, which supplied the human observation the M5C's missing
  numeric display had made impossible. The request-by-request ledger is in
  [`documentation/printer-findings.md`](documentation/printer-findings.md); the
  criteria table is in the
  [issue 15 thread](https://github.com/bigminer/ankermake-m5-protocol/issues/15).
- There is no active printer action. Operator presence alone is not clearance
  for motion, heating, fan, print, pause/resume, or stop. Before any such action,
  obtain fresh confirmation that the bed and toolhead path are clear, the
  filament path is safe when relevant, and physical power is immediately
  accessible.

The worktree contains local user state that must not be modified, staged, or
committed without explicit instruction:

- `.env` is **tracked** and locally modified. The only divergence is
  `FLASK_HOST`: the committed default is `127.0.0.1` and this machine binds
  elsewhere. It will show as dirty in every session — that is expected, and it
  must never be staged.
- `.playwright-mcp/` is a browser artifact directory, now git-ignored.

The Chrony PID-file repair and its documentation were committed in `261f8ce`.
Do not stage `.env` or `.playwright-mcp/`.

The project previously completed the issue #7 server-owned snapshot foundation
and the issue #8/#11 named Stop/Pause/Resume action path. Those three
implementation issues are closed. That action path remains disabled by default
and still needs supervised live validation in #9 and #16.

An attended follow-up found and fixed two additional preflight gaps: normalized
state omitted the real 1000/subType 1 `value`, and PPPP file transfer did not
check its one-byte acknowledgement result. Synthetic no-motion uploads received
valid transfer acknowledgements but never became active jobs, so no named
Pause/Resume/Stop action was sent. Final state was idle with both targets zero;
the local validation-mode setting was returned to `false`.

## Running a supervised validation

Established 2026-07-26. The four remaining supervised validations (#9, #16, #17,
#18) all need this same setup.

**Do not enable validation mode by editing the LaunchAgent.** Run a temporary
instance with the variable in its process environment instead:

1. `launchctl bootout gui/$(id -u)/com.ankerctl.webserver`
2. Read the plist's `EnvironmentVariables` with `plutil -convert json`, inject
   them into `os.environ` without printing them, override
   `ANKERCTL_ACTION_VALIDATION_MODE=true`, then `exec` `ankerctl.py --insecure
   webserver run --host 127.0.0.1`
3. Run the validation
4. Kill the process, then `launchctl bootstrap gui/$(id -u) <plist>`

Why this and not the plist: **ungating dies with the process.** The persistent
configuration never leaves `false`, so an interrupted or abandoned run cannot
leave the printer ungated — the failure mode the plist approach has. Binding
loopback also keeps a temporarily ungated server off the network, where the
plist uses `0.0.0.0`. Editing a LaunchAgent is also a system-configuration
change that a coding agent should hand back to the operator rather than perform.

Verify the gate before and after: a named action must return
`supervised_validation_required` outside the run.

Two conditions will otherwise waste a run. Both are detailed in
[`documentation/printer-findings.md`](documentation/printer-findings.md):

- **The M5C never publishes `state`** — only temperatures. `state` exists solely
  as a reply to `APP_QUERY_STATUS` (1027) and goes stale 15s after a poll, so a
  fan request fails its freshness gate unless status was polled immediately
  before.
- **The lazy MQTT service ages facts between short-lived connections.** Do a
  warm-up `/ws/state` read immediately before submitting any action. This
  invalidated one request on 2026-07-26 and one on 2026-07-23.

**Physical observations need an established baseline.** A fan observation taken
while the hotend is hot is not attributable, because the firmware runs its own
hotend fan above a temperature threshold. Turn the heaters off and get the
operator to confirm silence first, or the observation proves nothing.

## Session closeout and GitHub disposition

There is no active monitoring, validation, or printer action to resume
automatically.

| Issue | Final session disposition |
| --- | --- |
| #5 — original Home/Pause/Stop incident | Already closed as not planned; received a final comment pointing to the replacement issue tree and the 2026-07-20 failure evidence |
| #6 — deep Printer-action module | Open parent; updated with the completed slices, safe-suite result, invalid synthetic fixture, and paused status |
| #7 — server-owned Printer snapshot | Closed completed |
| #8 — Protective Stop tracer bullet | Closed completed for offline implementation; #9 retains live validation |
| #9 — supervised Protective Stop | Open; synthetic attempt was invalid and no Stop was sent |
| #10 — thermal and fan action migration | **Closed completed**; merged in PR #21 |
| #11 — Pause/Resume migration | Closed completed for offline implementation; #16 retains live validation |
| #15 — supervised thermal/fan validation | Open, but only two items remain — see below |
| #16 — supervised Pause/Resume | Open; synthetic attempt was invalid and neither action was sent |

No claim is made that the whole parent design is complete.

### Issue 15 — what is left

Criterion 3 is met for nozzle and bed. Two items remain:

1. **Criterion 7 is now reachable but not done.** Add to the LaunchAgent's
   `EnvironmentVariables`, then unload/load:
   `ANKERCTL_VALIDATED_ACTION_CONTRACTS="nozzle_target=m5c-nozzle-target-v1,bed_target=m5c-bed-target-v1,heater_off=m5c-heater-off-v1"`
   That enables exactly the three actions with successful evidence and leaves
   everything else gated. Issue 15 can close once this is set.
2. **`fan_setting` — the copy is fixed; enabling it is now an operator step.**
   See below.

#### The `fan_setting` decision — settled 2026-07-27

**Decided: soften the copy first, then enable.** The copy half is done. The
enable half is an operator step — add `fan_setting=m5c-fan-setting-v1` to
`ANKERCTL_VALIDATED_ACTION_CONTRACTS` alongside the three thermal contracts.
No code is owed for it; the contract already exists in `printer_actions.py`.

`renderActionOutcome` in `static/ankersrv.js` now gives
`fan_setting`/`confirmation_unavailable` its own informational `text-info` line
instead of `text-danger` "could not be confirmed". The other two ways a fan
request can reach `indeterminate` — `protocol_submission_uncertain` and
`server_restarted_before_confirmation` — keep the failure styling, because those
are real failures; a browser test covers both directions.

Two things about that change worth carrying forward:

- **The branch is gated on the action as well as the reason, deliberately.**
  Today `confirmation_unavailable` is emitted only for `fan_setting`, so the
  action check is redundant on paper. It is an allowlist, not defensive coding:
  a future unconfirmable action has no supervised evidence behind it and should
  read as an alarm until it does.
- **`confirmation_unavailable` conflates two different unknowns.** A fan request
  resolves that way when the deadline passes, regardless of whether the command
  ever reached the printer — `confirmed` is hardcoded `False` for `fan_setting`.
  A silently disconnected printer, the documented 2026-07-19 failure mode,
  resolves identically to a working one. The copy therefore stops short of
  naming the telemetry gap as the cause. Separating the two unknowns properly
  would need the `unconfirmable` status rejected below, so it stays open — worth
  revisiting when #19 contracts the legacy path.

The reasoning behind the decision is kept below, because the obvious-looking
answer is probably wrong and that is easy to lose.

**The mechanic.** The M5C publishes no fan-state fact, so a fan action has
nothing to confirm against. It is accepted, `M106`/`M107` is sent, and 30
seconds later it resolves `indeterminate/confirmation_unavailable`. That is not
a bug and no fixture can fix it — it is a permanent property of the protocol.

**The tension.** The action works. On 2026-07-26 the operator heard the fan
start at 50% and stop at 0%, from a verified-silent baseline, and both requests
resolved `indeterminate`. So the *only* thing normal use would add is a UI that
reports failure-shaped uncertainty every single time the fan is commanded, for
an action that is in fact working perfectly.

**Why that matters more than it looks.** `renderActionOutcome` in
`static/ankersrv.js` styles `indeterminate` as `text-danger` and prints "could
not be confirmed: confirmation_unavailable". Every fan press would produce a red
message. That is precisely the alarm-fatigue failure the Stop-supersession fix
in `367346a` was made to avoid: a warning that fires when nothing is wrong
teaches the operator to ignore warnings that fire when something is. Enabling
`fan_setting` as it stands would reintroduce that pattern, in the same UI, weeks
after removing it.

**The options, roughly in order of preference.**

- **Soften the copy first, then enable.** ← **chosen, and the copy half is
  done.** Give `fan_setting` its own `indeterminate` string, styled as
  information rather than danger. This is the one change that makes the outcome
  honest *and* accurate: the request genuinely did what it could, and nothing is
  wrong. Originally raised as finding 5 in the #21 review — which lived in a
  session's review output and was never posted to GitHub, so it is not
  recoverable there.
- **Add a distinct outcome status** (`unconfirmable`, say) separate from
  `indeterminate`, so the server distinguishes "we could not confirm this" from
  "this class of action is never confirmable". Cleaner semantically, but it
  widens the action contract and touches every consumer.
- **Enable as-is and accept the red text.** Fastest, and the option that trains
  operators to discount warnings. Not recommended.
- **Leave it gated indefinitely.** The legacy browser path still drives the fan
  when validation mode is off, so nothing is lost operationally today. The cost
  is that #19 (contract the legacy path) can never fully land while one control
  still depends on that path.

**What is not in question:** the fan action's server-side behavior is correct
and validated, including Protective fan-off under stale state. This is entirely
a question of how the outcome is presented.

### Issue 14 — implemented offline, awaiting validation

Contract `m5c-print-start-v1`, gated. The action order, policy, and cleanup
rules are documented in the "`print_start` Compound action order" section of
[`documentation/printer-test-validation.md`](documentation/printer-test-validation.md);
issue [#18](https://github.com/bigminer/ankermake-m5-protocol/issues/18) is the
supervised validation that would ungate it.

Two things a reviewer should know:

- **Both upload routes still take the legacy path while the action is gated**,
  which is every deployment today. Nothing about normal printing changed. The
  named path only engages under validation mode or a matching contract.
- **The named path returns to the slicer on acceptance, not on transfer.**
  That is the intended acceptance/confirmation split, but it means a slicer no
  longer learns about a transfer failure from its own HTTP response — only the
  browser, which watches the action stream, sees the outcome. Worth deciding
  before #19 contracts the legacy path away.

🚨 **`G36` is still not honored by production firmware, and the mitigation
previously recorded here does not work.** This paragraph used to say a supervised
run should validate the unprepared path first with `ANKERCTL_PREPRINT_G36`
`false`. **That variable does not reach the named action.** `web/util.py:232`
gates the *legacy* pre-print routine on it; `printer_actions.py:512` calls
`prepare_bed` — which sends `G36` then `M400` — whenever the artifact carries a
bed temperature, with no such check. Setting the variable false changes nothing
about what `print_start` sends.

`G36` has never produced leveling motion or a completion `ok` across three
supervised sessions, so `prepare_bed` waits for something that never arrives and
preparation times out. The ledger's older "wedges the command queue, needs a
power cycle" wording is **contested** — one early experiment recorded it, the two
supervised 2026-07-09 sessions did not reproduce it.

**`G36` also appears to be the wrong command.** The OrcaSlicer Anker M5C profile,
behind every successful print, starts `M4899 T3` → `M104 S150` → `M190` → `M109`
→ **`G28 ;Home`**. Our preparation matches the first three steps and substitutes
`G36` for `G28`. The working flow never sends `G36`, and `M4899` is a real Anker
opcode we never send at all.

**Tracked as [#25](https://github.com/bigminer/ankermake-m5-protocol/issues/25);
do not run #18 until it is resolved.** See finding D1 in
[`documentation/audit-2026-07-27.md`](documentation/audit-2026-07-27.md).

### Next implementation work

**Re-planned 2026-07-28 after the audit.** The three issues below are new, need
no printer, and should come before any further validation. Everything learned in
the last two days came from reading published source; the live test run in the
same period answered a question one grep answers.

| Issue | Why it is first |
| --- | --- |
| [#27](https://github.com/bigminer/ankermake-m5-protocol/issues/27) — homing from firmware source | Oldest problem, the one with physical consequences, and the standing "arming lives in the comm module" explanation now has firmware evidence against it. Read-only. **An outcome of "omit Home permanently" is welcome.** |
| [#26](https://github.com/bigminer/ankermake-m5-protocol/issues/26) — map the control layer to source | Re-grounds the ledger. Its firmware section read two of three config files, so any row may be wrong |
| [#25](https://github.com/bigminer/ankermake-m5-protocol/issues/25) — fix the ungated `G36` | Blocks #18. Offline |

Status of the rest:

- **#12 (bounded jog) — now `needs-triage`, not `ready-for-agent`.** It read as
  actionable because its only listed blocker (#8) is closed, while the real
  blocker sat only in this file. `FACT_PATHS` has no position fact; `M114`
  reports planner space, so nothing can confirm physical motion; and
  `NO_MOTION_BEFORE_HOMING` means X/Y refuse to move at all until homed. The
  contract needs designing first.
- **#13 — now `needs-triage`** too: blocked by #12, and its live-Z effects are
  invisible to `M114` by design, so every outcome falls in the unobservable
  branch.
- **#6 user story 7 needs revision** — it promises confirmation backed by
  physical behaviour, which is achievable for thermal, impossible for jog and
  live Z, and unknown for fan.
- **#15** — the three thermal contracts are still one operator env-var line from
  closing. The fan half is reopened pending the 1005 question.
- **#17 has two criteria that cannot pass** as written; revise them with #12/#13
  rather than discovering it mid-run.
- #19 is blocked by #9, #15, #16, #17, #18. #9 and #16 remain `ready-for-human`
  and still need the operator and the validation setup described above.

## Mandatory safety rules

Read `AGENTS.md` and `CLAUDE.md` before acting.

Never send a command that moves, heats, starts, pauses, resumes, or stops the
physical printer without fresh confirmation that the operator is at the
printer with a safe toolhead path and immediate access to the power switch.
Read-only telemetry is allowed.

Do not put secrets or personal setup values in tracked files, tool output,
commits, PRs, or issues. In particular, do not print the full LaunchAgent
configuration: it contains authentication material. Run
`./scripts/check-secrets.sh` before every stage, commit, or push.

## Session history

Dated incident and validation narratives are **not** kept here. They live in the
canonical ledgers, which grade every claim by confidence:

- [`documentation/printer-findings.md`](documentation/printer-findings.md) —
  what we know about this printer and how much to trust it. Covers the
  2026-07-19 observation gap, the 2026-07-20 same-room recovery and live-print
  retest, homing (including the containment commit trail), and every named-action
  validation run through 2026-07-26.
- [`documentation/printer-test-validation.md`](documentation/printer-test-validation.md)
  — test gates, the live-test procedure, the homing and print-control incidents,
  and the PRINT_CONTROL pause/resume/stop contract.
- The broad local-control and web-dashboard effort merged through
  [PR #20](https://github.com/bigminer/ankermake-m5-protocol/pull/20).

Keep this file about **current state and what to do next**. When a session
produces a finding, put it in the ledger and leave a pointer here.

## Standing constraints

These outlive any one session. The parent design is
[issue #6](https://github.com/bigminer/ankermake-m5-protocol/issues/6).

- **Home stays disabled**, both in the UI and at the `/ws/ctrl` rejection. Do not
  re-enable it from a command or value guess. Before any standalone homing
  design, capture a complete known-good official print-start/calibration flow
  including the state that arms the nozzle probe, and reconcile it against the
  published firmware. Accept that production firmware may not expose safe
  standalone Home at all — if so, omit the feature permanently.
- **Never add Pause/Resume identity fields to Stop.** Pause and Resume require
  the exact server-recorded upload identity; Stop is always global and
  identity-free. Conflating them caused the 2026-07-13 regression.
- **#9 still has an unsolved fixture problem.** It forbids homing and unrelated
  motion, but synthetic zero-motion files never become active jobs, so there is
  nothing to Stop. Do not substitute a normal sliced print without a separate
  safety review or an explicit revision of that validation contract.
- **#16 needs a separately authorized, known-safe real print** and the exact
  server-recorded upload identity.
- **Actions are enabled per-action, never wholesale.** Use
  `ANKERCTL_VALIDATED_ACTION_CONTRACTS` for actions whose supervised validation
  succeeded. `ANKERCTL_ACTION_VALIDATION_MODE` ungates everything at once and is
  only for an attended run.

## Useful commands

Safe, non-live test suite:

```sh
PYTHONPATH=. .venv/bin/pytest -q -m 'not live_printer'
```

Secret and diff checks:

```sh
./scripts/check-secrets.sh
git diff --check
```

Local read-only service check:

```sh
curl -fsS http://127.0.0.1:4470/api/version
```

Do not run live-printer tests merely because their environment flags are
available. The operator confirmation in the current session is mandatory.
