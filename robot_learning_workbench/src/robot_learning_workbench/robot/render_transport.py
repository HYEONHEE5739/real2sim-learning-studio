"""Owned render child transport, newest live frame and one frozen Pair request."""
from pathlib import Path
import os,time,json
import numpy as np
from PIL import Image
from ..data.native import atomic_json,file_sha256,encoded


def write_preview(path,value):
    """Replace disposable live IPC atomically; durable Capture files use atomic_json."""
    temporary=path.with_name(path.name+'.pending')
    try:temporary.write_bytes(encoded(value));os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


class RenderProcess:
    """Owned simulation child; real serial control remains in Session."""
    def __init__(self,plan,mapping):
        import subprocess,sys
        self.startup_times_ns={'parent_started':time.monotonic_ns()}
        self.root=plan.output_path/'renderer';self.root.mkdir();self.engine=plan.engine;self.capture_id=None;self.last_live=None;self.last_request=0;self.number=0;self.ready=None
        # Prepare/connect already verified the plan. The child loads SceneView
        # before declaring ready; the control owner need not build a second view.
        scene=Path(plan.resolved_inputs['scene']['path']);settings=Path(plan.resolved_inputs['engine_config']['path'])
        expected_settings=plan.resolved_inputs['engine_config']['files'][settings.name]
        if file_sha256(settings)!=expected_settings:raise ValueError('Prepared engine settings changed before render startup')
        identity=dict(scene=dict(plan.scene_identity),settings_sha256=expected_settings,mapping_sha256=mapping['sha256'],engine=plan.engine)
        atomic_json(self.root/'config.json',dict(scene=str(scene),settings=str(settings),mapping=mapping,identity=identity,engine=plan.engine))
        self.startup_times_ns['parent_inputs_checked']=time.monotonic_ns()
        self.log=(self.root/'stdout.log').open('wb');self.process=subprocess.Popen([sys.executable,'-B','-m','robot_learning_workbench.robot.render_worker',str(self.root)],stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)
        self.startup_times_ns['spawned']=time.monotonic_ns()

    def observe(self,q):
        now=time.monotonic_ns()
        if now-self.last_request<100_000_000:return
        self.number+=1;self.last_request=now;write_preview(self.root/'latest.json',{'id':'live_'+str(self.number),'q':list(q),'requested_ns':now})

    def capture(self,pending):
        if self.capture_id is not None:raise ValueError('One Pair render at a time')
        self.capture_id=pending['id'];atomic_json(self.root/'capture.json',{'id':self.capture_id,'q':pending['sample']['q_measured'],'requested_ns':time.monotonic_ns()})

    def prioritize_capture(self,pending):
        path=self.root/'capture-priority'
        if pending:
            if not path.exists():path.touch()
        else:path.unlink(missing_ok=True)

    def _read(self,name,*,previous_id=None,decode=True):
        read_started=time.monotonic_ns();sha_duration=0;path=self.root/name
        if not path.is_file():return None
        before=path.read_bytes();result=json.loads(before);images={}
        if result['id']==previous_id:return None
        for camera,row in result['files'].items():
            image=Path(row['path'])
            if not image.resolve().is_relative_to(self.root.resolve()):raise ValueError('Render result escaped owned storage')
            try:
                begin=time.monotonic_ns();actual_sha=file_sha256(image);sha_duration+=time.monotonic_ns()-begin
                if actual_sha!=row['sha256']:return None
                if decode:images[camera]=np.asarray(Image.open(image).convert('RGB'))
            except(FileNotFoundError,OSError):return None
        if path.read_bytes()!=before:return None
        # Missing historical worker timestamps stay missing; never invent them.
        verified=time.monotonic_ns();timing=dict(result.get('render_transport_times_ns',{}))
        timing.update(parent_read_started=read_started,parent_verified=verified,parent_sha_duration=sha_duration)
        return {**result,'images':images,'result_latency_ms':(verified-result['requested_ns'])/1e6,
            'render_transport_times_ns':timing}

    def poll(self):
        if self.ready is None and(self.root/'ready.json').is_file():self.ready=json.loads((self.root/'ready.json').read_text())
        if(self.root/'error.json').is_file():raise ValueError('Scene render failed: '+json.loads((self.root/'error.json').read_text())['error'])
        if self.process.poll()is not None:raise ValueError('Scene render child exited: '+str(self.process.returncode))
        live=self._read('live-result.json',previous_id=self.last_live['id']if self.last_live is not None else None)
        if live is not None and (self.last_live is None or live['id']!=self.last_live['id']):
            self.last_live={k:v for k,v in live.items()if k!='images'}
            from ..data import video
            if video._preview_sink is not None:
                for n,image in live['images'].items():video._preview_sink('sim_'+n,image,live['generation'],live['sim_timestamp']['monotonic_ns']/1e9,0)
        # Frozen PNGs are decoded by the save process, not the interpreter that
        # also schedules serial control. Live preview decoding stays unchanged.
        result=self._read('capture-result.json',decode=False)if self.capture_id is not None else None
        if result is not None and result['id']==self.capture_id:self.capture_id=None;return result

    def release_capture(self,identifier):
        # Scratch cleanup cannot turn an already published observation into failure.
        import shutil
        from real2sim_builder.scene import identifier as validate_id
        validate_id(identifier);warnings=[]
        try:shutil.rmtree(self.root/'captures'/identifier)
        except FileNotFoundError:pass
        except OSError as error:warnings.append(str(error))
        try:
            path=self.root/'capture-result.json'
            if path.is_file()and json.loads(path.read_text()).get('id')==identifier:path.unlink()
        except (OSError,ValueError)as error:warnings.append(str(error))
        return warnings

    def close(self):
        import signal,subprocess
        (self.root/'stop').touch()
        try:
            if self.process.poll()is None:
                try:self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid,signal.SIGTERM)
                    try:self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait(timeout=5)
        finally:self.log.close()
