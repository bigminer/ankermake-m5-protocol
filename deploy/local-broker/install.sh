#!/bin/sh
# Install the AnkerMake M5C local-broker stack as boot-persistent LaunchDaemons.
# Idempotent: re-running updates configs and reloads the daemons; an existing
# broker certificate is kept.
#
# NOTE: loading these daemons activates the redirect — the printer's MQTT is
# re-pointed at the local broker and its Anker cloud paths are dropped. Run this
# with the operator present at the printer (see README.md).
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run with sudo: sudo ./install.sh" >&2; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX=/opt/ankerm5c

# Locate mosquitto/dnsmasq/openssl so the plists' paths are valid on this Mac.
MOSQ=$(command -v mosquitto || echo /opt/homebrew/sbin/mosquitto)
DNSMASQ=$(command -v dnsmasq || echo /opt/homebrew/sbin/dnsmasq)
CHRONYD=$(command -v chronyd || echo /opt/homebrew/sbin/chronyd)
[ -x "$MOSQ" ]    || { echo "mosquitto not found (brew install mosquitto)" >&2; exit 1; }
[ -x "$DNSMASQ" ] || { echo "dnsmasq not found (brew install dnsmasq)" >&2; exit 1; }
[ -x "$CHRONYD" ] || { echo "chronyd not found (brew install chrony)" >&2; exit 1; }

mkdir -p "$PREFIX/certs" "$PREFIX/pf" "$PREFIX/logs"

install -m 0644 "$SRC/mosquitto.conf" "$PREFIX/mosquitto.conf"
install -m 0644 "$SRC/dnsmasq.conf"   "$PREFIX/dnsmasq.conf"
install -m 0644 "$SRC/chrony.conf"    "$PREFIX/chrony.conf"
install -m 0644 "$SRC/pf/anker_dns"   "$PREFIX/pf/anker_dns"
install -m 0644 "$SRC/pf/anker_block" "$PREFIX/pf/anker_block"
install -m 0755 "$SRC/pf-loader.sh"   "$PREFIX/pf-loader.sh"

# Self-signed broker cert (only generate if missing so the printer keeps
# trusting the same cert across reinstalls).
if [ ! -f "$PREFIX/certs/server.crt" ]; then
    echo "generating self-signed broker cert (CN=make-mqtt.ankermake.com)"
    CNF=$(mktemp)
    cat > "$CNF" <<'EOF'
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = make-mqtt.ankermake.com
[v3]
subjectAltName = DNS:make-mqtt.ankermake.com,DNS:make-mqtt-eu.ankermake.com,IP:192.168.2.1
EOF
    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$PREFIX/certs/server.key" \
        -out "$PREFIX/certs/server.crt" \
        -days 3650 -config "$CNF"
    rm -f "$CNF"
    chmod 0600 "$PREFIX/certs/server.key"
    chmod 0644 "$PREFIX/certs/server.crt"
fi

# Install and (re)load the LaunchDaemons.
for p in com.ankerm5c.mosquitto com.ankerm5c.dnsmasq com.ankerm5c.chrony com.ankerm5c.pf-loader; do
    install -m 0644 "$SRC/launchd/$p.plist" "/Library/LaunchDaemons/$p.plist"
    launchctl bootout system "/Library/LaunchDaemons/$p.plist" 2>/dev/null || true
    launchctl bootstrap system "/Library/LaunchDaemons/$p.plist"
done

echo "installed. verify with: sudo $SRC/verify.sh"
