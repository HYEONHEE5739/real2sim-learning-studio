"""Pre-step recording and recorded-input contracts shared by concrete engines."""
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from ..robot.calibration import JOINTS


def pose7(matrix):
    q=Rotation.from_matrix(matrix[:3,:3]).as_quat()
    return np.r_[matrix[:3,3],q[[3,0,1,2]]]



def record_frame(episode,sample,target_pose,target,*,time_s,requested=None,signals=None,base=None,previous_pose=None,command_requested=None,command_limits=None):
    """Record pre-step arrays in original B02 names/dtypes, never post-step state."""
    import torch
    def add(key,value):episode.add(key,torch.from_numpy(np.array(value,copy=True)))
    previous=sample['eef_pose'] if previous_pose is None else previous_pose
    action=np.r_[target_pose[:3,3]-previous[:3,3],Rotation.from_matrix(target_pose[:3,:3]@previous[:3,:3].T).as_rotvec(),target[5]]
    add('actions',action);add('joint_targets',target);add('action_timestamp',np.float64(time_s))
    if command_requested is not None:
        from ..robot.control import checked_target
        info={};payload=checked_target(command_requested,limits=command_limits,applied_dtype=np.asarray(target).dtype,diagnostics=info)
        if not np.array_equal(payload,target):raise ValueError('Recorded command must equal actual native payload')
        add('commands/requested_joint_rad',command_requested);add('commands/applied_joint_rad',target)
        add('commands/saturation_mask',np.asarray(info['saturation_mask'],dtype=np.bool_))
        add('commands/saturation_delta_rad',np.asarray(info['delta_rad'],dtype=np.float64))
    add('obs/timestamp',np.array([time_s],dtype=np.float64));add('obs/policy/joint_pos',sample['joint_positions'])
    add('obs/policy/ee_state',pose7(sample['eef_pose']))
    add('obs/datagen_info/eef_pose/tool0',sample['eef_pose'].astype(np.float32))
    add('obs/datagen_info/target_eef_pose/tool0',target_pose.astype(np.float32))
    for name,pose in sample['object_poses'].items():
        add('obs/datagen_info/object_pose/'+name,pose.astype(np.float32))
        if base is not None:add('obs/object_poses/'+name,pose7(base@pose))
    for camera in ('side','wrist'):add('obs/camera_timestamps/'+camera,np.float64(time_s))
    if requested is not None:
        add('collection/requested_action',requested)
        add('collection/state',collection_coordinates(sample['joint_positions'],measured=True))
        add('collection/action',collection_coordinates(target))
    for name,value in (signals or {}).items():
        add('obs/events/'+name,np.array([value],dtype=np.uint8))
        if name=='grasp':add('obs/datagen_info/subtask_term_signals/grasp',np.array([value],dtype=np.uint8))



def add_initial(episode,initial):
    import torch
    def tensors(value):return {k:tensors(v) if isinstance(v,dict) else torch.from_numpy(np.array(v,copy=True)) for k,v in value.items()}
    episode.data['initial_state']=tensors(initial)



def collection_coordinates(model_rad,*,measured=False):
    from ..robot.calibration import LEGACY_MAPPER
    q=np.array(model_rad,dtype=np.float64,copy=True)
    if q.shape!=(6,) or not np.isfinite(q).all():raise ValueError('Six finite model joints required')
    closed=LEGACY_MAPPER.gripper_zero_offset_rad;opened=closed+100*LEGACY_MAPPER.gripper_rad_per_percent
    q[5]=(q[5]-closed)/(opened-closed)
    tolerance=.02 if measured else 1e-6
    if q[5]<-tolerance or q[5]>1+tolerance:raise ValueError('Gripper outside declared canonical endpoints')
    q[5]=np.clip(q[5],0,1)
    return q.astype(np.float32)



def command_summary(episode):
    """Small executed-command statistics, never a copy of bulk action arrays."""
    values=episode.data.get('commands',{})
    if 'saturation_mask' not in values:return {'steps':0,'saturated_steps':0,'joint_events':0,'max_abs_delta_rad':0.}
    def array(value):return np.stack([v.cpu().numpy() for v in value]) if isinstance(value,list) else value.cpu().numpy()
    mask=array(values['saturation_mask']);delta=array(values['saturation_delta_rad'])
    from ..robot.calibration import JOINTS
    return {'steps':len(mask),'saturated_steps':int(mask.any(axis=1).sum()),'joint_events':int(mask.sum()),
            'per_joint_counts':dict(zip(JOINTS,mask.sum(axis=0).astype(int).tolist())),
            'max_abs_delta_rad':float(np.max(np.abs(delta[mask]))) if mask.any() else 0.}



def recorded_initial(episode):
    """Original Source initial tensors, never Annotation's re-saved initial."""
    def array(value):return {k:array(v) for k,v in value.items()} if isinstance(value,dict) else value.detach().cpu().numpy().copy()
    return array(episode.data['initial_state'])



def validate_recording(recording):
    required=dict(joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30,resolution=[640,480])
    if any(recording.get(k)!=v for k,v in required.items()):
        raise ValueError('Source joint order/unit/frame/phase/camera contract missing or incompatible')



def validate_source_ranges(catalog):
    if any(ep.start!=0 or ep.stop not in (None,ep.num_frames) for ep in catalog.episodes):
        raise ValueError('Annotation requires complete Source episodes and original initial state; use a numerical Source stream to collect a new episode from a trim')

