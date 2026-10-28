"""Direct model-radian servos and MuJoCo stepping; no IK or robot devices.

https://mujoco.readthedocs.io/en/3.3.7/APIreference/APIfunctions.html#mj-step
"""
from collections.abc import Mapping
import numpy as np
from .model import JOINTS


def command_target(target,bindings):
    if isinstance(target,Mapping):
        if set(target)!=set(JOINTS):raise ValueError('Exact six SO101 joint names required')
        target=[target[name] for name in JOINTS]
    from ...robot.control import checked_target
    return checked_target(target,limits=bindings.limits,applied_dtype=np.float64)


def step(model,data,bindings,target):
    """One control interval, original ten substeps and post-integration forward."""
    import mujoco
    q=command_target(target,bindings);before=float(data.time);warnings=np.array([w.number for w in data.warning])
    data.ctrl[list(bindings.actuator_ids)]=q
    for _ in range(bindings.decimation):mujoco.mj_step(model,data)
    mujoco.mj_forward(model,data)
    if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all() or data.time<=before or np.any(np.array([w.number for w in data.warning])>warnings):raise RuntimeError('Nonfinite/unstable MuJoCo step after command application; state/effect unknown')
    return data.time
