#!/usr/bin/env bash
set -euo pipefail

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die 'run with sudo'
SERVICE_USER=${SUDO_USER:-}
[[ -n $SERVICE_USER && $SERVICE_USER != root ]] || die 'run from the service owner account with sudo'
SERVICE_HOME=$(getent passwd "$SERVICE_USER" | cut -d: -f6)
[[ -n $SERVICE_HOME && -d $SERVICE_HOME ]] || die 'could not find the service user home'

: "${M5C_AP_INTERFACE:?set M5C_AP_INTERFACE}"
AP_CONNECTION=${M5C_AP_CONNECTION:-m5c-local-linux}
M5C_AP_SSID=${M5C_AP_SSID:-$(nmcli -g 802-11-wireless.ssid connection show "$AP_CONNECTION" 2>/dev/null || true)}
M5C_AP_PSK=${M5C_AP_PSK:-$(nmcli --show-secrets -g 802-11-wireless-security.psk connection show "$AP_CONNECTION" 2>/dev/null || true)}
: "${M5C_AP_SSID:?set M5C_AP_SSID or provide an existing AP profile}"
: "${M5C_AP_PSK:?set M5C_AP_PSK or provide an existing AP profile}"
[[ $M5C_AP_PSK =~ ^.{8,63}$ ]] || die 'WPA2 passphrase must be 8–63 characters'
[[ $M5C_AP_INTERFACE =~ ^[[:alnum:]_.:-]+$ ]] || die 'invalid interface name'

AP_ADDRESS=${M5C_AP_ADDRESS:-10.77.0.1}
AP_SUBNET=${M5C_AP_SUBNET:-10.77.0.0/24}
DHCP_START=${M5C_DHCP_START:-10.77.0.10}
DHCP_END=${M5C_DHCP_END:-10.77.0.50}
PRINTER_ADDRESS=${M5C_PRINTER_ADDRESS:-10.77.0.21}
UPLINK_INTERFACE=${M5C_UPLINK_INTERFACE:-$(ip -4 route show default | awk 'NR==1 {print $5}')}
REPO_DIR=$(cd "$(dirname "$0")/../../.." && pwd)
VENV_PYTHON=${M5C_VENV_PYTHON:-$SERVICE_HOME/.local/share/ankerctl/venv/bin/python}
CONFIG_FILE=$SERVICE_HOME/.config/ankerctl/default.json
[[ -f $CONFIG_FILE ]] || die "missing owner config: $CONFIG_FILE"
[[ -x $VENV_PYTHON ]] || die "missing executable venv Python: $VENV_PYTHON"
command -v nmcli >/dev/null || die 'NetworkManager nmcli is required'
command -v ufw >/dev/null || die 'UFW is required'
command -v nft >/dev/null || die 'nftables is required for optional cloud mode'
for pkg in dnsmasq mosquitto chronyd openssl; do command -v "$pkg" >/dev/null || die "missing required executable: $pkg"; done
[[ -e /sys/class/net/$M5C_AP_INTERFACE ]] || die "interface does not exist: $M5C_AP_INTERFACE"
[[ -n $UPLINK_INTERFACE && $UPLINK_INTERFACE != "$M5C_AP_INTERFACE" && -e /sys/class/net/$UPLINK_INTERFACE ]] || die 'a separate wired uplink interface is required'
if [[ -z ${M5C_PRINTER_MAC:-} ]]; then
  M5C_PRINTER_MAC=$(ip neigh show to "$PRINTER_ADDRESS" dev "$M5C_AP_INTERFACE" | awk 'NR==1 {print $5}')
fi
if [[ -z ${M5C_PRINTER_MAC:-} && -r /run/m5c-ap-test/dnsmasq.leases ]]; then
  M5C_PRINTER_MAC=$(awk -v ip="$PRINTER_ADDRESS" '$3 == ip {print $2; exit}' /run/m5c-ap-test/dnsmasq.leases)
fi
if [[ -z ${M5C_PRINTER_MAC:-} && -r /var/lib/m5c-local/dnsmasq.leases ]]; then
  M5C_PRINTER_MAC=$(awk -v ip="$PRINTER_ADDRESS" '$3 == ip {print $2; exit}' /var/lib/m5c-local/dnsmasq.leases)
fi
[[ ${M5C_PRINTER_MAC:-} =~ ^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$ ]] || die 'printer MAC not found; set M5C_PRINTER_MAC or connect the printer first'

install -d -m 0750 /etc/m5c-local /etc/m5c-local/dhcp-hosts.d /etc/m5c-local/certs
chown root:mosquitto /etc/m5c-local
chmod 0755 /etc/m5c-local
install -d -o root -g dnsmasq -m 0750 /etc/m5c-local/dhcp-hosts.d
install -d -o mosquitto -g mosquitto -m 0750 /etc/m5c-local/certs
install -d -m 0755 /var/lib/m5c-local
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 "$SERVICE_HOME/.config/ankerctl"

