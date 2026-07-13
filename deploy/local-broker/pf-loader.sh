#!/bin/sh
# Load the Anker pf sub-anchors once Internet Sharing's bridge100 is up.
# Run at boot by com.ankerm5c.pf-loader. The sub-anchors live under the stock
# "com.apple/*" anchors, so they are evaluated alongside Internet Sharing's NAT
# instead of flushing it. Never `pfctl -f` the main ruleset here.
set -u
PFCTL=/sbin/pfctl
ANCHOR_DIR=/opt/ankerm5c/pf

# Internet Sharing creates bridge100 (192.168.2.1) asynchronously at boot.
# Wait up to ~120s for it before loading rules that reference it.
i=0
while [ "$i" -lt 60 ]; do
    if /sbin/ifconfig bridge100 2>/dev/null | /usr/bin/grep -q 'inet 192.168.2.1'; then
        break
    fi
    sleep 2
    i=$((i + 1))
done

if ! /sbin/ifconfig bridge100 2>/dev/null | /usr/bin/grep -q 'inet 192.168.2.1'; then
    echo "pf-loader: bridge100/192.168.2.1 not up after wait — is Internet Sharing on?" >&2
    exit 1
fi

# Internet Sharing enables pf; make sure it is on before loading the anchors.
$PFCTL -s info 2>/dev/null | /usr/bin/grep -q 'Status: Enabled' || $PFCTL -e 2>&1

$PFCTL -a com.apple/anker_dns   -f "$ANCHOR_DIR/anker_dns"   2>&1
$PFCTL -a com.apple/anker_block -f "$ANCHOR_DIR/anker_block" 2>&1
echo "pf-loader: loaded anker_dns + anker_block sub-anchors"
