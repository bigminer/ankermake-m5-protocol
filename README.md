# ankerctl — AnkerMake M5/M5C without the cloud

[![Tests](https://github.com/bigminer/ankermake-m5-protocol/actions/workflows/tests.yml/badge.svg)](https://github.com/bigminer/ankermake-m5-protocol/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![License: GPLv3](https://img.shields.io/badge/license-GPLv3-green)](LICENSE)

Keep using your AnkerMake M5 or M5C with only free and open-source software:
slice in OrcaSlicer, hit print, and monitor and control the printer from a web
dashboard — no AnkerMake slicer, no mobile app, and ultimately no Anker cloud.

**Project target:** the printer and `ankerctl` communicate through a broker you
run on your local network. Anker's MQTT service is replaced, not proxied: the
printer can keep working with its cloud connection severed.

## ⚡ Highlights

**New in this fork:**

- 🏠 **Fully local MQTT is the target end state** — the proven M5C setup uses a
  Mac-hosted, printer-only Wi-Fi network, local DNS, and Mosquitto so the
  printer and `ankerctl` meet on your LAN instead of at Anker. PPPP remains the
  direct LAN path for file transfer.
- 🎛️ **Control tab** — pause/resume/stop, bounded jogs, nozzle/bed temperature
  targets, part-fan speed, and a live gcode terminal. Pause/resume use the
  printer's job-aware `PRINT_CONTROL` command; stop combines job cancellation
  with `M2024` to clear buffered motion
- 🔐 **Protected remote printing** — local slicers work without setup; remote
  slicers require a dedicated API key, as does the web UI when configured
- 📷 **External webcam support** — embed any MJPEG/WebRTC stream in the
  dashboard, giving the camera-less M5C a live view
- 📐 **Pre-print auto-leveling** — optionally preheat and run the printer's
  G36 auto-align routine before every slicer-uploaded print
- 🩺 **Hardening** — file transfers time out instead of hanging forever,
  failures reach the slicer instead of being logged and forgotten, secrets are
  stored owner-only, plus a test suite and working CI

**From the original project:**

- 🖨️ **Print directly from your slicer** — OrcaSlicer, PrusaSlicer,
  SuperSlicer and friends, via the OctoPrint-compatible upload API
- 📊 **Web dashboard** — print progress, layer, speed, temperatures, and the
  M5's built-in camera stream
- ⌨️ **CLI tools** — LAN printer discovery, file upload, interactive gcode,
  raw MQTT monitoring, camera video capture

## 🔍 Overview

`ankerctl` uses the same protocols as Anker's own software (MQTT, PPPP, HTTPS),
reverse-engineered by the
[Ankermgmt community](https://github.com/Ankermgmt/ankermake-m5-protocol)
and — since Anker/eufyMake
[published the printer's Marlin source](https://github.com/eufymake/eufyMake-Marlin-M5C) —
verified against the actual firmware. Your AnkerMake account is needed once,
to fetch the printer's connection keys; after that, the supported local-broker
configuration keeps printer control and telemetry on your network.

This is a maintained fork of
[Ankermgmt/ankermake-m5-protocol](https://github.com/Ankermgmt/ankermake-m5-protocol).

## 🏠 Local MQTT: the intended end state

The fully-local configuration replaces `make-mqtt.ankermake.com` with a local
Mosquitto broker. The printer and `ankerctl` both resolve that name to the Mac,
then exchange the existing encrypted MQTT messages locally. PPPP file transfer
continues directly to the printer over the LAN. With the printer placed behind
the Mac's Wi-Fi sharing/NAT network and Anker destinations blocked, the printer
has no functional dependency on Anker's cloud.

This has been verified on an M5C with a self-signed local broker certificate,
live telemetry, supervised bounded jogs, and an OrcaSlicer upload that
completed and started a print. It is currently a documented macOS deployment,
not a one-click cross-platform installer. See the [local-control research
and runbook](documentation/local-control-research.md) for the network design,
required `ankerctl` settings, and validation evidence.

## 🚀 Getting started

Requires **Python 3.10+** and the printer on the same network. (Prefer
containers? See the [docker install](documentation/install-from-docker.md),
Linux only.)

```sh
git clone https://github.com/bigminer/ankermake-m5-protocol.git
cd ankermake-m5-protocol
pip3 install -r requirements.txt
./ankerctl.py webserver run
```

Then open [http://localhost:4470](http://localhost:4470) and follow the setup
flow:

1. **Import your Anker account** — log in with email and password right in the
   Setup tab (captcha supported), or upload the `login.json` from an existing
   AnkerMake slicer install:
   - Windows: `%APPDATA%\AnkerMake\AnkerMake_64bit_fp\login.json`
   - macOS: `~/Library/Application Support/AnkerMake/AnkerMake_64bit_fp/login.json`
2. **Set the printer's IP** — if the dashboard warns the IP is missing, use
   **Setup → Update printer IP** with the printer powered on.

That's it — the Live tab should show your printer. Platform-specific install
walkthroughs live in [documentation/install-from-git.md](documentation/install-from-git.md).

## 🖨️ Printing from OrcaSlicer

1. On the **Prepare** screen, click the **connection icon** (📶) next to the
   printer dropdown.
2. Configure the physical printer:
   - **Host Type:** `OctoPrint`
   - **Hostname, IP or URL:** `127.0.0.1:4470` (or wherever ankerctl runs)
   - **API Key:** leave empty only for a local slicer. For a remote slicer,
     set `ANKERCTL_SLICER_TOKEN` and enter that value here.
3. Click **Test**, then **OK**.
4. Slice, then **Print plate**.

The same steps work in PrusaSlicer and SuperSlicer ("Send and Print").

> **Note**
> The printer can't store uploaded jobs, so "upload only" is not supported —
> jobs start printing as soon as the transfer completes. And with the
> pre-print hook enabled, expect a few minutes of heating and leveling before
> the first move.

## ⚙️ Configuration

All optional. Set as environment variables or in a `.env` file in the project
directory:

| Variable | Default | Effect |
| --- | --- | --- |
| `FLASK_HOST` | `127.0.0.1` | Interface to bind; `0.0.0.0` allows other devices on your network |
| `FLASK_PORT` | `4470` | Webserver port |
| `PRINTER_INDEX` | `0` | Which printer to use if your account has several |
| `ANKERCTL_TOKEN` | *(unset)* | Require this token to log in to the web UI |
| `ANKERCTL_SLICER_TOKEN` | *(unset)* | Required `X-Api-Key` for non-loopback slicer uploads; configure the same value as the slicer's API key |
| `ANKERCTL_MAX_UPLOAD_BYTES` | `536870912` | Largest accepted upload request, in bytes |
| `ANKERCTL_SECRET_KEY` | *(random)* | Stable session key so web logins survive restarts |
| `ANKERCTL_WEBCAM_URL` | *(unset)* | External webcam stream to embed (also settable in the Setup tab) |
| `ANKERCTL_PREPRINT_G36` | off | Preheat + auto-level before each slicer-uploaded print |
| `ANKERCTL_PREPRINT_COMMAND_TIMEOUT` | `300` | Seconds to wait for heating/leveling in the pre-print hook |

> **Warning**
> Remote slicer uploads are refused until `ANKERCTL_SLICER_TOKEN` is set.
> Keep the web UI on your LAN or a private network like Tailscale — do not
> expose it directly to the internet.

To run ankerctl as an always-on service, see the
[macOS launchd runbook](documentation/local-macos-service.md) (a complete
worked example with OrcaSlicer, Tailscale, and an iPad as webcam) or use
`docker compose up -d` on Linux.

## ✅ Testing

Safe local and CI tests exclude the live printer suite:

```sh
.venv/bin/python -m pytest tests/ -v -m "not live_printer"
.venv/bin/python -m pyflakes ankerctl.py cli/*.py web/*.py web/service/*.py web/lib/*.py
```

Browser tests are marked `browser` and skip if Playwright or its Chromium
runtime is not installed. Live printer tests are marked `live_printer` and are
never enabled by default. The supervised workflow and required environment
gates are documented in
[Printer test validation](documentation/printer-test-validation.md).

## ⌨️ Command line

```sh
./ankerctl.py pppp lan-search --store          # find printer on LAN, save its IP
./ankerctl.py pppp print-file boaty.gcode      # upload and print a file
./ankerctl.py mqtt gcode                       # interactive gcode prompt
./ankerctl.py mqtt monitor                     # watch printer events in realtime
./ankerctl.py config show                      # show imported account/printer info
```

Every command accepts `-h` for details.

## 📚 Learn more

- [Developer docs](documentation/developer-docs/) — protocol internals
  (`libflagship`, MQTT, PPPP)
- [Ankermgmt/ankermake-m5-research](https://github.com/Ankermgmt/ankermake-m5-research)
  — community protocol research
- Official firmware source (Marlin fork):
  [M5](https://github.com/eufymake/eufyMake-Marlin) /
  [M5C](https://github.com/eufymake/eufyMake-Marlin-M5C)

## ⚖️ Legal

This project is **not** endorsed by, affiliated with, or supported by
AnkerMake. All information comes from reverse engineering using publicly
available resources and from firmware source code published by the vendor.

Licensed under the [GNU GPLv3](LICENSE), copyright © 2023 Christian Iversen.
Some icons from [IconFinder](https://www.iconfinder.com/iconsets/3d-printing-line)
([CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)).