render() {
  sed -e "s|@AP_INTERFACE@|$M5C_AP_INTERFACE|g" \
      -e "s|@AP_ADDRESS@|$AP_ADDRESS|g" \
      -e "s|@AP_SUBNET@|$AP_SUBNET|g" \
      -e "s|@DHCP_START@|$DHCP_START|g" \
      -e "s|@DHCP_END@|$DHCP_END|g" "$1" > "$2"
}
render "$REPO_DIR/deploy/local-broker/linux/dnsmasq.conf" /etc/m5c-local/dnsmasq.conf
render "$REPO_DIR/deploy/local-broker/linux/mosquitto.conf" /etc/m5c-local/mosquitto.conf
render "$REPO_DIR/deploy/local-broker/linux/chrony.conf" /etc/m5c-local/chrony.conf
render "$REPO_DIR/deploy/local-broker/linux/mode-local.conf" /etc/m5c-local/mode-local.conf
install -m 0644 /etc/m5c-local/mode-local.conf /etc/m5c-local/mode.conf
{
  printf 'AP_INTERFACE=%q\nUPLINK_INTERFACE=%q\nAP_ADDRESS=%q\nAP_SUBNET=%q\n' \
    "$M5C_AP_INTERFACE" "$UPLINK_INTERFACE" "$AP_ADDRESS" "$AP_SUBNET"
  printf 'PRINTER_ADDRESS=%q\nAP_CONNECTION=%q\nSERVICE_USER=%q\nSERVICE_HOME=%q\n' \
    "$PRINTER_ADDRESS" "$AP_CONNECTION" "$SERVICE_USER" "$SERVICE_HOME"
  printf 'REPO_DIR=%q\nVENV_PYTHON=%q\n' "$REPO_DIR" "$VENV_PYTHON"
} > /etc/m5c-local/network.conf
chmod 0644 /etc/m5c-local/{dnsmasq.conf,mosquitto.conf,chrony.conf,mode-local.conf,mode.conf,network.conf}
install -D -m 0755 "$REPO_DIR/deploy/local-broker/linux/m5c-cloud-mode" /usr/local/libexec/m5c-cloud-mode
printf '%s,%s,%s\n' "$M5C_PRINTER_MAC" "$PRINTER_ADDRESS" m5c-printer > /etc/m5c-local/dhcp-hosts.d/printer.conf
chown root:dnsmasq /etc/m5c-local/dhcp-hosts.d/printer.conf
chmod 0640 /etc/m5c-local/dhcp-hosts.d/printer.conf

# The temporary proof daemons own the same ports as the persistent services.
# Stop only processes whose command line points at our temporary configs.
stop_temporary() {
  local pidfile=$1 expected=$2 pid args
  [[ -r $pidfile ]] || return 0
  read -r pid < "$pidfile" || return 0
  [[ $pid =~ ^[0-9]+$ ]] || return 0
  args=$(ps -p "$pid" -o args= 2>/dev/null || true)
  [[ $args == *"$expected"* ]] || return 0
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
  kill -KILL "$pid" 2>/dev/null || true
}
stop_temporary /run/m5c-ap-test/dnsmasq.pid /tmp/m5c-ap-test.dnsmasq.conf
stop_temporary /run/m5c-local/chrony/chronyd.pid /tmp/m5c-local-chrony.conf
# Mosquitto's temporary daemon was started with -d and has no pid file.
while read -r pid; do
  [[ $pid =~ ^[0-9]+$ ]] || continue
  args=$(ps -p "$pid" -o args= 2>/dev/null || true)
  [[ $args == *'/tmp/m5c-local-mosquitto.conf'* ]] && kill "$pid" 2>/dev/null || true
done < <(pgrep -x mosquitto || true)

# Reuse the existing temporary AP profile, keeping the same SSID/passphrase.
if nmcli -t -f NAME connection show | grep -Fxq "$AP_CONNECTION"; then
  nmcli connection modify "$AP_CONNECTION" \
    connection.interface-name "$M5C_AP_INTERFACE" connection.autoconnect yes \
    connection.autoconnect-priority 100 connection.permissions "" \
    802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 1 \
    802-11-wireless.ssid "$M5C_AP_SSID" 802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "$M5C_AP_PSK" ipv4.method manual \
    ipv4.addresses "$AP_ADDRESS/24" ipv4.never-default yes ipv4.dns "$AP_ADDRESS" \
    ipv4.dns-search '~ankermake.com' ipv4.ignore-auto-dns yes ipv6.method disabled
