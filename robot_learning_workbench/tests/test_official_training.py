"""L01 config rejection before effects; actual smoke lives in recorded evidence."""
import copy
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]

def config(output):
    return dict(dataset={'repo_id':'workbench/native','root':str(ROOT/'docs/evidence/l03-lerobot/outputs-final/train'),'video_backend':'pyav','use_imagenet_stats':False},output_dir=str(output),policy={'type':'act','device':'cuda','push_to_hub':False,'pretrained_backbone_weights':None},steps=2,batch_size=1,num_workers=0,eval_freq=0,log_freq=1,save_freq=1,wandb={'enable':False})


def test_training_plan_is_official_and_refuses_side_effecting_options(tmp_path):
    from robot_learning_workbench.learning.train import validate_config
    cfg=config(tmp_path/'out');validate_config(cfg,dataset=Path(cfg['dataset']['root']),output=tmp_path/'out',mode='scratch')
    for key,value in [('push_to_hub',True),('pretrained_backbone_weights','ResNet18_Weights.IMAGENET1K_V1'),('type','smolvla')]:
        bad=copy.deepcopy(cfg);bad['policy'][key]=value
        with pytest.raises(ValueError):validate_config(bad,dataset=Path(cfg['dataset']['root']),output=tmp_path/'out',mode='scratch')
    bad=copy.deepcopy(cfg);bad['dataset']['episodes']=[0]
    with pytest.raises(ValueError):validate_config(bad,dataset=Path(cfg['dataset']['root']),output=tmp_path/'out',mode='scratch')
    bad=copy.deepcopy(cfg);bad['log_freq']=100
    with pytest.raises(ValueError):validate_config(bad,dataset=Path(cfg['dataset']['root']),output=tmp_path/'out',mode='scratch')


def test_prepare_training_checks_official_metadata_without_rehashing_shared_video(tmp_path,monkeypatch):
    import json,yaml
    from robot_learning_workbench.data import native
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe,verify_prepared_inputs
    cfg=config(tmp_path/'out');c=tmp_path/'train.json';c.write_text(json.dumps(cfg));p=tmp_path/'r.yaml';p.write_text(yaml.safe_dump(dict(schema_version=1,stage='train',inputs={'dataset':cfg['dataset']['root'],'training_config':str(c)},execution={'mode':'scratch'},output={'directory':str(tmp_path/'out')})))
    original=native.file_sha256;seen=[]
    def capture(path):seen.append(str(path));return original(path)
    monkeypatch.setattr(native,'file_sha256',capture)
    plan=prepare_recipe(read_recipe(p));verify_prepared_inputs(plan)
    assert not any(name.endswith('.mp4') for name in seen)
    assert plan.resolved_inputs['dataset']['kind']=='lerobot_dataset'


def test_cancel_ignoring_child_gets_bounded_kill(monkeypatch):
    import subprocess
    from robot_learning_workbench.learning.train import stop_child
    import robot_learning_workbench.learning.train as module
    calls=[]
    class Child:
        pid=123
        def poll(self):return None
        def wait(self,timeout=None):
            calls.append(timeout)
            if len(calls)==1:raise subprocess.TimeoutExpired('owned child',timeout)
            return -9
    monkeypatch.setattr(module.os,'killpg',lambda *args:calls.append(('signal',args[1])))
    # Track wait calls separately from signal tracing.
    class Child2(Child):
        count=0
        def wait(self,timeout=None):
            self.count+=1
            if self.count==1:raise subprocess.TimeoutExpired('owned child',timeout)
            return -9
    assert stop_child(Child2())==-9
    assert calls[0][1]==module.signal.SIGTERM and calls[-1][1]==module.signal.SIGKILL


def test_scratch_official_config_is_frozen_before_subprocess(tmp_path):
    from robot_learning_workbench.learning.train import freeze_inputs
    from types import SimpleNamespace
    from robot_learning_workbench.data.native import read_json
    import json
    cfg=config(tmp_path/'out');path=tmp_path/'mutable.json';path.write_text(json.dumps(cfg))
    plan=SimpleNamespace(output_path=tmp_path/'out',effective_settings={'execution':{'mode':'scratch'}},resolved_inputs={})
    argv=freeze_inputs(plan,['python','--config_path='+str(path)],cfg)
    snapshot=Path(argv[-1].split('=',1)[1]);path.write_text('{}')
    assert snapshot!=path and read_json(snapshot)==cfg


