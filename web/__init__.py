"""
This module is designed to implement a Flask web server for video
streaming and handling other functionalities of AnkerMake M5.
It also implements various services, routes and functions including.

Methods:
    - startup(): Registers required services on server start

Routes:
    - /ws/mqtt: Handles receiving and sending messages on the 'mqttqueue' stream service through websocket
    - /ws/pppp-state: Provides the status of the 'pppp' stream service through websocket
    - /ws/video: Handles receiving and sending messages on the 'videoqueue' stream service through websocket
    - /ws/ctrl: Handles controlling of light and video quality through websocket
    - /video: Handles the video streaming/downloading feature in the Flask app
    - /: Renders the html template for the root route, which is the homepage of the Flask app
    - /api/version: Returns the version details of api and server as dictionary
    - /api/ankerctl/config/upload: Handles the uploading of configuration file \
        to Flask server and returns a HTML redirect response
    - /api/ankerctl/server/reload: Reloads the Flask server and returns a HTML redirect response
    - /api/files/local: Handles the uploading of files to Flask server and returns a dictionary containing file details

Functions:
    - webserver(config, host, port, **kwargs): Starts the Flask webserver

Services:
    - util: Houses utility services for use in the web module
    - config: Handles configuration manipulation for ankerctl
"""
import hmac
import os
import json
import time
import logging as log

from datetime import datetime
from queue import Empty, Queue
from secrets import token_urlsafe as token
from urllib.parse import urlsplit
from flask import Flask, flash, request, render_template, Response, session, url_for, jsonify, redirect
from flask_sock import Sock
from user_agents import parse as user_agent_parse

from libflagship import ROOT_DIR

from web.lib.service import ServiceManager, RunState, ServiceStoppedError

import web.config
import web.platform
import web.util

import cli.util
import cli.config
import cli.countrycodes


app = Flask(__name__, root_path=ROOT_DIR, static_folder="static", template_folder="static")
# secret_key is required for flash() to function.
# ANKERCTL_SECRET_KEY keeps login sessions valid across restarts; otherwise a
# fresh random key is generated (and users must re-login after a restart).
app.secret_key = os.environ.get("ANKERCTL_SECRET_KEY") or token(24)
app.config.from_prefixed_env()

# Optional shared-secret access token. When set, the human web UI requires
# login; when empty, auth is disabled (preserving previous behaviour). The
# slicer/OctoPrint upload endpoints are always exempt (see _require_token).
app.config["access_token"] = os.environ.get("ANKERCTL_TOKEN", "")

# Optional external webcam stream URL (e.g. MJPEG from a phone/USB cam),
# embedded on the Control tab. Empty = hidden.
app.config["webcam_url"] = os.environ.get("ANKERCTL_WEBCAM_URL", "")

# When enabled, Orca uploads are held while ankerctl preheats the printer and
# invokes the M5C firmware's G36 preparation routine over MQTT. G36 is sent
# out-of-band because the printer rejects it when embedded in uploaded G-code.
app.config["preprint_g36"] = os.environ.get(
    "ANKERCTL_PREPRINT_G36", ""
).lower() in {"1", "true", "yes", "on"}
app.config["preprint_command_timeout"] = int(
    os.environ.get("ANKERCTL_PREPRINT_COMMAND_TIMEOUT", "300")
)

app.svc = ServiceManager()

sock = Sock(app)


# Paths always reachable without a login token: the OctoPrint upload API used
# by slicers (Orca/PrusaSlicer), version probe, the login page itself, and
# static assets needed to render it.
AUTH_EXEMPT_EXACT = {"/api/version", "/login"}
AUTH_EXEMPT_PREFIX = ("/static/", "/api/files/local")


def _auth_enabled():
    return bool(app.config.get("access_token"))


def _auth_is_valid():
    if not _auth_enabled():
        return True
    return bool(session.get("authed"))


def _auth_safe_next():
    if request.query_string:
        return request.full_path.removesuffix("?")
    return request.path


def _auth_safe_redirect_target(target):
    if not target:
        return url_for("app_root")
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/"):
        return url_for("app_root")
    return target


