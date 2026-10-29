"""Host receipt-time Capture calculations. No acquisition, engine or writer loop."""
from collections import deque
from pathlib import Path
import copy
import time
import numpy as np
from .calibration import JOINTS, LEGACY_MAPPER, mapper_from_metadata, values

def require_capture_mapping(state):
    mapper_from_metadata(state['sim_joint_mapping'])

def to_sim(native): return LEGACY_MAPPER.calibrated_to_urdf(values(native))

def observed_positions(mapper, native, raw=None, motor_specs=None):
    """Decode real feedback without clipping; preserve raw SDK saturation evidence."""
    convert = getattr(mapper, 'calibrated_to_observation', mapper.calibrated_to_urdf)
    q = convert(native, raw=raw) if raw is not None and hasattr(mapper,'calibrated_to_observation') else convert(native)
    if raw is not None and motor_specs is not None:
        from .calibration import native_from_raw
        if set(raw) != set(JOINTS) or not np.isfinite(list(raw.values())).all():
            raise ValueError("Invalid raw feedback packet")
        entries=getattr(mapper,'profile',{}).get('joints',{})
        legacy=LEGACY_MAPPER if entries else mapper
        for n in JOINTS:
            if n in entries: continue
            spec=motor_specs[n];cal=spec['calibration']
            expected=native_from_raw(np.clip(raw[n],cal['range_min'],cal['range_max'])
                if spec['mode']=='RANGE_0_100' else raw[n],spec)
            if abs(expected-native[n])>1e-6: raise ValueError(n+': raw/native packet mismatch')
            unbounded=dict(native);unbounded[n]=native_from_raw(raw[n],spec)
            q[n]=legacy.calibrated_to_urdf(unbounded)[n]
    if set(q) != set(JOINTS) or not np.isfinite(list(q.values())).all():
        raise ValueError('Non-finite or invalid observed joint coordinates')
    return {n:float(q[n]) for n in JOINTS}

class Stability:
    def __init__(self, window_s=0.6, arm_span_deg=1.0, gripper_span=2.0, max_gap_s=0.2):
        self.window_s = window_s
        self.arm_span_deg = arm_span_deg
        self.gripper_span = gripper_span
        self.max_gap_s = max_gap_s
        self.history = deque(maxlen=600)

    def add(self, t_ns, native, tip=None):
        if not isinstance(t_ns,(int,np.integer)) or isinstance(t_ns,bool):raise ValueError('Integer host timestamp required')
        native=values(native)
        if tip is not None:
            tip=np.array(tip,dtype=float,copy=True)
            if tip.shape!=(3,) or not np.isfinite(tip).all():raise ValueError('Invalid measured tip')
        if self.history and t_ns <= self.history[-1][0]:
            raise ValueError("History timestamps must increase")
        self.history.append((t_ns, np.array([native[n] for n in JOINTS]), tip))
        while len(self.history) > 2 and (t_ns - self.history[1][0]) / 1e9 > self.window_s * 1.5:
            self.history.popleft()

    def assess(self):
        if len(self.history) < 3:
            return {"stable": False, "reason": "insufficient_history"}
        end = self.history[-1][0]
        start = end - int(self.window_s * 1e9)
        rows = list(self.history)
        before = [i for i, r in enumerate(rows) if r[0] <= start]
        if not before:
            return {"stable": False, "reason": "warming_up"}
        rows = rows[before[-1] :]
        gaps = np.diff([r[0] for r in rows]) / 1e9
        span = np.ptp(np.array([r[1] for r in rows]), axis=0)
        tips = [r[2] for r in rows if r[2] is not None]
        tip_span = max(np.linalg.norm(np.asarray(tips) - np.median(tips, axis=0), axis=1)) * 1000 if tips else None
        stable = bool(
            max(gaps) <= self.max_gap_s and max(span[:-1]) <= self.arm_span_deg and span[-1] <= self.gripper_span
        )
        return {
            "stable": stable,
            "window_start_ns": rows[0][0],
            "window_end_ns": end,
            "max_gap_ms": float(max(gaps) * 1000),
            "arm_span_deg": float(max(span[:-1])),
            "gripper_span_percentage_points": float(span[-1]),
            "sim_tip_spread_mm": float(tip_span) if tip_span is not None else None,
            "thresholds": {
                "window_s": self.window_s,
                "arm_span_deg": self.arm_span_deg,
                "gripper_span": self.gripper_span,
                "max_gap_s": self.max_gap_s,
            },
            "reason": "stable" if stable else "motion_or_sampling_gap",
        }

