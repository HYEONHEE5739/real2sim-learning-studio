"""Native-only publication and consumers; synthetic inputs, no device IO."""
import inspect
from pathlib import Path

import pytest

from real2sim_builder.export import export_revision
from real2sim_builder.files import read, write
from test_export_registration import export_project
from test_native_reconstruction_execution import native_project


def test_direct_export_always_publishes_native_profiles_and_keeps_scene_source(tmp_path):
    _, project, _ = native_project(tmp_path)
    destination = project.root / 'exports/direct-native'
    export_revision(project, destination=destination, allow_unvalidated=True,
                    native_options={'initial_joint_rad': [0.] * 6})
    record = read(project.root / 'project.yaml')['execution_packages'][-1]
    assert set(record['engine_profiles']['mujoco']) == {'pose', 'physics'}
    assert record['engine_config']['mujoco'] == record['engine_profiles']['mujoco']['pose']
    assert read(destination / 'authored_scene.json')['robot_model']['model_sha256']
    assert not (project.root / 'configuration/export-authored-preview.json').exists()
    assert 'execution_mode' not in inspect.signature(export_revision).parameters
    assert 'engine_config' not in inspect.signature(export_revision).parameters


def test_direct_export_without_robot_has_specific_blockers_and_no_executable_settings(tmp_path):
    _, project = export_project(tmp_path)
    destination = project.root / 'exports/incomplete-native'
    export_revision(project, destination=destination, allow_unvalidated=True)
    record = read(project.root / 'project.yaml')['execution_packages'][-1]
    assert record['engine_config'] == {}
    assert record['engine_profiles'] == {'mujoco': {}, 'isaac': {}}
    assert all(row['pose'] == row['physics'] == 'BLOCKED'
               and any('robot' in reason.lower() for reason in row['needs'])
               for row in record['execution_readiness'].values())


def test_authored_configuration_is_rejected_before_candidate_or_child_work():
    from real2sim_builder.stage_runtime import validate_configuration
    with pytest.raises(ValueError, match='simulator.mode|Native'):
        validate_configuration({'simulator': {'mode': 'authored'}})


def test_scene_view_rejects_authored_settings_instead_of_loading_another_renderer(tmp_path):
    from robot_learning_workbench.robot.scene_render import SceneView
    _, project, mapping = native_project(tmp_path)
    destination = project.root / 'exports/native'
    export_revision(project, destination=destination, allow_unvalidated=True,
                    native_options={'initial_joint_rad': [0.] * 6})
    settings = project.root / 'configuration/removed-preview.json'
    write(settings, {'render_type': 'authored'})
    with pytest.raises(ValueError, match='Native|native'):
        SceneView(destination / 'scene.json', 'mujoco', settings, mapping)


def test_old_registration_is_not_offered_as_an_executable_scene(tmp_path):
    from robot_learning_workbench.ui.session_operations import execution_scenes, real_sim_setup
    from robot_learning_workbench.ui.pipeline_inputs import scenes
    from robot_learning_workbench.scene_preparation import source_inputs
    workspace, project, _ = native_project(tmp_path)
    destination = project.root / 'exports/native'
    export_revision(project, destination=destination, allow_unvalidated=True,
                    native_options={'initial_joint_rad': [0.] * 6})
    info = read(project.root / 'project.yaml')
    info['execution_packages'][-1].pop('engine_profiles')
    info['execution_packages'][-1].pop('execution_readiness')
    write(project.root / 'project.yaml', info)
    assert execution_scenes(workspace)['scenes'][0]['engines'] == []
    assert scenes(workspace)['scenes'][0]['engine_config'] == {}
    with pytest.raises(ValueError, match='Native'):
        real_sim_setup(workspace, project.root, destination / 'scene.json', 'mujoco')
    with pytest.raises(ValueError, match='Native'):
        source_inputs(project.root, 'mujoco')


@pytest.mark.parametrize('missing,reason', [
    ('mapping', 'Mapping'), ('initial_q', 'initial_joint_rad'),
    ('wrist_mount', 'mount'), ('sensor_resolution', '640'),
    ('robot_collision', 'Collision'), ('robot_inertial', 'inertial')])
def test_incomplete_native_inputs_are_blocked_with_a_specific_reason(tmp_path, missing, reason):
    import hashlib
    from robot_learning_workbench.robot.calibration import PrecisionMapper
    _, project, mapping = native_project(tmp_path)
    scene = project.scene
    options = {'initial_joint_rad': [0.] * 6}
    if missing == 'mapping':
        scene['robot_model'].pop('mapping')
    elif missing == 'initial_q':
        options = {}
    elif missing == 'wrist_mount':
        scene['cameras'][1]['frame'] = 'world'
    elif missing == 'sensor_resolution':
        scene['cameras'][1]['resolution'] = [320, 240]
    else:
        model = project.root / scene['robot_model']['path']
        if missing == 'robot_collision':
            model.write_text(model.read_text().replace('<collision><geometry><mesh filename="tetra.obj"/></geometry></collision>', ''))
        else:
            import xml.etree.ElementTree as ET
            tree = ET.parse(model)
            for link in tree.findall('link'):
                if link.find('inertial') is not None:link.remove(link.find('inertial'))
            tree.write(model, encoding='unicode')
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        scene['robot_model']['model_sha256'] = digest
        mapping['profile']['urdf_sha256'] = digest
        scene['robot_model']['mapping'] = PrecisionMapper(mapping['profile']).metadata()
    project.save_scene(scene)
    write(project.root / 'working/validation/report.json', dict(passed=False, input_signature=project.signature()))
    export_revision(project, destination=project.root / 'exports/blocked', allow_unvalidated=True,
                    native_options=options)
    record = read(project.root / 'project.yaml')['execution_packages'][-1]
    assert record['engine_config'] == {}
    rows = [record['execution_readiness']['mujoco']] if missing == 'robot_inertial' else record['execution_readiness'].values()
    assert all(any(reason.lower() in need.lower() for need in row['needs']) for row in rows)


