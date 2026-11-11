import os
import subprocess
from pathlib import Path

def test_scene_prepare_literal_prompt_to_fake_codex_and_fresh_ui_restore(tmp_path):
    """Real Qt save/reopen and Backend handoff; only the CLI answer is Fake."""
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.files import read,write,sha
    from real2sim_builder.evidence import save_scene_memo
    from real2sim_builder.authoring import modeling_tasks,run_codex_modeling
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
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',XDG_CONFIG_HOME=str(tmp_path/'qt-settings'));env.pop('PYTHONHOME',None)
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



def qt_check(tmp_path,code):
    setup='''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QTabWidget,QTableWidget
from real2sim_builder.project import Project
from real2sim_builder.files import read,write
from real2sim_builder import ui_reconstruction as ui
app=QApplication([])
p=Project.create(Path(sys.argv[1]),'simple UI')
# No external account/network access in UI regression fixtures.
ui.ReconstructionDialog.refresh_account=lambda self:None
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',XDG_CONFIG_HOME=str(tmp_path/'qt-settings'));env.pop('PYTHONHOME',None)
    python=Path('workbench_runs/runtime/qt/bin/python3.11').absolute()
    result=subprocess.run([str(python),'-B','-c',setup+code,str(tmp_path)],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_single_screen_retains_config_and_no_heavy_imports(tmp_path):
    qt_check(tmp_path,'''
config={'candidate':'existing','scene_state_id':'layout','objects':{'cup':{'prompt':'cup','asset_manifest':'input/asset.json'}},
 'measurements':[{'id':'cup','dimensions_m':[.1,.1,.1]}],'fitting':{'supports':{'cup':{'support':'table','status':'PROPOSED','source':'estimated','evidence':['photo']}}},'sam':{'python':'saved','model':'saved'}}
write(p.root/'input/reconstruction.yaml',config)
d=ui.ReconstructionDialog(p.root,sys.executable)
assert d.configuration()==config
assert not d.findChildren(QTabWidget)and not d.findChildren(QTableWidget)
assert d.candidate.text()=='existing' and not hasattr(d,'export_button')
assert not any(n.split('.')[0]in('mujoco','torch','pxr','isaaclab')for n in sys.modules)
d.close()
''')


def test_model_and_effort_popups_are_readable_inside_workbench(tmp_path):
    qt_check(tmp_path,'''
from robot_learning_workbench.ui.theme import STYLE
from PyQt6.QtGui import QPalette
app.setStyleSheet(STYLE)
d=ui.ReconstructionDialog(p.root,sys.executable)
d.model.addItems(['model-a','model-b','model-c'])
d.effort.clear();d.effort.addItems(['low','medium','high'])
d.show();app.processEvents()
for combo in (d.model,d.effort):
 combo.showPopup();app.processEvents()
 view=combo.view();palette=view.palette()
 base=palette.color(QPalette.ColorRole.Base)
 text=palette.color(QPalette.ColorRole.Text)
 assert base.lightness()>200 and text.lightness()<80,(base.name(),text.name())
 # Check the actual unselected row background, not only the declared stylesheet.
 image=view.viewport().grab().toImage()
 rect=view.visualRect(combo.model().index(1,0))
 assert image.pixelColor(min(rect.right(),image.width()-1)-12,min(rect.center().y(),image.height()-1)).lightness()>200
 combo.hidePopup()
d.close()
''')


def test_usage_refresh_clears_old_account_and_displays_real_periods(tmp_path):
    qt_check(tmp_path,'''
