"""Filesystem contract tests; fixtures are synthetic, never migrated v8 packages."""
import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from scene_contract.package import FileEntry, SceneError, SceneIdentity, load_scene, verify_files


def entry(path, data=b"asset"):
    return FileEntry(path, len(data), hashlib.sha256(data).hexdigest())


def test_verify_files_checks_bytes_without_writing(tmp_path):
    asset = tmp_path / "robot.urdf"
    asset.write_bytes(b"asset")
    before = asset.stat()
    verify_files(tmp_path, (entry("robot.urdf"),))
    assert (asset.stat().st_size, asset.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)


@pytest.mark.parametrize("path", ["", "/tmp/asset", "../asset", "a/../asset", "a//b", "./asset",
    "C:/asset", "a\\b", "file:///asset", "https://example.org/asset", ".", "a/", "a\x00b"])
def test_runtime_paths_must_be_canonical_and_package_relative(tmp_path, path):
    with pytest.raises(SceneError) as raised:
        verify_files(tmp_path, (entry(path),))
    assert raised.value.code == "SCENE_INVALID"
    assert raised.value.effect == "not_started"
    assert raised.value.issues[0].field == "files[0].path"


@pytest.mark.parametrize("fault", ["missing", "size", "sha", "duplicate", "directory", "fifo"])
def test_required_files_reject_missing_changed_or_nonregular_payload(tmp_path, fault):
    target = tmp_path / "robot.urdf"
    if fault == "directory": target.mkdir()
    elif fault == "fifo":
        import os
        os.mkfifo(target)
    elif fault != "missing": target.write_bytes(b"asset" if fault == "duplicate" else b"different" if fault == "size" else b"other")
    files = (entry("robot.urdf"),)
    if fault == "duplicate": files += files
    with pytest.raises(SceneError):
        verify_files(tmp_path, files)


def test_runtime_symlink_cannot_escape_package(tmp_path):
    root = tmp_path / "package"; root.mkdir()
    outside = tmp_path / "outside"; outside.write_bytes(b"asset")
    (root / "robot.urdf").symlink_to(outside)
    with pytest.raises(SceneError, match="outside"):
        verify_files(root, (entry("robot.urdf"),))


@pytest.mark.parametrize("size,digest", [(True, "a"*64), (-1, "a"*64), (1, "A"*64), (1, "a"*63)])
def test_manifest_file_record_types_are_strict(tmp_path, size, digest):
    with pytest.raises(SceneError):
        verify_files(tmp_path, (FileEntry("asset", size, digest),))


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def manifest(root):
    files = [asdict(entry(p.relative_to(root).as_posix(), p.read_bytes())) for p in sorted(root.rglob("*"))
             if p.is_file() and p.name != "manifest.json"]
    write_json(root / "manifest.json", {"schema_version": 1, "files": files})


@pytest.fixture
def package_dir(tmp_path):
    root = tmp_path / "original"; root.mkdir()
    write_json(root / "scene.json", {"schema_version": 1, "scene_id": "scene2_builder", "revision": "v8",
        "units": {"length":"m", "angle":"rad", "time":"s", "mass":"kg"},
        "frames": {"world":{"parent":None,"state":"reference",
            "T_parent_from_frame":[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]]},
            "workspace":{"parent":"world","state":"reference",
            "T_parent_from_frame":[[0.,-1.,0.,.125],[1.,0.,0.,-.25],[0.,0.,1.,.01],[0.,0.,0.,1.]]}},
        "objects": {}, "robot": {}, "cameras": {}, "supports": {}, "engines": {},
        "calibration": "calibration.json", "manifest": "manifest.json",
        "validation": {"execution":"READY", "geometry":"UNVALIDATED", "physics":"UNVALIDATED"}})
    write_json(root / "calibration.json", {"schema_version":1, "records":{}, "evidence":{}})
    manifest(root)
    return root


def test_scene_identity_uses_manifest_bytes_and_survives_move(package_dir, tmp_path):
    before = load_scene(package_dir / "scene.json")
    moved = tmp_path / "moved"; shutil.move(package_dir, moved)
    loaded = load_scene(moved / "scene.json", expected=before.identity)
    assert loaded.identity == SceneIdentity("scene2_builder", "v8", hashlib.sha256((moved/"manifest.json").read_bytes()).hexdigest())
    assert loaded.root == moved
    assert loaded.scene["frames"] == before.scene["frames"]
    assert loaded.scene["frames"]["workspace"]["T_parent_from_frame"][0][3] == .125
    assert loaded.scene["validation"]["geometry"] == "UNVALIDATED"
    with pytest.raises(TypeError): loaded.scene["validation"]["geometry"] = "VALIDATED"


