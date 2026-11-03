"""Review hints and recorded object positions remain selectable, not verdicts."""
import os,subprocess
from test_workbench_window import UI


def test_quality_overview_selects_recorded_initial_positions_and_explains_hints():
    code='''
from PyQt6.QtWidgets import QApplication,QPushButton
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from robot_learning_workbench.ui.curation_quality import QualityOverview
app=QApplication([]);panel=QualityOverview();panel.resize(1100,560);panel.show()
rows=[dict(selection_id='e1',quality=dict(flags=['EE 정지 비율 높음'],initial_objects={'cube_red':[.1,.2,.03]},duration=2.,stop_fraction=.9,command_stop_fraction=.2,jitter=3.,gripper_jitter=4.)),dict(selection_id='e2',quality=dict(flags=[],initial_objects={'cube_red':[.3,.2,.03]}))]
for row in rows:row.update(success_source='recording_only',recorded_success=None)
panel.set_rows(rows,['cube_red']);panel.select(0);app.processEvents()
assert not {'다른 Dataset 배치 비교','비교 지우기'}&{b.text()for b in panel.findChildren(QPushButton)}
assert panel.objects.currentText()=='cube_red'
assert len(panel.scatter.rows)==2
assert '확인 필요'in panel.summary.text() and '90.0%'in panel.summary.text()
assert 'RMS'not in panel.summary.text()
assert panel.scatter.width()>panel.width()*.85
assert panel.summary.height()<100
region={'support':[[-.5,-.5],[.5,-.5],[.5,.5],[-.5,.5]],'allowed':[[.09,.19],[.31,.19],[.31,.21],[.09,.21]],'robot_xy':[0.,0.]}
panel.regions={'cube_red':region};panel.refresh();app.processEvents()
assert abs(panel.scatter.screen[1].x()-panel.scatter.screen[0].x())>400
rows[0]['quality']['initial_objects']['cube_blue']=[.2,.2,.03]
panel.set_rows(rows,['cube_blue']);app.processEvents()
assert panel.objects.count()==1 and panel.objects.currentText()=='cube_blue'
assert len(panel.scatter.rows)==1
panel.set_rows(rows,['cube_red']);panel.select(0);app.processEvents()
hits=[];panel.selected.connect(hits.append)
point=panel.scatter.screen[1].toPoint();QTest.mouseClick(panel.scatter,Qt.MouseButton.LeftButton,pos=point)
assert hits==[1],hits
panel.set_selection([dict(included=False,split='train'),dict(included=True,split='val')]);app.processEvents()
assert not panel.scatter.rows[0]['included'] and panel.scatter.rows[1]['split']=='val'
assert len(panel.scatter.rows)==2
assert panel.scatter.has_splits()
panel.set_rows([dict(selection_id='official',quality=dict(flags=[],initial_objects={}))]);app.processEvents()
assert not panel.scatter.rows and '없'in panel.position_note.text()
panel.close()
'''
    result=subprocess.run([UI,'-B','-c',code],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
