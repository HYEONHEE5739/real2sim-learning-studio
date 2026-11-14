"""Workspace Library UI; all USD/disk mutations use the existing backend job."""
from PyQt6.QtCore import Qt,QProcess,QTimer
from PyQt6.QtGui import QIcon,QPixmap
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QListWidget,QListWidgetItem,QLabel,QComboBox,QPushButton,QFileDialog,QInputDialog,QSlider,QSpinBox,QGridLayout,QWidget,QScrollArea,QSizePolicy
from .jobs import BackendJob
from .asset_viewport import AssetViewport


class ObjectLibraryDialog(QDialog):
    def __init__(self,project,python,parent=None):
        super().__init__(parent);self.project=str(project);self.assets=[];self.selected=None;self.operation=None;self.closed=False;self.pending=None
        self.setWindowTitle('Object Library · Workspace 공유 자산');self.resize(1050,820)
        layout=QVBoxLayout(self);self.search=QLineEdit();self.search.setPlaceholderText('Asset ID / 이름 검색');layout.addWidget(self.search)
        body=QHBoxLayout();layout.addLayout(body,1);self.items=QListWidget();body.addWidget(self.items,1)
        right=QVBoxLayout();body.addLayout(right,3);self.version=QComboBox();right.addWidget(self.version);self.view=AssetViewport();self.view.setMinimumHeight(240);right.addWidget(self.view,1)
        sliders=QHBoxLayout();right.addLayout(sliders)
        for attribute,title,initial in [('opacity','Visual',100),('visible_opacity','Collision Front',0),('hidden_opacity','Collision Hidden',0)]:
            column=QVBoxLayout();sliders.addLayout(column,1);label=QLabel(f'{title} {initial}%');label.setWordWrap(True);column.addWidget(label)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(0,100);slider.setValue(initial);column.addWidget(slider)
            setattr(self,attribute,slider);setattr(self,attribute+'_label',label)
        self.opacity.setToolTip('Visual의 색상만 숨기거나 투명하게 합니다. Collision의 앞/뒤 판정을 위한 Depth는 유지합니다.')
        info=QHBoxLayout();right.addLayout(info);self.details=QLabel('Object를 선택하세요.');self.details.setWordWrap(True);self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);info.addWidget(self.details,1)
        self.reset=QPushButton('Reset View');info.addWidget(self.reset);self.reset.clicked.connect(self.view.reset_view)
        self.advanced=QPushButton('▸ Advanced / Debug');self.advanced.setCheckable(True);right.addWidget(self.advanced)
        self.advanced_panel=QScrollArea();self.advanced_panel.setWidgetResizable(True);self.advanced_panel.setMinimumHeight(96);self.advanced_panel.setMaximumHeight(180)
        content=QWidget();self.advanced_panel.setWidget(content);wire=QGridLayout(content);right.addWidget(self.advanced_panel);self.advanced_panel.hide()
        wire.addWidget(QLabel('Edge Mode'),0,0);self.edge_mode=QComboBox();self.edge_mode.addItem('Feature Edges','feature');self.edge_mode.addItem('All Edges','all');wire.addWidget(self.edge_mode,0,1)
        wire.addWidget(QLabel('Feature Angle'),0,2);self.feature_angle=QSpinBox();self.feature_angle.setRange(0,180);self.feature_angle.setValue(25);self.feature_angle.setSuffix('°');wire.addWidget(self.feature_angle,0,3)
        wire.addWidget(QLabel('Collision Mode'),1,0);self.collision_mode=QComboBox()
        self.collision_mode.addItem('Visible Only','visible');self.collision_mode.addItem('X-Ray','xray');self.collision_mode.setCurrentIndex(1);wire.addWidget(self.collision_mode,1,1)
        self.collision_only=QPushButton('Collision Only');self.collision_only.setCheckable(True);wire.addWidget(self.collision_only,1,2,1,2)
        self.collision_only.setToolTip('불투명 Collision 면과 Edge를 진단합니다. 해제하면 기존 슬라이더 값으로 돌아갑니다.')
        self.edge_mode.setToolTip('Feature Edges: 주요 모서리와 현재 시점의 외곽선. All Edges: 전체 삼각형 진단.')
        self.legend=QLabel('청록 실선: 보이는 Collision · 주황 점선: 가려진 Collision (X-Ray)');self.legend.setWordWrap(True);wire.addWidget(self.legend,2,0,1,4)
        self.advanced_details=QLabel();self.advanced_details.setWordWrap(True);self.advanced_details.setTextFormat(Qt.TextFormat.PlainText)
        self.advanced_details.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.advanced_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);wire.addWidget(self.advanced_details,3,0,1,4)
        row=QHBoxLayout();layout.addLayout(row);self.candidate=QComboBox();self.candidate.setEditable(True);row.addWidget(QLabel('현재 Scene Candidate'));row.addWidget(self.candidate)
        self.object_id=QLineEdit();self.object_id.setPlaceholderText('새 인스턴스 / 기존 Object ID');row.addWidget(self.object_id)
        self.add=QPushButton('Candidate에 추가');row.addWidget(self.add);self.assign=QPushButton('기존 Object 버전 지정');row.addWidget(self.assign)
        actions=QHBoxLayout();layout.addLayout(actions);self.register=QPushButton('새 USDA 등록');self.publish=QPushButton('Library에 게시');self.refresh=QPushButton('새로고침')
        for b in(self.register,self.publish,self.refresh):actions.addWidget(b)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.job=BackendJob(python,self);self.job.finished.connect(self.received);self.job.log.connect(self.status.setText)
        self.search.textChanged.connect(self.populate);self.items.currentItemChanged.connect(self.choose);self.version.currentIndexChanged.connect(self.preview)
        self.collision_mode.currentIndexChanged.connect(self.display_changed);self.opacity.valueChanged.connect(self.display_changed)
        self.edge_mode.currentIndexChanged.connect(self.display_changed);self.feature_angle.valueChanged.connect(self.display_changed)
        self.visible_opacity.valueChanged.connect(self.display_changed);self.hidden_opacity.valueChanged.connect(self.display_changed)
        self.collision_only.toggled.connect(self.display_changed);self.advanced.toggled.connect(self.toggle_advanced)
        self.view.error.connect(self.status.setText);self.view.rendered.connect(self.thumbnail)
        self.add.clicked.connect(lambda:self.edit('instantiate'));self.assign.clicked.connect(lambda:self.edit('assign'));self.register.clicked.connect(self.register_usda);self.publish.clicked.connect(lambda:self.call('publish',manifest=self.manifest()));self.refresh.clicked.connect(lambda:self.call('list'))
        self.display_changed();self.call('list')
    def call(self,action,**args):
        if self.job.process.state()!=QProcess.ProcessState.NotRunning:
            if action in('preview','list'):self.pending=(action,args)
            return
        self.operation=action;self.status.setText('처리 중…');self.job.start('object_library',project=self.project,action=action,**args)
    def manifest(self):return self.version.currentData()
    def populate(self):
        self.items.clear();query=self.search.text().casefold()
        for name in sorted({r['asset_id']for r in self.assets if query in r['asset_id'].casefold()}):
            item=QListWidgetItem(name);item.setData(Qt.ItemDataRole.UserRole,name);self.items.addItem(item)
    def choose(self,item,old=None):
        self.version.blockSignals(True);self.version.clear()
        if item:
            for r in self.assets:
                if r['asset_id']==item.data(Qt.ItemDataRole.UserRole):self.version.addItem(r['version']+(' · 손상'if r.get('error')else''),r['manifest'])
        self.version.blockSignals(False);self.preview()
    def preview(self):
        self.view.load(None);self.details.setText('선택한 버전 검증/로딩 중…');self.advanced_details.clear();self.advanced_details.setToolTip('')
        if self.manifest():self.call('preview',manifest=self.manifest())
    def received(self,response):
        if self.closed:return
        if self.pending:
            action,args=self.pending;self.pending=None;QTimer.singleShot(0,lambda:self.call(action,**args))
            if self.operation=='preview':return
        if not response.get('ok'):self.status.setText(str(response.get('error',{}).get('message','작업 실패')));return
        data=response['result']
        if self.operation=='list':
            self.assets=data['assets'];self.candidate.clear();self.candidate.addItems(data['candidates']or['library_draft']);self.populate();self.status.setText('버전은 불변입니다. 선택한 Candidate에만 추가/지정됩니다.')
        elif self.operation=='preview':
            self.view.load(data)
            size=' × '.join('?'if v is None else f'{v*1000:g}'for v in data['dimensions']['value'])+' mm'
            validation={'AUTHORED_UNVALIDATED':'미검증','UNRESOLVED':'형상 미확정'}.get(data['collision_status'],'미확인')
            self.details.setText(f'크기: {size} · 충돌 검증: {validation}');self.status.clear()
            visual=[m for m in data['meshes']if m['kind']=='visual'];textures=sum(bool(m.get('texture_png'))for m in visual)
            self.advanced_details.setText(f"Object ID: {data['asset_id']} · Version: {data['version']}\nDimensions: {size} · Provenance: {data['dimensions']['provenance']}\nMaterial / Texture: Visual {len(visual)}개 · Texture {textures}개\nCollision: {data['collision_status']} · 물리 검증: "+('검증됨'if data.get('physical_verified')is True else'미검증'))
            self.advanced_details.setToolTip('\n'.join([data['material_scope'],*data['dimensions'].get('evidence',[])]))
        else:self.status.setText('완료 · '+str(data.get('status',data.get('version',''))));self.call('list')
    def display_changed(self):
        diagnostic=self.collision_only.isChecked();xray=self.collision_mode.currentData()=='xray'
        self.opacity.setEnabled(not diagnostic);self.visible_opacity.setEnabled(not diagnostic);self.hidden_opacity.setEnabled(xray and not diagnostic)
        self.feature_angle.setEnabled(self.edge_mode.currentData()=='feature')
        self.opacity_label.setText('Visual '+str(self.opacity.value())+'%')
        self.visible_opacity_label.setText('Collision Front '+str(self.visible_opacity.value())+'%')
        self.hidden_opacity_label.setText('Collision Hidden '+str(self.hidden_opacity.value())+'%')
        self.view.state.update(show_visual=not diagnostic,show_collision=diagnostic or self.visible_opacity.value()>0 or(xray and self.hidden_opacity.value()>0),
            collision_mode=self.collision_mode.currentData(),visual_opacity=self.opacity.value()/100.,
            edge_mode=self.edge_mode.currentData(),feature_angle=self.feature_angle.value(),
            visible_opacity=1. if diagnostic else self.visible_opacity.value()/100.,
            hidden_opacity=max(.2,self.hidden_opacity.value()/100.)if diagnostic else self.hidden_opacity.value()/100.)
        self.view.request_render()
    def show_collision_only(self):
        self.collision_only.setChecked(True)
    def toggle_advanced(self,checked):
        self.advanced_panel.setVisible(checked);self.advanced.setText(('▾ 'if checked else'▸ ')+'Advanced / Debug')
    def thumbnail(self,image):
        item=self.items.currentItem()
        if item:item.setIcon(QIcon(QPixmap.fromImage(image.scaled(96,96,Qt.AspectRatioMode.KeepAspectRatio))))
    def edit(self,action):
        if self.manifest()and self.object_id.text().strip():self.call(action,manifest=self.manifest(),candidate=self.candidate.currentText(),object_id=self.object_id.text().strip())
    def register_usda(self):
        file,_=QFileDialog.getOpenFileName(self,'새 Object USDA 등록','','USD ASCII (*.usda)')
        if not file:return
        name,ok=QInputDialog.getText(self,'Object Identity','Asset ID (명시적 새 자산/새 버전)')
        if ok and name.strip():self.call('register',path=file,asset_id=name.strip())
    def closeEvent(self,event):self.closed=True;self.view.close();self.job.stop();super().closeEvent(event)
