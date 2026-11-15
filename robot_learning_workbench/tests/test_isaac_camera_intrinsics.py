"""Scene -> actual Isaac config boundary with test-only SDK objects, no Kit.

Physical pinhole reconstruction is an independent projection oracle. Runtime
lens-schema behavior is verified separately from these configuration tests.
"""
import copy
from dataclasses import replace
from collections.abc import Mapping
from importlib.metadata import distribution
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from pxr import Plug

from robot_learning_workbench.engines.isaac import env_cfg
from test_isaac_engine import package_and_inputs


# Without Kit, register the installed resource plugin during collection, before
# another test creates the first USD Stage and freezes SchemaRegistry's types.
# This uses the actual schema; it does not simulate ApplyAPI or attribute storage.
_usd_cache=Path(distribution('isaacsim').locate_file('isaacsim/extscache'))
_lens_plugins=list(_usd_cache.glob('omni.usd.schema.omni_lens_distortion-*/usd_plugins'))
assert len(_lens_plugins)==1
Plug.Registry().RegisterPlugins(str(_lens_plugins[0]))


def _mutable(value):
    if isinstance(value, Mapping):
        return {key: _mutable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mutable(item) for item in value]
    return value


def _scene_with_cameras(side, wrist=None, *, side_resolution=(640, 480), wrist_resolution=(640, 480)):
    package, settings = package_and_inputs()
    scene = _mutable(package.scene)
    scene['cameras']['side'].update(K=np.asarray(side).tolist(), resolution=list(side_resolution), distortion=[0.] * 5)
    scene['cameras']['wrist'].update(K=np.asarray(side if wrist is None else wrist).tolist(),
                                   resolution=list(wrist_resolution), distortion=[0.] * 5)
    return replace(package, scene=scene), {key: copy.deepcopy(value) for key, value in settings.items()
                                         if key not in ('baseline_metadata', 'package_root')}


class _Cfg:
    def __init__(self, *args, **kwargs):
        if args:
            assert len(args) == 1
            self.name = args[0]
        self.__dict__.update(kwargs)


class _Pinhole(_Cfg):
    horizontal_aperture_offset = 0.
    vertical_aperture_offset = 0.

    @classmethod
    def from_intrinsic_matrix(cls, intrinsic_matrix, width, height, focal_length=None, **kwargs):
        # Exact observed contract of the installed Lab2.3 converter: it warns
        # and collapses non-square pixels / offsets. It is not an exact oracle.
        k = np.asarray(intrinsic_matrix).reshape(3, 3)
        f = (k[0, 0] + k[1, 1]) / 2
        pixel = 1 / float(width) if focal_length is None else focal_length / f
        return cls(focal_length=pixel * f, horizontal_aperture=pixel * width,
                   vertical_aperture=pixel * height, **kwargs)


class _Camera:
    @property
    def data(self):return self._data

    def update(self,*args,**kwargs):pass

    def _update_intrinsic_matrices(self, env_ids):
        # Installed Lab2.3 readback: horizontal aperture only, centered/square.
        for i in env_ids:
            f=self.cfg.width*self._sensor_prims[i].GetFocalLengthAttr().Get()/self._sensor_prims[i].GetHorizontalApertureAttr().Get()
            self._data.intrinsic_matrices[i]=self._data.intrinsic_matrices.new_tensor(
                [[f,0.,self.cfg.width/2],[0.,f,self.cfg.height/2],[0.,0.,1.]])

    def _update_poses(self, env_ids):
        self.updated_pose_ids = list(env_ids)


