$(function () {
    /**
     * Updates the Copywrite year on document ready
     */
    $("#copyYear").text(new Date().getFullYear());

    /**
     * Handle modal for progress bar being shown
     */
    var popupModalDom = document.getElementById("popupModal");
    var popupModalBS = new bootstrap.Modal(popupModalDom);

    popupModalDom.addEventListener("shown.bs.modal", function (e) {
        const trigger = e.relatedTarget;
        const modalInner = $("#modal-inner");
        modalInner.text(trigger.dataset.msg);
        if (trigger.dataset.href) {
            window.location.href = trigger.dataset.href;
        }
    });

    /**
     * Opens modal if gcode upload file is present
     */
    const gcodeUpload = $("#gcode-upload");
    gcodeUpload.on("click", function (event) {
        var fileInput = $("#gcode_file");
        if (fileInput.prop("value").trim() !== "") {
            const relatedTarget = {
                dataset: {
                    msg: gcodeUpload.data("msg"),
                },
            };
            popupModalBS.show(relatedTarget);
        }
    });

    /**
     * On click of an element with attribute "data-clipboard-src", updates clipboard with text from that element
     */
    if (navigator.clipboard) {
        /* Clipboard support present: link clipboard icons to source object */
        $("[data-clipboard-src]").each(function (i, elm) {
            $(elm).on("click", function () {
                const src = $(elm).attr("data-clipboard-src");
                const value = $(src).text();
                navigator.clipboard.writeText(value);
                console.log(`Copied ${value} to clipboard`);
            });
        });
    } else {
        /* Clipboard support missing: remove clipboard icons to minimize confusion */
        $("[data-clipboard-src]").remove();
    }

    /**
     * Converts a string to its boolean value.
     *
     * @function
     * @param {string} string - The string to be converted.
     * @returns {boolean} - True if the input string is "true", "yes", or "1"; otherwise, false.
     */
    function stringToBoolean(string) {
        if (!string) return false;
        switch (string.toLowerCase().trim()) {
            case "true":
            case "yes":
            case "1":
                return true;
            default:
                return false;
        }
    }

    // Get URL parameter for fullscreen and apply it if needed, this emulates fullscreen
    let urlParams = new URLSearchParams(window.location.search);
    let fullscreenParam = stringToBoolean(urlParams.get("fullscreen"));
    if (fullscreenParam) {
        setFullscreenClasses(true, true);
    }

    // Toggle fullscreen when the full screen button in the video element is clicked
    $("#video-fs").on("click", function () {
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else {
            let vp = document.getElementById("vmain");
            vp.requestFullscreen();
        }
    });

    /**
     * Sets or unsets the required classes for fullscreen functionality.
     *
     * @function
     * @param {boolean} fullscreen - Whether to set or unset the classes (true to set, false to unset).
     * @param {boolean} emulate - Whether to emulate the fullscreen mode or not.
     */
    function setFullscreenClasses(fullscreen = false, emulate = false) {
        $(".fullscreen-emulate").removeClass("fullscreen-emulate-active");
        $(".fullscreen-emulate-d-none").removeClass("fullscreen-emulate-d-none-active");
        if (fullscreen) {
            if (emulate) {
                $(".fullscreen-emulate").addClass("fullscreen-emulate-active");
                $(".fullscreen-emulate-d-none").addClass("fullscreen-emulate-d-none-active");
            }
            $("#vmain .col-xl-8").removeClass("col-xl-8").addClass("col-xl-9");
            $("#vmain .col-xl-4").removeClass("col-xl-4").addClass("col-xl-3");
        } else {
            $("#vmain .col-xl-9").removeClass("col-xl-9").addClass("col-xl-8");
            $("#vmain .col-xl-3").removeClass("col-xl-3").addClass("col-xl-4");
        }
    }

    /**
     * Event listener for fullscreen change event.
     * Adds or removes appropriate CSS classes to adjust the video element size.
     */
    document.addEventListener("fullscreenchange", function () {
        /* Make more room for video element in fullscreen mode */
        if (document.fullscreenElement) {
            setFullscreenClasses(true);
        } else {
            setFullscreenClasses(false);
        }
    });

    /**
     * Initializes bootstrap alerts and sets a timeout for when they should automatically close
     */
    $(".alert").each(function (i, alert) {
        var bsalert = new bootstrap.Alert(alert);
        setTimeout(() => {
            bsalert.close();
        }, +alert.getAttribute("data-timeout"));
    });

    /**
     * Get temperature from input
     * @param {number} temp Temperature in Celsius
     * @returns {number} Rounded temperature
     */
    function getTemp(temp) {
        return Math.round(temp / 100);
    }

    /**
     * Calculate the percentage between two numbers
     * @param {number} layer
     * @param {number} total
     * @returns {number} percentage
     */
    function getPercentage(progress) {
        return Math.round(((progress / 100) * 100) / 100);
    }

    /**
     * Convert time in seconds to hours, minutes, and seconds format
     * @param {number} totalseconds
     * @returns {string} Formatted time string
     */
    function getTime(totalseconds) {
        const hours = Math.floor(totalseconds / 3600);
        const minutes = Math.floor((totalseconds % 3600) / 60);
        const seconds = totalseconds % 60;

        const timeString =
            `${hours.toString().padStart(2, "0")}:` +
            `${minutes.toString().padStart(2, "0")}:` +
            `${seconds.toString().padStart(2, "0")}`;

        return timeString;
    }

    /**
     * Calculates the AnkerMake M5 Speed ratio ("X-factor")
     * @param {number} speed - The speed value in mm/s
     * @return {number} The speed factor in units of "X" (50mm/s)
     */
    function getSpeedFactor(speed) {
        return `X${speed / 50}`;
    }

    function setText(selectors, value) {
        selectors.forEach(function (selector) {
            $(selector).text(value);
        });
    }

    function setDisabled(selectors, disabled) {
        selectors.forEach(function (selector) {
            const elem = $(selector).get(0);
            if (elem) {
                elem.disabled = disabled;
            }
        });
    }

    /**
     * Updates the country code <select> element
     */
    (function(selectElement) {
        var countryCodes = selectElement.data("countrycodes");
        var currentCountry = selectElement.data("country");
        countryCodes.forEach((item) => {
            var selected = (currentCountry == item.c) ? " selected" : "";
            $(`<option value="${item.c}"${selected}>${item.n}</option>`).appendTo(selectElement);
        });
    })($("#loginCountry"));

    /**
     * Login data submission and CAPTCHA handling
     */
    $("#captchaRow").hide();
    $("#loginCaptchaId").val("");

    $("#config-login-form").on("submit", function(e) {
        e.preventDefault();

        (async () => {
            const form = $("#config-login-form");
            const url = form.attr("action");

            const form_data = new URLSearchParams();
            for (const pair of new FormData(form.get(0))) {
                form_data.append(pair[0], pair[1]);
            }

            const resp = await fetch(url, {
                method: 'POST',
                body: form_data
            });

            if (resp.status < 300) {
                const data = await resp.json();
                const input = $("#loginCaptchaText");
                if ("redirect" in data) {
                    document.location = data["redirect"];
                }
                else if ("error" in data) {
                    flash_message(data["error"], "danger");
                    input.get(0).focus();
                }
                else if ("captcha_id" in data) {
                    input.val("");
                    input.attr("aria-required", "true");
                    input.prop("required");
                    input.get(0).focus();
                    $("#loginCaptchaId").val(data["captcha_id"]);
                    $("#loginCaptchaImg").attr("src", data["captcha_url"]);
                    $("#captchaRow").show();
                }
            }
            else {
                flash_message(`HTTP Error ${resp.status}: ${resp.statusText}`, "danger")
            }
        })();
    });

    function flash_message(message, category) {
        // copy from base.html
        $(`<div class="alert alert-${category} alert-dismissible fade show" data-timeout="7500" role="alert">` +
          '<button type="button" class="btn-close btn-sm btn-close-white" data-bs-dismiss="alert" aria-label="Close">' +
          '</button>' +
          message +
          '</div>').appendTo($("#messages").empty());
        // does not auto-close yet...
    }

    /**
     * AutoWebSocket class
     *
     * This class wraps a WebSocket, and makes it automatically reconnect if the
     * connection is lost.
     */
    class AutoWebSocket {
        constructor({
            name,
            url,
            badge = null,
            open = null,
            opened = null,
            close = null,
            error = null,
            message = null,
            binary = false,
            reconnect = 1000,
        }) {
            this.name = name;
            this.url = url;
            this.badge = badge;
            this.reconnect = reconnect;
            this.open = open;
            this.opened = opened;
            this.close = close;
            this.error = error;
            this.message = message;
            this.binary = binary;
            this.ws = null;
            this.is_open = false;
        }

        _open() {
            $(this.badge).removeClass("text-bg-success text-bg-danger").addClass("text-bg-warning");
            if (this.open)
                this.open(this.ws);
        }

        _close() {
            $(this.badge).removeClass("text-bg-warning text-bg-success").addClass("text-bg-danger");
            this.is_open = false;
            setTimeout(() => this.connect(), this.reconnect);
            if (this.close)
                this.close(this.ws);
        }

        _error() {
            console.log(`${this.name} error`);
            this.ws.close();
            this.is_open = false;
            if (this.error)
                this.error(this.ws);
        }

        _message(event) {
            if (!this.is_open) {
                $(this.badge).removeClass("text-bg-danger text-bg-warning").addClass("text-bg-success");
                this.is_open = true;
                if (this.opened)
                    this.opened(event);
            }
            if (this.message)
                this.message(event);
        }

        connect() {
            var ws = this.ws = new WebSocket(this.url);
            if (this.binary)
                ws.binaryType = "arraybuffer";
            ws.addEventListener("open", this._open.bind(this));
            ws.addEventListener("close", this._close.bind(this));
            ws.addEventListener("error", this._error.bind(this));
            ws.addEventListener("message", this._message.bind(this));
        }
    }

    /**
     * Auto web sockets
     */
    sockets = {};

    // Name of the running job, from print telemetry; used by PRINT_CONTROL.
    let currentPrintFile = "";
    let printerState = "unknown";
    let currentNozzleTemp = 0;
    let requestedNozzleTarget = null;
    let requestedBedTarget = null;
    let lastPrinterHeartbeat = 0;
    let lastTelemetry = 0;
    let printerHeartbeatPending = false;
    let printerHeartbeatTimer = null;
    let printerHeartbeatTimeout = null;
    const PRINTER_HEARTBEAT_INTERVAL_MS = 10000;
    const PRINTER_HEARTBEAT_STALE_MS = 15000;
    const PRINTER_HEARTBEAT_REPLY_TIMEOUT_MS = 5000;
    const HEARTBEAT_REQUEST_ID = "printer-heartbeat";

    function printIsActive() {
        return /print|paus|resume/i.test(printerState) || currentPrintFile !== "";
    }

    // The printer is only considered live if it has said something recently.  An
    // open control socket proves we reached ankerctl, not that ankerctl reached
    // the printer: its service threads can wedge while still reporting Running.
    function printerIsLive() {
        return Date.now() - lastPrinterHeartbeat < PRINTER_HEARTBEAT_STALE_MS
            || Date.now() - lastTelemetry < PRINTER_HEARTBEAT_STALE_MS;
    }

    function telemetryIsFresh() {
        return Date.now() - lastTelemetry < PRINTER_HEARTBEAT_STALE_MS;
    }

    function updatePrinterState() {
        let state;
        if (printIsActive()) {
            state = printerState;
        } else if (printerIsLive()) {
            state = "Ready";
        } else if (printerHeartbeatPending) {
            state = "Checking…";
        } else {
            state = "Offline";
        }
        setText(["#control-printer-state"], state);
    }

    function sendPrinterHeartbeat() {
        if (!ctrlReady()) {
            updatePrinterState();
            return;
        }
        // State telemetry is stronger evidence of liveness than another M105.
        // Avoid adding fixed-rate MQTT traffic while the printer is already
        // publishing, especially during a print. Probing resumes once that
        // passive traffic becomes stale.
        if (telemetryIsFresh()) {
            printerHeartbeatPending = false;
            window.clearTimeout(printerHeartbeatTimeout);
            printerHeartbeatTimeout = null;
            updatePrinterState();
            return;
        }
        printerHeartbeatPending = true;
        window.clearTimeout(printerHeartbeatTimeout);
        sendMqtt({
            commandType: MqttMsgType.ZZ_MQTT_CMD_GCODE_COMMAND,
            cmdData: "M105",
            cmdLen: 4,
        }, true, HEARTBEAT_REQUEST_ID);
        printerHeartbeatTimeout = window.setTimeout(function () {
            printerHeartbeatPending = false;
            updatePrinterState();
        }, PRINTER_HEARTBEAT_REPLY_TIMEOUT_MS);
    }

    function startPrinterHeartbeat() {
        window.clearInterval(printerHeartbeatTimer);
        sendPrinterHeartbeat();
        printerHeartbeatTimer = window.setInterval(function () {
            sendPrinterHeartbeat();
            updatePrinterState();
            updateAttendedControls();
        }, PRINTER_HEARTBEAT_INTERVAL_MS);
    }

    function stopPrinterHeartbeat() {
        window.clearInterval(printerHeartbeatTimer);
        printerHeartbeatTimer = null;
        window.clearTimeout(printerHeartbeatTimeout);
        printerHeartbeatTimeout = null;
        lastPrinterHeartbeat = 0;
        printerHeartbeatPending = false;
        updatePrinterState();
    }

    function updateAttendedControls() {
        // Gate on the printer answering, not merely on our socket to ankerctl
        // being open: a wedged ankerctl accepts commands and drops them silently.
        const controlReady = ctrlReady() && printerIsLive();
        const printActive = printIsActive();
        $("#print-pause, #print-resume, #print-stop").prop("disabled", !controlReady || !printActive);
        const canAdjustZ = controlReady && !printActive;
        const canMoveFilament = canAdjustZ && currentNozzleTemp >= 17000;
        // Full/Z homing is disabled independently of connection state. Both
        // raw G28 and the app-level MOVE_ZERO command drove this M5C into the
        // plate without engaging the nozzle probe.
        $("#jog-home").prop("disabled", true);
        $(".jog-btn").prop("disabled", !canAdjustZ);
        $("#z-offset-down, #z-offset-up").prop("disabled", !canAdjustZ);
        $("#filament-retract, #filament-extrude").prop("disabled", !canMoveFilament);
    }

    // Telemetry socket: consumes the normalized printer-state schema from
    // /ws/state (nozzle/bed/print/speed/state) instead of raw MQTT commandType
    // messages. The raw feed still exists on /ws/mqtt for debugging.
    sockets.mqtt = new AutoWebSocket({
        name: "state socket",
        url: `${location.protocol.replace('http','ws')}//${location.host}/ws/state`,

        opened: function (event) {
            setDisabled(["#set-nozzle-temp", "#set-bed-temp"], false);
        },

        message: function (ev) {
            const data = JSON.parse(ev.data);
            lastTelemetry = Date.now();
            updatePrinterState();

            if ("state" in data) {
                printerState = data.state;
                updatePrinterState();
                updateAttendedControls();
            }

            if (data.print) {
                const p = data.print;
                if ("name" in p) {
                    currentPrintFile = p.name || "";
                    $("#print-name").text(p.name);
                    updateAttendedControls();
                }
                if ("elapsed" in p) {
                    $("#time-elapsed").text(getTime(p.elapsed));
                }
                if ("remaining" in p) {
                    $("#time-remain").text(getTime(p.remaining));
                }
                if ("progress" in p) {
                    const progress = getPercentage(p.progress);
                    $("#progressbar").attr("aria-valuenow", progress);
                    $("#progressbar").attr("style", `width: ${progress}%`);
                    setText(["#progress", "#control-progress"], `${progress}%`);
                    $("#control-preview-bar")
                        .text(`${progress}%`)
                        .attr("aria-valuenow", progress)
                        .attr("style", `width: ${progress}%`);
                }
                // Control tab: object preview (printer-provided image URL) + overlay
                if ("img" in p) {
                    if ($("#control-preview-img").attr("src") !== p.img) {
                        $("#control-preview-img").attr("src", p.img);
                    }
                    $("#control-preview-name").text(p.name || "");
                    $("#control-preview-wrap").show();
                }
                if (p.layer) {
                    setText(["#print-layer", "#control-layer"], `${p.layer.current} / ${p.layer.total}`);
                }
            }

            if (data.nozzle) {
                if ("current" in data.nozzle) {
                    currentNozzleTemp = data.nozzle.current;
                    setText(["#nozzle-temp", "#control-nozzle-current"], `${getTemp(data.nozzle.current)}°C`);
                    updateAttendedControls();
                }
                if ("target" in data.nozzle) {
                    const target = getTemp(data.nozzle.target);
                    if (!isNaN(target)) {
                        if (requestedNozzleTarget === target) {
                            requestedNozzleTarget = null;
                        }
                        const shownTarget = requestedNozzleTarget ?? target;
                        setText(["#set-nozzle-temp", "#control-nozzle-target"], `${shownTarget}°C`);
                        $("#control-nozzle-input").val(shownTarget);
                    }
                }
            }

            if (data.bed) {
                if ("current" in data.bed) {
                    setText(["#bed-temp", "#control-bed-current"], `${getTemp(data.bed.current)}°C`);
                }
                if ("target" in data.bed) {
                    const target = getTemp(data.bed.target);
                    if (!isNaN(target)) {
                        if (requestedBedTarget === target) {
                            requestedBedTarget = null;
                        }
                        const shownTarget = requestedBedTarget ?? target;
                        setText(["#set-bed-temp", "#control-bed-target"], `${shownTarget}°C`);
                        $("#control-bed-input").val(shownTarget);
                    }
                }
            }

            if ("speed" in data) {
                setText(["#print-speed", "#control-print-speed"], `${data.speed}mm/s ${getSpeedFactor(data.speed)}`);
            }
        },

        close: function (ws) {
            $("#print-name").text("");
            $("#time-elapsed").text("00:00:00");
            $("#time-remain").text("00:00:00");
            $("#progressbar").attr("aria-valuenow", 0);
            $("#progressbar").attr("style", "width: 0%");
            setText(["#progress", "#control-progress"], "0%");
            setText(["#nozzle-temp", "#control-nozzle-current"], "0°C");
            setText(["#set-nozzle-temp", "#control-nozzle-target"], "0°C");
            setText(["#bed-temp", "#control-bed-current"], "0°C");
            setText(["#set-bed-temp", "#control-bed-target"], "0°C");
            setText(["#print-speed", "#control-print-speed"], "0mm/s");
            setText(["#print-layer", "#control-layer"], "0 / 0");
            printerState = "disconnected";
            currentNozzleTemp = 0;
            currentPrintFile = "";
            requestedNozzleTarget = null;
            requestedBedTarget = null;
            lastTelemetry = 0;
            updatePrinterState();
            setDisabled(["#set-nozzle-temp", "#set-bed-temp"], true);
            updateAttendedControls();
        },
    });

    /**
     * Initializing a new instance of JMuxer for video playback
     */
    sockets.video = new AutoWebSocket({
        name: "Video socket",
        url: `${location.protocol.replace('http','ws')}${location.host}/ws/video`,
        badge: "#badge-video",
        binary: true,

        open: function () {
            this.jmuxer = new JMuxer({
                node: "player",
                mode: "video",
                flushingTime: 0,
                fps: 15,
                // debug: true,
                onReady: function (data) {
                    console.log(data);
                },
                onError: function (data) {
                    console.log(data);
                },
            });
        },

        message: function (event) {
            this.jmuxer.feed({
                video: new Uint8Array(event.data),
            });
        },

        close: function () {
            if (!this.jmuxer)
                return;

            this.jmuxer.destroy();

            /* Clear video source (to show loading animation) */
            $("#player").attr("src", "");
        },
    });

    sockets.ctrl = new AutoWebSocket({
        name: "Control socket",
        url: `${location.protocol.replace('http','ws')}//${location.host}/ws/ctrl`,

        opened: function () {
            $(".control-command").prop("disabled", false);
            updateAttendedControls();
            startPrinterHeartbeat();
        },

        message: function (event) {
            const data = JSON.parse(event.data);
            if (data.ankerctlError) {
                flash_message(data.ankerctlError, "warning");
                appendGcodeLog(`< Blocked: ${data.ankerctlError}`);
                return;
            }
            if (data.requestId === HEARTBEAT_REQUEST_ID) {
                window.clearTimeout(printerHeartbeatTimeout);
                printerHeartbeatTimeout = null;
                printerHeartbeatPending = false;
                if (data.mqttReply) {
                    lastPrinterHeartbeat = Date.now();
                } else {
                    lastPrinterHeartbeat = 0;
                }
                updatePrinterState();
                updateAttendedControls();
                return;
            }
            if (Object.prototype.hasOwnProperty.call(data, "mqttReply")) {
                if (data.mqttReply && Object.prototype.hasOwnProperty.call(data.mqttReply, "resData")) {
                    appendGcodeLog(`< ${data.mqttReply.resData}`);
                } else if (data.mqttReply) {
                    appendGcodeLog(`< ${JSON.stringify(data.mqttReply)}`);
                } else {
                    appendGcodeLog("< No response");
                }
            }
        },

        close: function () {
            $(".control-command").prop("disabled", true);
            updateAttendedControls();
            stopPrinterHeartbeat();
        },
    });

    sockets.pppp_state = new AutoWebSocket({
        name: "PPPP socket",
        url: `${location.protocol.replace('http','ws')}//${location.host}/ws/pppp-state`,
    });

    /* Only connect websockets if #player element exists in DOM (i.e., if we
     * have a configuration). Otherwise we are constantly trying to make
     * connections that will never succeed. */
    if ($("#control-printer-state").length) {
        sockets.mqtt.connect();
        sockets.ctrl.connect();
        sockets.pppp_state.connect();
    }
    if ($("#player").length) {
        sockets.video.connect();
    }

    /**
     * On click of element with id "light-on", sends JSON data to wsctrl to turn light on
     */
    $("#light-on").on("click", function () {
        sockets.ctrl.ws.send(JSON.stringify({ light: true }));
        return false;
    });

    /**
     * On click of element with id "light-off", sends JSON data to wsctrl to turn light off
     */
    $("#light-off").on("click", function () {
        sockets.ctrl.ws.send(JSON.stringify({ light: false }));
        return false;
    });

    /**
     * On click of element with id "quality-low", sends JSON data to wsctrl to set video quality to low
     */
    $("#quality-low").on("click", function () {
        sockets.ctrl.ws.send(JSON.stringify({ quality: 0 }));
        return false;
    });

    /**
     * On click of element with id "quality-high", sends JSON data to wsctrl to set video quality to high
     */
    $("#quality-high").on("click", function () {
        sockets.ctrl.ws.send(JSON.stringify({ quality: 1 }));
        return false;
    });

    /**
     * Handle input modal being shown
     */
    var popupModalInputDom = document.getElementById("popupModalInput");
    var popupModalInputBS = new bootstrap.Modal(popupModalInputDom);

    $(".control-temperature-picker").on("click", function () {
        const trigger = document.querySelector($(this).attr("data-picker-trigger"));
        popupModalInputBS.show(trigger);
        return false;
    });

    popupModalInputDom.addEventListener("shown.bs.modal", function (e) {
        const trigger = e.relatedTarget;
        const input_id = $(trigger).attr("id");
        const modalInput = $("#modal-input-elem");
        const isTemperatureTarget = $(trigger).attr("data-clear-on-open") === "true";
        setClearModalInput(trigger, $(trigger).attr("title"))

        if (isTemperatureTarget) {
            const picker = $("#temperature-picker");
            const range = $("#temperature-picker-range");
            const max = $(trigger).attr("data-input-max");
            range.attr("max", max).attr("step", $(trigger).attr("data-picker-step") || "5").val(0);
            range.get(0).oninput = function () {
                $("#temperature-picker-value").text(`${this.value}°C`);
            };
            $("#temperature-picker-value").text("0°C");
            picker.attr("data-temperature-target", input_id);
            picker.removeClass("d-none");
            $("#popupModalInputCustom").removeClass("d-none");
            $("#popupModalInputOK").text("Set slider");
        } else {
            $("#temperature-picker").addClass("d-none").removeAttr("data-temperature-target");
            $("#popupModalInputCustom").addClass("d-none");
            $("#popupModalInputOK").text("OK");
        }
        document.getElementById("popupModalInputCustom").onclick = function () {
            const customValue = String(modalInput.val() || "").trim();
            if (customValue === "") {
                flash_message("Enter a custom temperature first", "warning");
                return false;
            }
            sendNewValueViaMQTT(input_id, customValue);
            setClearModalInput(trigger, "", false);
            $("#popupModalInput form").off("submit");
            popupModalInputBS.hide();
            return false;
        };

        $("#popupModalInput form").on("submit", function (event) {
            // do not perform the default submit action
            event.preventDefault();

            // send the new value to the printer
            const value = isTemperatureTarget
                ? document.getElementById("temperature-picker-range").value
                : String(modalInput.val() || "").trim();
            sendNewValueViaMQTT(input_id, value);

            // clear modal
            setClearModalInput(trigger, "", false);

            // remove previous "submit" event handlers
            $("#popupModalInput form").off("submit");

            // hide modal
            popupModalInputBS.hide()

            return false;
        });

        if (isTemperatureTarget) {
            modalInput.attr("placeholder", "Enter temperature");
        } else {
            modalInput.removeAttr("placeholder");
            modalInput.get(0).select();
        }
        // Keep the keyboard closed for temperature pickers. The slider is the
        // default path; tapping the empty custom field explicitly selects it.
        if (!isTemperatureTarget) {
            modalInput.get(0).focus();
        }
    });

    // from https://stackoverflow.com/a/3561711/15468061
    function escapeRegex(string) {
        return string.replace(/[/\-\\^$*+?.()|[\]{}]/g, '\\$&');
    }

    function setClearModalInput(trigger, title, doSet = true) {
        const modalInput = $("#modal-input-elem");
        let unit = "";
        // loop over all "data-input-*" attributes
        [].forEach.call(trigger.attributes, function (attr) {
            console.debug("attr", attr);
            if (attr.name.startsWith("data-input-")) {
                const value = attr.value;
                const attr_name = attr.name.slice(11);
                switch (attr_name) {
                    case "icon-class":
                        if (doSet) {
                            $("#popupModalGroup").children().addClass(value);
                        } else {
                            $("#popupModalGroup").children().removeClass(value);
                        }
                        break;
                    case "unit":
                        $("#popupModalInputUnit").text(doSet ? value : "");
                        unit = value;
                        break;
                    default:
                        if (doSet) {
                            modalInput.attr(attr_name, value);
                        } else {
                            modalInput.removeAttr(attr_name);
                        }
                }
            }
        });
        if (doSet) {
            // special handling of title and value
            $("#modal-input-inner").text(title);
            const unit_regex = new RegExp(escapeRegex(unit) + "$");
            const input_value = $(trigger).attr("data-clear-on-open") === "true"
                ? ""
                : $(trigger).text().trim().replace(unit_regex, "").trim();
            modalInput.val(input_value);
        } else {
            $("#modal-input-inner").text("");
            modalInput.val("");
        }
    }

    function sendNewValueViaMQTT(input_id, new_value) {
        const target = Number.parseInt(new_value, 10);
        const temperatures = {
            "set-nozzle-temp": { kind: "nozzle", command: "M104", limit: 300, target: "#set-nozzle-temp" },
            "control-nozzle-input": { kind: "nozzle", command: "M104", limit: 300, target: "#set-nozzle-temp" },
            "set-bed-temp": { kind: "bed", command: "M140", limit: 100, target: "#set-bed-temp" },
            "control-bed-input": { kind: "bed", command: "M140", limit: 100, target: "#set-bed-temp" },
        };
        const setting = temperatures[input_id];
        if (!setting || !Number.isInteger(target) || target < 0 || target > setting.limit) {
            flash_message("Enter a temperature within the allowed range", "warning");
            return;
        }
        // PREHEAT_CONFIG stores a profile; it does not change the active
        // heater target. M104/M140 are the firmware commands that do.
        if (setting.kind === "nozzle") {
            requestedNozzleTarget = target;
            $("#control-nozzle-input").val(target);
        } else {
            requestedBedTarget = target;
            $("#control-bed-input").val(target);
        }
        sendGcode(`${setting.command} S${target}`);
        setText([setting.target], `${target}°C`);
    }

    /**
     * Control tab
     *
     * Sends printer commands over the /ws/ctrl websocket as raw GCode
     * (GCODE_COMMAND). Pause/resume use PRINT_CONTROL with the active job
     * identity. Stop combines PRINT_CONTROL cancellation with M2024 so both
     * the communication-module job and MCU-buffered motion are stopped.
     */
    function ctrlReady() {
        return sockets.ctrl && sockets.ctrl.ws && sockets.ctrl.is_open;
    }

    function appendGcodeLog(line) {
        const logElem = $("#gcode-log");
        if (!logElem.length) {
            return;
        }
        logElem.append(document.createTextNode(`${line}\n`));
        logElem.get(0).scrollTop = logElem.get(0).scrollHeight;
    }

    function sendMqtt(message_data, awaitResponse = false, requestId = null) {
        if (!ctrlReady()) {
            flash_message("Control socket not connected", "warning");
            return;
        }
        // The heartbeat is exempt: it is the probe that re-establishes liveness,
        // so blocking it while offline would make recovery impossible.
        if (requestId !== HEARTBEAT_REQUEST_ID && !printerIsLive()) {
            flash_message("Printer is not responding — command not sent", "danger");
            return;
        }
        const message = {
            mqtt: message_data,
            awaitResponse: awaitResponse,
        };
        if (requestId !== null) {
            message.requestId = requestId;
        }
        sockets.ctrl.ws.send(JSON.stringify(message));
    }

    // Pause/resume identify the running job by name. Stop is deliberately not
    // routed through this helper: its captured and live-validated payload is
    // the minimal {commandType: PRINT_CONTROL, value: 0} form.
    function sendJobControl(value) {
        sendMqtt({
            commandType: MqttMsgType.ZZ_MQTT_CMD_PRINT_CONTROL,
            value: value,
            userName: "ankerctl",
            filePath: currentPrintFile,
        });
    }

    function attemptsZHome(line) {
        const command = String(line).split(";", 1)[0].trim().toUpperCase();
        if (!command.startsWith("G28")) {
            return false;
        }
        const axes = command.slice(3).match(/[XYZ]/g) || [];
        return axes.length === 0 || axes.includes("Z");
    }

    function sendGcode(line, awaitResponse = false) {
        if (attemptsZHome(line)) {
            flash_message("Direct web Z homing is disabled because it did not engage the M5C probe sequence", "warning");
            return false;
        }
        sendMqtt({
            commandType: MqttMsgType.ZZ_MQTT_CMD_GCODE_COMMAND,
            cmdData: line,
            cmdLen: line.length,
        }, awaitResponse);
        appendGcodeLog(`> ${line}`);
        return true;
    }

    $("#control-refresh").on("click", function () {
        window.location.reload();
        return false;
    });

    // Pause / Resume use PRINT_CONTROL (job-aware) rather than M2022/M2023;
    // the M-code path does not act on an onboard job whose stream the
    // communication module owns.
    $("#print-pause").on("click", function () {
        sendJobControl(1);
        return false;
    });
    $("#print-resume").on("click", function () {
        sendJobControl(2);
        return false;
    });
    // Stop needs both paths: PRINT_CONTROL value=0 cancels the job on the
    // communication module (M2024 alone cannot cancel it), and M2024 clears
    // the MCU queue and stops motion already buffered.
    $("#print-stop").on("click", function () {
        if (window.confirm("Stop the current print?")) {
            sendMqtt({
                commandType: MqttMsgType.ZZ_MQTT_CMD_PRINT_CONTROL,
                value: 0,
            });
            sendGcode("M2024");
        }
        return false;
    });

    // Part fan (0-100% -> M106 S0-255, 0 -> M107)
    $("#fan-slider").on("input", function () {
        $("#fan-value").text(`${this.value}%`);
    });
    $("#fan-apply").on("click", function () {
        const pct = parseInt($("#fan-slider").val());
        if (pct <= 0) {
            sendGcode("M107");
        } else {
            sendGcode(`M106 S${Math.round(pct * 255 / 100)}`);
        }
        return false;
    });

    // Jog in relative mode, restoring absolute mode in a separate command.
    // A semicolon starts a Marlin comment, so combining these on one line
    // would execute G91 but silently discard the move and trailing G90.
    $(".jog-btn").on("click", function () {
        const axis = $(this).data("axis");
        const dir = parseInt($(this).data("dir"));
        const step = parseFloat($("#jog-step").val()) * dir;
        const feed = (axis === "Z") ? 600 : 3000;
        sendGcode("G91");
        sendGcode(`G1 ${axis}${step} F${feed}`);
        sendGcode("G90");
        return false;
    });
    function confirmAttendedAction(message) {
        if (printIsActive()) {
            flash_message("This control is unavailable while a print is active", "warning");
            return false;
        }
        if (!window.confirm(message)) {
            return false;
        }
        return true;
    }

    $("#filament-extrude, #filament-retract").on("click", function () {
        const amount = parseFloat($("#filament-amount").val());
        const direction = this.id === "filament-extrude" ? 1 : -1;
        const action = direction > 0 ? "extrude" : "retract";
        if (currentNozzleTemp < 17000) {
            flash_message("Heat the nozzle to at least 170°C before moving filament", "warning");
            return false;
        }
        if (!confirmAttendedAction(`${action[0].toUpperCase()}${action.slice(1)} ${amount} mm of filament? Stay at the printer.`)) {
            return false;
        }
        // The printer treats a semicolon as the beginning of a comment, so
        // these must be separate messages rather than one combined string.
        sendGcode("M83");
        sendGcode(`G1 E${direction * amount} F300`);
        sendGcode("M82");
        return false;
    });

    $("#z-offset-down, #z-offset-up").on("click", function () {
        const step = parseFloat($("#z-offset-step").val());
        const direction = this.id === "z-offset-up" ? 1 : -1;
        const amount = direction * step;
        if (!confirmAttendedAction(`Apply a live Z adjustment of ${amount.toFixed(2)} mm? Stay at the printer.`)) {
            return false;
        }
        sendGcode(`M290 Z${amount.toFixed(2)}`);
        return false;
    });

    // GCode terminal
    $("#gcode-form").on("submit", function (event) {
        event.preventDefault();
        const input = $("#gcode-input");
        const line = input.val().trim();
        if (line) {
            sendGcode(line, true);
            input.val("");
        }
        return false;
    });

});
