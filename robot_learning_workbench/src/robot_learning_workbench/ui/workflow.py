"""Stage-local saved Recipe and existing Run IPC. Physics stays in backend Python."""
import json
from pathlib import Path
import uuid
import time
from PyQt6.QtCore import Qt,QTimer,QUrl
from PyQt6.QtGui import QImage,QPixmap,QDesktopServices,QShortcut,QKeySequence
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFileDialog,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QPlainTextEdit,QCheckBox,QTableWidget,QTableWidgetItem,QMessageBox,QInputDialog,QGridLayout,QSplitter,QScrollArea,QDialog,QListWidget,QProgressBar
from .recipe_editor import RecipeEditor
from .jobs import BackendJob
from .operations import stage_support,run_outcome


class WorkflowPage(QWidget):
    def __init__(self,stage,python,modules,parent=None):
        super().__init__(parent)
        if stage in ('capture','real_sim'):raise ValueError('Use the dedicated SessionPage for Capture / Real-Sim')
        from .theme import STYLE
        from .view import CameraView
        self.setStyleSheet(STYLE)
        self.stage=stage;self.workspace=Path(getattr(parent,'workspace',Path.cwd())).resolve();self.backend_python=python;self.modules=str(modules)
        self.handle=None;self.after_seq=0;self.request_id=None;self.ready=None;self.busy=False;self.edit_error=False;self.dataset_state='미확인';self.owned_runs=set();self._syncing=False
        titles={'teleoperation':'Teleoperation · Fake / 읽기 전용','source':'Source Demo','annotation':'Annotation','datagen':'Mimic / Datagen','train':'모델 학습','hub_download':'Hub 다운로드','hub_upload':'Hub 업로드','simulation_evaluation':'Sim 평가','offline_validation':'Offline Validation','real_evaluation':'Real Policy · Observe Only'}
        self.heading=QLabel(titles[stage]);self.heading.setObjectName('dashboardTitle');self.heading.hide()
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(12)
        self.splitter=QSplitter(Qt.Orientation.Horizontal);outer.addWidget(self.splitter,1)
        self.viewer=QWidget();self.viewer.setObjectName('workspaceCanvas');box=QVBoxLayout(self.viewer);box.setContentsMargins(0,0,0,0);box.setSpacing(12);self.splitter.addWidget(self.viewer)
        self.settings_scroll=QScrollArea();self.settings_scroll.setObjectName('settingsPanel');self.settings_scroll.setWidgetResizable(True);self.settings_scroll.setMinimumWidth(320)
        self.settings_content=QWidget();self.settings_content.setObjectName('settingsContent');settings=QVBoxLayout(self.settings_content);settings.setSpacing(10);self.settings_scroll.setWidget(self.settings_content);self.splitter.addWidget(self.settings_scroll)
        self.splitter.setChildrenCollapsible(False);self.splitter.setStretchFactor(0,1);self.splitter.setStretchFactor(1,0);self.splitter.setSizes([850,390])
        title=QLabel('실행 설정');title.setObjectName('sectionTitle');settings.addWidget(title)
        recipe_row=QGridLayout();settings.addLayout(recipe_row)
        self.load_button=QPushButton('Recipe 불러오기');self.save_button=QPushButton('다른 이름으로 저장');self.check_button=QPushButton('저장 입력 검사');self.new_output_button=QPushButton('새 Run 출력')
        for i,button in enumerate((self.load_button,self.save_button,self.check_button,self.new_output_button)):recipe_row.addWidget(button,i//2,i%2)
        self.recipe_status=QLabel('저장 Recipe를 선택하세요');self.recipe_status.setWordWrap(True);settings.addWidget(self.recipe_status)
        self.load_button.clicked.connect(self.choose_recipe);self.save_button.clicked.connect(self.save_recipe);self.check_button.clicked.connect(self.check_recipe);self.new_output_button.clicked.connect(self.suggest_output)
        self.form=QVBoxLayout();settings.addLayout(self.form)
        self.details=QCheckBox('고급 설정 · 입력 계약 / Recipe YAML');self.advanced=QWidget();self.advanced_form=QVBoxLayout(self.advanced);self.advanced_form.setContentsMargins(0,0,0,0)
        self.details.toggled.connect(self.advanced.setVisible);self.advanced.hide()
        self.editor=RecipeEditor();self.editor.changed.connect(self.invalidate)
        self.input_rows={};self.inputs={}
        def field(layout,label,widget):
            panel=QWidget();panel.setObjectName('settingsContent');row=QVBoxLayout(panel);row.setContentsMargins(0,0,0,0);row.setSpacing(4);row.addWidget(QLabel(label));row.addWidget(widget);layout.addWidget(panel);return panel
        self.engine=QComboBox();self.engine.addItems(['mujoco','isaaclab']);self.engine.currentTextChanged.connect(lambda x:self.edit_field('engine',x))
        if stage in ('source','annotation','datagen','simulation_evaluation','real_sim'):field(self.form,'Simulation backend',self.engine)
        self.source_kind=None
        if stage=='source':
            self.source_kind=QComboBox();self.source_kind.addItems(['Recorded Target Stream','Live Leader (read only → Simulation)']);field(self.form,'Source 입력',self.source_kind);self.source_kind.currentIndexChanged.connect(self.change_source_kind)
        labels={'scene':'Scene Package','dataset':'사용할 데이터','source_dataset':'저장된 Target Stream','device_profile':'장치 연결 Profile','engine_config':'엔진 실행 설정','resume_dataset':'기존 결과 · 다른 출력 Resume','training_config':'공식 Training Config','policy':'Policy / Checkpoint','checkpoint':'Resume Checkpoint','repo_id':'Repository ID','revision':'Revision / Commit','artifact':'업로드할 Dataset / Policy','policy_contract':'외부 Policy 의미 계약','camera_config':'Side / Wrist Camera 설정','capture_session':'보존 Capture','calibration_profile':'관절 관측 Profile','robot_model':'Capture용 원본 Robot Model','leader_device_profile':'Fake Leader Profile','leader_calibration_profile':'Fake Leader 관측 Profile'}
        keys={'teleoperation':['device_profile','calibration_profile','leader_device_profile','leader_calibration_profile','scene','camera_config'],'source':['scene','source_dataset','device_profile','engine_config'],'annotation':['dataset','scene'],'datagen':['scene','dataset','resume_dataset'],'train':['dataset','training_config','policy','checkpoint'],'hub_download':['repo_id','revision'],'hub_upload':['artifact','repo_id','revision'],'simulation_evaluation':['scene','policy','engine_config','resume_dataset','policy_contract'],'offline_validation':['dataset','policy','policy_contract'],'real_evaluation':['scene','policy','policy_contract','device_profile','camera_config','capture_session','calibration_profile']}[stage]
        primary={'scene','dataset','source_dataset','device_profile','training_config','policy','checkpoint','repo_id','revision','artifact','calibration_profile','camera_config'}
        for key in keys:
            line=QLineEdit();line.setPlaceholderText(labels[key]);line.editingFinished.connect(lambda k=key,w=line:self.edit_input(k,w.text()));self.inputs[key]=line
            panel=QWidget();panel.setObjectName('settingsContent');row=QVBoxLayout(panel);row.setContentsMargins(0,0,0,0);row.setSpacing(4);row.addWidget(QLabel(labels[key]));row.addWidget(line)
            buttons=QHBoxLayout();row.addLayout(buttons)
            browse=QPushButton('선택');browse.clicked.connect(lambda _,k=key:self.choose_input(k));buttons.addWidget(browse)
            if key=='scene':
                use=QPushButton('검사한 Scene 적용');use.clicked.connect(self.use_scene);buttons.addWidget(use)
            (self.form if key in primary else self.advanced_form).addWidget(panel);self.input_rows[key]=panel
        self.output=QLineEdit();self.output.setPlaceholderText('새 결과 폴더');self.output.editingFinished.connect(self.edit_output);field(self.form,'저장 위치',self.output)
        self.mode=QComboBox();self.mode.addItems(['fake_all','observe_only','gripper_once']if stage=='teleoperation'else['auto','manual']if stage=='annotation'else{'real_evaluation':['offline','observe_only','gripper_once','fake_all']}[stage]if stage=='real_evaluation'else['scratch','finetune','resume'])
        if stage in ('annotation','train','capture','real_evaluation','real_sim','teleoperation'):field(self.form,'실행 방식',self.mode);self.mode.currentTextChanged.connect(lambda x:self.edit_execution('mode',x))
        self.counts={};self.count_labels={}
        for key in {'source':['env_num','num_episodes'],'annotation':['env_num'],'datagen':['env_num','num_episodes','max_attempts'],'simulation_evaluation':['env_num','episodes','timeout_s']}.get(stage,[]):
            spin=QDoubleSpinBox()if key=='timeout_s'else QSpinBox();spin.setRange(.001 if key=='timeout_s'else 1,100000);spin.valueChanged.connect(lambda value,k=key:self.edit_execution(k,value));self.counts[key]=spin
            if key=='timeout_s':spin.setDecimals(3);spin.setSingleStep(.1)
            panel=field(self.form,{'env_num':'환경 수','num_episodes':'추가 Episode 수','max_attempts':'시도 예산','episodes':'평가 Attempt 목표','timeout_s':'평가 최대 시간 (제어 시각 s)'}[key],spin);self.count_labels[key]=panel.findChild(QLabel)
        self.placement=QComboBox();self.placement.addItems(['Fixed','Random'])
        self.object_table=None
        if stage in ('datagen','simulation_evaluation'):
            field(self.form,'Object Placement',self.placement);self.placement.currentTextChanged.connect(self.change_placement)
            self.object_table=QTableWidget(0,6);self.object_table.setHorizontalHeaderLabels(['Object','Frame','Support','Fixed X (m)','Fixed Y (m)','Workspace']);self.object_table.setMaximumHeight(190);self.object_table.setMinimumWidth(0);self.object_table.itemChanged.connect(self.edit_objects);self.form.addWidget(self.object_table)
        self.dataset_resume=None
        if stage in ('source','datagen'):
            self.dataset_resume=QCheckBox('기존 Dataset에 추가 저장 (Resume)');self.dataset_resume.toggled.connect(self.edit_dataset_resume);self.form.addWidget(self.dataset_resume)
            choose=QPushButton('이어 수집할 Dataset 선택');choose.clicked.connect(self.choose_dataset_output);self.form.addWidget(choose)
        self.task_instruction=QLineEdit();self.task_instruction.setPlaceholderText('실제 작업 문장')
        if stage in ('simulation_evaluation','real_evaluation'):field(self.form,'Task Instruction',self.task_instruction);self.task_instruction.editingFinished.connect(lambda:self.edit_execution('task_instruction',self.task_instruction.text()))
        self.policy_model=QLabel('Policy 모델: Checkpoint 선택 필요');self.policy_model.setWordWrap(True)
        if stage in ('simulation_evaluation','offline_validation'):self.form.addWidget(self.policy_model)
        if stage in ('real_evaluation','teleoperation'):
            self.live_frames=QSpinBox();self.live_frames.setRange(1,300);self.live_frames.valueChanged.connect(lambda value:self.edit_execution('max_frames',value));field(self.form,'읽기 / Fake 최대 frame · 팔 구동 없음',self.live_frames)
        self.gripper_fields={}
        if stage in ('teleoperation','real_evaluation'):
            for key in (('gripper_target_rad','max_gripper_delta_raw')if stage=='teleoperation'else('max_gripper_delta_raw',)):
                line=QLineEdit();line.setPlaceholderText('동작 기본값 없음');line.editingFinished.connect(lambda k=key,w=line:self.edit_gripper_parameter(k,w.text()));self.gripper_fields[key]=line
                field(self.advanced_form,'Gripper 목표 (rad)'if key.endswith('_rad')else'승인된 Gripper 변위 상한 (encoder count)',line)
        self.task_info=QLabel();self.task_info.setWordWrap(True);self.advanced_form.addWidget(self.task_info)
        self.advanced_form.addWidget(self.editor)
        if stage=='train':
            from .learning import TrainingSettings
            self.training_settings=TrainingSettings(self);self.form.addWidget(self.training_settings)
            self.form.removeWidget(self.input_rows['training_config']);self.advanced_form.insertWidget(0,self.input_rows['training_config'])
            mode_row=self.mode.parentWidget();self.form.removeWidget(mode_row);self.form.insertWidget(0,mode_row);self.form.removeWidget(self.training_settings);self.form.insertWidget(1,self.training_settings)
        if stage in ('hub_download','hub_upload'):
            from .hub import HubSettings
            self.hub_settings=HubSettings(self);self.form.addWidget(self.hub_settings)
        settings.addWidget(self.details);settings.addWidget(self.advanced);settings.addStretch()
        self.state=QLabel('저장 Recipe를 선택하세요');self.state.setWordWrap(True);self.state.setStyleSheet('background: transparent; padding: 6px;')
        self.action_card=QWidget();self.action_card.setObjectName('actionCard');actions=QHBoxLayout(self.action_card);actions.addWidget(self.state,1);box.addWidget(self.action_card)
        self.start_button=QPushButton({'source':'데모 기록 시작','annotation':'Annotation 시작','datagen':'데이터 생성 시작','train':'학습 시작','simulation_evaluation':'Sim 평가 시작'}.get(stage,'선택 단계 실행'));self.start_button.setObjectName('primaryAction')
        self.cancel_button=QPushButton('현재 workflow 중지');self.cancel_button.setObjectName('stopAction');actions.addWidget(self.start_button);actions.addWidget(self.cancel_button)
        self.start_button.setEnabled(False);self.cancel_button.setEnabled(False);self.start_button.clicked.connect(self.start_run);self.cancel_button.clicked.connect(self.cancel_run)
        self.commands={};self.mark_frame=QSpinBox();self.mark_frame.setRange(1,1000000);controls=QGridLayout();box.addLayout(controls)
        if stage=='annotation':
            controls.addWidget(QLabel('Grasp Frame'),1,0);self.mark_frame.setMaximumWidth(110);controls.addWidget(self.mark_frame,1,1)
            for i,(kind,text) in enumerate([('pause','일시정지'),('resume','재생'),('step','한 스텝'),('mark','Grasp 표시'),('skip','Episode 건너뛰기')]):
                button=QPushButton(text);button.setEnabled(False);button.clicked.connect(lambda _,k=kind:self.command(k));controls.addWidget(button,0,i);self.commands[kind]=button
        if stage=='source':
            for i,(kind,text) in enumerate([('save','저장 / 다음 (→)'),('discard','폐기 (←)')]):
                button=QPushButton(text);button.setEnabled(False);button.clicked.connect(lambda _,k=kind:self.command(k));controls.addWidget(button,0,i);self.commands[kind]=button
        self.preview_env=QSpinBox();self.preview_env.setMaximumWidth(80);self.preview_env.setRange(0,0);self.preview_env.valueChanged.connect(self.select_preview)
        if stage in ('source','annotation','datagen','simulation_evaluation'):
            self.preview_env_label=QLabel('Env');controls.addWidget(self.preview_env_label,1,3);controls.addWidget(self.preview_env,1,4)
        self.gripper_button=QPushButton('Gripper-Only · 별도 현장 승인 / 팔 5축 금지');self.gripper_button.setEnabled(False);self.gripper_button.clicked.connect(self.approve_gripper)
        if stage in ('real_evaluation','teleoperation'):box.addWidget(self.gripper_button)
        self.progress_bar=QProgressBar();self.progress_bar.setRange(0,1);self.progress_bar.setValue(0);self.progress_bar.setFormat('Worker 대기');self.progress_text=QLabel('');self.progress_text.setWordWrap(True)
        if stage in ('source','annotation','datagen','train','simulation_evaluation'):box.addWidget(self.progress_bar);box.addWidget(self.progress_text)
        self.media_splitter=QSplitter(Qt.Orientation.Vertical);box.addWidget(self.media_splitter,1)
        self.preview_card=QWidget();self.preview_card.setObjectName('previewCard');grid=QGridLayout(self.preview_card);self.media_splitter.addWidget(self.preview_card)
        self.previews={};self.sim_previews={}
        for col,n in enumerate(('side','wrist')):
            grid.addWidget(QLabel(('REAL 'if stage=='real_evaluation'else'SIM ')+n.upper()),0,col);label=CameraView(n.upper()+' — 실행 대기',minimum=(120,90));grid.addWidget(label,1,col);self.previews[n]=label
        grid.setRowStretch(1,1)
        for label in (*self.previews.values(),*self.sim_previews.values()):label.setStyleSheet('background: #141b23; border-radius: 14px; color: #8b9aaa;')
        self.preview_card.setVisible(stage in ('source','annotation','datagen','simulation_evaluation','real_evaluation'))
        self.log_card=QWidget();self.log_card.setObjectName('logCard');log_box=QVBoxLayout(self.log_card);self.media_splitter.addWidget(self.log_card)
        tools=QGridLayout();log_box.addLayout(tools);tools.addWidget(QLabel('진행 / 오류 로그'),0,0)
        self.result_button=QPushButton('결과 상세');self.result_button.clicked.connect(self.open_result);tools.addWidget(self.result_button,0,1)
        self.reopen_button=QPushButton('기존 Run 열기');self.reopen_button.clicked.connect(self.reopen_run);tools.addWidget(self.reopen_button,0,2)
        self.resume_button=QPushButton('새 worker로 계속 실행');self.resume_button.clicked.connect(self.continue_run);self.resume_button.hide();tools.addWidget(self.resume_button,1,1,1,2)
        self.loss_chart=None
        if stage=='train':
            from .learning import LossChart
            self.loss_chart=LossChart();self.loss_chart.hide();loss_button=QPushButton('학습 Loss 그래프');loss_button.clicked.connect(self.show_loss);tools.addWidget(loss_button,1,0)
        self.log=QPlainTextEdit();self.log.setObjectName('console');self.log.setReadOnly(True);self.log.setMaximumBlockCount(1000);log_box.addWidget(self.log)
        self.media_splitter.setStretchFactor(0,3);self.media_splitter.setStretchFactor(1,1);self.media_splitter.setSizes([500,180])
        if stage=='source':self.progress_bar.hide();self.progress_text.setObjectName('mutedLabel');self.progress_text.setText('Source 기록 전용 · 실물 Follower 명령 없음')
        self.job=BackendJob(python,self);self.job.finished.connect(self.job_finished);self.job.log.connect(self.log.appendPlainText);self.operation=None
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(34);self.generations={}
        if stage=='source':
            self.viewer.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.shortcuts=[]
            for key,kind in [('Right','save'),('Left','discard')]:
                shortcut=QShortcut(QKeySequence(key),self.viewer);shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);shortcut.setAutoRepeat(False);shortcut.activated.connect(lambda k=kind:self.commands[k].click()if self.commands[k].isEnabled()else None);self.shortcuts.append(shortcut)
        support=stage_support(stage)
        self.mode.currentTextChanged.connect(self.sync_input_visibility);self.sync_input_visibility()
        if self.source_kind is not None:self.change_source_kind(self.source_kind.currentIndex())
        if not support['runnable']:self.state.setText(support['reason'])

    def sync_input_visibility(self,*_):
        if self.stage=='train':
            self.input_rows['policy'].setVisible(self.mode.currentText()=='finetune');self.input_rows['checkpoint'].setVisible(self.mode.currentText()=='resume')
        if self.stage=='source':
            show=self.counts['env_num'].value()>1;self.preview_env_label.setVisible(show);self.preview_env.setVisible(show)

    def display_hardware_result(self,data):
        if hasattr(self,'readiness'):
            self.readiness.setText('최근 Run '+str(data.get('status'))+' · 측정 '+str(data.get('frames',0))+' frame · command_sent='+str(data.get('command_sent',False)))
    def show_loss(self):
        if self.stage!='train':return
        if not hasattr(self,'loss_dialog'):
            self.loss_dialog=QDialog(self);self.loss_dialog.setWindowTitle('학습 Loss · 공식 로그');self.loss_dialog.resize(1000,600);QVBoxLayout(self.loss_dialog).addWidget(self.loss_chart)
        self.loss_chart.show();self.loss_dialog.show();self.loss_dialog.raise_()

    def hideEvent(self,event):
        if hasattr(self,'loss_dialog'):self.loss_dialog.hide()
        super().hideEvent(event)

    def show_policy_model(self,path):
        try:
            from ..recipe import policy_model_path
            root=policy_model_path(self.editor.path.parent/path);config=json.loads((root/'config.json').read_text());self.policy_model.setText('Policy 모델: '+str(config['type'])+' · 실제 Checkpoint Config')
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
    def suggest_output(self):
        if self.active() or self.editor.path is None:self.state.setText('저장 Recipe를 열고 기존 실행이 끝난 뒤 새 출력을 제안하세요');return
        if self.dataset_resume is not None and self.dataset_resume.isChecked():self.state.setText('Resume는 명시한 기존 Dataset 경로를 유지합니다');return
        from .paths import output_path
        if self.stage in ('hub_download','hub_upload'):
            group='policy' if self.hub_settings.kind.currentText()=='model' else 'dataset'
            path=self.workspace/group/(self.stage+'-'+uuid.uuid4().hex[:8])
        else:path=output_path(self.workspace,self.stage)
        self.output.setText(str(path));self.edit_output();self.state.setText('새 출력 제안 · Recipe와 공식 Training Config를 저장하고 다시 검사하세요')
    def choose_input(self,key):
        from .paths import input_directory
        directory=str(input_directory(self.workspace,self.stage,key))
        if key=='artifact' and self.hub_settings.kind.currentText()=='model':directory=str(self.workspace/'policy')
        if key in ('dataset','source_dataset','resume_dataset','policy','checkpoint','artifact','capture_session'):
            value=QFileDialog.getExistingDirectory(self,key+' 선택',directory)
        else:value,_=QFileDialog.getOpenFileName(self,key+' 선택',directory)
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
        if hasattr(self,'recipe_status')and self.editor.dirty:self.recipe_status.setText('편집 중 · 저장하고 다시 검사하세요')
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
            if self.source_kind is not None:self.source_kind.setCurrentIndex(1 if 'device_profile'in data['inputs'] else 0)
            for key,line in self.inputs.items():line.setText(data['inputs'].get(key,''))
            for key,spin in self.counts.items():
                value=data['execution'].get(key,data['execution'].get('episodes',data['execution'].get('target_successes',1))if key=='num_episodes'else 1);spin.setValue(float(value)if key=='timeout_s'else int(value))
            if 'num_episodes'in self.count_labels:self.count_labels['num_episodes'].setText('추가 Episode 수'if'num_episodes'in data['execution']else'누적 Episode 목표 · 기존 Recipe')
            self.preview_env.setRange(0,max(0,int(data['execution'].get('env_num',data['execution'].get('num_envs',1)))-1))
            if self.dataset_resume is not None:self.dataset_resume.setChecked(data['execution'].get('resume',False))
            self.task_instruction.setText(data['execution'].get('task_instruction',''))
            self.mode.setCurrentText(data['execution'].get('mode','auto'))
            if hasattr(self,'live_frames'):self.live_frames.setValue(data['execution'].get('max_frames',1))
            for key,line in self.gripper_fields.items():line.setText(str(data['execution'][key])if key in data['execution']else'')
            names=[o['placement']['function'] for o in data.get('objects',{}).values()]
            self.placement.setCurrentText('Random' if names and all(n=='placement.random_workspace' for n in names) else 'Fixed')
        finally:self._syncing=False
        self.sync_input_visibility()
        if hasattr(self,'hub_settings'):self.hub_settings.sync(data)
        self.sync_objects(data)
        if 'policy' in data['inputs']:self.show_policy_model(data['inputs']['policy'])
        fn=data.get('functions',{}).get('acceptance',data.get('functions',{}).get('success',{}));self.task_info.setText('Task · '+str(fn.get('function',''))+' · '+str(fn.get('params',{})))
        self.invalidate();self.recipe_status.setText('저장됨 · '+Path(path).name);self.state.setText('저장됨 — 입력 검사를 실행하세요')
        if hasattr(self,'training_settings'):self.training_settings.load()
    def safe_update(self,fn):
        try:self.editor.update(fn);return True
        except Exception as error:self.edit_error=True;self.invalidate();self.state.setText('Recipe 편집 오류: '+str(error))
    def change_source_kind(self,index):
        live=index==1
        self.input_rows['source_dataset'].setVisible(not live);self.input_rows['device_profile'].setVisible(live)
        self.inputs['source_dataset'].setEnabled(not live);self.inputs['device_profile'].setEnabled(live)
        if not self._syncing and self.editor.path is not None:
            self.safe_update(lambda data:data['inputs'].pop('source_dataset' if live else 'device_profile',None))
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
        folder=QFileDialog.getExistingDirectory(self,'기존 Dataset 또는 새 Dataset의 상위 폴더',str(self.workspace/self.stage))
        if not folder:return
        target=Path(folder) if self.dataset_resume.isChecked() else Path(folder)/(self.stage+'-'+uuid.uuid4().hex[:8])
        self.output.setText(str(target));self.edit_output()
    def edit_dataset_resume(self,value):
        if self._syncing or self.editor.path is None:return
        def edit(data):
            data['execution']['resume']=value;data['execution']['num_episodes']=self.counts['num_episodes'].value();data['execution'].pop('episodes',None);data['execution'].pop('target_successes',None);data['inputs'].pop('resume_dataset',None)
        self.safe_update(edit)
        self.count_labels['num_episodes'].setText('추가 Episode 수')
    def edit_execution(self,key,value):
        if self._syncing or self.editor.path is None:return
        def edit(data):
            data['execution'][key]=value
            if key=='env_num':data['execution'].pop('num_envs',None)
            if key=='num_episodes':data['execution'].pop('episodes',None);data['execution'].pop('target_successes',None)
        self.safe_update(edit)
        if key=='env_num':self.preview_env.setRange(0,value-1);self.sync_input_visibility()
        if key=='num_episodes':self.count_labels[key].setText('추가 Episode 수')
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
    def edit_gripper_parameter(self,key,text):
        if self._syncing or self.editor.path is None:return
        try:
            if text:self.edit_execution(key,float(text) if key.endswith('_rad') else int(text))
            else:self.safe_update(lambda doc:doc['execution'].pop(key,None))
        except ValueError:self.invalidate();self.state.setText('명시 유한 rad Target / 양의 raw 변위 예산을 입력하세요')
    def approve_gripper(self):
        proposal=getattr(self,'gripper_proposal',None)
        if not proposal or not self.handle or not self.active():return
        message=f"Gripper motor6만 단일 명령: raw {proposal['current_raw']} → {proposal['target_raw']} (delta {proposal['raw_delta']})\n팔 5축 Goal/Torque 쓰기 없음. 로봇 옆에서 감독 중이며 손/물체/케이블이 없고 즉시 전원 차단할 수 있습니까?"
        if QMessageBox.question(self,'현장 Gripper 단일 동작 승인',message,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        text,ok=QInputDialog.getText(self,'적용 Target 확인','승인할 target raw 값을 그대로 입력하세요: '+str(proposal['target_raw']))
        if not ok or text.strip()!=str(proposal['target_raw']):return
        from ..robot.calibration import fingerprint
        from ..run import RunHandle,send_command
        h=self.handle
        receipt=send_command(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),{'command_id':uuid.uuid4().hex,'kind':'gripper_approve','payload':{'proposal_sha256':fingerprint(proposal),'target_raw':proposal['target_raw'],'supervised':True,'clear':True,'stop_ready':True}})
        self.gripper_button.setEnabled(False);self.log.appendPlainText('Gripper 승인 요청 '+receipt.status+' · 실제 ACK/feedback 확인 필요')
    def check_recipe(self):
        if self.busy:self.state.setText('현재 입력 작업 종료를 기다리세요');return
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
        if any(page is not self and page.active() for page in [*getattr(self.window(),'workflows',{}).values(),*getattr(self.window(),'sessions',{}).values()]):
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
            import hashlib
            try:current_sha=hashlib.sha256(self.editor.path.read_bytes()).hexdigest()if self.editor.path is not None else None
            except OSError as error:
                self.ready=None;self.start_button.setEnabled(False);self.state.setText('Recipe 재확인 실패: '+str(error));return
            if self.editor.dirty or current_sha!=data['recipe_sha256']:
                self.ready=None;self.start_button.setEnabled(False);self.recipe_status.setText('검사 중 편집됨 · 저장하고 다시 검사하세요');return
            self.ready=data if data['runnable'] and data['state']=='runtime_ready' else None
            self.state.setText(('입력 준비 완료 · ' if self.ready else 'Prepared · 실행 차단 · ')+data['reason']);self.start_button.setEnabled(self.ready is not None);self.recipe_status.setText('저장 입력 검사 통과'if self.ready else'검사 완료 · 실행 차단')
        elif self.operation=='terminal_hardware':
            self.dataset_state='실물 결과 재개방 확인 · 측정 frame '+str(data.get('frames',data.get('verified_capture_frames',0)));self.state.setText('측정 frame '+str(data.get('frames',data.get('verified_capture_frames',0)))+' · '+str(data.get('status'))+' · command_sent='+str(data.get('command_sent',False)))
            self.display_hardware_result(data)
            self.log.appendPlainText('결과: '+str(data.get('status'))+' · 측정 '+str(data.get('frames',0))+' frame · command_sent='+str(data.get('command_sent',False)))
            for kind,labels in (('real',self.previews),('sim',self.sim_previews)):
                for n,path in data.get('images',{}).get(kind,{}).items():
                    if n in labels:labels[n].setPixmap(QPixmap(path).scaled(640,480,Qt.AspectRatioMode.KeepAspectRatio))
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
                    if 'gripper_proposal'in payload.get('progress',{}):self.gripper_proposal=payload['progress']['gripper_proposal'];self.gripper_button.setEnabled(True)
                    if 'env_index' in payload:
                        if not hasattr(self,'env_contexts'):self.env_contexts={}
                        self.env_contexts[payload['env_index']]=payload
                if event['kind']=='command_ack':self.log.appendPlainText('실제 명령 ACK · '+json.dumps(payload,ensure_ascii=False))
                if event['kind']=='error':self.log.appendPlainText(json.dumps(payload,ensure_ascii=False))
            outcome=run_outcome({**record,'status':status.status});self.outcome=outcome
            terminal=outcome['worker_finished']or status.status=='unknown';self.progress_bar.setRange(0,1 if terminal else 0);self.progress_bar.setValue(1 if status.status=='completed'else 0);self.progress_bar.setFormat('Worker '+status.status)
            self.progress_text.setText('Episode '+str(outcome['completed_episodes'])+' · Attempt '+str(outcome['attempts']if outcome['attempts']is not None else'미집계')+' · Env '+str(self.context.get('env_index','—'))+' / tick '+str(self.context.get('tick','—'))+(' · 목표 미달'if outcome['goal_reached']is False else''))
            for kind,button in self.commands.items():button.setEnabled(not outcome['worker_finished'] and status.status!='unknown' and (kind!='step' or self.engine.currentText()!='isaaclab' or self.counts.get('env_num').value()==1) and (kind!='mark' or (self.mode.currentText()=='manual' and self.mark_frame.value()<=getattr(self,'env_contexts',{}).get(self.preview_env.value(),getattr(self,'context',{})).get('tick',-1))))
            if outcome['worker_finished'] or status.status=='unknown':
                self.cancel_button.setEnabled(False);self.gripper_button.setEnabled(False)
                if status.status=='unknown' and self.handle['run_dir'] in self.owned_runs:
                    import shutil
                    shutil.rmtree(Path(self.handle['run_dir'])/'preview',ignore_errors=True)
                if (self.stage in ('source','annotation','datagen','simulation_evaluation') or self.stage in ('teleoperation','real_evaluation') and (Path(self.handle['output_path'])/'run.json').is_file()) and getattr(self,'_verified_terminal',None)!=self.handle['run_id'] and not self.busy:
                    self._verified_terminal=self.handle['run_id'];self.operation='terminal_catalog';self.busy=True;self.job.start('catalog',path=self.handle['output_path'])
                if self.stage in ('real_evaluation','teleoperation') and getattr(self,'_verified_terminal',None)!=self.handle['run_id'] and not self.busy and any((Path(self.handle['output_path'])/name).is_file()for name in ('hardware-report.json','gripper-report.json')):
                    self._verified_terminal=self.handle['run_id'];self.operation='terminal_hardware';self.busy=True;self.job.start('hardware_result',path=self.handle['output_path'])
                if getattr(self,'_preview_terminal_cleared',None)!=self.handle['run_id']:
                    for name,label in self.previews.items():label.clear();label.setText(name+' · Live Preview 종료')
                    self._preview_terminal_cleared=self.handle['run_id']
                self.resume_button.setVisible(bool(outcome['needs_resume']))
                text='Worker '+status.status+' · '+self.dataset_state+' · 완료 Episode '+str(outcome['completed_episodes'])
                if outcome.get('existing_episodes') is not None:text+=' · 기존 '+str(outcome['existing_episodes'])+' / 추가 '+str(outcome['added_episodes'])
                if outcome['goal_reached'] is False:text+=' · 목표 미달'
                if outcome['needs_resume']:text+=' · 새 worker에서 기존 Dataset 추가 저장 필요'
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
        # Reopened legacy runs still use the current explicit append contract.
        # Preparation may reject a changed historical identity; never copy/repair it.
        def append(data):
            data['inputs'].pop('resume_dataset',None)
            data['execution'].update(resume=True,num_episodes=self.counts['num_episodes'].value())
            data['execution'].pop('target_successes',None)
            data['output']['directory']=self.handle['output_path']
        if self.safe_update(append):
            self.count_labels['num_episodes'].setText('추가 Episode 수')
            self.output.setText(self.handle['output_path']);self._syncing=True
            try:self.dataset_resume.setChecked(True)
            finally:self._syncing=False
            self.state.setText('기존 Dataset 추가 저장 Recipe 편집 중 · 추가 Episode/Attempt 예산을 확인하고 저장·검사하세요')
    def show_training_result(self):
        path=Path(self.handle['output_path'])/'training-result.json'
        if path.is_file() and getattr(self,'_shown_training',None)!=str(path):
            result=json.loads(path.read_text());self.log.appendPlainText(json.dumps({'loss':result['metrics'],'checkpoints':result['checkpoints']},ensure_ascii=False));self._shown_training=str(path)
