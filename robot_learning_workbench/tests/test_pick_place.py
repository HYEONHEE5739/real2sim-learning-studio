"""Offline T02 contracts, using immutable B01 inputs; no engine/device execution."""
import json
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench.tasks.pick_place import StableGrasp

ROOT=Path(__file__).resolve().parents[2]
B01=ROOT/'docs/evidence/b01'
BOUNDARY=json.loads((B01/'boundary-fixtures.json').read_text())

@pytest.mark.parametrize('case',BOUNDARY['grasp'])
def test_b01_all_stable_grasp_rows_and_latch(case):
    expected=BOUNDARY['grasp'][case]
    dt={'hold_below':.05-1e-8,'hold_above':.05+1e-8}.get(case,.05)  # B01 boundary harness inputs
    tracker=StableGrasp(dt,[.024]*3)
    for row in expected['rows']:
        assert tracker.observe(*row['input'])==row['result']
        assert tracker.details==row['details']
        assert len(tracker.samples)==row['window_samples']
    details=tracker.details.copy()
    assert tracker.observe(4,[1,0,0],[1,0,0,0],[0,0,0],[0,0,0],False,False)==expected['duplicate_tick_result']
    assert tracker.details==details
    assert tracker.observe(5,[0,0,0],[1,0,0,0],[0,0,0],[0,0,0],False,False)==expected['after_contact_loss_latched']


def feed(t,i):
    return t.observe(i,[0,0,.02],[1,0,0,0],[i*.002,0,0],[i*.002,0,.02],True,True)


def test_gap_clears_window_without_cancelling_latch_and_new_episode_is_fresh():
    tracker=StableGrasp(.05,None)
    for i in range(4):assert not feed(tracker,i)
    assert not feed(tracker,5)
    assert len(tracker.samples)==1
    for i in range(6,9):assert not feed(tracker,i)
    assert feed(tracker,9)
    assert feed(tracker,15)
    assert tracker.completed and len(tracker.samples)==1
    assert not feed(StableGrasp(.05,None),0)


def test_window_owns_copies_and_size_does_not_change_detection():
    tracker=StableGrasp(.05,[1e6]*3)
    a=np.array([0.,0.,.02]);tracker.observe(0,a,[1,0,0,0],[0,0,0],a,True,True)
    a[:]=99
    assert tracker.samples[0][0].tolist()==[0,0,.02]
    assert tracker.samples[0][3].tolist()==[0,0,.02]
    for i in range(1,12):feed(tracker,i)
    assert tracker.completed
    assert len(tracker.samples)<=int(np.ceil(.2/.05))+1

from robot_learning_workbench.tasks.pick_place import PlacementGeometry, numpy_corners, placement_details

PROFILE=json.loads((B01/'runspace/soarm101_lab/outputs/real2sim/environments/scene2_builder/v8/profile.json').read_text())
CUP=PROFILE['objects']['cup_a_visual']
GEOMETRY=PlacementGeometry(tuple(PROFILE['objects']['cube_red']['dimensions_m']),tuple(CUP['dimensions_m']),CUP['wall_m'],CUP['bottom_diameter_m'])

@pytest.mark.parametrize('row',BOUNDARY['placement'],ids=lambda row:row['case'])
def test_b01_placement_snapshots(row):
    # Use the captured fixed target, not the cube after its quaternion round-trip.
    trace=(json.loads(line) for line in (B01/'runs/annotation_mujoco_A/trace.jsonl').open())
    target=np.array(next(row for row in trace if row['event']=='reset')['result']['object_poses']['cup_a']['values'])
    points=numpy_corners(np.array(row['actual_object_pose']),target,GEOMETRY.object_dimensions_m)
    actual=placement_details(points,np.array([row['requested_speed'],0.,0.]),GEOMETRY)
    for key in ('height_ok','wall_ok','speed_ok','success'):
        assert actual[key]==row['result'][key]
    assert actual['speed_m_s']==row['result']['speed_m_s']
    assert actual['radial_excess_m']==row['result']['radial_excess_m']


