import importlib,tomllib
from pathlib import Path
import pytest
from test_robot_offline_stages import plan
from robot_learning_workbench.robot import offline


def test_capture_dependency_is_optional_and_declared():
    p=Path(__file__).resolve().parents[1]/'pyproject.toml'
    config=tomllib.loads(p.read_text());extra=config['project']['optional-dependencies']['offline']
    assert 'lerobot==0.4.1' in extra and any(x.startswith('real2sim-builder>=') for x in extra)
    assert not any('real2sim-builder' in x for x in config['project']['dependencies'])


def test_capture_dependency_error_is_clear_and_precedes_output(tmp_path,monkeypatch):
    from dataclasses import replace
    p=replace(plan(tmp_path,'precision_calibration'),stage='capture');original=importlib.import_module
    def missing(name,package=None):
        if name=='real2sim_builder.capture':raise ModuleNotFoundError("Builder not installed",name='real2sim_builder')
        return original(name,package)
    monkeypatch.setattr(importlib,'import_module',missing)
    with pytest.raises(ValueError,match='offline.*extra')as error:offline.run(p,events=lambda _:None,commands=lambda:())
    assert error.value.code=='STAGE_DEPENDENCY_MISSING' and not p.output_path.exists()


def test_backend_import_and_cli_prepare_do_not_require_builder(tmp_path):
    import subprocess,sys
    code='''
import sys,importlib.abc
class MissingBuilder(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='real2sim_builder' or fullname.startswith('real2sim_builder.'):
   raise ModuleNotFoundError('Builder absent in isolated test',name=fullname)
sys.meta_path.insert(0,MissingBuilder())
from robot_learning_workbench.cli import main
from robot_learning_workbench.learning.policy import policy_catalog
from robot_learning_workbench.robot.offline import capture_reader
from pathlib import Path
root=Path(sys.argv[1]);(root/'dataset/meta').mkdir(parents=True);(root/'dataset/meta/info.json').write_text('{}');(root/'train.json').write_text('{}')
p=root/'train.yaml';p.write_text('schema_version: 1\\nstage: train\\ninputs: {dataset: dataset, training_config: train.json}\\nexecution: {mode: scratch}\\noutput: {directory: output}\\n')
assert main(['prepare',str(p)])==0
try:capture_reader()
except ValueError as e:assert e.code=='STAGE_DEPENDENCY_MISSING'
else:raise AssertionError('Capture should require Builder')
assert not any(n.startswith('real2sim_builder') for n in sys.modules)
'''
    result=subprocess.run([sys.executable,'-B','-c',code,str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_device_profile_sdk_calibration_bytes_are_pinned(tmp_path):
    import json,yaml
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe,verify_prepared_inputs
    from test_policy_paths import MODEL
    cal=tmp_path/'motors.json';cal.write_text('{}')
    device=tmp_path/'device.json';device.write_text(json.dumps({'role':'follower','sdk':{'port':'/dev/not-opened','id':'offline'},'calibration_path':str(cal)}))
    recipe=tmp_path/'real.yaml';recipe.write_text(yaml.safe_dump(dict(schema_version=1,stage='real_evaluation',inputs={'device_profile':str(device),'policy':str(MODEL)},execution={'mode':'offline','episodes':1},output={'directory':str(tmp_path/'out')})))
    prepared=prepare_recipe(read_recipe(recipe));assert prepared.resolved_inputs['motor_calibration']['path']==str(cal)
    cal.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='changed'):verify_prepared_inputs(prepared)
