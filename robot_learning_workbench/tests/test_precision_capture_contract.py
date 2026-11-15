"""Synthetic Precision writer -> Capture/Snapshot reader contract; no device I/O."""
import copy
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from real2sim_builder.capture import load_session
from real2sim_builder.files import read, write
from real2sim_builder.project import Project
from robot_learning_workbench.data.native import file_sha256
from robot_learning_workbench.robot import capture
from robot_learning_workbench.robot.calibration import (
    JOINTS, PrecisionMapper, fingerprint, load_profile, mapper_from_metadata,
    native_from_raw, review_joint, validate_joint,
)
from robot_learning_workbench.robot.precision import PrecisionSession
from robot_learning_workbench.robot.snapshots import SnapshotStore


class CalculationDevice:
    """Only identity and motor arithmetic are available to this offline test."""

    def __init__(self, directory):
        self.calibration_path = directory / 'synthetic-sdk.json'
        self.calibration_path.write_text('{"synthetic":true}\n')
        self.identity = {
            'role': 'follower', 'id': 'synthetic_follower',
            'port': str(directory / 'unused-serial'),
            'calibration_sha256': file_sha256(self.calibration_path),
            'motors': {n: {'id': i, 'model': 'synthetic'} for i, n in enumerate(JOINTS, 1)},
        }

    def unchanged(self):
        return file_sha256(self.calibration_path) == self.identity['calibration_sha256']

    def motor_spec(self, joint):
        return {
            'resolution': 4096, 'mode': 'DEGREES', 'apply_drive_mode': False,
            'calibration_hash': self.identity['calibration_sha256'],
            'calibration': {'range_min': 200, 'range_max': 3800, 'drive_mode': 0, 'homing_offset': 0},
        }

    def connect(self):
        raise AssertionError('Offline calculation must never connect a device')

    def release_for_calibration(self, **kwargs):
        raise AssertionError('Offline calculation must never change Torque')

    def sample(self, *args, **kwargs):
        raise AssertionError('References must be synthetic, not acquired from a device')


def saved_precision(tmp_path, status='CALIBRATED_MANUAL'):
    workspace = tmp_path / 'workspace'
    directory = workspace / 'devices' / 'synthetic'
    directory.mkdir(parents=True)
    model = directory / 'robot.urdf'
    links = '<link name="base"/>' + ''.join(f'<link name="link_{i}"/>' for i in range(6))
    joints = ''.join(
        f'<joint name="{name}" type="revolute"><parent link="{parent}"/>'
        f'<child link="link_{i}"/><origin xyz="0 0 0.1" rpy="0 0 0"/>'
        '<axis xyz="0 0 1"/><limit lower="-2" upper="2" effort="1" velocity="1"/></joint>'
        for i, (name, parent) in enumerate(zip(JOINTS, ['base', *[f'link_{j}' for j in range(5)]]))
    )
    model.write_text('<robot name="synthetic">' + links + joints + '</robot>')
    configuration = directory / 'capture.yaml'
    configuration.write_text(yaml.safe_dump({'schema_version': 1, 'stage': 'scene_capture', 'inputs': {'robot_model': str(model)}}))
    device = CalculationDevice(directory)
    inputs = {p: p.read_bytes() for p in (model, configuration, device.calibration_path)}
    session = PrecisionSession(workspace, configuration, 'follower', model, device, events=lambda event: None)
    references = [
        {'joint': 'shoulder_pan', 'raw': raw, 'angle_rad': angle, 'split': split,
         'calibration_hash': device.identity['calibration_sha256']}
        for raw, angle, split in ((1500, 0., 'train'), (2500, math.pi / 2, 'train'))
    ]
    if status == 'VALIDATED_MANUAL':
        references.append({**references[0], 'raw': 2000, 'angle_rad': math.pi / 4, 'split': 'validation'})
    candidate = session.calculate('shoulder_pan', references)
    assert candidate['status'] == 'CALIBRATED_MANUAL' and candidate['physical_verified'] is False
    if status == 'REVIEWED_MANUAL':
        candidate = review_joint(candidate)
    elif status == 'VALIDATED_MANUAL':
        candidate = validate_joint(candidate)
    session.candidates['shoulder_pan'] = candidate
    path = workspace / 'calibration' / 'manual.json'
    result = session.save(str(path), False)
    profile = load_profile(path, expected_sha256=result['sha256'], role='follower', identity=device.identity)
    assert result['automatically_applied'] and result['physical_verified'] is False
    assert profile['physical_verified'] is False
    assert profile['joints']['shoulder_pan']['status'] == status
    assert profile['joints']['shoulder_pan']['physical_verified'] is False
    mapping = PrecisionMapper(profile).metadata()
    assert mapper_from_metadata(mapping).metadata() == mapping
    assert mapping['physical_verified'] is False
    assert mapping['legacy_joints'] == list(JOINTS[1:])
    assert all(p.read_bytes() == raw for p, raw in inputs.items())
    return workspace, model, path, mapping


