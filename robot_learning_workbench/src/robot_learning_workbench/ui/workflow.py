"""Stage-local saved Recipe and existing Run IPC. Physics stays in backend Python."""
import json
from pathlib import Path
import uuid
import time
from PyQt6.QtCore import Qt,QTimer,QUrl,QProcess
from PyQt6.QtGui import QImage,QPixmap,QDesktopServices
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFileDialog,QComboBox,QSpinBox,QPlainTextEdit,QGridLayout,QSplitter,QScrollArea,QDialog,QProgressBar
from .pipeline_settings import PipelineSettings
from .jobs import BackendJob
from .operations import run_outcome


class WorkflowPage(QWidget):
    def __init__(self,stage,python,modules,parent=None):
        super().__init__(parent)
        if stage in ('source','capture','real_sim'):raise ValueError('Use the dedicated SourcePage or Session page')
        from .theme import STYLE
        from .view import CameraView
        self.setStyleSheet(STYLE)
        self.stage=stage;self.workspace=Path(getattr(parent,'workspace',Path.cwd())).resolve();self.backend_python=python;self.modules=str(modules)
        self.handle=None;self.after_seq=0;self.request_id=None;self.ready=None;self.busy=False;self.stop_requested=False;self.cancel_command_id=None;self.cancel_queued=False;self.start_after_prepare=False;self.execution={};self.dataset_state='미확인';self.owned_runs=set()
        titles={'annotation':'Annotation','datagen':'Mimic / Datagen','train':'모델 학습','hub_download':'Hub 다운로드','hub_upload':'Hub 업로드','simulation_evaluation':'Sim 평가','offline_validation':'Offline Validation','real_evaluation':'Real Evaluation'}
        self.heading=QLabel(titles[stage]);self.heading.setObjectName('dashboardTitle');self.heading.hide()
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(12)
        self.splitter=QSplitter(Qt.Orientation.Horizontal);outer.addWidget(self.splitter,1)
        self.viewer=QWidget();self.viewer.setObjectName('workspaceCanvas');box=QVBoxLayout(self.viewer);box.setContentsMargins(0,0,0,0);box.setSpacing(12);self.splitter.addWidget(self.viewer)
        self.settings_scroll=QScrollArea();self.settings_scroll.setObjectName('settingsPanel');self.settings_scroll.setWidgetResizable(True);self.settings_scroll.setMinimumWidth(320)
        self.engine=QComboBox(self);self.engine.addItems(['mujoco','isaaclab'])
        self.settings=PipelineSettings(stage,python,self.workspace,self.engine,self);self.editor=self.settings.editor
        self.settings_scroll.setWidget(self.settings);self.splitter.addWidget(self.settings_scroll)
        self.splitter.setChildrenCollapsible(False);self.splitter.setStretchFactor(0,1);self.splitter.setStretchFactor(1,0);self.splitter.setSizes([850,430])
        if stage=='real_evaluation':
            status=QLabel('현재 구현: 실제 관측 → Policy 추론. 자율 모터 Rollout은 연결되지 않았습니다.');status.setWordWrap(True);box.addWidget(status)
        self.state=QLabel('입력을 선택하거나 Script를 불러오세요.');self.state.setWordWrap(True);self.state.setStyleSheet('background: transparent; padding: 6px;')
        self.action_card=QWidget();self.action_card.setObjectName('actionCard');actions=QHBoxLayout(self.action_card);actions.addWidget(self.state,1);box.addWidget(self.action_card)
        self.start_button=QPushButton({'annotation':'Annotation 시작','datagen':'데이터 생성 시작','train':'학습 시작','simulation_evaluation':'Sim 평가 시작','real_evaluation':'Policy 관측 시작','offline_validation':'Validation 시작','hub_download':'다운로드 시작','hub_upload':'업로드 시작'}[stage]);self.start_button.setObjectName('primaryAction')
        self.cancel_button=QPushButton('현재 workflow 중지');self.cancel_button.setObjectName('stopAction');actions.addWidget(self.start_button);actions.addWidget(self.cancel_button)
        self.start_button.setEnabled(False);self.cancel_button.setEnabled(False);self.start_button.clicked.connect(self.start_run);self.cancel_button.clicked.connect(self.cancel_run)
        self.mark_event=QComboBox();self.mark_event.setEditable(True);self.mark_event.addItem('grasp')
        self.commands={};self.mark_frame=QSpinBox();self.mark_frame.setRange(1,1000000);self.manual_controls=QWidget();controls=QGridLayout(self.manual_controls);box.addWidget(self.manual_controls);self.manual_controls.hide()
        if stage=='annotation':
            controls.addWidget(self.mark_event,1,0);self.mark_frame.setMaximumWidth(110);controls.addWidget(self.mark_frame,1,1)
            for i,(kind,text) in enumerate([('pause','일시정지'),('resume','재생'),('step','한 스텝'),('mark','Event 표시'),('skip','Episode 건너뛰기')]):
                button=QPushButton(text);button.setEnabled(False);button.clicked.connect(lambda _,k=kind:self.command(k));controls.addWidget(button,0,i);self.commands[kind]=button
        self.preview_env=QSpinBox();self.preview_env.setMaximumWidth(80);self.preview_env.setRange(0,0);self.preview_env.valueChanged.connect(self.select_preview)
        if stage in ('annotation','datagen','simulation_evaluation'):
            env_row=QHBoxLayout();box.addLayout(env_row);env_row.addWidget(QLabel('Preview Env'));env_row.addWidget(self.preview_env);env_row.addStretch()
        self.progress_bar=QProgressBar();self.progress_bar.setRange(0,1);self.progress_bar.setValue(0);self.progress_bar.setFormat('Worker 대기');self.progress_text=QLabel('');self.progress_text.setWordWrap(True)
        if stage in ('annotation','datagen','train','simulation_evaluation'):box.addWidget(self.progress_bar);box.addWidget(self.progress_text)
        self.media_splitter=QSplitter(Qt.Orientation.Vertical);box.addWidget(self.media_splitter,1)
        self.preview_card=QWidget();self.preview_card.setObjectName('previewCard');grid=QGridLayout(self.preview_card);self.media_splitter.addWidget(self.preview_card)
        self.previews={};self.sim_previews={}
        for col,n in enumerate(('side','wrist')):
            grid.addWidget(QLabel(('REAL 'if stage=='real_evaluation'else'SIM ')+n.upper()),0,col);label=CameraView(n.upper()+' — 실행 대기',minimum=(120,90));grid.addWidget(label,1,col);self.previews[n]=label
        grid.setRowStretch(1,1)
        for label in (*self.previews.values(),*self.sim_previews.values()):label.setStyleSheet('background: #141b23; border-radius: 14px; color: #8b9aaa;')
        self.preview_card.setVisible(stage in ('annotation','datagen','simulation_evaluation','real_evaluation'))
        self.log_card=QWidget();self.log_card.setObjectName('logCard');log_box=QVBoxLayout(self.log_card);self.media_splitter.addWidget(self.log_card)
        tools=QGridLayout();log_box.addLayout(tools);tools.addWidget(QLabel('진행 / 오류 로그'),0,0)
        self.result_button=QPushButton('결과 상세');self.result_button.clicked.connect(self.open_result);tools.addWidget(self.result_button,0,1)
        self.reopen_button=QPushButton('기존 Run 열기');self.reopen_button.clicked.connect(self.reopen_run);tools.addWidget(self.reopen_button,0,2)
        self.loss_chart=None
        if stage=='train':
            from .learning import LossChart
            self.loss_chart=LossChart();self.loss_chart.hide();loss_button=QPushButton('학습 Loss 그래프');loss_button.clicked.connect(self.show_loss);tools.addWidget(loss_button,1,0)
        self.log=QPlainTextEdit();self.log.setObjectName('console');self.log.setReadOnly(True);self.log.setMaximumBlockCount(1000);log_box.addWidget(self.log)
        self.media_splitter.setStretchFactor(0,3);self.media_splitter.setStretchFactor(1,1);self.media_splitter.setSizes([500,180])
        self.job=BackendJob(python,self);self.job.finished.connect(self.job_finished);self.job.log.connect(self.log.appendPlainText);self.operation=None
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(34);self.generations={}
        self.settings.changed.connect(self.invalidate);self.settings.error.connect(self.show_error);self.settings.apply_requested.connect(self.apply_script)
        if stage=='train':
            button=QPushButton('공식 Training JSON 편집');self.settings.layout().addWidget(button)
            button.clicked.connect(self.edit_training_json)
        if stage in ('hub_download','hub_upload'):
            from .hub import HubActions
            self.hub_actions=HubActions(self);self.settings.layout().addWidget(self.hub_actions)
        self.buttons()

    def edit_training_json(self):
        from .training_json import TrainingJsonDialog
        dialog=TrainingJsonDialog(self);dialog.exec()

    def show_error(self,message):
        self.state.setText(message);self.log.appendPlainText(message)

    def buttons(self):
        active=self.active();self.settings.set_busy(active)
        self.start_button.setEnabled(not active and not self.settings.invalid_selection and self.editor.path is not None and self.editor.path.is_file()and not self.editor.dirty)
        self.cancel_button.setEnabled(active and not(self.stop_requested and(self.busy or self.cancel_queued)))
        if hasattr(self,'hub_actions'):self.hub_actions.setEnabled(not active)

    def invalidate(self):
        self.ready=None
        if self.editor.dirty:self.state.setText('Script 편집 중 · 저장 및 적용하세요.')
        self.buttons()

    def apply_script(self,path,*,start=False):
        if self.active():self.show_error('현재 실행이 끝난 뒤 Script를 적용하세요.');return
        if self.settings.query_operation=='dataset'and self.settings.query_version==self.settings.version and self.settings.query.process.state()!=QProcess.ProcessState.NotRunning:
            self.show_error('입력 데이터의 Scene 조회가 끝난 뒤 적용하세요.');return
        try:
            data=self.editor.data();self.settings.validate_stage(data);self.sync_execution(data)
            self.ready=None;self.stop_requested=False;self.cancel_command_id=None;self.cancel_queued=False;self.start_after_prepare=start;self.busy=True;self.operation='prepare';self.state.setText('Script와 입력 준비 중…');self.buttons()
            self.job.start('prepare',path=str(path),modules=self.modules)
        except Exception as error:self.busy=False;self.start_after_prepare=False;self.show_error(str(error));self.buttons()

    def sync_execution(self,data):
        self.execution=data.get('execution',{})
        self.settings.syncing=True
        try:
            if 'engine'in data:self.engine.setCurrentText(data['engine'])
        finally:self.settings.syncing=False
        self.preview_env.blockSignals(True)
        try:self.preview_env.setRange(0,max(0,int(self.execution.get('env_num',self.execution.get('num_envs',1)))-1));self.preview_env.setValue(0)
        finally:self.preview_env.blockSignals(False)
        self.manual_controls.setVisible(self.stage=='annotation'and self.execution.get('mode')=='manual')
        if self.stage=='annotation':self.mark_event.clear();self.mark_event.addItems(list(data.get('functions',{}).get('signals',{}))or['grasp'])

    def display_hardware_result(self,data):
        self.log.appendPlainText('최근 Run '+str(data.get('status'))+' · 측정 '+str(data.get('frames',0))+' frame · command_sent='+str(data.get('command_sent',False)))
    def show_loss(self):
        if self.stage!='train':return
        if not hasattr(self,'loss_dialog'):
            self.loss_dialog=QDialog(self);self.loss_dialog.setWindowTitle('학습 Loss · 공식 로그');self.loss_dialog.resize(1000,600);QVBoxLayout(self.loss_dialog).addWidget(self.loss_chart)
        self.loss_chart.show();self.loss_dialog.show();self.loss_dialog.raise_()

    def hideEvent(self,event):
        if hasattr(self,'loss_dialog'):self.loss_dialog.hide()
        super().hideEvent(event)

    def select_preview(self,index):
        if self.handle:
            from ..run import select_preview_env
            select_preview_env(self.handle['run_dir'],index)
        self.generations.clear()
        for label in self.previews.values():label.clear()

    def command(self,kind):
        if not self.handle or not self.active()or self.stop_requested:return
        if kind=='mark' and not 0<self.mark_frame.value()<=getattr(self,'env_contexts',{}).get(self.preview_env.value(),getattr(self,'context',{})).get('tick',-1):
            self.log.appendPlainText('아직 재생하지 않은 frame은 표시할 수 없습니다');return
        from ..run import RunHandle,send_command
        payload={'count':1} if kind=='step' else ({'event':self.mark_event.currentText().strip(),'frame':self.mark_frame.value()} if kind=='mark' else ({'reason':'user'} if kind=='skip' else {}))
        try:
            h=self.handle;context=getattr(self,'env_contexts',{}).get(self.preview_env.value(),getattr(self,'context',{}));command={'command_id':uuid.uuid4().hex,'kind':kind,'payload':payload}
            if 'episode_id' in context:command.update(episode_id=context['episode_id'],env_index=self.preview_env.value())
            receipt=send_command(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),command)
            self.log.appendPlainText(kind+' 요청: '+receipt.status+' · 실제 적용 ACK는 로그로 확인')
        except Exception as error:self.log.appendPlainText(str(error))

    def reopen_run(self):
        if self.active():return
        folder=QFileDialog.getExistingDirectory(self,'기존 Run 폴더 (run.json)')
        if not folder:return
        try:
            from ..run import load_worker_request,read_status
            from ..recipe import _parse_recipe
            path=Path(folder).resolve();record=json.loads((path/'run.json').read_text());wire=load_worker_request(path);req=wire.request
            if record['stage']!=self.stage or req.expected_stage!=self.stage:raise ValueError('현재 화면과 Run stage가 다릅니다')
            if wire.run_id!=path.name or record['run_id']!=wire.run_id or record['request_id']!=req.request_id or wire.run_dir.resolve()!=path:raise ValueError('Run identity가 저장된 실행과 다릅니다.')
            snapshot=path/'recipe.yaml';raw=(snapshot if snapshot.exists()else req.recipe_path).read_bytes()
            doc=_parse_recipe(req.recipe_path,raw,self.stage)
            if doc.sha256!=req.expected_recipe_sha256:raise ValueError('저장된 Run Script가 변경되었습니다.')
            if(doc.base_dir/doc.spec.output['directory']).resolve()!=req.output_path.resolve():raise ValueError('저장된 Run 출력 identity가 다릅니다.')
            status=read_status(path)
            self.ready=None;self.stop_requested=status.phase=='stopping';self.cancel_command_id=None;self.cancel_queued=self.stop_requested
            self.settings.restore_run_script(raw,doc.base_dir,snapshot);self.sync_execution(self.editor.data())
            self.context={};self.env_contexts={};self.handle={'run_id':wire.run_id,'request_id':req.request_id,'run_dir':str(path),'output_path':str(req.output_path)};self.after_seq=0;self.generations.clear()
            self.state.setText('기존 Run · '+status.status);self.buttons();self.poll()
        except Exception as error:self.state.setText(str(error))
    def active(self):
        if self.handle is None:return self.busy
        from ..run import read_status
        return self.busy or read_status(self.handle['run_dir']).status not in ('completed','cancelled','failed','unknown')
    def start_run(self):
        if self.editor.path is None or self.editor.dirty or self.settings.invalid_selection or self.active():return
        if hasattr(self,'hub_actions')and self.hub_actions.job.process.state()!=QProcess.ProcessState.NotRunning:self.show_error('Hub 조회가 끝난 뒤 실행하세요.');return
        if any(page is not self and page.active() for page in [*getattr(self.window(),'workflows',{}).values(),*getattr(self.window(),'sessions',{}).values()]):
            self.state.setText('현재 실행 중인 worker를 종료한 뒤 시작하세요');return
        if self.ready is None:self.apply_script(self.editor.path,start=True);return
        if self.stage=='hub_upload':
            from PyQt6.QtWidgets import QMessageBox
            data=self.editor.data()
            if not data.get('execution',{}).get('confirm_upload'):self.show_error('업로드할 Script의 confirm_upload: true를 저장 및 적용하세요.');return
            if QMessageBox.question(self,'Hub 업로드',str(data['inputs'].get('artifact',''))+' → '+str(data['inputs'].get('repo_id',''))+'\n이 Script로 업로드할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        for name,label in self.previews.items():label.clear();label.setText(name+' · 새 Run 대기')
        self.handle=None;self.context={};self.env_contexts={};self.after_seq=0;self.generations.clear()
        self.stop_requested=False;self.cancel_command_id=None;self.cancel_queued=False
        self.request_id=uuid.uuid4().hex;self.operation='start';self.busy=True;self.start_button.setEnabled(False);self.state.setText('worker 시작 준비 중…')
        self.buttons()
        try:self.job.start('start',path=str(self.editor.path),modules=self.modules,request_id=self.request_id,expected_recipe_sha256=self.ready['recipe_sha256'],expected_prepared_sha256=self.ready['prepared_sha256'])
        except Exception as error:self.job_finished({'ok':False,'error':{'message':str(error)}})
    def job_finished(self,response):
        self.busy=False
        if self.operation=='terminal_catalog':self.dataset_state='저장 검증 통과' if response.get('ok') else '저장 검증 실패: '+response.get('error',{}).get('message','오류')
        if not response.get('ok'):
            self.ready=None;self.operation=None;self.start_after_prepare=False;self.state.setText(response.get('error',{}).get('message','Backend 오류'));self.buttons();return
        data=response['result']
        if self.operation=='prepare':
            import hashlib
            start=self.start_after_prepare;self.start_after_prepare=False;self.operation=None
            if self.stop_requested:self.ready=None;self.state.setText('Script 적용을 취소했습니다.');self.buttons();return
            try:current_sha=hashlib.sha256(self.editor.path.read_bytes()).hexdigest()if self.editor.path else None
            except OSError as error:self.ready=None;self.show_error(str(error));self.buttons();return
            if self.editor.dirty or current_sha!=data['recipe_sha256']:
                self.ready=None;self.state.setText('적용 중 Script가 변경되었습니다. 다시 저장 및 적용하세요.');self.buttons();return
            self.ready=data if data['runnable']and data['state']=='runtime_ready'else None
            self.state.setText('실행 준비됨 · '+self.editor.path.name if self.ready else data['reason']);self.buttons()
            if start and self.ready:self.start_run()
            return
        elif self.operation=='terminal_hardware':
            self.dataset_state='실물 결과 재개방 확인 · 측정 frame '+str(data.get('frames',data.get('verified_capture_frames',0)));self.state.setText('측정 frame '+str(data.get('frames',data.get('verified_capture_frames',0)))+' · '+str(data.get('status'))+' · command_sent='+str(data.get('command_sent',False)))
            self.display_hardware_result(data)
            self.log.appendPlainText('결과: '+str(data.get('status'))+' · 측정 '+str(data.get('frames',0))+' frame · command_sent='+str(data.get('command_sent',False)))
            for kind,labels in (('real',self.previews),('sim',self.sim_previews)):
                for n,path in data.get('images',{}).get(kind,{}).items():
                    if n in labels:labels[n].setPixmap(QPixmap(path).scaled(640,480,Qt.AspectRatioMode.KeepAspectRatio))
        elif self.operation=='terminal_catalog':
            self.log.appendPlainText('저장 결과 재개방 확인 · 완료 Episode '+str(len(data['inspection']['episodes']))+' / 미완료 intent '+str(len(data['inspection']['unresolved_source_intents'])))
        elif self.operation=='start':
            self.handle=data;self.context={};self.env_contexts={};self.owned_runs.add(data['run_dir']);self.dataset_state='미확인';self.after_seq=0;self.generations.clear();self.operation=None
            if self.stop_requested:self.send_cancel()
            else:self.state.setText('worker 실행 중')
        self.operation=None;self.buttons()
    def cancel_run(self):
        self.stop_requested=True;self.start_after_prepare=False
        if self.busy and self.operation in('prepare','start'):
            self.state.setText('취소 요청을 기억했습니다 · '+('시작 응답'if self.operation=='start'else'입력 작업 종료')+'를 기다립니다.');self.buttons();return
        if not self.handle:return
        self.send_cancel();self.buttons()

    def send_cancel(self):
        if self.cancel_queued:return
        from ..run import RunHandle,send_command
        h=self.handle
        if self.cancel_command_id is None:self.cancel_command_id=uuid.uuid4().hex
        try:
            receipt=send_command(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),{'command_id':self.cancel_command_id,'kind':'cancel','payload':{}})
            self.cancel_queued=True;self.state.setText('취소 요청 '+receipt.status+' · 실제 종료를 기다립니다')
        except Exception as error:self.show_error('취소 전달 실패 · 다시 중단을 눌러 재시도하세요: '+str(error))
    def poll(self):
        if not self.handle or self.operation in('prepare','start'):return
        from ..run import read_status,read_events,read_preview_frame
        try:
            record=json.loads((Path(self.handle['run_dir'])/'run.json').read_text());status=read_status(self.handle['run_dir'])
            page=read_events(self.handle['run_dir'],self.after_seq,100);self.after_seq=page.next_seq
            for event in page.items:
                payload=event['payload']
                if event['kind']=='log':
                    self.log.appendPlainText(payload.get('message',''))
                    if self.loss_chart:self.loss_chart.add_text(payload.get('message',''))
                if event['kind']=='status':
                    self.context=payload
                    if 'env_index' in payload:
                        if not hasattr(self,'env_contexts'):self.env_contexts={}
                        self.env_contexts[payload['env_index']]=payload
                if event['kind']=='command_ack':self.log.appendPlainText('실제 명령 ACK · '+json.dumps(payload,ensure_ascii=False))
                if event['kind']=='error':self.log.appendPlainText(json.dumps(payload,ensure_ascii=False))
            outcome=run_outcome({**record,'status':status.status});self.outcome=outcome
            terminal=outcome['worker_finished']or status.status=='unknown';self.progress_bar.setRange(0,1 if terminal else 0);self.progress_bar.setValue(1 if status.status=='completed'else 0);self.progress_bar.setFormat('Worker '+status.status)
            self.progress_text.setText('Episode '+str(outcome['completed_episodes'])+' · Attempt '+str(outcome['attempts']if outcome['attempts']is not None else'미집계')+' · Env '+str(self.context.get('env_index','—'))+' / tick '+str(self.context.get('tick','—'))+(' · 목표 미달'if outcome['goal_reached']is False else''))
            for kind,button in self.commands.items():button.setEnabled(not self.stop_requested and not outcome['worker_finished'] and status.status!='unknown' and (kind!='step' or self.engine.currentText()!='isaaclab' or int(self.execution.get('env_num',self.execution.get('num_envs',1)))==1) and (kind!='mark' or (self.execution.get('mode')=='manual' and self.mark_frame.value()<=getattr(self,'env_contexts',{}).get(self.preview_env.value(),getattr(self,'context',{})).get('tick',-1))))
            if outcome['worker_finished'] or status.status=='unknown':
                self.cancel_button.setEnabled(False)
                if status.status=='unknown' and self.handle['run_dir'] in self.owned_runs:
                    import shutil
                    shutil.rmtree(Path(self.handle['run_dir'])/'preview',ignore_errors=True)
                if (self.stage in ('annotation','datagen','simulation_evaluation') or self.stage=='real_evaluation' and (Path(self.handle['output_path'])/'run.json').is_file()) and getattr(self,'_verified_terminal',None)!=self.handle['run_id'] and not self.busy:
                    self._verified_terminal=self.handle['run_id'];self.operation='terminal_catalog';self.busy=True;self.job.start('catalog',path=self.handle['output_path'])
                if self.stage=='real_evaluation' and getattr(self,'_verified_terminal',None)!=self.handle['run_id'] and not self.busy and any((Path(self.handle['output_path'])/name).is_file()for name in ('hardware-report.json',)):
                    self._verified_terminal=self.handle['run_id'];self.operation='terminal_hardware';self.busy=True;self.job.start('hardware_result',path=self.handle['output_path'])
                if getattr(self,'_preview_terminal_cleared',None)!=self.handle['run_id']:
                    for name,label in self.previews.items():label.clear();label.setText(name+' · Live Preview 종료')
                    self._preview_terminal_cleared=self.handle['run_id']
                text='Worker '+status.status+' · '+self.dataset_state+' · 완료 Episode '+str(outcome['completed_episodes'])
                if outcome.get('existing_episodes') is not None:text+=' · 기존 '+str(outcome['existing_episodes'])+' / 추가 '+str(outcome['added_episodes'])
                if outcome['goal_reached'] is False:text+=' · 목표 미달'
                if outcome['needs_resume']:text+=' · 새 worker에서 기존 Dataset 추가 저장 필요'
                if outcome['budget_exhausted']:text+=' · Attempt 예산 소진'
                if outcome['successes'] is not None:text+=' · Task 성공 '+str(outcome['successes'])+' / 실패 '+str(outcome['failures'])
                if outcome['success_rate'] is not None:text+=' · 성공률 '+str(outcome['success_rate'])
                if outcome['error']:text+=' · '+outcome['error'].get('message','오류')
                self.state.setText(text);self.buttons()
                if self.stage=='train':self.show_training_result()
                return
            if getattr(self,'_preview_selected',None)!=(self.handle['run_id'],self.preview_env.value()) and (Path(self.handle['run_dir'])/'preview').is_dir():
                self.select_preview(self.preview_env.value());self._preview_selected=(self.handle['run_id'],self.preview_env.value())
            self.state.setText('중단 요청됨 · 실제 Worker 종료를 기다립니다.'if self.stop_requested else 'Worker '+status.status+' · '+str(record.get('progress',{}))+(' · Vector pause/resume는 전체 Scene에 적용' if self.engine.currentText()=='isaaclab' and int(self.execution.get('env_num',self.execution.get('num_envs',1)))>1 else ''))
            for camera,label in self.previews.items():
                frame=read_preview_frame(self.handle['run_dir'],camera)
                if frame is None:continue
                meta,raw=frame
                if meta.get('env_index',0)!=self.preview_env.value():continue
                if self.generations.get(camera)==meta['generation']:continue
                self.generations[camera]=meta['generation']
                if not hasattr(self,'preview_metrics'):self.preview_metrics={}
                metric=self.preview_metrics.setdefault((self.handle['run_id'],self.preview_env.value(),camera),{'frames':0,'first_ns':time.monotonic_ns(),'latency_ns':[],'generation_skips':0,'previous_generation':0,'shape':meta.get('shape')})
                metric['frames']+=1;metric['last_ns']=time.monotonic_ns();metric['latency_ns'].append(metric['last_ns']-meta.get('published_monotonic_ns',metric['last_ns']));metric['generation_skips']+=max(0,meta['generation']-metric['previous_generation']-1) if metric['previous_generation'] else 0;metric['previous_generation']=meta['generation']
                metric['latency_ns']=metric['latency_ns'][-300:]
                image=QImage.fromData(raw,b'PPM')
                if not image.isNull():label.setPixmap(QPixmap.fromImage(image).scaled(640,480,Qt.AspectRatioMode.KeepAspectRatio))
        except Exception as error:self.state.setText('상태/Preview 조회 실패: '+str(error))
    def open_result(self):
        if self.handle:QDesktopServices.openUrl(QUrl.fromLocalFile(self.handle['output_path']))
    def show_training_result(self):
        path=Path(self.handle['output_path'])/'training-result.json'
        if path.is_file() and getattr(self,'_shown_training',None)!=str(path):
            result=json.loads(path.read_text());self.log.appendPlainText(json.dumps({'loss':result['metrics'],'checkpoints':result['checkpoints']},ensure_ascii=False));self._shown_training=str(path)
