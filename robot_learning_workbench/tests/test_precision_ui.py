from test_ui_restoration import qt


def test_precision_tab_records_references_and_applies_only_an_explicit_saved_revision(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.precision_page import PrecisionPage
app=QApplication([]);w=Window('/no/worker',Path(sys.argv[1])/'modules',Path(sys.argv[1])/'workspace');p=w.sessions['precision'];assert isinstance(p,PrecisionPage)
assert w.tabs.widget(3)is p and 'precision_calibration'not in w.workflows
p.client.running=True;sent=[];p.client.send=lambda kind,payload=None:sent.append((kind,payload));p.buttons()
p.angle.setValue(0);p.record.click();assert sent[-1]==('precision_record',{'joint':'shoulder_pan','angle_rad':0.,'split':'train'})
p.split.setCurrentIndex(1);p.angle.setValue(45);p.record.click();assert sent[-1][1]['split']=='validation'
reference={'reference_id':'one','raw':1500,'angle_rad':0,'split':'train','before_model_rad':0.1}
projection={'kind':'precision_fit','result':{},'joint':'shoulder_pan','candidate':{'status':'VALIDATED_MANUAL','errors_rad':[.001]},'references':[reference]}
p.update_progress({'precision_result':projection});assert p.references.rowCount()==1 and not p.apply_button.isEnabled()
p.joint.setCurrentIndex(2);assert 'VALIDATED_MANUAL'not in p.fit_result.text()
p.update_progress({'precision_result':projection});assert p.references.rowCount()==0
p.joint.setCurrentIndex(0);p.update_progress({'precision_result':{**projection,'kind':'precision_select'}});assert p.references.item(0,5).text()!='—'
p.update_progress({'precision_result':{'kind':'precision_save','result':{'path':'/saved/profile.json','sha256':'a'*64},'joint':'shoulder_pan','candidate':None,'references':[]}});assert p.apply_button.isEnabled()
assert 'precision_activate'not in [r[0]for r in sent]
received=[];p.activated.connect(received.append);p.update_progress({'precision_result':{'kind':'precision_activate','result':{'configuration_path':'/new/config.yaml','source_configuration_path':'/old/config.yaml'},'joint':'shoulder_pan','candidate':None,'references':[]}});assert received
p.client.running=False;w.close();app.processEvents()
''',tmp_path)


def test_real_sim_export_refresh_preserves_revision_and_disables_undeclared_engines(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.real_sim_page import RealSimPage
app=QApplication([]);root=Path(sys.argv[1]);p=RealSimPage('/no/worker','modules',root);calls=[];p.job.start=lambda op,**args:calls.append((op,args))
row={'name':'Authored','revision':'r1','project_id':'project-one','scene_id':'scene-one','project':str(root/'scenes/one'),'scene':str(root/'scenes/one/exports/r1/scene.json'),'engines':['mujoco']}
p.loaded({'ok':True,'result':{'scenes':[row]}});assert p.scene_combo.currentData()['revision']=='r1'
assert not p.engine.model().item(1).isEnabled()and 'project-one'in p.scene_combo.currentText()
(root/'scenes/one').mkdir(parents=True);(root/'scenes/one/project.yaml').write_text('owned')
p.refresh_scenes(force=True);assert calls[-1][0]=='session_execution_scenes'and not p.client.active()
p.client.running=True;n=len(calls);p.refresh_scenes(force=True);assert len(calls)==n
p.client.running=False;p.template={'ready':True};p.project={'project':'old'};p.loaded({'ok':True,'result':{'scenes':[]}});p.buttons();assert p.template is None and p.project is None and not p.connect_button.isEnabled()
p.stop_timers();p.close()
''',tmp_path)
