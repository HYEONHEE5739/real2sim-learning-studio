"""Column-vector reference transforms. Live poses remain owned by each engine."""
from collections.abc import Mapping

import numpy as np

from .package import SceneError, _id, _keys


def validate_transform(value, *, field: str = "transform") -> np.ndarray:
    """Validate using the existing profile.transform tolerances; never orthogonalize."""
    try:
        raw = np.asarray(value)
        if raw.shape != (4, 4) or raw.dtype.kind not in "iuf":
            raise ValueError("expected a numeric real 4x4 matrix")
        matrix = np.asarray(raw, dtype=float).copy()
        if not np.isfinite(matrix).all():
            raise ValueError("Transform must be finite 4x4")
        if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8, rtol=1e-5):
            raise ValueError("Invalid homogeneous transform")
        rotation = matrix[:3, :3]
        with np.errstate(over="ignore", invalid="ignore"):
            valid = (np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5, rtol=1e-5)
                     and np.isclose(np.linalg.det(rotation), 1, atol=1e-5, rtol=1e-5))
        if not valid:
            raise ValueError("Rotation must be right-handed orthonormal")
        return matrix
    except (ValueError, TypeError, OverflowError) as exc:
        raise SceneError("SCENE_INVALID", field, str(exc)) from exc


def _frame_matrices(frames: Mapping) -> dict[str, np.ndarray]:
    if not isinstance(frames, Mapping) or "world" not in frames:
        raise SceneError("FRAME_UNRESOLVABLE", "scene.frames", "world frame is required")
    matrices = {}
    for name, node in frames.items():
        _id(name, "scene.frames")
        field = "scene.frames." + name
        _keys(node, {"parent", "T_parent_from_frame", "state"}, {"dynamic_source"}, field)
        if node["state"] != "reference":
            raise SceneError("SCENE_INVALID", field + ".state", "Metadata stores reference poses only")
        if name == "world":
            if node["parent"] is not None:
                raise SceneError("FRAME_UNRESOLVABLE", field + ".parent", "world must be the only root")
        else:
            _id(node["parent"], field + ".parent")
            if node["parent"] not in frames:
                raise SceneError("FRAME_UNRESOLVABLE", field + ".parent", "unknown parent frame")
        if "dynamic_source" in node and (not isinstance(node["dynamic_source"], Mapping) or not node["dynamic_source"]):
            raise SceneError("SCENE_INVALID", field + ".dynamic_source", "expected an explicit engine binding")
        matrices[name] = validate_transform(node["T_parent_from_frame"], field=field + ".T_parent_from_frame")
    if not np.array_equal(matrices["world"], np.eye(4)):
        raise SceneError("SCENE_INVALID", "scene.frames.world.T_parent_from_frame", "world root must be identity")
    completed = set()
    for name in frames:
        chain = set()
        cursor = name
        while cursor is not None and cursor not in completed:
            if cursor in chain:
                raise SceneError("FRAME_UNRESOLVABLE", "scene.frames." + cursor, "frame graph contains a cycle")
            chain.add(cursor)
            cursor = frames[cursor]["parent"]
        completed.update(chain)
    return matrices


def validate_frames(frames: Mapping) -> None:
    """Check every frame, parent edge and reference matrix, without runtime lookup."""
    _frame_matrices(frames)


def resolve_transform(frames: Mapping, *, source: str, target: str, state: str = "reference") -> np.ndarray:
    """Return T_target_from_source = inverse(T_world_target) @ T_world_source."""
    if state != "reference":
        raise SceneError("FRAME_UNRESOLVABLE", "state", "live/current poses require explicit engine state")
    matrices = _frame_matrices(frames)
    for field, name in (("source", source), ("target", target)):
        _id(name, field)
        if name not in frames:
            raise SceneError("FRAME_UNRESOLVABLE", field, "unknown frame: " + name)
    def world_pose(name):
        chain = []
        while name is not None:
            chain.append(name)
            name = frames[name]["parent"]
        result = np.eye(4)
        for name in reversed(chain):
            result = result @ matrices[name]
        return result
    # Use the original full inverse, not a transposed/renormalized rotation shortcut.
    return np.linalg.inv(world_pose(target)) @ world_pose(source)