def test_region_inclusive_and_speed_strict_and_rotated_corners():
    points=np.array([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)],dtype=float)
    assert placement_details(points,np.zeros(3),GEOMETRY,relation='inside_region_and_settled',bounds_m=((-1,-1,-1),(1,1,1)))['success']
    assert not placement_details(points,np.array([.03,0,0]),GEOMETRY,relation='inside_region_and_settled',bounds_m=((-1,-1,-1),(1,1,1)))['success']
    pose=np.eye(4);pose[:2,:2]=[[0,-1],[1,0]]
    result=numpy_corners(pose,np.eye(4),(.02,.04,.06))
    np.testing.assert_array_equal(result[0],[.02,-.01,-.03])

from robot_learning_workbench.tasks.registry import TaskError


def test_tensor_speed_equality_uses_tensor_threshold_rounding():
    import torch
    points=torch.zeros((8,3),dtype=torch.float32)
    # float32(.03) is below Python float(.03), but original Tensor comparison is equal.
    result=placement_details(points,torch.tensor([.03,0,0],dtype=torch.float32),GEOMETRY)
    assert result['speed_ok'] is False


@pytest.mark.parametrize('relation',['unknown','',None])
def test_unknown_placement_relation_does_not_fall_back(relation):
    with pytest.raises(TaskError):placement_details(np.zeros((8,3)),np.zeros(3),GEOMETRY,relation=relation)


from robot_learning_workbench.tasks.pick_place import create_stable_grasp, GraspParams


def sample(tick,params=None):
    return dict(episode_id='episode',env_index=0,tick=tick,phase='post_step',dt_s=.05,
        grasp_inputs=dict(object_id='red',relative=[0,0,.02],relative_quat=[1,0,0,0],
            ee_position=[tick*.002,0,0],object_position=[tick*.002,0,.02],quaternion_order='wxyz'),
        contacts=dict(left=True,right=True,source_definition='mujoco_body_pair_dist_le_0'))


def test_factory_post_step_update_and_pre_step_snapshot_are_distinct():
    tracker=create_stable_grasp(params=GraspParams('red'),episode=dict(episode_id='episode',env_index=0,control_dt_s=.05))
    stored=[];signals=[]
    for tick in range(7):
        stored.append(tracker.completed)
        signals.append(tracker.update(sample(tick)))
    assert next(i for i,x in enumerate(signals) if x.value)==4
    assert next(i for i,x in enumerate(stored) if x)==5
    assert signals[0].value is False
    assert signals[4].phase=='post_step' and signals[4].tick==4
    assert signals[4].diagnostics['object_id']=='red'
    with pytest.raises(TypeError):signals[4].diagnostics['stable']=False
    other=create_stable_grasp(params=GraspParams('red'),episode=dict(episode_id='other',env_index=1,control_dt_s=.05))
    assert other.completed is False


@pytest.mark.parametrize('change',[
    {'phase':'pre_step'},{'tick':True},{'episode_id':'wrong'},{'env_index':1},{'dt_s':.01},
    {'contacts':{'left':None,'right':True,'source_definition':'mujoco_body_pair_dist_le_0'}},
    {'contacts':{'left':True,'right':True,'source_definition':''}},
    {'grasp_inputs':{'object_id':'red'}},
])
def test_tracker_bad_live_inputs_do_not_advance_state(change):
    tracker=create_stable_grasp(params=GraspParams('red'),episode=dict(episode_id='episode',env_index=0,control_dt_s=.05))
    with pytest.raises(TaskError):tracker.update(sample(0)|change)
    assert tracker.last_tick is None and not tracker.samples

from robot_learning_workbench.tasks.registry import load_registry,read_module_names,resolve,validate_params
from robot_learning_workbench.tasks.pick_place import PickPlaceParams,SignalValue,grasp_and_placement,v8_placement
from test_task_registry import scene

