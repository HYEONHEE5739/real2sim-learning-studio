"""Stage-local saved Recipe and existing Run IPC. Physics stays in backend Python."""
import json
from pathlib import Path
import uuid
import time
from PyQt6.QtCore import Qt,QTimer,QUrl
from PyQt6.QtGui import QImage,QPixmap,QDesktopServices
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFileDialog,QComboBox,QSpinBox,QLineEdit,QPlainTextEdit,QCheckBox,QTableWidget,QTableWidgetItem
from .recipe_editor import RecipeEditor
from .jobs import BackendJob
from .operations import stage_support,run_outcome


class WorkflowPage(QWidget):
    def __init__(self,stage,python,modules,parent=None):
        super().__init__(parent);self.stage=stage;self.backend_python=python;self.modules=str(modules);self.handle=None;self.after_seq=0;self.request_id=None;self.ready=None;self.busy=False;self.edit_error=False;self.dataset_state='미확인';self.owned_runs=set()
        box=QVBoxLayout(self);self.heading=QLabel({'source':'Source 입력','annotation':'Annotation','datagen':'DataGen','train':'공식 LeRobot Training','hub_download':'Hub 다운로드','hub_upload':'Hub 명시 업로드','simulation_evaluation':'Simulation Evaluation','offline_validation':'독립 Validation'}[stage]);box.addWidget(self.heading)
        row=QHBoxLayout();box.addLayout(row)
        self.load_button=QPushButton('Recipe 열기');self.save_button=QPushButton('다른 이름으로 저장');self.check_button=QPushButton('저장 입력 검사')
        for button in (self.load_button,self.save_button,self.check_button):row.addWidget(button)
        self.load_button.clicked.connect(self.choose_recipe);self.save_button.clicked.connect(self.save_recipe);self.check_button.clicked.connect(self.check_recipe)
        self.editor=RecipeEditor();self.editor.changed.connect(self.invalidate)
        self.engine=QComboBox();self.engine.addItems(['mujoco','isaaclab']);self.engine.currentTextChanged.connect(lambda x:self.edit_field('engine',x))
        self.inputs={};self.form=QVBoxLayout();box.addLayout(self.form)
        if stage in ('source','annotation','datagen','simulation_evaluation'):self.form.addWidget(self.engine)
        for key in ({'source':['scene','source_dataset','engine_config'],'annotation':['dataset','scene'],'datagen':['scene','dataset','resume_dataset'],
                     'train':['dataset','training_config','policy','checkpoint'],'hub_download':['repo_id','revision'],'hub_upload':['artifact','repo_id','revision'],'simulation_evaluation':['scene','policy','engine_config','resume_dataset','policy_contract'],'offline_validation':['dataset','policy']}[stage]):
            line=QLineEdit();line.setPlaceholderText(key);line.editingFinished.connect(lambda k=key,w=line:self.edit_input(k,w.text()));self.inputs[key]=line
            row=QHBoxLayout();row.addWidget(QLabel(key));row.addWidget(line);self.form.addLayout(row)
            if key=='scene':
                use=QPushButton('현재 검사 Scene 적용');use.clicked.connect(self.use_scene);row.addWidget(use)
            browse=QPushButton('선택');browse.clicked.connect(lambda _,k=key:self.choose_input(k));row.addWidget(browse)
        self.task_instruction=QLineEdit();self.task_instruction.setPlaceholderText('Language Policy Task Instruction (명시 문장)')
        if stage=='simulation_evaluation':self.form.addWidget(self.task_instruction);self.task_instruction.editingFinished.connect(lambda:self.edit_execution('task_instruction',self.task_instruction.text()))
        self.policy_model=QLabel('Policy 모델: Checkpoint 선택 필요')
        if stage in ('simulation_evaluation','offline_validation'):self.form.addWidget(self.policy_model)
        self.output=QLineEdit();self.output.setPlaceholderText('새 결과 폴더');self.output.editingFinished.connect(lambda:self.edit_output());self.form.addWidget(self.output)
        self.placement=QComboBox();self.placement.addItems(['Fixed','Random'])
        if stage in ('datagen','simulation_evaluation'):self.form.addWidget(self.placement);self.placement.currentTextChanged.connect(self.change_placement)
        self.counts={}
        for key in ({'source':['env_num','num_episodes'],'annotation':['env_num'],'datagen':['env_num','num_episodes','max_attempts'],'simulation_evaluation':['env_num','episodes','timeout_s']}.get(stage,[])):
            spin=QSpinBox();spin.setRange(1,100000);spin.valueChanged.connect(lambda v,k=key:self.edit_execution(k,v));self.counts[key]=spin
            row=QHBoxLayout();row.addWidget(QLabel(key));row.addWidget(spin);self.form.addLayout(row)
        self.dataset_resume=None
        if stage in ('source','datagen'):
            self.dataset_resume=QCheckBox('기존 Dataset 경로에 추가 (Resume)');self.form.addWidget(self.dataset_resume);self.dataset_resume.toggled.connect(self.edit_dataset_resume)
            choose=QPushButton('Dataset 경로 선택');choose.clicked.connect(self.choose_dataset_output);self.form.addWidget(choose)
        self.mode=QComboBox();self.mode.addItems(['auto','manual'] if stage=='annotation' else ['scratch','finetune','resume'])
        if stage in ('annotation','train'):self.form.addWidget(self.mode);self.mode.currentTextChanged.connect(lambda x:self.edit_execution('mode',x))
        self.commands={};self.mark_frame=QSpinBox();self.mark_frame.setRange(1,1000000)
        if stage=='annotation':
            row=QHBoxLayout();box.addLayout(row);row.addWidget(QLabel('수동 grasp 원본 frame'));row.addWidget(self.mark_frame)
            for kind,text in [('pause','일시정지'),('resume','재생'),('step','1 step'),('mark','grasp 표시'),('skip','Episode 제외')]:
                button=QPushButton(text);button.setEnabled(False);button.clicked.connect(lambda _,k=kind:self.command(k));row.addWidget(button);self.commands[kind]=button
        self.object_table=None
        if stage in ('datagen','simulation_evaluation'):
            self.object_table=QTableWidget(0,6);self.object_table.setHorizontalHeaderLabels(['배치 Object','Frame','Support','Fixed X (m)','Fixed Y (m)','Random Workspace']);self.object_table.itemChanged.connect(self.edit_objects);box.addWidget(self.object_table)
        self.task_info=QLabel();self.task_info.setWordWrap(True);box.addWidget(self.task_info)
        self.details=QCheckBox('고급: 저장 Recipe YAML');self.details.toggled.connect(self.editor.setVisible);box.addWidget(self.details);box.addWidget(self.editor);self.editor.hide()
        self.state=QLabel('저장 Recipe를 선택하세요');self.state.setWordWrap(True);box.addWidget(self.state)
        row=QHBoxLayout();box.addLayout(row)
        self.start_button=QPushButton('실행');self.cancel_button=QPushButton('취소');self.result_button=QPushButton('결과 열기');self.resume_button=QPushButton('새 worker로 계속 실행')
        for button in (self.start_button,self.cancel_button,self.result_button,self.resume_button):row.addWidget(button)
        self.start_button.setEnabled(False);self.cancel_button.setEnabled(False);self.resume_button.setVisible(False)
        self.reopen_button=QPushButton('기존 Run 다시 열기');row.addWidget(self.reopen_button);self.reopen_button.clicked.connect(self.reopen_run)
        self.start_button.clicked.connect(self.start_run);self.cancel_button.clicked.connect(self.cancel_run);self.result_button.clicked.connect(self.open_result);self.resume_button.clicked.connect(self.continue_run)
        self.preview_env=QSpinBox();self.preview_env.setRange(0,0);self.preview_env.valueChanged.connect(self.select_preview)
        if stage in ('source','annotation','datagen','simulation_evaluation'):box.addWidget(QLabel('Preview / Manual 명령 Env'));box.addWidget(self.preview_env)
        preview=QHBoxLayout();box.addLayout(preview);self.previews={n:QLabel(n+' · Live Preview 대기') for n in ('side','wrist')}
        for label in self.previews.values():label.setMinimumSize(320,240);label.setAlignment(Qt.AlignmentFlag.AlignCenter);preview.addWidget(label)
        if stage in ('train','offline_validation'):
            for label in self.previews.values():label.hide()
        self.loss_chart=None
        if stage=='train':
            from .learning import LossChart,TrainingSettings
            self.training_settings=TrainingSettings(self);box.addWidget(self.training_settings)
            self.loss_chart=LossChart();box.addWidget(self.loss_chart)
        if stage in ('hub_download','hub_upload'):
            from .hub import HubSettings
            self.hub_settings=HubSettings(self);box.addWidget(self.hub_settings)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(1000);box.addWidget(self.log)
        self.job=BackendJob(python,self);self.job.finished.connect(self.job_finished);self.job.log.connect(self.log.appendPlainText);self.operation=None
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(34);self.generations={};self._syncing=False
        support=stage_support(stage)
        if not support['runnable']:self.state.setText(support['reason'])

    def show_policy_model(self,path):
        try:
            root=(self.editor.path.parent/path).resolve();config=json.loads((root/'config.json').read_text());self.policy_model.setText('Policy 모델: '+str(config['type'])+' · 실제 Checkpoint Config')
        except (OSError,ValueError,KeyError):self.policy_model.setText('Policy 모델: Config 확인 필요')

    def select_preview(self,index):
        if self.handle:
            from ..run import select_preview_env
            select_preview_env(self.handle['run_dir'],index)
        self.generations.clear()
        for label in self.previews.values():label.clear()

    def use_scene(self):
        scene=getattr(self.window(),'scene',None)
        if scene is None or not scene.valid:self.state.setText('Scene 화면에서 패키지를 먼저 검사하세요');return
        self.inputs['scene'].setText(scene.scene_path);self.edit_input('scene',scene.scene_path)
    def scene_matches(self):
        scene=getattr(self.window(),'scene',None)
        if scene is None or scene.scene_path is None or 'scene' not in self.inputs:return True
        path=(self.editor.path.parent/self.editor.data()['inputs']['scene']).resolve()
        if not scene.valid or str(path)!=scene.scene_path:
            self.invalidate();self.state.setText('현재 선택 Scene과 Recipe가 다릅니다. 검사 Scene을 적용하고 Recipe를 저장·재검사하세요');return False
        return True
    def choose_input(self,key):
        if key in ('dataset','source_dataset','resume_dataset','policy','checkpoint','artifact'):
            value=QFileDialog.getExistingDirectory(self,key+' 선택')
        else:value,_=QFileDialog.getOpenFileName(self,key+' 선택')
        if value:self.inputs[key].setText(value);self.edit_input(key,value)

    def command(self,kind):
        if not self.handle or not self.active():return
        if kind=='mark' and not 0<self.mark_frame.value()<=getattr(self,'env_contexts',{}).get(self.preview_env.value(),getattr(self,'context',{})).get('tick',-1):
            self.log.appendPlainText('아직 재생하지 않은 frame은 표시할 수 없습니다');return
        from ..run import RunHandle,send_command
        payload={'count':1} if kind=='step' else ({'event':'grasp','frame':self.mark_frame.value()} if kind=='mark' else ({'reason':'user'} if kind=='skip' else {}))
        try:
            h=self.handle;context=getattr(self,'env_contexts',{}).get(self.preview_env.value(),getattr(self,'context',{}));command={'command_id':uuid.uuid4().hex,'kind':kind,'payload':payload}
            if 'episode_id' in context:command.update(episode_id=context['episode_id'],env_index=self.preview_env.value())
            receipt=send_command(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),command)
            self.log.appendPlainText(kind+' 요청: '+receipt.status+' · 실제 적용 ACK는 로그로 확인')
        except Exception as error:self.log.appendPlainText(str(error))

    def invalidate(self):
        self.ready=None;self.start_button.setEnabled(False)
    def choose_recipe(self):
        path,_=QFileDialog.getOpenFileName(self,'저장 Recipe','','YAML (*.yaml *.yml)')
        if path:
            try:self.load_recipe(path)
            except Exception as error:self.invalidate();self.state.setText(str(error))
    def load_recipe(self,path):
        if self.active():raise ValueError('실행 중인 Recipe를 바꿀 수 없습니다')
        import yaml
        data=yaml.safe_load(Path(path).read_text())
        if not isinstance(data,dict) or data.get('stage')!=self.stage:raise ValueError('현재 화면과 Recipe stage가 다릅니다')
        self.editor.load(path);self.edit_error=False
        self._syncing=True
        try:
            self.engine.setCurrentText(data.get('engine','mujoco'));self.output.setText(data['output']['directory'])
            for key,line in self.inputs.items():line.setText(data['inputs'].get(key,''))
            for key,spin in self.counts.items():spin.setValue(int(data['execution'].get(key,data['execution'].get('episodes',data['execution'].get('target_successes',1)) if key=='num_episodes' else 1)))
            self.preview_env.setRange(0,max(0,int(data['execution'].get('env_num',data['execution'].get('num_envs',1)))-1))
            if self.dataset_resume is not None:self.dataset_resume.setChecked(data['execution'].get('resume',False))
            self.task_instruction.setText(data['execution'].get('task_instruction',''))
            self.mode.setCurrentText(data['execution'].get('mode','auto'))
            names=[o['placement']['function'] for o in data.get('objects',{}).values()]
            self.placement.setCurrentText('Random' if names and all(n=='placement.random_workspace' for n in names) else 'Fixed')
        finally:self._syncing=False
        if hasattr(self,'hub_settings'):self.hub_settings.sync(data)
        self.sync_objects(data)
        if 'policy' in data['inputs']:self.show_policy_model(data['inputs']['policy'])
        fn=data.get('functions',{}).get('acceptance',data.get('functions',{}).get('success',{}));self.task_info.setText('Task · '+str(fn.get('function',''))+' · '+str(fn.get('params',{})))
        self.invalidate();self.state.setText('저장됨 — 입력 검사를 실행하세요')
    def safe_update(self,fn):
        try:self.editor.update(fn);return True
        except Exception as error:self.edit_error=True;self.invalidate();self.state.setText('Recipe 편집 오류: '+str(error))
    def edit_field(self,key,value):
        if self._syncing or self.editor.path is None:return
        self.safe_update(lambda data:data.__setitem__(key,value))
    def edit_input(self,key,value):
        if self._syncing or self.editor.path is None:return
        def update(data):
            if value:data['inputs'][key]=value
            else:data['inputs'].pop(key,None)
        self.safe_update(update)
        if key=='policy':self.show_policy_model(value)
    def choose_dataset_output(self):
        folder=QFileDialog.getExistingDirectory(self,'기존 Dataset 또는 새 Dataset의 상위 폴더')
        if not folder:return
        target=Path(folder) if self.dataset_resume.isChecked() else Path(folder)/('dataset-'+uuid.uuid4().hex[:8])
        self.output.setText(str(target));self.edit_output()
    def edit_dataset_resume(self,value):
        if self._syncing or self.editor.path is None:return
        def edit(data):
            data['execution']['resume']=value;data['execution']['num_episodes']=self.counts['num_episodes'].value();data['execution'].pop('episodes',None);data['execution'].pop('target_successes',None);data['inputs'].pop('resume_dataset',None)
        self.safe_update(edit)
    def edit_execution(self,key,value):
        if self._syncing or self.editor.path is None:return
        def edit(data):
            data['execution'][key]=value
            if key=='env_num':data['execution'].pop('num_envs',None)
            if key=='num_episodes':data['execution'].pop('episodes',None);data['execution'].pop('target_successes',None)
        self.safe_update(edit)
        if key=='env_num':self.preview_env.setRange(0,value-1)
    def edit_output(self):
        if self._syncing or self.editor.path is None:return
        self.safe_update(lambda data:data['output'].__setitem__('directory',self.output.text()))

    def sync_objects(self,data):
        if self.object_table is None:return
        self._syncing=True
        try:
            import copy
            self.object_presets=copy.deepcopy(data.get('objects',{}));self.object_table.setRowCount(len(self.object_presets))
            for i,(name,obj) in enumerate(data.get('objects',{}).items()):
                p=obj['placement']['params'];xy=p.get('xy_m',['',''])
                for j,value in enumerate([name,p.get('frame',''),p.get('support',''),*xy,p.get('workspace','')]):
                    item=QTableWidgetItem(str(value))
                    if j==0:
                        item.setFlags((item.flags() & ~Qt.ItemFlag.ItemIsEditable)|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked)
                    self.object_table.setItem(i,j,item)
        finally:self._syncing=False
    def edit_objects(self,*_):
        if self._syncing or self.editor.path is None:return
        def change(data):
            for i in range(self.object_table.rowCount()):
                name,frame,support,x,y,workspace=[self.object_table.item(i,j).text().strip() for j in range(6)]
                if self.object_table.item(i,0).checkState()!=Qt.CheckState.Checked:data['objects'].pop(name,None);continue
                if name not in data['objects']:
                    import copy
                    data['objects'][name]=copy.deepcopy(self.object_presets[name])
                old=data['objects'][name]['placement'];same=(old['function']=='placement.random_workspace')==(self.placement.currentText()=='Random')
                params=dict(old.get('params',{})) if same else {}
                params.update(frame=frame,support=support)
                if self.placement.currentText()=='Random':
                    if not workspace:raise ValueError('실제 Workspace Object를 지정하세요')
                    params['workspace']=workspace;function='placement.random_workspace'
                else:params['xy_m']=[float(x),float(y)];function='placement.fixed_xy'
                data['objects'][name]['placement']={'function':function,'params':params}
        if self.safe_update(change):self.edit_error=False
    def change_placement(self,mode):
        if not self._syncing:self.edit_objects()
    def reopen_run(self):
        if self.active():return
        folder=QFileDialog.getExistingDirectory(self,'기존 Run 폴더 (run.json)')
        if not folder:return
        try:
            path=Path(folder).resolve();record=json.loads((path/'run.json').read_text())
            if record['stage']!=self.stage:raise ValueError('현재 화면과 Run stage가 다릅니다')
            req=json.loads((path/'worker_request.json').read_text())['request']
            self.context={};self.env_contexts={};self.handle={'run_id':record['run_id'],'request_id':record['request_id'],'run_dir':str(path),'output_path':req['output_path']};self.after_seq=0;self.generations.clear();self.poll()
        except Exception as error:self.state.setText(str(error))
    def save_recipe(self):
        path,_=QFileDialog.getSaveFileName(self,'보존 자료와 별도의 Recipe 저장','','YAML (*.yaml)')
        if path:
            try:self.editor.save(path)
            except Exception as error:self.state.setText(str(error))
    def check_recipe(self):
        if self.edit_error:self.state.setText('화면 편집 오류를 수정하거나 저장 Recipe를 다시 여세요');return
        if self.editor.path is None or self.editor.dirty:self.state.setText('먼저 Recipe를 저장하세요');return
        try:
            from ..recipe import read_recipe
            read_recipe(self.editor.path,expected_stage=self.stage)
            self.state.setText('문법 유효 · 실제 입력 검사 중…');self.operation='prepare';self.busy=True
            self.job.start('prepare',path=str(self.editor.path),modules=self.modules)
        except Exception as error:self.busy=False;self.state.setText(str(error))
    def active(self):
        if self.handle is None:return self.busy
        from ..run import read_status
        return self.busy or read_status(self.handle['run_dir']).status not in ('completed','cancelled','failed','unknown')
    def start_run(self):
        if not self.ready or self.editor.dirty or self.edit_error or self.active():return
        if not self.scene_matches():return
        if any(page is not self and page.active() for page in getattr(self.window(),'workflows',{}).values()):
            self.state.setText('현재 실행 중인 worker를 종료한 뒤 시작하세요');return
        for name,label in self.previews.items():label.clear();label.setText(name+' · 새 Run 대기')
        self.request_id=uuid.uuid4().hex;self.operation='start';self.busy=True;self.start_button.setEnabled(False);self.state.setText('worker 시작 준비 중…')
        self.job.start('start',path=str(self.editor.path),modules=self.modules,request_id=self.request_id,expected_recipe_sha256=self.ready['recipe_sha256'],expected_prepared_sha256=self.ready['prepared_sha256'])
    def job_finished(self,response):
        self.busy=False
        if self.operation=='terminal_catalog':self.dataset_state='저장 검증 통과' if response.get('ok') else '저장 검증 실패: '+response.get('error',{}).get('message','오류')
        if not response.get('ok'):
            self.ready=None;self.state.setText(response.get('error',{}).get('message','Backend 오류'));return
        data=response['result']
        if self.operation=='prepare':
            self.ready=data if data['runnable'] and data['state']=='runtime_ready' else None
            self.state.setText(('입력 준비 완료 · ' if self.ready else 'Prepared · 실행 차단 · ')+data['reason']);self.start_button.setEnabled(self.ready is not None)
        elif self.operation=='terminal_catalog':
            self.log.appendPlainText('저장 결과 재개방 확인 · 완료 Episode '+str(len(data['inspection']['episodes']))+' / 미완료 intent '+str(len(data['inspection']['unresolved_source_intents'])))
        elif self.operation=='start':
            self.handle=data;self.context={};self.env_contexts={};self.owned_runs.add(data['run_dir']);self.dataset_state='미확인';self.after_seq=0;self.generations.clear();self.cancel_button.setEnabled(True);self.state.setText('worker 실행 중')
        self.operation=None
    def cancel_run(self):
        if not self.handle:return
        from ..run import RunHandle,send_command
        h=self.handle
        receipt=send_command(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),{'command_id':uuid.uuid4().hex,'kind':'cancel','payload':{}})
        self.state.setText('취소 요청 '+receipt.status+' · 실제 종료를 기다립니다')
    def poll(self):
        if not self.handle:return
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
            for kind,button in self.commands.items():button.setEnabled(not outcome['worker_finished'] and status.status!='unknown' and (kind!='step' or self.engine.currentText()!='isaaclab' or self.counts.get('env_num').value()==1) and (kind!='mark' or (self.mode.currentText()=='manual' and self.mark_frame.value()<=getattr(self,'env_contexts',{}).get(self.preview_env.value(),getattr(self,'context',{})).get('tick',-1))))
            if outcome['worker_finished'] or status.status=='unknown':
                self.cancel_button.setEnabled(False)
                if status.status=='unknown' and self.handle['run_dir'] in self.owned_runs:
                    import shutil
                    shutil.rmtree(Path(self.handle['run_dir'])/'preview',ignore_errors=True)
                if self.stage in ('source','annotation','datagen','simulation_evaluation') and getattr(self,'_verified_terminal',None)!=self.handle['run_id'] and not self.busy:
                    self._verified_terminal=self.handle['run_id'];self.operation='terminal_catalog';self.busy=True;self.job.start('catalog',path=self.handle['output_path'])
                for name,label in self.previews.items():label.clear();label.setText(name+' · Live Preview 종료')
                self.resume_button.setVisible(bool(outcome['needs_resume']))
                text='Worker '+status.status+' · '+self.dataset_state+' · 완료 Episode '+str(outcome['completed_episodes'])
                if outcome.get('existing_episodes') is not None:text+=' · 기존 '+str(outcome['existing_episodes'])+' / 추가 '+str(outcome['added_episodes'])
                if outcome['goal_reached'] is False:text+=' · 목표 미달'
                if outcome['needs_resume']:text+=' · 새 worker/새 출력 Resume 필요'
                if outcome['budget_exhausted']:text+=' · Attempt 예산 소진'
                if outcome['successes'] is not None:text+=' · Task 성공 '+str(outcome['successes'])+' / 실패 '+str(outcome['failures'])
                if outcome['success_rate'] is not None:text+=' · 성공률 '+str(outcome['success_rate'])
                if outcome['error']:text+=' · '+outcome['error'].get('message','오류')
                self.state.setText(text)
                if self.stage=='train':self.show_training_result()
                return
            if getattr(self,'_preview_selected',None)!=(self.handle['run_id'],self.preview_env.value()) and (Path(self.handle['run_dir'])/'preview').is_dir():
                self.select_preview(self.preview_env.value());self._preview_selected=(self.handle['run_id'],self.preview_env.value())
            self.state.setText('Worker '+status.status+' · '+str(record.get('progress',{}))+(' · Vector pause/resume는 전체 Scene에 적용' if self.engine.currentText()=='isaaclab' and self.counts.get('env_num') and self.counts['env_num'].value()>1 else ''))
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
    def continue_run(self):
        if not self.handle or self.stage!='datagen' or self.active():return
        out=QFileDialog.getExistingDirectory(self,'새 출력의 상위 폴더 선택')
        if not out:return
        # The user saves/inspects this new Recipe before preparing; never auto-loop.
        self.safe_update(lambda d:(d['inputs'].__setitem__('resume_dataset',self.handle['output_path']),d['output'].__setitem__('directory',str(Path(out)/('continued-'+uuid.uuid4().hex[:8])))))
        self.output.setText(self.editor.data()['output']['directory']);self.state.setText('Resume Recipe 편집 중 · 새 이름으로 저장하고 검사하세요')
    def show_training_result(self):
        path=Path(self.handle['output_path'])/'training-result.json'
        if path.is_file() and getattr(self,'_shown_training',None)!=str(path):
            result=json.loads(path.read_text());self.log.appendPlainText(json.dumps({'loss':result['metrics'],'checkpoints':result['checkpoints']},ensure_ascii=False));self._shown_training=str(path)
