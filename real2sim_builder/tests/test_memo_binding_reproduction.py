"""Legacy strict checks remain mandatory beside typed Memo group binding.

The fixtures are synthetic. No production Scene, saved diagnostic, model or
remote provider is needed to reproduce the original contract mismatch.
"""
import copy
import hashlib

import pytest

from real2sim_builder import authoring


def _case(text='red block height 24mm.'):
    memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    geometry={'kind':'box','dimensions_m':[None,None,.024],
        'source':'user_memo','evidence_quote':text,'evidence':['User declaration'],
        'wall_m':None,'support':None,'dimension_relations':[],
        'measurement_claims':[{'field':'z','object_id':'block_red',
            'subject_quote':'red block','axis_quote':'height','statement_quote':text,
            'value_quote':'24mm','value':'24','unit':'mm'}]}
    obj={'id':'block_red','prompt':'red block','role':'manipulable_object',
        'category':'block','modeling_notes':'Unmeasured axes stay unknown',
        'representative_view':{'image_id':'photo_a','evidence':'Visible red block'},
        'observations':[{'image_id':'photo_a','box_xyxy':[10,10,30,30],
                         'points':[],'evidence':'Visible red block'}],
        'geometry':geometry,'model_references':[],'robot_attachment':None,
        'support_relation':None}
    answer={'scene_memo_sha256':memo['sha256'],'objects':[obj],
            'capture_layouts':[],'task':None,'needs':[]}
    images=[{'id':'photo_a','role':'scene_photo','resolution':[100,80],
             'sha256':'a'*64,'scene_state_id':'photo_layout'},
            {'id':'ref_a','role':'model_reference','resolution':[100,80],
             'sha256':'b'*64,'scene_state_id':'reference_layout'},
            {'id':'capture_a','role':'capture','resolution':[100,80],
             'sha256':'c'*64,'scene_state_id':'capture_layout',
             'capture_manifest':'capture/manifest.json'}]
    return answer,memo,images


def _parse(answer,memo,images):
    return authoring.parse_scene_analysis(answer,memo,[i['id']for i in images],
        image_records=images,robot_links=['wrist'])


def test_legacy_single_scalar_still_preserves_partial_measured_geometry():
    answer,memo,images=_case();before=copy.deepcopy(answer)
    result=_parse(answer,memo,images)['block_red']['geometry']
    assert result['dimensions_m']==[None,None,.024]
    assert result['provenance']=='measured'
    assert result['numeric_evidence_verified'] is True
    assert answer==before


@pytest.mark.parametrize('layout',['photo_layout','reference_layout','invented_layout'])
def test_only_actual_capture_layout_namespace_can_be_bound(layout):
    answer,memo,images=_case()
    answer['capture_layouts']=[{'scene_state_id':layout,'status':'SAME_LAYOUT',
                              'evidence':'A nonempty claim cannot change namespace'}]
    before=copy.deepcopy(answer)
    with pytest.raises(ValueError,match='Invalid Capture layout reference/evidence'):
        _parse(answer,memo,images)
    assert answer==before


def test_valid_capture_layout_is_accepted_without_confusing_photo_layouts():
    answer,memo,images=_case()
    answer['capture_layouts']=[{'scene_state_id':'capture_layout',
        'status':'AMBIGUOUS','evidence':'Capture relationship is not established'}]
    assert _parse(answer,memo,images)['block_red']['geometry']['provenance']=='measured'


def test_legacy_relation_cannot_authenticate_a_plural_subject_as_unique_ids():
    answer,memo,images=_case('두 개의 블록은 한 변 24mm의 정육면체다.')
    first=answer['objects'][0];second=copy.deepcopy(first)
    first['prompt']='빨간 블록';second.update(id='block_green',prompt='초록 블록')
    answer['objects'].append(second)
    relation={'relation':'cube','statement_quote':memo['text'],
        'relation_quote':'정육면체',
        'bindings':[{'object_id':'block_red','subject_quote':'블록'},
                    {'object_id':'block_green','subject_quote':'블록'}],
        'measurements':[{'field':'edge','axis_quote':'한 변',
            'clause_quote':'한 변 24mm','value_quote':'24mm','value':'24','unit':'mm'}],
        'reference_object_id':None}
    for obj in answer['objects']:
        obj['geometry'].update(dimensions_m=[.024]*3,measurement_claims=[],
                               dimension_relations=[copy.deepcopy(relation)])
    with pytest.raises(ValueError,match='Ambiguous measurement relation subject/Object binding'):
        _parse(answer,memo,images)


@pytest.mark.parametrize('mutation,expected',[
    ('object_id','Measurement Object/axis mismatch'),
    ('source_quote','Dimension quote missing'),
    ('unit','Single literal scalar number/unit witness required'),
    ('numeric','Measurement numeric/unit conversion contradicts returned dimension'),
])
def test_invalid_single_measurement_is_not_repaired_by_group_support(mutation,expected):
    answer,memo,images=_case();geometry=answer['objects'][0]['geometry']
    claim=geometry['measurement_claims'][0]
    if mutation=='object_id':claim['object_id']='block_green'
    elif mutation=='source_quote':geometry['evidence_quote']='red block height 25mm.'
    elif mutation=='unit':claim['unit']='m'
    else:geometry['dimensions_m'][2]=24
    before=copy.deepcopy(answer)
    with pytest.raises(ValueError,match=expected):_parse(answer,memo,images)
    assert answer==before


def test_image_estimate_cannot_become_measured_even_with_numeric_claim_attached():
    answer,memo,images=_case()
    answer['objects'][0]['geometry']['source']='visual_inference'
    result=_parse(answer,memo,images)['block_red']['geometry']
    assert result['provenance']=='estimated'
    assert result['numeric_evidence_verified'] is False


def test_missing_scalar_witness_stays_estimated_and_marked_for_review():
    answer,memo,images=_case()
    answer['objects'][0]['geometry']['measurement_claims']=[]
    result=_parse(answer,memo,images)['block_red']['geometry']
    assert result['numeric_evidence_verified'] is False
    assert result['provenance']=='estimated'
    assert result['measurement_review']=='UNVERIFIED_NUMERIC_EVIDENCE'
