#!/bin/sh
# Read-only health check for the M5C local-broker stack. Run with sudo so the
# pf-anchor checks can read the ruleset. Exit non-zero if any layer is down.
# This is the cold-boot verification: after a reboot, `sudo ./verify.sh` should
# report every line ok with nothing else touched.
FAIL=0
ok()  { printf "  ok   %s\n" "$1"; }
bad() { printf "  FAIL %s\n" "$1"; FAIL=1; }

echo "LaunchDaemons:"
for l in com.ankerm5c.mosquitto com.ankerm5c.dnsmasq com.ankerm5c.chrony com.ankerm5c.pf-loader; do
    if launchctl print "system/$l" >/dev/null 2>&1; then ok "$l loaded"; else bad "$l not loaded"; fi
done

echo "Listeners:"
lsof -nP -iTCP:8789 -sTCP:LISTEN >/dev/null 2>&1 && ok "mosquitto listening :8789" || bad "mosquitto :8789 down"
lsof -nP -iUDP:5354 >/dev/null 2>&1              && ok "dnsmasq listening :5354"  || bad "dnsmasq :5354 down"
lsof -nP -iUDP:123 2>/dev/null | grep -q chronyd && ok "chrony serving NTP :123"   || bad "chrony :123 down"

echo "Internet Sharing:"
ifconfig bridge100 2>/dev/null | grep -q 'inet 192.168.2.1' \
    && ok "bridge100 = 192.168.2.1" || bad "bridge100 down — Internet Sharing off"

echo "pf sub-anchors:"
DNS_NAT=$(pfctl -a com.apple/anker_dns -s nat 2>/dev/null)
echo "$DNS_NAT" | grep -q 'port = 53'  && ok "anker_dns DNS rdr loaded"  || bad "anker_dns DNS rdr not loaded"
echo "$DNS_NAT" | grep -q 'port = 123' && ok "anker_dns NTP rdr loaded"  || bad "anker_dns NTP rdr not loaded"
pfctl -a com.apple/anker_block -s rules 2>/dev/null | grep -q 'block drop .* to any' \
    && ok "anker_block default-deny egress loaded" || bad "anker_block egress not loaded"

echo "DNS answer (via local dnsmasq):"
ANS=$(dig +short -p 5354 @127.0.0.1 make-mqtt.ankermake.com 2>/dev/null)
[ "$ANS" = "192.168.2.1" ] && ok "make-mqtt.ankermake.com -> 192.168.2.1" || bad "make-mqtt resolved to '${ANS:-<none>}'"
for h in make-app.ankermake.com www.anker.com ota.eufylife.com; do
    B=$(dig +short -p 5354 @127.0.0.1 "$h" 2>/dev/null)
    [ "$B" = "0.0.0.0" ] && ok "blackholed: $h -> 0.0.0.0" || bad "$h not blackholed (-> '${B:-<none>}')"
done

echo
[ "$FAIL" -eq 0 ] && echo "ALL OK" || echo "SOME CHECKS FAILED"
exit "$FAIL"
