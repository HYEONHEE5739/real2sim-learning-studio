"""Explicit Candidate joint-fit acceptance must keep derived observations usable.

The numerical solve alone is substituted; RGB/NPZ/registered-view dependency
checks, optical reprojection and Candidate persistence use product code.
"""
import copy

import numpy as np
import pytest
from PIL import Image

from real2sim_builder.calibration import hybrid,joint
from real2sim_builder.capture import observation_scene
from real2sim_builder.files import read,sha
from real2sim_builder.observations import register_image,registered_images,source_record_digest
from real2sim_builder.project import Candidate,Project
from real2sim_builder.scene import camera_calibration_signature,value,world_pose
from test_builder_export import legacy_scene


def _fixture(tmp_path,kind='camera',*,protected=False):
    project=Project.create(tmp_path/'projects','direct joint dependencies');scene=legacy_scene()
    camera=scene['cameras'][0]
    scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'calibrated'if protected else'estimated')}
    joint_record=None
    if kind in('mount','base'):
        from real2sim_builder.calibration.geometry import link_transforms
        model=project.root/'input/robot.urdf'
        model.write_text('<robot name="fixture"><link name="base"/><link name="hand"/>'
            '<joint name="hinge" type="revolute"><parent link="base"/><child link="hand"/>'
            '<origin xyz=".1 0 0"/><axis xyz="0 0 1"/><limit lower="-1" upper="1" effort="1" velocity="1"/>'
            '</joint></robot>')
        scene['robot_model']={'format':'urdf','path':'input/robot.urdf','model_sha256':sha(model),
            'joint_names':['hinge'],'mapping':{'sha256':'a'*64}}
        for link,pose in link_transforms(model,{'hinge':0.}).items():
            scene['frames']['robot_link_'+link]={'parent':'robot_base','transform':value(pose.tolist(),'derived')}
        camera.update(id='wrist',camera_type='wrist',frame='robot_link_hand')
        # The shared mount remains calibrated in the Base-only case.
        camera['pose']['provenance']='calibrated'if kind=='base'or protected else'estimated'
        joint_record={'q_measured':[.25],'joint_names':['hinge'],'joint_units':['rad'],
            'mapping_sha256':'a'*64,'robot_model_sha256':sha(model),'image_timestamp_ns':1000,'joint_timestamp_ns':1000}
    else:camera['pose']['provenance']='calibrated'if protected else'estimated'
    project.save_scene(scene)
    source=tmp_path/'rgb.png';Image.new('RGB',(160,120),(23,46,79)).save(source)
    image=register_image(project,source,camera=camera['id'],camera_type='wrist'if joint_record else'side',
        scene_state='layout',joint_record=joint_record)
    # Known synthetic initial registration. It intentionally follows the shared
    # Camera/mount, rather than storing an unrelated per-image World pose.
    signature=camera_calibration_signature(scene,camera)
    scene['view_registrations']={image['id']:{'status':'REGISTERED_ESTIMATED','source_image_sha256':image['sha256'],
        'image_record_sha256':source_record_digest(image),'scene_state_id':'layout','camera':camera['id'],
        'camera_signature':signature,'T_world_camera':None,'calibration_evidence':['synthetic initial registration']}}
    scene['reconstruction_state']={'id':'layout'}
    posed=observation_scene(scene,image,project.root,complete=False)
    optical=np.array([[-.03,-.02,.6],[.03,-.02,.8],[.03,.02,1.],[-.03,.02,1.2]])
    pose=world_pose(posed,posed['cameras'][0]);world=optical@pose[:3,:3].T+pose[:3,3]
    source_npz=project.root/'input/raw-optical.npz'
    np.savez_compressed(source_npz,points_camera_relative=optical,points_world_m=world)
    mask=project.root/'input/object-mask.png';Image.new('L',(160,120),255).save(mask)
    scene['reconstruction_observations']={'clouds':[{'image_id':image['id'],'object_id':'block',
        'split':'train','group_id':image['group_id'],'path':'input/raw-optical.npz','sha256':sha(source_npz),
        'mask':'input/object-mask.png','mask_sha256':sha(mask),'units':'m','frame':'world','depth_scale':1.,
        'dependencies':{'image_sha256':image['sha256'],'image_record_sha256':source_record_digest(image),
            'camera_signature':signature,'camera_pose':pose.tolist()}}]}
    candidate=Candidate.create(project,'draft');candidate.save(scene)
    return project,candidate,image,source_npz,optical


def _move(scene,kind,amount):
    updated=copy.deepcopy(scene)
    field=updated['frames']['robot_base']['transform']if kind=='base'else updated['cameras'][0]['pose']
    field['value'][0][3]+=amount
    return updated


def _oracle(scene,image,project,optical):
    posed=observation_scene(scene,image,project.root,complete=False)
    camera=next(row for row in posed['cameras']if row['id']==image['camera'])
    pose=world_pose(posed,camera)
    return optical@pose[:3,:3].T+pose[:3,3]


