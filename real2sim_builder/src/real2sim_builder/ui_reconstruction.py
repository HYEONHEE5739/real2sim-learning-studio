"""Single reconstruction control screen. Saved Project inputs remain backend-owned."""
from scene_contract.naming import numbered_path
import copy
import json
import os
from pathlib import Path
import tempfile
import time
from PyQt6.QtCore import QProcess,QProcessEnvironment,QThread,QTimer,QSettings,pyqtSignal
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QPushButton,QPlainTextEdit,QGroupBox,QProgressBar)
from .project import Project
from .files import read,write
from . import codex_cli


class AccountQuery(QThread):
    result=pyqtSignal(object)
    def run(self):
        try:self.result.emit({'snapshot':codex_cli.snapshot()})
        except Exception as error:self.result.emit({'error':str(error)})


def saved_configuration(project,candidate):
    """Read the latest typed plan; opening this UI never edits Scene inputs."""
    path=project.root/'input/reconstruction.yaml'
    result=copy.deepcopy(read(path)if path.is_file()else{})
    # A stopped structural review may already have a newer Candidate-local plan.
    review=project.root/'scratch/agent'/candidate/'review-config.yaml'
    if review.is_file():result=copy.deepcopy(read(review))
    result['candidate']=candidate
    if not result.get('scene_state_id'):
        photos=[i for i in project.evidence['images']if i.get('role')=='scene_photo']
        states=[i.get('scene_state_id')for i in (photos or project.evidence['images'])if i.get('scene_state_id')and i.get('role')!='model_reference']
        if states:result['scene_state_id']=states[-1]
    return result


def runtime_needs(config,*,refit=False):
    from .sfm import backend
    needs=[]
    geometry=config.get('geometry',{});selected=backend(config)
    runtimes=[('SAM3.1',config.get('sam',{}),True)]
    if selected=='mast3r_colmap'and not refit:
        runtimes.extend([('MASt3R',geometry,True),('COLMAP',{'python':geometry.get('colmap_python')},False)])
    for label,spec,checkpoint in runtimes:
        python=Path(spec.get('python')or'/nonexistent')
        model=Path(spec.get('model')or'/nonexistent')
        if not python.is_file()or not os.access(python,os.X_OK):needs.append(label+': 저장된 Python 실행 경로가 없습니다.')
        if checkpoint and not model.exists():needs.append(label+': 저장된 로컬 모델 경로가 없습니다.')
    if selected=='mast3r_colmap'and not refit and not(Path(geometry.get('source')or'/nonexistent')/'mast3r/model.py').is_file():
        needs.append('MASt3R: 저장된 공식 소스 경로가 없습니다.')
    return needs


