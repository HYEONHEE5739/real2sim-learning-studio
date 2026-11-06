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


def fitting_scores(metrics):
    """Comparable train-view residuals; no pooled score can hide a regression."""
    import math,json
    scores={}
    for row in metrics.get('images',[]):
        if row.get('split')!='train':continue
        key=json.dumps([row['image_id'],row.get('camera_type'),row.get('q_measured')],sort_keys=True)
        values=[row.get('mae'),row.get('rmse')]
        iou=row.get('edge_iou');values.append(None if iou is None else 1-iou)
        objects=sorted(row.get('objects',[]),key=lambda obj:obj['object_id'])
        key+=json.dumps([obj['object_id']for obj in objects])
        for obj in objects:
            values.extend([1-obj['iou'],obj['center_error_px'],obj['observed_point_surface_rmse_m']])
        if key in scores or any(isinstance(v,bool)or not isinstance(v,(int,float))or not math.isfinite(v)for v in values):return {}
        scores[key]=values
    return scores


def retain_fitting(candidate,best,report):
    """Retain a valid non-regressing round and its mutable Candidate closure."""
    import shutil,uuid
    metrics=read(candidate.root/'metrics.json');scores=fitting_scores(metrics)
    if not scores:return best
    signature=candidate.project.signature(candidate.scene)
    if metrics.get('input_signature')!=signature:raise ValueError('Stale fitting checkpoint metrics')
    if best:
        previous=read(best/'manifest.json');old=previous['scores']
        if any(signature[key]!=previous['signature'][key]for key in ('evidence_sha256','scene_memo_sha256')):return best
        def external_files(record):
            return {path:digest for path,digest in record['files'].items()
                if not(candidate.project.root/path).is_relative_to(candidate.root)}
        if external_files(signature)!=external_files(previous['signature']):return best
        if scores.keys()!=old.keys():return best
        pairs=[(value,prior)for key in scores for value,prior in zip(scores[key],old[key])]
        if any(len(scores[k])!=len(old[k])for k in scores)or any(a>b for a,b in pairs)or not any(a<b for a,b in pairs):return best
    folder=candidate.root/'fitting/checkpoints'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    write(folder/'scene.yaml',candidate.scene);write(folder/'report.json',report)
    paths=set()
    for relative in signature['files']:
        path=candidate.project.root/relative
        if path.is_relative_to(candidate.root):paths.add(path)
    for name in ('metrics.json','reconstruction-config.yaml','review-config.yaml','fitting/codex-review.json','modeling/results.json','modeling/tasks.json'):
        path=candidate.root/name
        if path.is_file():paths.add(path)
    for name in ('fitting/final/previews','physics'):
        path=candidate.root/name
        if path.exists():paths.update(p for p in path.rglob('*')if p.is_file())
    files={}
    for path in paths:
        relative=path.relative_to(candidate.root).as_posix();target=folder/'files'/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);files[relative]=sha(target)
    write(folder/'manifest.json',{'scores':scores,'signature':signature,'files':files,
        'scene_sha256':sha(folder/'scene.yaml'),'report_sha256':sha(folder/'report.json')})
    return folder


def restore_fitting(candidate,folder):
    """Validate all saved bytes before restoring only Candidate-owned files."""
    import shutil
    manifest=read(folder/'manifest.json')
    for name,key in (('scene.yaml','scene_sha256'),('report.json','report_sha256')):
        if sha(folder/name)!=manifest[key]:raise ValueError('Corrupt fitting checkpoint')
    for relative,digest in manifest['files'].items():
        target=(candidate.root/relative).resolve()
        if not target.is_relative_to(candidate.root.resolve())or sha(folder/'files'/relative)!=digest:
            raise ValueError('Corrupt fitting checkpoint file')
    for relative,digest in manifest['signature']['files'].items():
        path=candidate.project.root/relative
        if not path.is_relative_to(candidate.root)and sha(path)!=digest:
            raise ValueError('External input changed since fitting checkpoint')
    for relative in manifest['files']:
        target=candidate.root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(folder/'files'/relative,target)
    candidate.save(read(folder/'scene.yaml'))
    if candidate.project.signature(candidate.scene)!=manifest['signature']:raise ValueError('Fitting checkpoint signature mismatch')


