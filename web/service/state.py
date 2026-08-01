"""Normalize raw Anker MQTT notices into a stable printer-state schema.

The UI consumes named fields (nozzle/bed/print/speed/state) from /ws/state
instead of parsing raw MQTT commandType numbers off /ws/mqtt. Numeric values keep
their raw encoding (e.g. temperatures in centi-degrees, progress scaled by 100);
value formatting stays in the client. A notice the UI does not use normalizes to
{} (and is dropped) — except a printer-state string, which may ride on any
notice and is always surfaced.
"""

_STATE_KEYS = ("state", "status", "print_state", "printState", "machineStatus", "currentStatus")


def _state_of(obj):
    for key in _STATE_KEYS:
        if key in obj:
            return str(obj[key])
    return None


def _temp(obj):
    out = {}
    if "currentTemp" in obj:
        out["current"] = obj["currentTemp"]
    if "targetTemp" in obj:
        out["target"] = obj["targetTemp"]
    return out


def normalize(obj):
    """Map one decoded MQTT notice dict to a partial normalized-state dict."""
    out = {}

    state = _state_of(obj)
    if state is not None:
        out["state"] = state

    ct = obj.get("commandType")
    if ct == 1000 and obj.get("subType") == 1:  # printer state event
        if "value" in obj:
            out["state"] = str(obj["value"])
    elif ct == 1001:  # print job status
        p = {}
        if "name" in obj:
            p["name"] = obj["name"]
        if "totalTime" in obj:
            p["elapsed"] = obj["totalTime"]
        if "time" in obj:
            # 1001's `time` is remaining MILLISECONDS, not seconds. Observed on a
            # live ~3h print 2026-08-01: it read 9_472_157 while the operator's
            # job had ~2.6h left, and the UI rendered that raw as "2631:07:34".
            # It is a live re-estimate, not a countdown -- it rises as well as
            # falls. See INDEX F-044.
            p["remaining"] = obj["time"] // 1000
        if "progress" in obj:
            p["progress"] = obj["progress"]
        if "img" in obj:
            p["img"] = obj["img"]
        if p:
            out["print"] = p
    elif ct == 1003:  # nozzle temperature
        t = _temp(obj)
        if t:
            out["nozzle"] = t
    elif ct == 1004:  # bed temperature
        t = _temp(obj)
        if t:
            out["bed"] = t
    elif ct == 1005:  # fan speed, percent
        # ZZ_MQTT_CMD_FAN_SPEED (0x3ed).  Published on *change* only, not on a
        # cadence -- observed live at 99 mid-print and 0 at completion, twice in
        # a 25-minute run.  See documentation/captures/.
        if "value" in obj:
            out["fan"] = obj["value"]
    elif ct == 1006:  # print speed
        if "value" in obj:
            out["speed"] = obj["value"]
    elif ct == 1052:  # layer progress
        out["print"] = {"layer": {"current": obj.get("real_print_layer"),
                                  "total": obj.get("total_layer")}}

    return out
