# Portions adapted from NVIDIA SimFoundry (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# Apache-2.0; see real2sim_builder/third_party/SIMFOUNDRY_NOTICE.md.
# Original sam_v3.py / Stage5 @ 9e34ebefcd020583fbb755a8b57268dce78eca26.
"""Pure original Mask math and observation identity; no model initialization."""
from copy import deepcopy
from typing import Protocol, runtime_checkable
import numpy as np

@runtime_checkable
class TextEncoder(Protocol):
    def get_text_features(self,text): ...
    def get_similarity_matrix(self,a,b): ...

def create_polygon_from_vertices(vertices):
    """
    Create a valid Polygon from a list of vertices projected onto the x-y plane.

    Args:
        vertices (list of tuples): A list of tuples representing the projected points on the x-y plane.

    Returns:
        None or Polygon: A Shapely Polygon object created from the vertices, or None if a valid polygon cannot be formed.
    """
    from shapely.geometry import Polygon, MultiPoint
    unique_points = np.unique(vertices, axis=0)
    if len(unique_points) == 4:
        center = np.mean(unique_points, axis=0)
        angles = np.arctan2(unique_points[:, 1] - center[1], unique_points[:, 0] - center[0])
        sorted_points = unique_points[np.argsort(angles)]
        return Polygon(sorted_points)
    if len(unique_points) > 4:
        convex_hull = MultiPoint(unique_points).convex_hull
        if isinstance(convex_hull, Polygon):
            return convex_hull
        else:
            raise AssertionError('Convex Hull Creation Fail')
    raise AssertionError('Not enough points for a polygon')

def mask_area(mask):return np.sum(mask)
def mask_intersection_area(a,b):return np.sum(a&b)

