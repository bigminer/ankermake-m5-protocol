"""Typed, server-owned Printer actions.

Stop, Pause, and Resume keep their protocol details, sequencing, journal, and
confirmation policy private behind ``submit`` and ``watch``.
"""

from dataclasses import asdict, dataclass
import json
import logging as log
import os
from pathlib import Path
from queue import Empty, Queue
from threading import Lock
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

    def to_dict(self):
        return {
            "requestId": self.request_id,
            "printerId": self.printer_id,
            "action": self.action,
            "status": self.status,
            "reason": self.reason,
            "acceptedAt": self.accepted_at,
            "updatedAt": self.updated_at,
        }


class PrinterActions:
    """Deep Printer-action module with the ``submit`` / ``watch`` interface."""

    def __init__(
        self,
        *,
        snapshots,
        protocol,
        journal_path,
        clock=time.time,
        validation_mode=False,
        confirmation_timeout=30.0,
    ):
        self._snapshots = snapshots
        self._protocol = protocol
        self._journal_path = Path(journal_path)
        self._clock = clock
        self._validation_mode = validation_mode
        self._confirmation_timeout = confirmation_timeout
        self._records = {}
        self._requests = {}
        self._deadlines = {}
        self._contexts = {}
        self._locks = {}
        self._load_journal()

    def watch(self, watch):
        return self._snapshots.watch(watch)

    def submit(self, request):
        if not isinstance(request.action, (Stop, Pause, Resume)):
            return self._rejected(request, "unsupported_action")

        canonical = (request.printer_id, asdict(request.action))
        existing = self._records.get(request.request_id)
        if existing is not None:
            if self._requests[request.request_id] == canonical:
                return existing
            return self._rejected(request, "request_identity_conflict", publish=False)

        if not self._validation_mode:
            return self._rejected(request, "supervised_validation_required")

        if isinstance(request.action, (Pause, Resume)) and any(
            self._records[pending_id].printer_id == request.printer_id
            and self._records[pending_id].action in {"pause", "resume"}
            for pending_id in self._deadlines
        ):
            return self._rejected(request, "conflicting_job_action_pending")

        if isinstance(request.action, Stop):
            for pending_id in list(self._deadlines):
                pending = self._records[pending_id]
                if (
                    pending.printer_id == request.printer_id
                    and pending.action in {"pause", "resume"}
                ):
                    self._transition(
                        pending, "superseded", "protective_stop_submitted"
                    )
                    del self._deadlines[pending_id]
                    self._contexts.pop(pending_id, None)

        context = {}
        if isinstance(request.action, (Pause, Resume)):
            required_states = (
                {"printing", "1"}
                if isinstance(request.action, Pause)
                else {"paused", "pause", "2"}
            )
            context = self._fresh_job_identity(request.printer_id, required_states)
            if context.get("error"):
                return self._rejected(request, context["error"])

        now = self._clock()
        accepted = ActionOutcome(
            request.request_id,
            request.printer_id,
            request.action.kind,
            "accepted",
            None,
            now,
            now,
        )
        self._requests[request.request_id] = canonical
        self._record(accepted)

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
                else:
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
        except Exception:
            return self._transition(accepted, "indeterminate", "protocol_submission_uncertain")

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
            else:
                confirmed = self._job_state_is_confirmed(
                    record.printer_id, self._contexts[request_id], {"printing", "1"}
                )
            if confirmed:
                self._transition(record, "confirmed", None)
                del self._deadlines[request_id]
                self._contexts.pop(request_id, None)
            elif now >= deadline:
                self._transition(record, "indeterminate", "confirmation_timeout")
                del self._deadlines[request_id]
                self._contexts.pop(request_id, None)

    def _fresh_job_identity(self, printer_id, required_states):
        from .printer_snapshot import Watch

        snapshot = next(self._snapshots.watch(Watch(printer_id)))
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
        from .printer_snapshot import Watch

        snapshot = next(self._snapshots.watch(Watch(printer_id)))
        state = snapshot.facts["state"]
        name = snapshot.facts["print.name"]
        return (
            state.freshness == "fresh"
            and str(state.value).lower() in expected_states
            and name.freshness == "fresh"
            and name.value == context["file_name"]
        )

    def _stop_is_confirmed(self, printer_id):
        from .printer_snapshot import Watch

        snapshot = next(self._snapshots.watch(Watch(printer_id)))
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

    def _transition(self, prior, status, reason):
        outcome = ActionOutcome(
            prior.request_id,
            prior.printer_id,
            prior.action,
            status,
            reason,
            prior.accepted_at,
            self._clock(),
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
        )
        if publish:
            self._requests[request.request_id] = (
                request.printer_id,
                asdict(request.action) if hasattr(request.action, "__dataclass_fields__") else {},
            )
            self._record(outcome)
        return outcome

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
            )
            self._requests[outcome.request_id] = (outcome.printer_id, {"kind": outcome.action})
            if outcome.status == "accepted":
                outcome = ActionOutcome(
                    outcome.request_id,
                    outcome.printer_id,
                    outcome.action,
                    "indeterminate",
                    "server_restarted_before_confirmation",
                    outcome.accepted_at,
                    self._clock(),
                )
                self._append_journal(outcome)
            self._records[outcome.request_id] = outcome
            self._snapshots.record_action(outcome.printer_id, outcome)


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

    def mqtt(self, printer_id, message):
        self._require_selected_printer(printer_id)
        with self._app.svc.borrow("mqttqueue") as mqtt:
            return mqtt.transport.command(message)

    def gcode(self, printer_id, line):
        return self.mqtt(printer_id, {
            "commandType": 0x0413,
            "cmdData": line,
            "cmdLen": len(line),
        })

    def _require_selected_printer(self, printer_id):
        selected = f"printer-{self._app.config['printer_index']}"
        if printer_id != selected:
            raise ValueError("printer is not selected")
