"""Original Qt presentation with saved Recipe/R03 semantics, without hardware IO."""
import os,subprocess
from pathlib import Path
from test_workbench_window import UI


def qt(script,tmp_path):
    result=subprocess.run([UI,'-B','-c',script,str(tmp_path)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_workflow_has_original_viewer_settings_and_advanced_recipe_boundary(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench.ui.view import CameraView
app=QApplication([]);page=WorkflowPage('datagen',sys.executable,'modules')
page.resize(1320,900);page.show();app.processEvents()
assert page.width()==1320 and page.height()==900
assert page.splitter.widget(0) is page.viewer and page.splitter.widget(1) is page.settings_scroll
assert 320<=page.settings_scroll.width()<=430
assert page.previews.keys()=={'side','wrist'} and all(isinstance(p,CameraView)for p in page.previews.values())
assert page.start_button.objectName()=='primaryAction' and page.cancel_button.objectName()=='stopAction'
assert not page.details.isChecked() and not page.editor.isVisible()
assert not page.input_rows['resume_dataset'].isVisible()
assert page.object_table.isVisible() and page.counts['num_episodes'].isVisible()
assert not page.gripper_button.isVisible() and page.loss_chart is None
page.timer.stop();page.close()
assert not any(n in sys.modules for n in ('torch','lerobot','isaaclab','mujoco','serial'))
''',tmp_path)


def test_theme_and_camera_widget_preserve_original_code(tmp_path):
    qt('''
import ast
from pathlib import Path
from robot_learning_workbench.ui import theme,view
old=Path('/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow')
namespace={};exec(compile((old/'theme.py').read_text(),'original-theme','exec'),namespace)
assert theme.STYLE==namespace['STYLE']
def camera(path):
    tree=ast.parse(path.read_text());return ast.dump(next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='CameraView'),include_attributes=False)
assert camera(old/'view.py')==camera(Path(view.__file__))
''',tmp_path)


def test_original_main_tabs_navigation_and_saved_stage_state_fit_both_sizes(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);window=Window('/no/worker',root/'modules.yaml',root/'workspace')
assert [window.tabs.tabText(i)for i in range(window.tabs.count())]==['1 · Real2Sim Capture','2 · Real / Sim','3 · Workspace Pipeline','4 · Precision Calibration']
assert window.navigation_panel.width()==200 and window.navigation.objectName()=='stageNavigation'
p=window.workflows['source'];recipe=root/'source.yaml'
recipe.write_text('schema_version: 1\\nstage: source\\nengine: mujoco\\ninputs: {}\\nexecution: {num_episodes: 1}\\noutput: {directory: source}\\n')
p.load_recipe(recipe);p.counts['num_episodes'].setValue(3)
for size in ((1320,900),(1920,1080)):
    window.resize(*size);window.show();app.processEvents()
    assert (window.width(),window.height())==size
    window.tabs.setCurrentIndex(2)
    window.navigation.setCurrentRow(4);app.processEvents()
    assert window.stack.currentWidget() is window.workflows['datagen']
    window.navigation.setCurrentRow(1);app.processEvents()
    assert p.editor.dirty and p.counts['num_episodes'].value()==3 and not p.start_button.isEnabled()
window.close();app.processEvents();assert not window.isVisible()
assert not any(n in sys.modules for n in ('torch','lerobot','isaaclab','mujoco','serial'))
''',tmp_path)


def test_curation_keeps_original_episode_video_timeline_and_folded_tools(tmp_path):
    qt('''
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.curation import CurationPage
from robot_learning_workbench.ui.view import CameraView,EventTimeline
import sys
app=QApplication([]);page=CurationPage('/no/worker',Path(sys.argv[1]));page.resize(1320,900);page.show();app.processEvents()
assert page.splitter.widget(0) is page.episode_panel
assert isinstance(page.timeline,EventTimeline)
assert all(isinstance(v,CameraView)for v in page.images.values())
assert not page.analysis_panel.isVisible() and not page.advanced_panel.isVisible()
assert page.preview_tabs.count()>=2 and page.play_button.isVisible()
assert page.trim_start.isVisible() and page.trim_stop.isVisible()
page.close()
''',tmp_path)


def test_episode_plot_is_bounded_and_uses_recorded_targets_and_selection(tmp_path):
    import numpy as np
    from test_native_dataset import execution,episode
    from robot_learning_workbench.data.native import NativeRun
    from robot_learning_workbench.data.curation import save_curation
    from robot_learning_workbench.ui.operations import execute
    with NativeRun(tmp_path/'original',execution())as owner:
        segment=owner.segment('one');segment.write_episode(episode(700),episode_id='ep');segment.commit()
    save_curation(tmp_path/'view.json',owner.root,frame_ranges={'ep':(20,650)})
    result=execute({'operation':'episode_plot','arguments':{'source':str(tmp_path/'view.json'),'selection_id':'ep'}})
    assert result['frames']==630 and result['original_range']==[20,650]
    assert 1<=len(result['indices'])<=512 and result['indices'][0]==0 and result['indices'][-1]==629
    np.testing.assert_array_equal(result['targets'],np.ones((len(result['indices']),6)))
    assert result['target_unit']=='rad' and result['eef'] is None and result['events']=={}


def test_actual_backend_curation_trim_frame_and_revision_roundtrip(tmp_path):
    from robot_learning_workbench.data import native as n
    from robot_learning_workbench.data.video import AsyncVideoWriter
    from test_native_dataset import execution,episode
    import numpy as np,sys
    video=tmp_path/'camera.mp4';writer=AsyncVideoWriter(video,width=64,height=48)
    for i in range(6):writer.write(np.full((48,64,3),i*30,np.uint8))
    writer.close()
    with n.NativeRun(tmp_path/'source',execution())as owner:
        segment=owner.segment('one');e=episode(6)
        import torch
        e.data['obs']['datagen_info']={'subtask_term_signals':{'grasp':torch.tensor([[0],[0],[0],[1],[1],[1]],dtype=torch.uint8)}}
        segment.write_episode(e,episode_id='ep',media={'side':video});segment.commit()
    before=n.file_sha256(n.load_catalog(owner.root).episodes[0].file)
    qt('''
from pathlib import Path
import sys,time,json
from PyQt6.QtWidgets import QApplication,QFileDialog
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.curation import CurationPage
app=QApplication([]);root=Path(sys.argv[1]);p=CurationPage("BACKEND_PYTHON",root);p.show()
def wait(condition):
    end=time.monotonic()+30
    while not condition():
        if time.monotonic()>end:raise AssertionError(p.state.text()+p.metrics.text())
        app.processEvents();QTest.qWait(10)
p.load_source(root/'source');wait(lambda:len(p.rows)==1 and not p.busy and not p.plot_busy)
assert p.episode_list.count()==1 and p.table.currentRow()==0
from PyQt6.QtCore import Qt
assert not(p.table.item(0,2).flags() & Qt.ItemFlag.ItemIsEditable)
assert not(p.table.item(0,3).flags() & Qt.ItemFlag.ItemIsEditable)
p.trim_start.setValue(2);p.trim_stop.setValue(5)
wait(lambda:not p.busy and getattr(p,'last_review',{}).get('original_frame')==2)
assert p.clock_label.text().startswith('0 / 2')
p.seek(1)
wait(lambda:not p.busy and getattr(p,'last_review',{}).get('original_frame')==3)
assert p.dirty and p.frame.value()==1 and p.timeline.value()==1
assert p.timeline.markers[0]['frame']==1
assert not p.images['side'].pixmap().isNull()
assert p.actions.frame==3 and p.actions.sample_frame==3 and p.trajectory.frame==3
QFileDialog.getSaveFileName=lambda *a,**kw:(str(root/'revision.json'),'JSON')
p.save_revision();wait(lambda:p.source==str(root/'revision.json')and not p.busy and not p.plot_busy)
assert not p.dirty and p.rows[0]['selection_range']==[2,5]
assert p.trim_start.value()==2 and p.trim_stop.value()==5
assert p.plot_data['original_range']==[2,5]
assert p.clock_label.text().startswith('0 / 2') and p.last_review['original_frame']==2
p.seek(0);wait(lambda:not p.busy)
assert p.actions.frame==0 and p.actions.sample_frame==0
p.analyze();wait(lambda:not p.busy)
assert p.histogram.series[0]['scope']['frames']==3
assert p.histogram.series[0]['fields']['joint_targets']['count']==3
p.analysis_toggle.setChecked(True);app.processEvents()
p.preview_tabs.setCurrentIndex(1);app.processEvents()
p.close();app.processEvents()
'''.replace('BACKEND_PYTHON',sys.executable),tmp_path)
    assert n.file_sha256(n.load_catalog(owner.root).episodes[0].file)==before


def test_dedicated_hardware_tabs_preserve_precision_and_require_explicit_motion_approval(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication,QPushButton
from robot_learning_workbench.ui.app import Window
app=QApplication([]);w=Window('/no/worker',Path(sys.argv[1])/'modules',Path(sys.argv[1])/'space');w.show();app.processEvents()
c=w.sessions['capture'];r=w.sessions['real_sim'];p=w.sessions['precision']
assert hasattr(c,'snapshot_table')and hasattr(c,'client')
assert set(r.previews)=={'side','wrist','sim_side','sim_wrist'}
assert not c.start_teleop_button.isEnabled()and not hasattr(r,'start_teleop_button')
assert p.references.columnCount()==6 and not p.record.isEnabled()and not p.apply_button.isEnabled()
for page in (w.workflows['real_evaluation'],):
    assert not page.gripper_button.isEnabled()
    assert not any(b.isEnabled() and any(word in b.text()for word in ('힘 풀기','Home','Start Teleop','Torque Enable'))for b in page.findChildren(QPushButton))
w.navigation.setCurrentRow(5);app.processEvents();assert w.curation_dialog.isVisible()
w.curation_dialog.close();w.close();app.processEvents()
''',tmp_path)


def test_precision_presentation_is_a_read_only_projection_of_existing_profile(tmp_path):
    from test_precision_calibration import INV
    from robot_learning_workbench.ui.operations import execute
    from robot_learning_workbench.data.native import file_sha256
    path=INV['roles']['follower']['profile_path'];before=file_sha256(path)
    result=execute({'operation':'precision_profile','arguments':{'path':path}})
    assert result['role']=='follower' and len(result['joints'])==6
    assert result['physical_verified'] is False and result['source_sha256']==before
    assert result['references'] and all('joint'in row and 'raw'in row for row in result['references'])
    assert file_sha256(path)==before


def test_source_shortcuts_target_existing_r03_commands_and_keep_recipe_dirty(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('source','/no/worker','modules');p.show();app.processEvents()
seen=[];p.command=lambda kind:seen.append(kind)
p.commands['save'].setEnabled(True);p.commands['discard'].setEnabled(True)
p.viewer.setFocus();QTest.keyClick(p.viewer,Qt.Key.Key_Right);QTest.keyClick(p.viewer,Qt.Key.Key_Left)
assert seen==['save','discard']
r=root/'source.yaml';r.write_text('schema_version: 1\\nstage: source\\nengine: mujoco\\ninputs: {source_dataset: recorded}\\nexecution: {num_episodes: 1}\\noutput: {directory: data}\\n')
p.load_recipe(r);assert p.input_rows['device_profile'].isHidden()
p.source_kind.setCurrentIndex(1)
assert p.editor.dirty and 'source_dataset'not in p.editor.data()['inputs'] and not p.input_rows['device_profile'].isHidden()
assert '편집'in p.recipe_status.text() and not p.start_button.isEnabled()
p.timer.stop();p.close()
''',tmp_path)


def test_prepare_response_cannot_override_edits_made_during_check(tmp_path):
    qt('''
from pathlib import Path
import sys,hashlib
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);r=root/'r.yaml';r.write_text('schema_version: 1\\nstage: datagen\\nengine: mujoco\\ninputs: {}\\nexecution: {num_episodes: 1}\\noutput: {directory: data}\\n')
p=WorkflowPage('datagen','/no/worker','modules');p.load_recipe(r);p.operation='prepare';p.busy=True
sha=hashlib.sha256(r.read_bytes()).hexdigest();p.counts['env_num'].setValue(2)
p.job_finished({'ok':True,'result':{'runnable':True,'state':'runtime_ready','reason':'ready','recipe_sha256':sha,'prepared_sha256':'old-check'}})
assert p.ready is None and not p.start_button.isEnabled() and p.editor.dirty
p.load_recipe(r);r.unlink();p.operation='prepare'
p.job_finished({'ok':True,'result':{'runnable':True,'state':'runtime_ready','reason':'ready','recipe_sha256':sha,'prepared_sha256':'old-check'}})
assert p.ready is None and not p.start_button.isEnabled() and 'Recipe'in p.state.text()
p.timer.stop();p.close()
''',tmp_path)


def test_source_preview_and_training_primary_settings_match_original_priorities(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'space');w.resize(1320,900);w.show();w.tabs.setCurrentIndex(2);w.navigation.setCurrentRow(1);app.processEvents()
p=w.workflows['source'];assert p.previews['side'].height()>=250
w.navigation.setCurrentRow(6);app.processEvents();t=w.workflows['train']
assert t.input_rows['policy'].isHidden() and t.input_rows['checkpoint'].isHidden()
assert t.training_settings.mapTo(t.settings_content,t.training_settings.rect().topLeft()).y()<400
w.close();app.processEvents()
''',tmp_path)


def test_source_env_selector_follows_edited_environment_count(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('source','/no/worker','modules');p.show()
r=root/'source.yaml';r.write_text('schema_version: 1\\nstage: source\\nengine: mujoco\\ninputs: {}\\nexecution: {env_num: 1, num_episodes: 1}\\noutput: {directory: output}\\n')
p.load_recipe(r);app.processEvents();assert not p.preview_env.isVisible()
p.counts['env_num'].setValue(4);app.processEvents()
assert p.preview_env.isVisible() and p.preview_env.maximum()==3
p.counts['env_num'].setValue(1);app.processEvents();assert not p.preview_env.isVisible()
p.timer.stop();p.close()
''',tmp_path)