@app.before_request
def _require_token():
    """
    Gate the web UI behind a shared token when ANKERCTL_TOKEN is set. Slicer
    upload endpoints stay open so 'Send and Print' keeps working without auth.
    """
    required = app.config.get("access_token")
    if not required:
        return

    path = request.path
    if path in AUTH_EXEMPT_EXACT or path.startswith(AUTH_EXEMPT_PREFIX):
        return

    if _auth_is_valid():
        return

    # Websocket handshakes can't follow a redirect; reject outright.
    if path.startswith("/ws/"):
        return "Unauthorized", 401

    return redirect(url_for("app_login", next=_auth_safe_next()))


@app.route("/login", methods=["GET", "POST"])
def app_login():
    """
    Minimal token login. Sets a session cookie on success. If no token is
    configured, auth is disabled and we redirect straight to the app.
    """
    required = app.config.get("access_token")
    if not required:
        return redirect(url_for("app_root"))

    next_url = _auth_safe_redirect_target(request.values.get("next"))

    if request.method == "POST":
        if hmac.compare_digest(request.form.get("token", ""), required):
            session["authed"] = True
            return redirect(next_url)
        flash("Invalid token", "danger")

    return render_template("login.html", next_url=next_url)


# autopep8: off
import web.service.pppp
import web.service.video
import web.service.mqtt
import web.service.state
import web.service.filetransfer
# autopep8: on


PRINTERS_WITHOUT_CAMERA = ["V8110"]


CTRL_MQTT_REPLY_TIMEOUT = 10


def ctrl_send_mqtt(sock, msg):
    """
    Send an mqtt command from a websocket request. Replies are collected via
    the service's notify stream instead of the client's own await_response(),
    so the MqttQueue service thread remains the only caller of the paho
    network loop (which is not thread-safe), and messages arriving while we
    wait still reach every other subscriber.
    """
    command_type = msg["mqtt"]["commandType"]

    with app.svc.borrow("mqttqueue") as mq:
        if not msg.get("awaitResponse"):
            mq.transport.command(msg["mqtt"])
            return

        replies = Queue()
        with mq.tap(replies.put):
            mq.transport.command(msg["mqtt"])

            reply = None
            deadline = time.monotonic() + CTRL_MQTT_REPLY_TIMEOUT
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    obj = replies.get(timeout=remaining)
                except Empty:
                    break
                if obj.get("commandType") == command_type:
                    reply = obj
                    break

        sock.send(json.dumps({
            "commandType": command_type,
            "mqttReply": reply,
        }))


@sock.route("/ws/mqtt")
def mqtt(sock):
    """
    Handles receiving and sending messages on the 'mqttqueue' stream service through websocket
    """
    if not _auth_is_valid():
        return
    if not app.config["login"]:
        return
    for data in app.svc.stream("mqttqueue"):
        log.debug(f"MQTT message: {data}")
        sock.send(json.dumps(data))


@sock.route("/ws/state")
def state(sock):
    """
    Normalized printer-state stream. MQTT notices are mapped to a stable schema
    (nozzle/bed/print/speed/state) so the UI consumes named fields instead of
    parsing raw commandType messages. The raw feed remains on /ws/mqtt.
    """
    if not _auth_is_valid():
        return
    if not app.config["login"]:
        return
    for data in app.svc.stream("mqttqueue"):
        norm = web.service.state.normalize(data)
        if norm:
            sock.send(json.dumps(norm))


@sock.route("/ws/video")
def video(sock):
    """
    Handles receiving and sending messages on the 'videoqueue' stream service through websocket
    """
    if not _auth_is_valid():
        return
    if not app.config["login"] or not app.config["video_supported"]:
        return
    for msg in app.svc.stream("videoqueue"):
        sock.send(msg.data)


@sock.route("/ws/pppp-state")
def pppp_state(sock):
    """
    Handles a status request for the 'pppp' stream service through websocket
    """
    if not _auth_is_valid():
        return
    if not app.config["login"]:
        return

    pppp_connected = False

    # A timeout of 3 sec should be fine, as the printer continuously sends
    # PktAlive messages every second on an established connection.
    for chan, msg in app.svc.stream("pppp", timeout=3.0):
        if not pppp_connected:
            with app.svc.borrow("pppp") as pppp:
                if pppp.connected:
                    pppp_connected = True
                    # this is the only message ever sent on this connection
                    # to signal that the pppp connection is up
                    sock.send(json.dumps({"status": "connected"}))
                    log.info(f"PPPP connection established")
    if not pppp_connected:
        log.warning(f'[{datetime.now().strftime("%d/%b/%Y %H:%M:%S")}] PPPP connection lost, restarting PPPPService')
        try:
            app.svc.get("pppp").worker_start()
        except TimeoutError:
            app.svc.get("pppp").restart()


