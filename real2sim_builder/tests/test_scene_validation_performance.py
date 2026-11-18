"""Synthetic validation work bounds without weakening asset or collision checks."""
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from real2sim_builder import scene as scene_module
from real2sim_builder.files import sha


def _write_obj(path, vertices, faces):
    path.write_text(
        "".join("v " + " ".join(map(str, vertex)) + "\n" for vertex in vertices)
        + "".join("f " + " ".join(str(index + 1) for index in face) + "\n" for face in faces)
    )


def _compound_scene(root, part_count=6):
    asset_root = root / "assets"
    asset_root.mkdir()
    vertices = [[0, 0, 0], [.02, 0, 0], [0, .02, 0], [0, 0, .02]]
    faces = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]
    _write_obj(asset_root / "collision.obj", vertices, faces)
    _write_obj(asset_root / "visual.obj", vertices, faces)
    (asset_root / "unrelated.usda").write_text('#usda 1.0\ndef Xform "Reference" {}\n')

    scene = scene_module.empty("Synthetic compound validation")
    scene["assets"] = {
        name: {"path": path.relative_to(root).as_posix(), "sha256": sha(path)}
        for name, path in (
            ("collision_mesh", asset_root / "collision.obj"),
            ("visual_mesh", asset_root / "visual.obj"),
            ("unrelated_usda", asset_root / "unrelated.usda"),
        )
    }
    parts = []
    for index in range(part_count):
        pose = np.eye(4)
        pose[0, 3] = index * .03
        parts.append({
            "type": "mesh", "asset": "collision_mesh",
            "dimensions": [.02, .02, .02], "pose": pose.tolist(),
        })
    scene["objects"] = [{
        "id": "compound_object", "role": "manipulable_object", "frame": "world",
        "pose": scene_module.value(np.eye(4).tolist(), "estimated"),
        "dimensions": scene_module.value([part_count * .03, .02, .02], "estimated"),
        "visual": {"type": "mesh", "asset": "visual_mesh"},
        "collision": {"type": "compound", "parts": parts},
        "color": scene_module.value([.4, .5, .6], "estimated"),
        "physics": {"mass_kg": scene_module.value(.1, "estimated")},
    }]
    scene["cameras"] = [{
        "id": "side", "frame": "world", "resolution": [160, 120],
        "pose": scene_module.value(np.eye(4).tolist(), "estimated"),
        "K": scene_module.value([[160., 0, 80.], [0, 160., 60.], [0, 0, 1.]], "estimated"),
        "distortion": scene_module.value([0.] * 5, "estimated"),
    }]
    return scene


@pytest.mark.parametrize("part_count", [1, 6])
def test_complete_validation_hashes_each_asset_once_despite_compound_parts(tmp_path, monkeypatch, part_count):
    scene = _compound_scene(tmp_path, part_count)
    hash_calls = Counter()
    real_sha = scene_module.sha

    def counted_sha(path):
        hash_calls[Path(path).resolve()] += 1
        return real_sha(path)

    monkeypatch.setattr(scene_module, "sha", counted_sha)
    expected = Counter({(tmp_path / asset["path"]).resolve(): 1 for asset in scene["assets"].values()})

    # Each complete call owns one integrity pass, including unrelated assets.
    for _ in range(2):
        hash_calls.clear()
        assert scene_module.validate(scene, tmp_path, complete=True) is scene
        assert hash_calls == expected


@pytest.mark.parametrize("asset_id", ["collision_mesh", "visual_mesh", "unrelated_usda"])
def test_complete_validation_rechecks_asset_integrity_after_a_success(tmp_path, asset_id):
    scene = _compound_scene(tmp_path)
    scene_module.validate(scene, tmp_path, complete=True)
    path = tmp_path / scene["assets"][asset_id]["path"]
    # Keep OBJ/USDA syntax valid so the failure must come from the stored SHA.
    with path.open("a") as stream:
        stream.write("\n# synthetic asset changed after validation\n")

    with pytest.raises(ValueError, match="Source asset hash changed"):
        scene_module.validate(scene, tmp_path, complete=True)


@pytest.mark.parametrize("collision_type", ["mesh", "compound"])
def test_complete_validation_rejects_a_genuinely_nonconvex_mesh(tmp_path, collision_type):
    scene = _compound_scene(tmp_path)
    path = tmp_path / "assets" / "nonconvex.obj"
    # A closed tetrahedron with its outer face dented toward an interior point.
    _write_obj(
        path,
        [[0, 0, 0], [.02, 0, 0], [0, .02, 0], [0, 0, .02], [.004, .004, .004]],
        [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 4], [2, 3, 4], [3, 1, 4]],
    )
    scene["assets"]["nonconvex_mesh"] = {"path": path.relative_to(tmp_path).as_posix(), "sha256": sha(path)}
    if collision_type == "mesh":
        scene["objects"][0]["collision"] = {"type": "mesh", "asset": "nonconvex_mesh"}
    else:
        # The final part must be checked after all the repeated convex parts.
        scene["objects"][0]["collision"]["parts"][-1]["asset"] = "nonconvex_mesh"

    with pytest.raises(ValueError, match="Concave collision mesh"):
        scene_module.validate(scene, tmp_path, complete=True)


def test_dynamic_pose_check_has_no_asset_io_and_rejects_invalid_fk(tmp_path,monkeypatch):
    scene=_compound_scene(tmp_path)
    scene_module.validate(scene,tmp_path,complete=True)
    monkeypatch.setattr(scene_module,"sha",lambda *_:pytest.fail("Dynamic state rehashed static assets"))
    scene_module.validate_pose_state(scene)
    scene["objects"][0]["pose"]["value"][0][3]=float("nan")
    with pytest.raises(ValueError,match="finite"):
        scene_module.validate_pose_state(scene)
