import numpy as np
import pytest


def test_chunk_overlap_is_three_and_tail_is_covered():
    from real2sim_builder.calibration.simfoundry import plan_chunks
    assert plan_chunks(8,4,3)==([0,1,2,3,4],[4]*5)
    with pytest.raises(ValueError):plan_chunks(8,4,2)


def test_world_to_camera_backprojection_is_inverted():
    from real2sim_builder.calibration.simfoundry import backproject, world_points
    K=np.array([[2.,0,1],[0,2,1],[0,0,1]])
    z=np.full((3,3),2.)
    E=np.c_[np.eye(3),[1.,0,0]]
    points=world_points(z,K,E)
    assert np.allclose(points[1,1],[-1,0,2])
    assert np.allclose(backproject(z,K)[1,1],[0,0,2])


def test_sim3_camera_merge_scales_depth_without_mixing_worlds():
    from real2sim_builder.calibration.simfoundry import merge_chunks
    centers=np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,0],[2,1,0]],float)
    def chunk(c):
        ext=np.array([np.c_[np.eye(3),-x]for x in c])
        return dict(extrinsics=ext,intrinsics=np.tile(np.eye(3),(len(c),1,1)),
                    depth=np.ones((len(c),2,2)),conf=np.ones((len(c),2,2)),image=np.zeros((len(c),2,2,3),np.uint8))
    a=chunk(centers[:4]);b=chunk((centers[1:]-[2,3,0])/2)
    merged,report=merge_chunks([a,b],[0,1],[4,4],5)
    assert np.allclose(-merged['extrinsics'][-1,:3,3],centers[-1])
    assert np.allclose(merged['depth'][-1],2)
    assert report[0]['scale']==pytest.approx(2)
    assert np.allclose(merged['depth'][:4],1)


def test_collinear_camera_overlap_is_not_accepted_as_a_unique_sim3():
    from real2sim_builder.calibration.simfoundry import similarity
    p=np.c_[np.arange(3),np.zeros((3,2))]
    with pytest.raises(ValueError,match='degenerate'):similarity(p,p)


def test_world_frame_uses_translation_before_rotation():
    from real2sim_builder.calibration.simfoundry import support_transform
    T=support_transform([0,0,-1],[.2,.3,1])
    assert np.allclose(T@np.array([.2,.3,1,1]),[0,0,0,1])
    assert (T@np.array([.2,.3,0,1]))[2]==pytest.approx(1)


def test_metric_check_reports_disagreement_and_does_not_rescale():
    from real2sim_builder.calibration.simfoundry import metric_qa
    points=np.array([[0,0,0],[.246,0,0],[.246,.234,0],[0,.234,0]])
    saved=points.copy();report=metric_qa(points,[.147,.151])
    assert report['verified'] is False
    assert report['edges'][0]['relative_error']==pytest.approx((.246-.147)/.147)
    assert np.array_equal(points,saved)
