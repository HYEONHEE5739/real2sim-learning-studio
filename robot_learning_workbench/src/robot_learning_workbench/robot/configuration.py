"""Explicit device configuration binding; construction does not connect/activate."""
from pathlib import Path


def create_leader(plan):
    """Explicit SDK construction; callers must call connect/activate separately."""
    from .calibration import mapper_from_scene
    from .devices import Leader
    from lerobot.teleoperators.so101_leader.config_so101_leader import SO101LeaderConfig
    spec=plan.input_documents['device_profile']
    if set(spec)!={'calibration_id','calibration_path','sdk'}:raise ValueError('Leader profile needs calibration_id/calibration_path/sdk')
    mapper=mapper_from_scene(plan.scene,spec['calibration_id'],role='leader',phase='device_observation')
    calibration=Path(spec['calibration_path'])
    if not calibration.is_absolute():raise ValueError('Explicit absolute SDK calibration file required')
    config=SO101LeaderConfig(**dict(spec['sdk']))
    if not config.use_degrees:raise ValueError('Precision Leader requires degree-native SDK normalization')
    return Leader.from_config(config,profile=mapper.profile,
        calibration_path=calibration,identity=mapper.profile['identity'],model_hash=mapper.profile['urdf_sha256'])

