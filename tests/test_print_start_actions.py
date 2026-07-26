"""Offline coverage for the upload / preparation / print-start Compound action.

Every test drives ``PrinterActions.submit`` and ``watch`` against strict
transport fakes, a fake clock, and a temporary journal.  No printer is
contacted and no test may depend on wall-clock time.
"""

import contextlib
import io
import json
import threading
import time

import pytest

from web.printer_actions import (
    ActionRequest,
    NozzleTarget,
    PrintStart,
    PrinterActions,
    Stop,
)
from web.printer_artifacts import ArtifactStore
from web.printer_snapshot import PrinterSnapshots, Watch


PREPARED_GCODE = b"M190 S55\nM109 S220\nG1 X10 Y10\n"


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class RecordingProtocol:
    """Strict fake for the true-external printer MQTT seam."""

    def __init__(self, effects=None, prepare_bed_error=None):
        self.effects = [] if effects is None else effects
        self.prepare_bed_error = prepare_bed_error

    def mqtt(self, printer_id, message):
        self.effects.append(("mqtt", printer_id, message))
        return {"reply": 0}

    def gcode(self, printer_id, line):
        self.effects.append(("gcode", printer_id, line))
        return {"reply": 0}

    def prepare_bed(self, printer_id, timeout):
        self.effects.append(("prepare_bed", printer_id))
        if self.prepare_bed_error is not None:
            raise self.prepare_bed_error

    def protective_stop(self, printer_id):
        self.mqtt(printer_id, {"commandType": 1008, "value": 0})
        self.gcode(printer_id, "M2024")
        return {"commandType": 1008, "reply": 0}


class RecordingTransfers:
    """Strict fake for the true-external PPPP upload seam."""

    def __init__(self, effects=None, transfer_error=None, start_error=None):
        self.effects = [] if effects is None else effects
        self.transfer_error = transfer_error
        self.start_error = start_error
        self.transferred = None
        self.before_transfer = None

    @contextlib.contextmanager
    def session(self, printer_id):
        self.effects.append(("transfer_open", printer_id))
        try:
            yield _RecordingSession(self, printer_id)
        finally:
            self.effects.append(("transfer_close", printer_id))


class _RecordingSession:
    def __init__(self, transfers, printer_id):
        self._transfers = transfers
        self._printer_id = printer_id

    def transfer(self, stream, user_name):
        if self._transfers.before_transfer is not None:
            self._transfers.before_transfer()
        self._transfers.transferred = (stream.filename, stream.read(), user_name)
        self._transfers.effects.append(
            ("transfer", self._printer_id, stream.filename)
        )
        if self._transfers.transfer_error is not None:
            raise self._transfers.transfer_error
        return "transfer-handle"

    def start(self, handle):
        self._transfers.effects.append(("start", self._printer_id, handle))
        if self._transfers.start_error is not None:
            raise self._transfers.start_error


class Preheating:
    """A sleep fake: advances the clock and lets the printer reach targets."""

    def __init__(self, clock, snapshots, schedule=()):
        self.clock = clock
        self.snapshots = snapshots
        self.schedule = list(schedule)
        self.calls = 0

    def __call__(self, seconds):
        self.calls += 1
        self.clock.now += seconds
        if self.schedule:
            self.snapshots.observe("printer-0", self.schedule.pop(0))


def stage(store, data=PREPARED_GCODE, filename="cube.gcode", prepare=True):
    stream = io.BytesIO(data)
    stream.filename = filename
    return store.stage(
        stream,
        user_name="OrcaSlicer",
        origin="slicer_upload",
        extract_temperatures=prepare,
    )


def idle_printer(snapshots):
    snapshots.observe(
        "printer-0",
        {
            "state": "idle",
            "nozzle": {"current": 2500, "target": 0},
            "bed": {"current": 2400, "target": 0},
        },
    )


def build(
    tmp_path, clock, snapshots, *, protocol, transfers, sleep=None,
    run_async=lambda work: work(), **kwargs,
):
    return PrinterActions(
        snapshots=snapshots,
        protocol=protocol,
        artifacts=ArtifactStore(tmp_path / "staging"),
        transfers=transfers,
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        sleep=sleep or (lambda seconds: None),
        run_async=run_async,
        validation_mode=True,
        **kwargs,
    )


@pytest.fixture
def world(tmp_path):
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock)
    effects = []
    protocol = RecordingProtocol(effects)
    transfers = RecordingTransfers(effects)
    idle_printer(snapshots)
    return {
        "tmp_path": tmp_path,
        "clock": clock,
        "snapshots": snapshots,
        "effects": effects,
        "protocol": protocol,
        "transfers": transfers,
    }


