"""Read-only, offline presentation of completed Candidate stage artifacts."""
import argparse
import html
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .files import read, sha
from .stage_artifacts import StageArtifact, STAGE_NAMES


def esc(value):
    return html.escape(str(value), quote=True)


def details(label, value):
    return f'<details><summary>{esc(label)}</summary><pre>{esc(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>'


def picture(url, label):
    return f'<figure><a href="{esc(url)}"><img loading="lazy" src="{esc(url)}"></a><figcaption>{esc(label)}</figcaption></figure>'


def scalar_map(values):
    finite = np.isfinite(values)
    if not finite.any():
        raise ValueError('No finite samples')
    low, high = np.percentile(values[finite], [2, 98])
    t = np.zeros(values.shape)
    t[finite] = np.clip((values[finite]-low)/max(high-low, 1e-12), 0, 1)
    colors = np.stack([t, 1-abs(2*t-1), 1-t], axis=-1)
    colors[~finite] = 0
    return Image.fromarray(np.uint8(colors*255)), (float(low), float(high))


def cloud_view(points, label, segments=()):
    pts=np.asarray(points).reshape(-1,3)
    pts=pts[np.isfinite(pts).all(axis=1)]
    if not len(pts):
        return '<p>NOT_AVAILABLE</p>'
    sample=pts[::max(1,int(np.ceil(len(pts)/5000)))]
    data=json.dumps({'points':sample.round(6).tolist(),'lines':list(segments)},allow_nan=False)
    return f'<figure><canvas width="600" height="380" data-cloud="{esc(data)}"></canvas><figcaption>{esc(label)} · 드래그 회전 / 휠 확대</figcaption></figure>'


_SCRIPT = """
for(const c of document.querySelectorAll('canvas[data-cloud]')){
 const d=JSON.parse(c.dataset.cloud),p=d.points,g=c.getContext('2d');
 const lo=[0,1,2].map(i=>Math.min(...p.map(q=>q[i]))),hi=[0,1,2].map(i=>Math.max(...p.map(q=>q[i])));
 const mid=lo.map((v,i)=>(v+hi[i])/2),span=Math.max(.00001,...hi.map((v,i)=>v-lo[i]));
 let a=.45,b=.35,z=1;
 function xy(q){let [x,y,h]=q.map((v,i)=>(v-mid[i])*320*z/span);
 return [300+x*Math.cos(a)-y*Math.sin(a),190+(x*Math.sin(a)+y*Math.cos(a))*Math.sin(b)-h*Math.cos(b)]}
 function draw(){g.fillStyle='#101b25';g.fillRect(0,0,600,380);g.fillStyle='#69c8bc';
 for(const q of p){let [x,y]=xy(q);g.fillRect(x,y,2,2)}
 for(const [s,t,color] of d.lines){g.strokeStyle=color;g.beginPath();g.moveTo(...xy(s));g.lineTo(...xy(t));g.stroke()}}
 c.onpointerdown=e=>c.setPointerCapture(e.pointerId);
 c.onpointermove=e=>{if(c.hasPointerCapture(e.pointerId)){a+=e.movementX*.01;b+=e.movementY*.01;draw()}};
 c.onwheel=e=>{e.preventDefault();z=Math.max(.1,Math.min(16,z*Math.exp(-e.deltaY*.001)));draw()};draw()
}
for(const check of document.querySelectorAll('input[data-layer]')){
 check.onchange=()=>document.getElementById(check.dataset.layer).hidden=!check.checked;
}
"""


def generate(candidate, output):
    candidate,output=Path(candidate).resolve(),Path(output).resolve()
    if output.is_relative_to(candidate):
        raise ValueError('Dashboard output must be a new directory outside the Candidate')
    return _render(candidate,output)


