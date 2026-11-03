import copy
import numpy as np
import pytest
from PIL import Image
from real2sim_builder.project import Project,Candidate
from real2sim_builder.scene import empty,value
from real2sim_builder.files import sha


def test_external_image_keeps_identity_and_is_not_a_fake_measured_joint_capture(tmp_path):
    from real2sim_builder.observations import register_image,registered_images,input_images
    p=Project.create(tmp_path,'views');path=tmp_path/'external.png';Image.new('RGB',(80,60)).save(path)
    record=register_image(p,path,camera='phone',camera_type='external',scene_state='layout_1',split='train')
    assert record['camera_type']=='external'and record['q_measured']is None
    assert record['registration_status']=='UNREGISTERED'and not record['eligible']
    images,state,needs=registered_images(p,'layout_1');assert not images and needs
    assert input_images(p,'layout_1')[0][0]['sha256']==sha(path)
    assert record['resolution']==[80,60]and record['scene_state_id']==state
    with pytest.raises(ValueError,match='layout'):
        register_image(p,path,camera='phone',camera_type='external',scene_state='layout_2')


def test_wrist_photo_cannot_invent_a_joint_mapping_or_time_binding(tmp_path):
    from real2sim_builder.observations import register_image
    p=Project.create(tmp_path,'wrist');path=tmp_path/'wrist.png';Image.new('RGB',(80,60)).save(path)
    before=p.evidence
    with pytest.raises(ValueError,match='measured'):
        register_image(p,path,camera='wrist',camera_type='wrist',scene_state='layout_1')
    assert p.evidence==before


def test_repeat_registration_preserves_the_original_metadata(tmp_path):
    from real2sim_builder.observations import register_image
    p=Project.create(tmp_path,'repeat');path=tmp_path/'phone.png';Image.new('RGB',(80,60)).save(path)
    row=register_image(p,path,camera='phone',camera_type='external',scene_state='layout_1')
    before=copy.deepcopy(p.evidence)
    assert register_image(p,path,camera='phone',camera_type='external',scene_state='layout_1')==row
    assert p.evidence==before
    with pytest.raises(ValueError,match='already registered'):
        register_image(p,path,camera='phone',camera_type='external',scene_state='layout_1',split='validation')
    assert p.evidence==before


def test_external_world_pose_is_derived_from_metric_anchors_without_changing_source_or_scene(tmp_path):
    from real2sim_builder.observations import register_image,register_views,registered_images
    from real2sim_builder.capture import observation_scene
    import cv2
    p=Project.create(tmp_path,'anchors');scene=empty('anchors');k=np.array([[120,0,40],[0,120,30],[0,0,1.]])
    scene['cameras']=[{'id':'phone','frame':'world','pose':value(None),'K':value(k.tolist(),'calibrated',['fixture lens calibration']),
                       'distortion':value([0.]*5,'calibrated',['fixture calibration']),'resolution':[80,60]}]
    p.save_scene(scene);c=Candidate.create(p,'registered');paths=[];rows=[]
    for i in range(2):
        path=tmp_path/f'phone_{i}.png';Image.new('RGB',(80,60),(i*100,0,0)).save(path);paths.append(path)
        rows.append(register_image(p,path,camera='phone',camera_type='external',scene_state='layout_1'))
    points=np.array([[-.1,-.1,0],[.1,-.1,0],[.1,.1,0],[-.1,.1,0],[0,0,.05]],float)
    bindings={}
    for i,row in enumerate(rows):
        uv,_=cv2.projectPoints(points,np.zeros(3),np.array([i*.02,0,.5]),k,np.zeros(5))
        bindings[row['id']]={'world_points_m':points.tolist(),'uv_px':uv.reshape(-1,2).tolist(),'source':'measured','evidence':['fixture board coordinates']}
    before=copy.deepcopy(p.evidence);signature=p.signature(scene)
    result=register_views(c,bindings,scene_state='layout_1')
    assert result['status']=='REGISTERED_ESTIMATED'and len(result['views'])==2
    assert p.evidence==before and p.signature(scene)==signature
    selected,_,needs=registered_images(p,'layout_1',scene=c.scene);assert len(selected)==2 and not needs
    poses=[observation_scene(c.scene,row,p.root,complete=False)['cameras'][0]['pose']['value']for row in selected]
    assert not np.allclose(poses[0],poses[1])
    assert c.scene['cameras'][0]['K']==scene['cameras'][0]['K']
    assert c.scene['cameras'][0]['pose']['value']is None
    assert all(sha(path)==row['sha256']for path,row in zip(paths,rows))


