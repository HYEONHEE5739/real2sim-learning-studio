from pathlib import Path
import json,yaml
import pytest
from real2sim_builder.project import Project
from robot_learning_workbench.recipe import read_recipe,prepare_recipe
R=Path(__file__).resolve().parents[2]


def observation_recipe(tmp_path,engine='mujoco'):
    import shutil,os,copy
    from real2sim_builder.files import read,write
    project=Project.create(tmp_path/'projects','Scene observation')
    config=yaml.safe_load((R/'workbench_runs/devices/so101-pickplace-0b794e7c/capture.yaml').read_text())
    inputs={k:v for k,v in config['inputs'].items()if not k.startswith('leader')}
    owned=R/'workbench_runs/scenes/pickplace-colorblock-b7a5592b'
    shutil.copytree(owned/'exports/scene-v8-native',project.root/'exports/scene-v8-native',copy_function=os.link)
    for key in('isaac','mujoco'):write(project.root/'configuration'/(key+'.json'),read(owned/'configuration'/(key+'.json')))
    info=read(project.root/'project.yaml');info['execution_packages']=copy.deepcopy(read(owned/'project.yaml')['execution_packages']);write(project.root/'project.yaml',info)
    inputs.update(project=str(project.root),scene=str(project.root/'exports/scene-v8-native/scene.json'),engine_config=str(project.root/'configuration'/('isaac.json'if engine=='isaaclab'else'mujoco.json')))
    data={'schema_version':1,'stage':'paired_session','engine':engine,'inputs':inputs,'execution':{'device_source':'memory'},'output':{'directory':str(tmp_path/'observation')}}
    path=tmp_path/'observation.yaml';path.write_text(yaml.safe_dump(data));return path,project,data


def test_paired_observation_needs_no_leader_or_motion_budget(tmp_path):
    from robot_learning_workbench.robot.session_devices import construct
    path,project,_=observation_recipe(tmp_path);plan=prepare_recipe(read_recipe(path));devices,cameras,_=construct(plan)
    assert set(devices)=={'follower'}and set(cameras)=={'side','wrist'}and not devices['follower']._connected
    assert 'leader_device_profile'not in plan.resolved_inputs


def test_candidate_rerender_recipe_is_retired(tmp_path):
    p=tmp_path/'old.yaml';p.write_text(yaml.safe_dump({'schema_version':1,'stage':'paired_rerender','engine':'mujoco','inputs':{},'execution':{},'output':{'directory':'old'}}))
    with pytest.raises(ValueError,match='stage'):read_recipe(p)


def test_native_mujoco_renderer_tracks_measured_follower_state_without_physics_step(tmp_path):
    import numpy as np
    from robot_learning_workbench.robot.scene_render import SceneView,NativeRenderer
    from robot_learning_workbench.robot.session_devices import construct
    path,project,_=observation_recipe(tmp_path);plan=prepare_recipe(read_recipe(path));devices,_,_=construct(plan)
    view=SceneView(plan.scene.root/'scene.json',plan.engine,plan.resolved_inputs['engine_config']['path'],devices['follower'].precision_mapper.metadata())
    q=[0.,-1.5,1.4,1.1,0.,0.]
    with NativeRenderer(view,tmp_path/'render')as renderer:
        first=renderer.render(q);q[0]=.2;second=renderer.render(q)
    assert first['physics_steps']==second['physics_steps']==0
    np.testing.assert_array_equal(second['applied_sim_joint_rad'],q)
    assert second['scene_identity']['manifest_sha256']==plan.scene_identity['manifest_sha256']
    assert all(rgb.shape==(480,640,3)for rgb in second['images'].values())
    assert not np.array_equal(first['images']['side'],second['images']['side'])


def test_scene_observation_rejects_changed_mapping_and_manifest(tmp_path):
    import copy,shutil,os
    from robot_learning_workbench.robot.scene_render import SceneView
    from robot_learning_workbench.robot.session_devices import construct
    path,project,_=observation_recipe(tmp_path);plan=prepare_recipe(read_recipe(path));devices,_,_=construct(plan);mapping=devices['follower'].precision_mapper.metadata()
    wrong=copy.deepcopy(mapping);wrong['sha256']='0'*64
    with pytest.raises(ValueError,match='hash|mapping'):SceneView(plan.scene.root/'scene.json',plan.engine,plan.resolved_inputs['engine_config']['path'],wrong)
    def owned_file(source,target):
        if Path(source).name=='manifest.json':return shutil.copyfile(source,target)
        os.link(source,target);return target
    root=tmp_path/'closed-scene';shutil.copytree(plan.scene.root,root,copy_function=owned_file)
    view=SceneView(root/'scene.json',plan.engine,plan.resolved_inputs['engine_config']['path'],mapping)
    manifest=root/'manifest.json';manifest.write_text(json.dumps(json.loads(manifest.read_text()),indent=3))
    with pytest.raises(ValueError,match='[Ii]dentity|[Mm]anifest|[Rr]evision'):view.verify()


