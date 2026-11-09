import json
from pathlib import Path
import pytest
from real2sim_builder import codex_cli as cli


def test_isolated_auth_environment_never_inherits_api_keys(monkeypatch,tmp_path):
    monkeypatch.setenv('HOME',str(tmp_path));monkeypatch.setenv('CODEX_HOME',str(tmp_path/'editor'))
    monkeypatch.setenv('OPENAI_API_KEY','secret');monkeypatch.delenv('REAL2SIM_CODEX_HOME',raising=False)
    env=cli.environment()
    assert env['CODEX_HOME']!=str(tmp_path/'editor') and 'OPENAI_API_KEY'not in env
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'explicit'))
    assert cli.environment()['CODEX_HOME']==str(tmp_path/'explicit')


def test_usage_keeps_buckets_and_real_windows_separate():
    data={'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':54,'windowDurationMins':300,'resetsAt':123},
         'secondary':{'usedPercent':71,'windowDurationMins':10080,'resetsAt':456}},
         'special':{'primary':{'usedPercent':99,'windowDurationMins':60,'resetsAt':789}}}}
    rows=cli.usage_windows(data)
    assert [(r['bucket'],r['remaining'],r['minutes'])for r in rows]==[('codex',46,300),('codex',29,10080),('special',1,60)]
    assert cli.usage_windows({})==[]


def test_structured_errors_not_generic_429_or_text_guess():
    assert cli.failure_code({'error':{'code':'usage_limit_reached'}})=='USAGE_LIMIT'
    assert cli.failure_code({'error':{'code':'unauthorized'}})=='AUTHENTICATION_FAILED'
    assert cli.failure_code({'error':{'code':'model_not_found'}})=='MODEL_UNAVAILABLE'
    assert cli.failure_code({'error':{'code':'network_error'}})=='NETWORK_FAILED'
    assert cli.failure_code({'error':{'message':'random quota 401 mention'}})=='MODELING_FAILED'


