"""Explicit Capture selection through real Qt/CLI/Pair readers; no device/model work."""
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from real2sim_builder import automation
from real2sim_builder.candidate import Candidate
from real2sim_builder.capture import load_session
from real2sim_builder.export import export_revision
from real2sim_builder.files import read, sha, write
from real2sim_builder.project import Project
from robot_learning_workbench.robot.calibration import JOINTS, native_from_raw
from robot_learning_workbench.robot.capture import snapshot_state
from robot_learning_workbench.robot.snapshots import SnapshotStore
from test_builder_export import legacy_scene
from test_capture_sensor_contract import _robot, _rgb


def _snapshot(project, store, mapper, identifier, layout, identity, package, sequence):
    stamp = 2_000_000_000 + sequence * 1_000_000_000
    raw = dict.fromkeys(JOINTS, 2000)
    specs = {name: entry['motor'] for name, entry in mapper.profile['joints'].items()}
    native = {name: native_from_raw(raw[name], specs[name]) for name in JOINTS}
    interval = {'start': {'monotonic_ns': stamp - 1}, 'end': {'monotonic_ns': stamp}}
    history = [{'timestamp_ns': stamp - (6-i) * 100_000_000, 'native': native,
                'raw': raw, 'feedback_interval': interval} for i in range(7)]
    packets = {name: {'read_start': {'monotonic_ns': stamp - 2_000_000},
                     'read_end': {'monotonic_ns': stamp - 1_000_000}, 'sequence': sequence}
               for name in ('side', 'wrist')}
    state = snapshot_state(SimpleNamespace(precision_mapper=mapper, motor_specs=specs,
                                          identity={'id': 'memory_only'}), history, packets,
                           {'stable': True, 'window_start_ns': stamp-600_000_000,
                            'window_end_ns': stamp})
    pending = store.prepare(identifier, state, {'real_side': _rgb(), 'real_wrist': _rgb()}, now_ns=stamp)
    # Explicitly author different synthetic layouts before committing the fixture.
    staging = Path(pending['staging'])
    manifest = read(staging/'capture_manifest.yaml')
    metadata = read(staging/'metadata.json')
    metadata['scene_state_id'] = layout
    write(staging/'metadata.json', metadata)
    manifest['snapshots'][0].update(scene_state_id=layout, metadata_sha256=sha(staging/'metadata.json'))
    write(staging/'capture_manifest.yaml', manifest)
    return store.finish(pending, rendered={
        'images': {'side': _rgb(), 'wrist': _rgb()},
        'measured_q_rad': pending['sample']['q_measured'],
        'applied_sim_joint_rad': [q+.01 for q in pending['sample']['q_measured']],
        'scene_identity': identity,
        'source_scene': {'package_path': str(package), 'identity': identity,
                         'authored_scene_sha256': sha(package/'authored_scene.json')},
        'engine': 'synthetic', 'sim_timestamp': {'monotonic_ns': stamp},
        'sim_cameras': {}, 'joint_mapping': mapper.metadata(),
    })


