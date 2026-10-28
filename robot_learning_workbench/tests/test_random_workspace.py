"""Workspace entropy policy and true convex-footprint geometry, without physics."""
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from scene_contract.package import load_scene
from robot_learning_workbench.tasks import placement as p
from robot_learning_workbench.tasks.registry import TaskError

@pytest.fixture(scope='module')
def scene():
    return load_scene(Path(__file__).resolve().parents[2]/'docs/evidence/e01-v8-collision/runspace/relocated/scene-v8-native/scene.json')

def params(scene, **kw):
    obj=p.WorkspaceParams('cube_red','object_marker','table','marker',**kw)
    p.validate_params(obj,scene)
    return obj

def request(q, **kw):
    return p.PlacementRequest(q.object,q.frame,q.support,rules_id=q.rules,**kw)

def test_geometry_limits_are_derived_from_150mm_and_24mm(scene):
    q=params(scene);lo,hi=q._context['bounds']
    np.testing.assert_allclose(lo,[-.063,-.063],rtol=0,atol=1e-15)
    np.testing.assert_allclose(hi,[.063,.063],rtol=0,atol=1e-15)
    with patch.object(np.random,'default_rng',return_value=np.random.Generator(np.random.PCG64(4))) as factory:
        result=p.random_workspace(request(q),params=q)
    factory.assert_called_once_with()
    assert result.diagnostics['valid'] and not result.diagnostics['physical_collision_checked']
    assert 'seed' not in result.diagnostics
    assert result.pose[2,3]==pytest.approx(.01175,abs=1e-15)
    np.testing.assert_array_equal(result.pose[:3,:3],np.eye(3))

def test_yaw_uses_rotated_footprint(scene):
    q=params(scene,yaw_rad=np.pi/4)
    np.testing.assert_allclose(q._context['bounds'][1],[.075-.012*np.sqrt(2)]*2,rtol=0,atol=1e-15)

def test_gap_is_surface_distance_including_diagonal():
    square=np.array([[-.012,-.012],[.012,-.012],[.012,.012],[-.012,.012]])
    assert p.polygon_distance(square,square+[.048,0])==pytest.approx(.024)
    assert p.polygon_distance(square,square+[.04,.04])==pytest.approx(np.sqrt(2)*.016)
    assert p.polygon_distance(square,square+[.042,.042])>.024

def test_random_rejects_explicit_rng_or_orientation(scene):
    q=params(scene)
    for extra in ({'rng':np.random.default_rng(3)},{'orientation':np.eye(3)},{'xy_m':(0,0)}):
        with pytest.raises(TaskError,match='Seed|RNG|orientation|XY'):p.random_workspace(request(q,**extra),params=q)

def test_occupied_identical_candidate_exhausts_without_effect(scene):
    q=params(scene);center=np.eye(4);center[2,3]=.01175
    class Constant:
        def uniform(self,lo,hi):return np.zeros(2)
    with patch.object(np.random,'default_rng',return_value=Constant()):
        with pytest.raises(TaskError) as caught:p.random_workspace(request(q,occupied_poses={'cube_blue':center}),params=q)
    assert caught.value.code=='INVALID_PLACEMENT'
    assert caught.value.diagnostics['attempts']==p.MAX_ATTEMPTS
    np.testing.assert_array_equal(center[:2,3],[0,0])


def test_batch_builds_all_before_effect_and_records_local_world(scene):
    from types import SimpleNamespace
    bindings={}
    for name in ('cube_red','cube_blue','cube_green'):
        q=p.WorkspaceParams(name,'object_marker','table','marker');p.validate_params(q,scene)
        bindings['objects.'+name+'.placement']=SimpleNamespace(name='placement.random_workspace',kind='placement',params=q,request_fields={})
    plan=SimpleNamespace(scene=scene,object_order=('cube_red','cube_blue','cube_green'),function_bindings=bindings)
    with patch.object(np.random,'default_rng',return_value=np.random.Generator(np.random.PCG64(9))):
        poses,records=p.workspace_reset_poses(plan,{})
    assert len(poses)==len(records)==3
    inverse=np.linalg.inv(p._reference_pose(scene,'object_marker','world'))
    polygons=[]
    for name,pose in poses:
        local=inverse@pose
        np.testing.assert_allclose(local,records[name]['local_pose'],atol=1e-15)
        v=np.concatenate(p._workspace_parts(scene,name))@local[:3,:3].T+local[:3,3]
        assert np.max(abs(v[:,:2]))<=.075+1e-16
        polygons.append(p._hull(v[:,:2]))
    assert all(p.polygon_distance(a,b)>=.024 for i,a in enumerate(polygons) for b in polygons[i+1:])


