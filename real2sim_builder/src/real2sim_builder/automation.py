"""Stage reconstruction and existing Real/Sim refinement on one Project lifecycle.

Actual RGB interpretation, sandboxed Blender assets, native multiview render
review and durable visual evidence share one bounded resumable loop. Current
Scenes, measured inputs and prior exports remain protected.
"""
from scene_contract.naming import numbered_path
from .files import read,write,sha
from .candidate import Candidate,exclusive
from .authoring import modeling_tasks,attach_modeled_assets,analysis_required
import copy


def _run_stage_pipeline(project, *, candidate, config, worker=None, through_stage=14):
    """Existing Project-owned orchestration with immutable per-stage attempts.

    `worker` replaces only heavy dependency calls in synthetic tests; stage
    processing, control, signatures, publication and reuse are always real.
    """
    from pathlib import Path
    from . import reconstruction_stages as processing
    from .stage_artifacts import StageArtifact, StageNeeds, STAGE_NAMES, manifest, verify_manifest, cache_key, digest
    from . import stage_runtime
    from dataclasses import fields
    config=copy.deepcopy(config or {})
    stage_runtime.validate_configuration(config)
    if type(through_stage)is not int or not 1<=through_stage<=14:raise ValueError('Invalid final stage')
    with exclusive(project):
        selected=Candidate(project,candidate)if(project.root/'scratch/agent'/candidate/'candidate.json').is_file()else Candidate.create(project,candidate)
        selected.require_open()
        from .scene import validate
        validate(selected.scene,project.root)
        if not(selected.root/'reconstruction-config.yaml').exists():write(selected.root/'reconstruction-config.yaml',config)
        root=selected.root/'reconstruction/simfoundry';root.mkdir(parents=True,exist_ok=True)
        initial=root/'initial_scene.yaml'
        if not initial.exists():
            write(initial,selected.scene)
            prior=selected.root/'reconstruction.json'
            if prior.is_file():write(root/'prior_reconstruction.json',read(prior))
        inputs=[initial]
        from .evidence import scene_memo
        memo=scene_memo(project)
        selected_inputs=[row for row in project.evidence.get('images',[])
            if row.get('role')=='scene_photo'and row.get('camera_type')=='external'
            and not row.get('runtime_baseline')and row.get('split','train')=='train'
            and(config.get('scene_state_id')is None or row.get('scene_state_id')==config['scene_state_id'])]
        selected_inputs += [row for row in project.evidence.get('videos',[])if row.get('role')=='scene_video'
            and(config.get('scene_state_id')is None or row.get('scene_state_id')==config['scene_state_id'])]
        inputs.extend(project.root/row['path']for row in selected_inputs)
        upstream=manifest(inputs,{'project':project.info['id'],'candidate':candidate,'scene_inputs':selected_inputs})
        index_path=root/'cache.json';index=read(index_path)if index_path.is_file()else{}
        if index.get('candidate_scene_sha256')not in(None,digest(selected.scene)):
            raise ValueError('Candidate Scene changed outside the retained stage checkpoint; review before resuming')
        report_path=selected.root/'reconstruction.json'
        previous_report=read(report_path)if report_path.is_file()else{}
        report={'pipeline':'simfoundry/1','candidate':candidate,'status':'RUNNING','stages':{},
                'needs':[],'physical_verified':False,'input_signature':upstream['data'],
                'not_tested':['real model accuracy','real physics stability','hardware/Task success']}
        if previous_report.get('pipeline')=='simfoundry/1'and previous_report.get('status')=='STOPPED':project.control('resume')
        data={};active=1;folder=None;identity={'kind':'mock'if worker is not None else'real'};subset={}
        keys={1:('scene_state_id','video_candidates'),2:('depth',),3:('support','z_far'),4:('metric_anchors','world_registration'),
              5:('objects','decomposition','scene_memo'),6:('image_preparation','pose'),7:('codex','objects','execute_modeling','max_modeling_calls','modeling_timeout_s'),
              8:('pose',),9:('articulation',),10:('world_registration','support_asset','sensor_registration','metric_anchors','capture_layouts'),11:('physics',),12:('physics',),13:('export',),14:('simulator',)}
        operations={1:('video',),2:('da3',),3:('support','vlm'),4:(),5:('vlm','segments','removal','image_edit_removal','depth_inpaint','da3'),
                    6:('image_edit_objects','background_remove','vlm'),7:('blender',),8:('cpd','canonicalize','foundationpose'),9:('articulation',),10:(),11:('vlm',),12:('physics',),13:(),14:('simulator',)}
        handlers={1:processing.prepare,2:processing.depth,3:processing.support,4:processing.world,
                  5:processing.decompose,6:processing.prepare_objects,7:processing.meshes,8:processing.poses,9:processing.articulate,10:processing.compile_scene,
                  11:processing.simulation_ready,12:processing.stabilize,13:processing.package_scene,14:processing.simulator_integration}
        def call(operation,request,folder):
            project.checkpoint()
            folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
            def normalized(node):
                if isinstance(node,dict):return {k:normalized(v)for k,v in node.items()}
                if isinstance(node,list):return [normalized(v)for v in node]
                if isinstance(node,str)and node.startswith('/'):
                    p=Path(node)
                    if p.is_file():return {'sha256':sha(p),'suffix':p.suffix}
                return node
            key=digest([operation,normalized(request),identity])
            cache=folder/'worker-cache.json'
            if cache.is_file():
                saved=read(cache)
                if saved['key']!=key:raise ValueError('Incomplete worker input identity changed')
                verify_manifest(saved['manifest'],output_root=folder)
                response=folder/'response.json'
                if (saved.get('execution')!=identity['kind']or not response.is_file()
                    or not any(Path(row['path'])==response.resolve()for row in saved['manifest']['files'])
                    or digest(saved['data'])!=digest(read(response))):
                    raise ValueError('Worker cache response integrity mismatch')
                return saved['data']
            result=worker(operation,request,Path(folder))if worker is not None else stage_runtime.invoke(selected,config,operation,request,folder,provider=call)
            if not isinstance(result,dict):raise ValueError('Typed worker result mapping required')
            result={**result,'_execution':identity['kind']}
            write(folder/'response.json',result)
            write(cache,{'key':key,'manifest':manifest(sorted(p for p in folder.rglob('*')if p.is_file()and p!=cache)),
                         'data':result,'execution':identity['kind']})
            project.checkpoint()
            return result
        def publish_report():
            report['completion']={'object_reconstruction':'COMPLETE'if '8'in report['stages']else'INCOMPLETE',
                'scene_compilation':'COMPLETE'if '10'in report['stages']else'UNRESOLVED',
                'sensor_accuracy':'NOT_VERIFIED','physical_task':'NOT_VERIFIED'}
            report['resume']={'available':True,'candidate':candidate,'incomplete_stage':report.get('failed_stage'),
                              'completed_stages':[k for k,s in report['stages'].items()if s['status']=='COMPLETE']}
            index['candidate_scene_sha256']=digest(selected.scene);write(index_path,index)
            write(report_path,report)
        def failure_record(status,error):
            import shutil
            failure=numbered_path(root/'failures'/('stage_'+str(active)),'attempt');failure.mkdir(parents=True)
            if folder is not None and folder.is_dir():
                for source in folder.rglob('*'):
                    if source.is_file():
                        target=failure/'partial'/source.relative_to(folder);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            write(failure/'failure.json',{'status':status,'type':type(error).__name__,'message':str(error),'gate':getattr(error,'gate',None)})
            artifact=StageArtifact.create(active,status,upstream,manifest(sorted(p for p in failure.rglob('*')if p.is_file())),runtime_identity=identity,config=subset,
                needs=[str(error)],error={'type':type(error).__name__,'code':getattr(error,'code',None),'gate':getattr(error,'gate',None)})
            artifact.validate(failure);write(failure/'artifact.json',artifact.to_dict());report['failure_artifact']=str(failure/'artifact.json')
        try:
            for stage in range(1,through_stage+1):
                active=stage;folder=None
                subset={k:config[k]for k in keys[stage]if k in config}
                if stage in(5,7):subset['scene_memo_sha256']=memo['sha256']
                if stage in(5,7):
                    from .authoring import _codex_guidance
                    subset['guidance_sha256']=_codex_guidance()[1]['sha256']
                    subset['model_references']=[r for r in project.evidence['images']if r.get('role')=='model_reference']
                if stage in(10,14):
                    from .observations import input_images
                    from .scene import local_path
                    sensors=[r for r in project.evidence['images']if r.get('camera_type')in('side','wrist')]
                    # Check actual bytes before considering a completed Stage
                    # cache. Metadata-only identities cannot detect file damage.
                    for image in sensors:
                        if sha(local_path(project.root,image['path']))!=image['sha256']:
                            raise ValueError('Sensor source SHA mismatch: '+image['id'])
                    for state in {r.get('scene_state_id')for r in sensors}:
                        input_images(project,state)  # Existing q/role/train-holdout contracts.
                    model=selected.scene.get('robot_model')
                    if model and any(r['camera_type']=='wrist'for r in sensors):
                        if not model.get('path')or not model.get('model_sha256'):
                            raise ValueError('Wrist Robot model SHA identity required')
                        if sha(local_path(project.root,model['path']))!=model['model_sha256']:
                            raise ValueError('Wrist Robot model SHA mismatch')
                    subset['sensor_captures']=sensors
                identity=copy.deepcopy(getattr(worker,'runtime_identity',None))if worker is not None else{'kind':'real','operations':{op:stage_runtime.identity(config,op)for op in operations[stage]}}
                if not identity:raise ValueError('Synthetic worker must declare explicit mock runtime identity')
                identity['stage_implementation_sha256']={str(p.relative_to(Path(__file__).parent)):sha(p)for p in Path(__file__).parent.rglob('*.py')}
                subset['schema']='simfoundry-stage/1'
                signature=cache_key(stage,upstream,subset,identity)
                cached=index.get(str(stage),{})
                if cached.get('key')==signature and cached.get('artifact'):
                    path=Path(cached['artifact'])
                    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Stage artifact outside Candidate')
                    raw=read(path);artifact=StageArtifact(**{f.name:raw[f.name]for f in fields(StageArtifact)})
                    artifact.validate(path.parent)
                    if artifact.status!='COMPLETE':raise ValueError('Only complete stages may be reused')
                    report['stages'][str(stage)]={'status':'COMPLETE','artifact':str(path),'reused':True}
                else:
                    project.checkpoint()
                    project.update(status='RUNNING',stage='STAGE_'+str(stage),candidate=candidate,task=STAGE_NAMES[stage-1])
                    if cached.get('key')==signature and cached.get('pending'):
                        folder=Path(cached['pending'])
                        if not folder.resolve().is_relative_to((root/f'stage_{stage:02d}').resolve()):raise ValueError('Pending stage outside Candidate')
                    else:
                        folder=numbered_path(root/f'stage_{stage:02d}','attempt');folder.mkdir(parents=True)
                        index[str(stage)]={'key':signature,'pending':str(folder)};write(index_path,index)
                    handler=handlers.get(stage)
                    if handler is None:raise StageNeeds('NOT_SUPPORTED','Stage '+str(stage)+' is not implemented yet')
                    output=handler(selected,config,data,folder,call)
                    project.checkpoint()
                    write(folder/'payload.json',output)
                    files=sorted(p for p in folder.rglob('*')if p.is_file())
                    artifact=StageArtifact.create(stage,'COMPLETE',upstream,manifest(files,output),
                        runtime_identity=identity,config=subset,coordinate_frame=output.get('coordinate_frame','not_applicable'),
                        warnings=output.get('warnings',[]))
                    artifact.validate(folder);path=folder/'artifact.json';write(path,artifact.to_dict())
                    index[str(stage)]={'key':signature,'artifact':str(path)};write(index_path,index)
                    report['stages'][str(stage)]={'status':'COMPLETE','artifact':str(path),'reused':False}
                index['candidate_scene_sha256']=digest(selected.scene);write(index_path,index)
                if not report['stages'][str(stage)]['reused']:
                    from .visual_evidence import record
                    images=sorted(p for p in path.parent.rglob('*.png'))[:12]
                    record(selected,'simfoundry_'+str(stage).zfill(2),'COMPLETE',images=images,files=[path],
                        summary=STAGE_NAMES[stage-1]+'; '+artifact.provenance['execution']+'; accuracy NOT_VERIFIED',details={'stage_id':stage,'execution':artifact.provenance['execution']})
                data[stage]=artifact.output_manifest['data']
                upstream=manifest([path],{'previous_output_sha256':artifact.output_sha256,'data':data[stage]})
                publish_report()
                # Stop after a cached stage still retains its completed record.
                project.checkpoint()
            report['status']='DRAFT_READY'if through_stage==14 else'STAGES_COMPLETE'
            project.update(status='DRAFT_READY'if through_stage==14 else'NEEDS_MORE_DATA',stage='STAGE_'+str(through_stage),
                           candidate=candidate,task='Stage artifacts retained; accuracy remains separately verified')
            publish_report();return report
        except (StageNeeds,InterruptedError)as error:
            failure_record('STOPPED'if isinstance(error,InterruptedError)else error.status,error)
            report.update(status='STOPPED'if isinstance(error,InterruptedError)else error.status,failed_stage=active,needs=[str(error)],error_code=getattr(error,'code',None))
            report['gate']=getattr(error,'gate',None)
            project.update(status='STOPPED'if isinstance(error,InterruptedError)else'NEEDS_MORE_DATA',stage='STAGE_'+str(active),candidate=candidate,needs=report['needs'])
            publish_report();return report
        except Exception as error:
            failure_record('FAILED',error)
            report.update(status='FAILED',failed_stage=active,error={'type':type(error).__name__,'message':str(error)})
            project.update(status='FAILED',stage='STAGE_'+str(active),candidate=candidate,error=str(error))
            publish_report();raise


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
        if row.get('split')!='train'or row.get('use_for_best_selection')is False:continue
        key=json.dumps([row['image_id'],row.get('camera_type'),row.get('q_measured')],sort_keys=True)
        values=[row.get('mae'),row.get('rmse')]
        iou=row.get('edge_iou');values.append(None if iou is None else 1-iou)
        objects=sorted(row.get('objects',[]),key=lambda obj:obj['object_id'])
        key+=json.dumps([obj['object_id']for obj in objects])
        for obj in objects:
            values.extend([1-obj['iou'],obj['center_error_px']])
            if obj.get('observed_point_surface_rmse_m')is not None:values.append(obj['observed_point_surface_rmse_m'])
        if key in scores or any(isinstance(v,bool)or not isinstance(v,(int,float))or not math.isfinite(v)for v in values):return {}
        scores[key]=values
    return scores


