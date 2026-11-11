# Portions adapted from NVIDIA SimFoundry, Copyright (c) 2026 NVIDIA
# CORPORATION & AFFILIATES. Apache-2.0; see third_party/SIMFOUNDRY_NOTICE.md.
"""SimFoundry optical depth, overlap Sim(3), and support-frame mathematics.

Reference commit 9e34ebefcd020583fbb755a8b57268dce78eca26:
pipeline/depth_backends.py and A_reconstruction/stages/4_unify_world_frame.py.
No Camera/Robot calibration or real-world accuracy is inferred by these helpers.
"""
import numpy as np
from scipy.spatial.transform import Rotation


def backproject(depth, K):
    depth, K = np.asarray(depth, float), np.asarray(K, float)
    if depth.ndim != 2 or K.shape != (3, 3) or not np.isfinite(K).all():
        raise ValueError('Expected optical-Z Depth and processed-image K')
    if not np.isfinite(depth).all() or np.any(depth <= 0) or min(K[0, 0], K[1, 1]) <= 0:
        raise ValueError('Finite positive optical Depth/focal required')
    y, x = np.mgrid[:depth.shape[0], :depth.shape[1]]
    return depth[..., None] * (np.stack((x, y, np.ones_like(x)), -1) @ np.linalg.inv(K).T)


def world_points(depth, K, extrinsics):
    E = np.asarray(extrinsics, float)
    if E.shape not in ((3, 4), (4, 4)) or not np.isfinite(E).all():
        raise ValueError('Expected World-to-Camera extrinsics')
    r = E[:3, :3]
    if not np.allclose(r @ r.T, np.eye(3), atol=1e-4) or not np.isclose(np.linalg.det(r), 1, atol=1e-4):
        raise ValueError('Invalid Camera rotation')
    return (backproject(depth, K) - E[:3, 3]) @ r


def plan_chunks(n, chunk_size=4, overlap=3):
    if any(type(x) is not int or x < 1 for x in (n, chunk_size, overlap)):
        raise ValueError('Positive integer frame/chunk settings required')
    if n <= chunk_size:
        return [0], [n]
    if not 3 <= overlap < chunk_size:
        raise ValueError('Sim(3) requires >=3 overlap frames and overlap < chunk size')
    starts = list(range(0, n - chunk_size + 1, chunk_size - overlap))
    if starts[-1] + chunk_size < n:
        starts.append(n - chunk_size)
    return starts, [chunk_size] * len(starts)


def similarity(source, target):
    """Umeyama similarity; reject an unobservable line/point overlap."""
    p, q = np.asarray(source, float), np.asarray(target, float)
    if p.shape != q.shape or p.ndim != 2 or p.shape[1] != 3 or len(p) < 3:
        raise ValueError('At least three corresponding camera centers required')
    a, b = p - p.mean(0), q - q.mean(0)
    if not np.isfinite([a, b]).all() or min(np.linalg.matrix_rank(a), np.linalg.matrix_rank(b)) < 2:
        raise ValueError('NEEDS_MORE_DATA: degenerate overlap camera centers')
    u, s, vt = np.linalg.svd(b.T @ a / len(p))
    sign = np.eye(3)
    sign[-1, -1] = np.sign(np.linalg.det(u @ vt))
    r = u @ sign @ vt
    scale = float(np.sum(s * np.diag(sign)) / np.mean(np.sum(a*a, axis=1)))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid Sim(3) scale')
    t = q.mean(0) - scale * r @ p.mean(0)
    return scale, r, t


