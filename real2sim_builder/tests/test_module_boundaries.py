"""Scene calculations and authoring lifecycle use explicit role modules."""
def test_scene_candidate_and_project_keep_the_existing_authoring_contract(tmp_path):
    from real2sim_builder.scene import empty,validate
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.files import read
    project=Project.create(tmp_path,'boundary')
    scene=empty('boundary');validate(scene);project.save_scene(scene)
    candidate=Candidate.create(project,'candidate')
    assert candidate.scene==scene and project.scene==scene
    assert read(project.root/'project.yaml')['id']==project.info['id']


def test_role_imports_do_not_initialize_engine_or_gui():
    import subprocess,sys
    result=subprocess.run([sys.executable,'-B','-c',"import sys;from real2sim_builder import project,scene,capture,evidence,candidate;assert not any(n in sys.modules for n in ('isaaclab','mujoco','PyQt6','serial'))"],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_role_modules_and_public_project_api_share_the_same_implementations():
    from real2sim_builder import project,evidence,capture,candidate,scene,scan,reconstruction
    assert project.Project.__module__=='real2sim_builder.project'
    assert project.Candidate is candidate.Candidate
    assert project.import_snapshots is capture.import_snapshots
    assert project.copy_input is evidence.copy_input
    assert project.validate is scene.validate
    assert reconstruction.registration is scan.registration
