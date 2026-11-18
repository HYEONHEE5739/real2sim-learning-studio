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


_PINHOLE_SCHEMA='OmniLensDistortionOpenCvPinholeAPI'
_PINHOLE_PREFIX='omni:lensdistortion:opencvPinhole:'
_PINHOLE_COEFFICIENTS=('k1','k2','p1','p2','k3','k4','k5','k6','s1','s2','s3','s4')


def _pinhole_properties(matrix, resolution, focal_length=24.):
    """Checked USD pinhole parameters; native lens schema owns RTX projection."""
    raw=np.asarray(matrix)
    if raw.shape!=(3,3)or raw.dtype.kind not in 'fiu'or not np.isfinite(raw).all():raise ValueError('Finite numeric 3x3 Camera K required')
    k=raw.astype(float)
    if k[0,0]<=0 or k[1,1]<=0:raise ValueError('Positive Camera focal lengths required')
    if k[0,1]!=0 or k[1,0]!=0 or not np.array_equal(k[2],[0.,0.,1.]):raise ValueError('NOT_SUPPORTED: zero-skew homogeneous pinhole K required')
    if len(resolution)!=2 or any(type(n)is not int or n<=0 for n in resolution):raise ValueError('Positive integer Camera resolution required')
    if type(focal_length)not in(int,float)or not math.isfinite(focal_length)or focal_length<=0:raise ValueError('Positive finite USD focal length required')
    width,height=resolution
    # Same USD convention as Builder's exporter/IsaacRenderer. Physical camera
    # attributes alone do not preserve these intrinsics in the installed Lab.
    properties={'focal_length':focal_length,'horizontal_aperture':focal_length*width/k[0,0],
        'vertical_aperture':focal_length*height/k[1,1],
        'horizontal_aperture_offset':(width/2-k[0,2])*focal_length/k[0,0],
        'vertical_aperture_offset':(k[1,2]-height/2)*focal_length/k[1,1]}
    with np.errstate(over='ignore',under='ignore'):
        native_k=k.astype(np.float32);native_properties=np.asarray(list(properties.values()),dtype=np.float32)
    if not np.isfinite(native_k).all()or native_k[0,0]<=0 or native_k[1,1]<=0 or not np.isfinite(native_properties).all()or np.any(native_properties[:3]<=0):
        raise ValueError('Camera parameters outside finite positive USD float32 range')
    return properties


def _set_native_pinhole(sensor,matrix,resolution,properties):
    """Same schema/attributes as Isaac Sim5.1 Camera.set_opencv_pinhole_properties.

    Use the existing Lab sensor, not another SDK Camera/render product. Author
    only its runtime session layer, never a referenced Scene or calibration.
    """
    from pxr import Gf,Usd,Tf
    prim=sensor.GetPrim();stage=prim.GetStage()
    try:can_apply=prim.CanApplyAPI(_PINHOLE_SCHEMA)
    except Tf.ErrorException as error:raise NotImplementedError('NOT_SUPPORTED: native OpenCV pinhole schema unavailable')from error
    if not can_apply:raise NotImplementedError('NOT_SUPPORTED: native OpenCV pinhole schema unavailable')
    with Usd.EditContext(stage,stage.GetSessionLayer()):
        if not prim.ApplyAPI(_PINHOLE_SCHEMA):raise NotImplementedError('NOT_SUPPORTED: cannot apply native OpenCV pinhole schema')
        attributes={'omni:lensdistortion:model':'opencvPinhole',
            _PINHOLE_PREFIX+'imageSize':Gf.Vec2i(*resolution)}
        attributes.update({_PINHOLE_PREFIX+name:float(value)for name,value in
            [('fx',matrix[0,0]),('fy',matrix[1,1]),('cx',matrix[0,2]),('cy',matrix[1,2])]})
        attributes.update({_PINHOLE_PREFIX+name:0. for name in _PINHOLE_COEFFICIENTS})
        # Physical USD attributes remain consistent for downstream inspection;
        # RTX projection is driven by the lens schema, not aperture offsets.
        for name,value in properties.items():
            first,*rest=name.split('_')
            attributes[first+''.join(word.capitalize()for word in rest)]=float(value)
        for name,value in attributes.items():
            attr=prim.GetAttribute(name)
            if not attr or not attr.Set(value):raise NotImplementedError('NOT_SUPPORTED: cannot set Camera attribute '+name)


