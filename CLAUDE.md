# Project Instructions

## Before diagnosing the printer

- **Read [`documentation/INDEX.md`](documentation/INDEX.md) before acting.** Its
  §1 is a trigger table: match what you are about to do, and the answer is
  probably already there. **Always read it before** grepping firmware, designing
  or changing a printer action, explaining why something cannot be confirmed,
  investigating homing or motion, or planning a live test.

  It exists because sessions repeatedly re-derived known results and revived
  refuted ones. §3 lists the specific method errors made here — including
  grepping two of the three firmware config files, and citing this repo's own
  `specification/mqtt.stf` as evidence about the printer.

  **This repo's specs, generated opcode tables, and code are not evidence about
  the printer.** They are our reverse-engineering. Only published first-party
  source, captured official-app traffic, and supervised observation are. Full
  hierarchy in [`documentation/method.md`](documentation/method.md).

  **And neither is this repo's own documentation — including `INDEX.md` and
  `printer-findings.md`.** They record evidence and current understanding, not
  fact. A fact row is a claim someone wrote down, and several have been wrong:
  F-040 was refuted by the very session that committed it. So:

  - **Never promote a doc claim to fact by citing it.** Follow it to its
    evidence — a test you can rerun, published first-party source, or a trusted
    external doc — and cite *that*. If a row has no such backing, it is a lead.
  - **Verify by testing where a test exists.** Prefer a fresh observation over a
    remembered one. When asserting a threshold or boundary, **test both sides of
    it** — F-040 generalised "under 512 bytes is safe" from the only two samples
    that sat on the boundary (INDEX A-16).
  - **A confirmed fact must link to its evidence**, so it is never relitigated:
    a capture file, a pinned source permalink (pin the commit — line numbers
    rot), or an external URL. Grade it, and say plainly when something is
    inference rather than observation.

  Detail behind the index lives in
  [`documentation/printer-findings.md`](documentation/printer-findings.md);
  primary evidence in [`documentation/captures/`](documentation/captures/).
  Append what you learn, with a status and a citation. Never delete a refuted
  entry — move it to the index's §6 with what killed it.

- **If the printer seems dead, locate the silent layer before restarting
  anything.** Check `/opt/ankerm5c/logs/mosquitto.out.log` first; `ankerctl`'s
  status API reports its own threads, not printer presence.

  - If printer PUBLISHes are current but web state is stale, restart `ankerctl`:
    `launchctl kickstart -k gui/$(id -u)/com.ankerctl.webserver`. This recovered
    the confirmed 2026-07-15 service-thread wedge.
  - If the broker logged the printer client disconnecting and PUBLISHes stopped,
    an `ankerctl` restart cannot force the remote printer back onto Wi-Fi. Check
    the hotspot neighbor/lease, signal path, and local-broker stack. This was the
    confirmed 2026-07-19 observation gap.

## Printer safety

- **Always confirm the human is present before operating the 3D printer
  directly.** "Operating directly" means any command that can cause the
  printer to move, heat, start/pause/resume/stop a job, or otherwise act
  physically — over MQTT, PPPP, serial, or the web UI. This includes live
  test suites gated on `ANKERCTL_TEST_ALLOW_*`.

  Why: these actions have real physical consequences (heat, motion, fire risk)
  and can wedge the firmware command queue, requiring a physical power cycle.

  How to apply: before issuing such a command, get explicit confirmation in the
  current session that the operator is at the printer with the bed clear and a
  safe toolhead path. Read-only observation (e.g. `ankerctl mqtt monitor`,
  capturing existing traffic) does not require this, but starting a job or
  sending motion/heat/control does.

## Repository hygiene — never commit or push secrets or personal config

- **Never stage, commit, or push secrets or setup-specific values.** This repo is
  public/shareable. Before every `git add`/`git commit`/`git push`, scan the diff
  and refuse to include:
  - **Secrets:** passwords, API keys, tokens, private keys/certs,
    `ANKERCTL_TOKEN`, `ANKERCTL_SECRET_KEY`, Anker account credentials, and the
    real config (`default.json` / `login.json`).
  - **Unique / personal config:** real printer SN and DUID, LAN or Tailscale IPs
    and hostnames, MAC addresses, `/Users/<name>` paths, personal webcam URLs.

  How to apply: use the placeholder set (e.g. `192.168.1.50`, `AK00000000000000`,
  `USPRAKM-000000-XXXXX`, `your-mac.your-tailnet.ts.net`, `/Users/you`,
  `http://127.0.0.1:4470`) in any tracked file. Real values live only in
  **`setup.local.conf`** (git-ignored); the committed template is
  **`setup.local.conf.example`**. Do not add secrets to the tracked `.env`, and
  keep its shared default `FLASK_HOST=127.0.0.1` (binding `0.0.0.0` exposes the
  web UI on all interfaces — a local-only choice, not a committed default).

  If a commit would include any of the above, stop and tell the operator instead
  of committing.

## Keep the system of record consistent

Run alongside the secret sweep, before every stage, commit, or push:

```sh
python scripts/check-docs.py
```

It fails on a refuted claim reappearing without a correction, on an
`INDEX.md` fact whose verify command no longer finds anything, and on a dead
link. **Fix the contradiction rather than widening the exclusion list.**

**Code comments count.** A comment asserting printer behaviour is a claim, and
it is the one a future session reads while editing the code it describes. When
a fact changes, grep for comments repeating the old version, and prefer citing
a fact ID (`INDEX F-003`) over restating it.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default five-label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses the single-context layout. See `docs/agents/domain.md`.
