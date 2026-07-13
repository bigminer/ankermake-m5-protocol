import logging as log
import re
import time
from threading import Lock

from flask import flash, redirect, request

import cli.mqtt
from libflagship.mqtt import MqttMsgType


_PREPRINT_LOCK = Lock()
_GCODE_COMMAND = MqttMsgType.ZZ_MQTT_CMD_GCODE_COMMAND.value
_NOZZLE_TEMPERATURE = MqttMsgType.ZZ_MQTT_CMD_NOZZLE_TEMP.value
_BED_TEMPERATURE = MqttMsgType.ZZ_MQTT_CMD_HOTBED_TEMP.value
# Limits derived from the M5C (V8110) Marlin firmware Configuration.h:
# BED_MAXTEMP 125 / HEATER_0_MAXTEMP 325, minus Marlin's standard
# BED_OVERSHOOT (10) / HOTEND_OVERSHOOT (15) target clamps.
_TEMPERATURE_LIMITS = {
    "M190": (1, 115),
    "M109": (150, 310),
}


def flash_redirect(path: str, message: str | None = None, category="info"):
    """
    Flashes a message and redirects the user to the specified path.

    Args:
        - path (str): A string representing the path to redirect the user to.
        - message (str | None): An optional string message to flash to the user.
        - category (str): A string representing the category of the flashed message. 
            Possible values are "info" (default), "danger", "warning", "success".

    Raises:
        - ValueError: If the path parameter is not provided.

    Returns:
        - A Flask redirect object.
    """
    if not path:
        raise ValueError("Redirect path is required")

    if message:
        flash(message, category)

    return redirect(path)


def extract_preprint_temperatures(data: bytes) -> tuple[int, int]:
    """Extract the resolved first-layer bed and nozzle temperatures."""
    text = data[:256 * 1024].decode("utf-8", errors="ignore")
    temperatures = {}

    for command, limits in _TEMPERATURE_LIMITS.items():
        match = re.search(
            rf"(?im)^\s*{command}\b[^\r\n;]*?\b[SR]\s*(-?\d+(?:\.\d+)?)",
            text,
        )
        if not match:
            raise ValueError(f"Pre-print hook could not find {command} temperature")

        value = round(float(match.group(1)))
        if not limits[0] <= value <= limits[1]:
            raise ValueError(
                f"Pre-print hook rejected unsafe {command} temperature: {value}C"
            )
        temperatures[command] = value

    return temperatures["M190"], temperatures["M109"]


def extract_preprint_temperatures_from_file(file) -> tuple[int, int]:
    """Inspect the G-code preamble and leave the upload ready to transfer."""
    data = file.read(256 * 1024)
    file.seek(0)
    return extract_preprint_temperatures(data)


def _send_gcode(client, command: str, timeout: int) -> dict:
    def send(value):
        client.command({
            "commandType": _GCODE_COMMAND,
            "cmdData": value,
            "cmdLen": len(value),
        })

    log.info("Pre-print hook: sending %s", command)
    send(command)
    # G-code commands first receive an "echo:busy" reply. M400 is queued
    # behind the command and supplies the terminal "ok" only after all prior
    # heating and motion have completed.
    send("M400")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        for _, body in client.fetch(timeout=min(1, remaining)):
            for reply in body:
                if reply.get("commandType") != _GCODE_COMMAND:
                    continue

                response = str(reply.get("resData", ""))
                lowered = response.lower()
                if any(
                    marker in lowered
                    for marker in ("error", "unknown", "failed")
                ):
                    raise RuntimeError(
                        f"Pre-print command failed ({command}): {response}"
                    )
                if reply.get("reply") == 0 and "ok" in lowered:
                    return reply

    raise TimeoutError(f"Timed out waiting for pre-print command: {command}")


def _cool_down(client):
    for command in ("M104 S0", "M140 S0"):
        try:
            _send_gcode(client, command, timeout=10)
        except Exception:
            log.exception("Pre-print hook: failed to send emergency cooldown command")


def _wait_for_temperature(client, command_type, target, tolerance, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        for _, body in client.fetch(timeout=min(1, remaining)):
            for message in body:
                if message.get("commandType") != command_type:
                    continue
                current = float(message["currentTemp"]) / 100
                if current >= target - tolerance:
                    log.info(
                        "Pre-print hook: temperature reached %.1fC / %dC",
                        current,
                        target,
                    )
                    return

    raise TimeoutError(f"Timed out waiting for temperature: {target}C")


def _disconnect_mqtt(client):
    try:
        client.disconnect()
    except Exception:
        log.exception("Pre-print hook: failed to disconnect MQTT client")


def _run_preprint_upload(app, upload, user_name, bed_temp, nozzle_temp):
    client = None
    try:
        client = cli.mqtt.mqtt_open(
            app.config["config"],
            app.config["printer_index"],
            app.config["insecure"],
        )

        timeout = int(app.config.get("preprint_command_timeout", 300))
        _send_gcode(client, "M104 S150", timeout=30)
        _send_gcode(client, f"M140 S{bed_temp}", timeout=30)
        _wait_for_temperature(
            client,
            _BED_TEMPERATURE,
            bed_temp,
            tolerance=0.5,
            timeout=timeout,
        )
        _send_gcode(client, f"M104 S{nozzle_temp}", timeout=30)
        _wait_for_temperature(
            client,
            _NOZZLE_TEMPERATURE,
            nozzle_temp,
            tolerance=1,
            timeout=timeout,
        )
        _send_gcode(client, "G36", timeout=timeout)

        with app.svc.borrow("filetransfer") as filetransfer:
            filetransfer.send_file(upload, user_name)
        log.info("Pre-print hook: completed routine and uploaded %r", upload.filename)
    except Exception:
        log.exception("Pre-print hook: failed for %r", upload.filename)
        if client is not None:
            _cool_down(client)
        raise
    finally:
        if client is not None:
            _disconnect_mqtt(client)


def upload_file_to_printer(app, file):
    """ This function uploads a file to the printer.

    Args:
        - app (object): The application object.
        - file (file-like object): The file to be uploaded to the printer.
    """
    user_name = request.headers.get("User-Agent", "ankerctl").split("/")[0]

    if app.config.get("preprint_g36"):
        bed_temp, nozzle_temp = extract_preprint_temperatures_from_file(file)
        if not _PREPRINT_LOCK.acquire(blocking=False):
            raise ConnectionError("A pre-print routine is already running")

        try:
            _run_preprint_upload(app, file, user_name, bed_temp, nozzle_temp)
        finally:
            _PREPRINT_LOCK.release()
        return

    with app.svc.borrow("filetransfer") as ft:
        ft.send_file(file, user_name)
