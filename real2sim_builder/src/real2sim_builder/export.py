"""New immutable Scene revisions, native reference closure and preserved identities.

USD uses installed Sdf/UsdUtils; XML uses declared include/mesh/texture filenames.
No lookup in the original workspace, engine startup, device or Dataset services.
"""
import copy
import json
import os
import re
from pathlib import Path
import shutil
import uuid
import xml.etree.ElementTree as ET
from .project import read,write,sha,local_path,validate


class ExportError(ValueError):
    def __init__(self,code,field,reason,*,effect='not_started'):
        self.code=code;self.effect=effect;self.issues=({'field':field,'reason':reason},)
        super().__init__(field+': '+reason)


def _source_path(parent,reference,resolutions):
    if reference in resolutions:return Path(resolutions[reference]).resolve()
    if ':' in reference and not Path(reference).is_absolute():raise ExportError('ASSET_UNRESOLVED',reference,'explicit local resolution required; no network or search fallback')
    return (parent/reference).resolve()


def _xml_references(tree):
    compiler=tree.find('compiler');directories={}
    if compiler is not None:
        assetdir=compiler.get('assetdir','')
        directories={'mesh':compiler.get('meshdir',assetdir),'texture':compiler.get('texturedir',assetdir)}
    for node in tree.iter():
        key='filename' if node.tag=='mesh' and 'filename' in node.attrib else 'file'
        if key in node.attrib:yield node,key,str(Path(directories.get(node.tag,''))/node.get(key))


def _expanded_xml(source,resolutions):
    """MJCF include is relative to the main model, including nested includes.

    https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html#include
    Flatten only XML include syntax, preserving element order and numeric strings.
    """
    tree=ET.parse(source);root=tree.getroot();included=[];seen={source}
    if root.tag!='mujoco':return tree,included
    def expand(parent):
        for node in list(parent):
            if node.tag!='include':expand(node);continue
            path=_source_path(source.parent,node.attrib['file'],resolutions)
            if path in seen:raise ExportError('ASSET_INVALID',str(path),'duplicate/cyclic MJCF include')
            if not path.is_file():raise ExportError('ASSET_MISSING',str(path),'MJCF include missing')
            seen.add(path);included.append(path);child=ET.parse(path).getroot();expand(child)
            offset=list(parent).index(node);parent.remove(node)
            for i,item in enumerate(list(child)):parent.insert(offset+i,item)
    expand(root);return tree,included


def _declared_children(source,resolutions):
    suffix=source.suffix.lower()
    if suffix in ('.usd','.usda','.usdc'):
        from pxr import UsdUtils
        refs=UsdUtils.ExtractExternalReferences(str(source))
        return [_source_path(source.parent,r,resolutions) for group in refs for r in group]
    if suffix in ('.xml','.mjcf','.urdf'):
        tree,_=_expanded_xml(source,resolutions)
        return [_source_path(source.parent,ref,resolutions) for _,_,ref in _xml_references(tree.getroot())]
    children=[]
    if suffix=='.mdl':
        # Only the installed OmniPBR module subset is supported, not arbitrary MDL.
        for module in re.findall(r'^\s*import\s+([^;]+);',source.read_text(),re.MULTILINE):
            if module.startswith('::'):
                library=module.rsplit('::',1)[0]
                if library not in {'::df','::state','::math','::base','::tex','::anno','::debug','::nvidia::core_definitions'}:
                    raise ExportError('ASSET_UNSUPPORTED',str(source),'unbound absolute MDL module: '+module)
            elif re.fullmatch(r'[A-Za-z_]\w*::\*',module):
                children.append(_source_path(source.parent,module.split('::')[0]+'.mdl',resolutions))
            else:raise ExportError('ASSET_UNSUPPORTED',str(source),'explicit MDL module support required: '+module)
    if suffix in ('.obj','.mtl'):
        for row in source.read_text().splitlines():
            words=row.split()
            if words and words[0]=='mtllib':children.extend(_source_path(source.parent,r,resolutions) for r in words[1:])
            elif words and (words[0].startswith('map_') or words[0] in ('bump','disp')):
                if len(words)!=2:raise ExportError('ASSET_UNSUPPORTED',str(source),'explicit MTL texture options needed')
                children.append(_source_path(source.parent,words[1],resolutions))
    return children


