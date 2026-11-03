"""Original Qt presentation with saved Recipe/R03 semantics, without hardware IO."""
import os,subprocess
from pathlib import Path
from test_workbench_window import UI


def qt(script,tmp_path):
    result=subprocess.run([UI,'-B','-c',script,str(tmp_path)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_workflow_has_original_viewer_and_single_visible_script_buffer(tmp_path):
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
assert page.editor.isVisible()and not hasattr(page,'counts')and not hasattr(page,'object_table')
assert page.loss_chart is None
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
assert [window.tabs.tabText(i)for i in range(window.tabs.count())]==['1 · Scene Prepare','2 · Real / Sim','3 · Workspace Pipeline','4 · Precision Calibration']
assert window.navigation_panel.width()==200 and window.navigation.objectName()=='stageNavigation'
p=window.workflows['source'];recipe=root/'source.yaml'
recipe.write_text('schema_version: 1\\nstage: source\\nengine: mujoco\\ninputs: {}\\nexecution: {num_episodes: 1}\\noutput: {directory: source}\\n')
p.settings.load_script(recipe);p.editor.text.setPlainText(p.editor.text.toPlainText().replace('num_episodes: 1','num_episodes: 3'))
for size in ((1320,900),(1920,1080)):
    window.resize(*size);window.show();app.processEvents()
    assert (window.width(),window.height())==size
    window.tabs.setCurrentIndex(2)
    window.navigation.setCurrentRow(window.page_rows['Mimic / Datagen']);app.processEvents()
    assert window.stack.currentWidget() is window.workflows['datagen']
    window.navigation.setCurrentRow(window.page_rows['Source Demo']);app.processEvents()
    assert p.editor.dirty and p.editor.data()['execution']['num_episodes']==3 and not p.start_button.isEnabled()
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
assert not hasattr(page,'trim_start') and not hasattr(page,'result')
assert not page.table.isVisible()
page.advanced_toggle.setChecked(True);app.processEvents()
assert page.table.isVisible()
assert page.train_ratio.mapTo(page, page.train_ratio.rect().center()).y()==page.split_seed.mapTo(page, page.split_seed.rect().center()).y()
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
from PyQt6.QtWidgets import QApplication,QFileDialog,QInputDialog
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
assert p.table.item(0,2).flags() & Qt.ItemFlag.ItemIsEditable
assert p.table.item(0,3).flags() & Qt.ItemFlag.ItemIsEditable
p.table.item(0,2).setText('2');p.table.item(0,3).setText('5')
wait(lambda:not p.busy and getattr(p,'last_review',{}).get('original_frame')==2)
assert p.clock_label.text().startswith('0.00s / 0.07s')
p.seek(1)
wait(lambda:not p.busy and getattr(p,'last_review',{}).get('original_frame')==3)
assert p.dirty and p.timeline.value()==1
assert p.timeline.markers[0]['frame']==1
assert not p.images['side'].pixmap().isNull()
assert p.actions.frame==3 and p.actions.sample_frame==3 and p.trajectory.frame==3
QInputDialog.getText=lambda *a,**kw:('revision',True)
p.save_revision();wait(lambda:bool(p.revision_record)and not p.busy and not p.plot_busy and getattr(p,'last_review',{}).get('original_frame')==2)
assert Path(p.source).is_relative_to(root/'curation') and Path(p.source).name=='revision_r001.json'
assert not p.dirty and p.rows[0]['selection_range']==[2,5]
assert p.frame_range()==(2,5)
assert p.plot_data['original_range']==[2,5]
assert p.clock_label.text().startswith('0.00s / 0.07s') and p.last_review['original_frame']==2
p.seek(0);wait(lambda:not p.busy)
assert p.actions.frame==0 and p.actions.sample_frame==0
assert p.plot_data['frames']==3 and not hasattr(p,'histogram')
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
assert p.references.columnCount()==6 and not p.record.isEnabled()and not p.save_as_button.isEnabled()
for page in (w.workflows['real_evaluation'],):
    assert not any(b.isEnabled() and any(word in b.text()for word in ('힘 풀기','Home','Start Teleop','Torque Enable'))for b in page.findChildren(QPushButton))
w.navigation.setCurrentRow(w.page_rows['Data Curation']);app.processEvents();assert w.curation_dialog.isVisible()
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


def test_source_shortcuts_target_existing_r03_commands_and_keep_script_dirty(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from robot_learning_workbench.ui.source_page import SourcePage
app=QApplication([]);root=Path(sys.argv[1]);p=SourcePage('/no/worker','modules',root);p.show();app.processEvents()
seen=[];p.command=lambda kind:seen.append(kind)
p.commands['save'].setEnabled(True);p.commands['discard'].setEnabled(True)
p.viewer.setFocus();QTest.keyClick(p.viewer,Qt.Key.Key_Right);QTest.keyClick(p.viewer,Qt.Key.Key_Left)
assert seen==['save','discard']
p.editor.text.setPlainText(p.editor.text.toPlainText().replace('num_episodes: 10','num_episodes: 3'))
assert p.editor.dirty and not p.start_button.isEnabled()
p.timer.stop();p.close()
''',tmp_path)


def test_prepare_response_cannot_override_edits_made_during_check(tmp_path):
    qt('''
from pathlib import Path
import sys,hashlib
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);r=root/'r.yaml';r.write_text('schema_version: 1\\nstage: datagen\\nengine: mujoco\\ninputs: {}\\nexecution: {num_episodes: 1}\\noutput: {directory: data}\\n')
p=WorkflowPage('datagen','/no/worker','modules');p.job.start=lambda *a,**k:None;p.settings.load_script(r);p.operation='prepare';p.busy=True
sha=hashlib.sha256(r.read_bytes()).hexdigest();p.editor.text.appendPlainText('# edit while preparing')
p.job_finished({'ok':True,'result':{'runnable':True,'state':'runtime_ready','reason':'ready','recipe_sha256':sha,'prepared_sha256':'old-check'}})
assert p.ready is None and not p.start_button.isEnabled() and p.editor.dirty
p.settings.load_script(r);r.unlink();p.operation='prepare'
p.job_finished({'ok':True,'result':{'runnable':True,'state':'runtime_ready','reason':'ready','recipe_sha256':sha,'prepared_sha256':'old-check'}})
assert p.ready is None and not p.start_button.isEnabled() and ('Recipe'in p.state.text()or 'r.yaml'in p.state.text())
p.timer.stop();p.close()
''',tmp_path)


def test_source_preview_and_training_primary_settings_match_original_priorities(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'space');w.resize(1320,900);w.show();w.tabs.setCurrentIndex(2);w.navigation.setCurrentRow(w.page_rows['Source Demo']);app.processEvents()
p=w.workflows['source'];assert p.previews['side'].height()>=250
w.navigation.setCurrentRow(w.page_rows['모델 학습']);app.processEvents();t=w.workflows['train']
assert t.editor.isVisible()and t.settings.selectors['training_config'].isVisible()
assert not hasattr(t,'training_settings')
w.close();app.processEvents()
''',tmp_path)
