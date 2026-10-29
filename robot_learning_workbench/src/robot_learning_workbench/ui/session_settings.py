"""Device/Profile settings edit existing schemas through one buffer per document."""
import json,uuid
from pathlib import Path
import yaml
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QWidget,QFormLayout,QLineEdit,QPushButton,QFileDialog,QLabel,QComboBox,QDoubleSpinBox
from .recipe_editor import RecipeEditor


class DeviceSettings(QDialog):
    def __init__(self,workspace,parent=None):
        super().__init__(parent);self.workspace=Path(workspace);self.documents={};self.ports={};self.inputs={};self.dirty=False;self.validated=False;self.saved_recipe=None
        self.setWindowTitle('장치 설정 · 기존 Profile / Camera / Recipe');self.resize(850,730)
        layout=QVBoxLayout(self);self.name=QLineEdit('SO-101 configuration');layout.addWidget(self.name)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1);self.tabs.currentChanged.connect(self.refresh_forms)
        general=QWidget();form=QFormLayout(general);self.tabs.addTab(general,'연결 및 보정')
        self.source=QComboBox();self.source.addItems(['hardware','memory']);form.addRow('장치 종류 · memory는 합성 시험',self.source)
        self.step=QDoubleSpinBox();self.step.setDecimals(3);self.step.setRange(.001,1);self.step.setValue(.05);form.addRow('최대 명령 변화 rad/주기',self.step)
        self.follow=QDoubleSpinBox();self.follow.setDecimals(3);self.follow.setRange(.001,2);self.follow.setValue(.2);form.addRow('최대 추종 오차 rad',self.follow)
        keys={'device_profile':'Follower 장치 Profile','leader_device_profile':'Leader 장치 Profile','calibration_profile':'Follower Precision Profile','leader_calibration_profile':'Leader Precision Profile','camera_config':'Side/Wrist Camera JSON','robot_model':'측정 Robot URDF','source_robot_model':'Profile 원본 URDF (한계 변경 검증 시)'}
        for key,label in keys.items():
            line=QLineEdit();self.inputs[key]=line;row=QHBoxLayout();row.addWidget(line,1);button=QPushButton('불러오기');row.addWidget(button);button.clicked.connect(lambda _,k=key:self.choose(k));form.addRow(label,row);line.textEdited.connect(self.edited)
        for key,label in(('device_profile','Follower 포트'),('leader_device_profile','Leader 포트')):
            port=QLineEdit();self.ports[key]=port;form.addRow(label,port);port.editingFinished.connect(lambda k=key:self.port_changed(k))
        self.message=QLabel('원본은 읽기 전용으로 불러오고 새 설정으로 저장합니다. 연결 중에는 편집할 수 없습니다.');self.message.setWordWrap(True);layout.addWidget(self.message)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        load=QPushButton('저장 구성 불러오기');load.clicked.connect(self.choose_recipe);buttons.addWidget(load)
        save=QPushButton('다른 이름으로 저장');save.clicked.connect(self.choose_save);buttons.addWidget(save)
        close=QPushButton('닫기');close.clicked.connect(self.accept);buttons.addWidget(close)
        for role,key in (('follower','device_profile'),('leader','leader_device_profile')):
            self.set_document(key,{'role':role,'calibration_path':'','sdk':{'port':'','id':'','use_degrees':True}})
        self.set_document('camera_config',{'cameras':{n:{'index_or_path':'','width':640,'height':480,'fps':30}for n in ('side','wrist')}})
        self.source.currentTextChanged.connect(self.edited);self.step.valueChanged.connect(self.edited);self.follow.valueChanged.connect(self.edited)
    def edited(self,*_):self.dirty=True;self.validated=False
    def set_document(self,key,data):
        if key not in self.documents:
            editor=RecipeEditor(self);self.documents[key]=editor;self.tabs.addTab(editor,{'device_profile':'Follower JSON','leader_device_profile':'Leader JSON','camera_config':'Camera YAML'}.get(key,key));editor.changed.connect(self.edited)
        self.documents[key].text.setPlainText(json.dumps(data,ensure_ascii=False,indent=2));self.sync_forms(key)
    def sync_forms(self,key):
        data=self.documents[key].data()
        if key in self.ports:self.ports[key].setText(data.get('sdk',{}).get('port',''))
    def refresh_forms(self,*_):
        for key in self.documents:
            try:self.sync_forms(key)
            except Exception as error:self.message.setText(str(error))
    def port_changed(self,key):
        if key not in self.documents:self.message.setText('먼저 장치 Profile을 불러오거나 JSON으로 작성하세요');return
        self.documents[key].update(lambda data:data.setdefault('sdk',{}).update(port=self.ports[key].text()))
    def choose(self,key):
        path,_=QFileDialog.getOpenFileName(self,'기존 '+key,str(self.workspace))
        if path:
            try:self.load_input(key,path)
            except Exception as error:self.message.setText(str(error))
    def load_input(self,key,path):
        path=Path(path).resolve();self.inputs[key].setText(str(path))
        if key in('device_profile','leader_device_profile','camera_config'):
            self.set_document(key,yaml.safe_load(path.read_text()));self.documents[key].path=path
        self.edited()
    def choose_recipe(self):
        path,_=QFileDialog.getOpenFileName(self,'저장 Session 구성',str(self.workspace),'YAML (*.yaml *.yml)')
        if path:
            try:self.load_recipe(path)
            except Exception as error:self.message.setText(str(error))
    def load_recipe(self,path):
        path=Path(path).resolve();data=yaml.safe_load(path.read_text())
        if data.get('stage')not in('capture_session','paired_session'):raise ValueError('지속 연결 Session Recipe를 선택하세요')
        for key in self.inputs:
            if not data.get('inputs',{}).get(key):self.inputs[key].clear()
            if data.get('inputs',{}).get(key):self.load_input(key,(path.parent/data['inputs'][key]).resolve())
        opts=data['execution'];self.source.setCurrentText(opts['device_source']);self.step.setValue(opts['max_command_step_rad']);self.follow.setValue(opts['max_follow_error_rad']);self.name.setText(path.stem);self.saved_recipe=path;self.dirty=False
        for editor in self.documents.values():editor.dirty=False
    def choose_save(self):
        path,_=QFileDialog.getSaveFileName(self,'새 장치 구성 저장',str(self.workspace/'configuration'/(self.name.text()+'.yaml')),'YAML (*.yaml)')
        if path:
            try:self.save(path);self.message.setText('저장됨 · 연결 시 Profile/장치 identity를 다시 검사합니다')
            except Exception as error:self.message.setText(str(error))
    def save(self,path):
        path=Path(path).resolve();folder=path.parent/(path.stem+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True,exist_ok=False)
        values={k:line.text().strip()for k,line in self.inputs.items()if line.text().strip()}
        for key,document in self.documents.items():
            data=document.data();document.text.setPlainText(json.dumps(data,ensure_ascii=False,indent=2));target=folder/(key+'.json');document.save(target);values[key]=str(target);self.inputs[key].setText(str(target))
        self.saved_recipe=path;data={'schema_version':1,'stage':'capture_session','inputs':values,'execution':{'device_source':self.source.currentText(),'max_command_step_rad':self.step.value(),'max_follow_error_rad':self.follow.value()},'output':{'directory':str(self.workspace/'capture'/'new-session')}}
        editor=RecipeEditor();editor.text.setPlainText(yaml.safe_dump(data,sort_keys=False,allow_unicode=True));editor.save(path);editor.deleteLater();self.dirty=False;self.validated=False;return path
    def recipe(self):
        if self.saved_recipe is None or self.dirty or any(d.dirty for d in self.documents.values()):raise ValueError('장치 설정을 명시 저장한 뒤 연결하세요')
        return yaml.safe_load(self.saved_recipe.read_text())
