import copy
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from real2sim_builder.scene import value,world_pose,frame_world,validate
from test_builder_export import legacy_scene


def supported(tilt=0.):
    s=legacy_scene();table,block=s['objects'];table['pose']['value']=np.eye(4).tolist()
    table['pose']['value'][:3]= (np.c_[Rotation.from_euler('y',tilt).as_matrix(),[.1,-.2,.3]]).tolist()
    block['pose']=value(np.eye(4).tolist(),'estimated',['bad initialization'])
    s['geometry_constraints']={'schema':'real2sim.geometry-constraints/1','units':'m','distances':[],
        'supports':{'block':{'support':'table','source':'user_declared','status':'CONFIRMED','evidence':['on table and upright']}}}
    return s


def test_explicit_support_corrects_bad_pose_in_support_coordinates():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.scene import support_metrics
    scene=supported(.3);before=copy.deepcopy(scene)
    scene['objects'][1]['pose']['value'][2][3]=2
    fixed,report=project_supports(scene)
    row=support_metrics(fixed)['relations'][0]
    assert abs(row['gap_m'])<1e-9 and row['normal_error_rad']<1e-8
    assert report['status']=='SATISFIED'
    assert np.allclose(world_pose(fixed,fixed['objects'][1])[:3,2],world_pose(fixed,fixed['objects'][0])[:3,2])
    assert fixed['objects'][0]==before['objects'][0] and scene['objects'][1]['pose']['value'][2][3]==2


def test_nested_supports_recompute_contact_after_dimension_change():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.scene import support_metrics
    s=supported(.25);board=copy.deepcopy(s['objects'][1]);board.update(id='board',role='workspace');board['dimensions']=value([.3,.3,.005],'estimated',['test'])
    s['objects'].append(board);s['geometry_constraints']['supports']['board']={'support':'table','source':'user_declared','evidence':['board on table']}
    s['geometry_constraints']['supports']['block']['support']='board'
    fixed,_=project_supports(s);fixed['objects'][1]['dimensions']=value([.06,.06,.12],'optimized',['size fit'])
    result,_=project_supports(fixed)
    assert support_metrics(result)['status']=='SATISFIED'
    assert len(support_metrics(result)['relations'])==2


def test_validation_rejects_floating_and_tilted_confirmed_support():
    from real2sim_builder.initialization import project_supports
    s,_=project_supports(supported());validate(s)
    s['objects'][1]['pose']['value'][2][3]+=.02
    with pytest.raises(ValueError,match='CONSTRAINT_CONFLICT'):validate(s)


def test_estimated_relation_does_not_snap_or_become_confirmed():
    from real2sim_builder.initialization import project_supports
    s=supported();s['geometry_constraints']['supports']['block'].update(source='estimated',status='PROPOSED')
    fixed,report=project_supports(s)
    assert fixed['objects']==s['objects'] and report['status']=='NEEDS_REVIEW'
    assert fixed['geometry_constraints']['supports']['block']['source']=='estimated'


def test_robot_base_contact_anchor_is_not_frame_origin():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.scene import support_metrics
    s=supported(.2);s['geometry_constraints']['supports']={'robot_base':{'support':'table','source':'user_declared','evidence':['mount surface'],
        'contact_anchor':{'point_m':[0,0,-.08],'normal':[0,0,1]}}}
    s['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated',['base fit'])}
    fixed,_=project_supports(s);t=frame_world(fixed,'robot_base');table=world_pose(fixed,fixed['objects'][0])
    contact=(t@np.array([0,0,-.08,1]))[:3];top=(table@np.array([0,0,.02,1]))[:3]
    assert abs((contact-top)@table[:3,2])<1e-10
    assert abs((t[:3,3]-contact)@table[:3,2]-.08)<1e-10
    assert support_metrics(fixed)['status']=='SATISFIED'


