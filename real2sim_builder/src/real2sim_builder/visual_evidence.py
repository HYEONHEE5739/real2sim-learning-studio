"""Candidate-owned visual work records; only actual files become evidence.

This is storage/display for the existing authoring loop, not another runner.
Input images and immutable library assets stay at their protected source paths.
"""
from pathlib import Path
import copy
import html
import shutil
import hashlib
import json
import os
from .files import read,write,sha
from .candidate import exclusive
from .scene import identifier
from scene_contract.naming import numbered_path


def run_identity(candidate):
    from .authoring import _codex_guidance
    signature=candidate.project.signature(candidate.scene)
    memo=candidate.root/'reconstruction_memo.json'
    return hashlib.sha256(json.dumps([signature['scene_memo_sha256'],signature['evidence_sha256'],candidate.info.get('source_revision'),sha(memo)if memo.is_file()else None,_codex_guidance()[1]['sha256']],sort_keys=True).encode()).hexdigest()


def record(candidate,stage,status,*,images=(),files=(),summary='',details=None):
    """Append one durable attempt; never overwrite earlier results or invent renders."""
    identifier("stage_"+stage)
    if status not in ('RUNNING','COMPLETE','FAILED','STOPPED','REUSED','NOT_VERIFIED','NEEDS_MORE_DATA'):
        raise ValueError('Unknown visual evidence status')
    prepared=[]
    for kind,paths in (('images',images),('files',files)):
        for raw in paths:
            path=Path(raw)
            if not path.is_absolute():path=candidate.root/path
            if path.is_symlink()or any(p.is_symlink()for p in path.parents if p!=candidate.project.root.parent):
                raise ValueError('Evidence symlink is forbidden')
            if not path.resolve().is_relative_to(candidate.project.root.resolve()):
                from .scene import local_path
                try:checked=local_path(candidate.project.root,os.path.relpath(path,candidate.project.root))
                except ValueError:raise ValueError('Evidence is outside Project')from None
                if checked.resolve()!=path.resolve():raise ValueError('Evidence is outside Project')
            if not path.is_file():raise ValueError('Missing evidence file: '+str(path))
            if kind=='images':
                from PIL import Image
                with Image.open(path)as image:image.verify()
            prepared.append((kind,path,sha(path)))
    with exclusive(candidate.project):
        candidate.require_open();root=candidate.root/'evidence'
        index=read(root/'index.json')if(root/'index.json').is_file()else{'schema':'real2sim.visual-evidence/1','candidate':candidate.name,'stages':[]}
        base=root/stage
        if stage=='02_object_modeling'and(details or{}).get('object_id'):
            base=base/identifier(details['object_id'])
        folder=numbered_path(base,'attempt');folder.mkdir(parents=True)
        row={'id':stage,'status':status,'path':folder.relative_to(root).as_posix(),'summary':str(summary),
             'details':copy.deepcopy(details or{}),'images':[],'files':[],'physical_verified':False,'run_identity':run_identity(candidate)}
        tasks=candidate.root/'modeling/tasks.json'
        if tasks.is_file():row['guidance']=read(tasks).get('guidance')
        runtimes=sorted((candidate.root/'modeling/codex').glob('request_*/runtime.json'))
        row['runtime']=read(runtimes[-1])if runtimes else None
        row['input_signature']=candidate.project.signature(candidate.scene)
        occupied=set()
        for kind,path,digest in prepared:
            name=path.name
            if name in occupied:name=str(len(occupied)+1)+'_'+name
            occupied.add(name);target=folder/'artifacts'/name;target.parent.mkdir(exist_ok=True)
            shutil.copyfile(path,target)
            if sha(target)!=digest:raise ValueError('Evidence changed during copy')
            row[kind].append({'path':target.relative_to(root).as_posix(),'sha256':digest,
                'source':os.path.relpath(path,candidate.project.root)})
        write(folder/'stage.json',row)
        (folder/'report.md').write_text('# '+stage+' — '+status+'\n\n'+str(summary)+'\n',encoding='utf8')
        index['stages'].append(row);write(root/'index.json',index)
        _index_html(root,index)
        return folder


