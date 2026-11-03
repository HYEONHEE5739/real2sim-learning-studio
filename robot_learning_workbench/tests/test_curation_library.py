"""Workspace results must be discoverable and reviewable across all four stages."""
from pathlib import Path

import numpy as np
import pytest

from test_native_dataset import episode,execution
from robot_learning_workbench.data import native,lerobot
from robot_learning_workbench.data.video import AsyncVideoWriter
from robot_learning_workbench.ui.operations import execute


@pytest.fixture
def library(tmp_path):
    workspace=tmp_path/'workspace';video=tmp_path/'camera.mp4'
    writer=AsyncVideoWriter(video,width=64,height=48)
    for value in (30,60,90,120):writer.write(np.full((48,64,3),value,np.uint8))
    writer.close();paths={}
    for stage in ('source','annotation','datagen'):
        with native.NativeRun(workspace/stage/('my-'+stage),execution(stage))as run:
            segment=run.segment('one');segment.write_episode(episode(4),episode_id='episode-1',
                metadata={'success_source':'recording_only'if stage=='source'else'physical_task'},media={'side':video,'wrist':video});segment.commit()
        paths[stage]=run.root
    paths['lerobot']=lerobot.materialize(paths['source'],workspace/'dataset'/'official',task='Pick the red cube')
    return workspace,paths


def test_catalog_discovers_source_annotation_datagen_and_official_and_reviews_each(library,tmp_path):
    workspace,paths=library
    before={p:native.file_sha256(p)for p in workspace.rglob('*')if p.is_file()}
    rows=execute({'operation':'curation_datasets','arguments':{'workspace':str(workspace)}})['datasets']
    assert {r['category']for r in rows}=={'source','annotation','datagen','lerobot'}
    assert {r['path']for r in rows}=={str(p)for p in paths.values()}
    for row in rows:
        assert row['episodes']==1 and row['frames']==4 and row['readable']
        catalog=execute({'operation':'catalog','arguments':{'path':row['path']}})
        selection=catalog['inspection']['episodes'][0]['selection_id']
        review=execute({'operation':'frame','arguments':{'source':row['path'],'selection_id':selection,'frame':2,'preview_directory':str(tmp_path/'preview')}})
        assert review['original_frame']==2 and set(review['images'])=={'side','wrist'}
        for image in review['images'].values():
            header,pixels=Path(image).read_bytes().split(b'\n255\n',1)
            assert b'64 48'in header  # Review retains the stored camera resolution.
            assert abs(np.frombuffer(pixels,np.uint8).mean()-90)<3
        plot=execute({'operation':'episode_plot','arguments':{'source':row['path'],'selection_id':selection}})
        assert plot['frames']==4 and len(plot['targets'])==4
    assert before=={p:native.file_sha256(p)for p in workspace.rglob('*')if p.is_file()}


def test_library_reports_broken_and_empty_runs_without_hiding_good_results(library):
    workspace,paths=library
    broken=workspace/'source'/'broken';broken.mkdir();(broken/'run.json').write_text('{}')
    with native.NativeRun(workspace/'source'/'empty',execution('source')):pass
    rows=execute({'operation':'curation_datasets','arguments':{'workspace':str(workspace)}})['datasets']
    by_path={r['path']:r for r in rows}
    assert all(by_path[str(path)]['readable']for path in paths.values())
    assert not by_path[str(broken)]['readable'] and by_path[str(broken)]['error']
    assert by_path[str(workspace/'source'/'empty')]['episodes']==0


def test_persistent_reader_seeks_exact_recorded_frames_for_all_four_types(library):
    from robot_learning_workbench.data.review import EpisodeReview
    workspace,paths=library
    before={p:native.file_sha256(p)for p in workspace.rglob('*')if p.is_file()}
    for source in paths.values():
        ep=native.load_catalog(source).episodes[0]
        reader=EpisodeReview(source,ep.selection_id or ep.episode_id)
        try:
            first=reader.frame(0);decoder=reader.decoders['side']
            second=reader.frame(1)
            assert reader.decoders['side']is decoder  # Sequential playback reuses the codec.
            assert second['timestamp_s']>first['timestamp_s']
            for index in (3,2,2,0,1):
                result=reader.frame(index)
                assert result['original_frame']==index
                assert abs(result['rgb']['side'].mean()-(30+index*30))<3
                assert abs(result['video_pts_s']['side']-index/30)<1e-6
        finally:reader.close()
        assert not reader.decoders and reader.file is None
    assert before=={p:native.file_sha256(p)for p in workspace.rglob('*')if p.is_file()}


