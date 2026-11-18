"""Bounded original-save admission and independent frozen Pair postprocessing."""
from concurrent.futures import Future
from types import SimpleNamespace
import time
import pytest

from robot_learning_workbench.robot.snapshots import CaptureQueue


def test_raw_slots_return_before_sim_completion_without_growing_total_backlog(tmp_path,monkeypatch):
    class Writer:
        def __init__(self):self.futures=[]
        def submit(self,*args,**kwargs):
            f=Future();self.futures.append(f);return f
    class Renderer:
        def __init__(self):self.calls=[];self.priority=False
        def capture(self,pending):self.calls.append(pending['id'])
        def prioritize_capture(self,value):self.priority=value
    writer=Writer();renderer=Renderer();published=[]
    session=SimpleNamespace(closing=False,terminal=False,state='TELEOP_ACTIVE',writer=writer,renderer=renderer,
        snapshots=[],control=None,ack=lambda *args:None,emit=lambda **kw:published.append(kw),events=lambda event:None)
    queue=CaptureQueue(session,paired=True)
    def freeze(*args):
        now=time.monotonic_ns()
        return dict(capture_request={'requested_ns':now},timestamps={'follower':{'end':{'monotonic_ns':now}}},physical_q_measured=[0.]*6),{},{}
    monkeypatch.setattr('robot_learning_workbench.robot.capture.freeze_capture',freeze)
    for i in range(2):
        queue.request(dict(command_id='raw'+str(i),payload={}))
        job=queue.jobs['pair_raw'+str(i)]
        folder=tmp_path/job['id'];folder.mkdir();(folder/'COMPLETE').touch()
        from real2sim_builder.files import write
        write(folder/'capture_manifest.yaml',{'snapshots':[{'id':job['id'],'path':'.'}]})
        write(folder/'metadata.json',{'files':{}})
        writer.futures[-1].set_result(dict(id=job['id'],staging=str(folder),sample=job['sample'],observed=[],quality=[]))
        queue.poll()
    progress=queue.progress()
    assert progress['capture_queue_size']==0,'Safe originals still occupy raw-save slots'
    assert progress['postprocessing_queue_size']==2 and progress['capture_request_allowed']
    assert renderer.priority and renderer.calls==['pair_raw0']
    # Two postprocess references plus two bounded original saves, still four total.
    queue.request(dict(command_id='next0',payload={}))
    queue.request(dict(command_id='next1',payload={}))
    assert len(queue.jobs)==4
    assert queue.progress()['capture_queue_size']==2
    assert not queue.progress()['capture_request_allowed']
    with pytest.raises(ValueError,match='queue full'):
        queue.request(dict(command_id='overflow',payload={}))
    # A sealed retry goes directly back to downstream, even if both original
    # save slots are currently occupied. It must not become a third raw save.
    queue._fail(queue.jobs['pair_raw1'],RuntimeError('Synthetic downstream failure'))
    queue.retry(dict(command_id='retry',payload={'snapshot_id':'pair_raw1'}))
    assert queue.progress()['capture_queue_size']==2
    assert queue.progress()['postprocessing_queue_size']==2
    assert session.state=='TELEOP_ACTIVE'


def test_capture_priority_blocks_a_new_live_request_until_the_next_frozen_request(tmp_path,monkeypatch):
    import json
    import numpy as np
    from robot_learning_workbench.data.native import atomic_json
    from robot_learning_workbench.robot import render_worker,scene_render,pose_render
    identity={'source':'synthetic'}
    monkeypatch.setattr(scene_render,'SceneView',lambda *_:SimpleNamespace(identity=identity,render_type='native',simulation_mode='pose'))
    atomic_json(tmp_path/'config.json',dict(engine='mujoco',scene='',settings='',mapping={},identity=identity))
    atomic_json(tmp_path/'capture.json',dict(id='pair1',q=[0.]*6,requested_ns=time.monotonic_ns()))
    atomic_json(tmp_path/'latest.json',dict(id='live1',q=[.1]*6,requested_ns=time.monotonic_ns()))
    (tmp_path/'capture-priority').touch()
    calls=[]
    clock=[10.]
    monkeypatch.setattr(render_worker.time,'monotonic',lambda:clock[0])
    def sleep(seconds):
        before=clock[0];clock[0]+=seconds
        # Only the idle branch after the frame interval can post the next Pair.
        # A worker that starts Live first therefore fails deterministically.
        if before>=10.+1/30-1e-9 and len(calls)==1:
            atomic_json(tmp_path/'capture.json',dict(id='pair2',q=[.2]*6,requested_ns=time.monotonic_ns()))
    monkeypatch.setattr(render_worker.time,'sleep',sleep)
    class Renderer:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def render(self,q):
            calls.append(q)
            if len(calls)==2:(tmp_path/'stop').touch()
            return dict(images={'side':np.zeros((12,16,3),np.uint8)})
    monkeypatch.setattr(pose_render,'create_pose_renderer',lambda *_:Renderer())
    render_worker.run(tmp_path)
    assert calls==[[0.]*6,[.2]*6]
    assert json.loads((tmp_path/'capture-result.json').read_text())['id']=='pair2'
