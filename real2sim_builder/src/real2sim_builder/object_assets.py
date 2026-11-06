"""Immutable, portable object USDA assets; placement belongs to Candidate.edit.

USD remains the visual authority. Triangulated OBJ/PNG derivatives let the
existing canonical geometry and MuJoCo exporter consume the same authored asset.
No model generation, collision decomposition or physical approval is inferred.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import uuid
from yaml import YAMLError
from contextlib import contextmanager

import numpy as np

from .candidate import exclusive
from .files import read, write, sha
from .scene import identifier, local_path, transform, value


def asset_manifests(project):
    """Metadata discovery shared with Qt; no USD/model import or file copying."""
    shared=project.workspace/'object_assets'
    if shared.is_symlink():raise ValueError('Workspace Library symlink is forbidden')
    result=[]
    for base in(shared,project.root/'input/object_assets'):
        for path in sorted(base.glob('*/*/manifest.json')):
            if len(path.parent.name)!=64:continue
            relative=os.path.relpath(path,project.root)
            result.append(path)
    return result


@contextmanager
def library_write(project):
    """Project lock plus one Workspace registration owner, across processes."""
    import fcntl
    with exclusive(project):
        base=project.workspace/'object_assets'
        if base.is_symlink():raise ValueError('Workspace Library symlink is forbidden')
        base.mkdir(exist_ok=True)
        lock=base/'.register.lock'
        if lock.is_symlink():raise ValueError('Workspace Library lock symlink is forbidden')
        with os.fdopen(os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600),'a')as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('Workspace Object Library is busy; retry after registration')from None
            try:yield base
            finally:fcntl.flock(stream,fcntl.LOCK_UN)


def inspect_usda(path):
    from pxr import Usd, UsdGeom, UsdPhysics
    from .export import verify_native_closure
    path=Path(path).resolve()
    if path.suffix.lower()!='.usda':raise ValueError('Object asset entry must be USDA')
    closure=verify_native_closure(path.parent,path)
    stage=Usd.Stage.Open(str(path))
    if not stage or not stage.GetDefaultPrim():raise ValueError('Object USDA requires a default Prim')
    if not stage.HasAuthoredMetadata('metersPerUnit') or UsdGeom.GetStageMetersPerUnit(stage)!=1:
        raise ValueError('Object USDA must declare metersPerUnit = 1')
    if UsdGeom.GetStageUpAxis(stage)!='Z':raise ValueError('Object USDA must declare Z up')
    root=stage.GetDefaultPrim()
    if any(p.HasAPI(UsdPhysics.RigidBodyAPI)or p.HasAPI(UsdPhysics.ArticulationRootAPI)for p in Usd.PrimRange(root)):
        raise ValueError('Object assets contain visual/collision only; assign rigid bodies at Scene instances, preserve Robot articulation separately')
    if not np.allclose(np.asarray(UsdGeom.Xformable(root).ComputeLocalToWorldTransform(Usd.TimeCode.Default())),np.eye(4)):
        raise ValueError('Object root must have identity transform; place instances through Candidate.edit')
    meshes=[UsdGeom.Mesh(p)for p in Usd.PrimRange(root)if p.IsA(UsdGeom.Mesh)]
    if not meshes:raise ValueError('Object USDA contains no Mesh')
    if any(a.ValueMightBeTimeVarying()for p in Usd.PrimRange(root)for a in p.GetAttributes()):
        raise ValueError('Static object assets cannot contain animated transforms')
    return stage,closure


def _convert(stage,folder):
    """Bake mesh transforms/UV seams, separate material subsets and collision.

    Only PreviewSurface/image textures are accepted. Unsupported materials are
    explicit errors, never silently replaced with a default material.
    """
    from pxr import Usd, UsdGeom, UsdShade, UsdPhysics
    root=stage.GetDefaultPrim();visual=[];collision=[];all_points=[];textures={}
    def material_for(prim):
        mat=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
        if not mat:return {'color':[.5]*3,'roughness':.6,'metallic':0.}
        shader=mat.ComputeSurfaceSource()[0]
        if not shader or shader.GetIdAttr().Get()!='UsdPreviewSurface':raise ValueError('Bake object materials to UsdPreviewSurface')
        result={}
        for key,default in [('diffuseColor',[.5]*3),('roughness',.6),('metallic',0.)]:
            inp=shader.GetInput(key);data=inp.Get()if inp else None
            result['color'if key=='diffuseColor'else key]=list(data)if key=='diffuseColor'and data is not None else data if data is not None else default
            if inp and inp.HasConnectedSource():
                source=inp.GetConnectedSource()[0];tex=UsdShade.Shader(source.GetPrim())
                if key!='diffuseColor'or tex.GetIdAttr().Get()!='UsdUVTexture':raise ValueError('Bake procedural/connected material channels before registration')
                asset=tex.GetInput('file').Get();path=Path(asset.resolvedPath)
                if not path.is_file():raise ValueError('Object material texture missing')
                from PIL import Image
                dest=folder/('texture_'+sha(path)[:16]+'.png')
                if not dest.exists():
                    with Image.open(path)as image:image.convert('RGB').save(dest)
                result['texture']=dest.name;textures[dest.name]=dest
                result['color']=[1.,1.,1.]
        return result
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Mesh):continue
        mesh=UsdGeom.Mesh(prim);points=np.asarray(mesh.GetPointsAttr().Get(),float)
        counts=np.asarray(mesh.GetFaceVertexCountsAttr().Get(),int);indices=np.asarray(mesh.GetFaceVertexIndicesAttr().Get(),int)
        if points.ndim!=2 or points.shape[1]!=3 or not np.isfinite(points).all()or counts.sum()!=len(indices)or np.any(counts<3):raise ValueError('Invalid USDA Mesh topology')
        if np.any(indices<0)or np.any(indices>=len(points)):raise ValueError('Mesh vertex index outside points')
        matrix=np.asarray(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
        points=points@matrix[:3,:3].T+matrix[:3,3]
        is_collision=prim.HasAPI(UsdPhysics.CollisionAPI)and UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get()is not False
        if not is_collision and UsdGeom.Imageable(prim).ComputeVisibility()=='invisible':continue
        if not is_collision:all_points.append(points)
        uv=UsdGeom.PrimvarsAPI(mesh).GetPrimvar('st');coords=np.asarray(uv.ComputeFlattened())if uv and uv.HasValue()else None
        interpolation=uv.GetInterpolation()if coords is not None else None
        groups={};offset=0
        subsets=UsdGeom.Subset.GetGeomSubsets(mesh,UsdGeom.Tokens.face,'materialBind')
        subset_by_face={int(face):sub.GetPrim()for sub in subsets for face in sub.GetIndicesAttr().Get()}
        for face,count in enumerate(counts):
            material=subset_by_face.get(face,prim);key=str(material.GetPath());group=groups.setdefault(key,{'prim':material,'rows':[]})
            for index in range(1,count-1):
                corners=[offset,offset+index,offset+index+1]
                if mesh.GetOrientationAttr().Get()=='leftHanded':corners.reverse()
                for corner in corners:
                    vertex=indices[corner];texcoord=[0.,0.]
                    if coords is not None:
                        address=corner if interpolation=='faceVarying'else vertex if interpolation in('vertex','varying')else face if interpolation=='uniform'else 0
                        texcoord=coords[address]
                    group['rows'].append((points[vertex],texcoord))
            offset+=count
        for group in groups.values():
            rows=group['rows'];dest=folder/('collision'if is_collision else'visual');dest=dest.with_name(dest.name+'_'+str(len(collision)if is_collision else len(visual))+'.obj')
            lines=['v '+' '.join(map(str,p))for p,_ in rows]+['vt '+' '.join(map(str,t))for _,t in rows]
            lines+=['f '+' '.join(f'{j+1}/{j+1}'for j in range(i,i+3))for i in range(0,len(rows),3)]
            dest.write_text('\n'.join(lines)+'\n')
            part={'type':'mesh','file':dest.name,'pose':np.eye(4).tolist(),'dimensions':np.maximum(np.ptp(np.array([r[0]for r in rows]),axis=0),1e-9).tolist()}
            if not is_collision:
                part.update(material_for(group['prim']))
                if part.get('texture')and coords is None:raise ValueError('Textured Mesh requires authored UV coordinates')
            else:
                # Reuse the canonical collision validator, including concavity.
                from .scene import empty,validate
                test=empty('collision');test['assets']={'mesh':{'path':dest.name,'sha256':sha(dest)}}
                test['objects']=[{'id':'piece','role':'fixture','frame':'world','pose':value(np.eye(4).tolist(),'estimated'),
                    'dimensions':value(part['dimensions'],'estimated'),'color':value([.5]*3,'estimated'),'physics':{},
                    'visual':{'type':'unknown'},'collision':{'type':'mesh','asset':'mesh'}}]
                validate(test,folder)
            (collision if is_collision else visual).append(part)
    if not visual:raise ValueError('Object asset has no visible Mesh')
    return visual,collision,np.ptp(np.concatenate(all_points),axis=0).tolist()


def dimensions_match(declared,actual):
    """Check only known axes; a null dimension does not invent a measurement."""
    return all(wanted is None or np.isclose(wanted,got,rtol=.02,atol=1e-5)for wanted,got in zip(declared,actual))


def register_object_asset(project,path,*,asset_id,dimensions=None,origin='authored object origin',blend=None,generation_id=None):
    """Own a versioned USD closure and portable derivatives; never edit sources."""
    identifier(asset_id);stage,closure=inspect_usda(path);source=Path(path).resolve()
    if dimensions is not None:
        dims=dimensions['value']
        if not isinstance(dims,list)or len(dims)!=3 or any(d is not None and(type(d)not in(int,float)or not np.isfinite(d)or d<=0)for d in dims):raise ValueError('Positive object dimensions required')
        if dimensions.get('provenance')not in('measured','estimated','calibrated')or not dimensions.get('evidence'):raise ValueError('Object dimension provenance and evidence required')
    identity={p.relative_to(source.parent).as_posix():sha(p)for p in sorted(closure)}
    version_input={'files':identity,'dimensions':dimensions,'origin':origin,'blend':sha(blend)if blend else None,'converter_sha256':sha(__file__)}
    if generation_id:version_input['generation_request_id']=identifier(generation_id)
    version=__import__('hashlib').sha256(json.dumps(version_input,sort_keys=True).encode()).hexdigest()
    with library_write(project)as library:
        base=library/asset_id;dest=base/version
        local_path(project.root,os.path.relpath(dest/'manifest.json',project.root))
        if dest.exists():
            record=read(dest/'manifest.json');verify_object_asset(project,record);return record
        base.mkdir(parents=True,exist_ok=True);pending=base/('.building-'+uuid.uuid4().hex);pending.mkdir()
        try:
            # Closure is already package-local; retaining its relative layout
            # keeps shader and mesh references byte-identical.
            for p in sorted(closure):
                target=pending/'usd'/p.relative_to(source.parent);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
            entry=pending/'usd'/source.name;owned,_=inspect_usda(entry)
            from pxr import UsdGeom,UsdPhysics
            for prim in owned.Traverse():
                if prim.IsA(UsdGeom.Mesh)and prim.HasAPI(UsdPhysics.CollisionAPI):
                    UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr('convexHull')
            owned.GetRootLayer().Save()
            visual,collision,size=_convert(owned,pending)
            if dimensions is not None and not dimensions_match(dimensions['value'],size):raise ValueError('USDA bounds disagree with declared object dimensions; fix Blender scale')
            dimension_record=copy.deepcopy(dimensions)if dimensions else value(size,'estimated',['authored USDA mesh bounds'])
            if dimensions and any(d is None for d in dims):
                dimension_record=value(size,'estimated',['authored USDA mesh bounds; only specified axes are constrained'])
                dimension_record['constraints']=copy.deepcopy(dimensions)
            if blend:shutil.copyfile(blend,pending/'source.blend')
            manifest={'schema':'real2sim.object-asset/1','asset_id':asset_id,'version':version,'entry':'usd/'+source.name,
                'default_prim':str(stage.GetDefaultPrim().GetPath()),'units':'m','up_axis':'Z','origin':origin,
                'dimensions':dimension_record,
                'visual':visual,'collision':collision,'collision_status':'AUTHORED_UNVALIDATED'if collision else'UNRESOLVED',
                'source_sha256':sha(source),'source_blend':'source.blend'if blend else None,'physical_verified':False,
                'files':{p.relative_to(pending).as_posix():sha(p)for p in pending.rglob('*')if p.is_file()}}
            if generation_id:manifest['generation_request_id']=generation_id
            manifest['manifest']=os.path.relpath(dest/'manifest.json',project.root)
            write(pending/'manifest.json',manifest);pending.rename(dest)
        except BaseException:
            shutil.rmtree(pending,ignore_errors=True);raise
        verify_object_asset(project,manifest)
        return manifest


def verify_object_asset(project,record):
    path=local_path(project.root,record['manifest']);base=path.parent
    base_root=project.workspace/'object_assets'if Path(record['manifest']).parts[:3]==('..','..','object_assets')else project.root/'input/object_assets'
    expected=base_root/identifier(record['asset_id'])/record['version']/'manifest.json'
    if path!=expected or read(path)!=record:raise ValueError('Object asset ID/version/manifest identity mismatch')
    if record.get('schema')!='real2sim.object-asset/1':raise ValueError('Unsupported object asset manifest')
    for relative,digest in record['files'].items():
        if Path(relative).is_absolute()or any(p in('..','.')for p in Path(relative).parts):raise ValueError('Object asset dependency escapes version')
        target=base
        for part in Path(relative).parts:
            target=target/part
            if target.is_symlink():raise ValueError('Object asset dependency symlink is forbidden')
        target=target.resolve()
        if not target.is_relative_to(base)or not target.is_file()or sha(target)!=digest:raise ValueError('Object asset dependency changed: '+relative)
    inspect_usda(base/record['entry'])
    return record


def list_object_assets(project):
    """Metadata catalogue only; validate closure strictly when a version is used.

    One malformed entry is an item error, never a failure of unrelated Scenes.
    No USD imports or texture reads are needed to populate a menu.
    """
    result=[]
    for path in asset_manifests(project):
        relative=os.path.relpath(path,project.root)
        summary={'asset_id':path.parent.parent.name,'version':path.parent.name,'manifest':relative,
                 'collision_status':'UNRESOLVED','dimensions':None}
        try:
            checked=local_path(project.root,relative)
            record=read(checked)
            if not isinstance(record,dict)or record.get('schema')!='real2sim.object-asset/1':raise ValueError('Invalid asset manifest metadata')
            if any(record.get(k)!=summary[k]for k in('asset_id','version','manifest')):raise ValueError('Asset ID/version/path mismatch')
            if not all(k in record for k in('files','dimensions','collision_status','entry')):raise ValueError('Incomplete asset metadata')
            result.append(record)
        except (ValueError,OSError,KeyError,TypeError,YAMLError)as error:
            result.append({**summary,'error':str(error)})
    return result


def publish_object_asset(project,manifest,*,source_project=None):
    """Explicitly publish a verified legacy version; never retarget its Scenes."""
    owner=source_project or project
    original=verify_object_asset(owner,read(local_path(owner.root,manifest)))
    source=local_path(owner.root,manifest).parent
    with library_write(project)as library:
        dest=library/original['asset_id']/original['version']
        reference=os.path.relpath(dest/'manifest.json',project.root)
        local_path(project.root,reference)
        record={**original,'manifest':reference}
        if dest.exists():
            current=verify_object_asset(project,read(dest/'manifest.json'))
            if current!=record:raise ValueError('Workspace Asset ID/version collision; existing version preserved')
            return current
        dest.parent.mkdir(parents=True,exist_ok=True);pending=dest.with_name('.building-'+uuid.uuid4().hex);pending.mkdir()
        try:
            for relative,digest in original['files'].items():
                target=pending/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source/relative,target)
                if sha(target)!=digest:raise ValueError('Legacy asset changed during publication')
            write(pending/'manifest.json',record);pending.rename(dest)
        except BaseException:
            shutil.rmtree(pending,ignore_errors=True);raise
        return verify_object_asset(project,record)


def instance_operation(project,manifest,name,*,pose=None,role='manipulable_object'):
    """One existing edit operation: add an instance plus its immutable assets."""
    record=verify_object_asset(project,read(local_path(project.root,manifest)));base=local_path(project.root,manifest).parent
    assets={};prefix='oa_'+__import__('hashlib').sha256((record['asset_id']+':'+record['version']).encode()).hexdigest()[:12]+'_'
    for index,(relative,digest)in enumerate(record['files'].items()):
        assets[prefix+str(index)]={'path':os.path.relpath(base/relative,project.root),'sha256':digest,'source':'object USDA asset','category':'visual'}
    manifest_key=prefix+'manifest'
    assets[manifest_key]={'path':manifest,'sha256':sha(local_path(project.root,manifest)),'source':'immutable Object Asset Manifest','category':'metadata'}
    keys={r['path']:k for k,r in assets.items()}
    def geometry(rows):
        result=[]
        for row in rows:
            part={k:copy.deepcopy(v)for k,v in row.items()if k!='file'}
            part['asset']=keys[os.path.relpath(base/row['file'],project.root)]
            if part.get('texture'):part['texture']=keys[os.path.relpath(base/part['texture'],project.root)]
            result.append(part)
        return {'type':'compound','parts':result}if result else{'type':'unknown'}
    entry_key=keys[os.path.relpath(base/record['entry'],project.root)]
    return {'op':'add_object','id':identifier(name),'role':role,'pose':transform(np.eye(4)if pose is None else pose).tolist(),
        'unknown_pose':pose is None,
        'dimensions':record['dimensions']['value'],'dimension_record':record['dimensions'],
        'visual':geometry(record['visual']),'collision':geometry(record['collision']),'assets':assets,
        'object_asset':{'asset_id':record['asset_id'],'version':record['version'],'entry_asset':entry_key,'default_prim':record['default_prim'],
            'collision_status':record['collision_status'],'manifest_asset':manifest_key,'manifest_sha256':sha(local_path(project.root,manifest))}}
