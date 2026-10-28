"""Isaac Lab2.3 Scene/Env configuration, built only after official AppLauncher.

Source: https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html
Source: https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.sim.converters.html
This module's import and execution-input validation do not import Isaac/PhysX.
"""
from pathlib import Path
import hashlib
import json
import math
import numpy as np


def execution_inputs(package, settings):
    """Bind explicit engine settings to this immutable package.

    No original repository, active calibration pointer or default robot fallback.
    """
    from collections.abc import Mapping
    if not isinstance(settings,Mapping):raise ValueError('Explicit engine settings mapping required; Recipe preparation is a separate boundary')
    identity=settings['scene_identity']
    if any(identity[k]!=getattr(package.identity,k) for k in ('scene_id','revision','manifest_sha256')):
        raise ValueError('Scene identity differs from execution input')
    files={f.path:f for f in package.files}
    def read_bound(row):
        path=row['asset_path']
        if path not in files or files[path].sha256!=row['sha256']:raise ValueError('Execution metadata outside manifest or wrong hash')
        source=package.root/path;raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Execution input changed')
        return json.loads(raw)
    metadata={key:read_bound(settings['baseline_metadata'][key]) for key in ('profile','task','physics','compiled_physics')}
    joints=tuple(package.scene['robot']['joint_order'])
    if joints!=('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper'):
        raise ValueError('Unsupported joint order for SO101 environment')
    q=settings['initial_joint_rad']
    if set(q)!=set(joints) or not all(math.isfinite(q[n]) for n in joints):raise ValueError('Invalid full initial model-radian joint state')
    objects=tuple(settings['active_object_ids'])
    if len(set(objects))!=len(objects) or not objects or any(n not in package.scene['objects'] or package.scene['objects'][n]['role']!='task_object' for n in objects):
        raise ValueError('Active objects must be distinct declared task objects')
    physics=settings['isaac'];dt=physics['physics_timestep_s'];decimation=physics['decimation']
    if not isinstance(dt,(int,float)) or not math.isfinite(dt) or dt<=0 or type(decimation) is not int or decimation<=0:
        raise ValueError('Invalid explicit physics timestep/decimation')
    candidates=[]
    for record in package.calibration['records'].values():
        if record['kind']=='robot_residual' and record['application']['mode']=='baked':
            for path in record['application']['asset_paths']:
                if Path(path).suffix=='.urdf':candidates.append((path,record['execution_model_sha256']))
    if len(candidates)!=1:raise ValueError('One explicitly bound baked execution URDF required')
    model,digest=candidates[0]
    if model not in files or files[model].sha256!=digest or hashlib.sha256((package.root/model).read_bytes()).hexdigest()!=digest:
        raise ValueError('Execution model identity differs from baked Calibration')
    binding=package.scene['robot'].get('bindings',{}).get('isaac',{})
    usd=binding.get('asset_path')
    if usd not in files or Path(usd).suffix.lower() not in ('.usd','.usda','.usdc'):
        raise ValueError('Explicit packaged Isaac execution USD required; no importer fallback')
    if hashlib.sha256((package.root/usd).read_bytes()).hexdigest()!=files[usd].sha256:
        raise ValueError('Isaac execution USD identity changed')
    return dict(metadata,robot_usd=package.root/usd,robot_urdf=package.root/model,joint_order=joints,initial_joint_rad=dict(q),active_object_ids=objects,
                dt=dt,decimation=decimation,seed=settings['seed'],scene_identity=dict(identity),source_settings=settings)


