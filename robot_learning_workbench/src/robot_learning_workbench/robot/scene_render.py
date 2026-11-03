"""Native simulated joint drives and contact physics; never a real robot command."""
from pathlib import Path
from dataclasses import asdict
import copy,json,time
import numpy as np
from scene_contract.package import load_scene
from .calibration import JOINTS,mapper_from_scene
from .registration import mapping_coordinates_equal
from ..data.native import file_sha256


class SceneView:
    def __init__(self,scene,engine,settings,mapping):
        self.path=Path(scene).resolve();self.engine=engine;self.settings_path=Path(settings).resolve();self.mapping=copy.deepcopy(mapping)
        self.package=load_scene(self.path);self.scene_identity=asdict(self.package.identity)
        if engine not in self.package.scene['engines']:raise ValueError('Selected Scene does not declare this engine')
        self.settings_sha256=file_sha256(self.settings_path);self.settings=json.loads(self.settings_path.read_text());self.settings.pop('package_root',None)
        self.render_type=self.settings.pop('render_type','native')
        if self.render_type not in('native','authored'):raise ValueError('Unsupported Scene render settings')
        matches=[]
        for name,record in self.package.calibration['records'].items():
            if record['kind']!='encoder_mapping'or record['application'].get('phase')!='device_observation':continue
            parameters=json.loads((self.package.root/record['parameters_file']).read_text())if 'parameters_file'in record else record['parameters']
            profile=parameters.get('profile',parameters)
            if profile.get('role')=='follower':matches.append(name)
        if self.render_type=='native'or matches:
            if len(matches)!=1:raise ValueError('Scene requires one unambiguous Follower observation Calibration')
            expected=mapper_from_scene(self.package,matches[0],role='follower',phase='device_observation').metadata()
            if not mapping_coordinates_equal(expected,self.mapping):raise ValueError('Follower measured coordinates differ from selected Scene Calibration')
        if self.render_type=='authored':
            from .authored_render import validate_binding
            validate_binding(self)
        self.watched=[self.path,self.package.root/'manifest.json',self.settings_path,*[self.package.root/f.path for f in self.package.files]]
        self.stats=self._stats();self.identity={'scene':self.scene_identity,'settings_sha256':self.settings_sha256,'mapping_sha256':mapping['sha256'],'engine':engine}
    def _stats(self):return [(str(p),p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns)for p in self.watched]
    def verify(self):
        if self._stats()!=self.stats:
            load_scene(self.path,expected=self.package.identity)
            if file_sha256(self.settings_path)!=self.settings_sha256:raise ValueError('Engine settings changed during Real/Sim connection')
            self.stats=self._stats()


