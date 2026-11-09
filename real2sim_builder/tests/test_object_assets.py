import copy
import numpy as np
import pytest

from real2sim_builder.project import Project, Candidate
from real2sim_builder.files import sha, write


def asset_fixture(folder):
    from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf
    from PIL import Image
    folder.mkdir(parents=True)
    Image.new('RGB', (4, 4), 'red').save(folder/'texture.png')
    stage=Usd.Stage.CreateNew(str(folder/'block.usda'))
    UsdGeom.SetStageMetersPerUnit(stage, 1);UsdGeom.SetStageUpAxis(stage, 'Z')
    root=UsdGeom.Xform.Define(stage, '/Object');stage.SetDefaultPrim(root.GetPrim())
    # Real triangulated mesh, UV and PreviewSurface texture, not an opaque stub.
    import trimesh
    box=trimesh.creation.box(extents=[.03]*3)
    for name,collision in [('Visual',False),('Collision',True)]:
        mesh=UsdGeom.Mesh.Define(stage,'/Object/'+name)
        mesh.CreatePointsAttr(box.vertices.tolist());mesh.CreateFaceVertexCountsAttr([3]*len(box.faces))
        mesh.CreateFaceVertexIndicesAttr(box.faces.ravel().tolist())
        if collision:
            from pxr import UsdPhysics
            UsdPhysics.CollisionAPI.Apply(mesh.GetPrim()).CreateCollisionEnabledAttr(True)
            mesh.CreateVisibilityAttr('invisible')
        else:
            uv=UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,'vertex')
            uv.Set([(0.,0.)]*len(box.vertices))
            material=UsdShade.Material.Define(stage,'/Object/Material')
            surface=UsdShade.Shader.Define(stage,'/Object/Material/Surface');surface.CreateIdAttr('UsdPreviewSurface')
            texture=UsdShade.Shader.Define(stage,'/Object/Material/Image');texture.CreateIdAttr('UsdUVTexture')
            texture.CreateInput('file',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath('texture.png'))
            surface.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(),'rgb')
            surface.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.4)
            material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(),'surface')
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
    stage.GetRootLayer().Save()
    return folder/'block.usda'


def test_register_reuse_instances_remove_and_portable_export(tmp_path):
    from real2sim_builder.object_assets import register_object_asset, list_object_assets, instance_operation
    from real2sim_builder.export import export_revision,verify_package
    from test_builder_export import legacy_scene
    from pxr import Usd
    p=Project.create(tmp_path/'projects','assets');p.save_scene(legacy_scene())
    original=asset_fixture(tmp_path/'source');before={f.name:sha(f) for f in original.parent.iterdir()}
    asset=register_object_asset(p,original,asset_id='red_block',dimensions={'value':[.03]*3,'provenance':'measured','evidence':['caliper']})
    assert asset['collision_status']=='AUTHORED_UNVALIDATED'
    assert register_object_asset(p,original,asset_id='red_block',dimensions=asset['dimensions'])==asset
    assert len(list_object_assets(p))==1
    c=Candidate.create(p,'reuse');untouched=copy.deepcopy(c.scene['objects'])
    for name,x in [('block2',.15),('block3',-.15)]:
        pose=np.eye(4);pose[:3,3]=[x,0,.03]
        c.edit([instance_operation(p,asset['manifest'],name,pose=pose.tolist())])
    assert c.scene['objects'][:2]==untouched
    added=c.scene['objects'][2:];assert added[0]['object_asset']==added[1]['object_asset']
    c.edit([{'op':'remove_object','id':'block3'}]);assert len(list_object_assets(p))==1
    write(c.root/'metrics.json',{'passed':False,'input_signature':p.signature(c.scene)})
    target=tmp_path/'revision';export_revision(p,destination=target,candidate='reuse',allow_unvalidated=True)
    original.parent.rename(tmp_path/'source_unavailable')
    package=verify_package(target)
    stage=Usd.Stage.Open(str(target/package.scene['engines']['isaac']['asset_path']))
    assert stage.GetPrimAtPath('/Scene/block2/Asset/Visual')
    assert stage.GetPrimAtPath('/Scene/block2/Asset').HasAuthoredReferences()
    assert {f.name:sha(f) for f in (tmp_path/'source_unavailable').iterdir()}==before
    import mujoco
    model=mujoco.MjModel.from_xml_path(str(target/package.scene['engines']['mujoco']['asset_path']))
    data=mujoco.MjData(model)
    for _ in range(5):mujoco.mj_step(model,data)
    assert np.isfinite(data.qpos).all()


