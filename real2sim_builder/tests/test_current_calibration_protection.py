"""Legacy public run keeps Current immutable until a validated result exists."""
import copy

import numpy as np
import pytest
from PIL import Image

from real2sim_builder.calibration.camera import fit_cameras, project_point, landmark_metrics
from real2sim_builder.files import write
from real2sim_builder.project import Project, add_image
from real2sim_builder.reconstruction import run
from test_builder_calibration import scene


def landmarks(truth):
    rows = []
    for point in [[-.1, -.1, 0], [.1, -.1, 0], [-.1, .1, 0],
                  [.1, .1, 0], [0, 0, .1], [.04, -.05, .12]]:
        row = {'camera': 'side', 'point_m': point, 'split': 'train'}
        row['uv'] = project_point(truth, truth['cameras'][0], row)[0].tolist()
        rows.append(row)
    return rows


@pytest.mark.parametrize('provenance', ['measured', 'calibrated'])
def test_camera_fitter_never_changes_protected_pose(scene, provenance):
    rows = landmarks(scene)
    scene['cameras'][0]['pose']['value'][0][3] += .035
    scene['cameras'][0]['pose']['provenance'] = provenance
    original = copy.deepcopy(scene)
    result, report = fit_cameras(scene, rows)
    assert result == original and scene == original


def test_estimated_camera_still_uses_metric_landmarks(scene):
    rows = landmarks(scene)
    scene['cameras'][0]['pose']['value'][0][3] += .035
    scene['cameras'][0]['pose']['provenance'] = 'estimated'
    original = copy.deepcopy(scene)
    result, report = fit_cameras(scene, rows)
    assert landmark_metrics(result, rows)['rmse_px'] < .01
    assert result['cameras'][0]['pose']['provenance'] == 'optimized'
    assert result['objects'] == original['objects'] and scene == original


def prepared(tmp_path, scene):
    truth = copy.deepcopy(scene)
    scene['cameras'][0]['pose']['value'][0][3] += .035
    scene['cameras'][0]['pose']['provenance'] = 'estimated'
    scene['objects'][1]['visual'] = {'type': 'unknown'}
    p = Project.create(tmp_path / 'projects', 'Protected Current')
    p.save_scene(scene)
    image = tmp_path / 'input.png'
    Image.new('RGB', (160, 120), 'gray').save(image)
    add_image(p, image, 'side')
    evidence = p.evidence
    evidence['landmarks'] = landmarks(truth)
    write(p.root / 'input/evidence.yaml', evidence)
    return p


@pytest.mark.parametrize('ending', ['needs', 'error', 'stop'])
def test_unsuccessful_legacy_run_and_retry_preserve_current_bytes(tmp_path, scene, monkeypatch, ending):
    import real2sim_builder.reconstruction as module
    p = prepared(tmp_path, scene)
    path = p.root / 'working/current_scene.yaml'
    # Exact bytes, including an existing user's formatting/comment, must survive.
    path.write_bytes(path.read_bytes() + b'\n# preserve prior Current formatting\n')
    before = path.read_bytes()
    if ending != 'needs':
        def interrupted(_scene):
            if ending == 'error':
                raise RuntimeError('synthetic failure after fitting')
            p.control('stop')
            p.checkpoint()
        monkeypatch.setattr(module, 'missing_geometry', interrupted)
    for _ in range(2):
        if ending == 'error':
            with pytest.raises(RuntimeError, match='synthetic failure'):
                run(p, max_iterations=1)
        else:
            assert run(p, max_iterations=1)['status'] == ('STOPPED' if ending == 'stop' else 'NEEDS_MORE_DATA')
        assert path.read_bytes() == before
        assert not (p.root / 'working/run.lock').exists()


def test_run_does_not_rewrite_calibrated_distortion_or_source_evidence(tmp_path, scene):
    scene['cameras'][0]['distortion']['value'] = [.02, -.001, .001, 0., 0.]
    p = prepared(tmp_path, scene)
    p_scene = p.scene
    p_scene['cameras'][0]['pose']['provenance'] = 'calibrated'
    p.save_scene(p_scene)
    path = p.root / 'working/current_scene.yaml'
    before, evidence = path.read_bytes(), p.evidence
    assert run(p, max_iterations=1)['status'] == 'NEEDS_MORE_DATA'
    assert path.read_bytes() == before and p.evidence == evidence


@pytest.mark.parametrize('invalid', ['protected', 'matrix'])
def test_automatic_publication_validates_and_preserves_before_current_write(tmp_path, scene, monkeypatch, invalid):
    import real2sim_builder.calibration.camera as camera
    p = prepared(tmp_path, scene)
    path = p.root / 'working/current_scene.yaml'
    before = path.read_bytes()
    def bad_fitter(original, rows):
        result = copy.deepcopy(original)
        if invalid == 'protected':
            result['objects'][0]['dimensions']['value'][0] *= 2
        else:
            result['cameras'][0]['pose']['value'][0][0] = np.nan
        return result, []
    monkeypatch.setattr(camera, 'fit_cameras', bad_fitter)
    with pytest.raises(ValueError):
        run(p, max_iterations=1)
    assert path.read_bytes() == before


@pytest.mark.parametrize('export_fails', [False, True])
def test_legacy_cli_publishes_only_a_valid_result_and_restores_after_export_failure(tmp_path, scene, monkeypatch, capsys, export_fails):
    from types import SimpleNamespace
    import real2sim_builder.reconstruction as module
    import real2sim_builder.rendering as rendering
    import real2sim_builder.export as exporter
    from real2sim_builder.cli import main
    p = prepared(tmp_path, scene)
    ready = p.scene
    ready['objects'][1]['visual'] = {'type': 'box'}
    p.save_scene(ready)
    path = p.root / 'working/current_scene.yaml'
    path.write_bytes(path.read_bytes() + b'\n# preserve on failed export\n')
    before = path.read_bytes()
    class Renderer:
        def __init__(self, *args):
            self.model = None
            self.mj = SimpleNamespace(MjData=lambda _: SimpleNamespace(qpos=np.zeros(1)), mj_step=lambda *args: None)
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(rendering, 'Renderer', Renderer)
    monkeypatch.setattr(module, 'validate_scene', lambda project, candidate, *args: (
        {'passed': True, 'needs': [], 'train_mae': .01, 'landmarks': {'validation': {}},
         'input_signature': project.signature(candidate)}, {}))
    if export_fails:
        def fail(*args, **kwargs): raise RuntimeError('synthetic exporter failure')
        monkeypatch.setattr(exporter, 'export_revision', fail)
        with pytest.raises(RuntimeError, match='synthetic exporter failure'):
            run(p, max_iterations=1, destination=tmp_path / 'new-export')
        assert path.read_bytes() == before
    else:
        assert main(['run', str(p.root), '--max-iterations', '1']) == 0
        assert 'DRAFT' in capsys.readouterr().out
        assert path.read_bytes() != before
        assert landmark_metrics(p.scene, p.evidence['landmarks'])['rmse_px'] < .01
        assert p.scene['objects'] == ready['objects']


def test_corrupt_current_is_reported_without_leaking_worker_lock(tmp_path):
    import yaml
    p = Project.create(tmp_path / 'projects', 'Invalid Current')
    current = p.root / 'working/current_scene.yaml'
    current.write_bytes(b'scene: [\n')
    before = current.read_bytes()
    with pytest.raises(yaml.YAMLError):
        run(p, max_iterations=1)
    assert current.read_bytes() == before
    assert not (p.root / 'working/run.lock').exists()
