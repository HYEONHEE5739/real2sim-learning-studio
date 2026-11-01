"""Activation uses encoded Leader goals; device mode and transport checks remain."""
import pytest

from test_supervised_session import controller


def test_feedback_change_does_not_replace_encoded_leader_goal(tmp_path,monkeypatch):
    import robot_learning_workbench.robot.control as control
    c,leader,follower,_,trace,_=controller(tmp_path)
    try:
        state=c._start_state();encode=control.encode_model_target;calls=0
        def arm_moves_during_encoding(*args,**kwargs):
            nonlocal calls
            calls+=1;result=encode(*args,**kwargs)
            if calls==2:follower.bus.present['shoulder_pan']+=100
            return result
        monkeypatch.setattr(control,'encode_model_target',arm_moves_during_encoding)
        c.start(command_id='start')
        assert c.active
        assert follower.bus.goal==c.last_activation['state']['initial_target_raw']
        assert follower.bus.goal['shoulder_pan']!=follower.bus.present['shoulder_pan']
    finally:c.stop();leader.close();follower.close()


def test_mode_change_after_goal_initialization_cannot_enable_torque(tmp_path,monkeypatch):
    c,leader,follower,_,trace,registers=controller(tmp_path)
    try:
        state=c._start_state();write=follower.bus.sync_write
        def mode_changes_after_initial_goal(name,packet,**kwargs):
            result=write(name,packet,**kwargs)
            if name=='Goal_Position':registers['Operating_Mode']['shoulder_pan']=1
            return result
        monkeypatch.setattr(follower.bus,'sync_write',mode_changes_after_initial_goal)
        with pytest.raises(Exception,match='position mode'):c.start(command_id='start')
        assert not c.active and not any(registers['Torque_Enable'].values())
        assert trace.count('write_Goal_Position')==1 and 'write_Torque_Enable'not in trace
    finally:c.stop();leader.close();follower.close()
