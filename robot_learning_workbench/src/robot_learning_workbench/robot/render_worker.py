"""One owned rendering child, one newest request and one pending paired capture."""
from pathlib import Path
import sys,time,json,os
from PIL import Image
from ..data.native import atomic_json,file_sha256


def run(root):
    from .real_sim import CandidateView,CandidateRenderer
    root=Path(root);config=json.loads((root/'config.json').read_text());launcher=None;seen={};generation=0
    try:
        if config['engine']=='isaac':
            from isaaclab.app import AppLauncher
            launcher=AppLauncher(headless=True,enable_cameras=True,device='cuda:0',fast_shutdown=False)
        view=CandidateView(config['project'],config['candidate'],config['model'],config['mapping'])
        if view.identity!=config['identity']:raise ValueError('Candidate changed before render child startup')
        with CandidateRenderer(view,config['engine'],root/'runtime')as renderer:
            atomic_json(root/'ready.json',{'ready':True,'identity':view.identity})
            while not(root/'stop').exists():
                request=None;capture=False
                for name in('capture.json','latest.json'):
                    if not(root/name).is_file():continue
                    candidate=json.loads((root/name).read_text())
                    from real2sim_builder.scene import identifier
                    if not {'id','q','requested_ns'}<=set(candidate)or set(candidate)-{'id','q','requested_ns','source_capture'}:raise ValueError('Invalid render request')
                    identifier(candidate['id'])
                    if candidate['id']!=seen.get(name):request=candidate;capture=name=='capture.json';break
                if request is None:time.sleep(.01);continue
                seen['capture.json'if capture else'latest.json']=request['id'];result=renderer.render(request['q'],source_capture=request.get('source_capture'));generation+=1
                folder=root/'captures'/request['id']if capture else root/'live'/str(generation%2);folder.mkdir(parents=True,exist_ok=True)
                files={}
                for name,rgb in result.pop('images').items():
                    path=folder/(name+'.png');temporary=path.with_suffix('.tmp.png');Image.fromarray(rgb).save(temporary);os.replace(temporary,path);files[name]={'path':str(path),'sha256':file_sha256(path)}
                result.update(id=request['id'],requested_ns=request['requested_ns'],generation=generation,files=files)
                atomic_json(root/('capture-result.json'if capture else'live-result.json'),result)
    except BaseException as error:
        atomic_json(root/'error.json',{'error':str(error)});raise
    finally:
        if launcher is not None:launcher.app.close()


if __name__=='__main__':run(sys.argv[1])
