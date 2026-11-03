"""Live Leader → Simulation Source collection with saved YAML and R03 commands."""
from pathlib import Path
import hashlib
from PyQt6.QtCore import Qt,QUrl
from PyQt6.QtGui import QImage,QPixmap,QShortcut,QKeySequence,QDesktopServices
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QScrollArea,QSplitter,QGridLayout,QPlainTextEdit
from .jobs import BackendJob
from .session_client import SessionClient
from .source_settings import SourceSettings
from .view import CameraView


class SourcePage(QWidget):
    def __init__(self,python,modules,workspace,parent=None):
        super().__init__(parent);self.stage='source';self.workspace=Path(workspace);self.modules=str(modules)
        self.ready=None;self.busy=False;self.apply_cancelled=False;self.start_after_prepare=False;self.contexts={};self.saved=set();self.pending_commands=set();self.last_error=None
        self.engine=QComboBox(self);self.engine.addItems(['mujoco','isaaclab'])
        self.client=SessionClient(python,modules,self);self.client.received.connect(self.received);self.client.preview.connect(self.show_preview);self.client.error.connect(self.show_error);self.client.terminal.connect(self.ended)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.splitter=QSplitter(Qt.Orientation.Horizontal);layout.addWidget(self.splitter)
        self.viewer=QWidget();self.viewer.setObjectName('workspaceCanvas');viewer=QVBoxLayout(self.viewer);self.splitter.addWidget(self.viewer)
        actions=QHBoxLayout();viewer.addLayout(actions);self.state=QLabel('Recipe를 불러오거나 Scene을 선택하고 Script를 저장하세요.');self.state.setWordWrap(True);actions.addWidget(self.state,1)
        self.start_button=QPushButton('데모 기록 시작');self.start_button.setObjectName('primaryAction');actions.addWidget(self.start_button)
        self.cancel_button=QPushButton('중단');self.cancel_button.setObjectName('stopAction');actions.addWidget(self.cancel_button)
        controls=QHBoxLayout();viewer.addLayout(controls);self.commands={}
        for kind,text in [('save','저장 / 다음 (→)'),('discard','폐기 / 다시 (←)')]:
            button=QPushButton(text);button.clicked.connect(lambda _,name=kind:self.command(name));controls.addWidget(button,1);self.commands[kind]=button
        self.progress_text=QLabel('Leader로 Simulation 로봇을 조작합니다. 실제 Follower에는 명령을 보내지 않습니다.');self.progress_text.setWordWrap(True);viewer.addWidget(self.progress_text)
        preview=QWidget();preview.setObjectName('previewCard');grid=QGridLayout(preview);viewer.addWidget(preview,3);self.previews={}
        grid.setRowStretch(1,1)
        for column,name in enumerate(('side','wrist')):
            grid.setColumnStretch(column,1)
            grid.addWidget(QLabel('SIM '+name.upper()),0,column);view=CameraView(name.upper()+' · 실행 대기',minimum=(120,90));grid.addWidget(view,1,column);self.previews[name]=view
        tools=QHBoxLayout();viewer.addLayout(tools);tools.addWidget(QLabel('진행 / 오류 로그'));tools.addStretch();self.result_button=QPushButton('결과 폴더');tools.addWidget(self.result_button)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(600);viewer.addWidget(self.log,1)
        self.settings_scroll=QScrollArea();self.settings_scroll.setObjectName('settingsPanel');self.settings_scroll.setWidgetResizable(True);self.settings_scroll.setMinimumWidth(350)
        self.settings=SourceSettings(python,workspace,self.engine,self);self.editor=self.settings.editor;self.settings_scroll.setWidget(self.settings);self.splitter.addWidget(self.settings_scroll)
        self.splitter.setChildrenCollapsible(False);self.splitter.setStretchFactor(0,1);self.splitter.setStretchFactor(1,0);self.splitter.setSizes([850,430])
        self.job=BackendJob(python,self);self.job.finished.connect(self.prepared);self.job.log.connect(self.log.appendPlainText)
        self.settings.changed.connect(self.invalidate);self.settings.error.connect(self.show_error);self.settings.apply_requested.connect(self.apply_script)
        self.start_button.clicked.connect(self.start_run);self.cancel_button.clicked.connect(self.cancel_run);self.result_button.clicked.connect(self.open_result)
        self.viewer.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.shortcuts=[]
        for key,kind in [('Right','save'),('Left','discard'),('Q','cancel')]:
            shortcut=QShortcut(QKeySequence(key),self.viewer);shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);shortcut.setAutoRepeat(False)
            shortcut.activated.connect(self.cancel_run if kind=='cancel'else lambda name=kind:self.command(name));self.shortcuts.append(shortcut)
        self.buttons()

    @property
    def handle(self):return self.client.handle
    @property
    def timer(self):return self.client.timer
    def active(self):return self.busy or self.client.active()

    def invalidate(self):
        self.ready=None;self.buttons()
        if self.editor.dirty:self.state.setText('Script 편집 중 · 저장 및 적용하세요.')

    def buttons(self):
        active=self.active();self.settings.set_busy(active)
        self.start_button.setEnabled(not active and self.editor.path is not None and not self.editor.dirty)
        self.cancel_button.setEnabled(self.client.active()and not self.client.cancel_requested)
        context=self.contexts.get(0);recording=self.client.running and not self.client.cancel_requested and context is not None and not self.pending_commands
        self.commands['save'].setEnabled(recording and context.get('tick',0)>0)
        self.commands['discard'].setEnabled(recording);self.result_button.setEnabled(bool(self.handle))

    def apply_script(self,path,*,start=False):
        if self.active():self.show_error('현재 실행이 끝난 뒤 Script를 적용하세요.');return
        self.ready=None;self.busy=True;self.apply_cancelled=False;self.start_after_prepare=start;self.state.setText('Scene과 Script 준비 중…');self.buttons()
        try:self.job.start('prepare',path=str(path),modules=self.modules)
        except Exception as error:
            self.busy=False;self.start_after_prepare=False;self.show_error(str(error));self.buttons()

    def prepared(self,response):
        self.busy=False;start=self.start_after_prepare;self.start_after_prepare=False
        if self.apply_cancelled:self.state.setText('Script 적용을 취소했습니다.');self.buttons();return
        if not response.get('ok'):self.show_error(response.get('error',{}).get('message','Script 적용 실패'));self.buttons();return
        result=response['result']
        current=hashlib.sha256(self.editor.path.read_bytes()).hexdigest()if self.editor.path and self.editor.path.is_file()else None
        if self.editor.dirty or current!=result.get('recipe_sha256'):
            self.show_error('적용 중 Script가 변경되었습니다. 저장 및 적용을 다시 누르세요.');self.buttons();return
        if result.get('runnable'):
            self.ready=result;self.state.setText('실행 준비됨 · '+self.editor.path.name)
            scene=result['plan']['resolved_inputs']['scene'];self.log.appendPlainText('실행 Scene · '+scene['path'])
        else:self.show_error(result.get('reason','실행 준비가 되지 않았습니다.'))
        self.buttons()
        if start and self.ready is not None:self.start_run()

    def start_run(self):
        if self.active()or self.editor.path is None or self.editor.dirty:return
        if any(page is not self and page.active()for page in [*getattr(self.window(),'workflows',{}).values(),*getattr(self.window(),'sessions',{}).values()]):self.show_error('다른 실행을 종료한 뒤 시작하세요.');return
        if self.ready is None:self.apply_script(self.editor.path,start=True);return
        self.contexts.clear();self.saved.clear();self.pending_commands.clear();self.last_error=None;self.state.setText('Simulation과 Leader 연결 중…')
        for name,view in self.previews.items():view.clear();view.setText(name+' · 연결 중')
        try:self.client.start_prepared(self.editor.path,self.ready);self.viewer.setFocus()
        except Exception as error:self.ready=None;self.show_error(str(error))
        self.buttons()

    def command(self,kind):
        if not self.commands[kind].isEnabled():return
        try:
            command_id=self.client.send(kind,{'reason':'user'}if kind=='discard'else{},context=self.contexts[0]);self.pending_commands.add(command_id)
            self.contexts.clear();self.buttons()
        except Exception as error:self.show_error(str(error))

    def cancel_run(self):
        self.apply_cancelled=True;self.start_after_prepare=False;self.ready=None;self.client.cancel();self.buttons()
        if self.client.active():self.state.setText('중단 요청 · Leader와 Simulation 정리를 기다립니다.')

    def received(self,event):
        kind=event['kind'];payload=event['payload']
        if kind=='status'and 'episode_id'in payload:
            self.contexts[payload.get('env_index',0)]=payload
            self.progress_text.setText('이번 실행 저장 '+str(len(self.saved))+' Episode · '+str(payload['episode_id'])+' · '+str(payload.get('tick',0))+' frame')
            self.state.setText('기록 중 · '+self.editor.path.name)
        elif kind=='episode_committed':
            self.saved.add(payload['episode_id']);self.contexts.clear();self.log.appendPlainText('저장됨 · '+payload['episode_id'])
            self.progress_text.setText('이번 실행 저장 '+str(len(self.saved))+' Episode')
        elif kind=='log':self.log.appendPlainText(payload.get('message',''))
        elif kind=='error':self.show_error(payload.get('message',str(payload)))
        elif kind=='command_ack'and payload.get('status')in('completed','rejected'):
            self.pending_commands.discard(payload['command_id'])
            if payload['status']=='rejected':self.show_error(payload.get('reason','명령 거부'))
        self.buttons()

    def show_preview(self,name,raw):
        if name in self.previews:
            image=QImage.fromData(raw,b'PPM')
            if not image.isNull():self.previews[name].setPixmap(QPixmap.fromImage(image))

    def show_error(self,message):self.last_error=message;self.state.setText(message);self.log.appendPlainText(message)

    def ended(self,status):
        self.ready=None;self.contexts.clear();self.pending_commands.clear();self.state.setText('실행 종료 · '+status+' · 저장 '+str(len(self.saved))+' Episode'+(' · '+self.last_error if status=='failed'and self.last_error else''))
        for view in self.previews.values():view.clear();view.setText('실행 종료')
        self.buttons()

    def open_result(self):
        if self.handle:QDesktopServices.openUrl(QUrl.fromLocalFile(self.handle['output_path']))
