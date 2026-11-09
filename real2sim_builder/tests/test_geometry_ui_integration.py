"""New geometry backend through the current single-screen Workbench entry."""
from test_reconstruction_ui import qt_check
import pytest


def test_saved_geometry_runtime_is_used_without_reintroducing_environment_forms(tmp_path):
    qt_check(tmp_path,'''
from real2sim_builder.sfm import backend
model=Path(sys.argv[1])/'weights';model.write_bytes(b'local test checkpoint')
source=Path(sys.argv[1])/'mast3r';(source/'mast3r').mkdir(parents=True)
(source/'mast3r/model.py').write_text('# installed source fixture')
config={'candidate':'same_candidate','sam':{'python':sys.executable,'model':str(model)},
 'geometry':{'backend':'mast3r_colmap','python':sys.executable,'model':str(model),
             'source':str(source),'colmap_python':sys.executable}}
write(p.root/'input/reconstruction.yaml',config)
assert ui.runtime_needs(config)==[],ui.runtime_needs(config)
assert backend({})=='mast3r_colmap'
legacy={'sam':config['sam'],'da3':config['sam']}
assert any('MASt3R'in n for n in ui.runtime_needs(legacy)) and backend(legacy)=='mast3r_colmap'
assert any('MASt3R'in n for n in ui.runtime_needs({'sam':config['sam']}))
assert ui.runtime_needs({'sam':config['sam']},refit=True)==[]
d=ui.ReconstructionDialog(p.root,sys.executable)
assert d.configuration()==config
assert not d.findChildren(QTabWidget)and not d.findChildren(QTableWidget)
assert len(d.findChildren(ui.QComboBox))==2
models=[{'model':'test','defaultReasoningEffort':'high','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]
d.account_result({'snapshot':{'version':'test cli','logged_in':True,'account':{},'models':models,'usage':[]}},0)
commands=[];d.start_cli=lambda args:commands.append(args)
d.launch()
assert commands[0][0]=='reconstruct' and '--run-modeling'in commands[0]
sent=read(Path(commands[0][commands[0].index('--config')+1]))
assert sent['candidate']=='same_candidate'and sent['geometry']==config['geometry']
assert d.effort.currentData()=='high'
d.close()
''')


def test_native_geometry_progress_maps_to_single_screen_and_preserves_auth_controls(tmp_path):
    qt_check(tmp_path,'''
d=ui.ReconstructionDialog(p.root,sys.executable)
d.busy=lambda:True
for stage,phrase,key in [('MASt3R Matching','MASt3R','inference'),
    ('COLMAP Registration / Bundle Adjustment','COLMAP','inference'),
    ('Dense Geometry Alignment','Dense','inference'),('Metric Registration','Camera','camera')]:
 p.update(status='RUNNING',stage=stage)
 d.update_progress()
 assert phrase in d.current.text(),d.current.text()
 assert d.stage_labels[key][0].text().startswith('●'),d.stage_labels[key][0].text()
assert not d.findChildren(QTabWidget)and not d.findChildren(QTableWidget)
d.busy=lambda:False;d.close()
''')


def test_existing_scene_prepare_button_opens_current_dialog_with_saved_backend(tmp_path):
    qt_check(tmp_path,'''
from robot_learning_workbench.ui.scene_inputs import SceneInputs
from real2sim_builder.sfm import backend
config={'candidate':'saved','geometry':{'backend':'mast3r_colmap','source':'saved runtime'}}
write(p.root/'input/reconstruction.yaml',config)
seen=[]
def inspect(dialog):
 assert backend(dialog.configuration())=='mast3r_colmap'
 assert dialog.configuration()==config
 assert not dialog.findChildren(QTabWidget)and not dialog.findChildren(QTableWidget)
 seen.append(dialog.candidate.text())
 return 0
ui.ReconstructionDialog.exec=inspect
panel=SceneInputs(p.root.parent)
panel.backend_python=sys.executable
panel.load({'project':str(p.root),'notes':'Scene memo retained','inputs':[]})
assert panel.reconstruct.isEnabled()
panel.reconstruct.click()
assert seen==['saved']and panel.note_text()=='Scene memo retained'
panel.close()
''')


