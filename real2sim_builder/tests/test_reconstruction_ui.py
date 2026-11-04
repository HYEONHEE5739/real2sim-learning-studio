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
 'objects':{'cube':{'category':'block','asset_group':'blocks','asset_group_relation':{'status':'PROPOSED','provenance':'estimated','evidence':['notes']},'prompt':'red cube','images':{'photo':{'box_xyxy':[1,2,30,40]}}}},
 'measurements':[{'id':'cube','kind':'box','role':'manipulable_object','dimensions_m':[.03,.03,.03],'evidence':['caliper']}],
 'fitting':{'max_evaluations':20},'da3':{'process_res':280}})
d=ReconstructionDialog(p.root,sys.executable)
config=d.configuration()
assert config['anchors']=={'photo':{'evidence':['board']}}
assert config['objects']['cube']['images']['photo']['box_xyxy']==[1,2,30,40]
assert config['objects']['cube']['asset_group']=='blocks'and config['objects']['cube']['category']=='block'
assert config['objects']['cube']['asset_group_relation']['provenance']=='estimated'
d.objects.cellWidget(0,9).setCurrentIndex(d.objects.cellWidget(0,9).findData('__new_model__'))
assert d.configuration()['objects']['cube']['modeling_action']=='new'
request=d.configuration()['objects']['cube']['modeling_request_id']
assert d.configuration()['objects']['cube']['modeling_request_id']==request
d.add_object({'id':'cube2','kind':'box','role':'manipulable_object'})
d.objects.item(1,11).setText('blocks')
d.group_asset_choice(d.objects.cellWidget(0,9))
config=d.configuration();assert config['objects']['cube']['modeling_request_id']==config['objects']['cube2']['modeling_request_id']
d.objects.cellWidget(1,9).setCurrentIndex(0);d.group_asset_choice(d.objects.cellWidget(1,9))
assert all('modeling_action'not in q for q in d.configuration()['objects'].values())
assert config['measurements'][0]['dimensions_m']==[.03]*3
assert config['da3']['process_res']==280 and d.objects.rowCount()==2
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
assert 'WAITING_FOR_CODEX_ANALYSIS' in d.summary.toPlainText()
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


def test_unmeasured_analysis_objects_and_model_requests_survive_dialog_reopen(tmp_path):
    code='''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from real2sim_builder.project import Project
from real2sim_builder.files import read,write
from real2sim_builder.ui_reconstruction import ReconstructionDialog
app=QApplication([]);existing=list(Path(sys.argv[1]).glob('*/project.yaml'))
p=Project(existing[0].parent)if existing else Project.create(Path(sys.argv[1]),'reopen')
config={'scene_state_id':'layout','objects':{
 'cup1':{'category':'cup','role':'receptacle','prompt':'paper cup','asset_group':'cups','modeling_action':'new','modeling_request_id':'request_cups'},
 'cup2':{'category':'cup','role':'receptacle','prompt':'paper cup','asset_group':'cups','asset_manifest':'input/object_assets/cups/missing/manifest.json'},
 'red_block':{'category':'cube','role':'manipulable_object','prompt':'red cube'}},
 'selections':{'side':{'cup1':1}},'candidate':'unfinished_candidate'}
if not(p.root/'input/reconstruction.yaml').exists():write(p.root/'input/reconstruction.yaml',config)
for _ in range(2):
 d=ReconstructionDialog(p.root,sys.executable)
 assert d.objects.rowCount()==3
 actual=d.configuration();assert actual['objects']==config['objects'],actual
 assert actual['selections']==config['selections']
 assert d.candidate.text()=='unfinished_candidate'
 write(p.root/'input/reconstruction.yaml',actual);d.close()
assert not any(n.split('.')[0]in('mujoco','torch','pxr','isaaclab')for n in sys.modules)
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen');env.pop('PYTHONHOME',None)
    python=Path('workbench_runs/runtime/qt/bin/python3.11').absolute()
    result=subprocess.run([str(python),'-B','-c',code,str(tmp_path)],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    restarted=subprocess.run([str(python),'-B','-c',code,str(tmp_path)],env=env,capture_output=True,text=True)
    assert restarted.returncode==0,restarted.stdout+restarted.stderr


def test_second_scene_menu_reads_shared_library_and_explicit_delete_is_local(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.object_assets import register_object_asset
    from real2sim_builder.files import write
    from test_object_assets import asset_fixture
    a=Project.create(tmp_path/'scenes','A');b=Project.create(tmp_path/'scenes','B')
    asset=register_object_asset(a,asset_fixture(tmp_path/'asset'),asset_id='cups')
    write(b.root/'input/reconstruction.yaml',{'objects':{n:{'role':'receptacle','category':'cup','asset_group':'cups','asset_manifest':asset['manifest']}for n in('cup1','cup2')}})
    code='''
