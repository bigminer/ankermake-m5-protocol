# M5C local-broker — boot-persistent services

This directory makes the proven fully-local M5C setup survive a reboot. It
installs four macOS **LaunchDaemons** (start at boot, no login required) that
stand up the local broker, DNS, NTP, and pf redirect/egress that replace Anker's
cloud on the LAN:

| Daemon | Does |
| --- | --- |
| `com.ankerm5c.mosquitto` | Local MQTT broker on `*:8789`, self-signed TLS (`CN=make-mqtt.ankermake.com`), anonymous. |
| `com.ankerm5c.dnsmasq` | Local DNS on `127.0.0.1:5354`: `make-mqtt(-eu).ankermake.com → 192.168.2.1`, blackholes `ankermake.com`/`eufylife.com`/`anker.com`, forwards everything else upstream. |
| `com.ankerm5c.chrony` | Local NTP server so the printer's clock stays correct offline. Runs with `-x` (serves the Mac's time, does not fight macOS `timed`); `local stratum 10` keeps it valid even when the Mac is offline. |
| `com.ankerm5c.pf-loader` | After Internet Sharing brings up `bridge100`, loads the `com.apple/anker_dns` (rdr `:53 → 5354` and `:123 → 192.168.2.1`) and `com.apple/anker_block` (default-deny printer egress) pf sub-anchors. |

Everything installs under `/opt/ankerm5c/`. The design and the evidence it is
based on are in
[../../documentation/local-control-research.md](../../documentation/local-control-research.md).
Chrony's PID file is deliberately stored under `/var/run`, not this persistent
prefix, so a pre-reboot PID cannot collide with an unrelated process after the
Mac starts again.

## How the cloud is severed (egress allowlist, not a blocklist)

Anker's cloud (`make-mqtt` / `make-app` / `www.anker.com`) is fronted by AWS
Global Accelerator, which answers from many rotating anycast IPs across AWS
ranges — an IP blocklist can't keep up. Instead, `anker_block` is a **default
deny** on the printer's egress: once fully local, everything the printer needs
(broker, DNS, NTP, PPPP file transfer) is on the Mac at `192.168.2.1`, so the
rule passes `192.168.2.2 → 192.168.2.0/24` and drops everything else off-subnet.
That is immune to IP rotation and also kills OTA and connectivity checks. The
`anker_dns` NTP redirect rewrites the printer's `:123` to the local chrony
*before* this filter runs, so time sync still works. PPPP file transfer/P2P
stays on the LAN subnet, so it is unaffected by the off-subnet block. The M5C
has no onboard camera.

## Prerequisites (already true on this Mac, verify before install)

- **Internet Sharing is on** and shares the uplink out over the printer-only
  Wi-Fi hotspot (`bridge100 = 192.168.2.1`). This is a macOS system setting that
  persists across reboot on its own; these daemons do **not** manage it.
  Check: `ifconfig bridge100 | grep 192.168.2.1`.
- `mosquitto`, `dnsmasq`, and `chrony` installed
  (`brew install mosquitto dnsmasq chrony`).
- The `ankerctl` side is already configured for the local broker: the
  `com.ankerctl.webserver` LaunchAgent runs with `--insecure`, and the cached
  `printer.ip_addr` in `default.json` is the hotspot lease `192.168.2.2`
  (see the research doc, "ankerctl integration").

## Install

Loading these daemons **activates the redirect**: the printer's MQTT is
re-pointed at the local broker and its Anker cloud paths are dropped. Do it with
the operator present at the printer (per the printer-safety rule in
`CLAUDE.md`).

```sh
cd deploy/local-broker
sudo ./install.sh
sudo ./verify.sh
```

`install.sh` is idempotent — re-run it after editing any config to reinstall and
reload. It keeps an existing broker cert so the printer keeps trusting the same
one.

## Verify a reboot (the actual durability test)

1. `sudo reboot`
2. Log back in, wait ~1–2 min for Internet Sharing + the pf-loader wait loop.
3. `cd deploy/local-broker && sudo ./verify.sh` — expect **ALL OK**.
4. Confirm the printer reconnected to the local broker with the cloud severed:
   ```sh
   tail -n 40 /opt/ankerm5c/logs/mosquitto.log   # expect the printer's CONNECT/SUBSCRIBE
   .venv/bin/python ankerctl.py --insecure mqtt monitor   # expect live temps
   ```

`verify.sh` checks every layer: the four daemons loaded, `:8789`/`:5354`/`:123`
listening, `bridge100` up, the DNS + NTP rdr and default-deny egress anchors
present, and that dnsmasq answers `make-mqtt → 192.168.2.1` while blackholing
`make-app` / `www.anker.com` / `ota.eufylife.com`.

## Uninstall

```sh
sudo ./uninstall.sh          # stop daemons, flush anchors, keep the cert
sudo ./uninstall.sh --purge  # also delete /opt/ankerm5c and the cert
```

After uninstall, a printer that is still associated with Wi-Fi is expected to
reconnect to Anker's cloud on a later DNS lookup. This is not guaranteed recovery
for a printer that has already left the hotspot; confirm association and broker
behavior instead of assuming the reconnect occurred.

## Troubleshooting

- **`verify.sh` says `bridge100 down`** — Internet Sharing is off. Turn it back
  on (System Settings → General → Sharing → Internet Sharing, share to the
  `M5C-Local` Wi-Fi). The pf-loader waits ~120s for it at boot; if sharing comes
  up later, re-run `sudo launchctl kickstart -k system/com.ankerm5c.pf-loader`.
- **anchors not loaded but bridge100 up** — check `/opt/ankerm5c/logs/pf-loader.log`.
  Re-run the loader with the `kickstart` command above. Never `sudo pfctl -f
  /etc/pf.conf` — that flushes Internet Sharing's NAT.
- **printer not connecting** — confirm on the broker log it is even reaching the
  Mac; if DNS is wrong, `dig +short -p 5354 @127.0.0.1 make-mqtt.ankermake.com`
  must return `192.168.2.1`.
- **Internet Sharing was toggled** — its restart can drop the sub-anchors;
  kickstart the pf-loader again (it is safe to run repeatedly).
