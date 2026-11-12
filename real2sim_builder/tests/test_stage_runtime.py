import sys
from pathlib import Path
import pytest
from real2sim_builder.stage_artifacts import StageNeeds


def test_unconfigured_runtime_identity_never_scans_cwd_or_user_files(monkeypatch):
    from real2sim_builder.stage_runtime import identity
    def forbidden(*a,**k):raise AssertionError('An absent path must not scan the working directory')
    monkeypatch.setattr(Path,'rglob',forbidden)
    assert identity({},'da3')['files']=={}
    with pytest.raises(ValueError,match='credentials'):
        identity({'runtimes':{'vlm':{'model_options':{'api_key':'DO_NOT_PERSIST'}}}},'vlm')


def test_vram_gate_prevents_worker_launch_and_keeps_explicit_budget(tmp_path,monkeypatch):
    from real2sim_builder import stage_runtime,inference
    from test_stage_pipeline import synthetic_project
    from real2sim_builder.candidate import Candidate
    p=synthetic_project(tmp_path);c=Candidate.create(p,'test')
    config={'runtimes':{'da3':{'python':sys.executable}}}
    monkeypatch.setattr(stage_runtime.subprocess,'check_output',lambda *a,**kw:'3000\n')
    monkeypatch.setattr(inference,'_run_worker',lambda *a,**kw:pytest.fail('No worker may start below the VRAM gate'))
    with pytest.raises(StageNeeds,match='Insufficient free VRAM'):
        stage_runtime.invoke(c,config,'da3',{'images':['synthetic']*8,'process_res':336},tmp_path/'worker')


def test_public_default_enters_stages_without_retired_sfm_or_codex_composition(tmp_path,monkeypatch):
    from real2sim_builder.automation import reconstruct
    from real2sim_builder import inference,authoring
    from real2sim_builder.project import Project
    p=Project.create(tmp_path/'projects','default')
    def forbidden(*a,**kw):pytest.fail('Retired/default Codex Scene composition must not execute')
    monkeypatch.setattr(inference,'run_models',forbidden)
    monkeypatch.setattr(authoring,'run_codex_modeling',forbidden)
    r=reconstruct(p,candidate='new',config={})
    assert r['pipeline']=='simfoundry/1'and r['failed_stage']==1 and r['status']=='NEEDS_MORE_DATA'


def test_credentials_are_rejected_before_any_candidate_configuration_is_written(tmp_path):
    from real2sim_builder.automation import reconstruct
    from real2sim_builder.project import Project
    p=Project.create(tmp_path/'projects','no secrets')
    with pytest.raises(ValueError,match='credentials'):
        reconstruct(p,candidate='new',config={'runtimes':{'vlm':{'model_options':{'api_key':'DO_NOT_PERSIST'}}}})
    assert not(p.root/'scratch/agent/new').exists()


def test_cached_stage_cannot_hide_a_changed_candidate_asset_payload(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    from test_stage_pipeline import synthetic_project,MockModels
    from real2sim_builder.candidate import Candidate
    p=synthetic_project(tmp_path);c=Candidate.create(p,'test');asset=tmp_path/'metadata.txt';asset.write_text('original')
    linked=c.asset(asset);worker=MockModels()
    _run_stage_pipeline(p,candidate='test',config={},worker=worker,through_stage=2)
    Path(linked['path']).write_text('changed')
    with pytest.raises(ValueError,match='hash changed'):
        _run_stage_pipeline(p,candidate='test',config={},worker=worker,through_stage=2)
    assert worker.calls==['da3']


@pytest.mark.parametrize('cancel',['stop','timeout'])
def test_actual_stage_entrypoint_owned_group_stops_and_times_out(tmp_path,monkeypatch,cancel):
    import os,time,signal,psutil
    from real2sim_builder.inference import _run_worker
    from real2sim_builder import stage_workers
    from real2sim_builder.project import Project
    p=Project.create(tmp_path/'projects','owned stage');pidfile=tmp_path/'pid.txt'
    wrapper=tmp_path/'python-wrapper'
    wrapper.write_text('#!'+sys.executable+'\nimport os,time,subprocess,sys\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\nPath('+repr(str(pidfile))+').write_text(str(os.getpid())+" "+str(p.pid))\ntime.sleep(30)\n')
    wrapper.chmod(0o700)
    def checkpoint():
        if cancel=='stop'and pidfile.exists():raise InterruptedError('synthetic stage Stop')
    monkeypatch.setattr(p,'checkpoint',checkpoint)
    error=InterruptedError if cancel=='stop'else TimeoutError
    with pytest.raises(error):_run_worker(p,wrapper,'cpd',{},tmp_path/'owned',1.,entrypoint=Path(stage_workers.__file__))
    assert pidfile.exists()
    pids=[int(v)for v in pidfile.read_text().split()]
    for pid in pids:
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            try:status=psutil.Process(pid).status()
            except psutil.NoSuchProcess:break
            if status==psutil.STATUS_ZOMBIE:break
            time.sleep(.01)  # Observe delivery of SIGTERM/SIGKILL, not scheduler timing.
        else:pytest.fail('Owned process remained alive after worker group cleanup')
    assert(tmp_path/'owned/request.json').is_file()


def test_actual_missing_dependency_worker_returns_runtime_record(tmp_path):
    from real2sim_builder.stage_workers import main
    import importlib.util,json
    # Isolated child uses the current configured test Python, which lacks probreg.
    from real2sim_builder.stage_runtime import invoke
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    p=Project.create(tmp_path/'projects','dependency result');c=Candidate.create(p,'test')
    folder=tmp_path/'missing'
    with pytest.raises(StageNeeds,match='unavailable'):
        invoke(c,{'runtimes':{'pose':{'python':sys.executable}}},'cpd',{'mesh':'not opened','points':'not opened'},folder)
    assert json.loads((folder/'result.json').read_text())['status']=='NEEDS_RUNTIME'