def align_measured(samples, timestamp, max_skew_ns=100_000_000, mapper=None, observation_only=False, motor_specs=None):
    """Interpolate measured arm values; gripper is held from the last sample."""
    if not samples:
        raise ValueError('Measured joint history missing')
    times = np.asarray([s['timestamp_ns'] for s in samples], dtype=np.int64)
    if np.any(np.diff(times) <= 0):
        raise ValueError('Measured timestamps must increase')
    def measured(sample):
        if mapper:
            return observed_positions(mapper,sample['native'],raw=sample.get('raw'),motor_specs=motor_specs)
        return to_sim(sample['native'])
    positions = np.asarray([[measured(s)[n] for n in JOINTS] for s in samples])
    right = int(np.searchsorted(times, timestamp))
    if right < len(times) and times[right] == timestamp:
        return positions[right].tolist()
    if right == 0 or right == len(times):
        index = 0 if right == 0 else len(times) - 1
        if abs(int(times[index]) - timestamp) > max_skew_ns:
            raise ValueError('Image/joint timestamp skew exceeds 100 ms')
        return positions[index].tolist()
    left = right - 1
    if max(timestamp - int(times[left]), int(times[right]) - timestamp) > max_skew_ns:
        raise ValueError('Measured interpolation gap exceeds 100 ms')
    alpha = (timestamp - times[left]) / float(times[right] - times[left])
    q = positions[left] * (1 - alpha) + positions[right] * alpha
    q[-1] = positions[left, -1]
    return q.tolist()

def render_k(camera):
    # Isaac Lab 2.3 pinhole limitation: use centred square-pixel virtual camera.
    # Real images are rectified to this same K for appearance comparisons.
    w, h = camera["resolution"]
    k = np.asarray(camera["K"], float)
    f = float((k[0, 0] + k[1, 1]) / 2)
    return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])

def assess_pair(
    frames,
    sim_stamp,
    follower_interval,
    real_stability,
    sim_stability,
    error,
    now_ns,
    max_skew_ms=100.0,
    max_age_ms=200.0,
    max_arm_error_rad=0.035,
    max_gripper_error=2.0,
):
    numeric=[max_skew_ms,max_age_ms,max_arm_error_rad,max_gripper_error]
    if error is not None:numeric += [error['max_arm_error_rad'],error['gripper_error_percentage_points']]
    if not np.isfinite(numeric).all() or min(numeric)<0:raise ValueError('Finite nonnegative pairing values required')
    for packet in frames.values():
        if packet is not None and not packet['read_start']['monotonic_ns']<=packet['read_end']['monotonic_ns']<=now_ns:
            raise ValueError('Invalid camera read interval')
    reasons = []
    timing = {}
    stamps = [sim_stamp["monotonic_ns"]]
    for name in ("real_side", "real_wrist"):
        f = frames.get(name)
        if f is None:
            reasons.append("missing_" + name)
            continue
        t = f["read_end"]["monotonic_ns"]
        stamps.append(t)
        timing[name] = {
            "receive_minus_sim_ms": (t - sim_stamp["monotonic_ns"]) / 1e6,
            "age_ms": (now_ns - t) / 1e6,
            "timestamp_kind": "host_read_completion_not_exposure",
            "exposure_timestamp": None,
        }
        if now_ns - t > max_age_ms * 1e6:
            reasons.append("stale_" + name)
        if abs(t - sim_stamp["monotonic_ns"]) > max_skew_ms * 1e6:
            reasons.append("skew_" + name)
        if (
            real_stability.get("window_start_ns", now_ns) > f["read_start"]["monotonic_ns"]
            or real_stability.get("window_end_ns", 0) < t
        ):
            reasons.append("frame_not_covered_by_stability_" + name)
    if follower_interval:
        rt = follower_interval["end"]["monotonic_ns"]
        stamps.append(rt)
        timing["follower_read_minus_sim_ms"] = (rt - sim_stamp["monotonic_ns"]) / 1e6
        timing["follower_read_duration_ms"] = (rt - follower_interval["start"]["monotonic_ns"]) / 1e6
        if now_ns - rt > max_age_ms * 1e6 or timing["follower_read_duration_ms"] > max_skew_ms:
            reasons.append("follower_measurement_stale_or_slow")
    else:
        reasons.append("no_physical_follower_measurement")
    spread = (max(stamps) - min(stamps)) / 1e6
    if spread > max_skew_ms:
        reasons.append("observation_time_spread")
    if now_ns - sim_stamp["monotonic_ns"] > max_age_ms * 1e6:
        reasons.append("stale_sim")
    if not real_stability.get("stable"):
        reasons.append("physical_follower_not_stable")
    if not sim_stability.get("stable"):
        reasons.append("sim_not_stable")
    if error is None:
        reasons.append("joint_error_unavailable")
    elif error["max_arm_error_rad"] > max_arm_error_rad or error["gripper_error_percentage_points"] > max_gripper_error:
        reasons.append("real_sim_joint_error")
    return {
        "hardware_synchronized": False,
        "eligible_for_calibration": not reasons,
        "reasons": reasons,
        "observation_time_spread_ms": spread,
        "timing": timing,
        "thresholds": {
            "max_skew_ms": max_skew_ms,
            "max_age_ms": max_age_ms,
            "max_arm_error_rad": max_arm_error_rad,
            "max_gripper_error_percentage_points": max_gripper_error,
        },
        "limitation": "Software pairing of host receipt times only; USB exposure/buffering latency is unknown. Eligibility is a heuristic, not proof of geometric calibration.",
    }

