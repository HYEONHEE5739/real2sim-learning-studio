"""Short-lived backend operations for Qt. No Qt, device activation or new config store."""
from pathlib import Path
import json
import sys


def stage_support(stage: str) -> dict:
    if stage in ('teleoperation','annotation','datagen','simulation_evaluation','train','offline_validation','hub_download','hub_upload'):
        return {'runnable':True,'reason':'지원 입력 검증 후 실행; 엔진 초기화는 실행 시 확인'}
    if stage in ('capture','precision_calibration','real_evaluation','real_sim'):return {'runnable':True,'reason':'오프라인 보존 자료/SDK 설정 검사만 실행합니다. 실제 장치/모터/카메라를 연결하지 않습니다.'}
    if stage=='source':return {'runnable':True,'reason':'Recorded Target Stream 또는 Live Leader 읽기 → Simulation Source. 실제 Follower 명령 없음.'}
    return {'runnable':False,'reason':'이 단계의 실행 Runner는 구현·검증되지 않았습니다. 직접 API 기능과 구분합니다.'}


def run_outcome(record: dict) -> dict:
    summary=record.get('attempt_summary') or {};status=record.get('status','unknown')
    rows=summary.get('history')
    successes=summary.get('successes',sum(r['status']=='success' for r in rows) if rows is not None else None)
    failures=summary.get('failures',sum(r['status'] in ('failure','ik_failure') for r in rows) if rows is not None else None)
    return {'existing_episodes':summary.get('existing_episodes'),'added_episodes':summary.get('added_episodes'),'successes':successes,'failures':failures,'attempts':summary.get('attempts'),'success_rate':summary.get('success_rate'),'worker_status':status,'worker_finished':status in ('completed','failed','cancelled'),
        'completed_episodes':record.get('completed_episodes'),
        'goal_reached':summary.get('target_reached'),'budget_exhausted':summary.get('budget_exhausted'),
        'needs_resume':summary.get('fresh_worker_required',False),'task_success':summary.get('latest',{}).get('success'),
        'error':record.get('error'),'summary':summary}


