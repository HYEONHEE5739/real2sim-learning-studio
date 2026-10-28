"""MuJoCo workflow contracts; all engines are real, input devices are explicit fixtures."""
import json
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench.engines.mujoco import source
from robot_learning_workbench.data.native import load_catalog,read_array
ROOT=Path(__file__).resolve().parents[2]

def test_recorded_episode_keeps_pre_state_and_requested_command():
    from robot_learning_workbench.data.native import native_api
    before={'joint_positions':np.array([0.,1.,2.,3.,4.,1.]), 'eef_pose':np.eye(4), 'object_poses':{'cube_red':np.eye(4)}}
    after=dict(before,joint_positions=np.arange(6,dtype=float)+.01)
    episode=native_api()[0]();source.record_frame(episode,before,np.eye(4),np.ones(6),time_s=0.,requested=np.ones(6)*2,signals={})
    episode.pre_export()
    np.testing.assert_array_equal(episode.data['obs']['policy']['joint_pos'][0],before['joint_positions'])
    np.testing.assert_array_equal(episode.data['collection']['requested_action'][0],np.ones(6)*2)
    assert not np.array_equal(episode.data['obs']['policy']['joint_pos'][0],after['joint_positions'])
    assert episode.data['obs']['datagen_info']['eef_pose']['tool0'].dtype.__str__()=='torch.float32'

def test_control_cancel_and_stale_mark():
    events=[];state={'paused':False,'steps':0,'cancelled':False,'marks':[],'skipped':False}
    source.control_commands([{'command_id':'c','kind':'cancel','payload':{}}],state,events.append,tick=8,episode_id='a')
    assert state['cancelled'] and events[-1]['payload']['status']=='completed'
    with pytest.raises(ValueError):source.control_commands([{'command_id':'m','kind':'mark','episode_id':'old','payload':{'frame':2,'event':'grasp'}}],state,events.append,tick=8,episode_id='a')

def test_source_recipe_accepts_explicit_engine_input_and_duration(tmp_path):
    import yaml
    from robot_learning_workbench.recipe import read_recipe
    recipe={'schema_version':1,'stage':'source','engine':'mujoco','inputs':{'scene':'scene.json','device_profile':'leader.json','engine_config':'engine.json'},'execution':{'episodes':1,'seed':1047,'episode_time_s':1.,'reset_time_s':0.},'output':{'directory':'out'},'objects':{'cube_red':{'placement':{'function':'placement.fixed_xy','params':{'frame':'workspace','support':'table','xy_m':[0,0]}}}}}
    p=tmp_path/'r.yaml';p.write_text(yaml.safe_dump(recipe));doc=read_recipe(p)
    assert doc.spec.execution['episode_time_s']==1.
    recipe['execution']['episode_time_s']=0;p.write_text(yaml.safe_dump(recipe))
    with pytest.raises(ValueError):read_recipe(p)

def test_actual_source_collect_publish_and_cancel(tmp_path):
    import mujoco
    from scene_contract.package import load_scene
    from robot_learning_workbench.engines.mujoco.model import build_model,ModelConfig,JOINTS
    from robot_learning_workbench.engines.mujoco.state import restore_episode
    from robot_learning_workbench.data.native import NativeRun
    settings=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text());root=Path(settings['package_root'])
    cfg=ModelConfig(tuple(settings['initial_joint_rad'][n] for n in JOINTS),('cube_red',),json.loads((root/settings['baseline_metadata']['compiled_physics']['asset_path']).read_text())['objects'])
    model,b=build_model(load_scene(root/'scene.json'),cfg);data=mujoco.MjData(model);restore_episode(model,data,b,None)
    initial=data.qpos[list(b.q_indices)].copy();target=initial.copy();target[0]+=.01
    with NativeRun(tmp_path/'out',{'stage':'source','seed':4}) as run:
        segment=run.segment('a');ep,media,snapshot,status=source.collect_episode(model,data,b,segment,episode_id='one',seed=4,frames=2,read_target=lambda:target,events=lambda e:None,commands=lambda:())
        assert status=='completed' and data.time==pytest.approx(2/30)
        segment.write_episode(ep,episode_id='one',metadata={'initial_snapshot':snapshot,'success_source':'recording_only'},media=media);segment.commit()
    saved=load_catalog(tmp_path/'out').episodes[0]
    np.testing.assert_array_equal(read_array(saved,'obs/policy/joint_pos')[0],initial)
    np.testing.assert_array_equal(read_array(saved,'joint_targets'),np.tile(target,(2,1)))
    assert all(v['shape']==[480,640,3] and v['frames']==2 for v in saved.media.values())
    with NativeRun(tmp_path/'cancel',{'stage':'source','seed':4}) as run:
        seg=run.segment('c');ep,media,_,status=source.collect_episode(model,data,b,seg,episode_id='two',seed=4,frames=2,read_target=lambda:target,events=lambda e:None,commands=lambda:({'command_id':'cancel','kind':'cancel'},))
        assert status=='cancelled' and media=={}
        for kind in ('save','discard'):
            ep,media,_,status=source.collect_episode(model,data,b,seg,episode_id='two',seed=4,frames=2,read_target=lambda:target,events=lambda e:None,commands=lambda:({'command_id':kind,'kind':kind},))
            assert status=='discarded' and not media
    assert not load_catalog(tmp_path/'cancel').episodes