def publish(candidate):
    """Publish only derived evidence for a Candidate owned by the active writer."""
    import os
    import tempfile
    evidence=candidate/'evidence'
    previews=evidence/'previews'
    previews.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=evidence) as temporary:
        page=_render(candidate,Path(temporary)/'view')
        document=page.read_text(encoding='utf8')
        records=json.loads((page.parent/'sources.json').read_text())
        for record in records:
            file=page.parent/record['preview']
            destination=previews/(record['sha256']+file.suffix)
            if not destination.exists() or sha(destination)!=record['sha256']:
                os.replace(file,destination)
            relative=destination.relative_to(evidence).as_posix()
            for attr in ('src','href'):
                document=document.replace(f'{attr}="{file.name}"',f'{attr}="{relative}"')
            record['preview']=relative
        manifest=Path(temporary)/'sources.json'
        manifest.write_text(json.dumps(records,indent=2),encoding='utf8')
        dest=previews/('sources-'+sha(manifest)+'.json')
        os.replace(manifest,dest)
        page.write_text(document+'<p><a href="'+dest.relative_to(evidence).as_posix()+'">Preview sources (SHA256)</a></p>',encoding='utf8')
        os.replace(page,evidence/'index.html')
    return evidence/'index.html'


def _render(candidate,output):
    root=candidate/'reconstruction/simfoundry'
    cache=read(root/'cache.json')
    report=read(candidate/'reconstruction.json') if (candidate/'reconstruction.json').is_file() else {}
    output.mkdir(parents=True,exist_ok=False)
    allowed={}
    provenance=[]
    depth_file=None
    times=[]
    timing=root/'timing.jsonl'
    if timing.is_file():
        for line in timing.read_text().splitlines():
            try:times.append(json.loads(line))
            except ValueError:continue  # Interrupted append. Never infer a duration.
    def source(name):
        path=Path(name)
        if path not in allowed:
            raise ValueError('File is outside verified stage outputs: '+path.name)
        return path
    def save(image,name,origin):
        image.save(output/name)
        provenance.append({'preview':name,'sha256':sha(output/name),'source':str(origin),'source_sha256':allowed[origin]})
        return name
    pages=[]
    for stage,title in enumerate(STAGE_NAMES,1):
        start=time.monotonic()
        entry=cache.get(str(stage),{})
        failed=report.get('failed_stage')==stage
        status=report.get('status') if failed else 'NOT_AVAILABLE'
        content=[]
        if failed:
            content.append(details('진단',report.get('gate') or report.get('error') or report.get('needs')))
        try:
            if entry.get('artifact') and not failed:
                path=Path(entry['artifact'])
                if path.name!='artifact.json' or path.resolve()!=path or path.parent.parent!=root/f'stage_{stage:02d}':
                    raise ValueError('Unexpected stage artifact path')
                artifact=StageArtifact(**read(path)).validate(path.parent)
                if artifact.stage_id!=stage:raise ValueError('Stage identity mismatch')
                allowed.update({Path(r['path']):r['sha256'] for r in artifact.output_manifest['files']})
                payload=artifact.output_manifest['data']
                status='REUSED' if report.get('stages',{}).get(str(stage),{}).get('reused') else artifact.status
                content.append(f'<p>{esc(artifact.coordinate_frame)} · {esc(artifact.provenance["execution"])}</p>')
                content.append(f'<a href="{esc(path.as_uri())}">Stage Artifact</a> · <code>{sha(path)}</code>')
                if stage==2:
                    depth_file=source(payload['prediction'])
                    with np.load(depth_file,allow_pickle=False) as arr:
                        depths,confidence,images=arr['depth'],arr['conf'],arr['image']
                        for i,(depth,conf,rgb) in enumerate(zip(depths,confidence,images)):
                            label=payload['frames'][i]['id']
                            content.append(picture(save(Image.fromarray(rgb),f'rgb-{i}.png',depth_file),label+' · processed RGB'))
                            for name,v in [('estimated optical Z (m)',depth),('confidence',conf)]:
                                im,bounds=scalar_map(v)
                                filename=f'{"z" if v is depth else "conf"}-{i}.png'
                                content.append(picture(save(im,filename,depth_file),f'{label} · {name} · blue → red {bounds}'))
                            counts,edges=np.histogram(depth[np.isfinite(depth)],bins=24)
                            content.append(details(label+' · Depth distribution / K / W2C',
                                {'bin_edges_m':edges.tolist(),'counts':counts.tolist(),'K':arr['intrinsics'][i].tolist(),
                                 'W2C':arr['extrinsics'][i].tolist(),'original_to_processed':payload['original_to_processed'][i]}))
                if stage==3 and depth_file:
                    support=source(payload['support_masks'])
                    frames=(payload.get('semantic_preview') or {}).get('frames',[])
                    with np.load(depth_file) as pred,np.load(support) as masks:
                        for i,(rgb,mask) in enumerate(zip(pred['image'],masks['masks'])):
                            layers=[('support',mask,support)]
                            for row in (frames[i]['associations'] if i<len(frames) else []):
                                if row.get('mask'):
                                    origin=source(row['mask'])
                                    with Image.open(origin) as im: layers.append((row['id'],np.array(im.convert('L')),origin))
                            controls=[];stack=f'<img src="rgb-{i}.png">'
                            for j,(name,m,origin) in enumerate(layers):
                                if m.shape!=rgb.shape[:2]:raise ValueError('Mask pixel grid mismatch')
                                rgba=np.zeros((*m.shape,4),np.uint8)
                                rgba[m.astype(bool)]=[(47+83*j)%255,(220+57*j)%255,(125+117*j)%255,120]
                                lid=f'mask-{i}-{j}'
                                save(Image.fromarray(rgba),lid+'.png',origin)
                                stack+=f'<img id="{lid}" src="{lid}.png">'
                                controls.append(f'<label><input type="checkbox" data-layer="{lid}" checked>{esc(name)}</label>')
                            content.append('<div>'+''.join(controls)+'</div><div class="stack">'+stack+'</div>')
                if stage==4:
                    with np.load(source(payload['world_points'])) as a:
                        points=a['points'];matrix=a['support_from_da3']
                    extent=float(np.nanpercentile(abs(points[np.isfinite(points)]),80))
                    lines=[([0,0,0],(np.eye(3)[j]*extent).tolist(),color) for j,color in enumerate(['red','lime','skyblue'])]
                    corners=[[x*extent,y*extent,0] for x,y in [(-1,-1),(1,-1),(1,1),(-1,1)]]
                    lines.extend((corners[j-1],corners[j],'gray') for j in range(4))
                    if depth_file:
                        with np.load(depth_file) as a:
                            for e in a['extrinsics']:
                                pose=matrix@np.linalg.inv(np.vstack((e,[0,0,0,1])))
                                lines.append((pose[:3,3].tolist(),(pose[:3,3]+pose[:3,2]*extent/4).tolist(),'orange'))
                    content.append(cloud_view(points,'Support frame · model estimated m · Z=0 / cameras',lines))
                if stage in range(5,9):
                    for i,obj in enumerate(payload.get('objects',[])):
                        content.append('<h3>'+esc(obj['id'])+'</h3>')
                        plan=obj.get('geometry_build_plan') or {}
                        content.append('<p>'+esc(plan.get('route','NOT_RECORDED'))+' · '+esc(plan.get('reason',''))+'</p>')
                        content.append(details('제작 계획 및 관측',obj))
                        if stage==5:
                            with np.load(source(obj['observed'])) as a:
                                mask=a['mask'].astype(bool)
                                content.append(picture(source(obj['mask']).as_uri(),'Object mask'))
                                content.append(picture(source(obj['observed_rgb']).as_uri(),'Observed RGB · iteration '+str(obj['iteration'])))
                                original=mask & (a['depth_source']==0)
                                if original.any():
                                    depth,bounds=scalar_map(np.where(original,a['depth'],np.nan))
                                    image=save(depth,f'object-z-{i}.png',source(obj['observed']))
                                    content.append(picture(image,'Original estimated Z (m) · '+str(bounds)))
                        if stage==6 and obj.get('crops'):
                            path_rgba=source(obj['crops']['focus']['path'])
                            with Image.open(path_rgba) as rgba:
                                alpha=save(rgba.getchannel('A'),f'alpha-{i}.png',path_rgba)
                            content.append(picture(path_rgba.as_uri(),'Observed focus RGBA')+picture(alpha,'Observed alpha'))
                        if stage in (7,8):
                            from .calibration.geometry import mesh_data
                            v,f=mesh_data(source(obj['mesh']))
                            if stage==7:
                                faces=f[::max(1,int(np.ceil(len(f)/1800)))]
                                lines=[(v[tri[j-1]].tolist(),v[tri[j]].tolist(),'#849dad') for tri in faces for j in range(3)]
                                content.append(cloud_view(v,'Object local geometry',lines))
                            elif obj.get('fit'):
                                fit=obj['fit']
                                with np.load(source(obj['observed'])) as a:
                                    im=Image.fromarray(a['image']);k=a['K']
                                draw=ImageDraw.Draw(im)
                                rotation=np.asarray(fit['rotation'])@np.asarray(obj['canonicalization']['rotation'])
                                pts=(v*fit['scale'])@rotation.T+fit['translation']
                                uv=pts@k.T
                                for x,y,z in uv[uv[:,2]>0][::max(1,len(v)//5000)]:
                                    draw.point((x/z,y/z),fill=(0,255,220))
                                name=f'fit-{i}.png'
                                im.save(output/name)
                                provenance.append({'preview':name,'sha256':sha(output/name),'artifact_sha256':sha(path)})
                                content.append(picture(name,'Estimated fit · observed grid'))
                if stage==5:
                    original=next((Path(r['path']) for r in artifact.output_manifest['files']
                                   if Path(r['path']).name=='initial.png'),None)
                    for row in payload.get('removal_history',[]):
                        edited=source(row['rgb_after'])
                        if original:
                            content.append('<div class="pair">'+picture(source(original).as_uri(),'Before · '+row['removed'])+
                                           picture(edited.as_uri(),'After · '+row['removed'])+'</div>')
                        original=edited
                if stage in (10,11):
                    from .scene import local_path,world_pose
                    from .calibration.hybrid import surface_mesh
                    scene=read(source(payload['scene']))
                    project=candidate.parents[2]
                    for asset in scene['assets'].values():
                        file=local_path(project,asset['path'])
                        if sha(file)!=asset['sha256']:raise ValueError('Scene dependency changed: '+file.name)
                    for field in (['visual'] if stage==10 else ['visual','collision']):
                        vertices=[];lines=[]
                        for obj in scene['objects']:
                            if obj[field]['type']=='unknown' or (field=='collision' and obj.get('collision_enabled') is False):continue
                            if obj['dimensions'].get('value') is None or obj['pose'].get('value') is None:continue
                            mesh=surface_mesh({**obj,'visual':obj[field]},scene,project)
                            mesh.apply_transform(world_pose(scene,obj))
                            v,f=np.asarray(mesh.vertices),np.asarray(mesh.faces)
                            vertices.extend(v[::max(1,len(v)//600)])
                            for tri in f[::max(1,len(f)//180)]:
                                lines.extend((v[tri[j-1]].tolist(),v[tri[j]].tolist(),'#8ac2cd') for j in range(3))
                        for cam in scene['cameras']:
                            if cam['pose'].get('value') is None:continue
                            t=world_pose(scene,cam)
                            lines.append((t[:3,3].tolist(),(t[:3,3]+t[:3,2]*.05).tolist(),'orange'))
                        if vertices:content.append(cloud_view(vertices,field+' · compiled scene / camera axes',lines))
                if stage==12:
                    for row in artifact.output_manifest['files']:
                        trajectory=Path(row['path'])
                        if trajectory.name=='physics-pose-history.npz':
                            with np.load(trajectory) as history:
                                for name in history.files:
                                    poses=history[name]
                                    if poses.ndim==3 and poses.shape[1:]==(4,4):
                                        content.append(cloud_view(poses[:,:3,3],name+' · recorded positions'))
                if stage==14:
                    content.append('<p>Real/Sim paired comparison &amp; measured q · NOT_AVAILABLE</p>')
                for row in artifact.output_manifest['files']:
                    image=Path(row['path'])
                    if image.suffix.lower() in ('.png','.jpg','.jpeg'):
                        content.append(picture(image.as_uri(),str(image.relative_to(path.parent))))
                content.append(details('계산 결과 및 검증',payload))
            elif failed and report.get('failure_artifact'):
                failure=Path(report['failure_artifact'])
                if (failure.name!='artifact.json' or failure.resolve()!=failure or
                        failure.parent.parent!=root/'failures'/('stage_'+str(stage))):
                    raise ValueError('Unexpected failure artifact path')
                record=StageArtifact(**read(failure)).validate(failure.parent)
                if record.stage_id!=stage:raise ValueError('Failure stage identity mismatch')
                for row in record.output_manifest['files']:
                    file=Path(row['path'])
                    if file.name in ('geometry_build_plan.json','object_progress.json','frame-selection.json'):
                        content.append(details(file.name,read(file)))
                    if file.suffix.lower()=='.png':
                        content.append(picture(file.as_uri(),file.name+' · partial'))
                content.append(f'<a href="{esc(failure.as_uri())}">Failure Artifact</a> · {sha(failure)}')
            elif entry.get('pending') and not failed:
                status='RUNNING' if report.get('status')=='RUNNING' else 'INCOMPLETE'
        except Exception as error:
            content.append('<p>Preview unavailable · '+esc(error)+'</p>')
        events=[r for r in times if r.get('stage')==stage]
        if events:
            from collections import Counter
            counts=Counter((r['operation'],r['status'],r.get('execution')) for r in events if r['operation']!='stage')
            content.append(details('Worker 호출 집계',{' / '.join(map(str,k)):v for k,v in counts.items()}))
        content.append(details('실행 시간 및 Worker 호출',events or 'NOT_RECORDED'))
        pages.append(f'<section id="s{stage}"><h2>{stage}. {esc(title)}</h2><p>{esc(status)} · Accuracy NOT_VERIFIED</p>'+
                     ''.join(content)+f'<small>Preview {time.monotonic()-start:.3f} s</small></section>')
    nav=' '.join(f'<a href="#s{i}">{i}</a>' for i in range(1,15))
    page='''<!doctype html><meta charset="utf-8"><title>Reconstruction Evidence</title><style>
body{background:#14202b;color:#eef5fc;font:16px system-ui;margin:2rem}nav{position:sticky;top:0;background:#14202b;padding:12px;z-index:2}
a{color:#70e1db;margin-right:8px}section{scroll-margin-top:60px;border-top:1px solid #587080;padding:1rem}
figure{display:inline-block;max-width:100%;margin:8px}img,canvas{max-width:100%;height:auto}figure img{max-height:230px}
.stack{position:relative;width:480px;max-width:100%}.stack img{width:100%;display:block}.stack img+img{position:absolute;inset:0}.stack img[hidden]{display:none}
.pair{display:flex;gap:8px}.pair figure{max-width:48%}pre,code{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:8px 0}canvas{touch-action:none}</style>'''
    (output/'index.html').write_text(page+'<h1>Reconstruction Evidence</h1><nav>'+nav+'</nav>'+''.join(pages)+'<script>'+_SCRIPT+'</script>',encoding='utf8')
    (output/'sources.json').write_text(json.dumps(provenance,indent=2),encoding='utf8')
    return output/'index.html'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate');parser.add_argument('output')
    args=parser.parse_args()
    print(generate(args.candidate,args.output))
