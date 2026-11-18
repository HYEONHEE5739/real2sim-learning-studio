"""Visual evidence may survive deferred numeric/layout claims, never bad identity."""
import copy
import hashlib
import pytest


def plan():
    text='red block is 24mm. Its geometry is an image estimate until measurement review.'
    memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    geometry={'kind':'box','dimensions_m':[.024,.024,.024],'source':'visual_inference',
        'evidence_quote':'','evidence':['Visible RGB estimate'],'wall_m':None,'support':None,
        'measurement_claims':[],'dimension_relations':[]}
    obj={'id':'block_red','prompt':'red block','role':'manipulable_object','category':'block',
        'modeling_notes':'Visible red block; unmeasured appearance is estimated',
        'representative_view':{'image_id':'frame1','evidence':'Visible in RGB'},
        'observations':[{'image_id':'frame1','box_xyxy':[20,10,40,30],'points':[],
                         'evidence':'Visible red block in this image'}],
        'geometry':geometry,'model_references':[],'robot_attachment':None,'support_relation':None}
    answer={'scene_memo_sha256':memo['sha256'],'objects':[obj],'capture_layouts':[],
            'task':None,'needs':[]}
    records=[{'id':'frame1','role':'scene_photo','resolution':[100,80],
              'sha256':'a'*64,'scene_state_id':'photos_layout'},
             {'id':'ref1','role':'model_reference','resolution':[100,80],'sha256':'b'*64}]
    return answer,memo,records


def parse(answer,memo,records):
    from real2sim_builder.authoring import parse_visual_scene_analysis
    return parse_visual_scene_analysis(answer,memo,{r['id']for r in records},
        image_records=records,robot_links=['gripper'])


def test_valid_strict_plan_keeps_full_geometry_and_input_unchanged():
    answer,memo,records=plan();before=copy.deepcopy(answer)
    result=parse(answer,memo,records)
    assert result['validation']=={'status':'FULL','strict_error':None}
    assert result['objects']['block_red']['geometry']['dimensions_m']==[.024,.024,.024]
    assert result['objects']['block_red']['geometry']['provenance']=='estimated'
    assert result['deferred']=={} and answer==before


def test_photo_layout_claim_is_deferred_without_applying_or_losing_raw_dimensions():
    answer,memo,records=plan()
    answer['capture_layouts']=[{'scene_state_id':'photos_layout','status':'SAME_LAYOUT',
                               'evidence':'Photo views look consistent; no Capture record exists'}]
    answer['objects'][0]['geometry'].update(source='user_memo',evidence_quote='red block is 24mm.')
    before=copy.deepcopy(answer)
    result=parse(answer,memo,records)
    assert result['validation']['status']=='VISUAL_ONLY'
    assert 'Capture layout' in result['validation']['strict_error']
    assert 'geometry'not in result['objects']['block_red']
    assert result['objects']['block_red']['images']['frame1']['box_xyxy']==[20,10,40,30]
    assert result['deferred']['geometry']['block_red']==before['objects'][0]['geometry']
    assert result['deferred']['capture_layouts']==before['capture_layouts']
    assert answer==before


def test_invalid_numeric_witness_is_deferred_without_becoming_measured():
    answer,memo,records=plan();g=answer['objects'][0]['geometry']
    g.update(source='user_memo',evidence_quote='red block is 24mm.')
    g['dimension_relations']=[{'relation':'axes','statement_quote':'red block is 24mm.',
        'relation_quote':'치수','bindings':[{'object_id':'block_red','subject_quote':'red block'}],
        'measurements':[{'field':'x','axis_quote':'x','clause_quote':'red block is 24mm.',
                         'value_quote':'24mm','value':'24','unit':'mm'}],
        'reference_object_id':None}]
    before=copy.deepcopy(answer)
    result=parse(answer,memo,records)
    assert result['validation']['status']=='VISUAL_ONLY'
    assert 'Measurement relation' in result['validation']['strict_error']
    assert 'geometry'not in result['objects']['block_red']
    assert result['deferred']['geometry']['block_red']==g
    assert answer==before


@pytest.mark.parametrize('invalid',['memo','bounds','image_id','object_id','duplicate_id','reference_role','attachment'])
def test_projection_does_not_salvage_invalid_identity_or_image_contract(invalid):
    answer,memo,records=plan();obj=answer['objects'][0]
    answer['capture_layouts']=[{'scene_state_id':'photos_layout','status':'SAME_LAYOUT',
                               'evidence':'Forces visual projection before the invalid observation check'}]
    if invalid=='memo':answer['scene_memo_sha256']='0'*64
    elif invalid=='bounds':obj['observations'][0]['box_xyxy']=[20,10,140,30]
    elif invalid=='image_id':obj['observations'][0]['image_id']='invented_image'
    elif invalid=='object_id':obj['id']='../invented_object'
    elif invalid=='duplicate_id':answer['objects'].append(copy.deepcopy(obj))
    elif invalid=='reference_role':obj['model_references']=[{'image_id':'frame1','status':'LINKED','evidence':'Wrong image role'}]
    else:obj['robot_attachment']={'link':'invented_robot_link','T_link_object':None,'evidence':'Unverified link'}
    before=copy.deepcopy(answer)
    with pytest.raises(ValueError):parse(answer,memo,records)
    assert answer==before


def test_projection_validates_schema_before_any_numeric_or_layout_fallback():
    answer,memo,records=plan();answer['objects'][0]['role']='invented_role'
    with pytest.raises(ValueError):parse(answer,memo,records)
