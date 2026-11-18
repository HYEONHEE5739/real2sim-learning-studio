"""One owned rendering child, one newest request and one pending paired capture."""
from pathlib import Path
import sys,time,json,os
from PIL import Image
from ..data.native import atomic_json,file_sha256
from .render_transport import write_preview


def run(root):
    from .scene_render import SceneView,create_renderer
    startup=dict(worker_entered=time.monotonic_ns())
    root=Path(root);config=json.loads((root/'config.json').read_text());launcher=None;seen={};generation=0
    try:
        if config['engine']=='isaac':
            from ..engines.isaac.env_cfg import prepare_camera_schema
            prepare_camera_schema();startup['camera_schema_registered']=time.monotonic_ns()
            from isaaclab.app import AppLauncher
            launcher=AppLauncher(headless=True,enable_cameras=True,device='cuda:0',fast_shutdown=False)
        view=SceneView(config['scene'],config['engine'],config['settings'],config['mapping'])
        startup['scene_loaded']=time.monotonic_ns()
        if view.identity!=config['identity']:raise ValueError('Scene changed before render child startup')
        comparison=view.simulation_mode=='pose'
        if comparison:
            from .pose_render import create_pose_renderer
        factory=create_pose_renderer if comparison else create_renderer
        startup['renderer_started']=time.monotonic_ns()
        with factory(view,root/'runtime')as renderer:
            startup['renderer_initialized']=time.monotonic_ns()
            interval=1/30 if comparison else renderer.control_dt_s
            atomic_json(root/'ready.json',{'ready':True,'identity':view.identity,'render_type':view.render_type,'physics_enabled':not comparison,
                'startup_times_ns':startup,'renderer_times_ns':getattr(renderer,'initialization_times_ns',{})})
            last_target=None;next_step=time.monotonic();previous_job=None
            while not(root/'stop').exists():
                request=None;capture=False
                for name in('capture.json','latest.json'):
                    if name=='latest.json'and(root/'capture-priority').exists():continue
                    if not(root/name).is_file():continue
                    candidate=json.loads((root/name).read_text())
                    from real2sim_builder.scene import identifier
                    if not {'id','q','requested_ns'}<=set(candidate)or set(candidate)-{'id','q','requested_ns'}:raise ValueError('Invalid render request')
                    identifier(candidate['id'])
                    if candidate['id']!=seen.get(name):request=candidate;request_read_ns=time.monotonic_ns();capture=name=='capture.json';break
                now=time.monotonic()
                if now<next_step:time.sleep(min(.01,next_step-now));continue
                if request is None:
                    if last_target is not None and not comparison:
                        renderer.advance(last_target);next_step=now+renderer.control_dt_s
                    else:time.sleep(.01)
                    continue
                seen['capture.json'if capture else'latest.json']=request['id'];last_target=request['q']
                # Same sequential scheduling; retain boundaries needed to distinguish
                # an in-flight live render from frozen-render computation and IPC.
                timing=dict(requested=request['requested_ns'],request_read=request_read_ns,
                    render_started=time.monotonic_ns(),previous_job=previous_job,png={})
                result=renderer.render(last_target);timing['render_completed']=time.monotonic_ns();generation+=1;next_step=now+interval
                folder=root/'captures'/request['id']if capture else root/'live'/str(generation%2);folder.mkdir(parents=True,exist_ok=True)
                files={}
                for name,rgb in result.pop('images').items():
                    path=folder/(name+'.png');temporary=path.with_suffix('.tmp.png');row=dict(encode_started=time.monotonic_ns())
                    Image.fromarray(rgb).save(temporary,compress_level=1);os.replace(temporary,path);row['encoded']=time.monotonic_ns()
                    row['sha_started']=time.monotonic_ns();files[name]={'path':str(path),'sha256':file_sha256(path)};row['sha_completed']=time.monotonic_ns();timing['png'][name]=row
                timing['result_ready']=time.monotonic_ns()
                result.update(id=request['id'],requested_ns=request['requested_ns'],generation=generation,files=files,render_transport_times_ns=timing)
                if capture:atomic_json(root/'capture-result.json',result)
                else:write_preview(root/'live-result.json',result)
                previous_job=dict(id=request['id'],capture=capture,render_started=timing['render_started'],
                    render_completed=timing['render_completed'],result_ready=timing['result_ready'],published=time.monotonic_ns())
    except BaseException as error:
        atomic_json(root/'error.json',{'error':str(error)});raise
    finally:
        if launcher is not None:launcher.app.close()


if __name__=='__main__':run(sys.argv[1])