def copy_native_asset(source,destination,*,resolutions=None,copied=None,report=None,_layout=None):
    """Copy explicit local native dependencies once; only derived paths are rewritten."""
    source=Path(source).resolve();destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    copied={} if copied is None else copied;resolutions=resolutions or {};report=[] if report is None else report
    if source in copied:return copied[source]
    if not source.is_file():raise ExportError('ASSET_MISSING',str(source),'required native file missing')
    if _layout is None:
        seen=set();queue=[source]
        while queue:
            item=queue.pop()
            if item in seen:continue
            if not item.is_file():raise ExportError('ASSET_MISSING',str(item),'required native dependency missing')
            seen.add(item);queue.extend(_declared_children(item,resolutions))
        common=Path(os.path.commonpath([str(p.parent) for p in seen]))
        base=destination/'assets'/sha(source)
        # Shared model meshes must retain the same relative layout for every URDF.
        # Reuse an already copied graph's prefix instead of rewriting calibrated
        # model bytes merely because its shared mesh was copied first.
        for item in sorted(seen):
            if item not in copied:continue
            prefix=copied[item]
            for _ in item.relative_to(common).parts:prefix=prefix.parent
            if prefix.is_relative_to(destination) and all(copied[p]==prefix/p.relative_to(common) for p in seen if p in copied):
                base=prefix;break
        _layout=(base,common)
    target=_layout[0]/source.relative_to(_layout[1]);target.parent.mkdir(parents=True,exist_ok=True);copied[source]=target
    suffix=source.suffix.lower();shutil.copyfile(source,target)
    if suffix in ('.usd','.usda','.usdc'):
        # https://openusd.org/release/api/dependencies_8h.html
        from pxr import Sdf,UsdUtils
        layer=Sdf.Layer.FindOrOpen(str(source))
        if layer is None:raise ExportError('ASSET_INVALID',str(source),'USD layer cannot be opened')
        derived=Sdf.Layer.CreateAnonymous();derived.TransferContent(layer);changes=[]
        def rewrite(reference):
            if not reference:return reference
            child=_source_path(source.parent,reference,resolutions)
            packaged=copy_native_asset(child,destination,resolutions=resolutions,copied=copied,report=report,_layout=_layout)
            relative=os.path.relpath(packaged,target.parent)
            if relative!=reference:changes.append(reference)
            return relative
        UsdUtils.ModifyAssetPaths(derived,rewrite)
        # Export with the original file extension; never Save the input layer.
        if changes and not derived.Export(str(target)):raise ExportError('ASSET_INVALID',str(source),'USD derived layer export failed')
    elif suffix in ('.xml','.mjcf','.urdf'):
        tree,included=_expanded_xml(source,resolutions);root=tree.getroot();changed=bool(included)
        for path in included:report.append({'source':str(path),'source_sha256':sha(path),'derived_into':target.relative_to(destination).as_posix(),'reason':'MJCF include expanded relative to main file'})
        for node,key,reference in list(_xml_references(root)):
            packaged=copy_native_asset(_source_path(source.parent,reference,resolutions),destination,resolutions=resolutions,copied=copied,report=report,_layout=_layout)
            relative=os.path.relpath(packaged,target.parent)
            changed=changed or node.get(key)!=relative
            node.set(key,relative)
        compiler=root.find('compiler')
        if compiler is not None:
            for key in ('meshdir','texturedir','assetdir'):
                if key in compiler.attrib:changed=True;compiler.attrib.pop(key)
        if changed:tree.write(target,encoding='unicode',xml_declaration=True)
    elif suffix=='.mdl':
        for child in _declared_children(source,resolutions):
            copy_native_asset(child,destination,resolutions=resolutions,copied=copied,report=report,_layout=_layout)
    elif suffix=='.obj':
        # Preserve geometry exactly; only external material library references change.
        rows=[]
        for row in source.read_text().splitlines(keepends=True):
            words=row.split()
            if words and words[0]=='mtllib':
                paths=[copy_native_asset(_source_path(source.parent,r,resolutions),destination,resolutions=resolutions,copied=copied,report=report,_layout=_layout) for r in words[1:]]
                row='mtllib '+' '.join(os.path.relpath(p,target.parent) for p in paths)+'\n'
            rows.append(row)
        if ''.join(rows)!=source.read_text():target.write_text(''.join(rows))
    elif suffix=='.mtl':
        rows=[]
        for row in source.read_text().splitlines(keepends=True):
            words=row.split()
            if words and (words[0].startswith('map_') or words[0] in ('bump','disp')):
                if len(words)!=2:raise ExportError('ASSET_UNSUPPORTED',str(source),'MTL texture options require an explicit importer')
                p=copy_native_asset(_source_path(source.parent,words[1],resolutions),destination,resolutions=resolutions,copied=copied,report=report,_layout=_layout)
                row=words[0]+' '+os.path.relpath(p,target.parent)+'\n'
            rows.append(row)
        target.write_text(''.join(rows))
    report.append({'source':str(source),'source_sha256':sha(source),'path':target.relative_to(destination).as_posix(),'sha256':sha(target),'derived_paths_only':sha(source)!=sha(target)})
    return target


