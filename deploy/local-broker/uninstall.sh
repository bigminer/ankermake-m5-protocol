#!/bin/sh
# Remove the M5C local-broker stack: stop the daemons, flush the pf sub-anchors,
# and delete the installed files. Does NOT touch Internet Sharing or the
# ankerctl service. Pass --purge to also remove the broker cert.
set -u

[ "$(id -u)" -eq 0 ] || { echo "run with sudo: sudo ./uninstall.sh" >&2; exit 1; }

for p in com.ankerm5c.mosquitto com.ankerm5c.dnsmasq com.ankerm5c.chrony com.ankerm5c.pf-loader; do
    launchctl bootout system "/Library/LaunchDaemons/$p.plist" 2>/dev/null || true
    rm -f "/Library/LaunchDaemons/$p.plist"
done

# Flush the sub-anchors so the redirect/blocks stop immediately. This clears
# only our anchors; Internet Sharing's NAT is untouched.
pfctl -a com.apple/anker_dns   -F all 2>/dev/null || true
pfctl -a com.apple/anker_block -F all 2>/dev/null || true

if [ "${1:-}" = "--purge" ]; then
    rm -rf /opt/ankerm5c
    echo "purged /opt/ankerm5c (including broker cert)"
else
    rm -f /opt/ankerm5c/mosquitto.conf /opt/ankerm5c/dnsmasq.conf /opt/ankerm5c/chrony.conf \
          /opt/ankerm5c/pf-loader.sh /opt/ankerm5c/pf/anker_dns /opt/ankerm5c/pf/anker_block
    echo "removed daemons and configs; kept /opt/ankerm5c/certs (use --purge to remove)"
fi
echo "uninstalled. The printer will reconnect to Anker cloud on its next DNS lookup."
