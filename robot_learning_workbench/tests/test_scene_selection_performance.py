"""Scene selection stays cheap; execution preparation retains full integrity checks."""
from collections import Counter
import json
from pathlib import Path

import pytest

from real2sim_builder.export import export_revision
from real2sim_builder.files import read, write
from robot_learning_workbench.ui.session_operations import execution_scenes, real_sim_setup
from scene_contract import package
from test_native_reconstruction_execution import native_project


@pytest.fixture
def exported_scene(tmp_path):
    workspace, project, _ = native_project(tmp_path)
    destination = project.root / "exports" / "selection-review"
    identity = export_revision(project, destination=destination, revision="selection_review", allow_unvalidated=True,native_options={'initial_joint_rad':[0.]*6})
    return workspace, project, destination, identity


def _observe_full_validation(monkeypatch):
    calls = Counter()
    real_load_scene = package.load_scene
    real_verify_files = package.verify_files

    def load_scene(*args, **kwargs):
        calls["load_scene"] += 1
        return real_load_scene(*args, **kwargs)

    def verify_files(*args, **kwargs):
        calls["verify_files"] += 1
        return real_verify_files(*args, **kwargs)

    monkeypatch.setattr(package, "load_scene", load_scene)
    monkeypatch.setattr(package, "verify_files", verify_files)
    return calls


def _bind_synthetic_configuration(workspace, project):
    from robot_learning_workbench.robot.registration import bind_configuration, save_configuration

    root = workspace / "devices" / "synthetic-inputs"
    root.mkdir(parents=True)
    sdk = root / "sdk.json"
    write(sdk, {})
    device = root / "device.json"
    write(device, {"role": "follower", "calibration_path": str(sdk)})
    calibration = root / "precision.json"
    write(calibration, {"synthetic": True})
    cameras = root / "cameras.json"
    write(cameras, {"cameras": {}})
    model = root / "robot.urdf"
    model.write_text('<robot name="synthetic"><link name="base"/></robot>')
    # Selection resolves these owned paths. Device validation remains pending.
    configuration = save_configuration(workspace, "Synthetic selection", {
        "schema_version": 1, "stage": "scene_capture",
        "inputs": {"device_profile": str(device), "calibration_profile": str(calibration),
                   "camera_config": str(cameras), "robot_model": str(model)},
        "execution": {"device_source": "memory"}, "output": {"directory": "unused"},
    })
    bind_configuration(project.root, configuration, workspace)
    return configuration


def test_execution_scene_catalog_lists_registered_packages_without_full_validation(exported_scene, monkeypatch):
    workspace, project, first, first_identity = exported_scene
    second = project.root / "exports" / "second-review"
    second_identity = export_revision(project, destination=second, revision="second_review", allow_unvalidated=True,native_options={'initial_joint_rad':[0.]*6})
    calls = _observe_full_validation(monkeypatch)

    rows = execution_scenes(workspace)["scenes"]

    assert {row["scene"] for row in rows} == {str(first / "scene.json"), str(second / "scene.json")}
    assert {row["revision"] for row in rows} == {first_identity.revision, second_identity.revision}
    assert all(set(row["engines"]) == {"mujoco"} for row in rows)
    assert calls == Counter(), "Catalog selection expanded the immutable asset closure"


def test_changed_manifest_is_not_a_normal_selectable_scene(exported_scene):
    workspace, _, destination, _ = exported_scene
    assert execution_scenes(workspace)["scenes"]
    manifest = destination / "manifest.json"
    manifest.write_text(manifest.read_text() + "\n")

    rows = execution_scenes(workspace)["scenes"]

    assert not rows or all(row.get("valid") is False and row.get("reason") for row in rows)


