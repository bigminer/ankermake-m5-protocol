import contextlib

from web.printer_actions import (
    ActionRequest,
    BedTarget,
    FanSetting,
    HeaterOff,
    MqttActionProtocol,
    NozzleTarget,
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


def test_temperature_targets_require_fresh_action_specific_facts(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe("printer-0", {"nozzle": {"current": 2000}})
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    nozzle = actions.submit(
        ActionRequest("nozzle-1", "printer-0", NozzleTarget(celsius=40))
    )
    bed = actions.submit(
        ActionRequest("bed-1", "printer-0", BedTarget(celsius=35))
    )

    assert nozzle.status == "accepted"
    assert bed.status == "rejected"
    assert bed.reason == "fresh_bed_temperature_required"
    assert protocol.effects == [("gcode", "printer-0", "M104 S40")]


def test_temperature_target_limits_are_server_owned(tmp_path):
    actions = PrinterActions(
        snapshots=PrinterSnapshots(clock=FakeClock()),
        protocol=RecordingProtocol(),
        journal_path=tmp_path / "actions.jsonl",
        clock=FakeClock(),
        validation_mode=True,
    )

    invalid = [
        NozzleTarget(celsius=0),
        NozzleTarget(celsius=301),
        NozzleTarget(celsius=40.5),
        BedTarget(celsius=0),
        BedTarget(celsius=101),
        BedTarget(celsius=True),
    ]

    for index, action in enumerate(invalid):
        outcome = actions.submit(ActionRequest(f"invalid-{index}", "printer-0", action))
        assert outcome.status == "rejected"
        assert outcome.reason == "invalid_action_parameters"


def test_new_temperature_target_supersedes_only_the_same_resource(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe(
        "printer-0",
        {"nozzle": {"current": 2000}, "bed": {"current": 2100}},
    )
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    actions.submit(
        ActionRequest("nozzle-40", "printer-0", NozzleTarget(celsius=40))
    )
    actions.submit(ActionRequest("bed-35", "printer-0", BedTarget(celsius=35)))
    actions.submit(
        ActionRequest("nozzle-50", "printer-0", NozzleTarget(celsius=50))
    )

    current = next(actions.watch(Watch("printer-0")))
    assert current.actions["nozzle-40"].status == "superseded"
    assert current.actions["nozzle-40"].reason == "newer_target_submitted"
    assert current.actions["bed-35"].status == "accepted"
    assert current.actions["nozzle-50"].status == "accepted"
    assert protocol.effects == [
        ("gcode", "printer-0", "M104 S40"),
        ("gcode", "printer-0", "M140 S35"),
        ("gcode", "printer-0", "M104 S50"),
    ]


def test_temperature_target_confirms_only_from_a_new_matching_observation(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe(
        "printer-0",
        {"nozzle": {"current": 3900, "target": 4000}},
    )
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=RecordingProtocol(),
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    actions.submit(
        ActionRequest("nozzle-40", "printer-0", NozzleTarget(celsius=40))
    )
    actions.tick()
    assert (
        next(actions.watch(Watch("printer-0"))).actions["nozzle-40"].status
        == "accepted"
    )

    clock.now += 1
    snapshots.observe("printer-0", {"nozzle": {"target": 4000}})
    actions.tick()

    assert (
        next(actions.watch(Watch("printer-0"))).actions["nozzle-40"].status
        == "confirmed"
    )


def test_protective_heater_off_bypasses_freshness_and_confirms_targets(tmp_path):
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

    accepted = actions.submit(
        ActionRequest("heaters-off", "printer-0", HeaterOff(heater="all"))
    )

    assert accepted.status == "accepted"
    assert protocol.effects == [
        ("gcode", "printer-0", "M104 S0"),
        ("gcode", "printer-0", "M140 S0"),
    ]

    clock.now += 1
    snapshots.observe(
        "printer-0",
        {"nozzle": {"target": 0}, "bed": {"target": 0}},
    )
    actions.tick()

    assert (
        next(actions.watch(Watch("printer-0"))).actions["heaters-off"].status
        == "confirmed"
    )


def test_fan_setting_requires_fresh_state_and_never_confirms_from_ack(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe("printer-0", {"state": "idle"})
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
        confirmation_timeout=30,
    )

    accepted = actions.submit(
        ActionRequest("fan-50", "printer-0", FanSetting(percent=50))
    )

    assert accepted.status == "accepted"
    assert protocol.effects == [("gcode", "printer-0", "M106 S128")]

    clock.now += 31
    actions.tick()

    outcome = next(actions.watch(Watch("printer-0"))).actions["fan-50"]
    assert outcome.status == "indeterminate"
    assert outcome.reason == "confirmation_unavailable"


def test_fan_setting_bounds_and_stale_state_are_rejected(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe("printer-0", {"state": "idle"})
    clock.now += 16
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    stale = actions.submit(
        ActionRequest("fan-stale", "printer-0", FanSetting(percent=50))
    )
    invalid = actions.submit(
        ActionRequest("fan-invalid", "printer-0", FanSetting(percent=101))
    )

    assert stale.status == "rejected"
    assert stale.reason == "fresh_printer_state_required"
    assert invalid.status == "rejected"
    assert invalid.reason == "invalid_action_parameters"
    assert protocol.effects == []


def test_parameterized_action_retry_survives_restart_without_replay(tmp_path):
    clock = FakeClock()
    journal = tmp_path / "actions.jsonl"
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe("printer-0", {"nozzle": {"current": 2000}})
    first_protocol = RecordingProtocol()
    first = PrinterActions(
        snapshots=snapshots,
        protocol=first_protocol,
        journal_path=journal,
        clock=clock,
        validation_mode=True,
    )
    request = ActionRequest("nozzle-40", "printer-0", NozzleTarget(celsius=40))
    first.submit(request)

    restarted_protocol = RecordingProtocol()
    restarted = PrinterActions(
        snapshots=PrinterSnapshots(clock=clock),
        protocol=restarted_protocol,
        journal_path=journal,
        clock=clock,
        validation_mode=True,
    )

    retry = restarted.submit(request)
    conflict = restarted.submit(
        ActionRequest("nozzle-40", "printer-0", NozzleTarget(celsius=45))
    )

    assert retry.status == "indeterminate"
    assert retry.reason == "server_restarted_before_confirmation"
    assert conflict.status == "rejected"
    assert conflict.reason == "request_identity_conflict"
    assert restarted_protocol.effects == []


def test_obsolete_validation_evidence_does_not_ungate_changed_contract(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    snapshots.observe("printer-0", {"nozzle": {"current": 2000}})
    protocol = RecordingProtocol()
    actions = PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=False,
        validated_contracts={"nozzle_target": "obsolete-contract"},
    )

    outcome = actions.submit(
        ActionRequest("nozzle-40", "printer-0", NozzleTarget(celsius=40))
    )

    assert outcome.status == "rejected"
    assert outcome.reason == "supervised_validation_required"
    assert protocol.effects == []
