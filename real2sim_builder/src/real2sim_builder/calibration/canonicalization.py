# Portions (c) 2026 NVIDIA CORPORATION & AFFILIATES, Apache-2.0.
# Source SimFoundry @ 9e34ebefcd020583fbb755a8b57268dce78eca26; see third_party.
from __future__ import annotations

import numpy as np

# glTF convention, and what front_canonicalization's yaw renders assume.
MESH_UP = np.array([0.0, 1.0, 0.0])

# Backends that generate in the conditioning camera's frame; only their meshes carry a
# generation tilt worth baking. Canonical-frame backends (hunyuan, trellis2, direct3d)
# are upright by construction, so a fitted tilt there is a fit error or the object's
# physical placement — baking either corrupts the mesh.
PIXEL_ALIGNED_SHAPE_MODELS = ("pixal3d",)


def resolve_bake_fitted_tilt(mode, shape_model):
    """Bool passthrough; "auto" bakes only for pixel-aligned shape backends."""
    if isinstance(mode, bool):
        return mode
    return str(shape_model) in PIXEL_ALIGNED_SHAPE_MODELS


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError("zero-length direction vector")
    return v / n


def rotation_between(v_from, v_to):
    """Minimal 3x3 rotation taking direction `v_from` onto direction `v_to`."""
    a, b = _unit(v_from), _unit(v_to)
    c = float(np.clip(a @ b, -1.0, 1.0))
    axis = np.cross(a, b)
    s = float(np.linalg.norm(axis))
    if s < 1e-12:
        if c > 0.0:
            return np.eye(3)
        # Antiparallel: rotate 180 degrees about any axis perpendicular to `a`.
        helper = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = _unit(np.cross(a, helper))
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    axis = axis / s
    angle = np.arctan2(s, c)
    K = np.array([
        [0.0, -axis[2], axis[1]],
        [axis[2], 0.0, -axis[0]],
        [-axis[1], axis[0], 0.0],
    ])
    return np.eye(3) + np.sin(angle) * K + (1.0 - np.cos(angle)) * (K @ K)


def up_in_mesh_frame(rot_fit, gravity_up):
    """Direction in mesh coordinates that `rot_fit` sends onto the scene's gravity axis.

    `rot_fit` maps mesh points into the frame of the fitted point cloud;
    `gravity_up` is the scene's up axis expressed in that same frame.
    """
    return _unit(np.asarray(rot_fit, dtype=float).T @ _unit(gravity_up))


def tilt_from_fit(rot_fit, gravity_up, mesh_up=MESH_UP):
    """(tilt_deg, rot_tilt) implied by a fitted pose.

    `rot_tilt @ mesh` is upright (its `mesh_up` is the object's true up), and the
    adjusted pose `rot_fit @ rot_tilt.T` sends `mesh_up` exactly onto `gravity_up`,
    so the residual rotation in the stored pose is pure gravity yaw.
    """
    v = up_in_mesh_frame(rot_fit, gravity_up)
    mesh_up = _unit(mesh_up)
    tilt_deg = float(np.degrees(np.arccos(np.clip(v @ mesh_up, -1.0, 1.0))))
    return tilt_deg, rotation_between(v, mesh_up)


def up_axis_spread_deg(rots, gravity_up):
    """Largest pairwise angle (deg) between the up axes implied by candidate fits.

    A consensus gate: independent CPD restarts that agree on where the object's up
    lies can be trusted; wildly disagreeing fits mean the registration is unreliable
    and no tilt should be baked from it.
    """
    ups = [up_in_mesh_frame(r, gravity_up) for r in rots]
    worst = 0.0
    for i in range(len(ups)):
        for j in range(i + 1, len(ups)):
            ang = float(np.degrees(np.arccos(np.clip(ups[i] @ ups[j], -1.0, 1.0))))
            worst = max(worst, ang)
    return worst


def decide_tilt(info_sorted, gravity_up, *, min_tilt_deg, max_tilt_deg, consensus_deg,
                consensus_top_k=3, mesh_up=MESH_UP):
    """Gatekeeping for tilt baking. Returns (rot_tilt or None, info dict).

    `info_sorted` is stage 8's fit list, best first; each entry's ``tf_z_up.rot`` maps
    mesh points into the target-cloud frame. None = leave the mesh as-is.
    """
    best_rot = info_sorted[0]["tf_z_up"].rot
    tilt_deg, rot_tilt = tilt_from_fit(best_rot, gravity_up, mesh_up=mesh_up)
    spread = up_axis_spread_deg(
        [e["tf_z_up"].rot for e in info_sorted[:consensus_top_k]], gravity_up,
    ) if len(info_sorted) > 1 else 0.0
    info = {
        "tilt_deg": tilt_deg,
        "consensus_spread_deg": spread,
        "applied_tilt_deg": 0.0,
        "status": "unknown",
    }
    if tilt_deg < min_tilt_deg:
        info["status"] = "below_threshold"
        return None, info
    if tilt_deg > max_tilt_deg:
        info["status"] = "implausible_tilt"
        return None, info
    if spread > consensus_deg:
        info["status"] = "inconsistent_fits"
        return None, info
    info["applied_tilt_deg"] = tilt_deg
    info["status"] = "baked"
    return rot_tilt, info

