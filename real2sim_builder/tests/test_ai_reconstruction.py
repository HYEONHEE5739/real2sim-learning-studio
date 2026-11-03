import numpy as np
import pytest


def test_mask_depth_resize_and_crop_are_explicit_in_pixel_coordinates():
    from real2sim_builder.inference import object_points
    depth=np.full((4,6),2.);mask=np.zeros((8,12),np.uint8);mask[:,6:]=1
    k=np.array([[3.,0,3],[0,3,2],[0,0,1]])
    transform=np.diag([.5,.5,1.])
    points,report=object_points(depth,mask,k,transform,erode_px=0)
    assert len(points)==12 and report['frame']=='camera_optical'and report['units']=='DA3_relative'
    assert np.min(points[:,0])>=0 and np.all(points[:,2]==2)
    with pytest.raises(ValueError,match='pixel transform'):
        object_points(depth,mask,k,None)


def test_unknown_depth_scale_cannot_become_world_metres_by_default():
    from real2sim_builder.inference import metric_points
    points=np.array([[0.,0,2.],[.1,0,2.]])
    assert metric_points(points,None,None)['status']=='NEEDS_MORE_DATA'
    result=metric_points(points,{'scale':.5,'source':'measured','evidence':['depth anchor']},np.eye(4))
    np.testing.assert_allclose(result['points_world_m'],points*.5)
    with pytest.raises(ValueError):metric_points(points,{'scale':1.,'source':'estimated','evidence':[]},np.eye(4))


def test_invalid_depth_and_low_confidence_are_not_observed_geometry():
    from real2sim_builder.inference import object_points
    depth=np.array([[1.,np.nan],[0.,2.]])
    confidence=np.array([[.9,.9],[.9,.1]])
    points,report=object_points(depth,np.ones((2,2)),np.eye(3),np.eye(3),confidence=confidence,min_confidence=.5,erode_px=0)
    assert len(points)==1 and report['points']==1
    np.testing.assert_allclose(points,[[0.,0.,1.]])


def test_bad_array_shapes_are_rejected_before_npz_is_used():
    from real2sim_builder.inference import validate_depth_output
    arrays={'depth':np.ones((2,4,6)),'intrinsics':np.repeat(np.eye(3)[None],2,axis=0),'extrinsics':np.zeros((2,3,4))}
    with pytest.raises(ValueError):validate_depth_output(arrays,2)
    arrays['extrinsics'][:,:3,:3]=np.eye(3)
    validate_depth_output(arrays,2)
    arrays['intrinsics']=np.eye(3)
    with pytest.raises(ValueError):validate_depth_output(arrays,2)


def test_cloud_pipeline_binds_original_mask_metric_anchors_and_candidate_files(tmp_path):
    import copy
    from PIL import Image
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.scene import empty,value
    from real2sim_builder.observations import register_image,register_views
    from real2sim_builder.inference import build_point_clouds
    from real2sim_builder.files import sha
    p=Project.create(tmp_path,'cloud');scene=empty('cloud')
    scene['cameras']=[{'id':'phone','frame':'world','pose':value(None),'resolution':[80,60],
        'K':value([[60,0,40],[0,60,30],[0,0,1]],'calibrated',['lens']),
        'distortion':value([0.]*5,'calibrated',['lens'])}]
    p.save_scene(scene);source=tmp_path/'photo.png';Image.new('RGB',(80,60)).save(source)
    row=register_image(p,source,camera='phone',camera_type='external',scene_state='layout')
    before=copy.deepcopy(p.evidence);current=sha(p.root/'working/current_scene.yaml');c=Candidate.create(p,'metric')
    world=[[-.3,-.2,1],[.3,-.2,1],[.3,.2,1],[-.3,.2,1]]
    uv=[[22,18],[58,18],[58,42],[22,42]]
    register_views(c,{row['id']:{'source':'measured','evidence':['board corners'],'world_points_m':world,'uv_px':uv}},scene_state='layout')
    folder=c.root/'inference';folder.mkdir();mask=folder/'mask.png';Image.new('L',(80,60),255).save(mask)
    depth=folder/'depth.npz';np.savez(depth,depth=np.full((1,30,40),2.),intrinsics=np.array([[[30,0,20],[0,30,15],[0,0,1]]]),
        extrinsics=np.eye(4)[None],original_to_processed=np.diag([.5,.5,1.])[None])
    report={'scene_state_id':'layout','depth_batches':[{'path':str(depth),'image_ids':[row['id']],'metadata':{'sha256':sha(depth)}}],
        'segments':[{'image_id':row['id'],'object_id':'block','source_image_sha256':row['sha256'],
                     'masks':[{'path':str(mask),'sha256':sha(mask)}]}]}
    result=build_point_clouds(c,report)
    assert result['status']=='METRIC_ESTIMATED'and len(result['clouds'])==1
    cloud=result['clouds'][0]
    with np.load(p.root/cloud['path'])as arrays:np.testing.assert_allclose(arrays['points_world_m'][:,2],1.,atol=1e-6)
    assert cloud['provenance']=='derived'and not cloud['identity_verified']
    assert p.evidence==before and sha(p.root/'working/current_scene.yaml')==current
    assert cloud['path']in p.signature(c.scene)['files']


def test_model_inputs_apply_exif_once_without_changing_original_photo(tmp_path):
    from PIL import Image
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.observations import register_image
    from real2sim_builder.inference import prepare_rgb
    from real2sim_builder.files import sha
    p=Project.create(tmp_path,'oriented');image=tmp_path/'portrait.jpg'
    exif=Image.Exif();exif[274]=6;Image.new('RGB',(12,8),'red').save(image,exif=exif)
    row=register_image(p,image,camera='phone',camera_type='external',scene_state='layout')
    digest=sha(image);c=Candidate.create(p,'normalized');prepared=prepare_rgb(c,[row])[row['id']]
    with Image.open(prepared['path'])as decoded:
        assert list(decoded.size)==row['resolution']==[8,12] and decoded.getexif().get(274,1)==1
    assert prepared['source_sha256']==digest and sha(image)==digest


def test_cancel_releases_only_the_owned_model_process_group(tmp_path):
    import os,sys,subprocess,time
    from real2sim_builder.inference import _run_worker
    from real2sim_builder.project import Project
    p=Project.create(tmp_path,'cancel');pid=tmp_path/'child.pid';wrapper=tmp_path/'existing_python'
    wrapper.write_text('#!'+sys.executable+'\nimport subprocess,sys,time\nfrom pathlib import Path\n'
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\n'
        'Path('+repr(str(pid))+').write_text(str(child.pid))\ntime.sleep(30)\n')
    wrapper.chmod(0o700)
    unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
    started=time.monotonic()
    def cancel_when_started():
        if pid.exists():raise InterruptedError('requested cancellation')
    p.checkpoint=cancel_when_started
    try:
        with pytest.raises(InterruptedError):_run_worker(p,wrapper,'sam',{},tmp_path/'job',5)
        assert time.monotonic()-started<5 and unrelated.poll()is None
        child=int(pid.read_text());state=__import__('pathlib').Path('/proc')/str(child)/'stat'
        assert not state.exists()or state.read_text().split()[2]=='Z'
    finally:unrelated.terminate();unrelated.wait(timeout=3)
