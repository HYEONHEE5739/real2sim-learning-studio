"""Concrete continuous-session device construction; never connect on import/prepare."""
from pathlib import Path
import time
import numpy as np
from .calibration import JOINTS,load_profile,profile_for_model,joint_specs,raw_from_native
from .configuration import create_observer
from .devices import CameraReader
from ..data.native import file_sha256


class MemoryCamera:
    """Explicit test source, visibly declared synthetic; no camera SDK constructor."""
    def __init__(self,name):
        self.is_connected=False;grid=np.indices((480,640)).sum(0)
        self.image=np.stack([(grid%24<12)*180,grid%255,np.full_like(grid,64 if name=='side'else 180)],axis=2).astype(np.uint8)
    def connect(self):self.is_connected=True
    def disconnect(self):self.is_connected=False
    def read(self):time.sleep(1/30);return self.image.copy()


def binding(plan,role):
    from ..recipe import _plain
    device_key,profile_key=('device_profile','calibration_profile')if role=='follower'else('leader_device_profile','leader_calibration_profile')
    model=Path(plan.resolved_inputs['robot_model']['path']);model_hash=file_sha256(model);source=plan.resolved_inputs.get('source_robot_model')
    profile=load_profile(plan.resolved_inputs[profile_key]['path'],role=role)
    if profile['urdf_sha256']!=model_hash:
        if source is None:raise ValueError('Explicit source_robot_model required for verified limit-only model binding')
        profile=profile_for_model(profile,model_hash,source_model=Path(source['path']).read_bytes(),execution_model=model.read_bytes())
    spec=_plain(plan.input_documents[device_key])
    if spec['role']!=role:raise ValueError('Wrong device role')
    return spec,profile


def device(spec,profile,memory,initial=None,*,memory_port=None):
    if memory:
        import copy
        spec=copy.deepcopy(spec);profile=copy.deepcopy(profile)
        spec['sdk']['port']=str(memory_port);profile['identity']['port']=str(Path(memory_port).resolve())
        from .teleoperation import fake_device
        result=fake_device(spec,profile,initial_model_q=initial);result.read_only=True
    else:result=create_observer(spec,profile)
    return result


def construct(plan):
    from .calibration import PrecisionMapper
    model=Path(plan.resolved_inputs['robot_model']['path']);bounds={n:e['limits']for n,e in joint_specs(model).items()}
    memory=plan.effective_settings['execution']['device_source']=='memory'
    roles=('leader','follower')if 'leader_device_profile'in plan.resolved_inputs else('follower',)
    bindings={r:binding(plan,r)for r in roles};initial=None
    if memory:
        limits={r:PrecisionMapper(p).command_limits(bounds)for r,(_,p)in bindings.items()}
        initial={n:(max(limits[r][n][0]for r in roles)+min(limits[r][n][1]for r in roles))/2 for n in JOINTS}
    devices={r:device(spec,profile,memory,initial,memory_port=plan.output_path/('memory-'+r))for r,(spec,profile)in bindings.items()}
    if len({Path(d.bus.port).resolve()for d in devices.values()})!=len(devices):raise ValueError('Leader/Follower cannot share a serial port')
    return devices,construct_cameras(plan),bounds


def construct_cameras(plan):
    from ..recipe import _plain
    memory=plan.effective_settings['execution']['device_source']=='memory'
    configs=_plain(plan.input_documents['camera_config'])['cameras']
    if set(configs)!={'side','wrist'}:raise ValueError('Both Side/Wrist camera definitions required')
    paths=[];cameras={}
    for name,settings in configs.items():
        from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
        cfg=OpenCVCameraConfig(**settings)
        if(cfg.width,cfg.height,cfg.fps)!=(640,480,30):raise ValueError('Capture requires original640x480 RGB at requested30Hz')
        paths.append(str(Path('/dev/video'+str(cfg.index_or_path)if isinstance(cfg.index_or_path,int)else cfg.index_or_path).resolve()))
        cameras[name]=CameraReader(MemoryCamera(name),device='memory:'+name)if memory else CameraReader.from_config(cfg)
        cameras[name].metadata['synthetic_input']=memory
    if len(set(paths))!=2:raise ValueError('Side/Wrist cannot share a camera device')
    return cameras
