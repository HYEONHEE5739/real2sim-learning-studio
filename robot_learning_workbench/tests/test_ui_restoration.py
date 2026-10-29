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
p.trim_start.setValue(2);p.trim_stop.setValue(5);p.seek(1)
wait(lambda:not p.busy and getattr(p,'last_review',{}).get('original_frame')==3)
assert p.dirty and p.frame.value()==1 and p.timeline.value()==1
assert p.timeline.markers[0]['frame']==1
assert not p.images['side'].pixmap().isNull()
QFileDialog.getSaveFileName=lambda *a,**kw:(str(root/'revision.json'),'JSON')
p.save_revision();wait(lambda:p.source==str(root/'revision.json')and not p.busy and not p.plot_busy)
assert not p.dirty and p.rows[0]['selection_range']==[2,5]
p.analyze();wait(lambda:not p.busy)
assert p.histogram.series[0]['scope']['frames']==3
assert p.histogram.series[0]['fields']['joint_targets']['count']==3
p.analysis_toggle.setChecked(True);app.processEvents()
p.preview_tabs.setCurrentIndex(1);app.processEvents()
p.close();app.processEvents()
'''.replace('BACKEND_PYTHON',sys.executable),tmp_path)
    assert n.file_sha256(n.load_catalog(owner.root).episodes[0].file)==before
