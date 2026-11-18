"""Single reconstruction control screen. Saved Project inputs remain backend-owned."""
from scene_contract.naming import numbered_path
import copy
import json
import os
from pathlib import Path
import tempfile
import time
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl,QProcess,QProcessEnvironment,QThread,QTimer,QSettings,pyqtSignal
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QPushButton,QPlainTextEdit,QGroupBox,QProgressBar,QGridLayout,QCheckBox,QSpinBox)
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
    """The stage runner checks each Runtime when reached; refits need Blender."""
    import shutil
    needs=[]
    if not refit:return needs
    if not shutil.which(os.environ.get('REAL2SIM_BLENDER','blender')):needs.append('Blender: 기존 실행 파일을 REAL2SIM_BLENDER로 지정하세요.')
    if not shutil.which('bwrap'):needs.append('Blender Sandbox: 기존 bwrap 실행 파일이 필요합니다.')
    return needs


class ReconstructionDialog(QDialog):
    def __init__(self,project,python,parent=None,*,refit=False,source_scene=None,capture_ids=None,engine=None):
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
        selection=self._refit_selection()if refit else None
        if Path(codex_cli.environment()['CODEX_HOME']).is_relative_to(self.project.root):raise ValueError('Codex 인증 폴더는 Project 밖에 있어야 합니다.')
        self.process=QProcess(self);self.auth_process=QProcess(self)
        self.query=None;self.account=None;self.pending_start=False;self.pending_close=False
        self.started_at=None;self.stage_seen=None;self.stage_since=None
        self.auth_guard=None;self.temporary=None;self.generation=0;self.report_started=False
        self.preferences=QSettings('Real2Sim','BuilderCodex')
        saved=read(self.project.root/'input/reconstruction.yaml')if(self.project.root/'input/reconstruction.yaml').is_file()else{}
        name=saved.get('candidate')or self.project.state.get('candidate')or numbered_path(self.project.root/'scratch/agent','auto').name
        self.fresh_run=False
        active=self.project.state.get('candidate')
        if not refit and active and (self.project.root/'scratch/agent'/active/'reconstruction/simfoundry/cache.json').is_file():
            name=active
        if refit:
            name=self.project.state.get('candidate')or name
            root=self.project.root/'scratch/agent'/name
            info=read(root/'candidate.json')if(root/'candidate.json').is_file()else{}
            scene=read(root/'candidate_scene.yaml')if(root/'candidate_scene.yaml').is_file()else{}
            if info.get('status')!='OPEN'or not info.get('source_revision')or scene.get('reconstruction_state',{}).get('id')!=selection['scene_state_id']or info['source_revision']['identity']!=selection['source_identity']:name=numbered_path(self.project.root/'scratch/agent','refit').name
        from .scene import identifier
        identifier(name)
        if refit:
            self.candidate=QLabel(name)
        else:
            self.candidate=QComboBox()
            self.candidate.setAccessibleName('Scene 실행 기록')
            self.load_run_history(active,name)
        self.setWindowTitle('Auto Reconstruction');self.resize(800,830)
        self.setStyleSheet('''
QDialog { background:#0c1420; color:#e7eff8; }
QLabel,QGroupBox { color:#e7eff8; background:transparent; }
QGroupBox { background:#121f2e; border:1px solid #2d4259; border-radius:10px; margin-top:16px; padding:16px 12px 12px; font-weight:500; }
QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 5px; }
QComboBox,QPlainTextEdit { background:#0d1825; color:#e7eff8; border:1px solid #31465d; border-radius:7px; padding:7px; }
QComboBox QAbstractItemView { background:#142334; color:#e7eff8; selection-background-color:#164c4d; selection-color:#63f4de; border:1px solid #39556d; outline:0; }
QComboBox QAbstractItemView::item { background:#142334; color:#e7eff8; min-height:28px; }
QComboBox QAbstractItemView::item:selected { background:#164c4d; color:#63f4de; }
QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1d2c3d,stop:1 #14202e); color:#dce8f5; border:1px solid #344a62; border-radius:8px; padding:9px 14px; }
QPushButton:hover { background:#243a4e; border-color:#00cbb6; }
QPushButton:disabled { color:#7b91a7; background:#12202d; }
QProgressBar { background:#102131; color:#c8dfef; border:1px solid #2b4257; border-radius:4px; }
QProgressBar::chunk { background:#0b8f83; border-radius:4px; }
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
        if self.refit:
            titles=(('analysis','장면 분석'),('inference','Object / Reference 연결'),('modeling','Blender USDA 제작'),
                    ('camera','공유 Sensor Camera'),('fitting','Real/Sim 정합 및 Codex 검토'),('checkpoint','최선 결과 저장'))
            for key,title in titles:
                label=QLabel('○ '+title);steps.addWidget(label);self.stage_labels[key]=(label,title)
        else:
            from .stage_artifacts import STAGE_NAMES
            grid=QGridLayout();steps.addLayout(grid)
            for index,title in enumerate(STAGE_NAMES):
                label=QLabel('○ '+str(index+1)+'. '+title);label.setWordWrap(True)
                grid.addWidget(label,index//2,index%2);self.stage_labels[str(index+1)]=(label,str(index+1)+'. '+title)
        self.numeric=None;self.refit_engine=engine
        if refit:
            self.numeric=QCheckBox('실측 q 기반 수치 공동 정합 (Codex 호출 없음)');self.numeric.setChecked(saved_configuration(self.project,self.candidate_name).get('numeric_refinement',{}).get('enabled',True));layout.addWidget(self.numeric)
            self.rounds=QSpinBox();self.rounds.setRange(1,20);self.rounds.setValue(4);self.rounds.setPrefix('최대 반복 ');layout.addWidget(self.rounds)
        self.current=QLabel('저장된 작업 확인 중…');self.current.setWordWrap(True);steps.addWidget(self.current)
        self.elapsed=QLabel();steps.addWidget(self.elapsed);self.elapsed.hide()
        row=QHBoxLayout();layout.addLayout(row)
        self.start=QPushButton('재정합 시작 / 이어서 실행' if refit else '새로 생성')
        self.start.clicked.connect(lambda: self.run(fresh=not self.refit));row.addWidget(self.start)
        self.resume=None
        if not refit:
            self.start.setToolTip('같은 Scene 입력으로 새 Candidate를 만들고 Stage 1부터 실행합니다.')
            self.resume=QPushButton('이어서 실행');self.resume.clicked.connect(lambda: self.run())
            self.resume.setToolTip('표시된 Candidate에서 저장된 작업 다음부터 실행합니다.')
            row.addWidget(self.resume)
        self.stop=QPushButton('중단');self.stop.clicked.connect(self.request_stop);self.stop.setEnabled(False);row.addWidget(self.stop)
        self.evidence_button=QPushButton('제작 기록 / 결과 이미지 보기');self.evidence_button.clicked.connect(self.open_evidence);layout.addWidget(self.evidence_button)
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);self.summary.setMaximumHeight(150);layout.addWidget(self.summary)
        self.summary.hide()
        self.summary.textChanged.connect(lambda:self.summary.setVisible(bool(self.summary.toPlainText().strip())))
        self.process.readyReadStandardOutput.connect(self.discard_output);self.process.readyReadStandardError.connect(self.discard_output)
        self.process.finished.connect(self.finished);self.process.errorOccurred.connect(self.process_error)
        self.process.stateChanged.connect(lambda _:self.controls())
        self.auth_process.readyReadStandardOutput.connect(self.auth_output);self.auth_process.readyReadStandardError.connect(self.auth_output)
        self.auth_process.finished.connect(self.auth_finished);self.auth_process.errorOccurred.connect(self.auth_error)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.update_progress);self.timer.start()

        if not refit:self.candidate.currentIndexChanged.connect(self.run_selected)
        self.clear_account();self.update_progress();self.controls();QTimer.singleShot(0,self.refresh_account)

    @property
    def candidate_name(self):
        return self.candidate.currentData() if isinstance(self.candidate,QComboBox) else self.candidate.text()

    def load_run_history(self,active,fallback):
        from .scene import identifier
        history=[]
        for metadata in (self.project.root/'scratch/agent').glob('*/candidate.json'):
            folder=metadata.parent
            if folder.is_symlink() or metadata.is_symlink():continue
            report_path=folder/'reconstruction.json'
            checkpoint=folder/'reconstruction/simfoundry/cache.json'
            try:
                name=identifier(folder.name)
                info=read(metadata)
                if info.get('source_revision') or info.get('id')!=name:continue
                report=read(report_path) if report_path.is_file() else {}
                if report.get('pipeline')!='simfoundry/1' and not checkpoint.is_file():continue
                latest=max(p.stat().st_mtime_ns for p in (metadata,report_path,checkpoint) if p.exists())
                history.append((latest,name,report))
            except (OSError,ValueError):continue
        for _,name,report in sorted(history,reverse=True):
            self.candidate.addItem(self.run_caption(name,report),name)
        if history:
            self.candidate.setCurrentIndex(max(0,self.candidate.findData(active or '')))
        else:
            self.candidate.addItem(fallback+' · 실행 전',fallback)

    @staticmethod
    def run_caption(name,report,stage=None):
        from .stage_artifacts import STAGE_NAMES
        status=report.get('status','대기')
        label={'STOPPED':'중단','RUNNING':'진행 중','FAILED':'실패','DRAFT_READY':'초안 생성 완료',
               'NEEDS_RUNTIME':'실행 환경 필요','NEEDS_REVIEW':'검토 필요','NEEDS_MORE_DATA':'추가 자료 필요'}.get(status,status)
        stage=stage or report.get('failed_stage')
        if stage is None:
            completed=[i for i in range(1,15) if report.get('stages',{}).get(str(i),{}).get('status')=='COMPLETE']
            if completed: return f'{name} · {label} · Stage {max(completed)}까지 완료'
        if type(stage) is int and 1<=stage<=14:
            return f'{name} · {label} · Stage {stage} · {STAGE_NAMES[stage-1]}'
        return f'{name} · {label}'

    def run_selected(self):
        self.report_started=False
        self.elapsed.hide()
        self.summary.clear()
        self.update_progress()
        self.controls()

    def _refit_selection(self):
        from .automation import select_refit_pairs
        selected=select_refit_pairs(self.project,capture_ids=self.capture_ids,source_identity=self.source_identity)
        if selected.get('code'):raise ValueError(selected['code']+': '+'; '.join(selected['needs']))
        return selected

    def configuration(self,candidate=None):
        result=saved_configuration(self.project,candidate or self.candidate_name)
        if self.refit:
            if self.numeric is not None:
                result.setdefault('numeric_refinement',{})['enabled']=self.numeric.isChecked()
                result['numeric_refinement']['max_iterations']=self.rounds.value()
            if self.refit_engine:result.setdefault('fitting',{})['engine']='isaac'if self.refit_engine=='isaaclab'else self.refit_engine
            selected=self._refit_selection()
            result['refit_source_identity']=selected['source_identity']
            result['refit_capture_ids']=selected['capture_ids']
            result['scene_state_id']=selected['scene_state_id']
        return result

    def busy(self):return self.process.state()!=QProcess.ProcessState.NotRunning

    def controls(self):
        auth=self.auth_process.state()!=QProcess.ProcessState.NotRunning
        query=self.query is not None
        locked=self.busy()or auth or self.pending_start
        self.start.setEnabled(not locked and not query)
        if self.resume is not None:
            self.candidate.setEnabled(not locked)
            root=self.project.root/'scratch/agent'/self.candidate_name
            self.resume.setEnabled(not locked and not query and (root/'reconstruction/simfoundry/cache.json').is_file()
                                   and (root/'candidate.json').is_file() and read(root/'candidate.json').get('status')=='OPEN')
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
        if 'error'in result:
            self.clear_account()
            self.summary.setPlainText(result['error'])
            pending=self.pending_start;self.pending_start=False
            if pending and not self.refit:
                try:self.launch()
                except Exception as error:self.summary.setPlainText(str(error))
            self.controls();return
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
            if not logged and self.refit:self.summary.setPlainText('Builder Codex 로그인 후 이어서 실행하세요.')
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

    def run(self,*,fresh=False):
        if self.busy()or self.query is not None or self.pending_start:return
        if not self.refit and not fresh and not self.resume.isEnabled():return
        self.fresh_run=fresh
        if self.numeric is not None and self.numeric.isChecked():
            try:self.launch()
            except Exception as error:self.summary.setPlainText(str(error))
            return
        self.pending_start=True;self.refresh_account();self.controls()

    def launch(self):
        name=numbered_path(self.project.root/'scratch/agent','auto').name if self.fresh_run else self.candidate_name
        config=self.configuration(name);numeric=self.refit and config.get('numeric_refinement',{}).get('enabled',False)
        needs=runtime_needs(config,refit=self.refit and not numeric)
        if needs:raise ValueError('\n'.join(needs)+'\n기존 설치 환경의 Reconstruction 설정을 복원하세요. 자동 설치하지 않습니다.')
        if not numeric and self.account and self.account.get('logged_in'):
            codex_cli.selection_args(self.model.currentText(),self.effort.currentData(),self.account['models'])
        from real2sim_builder.candidate import project_busy
        if project_busy(self.project):raise ValueError('이 Project가 실행 중입니다. 기존 작업 종료 후 재개하세요.')
        if self.fresh_run:
            from .candidate import Candidate,exclusive
            with exclusive(self.project):
                Candidate.create(self.project,name)
                self.project.control('resume')
            index=self.candidate.findData(name)
            if index<0:
                self.candidate.insertItem(0,name+' · 실행 전',name)
                index=0
            self.candidate.setCurrentIndex(index)
            self.fresh_run=False
        if self.temporary:self.temporary.cleanup()
        self.temporary=tempfile.TemporaryDirectory(prefix='real2sim-reconstruct-')
        path=Path(self.temporary.name)/'configuration.yaml';write(path,config)
        args=['refit-pairs'if self.refit else'reconstruct',str(self.project.root),'--candidate',self.candidate_name,'--config',str(path)]
        if not numeric:args+=['--run-modeling']
        if self.refit:args+=['--scene-state',config.get('scene_state_id','')]
        if not numeric:self.preferences.setValue('model',self.model.currentText());self.preferences.setValue('effort',self.effort.currentData()or'')
        self.start_cli(args)

    def start_cli(self,args):
        env=QProcessEnvironment.systemEnvironment();root=Path(__file__).absolute().parents[1]
        paths=[str(root),str(root.parent.parent/'scene_contract/src')]
        if os.environ.get('REAL2SIM_USD_PYTHONPATH'):paths.append(os.environ['REAL2SIM_USD_PYTHONPATH'])
        env.insert('PYTHONPATH',os.pathsep.join(paths));env.remove('PYTHONHOME');env.insert('PYTHONNOUSERSITE','1');env.insert('PYTHONDONTWRITEBYTECODE','1')
        env.insert('REAL2SIM_CODEX_HOME',codex_cli.environment()['CODEX_HOME'])
        env.insert('REAL2SIM_CODEX_MODEL',self.model.currentText());env.insert('REAL2SIM_CODEX_EFFORT',self.effort.currentData()or'')
        self.report_started=True;self.report_mtime=(self.project.root/'scratch/agent'/self.candidate_name/'reconstruction.json').stat().st_mtime_ns if (self.project.root/'scratch/agent'/self.candidate_name/'reconstruction.json').exists()else None
        self.summary.clear();self.started_at=time.monotonic();self.stage_seen=None;self.stage_since=None
        self.elapsed.setText('이번 실행 00:00 · 시작 중');self.elapsed.show()
        self.process.setProcessEnvironment(env);self.process.start(self.python,['-B','-m','real2sim_builder.cli',*args])

    def request_stop(self):
        if self.busy():self.project.control('stop');self.summary.setPlainText('중단 요청 · 하위 프로세스 종료와 결과 보존을 기다리는 중…')

    def discard_output(self):
        self.process.readAllStandardOutput();self.process.readAllStandardError()

    def process_error(self,*_):
        self.summary.setPlainText('실행 실패 · '+self.process.errorString());self.controls()

    def update_progress(self):
        root=self.project.root/'scratch/agent'/self.candidate_name
        try:
            state=self.project.state;report=json.loads((root/'reconstruction.json').read_text())if(root/'reconstruction.json').is_file()else{}
            stages=report.get('stages',{});stage=state.get('stage')if self.busy() and state.get('candidate') in (None,self.candidate_name) else None
            if self.busy() and self.started_at is not None:
                now=time.monotonic()
                if stage!=self.stage_seen:self.stage_seen=stage;self.stage_since=now
                total=int(now-self.started_at)
                text=f'이번 실행 {total//60:02d}:{total%60:02d}'
                if stage and self.stage_since is not None:
                    seconds=int(now-self.stage_since)
                    text+=f' · 현재 단계 {seconds//60:02d}:{seconds%60:02d}'
                self.elapsed.setText(text+' · 실행 중')
            if self.refit and report.get('pipeline')=='numeric-pairs/1':
                self.current.setText('수치 정합 반복 '+str(report.get('current_iteration',0))+' · 개선 채택 '+str(report.get('accepted_iterations',0))+' · Best/Current 별도 보존')
                if not self.busy():self.show_report(report)
                return
            if not self.refit:
                from .stage_artifacts import STAGE_NAMES
                for key,(label,title)in self.stage_labels.items():
                    text=('● 'if stage=='STAGE_'+key else'✓ 'if stages.get(key,{}).get('status')=='COMPLETE'else'○ ')+title
                    if label.text()!=text:label.setText(text)
                active=int(stage[6:])if stage and stage.startswith('STAGE_')else report.get('failed_stage')
                title=STAGE_NAMES[active-1]if type(active)is int and 1<=active<=14 else report.get('status','대기')
                if report or stage:
                    caption=self.run_caption(self.candidate_name,report,active)
                    if caption!=self.candidate.currentText():
                        self.candidate.setItemText(self.candidate.currentIndex(),caption)
                operation=state.get('last_worker_operation') if self.busy() and stage else None
                detail=f' · 최근 호출 {operation}' if operation else ''
                self.current.setText('현재 작업: '+('Stage '+str(active)+' · 'if active else'')+title+detail)
                if not self.busy()and report and not self.report_started:self.show_report(report)
                return

            mapping={'CODEX ANALYSIS':'analysis','SCENE_COMPOSITION':'camera','GEOMETRY':'modeling','CODEX_MODELING':'modeling','FITTING':'fitting','CODEX_REVIEW':'fitting','CHECKPOINT':'checkpoint'}
            config=self.configuration()
            complete={'analysis':bool(config.get('scene_analysis')),'inference':bool(config.get('objects')),
                'modeling':stages.get('modeling',{}).get('status')=='ASSETS_READY','camera':stages.get('first_scene',{}).get('status')=='RENDERED',
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
            labels={'CODEX ANALYSIS':'Codex 이미지·메모 분석 중','CODEX_MODELING':'Codex Blender 모델링 중','GEOMETRY':'USDA 자산 연결 중','SCENE_COMPOSITION':'최초 Scene / 추정 Camera 구성 중',
                'FITTING':'실제 다중 View 렌더 생성 중','CODEX_REVIEW':'Codex Before/After 검토 중','PHYSICS':'실제 물리 진단 중','VALIDATION':'결과 저장 중'}
            self.current.setText(f"현재 작업: {labels.get(stage,report.get('status','대기'))} · 완료 Codex {count}회 / 검토 {review}회")
            if not self.busy() and report and not self.report_started:self.show_report(report)
        except (OSError,ValueError,KeyError):pass  # Atomic writer may be replacing a record.

    def open_evidence(self):
        path=self.project.root/'scratch/agent'/self.candidate_name/'evidence/index.html'
        candidate=path.parent.parent
        if not self.refit and (candidate/'reconstruction/simfoundry/cache.json').is_file() and candidate.resolve().is_relative_to(self.project.root.resolve()):
            if getattr(self,'dashboard_job',None) and self.dashboard_job.state()!=QProcess.ProcessState.NotRunning:
                return
            destination=Path(tempfile.mkdtemp(prefix='real2sim-evidence-'))/'dashboard'
            job=QProcess(self)
            self.dashboard_job=job
            env=QProcessEnvironment.systemEnvironment()
            roots=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[3]/'scene_contract/src')]
            env.insert('PYTHONPATH',os.pathsep.join(roots+[env.value('PYTHONPATH')]))
            job.setProcessEnvironment(env)
            def finished(code,*_):
                if code==0 and (destination/'index.html').is_file():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination/'index.html')))
                else:
                    self.summary.setPlainText('제작 기록 열기 실패 · '+bytes(job.readAllStandardError()).decode(errors='replace')[-500:])
            job.finished.connect(finished)
            job.errorOccurred.connect(lambda _: self.summary.setPlainText(job.errorString()))
            job.start(self.python,['-B','-m','real2sim_builder.evidence_dashboard',str(candidate),str(destination)])
            return
        if path.is_file()and not path.is_symlink()and path.resolve().is_relative_to(self.project.root.resolve()):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:self.summary.setPlainText('아직 생성된 제작 기록이 없습니다. 실행한 단계부터 실제 결과를 보존합니다.')

    def show_report(self,report):
        status=report.get('status','FAILED');code=report.get('error_code')
        names={'VISUAL_DRAFT_REVIEWED':'완료 · 시각 초안','NEEDS_MORE_DATA':'추가 자료 필요','STOPPED':'중단 · 이어서 실행 가능',
               'DRAFT_READY':'초안 Package 생성 · 센서/물리 정확도 별도 검증','REFINED_DRAFT':'수치 정합 초안 · 독립 정확도/물리/Task 미검증',
               'NEEDS_RUNTIME':'Runtime/인증 필요 · 완료 Stage 보존','NOT_SUPPORTED':'미지원 기능 · 완료 Stage 보존','NEEDS_REVIEW':'검토 필요 · 완료 Stage 보존',
               'FAILED':'실패 · 저장된 작업 보존','USAGE_LIMIT':'사용량 한도 도달 · 계정 전환 후 이어서 실행',
               'AUTHENTICATION_FAILED':'인증 필요 · 로그인 후 이어서 실행','MODEL_UNAVAILABLE':'모델 접근 불가 · 모델을 다시 선택하세요.'}
        self.summary.setPlainText(names.get(code,names.get(status,status))+'\n'+str(report.get('error',''))+'\n'+'\n'.join(report.get('needs',[])))
        if report.get('completion'):
            c=report['completion'];self.summary.appendPlainText('Object 재구성: '+c['object_reconstruction']+' / Scene 좌표 합성: '+c['scene_compilation']+' / 센서·물리·Task 정확도: NOT_VERIFIED')
        for row in report.get('history',[]):
            if 'metrics'in row:
                values=['%s/%s MAE %.5f'%(r.get('camera_type','?'),r['split'],r['mae'])for r in row['metrics'].get('images',[])]
                self.summary.appendPlainText('반복 '+str(row['iteration']+1)+' · '+('Best 채택'if row['accepted']else'Best 유지')+' · '+'; '.join(values))

    def finished(self,code,*_):
        if self.started_at is not None:
            seconds=int(time.monotonic()-self.started_at);self.elapsed.setText(f'이번 실행 {seconds//60:02d}:{seconds%60:02d} · 종료');self.started_at=None
        self.discard_output();self.report_started=False
        root=self.project.root/'scratch/agent'/self.candidate_name;path=root/'reconstruction.json'
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
        self.timer.stop()
        if self.temporary:self.temporary.cleanup()
        event.accept()
