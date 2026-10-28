"""MuJoCo3.3.7 native integration state, world/base samples and collision rollback.

https://mujoco.readthedocs.io/en/3.3.7/APIreference/APIfunctions.html#mj-getstate
Snapshots are engine/model/version-bound. No mid-Episode workflow Resume promise.
"""
from dataclasses import asdict
import numpy as np
from scipy.spatial.transform import Rotation
from .model import JOINTS,transform


def snapshot(model,data,bindings):
    import mujoco
    spec=mujoco.mjtState.mjSTATE_INTEGRATION;values=np.empty(mujoco.mj_stateSize(model,spec),dtype=np.float64)
    mujoco.mj_getState(model,data,values,spec)
    return {'schema':'so101.mujoco-state/1','backend':'mujoco','model_sha256':bindings.model_sha256,'mujoco_version':mujoco.__version__,
        'scene_identity':asdict(bindings.scene_identity),'state_spec':int(spec),'integration_state':values.tolist()}


def _values(value,shape,field):
    result=np.asarray(value)
    if result.dtype.kind not in 'fiu' or result.shape!=shape or not np.isfinite(result).all():raise ValueError('Invalid finite state '+field)
    return result.astype(np.float64)


def restore_episode(model,data,bindings,initial):
    """Restore an opaque same-model snapshot or explicit canonical world initial state."""
    import mujoco
    if initial is not None and initial.get('backend')=='mujoco':
        expected=snapshot(model,data,bindings)
        if any(initial.get(key)!=expected[key] for key in ('schema','backend','model_sha256','mujoco_version','scene_identity','state_spec')):raise ValueError('Incompatible MuJoCo state/model/version/Scene')
        spec=mujoco.mjtState.mjSTATE_INTEGRATION;values=_values(initial['integration_state'],(mujoco.mj_stateSize(model,spec),),'integration_state')
        mujoco.mj_resetData(model,data);mujoco.mj_setState(model,data,values,spec);mujoco.mj_forward(model,data);return
    q=bindings.initial_joint_rad;qd=np.zeros(6);object_values={}
    if initial is not None:
        robot=initial['articulation']['robot'];q=_values(robot['joint_position'],(1,6),'joint_position')[0];qd=_values(robot['joint_velocity'],(1,6),'joint_velocity')[0]
        root=_values(robot['root_pose'],(1,7),'robot.root_pose')[0]
        expected=bindings.world_from_robot_base;actual=transform(np.block([[Rotation.from_quat(root[[4,5,6,3]]).as_matrix(),root[:3,None]],[np.zeros((1,3)),np.ones((1,1))]]))
        if not np.allclose(actual,expected,rtol=0,atol=1e-12):raise ValueError('Fixed robot base initial pose differs from bound Scene')
        velocity=_values(robot['root_velocity'],(1,6),'robot.root_velocity')
        if np.any(velocity):raise ValueError('Fixed robot root cannot restore nonzero velocity')
        if not set(bindings.dynamic_objects)<=set(initial['rigid_object']) or not set(initial['rigid_object'])<=set(bindings.object_body_ids):raise ValueError('Initial object identities differ')
        reference=mujoco.MjData(model);reference.qpos[list(bindings.q_indices)]=q;mujoco.mj_forward(model,reference)
        for name in initial['rigid_object']:
            obj=initial['rigid_object'][name];pose=_values(obj['root_pose'],(1,7),name+'.pose')[0];vel=_values(obj['root_velocity'],(1,6),name+'.velocity')[0]
            if not np.isclose(np.linalg.norm(pose[3:]),1.,rtol=0,atol=1e-6):raise ValueError('Invalid quaternion')
            if name not in bindings.dynamic_objects:
                index=bindings.object_body_ids[name];m=np.eye(4);m[:3,3]=pose[:3];m[:3,:3]=Rotation.from_quat(pose[[4,5,6,3]]).as_matrix()
                expected=np.eye(4);expected[:3,3]=reference.xpos[index];expected[:3,:3]=reference.xmat[index].reshape(3,3)
                if np.any(vel) or not np.allclose(m,expected,rtol=0,atol=1e-12):raise ValueError('Recorded static object differs from Scene')
            else:object_values[name]=(pose,vel)
    if np.any(q<bindings.limits[:,0]) or np.any(q>bindings.limits[:,1]):raise ValueError('Initial joint target outside model bounds')
    mujoco.mj_resetData(model,data);data.qpos[list(bindings.q_indices)]=q;data.qvel[list(bindings.v_indices)]=qd;data.ctrl[list(bindings.actuator_ids)]=q
    for name,(pose,vel) in object_values.items():
        qi,vi=bindings.object_indices[name];data.qpos[qi:qi+7]=pose;data.qvel[vi:vi+3]=vel[:3]
        data.qvel[vi+3:vi+6]=Rotation.from_quat(pose[[4,5,6,3]]).as_matrix().T@vel[3:]
    mujoco.mj_forward(model,data)


