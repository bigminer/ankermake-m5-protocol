# Project Instructions

## Before diagnosing the printer

- **Read [`documentation/printer-findings.md`](documentation/printer-findings.md) first**
  — it records what we know, what failed, and which conclusions were retracted.
  Append what you learn, with a status. Don't delete refuted entries.

- **If the printer seems dead, restart `ankerctl` before diagnosing anything else.**
  `launchctl kickstart -k gui/$(id -u)/com.ankerctl.webserver`

  Why: its service threads wedge and keep reporting `Running` while receiving
  nothing. On 2026-07-15 this cost an hour chasing pf, dnsmasq, and mosquitto —
  all healthy. The printer was publishing to the broker the entire time. Check
  `/opt/ankerm5c/logs/mosquitto.out.log` to see what the printer is *actually*
  doing; ankerctl's status API only reports its own threads, not the printer.

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

## Agent skills

### Issue tracker

Issues and PRDs are tracked as GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default five-label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses the single-context layout. See `docs/agents/domain.md`.
