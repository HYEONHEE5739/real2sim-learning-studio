"""Playback follows recorded time, rather than waiting on a process per frame."""
import json,os,subprocess,sys

import numpy as np
from test_native_dataset import episode,execution
from test_workbench_window import UI
from robot_learning_workbench.data.native import NativeRun
from robot_learning_workbench.data.video import AsyncVideoWriter


def test_qt_playback_advances_in_seconds_without_frame_jobs_or_status_flicker(tmp_path):
    video=tmp_path/'side.mp4';writer=AsyncVideoWriter(video,width=64,height=48)
    for i in range(90):writer.write(np.full((48,64,3),i*2,np.uint8))
    writer.close();workspace=tmp_path/'workspace'
    with NativeRun(workspace/'source'/'demo',execution('source'))as run:
        segment=run.segment('one');segment.write_episode(episode(90),episode_id='demo',metadata={'success_source':'recording_only'},media={'side':video,'wrist':video})
        segment.write_episode(episode(90),episode_id='no-wrist',metadata={'success_source':'recording_only'},media={'side':video});segment.commit()
    code='''
import sys,time
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.curation import CurationPage
app=QApplication([]);p=CurationPage(sys.argv[1],Path(sys.argv[2]));p.resize(1320,940);p.show()
def wait(predicate):
    deadline=time.monotonic()+25
    while not predicate()and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    assert predicate(),p.state.text()
wait(lambda:bool(p.rows)and not p.busy and not p.plot_busy and bool(getattr(p,'last_review',None)))
p.toggle_play();states=[];begin=time.monotonic()
while time.monotonic()-begin<1.25:app.processEvents();states.append(p.state.text());QTest.qWait(10)
p.stop_playback();app.processEvents()
assert p.timeline.value()>=28,('Playback stalled at frame',p.timeline.value())
assert len(set(states))==1,('Frame status flickers',set(states))
assert 's / 'in p.clock_label.text(),p.clock_label.text()
assert p.operation!='frame','A new Backend process is still being used per frame'
pid=p.reader.process.processId()
p.seek(5);p.seek(40);p.seek(10)
wait(lambda:p.last_review.get('original_frame')==10)
assert p.reader.process.processId()==pid
p.seek(0);wait(lambda:p.last_review.get('original_frame')==0)
p.select_episode(1);wait(lambda:p.last_review.get('selection_id')=='no-wrist')
assert p.images['wrist'].pixmap().isNull(),'Previous Episode camera leaked into current playback'
assert '기록된 영상 없음'in p.images['wrist'].text()
assert p.reader.process.processId()==pid
p.hide();app.processEvents();assert not p.reader.process.processId()
p.show();wait(lambda:not p.plot_busy and bool(p.reader.process.processId())and p.last_review.get('selection_id')=='no-wrist')
p.close();app.processEvents()
assert not p.preview_directory.exists()
assert not p.reader.process.processId()
'''
    result=subprocess.run([UI,'-B','-c',code,sys.executable,str(workspace)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=50)
    assert result.returncode==0,result.stdout+result.stderr