@pytest.fixture
def config_sdk(monkeypatch):
    """Replace only Isaac imports and USD asset derivation, not Camera inputs."""
    def module(name, **attrs):
        result = ModuleType(name)
        result.__dict__.update(attrs)
        if '.' not in name:
            result.__path__ = []
        monkeypatch.setitem(sys.modules, name, result)
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            if parent in sys.modules:
                setattr(sys.modules[parent], child, result)
        return result
    module('isaaclab')
    module('isaaclab.sim', **{name: _Cfg for name in (
        'UsdFileCfg', 'RigidBodyPropertiesCfg', 'ArticulationRootPropertiesCfg',
        'MassPropertiesCfg', 'CollisionPropertiesCfg', 'DomeLightCfg')}, PinholeCameraCfg=_Pinhole)
    module('isaaclab.scene', InteractiveSceneCfg=_Cfg)
    initial = type('Asset', (_Cfg,), {'InitialStateCfg': _Cfg})
    module('isaaclab.assets', AssetBaseCfg=initial, ArticulationCfg=initial, RigidObjectCfg=initial)
    module('isaaclab.actuators', ImplicitActuatorCfg=_Cfg)
    camera_cfg = type('CameraCfg', (_Cfg,), {'OffsetCfg': _Cfg})
    frame = type('FrameCfg', (_Cfg,), {'FrameCfg': _Cfg})
    module('isaaclab.sensors', Camera=_Camera, CameraCfg=camera_cfg,
           FrameTransformerCfg=frame, ContactSensorCfg=_Cfg)
    class EnvCfg:
        def __init__(self):
            self.sim = _Cfg()
    module('isaaclab.envs', ManagerBasedEnvCfg=EnvCfg)
    module('isaaclab.managers', **{name: _Cfg for name in
        ('ObservationGroupCfg', 'ObservationTermCfg', 'EventTermCfg', 'SceneEntityCfg')})
    module('isaaclab.envs.mdp', joint_pos=lambda env: None, joint_vel=lambda env: None,
           image=lambda env: None)
    module('isaaclab.envs.mdp.actions', JointPositionActionCfg=_Cfg)
    module('isaaclab.utils', configclass=lambda cls: cls)
    prepared = []
    def assets(package, inputs, directory):
        prepared.append(copy.deepcopy(inputs))
        return {'static': Path(directory) / 'static.usda', 'mounted': {}, 'objects': {}}
    monkeypatch.setattr(env_cfg, 'write_scene_assets', assets)
    return prepared


def _physical_matrix(camera):
    spawn = camera.spawn
    fx = camera.width * spawn.focal_length / spawn.horizontal_aperture
    fy = camera.height * spawn.focal_length / spawn.vertical_aperture
    return np.array([[fx, 0., camera.width / 2 - spawn.horizontal_aperture_offset * fx / spawn.focal_length],
                     [0., fy, camera.height / 2 + spawn.vertical_aperture_offset * fy / spawn.focal_length],
                     [0., 0., 1.]])


@pytest.mark.parametrize('fx,fy,cx,cy', [
    (700., 700., 320., 240.), (600., 800., 320., 240.), (600., 800., 300., 210.),
], ids=['centered_square', 'centered_anisotropic', 'required_offcenter'])
def test_scene_intrinsic_reaches_actual_isaac_camera_config_without_averaging(tmp_path, config_sdk, fx, fy, cx, cy):
    expected = np.array([[fx, 0., cx], [0., fy, cy], [0., 0., 1.]])
    package, settings = _scene_with_cameras(expected)
    original = _mutable(package.scene)
    cfg = env_cfg.build_env_cfg(package, settings, runtime_directory=tmp_path / 'runtime', device='cpu')
    for name in ('side', 'wrist'):
        np.testing.assert_array_equal(config_sdk[0]['profile']['cameras'][name]['K'], expected)
        # Float64 arithmetic roundoff budget: at most a few products/divisions,
        # scaled by the exact values involved, not a hand-picked pixel tolerance.
        got = _physical_matrix(getattr(cfg.scene, 'camera_' + name))
        np.testing.assert_allclose(got, expected, rtol=8*np.finfo(float).eps, atol=0.)
        points = np.array([[0., 0., 1.], [.1, -.1, 2.], [-.2, .3, 1.5], [.5, .2, 4.]])
        projection = lambda k: (points @ k.T)[:, :2] / points[:, 2:3]
        np.testing.assert_allclose(projection(got), projection(expected), rtol=16*np.finfo(float).eps, atol=0.)
        sensor=_runtime_sensor(getattr(cfg.scene,'camera_'+name),count=1)
        np.testing.assert_array_equal(_native_matrix(sensor,0),expected)
        np.testing.assert_array_equal(sensor.data.intrinsic_matrices[0].numpy(),expected)
    assert _mutable(package.scene) == original