import sys
from PyQt6.QtWidgets import QApplication
from real2sim_builder.ui_reconstruction import ReconstructionDialog
app=QApplication([]);d=ReconstructionDialog(sys.argv[1],sys.executable)
assert d.asset_list.count()==1 and 'Workspace' in d.asset_list.itemText(0)
assert d.objects.rowCount()==2
assert all(d.objects.cellWidget(r,9).currentData()==d.asset_list.itemData(0)for r in range(2))
d.objects.selectRow(1);d.remove_objects()
assert set(d.configuration()['objects'])=={'cup1'}
assert d.asset_list.count()==1
assert not any(n.split('.')[0]in('mujoco','torch','pxr','isaaclab')for n in sys.modules)
d.close()
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen');env.pop('PYTHONHOME',None)
    python=Path('workbench_runs/runtime/qt/bin/python3.11').absolute()
    result=subprocess.run([str(python),'-B','-c',code,str(b.root)],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_scene_prepare_literal_prompt_to_fake_codex_and_fresh_ui_restore(tmp_path):
    """Real Qt save/reopen and Backend handoff; only the CLI answer is Fake."""
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.files import read,write,sha
    from real2sim_builder.evidence import save_scene_memo
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    from test_scene_memo_contract import reply_for,fake_cli
    from PIL import Image
    p=Project.create(tmp_path/'scenes','UI memo');other=Project.create(tmp_path/'scenes','other')
    save_scene_memo(other,'Other Scene: blue block only.')
    image=tmp_path/'photo.png';Image.new('RGB',(40,30),'white').save(image)
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cups')
    config={'candidate':'memo_ui','scene_state_id':'selected_capture_batch','objects':{
        n:{'prompt':'cup','role':'receptacle','asset_group':'cups','asset_manifest':asset['manifest'],
           'asset_group_relation':{'provenance':'estimated','status':'PROPOSED','source':'visual_inference','evidence':['prior photo guess']}}for n in('cup_left','cup_right')}}
    write(p.root/'input/reconstruction.yaml',config)
    text='先の説明を修正。\r\n오른쪽 컵 두 개는 똑같아. 💜\n'
    ui_code='''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.scene_inputs import SceneInputs
from robot_learning_workbench.scene_preparation import scene_details,save_inputs
from real2sim_builder.ui_reconstruction import ReconstructionDialog
app=QApplication([]);root=Path(sys.argv[1]);panel=SceneInputs(root.parent.parent)
if sys.argv[2]=='save':
 panel.load(scene_details(root));panel.pending=[sys.argv[3]]
 panel.notes.setPlainText('先の説明を修正。\\n오른쪽 컵 두 개는 똑같아. 💜\\n')
 saved=[]
 panel.saveRequested.connect(lambda files,text:saved.append(save_inputs(root,files,text)))
 panel.save.click();assert len(saved)==1 and len(saved[0]['inputs'])==1
else:
 data=scene_details(root);panel.load(data)
 assert panel.note_text()=='先の説明を修正。\\r\\n오른쪽 컵 두 개는 똑같아. 💜\\n'
 panel.saveRequested.connect(lambda files,text:save_inputs(root,files,text));panel.save.click()
 d=ReconstructionDialog(root,sys.executable);config=d.configuration()
 assert config['scene_state_id']=='selected_capture_batch'
 assert set(config['objects'])=={'cup_left','cup_right'}
 assert all(s['asset_manifest']for s in config['objects'].values())
 assert config['objects']['cup_left']['asset_group_relation']['source']=='user_memo'
 d.close()
assert not any(n.split('.')[0]in('mujoco','torch','pxr','isaaclab')for n in sys.modules)
panel.close()
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen');env.pop('PYTHONHOME',None)
    qt=Path('workbench_runs/runtime/qt/bin/python3.11').absolute()
    result=subprocess.run([str(qt),'-B','-c',ui_code,str(p.root),'save',str(image)],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
    # Preserve mixed line endings when loading an existing text file in Qt.
    save_scene_memo(p,text);c=Candidate.create(p,'memo_ui')
    # Current memo differs from the old interpretation: execution must request Codex.
    config['scene_analysis']={'memo_sha256':'old'}
    modeling_tasks(c,config,{})
    fake=tmp_path/'fake_codex';fake_cli(fake,text,__import__('json').dumps(reply_for(text)))
    run_codex_modeling(c,executable=fake,timeout_s=10)
    before={f.relative_to(c.root).as_posix():sha(f)for f in (c.root/'modeling/codex').rglob('*')if f.is_file()}
    result=subprocess.run([str(qt),'-B','-c',ui_code,str(p.root),'restore'],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
    assert (p.root/'input/scene_memo.txt').read_bytes()==text.encode()
    assert before=={f.relative_to(c.root).as_posix():sha(f)for f in (c.root/'modeling/codex').rglob('*')if f.is_file()}
    assert (other.root/'input/scene_memo.txt').read_text()=='Other Scene: blue block only.'
