import numpy as np
import pytest


def test_dense_frame_alignment_is_one_robust_similarity_not_camera_pose_substitution():
    from real2sim_builder.sfm import robust_similarity,transform_points
    rng=np.random.default_rng(7);points=rng.normal(size=(200,3))
    rotation=np.array([[0.,-1,0],[1,0,0],[0,0,1]])
    target=2.4*points@rotation.T+[.2,-.7,2.]
    corrupted=target.copy();corrupted[:40]+=rng.normal(size=(40,3))*10
    fitted=robust_similarity(points,corrupted)
    assert fitted['status']=='ALIGNED_RELATIVE'and not fitted['metric_scale_verified']
    assert fitted['inliers']>=160
    np.testing.assert_allclose(transform_points(points,fitted),target,atol=1e-7)
    assert fitted['scale']==pytest.approx(2.4)


def test_rank_deficiency_reflection_and_inconsistent_dense_geometry_are_unresolved():
    from real2sim_builder.sfm import robust_similarity
    line=np.c_[np.arange(50),np.zeros((50,2))]
    assert robust_similarity(line,line)['status']=='UNRESOLVED'
    rng=np.random.default_rng(4);a=rng.normal(size=(100,3));b=a.copy();b[:,0]*=-1
    assert robust_similarity(a,b)['status']=='UNRESOLVED'
    assert robust_similarity(a,rng.normal(size=(100,3)))['status']=='UNRESOLVED'


def test_reprojection_uses_camera_optical_z_cheirality_and_z_buffer_without_hole_fill():
    from real2sim_builder.sfm import optical_depth
    k=np.array([[10.,0,2],[0,10,2],[0,0,1]])
    w2c=np.eye(4);w2c[2,3]=-3
    world=np.array([[0,0,5],[0,0,7],[.2,0,5],[0,0,2],[np.nan,0,0]])
    z,conf,report=optical_depth(world,np.ones(5),k,w2c,(5,5))
    assert z[2,2]==2 and z[2,3]==2 and np.count_nonzero(np.isfinite(z))==2
    assert np.isnan(z[0,0])and conf[0,0]==0 and report['cheirality_rejected']==1
    # Using the inverse pose is observable: it must not silently yield the same depth.
    other,_,_=optical_depth(world,np.ones(5),k,np.linalg.inv(w2c),(5,5))
    assert other[2,2]!=z[2,2]


def test_pixel_affine_depth_and_distortion_roundtrip_keeps_only_observed_samples():
    from real2sim_builder.sfm import optical_depth
    from real2sim_builder.inference import object_points
    from real2sim_builder.cameras import optical_rays,project_pixels
    k=np.array([[50.,0,20],[0,55,15],[0,0,1]]);dist=[.03,0,0,0,0]
    uv=np.array([[10.,10],[20,15],[30,20]])
    lens={'K':{'value':k},'distortion':{'value':dist}}
    points=optical_rays(lens,uv)*np.array([2,3,4])[:,None]
    np.testing.assert_allclose(project_pixels(lens,points),uv,atol=1e-5)
    z,confidence,_=optical_depth(points,np.ones(3),k,np.eye(4),(30,40),distortion=dist,source_pixels=uv)
    recovered,_=object_points(z,np.ones((60,80)),k,np.diag([.5,.5,1.]),confidence=confidence,erode_px=0,distortion=dist)
    np.testing.assert_allclose(recovered,points,atol=1e-5)
    bad,_,_=optical_depth(points,np.ones(3),k,np.eye(4),(30,40),source_pixels=uv+50)
    assert not np.isfinite(bad).any()


def test_backend_defaults_and_legacy_configuration_are_explicit():
    from real2sim_builder.sfm import backend
    assert backend({})=='mast3r_colmap'
    assert backend({'da3':{'python':'old'}})=='mast3r_colmap'
    assert backend({'da3':{},'geometry':{'backend':'mast3r_colmap'}})=='mast3r_colmap'
    with pytest.raises(ValueError,match='retired'):backend({'geometry':{'backend':'da3'}})
    with pytest.raises(ValueError):backend({'geometry':{'backend':'sift_fallback'}})


def test_retired_da3_never_executes_or_silently_falls_back():
    from real2sim_builder.sfm import backend
    from real2sim_builder.inference import _worker
    assert backend({'da3':{'python':'old saved interpreter'}})=='mast3r_colmap'
    with pytest.raises(ValueError,match='retired|removed|지원하지'):
        backend({'geometry':{'backend':'da3'}})
    with pytest.raises(ValueError,match='Unknown|retired|removed'):_worker('da3',{})


