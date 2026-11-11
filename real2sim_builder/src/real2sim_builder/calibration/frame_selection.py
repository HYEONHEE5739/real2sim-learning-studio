# Adapted from NVIDIA SimFoundry (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# Apache-2.0; see ../../../../third_party/SIMFOUNDRY_NOTICE.md.
# Source: simfoundry/pipeline/frame_selection.py @ 9e34ebefcd020583fbb755a8b57268dce78eca26
from dataclasses import dataclass, field
from typing import Sequence, Any
import os
import numpy as np


DEFAULT_SELECTION_CFG = {
    "mode": "hybrid",
    "max_candidates": 24,
    "min_object_height": 0.015,
    "max_object_height": 0.6,
    "min_component_px": 50,
    "max_tilt": None,             # None -> inherit s3_ground.floor_tilt_threshold
    "min_plane_inlier_ratio": 0.6,
    "min_support_coverage": 0.05,
    "max_clipped_frac": 0.5,
    "clipped_penalty": 0.35,
    "vlm_top_k": 4,
    "vlm_max_side": 1024,
    "vlm_model": None,            # None -> inherit s3_ground.detection_model
    "write_debug_sheet": True,
    "weights": {
        "object_coverage": 0.40,
        "object_separation": 0.20,
        "sharpness": 0.20,
        "support_coverage": 0.10,
        "plane_quality": 0.10,
    },
}

@dataclass
class FrameScore:
    """Per-candidate metrics and the score they combine into."""

    idx: int
    eligible: bool = True
    reject_reason: str | None = None
    floor_category: str | None = None
    floor_logit: float = 0.0
    tilt: float = float("nan")
    plane_inlier_ratio: float = 0.0
    support_coverage: float = 0.0
    object_coverage: float = 0.0
    smallest_object: float = 0.0
    n_objects: int = 0
    clipped_frac: float = 0.0
    sharpness: float = 0.0
    score: float = 0.0
    terms: dict[str, float] = field(default_factory=dict)

def _object_mask_above_plane(points_flat, normal, d, shape, valid, sel_cfg, plane_points):
    """Pixels holding geometry that rests on the support plane.

    Restricted to the plane's own footprint (the convex hull of its inliers, taken in plane
    coordinates) so background walls, chairs and floor never count as tabletop objects.
    """
    from scipy.spatial import ConvexHull, Delaunay, QhullError

    heights = points_flat @ normal + d

    e1 = np.cross(normal, np.array([0.0, 0.0, 1.0]))
    norm_e1 = np.linalg.norm(e1)
    if norm_e1 < 1e-8:
        e1 = np.cross(normal, np.array([0.0, 1.0, 0.0]))
        norm_e1 = np.linalg.norm(e1)
    e1 = e1 / norm_e1
    e2 = np.cross(normal, e1)

    hull_uv = np.stack([plane_points @ e1, plane_points @ e2], axis=-1)
    try:
        hull = Delaunay(hull_uv[ConvexHull(hull_uv).vertices])
    except (QhullError, ValueError):
        return None
    all_uv = np.stack([points_flat @ e1, points_flat @ e2], axis=-1)
    inside_footprint = hull.find_simplex(all_uv) >= 0

    above = (heights > sel_cfg["min_object_height"]) & (heights < sel_cfg["max_object_height"])
    return (valid & inside_footprint & above).reshape(shape)

def _sharpness(source_fpath: str | None, rgb: np.ndarray, object_mask: np.ndarray) -> float:
    """Laplacian variance around the objects, measured on the image stage 5 will crop from."""
    import cv2

    if source_fpath is not None and os.path.isfile(source_fpath):
        gray = cv2.cvtColor(cv2.imread(source_fpath), cv2.COLOR_BGR2GRAY)
    else:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    h, w = gray.shape
    region = cv2.resize(object_mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
    # Dilate so object silhouettes -- the edges where blur shows up most clearly -- are included.
    k = max(3, (min(h, w) // 60) | 1)
    region = cv2.dilate(region, np.ones((k, k), np.uint8)).astype(bool)

    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    if region.sum() < 100:
        return float(laplacian.var())
    return float(laplacian[region].var())

def _normalize(values: Sequence[float]) -> list[float]:
    """Min-max to [0, 1]; an all-equal metric contributes nothing to the ranking."""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]

def rank_frames(scores: Sequence[FrameScore], sel_cfg: dict[str, Any]) -> list[FrameScore]:
    """Assign each eligible frame a combined score, best first.

    Metrics are normalized across the eligible candidates rather than against absolute
    thresholds, because what counts as "close enough" or "sharp enough" depends entirely on
    how the capture was shot.
    """
    eligible = [s for s in scores if s.eligible]
    if not eligible:
        return []

    weights = sel_cfg["weights"]
    metrics = {
        "object_coverage": _normalize([s.object_coverage for s in eligible]),
        "object_separation": _normalize([float(s.n_objects) for s in eligible]),
        "sharpness": _normalize([s.sharpness for s in eligible]),
        "support_coverage": _normalize([s.support_coverage for s in eligible]),
        "plane_quality": _normalize([s.plane_inlier_ratio for s in eligible]),
    }
    for i, s in enumerate(eligible):
        s.terms = {name: round(float(values[i]), 4) for name, values in metrics.items()}
        total = sum(weights.get(name, 0.0) * values[i] for name, values in metrics.items())
        total -= sel_cfg["clipped_penalty"] * s.clipped_frac
        s.score = float(total)
    return sorted(eligible, key=lambda s: s.score, reverse=True)
