"""SO101 encoder/model arithmetic and explicit immutable model evidence.

Homed raw positions already include Homing_Offset; no device, Git, engine or active
profile lookup is performed by this module. Source: original Precision Calibration.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
from dataclasses import dataclass, asdict
from collections.abc import Mapping
import xml.etree.ElementTree as ET
import numpy as np

JOINTS = ('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper')
SCHEMA = 'so101.precision-calibration/1'
MAPPING = 'so101.precision-joint-mapping/1'

def values(data):
    """A complete finite scalar packet in authoritative joint order."""
    if not isinstance(data, Mapping) or set(data) != set(JOINTS): raise ValueError('Expected exact SO101 joints')
    if any(isinstance(v, (str, bool, np.bool_)) or not np.isscalar(v) or not np.isreal(v) for v in data.values()):
        raise ValueError('Expected real numeric joint values')
    out = {n:float(data[n]) for n in JOINTS}
    if not all(math.isfinite(v) for v in out.values()): raise ValueError('Nonfinite joint packet')
    return out

@dataclass(frozen=True)
class SO101SimJointMapper:
    arm_sign: tuple = (1, 1, 1, 1, 1)
    arm_zero_offset_rad: tuple = (0., 0., 0., 0., 0.)
    # Separate percent coordinate: preserve the legacy 0% -> 0rad, 100% -> 100deg.
    gripper_rad_per_percent: float = math.pi / 180
    gripper_zero_offset_rad: float = 0.
    evidence: str = 'legacy_unverified'
    version: str = 'so101.sim-joint-mapping/1'

    def __post_init__(self):
        object.__setattr__(self, 'arm_sign', tuple(self.arm_sign))
        object.__setattr__(self, 'arm_zero_offset_rad', tuple(self.arm_zero_offset_rad))
        if len(self.arm_sign) != 5 or any(s not in (-1, 1) for s in self.arm_sign):
            raise ValueError('Exactly five arm signs (+1/-1) required')
        if len(self.arm_zero_offset_rad) != 5 or not np.isfinite(self.arm_zero_offset_rad).all():
            raise ValueError('Exactly five finite arm offsets required')
        if not math.isfinite(self.gripper_rad_per_percent) or self.gripper_rad_per_percent == 0:
            raise ValueError('Gripper percent mapping must be finite and invertible')
        if not math.isfinite(self.gripper_zero_offset_rad):
            raise ValueError('Finite gripper offset required')
        if not self.evidence:
            raise ValueError('Mapping evidence/status required')

    def _input(self, values):
        named = isinstance(values, Mapping)
        if named:
            if set(values) != set(JOINTS):
                raise ValueError('Expected exact SO101 joint names')
            values = [values[n] for n in JOINTS]
        a = np.asarray(values, dtype=np.float64)
        if a.ndim < 1 or a.shape[-1] != 6 or not np.isfinite(a).all():
            raise ValueError('Expected finite (..., 6) joint coordinates')
        return a, named

    @staticmethod
    def _output(a, named):
        return dict(zip(JOINTS, a.tolist())) if named else a

    def calibrated_to_urdf(self, values):
        a, named = self._input(values)
        out = np.empty_like(a)
        out[..., :5] = a[..., :5] * (math.pi / 180) * self.arm_sign + self.arm_zero_offset_rad
        out[..., 5] = a[..., 5] * self.gripper_rad_per_percent + self.gripper_zero_offset_rad
        return self._output(out, named)

    def urdf_to_calibrated(self, values):
        a, named = self._input(values)
        out = np.empty_like(a)
        out[..., :5] = (a[..., :5] - self.arm_zero_offset_rad) / self.arm_sign * (180 / math.pi)
        out[..., 5] = (a[..., 5] - self.gripper_zero_offset_rad) / self.gripper_rad_per_percent
        return self._output(out, named)

    def metadata(self):
        spec = {**asdict(self), 'joint_order': list(JOINTS),
                'input': 'arm_calibration_relative_degree; gripper_percent', 'output': 'urdf_joint_radian'}
        encoded = json.dumps(spec, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        return {**json.loads(encoded), 'sha256': hashlib.sha256(encoded).hexdigest()}

LEGACY_MAPPER = SO101SimJointMapper()

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def joint_specs(urdf):
    result = {}
    for joint in ET.parse(urdf).findall('joint'):
        name = joint.get('name')
        if name not in JOINTS: continue
        origin, limit = joint.find('origin'), joint.find('limit')
        result[name] = dict(parent=joint.find('parent').get('link'), child=joint.find('child').get('link'),
            axis=list(map(float, joint.find('axis').get('xyz').split())),
            origin_xyz=list(map(float, origin.get('xyz', '0 0 0').split())),
            origin_rpy=list(map(float, origin.get('rpy', '0 0 0').split())),
            limits=[float(limit.get('lower')), float(limit.get('upper'))])
    if set(result) != set(JOINTS): raise ValueError('Expected the six named SO-101 URDF joints')
    return result

def raw_from_native(native, spec):
    cal = spec['calibration']; lo, hi = cal['range_min'], cal['range_max']
    if hi <= lo: raise ValueError('Invalid motor range')
    if spec['mode'] == 'DEGREES': return native * (spec['resolution'] - 1) / 360 + (lo + hi) / 2
    if spec['mode'] != 'RANGE_0_100': raise ValueError('Unsupported normalization')
    value = 100 - native if spec['apply_drive_mode'] and cal['drive_mode'] else native
    return lo + value * (hi - lo) / 100

def native_from_raw(raw, spec):
    cal = spec['calibration']; lo, hi = cal['range_min'], cal['range_max']
    if hi <= lo: raise ValueError('Invalid motor range')
    if spec['mode'] == 'DEGREES': return (raw - (lo + hi) / 2) * 360 / (spec['resolution'] - 1)
    if spec['mode'] != 'RANGE_0_100': raise ValueError('Unsupported normalization')
    value = (raw - lo) * 100 / (hi - lo)
    return 100 - value if spec['apply_drive_mode'] and cal['drive_mode'] else value

def unwrap(raw, anchor, period):
    delta = (raw - anchor + period / 2) % period - period / 2
    if abs(abs(delta) - period / 2) < 2: raise ValueError('Ambiguous half-turn encoder wrap; add closer references')
    return anchor + delta

def joint_raw_limits(entry):
    """Inverse URDF bounds, separate from the observed reference raw_domain."""
    return sorted(entry['anchor_raw'] + (q-entry['reference_angle_rad'])/entry['rad_per_count']
                  for q in entry['limits'])

def joint_raw_coordinate(entry, raw):
    """Resolve the encoder branch using URDF bounds, never the taught interval."""
    raw = float(raw)
    if not math.isfinite(raw): raise ValueError('Nonfinite motor position')
    lo, hi = joint_raw_limits(entry)
    period = entry['motor']['resolution']
    margin = 1e-6 / abs(entry['rad_per_count'])
    first = math.ceil((lo-margin-raw)/period)
    last = math.floor((hi+margin-raw)/period)
    if first > last: raise ValueError('Position outside URDF limits')
    if first != last: raise ValueError('Ambiguous encoder branch within URDF limits')
    return raw + first*period

def joint_angle(entry, raw):
    x = joint_raw_coordinate(entry, raw)
    return entry['rad_per_count']*(x-entry['anchor_raw']) + entry['reference_angle_rad']

def fit_joint(references, spec, joint, limits, reference_mode='angle'):
    if not references: raise ValueError('Record a reference first')
    if reference_mode not in ('angle', 'legacy_endpoints'): raise ValueError('Unknown reference mode')
    if spec['resolution']<=1 or spec['calibration']['range_max']<=spec['calibration']['range_min']:
        raise ValueError('Invalid encoder resolution/range')
    for ref in references:
        if ref['joint']!=joint or ref['split'] not in ('train','validation'): raise ValueError('Reference joint/split mismatch')
        if not np.isfinite([ref['raw'], ref['angle_rad']]).all(): raise ValueError('Nonfinite reference')
        if not limits[0] <= ref['angle_rad'] <= limits[1]: raise ValueError('Reference outside URDF limit')
        if ref['calibration_hash'] != spec['calibration_hash']: raise ValueError('Motor calibration changed')
    train = [r for r in references if r['split'] == 'train']
    if not train: raise ValueError('Training references missing')
    anchor = train[0]['raw']; period = spec['resolution']
    x = np.array([unwrap(r['raw'], anchor, period) for r in train], float)
    y = np.array([r['angle_rad'] for r in train], float)
    fallback = math.pi / 180 if joint != 'gripper' else LEGACY_MAPPER.gripper_rad_per_percent
    slope = fallback * (native_from_raw(anchor + 1, spec) - native_from_raw(anchor, spec))
    status = 'OFFSET_ONLY_NEEDS_MORE_DATA'
    if len(train) >= 2:
        if np.ptp(x) < 20 or np.ptp(y) < math.radians(5): raise ValueError('References are not distinct enough')
        if np.ptp(x) >= period / 2: raise ValueError('Encoder branch ambiguous; use closer references')
        slope, intercept = np.linalg.lstsq(np.c_[x - anchor, np.ones(len(x))], y, rcond=None)[0]
        if abs(slope) < 1e-8 or not .1 <= abs(slope) / (2 * math.pi / period) <= 5:
            raise ValueError('Implausible angle scale')
        status = 'CANDIDATE_NEEDS_VALIDATION'
    else: intercept = float(y[0])
    if joint == 'gripper' and reference_mode == 'legacy_endpoints':
        labels = {r.get('reference_kind') for r in train}
        openings = [r.get('opening_m') for r in train]
        if not {'closed', 'open'} <= labels or any(v is None or not np.isfinite(v) or v < 0 for v in openings):
            status = 'NEEDS_MORE_DATA_GRIPPER_ENDPOINTS'
        elif max(openings) - min(openings) < .002: raise ValueError('Distinct measured opening endpoints required')
    errors = [float(slope * (unwrap(r['raw'], anchor, period) - anchor) + intercept - r['angle_rad']) for r in references]
    unwrapped = [unwrap(r['raw'], anchor, period) for r in references]
    if max(unwrapped) - min(unwrapped) >= period / 2: raise ValueError('Wrap branch spans half-turn; ambiguous')
    return dict(status=status, anchor_raw=anchor, reference_angle_rad=float(intercept), rad_per_count=float(slope),
        direction=1 if slope > 0 else -1, raw_domain=[float(min(unwrapped)), float(max(unwrapped))],
        zero_raw_unwrapped=float(anchor - intercept / slope), limits=list(limits),
        train_rmse_rad=float(np.sqrt(np.mean(np.square([e for r, e in zip(references, errors) if r['split'] == 'train'])))),
        errors_rad=errors, references=copy.deepcopy(references), motor=copy.deepcopy(spec),
        reference_mode=reference_mode, evidence='estimated/manual', physical_verified=False)

def validate_joint(entry, tolerance_deg=2.):
    """Recheck evidence in existing VALIDATED_MANUAL profiles, not a worker action."""
    tolerance = math.radians(float(tolerance_deg))
    if not 0 < tolerance <= math.radians(5): raise ValueError('Tolerance must be >0 and <=5 degrees')
    rebuilt = fit_joint(entry['references'], entry['motor'], entry['references'][0]['joint'], entry['limits'],
                        entry.get('reference_mode','legacy_endpoints'))
    if rebuilt['status'] != 'CANDIDATE_NEEDS_VALIDATION': return {**rebuilt, 'status': 'NEEDS_MORE_DATA'}
    held = [r for r in rebuilt['references'] if r['split'] == 'validation']
    train = [r for r in rebuilt['references'] if r['split'] == 'train']
    if not held or any(min(abs(unwrap(r['raw'], t['raw'], entry['motor']['resolution']) - t['raw']) for t in train) < 10
                       or min(abs(r['angle_rad']-t['angle_rad']) for t in train)<math.radians(2) for r in held):
        return {**rebuilt, 'status': 'NEEDS_MORE_DATA', 'reason': 'Record a separate, distinct validation pose'}
    held_errors = [abs(e) for r, e in zip(rebuilt['references'], rebuilt['errors_rad']) if r['split'] == 'validation']
    passed = max(held_errors) <= tolerance and rebuilt['train_rmse_rad'] <= tolerance
    return {**rebuilt, 'status': 'VALIDATED_MANUAL' if passed else 'NEEDS_MORE_DATA',
        'validation': dict(passed=passed, tolerance_deg=tolerance_deg, max_error_deg=math.degrees(max(held_errors)),
                           scope='held-out manual reference; HARDWARE_NOT_TESTED by automated suite')}

def review_joint(entry, tolerance_deg=.5):
    """Enable manual live review; check fit residuals, not independent accuracy."""
    tolerance = float(tolerance_deg)
    if not np.isfinite(tolerance) or not 0 < tolerance <= 5:
        raise ValueError('Tolerance must be >0 and <=5 degrees')
    rebuilt = fit_joint(entry['references'], entry['motor'], entry['references'][0]['joint'], entry['limits'],
                        entry.get('reference_mode','legacy_endpoints'))
    errors = [abs(math.degrees(e)) for r,e in zip(rebuilt['references'], rebuilt['errors_rad']) if r['split']=='train']
    maximum = max(errors)
    supported = rebuilt['status'] in ('CANDIDATE_NEEDS_VALIDATION', 'OFFSET_ONLY_NEEDS_MORE_DATA')
    passed = supported and maximum <= tolerance
    return {**rebuilt, 'status': 'REVIEWED_MANUAL' if passed else 'NEEDS_MORE_DATA',
            'review': dict(passed=passed, tolerance_deg=tolerance, max_error_deg=maximum,
                          scope='recorded-reference fit and live display; no independent validation',
                          independent_validation=False)}

class PrecisionMapper:
    """Partial profiles retain legacy mapping on untouched joints, explicitly labelled."""
    def __init__(self, profile):
        self.profile = copy.deepcopy(profile)
        if profile.get('schema') != SCHEMA: raise ValueError('Unknown precision profile')
        if not profile.get('joints'):raise ValueError('Profile must contain a validated joint')
        for joint, entry in profile['joints'].items():
            if joint not in JOINTS or entry['status'] not in ('VALIDATED_MANUAL', 'REVIEWED_MANUAL'): raise ValueError('Unvalidated profile joint')
            if any(r['joint']!=joint for r in entry['references']):raise ValueError('Profile joint/reference mismatch')
            if entry['status']=='REVIEWED_MANUAL':
                checked = review_joint(entry, entry['review']['tolerance_deg'])
                if entry['review'] != checked['review']: raise ValueError('Manual review evidence differs')
            else: checked = validate_joint(entry, entry['validation']['tolerance_deg'])
            if checked['status'] != entry['status']: raise ValueError('Validation no longer passes')
            for key in ('anchor_raw', 'reference_angle_rad', 'rad_per_count', 'raw_domain'):
                if entry[key] != checked[key]: raise ValueError('Profile coefficients disagree with reference evidence')

    def _forward(self, raw, joint):
        entry = self.profile['joints'][joint]
        try: return joint_angle(entry, raw)
        except ValueError as exc: raise ValueError(joint + ': ' + str(exc)) from exc

    def raw_to_urdf(self, raw, native):
        raw = values(raw); native = values(native)
        q = LEGACY_MAPPER.calibrated_to_urdf(native)
        for joint in self.profile['joints']: q[joint] = self._forward(raw[joint], joint)
        return q

    def calibrated_to_urdf(self, native):
        native = values(native)
        q = LEGACY_MAPPER.calibrated_to_urdf(native)
        for joint, entry in self.profile['joints'].items(): q[joint] = self._forward(raw_from_native(native[joint], entry['motor']), joint)
        return q

    def calibrated_to_observation(self, native, raw=None):
        """Decode observations/leader requests beyond model limits; never authorize a goal."""
        native = values(native)
        if raw is not None: raw = values(raw)
        q = LEGACY_MAPPER.calibrated_to_urdf(native)
        if raw is not None and (set(raw)!=set(JOINTS) or not np.isfinite(list(raw.values())).all()):
            raise ValueError('Invalid raw feedback packet')
        for joint, entry in self.profile['joints'].items():
            position = raw_from_native(native[joint], entry['motor']) if raw is None else float(raw[joint])
            if raw is not None:
                spec=entry['motor']; cal=spec['calibration']
                normalized = native_from_raw(np.clip(position,cal['range_min'],cal['range_max'])
                    if spec['mode']=='RANGE_0_100' else position, spec)
                if abs(normalized-native[joint])>1e-6: raise ValueError(joint+': raw/native packet mismatch')
            try: q[joint] = self._forward(position, joint)
            except ValueError as exc:
                if 'Position outside URDF limits' not in str(exc): raise
                # Out-of-model measurements on the reference encoder branch are
                # evidence, not permission to send an out-of-limit motor goal.
                x = unwrap(position, entry['anchor_raw'], entry['motor']['resolution'])
                q[joint] = entry['rad_per_count']*(x-entry['anchor_raw']) + entry['reference_angle_rad']
        return q

    def command_limits(self, bounds):
        """Representable integer goals for Teleop; never change measured angles.

        Keep the inverse strict for policy/replay. Reject disconnected or ambiguous
        encoder intervals rather than treating a gap as a commandable range.
        """
        result = dict(bounds)
        for joint, entry in self.profile['joints'].items():
            low, high = max(bounds[joint][0], entry['limits'][0]), min(bounds[joint][1], entry['limits'][1])
            if low > high: raise ValueError(joint + ': no common model/motor command range')
            slope = entry['rad_per_count']; anchor = entry['anchor_raw']; zero = entry['reference_angle_rad']
            lo, hi = sorted(anchor + (q-zero)/slope for q in (low, high))
            cal = entry['motor']['calibration']; period = entry['motor']['resolution']
            if cal['range_max']-cal['range_min'] >= period:
                raise ValueError(joint + ': ambiguous command encoder branch')
            intervals = []
            for branch in range(math.ceil((cal['range_min']-hi)/period), math.floor((cal['range_max']-lo)/period)+1):
                first = math.ceil(max(cal['range_min'], lo+branch*period))
                last = math.floor(min(cal['range_max'], hi+branch*period))
                if first > last: continue
                # Reuse the same branch checks as forward/inverse, including wraps.
                angles = sorted(joint_angle(entry, raw) for raw in (first, last))
                intervals.append(angles)
            if len(intervals) != 1:
                raise ValueError(joint + ': no single unambiguous model/motor command range')
            result[joint] = intervals[0]
        return result

    def urdf_to_calibrated(self, q):
        q = values(q)
        native = LEGACY_MAPPER.urdf_to_calibrated(q)
        for joint, entry in self.profile['joints'].items():
            if not entry['limits'][0] <= q[joint] <= entry['limits'][1]: raise ValueError(joint + ': command outside URDF limits')
            x = entry['anchor_raw'] + (q[joint] - entry['reference_angle_rad']) / entry['rad_per_count']
            cal = entry['motor']['calibration']; period = entry['motor']['resolution']
            # Float round-trip at an integer boundary is not a different branch.
            first = math.ceil((cal['range_min']-x-1e-7)/period)
            last = math.floor((cal['range_max']-x+1e-7)/period)
            if first > last:
                raise ValueError(
                    f'{joint}: command outside calibrated motor range; '
                    f'requested={math.degrees(q[joint]):+.2f} deg, '
                    f'reference-branch raw={x:.2f}, '
                    f'calibrated raw=[{cal["range_min"]}, {cal["range_max"]}]; '
                    'no goal sent. Move Leader toward its calibrated neutral pose before Start.'
                )
            if first != last: raise ValueError(joint + ': ambiguous command encoder branch')
            # Quantize at the URDF boundary without rounding a valid goal beyond it.
            lo, hi = joint_raw_limits(entry)
            lower = math.ceil(max(cal['range_min'], lo+first*period))
            upper = math.floor(min(cal['range_max'], hi+first*period))
            if lower > upper: raise ValueError(joint + ': no representable motor goal inside URDF limits')
            raw = min(upper, max(lower, round(x+first*period)))
            resolved = joint_raw_coordinate(entry, raw)
            if abs(resolved-(raw-first*period)) > 1e-6:
                raise ValueError(joint + ': command encoder branch does not roundtrip')
            native[joint] = native_from_raw(raw, entry['motor'])
        return native

    def metadata(self):
        spec = {'schema': MAPPING, 'profile': self.profile, 'joint_order': list(JOINTS),
            'input': 'original LeRobot degrees/percent; homed Present_Position before normalization',
            'output': 'urdf_joint_radian', 'evidence': 'partial_manual_calibration', 'physical_verified': False,
            'operational_range': 'URDF limits; goals also require calibrated motor range and an unambiguous encoder branch',
            'legacy_joints': [n for n in JOINTS if n not in self.profile['joints']]}
        return {**spec, 'sha256': fingerprint(spec)}


def model_without_limits(urdf):
    """Compare full XML contents; only six named lower/upper limits may differ."""
    tree = ET.fromstring(urdf)
    for joint in tree.findall('joint'):
        if joint.get('name') in JOINTS:
            for key in ('lower', 'upper'): joint.find('limit').attrib.pop(key)
    def node(e):
        return (e.tag, sorted(e.attrib.items()), (e.text or '').strip(), [node(child) for child in e])
    return node(tree)


def profile_for_model(profile, model_hash, *, source_model=None, execution_model=None):
    """Bind only an in-memory copy, using supplied hash-checked model bytes.

    Unlike the historical repository lookup, no active pointer or Git is consulted.
    S01/S02 package callers can supply the registered source/execution assets.
    """
    if profile['urdf_sha256'] == model_hash: return copy.deepcopy(profile)
    if not isinstance(source_model, bytes) or not isinstance(execution_model, bytes):
        raise ValueError('Exact source and execution model evidence required')
    if hashlib.sha256(source_model).hexdigest() != profile['urdf_sha256'] or hashlib.sha256(execution_model).hexdigest() != model_hash:
        raise ValueError('Model evidence SHA-256 mismatch')
    if model_without_limits(source_model) != model_without_limits(execution_model):
        raise ValueError('Precision profile URDF identity conflict: geometry/origin/axis/topology changed')
    before = {j.get('name'): j.find('limit') for j in ET.fromstring(source_model).findall('joint')}
    after = {j.get('name'): j.find('limit') for j in ET.fromstring(execution_model).findall('joint')}
    result = copy.deepcopy(profile)
    for name in JOINTS:
        bounds = [float(after[name].get(k)) for k in ('lower', 'upper')]
        if not np.isfinite(bounds).all() or bounds[0] >= bounds[1]: raise ValueError(name + ': invalid current URDF limits')
    for name, entry in result['joints'].items():
        if entry['limits'] != [float(before[name].get(k)) for k in ('lower','upper')]:
            raise ValueError(name + ': saved profile/model limits disagree')
        entry['limits'] = [float(after[name].get(k)) for k in ('lower','upper')]
    result['urdf_sha256'] = model_hash
    result['runtime_model_binding'] = {'saved_profile_sha256':fingerprint(profile),
        'saved_urdf_sha256':profile['urdf_sha256'], 'change':'lower_upper_limits_only', 'persisted':False}
    return result


def mapper_from_metadata(metadata):
    if metadata.get('schema') != MAPPING: raise ValueError('Unknown precision mapping schema')
    spec = {k:v for k,v in metadata.items() if k != 'sha256'}
    if fingerprint(spec) != metadata.get('sha256'): raise ValueError('Precision mapping hash mismatch')
    if tuple(metadata.get('joint_order', ())) != JOINTS: raise ValueError('Mapping joint order mismatch')
    mapper = PrecisionMapper(metadata['profile'])
    if mapper.metadata() != dict(metadata): raise ValueError('Precision mapping content mismatch')
    return mapper


def _json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result: raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value): raise ValueError('Nonfinite JSON number: ' + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    fingerprint(value)  # Reject overflow as well as NaN/Infinity.
    return value


def load_profile(path, *, expected_sha256=None, role=None, identity=None):
    """Read a chosen profile. expected_sha256 is the file-byte hash, not mapping hash."""
    raw = Path(path).read_bytes()
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Profile file SHA-256 mismatch')
    profile = _json(raw)
    if role is not None and profile.get('role') != role: raise ValueError('Profile role mismatch')
    if identity is not None and profile.get('identity') != identity: raise ValueError('Profile device identity mismatch')
    PrecisionMapper(profile)
    return profile


def mapper_from_scene(package, calibration_id, *, role, phase):
    """Bind a declared Encoder record; baked geometry is never an encoder command."""
    from scene_contract.package import verify_files
    verify_files(package.root, package.files)
    record = package.calibration['records'][calibration_id]
    application = record['application']
    if record['kind'] != 'encoder_mapping' or application['mode'] != 'runtime' or application['phase'] != phase:
        raise ValueError('Expected encoder runtime record at the requested phase; baked transforms must not be reapplied')
    def plain(value):
        if isinstance(value, Mapping): return {k:plain(v) for k,v in value.items()}
        if isinstance(value, (tuple,list)): return [plain(v) for v in value]
        return value
    parameters = (_json((package.root / record['parameters_file']).read_bytes())
                  if 'parameters_file' in record else plain(record['parameters']))
    profile = parameters['profile'] if parameters.get('schema') == MAPPING else parameters
    if profile.get('role') != role: raise ValueError('Encoder role mismatch')
    original_hash = profile.get('runtime_model_binding', {}).get('saved_urdf_sha256', profile['urdf_sha256'])
    if original_hash != record['source_model_sha256']: raise ValueError('Source model binding mismatch')
    assets = {entry.sha256: package.root / entry.path for entry in package.files}
    source_hash = profile['urdf_sha256']; target_hash = record['execution_model_sha256']
    effective = profile_for_model(profile, target_hash, source_model=assets[source_hash].read_bytes(), execution_model=assets[target_hash].read_bytes())
    mapper = mapper_from_metadata(parameters) if parameters.get('schema') == MAPPING else PrecisionMapper(effective)
    if mapper.profile != effective: raise ValueError('Execution model mapping mismatch')
    return mapper


def review_revision(source: Path|str, output: Path|str, *, references: dict|None=None, tolerance_deg: float=.5) -> dict:
    """Review explicit angle references; save a new revision without motor writes.

    Feedback alone supplies no angle ground truth. Omitted references re-review
    the existing evidence and cannot establish new independent physical accuracy.
    """
    from ..data.native import atomic_json
    import uuid
    source=Path(source).resolve();output=Path(output).resolve();raw=source.read_bytes();profile=load_profile(source)
    if output==source or output.exists():raise FileExistsError('A new profile Revision path is required')
    if references is not None and (not isinstance(references,dict) or not references or set(references)-set(profile['joints'])):raise ValueError('Explicit measured joint reference records required')
    previous=copy.deepcopy(profile);joints={}
    for n,entry in profile['joints'].items():
        candidate=copy.deepcopy(entry)
        if references is not None and n in references:
            candidate=fit_joint(references[n],entry['motor'],n,entry['limits'],entry.get('reference_mode','angle'))
        reviewed=review_joint(candidate,tolerance_deg)
        if reviewed['status']!='REVIEWED_MANUAL':raise ValueError(n+': NEEDS_MORE_DATA; no reviewed revision published')
        joints[n]=reviewed
    profile.update(id='profile_'+uuid.uuid4().hex,parent_sha256=hashlib.sha256(raw).hexdigest(),parent_path=str(source),joints=joints,physical_verified=False)
    PrecisionMapper(profile);atomic_json(output,profile,exclusive=True)
    return {'path':str(output),'parent_sha256':profile['parent_sha256'],'physical_verified':False,'new_reference_input':references is not None,'new_independent_reference':False,
        'comparison':{n:{'slope_delta':joints[n]['rad_per_count']-previous['joints'][n]['rad_per_count'],'reference_angle_delta_rad':joints[n]['reference_angle_rad']-previous['joints'][n]['reference_angle_rad'],'max_fit_error_deg':joints[n]['review']['max_error_deg']}for n in joints}}
