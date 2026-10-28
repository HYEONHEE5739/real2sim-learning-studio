"""T03 v8 bbox sampling and pose checks; no engine or generic collision placement."""
import json
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench.tasks.placement import sample_uniform_xy, validate_v8_pose
from robot_learning_workbench.tasks.registry import TaskError

ROOT=Path(__file__).resolve().parents[2]
B01=ROOT/'docs/evidence/b01'
W=B01/'runspace/soarm101_lab/outputs/real2sim/environments/scene2_builder/v8'
PROFILE=json.loads((W/'profile.json').read_text());TASK=json.loads((W/'task.json').read_text())
FIXTURE=json.loads((B01/'boundary-fixtures.json').read_text())['reset']
SUPPORT=PROFILE['objects']['marker'];POSE=np.array(SUPPORT['T_workspace']);DIMS=SUPPORT['dimensions_m']
SIZE=PROFILE['objects']['cube_red']['dimensions_m']


def test_b01_uniform_three_batches_positions_and_rng_exact():
    rng=np.random.default_rng(1047)
    assert rng.bit_generator.state==FIXTURE['uniform']['before_rng']
    for batch in FIXTURE['uniform']['samples']:
        placed={};sizes={}
        for name in TASK['dynamic']:
            size=PROFILE['objects'][name]['dimensions_m']
            xyz,attempts=sample_uniform_xy(POSE,DIMS,size,rng,placed,sizes,margin_m=.01,separation_m=.005,clearance_m=.003,object_id=name)
            assert xyz.tolist()==batch['cube_positions'][name]
            assert 1<=attempts<=1000
            placed[name]=xyz;sizes[name]=np.array(size)
    assert rng.bit_generator.state==FIXTURE['uniform']['after_rng']


def test_one_thousand_draw_exhaustion_is_structured_and_does_not_mutate_occupied():
    class Constant:
        def __init__(self):self.calls=0
        def uniform(self,lo,hi):self.calls+=1;return np.zeros(2)
    rng=Constant();occupied={'cube_blue':POSE[:3,3].copy()};before=occupied['cube_blue'].copy()
    with pytest.raises(TaskError) as raised:
        sample_uniform_xy(POSE,DIMS,SIZE,rng,occupied,{'cube_blue':np.array(SIZE)},margin_m=.01,separation_m=.005,clearance_m=.003,object_id='cube_red')
    assert rng.calls==1000
    assert raised.value.code=='PLACEMENT_EXHAUSTED'
    assert raised.value.diagnostics['object_id']=='cube_red'
    assert raised.value.diagnostics['attempts']==1000
    np.testing.assert_array_equal(occupied['cube_blue'],before)


def test_pose_check_old_tolerances_and_rotated_footprint():
    pose=POSE.copy();pose[:3,3]=[POSE[0,3],POSE[1,3],POSE[2,3]+DIMS[2]/2+SIZE[2]/2+.003]
    validate_v8_pose(pose,SIZE,POSE,DIMS,object_id='cube_red')
    bad=pose.copy();bad[0,3]+=1
    with pytest.raises(TaskError):validate_v8_pose(bad,SIZE,POSE,DIMS,object_id='cube_red')
    bad=pose.copy();bad[2,3]=POSE[2,3]+DIMS[2]/2+SIZE[2]/2-2e-6
    with pytest.raises(TaskError):validate_v8_pose(bad,SIZE,POSE,DIMS,object_id='cube_red')

from robot_learning_workbench.tasks import placement
from robot_learning_workbench.tasks.placement import PlacementRequest, PlacementParams, validate_params
from robot_learning_workbench.tasks.registry import load_registry,read_module_names,resolve,validate_params as checked_params