@pytest.mark.parametrize('refit',[False,True])
def test_reconstruction_hands_effective_fitting_settings_to_existing_solver(tmp_path,monkeypatch,refit):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder import automation,authoring,inference,observations,validation
    from real2sim_builder.calibration import hybrid
    from real2sim_builder.project import Candidate
    from real2sim_builder.files import sha
    project,truth,observed=rendered_fixture(tmp_path);candidate=Candidate(project,'fit')
    scene=candidate.scene;scene['reconstruction_observations']=observed['reconstruction_observations'];candidate.save(scene)
    original=sha(project.root/'working/current_scene.yaml');received=[]
    monkeypatch.setattr(inference,'run_models',lambda *a,**k:{'status':'INFERRED','images':project.evidence['images'],
        'segments':[],'depth_batches':[],'geometry':{'backend':'mast3r_colmap','status':'GEOMETRY_READY'}})
    monkeypatch.setattr(observations,'predict_views',lambda *a,**k:{'views':[]})
    monkeypatch.setattr(inference,'build_point_clouds',lambda *a,**k:scene['reconstruction_observations'])
    monkeypatch.setattr(automation,'attach_modeled_assets',lambda *a:{'attached':[]})
    monkeypatch.setattr(automation,'modeling_tasks',lambda *a:{'status':'ASSETS_READY'})
    def fit(project,scene,folder,options):
        received.append(options)
        return scene,{'status':'BUDGET_EXHAUSTED','converged':False,'training_view_count':2,'after_loss':0.}
    monkeypatch.setattr(hybrid,'fit_scene',fit)
    monkeypatch.setattr(hybrid,'alignment_metrics',lambda *a:{'images':[]})
    monkeypatch.setattr(authoring,'fitting_review',lambda *a:{'status':'NEEDS_MORE_DATA','wrist_observed':False})
    monkeypatch.setattr(validation,'physics_probe',lambda *a:{'status':'NOT_TESTED'})
    config={'objects':{'block':{'prompt':'block'}},'scene_state_id':'layout','fitting':{'max_evaluations':7}}
    result=automation.reconstruct(project,candidate='fit',config=config,refit_only=refit)
    assert received[0]['max_evaluations']==7
    assert received[0]['optimize_appearance']is(not refit)
    if refit:assert received[0]['optimize_dimensions']is False
    assert result['stages']['geometry_backend']['backend']=='mast3r_colmap'
    assert sha(project.root/'working/current_scene.yaml')==original


def test_initial_batch_defaults_to_scene_photos_without_relabeling_capture(tmp_path):
    qt_check(tmp_path,'''
from real2sim_builder.ui_reconstruction import saved_configuration
images=[{'id':'phone','role':'scene_photo','scene_state_id':'photos'},
        {'id':'sensor','role':'capture','scene_state_id':'capture'},
        {'id':'model','role':'model_reference','scene_state_id':'reference'}]
write(p.root/'input/evidence.yaml',{'images':images})
assert saved_configuration(p,'same')['scene_state_id']=='photos'
assert p.evidence['images']==images
''')


def test_pair_without_a_detected_mask_still_saves_actual_same_pose_rgb_comparisons(tmp_path,monkeypatch):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder import automation,inference
    from real2sim_builder.files import read
    p,truth,observed=rendered_fixture(tmp_path)
    monkeypatch.setattr(inference,'run_models',lambda *a,**k:{'status':'SEGMENTED','images':p.evidence['images'],'segments':[],'depth_batches':[],'scene_state_id':'layout'})
    result=automation.reconstruct(p,candidate='fit',config={'objects':{'block':{'prompt':'block'}},'scene_state_id':'layout'},refit_only=True)
    assert result['stages']['pair_comparison']['views']==2
    assert result['stages']['codex_review']['status']=='WAITING_FOR_CODEX_REVIEW'
    assert len(list((p.root/'scratch/agent/fit/fitting/final/previews').glob('*/sim.png')))==2
    assert all(row['objects']==[]for row in read(p.root/'scratch/agent/fit/metrics.json')['images'])
