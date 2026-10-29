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


def construct(plan):
    from ..recipe import _plain
    model=Path(plan.resolved_inputs['robot_model']['path']);model_hash=file_sha256(model);source=plan.resolved_inputs.get('source_robot_model')
    profiles={};specs={};devices={};memory=plan.effective_settings['execution']['device_source']=='memory'
    for role,device_key,profile_key in(('follower','device_profile','calibration_profile'),('leader','leader_device_profile','leader_calibration_profile')):
        profile=load_profile(plan.resolved_inputs[profile_key]['path'],role=role)
        if profile['urdf_sha256']!=model_hash:
            if source is None:raise ValueError('Explicit source_robot_model required for verified limit-only model binding')
            profile=profile_for_model(profile,model_hash,source_model=Path(source['path']).read_bytes(),execution_model=model.read_bytes())
        spec=_plain(plan.input_documents[device_key])
        if spec['role']!=role:raise ValueError('Wrong device role')
        profiles[role]=profile;specs[role]=spec
    bounds={n:e['limits']for n,e in joint_specs(model).items()};initial=None
    if memory:
        from .calibration import PrecisionMapper
        f=PrecisionMapper(profiles['follower']).command_limits(bounds);l=PrecisionMapper(profiles['leader']).command_limits(bounds)
        initial={n:(max(f[n][0],l[n][0])+min(f[n][1],l[n][1]))/2 for n in JOINTS}
    for role,profile in profiles.items():
        spec=specs[role]
        if memory:
            from .teleoperation import fake_device
            device=fake_device(spec,profile,initial_model_q=initial);device.read_only=True
        else:device=create_observer(spec,profile)
        devices[role]=device
    if Path(devices['leader'].bus.port).resolve()==Path(devices['follower'].bus.port).resolve():raise ValueError('Leader/Follower cannot share a serial port')
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
    return devices,cameras,bounds