@pytest.mark.parametrize("field,value,code", [("revision","v9","SCENE_REVISION_MISSING"),
    ("scene_id","different","SCENE_REVISION_MISSING"), ("manifest_sha256","0"*64,"SCENE_INTEGRITY_MISMATCH")])
def test_expected_identity_never_selects_latest(package_dir, field, value, code):
    fields = asdict(load_scene(package_dir/"scene.json").identity); fields[field] = value
    with pytest.raises(SceneError) as raised: load_scene(package_dir/"scene.json", expected=SceneIdentity(**fields))
    assert raised.value.code == code


@pytest.mark.parametrize("payload", ['{"schema_version":1,"schema_version":1}',
    '{"schema_version":NaN}', '{"value":1e999}', '{"x":Infinity}', '{'])
def test_metadata_rejects_duplicate_keys_nonfinite_and_invalid_json(package_dir, payload):
    (package_dir/"scene.json").write_text(payload)
    with pytest.raises(SceneError): load_scene(package_dir/"scene.json")


@pytest.mark.parametrize("field,value", [("schema_version",True),("schema_version",2),
    ("scene_id",""),("revision",8),("unexpected",42)])
def test_metadata_header_fields_are_checked(package_dir, field, value):
    scene = json.loads((package_dir/"scene.json").read_text()); scene[field] = value
    write_json(package_dir/"scene.json",scene); manifest(package_dir)
    with pytest.raises(SceneError): load_scene(package_dir/"scene.json")


def test_manifest_must_register_metadata_and_exclude_itself(package_dir):
    data=json.loads((package_dir/"manifest.json").read_text())
    data["files"]=[r for r in data["files"] if r["path"]!="calibration.json"]
    write_json(package_dir/"manifest.json",data)
    with pytest.raises(SceneError,match="calibration.json"): load_scene(package_dir/"scene.json")


@pytest.mark.parametrize("reference", ["asset_path", "required_files", "asset_paths", "parameters_file"])
def test_declared_runtime_dependencies_must_be_in_manifest(package_dir, reference):
    scene = json.loads((package_dir/"scene.json").read_text())
    asset = "assets/robot/finger_convex_parts.json"
    node = {reference:[asset] if reference.endswith("s") else asset}
    scene["engines"]["mujoco"] = {"asset_path":"scene.xml", **node}
    (package_dir/"scene.xml").write_bytes(b"synthetic MJCF entry")
    write_json(package_dir/"scene.json",scene); manifest(package_dir)
    # File presence is insufficient: deliberately leave it out of the manifest.
    (package_dir/asset).parent.mkdir(parents=True); (package_dir/asset).write_text("{}")
    with pytest.raises(SceneError,match="unregistered") as raised: load_scene(package_dir/"scene.json")
    assert reference in raised.value.issues[0].field


def calibration_record(source, execution):
    return {"kind":"encoder_mapping", "target":"robot", "algorithm_id":"so101_precision_v1",
        "source_model_sha256":source, "execution_model_sha256":execution, "joint_order":["joint_a"],
        "parameters":{}, "application":{"mode":"runtime", "phase":"device_observation",
            "input_space":"homed_count", "output_space":"model_rad", "order_index":0},
        "validation":{"physical_verified":False}, "evidence_ids":[]}


def test_calibration_model_evidence_hash_must_be_in_manifest(package_dir):
    scene=json.loads((package_dir/"scene.json").read_text())
    scene["robot"]={"frame_id":"world","joint_order":["joint_a"]}
    write_json(package_dir/"scene.json",scene)
    current=package_dir/"current.urdf"; current.write_bytes(b"current model")
    saved=package_dir/"historical.urdf"; saved.write_bytes(b"saved model")
    rec=calibration_record(entry("",saved.read_bytes()).sha256, entry("",current.read_bytes()).sha256)
    write_json(package_dir/"calibration.json",{"schema_version":1,"records":{"encoder":rec},"evidence":{}})
    manifest(package_dir)
    good=load_scene(package_dir/"scene.json")
    assert good.calibration["records"]["encoder"]["validation"]["physical_verified"] is False
    data=json.loads((package_dir/"manifest.json").read_text())
    data["files"]=[r for r in data["files"] if r["path"]!="historical.urdf"]
    write_json(package_dir/"manifest.json",data)
    with pytest.raises(SceneError,match="source_model_sha256"): load_scene(package_dir/"scene.json")


