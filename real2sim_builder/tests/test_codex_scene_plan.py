import copy
import numpy as np
import pytest
from real2sim_builder.project import Project
from real2sim_builder.candidate import Candidate
from real2sim_builder.files import read,sha
from test_builder_export import legacy_scene


def test_scene_plan_places_assets_and_estimated_photo_camera_without_depth(tmp_path):
    from real2sim_builder.authoring import apply_scene_plan
    from real2sim_builder.observations import register_image,registered_images
    from PIL import Image
    p=Project.create(tmp_path,'Codex scene');scene=legacy_scene();scene['objects'][1]['pose']['provenance']='estimated';p.save_scene(scene);c=Candidate.create(p,'auto')
    rgb=tmp_path/'photo.png';Image.new('RGB',(160,120)).save(rgb)
    image=register_image(p,rgb,camera='photo_cam',camera_type='external',scene_state='layout')
    pose=np.eye(4);pose[:3,3]=[.1,0,.1]
    cam=np.eye(4);cam[:3,:3]=[[1,0,0],[0,-1,0],[0,0,-1]];cam[2,3]=1
    plan={'object_poses':[{'id':'block','pose':pose.tolist(),'evidence':['visible block'],'image_ids':[image['id']]}],
          'cameras':[{'id':'photo_cam','frame':'world','pose':cam.tolist(),'K':[[140,0,80],[0,140,60],[0,0,1]],'distortion':[0]*5,'resolution':[160,120],'image_ids':[image['id']],'evidence':['photo perspective estimate']}],'needs':[]}
    current=sha(p.root/'working/current_scene.yaml')
    apply_scene_plan(c,plan,scene_state='layout')
    row=c.scene['view_registrations'][image['id']]
    assert row['status']=='REGISTERED_ESTIMATED'and row['metric_scale_verified']is False
    assert row['provenance']=='estimated'and not row['physical_verified']
    assert registered_images(p,scene=c.scene)[0][0]['id']==image['id']
    assert c.scene['cameras'][-1]['K']['provenance']=='estimated'
    assert sha(p.root/'working/current_scene.yaml')==current
    assert not(c.root/'.cache/inference').exists()


def test_scene_plan_cannot_modify_measurements_or_reference_robot(tmp_path):
    from real2sim_builder.authoring import apply_scene_plan
    p=Project.create(tmp_path,'protected');p.save_scene(legacy_scene());c=Candidate.create(p,'auto')
    before=c.scene
    with pytest.raises(ValueError,match='Protected|reference|measured'):
        apply_scene_plan(c,{'object_poses':[{'id':'table','pose':np.eye(4).tolist(),'image_ids':[],'evidence':['estimate']}],'cameras':[],'needs':[]})
    assert c.scene==before


def test_scene_plan_requires_real_image_ids_and_rejects_invalid_camera_transform(tmp_path):
    from real2sim_builder.authoring import apply_scene_plan
    p=Project.create(tmp_path,'invalid');c=Candidate.create(p,'auto')
    plan={'object_poses':[],'cameras':[{'id':'fake','frame':'world','pose':np.eye(4).tolist(),'K':np.eye(3).tolist(),'distortion':[0]*5,'resolution':[160,120],'image_ids':['missing'],'evidence':['estimate']}],'needs':[]}
    with pytest.raises(ValueError,match='image'):apply_scene_plan(c,plan)
    assert not c.scene['cameras']


def test_source_camera_is_reused_for_registered_capture_without_new_pose(tmp_path):
    from real2sim_builder.authoring import apply_scene_plan
    from real2sim_builder.observations import register_image,registered_images
    from real2sim_builder.files import write
    from PIL import Image
    p=Project.create(tmp_path,'source view');p.save_scene(legacy_scene());c=Candidate.create(p,'auto')
    rgb=tmp_path/'real.png';Image.new('RGB',(160,120)).save(rgb)
    image=register_image(p,rgb,camera='side',camera_type='side',scene_state='layout')
    evidence=p.evidence;evidence['images'][0]['eligible']=False;write(p.root/'input/evidence.yaml',evidence)
    before=c.scene['cameras'];source=sha(p.root/'input/evidence.yaml')
    apply_scene_plan(c,{'object_poses':[],'cameras':[],'needs':[]},scene_state='layout')
    assert c.scene['cameras']==before
    assert registered_images(p,scene=c.scene)[0][0]['id']==image['id']
    assert sha(p.root/'input/evidence.yaml')==source


def test_partial_measured_asset_constraints_survive_geometry_estimation():
    from real2sim_builder.authoring import geometry_specs
    from real2sim_builder.scene import value
    scene=legacy_scene();paper=scene['objects'][1];paper['id']='paper'
    paper['dimensions']=value([.147,.151,.00015],'estimated',['render thickness'])
    paper['dimensions']['constraints']=value([.147,.151,None],'measured',['user outer border measurement'])
    specs=geometry_specs({'objects':{'paper':{'role':'workspace'}}},scene)
    measured=next(r for r in specs if r['id']=='paper')
    assert measured['dimensions_m']==[.147,.151,None]and measured['provenance']=='measured'
    with pytest.raises(ValueError,match='conflict'):
        geometry_specs({'objects':{'paper':{'geometry':{'kind':'box','dimensions_m':[.15,.15,.001],'provenance':'estimated'}}}},scene)