def verify_native_closure(root,entry):
    """Read-only native closure; every resolved dependency must stay inside root."""
    root=Path(root).resolve();entry=Path(entry);entry=entry if entry.is_absolute() else root/entry
    seen=set();queue=[entry]
    while queue:
        path=queue.pop().resolve()
        if path in seen:continue
        if not path.is_relative_to(root) or not path.is_file():raise ExportError('ASSET_MISSING',str(path),'missing or external native dependency')
        seen.add(path);suffix=path.suffix.lower()
        if suffix in ('.usd','.usda','.usdc'):
            from pxr import Sdf,UsdUtils
            # Official recursive resolver catches references, payloads and asset values.
            for group in UsdUtils.ExtractExternalReferences(str(path)):
                for reference in group:
                    if Path(reference).is_absolute() or ':' in reference:raise ExportError('ASSET_UNRESOLVABLE',reference,'USD asset path must be package-relative')
            layers,assets,missing=UsdUtils.ComputeAllDependencies(Sdf.AssetPath(str(path)))
            if missing:raise ExportError('ASSET_UNRESOLVABLE',str(path),str(missing))
            queue.extend(Path(p.realPath) for p in layers);queue.extend(Path(p) for p in assets)
        elif suffix in ('.xml','.mjcf','.urdf'):
            for _,_,ref in _xml_references(ET.parse(path).getroot()):
                if Path(ref).is_absolute() or ':' in ref:raise ExportError('ASSET_UNRESOLVABLE',ref,'package-relative native dependency required')
                queue.append(path.parent/ref)
        elif suffix in ('.obj','.mtl'):
            for row in path.read_text().splitlines():
                words=row.split()
                if words and words[0]=='mtllib':queue.extend(path.parent/p for p in words[1:])
                elif words and (words[0].startswith('map_') or words[0] in ('bump','disp')):queue.append(path.parent/words[-1])
        elif suffix=='.mdl':queue.extend(_declared_children(path,{}))
    return seen


from .exporters import mjcf,usd


def _frame_name(frames,prefix,name):
    result=prefix+name
    if result in frames:raise ExportError('SCENE_INVALID',result,'generated Frame ID collides; rename explicitly')
    return result


