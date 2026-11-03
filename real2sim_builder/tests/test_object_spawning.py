import copy
import pytest
from test_builder_export import project_fixture


def test_builder_edits_and_exports_explicit_spawn_policy_without_changing_geometry(tmp_path):
    from real2sim_builder.project import Candidate
    from real2sim_builder.export import export_revision,verify_package
    project=project_fixture(tmp_path);candidate=Candidate.create(project,'selectable')
    before=candidate.scene
    candidate.edit([dict(op='set_spawn',id='block',value='recipe')])
    after=candidate.scene
    assert after['objects'][1]['spawn']=='recipe'
    del after['objects'][1]['spawn'];assert after==before
    from real2sim_builder.files import write
    write(candidate.root/'metrics.json',dict(input_signature=project.signature(candidate.scene),passed=False,scope='spawn metadata edit; geometry unchanged'))
    export_revision(project,destination=project.root/'exports/selectable',candidate=candidate.name,allow_unvalidated=True)
    package=verify_package(project.root/'exports/selectable')
    assert package.scene['objects']['block']['spawn']=='recipe'
    assert package.scene['objects']['table']['spawn']=='always'
    with pytest.raises(ValueError):candidate.edit([dict(op='set_spawn',id='block',value='sometimes')])


def test_isaac_derived_layers_exclude_unselected_workpieces_and_their_children(tmp_path):
    from real2sim_builder.export import export_revision,verify_package
    from real2sim_builder.files import write
    from robot_learning_workbench.engines.isaac.env_cfg import write_scene_assets
    from pxr import Usd
    project=project_fixture(tmp_path);scene=project.scene
    scene['objects'][1]['spawn']='recipe'
    other=copy.deepcopy(scene['objects'][1]);other['id']='other';scene['objects'].append(other)
    badge=copy.deepcopy(other);badge.update(id='badge',role='fixture',parent_object='other',spawn='always');scene['objects'].append(badge)
    project.save_scene(scene);write(project.root/'working/validation/report.json',dict(passed=False,input_signature=project.signature(),scope='synthetic selection'))
    export_revision(project,destination=project.root/'exports/selected',allow_unvalidated=True)
    package=verify_package(project.root/'exports/selected')
    inputs=dict(active_object_ids=('block',),task={'dynamic':['block']},compiled_physics={'objects':{}})
    layers=write_scene_assets(package,inputs,tmp_path/'runtime')
    static=Usd.Stage.Open(str(layers['static']))
    assert not static.GetPrimAtPath('/Static/other').IsActive()
    assert not static.GetPrimAtPath('/Static/badge').IsActive()
    assert static.GetPrimAtPath('/Static/table').IsActive()
    assert set(layers['objects'])=={'block'}