def prepared(path: str,modules: str) -> dict:
    from ..cli import prepare
    plan=prepare(path,task_modules=modules);support=stage_support(plan.stage)
    if not support['runnable']:return {**support,'state':'prepared','plan':plan.summary()}
    if plan.stage in ('capture','precision_calibration','real_evaluation','real_sim') and plan.effective_settings['execution'].get('mode')!='offline':
        from ..robot.live import open_inputs
        if not 1<=plan.effective_settings['execution'].get('max_frames',0)<=300:raise ValueError('명시 max_frames 1..300을 지정하세요')
        if 'calibration_profile'not in plan.resolved_inputs:raise ValueError('선택한 Precision Profile이 필요합니다')
        open_inputs(plan)  # Constructors only: no connection, camera start or motor writes.
        return {**support,'state':'runtime_ready','reason':'실물 읽기 전용 · Goal/Torque 쓰기 없음 · 실물 팔 구동 금지','plan':plan.summary(),'prepared_sha256':plan.sha256,'recipe_sha256':plan.recipe_sha256}
    if plan.stage=='teleoperation':
        if plan.effective_settings['execution']['mode']=='fake_all':
            from ..robot.teleoperation import fake_device
            from ..robot.calibration import load_profile
            for key,profile in (('device_profile','calibration_profile'),('leader_device_profile','leader_calibration_profile')):
                if key not in plan.input_documents or profile not in plan.resolved_inputs:raise ValueError('Fake full-axis Teleoperation needs explicit Leader and Follower profiles')
                from ..recipe import _plain
                fake_device(_plain(plan.input_documents[key]),load_profile(plan.resolved_inputs[profile]['path']))
        else:
            from ..robot.live import open_inputs
            open_inputs(plan)
    if plan.stage=='source':
        if 'source_dataset' in plan.resolved_inputs:
            from ..data.native import load_catalog
            from robot_learning_workbench.data.recording import validate_recording
            source=load_catalog(plan.resolved_inputs['source_dataset']['path']);validate_recording(source.execution.get('recording',{}))
            if source.execution.get('stage')!='source' or source.execution.get('engine')!=plan.engine or not source.episodes:raise ValueError('엔진이 일치하는 Source target stream이 필요합니다')
        else:
            from ..robot.configuration import create_leader
            device=create_leader(plan)
            if not device.read_only:raise ValueError('Live Leader must preserve torque and never send motor commands')
    if plan.stage=='datagen':
        from importlib import import_module
        import_module('robot_learning_workbench.engines.'+plan.engine+'.datagen').load_inputs(plan)
        placements=[b.name for b in plan.function_bindings.values() if b.kind=='placement']
        if any(n not in ('placement.fixed_xy','placement.random_workspace') for n in placements) or len(set(placements))!=1:
            raise ValueError('UI DataGen supports an all-Fixed or all-Random batch')
    elif plan.stage=='annotation':
        from ..data.native import load_catalog
        from robot_learning_workbench.data.recording import validate_recording
        catalog=load_catalog(plan.resolved_inputs['dataset']['path']);validate_recording(catalog.execution.get('recording',{}))
        from robot_learning_workbench.data.recording import validate_source_ranges
        validate_source_ranges(catalog)
        if catalog.execution.get('stage')!='source' or catalog.execution.get('engine')!=plan.engine:raise ValueError('엔진이 같은 원본 Source가 필요합니다')
        if plan.engine=='isaac':
            from ..engines.isaac.annotation import validate_source
            validate_source(catalog)
    elif plan.stage=='train':
        from ..learning.train import training_command
        training_command(plan)
    elif plan.stage=='simulation_evaluation':
        if any(b.kind=='placement' and b.name not in ('placement.fixed_xy','placement.random_workspace') for b in plan.function_bindings.values()):raise ValueError('Evaluation은 Fixed 또는 Workspace Random 배치를 지원합니다')
        from ..learning.policy import checkpoint_record
        path=Path(plan.resolved_inputs['policy']['path'])
        if (path/'workbench-checkpoint.json').is_file():checkpoint_record(path)
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies import factory
        if plan.input_documents['policy_config'].get('type') not in PreTrainedConfig.get_known_choices():raise ValueError('설치된 LeRobot에 등록되지 않은 Policy입니다')
    return {**support,'state':'runtime_ready','plan':plan.summary(),'prepared_sha256':plan.sha256,'recipe_sha256':plan.recipe_sha256}


