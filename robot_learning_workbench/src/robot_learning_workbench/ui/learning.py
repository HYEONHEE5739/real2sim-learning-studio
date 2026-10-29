"""Display official ACT loss only; no model, optimizer or custom trainer."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter,QPen,QPolygonF,QColor
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QWidget


class LossChart(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.points=[];self.setMinimumHeight(130)
    def add_text(self,text):
        from ..learning.train import parse_metrics
        values={row['step']:row for row in self.points}
        values.update({row['step']:row for row in parse_metrics(text)})
        self.points=[values[k] for k in sorted(values)];self.update()
    def paintEvent(self,event):
        import math
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#17212b'));painter.setPen(QColor('#eeeeee'));painter.drawText(12,18,'공식 Training Loss')
        points=[p for p in self.points if math.isfinite(p['loss'])]
        if not points:painter.drawText(12,48,'공식 loss 로그 대기');return
        minimum=min(p['loss'] for p in points);maximum=max(p['loss'] for p in points);first=points[0]['step'];last=points[-1]['step']
        poly=QPolygonF([QPointF(25+(self.width()-45)*(p['step']-first)/max(1,last-first),30+(self.height()-55)*(maximum-p['loss'])/max(1e-12,maximum-minimum)) for p in points])
        painter.setPen(QPen(QColor('#4ed6ba'),2));painter.drawPolyline(poly)
        for point in poly:painter.drawEllipse(point,3,3)
        painter.setPen(QColor('#eeeeee'));painter.drawText(12,self.height()-8,f"step {last} · loss {points[-1]['loss']:.6g}")


class TrainingSettings(QWidget):
    """Edit only the existing official JSON; save a new file before Recipe reuse."""
    def __init__(self,page):
        from PyQt6.QtWidgets import QFormLayout,QGridLayout,QPushButton,QSpinBox,QComboBox,QLabel,QCheckBox,QVBoxLayout,QPlainTextEdit
        super().__init__(page);self.page=page;self.config=None;layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        load=QPushButton('공식 Config 읽기');save=QPushButton('수정 Config 새 파일로 저장');layout.addWidget(load)
        form=QFormLayout();form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows);layout.addLayout(form)
        self.steps=QSpinBox();self.steps.setRange(1,10000000);self.batch=QSpinBox();self.batch.setRange(1,65536);self.device=QComboBox();self.device.addItems(['cpu','cuda']);self.model=QComboBox();self.model.setPlaceholderText('설치 Registry 확인 필요');self.pretrained=QCheckBox('SmolVLA 캐시 VLM 가중치 사용');self.pretrained.setEnabled(False)
        for label,widget in (('학습 모델',self.model),('누적 Steps',self.steps),('Batch',self.batch),('Device',self.device)):form.addRow(label,widget)
        self.support_label=QLabel('ACT / SmolVLA / Diffusion: smoke 검증 · 다른 Registry 모델은 별도 입력/의존성 검증 필요');self.support_label.setWordWrap(True);layout.addWidget(self.support_label);layout.addWidget(self.pretrained)
        config_toggle=QCheckBox('고급: 공식 Policy JSON');layout.addWidget(config_toggle)
        self.policy_json=QPlainTextEdit();self.policy_json.setPlaceholderText('모델별 실제 공식 Policy Config');self.policy_json.setMaximumHeight(180);self.policy_json.hide();layout.addWidget(self.policy_json);config_toggle.toggled.connect(self.policy_json.setVisible)
        self.policy_json.textChanged.connect(self.edited)
        create=QPushButton('선택 모델의 공식 기본 Config');layout.addWidget(create);create.clicked.connect(self.create);layout.addWidget(save)
        from .jobs import BackendJob
        from PyQt6.QtCore import QTimer
        self.job=BackendJob(page.backend_python,self);self.job.finished.connect(self.received);self.operation='catalog'
        self.catalog_started=False
        load.clicked.connect(self.load);save.clicked.connect(self.save)
        self.steps.valueChanged.connect(self.edited);self.batch.valueChanged.connect(self.edited);self.device.currentTextChanged.connect(self.edited);self.model.currentTextChanged.connect(self.edited);self.pretrained.toggled.connect(self.edited)
    def showEvent(self,event):
        super().showEvent(event)
        if not self.catalog_started:
            self.catalog_started=True;self.operation='catalog';self.job.start('policy_catalog')
    def edited(self,*_):
        self.page.edit_error=True;self.page.invalidate();self.page.state.setText('Config 편집 중 · 새 파일로 저장하세요')
    def load(self):
        import json
        from pathlib import Path
        try:
            data=json.loads(Path(self.page.inputs['training_config'].text()).read_text())
            if self.model.findText(data['policy']['type'])<0:self.model.addItem(data['policy']['type'])
            self.policy_json.setPlainText(json.dumps(data['policy'],ensure_ascii=False,indent=2))
            self.model.setCurrentText(data['policy']['type']);self.pretrained.setEnabled(data['policy']['type']=='smolvla');self.pretrained.setChecked(data['policy'].get('load_vlm_weights',False))
            self.config=data;self.steps.setValue(data['steps']);self.batch.setValue(data['batch_size']);self.device.setCurrentText(data['policy']['device']);self.page.edit_error=False
        except Exception as error:self.page.state.setText(str(error))
    def save(self):
        import json,copy
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog
        if self.config is None:self.page.state.setText('공식 Config를 읽거나 생성하세요');return
        path,_=QFileDialog.getSaveFileName(self,'새 공식 LeRobot JSON Config',str(self.page.workspace/'policy'/'training-config.json'),'JSON (*.json)')
        if not path:return
        try:
            target=Path(path).resolve()
            if target.is_relative_to('/home/hyeonhee/soarm_isaaclab') or target.is_relative_to('/home/hyeonhee/miniconda3') or target.is_relative_to('/home/hyeonhee/IsaacLab'):raise ValueError('보존 원본/SDK 안에 저장할 수 없습니다')
            if self.model.currentText()!=self.config['policy']['type']:raise ValueError('선택 모델의 실제 공식 Config를 먼저 읽으세요. 모델별 파라미터를 임의 변환하지 않습니다')
            data=copy.deepcopy(self.config);data['policy']=json.loads(self.policy_json.toPlainText());data['steps']=self.steps.value();data['batch_size']=self.batch.value();data['policy']['device']=self.device.currentText()
            if data['policy']['type']=='smolvla':data['policy']['load_vlm_weights']=self.pretrained.isChecked()
            if data['policy'].get('type')!=self.model.currentText():raise ValueError('Policy JSON과 선택 모델이 다릅니다')
            if self.page.mode.currentText()=='finetune':
                from ..recipe import policy_model_path
                data['policy']['pretrained_path']=str(policy_model_path(self.page.editor.path.parent/self.page.inputs['policy'].text()))
            base=self.page.editor.path.parent
            data['output_dir']=str((base/self.page.output.text()).resolve());data['dataset']['root']=str((base/self.page.inputs['dataset'].text()).resolve());data['resume']=self.page.mode.currentText()=='resume'
            with target.open('x') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
            self.page.inputs['training_config'].setText(str(target));self.page.edit_input('training_config',str(target));self.page.edit_error=False;self.page.state.setText('새 Config 저장됨 · Recipe를 저장하고 다시 검사하세요')
        except Exception as error:self.page.state.setText(str(error))

    def create(self):
        if self.page.editor.path is None:self.page.state.setText('저장 Recipe를 먼저 여세요');return
        base=self.page.editor.path.parent
        try:
            self.job.start('training_config',policy_type=self.model.currentText(),dataset=str((base/self.page.inputs['dataset'].text()).resolve()),output=str((base/self.page.output.text()).resolve()));self.operation='create'
        except Exception as error:self.page.state.setText(str(error))
    def received(self,result):
        import json
        if not result.get('ok'):self.page.state.setText(result['error']['message']);return
        if self.operation=='catalog':
            current=self.model.currentText();self.model.clear()
            for row in result['result']['policies']:
                self.model.addItem(row['type']);self.model.setItemData(self.model.count()-1,json.dumps(row,ensure_ascii=False),Qt.ItemDataRole.ToolTipRole)
            if current:self.model.setCurrentText(current)
        else:
            self.config=result['result']['config'];self.policy_json.setPlainText(json.dumps(self.config['policy'],ensure_ascii=False,indent=2));self.steps.setValue(self.config['steps']);self.batch.setValue(self.config['batch_size']);self.device.setCurrentText(self.config['policy']['device']);self.edited()