@sock.route("/ws/ctrl")
def ctrl(sock):
    """
    Handles controlling of light and video quality through websocket
    """
    if not _auth_is_valid():
        return
    if not app.config["login"]:
        return

    # send a response on connect, to let the client know the connection is ready
    sock.send(json.dumps({"ankerctl": 1}))

    while True:
        payload = sock.receive()
        if payload is None:
            return
        msg = json.loads(payload)

        if "mqtt" in msg:
            ctrl_send_mqtt(sock, msg)

        if "light" in msg:
            with app.svc.borrow("videoqueue") as vq:
                vq.api_light_state(msg["light"])

        if "quality" in msg:
            with app.svc.borrow("videoqueue") as vq:
                vq.api_video_mode(msg["quality"])


@app.get("/video")
def video_download():
    """
    Handles the video streaming/downloading feature in the Flask app
    """
    def generate():
        if not app.config["login"] or not app.config["video_supported"]:
            return
        # start videoqueue if it is not running
        vq = app.svc.svcs.get("videoqueue")
        if vq and vq.state == RunState.Stopped:
            try:
                vq.start()
                vq.await_ready()
            except ServiceStoppedError:
                log.error("VideoQueueService could not be started")
                return
        for msg in app.svc.stream("videoqueue"):
            yield msg.data

    return Response(generate(), mimetype="video/mp4")


@app.get("/")
def app_root():
    """
    Renders the html template for the root route, which is the homepage of the Flask app
    """
    config = app.config["config"]
    with config.open() as cfg:
        user_agent = user_agent_parse(request.headers.get("User-Agent"))
        user_os = web.platform.os_platform(user_agent.os.family)
        webcam_url = cfg.webcam_url or app.config["webcam_url"]

        if cfg:
            anker_config = str(web.config.config_show(cfg))
            config_existing_email = cfg.account.email
            printer = cfg.printers[app.config["printer_index"]]
            country = cfg.account.country
            if not printer.ip_addr:
                flash("Printer IP address is not set yet, please complete the setup...",
                      "warning")
        else:
            anker_config = "No printers found, please load your login config..."
            config_existing_email = ""
            printer = None
            country = ""

        if ":" in request.host:
            request_host, request_port = request.host.split(":", 1)
        else:
            request_host = request.host
            request_port = "80"

        return render_template(
            "index.html",
            request_host=request_host,
            request_port=request_port,
            configure=app.config["login"],
            login_file_path=web.platform.login_path(user_os),
            anker_config=anker_config,
            video_supported=app.config["video_supported"],
            config_existing_email=config_existing_email,
            country_codes=json.dumps(cli.countrycodes.country_codes),
            current_country=country,
            webcam_url=webcam_url,
            printer=printer
        )


@app.get("/api/version")
def app_api_version():
    """
    Returns the version details of api and server as dictionary

    Returns:
        A dictionary containing version details of api and server
    """
    return {"api": "0.1", "server": "1.9.0", "text": "OctoPrint 1.9.0"}


@app.post("/api/ankerctl/config/updateip")
def app_api_ankerctl_config_update_ip_addresses():
    """
    Handles the uploading of configuration file to Flask server

    Returns:
        A HTML redirect response
    """
    if request.method != "POST":
        return web.util.flash_redirect(url_for('app_root'),
                                       f"Wrong request method {request.method}", "danger")

    message = None
    category = "info"
    url = url_for("app_root")
    config = app.config["config"]
    found_printers = dict(list(cli.pppp.pppp_find_printer_ip_addresses()))

    if found_printers:
        # update printer IP addresses
        log.debug(f"Checking configured printer IP addresses:")
        updated_printers = cli.config.update_printer_ip_addresses(config, found_printers)

        # determine the message to display to the user
        if updated_printers is not None:
            if updated_printers:
                category = "success"
                message = f"Successfully update IP addresses of printer(s) {', '.join(updated_printers)}"
                url = url_for("app_api_ankerctl_server_internal_reload")
            else:
                message = f"No IP addresses were updated."
        else:
            category = "danger"
            message = f"Internal error."
    else:
        category = "danger"
        message = "No printers responded within timeout. " \
                  "Are you connected to the same network as the printer?"

    return web.util.flash_redirect(url, message, category)


