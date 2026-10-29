"""Frozen measured Real/Sim observations in the existing Builder Pair format."""
from pathlib import Path
import os
import numpy as np
from PIL import Image
from ..data.native import atomic_json,file_sha256,digest


def write_pair(root,manifest,pending,rendered):
    """Fill the existing snapshot paired-observation/1 before it is published."""
    from real2sim_builder.files import read
    from real2sim_builder.validation import compare
    root=Path(root);row=manifest['snapshots'][0];shot=root/row['path'];metadata=read(shot/'metadata.json')
    if rendered['measured_q_rad']!=pending['sample']['q_measured']:raise ValueError('Renderer result does not match frozen measured q')
    context={'workspace_id':manifest['project_id'],'content_sha256':rendered['scene_identity']['manifest_sha256'],'builder':{'manifest_sha256':digest(rendered['scene_identity'])}}
    metrics={};sim_files={}
    for image in metadata['images']:
        name=image['camera'];rgb=rendered['images'][name];real=np.asarray(Image.open(shot/image['path']).convert('RGB'));sim='sim_'+name+'.png'
        transport=rendered.get('files',{}).get(name)
        if transport is not None:
            if file_sha256(transport['path'])!=transport['sha256']:raise ValueError('Rendered transport bytes changed')
            if not(shot/sim).exists():os.link(transport['path'],shot/sim)
            if file_sha256(shot/sim)!=transport['sha256']:raise ValueError('Paired render bytes changed while sharing')
        else:Image.fromarray(rgb).save(shot/sim)
        metadata['files'][sim]=file_sha256(shot/sim);sim_files[name]=sim
        # Existing Builder diagnostics emit normalized RGB metrics and visual comparisons.
        metrics[name]={**compare(real,rgb,shot/'comparison'/name,save_inputs=False),'objects':rendered.get('geometry',{}).get(name,[]),'landmark_rmse_px':None,'mask_iou':None,'geometry_status':'UNMEASURED'}
    for path in (shot/'comparison').rglob('*.png'):metadata['files'][path.relative_to(shot).as_posix()]=file_sha256(path)
    pair={k:v for k,v in rendered.items()if k not in('images','files','id','requested_ns','generation','result_latency_ms')};pair.update(schema='real2sim.paired-observation/1',meaning='historical_runtime_baseline_not_ground_truth',
        measurement_basis='follower_feedback',workspace_context=context,sim_q_measured_rad=rendered['applied_sim_joint_rad'],quality={'eligible':not pending['quality'],'warnings':pending['quality'],'physical_verified':False},
        sim_images=sim_files,comparison=metrics,hardware_synchronized=False,source_capture_timestamp_ns=pending['sample']['timestamp_ns'])
    atomic_json(shot/'pair.json',pair);metadata['files']['pair.json']=file_sha256(shot/'pair.json');atomic_json(shot/'metadata.json',metadata)
    row['metadata_sha256']=file_sha256(shot/'metadata.json');pending['comparison']=metrics