def test_prepared_print_runs_the_compound_sequence_in_order(world):
    clock, snapshots = world["clock"], world["snapshots"]
    sleep = Preheating(clock, snapshots, schedule=[
        {"bed": {"current": 5500}},
        {"nozzle": {"current": 22000}},
    ])
    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"], sleep=sleep,
    )
    artifact = stage(actions.artifacts)

    accepted = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))
    )

    assert accepted.status == "accepted"
    assert world["effects"] == [
        ("gcode", "printer-0", "M104 S150"),
        ("gcode", "printer-0", "M140 S55"),
        ("gcode", "printer-0", "M104 S220"),
        ("prepare_bed", "printer-0"),
        ("transfer_open", "printer-0"),
        ("transfer", "printer-0", "cube.gcode"),
        ("start", "printer-0", "transfer-handle"),
        ("transfer_close", "printer-0"),
    ]
    assert world["transfers"].transferred == (
        "cube.gcode", PREPARED_GCODE, "OrcaSlicer",
    )


def test_unprepared_print_transfers_and_starts_without_heating(world):
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)

    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)))

    assert world["effects"] == [
        ("transfer_open", "printer-0"),
        ("transfer", "printer-0", "model.acode"),
        ("start", "printer-0", "transfer-handle"),
        ("transfer_close", "printer-0"),
    ]


def test_print_start_confirms_from_observed_job_state(world):
    clock, snapshots = world["clock"], world["snapshots"]
    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)
    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)))

    assert next(actions.watch(Watch("printer-0"))).actions["print-1"].reason == (
        "awaiting_confirmation"
    )

    snapshots.observe(
        "printer-0", {"state": "printing", "print": {"name": "model.acode"}}
    )
    actions.tick()

    current = next(actions.watch(Watch("printer-0")))
    assert current.actions["print-1"].status == "confirmed"
    # The trusted upload identity is what Pause and Resume later need.
    assert current.facts["print.user_name"].value == "OrcaSlicer"
    assert current.facts["print.origin"].value == "slicer_upload"


def test_unconfirmed_print_start_becomes_indeterminate(world):
    clock, snapshots = world["clock"], world["snapshots"]
    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"],
        confirmation_timeout=30,
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)
    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)))

    clock.now += 31
    actions.tick()

    current = next(actions.watch(Watch("printer-0")))
    assert current.actions["print-1"].status == "indeterminate"
    assert current.actions["print-1"].reason == "confirmation_timeout"


@pytest.mark.parametrize(
    "observation, reason",
    [
        ({}, "fresh_printer_state_required"),
        ({"state": "printing"}, "idle_printer_required"),
    ],
)
def test_policy_rejects_before_any_physical_effect(world, observation, reason):
    clock, snapshots = world["clock"], world["snapshots"]
    if observation:
        snapshots.observe("printer-0", observation)
    else:
        clock.now += 60  # every fact goes stale
    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts)

    outcome = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))
    )

    assert outcome.status == "rejected"
    assert outcome.reason == reason
    assert world["effects"] == []
    # A rejected request never consumes the artifact, so the caller may retry.
    assert actions.artifacts.get(artifact.reference) is not None


def test_policy_rejects_an_unknown_or_already_consumed_artifact(world):
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)
    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)))
    world["effects"].clear()

    outcome = actions.submit(
        ActionRequest("print-2", "printer-0", PrintStart(artifact.reference))
    )

    assert outcome.status == "rejected"
    assert outcome.reason == "unknown_staged_artifact"
    assert world["effects"] == []

    missing = actions.submit(ActionRequest("print-3", "printer-0", PrintStart("")))
    assert missing.reason == "invalid_action_parameters"


def test_policy_rejects_unsupported_preparation_temperatures(world):
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"M190 S55\nM109 S500\n")

    outcome = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))
    )

    assert outcome.status == "rejected"
    assert outcome.reason == "unsupported_preparation_temperatures"
    assert world["effects"] == []


def test_preparation_timeout_cleans_up_and_reports_indeterminate(world):
    clock, snapshots = world["clock"], world["snapshots"]
    sleep = Preheating(clock, snapshots)  # the bed never reaches its target
    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"], sleep=sleep,
        preparation_timeout=60,
    )
    artifact = stage(actions.artifacts)

    outcome = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))
    )

    assert outcome.status == "indeterminate"
    assert outcome.reason == "preparation_timeout"
    assert world["effects"][-2:] == [
        ("gcode", "printer-0", "M104 S0"),
        ("gcode", "printer-0", "M140 S0"),
    ]
    assert ("transfer_open", "printer-0") not in world["effects"]
    assert actions.artifacts.get(artifact.reference) is None