@app.post("/api/ankerctl/config/upload")
def app_api_ankerctl_config_upload():
    """
    Handles the uploading of configuration file to Flask server

    Returns:
        A HTML redirect response
    """
    if request.method != "POST":
        return web.util.flash_redirect(url_for('app_root'))
    if "login_file" not in request.files:
        return web.util.flash_redirect(url_for('app_root'), "No file found", "danger")
    file = request.files["login_file"]

    try:
        web.config.config_import(file, app.config["config"])
        return web.util.flash_redirect(url_for('app_api_ankerctl_server_internal_reload'),
                                       "AnkerMake Config Imported!", "success")
    except web.config.ConfigImportError as err:
        log.exception(f"Config import failed: {err}")
        return web.util.flash_redirect(url_for('app_root'), f"Error: {err}", "danger")
    except Exception as err:
        log.exception(f"Config import failed: {err}")
        return web.util.flash_redirect(url_for('app_root'), f"Unexpected Error occurred: {err}", "danger")


@app.post("/api/ankerctl/config/webcam")
def app_api_ankerctl_config_webcam():
    with app.config["config"].modify() as cfg:
        cfg.webcam_url = request.form.get("webcam_url", "").strip()

    message = "Webcam URL saved" if cfg.webcam_url else "Webcam URL cleared"
    return web.util.flash_redirect(url_for('app_root'), message, "success")


@app.post("/api/ankerctl/config/login")
def app_api_ankerctl_config_login():
    if request.method != "POST":
        flash(f"Invalid request method '{request.method}", "danger")
        return jsonify({"redirect": url_for('app_root')})

    # get form data
    form_data = request.form.to_dict()

    for key in ["login_email", "login_password", "login_country"]:
        if key not in form_data:
            return jsonify({"error": "Error: Missing form entry '{key}'"})

    if not cli.countrycodes.code_to_country(form_data["login_country"]):
        return jsonify({"error": f"Error: Invalid country code '{form_data['login_country']}'"})

    try:
        web.config.config_login(form_data['login_email'], form_data['login_password'],
                                form_data['login_country'],
                                form_data['login_captcha_id'], form_data['login_captcha_text'],
                                app.config["config"])
        flash("AnkerMake Config Imported!", "success")
        return jsonify({"redirect": url_for('app_api_ankerctl_server_reload')})
    except web.config.ConfigImportError as err:
        if err.captcha:
            # we have to solve a capture, display it
            return jsonify({"captcha_id": err.captcha["id"],
                            "captcha_url": err.captcha["img"]})
        # unknown import error
        log.exception(f"Config import failed: {err}")
        flash(f"Error: {err}", "danger")
        return jsonify({"redirect": url_for('app_root')})
    except Exception as err:
        # unknown error
        log.exception(f"Config import failed: {err}")
        flash(f"Unexpected error occurred: {err}", "danger")
        return jsonify({"redirect": url_for('app_root')})


@app.get("/api/ankerctl/server/reload")
def app_api_ankerctl_server_reload():
    """
    Reloads the Flask server

    Returns:
        A HTML redirect response
    """
    # clear any pending flash messages
    if "_flashes" in session:
        session["_flashes"].clear()

    config = app.config["config"]

    with config.open() as cfg:
        if not cfg:
            return web.util.flash_redirect(url_for('app_root'), "No printers found in config", "warning")

    return app_api_ankerctl_server_internal_reload("Ankerctl reloaded successfully")


@app.get("/api/ankerctl/server/intreload")
def app_api_ankerctl_server_internal_reload(success_message: str=None):
    """
    Internal variant for reloading the Flask server.

    This version shall be used as the forwarding target of actions displaying
    flash messages. The current function will not clear and overwrite such
    messages.

    Returns:
        A HTML redirect response
    """
    config = app.config["config"]

    with config.open() as cfg:
        app.config["login"] = bool(cfg)
        app.config["video_supported"] = any([printer.model not in PRINTERS_WITHOUT_CAMERA for printer in cfg.printers])
        if cfg.printers and not app.svc.svcs:
            register_services(app)

    try:
        app.svc.restart_all(await_ready=False)
    except Exception as err:
        log.exception(err)
        return web.util.flash_redirect(url_for('app_root'), f"Ankerctl could not be reloaded: {err}", "danger")

    return web.util.flash_redirect(url_for('app_root'), success_message, "success")


