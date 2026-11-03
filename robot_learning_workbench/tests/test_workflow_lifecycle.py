"""Real Qt and file IPC, without starting simulation, training or devices."""
import pytest
from test_pipeline_scripts import qt


@pytest.mark.parametrize('previous',[False,True])
def test_stop_during_start_targets_only_the_late_new_run(tmp_path,previous):
    qt('''
import json,sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('offline_validation','/no/worker','modules');p.timer.stop()
def run(name,status):
 folder=root/name;folder.mkdir();(folder/'commands').mkdir()
 handle={'run_id':name,'request_id':name+'-request','run_dir':str(folder),'output_path':str(root/(name+'-output'))}
 (folder/'run.json').write_text(json.dumps(dict(stage='offline_validation',status=status,phase='running',request_id=handle['request_id'],run_id=name,completed_episodes=0)))
 return handle
old=run('previous','completed');new=run('new','running')
if PREVIOUS:p.handle=old
p.operation='start';p.busy=True;p.buttons()
p.cancel_button.click();p.poll()
assert not list((root/'previous/commands').glob('*.json'))
assert '취소'in p.state.text()or '중단'in p.state.text()
p.job_finished({'ok':True,'result':new})
commands=list((root/'new/commands').glob('*.json'))
assert len(commands)==1 and json.loads(commands[0].read_text())['payload']['kind']=='cancel'
assert not list((root/'previous/commands').glob('*.json'))
assert '취소'in p.state.text()or '중단'in p.state.text()
p.cancel_run();assert len(list((root/'new/commands').glob('*.json')))==1
p.poll();assert '중단'in p.state.text()and not p.cancel_button.isEnabled()
data=json.loads((root/'new/run.json').read_text());data.update(status='cancelled',phase='terminal');(root/'new/run.json').write_text(json.dumps(data))
p.poll();assert not p.active()and not p.cancel_button.isEnabled()
p.close()
'''.replace('PREVIOUS',repr(previous)),tmp_path)


def test_failed_start_releases_pending_stop_without_a_phantom_run(tmp_path):
    qt('''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);p=WorkflowPage('offline_validation','/no/worker','modules');p.timer.stop()
p.operation='start';p.busy=True;p.cancel_run()
p.job_finished({'ok':False,'error':{'message':'start failed'}})
assert p.handle is None and not p.active()and not p.cancel_button.isEnabled()
assert p.operation is None and 'start failed'in p.state.text()
p.close()
''',tmp_path)


def test_cancel_delivery_retry_reuses_the_same_command_id(tmp_path):
    qt('''
import sys,json
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench import run
app=QApplication([]);root=Path(sys.argv[1]);folder=root/'run';folder.mkdir();(folder/'commands').mkdir()
(folder/'run.json').write_text(json.dumps(dict(run_id='run',request_id='request',status='running',phase='running')))
p=WorkflowPage('offline_validation','/no/worker','modules');p.timer.stop();p.handle={'run_id':'run','request_id':'request','run_dir':str(folder),'output_path':str(root/'output')}
send=run.send_command;ids=[]
def controlled(handle,command):
 ids.append(command['command_id'])
 if len(ids)==1:raise OSError('controlled write error')
 return send(handle,command)
with patch.object(run,'send_command',side_effect=controlled):
 p.cancel_run();assert p.cancel_button.isEnabled()and '전달 실패'in p.state.text()
 p.cancel_run();assert not p.cancel_button.isEnabled()
assert len(ids)==2 and ids[0]==ids[1]and len(list((folder/'commands').glob('*.json')))==1
p.close()
''',tmp_path)


def test_new_start_discards_previous_terminal_handle_before_waiting(tmp_path):
    qt('''
import sys,json,yaml
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('offline_validation','/no/worker','modules');p.timer.stop()
folder=root/'old';folder.mkdir();(folder/'run.json').write_text(json.dumps(dict(status='completed',phase='terminal',request_id='old-request')))
p.handle={'run_id':'old','request_id':'old-request','run_dir':str(folder),'output_path':str(root/'old-output')}
script=root/'r.yaml';script.write_text(yaml.safe_dump(p.editor.data()));p.editor.load(script);p.ready={'recipe_sha256':'sha','prepared_sha256':'plan'}
requests=[];p.job.start=lambda op,**kw:requests.append((op,kw));p.start_run()
assert p.handle is None and p.operation=='start'and p.active()and requests[-1][0]=='start'
p.cancel_run();p.job_finished({'ok':False,'error':{'message':'controlled start failure'}});p.close()
''',tmp_path)


