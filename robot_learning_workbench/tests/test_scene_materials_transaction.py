"""Synthetic camera-only material saves publish one complete Evidence transaction."""
import copy
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from real2sim_builder import files
from real2sim_builder.project import Project
from robot_learning_workbench.robot import scene_observation


@pytest.fixture
def project(tmp_path):
    project = Project.create(tmp_path / "scenes", "Synthetic materials")
    evidence = project.read_evidence(resolve=False)
    evidence["notes"] = ["Existing Evidence must survive registration and failure"]
    project.write_evidence(evidence)
    return project


@pytest.fixture
def observation():
    frozen_ns = 10_000_000_000
    packets = {}
    for index, name in enumerate(("side", "wrist")):
        end_ns = frozen_ns - (30 + index * 5) * 1_000_000
        packets[name] = {
            "rgb": np.full((480, 640, 3), 40 + index * 80, np.uint8),
            "sequence": 11 + index,
            "read_start": {"monotonic_ns": end_ns - 2_000_000, "unix_ns": 1_800_000_000_000_000_000 + end_ns - 2_000_000},
            "read_end": {"monotonic_ns": end_ns, "unix_ns": 1_800_000_000_000_000_000 + end_ns},
        }
    request = {"requested_ns": frozen_ns - 20_000_000,
               "received_ns": frozen_ns - 10_000_000, "observed_ns": frozen_ns}
    return frozen_ns, packets, request


def _observation_root(project):
    return project.root / "input" / "observations" / "synthetic_session" / "observation_one"


def _saved_originals(root):
    return {name: (root / name).read_bytes() for name in ("side.png", "wrist.png", "observation.json")}


def _assert_registered(project, row):
    evidence = files.read(project.root / "input" / "evidence.yaml")
    root = Path(row["path"])
    assert evidence["notes"] == ["Existing Evidence must survive registration and failure"]
    assert len(evidence["images"]) == 2 and len(evidence["documents"]) == 1
    assert {image["camera"] for image in evidence["images"]} == {"side", "wrist"}
    for image in evidence["images"]:
        path = project.root / image["path"]
        assert path == root / (image["camera"] + ".png")
        assert image["sha256"] == files.sha(path)
        assert image["resolution"] == [640, 480]
        assert image["eligible"] is False
    document = evidence["documents"][0]
    assert project.root / document["path"] == root / "observation.json"
    assert document["sha256"] == files.sha(root / "observation.json")
    assert document["role"] == "unbound_sdk_camera_observation"
    assert not list((project.root / "input" / "scene_photos").rglob("*.png"))


def test_material_registration_uses_one_unresolved_read_and_one_complete_evidence_write(project, observation, monkeypatch):
    frozen_ns, packets, _ = observation
    reads, writes = [], []
    real_read, real_write = project.read_evidence, project.write_evidence

    def read_evidence(*, resolve=True):
        reads.append(resolve)
        return real_read(resolve=resolve)

    def write_evidence(data):
        writes.append(copy.deepcopy(data))
        return real_write(data)

    monkeypatch.setattr(project, "read_evidence", read_evidence)
    monkeypatch.setattr(project, "write_evidence", write_evidence)

    row = scene_observation.save_materials(project, "synthetic_session", "observation_one", packets, None, now_ns=frozen_ns)

    assert reads == [False], "One observation expanded or repeatedly parsed the Evidence index"
    assert len(writes) == 1, "Side/Wrist images and their document were published separately"
    assert len(writes[0]["images"]) == 2 and len(writes[0]["documents"]) == 1
    _assert_registered(project, row)


def test_material_pngs_are_registered_in_place_without_scene_photo_duplicates(project, observation):
    frozen_ns, packets, _ = observation

    row = scene_observation.save_materials(project, "synthetic_session", "observation_one", packets, None, now_ns=frozen_ns)

    root = _observation_root(project)
    assert Path(row["path"]) == root
    assert {name: Path(path) for name, path in row["images"].items()} == {name: root / (name + ".png") for name in packets}
    for name, packet in packets.items():
        with Image.open(root / (name + ".png")) as image:
            np.testing.assert_array_equal(np.asarray(image), packet["rgb"])
    _assert_registered(project, row)


@pytest.mark.parametrize("with_request", [False, True])
def test_repeated_completed_observation_reuses_originals_without_duplicate_evidence(project, observation, with_request):
    frozen_ns, packets, request = observation
    kwargs = {"now_ns": frozen_ns, **({"request": request} if with_request else {})}
    first = scene_observation.save_materials(project, "synthetic_session", "observation_one", packets, None, **kwargs)
    originals = _saved_originals(Path(first["path"]))
    evidence_bytes = (project.root / "input" / "evidence.yaml").read_bytes()

    second = scene_observation.save_materials(project, "synthetic_session", "observation_one", packets, None, **kwargs)

    assert (second["id"], second["path"], second["images"]) == (first["id"], first["path"], first["images"])
    assert _saved_originals(Path(second["path"])) == originals
    assert (project.root / "input" / "evidence.yaml").read_bytes() == evidence_bytes
    _assert_registered(project, second)