def merge_chunks(chunks, starts, sizes, count):
    """Keep overlap in the anchor world; scale new optical Z with the fitted Sim(3)."""
    keys = ('depth', 'conf', 'intrinsics', 'extrinsics', 'image')
    if not chunks or len(chunks) != len(starts) or len(starts) != len(sizes) or starts[0] != 0:
        raise ValueError('Invalid chunk plan')
    merged = {k: np.zeros((count, *np.asarray(chunks[0][k]).shape[1:]), dtype=np.asarray(chunks[0][k]).dtype) for k in keys}
    filled = np.zeros(count, bool)
    for k in keys:
        merged[k][:sizes[0]] = chunks[0][k]
    filled[:sizes[0]] = True
    reports = []
    for i, chunk in enumerate(chunks[1:], 1):
        start = starts[i]
        overlap = min(starts[i-1] + sizes[i-1], start + sizes[i]) - start
        if overlap < 3 or not filled[start:start+overlap].all():
            raise ValueError('Insufficient registered overlap for Sim(3)')
        def centers(ext):
            return np.array([-e[:3, :3].T @ e[:3, 3] for e in ext])
        p, q = centers(chunk['extrinsics'][:overlap]), centers(merged['extrinsics'][start:start+overlap])
        scale, r, t = similarity(p, q)
        residual = np.linalg.norm(scale*p @ r.T + t - q, axis=1)
        reports.append({'chunk': i, 'scale': scale, 'rotation': r.tolist(), 'translation': t.tolist(),
                        'overlap': overlap, 'camera_center_residual': residual.tolist(),
                        'metric_verified': False})
        for j in range(overlap, sizes[i]):
            g = start+j
            c2w = np.eye(4)
            c2w[:3] = chunk['extrinsics'][j]
            c2w = np.linalg.inv(c2w)
            c2w[:3, :3] = r @ c2w[:3, :3]
            c2w[:3, 3] = scale*r @ c2w[:3, 3] + t
            for k in keys:
                merged[k][g] = chunk[k][j]
            merged['extrinsics'][g] = np.linalg.inv(c2w)[:3]
            merged['depth'][g] = chunk['depth'][j]*scale
            filled[g] = True
    if not filled.all():
        raise ValueError('Chunk merge left missing frames')
    return merged, reports


def support_transform(normal, origin):
    """Original roll/tilt order R_tilt R_roll, then negative Camera-frame origin."""
    normal, origin = np.asarray(normal, float), np.asarray(origin, float)
    if normal.shape != (3,) or origin.shape != (3,) or not np.isfinite([normal, origin]).all() or not np.isclose(np.linalg.norm(normal), 1):
        raise ValueError('Finite unit normal and Camera-frame centroid required')
    roll = np.arctan2(normal[0], np.linalg.norm(normal[1:]))
    tilt = np.arctan2(normal[1], normal[2])
    r = Rotation.from_euler('xyz', [tilt, 0, 0]).as_matrix() @ Rotation.from_euler('xyz', [0, 0, -roll]).as_matrix()
    result = np.eye(4)
    result[:3, :3], result[:3, 3] = r, -r @ origin
    return result


def metric_qa(corners, measured_xy):
    """Compare explicitly identified full-boundary corners; never infer them from bounds."""
    corners, measured = np.asarray(corners, float), np.asarray(measured_xy, float)
    if corners.shape != (4, 3) or measured.shape != (2,) or not np.isfinite(corners).all() or not np.isfinite(measured).all() or np.any(measured <= 0):
        raise ValueError('Four observed corners and two positive measured dimensions required')
    edges = []
    for i in range(4):
        length = float(np.linalg.norm(corners[i] - corners[(i+1) % 4]))
        expected = float(measured[i % 2])
        edges.append({'edge': [i, (i+1) % 4], 'predicted_m': length, 'measured_m': expected,
                      'relative_error': abs(length-expected)/expected})
    return {'status': 'DIAGNOSTIC_ONLY', 'verified': False, 'edges': edges,
            'scale_applied': False, 'independent_accuracy': 'NOT_VERIFIED'}


def da3_pixel_affines(original_sizes, process_res, processed_size):
    """Installed DA3 upper_bound_resize, patch14 resize, batch center crop.

    The affine maps integer pixel centers, including cv2 resize half-pixel
    offsets. A common batch crop is distinct from changing the original aspect.
    Source: DA3 utils/io/input_processor.py, _process_one/_unify_batch_shapes.
    """
    width,height=processed_size;result=[]
    for ow,oh in original_sizes:
        if min(ow,oh,width,height,process_res)<=0:raise ValueError('Positive processed/original image dimensions required')
        scale=process_res/max(ow,oh)
        bw,bh=max(1,round(ow*scale)),max(1,round(oh*scale))
        def patch(x):
            down=(x//14)*14;up=down+14
            return max(1,up if abs(up-x)<=abs(x-down)else down)
        w,h=patch(bw),patch(bh)
        if width>w or height>h:raise ValueError('Unexpected DA3 processed output grid')
        cx,cy=(w-width)//2,(h-height)//2;sx,sy=w/ow,h/oh
        result.append([[sx,0,(sx-1)/2-cx],[0,sy,(sy-1)/2-cy],[0,0,1]])
    return result