def prune_redundant_masks(masks, boxes_xyxy, logits, phrases, polygon_relative_intersection_threshold=0.97, polygon_relative_area_threshold=0.9, obj_mask_intersect_area_threshold=0.9, duplicate_mask_intersect_area_threshold=0.95, boundary_proportion=None, text_encoder=None, text_encoder_similarity_threshold=0.85, verbose=False):
    from skimage import morphology
    H, W = masks[0].shape
    idxs_to_remove = dict()
    susp_small_large_box_idxs = set()
    for i, (box_a, phrase_a) in enumerate(zip(boxes_xyxy, phrases)):
        lower_a_x, lower_a_y, upper_a_x, upper_a_y = box_a
        polygon_a = create_polygon_from_vertices([(lower_a_x, lower_a_y), (upper_a_x, lower_a_y), (upper_a_x, upper_a_y), (lower_a_x, upper_a_y)])
        for j, (box_b, phrase_b) in enumerate(zip(boxes_xyxy, phrases)):
            if i == j:
                continue
            elif phrase_a in phrase_b or phrase_b in phrase_a:
                lower_b_x, lower_b_y, upper_b_x, upper_b_y = box_b
                polygon_b = create_polygon_from_vertices([(lower_b_x, lower_b_y), (upper_b_x, lower_b_y), (upper_b_x, upper_b_y), (lower_b_x, upper_b_y)])
                if polygon_a.intersects(polygon_b):
                    intersect_area = polygon_a.intersection(polygon_b).area
                    if intersect_area / polygon_a.area >= polygon_relative_intersection_threshold or intersect_area / polygon_b.area >= polygon_relative_intersection_threshold:
                        if polygon_a.area < polygon_b.area:
                            if polygon_a.area < polygon_relative_area_threshold * polygon_b.area:
                                susp_small_large_box_idxs.add((i, j))
                            elif i not in idxs_to_remove:
                                idxs_to_remove[i] = 'box_xyxy overlap'
                        elif polygon_b.area < polygon_relative_area_threshold * polygon_a.area:
                            susp_small_large_box_idxs.add((j, i))
                        elif j not in idxs_to_remove:
                            idxs_to_remove[j] = 'box_xyxy overlap'
    for i, (smaller_idx, larger_idx) in enumerate(susp_small_large_box_idxs):
        for j, (smaller_idx_2, larger_idx_2) in enumerate(susp_small_large_box_idxs):
            if i == j:
                continue
            if larger_idx == larger_idx_2:
                if larger_idx not in idxs_to_remove:
                    idxs_to_remove[larger_idx] = 'large bbox overlapping multiple small bbox'
                break
    for i, mask in enumerate(masks):
        masks[i] = morphology.remove_small_objects(mask, min_size=int(np.sqrt(W * H) / 10.0), connectivity=1)
    mask_areas = [mask_area(mask) for mask in masks]
    for i, (mask_a, mask_area_a, phrase_a, logit_a) in enumerate(zip(masks, mask_areas, phrases, logits)):
        if i in idxs_to_remove:
            continue
        for j, (mask_b, mask_area_b, phrase_b, logit_b) in enumerate(zip(masks, mask_areas, phrases, logits)):
            if i == j or j in idxs_to_remove or i in idxs_to_remove:
                continue
            inter_area = mask_intersection_area(mask_a, mask_b)
            if inter_area / mask_area_a >= duplicate_mask_intersect_area_threshold and inter_area / mask_area_b >= duplicate_mask_intersect_area_threshold:
                idx_to_remove = i if logit_a < logit_b else j
                idxs_to_remove[idx_to_remove] = 'duplicate mask with same pixels'
                continue
            if text_encoder is not None:
                assert isinstance(text_encoder, TextEncoder)
                text_features = text_encoder.get_text_features([phrase_a, phrase_b])
                cos_sim = text_encoder.get_similarity_matrix(text_features, text_features)[0, 1]
                if cos_sim < text_encoder_similarity_threshold:
                    continue
                print(f'Detected similar phrases [{phrase_a} // {phrase_b}], checking for mask overlap...')
            min_area = min(mask_area_a, mask_area_b)
            if inter_area > obj_mask_intersect_area_threshold * min_area:
                if mask_area_a > mask_area_b:
                    print(f'Pruning {phrase_b} because of sufficient overlap')
                    if j not in idxs_to_remove:
                        idxs_to_remove[j] = 'mask pixels proportion overlap'
                        continue
                else:
                    print(f'Pruning {phrase_a} because of sufficient overlap')
                    if i not in idxs_to_remove:
                        idxs_to_remove[i] = 'mask pixels proportion overlap'
                        continue
                    break
    if boundary_proportion is not None:
        for i, mask in enumerate(masks):
            h_idxs, w_idxs = np.where(mask)
            if np.any((h_idxs < H * boundary_proportion) | (h_idxs > H * (1 - boundary_proportion)) | (w_idxs < W * boundary_proportion) | (w_idxs > W * (1 - boundary_proportion))):
                if i not in idxs_to_remove:
                    idxs_to_remove[i] = 'near image boundary'
    pruned_masks = deepcopy(masks)
    pruned_boxes_xyxy = deepcopy(boxes_xyxy)
    pruned_logits = deepcopy(logits)
    pruned_phrases = deepcopy(phrases)
    for idx in sorted(idxs_to_remove.keys(), reverse=True):
        reason = idxs_to_remove[idx]
        pruned_boxes_xyxy = np.concatenate((pruned_boxes_xyxy[:idx], pruned_boxes_xyxy[idx + 1:]))
        pruned_logits = np.concatenate((pruned_logits[:idx], pruned_logits[idx + 1:]))
        del pruned_masks[idx]
        if verbose:
            print(f'remove idx:{idx} phrase:{phrases[idx]}, reason: {reason}')
        del pruned_phrases[idx]
    if verbose:
        print(f'idxs to remove: {idxs_to_remove}')
    return (pruned_masks, pruned_boxes_xyxy, pruned_logits, pruned_phrases)