class ReconstructionDialog(QDialog):
    def __init__(self,project,python,parent=None,*,refit=False,source_scene=None,capture_ids=None):
        super().__init__(parent)
        self.project=Project(project);self.python=str(python);self.refit=refit
        self.source_identity=None
        self.capture_ids=list(capture_ids or[])
        if source_scene:
            from scene_contract.package import load_scene
            from dataclasses import asdict
            path=Path(source_scene).resolve()
            if not path.is_relative_to(self.project.root):raise ValueError('Refit source belongs to another Project')
            self.source_identity=asdict(load_scene(path).identity)
        if Path(codex_cli.environment()['CODEX_HOME']).is_relative_to(self.project.root):raise ValueError('Codex 인증 폴더는 Project 밖에 있어야 합니다.')
        self.process=QProcess(self);self.auth_process=QProcess(self)
        self.query=None;self.account=None;self.pending_start=False;self.pending_close=False
        self.auth_guard=None;self.temporary=None;self.generation=0;self.report_started=False
        self.preferences=QSettings('Real2Sim','BuilderCodex')
        saved=read(self.project.root/'input/reconstruction.yaml')if(self.project.root/'input/reconstruction.yaml').is_file()else{}
        name=saved.get('candidate')or self.project.state.get('candidate')or numbered_path(self.project.root/'scratch/agent','auto').name
        if refit:
            name=self.project.state.get('candidate')or name
            root=self.project.root/'scratch/agent'/name
            info=read(root/'candidate.json')if(root/'candidate.json').is_file()else{}
            scene=read(root/'candidate_scene.yaml')if(root/'candidate_scene.yaml').is_file()else{}
            states=[i.get('scene_state_id')for i in self.project.evidence['images']if i.get('runtime_baseline')and i.get('scene_state_id')]
            layout=states[-1]if states else None
            if not info.get('source_revision')or scene.get('reconstruction_state',{}).get('id')!=layout or(self.source_identity and info['source_revision']['identity']!=self.source_identity):name=numbered_path(self.project.root/'scratch/agent','refit').name
        from .scene import identifier
        identifier(name);self.candidate=QLabel(name)
        self.setWindowTitle('Auto Reconstruction');self.resize(800,830)
        self.setStyleSheet('''
QDialog { background:#f7f9fa; color:#18212b; }
QLabel,QGroupBox { color:#18212b; }
QGroupBox { background:white; border:1px solid #dce2e7; border-radius:12px; margin-top:16px; padding:16px 12px 12px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 5px; }
QComboBox,QPlainTextEdit { background:white; color:#18212b; border:1px solid #dce2e7; border-radius:6px; padding:6px; }
QComboBox QAbstractItemView { background:white; color:#18212b; selection-background-color:#237b65; selection-color:white; border:1px solid #cdd6dd; outline:0; }
QComboBox QAbstractItemView::item { background:white; color:#18212b; min-height:26px; }
QComboBox QAbstractItemView::item:selected { background:#237b65; color:white; }
QPushButton { background:white; color:#18212b; border:1px solid #cdd6dd; border-radius:12px; padding:9px 14px; }
QPushButton:hover { background:#e7f5f0; }
QPushButton:disabled { color:#87929b; background:#eff2f4; }
QProgressBar { background:#edf0f2; border:0; border-radius:4px; }
QProgressBar::chunk { background:#16a085; border-radius:4px; }
''')
        layout=QVBoxLayout(self);layout.setSpacing(14)
        title=QLabel('Auto Reconstruction');title.setStyleSheet('font-size:22px;font-weight:600');layout.addWidget(title)
        cli=QGroupBox('Codex CLI');form=QVBoxLayout(cli);layout.addWidget(cli)
        self.login_status=QLabel('로그인 상태 확인 중…');form.addWidget(self.login_status)
        self.version=QLabel();form.addWidget(self.version)
        models=QHBoxLayout();form.addLayout(models)
        self.model=QComboBox();self.model.setEditable(True);self.model.setMinimumWidth(270)
        self.effort=QComboBox()
        models.addWidget(QLabel('모델'));models.addWidget(self.model,1);models.addWidget(QLabel('추론 강도'));models.addWidget(self.effort,1)
        self.model.currentTextChanged.connect(self.model_changed)
        self.usage_box=QVBoxLayout();form.addLayout(self.usage_box)
        self.usage_title=QLabel('Usage & Limits');self.usage_title.setStyleSheet('font-weight:600');self.usage_box.addWidget(self.usage_title)
        self.usage_rows=QVBoxLayout();self.usage_box.addLayout(self.usage_rows)
        row=QHBoxLayout();form.addLayout(row)
        self.refresh=QPushButton('사용량 새로고침');self.refresh.clicked.connect(lambda:self.refresh_account());row.addWidget(self.refresh)
        self.login=QPushButton('로그인');self.login.clicked.connect(self.authenticate);row.addWidget(self.login)
        scene=QGroupBox('Scene');scene_layout=QVBoxLayout(scene);layout.addWidget(scene)
        scene_layout.addWidget(QLabel(self.project.info['name']));scene_layout.addWidget(self.candidate)
        scene_layout.addWidget(QLabel('저장된 Evidence · Capture · Scene Memo 자동 사용'))
        progress=QGroupBox('Scene 제작 진행 상황');steps=QVBoxLayout(progress);layout.addWidget(progress)
        self.stage_labels={}
        from .sfm import backend
        backend(saved);perception='SAM3.1 / MASt3R / COLMAP'
        for key,title in (('analysis','장면 분석'),('inference',perception),('modeling','Blender USDA 제작'),
                          ('camera','Camera / Scale 초기화'),('fitting','Real/Sim 정합 및 Codex 수정 검토'),('checkpoint','최선 결과 저장')):
            label=QLabel('○ '+title);steps.addWidget(label);self.stage_labels[key]=(label,title)
        self.current=QLabel('저장된 작업 확인 중…');self.current.setWordWrap(True);steps.addWidget(self.current)
        row=QHBoxLayout();layout.addLayout(row)
        self.start=QPushButton('생성 시작 / 이어서 실행');self.start.clicked.connect(self.run);row.addWidget(self.start)
        self.stop=QPushButton('중단');self.stop.clicked.connect(self.request_stop);self.stop.setEnabled(False);row.addWidget(self.stop)
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);self.summary.setMaximumHeight(150);layout.addWidget(self.summary)
        self.process.readyReadStandardOutput.connect(self.discard_output);self.process.readyReadStandardError.connect(self.discard_output)
        self.process.finished.connect(self.finished);self.process.errorOccurred.connect(self.process_error)
        self.process.stateChanged.connect(lambda _:self.controls())
        self.auth_process.readyReadStandardOutput.connect(self.auth_output);self.auth_process.readyReadStandardError.connect(self.auth_output)
        self.auth_process.finished.connect(self.auth_finished);self.auth_process.errorOccurred.connect(self.auth_error)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.update_progress);self.timer.start()
        self.usage_timer=QTimer(self);self.usage_timer.setInterval(60000);self.usage_timer.timeout.connect(self.refresh_account);self.usage_timer.start()
        self.clear_account();self.update_progress();QTimer.singleShot(0,self.refresh_account)

    def configuration(self):
        result=saved_configuration(self.project,self.candidate.text())
        if self.refit:
            from .authoring import runtime_configuration
            result=runtime_configuration(self.project,result)
            if self.source_identity:result['refit_source_identity']=self.source_identity
            if self.capture_ids:result['refit_capture_ids']=self.capture_ids
            # Select the saved Pair layout, not the earlier Scene Prepare layout.
            states=[i.get('scene_state_id')for i in self.project.evidence['images']if i.get('runtime_baseline')and i.get('scene_state_id')]
            if states:result['scene_state_id']=states[-1]
        return result

    def busy(self):return self.process.state()!=QProcess.ProcessState.NotRunning

    def controls(self):
        auth=self.auth_process.state()!=QProcess.ProcessState.NotRunning
        query=self.query is not None
        locked=self.busy()or auth or self.pending_start
        self.start.setEnabled(not locked and not query)
        self.model.setEnabled(not locked);self.effort.setEnabled(not locked)
        self.login.setEnabled(not locked and not query);self.refresh.setEnabled(not auth and not query)
        self.stop.setEnabled(self.busy())

    def clear_account(self):
        self.account=None;self.login_status.setText('로그인 상태 · 조회 불가');self.render_usage([])

    def render_usage(self,rows):
        while self.usage_rows.count():
            widget=self.usage_rows.takeAt(0).widget()
            if widget:widget.hide();widget.deleteLater()
        if not rows:self.usage_rows.addWidget(QLabel('사용량 · 조회 불가'));return
        for row in rows:
            minutes=row['minutes'];period='5시간'if minutes==300 else'주간'if minutes==10080 else str(minutes)+'분'if minutes else'기간 미제공'
            scope=row.get('model')or'적용 모델 미확인'
            self.usage_rows.addWidget(QLabel(f"{row['name']} · {scope} · {period} 한도     {row['remaining']:g}% 남음"))
            bar=QProgressBar();bar.setRange(0,100);bar.setValue(round(row['remaining']));bar.setTextVisible(False);bar.setMaximumHeight(8)
            self.usage_rows.addWidget(bar)
            reset=row.get('resets_at')
            if isinstance(reset,(float,int)):
                remaining=max(0,int(reset-time.time()));days,remain=divmod(remaining,86400);hours,remain=divmod(remain,3600)
                text=f'초기화까지 {days}일 {hours}시간 {remain//60}분 · '+time.strftime('%m/%d %H:%M',time.localtime(reset))
            else:text='초기화 시각 · 조회 불가'
            self.usage_rows.addWidget(QLabel(text))

    def refresh_account(self):
        if self.query is not None or self.auth_process.state()!=QProcess.ProcessState.NotRunning:return
        generation=self.generation;self.query=AccountQuery(self)
        self.query.result.connect(lambda result:self.account_result(result,generation))
        self.query.finished.connect(self.query_finished);self.query.start();self.controls()

    def query_finished(self):
        self.query.deleteLater();self.query=None;self.controls()
        if self.pending_close and not self.busy():self.close()

    def account_result(self,result,generation):
        if generation!=self.generation:return
        self.clear_account()
        if 'error'in result:
            self.summary.setPlainText(result['error']);self.pending_start=False;self.controls();return
        self.account=result['snapshot'];self.version.setText(self.account['version'])
        logged=self.account['logged_in'];identity=self.account.get('account')or{}
        self.login_status.setText(('로그인됨'if logged else'로그인 필요')+' · '+' · '.join(str(identity[k])for k in ('email','planType')if identity.get(k)))
        self.login.setText('계정 전환'if logged else'로그인')
        self.render_usage(self.account.get('usage',[]))
        selected=self.model.currentText()or str(self.preferences.value('model',''))
        self.model.blockSignals(True);self.model.clear()
        for model in self.account['models']:self.model.addItem(model['model'])
        if selected:self.model.setCurrentText(selected)
        elif self.account['models']:
            default=next((m for m in self.account['models']if m.get('isDefault')),self.account['models'][0]);self.model.setCurrentText(default['model'])
        self.model.blockSignals(False);self.model_changed()
        self.model.setPlaceholderText('지원 모델 ID 직접 입력'if not self.account['models']else'모델 선택')
        if self.pending_start:
            self.pending_start=False
            if not logged:self.summary.setPlainText('Builder Codex 로그인 후 이어서 실행하세요.')
            else:
                try:self.launch()
                except Exception as error:self.summary.setPlainText(str(error))
        self.controls()

    def model_changed(self,*_):
        selected=self.effort.currentData()or self.preferences.value('effort','')
        self.effort.clear()
        row=next((m for m in (self.account or{}).get('models',[])if m['model']==self.model.currentText()),None)
        if row:
            for effort in row['supportedReasoningEfforts']:self.effort.addItem(effort['reasoningEffort'],effort['reasoningEffort'])
            index=self.effort.findData(selected or row.get('defaultReasoningEffort'))
            if index<0:index=self.effort.findData(row.get('defaultReasoningEffort'))
            if index>=0:self.effort.setCurrentIndex(index)
        else:self.effort.addItem('CLI 기본값 · 지원 여부 미확인',None)

    def authenticate(self):
        if self.busy()or self.pending_start or self.query is not None:return
        try:
            program=codex_cli.executable();codex_cli.capabilities(program)
            guard=codex_cli.auth_lock(exclusive=True);guard.__enter__();self.auth_guard=guard
            switch=bool(self.account and self.account['logged_in'])
            self.generation+=1;self.clear_account();self.model.clear();self.effort.clear()
            self.auth_action='logout'if switch else'login'
            self.auth_process.setProcessEnvironment(self.cli_environment())
            self.auth_process.start(program,[self.auth_action]);self.controls()
            self.summary.setPlainText('공식 Codex 인증 절차를 진행하세요. 인증 정보는 이 Project에 저장하지 않습니다.')
        except Exception as error:
            self.release_auth();self.summary.setPlainText(str(error))

    def cli_environment(self):
        env=QProcessEnvironment()
        for key,value in codex_cli.environment().items():env.insert(key,value)
        return env

    def auth_output(self):
        # Official browser/device instructions are transient UI text, never a file.
        data=bytes(self.auth_process.readAllStandardOutput())+bytes(self.auth_process.readAllStandardError())
        self.summary.appendPlainText(data.decode(errors='replace')[-4000:])

    def auth_finished(self,code,*_):
        if self.auth_action=='logout'and code==0 and not self.pending_close:
            self.auth_action='login';self.auth_process.start(codex_cli.executable(),['login']);return
        self.release_auth();self.controls();self.refresh_account()

    def release_auth(self):
        if self.auth_guard:self.auth_guard.__exit__(None,None,None);self.auth_guard=None

    def auth_error(self,*_):
        self.release_auth();self.clear_account();self.summary.setPlainText('Codex 인증 프로세스를 실행하지 못했습니다.');self.controls()

    def run(self):
        if self.busy()or self.query is not None:return
        self.pending_start=True;self.refresh_account();self.controls()

    def launch(self):
        config=self.configuration();needs=runtime_needs(config,refit=self.refit)
        if needs:raise ValueError('\n'.join(needs)+'\n기존 설치 환경의 Reconstruction 설정을 복원하세요. 자동 설치하지 않습니다.')
        codex_cli.selection_args(self.model.currentText(),self.effort.currentData(),self.account['models'])
        if (self.project.root/'working/run.lock').exists():raise ValueError('이 Project가 실행 중입니다. 기존 작업 종료 후 재개하세요.')
        if self.temporary:self.temporary.cleanup()
        self.temporary=tempfile.TemporaryDirectory(prefix='real2sim-reconstruct-')
        path=Path(self.temporary.name)/'configuration.yaml';write(path,config)
        args=['refit-pairs'if self.refit else'reconstruct',str(self.project.root),'--candidate',self.candidate.text(),'--config',str(path),'--run-modeling']
        if self.refit:args+=['--scene-state',config.get('scene_state_id','')]
        self.preferences.setValue('model',self.model.currentText());self.preferences.setValue('effort',self.effort.currentData()or'')
        self.start_cli(args)

    def start_cli(self,args):
        env=QProcessEnvironment.systemEnvironment();root=Path(__file__).absolute().parents[1]
        paths=[str(root),str(root.parent.parent/'scene_contract/src')]
        if os.environ.get('REAL2SIM_USD_PYTHONPATH'):paths.append(os.environ['REAL2SIM_USD_PYTHONPATH'])
        env.insert('PYTHONPATH',os.pathsep.join(paths));env.remove('PYTHONHOME');env.insert('PYTHONNOUSERSITE','1');env.insert('PYTHONDONTWRITEBYTECODE','1')
        env.insert('REAL2SIM_CODEX_HOME',codex_cli.environment()['CODEX_HOME'])
        env.insert('REAL2SIM_CODEX_MODEL',self.model.currentText());env.insert('REAL2SIM_CODEX_EFFORT',self.effort.currentData()or'')
        self.report_started=True;self.report_mtime=(self.project.root/'scratch/agent'/self.candidate.text()/'reconstruction.json').stat().st_mtime_ns if (self.project.root/'scratch/agent'/self.candidate.text()/'reconstruction.json').exists()else None
        self.summary.setPlainText('저장된 입력으로 Scene 제작을 시작합니다.')
        self.process.setProcessEnvironment(env);self.process.start(self.python,['-B','-m','real2sim_builder.cli',*args])

    def request_stop(self):
        if self.busy():self.project.control('stop');self.summary.setPlainText('중단 요청 · 하위 프로세스 종료와 결과 보존을 기다리는 중…')

    def discard_output(self):
        self.process.readAllStandardOutput();self.process.readAllStandardError()

    def process_error(self,*_):
        self.summary.setPlainText('실행 실패 · '+self.process.errorString());self.controls()

    def update_progress(self):
        root=self.project.root/'scratch/agent'/self.candidate.text()
        try:
            state=self.project.state;report=json.loads((root/'reconstruction.json').read_text())if(root/'reconstruction.json').is_file()else{}
            stages=report.get('stages',{});stage=state.get('stage')if self.busy() else None
            mapping={'CODEX ANALYSIS':'analysis','ANALYZE':'inference','GEOMETRY':'modeling','CODEX_MODELING':'modeling',
                     'CAMERA & SCALE':'camera','Metric Registration':'camera','FITTING':'fitting','CODEX_REVIEW':'fitting','CHECKPOINT':'checkpoint','SENSOR_REGISTRATION':'camera','JOINT_SENSOR_FITTING':'fitting',
                     'MASt3R Matching':'inference','COLMAP Registration / Bundle Adjustment':'inference',
                     'Dense Geometry Alignment':'inference','COLMAP Registration / Bundle Adjustment / Dense Geometry Alignment':'inference'}
            config=self.configuration()
            complete={'analysis':bool(config.get('scene_analysis')),'inference':stages.get('inference',{}).get('status')=='INFERRED',
                'modeling':stages.get('modeling',{}).get('status')=='ASSETS_READY','camera':bool(stages.get('clouds',{}).get('clouds')),
                'fitting':report.get('status')=='VISUAL_DRAFT_REVIEWED','checkpoint':bool(report.get('selected_checkpoint'))}
            count=state.get('codex_calls',report.get('modeling_calls',0));review=state.get('review_calls',report.get('review_calls',0))
            assets=json.loads((root/'modeling/results.json').read_text())if(root/'modeling/results.json').is_file()else{}
            tasks=json.loads((root/'modeling/tasks.json').read_text())if(root/'modeling/tasks.json').is_file()else{}
            completed_names={name for key,record in assets.get('groups',{}).items()if record.get('fingerprint')==tasks.get('groups',{}).get(key,{}).get('fingerprint')for name in record.get('members',[])}
            total=len(config.get('objects',{}));completed=total if complete['modeling']else len(completed_names & set(config.get('objects',{})))
            for key,(label,title)in self.stage_labels.items():
                text=('● 'if mapping.get(stage)==key else'✓ 'if complete[key]else'○ ')+title
                if key=='modeling':text+=f' ({completed}/{total})'
                if label.text()!=text:label.setText(text)
            labels={'CODEX ANALYSIS':'Codex 장면 분석 중','ANALYZE':'SAM3.1 / Geometry 실행 중','CODEX_MODELING':'Codex USDA 모델링 중','GEOMETRY':'USDA 연결 중','CAMERA & SCALE':'Camera/Scale 초기화 중','Metric Registration':'Camera/Scale 초기화 중',
                'MASt3R Matching':'MASt3R Matching 중','COLMAP Registration / Bundle Adjustment':'COLMAP 등록 / Bundle Adjustment 중',
                'Dense Geometry Alignment':'Dense Geometry 정합 중','COLMAP Registration / Bundle Adjustment / Dense Geometry Alignment':'COLMAP / Dense Geometry 준비 중',
                'SENSOR_REGISTRATION':'Side/Wrist 센서 초기 정합 중','JOINT_SENSOR_FITTING':'휴대폰·Side/Wrist 공동 정합 중','OBSERVATIONS':'관측 점군 구성 중','FITTING':'Real/Sim 정합 중','CODEX_REVIEW':'Codex 수정 검토 중','PHYSICS':'물리 검사 중','VALIDATION':'결과 저장 중'}
            self.current.setText(f"현재 작업: {labels.get(stage,report.get('status','대기'))} · 완료 Codex {count}회 / 검토 {review}회")
            if not self.busy() and report and not self.report_started:self.show_report(report)
        except (OSError,ValueError,KeyError):pass  # Atomic writer may be replacing a record.

    def show_report(self,report):
        status=report.get('status','FAILED');code=report.get('error_code')
        names={'VISUAL_DRAFT_REVIEWED':'완료 · 시각 초안','NEEDS_MORE_DATA':'추가 자료 필요','STOPPED':'중단 · 이어서 실행 가능',
               'FAILED':'실패 · 저장된 작업 보존','USAGE_LIMIT':'사용량 한도 도달 · 계정 전환 후 이어서 실행',
               'AUTHENTICATION_FAILED':'인증 필요 · 로그인 후 이어서 실행','MODEL_UNAVAILABLE':'모델 접근 불가 · 모델을 다시 선택하세요.'}
        self.summary.setPlainText(names.get(code,names.get(status,status))+'\n'+report.get('error','')+'\n'+'\n'.join(report.get('needs',[])))

    def finished(self,code,*_):
        self.discard_output();self.report_started=False
        root=self.project.root/'scratch/agent'/self.candidate.text();path=root/'reconstruction.json'
        if path.is_file() and path.stat().st_mtime_ns!=getattr(self,'report_mtime',None):self.show_report(read(path))
        elif code:self.summary.setPlainText('실행 실패 · 종료 코드 '+str(code))
        if self.temporary:self.temporary.cleanup();self.temporary=None
        self.report_started=True;self.update_progress();self.controls();self.refresh_account()
        if self.pending_close and self.query is None:self.close()

    def closeEvent(self,event):
        if self.busy()or self.query is not None or self.auth_process.state()!=QProcess.ProcessState.NotRunning:
            self.pending_close=True;self.request_stop()
            if self.auth_process.state()!=QProcess.ProcessState.NotRunning:self.auth_process.terminate()
            event.ignore();return
        self.timer.stop();self.usage_timer.stop()
        if self.temporary:self.temporary.cleanup()
        event.accept()