def blur_variance(rgb: np.ndarray) -> float:
    """Existing Laplacian texture heuristic; never a Calibration approval."""
    import cv2
    return float(cv2.Laplacian(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY),cv2.CV_64F).var())

def prepare_snapshot(state, images, profile, now_ns=None):
    """Validate and freeze one whole observation before publishing any files."""
    state=copy.deepcopy(state)
    now_ns = state.get('captured_host_ns', time.monotonic_ns()) if now_ns is None else now_ns
    if set(images) != {'real_side', 'real_wrist'}:
        raise ValueError('Both real Side/Wrist frames are required; retry Capture')
    if state.get('joint_names') != list(JOINTS):
        raise ValueError('Measured joint names/order mismatch')
    if not state.get('sim_joint_mapping'):
        raise ValueError('Snapshot requires explicit joint mapping metadata')
    require_capture_mapping(state)
    from .calibration import mapper_from_metadata
    mapper = mapper_from_metadata(state['sim_joint_mapping'])
    convert = mapper.calibrated_to_urdf
    observation_only = state.get('precision_observation_only') is True
    if observation_only:
        if state.get('sent_target') is not None: raise ValueError('Passive capture must not contain a motor command')
    raw=(state.get('precision_raw_feedback') or {}).get('follower')
    motor_specs=state.get('hardware',{}).get('follower',{}).get('motor_specs')
    q = observed_positions(mapper,state['physical_follower_measured_joint_state'],raw=raw,motor_specs=motor_specs)
    samples = copy.deepcopy(state.get('measured_samples', []))
    feedback_time = state['timestamps']['follower']['end']['monotonic_ns']
    if not samples or samples[-1]['timestamp_ns'] != feedback_time:
        raise ValueError('Latest measured feedback missing from history')
    if not np.allclose([q[n] for n in JOINTS], align_measured(samples, feedback_time, mapper=mapper, observation_only=observation_only, motor_specs=motor_specs), atol=1e-8):
        raise ValueError('Measured feedback/history mismatch')
    if now_ns - feedback_time > 200_000_000 or feedback_time > now_ns:
        raise ValueError('Measured joint feedback is stale')
    stability = state.get('real_stability', {})
    if not stability.get('stable'):
        raise ValueError('Robot pose is moving or feedback is warming up; hold still and retry')
    warnings = []
    joint_limit_warnings = copy.deepcopy(state.get('joint_limit_warnings', {})) or {n: {'measured_rad':q[n], 'limits_rad':entry['limits']}
                           for n,entry in getattr(mapper, 'profile', {}).get('joints', {}).items()
                           if not entry['limits'][0]-1e-6 <= q[n] <= entry['limits'][1]+1e-6}
    for n,detail in joint_limit_warnings.items():
        warnings.append(f'{n}: measured {np.degrees(detail["measured_rad"]):.2f} deg outside URDF limits; original measurement retained')
    observed = []
    for name in ('side', 'wrist'):
        rgb = images['real_' + name]
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError('Real camera must provide RGB uint8')
        if list(rgb.shape[1::-1]) != profile['cameras'][name]['resolution']:
            raise ValueError('Original image resolution differs from pixel calibration')
        packet = state['timestamps']['real_cameras']['real_' + name]
        t = packet['read_end']['monotonic_ns']
        start = packet['read_start']['monotonic_ns']
        if not start <= t <= now_ns or now_ns - t > 200_000_000:
            raise ValueError(name + ' camera frame is stale; retry Capture')
        if abs(t - feedback_time) > 100_000_000:
            raise ValueError(name + ' image/joint timestamp skew exceeds 100 ms')
        if start < stability['window_start_ns'] or t > stability['window_end_ns']:
            raise ValueError(name + ' frame is not covered by stable measured feedback')
        blur = blur_variance(rgb)
        if blur < 10:
            warnings.append(name + ': blurred or textureless image; excluded from calibration')
        observed.append({'camera': name, 'path': name + '.png', 'timestamp_ns': t,
                         'read_start_ns': start, 'sequence': packet['sequence'],
                         'resolution': list(rgb.shape[1::-1]), 'blur_variance': blur,
                         'q_measured': align_measured(samples, t, mapper=mapper, observation_only=observation_only, motor_specs=motor_specs),
                         'joint_skew_ns': t - feedback_time, 'eligible': blur >= 10,
                         'timestamp_kind': 'host_read_interval_not_exposure'})
    # Read the recorded applied q of historical snapshots, without generating
    # that retired controller's metadata in new snapshots.
    command = (state.get('joint_control',{}).get('applied_joint_rad') or convert(state['sent_target'])) if state.get('sent_target') is not None else None
    measured = {'timestamp_ns': feedback_time, 'q_measured': [q[n] for n in JOINTS],
                'q_native': state['physical_follower_measured_joint_state'],
                'q_command': [command[n] for n in JOINTS] if command else None,
                'command_timestamp_ns': state['timestamps']['send']['end']['monotonic_ns'] if command else None,
                'captured_host_ns': now_ns,
                'measured_samples': [{**a,'q_measured':align_measured([a],a['timestamp_ns'],mapper=mapper,observation_only=observation_only,motor_specs=motor_specs)} for a in samples], 'timestamps': state['timestamps'], 'real_stability': stability,
                'precision_raw_feedback': state.get('precision_raw_feedback'), 'tracking': state.get('tracking'),
                'precision_run_configuration': state.get('precision_run_configuration', {})}
    measured.update(precision_observation_only=observation_only, joint_limit_warnings=joint_limit_warnings,
                    sim_pose_matches_measured=state.get('sim_pose_matches_measured'))
    measured.update(mapping_sha256=state['sim_joint_mapping']['sha256'],
                    model_sha256=mapper.profile['urdf_sha256'],joint_order=list(JOINTS),
                    model_units=['rad']*6,hardware_synchronized=False)
    return measured, observed, warnings


