"""Measured-FK rendering of a manifest-covered Builder export, without physics."""
from pathlib import Path
import numpy as np
from real2sim_builder.files import read,sha
from real2sim_builder.scene import validate,world_pose
from .calibration import JOINTS,mapper_from_metadata,joint_specs


def validate_binding(view):
    package=view.package;path=package.root/'authored_scene.json'
    if not any(f.path=='authored_scene.json'for f in package.files):raise ValueError('Manifest-covered authored Scene required')
    scene=read(path);validate(scene,package.root,complete=True);model=scene.get('robot_model',{})
    mapping=mapper_from_metadata(view.mapping)
    if model.get('joint_names')!=list(JOINTS)or package.scene['robot'].get('joint_order')!=tuple(JOINTS):raise ValueError('Authored Scene requires the explicit six-axis robot joint order')
    if model.get('model_sha256')!=mapping.profile['urdf_sha256']or model.get('model_sha256')!=package.scene['robot'].get('source_model_sha256'):raise ValueError('Authored model and measured Mapping identity differ')
    if model.get('path')!=package.scene['robot'].get('asset_path'):raise ValueError('Authored FK model differs from exported robot')
    if sha(package.root/model['path'])!=model['model_sha256']:raise ValueError('FK model bytes changed')
    if not any(o.get('link')for o in scene['objects']):raise ValueError('Authored Scene has no robot link geometry')
    cameras={c['id']:c for c in scene['cameras']}
    if not {'side','wrist'}<=cameras.keys()or any(cameras[n]['resolution']!=[640,480]for n in('side','wrist')):raise ValueError('Explicit Side/Wrist 640×480 camera declarations required')
    view.authored_scene=scene


class AuthoredRenderer:
    def __init__(self,view,directory):
        self.view=view;self.renderer=None;self.static=None;directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        self.bounds=joint_specs(view.package.root/view.authored_scene['robot_model']['path'])
        if view.engine=='mujoco':
            import mujoco
            self.model=mujoco.MjModel.from_xml_path(str(view.package.root/view.package.scene['engines']['mujoco']['asset_path']));self.data=mujoco.MjData(self.model);self.renderer=mujoco.Renderer(self.model,height=480,width=640)
        elif view.engine=='isaac':self.static=StaticIsaacRenderer(view.authored_scene,view.package.root,directory)
        else:raise ValueError('Unsupported authored Scene engine')
    def render(self,q):
        import time
        from real2sim_builder.capture import observation_scene
        self.view.verify();begin=time.monotonic_ns();raw=np.asarray(q)
        if raw.shape!=(6,)or raw.dtype.kind not in'fiu'or not np.isfinite(raw).all():raise ValueError('Six finite measured model-radian joints required')
        for n,x in zip(JOINTS,raw):
            if not self.bounds[n]['limits'][0]<=x<=self.bounds[n]['limits'][1]:raise ValueError('Measured joint outside authored model limits: '+n)
        scene=observation_scene(self.view.authored_scene,{'session_id':'measured','eligible':True,'q_measured':raw.tolist(),'joint_names':list(JOINTS)},self.view.package.root)
        if self.static:images=self.static.render(scene)
        else:
            import mujoco
            from scipy.spatial.transform import Rotation
            from real2sim_builder.cameras import OPTICAL_TO_RENDER
            for obj in scene['objects']:
                index=mujoco.mj_name2id(self.model,mujoco.mjtObj.mjOBJ_BODY,obj['id']);pose=world_pose(scene,obj);quaternion=Rotation.from_matrix(pose[:3,:3]).as_quat()[[3,0,1,2]]
                if index<0:raise ValueError('Authored object missing from native model')
                address=self.model.body_jntadr[index]
                if self.model.body_jntnum[index]and self.model.jnt_type[address]==mujoco.mjtJoint.mjJNT_FREE:
                    offset=self.model.jnt_qposadr[address];self.data.qpos[offset:offset+7]=np.r_[pose[:3,3],quaternion]
                else:self.model.body_pos[index]=pose[:3,3];self.model.body_quat[index]=quaternion
            for camera in scene['cameras']:
                index=mujoco.mj_name2id(self.model,mujoco.mjtObj.mjOBJ_CAMERA,camera['id']);pose=world_pose(scene,camera)@OPTICAL_TO_RENDER;self.model.cam_pos[index]=pose[:3,3];self.model.cam_quat[index]=Rotation.from_matrix(pose[:3,:3]).as_quat()[[3,0,1,2]]
            mujoco.mj_forward(self.model,self.data);images={}
            for n in('side','wrist'):self.renderer.update_scene(self.data,camera=n);images[n]=self.renderer.render().copy()
        cameras={c['id']:{'resolution':c['resolution'],'K':c['K']['value'],'T_world_optical':world_pose(scene,c).tolist()}for c in scene['cameras']if c['id']in('side','wrist')}
        return {'images':images,'measured_q_rad':raw.tolist(),'applied_sim_joint_rad':raw.tolist(),'sim_joint_delta_rad':[0.]*6,'scene_identity':self.view.scene_identity,'engine':self.view.engine,'physics_steps':0,'state_application':'authored_measured_fk',
                'sim_timestamp':{'monotonic_ns':time.monotonic_ns(),'timestamp_kind':'render_completion_not_camera_exposure'},'render_ms':(time.monotonic_ns()-begin)/1e6,'sim_cameras':cameras,'joint_mapping':self.view.mapping,'geometry_status':'UNMEASURED','physical_verified':False}
    def close(self):
        if self.renderer:self.renderer.close();self.renderer=None
        if self.static:self.static.close();self.static=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class StaticIsaacRenderer:
    def __init__(self,scene,root,directory):
        import isaaclab.sim as sim
        from isaaclab.sensors import Camera,CameraCfg
        from real2sim_builder.exporters.usd import export
        import omni.usd
        self.sim=sim.SimulationContext(sim.SimulationCfg(dt=1/30,device='cuda:0'));self.cameras={}
        try:
            path=directory/'authored.usda';export(scene,root,path);cfg=sim.UsdFileCfg(usd_path=str(path));cfg.func('/World/Authored',cfg);self.stage=omni.usd.get_context().get_stage()
            for n in('side','wrist'):self.cameras[n]=Camera(CameraCfg(prim_path='/World/Authored/'+n,spawn=None,width=640,height=480,data_types=['rgb'],update_latest_camera_pose=True))
            self.sim.reset()
        except BaseException:self.close();raise
    def render(self,scene):
        from pxr import Gf
        from real2sim_builder.cameras import OPTICAL_TO_RENDER
        for row in scene['objects']+scene['cameras']:
            pose=world_pose(scene,row)
            if row in scene['cameras']:pose=pose@OPTICAL_TO_RENDER
            attr=self.stage.GetPrimAtPath('/World/Authored/'+row['id']).GetAttribute('xformOp:transform')
            if not attr:raise ValueError('Authored USD transform unavailable: '+row['id'])
            attr.Set(Gf.Matrix4d(*pose.T.ravel().tolist()))
        for _ in range(3):self.sim.render()
        for sensor in self.cameras.values():sensor.update(1/30,force_recompute=True)
        return {n:s.data.output['rgb'][0,:,:,:3].detach().cpu().numpy().copy()for n,s in self.cameras.items()}
    def close(self):
        # Isaac Lab's public build_simulation_context uses this cleanup order.
        # stop() here invokes its standalone STOP callback's render-until-resume
        # loop, preventing a headless child from ever returning to app.close().
        self.cameras.clear();self.sim.clear_all_callbacks();self.sim.clear_instance()
