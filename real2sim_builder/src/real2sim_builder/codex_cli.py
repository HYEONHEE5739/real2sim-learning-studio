"""Official local Codex authentication/catalog/usage boundary. No credential file reads.

Account data stays in memory. The same explicit CODEX_HOME is used by login,
App Server and exec. This module never performs inference to query usage.
"""
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time
from functools import lru_cache
from contextlib import contextmanager


def environment():
    allowed=('PATH','HOME','LANG','LC_ALL','TERM','TMPDIR','SSL_CERT_FILE','SSL_CERT_DIR','DISPLAY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS')
    env={k:v for k,v in os.environ.items()if k in allowed}
    home=Path(os.environ.get('REAL2SIM_CODEX_HOME',str(Path.home()/'.local/share/real2sim-builder/codex'))).expanduser().resolve()
    env['CODEX_HOME']=str(home)
    return env


def executable():
    path=shutil.which('codex')
    if not path:raise RuntimeError('설치된 codex CLI를 찾을 수 없습니다.')
    return path


@lru_cache(maxsize=8)
def capabilities(program):
    env=environment()
    Path(env['CODEX_HOME']).mkdir(parents=True,exist_ok=True,mode=0o700)
    def run(args):
        r=subprocess.run([program,*args],env=env,capture_output=True,text=True,timeout=10)
        if r.returncode:raise RuntimeError('Codex CLI 인터페이스 미지원: '+' '.join(args))
        return r.stdout+r.stderr
    version=run(['--version']).splitlines()[0].strip()
    login=run(['login','--help']);run(['login','status','--help']);run(['logout','--help'])
    help_text=run(['exec','--help'])
    try:server=run(['app-server','--help'])
    except RuntimeError:server=''
    for flag in ('--ignore-user-config','--model','--ephemeral','--output-schema','--json'):
        if flag not in help_text:raise RuntimeError('Codex CLI 필수 옵션 미지원: '+flag)
    return {'version':version,'device_auth':'--device-auth'in login,'app_server':'--listen'in server}


