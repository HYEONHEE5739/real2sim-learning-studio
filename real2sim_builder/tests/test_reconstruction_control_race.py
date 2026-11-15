"""Deterministic real control writer/consumer interleavings; no reconstruction.

Read hooks recognize command payloads, including a future claimed-file path.
They never manufacture a command or bypass Project.control's actual writer.
"""
import pytest

from real2sim_builder import project as module
from real2sim_builder.candidate import exclusive
from real2sim_builder.project import Project


@pytest.mark.parametrize('paused',[False,True],ids=['checkpoint','pause_loop'])
def test_new_stop_written_after_resume_read_is_preserved_or_consumed(tmp_path,monkeypatch,paused):
    project=Project.create(tmp_path,'control race');project.update(status='RUNNING')
    project.control('pause'if paused else'resume')
    original_read=module.read;seen=[];sleeps=[]
    def read_then_stop(path):
        payload=original_read(path)
        if isinstance(payload,dict)and payload.get('command')=='resume'and not seen:
            seen.append('resume-read');project.control('stop')
        return payload
    def resume_at_pause_boundary(seconds):
        sleeps.append(seconds)
        assert len(sleeps)<4,'Pause loop lost the resume or stop command'
        if len(sleeps)==1:
            assert project.state['status']=='PAUSED';project.control('resume')
    monkeypatch.setattr(module,'read',read_then_stop)
    if paused:monkeypatch.setattr(module.time,'sleep',resume_at_pause_boundary)
    stopped=False
    try:project.checkpoint()
    except InterruptedError:stopped=True
    assert seen==['resume-read']
    if not stopped:
        pending=project.root/'working/control.json'
        assert pending.is_file(),'Unread newer Stop was deleted by an older Resume consumer'
        assert original_read(pending)['command']=='stop'
        with pytest.raises(InterruptedError):project.checkpoint()
    # A processed stop is not replayed on a later checkpoint.
    project.checkpoint()
    assert not(project.root/'working/control.json').exists()


def test_pause_resume_stop_remain_available_while_worker_owns_project_lock(tmp_path,monkeypatch):
    project=Project.create(tmp_path,'locked control');project.update(status='RUNNING')
    def resume(_):
        assert project.state['status']=='PAUSED'
        project.control('resume')
    monkeypatch.setattr(module.time,'sleep',resume)
    with exclusive(project):
        assert(project.root/'working/run.lock').is_file()
        project.control('pause');project.checkpoint()
        assert project.state['status']=='RUNNING'
        project.control('stop')
        with pytest.raises(InterruptedError):project.checkpoint()
    assert not(project.root/'working/run.lock').exists()


def test_normal_and_repeated_control_commands_do_not_corrupt_project_or_replay(tmp_path):
    project=Project.create(tmp_path,'commands');project.update(status='RUNNING')
    project.checkpoint();project.control('resume');project.control('resume');project.checkpoint()
    assert project.state['status']=='RUNNING'
    project.control('stop');project.control('stop')
    with pytest.raises(InterruptedError):project.checkpoint()
    project.checkpoint()
    project.control('stop');path=project.root/'working/control.json';before=path.read_bytes()
    with pytest.raises(ValueError):project.control('unknown')
    assert path.read_bytes()==before


def test_readonly_inspection_cannot_consume_or_replace_control(tmp_path):
    owner=Project.create(tmp_path,'readonly');owner.control('stop')
    read_only=Project(owner.root,read_only=True)
    before={str(path.relative_to(owner.root)):path.read_bytes()for path in owner.root.rglob('*')if path.is_file()}
    with pytest.raises(PermissionError):read_only.control('resume')
    with pytest.raises(PermissionError):read_only.checkpoint()
    assert before=={str(path.relative_to(owner.root)):path.read_bytes()for path in owner.root.rglob('*')if path.is_file()}
