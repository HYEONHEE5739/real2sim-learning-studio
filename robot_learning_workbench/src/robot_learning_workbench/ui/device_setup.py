"""Basic device choices and an explicit advanced Recipe editor; no SDK in Qt."""
import json,uuid
from pathlib import Path
import yaml
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QLabel,QComboBox,QFileDialog,QMessageBox,QInputDialog
from .recipe_editor import RecipeEditor
from .jobs import BackendJob
from .session_client import SessionClient


class DeviceSetup(QDialog):
    def __init__(self,workspace,python,modules,parent=None):
        super().__init__(parent);self.workspace=Path(workspace);self.saved_recipe=None;self.dirty=False;self.operation=None;self.inventory={}
        self.setWindowTitle('장치 설정');self.resize(700,620);box=QVBoxLayout(self)
        self.configuration=QComboBox();box.addWidget(self.configuration);self.configuration.currentIndexChanged.connect(self.select_saved)
        self.name=QLineEdit('SO-101 devices');box.addWidget(self.name);form=QFormLayout();box.addLayout(form)
        self.robot=QComboBox();self.robot.addItem('SO-101 Leader / Follower','so101');self.robot.addItem('카메라만 사용','cameras');form.addRow('Robot',self.robot)
        for key,label in(('leader','Leader'),('follower','Follower'),('side','Side Camera'),('wrist','Wrist Camera')):
            combo=QComboBox();setattr(self,key,combo);form.addRow(label,combo);combo.currentIndexChanged.connect(self.changed)
        self.robot.currentIndexChanged.connect(self.changed)
        self.status=QLabel('장치 검색은 포트를 열거나 모터를 활성화하지 않습니다.');self.status.setWordWrap(True);box.addWidget(self.status)
        row=QHBoxLayout();box.addLayout(row)
        for label,fn in(('장치 검색',self.search),('선택 구성 저장',self.save_selected),('SDK Calibration',self.calibration)):
            button=QPushButton(label);button.clicked.connect(fn);row.addWidget(button)
        advanced=QPushButton('고급 설정 · JSON/YAML');advanced.setCheckable(True);box.addWidget(advanced)
        self.advanced=RecipeEditor(self);box.addWidget(self.advanced,1);self.advanced.hide();advanced.toggled.connect(self.advanced.setVisible);self.advanced.changed.connect(self.changed)
        advrow=QHBoxLayout();box.addLayout(advrow)
        for label,fn in(('구성 불러오기',self.load_file),('고급 구성 새 파일 저장',self.save_advanced),('닫기',self.accept)):
            button=QPushButton(label);button.clicked.connect(fn);advrow.addWidget(button)
        self.job=BackendJob(python,self);self.job.finished.connect(self.result);self.job.log.connect(self.status.setText)
        self.calibration_client=SessionClient(python,modules,self);self.calibration_client.progress.connect(self.calibration_progress);self.calibration_client.error.connect(self.status.setText);self.calibration_client.terminal.connect(lambda state:self.status.setText('Calibration Worker '+state+' · 연결 전에 파일/장치 identity를 다시 검사합니다'))
        self.refresh_configurations()
    def changed(self,*_):self.dirty=True
    def refresh_configurations(self):
        selected=str(self.saved_recipe)if self.saved_recipe else None;self.configuration.blockSignals(True);self.configuration.clear();self.configuration.addItem('저장 구성 선택',None)
        for p in sorted((self.workspace/'devices').glob('*/capture.yaml')):self.configuration.addItem(p.parent.name,str(p))
        if selected:
            if self.configuration.findData(selected)<0:self.configuration.addItem(Path(selected).stem,selected)
            self.configuration.setCurrentIndex(self.configuration.findData(selected))
        self.configuration.blockSignals(False)
    def request(self,operation,**arguments):
        from PyQt6.QtCore import QProcess
        if self.job.process.state()!=QProcess.ProcessState.NotRunning:self.status.setText('현재 장치 설정 작업이 끝날 때까지 기다리세요');return
        try:self.operation=operation;self.job.start(operation,**arguments)
        except Exception as error:self.status.setText(str(error))
    def search(self):self.request('session_devices')
    def discovered(self,result):
        self.inventory=result
        for key in('leader','follower','side','wrist'):
            combo=getattr(self,key);current=combo.currentData();combo.blockSignals(True);combo.clear();combo.addItem('선택하세요',None)
            for row in result['serial'if key in('leader','follower')else'cameras']:
                combo.addItem(row['path']+(' · USB '+str(row.get('serial'))if key in('leader','follower')else''),row if key in('leader','follower')else row['path'])
            if current is not None:
                index=combo.findData(current)
                if index<0:combo.addItem(str(current),current);index=combo.count()-1
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
    def save_selected(self):
        self.request('session_device_configure',workspace=str(self.workspace),name=self.name.text(),existing=str(self.saved_recipe)if self.saved_recipe else None,choices={k:getattr(self,k).currentData()for k in('robot','leader','follower','side','wrist')})
    def result(self,response):
        if not response.get('ok'):self.status.setText(response.get('error',{}).get('message','장치 설정 오류'));return
        result=response['result']
        if self.operation=='session_devices':self.discovered(result)
        elif 'path'in result:
            try:self.load_recipe(result['path']);self.status.setText('저장됨 · 자동 연결/모터 활성화 없음')
            except Exception as error:self.status.setText(str(error))
    def select_saved(self):
        if self.configuration.currentData():
            try:self.load_recipe(self.configuration.currentData())
            except Exception as error:self.saved_recipe=None;self.status.setText(str(error))
    def load_file(self):
        file,_=QFileDialog.getOpenFileName(self,'장치 구성 불러오기',str(self.workspace),'YAML (*.yaml *.yml)')
        if file:
            try:self.load_recipe(file)
            except Exception as error:self.status.setText(str(error))
    def load_recipe(self,path):
        path=Path(path).resolve();data=yaml.safe_load(path.read_text())
        if data.get('stage')not in('scene_capture','capture_session','paired_session'):raise ValueError('Scene 관측 또는 지속 Session 구성을 선택하세요')
        for k,v in data['inputs'].items():data['inputs'][k]=str((path.parent/v).resolve())
        self.advanced.text.setPlainText(yaml.safe_dump(data,sort_keys=False,allow_unicode=True));self.saved_recipe=path
        for key,spec_key in(('leader','leader_device_profile'),('follower','device_profile')):
            combo=getattr(self,key);combo.blockSignals(True);combo.clear()
            if spec_key in data['inputs']:
                spec=yaml.safe_load(Path(data['inputs'][spec_key]).read_text());item={**spec.get('usb_identity',{}),'path':spec['sdk']['port']};combo.addItem(str(item.get('serial')or item['path'])+' · 저장 identity',item)
            else:combo.addItem('사용하지 않음',None)
            combo.blockSignals(False)
        self.robot.setCurrentIndex(0 if 'device_profile'in data['inputs']else 1)
        cameras=yaml.safe_load(Path(data['inputs']['camera_config']).read_text())['cameras']
        for name in('side','wrist'):
            combo=getattr(self,name);combo.blockSignals(True);combo.clear();p=cameras[name]['index_or_path'];combo.addItem(str(p),p);combo.blockSignals(False)
        self.status.setText('저장 구성 복원 · '+('Precision/model rad 측정 가능 · 명령은 별도 현장 승인 필요'if data['stage']!='scene_capture'else'SDK native / Camera 관측 · model rad 및 제어 권한 없음'))
        self.dirty=False;self.advanced.dirty=False;self.refresh_configurations()
    def save_advanced(self):
        try:self.request('session_device_save',workspace=str(self.workspace),name=self.name.text(),recipe=self.advanced.data())
        except Exception as error:self.status.setText(str(error))
    def recipe(self):
        if not self.saved_recipe or self.dirty:raise ValueError('장치 구성을 저장한 후 연결하세요')
        return self.advanced.data()
    def calibration(self):
        try:
            data=self.recipe();role,ok=QInputDialog.getItem(self,'공식 SDK Calibration','개체 선택',['follower','leader'],0,False)
            if not ok:return
            answer=QMessageBox.warning(self,'현장 감독 SDK Calibration','공식 절차는 Torque를 끄고 Homing/Range 레지스터를 기록합니다. 팔을 지지하고 충돌 위험을 제거하세요. 직접 감독하며 수동 자세 이동과 각 SDK 지시에 응답할 준비가 됐습니까? 기존 Calibration은 덮어쓰지 않습니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
            if answer!=QMessageBox.StandardButton.Yes:return
            key='device_profile'if role=='follower'else'leader_device_profile';file=self.workspace/'devices'/('calibration_'+uuid.uuid4().hex+'.yaml');output=self.workspace/'calibration'/uuid.uuid4().hex
            file.parent.mkdir(parents=True,exist_ok=True);file.write_text(yaml.safe_dump({'schema_version':1,'stage':'sdk_calibration','inputs':{'device_profile':data['inputs'][key]},'execution':{'confirm_on_site':True,'timeout_s':600},'output':{'directory':str(output)}}));self.calibration_client.connect_session(file)
        except Exception as error:self.status.setText(str(error))
    def calibration_progress(self,progress):
        prompt=progress.get('calibration_prompt')
        if prompt:
            response,ok=QInputDialog.getText(self,'공식 SDK · '+prompt['role'],prompt['text'])
            self.calibration_client.send('calibration_response',{'prompt_id':prompt['id'],'response':response})if ok else self.calibration_client.cancel()
    def accept(self):
        if self.calibration_client.active():self.calibration_client.cancel();self.status.setText('Calibration Worker 종료를 기다립니다');return
        super().accept()
    def reject(self):
        if self.calibration_client.active():self.calibration_client.cancel();self.status.setText('Calibration Worker 종료를 기다립니다');return
        super().reject()
    def closeEvent(self,event):
        if self.calibration_client.active():self.calibration_client.cancel();event.ignore();self.status.setText('Calibration Worker 종료를 기다립니다');return
        super().closeEvent(event)
