"""v8 single-arm Mimic plans and fixed DLS eligibility; no physics loop or storage format.

Reference math: https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab_mimic/isaaclab_mimic.datagen.html
"""
from contextlib import contextmanager
import threading
import numpy as np
import torch

_RNG_LOCK=threading.RLock()


def attempt_seed(seed,index):
    """v8 scheduler attempt identity, independent of success count/worker order."""
    if type(seed) is not int or seed<0 or type(index) is not int or index<0:
        raise ValueError('Nonnegative integer base seed and attempt required')
    return int(np.random.SeedSequence([seed,index]).generate_state(1)[0])


class RandomStream:
    """Original NumPy/Torch CPU stream isolation, including nested/error paths."""
    def __init__(self,seed):
        if type(seed) is not int or not 0<=seed<2**32:raise ValueError('uint32 seed required')
        self.numpy=np.random.RandomState(seed).get_state()
        self.torch=torch.Generator().manual_seed(seed).get_state();self.depth=0

    @contextmanager
    def active(self):
        with _RNG_LOCK:
            if self.depth:
                self.depth+=1
                try:yield
                finally:self.depth-=1
                return
            previous_np=np.random.get_state();previous_torch=torch.random.get_rng_state()
            np.random.set_state(self.numpy);torch.random.set_rng_state(self.torch);self.depth=1
            try:yield
            finally:
                self.numpy=np.random.get_state();self.torch=torch.random.get_rng_state();self.depth=0
                np.random.set_state(previous_np);torch.random.set_rng_state(previous_torch)

from dataclasses import dataclass
from types import SimpleNamespace
from .reference.datagen_info_pool import DataGenInfoPool


@dataclass(frozen=True)
class Subtask:
    """Single-arm declaration data only; no alternate execution/config framework."""
    object_ref: str | None
    subtask_term_signal: str | None
    subtask_term_offset_range: tuple[int,int]=(0,0)
    selection_strategy: str='nearest_neighbor_object'
    nn_k: int=3
    num_interpolation_steps: int=5
    num_fixed_steps: int=0
    action_noise: float=0.
    first_subtask_start_offset_range: tuple[int,int]=(0,0)
    subtask_start_offset_range: tuple[int,int]=(0,0)
    apply_noise_during_interpolation: bool=False

    @property
    def selection_strategy_kwargs(self):
        return {} if self.selection_strategy=='random' else {'nn_k':self.nn_k}


def subtask_configuration(subtasks,seed=1):
    """Validate supported v8 single-arm calculation declarations, without imports."""
    tasks=tuple(subtasks)
    if not tasks or any(not isinstance(s,Subtask) for s in tasks):raise ValueError('Explicit Subtask declarations required')
    if type(seed) is not int or not 0<=seed<2**32:raise ValueError('uint32 seed required')
    if tasks[-1].subtask_term_signal is not None or tasks[-1].subtask_term_offset_range!=(0,0):raise ValueError('Final subtask has no termination signal/offset')
    for i,s in enumerate(tasks):
        if s.selection_strategy not in ('random','nearest_neighbor_object','nearest_neighbor_robot_distance'):raise ValueError('Unsupported source selection')
        if s.object_ref is None and s.selection_strategy!='random':raise ValueError('Object-independent subtask requires random selection')
        if s.object_ref is not None and (not isinstance(s.object_ref,str) or not s.object_ref):raise ValueError('Object ID required')
        if i<len(tasks)-1 and (not isinstance(s.subtask_term_signal,str) or not s.subtask_term_signal):raise ValueError('Nonfinal termination signal required')
        if not isinstance(s.subtask_term_offset_range,tuple) or len(s.subtask_term_offset_range)!=2 or any(type(v) is not int for v in s.subtask_term_offset_range) or s.subtask_term_offset_range[0]>s.subtask_term_offset_range[1]:raise ValueError('Ordered integer offset range required')
        if s.first_subtask_start_offset_range!=(0,0) or s.subtask_start_offset_range!=(0,0):raise ValueError('v8 planning uses sequential start boundaries; SkillGen/start-offset options unsupported')
        if any(type(v) is not int or v<0 for v in (s.num_interpolation_steps,s.num_fixed_steps)) or type(s.nn_k) is not int or s.nn_k<1:raise ValueError('Invalid interpolation/fixed/nn_k')
        if not np.isfinite(s.action_noise) or s.action_noise!=0. or s.apply_noise_during_interpolation is not False:raise ValueError('v8 production planning has zero action noise')
    return SimpleNamespace(subtask_configs={'tool0':tasks},datagen_config=SimpleNamespace(seed=seed,use_skillgen=False,generation_select_src_per_subtask=False,generation_select_src_per_arm=False,generation_transform_first_robot_pose=False,generation_interpolate_from_last_target_pose=True))


