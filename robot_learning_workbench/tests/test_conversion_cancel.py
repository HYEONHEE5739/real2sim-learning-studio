"""Cooperative R03 cancellation through the real official Dataset writer."""
import json
from pathlib import Path
import pytest
import yaml
from test_lerobot_dataset import source
from robot_learning_workbench.data import native as n,lerobot as l
from robot_learning_workbench.recipe import read_recipe,prepare_recipe


@pytest.mark.parametrize('stage',['convert','merge'])
def test_cancel_after_first_episode_closes_writer_and_preserves_staging(tmp_path,monkeypatch,stage):
    from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata,LeRobotDataset
    roots=[source(tmp_path,'one').root]
    if stage=='merge':roots.append(source(tmp_path,'two','isaac').root)
    before={p:n.file_sha256(p)for root in roots for p in root.rglob('*')if p.is_file()}
    output=tmp_path/'out';path=tmp_path/'job.yaml'
    path.write_text(yaml.safe_dump(dict(schema_version=1,stage=stage,
        inputs={'datasets':[str(p)for p in roots]}if stage=='merge'else{'dataset':str(roots[0])},
        execution={'task_instruction':'pick cube'},output={'directory':str(output)})))
    plan=prepare_recipe(read_recipe(path));saved=[];closed=[];events=[]
    save=LeRobotDatasetMetadata.save_episode;finalize=LeRobotDataset.finalize
    def track_save(self,*args,**kwargs):
        result=save(self,*args,**kwargs);saved.append(self.root);return result
    def track_close(self,*args,**kwargs):
        result=finalize(self,*args,**kwargs);closed.append(self.root);return result
    monkeypatch.setattr(LeRobotDatasetMetadata,'save_episode',track_save)
    monkeypatch.setattr(LeRobotDataset,'finalize',track_close)
    def commands():
        return ({'command_id':'stop','kind':'cancel'},)if saved else ()
    result=l.run(plan,events=events.append,commands=commands)
    assert result.status=='cancelled'and not result.output_refs
    assert len(saved)==1 and output.with_name('out.staging')in closed
    assert not output.exists()and output.with_name('out.staging').is_dir()
    assert [r['payload']['status']for r in events if r['kind']=='command_ack']==['completed']
    import pyarrow.parquet as pq
    for p in output.with_name('out.staging').rglob('*.parquet'):pq.read_metadata(p)
    assert before=={p:n.file_sha256(p)for root in roots for p in root.rglob('*')if p.is_file()}
    with pytest.raises(n.DataError,match='unfinished'):l.materialize(roots[0],output,task='pick cube')


def test_cancel_is_polled_during_video_decode(tmp_path,monkeypatch):
    """A single long video must not postpone Cancel until the Episode ends."""
    import av
    import numpy as np
    path=tmp_path/'small.mp4'
    with av.open(str(path),'w')as output:
        stream=output.add_stream('libx264',rate=30);stream.width=32;stream.height=32;stream.pix_fmt='yuv420p'
        for _ in range(16):
            for packet in stream.encode(av.VideoFrame.from_ndarray(np.zeros((32,32,3),np.uint8),format='rgb24')):output.mux(packet)
        for packet in stream.encode():output.mux(packet)
    count=0
    def checkpoint():
        nonlocal count
        count+=1
        if count==3:raise InterruptedError('Synthetic cancellation')
    with pytest.raises(InterruptedError,match='Synthetic cancellation'):
        l._video_window({'path':path,'fps':30,'shape':[32,32,3]},0,16,checkpoint=checkpoint)
    assert count==3


def test_normal_convert_still_completes_and_failure_is_not_cancelled(tmp_path,monkeypatch):
    root=source(tmp_path).root;path=tmp_path/'job.yaml'
    path.write_text(yaml.safe_dump(dict(schema_version=1,stage='convert',inputs={'dataset':str(root)},
        execution={'task_instruction':'pick cube'},output={'directory':str(tmp_path/'out')})))
    plan=prepare_recipe(read_recipe(path));result=l.run(plan,events=lambda _:None,commands=lambda:())
    assert result.status=='completed'and len(n.load_catalog(tmp_path/'out').episodes)==2
    def failed(*args,**kwargs):raise OSError('disk full')
    monkeypatch.setattr(l,'materialize',failed)
    with pytest.raises(OSError,match='disk full'):l.run(plan,events=lambda _:None,commands=lambda:())
