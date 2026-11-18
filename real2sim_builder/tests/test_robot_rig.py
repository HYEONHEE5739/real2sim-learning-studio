"""Fixed visual accessories preserve the source robot's articulated contract.

These tests use native USD/OBJ closures and the real URDF FK implementation;
they never connect hardware, initialize a learned model or invoke Blender.
"""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from real2sim_builder.candidate import Candidate
from real2sim_builder.files import read,sha
from real2sim_builder.project import Project


def rig_fixture(tmp_path):
    from test_object_assets import asset_fixture
    from real2sim_builder.object_assets import register_object_asset
    import trimesh
    project=Project.create(tmp_path/'projects','Rig fixture')
    asset=register_object_asset(project,asset_fixture(tmp_path/'camera-source'),
        asset_id='test_camera_assembly')
    source=tmp_path/'robot-source';source.mkdir()
    mesh=source/'body.stl';trimesh.creation.box(extents=[.03,.04,.06]).export(mesh)
    model=source/'robot.urdf'
    model.write_text('''<robot name="fixture_arm">
      <link name="base"><visual><geometry><mesh filename="body.stl"/></geometry></visual></link>
      <link name="wrist"><visual><origin xyz="0 0 .01"/><geometry><box size=".025 .03 .04"/></geometry></visual></link>
      <link name="jaw"><visual><geometry><box size=".01 .02 .03"/></geometry></visual></link>
      <joint name="hinge" type="revolute"><parent link="base"/><child link="wrist"/>
        <origin xyz=".01 .02 .08" rpy=".1 .2 .3"/><axis xyz="0 0 1"/>
        <limit lower="-1.2" upper="1.4" effort="5" velocity="2"/><dynamics damping=".03"/></joint>
      <joint name="gripper" type="revolute"><parent link="wrist"/><child link="jaw"/>
        <origin xyz="0 -.02 .01" rpy="0 .1 0"/><axis xyz="1 0 0"/>
        <limit lower="-.5" upper=".8" effort="2" velocity="1"/></joint>
    </robot>''')
    mount=np.eye(4);mount[:3,:3]=[[1,0,0],[0,0,-1],[0,1,0]];mount[:3,3]=[.02,-.03,.025]
    optical=np.eye(4);optical[:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]];optical[:3,3]=[0,-.02,.04]
    manifest=(project.root/asset['manifest']).resolve()
    return project,model,manifest,mount,optical


def build(tmp_path,case=None,**changes):
    from real2sim_builder.evidence import create_robot_rig
    project,source,manifest,mount,optical=case or rig_fixture(tmp_path)
    options={'mount_link':'wrist','T_link_mount':mount.tolist(),
        'T_mount_optical':optical.tolist(),'evidence':['Synthetic fixture mounting reference; uncalibrated']}
    options.update(changes)
    rig=create_robot_rig(source,manifest,tmp_path/'rig-output',**options)
    return rig,(project,source,manifest,mount,optical)


def model_path(rig):
    root=Path(rig['path']).parent
    return root/rig['model']['path']


def structural(node):
    return (node.tag,dict(node.attrib),(node.text or '').strip(),[structural(c)for c in node])


