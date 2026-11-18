"""Explicit robot-rig selection is metadata, not a Scene migration or calibration."""
import os
from pathlib import Path
import subprocess

import pytest

from real2sim_builder.files import read,sha,write
from real2sim_builder.project import Project


@pytest.fixture
def rig_case(tmp_path,monkeypatch):
    # Reuse the real native USD/Collision fixture, without Blender/model inference.
    tests=Path(__file__).resolve().parents[2]/'real2sim_builder/tests'
    monkeypatch.syspath_prepend(str(tests))
    from test_robot_rig import rig_fixture
    from real2sim_builder.evidence import create_robot_rig
    project,source,manifest,mount,optical=rig_fixture(tmp_path)
    destination=project.workspace/'robot_rigs/test-camera/v001'
    rig=create_robot_rig(source,manifest,destination,mount_link='wrist',
        T_link_mount=mount.tolist(),T_mount_optical=optical.tolist(),
        evidence=['Synthetic shared Camera Rig; estimated mount, not Calibration'])
    return project,rig,source,manifest


def test_workspace_variants_discover_registered_rig_without_loading_models(rig_case,monkeypatch):
    from robot_learning_workbench.scene_preparation import robot_variants
    import real2sim_builder.evidence as evidence
    project,rig,source,manifest=rig_case
    # Discovery is a metadata operation; selection performs full closure validation.
    def forbidden(*args,**kwargs):pytest.fail('Catalog cannot import a Robot into a Scene')
    monkeypatch.setattr(evidence,'import_robot_rig',forbidden)
    before={p:sha(p)for p in project.workspace.rglob('*')if p.is_file()}
    variants=robot_variants(project.workspace)
    original=next(row for row in variants if row['rig']is None)
    assert original['name']=='SO-ARM101'
    selected=next(row for row in variants if row['rig']==rig['path'])
    assert selected['name']==rig['name']
    assert selected['version']=='v001'
    assert 'v001'in selected['label'] and 'estimated'in selected['label']
    assert Path(selected['path']).resolve()==Path(rig['path']).parent/rig['model']['path']
    assert all(sha(p)==value for p,value in before.items())


def test_final_visual_rig_uses_its_name_without_claiming_calibration(rig_case):
    from robot_learning_workbench.scene_preparation import robot_variants
    project,rig,source,manifest=rig_case
    path=Path(rig['path']);record=read(path)
    record.update(name='SO-ARM101 + Wrist Camera',status='FINAL_VISUAL_MODEL')
    write(path,record)
    row=next(r for r in robot_variants(project.workspace)if r.get('rig')==str(path))
    assert row['label']=='SO-ARM101 + Wrist Camera'
    assert row['version']=='v001'
    assert row['mount_status']=='estimated'
    assert row['calibration_status']=='uncalibrated'
    assert record['physical_verified']is False


def test_named_rig_without_version_directory_is_discovered_and_selected(rig_case):
    from robot_learning_workbench.scene_preparation import robot_variants,select_robot_rig
    project,rig,source,manifest=rig_case
    previous=Path(rig['path']);named=project.workspace/'robot_rigs/so101_with_camera'
    original_model_sha=rig['model']['sha256'];previous.parent.rename(named)
    path=named/'rig.yaml';record=read(path)
    record.update(name='SO-ARM101 + Wrist Camera',status='FINAL_VISUAL_MODEL')
    write(path,record)
    row=next(r for r in robot_variants(project.workspace)if r.get('rig')==str(path))
    assert row['label']=='SO-ARM101 + Wrist Camera'
    assert row['version']is None
    assert row['model_sha256']==original_model_sha
    assert row['calibration_status']=='uncalibrated'
    result=select_robot_rig(project.root,path)
    assert result['robot_rig']['path']=='../../robot_rigs/so101_with_camera/rig.yaml'
    assert result['robot_rig']['sha256']==sha(path)


def test_final_rig_combo_retains_version_and_uncalibrated_tooltip(tmp_path):
    from test_workbench_window import UI
    code='''
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.scene_inputs import SceneInputs
app=QApplication([]);panel=SceneInputs('.');events=[]
panel.robotRigRequested.connect(events.append)
panel.load({'project':None,'inputs':[],'notes':'','robot_variants':[
 {'name':'SO-ARM101 + Wrist Camera','label':'SO-ARM101 + Wrist Camera',
  'version':'v006','rig':'rig.yaml','mount_status':'estimated',
  'calibration_status':'uncalibrated'}]})
assert not events
assert panel.robot_variant.itemText(1)=='SO-ARM101 + Wrist Camera'
tip=panel.robot_variant.itemData(1,Qt.ItemDataRole.ToolTipRole)
assert all(value in tip for value in ['v006','estimated','uncalibrated']),tip
panel.close()
'''
    process=subprocess.run([UI,'-B','-c',code],
        env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=20)
    assert process.returncode==0,process.stdout+process.stderr


