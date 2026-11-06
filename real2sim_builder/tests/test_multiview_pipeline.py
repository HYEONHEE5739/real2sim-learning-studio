"""Multiview identity and reconstruction contracts; data are synthetic."""
import copy
from pathlib import Path
import numpy as np
from PIL import Image
from real2sim_builder.files import sha,write,read
from real2sim_builder.project import Project,Candidate


def test_isaac_parent_leaves_control_consumption_to_worker(tmp_path,monkeypatch):
    import subprocess
    from real2sim_builder.isaac_render import run_job
    project=Project.create(tmp_path/'scenes','single control owner')
    monkeypatch.setattr(project,'checkpoint',lambda:(_ for _ in()).throw(AssertionError('Parent consumed worker control')))
    class Child:
        returncode=0
        def __init__(self,args,**kwargs):
            self.folder=Path(args[-1]);self.polls=0
            write(self.folder/'report.json',{'images':[]})
        def poll(self):
            self.polls+=1
            return None if self.polls==1 else 0
    monkeypatch.setattr(subprocess,'Popen',Child)
    assert run_job(project,{},tmp_path/'jobs',{},'compare')=={'images':[]}


def test_isaac_fast_exit_cannot_hide_worker_error(tmp_path,monkeypatch):
    import subprocess,pytest
    from real2sim_builder.isaac_render import run_job
    project=Project.create(tmp_path/'scenes','failed worker')
    class Child:
        returncode=0
        def __init__(self,args,**kwargs):write(Path(args[-1])/'error.json',{'error':'render failed','stopped':False})
        def poll(self):return 0
    monkeypatch.setattr(subprocess,'Popen',Child)
    with pytest.raises(RuntimeError,match='render failed'):
        run_job(project,{},tmp_path/'jobs',{},'compare')


def test_isaac_stuck_worker_stop_is_bounded_and_retains_checkpoint(tmp_path,monkeypatch):
    import subprocess,pytest,time,os,signal
    from real2sim_builder.isaac_render import run_job
    project=Project.create(tmp_path/'scenes','stuck worker');clock=iter(range(100));signals=[]
    monkeypatch.setattr(time,'monotonic',lambda:next(clock));monkeypatch.setattr(time,'sleep',lambda _:None)
    class Child:
        pid=123456;returncode=None
        def __init__(self,args,**kwargs):
            write(Path(args[-1])/'best-scene.yaml',{});project.control('stop')
        def poll(self):return None
        def wait(self,timeout=None):self.returncode=-15;return -15
    monkeypatch.setattr(subprocess,'Popen',Child);monkeypatch.setattr(os,'killpg',lambda pid,sig:signals.append((pid,sig)))
    with pytest.raises(InterruptedError)as caught:run_job(project,{},tmp_path/'jobs',{},'fit')
    assert caught.value.best_scene=={}
    assert signals==[(123456,signal.SIGTERM)]


def observations_fixture(tmp_path):
    images=[];segments=[];depth=[];extrinsics=[]
    for index,centers in enumerate(((30,70),(20,60),(25,65))):
        key='v'+str(index);images.append({'id':key,'camera':'phone','resolution':[100,80],'split':'train','path':key+'.png'})
        Image.new('RGB',(100,80),(index,0,0)).save(tmp_path/(key+'.png'))
        masks=[]
        for n,x in enumerate(centers):
            if index==2 and n==0:continue  # Left object occluded in one view.
            mask=np.zeros((80,100),np.uint8);mask[30:50,x-5:x+5]=255
            path=tmp_path/(key+'_'+str(n)+'.png');Image.fromarray(mask).save(path);masks.append({'path':str(path),'sha256':sha(path)})
        if index==1:masks.reverse()  # SAM ordering is not physical identity.
        segments.extend({'image_id':key,'object_id':name,'masks':copy.deepcopy(masks),'status':'AMBIGUOUS'}for name in('left','right'))
        depth.append(np.ones((80,100)))
        ext=np.eye(4);ext[0,3]=-(0,.1,.05)[index];extrinsics.append(ext)
    file=tmp_path/'depth.npz';np.savez(file,depth=depth,conf=np.ones_like(depth),extrinsics=extrinsics,
        intrinsics=np.repeat(np.array([[[100.,0,50],[0,100,40],[0,0,1]]]),3,axis=0),original_to_processed=np.repeat(np.eye(3)[None],3,axis=0))
    return {'images':images,'segments':segments,'depth_batches':[{'path':str(file),'image_ids':[i['id']for i in images],'metadata':{'sha256':sha(file)}}]}


