# ankerctl — AnkerMake M5/M5C without the cloud

`ankerctl` lets you keep using an AnkerMake M5 or M5C 3D printer with only free
and open-source software: slice in OrcaSlicer (or PrusaSlicer and friends), hit
print, and monitor and control the printer from a web dashboard — no AnkerMake
slicer, no mobile app.

This is a maintained fork of
[Ankermgmt/ankermake-m5-protocol](https://github.com/Ankermgmt/ankermake-m5-protocol),
with protocol details verified against the
[M5C Marlin firmware source](https://github.com/eufymake/eufyMake-Marlin-M5C)
that Anker (now eufyMake) has since published.

![Screenshot of ankerctl](/documentation/web-interface.png "Screenshot of ankerctl web interface")

## What it makes possible

**Print from your slicer.** ankerctl speaks the OctoPrint upload API, so
OrcaSlicer, PrusaSlicer, SuperSlicer, etc. can send jobs straight to the
printer with their built-in "print host" support. See
[Printing from OrcaSlicer](#printing-from-orcaslicer) below.

**Web dashboard** at `http://localhost:4470`:

- **Live tab** — print progress, layer, speed, nozzle/bed temperatures, and
  camera stream (M5 built-in camera, or any external webcam URL for the M5C —
  e.g. an MJPEG or WebRTC feed from a phone or USB cam).
- **Control tab** — pause/resume/stop, jog and home, nozzle/bed temperature
  targets, part-fan speed, object preview, and a live gcode terminal.
  Pause/resume/stop use `M2022`/`M2023`/`M2024`, the out-of-band commands
  verified against the published M5C firmware source.
- **Print tab** — upload a gcode file from the browser.
- **Setup tab** — import your Anker account, find the printer's IP, configure
  the webcam URL, and follow slicer setup instructions.

**Optional extras:**

- **Remote access with a login token** — set `ANKERCTL_TOKEN` and the web UI
  requires a login, while slicer uploads keep working without one. Pairs well
  with [Tailscale](https://tailscale.com/) for printing from anywhere.
- **Pre-print auto-leveling** — with `ANKERCTL_PREPRINT_G36=1`, every slicer
  upload first preheats the bed and nozzle (using the temperatures from your
  sliced gcode) and runs the printer's G36 auto-align routine before the print
  starts.
- **CLI tools** — monitor raw MQTT traffic, send gcode interactively, discover
  printers on the LAN, upload files, capture camera video, and poke at the
  low-level MQTT/PPPP/HTTPS APIs.

## Requirements

- Python **3.10 or newer** (or Docker on Linux)
- The printer on the same network as the machine running ankerctl
- An AnkerMake account (used once, to fetch your printer's connection keys)

## Getting started

### 1. Install

```sh
git clone https://github.com/bigminer/ankermake-m5-protocol.git
cd ankermake-m5-protocol
pip3 install -r requirements.txt
```

Platform-specific walkthroughs: [git install](documentation/install-from-git.md)
(Windows/macOS/Linux) or [docker install](documentation/install-from-docker.md)
(Linux only).

### 2. Start the webserver

```sh
./ankerctl.py webserver run
```

Then open [http://localhost:4470](http://localhost:4470).

### 3. Import your Anker account

The printer's MQTT/PPPP keys come from your AnkerMake account. On first launch,
the web UI walks you through it — pick whichever is easier:

- **Log in with email and password** directly from the Setup tab (captcha
  supported), or
- **Upload `login.json`** from an existing AnkerMake slicer install:
  - Windows: `%APPDATA%\AnkerMake\AnkerMake_64bit_fp\login.json`
  - macOS: `~/Library/Application Support/AnkerMake/AnkerMake_64bit_fp/login.json`

The same works from the command line: `./ankerctl.py config login` or
`./ankerctl.py config import [path/to/login.json]`.

Credentials are only used against Anker's HTTPS API to fetch your printer
list and keys; the result is cached locally (with owner-only file permissions)
and everything after that is printer-to-ankerctl on your LAN.

### 4. Set the printer's IP

If the dashboard warns that the printer IP is not set, use **Setup → Update
printer IP** (or `./ankerctl.py pppp lan-search --store`) with the printer
powered on.

That's it — the Live tab should show your printer's status.

## Printing from OrcaSlicer

1. In OrcaSlicer, select your AnkerMake printer profile on the **Prepare**
   screen, then click the **connection icon** (📶) next to the printer
   dropdown.
2. Configure the physical printer:
   - **Host Type:** `OctoPrint`
   - **Hostname, IP or URL:** `127.0.0.1:4470` (or the IP/hostname of the
     machine running ankerctl)
   - **API Key:** leave empty
3. Click **Test** — you should see a success message — then **OK**.
4. Slice, then use **Print plate** (upload *and* print).

The printer cannot store uploaded jobs for later, so "upload only" is not
supported — jobs always start printing as soon as the transfer completes.
The same steps work in PrusaSlicer and SuperSlicer ("Send and Print").

> **Tip**
> If you enabled the pre-print hook (`ANKERCTL_PREPRINT_G36=1`), the job
> won't visibly start until the bed and nozzle have reached your first-layer
> temperatures and auto-leveling has finished — expect a few minutes of
> heating before motion.

## Configuration

ankerctl reads environment variables at startup (a `.env` file in the project
directory also works). Everything is optional:

| Variable | Default | Effect |
| --- | --- | --- |
| `FLASK_HOST` | `127.0.0.1` | Interface the webserver binds to. Use `0.0.0.0` to allow other devices on your network |
| `FLASK_PORT` | `4470` | Webserver port |
| `PRINTER_INDEX` | `0` | Which printer to use if your account has several |
| `ANKERCTL_TOKEN` | *(unset)* | Require this token to log in to the web UI. Slicer endpoints stay open so printing keeps working |
| `ANKERCTL_SECRET_KEY` | *(random)* | Stable session key, so web logins survive webserver restarts |
| `ANKERCTL_WEBCAM_URL` | *(unset)* | External webcam stream to embed in the dashboard (also settable in the Setup tab) |
| `ANKERCTL_PREPRINT_G36` | off | Preheat + run G36 auto-leveling before each slicer-uploaded print |
| `ANKERCTL_PREPRINT_COMMAND_TIMEOUT` | `300` | Seconds to wait for heating/leveling during the pre-print hook |

> **Warning**
> The web UI is meant for your LAN or a private network like Tailscale — don't
> expose it directly to the internet, even with a token set.

### Running as a service

To have ankerctl start automatically and stay running:

- **macOS:** see the [launchd service runbook](documentation/local-macos-service.md)
  (a complete worked example with OrcaSlicer, Tailscale remote access, and an
  iPad as webcam).
- **Linux/Docker:** `docker compose up -d` per the
  [docker install](documentation/install-from-docker.md).

## Command-line tools

```sh
./ankerctl.py webserver run                    # run the web dashboard
./ankerctl.py pppp lan-search --store          # find printer on LAN, save its IP
./ankerctl.py pppp print-file boaty.gcode      # upload and print a file
./ankerctl.py pppp capture-video -m 4mb out.h264   # capture camera video (M5)
./ankerctl.py mqtt monitor                     # watch printer events in realtime
./ankerctl.py mqtt gcode                       # interactive gcode prompt
./ankerctl.py mqtt rename-printer BoatyMcBoatFace
./ankerctl.py config show                      # show imported account/printer info
./ankerctl.py -p 1 <command>                   # select a printer by index
```

Every command accepts `-h` for details.

## Documentation

- [Developer docs](documentation/developer-docs/) — protocol internals
  (`libflagship`, MQTT, PPPP)
- [Ankermgmt/ankermake-m5-research](https://github.com/Ankermgmt/ankermake-m5-research)
  — community protocol research
- Official firmware source (Marlin fork):
  [M5](https://github.com/eufymake/eufyMake-Marlin) /
  [M5C](https://github.com/eufymake/eufyMake-Marlin-M5C)

Tests live in [`tests/`](tests/) and run with `python -m pytest tests/`.

## Legal

This project is **<u>NOT</u>** endorsed, affiliated with, or supported by
AnkerMake. All information found herein is gathered entirely from reverse
engineering using publicly available knowledge and resources, and from
firmware source code published by the vendor.

The goal of this project is to make the AnkerMake M5 and M5C usable and
accessible using only Free and Open Source Software (FOSS).

This project is [licensed under the GNU GPLv3](LICENSE), and copyright ©
2023 Christian Iversen.

Some icons from [IconFinder](https://www.iconfinder.com/iconsets/3d-printing-line),
and licensed under [Creative Commons](https://creativecommons.org/licenses/by/3.0/)