d=ui.ReconstructionDialog(p.root,sys.executable)
models=[{'model':'test','isDefault':True,'defaultReasoningEffort':'high','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]
snapshot={'version':'test cli','logged_in':True,'account':{'planType':'pro'},'models':models,
 'usage':[{'name':'codex','bucket':'codex','model':None,'minutes':300,'remaining':46,'resets_at':2000000000}]}
d.account_result({'snapshot':snapshot},0)
assert d.model.currentText()=='test' and d.effort.currentData()=='high'
assert any('46%'in label.text()for label in d.findChildren(ui.QLabel))
d.account_result({'error':'조회 실패'},0)
assert d.account is None and d.usage_rows.count()==1
assert d.usage_rows.itemAt(0).widget().text()=='사용량 · 조회 불가'
d.generation=2;d.account_result({'snapshot':snapshot},1);assert d.account is None
d.close()
''')


def test_launch_always_continuous_and_passes_same_auth_and_model(tmp_path):
    qt_check(tmp_path,'''
d=ui.ReconstructionDialog(p.root,sys.executable)
models=[{'model':'test','defaultReasoningEffort':'high','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]
d.account_result({'snapshot':{'version':'test','logged_in':True,'account':{},'models':models,'usage':[]}},0)
ui.runtime_needs=lambda config,**kwargs:[]
commands=[];d.start_cli=lambda args:commands.append(args)
d.launch();assert '--run-modeling'in commands[0] and '--candidate'in commands[0]
assert read(Path(commands[0][commands[0].index('--config')+1]))['candidate']==d.candidate.text()
d.refit=True;d.launch();assert commands[1][0]=='refit-pairs'
assert read(p.root/'working/control.json')if (p.root/'working/control.json').exists()else True
d.close()
''')


def test_failure_does_not_show_old_success_and_runtime_missing_is_actionable(tmp_path):
    qt_check(tmp_path,'''
d=ui.ReconstructionDialog(p.root,sys.executable)
missing=ui.runtime_needs({})
assert not any(any(label in item for label in ('SAM','MASt3R','COLMAP','DA3'))for item in missing)
ui.os.environ['REAL2SIM_BLENDER']='/missing/blender'
assert any('Blender'in item for item in ui.runtime_needs({},refit=True))
assert not any('DA3'in item for item in missing)
d.show_report({'status':'FAILED','error_code':'USAGE_LIMIT'})
assert '계정 전환'in d.summary.toPlainText()
d.show_report({'status':'STOPPED'});assert '이어서 실행'in d.summary.toPlainText()
d.close()
''')


def test_account_switch_uses_official_processes_and_same_private_home(tmp_path):
    qt_check(tmp_path,'''
import os,time
home=Path(sys.argv[1])/'private-auth';os.environ['REAL2SIM_CODEX_HOME']=str(home)
program=Path(sys.argv[1])/'codex'
program.write_text('#!'+sys.executable+'\\nimport os,sys\\nfrom pathlib import Path\\nh=Path(os.environ["CODEX_HOME"]);h.mkdir(exist_ok=True)\\nwith (h/"calls").open("a") as f:f.write(sys.argv[1]+"\\\\n")\\n')
program.chmod(0o700)
ui.codex_cli.executable=lambda:str(program);ui.codex_cli.capabilities=lambda p:{}
d=ui.ReconstructionDialog(p.root,sys.executable);d.account={'logged_in':True}
refreshed=[];d.refresh_account=lambda:refreshed.append(True)
d.authenticate();assert d.account is None
until=time.monotonic()+5
while d.auth_guard is not None and time.monotonic()<until:app.processEvents();time.sleep(.01)
assert d.auth_guard is None and refreshed
assert (home/'calls').read_text().splitlines()==['logout','login']
assert not list(p.root.rglob('auth.json'))
d.close()
''')


def test_failed_launch_never_reuses_previous_success_report(tmp_path):
    qt_check(tmp_path,'''
d=ui.ReconstructionDialog(p.root,sys.executable)
path=p.root/'scratch/agent'/d.candidate.text()/'reconstruction.json';write(path,{'status':'VISUAL_DRAFT_REVIEWED'})
d.report_mtime=path.stat().st_mtime_ns;d.finished(1)
assert '실행 실패'in d.summary.toPlainText()and '완료'not in d.summary.toPlainText()
d.close()
''')


def test_pair_screen_uses_latest_saved_layout_and_resumes_its_candidate(tmp_path):
    qt_check(tmp_path,'''
from real2sim_builder.candidate import Candidate
c=Candidate.create(p,'earlier');p.update(candidate='earlier')
write(p.root/'input/reconstruction.yaml',{'candidate':'earlier','scene_state_id':'old'})
evidence=p.evidence;evidence['images']=[{'scene_state_id':'new','runtime_baseline':{'revision':'rev'}}];write(p.root/'input/evidence.yaml',evidence)
d=ui.ReconstructionDialog(p.root,sys.executable,refit=True)
name=d.candidate.text();assert name!='earlier'and d.configuration()['scene_state_id']=='new'
c=Candidate.create(p,name);info=c.info;info['source_revision']='rev';write(c.root/'candidate.json',info)
scene=c.scene;scene['reconstruction_state']={'id':'new'};write(c.root/'candidate_scene.yaml',scene);p.update(candidate=name)
d.close();again=ui.ReconstructionDialog(p.root,sys.executable,refit=True)
assert again.candidate.text()==name
again.close()
''')


def test_staged_ui_has_per_stage_preflight_and_opens_existing_visual_record(tmp_path):
    qt_check(tmp_path,'''
assert not any('SAM' in n or 'COLMAP' in n or 'MASt3R' in n for n in ui.runtime_needs({'sam':{},'geometry':{'backend':'not-installed'}}))
d=ui.ReconstructionDialog(p.root,sys.executable)
assert hasattr(d,'evidence_button')
assert len(d.stage_labels)==14 and any('SAM3' in title for _,title in d.stage_labels.values())
assert not any('COLMAP' in title for _,title in d.stage_labels.values())
from real2sim_builder.candidate import Candidate
from real2sim_builder.visual_evidence import record
c=Candidate.create(p,d.candidate.text());record(c,'01_scene_analysis','STOPPED',summary='retained')
opened=[]
ui.QDesktopServices.openUrl=lambda url:opened.append(url.toLocalFile())
d.open_evidence()
assert opened==[str(c.root/'evidence/index.html')]
d.close()
''')


def test_stage_progress_and_logout_allow_cpu_and_depth_work_before_codex(tmp_path):
    qt_check(tmp_path,'''
d=ui.ReconstructionDialog(p.root,sys.executable)
assert len(d.stage_labels)==14
commands=[];d.start_cli=lambda args:commands.append(args)
d.pending_start=True
d.account_result({'snapshot':{'version':'test','logged_in':False,'account':{},'models':[],'usage':[]}},0)
assert commands and commands[0][0]=='reconstruct'
d.busy=lambda:True
for stage in (1,2,3,7,10,14):
 p.update(status='RUNNING',stage='STAGE_'+str(stage))
 d.update_progress()
 assert d.stage_labels[str(stage)][0].text().startswith('●')
 assert str(stage) in d.current.text()
d.busy=lambda:False;d.close()
''')
