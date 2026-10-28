"""Workbench stage pages; Builder remains an independent application."""
import argparse,json,sys
from pathlib import Path
from PyQt6.QtCore import QProcess,QProcessEnvironment,QTimer
from PyQt6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QListWidget,QStackedWidget,QPushButton,QLabel,QFileDialog,QLineEdit,QPlainTextEdit,QInputDialog,QTabWidget
from .jobs import BackendJob
from .workflow import WorkflowPage
from .curation import CurationPage


class ScenePage(QWidget):
    def __init__(self,python,workspace,parent=None):
        super().__init__(parent);self.python=python;self.workspace=Path(workspace);self.scene_path=None;self.builder_project=None;self.valid=False
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Scene · 기존 패키지 검사 / 독립 Builder 연결'))
        self.path=QLineEdit();self.path.setReadOnly(True);layout.addWidget(self.path);row=QHBoxLayout();layout.addLayout(row)
        for text,fn in [('Scene Package 선택',self.choose_scene),('Manifest·Calibration·Model 검사',self.inspect),('Builder Project 선택',self.choose_project),('기존 Builder 열기',self.open_builder),('수평 기준 검사 (선택)',self.horizontal)]:
            button=QPushButton(text);button.clicked.connect(fn);row.addWidget(button)
        self.state=QLabel('기존 Scene을 선택하세요. v9 생성/실물 Calibration은 자동 실행하지 않습니다.');self.state.setWordWrap(True);layout.addWidget(self.state)
        self.info=QPlainTextEdit();self.info.setReadOnly(True);layout.addWidget(self.info)
        self.job=BackendJob(python,self);self.job.finished.connect(self.finished);self.job.log.connect(self.info.appendPlainText)
        self.builder=QProcess(self);self.builder.readyReadStandardError.connect(lambda:self.info.appendPlainText(bytes(self.builder.readAllStandardError()).decode(errors='replace')))
    def choose_scene(self):
        path,_=QFileDialog.getOpenFileName(self,'기존 Scene scene.json','','JSON (*.json)')
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
        path=QFileDialog.getExistingDirectory(self,'기존 Builder Project 선택')
        if path:self.builder_project=Path(path);self.state.setText('Builder Project 선택됨 · '+path)
    def open_builder(self):
        if self.builder.state()!=QProcess.ProcessState.NotRunning:self.state.setText('이미 Builder가 실행 중입니다');return
        if self.builder_project is None:self.state.setText('기존 Builder Project를 선택하세요');return
        environment=QProcessEnvironment.systemEnvironment();environment.insert('REAL2SIM_WORKER_PYTHON',self.python);self.builder.setProcessEnvironment(environment)
        self.builder.start(sys.executable,['-B','-m','real2sim_builder.cli','ui','--projects',str(self.builder_project.parent)])
        self.state.setText('독립 Builder 실행 요청 · 새 Export 결과를 Scene Package 선택으로 다시 여세요')


class Window(QMainWindow):
    def __init__(self,backend_python,modules,workspace):
        super().__init__();self.setWindowTitle('Robot Learning Workbench');self.resize(1320,900);self.workspace=Path(workspace).resolve();self.workspace.mkdir(parents=True,exist_ok=True);self.closing=False;self.cancelled_on_close=set()
        central=QWidget();self.setCentralWidget(central);layout=QHBoxLayout(central);self.navigation=QListWidget();layout.addWidget(self.navigation,1);self.stack=QStackedWidget();layout.addWidget(self.stack,5)
        self.scene=ScenePage(backend_python,self.workspace,self);self.source=CurationPage(backend_python,self.workspace,self,source_only=True);self.curation=CurationPage(backend_python,self.workspace,self)
        self.workflows={stage:WorkflowPage(stage,backend_python,modules,self) for stage in ('source','annotation','datagen','train','simulation_evaluation','offline_validation')}
        self.source_tabs=QTabWidget();self.source_tabs.addTab(self.workflows['source'],'Simulation Source 수집');self.source_tabs.addTab(self.source,'저장 Source 검토')
        pages=[('Scene',self.scene),('Source',self.source_tabs),('Annotation',self.workflows['annotation']),('DataGen',self.workflows['datagen']),('Curation',self.curation),('ACT / SmolVLA Training',self.workflows['train']),('Evaluation',self.workflows['simulation_evaluation']),('독립 Validation',self.workflows['offline_validation'])]
        for name,page in pages:self.navigation.addItem(name);self.stack.addWidget(page)
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex);self.navigation.setCurrentRow(0)
        self.statusBar().showMessage('현재 지원: Simulation + ACT · 실물/SmolVLA/Hub는 실행하지 않습니다')
    def closeEvent(self,event):
        active=[page for page in self.workflows.values() if page.active()]
        if active:
            self.closing=True
            for page in active:
                if page.handle and page.handle['run_id'] not in self.cancelled_on_close:
                    page.cancel_run();self.cancelled_on_close.add(page.handle['run_id'])
            self.statusBar().showMessage('취소와 실제 worker/Preview 정리를 기다립니다…');event.ignore();QTimer.singleShot(500,self.close);return
        from PyQt6.QtCore import QProcess
        jobs=[self.scene.job,self.source.job,self.curation.job]+[page.job for page in self.workflows.values()]
        if any(job.process.state()!=QProcess.ProcessState.NotRunning for job in jobs):
            self.statusBar().showMessage('현재 파일 작업 종료를 기다립니다…');event.ignore();QTimer.singleShot(500,self.close);return
        if self.scene.builder.state()!=QProcess.ProcessState.NotRunning:
            self.scene.builder.terminate();event.ignore();QTimer.singleShot(500,self.close);return
        for page in self.workflows.values():page.timer.stop()
        import shutil
        for page in (self.source,self.curation):shutil.rmtree(page.preview_directory,ignore_errors=True)
        event.accept()


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--backend-python',required=True);parser.add_argument('--task-modules',required=True);parser.add_argument('--workspace',required=True)
    args=parser.parse_args(argv)
    if not Path(args.backend_python).is_file():parser.error('기존 backend Python 경로가 필요합니다')
    app=QApplication.instance() or QApplication(sys.argv[:1]);window=Window(args.backend_python,args.task_modules,args.workspace);window.show();return app.exec()


if __name__=='__main__':raise SystemExit(main())
