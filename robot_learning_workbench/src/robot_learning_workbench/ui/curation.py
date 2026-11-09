from scene_contract.naming import numbered_path
"""Native selections and existing Curation APIs; slow reads run outside Qt."""
from pathlib import Path
import uuid
from PyQt6.QtCore import Qt,QTimer,QElapsedTimer
from PyQt6.QtGui import QPixmap,QImage,QColor
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QFileDialog,QTableWidget,QTableWidgetItem,QAbstractItemView,QSpinBox,QComboBox,QScrollArea,QSplitter,QGridLayout,QListWidget,QListWidgetItem,QTabWidget,QDoubleSpinBox,QInputDialog,QHeaderView,QDialog
from .jobs import BackendJob
from .dataset_picker import DatasetPicker
from .revision_picker import RevisionPicker
from .dataset_merge import DatasetMergeDialog
from .review_client import ReviewClient
from .curation_quality import QualityOverview,outcome
from .curation_table import FrameRangeDelegate,SplitDelegate


class CurationPage(QWidget):
    def __init__(self,python,workspace,parent=None,*,source_only=False):
        super().__init__(parent)
        from .view import CameraView,EventTimeline
        from .plots import ReviewPlot
        from .theme import STYLE
        self.setStyleSheet(STYLE);self.workspace=Path(workspace);self.source_only=source_only;self.source=None;self.original_source=None;self.original_identity=None;self.revision_record=None;self.rows=[];self.dirty=False;self.loading=False;self.operation=None;self.busy=False;self.pending_source=None;self.preview_directory=self.workspace/'.review'/uuid.uuid4().hex
        self._syncing_review=False;self.playing=False;self.plot_busy=False;self.plot_data=None;self.timestamps=[];self.elapsed=QElapsedTimer();self.play_start=0;self.last_requested=None
        layout=QVBoxLayout(self);layout.setSpacing(10);header=QHBoxLayout();layout.addLayout(header)
        title=QLabel('Source 검토'if source_only else'Data Curation');title.setStyleSheet('font-size:22px; font-weight:600;');header.addWidget(title);header.addStretch()
        for text,fn in [('데이터 열기',self.choose_source),('Revision 열기',self.choose_revision)]:
            button=QPushButton(text);button.clicked.connect(fn);header.addWidget(button)
        self.datasets=DatasetPicker(python,self.workspace,self);layout.addWidget(self.datasets)
        self.datasets.selected.connect(self.load_source);self.datasets.cleared.connect(lambda:self.load_source(''))
        self.revisions=RevisionPicker(self);layout.addWidget(self.revisions);self.revisions.selected.connect(self.load_source)
        self.state=QLabel('Episode 검토 · 영상과 기록 확인 · 원본 보존');self.state.setWordWrap(True);layout.addWidget(self.state)
        self.page_scroll=QScrollArea();self.page_scroll.setWidgetResizable(True);layout.addWidget(self.page_scroll,1);content=QWidget();page=QVBoxLayout(content);page.setContentsMargins(0,0,0,0);page.setSpacing(10);self.page_scroll.setWidget(content)
        self.splitter=QSplitter();self.splitter.setMinimumHeight(380);page.addWidget(self.splitter,1)
        self.episode_panel=QWidget();left=QVBoxLayout(self.episode_panel);self.splitter.addWidget(self.episode_panel);left.addWidget(QLabel('Episode 목록'))
        self.filter=QComboBox();self.filter.addItems(['전체','작업 성공','작업 실패','Source Demo','train','val','확인 필요']);self.filter.currentIndexChanged.connect(self.apply_filter);left.addWidget(self.filter)
        self.episode_list=QListWidget();self.list=self.episode_list;self.episode_list.setMinimumWidth(220);self.episode_list.setWordWrap(True);left.addWidget(self.episode_list,1)
        self.episode_list.currentRowChanged.connect(self.select_episode);self.episode_list.itemChanged.connect(self.include_changed)
        self.selection_count=QLabel('전체 0개 중 0개 포함');self.selection_count.setWordWrap(True);left.addWidget(self.selection_count)
        right=QWidget();review=QVBoxLayout(right);self.splitter.addWidget(right);self.episode_title=QLabel('Episode를 선택하세요');review.addWidget(self.episode_title)
        self.preview_tabs=QTabWidget();review.addWidget(self.preview_tabs,1);videos=QWidget();rgb=QHBoxLayout(videos);self.images={}
        for name in ('side','wrist'):
            col=QVBoxLayout();rgb.addLayout(col,1);col.addWidget(QLabel(name.title()));label=CameraView('영상 없음',(120,120));col.addWidget(label,1);self.images[name]=label
        self.preview_tabs.addTab(videos,'영상 · Side / Wrist')
        trajectory_page=QWidget();trajectory_layout=QVBoxLayout(trajectory_page);views=QHBoxLayout();views.addWidget(QLabel('드래그 회전 · 휠 확대'));trajectory_layout.addLayout(views)
        self.trajectory=ReviewPlot('trajectory');trajectory_layout.addWidget(self.trajectory,1)
        self.geometry_note=QLabel();self.geometry_note.setWordWrap(True);self.geometry_note.hide();trajectory_layout.addWidget(self.geometry_note)
        for name in ('3D','XY','XZ','YZ'):
            button=QPushButton(name);button.clicked.connect(lambda _,n=name:self.trajectory.set_view(n));views.addWidget(button)
        self.trajectory.set_view('3D');self.preview_tabs.addTab(trajectory_page,'로봇 · 물체 경로')
        playbar=QHBoxLayout();review.addLayout(playbar);self.play_button=QPushButton('재생');self.play_button.clicked.connect(self.toggle_play);playbar.addWidget(self.play_button)
        self.timeline=EventTimeline();self.timeline.setRange(0,0);self.timeline.valueChanged.connect(self.seek);self.timeline.eventPicked.connect(self.seek);playbar.addWidget(self.timeline,1)
        self.clock_label=QLabel('0.00s / 0.00s');playbar.addWidget(self.clock_label);self.rate=QComboBox();self.rate.addItems(['0.25×','0.5×','1×','2×']);self.rate.setCurrentIndex(2);self.rate.currentIndexChanged.connect(self.restart_clock);playbar.addWidget(self.rate)
        self.splitter.setSizes([300,1050]);self.splitter.setStretchFactor(1,1)
        self.analysis_toggle,self.analysis_panel,analysis=self.fold(page,'상세 분석 · 초기 물체 배치 / 품질 / 관절 움직임')
        self.overview=QualityOverview();analysis.addWidget(self.overview);self.overview.selected.connect(self.select_episode);self.scatter=self.overview.scatter
        self.actions=ReviewPlot('actions');self.actions.setMinimumHeight(175);analysis.addWidget(self.actions)
        self.metrics=QLabel('기록되지 않은 EEF·Task·기하 오차는 추정하지 않습니다.');self.metrics.setWordWrap(True);analysis.addWidget(self.metrics)
        self.advanced_toggle,self.advanced_panel,advanced=self.fold(page,'Dataset 구성 · Trim / Train·Validation / 상세 표')
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['사용','Episode','원본 시작','원본 끝(미포함)','원본 최대 끝','원 Episode 판정','Split'])
        for column,width in enumerate((64,140,110,150,150,190,100)):self.table.setColumnWidth(column,width)
        self.table.horizontalHeader().setSectionResizeMode(5,QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(2,FrameRangeDelegate(self.table));self.table.setItemDelegateForColumn(3,FrameRangeDelegate(self.table));self.table.setItemDelegateForColumn(6,SplitDelegate(self.table))
        self.table.itemChanged.connect(self.edited);self.table.currentCellChanged.connect(lambda row,col,previous_row,previous_col:self.selection_changed()if row!=previous_row else None);self.table.setMinimumHeight(240);advanced.addWidget(self.table)
        self.table.cellClicked.connect(lambda row,col:self.table.editItem(self.table.item(row,col))if not self.source_only and col in(2,3,6)else None)
        self.buttons={}
        if not source_only:
            ratio=QHBoxLayout();advanced.addLayout(ratio)
            self.train_ratio=QDoubleSpinBox();self.train_ratio.setRange(1,99);self.train_ratio.setValue(80);self.train_ratio.setSuffix('%');self.train_ratio.setMaximumWidth(140)
            self.split_seed=QSpinBox();self.split_seed.setRange(0,2147483647);self.split_seed.setMaximumWidth(160)
            ratio.addWidget(QLabel('Train 비율'));ratio.addWidget(self.train_ratio);ratio.addWidget(QLabel('Split Seed'));ratio.addWidget(self.split_seed)
            button=QPushButton('Train/Val 배치 미리보기');button.clicked.connect(self.split);ratio.addWidget(button,1);self.buttons['Train/Val 분할']=button
        else:self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_label=QLabel('작업 설명 · single_task: Dataset을 선택하세요.');self.task_label.setWordWrap(True);self.task_label.setTextFormat(Qt.TextFormat.PlainText)
        footer=QGridLayout();layout.addLayout(footer)
        if not source_only:
            footer.addWidget(self.task_label,0,0,1,3)
            for i,(text,fn)in enumerate([('Revision 저장',self.save_revision),('LeRobot Export',self.export),('Dataset Merge',self.merge)]):
                button=QPushButton(text);button.clicked.connect(fn);footer.addWidget(button,1,i);self.buttons[text]=button
                if i==0:button.setObjectName('primaryAction')
        self.job=BackendJob(python,self);self.job.finished.connect(self.finished)
        self.reader=ReviewClient(python,self.workspace,self.preview_directory,self);self.reader.opened.connect(self.review_opened);self.reader.frame.connect(self.review_finished);self.reader.error.connect(self.review_error)
        self.play_timer=QTimer(self);self.play_timer.setInterval(16);self.play_timer.timeout.connect(self.advance)

    @staticmethod
    def fold(layout,title):
        button=QPushButton('▸ '+title);button.setCheckable(True);layout.addWidget(button);panel=QWidget();body=QVBoxLayout(panel);layout.addWidget(panel);panel.hide()
        def toggle(expanded):panel.setVisible(expanded);button.setText(('▾ 'if expanded else'▸ ')+title)
        button.toggled.connect(toggle);return button,panel,body

    def select_episode(self,index):
        if index>=0:
            if self.episode_list.item(index).isHidden():self.filter.setCurrentIndex(0)
            self.table.setCurrentCell(index,1)

    def include_changed(self,item):
        if self.loading or self.source_only:return
        self.table.item(self.episode_list.row(item),0).setCheckState(item.checkState())

    def refresh_list(self):
        self.episode_list.blockSignals(True)
        try:
            if self.episode_list.count()!=len(self.rows):self.episode_list.clear()
            for i,row in enumerate(self.rows):
                label=outcome(row);flags=row.get('quality',{}).get('flags',[])
                role=self.table.item(i,6).text()or'미분할';item=self.episode_list.item(i)
                if item is None:item=QListWidgetItem();self.episode_list.addItem(item)
                item.setText(row['selection_id']+'\n'+label+' · '+role+('\n확인 필요 · '+', '.join(flags)if flags else''));item.setData(Qt.ItemDataRole.UserRole,row['selection_id'])
                item.setForeground(QColor('#efb467'if flags else'#dce5ee'));item.setToolTip('확인 필요는 불량 판정이나 자동 제외가 아닙니다.\n'+', '.join(flags)if flags else label)
                if not self.source_only:item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(self.table.item(i,0).checkState())
        finally:self.episode_list.blockSignals(False)
        self.apply_filter()
        self.overview.set_selection([dict(included=self.table.item(i,0).checkState()==Qt.CheckState.Checked,split=self.table.item(i,6).text())for i in range(len(self.rows))])

    def apply_filter(self,*_):
        for i,row in enumerate(self.rows):
            role=self.table.item(i,6).text();kind=self.filter.currentIndex();recording=row['success_source']=='recording_only'
            visible=kind==0 or kind==1 and not recording and row['recorded_success']is True or kind==2 and not recording and row['recorded_success']is False or kind==3 and recording or kind in(4,5)and role==self.filter.currentText()or kind==6 and bool(row.get('quality',{}).get('flags'))
            self.episode_list.item(i).setHidden(not visible)
        total=len(self.rows);included=sum(self.table.item(i,0).checkState()==Qt.CheckState.Checked for i in range(total));shown=sum(not self.episode_list.item(i).isHidden()for i in range(total))
        self.selection_count.setText(f'전체 {total}개 중 {included}개 포함 · 제외 {total-included} · 표시 {shown}')

    def frame_range(self,index=None):
        index=self.table.currentRow()if index is None else index
        parent_low,parent_high=self.rows[index]['selection_range']
        try:low,high=(int(self.table.item(index,col).text())for col in(2,3))
        except ValueError:raise ValueError('시작·끝 프레임은 정수로 입력하세요.')from None
        if not parent_low<=low<high<=parent_high:
            raise ValueError(f'편집 가능한 구간은 [{parent_low}, {parent_high})이며 시작은 끝보다 작아야 합니다.')
        return low,high

    def update_plot_cursor(self):
        index=self.table.currentRow()
        if index<0 or index>=len(self.rows):return
        frame=self.timeline.value()+self.frame_range()[0]-self.rows[index]['selection_range'][0]
        self.actions.set_frame(frame);payload=getattr(self,'last_review',{})
        self.trajectory.set_frame(frame,payload if payload.get('selection_id')==self.rows[index]['selection_id']else None)

    def seek(self,value):
        if self._syncing_review:return
        self.stop_playback()
        self._syncing_review=True
        self.timeline.setValue(value);self.update_clock(value)
        self._syncing_review=False;self.update_plot_cursor()
        self.review()

    def update_clock(self,value):
        index=self.table.currentRow()
        if index<0 or not self.timestamps:return
        offset=self.frame_range()[0]-self.rows[index]['selection_range'][0]
        times=self.timestamps[offset:offset+self.timeline.maximum()+1]
        if times:self.clock_label.setText(f'{times[min(value,len(times)-1)]-times[0]:.2f}s / {times[-1]-times[0]:.2f}s · {value+1} frame')

    def restart_clock(self,*_):
        self.play_start=self.timeline.value();self.elapsed.start()

    def toggle_play(self):
        if self.playing:self.stop_playback();return
        if not self.timestamps or self.plot_busy:return
        if self.timeline.value()==self.timeline.maximum():self.seek(0)
        self.playing=True;self.play_button.setText('일시정지');self.restart_clock();self.play_timer.start()

    def advance(self):
        import bisect
        index=self.table.currentRow()
        if index<0 or not self.timestamps:return
        offset=self.frame_range()[0]-self.rows[index]['selection_range'][0]
        stamp=self.timestamps[offset+self.play_start]+self.elapsed.elapsed()/1000*[.25,.5,1,2][self.rate.currentIndex()]
        value=min(self.timeline.maximum(),max(0,bisect.bisect_right(self.timestamps,stamp)-1-offset))
        if value!=self.last_requested:self.reader.request(offset+value);self.last_requested=value


    def stop_playback(self):
        self.playing=False;self.play_timer.stop();self.play_button.setText('재생')

    def hideEvent(self,event):
        self.close_review();super().hideEvent(event)

    def showEvent(self,event):
        super().showEvent(event)
        if self.source and self.rows:self.request_plot();self.review()

    def closeEvent(self,event):
        self.close_review();super().closeEvent(event)

    def close_review(self):
        self.stop_playback();self.reader.close()

    def request_plot(self):
        i=self.table.currentRow()
        if i<0 or not self.source:return
        self.plot_busy=True;self.timestamps=[];self.last_requested=None;self.last_review={}
        self.reader.select(self.source,self.rows[i]['selection_id'])

    def review_opened(self,info):
        self.plot_busy=False
        self.timestamps=info['timestamps'];data=info['plot'];self.plot_data=data;times=data['timestamps'];row={'states':data.get('states'),'state_action_comparable':data.get('state_action_comparable',False),'actions':data['targets'],'frames':data['frames'],'sample_indices':data['indices'],'timestamps':times,'duration':float(times[-1]-times[0]),'events':data['events'],'target_unit':data['target_unit'],'joint_order':data['joint_order']}
        self.actions.row=row
        scene=info.get('scene',{});self.trajectory.set_scene(scene)
        self.trajectory.row={**row,'ee':data['eef'],'object_paths':data.get('object_paths',{}),'display_frame':data['eef_frame'],'eef_unit':data['eef_unit']}if data['eef']is not None or scene else None
        self.geometry_note.setVisible(bool(info.get('scene_note')));self.geometry_note.setText('연결 가능한 원 Scene 모델이 없습니다. 영상·기록된 경로는 확인할 수 있습니다.');self.geometry_note.setToolTip(info.get('scene_note',''))
        self.trajectory.setToolTip(info.get('scene_note','')or'기록된 측정 관절·물체 자세와 원 Scene의 표시용 축약 Mesh. Physics 재실행 아님.')
        self.overview.regions=info.get('regions',{});self.overview.refresh();self.update_plot_cursor()
        self.sync_timeline_events();self.metrics.setText('기록 Target · '+data['target_unit']+' · '+str(data['frames'])+' frame'+(' · 그래프 최대512점 표본'if data['sampled']else'')+'\n'+data['event_phase'])

    def sync_timeline_events(self):
        if self.plot_data is None:return
        shift=self.frame_range()[0]-self.plot_data['original_range'][0]
        events={key:value-shift for key,value in self.plot_data['events'].items()if 0<=value-shift<=self.timeline.maximum()}
        self.timeline.set_events(events,self.timestamps[shift:shift+self.timeline.maximum()+1]or None)

    def review_error(self,message):
        self.plot_busy=False;self.stop_playback();self.state.setText(message)

    def review_finished(self,result):
        i=self.table.currentRow()
        if i<0 or result['selection_id']!=self.rows[i]['selection_id']:return
        value=result['original_frame']-self.frame_range()[0]
        if not 0<=value<=self.timeline.maximum():return
        self.last_review={k:v for k,v in result.items()if k!='images'};self._syncing_review=True
        self.timeline.setValue(value);self.update_clock(value);self._syncing_review=False
        self.update_plot_cursor()
        if self.playing and value>=self.timeline.maximum():self.stop_playback()
        for camera,label in self.images.items():
            raw=result['images'].get(camera)
            if raw is not None:label.setPixmap(QPixmap.fromImage(QImage.fromData(raw,b'PPM')))
            else:label.clear();label.setText(camera+' · 기록된 영상 없음')

    def perform(self,operation,**arguments):
        if self.busy:self.state.setText('현재 작업이 끝난 뒤 실행하세요');return
        self.busy=True;self.datasets.setEnabled(operation=='curation_editor');self.revisions.setEnabled(False);self.splitter.setEnabled(False);self.operation=operation;self.state.setText('Dataset 불러오는 중…'if operation=='curation_editor'else operation+' 처리 중…');self.job.start(operation,**arguments)
    def choose_source(self):
        p=QFileDialog.getExistingDirectory(self,'Dataset 최상위 폴더 선택 · run.json 또는 meta/info.json',str(self.workspace))
        if p:self.load_source(p)
    def choose_revision(self):
        root=self.workspace/'curation';root.mkdir(parents=True,exist_ok=True)
        p,_=QFileDialog.getOpenFileName(self,'저장 Curation Revision',str(root),'JSON (*.json)')
        if p:self.load_source(p)
    def load_source(self,path,*,notice=''):
        self.load_notice=notice
        path=str(Path(path).resolve())if path else''
        if self.busy:self.pending_source=path;return
        self.close_review();self.source=None;self.original_source=None;self.original_identity=None;self.revision_record=None;self.revisions.reset();self.rows=[];self.last_review={};self.plot_data=None;self.timestamps=[];self.plot_busy=False
        self.loading=True;self.table.setRowCount(0);self.episode_list.clear();self.overview.set_rows([]);self.loading=False;self.apply_filter()
        self.actions.row=None;self.trajectory.row=None;self.trajectory.set_scene({});self.actions.update();self.trajectory.update()
        self.metrics.clear();self.geometry_note.hide()
        self._syncing_review=True;self.timeline.setRange(0,0);self.timeline.set_events({});self._syncing_review=False
        self.filter.setCurrentIndex(0)
        self.episode_title.setText('Dataset을 불러오는 중…');self.task_label.setText('작업 설명 · 불러오는 중…');self.clock_label.setText('0.00s / 0.00s')
        for label in self.images.values():label.clear();label.setText('영상 없음')
        if not path:
            self.state.setText('선택할 Dataset이 없습니다.');self.episode_title.setText('Episode 없음');self.task_label.setText('작업 설명 · Dataset 없음');return
        self.perform('curation_editor',workspace=str(self.workspace),path=path)
    def edited(self,item=None):
        if self.loading:return
        self.dirty=True
        if item is not None and item.column()in(2,3):
            try:low,high=self.frame_range(item.row())
            except ValueError as error:self.stop_playback();self.state.setText(str(error));return
            if item.row()==self.table.currentRow():
                self._syncing_review=True;self.timeline.setRange(0,high-low-1);self._syncing_review=False
                self.sync_timeline_events();self.seek(0)
        self.state.setText('선택 편집 중 · 새 Revision으로 저장한 뒤 Export하세요');self.refresh_list()
    def selection_changed(self):
        if self.loading:return
        index=self.table.currentRow()
        if index<0 or index>=len(self.rows):return
        self.stop_playback();self._syncing_review=True
        try:
            low,high=self.frame_range(index)
            self.timeline.setRange(0,max(0,high-low-1));self.timeline.setValue(0)
            self.episode_list.setCurrentRow(index);self.episode_title.setText(self.rows[index]['selection_id']+' · 원본 ['+str(low)+', '+str(high)+')')
        except ValueError as error:self.state.setText(str(error));return
        finally:self._syncing_review=False
        self.overview.select(index);self.last_review={};self.request_plot();self.seek(0)
    def finished(self,response):
        self.busy=False;self.datasets.setEnabled(True);self.revisions.setEnabled(self.source is not None);self.splitter.setEnabled(True)
        pending=self.pending_source;self.pending_source=None
        if pending is not None and not(self.operation=='curation_editor'and response.get('ok')and response['result']['path']==pending):
            self.load_source(pending);return
        if not response.get('ok'):
            self.stop_playback();self.state.setText(response.get('error',{}).get('message','오류'));return
        result=response['result'];self.state.setText('완료')
        if self.operation=='curation_editor':
            self.close_review();self.plot_data=None;self.actions.row=None;self.trajectory.row=None;self.trajectory.set_scene({});self.last_review={};self.timestamps=[]
            descriptions=result.get('task_descriptions',[]);self.task_label.setText('작업 설명 · single_task: '+' / '.join(value or'미기록'for value in descriptions));self.task_label.setToolTip('Source에서 저장한 작업 문장입니다. Export와 Merge는 Episode의 문장을 그대로 사용합니다.')
            self.source=result['path'];self.original_source=result['original_path'];self.original_identity=result['original_identity'];self.revision_record=result['revision']
            self.datasets.show_original(result['original']);self.revisions.set_source(self.original_source,self.revision_record,result['revisions'])
            self.rows=result['inspection']['episodes'];self.overview.set_rows(self.rows,result.get('task_objects',()));self.loading=True;self.table.setRowCount(len(self.rows))
            try:
                for i,row in enumerate(self.rows):
                    check=QTableWidgetItem();check.setFlags(Qt.ItemFlag.ItemIsEnabled|(Qt.ItemFlag.ItemIsUserCheckable if not self.source_only else Qt.ItemFlag(0)));check.setCheckState(Qt.CheckState.Checked if row['included']else Qt.CheckState.Unchecked);self.table.setItem(i,0,check)
                    label=outcome(row)+' · Env '+str(row.get('env_index','?'))
                    values=[row['selection_id'],*row['edit_range'],row['original_frames'],label,row['edit_split']or'']
                    for j,value in enumerate(values,1):
                        item=QTableWidgetItem(str(value))
                        if j==2:item.setData(Qt.ItemDataRole.UserRole,row['selection_range'])
                        if j in(2,3,4):item.setToolTip(f"원본 전체: {row['original_frames']} frame · 편집 가능: [{row['selection_range'][0]}, {row['selection_range'][1]})")
                        if j in (1,4,5):item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(i,j,item)
                self.dirty=False
            finally:self.loading=False
            self.refresh_list()
            if self.rows:
                self.table.blockSignals(True);self.table.setCurrentCell(0,1);self.table.blockSignals(False)
                self.episode_list.blockSignals(True);self.episode_list.setCurrentRow(0);self.episode_list.blockSignals(False)
                self.selection_changed()
            warnings=sum(bool(row.get('quality',{}).get('flags'))for row in self.rows)
            self.state.setText(f'{len(self.rows)} Episode · 확인 필요 {warnings} · 주의 표시는 자동 제외가 아닙니다.'+(' · '+self.load_notice if self.load_notice else''))
        elif self.operation=='split':
            self.loading=True
            for role,ids in result['splits'].items():
                for i,row in enumerate(self.rows):
                    if row['selection_id'] in ids:self.table.item(i,6).setText(role)
            self.loading=False;self.edited();self.analysis_toggle.setChecked(True)
            QTimer.singleShot(0,lambda:self.page_scroll.ensureWidgetVisible(self.overview.scatter,0,12))
        elif self.operation=='save_revision':
            saved=result['datasets'];summary='저장 완료 · '+' / '.join(f"{row['role']}: {row['episodes']} Episode"for row in saved)
            self.load_source(saved[0]['path'],notice=summary)
        elif self.operation=='merge':
            if self.dirty:self.state.setText('Dataset Merge 저장 완료 · '+result['path']+' · 현재 편집은 유지됩니다.')
            else:self.load_source(result['path'],notice='Dataset Merge 저장 완료 · '+result['path'])
        elif self.operation=='materialize':self.state.setText('LeRobot 저장 완료 · '+result['path'])

    def stable(self):
        if not self.source or self.dirty:self.state.setText('Dataset 선택 후 변경한 선택/구간을 Revision에 저장하세요');return False
        return True
    def review(self):
        if not self.source:return
        i=self.table.currentRow()
        if i<0:self.state.setText('Episode를 선택하세요');return
        try:low,high=self.frame_range(i)
        except ValueError as error:self.state.setText(str(error));return
        self.last_requested=self.timeline.value();self.reader.request(low-self.rows[i]['selection_range'][0]+self.timeline.value(),manual=True)
    def save_revision(self):
        if not self.original_source or self.busy:return
        initial=self.revision_record['name']if self.revision_record else'선별'
        name,ok=QInputDialog.getText(self,'Revision 저장','선별 이름 · r001/r002 번호는 자동으로 붙습니다.',text=initial)
        if not ok:return
        try:
            order=[];ranges={};splits={};exclude=[]
            for i,row in enumerate(self.rows):
                id_=row['selection_id'];order.append(id_)
                ranges[id_]=list(self.frame_range(i));role=self.table.item(i,6).text().strip()
                if self.table.item(i,0).checkState()!=Qt.CheckState.Checked:
                    exclude.append(id_)
                elif role:splits.setdefault(role,[]).append(id_)
            self.perform('save_revision',workspace=str(self.workspace),source=self.source,name=name,
                         parent=self.source if self.revision_record else None,expected_original=self.original_identity,
                         order=order,exclude=exclude,frame_ranges=ranges,splits=splits)
        except ValueError as error:self.state.setText(str(error))
    def split(self):
        if self.stable():self.perform('split',source=self.source,train_fraction=self.train_ratio.value()/100,seed=self.split_seed.value())
    def export(self):
        if not self.stable():return
        parent=QFileDialog.getExistingDirectory(self,'새 Export 출력 상위 폴더',str(self.workspace/'dataset'))
        if parent:self.perform('materialize',source=self.source,output=str(Path(parent)/numbered_path(parent,'lerobot').name))
    def merge(self):
        if self.busy:self.state.setText('현재 작업이 끝난 뒤 실행하세요');return
        dialog=DatasetMergeDialog(self.job.python,self.workspace,self.datasets.rows,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        sources=dialog.paths
        parent=QFileDialog.getExistingDirectory(self,'새 Dataset Merge 출력 상위 폴더',str(self.workspace/'dataset'))
        if parent:self.perform('merge',sources=sources,output=str(Path(parent)/numbered_path(parent,'merged').name))