class NativeRenderer:
    state_application='native_physics_joint_target'
    def __init__(self,view,directory):
        self.view=view;self.env=None;self.renderer=None;self.model=None;self.binding=None;self.total_physics_steps=0;self.last_frame_steps=0
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        if view.engine=='mujoco':
            import mujoco
            from ..engines.mujoco.model import ModelConfig,build_model
            self.model,self.binding=build_model(view.package,ModelConfig(**view.settings));self.data=mujoco.MjData(self.model)
            from ..engines.mujoco.state import restore_episode
            restore_episode(self.model,self.data,self.binding,None)
            self.renderer=mujoco.Renderer(self.model,height=480,width=640)
        elif view.engine=='isaac':
            from isaaclab.envs import ManagerBasedEnv
            from ..engines.isaac.env_cfg import build_env_cfg
            try:self.env=ManagerBasedEnv(cfg=build_env_cfg(view.package,view.settings,runtime_directory=directory/'native'));self.env.reset()
            except BaseException:self.close();raise
        else:raise ValueError('Actual MuJoCo or Isaac Scene engine required')
    @property
    def control_dt_s(self):
        return float(self.model.opt.timestep)*self.binding.decimation if self.view.engine=='mujoco'else self.env.physics_dt*self.env.cfg.decimation

    def advance(self,q):
        """Progress a control interval even when no new preview is requested."""
        self.view.verify();raw=np.asarray(q)
        if raw.shape!=(6,)or raw.dtype.kind not in'fiu'or not np.isfinite(raw).all():raise ValueError('Six finite measured model-radian joints required')
        target,steps=self._advance(raw.astype(np.float64));self.total_physics_steps+=steps
        return target
    def _advance(self,measured):
        # Same checked targets and physics intervals as Source/DataGen.
        # https://mujoco.readthedocs.io/en/3.3.7/APIreference/APIfunctions.html#mj-step
        # https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html
        if self.view.engine=='mujoco':
            from ..engines.mujoco.control import step
            step(self.model,self.data,self.binding,measured)
            return self.data.ctrl[list(self.binding.actuator_ids)].copy(),self.binding.decimation
        from ..engines.isaac.mdp import apply_joint_targets
        apply_joint_targets(self.env,measured[None])
        robot=self.env.scene['robot'];ids=[robot.joint_names.index(n)for n in JOINTS]
        return robot.data.joint_pos_target[0,ids].detach().cpu().numpy().copy(),self.env.cfg.decimation
    def render(self,q):
        self.view.verify();begin=time.monotonic_ns();raw=np.asarray(q)
        if raw.shape!=(6,)or raw.dtype.kind not in'fiu'or not np.isfinite(raw).all():raise ValueError('Six finite measured model-radian joints required')
        measured=raw.astype(np.float64);images={};cameras={};objects={}
        target=self.advance(measured)
        if self.view.engine=='mujoco':
            from ..engines.mujoco.state import camera_pose
            from ..engines.mujoco.rendering import camera_rgb
            for name in('side','wrist'):
                images[name]=camera_rgb(self.renderer,self.data,self.binding.camera_ids[name]).copy()
                cameras[name]={'resolution':[640,480],'K':self.view.package.scene['cameras'][name]['K'],'T_world_optical':camera_pose(self.model,self.data,self.binding,name).tolist()}
            applied=self.data.qpos[list(self.binding.q_indices)].copy()
            for name,row in self.view.package.scene['objects'].items():
                if row['role']not in('task_object','receptacle')or name not in self.binding.object_body_ids:continue
                index=self.binding.object_body_ids[name];matrix=np.eye(4)
                matrix[:3,:3]=self.data.xmat[index].reshape(3,3);matrix[:3,3]=self.data.xpos[index]
                objects[name]=matrix.tolist()
            simulation_time=float(self.data.time)
        else:
            from scipy.spatial.transform import Rotation
            env=self.env;robot=env.scene['robot'];ids=[robot.joint_names.index(n)for n in JOINTS]
            for _ in range(3):env.sim.render()
            for name in('side','wrist'):
                sensor=env.scene['camera_'+name];sensor.update(env.physics_dt,force_recompute=True)
                images[name]=sensor.data.output['rgb'][0,:,:,:3].detach().cpu().numpy().copy()
                quaternion=sensor.data.quat_w_ros[0].detach().cpu().numpy();transform=np.eye(4);transform[:3,:3]=Rotation.from_quat(quaternion[[1,2,3,0]]).as_matrix();transform[:3,3]=sensor.data.pos_w[0].detach().cpu().numpy()
                cameras[name]={'resolution':[640,480],'K':sensor.data.intrinsic_matrices[0].detach().cpu().numpy().tolist(),'T_world_optical':transform.tolist()}
            applied=robot.data.joint_pos[0,ids].detach().cpu().numpy().copy()
            for name,asset in env.scene.rigid_objects.items():
                matrix=np.eye(4);quaternion=asset.data.root_quat_w[0].detach().cpu().numpy()
                matrix[:3,:3]=Rotation.from_quat(quaternion[[1,2,3,0]]).as_matrix();matrix[:3,3]=asset.data.root_pos_w[0].detach().cpu().numpy()
                objects[name]=matrix.tolist()
            simulation_time=self.total_physics_steps*env.physics_dt
        steps=self.total_physics_steps-self.last_frame_steps;self.last_frame_steps=self.total_physics_steps
        return {'images':images,'measured_q_rad':measured.tolist(),'applied_sim_joint_rad':applied.tolist(),'sim_joint_delta_rad':(applied.astype(np.float64)-measured).tolist(),
            'sim_target_joint_rad':target.tolist(),'sim_object_poses_world':objects,'simulation_time_s':simulation_time,
            'scene_identity':self.view.scene_identity,'engine':self.view.engine,'physics_steps':steps,'total_physics_steps':self.total_physics_steps,'state_application':self.state_application,
            'sim_timestamp':{'monotonic_ns':time.monotonic_ns(),'timestamp_kind':'render_completion_not_camera_exposure'},'render_ms':(time.monotonic_ns()-begin)/1e6,
            'sim_cameras':cameras,'joint_mapping':self.view.mapping,'geometry_status':'UNMEASURED'}
    def close(self):
        if self.renderer is not None:self.renderer.close();self.renderer=None
        if self.env is not None:self.env.close();self.env=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


def create_renderer(view,directory):
    if view.render_type=='authored':
        raise ValueError('Real/Sim physics requires native articulation and engine settings; this export only provides an authored pose view')
    return NativeRenderer(view,directory)
