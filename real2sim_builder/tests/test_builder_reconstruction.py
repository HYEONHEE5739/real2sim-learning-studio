"""Real algorithm fixture copies from the original scan initialization suite."""
import copy,json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from real2sim_builder.project import Project,Candidate,write,read,sha,empty,value
from real2sim_builder.reconstruction import import_scan,registration,initialize,load,segment,plane,selection,scale_from_lengths,analyze,run


def glb(path):
    import trimesh
    scene=trimesh.Scene();mesh=trimesh.creation.box(extents=[.06,.04,.05]);mesh.visual=trimesh.visual.texture.TextureVisuals(uv=np.zeros((len(mesh.vertices),2)),image=Image.new('RGB',(32,32),'red'))
    scene.add_geometry(mesh,node_name='block_node',transform=trimesh.transformations.translation_matrix([.1,0,.025]));scene.add_geometry(trimesh.creation.box(extents=[.6,.4,.02]),node_name='table_node',transform=trimesh.transformations.translation_matrix([0,0,-.01]));path.write_bytes(scene.export(file_type='glb'));return path


def registered():
    return dict(correspondences=[{'scan':p,'world_m':p,'source':'measured','evidence':'surveyed fixture'} for p in [[0,0,0],[.2,0,0],[0,.2,0],[0,0,.2]]],fit_scale=True)


def test_glb_import_nodes_texture_hash_and_idempotence(tmp_path):
    p=Project.create(tmp_path/'projects','scan');source=glb(tmp_path/'scan.glb');original=sha(source);row=import_scan(p,source)
    assert len(row['inspection']['nodes'])==2 and row['inspection']['metric_scale_status']=='UNKNOWN'
    assert import_scan(p,source)['id']==row['id'] and len(p.evidence['scans'])==1 and sha(source)==original
    _,nodes=load(source,textures=True);assert any(getattr(m.visual,'uv',None) is not None for _,m,_ in nodes)
    assert np.allclose(np.vstack([m.vertices for _,m,_ in nodes]).max(0),[.3,.2,.05])


def test_registration_recovers_scale_rigid_and_rejects_degeneracy():
    c=registered();t=np.array([.3,-.1,.05])
    for r in c['correspondences']:r['world_m']=(np.asarray(r['scan'])*2+t).tolist()
    report=registration(c);assert report['status']=='ESTIMATED' and abs(report['scale']-2)<1e-8;np.testing.assert_allclose(np.asarray(report['T_world_scan'])[:3,3],t)
    assert registration({'correspondences':c['correspondences'][:2]})['status']=='NEEDS_MORE_DATA'
    for r in c['correspondences']:r['scan']=[r['scan'][0],0,0]
    assert registration(c)['status']=='NEEDS_MORE_DATA'


def test_initial_candidate_preserves_measured_dims_and_open_collision(tmp_path):
    from real2sim_builder.project import import_metadata
    p=Project.create(tmp_path/'projects','scan');scan=import_scan(p,glb(tmp_path/'scan.glb'));measurement=tmp_path/'measurement.yaml';write(measurement,{'units':'mm','objects':[{'id':'block','role':'manipulable_object','dimensions':[24,24,24]}]});import_metadata(p,measurement);c=Candidate.create(p,'initial')
    config=tmp_path/'config.yaml';write(config,{'schema':'real2sim.scan-initialization/1','registration':registered(),'objects':[{'id':'block','role':'manipulable_object','shape':'box','roi_scan':[[.069,-.021,-.001],[.131,.021,.051]]},{'id':'cup','role':'receptacle','shape':'container','roi_scan':[[-.31,-.21,-.021],[.31,.21,-.002]],'full_bounds':True,'wall_m':.002}]})
    baseline=sha(p.root/'working/current_scene.yaml');report=initialize(c,scan['id'],config)
    assert report['status']=='INITIALIZED_ESTIMATED' and sha(p.root/'working/current_scene.yaml')==baseline
    assert c.scene['objects'][0]['dimensions']['value']==[.024]*3 and c.scene['objects'][1]['collision']['type']=='container'
    assert any(report['objects'][0]['dimension_conflict'])
    with pytest.raises((ValueError,FileNotFoundError)):c.promote()


def test_missing_registration_never_invents_metric_geometry(tmp_path):
    p=Project.create(tmp_path/'projects','scan');scan=import_scan(p,glb(tmp_path/'scan.glb'));c=Candidate.create(p,'initial');config=tmp_path/'config.yaml';write(config,{'schema':'real2sim.scan-initialization/1','objects':[]});before=sha(c.root/'candidate_scene.yaml')
    assert initialize(c,scan['id'],config)['status']=='NEEDS_MORE_DATA' and sha(c.root/'candidate_scene.yaml')==before


def test_image_only_pipeline_requests_metric_evidence_without_export(tmp_path):
    from real2sim_builder.project import add_image
    p=Project.create(tmp_path/'projects','unknown');image=tmp_path/'real.png';Image.new('RGB',(64,48),'red').save(image);add_image(p,image)
    state=run(p);assert state['status']=='NEEDS_MORE_DATA' and len(state['needs'])>=2
    assert p.scene['cameras'][0]['K']['value'] is None and not list((p.root/'exports').glob('*'))


def test_segment_plane_and_components_retains_source(tmp_path):
    p=Project.create(tmp_path/'projects','segment');source=glb(tmp_path/'scan.glb');scan=import_scan(p,source);before=sha(source);config=tmp_path/'segment.yaml'
    write(config,{'roi_scan':[[-.4,-.3,-.1],[.4,.3,.2]],'up_scan':[0,0,1],'plane_tolerance_scan':.001,'voxel_scan':.005,'cluster_radius_scan':.03,'min_component_points':3})
    report=segment(p,scan['id'],config)
    assert report['status'] in ('PROPOSALS_ONLY','NEEDS_MORE_DATA') and sha(source)==before
    assert report['status']!='PASS'


def test_pure_registration_reference_actual_saved_configuration_and_boundary():
    import ast
    source=Path('/home/hyeonhee/soarm_isaaclab/real2sim-builder/app/reconstruction/scan.py');tree=ast.parse(source.read_text());function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='registration');space={'np':np};exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),space)
    cfg=registered();cfg['correspondences'][3]['world_m'][2]+=.001
    assert registration(cfg)==space['registration'](cfg)
    with pytest.raises(ValueError):registration({'correspondences':[{'scan':[0,0,0],'world_m':[0,0,0],'source':'estimated'}]*3})


def test_validation_report_completes_with_no_images_and_no_fake_pass(tmp_path):
    from real2sim_builder.reconstruction import validate_scene
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'projects','validation');p.save_scene(legacy_scene())
    report,rendered=validate_scene(p,p.scene,None,tmp_path/'review',{'mae':.1,'silhouette_iou':.8,'reprojection_px':3.})
    assert report['passed'] is False and report['physics_status']=='PHYSICS_NOT_VALIDATED'
    assert report['input_signature']==p.signature() and 'diagnosis' in report and 'coverage' in report
    assert rendered=={}
