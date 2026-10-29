"""Native selections and existing Curation APIs; slow reads run outside Qt."""
from pathlib import Path
import json,uuid
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QFileDialog,QLineEdit,QTableWidget,QTableWidgetItem,QAbstractItemView,QSpinBox,QPlainTextEdit,QComboBox,QScrollArea,QSplitter,QGridLayout,QListWidget,QListWidgetItem,QTabWidget,QDoubleSpinBox,QFormLayout
from .jobs import BackendJob


class CurationPage(QWidget):
    def __init__(self,python,workspace,parent=None,*,source_only=False):
        super().__init__(parent)
        from .view import CameraView,EventTimeline
        from .plots import ReviewPlot,HistogramPlot
        from .theme import STYLE
        self.setStyleSheet(STYLE);self.workspace=Path(workspace);self.source_only=source_only;self.source=None;self.rows=[];self.dirty=False;self.loading=False;self.operation=None;self.busy=False;self.preview_directory=self.workspace/'.review'/uuid.uuid4().hex
        self._syncing_review=False;self.playing=False;self.pending_review=False;self.plot_busy=False;self.plot_target=None;self.plot_active=None;self.plot_data=None
        layout=QVBoxLayout(self);layout.setSpacing(10);header=QHBoxLayout();layout.addLayout(header)
        title=QLabel('Source 검토'if source_only else'Data Curation');title.setStyleSheet('font-size:22px; font-weight:600;');header.addWidget(title);header.addStretch()
        for text,fn in [('데이터 열기',self.choose_source),('Revision 열기',self.choose_revision)]:
            button=QPushButton(text);button.clicked.connect(fn);header.addWidget(button)
        self.path=QLineEdit();self.path.setReadOnly(True);layout.addWidget(self.path)
        self.state=QLabel('Episode 검토 · 영상과 기록 확인 · 원본 보존');self.state.setWordWrap(True);layout.addWidget(self.state)
        self.page_scroll=QScrollArea();self.page_scroll.setWidgetResizable(True);layout.addWidget(self.page_scroll,1);content=QWidget();page=QVBoxLayout(content);page.setContentsMargins(0,0,0,0);page.setSpacing(10);self.page_scroll.setWidget(content)
        self.splitter=QSplitter();self.splitter.setMinimumHeight(380);page.addWidget(self.splitter,1)
        self.episode_panel=QWidget();left=QVBoxLayout(self.episode_panel);self.splitter.addWidget(self.episode_panel);left.addWidget(QLabel('Episode 목록'))
        self.filter=QComboBox();self.filter.addItems(['전체','작업 성공','작업 실패','recording_only','train','val']);self.filter.currentIndexChanged.connect(self.apply_filter);left.addWidget(self.filter)
        self.episode_list=QListWidget();self.list=self.episode_list;self.episode_list.setMinimumWidth(220);self.episode_list.setWordWrap(True);left.addWidget(self.episode_list,1)
        self.episode_list.currentRowChanged.connect(self.select_episode);self.episode_list.itemChanged.connect(self.include_changed)
        self.exclude_button=QPushButton('선택 Episode 제외 / 포함');self.exclude_button.clicked.connect(self.toggle_episode);left.addWidget(self.exclude_button);self.exclude_button.setVisible(not source_only)
        right=QWidget();review=QVBoxLayout(right);self.splitter.addWidget(right);self.episode_title=QLabel('Episode를 선택하세요');review.addWidget(self.episode_title)
        self.preview_tabs=QTabWidget();review.addWidget(self.preview_tabs,1);videos=QWidget();rgb=QHBoxLayout(videos);self.images={}
        for name in ('side','wrist'):
            col=QVBoxLayout();rgb.addLayout(col,1);col.addWidget(QLabel(name.title()));label=CameraView('영상 없음',(120,120));col.addWidget(label,1);self.images[name]=label
        self.preview_tabs.addTab(videos,'영상 · Side / Wrist')
        trajectory_page=QWidget();trajectory_layout=QVBoxLayout(trajectory_page);views=QHBoxLayout();views.addWidget(QLabel('드래그 회전 · 휠 확대'));trajectory_layout.addLayout(views)
        self.trajectory=ReviewPlot('trajectory');trajectory_layout.addWidget(self.trajectory,1)
        for name in ('3D','XY','XZ','YZ'):
            button=QPushButton(name);button.clicked.connect(lambda _,n=name:self.trajectory.set_view(n));views.addWidget(button)
        self.trajectory.set_view('3D');self.preview_tabs.addTab(trajectory_page,'기록된 EEF 경로')
        playbar=QHBoxLayout();review.addLayout(playbar);self.play_button=QPushButton('재생');self.play_button.clicked.connect(self.toggle_play);playbar.addWidget(self.play_button)
        self.timeline=EventTimeline();self.timeline.setRange(0,0);self.timeline.valueChanged.connect(self.seek);self.timeline.eventPicked.connect(self.seek);playbar.addWidget(self.timeline,1)
        self.clock_label=QLabel('0 / 0');playbar.addWidget(self.clock_label);self.rate=QComboBox();self.rate.addItems(['0.25×','0.5×','1×','2×']);self.rate.setCurrentIndex(2);playbar.addWidget(self.rate)
        self.frame=QSpinBox();self.frame.setRange(0,0);self.frame.setMaximumWidth(100);self.frame.valueChanged.connect(self.seek)
        self.review_button=QPushButton('저장 Frame 검토');self.review_button.clicked.connect(self.review)
        trim=QGridLayout();review.addLayout(trim);self.trim_start=QSpinBox();self.trim_stop=QSpinBox()
        for column,(label,widget)in enumerate([('원본 시작',self.trim_start),('원본 끝 (미포함)',self.trim_stop)]):trim.addWidget(QLabel(label),0,column);trim.addWidget(widget,1,column)
        self.trim_start.valueChanged.connect(self.trim_changed);self.trim_stop.valueChanged.connect(self.trim_changed);self.trim_start.setEnabled(not source_only);self.trim_stop.setEnabled(not source_only)
        trim.addWidget(self.frame,2,0);trim.addWidget(self.review_button,2,1);self.splitter.setSizes([300,1050]);self.splitter.setStretchFactor(1,1)
        self.analysis_toggle,self.analysis_panel,analysis=self.fold(page,'상세 분석 · 기록 Target / Action·Observation 분포')
        self.actions=ReviewPlot('actions');self.actions.setMinimumHeight(175);analysis.addWidget(self.actions)
        self.metrics=QLabel('기록되지 않은 EEF·Task·기하 오차는 추정하지 않습니다.');self.metrics.setWordWrap(True);analysis.addWidget(self.metrics)
        self.scope=QComboBox();self.scope.addItems(['현재 전체 선택','train','val']);analysis.addWidget(self.scope)
        controls=QHBoxLayout();analysis.addLayout(controls)
        for text,fn in [('분포 통계',self.analyze),('Dataset 비교',self.compare)]:
            button=QPushButton(text);button.clicked.connect(fn);controls.addWidget(button)
        stat_controls=QHBoxLayout();analysis.addLayout(stat_controls);self.stats_field=QComboBox();self.stats_component=QSpinBox();self.stats_component.setRange(0,0);stat_controls.addWidget(self.stats_field);stat_controls.addWidget(self.stats_component)
        self.histogram=HistogramPlot();analysis.addWidget(self.histogram);self.stats_field.currentTextChanged.connect(self.update_histogram);self.stats_component.valueChanged.connect(self.update_histogram)
        position=QFormLayout();analysis.addLayout(position);self.position_object=QLineEdit();self.position_object.setPlaceholderText('기록된 Object ID');self.position_frame=QComboBox();self.position_frame.setEditable(True);self.position_frame.addItems(['robot_base','world']);position.addRow('Object',self.position_object);position.addRow('좌표 Frame',self.position_frame)
        locate=QPushButton('선택 시작 Object 분포 · 검사 Scene 필요');locate.clicked.connect(self.positions);analysis.addWidget(locate);self.scatter=ReviewPlot('scatter');analysis.addWidget(self.scatter)
        self.advanced_toggle,self.advanced_panel,advanced=self.fold(page,'Dataset 구성 · Trim / Train·Validation / 상세 표')
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['사용','Episode','원본 시작','원본 끝(미포함)','원 Episode 판정','Split']);self.table.itemChanged.connect(self.edited);self.table.itemSelectionChanged.connect(self.selection_changed);advanced.addWidget(self.table)
        ratio=QGridLayout();advanced.addLayout(ratio);self.train_ratio=QDoubleSpinBox();self.train_ratio.setRange(1,99);self.train_ratio.setValue(80);self.train_ratio.setSuffix('%');self.split_seed=QSpinBox();self.split_seed.setRange(0,2147483647)
        ratio.addWidget(QLabel('Train 비율'),0,0);ratio.addWidget(self.train_ratio,0,1);ratio.addWidget(QLabel('Split Seed (Pose Seed 아님)'),1,0);ratio.addWidget(self.split_seed,1,1)
        self.buttons={}
        if not source_only:
            button=QPushButton('Train/Val 배치 미리보기');button.clicked.connect(self.split);advanced.addWidget(button);self.buttons['Train/Val 분할']=button
            assignment=QHBoxLayout();advanced.addLayout(assignment);self.assign=QComboBox();self.assign.addItems(['train','val']);assignment.addWidget(self.assign);button=QPushButton('선택 Episode에 지정');button.clicked.connect(self.assign_split);assignment.addWidget(button)
        else:self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result=QPlainTextEdit();self.result.setReadOnly(True);self.result.setMaximumBlockCount(300);self.result.setMaximumHeight(190);advanced.addWidget(self.result)
        self.task=QLineEdit();self.task.setPlaceholderText('학습용 실제 작업 문장 · Export 시 필수')
        footer=QGridLayout();layout.addLayout(footer)
        if not source_only:
            footer.addWidget(self.task,0,0,1,3)
            for i,(text,fn)in enumerate([('Revision 저장',self.save_revision),('LeRobot Export',self.export),('호환 Merge',self.merge)]):
                button=QPushButton(text);button.clicked.connect(fn);footer.addWidget(button,1,i);self.buttons[text]=button
                if i==0:button.setObjectName('primaryAction')
        self.job=BackendJob(python,self);self.job.finished.connect(self.finished);self.job.log.connect(self.result.appendPlainText)
        self.plot_job=BackendJob(python,self);self.plot_job.finished.connect(self.plot_finished)
        self.play_timer=QTimer(self);self.play_timer.timeout.connect(self.advance)

    @staticmethod
    def fold(layout,title):
        button=QPushButton('▸ '+title);button.setCheckable(True);layout.addWidget(button);panel=QWidget();body=QVBoxLayout(panel);layout.addWidget(panel);panel.hide()
        def toggle(expanded):panel.setVisible(expanded);button.setText(('▾ 'if expanded else'▸ ')+title)
        button.toggled.connect(toggle);return button,panel,body

    def select_episode(self,index):
        if index>=0:self.table.setCurrentCell(index,1)

    def include_changed(self,item):
        if self.loading or self.source_only:return
        self.table.item(self.episode_list.row(item),0).setCheckState(item.checkState())

    def toggle_episode(self):
        i=self.table.currentRow()
        if i>=0:self.table.item(i,0).setCheckState(Qt.CheckState.Unchecked if self.table.item(i,0).checkState()==Qt.CheckState.Checked else Qt.CheckState.Checked)

    def refresh_list(self):
        self.episode_list.blockSignals(True)
        try:
            if self.episode_list.count()!=len(self.rows):self.episode_list.clear()
            for i,row in enumerate(self.rows):
                outcome='recording_only'if row['success_source']=='recording_only'else'성공'if row['recorded_success']is True else'실패'if row['recorded_success']is False else'미확인'
                role=self.table.item(i,5).text()or'미분할';item=self.episode_list.item(i)
                if item is None:item=QListWidgetItem();self.episode_list.addItem(item)
                item.setText(row['selection_id']+'\n'+outcome+' · '+role+' · '+str(row['category']or''));item.setData(Qt.ItemDataRole.UserRole,row['selection_id'])
                if not self.source_only:item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(self.table.item(i,0).checkState())
        finally:self.episode_list.blockSignals(False)
        self.apply_filter()

    def apply_filter(self,*_):
        for i,row in enumerate(self.rows):
            role=self.table.item(i,5).text();kind=self.filter.currentIndex();recording=row['success_source']=='recording_only'
            visible=kind==0 or kind==1 and not recording and row['recorded_success']is True or kind==2 and not recording and row['recorded_success']is False or kind==3 and recording or kind>=4 and role==self.filter.currentText()
            self.episode_list.item(i).setHidden(not visible)

    def trim_changed(self,*_):
        if self._syncing_review or self.source_only:return
        index=self.table.currentRow()
        if index<0:return
        self.table.item(index,2).setText(str(self.trim_start.value()));self.table.item(index,3).setText(str(self.trim_stop.value()))
        self.frame.setMaximum(max(0,self.trim_stop.value()-self.trim_start.value()-1));self.timeline.setMaximum(self.frame.maximum());self.sync_timeline_events()
        self.update_plot_cursor()

    def update_plot_cursor(self):
        index=self.table.currentRow()
        if index<0 or index>=len(self.rows):return
        frame=self.frame.value()+self.trim_start.value()-self.rows[index]['selection_range'][0]
        self.actions.set_frame(frame);self.trajectory.set_frame(frame)

    def seek(self,value):
        if self._syncing_review:return
        self._syncing_review=True
        self.frame.setValue(value);self.timeline.setValue(value);self.clock_label.setText(f'{value} / {self.frame.maximum()} · frame0')
        self._syncing_review=False;self.update_plot_cursor()
        if self.busy:self.pending_review=True
        else:self.review()

    def toggle_play(self):
        self.playing=not self.playing;self.play_button.setText('일시정지'if self.playing else'재생')
        if self.playing:self.play_timer.start(max(1,int(33/[.25,.5,1,2][self.rate.currentIndex()])))
        else:self.play_timer.stop()

    def advance(self):
        if self.busy:return
        if self.frame.value()>=self.frame.maximum():self.stop_playback();return
        self.seek(self.frame.value()+1)

    def stop_playback(self):
        self.playing=False;self.play_timer.stop();self.play_button.setText('재생')

    def hideEvent(self,event):
        self.stop_playback();super().hideEvent(event)

    def closeEvent(self,event):
        self.stop_playback();super().closeEvent(event)

    def assign_split(self):
        i=self.table.currentRow()
        if i>=0:self.table.item(i,5).setText(self.assign.currentText())

    def positions(self):
        if not self.stable():return
        owner=self.parentWidget()
        while owner is not None and not hasattr(owner,'scene'):owner=owner.parentWidget()
        scene=getattr(owner,'scene',None)
        if scene is None or not scene.valid:self.state.setText('정확한 기록 Scene을 먼저 검사하세요');return
        self.perform('positions',source=self.source,object_id=self.position_object.text().strip(),scene=scene.scene_path,frame=self.position_frame.currentText(),split=None if self.scope.currentIndex()==0 else self.scope.currentText())

    def request_plot(self):
        i=self.table.currentRow()
        if i<0 or not self.source:return
        self.plot_target=(self.source,self.rows[i]['selection_id'])
        if self.plot_busy:return
        self.plot_active=self.plot_target;self.plot_busy=True;self.plot_job.start('episode_plot',source=self.plot_active[0],selection_id=self.plot_active[1])

    def plot_finished(self,response):
        self.plot_busy=False
        if self.plot_active!=self.plot_target:self.request_plot();return
        if not response.get('ok'):self.metrics.setText(response.get('error',{}).get('message','기록된 plot 없음'));return
        data=response['result'];self.plot_data=data;times=data['timestamps'];row={'actions':data['targets'],'frames':data['frames'],'sample_indices':data['indices'],'timestamps':times,'duration':float(times[-1]-times[0]),'events':data['events'],'target_unit':data['target_unit'],'joint_order':data['joint_order']}
        self.actions.row=row
        self.trajectory.row={**row,'ee':data['eef'],'display_frame':data['eef_frame'],'eef_unit':data['eef_unit']}if data['eef']is not None else None;self.update_plot_cursor()
        self.sync_timeline_events();self.metrics.setText('기록 Target · '+data['target_unit']+' · '+str(data['frames'])+' frame'+(' · 그래프 최대512점 표본'if data['sampled']else'')+'\n'+data['event_phase'])

    def sync_timeline_events(self):
        if self.plot_data is None:return
        shift=self.trim_start.value()-self.plot_data['original_range'][0]
        events={key:value-shift for key,value in self.plot_data['events'].items()if 0<=value-shift<=self.frame.maximum()}
        self.timeline.set_events(events)
        for marker in self.timeline.markers:
            marker['time']=self.plot_data.get('event_times_s',{}).get(marker['name'],marker['time'])
            marker['label']+=' · 저장 선택 시작 기준 시각'

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
        if not self.loading:
            self.dirty=True;self.state.setText('선택 편집 중 · 새 Revision으로 저장한 뒤 통계/Export하세요');self.refresh_list()
    def selection_changed(self):
        if self.loading:return
        index=self.table.currentRow()
        if index<0 or index>=len(self.rows):return
        self.stop_playback();self._syncing_review=True
        try:
            low=int(self.table.item(index,2).text());high=int(self.table.item(index,3).text());parent=self.rows[index]['selection_range']
            self.trim_start.setRange(parent[0],parent[1]-1);self.trim_stop.setRange(parent[0]+1,parent[1]);self.trim_start.setValue(low);self.trim_stop.setValue(high)
            self.frame.setMaximum(max(0,high-low-1));self.frame.setValue(0);self.timeline.setRange(0,self.frame.maximum());self.timeline.setValue(0)
            self.episode_list.setCurrentRow(index);self.episode_title.setText(self.rows[index]['selection_id']+' · 원본 ['+str(low)+', '+str(high)+')')
        finally:self._syncing_review=False
        self.request_plot();self.review()
    def finished(self,response):
        self.busy=False
        if not response.get('ok'):
            self.stop_playback();self.pending_review=False;self.state.setText(response.get('error',{}).get('message','오류'));return
        result=response['result'];self.state.setText('완료 · 원본 데이터는 변경하지 않았습니다')
        if self.operation=='catalog':
            self.stop_playback();self.plot_target=None;self.plot_data=None;self.actions.row=None;self.trajectory.row=None
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
            self.refresh_list()
            if self.rows:
                self.table.blockSignals(True);self.table.setCurrentCell(0,1);self.table.blockSignals(False)
                self.episode_list.blockSignals(True);self.episode_list.setCurrentRow(0);self.episode_list.blockSignals(False)
                self.selection_changed()
            self.result.setPlainText(json.dumps({'선택_frame':result['inspection']['selected_frames'],
                '원본_attempt':[{'attempt':r['attempt'],'status':r['status'],'category':r.get('diagnostics',{}).get('category'),'steps':r.get('diagnostics',{}).get('steps')} for r in result['inspection']['source_attempts']],
                '미확정_수':len(result['inspection']['unresolved_source_intents'])},ensure_ascii=False,indent=2))
        elif self.operation=='frame':
            current=self.table.currentRow()
            if current>=0 and result['selection_id']==self.rows[current]['selection_id'] and result['original_frame']==self.trim_start.value()+self.frame.value():
                self.last_review={k:v for k,v in result.items()if k not in ('images','source_identity')}
                for camera,label in self.images.items():
                    path=result['images'].get(camera)
                    if path:label.setPixmap(QPixmap(path))
                    else:label.clear();label.setText(camera+' · 기록된 영상 없음')
                self.result.setPlainText(json.dumps(self.last_review,ensure_ascii=False,indent=2))
            if self.pending_review:self.pending_review=False;self.review()
        elif self.operation=='positions':
            rows={r['selection_id']:r for r in self.rows}
            self.scatter.rows=[dict(xy=p['xy_m'],name=p['selection_id'],flags=[],split=rows[p['selection_id']]['split'])for p in result['points']];self.scatter.update()
            self.metrics.setText('선택 구간 첫 기록 위치 · '+result['frame']+' [m] · '+str(len(result['points']))+' Episode · Physics 초기 상태로 재명명하지 않음')
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
            self.result.setPlainText('\n'.join(lines));self.histogram.series=datasets;self.stats_field.clear();self.stats_field.addItems(list(datasets[0]['fields']));self.update_histogram()
        else:self.result.setPlainText(json.dumps(result,ensure_ascii=False,indent=2))
    def update_histogram(self,*_):
        if not self.histogram.series or not self.stats_field.currentText():return
        name=self.stats_field.currentText();row=self.histogram.series[0]['fields'][name]
        self.stats_component.setMaximum(len(row['mean'])-1);self.histogram.field=name;self.histogram.component=self.stats_component.value();self.histogram.update()
        scopes=['Dataset '+str(i+1)+' · '+str(d['scope']['episodes'])+' Episode / '+str(d['scope']['frames'])+' frame · '+str(d['scope'].get('split')or'현재 전체 선택')for i,d in enumerate(self.histogram.series)]
        index=self.stats_component.value();self.metrics.setText('\n'.join(scopes)+'\n'+name+' ['+str(row['unit'])+'] · '+row['phase']+' · 평균 '+str(row['mean'][index])+' / 최소 '+str(row['min'][index])+' / 최대 '+str(row['max'][index]))

    def stable(self):
        if not self.source or self.dirty:self.state.setText('Dataset 선택 후 변경한 선택/구간을 Revision에 저장하세요');return False
        return True
    def review(self):
        if not self.source:return
        i=self.table.currentRow()
        if i<0:self.state.setText('Episode를 선택하세요');return
        parent_low,parent_high=self.rows[i]['selection_range'];low=self.trim_start.value();high=self.trim_stop.value()
        if not parent_low<=low<high<=parent_high:self.state.setText('구간은 부모 선택 안의 비어 있지 않은 [시작, 끝)이어야 합니다');return
        if self.busy:self.pending_review=True;return
        self.perform('frame',source=self.source,selection_id=self.rows[i]['selection_id'],frame=low-parent_low+self.frame.value(),preview_directory=str(self.preview_directory))
    def save_revision(self):
        if not self.source:return
        from .paths import output_path
        path,_=QFileDialog.getSaveFileName(self,'새 Curation Revision',str(output_path(self.workspace,'curation').with_suffix('.json')),'JSON (*.json)')
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
        if self.stable():self.perform('split',source=self.source,train_fraction=self.train_ratio.value()/100,seed=self.split_seed.value())
    def analyze(self):
        if self.stable():self.perform('distribution',source=self.source,split=None if self.scope.currentIndex()==0 else self.scope.currentText())
    def compare(self):
        if not self.stable():return
        other=QFileDialog.getExistingDirectory(self,'비교 Dataset')
        if other:self.perform('compare',sources=[self.source,other])
    def export(self):
        if not self.stable():return
        if not self.task.text().strip():self.state.setText('실제 작업 문장을 입력하세요');return
        parent=QFileDialog.getExistingDirectory(self,'새 Export 출력 상위 폴더',str(self.workspace/'dataset'))
        if parent:self.perform('materialize',source=self.source,output=str(Path(parent)/('lerobot-'+uuid.uuid4().hex[:8])),task=self.task.text(),split=None if self.scope.currentIndex()==0 else self.scope.currentText())
    def merge(self):
        if not self.stable():return
        other=QFileDialog.getExistingDirectory(self,'Merge할 다른 canonical Dataset')
        if not other:return
        parent=QFileDialog.getExistingDirectory(self,'새 Merge 출력 상위 폴더',str(self.workspace/'dataset'))
        if parent:self.perform('merge',sources=[self.source,other],output=str(Path(parent)/('merged-'+uuid.uuid4().hex[:8])),task=self.task.text() or None)