def write_scene_assets(package, inputs, directory):
    """Derive local USD views, excluding snapshot robots and inactive manipulands.

    References retain package mesh/material bytes. Derived layers live outside the
    immutable package and are not a replacement Scene/Dataset format.
    """
    from pxr import Usd,UsdGeom,UsdPhysics,UsdShade,Gf
    from scene_contract.transforms import resolve_transform
    directory=Path(directory).resolve()
    if directory.is_relative_to(package.root):raise ValueError('Runtime assets must not modify Scene package')
    directory.mkdir(parents=True,exist_ok=False)
    source=package.root/package.scene['engines']['isaac']['asset_path']
    provenance=json.loads((package.root/'provenance.json').read_text())['original_scene']
    originals={o['id']:o for o in provenance['objects']}
    def mounted(name):
        frame=originals[name]['frame']
        while frame is not None:
            if frame=='robot_link_gripper':return True
            frame=provenance['frames'][frame]['parent']
        return False
    attached=[n for n in originals if mounted(n)]
    targets=[n for n,o in package.scene['objects'].items() if o['role']=='receptacle']
    bodies=list(inputs['active_object_ids'])+targets
    stage=Usd.Stage.CreateNew(str(directory/'static.usda'));prim=UsdGeom.Xform.Define(stage,'/Static').GetPrim()
    stage.SetDefaultPrim(prim);prim.GetReferences().AddReference(str(source),'/Scene')
    for name,obj in package.scene['objects'].items():
        path='/Static/'+name
        if obj['role']=='reference_robot' or name in inputs['task']['dynamic'] or name in targets or name in attached:
            stage.OverridePrim(path).SetActive(False);continue
        collision=inputs['compiled_physics']['objects'].get(name,{}).get('collision',False)
        for child in Usd.PrimRange(stage.GetPrimAtPath(path)):
            if child.HasAPI(UsdPhysics.CollisionAPI):UsdPhysics.CollisionAPI(child).CreateCollisionEnabledAttr(collision)
    for name in package.scene['cameras']:stage.OverridePrim('/Static/'+name).SetActive(False)
    stage.GetRootLayer().Save()
    result={'static':directory/'static.usda','objects':{},'mounted':{}}
    for name in bodies+attached:
        path=directory/(name+'.usda');stage=Usd.Stage.CreateNew(str(path));prim=UsdGeom.Xform.Define(stage,'/Object').GetPrim();stage.SetDefaultPrim(prim)
        prim.GetReferences().AddReference(str(source),'/Scene/'+name)
        pose=np.eye(4)
        if name in attached:
            pose=resolve_transform(package.scene['frames'],source=package.scene['objects'][name]['frame_id'],target='robot_link_gripper')
        UsdGeom.Xformable(prim).MakeMatrixXform().Set(Gf.Matrix4d(pose.T.tolist()))
        if name in attached:
            prim.RemoveAPI(UsdPhysics.RigidBodyAPI);prim.RemoveAPI(UsdPhysics.MassAPI)
        else:
            UsdPhysics.RigidBodyAPI.Apply(prim).CreateKinematicEnabledAttr(name in targets)
        material=UsdShade.Material.Define(stage,'/Object/VisualMaterial');material.GetPrim().GetReferences().AddReference(str(source),'/Scene/material_'+name)
        physical=UsdShade.Material.Define(stage,'/Object/PhysicsMaterial');mat=UsdPhysics.MaterialAPI.Apply(physical.GetPrim())
        spec=inputs['compiled_physics']['objects'].get(name,{})
        values=spec.get('material') or {'static_friction':1.,'dynamic_friction':1.,'restitution':0.}
        mat.CreateStaticFrictionAttr(values['static_friction']);mat.CreateDynamicFrictionAttr(values['dynamic_friction']);mat.CreateRestitutionAttr(values['restitution'])
        for child in list(Usd.PrimRange(prim)):
            if child.GetName().startswith('visual_'):UsdShade.MaterialBindingAPI.Apply(child).Bind(material)
            if child.HasAPI(UsdPhysics.CollisionAPI):
                UsdPhysics.CollisionAPI(child).CreateCollisionEnabledAttr(bool(spec.get('collision',False)))
                UsdShade.MaterialBindingAPI.Apply(child).Bind(physical,materialPurpose='physics')
        stage.GetRootLayer().Save();result['mounted' if name in attached else 'objects'][name]=path
    return result


def spawn_robot(prim_path,cfg,translation=None,orientation=None,**kwargs):
    """Reference the packaged execution USD without rebuilding its physics.

    Source: https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.sim.spawners.html
    Preserve instanced colliders, compound groups, pads and authored joint frames.
    """
    from isaaclab.sim.spawners.from_files import spawn_from_usd
    from pxr import Usd,UsdGeom
    robot=spawn_from_usd(prim_path,cfg,translation=translation,orientation=orientation,**kwargs)
    stage=robot.GetStage()
    camera=stage.GetPrimAtPath(robot.GetPath().AppendPath('gripper/Camera_WristView'))
    if camera and camera.IsA(UsdGeom.Camera):
        with Usd.EditContext(stage,stage.GetSessionLayer()):camera.SetActive(False)
    return robot


