"""Scene/engine selection, supervised Leader control and measured Follower→Sim views."""
from pathlib import Path
import time,uuid,yaml
from PyQt6.QtGui import QImage,QPixmap
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QComboBox,QPlainTextEdit
from .jobs import BackendJob
from .session_client import SessionClient
from .snapshot_table import SnapshotTable
from .view import CameraView


class RealSimPage(QWidget):
    def __init__(self,python,modules,workspace,parent=None):
        super().__init__(parent);self.workspace=Path(workspace);self.template=None;self.project=None;self.last_progress={};self.request_control=False;self.selection_key=None;self.recipe_path=None
        self.client=SessionClient(python,modules,self);self.client.progress.connect(self.update_progress);self.client.preview.connect(self.show_preview);self.client.error.connect(self.show_error);self.client.received.connect(self.event_received);self.client.terminal.connect(self.ended)
        self.job=BackendJob(python,self);self.job.finished.connect(self.loaded);self.job.log.connect(self.show_error);self.job.process.stateChanged.connect(lambda _:self.buttons())
        box=QVBoxLayout(self);title=QLabel('2. Real / Sim');title.setObjectName('dashboardTitle');box.addWidget(title)
        hint=QLabel('Follower 측정값을 Sim의 목표 관절값으로 사용합니다. Sim은 중력·충돌을 계산하므로 실제 자세와 차이가 날 수 있습니다. 중단하면 새 모터 목표 전송을 멈춥니다.');hint.setWordWrap(True);box.addWidget(hint)
        selection=QHBoxLayout();box.addLayout(selection);selection.addWidget(QLabel('Scene'));self.scene_combo=QComboBox();selection.addWidget(self.scene_combo,1)
        selection.addWidget(QLabel('Simulation'));self.engine=QComboBox();self.engine.addItem('MuJoCo','mujoco');self.engine.addItem('Isaac Lab','isaaclab');selection.addWidget(self.engine)
        self.scene_combo.currentIndexChanged.connect(self.load_selected);self.engine.currentIndexChanged.connect(self.load_selected)
        self.state=QLabel('DISCONNECTED');box.addWidget(self.state);grid=QGridLayout();box.addLayout(grid,4);self.previews={};self.camera_labels={}
        for i,name in enumerate(('side','sim_side','wrist','sim_wrist')):
            panel=QWidget();panel.setObjectName('previewCard');layout=QVBoxLayout(panel);layout.setContentsMargins(4,4,4,4)
            label=QLabel(('SIM 'if name.startswith('sim_')else'REAL ')+name.removeprefix('sim_').upper()+' · 연결 대기');layout.addWidget(label)
            view=CameraView('영상 없음',(120,75));layout.addWidget(view,1);grid.addWidget(panel,i//2,i%2);self.previews[name]=view;self.camera_labels[name]=label
        self.measured=QLabel('Follower 측정값 (rad) · —');box.addWidget(self.measured)
        self.simulated=QLabel('Sim 관절값 (rad) · —');self.simulated.setWordWrap(True);box.addWidget(self.simulated)
        actions=QHBoxLayout();box.addLayout(actions);self.connect_button=QPushButton('Real/Sim 연결 · Teleop');self.capture_button=QPushButton('Capture');self.stop_button=QPushButton('중단')
        self.connect_button.setObjectName('primaryAction');self.capture_button.setObjectName('primaryAction');self.stop_button.setObjectName('stopAction')
        for b in(self.connect_button,self.capture_button,self.stop_button):actions.addWidget(b,1)
        self.connect_button.clicked.connect(self.connect_session);self.capture_button.clicked.connect(lambda:self.send('session_snapshot'));self.stop_button.clicked.connect(self.cancel_run)
        self.capture_hint=QLabel('Scene과 엔진을 선택하세요.');self.capture_hint.setWordWrap(True);box.addWidget(self.capture_hint)
        self.operation_message=QLabel();self.operation_message.setWordWrap(True);box.addWidget(self.operation_message);self.operation_message.hide()
        box.addWidget(QLabel('이번 실행의 Paired Capture · Real Side / Sim Side / Real Wrist / Sim Wrist'))
        self.run_folder=QLabel();self.run_folder.setWordWrap(True);self.run_folder.hide();box.addWidget(self.run_folder)
        self.snapshot_table=SnapshotTable(paired=True,parent=self);self.snapshot_table.error.connect(self.show_error);box.addWidget(self.snapshot_table,1)
        self.refit_button=QPushButton('촬영 자료로 Scene 재정합');self.refit_button.clicked.connect(self.open_refinement);box.addWidget(self.refit_button)
        self.log=QPlainTextEdit();self.log.hide();box.addWidget(self.log);self.buttons()
        self.catalog_signature=None;self.catalog_timer=QTimer(self);self.catalog_timer.setInterval(1500);self.catalog_timer.timeout.connect(self.refresh_scenes);self.catalog_timer.start()
        self.refresh_scenes()
    def open_refinement(self):
        if self.active()or not self.project:return
        from real2sim_builder.ui_reconstruction import ReconstructionDialog
        dialog=ReconstructionDialog(self.project['project'],self.job.python,self,refit=True)
        dialog.exec()
    @property
    def rows(self):return self.snapshot_table.rows
    def active(self):return self.client.active()
    def stop_timers(self):self.client.timer.stop();self.catalog_timer.stop()
    def refresh_scenes(self,force=False):
        from PyQt6.QtCore import QProcess
        if self.active()or self.job.process.state()!=QProcess.ProcessState.NotRunning:return
        signature=tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size)for p in sorted((self.workspace/'scenes').glob('*/project.yaml')))
        if not force and signature==self.catalog_signature:return
        self.catalog_signature=signature
        if signature or self.scene_combo.count():self.job.start('session_execution_scenes',workspace=str(self.workspace))
    def showEvent(self,event):
        super().showEvent(event)
        if hasattr(self,'catalog_timer'):self.refresh_scenes(force=True)
    def buttons(self):
        from PyQt6.QtCore import QProcess
        idle=not self.active()and self.job.process.state()==QProcess.ProcessState.NotRunning
        ready=self.client.running and not self.client.cancel_requested and self.last_progress.get('session_state')=='OBSERVING'and self.last_progress.get('teleoperation_available',False)
        self.scene_combo.setEnabled(idle);self.engine.setEnabled(idle);self.connect_button.setEnabled(idle and self.template is not None or bool(ready))
        if hasattr(self,'refit_button'):self.refit_button.setEnabled(idle and self.project is not None)
        self.connect_button.setText('Teleoperation 시작'if ready else'Real/Sim 연결 · Teleop')
        self.capture_button.setEnabled(self.client.running and not self.client.cancel_requested and self.last_progress.get('capture_request_allowed',False))
        self.capture_button.setText('Capture 처리 중…'if self.last_progress.get('capture_pending')else'Capture');self.stop_button.setEnabled(self.active())
    def load_selected(self):
        if self.active():return
        self.template=None;self.project=None;self.last_progress={};self.buttons();row=self.scene_combo.currentData()
        if not row:
            self.selection_key=None;self.snapshot_table.reset();self.run_folder.hide();return
        if row:
            allowed=row.get('engines',[])
            self.engine.blockSignals(True)
            for i in range(self.engine.count()):self.engine.model().item(i).setEnabled(('isaac'if self.engine.itemData(i)=='isaaclab'else self.engine.itemData(i))in allowed)
            if ('isaac'if self.engine.currentData()=='isaaclab'else self.engine.currentData())not in allowed:
                self.engine.setCurrentIndex(next((i for i in range(self.engine.count())if self.engine.model().item(i).isEnabled()),-1))
            self.engine.blockSignals(False)
            if self.engine.currentIndex()<0:self.capture_hint.setText('등록된 엔진 설정이 없습니다.');return
            selection=(row['scene'],self.engine.currentData())
            if selection!=self.selection_key:self.snapshot_table.reset();self.run_folder.hide()
            self.selection_key=selection
            self.job.start('session_real_setup',workspace=str(self.workspace),project=row['project'],scene=row['scene'],engine=self.engine.currentData())
    def loaded(self,response):
        if not response.get('ok'):self.show_error(response.get('error',{}).get('message','Scene 설정 오류'));self.buttons();return
        result=response['result']
        if 'scenes'in result:
            selected=self.scene_combo.currentData();selected=selected['scene']if selected else None
            self.scene_combo.blockSignals(True);self.scene_combo.clear()
            for row in result['scenes']:self.scene_combo.addItem(row['name']+' · '+row['revision']+' · '+row['project_id']+' / '+', '.join(row['engines']),row)
            if selected:
                for i in range(self.scene_combo.count()):
                    if self.scene_combo.itemData(i)['scene']==selected:self.scene_combo.setCurrentIndex(i);break
            self.scene_combo.blockSignals(False)
            self.load_selected()
            if not self.scene_combo.currentData():self.capture_hint.setText('등록된 실행 Scene이 없습니다. Builder에서 Scene Package를 준비하세요.')
        else:
            self.template=result['recipe'];self.project={'project':result['project'],'name':result['name']}
            self.capture_hint.setText('연결할 준비가 되었습니다.');self.capture_hint.show();self.operation_message.hide();self.buttons()
    def connect_session(self):
        try:
            if self.client.running:self.start_teleoperation();return
            if any(p is not self and p.active()for p in getattr(self.window(),'sessions',{}).values())or any(p.active()for p in getattr(self.window(),'workflows',{}).values()):raise ValueError('다른 장치/Simulation Session을 먼저 중단하세요.')
            if self.template is None:raise ValueError('실행 Scene을 선택하세요.')
            import copy
            data=copy.deepcopy(self.template);self.request_control='leader_device_profile'in data['inputs']
            key='real_sim_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6];root=self.workspace/'real_sim';root.mkdir(parents=True,exist_ok=True)
            data['output']={'directory':str(root/key)};path=root/(key+'.yaml');path.write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
            self.last_progress={};self.operation_message.hide();self.recipe_path=path;self.client.connect_session(path);self.snapshot_table.reset();self.run_folder.hide()
            self.state.setText('CONNECTING · Scene/Follower/Camera 준비 중');self.buttons()
        except Exception as error:self.show_error(str(error))
    def send(self,kind,payload=None):
        try:self.operation_message.hide();self.client.send(kind,payload)
        except Exception as error:self.show_error(str(error))
    def start_teleoperation(self):
        if self.isVisible():self.send('teleop_start')
    def cancel_run(self):
        self.request_control=False
        self.client.cancel();self.buttons()
    def update_progress(self,progress):
        self.last_progress.update(progress);p=self.last_progress;self.state.setText(('MEMORY · 합성 시험 / 'if p.get('device_source')=='memory'else'')+p.get('session_state','CONNECTING'));self.buttons()
        self.capture_hint.show();self.capture_hint.setText('캡처 중…'if p.get('capture_pending')else'연결 중…'if p.get('session_state')=='CONNECTING'else'멈추면 캡처할 수 있습니다.')
        self.capture_hint.setToolTip(p.get('capture_reason',''))
        if p.get('q_measured'):self.measured.setText('Follower 측정값 (rad) · '+', '.join(f'{q:.4f}'for q in p['q_measured']))
        if p.get('simulation'):
            simulation=p['simulation'];delta=max(abs(q)for q in simulation['sim_joint_delta_rad'])
            self.simulated.setText('Sim 관절값 (rad) · '+', '.join(f'{q:.4f}'for q in simulation['applied_sim_joint_rad'])+f' · 최대 추종 차이 {delta:.4f}rad')
        for n,timing in p.get('camera_timing',{}).items():
            if timing:self.camera_labels[n].setText(('MEMORY 'if p.get('device_source')=='memory'else'REAL ')+n.upper()+f" · {timing.get('received_fps',0)or 0:.1f}FPS · age {timing['age_ms']:.0f}ms · Δt {timing['joint_skew_ms']:.0f}ms")
        if p.get('render_timing'):
            for n in('sim_side','sim_wrist'):self.camera_labels[n].setText('SIM '+n[4:].upper()+f" · render {p['render_timing']['render_ms']:.0f}ms · age {p['render_timing']['age_ms']:.0f}ms")
        if progress.get('snapshot'):
            snapshot=progress['snapshot'];self.snapshot_table.append(snapshot)
            folder=Path(snapshot['path']).parent
            self.run_folder.setText('Capture 저장 폴더 · '+folder.name);self.run_folder.setToolTip(str(folder));self.run_folder.show()
        if progress.get('error'):self.show_error(progress['error'])
        if self.request_control and p.get('session_state')=='OBSERVING'and p.get('teleoperation_available'):
            self.request_control=False;self.send('teleop_start')
    def event_received(self,event):
        if event['kind']=='error'or event['kind']=='command_ack'and event['payload'].get('status')=='rejected':self.show_error(event['payload'].get('reason')or event['payload'].get('message')or str(event['payload']))
    def show_preview(self,name,raw):
        if name in self.previews:
            image=QImage.fromData(raw,b'PPM')
            if not image.isNull():self.previews[name].setPixmap(QPixmap.fromImage(image))
    def show_error(self,message):self.log.appendPlainText(message);self.operation_message.setText(message);self.operation_message.show()
    def ended(self,status):
        self.request_control=False
        handle=self.client.handle
        if status in('completed','cancelled')and handle and self.recipe_path and self.recipe_path.stem==Path(handle['output_path']).name and not Path(handle['output_path']).exists():
            try:self.recipe_path.unlink(missing_ok=True)
            except OSError as error:self.show_error('임시 연결 설정 정리 실패: '+str(error))
            self.run_folder.hide();self.operation_message.setText('Capture 없이 종료했습니다. 저장한 촬영 결과는 없습니다.');self.operation_message.show()
        self.last_progress={};self.state.setText('DISCONNECTED · '+status);self.capture_hint.hide();self.buttons()
        self.simulated.setText('Sim 관절값 (rad) · —')
        for name,view in self.previews.items():view.clear();view.setText('연결 종료');self.camera_labels[name].setText(('SIM 'if name.startswith('sim_')else'REAL ')+name.removeprefix('sim_').upper()+' · 연결 종료')
    def hideEvent(self,event):
        self.request_control=False
        if self.client.running:self.send('teleop_stop')
        super().hideEvent(event)