def test_selecting_and_clearing_only_changes_project_binding(rig_case,monkeypatch):
    from robot_learning_workbench.scene_preparation import select_robot_rig,scene_details
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.evidence import save_scene_memo
    import real2sim_builder.evidence as evidence
    project,rig,source,manifest=rig_case
    save_scene_memo(project,'Original hardware note, 63mm cup height.\r\n')
    candidate=Candidate.create(project,'existing_candidate')
    calibration=project.root/'input/existing-calibration.json'
    write(calibration,{'status':'existing_fixture','do_not_rebind':True})
    info=project.info
    info['device_configuration']={'path':'../../devices/synthetic/capture.yaml','sha256':'a'*64,'automatic_connect':False}
    write(project.root/'project.yaml',info)
    before={p:sha(p)for p in project.root.rglob('*')if p.is_file()and p.name!='project.yaml'}
    before_info=read(project.root/'project.yaml')
    def forbidden(*args,**kwargs):pytest.fail('Selection cannot migrate Current/Candidate or register a camera')
    monkeypatch.setattr(evidence,'import_robot_rig',forbidden)

    result=select_robot_rig(project.root,rig['path'])
    binding=Project(project.root,read_only=True).info['robot_rig']
    assert not Path(binding['path']).is_absolute()
    assert (project.root/binding['path']).resolve()==Path(rig['path'])
    assert binding['sha256']==sha(rig['path'])
    assert result['robot_rig']['sha256']==binding['sha256']
    assert scene_details(project.root)['robot_rig']['sha256']==binding['sha256']
    assert any(row['rig']==rig['path']for row in result['robot_variants'])
    assert all(sha(p)==value for p,value in before.items())
    current=project.root/'working/current_scene.yaml'
    assert not current.exists()
    assert not candidate.scene.get('robot_model')

    result=select_robot_rig(project.root,None)
    after=Project(project.root,read_only=True).info
    assert not after.get('robot_rig')and result['robot_rig']is None
    assert {k:v for k,v in after.items()if k!='robot_rig'}==before_info
    assert all(sha(p)==value for p,value in before.items())


def test_corrupt_rig_selection_is_rejected_before_project_metadata_write(rig_case):
    from robot_learning_workbench.scene_preparation import select_robot_rig
    project,rig,source,manifest=rig_case
    before=sha(project.root/'project.yaml')
    model=Path(rig['path']).parent/rig['model']['path']
    model.write_bytes(model.read_bytes()+b'\n<!-- unauthorized edit -->\n')
    with pytest.raises(ValueError,match='(?i)sha|changed|integrity|hash'):
        select_robot_rig(project.root,rig['path'])
    assert sha(project.root/'project.yaml')==before
    assert not Project(project.root,read_only=True).info.get('robot_rig')


def test_one_frozen_rig_can_be_selected_by_two_scenes_without_asset_changes(rig_case):
    from robot_learning_workbench.scene_preparation import select_robot_rig
    project,rig,source,manifest=rig_case
    second=Project.create(project.root.parent,'Second Scene')
    before={p:sha(p)for p in Path(rig['path']).parent.rglob('*')if p.is_file()}
    first_selection=select_robot_rig(project.root,rig['path'])
    second_selection=select_robot_rig(second.root,rig['path'])
    assert first_selection['robot_rig']['sha256']==second_selection['robot_rig']['sha256']
    assert all(sha(p)==value for p,value in before.items())
    assert not(project.root/'working/current_scene.yaml').exists()
    assert not(second.root/'working/current_scene.yaml').exists()


def test_rig_selection_requires_the_explicit_workspace_rig_pool(rig_case,tmp_path):
    import shutil
    from robot_learning_workbench.scene_preparation import select_robot_rig
    project,rig,source,manifest=rig_case
    outside=tmp_path/'unregistered-copy';shutil.copytree(Path(rig['path']).parent,outside)
    before=sha(project.root/'project.yaml')
    with pytest.raises(ValueError,match='Workspace|workspace'):
        select_robot_rig(project.root,outside/'rig.yaml')
    assert sha(project.root/'project.yaml')==before


def test_real_qt_robot_combo_emits_explicit_selection_only_and_preserves_saved_notes(tmp_path):
    from test_workbench_window import UI
    code='''
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QComboBox
from robot_learning_workbench.ui.scene_inputs import SceneInputs
import sys
app=QApplication([]);panel=SceneInputs(sys.argv[1]);events=[];saved=[]
assert isinstance(panel.robot_variant,QComboBox)
panel.robotRigRequested.connect(events.append)
panel.saveRequested.connect(lambda files,text:saved.append((files,text)))
rig=str(Path(sys.argv[1])/'robot_rigs/camera/v001/rig.yaml')
original='My original Memo\\r\\nDo not change Capture or Camera Calibration.\\r\\n'
data={'project':str(Path(sys.argv[1])/'scenes/one'),'inputs':[],'notes':original,'notes_saved':True,
 'robot_variants':[{'name':'SO-ARM101','rig':None,'path':None},
  {'name':'SO-ARM101 + Wrist Camera','rig':rig,'path':'variant.urdf','mount_status':'estimated','calibration_status':'uncalibrated'}],
 'robot_rig':{'path':'../../robot_rigs/camera/v001/rig.yaml','sha256':'a'*64}}
panel.load(data);app.processEvents()
assert not events,'Loading a Scene cannot trigger a write or selection action'
assert panel.robot_variant.count()==2
assert panel.robot_variant.currentText()=='SO-ARM101 + Wrist Camera'
panel.robot_variant.setCurrentIndex(0);app.processEvents()
assert events==[''],events
panel.robot_variant.setCurrentIndex(1);app.processEvents()
assert events==['',rig],events
panel.load(dict(data,robot_rig=None));app.processEvents()
assert panel.robot_variant.currentIndex()==0 and events==['',rig]
panel.load(dict(data,robot_variants=[]));app.processEvents()
assert '확인 필요'in panel.robot_variant.currentText()
assert panel.robot_variant.currentData()==rig and events==['',rig]
panel.save.click();assert saved==[([],original)],saved
assert not any(n in sys.modules for n in ['torch','mujoco','isaaclab','lerobot'])
panel.close()
'''
    process=subprocess.run([UI,'-B','-c',code,str(tmp_path)],
        env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=20)
    assert process.returncode==0,process.stdout+process.stderr
