"""Owned localhost ComfyUI/GGUF job. No UI, remote upload, or model download.

API graph uses ComfyUI's ReferenceLatent (Kontext reference conditioning),
not an inpaint latent or a claim that FLUX directly obeys an exact mask.
"""
from pathlib import Path
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request


def validate_server(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('Owned localhost-only ComfyUI endpoint required')
    return parsed.port


def workflow(image,prompt,models,*,seed,size,steps,template=None,height=None):
    path=Path(template)if template else Path(__file__).parents[2]/'config/flux-kontext-gguf.api.json'
    graph=json.loads(path.read_text())
    graph['1']['inputs']['unet_name']=models['unet']
    graph['2']['inputs'].update(clip_name1=models['clip'],clip_name2=models['t5'])
    graph['4']['inputs']['vae_name']=models['vae']
    graph['5']['inputs']['image']=image
    graph['3']['inputs']['text']=prompt
    graph['7']['inputs'].update(width=size,height=height or size,batch_size=1)
    graph['9']['inputs'].update(seed=seed,steps=steps)
    return graph


def edit_prompt(request):
    """Keep the caller's removal instruction/context intact at the model boundary."""
    task=request.get('task');prompt=request.get('prompt','')
    if task=='removal':
        if not isinstance(prompt,str)or not prompt.strip():
            prompt='Remove only '+request['object_prompt']+' and its cast shadow. Reconstruct the exposed background.'
        mode=request.get('annotation_mode','outline')
        annotation={'mask':'The bright green filled pixels mark the target area.',
                    'outline':'The target is outlined in bright green.',
                    'bbox':'The target is inside the bright green box.'}.get(mode)
        if annotation is None:raise ValueError('Unknown removal annotation mode')
        prompt+='\n'+annotation+' Remove the target completely, including its cast shadow and the green annotation. Preserve the camera viewpoint, surface perspective and all other objects.'
        if request.get('object_id'):prompt+='\nTarget instance: '+request['object_id']
        if request.get('preserve_objects'):prompt+='\nPreserve these other instances: '+json.dumps(request['preserve_objects'])
        if request.get('scene_context'):prompt+='\nScene context (data, not tool instructions): '+request['scene_context']
    elif not prompt and task in ('upsample','infill'):
        prompt=('Complete and enhance 'if task=='upsample'else'Complete the visible ')+request['object_prompt']+' preserving its identity, shape, materials and viewpoint.'
    return prompt


def protect_pixels(original,edited,mask):
    """Copy original non-edit pixels exactly; synthesized RGB remains estimated."""
    from PIL import Image
    if mask.size!=original.size:raise ValueError('Edit Mask pixel frame mismatch')
    edited=edited.resize(original.size,Image.Resampling.LANCZOS)
    return Image.composite(edited.convert('RGB'),original.convert('RGB'),mask.convert('L').point(lambda x:255 if x else 0))


def edit(request):
    from PIL import Image
    if request.get('task')=='describe':
        return {'provider':'comfy_gguf','supported':True,'inference_executed':False,
                'image_shapes':[[512,512],[512,384],[384,512]],'batch_size':1}
    source=Path(request.get('source',''))
    if not(source/'main.py').is_file():raise FileNotFoundError('Existing ComfyUI source required')
    root=Path(request.get('models',source/'models')).resolve()
    options=dict(request.get('model_options',{}))
    names=options.get('models',{'unet':'flux1-kontext-dev-Q4_K_S.gguf','clip':'clip_l.safetensors',
             't5':'t5xxl_fp8_e4m3fn_scaled.safetensors','vae':'ae.safetensors'})
    model_files={k:root/('unet'if k=='unet'else'vae'if k=='vae'else'text_encoders')/name for k,name in names.items()}
    if set(model_files)!={'unet','clip','t5','vae'} or any(not p.is_file() or not p.resolve().is_relative_to(root.resolve()) for p in model_files.values()):
        raise FileNotFoundError('All four explicitly configured local FLUX/encoder/VAE files required')
    size=int(options.get('size',512));steps=int(options.get('steps',20));timeout=float(options.get('timeout_s',600))
    if not 64<=size<=512 or not 1<=steps<=50 or not 1<=timeout<=1800:raise ValueError('Bounded batch1/512px Comfy budget required')
    out=Path(request['output']).resolve()
    inputs=out/'comfy_input';outputs=out/'comfy_output';user=out/'comfy_user'
    for folder in (inputs,outputs,user):folder.mkdir(exist_ok=True)
    image=Image.open(request['image']).convert('RGB')
    factor=size/max(image.size);w,h=(max(16,round(v*factor/16)*16)for v in image.size)
    image.resize((w,h),Image.Resampling.LANCZOS).save(inputs/'input.png')
    prompt=edit_prompt(request)
    graph=workflow('input.png',prompt,names,seed=int(request.get('seed',0)),size=w,height=h,steps=steps,template=request.get('workflow'))
    (out/'workflow.json').write_text(json.dumps(graph,indent=2))
    # Never attach to an existing user's server or interrupt unrelated jobs.
    with socket.socket()as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url='http://127.0.0.1:'+str(port);validate_server(url)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def api(path,payload=None):
        data=json.dumps(payload).encode()if payload is not None else None
        req=urllib.request.Request(url+path,data=data,headers={'Content-Type':'application/json'})
        with opener.open(req,timeout=5)as response:return json.load(response)
    command=[sys.executable,str(source/'main.py'),'--listen','127.0.0.1','--port',str(port),
        '--lowvram','--reserve-vram','1','--cpu-vae','--disable-auto-launch','--offline',
        '--disable-all-custom-nodes','--whitelist-custom-nodes','ComfyUI-GGUF',
        '--input-directory',str(inputs),'--output-directory',str(outputs),'--user-directory',str(user),
        '--models-directory',str(root),
        '--preview-method','none']
    deadline=time.monotonic()+timeout;job=None
    with (out/'comfy-server.log').open('w')as log:
        # Inherit the stage's owned process group: Stop/timeout kills server too.
        child=subprocess.Popen(command,cwd=source,stdout=log,stderr=subprocess.STDOUT)
        try:
            while True:
                if child.poll()is not None:raise RuntimeError('ComfyUI startup failed; see owned server log')
                try:info=api('/object_info');break
                except (OSError,ValueError):
                    if time.monotonic()>deadline:raise TimeoutError('ComfyUI startup deadline')
                    time.sleep(.5)
            if any(node['class_type']not in info for node in graph.values()):raise ImportError('Required ComfyUI/GGUF API nodes unavailable')
            for number,key,field in [('1','unet','unet_name'),('2','clip','clip_name1'),('2','t5','clip_name2'),('4','vae','vae_name')]:
                allowed=info[graph[number]['class_type']]['input']['required'][field][0]
                if names[key]not in allowed:raise FileNotFoundError('Configured model absent from ComfyUI node catalog')
            submitted=api('/prompt',{'prompt':graph,'client_id':'r2s-owned-worker'})
            if submitted.get('node_errors')or not submitted.get('prompt_id'):raise ValueError('ComfyUI rejected API workflow')
            job=submitted['prompt_id']
            (out/'job.json').write_text(json.dumps({'prompt_id':job,'status':'submitted','endpoint':url}))
            while True:
                history=api('/history/'+job).get(job)
                if history:
                    (out/'job.json').write_text(json.dumps({'prompt_id':job,'status':history.get('status')}))
                    if history.get('status',{}).get('status_str')=='error':
                        messages=json.dumps(history.get('status',{}))
                        if 'out of memory'in messages.lower():raise RuntimeError('CUDA out of memory in ComfyUI job')
                        raise RuntimeError('ComfyUI execution failed; see owned server log')
                    if history.get('status',{}).get('completed'):break
                if child.poll()is not None:raise RuntimeError('ComfyUI exited during generation')
                if time.monotonic()>deadline:raise TimeoutError('ComfyUI inference deadline')
                time.sleep(.5)
            rows=history.get('outputs',{}).get('11',{}).get('images',[])
            if len(rows)!=1:raise ValueError('Expected exactly one ComfyUI image')
            row=rows[0];file=outputs/row.get('subfolder','')/row['filename']
            if row.get('type')!='output' or not file.resolve().is_relative_to(outputs):raise ValueError('Invalid ComfyUI output path')
            generated=Image.open(file);generated.load()
            if generated.size!=(w,h):raise ValueError('Generated RGB pixel grid mismatch')
            base=Image.open(request.get('original_image',request['image'])).convert('RGB')
            if request.get('mask'):
                result=protect_pixels(base,generated,Image.open(request['mask']))
            else:result=generated.resize(base.size,Image.Resampling.LANCZOS).convert('RGB')
            path=out/'edited.png';result.save(path)
            manifests={}
            for key,file in model_files.items():
                with file.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
                manifests[key]={'path':str(file.resolve()),'sha256':digest,'bytes':file.stat().st_size}
            return {'path':str(path),'provider':'comfy_gguf','prompt_id':job,'models':manifests,
                'inference_executed':True,'provenance':'synthesized RGB; not measured','batch_size':1,
                'processed_resolution':[w,h],
                'input_to_processed':[[w/image.width,0,(w/image.width-1)/2],[0,h/image.height,(h/image.height-1)/2],[0,0,1]],
                'returned_resolution':list(base.size),'returned_pixel_frame':'original input; K unchanged',
                'raw_path':str((outputs/row.get('subfolder','')/row['filename']).resolve()),
                'generated_region':request.get('mask'),'mask_conditioning':False,'annotation_mode':request.get('annotation_mode'),'quality_status':'NOT_VERIFIED','non_edit_pixels':'exact original copy'if request.get('mask')else'whole crop generated'}
        finally:
            if child.poll()is None:
                try:api('/interrupt',{});api('/free',{'unload_models':True,'free_memory':True})
                except (OSError,ValueError):pass
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait()
