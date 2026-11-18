"""Shared Studio chrome. Styling never changes camera or simulation RGB."""

COLORS = dict(background='#0c1420',panel='#121f2e',raised='#1a2a3d',border='#2d4259',
              text='#e7eff8',muted='#9db0c7',accent='#00d9c0',danger='#ff8494')

STYLE = """
QWidget { background: #0c1420; color: #e7eff8; font-family: 'DejaVu Sans', 'Noto Sans CJK KR', sans-serif; font-size: 13px; font-weight: 400; selection-background-color: #125653; selection-color: #effffc; }
QMainWindow, QDialog { background: #0c1420; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QLabel:disabled { color: #71869d; }
QScrollArea, QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1c2b3d,stop:1 #131f2d); color: #b9c9db; border: 1px solid #2c4056; border-radius: 8px; padding: 10px 18px; margin: 4px 6px 8px 0; font-weight: 500; }
QTabBar::tab:hover { background: #20354a; color: #f0f6ff; border-color: #52708b; }
QTabBar::tab:selected { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #10413f,stop:1 #102b33); color: #38efd7; border-color: #00cbb6; }
QPushButton, QToolButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1d2c3d,stop:1 #14202e); color: #dce8f5; border: 1px solid #344a62; border-radius: 8px; padding: 8px 12px; min-height: 18px; font-weight: 500; }
QPushButton:hover, QToolButton:hover { background: #243a4e; border-color: #5b7b96; color: #f7fbff; }
QPushButton:pressed, QToolButton:pressed { background: #102b38; border-color: #00cbb6; }
QPushButton:focus, QToolButton:focus { border-color: #00d9c0; }
QPushButton:checked, QToolButton:checked { background: #0f3e40; border-color: #00cbb6; color: #55f1dd; }
QPushButton#primaryAction { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #087c72,stop:1 #07574f); color: #f1fffc; border: 1px solid #00c9b2; font-weight: 600; }
QPushButton#primaryAction:hover { background: #0b8b7c; border-color: #54f3d9; }
QPushButton#primaryAction:pressed { background: #064c48; }
QPushButton#stopAction { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #432432,stop:1 #251b28); color: #ff9eab; border: 1px solid #954256; }
QPushButton#stopAction:hover { background: #5b283a; border-color: #ff7189; color: #ffd6dd; }
QPushButton:disabled, QToolButton:disabled, QPushButton#primaryAction:disabled, QPushButton#stopAction:disabled { background: #12202d; border-color: #2b3b4d; color: #7b91a7; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit { background: #0d1825; color: #e7eff8; border: 1px solid #31465d; border-radius: 7px; padding: 7px 9px; min-height: 19px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid #00c7b4; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { background: #101c29; color: #74899f; border-color: #26384b; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 22px; border: none; }
QComboBox QAbstractItemView { background: #142334; color: #e7eff8; selection-background-color: #164c4d; selection-color: #63f4de; border: 1px solid #39556d; outline: none; }
QComboBox QAbstractItemView::item { min-height: 28px; padding: 3px 6px; }
QComboBox QAbstractItemView::item:selected { background: #164c4d; color: #63f4de; }
QPlainTextEdit, QTextEdit, QTextBrowser { background: #0d1825; color: #dfeaf7; border: 1px solid #31465d; border-radius: 8px; padding: 8px; }
QPlainTextEdit#codeEditor, QPlainTextEdit#console { font-family: 'D2Coding', 'Noto Sans Mono', monospace; font-size: 13px; }
QPlainTextEdit#console { background: #0b1521; border-color: #24394e; }
QListWidget, QTreeWidget, QTableView, QTableWidget { background: #0d1825; alternate-background-color: #122131; color: #dce8f4; border: 1px solid #2d4259; border-radius: 8px; padding: 3px; gridline-color: #22364a; outline: none; }
QListWidget::item, QTreeWidget::item { padding: 5px; border-radius: 4px; }
QListWidget::item:selected, QTreeWidget::item:selected, QTableView::item:selected { background: #16494c; color: #e8fffa; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #20364a; }
QHeaderView { background: transparent; }
QHeaderView::section { background: #1a2b3e; color: #b7cadf; border: none; border-bottom: 1px solid #35506a; padding: 6px 8px; font-size: 12px; font-weight: 500; }
QTableCornerButton::section { background: #1a2b3e; border: none; }
QGroupBox { background: #121f2e; border: 1px solid #2d4259; border-radius: 10px; margin-top: 16px; padding: 15px 10px 10px; font-weight: 500; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #bacfe2; }
QWidget#dashboardHeader, QWidget#navigationPanel, QWidget#settingsContent, QWidget#settingCard, QWidget#actionCard, QWidget#logCard, QScrollArea#settingsPanel { background: #121f2e; border: 1px solid #293f55; border-radius: 10px; }
QWidget#workspaceCanvas { background: transparent; }
QWidget#previewCard { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #192a3c,stop:1 #111d2c); border: 1px solid #3a536b; border-radius: 10px; }
QWidget#previewCard QLabel { border: none; background: transparent; }
QLabel#previewTitle { color: #dceaf8; font-size: 12px; font-weight: 500; padding: 4px 5px; }
QLabel#jointCard { background: #152537; color: #c4d6e8; border: 1px solid #293f55; border-radius: 7px; padding: 7px 3px; font-size: 12px; }
QLabel#dashboardTitle { font-size: 24px; font-weight: 600; color: #f1f7ff; background: transparent; padding: 2px 0; }
QLabel#eyebrow { color: #6dddcf; font-size: 11px; font-weight: 500; letter-spacing: 1px; padding: 4px 6px; }
QLabel#sectionTitle { font-size: 17px; font-weight: 500; color: #e6f2ff; padding: 6px; }
QLabel#mutedLabel { color: #9db0c7; background: transparent; padding: 4px; }
QLabel#safetyBanner { color: #9db0c7; background: transparent; font-size: 12px; padding: 2px 0; }
QLabel#taskBadge { background: #103739; color: #62e6d2; border: 1px solid #1b6663; border-radius: 7px; padding: 8px; }
QListWidget#stageNavigation { background: transparent; border: none; padding: 0; }
QListWidget#stageNavigation::item { color: #a5bbd0; padding: 12px 7px; margin: 3px 0; border: 1px solid transparent; border-radius: 7px; }
QListWidget#stageNavigation::item:selected { background: #103d40; border-color: #16756e; color: #6bf2dc; }
QListWidget#stageNavigation::item:hover { background: #20344a; }
QSplitter::handle { background: transparent; width: 7px; height: 7px; }
QSplitter::handle:hover { background: #1a4d53; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0 2px; }
QScrollBar::handle { background: #38536b; border-radius: 3px; }
QScrollBar::handle:vertical { min-height: 28px; }
QScrollBar::handle:horizontal { min-width: 28px; }
QScrollBar::handle:hover { background: #5a7d95; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QCheckBox, QRadioButton { spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #54718b; border-radius: 4px; background: #0d1825; }
QCheckBox::indicator:checked { background: #00aa98; border-color: #45e7d0; }
QRadioButton::indicator { width: 15px; height: 15px; border: 1px solid #54718b; border-radius: 8px; background: #0d1825; }
QRadioButton::indicator:checked { background: #00aa98; border: 3px solid #236b6b; }
QSlider::groove:horizontal { height: 4px; background: #253c52; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #00bda9; border-radius: 2px; }
QSlider::handle:horizontal { background: #a7e9e0; border: 1px solid #4d9f9a; width: 12px; margin: -5px 0; border-radius: 5px; }
QProgressBar { background: #102131; color: #c8dfef; border: 1px solid #2b4257; border-radius: 5px; text-align: center; min-height: 18px; }
QProgressBar::chunk { background: #0b8f83; border-radius: 4px; }
QStatusBar { background: #0a121c; color: #91a9c0; border-top: 1px solid #22364a; font-size: 11px; }
QStatusBar::item { border: none; }
QToolTip { background: #1a2d40; color: #eef8ff; border: 1px solid #45637d; padding: 6px 8px; }
QMenu, QMenuBar { background: #121f2e; color: #dceaf6; border: 1px solid #2d4259; }
QMenu::item { padding: 7px 18px; }
QMenu::item:selected { background: #16494c; color: #6bf2dc; }
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