def test_side_and_wrist_keep_independent_k_resolution_and_optical_mount(tmp_path, config_sdk):
    side = np.array([[600., 0., 300.], [0., 800., 210.], [0., 0., 1.]])
    wrist = np.array([[470., 0., 180.], [0., 510., 120.], [0., 0., 1.]])
    package, settings = _scene_with_cameras(side, wrist, wrist_resolution=(400, 300))
    original = _mutable(package.scene)
    inputs = env_cfg.execution_inputs(package, settings)
    cfg = env_cfg.build_env_cfg(package, settings, runtime_directory=tmp_path / 'runtime', device='cpu')
    for name, expected in [('side', side), ('wrist', wrist)]:
        camera = getattr(cfg.scene, 'camera_' + name)
        assert (camera.width, camera.height) == tuple(inputs['profile']['cameras'][name]['resolution'])
        assert camera.offset.convention == 'ros'
        pose = np.eye(4)
        pose[:3, 3] = camera.offset.pos
        pose[:3, :3] = Rotation.from_quat(np.asarray(camera.offset.rot)[[1, 2, 3, 0]]).as_matrix()
        np.testing.assert_allclose(pose, inputs['profile']['cameras'][name]['T_parent_camera'], atol=8*np.finfo(float).eps)
        np.testing.assert_allclose(_physical_matrix(camera), expected, rtol=8*np.finfo(float).eps, atol=0.)
    assert '/Robot/' not in cfg.scene.camera_side.prim_path
    assert '/Robot/' in cfg.scene.camera_wrist.prim_path
    assert _mutable(package.scene) == original


@pytest.mark.parametrize('bad', ['shape', 'nan', 'inf', 'negative_fx', 'zero_fy', 'skew', 'homogeneous'])
def test_invalid_or_unsupported_scene_k_is_rejected_before_runtime_assets(tmp_path, config_sdk, bad):
    k = np.array([[700., 0., 320.], [0., 700., 240.], [0., 0., 1.]])
    if bad == 'shape': k = k[:2]
    elif bad == 'nan': k[0, 0] = np.nan
    elif bad == 'inf': k[0, 2] = np.inf
    elif bad == 'negative_fx': k[0, 0] = -700.
    elif bad == 'zero_fy': k[1, 1] = 0.
    elif bad == 'skew': k[0, 1] = 1.
    else: k[2, 2] = 2.
    package, settings = _scene_with_cameras(k)
    with pytest.raises(ValueError):
        env_cfg.build_env_cfg(package, settings, runtime_directory=tmp_path / 'runtime', device='cpu')
    assert not config_sdk


def _runtime_sensor(camera, count=2):
    """Real USD Camera/schema, actual Workbench subclass, CPU tensor buffers.

    Replace only the Kit/Replicator lifecycle. The installed Lab initializer
    calls this same _update_intrinsic_matrices hook after creating buffers.
    """
    import torch
    from pxr import Usd,UsdGeom
    stage=Usd.Stage.CreateInMemory()
    sensors=[]
    for index in range(count):
        prim=UsdGeom.Camera.Define(stage,f'/World/Camera_{index}')
        for field,attr in [('focal_length','FocalLength'),('horizontal_aperture','HorizontalAperture'),
            ('vertical_aperture','VerticalAperture'),('horizontal_aperture_offset','HorizontalApertureOffset'),
            ('vertical_aperture_offset','VerticalApertureOffset')]:
            getattr(prim,'Create'+attr+'Attr')(float(getattr(camera.spawn,field)))
        sensors.append(prim)
    sensor=object.__new__(camera.class_type)
    sensor.cfg=camera;sensor._sensor_prims=sensors;sensor._view=SimpleNamespace(count=count)
    sensor._ALL_INDICES=torch.arange(count);sensor.device=sensor._device='cpu'
    sensor._data=SimpleNamespace(intrinsic_matrices=torch.zeros(count,3,3,dtype=torch.float32))
    sensor.stage=stage
    sensor._update_intrinsic_matrices(sensor._ALL_INDICES)
    return sensor