def test_engine_recipe_rejects_missing_config_before_output(tmp_path):
    from types import SimpleNamespace
    plan=SimpleNamespace(engine='mujoco',stage='source',effective_settings={'execution':{'episodes':1,'seed':1}},input_documents={})
    with pytest.raises(ValueError,match='engine_config'):source.resolved_model_config(plan)

def test_manual_boundary_requires_physical_success_and_one_interior_mark():
    from robot_learning_workbench.engines.mujoco.annotation import accept_annotation
    assert accept_annotation(True,388,'manual',[203])==(True,203)
    assert accept_annotation(False,388,'manual',[203])==(False,None)
    for marks in ([],[0],[387],[203,204]):assert accept_annotation(True,388,'manual',marks)==(False,None)
    assert accept_annotation(True,388,'auto',[])==(True,None)

def test_step_ack_waits_for_actual_physics_steps():
    events=[];state=dict(paused=True,steps=0,cancelled=False,marks=[],skipped=False)
    source.control_commands([{'command_id':'two','kind':'step','payload':{'count':2}}],state,events.append,tick=7,episode_id='a')
    assert events==[]
    source.step_completed(state,events.append,7);assert events==[]
    source.step_completed(state,events.append,8)
    assert events[-1]['payload']=={'command_id':'two','status':'completed','applied_tick':8}

def test_source_collection_coordinate_retains_b02_float32_fraction():
    q=np.array([0.,.1,.2,.3,.4,np.pi/2])
    state=source.collection_coordinates(q,measured=True)
    assert state.dtype==np.float32 and state[5]==np.float32(.9)
    assert np.array_equal(q,np.array([0.,.1,.2,.3,.4,np.pi/2]))
    with pytest.raises(ValueError):source.collection_coordinates(np.array([0.,0,0,0,0,3.]),measured=True)


def test_source_target_preserves_requested_and_rejects_outside_canonical_gripper():
    from types import SimpleNamespace
    b=SimpleNamespace(limits=np.tile([-4.,4.],(6,1)))
    raw=np.array([0.,0.,0.,0.,0.,-1.])
    assert np.all(source.source_target(raw,b)>=b.limits[:,0]) and np.all(source.source_target(raw,b)<=b.limits[:,1])
    assert raw[5]==-1.
    raw[5]=3.
    assert np.all(source.source_target(raw,b)>=b.limits[:,0]) and np.all(source.source_target(raw,b)<=b.limits[:,1])


def test_source_save_discard_commands_require_actual_recorded_frames():
    events=[];state=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False)
    source.control_commands([dict(command_id='save',kind='save')],state,events.append,tick=0,episode_id='a')
    assert state['save']  # Empty save ends the attempt; collector must never publish zero frames.
    source.control_commands([dict(command_id='save2',kind='save')],state,events.append,tick=3,episode_id='a')
    assert state['save']
    source.control_commands([dict(command_id='discard',kind='discard')],state,events.append,tick=3,episode_id='a')
    assert state['discard']


def test_annotation_requires_recorded_units_phase_and_order():
    from robot_learning_workbench.engines.mujoco.annotation import validate_recording
    from robot_learning_workbench.engines.mujoco.model import JOINTS
    recording=dict(joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30,resolution=[640,480])
    validate_recording(recording)
    for key,value in [('units','degrees'),('observation_phase','post_step'),('joint_order',list(reversed(JOINTS)))]:
        with pytest.raises(ValueError):validate_recording({**recording,key:value})