def _scene_spec(scene,scene_id,revision,mapping,model_path,required):
    import numpy as np
    from .calibration.geometry import parts
    frames={};world=np.asarray(scene['frames']['world']['transform']['value'])
    aliases={name:name for name in scene['frames']}
    if not np.array_equal(world,np.eye(4)):
        if 'builder_world' in scene['frames']:raise ExportError('SCENE_INVALID','world','builder_world alias collision')
        aliases['world']='builder_world';frames['world']={'parent':None,'state':'reference','T_parent_from_frame':np.eye(4).tolist()}
    for name,frame in scene['frames'].items():
        frames[aliases[name]]={'parent':aliases.get(frame['parent']),'state':'reference','T_parent_from_frame':frame['transform']['value']}
        if name=='world' and aliases[name]!='world':frames[aliases[name]]['parent']='world'
    def geom(obj,field):
        result=[]
        for part in parts(obj,field):
            node={'kind':'mesh' if part['type']=='mesh' else 'primitive','local_transform':part['pose'].tolist(),'scale':part.get('scale',[1.,1.,1.])}
            if part['type']=='mesh':node['asset_path']=scene['assets'][part['asset']]['path']
            else:node.update(primitive=part['type'],dimensions_m=part['dimensions'].tolist())
            result.append(node)
        return result[0] if len(result)==1 else {'kind':'compound','parts':result}
    objects={};supports={}
    for obj in scene['objects']:
        fid=_frame_name(frames,'object_',obj['id']);frames[fid]={'parent':aliases[obj['frame']],'state':'reference','T_parent_from_frame':obj['pose']['value']}
        task_geometry={'dimensions_m':obj['dimensions']['value']}
        collision=obj['collision']
        if collision['type']=='container':
            task_geometry['wall_m']=collision['wall']['value']
            if 'bottom_diameter_m' in collision:task_geometry['bottom_diameter_m']=collision['bottom_diameter_m']
        objects[obj['id']]={'name':obj['id'],'role':'task_object' if obj['role']=='manipulable_object' else obj['role'],'frame_id':fid,
            'visual':geom(obj,'visual'),'collision':geom(obj,'collision'),'physics':copy.deepcopy(obj['physics']),'task_geometry':task_geometry,
            'bindings':{'isaac':{'prim_path':mapping['isaac'][obj['id']]},'mujoco':{'body_name':obj['id']}},'builder_role':obj['role']}
        if obj['role']=='support_surface':supports[obj['id']]={'object_id':obj['id'],'placement_frame_id':aliases[obj['frame']]}
    cameras={}
    for camera in scene['cameras']:
        fid=_frame_name(frames,'camera_',camera['id']);frames[fid]={'parent':aliases[camera['frame']],'state':'reference','T_parent_from_frame':camera['pose']['value']}
        cameras[camera['id']]={'frame_id':fid,'K':camera['K']['value'],'distortion':camera['distortion']['value'],'resolution':camera['resolution'],
            'convention':'x_right_y_down_z_forward','validation':copy.deepcopy(camera.get('calibration_quality',{'state':'UNVALIDATED'}))}
    robot={}
    if scene.get('robot_model'):
        robot={'asset_path':model_path,'joint_order':scene['robot_model']['joint_names'],'required_files':required,
               'source_model_sha256':scene['robot_model']['model_sha256'],'reference_snapshot_only':True}
    return {'schema_version':1,'scene_id':scene_id,'revision':revision,'units':{'length':'m','angle':'rad','time':'s','mass':'kg'},'frames':frames,
            'objects':objects,'robot':robot,'cameras':cameras,'supports':supports,'engines':{},'calibration':'calibration.json','manifest':'manifest.json',
            'validation':{'execution':'NOT_TESTED','geometry':'UNVALIDATED','physics':'UNVALIDATED'}}


def _collision_binding(root,copied):
    """Bind known SO101 auxiliary files and exact source bytes; no repo fallback."""
    from .exporters.mjcf import load_robot_collision
    by_name={p.name:p for p in copied}
    expected=('finger_convex_parts.json','usd_contact_pads.json')
    if not all(name in by_name for name in expected):raise ExportError('ASSET_MISSING','robot.collision','explicit Finger Collision and contact pad inputs required for SO101')
    hashes={sha(target):target for target in copied.values()}
    binding={}
    for name in expected:
        data=read(by_name[name]);references={}
        if name=='finger_convex_parts.json':identities={row['mesh']:row['source_sha256'] for row in data['meshes']}
        else:identities=data['source_sha256']
        for key,expected_hash in identities.items():
            if expected_hash not in hashes:raise ExportError('ASSET_MISSING',name+':'+key,'exact collision source hash missing; provide original source Asset explicitly')
            references[key]={'asset_path':hashes[expected_hash].relative_to(root).as_posix(),'sha256':expected_hash}
        binding['finger_convex_parts' if name==expected[0] else 'contact_pads']={'asset_path':copied[by_name[name]].relative_to(root).as_posix(),'sources':references}
    load_robot_collision(root,binding)
    return binding


def verify_package(path):
    from scene_contract.package import load_scene
    root=Path(path).resolve();package=load_scene(root/'scene.json');registered={f.path for f in package.files}
    for engine in package.scene['engines'].values():
        for dependency in verify_native_closure(root,engine['asset_path']):
            if dependency.relative_to(root).as_posix() not in registered:raise ExportError('ASSET_UNREGISTERED',str(dependency),'native closure file missing from manifest')
    if package.scene['robot'].get('asset_path'):
        for dependency in verify_native_closure(root,package.scene['robot']['asset_path']):
            if dependency.relative_to(root).as_posix() not in registered:raise ExportError('ASSET_UNREGISTERED',str(dependency),'robot dependency missing from manifest')
    for binding in package.scene['robot'].get('bindings',{}).values():
        for dependency in verify_native_closure(root,binding['asset_path']):
            if dependency.relative_to(root).as_posix() not in registered:raise ExportError('ASSET_UNREGISTERED',str(dependency),'execution robot dependency missing from manifest')
    if package.scene['robot'].get('collision'):
        from .exporters.mjcf import load_robot_collision
        load_robot_collision(root,package.scene['robot']['collision'])
    return package