def _native_pinhole_matrix(sensor,resolution):
    prim=sensor.GetPrim()
    if not prim.HasAPI(_PINHOLE_SCHEMA)or prim.GetAttribute('omni:lensdistortion:model').Get()!='opencvPinhole':
        raise NotImplementedError('NOT_SUPPORTED: calibrated native OpenCV pinhole schema required')
    if tuple(prim.GetAttribute(_PINHOLE_PREFIX+'imageSize').Get())!=tuple(resolution):raise ValueError('Camera lens calibration resolution changed')
    if any(prim.GetAttribute(_PINHOLE_PREFIX+name).Get()!=0. for name in _PINHOLE_COEFFICIENTS):raise ValueError('Undistorted pinhole Camera required')
    fx,fy,cx,cy=[prim.GetAttribute(_PINHOLE_PREFIX+name).Get()for name in ('fx','fy','cx','cy')]
    k=np.array([[fx,0.,cx],[0.,fy,cy],[0.,0.,1.]])
    if not np.isfinite(k).all()or fx<=0 or fy<=0:raise ValueError('Invalid native Camera intrinsic values')
    return k


def execution_inputs(package, settings, *, projection_adapter=False):
    """Bind explicit engine settings to this immutable package.

    No original repository, active calibration pointer or default robot fallback.
    """
    from collections.abc import Mapping
    if not isinstance(settings,Mapping):raise ValueError('Explicit engine settings mapping required; Recipe preparation is a separate boundary')
    if settings.get('render_type','native')!='native' or settings.get('simulation_mode','physics')!='physics':
        raise ValueError('Task Physics requires a Native Physics profile; Pose/Authored is not physics')
    if 'baseline_metadata'not in settings:return scene_execution_inputs(package,settings,projection_adapter=projection_adapter)
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
    if len(set(objects))!=len(objects) or any(n not in package.scene['objects'] or package.scene['objects'][n]['role']!='task_object' for n in objects):
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
    provenance=json.loads((package.root/'authored_scene.json').read_text())if (package.root/'authored_scene.json').is_file()else json.loads((package.root/'provenance.json').read_text())['original_scene']
    originals={o['id']:o for o in provenance['objects']}
    def mounted(name):
        frame=originals[name]['frame']
        while frame is not None:
            if frame.startswith('robot_link_'):return frame.removeprefix('robot_link_')
            frame=provenance['frames'][frame]['parent']
        return None
    from scene_contract.objects import present_objects
    present=set(present_objects(package.scene,inputs['active_object_ids']))
    attached=[n for n in originals if n in present and mounted(n)]
    targets=[n for n,o in package.scene['objects'].items() if n in present and o['role']=='receptacle']
    bodies=list(inputs['active_object_ids'])+targets
    stage=Usd.Stage.CreateNew(str(directory/'static.usda'));prim=UsdGeom.Xform.Define(stage,'/Static').GetPrim()
    stage.SetDefaultPrim(prim);prim.GetReferences().AddReference(str(source),'/Scene')
    for name,obj in package.scene['objects'].items():
        path='/Static/'+name
        if name not in present or obj['role']=='reference_robot' or name in inputs['task']['dynamic'] or name in targets or name in attached:
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
            pose=resolve_transform(package.scene['frames'],source=package.scene['objects'][name]['frame_id'],target='robot_link_'+mounted(name))
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


