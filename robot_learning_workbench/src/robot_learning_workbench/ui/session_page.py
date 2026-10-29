"""Two task screens: project capture and measured-state Real/Sim pairing."""
import json,math,uuid,time
from pathlib import Path
import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage,QPixmap
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLabel,QPushButton,QComboBox,QFileDialog,QInputDialog,QPlainTextEdit,QTableWidget,QTableWidgetItem,QHeaderView,QDialog,QDialogButtonBox,QCheckBox,QScrollArea
from .view import CameraView
from .session_client import SessionClient
from .session_settings import DeviceSettings
from .jobs import BackendJob


class SessionPage(QWidget):
    def __init__(self,kind,python,modules,workspace,parent=None):
        super().__init__(parent);self.setObjectName('sessionPage');self.setStyleSheet('\nQWidget#sessionPage QLabel { background: transparent; }\nQWidget#sessionPage QLabel#jointCard { background: #242d3a; border-radius: 8px; padding: 8px 4px; }\nQWidget#sessionPage QPushButton { padding: 7px 10px; border-radius: 8px; }\nQWidget#sessionPage QLabel#dashboardTitle { font-size: 23px; padding: 0; }\nQWidget#sessionPage QPushButton#primaryAction:disabled { background: #263b37; color: #7c9690; border-color: #3d5550; }\n');self.kind=kind;self.workspace=Path(workspace);self.project=None;self.rows=[];self.proposal=None;self.last_progress={};self.finishing=False;self.approval_dialog=None;self.project_buttons=[]
        self.client=SessionClient(python,modules,self);self.settings=DeviceSettings(workspace,self);self.job=BackendJob(python,self);self.job.finished.connect(self.project_result)
        self.client.progress.connect(self.update_progress);self.client.received.connect(self.event_received);self.client.preview.connect(self.show_preview);self.client.error.connect(self.show_error);self.client.terminal.connect(self.ended)
        layout=QVBoxLayout(self);layout.setSpacing(6)
        title=QLabel('1. Real2Sim Capture'if kind=='capture'else'2. Real / Sim');title.setObjectName('dashboardTitle');layout.addWidget(title)
        subtitle=QLabel('Scene 이전의 실측 자료를 Builder Project에 저장합니다.'if kind=='capture'else'Follower 측정 관절값을 기준으로 실제 영상과 Candidate 렌더를 비교합니다.');layout.addWidget(subtitle)
        project_row=QHBoxLayout();layout.addLayout(project_row);project_row.addWidget(QLabel('Builder Project'))
        self.project_combo=QComboBox();self.project_combo.setMinimumWidth(220);project_row.addWidget(self.project_combo,1)
        for label,fn in [('열기',self.choose_project),('새 프로젝트',self.new_project)]:
            button=QPushButton(label);button.clicked.connect(fn);project_row.addWidget(button);self.project_buttons.append(button)
        self.project_path=QLabel('Project를 선택하세요');self.project_path.setObjectName('mutedLabel');project_row.addWidget(self.project_path,1)
        self.project_combo.currentIndexChanged.connect(self.select_project)
        body=QHBoxLayout();layout.addLayout(body,1);left=QVBoxLayout();left.setSpacing(6);body.addLayout(left,4);side=QWidget();side.setObjectName('navigationPanel');side.setMaximumWidth(310);right=QVBoxLayout(side);body.addWidget(side,1)
        grid=QGridLayout();left.addLayout(grid,5);self.previews={};self.camera_labels={}
        names=('side','wrist')if kind=='capture'else('side','sim_side','wrist','sim_wrist')
        for i,name in enumerate(names):
            panel=QWidget();panel.setObjectName('previewCard');box=QVBoxLayout(panel);box.setContentsMargins(4,4,4,4);label=QLabel(('SIM 'if name.startswith('sim_')else'REAL ')+name.replace('sim_','').upper()+' · 연결 대기');box.addWidget(label)
            view=CameraView('영상 없음',(120,75));view.setObjectName('cameraView');box.addWidget(view,1);self.previews[name]=view;self.camera_labels[name]=label
            grid.addWidget(panel,0 if kind=='capture'else i//2,i%2)
        state_row=QHBoxLayout();left.addLayout(state_row);state_row.addWidget(QLabel('로봇 상태 (Follower Feedback)'));self.state=QLabel('DISCONNECTED');state_row.addWidget(self.state,1)
        joints=QHBoxLayout();left.addLayout(joints);self.joint_labels=[]
        for name in('Shoulder Pan','Shoulder Lift','Elbow Flex','Wrist Flex','Wrist Roll','Gripper'):
            label=QLabel(name+'\n— rad\n—°');label.setAlignment(Qt.AlignmentFlag.AlignCenter);label.setObjectName('jointCard');joints.addWidget(label,1);self.joint_labels.append(label)
        actions=QGridLayout();left.addLayout(actions)
        self.connect_button=QPushButton('로봇 연결');self.connect_button.setObjectName('primaryAction');self.connect_button.clicked.connect(self.connect_session)
        self.start_teleop_button=QPushButton('▶ Teleoperation 시작');self.start_teleop_button.clicked.connect(lambda:self.send('teleop_prepare'))
        self.stop_teleop_button=QPushButton('■ Teleoperation 중지');self.stop_teleop_button.clicked.connect(lambda:self.send('teleop_stop'))
        self.capture_button=QPushButton('현재 자세 Capture'if kind=='capture'else'Real / Sim Capture');self.capture_button.setObjectName('primaryAction');self.capture_button.clicked.connect(lambda:self.send('session_snapshot'))
        self.disconnect_button=QPushButton('연결 해제');self.disconnect_button.clicked.connect(lambda:self.send('session_disconnect'))
        self.finish_button=QPushButton('Capture 작업 종료'if kind=='capture'else'작업 종료');self.finish_button.clicked.connect(self.finish)
        for i,b in enumerate((self.connect_button,self.start_teleop_button,self.stop_teleop_button,self.capture_button)):actions.addWidget(b,0,i)
        actions.addWidget(self.disconnect_button,1,0,1,2);actions.addWidget(self.finish_button,1,2,1,2)
        self.capture_hint=QLabel('저장된 장치 설정과 Project가 필요합니다');self.capture_hint.setWordWrap(True);left.addWidget(self.capture_hint)
        left.addWidget(QLabel('Snapshot 목록 · 더블 클릭하면 원본/비교 상세를 엽니다'if kind=='capture'else'Paired Capture 목록 · 원본 Real은 유지됩니다'))
        headers=['#','시간','Side','Wrist','관절 상태 (rad)','품질','상태']if kind=='capture'else['#','시간','Real Side','Sim Side','Real Wrist','Sim Wrist','관절 상태 (rad)','품질','상태']
        self.q_column=4 if kind=='capture'else 6;self.thumbnail_columns={2:'side',3:'wrist'}if kind=='capture'else{2:'side',3:'sim_side',4:'wrist',5:'sim_wrist'}
        self.snapshot_table=QTableWidget(0,len(headers));self.snapshot_table.setHorizontalHeaderLabels(headers);self.snapshot_table.setMaximumHeight(150);self.snapshot_table.setMinimumHeight(100);self.snapshot_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for column in range(len(headers)):self.snapshot_table.setColumnWidth(column,70 if column in self.thumbnail_columns else 90)
        self.snapshot_table.setColumnWidth(0,35);self.snapshot_table.horizontalHeader().setSectionResizeMode(self.q_column,QHeaderView.ResizeMode.Stretch);self.snapshot_table.cellDoubleClicked.connect(self.details);left.addWidget(self.snapshot_table,2)
        right.addWidget(QLabel('장치 설정'));self.configuration=QComboBox();right.addWidget(self.configuration);self.configuration.currentIndexChanged.connect(self.select_configuration)
        self.settings_button=QPushButton('불러오기 · 편집 · 저장');self.settings_button.clicked.connect(self.edit_settings);right.addWidget(self.settings_button)
        self.device_state=QLabel('Leader / Follower / Camera\n연결되지 않음');self.device_state.setWordWrap(True);right.addWidget(self.device_state)
        self.candidate_combo=QComboBox();self.engine=QComboBox();self.engine.addItems(['isaaclab','mujoco'])
        if kind=='real_sim':
            right.addWidget(QLabel('Simulation · 검토 중 Candidate'));right.addWidget(self.candidate_combo);refresh=QPushButton('후보 새로고침');refresh.clicked.connect(self.refresh_project);right.addWidget(refresh);self.project_buttons.append(refresh);right.addWidget(QLabel('렌더 엔진'));right.addWidget(self.engine)
            self.rerender_button=QPushButton('선택 Capture를 현재 후보로 재렌더');self.rerender_button.clicked.connect(self.rerender);right.addWidget(self.rerender_button)
        right.addStretch(1);self.session_label=QLabel('세션 없음');self.session_label.setWordWrap(True);right.addWidget(self.session_label)
        note=QLabel('원본 RGB 640×480 저장\n수신 시각 기준 정합\nScene/물리 Calibration 자동 승인 없음\n\n중지/해제: 새 Goal 차단, Torque 유지\n현장 전원 차단 수단을 확보하세요');note.setWordWrap(True);note.setObjectName('mutedLabel');right.addWidget(note)
        diagnostics=QPushButton('진단 로그');diagnostics.setCheckable(True);layout.addWidget(diagnostics);self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(100);self.log.hide();diagnostics.toggled.connect(self.log.setVisible);layout.addWidget(self.log)
        self.refresh_configurations();self.buttons(False)
    def active(self):return self.client.active()
    def cancel_run(self):self.client.cancel()
    def buttons(self,connected):
        self.connect_button.setEnabled(not self.active()and self.project is not None and self.settings.saved_recipe is not None)
        for b in(self.start_teleop_button,self.capture_button,self.stop_teleop_button,self.disconnect_button,self.finish_button):b.setEnabled(connected)
        for button in self.project_buttons:button.setEnabled(not self.active())
        self.configuration.setEnabled(not self.active())
        self.settings_button.setEnabled(not self.active());self.project_combo.setEnabled(not self.active());self.engine.setEnabled(not self.active());self.candidate_combo.setEnabled(not self.active())
    def refresh_configurations(self):
        selected=str(self.settings.saved_recipe)if self.settings.saved_recipe else None
        self.configuration.blockSignals(True);self.configuration.clear()
        for p in sorted((self.workspace/'configuration').glob('*.yaml')):self.configuration.addItem(p.stem,str(p))
        if selected:
            if self.configuration.findData(selected)<0:self.configuration.addItem(Path(selected).stem,selected)
            self.configuration.setCurrentIndex(self.configuration.findData(selected))
        self.configuration.blockSignals(False)
    def select_configuration(self):
        if self.active():return
        path=self.configuration.currentData()
        if path:
            try:self.settings.load_recipe(path);self.buttons(False)
            except Exception as error:self.show_error(str(error))
    def edit_settings(self):
        if self.active():return
        if self.configuration.currentData()and self.settings.saved_recipe is None:
            try:self.settings.load_recipe(self.configuration.currentData())
            except Exception as error:self.show_error(str(error))
        self.settings.exec();self.refresh_configurations();self.buttons(False)
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
        self.job.start('session_project',path=str(path))
    def select_project(self,index):
        path=self.project_combo.itemData(index)
        if path and(self.project is None or path!=self.project['project']):self.load_project(path)
    def refresh_project(self):
        if self.active():return
        if self.project:self.load_project(self.project['project'])
    def project_result(self,response):
        if self.active():self.show_error('연결 중 Project 변경 결과를 적용하지 않습니다');return
        if not response.get('ok'):self.show_error(response.get('error',{}).get('message','Project error'));return
        data=response['result']
        if 'project'not in data:return
        changed=self.project is None or self.project['project']!=data['project']
        self.project=data
        if changed:self.rows=[];self.snapshot_table.setRowCount(0)
        for row in data.get('snapshots',[]):self.add_snapshot(row)
        self.project_combo.blockSignals(True)
        if self.project_combo.findData(data['project'])<0:self.project_combo.addItem(data['name'],data['project'])
        self.project_combo.setCurrentIndex(self.project_combo.findData(data['project']));self.project_combo.blockSignals(False);self.project_path.setText(Path(data['project']).name);self.project_path.setToolTip(data['project'])
        self.candidate_combo.clear()
        for row in data['candidates']:self.candidate_combo.addItem(row['name']+' · '+row['status'],row['path'])
        self.buttons(False)
    def connect_session(self):
        try:
            if any(p is not self and p.active()for p in getattr(self.window(),'sessions',{}).values())or any(p.active()for p in getattr(self.window(),'workflows',{}).values()):raise ValueError('다른 Worker를 먼저 종료하세요')
            data=self.settings.recipe();data['stage']='capture_session'if self.kind=='capture'else'paired_session';data['inputs']['project']=self.project['project']
            if self.kind=='real_sim':
                if not self.candidate_combo.currentData():raise ValueError('검토할 Scene Candidate를 선택하세요')
                data['inputs']['candidate']=self.candidate_combo.currentData();data['engine']=self.engine.currentText()
            else:data.pop('engine',None);data['inputs'].pop('candidate',None)
            key='session_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6];root=self.workspace/('capture'if self.kind=='capture'else'real_sim');root.mkdir(exist_ok=True)
            data['output']={'directory':str(root/key)};path=root/(key+'.yaml');path.write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True));self.session_label.setText(key);self.client.connect_session(path);self.buttons(False);self.state.setText('입력 검사 / CONNECTING')
        except Exception as error:self.show_error(str(error))
    def send(self,kind,payload=None):
        try:return self.client.send(kind,payload)
        except Exception as error:self.show_error(str(error))
    def finish(self):self.finishing=True;self.send('session_finish')
    def update_progress(self,progress):
        if getattr(self.client,'stage',None)=='paired_rerender':
            if 'snapshot'in progress:self.add_snapshot(progress['snapshot'])
            self.state.setText('Candidate 재렌더 · 장치 연결 없음');self.buttons(False);return
        self.last_progress.update(progress);p=self.last_progress;state=p.get('session_state','CONNECTING');connected=state in('OBSERVING','TELEOP_READY','TELEOP_ACTIVE','CAPTURING');self.buttons(connected);self.state.setText(state)
        self.start_teleop_button.setEnabled(connected and not p.get('teleop_active',False));self.stop_teleop_button.setEnabled(connected and p.get('teleop_active',False));self.capture_button.setEnabled(connected and p.get('capture_ready',False));self.capture_hint.setText(p.get('capture_reason',''))
        q=p.get('q_measured')
        if q:
            for label,value in zip(self.joint_labels,q):label.setText(label.text().split('\n')[0]+f'\n{value:.4f} rad\n{math.degrees(value):.2f}°')
        source=p.get('device_source',self.settings.source.currentText());self.device_state.setText(('MEMORY · 합성 시험'if source=='memory'else'HARDWARE · 실측')+'\n'+state)
        for n,timing in p.get('camera_timing',{}).items():
            if timing:self.camera_labels[n].setText(('FAKE 'if source=='memory'else'REAL ')+n.upper()+f" · 640×480 · {timing.get('received_fps',0)or 0:.1f}FPS · age {timing['age_ms']:.0f}ms · Δt {timing['joint_skew_ms']:.0f}ms")
        if p.get('render_timing'):
            timing=p['render_timing']
            for name in ('sim_side','sim_wrist'):
                if name in self.camera_labels:self.camera_labels[name].setText(f"SIM {name[4:].upper()} · render {timing['render_ms']:.0f}ms · age {timing['age_ms']:.0f}ms")
        if 'snapshot'in progress:self.add_snapshot(progress['snapshot'])
        if 'teleop_proposal'in progress:self.approve(progress['teleop_proposal'])
        if progress.get('error'):self.show_error(progress['error'])
    def approve(self,proposal):
        if not self.isVisible():self.send('teleop_stop');return
        self.proposal=proposal;dialog=QDialog(self);self.approval_dialog=dialog;dialog.setWindowTitle('현장 감독 Teleoperation 승인');box=QVBoxLayout(dialog)
        label=QLabel('6축 구동 권한을 현재 연결에만 부여합니다. 중지/해제는 새 Goal을 차단하고 Torque를 유지합니다.\n현재 자세·Goal·방향·범위 및 전원 차단 수단을 현장에서 확인하세요.');label.setWordWrap(True);box.addWidget(label)
        detail=QPlainTextEdit(json.dumps(proposal,ensure_ascii=False,indent=2));detail.setReadOnly(True);box.addWidget(detail);checks={}
        for key,text in [('supervised','현장에서 직접 감독합니다'),('clear','충돌 위험과 주변 장애물을 확인했습니다'),('stop_ready','즉시 전원 차단 수단이 준비됐습니다'),('direction_checked','Leader/Follower 명령 방향을 확인했습니다'),('ranges_checked','현재 관절과 승인 이동 범위를 확인했습니다'),('preserve_torque','중지 시 Torque 유지 정책을 확인했습니다')]:
            check=QCheckBox(text);checks[key]=check;box.addWidget(check)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False);box.addWidget(buttons)
        for c in checks.values():c.toggled.connect(lambda:buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(all(c.isChecked()for c in checks.values())))
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()==QDialog.DialogCode.Accepted and self.isVisible():self.send('teleop_start',{'proposal_sha256':proposal['sha256'],**{k:c.isChecked()for k,c in checks.items()}})
        self.approval_dialog=None
    def event_received(self,event):
        if event['kind']in('error','log')or event['kind']=='command_ack'and event['payload'].get('status')=='rejected':self.show_error(json.dumps(event['payload'],ensure_ascii=False))
    def show_preview(self,camera,raw):
        if camera in self.previews:
            image=QImage.fromData(raw,b'PPM')
            if not image.isNull():self.previews[camera].setPixmap(QPixmap.fromImage(image))
    def show_error(self,message):self.log.appendPlainText(message);self.capture_hint.setText(message)
    def ended(self,status):
        self.state.setText('DISCONNECTED · Worker '+status);self.last_progress={};self.proposal=None;self.buttons(False)
        for name,view in self.previews.items():view.clear();view.setText(name+' · 연결 종료')
        if self.finishing:self.session_label.setText('작업 종료 · '+str(len(self.rows))+' Snapshot 보존');self.finishing=False
    def add_snapshot(self,row):
        if any(r['path']==row['path']for r in self.rows):return
        self.rows.append(row);i=self.snapshot_table.rowCount();self.snapshot_table.insertRow(i)
        stamp=time.strftime('%H:%M:%S',time.localtime(row['unix_ns']/1e9))if row.get('unix_ns')else'시각 미기록'
        values={0:i+1,1:stamp,self.q_column:', '.join(f'{q:.4f}'for q in row.get('q_measured',[])),self.q_column+1:'경고'if row.get('quality')else'보정 미확인',self.q_column+2:'Pair 저장'if row.get('paired')else'Capture 저장'}
        for column,value in values.items():self.snapshot_table.setItem(i,column,QTableWidgetItem(str(value)))
        for column,name in self.thumbnail_columns.items():
            images=list(Path(row['path']).glob('shots/*/'+name+'.png'))
            if images:
                thumbnail=CameraView(minimum=(45,32));thumbnail.show_image(images[0]);self.snapshot_table.setCellWidget(i,column,thumbnail)
        self.snapshot_table.setRowHeight(i,38)
    def details(self,row,column=0):
        from .session_results import ResultsDialog
        if 0<=row<len(self.rows):ResultsDialog(self.rows[row],self).exec()
    def rerender(self):
        if self.active():self.show_error('연결 해제 후 다른 Candidate로 재렌더하세요');return
        row=self.snapshot_table.currentRow()
        if row<0 or not self.candidate_combo.currentData():self.show_error('Capture와 Candidate를 선택하세요');return
        source=self.rows[row]['path'];root=self.workspace/'real_sim';root.mkdir(exist_ok=True);key='rerender_'+uuid.uuid4().hex;path=root/(key+'.yaml')
        data={'schema_version':1,'stage':'paired_rerender','engine':self.engine.currentText(),'inputs':{'project':self.project['project'],'candidate':self.candidate_combo.currentData(),'capture_session':source},'execution':{},'output':{'directory':str(root/key)}}
        path.write_text(yaml.safe_dump(data,sort_keys=False));self.client.connect_session(path);self.buttons(False);self.state.setText('Candidate 재렌더 · 장치 연결 없음')
    def hideEvent(self,event):
        if self.approval_dialog is not None:self.approval_dialog.reject()
        if self.client.running and self.client.stage in ('capture_session','paired_session'):self.send('teleop_stop')
        super().hideEvent(event)
