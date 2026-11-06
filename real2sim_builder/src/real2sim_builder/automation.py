"""Automated Candidate reconstruction in the existing Project lifecycle.

    Each expensive model owns one sequential child in inference.py. Geometry,
    registration, fitting and reports remain local; Current and prior exports
    are never replaced by this entry point.
"""
from .files import read,write,sha
from .candidate import Candidate,exclusive
from .authoring import modeling_tasks,attach_modeled_assets,analysis_required
import copy


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


def reconstruct(project,*,candidate,config=None,scene_state=None):
    """Hold the existing Project lock across every pipeline stage."""
    with exclusive(project):
        return _reconstruct(project,candidate=candidate,config=config,scene_state=scene_state)


def captured_robot(candidate,images):
    """Reuse archived URDF/FK/Mapping in the Candidate without editing Current."""
    from .scene import local_path,value
    from .calibration.geometry import reference_geometry,reference_model
    from .evidence import asset_importer
    from .capture import load_snapshots
    import numpy as np
    scene=candidate.scene
    if scene.get('robot_model'):return {'status':'EXISTING_MODEL'}
    image=next((i for i in images if i.get('capture_manifest')and i.get('q_measured')is not None),None)
    if image is None:return {'status':'UNRESOLVED','needs':['No mapped Robot Capture; relative RGB analysis remains available']}
    root=local_path(candidate.project.root,image['capture_manifest']).parent
    manifest,_,_=load_snapshots(root,scene_state=image['scene_state_id'])
    model=root/manifest['robot']['path'];joints=dict(zip(image['joint_names'],image['q_measured']))
    scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated',['robot-base coordinate gauge, not measured World registration'])}
    importer=asset_importer(candidate.project,scene)
    if model.suffix.lower()=='.urdf':objects,fk=reference_geometry(model,joints,importer)
    else:objects,fk=reference_model(model,joints,importer,candidate.root/'robot_reference')
    scene['objects'].extend(objects)
    for name,pose in fk.items():scene['frames']['robot_link_'+name]={'parent':'robot_base','transform':value(pose.tolist(),'derived',['recorded measured-q FK'])}
    scene['robot_model']={'format':'urdf'if model.suffix.lower()=='.urdf'else'mjcf','path':model.relative_to(candidate.project.root).as_posix(),
        'model_sha256':sha(model),'source_robot_sha256':manifest.get('source_robot_sha256'),'joint_names':image['joint_names'],
        'mapping':manifest['joint_mapping'],'mapping_verified':False,'joint_coordinate_status':'RECORDED_MODEL_RAD; physical verification unchanged'}
    candidate.save(scene)
    return {'status':'IMPORTED_REFERENCE','model_sha256':sha(model),'physical_verified':False,'scope':'recorded model/mapping; no control or Calibration approval'}


