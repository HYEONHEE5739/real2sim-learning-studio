"""Unknown primitive dimensions may fit; measured axes and asset versions stay fixed."""
import copy
import numpy as np
from test_fitting_strategy import fixture,selected


def test_dimension_parameters_require_metric_views_and_preserve_measured_axes():
    from real2sim_builder.calibration.joint import parameter_blocks,apply_parameters
    scene,rows=fixture(2);scene['cameras'][0]['pose']['provenance']='calibrated'
    obj=scene['objects'][1];obj['dimensions']['provenance']='estimated'
    obj['dimensions']['constraints']={'value':[None,None,obj['dimensions']['value'][2]],'provenance':'measured','evidence':['height']}
    original=copy.deepcopy(scene)
    options={'cameras':[],'objects':[],'optimize_dimensions':True,'optimize_depth_scale':False,'optimize_intrinsics':False}
    active,report=selected(scene,rows,options)
    assert active['dimensions','block']==[0,1]
    blocks,radius=parameter_blocks(scene,rows,options)
    updated,_=apply_parameters(scene,blocks,np.full(len(radius),.1))
    dims=updated['objects'][1]['dimensions']
    assert np.allclose(dims['value'][:2],np.array(obj['dimensions']['value'][:2])*np.exp(.1))
    assert dims['value'][2]==obj['dimensions']['value'][2]
    assert dims['constraints']==obj['dimensions']['constraints'] and dims['provenance']=='optimized'
    assert scene==original
    assert ('dimensions','block') not in selected(scene,rows[:1],options)[0]
    obj['object_asset']={'asset_id':'bound-version'}
    assert ('dimensions','block') not in selected(scene,rows,options)[0]


def test_joint_render_fit_reduces_unknown_width_error(tmp_path):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder.calibration.hybrid import fit_scene
    p,truth,scene=rendered_fixture(tmp_path)
    obj=scene['objects'][1];obj['pose']=copy.deepcopy(truth['objects'][1]['pose'])
    expected=truth['objects'][1]['dimensions']['value']
    obj['dimensions']['provenance']='estimated';obj['dimensions']['value'][0]*=1.15
    obj['dimensions']['constraints']={'value':[None,*expected[1:]],'provenance':'measured','evidence':['fixture']}
    before=copy.deepcopy(scene)
    fitted,report=fit_scene(p,scene,p.root/'scratch/size-fit',dict(cameras=[],objects=[],optimize_intrinsics=False,
        optimize_depth_scale=False,optimize_dimensions=True,max_iterations=2,max_evaluations=40))
    assert report['after_loss']<report['before_loss']
    assert abs(fitted['objects'][1]['dimensions']['value'][0]-expected[0])<.004
    assert fitted['objects'][1]['dimensions']['value'][1:]==expected[1:]
    assert scene==before and fitted['objects'][1]['pose']==obj['pose']


def test_native_changed_box_dimensions_match_fresh_compilation(tmp_path):
    from test_builder_export import legacy_scene
    from real2sim_builder.rendering import Renderer
    scene=legacy_scene();scene['objects'][1]['dimensions']['provenance']='estimated'
    original=copy.deepcopy(scene);changed=copy.deepcopy(scene)
    changed['objects'][1]['dimensions']['value'][0]*=1.4
    with Renderer(scene,tmp_path,tmp_path/'old') as renderer:
        before=renderer.mask('side','block');renderer.update_scene(changed)
        mask=renderer.mask('side','block');rgb=renderer.rgb('side');depth=renderer.depth('side')
        with Renderer(changed,tmp_path,tmp_path/'new') as fresh:
            assert np.array_equal(mask,fresh.mask('side','block'))
            assert np.array_equal(rgb,fresh.rgb('side'))
            assert np.allclose(depth,fresh.depth('side'))
        assert not np.array_equal(before,mask)
        renderer.update_scene(scene)
        assert np.array_equal(renderer.mask('side','block'),before)
    assert scene==original