def test_tilted_contact_orientation_is_explicitly_preserved():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.scene import support_metrics
    s=supported(.2);r=Rotation.from_euler('x',.12).as_matrix()
    s['geometry_constraints']['supports']['block'].update(parallel=False,relative_rotation=r.tolist())
    fixed,_=project_supports(s);relative=world_pose(fixed,fixed['objects'][0])[:3,:3].T@world_pose(fixed,fixed['objects'][1])[:3,:3]
    assert np.allclose(relative,r) and support_metrics(fixed)['status']=='SATISFIED'


def test_joint_variables_prevent_image_loss_from_tipping_cup_or_base():
    from real2sim_builder.calibration.joint import parameter_blocks,apply_parameters
    from real2sim_builder.scene import support_metrics
    s=supported(.2);s['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated',['initial'])}
    s['geometry_constraints']['supports']['robot_base']={'support':'table','source':'user_declared','evidence':['bolted mount'],
        'contact_anchor':{'point_m':[0,0,-.08],'normal':[0,0,1]}}
    rows=[{'split':'train','image_id':'side','camera':'side','object_id':'block'}]
    blocks,radius=parameter_blocks(s,rows,{'robot_base':True,'objects':['block'],'cameras':[]})
    assert {(b[0],b[4])for b in blocks}=={('base_support',3),('object_support',3)}
    trial,_=apply_parameters(s,blocks,radius*.8)
    assert support_metrics(trial)['status']=='SATISFIED'
    assert np.allclose(frame_world(trial,'robot_base')[:3,2],world_pose(trial,trial['objects'][0])[:3,2])


def test_icp_hypotheses_obey_same_sloped_support():
    from real2sim_builder.calibration.hybrid import initial_poses,trimmed_icp,surface_points
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.scene import support_relations,supported_pose
    s=supported(.2);fixed,_=project_supports(s);obj=s['objects'][1]
    model=surface_points(obj,s,'.',300);target=world_pose(fixed,fixed['objects'][1]);observed=model@target[:3,:3].T+target[:3,3]
    relation=support_relations(s)['block']
    project=lambda pose:supported_pose(s,'block',relation,pose)
    seeds=initial_poses(s,obj,observed,'table')
    assert all(np.allclose(p,project(p))for p in seeds)
    result=trimmed_icp(model,observed,seeds,iterations=5,project_pose=project)
    assert np.allclose(result['T_world_object'],project(result['T_world_object']))


def test_zero_yaw_bound_keeps_xy_and_fixed_heading():
    from real2sim_builder.calibration.joint import parameter_blocks,apply_parameters
    s=supported();s['geometry_constraints']['supports']['block']['yaw_bound_rad']=0
    rows=[dict(split='train',image_id='side',camera='side',object_id='block')]
    blocks,radius=parameter_blocks(s,rows,{'cameras':[]})
    assert blocks[0][4]==2 and np.all(radius>0)
    trial,_=apply_parameters(s,blocks,radius*.5)
    assert np.allclose(world_pose(trial,trial['objects'][1])[:3,:3],np.eye(3))


def test_support_diagnostic_measures_true_tilted_collision_penetration():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.scene import support_metrics,collision_extent
    s,_=project_supports(supported());obj=s['objects'][1]
    obj['pose']['value'][:3]=np.c_[Rotation.from_euler('x',.5).as_matrix(),world_pose(s,obj)[:3,3]].tolist()
    row=support_metrics(s)['relations'][0]
    actual_gap=world_pose(s,obj)[2,3]-.32+collision_extent(s,obj,world_pose(s,obj)[:3,:3].T@[0,0,1])
    assert row['gap_m']==pytest.approx(actual_gap) and row['penetration_m']>0


