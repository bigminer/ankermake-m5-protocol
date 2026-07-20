import pytest

from web.printer_snapshot import CursorExpired, PrinterSnapshots, Watch


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def test_watch_delivers_current_snapshot_then_monotonic_updates():
    snapshots = PrinterSnapshots(clock=FakeClock())
    watcher = snapshots.watch(Watch(printer_id="printer-0"))

    initial = next(watcher)
    assert initial.cursor == 0
    assert initial.printer_id == "printer-0"
    assert initial.facts["print.name"].freshness == "unknown"

    snapshots.observe(
        "printer-0",
        {
            "state": "printing",
            "print": {"name": "job.gcode", "progress": 1200},
        },
    )

    update = next(watcher)
    assert update.cursor == 1
    assert update.facts["state"].value == "printing"
    assert update.facts["state"].freshness == "fresh"
    assert update.facts["print.name"].value == "job.gcode"
    assert update.facts["print.progress"].value == 1200


def test_each_fact_expires_independently_and_emits_a_snapshot_update():
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock, fresh_for=15)
    watcher = snapshots.watch(Watch(printer_id="printer-0"))
    next(watcher)

    snapshots.observe("printer-0", {"state": "printing"})
    state_update = next(watcher)
    assert state_update.facts["state"].freshness == "fresh"
    assert state_update.facts["nozzle.current"].freshness == "unknown"

    clock.now += 10
    snapshots.observe("printer-0", {"nozzle": {"current": 22000}})
    temperature_update = next(watcher)
    assert temperature_update.facts["state"].freshness == "fresh"
    assert temperature_update.facts["nozzle.current"].freshness == "fresh"

    clock.now += 6
    snapshots.tick()
    stale_update = next(watcher)
    assert stale_update.cursor == temperature_update.cursor + 1
    assert stale_update.facts["state"].freshness == "stale"
    assert stale_update.facts["nozzle.current"].freshness == "fresh"


def test_watch_resumes_without_gaps_or_duplicate_logical_updates():
    snapshots = PrinterSnapshots(clock=FakeClock())
    snapshots.observe("printer-0", {"print": {"progress": 100}})
    snapshots.observe("printer-0", {"print": {"progress": 200}})
    snapshots.observe("printer-0", {"print": {"progress": 300}})

    watcher = snapshots.watch(Watch(printer_id="printer-0", cursor=1))

    assert [next(watcher).cursor, next(watcher).cursor] == [2, 3]


def test_watch_rejects_a_cursor_older_than_retained_history():
    snapshots = PrinterSnapshots(clock=FakeClock(), history_limit=2)
    snapshots.observe("printer-0", {"print": {"progress": 100}})
    snapshots.observe("printer-0", {"print": {"progress": 200}})
    snapshots.observe("printer-0", {"print": {"progress": 300}})

    watcher = snapshots.watch(Watch(printer_id="printer-0", cursor=0))

    with pytest.raises(CursorExpired) as error:
        next(watcher)
    assert error.value.oldest_cursor == 2
    assert error.value.current_cursor == 3


def test_snapshot_serialization_keeps_the_legacy_state_shape_with_fact_metadata():
    snapshots = PrinterSnapshots(clock=FakeClock())
    snapshots.observe(
        "printer-0",
        {
            "state": "printing",
            "nozzle": {"current": 22000, "target": 22000},
            "print": {"name": "job.gcode", "layer": {"current": 3, "total": 43}},
        },
    )

    payload = next(snapshots.watch(Watch(printer_id="printer-0"))).to_dict()

    assert payload["cursor"] == 1
    assert payload["printerId"] == "printer-0"
    assert payload["state"] == "printing"
    assert payload["nozzle"] == {"current": 22000, "target": 22000}
    assert payload["print"] == {
        "name": "job.gcode",
        "layer": {"current": 3, "total": 43},
    }
    assert payload["facts"]["print.name"] == {
        "value": "job.gcode",
        "observedAt": 100.0,
        "freshness": "fresh",
    }
    assert payload["facts"]["bed.current"] == {
        "value": None,
        "observedAt": None,
        "freshness": "unknown",
    }


def test_matching_print_telemetry_binds_and_refreshes_trusted_upload_identity():
    clock = FakeClock()
    snapshots = PrinterSnapshots(clock=clock, fresh_for=15)
    snapshots.remember_job(
        "printer-0", "job.gcode", "OrcaSlicer", "slicer_upload"
    )
    snapshots.observe("printer-0", {"print": {"name": "job.gcode"}})

    first = next(snapshots.watch(Watch("printer-0")))
    assert first.facts["print.user_name"].value == "OrcaSlicer"
    assert first.facts["print.origin"].value == "slicer_upload"

    clock.now += 14
    snapshots.observe("printer-0", {"print": {"progress": 2500}})
    refreshed = next(snapshots.watch(Watch("printer-0")))
    assert refreshed.facts["print.name"].freshness == "fresh"
    assert refreshed.facts["print.user_name"].freshness == "fresh"

    clock.now += 2
    snapshots.tick()
    still_fresh = next(snapshots.watch(Watch("printer-0")))
    assert still_fresh.facts["print.name"].freshness == "fresh"
    assert still_fresh.facts["print.user_name"].freshness == "fresh"
