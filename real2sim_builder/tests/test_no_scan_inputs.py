"""Retired GLB entry points reject inputs while metric authoring remains available."""
import copy
import pytest
from real2sim_builder.project import Project,Candidate
from real2sim_builder.scene import empty,validate
from real2sim_builder.files import sha,write


@pytest.mark.parametrize('suffix',['.glb','.gltf','.GLB'])
def test_glb_is_rejected_before_copying_evidence_or_candidate_assets(tmp_path,suffix):
    from real2sim_builder.evidence import copy_input
    project=Project.create(tmp_path/'projects','no scan');candidate=Candidate.create(project,'draft')
    source=tmp_path/('scan'+suffix);source.write_bytes(b'legacy original bytes')
    before=copy.deepcopy(project.evidence)
    for operation in (lambda:copy_input(project,source),lambda:candidate.asset(source)):
        with pytest.raises(ValueError,match='LEGACY_UNSUPPORTED'):operation()
    assert project.evidence==before and source.read_bytes()==b'legacy original bytes'
    assert not list((candidate.root/'assets').glob('**/*'))


def test_legacy_scene_can_be_inspected_but_not_silently_reexported(tmp_path):
    project=Project.create(tmp_path/'projects','legacy');scene=empty('legacy')
    scene['scan_initialization']={'registration':{'metric_scale_verified':False}}
    path=project.root/'working/current_scene.yaml';write(path,scene);before=sha(path)
    assert Project(project.root).scene==scene
    with pytest.raises(ValueError,match='LEGACY_UNSUPPORTED'):validate(scene,project.root)
    plain=empty('asset');plain['assets']['scan']={'path':'input/assets/old.glb'}
    with pytest.raises(ValueError,match='LEGACY_UNSUPPORTED'):validate(plain)
    assert sha(path)==before


def test_old_scan_cli_is_gone_and_measurement_constraint_action_is_available(tmp_path):
    from real2sim_builder.cli import main
    with pytest.raises(SystemExit)as error:main(['scan',str(tmp_path),'import','--path','scan.glb'])
    assert error.value.code==2
    from real2sim_builder.initialization import constrain
    assert callable(constrain)


def test_workbench_rejects_a_glb_batch_without_mutating_other_inputs(tmp_path):
    from PIL import Image
    from robot_learning_workbench.scene_preparation import save_inputs
    project=Project.create(tmp_path/'projects','inputs');before=project.evidence
    photo=tmp_path/'photo.png';Image.new('RGB',(12,12)).save(photo)
    source=tmp_path/'scan.gltf';source.write_text('{}')
    with pytest.raises(ValueError,match='LEGACY_UNSUPPORTED'):save_inputs(project.root,[photo,source],'notes')
    assert project.evidence==before
