# Project status audit — 2026-09-04

## Executive summary

The project is **functionally useful but not finished**. The local-broker stack,
slicer upload/start path, dashboard, normalized telemetry, and local print/monitor
workflow have all been implemented and exercised. The remaining product gap is
trustworthy control: several controls still lack an honest confirmation contract,
some use raw G-code instead of the printer's native application opcode, and the
named-action layer remains deliberately gated pending supervised validation.
This is the same broad conclusion as the canonical index, which says the
cloud-free goal is "largely true" but issue #6 remains unfinished
([INDEX §7](INDEX.md#7-distance-to-the-goal),
[#6](https://github.com/bigminer/ankermake-m5-protocol/issues/6)).

Development has paused rather than reached a release boundary. The latest push
was commit [`0595a83`](https://github.com/bigminer/ankermake-m5-protocol/commit/0595a83b4a0004db5642ac9d6f8e0e000f421c83)
on 2026-08-01, 34 days before this audit. There are no tags, GitHub releases,
milestones, deployments, open pull requests, wiki, or Discussions. Source:
read-only `gh repo view`, `gh api`, `gh pr list`, and `git tag --list` queries on
2026-09-04.

The most important status problem is **documentation and tracker drift**. The
repository has a strong evidence hierarchy and automated consistency checks, but
multiple current-looking documents still repeat claims that the index itself has
refuted. The GitHub issue comments are often newer than their bodies, labels, and
blocker lists. Until these are reconciled, use this order of authority:

1. primary captures or pinned first-party firmware source;
2. [`INDEX.md`](INDEX.md), except for the specific discrepancies below;
3. the latest GitHub issue comments;
4. long-form research, handoff, and runbook prose only after cross-checking.

That ordering follows the repository's own evidence policy
([CLAUDE.md](../CLAUDE.md), [method.md §2](method.md#2-source-hierarchy)).

## Repository and delivery status

- Local `main` and `origin/main` are both at `0595a83`; the fork is 108 commits
  ahead of `upstream/main` and zero behind. The upstream tip remains its
  2024-11-14 commit
  [`88131a5`](https://github.com/anselor/ankermake-m5-protocol/commit/88131a559fdd43105f16fb7d464e662b678cda19).
  Source: `git rev-list --left-right --count main...origin/main`, the equivalent
  upstream query, and the GitHub commits API.
- The repository has 903 commits total. The focused fork-development wave was
  108 commits from 2026-07-06 through 2026-08-01. It delivered the local broker,
  normalized state, server-owned action/snapshot architecture, safety gates,
  print-start migration, protocol/firmware research, primary captures, and docs
  consistency tooling. Source: `git rev-list`, `git log --since=2026-07-01`, and
  the linked closed work below.
- The latest HEAD ran four successful GitHub workflows: Tests, Docs consistency,
  Secret sweep, and Docker Image CI
  ([workflow run](https://github.com/bigminer/ankermake-m5-protocol/actions/runs/30709739442)).
  The release-trigger defect was also closed in
  [#31](https://github.com/bigminer/ankermake-m5-protocol/issues/31), but no
  semantic-version tag has since exercised the release path.
- A fresh local non-printer run passed **178/178 selected tests**; 8 live-printer
  tests were excluded. Collection currently contains 30 browser tests. Both
  `python scripts/check-docs.py` and `./scripts/check-secrets.sh` passed. Source:
  those commands run from this checkout on 2026-09-04.
- The README's raw `pyflakes` command exits nonzero with 13 style/unused-code
  findings. CI intentionally fails only on "undefined name," so this does not
  contradict the green workflow but does mean the README command is not a clean
  local gate ([tests workflow](../.github/workflows/tests.yml)).
- The working tree was already dirty before this report: `.env`,
  `static/ankersrv.js`, `static/tabs/control.html`, and
  `tests/test_browser_ui.py` were modified (194 insertions, 12 deletions). The
  non-`.env` diff is local UI/test work that heats a cold nozzle before filament
  movement. It is not on GitHub and should not be counted as shipped completion
  of [#13](https://github.com/bigminer/ankermake-m5-protocol/issues/13). This
  audit did not inspect or reproduce `.env` contents. Source: `git status
  --short`, `git diff --stat`, and the non-secret code diff.

## GitHub issue and PR landscape

The tracker has **24 issues: 16 open and 8 closed**. Open issue labels are 7
`ready-for-human`, 5 `needs-triage`, and 4 `ready-for-agent`. There have been 9
pull requests, all merged; the latest was
[#24](https://github.com/bigminer/ankermake-m5-protocol/pull/24) on 2026-07-26.
Later work landed as direct commits to `main`. Source: `gh issue list` and `gh pr
list` on 2026-09-04.

### Practical priority chain

1. **Clarify the parent contract.** [#6](https://github.com/bigminer/ankermake-m5-protocol/issues/6)
   remains the umbrella. Its confirmation vocabulary promises more than jog and
   live-Z telemetry can prove; thermal outcomes are measurable, fan outcomes can
   become measurable through the native opcode, while jog can at best prove
   accepted/queued/drained. The same gap is recorded in
   [INDEX §7](INDEX.md#7-distance-to-the-goal).
2. **Do the high-leverage operator-assisted capture.** [#28](https://github.com/bigminer/ankermake-m5-protocol/issues/28)
   is the main research bottleneck. Capturing the official app can establish the
   unknown fan, jog, homing/leveling, and job-start payloads without guessing.
   It directly unblocks [#29](https://github.com/bigminer/ankermake-m5-protocol/issues/29)
   and informs #12 and #27.
3. **Take the safe offline fixes.** [#30](https://github.com/bigminer/ankermake-m5-protocol/issues/30)
   is unblocked: per-fact freshness is needed because on-change facts can be
   accurate while marked stale. [#33](https://github.com/bigminer/ankermake-m5-protocol/issues/33)
   has useful offline capture/design work around `+ringbuf`, although its final
   acceptance criterion needs a supervised jog and is therefore not wholly
   agent-only.
4. **Re-specify motion work before implementing it.** [#12](https://github.com/bigminer/ankermake-m5-protocol/issues/12),
   [#13](https://github.com/bigminer/ankermake-m5-protocol/issues/13), and
   [#17](https://github.com/bigminer/ankermake-m5-protocol/issues/17) remain
   underspecified. X/Y jogs are inhibited until homed, `M114` cannot prove
   physical motion, and live-Z is invisible to it
   ([jog research](jog-confirmation-research.md)).
5. **Resolve human-gated validation.** The outstanding supervised backlog is
   [#9 Stop](https://github.com/bigminer/ankermake-m5-protocol/issues/9),
   [#15 thermal/fan](https://github.com/bigminer/ankermake-m5-protocol/issues/15),
   [#16 Pause/Resume](https://github.com/bigminer/ankermake-m5-protocol/issues/16),
   #17 motion, and [#18 upload/start](https://github.com/bigminer/ankermake-m5-protocol/issues/18).
   [#19](https://github.com/bigminer/ankermake-m5-protocol/issues/19) is the
   legacy-browser finish line and should remain blocked until those contracts
   settle.
6. **Treat the motion-profile divergence as an explicit product decision.**
   [#32](https://github.com/bigminer/ankermake-m5-protocol/issues/32) records that
   the firmware boots in an older motion profile and that `M503` replies are
   lossy. The remaining EEPROM/behavior comparison needs serial/app evidence and
   possibly supervised printing; it is not a quick offline fix.

Completed milestones include the server-owned snapshot/action foundations
([#7](https://github.com/bigminer/ankermake-m5-protocol/issues/7),
[#8](https://github.com/bigminer/ankermake-m5-protocol/issues/8)), thermal/fan and
print-start migrations
([#10](https://github.com/bigminer/ankermake-m5-protocol/issues/10),
[#14](https://github.com/bigminer/ankermake-m5-protocol/issues/14)), Pause/Resume
migration ([#11](https://github.com/bigminer/ankermake-m5-protocol/issues/11)),
and the first-party control-layer map
([#26](https://github.com/bigminer/ankermake-m5-protocol/issues/26)).

### Tracker drift

- `INDEX.md` still calls #25 an "ungated G36" defect and says it blocks #18
  ([INDEX lines 184-185](INDEX.md#L184-L185)). That conflicts with the index's
  own trigger row, [#25's correction](https://github.com/bigminer/ankermake-m5-protocol/issues/25#issuecomment-5110443788),
  and [#18's latest status](https://github.com/bigminer/ankermake-m5-protocol/issues/18#issuecomment-5110443895):
  the gate works, #25 is now about a duplicative opt-in `G36`, and #18 is blocked
  only by #15.
- #27 is labelled `ready-for-agent`, but later source work already answered its
  source-tracing portion; the remaining probe discriminator needs serial or
  official-app evidence. #19 is also labelled `ready-for-agent` despite its
  explicit validation dependencies
  ([#27](https://github.com/bigminer/ankermake-m5-protocol/issues/27),
  [#19](https://github.com/bigminer/ankermake-m5-protocol/issues/19)).
- The issue bodies for #9, #12, #15, and #16 retain closed or superseded blocker
  lists; their later comments describe the real state. #25 retains void original
  acceptance criteria, and #32's source-work checklist remains unchecked despite
  later answers in comments. Source: each issue's body and comments, audited
  read-only on 2026-09-04.

## Documentation audit

All 30 tracked Markdown files were reviewed. The strongest current sources are
`CLAUDE.md`, `AGENTS.md`, `CONTEXT.md`, the three ADRs, `docs/agents/*`, the
local-broker deployment README, and—despite the exceptions below—the index and
capture README. The index's evidence hierarchy, stable fact IDs, refuted-claim
ledger, and verify commands are a sound foundation
([INDEX §2-§3](INDEX.md#2-evidence-rule),
[INDEX §10](INDEX.md#10-keeping-this-true)).

### High-priority inconsistencies

1. **`G36` status is still wrong in user-facing and canonical prose.** The
   [README](../README.md#L31-L37) says production firmware never honored it, and
   later says the enabled hook levels the printer
   ([README](../README.md#L122-L126)). The top command table in
   [printer-findings.md](printer-findings.md#L70-L78) and portions of
   [printer-test-validation.md](printer-test-validation.md) retain similar
   conclusions. These conflict with INDEX F-010/F-011 and §6: the failed runs
   used 150°C below a 160°C gate. That correction does **not** establish the hook
   as safe; it establishes that "firmware never honors G36" was not supported.
2. **Fan telemetry corrections did not propagate.** Current code maps `1005` to
   `fan`, and `fan` is tracked in `FACT_PATHS` (INDEX F-007/F-008). Yet
   [printer-test-validation.md lines 287-350](printer-test-validation.md#L287-L350)
   says `normalize()` lacks the branch and later says fan speed has no telemetry.
   Dated sections of [printer-findings.md](printer-findings.md) and several
   comparisons in [jog-confirmation-research.md](jog-confirmation-research.md)
   repeat the obsolete claim without enough local framing. The accurate current
   statement is narrower: native fan telemetry exists, but `ankerctl`'s raw
   `M106`/`M107` path bypasses the module state needed to confirm its own action
   (INDEX F-003/F-022).
3. **The method document contradicts the completed Linux-SDK analysis.** It says
   the SDK ships Paho and therefore the upper computer uses it
   ([method.md lines 260-265](method.md#L260-L265)); INDEX F-033 and the detailed
   source audit say the selected M5C build disables all MQTT packages and the
   proprietary application is unpublished. Opcode payloads therefore still
   require official-app capture.
4. **The operations runbook has an obsolete topology and deployment snapshot.**
   [local-macos-service.md](local-macos-service.md) still diagrams Anker cloud
   MQTT at lines 27-49, describes a now-merged draft branch at lines 70-77, and
   repeats the refuted `print_start` gate claim at lines 768-771. Operational
   commands may still be useful, but the document is not a reliable current-state
   handoff.
5. **The superseded research banner is better than its body.**
   [local-control-research.md](local-control-research.md#L1-L30) correctly warns
   that its control-parity framing is wrong, but the banner itself repeats the
   obsolete "zero 1043" count, and later sections call cloud MQTT the current
   boundary, call the implemented broker redirect in progress, and retain
   completed next steps. It should be treated as experiment history, not a live
   plan.
6. **Two index/capture formulations are internally imprecise.** INDEX F-039 says
   "see F-040" for the unit's boot profile when F-041 is the relevant observation.
   INDEX F-043 and the capture README say a reply is complete "iff" it ends in
   `ok\n`, then concede this is necessary but not proven sufficient
   ([INDEX facts](INDEX.md#the-control-layer-mapped-to-tier-1-issue-26-2026-07-28),
   [capture notes](captures/README.md)).
7. **The handoff and changelog are stale.** [handoff.md](../handoff.md) is dated
   2026-07-28, lists #26 as unstarted, gives old test counts, and no longer
   describes the working tree. [CHANGELOG.md](../CHANGELOG.md) has an empty
   `Unreleased` section and stops at 1.0.1 in January 2024 despite the 108-commit
   2026 fork-development wave.

### Lower-priority documentation debt

- Four developer-doc links are broken: `documentation/developer-docs/libflagship.md`
  lines 23, 24, and 32, plus
  `example-file-usage/mqtt-connect-example-file-usage.md` line 15. The automated
  link checker checks only links in `INDEX.md`, not the full documentation tree
  ([check-docs.py](../scripts/check-docs.py)).
- The example prerequisites claim Transwarp is in `requirements.txt`, but it is
  not; the examples also fail to import `libflagship` from the documented working
  directory without setting the repository root on `PYTHONPATH`.
- `install-from-git.md` misspells `ankerctl.py` as `ankerctly.py` at line 4.
  `mqtt-overview.md` overgeneralizes telemetry as change-only and links to a
  nonexistent plural `specifications` directory. The auth-token example's
  command-line/logging advice is inconsistent with the repository's newer
  credential-hygiene posture. Sources: the cited developer documents, current
  `requirements.txt`, and [`CLAUDE.md`](../CLAUDE.md).

### Why the green docs check did not catch this

`scripts/check-docs.py` is deliberately narrow: it skips `INDEX.md` for
refuted-phrase checks, validates local links only inside that file, runs only
backticked `grep` verify commands, and checks citation presence rather than
evidence quality. Its phrase matcher also misses spelling variants such as
"honoured," while a nearby correction marker can mask a still-current-looking
sentence. The script's own comments describe this limited scope
([check-docs.py](../scripts/check-docs.py)); the successful check is therefore
useful but not proof that all documentation agrees.

## Recommended restart sequence

1. **Reconcile docs and issue metadata first, entirely offline/read-only with
   respect to the printer.** Fix INDEX #25/#18, F-039/F-041, F-043 wording, then
   propagate the G36, fan, SDK, and `1043` corrections into README, handoff,
   runbook, validation, and research docs. Refresh issue bodies/labels only after
   deciding their current scopes.
2. **Review the existing local filament-control WIP before treating it as part of
   #13.** In particular, check it against ADR-0001's validation gate and
   ADR-0003's server-owned typed-action boundary
   ([ADR-0001](../docs/adr/0001-gate-printer-actions-on-supervised-validation.md),
   [ADR-0003](../docs/adr/0003-use-a-minimal-typed-printer-action-interface.md)).
3. **Complete the genuinely offline design work:** #30, the offline portion of
   #33, and the #6 confirmation vocabulary/re-specification for #12/#13/#17.
4. **Plan one attended capture session for #28.** That is the highest-leverage
   printer-dependent step; it should establish payloads before #29 or native jog
   work is implemented. No payload should be guessed
   ([INDEX trigger table](INDEX.md#1-triggers--match-your-next-action-read-the-cell-then-proceed)).
5. **Then run narrowly scoped supervised validations** for #15, #18, #9, and
   #16, using the safety and evidence gates in
   [printer-test-validation.md](printer-test-validation.md). Only after their
   contracts settle should #19 migrate the legacy browser path.

## Audit boundary

This audit was read-only with respect to GitHub and the printer. It did not query
or operate the printer, did not run live-printer tests, and does not assert that
the July handoff's printer state remains current. It created only this report and
did not stage, commit, push, or change GitHub state.
