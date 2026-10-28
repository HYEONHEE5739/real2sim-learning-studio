import numpy as np
import pytest
from types import SimpleNamespace
from robot_learning_workbench.robot import control
from robot_learning_workbench.engines.mujoco import source


def test_source_saturates_gripper_without_changing_requested():
    b=SimpleNamespace(limits=np.tile([-4.,4.],(6,1)))
    raw=np.array([0.,0.,0.,0.,0.,-1.]);target=source.source_target(raw,b)
    assert target[5]==0. and raw[5]==-1.


def test_native_dtype_uses_inward_saturation_for_rounding_overshoot():
    upper=1.7453264625997165;limits=np.tile([-3.,3.],(6,1));limits[3,1]=upper
    target=np.zeros(6);target[3]=upper
    np.testing.assert_array_equal(control.checked_target(target,limits=limits,applied_dtype=np.float64),target)
    assert control.checked_target(target,limits=limits,applied_dtype=np.float32)[3]==1.7453263998031616

@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf')])
def test_bad_target_never_becomes_a_valid_command(value):
    target=np.zeros(6);target[0]=value
    with pytest.raises(control.TargetRejected):control.checked_target(target,limits=np.tile([-3.,3.],(6,1)),applied_dtype=np.float64)


def test_normal_source_target_is_byte_preserved():
    b=SimpleNamespace(limits=np.tile([-3.,3.],(6,1)));target=np.array([.1,-.2,.3,-.4,.5,.6])
    np.testing.assert_array_equal(source.source_target(target,b),target)


def test_isaac_preflight_saturates_inside_original_limits():
    from robot_learning_workbench.engines.isaac.mdp import validate_targets
    limits=np.tile([-3.,3.],(1,6,1));limits[0,3,1]=1.7453264625997165
    q=np.zeros((1,6));q[0,3]=limits[0,3,1]
    assert validate_targets(q,limits)[0,3]==1.7453263998031616