def retain_fitting(candidate,best,report):
    """Retain a valid non-regressing round and its mutable Candidate closure."""
    import shutil,uuid
    from .scene import validate
    validate(candidate.scene,candidate.project.root)
    metrics=read(candidate.root/'metrics.json');scores=fitting_scores(metrics)
    if not scores:return best
    signature=candidate.project.signature(candidate.scene)
    from .visual_evidence import run_identity
    if best and read(best/'manifest.json').get('authoring_run')!=run_identity(candidate):best=None
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
    folder=numbered_path(candidate.root/'fitting/checkpoints','checkpoint')
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
    write(folder/'manifest.json',{'scores':scores,'signature':signature,'files':files,'authoring_run':run_identity(candidate),
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
    """Default SimFoundry stages; Real/Sim continues its existing source refit."""
    if refit_only:
        return _refit_reconstruct(project,candidate=candidate,config=config,scene_state=scene_state,
            run_modeling=run_modeling,max_modeling_calls=max_modeling_calls,modeling_timeout_s=modeling_timeout_s,
            max_review_calls=max_review_calls,refit_only=True)
    configured=copy.deepcopy(config if config is not None else read(project.root/'input/reconstruction.yaml')if(project.root/'input/reconstruction.yaml').is_file()else{})
    from .stage_runtime import workspace_configuration,runtime_environment
    configured=workspace_configuration(project,configured)
    if scene_state is not None:configured['scene_state_id']=scene_state
    configured.update(execute_modeling=bool(run_modeling),max_modeling_calls=max_modeling_calls,modeling_timeout_s=modeling_timeout_s)
    if type(max_modeling_calls)is not int or not 1<=max_modeling_calls<=30:raise ValueError('Bounded Codex call budget required')
    if not 1<=modeling_timeout_s<=3600:raise ValueError('Bounded Codex deadline required')
    with runtime_environment(configured):
        return _run_stage_pipeline(project,candidate=candidate,config=configured)


def _refit_reconstruct(project,*,candidate,config=None,scene_state=None,run_modeling=False,max_modeling_calls=6,modeling_timeout_s=900,max_review_calls=3,refit_only=False):
    """Keep the best comparable round even on Stop, child failure or budget exit."""
    best=[None];result=None;failure=None
    with exclusive(project):
        prior_path=project.root/'scratch/agent'/candidate/'reconstruction.json'
        prior=read(prior_path)if prior_path.is_file()else{}
        checkpoint=prior.get('selected_checkpoint')
        if checkpoint:
            from pathlib import Path
            saved=Path(checkpoint).resolve()
            if not saved.is_relative_to(project.root/'scratch/agent'/candidate/'fitting/checkpoints'):
                raise ValueError('Checkpoint is outside this Candidate')
            if saved.is_dir():
                manifest=read(saved/'manifest.json')
                from .visual_evidence import run_identity
                current=Candidate(project,candidate)
                if project.signature(current.scene)==manifest['signature']and manifest.get('authoring_run')==run_identity(current):best[0]=saved
        # A completed Stop can leave a late control message. Clear it only under the lock.
        project.control('resume')
        initial_result=None
        if best[0] is not None and prior.get('failed_stage')=='CODEX_REVIEW':
            selected=Candidate(project,candidate)
            frozen=selected.root/'reconstruction-config.yaml'
            requested=config if config is not None else read(project.root/'input/reconstruction.yaml')
            if frozen.is_file()and _fitting_configuration(requested,refit_only)==read(frozen)and scene_state in(None,requested.get('scene_state_id')):
                restore_fitting(selected,best[0])
                initial_result=read(best[0]/'report.json')
        try:
            result=_reconstruct_loop(project,candidate=candidate,config=config,scene_state=scene_state,
                run_modeling=run_modeling,max_modeling_calls=max_modeling_calls,modeling_timeout_s=modeling_timeout_s,
                max_review_calls=max_review_calls,refit_only=refit_only,best=best,initial_result=initial_result)
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
            path=project.root/'scratch/agent'/candidate/'reconstruction.json'
            if (path.parent/'candidate.json').is_file():
                final=read(path)if path.is_file()else(result or {'status':'FAILED'})
                if failure is not None:final.update(status='STOPPED'if isinstance(failure,InterruptedError)else'FAILED',error=str(failure),error_code=getattr(failure,'code',None))
                selected=Candidate(project,candidate)
                if project.state.get('candidate')==candidate:
                    final.setdefault('modeling_calls',project.state.get('codex_calls',0))
                    final.setdefault('review_calls',project.state.get('review_calls',0))
                final['resume']={'candidate':candidate,'available':selected.info['status']=='OPEN',
                    'input_signature':project.signature(selected.scene),'stage':project.state.get('stage'),
                    'completed_stages':[k for k,v in final.get('stages',{}).items()if v.get('status')in('RENDERED','COMPOSED_ESTIMATED','ASSETS_READY')],
                    'incomplete_stage':final.get('failed_stage')or project.state.get('stage')}
                from .visual_evidence import run_identity
                final['pipeline']='codex-first/2';final['authoring_run']=run_identity(selected)
                if final.get('status')in('FAILED','STOPPED'):
                    project.update(status=final['status'],stage=final.get('failed_stage')or project.state.get('stage'),
                        error=final.get('error'),error_code=final.get('error_code'),
                        task='Candidate and completed evidence retained; resume the unfinished stage')
                write(path,final)
                if result is not None:result.update(final)
                if final.get('pipeline')=='codex-first/2':
                    from .visual_evidence import record,finish_iteration,current_images
                    status=final.get('status')
                    if status in('STOPPED','FAILED'):finish_iteration(selected,status=status)
                    metrics=read(selected.root/'metrics.json')if(selected.root/'metrics.json').is_file()else{}
                    images=current_images(selected,kinds=('sim','side_by_side'),metrics=metrics)if metrics.get('input_signature')==project.signature(selected.scene)else[]
                    record(selected,'06_final_comparison','STOPPED'if status=='STOPPED'else'FAILED'if status=='FAILED'else'COMPLETE'if images else'NOT_VERIFIED',
                        images=images,files=[p for p in(path,selected.root/'metrics.json')if p.is_file()],
                        summary='Selected best actual Scene / '+str(status)+'; independent sensor, physics and Task verification remain separate',
                        details={'candidate_status':selected.info['status'],'selected_checkpoint':final.get('selected_checkpoint'),
                            'restored_best':final.get('restored_best',False),'unverified':final.get('needs',[])})


def _reconstruct_loop(project,*,candidate,config=None,scene_state=None,run_modeling=False,max_modeling_calls=6,modeling_timeout_s=900,max_review_calls=3,refit_only=False,best=None,initial_result=None):
    """Hold the existing Project lock across every pipeline stage."""
    with exclusive(project):
        saved_config=project.root/'input/reconstruction.yaml'
        config=copy.deepcopy(config if config is not None else read(saved_config)if saved_config.is_file()else{})
        config['authoring_mode']='codex'
        if isinstance(max_modeling_calls,bool)or not isinstance(max_modeling_calls,int)or max_modeling_calls<0:
            raise ValueError('Nonnegative integer max_modeling_calls required')
        if isinstance(max_review_calls,bool)or not isinstance(max_review_calls,int)or max_review_calls<0:
            raise ValueError('Nonnegative integer max_review_calls required')
        previous_path=project.root/'scratch/agent'/candidate/'reconstruction.json'
        previous=read(previous_path)if previous_path.is_file()else{}
        from .visual_evidence import run_identity
        if previous and ((previous.get('pipeline')!='codex-first/2')or(previous.get('authoring_run')and previous['authoring_run']!=run_identity(Candidate(project,candidate)))):
            previous={}
        calls=previous.get('modeling_calls',0);reviews=previous.get('review_calls',0);history=previous.get('review_history',[])
        project.update(codex_calls=calls,review_calls=reviews,candidate=candidate)

        while True:
            result=initial_result if initial_result is not None else _reconstruct(project,candidate=candidate,config=config,scene_state=scene_state,refit_only=refit_only)
            initial_result=None
            if not run_modeling:return result
            result['modeling_calls']=calls
            if result.get('stages',{}).get('codex_review',{}).get('status')=='WAITING_FOR_CODEX_REVIEW' and result['status']not in('FAILED','STOPPED'):
                best[0]=retain_fitting(Candidate(project,candidate),best[0],result)
            if result['status']not in('WAITING_FOR_CODEX_ANALYSIS','WAITING_FOR_CODEX','WAITING_FOR_CODEX_SCENE'):
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
                folder=numbered_path(selected.root/'fitting/reviews','review')
                write(folder/'scene.yaml',selected.scene)
                write(folder/'metrics.json',read(selected.root/'metrics.json'))
                try:
                    project.checkpoint()
                    modeling_tasks(selected,config or read(project.root/'input/reconstruction.yaml'),None)
                    project.update(status='RUNNING',stage='CODEX_REVIEW',codex_calls=calls,review_calls=reviews,task='Codex comparison judgment')
                    judged=run_codex_modeling(selected,timeout_s=modeling_timeout_s,review_fitting=True)
                except Exception as error:
                    if getattr(error,'remote_attempted',False):reviews+=1;project.update(review_calls=reviews)
                    result.update(status='STOPPED'if isinstance(error,InterruptedError)else'FAILED',
                        failed_stage='CODEX_REVIEW',error=str(error),error_code=getattr(error,'code',None),modeling_calls=calls,review_calls=reviews,review_history=history)
                    write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                    if isinstance(error,InterruptedError):return result
                    raise
                reviews+=1;project.update(review_calls=reviews);decision=judged['decision'];history.append(decision)
                write(folder/'decision.json',judged)
                result.update(review_calls=reviews,review_history=history,visual_review=decision)
                action=decision['action']
                if action in ('complete','needs_data'):
                    result.update(status='VISUAL_DRAFT_REVIEWED'if action=='complete'and not result.get('needs')else'NEEDS_MORE_DATA',physical_verified=False)
                    write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                    return result
                from .visual_evidence import start_iteration
                start_iteration(selected,decision)
                config=copy.deepcopy(config or read(project.root/'input/reconstruction.yaml'))
                if action=='numeric':
                    if decision.get('scene_plan')is None:
                        result.update(status='NEEDS_MORE_DATA',needs=['Codex correction omitted a concrete Scene plan; no Depth solver was executed'])
                        write(selected.root/'reconstruction.json',result);return result
                    config['scene_plan']=decision['scene_plan']
                else:
                    if calls>=max_modeling_calls:
                        result.update(status='WAITING_FOR_CODEX',stop_reason='max_modeling_calls')
                        write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                        return result
                    if refit_only:config['refit_structural']=True  # Stay in Pair mode; never restart initial Scene SfM.
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
                project.update(status='RUNNING',stage='SCENE_COMPOSITION'if result['status']=='WAITING_FOR_CODEX_SCENE'else'CODEX_MODELING'if result['status']=='WAITING_FOR_CODEX'else'CODEX ANALYSIS',codex_calls=calls,review_calls=reviews,task='Codex execution')
                kwargs={'compose_scene':True}if result['status']=='WAITING_FOR_CODEX_SCENE'else{}
                modeled=run_codex_modeling(Candidate(project,candidate),timeout_s=modeling_timeout_s,**kwargs)
            except Exception as error:
                if getattr(error,'remote_attempted',False):calls+=1;project.update(codex_calls=calls)
                status='STOPPED'if isinstance(error,InterruptedError)else'FAILED'
                result.update(status=status,error=str(error),error_code=getattr(error,'code',None),failed_stage='CODEX_SCENE'if result.get('status')=='WAITING_FOR_CODEX_SCENE'else'CODEX_MODELING',modeling_calls=calls,review_calls=reviews,review_history=history)
                write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                project.update(status=status,stage='CODEX_MODELING',error=str(error),task='Candidate retained; resume reconstruction')
                if isinstance(error,InterruptedError):return result
                raise
            if not modeled.get('reused'):calls+=1
            project.update(codex_calls=calls,review_calls=reviews)
            if modeled['status']=='ANALYZED_OBJECT_PROPOSALS'and modeled.get('objects')=={}:
                result.update(status='NEEDS_MORE_DATA',needs=modeled.get('needs',[]),modeling_calls=calls,modeling=modeled)
                write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                project.update(status='NEEDS_MORE_DATA',needs=result['needs'],task='Scene analysis requires additional evidence')
                return result
            if modeled['status']not in('REGISTERED_UNVALIDATED','ASSETS_READY','ANALYZED_OBJECT_PROPOSALS','SCENE_COMPOSED'):
                result.update(status=modeled['status'],modeling_calls=calls,modeling=modeled)
                write(project.root/'scratch/agent'/candidate/'reconstruction.json',result)
                return result
            # Analysis writes the typed plan through the existing configuration
            # owner. Continue with that plan, never the stale caller snapshot.
            saved=project.root/'scratch/agent'/candidate/'review-config.yaml'
            if not saved.is_file():saved=project.root/'input/reconstruction.yaml'
            if modeled.get('configuration'):
                from pathlib import Path
                response=Path(modeled['configuration']).resolve()
                if not response.is_relative_to(project.root):raise ValueError('Modeled configuration is outside Project')
                saved=response
            if saved.is_file() and(not reviews or modeled['status']=='ANALYZED_OBJECT_PROPOSALS'):config=read(saved)


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


def refine_numeric_pairs(candidate, config):
    """Bounded sensor rounds using existing solvers, render metrics and Best closure.

    Train views select Best. Holdout diagnostics never feed the solve/selection.
    Physics/Task approval and optional structural remodeling remain separate.
    """
    from .calibration import joint,hybrid
    from .editing import preserve
    from .observations import register_sensor_views
    from .stage_artifacts import digest
    from .visual_evidence import record
    project=candidate.project;options=config.get('numeric_refinement',{});limit=options.get('max_iterations',4)
    if type(limit)is not int or not 1<=limit<=20:raise ValueError('Numeric refinement iterations must be 1..20')
    fitting={**config.get('fitting',{}),'optimize_dimensions':False,'optimize_appearance':False,'optimize_lighting':False,
             'optimize_depth_scale':False,'holdout_policy':'report_only'}
    fitting.setdefault('robot_base',True)
    path=candidate.root/'numeric_refinement.json';identity=digest([config,project.evidence,candidate.info.get('source_revision')])
    prior=read(path)if path.is_file()else{}
    history=prior.get('history',[])if prior.get('identity')==identity else[]
    report={'pipeline':'numeric-pairs/1','candidate':candidate.name,'identity':identity,'status':'NEEDS_MORE_DATA',
        'history':history,'physical_verified':False,'holdout_used_for_selection':False,'needs':[],
        'accepted_iterations':sum(r.get('accepted',False)for r in history),'stages':{}}
    best=None;project.control('resume');candidate.require_open()
    (candidate.root/'fitting').mkdir(exist_ok=True)
    write(candidate.root/'reconstruction-config.yaml',config)
    try:
        registration=register_sensor_views(candidate,config,scene=candidate.scene,persist=False)
        if registration.get('needs'):report['needs']=registration['needs'];return report
        candidate.save(registration.get('scene',candidate.scene))
        # Reuse approved silhouette constraints without fabricating sensor Z.
        from .observations import annotation_evidence
        from .inference import build_render_observations
        from .scene import local_path
        import shutil
        evidence=annotation_evidence(project,candidate.scene);segments=[]
        for row in evidence.get('masks',[]):
            if row.get('mask_kind')!='silhouette'or row.get('occluded')is not False or row.get('confidence',1)<.2:continue
            source=local_path(project.root,row['path'])
            if sha(source)!=row['sha256']:raise ValueError('Reviewed sensor Mask changed')
            folder=candidate.root/'.cache/refit_masks';folder.mkdir(parents=True,exist_ok=True);target=folder/(sha(source)+'.png')
            if not target.exists():shutil.copyfile(source,target)
            segments.append({'image_id':row['observation'],'object_id':row['object'],
                'association':{'status':'ASSIGNED_ESTIMATED','mask_path':str(target),'mask_sha256':sha(target)}})
        if segments:build_render_observations(candidate,{'segments':segments,'images':[{'id':r['image_id']}for r in segments]},same_layout=True)
        from .initialization import project_supports
        baseline,physical=project_supports(candidate.scene,fitting.get('supports'),project.root)
        baseline=hybrid.reproject_observations(project,baseline,{},candidate.root/'fitting/baseline_observations')
        metrics=hybrid.alignment_metrics(project,baseline,candidate.root/'fitting/final',fitting)
        if not fitting_scores(metrics):report['needs']=metrics.get('needs',[])+['Comparable finite training renders required'];return report
        candidate.save(baseline)
        write(candidate.root/'metrics.json',metrics)
        best=retain_fitting(candidate,None,report)
        if best is None:report['needs']=metrics.get('needs',[])+['Comparable finite train Side/Wrist render metrics required'];return report
        for index in range(len(history),limit):
            report['current_iteration']=index+1;report['selected_checkpoint']=str(best)
            write(candidate.root/'reconstruction.json',report)
            project.update(status='RUNNING',stage='FITTING',candidate=candidate.name,task='Shared sensor refinement '+str(index+1))
            project.checkpoint();before=candidate.scene;round_dir=numbered_path(candidate.root/'fitting/rounds','iteration');round_dir.mkdir(parents=True)
            write(round_dir/'before.yaml',before);write(round_dir/'before-metrics.json',metrics)
            settings={**fitting,'round':index}
            trial,solver=joint.fit_joint_scene(project,before,settings)
            if solver.get('status')=='IMPROVED'and(solver.get('jacobian_rank',-1)<solver.get('parameter_count',0)):
                trial=before;solver={**solver,'status':'UNRESOLVED','needs':solver.get('needs',[])+['Rank-deficient shared Camera/Base/Object fit retained as diagnostic; Best is unchanged']}
            trial=hybrid.reproject_observations(project,trial,{},round_dir/'joint_observations')
            if options.get('render_fit',bool(trial.get('reconstruction_observations',{}).get('clouds'))):trial,render=hybrid.fit_scene(project,trial,round_dir/'render_fit',settings);solver['render']=render
            project.checkpoint();preserve(before,trial)
            from .scene import validate
            validate(trial,project.root)
            candidate.save(trial)
            after=hybrid.alignment_metrics(project,trial,round_dir/'after',settings)
            write(candidate.root/'metrics.json',after);write(round_dir/'after.yaml',trial)
            previous=best;best=retain_fitting(candidate,best,report);accepted=best!=previous
            history.append({'iteration':index,'accepted':accepted,'solver':solver,'before_metrics':metrics,'metrics':after,'folder':str(round_dir),
                            'training_ids':[r['image_id']for r in after['images']if r['split']=='train'],
                            'holdout_ids':[r['image_id']for r in after['images']if r['split']=='validation']})
            report['accepted_iterations']+=int(accepted);write(path,report)
            if not accepted:restore_fitting(candidate,best);report['needs']=solver.get('needs',[]);break
            metrics=after
        report['status']='REFINED_DRAFT'if report['accepted_iterations']else'NEEDS_MORE_DATA'
        report['stages']['fitting']={'solver_executed':True,'scope':'shared sensor/CAD pose draft; not independent calibration'}
    except InterruptedError:report['status']='STOPPED'
    except Exception as error:report.update(status='FAILED',needs=[str(error)])
    finally:
        if best is not None:restore_fitting(candidate,best);report['selected_checkpoint']=str(best)
        report['input_signature']=project.signature(candidate.scene);report['resume']={'available':True,'candidate':candidate.name}
        write(path,report);write(candidate.root/'reconstruction.json',report)
        project.update(status='DRAFT_READY'if report['status']=='REFINED_DRAFT'else report['status'],candidate=candidate.name,needs=report['needs'])
        record(candidate,'06_final_comparison','NOT_VERIFIED'if report['status']=='REFINED_DRAFT'else report['status'],files=[path],summary='Numeric Pair refinement; passive Physics/Task not executed',details=report)
    return report


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
        capture_ids=(config or{}).get('refit_capture_ids')
        if capture_ids:paired=[i for i in paired if i.get('snapshot_id')in capture_ids]
        expected=(config or{}).get('refit_source_identity')
        if expected:
            matched=[]
            for image in paired:
                baseline=image['runtime_baseline'];identity=baseline.get('scene_identity')
                if identity is None and baseline.get('pair_path'):
                    from .scene import local_path
                    path=local_path(project.root,baseline['pair_path'])
                    if sha(path)!=baseline.get('pair_sha256'):return unavailable('PAIR_SOURCE_MISMATCH',['Recorded Pair SHA mismatch'])
                    identity=read(path).get('scene_identity')
                if identity==expected:matched.append(image)
            paired=matched
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
        config=copy.deepcopy(read(project.root/'input/reconstruction.yaml')if config is None and(project.root/'input/reconstruction.yaml').is_file()else config or{})
        config['scene_state_id']=scene_state
        memo_path=project.root/'working/reconstruction_memo.json'
        if memo_path.is_file():
            import hashlib
            memo=read(memo_path)
            if hashlib.sha256(memo['text'].encode('utf-8')).hexdigest()!=memo['sha256']:raise ValueError('Reconstruction Memo SHA mismatch')
            if memo['source_identity']!=revision['identity']:return unavailable('PAIR_MEMO_SOURCE_MISMATCH',['Reconstruction Memo belongs to a different source Revision'])
            write(selected.root/'reconstruction_memo.json',memo)
            config['reconstruction_memo']=memo
        config['image_ids']=[i['id']for i in paired]
        # Each requested Capture set is explicit. Do not silently keep the
        # previous attempt's observations just because its layout label matches.
        scene=selected.scene;ids=set(config['image_ids'])
        scene['view_registrations']={key:r for key,r in scene.get('view_registrations',{}).items()if key in ids}
        if scene.get('reconstruction_observations'):
            scene['reconstruction_observations']['clouds']=[r for r in scene['reconstruction_observations']['clouds']if r['image_id']in ids]
        selected.save(scene)
        result=refine_numeric_pairs(selected,config)if config.get('numeric_refinement',{}).get('enabled',False)else reconstruct(project,candidate=candidate,config=config,scene_state=scene_state,refit_only=True,
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
    from .rendering import render_scene
    try:validate(render_scene(scene),project.root,complete=True)
    except ValueError as error:needs.append(str(error))
    rendered={c['id']for c in render_scene(scene)['cameras']}
    unresolved=[c['id']for c in scene['cameras']if c['id']not in rendered]
    if unresolved:needs.append('Unresolved sensor cameras: '+', '.join(unresolved))
    if not scene.get('cameras'):needs.append('Usable Camera required for a rendered draft')
    if comparison.get('status')!='OPTIMIZED_UNVERIFIED'or not comparison.get('converged')or not comparison.get('training_view_count')or not math.isfinite(comparison.get('after_loss',float('inf'))):
        needs.append('Native multiview fitting must finish with finite training loss; exhausted budget is not convergence')
    return {'status':'DRAFT_READY'if not needs else'NEEDS_MORE_DATA','needs':needs,'physical_verified':False}


def _fitting_configuration(config,refit_only):
    config=copy.deepcopy(config)
    config['authoring_mode']='codex'
    for key in ('sam','geometry','da3','camera_initialization','selections'):config.pop(key,None)
    fitting=config.setdefault('fitting',{})
    fitting.setdefault('optimize_appearance',not refit_only)
    fitting.setdefault('optimize_lighting',not refit_only)
    if refit_only:
        config['refit_mode']=True
        # Pair refitting preserves the source Revision's geometry and materials.
        fitting['optimize_dimensions']=False
        fitting['optimize_appearance']=False;fitting['optimize_lighting']=False
    return config


def _reconstruct(project,*,candidate,config=None,scene_state=None,refit_only=False):
    """Single Codex-first authoring path; Depth and segmentation are not prerequisites."""
    from .authoring import geometry_specs,apply_scene_plan
    from .initialization import measured_geometry,project_supports
    from .calibration.hybrid import alignment_metrics
    from .visual_evidence import record,freeze_scene,finish_iteration,current_images
    from .rendering import render_scene
    from .scene import validate
    from .validation import physics_probe
    config=copy.deepcopy(read(project.root/'input/reconstruction.yaml')if config is None else config)
    config=_fitting_configuration(config,refit_only);config['authoring_mode']='codex'
    fitting=config['fitting'];selected=Candidate(project,candidate)if(project.root/'scratch/agent'/candidate/'candidate.json').exists()else Candidate.create(project,candidate)
    selected.require_open()
    prior=selected.root/'reconstruction.json'
    if prior.is_file()and read(prior).get('pipeline')!='codex-first/2'and not(selected.root/'evidence/00_prior_candidate').exists():
        record(selected,'00_prior_candidate','REUSED',files=[p for p in(prior,selected.root/'candidate_scene.yaml',selected.root/'candidate.json',selected.root/'reconstruction-config.yaml',selected.root/'modeling/results.json')if p.is_file()],
            summary='Existing Candidate state before Codex-first execution; original inference caches remain intact')
    frozen=selected.root/'reconstruction-config.yaml';write(frozen,config)
    scene=selected.scene
    # Historical inference caches stay intact; retired generated observations do not drive this path.
    scene.pop('reconstruction_observations',None);scene.pop('camera_predictions',None)
    scene['reconstruction_configuration']={'path':frozen.relative_to(project.root).as_posix(),'sha256':sha(frozen),'provenance':'derived'}
    selected.save(scene)
    report={'candidate':candidate,'status':'NEEDS_MORE_DATA','pipeline':'codex-first/2','physical_verified':False,'stages':{},'needs':[]}
    def progress(stage,task):
        project.checkpoint();write(selected.root/'reconstruction.json',report);project.update(status='RUNNING',stage=stage,task=task,candidate=candidate)
    def finish():
        report['input_signature']=project.signature(selected.scene)
        report['evidence_index']=str(selected.root/'evidence/index.html')
        write(selected.root/'reconstruction.json',report);project.update(status=report['status'],needs=report['needs'],task='Candidate and visual evidence retained')
        return report
    try:
        from .evidence import scene_memo
        from .observations import input_images
        photos,state,needs=input_images(project,scene_state or config.get('scene_state_id'))
        config['scene_state_id']=state
        if not refit_only:
            captures=[i for i in project.evidence['images']if i.get('capture_manifest')and i.get('q_measured')is not None]
            report['stages']['robot_reference']=captured_robot(selected,captures)
        needs_analysis=(not config.get('objects'))or(not refit_only and analysis_required(config,scene_memo(project)['sha256'],project=project))
        if needs_analysis:
            progress('CODEX ANALYSIS','Read Scene/Model photos and the literal Memo')
            report['stages']['modeling']=modeling_tasks(selected,config,{})
            report['status']=report['stages']['modeling']['status'];report['needs']=report['stages']['modeling']['needs'];return finish()
        progress('GEOMETRY','Protect measurements and attach independently authored USDA assets')
        geometry=geometry_specs(config,selected.scene)
        if not refit_only:selected.save(measured_geometry(selected.scene,geometry))
        if refit_only and not config.get('refit_structural'):
            report['stages']['assets']={'attached':[],'scope':'Source Revision immutable asset versions reused'}
            task=modeling_tasks(selected,config,{})
            task.update(status='ASSETS_READY',pending=[],needs=[])
        else:
            report['stages']['assets']=attach_modeled_assets(selected,config,{})
            task=modeling_tasks(selected,config,{})
        report['stages']['modeling']=task
        if task['status']!='ASSETS_READY':report.update(status=task['status'],needs=task['needs']);return finish()
        if refit_only and not config.get('scene_plan')and selected.scene.get('cameras'):
            source=selected.scene
            if all(all(c[k]['value']is not None for k in('pose','K','distortion'))for c in source['cameras'])and all(o['pose']['value']is not None for o in source['objects']):
                config['scene_plan']={'object_poses':[],'cameras':[],'lighting':None,'needs':[]}
        from .visual_evidence import record_reused_assets
        record_reused_assets(selected,config)
        # Composition is another typed call at the existing Codex execution boundary.
        if not config.get('scene_plan'):
            report.update(status='WAITING_FOR_CODEX_SCENE',needs=['Estimate Object/Camera composition from actual images'])
            report['stages']['composition']={'status':'WAITING_FOR_CODEX_SCENE'};return finish()
        progress('SCENE_COMPOSITION','Apply estimated Camera/Object plan; protect q, measurements and calibration')
        report['stages']['composition']=apply_scene_plan(selected,config['scene_plan'],scene_state=state,image_ids=config.get('image_ids'),capture_layouts=config.get('capture_layouts',[]))
        supports=copy.deepcopy(config.get('fitting',{}).get('supports',{}))
        for name,row in selected.scene.get('geometry_constraints',{}).get('supports',{}).items():
            if row.get('support_anchor')and name in supports:
                original=supports[name]
                if isinstance(original,str):original={'support':original}
                if original.get('support_anchor')is not None and original['support_anchor']!=row['support_anchor']:raise ValueError('CONSTRAINT_CONFLICT: configured Support Anchor differs from Scene')
                supports[name]={**original,'support_anchor':row['support_anchor']}
        supported,physical=project_supports(selected.scene,supports,project.root,allow_incomplete=True)
        selected.save(supported);report['stages']['physical_constraints']=physical
        from .scene import support_relations
        nodes={o['id']:o for o in supported['objects']}
        missing=[name for name,row in support_relations(supported).items()if row['status']=='CONFIRMED'and not row.get('support_anchor')and nodes[row['support']]['collision']['type']not in('box','cylinder')]
        if missing:
            config['composition_feedback']={'validation_error':'Explicit Support Anchors required for declared contacts: '+', '.join(missing),'previous_plan':config.pop('scene_plan')}
            write(frozen,config);write(selected.root/'review-config.yaml',config);modeling_tasks(selected,config,{})
            report.update(status='WAITING_FOR_CODEX_SCENE',needs=[config['composition_feedback']['validation_error']])
            record(selected,'03_scene_composition','NEEDS_MORE_DATA',summary=report['needs'][0]);return finish()
        try:validate(render_scene(selected.scene),project.root,complete=True)
        except ValueError as error:
            report['needs']=[str(error)];record(selected,'03_first_scene','NEEDS_MORE_DATA',summary=str(error));return finish()
        progress('FITTING','Render actual multiview Scene for Codex comparison; no Depth solver')
        metrics=alignment_metrics(project,selected.scene,selected.root/'fitting/final',fitting)
        write(selected.root/'metrics.json',metrics)
        if refit_only:report['stages']['pair_comparison']={'views':len(metrics['images']),'scope':'Source Camera and measured-q RGB; no Depth or geometric solver','solver_executed':False,'needs':metrics['needs']}
        if not metrics['images']:
            report['needs']=metrics['needs']or['No usable photo/sensor cameras were returned'];record(selected,'03_first_scene','NEEDS_MORE_DATA',summary='No renderable observation views');return finish()
        rendered=current_images(selected,metrics=metrics)
        first=freeze_scene(selected,'03_first_scene',images=rendered,summary='First actual Simulator Scene before iterative edits',details={'engine':fitting.get('engine','mujoco'),'units':'metres for measured assets, estimated placement/cameras','physics_steps':0,'initial_collision':'See matching 05_physics stage; NOT_VERIFIED until query finishes'})
        report['stages']['first_scene']={'status':'RENDERED','path':str(first),'views':len(metrics['images'])}
        progress('PHYSICS','Actual initial collision query and possible passive dynamics; missing mass remains unverified')
        report['stages']['physics']=physics_probe(project,render_scene(selected.scene),selected.root/'physics')
        finish_iteration(selected)
        from .authoring import fitting_review
        review=fitting_review(selected)
        report['stages']['codex_review']={'status':review['status'],'wrist_observed':review['wrist_observed']}
        report['stages']['camera_quality']=metrics.get('camera_quality',{})
        physics_files=[p for p in(selected.root/'physics').rglob('*.json')if p.is_file()]
        stepped=report['stages']['physics'].get('mujoco',{}).get('steps',0)>0
        record(selected,'05_physics','COMPLETE'if stepped else'NOT_VERIFIED',files=physics_files,summary='Actual collision query / passive probe; unexecuted dynamics and unsupported checks remain explicit',details=report['stages']['physics'])
        report['stages']['fitting']={'status':'RENDERED_UNVERIFIED','solver_executed':False,'training_view_count':sum(i.get('split')=='train'for i in metrics['images']),'physical_verified':False}
        report['status']='DRAFT_READY';report['needs']=list(dict.fromkeys(config['scene_plan']['needs']+metrics.get('needs',[])))
        return finish()
    except InterruptedError:
        report['status']='STOPPED';finish_iteration(selected,status='STOPPED');record(selected,'06_final_comparison','STOPPED',summary='Stop retained completed stages and the first/best Scene');return finish()
    except Exception as error:
        report.update(status='FAILED',error=str(error))
        if 'CONSTRAINT_CONFLICT'in str(error):report['error_code']='CONSTRAINT_CONFLICT'
        finish_iteration(selected,status='FAILED');record(selected,'06_final_comparison','FAILED',summary=str(error));finish();raise