def test_memo_support_uses_separate_evidence_and_never_dimension_quote_as_confirmation():
    from real2sim_builder.authoring import parse_scene_analysis
    from test_modeling_handoff import semantic_reply
    import hashlib
    text='block height 60mm. block sits upright on the table.'
    memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    geometry=dict(kind='box',dimensions_m=[None,None,.06],source='user_memo',evidence_quote='block height 60mm.',evidence=[],wall_m=None,support='table')
    answer=semantic_reply([dict(id='block',prompt='block',role='manipulable_object',geometry=geometry),dict(id='table',prompt='table',role='support_surface')],text)
    parsed=parse_scene_analysis(answer,memo)
    assert parsed['block']['support']['status']=='PROPOSED'
    answer['objects'][0]['support_relation']=dict(support='table',source='user_memo',evidence_quote='block sits upright on the table.',evidence=[],parallel=True)
    parsed=parse_scene_analysis(answer,memo)
    assert parsed['block']['support']['status']=='CONFIRMED'
    assert 'block sits upright' in ' '.join(parsed['block']['support']['evidence'])
    answer['objects'][0]['support_relation']['source']='visual_inference'
    answer['objects'][0]['support_relation']['evidence']=['visible contact']
    assert parse_scene_analysis(answer,memo)['block']['support']['status']=='PROPOSED'


def test_unknown_pose_stays_unknown_until_cloud_initialization():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.calibration.hybrid import initial_poses
    s=supported();s['objects'][1]['pose']=value(None)
    draft,report=project_supports(s,allow_incomplete=True)
    assert draft['objects'][1]['pose']['value']is None and report['status']=='NEEDS_MORE_DATA'
    seeds=initial_poses(draft,draft['objects'][1],np.random.default_rng(0).normal(size=(30,3))*.01,'table')
    assert seeds and all(np.allclose(p[:3,2],[0,0,1])for p in seeds)


def test_mesh_contact_uses_displaced_collision_not_visual_bounds(tmp_path):
    import trimesh
    from real2sim_builder.files import sha
    from real2sim_builder.initialization import project_supports
    s=supported();mesh=trimesh.creation.box(extents=[.06,.06,.06]);mesh.apply_translation([0,0,.12])
    path=tmp_path/'offset.stl';mesh.export(path)
    s['assets']['offset']={'path':'offset.stl','sha256':sha(path)}
    s['objects'][1]['collision']={'type':'mesh','asset':'offset'}
    result,_=project_supports(s,root=tmp_path)
    assert world_pose(result,result['objects'][1])[2,3]==pytest.approx(.32-.09,abs=1e-8)
    validate(result,tmp_path)


def test_confirmed_constraint_conflicts_and_cycles_are_rejected():
    from real2sim_builder.initialization import project_supports
    s=supported();s['objects'][1]['pose']['provenance']='measured'
    with pytest.raises(ValueError,match='CONSTRAINT_CONFLICT'):project_supports(s)
    s=supported();s['geometry_constraints']['supports']['table']={'support':'block','source':'measured','evidence':['bad cycle']}
    with pytest.raises(ValueError,match='cyclic'):project_supports(s)


def test_mujoco_passive_contact_of_projected_geometry(tmp_path):
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.validation import physics_probe
    from real2sim_builder.project import Project
    s,_=project_supports(supported());s['objects'][1]['physics']['mass_kg']=value(.03,'estimated',['synthetic probe'])
    p=Project.create(tmp_path/'projects','contact')
    report=physics_probe(p,s,tmp_path/'native',steps=300)
    mj=report['mujoco']
    assert mj['steps']==300 and mj['finite']and mj['contact_count']>0
    assert mj['settled']and not mj['initial_penetrations']and not mj['final_penetrations']
    assert report['physical_verified']is False


def test_yaw_limit_is_not_reset_by_each_solver_iteration():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.calibration.joint import parameter_blocks,apply_parameters
    s=supported();s['geometry_constraints']['supports']['block']['yaw_bound_rad']=.1
    s,_=project_supports(s)
    rows=[dict(split='train',image_id='side',camera='side',object_id='block')]
    for _ in range(5):
        blocks,radius=parameter_blocks(s,rows,{'cameras':[]});s,_=apply_parameters(s,blocks,radius)
    yaw=Rotation.from_matrix(world_pose(s,s['objects'][1])[:3,:3]).as_euler('xyz')[2]
    assert abs(yaw)<=.1+1e-10


