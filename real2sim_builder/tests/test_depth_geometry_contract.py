"""DA3 array contracts and stored legacy component metadata; no SfM executor."""
import numpy as np
import pytest

def test_stored_common_frame_is_not_reestimated_and_disjoint_components_are_not_merged(tmp_path):
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


def test_da3_cloud_contract_consumes_metric_registration_without_fabricating_scale(tmp_path):
    from PIL import Image
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.scene import empty,value
    from real2sim_builder.observations import register_image,register_views
    from real2sim_builder.inference import build_point_clouds
    from real2sim_builder.files import sha
    project=Project.create(tmp_path,'DA3 metric');scene=empty('DA3 metric')
    scene['cameras']=[{'id':'phone','frame':'world','pose':value(None),'resolution':[80,60],
        'K':value([[60,0,40],[0,60,30],[0,0,1]],'calibrated',['synthetic lens']),
        'distortion':value([0.]*5,'calibrated',['synthetic lens'])}]
    project.save_scene(scene);source=tmp_path/'photo.png';Image.new('RGB',(80,60)).save(source)
    image=register_image(project,source,camera='phone',camera_type='external',scene_state='layout')
    candidate=Candidate.create(project,'metric');folder=candidate.root/'.cache/inference';folder.mkdir(parents=True)
    mask=folder/'mask.png';Image.new('L',(80,60),255).save(mask)
    path=folder/'depth.npz';np.savez(path,depth=np.full((1,30,40),2.),intrinsics=np.array([[[30,0,20],[0,30,15],[0,0,1]]]),
        extrinsics=np.eye(4)[None],original_to_processed=np.diag([.5,.5,1.])[None],distortion=np.zeros((1,5)),conf=np.ones((1,30,40)))
    report={'scene_state_id':'layout','backend':'da3_nested','depth_batches':[{'path':str(path),'image_ids':[image['id']],
       'metadata':{'sha256':sha(path),'backend':'da3_nested','common_frame':'one','units':'geometry_relative'}}],
       'segments':[{'image_id':image['id'],'object_id':'block','source_image_sha256':image['sha256'],'masks':[{'path':str(mask),'sha256':sha(mask)}]}]}
    assert build_point_clouds(candidate,report)['status']=='NEEDS_MORE_DATA'
    register_views(candidate,{image['id']:{'source':'measured','evidence':['synthetic board'],
       'world_points_m':[[-.3,-.2,1],[.3,-.2,1],[.3,.2,1],[-.3,.2,1]],'uv_px':[[22,18],[58,18],[58,42],[22,42]]}},scene_state='layout')
    result=build_point_clouds(candidate,report)
    assert result['status']=='METRIC_ESTIMATED'and result['clouds'][0]['point_filter']['units']=='geometry_relative'
    with np.load(project.root/result['clouds'][0]['path'])as d:np.testing.assert_allclose(d['points_world_m'][:,2],1,atol=1e-6)


def test_geometry_optional_arrays_cannot_misrepresent_pixel_or_lens_coordinates():
    from real2sim_builder.inference import validate_depth_output
    arrays={'depth':np.ones((1,4,6)),'intrinsics':np.eye(3)[None],'extrinsics':np.eye(4)[None]}
    for name,value in [('distortion',np.zeros((1,3))),('distortion',np.full((1,5),np.nan)),
                       ('original_to_processed',np.zeros((1,3,3))),('conf',np.full((1,4,6),-1.))]:
        with pytest.raises(ValueError):validate_depth_output({**arrays,name:value},1)


@pytest.mark.parametrize('kind',['da3','sam'])
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


def test_da3_depth_contract_reaches_existing_metric_fusion_assets_and_native_fitting(tmp_path):
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
    report={'backend':'da3_nested','images':images,'scene_state_id':'layout','segments':segments,
            'depth_batches':[{'path':str(path),'image_ids':[r['id']for r in images],
                             'metadata':{'sha256':sha(path),'common_frame':'synthetic','units':'geometry_relative'}}]}
    config={'objects':{'block':{'prompt':'block'}}};write(candidate.root/'reconstruction-config.yaml',config)
    cloud=build_point_clouds(candidate,report)
    assert cloud['status']=='METRIC_ESTIMATED'and len(cloud['clouds'])==2
    groups,_=modeling_groups(candidate,config,report)
    assert groups['block']['geometry_observations'][0]['units']=='m'
    _,fitted=fit_scene(project,candidate.scene,folder/'fit',{'objects':[],'cameras':[],'max_evaluations':2})
    assert fitted['training_view_count']==2 and fitted['physics_steps']==0
    assert not fitted['physical_verified']


def test_empty_distorted_depth_pixels_remain_empty_not_opencv_failure():
    from real2sim_builder.cameras import optical_rays,project_pixels
    camera={'K':{'value':np.eye(3).tolist()},'distortion':{'value':[.1,0.,0.,0.,0.]}}
    assert optical_rays(camera,np.empty((0,2))).shape==(0,3)
    assert project_pixels(camera,np.empty((0,3))).shape==(0,2)