def snapshot_state(device, history, packets, stability):
    """Project an owned feedback window into the existing Snapshot contract."""
    start=stability.get('window_start_ns',history[0]['timestamp_ns']);history=[r for r in history if r['timestamp_ns']>=start]
    last=history[-1];q=observed_positions(device.precision_mapper,last['native'],raw=last['raw'],motor_specs=device.motor_specs)
    return dict(captured_host_ns=time.monotonic_ns(),joint_names=list(JOINTS),sim_joint_mapping=device.precision_mapper.metadata(),precision_observation_only=True,sent_target=None,
        physical_follower_measured_joint_state=last['native'],physical_q_measured=[q[n]for n in JOINTS],precision_raw_feedback={'follower':last['raw']},
        hardware={'follower':{'motor_specs':device.motor_specs,'identity':device.identity}},measured_samples=[{k:r[k]for k in('timestamp_ns','native','raw')}for r in history],
        real_stability=stability,timestamps={'follower':last['feedback_interval'],'real_cameras':{'real_'+n:{k:p[k]for k in('read_start','read_end','sequence')}for n,p in packets.items()}})


def share_model(root, model):
    """Share the existing portable model closure; never mutate source assets."""
    import os,hashlib,xml.etree.ElementTree as ET
    root=Path(root);model=Path(model).resolve()
    dependencies=set()
    def visit(path):
        path=path.resolve()
        if not path.is_file():raise ValueError('Missing model dependency: '+str(path))
        if path in dependencies:return
        dependencies.add(path)
        if path==model or path.suffix.lower()=='.urdf':
            for node in ET.parse(path).iter():
                reference=node.get('filename') or node.get('file')
                if reference:
                    if Path(reference).is_absolute() or '://'in reference:raise ValueError('Portable relative model dependencies required')
                    visit(path.parent/reference)
    visit(model)
    common=Path(os.path.commonpath([str(p.parent)for p in dependencies]));files={}
    for source in dependencies:
        relative=Path("model")/source.relative_to(common);target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        os.link(source,target);files[relative.as_posix()]=hashlib.sha256(target.read_bytes()).hexdigest()
    return (Path("model")/model.relative_to(common)).as_posix(),files


