import numpy as np
import pytest
from test_robot_lifecycle import make
from robot_learning_workbench.robot import teleoperation
from robot_learning_workbench.robot.devices import DeviceError


def test_fake_full_axis_loop_records_requested_applied_and_measured_separately(tmp_path):
    leader,_,lt=make(tmp_path,'leader');follower,_,ft=make(tmp_path,'follower')
    bounds={n:e['limits']for n,e in follower.profile['joints'].items()}
    rows,cancelled=teleoperation.collect(leader,follower,model_bounds=bounds,frames=3,commands=lambda:())
    assert not cancelled
    assert len(rows)==3 and all(len(row['applied_model_rad'])==6 for row in rows)
    assert ft.count('send')==3 and all(row['hardware_verified'] is False for row in rows)
    assert all(row['pre_measured_model_rad'] is not row['applied_model_rad']for row in rows)
    assert lt[-1]=='port_close'and ft[-1]=='port_close'


def test_real_full_axis_loop_is_blocked_before_connection(tmp_path):
    leader,_,lt=make(tmp_path,'leader');follower,_,ft=make(tmp_path,'follower');follower.read_only=True
    with pytest.raises(DeviceError,match='ARM_MOTION_NOT_APPROVED'):teleoperation.collect(leader,follower,model_bounds={},frames=1,commands=lambda:())
    assert lt==[]and ft==[]


def test_native_fake_teleoperation_roundtrip_never_constructs_serial_port(tmp_path,monkeypatch):
    import json,yaml
    from pathlib import Path
    from test_precision_calibration import INV
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.data.native import load_catalog,read_array
    from lerobot.motors.feetech.feetech import FeetechMotorsBus
    monkeypatch.setattr(FeetechMotorsBus,'__init__',lambda *a,**kw:pytest.fail('Fake must not construct a serial bus'))
    root=Path(__file__).resolve().parents[2];e=root/'docs/evidence/hardware-read-gripper'
    p=tmp_path/'teleop.yaml';p.write_text(yaml.safe_dump(dict(schema_version=1,stage='teleoperation',inputs={'device_profile':str(e/'follower-device.json'),'calibration_profile':INV['roles']['follower']['profile_path'],'leader_device_profile':str(e/'leader-device.json'),'leader_calibration_profile':INV['roles']['leader']['profile_path']},execution={'mode':'fake_all','max_frames':3},output={'directory':str(tmp_path/'native')})))
    result=teleoperation.run(prepare_recipe(read_recipe(p)),events=lambda _:None,commands=lambda:())
    assert result.status=='completed'
    catalog=load_catalog(tmp_path/'native');assert len(catalog.episodes)==1 and catalog.execution['engine']=='fake'
    q=read_array(catalog.episodes[0],'joint_targets');assert q.shape==(3,6)


def test_cancelled_fake_recording_never_publishes_partial_episode(tmp_path,monkeypatch):
    import json,yaml
    from pathlib import Path
    from test_precision_calibration import INV
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.data.native import load_catalog,history
    root=Path(__file__).resolve().parents[2];e=root/'docs/evidence/hardware-read-gripper'
    p=tmp_path/'cancel.yaml';p.write_text(yaml.safe_dump(dict(schema_version=1,stage='teleoperation',inputs={'device_profile':str(e/'follower-device.json'),'calibration_profile':INV['roles']['follower']['profile_path'],'leader_device_profile':str(e/'leader-device.json'),'leader_calibration_profile':INV['roles']['leader']['profile_path']},execution={'mode':'fake_all','max_frames':3},output={'directory':str(tmp_path/'native')})))
    calls=[]
    def commands():
        calls.append(1)
        return ({'kind':'cancel','command_id':'cancel'},)if len(calls)==2 else ()
    result=teleoperation.run(prepare_recipe(read_recipe(p)),events=lambda _:None,commands=commands)
    catalog=load_catalog(tmp_path/'native')
    assert result.status=='cancelled' and len(catalog.episodes)==0
    assert history(tmp_path/'native')[0]['status']=='cancelled'


def test_full_fake_policy_loop_preserves_action_queue_reset_and_applied_readback(tmp_path):
    from types import SimpleNamespace as NS
    import torch
    f,_,trace=make(tmp_path);calls=[]
    class Policy:
        def reset(self):calls.append('reset');self.i=0
        def select_action(self,batch):
            calls.append('select');self.i+=1
            # Model-radian q at motor-neutral mapping, within the approved range.
            return torch.tensor([[sum(f.precision_mapper.command_limits({n:e['limits']for n,e in f.profile['joints'].items()})[n])/2 for n in f.profile['joints']]])
    p=Policy();bounds={n:e['limits']for n,e in f.profile['joints'].items()}
    rgb={n:np.zeros((480,640,3),np.uint8)for n in ('side','wrist')}
    from robot_learning_workbench.robot.calibration import JOINTS
    rows,cancelled=teleoperation.collect_policy(p,lambda b:b,lambda a:a,follower=f,contract={'joint_order':JOINTS},model_bounds=bounds,images=rgb,frames=3,commands=lambda:())
    assert calls==['reset','select','select','select','reset'] and not cancelled
    assert len(rows)==3 and trace.count('send')==3
    assert all(row['hardware_verified'] is False and len(row['applied_model_rad'])==6 for row in rows)