else
  nmcli connection add type wifi ifname "$M5C_AP_INTERFACE" con-name "$AP_CONNECTION" \
    ssid "$M5C_AP_SSID" 802-11-wireless.mode ap 802-11-wireless.band bg \
    802-11-wireless.channel 1 802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "$M5C_AP_PSK" ipv4.method manual \
    ipv4.addresses "$AP_ADDRESS/24" ipv4.never-default yes ipv4.dns "$AP_ADDRESS" \
    ipv4.dns-search '~ankermake.com' ipv4.ignore-auto-dns yes ipv6.method disabled \
    connection.autoconnect yes connection.autoconnect-priority 100
fi

if [[ ! -s /etc/m5c-local/certs/server.crt || ! -s /etc/m5c-local/certs/server.key ]]; then
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1825 \
    -keyout /etc/m5c-local/certs/server.key -out /etc/m5c-local/certs/server.crt \
    -subj '/CN=make-mqtt.ankermake.com' \
    -addext "subjectAltName=DNS:make-mqtt.ankermake.com,DNS:make-mqtt-eu.ankermake.com,IP:$AP_ADDRESS" \
    >/dev/null 2>&1
fi
chown mosquitto:mosquitto /etc/m5c-local/certs/server.{crt,key}
chmod 0644 /etc/m5c-local/certs/server.crt
chmod 0600 /etc/m5c-local/certs/server.key

SERVICE_ENV=$SERVICE_HOME/.config/ankerctl/service.env
if [[ ! -e $SERVICE_ENV ]]; then
  umask 077
  printf '%s=%s\n%s=%s\n%s=%s\n' \
    'ANKERCTL_TOKEN' "$(openssl rand -hex 32)" \
    'ANKERCTL_SLICER_TOKEN' "$(openssl rand -hex 32)" \
    'ANKERCTL_SECRET_KEY' "$(openssl rand -hex 32)" > "$SERVICE_ENV"
  chown "$SERVICE_USER:$SERVICE_USER" "$SERVICE_ENV"
fi
chmod 0600 "$SERVICE_ENV"

for unit in "$REPO_DIR"/deploy/local-broker/linux/systemd/*.service; do
  sed -e "s|@SERVICE_USER@|$SERVICE_USER|g" \
      -e "s|@REPO_DIR@|$REPO_DIR|g" \
      -e "s|@SERVICE_HOME@|$SERVICE_HOME|g" \
      -e "s|@VENV_PYTHON@|$VENV_PYTHON|g" \
      -e "s|@AP_INTERFACE@|$M5C_AP_INTERFACE|g" \
      -e "s|@AP_ADDRESS@|$AP_ADDRESS|g" "$unit" > "/etc/systemd/system/$(basename "$unit")"
done

# Network isolation: only DHCP, local DNS/NTP/MQTT on the AP; web UI via Tailscale.
ufw allow in on "$M5C_AP_INTERFACE" to "$AP_ADDRESS" port 67 proto udp comment 'M5C DHCP'
ufw allow in on "$M5C_AP_INTERFACE" from "$AP_SUBNET" to "$AP_ADDRESS" port 53 proto udp comment 'M5C DNS UDP'
ufw allow in on "$M5C_AP_INTERFACE" from "$AP_SUBNET" to "$AP_ADDRESS" port 53 proto tcp comment 'M5C DNS TCP'
ufw allow in on "$M5C_AP_INTERFACE" from "$AP_SUBNET" to "$AP_ADDRESS" port 8789 proto tcp comment 'M5C MQTT'
ufw allow in on "$M5C_AP_INTERFACE" from "$AP_SUBNET" to "$AP_ADDRESS" port 123 proto udp comment 'M5C NTP'
ufw allow in on tailscale0 to any port 4470 proto tcp comment 'ankerctl via Tailscale' || true
printf 'net.ipv4.ip_forward=0\nnet.ipv6.conf.all.forwarding=0\n' > /etc/sysctl.d/90-m5c-local.conf
chmod 0644 /etc/sysctl.d/90-m5c-local.conf
sysctl -q -w net.ipv4.ip_forward=0 net.ipv6.conf.all.forwarding=0

systemctl daemon-reload
systemctl enable NetworkManager.service m5c-ap-ready.service m5c-local-dnsmasq.service \
  m5c-local-chronyd.service m5c-local-mosquitto.service ankerctl.service
nmcli connection up "$AP_CONNECTION" || true
systemctl restart m5c-ap-ready.service
systemctl restart m5c-local-dnsmasq.service m5c-local-chronyd.service m5c-local-mosquitto.service
systemctl restart ankerctl.service || die 'ankerctl failed to start; inspect journalctl -u ankerctl'

printf 'Installed. Check: systemctl --no-pager --full status m5c-ap-ready m5c-local-dnsmasq m5c-local-chronyd m5c-local-mosquitto ankerctl\n'
printf 'Web UI: http://<host-tailscale-ip>:4470 (token in %s)\n' "$SERVICE_ENV"