@pytest.fixture
def scene(tmp_path):
    import hashlib
    from scene_contract.package import load_scene
    frames={'world':{'parent':None,'T_parent_from_frame':np.eye(4).tolist(),'state':'reference'},
        'workspace':{'parent':'world','T_parent_from_frame':PROFILE['workspace']['T_world'],'state':'reference'}}
    objects={}
    for name in ['marker',*TASK['dynamic']]:
        p=PROFILE['objects'][name]
        frames[name]={'parent':'workspace','T_parent_from_frame':p['T_workspace'],'state':'reference'}
        objects[name]={'frame_id':name,'role':'environment' if name=='marker' else 'task_object','task_geometry':{'dimensions_m':p['dimensions_m']}}
    data=dict(schema_version=1,scene_id='v8_numeric_fixture',revision='r1',units={'length':'m','angle':'rad','time':'s','mass':'kg'},frames=frames,objects=objects,
        robot={},cameras={},engines={},validation={},supports={'marker_top':{'object_id':'marker','placement_frame_id':'workspace'}},calibration='calibration.json',manifest='manifest.json')
    (tmp_path/'scene.json').write_text(json.dumps(data));(tmp_path/'calibration.json').write_text(json.dumps({'schema_version':1,'records':{},'evidence':{}}))
    entries=[dict(path=p.name,size_bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (tmp_path/'scene.json',tmp_path/'calibration.json')]
    (tmp_path/'manifest.json').write_text(json.dumps({'schema_version':1,'files':entries}))
    return load_scene(tmp_path/'scene.json')


def params(scene,name='cube_red',**overrides):
    p=PlacementParams(name,'workspace','marker_top',**overrides);validate_params(p,scene);return p


def request(name='cube_red',**values):
    return PlacementRequest(name,'workspace','marker_top',**values)


def test_fixed_exact_xy_old_height_default_orientation_and_no_rng(scene):
    p=params(scene);xy=tuple(POSE[:2,3])
    r=placement.fixed_xy(request(xy_m=xy),params=p)
    assert tuple(r.pose[:2,3])==xy
    assert r.pose[2,3]==POSE[2,3]+DIMS[2]/2+SIZE[2]/2+.003
    np.testing.assert_array_equal(r.pose[:3,:3],np.array(PROFILE['objects']['cube_red']['T_workspace'])[:3,:3])
    assert r.attempts==0 and r.rules_id=='v8_preserved'
    with pytest.raises(ValueError):r.pose[0,3]=99


def test_registered_random_order_and_rng_match_b01(scene):
    registry=load_registry(read_module_names(ROOT/'robot_learning_workbench/task_modules.yaml'))
    fn=resolve(registry,'placement.random_xy',kind='placement',stage='source',engine='isaac').callable
    rng=np.random.default_rng(1047)
    for batch in FIXTURE['uniform']['samples']:
        occupied={}
        for name in TASK['dynamic']:
            p=checked_params(registry,'placement.random_xy',{'object':name,'frame':'workspace','support':'marker_top'},kind='placement',stage='source',engine='isaac',scene=scene)
            result=fn(request(name,rng=rng,occupied_poses=occupied),params=p)
            assert result.pose[:3,3].tolist()==batch['cube_positions'][name]
            occupied[name]=result.pose
    assert rng.bit_generator.state==FIXTURE['uniform']['after_rng']


@pytest.mark.parametrize('xy',[(100.,0.),(float('nan'),0.),(0.,),('x',0.)])
def test_fixed_invalid_does_not_adjust(scene,xy):
    with pytest.raises(TaskError) as error:placement.fixed_xy(request(xy_m=xy),params=params(scene))
    assert error.value.code=='INVALID_PLACEMENT'


def test_fixed_overlap_and_random_explicit_orientation_are_not_corrected(scene):
    p=params(scene);r=placement.fixed_xy(request(xy_m=tuple(POSE[:2,3])),params=p)
    with pytest.raises(TaskError):placement.fixed_xy(request(xy_m=tuple(POSE[:2,3]),occupied_poses={'cube_blue':r.pose}),params=p)
    rot=np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]])
    result=placement.random_xy(request(rng=np.random.default_rng(1047),orientation=rot),params=p)
    np.testing.assert_array_equal(result.pose[:3,:3],rot)


def test_geometry_binding_uses_exact_parent_relative_values(scene):
    p=params(scene)
    np.testing.assert_array_equal(p._context['support_pose'],POSE)
    np.testing.assert_array_equal(p._context['object_pose'],PROFILE['objects']['cube_red']['T_workspace'])
    with pytest.raises(ValueError):p._context['support_pose'][0,3]=0

@pytest.mark.parametrize('delta,allowed',[(-1e-12,False),(0.,False),(1e-12,True)])
def test_strict_separation_equality_and_single_axis_escape(delta,allowed):
    class Rng:
        def __init__(self):self.calls=0
        def uniform(self,lo,hi):self.calls+=1;return np.array([0.,.029+delta])
    rng=Rng();kwargs=dict(margin_m=.01,separation_m=.005,clearance_m=.003,object_id='red')
    if allowed:
        _,count=sample_uniform_xy(np.eye(4),DIMS,SIZE,rng,{'blue':np.zeros(3)},{'blue':np.array(SIZE)},**kwargs)
        assert count==rng.calls==1
    else:
        with pytest.raises(TaskError) as e:sample_uniform_xy(np.eye(4),DIMS,SIZE,rng,{'blue':np.zeros(3)},{'blue':np.array(SIZE)},**kwargs)
        assert e.value.code=='PLACEMENT_EXHAUSTED' and rng.calls==1000


