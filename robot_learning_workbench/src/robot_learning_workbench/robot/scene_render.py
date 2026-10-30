"""Read-only native Scene state mirroring, never a physical robot command or Task step."""
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
    def __init__(self,view,directory):
        self.view=view;self.env=None;self.renderer=None;self.model=None;self.binding=None
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        if view.engine=='mujoco':
            import mujoco
            from ..engines.mujoco.model import ModelConfig,build_model
            self.model,self.binding=build_model(view.package,ModelConfig(**view.settings));self.data=mujoco.MjData(self.model)
            self.renderer=mujoco.Renderer(self.model,height=480,width=640)
        elif view.engine=='isaac':
            from isaaclab.envs import ManagerBasedEnv
            from ..engines.isaac.env_cfg import build_env_cfg
            try:self.env=ManagerBasedEnv(cfg=build_env_cfg(view.package,view.settings,runtime_directory=directory/'native'));self.env.reset()
            except BaseException:self.close();raise
        else:raise ValueError('Actual MuJoCo or Isaac Scene engine required')
    def render(self,q):
        self.view.verify();begin=time.monotonic_ns();raw=np.asarray(q)
        if raw.shape!=(6,)or raw.dtype.kind not in'fiu'or not np.isfinite(raw).all():raise ValueError('Six finite measured model-radian joints required')
        measured=raw.astype(np.float64);images={};cameras={}
        if self.view.engine=='mujoco':
            import mujoco
            from ..engines.mujoco.state import camera_pose
            self.data.qpos[list(self.binding.q_indices)]=measured;self.data.qvel[list(self.binding.v_indices)]=0
            mujoco.mj_forward(self.model,self.data)
            for name in('side','wrist'):
                self.renderer.update_scene(self.data,camera=self.binding.camera_ids[name]);images[name]=self.renderer.render().copy()
                cameras[name]={'resolution':[640,480],'K':self.view.package.scene['cameras'][name]['K'],'T_world_optical':camera_pose(self.model,self.data,self.binding,name).tolist()}
            applied=self.data.qpos[list(self.binding.q_indices)].copy()
        else:
            import torch
            from scipy.spatial.transform import Rotation
            env=self.env;robot=env.scene['robot'];ids=[robot.joint_names.index(n)for n in JOINTS]
            pose=robot.data.joint_pos.clone();pose[:,ids]=torch.as_tensor(measured,dtype=pose.dtype,device=env.device)
            robot.write_joint_state_to_sim(pose,torch.zeros_like(pose));env.scene.write_data_to_sim();env.sim.forward();env.scene.update(env.physics_dt)
            for _ in range(3):env.sim.render()
            for name in('side','wrist'):
                sensor=env.scene['camera_'+name];sensor.update(env.physics_dt,force_recompute=True)
                images[name]=sensor.data.output['rgb'][0,:,:,:3].detach().cpu().numpy().copy()
                quaternion=sensor.data.quat_w_ros[0].detach().cpu().numpy();transform=np.eye(4);transform[:3,:3]=Rotation.from_quat(quaternion[[1,2,3,0]]).as_matrix();transform[:3,3]=sensor.data.pos_w[0].detach().cpu().numpy()
                cameras[name]={'resolution':[640,480],'K':sensor.data.intrinsic_matrices[0].detach().cpu().numpy().tolist(),'T_world_optical':transform.tolist()}
            applied=robot.data.joint_pos[0,ids].detach().cpu().numpy().copy()
        return {'images':images,'measured_q_rad':measured.tolist(),'applied_sim_joint_rad':applied.tolist(),'sim_joint_delta_rad':(applied.astype(np.float64)-measured).tolist(),
            'scene_identity':self.view.scene_identity,'engine':self.view.engine,'physics_steps':0,'state_application':'native_measured_joint_state',
            'sim_timestamp':{'monotonic_ns':time.monotonic_ns(),'timestamp_kind':'render_completion_not_camera_exposure'},'render_ms':(time.monotonic_ns()-begin)/1e6,
            'sim_cameras':cameras,'joint_mapping':self.view.mapping,'geometry_status':'UNMEASURED'}
    def close(self):
        if self.renderer is not None:self.renderer.close();self.renderer=None
        if self.env is not None:self.env.close();self.env=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


def create_renderer(view,directory):
    if view.render_type=='authored':
        from .authored_render import AuthoredRenderer
        return AuthoredRenderer(view,directory)
    return NativeRenderer(view,directory)
