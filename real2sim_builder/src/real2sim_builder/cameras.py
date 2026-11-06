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