def build_env_cfg(package,settings,*,runtime_directory,device='cuda:0',num_envs=1):
    """Create concrete ManagerBasedEnvCfg after AppLauncher, without an Env adapter.

    settings is explicit bound engine input, not a PreparedRun/Recipe runner.
    """
    inputs=execution_inputs(package,settings)
    if type(num_envs) is not int or num_envs<1:raise ValueError('Positive num_envs required')
    if device not in ('cpu','cuda:0'):raise ValueError('Explicit supported device required')
    from scipy.spatial.transform import Rotation
    import isaaclab.sim as sim
    from isaaclab.scene import InteractiveSceneCfg
    from isaaclab.assets import AssetBaseCfg,ArticulationCfg,RigidObjectCfg
    from isaaclab.actuators import ImplicitActuatorCfg
    from isaaclab.sensors import Camera,CameraCfg,FrameTransformerCfg,ContactSensorCfg
    from isaaclab.envs import ManagerBasedEnvCfg
    from isaaclab.managers import ObservationGroupCfg,ObservationTermCfg,EventTermCfg,SceneEntityCfg
    from isaaclab.envs.mdp.actions import JointPositionActionCfg
    import isaaclab.envs.mdp as official_mdp
    from isaaclab.utils import configclass
    from . import mdp
    runtime=Path(runtime_directory).resolve();assets=write_scene_assets(package,inputs,runtime/'scene')
    def pose(matrix):
        matrix=np.asarray(matrix);quat=Rotation.from_matrix(matrix[:3,:3]).as_quat()
        return tuple(matrix[:3,3]),tuple(quat[[3,0,1,2]])
    class RuntimeCamera(Camera):
        def _update_poses(self,env_ids):
            if not self.cfg.prim_path.rsplit('/',1)[0].endswith('/gripper'):return super()._update_poses(env_ids)
            import torch
            from isaaclab.utils.math import combine_frame_transforms,convert_camera_frame_orientation_convention
            if not hasattr(self,'_mount_view'):
                parent=self.cfg.prim_path.rsplit('/',1)[0].replace('.*','*');self._mount_view=sim.SimulationContext.instance().physics_sim_view.create_rigid_body_view(parent)
            state=self._mount_view.get_transforms()[env_ids]
            local_p=torch.tensor(self.cfg.offset.pos,device=self.device,dtype=state.dtype).expand(len(state),-1)
            local_q=torch.tensor(self.cfg.offset.rot,device=self.device,dtype=state.dtype).expand(len(state),-1)
            position,rotation=combine_frame_transforms(state[:,:3],state[:,[6,3,4,5]],local_p,local_q)
            self._data.pos_w[env_ids]=position;self._data.quat_w_world[env_ids]=convert_camera_frame_orientation_convention(rotation,origin=self.cfg.offset.convention,target='world')
    scene=InteractiveSceneCfg(num_envs=num_envs,env_spacing=2.)
    gains={'shoulder_pan':(55.,.7),'shoulder_lift':(30.,.8),'elbow_flex':(25.,.7),'wrist_flex':(12.,.5),'wrist_roll':(7.,.5),'gripper':(4.,.3)}
    robot_spawn=sim.UsdFileCfg(usd_path=str(inputs['robot_usd']),activate_contact_sensors=True,
        rigid_props=sim.RigidBodyPropertiesCfg(disable_gravity=False,max_depenetration_velocity=5.),
        articulation_props=sim.ArticulationRootPropertiesCfg(enabled_self_collisions=False,solver_position_iteration_count=32,solver_velocity_iteration_count=1,fix_root_link=True))
    robot_spawn.func=spawn_robot
    root_pos,root_rot=pose(inputs['profile']['robot_base']['T_world'])
    scene.robot=ArticulationCfg(prim_path='{ENV_REGEX_NS}/Robot',spawn=robot_spawn,
        init_state=ArticulationCfg.InitialStateCfg(pos=root_pos,rot=root_rot,joint_pos=inputs['initial_joint_rad']),
        actuators={'joints':ImplicitActuatorCfg(joint_names_expr=list(inputs['joint_order']),effort_limit_sim=30.,stiffness={n:v[0] for n,v in gains.items()},damping={n:v[1] for n,v in gains.items()})})
    scene.workspace_static=AssetBaseCfg(prim_path='{ENV_REGEX_NS}/Workspace',spawn=sim.UsdFileCfg(usd_path=str(assets['static'])))
    for name,file in assets['mounted'].items():setattr(scene,name,AssetBaseCfg(prim_path='{ENV_REGEX_NS}/Robot/gripper/'+name,spawn=sim.UsdFileCfg(usd_path=str(file))))
    from scene_contract.transforms import resolve_transform
    for name,file in assets['objects'].items():
        target=name not in inputs['active_object_ids'];spec=inputs['compiled_physics']['objects'][name]
        transform=resolve_transform(package.scene['frames'],source=package.scene['objects'][name]['frame_id'],target='world');pos,quat=pose(transform)
        setattr(scene,name,RigidObjectCfg(prim_path='{ENV_REGEX_NS}/'+name,
            spawn=sim.UsdFileCfg(usd_path=str(file),rigid_props=None if target else sim.RigidBodyPropertiesCfg(solver_position_iteration_count=16,solver_velocity_iteration_count=1),
                mass_props=sim.MassPropertiesCfg(mass=spec['mass_kg']) if not target else None,
                # v8 targets retain asset/PhysX offsets; .002 applies to cubes only.
                collision_props=None if target else sim.CollisionPropertiesCfg(contact_offset=.002,rest_offset=0.)),
            init_state=RigidObjectCfg.InitialStateCfg(pos=pos,rot=quat)))
    scene.ee_frame=FrameTransformerCfg(prim_path='{ENV_REGEX_NS}/Robot/base',debug_vis=False,target_frames=[FrameTransformerCfg.FrameCfg(prim_path='{ENV_REGEX_NS}/Robot/tool0',name='tool0')])
    scene.dome_light=AssetBaseCfg(prim_path='/World/Light',spawn=sim.DomeLightCfg(intensity=1000.,color=(.75,.75,.75)))
    for view,camera in inputs['profile']['cameras'].items():
        width,height=camera['resolution'];raw=np.asarray(camera['K']);f=(raw[0,0]+raw[1,1])/2;pos,quat=pose(camera['T_parent_camera'])
        path='Robot/gripper/' if camera['parent']=='gripper' else ''
        setattr(scene,'camera_'+view,CameraCfg(class_type=RuntimeCamera,prim_path='{ENV_REGEX_NS}/'+path+'Camera_'+view,width=width,height=height,data_types=['rgb'],update_period=0.,update_latest_camera_pose=True,
            spawn=sim.PinholeCameraCfg(focal_length=24.,horizontal_aperture=24*width/f,vertical_aperture=24*height/f,clipping_range=(.001,100.),f_stop=0.),offset=CameraCfg.OffsetCfg(pos=pos,rot=quat,convention='ros')))
    for name,link in [('grasp_fixed_contact','gripper'),('grasp_moving_contact','jaw')]:
        setattr(scene,name,ContactSensorCfg(prim_path='{ENV_REGEX_NS}/Robot/'+link,update_period=0.,filter_prim_paths_expr=['{ENV_REGEX_NS}/'+n for n in inputs['active_object_ids']]))
    @configclass
    class Actions:
        joints=JointPositionActionCfg(asset_name='robot',joint_names=list(inputs['joint_order']),scale=1.,use_default_offset=False,preserve_order=True)
    @configclass
    class Policy(ObservationGroupCfg):
        joint_pos=ObservationTermCfg(func=official_mdp.joint_pos)
        joint_vel=ObservationTermCfg(func=official_mdp.joint_vel)
        ee_state=ObservationTermCfg(func=mdp.ee_state)
        side_cam=ObservationTermCfg(func=official_mdp.image,params={'sensor_cfg':SceneEntityCfg('camera_side'),'normalize':False})
        wrist_cam=ObservationTermCfg(func=official_mdp.image,params={'sensor_cfg':SceneEntityCfg('camera_wrist'),'normalize':False})
    @configclass
    class Observations:
        policy=Policy(concatenate_terms=False,enable_corruption=False)
    @configclass
    class Events:
        reset=EventTermCfg(func=mdp.reset_scene,mode='reset')
    cfg=ManagerBasedEnvCfg();cfg.scene=scene;cfg.actions=Actions();cfg.observations=Observations();cfg.events=Events()
    cfg.sim.dt=inputs['dt'];cfg.decimation=cfg.sim.render_interval=inputs['decimation'];cfg.sim.device=device;cfg.seed=inputs['seed']
    cfg.workbench_joint_order=inputs['joint_order'];cfg.workbench_scene_identity=inputs['scene_identity'];cfg.workbench_active_objects=inputs['active_object_ids'];cfg.workbench_inputs=inputs
    import xml.etree.ElementTree as ET
    model=ET.parse(inputs['robot_urdf']).getroot()
    cfg.workbench_joint_limits_rad=tuple(tuple(float(model.find("joint[@name='"+name+"']/limit").get(key)) for key in ('lower','upper')) for name in inputs['joint_order'])
    return cfg
