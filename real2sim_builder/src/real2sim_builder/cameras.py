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