def test_common_sfm_frame_is_not_reestimated_and_disjoint_components_are_not_merged(tmp_path):
    from real2sim_builder.calibration.registration import align_depth_batches
    from real2sim_builder.files import sha
    path=tmp_path/'depth.npz';np.savez(path,invalid_legacy_data=np.ones(3))
    batch={'path':str(path),'metadata':{'common_frame':'component1','sha256':sha(path)}}
    result=align_depth_batches([batch])
    assert result['batches'][0]['state']=='PREDICTED'and not result['metric_scale_verified']
    other={'path':str(path),'metadata':{**batch['metadata'],'common_frame':'component2'}}
    disconnected=align_depth_batches([batch,other])
    assert disconnected['batches'][0]['state']=='PREDICTED'
    assert disconnected['batches'][1]['state']=='UNRESOLVED'
    assert disconnected['batches'][0]['scale']==1. and not disconnected['metric_scale_verified']
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):align_depth_batches([batch])


def test_disconnected_components_keep_largest_usable_train_component_without_merging(tmp_path):
    from real2sim_builder.calibration.registration import align_depth_batches
    from real2sim_builder.files import sha
    path=tmp_path/'relative.npz';np.savez(path,not_metric=np.ones(1))
    small={'path':str(path),'image_ids':['a','overlap'],'metadata':{'common_frame':'small','sha256':sha(path)}}
    large={'path':str(path),'image_ids':['b','c','d','overlap'],'metadata':{'common_frame':'large','sha256':sha(path)}}
    result=align_depth_batches([small,large])
    assert result['batches'][0]['state']=='UNRESOLVED'
    assert result['batches'][1]['state']=='PREDICTED'and result['batches'][1]['scale']==1.
    assert result['batches'][1]['T_common_batch']==np.eye(4).tolist()
    assert not result['metric_scale_verified']


def test_new_sfm_cloud_contract_consumes_metric_registration_without_fabricating_scale(tmp_path):
    from PIL import Image
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.scene import empty,value
    from real2sim_builder.observations import register_image,register_views
    from real2sim_builder.inference import build_point_clouds
    from real2sim_builder.files import sha
    project=Project.create(tmp_path,'sfm metric');scene=empty('sfm metric')
    scene['cameras']=[{'id':'phone','frame':'world','pose':value(None),'resolution':[80,60],
        'K':value([[60,0,40],[0,60,30],[0,0,1]],'calibrated',['synthetic lens']),
        'distortion':value([0.]*5,'calibrated',['synthetic lens'])}]
    project.save_scene(scene);source=tmp_path/'photo.png';Image.new('RGB',(80,60)).save(source)
    image=register_image(project,source,camera='phone',camera_type='external',scene_state='layout')
    candidate=Candidate.create(project,'metric');folder=candidate.root/'.cache/inference';folder.mkdir(parents=True)
    mask=folder/'mask.png';Image.new('L',(80,60),255).save(mask)
    path=folder/'depth.npz';np.savez(path,depth=np.full((1,30,40),2.),intrinsics=np.array([[[30,0,20],[0,30,15],[0,0,1]]]),
        extrinsics=np.eye(4)[None],original_to_processed=np.diag([.5,.5,1.])[None],distortion=np.zeros((1,5)),conf=np.ones((1,30,40)))
    report={'scene_state_id':'layout','backend':'mast3r_colmap','depth_batches':[{'path':str(path),'image_ids':[image['id']],
       'metadata':{'sha256':sha(path),'backend':'mast3r_colmap','common_frame':'one','units':'sfm_relative'}}],
       'segments':[{'image_id':image['id'],'object_id':'block','source_image_sha256':image['sha256'],'masks':[{'path':str(mask),'sha256':sha(mask)}]}]}
    assert build_point_clouds(candidate,report)['status']=='NEEDS_MORE_DATA'
    register_views(candidate,{image['id']:{'source':'measured','evidence':['synthetic board'],
       'world_points_m':[[-.3,-.2,1],[.3,-.2,1],[.3,.2,1],[-.3,.2,1]],'uv_px':[[22,18],[58,18],[58,42],[22,42]]}},scene_state='layout')
    result=build_point_clouds(candidate,report)
    assert result['status']=='METRIC_ESTIMATED'and result['clouds'][0]['point_filter']['units']=='sfm_relative'
    with np.load(project.root/result['clouds'][0]['path'])as d:np.testing.assert_allclose(d['points_world_m'][:,2],1,atol=1e-6)