def test_cross_view_depth_association_survives_missing_masks_and_reordered_candidates(tmp_path):
    from real2sim_builder.inference import associate_instances
    report=observations_fixture(tmp_path)
    objects={'left':{'prompt':'paper cup','asset_group':'cups','images':{'v0':{'box_xyxy':[20,20,40,60]}}},
             'right':{'prompt':'paper cup','asset_group':'cups','images':{'v0':{'box_xyxy':[60,20,80,60]}}}}
    result=associate_instances(report,objects)
    selected={(r['image_id'],r['object_id']):r['association']for r in result['segments']}
    assert selected['v1','left']['mask_index']==1 and selected['v1','right']['mask_index']==0
    assert selected['v2','left']['status']=='NOT_FOUND'
    assert selected['v2','right']['status']=='ASSIGNED_ESTIMATED'
    assert selected['v1','left']['basis']=='cross_view_geometry'
    assert report['segments'][0].get('association')is None


def test_partial_mask_count_does_not_block_explicit_asset_identity(tmp_path):
    from real2sim_builder.authoring import modeling_groups,group_asset
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'scenes','mask independence');c=Candidate.create(p,'draft')
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cups')
    report=observations_fixture(c.root)
    for i in report['images']:
        i['sha256']=sha(c.root/i['path']);i['path']=(c.root/i['path']).relative_to(p.root).as_posix()
    config={'objects':{n:{'prompt':'cup','asset_group':'cups','asset_manifest':asset['manifest']}for n in('left','right')}}
    groups,_=modeling_groups(c,config,report)
    assert group_asset(c,groups['cups'],{})[0]['version']==asset['version']
    assert not groups['cups']['blocked']


def test_metric_plane_initialization_uses_partial_measurements_and_shared_phone_k(tmp_path):
    from real2sim_builder.observations import register_image,predict_views,register_views,registered_images
    from real2sim_builder.scene import empty
    from real2sim_builder.capture import observation_scene
    p=Project.create(tmp_path/'scenes','metric board');p.save_scene(empty('metric board'));images=[];segments=[]
    for index in range(2):
        rgb=tmp_path/f'board{index}.png';Image.new('RGB',(100,80),(index,0,0)).save(rgb)
        row=register_image(p,rgb,camera='phone',camera_type='external',scene_state='layout');images.append(row)
        mask=np.zeros((80,100),np.uint8);mask[20:60,20:80]=255;path=tmp_path/f'mask{index}.png';Image.fromarray(mask).save(path)
        segments.append({'image_id':row['id'],'object_id':'board','masks':[{'path':str(path),'sha256':sha(path)}],'association':{'status':'ASSIGNED_ESTIMATED','mask_path':str(path),'mask_sha256':sha(path)}})
    c=Candidate.create(p,'auto');depth=c.root/'depth.npz';k=np.array([[100.,0,50],[0,100.,40],[0,0,1.]])
    np.savez(depth,depth=np.full((2,80,100),2.),intrinsics=np.repeat(k[None],2,axis=0),extrinsics=np.repeat(np.eye(4)[None],2,axis=0),original_to_processed=np.repeat(np.eye(3)[None],2,axis=0))
    report={'images':images,'segments':segments,'scene_state_id':'layout','depth_batches':[{'path':str(depth),'image_ids':[i['id']for i in images],'metadata':{'sha256':sha(depth)}}]}
    result=predict_views(c,report,{'measurements':[{'id':'board','kind':'box','role':'support_surface','dimensions_m':[.6,.4,.02],'evidence':['ruler']} ]})
    assert result['status']=='PREDICTED',result
    assert abs(result['metric_alignment']['scale']-.5)<.04
    register_views(c,scene_state='layout')
    assert len(registered_images(p,'layout',scene=c.scene)[0])==2
    assert len(c.scene['cameras'])==1
    posed=[observation_scene(c.scene,i,p.root,complete=False)for i in images]
    np.testing.assert_array_equal(posed[0]['cameras'][0]['K']['value'],posed[1]['cameras'][0]['K']['value'])
    assert p.scene['cameras']==[]