def build_env_cfg(package,settings,*,runtime_directory,device='cuda:0',num_envs=1,projection_adapter=False):
    """Create concrete ManagerBasedEnvCfg after AppLauncher, without an Env adapter.

    settings is explicit bound engine input, not a PreparedRun/Recipe runner.
    """
    inputs=execution_inputs(package,settings,projection_adapter=projection_adapter)
    camera_properties={name:_pinhole_properties(camera['K'],camera['resolution'])for name,camera in inputs['profile']['cameras'].items()}
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
    # InteractiveScene expands ENV_REGEX_NS in copied CameraCfg prim paths.
    # The unique terminal Camera name survives that expansion.
    camera_intrinsics={'Camera_'+name:np.array(row['K'],dtype=float,copy=True)for name,row in inputs['profile']['cameras'].items()}
    class RuntimeCamera(Camera):
        def _initialize_impl(self):
            self._workbench_intrinsics_initialized=False
            super()._initialize_impl()
        def set_intrinsic_matrices(self,matrices,focal_length=None,env_ids=None):
            import torch
            raw=matrices.detach().cpu().numpy()if isinstance(matrices,torch.Tensor)else np.asarray(matrices)
            ids=list(range(len(self._sensor_prims)))if env_ids is None else np.asarray(
                env_ids.detach().cpu().numpy()if isinstance(env_ids,torch.Tensor)else env_ids)
            ids=np.asarray(ids)
            if ids.ndim!=1 or ids.dtype.kind not in 'iu'or len(set(ids.tolist()))!=len(ids)or np.any(ids<0)or np.any(ids>=len(self._sensor_prims)):
                raise ValueError('Distinct valid Camera env_ids required')
            if raw.shape!=(len(ids),3,3):raise ValueError('One 3x3 intrinsic matrix per Camera env_id required')
            resolution=(self.cfg.width,self.cfg.height)
            focal=self.cfg.spawn.focal_length if focal_length is None else focal_length
            # Validate the entire batch before writing any Camera prim/buffer.
            properties=[_pinhole_properties(k,resolution,focal)for k in raw]
            for index,k,params in zip(ids,raw,properties):_set_native_pinhole(self._sensor_prims[index],k,resolution,params)
            self._workbench_intrinsics_initialized=True
            self._update_intrinsic_matrices(ids)
        def _update_intrinsic_matrices(self,env_ids):
            if not getattr(self,'_workbench_intrinsics_initialized',False):
                k=camera_intrinsics[self.cfg.prim_path.rsplit('/',1)[-1]]
                self.set_intrinsic_matrices(np.broadcast_to(k,(len(self._sensor_prims),3,3)))
                return
            for index in env_ids:
                k=_native_pinhole_matrix(self._sensor_prims[index],(self.cfg.width,self.cfg.height))
                self._data.intrinsic_matrices[index]=self._data.intrinsic_matrices.new_tensor(k)
        def _update_poses(self,env_ids):
            if '/Robot/'not in self.cfg.prim_path:return super()._update_poses(env_ids)
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
    for name,file in assets['mounted'].items():
        from scene_contract.transforms import resolve_transform
        authored=json.loads((package.root/('authored_scene.json'if(package.root/'authored_scene.json').is_file()else'provenance.json')).read_text())
        authored=authored.get('original_scene',authored);row=next(o for o in authored['objects']if o['id']==name);frame=row['frame']
        while not frame.startswith('robot_link_'):frame=authored['frames'][frame]['parent']
        local=resolve_transform(package.scene['frames'],source=package.scene['objects'][name]['frame_id'],target=frame)
        mount_pos,mount_rot=pose(local)
        # AssetBase passes its initial pose to the USD spawner, replacing the
        # root transform in the derived layer. Preserve the declared mount.
        setattr(scene,name,AssetBaseCfg(prim_path='{ENV_REGEX_NS}/Robot/'+frame.removeprefix('robot_link_')+'/'+name,
            spawn=sim.UsdFileCfg(usd_path=str(file)),init_state=AssetBaseCfg.InitialStateCfg(pos=mount_pos,rot=mount_rot)))
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
        width,height=camera['resolution'];pos,quat=pose(camera['T_parent_camera'])
        path='Robot/'+camera['parent']+'/'if camera['parent']!='world'else''
        setattr(scene,'camera_'+view,CameraCfg(class_type=RuntimeCamera,prim_path='{ENV_REGEX_NS}/'+path+'Camera_'+view,width=width,height=height,data_types=['rgb'],update_period=0.,update_latest_camera_pose=True,
            spawn=sim.PinholeCameraCfg(**camera_properties[view],clipping_range=(.001,100.),f_stop=0.),offset=CameraCfg.OffsetCfg(pos=pos,rot=quat,convention='ros')))
    for name,link in ([('grasp_fixed_contact','gripper'),('grasp_moving_contact','jaw')]if inputs['active_object_ids']else[]):
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


