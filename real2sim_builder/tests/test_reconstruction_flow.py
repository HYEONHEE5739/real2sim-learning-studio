"""Orchestration contracts; model/tool boundaries replaced, no accuracy claims."""
from real2sim_builder.project import Project, Candidate
from real2sim_builder.files import read, write


def test_reconstruct_runs_analysis_modeling_and_resumes_same_candidate(tmp_path,monkeypatch):
    from real2sim_builder import automation, authoring
    p=Project.create(tmp_path,'connected'); calls=[]
    def stage(project,**kwargs):
        calls.append(('stage',kwargs['config']))
        if len(calls)==1:Candidate.create(project,kwargs['candidate'])
        status={1:'WAITING_FOR_CODEX_ANALYSIS',3:'WAITING_FOR_CODEX',5:'DRAFT_READY'}[len(calls)]
        return {'status':status,'candidate':kwargs['candidate']}
    def model(candidate,**kwargs):
        calls.append(('codex',candidate.name))
        write(p.root/'input/reconstruction.yaml',{'analysis_round':len(calls)})
        return {'status':'ANALYZED_OBJECT_PROPOSALS' if len(calls)==2 else 'REGISTERED_UNVALIDATED'}
    monkeypatch.setattr(automation,'_reconstruct',stage)
    monkeypatch.setattr(authoring,'run_codex_modeling',model)
    result=automation.reconstruct(p,candidate='draft',config={},run_modeling=True)
    assert result['status']=='DRAFT_READY'
    assert [c[0]for c in calls]==['stage','codex','stage','codex','stage']
    assert calls[-1][1]=={'analysis_round':4}
    assert result['modeling_calls']==2


def test_modeling_loop_stops_at_call_budget_and_keeps_candidate(tmp_path,monkeypatch):
    from real2sim_builder import automation, authoring
    p=Project.create(tmp_path,'bounded');Candidate.create(p,'draft')
    monkeypatch.setattr(automation,'_reconstruct',lambda *a,**k:{'status':'WAITING_FOR_CODEX'})
    monkeypatch.setattr(authoring,'run_codex_modeling',lambda *a,**k:{'status':'ASSETS_READY'})
    result=automation.reconstruct(p,candidate='draft',config={},run_modeling=True,max_modeling_calls=1)
    assert result['status']=='WAITING_FOR_CODEX' and result['stop_reason']=='max_modeling_calls'
    assert Candidate(p,'draft').info['status']=='OPEN'


def test_modeling_failure_reports_stage_and_preserves_candidate(tmp_path,monkeypatch):
    from real2sim_builder import automation, authoring
    import pytest
    p=Project.create(tmp_path,'failure');Candidate.create(p,'draft')
    before=Candidate(p,'draft').scene
    monkeypatch.setattr(automation,'_reconstruct',lambda *a,**k:{'status':'WAITING_FOR_CODEX'})
    def failed(*a,**k):raise RuntimeError('model child failed')
    monkeypatch.setattr(authoring,'run_codex_modeling',failed)
    with pytest.raises(RuntimeError,match='model child failed'):
        automation.reconstruct(p,candidate='draft',config={},run_modeling=True)
    result=read(p.root/'scratch/agent/draft/reconstruction.json')
    assert result['status']=='FAILED' and result['failed_stage']=='CODEX_MODELING'
    assert Candidate(p,'draft').scene==before


def test_stop_during_modeling_returns_resumable_state(tmp_path,monkeypatch):
    from real2sim_builder import automation, authoring
    p=Project.create(tmp_path,'stop');Candidate.create(p,'draft')
    monkeypatch.setattr(automation,'_reconstruct',lambda *a,**k:{'status':'WAITING_FOR_CODEX'})
    def stop(*a,**k):raise InterruptedError('user stop')
    monkeypatch.setattr(authoring,'run_codex_modeling',stop)
    result=automation.reconstruct(p,candidate='draft',config={},run_modeling=True)
    assert result['status']=='STOPPED'
    assert read(p.root/'scratch/agent/draft/reconstruction.json')['failed_stage']=='CODEX_MODELING'
    assert Candidate(p,'draft').info['status']=='OPEN'


def test_default_handoff_does_not_launch_codex(tmp_path,monkeypatch):
    from real2sim_builder import automation, authoring
    p=Project.create(tmp_path,'manual')
    monkeypatch.setattr(automation,'_reconstruct',lambda *a,**k:{'status':'WAITING_FOR_CODEX_ANALYSIS'})
    def forbidden(*a,**k):raise AssertionError('unexpected external execution')
    monkeypatch.setattr(authoring,'run_codex_modeling',forbidden)
    assert automation.reconstruct(p,candidate='draft',config={})['status']=='WAITING_FOR_CODEX_ANALYSIS'


