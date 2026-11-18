"""New synthetic Builder packages through the real Native MuJoCo loader."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from real2sim_builder.export import export_revision
from real2sim_builder.files import read, write
from robot_learning_workbench.robot.calibration import JOINTS, PrecisionMapper
from test_export_registration import export_project


def native_project(tmp_path):
    from real2sim_builder.evidence import import_robot
    from test_precision_calibration import bound
    workspace,project=export_project(tmp_path)
    _,mapper=bound('follower')
    profile=copy.deepcopy(mapper.profile)
    profile.pop('runtime_model_binding',None)
    model=project.root/'input/robot.urdf'
    mesh=project.root/'input/tetra.obj'
    mesh.write_text('v 0 0 0\nv .025 0 0\nv 0 .025 0\nv 0 0 .025\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n')
    links=['base','shoulder','upper_arm','forearm','wrist','gripper','jaw']
    text=['<robot name="synthetic">']
    for name in links:
        text.append('<link name="'+name+'"><inertial><mass value=".1"/><inertia ixx=".0001" ixy="0" ixz="0" iyy=".0001" iyz="0" izz=".0001"/></inertial><visual><geometry><mesh filename="tetra.obj"/></geometry></visual><collision><geometry><mesh filename="tetra.obj"/></geometry></collision></link>')
    for i,name in enumerate(JOINTS):
        lo,hi=profile['joints'][name]['limits']
        text.append(f'<joint name="{name}" type="revolute"><parent link="{links[i]}"/><child link="{links[i+1]}"/><origin xyz="0 0 .035"/><axis xyz="0 1 0"/><limit lower="{lo}" upper="{hi}" effort="10" velocity="2"/></joint>')
    text.append('<link name="tool0"/><joint name="tool_fixed" type="fixed"><parent link="gripper"/><child link="tool0"/><origin xyz="0 0 .02"/></joint></robot>')
    model.write_text(''.join(text))
    profile['urdf_sha256']=hashlib.sha256(model.read_bytes()).hexdigest()
    mapping=PrecisionMapper(profile).metadata()
    import_robot(project,model,joints=dict.fromkeys(JOINTS,0.),base=np.eye(4).tolist())
    scene=project.scene
    scene['robot_model']['mapping']=mapping
    scene['objects'][1]['physics']['mass_kg']['value']=.05
    scene['objects'][1]['pose']['value'][0][3]=.25
    scene['cameras'][1]['frame']='robot_link_gripper'
    scene['cameras'][1]['pose']['value']=np.eye(4).tolist()
    project.save_scene(scene)
    write(project.root/'working/validation/report.json',dict(passed=False,input_signature=project.signature()))
    return workspace,project,mapping


def test_native_review_without_robot_reports_blocker_and_has_no_authored_fallback(tmp_path):
    _,project=export_project(tmp_path)
    package=project.root/'exports/native-review'
    export_revision(project,destination=package,allow_unvalidated=True)
    record=read(project.root/'project.yaml')['execution_packages'][0]
    assert record['engine_config']=={}
    assert record['execution_readiness']['mujoco']['status']=='BLOCKED'
    assert any('robot' in reason.lower() for reason in record['execution_readiness']['mujoco']['needs'])
    assert read(package/'provenance.json')['validation']['passed'] is False


@pytest.mark.parametrize('distorted',[False,True])
def test_new_native_pose_preserves_q_camera_identity_and_invalidates_changed_assets(tmp_path,monkeypatch,distorted):
    from robot_learning_workbench.robot.scene_render import SceneView
    from robot_learning_workbench.robot.pose_render import create_pose_renderer
    from real2sim_builder import scene as scene_module
    _,project,mapping=native_project(tmp_path)
    if distorted:
        scene=project.scene;scene['cameras'][1]['distortion']['value']=[.12,0.,0.,0.,0.]
        project.save_scene(scene)
        write(project.root/'working/validation/report.json',dict(passed=False,input_signature=project.signature()))
    destination=project.root/'exports/native-pose'
    export_revision(project,destination=destination,allow_unvalidated=True,
        native_options={'initial_joint_rad':[0.]*6})
    record=read(project.root/'project.yaml')['execution_packages'][0]
    assert record['execution_readiness']['mujoco']['pose']=='READY'
    if distorted:
        # Native Real/Sim owns explicit post-distortion. Source/DataGen's
        # pinhole-only consumer must retain its guard rather than emit wrong RGB.
        assert record['execution_readiness']['mujoco']['physics']=='BLOCKED'
        from scene_contract.package import load_scene
        from robot_learning_workbench.engines.mujoco.model import build_model,ModelConfig
        with pytest.raises(ValueError,match='distortion|undistorted|projection'):
            build_model(load_scene(destination/'scene.json'),ModelConfig(initial_joint_rad=[0.]*6,active_object_ids=[],object_physics={}))
    settings=project.root/record['engine_config']['mujoco']
    assert read(settings)['simulation_mode']=='pose'
    view=SceneView(destination/'scene.json','mujoco',settings,mapping)
    with create_pose_renderer(view,tmp_path/'render') as renderer:
        monkeypatch.setattr(scene_module,'sha',lambda *_:pytest.fail('Native frame performed full Builder asset hashing'))
        first=renderer.render([0.]*6)
        second=renderer.render([0.]*6)
        moved=renderer.render([.1,0,0,0,0,0])
        assert first['physics_steps']==0 and first['state_application']=='native_measured_joint_state'
        assert first['applied_sim_joint_rad']==[0.]*6
        for name in ('side','wrist'):
            assert np.array_equal(first['images'][name],second['images'][name])
            assert first['sim_cameras'][name]==second['sim_cameras'][name]
        assert moved['sim_cameras']['wrist']['T_world_optical']!=first['sim_cameras']['wrist']['T_world_optical']
        with pytest.raises(ValueError,match='limit'):
            renderer.render([100.]*6)
        with pytest.raises(ValueError,match='finite'):
            renderer.render([float('nan')]*6)
        (destination/view.package.scene['robot']['asset_path']).write_text('changed synthetic URDF')
        with pytest.raises(ValueError,match='[Hh]ash|[Ss]ize|integrity|mismatch'):
            renderer.render([0.]*6)


def test_new_native_physics_has_actual_steps_gravity_contacts_and_joint_error(tmp_path):
    from robot_learning_workbench.robot.scene_render import SceneView,create_renderer
    _,project,mapping=native_project(tmp_path)
    destination=project.root/'exports/native-physics'
    export_revision(project,destination=destination,allow_unvalidated=True,
        native_options={'initial_joint_rad':[0.]*6})
    record=read(project.root/'project.yaml')['execution_packages'][0]
    assert record['execution_readiness']['mujoco']['physics']=='READY'
    settings=project.root/record['engine_profiles']['mujoco']['physics']
    view=SceneView(destination/'scene.json','mujoco',settings,mapping)
    with create_renderer(view,tmp_path/'physics')as renderer:
        qi,_=renderer.binding.object_indices['block']
        renderer.data.qpos[qi+2]+=.08
        raised=float(renderer.data.qpos[qi+2])
        for _ in range(30):
            renderer.advance([0.]*6)
        assert float(renderer.data.time)>.5
        assert renderer.data.qpos[qi+2]<raised-.04 and renderer.data.ncon>0
        result=renderer.render([.1,0,0,0,0,0])
        assert result['state_application']=='native_physics_joint_target' and result['physics_steps']>0
        assert result['sim_target_joint_rad']==[.1,0,0,0,0,0]
        assert not np.allclose(result['applied_sim_joint_rad'],result['measured_q_rad'],atol=1e-6)
    assert read(destination/'scene.json')['validation']['physics']=='UNVALIDATED'


def test_native_stage14_uses_the_actual_owned_worker_entrypoint(tmp_path):
    import os,subprocess,sys
    from real2sim_builder import stage_workers
    _,project,_=native_project(tmp_path)
    destination=project.root/'exports/worker-native'
    export_revision(project,destination=destination,allow_unvalidated=True,
        native_options={'initial_joint_rad':[0.]*6})
    row=read(project.root/'project.yaml')['execution_packages'][0]
    output=tmp_path/'native-worker';request=tmp_path/'request.json'
    write(request,dict(package=str(destination),engine='mujoco',camera_ids=['side','wrist'],
        engine_config=str(project.root/row['engine_config']['mujoco']),output=str(output)))
    env=os.environ.copy()
    result=subprocess.run([sys.executable,'-B',stage_workers.__file__,'--worker','simulator',str(request)],
        env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    response=read(output/'result.json')
    assert response['status']=='COMPLETE'
    assert response['data']['state_application']=='native_measured_joint_state'
    assert response['data']['physics_steps']==0
    assert all(Path(p).is_file()for p in response['data']['renders'])


def test_actual_stage13_and14_keep_native_execution_separate_from_approval(tmp_path):
    from real2sim_builder.candidate import Candidate
    from real2sim_builder import reconstruction_stages,stage_workers
    _,project,_=native_project(tmp_path)
    candidate=Candidate.create(project,'native_stage')
    folder=candidate.root/'stage13';folder.mkdir()
    config={'simulator':{'native_options':{'initial_joint_rad':[0.]*6}}}
    packaged=reconstruction_stages.package_scene(candidate,config,{10:{'coordinate_frame':'synthetic explicit World'},12:{}},folder,None)
    assert packaged['execution_mode']=='native' and packaged['native_readiness']['mujoco']['pose']=='READY'
    assert packaged['approved']is False and packaged['physical_verified']is False
    output=candidate.root/'stage14';output.mkdir()
    def provider(operation,request,work):
        assert operation=='simulator'
        work.mkdir();return stage_workers.simulator({**request,'output':str(work)})
    result=reconstruction_stages.simulator_integration(candidate,config,{13:packaged},output,provider)
    assert result['runtime']['state_application']=='native_measured_joint_state'
    assert result['runtime']['physics_steps']==0
    assert result['physical_verified']is False and candidate.info['status']=='OPEN'


def test_default_stage14_does_not_use_authored_when_native_is_blocked(tmp_path):
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.reconstruction_stages import package_scene,simulator_integration
    from real2sim_builder.stage_artifacts import StageNeeds
    _,project=export_project(tmp_path);candidate=Candidate.create(project,'blocked')
    folder=candidate.root/'stage13';folder.mkdir()
    packaged=package_scene(candidate,{}, {10:{'coordinate_frame':'synthetic'},12:{}},folder,None)
    output=candidate.root/'stage14';output.mkdir()
    with pytest.raises(StageNeeds,match='Native.*not ready'):
        simulator_integration(candidate,{}, {13:packaged},output,lambda *_:pytest.fail('No authored fallback or simulator request allowed'))


def test_exported_native_physics_settings_feed_existing_source_consumer(tmp_path):
    from types import SimpleNamespace
    from scene_contract.package import load_scene
    from robot_learning_workbench.engines.mujoco.source import resolved_model_config
    _,project,_=native_project(tmp_path);destination=project.root/'exports/source-native'
    export_revision(project,destination=destination,allow_unvalidated=True,native_options={'initial_joint_rad':[0.]*6})
    record=read(project.root/'project.yaml')['execution_packages'][0]
    plan=SimpleNamespace(engine='mujoco',stage='source',effective_settings={'execution':{}},object_order=('block',),
        scene=load_scene(destination/'scene.json'),input_documents={})
    plan.input_documents['engine_config']=read(project.root/record['engine_profiles']['mujoco']['physics'])
    assert resolved_model_config(plan).active_object_ids==['block']
    plan.input_documents['engine_config']=read(project.root/record['engine_profiles']['mujoco']['pose'])
    with pytest.raises(ValueError,match='[Pp]ose|[Pp]hysics'):
        resolved_model_config(plan)


def test_workspace_physics_selectors_use_physics_profile_while_realsim_keeps_pose(tmp_path):
    from robot_learning_workbench.ui.pipeline_inputs import scenes
    from robot_learning_workbench.ui.session_operations import real_sim_setup
    from robot_learning_workbench.scene_preparation import source_inputs
    from robot_learning_workbench.robot.registration import bind_configuration
    from test_scene_selection_performance import _bind_synthetic_configuration
    workspace,project,_=native_project(tmp_path);destination=project.root/'exports/physics-selection'
    export_revision(project,destination=destination,allow_unvalidated=True,native_options={'initial_joint_rad':[0.]*6})
    record=read(project.root/'project.yaml')['execution_packages'][0]
    config=_bind_synthetic_configuration(workspace,project)
    write(config.parent/'leader.json',{'role':'leader'})
    document=read(config);document['inputs']['leader_device_profile']='leader.json';write(config,document)
    bind_configuration(project.root,config,workspace)
    physics=(project.root/record['engine_profiles']['mujoco']['physics']).resolve()
    pose=(project.root/record['engine_profiles']['mujoco']['pose']).resolve()
    assert Path(scenes(workspace)['scenes'][0]['engine_config']['mujoco'])==physics
    assert Path(source_inputs(project.root,'mujoco')['inputs']['engine_config'])==physics
    assert Path(real_sim_setup(workspace,project.root,destination/'scene.json','mujoco')['recipe']['inputs']['engine_config'])==pose


def test_missing_physics_properties_never_select_pose_or_an_older_physics_revision(tmp_path):
    from robot_learning_workbench.scene_preparation import source_inputs
    from robot_learning_workbench.ui.pipeline_inputs import scenes
    _,project,_=native_project(tmp_path)
    export_revision(project,destination=project.root/'exports/ready',allow_unvalidated=True,native_options={'initial_joint_rad':[0.]*6})
    scene=project.scene;scene['objects'][1]['physics']['mass_kg']['value']=None;project.save_scene(scene)
    write(project.root/'working/validation/report.json',dict(passed=False,input_signature=project.signature()))
    export_revision(project,destination=project.root/'exports/missing-mass',allow_unvalidated=True,native_options={'initial_joint_rad':[0.]*6})
    rows=scenes(project.root.parent.parent)['scenes']
    assert rows[-1]['engine_config']=={}
    with pytest.raises(ValueError,match='mass'):
        source_inputs(project.root,'mujoco')
