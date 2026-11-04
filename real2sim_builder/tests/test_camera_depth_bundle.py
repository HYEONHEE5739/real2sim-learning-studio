import copy
import numpy as np
from scipy.spatial.transform import Rotation


def test_hand_eye_recovers_metric_scale_and_shared_mount_without_user_calibration():
    from real2sim_builder.calibration.registration import wrist_from_motion
    rng=np.random.default_rng(3);fk=[]
    base=np.eye(4);base[:3,:3]=Rotation.from_euler('xyz',[.2,.1,-.2]).as_matrix();base[:3,3]=[.3,-.2,.5]
    mount=np.eye(4);mount[:3,:3]=Rotation.from_euler('xyz',[.1,-.2,.3]).as_matrix();mount[:3,3]=[.03,.02,.01]
    cameras=[]
    for _ in range(9):
        f=np.eye(4);f[:3,:3]=Rotation.from_rotvec(rng.normal(0,.4,3)).as_matrix();f[:3,3]=rng.uniform(-.2,.2,3)
        fk.append(f);c=base@f@mount;c[:3,3]/=2.3;cameras.append(c)
    result=wrist_from_motion(fk,cameras)
    assert result['status']=='OPTIMIZED' and result['physical_verified'] is False
    np.testing.assert_allclose(result['scale'],2.3,atol=1e-6)
    np.testing.assert_allclose(result['T_link_camera'],mount,atol=1e-6)
    unresolved=wrist_from_motion([np.eye(4)]*5,[np.eye(4)]*5)
    assert unresolved['status']=='UNRESOLVED'


def test_overlapping_depth_batches_align_similarities_and_disconnected_batches_stay_unresolved(tmp_path):
    from real2sim_builder.calibration.registration import align_depth_batches
    # Same non-planar depth view, independent DA3 coordinate frames/scales.
    k=np.array([[30,0,20],[0,30,15],[0,0,1.]])
    v,u=np.mgrid[:30,:40];z=1+u*.002+v*v*.0004
    a=np.eye(4);b=np.eye(4);b[:3,:3]=Rotation.from_euler('y',.2).as_matrix();b[:3,3]=[.2,.1,0]
    batches=[]
    for index,(ext,scale,ids)in enumerate([(a,1.,['ref','view1']),(b,2.,['ref','view2']),(a,1.,['isolated'])]):
        path=tmp_path/f'{index}.npz';np.savez(path,depth=np.repeat((z*scale)[None],len(ids),axis=0),
            intrinsics=np.repeat(k[None],len(ids),axis=0),extrinsics=np.repeat(ext[None],len(ids),axis=0),
            original_to_processed=np.repeat(np.eye(3)[None],len(ids),axis=0))
        from real2sim_builder.files import sha
        batches.append({'path':str(path),'image_ids':ids,'metadata':{'sha256':sha(path)}})
    result=align_depth_batches(batches)
    assert result['batches'][1]['state']=='PREDICTED'
    np.testing.assert_allclose(result['batches'][1]['scale'],.5,atol=1e-8)
    assert result['batches'][2]['state']=='UNRESOLVED'