@pytest.mark.parametrize('nonfinite',[True,False])
def test_final_log_preserves_closed_checkpoint_and_frozen_config(tmp_path,monkeypatch,nonfinite):
    """Child can exit between polls; its final log must not hide earlier output."""
    import json,os,yaml
    from robot_learning_workbench.learning import train as module
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    source=ROOT/'docs/evidence/learning-bundle/runs/act-second/checkpoints/000001'
    cfg=json.loads((source/'workbench-checkpoint.json').read_text())['config'];cfg['output_dir']=str(tmp_path/'out');cfg['steps']=2 if nonfinite else 1
    config_file=tmp_path/'train.json';config_file.write_text(json.dumps(cfg))
    recipe=tmp_path/'r.yaml';recipe.write_text(yaml.safe_dump(dict(schema_version=1,stage='train',inputs={'dataset':cfg['dataset']['root'],'training_config':str(config_file)},execution={'mode':'scratch'},output={'directory':cfg['output_dir']})))
    plan=prepare_recipe(read_recipe(recipe))
    class ExitedChild:
        pid=123
        def __init__(self,*args,stdout,**kwargs):
            target=plan.output_path/'checkpoints/000001'
            for p in source.rglob('*'):
                if not p.is_file() or p.name=='workbench-checkpoint.json':continue
                dest=target/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True)
                if p.name=='train_config.json':
                    doc=json.loads(p.read_text());doc.update(output_dir=cfg['output_dir'],steps=cfg['steps']);dest.write_text(json.dumps(doc))
                else:os.link(p,dest)
            (target.parent/'last').symlink_to('000001')
            stdout.write(b'step:1 loss:1.0\n'+(b'step:2 loss:nan\n' if nonfinite else b''))
            config_file.write_text('{}')  # Next run's editable config, not this run's frozen bytes.
        def poll(self):return int(nonfinite)
        def wait(self):return int(nonfinite)
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.configs.train import TrainPipelineConfig
    monkeypatch.setattr(module.subprocess,'Popen',ExitedChild)
    if nonfinite:
        with pytest.raises(ValueError,match='Nonfinite'):module.train(plan,events=lambda row:None,commands=lambda:())
    else:assert module.train(plan,events=lambda row:None,commands=lambda:()).status=='completed'
    assert (plan.output_path/'checkpoints/000001/workbench-checkpoint.json').is_file()


def test_log_parsing_and_nonfinite_step_are_separate():
    from robot_learning_workbench.learning.train import parse_metrics,nonfinite_step
    assert parse_metrics('step:1 loss:1e\nstep:2 loss:2.0')==[{'step':2,'loss':2.0}]
    assert nonfinite_step('step:1,003 loss:nan\nstep:1,002 loss:inf')==1002


def test_known_bad_control_meaning_rejected_before_official_training(tmp_path):
    import json,shutil,os,yaml
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.learning.train import training_command
    cfg=config(tmp_path/'out');src=Path(cfg['dataset']['root']);dst=tmp_path/'data'
    shutil.copytree(src,dst,copy_function=os.link)
    p=dst/'workbench.json';doc=json.loads(p.read_text());doc['control_contract']['joint_order'].reverse();p.unlink();p.write_text(json.dumps(doc))
    cfg['dataset']['root']=str(dst);c=tmp_path/'train.json';c.write_text(json.dumps(cfg));r=tmp_path/'r.yaml'
    r.write_text(yaml.safe_dump(dict(schema_version=1,stage='train',inputs={'dataset':str(dst),'training_config':str(c)},execution={'mode':'scratch'},output={'directory':str(tmp_path/'out')})))
    with pytest.raises(ValueError,match='meaning'):training_command(prepare_recipe(read_recipe(r)))
    assert not (tmp_path/'out').exists()