def execute(request: dict) -> dict:
    """Explicit existing function calls, not an extensible operation registry."""
    op=request['operation'];args=request.get('arguments',{})
    if op=='training_config':
        from lerobot.policies.factory import make_policy_config
        from lerobot.configs.train import TrainPipelineConfig
        from lerobot.configs.default import DatasetConfig
        cfg=TrainPipelineConfig(dataset=DatasetConfig(repo_id='local/dataset',root=Path(args['dataset'])),policy=make_policy_config(args['policy_type']),output_dir=Path(args['output']),eval_freq=0)
        cfg.policy.push_to_hub=False
        if hasattr(cfg.policy,'pretrained_backbone_weights'):cfg.policy.pretrained_backbone_weights=None
        return {'config':cfg.to_dict()}
    if op=='policy_catalog':
        from ..learning.policy import policy_catalog
        return {'policies':policy_catalog()}
    if op=='hub_resolve':
        from ..learning.hub import resolve
        return resolve(**args)
    if op=='precision_revision':
        from ..robot.calibration import review_revision
        return review_revision(**args)
    if op=='hub_create':
        from ..learning.hub import create_repository
        return create_repository(**args)
    if op=='prepare':return prepared(**args)
    if op=='scene':
        from scene_contract.package import load_scene
        from dataclasses import asdict
        scene=load_scene(Path(args['path']))
        return {'path':str(Path(args['path']).resolve()),'identity':asdict(scene.identity),'objects':list(scene.scene['objects']),
            'engines':list(scene.scene['engines']),'calibration_records':len(scene.calibration['records']),
            'robot_model':scene.scene['robot'].get('joint_order'),'valid':True}
    if op=='start':
        from ..run import start,StartRequest
        from ..recipe import read_recipe
        from ..data.native import file_sha256
        doc=read_recipe(args['path'])
        if doc.sha256!=args['expected_recipe_sha256']:raise ValueError('검사 후 Recipe가 변경되었습니다. 다시 검사하세요.')
        modules=Path(args['modules']);ready=prepared(args['path'],str(modules))
        if ready['prepared_sha256']!=args['expected_prepared_sha256']:raise ValueError('검사 후 입력이 변경되었습니다. 다시 검사하세요.')
        if not ready['runnable']:raise ValueError(ready['reason'])
        output=(doc.base_dir/doc.spec.output['directory']).resolve()
        needs_tasks=bool(doc.spec.objects or doc.spec.functions)
        handle=start(StartRequest(args['request_id'],doc.path,doc.sha256,doc.spec.stage,output,modules if needs_tasks else None,file_sha256(modules) if needs_tasks else None,ready['prepared_sha256']))
        return {'run_id':handle.run_id,'request_id':handle.request_id,'run_dir':str(handle.run_dir),'output_path':str(output)}
    if op=='catalog':
        from ..data.curation import inspect_dataset
        from ..data.native import load_catalog
        catalog=load_catalog(args['path'])
        return {'path':str(catalog.root),'kind':catalog.kind,'inspection':inspect_dataset(catalog),
                'active_objects':catalog.execution.get('active_objects',[]),'engine':catalog.execution.get('engine')}
    if op=='frame':
        from ..data.curation import review_frame
        from ..data.native import load_catalog
        result=review_frame(args['source'],args['selection_id'],args['frame']);result['values']={k:v.tolist() for k,v in result['values'].items()};folder=Path(args['preview_directory']).resolve()
        catalog=load_catalog(args['source'])
        if any(folder.is_relative_to(ep.source_root) for ep in catalog.episodes):raise ValueError('Preview must be outside immutable inputs')
        folder.mkdir(parents=True,exist_ok=True);images={}
        for camera,rgb in result.pop('rgb').items():
            # Only this single reviewed frame; no MP4 decode in the Qt thread.
            small=rgb[::2,::2].copy();h,w=small.shape[:2];target=folder/(camera+'.ppm')
            target.write_bytes(f'P6\n{w} {h}\n255\n'.encode()+small.tobytes());images[camera]=str(target)
        return {**result,'images':images}
    if op in ('distribution','compare','split','save_curation','materialize','merge','horizontal'):
        from ..data import curation
        if op=='distribution':return curation.distribution(**args)
        if op=='compare':return curation.compare_distributions(**args)
        if op=='split':return curation.split_dataset(**args)
        if op=='save_curation':
            curation.save_curation(**args);return {'path':str(Path(args['path']).resolve())}
        if op=='horizontal':
            from real2sim_builder.project import Project,validate_horizontal_layout
            scene=Project(args.pop('project'),read_only=True).scene
            return validate_horizontal_layout(scene,**args)
        from ..data import lerobot
        output=lerobot.merge(**args) if op=='merge' else lerobot.materialize(**args)
        return {'path':str(output)}
    raise ValueError('지원하지 않는 UI operation: '+op)


def main():
    import contextlib
    from ..data.native import plain
    try:
        request=json.loads(sys.stdin.read())
        with contextlib.redirect_stdout(sys.stderr):result=execute(request)
        print(json.dumps({'ok':True,'result':plain(result)},ensure_ascii=False));return 0
    except Exception as error:
        from ..recipe import _plain
        print(json.dumps({'ok':False,'error':{'code':getattr(error,'code','INPUT_INVALID'),'message':str(error),
            'issues':_plain(getattr(error,'issues',()))}},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
