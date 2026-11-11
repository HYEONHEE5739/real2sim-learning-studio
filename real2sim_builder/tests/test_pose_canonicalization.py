import numpy as np
from scipy.spatial.transform import Rotation


def test_native_tilt_and_yaw_baking_preserve_world_geometry():
    from real2sim_builder.calibration.canonicalization import native_tilt,native_yaw_snap
    r=Rotation.from_euler('xy',[20,-13],degrees=True).as_matrix()
    tilt,info=native_tilt([r,r,r],[0,0,1],enabled=True)
    assert info['status']=='baked'
    np.testing.assert_allclose((r@tilt.T)@[0,0,1],[0,0,1],atol=1e-10)
    vertices=np.array([[x,y,z]for x in(-2,2)for y in(-1,1)for z in(0,1)])
    raw=Rotation.from_euler('z',19,degrees=True).apply(vertices)
    yaw,report=native_yaw_snap(raw)
    assert report['status']=='snapped'
    np.testing.assert_allclose(np.sort(np.ptp(raw@yaw.T,axis=0)),[1,2,4],atol=1e-10)
    points=np.random.default_rng(7).normal(size=(20,3));c=yaw@tilt
    np.testing.assert_allclose((points@c.T)@(r@c.T).T,points@r.T,atol=1e-12)


def test_native_canonical_backend_never_bakes_physical_placement_tilt():
    from real2sim_builder.calibration.canonicalization import native_tilt
    r=Rotation.from_euler('x',25,degrees=True).as_matrix()
    tilt,info=native_tilt([r],[0,0,1],enabled='auto',shape_model='codex_blender')
    np.testing.assert_array_equal(tilt,np.eye(3))
    assert info['status']=='canonical_backend'
    _,info=native_tilt([r,Rotation.from_euler('y',-25,degrees=True).as_matrix()],[0,0,1],enabled=True)
    assert info['status']=='inconsistent_fits'