def reset_object_poses(model,data,bindings,poses):
    """Apply already placement-validated world poses; rollback any penetrating batch.

    Support/bbox sampling is T03/T04's responsibility. No retry or RNG consumption.
    """
    import mujoco
    before=snapshot(model,data,bindings);changed=set()
    try:
        for name,pose in poses:
            if name not in bindings.object_indices:raise ValueError('Only selected free objects may be reset')
            pose=transform(pose);q,v=bindings.object_indices[name];xyzw=Rotation.from_matrix(pose[:3,:3]).as_quat()
            data.qpos[q:q+7]=[*pose[:3,3],*xyzw[[3,0,1,2]]];data.qvel[v:v+6]=0;data.qacc_warmstart[:]=0;changed.add(bindings.object_body_ids[name]);mujoco.mj_forward(model,data)
        if any(c.dist< -1e-6 and (int(model.geom_bodyid[c.geom1]) in changed or int(model.geom_bodyid[c.geom2]) in changed) for c in data.contact):raise ValueError('Reset pose penetrates Collision geometry')
    except BaseException:
        restore_episode(model,data,bindings,before);raise


def finger_contacts(model,data,bindings,object_id):
    if object_id not in bindings.object_body_ids:raise ValueError('Unknown contact target')
    target=bindings.object_body_ids[object_id];result=[False,False]
    for contact in data.contact:
        bodies={int(model.geom_bodyid[contact.geom1]),int(model.geom_bodyid[contact.geom2])}
        if target in bodies and contact.dist<=0:
            for i,body in enumerate(bindings.finger_body_ids):result[i]|=body in bodies
    return result


def camera_pose(model,data,bindings,name):
    """Current world ROS optical pose (the engine camera itself uses OpenGL axes)."""
    if name not in bindings.camera_ids:raise ValueError('Unknown camera')
    index=bindings.camera_ids[name];pose=np.eye(4);pose[:3,3]=data.cam_xpos[index]
    pose[:3,:3]=data.cam_xmat[index].reshape(3,3)@np.diag([1.,-1.,-1.])
    return pose


def read_sample(model,data,bindings,phase,tick,*,episode_id='engine-check',env_index=0,object_id=None):
    """Owned model/base snapshots; caller supplies the original pre/post-step phase."""
    import mujoco
    if phase not in ('pre_step','post_step','episode_end') or type(tick) is not int or tick<0 or type(env_index) is not int or env_index<0 or not isinstance(episode_id,str) or not episode_id:raise ValueError('Invalid MuJoCo sample phase/tick/episode/env')
    inverse=np.linalg.inv(bindings.world_from_robot_base)
    def pose(position,rotation):
        result=np.eye(4);result[:3,3]=position;result[:3,:3]=np.asarray(rotation).reshape(3,3)
        return inverse@result
    eef=pose(data.site_xpos[bindings.eef_id],data.site_xmat[bindings.eef_id]);objects={};velocities={}
    for name,index in bindings.object_body_ids.items():
        objects[name]=pose(data.xpos[index],data.xmat[index]);twist=np.empty(6)
        mujoco.mj_objectVelocity(model,data,mujoco.mjtObj.mjOBJ_BODY,index,twist,0);velocities[name]=twist[3:].copy()
    sample={'episode_id':episode_id,'env_index':env_index,'tick':tick,'phase':phase,'dt_s':float(model.opt.timestep)*bindings.decimation,'pose_frame':'robot_base',
        'object_poses':objects,'eef_pose':eef,'joint_positions':data.qpos[list(bindings.q_indices)].copy(),'joint_order':tuple(JOINTS),'linear_velocities':velocities,'signals':{}}
    if object_id is not None:
        if object_id not in bindings.dynamic_objects:raise ValueError('Task contact object must be selected')
        relative=np.linalg.inv(eef)@objects[object_id];left,right=finger_contacts(model,data,bindings,object_id)
        sample['grasp_inputs']={'object_id':object_id,'relative':relative[:3,3].copy(),'relative_quat':Rotation.from_matrix(relative[:3,:3]).as_quat(),'quaternion_order':'xyzw','ee_position':eef[:3,3].copy(),'object_position':objects[object_id][:3,3].copy()}
        sample['contacts']={'left':bool(left),'right':bool(right),'source_definition':'mujoco_body_pair_dist_le_0'}
    return sample
