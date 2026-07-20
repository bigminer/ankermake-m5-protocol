import contextlib

from web.printer_actions import (
    ActionRequest,
    MqttActionProtocol,
    Pause,
    PrinterActions,
    Resume,
    Stop,
)
from web.printer_snapshot import PrinterSnapshots, Watch


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class RecordingProtocol:
    def __init__(self):
        self.effects = []

    def mqtt(self, printer_id, message):
        self.effects.append(("mqtt", printer_id, message))
        return {"reply": 0}

    def gcode(self, printer_id, line):
        self.effects.append(("gcode", printer_id, line))
        return {"reply": 0}

    def protective_stop(self, printer_id):
        self.mqtt(printer_id, {"commandType": 1008, "value": 0})
        self.gcode(printer_id, "M2024")
        return {"commandType": 1008, "reply": 0}


def test_stop_reply_without_a_job_transition_becomes_indeterminate(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe(
        "printer-0",
        {"state": "printing", "print": {"name": "job.gcode", "progress": 4900}},
    )
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
        confirmation_timeout=30,
    )
    watcher = actions.watch(Watch(printer_id="printer-0"))
    next(watcher)

    accepted = actions.submit(ActionRequest("stop-1", "printer-0", Stop()))

    assert accepted.status == "accepted"
    assert protocol.effects == [
        ("mqtt", "printer-0", {"commandType": 1008, "value": 0}),
        ("gcode", "printer-0", "M2024"),
    ]
    assert next(watcher).actions["stop-1"].status == "accepted"

    snapshots.observe(
        "printer-0",
        {"state": "printing", "print": {"name": "job.gcode", "progress": 5300}},
    )
    clock.now += 31
    actions.tick()

    outcome = next(watcher)
    if outcome.actions["stop-1"].status == "accepted":
        outcome = next(watcher)
    assert outcome.actions["stop-1"].status == "indeterminate"
    assert outcome.actions["stop-1"].reason == "confirmation_timeout"


def test_stop_nonzero_print_control_reply_is_immediately_indeterminate(tmp_path):
    class RejectingProtocol(RecordingProtocol):
        def protective_stop(self, printer_id):
            self.mqtt(printer_id, {"commandType": 1008, "value": 0})
            self.gcode(printer_id, "M2024")
            return {"commandType": 1008, "reply": 7}

    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe(
        "printer-0", {"state": "printing", "print": {"name": "job.gcode"}}
    )
    protocol = RejectingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    outcome = actions.submit(ActionRequest("stop-1", "printer-0", Stop()))

    assert outcome.status == "indeterminate"
    assert outcome.reason == "print_control_rejected"
    assert protocol.effects == [
        ("mqtt", "printer-0", {"commandType": 1008, "value": 0}),
        ("gcode", "printer-0", "M2024"),
    ]


