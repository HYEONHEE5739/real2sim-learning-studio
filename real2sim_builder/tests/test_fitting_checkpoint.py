import pytest
from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import write,read
from real2sim_builder.automation import retain_fitting,restore_fitting


def metrics(p,c,error):
    from PIL import Image
    folder=c.root/'fitting/final/previews/w';folder.mkdir(parents=True,exist_ok=True)
    for kind in ('real','sim','side_by_side','overlay','difference'):
        if not(folder/(kind+'.png')).exists():Image.new('RGB',(8,8),'white').save(folder/(kind+'.png'))
    return {'input_signature':p.signature(c.scene),'images':[{'image_id':'w','camera_type':'wrist','split':'train','q_measured':[0]*6,'mae':error,'rmse':error,'edge_iou':1-error,'objects':[]}]}


def test_checkpoint_restores_scene_config_metrics_and_preview(tmp_path):
    p=Project.create(tmp_path,'best');c=Candidate.create(p,'draft')
    cfg=c.root/'reconstruction-config.yaml';write(cfg,{'round':1})
    scene=c.scene;scene['reconstruction_configuration']={'path':cfg.relative_to(p.root).as_posix()};c.save(scene)
    preview=c.root/'fitting/final/previews/w/real.png';preview.parent.mkdir(parents=True);preview.write_bytes(b'first')
    write(c.root/'metrics.json',metrics(p,c,.1))
    best=retain_fitting(c,None,{'status':'NOT_VERIFIED'})
    write(cfg,{'round':2});preview.write_bytes(b'second');write(c.root/'metrics.json',metrics(p,c,.3))
    assert retain_fitting(c,best,{'status':'NOT_VERIFIED'})==best
    restore_fitting(c,best)
    assert read(cfg)=={'round':1} and preview.read_bytes()==b'first'
    assert read(c.root/'metrics.json')['input_signature']==p.signature(c.scene)


def test_incomparable_views_and_corrupt_checkpoint_are_not_accepted(tmp_path):
    p=Project.create(tmp_path,'compare');c=Candidate.create(p,'draft')
    write(c.root/'metrics.json',metrics(p,c,.2));best=retain_fitting(c,None,{})
    newer=metrics(p,c,.1);newer['images'][0]['q_measured'][0]=1
    write(c.root/'metrics.json',newer)
    assert retain_fitting(c,best,{})==best
    (best/'scene.yaml').write_text('tampered')
    with pytest.raises(ValueError,match='checkpoint'):restore_fitting(c,best)


@pytest.mark.parametrize('exit_kind',['budget','failure','stop','complete'])
def test_pipeline_restores_best_after_later_model_round(tmp_path,monkeypatch,exit_kind):
    from real2sim_builder import automation,authoring
    p=Project.create(tmp_path,exit_kind);c=Candidate.create(p,'draft');rounds=[0]
    def stage(project,**kwargs):
        rounds[0]+=1
        scene=c.scene;scene['test_round']=rounds[0];c.save(scene)
        if rounds[0]==2 and exit_kind=='failure':raise RuntimeError('child failed')
        if rounds[0]==2 and exit_kind=='stop':return {'status':'STOPPED'}
        write(c.root/'metrics.json',metrics(p,c,.1 if rounds[0]==1 else .4))
        return {'status':'NOT_VERIFIED','stages':{'codex_review':{'status':'WAITING_FOR_CODEX_REVIEW'}}}
    monkeypatch.setattr(automation,'_reconstruct',stage)
    monkeypatch.setattr(automation,'modeling_tasks',lambda *a:None)
    monkeypatch.setattr(authoring,'run_codex_modeling',lambda *a,**k:{'decision':{'action':'complete'if rounds[0]==2 else'numeric','objects':[],'evidence':['w'],'reason':'refine','scene_plan':{'object_poses':[],'cameras':[],'needs':[]}if rounds[0]==1 else None}})
    if exit_kind=='failure':
        with pytest.raises(RuntimeError):automation.reconstruct(p,candidate='draft',config={'objects':{}},run_modeling=True,max_review_calls=1)
    else:
        result=automation.reconstruct(p,candidate='draft',config={'objects':{}},run_modeling=True,max_review_calls=2 if exit_kind=='complete'else 1)
        assert result['restored_best']
        assert result['status']==('STOPPED' if exit_kind=='stop' else 'BEST_RESTORED_UNVERIFIED'if exit_kind=='complete'else 'REVIEW_BUDGET_EXHAUSTED')
    assert c.scene['test_round']==1
    assert read(c.root/'metrics.json')['input_signature']==p.signature(c.scene)


def test_improved_phone_cannot_replace_regressed_wrist(tmp_path):
    p=Project.create(tmp_path,'roles');c=Candidate.create(p,'draft')
    report=metrics(p,c,.2);phone=dict(report['images'][0],image_id='phone',camera_type='external',q_measured=None,mae=.9,rmse=.9,edge_iou=.1)
    report['images'].append(phone);write(c.root/'metrics.json',report)
    best=retain_fitting(c,None,{})
    report['images'][0]['mae']=.21
    phone.update(mae=.01,rmse=.01,edge_iou=.99)
    write(c.root/'metrics.json',report)
    assert retain_fitting(c,best,{})==best
    report['images'][0]['mae']=.1;write(c.root/'metrics.json',report)
    assert retain_fitting(c,best,{})!=best


def test_review_quota_resume_uses_validated_fitting_without_repeating_it(tmp_path,monkeypatch):
    from real2sim_builder import automation,authoring,codex_cli
    p=Project.create(tmp_path,'review resume');c=Candidate.create(p,'same')
    config={'authoring_mode':'codex','objects':{},'fitting':{'optimize_appearance':True,'optimize_lighting':True}}
    write(c.root/'reconstruction-config.yaml',config)
    write(c.root/'metrics.json',metrics(p,c,.1))
    ready={'status':'NOT_VERIFIED','stages':{'codex_review':{'status':'WAITING_FOR_CODEX_REVIEW'}}}
    best=retain_fitting(c,None,ready)
    write(c.root/'reconstruction.json',{**ready,'status':'FAILED','failed_stage':'CODEX_REVIEW','error_code':'USAGE_LIMIT',
        'selected_checkpoint':str(best),'modeling_calls':1,'review_calls':0})
    monkeypatch.setattr(automation,'_reconstruct',lambda *a,**k:pytest.fail('completed fitting repeated'))
    monkeypatch.setattr(automation,'modeling_tasks',lambda *a:None)
    monkeypatch.setattr(authoring,'run_codex_modeling',lambda *a,**k:{'decision':{'action':'complete','objects':[],'evidence':['w'],'reason':'ok'}})
    result=automation.reconstruct(p,candidate='same',config=config,run_modeling=True)
    assert result['status']=='VISUAL_DRAFT_REVIEWED' and result['review_calls']==1
    assert Candidate(p,'same').scene==c.scene
