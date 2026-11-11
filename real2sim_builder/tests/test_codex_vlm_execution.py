"""Small owned fake CLI repros; no account or online inference."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from real2sim_builder import codex_cli,authoring
from real2sim_builder.files import read


def fake_job(tmp_path,monkeypatch,body):
    program=tmp_path/'codex';program.write_text('#!'+sys.executable+'\n'+body);program.chmod(0o755)
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'auth'))
    monkeypatch.setenv('REAL2SIM_CODEX_MODEL','vision');monkeypatch.setenv('REAL2SIM_CODEX_EFFORT','high')
    monkeypatch.setattr(codex_cli,'executable',lambda:str(program))
    monkeypatch.setattr(codex_cli,'capabilities',lambda _:dict(version='fake',images=True,structured_output=True,vlm_policy=True))
    monkeypatch.setattr(codex_cli,'snapshot',lambda _:dict(logged_in=True,models=[dict(model='vision',inputModalities=['image'],supportedReasoningEfforts=[dict(reasoningEffort='high')])]))
    image=tmp_path/'cup.png';Image.new('RGB',(12,8)).save(image)
    candidate=SimpleNamespace(project=SimpleNamespace(root=tmp_path/'project',checkpoint=lambda:None))
    request={'images':[str(image)],'task':'test','context':{'memo':'INLINE_MEMO_SENTINEL'},'prompt':'Inspect attached image',
      'response_schema':{'type':'object','properties':{'removed':{'type':'string','enum':['yes','no']}},'required':['removed'],'additionalProperties':False}}
    return candidate,request,tmp_path/'job'


def test_visual_context_is_inline_with_technical_shell_disable(tmp_path,monkeypatch):
    c,r,out=fake_job(tmp_path,monkeypatch,'''import sys,json
from pathlib import Path
a=sys.argv
assert 'shell_tool'in a and '--disable'in a
assert any(x.startswith('model_instructions_file=')for x in a)
assert 'INLINE_MEMO_SENTINEL'in a[-1]
assert 'Read BUILDER_GUIDE.md and tasks.json'not in a[-1]
assert any('permissions.builder.filesystem='in x and '=\"write\"'not in x for x in a)
Path(a[a.index('--output-last-message')+1]).write_text('{"removed":"no"}')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':2}}))
''')
    assert authoring.run_codex_vlm(c,r,out)['answer']=={'removed':'no'}
    assert read(out/'events.json')['turn_completed'] is True


def test_timeout_keeps_timeline_and_discards_partial_answer(tmp_path,monkeypatch):
    c,r,out=fake_job(tmp_path,monkeypatch,'''import sys,json,time
from pathlib import Path
a=sys.argv
Path(a[a.index('--output-last-message')+1]).write_text('{"removed":')
print(json.dumps({'type':'turn.started'}),flush=True)
print(json.dumps({'type':'item.completed','item':{'id':'item_1','type':'command_execution','status':'completed','exit_code':0,'command':'echo SECRET_ACCOUNT','aggregated_output':'PRIVATE'}}),flush=True)
time.sleep(10)
''')
    with pytest.raises(TimeoutError):authoring.run_codex_vlm(c,r,out,timeout_s=.25)
    assert not(out/'answer.json').exists() and read(out/'status.json')['code']=='TIMEOUT'
    events=read(out/'events.json')
    assert events['events'][0]['event']=='process.started'
    assert events['events'][-1]['event']=='process.exited'
    assert any(e['event']=='parent.timeout'for e in events['events'])
    assert all('elapsed_s'in e for e in events['events'])
    assert 'SECRET_ACCOUNT'not in (out/'events.json').read_text() and 'PRIVATE'not in(out/'events.json').read_text()


@pytest.mark.parametrize('scenario',['last_message_only','completed_missing_file','invalid_schema','invalid_json','auth','quota'])
def test_output_completion_cases_do_not_hide_missing_or_invalid_json(tmp_path,monkeypatch,scenario):
    body='''import sys,json
from pathlib import Path
a=sys.argv;scenario=SCENARIO
answer=Path(a[a.index('--output-last-message')+1])
if scenario=='last_message_only':answer.write_text('{"removed":"yes"}')
elif scenario=='invalid_schema':answer.write_text('{"removed":true}')
elif scenario=='invalid_json':answer.write_text('{"removed":')
if scenario in ('auth','quota'):
 print(json.dumps({'type':'turn.failed','error':{'code':'unauthorized'if scenario=='auth'else'quota_exceeded','message':'PRIVATE_ACCOUNT'}}))
 raise SystemExit(1)
if scenario!='last_message_only':print(json.dumps({'type':'turn.completed'}))
'''.replace('SCENARIO',repr(scenario))
    c,r,out=fake_job(tmp_path,monkeypatch,body)
    if scenario=='last_message_only':
        assert authoring.run_codex_vlm(c,r,out)['answer']['removed']=='yes'
        assert read(out/'events.json')['turn_completed']is False
        assert read(out/'status.json')['status']=='COMPLETE'
    else:
        with pytest.raises(Exception)as caught:authoring.run_codex_vlm(c,r,out)
        assert read(out/'status.json')['status']=='FAILED' and not(out/'answer.json').exists()
        if scenario in('auth','quota'):
            assert read(out/'status.json')['code']==('AUTHENTICATION_FAILED'if scenario=='auth'else'USAGE_LIMIT'), (type(caught.value).__name__,str(caught.value))
        assert 'PRIVATE_ACCOUNT'not in(out/'events.json').read_text()
    assert not(out/'worker-cache.json').exists()  # Owned orchestrator alone publishes successful Worker manifests.


def test_interrupt_discards_partial_answer_and_records_owned_exit(tmp_path,monkeypatch):
    c,r,out=fake_job(tmp_path,monkeypatch,'''import sys,json,time
from pathlib import Path
a=sys.argv;Path(a[a.index('--output-last-message')+1]).write_text('{"removed":')
print(json.dumps({'type':'turn.started'}),flush=True);time.sleep(10)
''')
    calls=[]
    def checkpoint():
        calls.append(1)
        if len(calls)>2:raise InterruptedError('test stop')
    c.project.checkpoint=checkpoint
    with pytest.raises(InterruptedError):authoring.run_codex_vlm(c,r,out)
    assert read(out/'status.json')['status']=='STOPPED'and not(out/'answer.json').exists()
    events=read(out/'events.json')['events']
    assert any(x['event']=='parent.interrupted'for x in events)
    assert events[-1]['event']=='process.exited'


def test_visual_policy_changes_cache_identity_and_keeps_stage7_writer(tmp_path,monkeypatch):
    from real2sim_builder.stage_runtime import identity
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'auth'))
    monkeypatch.setenv('REAL2SIM_CODEX_MODEL','vision')
    original=authoring.visual_policy;before=identity({},'vlm')
    monkeypatch.setattr(authoring,'visual_policy',lambda guide:original(guide)+'Changed trusted policy')
    assert identity({},'vlm')!=before
    assert any('="write"'in arg for arg in codex_cli.sandbox_args(tmp_path))
    assert all('="write"'not in arg for arg in codex_cli.sandbox_args(tmp_path,read_only=True))


def test_completed_valid_output_is_not_lost_while_cli_shutdown_hangs(tmp_path,monkeypatch):
    c,r,out=fake_job(tmp_path,monkeypatch,'''import sys,json,time
from pathlib import Path
a=sys.argv;Path(a[a.index('--output-last-message')+1]).write_text('{"removed":"yes"}')
print(json.dumps({'type':'turn.completed'}),flush=True);time.sleep(10)
''')
    monkeypatch.setattr(codex_cli,'COMPLETED_EXIT_GRACE_S',.1,raising=False)
    result=authoring.run_codex_vlm(c,r,out,timeout_s=.8)
    assert result['answer']=={'removed':'yes'}
    events=read(out/'events.json')
    assert events['turn_completed'] and any(x['event']=='completed_output.exit_grace'for x in events['events'])
    assert read(out/'status.json')['status']=='COMPLETE'