@pytest.mark.parametrize('kind',['camera','mount','base'])
def test_direct_joint_fit_reprojects_raw_cloud_and_refreshes_shared_dependencies(tmp_path,monkeypatch,kind):
    project,candidate,image,source_npz,optical=_fixture(tmp_path,kind)
    original=sha(source_npz);current=sha(project.root/'working/current_scene.yaml');input_sha=sha(project.root/'input/evidence.yaml')
    scene=candidate.scene;old_row=copy.deepcopy(scene['reconstruction_observations']['clouds'][0])
    original_mask=sha(project.root/old_row['mask'])
    def solve(project,scene,options):
        # Direct explicit diagnostic fitting retains IMPROVED even when rank is
        # deficient; automatic Stage10/Numeric rank veto is a separate policy.
        return _move(scene,kind,.04),{'status':'IMPROVED','jacobian_rank':2,'parameter_count':6,
            'needs':['Synthetic rank-deficient diagnostic'],'physical_verified':False}
    monkeypatch.setattr(joint,'fit_joint_scene',solve)
    report=candidate.fit('joint:scene',{'cameras':[image['camera']]})
    assert report['status']=='IMPROVED'and report['jacobian_rank']==2
    saved=candidate.scene;row=saved['reconstruction_observations']['clouds'][0]
    assert row['path']!=old_row['path'],'Accepted shared Camera calibration left the old World cloud in place'
    assert row['sha256']==sha(project.root/row['path'])
    assert len(registered_images(project,'layout',scene=saved)[0])==1
    assert hybrid.cloud_inputs(project,saved)==saved['reconstruction_observations']['clouds']
    with np.load(project.root/row['path'],allow_pickle=False)as values:
        np.testing.assert_array_equal(values['points_camera_relative'],optical)
        np.testing.assert_allclose(values['points_world_m'],_oracle(saved,image,project,optical),atol=1e-15)
    assert row['mask']==old_row['mask']and sha(project.root/row['mask'])==original_mask
    assert source_npz.is_file()and sha(source_npz)==original
    assert sha(project.root/'working/current_scene.yaml')==current and sha(project.root/'input/evidence.yaml')==input_sha
    assert read(candidate.root/'joint-fit.json')['status']=='IMPROVED'


def test_repeated_direct_joint_fit_uses_original_optical_points_not_accumulated_world(tmp_path,monkeypatch):
    project,candidate,image,source_npz,optical=_fixture(tmp_path)
    initial=candidate.scene;source_sha=sha(source_npz);paths=[]
    monkeypatch.setattr(joint,'fit_joint_scene',lambda project,scene,options:(
        _move(scene,'camera',.04),{'status':'IMPROVED','physical_verified':False}))
    for iteration in range(2):
        assert candidate.fit('joint:scene')['status']=='IMPROVED'
        scene=candidate.scene;row=scene['reconstruction_observations']['clouds'][0];paths.append(row['path'])
        with np.load(project.root/row['path'],allow_pickle=False)as values:
            np.testing.assert_allclose(values['points_world_m'],_oracle(scene,image,project,optical),atol=1e-15)
            np.testing.assert_array_equal(values['points_camera_relative'],optical)
        assert len(registered_images(project,'layout',scene=scene)[0])==1
        hybrid.cloud_inputs(project,scene)
    assert len(set(paths))==2
    assert candidate.scene['cameras'][0]['pose']['value'][0][3]==pytest.approx(initial['cameras'][0]['pose']['value'][0][3]+.08)
    assert sha(source_npz)==source_sha


def test_nonimproved_fit_does_not_adopt_solver_scene_or_rewrite_cloud_references(tmp_path,monkeypatch):
    project,candidate,image,source_npz,optical=_fixture(tmp_path)
    before=candidate.scene;scene_sha=sha(candidate.root/'candidate_scene.yaml');raw_sha=sha(source_npz)
    monkeypatch.setattr(joint,'fit_joint_scene',lambda project,scene,options:(
        _move(scene,'camera',.04),{'status':'NEEDS_MORE_DATA','needs':['synthetic no accepted fit']}))
    assert candidate.fit('joint:scene')['status']=='NEEDS_MORE_DATA'
    assert candidate.scene==before and sha(candidate.root/'candidate_scene.yaml')==scene_sha
    assert sha(source_npz)==raw_sha
    assert len(registered_images(project,'layout',scene=candidate.scene)[0])==1


def test_direct_fit_cannot_bypass_protected_measured_camera_with_refreshed_observations(tmp_path,monkeypatch):
    project,candidate,image,source_npz,optical=_fixture(tmp_path,protected=True)
    before=candidate.scene;scene_sha=sha(candidate.root/'candidate_scene.yaml');raw_sha=sha(source_npz)
    monkeypatch.setattr(joint,'fit_joint_scene',lambda project,scene,options:(
        _move(scene,'camera',.04),{'status':'IMPROVED','physical_verified':False}))
    with pytest.raises(ValueError,match='Protected'):candidate.fit('joint:scene')
    assert candidate.scene==before and sha(candidate.root/'candidate_scene.yaml')==scene_sha
    assert sha(source_npz)==raw_sha
