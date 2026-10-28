"""Project manager/progress monitor. Reconstruction lives in a separate worker."""
import json
import os
from pathlib import Path
import sys
import yaml
from PyQt6.QtCore import Qt,QProcess,QProcessEnvironment,QTimer,QUrl
from PyQt6.QtGui import QPixmap,QDesktopServices
from PyQt6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QListWidget,
    QPushButton,QLabel,QFileDialog,QInputDialog,QLineEdit,QComboBox,QTabWidget,QTextEdit,QMessageBox,QSplitter,QSizePolicy)
from .project import Project,STAGES,read


class Window(QMainWindow):
    def __init__(self,projects):
        super().__init__();self.projects=Path(projects).resolve();self.projects.mkdir(parents=True,exist_ok=True)
        self.project=None;self.worker_kind=None;self.process=QProcess(self);self.setWindowTitle('Real2Sim Builder');self.resize(1300,860)
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        title=QLabel('Real2Sim Builder');title.setStyleSheet('font-size:26px;font-weight:600');layout.addWidget(title)
        split=QSplitter();layout.addWidget(split,1);home=QWidget();left=QVBoxLayout(home);split.addWidget(home)
        left.addWidget(QLabel('Projects'));self.list=QListWidget();left.addWidget(self.list);self.list.currentRowChanged.connect(self.selected)
        self.new_button=QPushButton('+ New Scene');self.new_button.clicked.connect(lambda:self.guard(self.new));left.addWidget(self.new_button)
        self.tabs=QTabWidget();split.addWidget(self.tabs);split.setSizes([280,1000])
        self.setup_inputs();self.setup_run();self.setup_compare();self.setup_result()
        reload_=QPushButton('Reload project');reload_.clicked.connect(lambda:self.guard(self.reload_project));left.addWidget(reload_)
        self.process.readyReadStandardOutput.connect(self.logs);self.process.readyReadStandardError.connect(self.logs)
        self.process.stateChanged.connect(self.worker_state)
        self.process.finished.connect(self.finished);self.process.errorOccurred.connect(lambda error:self.log.append('Worker error: '+self.process.errorString()))
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(500);self.refresh()

    def guard(self,fn):
        try:fn()
        except Exception as exc:QMessageBox.warning(self,'Real2Sim Builder',str(exc))

    def setup_inputs(self):
        tab=QWidget();box=QVBoxLayout(tab);self.tabs.addTab(tab,'New Scene / Inputs')
        self.name=QLabel('Select or create a project');box.addWidget(self.name)
        row=QHBoxLayout();box.addLayout(row);row.addWidget(QLabel('Camera / view ID'));self.camera=QLineEdit('side');row.addWidget(self.camera)
        self.split=QComboBox();self.split.addItems(['train','validation']);row.addWidget(self.split)
        for title,kind in [('Add Images','image'),('Add Videos','video'),('Camera Calibration','calibration'),('Measurements / Geometry','measurements'),('Canonical Scene','scene'),('Robot URDF / MJCF / USD','robot')]:
            button=QPushButton(title);button.clicked.connect(lambda _,k=kind:self.guard(lambda:self.add(k)));box.addWidget(button)
        self.candidates=QComboBox();box.addWidget(self.candidates)
        candidate_row=QHBoxLayout();box.addLayout(candidate_row)
        for label,action in [('Create candidate','create'),('Reject candidate','reject'),('Promote candidate','promote')]:
            button=QPushButton(label);button.clicked.connect(lambda _,a=action:self.guard(lambda:self.candidate_action(a)));candidate_row.addWidget(button)
        self.inputs=QTextEdit();self.inputs.setReadOnly(True);box.addWidget(self.inputs,1)
        start=QPushButton('Start Reconstruction');start.clicked.connect(lambda:self.guard(self.start));box.addWidget(start)

    def setup_run(self):
        tab=QWidget();box=QVBoxLayout(tab);self.tabs.addTab(tab,'Run')
        row=QHBoxLayout();box.addLayout(row);row.addWidget(QLabel('Worker Python'));self.python=QLineEdit(os.environ.get('REAL2SIM_WORKER_PYTHON',sys.executable));row.addWidget(self.python)
        self.renderer=QComboBox();self.renderer.addItems(['software-egl','egl','osmesa']);row.addWidget(self.renderer)
        self.status=QLabel('DRAFT');self.status.setWordWrap(True);box.addWidget(self.status)
        self.stages=QListWidget();self.stages.addItems(STAGES);box.addWidget(self.stages)
        row=QHBoxLayout();box.addLayout(row)
        for label,fn in [('Start',self.start),('Pause',lambda:self.command('pause')),('Resume',self.resume),('Stop',lambda:self.command('stop'))]:
            button=QPushButton(label);button.clicked.connect(lambda _,f=fn:self.guard(f));row.addWidget(button)
        self.log=QTextEdit();self.log.setReadOnly(True);box.addWidget(self.log,1)

    def setup_compare(self):
        tab=QWidget();box=QVBoxLayout(tab);self.tabs.addTab(tab,'Compare')
        self.comparison_source=QComboBox();self.comparison_source.addItem('Final validation', 'working/validation');self.comparison_source.currentIndexChanged.connect(self.show_compare);box.addWidget(self.comparison_source)
        self.views=QComboBox();self.views.currentTextChanged.connect(self.show_compare);box.addWidget(self.views)
        self.compare_tabs=QTabWidget();box.addWidget(self.compare_tabs,1);self.pictures={}
        for name in ('side_by_side','overlay','difference'):
            label=QLabel('No render yet');label.setAlignment(Qt.AlignmentFlag.AlignCenter);self.pictures[name]=label;self.compare_tabs.addTab(label,name.replace('_',' ').title())
            # Pixmap size must not become a layout minimum: that feeds each
            # refresh back into the next image size and makes the window grow.
            label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
            label.setMinimumSize(1,1)
        self.metrics=QTextEdit();self.metrics.setReadOnly(True);box.addWidget(self.metrics)

    def setup_result(self):
        tab=QWidget();box=QVBoxLayout(tab);self.tabs.addTab(tab,'Result');self.result=QTextEdit();self.result.setReadOnly(True);box.addWidget(self.result)
        export_=QPushButton('Export new revision');export_.clicked.connect(lambda:self.guard(self.export_selected));box.addWidget(export_)
        open_=QPushButton('Open export folder');open_.clicked.connect(lambda:self.guard(self.open_export));box.addWidget(open_)
        viewer=QPushButton('Open accepted MJCF in MuJoCo viewer');viewer.clicked.connect(lambda:self.guard(self.open_mujoco));box.addWidget(viewer)

    def refresh(self):
        selected=str(self.project.root) if self.project else None
        self.paths=sorted(p.parent for p in self.projects.glob('*/project.yaml'))
        self.list.blockSignals(True);self.list.clear()
        for path in self.paths:
            try:
                p=Project(path);self.list.addItem(p.info['name']+'   '+p.state['status'])
            except (OSError,ValueError,KeyError,yaml.YAMLError) as exc:
                self.list.addItem(path.name+'   READ_ERROR');self.log.append(str(path)+': '+str(exc))
        if selected and Path(selected) in self.paths:self.list.setCurrentRow(self.paths.index(Path(selected)))
        self.list.blockSignals(False)

    def selected(self,row):
        if self.process.state()!=QProcess.ProcessState.NotRunning:return
        if 0<=row<len(self.paths):
            try:self.project=Project(self.paths[row]);self.poll(force=True)
            except (OSError,ValueError,KeyError,yaml.YAMLError) as exc:
                self.project=None;self.status.setText('Project READ_ERROR: '+str(exc));self.log.append(str(exc))

    def new(self):
        if self.process.state()!=QProcess.ProcessState.NotRunning:raise ValueError('Stop the active worker before creating another scene')
        name,ok=QInputDialog.getText(self,'New Scene','Scene Name')
        if ok and name.strip():self.project=Project.create(self.projects,name);self.refresh();self.poll(force=True);self.tabs.setCurrentIndex(0)

    def require_idle(self):
        if not self.project:raise ValueError('Create/select a project first')
        if self.process.state()!=QProcess.ProcessState.NotRunning:raise ValueError('Stop reconstruction before changing input evidence')

    def add(self,kind):
        self.require_idle()
        paths,_=QFileDialog.getOpenFileNames(self,'Add '+kind)
        if not paths:return
        args=['-u','-m','real2sim_builder.cli','add',str(self.project.root),*paths,'--kind',kind,'--camera',self.camera.text(),'--split',self.split.currentText()]
        if kind=='robot':
            states,_=QFileDialog.getOpenFileName(self,'Optional joint states in model radians (needed for articulated URDF/MJCF)')
            if states:args+=['--joints',states]
        self.start_worker(args,'add')

    def start_worker(self,args,kind):
        root=Path(__file__).resolve().parents[1]
        environment=QProcessEnvironment.systemEnvironment()
        # The GUI may borrow Qt from another venv; its NumPy and other binary
        # packages must never shadow the selected worker Python's own packages.
        paths=[str(root),str(root.parent.parent/'scene_contract/src')]
        usd_path=os.environ.get('REAL2SIM_USD_PYTHONPATH')
        if usd_path:paths.append(usd_path)
        environment.insert('PYTHONPATH',os.pathsep.join(paths))
        environment.remove('PYTHONHOME')
        environment.insert('PYTHONNOUSERSITE','1')
        environment.insert('PYTHONDONTWRITEBYTECODE','1')
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(root))
        self.worker_kind=kind
        self.process.start(self.python.text(),args)

    def start(self):
        self.require_idle();self.log.clear()
        self.start_worker(['-u','-m','real2sim_builder.cli','run',str(self.project.root),'--renderer',self.renderer.currentText()],'run');self.tabs.setCurrentIndex(1)

    def command(self,name):
        if not self.project:raise ValueError('Select a project')
        if self.process.state()==QProcess.ProcessState.NotRunning:raise ValueError('No active worker')
        if self.worker_kind!='run':raise ValueError('Input import is in progress; reconstruction controls are available after import finishes')
        self.project.control(name)

    def resume(self):
        if self.process.state()!=QProcess.ProcessState.NotRunning:self.command('resume')
        else:self.start()

    def logs(self):
        text=bytes(self.process.readAllStandardOutput())+bytes(self.process.readAllStandardError())
        self.log.append(text.decode(errors='replace'))

    def worker_state(self,state):
        idle=state==QProcess.ProcessState.NotRunning
        self.list.setEnabled(idle);self.new_button.setEnabled(idle)
        self.python.setEnabled(idle);self.renderer.setEnabled(idle)

    def finished(self,*args):self.worker_kind=None;self.refresh();self.poll(force=True)

    def poll(self,force=False):
        if not self.project:return
        try:
            state=self.project.state;self.name.setText(self.project.info['name']);self.status.setText(
                f"{state['status']} · {state.get('stage')} · Iteration {state['iteration']}\n{state.get('task','')}\nDecision: {state['decision']}\n"+json.dumps(state.get('metrics',{}),ensure_ascii=False))
            self.stages.setCurrentRow(STAGES.index(state['stage']) if state.get('stage') in STAGES else -1)
            self.inputs.setPlainText(json.dumps(self.project.evidence,indent=2,ensure_ascii=False));self.result.setPlainText(json.dumps(state,indent=2,ensure_ascii=False))
            names=[p.parent.name for p in sorted((self.project.root/'scratch/agent').glob('*/candidate.json'))]
            if names!=[self.candidates.itemText(i) for i in range(self.candidates.count())]:self.candidates.clear();self.candidates.addItems(names)
            sources=[('Final validation','working/validation')]+[(str(p.parent.parent.name)+' / '+p.name,p.relative_to(self.project.root).as_posix()) for p in sorted((self.project.root/'scratch/agent').glob('*/renders/*')) if (p/'metrics.json').exists()]
            selected=self.comparison_source.currentData()
            if sources!=[(self.comparison_source.itemText(i),self.comparison_source.itemData(i)) for i in range(self.comparison_source.count())]:
                self.comparison_source.blockSignals(True);self.comparison_source.clear()
                for label,path in sources:self.comparison_source.addItem(label,path)
                index=self.comparison_source.findData(selected);self.comparison_source.setCurrentIndex(max(index,0));self.comparison_source.blockSignals(False)
            paths=sorted(p.name for p in (self.project.root/self.comparison_source.currentData()/'previews').glob('*') if p.is_dir())
            if paths!=[self.views.itemText(i) for i in range(self.views.count())]:self.views.clear();self.views.addItems(paths)
            self.show_compare()
        except (OSError,ValueError,KeyError,yaml.YAMLError) as exc:
            message='Project state READ_ERROR: '+str(exc)
            self.status.setText(message)
            if getattr(self,'_last_read_error',None)!=message:self.log.append(message);self._last_read_error=message

    def show_compare(self,*args):
        if not self.project:return
        base=self.project.root/(self.comparison_source.currentData() or 'working/validation')
        root=base/'previews'/self.views.currentText()
        for name,label in self.pictures.items():
            pix=QPixmap(str(root/(name+'.png')))
            if not pix.isNull():label.setPixmap(pix.scaled(label.contentsRect().size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            else:label.clear();label.setText('No render yet')
        report=base/('report.json' if base.name=='validation' else 'metrics.json')
        if report.exists():self.metrics.setPlainText(json.dumps(read(report),indent=2))
        else:self.metrics.setPlainText('No validation report for this selection')

    def reload_project(self):
        self.require_idle();self.project=Project(self.project.root);self.refresh();self.poll(force=True)

    def candidate_action(self,action):
        self.require_idle()
        if action=='create':
            name,ok=QInputDialog.getText(self,'Candidate','Candidate ID')
            if not ok:return
        else:name=self.candidates.currentText()
        if not name:raise ValueError('Select a candidate')
        self.start_worker(['-u','-m','real2sim_builder.cli','candidate',str(self.project.root),action,name],'candidate')

    def export_selected(self,destination=None):
        self.require_idle()
        if destination is None:
            destination,_=QFileDialog.getSaveFileName(self,'New Scene package directory')
        if not destination:return
        if Path(destination).exists():raise ValueError('A new destination is required; existing packages are immutable')
        self.start_worker(['-u','-m','real2sim_builder.cli','export',str(self.project.root),'--destination',str(destination)],'export')

    def export_path(self):
        if not self.project:raise ValueError('Select a project')
        state=self.project.state;destination=state.get('export_destination')
        if not destination:raise ValueError('No published Scene revision for this project')
        from scene_contract.package import load_scene
        load_scene(Path(destination)/'scene.json')
        return Path(destination)

    def open_export(self):QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.export_path())))

    def open_mujoco(self):
        from scene_contract.package import load_scene
        package=load_scene(self.export_path()/'scene.json')
        path=package.root/package.scene['engines']['mujoco']['asset_path']
        QProcess.startDetached(self.python.text(),['-m','mujoco.viewer','--mjcf',str(path)])

    def closeEvent(self,event):
        if self.process.state()!=QProcess.ProcessState.NotRunning:
            if self.worker_kind=='run':self.project.control('stop')
            self.process.waitForFinished(2000)
            if self.process.state()!=QProcess.ProcessState.NotRunning:event.ignore();return
        self.timer.stop();event.accept()


def launch(projects):
    app=QApplication.instance() or QApplication(sys.argv);window=Window(projects);window.show();return app.exec()
