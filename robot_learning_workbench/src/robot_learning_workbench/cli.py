"""CLI for the same saved-file APIs used by Workbench. No shell command Recipes."""
import argparse
import contextlib
import json
from pathlib import Path
import sys

from .recipe import read_recipe,prepare_recipe,RecipeError,_plain


def prepare(path,*,stage=None,task_modules=None):
    doc=read_recipe(path,expected_stage=stage);tasks=None
    if doc.spec.objects or doc.spec.functions:
        if task_modules is None:raise RecipeError('TASK_MODULES_INVALID','task_modules','explicit task_modules.yaml required')
        from .tasks.registry import read_module_names,load_registry
        tasks=load_registry(read_module_names(Path(task_modules)))
    return prepare_recipe(doc,scene=None,tasks=tasks,inputs={})


def main(argv=None):
    parser=argparse.ArgumentParser(prog='robot-learning-workbench')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('validate','prepare'):
        p=commands.add_parser(name);p.add_argument('recipe');p.add_argument('--stage');p.add_argument('--task-modules')
    p=commands.add_parser('run');p.add_argument('recipe');p.add_argument('--stage');p.add_argument('--task-modules');p.add_argument('--request-id',required=True);p.add_argument('--expected-sha256');p.add_argument('--expected-prepared-sha256');p.add_argument('--run-root')
    p=commands.add_parser('status');p.add_argument('run_dir')
    p=commands.add_parser('events');p.add_argument('run_dir');p.add_argument('--after-seq',type=int,default=0);p.add_argument('--limit',type=int,default=200)
    p=commands.add_parser('command');p.add_argument('run_dir');p.add_argument('--id',required=True);p.add_argument('--kind',required=True);p.add_argument('--payload',default='{}');p.add_argument('--episode-id');p.add_argument('--env-index',type=int)
    p=commands.add_parser('worker',help=argparse.SUPPRESS);p.add_argument('run_dir')
    args=parser.parse_args(argv)
    try:
        if args.command=='worker':
            from .run import load_worker_request,execute
            result=execute(load_worker_request(Path(args.run_dir)))
            return 0 if result.status in ('completed','cancelled') else 1
        if args.command in ('run','status','events','command'):
            from . import run
            if args.command=='run':
                doc=read_recipe(args.recipe,expected_stage=args.stage);modules=Path(args.task_modules).resolve() if args.task_modules else None
                request=run.StartRequest(args.request_id,doc.path,args.expected_sha256 or doc.sha256,doc.spec.stage,(doc.base_dir/doc.spec.output['directory']).resolve(),modules,run._sha(modules.read_bytes()) if modules else None,args.expected_prepared_sha256)
                result=_plain(run.start(request,run_root=args.run_root))
            elif args.command=='status':result=_plain(run.read_status(args.run_dir))
            elif args.command=='events':result=_plain(run.read_events(args.run_dir,args.after_seq,args.limit))
            else:
                root=Path(args.run_dir).resolve();record=run._read(root/'run.json');handle=run.RunHandle(root.name,record['request_id'],root)
                command={'command_id':args.id,'kind':args.kind,'payload':run._decode(args.payload)}
                for key in ('episode_id','env_index'):
                    if getattr(args,key) is not None:command[key]=getattr(args,key)
                result=_plain(run.send_command(handle,command))
            print(json.dumps(result,ensure_ascii=False));return 0
        if args.command=='validate':
            doc=read_recipe(args.recipe,expected_stage=args.stage);result={'recipe_sha256':doc.sha256,'stage':doc.spec.stage,'status':'syntax_valid'}
        else:
            with contextlib.redirect_stdout(sys.stderr):plan=prepare(args.recipe,stage=args.stage,task_modules=args.task_modules)
            result=plan.summary();result['status']='prepared';result['prepared_sha256']=plan.sha256
        print(json.dumps(result,ensure_ascii=False));return 0
    except Exception as exc:
        error={'code':getattr(exc,'code','INPUT_INVALID'),'message':str(exc),'issues':_plain(getattr(exc,'issues',())),'effect':getattr(exc,'effect','not_started')}
        print(json.dumps(error,ensure_ascii=False),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
