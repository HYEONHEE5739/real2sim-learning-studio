"""Manual reference-angle calibration. The R03 child exclusively owns the device."""
from pathlib import Path
import math,time,uuid,yaml
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QLineEdit,QFileDialog,QDoubleSpinBox,QTableWidget,QTableWidgetItem,QMessageBox,QPlainTextEdit
from .session_client import SessionClient


class PrecisionPage(QWidget):
    activated=pyqtSignal(object)
    def __init__(self,python,modules,workspace,parent=None):
        super().__init__(parent);self.workspace=Path(workspace);self.saved_profile=None
        self.client=SessionClient(python,modules,self);self.client.progress.connect(self.update_progress);self.client.error.connect(self.error);self.client.received.connect(self.received);self.client.terminal.connect(self.ended)
        box=QVBoxLayout(self);title=QLabel('4. Precision Calibration');title.setObjectName('dashboardTitle');box.addWidget(title)
        hint=QLabel('사용자가 지지한 로봇을 기준 자세로 직접 맞추고 Raw Encoder ↔ 모델 기준각을 기록합니다. SDK Motor Calibration과 별개이며 Goal/Torque 명령을 보내지 않습니다.');hint.setWordWrap(True);box.addWidget(hint)
        top=QHBoxLayout();box.addLayout(top);self.configuration=QComboBox();top.addWidget(self.configuration,1);self.refresh_button=QPushButton('구성 새로고침');top.addWidget(self.refresh_button);self.refresh_button.clicked.connect(self.refresh)
        self.role=QComboBox();self.role.addItems(['follower','leader']);top.addWidget(self.role);self.configuration.currentIndexChanged.connect(self.select_configuration)
        model=QHBoxLayout();box.addLayout(model);model.addWidget(QLabel('URDF 모델'));self.model=QLineEdit();model.addWidget(self.model,1);self.model_button=QPushButton('선택');model.addWidget(self.model_button);self.model_button.clicked.connect(self.choose_model)
        connection=QHBoxLayout();box.addLayout(connection);self.connect_button=QPushButton('측정 연결');self.disconnect=QPushButton('연결 해제');connection.addWidget(self.connect_button);connection.addWidget(self.disconnect);self.connect_button.clicked.connect(self.connect_session);self.disconnect.clicked.connect(self.cancel_run)
        self.state=QLabel('DISCONNECTED');box.addWidget(self.state);self.measurement=QLabel('Raw / Native / 보정 전·후 각도 · —');self.measurement.setWordWrap(True);box.addWidget(self.measurement)
        row=QHBoxLayout();box.addLayout(row);self.joint=QComboBox();self.joint.addItems(['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper']);row.addWidget(self.joint);self.joint.currentTextChanged.connect(self.select_joint)
        row.addWidget(QLabel('수동 기준각 (°)'));self.angle=QDoubleSpinBox();self.angle.setRange(-360,360);self.angle.setDecimals(3);row.addWidget(self.angle);self.split=QComboBox();self.split.addItem('Fit 기준 자세','train');self.split.addItem('별도 검토 자세','validation');row.addWidget(self.split)
        self.record=QPushButton('현재 Raw 기록');row.addWidget(self.record);self.record.clicked.connect(lambda:self.send('precision_record',joint=self.joint.currentText(),angle_rad=math.radians(self.angle.value()),split=self.split.currentData()))
        self.references=QTableWidget(0,6);self.references.setHorizontalHeaderLabels(['Reference ID','Raw','기준각 °','용도','보정 전 오차 °','보정 후 오차 °']);self.references.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.references.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);box.addWidget(self.references,1)
        actions=QHBoxLayout();box.addLayout(actions);self.remove=QPushButton('선택 기준 삭제');actions.addWidget(self.remove);self.remove.clicked.connect(self.remove_reference)
        self.fit=QPushButton('Fit 계산');actions.addWidget(self.fit);self.fit.clicked.connect(lambda:self.send('precision_fit',joint=self.joint.currentText()))
        actions.addWidget(QLabel('검토 허용 오차 (°)'));self.tolerance=QDoubleSpinBox();self.tolerance.setRange(.001,5);self.tolerance.setDecimals(3);self.tolerance.setValue(.5);actions.addWidget(self.tolerance)
        self.review=QPushButton('Fit 근거 Review');actions.addWidget(self.review);self.review.clicked.connect(lambda:self.review_candidate(False));self.validate=QPushButton('별도 자세 검증');actions.addWidget(self.validate);self.validate.clicked.connect(lambda:self.review_candidate(True))
        self.fit_result=QLabel('Fit/Review 결과 없음 · 수동 기준의 정확도는 별도로 확인해야 합니다.');self.fit_result.setWordWrap(True);box.addWidget(self.fit_result)
        saved=QHBoxLayout();box.addLayout(saved);self.save_button=QPushButton('새 Profile 저장');saved.addWidget(self.save_button);self.save_button.clicked.connect(lambda:self.send('precision_save'));self.apply_button=QPushButton('승인 후 장치 구성에 적용');saved.addWidget(self.apply_button);self.apply_button.clicked.connect(self.apply_profile)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(110);self.log.setMaximumBlockCount(200);box.addWidget(self.log);self.refresh();self.buttons()
    def active(self):return self.client.active()
    def stop_timers(self):self.client.timer.stop()
    def refresh(self):
        if self.active():return
        selected=self.configuration.currentData();self.configuration.blockSignals(True);self.configuration.clear()
        for path in sorted((self.workspace/'devices').glob('*/capture.yaml')):self.configuration.addItem(path.parent.name,str(path.resolve()))
        index=self.configuration.findData(selected);self.configuration.setCurrentIndex(max(0,index));self.configuration.blockSignals(False);self.select_configuration()
    def select_configuration(self,*_):
        if self.active():return
        try:
            path=self.configuration.currentData();data=yaml.safe_load(Path(path).read_text())if path else{};model=data.get('inputs',{}).get('robot_model');self.model.setText(str((Path(path).parent/model).resolve())if model else'')
        except Exception as error:self.error(str(error));self.model.clear()
    def choose_model(self):
        path,_=QFileDialog.getOpenFileName(self,'Workspace 소유 URDF 선택',str(self.workspace),'URDF (*.urdf)')
        if path:self.model.setText(path)
    def connect_session(self):
        try:
            if any(p is not self and p.active()for p in getattr(self.window(),'sessions',{}).values())or any(p.active()for p in getattr(self.window(),'workflows',{}).values()):raise ValueError('다른 장치/실행을 먼저 종료하세요.')
            path=Path(self.configuration.currentData());data=yaml.safe_load(path.read_text());role=self.role.currentText();dk='device_profile'if role=='follower'else'leader_device_profile';pk='calibration_profile'if role=='follower'else'leader_calibration_profile'
            inputs={'configuration':str(path),'device_profile':str((path.parent/data['inputs'][dk]).resolve()),'robot_model':str(Path(self.model.text()).resolve())}
            for key,source in(('calibration_profile',pk),('source_robot_model','source_robot_model')):
                if source in data['inputs']:inputs[key]=str((path.parent/data['inputs'][source]).resolve())
            root=self.workspace/'calibration/sessions';root.mkdir(parents=True,exist_ok=True);key='precision_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
            recipe={'schema_version':1,'stage':'precision_session','inputs':inputs,'execution':{'role':role,'device_source':data['execution']['device_source']},'output':{'directory':str(root/key)}}
            target=root/(key+'.yaml');target.write_text(yaml.safe_dump(recipe,sort_keys=False));self.saved_profile=None;self.references.setRowCount(0);self.client.connect_session(target);self.state.setText('CONNECTING');self.buttons()
        except Exception as error:self.error(str(error))
    def send(self,kind,**payload):
        try:
            if kind in('precision_record','precision_remove','precision_fit','precision_review'):self.saved_profile=None
            self.client.send(kind,payload);self.buttons()
        except Exception as error:self.error(str(error))
    def select_joint(self,joint):
        self.references.setRowCount(0);self.fit_result.setText('선택 관절 결과를 기다립니다.');self.measurement.setText('선택 관절 측정 대기')
        if self.client.running:self.send('precision_select',joint=joint)
    def remove_reference(self):
        item=self.references.item(self.references.currentRow(),0)
        if item:self.send('precision_remove',reference_id=item.text())
    def review_candidate(self,independent):self.send('precision_review',joint=self.joint.currentText(),tolerance_deg=self.tolerance.value(),independent=independent)
    def apply_profile(self):
        if not self.saved_profile:return
        text='새 Precision Profile을 참조하는 장치 구성을 만듭니다. 기존 Profile/Scene Package는 보존됩니다. Capture가 원 구성을 선택 중이면 화면에서 새 구성을 선택합니다. Project Binding은 장치 설정 저장으로 별도 적용합니다. 실제 모터는 움직이지 않습니다. 적용하시겠습니까?'
        if QMessageBox.question(self,'Precision 적용 승인',text)==QMessageBox.StandardButton.Yes:self.send('precision_activate',path=self.saved_profile,approved=True)
    def update_progress(self,progress):
        if progress.get('error'):self.error(progress['error'])
        if progress.get('current_measurement',{}).get('joint')==self.joint.currentText():
            m=progress['current_measurement'];self.state.setText('CONNECTED · '+self.role.currentText()+' / '+m['joint']);self.measurement.setText(f"Raw {m['raw']} / Native {m['legacy_position']:.4f} / 이전 {m.get('before_model_rad')} rad / 새 보정 {m.get('after_model_rad')} rad / Torque {m['torque']}")
        if progress.get('precision_result'):
            p=progress['precision_result'];result=p['result'];kind=p['kind'];rows=p['references']
            if p['joint']==self.joint.currentText():
                candidate=p['candidate'];self.fit_result.setText((candidate['status']+' · '+str(candidate.get('validation',candidate.get('review',{})))if candidate else'선택 관절의 Fit/Review 결과 없음')+' · physical_verified=false')
                self.references.setRowCount(len(rows))
                for i,r in enumerate(rows):
                    before=r.get('before_model_rad');after=None
                    if candidate and i<len(candidate.get('errors_rad',[])):after=r['angle_rad']+candidate['errors_rad'][i]
                    values=(r['reference_id'],r['raw'],math.degrees(r['angle_rad']),r['split'],math.degrees(before-r['angle_rad'])if before is not None else'미결합',math.degrees(after-r['angle_rad'])if after is not None else'—')
                    for col,value in enumerate(values):self.references.setItem(i,col,QTableWidgetItem(str(value)))
            if kind=='precision_save':self.saved_profile=result['path'];self.fit_result.setText('저장됨 · '+result['path'])
            if kind=='precision_activate':self.activated.emit(result);self.fit_result.setText('새 장치 구성 적용 · '+result['configuration_path'])
        self.buttons()
    def buttons(self):
        active=self.active();ready=self.client.running and not self.client.cancel_requested
        for widget in(self.configuration,self.role,self.model,self.model_button,self.refresh_button,self.connect_button):widget.setEnabled(not active)
        for widget in(self.joint,self.angle,self.split,self.record,self.remove,self.fit,self.review,self.validate,self.save_button,self.tolerance):widget.setEnabled(ready)
        self.apply_button.setEnabled(ready and self.saved_profile is not None);self.disconnect.setEnabled(active)
    def received(self,event):
        if event['kind']=='command_ack'and event['payload'].get('status')=='rejected':self.error(event['payload'].get('reason','명령 거부'))
    def error(self,message):self.log.appendPlainText(message);self.state.setText(message)
    def cancel_run(self):self.client.cancel();self.buttons()
    def ended(self,status):self.state.setText('DISCONNECTED · '+status);self.buttons()
