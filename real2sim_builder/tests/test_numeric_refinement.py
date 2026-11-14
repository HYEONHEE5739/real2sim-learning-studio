import copy
import numpy as np
from real2sim_builder.files import write,read
from real2sim_builder.project import Project,Candidate
from test_builder_export import legacy_scene


def test_numeric_loop_reuses_solver_rejects_regression_and_preserves_best(tmp_path,monkeypatch):
    from real2sim_builder import automation,observations
    from real2sim_builder.calibration import hybrid,joint
    p=Project.create(tmp_path/'scenes','numeric');source=legacy_scene();source['objects'][1]['pose']['provenance']='estimated';p.save_scene(source);c=Candidate.create(p,'refit')
    scene=c.scene;scene['objects'][1]['pose']['value'][0][3]=.03;c.save(scene)
    monkeypatch.setattr(observations,'register_sensor_views',lambda c,cfg,**kw:{'scene':kw['scene'],'views':[],'needs':[]})
    def metric(project,scene,folder,options):
        x=abs(scene['objects'][1]['pose']['value'][0][3])
        return {'input_signature':p.signature(scene),'needs':[],'images':[{'image_id':name,'split':split,'camera_type':name,'mae':x,'rmse':x,'edge_iou':1-x,'objects':[]}for name,split in [('side','train'),('wrist','train'),('held','validation')]]}
    monkeypatch.setattr(hybrid,'alignment_metrics',metric)
    def fit(project,scene,options):
        trial=copy.deepcopy(scene);trial['objects'][1]['pose']['value'][0][3]=.01 if options.get('round')==0 else .05
        return trial,{'status':'IMPROVED','needs':[],'jacobian_rank':6,'parameter_count':6}
    monkeypatch.setattr(joint,'fit_joint_scene',fit)
    r=automation.refine_numeric_pairs(c,{'numeric_refinement':{'max_iterations':2},'fitting':{'round':0}})
    assert r['status']=='REFINED_DRAFT'and r['accepted_iterations']==1
    assert c.scene['objects'][1]['pose']['value'][0][3]==.01
    assert r['physical_verified']is False and r['holdout_used_for_selection']is False
    assert len(r['history'])==2 and r['history'][-1]['accepted']is False
    assert p.scene['objects'][1]['pose']['value'][0][3]==0


def test_numeric_stop_restores_best_and_resume_completes_unfinished_round(tmp_path,monkeypatch):
    from real2sim_builder import automation,observations
    from real2sim_builder.calibration import hybrid,joint
    p=Project.create(tmp_path/'scenes','resume');s=legacy_scene();s['objects'][1]['pose']['provenance']='estimated';p.save_scene(s);c=Candidate.create(p,'draft')
    s=c.scene;s['objects'][1]['pose']['value'][0][3]=.03;c.save(s)
    monkeypatch.setattr(observations,'register_sensor_views',lambda c,cfg,**kw:{'scene':kw['scene'],'views':[],'needs':[]})
    def metrics(p,s,*a):
        x=abs(s['objects'][1]['pose']['value'][0][3]);return {'input_signature':p.signature(s),'needs':[],
            'images':[{'image_id':'side','split':'train','camera_type':'side','mae':x,'rmse':x,'edge_iou':1-x,'objects':[]},
                      {'image_id':'holdout','split':'validation','camera_type':'side','mae':1-x,'rmse':1-x,'edge_iou':x,'objects':[]}]}
    monkeypatch.setattr(hybrid,'alignment_metrics',metrics);stopped=[]
    def fit(p,s,opts):
        trial=copy.deepcopy(s);trial['objects'][1]['pose']['value'][0][3]=.01/(opts['round']+1)
        if opts['round']==1 and not stopped:stopped.append(True);p.control('stop')
        return trial,{'status':'IMPROVED','needs':[],'jacobian_rank':6,'parameter_count':6}
    monkeypatch.setattr(joint,'fit_joint_scene',fit)
    config={'numeric_refinement':{'max_iterations':2}}
    first=automation.refine_numeric_pairs(c,config)
    assert first['status']=='STOPPED'and c.scene['objects'][1]['pose']['value'][0][3]==.01
    final=automation.refine_numeric_pairs(c,config)
    assert final['status']=='REFINED_DRAFT'and final['accepted_iterations']==2
    assert c.scene['objects'][1]['pose']['value'][0][3]==.005
    assert len(final['history'])==2


def test_real_native_render_joint_round_improves_two_views_without_ai(tmp_path,record_property):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder import automation
    from real2sim_builder.calibration.camera import project_point
    p,truth,scene=rendered_fixture(tmp_path)
    e=p.evidence;e['landmarks']=[]
    for image in e['images']:
        cam=next(c for c in truth['cameras']if c['id']==image['camera'])
        for x in(-.03,.03):
            for y in(-.03,.03):
                for z in(-.03,.03):
                    r={'observation':image['id'],'object':'block','point_m':[x,y,z],'source':'measured','evidence':'Synthetic CAD corner'}
                    r['uv']=project_point(truth,cam,r)[0].tolist();e['landmarks'].append(r)
    write(p.root/'input/evidence.yaml',e);p.save_scene(scene);original=copy.deepcopy(p.scene)
    c=Candidate.create(p,'numeric_native')
    result=automation.refine_numeric_pairs(c,{'numeric_refinement':{'max_iterations':2,'render_fit':False},
        'fitting':{'objects':['block'],'cameras':[],'supports':{'block':'table'},'max_nfev':30}})
    assert result['status']=='REFINED_DRAFT',result
    round=result['history'][0];assert round['accepted']
    assert all(a['mae']<b['mae']for a,b in zip(round['metrics']['images'],round['before_metrics']['images']))
    assert p.scene==original and result['physical_verified']is False
    record_property('before_mae',[r['mae']for r in round['before_metrics']['images']])
    record_property('after_mae',[r['mae']for r in round['metrics']['images']])


def test_refined_draft_cli_is_successful_completion_not_physics_approval(tmp_path,monkeypatch):
    from real2sim_builder import automation,cli
    p=Project.create(tmp_path/'scenes','cli numeric')
    monkeypatch.setattr(automation,'refit_pairs',lambda *a,**kw:{'status':'REFINED_DRAFT','physical_verified':False})
    assert cli.main(['refit-pairs',str(p.root),'--candidate','draft','--scene-state','layout'])==0
