"""Scene/engine selection and passive Follower→Sim observation, no authoring/control UI."""
from pathlib import Path
import time,uuid,yaml
from PyQt6.QtGui import QImage,QPixmap
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QComboBox,QPlainTextEdit
from .jobs import BackendJob
from .session_client import SessionClient
from .snapshot_table import SnapshotTable
from .view import CameraView


class RealSimPage(QWidget):
    def __init__(self,python,modules,workspace,parent=None):
        super().__init__(parent);self.workspace=Path(workspace);self.template=None;self.project=None;self.last_progress={}
        self.client=SessionClient(python,modules,self);self.client.progress.connect(self.update_progress);self.client.preview.connect(self.show_preview);self.client.error.connect(self.show_error);self.client.received.connect(self.event_received);self.client.terminal.connect(self.ended)
        self.job=BackendJob(python,self);self.job.finished.connect(self.loaded);self.job.log.connect(self.show_error);self.job.process.stateChanged.connect(lambda _:self.buttons())
        box=QVBoxLayout(self);title=QLabel('2. Real / Sim');title.setObjectName('dashboardTitle');box.addWidget(title)
        hint=QLabel('Follower를 손으로 움직이면 측정 관절값을 선택한 Scene에 반영합니다. 실물 모터 명령은 보내지 않습니다.');hint.setWordWrap(True);box.addWidget(hint)
        selection=QHBoxLayout();box.addLayout(selection);selection.addWidget(QLabel('Scene'));self.scene_combo=QComboBox();selection.addWidget(self.scene_combo,1)
        selection.addWidget(QLabel('Simulation'));self.engine=QComboBox();self.engine.addItem('MuJoCo','mujoco');self.engine.addItem('Isaac Lab','isaaclab');selection.addWidget(self.engine)
        self.scene_combo.currentIndexChanged.connect(self.load_selected);self.engine.currentIndexChanged.connect(self.load_selected)
        self.state=QLabel('DISCONNECTED');box.addWidget(self.state);grid=QGridLayout();box.addLayout(grid,4);self.previews={};self.camera_labels={}
        for i,name in enumerate(('side','sim_side','wrist','sim_wrist')):
            panel=QWidget();panel.setObjectName('previewCard');layout=QVBoxLayout(panel);layout.setContentsMargins(4,4,4,4)
            label=QLabel(('SIM 'if name.startswith('sim_')else'REAL ')+name.removeprefix('sim_').upper()+' · 연결 대기');layout.addWidget(label)
            view=CameraView('영상 없음',(120,75));layout.addWidget(view,1);grid.addWidget(panel,i//2,i%2);self.previews[name]=view;self.camera_labels[name]=label
        self.measured=QLabel('Follower 측정값 (rad) · —');box.addWidget(self.measured)
        actions=QHBoxLayout();box.addLayout(actions);self.connect_button=QPushButton('Real/Sim 연결');self.capture_button=QPushButton('Capture');self.stop_button=QPushButton('중단')
        self.connect_button.setObjectName('primaryAction');self.capture_button.setObjectName('primaryAction');self.stop_button.setObjectName('stopAction')
        for b in(self.connect_button,self.capture_button,self.stop_button):actions.addWidget(b,1)
        self.connect_button.clicked.connect(self.connect_session);self.capture_button.clicked.connect(lambda:self.send('session_snapshot'));self.stop_button.clicked.connect(self.cancel_run)
        self.capture_hint=QLabel('Scene과 엔진을 선택하세요.');self.capture_hint.setWordWrap(True);box.addWidget(self.capture_hint)
        self.operation_message=QLabel();self.operation_message.setWordWrap(True);box.addWidget(self.operation_message);self.operation_message.hide()
        box.addWidget(QLabel('Paired Capture · Real Side / Sim Side / Real Wrist / Sim Wrist'))
        self.snapshot_table=SnapshotTable(paired=True,parent=self);self.snapshot_table.error.connect(self.show_error);box.addWidget(self.snapshot_table,1)
        self.log=QPlainTextEdit();self.log.hide();box.addWidget(self.log);self.buttons()
        if any((self.workspace/'scenes').glob('*/project.yaml')):self.job.start('session_execution_scenes',workspace=str(self.workspace))
    @property
    def rows(self):return self.snapshot_table.rows
    def active(self):return self.client.active()
    def stop_timers(self):self.client.timer.stop()
    def buttons(self):
        from PyQt6.QtCore import QProcess
        idle=not self.active()and self.job.process.state()==QProcess.ProcessState.NotRunning
        self.scene_combo.setEnabled(idle);self.engine.setEnabled(idle);self.connect_button.setEnabled(idle and self.template is not None)
        self.capture_button.setEnabled(self.client.running and not self.client.cancel_requested and self.last_progress.get('capture_request_allowed',False))
        self.capture_button.setText('Capture 처리 중…'if self.last_progress.get('capture_pending')else'Capture');self.stop_button.setEnabled(self.active())
    def load_selected(self):
        if self.active():return
        self.template=None;self.project=None;self.last_progress={};self.snapshot_table.reset();self.buttons();row=self.scene_combo.currentData()
        if row:self.job.start('session_real_setup',workspace=str(self.workspace),project=row['project'],scene=row['scene'],engine=self.engine.currentData())
    def loaded(self,response):
        if not response.get('ok'):self.show_error(response.get('error',{}).get('message','Scene 설정 오류'));self.buttons();return
        result=response['result']
        if 'scenes'in result:
            self.scene_combo.blockSignals(True);self.scene_combo.clear()
            for row in result['scenes']:self.scene_combo.addItem(row['name']+' · '+row['revision'],row)
            self.scene_combo.blockSignals(False)
            if self.scene_combo.currentData():self.load_selected()
            else:self.capture_hint.setText('등록된 실행 Scene이 없습니다. Builder에서 Scene Package를 준비하세요.')
        else:
            self.template=result['recipe'];self.project={'project':result['project'],'name':result['name']};self.snapshot_table.reset()
            for row in result['snapshots']:self.snapshot_table.append(row)
            self.capture_hint.setText('Scene·Follower·Camera 설정 복원 완료 · 연결 시 identity를 다시 검사합니다.');self.operation_message.hide();self.buttons()
    def connect_session(self):
        try:
            if any(p is not self and p.active()for p in getattr(self.window(),'sessions',{}).values())or any(p.active()for p in getattr(self.window(),'workflows',{}).values()):raise ValueError('다른 장치/Simulation Session을 먼저 중단하세요.')
            if self.template is None:raise ValueError('실행 Scene을 선택하세요.')
            import copy
            data=copy.deepcopy(self.template);key='real_sim_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6];root=self.workspace/'real_sim';root.mkdir(parents=True,exist_ok=True)
            data['output']={'directory':str(root/key)};path=root/(key+'.yaml');path.write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
            self.last_progress={};self.operation_message.hide();self.client.connect_session(path);self.state.setText('CONNECTING · Scene/Follower/Camera 준비 중');self.buttons()
        except Exception as error:self.show_error(str(error))
    def send(self,kind):
        try:self.operation_message.hide();self.client.send(kind)
        except Exception as error:self.show_error(str(error))
    def cancel_run(self):self.client.cancel();self.buttons()
    def update_progress(self,progress):
        self.last_progress.update(progress);p=self.last_progress;self.state.setText(('MEMORY · 합성 시험 / 'if p.get('device_source')=='memory'else'')+p.get('session_state','CONNECTING'));self.buttons()
        self.capture_hint.setText(p.get('capture_reason','실제 관측과 Scene 렌더를 기다립니다.'))
        if p.get('q_measured'):self.measured.setText('Follower 측정값 (rad) · '+', '.join(f'{q:.4f}'for q in p['q_measured']))
        for n,timing in p.get('camera_timing',{}).items():
            if timing:self.camera_labels[n].setText(('MEMORY 'if p.get('device_source')=='memory'else'REAL ')+n.upper()+f" · {timing.get('received_fps',0)or 0:.1f}FPS · age {timing['age_ms']:.0f}ms · Δt {timing['joint_skew_ms']:.0f}ms")
        if p.get('render_timing'):
            for n in('sim_side','sim_wrist'):self.camera_labels[n].setText('SIM '+n[4:].upper()+f" · render {p['render_timing']['render_ms']:.0f}ms · age {p['render_timing']['age_ms']:.0f}ms")
        if progress.get('snapshot'):self.snapshot_table.append(progress['snapshot'])
        if progress.get('error'):self.show_error(progress['error'])
    def event_received(self,event):
        if event['kind']=='error'or event['kind']=='command_ack'and event['payload'].get('status')=='rejected':self.show_error(event['payload'].get('reason')or event['payload'].get('message')or str(event['payload']))
    def show_preview(self,name,raw):
        if name in self.previews:
            image=QImage.fromData(raw,b'PPM')
            if not image.isNull():self.previews[name].setPixmap(QPixmap.fromImage(image))
    def show_error(self,message):self.log.appendPlainText(message);self.operation_message.setText(message);self.operation_message.show()
    def ended(self,status):
        self.last_progress={};self.state.setText('DISCONNECTED · '+status);self.capture_hint.setText('Real/Sim 연결 종료 · 저장된 Capture는 보존됩니다.');self.buttons()
        for name,view in self.previews.items():view.clear();view.setText('연결 종료');self.camera_labels[name].setText(('SIM 'if name.startswith('sim_')else'REAL ')+name.removeprefix('sim_').upper()+' · 연결 종료')