def test_geometry_optional_arrays_cannot_misrepresent_pixel_or_lens_coordinates():
    from real2sim_builder.inference import validate_depth_output
    arrays={'depth':np.ones((1,4,6)),'intrinsics':np.eye(3)[None],'extrinsics':np.eye(4)[None]}
    for name,value in [('distortion',np.zeros((1,3))),('distortion',np.full((1,5),np.nan)),
                       ('original_to_processed',np.zeros((1,3,3))),('conf',np.full((1,4,6),-1.))]:
        with pytest.raises(ValueError):validate_depth_output({**arrays,name:value},1)


@pytest.mark.parametrize('static_role',['support_surface','workspace','background'])
def test_geometry_worker_resume_keeps_completed_stage_and_excludes_holdout_and_robot(tmp_path,monkeypatch,static_role):
    from pathlib import Path
    from PIL import Image
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.observations import register_image
    from real2sim_builder import inference,sfm
    from real2sim_builder.files import sha
    project=Project.create(tmp_path/'projects','resume');rows=[];prepared={};segments=[]
    for i,split in enumerate(['train','train','validation']):
        file=tmp_path/f'rgb{i}.png';Image.new('RGB',(40,30),(i,0,0)).save(file)
        row=register_image(project,file,camera=f'phone{i}',camera_type='external',scene_state='layout',split=split)
        rows.append(row);prepared[row['id']]={'path':str(file),'sha256':sha(file)}
        for obj,left in [('table',0),('robot',20)]:
            mask=tmp_path/f'{i}_{obj}.png';a=np.full((30,40),255,np.uint8)if obj=='table'else np.zeros((30,40),np.uint8)
            if left:a[:,left:]=255
            Image.fromarray(a).save(mask)
            segments.append({'image_id':row['id'],'object_id':obj,'masks':[{'path':str(mask),'sha256':sha(mask)}]})
    candidate=Candidate.create(project,'same');root=candidate.root/'.cache/inference';root.mkdir(parents=True)
    config={'objects':{'table':{'role':static_role},'robot':{'role':'reference_robot'}},
            'geometry':{'python':'mast','model':'weights','source':'source','colmap_python':'colmap'}}
    monkeypatch.setattr(inference,'_runtime',lambda p,c,k,f:(c[k],{'runtime':k}))
    calls=[];cancel=[True]
    def worker(project,python,kind,request,folder,timeout):
        calls.append(kind);out=Path(request['output']);out.mkdir()
        if kind=='mast3r':
            assert [r['id']for r in request['images']]==[r['id']for r in rows[:2]]
            mask=np.asarray(Image.open(request['images'][0]['static_mask']))
            assert mask[:,:20].all()and not mask[:,20:].any()
            sfm.publish(out,{'status':'POINTMAPS_READY'})
        elif cancel[0]:raise InterruptedError('stop after completed GPU stage')
        else:sfm.publish(out,{'status':'UNRESOLVED','components':[],'needs':['no geometric initialization']})
    monkeypatch.setattr(inference,'_run_worker',worker)
    with pytest.raises(InterruptedError):sfm.run_geometry(candidate,config,rows,prepared,segments,root)
    cancel[0]=False
    batches,report=sfm.run_geometry(candidate,config,rows,prepared,segments,root)
    assert calls==['mast3r','colmap','colmap']and not batches
    assert report['status']=='UNRESOLVED'and any('validation excluded'in s for s in report['needs'])
    sfm.run_geometry(candidate,config,rows,prepared,segments,root)
    assert len(calls)==3
    (Path(report['colmap_output'])/'result.json').write_text('{}')
    with pytest.raises(ValueError,match='changed'):sfm.run_geometry(candidate,config,rows,prepared,segments,root)