import logging
from types import SimpleNamespace
logger=logging.getLogger(__name__)
FRONT_TARGET_AZIMUTH_DEG=90

def yaw_to_target_rotation(front_azimuth_deg, target_azimuth_deg=FRONT_TARGET_AZIMUTH_DEG):
    """3x3 rotation about +Y mapping the front azimuth onto the target azimuth."""
    alpha = np.deg2rad(front_azimuth_deg - target_azimuth_deg)
    (c, s) = (np.cos(alpha), np.sin(alpha))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])

def applied_yaw_deg(front_azimuth_deg, target_azimuth_deg=FRONT_TARGET_AZIMUTH_DEG):
    return float((front_azimuth_deg - target_azimuth_deg + 180) % 360 - 180)

def yaw_rotation(yaw_deg):
    """3x3 rotation about +Y by `yaw_deg` (same convention as yaw_to_target_rotation)."""
    a = np.deg2rad(yaw_deg)
    (c, s) = (np.cos(a), np.sin(a))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])

def yaw_snap_to_axes(vertices, min_rectangularity=0.8):
    """Snap residual yaw so the mesh footprint's min-area rectangle aligns with x/z.

    The VLM passes decide WHICH face is the front (a semantic question); the precise
    angle is geometry's job — VLM picks plateau at their render granularity, leaving
    10-20 degrees of visible yaw on pixel-aligned meshes. The correction is bounded to
    (-45, 45] degrees so the semantic front choice is preserved, and it is skipped for
    footprints that are not box-like (rectangularity = hull area / min-rect area; a
    circle scores pi/4 ~ 0.785, where the rectangle's angle is meaningless).

    Expects an already-upright mesh (+Y up). Returns (rotation_3x3 or None, info).
    Never raises.
    """
    info = {'snap_yaw_deg': 0.0, 'rectangularity': None, 'status': 'unknown'}
    try:
        from scipy.spatial import ConvexHull
        pts = np.asarray(vertices, dtype=float)[:, [0, 2]]
        hull = ConvexHull(pts)
        hp = pts[hull.vertices]
        edges = np.diff(np.vstack([hp, hp[:1]]), axis=0)
        angles = np.unique(np.arctan2(edges[:, 1], edges[:, 0]) % (np.pi / 2))
        (best_area, best_angle) = (np.inf, 0.0)
        for ang in angles:
            (c, s) = (np.cos(ang), np.sin(ang))
            q = hp @ np.array([[c, -s], [s, c]])
            area = float(np.ptp(q[:, 0]) * np.ptp(q[:, 1]))
            if area < best_area:
                (best_area, best_angle) = (area, float(ang))
        info['rectangularity'] = float(hull.volume / best_area)
    except Exception as exc:
        logger.warning('Yaw snap failed (%s); leaving yaw as-is.', exc)
        info['status'] = f'error: {exc}'
        return (None, info)
    if info['rectangularity'] < min_rectangularity:
        info['status'] = 'not_boxy'
        return (None, info)
    theta = (best_angle + np.pi / 4) % (np.pi / 2) - np.pi / 4
    snap_deg = float(np.degrees(theta))
    info['snap_yaw_deg'] = snap_deg
    info['status'] = 'snapped'
    return (yaw_rotation(snap_deg), info)

# Proper rotation: Native +Z up -> source +Y up (no reflection).
NATIVE_TO_SOURCE=np.array([[1.,0,0],[0,0,1],[0,-1,0]])

def native_tilt(rotations,gravity_up,*,enabled='auto',shape_model='codex_blender',min_tilt_deg=10.,max_tilt_deg=80.,consensus_deg=20.):
    if not resolve_bake_fitted_tilt(enabled,shape_model):return np.eye(3),{'status':'canonical_backend','applied_tilt_deg':0.}
    info_sorted=[{'tf_z_up':SimpleNamespace(rot=np.asarray(r))}for r in rotations]
    rotation,info=decide_tilt(info_sorted,gravity_up,min_tilt_deg=min_tilt_deg,max_tilt_deg=max_tilt_deg,consensus_deg=consensus_deg,mesh_up=np.array([0.,0,1.]))
    return(np.eye(3)if rotation is None else rotation),info

def native_yaw_snap(vertices):
    rotation,info=yaw_snap_to_axes(np.asarray(vertices)@NATIVE_TO_SOURCE.T)
    return(np.eye(3)if rotation is None else NATIVE_TO_SOURCE.T@rotation@NATIVE_TO_SOURCE),info