def test_native_renderer_updates_camera_intrinsics_and_returns_optical_depth(tmp_path):
    from real2sim_builder.rendering import Renderer
    from test_builder_export import legacy_scene
    scene=legacy_scene();trial=copy.deepcopy(scene)
    trial['cameras'][0]['pose']['value'][0][3]+=.02
    trial['cameras'][0]['K']['value'][0][0]*=1.05
    trial['cameras'][0]['K']['value'][0][2]+=3
    with Renderer(scene,tmp_path,tmp_path/'initial')as r:
        r.update_scene(trial);rgb=r.rgb('side');mask=r.mask('side','block');depth=r.depth('side')
        assert depth.shape==mask.shape and np.isfinite(depth[mask]).all()and np.min(depth[mask])>0
    with Renderer(trial,tmp_path,tmp_path/'fresh')as r:
        np.testing.assert_array_equal(rgb,r.rgb('side'))
        np.testing.assert_allclose(depth,r.depth('side'),atol=1e-5)


def test_native_renderer_updates_appearance_and_lighting_like_fresh_export(tmp_path):
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.scene import value
    from test_builder_export import legacy_scene
    scene=legacy_scene();scene['objects'][1]['material']={'roughness':value(.2),'metallic':value(.1)}
    trial=copy.deepcopy(scene);trial['objects'][1]['color']=value([.1,.6,.2])
    trial['objects'][1]['material']={'roughness':value(.8),'metallic':value(.6)}
    trial['lights']['ambient']=value([.12,.2,.17])
    with Renderer(scene,tmp_path,tmp_path/'initial')as renderer:
        before=renderer.rgb('side');renderer.update_scene(trial);after=renderer.rgb('side')
        assert np.mean(abs(after.astype(float)-before))>1
    with Renderer(trial,tmp_path,tmp_path/'fresh')as renderer:
        np.testing.assert_array_equal(after,renderer.rgb('side'))


def test_joint_parameters_fit_estimated_appearance_but_lock_measured_and_shared_assets():
    from real2sim_builder.calibration.joint import parameter_blocks,apply_parameters
    from real2sim_builder.scene import value
    from test_builder_export import legacy_scene
    scene=legacy_scene();scene['objects'][1]['color']=value([.3,.2,.1],'estimated')
    scene['objects'][1]['material']={'roughness':value(.5,'estimated'),'metallic':value(.2,'measured')}
    rows=[{'camera':'side','image_id':'view','object_id':'block','split':'train'}]
    blocks,radius=parameter_blocks(scene,rows,{'objects':[],'cameras':[],'optimize_appearance':True,'optimize_lighting':True})
    assert {b[0]for b in blocks}=={'color','roughness','ambient'}
    trial,_=apply_parameters(scene,blocks,radius*.5)
    assert trial['objects'][1]['color']!=scene['objects'][1]['color']
    assert trial['objects'][1]['material']['metallic']==scene['objects'][1]['material']['metallic']
    assert trial['objects'][0]==scene['objects'][0]
    scene['objects'][1]['object_asset']={'asset_id':'shared'}
    blocks,_=parameter_blocks(scene,rows,{'objects':[],'cameras':[],'optimize_appearance':True})
    assert not blocks  # Immutable library material needs an explicit new version.


