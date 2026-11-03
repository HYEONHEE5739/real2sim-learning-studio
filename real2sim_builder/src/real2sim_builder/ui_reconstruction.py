"""Shared reconstruction form for Builder and Workbench; models run in CLI children."""
import copy
import os
from pathlib import Path
import tempfile
import time
from PyQt6.QtCore import QProcess,QProcessEnvironment,Qt,QUrl
from PyQt6.QtGui import QDesktopServices,QPixmap,QImageReader
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QWidget,QLabel,QLineEdit,QComboBox,
    QPushButton,QFileDialog,QTableWidget,QTableWidgetItem,QHeaderView,QPlainTextEdit,QMessageBox,QTabWidget,QInputDialog)
from .project import Project
from .files import read,write


class ReconstructionDialog(QDialog):
    def __init__(self,project,python,parent=None):
        super().__init__(parent);self.project=Project(project);self.python=str(python);self.process=QProcess(self)
        self.pending_close=False;self.temporary=None;self.setWindowTitle('Auto Reconstruction');self.resize(1000,760)
        path=self.project.root/'input/reconstruction.yaml';self.saved=read(path)if path.exists()else{}
        self.scene=self.project.scene if(self.project.root/'working/current_scene.yaml').exists()else{'objects':[],'cameras':[]}
        box=QVBoxLayout(self);box.addWidget(QLabel(self.project.info['name']+' · Current/기존 Export는 변경하지 않습니다.'))
        self.tabs=QTabWidget();box.addWidget(self.tabs,1)
        inputs=QWidget();layout=QVBoxLayout(inputs);self.tabs.addTab(inputs,'사진·실측')
        row=QHBoxLayout();layout.addLayout(row);row.addWidget(QLabel('정적 배치 ID'));self.state=QLineEdit(self.saved.get('scene_state_id','layout_1'));row.addWidget(self.state)
        self.camera=QLineEdit('external');row.addWidget(QLabel('Camera / 렌즈 ID'));row.addWidget(self.camera)
        self.camera_type=QComboBox();self.camera_type.addItems(['external','side','wrist']);row.addWidget(self.camera_type)
        self.split=QComboBox();self.split.addItems(['train','validation']);row.addWidget(self.split)
        button=QPushButton('사진·영상 등록');button.clicked.connect(lambda:self.guard(self.register_images));layout.addWidget(button)
        layout.addWidget(QLabel('Wrist는 실제 q·시각이 포함된 기존 Capture/Snapshot 등록을 사용합니다. 배치가 바뀌면 다른 ID를 쓰세요.'))
        self.images=QComboBox();layout.addWidget(self.images)
        layout.addWidget(QLabel('실측 치수: mm. 빈 치수는 추측하지 않습니다. 기존 측정값과 Robot은 보호합니다.'))
        self.objects=QTableWidget(0,9);self.objects.setHorizontalHeaderLabels(['Object ID','종류','역할','가로 mm','세로 mm','높이 mm','벽 mm','Support ID','SAM 설명'])
        self.objects.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(self.objects,1)
        add=QPushButton('물체 행 추가');add.clicked.connect(lambda:self.add_object({}));layout.addWidget(add)
        board=QPushButton('선택 사진의 측정 보드 코너 지정');board.clicked.connect(lambda:self.guard(self.board_corners));layout.addWidget(board)
        settings=QWidget();form=QFormLayout(settings);self.tabs.addTab(settings,'기존 모델 환경')
        self.paths={}
        for kind,label in(('sam','SAM 3.1'),('da3','DA3-SMALL')):
            for key,title in(('python','Python 실행 파일'),('model','로컬 Checkpoint / Model')):
                panel=QWidget();r=QHBoxLayout(panel);r.setContentsMargins(0,0,0,0)
                edit=QLineEdit(self.saved.get(kind,{}).get(key,''));self.paths[kind,key]=edit;r.addWidget(edit,1)
                choose=QPushButton('선택');choose.clicked.connect(lambda _,e=edit,k=kind,f=key:self.choose_path(e,k,f));r.addWidget(choose)
                form.addRow(label+' '+title,panel)
        form.addRow(QLabel('설치·다운로드 없이 지정한 기존 환경을 순서대로 실행합니다. 경로는 Project에 저장됩니다.'))
        review=QWidget();r=QVBoxLayout(review);self.tabs.addTab(review,'Mask·상태')
        self.mask_object=QComboBox();r.addWidget(self.mask_object)
        self.mask_index=QComboBox();r.addWidget(self.mask_index);self.mask_index.currentIndexChanged.connect(self.show_mask)
        self.mask_preview=QLabel('추론 후 사진·물체를 선택하세요');self.mask_preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.mask_preview.setMinimumHeight(200);r.addWidget(self.mask_preview,1)
        choose=QPushButton('선택 Mask 사용');choose.clicked.connect(lambda:self.guard(self.select_mask));r.addWidget(choose)
        edited=QPushButton('수정한 원본 해상도 Mask PNG 선택');edited.clicked.connect(lambda:self.guard(self.edited_mask));r.addWidget(edited)
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);r.addWidget(self.summary,1)
        actions=QHBoxLayout();box.addLayout(actions);self.candidate=QLineEdit('auto_'+time.strftime('%Y%m%d_%H%M%S'));actions.addWidget(QLabel('Candidate'));actions.addWidget(self.candidate)
        self.start=QPushButton('저장 · Auto Reconstruction');self.start.clicked.connect(lambda:self.guard(self.run));actions.addWidget(self.start)
        self.stop=QPushButton('중단');self.stop.setEnabled(False);self.stop.clicked.connect(lambda:self.project.control('stop'));actions.addWidget(self.stop)
        folder=QPushButton('결과 폴더');folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.root/'scratch/agent'/self.candidate.text()))));actions.addWidget(folder)
        self.export_button=QPushButton('미검증 초안 새 Export');self.export_button.clicked.connect(lambda:self.guard(self.export_draft));box.addWidget(self.export_button)
        self.process.readyReadStandardOutput.connect(self.logs);self.process.readyReadStandardError.connect(self.logs)
        self.process.finished.connect(self.finished);self.process.errorOccurred.connect(lambda _:self.summary.appendPlainText(self.process.errorString()))
        self.process.stateChanged.connect(self.process_state)
        specs={s['id']:s for s in self.saved.get('measurements',[])}
        for obj in self.scene['objects']:
            if obj.get('link')or obj['role']=='reference_robot':continue
            if obj['id']not in specs:
                spec={'id':obj['id'],'kind':obj['collision']['type'],'role':obj['role']}
                if obj['dimensions']['provenance']in('measured','calibrated'):
                    spec.update(dimensions_m=obj['dimensions']['value'],evidence=obj['dimensions'].get('evidence')or['existing measured Scene'])
                if obj['collision'].get('wall',{}).get('value')is not None:spec['wall_m']=obj['collision']['wall']['value']
                if obj['collision'].get('round'):spec['round']=True
                specs[obj['id']]=spec
        for spec in specs.values():self.add_object(spec)
        self.objects.itemChanged.connect(self.sync_object_names)
        self.images.currentIndexChanged.connect(self.reload_masks);self.mask_object.currentIndexChanged.connect(self.reload_masks)
        self.refresh_images()

    def guard(self,fn):
        try:fn()
        except(Exception)as error:QMessageBox.warning(self,'Auto Reconstruction',str(error))

    def add_object(self,spec):
        row=self.objects.rowCount();self.objects.insertRow(row);name=spec.get('id','')
        dims=spec.get('dimensions_m',[None]*3);query=self.saved.get('objects',{}).get(name,{})
        values=[name,spec.get('kind','box'),spec.get('role','manipulable_object'),*[str(v*1000)if v is not None else''for v in dims],
                str(spec['wall_m']*1000)if spec.get('wall_m')is not None else'',self.saved.get('fitting',{}).get('supports',{}).get(name,''),query.get('prompt','')]
        for col,value in enumerate(values):self.objects.setItem(row,col,QTableWidgetItem(str(value)))
        self.mask_object.addItem(name,name)

    def configuration(self):
        result=copy.deepcopy(self.saved);result['scene_state_id']=self.state.text().strip();result.setdefault('objects',{})
        result['measurements']=[];supports=result.setdefault('fitting',{}).setdefault('supports',{})
        previous={s['id']:s for s in self.saved.get('measurements',[])};active=set()
        for row in range(self.objects.rowCount()):
            values=[self.objects.item(row,col).text().strip()for col in range(9)];name,kind,role,*_=values
            if not name:continue
            active.add(name)
            if values[8]:result['objects'].setdefault(name,{})['prompt']=values[8]
            if values[7]:supports[name]=values[7]
            else:supports.pop(name,None)
            if any(values[i]for i in(3,4,5)):
                if not all(values[i]for i in(3,4,5)):raise ValueError(name+': 실측 가로·세로·높이를 모두 입력하세요.')
                spec=copy.deepcopy(previous.get(name,{}));spec.update(id=name,kind=kind,role=role,
                    dimensions_m=[float(values[i])/1000 for i in(3,4,5)],evidence=spec.get('evidence')or['user measured values entered in Scene Prepare'])
                if values[6]:spec['wall_m']=float(values[6])/1000
                if kind=='container':spec['round']=spec.get('round',True)
                result['measurements'].append(spec)
        for(kind,key),edit in self.paths.items():result.setdefault(kind,{})[key]=edit.text().strip()
        result['objects']={key:query for key,query in result['objects'].items()if key in active}
        return result

    def sync_object_names(self,*_):
        selected=self.mask_object.currentData();self.mask_object.blockSignals(True);self.mask_object.clear()
        for row in range(self.objects.rowCount()):
            item=self.objects.item(row,0)
            if item and item.text().strip():self.mask_object.addItem(item.text().strip(),item.text().strip())
        self.mask_object.setCurrentIndex(max(0,self.mask_object.findData(selected)));self.mask_object.blockSignals(False);self.reload_masks()

    def choose_path(self,edit,kind,key):
        if kind=='da3'and key=='model':path=QFileDialog.getExistingDirectory(self,'기존 DA3 snapshot 폴더')
        else:path,_=QFileDialog.getOpenFileName(self,'기존 환경/파일 선택')
        if path:edit.setText(path)

    def start_cli(self,args):
        if self.process.state()!=QProcess.ProcessState.NotRunning:raise ValueError('현재 작업을 중단한 뒤 변경하세요.')
        self.operation=args[0];self.summary.setPlainText(self.operation+' 실행 중…')
        environment=QProcessEnvironment.systemEnvironment();root=Path(__file__).absolute().parents[1]
        environment.insert('PYTHONPATH',os.pathsep.join([str(root),str(root.parent.parent/'scene_contract/src')]))
        usd=os.environ.get('REAL2SIM_USD_PYTHONPATH')
        if usd:environment.insert('PYTHONPATH',environment.value('PYTHONPATH')+os.pathsep+usd)
        environment.remove('PYTHONHOME');environment.insert('PYTHONNOUSERSITE','1');environment.insert('PYTHONDONTWRITEBYTECODE','1')
        self.process.setProcessEnvironment(environment);self.process.start(self.python,['-B','-m','real2sim_builder.cli',*args])

    def register_images(self):
        if self.camera_type.currentText()=='wrist':raise ValueError('Wrist 사진은 실제 measured q가 있는 Capture/Snapshot을 등록하세요.')
        paths,_=QFileDialog.getOpenFileNames(self,'같은 정적 배치의 RGB 사진·영상','','RGB (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.mp4 *.mov *.avi)')
        if paths:self.start_cli(['register-rgb',str(self.project.root),*paths,'--camera',self.camera.text().strip(),'--type',self.camera_type.currentText(),
                                 '--scene-state',self.state.text().strip(),'--split',self.split.currentText()])

    def run(self):
        if self.temporary:self.temporary.cleanup()
        self.temporary=tempfile.TemporaryDirectory(prefix='real2sim-reconstruct-')
        config=Path(self.temporary.name)/'configuration.yaml';self.saved=self.configuration();write(config,self.saved)
        self.start_cli(['reconstruct',str(self.project.root),'--candidate',self.candidate.text().strip(),'--config',str(config)])
        self.tabs.setCurrentIndex(2);self.summary.setPlainText('자동 재구성 실행 중…')

    def process_state(self,state):
        idle=state==QProcess.ProcessState.NotRunning
        self.tabs.setEnabled(idle);self.candidate.setEnabled(idle);self.start.setEnabled(idle);self.stop.setEnabled(not idle)
        self.export_button.setEnabled(idle)

    def export_draft(self):
        destination,_=QFileDialog.getSaveFileName(self,'미검증 초안의 새 Package 폴더',str(self.project.root/'exports'))
        if destination:
            self.start_cli(['export',str(self.project.root),'--candidate',self.candidate.text().strip(),
                '--allow-unvalidated','--destination',destination])

    def logs(self):
        self.summary.appendPlainText((bytes(self.process.readAllStandardOutput())+bytes(self.process.readAllStandardError())).decode(errors='replace')[-4000:])

    def finished(self,*_):
        self.logs();self.refresh_images();path=self.project.root/'scratch/agent'/self.candidate.text()/'reconstruction.json'
        if self.process.exitCode()not in(0,2):
            self.summary.setPlainText('실행 실패 (exit '+str(self.process.exitCode())+')\n'+self.summary.toPlainText())
        elif self.operation=='reconstruct'and path.is_file():
            report=read(path);self.summary.setPlainText(report['status']+'\n'+'\n'.join(report.get('needs',[])))
        if self.temporary:self.temporary.cleanup();self.temporary=None
        if self.pending_close:self.close()

    def refresh_images(self):
        selected=self.images.currentData();self.images.blockSignals(True);self.images.clear()
        for image in self.project.evidence['images']:
            if image.get('id')and image.get('scene_state_id')==self.state.text():self.images.addItem(image['id']+' · '+image.get('registration_status','Capture')+' · '+image['split'],image['id'])
        self.images.setCurrentIndex(max(0,self.images.findData(selected)));self.images.blockSignals(False);self.reload_masks()

    def reload_masks(self,*_):
        self.mask_index.clear();path=self.project.root/'scratch/agent'/self.candidate.text()/'inference/results.json'
        if not path.exists():return
        for row in read(path)['segments']:
            if row['image_id']==self.images.currentData()and row['object_id']==self.mask_object.currentData():
                for index,mask in enumerate(row['masks']):self.mask_index.addItem(str(index)+' · '+row['status'],mask['path'])

    def show_mask(self,*_):
        path=self.mask_index.currentData();pix=QPixmap(path)if path else QPixmap()
        if not pix.isNull():self.mask_preview.setPixmap(pix.scaled(700,260,Qt.AspectRatioMode.KeepAspectRatio))
        else:self.mask_preview.clear();self.mask_preview.setText('검출 Mask 없음')

    def select_mask(self):
        if self.mask_index.currentIndex()<0:raise ValueError('Mask를 선택하세요.')
        self.saved.setdefault('selections',{}).setdefault(self.images.currentData(),{})[self.mask_object.currentData()]=self.mask_index.currentIndex()
        self.summary.setPlainText('선택 반영됨 · Auto Reconstruction을 다시 실행하면 추론 캐시를 재사용합니다.')

    def edited_mask(self):
        path,_=QFileDialog.getOpenFileName(self,'원본 RGB와 같은 해상도의 이진 Mask','','PNG (*.png)')
        if path:
            if not self.images.currentData()or not self.mask_object.currentData():raise ValueError('사진과 물체를 선택하세요.')
            self.saved.setdefault('selections',{}).setdefault(self.images.currentData(),{})[self.mask_object.currentData()]=path

    def board_corners(self):
        from .automation import board_binding
        image=next((i for i in self.project.evidence['images']if i.get('id')==self.images.currentData()),None)
        if image is None:raise ValueError('등록된 사진을 선택하세요.')
        boards=[o['id']for o in self.scene['objects']if o['role']in('workspace','support_surface')]
        if not boards:raise ValueError('World 위치와 크기가 측정된 보드를 먼저 등록하세요.')
        board,ok=QInputDialog.getItem(self,'측정 보드','실측 World 보드',boards,0,False)
        if not ok:return
        board_binding(self.scene,board,[[0,0]]*4)  # Validate metric evidence before accepting clicks.
        dialog=QDialog(self);dialog.setWindowTitle('보드 위 네 모서리: (−X,−Y) → (+X,−Y) → (+X,+Y) → (−X,+Y)')
        layout=QVBoxLayout(dialog);hint=QLabel('동일한 실제 모서리를 순서대로 클릭하세요. 로봇/World 위치는 바뀌지 않습니다.');layout.addWidget(hint)
        reader=QImageReader(str(self.project.root/image['path']));reader.setAutoTransform(True)
        pixmap=QPixmap.fromImage(reader.read());label=QLabel();display=pixmap.scaled(900,600,Qt.AspectRatioMode.KeepAspectRatio)
        if pixmap.isNull():raise ValueError('사진을 읽을 수 없습니다.')
        label.setPixmap(display);label.setFixedSize(display.size());layout.addWidget(label);points=[]
        def clicked(event):
            if len(points)>=4:return
            points.append([event.position().x()*pixmap.width()/display.width(),event.position().y()*pixmap.height()/display.height()])
            hint.setText(str(len(points))+'/4 모서리 지정')
            if len(points)==4:dialog.accept()
        label.mousePressEvent=clicked
        reset=QPushButton('다시 지정');reset.clicked.connect(lambda:(points.clear(),hint.setText('0/4 모서리 지정')));layout.addWidget(reset)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.saved.setdefault('anchors',{})[image['id']]=board_binding(self.scene,board,points)
            self.summary.setPlainText('측정 보드 코너 반영됨 · Auto Reconstruction을 실행하세요.')

    def closeEvent(self,event):
        if self.process.state()!=QProcess.ProcessState.NotRunning:
            self.pending_close=True;self.project.control('stop');event.ignore();return
        if self.temporary:self.temporary.cleanup();self.temporary=None
        event.accept()
