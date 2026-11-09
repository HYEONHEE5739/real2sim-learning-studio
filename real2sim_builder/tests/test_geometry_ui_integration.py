"""Codex-first authoring through the current single-screen Workbench entry."""
from test_reconstruction_ui import qt_check
import pytest


def test_retired_geometry_settings_do_not_become_runtime_requirements(tmp_path):
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
assert ui.runtime_needs(legacy)==[]
assert ui.runtime_needs({'sam':config['sam']})==[]
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


def test_codex_render_progress_maps_to_single_screen_and_preserves_auth_controls(tmp_path):
    qt_check(tmp_path,'''
d=ui.ReconstructionDialog(p.root,sys.executable)
d.busy=lambda:True
for stage,phrase,key in [('CODEX ANALYSIS','Codex','analysis'),('SCENE_COMPOSITION','Camera','camera'),('FITTING','렌더','fitting')]:
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
def test_reconstruction_hands_effective_render_settings_without_running_geometry(tmp_path,monkeypatch,refit):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder import automation,inference
    from real2sim_builder.calibration import hybrid
    from real2sim_builder.files import sha
    project,truth,observed=rendered_fixture(tmp_path)
    original=sha(project.root/'working/current_scene.yaml');received=[];real_compare=hybrid.alignment_metrics
    def forbidden(*a,**k):raise AssertionError('Retired automatic geometry path executed')
    monkeypatch.setattr(inference,'run_models',forbidden);monkeypatch.setattr(hybrid,'fit_scene',forbidden)
    def compare(project,scene,folder,options):
        received.append(options);return real_compare(project,scene,folder,options)
    monkeypatch.setattr(hybrid,'alignment_metrics',compare)
    config={'objects':{'block':{'prompt':'block'}},'scene_state_id':'layout',
        'scene_plan':{'object_poses':[],'cameras':[],'needs':[]},'fitting':{'max_evaluations':7}}
    result=automation.reconstruct(project,candidate='fit',config=config,refit_only=refit)
    assert received[0]['max_evaluations']==7
    assert received[0]['optimize_appearance']is(not refit)
    if refit:assert received[0]['optimize_dimensions']is False
    assert 'geometry_backend'not in result['stages']
    assert result['stages']['first_scene']['views']==2
    assert not result['stages']['fitting']['solver_executed']
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
    def forbidden(*a,**k):raise AssertionError('Segmentation is not a Pair prerequisite')
    monkeypatch.setattr(inference,'run_models',forbidden)
    result=automation.reconstruct(p,candidate='fit',config={'objects':{'block':{'prompt':'block'}},'scene_state_id':'layout'},refit_only=True)
    assert result['stages']['pair_comparison']['views']==2
    assert result['stages']['codex_review']['status']=='WAITING_FOR_CODEX_REVIEW'
    assert len(list((p.root/'scratch/agent/fit/fitting/final/previews').glob('*/sim.png')))==2
    assert all(row['objects']==[]for row in read(p.root/'scratch/agent/fit/metrics.json')['images'])