@pytest.mark.parametrize("changed", ["pixels", "request"])
def test_existing_observation_key_rejects_different_original_inputs(project, observation, changed):
    frozen_ns, packets, request = observation
    row = scene_observation.save_materials(project, "synthetic_session", "observation_one", packets, None, now_ns=frozen_ns, request=request)
    originals = _saved_originals(Path(row["path"]))
    evidence_bytes = (project.root / "input" / "evidence.yaml").read_bytes()
    changed_packets, changed_request = copy.deepcopy(packets), copy.deepcopy(request)
    if changed == "pixels":
        changed_packets["side"]["rgb"][0, 0, 0] ^= 1
    else:
        changed_request["requested_ns"] -= 1_000_000

    with pytest.raises(ValueError):
        scene_observation.save_materials(project, "synthetic_session", "observation_one", changed_packets, None, now_ns=frozen_ns, request=changed_request)

    assert _saved_originals(Path(row["path"])) == originals
    assert (project.root / "input" / "evidence.yaml").read_bytes() == evidence_bytes


@pytest.mark.parametrize("camera", ["side", "wrist"])
def test_camera_frame_received_after_requested_instant_is_rejected(project, observation, camera):
    frozen_ns, packets, request = observation
    # Fresh at observation time, but too late to represent the requested instant.
    end_ns = request["requested_ns"] + 1_000_000
    packets[camera]["read_start"]["monotonic_ns"] = end_ns - 500_000
    packets[camera]["read_end"]["monotonic_ns"] = end_ns
    evidence_bytes = (project.root / "input" / "evidence.yaml").read_bytes()

    with pytest.raises(ValueError):
        scene_observation.save_materials(project, "synthetic_session", "observation_one", packets, None, now_ns=frozen_ns, request=request)

    assert not _observation_root(project).exists()
    assert (project.root / "input" / "evidence.yaml").read_bytes() == evidence_bytes


def test_deferred_writer_uses_frozen_observation_time_and_preserves_request_without_model_state(project, observation, monkeypatch):
    frozen_ns, packets, request = observation
    monkeypatch.setattr(scene_observation.time, "monotonic_ns", lambda: frozen_ns + 5_000_000_000)

    row = scene_observation.save_materials(project, "synthetic_session", "observation_one", packets, None, now_ns=frozen_ns, request=request)

    record = files.read(Path(row["path"]) / "observation.json")
    assert all(record["capture_request"][key] == value for key, value in request.items())
    for name, packet in packets.items():
        assert record["camera_timing"][name]["read_end"] == packet["read_end"]
        assert packet["read_end"]["monotonic_ns"] <= record["capture_request"]["requested_ns"]
    assert row["q_measured"] == []
    assert record["model_state"] is None and record["action"] is None
    assert record.get("q_measured") in (None, [])
    assert record["eligible_for_calibration"] is False
    _assert_registered(project, row)


def test_failed_atomic_evidence_write_preserves_sealed_originals_for_explicit_retry(project, observation, monkeypatch):
    frozen_ns, packets, _ = observation
    evidence_path = project.root / "input" / "evidence.yaml"
    before = evidence_path.read_bytes()
    real_replace = files.os.replace

    def fail_evidence_replace(source, destination):
        if Path(destination) == evidence_path:
            raise OSError("injected Evidence write failure")
        return real_replace(source, destination)

    with monkeypatch.context() as scoped:
        scoped.setattr(files.os, "replace", fail_evidence_replace)
        with pytest.raises(OSError, match="injected Evidence write failure"):
            scene_observation.save_materials(project, "synthetic_session", "observation_one", packets, None, now_ns=frozen_ns)

    root = _observation_root(project)
    originals = _saved_originals(root)
    assert (root / "COMPLETE").is_file(), "Registration failure left the original observation unsealed"
    assert evidence_path.read_bytes() == before
    for name, packet in packets.items():
        with Image.open(root / (name + ".png")) as image:
            np.testing.assert_array_equal(np.asarray(image), packet["rgb"])

    # Retry through a newly opened Project, without any in-memory recovery state.
    reopened = Project(project.root)
    row = scene_observation.save_materials(reopened, "synthetic_session", "observation_one", packets, None, now_ns=frozen_ns)

    assert _saved_originals(root) == originals
    _assert_registered(reopened, row)