def test_native_rgb_loss_with_bad_camera_cannot_tip_supported_cup_or_base(tmp_path):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder.scene import support_metrics,camera_calibration_signature
    from real2sim_builder.calibration.hybrid import fit_scene
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.files import read
    p,truth,s=rendered_fixture(tmp_path)
    camera=s['cameras'][0];camera['pose']['provenance']='estimated'
    pose=np.asarray(camera['pose']['value']);pose[:3,:3]=Rotation.from_euler('x',.07).as_matrix()@pose[:3,:3];camera['pose']['value']=pose.tolist()
    for record in s['view_registrations'].values():
        if record['camera']=='side':record.update(status='REGISTERED_ESTIMATED',camera_signature=camera_calibration_signature(s,camera))
    s['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated',['synthetic mount'])}
    supports={'block':'table','robot_base':dict(support='table',source='measured',evidence=['mount drawing'],contact_anchor=dict(point_m=[0,0,-.08],normal=[0,0,1]))}
    seen=[]
    class ContactRenderer(Renderer):
        def update_scene(self,trial):
            assert support_metrics(trial,root=p.root)['status']=='SATISFIED'
            seen.append(world_pose(trial,trial['objects'][1]).copy())
            return super().update_scene(trial)
    result,report=fit_scene(p,s,tmp_path/'fit',dict(supports=supports,robot_base=True,objects=['block'],cameras=['side'],renderer_factory=ContactRenderer,
        max_iterations=2,max_evaluations=50,loss_weights={'rgb':1.,'mask':0.,'edge':0.,'depth':0.,'metric':0.,'prior':.001}))
    assert len(seen)>4 and report['evaluations']>1
    assert support_metrics(result,root=p.root)['status']=='SATISFIED'
    assert all(np.allclose(pose[:3,2],[0,0,1])for pose in seen)
    assert support_metrics(read(tmp_path/'fit/best-scene.yaml'),root=p.root)['status']=='SATISFIED'
    assert result['objects'][0]==truth['objects'][0]


def test_landmark_joint_solver_uses_same_support_manifold(tmp_path):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder.calibration.joint import fit_joint_scene
    from real2sim_builder.calibration.camera import project_point
    from real2sim_builder.files import write
    from real2sim_builder.scene import support_metrics
    p,truth,s=rendered_fixture(tmp_path);e=p.evidence;e['landmarks']=[]
    for image in e['images']:
        camera=next(c for c in truth['cameras']if c['id']==image['camera'])
        for x in(-.03,.03):
            for y in(-.03,.03):
                for z in(-.03,.03):
                    row=dict(observation=image['id'],object='block',point_m=[x,y,z],source='measured',evidence='synthetic cube corners')
                    row['uv']=project_point(truth,camera,row)[0].tolist();e['landmarks'].append(row)
    write(p.root/'input/evidence.yaml',e)
    result,report=fit_joint_scene(p,s,dict(objects=['block'],cameras=[],supports={'block':'table'},max_nfev=30))
    assert report['status']=='IMPROVED' and report['after']['rmse_px']<report['before']['rmse_px']
    assert support_metrics(result,root=p.root)['status']=='SATISFIED'
    assert report['changed_variables']==[dict(kind='object_support',id='block',mode='xy_yaw_on_support')]


def test_new_asset_contact_is_recalculated_before_candidate_validation(tmp_path):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.object_assets import register_object_asset,instance_operation
    from real2sim_builder.scene import support_metrics
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','new asset');s,_=project_supports(supported())
    s['objects'][1]['dimensions']['provenance']='estimated';p.save_scene(s);c=Candidate.create(p,'contact')
    record=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='small_block')
    operation=instance_operation(p,record['manifest'],'block');operation['op']='use_object_asset'
    before=copy.deepcopy(c.scene);c.edit([operation])
    assert support_metrics(c.scene,root=p.root)['status']=='SATISFIED'
    assert world_pose(c.scene,c.scene['objects'][1])[2,3]!=world_pose(before,before['objects'][1])[2,3]
    assert p.scene==s


