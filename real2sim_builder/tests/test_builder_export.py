"""Official native representations; immutable package publication and closure."""
import copy,json,shutil
from pathlib import Path
import numpy as np,pytest
from scene_contract.package import load_scene,SceneError


def legacy_scene():
    from real2sim_builder.project import empty,value
    scene=empty('Measured workspace')
    for name,role,xyz,size in [('table','support_surface',[0,0,-.02],[1,.8,.04]),('block','manipulable_object',[0,0,.03],[.06]*3)]:
        t=np.eye(4);t[:3,3]=xyz
        scene['objects'].append(dict(id=name,role=role,frame='world',pose=value(t.tolist(),'measured'),dimensions=value(size,'measured'),visual={'type':'box'},collision={'type':'box'},color=value([.5,.2,.1],'measured'),physics={'mass_kg':value(None),'friction':value(.1,'measured')}))
    eye=np.array([.6,.4,.5]);f=-eye/np.linalg.norm(eye);right=np.cross(f,[0,0,1]);right/=np.linalg.norm(right);down=np.cross(f,right);t=np.eye(4);t[:3,:3]=np.column_stack([right,down,f]);t[:3,3]=eye
    scene['cameras'].append(dict(id='side',frame='world',pose=value(t.tolist(),'calibrated'),K=value([[160.,0,80.],[0,160.,60.],[0,0,1]],'calibrated'),resolution=[160,120],distortion=value([0.]*5,'calibrated')))
    return scene


