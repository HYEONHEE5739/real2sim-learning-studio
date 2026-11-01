from test_ui_restoration import qt


def test_precision_tab_records_calculates_and_saves_without_separate_activation(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.precision_page import PrecisionPage
app=QApplication([]);w=Window('/no/worker',Path(sys.argv[1])/'modules',Path(sys.argv[1])/'workspace');p=w.sessions['precision'];assert isinstance(p,PrecisionPage)
assert w.tabs.widget(3)is p and 'precision_calibration'not in w.workflows
p.client.running=True;sent=[]
def send(kind,payload=None):
    sent.append((kind,payload));return str(len(sent))
p.client.send=send;p.latest={'torque':0};p.buttons()
p.angle.setValue(0);p.record.click();assert sent[-1]==('precision_record',{'joint':'shoulder_pan','angle_rad':0.})
p.pending.clear()
reference={'reference_id':'one','raw':1500,'angle_rad':0,'split':'train','before_model_rad':0.1}
projection={'kind':'precision_record','result':{},'joint':'shoulder_pan','candidate':{'status':'CALIBRATED_MANUAL','errors_rad':[.001]},'references':[reference]}
p.update_progress({'precision_result':projection});assert p.references.rowCount()==1 and p.save_as_button.isEnabled()
p.joint.setCurrentIndex(2);assert p.references.rowCount()==0
p.pending.clear();p.joint.setCurrentIndex(0);p.pending.clear();assert p.references.item(0,5).text()!='—'
received=[];p.profile_saved.connect(received.append)
saved={'path':'/saved/profile.json','sha256':'a'*64,'configuration_path':'/new/config.yaml','source_configuration_path':'/old/config.yaml'}
p.update_progress({'precision_result':{**projection,'kind':'precision_save','result':saved}})
assert received==[saved]and p.profile_file.text()=='/saved/profile.json'
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
