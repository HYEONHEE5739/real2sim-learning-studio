"""Owned render child transport, newest live frame and one frozen Pair request."""
from pathlib import Path
import os,time,json
import numpy as np
from PIL import Image
from ..data.native import atomic_json,file_sha256


class RenderProcess:
    """A concrete read-only render child; serial control remains in Session."""
    def __init__(self,plan,mapping):
        import subprocess,sys
        self.root=plan.output_path/'renderer';self.root.mkdir();self.engine=plan.engine;self.capture_id=None;self.last_live=None;self.last_request=0;self.number=0
        from .scene_render import SceneView
        view=SceneView(plan.resolved_inputs['scene']['path'],plan.engine,plan.resolved_inputs['engine_config']['path'],mapping)
        expected_settings=plan.resolved_inputs['engine_config']['files'][view.settings_path.name]
        if view.scene_identity!=dict(plan.scene_identity)or view.settings_sha256!=expected_settings:raise ValueError('Prepared Scene or engine settings changed before render startup')
        atomic_json(self.root/'config.json',dict(scene=str(view.path),settings=str(view.settings_path),mapping=mapping,identity=view.identity,engine=plan.engine))
        self.log=(self.root/'stdout.log').open('wb');self.process=subprocess.Popen([sys.executable,'-B','-m','robot_learning_workbench.robot.render_worker',str(self.root)],stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)

    def observe(self,q):
        now=time.monotonic_ns()
        if now-self.last_request<100_000_000:return
        self.number+=1;self.last_request=now;atomic_json(self.root/'latest.json',{'id':'live_'+str(self.number),'q':list(q),'requested_ns':now})

    def capture(self,pending):
        if self.capture_id is not None:raise ValueError('One Pair render at a time')
        self.capture_id=pending['id'];atomic_json(self.root/'capture.json',{'id':self.capture_id,'q':pending['sample']['q_measured'],'requested_ns':time.monotonic_ns()})

    def _read(self,name):
        path=self.root/name
        if not path.is_file():return None
        before=path.read_bytes();result=json.loads(before);images={}
        for camera,row in result['files'].items():
            image=Path(row['path'])
            if not image.resolve().is_relative_to(self.root.resolve()):raise ValueError('Render result escaped owned storage')
            try:
                if file_sha256(image)!=row['sha256']:return None
                images[camera]=np.asarray(Image.open(image).convert('RGB'))
            except(FileNotFoundError,OSError):return None
        if path.read_bytes()!=before:return None
        return {**result,'images':images,'result_latency_ms':(time.monotonic_ns()-result['requested_ns'])/1e6}

    def poll(self):
        if(self.root/'error.json').is_file():raise ValueError('Scene render failed: '+json.loads((self.root/'error.json').read_text())['error'])
        if self.process.poll()is not None:raise ValueError('Scene render child exited: '+str(self.process.returncode))
        live=self._read('live-result.json')
        if live is not None and (self.last_live is None or live['id']!=self.last_live['id']):
            self.last_live={k:v for k,v in live.items()if k!='images'}
            from ..data import video
            if video._preview_sink is not None:
                for n,image in live['images'].items():video._preview_sink('sim_'+n,image,live['generation'],live['sim_timestamp']['monotonic_ns']/1e9,0)
        result=self._read('capture-result.json')if self.capture_id is not None else None
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
