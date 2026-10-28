"""Single intentional CLI for project creation, evidence, reconstruction and export."""
import argparse
import json
from pathlib import Path
from .project import Project,read,write


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('import-capture');p.add_argument('project');p.add_argument('session')
    p=sub.add_parser('import-snapshots');p.add_argument('project');p.add_argument('dataset');p.add_argument('--validation',nargs='*',default=[]);p.add_argument('--scene-state')
    p=sub.add_parser('import-paired');p.add_argument('project');p.add_argument('dataset');p.add_argument('--validation',nargs='*',default=[]);p.add_argument('--scene-state');p.add_argument('--include-flagged-reason');p.add_argument('--reconciliation')
    p=sub.add_parser('clone');p.add_argument('source');p.add_argument('destination')
    sub.add_parser('capabilities')
    for name in ('diagnose','coverage','analyze-objects'):
        p=sub.add_parser(name);p.add_argument('project');p.add_argument('--candidate');p.add_argument('--engine',choices=['blender','mujoco'],default='mujoco')
    p=sub.add_parser('inspect');p.add_argument('project')
    p=sub.add_parser('scan');p.add_argument('project');p.add_argument('action',choices=['import','inspect','segment','initialize','register','preview','constrain']);p.add_argument('--path');p.add_argument('--scan-id');p.add_argument('--candidate');p.add_argument('--config');p.add_argument('--engine',choices=['blender','mujoco'],default='blender');p.add_argument('--renderer',choices=['software-egl','egl','osmesa'],default='software-egl')
    p=sub.add_parser('candidate');p.add_argument('project');p.add_argument('action',choices=['create','edit','asset','render','evaluate','promote','reject','blender-build','blender-author','blender-sync','fit']);p.add_argument('name');p.add_argument('--target');p.add_argument('--options');p.add_argument('--edits');p.add_argument('--path');p.add_argument('--kind',choices=['visual','collision','textures'],default='visual');p.add_argument('--engine',choices=['blender','mujoco'],default='blender');p.add_argument('--renderer',choices=['software-egl','egl','osmesa'],default='software-egl');p.add_argument('--validation',action='store_true');p.add_argument('--target-object');p.add_argument('--allow',default='pose')
    p=sub.add_parser('rollback');p.add_argument('project')
    p=sub.add_parser('validate');p.add_argument('project');p.add_argument('--engine',choices=['blender','mujoco'],default='blender');p.add_argument('--renderer',choices=['software-egl','egl','osmesa'],default='software-egl')
    p=sub.add_parser('new');p.add_argument('name');p.add_argument('--projects',default='projects')
    p=sub.add_parser('add');p.add_argument('project');p.add_argument('paths',nargs='+');p.add_argument('--kind',choices=['image','reference','video','measurements','calibration','scene','robot','brief'],default='image');p.add_argument('--camera',default='side');p.add_argument('--split',choices=['train','validation'],default='train');p.add_argument('--joints');p.add_argument('--base')
    p=sub.add_parser('import-reference');p.add_argument('project');p.add_argument('--workspace',required=True);p.add_argument('--capture',required=True)
    p=sub.add_parser('run');p.add_argument('project');p.add_argument('--renderer',choices=['software-egl','egl','osmesa'],default='software-egl');p.add_argument('--max-iterations',type=int,default=8);p.add_argument('--mae',type=float,default=.12);p.add_argument('--reprojection-px',type=float,default=5);p.add_argument('--silhouette-iou',type=float,default=.8)
    p=sub.add_parser('control');p.add_argument('project');p.add_argument('action',choices=['pause','resume','stop'])
    p=sub.add_parser('status');p.add_argument('project')
    p=sub.add_parser('export');p.add_argument('project');p.add_argument('--destination',required=True);p.add_argument('--calibration');p.add_argument('--required-file',action='append',default=[]);p.add_argument('--allow-unvalidated',action='store_true');p.add_argument('--candidate')
    p=sub.add_parser('verify');p.add_argument('package')
    p=sub.add_parser('ui');p.add_argument('--projects',default='projects')
    args=parser.parse_args(argv)
    if args.command=='capabilities':
        from .rendering import capability
        import importlib.util
        print(json.dumps({'scan_input':'embedded GLB 2 with optional existing trimesh','scan_segmentation':'plane removal + voxel clustering proposals or explicit object ROI','unknown_camera_fit':['bootstrap','intrinsics','camera','distortion (k1)','quality'],'precision_mapping':'portable so101.precision-joint-mapping/1 hash/order/URDF-frame checks; manual status retained','capture_schema':['real2sim.snapshot/1','real2sim.capture/1 (legacy)'],'per_observation_fk':['urdf','scalar_joint_mjcf'],'multipose_fit':'weighted_soft_l1_landmarks','native_scene_contract':'schema_version=1; immutable new destination','articulated_action_replay':False,'workflow_schema':'so101.scene-workflow/1','workflow_authoring':'candidate edit --edits (set_workflow)','workflow_recipe':'SO101 pick/place only; metadata validation is not executed-task validation','blender':capability(), **{n:importlib.util.find_spec(n) is not None for n in ('mujoco','pxr','trimesh')}},indent=2));return 0
    if args.command=='clone':
        from .project import clone_project
        print(clone_project(args.source,args.destination).root);return 0
    if args.command=='new':print(Project.create(args.projects,args.name).root);return 0
    if args.command=='verify':
        from .export import verify_package
        from dataclasses import asdict
        package=verify_package(args.package)
        print(json.dumps({'identity':asdict(package.identity),'files':len(package.files)},indent=2));return 0
    if args.command=='ui':
        from .ui import launch
        launch(Path(args.projects));return
    project=Project(args.project)
    if args.command=='scan':
        from .reconstruction import import_scan,inspect_file,initialize,registration,preview,segment,constrain
        if args.action=='import':result=import_scan(project,args.path)
        elif args.action=='inspect':
            scan=next(r for r in project.evidence.get('scans',[]) if r['id']==args.scan_id)
            result=inspect_file(project.root/scan['path'])
        elif args.action=='register':
            from .project import exclusive
            with exclusive(project):
                result=registration(read(args.config));write(project.root/'working/scans/registration.json',result)
        elif args.action=='preview':result=preview(project,args.scan_id,args.engine,args.renderer,args.candidate)
        elif args.action=='segment':result=segment(project,args.scan_id,args.config)
        elif args.action=='constrain':
            from .project import Candidate
            result=constrain(Candidate(project,args.candidate),args.config)
        else:
            from .project import Candidate
            result=initialize(Candidate(project,args.candidate),args.scan_id,args.config)
        print(json.dumps(result,indent=2));return 2 if result.get('status') in ('NEEDS_MORE_DATA','CONFLICT') else 0
    if args.command=='import-capture':
        from .project import import_session
        from .project import exclusive
        with exclusive(project):
            if read(Path(args.session)/'capture_manifest.yaml').get('schema')=='real2sim.snapshot/1':
                from .project import import_snapshots
                result=import_snapshots(project,args.session)
            else:result=import_session(project,args.session)
        print(json.dumps(result,indent=2));return 0
    if args.command in ('import-snapshots','import-paired'):
        from .project import import_snapshots, import_paired
        from .project import exclusive
        with exclusive(project):
            if args.command=='import-paired':result=import_paired(project,args.dataset,args.validation,args.scene_state,reconciliation=args.reconciliation,include_flagged_reason=args.include_flagged_reason)
            else:result=import_snapshots(project,args.dataset,args.validation,args.scene_state)
        print(json.dumps(result,indent=2));return 0
    if args.command in ('diagnose','coverage','analyze-objects'):
        from .reconstruction import reports,diagnose,coverage
        report=reports(project,args.candidate,args.engine)
        result=diagnose(report) if args.command=='diagnose' else coverage(report) if args.command=='coverage' else {'status':'OBJECT_METRICS' if report else 'NEEDS_MORE_DATA','images':[{k:v for k,v in row.items() if k in ('image','observation','camera','split','objects')} for row in (report or {}).get('images',[])],'input_signature':(report or {}).get('input_signature')}
        print(json.dumps(result,indent=2));return 0
    if args.command=='inspect':
        print(json.dumps({'project':project.info,'state':project.state,'evidence':project.evidence,
            'scene':project.scene if (project.root/'working/current_scene.yaml').exists() else None,
            'candidates':sorted(p.parent.name for p in (project.root/'scratch/agent').glob('*/candidate.json'))},indent=2));return 0
    if args.command=='rollback':
        from .project import rollback
        print(json.dumps(rollback(project)));return 0
    if args.command=='validate':
        from .reconstruction import evaluate_project
        result=evaluate_project(project,args.engine,args.renderer);print(json.dumps(result,indent=2));return 0 if result['passed'] else 2
    if args.command=='candidate':
        from .project import Candidate
        from .rendering import workspace,Unavailable
        try:
            c=Candidate.create(project,args.name,args.target_object,args.allow.split(',')) if args.action=='create' else Candidate(project,args.name)
            if args.action=='create':result=c.info
            elif args.action=='edit':result=c.edit(read(args.edits))
            elif args.action=='fit':result=c.fit(args.target,read(args.options) if args.options else None)
            elif args.action=='asset':result=c.asset(args.path,args.kind)
            elif args.action in ('render','evaluate'):result=c.evaluate(args.engine,args.renderer,args.validation,args.action=='render')
            elif args.action=='promote':result=c.promote()
            elif args.action=='reject':result=c.reject()
            else:result=workspace(c,{'blender-build':'build','blender-author':'author','blender-sync':'sync'}[args.action],args.path)
            print(json.dumps(result,indent=2));return 2 if result.get('status') in ('NEEDS_MORE_DATA','REJECTED') and args.action=='fit' else 0
        except Unavailable as exc:
            print(json.dumps({'status':'UNAVAILABLE','engine':'blender','reason':str(exc)}));return 3
    if args.command in ('add','import-reference') and (project.root/'working/run.lock').exists():
        raise RuntimeError('Stop/resume the reconstruction worker before changing this project input')
    if args.command=='add':
        from . import project as evidence
        for path in args.paths:
            if args.kind=='brief':evidence.add_brief(project,path)
            elif args.kind in ('image','reference'):evidence.add_image(project,path,args.camera,args.split,context_only=args.kind=='reference')
            elif args.kind=='video':evidence.add_video(project,path,args.camera,args.split)
            elif args.kind=='scene':evidence.import_scene(project,path)
            elif args.kind in ('calibration','measurements'):evidence.import_metadata(project,path,args.kind)
            elif args.kind=='robot':evidence.import_robot(project,path,read(args.joints) if args.joints else {},read(args.base) if args.base else None)
    elif args.command=='import-reference':
        from .project import import_reference
        import_reference(project,args.workspace,args.capture)
    elif args.command=='control':project.control(args.action)
    elif args.command=='status':print(json.dumps(project.state,indent=2))
    elif args.command=='run':
        from .reconstruction import run
        state=run(project,args.renderer,args.max_iterations,{'mae':args.mae,'reprojection_px':args.reprojection_px,'silhouette_iou':args.silhouette_iou})
        print(json.dumps(state,indent=2));return 1 if state['status']=='FAILED' else 0
    elif args.command=='export':
        from .export import export_revision
        from dataclasses import asdict
        identity=export_revision(project,destination=Path(args.destination),candidate=args.candidate,
            calibration=read(args.calibration) if args.calibration else None,
            required_files=tuple(Path(p) for p in args.required_file),allow_unvalidated=args.allow_unvalidated)
        if not project.read_only:project.update(export_destination=str(Path(args.destination).resolve()),export_identity=asdict(identity))
        print(json.dumps({'identity':asdict(identity),'destination':str(Path(args.destination).resolve())},indent=2))

    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        from .rendering import Unavailable
        print(json.dumps({'status':'UNAVAILABLE' if isinstance(exc,Unavailable) else 'FAILED','error':type(exc).__name__,'reason':str(exc)}))
        raise SystemExit(3 if isinstance(exc,Unavailable) else 1)