def test_calibration_parameter_file_and_baked_asset_are_required(package_dir):
    rec=calibration_record("0"*64,"1"*64)
    rec.pop("parameters");rec["parameters_file"]="calibration/profile.json"
    rec["application"]={"mode":"baked", "asset_paths":["assets/robot/calibrated.usda"],
                        "input_calibration_ids":[],"order_index":0}
    write_json(package_dir/"calibration.json",{"schema_version":1,"records":{"mapping":rec},"evidence":{}})
    manifest(package_dir)
    with pytest.raises(SceneError): load_scene(package_dir/"scene.json")


@pytest.mark.parametrize("location_kind,status", [("missing","unavailable"),("available","available"),
    ("changed","mismatch"),("remote","unchecked")])
def test_optional_external_evidence_never_blocks_execution(package_dir, tmp_path, location_kind, status):
    original=tmp_path/"original-photo"; original.write_bytes(b"photo")
    location=str(original)
    if location_kind=="missing": original.unlink()
    if location_kind=="changed": original.write_bytes(b"different")
    if location_kind=="remote": location="https://example.invalid/evidence"
    data={"schema_version":1,"records":{},"evidence":{"photo":{
        "sha256":hashlib.sha256(b"photo").hexdigest(),"location":location}}}
    write_json(package_dir/"calibration.json",data);manifest(package_dir)
    loaded=load_scene(package_dir/"scene.json")
    assert loaded.evidence_access[0].access==status
    assert loaded.scene["validation"]["geometry"]=="UNVALIDATED"


@pytest.fixture
def asset_package(package_dir):
    paths=["assets/scene.xml","assets/calibrated.urdf","assets/source.urdf",
           "assets/finger_convex_parts.json","assets/usd_contact_pads.json","calibration/profile.json"]
    for path in paths:
        p=package_dir/path;p.parent.mkdir(exist_ok=True,parents=True);p.write_bytes(path.encode())
    scene=json.loads((package_dir/"scene.json").read_text())
    scene["engines"]={"mujoco":{"asset_path":paths[0], "required_files":paths[3:5]}}
    scene["robot"]={"frame_id":"world","joint_order":["joint_a"],"source_model":{"asset_path":paths[2]},"execution_models":{"mujoco":{"asset_path":paths[1]}}}
    rec=calibration_record(entry("",paths[2].encode()).sha256,entry("",paths[1].encode()).sha256)
    rec.pop("parameters");rec["parameters_file"]=paths[5]
    write_json(package_dir/"scene.json",scene)
    write_json(package_dir/"calibration.json",{"schema_version":1,"records":{"encoder":rec},"evidence":{}})
    manifest(package_dir)
    return package_dir


def test_package_move_preserves_declared_finger_and_calibration_dependencies(asset_package,tmp_path):
    loaded=load_scene(asset_package/"scene.json")
    dest=tmp_path/"elsewhere";shutil.move(asset_package,dest)
    result=load_scene(dest/"scene.json",expected=loaded.identity)
    assert result.identity==loaded.identity
    assert len(result.files)==8
    assert result.calibration["records"]["encoder"]["parameters_file"]=="calibration/profile.json"


@pytest.mark.parametrize("path",["assets/finger_convex_parts.json","assets/usd_contact_pads.json",
    "assets/source.urdf","assets/calibrated.urdf","calibration/profile.json"])
def test_omitted_required_dependency_is_rejected_even_when_file_exists(asset_package,path):
    doc=json.loads((asset_package/"manifest.json").read_text())
    doc["files"]=[r for r in doc["files"] if r["path"]!=path]
    write_json(asset_package/"manifest.json",doc)
    with pytest.raises(SceneError):load_scene(asset_package/"scene.json")


@pytest.mark.parametrize("data", [{"mujoco":{}},{"mujoco":{"required_files":[]}},
    {"mujoco":None},{"unknown_engine":{"asset_path":"scene.json"}}])
def test_declared_engine_requires_native_entry_and_known_engine_id(package_dir,data):
    scene=json.loads((package_dir/"scene.json").read_text());scene["engines"]=data
    write_json(package_dir/"scene.json",scene);manifest(package_dir)
    with pytest.raises(SceneError):load_scene(package_dir/"scene.json")


def test_mesh_declaration_cannot_omit_its_asset_path(package_dir):
    scene=json.loads((package_dir/"scene.json").read_text())
    scene["objects"]={"block":{"visual":{"kind":"mesh","asset_pth":"missing.stl"}}}
    write_json(package_dir/"scene.json",scene);manifest(package_dir)
    with pytest.raises(SceneError):load_scene(package_dir/"scene.json")


def test_manifest_cannot_register_itself(package_dir):
    data=json.loads((package_dir/"manifest.json").read_text())
    data["files"].append(asdict(entry("manifest.json",(package_dir/"manifest.json").read_bytes())))
    write_json(package_dir/"manifest.json",data)
    with pytest.raises(SceneError,match="itself"):load_scene(package_dir/"scene.json")


def test_internal_symlink_is_allowed_but_parent_symlink_escape_is_not(package_dir,tmp_path):
    (package_dir/"real").write_bytes(b"asset");(package_dir/"alias").symlink_to("real")
    verify_files(package_dir,(entry("alias"),))
    outside=tmp_path/"external";outside.mkdir();(outside/"data").write_bytes(b"asset")
    (package_dir/"escaped").symlink_to(outside,target_is_directory=True)
    with pytest.raises(SceneError):verify_files(package_dir,(entry("escaped/data"),))


@pytest.mark.parametrize("value", [None, [], {"schema_version":True,"files":[]},
    {"schema_version":2,"files":[]}, {"schema_version":1,"files":{},"extra":0},
    {"schema_version":1,"files":[{"path":"scene.json","size_bytes":0,"sha256":"0"*64,"extra":0}]}])
def test_malformed_manifest_fails_with_structured_error(package_dir,value):
    write_json(package_dir/"manifest.json",value)
    with pytest.raises(SceneError) as raised:load_scene(package_dir/"scene.json")
    assert raised.value.code in ("SCENE_INVALID","SCHEMA_UNSUPPORTED")
    assert raised.value.issues and raised.value.effect=="not_started"


def test_missing_revision_fails_without_directory_search(tmp_path):
    with pytest.raises(SceneError) as raised:load_scene(tmp_path/"absent/scene.json")
    assert raised.value.code=="SCENE_REVISION_MISSING"


def test_duplicate_object_id_is_not_silently_overwritten(package_dir):
    text=(package_dir/"scene.json").read_text().replace('"objects": {}','"objects": {"block": {}, "block": {}}')
    (package_dir/"scene.json").write_text(text);manifest(package_dir)
    with pytest.raises(SceneError,match="duplicate JSON key"):load_scene(package_dir/"scene.json")


def test_native_prim_path_is_not_treated_as_external_asset(package_dir):
    scene=json.loads((package_dir/"scene.json").read_text())
    scene["objects"]={"robot":{"bindings":{"isaac":{"asset_path":"robot.usda","prim_path":"/World/Robot"}}}}
    (package_dir/"robot.usda").write_bytes(b"synthetic native asset")
    write_json(package_dir/"scene.json",scene);manifest(package_dir)
    assert load_scene(package_dir/"scene.json").scene["objects"]["robot"]["bindings"]["isaac"]["prim_path"]=="/World/Robot"


def test_runtime_dependency_does_not_fall_back_to_working_directory(package_dir,tmp_path,monkeypatch):
    scene=json.loads((package_dir/"scene.json").read_text())
    scene["engines"]={"mujoco":{"asset_path":"scene.xml"}}
    write_json(package_dir/"scene.json",scene);manifest(package_dir)
    (tmp_path/"scene.xml").write_bytes(b"present outside package")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SceneError,match="unregistered"):load_scene(package_dir/"scene.json")


def test_loader_only_reads_package_and_evidence(asset_package):
    before={p.relative_to(asset_package): (p.stat().st_size,p.stat().st_mtime_ns,p.read_bytes())
            for p in asset_package.rglob("*") if p.is_file()}
    load_scene(asset_package/"scene.json")
    after={p.relative_to(asset_package): (p.stat().st_size,p.stat().st_mtime_ns,p.read_bytes())
           for p in asset_package.rglob("*") if p.is_file()}
    assert before==after


def test_absolute_internal_symlink_is_not_portable(package_dir):
    (package_dir/"real").write_bytes(b"asset")
    (package_dir/"alias").symlink_to(package_dir/"real")
    with pytest.raises(SceneError,match="portable"):
        verify_files(package_dir,(entry("alias"),))


@pytest.mark.parametrize("fault",["cycle","unknown_object_frame","bad_local_transform","geometry_double_transform"])
def test_load_scene_enforces_frame_graph_and_geometry_basis(package_dir,fault):
    scene=json.loads((package_dir/"scene.json").read_text())
    if fault=="cycle":scene["frames"]["workspace"]["parent"]="workspace"
    else:
        geometry={"kind":"primitive","local_transform":[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]]}
        scene["objects"]={"block":{"frame_id":"world","collision":[geometry]}}
        if fault=="unknown_object_frame":scene["objects"]["block"]["frame_id"]="missing"
        elif fault=="bad_local_transform":geometry["local_transform"][3][0]=.1
        else:geometry["frame_id"]="world"
    write_json(package_dir/"scene.json",scene);manifest(package_dir)
    with pytest.raises(SceneError):load_scene(package_dir/"scene.json")


def calibration_scene():
    scene={"schema_version":1,"scene_id":"calibration_test","revision":"r1",
        "units":{"length":"m","angle":"rad","time":"s","mass":"kg"},
        "frames":{"world":{"parent":None,"state":"reference",
            "T_parent_from_frame":[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}},
        "objects":{},"robot":{"frame_id":"world","joint_order":["joint_a"]},
        "cameras":{},"supports":{},"engines":{},"validation":{},"calibration":"calibration.json","manifest":"manifest.json"}
    return scene


def calibration_records():
    encoder=calibration_record("a"*64,"b"*64)
    mapping={"schema":"so101.precision-joint-mapping/1","profile":{"role":"follower","urdf_sha256":"b"*64},"joint_order":["joint_a"]}
    mapping["sha256"]=hashlib.sha256(json.dumps(mapping,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    encoder["parameters"]=mapping
    residual={**calibration_record("b"*64,"c"*64),"kind":"robot_residual","algorithm_id":"precision_bound_residual",
        "parameters":{"offset_rad":[.03],"precision_mapping_sha256":mapping["sha256"]},"application":{"mode":"baked","asset_paths":["assets/robot/calibrated.urdf"],
            "input_calibration_ids":["encoder"],"order_index":1}}
    return {"schema_version":1,"records":{"encoder":encoder,"residual":residual},"evidence":{}}


def test_encoder_dependency_is_not_itself_baked_into_geometry():
    from scene_contract.package import validate_scene
    calibration=calibration_records()
    validate_scene(calibration_scene(),calibration)
    assert calibration["records"]["encoder"]["application"]["mode"]=="runtime"
    assert calibration["records"]["residual"]["application"]["input_calibration_ids"]==["encoder"]


@pytest.mark.parametrize("fault",["duplicate_baked_runtime","duplicate_runtime","unknown_dependency","cycle",
    "same_order","reverse_order","spaces","joint_order","unknown_phase","unknown_target","baked_with_runtime_phase",
    "residual_on_hardware_command","repeated_asset","unknown_frame","missing_order"])
def test_invalid_calibration_application_relationships_are_rejected(fault):
    import copy
    from scene_contract.package import validate_scene
    calibration=calibration_records();records=calibration["records"]
    if fault=="duplicate_baked_runtime":
        clone=copy.deepcopy(records["residual"]);clone["application"]={"mode":"runtime","phase":"scene_initialization",
            "input_space":"model_frame","output_space":"model_frame","order_index":2};records["again"]=clone
    elif fault=="duplicate_runtime":records["again"]=copy.deepcopy(records["encoder"])
    elif fault=="unknown_dependency":records["residual"]["application"]["input_calibration_ids"]=["missing"]
    elif fault=="cycle":records["encoder"]["application"]["input_calibration_ids"]=["residual"]
    elif fault in ("same_order","reverse_order","spaces"):
        clone=copy.deepcopy(records["encoder"]);clone["algorithm_id"]="another_correction"
        clone["application"].update(input_calibration_ids=["encoder"],order_index=0 if fault=="same_order" else 1)
        if fault=="reverse_order":records["encoder"]["application"]["order_index"]=2
        if fault=="spaces":clone["application"]["input_space"]="native_degree"
        records["next"]=clone
    elif fault=="joint_order":records["encoder"]["joint_order"]=["other"]
    elif fault=="unknown_phase":records["encoder"]["application"]["phase"]="anytime"
    elif fault=="unknown_target":records["encoder"]["target"]="missing"
    elif fault=="baked_with_runtime_phase":records["residual"]["application"]["phase"]="device_command"
    elif fault=="residual_on_hardware_command":records["residual"]["application"]={"mode":"runtime","phase":"device_command",
            "input_space":"model_rad","output_space":"model_rad","order_index":1}
    elif fault=="repeated_asset":records["residual"]["application"]["asset_paths"]*=2
    elif fault=="unknown_frame":records["encoder"]["frame_ids"]=["missing"]
    else:records["encoder"]["application"].pop("order_index")
    with pytest.raises(SceneError):validate_scene(calibration_scene(),calibration)


def test_encoder_observation_and_command_are_distinct_phases():
    import copy
    from scene_contract.package import validate_scene
    calibration=calibration_records();command=copy.deepcopy(calibration["records"]["encoder"])
    command["application"].update(phase="device_command",input_space="model_rad",output_space="native_degree")
    calibration["records"]["command"]=command
    validate_scene(calibration_scene(),calibration)


def test_leader_and_follower_observations_have_independent_input_spaces():
    import copy
    from scene_contract.package import validate_scene
    calibration=calibration_records()
    calibration["records"]["encoder"]["application"]["input_space"]="follower_homed_count"
    leader=copy.deepcopy(calibration["records"]["encoder"])
    leader["application"]["input_space"]="leader_homed_count"
    leader["parameters"]={"role":"leader"}
    calibration["records"]["leader"]=leader
    validate_scene(calibration_scene(),calibration)


def test_bound_residual_cannot_omit_its_encoder_dependency():
    from scene_contract.package import validate_scene
    calibration=calibration_records()
    calibration["records"]["residual"]["application"]["input_calibration_ids"]=[]
    with pytest.raises(SceneError):validate_scene(calibration_scene(),calibration)


@pytest.mark.parametrize("fault",["residual_model_mismatch","baked_model_mismatch","bad_joint_type","bad_parameter_path"])
def test_calibration_identity_and_malformed_fields_are_checked(fault):
    from scene_contract.package import validate_scene
    calibration=calibration_records();records=calibration["records"]
    files=(FileEntry("assets/robot/calibrated.urdf",1,"c"*64),)
    if fault=="residual_model_mismatch":records["residual"]["source_model_sha256"]="d"*64
    elif fault=="baked_model_mismatch":files=(FileEntry("assets/robot/calibrated.urdf",1,"d"*64),)
    elif fault=="bad_joint_type":
        records["encoder"]["joint_order"]=None;records["encoder"]["application"]["joint_order"]=["joint_a"]
    else:records["encoder"].pop("parameters");records["encoder"]["parameters_file"]=["invalid"]
    with pytest.raises(SceneError):validate_scene(calibration_scene(),calibration,files=files)


def test_same_parameter_bytes_under_two_paths_do_not_bypass_duplicate_check():
    import copy
    from scene_contract.package import validate_scene
    calibration=calibration_records();record=calibration["records"]["encoder"]
    record.pop("parameters");record["parameters_file"]="calibration/first.json"
    another=copy.deepcopy(record);another["parameters_file"]="calibration/alias.json";another["application"]["order_index"]=1
    calibration["records"]["another"]=another
    files=(FileEntry("calibration/first.json",1,"d"*64),FileEntry("calibration/alias.json",1,"d"*64),
           FileEntry("assets/robot/calibrated.urdf",1,"c"*64))
    with pytest.raises(SceneError,match="duplicate calibration"):validate_scene(calibration_scene(),calibration,files=files)


@pytest.mark.parametrize("fault",["no_sensor_identity","no_frame_ids"])
def test_camera_calibration_needs_its_own_identity_and_frames(fault):
    from scene_contract.package import validate_scene
    scene=calibration_scene();scene["cameras"]={"side":{"frame_id":"world"}}
    record={"kind":"camera_intrinsic","target":"side","algorithm_id":"measured_camera",
        "parameters":{"K":[[800,0,320],[0,800,240],[0,0,1]]},"sensor_identity":{"sensor_id":"side"},
        "frame_ids":["world"],"application":{"mode":"runtime","phase":"camera_render",
            "input_space":"raw_pixels","output_space":"render_pixels","order_index":0},
        "validation":{"status":"UNVALIDATED"},"evidence_ids":[]}
    record.pop("sensor_identity" if fault=="no_sensor_identity" else "frame_ids")
    with pytest.raises(SceneError):validate_scene(scene,{"schema_version":1,"records":{"side":record},"evidence":{}})


@pytest.mark.parametrize("fault",["wrong_binding","tampered_mapping","wrong_mapping_model"])
def test_v8_bound_residual_requires_exact_mapping_fingerprint(fault):
    from scene_contract.package import validate_scene
    calibration=calibration_records();mapping=calibration["records"]["encoder"]["parameters"]
    if fault=="wrong_binding":calibration["records"]["residual"]["parameters"]["precision_mapping_sha256"]="0"*64
    elif fault=="tampered_mapping":mapping["profile"]["role"]="leader"
    else:
        mapping["profile"]["urdf_sha256"]="d"*64;mapping.pop("sha256")
        mapping["sha256"]=hashlib.sha256(json.dumps(mapping,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        calibration["records"]["residual"]["parameters"]["precision_mapping_sha256"]=mapping["sha256"]
    with pytest.raises(SceneError):validate_scene(calibration_scene(),calibration)


def test_alternative_encoder_parameter_representations_cannot_both_apply():
    import copy
    from scene_contract.package import validate_scene
    calibration=calibration_records();alias=copy.deepcopy(calibration["records"]["encoder"])
    alias.pop("parameters");alias["parameters_file"]="calibration/alias.json";alias["application"]["order_index"]=2
    calibration["records"]["alias"]=alias
    with pytest.raises(SceneError,match="duplicate calibration"):validate_scene(calibration_scene(),calibration)


@pytest.fixture
def bound_package(package_dir):
    scene=calibration_scene();calibration=calibration_records()
    model_paths=["old.urdf","current.urdf","assets/robot/calibrated.urdf"]
    hashes=[]
    for name in model_paths:
        p=package_dir/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name)
        hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
    encoder=calibration["records"]["encoder"];residual=calibration["records"]["residual"]
    encoder.update(source_model_sha256=hashes[0],execution_model_sha256=hashes[1])
    residual.update(source_model_sha256=hashes[1],execution_model_sha256=hashes[2])
    mapping=encoder.pop("parameters");mapping.pop("sha256");mapping["profile"]["urdf_sha256"]=hashes[1]
    mapping["sha256"]=hashlib.sha256(json.dumps(mapping,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    residual["parameters"]["precision_mapping_sha256"]=mapping["sha256"]
    encoder["parameters_file"]="mapping.json";write_json(package_dir/"mapping.json",mapping)
    residual["parameters_file"]="residual.json";write_json(package_dir/"residual.json",residual.pop("parameters"))
    write_json(package_dir/"scene.json",scene);write_json(package_dir/"calibration.json",calibration);manifest(package_dir)
    return package_dir


def test_file_based_bound_calibration_loads_and_survives_package_move(bound_package,tmp_path):
    loaded=load_scene(bound_package/"scene.json")
    moved=tmp_path/"relocated";shutil.move(bound_package,moved)
    result=load_scene(moved/"scene.json",expected=loaded.identity)
    assert result.calibration==loaded.calibration


def test_metadata_validation_accepts_frozen_loaded_data(bound_package):
    from scene_contract.package import validate_scene
    loaded=load_scene(bound_package/"scene.json")
    validate_scene(loaded.scene,loaded.calibration,files=loaded.files)


@pytest.mark.parametrize("field,unit",[("length","mm"),("angle","degree"),("time","ms")])
def test_units_are_not_silently_converted(field,unit):
    from scene_contract.package import validate_scene
    scene=calibration_scene();scene["units"][field]=unit
    with pytest.raises(SceneError,match="scene.units"):validate_scene(scene,calibration_records())


@pytest.mark.parametrize("file,field,value",[("mapping.json","sha256","0"*64),
    ("residual.json","precision_mapping_sha256","0"*64), ("mapping.json","joint_order",42)])
def test_file_based_binding_is_checked_even_after_manifest_is_recomputed(bound_package,file,field,value):
    data=json.loads((bound_package/file).read_text());data[field]=value
    write_json(bound_package/file,data);manifest(bound_package)
    with pytest.raises(SceneError):load_scene(bound_package/"scene.json")