@pytest.fixture
def task_scene(scene):
    import hashlib
    from scene_contract.package import load_scene
    root=scene.root;data=json.loads((root/'scene.json').read_text())
    data['objects']['red']['task_geometry']={'dimensions_m':list(GEOMETRY.object_dimensions_m)}
    data['objects']['cup']['task_geometry']={'dimensions_m':list(GEOMETRY.target_dimensions_m),
        'wall_m':GEOMETRY.wall_m,'bottom_diameter_m':GEOMETRY.bottom_diameter_m}
    (root/'scene.json').write_text(json.dumps(data))
    manifest=json.loads((root/'manifest.json').read_text())
    for entry in manifest['files']:
        path=root/entry['path'];entry.update(size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (root/'manifest.json').write_text(json.dumps(manifest))
    return load_scene(root/'scene.json')


def prepared(registry,scene,name='pick_place.v8_annotation',stage='annotation'):
    spec=resolve(registry,name,kind='acceptance' if stage!='simulation_evaluation' else 'predicate',stage=stage,engine='mujoco')
    p=validate_params(registry,name,{'object':'red','target':'cup'},kind=spec.kind,stage=stage,engine='mujoco',scene=scene,selected_objects=('red',))
    return spec,p


def final_sample(grasp=True,placed=True):
    points=np.zeros((8,3))
    if not placed:points[:,0]=1
    return dict(tick=10,phase='episode_end',placement_points={'red':{'target_id':'cup','points':points}},
        linear_velocities={'red':np.zeros(3)},signals={'grasp':SignalValue(grasp,9,'post_step',{'object_id':'red'})})


def test_default_list_registers_v8_plain_functions_without_engine_import(task_scene):
    r=load_registry(read_module_names(ROOT/'robot_learning_workbench/task_modules.yaml'))
    spec,p=prepared(r,task_scene)
    assert spec.callable is grasp_and_placement
    assert p._geometry==GEOMETRY
    assert spec.callable(final_sample(),params=p) is True
    assert not spec.callable(final_sample(grasp=False),params=p)
    assert not spec.callable(final_sample(placed=False),params=p)
    evaluation,e=prepared(r,task_scene,'pick_place.v8_evaluation','simulation_evaluation')
    s=final_sample(grasp=False);s['phase']='post_step'
    assert evaluation.callable(s,params=e) is True  # Placement-only, regardless of grasp.
    with pytest.raises(TaskError):resolve(r,'pick_place.v8_annotation',kind='acceptance',stage='source',engine='mujoco')
    assert not any('source' in spec.stages for name,spec in r.functions.items() if name.startswith('pick_place.'))


@pytest.mark.parametrize('stage,name',[('annotation','pick_place.v8_annotation'),('datagen','pick_place.v8_datagen')])
@pytest.mark.parametrize('grasp,placed',[(False,False),(False,True),(True,False),(True,True)])
def test_physical_acceptance_truth_table(task_scene,stage,name,grasp,placed):
    r=load_registry(('robot_learning_workbench.tasks.pick_place',));spec,p=prepared(r,task_scene,name,stage)
    assert spec.callable(final_sample(grasp,placed),params=p)==(grasp and placed)


def test_missing_or_unbound_input_is_not_false_success(task_scene):
    r=load_registry(('robot_learning_workbench.tasks.pick_place',));spec,p=prepared(r,task_scene)
    for changed in ({'signals':{}},{'signals':{'grasp':None}},{'signals':{'grasp':SignalValue(True,11,'post_step',{'object_id':'red'})}}):
        with pytest.raises(TaskError):spec.callable(final_sample()|changed,params=p)
    with pytest.raises(TaskError):v8_placement(final_sample(),params=PickPlaceParams('red','cup'))


@pytest.mark.parametrize('points,velocity',[(np.zeros((7,3)),np.zeros(3)),(np.full((8,3),np.nan),np.zeros(3)),(np.zeros((8,3)),np.full(3,np.inf))])
def test_bad_placement_arrays_rejected(points,velocity):
    with pytest.raises(TaskError):placement_details(points,velocity,GEOMETRY)

@pytest.mark.parametrize('dt',[0,-1,float('nan'),float('inf'),'0.05',True])
def test_invalid_factory_period(dt):
    with pytest.raises(TaskError):create_stable_grasp(params=GraspParams('red'),episode=dict(episode_id='episode',env_index=0,control_dt_s=dt))


def test_invalid_signal_is_not_coerced_to_boolean(task_scene):
    r=load_registry(('robot_learning_workbench.tasks.pick_place',));spec,p=prepared(r,task_scene)
    s=final_sample();s['signals']['grasp']=SignalValue(None,9,'post_step',{'object_id':'red'})
    with pytest.raises(TaskError):spec.callable(s,params=p)


def test_geometry_is_not_recipe_input_and_conventions_do_not_change_mid_episode(task_scene):
    r=load_registry(('robot_learning_workbench.tasks.pick_place',))
    with pytest.raises(TaskError):validate_params(r,'pick_place.v8_annotation',{'object':'red','target':'cup','_geometry':{}},kind='acceptance',stage='annotation',scene=task_scene)
    tracker=create_stable_grasp(params=GraspParams('red'),episode=dict(episode_id='episode',env_index=0,control_dt_s=.05))
    tracker.update(sample(0));s=sample(1);s['grasp_inputs']['quaternion_order']='xyzw'
    with pytest.raises(TaskError):tracker.update(s)
    assert tracker.last_tick==0


from robot_learning_workbench.tasks.pick_place import release_evidence


def test_release_and_drop_diagnostics_never_cancel_completed_grasp():
    tracker=StableGrasp(.05,None)
    for i in range(5):feed(tracker,i)
    state=(None,None,False,0,None)
    state=release_evidence(tracker,[0,0,0],[True,True],[0]*6,4,20,*state)
    for i in range(5,9):state=release_evidence(tracker,[.01,0,0],[False,False],[0]*6,i,20,*state)
    assert state[-1]==8 and tracker.completed
    opened=release_evidence(tracker,[.01,0,0],[False,False],[0]*5+[.001],9,20,*state)
    assert opened[2] and opened[3]==0 and tracker.completed

from robot_learning_workbench.tasks.pick_place import object_metrics

@pytest.mark.parametrize('movement',[.04-1e-9,.04,.04+1e-9])
def test_evaluation_transport_remains_separate_from_placement(movement):
    state={};p={'red':np.array([movement,0.,0.])}
    result=object_metrics(['red'],'red',p,np.zeros(3),state,grasp=True,place=True,initial_positions={'red':np.zeros(3)})
    assert result['place_success'] is True
    assert result['transport_success']==(movement>.04)
    assert result['full_task_success']==(movement>.04)
    assert result['target_selection_accuracy'] is None
    assert result['wrong_object_approach'] is None


def test_wrong_target_corner_input_rejected(task_scene):
    r=load_registry(('robot_learning_workbench.tasks.pick_place',));spec,p=prepared(r,task_scene)
    s=final_sample();s['placement_points']['red']={'target_id':'another_cup','points':np.zeros((8,3))}
    with pytest.raises(TaskError):spec.callable(s,params=p)


def test_explicit_target_corner_input_accepted(task_scene):
    r=load_registry(('robot_learning_workbench.tasks.pick_place',));spec,p=prepared(r,task_scene)
    s=final_sample();s['placement_points']['red']={'target_id':'cup','points':np.zeros((8,3))}
    assert spec.callable(s,params=p) is True


def test_bound_geometry_parameters_cannot_change_object_after_validation(task_scene):
    from dataclasses import FrozenInstanceError
    r=load_registry(('robot_learning_workbench.tasks.pick_place',));_,params=prepared(r,task_scene)
    with pytest.raises(FrozenInstanceError):params.object='blue'
