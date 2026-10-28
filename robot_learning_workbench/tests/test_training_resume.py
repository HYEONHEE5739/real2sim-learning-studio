from pathlib import Path
import json,yaml
import pytest
from robot_learning_workbench.recipe import read_recipe,prepare_recipe
ROOT=Path(__file__).resolve().parents[2]


def test_closed_official_resume_prepares_new_output_with_explicit_checkpoint(tmp_path):
    src=ROOT/'docs/evidence/learning-bundle';cfg=json.loads((src/'act-second.json').read_text());cfg.update(resume=True,steps=4,output_dir=str(tmp_path/'new'))
    c=tmp_path/'config.json';c.write_text(json.dumps(cfg));path=tmp_path/'r.yaml';path.write_text(yaml.safe_dump(dict(schema_version=1,stage='train',inputs={'dataset':cfg['dataset']['root'],'training_config':str(c),'checkpoint':str(src/'runs/act-second/checkpoints/000002')},execution={'mode':'resume'},output={'directory':str(tmp_path/'new')})))
    plan=prepare_recipe(read_recipe(path))
    from robot_learning_workbench.learning.train import training_command
    argv,config=training_command(plan)
    assert '--resume=true' in argv and '--steps=4' in argv
    assert argv[argv.index('--resume=true')-1].endswith('000002/pretrained_model/train_config.json')
    assert not (tmp_path/'new').exists()
