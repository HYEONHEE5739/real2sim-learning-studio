"""Automated Candidate reconstruction in the existing Project lifecycle.

    Each expensive model owns one sequential child in inference.py. Geometry,
    registration, fitting and reports remain local; Current and prior exports
    are never replaced by this entry point.
"""
from .files import read,write,sha
from .candidate import Candidate,exclusive


def board_binding(scene,name,uv):
    """Four explicitly identified top corners of an existing metric World board."""
    import numpy as np
    from .scene import world_pose
    obj=next(o for o in scene['objects']if o['id']==name)
    if obj['dimensions']['provenance']not in('measured','calibrated')or obj['pose']['provenance']not in('measured','calibrated'):
        raise ValueError('보드의 실측 크기와 World 위치가 필요합니다. 추정값을 측정 Anchor로 승격하지 않습니다.')
    pixels=np.asarray(uv,float)
    if pixels.shape!=(4,2)or not np.isfinite(pixels).all():raise ValueError('Identify four board corners in original image pixels')
    x,y,z=np.asarray(obj['dimensions']['value'])/2;pose=world_pose(scene,obj)
    corners=np.array([[-x,-y,z],[x,-y,z],[x,y,z],[-x,y,z]])@pose[:3,:3].T+pose[:3,3]
    return {'world_points_m':corners.tolist(),'uv_px':pixels.tolist(),'source':'measured',
            'evidence':obj['dimensions'].get('evidence',[])+obj['pose'].get('evidence',[])+['measured World board '+name]}


def save_configuration(project,config):
    """Persist one user configuration in Project, shared by CLI and both UIs."""
    import copy
    data=copy.deepcopy(config)
    if not isinstance(data,dict):raise ValueError('Reconstruction configuration must be a mapping')
    with exclusive(project):
        write(project.root/'input/reconstruction.yaml',data)
        project.invalidate()
    return data


def reconstruct(project,*,candidate,config=None,scene_state=None):
    """Hold the existing Project lock across every pipeline stage."""
    with exclusive(project):
        return _reconstruct(project,candidate=candidate,config=config,scene_state=scene_state)


def _reconstruct(project,*,candidate,config=None,scene_state=None):
    from .initialization import measured_geometry
    from .observations import register_views
    from .inference import run_models,build_point_clouds
    from .calibration.hybrid import compare_backends
    from .validation import physics_probe
    configuration=project.root/'input/reconstruction.yaml'
    config=read(configuration)if config is None else config
    selected=Candidate(project,candidate)if(project.root/'scratch/agent'/candidate/'candidate.json').exists()else Candidate.create(project,candidate)
    selected.require_open()
    frozen=selected.root/'reconstruction-config.yaml';write(frozen,config)
    scene=selected.scene;scene['reconstruction_configuration']={'path':frozen.relative_to(project.root).as_posix(),'sha256':sha(frozen),'provenance':'derived'}
    selected.save(scene)
    report={'candidate':candidate,'status':'NEEDS_MORE_DATA','physical_verified':False,'stages':{},'needs':[]}
    def progress(stage,task):
        project.checkpoint();project.update(status='RUNNING',stage=stage,task=task,candidate=candidate)
    try:
        progress('GEOMETRY','Build measured geometry; preserve Robot and Current')
        with exclusive(project):selected.save(measured_geometry(selected.scene,config.get('measurements',[])))
        progress('CAMERA & SCALE','Register image views from Camera calibration / measured anchors')
        registration=register_views(selected,config.get('anchors'),scene_state=scene_state or config.get('scene_state_id'))
        report['stages']['registration']=registration
        progress('ANALYZE','SAM segmentation followed by DA3 depth')
        inferred=run_models(selected,config,scene_state=registration['scene_state_id'])
        report['stages']['inference']={'status':inferred['status'],'report':str(selected.root/'inference/results.json')}
        if inferred['status']=='INFERRED':
            progress('GEOMETRY','Build only anchored metric visible object clouds')
            clouds=build_point_clouds(selected,inferred,selections=config.get('selections'))
            report['stages']['clouds']=clouds
            if clouds['clouds']:
                progress('GEOMETRY','Compare landmark / ICP-mask / hybrid drafts')
                with exclusive(project):
                    scene,comparison=compare_backends(project,selected.scene,selected.root/'fitting',config.get('fitting'))
                    selected.save(scene)
                    chosen=comparison.get('requested_backend')
                    metrics=comparison.get('backends',{}).get(chosen,{}).get('metrics')
                    if metrics:
                        # Existing promotion explicitly rejects this scope.
                        # A user can still request an unvalidated review export.
                        write(selected.root/'metrics.json',{**metrics,'scope':'train render only','passed':False,
                            'needs':['Unvalidated automated draft; independent reconstruction/physics review required']})
                report['stages']['fitting']=comparison
                progress('PHYSICS','Passive object collision/gravity probe')
                with exclusive(project):report['stages']['physics']=physics_probe(project,selected.scene,selected.root/'physics')
        for stage in report['stages'].values():report['needs'].extend(stage.get('needs',[]))
        if not report['stages'].get('clouds',{}).get('clouds'):report['needs'].append('Metric cloud/identity inputs incomplete; no pose was invented')
        report['needs']=list(dict.fromkeys(report['needs']))
        report['input_signature']=project.signature(selected.scene)
        write(selected.root/'reconstruction.json',report)
        project.update(status='NEEDS_MORE_DATA',stage='VALIDATION',decision='NEEDS_MORE_DATA',needs=report['needs'],task='Candidate retained; review reconstruction.json')
        return report
    except InterruptedError:
        report.update(status='STOPPED');write(selected.root/'reconstruction.json',report)
        project.update(status='STOPPED',task='Reconstruction stopped; Candidate/cache retained');return report
    except Exception as error:
        report.update(status='FAILED',error=str(error));write(selected.root/'reconstruction.json',report)
        project.update(status='FAILED',error=str(error),task='Candidate retained; inspect stage logs');raise