def reconstruct(project,*,candidate,config=None,scene_state=None,run_modeling=False,max_modeling_calls=6,modeling_timeout_s=900,max_review_calls=3,refit_only=False):
    """Keep the best comparable round even on Stop, child failure or budget exit."""
    best=[None];result=None;failure=None
    with exclusive(project):
        try:
            result=_reconstruct_loop(project,candidate=candidate,config=config,scene_state=scene_state,
                run_modeling=run_modeling,max_modeling_calls=max_modeling_calls,modeling_timeout_s=modeling_timeout_s,
                max_review_calls=max_review_calls,refit_only=refit_only,best=best)
            return result
        except Exception as error:
            failure=error
            raise
        finally:
            if best[0] is not None:
                selected=Candidate(project,candidate)
                restored=selected.project.signature(selected.scene)!=read(best[0]/'manifest.json')['signature']
                restore_fitting(selected,best[0])
                path=selected.root/'reconstruction.json'
                final=result if result is not None else(read(path)if path.is_file()else {'status':'FAILED'})
                if failure is not None:final.update(status='STOPPED'if isinstance(failure,InterruptedError)else'FAILED',error=str(failure))
                final['selected_checkpoint']=str(best[0]);final['restored_best']=restored
                final['input_signature']=project.signature(selected.scene)
                if restored:
                    final['latest_attempt']={k:copy.deepcopy(final[k])for k in ('stages','visual_review')if k in final}
                    saved=read(best[0]/'report.json');final['stages']=saved.get('stages',{})
                    final.pop('visual_review',None)
                    if final.get('status')=='VISUAL_DRAFT_REVIEWED':final['status']='BEST_RESTORED_UNVERIFIED'
                write(path,final)


def _reconstruct_loop(project,*,candidate,config=None,scene_state=None,run_modeling=False,max_modeling_calls=6,modeling_timeout_s=900,max_review_calls=3,refit_only=False,best=None):
    """Hold the existing Project lock across every pipeline stage."""
    with exclusive(project):
        if isinstance(max_modeling_calls,bool)or not isinstance(max_modeling_calls,int)or max_modeling_calls<0:
            raise ValueError('Nonnegative integer max_modeling_calls required')
        if isinstance(max_review_calls,bool)or not isinstance(max_review_calls,int)or max_review_calls<0:
            raise ValueError('Nonnegative integer max_review_calls required')
        calls=0;reviews=0;history=[]
        while True:
            result=_reconstruct(project,candidate=candidate,config=config,scene_state=scene_state,refit_only=refit_only)
            if not run_modeling:return result
            result['modeling_calls']=calls
            if result.get('stages',{}).get('codex_review',{}).get('status')=='WAITING_FOR_CODEX_REVIEW' and result['status']not in('FAILED','STOPPED'):
                best[0]=retain_fitting(Candidate(project,candidate),best[0],result)
            if result['status']not in('WAITING_FOR_CODEX_ANALYSIS','WAITING_FOR_CODEX'):
                review_stage=result.get('stages',{}).get('codex_review',{})
                result.update(review_calls=reviews,review_history=history)
                if review_stage.get('status')!='WAITING_FOR_CODEX_REVIEW' or result['status'] in ('FAILED','STOPPED'):
                    write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                    return result
                if reviews>=max_review_calls:
                    result.update(status='REVIEW_BUDGET_EXHAUSTED',stop_reason='max_review_calls')
                    write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                    return result
                from .authoring import run_codex_modeling
                selected=Candidate(project,candidate)
                # Retain each evaluated Scene before a structural replacement.
                # This is a resumable checkpoint, not a claim of global optimum.
                import uuid
                folder=selected.root/'fitting/reviews'/uuid.uuid4().hex
                write(folder/'scene.yaml',selected.scene)
                write(folder/'metrics.json',read(selected.root/'metrics.json'))
                try:
                    project.checkpoint()
                    modeling_tasks(selected,config or read(project.root/'input/reconstruction.yaml'),None)
                    judged=run_codex_modeling(selected,timeout_s=modeling_timeout_s,review_fitting=True)
                except Exception as error:
                    result.update(status='STOPPED'if isinstance(error,InterruptedError)else'FAILED',
                        failed_stage='CODEX_REVIEW',error=str(error))
                    write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                    if isinstance(error,InterruptedError):return result
                    raise
                reviews+=1;decision=judged['decision'];history.append(decision)
                write(folder/'decision.json',judged)
                result.update(review_calls=reviews,review_history=history,visual_review=decision)
                action=decision['action']
                if action in ('complete','needs_data'):
                    result.update(status='VISUAL_DRAFT_REVIEWED'if action=='complete'else'NEEDS_MORE_DATA',physical_verified=False)
                    write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                    return result
                config=copy.deepcopy(config or read(project.root/'input/reconstruction.yaml'))
                if action=='numeric':
                    if decision['objects']:config.setdefault('fitting',{})['objects']=decision['objects']
                else:
                    if calls>=max_modeling_calls:
                        result.update(status='WAITING_FOR_CODEX',stop_reason='max_modeling_calls')
                        write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                        return result
                    refit_only=False  # Explicit structural diagnosis: new Candidate asset versions, never source Export edits.
                    config['fitting_feedback']=judged.get('feedback',{})
                    for name in decision['objects']:
                        if name not in config.get('objects',{}):raise ValueError('No modeling configuration for '+name)
                        spec=config['objects'][name]
                        spec.pop('asset_manifest',None)
                        spec.update(modeling_action='new',modeling_request_id='review_'+uuid.uuid4().hex)
                        spec['modeling_notes']=str(spec.get('modeling_notes',''))+'\nFitting review: '+decision['reason']
                # Changes belong to this Candidate, never the user's original memo.
                write(selected.root/'review-config.yaml',config)
                continue
            if calls>=max_modeling_calls:
                result['stop_reason']='max_modeling_calls'
                write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                return result
            from .authoring import run_codex_modeling
            try:
                project.checkpoint()
                modeled=run_codex_modeling(Candidate(project,candidate),timeout_s=modeling_timeout_s)
            except Exception as error:
                status='STOPPED'if isinstance(error,InterruptedError)else'FAILED'
                result.update(status=status,error=str(error),failed_stage='CODEX_MODELING',modeling_calls=calls)
                write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                project.update(status=status,stage='CODEX_MODELING',error=str(error),task='Candidate retained; resume reconstruction')
                if isinstance(error,InterruptedError):return result
                raise
            calls+=1
            if modeled['status']not in('REGISTERED_UNVALIDATED','ASSETS_READY','ANALYZED_OBJECT_PROPOSALS'):
                result.update(status=modeled['status'],modeling_calls=calls,modeling=modeled)
                write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                return result
            # Analysis writes the typed plan through the existing configuration
            # owner. Continue with that plan, never the stale caller snapshot.
            saved=project.root/'input/reconstruction.yaml'
            if saved.is_file() and not reviews:config=read(saved)


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
                    from .capture import mapping_coordinates_equal
                    if model.get('mapping')and not mapping_coordinates_equal(model['mapping'],mapping):raise ValueError('Source Revision mapping differs from Pair')
            # Source geometry/assets are immutable; derived fitting inputs belong to the new layout.
            for key in('reconstruction_observations','derived_observations','view_registrations','camera_predictions','reconstruction_configuration'):
                scene.pop(key,None)
            validate(scene,project.root,complete=True)
            record={'identity':identity,'path':path.relative_to(project.root).as_posix(),
                'authored_scene_sha256':sha(path/'authored_scene.json')}
            return scene,record,None,None
        except (ValueError,OSError,KeyError)as error:failures.append(str(error))
    return None,None,'PAIR_SOURCE_UNRESOLVED','Verified source Revision unavailable: '+'; '.join(failures)