def test_fixed_camera_variant_preserves_source_joint_graph_and_all_mesh_paths(tmp_path):
    case=rig_fixture(tmp_path);_,source,manifest,_,_=case
    original={p:sha(p)for p in source.parent.rglob('*')if p.is_file()}
    asset_bytes={p:sha(p)for p in manifest.parent.rglob('*')if p.is_file()}
    rig,_=build(tmp_path,case)
    assert Path(rig['path']).is_absolute()
    assert Path(rig['path']).name=='rig.yaml'
    assert rig['schema']=='real2sim.robot-rig/1'
    assert rig['mount_status']=='estimated' and rig['calibration_status']=='uncalibrated'
    assert rig['source_robot_sha256']==sha(source)
    root=ET.parse(model_path(rig)).getroot();old=ET.parse(source).getroot()
    new_joints={j.get('name'):j for j in root.findall('joint')}
    for j in old.findall('joint'):assert structural(new_joints[j.get('name')])==structural(j)
    assert len(new_joints)==len(old.findall('joint'))+2
    assert {j.get('name')for j in root.findall('joint')if j.get('type')!='fixed'}=={'hinge','gripper'}
    assert {'wrist_camera_mount_link','camera_optical_frame'}<={n.get('name')for n in root.findall('link')}
    camera=root.find("link[@name='wrist_camera_mount_link']")
    assert camera.findall('visual') and camera.findall('collision')
    for mesh in root.findall('.//mesh'):
        filename=mesh.get('filename');assert filename and not filename.startswith(('package://','/'))
        path=(model_path(rig).parent/filename).resolve()
        assert path.is_relative_to(Path(rig['path']).parent) and path.is_file()
        assert path.suffix.lower()in('.obj','.stl','.dae'),filename
    assert all(sha(p)==v for p,v in original.items())
    assert all(sha(p)==v for p,v in asset_bytes.items())


@pytest.mark.parametrize('hinge,gripper',[(0.,0.),(.4,.2),(-.7,.5)])
def test_camera_follows_actual_fk_and_original_links_are_identical(tmp_path,hinge,gripper):
    from real2sim_builder.calibration.geometry import link_transforms
    rig,case=build(tmp_path);_,source,_,mount,optical=case
    joints={'hinge':hinge,'gripper':gripper}
    old=link_transforms(source,joints);new=link_transforms(model_path(rig),joints)
    for name,pose in old.items():np.testing.assert_allclose(new[name],pose,atol=1e-12)
    np.testing.assert_allclose(new['wrist_camera_mount_link'],old['wrist']@mount,atol=1e-10)
    np.testing.assert_allclose(new['camera_optical_frame'],old['wrist']@mount@optical,atol=1e-10)
    assert not np.allclose(new['camera_optical_frame'],new['wrist_camera_mount_link'])


@pytest.mark.parametrize('defect',['link','scale','reflection','nonfinite','shape','no_evidence'])
def test_unknown_mount_or_invalid_rigid_transform_is_rejected(tmp_path,defect):
    case=rig_fixture(tmp_path);mount=case[3].copy();changes={}
    if defect=='link':changes['mount_link']='invented_physical_link'
    elif defect=='scale':mount[0,0]=2.
    elif defect=='reflection':mount[0,0]=-1.
    elif defect=='nonfinite':mount[0,3]=np.nan
    elif defect=='shape':changes['T_mount_optical']=[[1.,0.],[0.,1.]]
    else:changes['evidence']=[]
    changes['T_link_mount']=mount.tolist()
    with pytest.raises(ValueError):build(tmp_path,case,**changes)


def test_rig_version_destination_is_never_overwritten(tmp_path):
    rig,case=build(tmp_path)
    frozen={p:sha(p)for p in Path(rig['path']).parent.rglob('*')if p.is_file()}
    with pytest.raises((ValueError,FileExistsError)):build(tmp_path,case)
    assert all(sha(p)==value for p,value in frozen.items())


def test_variant_preserves_mesh_subdirectories_for_native_mujoco_loader(tmp_path):
    rig,_=build(tmp_path)
    compiler=ET.parse(model_path(rig)).getroot().find('mujoco/compiler')
    assert compiler is not None
    assert compiler.get('strippath')=='false'
    assert compiler.get('discardvisual')=='false'
    assert compiler.get('fusestatic')=='false'


def test_rig_loader_rejects_modified_mesh_bytes(tmp_path):
    from real2sim_builder.evidence import load_robot_rig
    rig,_=build(tmp_path)
    root=ET.parse(model_path(rig)).getroot()
    filename=root.find("link[@name='wrist_camera_mount_link']/visual/geometry/mesh").get('filename')
    path=(model_path(rig).parent/filename).resolve();path.write_text(path.read_text()+'\n# changed\n')
    with pytest.raises(ValueError,match='(?i)sha|hash|changed|integrity'):
        load_robot_rig(rig['path'])


