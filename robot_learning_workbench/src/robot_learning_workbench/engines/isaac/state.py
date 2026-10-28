"""Native Isaac state snapshots, preflight validation and explicit asset restoration.

https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.assets.html
State writes/forward/update retain B01 native replay order; no IK or Task update.
"""
import numpy as np


def validate_initial(initial,count,object_names):
    """Validate everything before simulation writes; return owned original-dtype arrays."""
    if set(initial)!={'articulation','rigid_object'} or set(initial['articulation'])!={'robot'} or set(initial['rigid_object'])!=set(object_names):raise ValueError('Complete robot and exact object state required')
    result={'articulation':{},'rigid_object':{}}
    for category,nodes in initial.items():
        for name,fields in nodes.items():
            expected={'root_pose':7,'root_velocity':6}
            if category=='articulation':expected.update(joint_position=6,joint_velocity=6)
            if set(fields)!=set(expected):raise ValueError('State field contract mismatch: '+name)
            result[category][name]={}
            for field,width in expected.items():
                value=np.asarray(fields[field])
                if value.shape!=(count,width) or value.dtype.kind not in 'fiu' or not np.isfinite(value).all():raise ValueError('Invalid state '+name+'.'+field)
                if field=='root_pose' and not np.allclose(np.linalg.norm(value[:,3:7],axis=1),1,atol=1e-5):raise ValueError('Expected unit wxyz quaternion')
                result[category][name][field]=value.copy()
    return result


def initial_state(env,env_index=0,*,relative=False):
    """World root pose/velocity and ordered model rad/rad_s, matching B02 layout."""
    robot=env.scene['robot'];ids=[robot.joint_names.index(n) for n in env.cfg.workbench_joint_order]
    def cpu(value):return value.detach().cpu().numpy().copy()
    root=cpu(robot.data.root_state_w[env_index])
    result={'articulation':{'robot':{'root_pose':root[:7][None],'root_velocity':root[7:13][None],
        'joint_position':cpu(robot.data.joint_pos[env_index,ids])[None],'joint_velocity':cpu(robot.data.joint_vel[env_index,ids])[None]}},
        'rigid_object':{name:{'root_pose':cpu(obj.data.root_state_w[env_index,:7])[None],
            'root_velocity':cpu(obj.data.root_state_w[env_index,7:13])[None]} for name,obj in env.scene.rigid_objects.items()}}
    if relative:
        origin=cpu(env.scene.env_origins[env_index])
        for nodes in result.values():
            for fields in nodes.values():fields['root_pose'][:,:3]-=origin
    return result


def restore_episode(env,env_ids,initial,*,is_relative=False):
    """Restore episode boundary, never an unsupported mid-step PhysX checkpoint."""
    import torch
    ids=torch.as_tensor(env_ids,dtype=torch.long,device=env.device)
    if ids.ndim!=1 or not len(ids) or len(torch.unique(ids))!=len(ids) or torch.any(ids<0) or torch.any(ids>=env.num_envs):raise ValueError('Invalid environment IDs')
    values=validate_initial(initial,len(ids),tuple(env.scene.rigid_objects))
    validate_fixed_base(env,ids.detach().cpu().numpy(),values['articulation']['robot'],is_relative=is_relative)
    robot=env.scene['robot'];joints=[robot.joint_names.index(n) for n in env.cfg.workbench_joint_order]
    # Bounds/shape validation completes before reset or any command is applied.
    q=torch.as_tensor(values['articulation']['robot']['joint_position'],dtype=torch.float32,device=env.device)
    limits=robot.data.soft_joint_pos_limits[ids][:,joints]
    if torch.any(q<limits[:,:,0]) or torch.any(q>limits[:,:,1]):raise ValueError('Initial state outside model joint limits')
    env.reset(env_ids=ids)
    for category,nodes in values.items():
        for name,state in nodes.items():
            obj=env.scene[name];pose=torch.as_tensor(state['root_pose'],dtype=torch.float32,device=env.device).clone()
            # World snapshots are absolute; recorded single-origin episodes may
            # explicitly request replication relative to each environment origin.
            if is_relative:pose[:,:3]+=env.scene.env_origins[ids]
            # v8 resets the fixed robot root from authored Scene state. Reapplying
            # its observed PhysX link pose feeds measured round-trip drift back
            # into the fixed joint; restore joints, not a new base-pose command.
            if category!='articulation':
                obj.write_root_pose_to_sim(pose,env_ids=ids)
                obj.write_root_velocity_to_sim(torch.as_tensor(state['root_velocity'],dtype=torch.float32,device=env.device),env_ids=ids)
            if category=='articulation':
                velocity=torch.as_tensor(state['joint_velocity'],dtype=torch.float32,device=env.device)
                obj.write_joint_state_to_sim(q,velocity,joint_ids=joints,env_ids=ids);obj.set_joint_position_target(q,joint_ids=joints,env_ids=ids)
    env.scene.write_data_to_sim();env.sim.forward();env.scene.update(env.physics_dt)
    env.obs_buf=env.observation_manager.compute()