def test_dense_batch_metadata_does_not_duplicate_per_track_residuals_into_modeling_inputs(tmp_path,monkeypatch):
    from pathlib import Path
    from PIL import Image
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder import sfm,inference
    from real2sim_builder.files import sha
    project=Project.create(tmp_path/'projects','compact handoff');candidate=Candidate.create(project,'compact')
    root=candidate.root/'.cache/inference';root.mkdir(parents=True);rows=[];prepared={};segments=[]
    for i in range(2):
        rgb=tmp_path/f'{i}.png';Image.new('RGB',(40,30),'white').save(rgb)
        mask=tmp_path/f'mask{i}.png';Image.new('L',(40,30),255).save(mask)
        key=str(i);rows.append({'id':key,'sha256':sha(rgb),'resolution':[40,30],'split':'train','camera':'phone','scene_state_id':'layout'})
        prepared[key]={'path':str(rgb),'sha256':sha(rgb)}
        segments.append({'image_id':key,'object_id':'table','masks':[{'path':str(mask),'sha256':sha(mask)}]})
    monkeypatch.setattr(inference,'_runtime',lambda p,c,k,f:(c[k],{'runtime':k}))
    def worker(project,python,kind,request,folder,timeout):
        out=Path(request['output']);out.mkdir()
        if kind=='mast3r':sfm.publish(out,{'status':'POINTMAPS_READY'})
        else:
            file=out/'depth.npz';np.savez(file,depth=np.ones((2,30,40)),intrinsics=np.repeat(np.eye(3)[None],2,axis=0),extrinsics=np.repeat(np.eye(4)[None],2,axis=0))
            sfm.publish(out,{'status':'GEOMETRY_READY','components':[{'component':'0','image_ids':['0','1'],'path':str(file),
                'alignment':{'scale':2.,'T_target_source':np.eye(4).tolist(),'residual':[.001]*5000}}],'needs':[]})
    monkeypatch.setattr(inference,'_run_worker',worker)
    batches,result=sfm.run_geometry(candidate,{'objects':{'table':{'role':'support_surface'}},
        'geometry':{'python':'mast','model':'weights','source':'source','colmap_python':'colmap'}},rows,prepared,segments,root)
    assert 'residual'not in batches[0]['metadata']['alignment']
    assert batches[0]['metadata']['alignment']['scale']==2.
    assert len(result['components'][0]['alignment']['residual'])==5000


@pytest.mark.parametrize('kind',['mast3r','colmap'])
def test_owned_geometry_children_stop_and_report_oom_without_affecting_other_processes(tmp_path,kind):
    import sys,subprocess,time
    from pathlib import Path
    from real2sim_builder.inference import _run_worker
    from real2sim_builder.project import Project
    project=Project.create(tmp_path/'projects','owned worker');pid=tmp_path/'owned.pid'
    executable=tmp_path/'test-python'
    executable.write_text('#!'+sys.executable+'\nimport subprocess,sys,time\nfrom pathlib import Path\n'
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\n'
        'Path('+repr(str(pid))+').write_text(str(child.pid))\ntime.sleep(30)\n')
    executable.chmod(0o700)
    def stop():
        if pid.exists():raise InterruptedError('controlled stop')
    project.checkpoint=stop
    unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
    try:
        with pytest.raises(InterruptedError):_run_worker(project,executable,kind,{},tmp_path/'stop',5)
        state=Path('/proc')/pid.read_text()/'stat'
        try:status=state.read_text().split()[2]
        except (FileNotFoundError,ProcessLookupError):status=None
        assert status in(None,'Z')
        assert unrelated.poll()is None
    finally:unrelated.terminate();unrelated.wait(timeout=3)
    project.checkpoint=lambda:None
    executable.write_text('#!'+sys.executable+'\nimport sys\nprint("CUDA out of memory",flush=True)\nsys.exit(7)\n')
    with pytest.raises(RuntimeError,match='VRAM_OUT_OF_MEMORY'):_run_worker(project,executable,kind,{},tmp_path/'oom',5)


