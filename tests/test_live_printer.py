import json
import os
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import pytest
import requests


BASE_URL = os.environ.get(
    "ANKERCTL_TEST_BASE_URL",
    "http://127.0.0.1:4470",
).rstrip("/")
FIXTURES = Path(__file__).parent / "fixtures"


def _require_flag(name):
    if os.environ.get(name) != "1":
        pytest.skip(f"set {name}=1 to run this live-printer test")


def _require_token():
    token = os.environ.get("ANKERCTL_TEST_TOKEN")
    if not token:
        pytest.skip("set ANKERCTL_TEST_TOKEN to run authenticated live tests")
    return token


def _require_safety(*items):
    checklist = {
        item.strip()
        for item in os.environ.get("ANKERCTL_TEST_SAFETY_CHECKLIST", "").split(",")
        if item.strip()
    }
    missing = [item for item in items if item not in checklist]
    if missing:
        pytest.skip(
            "set ANKERCTL_TEST_SAFETY_CHECKLIST with: "
            + ", ".join(sorted(missing))
        )


@pytest.fixture()
def live_session():
    _require_flag("ANKERCTL_TEST_ALLOW_LIVE")
    token = _require_token()

    session = requests.Session()
    response = session.post(
        urljoin(BASE_URL + "/", "login?next=/"),
        data={"token": token},
        timeout=10,
        allow_redirects=True,
    )
    response.raise_for_status()
    if b"Access token required" in response.content:
        pytest.fail("live printer login did not accept ANKERCTL_TEST_TOKEN")
    return session


def _ws_url(path):
    parts = urlsplit(BASE_URL)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


def _cookie_header(session):
    cookie = "; ".join(
        f"{item.name}={item.value}"
        for item in session.cookies
    )
    return [f"Cookie: {cookie}"] if cookie else []


def _send_gcode(session, command, await_response=True):
    websocket = pytest.importorskip("websocket")
    ws = websocket.create_connection(
        _ws_url("/ws/ctrl"),
        header=_cookie_header(session),
        timeout=10,
    )
    try:
        hello = json.loads(ws.recv())
        assert hello == {"ankerctl": 1}
        ws.send(json.dumps({
            "mqtt": {
                "commandType": 0x0413,
                "cmdData": command,
                "cmdLen": len(command),
            },
            "awaitResponse": await_response,
        }))
        if await_response:
            return json.loads(ws.recv())
        return None
    finally:
        ws.close()


@pytest.mark.live_printer
def test_live_preflight_login_redirect_and_status(live_session):
    response = requests.get(BASE_URL + "/", timeout=10, allow_redirects=False)
    assert response.status_code in {200, 302}
    if response.status_code == 302:
        assert "/login" in response.headers["Location"]

    response = live_session.get(BASE_URL + "/api/ankerctl/status", timeout=10)
    response.raise_for_status()
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["services"]
    assert "possible_states" in payload
    assert payload["version"]["server"] == "1.9.0"


@pytest.mark.live_printer
def test_live_safe_terminal_m105(live_session):
    _require_safety("operator_present")

    response = _send_gcode(live_session, "M105", await_response=True)

    assert response["commandType"] == 0x0413
    assert response["mqttReply"] is not None


@pytest.mark.live_printer
def test_live_part_fan_50_then_off(live_session):
    _require_safety("operator_present")

    _send_gcode(live_session, "M106 S128", await_response=False)
    _send_gcode(live_session, "M107", await_response=False)


@pytest.mark.live_printer
@pytest.mark.heating
def test_live_supervised_low_temperature_heat_then_cooldown(live_session):
    _require_flag("ANKERCTL_TEST_ALLOW_HEATING")
    _require_safety("operator_present", "bed_clear", "filament_safe")

    try:
        _send_gcode(live_session, "M104 S40", await_response=True)
        _send_gcode(live_session, "M140 S35", await_response=True)
    finally:
        _send_gcode(live_session, "M104 S0", await_response=False)
        _send_gcode(live_session, "M140 S0", await_response=False)


@pytest.mark.live_printer
@pytest.mark.motion
def test_live_supervised_small_jogs(live_session):
    _require_flag("ANKERCTL_TEST_ALLOW_MOTION")
    _require_safety("operator_present", "bed_clear", "safe_clearance")

    for command in (
        "G91;G1 X1 F3000;G90",
        "G91;G1 X-1 F3000;G90",
        "G91;G1 Y1 F3000;G90",
        "G91;G1 Y-1 F3000;G90",
        "G91;G1 Z1 F600;G90",
        "G91;G1 Z-1 F600;G90",
    ):
        _send_gcode(live_session, command, await_response=True)


@pytest.mark.live_printer
@pytest.mark.print_job
def test_live_upload_tiny_safe_print(live_session):
    _require_flag("ANKERCTL_TEST_ALLOW_PRINT")
    _require_safety("operator_present", "bed_clear", "filament_safe")

    with (FIXTURES / "tiny_safe.gcode").open("rb") as fixture:
        response = live_session.post(
            BASE_URL + "/api/files/local",
            data={"print": "true"},
            files={"file": ("tiny_safe.gcode", fixture, "text/x.gcode")},
            timeout=60,
        )

    response.raise_for_status()
    assert response.json() == {}


@pytest.mark.live_printer
@pytest.mark.heating
@pytest.mark.motion
@pytest.mark.print_job
@pytest.mark.g36
def test_live_supervised_g36_resolved_upload(live_session):
    _require_flag("ANKERCTL_TEST_ALLOW_HEATING")
    _require_flag("ANKERCTL_TEST_ALLOW_MOTION")
    _require_flag("ANKERCTL_TEST_ALLOW_PRINT")
    _require_flag("ANKERCTL_TEST_ALLOW_G36")
    _require_flag("ANKERCTL_TEST_CONFIRM_PREPRINT_G36_ENABLED")
    _require_safety("operator_present", "bed_clear", "filament_safe", "safe_clearance")

    with (FIXTURES / "g36_resolved.gcode").open("rb") as fixture:
        response = live_session.post(
            BASE_URL + "/api/files/local",
            data={"print": "true"},
            files={"file": ("g36_resolved.gcode", fixture, "text/x.gcode")},
            timeout=60,
        )

    response.raise_for_status()
    assert response.json() == {}


@pytest.mark.live_printer
@pytest.mark.g36
def test_live_g36_invalid_fixtures_are_rejected_before_upload(live_session):
    _require_flag("ANKERCTL_TEST_ALLOW_G36")
    _require_flag("ANKERCTL_TEST_CONFIRM_PREPRINT_G36_ENABLED")
    _require_safety("operator_present", "bed_clear", "filament_safe")

    for name in ("preprint_unresolved.gcode", "preprint_unsafe_nozzle.gcode"):
        with (FIXTURES / name).open("rb") as fixture:
            response = live_session.post(
                BASE_URL + "/api/files/local",
                data={"print": "true"},
                files={"file": (name, fixture, "text/x.gcode")},
                timeout=20,
            )
        assert response.status_code >= 400
