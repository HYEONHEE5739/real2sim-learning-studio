"""Engine-neutral workflow helpers must not import another physics backend."""
import ast
from pathlib import Path


def test_concrete_engines_have_no_cross_backend_imports():
    root=Path(__file__).parents[1]/'src/robot_learning_workbench/engines'
    violations=[]
    for engine,other in [('isaac','mujoco'),('mujoco','isaac')]:
        for path in (root/engine).glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom) and other in (node.module or '').split('.'):
                    violations.append((engine,path.name,node.lineno,node.module))
    assert not violations,violations


def test_shared_workflow_modules_do_not_load_physics_or_gui():
    import subprocess,sys
    code='''import sys
from robot_learning_workbench.data.recording import validate_recording
from robot_learning_workbench.commands import command_channels
from robot_learning_workbench.data.publication import publish_generation
from robot_learning_workbench.tasks.evaluation import evaluation_result
assert evaluation_result(placed=True,grasp=False,steps=1,limit=10)['success']
assert not any(n in sys.modules for n in ('mujoco','isaaclab','torch','PyQt6'))
'''
    result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_data_and_task_helpers_do_not_depend_on_runner_or_ui():
    root=Path(__file__).parents[1]/'src/robot_learning_workbench'
    violations=[]
    for name in ('data/recording.py','data/publication.py','data/video.py','tasks/evaluation.py'):
        for node in ast.walk(ast.parse((root/name).read_text())):
            if isinstance(node,ast.ImportFrom) and (node.module or '').split('.')[0] in ('run','ui'):
                violations.append((name,node.lineno,node.module))
    assert not violations,violations


def test_moved_orchestration_keeps_append_provenance_and_strict_core(tmp_path):
    import pytest
    from test_dataset_append import execution,add
    from robot_learning_workbench.data.native import NativeRun,load_catalog,read_json,DataError
    old={**execution(),'workflow_code':{'source.py':'before','robot/control.py':'safe','state.py':'state','devices.py':'device','mimic.py':'ik'}}
    path=tmp_path/'source'
    with NativeRun(path,old) as owner:add(owner)
    ep=load_catalog(path).episodes[0];header=ep.file.parent/'segment.json.gz'
    original_header=header.read_bytes();original_file=ep.file.read_bytes()
    new={**old,'workflow_code':{**old['workflow_code'],'source.py':'after','commands.py':'moved','recording.py':'moved','publication.py':'moved','configuration.py':'moved'}}
    with NativeRun(path,new,append=True) as owner:add(owner)
    assert header.read_bytes()==original_header and ep.file.read_bytes()==original_file
    assert read_json(path/'run.json')['execution_history'][0]['workflow_code']==old['workflow_code']
    for name in ('robot/control.py','state.py','devices.py','mimic.py'):
        changed={**new,'workflow_code':{**new['workflow_code'],name:'changed'}}
        with pytest.raises(DataError):NativeRun(path,changed,append=True)