def _native_matrix(sensor, index):
    prim=sensor._sensor_prims[index].GetPrim()
    assert prim.HasAPI('OmniLensDistortionOpenCvPinholeAPI')
    assert prim.GetAttribute('omni:lensdistortion:model').Get()=='opencvPinhole'
    prefix='omni:lensdistortion:opencvPinhole:'
    assert tuple(prim.GetAttribute(prefix+'imageSize').Get())==(sensor.cfg.width,sensor.cfg.height)
    for name in ('k1','k2','p1','p2','k3','k4','k5','k6','s1','s2','s3','s4'):
        assert prim.GetAttribute(prefix+name).Get()==0.
    return np.array([[prim.GetAttribute(prefix+'fx').Get(),0,prim.GetAttribute(prefix+'cx').Get()],
        [0,prim.GetAttribute(prefix+'fy').Get(),prim.GetAttribute(prefix+'cy').Get()],[0,0,1.]])


def test_native_schema_and_runtime_readback_preserve_both_sensor_intrinsics(tmp_path, config_sdk):
    expected={'side':np.array([[600.,0,300],[0,800,210],[0,0,1.]]),
        'wrist':np.array([[470.,0,180],[0,510,120],[0,0,1.]])}
    package,settings=_scene_with_cameras(expected['side'],expected['wrist'],wrist_resolution=(400,300))
    cfg=env_cfg.build_env_cfg(package,settings,runtime_directory=tmp_path/'runtime',device='cpu',num_envs=2)
    for name,k in expected.items():
        camera=getattr(cfg.scene,'camera_'+name)
        camera.prim_path=camera.prim_path.replace('{ENV_REGEX_NS}','/World/envs/env_.*')
        sensor=_runtime_sensor(camera)
        for index in range(2):
            np.testing.assert_array_equal(_native_matrix(sensor,index),k)
            np.testing.assert_array_equal(sensor._data.intrinsic_matrices[index].numpy(),k)
        # Same hook on subsequent Camera refresh must not restore centered K.
        sensor._update_intrinsic_matrices(sensor._ALL_INDICES)
        np.testing.assert_array_equal(sensor._data.intrinsic_matrices[0].numpy(),k)


def test_runtime_intrinsic_setter_changes_only_requested_env_and_reads_native_schema(tmp_path, config_sdk):
    import torch
    original=np.array([[600.,0,300],[0,800,210],[0,0,1.]])
    package,settings=_scene_with_cameras(original);source=_mutable(package.scene)
    cfg=env_cfg.build_env_cfg(package,settings,runtime_directory=tmp_path/'runtime',device='cpu',num_envs=2)
    sensor=_runtime_sensor(cfg.scene.camera_side)
    updated=torch.tensor([[[650.,0,285],[0,775,205],[0,0,1.]]])
    sensor.set_intrinsic_matrices(updated,focal_length=35.,env_ids=[1])
    sensor._update_intrinsic_matrices(sensor._ALL_INDICES)
    np.testing.assert_array_equal(_native_matrix(sensor,0),original)
    np.testing.assert_array_equal(_native_matrix(sensor,1),updated[0].numpy())
    np.testing.assert_array_equal(sensor._data.intrinsic_matrices[1].numpy(),updated[0].numpy())
    assert sensor._sensor_prims[0].GetFocalLengthAttr().Get()==24.
    assert sensor._sensor_prims[1].GetFocalLengthAttr().Get()==35.
    assert _mutable(package.scene)==source