def configuration(pick,place,seed=1):
    return subtask_configuration((Subtask(pick,'grasp',(0,10)),Subtask(place,None)),seed)


def _planning_tensor(value,shape,field,*,dtype=torch.float32):
    try:tensor=torch.as_tensor(value)
    except (TypeError,ValueError,RuntimeError) as error:raise ValueError('Invalid '+field) from error
    if tensor.shape!=shape or tensor.is_complex() or tensor.dtype==torch.bool or not torch.isfinite(tensor).all():raise ValueError('Invalid '+field)
    return tensor.detach().to(dtype=dtype).clone()


def source_pool(episodes,cfg,*,device='cpu'):
    """Ingest explicit ordered (identity, official EpisodeData or data) pairs.

    No file reader/index/format is introduced. Native C supplies official records.
    Float32 planning is the existing Mimic consumer projection; input storage and
    float64 telemetry are never mutated or claimed as raw measured float32.
    """
    if device!='cpu':raise ValueError('Portable v8 planning stream is CPU; GPU RNG equivalence not established')
    # This is the official Pool's gripper-feature callback, not an execution env.
    features=SimpleNamespace(actions_to_gripper_actions=lambda actions:{'tool0':actions[:,-1:]})
    pool=DataGenInfoPool(features,cfg,device);names=[]
    for identity,episode in episodes:
        if not isinstance(identity,str) or not identity or identity in names:raise ValueError('Unique ordered source Episode identity required')
        values=episode if isinstance(episode,dict) else episode.data
        try:
            info=values['obs']['datagen_info'];actions=torch.as_tensor(values['actions'])
            if actions.ndim!=2 or actions.shape[0]<2 or actions.shape[1]!=7:raise ValueError('Mimic actions must be T x7; gripper is absolute model rad')
            t=actions.shape[0];projected={'actions':_planning_tensor(actions,(t,7),'actions'),'obs':{'datagen_info':{'eef_pose':{},'target_eef_pose':{},'object_pose':{},'subtask_term_signals':{}}}};target=projected['obs']['datagen_info']
            for name in ('eef_pose','target_eef_pose'):target[name]['tool0']=_planning_tensor(info[name]['tool0'],(t,4,4),name)
            for obj in dict.fromkeys(s.object_ref for s in cfg.subtask_configs['tool0'] if s.object_ref is not None):target['object_pose'][obj]=_planning_tensor(info['object_pose'][obj],(t,4,4),'object_pose.'+obj)
            for s in cfg.subtask_configs['tool0'][:-1]:
                signal=torch.as_tensor(info['subtask_term_signals'][s.subtask_term_signal])
                if signal.shape not in ((t,),(t,1)) or not torch.all((signal==0)|(signal==1)):raise ValueError('Binary per-frame subtask signal required')
                flat=signal.flatten()
                if flat[0]!=0 or torch.any(flat[1:]<flat[:-1]) or not torch.any(flat==1):raise ValueError('Sequential termination needs one 0->1 transition; no fabricated/shifted boundary')
                target['subtask_term_signals'][s.subtask_term_signal]=signal.clone()
            pool._add_episode(SimpleNamespace(data=projected))
        except (KeyError,AssertionError,IndexError) as error:raise ValueError('Invalid annotated Mimic input: '+str(error)) from error
        names.append(identity)
    if not names:raise ValueError('No annotated Source in Mimic pool')
    pool.episode_ids=tuple(names)
    return pool