def export_revision(project,*,destination,candidate=None,calibration=None,required_files=(),engine_sources=None,
                    scene_id=None,revision=None,allow_unvalidated=False,isaac_robot_asset=None,asset_resolutions=None):
    """Publish a new revision only after file/closure checks; never replace originals.

    Inputs are project-owned edit data or explicit read-only source files. Calibration
    is S02 declaration data: no fitter, encoder, residual or hardware command runs.
    """
    from .project import Candidate
    from scene_contract.package import load_scene
    destination=Path(destination).resolve();scene_id=scene_id or project.info['id'];revision=revision or destination.name
    if engine_sources:raise ExportError('ENGINE_SOURCE_UNSUPPORTED','engine_sources','replacement native assets require separately verified bindings; use the authored Scene exporter')
    if destination.exists():raise ExportError('OUTPUT_EXISTS',str(destination),'new Revision destination required')
    if (project.read_only and destination.is_relative_to(project.root)) or project.root.is_relative_to(destination) or destination==project.root:raise ExportError('OUTPUT_CONFLICT',str(destination),'must not contain/replace input project')
    if candidate is not None:
        selected=Candidate(project,candidate);scene=selected.scene;report_path=selected.root/'metrics.json'
        if not allow_unvalidated:raise ExportError('VALIDATION_REQUIRED','candidate','unpromoted candidate requires explicit review export')
    else:scene=project.scene;report_path=project.root/'working/validation/report.json'
    validate(scene,project.root,complete=True);signature=project.signature(scene)
    if not report_path.is_file():raise ExportError('VALIDATION_REQUIRED','report','fresh review/validation report required')
    report=read(report_path)
    if report.get('input_signature')!=signature:raise ExportError('INPUT_CHANGED','report','stale validation/evidence signature')
    if not report.get('passed') and not allow_unvalidated:raise ExportError('VALIDATION_REQUIRED','report','explicit unvalidated review export required')
    destination.parent.mkdir(parents=True,exist_ok=True);staging=destination.parent/('.building-'+uuid.uuid4().hex);staging.mkdir()
    lock_path=destination.parent/('.'+destination.name+'.export.lock');lock=None
    try:
        lock=lock_path.open('x');copied={};derivations=[];working=copy.deepcopy(scene)
        for asset in working['assets'].values():
            source=local_path(project.root,asset['path']);target=copy_native_asset(source,staging,copied=copied,report=derivations)
            asset['path']=target.relative_to(staging).as_posix();asset['sha256']=sha(target)
        model_path=None
        if working.get('robot_model'):
            source=local_path(project.root,working['robot_model']['path'])
            if sha(source)!=working['robot_model']['model_sha256']:raise ExportError('INPUT_CHANGED','robot_model','source model bytes changed')
            target=copy_native_asset(source,staging,copied=copied,report=derivations);model_path=target.relative_to(staging).as_posix();working['robot_model']['path']=model_path
        explicit=tuple(required_files) or tuple(project.info.get('export_dependencies',()))
        required=[]
        for file in explicit:
            entry={'source':str(file),'usage':'runtime'} if isinstance(file,(str,Path)) else file
            if set(entry)!={'source','usage'} or entry['usage'] not in ('runtime','identity_evidence'):raise ExportError('ASSET_INVALID','required_files','explicit source/usage required')
            source=Path(entry['source']);source=source.resolve() if source.is_absolute() else local_path(project.root,str(source))
            if entry['usage']=='identity_evidence':
                if not source.is_file():raise ExportError('ASSET_MISSING',str(source),'historical model evidence missing')
                target=staging/'evidence'/(sha(source)+source.suffix+'.source');target.parent.mkdir(exist_ok=True);shutil.copyfile(source,target)
                derivations.append({'source':str(source),'source_sha256':sha(source),'path':target.relative_to(staging).as_posix(),'sha256':sha(target),'usage':'identity_evidence; not an executable model'})
                copied[source]=target
            else:target=copy_native_asset(source,staging,copied=copied,report=derivations)
            required.append(target.relative_to(staging).as_posix())
        engines={};mapping={}
        for engine,module,suffix in [('mujoco',mjcf,'.xml'),('isaac',usd,'.usda')]:
            target=staging/('scene'+suffix);mapping[engine]=module.export(working,staging,target)
            engines[engine]={'asset_path':target.relative_to(staging).as_posix(),'loader_validation':'NOT_TESTED','required_files':required}
        spec=_scene_spec(working,scene_id,revision,mapping,model_path,required);spec['engines']=engines
        if isaac_robot_asset is not None:
            source=Path(isaac_robot_asset)
            source=source.resolve() if source.is_absolute() else local_path(project.root,str(source))
            if source.suffix.lower() not in ('.usd','.usda','.usdc'):raise ExportError('ASSET_INVALID','isaac_robot_asset','native execution USD required')
            target=copy_native_asset(source,staging,copied=copied,report=derivations,resolutions=asset_resolutions)
            from pxr import Usd
            stage=Usd.Stage.Open(str(target))
            if stage is None or not stage.GetDefaultPrim():raise ExportError('ASSET_INVALID','isaac_robot_asset','execution USD default prim required')
            spec['robot'].setdefault('bindings',{})['isaac']={'asset_path':target.relative_to(staging).as_posix()}
        if working.get('robot_model') and working['robot_model'].get('joint_names')==['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper']:
            spec['robot']['collision']=_collision_binding(staging,copied)
        calibration=copy.deepcopy(calibration) if calibration is not None else {'schema_version':1,'records':{},'evidence':{}}
        # Paths in explicit calibration records refer to this package. Missing model
        # bytes/parameters or baked-runtime duplicate declarations are rejected by S02.
        for name,record in calibration['records'].items():
            if 'parameters_file' in record:
                source=Path(record['parameters_file']);source=source if source.is_absolute() else local_path(project.root,str(source))
                target=copy_native_asset(source,staging,copied=copied,report=derivations);record['parameters_file']=target.relative_to(staging).as_posix()
            app=record['application']
            if app['mode']=='baked':
                relocated=[]
                for path in app['asset_paths']:
                    source=Path(path);source=source.resolve() if source.is_absolute() else (project.root/path).resolve()
                    if source not in copied:copy_native_asset(source,staging,copied=copied,report=derivations)
                    relocated.append(copied[source].relative_to(staging).as_posix())
                app['asset_paths']=relocated
        write(staging/'calibration.json',calibration)
        write(staging/'scene.json',spec)
        write(staging/'authored_scene.json',working)
        write(staging/'provenance.json',{'project':copy.deepcopy(project.info),'candidate':candidate,'input_signature':signature,'validation':report,
              'original_scene':scene,'evidence':project.evidence,'native_assets':derivations,'calibration_execution':'declarations_only; no parameter application'})
        def manifest():
            write(staging/'manifest.json',{'schema_version':1,'files':[{'path':p.relative_to(staging).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(staging.rglob('*')) if p.is_file() and p!=staging/'manifest.json']})
        manifest();load_scene(staging/'scene.json');verify_package(staging)
        # Parser loading is separate from PhysX/sensors/engine workflow validation.
        import mujoco
        m=mujoco.MjModel.from_xml_path(str(staging/spec['engines']['mujoco']['asset_path']))
        from pxr import Usd
        stage=Usd.Stage.Open(str(staging/spec['engines']['isaac']['asset_path']))
        if stage is None or not stage.GetDefaultPrim():raise ExportError('ASSET_INVALID','isaac','USD stage/default prim missing')
        spec['engines']['mujoco']['loader_validation']={'status':'PARSED','ngeom':m.ngeom}
        spec['engines']['isaac']['loader_validation']={'status':'PARSED','runtime':'NOT_TESTED'}
        write(staging/'scene.json',spec);manifest();package=verify_package(staging)
        if project.signature(scene)!=signature:raise ExportError('INPUT_CHANGED','project','input changed while exporting')
        for p in staging.rglob('*'):
            if p.is_file():
                with p.open('rb') as stream:os.fsync(stream.fileno())
        if destination.exists():raise ExportError('OUTPUT_EXISTS',str(destination),'destination appeared during export')
        os.rename(staging,destination)
        try:
            directory=os.open(destination.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        except OSError as error:
            raise ExportError('EXPORT_STATE_UNKNOWN',str(destination),'published package exists; directory durability was not confirmed; inspect this destination before retrying',effect='unknown') from error
        if not project.read_only:
            from .registration import register_export
            register_export(project,destination)
        return package.identity
    finally:
        if lock is not None:lock.close();lock_path.unlink(missing_ok=True)
        if staging.exists():shutil.rmtree(staging)