def pair_source(project,images):
    """Resolve one manifest-covered authored Revision; never substitute Current."""
    import copy
    from dataclasses import asdict
    from pathlib import Path
    from .scene import local_path,validate
    from .export import verify_package
    identities=[];baselines=[]
    for image in images:
        baseline=copy.deepcopy(image['runtime_baseline'])
        if baseline.get('pair_path'):
            path=local_path(project.root,baseline['pair_path'])
            if not path.is_file()or sha(path)!=baseline.get('pair_sha256'):
                return None,None,'PAIR_SOURCE_MISMATCH','Recorded Pair SHA mismatch'
            pair=read(path)
            if baseline.get('scene_identity')and baseline['scene_identity']!=pair.get('scene_identity'):
                return None,None,'PAIR_SOURCE_MISMATCH','Registered and archived Pair source identities disagree'
            baseline.update({k:pair[k]for k in('scene_identity','source_scene','joint_mapping')if k in pair})
        baselines.append(baseline);identity=baseline.get('scene_identity')
        if not identity or set(identity)!={'scene_id','revision','manifest_sha256'}:
            return None,None,'PAIR_SOURCE_UNRESOLVED','Pair lacks a complete source Scene identity'
        if baseline.get('workspace_context',{}).get('content_sha256')!=identity['manifest_sha256']:
            return None,None,'PAIR_SOURCE_MISMATCH','Pair source identity disagrees with its recorded manifest'
        hint=baseline.get('source_scene',{})
        if hint.get('identity',identity)!=identity:return None,None,'PAIR_SOURCE_MISMATCH','Pair source locator identity mismatch'
        identities.append(identity)
    if any(i!=identities[0]for i in identities):return None,None,'PAIR_SOURCE_MISMATCH','Select one source Revision per refit group'
    identity=identities[0]
    paths=[project.root/r['path']for r in project.info.get('execution_packages',[])]
    paths.extend(p.parent for p in (project.root/'exports').glob('*/scene.json'))
    paths.extend(p.parent for p in (project.root/'input/refit_sources').glob('*/scene.json'))
    for baseline in baselines:
        hint=baseline.get('source_scene',{}).get('package_path')
        if hint:
            path=Path(hint)
            if path.resolve().is_relative_to(project.root):paths.append(path)
    failures=[]
    for path in dict.fromkeys(paths):
        try:
            if sha(path/'manifest.json')!=identity['manifest_sha256']:continue
            package=verify_package(path)
            if asdict(package.identity)!=identity:raise ValueError('Scene identity differs from Pair')
            if 'authored_scene.json'not in{f.path for f in package.files}:raise ValueError('Source Revision has no manifest-covered authored Scene')
            for baseline in baselines:
                expected=baseline.get('source_scene',{}).get('authored_scene_sha256')
                if expected and expected!=sha(path/'authored_scene.json'):raise ValueError('Pair authored Scene SHA mismatch')
            scene=copy.deepcopy(read(path/'authored_scene.json'))
            for asset in scene['assets'].values():asset['path']=local_path(path,asset['path']).relative_to(project.root).as_posix()
            if scene.get('robot_model'):
                model=scene['robot_model'];model['path']=local_path(path,model['path']).relative_to(project.root).as_posix()
                for image,baseline in zip(images,baselines):
                    if image.get('joint_names')!=model['joint_names']:raise ValueError('Pair measured joint order differs from source Revision')
                    if image.get('robot_model_sha256')!=model['model_sha256']:
                        # Reuse the package's existing baked Geometry binding. The
                        # measured coordinate model and baked FK model can differ;
                        # this never permits arbitrary SHA aliases or q offsets.
                        bound=[r for r in package.calibration['records'].values()if r['kind']=='robot_residual'
                            and r['application']['mode']=='baked'and r.get('source_model_sha256')==image.get('robot_model_sha256')
                            and r.get('execution_model_sha256')==model['model_sha256']]
                        if len(bound)!=1:raise ValueError('Pair measured Robot model differs from source Revision without a verified baked binding')
                    mapping=baseline.get('joint_mapping')
                    if not mapping or mapping.get('sha256')!=image.get('mapping_sha256'):raise ValueError('Pair mapping identity mismatch')
                    if model.get('mapping')and model['mapping'].get('sha256')!=mapping['sha256']:raise ValueError('Source Revision mapping differs from Pair')
            # Source geometry/assets are immutable; derived fitting inputs belong to the new layout.
            for key in('reconstruction_observations','derived_observations','view_registrations','camera_predictions','reconstruction_configuration'):
                scene.pop(key,None)
            validate(scene,project.root,complete=True)
            record={'identity':identity,'path':path.relative_to(project.root).as_posix(),
                'authored_scene_sha256':sha(path/'authored_scene.json')}
            return scene,record,None,None
        except (ValueError,OSError,KeyError)as error:failures.append(str(error))
    return None,None,'PAIR_SOURCE_UNRESOLVED','Verified source Revision unavailable: '+'; '.join(failures)


def refit_pairs(project,*,candidate,scene_state,dataset=None,config=None,include_flagged_reason=None):
    """Existing Pair reader/import -> layout-specific Candidate -> cached fitting.

    Runtime Sim is diagnostic only. Measured q and original Real RGB drive the
    new Candidate. Asset geometry is reused, not reauthored for a pose change.
    """
    from .capture import import_paired,load_snapshots
    from .observations import input_images
    import copy
    from .scene import identifier
    identifier(candidate)
    def unavailable(code,needs):
        result={'candidate':candidate,'status':'NEEDS_MORE_DATA','code':code,'needs':needs,'physical_verified':False}
        target=project.root/'scratch/agent'/candidate
        if(target/'candidate.json').exists():write(target/'reconstruction.json',result)
        project.update(status=result['status'],needs=needs,task='Pair source/layout requires review')
        return result
    with exclusive(project):
        if dataset:
            manifest,_,_=load_snapshots(dataset,scene_state=scene_state)
            session=manifest['session_id']
            if not any(r['id']==session for r in project.evidence.get('capture_sessions',[])):
                import_paired(project,dataset,scene_state=scene_state,include_flagged_reason=include_flagged_reason)
        images,_,needs=input_images(project,scene_state)
        paired=[i for i in images if i.get('runtime_baseline')]
        if not paired:return unavailable('PAIR_SOURCE_UNRESOLVED',needs+['Select a completed registered Real/Sim Pair session in this layout'])
        if any(i.get('scene_state_id')!=scene_state for i in paired):
            return unavailable('PAIR_LAYOUT_MISMATCH',['Select one physical layout per refit'])
        source,revision,code,reason=pair_source(project,paired)
        if code:return unavailable(code,[reason])
        exists=(project.root/'scratch/agent'/candidate/'candidate.json').exists()
        if exists:
            selected=Candidate(project,candidate)
            if selected.info.get('source_revision')!=revision or selected.scene.get('reconstruction_state',{}).get('id')!=scene_state:
                return unavailable('PAIR_CANDIDATE_MISMATCH',['Use a new Candidate for this source Revision/layout'])
        else:
            selected=Candidate.create(project,candidate,source_scene=source,source_revision=revision)
            scene=selected.scene;scene['reconstruction_state']={'id':scene_state,'static_layout_verified':False};selected.save(scene)
        config=copy.deepcopy(read(project.root/'input/reconstruction.yaml')if config is None else config);config['scene_state_id']=scene_state
        config['image_ids']=[i['id']for i in paired]
        result=_reconstruct(project,candidate=candidate,config=config,scene_state=scene_state,refit_only=True)
        result['source_revision']=revision
        result['pair_diagnostics']={'observations':[i['id']for i in paired],
            'tracking':[{'image_id':i['id'],'measured_q':i.get('q_measured'),'runtime':i.get('runtime_baseline')}for i in paired],
            'geometry':'Source Revision geometry/material/collision unchanged; pose/camera fitting only',
            'appearance':'RGB residual alone cannot identify texture/light/geometry cause',
            'robot_q':'recorded measured q is immutable; runtime tracking differences are diagnostics'}
        write(selected.root/'reconstruction.json',result)
        return result


