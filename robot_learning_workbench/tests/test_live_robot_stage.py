import json
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest
from robot_learning_workbench.robot import live
from test_robot_lifecycle import make
from robot_learning_workbench.robot.calibration import JOINTS


def test_observe_runner_uses_measured_state_and_never_activates_or_sends(tmp_path,monkeypatch):
    device,_,trace=make(tmp_path);device.read_only=True
    class Camera:
        metadata={'device':'fake','requested_size':[640,480]}
        def start(self):pass
        def nearest(self,target_ns=None):
            import time
            t=time.monotonic_ns()
            return {'rgb':np.zeros((480,640,3),np.uint8),'sequence':1,'read_start':{'monotonic_ns':t-1},'read_end':{'monotonic_ns':t}}
        def close(self):pass
    from robot_learning_workbench import recipe
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda _:None)
    monkeypatch.setattr(live,'open_inputs',lambda p:(device,{'side':Camera(),'wrist':Camera()}))
    p=NS(stage='capture',effective_settings={'execution':{'mode':'observe_only','max_frames':3}},input_documents={},resolved_inputs={},scene=None,output_path=tmp_path/'out')
    out=live.run(p,events=lambda _:None,commands=lambda:())
    record=json.loads((p.output_path/'hardware-report.json').read_text())
    assert out.status=='completed' and record['frames']==3 and record['arm_commands']==0
    assert all(r['command_sent'] is False for r in record['observations'])
    assert not any(x in ('disable','configure','send','enable')for x in trace)
    assert ('disconnect',False)in trace


def test_full_real_motion_is_rejected_before_any_connection(tmp_path,monkeypatch):
    monkeypatch.setattr(live,'open_inputs',lambda _:pytest.fail('must reject before connection'))
    p=NS(effective_settings={'execution':{'mode':'full_robot','enable_motion':True}})
    with pytest.raises(ValueError,match='ARM_MOTION_NOT_APPROVED'):live.run(p,events=lambda _:None,commands=lambda:())


def test_real_observe_policy_performs_official_path_but_never_sends(tmp_path,monkeypatch):
    # Fake optical/device boundary; actual loop must call policy_inputs/infer/reset.
    from test_robot_lifecycle import make
    from robot_learning_workbench.learning import policy
    device,_,trace=make(tmp_path);device.read_only=True;calls=[]
    from robot_learning_workbench import recipe
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda _:None)
    monkeypatch.setattr(live,'open_inputs',lambda p:(device,{}))
    monkeypatch.setattr(policy,'policy_inputs',lambda *a:(NS(reset=lambda:calls.append('reset')),None,None,{'step':4},{'joint_order':list(JOINTS)}))
    monkeypatch.setattr(policy,'observation_batch',lambda *a,**kw:{})
    monkeypatch.setattr(policy,'infer',lambda *a,**kw:(calls.append('infer')or np.ones((1,6))*.2))
    scene=NS(scene={'robot':{'model_sha256':'a'*64}})
    p=NS(stage='real_evaluation',effective_settings={'execution':{'mode':'observe_only','max_frames':2}},input_documents={},resolved_inputs={},scene=scene,output_path=tmp_path/'out')
    live.run(p,events=lambda _:None,commands=lambda:())
    record=json.loads((p.output_path/'hardware-report.json').read_text())
    assert calls==['reset','infer','infer','reset']
    assert record['observations'][0]['policy_action_model_rad']==[.2]*6
    assert record['command_sent'] is False
