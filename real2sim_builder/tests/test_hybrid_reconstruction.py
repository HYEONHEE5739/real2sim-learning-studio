import copy
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from test_builder_export import legacy_scene


def test_measured_geometry_creates_open_cup_and_keeps_unknown_pose_and_robot():
    from real2sim_builder.initialization import measured_geometry
    scene=legacy_scene();before=copy.deepcopy(scene)
    spec={'id':'cup','role':'receptacle','kind':'container','dimensions_m':[.08,.08,.1],
          'wall_m':.002,'round':True,'evidence':['caliper record']}
    result=measured_geometry(scene,[spec])
    assert scene==before and result['objects'][:2]==before['objects']
    cup=result['objects'][-1]
    assert cup['pose']['value'] is None and cup['dimensions']['provenance']=='measured'
    assert cup['collision']['wall']['value']==.002 and cup['collision']['type']=='container'
    with pytest.raises(ValueError,match='measured'):
        measured_geometry(scene,[{**spec,'evidence':[]}])
    with pytest.raises(ValueError,match='locked'):
        measured_geometry(scene,[{**spec,'id':'block','kind':'box','dimensions_m':[.1]*3}])


def test_metric_depth_scale_comes_from_real_anchor_distances_not_default_one():
    from real2sim_builder.inference import depth_scale_from_anchors
    depth=np.full((20,20),2.)
    uv=[[2,2],[15,2],[15,15],[2,15]]
    points=[[-.1,-.1,1],[.1,-.1,1],[.1,.1,1],[-.1,.1,1]]
    result=depth_scale_from_anchors(depth,np.eye(3),uv,points,np.eye(4),['board measurement'])
    assert result['status']=='ESTIMATED' and result['anchor']['scale']==pytest.approx(.5)
    assert depth_scale_from_anchors(depth,np.eye(3),[],[],np.eye(4),[])['status']=='NEEDS_MORE_DATA'


def test_trimmed_icp_recovers_rigid_pose_despite_outliers_without_scaling():
    from real2sim_builder.calibration.hybrid import trimmed_icp
    rng=np.random.default_rng(7);model=rng.uniform(-.05,.05,(1200,3))
    pose=np.eye(4);pose[:3,:3]=Rotation.from_euler('xyz',[.05,-.03,.08]).as_matrix();pose[:3,3]=[.02,-.01,.03]
    observed=model@pose[:3,:3].T+pose[:3,3]
    observed=np.r_[observed,rng.uniform(.3,.5,(150,3))]
    start=pose.copy();start[:3,3]+=[.007,-.005,.006]
    report=trimmed_icp(model,observed,[start],trim=.85,iterations=60)
    assert report['status']=='ESTIMATED' and report['rmse_m']<1e-5
    np.testing.assert_allclose(report['T_world_object'],pose,atol=1e-4)
    assert report['scale']==1 and report['outliers_removed']>=150
    assert trimmed_icp(model,np.zeros((5,3)),[start])['status']=='NEEDS_MORE_DATA'


def test_planar_depth_reports_rotation_ambiguity_instead_of_confident_pose():
    from real2sim_builder.calibration.hybrid import trimmed_icp
    x,y=np.meshgrid(np.linspace(-.05,.05,12),np.linspace(-.05,.05,12))
    plane=np.c_[x.ravel(),y.ravel(),np.zeros(x.size)]
    result=trimmed_icp(plane,plane,[np.eye(4)])
    assert result['status']=='NEEDS_MORE_DATA' and 'degenerate' in ' '.join(result['needs'])


def test_mask_pose_updates_equal_fresh_native_render_without_recompiling(tmp_path):
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.scene import value
    scene=legacy_scene();scene['objects'][1]['pose']['provenance']='estimated'
    pose=np.array(scene['objects'][1]['pose']['value']);pose[0,3]+=.1
    with Renderer(scene,tmp_path,tmp_path/'first')as model:
        before=model.mask('side','block');model.set_object_pose('block',pose)
        changed=model.mask('side','block')
        assert not np.array_equal(before,changed)
    scene['objects'][1]['pose']=value(pose.tolist(),'estimated')
    with Renderer(scene,tmp_path,tmp_path/'fresh')as model:
        np.testing.assert_array_equal(changed,model.mask('side','block'))