def test_review_numeric_remodel_then_complete_reuses_pipeline(tmp_path,monkeypatch):
    from real2sim_builder import automation,authoring
    p=Project.create(tmp_path,'review flow');c=Candidate.create(p,'draft')
    events=[];decisions=iter(['numeric','remodel','complete']);model_pending=[False]
    config={'objects':{'cup':{'prompt':'cup'}},'fitting':{}}
    def stage(project,**kwargs):
        events.append(('stage',kwargs['config']))
        cfg=kwargs['config']
        if cfg['objects']['cup'].get('modeling_action')=='new' and not model_pending[0]:
            return {'status':'WAITING_FOR_CODEX'}
        write(c.root/'metrics.json',{'images':[]})
        return {'status':'NOT_VERIFIED','stages':{'codex_review':{'status':'WAITING_FOR_CODEX_REVIEW'}}}
    def run(candidate,**kwargs):
        if kwargs.get('review_fitting'):
            action=next(decisions);events.append(('review',action))
            return {'status':'REVIEWED','decision':{'action':action,'objects':['cup'],'evidence':['w'],'reason':'visible mismatch'}}
        events.append(('model',None));model_pending[0]=True
        return {'status':'REGISTERED_UNVALIDATED'}
    monkeypatch.setattr(automation,'_reconstruct',stage)
    monkeypatch.setattr(automation,'modeling_tasks',lambda *a:None)
    monkeypatch.setattr(authoring,'run_codex_modeling',run)
    result=automation.reconstruct(p,candidate='draft',config=config,run_modeling=True)
    assert result['status']=='VISUAL_DRAFT_REVIEWED' and not result['physical_verified']
    assert result['review_calls']==3 and result['modeling_calls']==1
    assert [e[0]for e in events]==['stage','review','stage','review','stage','model','stage','review']
    assert events[2][1]['fitting']['objects']==['cup']
    assert events[4][1]['objects']['cup']['modeling_action']=='new'
    assert 'modeling_action' not in config['objects']['cup']
    assert len(list((c.root/'fitting/reviews').glob('*/scene.yaml')))==3


def test_review_budget_does_not_claim_completion(tmp_path,monkeypatch):
    from real2sim_builder import automation,authoring
    p=Project.create(tmp_path,'review budget');c=Candidate.create(p,'draft')
    write(c.root/'metrics.json',{'images':[]})
    monkeypatch.setattr(automation,'_reconstruct',lambda *a,**k:{'status':'NOT_VERIFIED','stages':{'codex_review':{'status':'WAITING_FOR_CODEX_REVIEW'}}})
    monkeypatch.setattr(automation,'modeling_tasks',lambda *a:None)
    monkeypatch.setattr(authoring,'run_codex_modeling',lambda *a,**k:{'decision':{'action':'numeric','objects':[],'evidence':['w'],'reason':'pose'}})
    result=automation.reconstruct(p,candidate='draft',config={'objects':{}},run_modeling=True,max_review_calls=1)
    assert result['status']=='REVIEW_BUDGET_EXHAUSTED'
    assert result['review_calls']==1 and c.info['status']=='OPEN'


def test_stop_in_review_preserves_checkpoint(tmp_path,monkeypatch):
    from real2sim_builder import automation,authoring
    p=Project.create(tmp_path,'review stop');c=Candidate.create(p,'draft')
    before=c.scene;write(c.root/'metrics.json',{'images':[]})
    monkeypatch.setattr(automation,'_reconstruct',lambda *a,**k:{'status':'NOT_VERIFIED','stages':{'codex_review':{'status':'WAITING_FOR_CODEX_REVIEW'}}})
    monkeypatch.setattr(automation,'modeling_tasks',lambda *a:None)
    def stop(*a,**k):raise InterruptedError('stop')
    monkeypatch.setattr(authoring,'run_codex_modeling',stop)
    result=automation.reconstruct(p,candidate='draft',config={'objects':{}},run_modeling=True)
    assert result['status']=='STOPPED' and result['failed_stage']=='CODEX_REVIEW'
    assert c.scene==before
    assert len(list((c.root/'fitting/reviews').glob('*/scene.yaml')))==1