def prune_masks_below_surface(masks, boxes_xyxy, logits, phrases, pc, valid_mask=None, z_threshold=0.0, z_threshold_proportion=0.1, verbose=False):
    pruned_masks = deepcopy(masks)
    pruned_boxes_xyxy = deepcopy(boxes_xyxy)
    pruned_logits = deepcopy(logits)
    pruned_phrases = deepcopy(phrases)
    idxs_to_remove = set()
    for idx, mask in enumerate(masks):
        valid_pixels = mask & valid_mask if valid_mask is not None else mask
        valid_points = pc[valid_pixels].reshape(-1, 3)
        if np.sum(valid_points[:, 2] < z_threshold) / len(valid_points) > z_threshold_proportion:
            idxs_to_remove.add(idx)
    for idx in sorted(idxs_to_remove, reverse=True):
        pruned_boxes_xyxy = np.concatenate((pruned_boxes_xyxy[:idx], pruned_boxes_xyxy[idx + 1:]))
        pruned_logits = np.concatenate((pruned_logits[:idx], pruned_logits[idx + 1:]))
        del pruned_masks[idx]
        if verbose:
            print(f'below surface remove idx:{idx} phrase:{phrases[idx]}')
        del pruned_phrases[idx]
    return (pruned_masks, pruned_boxes_xyxy, pruned_logits, pruned_phrases)

def disentangle_masks(masks, phrases, overlap_threshold_proportion=0.9, verbose=False):
    if len(masks) < 2:
        return masks
    keep_masks = [np.ones_like(masks[0]) for _ in range(len(masks))]
    for i, (mask_a, phrase_a) in enumerate(zip(masks, phrases)):
        assert mask_a.dtype == bool
        n_mask_pixels = mask_a.sum()
        for j, (mask_b, phrase_b) in enumerate(zip(masks, phrases)):
            if i == j:
                continue
            if np.sum(mask_a & mask_b) / n_mask_pixels > overlap_threshold_proportion:
                if verbose:
                    print(f'Mask from {phrase_a} is subsumed by mask from {phrase_b}. Removing mask pixels from {phrase_b}.')
                keep_masks[j] &= ~mask_a
    updated_masks = [mask & keep_mask for mask, keep_mask in zip(masks, keep_masks)]
    return updated_masks

def get_primary_object_name(name: str) -> str:
    """
    Return the first segment of a slash-delimited object description.
    """
    if not isinstance(name, str):
        return name
    return name.split(' / ')[0].strip()

def choose_prompt_point_from_bbox(target_bbox, other_bboxes, img_w: int, img_h: int):
    """
    Pick a robust point inside target bbox that avoids overlapping bboxes when possible.
    Falls back to bbox center if no collision-free point is found.
    """
    x1, y1, x2, y2 = [float(v) for v in target_bbox]
    x1, x2 = (min(x1, x2), max(x1, x2))
    y1, y2 = (min(y1, y2), max(y1, y2))

    def _inside_box(px, py, box):
        bx1, by1, bx2, by2 = [float(v) for v in box]
        bx1, bx2 = (min(bx1, bx2), max(bx1, bx2))
        by1, by2 = (min(by1, by2), max(by1, by2))
        return bx1 <= px <= bx2 and by1 <= py <= by2

    def _same_box(a, b, eps=1.0):
        ax1, ay1, ax2, ay2 = [float(v) for v in a]
        bx1, by1, bx2, by2 = [float(v) for v in b]
        return abs(ax1 - bx1) <= eps and abs(ay1 - by1) <= eps and (abs(ax2 - bx2) <= eps) and (abs(ay2 - by2) <= eps)

    def _is_collision_free(px, py):
        for box in other_bboxes:
            if _same_box(target_bbox, box):
                continue
            if _inside_box(px, py, box):
                return False
        return True
    candidate_fracs = [(0.35, 0.5), (0.65, 0.5), (0.5, 0.35), (0.5, 0.65), (0.35, 0.35), (0.65, 0.35), (0.35, 0.65), (0.65, 0.65), (0.2, 0.5), (0.8, 0.5), (0.5, 0.2), (0.5, 0.8), (0.5, 0.5)]
    for fx, fy in candidate_fracs:
        px = int(np.clip(np.round(x1 + fx * (x2 - x1)), 0, img_w - 1))
        py = int(np.clip(np.round(y1 + fy * (y2 - y1)), 0, img_h - 1))
        if _is_collision_free(px, py):
            return ((px, py), {'fallback_to_center': False})
    cx = int(np.clip(np.round((x1 + x2) / 2.0), 0, img_w - 1))
    cy = int(np.clip(np.round((y1 + y2) / 2.0), 0, img_h - 1))
    return ((cx, cy), {'fallback_to_center': True})


