"""Presentation widgets ported from the original SO101 workflow UI.

CameraView preserves the original implementation; no engine/device ownership.
Source: soarm101_lab/workflow/view.py (see docs/ui-original-restoration.md).
"""
from pathlib import Path
from PyQt6.QtCore import Qt,QPointF,QEvent,pyqtSignal,QTimer
from PyQt6.QtGui import QPainter,QPixmap,QPen,QColor,QPolygonF
from PyQt6.QtWidgets import QLabel,QSizePolicy,QSlider,QStyleOptionSlider,QStyle,QToolTip,QVBoxLayout,QHBoxLayout,QWidget,QScrollArea,QDialog,QLayout,QAbstractScrollArea,QTabWidget


def capture_progress_text(progress):
    """Show what is pending; saving and motion authorization are independent."""
    if not progress.get('capture_pending'):return '원하는 순간 캡처하세요. 움직임·정합 품질은 촬영별로 기록합니다.'
    labels={'acquiring':'최신 영상·관절 정합 확인 중','prepare':'영상·측정값 저장 중',
            'render':'같은 자세의 Sim 영상 대기 중','finish':'Capture 등록 중','pending':'저장 대기 · 관측 보존됨'}
    labels.update(queued='원본 저장 대기',raw_saved='원본 저장 완료 · 후처리 대기',sim_pair='같은 측정 q의 Sim/Pair 처리 중',registering='Evidence 등록 중')
    text=labels.get(progress.get('capture_phase'),'캡처 중…')
    if progress.get('capture_queue_capacity'):
        text+=f" · 처리 중 {progress.get('capture_queue_size',0)}/{progress['capture_queue_capacity']}"
        if progress.get('capture_request_allowed'):text+=' · 추가 촬영 가능'
    elapsed=progress.get('capture_elapsed_s')
    if isinstance(elapsed,(int,float)):text+=f' · {elapsed:.1f}초'
    if progress.get('teleop_active')is False and progress.get('teleoperation_available',True):text+=' · Teleop 중지됨'
    return text


class LiveCameraArea(QWidget):
    """Give word-wrapped page layouts a flexible camera height, not RGB height."""
    def sizeHint(self):return self.minimumSizeHint().expandedTo(self.minimumSize())


class LiveSessionTabs(QTabWidget):
    """Hidden workflow tabs must not enlarge a scrollable live session window."""
    def __init__(self,parent=None):
        super().__init__(parent);self.currentChanged.connect(self.updateGeometry)

    def minimumSizeHint(self):
        size=super().minimumSizeHint();page=self.currentWidget()
        if page is not None and hasattr(page,'session_layout'):
            size.setHeight(page.minimumSizeHint().height()+self.tabBar().sizeHint().height()+4)
        return size