def freeze_scene(candidate,stage,*,images=(),summary='',details=None):
    """Freeze the first Scene once and every explicit iteration separately."""
    identifier("stage_"+stage);root=candidate.root/'evidence';path=root/'index.json'
    if stage=='03_first_scene'and path.is_file():
        previous=next((r for r in reversed(read(path)['stages'])if r['id']==stage and r['status']=='COMPLETE'and r.get('run_identity')==run_identity(candidate)),None)
        if previous:
            folder=root/previous['path']
            for kind in ('images','files'):
                for item in previous[kind]:
                    if sha(root/item['path'])!=item['sha256']:raise ValueError('First Scene evidence changed')
            checkpoint=read(folder/'checkpoint.json')
            if sha(folder/'scene_state.json')!=checkpoint['scene_sha256']:raise ValueError('First Scene state changed')
            return folder
    scene=candidate.scene;signature=candidate.project.signature(scene)
    folder=record(candidate,stage,'RUNNING',images=images,summary=summary,
                  details={**(details or{}),'input_signature':signature})
    write(folder/'scene_state.json',scene)
    closure={}
    for relative,digest in signature['files'].items():
        source=candidate.project.root/relative
        if source.resolve().is_relative_to(candidate.root.resolve()):
            target=folder/'closure'/source.relative_to(candidate.root);target.parent.mkdir(parents=True,exist_ok=True)
            if source.is_symlink()or sha(source)!=digest:raise ValueError('Scene checkpoint closure changed')
            shutil.copyfile(source,target);closure[relative]={'path':target.relative_to(folder).as_posix(),'sha256':digest}
        else:closure[relative]={'source':relative,'sha256':digest,'immutable_external':True}
    write(folder/'checkpoint.json',{'scene':'scene_state.json','scene_sha256':sha(folder/'scene_state.json'),
        'input_signature':signature,'files':closure,'physical_verified':False})
    index=read(root/'index.json');row=next(r for r in index['stages']if r['path']==folder.relative_to(root).as_posix());row['status']='COMPLETE'
    write(folder/'stage.json',row);write(root/'index.json',index)
    (folder/'report.md').write_text('# '+stage+' — COMPLETE\n\n'+str(summary)+'\n',encoding='utf8')
    _index_html(root,index)
    return folder


def _index_html(root,index):
    sections=[]
    for row in index['stages']:
        text='<section><h2>'+html.escape(row['id']+' / '+row['status'])+'</h2><p>'+html.escape(row['summary'])+'</p>'
        for image in row['images']:
            link=html.escape(image['path'],quote=True);text+='<a href="'+link+'"><img loading="lazy" src="'+link+'"></a>'
        for file in row['files']:
            text+='<p><a href="'+html.escape(file['path'],quote=True)+'">'+html.escape(Path(file['path']).name)+'</a></p>'
        for name in ('scene_state.json','checkpoint.json'):
            if(root/row['path']/name).is_file():text+='<p><a href="'+html.escape(row['path']+'/'+name,quote=True)+'">'+name+'</a></p>'
        iteration=row.get('details',{}).get('iteration')
        if iteration:
            identifier(iteration)
            for path in sorted((root/'04_iterations'/iteration/'comparisons').glob('*/*.png')):
                text+='<a href="'+html.escape(path.relative_to(root).as_posix(),quote=True)+'">'+html.escape(path.name)+'</a> '
            for name in ('changes.json','checkpoint.json','report.md'):
                path=root/'04_iterations'/iteration/name
                if path.is_file():text+='<p><a href="'+html.escape(path.relative_to(root).as_posix(),quote=True)+'">'+iteration+' / '+name+'</a></p>'
        text+='<p><a href="'+html.escape(row['path'],quote=True)+'/stage.json">Stage record / SHA</a></p></section>';sections.append(text)
    page='<!doctype html><meta charset="utf-8"><title>Scene 제작 기록</title><style>body{font:16px sans-serif;background:#18212b;color:#eee;max-width:1500px;margin:24px auto}a{color:#6de0c1}img{max-width:48%;margin:4px}section{border-top:1px solid #607080;padding:12px}</style><h1>Scene 제작 기록</h1><p>실제 생성 파일과 관측 근거. 추정값은 Calibration/물리 인증이 아닙니다.</p>'+'\n'.join(sections)
    (root/'index.html').write_text(page,encoding='utf8')