def draft_readiness(project,scene,comparison):
    """Review draft gate; independent accuracy and physics approval remain separate."""
    from .scene import validate
    import math
    needs=list(comparison.get('observability',{}).get('needs',[]))
    try:validate(scene,project.root,complete=True)
    except ValueError as error:needs.append(str(error))
    if not scene.get('cameras'):needs.append('Usable Camera required for a rendered draft')
    if comparison.get('status')!='OPTIMIZED_UNVERIFIED'or not comparison.get('converged')or not comparison.get('training_view_count')or not math.isfinite(comparison.get('after_loss',float('inf'))):
        needs.append('Native multiview fitting must finish with finite training loss; exhausted budget is not convergence')
    return {'status':'DRAFT_READY'if not needs else'NEEDS_MORE_DATA','needs':needs,'physical_verified':False}


def _reconstruct(project,*,candidate,config=None,scene_state=None,refit_only=False):
    from .initialization import measured_geometry
    from .observations import register_views,predict_views
    from .inference import run_models,build_point_clouds
    from .calibration.hybrid import fit_scene,alignment_metrics
    from .validation import physics_probe
    configuration=project.root/'input/reconstruction.yaml'
    config=read(configuration)if config is None else config
    config=copy.deepcopy(config)
    fitting=config.setdefault('fitting',{})
    fitting.setdefault('optimize_appearance',not refit_only)
    fitting.setdefault('optimize_lighting',not refit_only)
    if refit_only:
        # Pair refitting preserves the source Revision's material contract.
        fitting['optimize_appearance']=False;fitting['optimize_lighting']=False
    selected=Candidate(project,candidate)if(project.root/'scratch/agent'/candidate/'candidate.json').exists()else Candidate.create(project,candidate)
    selected.require_open()
    frozen=selected.root/'reconstruction-config.yaml';write(frozen,config)
    scene=selected.scene;scene['reconstruction_configuration']={'path':frozen.relative_to(project.root).as_posix(),'sha256':sha(frozen),'provenance':'derived'}
    selected.save(scene)
    report={'candidate':candidate,'status':'NEEDS_MORE_DATA','physical_verified':False,'stages':{},'needs':[]}
    def progress(stage,task):
        project.checkpoint();project.update(status='RUNNING',stage=stage,task=task,candidate=candidate)
    try:
        from .evidence import scene_memo
        if not refit_only and analysis_required(config,scene_memo(project)['sha256']):
            progress('CODEX ANALYSIS','Interpret the current literal Scene memo and photos')
            modeling=modeling_tasks(selected,config,{})
            report.update(status=modeling['status'],needs=modeling['needs'],input_signature=project.signature(selected.scene))
            report['stages']['modeling']=modeling
            write(selected.root/'reconstruction.json',report)
            project.update(status=report['status'],stage='CODEX ANALYSIS',needs=report['needs'],task='Current Scene memo requires Codex interpretation')
            return report
        from .authoring import geometry_specs
        geometry=geometry_specs(config,selected.scene)
        progress('ANALYZE','SAM segmentation followed by DA3 depth')
        inferred=run_models(selected,config,scene_state=scene_state or config.get('scene_state_id'))
        report['stages']['inference']={'status':inferred['status'],'report':str(selected.root/'inference/results.json')}
        report['stages']['inference']['needs']=inferred.get('needs',[])
        if inferred['status']=='INFERRED':
            progress('CAMERA & SCALE','Estimate cameras from DA3 overlap and observable robot motion')
            report['stages']['robot_reference']=captured_robot(selected,inferred['images'])
            if not refit_only:selected.save(measured_geometry(selected.scene,geometry))
            report['stages']['camera_predictions']=predict_views(selected,inferred,{**config.get('camera_initialization',{}),'measurements':[s for s in geometry if s.get('provenance','measured')in('measured','calibrated')and all(v is not None for v in s['dimensions_m'])]})
        # Existing audited calibration / explicit advanced anchors remain usable;
        # they are not required user inputs for the automatic path.
        registration=register_views(selected,config.get('anchors'),scene_state=scene_state or config.get('scene_state_id'))
        if not report['stages'].get('camera_predictions',{}).get('views'):report['stages']['registration']=registration
        clouds={'clouds':[]}
        if inferred['status']=='INFERRED':
            progress('OBSERVATIONS','Backproject and associate all usable metric views before authoring')
            clouds=build_point_clouds(selected,inferred,selections=config.get('selections'))
            report['stages']['clouds']=clouds
        progress('GEOMETRY','Preserve measurements; attach reusable object assets')
        if refit_only:
            report['stages']['assets']={'attached':[],'scope':'Source Revision geometry/material/collision preserved'}
            report['stages']['modeling']={'status':'ASSETS_READY','pending':[]}
        else:
            if inferred['status']!='INFERRED':selected.save(measured_geometry(selected.scene,geometry))
            report['stages']['assets']=attach_modeled_assets(selected,config,inferred)
            report['stages']['modeling']=modeling_tasks(selected,config,inferred)
        if inferred['status']=='INFERRED'and report['stages']['modeling']['status']=='ASSETS_READY':
            if clouds['clouds']:
                from .calibration.hybrid import fit_clouds
                from .scene import validate
                if any(o['pose']['value']is None for o in selected.scene['objects']):
                    initialized,initial_report=fit_clouds(project,selected.scene,config.get('fitting'))
                    selected.save(initialized);report['stages']['pose_initialization']=initial_report
                try:validate(selected.scene,project.root,complete=True)
                except ValueError as error:
                    report['stages']['completeness']={'status':'NEEDS_MORE_DATA','needs':[str(error)]}
                    clouds['clouds']=[]
            if clouds['clouds']:
                progress('FITTING','Native multiview Camera/Object Render-to-Real closed loop')
                with exclusive(project):
                    try:scene,comparison=fit_scene(project,selected.scene,selected.root/'fitting',fitting)
                    except (InterruptedError,ValueError,RuntimeError)as error:
                        if hasattr(error,'best_scene'):selected.save(error.best_scene)
                        raise
                    selected.save(scene)
                    metrics=alignment_metrics(project,scene,selected.root/'fitting/final',fitting)
                    write(selected.root/'metrics.json',{**metrics,'scope':'train render only','passed':False,
                        'needs':['Unvalidated automated draft; independent reconstruction/physics review required']})
                report['stages']['fitting']=comparison
                progress('PHYSICS','Passive object collision/gravity probe')
                with exclusive(project):report['stages']['physics']=physics_probe(project,selected.scene,selected.root/'physics')
        for stage in report['stages'].values():report['needs'].extend(stage.get('needs',[]))
        if not report['stages'].get('clouds',{}).get('clouds'):report['needs'].append('Metric cloud/identity inputs incomplete; no pose was invented')
        report['needs']=list(dict.fromkeys(report['needs']))
        modeling=report['stages']['modeling']['status']
        if modeling in('WAITING_FOR_CODEX','WAITING_FOR_CODEX_ANALYSIS'):report['status']=modeling
        elif report['stages'].get('fitting'):
            readiness=draft_readiness(project,selected.scene,report['stages']['fitting'])
            report['stages']['draft_readiness']=readiness;report['status']=readiness['status'];report['needs'].extend(readiness['needs'])
        report['input_signature']=project.signature(selected.scene)
        write(selected.root/'reconstruction.json',report)
        project.update(status=report['status'],stage='VALIDATION',decision='CONTINUE'if report['status']=='DRAFT_READY'else'NEEDS_MORE_DATA',needs=report['needs'],task='Candidate retained; review reconstruction.json')
        return report
    except InterruptedError:
        report.update(status='STOPPED');write(selected.root/'reconstruction.json',report)
        project.update(status='STOPPED',task='Reconstruction stopped; Candidate/cache retained');return report
    except Exception as error:
        report.update(status='FAILED',error=str(error));write(selected.root/'reconstruction.json',report)
        project.update(status='FAILED',error=str(error),task='Candidate retained; inspect stage logs');raise