def stop_child(child):
    # The owned process group can outlive its leader (CLI shell/tool children).
    try:os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:child.wait(timeout=3)
    except subprocess.TimeoutExpired:pass
    try:os.killpg(child.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    child.wait()


class AppServer:
    """Short-lived JSON-RPC stdio client; use from a background worker only."""
    def __init__(self,program,env,timeout=20):
        self.program=program;self.env=env;self.timeout=timeout;self.serial=0
        self.notifications=[];self.buffer=b''
    def __enter__(self):
        self.child=subprocess.Popen([self.program,'app-server','--listen','stdio://'],env=self.env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
        self.selector=selectors.DefaultSelector();self.selector.register(self.child.stdout,selectors.EVENT_READ)
        try:
            self.call('initialize',{'clientInfo':{'name':'real2sim_builder','version':'1'},'capabilities':{'experimentalApi':False}})
            self.send({'method':'initialized','params':{}})
        except BaseException:
            self.__exit__(None,None,None);raise
        return self
    def send(self,value):
        self.child.stdin.write((json.dumps(value)+'\n').encode());self.child.stdin.flush()
    def call(self,method,params=None):
        self.serial+=1;request=self.serial
        self.send({'id':request,'method':method,'params':params or {}})
        deadline=time.monotonic()+self.timeout
        while time.monotonic()<deadline:
            if b'\n'not in self.buffer:
                if not self.selector.select(min(.2,max(0,deadline-time.monotonic()))):continue
                data=os.read(self.child.stdout.fileno(),65536)
                if not data:raise RuntimeError('Codex App Server 연결 종료')
                self.buffer+=data
                if len(self.buffer)>8*1024*1024:raise RuntimeError('Codex App Server 응답 크기 초과')
                continue
            line,self.buffer=self.buffer.split(b'\n',1)
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('id')==request:
                if 'error'in value:raise RuntimeError('Codex App Server '+method+' 조회 실패 (code '+str(value['error'].get('code'))+')')
                return value.get('result',{})
            if value.get('method')=='account/rateLimits/updated':self.notifications.append(value)
            self.notifications=self.notifications[-8:]
        raise TimeoutError('Codex App Server '+method+' 응답 시간 초과')
    def __exit__(self,*_):
        stop_child(self.child);self.selector.close()
        for stream in (self.child.stdin,self.child.stdout):stream.close()


def usage_windows(response):
    buckets=response.get('rateLimitsByLimitId')
    if not buckets:
        single=response.get('rateLimits')
        buckets={single.get('limitId')or'codex':single}if single else{}
    rows=[]
    for key,bucket in buckets.items():
        for slot in ('primary','secondary'):
            window=bucket.get(slot)
            if not isinstance(window,dict):continue
            used=window.get('usedPercent')
            if isinstance(used,bool)or not isinstance(used,(float,int))or not math.isfinite(used):continue
            rows.append({'bucket':key,'name':bucket.get('limitName')or key,'model':bucket.get('normalModelSlug'),
                'remaining':max(0,min(100,100-used)),'minutes':window.get('windowDurationMins'),
                'resets_at':window.get('resetsAt'),'reached':bucket.get('rateLimitReachedType')})
    return rows


def snapshot(program=None):
    with auth_lock():return _snapshot(program)


def _snapshot(program=None):
    program=program or executable();info=capabilities(program);env=environment()
    home=Path(env['CODEX_HOME']);home.mkdir(parents=True,exist_ok=True,mode=0o700)
    status=subprocess.run([program,'login','status'],env=env,capture_output=True,timeout=10)
    result={'version':info['version'],'logged_in':status.returncode==0,'account':None,'models':[],
            'usage':[],'usage_error':None,'models_error':None}
    if not info.get('app_server',True):
        result.update(usage_error='Codex App Server 조회 미지원',models_error='지원 모델 ID를 직접 입력하세요.')
        return result
    with AppServer(program,env)as server:
        try:account=server.call('account/read',{'refreshToken':False}).get('account')
        except (RuntimeError,TimeoutError):
            result.update(usage_error='계정 API 조회 불가',models_error='모델 목록 조회 불가')
            return result
        result['account']={k:account.get(k)for k in ('type','email','planType')}if account else None
        result['logged_in']=bool(account) and result['logged_in']
        if result['logged_in']:
            try:result['usage']=usage_windows(server.call('account/rateLimits/read'))
            except (RuntimeError,TimeoutError)as error:result['usage_error']=str(error)
            server.notifications.clear()
            try:
                cursor=None
                for _ in range(20):
                    page=server.call('model/list',{'cursor':cursor,'limit':100,'includeHidden':False})
                    result['models'].extend(page.get('data',[]));cursor=page.get('nextCursor')
                    if not cursor:break
            except (RuntimeError,TimeoutError)as error:result['models_error']=str(error);result['models']=[]
            if server.notifications:
                # Updates are sparse; refetch instead of combining unrelated buckets/windows.
                try:result['usage']=usage_windows(server.call('account/rateLimits/read'))
                except (RuntimeError,TimeoutError):result.update(usage=[],usage_error='사용량 갱신 조회 불가')
    return result


def selection_args(model,effort,models):
    if not isinstance(model,str)or not model.strip()or any(c.isspace()for c in model):raise ValueError('Codex 모델 ID를 입력하세요.')
    row=next((m for m in models if m['model']==model),None)
    if models and row is None:raise ValueError('현재 계정의 모델 목록에서 지원되지 않는 모델입니다.')
    args=['--model',model]
    if effort:
        if row is None or effort not in {r['reasoningEffort']for r in row['supportedReasoningEfforts']}:
            raise ValueError('이 모델에서 지원되는 추론 강도를 선택하세요.')
        args+=['-c','model_reasoning_effort='+json.dumps(effort)]
    return args


def failure_code(event):
    """Classify explicit structured codes, never an incidental number in text."""
    error=event.get('error',event)
    if not isinstance(error,dict):return 'MODELING_FAILED'
    code=error.get('code')or error.get('type')or error.get('codexErrorInfo')
    if isinstance(code,dict):code=next(iter(code),'')
    # CLI 0.166 may omit the code in a formal error/turn.failed event. Match
    # only its observed leading limit sentence, never generic quota keywords
    # in model/tool output. Do not persist account-specific reset/link text.
    if event.get('type')in('error','turn.failed')and not code:
        message=error.get('message','')
        if isinstance(message,str)and message.startswith(('You’ve hit your usage limit.','You\'ve hit your usage limit.')):return 'USAGE_LIMIT'
    if code=='error'and event.get('type')=='error':
        message=error.get('message','')
        if isinstance(message,str)and message.startswith(('You’ve hit your usage limit.','You\'ve hit your usage limit.')):return 'USAGE_LIMIT'
    return {'usage_limit_reached':'USAGE_LIMIT','usageLimitExceeded':'USAGE_LIMIT',
        'quota_exceeded':'USAGE_LIMIT','unauthorized':'AUTHENTICATION_FAILED',
        'authentication_error':'AUTHENTICATION_FAILED','model_not_found':'MODEL_UNAVAILABLE',
        'model_access_denied':'MODEL_UNAVAILABLE','network_error':'NETWORK_FAILED',
        'streamConnectionFailed':'NETWORK_FAILED','httpConnectionFailed':'NETWORK_FAILED'}.get(code,'MODELING_FAILED')


class CodexExecutionError(RuntimeError):
    def __init__(self,code):
        self.code=code
        super().__init__({'USAGE_LIMIT':'Codex 사용량 한도 도달. 계정 전환 또는 초기화 후 이어서 실행하세요.',
            'AUTHENTICATION_FAILED':'Codex 로그인이 필요합니다.', 'MODEL_UNAVAILABLE':'선택한 Codex 모델에 접근할 수 없습니다.',
            'NETWORK_FAILED':'Codex 네트워크 연결 실패.'}.get(code,'Codex 실행 실패. 저장된 Candidate에서 재개할 수 있습니다.'))


@contextmanager
def auth_lock(*,exclusive=False):
    """Prevent account switching while any Builder Codex exec owns this home."""
    import fcntl
    home=Path(environment()['CODEX_HOME']);home.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (home/'.builder-auth.lock').open('a')as stream:
        try:fcntl.flock(stream,fcntl.LOCK_NB|(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH))
        except BlockingIOError:raise RuntimeError('다른 Builder Codex 작업이 실행 중입니다. 종료 후 계정을 전환하세요.')from None
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def sandbox_args(work):
    """Workspace writes, offline tools, no credential/home reads (official profile)."""
    home=environment()['CODEX_HOME']
    fs={':minimal':'read',str(Path(work).resolve()):'write',str(Path(home)/'auth.json'):'deny',
        str(Path(home)/'tmp'):'read',str(Path(executable()).resolve().parent.parent):'read'}
    table='{'+','.join(json.dumps(k)+'='+json.dumps(v)for k,v in fs.items())+'}'
    return ['-c','default_permissions="builder"','-c','permissions.builder.filesystem='+table,
            '-c','permissions.builder.network.enabled=false','-c','web_search="disabled"',
            '-c','shell_environment_policy.exclude=["CODEX_HOME","OPENAI_API_KEY"]']
