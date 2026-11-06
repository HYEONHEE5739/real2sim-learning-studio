"""Known lens distortion belongs to observation pixels, not inferred geometry."""
import copy
import cv2
import numpy as np
import pytest
from real2sim_builder.scene import value


@pytest.mark.parametrize('count',[4,5,8,12,14])
@pytest.mark.parametrize('quarter',[0,1,2,3])
def test_distorted_rays_roundtrip_with_rotated_optical_frame(count,quarter):
    from real2sim_builder.cameras import optical_rays,project_pixels
    k=np.array([[400.,0,160],[0,420,120],[0,0,1]])
    d=np.array([.1,-.025,.003,-.002,.001,0,0,0,.0002,0,-.0003,0,.01,-.01])[:count]
    theta=quarter*np.pi/2;r=np.array([[np.cos(theta),-np.sin(theta),0],[np.sin(theta),np.cos(theta),0],[0,0,1]])
    camera={'K':value(k.tolist(),'calibrated'),'distortion':value(d.tolist(),'calibrated'),
        'distortion_rotation':r.tolist(),'resolution':[320,240]}
    points=np.array([[.1,.2,1],[-.2,.1,1],[.25,-.18,1]])
    sensor=points@r;uv,_=cv2.projectPoints(sensor,np.zeros(3),np.zeros(3),np.eye(3),d)
    expected=np.c_[uv.reshape(-1,2),np.ones(3)]@r.T@k.T;expected=expected[:,:2]/expected[:,2:]
    original=copy.deepcopy(camera)
    assert np.allclose(project_pixels(camera,points),expected,atol=1e-8)
    assert np.allclose(optical_rays(camera,expected),points,atol=1e-8)
    assert camera==original


def test_native_rgb_mask_depth_share_distorted_pixel_grid(tmp_path):
    from test_builder_export import legacy_scene
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.cameras import distort_render
    from real2sim_builder.project import Project
    p=Project.create(tmp_path,'lens');scene=legacy_scene();original=copy.deepcopy(scene)
    with Renderer(scene,p.root,p.root/'scratch/lens')as renderer:
        rgb=renderer.rgb('side');mask=renderer.mask('side','block');depth=renderer.depth('side')
        distorted=copy.deepcopy(scene);cam=distorted['cameras'][0]
        cam['distortion']=value([.2,-.01,.01,-.02,0.],'calibrated')
        renderer.update_scene(distorted)
        assert np.array_equal(renderer.rgb('side'),distort_render(cam,rgb))
        assert np.array_equal(renderer.mask('side','block'),distort_render(cam,mask,nearest=True))
        assert np.allclose(renderer.depth('side'),distort_render(cam,depth,nearest=True),equal_nan=True)
    assert scene==original


def test_depth_cloud_retains_observed_distorted_pixels():
    from real2sim_builder.inference import object_points
    from real2sim_builder.cameras import project_pixels
    k=np.array([[30.,0,10],[0,30,10],[0,0,1]]);d=[.2,-.02,.01,-.01,0]
    points,_=object_points(np.ones((20,20)),np.ones((20,20)),k,np.eye(3),erode_px=0,distortion=d)
    camera={'K':value(k.tolist(),'calibrated'),'distortion':value(d,'calibrated')}
    y,x=np.indices((20,20));expected=np.c_[x.ravel(),y.ravel()]
    assert np.allclose(project_pixels(camera,points),expected,atol=1e-7)
    assert not np.allclose(points[:,:2],(expected-[10,10])/30)
