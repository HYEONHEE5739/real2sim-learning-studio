from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import read,write,sha


def test_empty_inputs_keep_a_measured_draft_without_launching_models_or_export(tmp_path):
    from real2sim_builder.automation import reconstruct
    p=Project.create(tmp_path,'empty auto')
    config={'measurements':[{'id':'block','kind':'box','dimensions_m':[.03]*3,'evidence':['caliper']}],
            'objects':{'block':{'prompt':'red cube'}}}
    result=reconstruct(p,candidate='auto_1',config=config)
    assert result['status']=='NEEDS_MORE_DATA' and result['needs']
    c=Candidate(p,'auto_1');assert c.scene['objects'][0]['pose']['value']is None
    assert not(p.root/'working/current_scene.yaml').exists() and not list((p.root/'exports').iterdir())
    assert not(c.root/'inference/sam-job').exists()
    assert p.state['status']=='NEEDS_MORE_DATA'


def test_cli_reconstruction_uses_saved_configuration_and_retains_original(tmp_path,capsys):
    from real2sim_builder.cli import main
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'cli auto');p.save_scene(legacy_scene());before=sha(p.root/'working/current_scene.yaml')
    config=tmp_path/'configuration.yaml';write(config,{'objects':{'block':{'prompt':'cube'}}})
    assert main(['reconstruct',str(p.root),'--candidate','cli_auto','--config',str(config)])==2
    assert read(p.root/'input/reconstruction.yaml')['objects']['block']['prompt']=='cube'
    assert sha(p.root/'working/current_scene.yaml')==before
    assert read(p.root/'scratch/agent/cli_auto/reconstruction.json')['physical_verified']is False


def test_board_pixel_binding_uses_existing_measured_world_geometry():
    from real2sim_builder.automation import board_binding
    from test_builder_export import legacy_scene
    import numpy as np
    scene=legacy_scene();uv=[[10,10],[100,10],[100,80],[10,80]]
    binding=board_binding(scene,'table',uv)
    np.testing.assert_allclose(binding['world_points_m'],[[-.5,-.4,0],[.5,-.4,0],[.5,.4,0],[-.5,.4,0]])
    assert binding['uv_px']==uv and binding['source']=='measured'


def test_pipeline_lock_can_nest_existing_candidate_operations_but_not_other_threads(tmp_path):
    from real2sim_builder.candidate import exclusive
    from concurrent.futures import ThreadPoolExecutor
    import pytest
    p=Project.create(tmp_path,'nested lock')
    with exclusive(p):
        c=Candidate.create(p,'nested')
        assert c.info['status']=='OPEN'and(p.root/'working/run.lock').exists()
        with ThreadPoolExecutor(1)as pool:
            future=pool.submit(Candidate.create,p,'concurrent')
            with pytest.raises(RuntimeError,match='busy'):future.result()
    assert not(p.root/'working/run.lock').exists()


def test_review_export_owns_cloud_and_mask_and_cannot_promote_the_draft(tmp_path):
    import numpy as np
    from PIL import Image
    import pytest
    from real2sim_builder.export import export_revision
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'review');p.save_scene(legacy_scene());c=Candidate.create(p,'draft')
    points=c.root/'points.npz';np.savez(points,points_world_m=np.ones((2,3)))
    mask=c.root/'mask.png';Image.new('L',(160,120),255).save(mask)
    scene=c.scene;scene['reconstruction_observations']={'clouds':[{
        'path':points.relative_to(p.root).as_posix(),'sha256':sha(points),
        'mask':mask.relative_to(p.root).as_posix(),'mask_sha256':sha(mask)}]}
    frozen=c.root/'configuration.yaml';write(frozen,{'objects':{'block':{'prompt':'cube'}}})
    scene['reconstruction_configuration']={'path':frozen.relative_to(p.root).as_posix(),'sha256':sha(frozen),'provenance':'derived'};c.save(scene)
    write(c.root/'metrics.json',{'scope':'train render only','images':[{}],'passed':False,'input_signature':p.signature(scene)})
    with pytest.raises(ValueError,match='Evaluate'):c.promote()
    destination=p.root/'exports/review';export_revision(p,destination=destination,candidate='draft',allow_unvalidated=True)
    exported=read(destination/'authored_scene.json')['reconstruction_observations']['clouds'][0]
    assert sha(destination/exported['path'])==sha(points)and sha(destination/exported['mask'])==sha(mask)
    frozen_export=read(destination/'authored_scene.json')['reconstruction_configuration']
    assert sha(destination/frozen_export['path'])==sha(frozen)


def test_mask_selection_preferences_do_not_rebase_the_current_scene_evidence(tmp_path):
    from real2sim_builder.automation import save_configuration
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'preferences');p.save_scene(legacy_scene());before=p.signature()
    save_configuration(p,{'objects':{'block':{'prompt':'cube'}}})
    c=Candidate.create(p,'correction')
    save_configuration(p,{'objects':{'block':{'prompt':'cube'}},'selections':{'photo':{'block':1}}})
    assert p.signature()==before==c.info['base_signature']
