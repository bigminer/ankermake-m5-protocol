"""Typed, server-owned Printer actions.

Protocol details, policy, sequencing, journal behavior, supersession, and
confirmation remain private behind ``submit`` and ``watch``.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import logging as log
import os
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
import time


@dataclass(frozen=True)
class Stop:
    kind: str = "stop"


@dataclass(frozen=True)
class Pause:
    kind: str = "pause"


@dataclass(frozen=True)
class Resume:
    kind: str = "resume"


@dataclass(frozen=True)
class NozzleTarget:
    celsius: int
    kind: str = "nozzle_target"


@dataclass(frozen=True)
class BedTarget:
    celsius: int
    kind: str = "bed_target"


@dataclass(frozen=True)
class HeaterOff:
    heater: str
    kind: str = "heater_off"


@dataclass(frozen=True)
class FanSetting:
    percent: int
    kind: str = "fan_setting"


@dataclass(frozen=True)
class PrintStart:
    """Print one staged upload, named only by its opaque artifact reference.

    Everything else the Compound action needs -- the file, the preparation
    temperatures, and the caller identity -- is server-owned staging metadata,
    so no caller can substitute content or identity at submission time.
    """

    artifact: str
    kind: str = "print_start"


@dataclass(frozen=True)
class ActionRequest:
    request_id: str
    printer_id: str
    action: object


@dataclass(frozen=True)
class ActionOutcome:
    request_id: str
    printer_id: str
    action: str
    status: str
    reason: str | None
    accepted_at: float | None
    updated_at: float
    parameters: dict | None = None

    def to_dict(self):
        return {
            "requestId": self.request_id,
            "printerId": self.printer_id,
            "action": self.action,
            "status": self.status,
            "reason": self.reason,
            "acceptedAt": self.accepted_at,
            "updatedAt": self.updated_at,
            "parameters": self.parameters or {},
        }


_ACTION_TYPES = (
    Stop,
    Pause,
    Resume,
    NozzleTarget,
    BedTarget,
    HeaterOff,
    FanSetting,
    PrintStart,
)

# Job actions contradict each other: only one may be unresolved at a time.
_JOB_ACTIONS = {"pause", "resume", "print_start"}

_IDLE_STATES = {"idle", "stopped", "stop", "0", "4"}

# Preparation limits are the M5C (V8110) firmware's own clamps, the same
# derivation as the pre-print hook in ``web.util``.  They are deliberately
# wider than the interactive NozzleTarget limit: a slicer's first-layer
# temperature is a resolved print parameter, not a hand-typed one.
_PREPARATION_LIMITS = {"bed": (1, 115), "nozzle": (150, 310)}

# Tolerances that decided the pre-print hook's live-validated heat-up waits.
_PREPARATION_TOLERANCE = {"bed": 0.5, "nozzle": 1.0}

# Supervised-validation evidence identifies the exact observable contract it
# established. Changing a contract value gates that action again until new
# evidence names the new value.
_ACTION_CONTRACTS = {
    "stop": "m5c-stop-v1",
    "pause": "m5c-pause-v1",
    "resume": "m5c-resume-v1",
    "nozzle_target": "m5c-nozzle-target-v1",
    "bed_target": "m5c-bed-target-v1",
    "heater_off": "m5c-heater-off-v1",
    "fan_setting": "m5c-fan-setting-v1",
    "print_start": "m5c-print-start-v1",
}


class _Aborted(Exception):
    """A Protective action cancelled this Compound action at a checkpoint."""


class _PreparationTimeout(Exception):
    """The printer did not reach a required preparation temperature."""


class PrinterActions:
    """Deep Printer-action module with the ``submit`` / ``watch`` interface."""

    def __init__(
        self,
        *,
        snapshots,
        protocol,
        journal_path,
        artifacts=None,
        transfers=None,
        clock=time.time,
        sleep=time.sleep,
        run_async=None,
        validation_mode=False,
        validated_contracts=None,
        confirmation_timeout=30.0,
        preparation_timeout=900.0,
        temperature_poll=1.0,
    ):
        self._snapshots = snapshots
        self._protocol = protocol
        self._artifacts = artifacts
        self._transfers = transfers
        self._journal_path = Path(journal_path)
        self._clock = clock
        self._sleep = sleep
        self._run_async = run_async or _run_in_background
        self._validation_mode = validation_mode
        self._validated_contracts = dict(validated_contracts or {})
        self._confirmation_timeout = confirmation_timeout
        self._preparation_timeout = preparation_timeout
        self._temperature_poll = temperature_poll
        self._records = {}
        self._requests = {}
        self._deadlines = {}
        self._contexts = {}
        self._aborts = {}
        self._locks = {}
        self._load_journal()

    @property
    def artifacts(self):
        """The staging area callers use to obtain an artifact reference."""
        return self._artifacts

    def is_enabled(self, kind):
        """Whether a named action is ungated for ordinary, unattended use."""
        return (
            self._validation_mode
            or self._validated_contracts.get(kind) == _ACTION_CONTRACTS.get(kind)
        )

    def watch(self, watch):
        return self._snapshots.watch(watch)

    def submit(self, request):
        if not isinstance(request.action, _ACTION_TYPES):
            return self._rejected(request, "unsupported_action")

        canonical = (request.printer_id, asdict(request.action))
        existing = self._records.get(request.request_id)
        if existing is not None:
            if self._requests[request.request_id] == canonical:
                return existing
            return self._rejected(request, "request_identity_conflict", publish=False)

        if not self.is_enabled(request.action.kind):
            return self._rejected(request, "supervised_validation_required")

        context = self._action_context(request)
        if context.get("error"):
            return self._rejected(request, context["error"])

        if isinstance(
            request.action, (Pause, Resume, PrintStart)
        ) and self._pending_job_actions(request.printer_id):
            return self._rejected(request, "conflicting_job_action_pending")

        resources = set(context.get("resources", ()))

        now = self._clock()
        parameters = self._action_parameters(request.action)
        accepted = ActionOutcome(
            request.request_id,
            request.printer_id,
            request.action.kind,
            "accepted",
            None,
            now,
            now,
            parameters,
        )
        self._requests[request.request_id] = canonical
        self._record(accepted)

        if isinstance(request.action, Stop):
            for pending in self._pending_job_actions(request.printer_id):
                self._transition(pending, "superseded", "protective_stop_submitted")
                self._resolve(pending.request_id)
            # A Protective Stop drives both heater targets to 0, which is what
            # _stop_is_confirmed waits on.  A pending heater target can never
            # reach its own value after that, so resolve it as superseded
            # rather than letting it decay into a confirmation_timeout that
            # reads as a failure of the Stop.  The fan is deliberately excluded:
            # Stop sends only PRINT_CONTROL and M2024, so we have no evidence
            # it halts the fan.
            self._supersede_resource_targets(
                request.printer_id, {"nozzle", "bed"}, "protective_stop_submitted"
            )
        if resources:
            self._supersede_resource_targets(
                request.printer_id, resources, "newer_target_submitted"
            )

        if isinstance(request.action, PrintStart):
            # A Compound action outlives its submission: acceptance is durable
            # first, then preparation, transfer, and start run to completion
            # without holding the caller.
            self._contexts[request.request_id] = context
            self._aborts[request.request_id] = Event()
            self._run_async(
                lambda: self._run_print_start(request.request_id, accepted, context)
            )
            return self._records[request.request_id]

        lock = self._locks.setdefault(request.printer_id, Lock())
        try:
            with lock:
                if isinstance(request.action, Stop):
                    reply = self._protocol.protective_stop(request.printer_id)
                    if reply is None:
                        log.warning(
                            "Protective Stop %s received no PRINT_CONTROL reply",
                            request.request_id,
                        )
                    else:
                        log.info(
                            "Protective Stop %s PRINT_CONTROL reply=%r",
                            request.request_id,
                            reply.get("reply"),
                        )
                        if reply.get("reply") != 0:
                            return self._transition(
                                accepted,
                                "indeterminate",
                                "print_control_rejected",
                            )
                elif isinstance(request.action, (Pause, Resume)):
                    value = 1 if isinstance(request.action, Pause) else 2
                    self._protocol.mqtt(
                        request.printer_id,
                        {
                            "commandType": 1008,
                            "value": value,
                            "userName": context["user_name"],
                            "filePath": context["file_name"],
                        },
                    )
                elif isinstance(request.action, NozzleTarget):
                    self._protocol.gcode(
                        request.printer_id, f"M104 S{request.action.celsius}"
                    )
                elif isinstance(request.action, BedTarget):
                    self._protocol.gcode(
                        request.printer_id, f"M140 S{request.action.celsius}"
                    )
                elif isinstance(request.action, HeaterOff):
                    if request.action.heater in {"nozzle", "all"}:
                        self._protocol.gcode(request.printer_id, "M104 S0")
                    if request.action.heater in {"bed", "all"}:
                        self._protocol.gcode(request.printer_id, "M140 S0")
                elif isinstance(request.action, FanSetting):
                    if request.action.percent == 0:
                        self._protocol.gcode(request.printer_id, "M107")
                    else:
                        pwm = round(request.action.percent * 255 / 100)
                        self._protocol.gcode(request.printer_id, f"M106 S{pwm}")
        except Exception:
            return self._transition(
                accepted, "indeterminate", "protocol_submission_uncertain"
            )

        self._deadlines[request.request_id] = now + self._confirmation_timeout
        self._contexts[request.request_id] = context
        return accepted

    def tick(self):
        now = self._clock()
        for request_id, deadline in list(self._deadlines.items()):
            record = self._records[request_id]
            if record.action == "stop":
                confirmed = self._stop_is_confirmed(record.printer_id)
            elif record.action == "pause":
                confirmed = self._job_state_is_confirmed(
                    record.printer_id, self._contexts[request_id], {"paused", "pause", "2"}
                )
            elif record.action in {"resume", "print_start"}:
                confirmed = self._job_state_is_confirmed(
                    record.printer_id, self._contexts[request_id], {"printing", "1"}
                )
            elif record.action in {"nozzle_target", "bed_target", "heater_off"}:
                confirmed = self._targets_are_confirmed(
                    record.printer_id, self._contexts[request_id]
                )
            else:
                confirmed = False
            if confirmed:
                self._transition(record, "confirmed", None)
                self._resolve(request_id)
            elif now >= deadline:
                reason = (
                    "confirmation_unavailable"
                    if record.action == "fan_setting"
                    else "confirmation_timeout"
                )
                self._transition(record, "indeterminate", reason)
                self._resolve(request_id)

    def _action_context(self, request):
        if isinstance(request.action, (Pause, Resume)):
            required_states = (
                {"printing", "1"}
                if isinstance(request.action, Pause)
                else {"paused", "pause", "2"}
            )
            return self._fresh_job_identity(request.printer_id, required_states)

        if isinstance(request.action, NozzleTarget):
            if (
                type(request.action.celsius) is not int
                or not 1 <= request.action.celsius <= 300
            ):
                return {"error": "invalid_action_parameters"}
            return self._temperature_context(
                request.printer_id,
                resource="nozzle",
                expected=request.action.celsius * 100,
            )

        if isinstance(request.action, BedTarget):
            if (
                type(request.action.celsius) is not int
                or not 1 <= request.action.celsius <= 100
            ):
                return {"error": "invalid_action_parameters"}
            return self._temperature_context(
                request.printer_id,
                resource="bed",
                expected=request.action.celsius * 100,
            )

        if isinstance(request.action, HeaterOff):
            if request.action.heater not in {"nozzle", "bed", "all"}:
                return {"error": "invalid_action_parameters"}
            snapshot = self._snapshot(request.printer_id)
            resources = (
                ("nozzle", "bed")
                if request.action.heater == "all"
                else (request.action.heater,)
            )
            return {
                "resources": resources,
                "targets": [
                    {
                        "path": f"{resource}.target",
                        "expected": 0,
                        "baseline": snapshot.facts[
                            f"{resource}.target"
                        ].observed_at,
                    }
                    for resource in resources
                ],
            }

        if isinstance(request.action, FanSetting):
            if (
                type(request.action.percent) is not int
                or not 0 <= request.action.percent <= 100
            ):
                return {"error": "invalid_action_parameters"}
            # Stopping the fan is Protective in the same sense as HeaterOff:
            # it must stay available exactly when telemetry has gone stale.
            # Only raising fan speed requires a fresh state fact.
            if request.action.percent > 0:
                snapshot = self._snapshot(request.printer_id)
                if snapshot.facts["state"].freshness != "fresh":
                    return {"error": "fresh_printer_state_required"}
            return {"resources": ("fan",), "confirmation": "unavailable"}

        if isinstance(request.action, PrintStart):
            return self._print_start_context(request)

        return {}

    def _print_start_context(self, request):
        """Prove a staged print is admissible before anything heats or moves."""
        if self._artifacts is None or self._transfers is None:
            return {"error": "print_start_unavailable"}
        if type(request.action.artifact) is not str or not request.action.artifact:
            return {"error": "invalid_action_parameters"}

        artifact = self._artifacts.get(request.action.artifact)
        if artifact is None:
            return {"error": "unknown_staged_artifact"}

        snapshot = self._snapshot(request.printer_id)
        state = snapshot.facts["state"]
        if state.freshness != "fresh":
            return {"error": "fresh_printer_state_required"}
        if str(state.value).lower() not in _IDLE_STATES:
            return {"error": "idle_printer_required"}

        if artifact.bed_celsius is not None:
            for resource, celsius in (
                ("bed", artifact.bed_celsius),
                ("nozzle", artifact.nozzle_celsius),
            ):
                low, high = _PREPARATION_LIMITS[resource]
                if type(celsius) is not int or not low <= celsius <= high:
                    return {"error": "unsupported_preparation_temperatures"}
                # Preparation waits on these facts, so a heat-up that could
                # never be observed is rejected before the heaters come on.
                if snapshot.facts[f"{resource}.current"].freshness != "fresh":
                    return {"error": f"fresh_{resource}_temperature_required"}

        return {"artifact": artifact, "file_name": artifact.name}

    def _run_print_start(self, request_id, accepted, context):
        """Prepare, transfer, and start one staged artifact, in that order."""
        printer_id = accepted.printer_id
        artifact = context["artifact"]
        abort = self._aborts[request_id]
        record = accepted
        stage = "preparation"
        try:
            if artifact.bed_celsius is not None:
                record = self._transition(record, "accepted", "preparing")
                # Order preserved from the live-validated pre-print routine: a
                # standby nozzle target so the bed can heat without oozing, the
                # bed target, then the real nozzle target, then the firmware's
                # own G36 routine.  G36 is sent out-of-band because the printer
                # rejects it inside uploaded G-code.
                self._protocol.gcode(printer_id, "M104 S150")
                self._protocol.gcode(printer_id, f"M140 S{artifact.bed_celsius}")
                self._await_temperature(printer_id, "bed", artifact.bed_celsius, abort)
                self._protocol.gcode(printer_id, f"M104 S{artifact.nozzle_celsius}")
                self._await_temperature(
                    printer_id, "nozzle", artifact.nozzle_celsius, abort
                )
                self._checkpoint(abort)
                self._protocol.prepare_bed(printer_id, self._preparation_timeout)
            self._checkpoint(abort)

            stage = "transfer"
            record = self._transition(record, "accepted", "transferring")
            # Transfer and start are inseparable, so they are the only part of
            # this action that holds the per-printer protocol lock.
            with self._locks.setdefault(printer_id, Lock()):
                with self._transfers.session(printer_id) as session:
                    with self._artifacts.open(artifact.reference) as stream:
                        handle = session.transfer(stream, artifact.user_name)
                    session.start(handle)
        except _Aborted:
            # A Protective action already published this request's outcome.
            self._clean_up_print_start(printer_id, artifact)
        except _PreparationTimeout:
            self._fail_print_start(record, printer_id, artifact, "preparation_timeout")
        except Exception:
            log.exception("Print start %s failed before confirmation", request_id)
            self._fail_print_start(record, printer_id, artifact, f"{stage}_failed")
        else:
            self._artifacts.discard(artifact.reference)
            if abort.is_set():
                # A Protective Stop landed while the transfer held the lock and
                # has already published this request's outcome.  It runs next,
                # so the job that just started is the one it cancels.
                return
            self._snapshots.remember_job(
                printer_id, artifact.name, artifact.user_name, artifact.origin
            )
            self._deadlines[request_id] = self._clock() + self._confirmation_timeout
            self._transition(record, "accepted", "awaiting_confirmation")
        finally:
            self._aborts.pop(request_id, None)

    def _await_temperature(self, printer_id, resource, celsius, abort):
        tolerance = _PREPARATION_TOLERANCE[resource]
        deadline = self._clock() + self._preparation_timeout
        while True:
            self._checkpoint(abort)
            fact = self._snapshot(printer_id).facts[f"{resource}.current"]
            try:
                reached = (
                    fact.freshness == "fresh"
                    and float(fact.value) / 100 >= celsius - tolerance
                )
            except (TypeError, ValueError):
                reached = False
            if reached:
                return
            if self._clock() >= deadline:
                raise _PreparationTimeout(resource)
            self._sleep(self._temperature_poll)

    @staticmethod
    def _checkpoint(abort):
        if abort.is_set():
            raise _Aborted()

    def _fail_print_start(self, record, printer_id, artifact, reason):
        self._clean_up_print_start(printer_id, artifact)
        self._contexts.pop(record.request_id, None)
        # Preparation heat is a physical effect, so a failure after it began is
        # uncertainty rather than proof that nothing happened.
        self._transition(record, "indeterminate", reason)

    def _clean_up_print_start(self, printer_id, artifact):
        """Discard the staged artifact and stop any preparation heating."""
        self._artifacts.discard(artifact.reference)
        if artifact.bed_celsius is None:
            return
        for line in ("M104 S0", "M140 S0"):
            try:
                self._protocol.gcode(printer_id, line)
            except Exception:
                log.exception("Print-start cleanup could not send %s", line)

    def _pending_job_actions(self, printer_id):
        """Unresolved job actions, whether awaiting confirmation or executing."""
        pending = {}
        for request_id in list(self._deadlines) + list(self._aborts):
            record = self._records.get(request_id)
            if (
                record is not None
                and record.printer_id == printer_id
                and record.action in _JOB_ACTIONS
            ):
                pending[request_id] = record
        return list(pending.values())

    def _resolve(self, request_id):
        """Retire one request, cancelling any Compound action still running."""
        self._deadlines.pop(request_id, None)
        self._contexts.pop(request_id, None)
        abort = self._aborts.get(request_id)
        if abort is not None:
            abort.set()

    def _temperature_context(self, printer_id, *, resource, expected):
        snapshot = self._snapshot(printer_id)
        if snapshot.facts[f"{resource}.current"].freshness != "fresh":
            return {"error": f"fresh_{resource}_temperature_required"}
        return {
            "resources": (resource,),
            "targets": [
                {
                    "path": f"{resource}.target",
                    "expected": expected,
                    "baseline": snapshot.facts[f"{resource}.target"].observed_at,
                }
            ],
        }

    def _snapshot(self, printer_id):
        from .printer_snapshot import Watch

        return next(self._snapshots.watch(Watch(printer_id)))

    def _supersede_resource_targets(self, printer_id, resources, reason):
        for pending_id in list(self._deadlines):
            pending = self._records[pending_id]
            pending_resources = set(
                self._contexts.get(pending_id, {}).get("resources", ())
            )
            if pending.printer_id != printer_id or not resources & pending_resources:
                continue
            self._transition(pending, "superseded", reason)
            del self._deadlines[pending_id]
            self._contexts.pop(pending_id, None)

    def _fresh_job_identity(self, printer_id, required_states):
        snapshot = self._snapshot(printer_id)
        state = snapshot.facts["state"]
        name = snapshot.facts["print.name"]
        user_name = snapshot.facts["print.user_name"]
        if state.freshness != "fresh" or str(state.value).lower() not in required_states:
            return {"error": "compatible_fresh_job_state_required"}
        if name.freshness != "fresh" or not name.value:
            return {"error": "fresh_job_name_required"}
        if user_name.freshness != "fresh" or not user_name.value:
            return {"error": "supported_job_identity_required"}
        return {"file_name": name.value, "user_name": user_name.value}

    def _job_state_is_confirmed(self, printer_id, context, expected_states):
        snapshot = self._snapshot(printer_id)
        state = snapshot.facts["state"]
        name = snapshot.facts["print.name"]
        return (
            state.freshness == "fresh"
            and str(state.value).lower() in expected_states
            and name.freshness == "fresh"
            and name.value == context["file_name"]
        )

    def _stop_is_confirmed(self, printer_id):
        snapshot = self._snapshot(printer_id)
        state = snapshot.facts["state"]
        name = snapshot.facts["print.name"]
        nozzle_target = snapshot.facts["nozzle.target"]
        bed_target = snapshot.facts["bed.target"]
        return (
            state.freshness == "fresh"
            and str(state.value).lower() in {"idle", "stopped", "stop", "0", "4"}
            and name.freshness == "fresh"
            and not name.value
            and nozzle_target.freshness == "fresh"
            and float(nozzle_target.value) == 0
            and bed_target.freshness == "fresh"
            and float(bed_target.value) == 0
        )

    def _targets_are_confirmed(self, printer_id, context):
        snapshot = self._snapshot(printer_id)
        for target in context["targets"]:
            fact = snapshot.facts[target["path"]]
            try:
                matches = float(fact.value) == target["expected"]
            except (TypeError, ValueError):
                matches = False
            if (
                fact.freshness != "fresh"
                or fact.observed_at == target["baseline"]
                or not matches
            ):
                return False
        return True

    def _transition(self, prior, status, reason):
        outcome = ActionOutcome(
            prior.request_id,
            prior.printer_id,
            prior.action,
            status,
            reason,
            prior.accepted_at,
            self._clock(),
            prior.parameters,
        )
        self._record(outcome)
        return outcome

    def _rejected(self, request, reason, *, publish=True):
        outcome = ActionOutcome(
            request.request_id,
            request.printer_id,
            getattr(request.action, "kind", "unknown"),
            "rejected",
            reason,
            None,
            self._clock(),
            self._action_parameters(request.action),
        )
        if publish:
            self._requests[request.request_id] = (
                request.printer_id,
                asdict(request.action) if hasattr(request.action, "__dataclass_fields__") else {},
            )
            self._record(outcome)
        return outcome

    @staticmethod
    def _action_parameters(action):
        if not hasattr(action, "__dataclass_fields__"):
            return {}
        return {
            key: value
            for key, value in asdict(action).items()
            if key != "kind"
        }

    def _record(self, outcome):
        self._append_journal(outcome)
        self._records[outcome.request_id] = outcome
        self._snapshots.record_action(outcome.printer_id, outcome)

    def _append_journal(self, outcome):
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(outcome.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._journal_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _load_journal(self):
        if not self._journal_path.exists():
            return
        latest = {}
        with self._journal_path.open(encoding="utf-8") as handle:
            for line in handle:
                data = json.loads(line)
                latest[data["requestId"]] = data
        for data in latest.values():
            outcome = ActionOutcome(
                data["requestId"],
                data["printerId"],
                data["action"],
                data["status"],
                data.get("reason"),
                data.get("acceptedAt"),
                data["updatedAt"],
                data.get("parameters", {}),
            )
            self._requests[outcome.request_id] = (
                outcome.printer_id,
                {"kind": outcome.action, **(outcome.parameters or {})},
            )
            if outcome.status == "accepted":
                outcome = ActionOutcome(
                    outcome.request_id,
                    outcome.printer_id,
                    outcome.action,
                    "indeterminate",
                    "server_restarted_before_confirmation",
                    outcome.accepted_at,
                    self._clock(),
                    outcome.parameters,
                )
                self._append_journal(outcome)
            self._records[outcome.request_id] = outcome
            self._snapshots.record_action(outcome.printer_id, outcome)


def _run_in_background(work):
    Thread(target=work, daemon=True).start()


class MqttActionProtocol:
    """Production adapter for the true-external printer MQTT seam."""

    def __init__(self, app, *, reply_timeout=10.0):
        self._app = app
        self._reply_timeout = reply_timeout

    def protective_stop(self, printer_id):
        """Dispatch both Stop effects, then collect the exact 1008 reply.

        Waiting happens only after both effects have been sent.  The reply is
        diagnostic acknowledgement, never physical-action confirmation.
        """
        self._require_selected_printer(printer_id)
        with self._app.svc.borrow("mqttqueue") as mqtt:
            replies = Queue()
            with mqtt.tap(replies.put):
                mqtt.transport.command({"commandType": 1008, "value": 0})
                mqtt.transport.command({
                    "commandType": 0x0413,
                    "cmdData": "M2024",
                    "cmdLen": 5,
                })

                deadline = time.monotonic() + self._reply_timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    try:
                        reply = replies.get(timeout=remaining)
                    except Empty:
                        return None
                    if (
                        reply.get("commandType") == 1008
                        and "reply" in reply
                    ):
                        return reply

    def prepare_bed(self, printer_id, timeout):
        """Run the firmware's own bed-preparation routine to completion.

        G36 is sent out-of-band because the printer rejects it when embedded in
        uploaded G-code.  M400 queues behind it and supplies the terminal "ok"
        only once probing has finished.
        """
        self._require_selected_printer(printer_id)
        with self._app.svc.borrow("mqttqueue") as mqtt:
            replies = Queue()
            with mqtt.tap(replies.put):
                for line in ("G36", "M400"):
                    mqtt.transport.command(self._gcode_message(line))

                deadline = time.monotonic() + timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out preparing the print bed")
                    try:
                        reply = replies.get(timeout=remaining)
                    except Empty:
                        raise TimeoutError("Timed out preparing the print bed")
                    if reply.get("commandType") != 0x0413:
                        continue
                    response = str(reply.get("resData", "")).lower()
                    if any(
                        marker in response
                        for marker in ("error", "unknown", "failed")
                    ):
                        raise RuntimeError(f"Bed preparation failed: {response}")
                    if reply.get("reply") == 0 and "ok" in response:
                        return

    def mqtt(self, printer_id, message):
        self._require_selected_printer(printer_id)
        with self._app.svc.borrow("mqttqueue") as mqtt:
            return mqtt.transport.command(message)

    def gcode(self, printer_id, line):
        return self.mqtt(printer_id, self._gcode_message(line))

    @staticmethod
    def _gcode_message(line):
        return {"commandType": 0x0413, "cmdData": line, "cmdLen": len(line)}

    def _require_selected_printer(self, printer_id):
        selected = f"printer-{self._app.config['printer_index']}"
        if printer_id != selected:
            raise ValueError("printer is not selected")


class PpppTransferProtocol:
    """Production adapter for the true-external PPPP upload seam.

    One session holds the file-transfer service for the whole inseparable
    transfer-then-start sequence; the PPPP module keeps owning the transfer
    implementation behind it.
    """

    def __init__(self, app):
        self._app = app

    @contextmanager
    def session(self, printer_id):
        self._require_selected_printer(printer_id)
        with self._app.svc.borrow("filetransfer") as filetransfer:
            yield _PpppTransferSession(filetransfer)

    def _require_selected_printer(self, printer_id):
        selected = f"printer-{self._app.config['printer_index']}"
        if printer_id != selected:
            raise ValueError("printer is not selected")


class _PpppTransferSession:
    def __init__(self, filetransfer):
        self._filetransfer = filetransfer

    def transfer(self, stream, user_name):
        return self._filetransfer.transfer_file(stream, user_name)

    def start(self, transfer):
        self._filetransfer.start_job(transfer)