def test_original_native_exporters_preserve_body_pose_camera_units(tmp_path):
    from real2sim_builder.exporters import mjcf,usd
    scene=legacy_scene();mjcf.export(scene,tmp_path,tmp_path/'scene.xml');usd.export(scene,tmp_path,tmp_path/'scene.usda')
    import mujoco
    model=mujoco.MjModel.from_xml_path(str(tmp_path/'scene.xml'));assert model.ngeom==4
    from pxr import Usd,UsdGeom
    stage=Usd.Stage.Open(str(tmp_path/'scene.usda'));assert UsdGeom.GetStageMetersPerUnit(stage)==1 and UsdGeom.GetStageUpAxis(stage)=='Z'
    pose=np.asarray(UsdGeom.Xformable(stage.GetPrimAtPath('/Scene/block')).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
    np.testing.assert_allclose(pose,scene['objects'][1]['pose']['value'],rtol=0,atol=1e-12)


def test_recursive_native_assets_are_localized_without_touching_originals(tmp_path):
    from real2sim_builder.export import copy_native_asset,verify_native_closure
    original=tmp_path/'original';original.mkdir();(original/'mesh.bin').write_bytes(b'meshbytes')
    (original/'child.usda').write_text('#usda 1.0\ndef Xform "Child" {\n asset provenance = @mesh.bin@\n}\n')
    (original/'root.usda').write_text('#usda 1.0\n( subLayers = [@child.usda@] )\ndef Xform "Root" {}\n')
    before={p:p.read_bytes() for p in original.iterdir()}
    package=tmp_path/'package';package.mkdir();copied=copy_native_asset(original/'root.usda',package)
    original.rename(tmp_path/'unavailable')
    closure=verify_native_closure(package,copied)
    assert len(closure)==3 and all(p.is_relative_to(package) for p in closure)
    assert {tmp_path/'unavailable'/p.name:b for p,b in before.items()}=={p:p.read_bytes() for p in (tmp_path/'unavailable').iterdir()}


def test_explicit_sdk_material_and_relative_mdl_import_are_part_of_closure(tmp_path):
    from real2sim_builder.export import copy_native_asset,verify_native_closure
    source=tmp_path/'source';sdk=tmp_path/'sdk';source.mkdir();sdk.mkdir()
    (source/'root.usda').write_text('#usda 1.0\ndef Xform "Root" {\n asset material = @Shader.mdl@\n}\n')
    (sdk/'Shader.mdl').write_text('mdl 1.7;\nimport ::math::*;\nimport Child::*;\n')
    (sdk/'Child.mdl').write_text('mdl 1.7;\n')
    out=tmp_path/'package';target=copy_native_asset(source/'root.usda',out,resolutions={'Shader.mdl':sdk/'Shader.mdl'})
    shutil.rmtree(source);shutil.rmtree(sdk)
    assert {f.name for f in verify_native_closure(out,target)}=={'root.usda','Shader.mdl','Child.mdl'}


def test_xml_include_mesh_paths_relative_to_their_native_parent_are_packaged(tmp_path):
    from real2sim_builder.export import copy_native_asset,verify_native_closure
    original=tmp_path/'original';(original/'sub').mkdir(parents=True);(original/'geometry').mkdir()
    (original/'geometry/mesh.stl').write_bytes(b'opaque triangle file')
    (original/'sub/child.xml').write_text('<mujocoinclude><asset><mesh name="x" file="geometry/mesh.stl"/></asset></mujocoinclude>')
    (original/'root.xml').write_text('<mujoco><include file="sub/child.xml"/></mujoco>')
    package=tmp_path/'package';package.mkdir();target=copy_native_asset(original/'root.xml',package)
    shutil.rmtree(original)
    assert len(verify_native_closure(package,target))==2


def test_missing_or_remote_native_reference_is_not_silently_ignored(tmp_path):
    from real2sim_builder.export import copy_native_asset
    for text in ['<mujoco><include file="missing.xml"/></mujoco>','<mujoco><include file="https://example.invalid/file"/></mujoco>']:
        source=tmp_path/'original.xml';source.write_text(text)
        with pytest.raises(ValueError):copy_native_asset(source,tmp_path/'package')


def test_relative_model_paths_preserve_calibration_model_bytes(tmp_path):
    from real2sim_builder.export import copy_native_asset,verify_native_closure
    root=tmp_path/'original';(root/'urdf').mkdir(parents=True);(root/'meshes').mkdir()
    (root/'meshes/finger.stl').write_bytes(b'finger')
    urdf=root/'urdf/model.urdf';urdf.write_text('<robot name="r"><link name="base"><visual><geometry><mesh filename="../meshes/finger.stl"/></geometry></visual></link></robot>')
    data=urdf.read_bytes();out=tmp_path/'package';out.mkdir();target=copy_native_asset(urdf,out)
    assert target.read_bytes()==data
    assert len(verify_native_closure(out,target))==2


def project_fixture(tmp_path):
    from real2sim_builder.project import Project,write
    p=Project.create(tmp_path/'projects','workspace');p.save_scene(legacy_scene())
    write(p.root/'working/validation/report.json',{'passed':False,'input_signature':p.signature(),'scope':'synthetic unvalidated review'})
    return p


def test_revision_publish_move_and_hash_closure(tmp_path):
    from real2sim_builder.export import export_revision,verify_package
    p=project_fixture(tmp_path);out=tmp_path/'exports/r1'
    identity=export_revision(p,destination=out,allow_unvalidated=True)
    package=load_scene(out/'scene.json',expected=identity)
    assert package.scene['validation']['physics']=='UNVALIDATED'
    assert package.scene['objects']['block']['task_geometry']['dimensions_m']==(.06,)*3
    moved=tmp_path/'moved';out.rename(moved)
    assert verify_package(moved).identity==identity
    assert set(package.scene['engines'])=={'isaac','mujoco'}
    with pytest.raises(ValueError):export_revision(p,destination=moved,allow_unvalidated=True)
    with pytest.raises(ValueError):export_revision(p,destination=tmp_path/'validated-only')


def test_execution_robot_usd_is_packaged_with_its_native_collision_dependencies(tmp_path):
    from real2sim_builder.export import export_revision,verify_package
    from pxr import Usd
    p=project_fixture(tmp_path);source=tmp_path/'native';source.mkdir()
    (source/'mesh.usda').write_text('#usda 1.0\ndef Xform "Geometry" {}\n')
    robot=source/'robot.usda';robot.write_text('#usda 1.0\n( defaultPrim = "Robot" )\ndef Xform "Robot" ( references = @mesh.usda@</Geometry> ) {}\n')
    before={f:f.read_bytes() for f in source.iterdir()}
    out=tmp_path/'revision'
    identity=export_revision(p,destination=out,allow_unvalidated=True,isaac_robot_asset=robot)
    source.rename(tmp_path/'unavailable');moved=tmp_path/'moved';out.rename(moved)
    package=verify_package(moved);binding=package.scene['robot']['bindings']['isaac']
    assert package.identity==identity
    assert Usd.Stage.Open(str(moved/binding['asset_path'])).GetDefaultPrim()
    assert (moved/binding['asset_path']).read_bytes()==before[robot]
    assert all((tmp_path/'unavailable'/f.name).read_bytes()==data for f,data in before.items())


def test_failed_export_and_stale_signature_never_publish(tmp_path,monkeypatch):
    from real2sim_builder import export as e
    p=project_fixture(tmp_path)
    def fail(*a,**k):raise OSError('disk full')
    with monkeypatch.context() as patch:
        patch.setattr(e.usd,'export',fail)
        with pytest.raises(OSError):e.export_revision(p,destination=tmp_path/'broken',allow_unvalidated=True)
    assert not (tmp_path/'broken').exists()
    scene=p.scene;scene['name']='changed';p.save_scene(scene)
    with pytest.raises(ValueError):e.export_revision(p,destination=tmp_path/'stale',allow_unvalidated=True)
    assert not (tmp_path/'stale').exists()


def collision_fixture(tmp_path):
    from real2sim_builder.project import sha,write
    source=tmp_path/'collision-input';source.mkdir();mesh=source/'finger.stl';mesh.write_bytes(b'original-finger-mesh');usd_source=source/'robot.usda';usd_source.write_text('#usda 1.0\ndef Xform "Robot" {}\n')
    finger=source/'finger_convex_parts.json';pads=source/'usd_contact_pads.json'
    write(finger,{'schema':'so101.finger-convex-parts/1','meshes':[{'link':'gripper','collision_index':0,'mesh':mesh.name,'source_sha256':sha(mesh),'parts':[]}]})
    write(pads,{'schema':'so101.usd-contact-pads/1','source_sha256':{usd_source.name:sha(usd_source)},'pads':[]})
    return [finger,pads,mesh,usd_source]


def test_collision_loader_uses_packaged_relative_paths_and_exact_source_identity(tmp_path):
    from real2sim_builder.export import _collision_binding,copy_native_asset
    from real2sim_builder.exporters.mjcf import load_robot_collision
    files=collision_fixture(tmp_path);root=tmp_path/'package';root.mkdir();copied={}
    for file in files:copy_native_asset(file,root,copied=copied)
    binding=_collision_binding(root,copied);before={p.name:p.read_bytes() for p in files};shutil.rmtree(files[0].parent)
    moved=tmp_path/'moved';root.rename(moved)
    loaded=load_robot_collision(moved,binding)
    assert loaded['finger_convex_parts']['meshes'][0]['link']=='gripper'
    target=moved/binding['finger_convex_parts']['sources']['finger.stl']['asset_path'];target.write_bytes(b'changed')
    with pytest.raises(ValueError):load_robot_collision(moved,binding)


def test_collision_source_hash_omission_is_rejected_even_if_auxiliary_json_present(tmp_path):
    from real2sim_builder.export import _collision_binding,copy_native_asset
    files=collision_fixture(tmp_path);root=tmp_path/'package';root.mkdir();copied={}
    for file in files[:2]:copy_native_asset(file,root,copied=copied)
    with pytest.raises(ValueError):_collision_binding(root,copied)


def test_missing_historical_model_dependencies_can_only_be_explicit_identity_evidence(tmp_path):
    from real2sim_builder.export import export_revision
    p=project_fixture(tmp_path);model=tmp_path/'historical.urdf';model.write_text('<robot name="evidence"><mesh filename="missing.stl"/></robot>')
    out=tmp_path/'export'
    identity=export_revision(p,destination=out,allow_unvalidated=True,required_files=[{'source':str(model),'usage':'identity_evidence'}])
    package=load_scene(out/'scene.json',expected=identity)
    assert any(f.sha256==__import__('hashlib').sha256(model.read_bytes()).hexdigest() and f.path.endswith('.source') for f in package.files)


def test_nested_mjcf_includes_follow_main_file_directory_and_load_after_move(tmp_path):
    from real2sim_builder.export import copy_native_asset,verify_native_closure
    import mujoco
    source=tmp_path/'input';(source/'sub').mkdir(parents=True)
    (source/'root.xml').write_text('<mujoco><include file="sub/a.xml"/></mujoco>')
    (source/'sub/a.xml').write_text('<mujocoinclude><include file="sub/b.xml"/></mujocoinclude>')
    (source/'sub/b.xml').write_text('<mujocoinclude><worldbody><body name="block"><geom type="box" size=".03 .02 .01"/></body></worldbody></mujocoinclude>')
    original=mujoco.MjModel.from_xml_path(str(source/'root.xml'))
    output=tmp_path/'package';output.mkdir();target=copy_native_asset(source/'root.xml',output)
    shutil.rmtree(source)
    model=mujoco.MjModel.from_xml_path(str(target));assert model.ngeom==original.ngeom
    np.testing.assert_array_equal(model.geom_size,original.geom_size)
    verify_native_closure(output,target)


def test_replacement_engine_asset_cannot_reuse_unrelated_generated_bindings(tmp_path):
    from real2sim_builder.export import export_revision
    p=project_fixture(tmp_path);other=tmp_path/'other.xml';other.write_text('<mujoco><worldbody/></mujoco>')
    with pytest.raises(ValueError):export_revision(p,destination=tmp_path/'wrong',engine_sources={'mujoco':other},allow_unvalidated=True)
    assert not (tmp_path/'wrong').exists()


def test_nested_manifest_named_dependency_is_registered(tmp_path):
    from real2sim_builder.export import export_revision
    p=project_fixture(tmp_path);source=tmp_path/'manifest.json';source.write_text('{"identity":"required parameters"}')
    out=tmp_path/'export';export_revision(p,destination=out,required_files=[source],allow_unvalidated=True)
    package=load_scene(out/'scene.json')
    assert any(f.path.startswith('assets/') and f.path.endswith('/manifest.json') for f in package.files)


def test_shared_model_dependency_preserves_both_model_byte_identities(tmp_path):
    from real2sim_builder.export import copy_native_asset
    source=tmp_path/'source';(source/'urdf').mkdir(parents=True);(source/'meshes').mkdir()
    (source/'meshes/finger.stl').write_bytes(b'exact shared geometry')
    models=[]
    for name in ('original','calibrated'):
        model=source/'urdf'/(name+'.urdf')
        model.write_text('<robot name="'+name+'"><link name="base"><visual><geometry><mesh filename="../meshes/finger.stl"/></geometry></visual></link></robot>')
        models.append(model)
    copied={};out=tmp_path/'package'
    for model in models:
        target=copy_native_asset(model,out,copied=copied)
        assert target.read_bytes()==model.read_bytes()


def test_nonidentity_legacy_world_is_a_child_of_canonical_world(tmp_path):
    from real2sim_builder.project import write,world_pose
    from real2sim_builder.export import export_revision,verify_package
    from scene_contract.transforms import resolve_transform
    p=project_fixture(tmp_path);scene=p.scene
    scene['frames']['world']['transform']['value'][0][3]=.37;p.save_scene(scene)
    write(p.root/'working/validation/report.json',{'passed':False,'input_signature':p.signature()})
    export_revision(p,destination=tmp_path/'package',allow_unvalidated=True)
    package=verify_package(tmp_path/'package')
    for obj in scene['objects']:
        np.testing.assert_array_equal(resolve_transform(package.scene['frames'],source=package.scene['objects'][obj['id']]['frame_id'],target='world'),world_pose(scene,obj))


def test_postpublish_directory_fsync_error_reports_unknown_without_deleting_package(tmp_path,monkeypatch):
    import stat
    from real2sim_builder import export as e
    p=project_fixture(tmp_path);out=tmp_path/'package';original=e.os.fsync
    def fail_directory(fd):
        if stat.S_ISDIR(e.os.fstat(fd).st_mode):raise OSError('directory fsync failed')
        return original(fd)
    monkeypatch.setattr(e.os,'fsync',fail_directory)
    with pytest.raises(e.ExportError) as error:e.export_revision(p,destination=out,allow_unvalidated=True)
    assert error.value.code=='EXPORT_STATE_UNKNOWN' and error.value.effect=='unknown'
    assert e.verify_package(out).identity.revision=='package'
    assert not list(tmp_path.glob('.building-*'))


@pytest.mark.parametrize('phase',['before_publish','after_publish'])
def test_actual_killed_export_never_publishes_an_incomplete_revision(tmp_path,phase):
    import os,subprocess,sys,time
    from real2sim_builder.export import export_revision,verify_package
    p=project_fixture(tmp_path);previous=tmp_path/'previous';old_id=export_revision(p,destination=previous,allow_unvalidated=True)
    output=tmp_path/'new';ready=tmp_path/'ready'
    child='''import os,sys,time
from pathlib import Path
from real2sim_builder.project import Project
from real2sim_builder import export as e
ready=Path(sys.argv[3])
def wait():
 ready.write_text('at controlled boundary')
 while True:time.sleep(.1)
if sys.argv[4]=='before_publish':
 original=e.usd.export
 def intercept(*args,**kwargs):
  result=original(*args,**kwargs);wait();return result
 e.usd.export=intercept
else:
 original=e.os.rename
 def intercept(source,target):
  original(source,target);wait()
 e.os.rename=intercept
e.export_revision(Project(sys.argv[1]),destination=sys.argv[2],allow_unvalidated=True)
'''
    process=subprocess.Popen([sys.executable,'-B','-c',child,str(p.root),str(output),str(ready),phase],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=os.environ.copy())
    try:
        deadline=time.monotonic()+20
        while not ready.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert ready.exists(),process.communicate(timeout=1)
        process.kill();process.wait(timeout=5)
        assert process.returncode<0
        assert verify_package(previous).identity==old_id
        if phase=='before_publish':
            assert not output.exists()
            with pytest.raises(FileExistsError):export_revision(p,destination=output,allow_unvalidated=True)
        else:
            assert verify_package(output).identity.revision=='new'
            with pytest.raises(ValueError):export_revision(p,destination=output,allow_unvalidated=True)
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        process.communicate(timeout=5)


def test_execution_usd_missing_default_prim_or_dependency_never_publishes(tmp_path):
    from real2sim_builder.export import export_revision
    p=project_fixture(tmp_path);source=tmp_path/'broken.usda'
    source.write_text('#usda 1.0\ndef Xform "Robot" {}\n')
    with pytest.raises(ValueError):export_revision(p,destination=tmp_path/'no-default',allow_unvalidated=True,isaac_robot_asset=source)
    assert not (tmp_path/'no-default').exists()
    source.write_text('#usda 1.0\n( defaultPrim = "Robot" )\ndef Xform "Robot" (references = @absent.usda@) {}\n')
    with pytest.raises(ValueError):export_revision(p,destination=tmp_path/'missing',allow_unvalidated=True,isaac_robot_asset=source)
    assert not (tmp_path/'missing').exists()


def test_unknown_absolute_mdl_import_is_not_misclassified_as_sdk_standard_library(tmp_path):
    from real2sim_builder.export import copy_native_asset
    source=tmp_path/'Custom.mdl';source.write_text('mdl 1.7;\nimport ::custom::Private::*;\n')
    with pytest.raises(ValueError):copy_native_asset(source,tmp_path/'package')
