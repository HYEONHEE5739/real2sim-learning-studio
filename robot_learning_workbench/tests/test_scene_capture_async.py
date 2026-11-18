"""Observation loop and actual spawned Writer, using camera memory inputs only."""
import os
import time
from types import SimpleNamespace
import numpy as np


def delayed_materials(args,kwargs):
    from robot_learning_workbench.robot.snapshots import save_snapshot
    time.sleep(.25)
    return save_snapshot('materials',*args,**kwargs)


def test_scene_observation_accepts_two_clicks_and_updates_preview_while_writer_saves(tmp_path,monkeypatch):
    from real2sim_builder.project import Project
    from robot_learning_workbench.robot import scene_observation,snapshots
    from robot_learning_workbench import recipe
    from robot_learning_workbench.data import video
    project=Project.create(tmp_path/'scenes','Observed camera inputs')
    output=tmp_path/'observations-run'
    plan=SimpleNamespace(output_path=output,resolved_inputs={'project':{'root':str(project.root)}})
    inner=snapshots.snapshot_writer(project=project,session_id='observations_run')
    writer_pid=inner.submit(os.getpid).result(timeout=10)
    assert writer_pid!=os.getpid()
    class Writer:
        def submit(self,fn,*args,**kwargs):
            if fn is snapshots.save_snapshot and args[0]=='materials':
                return inner.submit(delayed_materials,args[1:],kwargs)
            return inner.submit(fn,*args,**kwargs)
        def shutdown(self,**kwargs):return inner.shutdown(**kwargs)
    class Camera:
        def __init__(self):self.sequence=0;self.closed=False
        def start(self):pass
        def close(self):self.closed=True
        def statistics(self):return {'received_fps':30.}
        def nearest(self,target_ns,*,not_after):
            assert not_after
            self.sequence+=1;end=target_ns-5_000_000
            return dict(rgb=np.full((480,640,3),39,np.uint8),sequence=self.sequence,
                read_start={'monotonic_ns':end-1_000_000,'unix_ns':time.time_ns()},
                read_end={'monotonic_ns':end,'unix_ns':time.time_ns()})
    cameras={n:Camera()for n in('side','wrist')}
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda *_:None)
    monkeypatch.setattr(scene_observation,'construct',lambda *_:({},cameras))
    monkeypatch.setattr(snapshots,'snapshot_writer',lambda **_:Writer())
    events=[];preview=[];clicks=0;begin=time.monotonic()
    monkeypatch.setattr(video,'_preview_sink',lambda *args:preview.append(args[0]))
    def commands():
        nonlocal clicks
        assert time.monotonic()-begin<8,'Observation loop did not finish'
        if sum('snapshot'in e.get('payload',{}).get('progress',{})for e in events)==2:
            return [dict(kind='session_finish',command_id='finish',payload={})]
        rows=[dict(kind='session_heartbeat',command_id='heartbeat',payload={'timestamp_ns':time.monotonic_ns()})]
        if clicks<2:
            rows.append(dict(kind='session_snapshot',command_id='click_'+str(clicks),payload={'requested_ns':time.monotonic_ns()}));clicks+=1
        return rows
    try:
        result=scene_observation.run(plan,events=events.append,commands=commands)
    finally:
        inner.shutdown(wait=True)
    accepted=[e for e in events if e['kind']=='command_ack'and e['payload']['status']=='accepted']
    assert len(accepted)==2 and len(preview)>=12
    assert result.status=='completed'
    assert all(c.closed for c in cameras.values())
    assert not __import__('pathlib').Path('/proc',str(writer_pid)).exists()
    saved=[e['payload']['progress']['snapshot']for e in events if 'snapshot'in e.get('payload',{}).get('progress',{})]
    assert len(saved)==2 and all(row['q_measured']==[]and row['request']['requested_ns']<=row['request']['observed_ns']for row in saved)
    assert len(project.evidence['images'])==4 and len(project.evidence['documents'])==2
