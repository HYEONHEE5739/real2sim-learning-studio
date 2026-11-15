"""Real R03 children, publication consumers and Qt; no model or device execution."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from robot_learning_workbench import run
from test_pipeline_scripts import qt
from test_run_claims import request
from test_worker_protocol import claim_without_spawn


def test_exit_observation_survives_the_short_lived_start_backend(tmp_path):
    req = request(tmp_path)
    intent = tmp_path / 'intent.json'
    intent.write_text(json.dumps(run._plain(req)))
    # Hold the launched process until the start backend has actually exited.
    starter = '''import json,sys
from pathlib import Path
from robot_learning_workbench import run
data=json.loads(Path(sys.argv[1]).read_text())
for key in ('recipe_path','output_path'):data[key]=Path(data[key])
popen=run.subprocess.Popen
delay="import os,sys,time; from pathlib import Path; gate=Path(sys.argv[1]); deadline=time.monotonic()+15\\nwhile not gate.exists() and time.monotonic()<deadline:time.sleep(.01)\\nif not gate.exists():raise SystemExit(99)\\nos.execv(sys.executable,[sys.executable,*sys.argv[2:]])"
def launch(argv,**kw):return popen([argv[0],'-B','-c',delay.replace('\\\\n','\\n'),str(Path(sys.argv[1]).parent/'release'),*argv[1:]],**kw)
run.subprocess.Popen=launch
print(json.dumps(run._plain(run.start(run.StartRequest(**data)))),flush=True)
'''
    result = subprocess.run([sys.executable, '-B', '-c', starter, str(intent)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    handle = json.loads(result.stdout)
    folder = Path(handle['run_dir'])
    assert run.read_status(folder).status == 'prepared'
    (tmp_path / 'release').touch()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = run.read_status(folder)
        if getattr(state, 'exit_code', None) is not None:
            break
        time.sleep(.02)
    assert state.status == 'failed' and state.error['code'] == 'TRAIN_CONFIG_INVALID'
    assert state.exit_code == 1
    assert state.process_error is not None
    report = json.loads((folder / 'process_exit.json').read_text())
    assert not Path(f"/proc/{report['pid']}").exists()  # wait() reaped the execution child.


@pytest.mark.parametrize('code', [0, 7])
def test_actual_producer_exit_backend_and_qt_display_agree(tmp_path, monkeypatch, code):
    handle, _ = claim_without_spawn(tmp_path, monkeypatch)
    (tmp_path / 'handle.json').write_text(json.dumps(run._plain(handle)))
    producer = tmp_path / 'producer.py'
    producer.write_text('''import sys
from pathlib import Path
from robot_learning_workbench import run
from robot_learning_workbench.data import native
sys.path.insert(0,TESTS)
from test_native_dataset import episode,execution
request=run.load_worker_request(Path(sys.argv[1]))
def publish(plan,*,events,commands):
    with native.NativeRun(plan.output_path,execution()) as writer:
        segment=writer.segment('published')
        segment.write_episode(episode(),episode_id='kept')
        segment.commit()
    return run.StageResult('completed',(str(plan.output_path),),completed_episodes=1,
                           attempt_summary={'latest':{'success':False},'successes':0,'failures':1})
result=run.execute(request,_runner=publish)
assert result.status=='completed',result
(request.run_dir/'producer-ready').touch()
sys.stdin.read()
raise SystemExit(EXIT)
'''.replace('TESTS', repr(str(Path(__file__).parent))).replace('EXIT', str(code)))
    qt('''
import hashlib,json,subprocess,sys,threading,time
from dataclasses import asdict
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench import run
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench.ui.session_client import SessionClient
from robot_learning_workbench.ui.operations import run_outcome
app=QApplication([]);root=Path(sys.argv[1]);handle=json.loads((root/'handle.json').read_text());folder=Path(handle['run_dir'])
child=subprocess.Popen([BACKEND,'-B',str(root/'producer.py'),str(folder)],stdin=subprocess.PIPE)
monitor=threading.Thread(target=run._monitor,args=(child,folder));monitor.start()
p=WorkflowPage('offline_validation','/no/worker','modules');p.timer.stop()
client=SessionClient('/no/worker','modules');client.timer.stop();errors=[];terminal=[]
client.error.connect(errors.append);client.terminal.connect(terminal.append)
try:
 deadline=time.monotonic()+15
 while not (folder/'producer-ready').exists():
  assert time.monotonic()<deadline and child.poll() is None
  time.sleep(.02)
 original={str(f.relative_to(root/'output')):hashlib.sha256(f.read_bytes()).hexdigest()for f in(root/'output').rglob('*')if f.is_file()}
 before=run.read_status(folder);assert before.status=='completed'and before.exit_code is None
 p.handle={**handle,'output_path':str(root/'output')};p.poll();before_text=p.state.text()
 assert '종료 미확인'in before_text
 client.handle=handle;client.running=True;client.stage='train';client.poll()
 assert terminal==['completed']and not client.active()and not errors
 child.stdin.close();monitor.join(timeout=10);assert not monitor.is_alive()
 state=run.read_status(folder);assert child.returncode==CODE and state.exit_code==CODE
 backend=subprocess.run([BACKEND,'-B','-m','robot_learning_workbench.cli','status',str(folder)],capture_output=True,text=True,timeout=10)
 assert backend.returncode==0,backend.stderr
 backend_state=json.loads(backend.stdout);assert backend_state['exit_code']==CODE and backend_state['status']=='completed'
 outcome=run_outcome({**json.loads((folder/'run.json').read_text()),**asdict(state)})
 assert outcome['worker_finished']and outcome['process_finished']and outcome['exit_code']==CODE
 assert outcome['task_success']is False and outcome['successes']==0
 p.poll();after_text=p.state.text()
 client.poll();client.poll()
 assert len(errors)==int(bool(CODE))and (not CODE or str(CODE)in errors[0])
 assert terminal==['completed']  # Exit diagnostics do not re-publish the task result.
 assert 'exit '+str(CODE)in after_text and ('비정상 종료'in after_text)==bool(CODE)
 assert 'Task 성공 0 / 실패 1'in after_text
 assert {str(f.relative_to(root/'output')):hashlib.sha256(f.read_bytes()).hexdigest()for f in(root/'output').rglob('*')if f.is_file()}==original
 assert json.loads((folder/'process_exit.json').read_text())['pid']==json.loads((folder/'run.json').read_text())['worker_identity']['pid']
 (root/'ui-backend.json').write_text(json.dumps({'before':before_text,'after':after_text,'backend':backend_state,'actual_returncode':child.returncode},ensure_ascii=False))
finally:
 if child.poll() is None:
  if not child.stdin.closed:child.stdin.close()
  child.wait(timeout=10)
 monitor.join(timeout=10);p.close()
'''.replace('BACKEND', repr(sys.executable)).replace('CODE', str(code)), tmp_path)
    from robot_learning_workbench.data import native
    catalog = native.load_catalog(tmp_path / 'output')
    assert len(catalog.episodes) == 1 and catalog.episodes[0].episode_id == 'kept'
    assert native.read_array(catalog.episodes[0], 'actions').shape == (3, 7)


def test_ui_outcome_preserves_unknown_exit_for_legacy_and_published_task_success():
    from robot_learning_workbench.ui.operations import run_outcome
    old = run_outcome({'status': 'completed', 'attempt_summary': {'latest': {'success': True}}})
    assert old['worker_finished'] and old['task_success'] is True
    assert old['exit_code'] is None and not old['process_finished']