def randomize_boundaries(pool,*,stream):
    """Original sequential-boundary draw order, including zero-width RNG calls."""
    result={}
    with stream.active():
        for eef,boundaries in pool.subtask_boundaries.items():
            boundaries=np.array(boundaries)
            first=np.random.randint(low=pool.env_cfg.subtask_configs[eef][0].first_subtask_start_offset_range[0],high=pool.env_cfg.subtask_configs[eef][0].first_subtask_start_offset_range[0]+1,size=boundaries.shape[0])
            boundaries[:,0,0]+=first
            for i in range(boundaries.shape[1]):
                if i>0:boundaries[:,i,0]=boundaries[:,i-1,1]
                cfg=pool.env_cfg.subtask_configs[eef][i]
                end=np.random.randint(low=cfg.subtask_term_offset_range[0],high=cfg.subtask_term_offset_range[1]+1,size=boundaries.shape[0])
                boundaries[:,i,1]+=end
            if not np.all(boundaries[:,:,1]-boundaries[:,:,0]>0) or not np.all(boundaries[:,1:,:]-boundaries[:,:-1,:]>0) or not np.all(np.diff(boundaries.reshape(boundaries.shape[0],-1),axis=-1)>=0):raise ValueError('Invalid randomized subtask boundaries')
            result[eef]=boundaries
    return result

from .reference.datagen_info import DatagenInfo
from .reference.selection_strategy import make_selection_strategy
from .reference.data_generator import transform_source_data_segment_using_object_pose
from .reference.waypoint import WaypointSequence,WaypointTrajectory

def select_source_demo(pool, eef_name: str, eef_pose: np.ndarray, object_pose: np.ndarray, src_demo_current_subtask_boundaries: np.ndarray, subtask_object_name: str, selection_strategy_name: str, selection_strategy_kwargs: dict | None=None) -> int:
    """
        Helper method to run source subtask segment selection.

        Args:
            eef_name: name of end effector
            eef_pose: current end effector pose
            object_pose: current object pose for this subtask
            src_demo_current_subtask_boundaries: start and end indices for subtask segment in source demonstrations of shape (N, 2)
            subtask_object_name: name of reference object for this subtask
            selection_strategy_name: name of selection strategy
            selection_strategy_kwargs: extra kwargs for running selection strategy

        Returns:
            selected_src_demo_ind: selected source demo index
        """
    if subtask_object_name is None:
        assert selection_strategy_name == 'random', selection_strategy_name
    src_subtask_datagen_infos = []
    for i in range(len(pool.datagen_infos)):
        src_ep_datagen_info = pool.datagen_infos[i]
        subtask_start_ind = src_demo_current_subtask_boundaries[i][0]
        subtask_end_ind = src_demo_current_subtask_boundaries[i][1]
        src_subtask_datagen_infos.append(DatagenInfo(eef_pose=src_ep_datagen_info.eef_pose[eef_name][subtask_start_ind:subtask_end_ind], object_poses={subtask_object_name: src_ep_datagen_info.object_poses[subtask_object_name][subtask_start_ind:subtask_end_ind]} if subtask_object_name is not None else None, subtask_term_signals=None, target_eef_pose=src_ep_datagen_info.target_eef_pose[eef_name][subtask_start_ind:subtask_end_ind], gripper_action=src_ep_datagen_info.gripper_action[eef_name][subtask_start_ind:subtask_end_ind]))
    selection_strategy_obj = make_selection_strategy(selection_strategy_name)
    if selection_strategy_kwargs is None:
        selection_strategy_kwargs = dict()
    selected_src_demo_ind = selection_strategy_obj.select_source_demo(eef_pose=eef_pose, object_pose=object_pose, src_subtask_datagen_infos=src_subtask_datagen_infos, **selection_strategy_kwargs)
    return selected_src_demo_ind


@dataclass(frozen=True)
class PlannedSubtask:
    source_index: int
    source_episode: str
    boundary: tuple[int,int]
    subtask_index: int
    waypoints: tuple