def refit_pairs(project,*,candidate,scene_state,dataset=None,config=None,include_flagged_reason=None,run_modeling=False,max_modeling_calls=6,max_review_calls=3):
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
        result=reconstruct(project,candidate=candidate,config=config,scene_state=scene_state,refit_only=True,
            run_modeling=run_modeling,max_modeling_calls=max_modeling_calls,max_review_calls=max_review_calls)
        result['source_revision']=revision
        result['pair_diagnostics']={'observations':[i['id']for i in paired],
            'tracking':[{'image_id':i['id'],'measured_q':i.get('q_measured'),'runtime':i.get('runtime_baseline')}for i in paired],
            'geometry':('Source Export unchanged; reviewed structural corrections create Candidate asset versions'if run_modeling else'Source Revision geometry/material/collision unchanged; pose/camera fitting only'),
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
        # Pair refitting preserves the source Revision's geometry and materials.
        fitting['optimize_dimensions']=False
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
                from .authoring import fitting_review
                review=fitting_review(selected)
                report['stages']['codex_review']={'status':review['status'],'path':str(selected.root/'fitting/codex-review.json'),'wrist_observed':review['wrist_observed']}
                report['stages']['camera_quality']=metrics.get('camera_quality',{'status':'NOT_VERIFIED','needs':['Per-camera quality not evaluated']})
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
            if report['status']=='DRAFT_READY'and report['stages']['camera_quality']['status']!='CRITERIA_MET_UNVERIFIED':
                report['status']='NOT_VERIFIED'
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
