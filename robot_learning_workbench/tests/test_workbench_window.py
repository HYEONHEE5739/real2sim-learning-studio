import os,subprocess
from pathlib import Path
UI=str(Path(__file__).resolve().parents[2]/'workbench_runs/runtime/qt/bin/python3.11')


def test_real_qt_stage_page_has_no_loss_or_pose_seed_and_dirty_disables_run(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
from pathlib import Path
import sys
app=QApplication([]);root=Path(sys.argv[1]);recipe=root/'r.yaml'
recipe.write_text('schema_version: 1\\nstage: datagen\\nengine: mujoco\\ninputs: {}\\nexecution: {target_successes: 1, max_attempts: 2, seed: 1047}\\noutput: {directory: output}\\nobjects: {}\\n')
w=WorkflowPage('datagen',sys.executable,root/'modules.yaml');w.job.start=lambda *a,**k:None;w.settings.load_script(recipe);w.busy=False
assert not w.editor.dirty and not w.start_button.isEnabled()
w.editor.text.appendPlainText('# max_attempts edited in YAML');assert w.editor.dirty and not w.start_button.isEnabled()
assert not any(x in sys.modules for x in ['torch','mujoco','isaaclab','lerobot'])
w.timer.stop();w.close()
'''
    process=subprocess.run([UI,'-B','-c',code,str(tmp_path)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert process.returncode==0,process.stdout+process.stderr


def test_real_full_workbench_navigation_and_supported_controls(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
from pathlib import Path
import sys
app=QApplication([]);root=Path(sys.argv[1]);w=Window(sys.argv[2],root/'task_modules.yaml',root/'workspace');w.show();app.processEvents()
assert w.navigation.count()==10 and w.stack.count()==10
assert not w.workflows['datagen'].start_button.isEnabled()
assert w.source.previews.keys()=={'side','wrist'}
assert not any(n in sys.modules for n in ['torch','mujoco','isaaclab','lerobot'])
w.close()
from PyQt6.QtTest import QTest
for _ in range(500):app.processEvents();QTest.qWait(10)
assert not w.isVisible()
'''
    p=subprocess.run([UI,'-B','-c',code,str(tmp_path),'/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python'],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr


def test_qt_backend_start_failure_is_terminal_not_busy_forever(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.jobs import BackendJob
app=QApplication([]);j=BackendJob('/no/such/python');rows=[];j.finished.connect(rows.append);j.start('catalog',path='missing')
for _ in range(20):app.processEvents();QTest.qWait(10)
assert rows and not rows[0]['ok']
'''
    p=subprocess.run([UI,'-B','-c',code],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr


def test_annotation_controls_and_review_cleanup(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
from pathlib import Path
import sys
app=QApplication([]);root=Path(sys.argv[1]);w=Window(sys.argv[2],root/'modules.yaml',root/'space')
p=w.workflows['annotation'];assert set(p.commands)=={'pause','resume','step','mark','skip'}
assert not p.commands['mark'].isEnabled()
f=w.curation.preview_directory;f.mkdir(parents=True);(f/'side.ppm').write_bytes(b'x')
w.close()
from PyQt6.QtTest import QTest
for _ in range(500):app.processEvents();QTest.qWait(10)
assert not f.exists()
'''
    p=subprocess.run([UI,'-B','-c',code,str(tmp_path),'/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python'],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr






def test_manual_ui_command_preserves_explicit_episode_env_context(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench import run
from pathlib import Path
from unittest.mock import patch
app=QApplication([]);p=WorkflowPage('annotation','python','modules');p.handle={'run_id':'r','request_id':'i','run_dir':'/tmp/r'};p.context={'tick':215,'episode_id':'source-1','env_index':0};p.mark_frame.setValue(203)
seen=[]
with patch.object(p,'active',return_value=True),patch.object(run,'send_command',side_effect=lambda h,c:seen.append(c) or type('R',(),{'status':'queued'})()):p.command('mark')
assert seen[0]['episode_id']=='source-1' and seen[0]['env_index']==0 and seen[0]['payload']['frame']==203
p.timer.stop()
'''
    p=subprocess.run([UI,'-B','-c',code],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr
