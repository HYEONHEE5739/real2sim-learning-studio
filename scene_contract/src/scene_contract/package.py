"""Read-only Scene JSON and file integrity; no engine, device or Asset parsers."""
from dataclasses import dataclass
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Issue:
    field: str
    reason: str
    source: str | None = None


class SceneError(ValueError):
    """Public local contract error; ordinary task failure is not this exception."""
    def __init__(self, code: str, field: str, reason: str, source: Path | None = None):
        self.code = code
        self.message = f"{field}: {reason}"
        self.issues = (Issue(field, reason, str(source) if source is not None else None),)
        self.effect = "not_started"
        super().__init__(self.message)


@dataclass(frozen=True)
class FileEntry:
    path: str
    size_bytes: int
    sha256: str


def _relative(value: str, field: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value
            or value.startswith("/") or value == "." or ".." in PurePosixPath(value).parts
            or PurePosixPath(value).as_posix() != value):
        raise SceneError("SCENE_INVALID", field, "expected a canonical package-relative POSIX file path")
    return value


def _path(root: Path, value: str, field: str) -> Path:
    _relative(value, field)
    path = root / value
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            raise SceneError("SCENE_INVALID", field, "file resolves outside the package", path)
        cursor = root
        for part in PurePosixPath(value).parts:
            cursor = cursor / part
            if cursor.is_symlink() and cursor.readlink().is_absolute():
                raise SceneError("SCENE_INVALID", field, "absolute symbolic link is not portable", cursor)
    except (OSError, RuntimeError) as exc:
        raise SceneError("SCENE_INVALID", field, "cannot resolve file path", path) from exc
    return path


def _digest(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            h.update(block)
    return size, h.hexdigest()


def _sha(value: str, field: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SceneError("SCENE_INVALID", field, "expected lowercase SHA-256 hex")


def verify_files(root: Path, entries: tuple[FileEntry, ...]) -> None:
    """Check every declared regular file. This does not parse USD/MJCF closure."""
    root = Path(root)
    seen = set()
    for index, item in enumerate(entries):
        field = f"files[{index}]"
        path = _path(root, item.path, field + ".path")
        if item.path in seen:
            raise SceneError("SCENE_INVALID", field + ".path", "duplicate manifest path")
        seen.add(item.path)
        if type(item.size_bytes) is not int or item.size_bytes < 0:
            raise SceneError("SCENE_INVALID", field + ".size_bytes", "expected a nonnegative integer")
        _sha(item.sha256, field + ".sha256")
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise SceneError("SCENE_INTEGRITY_MISMATCH", field + ".path", "expected a regular file", path)
            if info.st_size != item.size_bytes or _digest(path) != (item.size_bytes, item.sha256):
                raise SceneError("SCENE_INTEGRITY_MISMATCH", field, "file size or SHA-256 mismatch", path)
        except OSError as exc:
            raise SceneError("SCENE_INTEGRITY_MISMATCH", field + ".path", "required file missing or unreadable", path) from exc


@dataclass(frozen=True)
class SceneIdentity:
    scene_id: str
    revision: str
    manifest_sha256: str


@dataclass(frozen=True)
class EvidenceAccess:
    evidence_id: str
    sha256: str
    location: str
    access: str


@dataclass(frozen=True)
class ScenePackage:
    root: Path
    identity: SceneIdentity
    scene: Mapping[str, Any]
    calibration: Mapping[str, Any]
    files: tuple[FileEntry, ...]
    evidence_access: tuple[EvidenceAccess, ...]


def _keys(value: Any, required: set[str], optional: set[str], field: str) -> None:
    if not isinstance(value, Mapping):
        raise SceneError("SCENE_INVALID", field, "expected a JSON object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise SceneError("SCENE_INVALID", field, f"missing fields {sorted(missing)}; unknown fields {sorted(extra)}")


def _version(value: Mapping[str, Any], field: str) -> None:
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise SceneError("SCHEMA_UNSUPPORTED", field + ".schema_version", "expected schema_version 1")


def _id(value: Any, field: str) -> None:
    if (not isinstance(value, str) or not value or value in (".", "..")
            or any(c.isspace() or ord(c) < 32 or c in "/\\" for c in value)):
        raise SceneError("SCENE_INVALID", field, "expected a nonempty ID, independent of filesystem paths")


def _read_json(path: Path) -> tuple[dict, bytes]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("nonfinite JSON number")
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)
    try:
        if not stat.S_ISREG(path.stat().st_mode): raise ValueError("expected a regular JSON file")
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
        finite(data)
        if not isinstance(data, dict): raise ValueError("expected a JSON object")
        return data, raw
    except (OSError, ValueError, RecursionError) as exc:
        raise SceneError("SCENE_INVALID", path.name, str(exc), path) from exc


def _freeze(value):
    if isinstance(value, dict): return MappingProxyType({k:_freeze(v) for k,v in value.items()})
    if isinstance(value, list): return tuple(_freeze(v) for v in value)
    return value


def _references(value: Any, field: str):
    """Only declared file-reference fields; prim/body IDs and opaque strings aren't paths."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = field + "." + key
            if key in ("asset_path", "parameters_file"):
                yield _relative(item, name), name
            elif key in ("asset_paths", "required_files"):
                if not isinstance(item, (list, tuple)):
                    raise SceneError("SCENE_INVALID", name, "expected a list of package-relative paths")
                for index, path in enumerate(item):
                    yield _relative(path, f"{name}[{index}]"), f"{name}[{index}]"
            else:
                yield from _references(item, name)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value): yield from _references(item, f"{field}[{index}]")


def _required_references(scene: Mapping, calibration: Mapping, files: tuple[FileEntry, ...]) -> None:
    paths = {row.path for row in files}; hashes = {row.sha256 for row in files}
    for value, field in ((scene, "scene"), (calibration["records"], "calibration.records")):
        for path, source in _references(value, field):
            if path not in paths:
                raise SceneError("SCENE_INVALID", source, "unregistered required file: " + path)
    for name, record in calibration["records"].items():
        field = "calibration.records." + name
        for key in ("source_model_sha256", "execution_model_sha256", "input_asset_sha256"):
            if key not in record:
                if key != "input_asset_sha256" and record["kind"] in ("encoder_mapping", "robot_residual"):
                    raise SceneError("SCENE_INVALID", field + "." + key, "robot calibration requires model identity")
                continue
            _sha(record[key], field + "." + key)
            if record[key] not in hashes:
                raise SceneError("SCENE_INVALID", field + "." + key, "identity has no corresponding manifest file")


def _id_list(value, field, *, allow_empty=False):
    if not isinstance(value, (list, tuple)) or (not value and not allow_empty):
        raise SceneError("SCENE_INVALID", field, "expected an explicit ID list")
    for name in value: _id(name, field)
    if len(set(value)) != len(value):
        raise SceneError("SCENE_INVALID", field, "duplicate ID")
    return tuple(value)


def _parameter_json(value):
    """Canonical hashing also accepts the package's frozen mapping/tuple data."""
    if isinstance(value, Mapping): return {key:_parameter_json(item) for key,item in value.items()}
    if isinstance(value, (list, tuple)): return [_parameter_json(item) for item in value]
    return value


def _calibration_relations(scene, calibration, files):
    records = calibration["records"]
    targets = {"robot"} if scene["robot"] else set()
    for section in ("objects", "cameras", "supports", "frames"):
        targets.update(scene[section])
    robot_order = scene["robot"].get("joint_order")
    if robot_order is not None: _id_list(robot_order, "scene.robot.joint_order")
    for name, record in records.items():
        field = "calibration.records." + name
        required = {"kind", "target", "algorithm_id", "application", "validation", "evidence_ids"}
        optional = {"parameters", "parameters_file", "source_model_sha256", "execution_model_sha256", "joint_order", "frame_ids", "sensor_identity", "input_asset_sha256"}
        _keys(record, required, optional, field)
        if ("parameters" in record) == ("parameters_file" in record):
            raise SceneError("SCENE_INVALID", field, "supply exactly one of parameters or parameters_file")
        if "parameters" in record and not isinstance(record["parameters"], Mapping):
            raise SceneError("SCENE_INVALID", field + ".parameters", "expected parameter data")
        if "parameters_file" in record:
            _relative(record["parameters_file"], field + ".parameters_file")
        for key in ("kind", "target", "algorithm_id"): _id(record[key], field + "." + key)
        if record["target"] not in targets:
            raise SceneError("SCENE_INVALID", field + ".target", "unknown calibration target")
        if not isinstance(record["validation"], Mapping):
            raise SceneError("SCENE_INVALID", field + ".validation", "expected validation data, never inferred status")
        evidence = _id_list(record["evidence_ids"], field + ".evidence_ids", allow_empty=True)
        if any(identity not in calibration["evidence"] for identity in evidence):
            raise SceneError("SCENE_INVALID", field + ".evidence_ids", "unknown evidence ID")
        app = record["application"]
        if not isinstance(app, Mapping) or app.get("mode") not in ("baked", "runtime"):
            raise SceneError("SCENE_INVALID", field + ".application.mode", "expected baked or runtime")
        if app["mode"] == "baked":
            _keys(app, {"mode", "asset_paths", "input_calibration_ids", "order_index"}, set(), field + ".application")
            paths = app["asset_paths"]
            if not isinstance(paths, (list, tuple)) or not paths or any(not isinstance(p, str) for p in paths):
                raise SceneError("SCENE_INVALID", field + ".application.asset_paths", "expected result Asset paths")
            for path in paths: _relative(path, field + ".application.asset_paths")
            if len(set(paths)) != len(paths):
                raise SceneError("SCENE_INVALID", field + ".application.asset_paths", "duplicate baked result Asset")
        else:
            _keys(app, {"mode", "phase", "input_space", "output_space", "order_index"},
                  {"input_calibration_ids", "joint_order", "frame_ids"}, field + ".application")
            if app["phase"] not in ("device_observation", "device_command", "scene_initialization", "camera_render"):
                raise SceneError("SCENE_INVALID", field + ".application.phase", "unknown runtime phase")
            for key in ("input_space", "output_space"): _id(app[key], field + ".application." + key)
            if record["kind"] == "robot_residual" and app["phase"] in ("device_observation", "device_command"):
                raise SceneError("SCENE_INVALID", field + ".application.phase", "Geometry residual must not change hardware q")
        if type(app["order_index"]) is not int or app["order_index"] < 0:
            raise SceneError("SCENE_INVALID", field + ".application.order_index", "expected nonnegative integer")
        dependencies = _id_list(app.get("input_calibration_ids", []), field + ".application.input_calibration_ids", allow_empty=True)
        if any(dependency not in records for dependency in dependencies):
            raise SceneError("SCENE_INVALID", field + ".application.input_calibration_ids", "unknown calibration dependency")
        if record["kind"] == "robot_residual" and record["algorithm_id"] == "precision_bound_residual":
            if app["mode"] != "baked":
                raise SceneError("SCENE_INVALID", field + ".application.mode", "v8 bound residual is already baked Geometry")
            if not any(isinstance(records[dependency], Mapping) and records[dependency].get("kind") == "encoder_mapping" for dependency in dependencies):
                raise SceneError("SCENE_INVALID", field + ".application.input_calibration_ids", "bound residual needs its fitted encoder mapping")
        for key in ("joint_order", "frame_ids"):
            if key in record and key in app:
                declared = _id_list(record[key], field + "." + key)
                applied = _id_list(app[key], field + ".application." + key)
                if declared != applied:
                    raise SceneError("SCENE_INVALID", field + "." + key, "record and application disagree")
            value = record.get(key, app.get(key))
            if value is not None:
                ids = _id_list(value, field + "." + key)
                if key == "frame_ids" and any(identity not in scene["frames"] for identity in ids):
                    raise SceneError("FRAME_UNRESOLVABLE", field + ".frame_ids", "unknown calibration frame")
                if key == "joint_order" and (robot_order is None or ids != tuple(robot_order)):
                    raise SceneError("SCENE_INVALID", field + ".joint_order", "must match the Scene robot joint order")
        if record["kind"] in ("encoder_mapping", "robot_residual"):
            _id_list(record.get("joint_order", app.get("joint_order")), field + ".joint_order")
        for key in ("source_model_sha256", "execution_model_sha256", "input_asset_sha256"):
            if key != "input_asset_sha256" and record["kind"] in ("encoder_mapping", "robot_residual") and key not in record:
                raise SceneError("SCENE_INVALID", field + "." + key, "model-bound calibration needs identity")
            if key in record: _sha(record[key], field + "." + key)
        if record["kind"] in ("camera_intrinsic", "camera_extrinsic"):
            if not (record.get("frame_ids") or app.get("frame_ids")):
                raise SceneError("SCENE_INVALID", field + ".frame_ids", "camera calibration needs explicit optical/mount frames")
            if "input_asset_sha256" not in record and not (isinstance(record.get("sensor_identity"), Mapping) and record["sensor_identity"]):
                raise SceneError("SCENE_INVALID", field + ".sensor_identity", "camera calibration needs its sensor or input Asset identity")

    # Dependencies include fitting evidence. A baked residual depending on an
    # encoder mapping does not mean that numeric mapping was baked into Geometry.
    completed = set()
    for name in records:
        stack = [(name, False)]
        active = set()
        while stack:
            current, leaving = stack.pop()
            if leaving:
                active.remove(current)
                completed.add(current)
            elif current not in completed:
                if current in active:
                    raise SceneError("SCENE_INVALID", "calibration.records." + current, "calibration dependency cycle")
                active.add(current)
                stack.append((current, True))
                stack.extend((dependency, False) for dependency in records[current]["application"].get("input_calibration_ids", []))

    def context(record):
        app = record["application"]
        return record["target"], app["mode"], app.get("phase"), app.get("input_space")
    hashes = {file.path:file.sha256 for file in files} if files is not None else {}
    seen = []
    for name, record in records.items():
        field = "calibration.records." + name
        app = record["application"]
        if app["mode"] == "baked" and "execution_model_sha256" in record and files is not None:
            result_hashes = {hashes.get(path) for path in app["asset_paths"]}
            if record["execution_model_sha256"] not in result_hashes:
                raise SceneError("SCENE_INVALID", field + ".execution_model_sha256", "baked result identity must match a declared output Asset")
        for dependency in app.get("input_calibration_ids", []):
            previous = records[dependency]
            if record["kind"] == "robot_residual" and previous["kind"] == "encoder_mapping":
                if record["source_model_sha256"] != previous["execution_model_sha256"]:
                    raise SceneError("SCENE_INVALID", field + ".source_model_sha256", "residual and fitted encoder mapping use different model frames")
            overlapping_assets = app["mode"] == previous["application"]["mode"] == "baked" and bool(set(app["asset_paths"]) & set(previous["application"]["asset_paths"]))
            if (app["mode"] == "runtime" and context(record)[:3] == context(previous)[:3]) or overlapping_assets:
                if previous["application"]["order_index"] >= app["order_index"]:
                    raise SceneError("SCENE_INVALID", field + ".application.order_index", "dependency must precede this application")
                if app["mode"] == "runtime" and previous["application"]["output_space"] != app["input_space"]:
                    raise SceneError("SCENE_INVALID", field + ".application.input_space", "dependency output/input space mismatch")
        if "parameters_file" in record:
            parameter_identity = ("file", hashes.get(record["parameters_file"], record["parameters_file"]))
        else:
            try:
                parameter_identity = ("inline", json.dumps(_parameter_json(record["parameters"]), sort_keys=True, allow_nan=False))
            except (TypeError, ValueError) as exc:
                raise SceneError("SCENE_INVALID", field + ".parameters", "expected finite JSON parameter data") from exc
        signature = record["kind"], record["target"], record["algorithm_id"], parameter_identity
        for prior_signature, prior in seen:
            prior_app = prior["application"]
            if context(record) == context(prior) and app["order_index"] == prior_app["order_index"]:
                if app["mode"] == "runtime" or set(app["asset_paths"]) & set(prior_app["asset_paths"]):
                    raise SceneError("SCENE_INVALID", field + ".application.order_index", "ambiguous application order")
            same_models = (record.get("source_model_sha256") is not None and
                (record.get("source_model_sha256"), record.get("execution_model_sha256")) ==
                (prior.get("source_model_sha256"), prior.get("execution_model_sha256")))
            if signature[:3] == prior_signature[:3] and (signature[3] == prior_signature[3] or same_models):
                conflict = (app["mode"] != prior_app["mode"] or
                    (app["mode"] == "runtime" and context(record) == context(prior)) or
                    (app["mode"] == "baked" and bool(set(app["asset_paths"]) & set(prior_app["asset_paths"]))))
                if conflict:
                    raise SceneError("SCENE_INVALID", field + ".application", "duplicate calibration application, including baked/runtime")
        seen.append((signature, record))


def _evidence_access(root: Path, evidence: Mapping) -> tuple[EvidenceAccess, ...]:
    results = []
    for name, record in evidence.items():
        field = "calibration.evidence." + name
        _keys(record, {"sha256", "location"}, set(), field); _sha(record["sha256"], field + ".sha256")
        location = record["location"]
        if not isinstance(location, str) or not location:
            raise SceneError("SCENE_INVALID", field + ".location", "expected a preservation location")
        access = "unchecked"
        if not re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", location):
            path = Path(location)
            if not path.is_absolute(): path = root / path
            try:
                if stat.S_ISREG(path.stat().st_mode):
                    access = "available" if _digest(path)[1] == record["sha256"] else "mismatch"
                else:
                    access = "unavailable"
            except (OSError, ValueError):
                access = "unavailable"
        results.append(EvidenceAccess(name, record["sha256"], location, access))
    return tuple(results)


def _asset_declarations(scene: Mapping) -> None:
    for engine, binding in scene["engines"].items():
        field = "scene.engines." + engine
        if engine not in ("isaac", "mujoco"):
            raise SceneError("SCENE_INVALID", field, "unknown engine ID")
        if not isinstance(binding, Mapping) or "asset_path" not in binding:
            raise SceneError("SCENE_INVALID", field + ".asset_path", "engine requires a native Asset entry")
    def geometry(value, field):
        if isinstance(value, Mapping):
            if value.get("kind") == "mesh" and "asset_path" not in value:
                raise SceneError("SCENE_INVALID", field + ".asset_path", "mesh requires a declared Asset file")
            for key, item in value.items(): geometry(item, field + "." + key)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value): geometry(item, f"{field}[{index}]")
    geometry(scene, "scene")


def _bound_residuals(calibration, *, root=None, files=None):
    """Preserve v8's exact mapping binding; no fit, model rebinding or motor conversion."""
    hashes = {entry.path:entry.sha256 for entry in files} if files is not None else {}
    def parameters(record):
        if "parameters" in record:
            return record["parameters"]
        if root is None:
            return None  # Metadata-only validation cannot assert file-content validation.
        path = _path(root, record["parameters_file"], "calibration.parameters_file")
        data, raw = _read_json(path)
        if hashlib.sha256(raw).hexdigest() != hashes.get(record["parameters_file"]):
            raise SceneError("SCENE_INTEGRITY_MISMATCH", "calibration.parameters_file", "loaded parameter bytes differ from manifest")
        return data
    for name, record in calibration["records"].items():
        if record["kind"] != "robot_residual" or record["algorithm_id"] != "precision_bound_residual":
            continue
        residual = parameters(record)
        if residual is None: continue
        field = "calibration.records." + name
        expected = residual.get("precision_mapping_sha256")
        _sha(expected, field + ".parameters.precision_mapping_sha256")
        matched = False; deferred = False
        for dependency in record["application"]["input_calibration_ids"]:
            previous = calibration["records"][dependency]
            if previous["kind"] != "encoder_mapping": continue
            mapping = parameters(previous)
            if mapping is None:
                deferred = True
                continue
            spec = {key:_parameter_json(value) for key,value in mapping.items() if key != "sha256"}
            actual = hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
            if (mapping.get("schema") == "so101.precision-joint-mapping/1" and actual == mapping.get("sha256") == expected
                    and isinstance(mapping.get("profile"), Mapping)
                    and mapping["profile"].get("role") in ("leader", "follower")
                    and mapping["profile"].get("urdf_sha256") == record["source_model_sha256"]
                    and isinstance(mapping.get("joint_order"), (list, tuple))
                    and tuple(mapping.get("joint_order", ())) == tuple(previous.get("joint_order", previous["application"].get("joint_order", ())))):
                matched = True
        if not matched and not deferred:
            raise SceneError("SCENE_INVALID", field + ".application.input_calibration_ids", "residual requires the exact fitted Precision mapping/model/order")


def validate_scene(scene: Mapping[str, Any], calibration: Mapping[str, Any], *, files: tuple[FileEntry, ...] | None = None) -> None:
    """Validate declared reference frames; native binding lookup remains engine-owned."""
    sections = {"frames", "objects", "robot", "cameras", "supports", "engines", "validation"}
    _keys(scene, sections | {"schema_version", "scene_id", "revision", "units", "calibration", "manifest"}, set(), "scene")
    _version(scene, "scene")
    for key in ("scene_id", "revision"): _id(scene[key], "scene." + key)
    if scene["units"] != {"length":"m", "angle":"rad", "time":"s", "mass":"kg"}:
        raise SceneError("SCENE_INVALID", "scene.units", "expected length=m, angle=rad, time=s, mass=kg")
    for key in sections:
        if not isinstance(scene[key], Mapping): raise SceneError("SCENE_INVALID", "scene." + key, "expected a JSON object")
    for section in ("frames", "objects", "cameras", "supports"):
        for name in scene[section]: _id(name, f"scene.{section}")
    _keys(calibration, {"schema_version", "records", "evidence"}, set(), "calibration")
    _version(calibration, "calibration")
    for key in ("records", "evidence"):
        if not isinstance(calibration[key], Mapping): raise SceneError("SCENE_INVALID", "calibration." + key, "expected a JSON object")
        for name in calibration[key]: _id(name, "calibration." + key)
    from .transforms import validate_frames, validate_transform
    validate_frames(scene["frames"])

    def frame_references(value, field):
        if isinstance(value, Mapping):
            if "local_transform" in value:
                if "frame_id" in value:
                    raise SceneError("SCENE_INVALID", field, "use frame_id or local_transform, not both")
                validate_transform(value["local_transform"], field=field + ".local_transform")
            if value.get("kind") in ("primitive", "mesh") and not ({"local_transform", "frame_id"} & value.keys()):
                raise SceneError("SCENE_INVALID", field, "Geometry needs a frame_id or local_transform")
            for key, item in value.items():
                source = field + "." + key
                if key in ("frame_id", "optical_frame_id", "mount_frame_id"):
                    _id(item, source)
                    if item not in scene["frames"]:
                        raise SceneError("FRAME_UNRESOLVABLE", source, "unknown reference frame: " + item)
                elif key == "frame_ids":
                    if not isinstance(item, (list, tuple)):
                        raise SceneError("SCENE_INVALID", source, "expected frame IDs")
                    for name in item:
                        _id(name, source)
                        if name not in scene["frames"]:
                            raise SceneError("FRAME_UNRESOLVABLE", source, "unknown reference frame: " + name)
                else:
                    frame_references(item, source)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value): frame_references(item, f"{field}[{index}]")
    for key in ("robot", "objects", "cameras", "supports", "engines"):
        frame_references(scene[key], "scene." + key)
    _calibration_relations(scene, calibration, files)
    _bound_residuals(calibration)


def load_scene(entry: Path, *, expected: SceneIdentity | None = None) -> ScenePackage:
    """Read an exact revision without registry lookup, fallback, engine imports or writes."""
    entry = Path(entry)
    root = entry.absolute().parent.resolve()
    if entry.name != "scene.json":
        raise SceneError("SCENE_INVALID", "entry", "expected scene.json")
    entry = _path(root, entry.name, "entry")
    if not entry.exists(): raise SceneError("SCENE_REVISION_MISSING", "entry", "Scene revision is missing", entry)
    scene, scene_bytes = _read_json(entry)
    manifest_name = _relative(scene.get("manifest"), "scene.manifest")
    manifest, manifest_bytes = _read_json(_path(root, manifest_name, "scene.manifest"))
    _keys(manifest, {"schema_version", "files"}, set(), "manifest")
    _version(manifest, "manifest")
    if not isinstance(manifest["files"], list):
        raise SceneError("SCENE_INVALID", "manifest.files", "expected a file list")
    files = []
    for index, row in enumerate(manifest["files"]):
        _keys(row, {"path", "size_bytes", "sha256"}, set(), f"manifest.files[{index}]")
        files.append(FileEntry(**row))
    files = tuple(files)
    by_path = {f.path:f for f in files if isinstance(f.path, str)}
    calibration_name = _relative(scene.get("calibration"), "scene.calibration")
    if manifest_name in by_path: raise SceneError("SCENE_INVALID", "manifest.files", "manifest must exclude itself")
    for required in (entry.name, calibration_name):
        if required not in by_path: raise SceneError("SCENE_INVALID", "manifest.files", "unregistered required file: " + required)
    verify_files(root, files)
    calibration, calibration_bytes = _read_json(_path(root, calibration_name, "scene.calibration"))
    for name, raw in ((entry.name, scene_bytes), (calibration_name, calibration_bytes)):
        if hashlib.sha256(raw).hexdigest() != by_path[name].sha256:
            raise SceneError("SCENE_INTEGRITY_MISMATCH", name, "loaded Metadata bytes differ from manifest")
    validate_scene(scene, calibration, files=files)
    _required_references(scene, calibration, files)
    _asset_declarations(scene)
    _bound_residuals(calibration, root=root, files=files)
    identity = SceneIdentity(scene["scene_id"], scene["revision"], hashlib.sha256(manifest_bytes).hexdigest())
    if expected is not None:
        _id(expected.scene_id, "expected.scene_id")
        _id(expected.revision, "expected.revision")
        _sha(expected.manifest_sha256, "expected.manifest_sha256")
        if (identity.scene_id, identity.revision) != (expected.scene_id, expected.revision):
            raise SceneError("SCENE_REVISION_MISSING", "expected", "Scene ID or revision does not match")
        if identity.manifest_sha256 != expected.manifest_sha256:
            raise SceneError("SCENE_INTEGRITY_MISMATCH", "expected.manifest_sha256", "manifest bytes changed")
    return ScenePackage(root, identity, _freeze(scene), _freeze(calibration), files,
                        _evidence_access(root, calibration["evidence"]))