def test_actual_mujoco_reset_uses_entropy_and_applies_whole_batch(tmp_path):
    import yaml,mujoco
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    from robot_learning_workbench.engines.mujoco.datagen import load_inputs
    from robot_learning_workbench.engines.mujoco.model import build_model
    from robot_learning_workbench.engines.mujoco.source import reset_placements
    from robot_learning_workbench.engines.mujoco.state import restore_episode
    root=Path(__file__).resolve().parents[2]
    spec=yaml.safe_load((root/'docs/evidence/simulation-workflows/mujoco-worker-final.yaml').read_text())
    spec['output']['directory']=str(tmp_path/'dataset')
    for item in spec['objects'].values():item['placement']={'function':'placement.random_workspace','params':{'frame':'object_marker','support':'table','workspace':'marker'}}
    path=tmp_path/'r.yaml';path.write_text(yaml.safe_dump(spec,sort_keys=False));plan=prepare_recipe(read_recipe(path),tasks=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement')))
    _,_,cfg,_=load_inputs(plan);model,b=build_model(plan.scene,cfg);data=mujoco.MjData(model);restore_episode(model,data,b,None)
    with patch.object(np.random,'default_rng',side_effect=lambda *a,**kw:np.random.Generator(np.random.PCG64(9))) as rng:
        records=reset_placements(plan,model,data,b,1047)
    assert all(call.args==() and call.kwargs=={} for call in rng.call_args_list)
    assert set(records)==set(spec['objects'])
    for name,row in records.items():
        assert row['applied'] and row['validation']['valid']
        np.testing.assert_array_equal(row['applied_world_pose'],row['observed_world_pose'])
    assert not any(c.dist<-1e-6 and (model.geom_bodyid[c.geom1] in [b.object_body_ids[n] for n in spec['objects']] or model.geom_bodyid[c.geom2] in [b.object_body_ids[n] for n in spec['objects']]) for c in data.contact)


def test_isaac_accepts_new_entropy_rule_but_retains_legacy_gate():
    from types import SimpleNamespace
    from robot_learning_workbench.engines.isaac.datagen import validate_placements
    validate_placements(SimpleNamespace(function_bindings={'p':SimpleNamespace(kind='placement',name='placement.random_workspace')}))
    with pytest.raises(ValueError):validate_placements(SimpleNamespace(function_bindings={'p':SimpleNamespace(kind='placement',name='placement.random_xy')}))


def test_batch_rejects_recipe_overrides_instead_of_ignoring(scene):
    from types import SimpleNamespace
    q=params(scene)
    b=SimpleNamespace(name='placement.random_workspace',kind='placement',params=q,request_fields={'xy_m':[0,0]})
    plan=SimpleNamespace(scene=scene,object_order=('cube_red',),function_bindings={'objects.cube_red.placement':b})
    with pytest.raises(TaskError,match='override'):p.workspace_reset_poses(plan,{})

@pytest.mark.parametrize('dimensions',[(0,.024,.024),(-.024,.024,.024),(.024,np.inf,.024)])
def test_geometry_rejects_invalid_dimensions(scene,dimensions):
    from types import SimpleNamespace
    objects=dict(scene.scene['objects']);obj=dict(objects['cube_red']);obj['collision']={**obj['collision'],'dimensions_m':dimensions};objects['cube_red']=obj
    s=SimpleNamespace(scene={**scene.scene,'objects':objects})
    with pytest.raises(ValueError):p._workspace_parts(s,'cube_red')


def test_result_evidence_is_deeply_immutable(scene):
    q=params(scene)
    with patch.object(np.random,'default_rng',return_value=np.random.Generator(np.random.PCG64(9))):
        result=p.random_workspace(request(q),params=q)
    with pytest.raises(TypeError):result.diagnostics['bounds_m'][0][0]=99
    with pytest.raises(TypeError):result.diagnostics['surface_distances_m']['invented']=0


def _random_plan(tmp_path):
    import yaml
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    root=Path(__file__).resolve().parents[2]
    spec=yaml.safe_load((root/'docs/evidence/simulation-workflows/mujoco-worker-final.yaml').read_text())
    for item in spec['objects'].values():item['placement']={'function':'placement.random_workspace','params':{'frame':'object_marker','support':'table','workspace':'marker'}}
    spec['output']['directory']=str(tmp_path/'dataset');spec['execution']['max_attempts']=1
    path=tmp_path/'r.yaml';path.write_text(yaml.safe_dump(spec,sort_keys=False))
    return prepare_recipe(read_recipe(path),tasks=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement')))


def test_invalid_candidates_close_attempt_without_episode_or_unknown_claim(tmp_path):
    from robot_learning_workbench.engines.mujoco.datagen import run
    from robot_learning_workbench.data.native import load_catalog,history
    plan=_random_plan(tmp_path)
    def reject(*args,**kw):p._fail('INVALID_PLACEMENT','cube_red','Impossible controlled fixture',attempts=1000)
    with patch.object(p,'workspace_reset_poses',side_effect=reject):
        result=run(plan,events=lambda _:None,commands=lambda:())
    assert result.completed_episodes==0 and result.attempt_summary['budget_exhausted']
    assert not load_catalog(plan.output_path).episodes
    rows=history(plan.output_path);assert len(rows)==1 and rows[0]['status']=='failure'
    assert rows[0]['diagnostics']['code']=='INVALID_PLACEMENT'


def test_engine_reset_exception_is_not_candidate_rejection(tmp_path):
    from robot_learning_workbench.engines.mujoco.datagen import run
    from robot_learning_workbench.data.native import load_catalog,history
    plan=_random_plan(tmp_path);error=ValueError('Controlled SDK state error');error.placement_records={'cube_red':{'applied':'unknown'}}
    with patch('robot_learning_workbench.engines.mujoco.source.reset_placements',side_effect=error):
        with pytest.raises(ValueError,match='SDK state'):run(plan,events=lambda _:None,commands=lambda:())
    assert not load_catalog(plan.output_path).episodes
    rows=history(plan.output_path);assert rows[0]['diagnostics']['category']=='engine_reset_error'
    assert rows[0]['diagnostics']['effect']=='unknown'
    assert rows[0]['diagnostics']['placements']['cube_red']['applied']=='unknown'


def test_float32_native_pose_cannot_reduce_minimum_surface_gap(scene):
    from scipy.spatial.transform import Rotation
    from types import SimpleNamespace
    bindings={};poses=[]
    for name,x in [('cube_red',-.06),('cube_blue',-.012)]:
        q=p.WorkspaceParams(name,'object_marker','table','marker');p.validate_params(q,scene)
        bindings['objects.'+name+'.placement']=SimpleNamespace(name='placement.random_workspace',params=q)
        pose,_=p.contact_pose(q._context['parts'],np.eye(3),[x,-.04105263157894737],q._context['support_pose'])
        w=p._reference_pose(scene,'object_marker','world')@pose
        quat=Rotation.from_matrix(w[:3,:3]).as_quat()[[3,0,1,2]];payload=np.r_[w[:3,3],quat].astype(np.float32)
        w=np.eye(4);w[:3,3]=payload[:3];w[:3,:3]=Rotation.from_quat(payload[[4,5,6,3]]).as_matrix();poses.append((name,w))
    plan=SimpleNamespace(scene=scene,object_order=tuple(n for n,_ in poses),function_bindings=bindings)
    with pytest.raises(TaskError,match='payload'):p.validate_workspace_payload(plan,poses,{})


def test_changed_geometry_and_workspace_recompute_bounds(scene):
    from types import SimpleNamespace
    objects=dict(scene.scene['objects'])
    for name,dims in [('cube_red',[.03,.04,.05]),('marker',[.2,.18,.0005])]:
        obj=dict(objects[name]);obj['collision']={**obj['collision'],'dimensions_m':dims};objects[name]=obj
    q=params(SimpleNamespace(scene={**scene.scene,'objects':objects}))
    np.testing.assert_allclose(q._context['bounds'][1],[.085,.07],rtol=0,atol=1e-15)


def test_less_than_24mm_gap_and_pose_seed_are_not_supported(scene):
    with pytest.raises(ValueError):params(scene,separation_m=.023)
    with pytest.raises(TypeError):p.WorkspaceParams('cube_red','object_marker','table','marker',seed=1047)


def test_isaac_partial_reset_error_marks_per_object_application_unknown(tmp_path):
    """Controlled SDK error path only; never counted as real Isaac execution."""
    from types import SimpleNamespace
    from robot_learning_workbench.engines.isaac.source import reset_placements
    plan=_random_plan(tmp_path)
    initial={'rigid_object':{n:{'root_pose':np.array([[0.,0.,0.,1.,0.,0.,0.]]),'root_velocity':np.zeros((1,6))} for n in plan.object_order}}
    import torch
    env=SimpleNamespace(scene=SimpleNamespace(env_origins=torch.zeros((1,3))),cfg=SimpleNamespace(workbench_inputs={'compiled_physics':{'objects':{}}}))
    with patch('robot_learning_workbench.engines.isaac.source.initial_state',return_value=initial), \
         patch('robot_learning_workbench.engines.isaac.state.restore_episode',side_effect=RuntimeError('SDK partial write')), \
         patch.object(np.random,'default_rng',return_value=np.random.Generator(np.random.PCG64(9))):
        with pytest.raises(RuntimeError,match='partial write') as caught:reset_placements(plan,env,None)
    assert all(row['applied']=='unknown' for row in caught.value.placement_records.values())
