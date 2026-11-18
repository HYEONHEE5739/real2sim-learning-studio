"""Frozen measured Real/Sim observations in the existing Builder Pair format."""
from pathlib import Path
import os
import numpy as np
from PIL import Image
from ..data.native import atomic_json,file_sha256,digest


def write_pair(root,manifest,pending,rendered,*,diagnostics=True):
    """Fill the existing snapshot paired-observation/1 before it is published."""
    from real2sim_builder.files import read
    from real2sim_builder.validation import compare
    root=Path(root);row=manifest['snapshots'][0];shot=root/row['path'];metadata=read(shot/'metadata.json')
    if rendered['measured_q_rad']!=pending['sample']['q_measured']:raise ValueError('Renderer result does not match frozen measured q')
    from real2sim_builder.capture import snapshot_metadata
    committed = snapshot_metadata(shot)
    if 'pair.json' in committed['files']:
        pair = read(shot/'pair.json')
        if pair['scene_identity'] != rendered['scene_identity'] or pair['measured_q_rad'] != rendered['measured_q_rad']:
            raise ValueError('Conflicting Pair identity')
        pending['comparison'] = pair['comparison']
        return
    if manifest.get('pair_scene_identity') is not None and manifest['pair_scene_identity'] != rendered['scene_identity']:
        raise ValueError('Rendered Scene differs from requested Scene')
    derived = {}
    context={'workspace_id':manifest['project_id'],'content_sha256':rendered['scene_identity']['manifest_sha256'],'builder':{'manifest_sha256':digest(rendered['scene_identity'])}}
    metrics={};sim_files={}
    for image in metadata['images']:
        name=image['camera'];transport=rendered.get('files',{}).get(name)
        rgb=rendered.get('images',{}).get(name)
        if rgb is None:
            if transport is None:raise ValueError('Frozen Sim image is missing')
            rgb=np.asarray(Image.open(transport['path']).convert('RGB'))
        real=np.asarray(Image.open(shot/image['path']).convert('RGB'));sim='sim_'+name+'.png'
        if transport is not None:
            if file_sha256(transport['path'])!=transport['sha256']:raise ValueError('Rendered transport bytes changed')
            (shot/sim).unlink(missing_ok=True)
            os.link(transport['path'],shot/sim)
        else:
            (shot/sim).unlink(missing_ok=True)
            Image.fromarray(rgb).save(shot/sim,compress_level=1)
        sim_sha=file_sha256(shot/sim)
        if transport is not None and sim_sha!=transport['sha256']:raise ValueError('Paired render bytes changed while sharing')
        derived[sim]=sim_sha;sim_files[name]=sim
        # Existing Builder diagnostics emit normalized RGB metrics and visual comparisons.
        metrics[name]={**compare(real,rgb,shot/'comparison'/name,save_inputs=False,png_compress_level=1,save_images=diagnostics),'objects':rendered.get('geometry',{}).get(name,[]),'landmark_rmse_px':None,'mask_iou':None,'geometry_status':'UNMEASURED'}
    for path in (shot/'comparison').rglob('*.png'):derived[path.relative_to(shot).as_posix()]=file_sha256(path)
    pair={k:v for k,v in rendered.items()if k not in('images','files','id','requested_ns','generation','result_latency_ms')};pair.update(schema='real2sim.paired-observation/1',meaning='historical_runtime_baseline_not_ground_truth',
        measurement_basis='follower_feedback',workspace_context=context,sim_q_measured_rad=rendered['applied_sim_joint_rad'],quality={'eligible':not pending['quality'],'warnings':pending['quality'],'physical_verified':False},
        sim_images=sim_files,comparison=metrics,hardware_synchronized=False,source_capture_timestamp_ns=pending['sample']['timestamp_ns'])
    pair['comparison_images']={'status':'AVAILABLE'if diagnostics else'DEFERRED','source':'saved original Real/Sim RGB, immutable Scene/q/camera metadata'}
    atomic_json(shot/'pair.json',pair);derived['pair.json']=file_sha256(shot/'pair.json')
    atomic_json(shot/'pair-manifest.json',dict(schema='real2sim.capture-pair/1',raw_metadata_sha256=file_sha256(shot/'metadata.json'),files=derived))
    pending['comparison']=metrics


def render_comparisons(root,destination):
    """Create disposable diagnostics outside the immutable Capture; no renderer."""
    from real2sim_builder.files import read
    from real2sim_builder.scene import local_path
    from real2sim_builder.validation import compare
    root=Path(root).resolve();destination=Path(destination).resolve()
    if destination.is_relative_to(root):raise ValueError('Derived comparisons must stay outside the immutable original Capture')
    from real2sim_builder.capture import snapshot_metadata
    metadata=snapshot_metadata(root)
    if file_sha256(root/'pair.json')!=metadata['files']['pair.json']:raise ValueError('Source Pair hash changed')
    pair=read(root/'pair.json');prepared=[];sources={}
    for camera,sim in pair['sim_images'].items():
        original=next(row['path']for row in metadata['images']if row['camera']==camera)
        paths=[]
        for relative in(original,sim):
            path=local_path(root,relative)
            if file_sha256(path)!=metadata['files'][relative]:raise ValueError('Original comparison image hash changed')
            sources[relative]=metadata['files'][relative];paths.append(path)
        prepared.append((camera,paths))
    # Validate every source before writing any derivative.
    outputs=[]
    for camera,(original,sim)in prepared:
        with Image.open(original)as a,Image.open(sim)as b:
            metrics=compare(np.asarray(a.convert('RGB')),np.asarray(b.convert('RGB')),destination/camera,save_inputs=False,png_compress_level=1)
        if any(not np.isclose(metrics[k],pair['comparison'][camera][k],rtol=0,atol=1e-12)for k in metrics):
            raise ValueError('Saved comparison metrics differ from immutable source')
        outputs.extend(str(destination/camera/(kind+'.png'))for kind in('side_by_side','overlay','difference'))
    atomic_json(destination/'source.json',{'pair_sha256':metadata['files']['pair.json'],'images':sources,
        'scene_identity':pair.get('scene_identity'),'measured_q_rad':pair.get('measured_q_rad'),'sim_cameras':pair.get('sim_cameras')})
    return outputs
