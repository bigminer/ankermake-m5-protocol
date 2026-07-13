# Agent instructions

This project's canonical agent guidance lives in [`CLAUDE.md`](CLAUDE.md). Any
coding agent working here (Claude Code, Codex, etc.) must follow it. The two
rules that matter most:

## 1. Printer safety
Never issue a command that moves, heats, or starts/stops the physical printer
(over MQTT, PPPP, serial, or the web UI — including `ANKERCTL_TEST_ALLOW_*` live
tests) without explicit confirmation, in the current session, that the operator
is at the printer. Read-only observation is fine. See `CLAUDE.md` for details.

## 2. Never commit or push secrets or personal config
This repo is public/shareable. Before any `git add`/`commit`/`push`, scan the
diff and refuse to include:

- **Secrets:** passwords, API keys, tokens, private keys/certs,
  `ANKERCTL_TOKEN`, `ANKERCTL_SECRET_KEY`, Anker account credentials, or the real
  config (`default.json` / `login.json`).
- **Unique / personal config:** real printer SN/DUID, LAN or Tailscale IPs and
  hostnames, MAC addresses, `/Users/<name>` paths, personal webcam URLs.

Use the placeholder set instead (`192.168.1.50`, `AK00000000000000`,
`USPRAKM-000000-XXXXX`, `your-mac.your-tailnet.ts.net`, `/Users/you`,
`http://127.0.0.1:4470`). Real values live only in the git-ignored
`setup.local.conf` (template: `setup.local.conf.example`).

`scripts/check-secrets.sh` enforces this locally and in CI
(`.github/workflows/secret-sweep.yml`) — run it before committing:

```sh
./scripts/check-secrets.sh
```
