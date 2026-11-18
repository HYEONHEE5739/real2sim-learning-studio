"""Relocated launcher and save guards, without starting engines or changing installs."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_workbench_window import UI


ROOT = Path(__file__).resolve().parents[2]


def test_launcher_uses_checkout_local_qt_runtime_when_no_override_is_set(tmp_path):
    project,_,_,capture,env=_launcher(tmp_path)
    runtime=project/'workbench_runs/runtime/qt/bin/python3.11'
    runtime.parent.mkdir(parents=True)
    shutil.copy2(env.pop('QT_PYTHON'),runtime)
    result=subprocess.run(['bash',str(project/'run_workbench_ui.sh')],cwd=tmp_path,
        env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    record=json.loads(capture.read_text())
    assert record['args'][:3]==['-B','-m','robot_learning_workbench.ui.app']
    assert record['args'][record['args'].index('--workspace')+1]==env['WORKBENCH_WORKSPACE']


def _launcher(tmp_path):
    project = tmp_path / 'other user' / 'relocated studio'
    project.mkdir(parents=True)
    shutil.copy2(ROOT / 'run_workbench_ui.sh', project)
    modules = project / 'robot_learning_workbench/task_modules.yaml'
    modules.parent.mkdir()
    modules.write_text('{}\n')
    capture = tmp_path / 'launch.json'
    fake_qt = tmp_path / 'existing Qt python'
    fake_qt.write_text('#!/usr/bin/python3\nimport json,os,sys\n'
                       'open(os.environ["R2S_LAUNCH_CAPTURE"],"w").write(json.dumps('
                       '{"args":sys.argv[1:],"pythonpath":os.environ.get("PYTHONPATH","")}))\n')
    fake_qt.chmod(0o755)
    backend = tmp_path / 'custom env/bin/python'
    backend.parent.mkdir(parents=True)
    backend.symlink_to('/usr/bin/python3')
    lab = tmp_path / 'custom IsaacLab'
    (lab / 'source/isaaclab').mkdir(parents=True)
    env = dict(os.environ, QT_PYTHON=str(fake_qt), BACKEND_PYTHON=str(backend),
               ISAACLAB_ROOT=str(lab), WORKBENCH_WORKSPACE=str(tmp_path / 'my workspace'),
               R2S_LAUNCH_CAPTURE=str(capture), PYTHONPATH=str(tmp_path / 'inherited packages'))
    return project, backend, lab, capture, env


def test_relocated_launcher_uses_explicit_existing_runtimes_and_workspace(tmp_path):
    project, backend, lab, capture, env = _launcher(tmp_path)
    result = subprocess.run(['bash', str(project / 'run_workbench_ui.sh')], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    record = json.loads(capture.read_text())
    args = record['args']
    assert args[args.index('--backend-python') + 1] == str(backend)
    assert args[args.index('--workspace') + 1] == env['WORKBENCH_WORKSPACE']
    assert args[args.index('--task-modules') + 1] == str(project / 'robot_learning_workbench/task_modules.yaml')
    paths = record['pythonpath'].split(os.pathsep)
    assert paths[:3] == [str(project / directory) for directory in
                        ('scene_contract/src', 'real2sim_builder/src', 'robot_learning_workbench/src')]
    assert str(lab / 'source/isaaclab') in paths
    assert not any('/home/hyeonhee/' in path for path in paths)


@pytest.mark.parametrize('key', ['QT_PYTHON', 'BACKEND_PYTHON', 'ISAACLAB_ROOT'])
def test_launcher_rejects_missing_explicit_runtime_before_gui(tmp_path, key):
    project, _, _, capture, env = _launcher(tmp_path)
    env[key] = str(tmp_path / 'missing runtime')
    result = subprocess.run(['bash', str(project / 'run_workbench_ui.sh')], env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert key in result.stderr
    assert not capture.exists()


def test_launcher_retains_cli_path_override_precedence(tmp_path):
    project, backend, _, capture, env = _launcher(tmp_path)
    env['BACKEND_PYTHON'] = str(tmp_path / 'obsolete default')
    workspace = tmp_path / 'explicit CLI workspace'
    result = subprocess.run(['bash', str(project / 'run_workbench_ui.sh'),
                             '--backend-python', str(backend), '--workspace', str(workspace)],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    args = json.loads(capture.read_text())['args']
    assert args[-4:] == ['--backend-python', str(backend), '--workspace', str(workspace)]


def test_recipe_save_preserves_other_users_installs_and_allows_new_workspace(tmp_path):
    script = '''
import sys
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.recipe_editor import RecipeEditor
app=QApplication([]);root=Path(sys.argv[1]);home=root/'another user';home.mkdir()
editor=RecipeEditor();editor.text.setPlainText('schema_version: 1\\n')
for name in ('independent-checkout','miniconda3','IsaacLab'):
    original=home/name/'protected.yaml';original.parent.mkdir();original.write_text('original')
    if name=='independent-checkout':(original.parent/'.git').mkdir()
    with patch.object(Path,'home',return_value=home):
        try:editor.save(original)
        except ValueError:pass
        else:raise AssertionError('Protected another-user install was overwritten: '+str(original))
    assert original.read_text()=='original'
target=root/'workspace/scripts/new.yaml'
with patch.object(Path,'home',return_value=home):editor.save(target)
assert target.read_text()=='schema_version: 1\\n'
from robot_learning_workbench.ui.paths import protected_destination
assert not protected_destination(target,backend_python='/no/worker')
assert not protected_destination(target,backend_python='/envs/example/bin/python')
editor.close()
'''
    process = subprocess.run([UI, '-B', '-c', script, str(tmp_path)],
                             env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr


def test_training_json_save_protects_explicit_backend_prefix_and_symlink_targets(tmp_path):
    script = '''
import json,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication,QDialog,QWidget,QPlainTextEdit,QLabel
from robot_learning_workbench.ui.training_json import TrainingJsonDialog
app=QApplication([]);root=Path(sys.argv[1]);prefix=root/'custom backend';(prefix/'bin').mkdir(parents=True)
python=prefix/'bin/python';python.touch();workspace=root/'workspace';workspace.mkdir()
page=QWidget();page.backend_python=str(python);page.workspace=workspace;page.ready=None
page.editor=SimpleNamespace(data=lambda:{'inputs':{'dataset':'dataset'},'execution':{'mode':'scratch'},'output':{'directory':'policy'}})
page.settings=SimpleNamespace(base=lambda:workspace,set_inputs=lambda _:None)
dialog=TrainingJsonDialog.__new__(TrainingJsonDialog);QDialog.__init__(dialog,page)
dialog.page=page;dialog.text=QPlainTextEdit();dialog.status=QLabel();dialog.text.setPlainText(json.dumps({'policy':{'type':'act'}}))
link=root/'looks writable';link.symlink_to(prefix,target_is_directory=True)
for target in (prefix/'new.json',link/'alias.json'):
    with patch('robot_learning_workbench.ui.training_json.QFileDialog.getSaveFileName',return_value=(str(target),'')):
        dialog.save()
    assert not target.exists() and 'scripts/train' in dialog.status.text(),dialog.status.text()
assert not any(name in sys.modules for name in ('torch','mujoco','isaaclab','lerobot'))
'''
    process = subprocess.run([UI, '-B', '-c', script, str(tmp_path)],
                             env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr


def test_source_and_device_editors_protect_their_owned_backend_without_launcher_env(tmp_path):
    script = '''
import os,sys
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication,QComboBox
from robot_learning_workbench.ui.source_settings import SourceSettings
from robot_learning_workbench.ui.device_setup import DeviceSetup
os.environ.pop('BACKEND_PYTHON',None)
app=QApplication([]);root=Path(sys.argv[1]);prefix=root/'nonstandard backend';(prefix/'bin').mkdir(parents=True)
python=prefix/'bin/python';python.touch();original=prefix/'protected.yaml';original.write_text('original')
engine=QComboBox();engine.addItem('mujoco')
with patch('robot_learning_workbench.ui.jobs.BackendJob.start'):
    source=SourceSettings(str(python),root/'workspace',engine)
    device=DeviceSetup(root/'workspace',str(python),'modules')
for editor in (source.editor,device.advanced):
    editor.text.setPlainText('changed')
    try:editor.save(original)
    except ValueError:pass
    else:raise AssertionError('Editor lost its actual backend prefix')
    assert original.read_text()=='original'
source.close();device.close()
'''
    process = subprocess.run([UI, '-B', '-c', script, str(tmp_path)],
                             env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr
