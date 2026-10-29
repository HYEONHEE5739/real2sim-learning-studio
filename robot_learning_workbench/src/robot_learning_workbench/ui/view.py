"""Presentation widgets ported from the original SO101 workflow UI.

CameraView preserves the original implementation; no engine/device ownership.
Source: soarm101_lab/workflow/view.py (see docs/ui-original-restoration.md).
"""
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter,QPixmap
from PyQt6.QtWidgets import QLabel,QSizePolicy


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