@app.post("/api/ankerctl/file/upload")
def app_api_ankerctl_file_upload():
    if request.method != "POST":
        return web.util.flash_redirect(url_for('app_root'))
    if "gcode_file" not in request.files:
        return web.util.flash_redirect(url_for('app_root'), "No file found", "danger")
    file = request.files["gcode_file"]

    try:
        web.util.upload_file_to_printer(app, file)
        return web.util.flash_redirect(url_for('app_root'),
                                       f"File {file.filename} sent to printer!", "success")
    except ConnectionError as err:
        return web.util.flash_redirect(url_for('app_root'),
                                       "Cannot connect to printer!\n"
                                       "Please verify that printer is online, and on the same network as ankerctl.\n"
                                       f"Exception information: {err}", "danger")
    except Exception as err:
        return web.util.flash_redirect(url_for('app_root'),
                                       f"Unknown error occurred: {err}", "danger")


@app.post("/api/files/local")
def app_api_files_local():
    """
    Handles the uploading of files to Flask server

    Returns:
        A dictionary containing file details
    """
    no_act = not cli.util.parse_http_bool(request.form["print"])

    if no_act:
        cli.util.http_abort(409, "Upload-only not supported by Ankermake M5")

    fd = request.files["file"]

    try:
        web.util.upload_file_to_printer(app, fd)
    except ConnectionError as E:
        log.error(f"Connection error: {E}")
        # This message will be shown in i.e. PrusaSlicer, so attempt to
        # provide a readable explanation.
        cli.util.http_abort(
            503,
            "Cannot connect to printer!\n" \
            "\n" \
            "Please verify that printer is online, and on the same network as ankerctl.\n" \
            "\n" \
            f"Exception information: {E}"
        )

    return {}


@app.get("/api/ankerctl/status")
def app_api_ankerctl_status() -> dict:
    """
    Returns the status of the services

    Returns:
        A dictionary containing the keys 'status', possible_states and 'services'
        status = 'ok' == some service is online, 'error' == no service is online
        services = {svc_name: {online: bool, state: str, state_value: int}}
        possible_states = {state_name: state_value}
        version = {api: str, server: str, text: str}
    """
    def get_svc_status(svc):
        # NOTE: Some services might not update their state on stop, so we can't rely on it to be 100% accurate
        state = svc.state
        if state == RunState.Running:
            return {'online': True, 'state': state.name, 'state_value': state.value}
        return {'online': False, 'state': state.name, 'state_value': state.value}

    svcs_status = {svc_name: get_svc_status(svc) for svc_name, svc in app.svc.svcs.items()}

    # If any service is online, the status is 'ok'
    ok = any([svc['online'] for svc_name, svc in svcs_status.items()])

    return {
        "status": "ok" if ok else "error",
        "services": svcs_status,
        "possible_states": {state.name: state.value for state in RunState},
        "version": app_api_version(),
    }


def register_services(app):
    app.svc.register("pppp", web.service.pppp.PPPPService())
    if app.config["video_supported"]:
        app.svc.register("videoqueue", web.service.video.VideoQueue())
    app.svc.register("mqttqueue", web.service.mqtt.MqttQueue())
    app.svc.register("filetransfer", web.service.filetransfer.FileTransferService())


def webserver(config, printer_index, host, port, insecure=False, **kwargs):
    """
    Starts the Flask webserver

    Args:
        - config: A configuration object containing configuration information
        - host: A string containing host address to start the server
        - port: An integer specifying the port number of server
        - **kwargs: A dictionary containing additional configuration information

    Returns:
        - None
    """
    with config.open() as cfg:
        video_supported = False
        if cfg:
            if printer_index < len(cfg.printers):
                video_supported = cfg.printers[printer_index].model not in PRINTERS_WITHOUT_CAMERA
        else:
            if not cfg.printers:
                log.error("No printers found in config")
            else:
                log.critical(f"Printer number {printer_index} out of range, max printer number is {len(cfg.printers)-1} ")
        app.config["config"] = config
        app.config["login"] = bool(cfg)
        app.config["printer_index"] = printer_index
        app.config["video_supported"] = video_supported
        app.config["port"] = port
        app.config["host"] = host
        app.config["insecure"] = insecure
        app.config.update(kwargs)
        if cfg.printers:
            register_services(app)
        app.run(host=host, port=port)
