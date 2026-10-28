"""Official Isaac MDP callbacks; model radians and native reset semantics.

https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.mdp.html
"""

def ee_state(env):
    import torch
    sensor=env.scene['ee_frame']
    return torch.cat([sensor.data.target_pos_source[:,0],sensor.data.target_quat_source[:,0]],dim=-1)


def reset_scene(env,env_ids):
    from isaaclab.envs.mdp import reset_scene_to_default
    reset_scene_to_default(env,env_ids,reset_joint_targets=True)


def validate_targets(targets,limits):
    """Validate against the bound URDF radian model, before USD degree rounding."""
    import numpy as np
    value=np.asarray(targets);bounds=np.asarray(limits)
    if value.ndim!=2 or value.shape[1]!=6 or value.dtype.kind not in 'fiu' or not np.isfinite(value).all():raise ValueError('Expected finite [num_envs,6] joint targets')
    if bounds.shape!=(len(value),6,2) or not np.isfinite(bounds).all() or np.any(bounds[:,:,0]>bounds[:,:,1]):raise ValueError('Invalid model radian limits')
    from ...robot.control import checked_target,TargetRejected
    payloads=[]
    for index,(q,b) in enumerate(zip(value,bounds)):
        try:payloads.append(checked_target(q,limits=b,applied_dtype=np.float32))
        except TargetRejected as error:
            error.diagnostics['batch_index']=index
            raise
    return np.stack(payloads)


def apply_joint_targets(env,targets):
    """Validate six finite model-radian targets before official env.step."""
    import torch
    import numpy as np
    raw=targets.detach().cpu().numpy() if isinstance(targets,torch.Tensor) else targets
    bounds=np.broadcast_to(env.cfg.workbench_joint_limits_rad,(env.num_envs,6,2))
    validated=validate_targets(raw,bounds)
    if len(validated)!=env.num_envs:raise ValueError('Expected one target per environment')
    value=torch.as_tensor(validated,dtype=torch.float32,device=env.device)
    result=env.step(value)
    validate_post_state(env)
    return result


def validate_post_state(env):
    """Reject nonfinite live state after application; never claim not_applied."""
    import torch
    for asset in (*env.scene.articulations.values(),*env.scene.rigid_objects.values()):
        values=[asset.data.root_state_w]
        if hasattr(asset.data,'joint_pos'):values.extend((asset.data.joint_pos,asset.data.joint_vel))
        if any(not torch.isfinite(value).all() for value in values):raise RuntimeError('Nonfinite Isaac physics state after command; effect unknown')


def advance_streams(env,streams,ready,*,pause_check=None):
    """Advance concrete per-env generators around one official vector physics step.

    A yielded target owns its recorded pre-step row. Keep it pending while another
    env finishes/publishes/resets, then apply all active rows in one env.step.
    Inactive envs retain their existing actuator targets and have no recorded row.
    """
    import numpy as np
    finished={}
    for index,stream in tuple(streams.items()):
        if index in ready:continue
        try:
            target=next(stream)
            if target is not None:ready[index]=target
        except StopIteration as done:finished[index]=done.value
        except Exception as error:finished[index]=error
    if finished:return finished,False
    if not ready or (pause_check is not None and pause_check()):
        import time
        time.sleep(.005)
        return {},False
    robot=env.scene['robot'];ids=[robot.joint_names.index(n) for n in env.cfg.workbench_joint_order]
    targets=robot.data.joint_pos_target[:,ids].detach().cpu().numpy().copy()
    for index,target in ready.items():targets[index]=target
    apply_joint_targets(env,targets);ready.clear()
    return {},True


def complete_episode(env,steps):
    """Single-env execution of the same concrete pre/physics/post iterator."""
    try:
        while True:
            try:target=next(steps)
            except StopIteration as done:return done.value
            if target is None:
                import time
                time.sleep(.01);continue
            apply_joint_targets(env,target[None])
    finally:steps.close()
