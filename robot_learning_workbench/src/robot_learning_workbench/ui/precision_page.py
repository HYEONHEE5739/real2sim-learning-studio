from scene_contract.naming import numbered_path
"""Guided reference-angle calibration; R03 owns Torque release and manual reference collection."""
from pathlib import Path
import math,time,yaml
from PyQt6.QtCore import Qt,pyqtSignal
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QComboBox,QPushButton,QLineEdit,QFileDialog,QDoubleSpinBox,QTableWidget,
    QTableWidgetItem,QPlainTextEdit,QScrollArea,QGroupBox,QHeaderView)
from .session_client import SessionClient


class PrecisionPage(QWidget):
    profile_saved=pyqtSignal(object)

    def __init__(self,python,modules,workspace,parent=None):
        super().__init__(parent)
        self.workspace=Path(workspace);self.results={};self.pending={};self.latest={};self.selection_sent=False
        self.client=SessionClient(python,modules,self)
        self.client.progress.connect(self.update_progress);self.client.error.connect(self.error)
        self.client.received.connect(self.received);self.client.terminal.connect(self.ended)
        layout=QVBoxLayout(self)
        title=QLabel('4. Precision Calibration');title.setObjectName('dashboardTitle');layout.addWidget(title)
        self.state=QLabel('연결하면 선택한 로봇의 전체 토크가 풀립니다. 로봇을 지지한 상태에서 연결하세요.');self.state.setWordWrap(True);layout.addWidget(self.state)
        scroll=QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll)
        content=QWidget();body=QVBoxLayout(content);scroll.setWidget(content)
        selection=QFormLayout();body.addLayout(selection)
        configuration=QHBoxLayout();self.configuration=QComboBox();configuration.addWidget(self.configuration,1)
        self.refresh_button=QPushButton('새로고침');configuration.addWidget(self.refresh_button)
        selection.addRow('장치 설정',configuration)
        self.role=QComboBox();self.role.addItem('Follower','follower');self.role.addItem('Leader','leader');selection.addRow('보정할 로봇',self.role)
        self.joint=QComboBox()
        for name,label in [('shoulder_pan','Shoulder Pan'),('shoulder_lift','Shoulder Lift'),('elbow_flex','Elbow Flex'),('wrist_flex','Wrist Flex'),('wrist_roll','Wrist Roll'),('gripper','Gripper')]:self.joint.addItem(label,name)
        selection.addRow('보정할 관절',self.joint)
        profile_row=QHBoxLayout();self.profile_file=QLineEdit();self.profile_file.setReadOnly(True);self.profile_file.setPlaceholderText('저장된 Precision 파일 또는 새 보정');profile_row.addWidget(self.profile_file,1)
        self.profile_button=QPushButton('Precision 파일 선택');profile_row.addWidget(self.profile_button);selection.addRow('Precision 파일',profile_row)
        connection=QHBoxLayout();body.addLayout(connection)
        self.connect_button=QPushButton('1. 연결 · 토크 해제');self.connect_button.setObjectName('primaryAction')
        self.disconnect=QPushButton('보정 작업 종료');self.disconnect.setObjectName('stopAction')
        connection.addWidget(self.connect_button);connection.addWidget(self.disconnect)
        self.current_angle=QLabel('현재 적용 각도 · —');self.current_angle.setStyleSheet('font-size: 24px; font-weight: bold; padding: 8px;');body.addWidget(self.current_angle)
        self.candidate_angle=QLabel('새 보정 각도 · 아직 계산하지 않았습니다.');self.candidate_angle.setStyleSheet('font-size: 20px; padding: 8px;');body.addWidget(self.candidate_angle)
        self.difference=QLabel('현재각과 새 보정각은 모터값을 변환한 값입니다. 실제 기준각은 직접 맞춰 입력하세요.');self.difference.setWordWrap(True);body.addWidget(self.difference)
        self.torque_label=QLabel();body.addWidget(self.torque_label)
        record_box=QGroupBox('2. 손으로 기준 자세에 맞추고 기록 · 자동 계산');body.addWidget(record_box);record_layout=QVBoxLayout(record_box)
        help_text=QLabel('로봇을 지지하고 관절을 기준 자세에 맞추세요. 아래에 실제 기준각을 입력하고 기록하면 바로 계산합니다.\n0°로 맞출 자세라면 0°를 입력하세요. 다른 자세에서도 추가로 기록할 수 있습니다.')
        help_text.setWordWrap(True);record_layout.addWidget(help_text)
        record_row=QHBoxLayout();record_layout.addLayout(record_row);record_row.addWidget(QLabel('손으로 맞춘 실제 기준각'))
        self.angle=QDoubleSpinBox();self.angle.setRange(-360,360);self.angle.setDecimals(3);self.angle.setSuffix(' °');record_row.addWidget(self.angle)
        self.record=QPushButton('지금 자세 기록');record_row.addWidget(self.record)
        self.references=QTableWidget(0,6);self.references.setHorizontalHeaderLabels(['입력 기준각 °','모터 숫자','보정 전 각도 °','보정 전 − 기준 °','보정 후 각도 °','보정 후 − 기준 °'])
        self.references.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.references.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.references.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.references.setSelectionMode(QTableWidget.SelectionMode.SingleSelection);self.references.setMinimumHeight(150);self.references.setMaximumHeight(230);record_layout.addWidget(self.references)
        self.remove=QPushButton('선택 자세 삭제');record_layout.addWidget(self.remove)
        self.fit_result=QLabel('기록한 자세가 없습니다.');self.fit_result.setWordWrap(True);body.addWidget(self.fit_result)
        self.next_step=QLabel();self.next_step.setWordWrap(True);body.addWidget(self.next_step)
        saved=QHBoxLayout();body.addLayout(saved);self.save_button=QPushButton('3. 저장 · 자동 적용');self.save_as_button=QPushButton('다른 이름으로 저장 · 자동 적용');saved.addWidget(self.save_button);saved.addWidget(self.save_as_button)
        self.saved_status=QLabel();self.saved_status.setWordWrap(True);body.addWidget(self.saved_status)
        self.advanced=QGroupBox('상세 정보');self.advanced.setCheckable(True);self.advanced.setChecked(False);body.addWidget(self.advanced)
        advanced_content=QWidget();QVBoxLayout(self.advanced).addWidget(advanced_content);advanced=QVBoxLayout(advanced_content)
        self.advanced.toggled.connect(advanced_content.setVisible);advanced_content.hide()
        details=QFormLayout();advanced.addLayout(details)
        model_row=QHBoxLayout();self.model=QLineEdit();self.model_button=QPushButton('선택');model_row.addWidget(self.model,1);model_row.addWidget(self.model_button);details.addRow('기준 Robot Model (URDF)',model_row)
        self.measurement=QLabel('Raw / SDK Native · —');self.measurement.setWordWrap(True);advanced.addWidget(self.measurement)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(120);self.log.setMaximumBlockCount(200);advanced.addWidget(self.log)
        body.addStretch()
        self.refresh_button.clicked.connect(self.refresh);self.configuration.currentIndexChanged.connect(self.select_configuration);self.role.currentIndexChanged.connect(self.select_configuration);self.profile_button.clicked.connect(self.choose_profile)
        self.model_button.clicked.connect(self.choose_model);self.connect_button.clicked.connect(self.connect_session);self.disconnect.clicked.connect(self.cancel_run)
        self.joint.currentIndexChanged.connect(self.select_joint);self.angle.valueChanged.connect(self.show_measurement)
        self.record.clicked.connect(lambda:self.send('precision_record',joint=self.joint.currentData(),angle_rad=math.radians(self.angle.value())))
        self.remove.clicked.connect(self.remove_reference);self.references.itemSelectionChanged.connect(self.buttons)
        self.save_button.clicked.connect(lambda:self.save_profile(True));self.save_as_button.clicked.connect(lambda:self.save_profile(False))
        self.refresh();self.buttons()

    def active(self):return self.client.active()
    def stop_timers(self):self.client.timer.stop()

    def refresh(self):
        if self.active():return
        selected=self.configuration.currentData();self.configuration.blockSignals(True);self.configuration.clear()
        for path in sorted((self.workspace/'devices').glob('*/capture.yaml')):self.configuration.addItem(path.parent.name,str(path.resolve()))
        index=self.configuration.findData(selected);self.configuration.setCurrentIndex(max(0,index));self.configuration.blockSignals(False);self.select_configuration();self.buttons()

    def select_configuration(self,*_):
        if self.active():return
        try:
            path=self.configuration.currentData();data=yaml.safe_load(Path(path).read_text())if path else{};model=data.get('inputs',{}).get('robot_model')
            self.model.setText(str((Path(path).parent/model).resolve())if model else'')
            key='calibration_profile'if self.role.currentData()=='follower'else'leader_calibration_profile';profile=data.get('inputs',{}).get(key)
            self.profile_file.setText(str((Path(path).parent/profile).resolve())if profile else'')
            self.results.clear();self.saved_status.clear();self.show_references()
        except Exception as error:self.error(str(error));self.model.clear()

    def choose_model(self):
        path,_=QFileDialog.getOpenFileName(self,'Workspace 소유 URDF 선택',str(self.workspace),'URDF (*.urdf)')
        if path:self.model.setText(path)

    def choose_profile(self):
        path,_=QFileDialog.getOpenFileName(self,'Precision 보정 파일 선택',str(self.workspace/'calibration'),'Precision JSON (*.json)')
        if path:self.profile_file.setText(path);self.results.clear();self.saved_status.clear();self.show_references()

    def save_profile(self,overwrite):
        path=self.profile_file.text()
        if not overwrite:
            initial=Path(path)if path else self.workspace/'calibration'/(self.role.currentData()+'-precision.json')
            initial=initial.with_name(initial.stem+'-new.json')
            path,_=QFileDialog.getSaveFileName(self,'새 이름으로 Precision 저장',str(initial),'Precision JSON (*.json)')
        if path:
            target=Path(path)
            if not target.suffix:target=target.with_suffix('.json')
            self.send('precision_save',path=str(target.resolve()),overwrite=overwrite)

    def connect_session(self):
        try:
            if any(p is not self and p.active()for p in getattr(self.window(),'sessions',{}).values())or any(p.active()for p in getattr(self.window(),'workflows',{}).values()):raise ValueError('다른 장치/실행을 먼저 종료하세요.')
            if not self.configuration.currentData():raise ValueError('먼저 장치 설정을 저장하세요.')
            if not self.model.text().strip():raise ValueError('장치 설정에 기준 Robot Model이 없습니다. 상세 정보에서 URDF를 선택하세요.')
            path=Path(self.configuration.currentData());data=yaml.safe_load(path.read_text());role=self.role.currentData();dk='device_profile'if role=='follower'else'leader_device_profile'
            if dk not in data['inputs']:raise ValueError('선택한 로봇이 이 장치 설정에 없습니다.')
            inputs={'configuration':str(path),'device_profile':str((path.parent/data['inputs'][dk]).resolve()),'robot_model':str(Path(self.model.text()).resolve())}
            if self.profile_file.text():inputs['calibration_profile']=str(Path(self.profile_file.text()).resolve())
            if 'source_robot_model'in data['inputs']:inputs['source_robot_model']=str((path.parent/data['inputs']['source_robot_model']).resolve())
            root=self.workspace/'calibration/sessions';root.mkdir(parents=True,exist_ok=True);key=numbered_path(self.workspace/'calibration/sessions','precision_'+time.strftime('%Y%m%d'),digits=2).name
            recipe={'schema_version':1,'stage':'precision_session','inputs':inputs,'execution':{'role':role,'device_source':data['execution']['device_source']},'output':{'directory':str(root/key)}}
            target=root/(key+'.yaml');target.write_text(yaml.safe_dump(recipe,sort_keys=False));self.saved_status.clear();self.results.clear();self.pending.clear();self.latest={};self.selection_sent=False;self.show_references()
            self.client.connect_session(target);self.state.setText('연결 중 · 선택 로봇의 토크를 해제합니다.');self.buttons()
        except Exception as error:self.error(str(error))

    def send(self,kind,**payload):
        try:
            if kind in('precision_record','precision_remove'):self.saved_status.clear()
            key=self.client.send(kind,payload);self.pending[key]=kind;self.buttons()
        except Exception as error:self.error(str(error))

    def select_joint(self,*_):
        self.latest={};self.show_measurement();self.show_references()
        if self.client.running and not self.client.cancel_requested:self.send('precision_select',joint=self.joint.currentData())

    def remove_reference(self):
        item=self.references.item(self.references.currentRow(),0)
        if item:self.send('precision_remove',reference_id=item.data(Qt.ItemDataRole.UserRole))

    def show_measurement(self,*_):
        m=self.latest
        if not m:
            self.current_angle.setText('현재 적용 각도 · —');self.candidate_angle.setText('새 보정 각도 · —');self.torque_label.clear();self.difference.setText('입력 기준 자세에 맞췄을 때 보정 전·후 각도를 비교하세요.');self.measurement.setText('Raw / SDK Native · —');return
        before=m.get('before_model_rad');after=m.get('after_model_rad');reference=self.angle.value()
        self.current_angle.setText('현재 적용 각도 · '+(f'{math.degrees(before):.3f}°'if before is not None else'미결합'))
        self.candidate_angle.setText('새 보정 각도 · '+(f'{math.degrees(after):.3f}°'if after is not None else'아직 계산하지 않았습니다.'))
        delta=[]
        if before is not None:delta.append(f'보정 전 − 입력 기준각: {math.degrees(before)-reference:+.3f}°')
        if after is not None:delta.append(f'보정 후 − 입력 기준각: {math.degrees(after)-reference:+.3f}°')
        self.difference.setText(' / '.join(delta)+' · 입력 기준 자세에 맞췄을 때 비교하세요.')
        self.torque_label.setText('Torque 꺼짐 · 지지한 상태에서 손으로 자세를 맞추세요.'if m['torque']==0 else'Torque가 다시 켜졌습니다. 보정 작업을 종료한 뒤 재연결하세요.')
        self.measurement.setText(f"Raw {m['raw']} / SDK Native {m['legacy_position']:.4f}")

    def show_references(self):
        result=self.results.get(self.joint.currentData(),{});rows=result.get('references',[]);candidate=result.get('candidate')
        self.references.setRowCount(len(rows))
        for i,row in enumerate(rows):
            before=row.get('before_model_rad');error=candidate['errors_rad'][i]if candidate and i<len(candidate.get('errors_rad',[]))else None
            after=row['angle_rad']+error if error is not None else None
            values=(math.degrees(row['angle_rad']),row['raw'],math.degrees(before)if before is not None else None,math.degrees(before-row['angle_rad'])if before is not None else None,math.degrees(after)if after is not None else None,math.degrees(error)if error is not None else None)
            for col,value in enumerate(values):
                item=QTableWidgetItem('—'if value is None else str(value)if col==1 else f'{value:.3f}')
                item.setToolTip('별도 검증 자세'if row['split']=='validation'else'보정 계산용 자세')
                if col==0:item.setData(Qt.ItemDataRole.UserRole,row['reference_id'])
                self.references.setItem(i,col,item)
        if not rows:self.fit_result.setText('기록한 자세가 없습니다.');self.next_step.setText('기준 자세에 맞추고 지금 자세 기록을 누르세요.')
        elif not candidate:self.fit_result.setText('기준 자세를 기록하세요.');self.next_step.setText('기록하면 바로 계산됩니다.')
        else:
            self.fit_result.setText(f'{len(rows)}개 자세로 계산됨 · '+('한 자세의 기준각 보정'if len(rows)==1 else'여러 자세의 각도 변환 보정'))
            self.next_step.setText('저장하면 선택 파일과 사용 장치 구성에 바로 반영됩니다.')
        self.buttons()

    def update_progress(self,progress):
        if progress.get('error'):self.error(progress['error'])
        measurement=progress.get('current_measurement')
        if measurement and not self.selection_sent:
            self.selection_sent=True
            if measurement.get('joint')!=self.joint.currentData():self.send('precision_select',joint=self.joint.currentData())
        if measurement and measurement.get('joint')==self.joint.currentData():
            self.latest=measurement;self.state.setText('연결됨 · '+self.role.currentText()+' / '+self.joint.currentText());self.show_measurement()
        result=progress.get('precision_result')
        if result:
            self.results[result['joint']]=result
            if result['joint']==self.joint.currentData():self.show_references()
            if result['kind']=='precision_save':
                saved=result['result'];self.profile_file.setText(saved['path']);self.saved_status.setText('저장·자동 적용됨 · '+saved['path'])
                self.configuration.blockSignals(True);index=self.configuration.findData(saved['configuration_path'])
                if index<0:self.configuration.addItem(Path(saved['configuration_path']).parent.name,saved['configuration_path']);index=self.configuration.count()-1
                self.configuration.setCurrentIndex(index);self.configuration.blockSignals(False);self.profile_saved.emit(saved)
        self.buttons()

    def buttons(self):
        active=self.active();ready=self.client.running and not self.client.cancel_requested and not self.pending
        for widget in(self.configuration,self.role,self.model,self.model_button,self.refresh_button,self.profile_button):widget.setEnabled(not active)
        self.connect_button.setEnabled(not active and self.configuration.currentData()is not None)
        for widget in(self.joint,self.angle):widget.setEnabled(ready or not active)
        self.record.setEnabled(ready and self.latest.get('torque')==0);self.remove.setEnabled(ready and self.references.currentRow()>=0)
        calculated=any(result.get('candidate')for result in self.results.values())
        self.save_button.setEnabled(ready and calculated and bool(self.profile_file.text()));self.save_as_button.setEnabled(ready and calculated);self.disconnect.setEnabled(active)

    def received(self,event):
        if event['kind']!='command_ack':return
        payload=event['payload']
        if payload.get('status')in('completed','rejected'):
            self.pending.pop(payload['command_id'],None)
            if payload['status']=='rejected':self.error(payload.get('reason','명령 거부'))
            self.buttons()

    def error(self,message):
        explanations={'Torque was enabled again; end calibration before reconnecting':'Torque가 다시 켜졌습니다. 보정 작업을 종료한 뒤 재연결하세요.','References are not distinct enough':'기준 자세가 너무 가깝습니다. 다른 각도에서 기록하세요.','Finite reference angle inside URDF limits required':'입력한 기준각이 이 관절의 모델 허용 범위를 벗어났습니다.'}
        text=explanations.get(message,message);self.log.appendPlainText(message);self.next_step.setText(text)

    def cancel_run(self):self.client.finish();self.buttons()
    def ended(self,status):
        self.pending.clear();self.latest={};self.show_measurement();self.state.setText('보정 작업 종료 · '+status);self.buttons()