def test_sfm_depth_contract_reaches_existing_metric_fusion_assets_and_native_fitting(tmp_path):
    """Synthetic metric evidence plus real renderer; no learned/real accuracy claim."""
    from PIL import Image
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder.project import Candidate
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.observations import register_views
    from real2sim_builder.scene import world_pose
    from real2sim_builder.files import sha,write
    from real2sim_builder.inference import build_point_clouds
    from real2sim_builder.authoring import modeling_groups
    from real2sim_builder.calibration.hybrid import fit_scene
    project,truth,_=rendered_fixture(tmp_path);candidate=Candidate(project,'fit')
    images=project.evidence['images'];folder=candidate.root/'.cache/inference';folder.mkdir(parents=True)
    depth=[];ks=[];poses=[];segments=[];anchors={}
    with Renderer(truth,project.root,folder/'render')as renderer:
        for image in images:
            cam=next(c for c in truth['cameras']if c['id']==image['camera']);k=np.asarray(cam['K']['value'])
            pose=np.linalg.inv(world_pose(truth,cam));relative=pose.copy();relative[:3,3]*=2
            depth.append(renderer.depth(cam['id'])*2);ks.append(k);poses.append(relative)
            mask=folder/(image['id']+'.png');Image.fromarray(renderer.mask(cam['id'],'block').astype('uint8')*255).save(mask)
            segments.append({'image_id':image['id'],'object_id':'block','source_image_sha256':image['sha256'],'status':'PROPOSED',
                             'masks':[{'path':str(mask),'sha256':sha(mask)}]})
            world=np.array([[-.1,-.1,0],[.1,-.1,0],[.1,.1,0],[-.1,.1,0]])
            optical=world@pose[:3,:3].T+pose[:3,3];uv=optical@k.T;uv=uv[:,:2]/uv[:,2:]
            anchors[image['id']]={'source':'measured','evidence':['synthetic known board'],
                                 'world_points_m':world.tolist(),'uv_px':uv.tolist()}
    register_views(candidate,anchors,scene_state='layout')
    path=folder/'depth.npz';np.savez_compressed(path,depth=depth,intrinsics=ks,extrinsics=poses,
        original_to_processed=np.repeat(np.eye(3)[None],len(images),axis=0),conf=np.ones_like(depth),distortion=np.zeros((len(images),5)))
    report={'backend':'mast3r_colmap','images':images,'scene_state_id':'layout','segments':segments,
            'depth_batches':[{'path':str(path),'image_ids':[r['id']for r in images],
                             'metadata':{'sha256':sha(path),'common_frame':'synthetic','units':'sfm_relative'}}]}
    config={'objects':{'block':{'prompt':'block'}}};write(candidate.root/'reconstruction-config.yaml',config)
    cloud=build_point_clouds(candidate,report)
    assert cloud['status']=='METRIC_ESTIMATED'and len(cloud['clouds'])==2
    groups,_=modeling_groups(candidate,config,report)
    assert groups['block']['geometry_observations'][0]['units']=='m'
    _,fitted=fit_scene(project,candidate.scene,folder/'fit',{'objects':[],'cameras':[],'max_evaluations':2})
    assert fitted['training_view_count']==2 and fitted['physics_steps']==0
    assert not fitted['physical_verified']


def test_disconnected_views_preserve_usable_components_and_isolated_unknowns():
    from real2sim_builder.sfm import view_components
    assert view_components(['side1','wrist1','side2','wrist2','isolated'],
        {('side1','side2'),('wrist2','wrist1')})==[['side1','side2'],['wrist1','wrist2'],['isolated']]
    assert view_components([],set())==[]


def test_component_pair_indices_are_local_without_mutating_forward_cache_names():
    from real2sim_builder.sfm import component_pairs
    pairs=[({'idx':4,'instance':'wrist_a'},{'idx':6,'instance':'wrist_b'}),
           ({'idx':0,'instance':'side'},{'idx':4,'instance':'wrist_a'})]
    local=component_pairs(['wrist_a','wrist_b'],pairs)
    assert [[v['idx']for v in pair]for pair in local]==[[0,1]]
    assert [[v['instance']for v in pair]for pair in local]==[['wrist_a','wrist_b']]
    assert pairs[0][0]['idx']==4 and pairs[0][1]['idx']==6


def test_empty_distorted_depth_pixels_remain_empty_not_opencv_failure():
    from real2sim_builder.cameras import optical_rays,project_pixels
    camera={'K':{'value':np.eye(3).tolist()},'distortion':{'value':[.1,0.,0.,0.,0.]}}
    assert optical_rays(camera,np.empty((0,2))).shape==(0,3)
    assert project_pixels(camera,np.empty((0,3))).shape==(0,2)


def test_initial_sfm_excludes_model_references_and_sensor_capture(tmp_path,monkeypatch):
    from real2sim_builder.sfm import run_geometry
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder import inference
    p=Project.create(tmp_path,'roles');c=Candidate.create(p,'existing')
    rows=[{'id':'model','role':'model_reference','split':'train'},
          {'id':'sensor','role':'capture','capture_manifest':'input/captures/capture_manifest.yaml','split':'train'}]
    def forbidden(*a,**k):raise AssertionError('Excluded images reached GPU runtime')
    monkeypatch.setattr(inference,'_runtime',forbidden)
    batches,report=run_geometry(c,{'objects':{}},rows,{},[],c.root)
    assert batches==[]and report['status']=='UNRESOLVED'
    assert any('initial' in n for n in report['needs'])


def test_unknown_physical_lenses_do_not_share_intrinsics_by_placeholder_or_hash():
    from real2sim_builder.sfm import lens_group
    first={'id':'scene_img1','physical_camera_id':None,'resolution':[640,480]}
    second={**first,'id':'scene_img2'}
    assert lens_group(first)!=lens_group(second)
    assert lens_group({**first,'physical_camera_id':'phone_lens_1'})==lens_group({**second,'physical_camera_id':'phone_lens_1'})