def test_asset_rejects_unknown_units_broken_texture_and_mutation(tmp_path):
    from real2sim_builder.object_assets import register_object_asset,instance_operation
    from pxr import UsdGeom,Usd
    p=Project.create(tmp_path/'projects','invalid');source=asset_fixture(tmp_path/'source')
    stage=Usd.Stage.Open(str(source));UsdGeom.SetStageMetersPerUnit(stage,.01);stage.GetRootLayer().Save()
    with pytest.raises(ValueError,match='meter'):register_object_asset(p,source,asset_id='bad')
    UsdGeom.SetStageMetersPerUnit(stage,1);stage.GetRootLayer().Save();(source.parent/'texture.png').unlink()
    with pytest.raises(ValueError):register_object_asset(p,source,asset_id='bad')
    assert not list((p.root/'input/object_assets').glob('*/manifest.json')) if (p.root/'input/object_assets').exists() else True


def test_measurements_do_not_create_primitive_visuals(tmp_path):
    from real2sim_builder.initialization import measured_geometry
    from real2sim_builder.scene import empty
    scene=measured_geometry(empty('new'),[{'id':'banana','kind':'mesh','dimensions_m':[.2,.05,.04],'evidence':['ruler']}])
    obj=scene['objects'][0]
    assert obj['visual']['type']=='unknown' and obj['dimensions']['provenance']=='measured'
    assert obj['pose']['value'] is None


def test_imported_convex_mesh_settles_on_table_without_deep_penetration(tmp_path):
    from real2sim_builder.object_assets import register_object_asset,instance_operation
    from real2sim_builder.scene import value
    from real2sim_builder.exporters import mjcf
    from test_builder_export import legacy_scene
    import mujoco
    p=Project.create(tmp_path/'projects','mesh contact');p.save_scene(legacy_scene());c=Candidate.create(p,'mesh')
    record=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='block')
    pose=np.eye(4);pose[:3,3]=[.15,0,.06]
    c.edit([instance_operation(p,record['manifest'],'added_block',pose=pose.tolist())])
    scene=c.scene;scene['objects'][-1]['physics']={'mass_kg':value(.05,'estimated'),'friction':value(.6,'estimated')}
    path=tmp_path/'mesh.xml';mjcf.export(scene,p.root,path);model=mujoco.MjModel.from_xml_path(str(path));data=mujoco.MjData(model)
    for _ in range(350):mujoco.mj_step(model,data)
    body=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'added_block')
    assert abs(data.xpos[body,2]-.015)<.001
    assert np.max(abs(data.qvel))<.1


def test_unready_isaac_probe_replaces_old_report_without_loading_kit(tmp_path):
    from real2sim_builder.validation import physics_probe
    from test_builder_export import legacy_scene
    from real2sim_builder.files import read
    p=Project.create(tmp_path/'projects','unready');folder=p.root/'scratch/probe';folder.mkdir()
    write(folder/'physics-isaac.json',{'status':'old_success'})
    result=physics_probe(p,legacy_scene(),folder,engine='isaac')
    assert result['status']=='NEEDS_MORE_DATA'
    assert read(folder/'physics-isaac.json')==result


def test_workspace_library_is_shared_but_scenes_and_exports_are_independent(tmp_path):
    from real2sim_builder.object_assets import register_object_asset,list_object_assets,instance_operation
    from real2sim_builder.export import export_revision,verify_package
    from real2sim_builder.scene import local_path
    from test_builder_export import legacy_scene
    from real2sim_builder.evidence import save_scene_memo
    from real2sim_builder.files import read
    workspace=tmp_path/'workspace';a=Project.create(workspace/'scenes','Scene A');b=Project.create(workspace/'scenes','Scene B')
    for p in(a,b):p.save_scene(legacy_scene())
    note=tmp_path/'note.md';note.write_text('Scene A cups');save_scene_memo(a,note.read_bytes().decode('utf-8'))
    record=register_object_asset(a,asset_fixture(tmp_path/'source'),asset_id='paper_cup')
    manifest=local_path(a.root,record['manifest'])
    assert manifest.is_relative_to(workspace/'object_assets')
    assert not(a.root/'input/object_assets').exists()and not(b.root/'input/object_assets').exists()
    assert list_object_assets(b)==[record]
    ca=Candidate.create(a,'two');cb=Candidate.create(b,'one')
    for name,x in[('cup1',.1),('cup2',-.1)]:
        pose=np.eye(4);pose[:3,3]=[x,0,.03];ca.edit([instance_operation(a,record['manifest'],name,pose=pose.tolist())])
    pose=np.eye(4);pose[:3,3]=[.3,0,.03];cb.edit([instance_operation(b,record['manifest'],'cup1',pose=pose.tolist())])
    ca.evaluate(engine='mujoco');cb.evaluate(engine='mujoco')
    before={f:sha(f)for f in a.root.rglob('*')if f.is_file()}
    export_revision(b,destination=b.root/'exports/v1',candidate='one',allow_unvalidated=True)
    assert all(sha(f)==h for f,h in before.items())
    export_revision(a,destination=a.root/'exports/v1',candidate='two',allow_unvalidated=True)
    before={f:sha(f)for f in a.root.rglob('*')if f.is_file()}
    frozen={f:sha(f)for f in(a.root/'exports/v1').rglob('*')if f.is_file()}
    old=sha(manifest)
    newer=register_object_asset(b,tmp_path/'source/block.usda',asset_id='paper_cup',generation_id='request_second')
    assert newer['version']==record['version']and newer['content_sha256']==record['content_sha256']and sha(manifest)==old
    assert ca.scene['objects'][-1]['object_asset']['version']==record['version']
    cb.edit([{**instance_operation(b,newer['manifest'],'cup1',pose=pose.tolist()),'op':'use_object_asset'}])
    assert all(sha(f)==h for f,h in frozen.items())
    assert all(sha(f)==h for f,h in before.items())
    assert not b.evidence.get('briefs')
    (workspace/'object_assets').rename(workspace/'unavailable_library')
    assert verify_package(a.root/'exports/v1')and verify_package(b.root/'exports/v1')