def start_iteration(candidate,decision):
    """Freeze actual pre-edit images before any model or pose can be changed."""
    marker=candidate.root/'authoring-iteration.json'
    if marker.is_file():
        folder=candidate.root/read(marker)['path']
        if folder.is_symlink()or not folder.resolve().is_relative_to((candidate.root/'evidence/04_iterations').resolve()):raise ValueError('Iteration outside Candidate')
        return folder
    folder=numbered_path(candidate.root/'evidence/04_iterations','iteration');folder.mkdir(parents=True)
    write(folder/'before_scene.json',candidate.scene)
    write(folder/'changes.json',{'status':'RUNNING','requested':decision,'applied':False,'physical_verified':False})
    _iteration_images(candidate,folder,'before')
    record(candidate,'04_iterations','RUNNING',images=list((folder/'sim_before').glob('*.png')),
        files=[folder/'changes.json'],summary='Before-edit Scene and actual renders retained',details={'iteration':folder.name})
    write(marker,{'path':folder.relative_to(candidate.root).as_posix()})
    return folder


def _iteration_images(candidate,folder,when):
    source=candidate.root/'fitting/final/previews'
    paths=current_images(candidate,kinds=('real','sim','side_by_side','overlay','difference'))
    for view in dict.fromkeys(path.parent for path in paths):
        for kind in ('real','sim','side_by_side','overlay','difference'):
            path=view/(kind+'.png')
            if not path.is_file():continue
            target=folder/('real_views'if kind=='real'else'sim_'+when if kind=='sim'else'comparisons/'+when)
            target.mkdir(parents=True,exist_ok=True);destination=target/(view.name+('_'+kind if kind not in('real','sim')else'')+'.png')
            if kind=='real'and destination.exists():
                if sha(destination)!=sha(path):raise ValueError('Iteration original RGB changed')
            else:shutil.copyfile(path,destination)


def finish_iteration(candidate,*,status='COMPLETE'):
    marker=candidate.root/'authoring-iteration.json'
    if not marker.is_file():return None
    folder=candidate.root/read(marker)['path']
    if not folder.resolve().is_relative_to((candidate.root/'evidence/04_iterations').resolve()):raise ValueError('Iteration outside Candidate')
    changes=read(folder/'changes.json');changes['status']=status
    if status=='COMPLETE':
        _iteration_images(candidate,folder,'after');changes['applied']=True
        before=read(folder/'before_scene.json');after=candidate.scene
        changes['changes']={}
        for group in ('objects','cameras','lights'):
            if before.get(group)!=after.get(group):changes['changes'][group]={'before':before.get(group),'after':after.get(group)}
        frozen=freeze_scene(candidate,'04_iterations',images=list((folder/'sim_before').glob('*.png'))+list((folder/'sim_after').glob('*.png')),
            summary='Actual before/after comparison',details={'iteration':folder.name,'requested':changes['requested']})
        write(folder/'checkpoint.json',{'path':frozen.relative_to(candidate.root).as_posix(),'scene_sha256':sha(frozen/'scene_state.json')})
        marker.unlink()
    write(folder/'changes.json',changes)
    (folder/'report.md').write_text('# '+folder.name+' — '+status+'\n\nBefore/after are actual renders. Unrendered after-images remain absent.\n',encoding='utf8')
    if status!='COMPLETE':record(candidate,'04_iterations',status,files=[folder/'changes.json'],summary='Interrupted iteration; earlier Scene/images retained',details={'iteration':folder.name})
    _index_html(candidate.root/'evidence',read(candidate.root/'evidence/index.json'))
    return folder