def test_candidate_cannot_remove_or_weaken_confirmed_constraints(tmp_path):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.initialization import project_supports
    p=Project.create(tmp_path,'preserve contact');scene,_=project_supports(supported());p.save_scene(scene);c=Candidate.create(p,'guard')
    for change in ('remove','relax'):
        trial=copy.deepcopy(c.scene)
        if change=='remove':trial.pop('geometry_constraints')
        else:trial['geometry_constraints']['supports']['block']['tolerance_m']=.2
        with pytest.raises(ValueError,match='[Pp]rotected|CONSTRAINT_CONFLICT'):c.save(trial)
    assert c.scene==scene


def test_contact_anchor_cannot_hide_known_collision_penetration():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.scene import support_metrics
    s=supported();s['geometry_constraints']['supports']['block']['contact_anchor']=dict(point_m=[0,0,.03],normal=[0,0,1])
    fixed,report=project_supports(s)
    assert report['status']=='CONSTRAINT_CONFLICT'
    assert support_metrics(fixed)['relations'][0]['collision_penetration_m']>.05
    with pytest.raises(ValueError,match='CONSTRAINT_CONFLICT'):validate(fixed)


@pytest.mark.parametrize('parallel',[True,False])
def test_missing_contact_surface_is_diagnosed_without_inventing_an_offset(tmp_path,parallel):
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.calibration.hybrid import fit_scene
    from real2sim_builder.project import Project
    s=supported();s['geometry_constraints']['supports']['block']['parallel']=parallel;s['objects'][0]['collision']={'type':'compound','parts':[dict(type='box',pose=np.eye(4).tolist(),dimensions=[1.,.8,.04])]}
    result,report=project_supports(s,allow_incomplete=True)
    assert result['objects']==s['objects'] and report['status']=='NEEDS_MORE_DATA'
    p=Project.create(tmp_path/'projects','missing surface')
    result,report=fit_scene(p,s,tmp_path/'fit')
    assert result==s and report['status']=='NEEDS_MORE_DATA'


def test_yaw_limit_violation_is_not_reported_as_normal_or_roll_pitch_error():
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.scene import support_metrics
    s=supported();s['geometry_constraints']['supports']['block']['yaw_bound_rad']=.1;s,_=project_supports(s)
    s['objects'][1]['pose']['value'][:3]=np.c_[Rotation.from_euler('z',.3).as_matrix(),world_pose(s,s['objects'][1])[:3,3]].tolist()
    report=support_metrics(s);row=report['relations'][0]
    assert report['status']=='CONSTRAINT_CONFLICT'
    assert row['normal_error_rad']<1e-8 and row['relative_roll_pitch_error_rad']<1e-8
def test_cloud_initialization_places_root_support_before_its_unknown_children(tmp_path,monkeypatch):
    from real2sim_builder.calibration import hybrid
    from real2sim_builder.project import Project
    from real2sim_builder.scene import value
    from real2sim_builder.files import sha
    from test_builder_export import legacy_scene
    import numpy as np
    p=Project.create(tmp_path,'parent first');scene=legacy_scene();rows=[]
    for obj in scene['objects']:
        points=hybrid.surface_points(obj,scene,p.root,100)+np.asarray(obj['pose']['value'])[:3,3]
        path=p.root/(obj['id']+'.npz');np.savez(path,points_world_m=points)
        mask=p.root/(obj['id']+'.png');mask.write_bytes(b'mask identity')
        rows.append({'object_id':obj['id'],'image_id':'one','split':'train','group_id':'g','units':'m','frame':'world',
            'path':path.name,'sha256':sha(path),'mask':mask.name,'mask_sha256':sha(mask)})
        obj['pose']=value(None)
    scene['reconstruction_observations']={'clouds':rows}
    def initialized(model,points,seeds,**kwargs):
        return {'status':'ESTIMATED','T_world_object':seeds[0].tolist()}
    monkeypatch.setattr(hybrid,'trimmed_icp',initialized)
    fitted,report=hybrid.fit_clouds(p,scene,{'supports':{'block':'table'}})
    assert fitted['objects'][0]['pose']['value']is not None
    assert fitted['objects'][1]['pose']['value']is not None
    assert report['physical_constraints']['status']!='CONSTRAINT_CONFLICT'