def _matrix(pose):
    from scipy.spatial.transform import Rotation
    value=np.asarray(pose);result=np.eye(4);result[:3,3]=value[:3];result[:3,:3]=Rotation.from_quat(value[[4,5,6,3]]).as_matrix();return result


def read_sample(env,env_index,phase,tick,*,episode_id='episode',object_id=None):
    """Owned current PhysX/Camera/ContactSensor snapshot, no tracker updates."""
    if phase not in ('pre_step','post_step','episode_end') or type(tick) is not int or tick<0 or env_index<0 or env_index>=env.num_envs:raise ValueError('Invalid sample phase/tick/env')
    from scipy.spatial.transform import Rotation
    robot=env.scene['robot'];index=env_index;joints=[robot.joint_names.index(n) for n in env.cfg.workbench_joint_order]
    def cpu(value):return value.detach().cpu().numpy().copy()
    base=_matrix(cpu(robot.data.root_pose_w[index]));inverse=np.linalg.inv(base)
    tool=robot.body_names.index('tool0');eef=inverse@_matrix(cpu(robot.data.body_link_pose_w[index,tool]))
    poses={n:inverse@_matrix(cpu(o.data.root_pose_w[index])) for n,o in env.scene.rigid_objects.items()}
    pick=object_id or env.cfg.workbench_active_objects[0]
    if pick not in env.cfg.workbench_active_objects:raise ValueError('Selected contact object is not active')
    filter_index=env.cfg.workbench_active_objects.index(pick)
    forces=[cpu(env.scene[name].data.force_matrix_w[index,0,filter_index]) for name in ('grasp_fixed_contact','grasp_moving_contact')]
    contact=[bool(np.linalg.norm(force)>1e-4) for force in forces]
    relative=np.linalg.inv(eef)@poses[pick]
    return {'episode_id':episode_id,'env_index':index,'tick':tick,'phase':phase,'dt_s':env.step_dt,'pose_frame':'robot_base',
        'joint_order':tuple(env.cfg.workbench_joint_order),'joint_positions':cpu(robot.data.joint_pos[index,joints]),'joint_velocities':cpu(robot.data.joint_vel[index,joints]),
        'object_poses':poses,'eef_pose':eef,'linear_velocities':{n:cpu(o.data.root_lin_vel_w[index]) for n,o in env.scene.rigid_objects.items()},
        'contacts':{'left':contact[0],'right':contact[1],'source_definition':'isaac_contact_sensor_gt_1e_4_n','force_w':np.asarray(forces)},
        'grasp_inputs':{'object_id':pick,'relative':relative[:3,3].copy(),'relative_quat':Rotation.from_matrix(relative[:3,:3]).as_quat(),'quaternion_order':'xyzw','ee_position':eef[:3,3].copy(),'object_position':poses[pick][:3,3].copy()},
        'cameras':{name:{'pos_w':cpu(env.scene['camera_'+name].data.pos_w[index]),'quat_w_ros':cpu(env.scene['camera_'+name].data.quat_w_ros[index]),'K':cpu(env.scene['camera_'+name].data.intrinsic_matrices[index]),'rgb':cpu(env.scene['camera_'+name].data.output['rgb'][index,:,:,:3])} for name in ('side','wrist')},'signals':{}}


def validate_fixed_base(env,env_ids,robot,*,is_relative=False):
    """v8 native Annotation base check (atol=1e-5), before physical effects.

    Recorded fixed-root pose is telemetry; Scene owns its anchored reference.
    Original: native/annotation.py:_episode fixed-base compatibility check.
    """
    reference=np.asarray(env.cfg.workbench_inputs['profile']['robot_base']['T_world'])
    origins=env.scene.env_origins.detach().cpu().numpy()
    for ordinal,index in enumerate(env_ids):
        expected=reference.copy()
        if not is_relative:expected[:3,3]+=origins[int(index)]
        if not np.allclose(expected,_matrix(robot['root_pose'][ordinal]),atol=1e-5):raise ValueError('Initial fixed robot base differs from Scene reference')
    if np.any(robot['root_velocity']!=0):raise ValueError('Moving fixed robot root is unsupported')