def test_registered_native_pose_flows_through_recipe_and_actual_render_child(tmp_path):
    import time
    from robot_learning_workbench.recipe import read_recipe, prepare_recipe
    from robot_learning_workbench.robot.render_transport import RenderProcess
    from robot_learning_workbench.ui.session_operations import real_sim_setup
    from test_scene_selection_performance import _bind_synthetic_configuration
    workspace, project, mapping = native_project(tmp_path)
    destination = project.root / 'exports/capture-native'
    export_revision(project, destination=destination, allow_unvalidated=True,
                    native_options={'initial_joint_rad': [0.] * 6})
    _bind_synthetic_configuration(workspace, project)
    data = real_sim_setup(workspace, project.root, destination / 'scene.json', 'mujoco')['recipe']
    data['output']['directory'] = str(tmp_path / 'paired')
    path = tmp_path / 'paired.yaml'; write(path, data)
    plan = prepare_recipe(read_recipe(path)); plan.output_path.mkdir()
    assert 'authored_render.py' not in {Path(p).name for p in plan.effective_settings['code_files']}
    process = RenderProcess(plan, mapping)
    try:
        deadline = time.monotonic() + 15
        process.observe([0.] * 6)
        while process.last_live is None:
            process.poll(); time.sleep(.01); assert time.monotonic() < deadline
        assert process.last_live['state_application'] == 'native_measured_joint_state'
        process.capture({'id': 'native_pair', 'sample': {'q_measured': [.1, 0., 0., 0., 0., 0.]}})
        result = None
        while result is None:
            result = process.poll(); time.sleep(.01); assert time.monotonic() < deadline
        assert result['physics_steps'] == result['total_physics_steps'] == 0
        assert result['applied_sim_joint_rad'] == [.1, 0., 0., 0., 0., 0.]
        # The Capture save process consumes the frozen PNGs without decoding
        # them in the serial/control interpreter.
        assert result['images'] == {} and set(result['files']) == {'side', 'wrist'}
        from PIL import Image
        assert all(Image.open(row['path']).size == (640, 480) for row in result['files'].values())
    finally:
        process.close()


def test_real_sim_recipe_cannot_use_registered_physics_settings(tmp_path):
    from robot_learning_workbench.recipe import read_recipe, prepare_recipe
    from robot_learning_workbench.ui.session_operations import real_sim_setup
    from test_scene_selection_performance import _bind_synthetic_configuration
    workspace, project, _ = native_project(tmp_path)
    destination = project.root / 'exports/mode-guard'
    export_revision(project, destination=destination, allow_unvalidated=True,
                    native_options={'initial_joint_rad': [0.] * 6})
    _bind_synthetic_configuration(workspace, project)
    data = real_sim_setup(workspace, project.root, destination / 'scene.json', 'mujoco')['recipe']
    physics = read(project.root / 'project.yaml')['execution_packages'][-1]['engine_profiles']['mujoco']['physics']
    data['inputs']['engine_config'] = str(project.root / physics)
    data['output']['directory'] = str(tmp_path / 'unstarted')
    path = tmp_path / 'bad-physics.yaml'; write(path, data)
    with pytest.raises(ValueError, match='Native Pose'):
        prepare_recipe(read_recipe(path))
    assert not (tmp_path / 'unstarted').exists()


def test_cli_export_uses_native_profiles_without_an_execution_mode_switch(tmp_path):
    from real2sim_builder.cli import main
    _, project, _ = native_project(tmp_path)
    destination = project.root / 'exports/cli-native'
    assert main(['export', str(project.root), '--destination', str(destination), '--allow-unvalidated',
                 '--initial-joint-rad', '0', '0', '0', '0', '0', '0']) == 0
    row = read(project.root / 'project.yaml')['execution_packages'][-1]
    assert set(row['engine_profiles']['mujoco']) == {'pose', 'physics'}


def test_real_sim_ui_never_switches_to_another_engine_automatically(tmp_path):
    from test_ui_restoration import qt
    qt('''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.real_sim_page import RealSimPage
app=QApplication([]);root=Path(sys.argv[1])
RealSimPage.refresh_scenes=lambda *args,**kwargs:None
p=RealSimPage('/no/worker',[],root);p.stop_timers();calls=[]
p.job.start=lambda *args,**kwargs:calls.append((args,kwargs))
p.engine.blockSignals(True);p.engine.setCurrentIndex(p.engine.findData('isaaclab'));p.engine.blockSignals(False)
row={'project':str(root),'scene':str(root/'exports/native/scene.json'),'engines':['mujoco'],'engine_config':{'mujoco':'configuration/pose.json'}}
p.scene_combo.blockSignals(True);p.scene_combo.addItem('Synthetic native',row);p.scene_combo.blockSignals(False)
p.load_selected()
assert p.engine.currentData()=='isaaclab'and not calls and p.template is None
assert not p.connect_button.isEnabled()and '직접 선택'in p.capture_hint.text()
p.engine.setCurrentIndex(p.engine.findData('mujoco'))
assert len(calls)==1 and calls[0][1]['engine']=='mujoco'
p.close();app.processEvents()
''',tmp_path)
