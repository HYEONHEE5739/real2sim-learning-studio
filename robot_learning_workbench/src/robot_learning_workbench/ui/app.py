"""Workbench execution pages; Scene authoring belongs to the Builder package."""
import argparse,sys
from pathlib import Path
from PyQt6.QtCore import QTimer,Qt
from PyQt6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QListWidget,QStackedWidget,QPushButton,QLabel,QTabWidget,QComboBox,QDialog
from .jobs import BackendJob
from .workflow import WorkflowPage
from .source_page import SourcePage
from .curation import CurationPage


class Window(QMainWindow):
    def __init__(self,backend_python,modules,workspace):
        super().__init__()
        from .theme import STYLE
        from .paths import GROUPS
        self.setStyleSheet(STYLE);self.setWindowTitle('Real2Sim Learning Studio');self.resize(1320,900);self.workspace=Path(workspace).resolve();self.workspace.mkdir(parents=True,exist_ok=True)
        for folder in set(GROUPS.values()):(self.workspace/folder).mkdir(exist_ok=True)
        self.closing=False;self.cancelled_on_close=set()
        central=QWidget();self.setCentralWidget(central);layout=QVBoxLayout(central)
        self.safety=QLabel('연결은 관측으로 시작 · Teleoperation 시작 버튼으로 실제 Leader → Follower 구동');self.safety.setWordWrap(True);layout.addWidget(self.safety)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.curation=CurationPage(backend_python,self.workspace,self)
        self.workflows={stage:WorkflowPage(stage,backend_python,modules,self)for stage in ('annotation','datagen','train','simulation_evaluation','offline_validation','hub_download','hub_upload','real_evaluation')}
        self.source=SourcePage(backend_python,modules,self.workspace,self);self.workflows['source']=self.source
        from .session_page import CapturePage
        from .real_sim_page import RealSimPage
        from .precision_page import PrecisionPage
        self.sessions={'capture':CapturePage(backend_python,modules,self.workspace,self),'real_sim':RealSimPage(backend_python,modules,self.workspace,self),'precision':PrecisionPage(backend_python,modules,self.workspace,self)}
        self.sessions['precision'].profile_saved.connect(self.precision_saved)
        self.pipeline=QWidget();outer=QVBoxLayout(self.pipeline);outer.setContentsMargins(12,12,12,12);outer.setSpacing(16)
        header=QWidget();header.setObjectName('dashboardHeader');header_layout=QHBoxLayout(header);title_box=QVBoxLayout();brand=QLabel('SO-101  /  WORKSPACE');brand.setObjectName('eyebrow');title_box.addWidget(brand)
        self.dashboard_title=QLabel('Source Demo');self.dashboard_title.setObjectName('dashboardTitle');title_box.addWidget(self.dashboard_title);header_layout.addLayout(title_box,1)
        self.engine_stack=QStackedWidget();self.engine_stack.setMaximumWidth(180);self.engine_stack.setMaximumHeight(50);header_layout.addWidget(self.engine_stack)
        self.settings_toggle=QPushButton('실행 설정');self.settings_toggle.setCheckable(True);self.settings_toggle.setChecked(True);self.settings_toggle.toggled.connect(self.toggle_settings);header_layout.addWidget(self.settings_toggle);outer.addWidget(header)
        body=QHBoxLayout();body.setSpacing(16);outer.addLayout(body,1)
        self.navigation_panel=QWidget();self.navigation_panel.setObjectName('navigationPanel');self.navigation_panel.setFixedWidth(200);nav=QVBoxLayout(self.navigation_panel);label=QLabel('WORKFLOW');label.setObjectName('eyebrow');nav.addWidget(label)
        self.section=QComboBox();self.section.addItems(['Sim 작업 파이프라인','Real']);nav.addWidget(self.section)
        self.navigation=QListWidget();self.navigation.setObjectName('stageNavigation');nav.addWidget(self.navigation,1)
        self.curation_shortcut=QPushButton('Data Curation');self.curation_shortcut.clicked.connect(lambda:self.navigation.setCurrentRow(self.page_rows['Data Curation']));nav.addWidget(self.curation_shortcut)
        hint=QLabel('단계를 선택하고\n입력을 확인한 뒤 실행하세요.');hint.setObjectName('mutedLabel');hint.setWordWrap(True);nav.addWidget(hint);body.addWidget(self.navigation_panel)
        self.stack=QStackedWidget();body.addWidget(self.stack,1)
        self.pages=[('Source Demo',self.source),('Annotation',self.workflows['annotation']),('Mimic / Datagen',self.workflows['datagen']),('Data Curation',self.curation),('모델 학습',self.workflows['train']),('Sim 평가',self.workflows['simulation_evaluation']),('Offline Validation',self.workflows['offline_validation']),('Hub 다운로드',self.workflows['hub_download']),('Hub 업로드',self.workflows['hub_upload']),('Real Evaluation',self.workflows['real_evaluation'])]
        self.page_rows={name:i for i,(name,_)in enumerate(self.pages)}
        self._last_pipeline_row=self.page_rows['Source Demo']
        for i,(name,page)in enumerate(self.pages):
            self.navigation.addItem(f'{i+1:02d}  {name}');self.stack.addWidget(QWidget()if page is self.curation else page)
            engine=page.engine if isinstance(page,(WorkflowPage,SourcePage))else QWidget()
            if isinstance(page,WorkflowPage)and page.stage in ('annotation','datagen','simulation_evaluation'):
                engine.parentWidget().hide()
            self.engine_stack.addWidget(engine)
        self.curation_dialog=QDialog(self);self.curation_dialog.setWindowTitle('Data Curation · Episode 검토');self.curation_dialog.resize(1400,920);self.curation_dialog.setWindowModality(Qt.WindowModality.WindowModal);QVBoxLayout(self.curation_dialog).addWidget(self.curation)
        self.tabs.addTab(self.sessions['capture'],'1 · Scene Prepare');self.tabs.addTab(self.sessions['real_sim'],'2 · Real / Sim');self.tabs.addTab(self.pipeline,'3 · Workspace Pipeline');self.tabs.addTab(self.sessions['precision'],'4 · Precision Calibration')
        self.navigation.currentRowChanged.connect(self.select_stage);self.section.currentIndexChanged.connect(self.change_section);self.change_section(0);self.navigation.setCurrentRow(self.page_rows['Source Demo'])
        self.tabs.currentChanged.connect(self.update_banner)
        self.tabs.setCurrentIndex(0)
        self.statusBar().showMessage('Scene v8 원본 보존 · Teleoperation 시작/중단은 사용자 조작 · Hub 쓰기 별도 승인')

    def update_banner(self,index):
        if index not in(0,1,2,3):return
        text={0:'로봇 연결은 관측으로 시작 · 텔레옵 시작으로 실제 Leader → Follower 구동',1:'Real/Sim: Leader → 실제 Follower 제어 · Follower 측정 자세를 Sim에 반영',3:'Precision: 연결 버튼으로 선택 로봇의 토크 해제 · 기준 자세 기록과 보정 저장'}
        if index==2:text[index]='Source Demo: Leader → Simulation 로봇 · 실제 Follower 명령 없음'if self.pages[self._last_pipeline_row][1]is self.source else'Workspace Pipeline · 선택 단계의 Script와 입력으로 실행'
        self.safety.setText(text[index])

    def precision_saved(self,result):
        capture=self.sessions['capture']
        if not capture.active()and str(capture.settings.saved_recipe)==result['source_configuration_path']:
            capture.settings.load_recipe(result['configuration_path']);capture.buttons(False)
        self.statusBar().showMessage('Precision 저장·자동 적용 완료 · 다음 연결부터 새 보정을 사용합니다.')

    def change_section(self,index):
        self.curation_shortcut.setVisible(index==0)
        names=('Source Demo','Annotation','Mimic / Datagen','모델 학습','Sim 평가','Offline Validation','Hub 다운로드','Hub 업로드')if index==0 else('Real Evaluation',)
        allowed={self.page_rows[name]for name in names}
        for i in range(self.navigation.count()):self.navigation.item(i).setHidden(i not in allowed)
        if self.navigation.currentRow()not in allowed:self.navigation.setCurrentRow(min(allowed))

    def select_stage(self,row):
        if row<0:return
        if self.pages[row][1] is self.curation:
            self.curation_dialog.show();self.curation_dialog.raise_();self.navigation.blockSignals(True);self.navigation.setCurrentRow(self._last_pipeline_row);self.navigation.blockSignals(False);return
        self._last_pipeline_row=row;self.stack.setCurrentIndex(row);self.tabs.setCurrentIndex(2);self.update_banner(2);name,page=self.pages[row];self.dashboard_title.setText(name)
        workflow=page
        self.settings_toggle.blockSignals(True);self.settings_toggle.setVisible(hasattr(workflow,'settings_scroll'));self.settings_toggle.setChecked(not workflow.settings_scroll.isHidden()if hasattr(workflow,'settings_scroll')else False);self.settings_toggle.blockSignals(False)
        self.engine_stack.setCurrentIndex(row);self.engine_stack.setVisible(isinstance(workflow,(WorkflowPage,SourcePage))and workflow.stage in ('source','annotation','datagen','simulation_evaluation'))

    def toggle_settings(self,visible):
        page=self.pages[self._last_pipeline_row][1]
        if hasattr(page,'settings_scroll'):page.settings_scroll.setVisible(visible)

    def closeEvent(self,event):
        active=[page for page in [*self.workflows.values(),*self.sessions.values()] if page.active()]
        if active:
            self.closing=True
            for page in active:
                if page in self.sessions.values()or isinstance(page,SourcePage):
                    page.cancel_run();continue
                if page.handle and page.handle['run_id'] not in self.cancelled_on_close:
                    page.cancel_run();self.cancelled_on_close.add(page.handle['run_id'])
            self.statusBar().showMessage('취소와 실제 worker/Preview 정리를 기다립니다…');event.ignore();QTimer.singleShot(500,self.close);return
        from PyQt6.QtCore import QProcess
        jobs=self.findChildren(BackendJob)
        if any(job.process.state()!=QProcess.ProcessState.NotRunning for job in jobs):
            self.statusBar().showMessage('현재 파일 작업 종료를 기다립니다…');event.ignore();QTimer.singleShot(500,self.close);return
        for page in self.workflows.values():page.timer.stop()
        for page in self.sessions.values():page.stop_timers()
        import shutil
        for page in (self.curation,):
            page.stop_playback();shutil.rmtree(page.preview_directory,ignore_errors=True)
        event.accept()


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--backend-python',required=True);parser.add_argument('--task-modules',required=True);parser.add_argument('--workspace',required=True)
    args=parser.parse_args(argv)
    if not Path(args.backend_python).is_file():parser.error('기존 backend Python 경로가 필요합니다')
    app=QApplication.instance() or QApplication(sys.argv[:1]);window=Window(args.backend_python,args.task_modules,args.workspace);window.show();return app.exec()


if __name__=='__main__':raise SystemExit(main())
