"""Display official ACT loss only; no model, optimizer or custom trainer."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter,QPen,QPolygonF
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
        painter=QPainter(self);painter.fillRect(self.rect(),Qt.GlobalColor.white);painter.setPen(Qt.GlobalColor.black);painter.drawText(12,18,'공식 Training Loss')
        points=[p for p in self.points if math.isfinite(p['loss'])]
        if not points:painter.drawText(12,48,'공식 loss 로그 대기');return
        minimum=min(p['loss'] for p in points);maximum=max(p['loss'] for p in points);first=points[0]['step'];last=points[-1]['step']
        poly=QPolygonF([QPointF(25+(self.width()-45)*(p['step']-first)/max(1,last-first),30+(self.height()-55)*(maximum-p['loss'])/max(1e-12,maximum-minimum)) for p in points])
        painter.setPen(QPen(Qt.GlobalColor.blue,2));painter.drawPolyline(poly)
        for point in poly:painter.drawEllipse(point,3,3)
        painter.setPen(Qt.GlobalColor.black);painter.drawText(12,self.height()-8,f"step {last} · loss {points[-1]['loss']:.6g}")


class TrainingSettings(QWidget):
    """Edit only the existing official JSON; save a new file before Recipe reuse."""
    def __init__(self,page):
        from PyQt6.QtWidgets import QHBoxLayout,QPushButton,QSpinBox,QComboBox,QLabel,QCheckBox
        super().__init__(page);self.page=page;self.config=None;row=QHBoxLayout(self)
        load=QPushButton('공식 Config 읽기');save=QPushButton('수정 Config 새 파일로 저장')
        self.steps=QSpinBox();self.steps.setRange(1,10000000);self.batch=QSpinBox();self.batch.setRange(1,65536);self.device=QComboBox();self.device.addItems(['cpu','cuda']);self.model=QComboBox();self.model.addItems(['act','smolvla']);self.pretrained=QCheckBox('SmolVLA 캐시된 VLM 가중치 사용');self.pretrained.setEnabled(False)
        for widget in (load,QLabel('누적 steps'),self.steps,QLabel('batch'),self.batch,self.device,self.model,self.pretrained,save):row.addWidget(widget)
        load.clicked.connect(self.load);save.clicked.connect(self.save)
        self.steps.valueChanged.connect(self.edited);self.batch.valueChanged.connect(self.edited);self.device.currentTextChanged.connect(self.edited);self.model.currentTextChanged.connect(self.edited);self.pretrained.toggled.connect(self.edited)
    def edited(self,*_):
        self.page.edit_error=True;self.page.invalidate();self.page.state.setText('Config 편집 중 · 새 파일로 저장하세요')
    def load(self):
        import json
        from pathlib import Path
        try:
            data=json.loads(Path(self.page.inputs['training_config'].text()).read_text())
            if data['policy']['type'] not in ('act','smolvla'):raise ValueError('ACT 또는 SmolVLA 공식 Config가 필요합니다')
            self.model.setCurrentText(data['policy']['type']);self.pretrained.setEnabled(data['policy']['type']=='smolvla');self.pretrained.setChecked(data['policy'].get('load_vlm_weights',False))
            self.config=data;self.steps.setValue(data['steps']);self.batch.setValue(data['batch_size']);self.device.setCurrentText(data['policy']['device']);self.page.edit_error=False
        except Exception as error:self.page.state.setText(str(error))
    def save(self):
        import json,copy
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog
        if self.config is None:self.page.state.setText('먼저 ACT Config를 읽으세요');return
        path,_=QFileDialog.getSaveFileName(self,'새 공식 ACT JSON Config','','JSON (*.json)')
        if not path:return
        try:
            target=Path(path).resolve()
            if target.is_relative_to('/home/hyeonhee/soarm_isaaclab') or target.is_relative_to('/home/hyeonhee/miniconda3') or target.is_relative_to('/home/hyeonhee/IsaacLab'):raise ValueError('보존 원본/SDK 안에 저장할 수 없습니다')
            if self.model.currentText()!=self.config['policy']['type']:raise ValueError('선택 모델의 실제 공식 Config를 먼저 읽으세요. 모델별 파라미터를 임의 변환하지 않습니다')
            data=copy.deepcopy(self.config);data['steps']=self.steps.value();data['batch_size']=self.batch.value();data['policy']['device']=self.device.currentText()
            if data['policy']['type']=='smolvla':data['policy']['load_vlm_weights']=self.pretrained.isChecked()
            base=self.page.editor.path.parent
            data['output_dir']=str((base/self.page.output.text()).resolve());data['dataset']['root']=str((base/self.page.inputs['dataset'].text()).resolve());data['resume']=self.page.mode.currentText()=='resume'
            with target.open('x') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
            self.page.inputs['training_config'].setText(str(target));self.page.edit_input('training_config',str(target));self.page.edit_error=False;self.page.state.setText('새 Config 저장됨 · Recipe를 저장하고 다시 검사하세요')
        except Exception as error:self.page.state.setText(str(error))