def scene_execution_inputs(package,settings,*,projection_adapter=False):
    """Resolve a new Scene from its declared assets, not v8 baseline file names."""
    from dataclasses import asdict
    from collections.abc import Mapping
    from scene_contract.transforms import resolve_transform
    from ...robot.calibration import JOINTS,joint_specs
    from ...robot.calibration import execution_urdf
    files={f.path:f for f in package.files};identity=asdict(package.identity)
    if 'scene_identity'in settings and dict(settings['scene_identity'])!=identity:raise ValueError('Engine configuration belongs to another Scene revision')
    if tuple(package.scene['robot']['joint_order'])!=JOINTS:raise ValueError('Scene robot joint order must match SO101')
    urdf=execution_urdf(package);asset=package.scene['robot'].get('bindings',{}).get('isaac',{}).get('asset_path')
    if asset not in files or Path(asset).suffix.lower()not in('.usd','.usda','.usdc'):raise ValueError('Declare robot.bindings.isaac.asset_path with a physics-enabled SO101 USD; the static Builder reference robot is not an Articulation')
    q=settings.get('initial_joint_rad')
    if isinstance(q,(list,tuple)):q=dict(zip(JOINTS,q))if len(q)==6 else{}
    limits=joint_specs(urdf)
    if not isinstance(q,dict)or set(q)!=set(JOINTS)or any(type(q[n])not in(int,float)or not math.isfinite(q[n])or not limits[n]['limits'][0]<=q[n]<=limits[n]['limits'][1]for n in JOINTS):raise ValueError('Declare six initial_joint_rad values within the selected URDF limits')
    active=tuple(settings.get('active_object_ids',[n for n,o in package.scene['objects'].items()if o['role']=='task_object']))
    if len(set(active))!=len(active)or any(n not in package.scene['objects']or package.scene['objects'][n]['role']!='task_object'for n in active):raise ValueError('active_object_ids must name declared task objects')
    physics=settings.get('isaac',{});dt=physics.get('physics_timestep_s',1/300);decimation=physics.get('decimation',10)
    if not math.isfinite(dt)or dt<=0 or type(decimation)is not int or decimation<1:raise ValueError('Invalid physics timestep/decimation')
    def scalar(value):return value.get('value')if isinstance(value,Mapping)else value
    compiled={}
    for name,obj in package.scene['objects'].items():
        mass=scalar(obj['physics'].get('mass_kg'));friction=scalar(obj['physics'].get('friction'));override=settings.get('object_physics',{}).get(name,{})
        mass=override.get('mass_kg',mass)
        if name in active and(type(mass)not in(int,float)or not math.isfinite(mass)or mass<=0):raise ValueError(name+': dynamic object requires explicit positive mass_kg')
        compiled[name]={'collision':override.get('collision',obj['role']!='reference_robot'),'mass_kg':mass,'material':override.get('material',{'static_friction':1. if friction is None else friction,'dynamic_friction':1. if friction is None else friction,'restitution':0.})}
    authored=json.loads((package.root/'authored_scene.json').read_text())if(package.root/'authored_scene.json').is_file()else json.loads((package.root/'provenance.json').read_text())['original_scene']
    cameras={};rows={c['id']:c for c in authored['cameras']}
    for name,camera in package.scene['cameras'].items():
        if name not in ('side','wrist'):continue  # Photo cameras remain package references, not live sensors.
        if any(camera['distortion']):
            if not projection_adapter:raise ValueError(name+': undistorted pinhole camera required outside the Native Real/Sim projection adapter')
            projection=json.loads((package.root/'camera_projection.json').read_text())
            if projection.get('cameras',{}).get(name,{}).get('distortion')!=list(camera['distortion']):
                raise ValueError(name+': matching manifest-bound camera projection required')
        frame=rows[name]['frame'];parent='world'
        while frame is not None:
            if frame.startswith('robot_link_'):parent=frame.removeprefix('robot_link_');break
            frame=authored['frames'][frame]['parent']
        local=resolve_transform(package.scene['frames'],source=camera['frame_id'],target='robot_link_'+parent if parent!='world'else'world')
        cameras[name]={'parent':parent,'T_parent_camera':local.tolist(),'resolution':list(camera['resolution']),'K':camera['K']}
    if not {'side','wrist'}<=cameras.keys():raise ValueError('Scene must declare Side/Wrist cameras')
    profile={'robot_base':{'T_world':resolve_transform(package.scene['frames'],source='robot_base',target='world').tolist()},'cameras':cameras}
    return {'profile':profile,'task':{'dynamic':list(active)},'physics':{},'compiled_physics':{'objects':compiled},'robot_usd':package.root/asset,'robot_urdf':urdf,'joint_order':JOINTS,'initial_joint_rad':q,'active_object_ids':active,'dt':dt,'decimation':decimation,'seed':settings.get('seed',0),'scene_identity':identity,'source_settings':settings}
