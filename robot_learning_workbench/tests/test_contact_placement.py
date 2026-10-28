"""T04 analytic/offline collision placement; never starts a physics engine."""
import numpy as np
import pytest
from robot_learning_workbench.tasks import placement as p
from robot_learning_workbench.tasks.registry import TaskError


def box(size=(2.,4.,6.), offset=(0.,0.,0.)):
    return np.array([[x,y,z] for x in (-size[0]/2,size[0]/2) for y in (-size[1]/2,size[1]/2) for z in (-size[2]/2,size[2]/2)])+offset


def rx(a):
    return np.array([[1,0,0],[0,np.cos(a),-np.sin(a)],[0,np.sin(a),np.cos(a)]])


@pytest.mark.parametrize('offset,z',[(0.,3.),(3.,0.),(-2.,5.)])
def test_contact_center_bottom_eccentric_origins(offset,z):
    pose,parts=p.contact_pose((box(offset=(0,0,offset)),),np.eye(3),[.2,.3],np.eye(4))
    np.testing.assert_array_equal(pose[:3,3],[.2,.3,z])
    assert parts[0][:,2].min()==0


def test_contact_rotated_object_and_tilted_support_keeps_input_xy():
    support=np.eye(4);support[:3,:3]=rx(.3);support[:3,3]=[1,2,3]
    vertices=box();rotation=rx(.8)
    pose,parts=p.contact_pose((vertices,),rotation,[.2,.7],support)
    n=support[:3,2]
    expected=(n@support[:3,3]-min((vertices@rotation.T+[.2,.7,0])@n))/n[2]
    assert pose[0,3]==.2 and pose[1,3]==.7
    assert pose[2,3]==pytest.approx(expected,abs=1e-12)
    assert min(parts[0][:,2])==pytest.approx(0,abs=1e-12)


def test_contact_compound_uses_lowest_part():
    pose,parts=p.contact_pose((box(),box((1,1,2),offset=(4,0,-5))),np.eye(3),[0,0],np.eye(4))
    assert pose[2,3]==6
    assert min(x[:,2].min() for x in parts)==0


@pytest.mark.parametrize('a',[np.pi/2,np.pi, np.arccos(1e-10)])
def test_parallel_or_downward_input_z_rejected(a):
    t=np.eye(4);t[:3,:3]=rx(a)
    with pytest.raises(TaskError):p.contact_pose((box(),),np.eye(3),[0,0],t)


def test_projected_geometry_distance_respects_shape_not_bbox():
    a=np.array([[0,0],[2,0],[0,2]])
    b=np.array([[2,2],[2,.5],[.5,2]])
    assert p.polygon_distance(a,b)==pytest.approx(.5/np.sqrt(2))
    assert p.polygon_distance(a,a)==0
    assert p.polygon_distance(a,np.array([[2,0],[3,0],[3,1]]))==0

import hashlib,json
from dataclasses import replace
from scene_contract.package import load_scene
from robot_learning_workbench.tasks.registry import load_registry, validate_params


def spec_box(size=(.2,.2,.4),offset=(0,0,0)):
    t=np.eye(4);t[:3,3]=offset
    return {'kind':'primitive','primitive':'box','dimensions_m':list(size),'scale':[1,1,1],'local_transform':t.tolist()}