def test_unknown_intrinsic_and_unanchored_da3_pose_stay_unregistered(tmp_path):
    from real2sim_builder.observations import register_image,register_views
    p=Project.create(tmp_path,'unknown');path=tmp_path/'phone.png';Image.new('RGB',(80,60)).save(path)
    row=register_image(p,path,camera='phone',camera_type='external',scene_state='layout_1');c=Candidate.create(p,'draft')
    before=sha(c.root/'candidate_scene.yaml')
    result=register_views(c,{row['id']:{'da3_extrinsics':np.eye(4).tolist()}},scene_state='layout_1')
    assert result['status']=='NEEDS_MORE_DATA'and result['needs']
    assert sha(c.root/'candidate_scene.yaml')==before


def test_registered_wrist_uses_measured_q_fk_even_without_legacy_session(tmp_path):
    import hashlib,json
    from real2sim_builder.observations import register_image,register_views,registered_images
    from real2sim_builder.capture import observation_scene
    p=Project.create(tmp_path,'wrist FK');scene=empty('wrist');model=p.root/'input/robot.urdf'
    model.write_text('<robot name="r"><link name="base"/><link name="mount"/><joint name="j" type="revolute"><parent link="base"/><child link="mount"/><axis xyz="0 0 1"/></joint></robot>')
    mapping={'version':'so101.sim-joint-mapping/1','joint_order':['j'],'output':'urdf_joint_radian'}
    mapping['sha256']=hashlib.sha256(json.dumps(mapping,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    scene['robot_model']={'path':'input/robot.urdf','model_sha256':sha(model),'joint_names':['j'],'mapping':mapping,'mapping_verified':False}
    for name,parent in(('robot_base','world'),('robot_link_mount','robot_base')):
        scene['frames'][name]={'parent':parent,'transform':value(np.eye(4).tolist(),'derived')}
    scene['cameras']=[{'id':'wrist','frame':'robot_link_mount','pose':value(np.eye(4).tolist(),'calibrated'),
        'K':value([[50,0,40],[0,50,30],[0,0,1]],'calibrated'),'distortion':value([0.]*5,'calibrated'),'resolution':[80,60]}]
    p.save_scene(scene);path=tmp_path/'wrist.png';Image.new('RGB',(80,60)).save(path)
    row=register_image(p,path,camera='wrist',camera_type='wrist',scene_state='layout',joint_record={
        'q_measured':[.5],'joint_names':['j'],'joint_units':['rad'],'mapping_sha256':mapping['sha256'],
        'robot_model_sha256':sha(model),'image_timestamp_ns':1000,'joint_timestamp_ns':1000})
    c=Candidate.create(p,'mounted');result=register_views(c,scene_state='layout')
    assert len(result['views'])==1 and not result['physical_verified']
    image=registered_images(p,'layout',scene=c.scene)[0][0]
    posed=observation_scene(c.scene,image,p.root,complete=False)
    rotation=np.asarray(posed['frames']['robot_link_mount']['transform']['value'])[:3,:3]
    assert rotation[0,0]==pytest.approx(np.cos(.5)) and p.evidence['images'][0]['q_measured']==[.5]


def test_external_video_frames_keep_video_group_and_real_timestamps(tmp_path):
    import cv2
    from real2sim_builder.observations import register_sources
    video=tmp_path/'phone.avi';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(80,60))
    assert writer.isOpened()
    for index in range(4):writer.write(np.full((60,80,3),index*50,np.uint8))
    writer.release();digest=sha(video);p=Project.create(tmp_path,'video')
    rows=register_sources(p,[video],camera='phone',camera_type='external',scene_state='layout')
    assert len(rows)==4 and {row['group_id']for row in rows}=={'video_'+digest}
    assert [row['timestamp']for row in rows]==[0,.1,.2,.3]
    assert all(row['source_video_sha256']==digest and row['q_measured']is None for row in rows)
    assert sha(video)==digest and p.evidence['videos'][0]['extracted']