def test_workspace_asset_resolver_rejects_escape_and_symlink(tmp_path):
    from real2sim_builder.object_assets import register_object_asset
    from real2sim_builder.scene import local_path
    p=Project.create(tmp_path/'scenes','paths')
    record=register_object_asset(p,asset_fixture(tmp_path/'source'),asset_id='block')
    with pytest.raises(ValueError):local_path(p.root,'../../object_assets/block/'+record['version']+'/../../outside')
    secret=tmp_path/'private.txt';secret.write_text('not an asset')
    alias=tmp_path/'object_assets/block'/record['version']/'alias.txt';alias.symlink_to(secret)
    with pytest.raises(ValueError):local_path(p.root,'../../object_assets/block/'+record['version']+'/alias.txt')


def test_legacy_library_publish_preserves_version_and_never_retargets_scene(tmp_path):
    from real2sim_builder.object_assets import register_object_asset,verify_object_asset,list_object_assets,instance_operation,publish_object_asset
    from real2sim_builder.scene import local_path
    from real2sim_builder.files import read
    import shutil
    p=Project.create(tmp_path/'scenes','legacy');source=asset_fixture(tmp_path/'source')
    asset=register_object_asset(p,source,asset_id='cup');shared=local_path(p.root,asset['manifest']).parent
    legacy=p.root/'input/object_assets'/asset['asset_id']/asset['version'];shutil.copytree(shared,legacy)
    old={**asset,'manifest':legacy.relative_to(p.root).as_posix()+'/manifest.json'};write(legacy/'manifest.json',old)
    # Simulate an existing Project whose only Library is still local.
    shutil.rmtree(p.workspace/'object_assets')
    verify_object_asset(p,old);c=Candidate.create(p,'legacy')
    c.edit([instance_operation(p,old['manifest'],'cup')])
    original={f:sha(f)for f in p.root.rglob('*')if f.is_file()}
    published=publish_object_asset(p,old['manifest'])
    assert published['version']==old['version']and published['files']==old['files']
    assert len(list_object_assets(p))==2
    assert all(sha(f)==h for f,h in original.items())
    assert publish_object_asset(p,old['manifest'])==published
    from real2sim_builder.cli import main
    assert main(['object-asset',str(p.root),'publish','--manifest',old['manifest']])==0
    assert c.scene['assets'][c.scene['objects'][0]['object_asset']['entry_asset']]['path'].startswith('input/object_assets/')


def test_workspace_registration_lock_is_shared_across_scene_processes(tmp_path):
    from real2sim_builder.object_assets import library_write,register_object_asset,list_object_assets
    import subprocess,sys
    a=Project.create(tmp_path/'scenes','A');b=Project.create(tmp_path/'scenes','B');source=asset_fixture(tmp_path/'source')
    code='''import sys
from real2sim_builder.project import Project
from real2sim_builder.object_assets import register_object_asset
try:register_object_asset(Project(sys.argv[1]),sys.argv[2],asset_id="cup")
except RuntimeError as error:
 assert "Library is busy"in str(error);print("shared lock rejected second writer")
else:raise AssertionError("concurrent registration must not pass ownership lock")
'''
    with library_write(a):
        result=subprocess.run([sys.executable,'-B','-c',code,str(b.root),str(source)],capture_output=True,text=True,timeout=20)
        assert result.returncode==0,result.stdout+result.stderr
        assert not list((a.workspace/'object_assets').glob('*/*/manifest.json'))
    first=register_object_asset(a,source,asset_id='cup');second=register_object_asset(b,source,asset_id='cup')
    assert first==second and len(list_object_assets(a))==1