def test_failed_preparation_routine_cleans_up_before_transfer(world):
    clock, snapshots = world["clock"], world["snapshots"]
    world["protocol"].prepare_bed_error = RuntimeError("probe failed")
    sleep = Preheating(clock, snapshots, schedule=[
        {"bed": {"current": 5500}},
        {"nozzle": {"current": 22000}},
    ])
    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"], sleep=sleep,
    )
    artifact = stage(actions.artifacts)

    outcome = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))
    )

    assert outcome.status == "indeterminate"
    assert outcome.reason == "preparation_failed"
    assert ("transfer_open", "printer-0") not in world["effects"]
    assert world["effects"][-2:] == [
        ("gcode", "printer-0", "M104 S0"),
        ("gcode", "printer-0", "M140 S0"),
    ]
    assert actions.artifacts.get(artifact.reference) is None


def test_disconnect_during_transfer_is_indeterminate_and_cleans_up(world):
    world["transfers"].transfer_error = ConnectionError("pppp connection lost")
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)

    outcome = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))
    )

    assert outcome.status == "indeterminate"
    assert outcome.reason == "transfer_failed"
    assert ("start", "printer-0", "transfer-handle") not in world["effects"]
    assert actions.artifacts.get(artifact.reference) is None


def test_failed_start_submission_is_indeterminate(world):
    world["transfers"].start_error = ConnectionError("printer rejected print job")
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)

    outcome = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))
    )

    assert outcome.status == "indeterminate"
    assert outcome.reason == "transfer_failed"
    assert actions.artifacts.get(artifact.reference) is None


def test_protective_stop_cancels_a_preparing_print_and_cleans_up(world):
    clock, snapshots = world["clock"], world["snapshots"]
    running = {}

    def stop_during_preparation(seconds):
        clock.now += seconds
        running["actions"].submit(ActionRequest("stop-1", "printer-0", Stop()))

    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"],
        sleep=stop_during_preparation,
    )
    running["actions"] = actions
    artifact = stage(actions.artifacts)

    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)))

    current = next(actions.watch(Watch("printer-0")))
    assert current.actions["print-1"].status == "superseded"
    assert current.actions["print-1"].reason == "protective_stop_submitted"
    assert ("transfer_open", "printer-0") not in world["effects"]
    assert actions.artifacts.get(artifact.reference) is None


def test_a_stop_during_transfer_keeps_the_superseded_outcome(world):
    # Stop marks the print superseded before it queues behind the transfer
    # lock, so the completing transfer must not report itself as still pending.
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)

    inside_transfer = threading.Event()
    release_transfer = threading.Event()
    world["transfers"].before_transfer = lambda: (
        inside_transfer.set(), release_transfer.wait(2)
    )

    printing = threading.Thread(
        target=actions.submit,
        args=(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)),),
    )
    printing.start()
    assert inside_transfer.wait(2)

    stopping = threading.Thread(
        target=actions.submit,
        args=(ActionRequest("stop-1", "printer-0", Stop()),),
    )
    stopping.start()
    assert _wait_for_status(actions, "print-1", "superseded")

    release_transfer.set()
    printing.join(2)
    stopping.join(2)

    current = next(actions.watch(Watch("printer-0"))).actions
    assert current["print-1"].status == "superseded"
    assert current["print-1"].reason == "protective_stop_submitted"
    assert actions.artifacts.get(artifact.reference) is None


def _wait_for_status(actions, request_id, status, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = next(actions.watch(Watch("printer-0"))).actions.get(request_id)
        if record is not None and record.status == status:
            return True
        time.sleep(0.01)
    return False


def test_a_second_print_start_is_rejected_while_one_is_unresolved(world):
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    first = stage(actions.artifacts, b"one", "one.acode", prepare=False)
    second = stage(actions.artifacts, b"two", "two.acode", prepare=False)
    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(first.reference)))
    world["effects"].clear()

    outcome = actions.submit(
        ActionRequest("print-2", "printer-0", PrintStart(second.reference))
    )

    assert outcome.status == "rejected"
    assert outcome.reason == "conflicting_job_action_pending"
    assert world["effects"] == []


def test_identical_retry_is_deduplicated_and_mismatched_reuse_rejected(world):
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)
    request = ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))

    first = actions.submit(request)
    retry = actions.submit(request)
    other = stage(actions.artifacts, b"other", "other.acode", prepare=False)
    conflict = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(other.reference))
    )

    assert retry == first
    assert world["effects"].count(("start", "printer-0", "transfer-handle")) == 1
    assert conflict.status == "rejected"
    assert conflict.reason == "request_identity_conflict"


