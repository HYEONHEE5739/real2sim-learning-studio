import numpy as np
from real2sim_builder.calibration.registration import align_points,plane


def test_proper_similarity_alignment_keeps_scale_separate_from_rigid_transform():
    from scipy.spatial.transform import Rotation
    points=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],float)
    rotation=Rotation.from_euler('xyz',[.1,.2,.3]).as_matrix();target=points@rotation.T*2+[.3,-.1,.05]
    report=align_points(points,target,estimate_scale=True)
    assert report['status']=='ESTIMATED'and abs(report['scale']-2)<1e-12
    pose=np.asarray(report['T_target_source']);np.testing.assert_allclose(pose[:3,:3],rotation,atol=1e-12)
    assert np.isclose(np.linalg.det(pose[:3,:3]),1)and report['rmse']<1e-12
    assert align_points(points[:2],target[:2])['status']=='NEEDS_MORE_DATA'
    assert align_points(np.array([[0,0,0],[1,0,0],[2,0,0]]),points[:3])['status']=='NEEDS_MORE_DATA'


def test_plane_is_format_independent_and_does_not_certify_metric_scale():
    x,y=np.meshgrid(np.linspace(-1,1,10),np.linspace(-1,1,10));points=np.c_[x.ravel(),y.ravel(),np.full(x.size,.3)]
    report=plane(np.vstack([points,[[4,4,2]]]))
    np.testing.assert_allclose(report['normal'],[0,0,1],atol=1e-10)
    assert report['provenance']=='derived'and report['rmse']<1e-10


def test_measured_candidate_constraints_are_available_without_scan(tmp_path):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.files import write,sha
    from test_builder_project import measured_pair_scene,measured_pair_constraints
    project=Project.create(tmp_path,'constraints');project.save_scene(measured_pair_scene());before=sha(project.root/'working/current_scene.yaml')
    candidate=Candidate.create(project,'metric');path=tmp_path/'constraints.yaml';write(path,measured_pair_constraints())
    report=candidate.constrain(path)
    assert report['status']=='MEASURED_RELATIVE_GEOMETRY_APPLIED'
    assert sha(project.root/'working/current_scene.yaml')==before
