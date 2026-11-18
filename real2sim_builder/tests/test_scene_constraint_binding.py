"""Codex interprets groups; Python authenticates IDs, literal scalars and algebra."""
import copy
import hashlib
import pytest


def binding_case():
    from test_visual_semantic_projection import plan
    from real2sim_builder.stage_artifacts import digest
    answer,_,images=plan()
    rows=[]
    for name in ('red_piece','green_piece','blue_piece'):
        row=copy.deepcopy(answer['objects'][0]);row.update(id=name,prompt=name,geometry=None)
        rows.append(row)
    answer['objects']=rows
    text='These three pieces are cubes, each edge 17mm.'
    memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    answer['scene_memo_sha256']=memo['sha256']
    packet={'scene_memo_sha256':memo['sha256'],'source_plan_sha256':digest(answer),
        'replaces_geometry_ids':[],'capture_layouts':[],
        'groups':[{'id':'pieces','members':[r['id']for r in rows],'count':3,
            'role':'manipulable_object','source_quote':text,'ambiguous':False,
            'evidence':[{'object_id':r['id'],'image_id':'frame1','evidence':'Visible distinct RGB instance'}for r in rows]}],
        'constraints':[{'id':'cube_sizes','kind':'shared_dimension','group_id':'pieces',
            'objects':[r['id']for r in rows],'reference_objects':[],'axis':None,
            'source_quote':text,'quantities':[{'quantity':'cube_edge_length','value':'17','unit':'mm','value_quote':'17mm'}],
            'assumptions':[],'evidence':'Shared declaration refers to all three observed pieces'}],
        'assemblies':[],'needs':[]}
    return packet,answer,memo,images


def validate(packet,answer,memo,images):
    from real2sim_builder.authoring import validate_scene_constraints
    return validate_scene_constraints(packet,answer,memo,image_records=images)


def test_shared_declaration_binds_every_member_without_independent_fake_measurements():
    packet,answer,memo,images=binding_case();before=copy.deepcopy((packet,answer))
    result=validate(packet,answer,memo,images)
    assert result['status']=='VALIDATED'
    assert len(result['constraints'])==1
    for name in ('red_piece','green_piece','blue_piece'):
        spec=result['objects'][name]
        assert spec['geometry']['dimensions_m']==[.017]*3
        assert spec['geometry']['provenance']=='measured'
        assert spec['shape_constraints']['memo_binding']['constraint_ids']==['cube_sizes']
        assert not spec['shape_constraints']['memo_binding']['independent_identity_verified']
    assert (packet,answer)==before


@pytest.mark.parametrize('defect',['id','partial_group','group_count','duplicate','role','source','number','unit','estimated','bottom_diameter','capture','stale'])
def test_invalid_shared_binding_fails_closed(defect):
    packet,answer,memo,images=binding_case();c=packet['constraints'][0]
    if defect=='id':c['objects'][0]='absent'
    elif defect=='partial_group':c['objects']=c['objects'][:1]
    elif defect=='group_count':packet['groups'][0]['count']=4
    elif defect=='duplicate':c['objects'][1]=c['objects'][0]
    elif defect=='role':packet['groups'][0]['role']='fixture'
    elif defect=='source':c['source_quote']='Invented: edge 17mm.'
    elif defect=='number':c['quantities'][0]['value']='18'
    elif defect=='unit':c['quantities'][0]['unit']='m'
    elif defect=='estimated':c['provenance']='estimated'
    elif defect=='bottom_diameter':c['quantities'][0]['quantity']='bottom_diameter'
    elif defect=='capture':packet['capture_layouts']=[{'scene_state_id':'photos_layout','status':'SAME_LAYOUT','evidence':'Wrong namespace'}]
    else:packet['source_plan_sha256']='0'*64
    with pytest.raises(ValueError):validate(packet,answer,memo,images)


def test_unlisted_geometry_cannot_be_silently_superseded():
    packet,answer,memo,images=binding_case();answer['objects'][0]['geometry']={'not':'a geometry'}
    from real2sim_builder.stage_artifacts import digest
    packet['source_plan_sha256']=digest(answer)
    with pytest.raises(ValueError):validate(packet,answer,memo,images)


def test_candidate_owned_video_frames_are_valid_static_observations():
    packet,answer,memo,images=binding_case();images[0]['role']='scene_video_frame'
    result=validate(packet,answer,memo,images)
    assert result['objects']['red_piece']['geometry']['dimensions_m']==[.017]*3
    from real2sim_builder.authoring import semantic_namespaces
    spaces=semantic_namespaces(images)
    assert spaces['scene_video_frame_ids']==['frame1']
    assert spaces['capture_layout_ids']==[]


@pytest.mark.parametrize('layout',['same_constraint','separate_constraints','height_first'])
def test_cube_edge_cannot_be_overwritten_by_a_conflicting_height(layout):
    from real2sim_builder.stage_artifacts import digest
    packet,answer,memo,images=binding_case()
    height_quote='These three pieces have height 18mm.'
    memo['text']+=' '+height_quote
    memo['sha256']=hashlib.sha256(memo['text'].encode()).hexdigest()
    answer['scene_memo_sha256']=packet['scene_memo_sha256']=memo['sha256']
    packet['source_plan_sha256']=digest(answer)
    quantity={'quantity':'height','value':'18','unit':'mm','value_quote':'18mm'}
    if layout=='same_constraint':
        packet['constraints'][0]['source_quote']=memo['text']
        packet['constraints'][0]['quantities'].append(quantity)
    else:
        height=copy.deepcopy(packet['constraints'][0])
        height.update(id='piece_heights',source_quote=height_quote,axis='z',quantities=[quantity])
        packet['constraints'].insert(0 if layout=='height_first'else 1,height)
    before=copy.deepcopy((packet,answer))
    with pytest.raises(ValueError,match='Contradictory'):
        validate(packet,answer,memo,images)
    assert (packet,answer)==before


def test_matching_cube_height_in_another_unit_preserves_the_shared_measurement():
    from real2sim_builder.stage_artifacts import digest
    packet,answer,memo,images=binding_case()
    memo['text']+=' Their height is 1.7cm.'
    memo['sha256']=hashlib.sha256(memo['text'].encode()).hexdigest()
    answer['scene_memo_sha256']=packet['scene_memo_sha256']=memo['sha256']
    packet['source_plan_sha256']=digest(answer)
    packet['constraints'][0]['source_quote']=memo['text']
    packet['constraints'][0]['quantities'].append(
        {'quantity':'height','value':'1.7','unit':'cm','value_quote':'1.7cm'})
    result=validate(packet,answer,memo,images)
    assert result['objects']['red_piece']['geometry']['dimensions_m']==[.017]*3