def test_restart_never_replays_an_unresolved_print_start(world):
    tmp_path, clock, snapshots = world["tmp_path"], world["clock"], world["snapshots"]
    actions = build(
        tmp_path, clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)
    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)))

    restarted_effects = []
    restarted = PrinterActions(
        snapshots=PrinterSnapshots(clock=clock),
        protocol=RecordingProtocol(restarted_effects),
        transfers=RecordingTransfers(restarted_effects),
        artifacts=ArtifactStore(tmp_path / "staging"),
        journal_path=tmp_path / "actions.jsonl",
        clock=clock,
        validation_mode=True,
    )

    current = next(restarted.watch(Watch("printer-0")))
    assert restarted_effects == []
    assert current.actions["print-1"].status == "indeterminate"
    assert current.actions["print-1"].reason == "server_restarted_before_confirmation"


def test_a_reconnecting_watcher_resumes_print_start_transitions_from_a_cursor(world):
    clock, snapshots = world["clock"], world["snapshots"]
    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)
    cursor = next(actions.watch(Watch("printer-0"))).cursor

    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)))
    snapshots.observe(
        "printer-0", {"state": "printing", "print": {"name": "model.acode"}}
    )
    actions.tick()

    reconnected = actions.watch(Watch("printer-0", cursor))
    statuses = []
    while not statuses or statuses[-1] != "confirmed":
        snapshot = next(reconnected)
        if "print-1" in snapshot.actions:
            statuses.append(snapshot.actions["print-1"].status)

    assert statuses[0] == "accepted"
    assert statuses[-1] == "confirmed"


def test_the_journal_records_only_the_opaque_reference(world):
    actions = build(
        world["tmp_path"], world["clock"], world["snapshots"],
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(
        actions.artifacts,
        b"G1 X1 ; secret geometry\n",
        r"C:\Users\someone\Desktop\confidential part.acode",
        prepare=False,
    )
    actions.submit(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)))

    journal = (world["tmp_path"] / "actions.jsonl").read_text()

    assert artifact.reference in journal
    for leaked in ("confidential", "someone", "Desktop", "secret geometry", "acode"):
        assert leaked not in journal
    for entry in journal.splitlines():
        assert json.loads(entry)["parameters"] == {"artifact": artifact.reference}


def test_print_start_is_gated_until_its_contract_is_validated(world):
    actions = PrinterActions(
        snapshots=world["snapshots"],
        protocol=world["protocol"],
        transfers=world["transfers"],
        artifacts=ArtifactStore(world["tmp_path"] / "staging"),
        journal_path=world["tmp_path"] / "actions.jsonl",
        clock=world["clock"],
        run_async=lambda work: work(),
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)

    outcome = actions.submit(
        ActionRequest("print-1", "printer-0", PrintStart(artifact.reference))
    )

    assert outcome.status == "rejected"
    assert outcome.reason == "supervised_validation_required"
    assert world["effects"] == []
    assert not actions.is_enabled("print_start")


def test_unrelated_actions_do_not_interleave_with_transfer_and_start(world):
    clock, snapshots = world["clock"], world["snapshots"]
    actions = build(
        world["tmp_path"], clock, snapshots,
        protocol=world["protocol"], transfers=world["transfers"],
    )
    artifact = stage(actions.artifacts, b"binary acode", "model.acode", prepare=False)

    inside_transfer = threading.Event()
    release_transfer = threading.Event()
    world["transfers"].before_transfer = lambda: (
        inside_transfer.set(), release_transfer.wait(2)
    )

    printing = threading.Thread(
        target=actions.submit,
        args=(ActionRequest("print-1", "printer-0", PrintStart(artifact.reference)),),
    )
    printing.start()
    assert inside_transfer.wait(2)

    heating = threading.Thread(
        target=actions.submit,
        args=(ActionRequest("nozzle-1", "printer-0", NozzleTarget(celsius=200)),),
    )
    heating.start()
    heating.join(0.2)
    assert heating.is_alive(), "an unrelated action entered the transfer boundary"
    assert ("gcode", "printer-0", "M104 S200") not in world["effects"]

    release_transfer.set()
    printing.join(2)
    heating.join(2)

    assert world["effects"].index(("gcode", "printer-0", "M104 S200")) > world[
        "effects"
    ].index(("start", "printer-0", "transfer-handle"))