def write_scene(tmp_path, *, collision=None, support=None, frames=None, extra_objects=None, assets=None):
    graph={name:{'parent':None if name=='world' else 'world','T_parent_from_frame':np.eye(4).tolist(),'state':'reference'} for name in ('world','object','surface','input')}
    graph.update(frames or {})
    objects={'red':{'role':'task_object','frame_id':'object','collision':collision or [spec_box()]},
             'blue':{'role':'task_object','frame_id':'object','collision':[spec_box()]}}
    objects.update(extra_objects or {})
    scene=dict(schema_version=1,scene_id='contact_fixture',revision='1',units={'length':'m','angle':'rad','time':'s','mass':'kg'},frames=graph,objects=objects,robot={},cameras={},engines={},validation={},supports={'top':support or {'frame_id':'surface','region_xy_m':[[-1,-1],[1,-1],[1,1],[-1,1]]}},calibration='calibration.json',manifest='manifest.json')
    files={'scene.json':json.dumps(scene),'calibration.json':json.dumps({'schema_version':1,'records':{},'evidence':{}}),**(assets or {})}
    entries=[]
    for name,value in files.items():
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
        entries.append({'path':name,'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (tmp_path/'manifest.json').write_text(json.dumps({'schema_version':1,'files':entries}))
    return load_scene(tmp_path/'scene.json')


def bind(scene, **kw):
    r=load_registry(('robot_learning_workbench.tasks.placement',))
    return validate_params(r,'placement.contact_fixed_xy',{'object':'red','frame':'input','support':'top',**kw},kind='placement',stage='source',scene=scene)


def req(**kw):return p.PlacementRequest('red','input','top',rules_id='collision_contact',**kw)


def test_registered_geometry_binding_scale_offset_and_default_pose(tmp_path):
    part=spec_box(offset=(0,0,.4));part['scale']=[2,1,3]
    params=bind(write_scene(tmp_path,collision=[part]))
    vertices=params._context['parts'][0]
    np.testing.assert_allclose(vertices.min(axis=0),[-.2,-.1,-.2])
    np.testing.assert_allclose(vertices.max(axis=0),[.2,.1,1.])
    assert not vertices.flags.writeable


def tetra_mesh():
    return {'schema_version':1,'vertices_m':[[0,0,0],[.2,0,0],[0,.2,0],[0,0,.4]],'triangles':[[0,2,1],[0,1,3],[1,2,3],[2,0,3]]}


def test_manifest_convex_mesh_and_named_part_frame(tmp_path):
    t=np.eye(4);t[2,3]=-.3
    mesh={'kind':'mesh','asset_path':'assets/tetra.json','frame_id':'part','scale':[1,1,1]}
    scene=write_scene(tmp_path,collision=[mesh],assets={'assets/tetra.json':json.dumps(tetra_mesh())},frames={'part':{'parent':'object','T_parent_from_frame':t.tolist(),'state':'reference'}})
    params=bind(scene)
    assert params._context['parts'][0][:,2].min()==-.3
    (tmp_path/'assets/tetra.json').write_text('{}')
    with pytest.raises((TaskError,ValueError)):bind(scene)


@pytest.mark.parametrize('change',['open','nonfinite','bad_index','flat','duplicate_key'])
def test_invalid_mesh_fails_preparation(tmp_path,change):
    m=tetra_mesh()
    if change=='open':m['triangles'].pop()
    if change=='nonfinite':m['vertices_m'][0][0]=float('nan')
    if change=='bad_index':m['triangles'][0][0]=99
    if change=='flat':m['vertices_m'][3][2]=0
    text=json.dumps(m)
    if change=='duplicate_key':text=text.replace('"schema_version": 1','"schema_version": 1, "schema_version": 1')
    scene=write_scene(tmp_path,collision=[{'kind':'mesh','asset_path':'m.json','local_transform':np.eye(4).tolist()}],assets={'m.json':text})
    with pytest.raises(TaskError):bind(scene)


@pytest.mark.parametrize('part',[dict(kind='primitive',primitive='sphere',radius_m=.1,local_transform=np.eye(4).tolist()),spec_box((0,.2,.3)),dict(spec_box(),scale=[-1,1,1])])
def test_unsupported_or_invalid_geometry_does_not_fallback_to_bbox(tmp_path,part):
    scene=write_scene(tmp_path,collision=[part])
    with pytest.raises(TaskError):bind(scene)


def test_fixed_contact_uses_geometry_not_task_dimensions(tmp_path):
    params=bind(write_scene(tmp_path));r=p.contact_fixed_xy(req(xy_m=(.3,.4)),params=params)
    np.testing.assert_array_equal(r.pose[:3,3],[.3,.4,.2])
    assert r.attempts==0 and r.rules_id=='collision_contact'
    assert r.diagnostics['physical_collision_checked'] is False
    assert not r.pose.flags.writeable


def test_default_and_explicit_rotations_recompute_height(tmp_path):
    t=np.eye(4);t[:3,:3]=rx(np.pi/2)
    scene=write_scene(tmp_path,frames={'object':{'parent':'world','T_parent_from_frame':t.tolist(),'state':'reference'}})
    params=bind(scene)
    assert p.contact_fixed_xy(req(xy_m=(0,0)),params=params).pose[2,3]==pytest.approx(.1)
    assert p.contact_fixed_xy(req(xy_m=(0,0),orientation=np.eye(3)),params=params).pose[2,3]==.2


def test_input_frame_changes_numeric_xy_not_physical_placement(tmp_path):
    support=np.eye(4);support[:3,:3]=rx(.35);support[:3,3]=[.5,-.2,1.]
    frame={'parent':'world','T_parent_from_frame':support.tolist(),'state':'reference'}
    scene=write_scene(tmp_path,frames={'surface':frame,'input':frame})
    local=bind(scene)
    a=p.contact_fixed_xy(req(xy_m=(.2,.3)),params=local)
    expected=support@a.pose
    world=bind(scene,frame='world')
    r=replace(req(xy_m=tuple(expected[:2,3])),frame_id='world')
    b=p.contact_fixed_xy(r,params=world)
    np.testing.assert_allclose(b.pose,expected,atol=1e-12)
    assert tuple(b.pose[:2,3])==tuple(expected[:2,3])


@pytest.mark.parametrize('xy',[(1.,0.),(float('nan'),0.),(0.,),('x',0.)])
def test_fixed_invalid_region_or_input_is_not_corrected(tmp_path,xy):
    with pytest.raises(TaskError):p.contact_fixed_xy(req(xy_m=xy),params=bind(write_scene(tmp_path)))


def test_compound_gap_is_not_replaced_by_whole_object_bbox(tmp_path):
    parts=[spec_box((.1,.1,.2),(-.4,0,0)),spec_box((.1,.1,.2),(.4,0,0))]
    params=bind(write_scene(tmp_path,collision=parts))
    obstacle=np.eye(4);obstacle[2,3]=.2
    r=p.contact_fixed_xy(req(xy_m=(0,0),occupied_poses={'blue':obstacle}),params=params)
    assert r.pose[2,3]==.1
    obstacle[0,3]=.4
    with pytest.raises(TaskError):p.contact_fixed_xy(req(xy_m=(0,0),occupied_poses={'blue':obstacle}),params=params)


@pytest.mark.parametrize('delta,allowed',[(-1e-6,False),(0,False),(1e-6,True)])
def test_projected_separation_boundary(tmp_path,delta,allowed):
    params=bind(write_scene(tmp_path),separation_m=.05)
    obstacle=np.eye(4);obstacle[:3,3]=[.25+delta,0,.2]
    if allowed:p.contact_fixed_xy(req(xy_m=(0,0),occupied_poses={'blue':obstacle}),params=params)
    else:
        with pytest.raises(TaskError):p.contact_fixed_xy(req(xy_m=(0,0),occupied_poses={'blue':obstacle}),params=params)


def test_random_budget_and_consumption(tmp_path):
    class Zero:
        calls=0
        def uniform(self,low,high):self.calls+=1;return np.zeros(2)
    params=bind(write_scene(tmp_path));rng=Zero();obstacle=np.eye(4)
    with pytest.raises(TaskError) as e:p.contact_random_xy(req(rng=rng,occupied_poses={'blue':obstacle}),params=params)
    assert rng.calls==1000 and e.value.code=='PLACEMENT_EXHAUSTED'
    assert e.value.diagnostics['attempts']==1000 and e.value.diagnostics['support_id']=='top'
    assert e.value.diagnostics['last_reason']=='projected_overlap_or_separation'


def test_random_fit_bounds_and_exact_rng_consumption(tmp_path):
    params=bind(write_scene(tmp_path),margin_m=.05)
    rng=np.random.default_rng(1047);control=np.random.default_rng(1047)
    expected=control.uniform([-.85,-.85],[.85,.85])
    r=p.contact_random_xy(req(rng=rng),params=params)
    np.testing.assert_allclose(r.pose[:2,3],expected,atol=1e-15)
    assert r.pose[2,3]==.2 and r.attempts==1
    assert rng.bit_generator.state==control.bit_generator.state


def test_impossible_footprint_and_bad_input_fail_before_draw(tmp_path):
    class Never:
        def uniform(self,*a):raise AssertionError('must not draw')
    params=bind(write_scene(tmp_path,collision=[spec_box((3,3,1))]))
    with pytest.raises(TaskError) as e:p.contact_random_xy(req(rng=Never()),params=params)
    assert e.value.code=='INVALID_PLACEMENT' and e.value.diagnostics['attempts']==0
    params=bind(write_scene(tmp_path))
    with pytest.raises(TaskError):p.contact_random_xy(req(rng=Never(),occupied_poses={'missing':np.eye(4)}),params=params)


def test_random_retains_explicit_orientation_and_no_legacy_clearance(tmp_path):
    params=bind(write_scene(tmp_path));rot=rx(.7)
    r=p.contact_random_xy(req(rng=np.random.default_rng(3),orientation=rot),params=params)
    np.testing.assert_array_equal(r.pose[:3,:3],rot)
    assert r.pose[2,3]==pytest.approx(.1*np.sin(.7)+.2*np.cos(.7))


@pytest.mark.parametrize('angle',[0.,.4,1.2])
def test_random_rotated_support_and_input_frames_have_valid_contact(tmp_path,angle):
    support=np.eye(4);support[:3,:3]=rx(.5);support[:3,3]=[.3,-.1,.8]
    rz=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1.]])
    input_pose=np.eye(4);input_pose[:3,:3]=rz;input_pose[:3,3]=[-.2,.3,-.5]
    frames={name:{'parent':'world','T_parent_from_frame':value.tolist(),'state':'reference'} for name,value in [('surface',support),('input',input_pose)]}
    params=bind(write_scene(tmp_path,frames=frames),margin_m=.03)
    rng=np.random.default_rng(6)
    for _ in range(12):
        result=p.contact_random_xy(req(rng=rng,orientation=rx(.7)),params=params)
        actual=(np.linalg.inv(support)@input_pose@result.pose)
        vertices=box((.2,.2,.4))@actual[:3,:3].T+actual[:3,3]
        assert vertices[:,2].min()==pytest.approx(0.,abs=1e-12)
        assert np.abs(vertices[:,:2]).max()<=.97+1e-12
        assert 1<=result.attempts<=1000