def test_follower_motion_updates_native_scene_and_pair_uses_four_images_without_writes(tmp_path):
    import time,numpy as np
    from robot_learning_workbench.robot.real_sim import RealSimSession
    from robot_learning_workbench.robot.session_devices import construct
    from robot_learning_workbench.robot.calibration import JOINTS,raw_from_native
    from real2sim_builder.capture import load_session
    path,project,_=observation_recipe(tmp_path);plan=prepare_recipe(read_recipe(path));devices,cameras,_=construct(plan);plan.output_path.mkdir();events=[]
    follower=devices['follower']
    def forbidden(*args,**kwargs):raise AssertionError('Real/Sim must not write any motor register')
    follower.bus.sync_write=forbidden;follower.bus.write=forbidden
    s=RealSimSession(plan,devices,cameras,events=events.append)
    def until(predicate,seconds=20):
        deadline=time.monotonic()+seconds
        while not predicate():
            s.observe();time.sleep(.035)
            assert time.monotonic()<deadline,(s.state,[e['payload']for e in events if e['kind']=='command_ack'or e['kind']=='status'and e['payload'].get('progress',{}).get('error')][-3:])
    try:
        s.connect();until(lambda:s.state=='OBSERVING')
        before=s.renderer.last_live['files']['side']['sha256'];q=dict(zip(JOINTS,s.history[-1]['q_measured']));q['shoulder_pan']+=.15
        native=follower.precision_mapper.urdf_to_calibrated(q)
        measured_raw={n:round(raw_from_native(native[n],follower.motor_specs[n]))for n in JOINTS};original_read=follower.bus.sync_read
        follower.bus.sync_read=lambda name,normalize=False,**kwargs:dict(measured_raw)if name=='Present_Position'else original_read(name,normalize=normalize,**kwargs)
        until(lambda:abs(s.renderer.last_live['measured_q_rad'][0]-q['shoulder_pan'])<.01)
        assert s.renderer.last_live['files']['side']['sha256']!=before
        s.dispatch([{'kind':'session_snapshot','command_id':'pair','payload':{}}]);until(lambda:len(s.snapshots)==1)
        saved=s.snapshots[0];assert set(saved['images'])=={'side','wrist','sim_side','sim_wrist'}
        manifest,rows,_=load_session(saved['path']);assert manifest['command_source']=='measured_observation_no_training_action'
        shot=next((Path(saved['path'])/'shots').iterdir());pair=json.loads((shot/'pair.json').read_text());state=json.loads((shot/'state.json').read_text())
        assert state['q_command']is None and pair['physics_steps']==0
        np.testing.assert_array_equal(pair['measured_q_rad'],saved['q_measured']);np.testing.assert_array_equal(pair['applied_sim_joint_rad'],saved['q_measured'])
        assert 'scene_identity'in pair and 'candidate_identity'not in pair
        assert s.teleoperation is None
        s.dispatch([{'kind':'session_snapshot','command_id':'late','payload':{}},{'kind':'cancel','command_id':'stop','payload':{}}])
        assert s.terminal and s.cancelled and len(s.snapshots)==1
        assert any(e['kind']=='command_ack'and e['payload']['command_id']=='late'and e['payload']['status']=='rejected'for e in events)
        assert all(not d._connected for d in devices.values())
    finally:s.close()


def test_memory_observer_does_not_claim_the_real_follower_serial_port(tmp_path):
    from robot_learning_workbench.robot.session_devices import construct
    path,project,_=observation_recipe(tmp_path);plan=prepare_recipe(read_recipe(path));devices,_,_=construct(plan)
    follower=devices['follower'];expected=plan.output_path/'memory-follower'
    assert Path(follower.bus.port)==expected and follower.identity['port']==str(expected)
    assert follower.read_only


def test_renderer_rejects_settings_changed_after_prepare_before_spawn(tmp_path,monkeypatch):
    from robot_learning_workbench.robot.render_transport import RenderProcess
    from robot_learning_workbench.robot.session_devices import construct
    import subprocess
    path,project,_=observation_recipe(tmp_path);plan=prepare_recipe(read_recipe(path));devices,_,_=construct(plan);plan.output_path.mkdir()
    settings=Path(plan.resolved_inputs['engine_config']['path']);settings.write_text(json.dumps(json.loads(settings.read_text()),indent=3))
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('Changed Prepared inputs must be rejected before spawning a render child'))
    with pytest.raises(ValueError,match='[Pp]repared|settings|changed'):RenderProcess(plan,devices['follower'].precision_mapper.metadata())


def test_legacy_finite_real_sim_is_inspection_only(tmp_path):
    path,project,data=observation_recipe(tmp_path);data['stage']='real_sim';data['inputs']={'scene':data['inputs']['scene'],'device_profile':data['inputs']['device_profile']};data['execution']={'mode':'observe_only','max_frames':3};path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError,match='mode|unknown'):read_recipe(path)
