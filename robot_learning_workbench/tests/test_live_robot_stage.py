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


@pytest.mark.parametrize('fail_second',[False,True])
def test_real_observe_policy_performs_official_path_but_never_sends(tmp_path,monkeypatch,fail_second):
    # Fake optical/device boundary; actual loop must call policy_inputs/infer/reset.
    from test_robot_lifecycle import make
    from robot_learning_workbench.learning import policy
    device,_,trace=make(tmp_path);device.read_only=True;calls=[]
    from robot_learning_workbench import recipe
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda _:None)
    monkeypatch.setattr(live,'open_inputs',lambda p:(device,{}))
    monkeypatch.setattr(policy,'policy_inputs',lambda *a:(NS(reset=lambda:calls.append('reset')),None,None,{'step':4},{'joint_order':list(JOINTS)}))
    monkeypatch.setattr(policy,'observation_batch',lambda *a,**kw:{})
    def infer(*a,**kw):
        calls.append('infer')
        if fail_second and calls.count('infer')==2:raise ValueError('Controlled second inference error')
        return np.ones((1,6))*.2
    monkeypatch.setattr(policy,'infer',infer)
    scene=NS(scene={'robot':{'model_sha256':'a'*64}})
    p=NS(stage='real_evaluation',effective_settings={'execution':{'mode':'observe_only','max_frames':2}},input_documents={},resolved_inputs={},scene=scene,output_path=tmp_path/'out')
    if fail_second:
        with pytest.raises(ValueError,match='second inference'):live.run(p,events=lambda _:None,commands=lambda:())
    else:live.run(p,events=lambda _:None,commands=lambda:())
    record=json.loads((p.output_path/'hardware-report.json').read_text())
    assert calls==['reset','infer','infer','reset']
    assert record['observations'][0]['policy_action_model_rad']==[.2]*6
    assert record['command_sent'] is False
    assert record['status']==('FAILED'if fail_second else'HARDWARE_READ_VERIFIED')
    if fail_second:assert 'second inference'in record['error']


def test_real_sim_renderer_keeps_measured_q_separate_from_position_commands(tmp_path):
    from scene_contract.package import load_scene
    from robot_learning_workbench.engines.mujoco.source import resolved_model_config
    from robot_learning_workbench.robot.live import render_comparison
    from test_policy_paths import ROOT
    import json
    scene=load_scene(ROOT/'docs/evidence/e01-v8-collision/runspace/relocated/scene-v8-native/scene.json')
    # Reuse the exercised ModelConfig rather than changing physics or assets.
    settings=json.loads((ROOT/'docs/evidence/hardware-read-gripper/real-sim-engine.json').read_text())
    p=NS(engine='mujoco',scene=scene,input_documents={'engine_config':settings})
    q=np.array(settings['initial_joint_rad']);rgb,actual=render_comparison(p,q,tmp_path)
    np.testing.assert_array_equal(actual,q)
    assert set(rgb)=={'side','wrist'} and all(x.shape==(480,640,3)for x in rgb.values())