def test_real_runner_source_resume_cancel_and_device_cleanup(tmp_path):
    import yaml
    from scene_contract.package import load_scene
    from scene_contract.transforms import resolve_transform
    from robot_learning_workbench.robot.calibration import mapper_from_scene,native_from_raw
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    from robot_learning_workbench.engines.mujoco.model import JOINTS
    from robot_learning_workbench.data.native import history
    settings=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text());root=Path(settings['package_root']);scene=load_scene(root/'scene.json')
    mapper=mapper_from_scene(scene,'leader',role='leader',phase='device_observation')
    class RecordedLeader:
        # Fake input device only; state/steps/cameras/Native writer remain real.
        precision_mapper=mapper
        last_raw={n:r['anchor_raw'] for n,r in mapper.profile['joints'].items()}
        closed=False;activated=False
        def connect(self):pass
        def activate(self):self.activated=True
        def read(self):return {n:native_from_raw(self.last_raw[n],mapper.profile['joints'][n]['motor']) for n in JOINTS},(0,0)
        def close(self):self.closed=True
    config=dict(initial_joint_rad=[settings['initial_joint_rad'][n] for n in JOINTS],active_object_ids=['cube_red'],object_physics=json.loads((root/settings['baseline_metadata']['compiled_physics']['asset_path']).read_text())['objects'])
    (tmp_path/'engine.json').write_text(json.dumps(config));(tmp_path/'leader.json').write_text(json.dumps({'calibration_id':'leader'}))
    pose=resolve_transform(scene.scene['frames'],source=scene.scene['objects']['table']['frame_id'],target='world')
    spec=dict(schema_version=1,stage='source',engine='mujoco',inputs={'scene':str(root/'scene.json'),'engine_config':'engine.json','device_profile':'leader.json'},execution={'episodes':1,'seed':7,'episode_time_s':.067,'reset_time_s':0.},output={'directory':'out'},objects={'cube_red':{'placement':{'function':'placement.fixed_xy','params':{'frame':'world','support':'table','xy_m':pose[:2,3].tolist()}}}})
    registry=load_registry(('robot_learning_workbench.tasks.placement',));path=tmp_path/'source.yaml'
    def prepare():path.write_text(yaml.safe_dump(spec));return prepare_recipe(read_recipe(path),tasks=registry)
    device=RecordedLeader();events=[];result=source.run(prepare(),leader=device,events=events.append,commands=lambda:())
    assert result.completed_episodes==1 and device.closed and device.activated
    first=load_catalog(tmp_path/'out');assert 1<=len(read_array(first.episodes[0],'joint_targets'))<=3
    assert events[-1]['kind']=='episode_committed'
    spec['inputs']['resume_dataset']=str(tmp_path/'out');spec['output']['directory']='resumed';spec['execution']['episodes']=2
    device=RecordedLeader();result=source.run(prepare(),leader=device,events=lambda e:None,commands=lambda:())
    assert result.completed_episodes==2 and device.closed
    assert [r['seed'] for r in history(tmp_path/'resumed')]==[7,8]
    assert load_catalog(tmp_path/'out').identity==first.identity
    spec['inputs'].pop('resume_dataset');spec['output']['directory']='cancelled'
    device=RecordedLeader();result=source.run(prepare(),leader=device,events=lambda e:None,commands=lambda:({'command_id':'c','kind':'cancel'},))
    assert result.status=='cancelled' and not load_catalog(tmp_path/'cancelled').episodes and device.closed


def test_actual_annotation_cancel_never_publishes_partial_episode(tmp_path):
    import yaml
    from robot_learning_workbench.engines.mujoco import annotation
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    from robot_learning_workbench.data.native import history
    settings=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text())
    original=ROOT/'docs/evidence/mujoco-workflows/runs-final/source'
    spec=dict(schema_version=1,stage='annotation',engine='mujoco',inputs={'scene':str(Path(settings['package_root'])/'scene.json'),'dataset':str(original)},execution={'mode':'auto'},functions={'acceptance':{'function':'pick_place.v8_annotation','params':{'object':'cube_red','target':'cup_a'}}},output={'directory':str(tmp_path/'cancelled')})
    path=tmp_path/'r.yaml';path.write_text(yaml.safe_dump(spec));registry=load_registry(('robot_learning_workbench.tasks.pick_place',));plan=prepare_recipe(read_recipe(path),tasks=registry)
    events=[]
    def commands():
        if events[-1]['payload']['tick']==2:return ({'command_id':'c','kind':'cancel','episode_id':'recorded-input'},)
        return ()
    result=annotation.run(plan,events=events.append,commands=commands)
    assert result.status=='cancelled' and result.completed_episodes==0
    assert not load_catalog(plan.output_path).episodes
    assert history(plan.output_path)[0]['status']=='cancelled'
    assert not any(e['kind']=='episode_committed' for e in events)


def test_reset_cooldown_rejects_step_without_fake_completion():
    events=[];state=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False,inactive=True)
    source.control_commands([dict(command_id='s',kind='step',payload={'count':1})],state,events.append,tick=3,episode_id='old')
    assert events[-1]['payload']['status']=='rejected' and state['steps']==0