def test_isaac_fitting_and_comparison_dispatch_owned_native_job(tmp_path,monkeypatch):
    from real2sim_builder import isaac_render
    from real2sim_builder.calibration.hybrid import fit_scene,alignment_metrics
    calls=[]
    def job(project,scene,folder,options,operation):
        calls.append(operation)
        return (scene,{'engine':'isaac'})if operation=='fit'else{'engine':'isaac','images':[]}
    monkeypatch.setattr(isaac_render,'run_job',job)
    assert fit_scene(None,{},tmp_path,{'engine':'isaac'})[1]['engine']=='isaac'
    assert alignment_metrics(None,{},tmp_path,{'engine':'isaac'})['engine']=='isaac'
    assert calls==['fit','compare']


def rendered_fixture(tmp_path):
    from test_builder_export import legacy_scene
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.observations import register_image,register_views
    from real2sim_builder.calibration.hybrid import surface_points
    from real2sim_builder.scene import value,world_pose
    p=Project.create(tmp_path/'scenes','closed loop');truth=legacy_scene()
    second=copy.deepcopy(truth['cameras'][0]);second['id']='other';second['pose']['value'][1][3]*=-1
    # Look at the same workpiece from the other side.
    eye=np.array([.6,-.4,.5]);forward=-eye/np.linalg.norm(eye);right=np.cross(forward,[0,0,1]);right/=np.linalg.norm(right)
    pose=np.eye(4);pose[:3,:3]=np.column_stack([right,np.cross(forward,right),forward]);pose[:3,3]=eye
    second['pose']=value(pose.tolist(),'calibrated');truth['cameras'].append(second);p.save_scene(truth)
    observations=[]
    with Renderer(truth,p.root,tmp_path/'truth')as renderer:
        for camera in ('side','other'):
            file=tmp_path/(camera+'.png');Image.fromarray(renderer.rgb(camera)).save(file)
            image=register_image(p,file,camera=camera,camera_type='side',scene_state='layout')
            mask=tmp_path/(camera+'_mask.png');Image.fromarray(renderer.mask(camera,'block').astype('uint8')*255).save(mask)
            points=surface_points(truth['objects'][1],truth,p.root,500)+[0,0,.03]
            cloud=p.root/(camera+'.npz');cam=world_pose(truth,next(c for c in truth['cameras']if c['id']==camera))
            optical=(points-cam[:3,3])@cam[:3,:3];uv=optical@np.array(truth['cameras'][0]['K']['value']).T;uv=uv[:,:2]/uv[:,2:3]
            np.savez(cloud,points_world_m=points,points_camera_relative=optical,uv_original=uv,depth_relative=optical[:,2])
            observations.append({'image_id':image['id'],'object_id':'block','split':'train','group_id':image['id'],
                 'path':cloud.relative_to(p.root).as_posix(),'sha256':sha(cloud),'mask':str(mask),'mask_sha256':sha(mask),
                 'units':'m','frame':'world','mask_kind':'silhouette','camera':camera,'depth_scale':1.})
    # Masks are owned input files; no absolute paths enter the Scene.
    for row in observations:
        source=tmp_path/Path(row['mask']).name;target=p.root/'input'/source.name;target.write_bytes(source.read_bytes());row['mask']=target.relative_to(p.root).as_posix()
    c=Candidate.create(p,'fit');register_views(c,scene_state='layout');scene=c.scene
    scene['reconstruction_observations']={'scene_state_id':'layout','clouds':observations}
    scene['objects'][1]['pose']['provenance']='estimated';scene['objects'][1]['pose']['value'][0][3]+=.018
    return p,truth,scene