def test_native_mask_refinement_improves_train_and_only_reports_holdout(tmp_path):
    from real2sim_builder.calibration.hybrid import refine_masks,surface_points,fit_clouds,alignment_metrics
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.observations import register_image,register_views
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.files import sha
    from real2sim_builder.scene import value
    from PIL import Image
    p=Project.create(tmp_path,'mask fit');truth=legacy_scene();p.save_scene(truth)
    with Renderer(truth,p.root,tmp_path/'truth')as renderer:
        mask=renderer.mask('side','block');rgb=renderer.rgb('side')
    path=tmp_path/'real.png';Image.fromarray(rgb).save(path)
    image=register_image(p,path,camera='side',camera_type='side',scene_state='layout')
    candidate=Candidate.create(p,'registered');register_views(candidate,scene_state='layout');truth=candidate.scene
    mask_file=p.root/'input/mask.png';Image.fromarray(mask.astype('uint8')*255).save(mask_file)
    points=surface_points(truth['objects'][1],truth,p.root)+[0,0,.03]
    cloud=p.root/'input/cloud.npz';np.savez(cloud,points_world_m=points)
    row={'image_id':image['id'],'object_id':'block','split':'train','group_id':image['id'],
         'path':'input/cloud.npz','sha256':sha(cloud),'mask':'input/mask.png','mask_sha256':sha(mask_file),
         'units':'m','frame':'world','mask_kind':'silhouette'}
    scene=copy.deepcopy(truth);pose=np.asarray(scene['objects'][1]['pose']['value']);pose[0,3]+=.018
    scene['objects'][1]['pose']=value(pose.tolist(),'estimated')
    scene['reconstruction_observations']={'scene_state_id':'layout','clouds':[row]}
    fitted,report=refine_masks(p,scene,tmp_path/'refine',{'objects':['block'],'supports':{'block':'table'},'max_evaluations':80})
    assert report['after'][0]['iou']>report['before'][0]['iou']
    assert report['physics_steps']==0 and fitted['objects'][1]['dimensions']==truth['objects'][1]['dimensions']
    assert np.linalg.norm(np.array(fitted['objects'][1]['pose']['value'])[:3,3]-[0,0,.03])<.018
    metrics=alignment_metrics(p,fitted,tmp_path/'alignment')
    assert metrics['images'][0]['objects'][0]['iou']>.8
    assert (tmp_path/'alignment/previews'/image['id']/'overlay.png').is_file()
    first,report=fit_clouds(p,scene,{'supports':{'block':'table'}})
    # A held-out cloud cannot become an initializer or an ICP residual.
    hostile=copy.deepcopy(row);hostile.update(image_id='held',split='validation',group_id='held')
    scene['reconstruction_observations']['clouds'].append(hostile)
    second,_=fit_clouds(p,scene,{'supports':{'block':'table'}})
    assert first=={**second,'reconstruction_observations':first['reconstruction_observations']}
    from real2sim_builder.calibration.hybrid import compare_backends
    from real2sim_builder.automation import draft_readiness
    fitted,comparison=compare_backends(p,{**scene,'reconstruction_observations':{'scene_state_id':'layout','clouds':[row]}},tmp_path/'comparison',
        {'backend':'icp_mask','objects':['block'],'supports':{'block':'table'},'max_evaluations':30})
    assert draft_readiness(p,fitted,comparison)['status']=='DRAFT_READY'
    assert comparison['winner']is None and comparison['default_backend']is None


def test_physics_probe_steps_gravity_and_keeps_articulation_unverified(tmp_path):
    from real2sim_builder.validation import physics_probe
    from real2sim_builder.project import Project
    from real2sim_builder.scene import value
    scene=legacy_scene();scene['objects'][1]['physics']['mass_kg']=value(.02,'estimated',['fixture mass'])
    scene['objects'][1]['physics']['friction']=value(.8,'estimated',['fixture friction'])
    p=Project.create(tmp_path,'physics');before=copy.deepcopy(scene)
    report=physics_probe(p,scene,tmp_path/'physics',steps=250)
    assert scene==before and report['mujoco']['steps']==250
    assert report['mujoco']['finite'] and report['mujoco']['contact_count']>0
    assert report['robot_articulation']=='NOT_TESTED' and report['physical_verified'] is False
    assert report['isaac']['physics_steps']==0 and report['isaac']['status']=='NOT_TESTED'
    assert report['status']!='PHYSICS_READY'


def test_cloud_pose_fit_preserves_measured_pair_distance(tmp_path):
    from real2sim_builder.calibration.hybrid import fit_clouds,surface_points
    from real2sim_builder.initialization import apply_geometry_constraints
    from real2sim_builder.project import Project
    from real2sim_builder.scene import world_pose,validate
    from real2sim_builder.files import sha
    from test_builder_project import measured_pair_scene,measured_pair_constraints
    from PIL import Image
    p=Project.create(tmp_path,'pair fit');scene,_=apply_geometry_constraints(measured_pair_scene(),measured_pair_constraints())
    rows=[]
    for index,obj in enumerate(scene['objects']):
        points=surface_points(obj,scene,p.root,500);pose=world_pose(scene,obj)
        points=points@pose[:3,:3].T+pose[:3,3]+[.005,index*.002,0]
        cloud=p.root/'input'/('cloud_'+str(index)+'.npz');np.savez(cloud,points_world_m=points)
        mask=p.root/'input'/('mask_'+str(index)+'.png');Image.new('L',(10,10),255).save(mask)
        rows.append({'object_id':obj['id'],'image_id':'view','split':'train','group_id':'view','units':'m','frame':'world',
            'path':cloud.relative_to(p.root).as_posix(),'sha256':sha(cloud),'mask':mask.relative_to(p.root).as_posix(),'mask_sha256':sha(mask)})
    scene['reconstruction_observations']={'clouds':rows};fitted,report=fit_clouds(p,scene,{'iterations':10})
    validate(fitted);poses=[world_pose(fitted,o)for o in fitted['objects']]
    assert np.linalg.norm(poses[0][:3,3]-poses[1][:3,3])==pytest.approx(.09)
    assert report['measured_constraints']['status']=='MEASURED_RELATIVE_GEOMETRY_APPLIED'