def test_qt_library_opens_and_plays_all_four_dataset_types(library,tmp_path):
    import json,os,subprocess,sys
    from test_workbench_window import UI
    workspace,paths=library
    code='''
from pathlib import Path
import json,sys,time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.curation import CurationPage
app=QApplication([]);paths=json.loads(sys.argv[3]);p=CurationPage(sys.argv[1],Path(sys.argv[2]));p.resize(1320,940)
assert hasattr(p,'datasets'),'Data Curation has no Workspace Dataset selector'
p.show()
def wait(predicate):
    deadline=time.monotonic()+30
    while not predicate()and time.monotonic()<deadline:app.processEvents();QTest.qWait(20)
    assert predicate(),p.state.text()
wait(lambda:len(p.datasets.rows)==4 and bool(p.rows) and not p.busy)
for kind,path in paths.items():
    wait(lambda:not p.busy and not p.plot_busy)
    p.datasets.kind.setCurrentIndex(p.datasets.kind.findData(kind))
    assert p.datasets.choices.count()==1
    assert p.datasets.choices.currentData()['path']==path
    wait(lambda:p.source==path and not p.busy)
    assert len(p.rows)==1 and p.episode_list.count()==1
    p.seek(2);wait(lambda:not p.busy and getattr(p,'last_review',{}).get('original_frame')==2)
    assert all(not image.pixmap().isNull()for image in p.images.values())
    p.toggle_play();wait(lambda:not p.playing)
    assert p.timeline.value()==3
wait(lambda:not p.plot_busy and not p.busy)
assert not any(name in sys.modules for name in ('torch','mujoco','isaaclab','lerobot'))
p.close();app.processEvents()
'''
    result=subprocess.run([UI,'-B','-c',code,sys.executable,str(workspace),json.dumps({k:str(v)for k,v in paths.items()})],
        env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=100)
    assert result.returncode==0,result.stdout+result.stderr


def test_qt_dataset_choice_switches_immediately_and_counts_included_episodes(library,tmp_path):
    import json,os,subprocess,sys
    from test_workbench_window import UI
    workspace,paths=library
    other=workspace/'source'/'another'
    with native.NativeRun(other,execution('source'))as run:
        segment=run.segment('one')
        for i in range(2):segment.write_episode(episode(4),episode_id='other-'+str(i))
        segment.commit()
    code='''
import sys,time
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication,QPushButton
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.curation import CurationPage
app=QApplication([]);root=Path(sys.argv[2]);p=CurationPage(sys.argv[1],root);p.show()
def wait(test):
 end=time.monotonic()+25
 while not test()and time.monotonic()<end:app.processEvents();QTest.qWait(10)
 assert test(),p.state.text()
wait(lambda:bool(p.rows)and not p.busy and len(p.datasets.rows)==5)
labels=[button.text()for button in p.findChildren(QPushButton)]
assert not {'선택 Dataset 열기','새로고침','선택 Episode 제외 / 포함'}&set(labels)
p.datasets.kind.setCurrentIndex(p.datasets.kind.findData('source'))
def index(path):return next(i for i in range(p.datasets.choices.count())if p.datasets.choices.itemData(i)['path']==str(path))
original=root/'source'/'my-source';other=root/'source'/'another'
p.datasets.choices.setCurrentIndex(index(original));p.datasets.choices.setCurrentIndex(index(other))
wait(lambda:p.source==str(other)and not p.busy and len(p.rows)==2)
assert p.episode_list.item(0).text().startswith('other-0')
assert '전체 2개 중 2개 포함'in p.selection_count.text()
p.episode_list.item(0).setCheckState(Qt.CheckState.Unchecked)
assert '전체 2개 중 1개 포함'in p.selection_count.text()
assert '제외 1'in p.selection_count.text()
assert not hasattr(p,'export_scope')
p.filter.setCurrentText('Source Demo')
assert '전체 2개 중 1개 포함'in p.selection_count.text()
p.datasets.choices.setCurrentIndex(index(original))
wait(lambda:p.source==str(original)and not p.busy and len(p.rows)==1)
assert '전체 1개 중 1개 포함'in p.selection_count.text()
assert not hasattr(p,'export_scope')
p.datasets.kind.addItem('비어 있는 종류','absent');p.datasets.kind.setCurrentIndex(p.datasets.kind.count()-1)
wait(lambda:not p.busy and p.source is None and not p.rows)
assert p.episode_list.count()==0 and '전체 0개 중 0개 포함'in p.selection_count.text()
assert p.timeline.maximum()==0 and not p.timeline.markers
assert p.overview.summary.text()=='Episode를 선택하세요.'
p.close();app.processEvents()
'''
    result=subprocess.run([UI,'-B','-c',code,sys.executable,str(workspace)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=70)
    assert result.returncode==0,result.stdout+result.stderr
