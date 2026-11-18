"""Typed relation algebra and assembly integrity, using synthetic declarations."""
import copy
import hashlib

import pytest

from test_scene_constraint_binding import binding_case,validate


def _row(plan,name,role):
    row=copy.deepcopy(plan['objects'][0]);row.update(id=name,prompt=name,role=role,geometry=None)
    plan['objects'].append(row)


def _quote(packet,plan,memo,text):
    from real2sim_builder.stage_artifacts import digest
    memo['text']+='\n'+text
    memo['sha256']=hashlib.sha256(memo['text'].encode()).hexdigest()
    plan['scene_memo_sha256']=memo['sha256']
    packet.update(scene_memo_sha256=memo['sha256'],source_plan_sha256=digest(plan))


def _constraint(name,kind,objects,text,quantities=(),**kw):
    row={'id':name,'kind':kind,'group_id':None,'objects':objects,'reference_objects':[],
         'axis':None,'source_quote':text,'quantities':[
             {'quantity':key,'value':str(value),'unit':'mm','value_quote':str(value)+'mm'}
             for key,value in quantities],
         'assumptions':[],'evidence':'Synthetic explicit declaration and associated RGB instances'}
    row.update(kw)
    return row


def _cups():
    packet,plan,memo,images=binding_case()
    names=['bowl_left','bowl_right']
    for name in names:_row(plan,name,'receptacle')
    text='These two bowls each have upper rim diameter 52mm and height 41mm.'
    _quote(packet,plan,memo,text)
    packet['groups'].append({'id':'bowls','members':names,'count':2,'role':'receptacle',
        'source_quote':text,'ambiguous':False,'evidence':[
            {'object_id':n,'image_id':'frame1','evidence':'A distinct bowl in the source RGB'}for n in names]})
    packet['constraints'].append(_constraint('bowl_size','shared_dimension',names,text,
        [('upper_rim_diameter',52),('height',41)],group_id='bowls'))
    text='The upper rim edge gap is 13mm and upper rim center distance is 65mm.'
    _quote(packet,plan,memo,text)
    packet['constraints'].append(_constraint('bowl_spacing','pair_spacing',names,text,
        [('upper_rim_edge_gap',13),('upper_rim_center_distance',65)],
        assumptions=['PARALLEL_AXES','EQUAL_RIM_HEIGHT','CIRCULAR_UPPER_RIMS']))
    return packet,plan,memo,images


def test_upper_rim_measurement_does_not_fill_bottom_or_internal_diameter():
    packet,plan,memo,images=_cups();before=copy.deepcopy((packet,plan))
    result=validate(packet,plan,memo,images)
    for name in ['bowl_left','bowl_right']:
        spec=result['objects'][name]
        assert spec['geometry']['dimensions_m']==[None,None,.041]
        assert spec['geometry']['wall_m'] is None
        quantities=spec['shape_constraints']['memo_binding']['quantities_m']
        assert quantities=={'upper_rim_diameter':.052,'height':.041}
        assert 'bottom_diameter'not in quantities and 'inner_diameter'not in quantities
    pair=next(c for c in result['constraints']if c['id']=='bowl_spacing')
    assert pair['numeric_consistency']=='PASS_UNDER_RECORDED_ASSUMPTIONS'
    assert pair['status']=='CONDITIONAL' and pair['assumptions_verified'] is False
    assert pair['pose_application']=='NONE'
    assert (packet,plan)==before


@pytest.mark.parametrize('quantity',['bottom_diameter','inner_diameter'])
def test_rim_declaration_cannot_be_returned_as_different_diameter(quantity):
    packet,plan,memo,images=_cups()
    packet['constraints'][-2]['quantities'][0]['quantity']=quantity
    with pytest.raises(ValueError):validate(packet,plan,memo,images)


def test_pair_spacing_contradiction_fails_even_with_authentic_scalar_quotes():
    packet,plan,memo,images=_cups()
    text='A revised center distance is 66mm while the upper rim edge gap is 13mm.'
    _quote(packet,plan,memo,text)
    packet['constraints'][-1]=_constraint('bowl_spacing','pair_spacing',['bowl_left','bowl_right'],text,
        [('upper_rim_edge_gap',13),('upper_rim_center_distance',66)],
        assumptions=['PARALLEL_AXES','EQUAL_RIM_HEIGHT','CIRCULAR_UPPER_RIMS'])
    with pytest.raises(ValueError,match='Contradictory rim gap and center distance'):
        validate(packet,plan,memo,images)


def test_pair_spacing_requires_all_geometry_assumptions():
    packet,plan,memo,images=_cups()
    packet['constraints'][-1]['assumptions'].remove('EQUAL_RIM_HEIGHT')
    with pytest.raises(ValueError,match='geometric assumptions'):
        validate(packet,plan,memo,images)


def test_explicit_height_z_axis_is_valid_without_new_pose_or_xy_measurements():
    packet,plan,memo,images=_cups()
    diameter=packet['constraints'][-2]
    height=copy.deepcopy(diameter);height.update(id='height_only',axis='z')
    height['quantities']=[q for q in height['quantities']if q['quantity']=='height']
    packet['constraints'].append(height)
    result=validate(packet,plan,memo,images)
    assert result['objects']['bowl_left']['geometry']['dimensions_m']==[None,None,.041]


