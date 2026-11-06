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
    def __init__(self,project,python,parent=None,*,refit=False):
        super().__init__(parent);self.project=Project(project);self.python=str(python);self.process=QProcess(self)
        self.refit=refit;self.deleted_objects=set();self.restore_conflicts=[]
        self.pending_close=False;self.temporary=None;self.setWindowTitle('Auto Reconstruction');self.resize(1000,760)
        path=self.project.root/'input/reconstruction.yaml';self.saved=read(path)if path.exists()else{}
        self.scene=self.project.scene if(self.project.root/'working/current_scene.yaml').exists()else{'objects':[],'cameras':[]}
        box=QVBoxLayout(self);box.addWidget(QLabel(self.project.info['name']+' · Current/기존 Export는 변경하지 않습니다.'))
        self.tabs=QTabWidget();box.addWidget(self.tabs,1)
        inputs=QWidget();layout=QVBoxLayout(inputs);self.tabs.addTab(inputs,'Scene Memo·사진')
        from .evidence import scene_memo
        memo=QPlainTextEdit();memo.setReadOnly(True);memo.setPlainText(scene_memo(self.project)['text']);memo.setMaximumHeight(140)
        layout.addWidget(QLabel('Scene Memo · 장면 설명, 실측 크기, 작업 목적을 Codex가 함께 이해합니다. 수정은 Scene Prepare에서 저장하세요.'));layout.addWidget(memo)
        row=QHBoxLayout();layout.addLayout(row);row.addWidget(QLabel('촬영 배치'));self.state=QComboBox();self.state.setEditable(True)
        groups=sorted({i['scene_state_id']for i in self.project.evidence['images']if i.get('scene_state_id')})
        self.state.addItems(groups);self.state.setCurrentText(self.saved.get('scene_state_id',groups[-1]if groups else'layout_1'));row.addWidget(self.state)
        self.camera=QLineEdit('external');row.addWidget(QLabel('Camera / 렌즈 ID'));row.addWidget(self.camera)
        self.camera_type=QComboBox();self.camera_type.addItems(['external','side','wrist']);row.addWidget(self.camera_type)
        self.split=QComboBox();self.split.addItems(['train','validation']);row.addWidget(self.split)
        button=QPushButton('사진·영상 등록');button.clicked.connect(lambda:self.guard(self.register_images));layout.addWidget(button)
        layout.addWidget(QLabel('Wrist는 실제 q·시각이 포함된 기존 Capture/Snapshot 등록을 사용합니다. 배치가 바뀌면 다른 ID를 쓰세요.'))
        self.images=QComboBox();layout.addWidget(self.images)
        advanced=QWidget();layout=QVBoxLayout(advanced);self.tabs.addTab(advanced,'고급 · 분석 물체/자산')
        layout.addWidget(QLabel('Codex 분석 결과와 자산 선택 · 치수는 Scene Memo에 자유롭게 적으세요. 미입력 치수는 실측으로 취급하지 않습니다.'))
        self.objects=QTableWidget(0,6);self.objects.setHorizontalHeaderLabels(['Object ID','역할','Support ID','SAM 설명','USDA 자산','물체 종류'])
        self.objects.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(self.objects,1)
        add=QPushButton('물체 행 추가');add.clicked.connect(lambda:self.add_object({}));layout.addWidget(add)
        remove=QPushButton('선택 물체 삭제');remove.clicked.connect(self.remove_objects);layout.addWidget(remove)
        settings=QWidget();form=QFormLayout(settings);self.tabs.addTab(settings,'기존 모델 환경')
        board=QPushButton('고급 진단 · 측정 보드 코너 지정 (선택)');board.clicked.connect(lambda:self.guard(self.board_corners));form.addRow(board)
        self.paths={}
        for kind,label in(('sam','SAM 3.1'),('da3','DA3-SMALL')):
            for key,title in(('python','Python 실행 파일'),('model','로컬 Checkpoint / Model')):
                panel=QWidget();r=QHBoxLayout(panel);r.setContentsMargins(0,0,0,0)
                edit=QLineEdit(self.saved.get(kind,{}).get(key,''));self.paths[kind,key]=edit;r.addWidget(edit,1)
                choose=QPushButton('선택');choose.clicked.connect(lambda _,e=edit,k=kind,f=key:self.choose_path(e,k,f));r.addWidget(choose)
                form.addRow(label+' '+title,panel)
        form.addRow(QLabel('설치·다운로드 없이 지정한 기존 환경을 순서대로 실행합니다. 경로는 Project에 저장됩니다.'))
        asset_page=QWidget();assets=QVBoxLayout(asset_page);self.tabs.addTab(asset_page,'USDA·Codex 모델링')
        self.asset_list=QComboBox();assets.addWidget(self.asset_list)
        register=QPushButton('기존 USDA 자산 등록');register.clicked.connect(lambda:self.guard(self.register_asset));assets.addWidget(register)
        publish=QPushButton('선택 Legacy 자산을 공용 Library에 등록');publish.clicked.connect(lambda:self.guard(self.publish_asset));assets.addWidget(publish)
        handoff=QPushButton('Codex 모델링 작업자료 열기');handoff.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.root/'scratch/agent'/self.candidate.text()/'modeling'))));assets.addWidget(handoff)
        codegen=QPushButton('Codex 분석·제작·정합 이어서 실행');codegen.clicked.connect(lambda:self.guard(lambda:self.run(run_modeling=True)));assets.addWidget(codegen)
        assets.addWidget(QLabel('연속 실행은 Codex 분석·Blender 제작 후 등록 결과를 읽어 정합을 이어갑니다. 기본 분석·모델링 최대 6회, 비교 검토 최대 3회입니다.\n비교 검토가 형상 수정을 요청하면 새 자산 버전을 제작합니다. Camera K·행렬 입력은 필요하지 않습니다.'));assets.addStretch()
        review=QWidget();r=QVBoxLayout(review);self.tabs.addTab(review,'Mask·상태')
        self.mask_object=QComboBox();r.addWidget(self.mask_object)
        self.mask_index=QComboBox();r.addWidget(self.mask_index);self.mask_index.currentIndexChanged.connect(self.show_mask)
        self.mask_preview=QLabel('추론 후 사진·물체를 선택하세요');self.mask_preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.mask_preview.setMinimumHeight(200);r.addWidget(self.mask_preview,1)
        choose=QPushButton('선택 Mask 사용');choose.clicked.connect(lambda:self.guard(self.select_mask));r.addWidget(choose)
        edited=QPushButton('수정한 원본 해상도 Mask PNG 선택');edited.clicked.connect(lambda:self.guard(self.edited_mask));r.addWidget(edited)
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);r.addWidget(self.summary,1)
        actions=QHBoxLayout();box.addLayout(actions);self.candidate=QLineEdit(self.saved.get('candidate')or self.project.state.get('candidate')or'auto_'+time.strftime('%Y%m%d_%H%M%S'));actions.addWidget(QLabel('Candidate'));actions.addWidget(self.candidate)
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
        for name,query in self.saved.get('objects',{}).items():
            if name not in specs:self.add_object({'id':name,'kind':'mesh','role':query.get('role','manipulable_object')})
        for obj in self.scene['objects']:
            query=self.saved.get('objects',{}).get(obj['id'],{})
            if query.get('role')and query['role']!=obj['role']:self.restore_conflicts.append(obj['id']+': saved role conflicts with Current Scene')
            measured=next((r for r in self.saved.get('measurements',[])if r['id']==obj['id']),None)
            if measured and obj['dimensions']['provenance']in('measured','calibrated'):
                if measured.get('dimensions_m')!=obj['dimensions']['value']:self.restore_conflicts.append(obj['id']+': saved dimensions conflict with protected Current Scene')
        if self.restore_conflicts:self.summary.setPlainText('\n'.join(self.restore_conflicts))
        self.objects.itemChanged.connect(self.sync_object_names)
        self.images.currentIndexChanged.connect(self.reload_masks);self.mask_object.currentIndexChanged.connect(self.reload_masks)
        self.state.currentTextChanged.connect(self.refresh_images);self.refresh_assets();self.refresh_images()

    def guard(self,fn):
        try:fn()
        except(Exception)as error:QMessageBox.warning(self,'Auto Reconstruction',str(error))

    def add_object(self,spec):
        row=self.objects.rowCount();self.objects.insertRow(row);name=spec.get('id','')
        query=self.saved.get('objects',{}).get(name,{})
        values=[name,spec.get('role','manipulable_object'),self.saved.get('fitting',{}).get('supports',{}).get(name,''),query.get('prompt','')]
        for col,value in enumerate(values):self.objects.setItem(row,col,QTableWidgetItem(str(value)))
        choice=QComboBox();choice.addItem('독립 모델링 / 기존 유지','');choice.addItem('검토 후 새 모델링','__new_model__');self.objects.setCellWidget(row,4,choice)
        choice.setProperty('saved_manifest',query.get('asset_manifest')or('__new_model__'if query.get('modeling_action')=='new'else''))
        choice.setProperty('request_id',query.get('modeling_request_id',''))
        choice.activated.connect(lambda _index,c=choice:self.object_asset_choice(c))
        self.objects.setItem(row,5,QTableWidgetItem(query.get('category','')))
        self.mask_object.addItem(name,name)

    def object_asset_choice(self,choice):
        # Editing one instance never edits another, including an existing shared asset.
        choice.setProperty('request_id','request_'+__import__('uuid').uuid4().hex if choice.currentData()=='__new_model__'else'')

    def configuration(self):
        if self.restore_conflicts:raise ValueError('\n'.join(self.restore_conflicts))
        result=copy.deepcopy(self.saved);result['scene_state_id']=self.state.currentText().strip();result.setdefault('objects',{})
        result['candidate']=self.candidate.text().strip()
        supports=result.setdefault('fitting',{}).setdefault('supports',{});requests={}
        for row in range(self.objects.rowCount()):
            values=[self.objects.item(row,col).text().strip()for col in range(4)];name,role,*_=values
            if not name:continue
            query=result['objects'].setdefault(name,{})
            query['role']=role
            query['category']=self.objects.item(row,5).text().strip()
            asset=self.objects.cellWidget(row,4).currentData()
            if asset=='__new_model__':
                query['modeling_action']='new';query.pop('asset_manifest',None)
                choice=self.objects.cellWidget(row,4)
                key=name
                request=requests.setdefault(key,choice.property('request_id')or('request_'+__import__('uuid').uuid4().hex))
                choice.setProperty('request_id',request);query['modeling_request_id']=request
            elif asset:
                query['asset_manifest']=asset;query.pop('modeling_action',None);query.pop('modeling_request_id',None)
            else:
                query.pop('asset_manifest',None);query.pop('modeling_action',None);query.pop('modeling_request_id',None)
            if values[3]:result['objects'].setdefault(name,{})['prompt']=values[3]
            if values[2]:supports[name]=values[2]
            else:supports.pop(name,None)
        for(kind,key),edit in self.paths.items():result.setdefault(kind,{})[key]=edit.text().strip()
        for key in self.deleted_objects:
            result['objects'].pop(key,None);supports.pop(key,None)
            for selections in result.get('selections',{}).values():selections.pop(key,None)
        return result

    def remove_objects(self):
        for row in sorted({i.row()for i in self.objects.selectedIndexes()},reverse=True):
            self.deleted_objects.add(self.objects.item(row,0).text().strip());self.objects.removeRow(row)
        self.sync_object_names()

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

    def refresh_assets(self):
        # Metadata only in Qt. USD validation/conversion stays in Backend CLI.
        from .object_assets import list_object_assets
        records=list_object_assets(self.project)
        self.asset_list.clear()
        for record in records:self.asset_list.addItem(('Workspace · 'if record['manifest'].startswith('../../object_assets/')else'Legacy · ')+record['asset_id']+' · '+record['version'][:8]+' · '+(record.get('error')or record['collision_status']),record['manifest'])
        for row in range(self.objects.rowCount()):
            combo=self.objects.cellWidget(row,4);selected=combo.currentData()or combo.property('saved_manifest');combo.clear();combo.addItem('자동 판정 / 기존 유지','');combo.addItem('검토 후 새 모델링','__new_model__')
            for record in records:combo.addItem(('Workspace · 'if record['manifest'].startswith('../../object_assets/')else'Legacy · ')+record['asset_id']+' · '+record['version'][:8],record['manifest'])
            if selected and combo.findData(selected)<0:combo.addItem('선택 자산 확인 필요 · '+str(selected),selected)
            index=combo.findData(selected);combo.setCurrentIndex(max(0,index))

    def publish_asset(self):
        manifest=self.asset_list.currentData()
        if not manifest:raise ValueError('등록할 Legacy 자산을 선택하세요.')
        self.start_cli(['object-asset',str(self.project.root),'publish','--manifest',manifest])

    def register_asset(self):
        path,_=QFileDialog.getOpenFileName(self,'물체 단위 USDA 선택','','USDA (*.usda)')
        if not path:return
        name,ok=QInputDialog.getText(self,'USDA 등록','Asset ID',text=Path(path).stem)
        if ok:self.start_cli(['object-asset',str(self.project.root),'register','--id',name,'--path',path])

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
                                 '--scene-state',self.state.currentText().strip(),'--split',self.split.currentText()])

    def run(self,*,run_modeling=False):
        if self.temporary:self.temporary.cleanup()
        self.temporary=tempfile.TemporaryDirectory(prefix='real2sim-reconstruct-')
        config=Path(self.temporary.name)/'configuration.yaml';self.saved=self.configuration();write(config,self.saved)
        args=['refit-pairs'if self.refit else'reconstruct',str(self.project.root),'--candidate',self.candidate.text().strip(),'--config',str(config)]
        if self.refit:args+=['--scene-state',self.state.currentText().strip()]
        if run_modeling:args+=['--run-modeling']
        self.start_cli(args)
        self.tabs.setCurrentIndex(3);self.summary.setPlainText('자동 재구성 실행 중…')

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
        if getattr(self,'operation',None)=='modeling-run'and self.process.exitCode()==0:
            self.saved=read(self.project.root/'input/reconstruction.yaml')
            existing={self.objects.item(row,0).text()for row in range(self.objects.rowCount())}
            for name,spec in self.saved.get('objects',{}).items():
                if name not in existing:self.add_object({'id':name,'kind':'mesh','role':spec.get('role','fixture')})
        self.logs();self.refresh_assets();self.refresh_images();path=self.project.root/'scratch/agent'/self.candidate.text()/'reconstruction.json'
        if self.process.exitCode()not in(0,2):
            self.summary.setPlainText('실행 실패 (exit '+str(self.process.exitCode())+')\n'+self.summary.toPlainText())
        elif self.operation in('reconstruct','refit-pairs')and path.is_file():
            report=read(path);stages=report.get('stages',{})
            self.summary.setPlainText(report['status']+'\n'+'\n'.join(k+': '+str(v.get('status',v.get('attached','')))for k,v in stages.items())+'\n'+'\n'.join(report.get('needs',[])))
        if self.temporary:self.temporary.cleanup();self.temporary=None
        if self.pending_close:self.close()

    def refresh_images(self):
        selected=self.images.currentData();self.images.blockSignals(True);self.images.clear()
        for image in self.project.evidence['images']:
            if image.get('id')and image.get('scene_state_id')==self.state.currentText():self.images.addItem(image['id']+' · '+image.get('registration_status','Capture')+' · '+image['split'],image['id'])
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
