"""Presentation widgets ported from the original SO101 workflow UI.

CameraView preserves the original implementation; no engine/device ownership.
Source: soarm101_lab/workflow/view.py (see docs/ui-original-restoration.md).
"""
from pathlib import Path
from PyQt6.QtCore import Qt,QPointF,QEvent,pyqtSignal
from PyQt6.QtGui import QPainter,QPixmap,QPen,QColor,QPolygonF
from PyQt6.QtWidgets import QLabel,QSizePolicy,QSlider,QStyleOptionSlider,QStyle,QToolTip


class CameraView(QLabel):
    def __init__(self, text='', minimum=(120, 90)):
        super().__init__(text)
        self.setMinimumSize(*minimum)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_signature = None

    def show_image(self, path):
        try:
            path=Path(path);stat=path.stat()
        except OSError:return
        signature=(str(path),stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        current=self.pixmap()
        if signature==self._image_signature and current is not None and not current.isNull():return
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.setPixmap(pixmap);self._image_signature=signature

    def paintEvent(self, event):
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = pix.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x, y = (self.width() - size.width()) // 2, (self.height() - size.height()) // 2
        painter.drawPixmap(x, y, size.width(), size.height(), pix)


class EventTimeline(QSlider):
    """Recorded event markers share the slider's native frame-to-pixel mapping."""
    eventPicked=pyqtSignal(int)
    LABELS={'approach':'접근','grasp':'집기','transport':'이동','place':'놓기'}
    COLORS=('#efb467','#55d6b0','#69b9ff','#d196fa')

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal);self.markers=[];self.setMinimumHeight(38)

    def set_events(self,events,timestamps=None,dt=1/30):
        self.markers=[]
        for order,(name,frame) in enumerate(sorted(events.items(),key=lambda item:(item[1],item[0]))):
            stamp=float(timestamps[frame]-timestamps[0]) if timestamps is not None else frame*dt
            label=self.LABELS.get(name,name)
            self.markers.append(dict(name=name,frame=frame,time=stamp,label=label,color=self.COLORS[order%len(self.COLORS)]))
        self.update()

    def marker_position(self,frame):
        option=QStyleOptionSlider();self.initStyleOption(option)
        groove=self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderGroove,self)
        handle=self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,self)
        span=max(0,groove.width()-handle.width())
        offset=QStyle.sliderPositionFromValue(self.minimum(),self.maximum(),frame,span,option.upsideDown)
        return QPointF(groove.x()+handle.width()/2+offset,groove.center().y())

    def markers_at(self,point):
        return sorted((m for m in self.markers if abs(self.marker_position(m['frame']).x()-point.x())<=7
                       and abs(self.marker_position(m['frame']).y()-point.y())<=16),
                      key=lambda m:abs(self.marker_position(m['frame']).x()-point.x()))

    def paintEvent(self,event):
        super().paintEvent(event);painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for marker in self.markers:
            point=self.marker_position(marker['frame']);x,y=point.x(),point.y()
            painter.setPen(QPen(QColor(marker['color']),2));painter.drawLine(QPointF(x,y-6),QPointF(x,y+7))
            painter.setBrush(QColor(marker['color']))
            painter.drawPolygon(QPolygonF([QPointF(x,y-8),QPointF(x-4,y-13),QPointF(x+4,y-13)]))
        painter.end()

    def mousePressEvent(self,event):
        hits=self.markers_at(event.position())
        if event.button()==Qt.MouseButton.LeftButton and hits:
            self.eventPicked.emit(hits[0]['frame']);event.accept();return
        super().mousePressEvent(event)

    def event(self,event):
        if event.type()==QEvent.Type.ToolTip:
            hits=self.markers_at(event.pos())
            if hits:
                QToolTip.showText(event.globalPos(),'\n'.join(f"{m['label']} ({m['name']}) · {m['time']:.2f}s · {m['frame']+1} frame" for m in hits),self)
                return True
        return super().event(event)