@pytest.mark.parametrize('draw',[np.array([np.nan,0]),np.array([np.inf,0]),np.array([0.]),True,np.array([1e3,0.])])
def test_bad_rng_response_is_not_retryable(draw):
    class Bad:
        calls=0
        def uniform(self,lo,hi):self.calls+=1;return draw
    rng=Bad()
    with pytest.raises(TaskError) as e:sample_uniform_xy(POSE,DIMS,SIZE,rng,{}, {},margin_m=.01,separation_m=.005,clearance_m=.003,object_id='red')
    assert e.value.code=='INVALID_PLACEMENT' and rng.calls==1


def test_no_fit_fails_before_drawing_and_seed_never_restored_on_exhaustion(scene):
    class NoDraw:
        def uniform(self,*args):raise AssertionError('invalid geometry must not consume RNG')
    with pytest.raises(TaskError) as e:sample_uniform_xy(POSE,DIMS,DIMS,NoDraw(),{}, {},margin_m=0,separation_m=0,clearance_m=.003,object_id='red')
    assert e.value.diagnostics['attempts']==0
    rng=np.random.default_rng(1047);reference=np.random.default_rng(1047)
    fixed=placement.fixed_xy(request(xy_m=tuple(POSE[:2,3])),params=params(scene))
    with pytest.raises(TaskError) as e:placement.random_xy(request(rng=rng,occupied_poses={'cube_blue':fixed.pose}),params=params(scene,separation_m=1.))
    for _ in range(1000):reference.uniform(-np.array([.053,.053]),np.array([.053,.053]))
    assert rng.bit_generator.state==reference.bit_generator.state
    assert e.value.diagnostics['support_id']=='marker_top' and e.value.diagnostics['rules_id']=='v8_preserved'


@pytest.mark.parametrize('override',[{'object_id':'wrong'},{'frame_id':'world'},{'rules_id':'collision_contact'},{'orientation':np.zeros((3,3))}])
def test_request_identity_rotation_or_rule_errors_before_rng(scene,override):
    from dataclasses import replace
    class NoDraw:
        def uniform(self,*args):raise AssertionError('must reject before drawing')
    req=replace(request(rng=NoDraw()),**override)
    with pytest.raises(TaskError):placement.random_xy(req,params=params(scene))


def test_v8_sampler_does_not_retry_a_later_rotated_support_pose_failure(scene):
    class Once:
        calls=0
        def uniform(self,lo,hi):self.calls+=1;return np.zeros(2)
    rng=Once();a=np.pi/4;rot=np.array([[1,0,0],[0,np.cos(a),-np.sin(a)],[0,np.sin(a),np.cos(a)]])
    result=placement.random_xy(request(rng=rng,orientation=rot),params=params(scene))
    with pytest.raises(TaskError):validate_v8_pose(result.pose,SIZE,POSE,DIMS,object_id='cube_red')
    assert rng.calls==result.attempts==1


@pytest.mark.parametrize('overrides',[{'rules':'four_anchors'},{'rules':'collision_contact'},{'clearance_m':.004},{'margin_m':-1},{'separation_m':float('nan')},{'frame':'world'}])
def test_only_approved_rules_and_placement_frame_supported(scene,overrides):
    registry=load_registry(('robot_learning_workbench.tasks.placement',))
    with pytest.raises(TaskError):checked_params(registry,'placement.random_xy',{'object':'cube_red','frame':'workspace','support':'marker_top'}|overrides,kind='placement',stage='source',scene=scene)


from robot_learning_workbench.tasks.placement import environment_seed

@pytest.mark.parametrize('count,index',[(1,0),(2,0),(2,1),(7,6)])
def test_original_per_env_seed_rule(count,index):
    expected=1047 if count==1 else int(np.random.SeedSequence([1047,index]).generate_state(1)[0])
    assert environment_seed(1047,index,num_envs=count)==expected


def test_annotation_restore_is_not_a_random_reset_stage():
    registry=load_registry(('robot_learning_workbench.tasks.placement',))
    with pytest.raises(TaskError) as e:resolve(registry,'placement.random_xy',kind='placement',stage='annotation',engine='mujoco')
    assert e.value.code=='TASK_UNSUPPORTED'


@pytest.mark.parametrize('seed,index,count',[(True,0,1),(-1,0,1),(1,True,1),(1,1,1),(1,0,0)])
def test_invalid_seed_context_is_structured(seed,index,count):
    with pytest.raises(TaskError):environment_seed(seed,index,num_envs=count)
