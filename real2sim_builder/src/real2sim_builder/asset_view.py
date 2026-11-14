"""Read-only preview of verified native USD through the canonical converter.

No alternate asset store or primitive proxy. Temporary OBJ/PNG derivatives are
owned by this call, never written into the immutable Library version.
"""
import base64
import io
import tempfile
from pathlib import Path
import numpy as np
from .files import read
from .scene import local_path


def load_asset_view(project, manifest):
    from .object_assets import verify_object_asset,inspect_usda,_convert
    from .calibration.geometry import obj_data
    from PIL import Image
    record=verify_object_asset(project,read(local_path(project.root,manifest)))
    entry=local_path(project.root,manifest).parent/record['entry']
    stage,_=inspect_usda(entry)
    meshes=[]
    with tempfile.TemporaryDirectory(prefix='real2sim-asset-preview-')as tmp:
        folder=Path(tmp);visual,collision,bounds=_convert(stage,folder)
        for kind,parts in [('visual',visual),('collision',collision)]:
            for part in parts:
                vertices,faces,uv=obj_data(folder/part['file'])
                texture=None
                if part.get('texture'):
                    with Image.open(folder/part['texture'])as source:
                        image=source.convert('RGB');image.thumbnail((1024,1024))
                        stream=io.BytesIO();image.save(stream,format='PNG');texture=base64.b64encode(stream.getvalue()).decode()
                meshes.append({'kind':kind,'vertices':vertices.tolist(),'faces':faces.tolist(),'uv':uv.tolist(),
                    'color':part.get('color',[.5,.5,.5]),'texture_png':texture})
    return {'asset_id':record['asset_id'],'version':record['version'],'dimensions':record['dimensions'],
        'collision_status':record['collision_status'],'meshes':meshes,'physical_verified':False,
        'material_scope':'UsdPreviewSurface diffuse/UV image; OpenGL depth-buffered preview, no PBR/lighting accuracy certificate',
        'texture_scope':'Preview mip <=1024 pixels; original texture bytes preserved'}


def library_action(project,action,**args):
    """Explicit UI adapter to existing immutable Asset/Candidate APIs."""
    from .object_assets import list_object_assets,register_object_asset,publish_object_asset,instance_operation
    from .candidate import Candidate
    if action=='list':return {'assets':list_object_assets(project),'candidates':[p.parent.name for p in (project.root/'scratch/agent').glob('*/candidate.json')]}
    if action=='preview':return load_asset_view(project,args['manifest'])
    if action=='register':return register_object_asset(project,args['path'],asset_id=args['asset_id'])
    if action=='publish':return publish_object_asset(project,args['manifest'])
    if action in('instantiate','assign'):
        candidate=Candidate(project,args['candidate'])if (project.root/'scratch/agent'/args['candidate']/'candidate.json').exists()else Candidate.create(project,args['candidate'])
        candidate.require_open()
        operation=instance_operation(project,args['manifest'],args['object_id'])
        if action=='assign':
            # Existing operation preserves pose/role and rejects measured conflicts.
            operation['op']='use_object_asset'
        candidate.edit([operation])
        return {'status':'CANDIDATE_UPDATED','candidate':candidate.name,'object_id':args['object_id']}
    raise ValueError('Unsupported Object Library action')