@pytest.mark.parametrize('delta,ok',[(0,True),(1e-10,True),(2e-9,False)])
def test_new_support_tolerance_separate_from_v8(tmp_path,delta,ok):
    params=bind(write_scene(tmp_path))
    if ok:p.contact_fixed_xy(req(xy_m=(.9+delta,0)),params=params)
    else:
        with pytest.raises(TaskError):p.contact_fixed_xy(req(xy_m=(.9+delta,0)),params=params)


def test_mesh_placement_triangle_footprint_and_compound_height(tmp_path):
    part={'kind':'mesh','asset_path':'m.json','local_transform':np.eye(4).tolist()}
    params=bind(write_scene(tmp_path,collision=[part],assets={'m.json':json.dumps(tetra_mesh())}))
    result=p.contact_fixed_xy(req(xy_m=(0,0)),params=params)
    assert result.pose[2,3]==0
    # Each convex part's projection is used, not the global AABB.
    other=np.eye(4);other[:3,3]=[.25,.25,.2]
    assert p.contact_fixed_xy(req(xy_m=(0,0),occupied_poses={'blue':other}),params=params).attempts==0


@pytest.mark.parametrize('change',['self_intersect','concave','clockwise','nonfinite','nonplanar_field'])
def test_invalid_support_is_preparation_error(tmp_path,change):
    region=[[-1,-1],[1,-1],[1,1],[-1,1]]
    if change=='self_intersect':
        angles=np.linspace(0,2*np.pi,5,endpoint=False);pts=np.column_stack((np.cos(angles),np.sin(angles)));region=pts[[0,2,4,1,3]].tolist()
    if change=='concave':region=[[-1,-1],[1,-1],[0,0],[1,1],[-1,1]]
    if change=='clockwise':region.reverse()
    if change=='nonfinite':region[0][0]=float('inf')
    support={'frame_id':'surface','region_xy_m':region}
    if change=='nonplanar_field':support['heightfield']='ignored?'
    with pytest.raises(ValueError):bind(write_scene(tmp_path,support=support))


