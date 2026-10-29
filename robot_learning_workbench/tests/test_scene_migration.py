from pathlib import Path
import json
import numpy as np
import pytest
from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import read,write,sha


def test_migration_rebuilds_project_and_owns_data_without_source_links(tmp_path):
    from test_candidate_pairs import candidate_fixture
    from robot_learning_workbench.scene_migration import migrate_authoring
    original,c,model,mapping=candidate_fixture(tmp_path);note=original.root/'input/note.txt';note.write_text('existing measurement')
    evidence=original.evidence;evidence['briefs']=[{'path':'input/note.txt','sha256':sha(note)}];write(original.root/'input/evidence.yaml',evidence)
    before={str(p):sha(p)for p in original.root.rglob('*')if p.is_file()}
    migrated=migrate_authoring(original.root,tmp_path/'new','pickplace_colorblock');new=Project(migrated['project'])
    assert new.info['name']=='pickplace_colorblock'and new.info['id']!=original.info['id']
    assert new.scene['objects']==original.scene['objects']and new.evidence['briefs']==original.evidence['briefs']
    assert all(sha(p)==h for p,h in before.items())
    assert not any(p.is_symlink()for p in new.root.rglob('*'))
    assert (new.root/'input/note.txt').stat().st_ino!=note.stat().st_ino
    assert list((new.root/'scratch/agent').glob('*/candidate_scene.yaml'))
    import shutil
    shutil.rmtree(original.root);assert read(new.root/'input/note.txt')=='existing measurement'
    from real2sim_builder.scene import validate
    validate(new.scene,new.root,complete=True)


def test_optional_urdf_import_copies_mesh_closure_and_missing_mesh_is_explicit(tmp_path):
    from robot_learning_workbench.scene_preparation import create_scene,save_inputs,scene_details
    p=create_scene(tmp_path/'workspace','URDF only');mesh=tmp_path/'mesh.stl';mesh.write_bytes(b'not decoded until geometry validation')
    urdf=tmp_path/'robot.urdf';urdf.write_text('<robot name="test"><link name="base"><visual><geometry><mesh filename="mesh.stl"/></geometry></visual></link></robot>')
    result=save_inputs(p['project'],[str(urdf)],'');saved=Path(p['project'])/next(r['path']for r in result['inputs']if r['kind']=='robot')
    mesh.unlink();urdf.unlink();assert saved.is_file()
    import xml.etree.ElementTree as ET
    assert (saved.parent/ET.parse(saved).find('.//mesh').get('filename')).is_file()


def test_registered_package_keeps_identity_bytes_and_closure_without_source(tmp_path):
    from robot_learning_workbench.scene_migration import register_package
    from scene_contract.package import load_scene
    root=Path(__file__).resolve().parents[2];source=root/'docs/evidence/e01-v8-collision/runspace/relocated/scene-v8-native'
    project=Project.create(tmp_path/'scenes','package');result=register_package(project,source,tmp_path)
    package=load_scene(Path(result['path'])/'scene.json');old=load_scene(source/'scene.json')
    assert package.identity==old.identity
    assert (package.root/'scene.json').read_bytes()==(source/'scene.json').read_bytes()
    assert package.root.is_relative_to(tmp_path)and not package.root.is_relative_to(source)
    assert project.info['execution_packages'][0]['manifest_sha256']==old.identity.manifest_sha256


def test_runtime_residual_is_removed_from_new_authoring_revisions(tmp_path):
    from test_candidate_pairs import candidate_fixture
    from robot_learning_workbench.scene_migration import migrate_authoring
    from real2sim_builder.scene import value
    original,c,m,mapping=candidate_fixture(tmp_path);s=original.scene;s['robot_model']['simulation_joint_offsets_rad']=value([.01]*6,'estimated',['historical only']);write(original.root/'working/current_scene.yaml',s)
    result=migrate_authoring(original.root,tmp_path/'new','new')
    assert 'simulation_joint_offsets_rad'not in Project(result['project']).scene['robot_model']
    archive=read(Path(result['project'])/'input/migration/source-scene.yaml');assert archive['robot_model']['simulation_joint_offsets_rad']==s['robot_model']['simulation_joint_offsets_rad']
