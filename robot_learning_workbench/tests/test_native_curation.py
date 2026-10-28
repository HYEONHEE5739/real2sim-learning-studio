"""Permanent non-destructive Curation, across a fresh interpreter."""
import json,subprocess,sys,os
from pathlib import Path
import pytest
from test_native_dataset import episode,execution
from robot_learning_workbench.data import native as n,curation as c

@pytest.fixture
def hundred(tmp_path):
    with n.NativeRun(tmp_path/'source',execution()) as run:
        for batch in range(10):
            seg=run.segment('batch'+str(batch))
            for i in range(batch*10,(batch+1)*10):seg.write_episode(episode(5),episode_id=f'e{i}')
            seg.commit()
    return n.load_catalog(run.root)


def test_v1_80_exit_reload_v2_70_and_unchanged_source(hundred,tmp_path):
    source=hundred;before={p:n.file_sha256(p) for p in source.root.rglob('*') if p.is_file()}
    v1=c.save_curation(tmp_path/'v1.json',source,exclude=[f'e{i}' for i in range(20)])
    assert v1.kind=='curated' and len(v1.episodes)==80 and len(n.load_catalog(source.root).episodes)==100
    code='from robot_learning_workbench.data.native import load_catalog;import sys,json;d=load_catalog(sys.argv[1]);print(json.dumps([e.episode_id for e in d.episodes]))'
    result=subprocess.run([sys.executable,'-B','-c',code,str(tmp_path/'v1.json')],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==[f'e{i}' for i in range(20,100)]
    loaded=n.load_catalog(tmp_path/'v1.json');v2=c.save_curation(tmp_path/'v2.json',loaded,exclude=[f'e{i}' for i in range(20,30)])
    assert [e.episode_id for e in v2.episodes]==[f'e{i}' for i in range(30,100)]
    assert before=={p:n.file_sha256(p) for p in source.root.rglob('*') if p.is_file()}
    from robot_learning_workbench.data.lerobot import materialize
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    for view,count in [(v1,80),(v2,70)]:
        out=materialize(view,tmp_path/('training-'+str(count)))
        ds=LeRobotDataset('workbench/native',root=out,video_backend='pyav')
        assert ds.num_episodes==count and len(ds)==count*5
        assert set(ds.hf_dataset.unique('source.episode_id'))=={e.episode_id for e in view.episodes}
    assert not list(tmp_path.glob('v*/*.hdf5')) and (tmp_path/'v2.json').stat().st_size<30000


def test_order_ranges_splits_and_invalid_expansion(hundred,tmp_path):
    selected=[hundred.episodes[4].episode_id,hundred.episodes[2].episode_id]
    v=c.save_curation(tmp_path/'v1.json',hundred,order=selected,frame_ranges={selected[0]:(1,4)},splits={'train':[selected[0]],'val':[selected[1]]})
    assert [(e.episode_id,e.start,e.stop) for e in v.episodes]==[(selected[0],1,4),(selected[1],0,5)]
    assert [e.episode_id for e in c.select_split(v,'train')]==[selected[0]]
    with pytest.raises(n.DataError):c.save_curation(tmp_path/'bad.json',v,order=['e99'])
    with pytest.raises(n.DataError):c.save_curation(tmp_path/'bad2.json',v,frame_ranges={selected[0]:(0,5)})
    with pytest.raises(n.DataError):c.save_curation(tmp_path/'bad3.json',v,splits={'train':selected,'val':[selected[0]]})


def test_missing_moved_source_is_explicit_and_relocation_checks_identity(hundred,tmp_path):
    view=c.save_curation(tmp_path/'view.json',hundred,order=['e1'])
    moved=tmp_path/'moved';hundred.root.rename(moved)
    with pytest.raises(n.DataError):n.load_catalog(view.root)
    resolved=c.load_curation(view.root,relocations={str(hundred.root):str(moved)})
    assert [e.episode_id for e in resolved.episodes]==['e1']
    (moved/'run.json').write_text('{}')
    with pytest.raises(n.DataError):c.load_curation(view.root,relocations={str(hundred.root):str(moved)})