def plan_subtask(pool,index,boundaries,*,eef_pose,object_poses,stream,previous=None):
    """Pure single-arm v8 retarget/interpolation from supplied numerical snapshots.

    The caller supplies the actual measured snapshot at each subtask boundary.
    This function never reads an engine, chooses IK, steps, writes or succeeds an
    Episode. For later subtasks the previous selected source and last target are
    reused exactly as the v8 production configuration requires.
    """
    tasks=pool.env_cfg.subtask_configs['tool0']
    if type(index) is not int or not 0<=index<len(tasks):raise ValueError('Invalid subtask index')
    if index and (not isinstance(previous,PlannedSubtask) or previous.subtask_index!=index-1 or not previous.waypoints):raise ValueError('Previous planned subtask identity/last target required')
    if not index and previous is not None:raise ValueError('First subtask must not inherit a prior plan')
    eef_pose=_planning_tensor(eef_pose,(4,4),'eef_pose')
    cfg=tasks[index];obj=None
    if cfg.object_ref is not None:
        if cfg.object_ref not in object_poses:raise ValueError('Current reference Object pose missing')
        obj=_planning_tensor(object_poses[cfg.object_ref],(4,4),'object_pose')
    array=np.asarray(boundaries.get('tool0'))
    if array.shape!=(pool.num_datagen_infos,len(tasks),2) or not np.issubdtype(array.dtype,np.integer):raise ValueError('Pool-specific integer boundaries required')
    for i,info in enumerate(pool.datagen_infos):
        if np.any(array[i,:,0]<0) or np.any(array[i,:,1]>info.eef_pose['tool0'].shape[0]) or np.any(array[i,:,1]<=array[i,:,0]):raise ValueError('Subtask boundaries outside source frames')
    with stream.active():
        selected=previous.source_index if index else select_source_demo(pool,'tool0',eef_pose,obj,array[:,index],cfg.object_ref,cfg.selection_strategy,cfg.selection_strategy_kwargs)
        if isinstance(selected,torch.Tensor) and selected.ndim==0 and selected.dtype==torch.int64:selected=int(selected)
        if type(selected) is not int or not 0<=selected<pool.num_datagen_infos:raise ValueError('Invalid selected source')
        if index and previous.source_episode!=pool.episode_ids[selected]:raise ValueError('Source pool identity changed between subtasks')
        start,end=map(int,array[selected,index]);info=pool.datagen_infos[selected]
        poses=info.target_eef_pose['tool0'][start:end].clone();gripper=info.gripper_action['tool0'][start:end].clone()
        if index==0:
            poses=torch.cat([info.eef_pose['tool0'][start:start+1],poses],dim=0)
            gripper=torch.cat([gripper[0:1],gripper],dim=0)
        if obj is not None:poses=transform_source_data_segment_using_object_pose(obj,poses,info.object_poses[cfg.object_ref][start])
        subtask=WaypointTrajectory();subtask.add_waypoint_sequence(WaypointSequence.from_poses(poses,gripper,cfg.action_noise))
        trajectory=WaypointTrajectory()
        if index:initial=WaypointSequence(sequence=[previous.waypoints[-1]])
        else:initial=WaypointSequence.from_poses(eef_pose.unsqueeze(0),subtask[0].gripper_action.unsqueeze(0),cfg.action_noise)
        trajectory.add_waypoint_sequence(initial)
        trajectory.merge(subtask,num_steps_interp=cfg.num_interpolation_steps,num_steps_fixed=cfg.num_fixed_steps,action_noise=float(cfg.apply_noise_during_interpolation)*cfg.action_noise)
        trajectory.pop_first();points=tuple(trajectory.get_full_sequence().sequence)
    return PlannedSubtask(selected,pool.episode_ids[selected],(start,end),index,points)

# Pinocchio owns model/Data; each worker binds its own mutable numerical workspace.
# Official API: https://stack-of-tasks.github.io/pinocchio/
DLS_PARAMETERS = dict(position_weight=1., orientation_weight=.01,
                      max_iterations=200, tolerance=1e-3, damping=1e-3, step_size=.3)