def _fixture(tmp_path, *, second_source=False, same_layout=False, source_robot=False):
    model, mapper = _robot(tmp_path)
    project = Project.create(tmp_path/'projects', 'explicit refit selection')
    source=legacy_scene()
    if source_robot:
        from real2sim_builder.scene import value
        owned=project.root/'input/model.urdf';owned.write_bytes(model.read_bytes())
        source['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'calibrated')}
        source['robot_model']={'format':'urdf','path':'input/model.urdf','model_sha256':sha(owned),
            'joint_names':list(JOINTS),'mapping':mapper.metadata(),'mapping_verified':False}
    project.save_scene(source)
    write(project.root/'working/validation/report.json', {'passed': False, 'input_signature': project.signature()})
    first = project.root/'exports/first'
    identity = asdict(export_revision(project, destination=first, allow_unvalidated=True))
    second = first
    other_identity = identity
    if second_source:
        second = project.root/'exports/second'
        scene = project.scene
        scene['objects'][1]['color']['value'] = [.1, .6, .3]
        project.save_scene(scene)
        write(project.root/'working/validation/report.json', {'passed': False, 'input_signature': project.signature()})
        other_identity = asdict(export_revision(project, destination=second, allow_unvalidated=True))
        assert other_identity != identity
    store = SnapshotStore(project, session_id='recorded_session', model=model, mapping=mapper.metadata())
    a = _snapshot(project, store, mapper, 'capture_a', 'layout_a', identity, first, 1)
    b = _snapshot(project, store, mapper, 'capture_b', 'layout_a' if same_layout else 'layout_b', other_identity, second, 2)
    assert a['id'] == load_session(Path(a['path']))[1][0]['id'] == 'capture_a'
    assert b['id'] == load_session(Path(b['path']))[1][0]['id'] == 'capture_b'
    images = project.evidence['images']
    assert {row['snapshot_id'] for row in images} == {'capture_a', 'capture_b'}
    return project, first, identity, [a, b]


def _immutable(project):
    folders = [project.root/'input', project.root/'exports']
    rows = {p.relative_to(project.root).as_posix(): sha(p)
            for folder in folders for p in folder.rglob('*') if p.is_file()}
    current = project.root/'working/current_scene.yaml'
    rows[current.relative_to(project.root).as_posix()] = sha(current)
    return rows


def _numeric(candidate, config):
    # Keep actual Pair source resolution and Candidate publication; replace only
    # sensor render/optimization beyond the selection boundary.
    return {'status': 'REFINED_DRAFT', 'physical_verified': False, 'needs': [],
            'selected_layout': config['scene_state_id'], 'selected_images': config['image_ids']}


@pytest.mark.parametrize('selection,layout', [('capture_a', 'layout_a'), ('capture_b', 'layout_b')])
def test_explicit_capture_selects_its_layout_through_actual_backend(tmp_path, monkeypatch, selection, layout):
    project, _, identity, _ = _fixture(tmp_path)
    before = _immutable(project)
    monkeypatch.setattr(automation, 'refine_numeric_pairs', _numeric)
    result = automation.refit_pairs(project, candidate='chosen', scene_state=layout, config={
        'refit_capture_ids': [selection], 'refit_source_identity': identity,
        'numeric_refinement': {'enabled': True}})
    assert result['status'] == 'REFINED_DRAFT', result
    assert result['selected_layout'] == layout
    assert len(result['selected_images']) == 2
    assert all(selection in key for key in result['selected_images'])
    assert Candidate(project, 'chosen').scene['reconstruction_state']['id'] == layout
    assert _immutable(project) == before


@pytest.mark.parametrize('bad', ['mixed_layout', 'unknown_id', 'partial_unknown', 'wrong_layout', 'missing_layout', 'missing_snapshot', 'mixed_source'])
def test_backend_never_silently_drops_an_explicit_capture_selection(tmp_path, monkeypatch, bad):
    project, _, identity, _ = _fixture(tmp_path, second_source=bad == 'mixed_source', same_layout=bad == 'mixed_source')
    selected = ['capture_a']
    if bad in ('mixed_layout', 'mixed_source'):
        selected.append('capture_b')
    elif bad == 'unknown_id':
        selected = ['absent_capture']
    elif bad == 'partial_unknown':
        selected.append('absent_capture')
    elif bad in ('missing_layout', 'missing_snapshot'):
        evidence = project.evidence
        for image in evidence['images']:
            if image.get('snapshot_id') == 'capture_a':
                image.pop('scene_state_id' if bad == 'missing_layout' else 'snapshot_id')
        write(project.root/'input/evidence.yaml', evidence)
    before = _immutable(project)
    calls = []
    monkeypatch.setattr(automation, 'refine_numeric_pairs', lambda *args: calls.append(args) or _numeric(*args))
    result = automation.refit_pairs(project, candidate='refused',
        scene_state='layout_b' if bad == 'wrong_layout' else 'layout_a', config={
            'refit_capture_ids': selected, 'refit_source_identity': identity,
            'numeric_refinement': {'enabled': True}})
    assert result['status'] == 'NEEDS_MORE_DATA', result
    assert result.get('code'), result
    assert not calls
    assert not (project.root/'scratch/agent/refused').exists()
    assert _immutable(project) == before


def test_pair_sha_guard_and_legacy_archived_identity_are_kept(tmp_path, monkeypatch):
    project, _, identity, _ = _fixture(tmp_path)
    evidence = project.evidence
    for image in evidence['images']:
        if image['snapshot_id'] == 'capture_a':
            # Historical imports can resolve identity from the verified Pair file.
            image.pop('runtime_baseline_ref',None)  # This fixture explicitly represents the legacy inline format.
            image['runtime_baseline'].pop('scene_identity')
    write(project.root/'input/evidence.yaml', evidence)
    monkeypatch.setattr(automation, 'refine_numeric_pairs', _numeric)
    config = {'refit_capture_ids': ['capture_a'], 'refit_source_identity': identity,
              'numeric_refinement': {'enabled': True}}
    first = automation.refit_pairs(project, candidate='legacy', scene_state='layout_a', config=config)
    assert first['status'] == 'REFINED_DRAFT', first
    image = next(row for row in project.evidence['images'] if row['snapshot_id'] == 'capture_a')
    pair = project.root/image['runtime_baseline']['pair_path']
    pair.write_bytes(pair.read_bytes()+b'\n')
    second = automation.refit_pairs(project, candidate='tampered', scene_state='layout_a', config=config)
    assert second['status'] == 'NEEDS_MORE_DATA' and second['code'] == 'PAIR_SOURCE_MISMATCH'
    assert not (project.root/'scratch/agent/tampered').exists()


def test_referenced_pair_corruption_keeps_the_existing_backend_needs_contract(tmp_path):
    project,_,identity,_=_fixture(tmp_path)
    image=project.evidence['images'][0];pair=project.root/image['runtime_baseline']['pair_path']
    pair.write_bytes(pair.read_bytes()+b'\n')
    result=automation.refit_pairs(project,candidate='tampered_ref',scene_state='layout_a',config={
        'refit_capture_ids':['capture_a'],'refit_source_identity':identity,'numeric_refinement':{'enabled':True}})
    assert result['status']=='NEEDS_MORE_DATA'and result['code']=='PAIR_SOURCE_MISMATCH'
    assert not(project.root/'scratch/agent/tampered_ref').exists()


@pytest.mark.parametrize('bad', ['none', 'package_sha', 'model_sha', 'mapping_sha', 'joint_order'])
def test_selection_keeps_real_source_package_and_robot_identity_guards(tmp_path, monkeypatch, bad):
    project, package, identity, _ = _fixture(tmp_path, source_robot=True)
    if bad == 'package_sha':
        (package/'manifest.json').write_bytes((package/'manifest.json').read_bytes()+b'\n')
    elif bad != 'none':
        evidence=project.evidence
        for image in evidence['images']:
            if image['snapshot_id']!='capture_a':continue
            if bad=='model_sha':image['robot_model_sha256']='0'*64
            elif bad=='mapping_sha':image['mapping_sha256']='0'*64
            else:image['joint_names']=list(reversed(image['joint_names']))
        write(project.root/'input/evidence.yaml',evidence)
    before=_immutable(project);calls=[]
    monkeypatch.setattr(automation,'refine_numeric_pairs',lambda *args:calls.append(args)or _numeric(*args))
    result=automation.refit_pairs(project,candidate='identity',scene_state='layout_a',config={
        'refit_capture_ids':['capture_a'],'refit_source_identity':identity,'numeric_refinement':{'enabled':True}})
    assert result['status']==('REFINED_DRAFT'if bad=='none'else'NEEDS_MORE_DATA'),result
    assert bool(calls)==(bad=='none')
    assert (project.root/'scratch/agent/identity/candidate.json').exists()==(bad=='none')
    assert _immutable(project)==before


@pytest.mark.parametrize('bad', ['empty_selection', 'wrong_candidate_layout', 'wrong_candidate_source'])
def test_bad_selection_cannot_rewrite_an_existing_candidate_or_its_report(tmp_path, monkeypatch, bad):
    project, _, identity, _ = _fixture(tmp_path, second_source=bad=='wrong_candidate_source')
    monkeypatch.setattr(automation,'refine_numeric_pairs',_numeric)
    config={'refit_capture_ids':['capture_a'],'refit_source_identity':identity,'numeric_refinement':{'enabled':True}}
    first=automation.refit_pairs(project,candidate='existing',scene_state='layout_a',config=config)
    assert first['status']=='REFINED_DRAFT'
    candidate=Candidate(project,'existing')
    frozen={p.relative_to(candidate.root).as_posix():sha(p)for p in candidate.root.rglob('*')if p.is_file()}
    before=_immutable(project)
    if bad=='empty_selection':config['refit_capture_ids']=[];layout='layout_a'
    else:
        config['refit_capture_ids']=['capture_b'];layout='layout_b'
        if bad=='wrong_candidate_source':
            from scene_contract.package import load_scene
            config['refit_source_identity']=asdict(load_scene(project.root/'exports/second/scene.json').identity)
    result=automation.refit_pairs(project,candidate='existing',scene_state=layout,config=config)
    assert result['status']=='NEEDS_MORE_DATA',result
    assert {p.relative_to(candidate.root).as_posix():sha(p)for p in candidate.root.rglob('*')if p.is_file()}==frozen
    assert _immutable(project)==before


def _gui_probe(tmp_path, mode):
    code = '''
import sys
from pathlib import Path
# Existing Qt package only; preserve the backend environment's NumPy/native ABI.
sys.path.append(str(Path('workbench_runs/runtime/qt/lib/python3.11/site-packages').absolute()))
from test_refit_capture_selection import gui_probe
gui_probe(Path(sys.argv[1]), sys.argv[2])
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_CONFIG_HOME=str(tmp_path/'qt-settings'))
    env['PYTHONPATH'] = os.pathsep.join([str(Path(__file__).parent.absolute()), env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-B', '-c', code, str(tmp_path), mode],
                            env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout+result.stderr


@pytest.mark.parametrize('mode', ['page_a', 'page_b', 'reuse_a', 'new_layout', 'new_source', 'no_ids', 'mixed_layout', 'mixed_source', 'missing_id', 'missing_metadata'])
def test_real_qt_selection_candidate_reuse_and_cli_backend_contract(tmp_path, mode):
    _gui_probe(tmp_path, mode)


def gui_probe(tmp_path, mode):
    from PyQt6.QtWidgets import QApplication, QAbstractItemView
    from real2sim_builder import ui_reconstruction as ui, cli
    from robot_learning_workbench.ui.real_sim_page import RealSimPage
    app = QApplication([])
    project, package, identity, rows = _fixture(tmp_path,
        second_source=mode in ('mixed_source', 'new_source'), same_layout=mode == 'mixed_source')
    before = _immutable(project)
    original_dialog = ui.ReconstructionDialog
    seen = []
    ui.ReconstructionDialog.refresh_account = lambda self: None
    if mode in ('page_a', 'page_b'):
        chosen = 0 if mode == 'page_a' else 1
        class ProbeDialog(original_dialog):
            def exec(self):
                self.timer.stop()
                self.usage_timer.stop()
                self.start.click()  # actual Qt signal -> run -> launch -> config
                assert seen, self.summary.toPlainText()
                return 0
            def start_cli(self, args):
                # Process transport boundary only; real CLI dispatch/backend below.
                path = Path(args[args.index('--config')+1])
                seen.append({'args':args, 'config':read(path)})
                assert cli.main(args) == 0
        ui.ReconstructionDialog = ProbeDialog
        RealSimPage.refresh_scenes = lambda self, force=False: None
        with patch.object(automation, 'refine_numeric_pairs', _numeric):
            page = RealSimPage(sys.executable, [], tmp_path/'workspace')
            page.stop_timers()
            page.project = {'project':str(project.root), 'name':project.info['name']}
            page.scene_combo.blockSignals(True)
            page.scene_combo.addItem('source', {'scene':str(package/'scene.json')})
            page.scene_combo.blockSignals(False)
            for row in rows:
                page.snapshot_table.append(row)
            page.snapshot_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            page.snapshot_table.selectRow(chosen)
            page.refit_button.setEnabled(True)
            page.refit_button.click()
            assert seen, page.operation_message.text()
            config = seen[0]['config']
            expected = rows[chosen]['id']
            assert config['refit_capture_ids'] == [expected], config
            assert config['scene_state_id'] == ('layout_a' if chosen == 0 else 'layout_b'), config
            report = read(project.root/'scratch/agent'/config['candidate']/'reconstruction.json')
            assert report['status'] == 'REFINED_DRAFT', report
            assert len(report['pair_diagnostics']['observations']) == 2
            assert all(expected in key for key in report['pair_diagnostics']['observations'])
            page.close()
        # The user's explicit Reconstruction Memo is the page's normal write.
        assert _immutable(project) == before
        return
    selected = ['capture_a']
    if mode == 'no_ids':
        selected = []
    elif mode in ('mixed_layout', 'mixed_source'):
        selected.append('capture_b')
    elif mode == 'missing_id':
        selected.append('not_recorded')
    elif mode == 'missing_metadata':
        evidence = project.evidence
        for image in evidence['images']:
            if image.get('snapshot_id') == 'capture_a':
                image.pop('scene_state_id')
        write(project.root/'input/evidence.yaml', evidence)
    if mode in ('no_ids', 'mixed_layout', 'mixed_source', 'missing_id', 'missing_metadata'):
        before = _immutable(project)
        rejected = False
        try:
            dialog = original_dialog(project.root, sys.executable, refit=True,
                                     source_scene=package/'scene.json', capture_ids=selected)
            try:
                dialog.configuration()
            finally:
                dialog.close()
        except ValueError:
            rejected = True
        assert rejected, 'Invalid Capture set must be rejected before choosing a layout'
        assert _immutable(project) == before
        assert not list((project.root/'scratch/agent').glob('*/candidate.json'))
        return
    # Build a real source-bound Candidate through the Backend, then exercise
    # Dialog's matching source/layout reuse decision while newer B exists.
    with patch.object(automation, 'refine_numeric_pairs', _numeric):
        report = automation.refit_pairs(project, candidate='existing_a', scene_state='layout_a', config={
            'refit_capture_ids':['capture_a'], 'refit_source_identity':identity,
            'numeric_refinement':{'enabled':True}})
    assert report['status'] == 'REFINED_DRAFT', report
    project.update(candidate='existing_a')
    candidate_before = (project.root/'scratch/agent/existing_a/candidate_scene.yaml').read_bytes()
    selected = ['capture_a'] if mode == 'reuse_a' else ['capture_b']
    chosen_package = package if mode != 'new_source' else project.root/'exports/second'
    dialog = original_dialog(project.root, sys.executable, refit=True,
                             source_scene=chosen_package/'scene.json', capture_ids=selected)
    assert (dialog.candidate.text() == 'existing_a') is (mode == 'reuse_a')
    assert dialog.configuration()['scene_state_id'] == ('layout_a' if mode == 'reuse_a' else 'layout_b')
    assert (project.root/'scratch/agent/existing_a/candidate_scene.yaml').read_bytes() == candidate_before
    assert _immutable(project) == before
    dialog.close()
