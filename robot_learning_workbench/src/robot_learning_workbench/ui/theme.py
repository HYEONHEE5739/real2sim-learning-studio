"""Shared desktop palette; no effect on simulator or camera pixels."""
STYLE = """
QWidget { background: #191d24; color: #e3e8ef; font-size: 13px; }
QScrollArea, QTabWidget::pane { border: 0; }
QTabBar::tab { background: #242b35; padding: 12px 20px; border: 0; }
QTabBar::tab:selected { background: #344352; color: #67e8bf; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #11171e; border: 1px solid #3b4655; border-radius: 6px; padding: 7px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #55d6b0; }
QPushButton, QToolButton { background: #2b3441; border: 1px solid #414e5e; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover, QToolButton:hover { background: #374759; border-color: #67e8bf; }
QPushButton:disabled, QComboBox:disabled, QLineEdit:disabled { color: #7f8b99; background: #232932; }
QPushButton#primaryAction { background: #237b65; border-color: #44b493; color: white; font-weight: bold; }
QPushButton#stopAction { border-color: #b57476; color: #f4b3b5; }
QWidget#settingCard { background: #242b35; border-radius: 8px; }
QWidget#settingCard QLabel, QWidget#settingCard QCheckBox { background: transparent; }
QPlainTextEdit, QTextBrowser, QTableWidget { background: #11171e; border: 1px solid #374353; border-radius: 6px; padding: 6px; selection-background-color: #346957; }
QHeaderView::section { background: #2b3441; padding: 5px; border: 0; }
QSplitter::handle { background: #303b49; }
QScrollBar:vertical { background: #191d24; width: 10px; }
QScrollBar::handle:vertical { background: #4c596a; min-height: 30px; border-radius: 4px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #7f8b99; border-radius: 3px; background: #11171e; }
QCheckBox::indicator:checked { background: #55d6b0; border-color: #55d6b0; }
"""

STYLE += """
QWidget { font-family: 'Noto Sans CJK KR', 'Noto Sans', sans-serif; }
QWidget#dashboardHeader { background: #222833; border-radius: 20px; }
QWidget#navigationPanel { background: #202631; border-radius: 18px; }
QWidget#workspaceCanvas { background: transparent; }
QScrollArea#settingsPanel { background: #222833; border-radius: 18px; }
QWidget#actionCard, QWidget#previewCard, QWidget#logCard { background: #222833; border-radius: 18px; }
QLabel#dashboardTitle { font-size: 25px; font-weight: 600; background: transparent; padding: 3px 8px; }
QLabel#eyebrow { color: #8ba3b2; font-size: 11px; font-weight: 600; background: transparent; padding: 8px; }
QLabel#sectionTitle { font-size: 18px; font-weight: 600; padding: 8px; }
QLabel#mutedLabel { color: #a1aebc; background: transparent; padding: 6px; }
QLabel#taskBadge { background: #253e3b; border-radius: 10px; padding: 10px; color: #a2e0cb; }
QListWidget#stageNavigation { background: transparent; border: none; outline: none; }
QListWidget#stageNavigation::item { padding: 14px 8px; margin: 4px 0; border-radius: 12px; color: #aeb9c7; }
QListWidget#stageNavigation::item:selected { background: #31554e; color: #b8ffe7; }
QListWidget#stageNavigation::item:hover { background: #303b4a; }
QPushButton, QToolButton { border-radius: 12px; padding: 10px 14px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { border-radius: 10px; }
QWidget#settingCard { border-radius: 14px; }
QPlainTextEdit#console { border: none; border-radius: 12px; font-family: monospace; }
QTabBar::tab { border-radius: 10px; margin: 4px; }
QTabBar::tab:selected { background: #31554e; }
QSplitter::handle { background: transparent; width: 10px; height: 10px; }
"""
STYLE += """
QWidget#settingsContent { background: #222833; border-radius: 18px; }
QWidget#settingsContent QLabel, QWidget#settingsContent QCheckBox { background: transparent; }
QWidget#logCard QLabel, QWidget#logCard QCheckBox, QWidget#previewCard QLabel { background: transparent; }
"""


def action_icon(kind):
    """Small vector glyphs in the native Qt renderer; no raster downloads."""
    from PyQt6.QtCore import Qt,QRectF,QPointF
    from PyQt6.QtGui import QIcon,QPixmap,QPainter,QPainterPath,QPen,QColor
    icon=QIcon()
    for mode,color in[(QIcon.Mode.Normal,'#e3f3f7'),(QIcon.Mode.Disabled,'#71899e')]:
        pix=QPixmap(48,48);pix.fill(Qt.GlobalColor.transparent);pix.setDevicePixelRatio(2)
        painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color),1.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        if kind=='capture':
            path=QPainterPath();path.moveTo(4,7);path.lineTo(8,7);path.lineTo(10,4);path.lineTo(15,4);path.lineTo(17,7);path.lineTo(20,7);path.quadTo(22,7,22,9);path.lineTo(22,19);path.quadTo(22,21,20,21);path.lineTo(4,21);path.quadTo(2,21,2,19);path.lineTo(2,9);path.quadTo(2,7,4,7)
            painter.drawPath(path);painter.drawEllipse(QRectF(8,10,8,8))
        elif kind=='stop':painter.drawRoundedRect(QRectF(5,5,14,14),2,2)
        else:
            painter.translate(12,12);painter.rotate(40)
            painter.drawRoundedRect(QRectF(-3.5,-10,7,12),3.5,3.5);painter.drawRoundedRect(QRectF(-3.5,-2,7,12),3.5,3.5);painter.drawLine(QPointF(0,-3),QPointF(0,3))
        painter.end();icon.addPixmap(pix,mode)
    return icon