def associate_masks(objects, boxes):
    """Match observations to stable IDs; reject missing/tied pixel evidence."""
    from scipy.optimize import linear_sum_assignment
    a=np.asarray([o['box_xyxy']for o in objects],float);b=np.asarray(boxes,float)
    if len(a)!=len(b)or len(a)==0:raise ValueError('AMBIGUOUS: instance/mask counts disagree')
    lo=np.maximum(a[:,None,:2],b[None,:,:2]);hi=np.minimum(a[:,None,2:],b[None,:,2:])
    overlap=np.maximum(hi-lo,0).prod(-1)
    union=np.prod(a[:,2:]-a[:,:2],-1)[:,None]+np.prod(b[:,2:]-b[:,:2],-1)[None,:]-overlap
    score=overlap/np.maximum(union,1e-12);rows,cols=linear_sum_assignment(-score)
    best=float(score[rows,cols].sum())
    if np.any(score[rows,cols]<=0):raise ValueError('AMBIGUOUS: no overlapping instance evidence')
    # An equally good complete assignment cannot establish Object identity.
    for row,col in zip(rows,cols):
        other=score.copy();other[row,col]=-1e6;r,c=linear_sum_assignment(-other)
        if best-float(other[r,c].sum())<=1e-9:raise ValueError('AMBIGUOUS: tied instance association')
    return {objects[i]['id']:int(j)for i,j in zip(rows,cols)}


def removal_region(mask):
    """The retained five-pixel support for both synthesized RGB and optical Z."""
    import cv2
    mask=np.asarray(mask,bool)
    if mask.ndim!=2 or not mask.any():raise ValueError('Nonempty removal Mask required')
    return cv2.dilate(mask.astype('uint8'),np.ones((3,3),np.uint8),iterations=5).astype(bool)


