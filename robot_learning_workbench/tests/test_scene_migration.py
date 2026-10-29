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
