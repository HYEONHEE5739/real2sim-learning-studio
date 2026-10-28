"""Offline Builder calibration: same metric math, no physical verification."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from real2sim_builder.calibration.camera import project_point,fit_cameras,fit_geometry,landmark_metrics

B=Path('/home/hyeonhee/soarm_isaaclab/real2sim-builder/app')

@pytest.fixture
def scene():
    from real2sim_builder.project import empty,value
    scene=empty('Synthetic measured workspace')
    def obj(name,role,dimensions,xyz,color):
        t=np.eye(4);t[:3,3]=xyz
        return {'id':name,'role':role,'frame':'world','pose':value(t.tolist(),'measured'),'dimensions':value(dimensions,'measured'),'visual':{'type':'box'},'collision':{'type':'box'},'color':value(color,'measured'),'physics':{'mass_kg':value(None),'friction':value(.1,'measured')}}
    scene['objects']=[obj('table','support_surface',[1,.8,.04],[0,0,-.02],[.5,.5,.5]),obj('block','manipulable_object',[.06,.06,.06],[0,0,.03],[.8,.15,.1])]
    eye=np.array([.6,.4,.5]);forward=-eye/np.linalg.norm(eye);right=np.cross(forward,[0,0,1]);right/=np.linalg.norm(right);down=np.cross(forward,right)
    t=np.eye(4);t[:3,:3]=np.column_stack([right,down,forward]);t[:3,3]=eye
    scene['cameras']=[{'id':'side','frame':'world','pose':value(t.tolist(),'calibrated'),'K':value([[160.,0,80.],[0,160.,60.],[0,0,1]],'calibrated'),'resolution':[160,120],'distortion':value([0.]*5,'calibrated')}]
    return scene


def test_metric_camera_fit_preserves_geometry_and_heldout(scene):
    truth=copy.deepcopy(scene);rows=[]
    for i,point in enumerate([[-.1,-.1,0],[.1,-.1,0],[-.1,.1,0],[.1,.1,0],[0,0,.1],[.04,-.05,.12],[.02,.02,.05]]):
        row={'camera':'side','point_m':point,'split':'train' if i<6 else 'validation'};row['uv']=project_point(truth,truth['cameras'][0],row)[0].tolist();rows.append(row)
    scene['cameras'][0]['pose']['value'][0][3]+=.035
    before=copy.deepcopy(scene);fitted,report=fit_cameras(scene,rows)
    assert landmark_metrics(fitted,[rows[-1]])['rmse_px']<.01
    assert fitted['objects']==before['objects'] and scene==before
    assert report[0]['points']==6 and fitted['cameras'][0]['pose']['provenance']=='optimized'


def test_calibrated_corners_recover_object_pose(scene):
    truth=copy.deepcopy(scene);rows=[]
    for point in [[-.03,-.03,-.03],[.03,-.03,-.03],[-.03,.03,-.03],[.03,.03,-.03],[-.03,-.03,.03],[.03,.03,.03]]:
        row={'camera':'side','object':'block','point_m':point,'split':'train'};row['uv']=project_point(truth,truth['cameras'][0],row)[0].tolist();rows.append(row)
    scene['objects'][1]['pose'].update(value=None,provenance='unknown')
    fitted,report=fit_geometry(scene,rows)
    np.testing.assert_allclose(fitted['objects'][1]['pose']['value'],truth['objects'][1]['pose']['value'],atol=1e-4)
    assert report[0]['object']=='block'


def test_collinear_metric_landmarks_rejected(scene):
    rows=[{'camera':'side','point_m':[i*.01,0,0],'uv':[1,1]} for i in range(5)]
    with pytest.raises(ValueError,match='collinear'):fit_cameras(scene,rows)


def test_camera_algorithm_function_bodies_match_existing_source():
    import real2sim_builder.calibration.camera as new
    old=ast.parse((B/'calibration/camera.py').read_text());actual=ast.parse(Path(new.__file__).read_text())
    funcs=lambda tree:{n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef)}
    assert funcs(actual)==funcs(old)


def test_reference_robot_fk_named_joint_and_rotation_order(tmp_path):
    from real2sim_builder.calibration.geometry import link_transforms
    path=tmp_path/'robot.urdf';path.write_text('<robot name="reference"><link name="root"/><link name="tool"/><joint name="hinge" type="revolute"><parent link="root"/><child link="tool"/><origin xyz="1 0 0"/><axis xyz="0 0 1"/><limit lower="-3" upper="3" effort="1" velocity="1"/></joint></robot>')
    pose=link_transforms(path,{'hinge':np.pi/2})['tool']
    np.testing.assert_allclose(pose[:3,3],[1,0,0]);np.testing.assert_allclose(pose[:3,0],[0,1,0],atol=1e-8)
    with pytest.raises(ValueError):link_transforms(path,{})


def test_geometry_parts_container_open_top_and_compound(scene):
    from real2sim_builder.calibration.geometry import parts
    from real2sim_builder.project import value
    obj=scene['objects'][1];obj['dimensions']=value([.1,.1,.12],'measured');obj['collision']={'type':'container','wall':value(.003,'measured'),'round':True,'bottom_diameter_m':.08}
    result=parts(obj,'collision');assert len(result)==129 and result[0]['type']=='cylinder'
    assert result[0]['pose'][2,3]==-.12/2+.003/2
    assert all(part['dimensions'][2]<.12 for part in result)
    obj['collision']={'type':'compound','parts':[{'type':'box','dimensions':[.1,.1,.01],'pose':np.eye(4).tolist()}]}
    assert len(parts(obj,'collision'))==1
    obj['collision']['parts'][0]['dimensions']=[0,.1,.01]
    with pytest.raises(ValueError):parts(obj,'collision')


# Existing unknown-camera/held-out/mapping test bodies retained.
import copy
import hashlib
import json
import numpy as np
import pytest
from real2sim_builder.project import Project,write
from real2sim_builder.project import empty,value
from real2sim_builder.calibration.camera import project_point
from real2sim_builder.calibration.geometry import fit
from real2sim_builder.project import mapping_contract,observation_scene


def fixture(tmp_path,planar=False,wrist=False):
    p=Project.create(tmp_path/'projects','camera');scene=empty('unknown')
    if wrist:
        path=p.root/'input/robot.urdf';path.write_text('<robot name="test"><link name="base"/><link name="mount"/><joint name="hinge" type="revolute"><parent link="base"/><child link="mount"/><axis xyz="0 0 1"/><limit lower="-3" upper="3" effort="1" velocity="1"/></joint></robot>')
        scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'measured')}
        scene['frames']['robot_link_mount']={'parent':'robot_base','transform':value(np.eye(4).tolist(),'derived')}
        scene['robot_model']={'path':'input/robot.urdf','joint_names':['hinge'],'mapping':{'source':'fixture'},'mapping_verified':False}
    t=np.eye(4);t[:3,3]=[.03,-.015,.02]
    camera={'id':'camera','frame':'robot_link_mount' if wrist else 'world','pose':value(t.tolist(),'estimated'),
            'K':value([[400,0,320],[0,400,240],[0,0,1]],'estimated'),'resolution':[640,480],'distortion':value([0.]*5,'estimated')}
    scene['cameras']=[camera];rows=[];images=[];rng=np.random.default_rng(1)
    points=rng.uniform([-.12,-.1,.4],[.12,.1,.8],(16,3))
    if planar:points[:,2]=.5
    for i,q in enumerate([-.4,.1,.6,1.]):
        obs={'id':f'pose_{i}','camera':'camera','split':'train' if i<3 else 'validation','group_id':f'g{i}',
             'q_measured':[q],'eligible':True}
        if wrist:obs.update(session_id='train' if i<3 else 'holdout',joint_names=['hinge'])
        images.append(obs)
        posed=observation_scene(scene,obs,p.root,complete=False)
        for point in points:
            row={'observation':obs['id'],'frame':'world','point_m':point.tolist(),'source':'measured','evidence':'synthetic metric fixture'}
            row['uv']=project_point(posed,posed['cameras'][0],row)[0].tolist();rows.append(row)
    evidence=p.evidence;evidence['images']=images;evidence['landmarks']=rows;write(p.root/'input/evidence.yaml',evidence)
    scene['cameras'][0]['K']=value(None);scene['cameras'][0]['pose']=value(None)
    return p,scene


def test_unknown_side_k_bootstrap_train_only_and_fixed_parameter_status(tmp_path):
    p,scene=fixture(tmp_path);original=copy.deepcopy(scene)
    result,report=fit(p,scene,'bootstrap:camera')
    assert report['status']=='IMPROVED'
    assert abs(result['cameras'][0]['K']['value'][0][0]-400)<.01
    assert report['holdout_after']['rmse_px']<.01
    assert result['cameras'][0]['calibration_quality']['state']=='ESTIMATED'
    assert report['holdout_used_for_seed_selection'] is False and scene==original


def test_planar_points_rejected_before_any_camera_mutation(tmp_path):
    p,scene=fixture(tmp_path,planar=True)
    result,report=fit(p,scene,'bootstrap:camera')
    assert report['status']=='NEEDS_MORE_DATA' and 'Noncoplanar' in report['need'] and result==scene


def test_wrist_mount_is_shared_q_never_modified_and_mapping_uncertainty_remains(tmp_path):
    p,scene=fixture(tmp_path,wrist=True);old=copy.deepcopy(p.evidence)
    result,report=fit(p,scene,'bootstrap:camera')
    assert report['status']=='IMPROVED'
    assert result['cameras'][0]['calibration_quality']['robot_mapping_verified'] is False
    assert p.evidence==old and report['holdout_after']['rmse_px']<.01
    _,assessment=fit(p,result,'quality:camera')
    assert assessment['status']=='NEEDS_MORE_DATA' and 'manually estimated' in assessment['need']


def test_failed_holdout_cannot_select_new_seed(tmp_path):
    p,scene=fixture(tmp_path);e=p.evidence
    for row in e['landmarks']:
        if row['observation']=='pose_3':row['uv'][0]+=50
    write(p.root/'input/evidence.yaml',e)
    result,report=fit(p,scene,'bootstrap:camera')
    assert report['status']=='REJECTED' and result==scene and not report['holdout_used_for_seed_selection']


def test_precision_hash_units_manual_state_and_double_offset_guard(tmp_path):
    mapping={'schema':'so101.precision-joint-mapping/1','joint_order':['hinge'],'output':'urdf_joint_radian','physical_verified':False,
             'profile':{'schema':'so101.precision-calibration/1','urdf_sha256':'abc','joints':{'hinge':{'status':'REVIEWED_MANUAL','rad_per_count':.001}}}}
    mapping['sha256']=hashlib.sha256(json.dumps(mapping,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    manifest={'joint_mapping':mapping,'joint_names':['hinge'],'joint_units':['rad'],'source_robot_sha256':'abc','robot':{'mapping_verified':False}}
    mapping_contract(manifest)
    corrupted=copy.deepcopy(manifest);corrupted['joint_mapping']['output']='degrees'
    with pytest.raises(ValueError,match='hash'):mapping_contract(corrupted)
    p,scene=fixture(tmp_path,wrist=True);scene['robot_model']['mapping']=mapping
    scene['robot_model']['simulation_joint_offsets_rad']=value([.02],'estimated',['historical hypothesis'])
    with pytest.raises(ValueError,match='historical'):observation_scene(scene,p.evidence['images'][0],p.root,complete=False)


def test_full_pinhole_audit_and_reused_holdout_guard(tmp_path):
    p,scene=fixture(tmp_path,wrist=True)
    camera=scene['cameras'][0];camera['frame']='world';camera['K']=value([[400,0,320],[0,400,240],[0,0,1]],'optimized')
    t=np.eye(4);t[:3,3]=[.03,-.015,.02];camera['pose']=value(t.tolist(),'optimized')
    e=p.evidence
    for row in e['landmarks']:row['uv']=project_point(scene,camera,row)[0].tolist()
    write(p.root/'input/evidence.yaml',e)
    # Exact synthetic points have subpixel evidence. At 1px assumed uncertainty
    # this narrow distribution is insufficient and must not be overcertified.
    _,limited=fit(p,scene,'quality:camera')
    assert limited['status']=='NEEDS_MORE_DATA' and limited['uncertainty_std']
    result,report=fit(p,scene,'quality:camera',{'pixel_uncertainty_px':.1})
    assert report['status']=='IMPROVED' and result['cameras'][0]['calibration_quality']['state']=='CALIBRATED'
    assert result['cameras'][0]['calibration_quality']['physical_verified'] is False
    from real2sim_builder.project import cameras_audited
    assert cameras_audited(result)
    result['cameras'][0]['K']['value'][0][0]+=5
    assert not cameras_audited(result)
    (p.root/'working/calibration_holdout_usage.jsonl').write_text(json.dumps({'holdout_observations':['pose_3']})+'\n')
    _,report=fit(p,scene,'quality:camera',{'pixel_uncertainty_px':.1})
    assert report['status']=='NEEDS_MORE_DATA' and 'fresh holdout' in report['need']


def test_precision_bound_model_residual_keeps_measured_q_and_rejects_other_mapping(tmp_path):
    from real2sim_builder.calibration.geometry import link_transforms
    from real2sim_builder.project import local_path
    p, scene = fixture(tmp_path, wrist=True)
    mapping = {'schema':'so101.precision-joint-mapping/1','sha256':'a'*64}
    scene['robot_model']['mapping'] = mapping
    scene['robot_model']['simulation_joint_offsets_rad'] = value([.02], 'estimated', ['contact residual'])
    obs = p.evidence['images'][0]
    original = copy.deepcopy(obs)
    with pytest.raises(ValueError, match='historical'):
        observation_scene(scene, obs, p.root, complete=False)
    scene['robot_model']['simulation_joint_offsets_rad']['precision_mapping_sha256'] = mapping['sha256']
    posed = observation_scene(scene, obs, p.root, complete=False)
    expected = link_transforms(local_path(p.root, scene['robot_model']['path']),
        dict(zip(obs['joint_names'], np.asarray(obs['q_measured']) + .02)))
    for link, pose in expected.items():
        assert np.allclose(posed['frames']['robot_link_'+link]['transform']['value'], pose)
    assert obs == original
    scene['robot_model']['mapping']['sha256'] = 'b'*64
    with pytest.raises(ValueError, match='recorded Precision'):
        observation_scene(scene, obs, p.root, complete=False)


def test_bound_residual_rejects_different_recorded_capture_mapping(tmp_path):
    p, scene = fixture(tmp_path, wrist=True)
    scene['robot_model']['mapping'] = {'schema':'so101.precision-joint-mapping/1','sha256':'a'*64}
    scene['robot_model']['simulation_joint_offsets_rad'] = {
        **value([.02],'estimated',['contact residual']), 'precision_mapping_sha256':'a'*64}
    write(p.root/'input/capture_reference.yaml', {'joint_mapping':{'sha256':'b'*64}})
    obs=copy.deepcopy(p.evidence['images'][0]);obs['capture_manifest']='input/capture_reference.yaml'
    with pytest.raises(ValueError,match='capture Precision mapping'):
        observation_scene(scene,obs,p.root,complete=False)


def test_segmented_cloud_full_coverage_required_before_dimensions_update(tmp_path,scene):
    from real2sim_builder.calibration.geometry import fit_depth_geometry
    from real2sim_builder.project import value
    scene['objects'][1]['dimensions']=value([.05,.05,.05],'estimated')
    points=np.array([[x,y,z] for x in [-.03,.03] for y in [-.04,.04] for z in [0,.06]])
    np.save(tmp_path/'cloud.npy',points);evidence={'point_clouds':[{'path':'cloud.npy','object':'block','frame':'world'}]}
    fitted,report=fit_depth_geometry(scene,evidence,tmp_path)
    assert fitted['objects'][1]['dimensions']==scene['objects'][1]['dimensions'] and not report[0]['complete_coverage']
    evidence['point_clouds'][0]['full_bounds']=True;fitted,report=fit_depth_geometry(scene,evidence,tmp_path)
    np.testing.assert_allclose(fitted['objects'][1]['dimensions']['value'],[.06,.08,.06])
    assert fitted['objects'][1]['dimensions']['provenance']=='derived' and report[0]['applied']


def test_zero_distortion_rectification_is_idempotent(tmp_path,scene):
    from real2sim_builder.project import Project
    from real2sim_builder.calibration.geometry import undistort_evidence
    p=Project.create(tmp_path/'projects','camera');p.save_scene(scene);before=p.signature()
    undistort_evidence(p);assert p.signature()==before


def test_passive_friction_identification_retains_measured_mass_requirement(scene,tmp_path):
    from real2sim_builder.calibration.physics import trajectory,fit
    scene['objects'][1]['physics']['mass_kg']=value(.12,'measured');scene['objects'][1]['physics']['friction']=value(.7,'measured')
    motion={'object':'block','support':'table','times_s':[0,.1,.2,.3,.4],'positions_world_m':[[0,0,.03]]*5,'initial_velocity_m_s':[1.,0,0],'split':'train','fit_parameters':['friction']}
    motion['positions_world_m']=trajectory(scene,tmp_path,tmp_path,motion).tolist()
    held=copy.deepcopy(motion);held['split']='validation';held['initial_velocity_m_s']=[.8,0,0];held['positions_world_m']=trajectory(scene,tmp_path,tmp_path,held).tolist()
    seed=copy.deepcopy(scene);seed['objects'][1]['physics']['friction']=value(.5,'estimated')
    fitted,report=fit(seed,tmp_path,tmp_path,[motion,held])
    assert abs(fitted['objects'][1]['physics']['friction']['value']-.7)<.05 and report[-1]['rmse_m']<.005
    seed['objects'][1]['physics']['mass_kg']=value(None)
    with pytest.raises(ValueError,match='measured object mass'):trajectory(seed,tmp_path,tmp_path,motion)

@pytest.mark.parametrize('camera_id',['side','wrist'])
def test_b03_actual_camera_matrices_and_projection_direction(camera_id):
    from real2sim_builder.project import empty
    root=Path(__file__).resolve().parents[2];saved=json.loads((root/'docs/evidence/b03/camera-probes.json').read_text())['geometry'][camera_id]
    scene=empty('B03 actual camera');parent=saved['parent']
    world_parent=np.eye(4)
    if parent!='world':
        world_parent[:3,:3]=Rotation.from_euler('xyz',[.3,-.2,.1]).as_matrix();world_parent[:3,3]=[.1,-.15,.22]
        scene['frames'][parent]={'parent':'world','transform':value(world_parent.tolist(),'measured')}
    camera={'id':camera_id,'frame':parent,'pose':value(saved['T_parent_optical'],'calibrated'),'K':value(saved['K_raw'],'calibrated'),'resolution':saved['resolution'],'distortion':value(saved['distortion'],'calibrated')}
    scene['cameras']=[camera];t_world_optical=world_parent@np.array(saved['T_parent_optical'])
    for point in [np.array([0.,0.,.5]),np.array([.06,-.03,.7]),np.array([-.01,.02,-.4])]:
        world=(t_world_optical@np.r_[point,1])[:3];uv,z=project_point(scene,camera,{'point_m':world.tolist(),'frame':'world'})
        k=np.array(saved['K_raw']);expected=(k@point)[:2]/point[2]
        np.testing.assert_allclose(uv,expected,rtol=0,atol=1e-10);assert abs(z-point[2])<1e-12
    optical_to_engine=np.eye(4);optical_to_engine[:3,:3]=np.diag([1,-1,-1])
    np.testing.assert_array_equal(np.array(saved['T_parent_optical'])@optical_to_engine,np.array(saved['T_parent_engine_camera']))
    assert saved['parent']==('world' if camera_id=='side' else 'gripper')


def test_baked_runtime_calibration_is_not_reapplied_by_camera_fit(scene):
    # Geometry fitting sees the declared model state only. It never mutates q or
    # invokes motor calibration; the shared package validator owns apply graph.
    from real2sim_builder.calibration.geometry import simulation_offsets
    model={'joint_names':['hinge'],'simulation_joint_offsets_rad':value([.02],'estimated',['contact residual']),'mapping':{'schema':'so101.precision-joint-mapping/1','sha256':'a'*64}}
    model['simulation_joint_offsets_rad']['precision_mapping_sha256']='b'*64
    with pytest.raises(ValueError,match='recorded Precision'):simulation_offsets(model)
    model['simulation_joint_offsets_rad']['precision_mapping_sha256']='a'*64
    np.testing.assert_array_equal(simulation_offsets(model),[.02])
    scene['simulation_configuration']={'mode':'precision_bound_residual','application':'baked'}
    before=copy.deepcopy(scene);fitted,_=fit_cameras(scene,[])
    assert scene==before and fitted==before


from PIL import Image
from real2sim_builder.project import add_image

def test_rectification_preserves_original_and_is_resume_safe(tmp_path,scene):
    from real2sim_builder.calibration.geometry import undistort_evidence
    from real2sim_builder.calibration.camera import project_point
    project=Project.create(tmp_path/'projects','Lens');scene['cameras'][0]['distortion']['value']=[.2,0,0,0,0]
    project.save_scene(scene);path=tmp_path/'original.png'
    Image.fromarray(np.zeros((120,160,3),np.uint8)).save(path);original=path.read_bytes()
    row=add_image(project,path,'side','train');point={'camera':'side','point_m':[.1,0,0],'uv':[0,0],'split':'train'}
    point['uv']=project_point(scene,scene['cameras'][0],point)[0].tolist()
    evidence=project.evidence;evidence['landmarks'].append(point);write(project.root/'input/evidence.yaml',evidence)
    undistort_evidence(project);first=project.evidence
    assert first['images'][0]['original_path']==row['path'] and path.read_bytes()==original
    expected=project_point(project.scene,project.scene['cameras'][0],point)[0]
    assert np.allclose(first['landmarks'][0]['uv'],expected,atol=1e-3)
    undistort_evidence(project);assert project.evidence==first
    add_image(project,path,'side');assert len(project.evidence['images'])==1