def write_observation(tmp_path, kind, workspace, model, mapping):
    image = np.repeat(((np.indices((480, 640)).sum(0) % 2) * 255).astype(np.uint8)[:, :, None], 3, axis=2)
    expected_q = [math.pi / 4, 0., 0., 0., 0., 0.]
    if kind == 'capture':
        destination = tmp_path / 'capture'
        capture.save_session(
            destination, model=model, mapping=mapping,
            samples=[{'id': 'sample_1', 'timestamp_ns': 1_000_000_000, 'q_measured': expected_q, 'command_applied': False}],
            images=[{'side': image, 'wrist': image.copy()}], metadata={'device_source': 'synthetic'},
        )
        return destination
    native = dict.fromkeys(JOINTS, 0.)
    native['shoulder_pan'] = native_from_raw(2000, mapping['profile']['joints']['shoulder_pan']['motor'])
    stability = capture.Stability()
    history = []
    for timestamp in range(300_000_000, 1_000_000_001, 100_000_000):
        stability.add(timestamp, native)
        history.append({'timestamp_ns': timestamp, 'native': dict(native)})
    packet = lambda timestamp: {'monotonic_ns': timestamp, 'unix_ns': timestamp + 1_000_000_000}
    state = {
        'joint_names': list(JOINTS), 'sim_joint_mapping': mapping,
        'physical_follower_measured_joint_state': native, 'measured_samples': history,
        'real_stability': stability.assess(), 'precision_observation_only': True, 'sent_target': None,
        'hardware': {'follower': {'identity': mapping['profile']['identity']}}, 'device_source': 'synthetic',
        'timestamps': {'follower': {'start': packet(999_000_000), 'end': packet(1_000_000_000)},
                       'real_cameras': {'real_' + n: {'read_start': packet(973_000_000), 'read_end': packet(975_000_000), 'sequence': 1}
                                        for n in ('side', 'wrist')}},
    }
    project = Project.create(workspace / 'scenes', 'Precision contract')
    store = SnapshotStore(project, session_id='synthetic_session', model=model, mapping=mapping)
    pending = store.prepare('snapshot_1', state, {'real_side': image, 'real_wrist': image.copy()}, now_ns=1_010_000_000)
    return Path(pending['staging'])


@pytest.mark.parametrize('kind', ['capture', 'snapshot'])
@pytest.mark.parametrize('status', ['CALIBRATED_MANUAL', 'REVIEWED_MANUAL', 'VALIDATED_MANUAL'])
def test_precision_calculate_save_metadata_reaches_capture_reader(tmp_path, kind, status):
    workspace, model, profile_path, mapping = saved_precision(tmp_path, status)
    originals = {p: p.read_bytes() for p in (model, profile_path)}
    original_mapping = copy.deepcopy(mapping)
    destination = write_observation(tmp_path, kind, workspace, model, mapping)
    manifest, samples, events = load_session(destination)
    assert manifest['joint_mapping'] == original_mapping == mapping
    assert manifest['source_robot_sha256'] == file_sha256(model)
    assert manifest['joint_names'] == list(JOINTS) and manifest['joint_units'] == ['rad'] * 6
    assert manifest['robot']['mapping_verified'] is False
    assert manifest['joint_mapping']['physical_verified'] is False
    assert samples[0]['q_measured'] == pytest.approx([math.pi / 4, 0., 0., 0., 0., 0.])
    assert events == [] and {image['camera'] for image in samples[0]['images']} == {'side', 'wrist'}
    if kind == 'snapshot':
        assert manifest['physical_verified'] is False
        metadata_path = destination / samples[0]['metadata_path']
        measured = read(metadata_path.parent / 'state.json')
        assert measured['q_command'] is None and measured['mapping_sha256'] == mapping['sha256']
        assert measured['model_sha256'] == file_sha256(model)
    assert all(p.read_bytes() == raw for p, raw in originals.items())


@pytest.mark.parametrize('kind', ['capture', 'snapshot'])
@pytest.mark.parametrize('bad', ['mapping_hash', 'model_hash', 'urdf', 'coefficient', 'boolean_coefficient', 'order', 'units', 'physical_verified', 'joint_physical_verified', 'mapping_verified', 'unknown_status'])
def test_precision_capture_reader_keeps_identity_and_numeric_guards(tmp_path, kind, bad):
    workspace, model, _, mapping = saved_precision(tmp_path, 'REVIEWED_MANUAL')
    destination = write_observation(tmp_path, kind, workspace, model, mapping)
    manifest_path = destination / 'capture_manifest.yaml'
    manifest = read(manifest_path)
    changed = manifest['joint_mapping']
    if bad == 'mapping_hash':
        changed['sha256'] = '0' * 64
    elif bad == 'model_hash':
        manifest['files'][manifest['robot']['path']] = '0' * 64
    elif bad == 'urdf':
        changed['profile']['urdf_sha256'] = '0' * 64
    elif bad == 'coefficient':
        changed['profile']['joints']['shoulder_pan']['rad_per_count'] = 0.
    elif bad == 'boolean_coefficient':
        changed['profile']['joints']['shoulder_pan']['rad_per_count'] = True
    elif bad == 'order':
        changed['joint_order'].reverse()
    elif bad == 'units':
        manifest['joint_units'][0] = 'm'
    elif bad == 'physical_verified':
        changed['physical_verified'] = True
    elif bad == 'joint_physical_verified':
        changed['profile']['joints']['shoulder_pan']['physical_verified'] = True
    elif bad == 'unknown_status':
        changed['profile']['joints']['shoulder_pan']['status'] = 'UNREVIEWED'
    else:
        manifest['robot']['mapping_verified'] = True
    if bad != 'mapping_hash':
        changed['sha256'] = fingerprint({k: v for k, v in changed.items() if k != 'sha256'})
    write(manifest_path, manifest)
    with pytest.raises(ValueError):
        load_session(destination)


def test_saved_manual_coefficients_must_still_match_reference_evidence(tmp_path):
    _, _, path, mapping = saved_precision(tmp_path)
    profile = read(path)
    profile['joints']['shoulder_pan']['rad_per_count'] += .001
    write(path, profile)
    with pytest.raises(ValueError, match='coefficients'):
        load_profile(path)
    mapping['profile'] = profile
    mapping['sha256'] = fingerprint({k: v for k, v in mapping.items() if k != 'sha256'})
    with pytest.raises(ValueError, match='coefficients'):
        mapper_from_metadata(mapping)