@pytest.mark.parametrize('bad',['batch','nan','negative','ids'])
def test_runtime_intrinsic_setter_validates_entire_batch_before_writes(tmp_path, config_sdk,bad):
    import torch
    original=np.array([[600.,0,300],[0,800,210],[0,0,1.]])
    package,settings=_scene_with_cameras(original)
    cfg=env_cfg.build_env_cfg(package,settings,runtime_directory=tmp_path/'runtime',device='cpu',num_envs=2)
    sensor=_runtime_sensor(cfg.scene.camera_side)
    before=sensor.stage.GetSessionLayer().ExportToString();data=sensor._data.intrinsic_matrices.clone()
    matrices=torch.tensor(np.repeat(original[None],2,axis=0));ids=None
    if bad=='batch':matrices=matrices[:1]
    elif bad=='nan':matrices[1,0,2]=float('nan')
    elif bad=='negative':matrices[1,0,0]=-1.
    else:ids=[0,2]
    with pytest.raises(ValueError):sensor.set_intrinsic_matrices(matrices,env_ids=ids)
    assert sensor.stage.GetSessionLayer().ExportToString()==before
    assert torch.equal(sensor._data.intrinsic_matrices,data)


def test_native_projection_has_only_schema_float32_rounding_error(tmp_path,config_sdk):
    k=np.array([[600.1234567,0.,300.2345678],[0.,800.3456789,210.4567891],[0.,0.,1.]])
    package,settings=_scene_with_cameras(k)
    cfg=env_cfg.build_env_cfg(package,settings,runtime_directory=tmp_path/'runtime',device='cpu')
    camera=cfg.scene.camera_side;sensor=_runtime_sensor(camera,count=1)
    native=_native_matrix(sensor,0)
    np.testing.assert_array_equal(native,k.astype(np.float32).astype(float))
    points=np.array([[0.,0.,1.],[.1,-.3,2.],[-.2,.3,.5],[.5,.2,4.],[-.1,.1,.4]])
    local=np.asarray(env_cfg.execution_inputs(package,settings)['profile']['cameras']['side']['T_parent_camera'])
    # A world -> ROS optical round trip checks the same pose ordering as the
    # returned config; pinhole +Z-forward uses x/z and y/z (image y-down).
    world=points@local[:3,:3].T+local[:3,3]
    pose=np.eye(4);pose[:3,3]=camera.offset.pos
    pose[:3,:3]=Rotation.from_quat(np.asarray(camera.offset.rot)[[1,2,3,0]]).as_matrix()
    optical=(world-pose[:3,3])@pose[:3,:3]
    project=lambda matrix,xyz:(xyz@matrix.T)[:,:2]/xyz[:,2:3]
    # Exact coefficient quantization plus float64 round-trip arithmetic bounds;
    # this is not a chosen pixel-accuracy threshold or a rendered-pixel test.
    delta=np.abs(native-k)
    quantization=np.abs(points[:,:2]/points[:,2:3])*np.diag(delta)[:2]+delta[:2,2]
    arithmetic=64*np.finfo(float).eps*np.maximum(1.,np.abs(project(k,points)))
    assert np.all(np.abs(project(native,optical)-project(k,points))<=quantization+arithmetic)


def test_missing_native_schema_fails_explicitly_without_centered_fallback(tmp_path,config_sdk,monkeypatch):
    package,settings=_scene_with_cameras([[600.,0,300],[0,800,210],[0,0,1.]])
    cfg=env_cfg.build_env_cfg(package,settings,runtime_directory=tmp_path/'runtime',device='cpu')
    monkeypatch.setattr(env_cfg,'_PINHOLE_SCHEMA','UnavailablePinholeAPI')
    with pytest.raises(NotImplementedError,match='NOT_SUPPORTED'):_runtime_sensor(cfg.scene.camera_side)