def _finite(value, shape, name):
    array=np.asarray(value)
    if array.shape!=shape or array.dtype.kind not in 'fiu' or not np.isfinite(array).all():
        raise ValueError('Invalid '+name)
    return array.astype(np.float64)


def best_effort_candidate(candidate, gripper, previous_applied, limits):
    """Return eligible command or invalid reason. Never applies, clips or holds."""
    previous=_finite(previous_applied,(6,),'previous applied command')
    bounds=_finite(limits,(6,2),'joint limits')
    grip=_finite(gripper,(),'gripper target')
    if np.any(bounds[:,0]>bounds[:,1]):raise ValueError('Inverted joint limits')
    if grip<bounds[5,0]-1e-7 or grip>bounds[5,1]+1e-7:raise ValueError('Gripper target outside model limits')
    arm=np.asarray(candidate)
    if arm.shape!=(5,):return None,'candidate_shape'
    if arm.dtype.kind not in 'fiu' or not np.isfinite(arm).all():return None,'candidate_nonfinite'
    if np.any(arm<bounds[:5,0]-1e-7) or np.any(arm>bounds[:5,1]+1e-7):return None,'joint_limit_violation'
    if np.max(np.abs(arm-previous[:5]))>.5:return None,'candidate_jump'
    return np.r_[arm,grip],''


@dataclass(frozen=True)
class IKResult:
    command: np.ndarray | None
    candidate: np.ndarray
    diagnostics: dict
    identity: dict


def bind_kinematics(urdf, *, model_sha256, joint_order):
    from pathlib import Path
    from ..data.native import file_sha256
    from ..robot.calibration import JOINTS
    if tuple(joint_order)!=tuple(JOINTS):raise ValueError('Exact SO101 joint order required')
    if file_sha256(urdf)!=model_sha256:raise ValueError('IK model identity mismatch')
    kin=SO101Kinematics(str(urdf),joint_names=list(JOINTS[:5]))
    kin.model_sha256=model_sha256
    kin.limits=np.array([[kin.model.lowerPositionLimit[kin.model.joints[kin.model.getJointId(n)].idx_q],kin.model.upperPositionLimit[kin.model.joints[kin.model.getJointId(n)].idx_q]] for n in JOINTS])
    kin.identity=dict(solver='pinocchio_dls',policy='best_effort',model_sha256=model_sha256,
        code_sha256=file_sha256(Path(__file__)),frame='robot_base',target_frame='tool0',joint_order=list(JOINTS),
        parameters=dict(DLS_PARAMETERS),seed_reference='measured_joint_positions',
        safety=dict(finite=True,joint_limits=True,max_arm_command_jump_rad=.5,jump_reference='previous_applied_command_arm'))
    return kin


class IKFailure(ValueError):
    def __init__(self,diagnostics):
        self.code='IK_INVALID_CANDIDATE';self.effect='not_applied';self.diagnostics=diagnostics
        super().__init__(diagnostics['failure_reason'])


