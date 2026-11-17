"""One recorded-observation list, shared by Capture and read-only Real/Sim."""
import time
from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTableWidget,QTableWidgetItem,QHeaderView
from .view import CameraView
from .session_results import ResultsDialog


class SnapshotTable(QTableWidget):
    error=pyqtSignal(str)
    def __init__(self,*,paired=False,parent=None):
        headers=['#','시간','Real Side','Sim Side','Real Wrist','Sim Wrist','관절 상태 (rad)','상태']if paired else['#','시간','Side','Wrist','관절 상태 (rad)','상태']
        super().__init__(0,len(headers),parent);self.rows=[];self.q_column=6 if paired else 4
        self.cameras={2:'side',3:'sim_side',4:'wrist',5:'sim_wrist'}if paired else{2:'side',3:'wrist'}
        self.setHorizontalHeaderLabels(headers);self.setMinimumHeight(110);self.setMaximumHeight(180);self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for c in range(len(headers)):self.setColumnWidth(c,75 if c in self.cameras else 90)
        self.setColumnWidth(0,35);self.horizontalHeader().setSectionResizeMode(self.q_column,QHeaderView.ResizeMode.Stretch);self.cellDoubleClicked.connect(self.details)
    def reset(self):self.rows=[];self.setRowCount(0)
    def reject(self,command_id,reason):
        row=next((r for r in self.rows if r.get('command_id')==command_id),None)
        if row is not None:self.append({**row,'phase':'FAILED','error':reason})
    def finish_pending(self,reason):
        for row in list(self.rows):
            if row.get('phase')not in(None,'REGISTERED','FAILED')and row.get('status')!='SAVED':self.append({**row,'phase':'FAILED','error':reason})
    def append(self,row):
        i=next((i for i,r in enumerate(self.rows)if row.get('id')and r.get('id')==row['id']),None)
        previous=self.rows[i]if i is not None else{}
        row={**previous,**row}
        if i is None:i=self.rowCount();self.rows.append(row);self.insertRow(i)
        else:self.rows[i]=row
        stamp=time.strftime('%H:%M:%S',time.localtime(row['unix_ns']/1e9))if row.get('unix_ns')else'시각 미기록'
        labels={'REQUESTED':'촬영 요청','OBSERVED':'관측 확보','QUEUED':'저장 대기','RAW_SAVED':'원본 저장','SIM_PAIR':'Sim/Pair 처리','REGISTERING':'등록 중','FAILED':'실패'}
        phase=row.get('phase');status=labels.get(phase,'Pair 저장'if row.get('paired')else'Capture 저장')
        for c,value in{0:i+1,1:stamp,self.q_column:', '.join(f'{q:.4f}'for q in row.get('q_measured',[])),self.q_column+1:status}.items():self.setItem(i,c,QTableWidgetItem(str(value)))
        self.item(i,self.q_column+1).setToolTip(row.get('error')or status)
        for c,name in self.cameras.items():
            if row.get('images',{}).get(name)and(previous.get('images',{}).get(name)!=row['images'][name]or self.cellWidget(i,c)is None):
                view=CameraView(minimum=(45,32));view.show_image(row['images'][name]);self.setCellWidget(i,c,view)
        self.setRowHeight(i,38)
    def details(self,row,column=0):
        if 0<=row<len(self.rows):
            record=self.rows[row]
            raw_saved=record.get('phase')=='FAILED'and record.get('path')and(Path(record['path'])/'COMPLETE').is_file()
            if record.get('phase')not in(None,'REGISTERED')and record.get('status')!='SAVED'and not raw_saved:return
            try:ResultsDialog(self.rows[row],self).exec()
            except Exception as error:self.error.emit(str(error))