@pytest.mark.parametrize('draw',[[float('nan'),0],[10.,0],[0.],True])
def test_invalid_rng_never_retries(tmp_path,draw):
    class Bad:
        calls=0
        def uniform(self,*args):self.calls+=1;return draw
    rng=Bad()
    with pytest.raises(TaskError) as error:p.contact_random_xy(req(rng=rng),params=bind(write_scene(tmp_path)))
    assert error.value.code=='INVALID_PLACEMENT' and rng.calls==1
    assert error.value.diagnostics['attempts']==1


def test_fixed_then_random_obeys_supplied_occupied_order_and_rng(tmp_path):
    params=bind(write_scene(tmp_path))
    class Sequence:
        calls=0
        def uniform(self,*args):
            self.calls+=1
            return np.array([0,0] if self.calls==1 else [.5,.5])
    rng=Sequence();other=np.eye(4);other[2,3]=.2
    r=p.contact_random_xy(req(rng=rng,occupied_poses={'blue':other}),params=params)
    assert r.attempts==2 and rng.calls==2
    np.testing.assert_array_equal(r.pose[:2,3],[.5,.5])
    np.testing.assert_array_equal(other[:3,3],[0,0,.2])


def test_geometry_part_ambiguity_is_not_silently_ignored(tmp_path):
    part=spec_box();part['radius_m']=999
    with pytest.raises(TaskError) as e:bind(write_scene(tmp_path,collision=[part]))
    assert e.value.code=='TASK_PARAMS_INVALID'


def test_contact_registration_has_no_annotation_or_success_gate(tmp_path):
    from robot_learning_workbench.tasks.registry import resolve
    registry=load_registry(('robot_learning_workbench.tasks.placement',))
    for name in ('placement.contact_fixed_xy','placement.contact_random_xy'):
        assert resolve(registry,name,kind='placement',stage='source',engine='mujoco').kind=='placement'
        with pytest.raises(TaskError):resolve(registry,name,kind='placement',stage='annotation')
    with pytest.raises(TaskError):bind(write_scene(tmp_path),clearance_m=.003)
