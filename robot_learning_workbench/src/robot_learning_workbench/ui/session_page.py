from scene_contract.naming import numbered_path
"""Scene material Capture with explicit start/stop Leader Teleoperation."""
import json,math,time
from pathlib import Path
import yaml
from PyQt6.QtCore import Qt,QSize
from PyQt6.QtGui import QImage,QPixmap
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QComboBox,QFileDialog,QInputDialog,QPlainTextEdit,QScrollArea
from .view import LiveCameraView,LiveSessionLayout,LiveCameraArea
from .session_client import SessionClient
from .device_setup import DeviceSetup
from .scene_inputs import SceneInputs
from .jobs import BackendJob
from .theme import action_icon


class CapturePage(QWidget):
    def __init__(self,python,modules,workspace,parent=None):
        super().__init__(parent);self.setObjectName('sessionPage');self.workspace=Path(workspace);self.project=None;self.last_progress={};self.finishing=False;self.materials_saving=False;self.project_buttons=[]
        self.client=SessionClient(python,modules,self);self.settings=DeviceSetup(workspace,python,modules,self);self.job=BackendJob(python,self);self.job.finished.connect(self.project_result);self.job.process.stateChanged.connect(lambda _:self.buttons(self.client.running))
        self.client.progress.connect(self.update_progress);self.client.received.connect(self.event_received);self.client.preview.connect(self.show_preview);self.client.error.connect(self.show_error);self.client.terminal.connect(self.ended)
        self.settings.calibration_client.terminal.connect(self.calibration_ended);self.request_control=False
        self.session_layout=LiveSessionLayout(self);layout=self.session_layout.content_layout
        title=QLabel('1. Scene Prepare');title.setObjectName('dashboardTitle');self.session_layout.header.insertWidget(0,title)
        subtitle=QLabel('새 프로젝트를 만들고 초기 입력·실측 이미지·Scene 메모를 모읍니다.');layout.addWidget(subtitle)
        project_row=QHBoxLayout();layout.addLayout(project_row);project_row.addWidget(QLabel('Project'))
        self.project_combo=QComboBox();self.project_combo.addItem('새 프로젝트를 만드세요',None);self.project_combo.setMinimumWidth(220);project_row.addWidget(self.project_combo,1)
        for label,fn in [('새 프로젝트',self.new_project),('프로젝트 열기',self.choose_project)]:
            button=QPushButton(label);button.clicked.connect(fn);project_row.addWidget(button);self.project_buttons.append(button)
        self.project_path=QLabel('Project를 선택하세요');self.project_path.setObjectName('mutedLabel');project_row.addWidget(self.project_path,1)
        self.project_combo.currentIndexChanged.connect(self.select_project)
        body=QHBoxLayout();layout.addLayout(body,1);left=QVBoxLayout();left.setSpacing(6);body.addLayout(left,4);side=QWidget();side.setObjectName('navigationPanel');side.setMaximumWidth(310);right=QVBoxLayout(side);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(side);scroll.setMinimumWidth(280);scroll.setMaximumWidth(330);body.addWidget(scroll,1)
        self.camera_area=LiveCameraArea();grid=QGridLayout(self.camera_area);grid.setContentsMargins(0,0,0,0);left.addWidget(self.camera_area,5);self.session_layout.set_camera(self.camera_area);self.session_layout.set_action_area(self.camera_area);self.previews={};self.camera_labels={}
        names=('side','wrist')
        for i,name in enumerate(names):
            panel=QWidget();panel.setObjectName('previewCard');box=QVBoxLayout(panel);box.setContentsMargins(6,6,6,6);label=QLabel(('SIM 'if name.startswith('sim_')else'REAL ')+name.replace('sim_','').upper()+' · 연결 대기');label.setObjectName('previewTitle');box.addWidget(label)
            view=LiveCameraView('영상 없음',title='REAL '+name.upper());view.setMinimumHeight(160);view.setObjectName('cameraView');box.addWidget(view,1);self.previews[name]=view;self.camera_labels[name]=label
            grid.addWidget(panel,0,i)
        state_row=QHBoxLayout();left.addLayout(state_row);state_row.addWidget(QLabel('로봇 상태 (Follower Feedback)'));self.state=QLabel('DISCONNECTED');state_row.addWidget(self.state,1)
        joints=QHBoxLayout();left.addLayout(joints);self.joint_labels=[]
        for name in('Shoulder Pan','Shoulder Lift','Elbow Flex','Wrist Flex','Wrist Roll','Gripper'):
            label=QLabel(name+'\n— rad\n—°');label.setAlignment(Qt.AlignmentFlag.AlignCenter);label.setObjectName('jointCard');joints.addWidget(label,1);self.joint_labels.append(label)
        actions=QGridLayout();self.session_layout.actions.addLayout(actions)
        self.connect_button=QPushButton('로봇 연결 · Teleop');self.connect_button.setObjectName('primaryAction');self.connect_button.clicked.connect(self.connect_session)
        self.capture_button=QPushButton('캡처');self.capture_button.clicked.connect(lambda:self.send('session_snapshot'))
        self.finish_button=QPushButton('종료');self.finish_button.setObjectName('stopAction');self.finish_button.clicked.connect(self.finish)
        for i,b in enumerate((self.connect_button,self.capture_button,self.finish_button)):actions.addWidget(b,0,i);actions.setColumnStretch(i,1)
        for b,icon in[(self.connect_button,'connect'),(self.capture_button,'capture'),(self.finish_button,'stop')]:b.setIcon(action_icon(icon));b.setIconSize(QSize(21,21));b.setMinimumHeight(42)
        self.connection_hint=QLabel();self.connection_hint.setWordWrap(True);self.connection_hint.setObjectName('mutedLabel');left.addWidget(self.connection_hint)
        self.capture_hint=QLabel();self.capture_hint.setWordWrap(True);self.capture_hint.hide();left.addWidget(self.capture_hint)
        self.teleop_hint=QLabel();self.teleop_hint.setWordWrap(True);self.teleop_hint.setObjectName('mutedLabel');left.addWidget(self.teleop_hint);self.teleop_hint.hide()
        self.operation_message=QLabel();self.operation_message.setWordWrap(True);left.addWidget(self.operation_message);self.operation_message.hide()
        from .snapshot_table import SnapshotTable
        self.history_toggle=QPushButton('촬영 기록')
        self.history_panel=QWidget();history=QVBoxLayout(self.history_panel);history.setContentsMargins(0,0,0,0)
        self.snapshot_table=SnapshotTable(parent=self);self.snapshot_table.error.connect(self.show_error);history.addWidget(self.snapshot_table)
        self.session_layout.set_history(self.history_toggle,self.history_panel,self.snapshot_table)
        self.settings_button=QPushButton('장치 설정');self.settings_button.clicked.connect(self.edit_settings);project_row.addWidget(self.settings_button)
        self.device_state=QLabel('저장 구성 선택 · 자동 연결 없음');self.device_state.setWordWrap(True);left.insertWidget(0,self.device_state)
        self.materials=SceneInputs(workspace,self);right.addWidget(self.materials,1);self.materials.saveRequested.connect(self.store_materials)
        self.materials.robotRigRequested.connect(self.select_robot_rig)
        self.materials.backend_python=python
        self.input_button=self.materials.add;self.notes=self.materials.notes;self.save_materials=self.materials.save
        right.addStretch(1);self.session_label=QLabel('세션 없음');self.session_label.setWordWrap(True);right.addWidget(self.session_label)
        note=QLabel('종료: 로봇·카메라 연결 해제, Torque 유지');note.setWordWrap(True);note.setObjectName('mutedLabel');right.addWidget(note)
        self.diagnostics_button=QPushButton('진단 로그');self.log=QPlainTextEdit();self.log.setReadOnly(True)
        self.log_dialog=self.session_layout.add_popup(self.diagnostics_button,self.log,'진단 로그',(1000,600))
        self.buttons(False)
        self.catalog_job=BackendJob(python,self);self.catalog_job.finished.connect(self.projects_loaded)
        self.catalog_job.start('source_scenes',workspace=str(self.workspace))
    def active(self):return self.client.active()or self.settings.calibration_client.active()
    def cancel_run(self):self.request_control=False;self.client.cancel();self.settings.calibration_client.cancel()
    def buttons(self,connected):
        from PyQt6.QtCore import QProcess
        idle=not self.active()and not self.finishing and self.job.process.state()==QProcess.ProcessState.NotRunning
        connected=connected and not self.finishing and not self.client.cancel_requested
        progress=self.last_progress
        restart=connected and progress.get('session_state')=='OBSERVING'and progress.get('teleoperation_available',False)and not progress.get('teleop_active',False)
        self.connect_button.setEnabled(idle and self.project is not None and self.settings.saved_recipe is not None or restart)
        self.connect_button.setText('Teleop 활성'if connected and progress.get('teleop_active')else'Teleop 다시 시작'if restart else'연결됨'if connected else'연결 중…'if self.active()else'로봇 연결 · Teleop')
        reason=''
        if self.finishing:reason='현재 연결 종료를 기다리세요.'
        elif self.active():reason='현재 Session이 연결 중이거나 실행 중입니다.'
        elif not idle:reason='Project·장치 구성 불러오기를 기다리세요.'
        elif self.project is None:reason='위에서 Project를 선택하거나 새 프로젝트를 만드세요.'
        elif self.settings.saved_recipe is None:reason='장치 설정에서 저장된 로봇·카메라 구성을 선택하고 저장하세요.'
        self.connect_button.setToolTip((progress.get('teleoperation_reason')or reason)if connected else(reason or'연결 준비 후 Leader → Follower Teleop을 시작합니다.'));self.connection_hint.setText(reason)
        self.connection_hint.setVisible(bool(reason)and idle)
        self.capture_button.setEnabled(connected and progress.get('capture_request_allowed',False))
        waiting=connected and progress.get('capture_pending')and not progress.get('capture_request_allowed')
        full=progress.get('capture_queue_capacity')and progress.get('capture_queue_size',0)>=progress['capture_queue_capacity']
        self.capture_button.setText(('대기열 가득 참'if full else'캡처 중…')if waiting else'캡처')
        self.finish_button.setText('종료 중…'if self.finishing else'종료')
        self.finish_button.setEnabled(self.active()and not self.finishing)
        for button in self.project_buttons:button.setEnabled(idle)
        self.settings.configuration.setEnabled(idle);self.materials.setEnabled(idle)
        self.settings_button.setEnabled(idle);self.project_combo.setEnabled(idle)
    def projects_loaded(self,response):
        if not response.get('ok'):
            self.show_error(response.get('error',{}).get('message','Project 목록을 읽지 못했습니다.'));return
        if self.active():return
        selected=self.project['project']if self.project else self.project_combo.currentData()
        self.project_combo.blockSignals(True);self.project_combo.clear();self.project_combo.addItem('Project 선택 또는 새 프로젝트 만들기',None)
        for item in response['result']['scenes']:
            self.project_combo.addItem(item['name'],item['project']);self.project_combo.setItemData(self.project_combo.count()-1,item['project'],Qt.ItemDataRole.ToolTipRole)
        index=self.project_combo.findData(selected)
        if selected and index<0:
            self.project_combo.addItem(self.project['name']if self.project else Path(selected).name,selected);index=self.project_combo.count()-1
        self.project_combo.setCurrentIndex(max(index,0));self.project_combo.blockSignals(False)
    def edit_settings(self):
        if self.active():return
        self.settings.exec();self.buttons(False)
        if self.project and self.settings.saved_recipe and not self.settings.dirty:
            self.job.start('session_bind',path=self.project['project'],configuration=str(self.settings.saved_recipe),workspace=str(self.workspace))
    def store_materials(self,files,notes):
        if self.active():return
        if not self.project:self.show_error('먼저 빈 Scene을 만들거나 선택하세요');return
        self.materials_saving=True
        self.job.start('session_materials',path=self.project['project'],files=files,notes=notes,workspace=str(self.workspace))
    def select_robot_rig(self,path):
        if self.active()or not self.project:return
        self.job.start('session_robot_rig',path=self.project['project'],rig_path=path or None,workspace=str(self.workspace))
    def choose_project(self):
        if self.active():return
        path=QFileDialog.getExistingDirectory(self,'Builder Project 선택',str(self.workspace/'scenes'))
        if path:self.load_project(path)
    def new_project(self):
        if self.active():return
        name,ok=QInputDialog.getText(self,'새 Builder Project','Project 이름')
        if ok and name:self.job.start('session_new_project',directory=str(self.workspace/'scenes'),name=name)
    def load_project(self,path):
        if self.active():raise ValueError('연결 중 Project를 변경할 수 없습니다')
        self.project=None;self.settings.saved_recipe=None;self.snapshot_table.reset();self.materials.load({});self.project_path.setText('Scene 입력 검사 중…');self.buttons(False)
        for control in(self.project_combo,self.settings_button,self.materials,*self.project_buttons):control.setEnabled(False)
        try:self.job.start('session_project',path=str(path),workspace=str(self.workspace))
        except Exception as error:self.buttons(False);self.show_error(str(error))
    def select_project(self,index):
        if self.active():return
        path=self.project_combo.itemData(index)
        if path is None:
            self.project=None;self.settings.saved_recipe=None;self.snapshot_table.reset();self.materials.load({})
            self.project_path.setText('Project를 선택하세요');self.device_state.setText('장치 설정에서 로봇/카메라를 선택하세요');self.buttons(False);return
        if path and(self.project is None or path!=self.project['project']):self.load_project(path)
    def project_result(self,response):
        if self.active():self.show_error('연결 중 Project 변경 결과를 적용하지 않습니다');return
        if not response.get('ok'):self.materials_saving=False;self.buttons(False);self.show_error(response.get('error',{}).get('message','Project error'));return
        data=response['result']
        if 'project'not in data:return
        changed=self.project is None or self.project['project']!=data['project']
        self.project=data
        if changed or self.materials_saving:self.materials.load(data)
        self.materials_saving=False
        if data.get('configuration_path'):
            try:self.settings.load_recipe(data['configuration_path']);self.device_state.setText('장치 구성 자동 복원 · '+Path(data['configuration_path']).parent.name+' · 연결 전 USB identity 재검사')
            except Exception as error:self.settings.saved_recipe=None;self.show_error(str(error))
        elif changed:self.settings.saved_recipe=None;self.device_state.setText('장치 설정에서 로봇/카메라를 선택하세요')
        if changed:self.snapshot_table.reset()
        for row in data.get('snapshots',[]):self.snapshot_table.append(row)
        self.history_toggle.setText(f'촬영 기록 ({len(self.rows)})')
        if data.get('snapshot_errors'):self.show_error('일부 캡처를 불러오지 못했습니다:\n'+'\n'.join(data['snapshot_errors']))
        self.project_combo.blockSignals(True)
        if self.project_combo.findData(data['project'])<0:self.project_combo.addItem(data['name'],data['project'])
        self.project_combo.setCurrentIndex(self.project_combo.findData(data['project']));self.project_combo.blockSignals(False);self.project_path.setText(Path(data['project']).name);self.project_path.setToolTip(data['project'])
        self.buttons(False)
    def connect_session(self):
        try:
            if self.client.running:
                if self.isVisible()and self.last_progress.get('session_state')=='OBSERVING'and self.last_progress.get('teleoperation_available')and not self.finishing and not self.client.cancel_requested:self.send('teleop_start')
                return
            if self.active()or self.finishing:return
            if any(p is not self and p.active()for p in getattr(self.window(),'sessions',{}).values())or any(p.active()for p in getattr(self.window(),'workflows',{}).values()):raise ValueError('다른 Worker를 먼저 종료하세요')
            data=self.settings.recipe();data['stage']='scene_capture'if data['stage']=='scene_capture'else'capture_session';data['inputs']['project']=self.project['project'];data.pop('engine',None)
            self.last_progress={};self.operation_message.clear();self.operation_message.hide();self.teleop_hint.hide()
            key=numbered_path(self.workspace/'capture','session_'+time.strftime('%Y%m%d'),digits=2).name;root=self.workspace/'capture';root.mkdir(exist_ok=True)
            data['output']={'directory':str(root/key)};path=root/(key+'.yaml');path.write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
            # This click authorizes exactly one start after connection readiness.
            self.request_control=data['stage']=='capture_session'and 'leader_device_profile'in data['inputs']
            self.client.connect_session(path)
            group='observations'if data['stage']=='scene_capture'else'captures';folder=Path(self.project['project'])/'input'/group/key
            self.session_label.setText('이번 실행 저장 폴더\n'+str(folder));self.session_label.setToolTip(str(folder))
            self.buttons(False);self.state.setText('입력 검사 / CONNECTING')
        except Exception as error:self.request_control=False;self.show_error(str(error))
    def send(self,kind,payload=None):
        try:
            if kind in('teleop_start','session_snapshot'):self.operation_message.clear();self.operation_message.hide()
            return self.client.send(kind,payload)
        except Exception as error:self.show_error(str(error))
    def finish(self):
        self.request_control=False;self.finishing=True;self.state.setText('종료 중…')
        self.client.finish();self.settings.calibration_client.cancel();self.buttons(False)
    def calibration_ended(self,status):
        if self.finishing and not self.active():self.ended(status)
        else:self.buttons(self.client.running)
    def update_progress(self,progress):
        self.last_progress.update(progress);p=self.last_progress;state=p.get('session_state','CONNECTING');connected=state in('OBSERVING','TELEOP_ACTIVE','CAPTURING');self.buttons(connected);self.state.setText('종료 중…'if self.finishing else state)
        self.capture_hint.setVisible(connected and not self.finishing)
        from .view import capture_progress_text
        self.capture_hint.setText(capture_progress_text(p))
        self.capture_hint.setToolTip(p.get('capture_reason',''))
        teleop_reason=p.get('teleoperation_reason','');self.teleop_hint.setText(teleop_reason);self.teleop_hint.setVisible(connected and bool(teleop_reason))
        q=p.get('q_measured')
        if q:
            for label,value in zip(self.joint_labels,q):label.setText(label.text().split('\n')[0]+f'\n{value:.4f} rad\n{math.degrees(value):.2f}°')
        if getattr(self.client,'stage',None)=='scene_capture'and not p.get('sdk_feedback'):
            for label in self.joint_labels:label.setText(label.text().split('\n')[0]+'\n로봇 미사용\n—')
        if p.get('sdk_feedback'):
            feedback=p['sdk_feedback']
            for label,(name,value)in zip(self.joint_labels,feedback['native'].items()):label.setText(label.text().split('\n')[0]+f'\n{value:.2f} SDK'+(' %'if name=='gripper'else' °')+'\nmodel rad 미결합')
        source=p.get('device_source');self.device_state.setText(('MEMORY · 합성 시험'if source=='memory'else'HARDWARE · 실측')+'\n'+('종료 중…'if self.finishing else state))
        for n,timing in p.get('camera_timing',{}).items():
            if timing:
                skew=timing.get('joint_skew_ms');suffix=f' · Δt {skew:.0f}ms'if skew is not None else' · camera receipt'
                self.camera_labels[n].setText(('FAKE 'if source=='memory'else'REAL ')+n.upper()+f" · 640×480 · {timing.get('received_fps',0)or 0:.1f}FPS · age {timing['age_ms']:.0f}ms"+suffix)
        if progress.get('capture_update'):
            self.snapshot_table.append(progress['capture_update']);self.history_toggle.setText(f'촬영 기록 ({len(self.rows)})')
        if 'snapshot'in progress:
            self.snapshot_table.append(progress['snapshot']);self.history_toggle.setText(f'촬영 기록 ({len(self.rows)})')
        if progress.get('error'):self.request_control=False;self.show_error(progress['error'])
        if self.request_control and state=='OBSERVING':
            self.request_control=False
            if self.isVisible()and self.client.running and not self.finishing and not self.client.cancel_requested and p.get('teleoperation_available')and not p.get('teleop_active')and not progress.get('error'):self.send('teleop_start')
    def event_received(self,event):
        if event['kind']=='log':self.log.appendPlainText(str(event['payload'].get('message',event['payload'])));return
        if event['kind']=='error'or event['kind']=='command_ack'and event['payload'].get('status')=='rejected':
            self.request_control=False
            payload=event['payload'];reason=payload.get('reason')or payload.get('message')or json.dumps(payload,ensure_ascii=False)
            self.snapshot_table.reject(payload.get('command_id'),reason);self.show_error(reason)
    def show_preview(self,camera,raw):
        if camera in self.previews:
            image=QImage.fromData(raw,b'PPM')
            if not image.isNull():self.previews[camera].setPixmap(QPixmap.fromImage(image))
    def show_error(self,message):self.request_control=False;self.log.appendPlainText(message);self.operation_message.setText(message);self.operation_message.show()
    def ended(self,status):
        self.request_control=False
        self.snapshot_table.finish_pending('연결 종료: 최종 저장·등록 완료를 확인하지 못했습니다. 원본 저장 경로를 확인하세요.')
        if self.finishing and self.settings.calibration_client.active():self.buttons(False);return
        if self.finishing:self.session_label.setText('종료 · 저장된 Snapshot '+str(len(self.rows))+'개 표시\n'+self.session_label.toolTip())
        self.finishing=False;self.state.setText('연결 종료'if status in('completed','cancelled')else'연결 상태 확인 필요');self.last_progress={};self.buttons(False)
        self.teleop_hint.hide();self.capture_hint.hide();self.device_state.setText(self.state.text())
        if status in('completed','cancelled'):self.operation_message.clear();self.operation_message.hide()
        for name,view in self.previews.items():
            view.clear();view.setText('연결 종료');self.camera_labels[name].setText('REAL '+name.upper()+' · 연결 종료')
        for label in self.joint_labels:label.setText(label.text().split('\n')[0]+'\n— rad\n—°')
    @property
    def rows(self):return self.snapshot_table.rows
    def stop_timers(self):self.client.timer.stop();self.settings.calibration_client.timer.stop()
    def hideEvent(self,event):
        self.request_control=False
        if self.client.running and self.client.stage=='capture_session':self.send('teleop_stop')
        super().hideEvent(event)