def test_pause_uses_trusted_orca_identity_and_confirms_the_same_job(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.remember_job(
        "printer-0", "job.gcode", "OrcaSlicer", "slicer_upload"
    )
    snapshots.observe(
        "printer-0",
        {"state": "printing", "print": {"name": "job.gcode", "progress": 1800}},
    )
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    accepted = actions.submit(ActionRequest("pause-1", "printer-0", Pause()))

    assert accepted.status == "accepted"
    assert protocol.effects == [
        (
            "mqtt",
            "printer-0",
            {
                "commandType": 1008,
                "value": 1,
                "userName": "OrcaSlicer",
                "filePath": "job.gcode",
            },
        ),
    ]

    snapshots.observe(
        "printer-0",
        {"state": "paused", "print": {"name": "job.gcode", "progress": 1800}},
    )
    actions.tick()

    current = next(actions.watch(Watch("printer-0")))
    assert current.actions["pause-1"].status == "confirmed"


def test_pause_rejects_unknown_job_identity_without_protocol_effects(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe(
        "printer-0",
        {"state": "printing", "print": {"name": "unknown.gcode"}},
    )
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    outcome = actions.submit(ActionRequest("pause-1", "printer-0", Pause()))

    assert outcome.status == "rejected"
    assert outcome.reason == "supported_job_identity_required"
    assert protocol.effects == []


def test_stop_confirms_only_after_the_job_is_observed_cleared(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe("printer-0", {
        "state": "printing",
        "print": {"name": "job.gcode"},
        "nozzle": {"target": 21500},
        "bed": {"target": 6000},
    })
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=RecordingProtocol(),
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )
    actions.submit(ActionRequest("stop-1", "printer-0", Stop()))

    snapshots.observe("printer-0", {"state": "idle", "print": {"name": ""}})
    actions.tick()

    current = next(actions.watch(Watch("printer-0")))
    assert current.actions["stop-1"].status == "accepted"

    snapshots.observe(
        "printer-0", {"nozzle": {"target": 0}, "bed": {"target": 0}}
    )
    actions.tick()

    current = next(actions.watch(Watch("printer-0")))
    assert current.actions["stop-1"].status == "confirmed"


def test_identical_retry_deduplicates_and_conflicting_reuse_is_rejected(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )
    request = ActionRequest("stop-1", "printer-0", Stop())

    first = actions.submit(request)
    retry = actions.submit(request)
    conflict = actions.submit(ActionRequest("stop-1", "printer-1", Stop()))

    assert retry == first
    assert len(protocol.effects) == 2
    assert conflict.status == "rejected"
    assert conflict.reason == "request_identity_conflict"


def test_restart_never_replays_and_marks_unresolved_action_indeterminate(tmp_path):
    clock = FakeClock()
    journal = tmp_path / "actions.jsonl"
    first_protocol = RecordingProtocol()
    first = PrinterActions(
        snapshots=PrinterSnapshots(clock=clock),
        protocol=first_protocol,
        journal_path=journal,
        clock=clock,
        validation_mode=True,
    )
    first.submit(ActionRequest("stop-1", "printer-0", Stop()))
    assert len(first_protocol.effects) == 2

    restarted_protocol = RecordingProtocol()
    restarted = PrinterActions(
        snapshots=PrinterSnapshots(clock=clock),
        protocol=restarted_protocol,
        journal_path=journal,
        clock=clock,
        validation_mode=True,
    )

    current = next(restarted.watch(Watch("printer-0")))
    assert restarted_protocol.effects == []
    assert current.actions["stop-1"].status == "indeterminate"
    assert current.actions["stop-1"].reason == "server_restarted_before_confirmation"


def test_resume_requires_paused_same_job_and_confirms_printing_transition(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.remember_job(
        "printer-0", "job.gcode", "OrcaSlicer", "slicer_upload"
    )
    snapshots.observe(
        "printer-0", {"state": "paused", "print": {"name": "job.gcode"}}
    )
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    accepted = actions.submit(ActionRequest("resume-1", "printer-0", Resume()))

    assert accepted.status == "accepted"
    assert protocol.effects == [
        (
            "mqtt",
            "printer-0",
            {
                "commandType": 1008,
                "value": 2,
                "userName": "OrcaSlicer",
                "filePath": "job.gcode",
            },
        ),
    ]

    snapshots.observe(
        "printer-0", {"state": "printing", "print": {"name": "job.gcode"}}
    )
    actions.tick()

    current = next(actions.watch(Watch("printer-0")))
    assert current.actions["resume-1"].status == "confirmed"


def test_contradictory_job_action_is_rejected_while_pause_is_unresolved(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.remember_job(
        "printer-0", "job.gcode", "OrcaSlicer", "slicer_upload"
    )
    snapshots.observe(
        "printer-0", {"state": "printing", "print": {"name": "job.gcode"}}
    )
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=RecordingProtocol(),
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )
    actions.submit(ActionRequest("pause-1", "printer-0", Pause()))
    snapshots.observe(
        "printer-0", {"state": "paused", "print": {"name": "job.gcode"}}
    )

    outcome = actions.submit(ActionRequest("resume-1", "printer-0", Resume()))

    assert outcome.status == "rejected"
    assert outcome.reason == "conflicting_job_action_pending"


def test_protective_stop_supersedes_an_unresolved_pause(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.remember_job(
        "printer-0", "job.gcode", "OrcaSlicer", "slicer_upload"
    )
    snapshots.observe(
        "printer-0", {"state": "printing", "print": {"name": "job.gcode"}}
    )
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )
    actions.submit(ActionRequest("pause-1", "printer-0", Pause()))

    stop = actions.submit(ActionRequest("stop-1", "printer-0", Stop()))

    current = next(actions.watch(Watch("printer-0")))
    assert stop.status == "accepted"
    assert current.actions["pause-1"].status == "superseded"
    assert current.actions["pause-1"].reason == "protective_stop_submitted"
    assert [effect[0] for effect in protocol.effects] == ["mqtt", "mqtt", "gcode"]


def test_stop_is_global_even_when_trusted_job_identity_is_available(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.remember_job(
        "printer-0", "job.gcode", "OrcaSlicer", "slicer_upload"
    )
    snapshots.observe(
        "printer-0", {"state": "printing", "print": {"name": "job.gcode"}}
    )
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    actions.submit(ActionRequest("stop-1", "printer-0", Stop()))

    assert protocol.effects == [
        (
            "mqtt",
            "printer-0",
            {"commandType": 1008, "value": 0},
        ),
        ("gcode", "printer-0", "M2024"),
    ]


def test_protective_stop_dispatches_both_effects_before_waiting_for_exact_reply():
    handlers = []

    class Transport:
        def __init__(self):
            self.commands = []

        def command(self, message):
            self.commands.append(message)
            if message.get("cmdData") == "M2024":
                for handler in handlers:
                    handler({"commandType": 1003, "reply": 0})
                    handler({"commandType": 1008, "reply": 0})

    class MqttService:
        transport = Transport()

        @contextlib.contextmanager
        def tap(self, handler):
            handlers.append(handler)
            try:
                yield self
            finally:
                handlers.remove(handler)

    class Services:
        @contextlib.contextmanager
        def borrow(self, name):
            assert name == "mqttqueue"
            yield MqttService()

    class App:
        config = {"printer_index": 0}
        svc = Services()

    reply = MqttActionProtocol(App()).protective_stop("printer-0")

    assert MqttService.transport.commands == [
        {"commandType": 1008, "value": 0},
        {"commandType": 0x0413, "cmdData": "M2024", "cmdLen": 5},
    ]
    assert reply == {"commandType": 1008, "reply": 0}
