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

- `main` and `origin/main` are synchronized at the merge of
  [`bigminer/ankermake-m5-protocol#20`](https://github.com/bigminer/ankermake-m5-protocol/pull/20).
  PR #20 joined the prior checkpoint-merge ancestry with the remaining
  `local-control` commits. The fully merged local and remote `local-control`
  branches were then deleted.
- Working branch: `main`, at `df6f971`. No open pull requests. Three merged on
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
- Checks on `main`: 105 offline tests pass with 8 skipped; 27 browser tests
  pass; `git diff --check` and the secret sweep pass.
- Origin branch cleanup removed `local-control`, `master`,
  `exiles-1.1-rebased`, `pyinstaller`, and `treitmayr_mqtt-commands` after
  verifying they were merged or had no unique patch content. The remaining
  legacy branches were retained because they still contain unique commits.
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

- `.env` is modified and contains local configuration.
- `.playwright-mcp/` is an untracked user/browser artifact directory.

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
2. **`fan_setting` is deliberately excluded, pending a decision.** It can never
   reach `confirmed`, because the M5C publishes no fan-state fact: every request
   resolves `indeterminate/confirmation_unavailable`, which the UI renders as a
   warning. Physical operation is proven. Whether an action that always reports
   uncertainty is acceptable for normal use is a product decision, not a
   technical gap.

### Next implementation work

Dependency edges verified 2026-07-26:

- **#14 (upload, preparation, print start) — unblocked**, and it became unblocked
  when #10 closed. Its confirmation contract is already supported: `print.name`,
  `print.origin`, `print.user_name`, `state`, and `print.progress` are all in
  `FACT_PATHS` and all published. This is the recommended next slice.
- **#12 (bounded jog) — unblocked but not ready to implement.** `FACT_PATHS` in
  `web/printer_snapshot.py` has no position facts, and position is poll-only
  (`M114`) — the same class of problem as `state`, except motion is where this
  printer has twice driven its nozzle into the plate. There is nothing for a jog
  action to confirm against, so the contract needs designing before any
  implementation begins.
- #13 is blocked by #12. #19 is blocked by #9, #15, and #16.
- #9, #16, #17, and #18 are `ready-for-human`: they need the operator at the
  printer and the validation setup described above.

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
