"""Native selections and existing Curation APIs; slow reads run outside Qt."""
from pathlib import Path
import json,uuid
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QFileDialog,QLineEdit,QTableWidget,QTableWidgetItem,QAbstractItemView,QSpinBox,QPlainTextEdit,QComboBox
from .jobs import BackendJob


class CurationPage(QWidget):
    def __init__(self,python,workspace,parent=None,*,source_only=False):
        super().__init__(parent);self.workspace=Path(workspace);self.source=None;self.rows=[];self.dirty=False;self.loading=False;self.operation=None;self.busy=False;self.preview_directory=self.workspace/'.review'/uuid.uuid4().hex
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Source 입력 · 저장 영상 검토' if source_only else 'Curation · 원본 보존 / 선택 Revision / 공식 LeRobot Export'))
        row=QHBoxLayout();layout.addLayout(row)
        for text,fn in [('Dataset 폴더',self.choose_source),('Revision 열기',self.choose_revision)]:
            button=QPushButton(text);button.clicked.connect(fn);row.addWidget(button)
        self.path=QLineEdit();self.path.setReadOnly(True);layout.addWidget(self.path)
        self.state=QLabel('Dataset을 선택하세요');self.state.setWordWrap(True);layout.addWidget(self.state)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['사용','Episode','원본 시작','원본 끝(미포함)','원 Episode 판정','Split'])
        self.table.itemChanged.connect(self.edited);self.table.itemSelectionChanged.connect(self.selection_changed);layout.addWidget(self.table)
        row=QHBoxLayout();layout.addLayout(row);self.frame=QSpinBox();self.frame.setRange(0,0);row.addWidget(QLabel('선택 구간 기준 Frame'));row.addWidget(self.frame)
        self.review_button=QPushButton('저장 Frame 검토');self.review_button.clicked.connect(self.review);row.addWidget(self.review_button)
        self.images={};row=QHBoxLayout();layout.addLayout(row)
        for name in ('side','wrist'):label=QLabel(name+' · 저장 영상');self.images[name]=label;row.addWidget(label)
        self.result=QPlainTextEdit();self.result.setReadOnly(True);self.result.setMaximumBlockCount(300);layout.addWidget(self.result)
        self.task=QLineEdit();self.task.setPlaceholderText('학습용 실제 작업 문장 (Export 시 필수)')
        self.buttons={}
        if not source_only:
            layout.addWidget(self.task);self.scope=QComboBox();self.scope.addItems(['현재 전체 선택','train','val']);layout.addWidget(self.scope);row=QHBoxLayout();layout.addLayout(row)
            for text,fn in [('Revision 저장',self.save_revision),('Train/Val 분할',self.split),('분포 통계',self.analyze),('Dataset 비교',self.compare),('LeRobot Export',self.export),('호환 Merge',self.merge)]:
                button=QPushButton(text);button.clicked.connect(fn);row.addWidget(button);self.buttons[text]=button
        else:
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            layout.addWidget(QLabel('실제 Leader/Follower 수집은 별도 연결·승인이 필요합니다. 이번 화면은 보존된 실제 Source 입력을 사용합니다.'))
        self.job=BackendJob(python,self);self.job.finished.connect(self.finished);self.job.log.connect(self.result.appendPlainText)
    def perform(self,operation,**arguments):
        if self.busy:self.state.setText('현재 작업이 끝난 뒤 실행하세요');return
        self.busy=True;self.operation=operation;self.state.setText('실제 '+operation+' 처리 중…');self.job.start(operation,**arguments)
    def choose_source(self):
        p=QFileDialog.getExistingDirectory(self,'Native / 공식 Dataset 선택')
        if p:self.load_source(p)
    def choose_revision(self):
        p,_=QFileDialog.getOpenFileName(self,'저장 Curation Revision','','JSON (*.json)')
        if p:self.load_source(p)
    def load_source(self,path):self.perform('catalog',path=str(Path(path).resolve()))
    def edited(self,*_):
        if not self.loading:self.dirty=True;self.state.setText('선택 편집 중 · 새 Revision으로 저장한 뒤 통계/Export하세요')
    def selection_changed(self):
        index=self.table.currentRow()
        if index<0 or index>=len(self.rows):return
        low,high=self.rows[index]['selection_range'];self.frame.setMaximum(high-low-1)
    def finished(self,response):
        self.busy=False
        if not response.get('ok'):self.state.setText(response.get('error',{}).get('message','오류'));return
        result=response['result'];self.state.setText('완료 · 원본 데이터는 변경하지 않았습니다')
        if self.operation=='catalog':
            self.source=result['path'];self.path.setText(self.source);self.rows=result['inspection']['episodes'];self.loading=True;self.table.setRowCount(len(self.rows))
            try:
                for i,row in enumerate(self.rows):
                    check=QTableWidgetItem();check.setFlags(Qt.ItemFlag.ItemIsUserCheckable|Qt.ItemFlag.ItemIsEnabled);check.setCheckState(Qt.CheckState.Checked);self.table.setItem(i,0,check)
                    outcome='recording_only' if row['success_source']=='recording_only' else str(row['recorded_success'])+' / '+str(row['category'])
                    outcome+=' · Env '+str(row.get('env_index','?'))
                    values=[row['selection_id'],*row['selection_range'],outcome,row['split'] or '']
                    for j,value in enumerate(values,1):
                        item=QTableWidgetItem(str(value))
                        if j in (1,4):item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(i,j,item)
                self.dirty=False
            finally:self.loading=False
            self.result.setPlainText(json.dumps({'선택_frame':result['inspection']['selected_frames'],
                '원본_attempt':[{'attempt':r['attempt'],'status':r['status'],'category':r.get('diagnostics',{}).get('category'),'steps':r.get('diagnostics',{}).get('steps')} for r in result['inspection']['source_attempts']],
                '미확정_수':len(result['inspection']['unresolved_source_intents'])},ensure_ascii=False,indent=2))
        elif self.operation=='frame':
            for camera,path in result.pop('images').items():self.images[camera].setPixmap(QPixmap(path))
            result.pop('source_identity',None);self.result.setPlainText(json.dumps(result,ensure_ascii=False,indent=2))
        elif self.operation=='split':
            self.loading=True
            for role,ids in result['splits'].items():
                for i,row in enumerate(self.rows):
                    if row['selection_id'] in ids:self.table.item(i,5).setText(role)
            self.loading=False;self.edited()
        elif self.operation=='save_curation':self.load_source(result['path'])
        elif self.operation in ('distribution','compare'):
            datasets=result['datasets'] if 'datasets' in result else [result]
            lines=[]
            for dataset in datasets:
                scope={k:v for k,v in dataset['scope'].items() if k!='identity'};lines.append('통계 범위 · '+json.dumps(scope,ensure_ascii=False))
                for name,field in dataset['fields'].items():
                    lines.append(name)
                    lines.extend(k+' · '+json.dumps(v,ensure_ascii=False) for k,v in field.items())
            self.result.setPlainText('\n'.join(lines))
        else:self.result.setPlainText(json.dumps(result,ensure_ascii=False,indent=2))
    def stable(self):
        if not self.source or self.dirty:self.state.setText('Dataset 선택 후 변경한 선택/구간을 Revision에 저장하세요');return False
        return True
    def review(self):
        if not self.stable():return
        i=self.table.currentRow()
        if i<0:self.state.setText('Episode를 선택하세요');return
        self.perform('frame',source=self.source,selection_id=self.rows[i]['selection_id'],frame=self.frame.value(),preview_directory=str(self.preview_directory))
    def save_revision(self):
        if not self.source:return
        path,_=QFileDialog.getSaveFileName(self,'새 Curation Revision','','JSON (*.json)')
        if not path:return
        try:
            order=[];ranges={};splits={};exclude=[]
            for i,row in enumerate(self.rows):
                id_=row['selection_id'];order.append(id_)
                if self.table.item(i,0).checkState()!=Qt.CheckState.Checked:exclude.append(id_);continue
                ranges[id_]=[int(self.table.item(i,2).text()),int(self.table.item(i,3).text())]
                role=self.table.item(i,5).text().strip()
                if role:splits.setdefault(role,[]).append(id_)
            self.perform('save_curation',path=path,source=self.source,order=order,exclude=exclude,frame_ranges=ranges,splits=splits)
        except ValueError as error:self.state.setText(str(error))
    def split(self):
        if self.stable():self.perform('split',source=self.source)
    def analyze(self):
        if self.stable():self.perform('distribution',source=self.source,split=None if self.scope.currentIndex()==0 else self.scope.currentText())
    def compare(self):
        if not self.stable():return
        other=QFileDialog.getExistingDirectory(self,'비교 Dataset')
        if other:self.perform('compare',sources=[self.source,other])
    def export(self):
        if not self.stable():return
        if not self.task.text().strip():self.state.setText('실제 작업 문장을 입력하세요');return
        parent=QFileDialog.getExistingDirectory(self,'새 Export 출력 상위 폴더')
        if parent:self.perform('materialize',source=self.source,output=str(Path(parent)/('lerobot-'+uuid.uuid4().hex[:8])),task=self.task.text(),split=None if self.scope.currentIndex()==0 else self.scope.currentText())
    def merge(self):
        if not self.stable():return
        other=QFileDialog.getExistingDirectory(self,'Merge할 다른 canonical Dataset')
        if not other:return
        parent=QFileDialog.getExistingDirectory(self,'새 Merge 출력 상위 폴더')
        if parent:self.perform('merge',sources=[self.source,other],output=str(Path(parent)/('merged-'+uuid.uuid4().hex[:8])),task=self.task.text() or None)