def solve_dls(kinematics,target,measured,previous_applied,gripper,*,model_sha256,joint_order,frame,units):
    """Compute fixed DLS + Best Effort eligibility; caller owns actual application."""
    from scene_contract.transforms import validate_transform
    from ..robot.calibration import JOINTS
    if model_sha256!=kinematics.model_sha256 or tuple(joint_order)!=tuple(JOINTS) or frame!='robot_base' or units!='m_rad':
        raise ValueError('IK model/frame/joint order/unit mismatch')
    goal=validate_transform(target);observed=_finite(measured,(6,),'measured model joints')
    previous=_finite(previous_applied,(6,),'previous applied command')
    # Check input gripper before any iterative work, even if the solver later fails.
    best_effort_candidate(observed[:5],gripper,previous,kinematics.limits)
    candidate,converged,native=kinematics.inverse_kinematics(observed[:5],goal,**DLS_PARAMETERS)
    command,reason=best_effort_candidate(candidate,gripper,previous,kinematics.limits)
    position=rotation=None
    candidate_array=np.asarray(candidate)
    if candidate_array.shape==(5,) and candidate_array.dtype.kind in 'fiu' and np.isfinite(candidate_array).all():
        actual=kinematics.forward_kinematics(candidate)
        position=float(np.linalg.norm(actual[:3,3]-goal[:3,3]))
        from scipy.spatial.transform import Rotation
        rotation=float(np.linalg.norm(Rotation.from_matrix(goal[:3,:3]@actual[:3,:3].T).as_rotvec()))
    diagnostics=dict(converged=bool(converged),native_result={k:float(v) if np.isfinite(v) else None for k,v in native.items()},position_error_m=position,
        rotation_error_rad=rotation,common_pose_passed=bool(position is not None and position<=.003 and rotation<=.12),
        candidate_valid=command is not None,failure_reason=reason or ('native_nonconvergence' if not converged else 'pose_tolerance_exceeded' if not (position is not None and position<=.003 and rotation<=.12) else ''),
        command_applied=False,measured_joint_rad=observed.tolist(),previous_applied_joint_rad=previous.tolist())
    if command is None:raise IKFailure(diagnostics)
    command.setflags(write=False)
    return IKResult(command,np.array(candidate,copy=True),diagnostics,dict(kinematics.identity))


