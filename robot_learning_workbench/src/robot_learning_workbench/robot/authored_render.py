"""Measured-FK rendering of a manifest-covered Builder export, without physics."""
from pathlib import Path
import numpy as np
from real2sim_builder.files import read,sha
from real2sim_builder.scene import validate,world_pose
from real2sim_builder.cameras import camera_roles,select_render_cameras
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
    sensors=select_render_cameras(scene);_sensor_bindings(sensors)
    if any(c['resolution']!=[640,480]for c in sensors['cameras']):raise ValueError('Explicit Side/Wrist 640×480 camera declarations required')
    view.authored_scene=scene


def _sensor_bindings(scene):
    roles=camera_roles(scene);result={}
    for name,role in roles.items():
        if role not in('side','wrist'):continue
        if role in result:raise ValueError('Ambiguous sensor role metadata: '+role)
        result[role]=name
    if set(result)!={'side','wrist'}:raise ValueError('Explicit Side/Wrist sensor role metadata required')
    return result


class AuthoredRenderer:
    def __init__(self,view,directory):
        self.view=view;self.static=None;directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        self.sensor_ids=_sensor_bindings(view.authored_scene)
        self.bounds=joint_specs(view.package.root/view.authored_scene['robot_model']['path'])
        if view.engine=='mujoco':
            from real2sim_builder.rendering import Renderer
            self.static=Renderer(select_render_cameras(view.authored_scene),view.package.root,directory)
        elif view.engine=='isaac':
            from real2sim_builder.isaac_render import IsaacRenderer
            self.static=IsaacRenderer(select_render_cameras(view.authored_scene),view.package.root,directory,data_types=('rgb',))
        else:raise ValueError('Unsupported authored Scene engine')
    def render(self,q):
        import time
        from real2sim_builder.capture import observation_scene
        self.view.verify();begin=time.monotonic_ns();raw=np.asarray(q)
        if raw.shape!=(6,)or raw.dtype.kind not in'fiu'or not np.isfinite(raw).all():raise ValueError('Six finite measured model-radian joints required')
        for n,x in zip(JOINTS,raw):
            if not self.bounds[n]['limits'][0]<=x<=self.bounds[n]['limits'][1]:raise ValueError('Measured joint outside authored model limits: '+n)
        scene=observation_scene(self.view.authored_scene,{'session_id':'measured','eligible':True,'q_measured':raw.tolist(),'joint_names':list(JOINTS)},self.view.package.root)
        self.static.update_scene(select_render_cameras(scene))
        images={role:self.static.rgb(name)for role,name in self.sensor_ids.items()}
        selected={c['id']:c for c in scene['cameras']}
        cameras={role:{'camera_id':name,'resolution':selected[name]['resolution'],'K':selected[name]['K']['value'],
            'distortion':selected[name]['distortion']['value'],'T_world_optical':world_pose(scene,selected[name]).tolist()}for role,name in self.sensor_ids.items()}
        return {'images':images,'measured_q_rad':raw.tolist(),'applied_sim_joint_rad':raw.tolist(),'sim_target_joint_rad':raw.tolist(),'sim_joint_delta_rad':[0.]*6,'scene_identity':self.view.scene_identity,'source_scene':self.view.source_scene,'engine':self.view.engine,'physics_steps':0,'total_physics_steps':0,'simulation_time_s':0.,'state_application':'authored_measured_fk',
                'sim_timestamp':{'monotonic_ns':time.monotonic_ns(),'timestamp_kind':'render_completion_not_camera_exposure'},'render_ms':(time.monotonic_ns()-begin)/1e6,'sim_cameras':cameras,'joint_mapping':self.view.mapping,'geometry_status':'UNMEASURED','physical_verified':False}
    def close(self):
        if self.static:self.static.close();self.static=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
