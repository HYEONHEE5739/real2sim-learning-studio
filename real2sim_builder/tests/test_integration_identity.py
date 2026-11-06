"""Instance identity and independent authoring, using synthetic observations."""
import copy
import numpy as np
from PIL import Image
from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import sha
from real2sim_builder.authoring import modeling_groups
from real2sim_builder.inference import associate_instances


def test_product_similarity_never_automatically_shares_new_assets(tmp_path):
    p=Project.create(tmp_path,'two cups');c=Candidate.create(p,'draft')
    objects={name:{'prompt':'paper cup','category':'cup','asset_group':'same_product',
        'asset_group_relation':{'status':'CONFIRMED','provenance':'user_declared','evidence':['same product']}}
        for name in ('cup_one','cup_two')}
    groups,_=modeling_groups(c,{'objects':objects},{})
    assert set(groups)=={'cup_one','cup_two'}
    assert groups['cup_one']['members']==['cup_one']
    assert groups['cup_two']['members']==['cup_two']


def test_nearly_duplicate_masks_cannot_identify_two_objects(tmp_path):
    masks=[]
    for index in range(2):
        a=np.zeros((40,40),np.uint8);a[10:30,10:30+index]=255
        file=tmp_path/f'{index}.png';Image.fromarray(a).save(file)
        masks.append({'path':str(file),'sha256':sha(file)})
    report={'segments':[{'object_id':name,'image_id':'view','masks':[masks[i]],'status':'UNIQUE_ESTIMATED'}for i,name in enumerate(('a','b'))]}
    result=associate_instances(report,{'a':{},'b':{}})
    assert all(r['association']['status']=='AMBIGUOUS' for r in result['segments'])


def test_representative_identity_does_not_accept_conflicting_other_view_semantics(tmp_path):
    from test_multiview_pipeline import observations_fixture
    report=observations_fixture(tmp_path)
    # v0 fixes identities. Wrong v1 boxes swap the same two objects.
    objects={'left':{'representative_view':'v0','images':{'v0':{'box_xyxy':[20,20,40,60]},'v1':{'box_xyxy':[50,20,70,60]}}},
             'right':{'representative_view':'v0','images':{'v0':{'box_xyxy':[60,20,80,60]},'v1':{'box_xyxy':[10,20,30,60]}}}}
    before=copy.deepcopy(report)
    result=associate_instances(report,objects)
    assert report==before
    rows=[r for r in result['segments']if r['image_id']=='v1']
    assert all(r['association']['status']=='AMBIGUOUS' for r in rows)


def test_codex_plan_chooses_representative_views_and_no_asset_groups(tmp_path):
    from real2sim_builder.authoring import scene_analysis_schema,parse_scene_analysis
    from real2sim_builder.evidence import save_scene_memo
    p=Project.create(tmp_path,'plan');memo=save_scene_memo(p,'two cups')
    schema=scene_analysis_schema()
    assert 'asset_groups'not in schema['properties']
    obj={'id':'cup_one','prompt':'cup','role':'receptacle','category':'cup','modeling_notes':'',
         'geometry':None,'representative_view':{'image_id':'clear','evidence':'separate visible cup'},
         'observations':[{'image_id':'clear','box_xyxy':[2,2,10,10],'evidence':'visible rim',
                          'points':[{'xy':[5,5],'label':1}]}]}
    answer={'scene_memo_sha256':memo['sha256'],'objects':[obj],'task':None,'needs':[]}
    objects=parse_scene_analysis(answer,memo,['occluded','clear'])
    assert objects['cup_one']['representative_view']=='clear'
    assert 'asset_group'not in objects['cup_one']
    assert objects['cup_one']['images']['clear']['points']==[{'xy':[5,5],'label':1}]


def test_existing_shared_asset_keeps_bindings_but_new_model_is_isolated(tmp_path):
    from real2sim_builder.authoring import attach_modeled_assets,modeling_tasks
    from real2sim_builder.object_assets import register_object_asset,instance_operation
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','preserved shared');c=Candidate.create(p,'draft')
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='old_cups')
    for name in ('a','b'):c.edit([instance_operation(p,asset['manifest'],name,role='receptacle')])
    original=copy.deepcopy(c.scene);digest=sha(p.root/asset['manifest'])
    config={'objects':{n:{'prompt':'cup','asset_group':'old_cups'}for n in ('a','b')}}
    assert modeling_tasks(c,config,{})['pending']==[]
    assert attach_modeled_assets(c,config,{})['attached']==[]
    config['objects']['a'].update(asset_manifest=asset['manifest'],modeling_action='new')
    groups,_=modeling_groups(c,config,{})
    assert groups['a']['members']==['a'] and groups['b']['members']==['b']
    assert modeling_tasks(c,config,{})['pending']==['a']
    assert c.scene==original and sha(p.root/asset['manifest'])==digest


def test_independent_asset_preserves_codex_memo_change_diagnostics(tmp_path):
    from real2sim_builder.evidence import save_scene_memo
    p=Project.create(tmp_path,'memo change');c=Candidate.create(p,'draft')
    old=save_scene_memo(p,'a cup');save_scene_memo(p,'change its height')
    config={'objects':{'cup':{'prompt':'cup','asset_group':'old_product',
        'asset_group_relation':{'status':'CONFIRMED','provenance':'user_declared',
          'memo_sha256':old['sha256'],'change_kind':'geometry','evidence':['old memo']}}}}
    groups,_=modeling_groups(c,config,{})
    assert groups['cup']['memo_relation_stale']
    assert groups['cup']['relations'][0]['change_kind']=='geometry'


def test_explicit_duplicate_assignment_is_not_reassigned_by_geometry(tmp_path):
    from test_multiview_pipeline import observations_fixture
    report=observations_fixture(tmp_path)
    objects={'left':{'representative_view':'v0','images':{'v0':{'box_xyxy':[20,20,40,60]},'v1':{'box_xyxy':[10,20,30,60]}}},
             'right':{'representative_view':'v0','images':{'v0':{'box_xyxy':[60,20,80,60]},'v1':{'box_xyxy':[10,20,30,60]}}}}
    result=associate_instances(report,objects)
    rows=[r for r in result['segments']if r['image_id']=='v1']
    assert all(r['association']['status']=='AMBIGUOUS' for r in rows)
    assert all(r['association'].get('conflict') for r in rows)