class SO101Kinematics:

    def __init__(self, urdf_path: str, target_frame_name: str='tool0', joint_names: list[str] | None=None):
        import pinocchio as pin
        self.model = pin.buildModelFromUrdf(urdf_path)
        self.data = self.model.createData()
        self.target_frame_name = target_frame_name
        if joint_names is None:
            raise ValueError('joint_names must be provided.')
        self.joint_names = joint_names
        if not self.model.existFrame(target_frame_name):
            frame_names = [frame.name for frame in self.model.frames]
            raise ValueError(f"Frame '{target_frame_name}' not found in URDF.\nAvailable frames:\n{frame_names}")
        self.frame_id = self.model.getFrameId(target_frame_name)
        self.q_indices = []
        for joint_name in self.joint_names:
            joint_id = self.model.getJointId(joint_name)
            if joint_id == 0:
                raise ValueError(f"Joint '{joint_name}' not found in URDF.")
            joint_model = self.model.joints[joint_id]
            if joint_model.nq != 1 or joint_model.nv != 1:
                raise ValueError(f"Joint '{joint_name}' is not 1-DoF: nq={joint_model.nq}, nv={joint_model.nv}")
            self.q_indices.append(joint_model.idx_q)
        self.q_indices = np.asarray(self.q_indices, dtype=int)

    def _make_full_q(self, arm_joint_pos: np.ndarray) -> np.ndarray:
        import pinocchio as pin
        arm_joint_pos = np.asarray(arm_joint_pos, dtype=np.float64).reshape(-1)
        if len(arm_joint_pos) != len(self.joint_names):
            raise ValueError(f'Expected {len(self.joint_names)} arm joints, got {len(arm_joint_pos)}')
        q = pin.neutral(self.model)
        q[self.q_indices] = arm_joint_pos
        return q

    def _extract_arm_q(self, q: np.ndarray) -> np.ndarray:
        return q[self.q_indices].copy()

    def forward_kinematics(self, joint_pos_rad: np.ndarray) -> np.ndarray:
        import pinocchio as pin
        q = self._make_full_q(joint_pos_rad)
        pin.forwardKinematics(self.model, self.data, q)
        pin.updateFramePlacements(self.model, self.data)
        placement = self.data.oMf[self.frame_id]
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = placement.rotation
        T[:3, 3] = placement.translation
        return T

    def inverse_kinematics(self, current_joint_pos_rad: np.ndarray, desired_ee_pose: np.ndarray, position_weight: float=1.0, orientation_weight: float=0.0, max_iterations: int=100, tolerance: float=0.0001, damping: float=0.0001, step_size: float=0.5) -> tuple[np.ndarray, bool, dict]:
        import pinocchio as pin
        current_joint_pos_rad = np.asarray(current_joint_pos_rad, dtype=np.float64).reshape(-1)
        desired_ee_pose = np.asarray(desired_ee_pose, dtype=np.float64)
        if desired_ee_pose.shape != (4, 4):
            raise ValueError(f'desired_ee_pose must be (4,4), got {desired_ee_pose.shape}')
        q = self._make_full_q(current_joint_pos_rad)
        target = pin.SE3(desired_ee_pose[:3, :3], desired_ee_pose[:3, 3])
        weights = np.array([position_weight, position_weight, position_weight, orientation_weight, orientation_weight, orientation_weight], dtype=np.float64)
        active_rows = weights > 0.0
        if not np.any(active_rows):
            raise ValueError('At least one IK weight must be > 0.')
        success = False
        pos_error_norm = np.inf
        rot_error_norm = np.inf
        weighted_error_norm = np.inf
        for iteration in range(max_iterations):
            pin.forwardKinematics(self.model, self.data, q)
            pin.updateFramePlacements(self.model, self.data)
            current = self.data.oMf[self.frame_id]
            pos_error = target.translation - current.translation
            R_error = target.rotation @ current.rotation.T
            rot_error = pin.log3(R_error)
            error = np.concatenate([pos_error, rot_error])
            pos_error_norm = np.linalg.norm(pos_error)
            rot_error_norm = np.linalg.norm(rot_error)
            weighted_error = weights[active_rows] * error[active_rows]
            weighted_error_norm = np.linalg.norm(weighted_error)
            if weighted_error_norm < tolerance:
                success = True
                break
            J = pin.computeFrameJacobian(self.model, self.data, q, self.frame_id, pin.ReferenceFrame.LOCAL_WORLD_ALIGNED)
            v_indices = []
            for joint_name in self.joint_names:
                joint_id = self.model.getJointId(joint_name)
                v_indices.append(self.model.joints[joint_id].idx_v)
            J_arm = J[:, v_indices]
            J_task = J_arm[active_rows, :]
            e_task = error[active_rows]
            w_task = weights[active_rows]
            J_weighted = w_task[:, None] * J_task
            e_weighted = w_task * e_task
            A = J_weighted @ J_weighted.T + damping * np.eye(J_weighted.shape[0])
            dq_arm = J_weighted.T @ np.linalg.solve(A, e_weighted)
            dq_arm *= step_size
            q[self.q_indices] += dq_arm
            lower = self.model.lowerPositionLimit
            upper = self.model.upperPositionLimit
            for q_idx in self.q_indices:
                if np.isfinite(lower[q_idx]):
                    q[q_idx] = max(q[q_idx], lower[q_idx])
                if np.isfinite(upper[q_idx]):
                    q[q_idx] = min(q[q_idx], upper[q_idx])
        q_arm = self._extract_arm_q(q)
        info = {'iterations': iteration + 1, 'position_error': pos_error_norm, 'orientation_error': rot_error_norm, 'weighted_error': weighted_error_norm}
        return (q_arm, success, info)


def ik_record(result,duration_s,*,applied):
    """Existing B02 numeric IK columns; S64 failure_reason stays in Native sidecar.

    Call after engine application; solver diagnostics alone never prove application.
    """
    if type(applied) is not bool or not np.isfinite(duration_s) or duration_s<0:raise ValueError('Actual application flag and finite duration required')
    d=result.diagnostics;position=d['position_error_m']*1000;rotation=float(np.degrees(d['rotation_error_rad']))
    return dict(ik_converged=bool(d['converged']),ik_candidate_applied=applied,ik_held=False,
        ik_invalid_candidate=False,ik_invalid_command=False,ik_numerical_failure=not d['converged'] or not d['common_pose_passed'],
        ik_position_error_mm=position,ik_orientation_error_deg=rotation,ik_success=bool(d['converged']),
        ik_duration_ms=float(duration_s*1000),ik_iterations_or_evaluations=int(d['native_result']['iterations']),position_error_mm=position,
        orientation_error_deg=rotation,joint_limit_violation=False,common_pose_passed=bool(d['common_pose_passed']),command_applied=applied,
        candidate_joint_rad=np.array(result.candidate,dtype=np.float64,copy=True))