def _sample_environment(cfg):
    """Actual Camera subclass/schema/buffers; fake physics state, no Kit/GPU."""
    import torch
    from robot_learning_workbench.robot.calibration import JOINTS
    class Scene(dict):
        rigid_objects={}
    scene=Scene()
    for name in ('side','wrist'):
        camera=getattr(cfg.scene,'camera_'+name);sensor=_runtime_sensor(camera,count=1)
        sensor._data.output={'rgb':torch.zeros(1,camera.height,camera.width,4,dtype=torch.uint8)}
        sensor._data.pos_w=torch.tensor([[.4,.3,.8]])
        sensor._data.quat_w_ros=torch.tensor([[1.,0.,0.,0.]])
        scene['camera_'+name]=sensor
    root=torch.tensor([[0.,0.,0.,1.,0.,0.,0.]])
    scene['robot']=SimpleNamespace(joint_names=list(JOINTS),body_names=['tool0'],
        data=SimpleNamespace(root_pose_w=root,body_link_pose_w=root[:,None,:],
            joint_pos=torch.zeros(1,6),joint_vel=torch.zeros(1,6)))
    return SimpleNamespace(scene=scene,cfg=cfg,num_envs=1,step_dt=1/30,physics_dt=1/300,
        sim=SimpleNamespace(render=lambda:None))


def test_native_camera_to_source_annotation_sample_preserves_both_full_intrinsics(tmp_path,config_sdk):
    from robot_learning_workbench.engines.isaac.state import read_sample
    side=np.array([[600.,0,300],[0,800,210],[0,0,1.]])
    wrist=np.array([[470.,0,180],[0,510,120],[0,0,1.]])
    package,settings=_scene_with_cameras(side,wrist,wrist_resolution=(400,300))
    cfg=env_cfg.build_env_cfg(package,settings,runtime_directory=tmp_path/'runtime',device='cpu')
    env=_sample_environment(cfg)
    sample=read_sample(env,0,'pre_step',0)
    for name,k in [('side',side),('wrist',wrist)]:
        np.testing.assert_array_equal(sample['cameras'][name]['K'],k)
        np.testing.assert_array_equal(sample['cameras'][name]['K'],_native_matrix(env.scene['camera_'+name],0))
        assert sample['cameras'][name]['rgb'].shape==tuple(reversed(package.scene['cameras'][name]['resolution']))+(3,)
        assert sample['cameras'][name]['quat_w_ros'].tolist()==[1.,0.,0.,0.]


def test_native_renderer_metadata_uses_sensor_pixel_grid_and_intrinsics(tmp_path,config_sdk):
    from robot_learning_workbench.robot.scene_render import NativeRenderer
    side=np.array([[600.,0,300],[0,800,210],[0,0,1.]])
    wrist=np.array([[470.,0,180],[0,510,120],[0,0,1.]])
    package,settings=_scene_with_cameras(side,wrist,wrist_resolution=(400,300))
    cfg=env_cfg.build_env_cfg(package,settings,runtime_directory=tmp_path/'runtime',device='cpu')
    renderer=object.__new__(NativeRenderer);renderer.env=_sample_environment(cfg)
    renderer.view=SimpleNamespace(verify=lambda:None,engine='isaac',scene_identity={'test':'synthetic'},source_scene={},mapping={})
    renderer.total_physics_steps=renderer.last_frame_steps=0
    renderer._advance=lambda measured:(measured.copy(),cfg.decimation)
    result=renderer.render(np.zeros(6))
    for name,k in [('side',side),('wrist',wrist)]:
        camera=result['sim_cameras'][name]
        assert camera['resolution']==list(package.scene['cameras'][name]['resolution'])
        assert result['images'][name].shape==tuple(reversed(camera['resolution']))+(3,)
        np.testing.assert_array_equal(camera['K'],k)
