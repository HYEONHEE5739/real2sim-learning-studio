"""Presentation of recorded motion hints and clickable initial object positions."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QLabel
from .plots import ReviewPlot


def outcome(row):
    if row['success_source']=='recording_only':return 'Source Demo · 성공 판정 전'
    return '작업 성공'if row['recorded_success']is True else'작업 실패'if row['recorded_success']is False else'판정 미기록'


class QualityOverview(QWidget):
    selected=pyqtSignal(int)

    def __init__(self,parent=None):
        super().__init__(parent);self.rows=[];self.selection=[];self.regions={};self.index=-1
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        positions=layout;controls=QHBoxLayout();positions.addLayout(controls)
        controls.addWidget(QLabel('Task objects'));self.objects=QComboBox();controls.addWidget(self.objects,1)
        self.scatter=ReviewPlot('scatter');self.scatter.setMinimumHeight(380);positions.addWidget(self.scatter,1)
        self.position_note=QLabel();self.position_note.setWordWrap(True);positions.addWidget(self.position_note)
        self.summary=QLabel('Episode를 선택하세요.');self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.objects.currentTextChanged.connect(self.refresh);self.scatter.picked.connect(self.pick)

    def set_rows(self,rows,task_objects=()):
        self.rows=rows;self.selection=[dict(included=True,split=row.get('split'))for row in rows];self.regions={};self.index=-1;self.summary.setText('Episode를 선택하세요.')
        names={name for row in rows for name in row.get('quality',{}).get('initial_objects',{})}
        preferred=[name for name in dict.fromkeys(task_objects)if name in names]
        self.objects.blockSignals(True);self.objects.clear();self.objects.addItems(preferred);self.objects.setEnabled(bool(preferred));self.objects.blockSignals(False);self.refresh()

    def set_selection(self,selection):
        self.selection=selection
        if 0<=self.index<len(self.rows):self.select(self.index)
        else:self.refresh()

    def refresh(self,*_):
        name=self.objects.currentText();points=[]
        for i,row in enumerate(self.rows):
            quality=row.get('quality',{});point=quality.get('initial_objects',{}).get(name)
            if point is None:continue
            points.append(dict(xy=point[:2],name=row['selection_id'],index=i,flags=quality.get('flags',[]),placement_region=self.regions.get(name),**self.selection[i]))
        count=len(points)
        self.scatter.rows=points;self.scatter.selected=next((j for j,row in enumerate(points)if row['index']==self.index),-1);self.scatter.update()
        self.position_note.setText(f'{count} / {len(self.rows)} Episode · Episode 시작 위치 · robot_base [m]'if points else'기록된 물체 위치가 없습니다. 위치를 추정하지 않습니다.')

    def select(self,index):
        self.index=index;self.refresh()
        if not 0<=index<len(self.rows):return
        row=self.rows[index];q=row.get('quality',{});flags=q.get('flags',[])
        selected=self.selection[index];status='포함'if selected['included']else'제외'
        duration=f" · {q['duration']:.1f}s"if q.get('duration')is not None else''
        idle=f" · EE 정지 {q['stop_fraction']*100:.1f}%"if q.get('stop_fraction')is not None else''
        lines=[row['selection_id']+' · '+outcome(row)+' · '+status+duration+idle]
        if flags:lines.append('확인 필요 · '+', '.join(flags))
        elif q.get('reason'):lines.append('일부 측정 없음 · '+q['reason'])
        self.summary.setText('\n'.join(lines))
        self.summary.setToolTip('주의 표시는 검토 힌트이며 자동 제외가 아닙니다. EE 정지: 기록 속도 <2mm/s. 주의 기준은 원본 Dataset에 고정됩니다.')

    def pick(self,index):
        self.selected.emit(self.scatter.rows[index]['index'])
