"""CLI routes saved projects/candidates into actual functions and explicit exports."""
import json
from pathlib import Path
import pytest


def test_cli_new_inspect_reload_status_and_capabilities(tmp_path,capsys):
    from real2sim_builder.cli import main
    assert main(['new','Builder offline','--projects',str(tmp_path)]) in (None,0)
    project=Path(capsys.readouterr().out.strip());assert (project/'project.yaml').exists()
    assert main(['inspect',str(project)])==0
    record=json.loads(capsys.readouterr().out);assert record['project']['name']=='Builder offline' and record['scene'] is None
    main(['status',str(project)]);assert json.loads(capsys.readouterr().out)['status']=='DRAFT'
    main(['capabilities']);record=json.loads(capsys.readouterr().out)
    assert record['articulated_action_replay'] is False
    assert record['native_scene_contract']=='schema_version=1; immutable new destination'


def test_export_cli_requires_new_destination_and_keeps_unknown_command_an_error(tmp_path):
    from real2sim_builder.cli import main
    with pytest.raises(SystemExit) as exc:main(['export',str(tmp_path)])
    assert exc.value.code==2
    with pytest.raises(SystemExit):main(['not-a-command'])


def test_cli_clone_makes_explicit_editable_copy_and_original_remains_read_only(tmp_path,capsys):
    from real2sim_builder.project import Project,sha
    from real2sim_builder.cli import main
    original=Project.create(tmp_path/'projects','Old project')
    (original.root/'working/owner.json').unlink()
    before={str(p.relative_to(original.root)):sha(p) for p in original.root.rglob('*') if p.is_file()}
    main(['clone',str(original.root),str(tmp_path/'copy')]);assert capsys.readouterr().out.strip()==str(tmp_path/'copy')
    copied=Project(tmp_path/'copy');copied.update(status='DRAFT',task='editable cloned project')
    assert not copied.read_only and Project(original.root).read_only
    assert before=={str(p.relative_to(original.root)):sha(p) for p in original.root.rglob('*') if p.is_file()}


def test_cli_review_export_and_verify_use_actual_native_package_without_promoting_success(tmp_path,capsys):
    from real2sim_builder.project import Project,write
    from real2sim_builder.cli import main
    from test_builder_export import legacy_scene
    project=Project.create(tmp_path/'projects','Review export');project.save_scene(legacy_scene())
    write(project.root/'working/validation/report.json',{'passed':False,'input_signature':project.signature(),'physics_status':'PHYSICS_NOT_VALIDATED'})
    destination=tmp_path/'published'
    assert main(['export',str(project.root),'--destination',str(destination),'--allow-unvalidated'])==0
    report=json.loads(capsys.readouterr().out)
    assert report['identity']['revision']=='published' and (destination/'manifest.json').is_file()
    assert project.state['status']=='DRAFT' and project.state['export_destination']==str(destination)
    assert main(['verify',str(destination)])==0
    verified=json.loads(capsys.readouterr().out);assert verified['identity']==report['identity'] and verified['files']>=5
