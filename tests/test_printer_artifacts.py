import io

import pytest

from web.printer_artifacts import ArtifactError, ArtifactStore


def upload(data, filename="cube.gcode"):
    stream = io.BytesIO(data)
    stream.filename = filename
    return stream


PREPARED = b"M190 S55\nM109 S220\nG28\n"


def test_staging_returns_an_opaque_reference_and_safe_metadata(tmp_path):
    store = ArtifactStore(tmp_path / "staging")

    artifact = store.stage(
        upload(PREPARED, r"C:\Users\someone\Desktop\my cube v2.gcode"),
        user_name="OrcaSlicer",
        origin="slicer_upload",
        extract_temperatures=True,
    )

    assert artifact.name == "my_cube_v2.gcode"
    assert artifact.size == len(PREPARED)
    assert artifact.user_name == "OrcaSlicer"
    assert artifact.origin == "slicer_upload"
    assert artifact.bed_celsius == 55
    assert artifact.nozzle_celsius == 220
    # The reference is opaque: it carries neither the caller's path nor the
    # file name, so journalling it cannot leak either.
    assert "cube" not in artifact.reference
    assert "Users" not in artifact.reference
    assert "someone" not in artifact.reference


def test_staged_content_is_readable_only_through_the_reference(tmp_path):
    store = ArtifactStore(tmp_path / "staging")

    artifact = store.stage(upload(PREPARED))

    with store.open(artifact.reference) as stream:
        assert stream.read() == PREPARED
        assert stream.filename == "cube.gcode"

    assert store.get(artifact.reference) == artifact
    assert store.get("not-a-reference") is None
    with pytest.raises(ArtifactError):
        store.open("not-a-reference")


def test_discard_removes_both_the_record_and_the_staged_content(tmp_path):
    root = tmp_path / "staging"
    store = ArtifactStore(root)
    artifact = store.stage(upload(PREPARED))

    store.discard(artifact.reference)

    assert store.get(artifact.reference) is None
    assert list(root.iterdir()) == []
    # Discarding twice is how cleanup runs after a partially failed action.
    store.discard(artifact.reference)


def test_staging_rejects_unusable_uploads_without_retaining_content(tmp_path):
    root = tmp_path / "staging"
    store = ArtifactStore(root)

    with pytest.raises(ArtifactError) as empty:
        store.stage(upload(b""))
    assert empty.value.reason == "empty_artifact"

    with pytest.raises(ArtifactError) as unnamed:
        store.stage(upload(PREPARED, "..."))
    assert unnamed.value.reason == "unsupported_artifact_name"

    with pytest.raises(ArtifactError) as unresolved:
        store.stage(
            upload(b"M190 S{first_layer_bed_temperature[0]}\nM109 S220\n"),
            extract_temperatures=True,
        )
    assert unresolved.value.reason == "unresolved_preparation_temperatures"

    assert list(root.iterdir()) == []


def test_staging_reads_temperatures_without_judging_them(tmp_path):
    # Whether a resolved temperature is supported is the print-start action's
    # policy, so staging must not pre-empt it.
    store = ArtifactStore(tmp_path / "staging")

    artifact = store.stage(upload(b"M190 S55\nM109 S500\n"), extract_temperatures=True)

    assert (artifact.bed_celsius, artifact.nozzle_celsius) == (55, 500)


def test_a_new_store_drops_artifacts_left_by_a_previous_process(tmp_path):
    root = tmp_path / "staging"
    orphaned = ArtifactStore(root).stage(upload(PREPARED)).reference

    store = ArtifactStore(root)

    assert store.get(orphaned) is None
    assert list(root.iterdir()) == []


def test_preparation_temperatures_are_absent_when_not_requested(tmp_path):
    store = ArtifactStore(tmp_path / "staging")

    artifact = store.stage(upload(b"binary acode payload", "model.acode"))

    assert artifact.name == "model.acode"
    assert artifact.bed_celsius is None
    assert artifact.nozzle_celsius is None
