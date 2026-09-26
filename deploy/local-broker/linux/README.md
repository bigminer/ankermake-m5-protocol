# Linux M5C hotspot and local broker

This is the Linux counterpart to the macOS stack in the parent directory. It
uses NetworkManager for the printer-only access point, dnsmasq for DHCP/DNS,
chrony for local time, Mosquitto for MQTT, and systemd for persistence.

Keep the host's uplink on Ethernet and use a dedicated Wi-Fi interface for the
printer AP. The default **local mode** omits a router option, uses isolated DNS,
keeps IPv4 forwarding off, and blocks Anker cloud names.

The live Linux setup has already demonstrated the local path: the M5C joined
the AP, received a reserved DHCP lease, synchronized to local NTP, and
published telemetry to Mosquitto. `ankerctl` decoded that telemetry using the
owner-only config copied from the previous host.

## Install

Install `dnsmasq`, `mosquitto`, and `chrony` (and `openssl`, `ufw`, `nftables`),
then set the AP interface before running the installer. It reuses the active
`m5c-local-linux` NetworkManager profile's SSID and key and reserves the
printer's current `.21` DHCP lease automatically. Set `M5C_AP_SSID`,
`M5C_AP_PSK`, or `M5C_PRINTER_MAC` only if those values cannot be discovered
from the existing profile and lease:

```sh
export M5C_AP_INTERFACE=wlp0s12f0
sudo --preserve-env=M5C_AP_INTERFACE,M5C_AP_SSID,M5C_AP_PSK,M5C_PRINTER_MAC \
  ./deploy/local-broker/linux/install.sh
```

The printer MAC and AP passphrase are written only to NetworkManager and
`/etc/m5c-local`; never commit them. Copy the existing
`~/.config/ankerctl/default.json` securely from the previous host before
installing. Its mode must be 0600.

The installer creates a web token, slicer token, and Flask signing key in
`~/.config/ankerctl/service.env` (mode 0600). The web UI listens on port 4470;
UFW allows it only through `tailscale0`. Token values remain in that file.

## Services

```sh
systemctl status m5c-ap-ready m5c-local-dnsmasq m5c-local-chronyd \
  m5c-local-mosquitto ankerctl
journalctl -u m5c-local-dnsmasq -u m5c-local-chronyd \
  -u m5c-local-mosquitto -f
```

In local mode, `ankerctl` uses `--insecure` only for the self-signed broker on
this private AP. Cloud mode removes that option and verifies Anker's broker
using the bundled CA. Printer actions remain gated by default; do not enable
action validation mode as part of installation.

## Switch between local and cloud

The eufyMake app controls the printer through Anker's cloud MQTT. The repo's
capture found that `ankerctl` can connect to the same cloud broker concurrently,
so the app and local web UI can both work in cloud mode. Cloud mode gives only
the reserved printer address a routed/NATed path through Ethernet, forwards its
DNS to Ethernet resolvers, and runs `ankerctl` with the bundled cloud CA. The
local broker remains installed but does not receive the printer's cloud MQTT
traffic in this mode.

```sh
sudo /usr/local/libexec/m5c-cloud-mode cloud  # enable Anker cloud access
sudo /usr/local/libexec/m5c-cloud-mode local  # restore isolated local broker
sudo /usr/local/libexec/m5c-cloud-mode status
```

The selected mode persists across reboot. Cloud mode gives the printer general
IPv4 egress, including any Anker firmware/update endpoints; local mode restores
the no-gateway, no-forwarding policy. Switching modes briefly restarts the
printer AP so it receives the correct DHCP gateway setting.