def test_selection_uses_official_model_efforts():
    models=[{'model':'supported','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]
    assert cli.selection_args('supported','high',models)==['--model','supported','-c','model_reasoning_effort="high"']
    with pytest.raises(ValueError):cli.selection_args('supported','ultra',models)
    with pytest.raises(ValueError):cli.selection_args('made-up','high',models)


def test_stdio_protocol_and_notification_and_close(tmp_path):
    fake=tmp_path/'codex';fake.write_text('''#!/usr/bin/env python3
import sys,json
for line in sys.stdin:
 r=json.loads(line)
 if 'id'not in r:continue
 method=r['method']
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'chatgpt','planType':'pro'}}
 elif method=='account/rateLimits/read':
  print(json.dumps({'method':'account/rateLimits/updated','params':{'rateLimits':{'primary':{'usedPercent':20,'windowDurationMins':300}}}}),flush=True)
  result={'rateLimits':{'primary':{'usedPercent':30,'windowDurationMins':300}}}
 elif method=='model/list':result={'data':[{'model':'test','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}],'nextCursor':None}
 else:result={}
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
''');fake.chmod(0o755)
    with cli.AppServer(str(fake),{'PATH':'/usr/bin:/bin','HOME':str(tmp_path),'CODEX_HOME':str(tmp_path/'auth')})as server:
        assert server.call('account/read',{'refreshToken':False})['account']['type']=='chatgpt'
        assert server.call('account/rateLimits/read')['rateLimits']['primary']['usedPercent']==30
        assert server.notifications[-1]['method']=='account/rateLimits/updated'
        child=server.child
    assert child.poll()is not None


def test_exec_selection_and_account_home_are_recorded_without_identity(tmp_path,monkeypatch):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.authoring import modeling_tasks,run_codex_modeling
    from real2sim_builder.files import read
    import sys
    p=Project.create(tmp_path/'projects','selected');c=Candidate.create(p,'same_candidate')
    modeling_tasks(c,{}, {})
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'auth'))
    monkeypatch.setenv('REAL2SIM_CODEX_MODEL','test-model');monkeypatch.setenv('REAL2SIM_CODEX_EFFORT','high')
    monkeypatch.setattr(cli,'snapshot',lambda *a:{'logged_in':True,'version':'test-cli','models':[{'model':'test-model','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]})
    fake=tmp_path/'codex';fake.write_text('#!'+sys.executable+'\n'+'''import sys,os,json
from pathlib import Path
a=sys.argv;assert a[a.index('--model')+1]=='test-model';assert 'model_reasoning_effort="high"'in a
assert os.environ['CODEX_HOME'].endswith('/auth')
r=Path(a[a.index('--cd')+1]);t=json.loads((r/'tasks.json').read_text())
assert not list(r.rglob('auth.json'))
Path(a[a.index('--output-last-message')+1]).write_text(json.dumps({'objects':[],'needs':[],'task':None,'scene_memo_sha256':t['scene_memo']['sha256']}))
''');fake.chmod(0o700)
    run_codex_modeling(c,executable=fake)
    folder=next((c.root/'modeling/codex').iterdir());record=read(folder/'runtime.json')
    assert record=={'model':'test-model','reasoning_effort':'high','cli_version':'test-cli'}
    assert 'email'not in json.dumps(record)


def test_account_switch_cannot_race_active_exec(tmp_path,monkeypatch):
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'auth'))
    with cli.auth_lock():
        with pytest.raises(RuntimeError,match='실행 중'):
            with cli.auth_lock(exclusive=True):pass
    with cli.auth_lock(exclusive=True):
        with pytest.raises(RuntimeError):
            with cli.auth_lock():pass
    with cli.auth_lock(exclusive=True):pass


def test_nonfinite_usage_is_not_a_real_remaining_limit():
    assert cli.usage_windows({'rateLimits':{'primary':{'usedPercent':float('nan')}}})==[]


def test_official_exec_error_without_code_reports_explicit_usage_limit_only():
    message='You’ve hit your usage limit. Upgrade to Pro or try again at 11:28 PM.'
    assert cli.failure_code({'type':'error','message':message})=='USAGE_LIMIT'
    assert cli.failure_code({'type':'turn.failed','error':{'message':message}})=='USAGE_LIMIT'
    assert cli.failure_code({'type':'item.completed','message':message})=='MODELING_FAILED'
    assert cli.failure_code({'type':'error','message':'A document says you hit a usage limit.'})=='MODELING_FAILED'
    assert cli.failure_code({'error':{'message':'random quota 401 mention'}})=='MODELING_FAILED'


def test_analysis_reuse_requires_original_response_and_current_evidence(tmp_path):
    from real2sim_builder.authoring import analysis_required,_codex_guidance
    from real2sim_builder.project import Project
    from real2sim_builder.files import write,sha
    p=Project.create(tmp_path/'projects','analysis cache')
    response=p.root/'scratch/answer.json';write(response,{'objects':[]})
    signature=p.signature({'assets':[]})
    config={'objects':{'cube':{'prompt':'cube'}},'scene_analysis':{'memo_sha256':signature['scene_memo_sha256'],
        'evidence_sha256':signature['evidence_sha256'],'path':'scratch/answer.json','sha256':sha(response),
        'guidance_sha256':_codex_guidance()[1]['sha256']}}
    assert not analysis_required(config,signature['scene_memo_sha256'],project=p)
    config['scene_analysis']['evidence_sha256']='changed'
    assert analysis_required(config,signature['scene_memo_sha256'],project=p)
    config['scene_analysis']['evidence_sha256']=signature['evidence_sha256']
    response.write_text('{}')
    assert analysis_required(config,signature['scene_memo_sha256'],project=p)


def test_stop_reaps_owned_tools_without_stopping_another_process(tmp_path):
    import subprocess,sys,time
    other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
    child=subprocess.Popen([sys.executable,'-c',
        'import subprocess,sys,time;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);print(p.pid,flush=True);time.sleep(30)'],
        stdout=subprocess.PIPE,text=True,start_new_session=True)
    try:
        descendant=int(child.stdout.readline());cli.stop_child(child)
        assert child.poll()is not None and other.poll()is None
        for _ in range(30):
            stat=Path('/proc')/str(descendant)/'stat'
            if not stat.exists()or stat.read_text().split()[2]=='Z':break
            time.sleep(.01)
        else:pytest.fail('owned tool survived Stop')
    finally:
        cli.stop_child(child);cli.stop_child(other);child.stdout.close()


def test_structured_auth_error_log_does_not_persist_raw_account_payload(tmp_path,monkeypatch):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.authoring import modeling_tasks,run_codex_modeling
    import sys
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'private'))
    p=Project.create(tmp_path/'projects','private log');c=Candidate.create(p,'same')
    modeling_tasks(c,{}, {})
    fake=tmp_path/'codex';fake.write_text('#!'+sys.executable+'\n'+'''import json,sys
print(json.dumps({'error':{'code':'unauthorized','message':'sensitive-account@example.invalid token=synthetic-secret'}}))
sys.exit(1)
''');fake.chmod(0o700)
    with pytest.raises(cli.CodexExecutionError)as error:run_codex_modeling(c,executable=fake)
    assert error.value.code=='AUTHENTICATION_FAILED'
    assert all('synthetic-secret'not in f.read_text()and 'sensitive-account'not in f.read_text()for f in c.root.rglob('*')if f.is_file())


def test_official_login_without_catalog_still_allows_explicit_model(tmp_path,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'private'))
    monkeypatch.setattr(cli,'capabilities',lambda p:{'version':'test-cli','app_server':False})
    monkeypatch.setattr(cli.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    result=cli.snapshot('/test/codex')
    assert result['logged_in'] and result['account']is None and result['usage']==[] and result['models']==[]
    assert result['usage_error']
    assert cli.selection_args('explicit-id',None,result['models'])==['--model','explicit-id']