@pytest.mark.parametrize('axis',['x','y'])
def test_height_cannot_bind_to_a_different_axis(axis):
    packet,plan,memo,images=_cups();packet['constraints'][-2]['axis']=axis
    with pytest.raises(ValueError):validate(packet,plan,memo,images)


def _rectangle(inner_y=102):
    packet,plan,memo,images=binding_case();_row(plan,'mat','workspace')
    text=f'The mat outer X is 92mm and outer Y is 108mm; inward border 3mm, inner X 86mm and inner Y {inner_y}mm.'
    _quote(packet,plan,memo,text)
    packet['constraints'].append(_constraint('mat_border','rectangle_border',['mat'],text,
        [('outer_x',92),('outer_y',108),('border_width',3),('inner_x',86),('inner_y',inner_y)]))
    return packet,plan,memo,images


def test_inward_border_is_not_geometry_z_or_wall_thickness():
    packet,plan,memo,images=_rectangle()
    mat=validate(packet,plan,memo,images)['objects']['mat']
    assert mat['geometry']['dimensions_m']==[.092,.108,None]
    assert mat['geometry']['wall_m'] is None
    assert mat['shape_constraints']['memo_binding']['quantities_m']['border_width']==.003


def test_inner_rectangle_contradiction_fails_with_exact_source_quotes():
    packet,plan,memo,images=_rectangle(inner_y=101)
    with pytest.raises(ValueError,match='Contradictory rectangle'):
        validate(packet,plan,memo,images)


def test_declared_support_angle_keeps_source_degrees_but_reports_si_radians():
    import math
    packet,plan,memo,images=binding_case();_row(plan,'desk_fixture','support_surface')
    text='The support tilt is 12deg.';_quote(packet,plan,memo,text)
    c=_constraint('support_angle','orientation',['desk_fixture'],text)
    c['quantities']=[{'quantity':'tilt','value':'12','unit':'deg','value_quote':'12deg'}]
    packet['constraints'].append(c)
    angle=validate(packet,plan,memo,images)['constraints'][-1]
    assert angle['quantities'][0]['unit']=='deg'
    assert angle['values_si']['tilt']==pytest.approx(math.radians(12))
    assert angle['pose_application']=='DECLARED_SCENE_CONSTRAINT_ONLY'


def _assembly():
    packet,plan,memo,images=binding_case()
    _row(plan,'arm','reference_robot');_row(plan,'housing','fixture');_row(plan,'lens','fixture')
    text='The existing arm carries one camera assembly composed of housing and lens.'
    _quote(packet,plan,memo,text)
    packet['assemblies']=[{'id':'wrist_camera','members':['housing','lens'],
        'parent_object_id':'arm','source_quote':text,'physical_sensor_count':1,
        'link':None,'T_link_assembly':None,'evidence':'One camera with two appearance components'}]
    return packet,plan,memo,images


def test_assembly_is_unregistered_until_mount_is_known_but_shapes_remain_ready():
    packet,plan,memo,images=_assembly()
    result=validate(packet,plan,memo,images)
    assembly=result['assemblies'][0]
    assert assembly['status']=='UNRESOLVED'
    assert assembly['sensor_registration']=='NOT_REGISTERED'
    assert result['objects']['red_piece']['modeling_readiness']=='READY_FOR_MODELING'
    assert result['objects']['housing']['shape_constraints']['memo_binding']['assembly_id']=='wrist_camera'


def test_reference_robot_is_reused_instead_of_ready_for_new_mesh():
    packet,plan,memo,images=_assembly()
    robot=validate(packet,plan,memo,images)['objects']['arm']
    assert robot['modeling_readiness']=='REUSE_EXISTING_URDF'
    assert 'geometry'not in robot


@pytest.mark.parametrize('defect',['unknown','duplicate_member','overlap','role','parent','link','mount'])
def test_invalid_assembly_integrity_is_rejected(defect):
    packet,plan,memo,images=_assembly();assembly=packet['assemblies'][0]
    if defect=='unknown':assembly['members'].append('unknown_component')
    elif defect=='duplicate_member':assembly['members'].append('housing')
    elif defect=='overlap':packet['assemblies'].append(copy.deepcopy(assembly))
    elif defect=='role':assembly['members'].append('red_piece')
    elif defect=='parent':assembly['parent_object_id']='red_piece'
    elif defect=='link':assembly['link']='invented_link'
    else:assembly['T_link_assembly']=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    with pytest.raises(ValueError):validate(packet,plan,memo,images)


def test_duplicate_assembly_id_is_invalid_even_with_disjoint_members():
    packet,plan,memo,images=_assembly()
    first=packet['assemblies'][0];second=copy.deepcopy(first)
    first['members']=['housing'];second['members']=['lens']
    packet['assemblies'].append(second)
    with pytest.raises(ValueError,match='[Dd]uplicate|[Ii]dentifier'):
        validate(packet,plan,memo,images)