def test_window_close_remembers_stop_before_a_handle_exists(tmp_path):
    qt('''
from types import SimpleNamespace
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench.ui.app import Window
app=QApplication([]);p=WorkflowPage('offline_validation','/no/worker','modules');p.timer.stop()
p.operation='start';p.busy=True
owner=SimpleNamespace(workflows={'validation':p},sessions={},closing=False,close=lambda:None,statusBar=lambda:SimpleNamespace(showMessage=lambda text:None))
event=SimpleNamespace(ignore=lambda:None)
with patch('robot_learning_workbench.ui.app.QTimer.singleShot'):Window.closeEvent(owner,event)
assert p.stop_requested and p.handle is None
p.job_finished({'ok':False,'error':{'message':'controlled failure'}});p.close()
''',tmp_path)


@pytest.mark.parametrize('snapshot',[True,False])
def test_reopen_restores_saved_manual_vector_settings_without_start_or_source_write(tmp_path,snapshot):
    qt('''
import sys,json,yaml,hashlib
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QFileDialog
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench.run import StartRequest,WorkerRequest,_plain
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('annotation','/no/worker','modules');p.timer.stop()
data=dict(schema_version=1,stage='annotation',engine='isaaclab',inputs={'dataset':'./source','scene':'./scene.json'},execution={'mode':'manual','env_num':4},functions={'acceptance':{'function':'pick_place.annotation','params':{'object':'red','target':'cup'}},'signals':{'grasp':{'function':'pick_place.stable_grasp','params':{'object':'red'}}}},output={'directory':'./output'})
original=root/'original.yaml';original.write_text(yaml.safe_dump(data));raw=original.read_bytes()
folder=root/'saved-run';folder.mkdir();(folder/'commands').mkdir()
req=StartRequest('request',original,hashlib.sha256(raw).hexdigest(),'annotation',root/'output')
(folder/'worker_request.json').write_text(json.dumps(_plain(WorkerRequest(req,folder.name,folder,sys.executable,'fixture'))))
(folder/'run.json').write_text(json.dumps(dict(run_id=folder.name,request_id='request',stage='annotation',status='running',phase='running',completed_episodes=0)))
if SNAPSHOT:
 (folder/'recipe.yaml').write_bytes(raw);original.write_text('stage: source\\n')
before={str(f):f.read_bytes()for f in(folder/'worker_request.json',folder/'run.json',original)}
requests=[];p.job.start=lambda *a,**k:requests.append((a,k));QFileDialog.getExistingDirectory=lambda *a,**k:str(folder)
p.reopen_run()
assert p.handle is not None and p.handle['run_id']==folder.name
assert p.execution['mode']=='manual'and p.engine.currentText()=='isaaclab'and p.preview_env.maximum()==3
assert not p.manual_controls.isHidden()and p.mark_event.currentText()=='grasp'
assert p.editor.path is None and p.editor.dirty
assert p.editor.data()['inputs']['dataset']==str(root/'source')
assert all(Path(f).read_bytes()==value for f,value in before.items())and not requests
assert p.ready is None and not p.start_button.isEnabled()
status=json.loads((folder/'run.json').read_text());status.update(status='cancelled',phase='terminal');(folder/'run.json').write_text(json.dumps(status))
p.close()
'''.replace('SNAPSHOT',repr(snapshot)),tmp_path)


def test_reopen_rejects_changed_snapshot_before_attaching(tmp_path):
    qt('''
import sys,json,hashlib
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QFileDialog
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench.run import StartRequest,WorkerRequest,_plain
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('annotation','/no/worker','modules');p.timer.stop()
original=root/'original.yaml';original.write_text('schema_version: 1\\nstage: annotation\\nengine: mujoco\\ninputs: {dataset: source}\\nexecution: {mode: auto}\\nfunctions: {acceptance: {function: pick_place.annotation, params: {object: red, target: cup}}}\\noutput: {directory: output}\\n')
folder=root/'saved-run';folder.mkdir();req=StartRequest('request',original,hashlib.sha256(original.read_bytes()).hexdigest(),'annotation',root/'output')
(folder/'worker_request.json').write_text(json.dumps(_plain(WorkerRequest(req,folder.name,folder,sys.executable,'fixture'))))
(folder/'run.json').write_text(json.dumps(dict(run_id=folder.name,request_id='request',stage='annotation',status='completed',phase='terminal')))
(folder/'recipe.yaml').write_bytes(original.read_bytes()+b'# changed\\n')
QFileDialog.getExistingDirectory=lambda *a,**k:str(folder);p.reopen_run()
assert p.handle is None and not p.active()and not p.start_button.isEnabled()
assert '변경'in p.state.text()or 'identity'in p.state.text()
p.close()
''',tmp_path)