def save_session(root: Path|str, *, model: Path|str, mapping: dict, samples: list, images: list, metadata: dict, scene=None) -> Path:
    """Publish the existing Builder real2sim.capture/1 format, not a second Dataset.

    Only measured observations are written. No action labels are inferred from q.
    Model dependencies share immutable files; original model bytes stay unchanged.
    """
    from pathlib import Path
    import os,hashlib,json
    import xml.etree.ElementTree as ET
    from PIL import Image
    from ..data.native import atomic_json
    from real2sim_builder.capture import load_session
    root=Path(root);model=Path(model).resolve()
    reserved={'schema','session_id','group_id','split','purpose','clock','joint_names','joint_units','q_measured_source','joint_mapping','source_robot_sha256','robot','cameras','samples','events','files','quality'}
    if reserved&metadata.keys():raise ValueError('Capture metadata cannot override reserved measurement/identity fields')
    if not samples or len(samples)!=len(images):raise ValueError('Aligned nonempty samples/images required')
    root.mkdir();destination=root;root=destination/'.pending';root.mkdir()
    model_relative,files=share_model(root,model);rows=copy.deepcopy(samples)
    previous=-1
    for index,(row,frames)in enumerate(zip(rows,images)):
        q=np.asarray(row['q_measured']);t=row['timestamp_ns']
        if q.shape!=(6,) or not np.isfinite(q).all() or t<=previous or set(frames)!={'side','wrist'}:raise ValueError('Invalid measured sample/image ordering')
        previous=t;row['images']=[]
        row['quality']={'eligible_for_calibration':False,'reason':'observation recording; independent static/calibration approval absent'}
        for camera,rgb in frames.items():
            if rgb.dtype!=np.uint8 or rgb.shape!=(480,640,3):raise ValueError('640x480 uint8 original RGB required')
            relative=f'images/{index:08d}-{camera}.png';target=root/relative;target.parent.mkdir(exist_ok=True)
            Image.fromarray(rgb).save(target);files[relative]=hashlib.sha256(target.read_bytes()).hexdigest()
            timing=row.get('camera_timing',{}).get(camera,{})
            row['images'].append(dict(camera=camera,blur_variance=blur_variance(rgb),path=relative,resolution=[640,480],sequence=timing.get('sequence',index),timestamp_ns=timing.get('timestamp_ns',t),eligible=timing.get('eligible',True) and row.get('stability',{}).get('stable',True),joint_skew_ns=timing.get('joint_skew_ns',0)))
    atomic_json(root/'samples.json',rows);atomic_json(root/'events.json',[])
    for name in ('samples.json','events.json'):files[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    manifest=dict(schema='real2sim.capture/1',session_id=destination.name.replace('-','_'),group_id=destination.name.replace('-','_'),split='train',purpose='demonstration',
        clock=dict(domain='host_monotonic_ns',hardware_synchronized=False,timestamp_kind='host_receipt_not_exposure'),
        joint_names=list(JOINTS),joint_units=['rad']*6,q_measured_source='physical_follower_feedback_converted_to_model',
        joint_mapping=mapping,source_robot_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        robot=dict(path=model_relative,mapping_verified=False),
        cameras=[dict(id=n,resolution=[640,480],color='rgb')for n in ('side','wrist')],samples='samples.json',events='events.json',files=files,
        quality=dict(incomplete=False),**metadata)
    if scene is not None:
        from scene_contract.transforms import resolve_transform
        frames=scene.scene['frames']
        manifest['robot'].update(format='urdf',T_world_base=resolve_transform(frames,source='robot_base',target='world').tolist(),base_provenance={'T_world':'inherited_scene_unverified'})
        manifest['cameras']=[]
        for name in ('side','wrist'):
            camera=scene.scene['cameras'][name];frame=frames[camera['frame_id']];parent=frame['parent']
            if parent not in ('world','robot_base') and not parent.startswith('robot_link_'):raise ValueError('Explicit Scene camera mount link required')
            manifest['cameras'].append(dict(id=name,parent=parent.removeprefix('robot_link_'),resolution=list(camera['resolution']),K=copy.deepcopy(camera['K']),
                distortion=copy.deepcopy(camera.get('distortion')),T_parent_camera=copy.deepcopy(frame['T_parent_from_frame']),
                provenance={key:'inherited_scene_unverified'for key in ('K','distortion','T_parent_camera')}))
    atomic_json(root/'capture_manifest.yaml',manifest)
    (root/'COMPLETE').write_text('complete\n')
    try:load_session(root)
    except BaseException:
        (root/'COMPLETE').unlink()
        raise
    for child in root.iterdir():
        if child.name!='COMPLETE':os.replace(child,destination/child.name)
    os.replace(root/'COMPLETE',destination/'COMPLETE');root.rmdir()
    return destination