def test_explicit_rig_import_affects_candidate_only_and_reuses_frozen_variant(tmp_path):
    from real2sim_builder.evidence import import_robot_rig
    rig,case=build(tmp_path);project=case[0];candidate=Candidate.create(project,'camera_preview')
    working=project.root/'working/current_scene.yaml'
    before=working.read_bytes()if working.exists()else None
    first=import_robot_rig(candidate,rig['path'],joints={'hinge':.2,'gripper':.1})
    scene=candidate.scene
    assert scene['robot_model']['format']=='urdf'
    assert scene['robot_model']['joint_names']==['hinge','gripper']
    assert 'robot_link_camera_optical_frame'in scene['frames']
    assert not scene['robot_model']['mapping_verified']
    assert scene['robot_rig']['mount_status']=='estimated'
    assert scene['robot_rig']['calibration_status']=='uncalibrated'
    assert (working.read_bytes()if working.exists()else None)==before
    frozen=copy.deepcopy(scene)
    second=import_robot_rig(candidate,rig['path'],joints={'hinge':.2,'gripper':.1})
    assert candidate.scene==frozen
    assert first['physical_verified']is False and second['physical_verified']is False


def test_rig_import_cannot_replace_a_different_existing_candidate_robot(tmp_path):
    from real2sim_builder.evidence import import_robot_rig
    rig,case=build(tmp_path);candidate=Candidate.create(case[0],'bound_robot')
    # This is an explicit identity mismatch fixture, not a real device profile.
    scene=candidate.scene;scene['robot_model']={'format':'urdf','path':'input/other.urdf',
        'model_sha256':'f'*64,'joint_names':['hinge','gripper'],'mapping_verified':True}
    from real2sim_builder.files import write
    write(candidate.root/'candidate_scene.yaml',scene);before=sha(candidate.root/'candidate_scene.yaml')
    with pytest.raises(ValueError,match='(?i)existing|different|replace|identity|robot'):
        import_robot_rig(candidate,rig['path'],joints={'hinge':0.,'gripper':0.})
    assert sha(candidate.root/'candidate_scene.yaml')==before


def test_textured_rig_reference_geometry_exports_complete_material_closure(tmp_path):
    from real2sim_builder.evidence import import_robot_rig
    from real2sim_builder.export import verify_native_closure,export_revision,verify_package
    from real2sim_builder.scene import value
    from real2sim_builder.files import write
    rig,case=build(tmp_path);project=case[0];candidate=Candidate.create(project,'textured_hardware')
    import_robot_rig(candidate,rig['path'])
    scene=candidate.scene
    for asset in scene['assets'].values():
        verify_native_closure(project.root,project.root/asset['path'])
    camera=[o for o in scene['objects']if o.get('link')=='wrist_camera_mount_link']
    assert any(o['visual'].get('texture')for o in camera)
    # This synthetic inspection camera is unrelated to physical Wrist calibration.
    scene['cameras']=[{'id':'inspection','purpose':'inspection','frame':'world',
        'pose':value(np.eye(4).tolist(),'estimated'),'K':value([[100.,0,40.],[0,100.,30.],[0,0,1.]],'estimated'),
        'resolution':[80,60],'distortion':value([0.]*5,'estimated')}]
    candidate.save(scene)
    write(candidate.root/'metrics.json',{'passed':False,'input_signature':project.signature(scene)})
    output=tmp_path/'review-package'
    export_revision(project,destination=output,candidate='textured_hardware',allow_unvalidated=True)
    package=verify_package(output)
    assert sha(output/package.scene['robot']['asset_path'])==rig['model']['sha256']
    assert list(output.rglob('*.mtl')) and list(output.rglob('*.png'))
