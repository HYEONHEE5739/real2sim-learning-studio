"""Existing Builder cameras responsibilities; authoring schemas unchanged."""
import numpy as np
from .scene import world_pose


OPTICAL_TO_RENDER = np.diag([1.0, -1.0, -1.0, 1.0])


CLIP = (0.001, 1000.0)


CONVENTIONS = {'canonical': '+X right, +Y down, +Z forward', 'render': '+X right, +Y up, -Z forward', 'conversion': OPTICAL_TO_RENDER.tolist(), 'clip_m': list(CLIP)}


def render_pose(scene, camera):
    return world_pose(scene, camera) @ OPTICAL_TO_RENDER


def blender_intrinsics(camera):
    k = np.asarray(camera['K']['value'], float)
    w, h = camera['resolution']
    ratio = k[0, 0] / k[1, 1]
    return {'sensor_fit': 'HORIZONTAL', 'sensor_width': 36.0, 'lens': float(k[0, 0] * 36 / w), 'shift_x': float((w / 2 - k[0, 2]) / w), 'shift_y': float((k[1, 2] - h / 2) * ratio / w), 'pixel_aspect_x': 1.0, 'pixel_aspect_y': float(ratio)}



def camera_pixels(camera,image):
    """Shared sensor pixels -> upright image pixels and optical axes.

    EXIF rotation is explicit; a crop needs its recorded affine. Scaling alone
    never silently explains an unknown aspect-ratio/lens change.
    """
    w,h=camera['resolution'];iw,ih=image['resolution']
    orientation={1:0,6:1,3:2,8:3}
    old=camera.get('reference_orientation',1);new=image.get('exif_orientation',old)
    if old not in orientation or new not in orientation:raise ValueError('Mirrored EXIF views require explicit unmirrored RGB')
    quarter=(orientation[new]-orientation[old])%4
    affines=[np.eye(3),np.array([[0,-1,h-1],[1,0,0],[0,0,1]]),np.array([[-1,0,w-1],[0,-1,h-1],[0,0,1]]),np.array([[0,1,0],[-1,0,w-1],[0,0,1]])]
    rotations=[np.eye(3),np.array([[0,-1,0],[1,0,0],[0,0,1]]),np.diag([-1,-1,1]),np.array([[0,1,0],[-1,0,0],[0,0,1]])]
    rw,rh=(h,w)if quarter%2 else(w,h)
    if image.get('pixel_from_camera')is not None:
        matrix=np.asarray(image['pixel_from_camera'],float)
        if matrix.shape!=(3,3)or not np.isfinite(matrix).all()or not np.allclose(matrix[2],[0,0,1])or min(matrix[0,0],matrix[1,1])<=0 or matrix[0,1]!=0 or matrix[1,0]!=0:
            raise ValueError('Resize/crop needs a finite axis-aligned pixel affine')
    else:
        if not np.isclose(iw/rw,ih/rh,rtol=.005):raise ValueError('Unknown crop or lens orientation: supply original upright RGB or its crop transform')
        matrix=np.diag([iw/rw,ih/rh,1.])
    return matrix@affines[quarter],rotations[quarter]


def optical_rays(camera,pixels):
    """Observed OpenCV pinhole pixels -> undistorted optical rays, z=1.

    EXIF rotates optical axes, not the original lens coefficients. The runtime
    observation carries that rotation while the stored Calibration stays intact.
    https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html
    """
    import cv2
    pixels=np.asarray(pixels,float).reshape(-1,2)
    if not np.isfinite(pixels).all():raise ValueError('Finite pixel coordinates required')
    k=np.asarray(camera['K']['value'],float);d=np.asarray(camera['distortion']['value'],float)
    rays=np.linalg.solve(k,np.c_[pixels,np.ones(len(pixels))].T).T
    if not d.any():return rays
    rotation=np.asarray(camera.get('distortion_rotation',np.eye(3)),float)
    sensor=rays@rotation;sensor=sensor[:,:2]/sensor[:,2:]
    clean=cv2.undistortPointsIter(sensor.reshape(-1,1,2),np.eye(3),d,None,None,
        (cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,40,1e-12)).reshape(-1,2)
    result=np.c_[clean,np.ones(len(clean))]@rotation.T
    if not np.isfinite(result).all():raise ValueError('Lens inversion produced invalid rays')
    return result/result[:,2:]


def project_pixels(camera,points):
    """Optical points -> original observed pixels, retaining lens distortion."""
    import cv2
    points=np.asarray(points,float).reshape(-1,3);k=np.asarray(camera['K']['value'],float)
    d=np.asarray(camera['distortion']['value'],float)
    if not d.any():pixels=points@k.T;return pixels[:,:2]/pixels[:,2:]
    rotation=np.asarray(camera.get('distortion_rotation',np.eye(3)),float)
    pixels,_=cv2.projectPoints(points@rotation,np.zeros(3),np.zeros(3),np.eye(3),d)
    projected=np.c_[pixels.reshape(-1,2),np.ones(len(points))]@rotation.T@k.T
    return projected[:,:2]/projected[:,2:]


from functools import lru_cache


@lru_cache(maxsize=8)
def _distortion_map(width,height,k,distortion,rotation):
    camera={'K':{'value':np.asarray(k).reshape(3,3)},'distortion':{'value':distortion},
            'distortion_rotation':np.asarray(rotation).reshape(3,3)}
    y,x=np.indices((height,width));rays=optical_rays(camera,np.c_[x.ravel(),y.ravel()])
    pinhole=rays@np.asarray(k).reshape(3,3).T
    pixels=(pinhole[:,:2]/pinhole[:,2:]).reshape(height,width,2).astype(np.float32)
    return pixels[:,:,0],pixels[:,:,1]


def distort_render(camera,pixels,*,nearest=False):
    """Resample a pinhole render onto the observed lens grid; no second render.

    Labels and optical-Z depth use nearest neighbours to avoid mixing surfaces.
    Outside the native field of view is zero/invalid, never extrapolated geometry.
    """
    import cv2
    d=camera['distortion']['value']
    if not any(d):return pixels
    w,h=camera['resolution']
    maps=_distortion_map(w,h,tuple(np.asarray(camera['K']['value']).ravel()),tuple(d),
        tuple(np.asarray(camera.get('distortion_rotation',np.eye(3))).ravel()))
    boolean=pixels.dtype==bool
    result=cv2.remap(pixels.astype(np.uint8)if boolean else pixels,*maps,
        interpolation=cv2.INTER_NEAREST if nearest else cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    return result.astype(bool)if boolean else result