class LiveSessionLayout(QVBoxLayout):
    """Scrollable live page, right-hand popup tools and pinned control buttons.

    Each modeless popup owns the original widget for the page's lifetime, so
    closing a window never loses live rows, selection, memo text or log messages.
    """
    def __init__(self,page):
        super().__init__(page);self.page=page;self.camera_area=None;self.action_area=None;self.popups=[]
        self.setSpacing(6)
        self.header=QHBoxLayout();self.header.addStretch(1);self.tools=QHBoxLayout();self.header.addLayout(self.tools);self.addLayout(self.header)
        self.page_scroll=QScrollArea();self.page_scroll.setWidgetResizable(True);self.page_scroll.setMinimumSize(0,0)
        self.content=QWidget();self.content_layout=QVBoxLayout(self.content);self.content_layout.setContentsMargins(0,0,0,0);self.content_layout.setSpacing(6)
        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize);self.page_scroll.setWidget(self.content)
        self.addWidget(self.page_scroll,1)
        self.action_bar=QWidget();self.actions=QHBoxLayout(self.action_bar);self.actions.setContentsMargins(0,0,0,0)
        self.footer=QHBoxLayout();self.footer.setSpacing(0);self.footer.addWidget(self.action_bar,1);self.footer.addStretch(0);self.addLayout(self.footer)
        self.resize_timer=QTimer(page);self.resize_timer.setSingleShot(True);self.resize_timer.timeout.connect(self.reveal_camera)
        page.installEventFilter(self)

    def set_camera(self,widget):self.camera_area=widget

    def set_action_area(self,widget):self.action_area=widget

    def set_history(self,toggle,widget,table):
        table.setMinimumHeight(70);table.setMaximumHeight(16777215)
        table.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        table.setVerticalScrollMode(table.ScrollMode.ScrollPerPixel)
        self.history_dialog=self.add_popup(toggle,widget,toggle.text())

    def add_popup(self,button,widget,title,size=(1100,600)):
        dialog=QDialog(self.page);dialog.setWindowTitle(title);dialog.resize(*size)
        layout=QVBoxLayout(dialog);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumSize(0,0)
        scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored);scroll.setWidget(widget);layout.addWidget(scroll)
        self.tools.addWidget(button);self.popups.append(dialog)
        def show():
            dialog.show();dialog.raise_();dialog.activateWindow()
        # show(), not exec(): the live page's Capture/Stop remains accessible.
        button.clicked.connect(show)
        return dialog

    def reveal_camera(self):
        if self.camera_area is not None:
            self.content_layout.activate();self.page_scroll.ensureWidgetVisible(self.camera_area,0,0)
        if self.action_area is not None:
            width=self.action_area.width();available=self.page.width()-self.contentsMargins().left()-self.contentsMargins().right()
            self.footer.setStretch(0,width);self.footer.setStretch(1,max(0,available-width))

    def eventFilter(self,watched,event):
        if watched is self.page and event.type()in(QEvent.Type.Resize,QEvent.Type.Show):
            self.resize_timer.start(0)
        elif watched is self.page and event.type()==QEvent.Type.Hide:
            for dialog in self.popups:dialog.close()
        return super().eventFilter(watched,event)


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


class LiveCameraView(CameraView):
    """Fill live panels without stretching; double click shows the whole frame."""
    def __init__(self,text='',*,title='Camera'):
        super().__init__(text,(240,180));self.title=title;self._expanded=None
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.setToolTip('화면 채움 확대 · 가장자리 일부가 잘릴 수 있습니다. 더블클릭: 전체 영상 크게 보기')

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(480,360)

    def minimumSizeHint(self):
        # QLabel otherwise reports the source pixmap (e.g. 640x480) as its
        # minimum. A scroll layout must resize the display, never the RGB data.
        return self.minimumSize()

    def setPixmap(self,pixmap):
        super().setPixmap(pixmap)
        if self._expanded is not None:self._expanded.setPixmap(pixmap)

    def clear(self):
        super().clear()
        if self._expanded is not None:self._expanded.clear()

    def paintEvent(self,event):
        pix=self.pixmap()
        if pix is None or pix.isNull():return super().paintEvent(event)
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size=pix.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        painter.drawPixmap((self.width()-size.width())//2,(self.height()-size.height())//2,size.width(),size.height(),pix)
        painter.end()

    def mouseDoubleClickEvent(self,event):
        pix=self.pixmap()
        if event.button()!=Qt.MouseButton.LeftButton or pix is None or pix.isNull():return super().mouseDoubleClickEvent(event)
        from PyQt6.QtWidgets import QDialog,QVBoxLayout
        dialog=QDialog(self.window());dialog.setWindowTitle(self.title+' · 전체 영상');dialog.resize(960,720)
        layout=QVBoxLayout(dialog);layout.setContentsMargins(0,0,0,0)
        self._expanded=CameraView();self._expanded.setPixmap(pix);layout.addWidget(self._expanded)
        try:dialog.exec()
        finally:self._expanded=None;dialog.deleteLater()
        event.accept()


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
