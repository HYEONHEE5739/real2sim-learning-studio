"""Activation must not energize an arm using a pose sampled before slow preparation."""
import pytest

from test_supervised_session import controller,approval


def test_follower_drift_during_initial_encoding_cannot_write_an_old_goal(tmp_path,monkeypatch):
    import robot_learning_workbench.robot.control as control
    c,leader,follower,_,trace,_=controller(tmp_path)
    try:
        proposal=c.propose();encode=control.encode_model_target;calls=0
        def arm_moves_during_encoding(*args,**kwargs):
            nonlocal calls
            calls+=1;result=encode(*args,**kwargs)
            if calls==2:follower.bus.present['shoulder_pan']+=100
            return result
        monkeypatch.setattr(control,'encode_model_target',arm_moves_during_encoding)
        with pytest.raises(Exception,match='[Ff]eedback|[Pp]ose|[Cc]hanged|[Mm]oved'):c.start(approval(proposal))
        assert not c.active
        assert not any(item.startswith('write_')for item in trace)
    finally:c.stop();leader.close();follower.close()


def test_follower_drift_after_goal_initialization_cannot_enable_torque(tmp_path,monkeypatch):
    c,leader,follower,_,trace,registers=controller(tmp_path)
    try:
        proposal=c.propose();write=follower.bus.sync_write
        def arm_moves_after_initial_goal(name,packet,**kwargs):
            result=write(name,packet,**kwargs)
            if name=='Goal_Position':follower.bus.present['shoulder_pan']+=100
            return result
        monkeypatch.setattr(follower.bus,'sync_write',arm_moves_after_initial_goal)
        with pytest.raises(Exception,match='[Ff]eedback|[Pp]ose|[Cc]hanged|[Mm]oved'):c.start(approval(proposal))
        assert not c.active and not any(registers['Torque_Enable'].values())
        assert trace.count('write_Goal_Position')==1 and 'write_Torque_Enable'not in trace
    finally:c.stop();leader.close();follower.close()
