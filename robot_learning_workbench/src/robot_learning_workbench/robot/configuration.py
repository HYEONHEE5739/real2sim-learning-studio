"""Explicit device configuration binding; construction does not connect/activate."""
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..recipe import PreparedRun
    from .devices import Follower,Leader
    from scene_contract.package import ScenePackage


def observation_configuration(spec: dict):
    """Official SDK config must load exactly the selected calibration bytes."""
    from .offline import sdk_configuration
    path=Path(spec['calibration_path']);cfg=sdk_configuration(spec)
    if not path.is_absolute()or not path.is_file():raise ValueError('Explicit existing SDK calibration path required')
    if path.name!=str(cfg.id)+'.json'or Path(cfg.calibration_dir or path.parent).resolve()!=path.parent.resolve():raise ValueError('SDK config must load the explicit calibration file')
    cfg.calibration_dir=path.parent
    return cfg


def create_observer(spec: dict, profile: dict) -> 'Follower':
    """Construct a pinned SDK observation device; never connect/configure/calibrate."""
    import hashlib
    from .devices import Follower,Leader
    import copy
    spec=copy.deepcopy(spec);profile=copy.deepcopy(profile)
    if spec.get('usb_identity'):
        from .registration import resolve_serial
        port=resolve_serial(spec['usb_identity']);spec['sdk']['port']=port;profile['identity']['port']=str(Path(port).resolve())
    role=spec['role'];path=Path(spec['calibration_path'])
    if not path.is_absolute() or not path.is_file():raise ValueError('Explicit existing SDK calibration path required')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=profile['identity']['calibration_sha256']:raise ValueError('SDK calibration identity differs from Precision profile')
    cfg=observation_configuration(spec)
    if role!=profile['role'] or str(Path(cfg.port).resolve())!=profile['identity']['port']:raise ValueError('Device role/port differs from approved identity')
    if role=='follower' and cfg.id!=profile['identity']['id']:raise ValueError('Follower ID differs from approved identity')
    expected=path.name if role=='leader' else cfg.id
    if expected!=profile['identity']['id']:raise ValueError('SDK calibration filename/device identity differs')
    cls=Leader if role=='leader' else Follower
    device=cls.from_config(cfg,profile=profile,calibration_path=path,identity=profile['identity'],model_hash=profile['urdf_sha256'])
    device.usb_identity=spec.get('usb_identity')
    return device


def bind_gripper_command(device: 'Follower', scene: 'ScenePackage', calibration_id: str) -> dict:
    """Explicit command-phase evidence only; this grants no motion approval."""
    from .calibration import mapper_from_scene
    mapper=mapper_from_scene(scene,calibration_id,role='follower',phase='device_command')
    if device.profile!=mapper.profile or 'gripper'not in mapper.profile['joints']:raise ValueError('Command Calibration differs from connected motor/model mapping')
    device._command_binding_verified=True
    return {'calibration_id':calibration_id,'mapping_sha256':mapper.metadata()['sha256'],'motion_approved':False}


def create_leader(plan: 'PreparedRun') -> 'Leader':
    """Explicit SDK construction; callers must call connect/activate separately."""
    from .calibration import mapper_from_scene
    spec=plan.input_documents['device_profile']
    if set(spec)!={'calibration_id','calibration_path','sdk'}:raise ValueError('Leader profile needs calibration_id/calibration_path/sdk')
    mapper=mapper_from_scene(plan.scene,spec['calibration_id'],role='leader',phase='device_observation')
    calibration=Path(spec['calibration_path'])
    if not calibration.is_absolute():raise ValueError('Explicit absolute SDK calibration file required')
    return create_observer({'role':'leader','calibration_path':str(calibration),'sdk':dict(spec['sdk'])},mapper.profile)