def test_simulator_closed_loop_joint_loss_decreases_across_views_and_restores_best(tmp_path):
    from pathlib import Path
    from real2sim_builder.calibration.hybrid import fit_scene
    p,truth,scene=rendered_fixture(tmp_path);before=copy.deepcopy(scene)
    result,report=fit_scene(p,scene,tmp_path/'fit',{'objects':['block'],'cameras':[],'supports':{'block':'table'},'max_iterations':3,'max_evaluations':90})
    assert report['status']=='OPTIMIZED_UNVERIFIED',report
    assert report['after_loss']<report['before_loss']*.7,report
    assert all(a['loss']<=b['loss']+.05 for a,b in zip(report['after'],report['before']))
    assert abs(result['objects'][1]['pose']['value'][0][3])<.01
    assert report['physics_steps']==0 and not report['physical_verified']
    assert scene==before and result['objects'][0]==truth['objects'][0]
    assert report['training_view_count']==2 and report['evaluations']>1
    assert (tmp_path/'fit/best-scene.yaml').is_file()
    assert report['stop_reason']in('converged','no_improvement','max_iterations')


def test_multiview_color_fit_reduces_native_rgb_loss_without_moving_geometry(tmp_path):
    from real2sim_builder.calibration.hybrid import fit_scene
    from real2sim_builder.scene import value
    p,truth,scene=rendered_fixture(tmp_path)
    scene['objects'][1]['pose']=copy.deepcopy(truth['objects'][1]['pose'])
    scene['objects'][1]['color']=value([.25,.35,.2],'estimated')
    result,report=fit_scene(p,scene,p.root/'scratch/color',{'cameras':[],'objects':[],
        'optimize_appearance':True,'max_iterations':2,'max_evaluations':60})
    assert report['after_loss']<report['before_loss']
    assert np.mean([r['components']['rgb']for r in report['after']])<np.mean([r['components']['rgb']for r in report['before']])*.4
    assert all(a['components']['rgb']<b['components']['rgb']for a,b in zip(report['after'],report['before']))
    assert result['objects'][1]['pose']==scene['objects'][1]['pose']
    assert result['objects'][1]['dimensions']==scene['objects'][1]['dimensions']


def test_joint_camera_object_fit_preserves_other_view_and_measured_fields(tmp_path,monkeypatch):
    import scipy.optimize
    from real2sim_builder.calibration.hybrid import fit_scene
    from real2sim_builder.scene import camera_calibration_signature
    p,truth,scene=rendered_fixture(tmp_path)
    camera=scene['cameras'][0];camera['pose']['provenance']='estimated';camera['pose']['value'][1][3]+=.018
    for binding in scene['view_registrations'].values():
        if binding['camera']=='side':binding.update(status='REGISTERED_ESTIMATED',camera_signature=camera_calibration_signature(scene,camera))
    minimize=scipy.optimize.minimize;checkpoints=[]
    def inspect_closed_iteration(*args,**kwargs):
        path=p.root/'scratch/joint/best-scene.yaml'
        if path.exists():
            saved=read(path)
            for binding in saved['view_registrations'].values():
                cam=next(c for c in saved['cameras']if c['id']==binding['camera'])
                assert binding['camera_signature']==camera_calibration_signature(saved,cam)
            checkpoints.append(saved)
        return minimize(*args,**kwargs)
    monkeypatch.setattr(scipy.optimize,'minimize',inspect_closed_iteration)
    result,report=fit_scene(p,scene,p.root/'scratch/joint',{'cameras':['side'],'objects':['block'],'supports':{'block':'table'},'max_iterations':3,'max_evaluations':160})
    assert report['after_loss']<report['before_loss']*.6,report
    assert all(a['loss']<=b['loss']+.05 for a,b in zip(report['after'],report['before']))
    assert result['cameras'][1]==truth['cameras'][1]
    assert np.linalg.norm(np.array(result['cameras'][0]['pose']['value'])[:3,3]-np.array(truth['cameras'][0]['pose']['value'])[:3,3])<.018
    assert result['objects'][1]['dimensions']==truth['objects'][1]['dimensions']
    assert len(checkpoints)>=2


