"""Native USDA authority, portable derivatives and first-use semantic integrity."""
import copy
from pathlib import Path
import numpy as np
import pytest
from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import read,write,sha
from real2sim_builder.object_assets import register_object_asset,verify_object_asset,instance_operation
from real2sim_builder.asset_view import load_asset_view
from test_object_assets import asset_fixture


def _l_shape(folder,rotation,orientation):
    from pxr import Usd,UsdGeom,UsdShade,Sdf
    folder.mkdir();stage=Usd.Stage.CreateNew(str(folder/'l.usda'))
    UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z')
    root=UsdGeom.Xform.Define(stage,'/Object');stage.SetDefaultPrim(root.GetPrim())
    polygon=np.array([[0,0],[2,0],[2,1],[1,1],[1,2],[0,2]],float)
    points=np.r_[np.c_[polygon,np.zeros(6)],np.c_[polygon,np.full(6,.1)]]
    top=(np.roll(np.arange(6),rotation)+6).tolist()
    faces=[list(range(5,-1,-1)),top]+[[i,(i+1)%6,(i+1)%6+6,i+6]for i in range(6)]
    mesh=UsdGeom.Mesh.Define(stage,'/Object/Visual');mesh.CreatePointsAttr(points.tolist())
    mesh.CreateFaceVertexCountsAttr([len(f)for f in faces]);mesh.CreateFaceVertexIndicesAttr([i for f in faces for i in f])
    mesh.CreateOrientationAttr(orientation)
    uv=UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,'faceVarying')
    uv.Set([tuple(points[i,:2]/2)for f in faces for i in f])
    mat=UsdShade.Material.Define(stage,'/Object/TopMaterial')
    shader=UsdShade.Shader.Define(stage,'/Object/TopMaterial/Surface');shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set((.1,.2,.8))
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
    subset=UsdGeom.Subset.Define(stage,'/Object/Visual/Top');subset.CreateElementTypeAttr('face');subset.CreateFamilyNameAttr('materialBind');subset.CreateIndicesAttr([1])
    UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(mat)
    stage.GetRootLayer().Save();return folder/'l.usda'


@pytest.mark.parametrize('rotation',[0,1,3])
@pytest.mark.parametrize('orientation',['rightHanded','leftHanded'])
def test_concave_native_polygon_area_coverage_uv_material_and_orientation(tmp_path,rotation,orientation):
    project=Project.create(tmp_path/'projects','concave');path=_l_shape(tmp_path/'source',rotation,orientation);original=sha(path)
    record=register_object_asset(project,path,asset_id='l_shape')
    view=load_asset_view(project,record['manifest']);area=0.;count=0
    for mesh in view['meshes']:
        vertices=np.asarray(mesh['vertices']);faces=np.asarray(mesh['faces']);uv=np.asarray(mesh['uv'])
        for face in faces:
            p=vertices[face]
            if not np.allclose(p[:,2],.1):continue
            cross=np.cross(p[1]-p[0],p[2]-p[0])[2];area+=abs(cross)/2;count+=1
            assert cross>0 if orientation=='rightHanded'else cross<0
            center=p.mean(axis=0)
            assert not(center[0]>1 and center[1]>1),'Triangle covers the missing L corner'
            np.testing.assert_allclose(uv[face],p[:,:2]/2)
            np.testing.assert_allclose(mesh['color'],[.1,.2,.8],atol=1e-7)
    assert count==4 and area==pytest.approx(3.)
    assert sha(path)==original and verify_object_asset(project,record)==record


@pytest.mark.parametrize('field',['collision_pose','visual_pose','visual_type','material','entry'])
@pytest.mark.parametrize('legacy',[False,True])
def test_first_binding_rejects_manifest_semantic_tampering_with_same_dependency_bytes(tmp_path,field,legacy):
    project=Project.create(tmp_path/'projects','semantic');record=register_object_asset(project,asset_fixture(tmp_path/'source'),asset_id='block')
    if legacy:
        record.pop('semantic_sha256');write(project.root/record['manifest'],record)
        assert verify_object_asset(project,record)==record
    path=project.root/record['manifest'];before={f:sha(path.parent/f)for f in record['files']};old_content=record['content_sha256']
    changed=copy.deepcopy(record)
    if field=='collision_pose':changed['collision'][0]['pose'][0][3]=2.
    elif field=='visual_pose':changed['visual'][0]['pose'][1][3]=3.
    elif field=='visual_type':changed['visual'][0]['type']='box'
    elif field=='material':changed['visual'][0]['color']=[0.,1.,0.]
    else:changed['entry']='visual_0.obj'
    write(path,changed)
    assert changed['content_sha256']==old_content and before=={f:sha(path.parent/f)for f in record['files']}
    with pytest.raises(ValueError):verify_object_asset(project,changed)
    with pytest.raises(ValueError):instance_operation(project,record['manifest'],'new_object')


def test_legacy_asset_schema_binding_and_portable_export_remain_readonly(tmp_path):
    from test_builder_export import legacy_scene
    from real2sim_builder.export import export_revision,verify_package
    project=Project.create(tmp_path/'projects','legacy');project.save_scene(legacy_scene())
    record=register_object_asset(project,asset_fixture(tmp_path/'source'),asset_id='legacy')
    record.pop('semantic_sha256');write(project.root/record['manifest'],record)
    assert record['schema']=='real2sim.object-asset/1'
    path=project.root/record['manifest'];original=path.read_bytes();files={f:sha(path.parent/f)for f in record['files']}
    candidate=Candidate.create(project,'legacy');candidate.edit([instance_operation(project,record['manifest'],'copy',pose=np.eye(4).tolist())])
    write(candidate.root/'metrics.json',{'passed':False,'input_signature':project.signature(candidate.scene)})
    export_revision(project,destination=tmp_path/'package',candidate='legacy',allow_unvalidated=True)
    verify_package(tmp_path/'package')
    assert path.read_bytes()==original and files=={f:sha(path.parent/f)for f in record['files']}


def test_existing_convex_nonplanar_quad_keeps_the_original_fan():
    from real2sim_builder.object_assets import _face_triangles
    points=np.array([[0,0,0],[1,0,.1],[1,1,0],[0,1,.1]])
    assert _face_triangles(points)==[(0,1,2),(0,2,3)]


def test_existing_zero_area_cap_faces_remain_zero_area_and_do_not_hide_self_intersection():
    from real2sim_builder.object_assets import _face_triangles
    points=np.array([[0,0,.001],[0,0,.001],[0,0,0],[0,0,0]])
    assert _face_triangles(points)==[(0,1,2),(0,2,3)]
    with pytest.raises(ValueError):_face_triangles(np.array([[0,0,0],[1,1,0],[0,1,0],[1,0,0]]))
