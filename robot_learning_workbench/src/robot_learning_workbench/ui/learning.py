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