def test_budget_and_cancel_do_not_certify_success_or_destroy_best_candidate(tmp_path,monkeypatch):
    import pytest
    from real2sim_builder.calibration.hybrid import fit_scene
    p,truth,scene=rendered_fixture(tmp_path)
    result,report=fit_scene(p,scene,p.root/'scratch/short',{'objects':['block'],'cameras':[],'max_iterations':1,'max_evaluations':1})
    assert report['status']=='BUDGET_EXHAUSTED'and not report['converged']
    original=copy.deepcopy(scene);calls=[]
    def cancel():
        calls.append(1)
        if len(calls)>9:raise InterruptedError('synthetic user Stop')
    monkeypatch.setattr(p,'checkpoint',cancel)
    with pytest.raises(InterruptedError):fit_scene(p,scene,p.root/'scratch/stopped',{'objects':['block'],'cameras':[]})
    assert (p.root/'scratch/stopped/best-scene.yaml').is_file()and scene==original
    assert read(p.root/'scratch/stopped/report.json')['status']=='STOPPED'


def test_shared_lens_intrinsics_follow_explicit_resize_crop_without_changing_base_camera(tmp_path):
    from real2sim_builder.cameras import camera_pixels
    from real2sim_builder.capture import observation_scene
    from real2sim_builder.scene import value
    from test_builder_export import legacy_scene
    scene=legacy_scene();camera=scene['cameras'][0];before=copy.deepcopy(camera)
    image={'id':'half','camera':'side','camera_type':'external','resolution':[80,60],'sha256':'x','scene_state_id':'layout'}
    matrix,_=camera_pixels(camera,image)
    np.testing.assert_allclose(matrix,np.diag([.5,.5,1]))
    scene['view_registrations']={'half':{'source_image_sha256':'x','scene_state_id':'layout','status':'REGISTERED_ESTIMATED',
        'T_world_camera':camera['pose']['value'],'calibration_evidence':['same lens resize'],'pixel_from_camera':matrix.tolist()}}
    posed=observation_scene(scene,image,tmp_path,complete=False)
    np.testing.assert_allclose(posed['cameras'][0]['K']['value'],matrix@np.asarray(before['K']['value']))
    assert posed['cameras'][0]['resolution']==[80,60]and scene['cameras'][0]==before
    crop={**image,'resolution':[70,50],'pixel_from_camera':[[.5,0,-5],[0,.5,-5],[0,0,1]]}
    np.testing.assert_allclose(camera_pixels(camera,crop)[0],crop['pixel_from_camera'])
    import pytest
    with pytest.raises(ValueError,match='crop'):camera_pixels(camera,{**image,'resolution':[70,50]})


def test_exif_rotation_shares_one_physical_lens_in_original_pixel_coordinates(tmp_path):
    from real2sim_builder.cameras import camera_pixels
    from test_builder_export import legacy_scene
    camera=legacy_scene()['cameras'][0];k=np.asarray(camera['K']['value']);k[0,0]=150;k[1,1]=170;k[0,2]=73;k[1,2]=51
    camera['K']['value']=k.tolist()
    image={'resolution':[120,160],'exif_orientation':6}
    affine,optical=camera_pixels(camera,image)
    upright=affine@k@optical.T
    np.testing.assert_allclose(upright,[[170,0,119-51],[0,150,73],[0,0,1]])
    points=np.array([[.1,.05,1],[.2,-.1,2]])
    before=points@k.T;before/=before[:,2:3]
    rotated=(points@optical.T)@upright.T;rotated/=rotated[:,2:3]
    np.testing.assert_allclose(rotated,before@affine.T)


def test_stop_during_solver_retains_latest_accepted_scene_not_only_iteration_start(tmp_path,monkeypatch):
    import pytest
    import scipy.optimize
    from real2sim_builder.calibration.hybrid import fit_scene,cloud_inputs
    p,truth,scene=rendered_fixture(tmp_path);folder=p.root/'scratch/interrupted'
    def stop_after_improvement(objective,zero,**kwargs):
        objective(np.array([-.018/.08,0.,0.]))
        raise InterruptedError('Stop during native solve')
    monkeypatch.setattr(scipy.optimize,'minimize',stop_after_improvement)
    with pytest.raises(InterruptedError):
        fit_scene(p,scene,folder,{'objects':['block'],'cameras':[],'supports':{'block':'table'}})
    saved=read(folder/'best-scene.yaml');report=read(folder/'report.json')
    assert abs(saved['objects'][1]['pose']['value'][0][3])<1e-8
    assert report['best_loss']<np.mean([r['loss']for r in report['before']])
    cloud_inputs(p,saved)  # Saved checkpoint has current dependencies too.
    assert report['status']=='STOPPED'and not report['physical_verified']