@pytest.mark.parametrize("engine", ["mujoco"])
def test_real_sim_settings_resolution_does_not_validate_asset_closure(exported_scene, monkeypatch, engine):
    workspace, project, destination, _ = exported_scene
    configuration = _bind_synthetic_configuration(workspace, project)
    calls = _observe_full_validation(monkeypatch)

    setup = real_sim_setup(workspace, project.root, destination / "scene.json", engine)

    recipe = setup["recipe"]
    assert recipe["stage"] == "paired_session" and recipe["engine"] == engine
    assert Path(recipe["inputs"]["scene"]) == destination / "scene.json"
    assert Path(recipe["inputs"]["engine_config"]).is_file()
    assert Path(setup["configuration"]) == configuration
    assert calls == Counter(), "Settings selection performed execution-time asset validation"


def test_recipe_preparation_rejects_corrupt_assets_before_device_construction(exported_scene, monkeypatch):
    from robot_learning_workbench.recipe import prepare_recipe, read_recipe
    from robot_learning_workbench.robot import session_devices

    workspace, project, destination, identity = exported_scene
    _bind_synthetic_configuration(workspace, project)
    recipe = real_sim_setup(workspace, project.root, destination / "scene.json", "mujoco")["recipe"]
    recipe["output"]["directory"] = str(workspace / "unstarted-real-sim")
    recipe_path = workspace / "selected-real-sim.yaml"
    write(recipe_path, recipe)
    document = read_recipe(recipe_path)

    def no_device_construction(*args, **kwargs):
        pytest.fail("Recipe preparation constructed a device")

    monkeypatch.setattr(session_devices, "construct", no_device_construction)
    monkeypatch.setattr(session_devices, "device", no_device_construction)
    prepared = prepare_recipe(document)
    assert prepared.scene.identity == identity
    # Keep the manifest unchanged and alter an asset at the same byte length.
    asset = next(row for row in read(destination / "manifest.json")["files"] if row["path"].endswith(".usda"))
    path = destination / asset["path"]
    contents = bytearray(path.read_bytes())
    contents[-1] ^= 1
    path.write_bytes(contents)

    with pytest.raises(package.SceneError) as error:
        prepare_recipe(document)

    assert error.value.code == "SCENE_INTEGRITY_MISMATCH"
    assert error.value.effect == "not_started"
    assert not (workspace / "unstarted-real-sim").exists()


def test_unchanged_successful_ui_selection_does_not_start_duplicate_setup_jobs(exported_scene, tmp_path):
    from test_ui_restoration import qt

    workspace, project, destination, _ = exported_scene
    _bind_synthetic_configuration(workspace, project)
    row = execution_scenes(workspace)["scenes"][0]
    setup = real_sim_setup(workspace, project.root, destination / "scene.json", "mujoco")
    (tmp_path / "ui-selection.json").write_text(json.dumps({"workspace": str(workspace), "row": row, "setup": setup}))
    qt('''
import json
from pathlib import Path
import sys
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.jobs import BackendJob
from robot_learning_workbench.ui.real_sim_page import RealSimPage

app = QApplication([])
data = json.loads((Path(sys.argv[1]) / 'ui-selection.json').read_text())
calls = []
def record_start(self, operation, **arguments):
    calls.append(operation)

with patch.object(BackendJob, 'start', record_start):
    page = RealSimPage(sys.executable, [], Path(data['workspace']))
    page.stop_timers()
    try:
        page.scene_combo.blockSignals(True)
        page.scene_combo.addItem('Synthetic review', data['row'])
        page.scene_combo.blockSignals(False)
        calls.clear()
        page.load_selected()
        assert calls == ['session_real_setup']
        page.loaded({'ok': True, 'result': data['setup']})
        assert page.template == data['setup']['recipe']
        calls.clear()

        page.load_selected()
        page.load_selected()

        assert not calls, 'Unchanged successful selection started duplicate setup jobs: ' + repr(calls)
        assert page.template == data['setup']['recipe']
    finally:
        page.stop_timers()
        page.close()
        app.processEvents()
''', tmp_path)
