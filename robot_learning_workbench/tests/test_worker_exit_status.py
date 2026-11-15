"""Task publication and observed process exit are separate R03 facts."""
from dataclasses import asdict
import hashlib
import json
import signal
import subprocess
import sys

import pytest

from robot_learning_workbench import run


def terminal_record(folder, status, *, error=None):
    folder.mkdir()
    record = dict(status=status, phase='terminal', progress={'tick': 3},
                  last_event_seq=2, error=error, output_refs=['published'])
    run._atomic(folder / 'run.json', record)
    run._atomic(folder / 'result.json', dict(run_id='exit-test', status=status,
                                           output_refs=['published'], error=error))
    return record


@pytest.mark.parametrize(('task_status', 'code'), [
    ('completed', 0), ('completed', 7), ('failed', 3),
    ('cancelled', 0), ('cancelled', 9),
])
def test_observed_exit_is_independent_of_published_task_result(tmp_path, task_status, code):
    folder = tmp_path / 'worker'
    error = {'code': 'TASK_FAILED', 'message': 'task failure', 'issues': [], 'effect': 'unknown'} if task_status == 'failed' else None
    record = terminal_record(folder, task_status, error=error)
    original = {name: (folder / name).read_bytes() for name in ('run.json', 'result.json')}
    with subprocess.Popen([sys.executable, '-B', '-c', f'raise SystemExit({code})']) as child:
        run._monitor(child, folder)
    status = run.read_status(folder)
    assert child.returncode == code
    assert status.status == task_status and status.error == error
    assert status.progress == record['progress'] and status.last_event_seq == 2
    assert status.exit_code == code
    assert (status.process_error is None) == (code == 0)
    if code:
        assert str(code) in status.process_error['message']
    assert json.loads((folder / 'process_exit.json').read_text())['exit_code'] == code
    assert {name: (folder / name).read_bytes() for name in original} == original


def test_terminal_status_before_process_exit_does_not_invent_zero(tmp_path):
    folder = tmp_path / 'worker'
    terminal_record(folder, 'completed')
    with subprocess.Popen([sys.executable, '-B', '-c', 'import sys; sys.stdin.read()'], stdin=subprocess.PIPE) as child:
        try:
            status = run.read_status(folder)
            assert child.poll() is None
            assert status.status == 'completed' and status.exit_code is None
            assert status.process_error is None
            assert asdict(status)['exit_code'] is None
            assert not (folder / 'process_exit.json').exists()
        finally:
            child.stdin.close()
            child.wait(timeout=10)
        run._monitor(child, folder)
    assert run.read_status(folder).exit_code == 0


@pytest.mark.parametrize('task_status', ['completed', 'failed', 'cancelled'])
def test_legacy_terminal_records_remain_readable_with_unknown_exit(tmp_path, task_status):
    folder = tmp_path / 'legacy'
    error = {'code': 'OLD_FAILURE', 'message': 'old task error'} if task_status == 'failed' else None
    terminal_record(folder, task_status, error=error)
    before = (folder / 'run.json').read_bytes()
    status = run.read_status(folder)
    assert status.status == task_status and status.error == error
    assert status.exit_code is None and status.process_error is None
    assert (folder / 'run.json').read_bytes() == before
    assert not (folder / 'process_exit.json').exists()


@pytest.mark.parametrize('code', [0, 7])
def test_exit_without_terminal_task_record_keeps_existing_failure_contract(tmp_path, code):
    folder = tmp_path / 'unfinished'
    folder.mkdir()
    run._status(folder, 'running', 'running')
    with subprocess.Popen([sys.executable, '-B', '-c', f'raise SystemExit({code})']) as child:
        run._monitor(child, folder)
    status = run.read_status(folder)
    assert status.status == 'failed' and status.phase == 'terminal'
    assert status.error['code'] == 'WORKER_EXITED'
    assert status.exit_code == code


def test_signal_termination_preserves_the_actual_negative_exit_code(tmp_path):
    folder = tmp_path / 'worker'
    terminal_record(folder, 'completed')
    with subprocess.Popen([sys.executable, '-B', '-c',
                           'import os,signal; os.kill(os.getpid(),signal.SIGTERM)']) as child:
        run._monitor(child, folder)
    status = run.read_status(folder)
    assert child.returncode == -signal.SIGTERM
    assert status.status == 'completed' and status.exit_code == -signal.SIGTERM
    assert status.process_error is not None


def test_nonzero_shutdown_does_not_invalidate_an_atomically_published_native_dataset(tmp_path):
    from robot_learning_workbench.data import native
    from test_native_dataset import episode, execution

    writer = native.NativeRun(tmp_path / 'published', execution())
    segment = writer.segment('saved')
    segment.write_episode(episode(), episode_id='recorded')
    segment.commit()
    writer.close()
    catalog = native.load_catalog(writer.root)
    identity = catalog.identity
    actions = native.read_array(catalog.episodes[0], 'actions').copy()
    files = {str(path.relative_to(writer.root)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in writer.root.rglob('*') if path.is_file()}
    folder = tmp_path / 'worker'
    terminal_record(folder, 'completed')
    with subprocess.Popen([sys.executable, '-B', '-c', 'raise SystemExit(7)']) as child:
        run._monitor(child, folder)
    status = run.read_status(folder)
    assert status.status == 'completed' and status.exit_code == 7
    current = native.load_catalog(writer.root, expected=identity)
    assert current.identity == identity and len(current.episodes) == 1
    assert native.read_array(current.episodes[0], 'actions').tobytes() == actions.tobytes()
    assert {str(path.relative_to(writer.root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in writer.root.rglob('*') if path.is_file()} == files


@pytest.mark.parametrize('raw', ['{', '{"exit_code":null}', '{"exit_code":true}'])
def test_invalid_exit_metadata_cannot_turn_a_published_result_into_successful_shutdown(tmp_path, raw):
    folder = tmp_path / 'worker'
    terminal_record(folder, 'completed')
    (folder / 'process_exit.json').write_text(raw)
    before = (folder / 'run.json').read_bytes()
    state = run.read_status(folder)
    assert state.status == 'completed' and state.error is None
    assert state.exit_code is None and state.process_error['code'] == 'WORKER_EXIT_UNKNOWN'
    assert (folder / 'run.json').read_bytes() == before
