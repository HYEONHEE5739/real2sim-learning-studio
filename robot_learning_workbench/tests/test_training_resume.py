from pathlib import Path
import json,yaml
import pytest
from robot_learning_workbench.recipe import read_recipe,prepare_recipe
ROOT=Path(__file__).resolve().parents[2]


def test_closed_official_resume_prepares_new_output_with_explicit_checkpoint(tmp_path):
    from checkpoint_fixture import official_checkpoint
    checkpoint=official_checkpoint(ROOT/'docs/evidence/learning-bundle/runs/act-second/checkpoints/000002')
    cfg=json.loads((checkpoint/'workbench-checkpoint.json').read_text())['config'];cfg.update(resume=True,steps=4,output_dir=str(tmp_path/'new'))
    c=tmp_path/'config.json';c.write_text(json.dumps(cfg));path=tmp_path/'r.yaml';path.write_text(yaml.safe_dump(dict(schema_version=1,stage='train',inputs={'dataset':cfg['dataset']['root'],'training_config':str(c),'checkpoint':str(checkpoint)},execution={'mode':'resume'},output={'directory':str(tmp_path/'new')})))
    plan=prepare_recipe(read_recipe(path))
    from robot_learning_workbench.learning.train import training_command
    argv,config=training_command(plan)
    assert '--resume=true' in argv and '--steps=4' in argv
    assert argv[argv.index('--resume=true')-1].endswith(str(checkpoint/'pretrained_model/train_config.json'))
    assert not (tmp_path/'new').exists()


def test_cross_device_checkpoint_retry(tmp_path,monkeypatch):
    import os,tempfile
    from types import SimpleNamespace
    from robot_learning_workbench.learning import train
    from robot_learning_workbench.data.native import file_sha256
    with tempfile.TemporaryDirectory(dir='/dev/shm') as source:
        root=Path(source)
        assert root.stat().st_dev!=tmp_path.stat().st_dev
        cfg=root/'pretrained_model/train_config.json';cfg.parent.mkdir();cfg.write_text('{}')
        weights=root/'weights';weights.write_bytes(b'measured fixture')
        files={p.relative_to(root).as_posix():file_sha256(p) for p in (cfg,weights)}
        monkeypatch.setattr(train,'checkpoint_record',lambda _:dict(files=files))
        plan=SimpleNamespace(output_path=tmp_path/'train',effective_settings={'execution':{'mode':'resume'}},resolved_inputs={'checkpoint':{'path':root}})
        files['weights']='invalid'
        with pytest.raises(ValueError):train.freeze_inputs(plan,['--config_path=initial'],{})
        assert not (tmp_path/'train.resume-input').exists()
        files['weights']=file_sha256(weights)
        args=train.freeze_inputs(plan,['--config_path=initial'],{})
        assert Path(args[0].split('=',1)[1]).read_text()=='{}'
        assert file_sha256(tmp_path/'train.resume-input/weights')==files['weights']
