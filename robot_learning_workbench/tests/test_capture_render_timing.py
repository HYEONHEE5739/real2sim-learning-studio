"""Timing boundaries only: no robot, engine, GUI, or rendering model is started."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from robot_learning_workbench.data.native import atomic_json, file_sha256
from robot_learning_workbench.robot.render_transport import RenderProcess


def test_worker_capture_timing_survives_transport_and_pair(tmp_path, monkeypatch):
    from robot_learning_workbench.robot import scene_render, pose_render, render_worker
    from robot_learning_workbench.robot.pairs import write_pair

    identity = {'manifest_sha256': 'a' * 64}
    view = SimpleNamespace(identity=identity, render_type='native',simulation_mode='pose')
    monkeypatch.setattr(scene_render, 'SceneView', lambda *args: view)
    atomic_json(tmp_path / 'config.json', dict(engine='mujoco', scene='unused',
        settings='unused', mapping={}, identity=identity))
    atomic_json(tmp_path / 'latest.json', dict(id='live_1', q=[0.] * 6,
        requested_ns=time.monotonic_ns()))
    requests = []

    class Renderer:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def render(self, q):
            requests.append(list(q))
            if len(requests) == 1:
                # Arrival during a live render, not a new worker or parallel engine.
                atomic_json(tmp_path / 'capture.json', dict(id='pair_1', q=q,
                    requested_ns=time.monotonic_ns()))
            else:
                (tmp_path / 'stop').touch()
            return dict(images={n:np.full((48,64,3),90,np.uint8) for n in ('side','wrist')},
                measured_q_rad=q, applied_sim_joint_rad=q, scene_identity=identity,
                sim_timestamp={'monotonic_ns':time.monotonic_ns()}, render_ms=0.)

    monkeypatch.setattr(pose_render, 'create_pose_renderer', lambda *args: Renderer())
    render_worker.run(tmp_path)
    raw = json.loads((tmp_path / 'capture-result.json').read_text())
    times = raw['render_transport_times_ns']
    assert times['requested'] <= times['request_read'] <= times['render_started'] <= times['render_completed'] <= times['result_ready']
    assert times['previous_job']['id'] == 'live_1'
    assert times['previous_job']['capture'] is False
    assert times['previous_job']['render_started'] <= times['requested'] <= times['previous_job']['render_completed']
    for camera in ('side','wrist'):
        row = times['png'][camera]
        assert times['render_completed'] <= row['encode_started'] <= row['encoded'] <= row['sha_started'] <= row['sha_completed'] <= times['result_ready']
        assert file_sha256(raw['files'][camera]['path']) == raw['files'][camera]['sha256']

    owner = RenderProcess.__new__(RenderProcess)
    owner.root = tmp_path
    result = owner._read('capture-result.json', decode=False)
    times = result['render_transport_times_ns']
    assert times['result_ready'] <= times['parent_read_started'] <= times['parent_verified']
    assert times['parent_sha_duration'] >= 0
    assert result['images'] == {}

    shot = tmp_path / 'pair'
    shot.mkdir()
    for name in ('side','wrist'):
        Image.fromarray(np.full((48,64,3),90,np.uint8)).save(shot / (name+'.png'))
    atomic_json(shot/'metadata.json', dict(files={}, images=[
        dict(camera=n,path=n+'.png') for n in ('side','wrist')]))
    pending = dict(sample=dict(q_measured=[0.] * 6,timestamp_ns=1),quality=[])
    write_pair(shot,dict(project_id='test',snapshots=[dict(path='.')]),pending,result)
    assert json.loads((shot/'pair.json').read_text())['render_transport_times_ns'] == times
    assert len(requests) == 2


def test_legacy_renderer_result_keeps_unknown_worker_timings_unknown(tmp_path):
    path = tmp_path / 'side.png'
    Image.fromarray(np.zeros((12,16,3),np.uint8)).save(path)
    atomic_json(tmp_path/'capture-result.json',dict(id='legacy',
        requested_ns=time.monotonic_ns(),files=dict(side=dict(path=str(path),sha256=file_sha256(path)))))
    owner = RenderProcess.__new__(RenderProcess)
    owner.root = tmp_path
    result = owner._read('capture-result.json',decode=False)
    times = result['render_transport_times_ns']
    assert 'render_started' not in times and 'request_read' not in times
    assert times['parent_read_started'] <= times['parent_verified']
    assert result['files']['side']['sha256'] == file_sha256(path)