def test_fixed_side_pose_is_shared_across_exif_rotated_observations(tmp_path):
    from real2sim_builder.observations import register_image,predict_views
    from real2sim_builder.cameras import camera_pixels
    from real2sim_builder.scene import value
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'scenes','same physical side');scene=legacy_scene()
    cam=scene['cameras'][0];cam['pose']['provenance']='estimated';p.save_scene(scene)
    images=[];segments=[];poses=[];intrinsics=[];depth=[]
    # Three calibrated external camera centres define a metric baseline. The
    # Side photographs differ only by EXIF orientation, never physical pose.
    for n in range(5):
        name='ref'+str(n)if n<3 else'side';orientation=6 if n==4 else 1
        res=[120,160]if orientation==6 else[160,120];path=tmp_path/f'{n}.png';Image.new('RGB',res,(n,0,0)).save(path)
        image=register_image(p,path,camera=name,camera_type='external'if n<3 else'side',scene_state='layout')
        image['exif_orientation']=orientation;images.append(image)
        pose=np.array(cam['pose']['value']);pose[:3,3]+=([0,0,0],[.1,0,0],[0,.1,0],[0,0,0],[0,0,0])[n]
        affine,optical=camera_pixels(cam,image);upright=pose.copy();upright[:3,:3]=pose[:3,:3]@optical.T
        poses.append(np.linalg.inv(upright));intrinsics.append(affine@np.array(cam['K']['value'])@optical.T)
        # Use a common square processed image; affine retains original pixels.
        depth.append(np.ones((160,160)))
        if n<3:scene['cameras'].append({**copy.deepcopy(cam),'id':name,'pose':value(pose.tolist(),'calibrated')})
    evidence=p.evidence
    for image in evidence['images']:image['exif_orientation']=next(i['exif_orientation']for i in images if i['id']==image['id'])
    write(p.root/'input/evidence.yaml',evidence);p.save_scene(scene);c=Candidate.create(p,'camera');batch=c.root/'depth.npz'
    np.savez(batch,depth=depth,intrinsics=intrinsics,extrinsics=poses,original_to_processed=np.repeat(np.eye(3)[None],5,axis=0))
    report={'images':images,'scene_state_id':'layout','segments':segments,'depth_batches':[{'path':str(batch),'metadata':{'sha256':sha(batch)},'image_ids':[i['id']for i in images]}]}
    result=predict_views(c,report)
    assert result['status']=='PREDICTED',result
    fitted=next(x for x in c.scene['cameras']if x['id']=='side')
    np.testing.assert_allclose(fitted['pose']['value'],cam['pose']['value'],atol=1e-8)


def test_passive_probe_rejects_final_penetration_even_with_zero_velocity(tmp_path,monkeypatch):
    import mujoco
    from real2sim_builder.validation import physics_probe
    from real2sim_builder.scene import value
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'scenes','penetration check');scene=legacy_scene();scene['objects'][1]['physics']['mass_kg']=value(.03,'estimated')
    def jammed_step(model,data):
        data.qpos[2]=.027;data.qvel[:]=0
        mujoco.mj_forward(model,data)
    monkeypatch.setattr(mujoco,'mj_step',jammed_step)
    report=physics_probe(p,scene,p.root/'scratch/probe',steps=1)
    assert not report['mujoco']['settled']
    assert report['mujoco']['final_penetrations']and any('Final inter-object penetration'in r for r in report['needs'])