def analysis_record(candidate,objects,execution,*,runtime=None,guidance=None):
    """Annotate only Codex-returned original-pixel boxes, never imagined masks."""
    from PIL import Image,ImageOps,ImageDraw
    annotations=execution/'annotations';annotations.mkdir(exist_ok=True)
    photos=[];inputs=[]
    for image in candidate.project.evidence['images']:
        if image.get('split')=='validation':continue
        source=candidate.project.root/image['path']
        if sha(source)!=image['sha256']:raise ValueError('Analysis evidence RGB changed')
        with Image.open(source)as raw:rgb=ImageOps.exif_transpose(raw).convert('RGB')
        draw=ImageDraw.Draw(rgb);draw.text((12,12),image.get('id',source.name)+' / '+image.get('role','unknown'),fill='red')
        for name,spec in objects.items():
            box=spec.get('images',{}).get(image.get('id'),{}).get('box_xyxy')
            if box:draw.rectangle(box,outline='red',width=max(2,rgb.width//500));draw.text((box[0]+3,box[1]+3),name,fill='red')
        path=annotations/(image.get('id','context_'+image['sha256'][:20])+'.png');rgb.save(path);photos.append(path)
        inputs.append({k:image.get(k)for k in ('id','path','sha256','resolution','role','scene_state_id')})
    if photos:
        sheet=Image.new('RGB',(1000,360*((len(photos)+2)//3)), '#eeeeee')
        for i,path in enumerate(photos):
            with Image.open(path)as image:thumb=ImageOps.contain(image,(328,350));sheet.paste(thumb,((i%3)*334,(i//3)*360))
        sheet.save(annotations/'overview.png')
    write(annotations/'objects.json',{'objects':objects,'inputs':inputs,'annotation_source':'Codex returned boxes in original upright pixels, NOT SAM masks','runtime':runtime,'guidance':guidance})
    return record(candidate,'01_scene_analysis','COMPLETE',images=([annotations/'overview.png']if photos else[])+photos,
        files=[annotations/'objects.json',execution/'answer.json',execution/'input_manifest.json'],summary='Actual input photographs with Codex Object/reference evidence',details={'runtime':runtime,'guidance':guidance})


def record_reused_assets(candidate,config):
    """Expose reused Object geometry without claiming a new Blender execution."""
    from .scene import local_path
    root=candidate.root/'evidence';index=read(root/'index.json')if(root/'index.json').is_file()else{'stages':[]}
    scene=candidate.scene;run=run_identity(candidate)
    for obj in scene['objects']:
        if obj.get('link')or obj['role']=='reference_robot':continue
        asset=obj.get('object_asset',{});version=asset.get('version');name=obj['id']
        prior=[r for r in index['stages']if r['id']=='02_object_modeling'and r.get('run_identity')==run and r.get('details',{}).get('object_id')==name]
        if any(r['details'].get('asset',{}).get('version')==version for r in prior):continue
        keys=set()
        for geometry in (obj['visual'],obj['collision']):
            for part in geometry.get('parts',[geometry]):
                if part.get('asset'):keys.add(part['asset'])
                if part.get('texture'):keys.add(part['texture'])
        for key in ('manifest_asset','entry_asset'):
            if asset.get(key):keys.add(asset[key])
        files=[local_path(candidate.project.root,scene['assets'][key]['path'])for key in sorted(keys)]
        for path,key in zip(files,sorted(keys)):
            if sha(path)!=scene['assets'][key]['sha256']:raise ValueError('Reused asset changed')
        record(candidate,'02_object_modeling','REUSED',files=files,
            summary='Existing Object geometry/version reused; no Blender creation or missing previews claimed',
            details={'object_id':name,'asset':asset,'geometry':{k:obj[k]for k in ('dimensions','visual','collision')},
                'references':config.get('objects',{}).get(name,{}).get('model_references',[]),
                'preview_status':'NOT_RECORDED unless an earlier actual modeling stage provides it','newly_authored':False})


def current_images(candidate,*,kinds=('sim',),metrics=None):
    """Enumerate only this signed comparison's actual outputs; retain old files separately."""
    metrics=metrics if metrics is not None else read(candidate.root/'metrics.json')
    if metrics.get('input_signature')!=candidate.project.signature(candidate.scene):
        raise ValueError('Current evidence render signature is stale')
    result=[]
    for image in metrics.get('images',[]):
        identifier(image['image_id'])
        for kind in kinds:
            if kind not in('real','sim','side_by_side','overlay','difference'):raise ValueError('Unknown comparison image kind')
            path=candidate.root/'fitting/final/previews'/image['image_id']/(kind+'.png')
            if not path.is_file():raise ValueError('Missing current comparison image')
            result.append(path)
    return result