def test_clone_into_another_workspace_publishes_only_referenced_asset_versions(tmp_path):
    from real2sim_builder.project import clone_project
    from real2sim_builder.object_assets import register_object_asset,instance_operation,list_object_assets
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'first/scenes','source');p.save_scene(legacy_scene())
    source=asset_fixture(tmp_path/'asset');used=register_object_asset(p,source,asset_id='used')
    register_object_asset(p,source,asset_id='unused')
    c=Candidate.create(p,'one');pose=np.eye(4);pose[2,3]=.03
    c.edit([instance_operation(p,used['manifest'],'cup',pose=pose.tolist())]);p.save_scene(c.scene)
    before={f:sha(f)for f in p.root.rglob('*')if f.is_file()}
    copied=clone_project(p.root,tmp_path/'second/scenes/cloned')
    assert [a['asset_id']for a in list_object_assets(copied)]==['used']
    assert copied.signature()['files']and all(sha(f)==h for f,h in before.items())


def test_malformed_unused_manifest_is_a_catalogue_item_error(tmp_path):
    from real2sim_builder.object_assets import list_object_assets
    p=Project.create(tmp_path/'scenes','malformed unused metadata')
    bad=p.workspace/'object_assets/unused'/'v001'/'manifest.json'
    bad.parent.mkdir(parents=True);bad.write_text('{ unclosed: [')
    rows=list_object_assets(p)
    assert len(rows)==1 and rows[0]['asset_id']=='unused'and rows[0]['error']


def test_unrelated_broken_asset_is_catalogued_without_blocking_selected_asset(tmp_path):
    from real2sim_builder.object_assets import list_object_assets,instance_operation,register_object_asset
    from real2sim_builder.authoring import modeling_tasks
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.files import write
    p=Project.create(tmp_path/'scenes','selective');c=Candidate.create(p,'draft')
    good=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='good')
    broken=p.workspace/'object_assets/broken'/'v001'/'manifest.json';write(broken,{'invalid':'metadata'})
    catalogue=list_object_assets(p)
    assert len(catalogue)==2 and next(r for r in catalogue if r['asset_id']=='broken')['error']
    instance_operation(p,good['manifest'],'block')
    modeling_tasks(c,{'objects':{'block':{'prompt':'box','asset_manifest':good['manifest']}}},{})
    (p.root/good['manifest']).parent.joinpath(good['entry']).write_bytes(b'corrupt')
    import pytest
    with pytest.raises(ValueError):instance_operation(p,good['manifest'],'block')
def test_partial_memo_dimension_constrains_asset_without_marking_other_axes_measured(tmp_path):
    import pytest
    from real2sim_builder.project import Project
    from real2sim_builder.object_assets import register_object_asset
    p=Project.create(tmp_path/'scenes','partial')
    path=asset_fixture(tmp_path/'asset')
    original=register_object_asset(p,path,asset_id='unconstrained')
    height=original['dimensions']['value'][2]
    declared={'value':[None,None,height],'provenance':'measured','evidence':['Scene Memo: height']}
    asset=register_object_asset(p,path,asset_id='partial',dimensions=declared)
    assert asset['dimensions']['provenance']=='estimated'
    assert asset['dimensions']['constraints']==declared
    with pytest.raises(ValueError,match='bounds disagree'):
        register_object_asset(p,path,asset_id='wrong_height',dimensions={**declared,'value':[None,None,height*2]})


def test_readable_asset_versions_separate_content_identity_from_storage(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.object_assets import register_object_asset
    p=Project.create(tmp_path,'Readable assets')
    source=tmp_path/'cube.usda'
    source.write_text('''#usda 1.0
(
 defaultPrim="Cube"
 metersPerUnit=1
 upAxis="Z"
)
def Xform "Cube" {
 def Mesh "Mesh" {
  point3f[] points=[(0,0,0),(1,0,0),(0,1,0),(0,0,1)]
  int[] faceVertexCounts=[3,3,3,3]
  int[] faceVertexIndices=[0,2,1,0,1,3,1,2,3,2,0,3]
 }
}
''')
    first=register_object_asset(p,source,asset_id='cube')
    assert first['version']=='v001'and len(first['content_sha256'])==64
    again=register_object_asset(p,source,asset_id='cube',generation_id='a_new_request')
    assert again['version']=='v001'
    source.write_text(source.read_text().replace('(1,0,0)','(2,0,0)'))
    second=register_object_asset(p,source,asset_id='cube')
    assert second['version']=='v002'and second['content_sha256']!=first['content_sha256']
