"""Workbench stage pages; Builder remains an independent application."""
import argparse,json,sys
from pathlib import Path
from PyQt6.QtCore import QProcess,QProcessEnvironment,QTimer,Qt
from PyQt6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QListWidget,QStackedWidget,QPushButton,QLabel,QFileDialog,QLineEdit,QPlainTextEdit,QInputDialog,QTabWidget,QComboBox,QGridLayout,QDialog
from .jobs import BackendJob
from .workflow import WorkflowPage
from .curation import CurationPage


class ScenePage(QWidget):
    def __init__(self,python,workspace,parent=None):
        super().__init__(parent);self.python=python;self.workspace=Path(workspace);self.scene_path=None;self.builder_project=None;self.valid=False
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Scene · 기존 패키지 검사 / 독립 Builder 연결'))
        self.path=QLineEdit();self.path.setReadOnly(True);layout.addWidget(self.path);row=QGridLayout();layout.addLayout(row)
        for i,(text,fn) in enumerate([('Scene Package 선택',self.choose_scene),('Manifest·Calibration·Model 검사',self.inspect),('Builder Project 선택',self.choose_project),('기존 Builder 열기',self.open_builder),('Workspace Builder 열기',self.open_workspace_builder),('수평 기준 검사 (선택)',self.horizontal)]):
            button=QPushButton(text);button.clicked.connect(fn);row.addWidget(button,i//3,i%3)
        self.state=QLabel('기존 Scene을 선택하세요. v9 생성/실물 Calibration은 자동 실행하지 않습니다.');self.state.setWordWrap(True);layout.addWidget(self.state)
        self.info=QPlainTextEdit();self.info.setReadOnly(True);layout.addWidget(self.info)
        self.job=BackendJob(python,self);self.job.finished.connect(self.finished);self.job.log.connect(self.info.appendPlainText)
        self.builder=QProcess(self);self.builder.readyReadStandardError.connect(lambda:self.info.appendPlainText(bytes(self.builder.readAllStandardError()).decode(errors='replace')))
    def choose_scene(self):
        path,_=QFileDialog.getOpenFileName(self,'기존 Scene scene.json',str(self.workspace/'scenes'),'JSON (*.json)')
        if path:self.select_scene(path)
    def select_scene(self,path):
        self.scene_path=str(Path(path).resolve());self.path.setText(self.scene_path);self.valid=False;self.state.setText('선택됨 · 검사를 실행하세요')
    def inspect(self):
        if not self.scene_path:self.state.setText('먼저 scene.json을 선택하세요');return
        self.operation='scene';self.valid=False;self.state.setText('Scene 파일·보정 선언·모델 무결성 검사 중…');self.job.start('scene',path=self.scene_path)
    def finished(self,result):
        if not result.get('ok'):self.state.setText(result.get('error',{}).get('message','Scene 오류'));return
        data=result['result']
        if getattr(self,'operation',None)=='horizontal':
            self.info.setPlainText(json.dumps(data,ensure_ascii=False,indent=2));self.state.setText('선택적 Geometry 검사 결과 · Calibration 완료가 아닙니다');return
        if data['path']!=self.scene_path:return
        self.valid=True;identity=data['identity'];self.state.setText('유효한 Scene · '+identity['scene_id']+' / '+identity['revision'])
        self.info.setPlainText(json.dumps({'objects':data['objects'],'engines':data['engines'],'calibration_records':data['calibration_records'],'joint_order':data['robot_model'],
            'scope':'파일/선언 검증이며 실물 Calibration·모든 엔진 실행 동등성을 승인하지 않습니다'},ensure_ascii=False,indent=2))
    def horizontal(self):
        if self.builder_project is None:self.state.setText('기존 Builder Project를 선택하세요');return
        text,ok=QInputDialog.getText(self,'수평 기준 검사','실제 Object ID: table, workspace, block1, block2, ...')
        if not ok:return
        ids=[s.strip() for s in text.split(',') if s.strip()]
        if len(ids)<3:self.state.setText('Table/Workspace/Block의 실제 ID를 지정하세요');return
        self.operation='horizontal';self.job.start('horizontal',project=str(self.builder_project),table=ids[0],workspace=ids[1],blocks=ids[2:])
    def choose_project(self):
        path=QFileDialog.getExistingDirectory(self,'기존 Builder Project 선택',str(self.workspace/'scenes'))
        if path:self.builder_project=Path(path);self.state.setText('Builder Project 선택됨 · '+path)
    def open_builder(self):
        if self.builder.state()!=QProcess.ProcessState.NotRunning:self.state.setText('이미 Builder가 실행 중입니다');return
        if self.builder_project is None:self.state.setText('기존 Builder Project를 선택하세요');return
        self.start_builder(self.builder_project.parent)
    def open_workspace_builder(self):
        if self.builder.state()!=QProcess.ProcessState.NotRunning:self.state.setText('이미 Builder가 실행 중입니다');return
        self.start_builder(self.workspace/'scenes')
    def start_builder(self,projects):
        environment=QProcessEnvironment.systemEnvironment();environment.insert('REAL2SIM_WORKER_PYTHON',self.python);self.builder.setProcessEnvironment(environment)
        self.builder.start(sys.executable,['-B','-m','real2sim_builder.cli','ui','--projects',str(projects)])
        self.state.setText('독립 Builder 실행 요청 · 새 Export 결과를 Scene Package 선택으로 다시 여세요')


class Window(QMainWindow):
    def __init__(self,backend_python,modules,workspace):
        super().__init__()
        from .theme import STYLE
        from .paths import GROUPS
        self.setStyleSheet(STYLE);self.setWindowTitle('Real2Sim Learning Studio');self.resize(1320,900);self.workspace=Path(workspace).resolve();self.workspace.mkdir(parents=True,exist_ok=True)
        for folder in set(GROUPS.values()):(self.workspace/folder).mkdir(exist_ok=True)
        self.closing=False;self.cancelled_on_close=set()
        central=QWidget();self.setCentralWidget(central);layout=QVBoxLayout(central)
        self.safety=QLabel('실물 팔 Goal/Torque 금지 · 읽기 전용 / Gripper 별도 승인 · 저장 Recipe만 실행');self.safety.setWordWrap(True);layout.addWidget(self.safety)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.scene=ScenePage(backend_python,self.workspace,self);self.source=CurationPage(backend_python,self.workspace,self,source_only=True);self.curation=CurationPage(backend_python,self.workspace,self)
        self.workflows={stage:WorkflowPage(stage,backend_python,modules,self)for stage in ('teleoperation','source','annotation','datagen','train','simulation_evaluation','offline_validation','hub_download','hub_upload','capture','precision_calibration','real_evaluation','real_sim')}
        self.source_tabs=QTabWidget();self.source_tabs.addTab(self.workflows['source'],'Simulation Source 수집');self.source_tabs.addTab(self.source,'저장 Source 검토')
        self.pipeline=QWidget();outer=QVBoxLayout(self.pipeline);outer.setContentsMargins(12,12,12,12);outer.setSpacing(16)
        header=QWidget();header.setObjectName('dashboardHeader');header_layout=QHBoxLayout(header);title_box=QVBoxLayout();brand=QLabel('SO-101  /  WORKSPACE');brand.setObjectName('eyebrow');title_box.addWidget(brand)
        self.dashboard_title=QLabel('Source Demo');self.dashboard_title.setObjectName('dashboardTitle');title_box.addWidget(self.dashboard_title);header_layout.addLayout(title_box,1)
        self.engine_stack=QStackedWidget();self.engine_stack.setMaximumWidth(180);self.engine_stack.setMaximumHeight(50);header_layout.addWidget(self.engine_stack)
        self.settings_toggle=QPushButton('실행 설정');self.settings_toggle.setCheckable(True);self.settings_toggle.setChecked(True);self.settings_toggle.toggled.connect(self.toggle_settings);header_layout.addWidget(self.settings_toggle);outer.addWidget(header)
        body=QHBoxLayout();body.setSpacing(16);outer.addLayout(body,1)
        self.navigation_panel=QWidget();self.navigation_panel.setObjectName('navigationPanel');self.navigation_panel.setFixedWidth(200);nav=QVBoxLayout(self.navigation_panel);label=QLabel('WORKFLOW');label.setObjectName('eyebrow');nav.addWidget(label)
        self.section=QComboBox();self.section.addItems(['Sim 작업 파이프라인','실물 읽기 / Teleoperation']);nav.addWidget(self.section)
        self.navigation=QListWidget();self.navigation.setObjectName('stageNavigation');nav.addWidget(self.navigation,1)
        curate=QPushButton('Data Curation');curate.clicked.connect(lambda:self.navigation.setCurrentRow(5));nav.addWidget(curate)
        hint=QLabel('단계를 선택하고\n입력을 확인한 뒤 실행하세요.');hint.setObjectName('mutedLabel');hint.setWordWrap(True);nav.addWidget(hint);body.addWidget(self.navigation_panel)
        self.stack=QStackedWidget();body.addWidget(self.stack,1)
        self.pages=[('Scene',self.scene),('Source Demo',self.source_tabs),('Teleoperation',self.workflows['teleoperation']),('Annotation',self.workflows['annotation']),('Mimic / Datagen',self.workflows['datagen']),('Data Curation',self.curation),('모델 학습',self.workflows['train']),('Sim 평가',self.workflows['simulation_evaluation']),('Offline Validation',self.workflows['offline_validation']),('Hub 다운로드',self.workflows['hub_download']),('Hub 업로드',self.workflows['hub_upload']),('Capture',self.workflows['capture']),('Precision Calibration',self.workflows['precision_calibration']),('Real Policy · Observe Only',self.workflows['real_evaluation']),('Real / Sim',self.workflows['real_sim'])]
        self.hardware_tabs={11:0,14:1,12:3};self._last_pipeline_row=1
        for i,(name,page)in enumerate(self.pages):
            self.navigation.addItem(f'{i+1:02d}  {name}');self.stack.addWidget(QWidget()if i in self.hardware_tabs or i==5 else page)
            engine=page.engine if isinstance(page,WorkflowPage)else self.workflows['source'].engine if page is self.source_tabs else QWidget()
            if page is self.source_tabs or isinstance(page,WorkflowPage)and page.stage in ('source','annotation','datagen','simulation_evaluation'):
                engine.parentWidget().hide()
            self.engine_stack.addWidget(engine if i not in self.hardware_tabs else QWidget())
        self.curation_dialog=QDialog(self);self.curation_dialog.setWindowTitle('Data Curation · Episode 검토');self.curation_dialog.resize(1400,920);self.curation_dialog.setWindowModality(Qt.WindowModality.WindowModal);QVBoxLayout(self.curation_dialog).addWidget(self.curation)
        self.tabs.addTab(self.workflows['capture'],'1 · Real2Sim Capture');self.tabs.addTab(self.workflows['real_sim'],'2 · Real / Sim');self.tabs.addTab(self.pipeline,'3 · Workspace Pipeline');self.tabs.addTab(self.workflows['precision_calibration'],'4 · Precision Calibration')
        self.navigation.currentRowChanged.connect(self.select_stage);self.section.currentIndexChanged.connect(self.change_section);self.change_section(0);self.navigation.setCurrentRow(1)
        self.tabs.setCurrentIndex(0)
        self.statusBar().showMessage('Scene v8 원본 보존 · 실제 모터 구동 기본 차단 · Hub 쓰기 별도 승인')

    def change_section(self,index):
        allowed={0,1,3,4,6,7,8,9,10}if index==0 else{2,11,12,13,14}
        for i in range(self.navigation.count()):self.navigation.item(i).setHidden(i not in allowed)
        if self.navigation.currentRow()not in allowed:self.navigation.setCurrentRow(min(allowed))

    def select_stage(self,row):
        if row<0:return
        if row==5:
            self.curation_dialog.show();self.curation_dialog.raise_();self.navigation.blockSignals(True);self.navigation.setCurrentRow(self._last_pipeline_row);self.navigation.blockSignals(False);return
        if row in self.hardware_tabs:
            self.tabs.setCurrentIndex(self.hardware_tabs[row]);self.navigation.blockSignals(True);self.navigation.setCurrentRow(self._last_pipeline_row);self.navigation.blockSignals(False);return
        self._last_pipeline_row=row;self.stack.setCurrentIndex(row);self.tabs.setCurrentIndex(2);name,page=self.pages[row];self.dashboard_title.setText(name)
        workflow=self.workflows['source']if page is self.source_tabs else page
        self.settings_toggle.blockSignals(True);self.settings_toggle.setVisible(hasattr(workflow,'settings_scroll'));self.settings_toggle.setChecked(not workflow.settings_scroll.isHidden()if hasattr(workflow,'settings_scroll')else False);self.settings_toggle.blockSignals(False)
        self.engine_stack.setCurrentIndex(row);self.engine_stack.setVisible(isinstance(workflow,WorkflowPage)and workflow.stage in ('source','annotation','datagen','simulation_evaluation'))

    def toggle_settings(self,visible):
        page=self.pages[self._last_pipeline_row][1];page=self.workflows['source']if page is self.source_tabs else page
        if hasattr(page,'settings_scroll'):page.settings_scroll.setVisible(visible)

    def closeEvent(self,event):
        active=[page for page in self.workflows.values() if page.active()]
        if active:
            self.closing=True
            for page in active:
                if page.handle and page.handle['run_id'] not in self.cancelled_on_close:
                    page.cancel_run();self.cancelled_on_close.add(page.handle['run_id'])
            self.statusBar().showMessage('취소와 실제 worker/Preview 정리를 기다립니다…');event.ignore();QTimer.singleShot(500,self.close);return
        from PyQt6.QtCore import QProcess
        jobs=self.findChildren(BackendJob)
        if any(job.process.state()!=QProcess.ProcessState.NotRunning for job in jobs):
            self.statusBar().showMessage('현재 파일 작업 종료를 기다립니다…');event.ignore();QTimer.singleShot(500,self.close);return
        if self.scene.builder.state()!=QProcess.ProcessState.NotRunning:
            self.scene.builder.terminate();event.ignore();QTimer.singleShot(500,self.close);return
        for page in self.workflows.values():page.timer.stop()
        import shutil
        for page in (self.source,self.curation):
            page.stop_playback();shutil.rmtree(page.preview_directory,ignore_errors=True)
        event.accept()


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--backend-python',required=True);parser.add_argument('--task-modules',required=True);parser.add_argument('--workspace',required=True)
    args=parser.parse_args(argv)
    if not Path(args.backend_python).is_file():parser.error('기존 backend Python 경로가 필요합니다')
    app=QApplication.instance() or QApplication(sys.argv[:1]);window=Window(args.backend_python,args.task_modules,args.workspace);window.show();return app.exec()


if __name__=='__main__':raise SystemExit(main())