def removal_annotation(rgb,mask,mode):
    import cv2
    result=np.array(rgb,copy=True);mask=np.asarray(mask,bool);scale=np.sqrt(mask.size)
    thickness=max(1,int(np.ceil(scale/500)))
    contours,_=cv2.findContours(mask.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if mode=='bbox':
        y,x=np.where(mask);cv2.rectangle(result,(int(x.min()),int(y.min())),(int(x.max()),int(y.max())),(0,255,0),max(1,round(scale/400)))
    elif mode in('mask','outline'):
        cv2.drawContours(result,contours,-1,(0,255,0),thickness)
        if mode=='mask':result[cv2.dilate(mask.astype('uint8'),np.ones((3,3),np.uint8),iterations=5)>0]=[0,255,0]
    else:raise ValueError('Unknown source removal annotation')
    green=np.all(result==[0,255,0],axis=-1)
    check=cv2.dilate(green.astype('uint8'),np.ones((5,5),np.uint8),iterations=4)>0
    return result,check


def removal_is_valid(rgb,check):
    # Original get_num_pixels_with_color tolerance=50 and sqrt(H*W)*0.33.
    green=np.all(np.isclose(rgb,np.array([0,255,0]).reshape(1,1,3),atol=50),axis=-1)
    return bool(np.sum(green&check)<=np.sqrt(check.size)*.33)


# Denoising portions: Copyright (c) 2024 ACDC authors (Stanford Vision and Learning Lab),
# NVIDIA modifications (c) 2026; Apache-2.0, same source revision as above.
def denoise_obj_point_cloud_v2(
        pcd_obj,
        visualize_process=False,
        visualize_result=False,
        target_density_cm2=5.0,
        outlier_removal_n_neighbors=None,
        outlier_removal_std_ratio=1.0,
        dbscan_eps=None,
        dbscan_min_pts=None,
        cluster_proportion_threshold=0.05,
):
    """
    Removes noise from object point by a set of point cloud denoising methods.
    Default values for arguments are tuned for resized images with longer side equals 1600 pixels.

    Args:
        pcd_obj (open3d.geometry.PointCloud): Object point cloud.
        visualize_process (bool): Whether to visualize the denoising process
        visualize_result (bool): Whether to visualize denoising result of the downsampled point cloud
        target_density_cm2 (float): Target surface density of points, specified in pts / cm^2
        outlier_removal_n_neighbors (None or int): If specified, the number of neighbors to take into consideration
            when removing statistical outliers from the downsampled point cloud.
            If None, will default to 4 * target_density_cm2
        outlier_removal_std_ratio (float): The standard deviation threshold when removing statistical outliers from
            the downsampled point cloud.
        dbscan_eps (None or float): If specified, the distance to use when clustering points. None defaults to 0.01
            (i.e.: using the target density cm2)
        dbscan_min_pts (None or int): If specified, the minimum number of points to consider when clustering points.
            None defaults to int(np.round(target_density_cm2 * dbscan_eps / 0.01)) (i.e.: normalized to the expected
            number of points within the unit area cm^2)
        cluster_proportion_threshold (float): The proportion of points to consider whether a given cluster is noise
            or not

    Returns:
        open3d.geometry.PointCloud: Denoised object point cloud.
        list: Corresponding point indices in pcd_obj.
    """
    import open3d as o3d
    import multiprocessing
    n_points = len(pcd_obj.points)
    if n_points == 0:
        return pcd_obj, np.array([], dtype=int)
    if n_points < 4:
        return pcd_obj, np.arange(n_points)

    if visualize_process:
        def vis():
            o3d.visualization.draw_geometries([pcd_obj])

        vis_process = multiprocessing.Process(target=vis)
        vis_process.start()
        vis_process.join()

    # 1. Downsample the object point cloud
    # We attempt to normalize the target density (assuming equally spaced points) according to its convex hull surface area
    ch, _ = pcd_obj.compute_convex_hull()
    ch_surface_area_cm2 = ch.get_surface_area() * (100 ** 2)     # m^2 -> cm^2
    # obb_extent = pcd_obj.get_oriented_bounding_box().extent
    # pcd_vol = np.prod(obb_extent) * (100 ** 3)       # in m^3 -> cm^3
    n_target_points = int(target_density_cm2 * ch_surface_area_cm2)
    if n_target_points < len(pcd_obj.points):
        downsampled_indices = np.random.choice(len(pcd_obj.points), n_target_points, replace=False)
        pcd_obj_downsampled = pcd_obj.select_by_index(downsampled_indices)
    else:
        downsampled_indices = np.arange(len(pcd_obj.points))
        pcd_obj_downsampled = pcd_obj

    if visualize_process:
        def vis():
            o3d.visualization.draw_geometries([pcd_obj_downsampled])

        vis_process = multiprocessing.Process(target=vis)
        vis_process.start()
        vis_process.join()

    # 2. Apply out-of-the-shelf statistical outlier removal
    outlier_removal_n_neighbors = int(np.round(4 * target_density_cm2)) if outlier_removal_n_neighbors is None else outlier_removal_n_neighbors
    pcd_obj_downsampled, ind = pcd_obj_downsampled.remove_statistical_outlier(nb_neighbors=outlier_removal_n_neighbors, std_ratio=outlier_removal_std_ratio)

    # Retain only the valid downsampled indices after noise removal
    valid_downsampled_indices = downsampled_indices[ind]
    if len(pcd_obj_downsampled.points) == 0:
        return pcd_obj_downsampled, np.array([], dtype=int)

    # 3. Perform DBSCAN clustering
    dbscan_eps = 0.01 if dbscan_eps is None else dbscan_eps
    dbscan_min_pts = int(np.round(target_density_cm2 * dbscan_eps / 0.01)) if dbscan_min_pts is None else dbscan_min_pts
    labels = np.array(pcd_obj_downsampled.cluster_dbscan(eps=dbscan_eps, min_points=dbscan_min_pts, print_progress=False))
    if len(labels) == 0:
        return pcd_obj_downsampled, np.array([], dtype=int)
    max_label = labels.max()

    if visualize_process:
        def vis():
            cmap = plt.get_cmap("tab20")
            colors = cmap(labels / (max_label if max_label > 0 else 1))
            colors[labels < 0] = 0
            pcd_obj_downsampled.colors = o3d.utility.Vector3dVector(colors[:, :3])
            o3d.visualization.draw_geometries([pcd_obj_downsampled])

        vis_process = multiprocessing.Process(target=vis)
        vis_process.start()
        vis_process.join()

    # Identify unique clusters and count the number of points in each cluster
    total_points = len(labels)
    unique_clusters, counts = np.unique(labels, return_counts=True)

    # Remove any cluster that is smaller than the given overall proportion of the point cloud
    inlier_cluster_idxs = []
    for cluster_id in unique_clusters:
        cluster_pt_idxs = np.where(labels == cluster_id)[0]
        n_cluster_pts = len(cluster_pt_idxs)
        if (n_cluster_pts / total_points) >= cluster_proportion_threshold:
            inlier_cluster_idxs.append(cluster_pt_idxs)
    if len(inlier_cluster_idxs) == 0:
        return pcd_obj_downsampled, np.array([], dtype=int)
    inlier_cluster_idxs = np.concatenate(inlier_cluster_idxs)

    cleaned_pcd = pcd_obj_downsampled.select_by_index(inlier_cluster_idxs)
    valid_indices_in_original = valid_downsampled_indices[inlier_cluster_idxs]

    if visualize_result:
        display_inlier_outlier(pcd_obj_downsampled, inlier_cluster_idxs)

        def vis():
            aligned_bbox = cleaned_pcd.get_axis_aligned_bounding_box()
            aligned_bbox.color = (1, 0, 0)
            oriented_bbox = cleaned_pcd.get_oriented_bounding_box()
            oriented_bbox.color = (0, 1, 0)
            o3d.visualization.draw_geometries([cleaned_pcd, aligned_bbox, oriented_bbox])

        vis_process = multiprocessing.Process(target=vis)
        vis_process.start()
        vis_process.join()

    # Return the cleaned point cloud
    return cleaned_pcd, valid_indices_in_original


def compute_object_removal_order(
    obj_chs,
    cam2world_tf,
    n_ray_samples=1000,
    occlusion_ray_fraction_threshold=0.05,
    support_ray_fraction_threshold=0.20,
    containment_fraction_threshold=0.50,
):
    """
    Determines which object to remove next using three prioritized heuristics:
      1. Occlusion: prefer non-occluded objects (visible from camera)
      2. Support level: prefer objects on top of / inside other objects (topmost first)
      3. Camera depth: prefer objects closer to the camera (foreground first)

    Support relationships are computed first so that the occlusion check can exclude
    supporting objects. For example, a croissant inside an open box will have camera-
    directed rays that hit the box's convex hull, but this is expected geometry (the box
    supports the croissant), not true visual occlusion.

    Args:
        obj_chs: dict mapping phrase_unique_id -> trimesh convex hull mesh
        cam2world_tf: 4x4 camera-to-world transformation matrix
        n_ray_samples: number of ray samples for each test
        occlusion_ray_fraction_threshold: fraction of camera-directed rays that must be
            blocked for an object to be considered occluded
        support_ray_fraction_threshold: fraction of downward rays from B that must hit A
            for B to be considered "on top of" A
        containment_fraction_threshold: fraction of B's interior points that must be
            inside A's convex hull for B to be considered "inside" A

    Returns:
        str: phrase_unique_id of the object to remove
    """
    from collections import defaultdict
    import logging
    import trimesh
    logger=logging.getLogger(__name__)
    phrases = list(obj_chs.keys())

    if len(phrases) == 1:
        logger.info(f"Only one object detected: {phrases[0]}")
        return phrases[0]

    cam_pos = cam2world_tf[:3, 3]

    # Pre-compute intersectors and interior sample points for each object
    intersectors = {}
    interior_points = {}
    for phrase, ch in obj_chs.items():
        intersectors[phrase] = trimesh.ray.ray_pyembree.RayMeshIntersector(ch)
        min_coords = ch.bounds[0]
        max_coords = ch.bounds[1]
        candidates = np.random.uniform(low=min_coords, high=max_coords, size=(n_ray_samples, 3))
        inside = intersectors[phrase].contains_points(candidates)
        interior_points[phrase] = candidates[inside]

    # --- Heuristic 2 (computed first): Support relationship detection ---
    # Build a directed graph: on_top_of[B] contains A means B is on top of A
    # (i.e. A supports B, so B should be removed before A)
    # This must be computed before occlusion so we can exclude supporting objects
    # from the occlusion check.
    on_top_of = defaultdict(set)   # B -> set of objects that B sits on top of

    for phrase_b in phrases:
        ch_b = obj_chs[phrase_b]
        pts_b = interior_points[phrase_b]
        if len(pts_b) == 0:
            continue
        centroid_b_z = ch_b.centroid[2]

        for phrase_a in phrases:
            if phrase_a == phrase_b:
                continue
            ch_a = obj_chs[phrase_a]

            # Skip if B's centroid is well below A's bottom -- B can't be on top of A
            if centroid_b_z < ch_a.bounds[0][2] - 0.02:
                continue

            # Test 1: Downward rays from B's interior hitting A's convex hull
            down_dirs = np.zeros((len(pts_b), 3))
            down_dirs[:, 2] = -1.0
            down_hits = intersectors[phrase_a].intersects_any(
                ray_origins=pts_b,
                ray_directions=down_dirs,
            )
            down_fraction = down_hits.sum() / len(pts_b)

            # Test 2: Containment -- fraction of B's interior inside A's convex hull
            containment_fraction = 0.0
            if len(pts_b) > 0:
                inside_a = intersectors[phrase_a].contains_points(pts_b)
                containment_fraction = inside_a.sum() / len(pts_b)

            if down_fraction >= support_ray_fraction_threshold or containment_fraction >= containment_fraction_threshold:
                on_top_of[phrase_b].add(phrase_a)
                reason = []
                if down_fraction >= support_ray_fraction_threshold:
                    reason.append(f"downward rays={down_fraction:.2f}")
                if containment_fraction >= containment_fraction_threshold:
                    reason.append(f"containment={containment_fraction:.2f}")
                logger.info(f"Support: {phrase_b} is on top of {phrase_a} ({', '.join(reason)})")

    # Support levels: longest chain of objects stacked above each object, with
    # mutually-supporting cycles (ambiguous masks) condensed so it terminates.
    support_level, mutual_support_groups = support_levels(phrases, on_top_of)
    for group in mutual_support_groups:
        logger.warning(
            f"Mutually-supporting objects (overlapping/ambiguous masks?): {group}; "
            "they share a support level and later heuristics break the tie."
        )

    for p in phrases:
        logger.info(f"Support level: {p} = {support_level[p]}")

    # --- Heuristic 1: Fractional occlusion via camera-directed rays ---
    # When checking if object A is occluded, we skip objects that A sits on top of.
    # Rays from A hitting a supporting object's convex hull are expected (the object
    # is inside/on-top-of the supporter), not true visual occlusion.
    occlusion_fractions = {}
    for phrase_a in phrases:
        pts = interior_points[phrase_a]
        if len(pts) == 0:
            occlusion_fractions[phrase_a] = 0.0
            continue
        ray_dirs = cam_pos.reshape(1, 3) - pts
        ray_dirs = ray_dirs / np.linalg.norm(ray_dirs, axis=-1, keepdims=True)
        # Objects that A sits on top of should not count as occluders
        a_supporters = on_top_of.get(phrase_a, set())
        max_blocked = 0.0
        for phrase_b in phrases:
            if phrase_b == phrase_a:
                continue
            if phrase_b in a_supporters:
                continue
            hits = intersectors[phrase_b].intersects_any(
                ray_origins=pts,
                ray_directions=ray_dirs,
            )
            fraction = hits.sum() / len(pts)
            max_blocked = max(max_blocked, fraction)
        occlusion_fractions[phrase_a] = max_blocked

    is_occluded = {p: frac > occlusion_ray_fraction_threshold for p, frac in occlusion_fractions.items()}
    for p in phrases:
        if is_occluded[p]:
            logger.info(f"Occlusion: {p} is occluded (max blocked fraction: {occlusion_fractions[p]:.2f})")
        else:
            logger.info(f"Occlusion: {p} is NOT occluded (max blocked fraction: {occlusion_fractions[p]:.2f})")

    # --- Heuristic 3: Camera distance ---
    # Use direct distance instead of a camera-axis projection because project data
    # may use either +Z-forward or -Z-forward camera transforms.
    camera_depths = {}
    for phrase, ch in obj_chs.items():
        centroid = ch.centroid
        camera_depths[phrase] = np.linalg.norm(centroid - cam_pos)

    for p in phrases:
        logger.info(f"Camera depth: {p} = {camera_depths[p]:.4f}")

    # --- Combined multi-level sort ---
    # Priority: (1) non-occluded first, (2) lowest support level first, (3) closest to camera first
    sorted_phrases = sorted(phrases, key=lambda p: (
        is_occluded[p],         # False (0) < True (1) -> non-occluded first
        support_level[p],       # 0 < 1 < 2 ... -> topmost objects first
        camera_depths[p],       # smaller -> closer to camera
    ))

    logger.info(f"\nObject removal priority order:")
    for i, p in enumerate(sorted_phrases):
        logger.info(f"  {i+1}. {p} (occluded={is_occluded[p]}, support_level={support_level[p]}, cam_depth={camera_depths[p]:.4f})")

    selected = sorted_phrases[0]
    logger.info(f"\nSelected for removal: {selected}")
    return selected


def support_levels(phrases, on_top_of):
    """Cycle-safe support levels. Returns (levels, mutual_groups).

    ``on_top_of[b]`` is the set of objects b sits on top of. Level 0 = nothing
    on top (removed first); an object's level is the longest chain of objects
    stacked above it. ``mutual_groups`` lists any mutually-supporting groups
    (cycles) that were condensed; their members share a level.
    """
    phrases = list(phrases)
    known = set(phrases)
    succ = {p: [w for w in sorted(on_top_of.get(p, ())) if w in known and w != p]
            for p in phrases}
    self_loops = {p for p in phrases if p in on_top_of.get(p, ())}

    comps = _tarjan_scc(phrases, succ)
    comp_of = {n: i for i, comp in enumerate(comps) for n in comp}

    # reversed() is topological order, so each component's level is final
    # before it relaxes its successors.
    comp_level = [0] * len(comps)
    for ci in reversed(range(len(comps))):
        for node in comps[ci]:
            for w in succ[node]:
                cj = comp_of[w]
                if cj != ci and comp_level[cj] < comp_level[ci] + 1:
                    comp_level[cj] = comp_level[ci] + 1

    levels = {n: comp_level[comp_of[n]] for n in phrases}
    mutual_groups = [sorted(comp) for comp in comps
                     if len(comp) > 1 or comp[0] in self_loops]
    return levels, mutual_groups


def _tarjan_scc(nodes, succ):
    """Iterative Tarjan. Returns components in reverse topological order
    (every edge points from a later component to an earlier one)."""
    from itertools import count
    index_of = {}
    lowlink = {}
    on_stack = set()
    stack = []
    comps = []
    counter = count()
    for root in nodes:
        if root in index_of:
            continue
        index_of[root] = lowlink[root] = next(counter)
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(succ.get(root, ())))]
        while work:
            node, it = work[-1]
            descended = False
            for w in it:
                if w not in index_of:
                    index_of[w] = lowlink[w] = next(counter)
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(succ.get(w, ()))))
                    descended = True
                    break
                if w in on_stack:
                    lowlink[node] = min(lowlink[node], index_of[w])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index_of[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                comps.append(comp)
    return comps
