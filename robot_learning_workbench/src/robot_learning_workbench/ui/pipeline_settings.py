"""One saved YAML buffer and compact input selectors for pipeline stages."""
from pathlib import Path
import yaml
from PyQt6.QtCore import Qt,pyqtSignal,QProcess
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QLineEdit,QFileDialog,QComboBox,QDialog
from .recipe_editor import RecipeEditor
from .pipeline_scripts import default_script,rebase_paths
from .jobs import BackendJob


SELECTORS={
    'annotation':('dataset',),'datagen':('dataset',),
    'train':('dataset','training_config','policy','checkpoint'),
    'simulation_evaluation':('policy',),'offline_validation':('dataset','policy'),
    'hub_download':(),'hub_upload':('artifact',),
    'real_evaluation':('policy','device_profile','calibration_profile','camera_config'),
}
LABELS={'dataset':'입력 Dataset','training_config':'공식 Training JSON','policy':'Policy / Checkpoint',
        'checkpoint':'Resume Checkpoint · 선택','artifact':'업로드할 Dataset / Policy',
        'device_profile':'Follower 장치 Profile','calibration_profile':'Precision Profile','camera_config':'Camera 설정'}


class PipelineSettings(QWidget):
    changed=pyqtSignal()
    apply_requested=pyqtSignal(object)
    error=pyqtSignal(str)

    def __init__(self,stage,python,workspace,engine,parent=None):
        super().__init__(parent);self.stage=stage;self.python=python;self.workspace=Path(workspace).resolve();self.engine=engine
        self.directory=self.workspace/'scripts'/stage;self.version=0;self.syncing=False;self.invalid_selection=False;self.query_version=None;self.query_operation=None
        box=QVBoxLayout(self);box.setContentsMargins(12,12,12,12);box.addWidget(QLabel('실행 설정'))
        self.scene=None;self.scene_rows=[]
        if stage in ('annotation','datagen','simulation_evaluation'):
            row=QHBoxLayout();box.addLayout(row);row.addWidget(QLabel('Scene'));self.scene=QComboBox();self.scene.addItem('Scene 선택',None);row.addWidget(self.scene,1)
            browse=QPushButton('폴더 선택');row.addWidget(browse);browse.clicked.connect(self.choose_scene);self.scene.currentIndexChanged.connect(self.select_scene)
        self.selectors={}
        inputs=QGridLayout();box.addLayout(inputs)
        for index,key in enumerate(SELECTORS[stage]):
            button=QPushButton(LABELS[key]);button.clicked.connect(lambda _,k=key:self.choose_input(k));inputs.addWidget(button,index//2,index%2);self.selectors[key]=button
        self.load_button=QPushButton('Recipe 불러오기');box.addWidget(self.load_button);self.load_button.clicked.connect(self.choose_script)
        self.script_path=QLineEdit();self.script_path.setReadOnly(True);self.script_path.setPlaceholderText('아직 저장하지 않은 Script');box.addWidget(self.script_path)
        self.editor=RecipeEditor();self.editor.label.hide();self.editor.text.setMinimumHeight(240)
        self.editor.text.setStyleSheet('QPlainTextEdit { background: #f4f5f8; color: #172030; selection-background-color: #a9cced; font-family: monospace; padding: 8px; }')
        self.editor.text.setPlainText(default_script(stage,self.workspace,engine.currentText()));box.addWidget(self.editor,1)
        self.save_button=QPushButton('저장 및 적용');self.save_button.setObjectName('primaryAction');box.addWidget(self.save_button);self.save_button.clicked.connect(self.save_and_apply)
        hint=QLabel('실행 값·출력 위치는 YAML에서 수정합니다. Script 저장 위치: scripts/'+stage);hint.setWordWrap(True);box.addWidget(hint)
        self.editor.changed.connect(self.edited);self.engine.currentTextChanged.connect(self.engine_changed)
        self.query=BackendJob(python,self);self.query.finished.connect(self.received)
        self.task_query=BackendJob(python,self);self.task_query.finished.connect(self.task_received)
        self.task_version=None;self.task_pending=False;self.task_modules=getattr(parent,'modules',None)

    def edited(self):
        self.version+=1;self.refresh_labels();self.changed.emit()

    def update(self,fn):
        self.editor.update(fn)

    def set_inputs(self,values):
        def edit(data):data.setdefault('inputs',{}).update(values)
        self.update(edit)

    def base(self):return self.editor.path.parent if self.editor.path else self.directory

    def refresh_labels(self):
        try:
            data=self.editor.data()
        except (ValueError,yaml.YAMLError):data={}
        inputs=data.get('inputs',{});inputs=inputs if isinstance(inputs,dict)else{}
        for key,button in self.selectors.items():
            value=inputs.get(key,'');value=value if isinstance(value,str)else''
            button.setText(LABELS[key]+(' · '+Path(value).name if value else''));button.setToolTip(value)
        if self.scene is None:return
        engine=data.get('engine');index=self.engine.findText(engine)if isinstance(engine,str)else-1
        blocked=self.engine.blockSignals(True)
        try:self.engine.setCurrentIndex(index)
        finally:self.engine.blockSignals(blocked)
        value=inputs.get('scene');path=str((self.base()/value).resolve())if isinstance(value,str)and value else None
        index=next((i+1 for i,row in enumerate(self.scene_rows)if row['scene']==path),0)
        blocked=self.scene.blockSignals(True)
        try:
            name=Path(path).parent.name if path and Path(path).name=='scene.json'else Path(path).name if path else''
            self.scene.setItemText(0,'외부 Scene · '+name if path and not index else'Scene 선택')
            self.scene.setItemData(0,path if not index else None,Qt.ItemDataRole.ToolTipRole)
            self.scene.setCurrentIndex(index)
        finally:self.scene.blockSignals(blocked)

    def set_busy(self,busy):
        self.setEnabled(not busy);self.engine.setEnabled(not busy)

    def showEvent(self,event):
        super().showEvent(event)
        if self.scene is not None and self.isEnabled()and self.query.process.state()==QProcess.ProcessState.NotRunning:
            self.query_operation='scenes';self.query_version=self.version;self.query.start('pipeline_scenes',workspace=str(self.workspace))

    def engine_changed(self,*_):
        if self.syncing or self.stage not in ('annotation','datagen','simulation_evaluation'):return
        try:
            self.update(lambda data:data.__setitem__('engine',self.engine.currentText()))
            if self.scene is not None and self.scene.currentData():self.select_scene()
        except Exception as error:self.error.emit('YAML을 먼저 수정하세요: '+str(error))

    def select_scene(self,*_):
        if self.syncing or not self.scene.currentData():return
        row=self.scene.currentData();key={'isaaclab':'isaac','mujoco':'mujoco'}.get(self.engine.currentText())
        if key is None:self.refresh_labels();self.error.emit('YAML의 engine을 mujoco 또는 isaaclab으로 지정하세요.');return
        if key not in row.get('engines',[]):self.error.emit('이 Scene은 선택 엔진을 지원하지 않습니다.');return
        values={'scene':row['scene']}
        config=row.get('engine_config',{}).get(key)
        if config:values['engine_config']=config
        try:self.set_inputs(values);self.request_task()
        except Exception as error:self.error.emit('YAML을 먼저 수정하세요: '+str(error))

    def choose_scene(self):
        key={'isaaclab':'isaac','mujoco':'mujoco'}.get(self.engine.currentText())
        if key is None:self.error.emit('YAML의 engine을 mujoco 또는 isaaclab으로 지정하세요.');return
        folder=QFileDialog.getExistingDirectory(self,'Scene Project 또는 Export 폴더',str(self.workspace/'scenes'))
        if not folder:return
        root=Path(folder);matches=[r for r in self.scene_rows if Path(r['project'])==root or Path(r['scene']).parent==root]
        matches=[r for r in matches if key in r['engines']]
        if matches:
            index=self.scene.findData(matches[-1]);self.scene.setCurrentIndex(index);self.select_scene();return
        if (root/'scene.json').is_file():
            try:self.set_inputs({'scene':str(root/'scene.json')});self.request_task()
            except Exception as error:self.error.emit('YAML을 먼저 수정하세요: '+str(error))
            return
        self.error.emit('등록된 실행 Scene 또는 scene.json이 있는 Export 폴더를 선택하세요.')

    def choose_input(self,key):
        from .paths import input_directory
        if self.query.process.state()!=QProcess.ProcessState.NotRunning:self.error.emit('입력 목록을 읽은 뒤 다시 선택하세요.');return
        if key=='dataset'and self.stage in ('annotation','datagen'):
            from .dataset_input import DatasetInputDialog
            dialog=DatasetInputDialog(self.python,self.workspace,self.stage,self)
            value=dialog.path if dialog.exec()==QDialog.DialogCode.Accepted else''
        elif key in ('dataset','policy','checkpoint','artifact'):
            value=QFileDialog.getExistingDirectory(self,LABELS[key],str(input_directory(self.workspace,self.stage,key)))
        else:value,_=QFileDialog.getOpenFileName(self,LABELS[key],str(self.workspace),'JSON / YAML (*.json *.yaml *.yml)')
        if not value:return
        try:
            if key=='dataset'and self.stage in ('annotation','datagen'):
                def edit(data):
                    data.setdefault('inputs',{}).update(dataset=value,scene='');data['inputs'].pop('engine_config',None)
                self.update(edit)
            else:self.set_inputs({key:value})
        except Exception as error:self.error.emit('YAML을 먼저 수정하세요: '+str(error));return
        if key=='dataset'and self.stage in ('annotation','datagen'):
            self.query_version=self.version;self.query_operation='dataset';self.query.start('pipeline_dataset',workspace=str(self.workspace),path=value,stage=self.stage)

    def received(self,response):
        if not response.get('ok'):self.error.emit(response.get('error',{}).get('message','입력 조회 실패'));return
        data=response['result']
        if self.query_operation=='scenes':
            self.scene_rows=data['scenes'];self.scene.blockSignals(True);self.scene.clear();self.scene.addItem('Scene 선택',None)
            for row in self.scene_rows:self.scene.addItem(row['name']+' · '+row['revision'],row)
            self.scene.blockSignals(False);self.refresh_labels();return
        if self.query_version!=self.version:return
        self.update(lambda doc:(doc.__setitem__('engine',data['engine']),doc.setdefault('inputs',{}).update(data['inputs'])))
        self.request_task()

    def request_task(self):
        if self.stage not in ('annotation','datagen','simulation_evaluation'):return
        if not self.task_modules:return
        if self.task_query.process.state()!=QProcess.ProcessState.NotRunning:
            self.task_pending=True;return
        try:data=self.editor.data();path=data.get('inputs',{}).get('scene')
        except (ValueError,yaml.YAMLError):return
        if not path:return
        self.task_pending=False;self.task_version=self.version
        self.task_query.start('pipeline_task',path=str((self.base()/path).resolve()),
            modules=self.task_modules,stage=self.stage,engine=data['engine'])

    def task_received(self,response):
        if self.task_pending:
            self.task_pending=False;self.request_task();return
        if self.task_version!=self.version:return
        if not response.get('ok'):
            self.error.emit(response.get('error',{}).get('message','Scene 작업 설정 조회 실패'));return
        result=response['result']
        if result['status']=='NO_TASK':return
        if result['status']!='CONFIGURED':
            self.error.emit('Scene 작업에 추가 구현이 필요합니다: '+'; '.join(result['needs']));return
        data=self.editor.data();role='success' if self.stage=='simulation_evaluation' else 'acceptance'
        current=data.get('functions',{});params=current.get(role,{}).get('params',{})
        default_name={'annotation':'pick_place.annotation','datagen':'pick_place.v8_datagen',
                      'simulation_evaluation':'pick_place.v8_evaluation'}[self.stage]
        blank=not current or (set(current)=={role} and current[role].get('function')==default_name
                              and params=={'object':'','target':''})
        if not blank:return
        def edit(doc):
            doc['functions']=result['functions']
            if self.stage=='simulation_evaluation' and not doc.setdefault('execution',{}).get('task_instruction'):
                doc['execution']['task_instruction']=result['instruction']
        self.update(edit)

    def choose_script(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        path,_=QFileDialog.getOpenFileName(self,'저장된 '+self.stage+' Script',str(self.directory),'YAML (*.yaml *.yml)')
        if path:
            try:self.load_script(path)
            except Exception as error:self.changed.emit();self.error.emit(str(error))

    def load_script(self,path):
        if not self.isEnabled():raise ValueError('현재 실행이 끝난 뒤 Script를 변경하세요.')
        try:
            data=yaml.safe_load(Path(path).read_text());self.validate_stage(data)
        except Exception:
            self.invalid_selection=True;self.changed.emit();raise
        self.invalid_selection=False
        self.editor.load(path)
        self.script_path.setText(self.editor.path.name);self.script_path.setToolTip(str(self.editor.path));self.refresh_labels();self.apply_requested.emit(self.editor.path)

    def validate_stage(self,data):
        if not isinstance(data,dict)or data.get('stage')!=self.stage:raise ValueError('stage: '+self.stage+'인 Script를 선택하세요.')
        if self.stage=='real_evaluation'and(data.get('execution',{}).get('mode')!='observe_only'or data.get('execution',{}).get('enable_motion',False)):
            raise ValueError('Real Evaluation UI는 현재 observe_only만 지원합니다. 실물 자율 Rollout은 연결되지 않았습니다.')

    def restore_run_script(self,raw,base,snapshot):
        """An archived Run becomes an unsaved draft; never edit its saved bytes."""
        data=rebase_paths(yaml.safe_load(raw),base)
        self.editor.path=None;self.invalid_selection=False
        self.editor.text.setPlainText(yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
        self.script_path.setText('Run snapshot · '+snapshot.parent.name);self.script_path.setToolTip(str(snapshot))
        self.refresh_labels()

    def save_and_apply(self):
        if not self.isEnabled():self.error.emit('현재 실행이 끝난 뒤 저장하세요.');return
        try:
            data=self.editor.data();self.validate_stage(data)
            target,_=QFileDialog.getSaveFileName(self,'Script 저장 및 적용',str(self.editor.path or self.directory/(self.stage+'.yaml')),'YAML (*.yaml *.yml)')
            if not target:return
            path=Path(target).resolve()
            if not path.suffix:path=path.with_suffix('.yaml')
            if path.suffix.lower()not in('.yaml','.yml'):raise ValueError('YAML 파일로 저장하세요.')
            if any(path.is_relative_to(self.workspace/name)for name in ('scenes','devices','runtime','.assets')):raise ValueError('Script는 자산 폴더 대신 scripts에 저장하세요.')
            if path.parent!=self.base():self.editor.text.setPlainText(yaml.safe_dump(rebase_paths(data,self.base()),sort_keys=False,allow_unicode=True))
            self.editor.save(path);self.invalid_selection=False;self.script_path.setText(path.name);self.script_path.setToolTip(str(path));self.apply_requested.emit(path)
        except Exception as error:self.changed.emit();self.error.emit(str(error))
