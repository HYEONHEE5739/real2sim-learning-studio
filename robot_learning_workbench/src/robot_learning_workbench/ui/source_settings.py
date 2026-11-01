"""Scene-name selection and one saved YAML buffer for Live Source collection."""
from pathlib import Path
import json,uuid,yaml
from PyQt6.QtCore import Qt,pyqtSignal
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QLineEdit,QFileDialog
from .recipe_editor import RecipeEditor
from .jobs import BackendJob


class SourceSettings(QWidget):
    apply_requested=pyqtSignal(object)
    changed=pyqtSignal()
    error=pyqtSignal(str)

    def __init__(self,python,workspace,engine,parent=None):
        super().__init__(parent);self.workspace=Path(workspace);self.engine=engine;self.syncing=False
        self.directory=self.workspace/'scripts/source';self.directory.mkdir(parents=True,exist_ok=True)
        box=QVBoxLayout(self);box.addWidget(QLabel('실행 설정'))
        row=QHBoxLayout();box.addLayout(row);row.addWidget(QLabel('Scene'));self.scene=QComboBox();row.addWidget(self.scene,1)
        self.open_scene=QPushButton('폴더 선택');row.addWidget(self.open_scene)
        self.load_button=QPushButton('Recipe 불러오기');box.addWidget(self.load_button)
        self.script_path=QLineEdit();self.script_path.setReadOnly(True);self.script_path.setPlaceholderText('아직 저장하지 않은 Source Script');box.addWidget(self.script_path)
        self.editor=RecipeEditor(self);self.editor.label.hide();self.editor.text.setMinimumHeight(380)
        self.editor.text.setStyleSheet('QPlainTextEdit { background: #f4f5f8; color: #172030; selection-background-color: #a9cced; font-family: monospace; padding: 8px; }')
        box.addWidget(self.editor,1);self.save_button=QPushButton('저장 및 적용');self.save_button.setObjectName('primaryAction');box.addWidget(self.save_button)
        hint=QLabel('Episode 수·환경 수·시간·Resume·데이터 저장 위치는 YAML에서 수정하세요. Script 저장 위치: scripts/source');hint.setWordWrap(True);box.addWidget(hint)
        self.scene.addItem('Scene 선택',None);self.scene.currentIndexChanged.connect(self.select_scene)
        self.open_scene.clicked.connect(self.choose_scene);self.load_button.clicked.connect(self.choose_script);self.save_button.clicked.connect(self.save_and_apply)
        self.editor.changed.connect(self.changed);self.engine.currentTextChanged.connect(self.select_engine)
        self.editor.text.setPlainText(self.default_script())
        self.catalog=BackendJob(python,self);self.catalog.finished.connect(self.scenes_loaded)
        self.catalog.start('source_scenes',workspace=str(self.workspace))

    def showEvent(self,event):
        super().showEvent(event)
        from PyQt6.QtCore import QProcess
        if hasattr(self,'catalog')and self.editor.isEnabled()and self.catalog.process.state()==QProcess.ProcessState.NotRunning:self.catalog.start('source_scenes',workspace=str(self.workspace))

    def default_script(self):
        text=yaml.safe_dump({'schema_version':1,'stage':'source','engine':self.engine.currentText(),'inputs':{'scene':''},
            'execution':{'seed':1047,'env_num':1,'num_episodes':10,'episode_time_s':60.0,'reset_time_s':0.0,'resume':False},
            'output':{'directory':str(self.workspace/'source'/('demo-'+uuid.uuid4().hex[:8]))},'objects':{},'functions':{}},sort_keys=False,allow_unicode=True)
        return text.replace('env_num: 1','env_num: 1  # Live Leader Source는 현재 1-env').replace('num_episodes: 10','num_episodes: 10  # 이번에 추가로 저장할 Episode 수').replace('episode_time_s: 60.0','episode_time_s: 60.0  # Episode 최대 시간 (초)').replace('reset_time_s: 0.0','reset_time_s: 0.0  # 저장·폐기 후 대기 (초)').replace('resume: false','resume: false  # 같은 output.directory에 이어 수집하려면 true')

    def set_busy(self,busy):
        for widget in(self.scene,self.open_scene,self.load_button,self.save_button,self.editor,self.engine):widget.setEnabled(not busy)

    def scenes_loaded(self,response):
        if not response.get('ok'):self.error.emit(response.get('error',{}).get('message','Scene 목록을 읽지 못했습니다.'));return
        selected=self.scene.currentData();rows=response['result']['scenes'];self.scene.blockSignals(True);self.scene.clear();self.scene.addItem('Scene 선택',None)
        for row in rows:self.scene.addItem(row['name'],row['project']);self.scene.setItemData(self.scene.count()-1,row['project'],Qt.ItemDataRole.ToolTipRole)
        index=self.scene.findData(selected)
        if selected and index<0:self.scene.addItem(Path(selected).name,selected);index=self.scene.count()-1
        self.scene.setCurrentIndex(max(index,0));self.scene.blockSignals(False)

    def choose_scene(self):
        path=QFileDialog.getExistingDirectory(self,'Scene 최상위 폴더 선택',str(self.workspace/'scenes'))
        if not path:return
        if not(Path(path)/'project.yaml').is_file():self.error.emit('project.yaml이 있는 Scene 최상위 폴더를 선택하세요.');return
        index=self.scene.findData(path)
        if index<0:self.scene.addItem(Path(path).name,path);index=self.scene.count()-1
        self.scene.setCurrentIndex(index)

    def select_scene(self,*_):
        if self.syncing:return
        path=self.scene.currentData()
        self.update_choice('scene',path or'')

    def select_engine(self,*_):
        if not self.syncing:self.update_choice('engine',self.engine.currentText())

    def update_choice(self,key,value):
        try:
            text=self.editor.text.toPlainText();data=self.editor.data();root=yaml.compose(text)
            nodes={node.value:value for node,value in root.value}
            if key=='scene':nodes={node.value:value for node,value in nodes['inputs'].value}
            selected=nodes.get(key)
            if selected is None:
                if key=='scene':data['inputs']['scene']=value
                else:data[key]=value
                self.editor.text.setPlainText(yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
            else:self.editor.text.setPlainText(text[:selected.start_mark.index]+json.dumps(value,ensure_ascii=False)+text[selected.end_mark.index:])
        except Exception as error:self.changed.emit();self.error.emit('YAML 편집 내용을 먼저 수정하세요: '+str(error))

    def sync_script(self,data):
        self.syncing=True
        try:
            self.engine.setCurrentText(data.get('engine','mujoco'));value=data.get('inputs',{}).get('scene')
            path=str((self.editor.path.parent/str(value)).resolve())if value and self.editor.path else value
            index=self.scene.findData(path)
            if path and index<0:
                project=Path(path);metadata=project/'project.yaml'
                name=yaml.safe_load(metadata.read_text()).get('name',project.name)if metadata.is_file()else project.name
                self.scene.addItem(name,path);index=self.scene.count()-1
            self.scene.setCurrentIndex(max(index,0))
        finally:self.syncing=False
        self.script_path.setText(self.editor.path.name if self.editor.path else'');self.script_path.setToolTip(str(self.editor.path or''))

    def choose_script(self):
        path,_=QFileDialog.getOpenFileName(self,'저장된 Source Script',str(self.directory),'YAML Script (*.yaml *.yml)')
        if path:
            try:self.load_script(path)
            except Exception as error:self.changed.emit();self.error.emit(str(error))

    def load_script(self,path):
        data=yaml.safe_load(Path(path).read_text())
        if not isinstance(data,dict)or data.get('stage')!='source':raise ValueError('Source YAML Script를 선택하세요.')
        if 'source_dataset'in data.get('inputs',{}):raise ValueError('Source Demo는 Leader 수집 전용입니다. 저장 자료는 Data Curation에서 재생하세요.')
        self.editor.load(path);self.sync_script(data);self.apply_requested.emit(self.editor.path)

    def save_and_apply(self):
        try:
            data=self.editor.data()
            if data.get('stage')!='source':raise ValueError('stage: source를 유지하세요.')
            if 'source_dataset'in data.get('inputs',{}):raise ValueError('저장 Target Stream 대신 Scene을 선택하세요. 재생은 Data Curation을 사용하세요.')
            initial=self.editor.path or self.directory/'source.yaml'
            path,_=QFileDialog.getSaveFileName(self,'Source Script 저장 및 적용',str(initial),'YAML Script (*.yaml *.yml)')
            if not path:return
            target=Path(path)
            if not target.suffix:target=target.with_suffix('.yaml')
            if target.suffix.lower()not in('.yaml','.yml'):raise ValueError('Source Script는 .yaml 또는 .yml로 저장하세요.')
            if any(target.resolve().is_relative_to(self.workspace/name)for name in('scenes','devices','runtime','.assets')):raise ValueError('Scene·장치·Runtime 자료 대신 scripts/source 폴더에 저장하세요.')
            self.editor.save(target);self.sync_script(data);self.apply_requested.emit(self.editor.path)
        except Exception as error:self.changed.emit();self.error.emit(str(error))