def test_other_layout_sensor_binding_is_context_only_not_static_alignment(tmp_path):
    from real2sim_builder.authoring import apply_scene_plan
    from real2sim_builder.observations import register_image
    from PIL import Image
    p=Project.create(tmp_path,'layout context');p.save_scene(legacy_scene());c=Candidate.create(p,'auto')
    rgb=tmp_path/'capture.png';Image.new('RGB',(160,120),'green').save(rgb)
    sensor=register_image(p,rgb,camera='side',camera_type='side',scene_state='capture_layout')
    cam=p.scene['cameras'][0]
    plan={'object_poses':[],'cameras':[{'id':'side','frame':'world','pose':cam['pose']['value'],'K':cam['K']['value'],'distortion':cam['distortion']['value'],'resolution':cam['resolution'],'image_ids':[sensor['id']],'evidence':['known fixed sensor']}],'needs':[]}
    apply_scene_plan(c,plan,scene_state='photo_layout',capture_layouts=[{'scene_state_id':'capture_layout','status':'DIFFERENT_LAYOUT'}])
    row=c.scene['view_registrations'][sensor['id']]
    assert row['comparison_scope']=='robot_context_only'
    assert row['static_layout_shared']is False


def test_composition_output_contract_excludes_reference_photos_and_unknown_cameras():
    from real2sim_builder.authoring import scene_plan_schema
    schema=scene_plan_schema(image_records=[{'id':'photo','camera':'cam','role':'scene_photo','split':'train'},
        {'id':'reference','camera':'reference_cam','role':'model_reference','split':'train'}],object_ids=['block'],frames=['world'])
    cam=schema['properties']['cameras']['items']['properties']
    assert cam['image_ids']['items']['enum']==['photo']
    assert cam['id']['enum']==['cam']
    assert schema['properties']['needs']['items']=={'type':'string'}
    assert cam['evidence']['items']=={'type':'string'}
    assert schema['properties']['object_poses']['items']['properties']['image_ids']['items']['enum']==['photo']


def test_scene_plan_can_complete_missing_mesh_support_anchor_but_cannot_move_it(tmp_path):
    from real2sim_builder.authoring import apply_scene_plan
    from real2sim_builder.scene import value,support_metrics
    p=Project.create(tmp_path,'explicit support');scene=legacy_scene()
    parent=scene['objects'][0];child=scene['objects'][1]
    parent['collision']={'type':'compound','parts':[{'type':'box','pose':np.eye(4).tolist(),'dimensions':parent['dimensions']['value']}]}
    scene['geometry_constraints']={'schema':'real2sim.geometry-constraints/1','units':'m','distances':[],
        'supports':{'block':{'support':'table','source':'user_declared','status':'CONFIRMED','evidence':['declared contact'],'parallel':True}}}
    child['pose']=value(np.eye(4).tolist(),'estimated',['initial placement'])
    p.save_scene(scene);c=Candidate.create(p,'auto')
    z=parent['dimensions']['value'][2]/2
    plan={'object_poses':[],'cameras':[],'needs':[],
        'support_anchors':[{'id':'block','support':'table','point_m':[0,0,z],'normal':[0,0,1],'image_ids':[],'evidence':['actual collision top face']} ]}
    apply_scene_plan(c,plan)
    relation=c.scene['geometry_constraints']['supports']['block']
    assert relation['support_anchor']=={'point_m':[0,0,z],'normal':[0,0,1]}
    assert relation['status']=='CONFIRMED'and relation['tolerance_m']==1e-6
    assert support_metrics(c.scene,root=p.root)['status']=='SATISFIED'
    before=c.scene
    plan['support_anchors'][0]['point_m'][2]+=0.01
    with pytest.raises(ValueError,match='anchor|Anchor|CONSTRAINT'):apply_scene_plan(c,plan)
    assert c.scene==before


def test_missing_mesh_anchor_requests_bounded_typed_composition_feedback(tmp_path):
    from real2sim_builder.automation import reconstruct
    from real2sim_builder.scene import value
    p=Project.create(tmp_path,'support feedback');scene=legacy_scene()
    parent=scene['objects'][0]
    parent['collision']={'type':'compound','parts':[{'type':'box','pose':np.eye(4).tolist(),'dimensions':parent['dimensions']['value']}]}
    scene['objects'][1]['pose']=value(np.eye(4).tolist(),'estimated',['initial placement'])
    scene['geometry_constraints']={'schema':'real2sim.geometry-constraints/1','units':'m','distances':[],
        'supports':{'block':{'support':'table','source':'user_declared','status':'CONFIRMED','evidence':['declared contact'],'parallel':True}}}
    p.save_scene(scene)
    result=reconstruct(p,candidate='auto',config={'objects':{'block':{'prompt':'block'}},'scene_plan':{'object_poses':[],'cameras':[],'needs':[]}})
    assert result['status']=='WAITING_FOR_CODEX_SCENE'
    config=read(Candidate(p,'auto').root/'review-config.yaml')
    assert 'block'in config['composition_feedback']['validation_error']
    assert 'scene_plan'not in config


def test_composition_does_not_overwrite_conflicting_configured_anchor(tmp_path):
    from real2sim_builder.automation import reconstruct
    scene=legacy_scene();z=scene['objects'][0]['dimensions']['value'][2]/2
    relation={'support':'table','source':'user_declared','status':'CONFIRMED','evidence':['declared contact'],'parallel':True,
        'support_anchor':{'point_m':[0,0,z],'normal':[0,0,1]}}
    scene['geometry_constraints']={'schema':'real2sim.geometry-constraints/1','units':'m','distances':[],'supports':{'block':relation}}
    p=Project.create(tmp_path,'anchor conflict');p.save_scene(scene)
    configured=copy.deepcopy(relation);configured['support_anchor']['point_m'][2]+=.01
    with pytest.raises(ValueError,match='CONSTRAINT_CONFLICT'):
        reconstruct(p,candidate='auto',config={'objects':{'block':{'prompt':'block'}},
            'scene_plan':{'object_poses':[],'cameras':[],'needs':[]},'fitting':{'supports':{'block':configured}}})