def test_saved_episode_training_and_fractional_time_settings_are_displayed_truthfully(tmp_path):
    qt('''
import json,sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QLabel
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('datagen','/no/worker','modules')
r=root/'r.yaml';r.write_text('schema_version: 1\\nstage: datagen\\nengine: mujoco\\ninputs: {}\\nexecution: {num_episodes: 2, resume: true}\\noutput: {directory: data}\\n')
p.load_recipe(r);assert any(l.text()=='추가 Episode 수'for l in p.findChildren(QLabel))
r.write_text(r.read_text().replace('num_episodes: 2','target_successes: 3'));p.load_recipe(r)
assert any('누적 Episode 목표'in l.text()for l in p.findChildren(QLabel))
p.counts['num_episodes'].setValue(4);assert p.editor.data()['execution']['num_episodes']==4
assert any(l.text()=='추가 Episode 수'for l in p.findChildren(QLabel))
p.timer.stop();p.close()
t=WorkflowPage('train','/no/worker','modules');cfg=root/'config.json';cfg.write_text(json.dumps({'policy':{'type':'act','device':'cuda'},'steps':7,'batch_size':3}))
r.write_text('schema_version: 1\\nstage: train\\ninputs: {training_config: config.json, dataset: data}\\nexecution: {mode: scratch}\\noutput: {directory: model}\\n')
t.load_recipe(r);assert t.training_settings.steps.value()==7 and t.training_settings.batch.value()==3 and t.training_settings.device.currentText()=='cuda'
assert not t.editor.dirty and not t.edit_error
t.training_settings.operation='catalog';t.training_settings.received({'ok':True,'result':{'policies':[{'type':'act','error':None},{'type':'diffusion','error':None}]}})
assert not t.edit_error and t.training_settings.model.currentText()=='act'
t.timer.stop();t.close()
e=WorkflowPage('simulation_evaluation','/no/worker','modules');r.write_text('schema_version: 1\\nstage: simulation_evaluation\\nengine: mujoco\\ninputs: {}\\nexecution: {episodes: 1, timeout_s: 0.2}\\noutput: {directory: evaluation}\\n')
e.load_recipe(r);assert e.counts['timeout_s'].value()==0.2 and not e.editor.dirty
e.timer.stop();e.close()
''',tmp_path)