def test_joint_depth_fit_moves_camera_and_object_and_reprojects_clouds(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.scene import value,world_pose
    from real2sim_builder.calibration.hybrid import surface_points
    from real2sim_builder.calibration.joint import fit_depth_bundle
    from real2sim_builder.files import sha
    from test_builder_export import legacy_scene
    scene=legacy_scene();p=Project.create(tmp_path/'projects','bundle')
    scene['objects'][1]['pose']['provenance']='estimated'
    scene['cameras'][0]['pose']['provenance']='estimated'
    true=copy.deepcopy(scene);rows=[]
    for name in ['table','block']:
        obj=next(o for o in true['objects']if o['id']==name)
        points=surface_points(obj,true,p.root,800)
        world=points@world_pose(true,obj)[:3,:3].T+world_pose(true,obj)[:3,3]
        pose=world_pose(true,true['cameras'][0]);optical=(world-pose[:3,3])@pose[:3,:3]
        path=p.root/f'{name}.npz';np.savez(path,points_camera_relative=optical,points_world_m=world)
        rows.append({'image_id':'side_1','object_id':name,'camera':'side','split':'train','group_id':'g1',
                     'path':path.relative_to(p.root).as_posix(),'sha256':sha(path),'depth_scale':1.,'frame':'world','units':'m'})
    scene['objects'][1]['pose']['value'][0][3]+=.025
    scene['cameras'][0]['pose']['value'][1][3]+=.02
    scene['reconstruction_observations']={'clouds':rows}
    baseline=copy.deepcopy(scene)
    result,report=fit_depth_bundle(p,scene,{'objects':['block'],'cameras':['side'],'surface_samples':800,'max_nfev':90,'optimize_depth_scale':False})
    assert report['status']=='IMPROVED',report
    assert report['after_rmse_m']<report['before_rmse_m']*.2
    np.testing.assert_allclose(result['objects'][1]['pose']['value'],true['objects'][1]['pose']['value'],atol=.003)
    np.testing.assert_allclose(result['cameras'][0]['pose']['value'],true['cameras'][0]['pose']['value'],atol=.003)
    assert scene==baseline and result['objects'][0]==true['objects'][0]
    assert result['objects'][1]['dimensions']==true['objects'][1]['dimensions']


def test_camera_initialization_from_wrist_capture_needs_no_k_or_board_clicks(tmp_path):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.scene import empty,value
    from real2sim_builder.files import sha
    from real2sim_builder.observations import register_image,predict_views,registered_images
    from real2sim_builder.capture import observation_scene
    from real2sim_builder.calibration.geometry import link_transforms
    from PIL import Image
    p=Project.create(tmp_path/'projects','automatic camera');model=p.root/'input/robot.urdf'
    xml=['<robot name="fixture"><link name="base"/>'];names=[];parent='base'
    for n,axis in enumerate(['0 0 1','0 1 0','1 0 0','0 1 0','1 0 0','0 0 1']):
        link=f'l{n}';name=f'j{n}';names.append(name)
        xml.append(f'<link name="{link}"/><joint name="{name}" type="revolute"><parent link="{parent}"/><child link="{link}"/><origin xyz=".04 .01 .03"/><axis xyz="{axis}"/><limit lower="-2" upper="2" effort="1" velocity="1"/></joint>');parent=link
    model.write_text(''.join(xml)+'</robot>')
    scene=empty('motion');scene['robot_model']={'path':'input/robot.urdf','format':'urdf','model_sha256':sha(model),'joint_names':names,'mapping':{'sha256':'a'*64}}
    scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated',['robot base coordinate gauge'])}
    scene['frames']['robot_link_l5']={'parent':'robot_base','transform':value(np.eye(4).tolist(),'derived')}
    scene['cameras']=[{'id':'wrist','frame':'robot_link_l5','pose':value(None),'K':value(None),'distortion':value([0.]*5,'estimated'),'resolution':[80,60]}]
    p.save_scene(scene);rng=np.random.default_rng(8);images=[];extrinsics=[]
    base=np.eye(4);base[:3,3]=[.3,.1,.4];mount=np.eye(4);mount[:3,3]=[.02,0,.04]
    for n in range(9):
        q=rng.uniform(-.8,.8,6).tolist();fk=link_transforms(model,dict(zip(names,q)))['l5'];pose=base@fk@mount;pose[:3,3]/=1.8
        extrinsics.append(np.linalg.inv(pose));source=tmp_path/f'image{n}.png';Image.new('RGB',(80,60),(n,0,0)).save(source)
        images.append(register_image(p,source,camera='wrist',camera_type='wrist',scene_state='layout',joint_record={'q_measured':q,'joint_names':names,'joint_units':['rad']*6,
            'mapping_sha256':'a'*64,'robot_model_sha256':sha(model),'image_timestamp_ns':n*1000,'joint_timestamp_ns':n*1000}))
    original=p.signature();candidate=Candidate.create(p,'auto');batch=candidate.root/'depth.npz'
    np.savez(batch,depth=np.ones((9,60,80)),intrinsics=np.repeat(np.array([[[60,0,40],[0,60,30],[0,0,1.]]]),9,axis=0),
        extrinsics=np.asarray(extrinsics),original_to_processed=np.repeat(np.eye(3)[None],9,axis=0))
    report={'images':images,'scene_state_id':'layout','depth_batches':[{'path':str(batch),'metadata':{'sha256':sha(batch)},'image_ids':[i['id']for i in images]}]}
    result=predict_views(candidate,report)
    assert result['status']=='PREDICTED'and len(result['views'])==9,result
    assert result['metric_alignment']['scale']==__import__('pytest').approx(1.8,abs=1e-6)
    assert not result['physical_verified']and p.signature()==original
    np.testing.assert_allclose(candidate.scene['cameras'][0]['pose']['value'],mount,atol=1e-6)
    assert len(registered_images(p,'layout',scene=candidate.scene)[0])==9
    assert observation_scene(candidate.scene,images[-1],p.root,complete=False)['cameras'][0]['K']['value']is not None


def test_camera_registration_does_not_erase_capture_quality_exclusions(tmp_path):
    from real2sim_builder.observations import register_image,registered_images
    from real2sim_builder.project import Project
    from real2sim_builder.files import write
    from real2sim_builder.scene import camera_calibration_signature
    from PIL import Image
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'quality');photo=tmp_path/'photo.png';Image.new('RGB',(160,120)).save(photo)
    record=register_image(p,photo,camera='side',camera_type='side',scene_state='layout')
    evidence=p.evidence;evidence['images'][0]['capture_quality_reasons']=['blur_or_textureless_image'];write(p.root/'input/evidence.yaml',evidence)
    from real2sim_builder.observations import source_record_digest
    record=evidence['images'][0];scene=legacy_scene();scene['view_registrations']={record['id']:{'status':'REGISTERED_ESTIMATED',
        'source_image_sha256':record['sha256'],'image_record_sha256':source_record_digest(record),
        'camera_signature':camera_calibration_signature(scene,scene['cameras'][0])}}
    assert not registered_images(p,'layout',scene=scene)[0]


def test_comparison_does_not_mark_rendered_but_unfitted_scene_ready(tmp_path,monkeypatch):
    from real2sim_builder.project import Project
    from real2sim_builder.calibration import hybrid,joint
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'projects','no solution');scene=legacy_scene()
    monkeypatch.setattr(hybrid,'cloud_inputs',lambda *_:[{'split':'train','image_id':'one'}])
    metrics={'images':[{'split':'train','image_id':'one','mae':.1}]}
    monkeypatch.setattr(hybrid,'alignment_metrics',lambda *args:metrics)
    unavailable=lambda p,s,*args:(s,{'status':'NEEDS_MORE_DATA','needs':['no fit inputs']})
    monkeypatch.setattr(hybrid,'fit_clouds',unavailable);monkeypatch.setattr(hybrid,'refine_masks',unavailable)
    monkeypatch.setattr(joint,'fit_joint_scene',unavailable);monkeypatch.setattr(joint,'fit_depth_bundle',unavailable)
    _,report=hybrid.compare_backends(p,scene,p.root/'scratch/compare')
    assert report['status']=='NEEDS_MORE_DATA'
    assert report['backends']['hybrid']['status']=='NEEDS_MORE_DATA'


def test_pipeline_reports_modeling_states_instead_of_generic_missing_data(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.automation import reconstruct
    p=Project.create(tmp_path/'projects','empty')
    report=reconstruct(p,candidate='analysis',config={})
    assert report['status']=='WAITING_FOR_CODEX_ANALYSIS'
    assert p.state['status']==report['status']
    report=reconstruct(p,candidate='model',config={'objects':{'block':{'prompt':'red block'}}})
    assert report['status']=='WAITING_FOR_CODEX'
    assert p.state['status']==report['status']and report['physical_verified']is False


def test_draft_gate_requires_training_solved_render_finite_pose_and_geometry(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.automation import draft_readiness
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'projects','readiness');scene=legacy_scene()
    solved={'status':'PROVISIONAL_COMPARISON','requested_backend':'hybrid','backends':{'hybrid':{
        'stages':{'icp':{'status':'ESTIMATED','objects':{'block':{'status':'ESTIMATED'}}}},
        'metrics':{'images':[{'split':'train','image_id':'photo','mae':.1}]}}}}
    assert draft_readiness(p,scene,solved)['status']=='DRAFT_READY'
    for kind in ['validation_only','backend_failed','missing_visual','missing_pose','nonfinite','no_camera']:
        trial=copy.deepcopy(scene);report=copy.deepcopy(solved)
        if kind=='validation_only':report['backends']['hybrid']['metrics']['images'][0]['split']='validation'
        elif kind=='backend_failed':report['backends']['hybrid']['stages']['icp']['status']='FAILED'
        elif kind=='missing_visual':trial['objects'][1]['visual']={'type':'unknown'}
        elif kind=='missing_pose':trial['objects'][1]['pose']['value']=None
        elif kind=='nonfinite':trial['cameras'][0]['pose']['value'][0][3]=float('nan')
        else:trial['cameras']=[]
        result=draft_readiness(p,trial,report)
        assert result['status']=='NEEDS_MORE_DATA',kind
        assert result['physical_verified']is False


def test_reconstruction_cli_and_project_report_same_waiting_state(tmp_path,capsys):
    from real2sim_builder.project import Project
    from real2sim_builder.files import write,read
    from real2sim_builder.cli import main
    import json
    p=Project.create(tmp_path/'projects','cli state');write(p.root/'input/reconstruction.yaml',{})
    assert main(['reconstruct',str(p.root),'--candidate','analysis'])==2
    result=json.loads(capsys.readouterr().out)
    assert result['status']==p.state['status']=='WAITING_FOR_CODEX_ANALYSIS'
    assert read(p.root/'scratch/agent/analysis/reconstruction.json')['status']==result['status']


def test_empty_and_validation_only_clouds_cannot_prepare_a_draft(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.calibration.hybrid import compare_backends
    from real2sim_builder.files import sha
    from test_builder_export import legacy_scene
    from PIL import Image
    p=Project.create(tmp_path/'projects','no training');scene=legacy_scene()
    _,report=compare_backends(p,scene,p.root/'scratch/empty')
    assert report['status']=='NEEDS_MORE_DATA'and not report['backends']
    cloud=p.root/'input/held.npz';np.savez(cloud,points_world_m=np.zeros((100,3)))
    mask=p.root/'input/held.png';Image.new('L',(160,120)).save(mask)
    scene['reconstruction_observations']={'clouds':[{'image_id':'held','object_id':'block','split':'validation','group_id':'held',
        'path':'input/held.npz','sha256':sha(cloud),'mask':'input/held.png','mask_sha256':sha(mask),'units':'m','frame':'world'}]}
    _,report=compare_backends(p,scene,p.root/'scratch/held')
    assert report['status']=='NEEDS_MORE_DATA'and not report['backends']
