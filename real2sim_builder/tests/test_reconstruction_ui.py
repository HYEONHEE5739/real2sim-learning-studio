import os
import subprocess
from pathlib import Path


def test_shared_form_preserves_advanced_configuration_and_requires_no_model_import(tmp_path):
    code='''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from real2sim_builder.project import Project
from real2sim_builder.files import write
from real2sim_builder.ui_reconstruction import ReconstructionDialog
app=QApplication([]);p=Project.create(Path(sys.argv[1]),'form')
write(p.root/'input/reconstruction.yaml',{'scene_state_id':'layout','anchors':{'photo':{'evidence':['board']}},
 'objects':{'cube':{'prompt':'red cube','images':{'photo':{'box_xyxy':[1,2,30,40]}}}},
 'measurements':[{'id':'cube','kind':'box','role':'manipulable_object','dimensions_m':[.03,.03,.03],'evidence':['caliper']}],
 'fitting':{'max_evaluations':20},'da3':{'process_res':280}})
d=ReconstructionDialog(p.root,sys.executable)
config=d.configuration()
assert config['anchors']=={'photo':{'evidence':['board']}}
assert config['objects']['cube']['images']['photo']['box_xyxy']==[1,2,30,40]
assert config['measurements'][0]['dimensions_m']==[.03]*3
assert config['da3']['process_res']==280 and d.objects.rowCount()==1
assert not any(name.split('.')[0]in('mujoco','torch','pxr','isaaclab')for name in sys.modules)
d.close();print('shared form metadata retained without AI/engine imports')
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen');env.pop('PYTHONHOME',None)
    python=Path('workbench_runs/runtime/qt/bin/python3.11').absolute()
    result=subprocess.run([str(python),'-B','-c',code,str(tmp_path)],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_actual_form_saves_configuration_runs_cli_and_displays_missing_data(tmp_path):
    code='''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from real2sim_builder.project import Project
from real2sim_builder.files import read
from real2sim_builder.ui_reconstruction import ReconstructionDialog
app=QApplication([]);p=Project.create(Path(sys.argv[1]),'actual form')
d=ReconstructionDialog(p.root,'/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python')
d.show();app.processEvents();d.run()
assert d.process.waitForFinished(10000),d.summary.toPlainText()
app.processEvents()
assert d.process.exitCode()==2,d.summary.toPlainText()
assert 'NEEDS_MORE_DATA' in d.summary.toPlainText()
assert (p.root/'input/reconstruction.yaml').is_file()
assert (p.root/'scratch/agent'/d.candidate.text()/'reconstruction.json').is_file()
assert not (p.root/'working/current_scene.yaml').exists()
assert not any(name.split('.')[0]in('mujoco','torch','pxr','isaaclab')for name in sys.modules)
from real2sim_builder.candidate import Candidate
Candidate(p,d.candidate.text()).reject()
d.run();assert d.process.waitForFinished(10000);app.processEvents()
assert d.process.exitCode()==1 and '실행 실패' in d.summary.toPlainText(),d.summary.toPlainText()
d.close();print('actual Qt to CLI, missing data preserved, no model/hardware launch')
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen');env.pop('PYTHONHOME',None)
    python=Path('workbench_runs/runtime/qt/bin/python3.11').absolute()
    result=subprocess.run([str(python),'-B','-c',code,str(tmp_path)],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
