"""T01 declaration tests; no v8 predicates or engines are implemented here."""
import sys

import pytest

from robot_learning_workbench.tasks.registry import TaskError, read_module_names


def test_module_list_is_data_only_and_preserves_order(tmp_path):
    path=tmp_path/"task_modules.yaml"
    path.write_text("# Explicit order\nmodules:\n  - not_imported_task_b\n  - not_imported_task_a\n")
    assert read_module_names(path)==("not_imported_task_b","not_imported_task_a")
    assert "not_imported_task_b" not in sys.modules


def test_empty_explicit_list_is_valid(tmp_path):
    path=tmp_path/"task_modules.yaml";path.write_text("modules: []\n")
    assert read_module_names(path)==()


@pytest.mark.parametrize("text",["modules: [a, a]", "modules: a", "modules: [true]", "modules: [../a.py]",
    "modules: ['a:b']", "modules: ['a..b']", "modules: [a]\nmodules: [b]", "modules: []\nextra: true",
    "modules: [!!python/object/apply:os.system ['echo forbidden']]", "modules: &x [*x]", "[]", "{}", "modules: [class]"])
def test_invalid_module_lists_are_rejected_without_import(tmp_path,text):
    path=tmp_path/"task_modules.yaml";path.write_text(text)
    with pytest.raises(TaskError) as raised:read_module_names(path)
    assert raised.value.code=="TASK_MODULES_INVALID"
    assert raised.value.effect=="not_started"
    assert raised.value.issues[0].field


def test_module_list_read_errors_are_structured(tmp_path):
    with pytest.raises(TaskError):read_module_names(tmp_path/"missing.yaml")

from dataclasses import dataclass
import importlib
from robot_learning_workbench.tasks.registry import FunctionSpec, load_registry, resolve


MODULE = '''from dataclasses import dataclass
from robot_learning_workbench.tasks.registry import FunctionSpec
@dataclass(frozen=True)
class Params:
    threshold: float = 0.03
def check(sample, *, params):
    raise AssertionError("registration must not execute predicates")
def create(*, params, episode):
    raise AssertionError("registration must not instantiate trackers")
FUNCTIONS = {
    "test.check": FunctionSpec(kind="predicate", stages={"annotation"}, engines={"mujoco"}, params_type=Params, callable=check),
    "test.tracker": FunctionSpec(kind="tracker", stages={"annotation"}, engines={"independent"}, params_type=Params, callable=create),
}
'''


@pytest.fixture
def task_module(tmp_path, monkeypatch):
    import uuid
    name="t01_"+uuid.uuid4().hex
    monkeypatch.syspath_prepend(str(tmp_path))
    def write(body=MODULE):
        (tmp_path/(name+".py")).write_text(body)
        importlib.invalidate_caches()
        return name
    yield write
    sys.modules.pop(name,None)


def test_explicit_registration_keeps_plain_callable_without_running_it(task_module,tmp_path):
    name=task_module()
    path=tmp_path/"task_modules.yaml";path.write_text(f"modules: [{name}]\n")
    registry=load_registry(read_module_names(path))
    spec=resolve(registry,"test.check",kind="predicate",stage="annotation",engine="mujoco")
    assert spec.callable is sys.modules[name].check
    assert registry.modules==(name,)
    assert registry.source_sha256
    assert resolve(registry,"test.tracker",kind="tracker",stage="annotation",engine=None).callable is sys.modules[name].create
    with pytest.raises(TypeError):registry.functions["extra"]=spec
    with pytest.raises(AttributeError):spec.engines.add("isaac")


@pytest.mark.parametrize("change",[
    'kind="bad"', 'stages={"train"}', 'engines={"unknown"}',
    'engines={"independent", "mujoco"}', 'contract_version=True', 'contract_version=2',
    'params_type=dict', 'requires=("eval(x)",)', 'bindings={"datagen": {"phase": "post_step"}}',
    'bindings={"annotation": {"phase": "bad"}}',
])
def test_invalid_declarations(task_module,change):
    body=MODULE.replace('kind="predicate", stages={"annotation"}, engines={"mujoco"}, params_type=Params, callable=check',
        'kind="predicate", stages={"annotation"}, engines={"mujoco"}, params_type=Params, callable=check, '+change)
    # Replace a keyword rather than creating a Python syntax error.
    key=change.split('=')[0]
    original={'kind':'kind="predicate", ', 'stages':'stages={"annotation"}, ', 'engines':'engines={"mujoco"}, ', 'params_type':'params_type=Params, '}.get(key)
    if original:body=body.replace(original,'',1)
    with pytest.raises(TaskError) as raised:load_registry((task_module(body),))
    assert raised.value.code=="TASK_DECLARATION_INVALID"


@pytest.mark.parametrize("body",[
    MODULE.replace('"test.check"','"bad/name"'),
    MODULE.replace('FUNCTIONS = {','DECLARATIONS = {'),
    MODULE.replace('def check(sample, *, params):','def check(sample, params):'),
    MODULE.replace('def check(sample, *, params):','async def check(sample, *, params):'),
    MODULE.replace('def check(sample, *, params):','def check(sample, *, params, extra):'),
    MODULE.replace('def create(*, params, episode):','def create(params, episode):'),
    MODULE.replace('callable=check','callable="some.module:check"'),
])
def test_bad_names_missing_declaration_and_callable_contract(task_module,body):
    with pytest.raises(TaskError):load_registry((task_module(body),))


def test_duplicate_modules_names_and_import_failures(task_module):
    name=task_module()
    with pytest.raises(TaskError):load_registry((name,name))
    with pytest.raises(TaskError) as raised:load_registry((name,"t01_missing_module"))
    assert raised.value.__cause__ is not None
    with pytest.raises(TaskError):load_registry([name])


@pytest.mark.parametrize("name,kind,stage,engine,code",[
    ("missing","predicate","annotation","mujoco","TASK_UNKNOWN"),
    ("test.check","acceptance","annotation","mujoco","TASK_UNSUPPORTED"),
    ("test.check","predicate","source","mujoco","TASK_UNSUPPORTED"),
    ("test.check","predicate","annotation","isaac","TASK_UNSUPPORTED"),
    ("test.check","predicate","annotation",None,"TASK_UNSUPPORTED"),
])
def test_resolve_refuses_fallback(task_module,name,kind,stage,engine,code):
    with pytest.raises(TaskError) as raised:resolve(load_registry((task_module(),)),name,kind=kind,stage=stage,engine=engine)
    assert raised.value.code==code


def test_only_listed_modules_imported_and_duplicate_global_names_refused(task_module,tmp_path):
    (tmp_path/"unlisted_t01.py").write_text('raise AssertionError("must not discover")')
    name=task_module()
    registry=load_registry((name,))
    assert "unlisted_t01" not in sys.modules
    (tmp_path/"duplicate_t01.py").write_text(f"from {name} import FUNCTIONS")
    try:
        with pytest.raises(TaskError):load_registry((name,"duplicate_t01"))
    finally:sys.modules.pop("duplicate_t01",None)
    assert len(registry.functions)==2

from robot_learning_workbench.tasks.registry import validate_params


PARAM_MODULE = '''from dataclasses import dataclass, field
from typing import Literal
from robot_learning_workbench.tasks.registry import FunctionSpec
@dataclass(frozen=True)
class Bounds:
    xy: tuple[float, float]
@dataclass(frozen=True)
class Params:
    object_id: str = field(metadata={"reference": "object"})
    frame_id: str = field(metadata={"reference": "frame"})
    support_id: str = field(metadata={"reference": "support"})
    bounds: Bounds
    enabled: bool = True
    count: int = 2
    mode: Literal["fixed", "random"] = "fixed"
    optional: float | None = None
    weights: dict[str, float] = field(default_factory=dict)
    targets: list[str] = field(default_factory=list, metadata={"reference": "object"})
def check(sample, *, params):
    raise AssertionError("validation must not run predicate")
def validate_params(params, scene):
    if params.count < 1:raise ValueError("count must be positive")
FUNCTIONS={"test.refs": FunctionSpec(kind="predicate", stages={"annotation"}, engines={"independent"}, params_type=Params, callable=check)}
'''


@pytest.fixture
def scene(tmp_path):
    import hashlib,json
    from scene_contract.package import load_scene
    root=tmp_path/"scene";root.mkdir()
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    data={"schema_version":1,"scene_id":"test_scene","revision":"r1","units":{"length":"m","angle":"rad","time":"s","mass":"kg"},
        "frames":{"world":{"parent":None,"T_parent_from_frame":identity,"state":"reference"}},
        "objects":{"red":{"frame_id":"world","role":"task_object"},"blue":{"frame_id":"world","role":"task_object"},"cup":{"frame_id":"world","role":"environment"}},
        "robot":{},"cameras":{},"supports":{"table":{"frame_id":"world"}},"engines":{},"validation":{},"calibration":"calibration.json","manifest":"manifest.json"}
    (root/"scene.json").write_text(json.dumps(data))
    (root/"calibration.json").write_text(json.dumps({"schema_version":1,"records":{},"evidence":{}}))
    entries=[{"path":p.name,"size_bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in (root/"scene.json",root/"calibration.json")]
    (root/"manifest.json").write_text(json.dumps({"schema_version":1,"files":entries}))
    return load_scene(root/"scene.json")


def values():return {"object_id":"red","frame_id":"world","support_id":"table","bounds":{"xy":[0.1,0.2]}}


def parameters(registry,data,scene=None,**kwargs):
    return validate_params(registry,"test.refs",data,kind="predicate",stage="annotation",scene=scene,**kwargs)


def test_typed_params_and_real_scene_contract(task_module,scene):
    registry=load_registry((task_module(PARAM_MODULE),))
    data=values();data["targets"]=["cup"]
    result=parameters(registry,data,scene,selected_objects=("red",))
    assert result.bounds.xy==(0.1,0.2)
    assert result.enabled is True and result.count==2 and result.optional is None
    assert result.targets==["cup"]
    data["targets"].append("blue")
    assert result.targets==["cup"]
    assert scene.identity.revision=="r1"


@pytest.mark.parametrize("change",[
    {"extra":0}, {"count":True}, {"count":1.5}, {"count":0}, {"enabled":1}, {"mode":"unknown"},
    {"optional":float("nan")}, {"optional":float("inf")}, {"optional":"0.1"},
    {"bounds":{"xy":[1]}}, {"bounds":{"xy":[True,0.1]}}, {"bounds":{"xy":[1,2],"extra":1}},
    {"weights":{"x":"0.2"}}, {"weights":{1:0.2}}, {"object_id":"unknown"}, {"frame_id":"unknown"}, {"support_id":"unknown"},
    {"targets":["unknown"]}, {"targets":"red"},
])
def test_bad_params_and_scene_references(task_module,scene,change):
    registry=load_registry((task_module(PARAM_MODULE),))
    with pytest.raises(TaskError) as raised:parameters(registry,values()|change,scene)
    assert raised.value.code=="TASK_PARAMS_INVALID"
    assert raised.value.issues[0].field
    assert raised.value.effect=="not_started"


def test_missing_scene_required_param_and_selection(task_module,scene):
    registry=load_registry((task_module(PARAM_MODULE),))
    with pytest.raises(TaskError):parameters(registry,values())
    with pytest.raises(TaskError):parameters(registry,{k:v for k,v in values().items() if k!="bounds"},scene)
    with pytest.raises(TaskError) as raised:parameters(registry,values(),scene,selected_objects=("blue",))
    assert raised.value.code=="OBJECT_NOT_SELECTED"
    with pytest.raises(TaskError):parameters(registry,values(),scene,selected_objects=("unknown",))


def test_scalar_params_do_not_require_scene_and_no_task_call(task_module):
    registry=load_registry((task_module(),))
    params=validate_params(registry,"test.check",{},kind="predicate",stage="annotation",engine="mujoco")
    assert params.threshold==0.03


@pytest.mark.parametrize("body",[
    PARAM_MODULE.replace('metadata={"reference": "object"}','metadata={"reference": "bad"}',1),
    PARAM_MODULE.replace('count: int = 2','count: object = 2'),
    PARAM_MODULE.replace('count: int = 2','count: int = True'),
    PARAM_MODULE.replace('object_id: str','object_id: float',1),
])
def test_bad_parameter_schemas_rejected_at_registration(task_module,body):
    with pytest.raises(TaskError) as raised:load_registry((task_module(body),))
    assert raised.value.code=="TASK_DECLARATION_INVALID"


def test_invalid_custom_validator_result(task_module,scene):
    body=PARAM_MODULE.replace('if params.count < 1:raise ValueError("count must be positive")','return True')
    registry=load_registry((task_module(body),))
    with pytest.raises(TaskError):parameters(registry,values(),scene)


BINDING_MODULE = MODULE + '''
FUNCTIONS["test.accept"] = FunctionSpec(kind="acceptance", stages={"annotation"}, engines={"mujoco"}, params_type=Params,
    callable=lambda final, *, params: False, requires=("signals.grasp",),
    bindings={"annotation":{"phase":"episode_end", "signals":{"grasp":{"function":"test.tracker", "params":{"threshold":0.1}}}}})
'''


def test_literal_bindings_checked_and_preserved_without_runtime_scheduler(task_module):
    registry=load_registry((task_module(BINDING_MODULE),))
    spec=resolve(registry,"test.accept",kind="acceptance",stage="annotation",engine="mujoco")
    assert spec.bindings["annotation"]["signals"]["grasp"]["function"]=="test.tracker"
    with pytest.raises(TypeError):spec.bindings["annotation"]["phase"]="pre_step"


@pytest.mark.parametrize("body",[
    BINDING_MODULE.replace('"function":"test.tracker"','"function":"missing"'),
    BINDING_MODULE.replace('"function":"test.tracker"','"function":"test.check"'),
    BINDING_MODULE.replace('"threshold":0.1','"missing":0.1'),
    BINDING_MODULE.replace('"threshold":0.1','"threshold":"bad"'),
    BINDING_MODULE.replace('"threshold":0.1','"threshold":float("inf")'),
])
def test_binding_provider_and_partial_parameter_defaults(task_module,body):
    with pytest.raises(TaskError):load_registry((task_module(body),))


@pytest.mark.parametrize("change",[
    'kind=[]', 'bindings={"annotation": {"phase": []}}', 'requires=[[]]',
    'stages="annotation"', 'engines=[]', 'stages=["annotation", "annotation"]',
])
def test_malformed_declaration_values_have_structured_errors(task_module,change):
    key=change.split('=')[0]
    body=MODULE.replace('callable=check)', 'callable=check, '+change+')')
    original={'kind':'kind="predicate", ', 'stages':'stages={"annotation"}, ', 'engines':'engines={"mujoco"}, '}.get(key)
    if original:body=body.replace(original,'',1)
    with pytest.raises(TaskError) as raised:load_registry((task_module(body),))
    assert raised.value.code=="TASK_DECLARATION_INVALID"


@pytest.mark.parametrize("provider",['{"function": []}', '{"function": "test.tracker", "extra": 1}', '{"function": "test.tracker", "delayed": 1}'])
def test_malformed_binding_providers_are_structured(task_module,provider):
    body=BINDING_MODULE.replace('{"function":"test.tracker", "params":{"threshold":0.1}}',provider)
    with pytest.raises(TaskError):load_registry((task_module(body),))


def test_explicit_binding_cycles_and_post_to_pre_are_rejected(task_module):
    tail='''
FUNCTIONS["test.tracker"] = FunctionSpec(kind="tracker", stages={"annotation"}, engines={"independent"}, params_type=Params, callable=create,
    bindings={"annotation":{"phase":"post_step", "signals":{"self_ref":{"function":"test.tracker"}}}})
'''
    with pytest.raises(TaskError):load_registry((task_module(MODULE+tail),))


def test_binding_phase_requires_delayed_for_previous_post_signal(task_module):
    tracker='''
FUNCTIONS["test.tracker"] = FunctionSpec(kind="tracker", stages={"annotation"}, engines={"independent"}, params_type=Params, callable=create,
    bindings={"annotation":{"phase":"post_step"}})
'''
    pre=BINDING_MODULE.replace('"phase":"episode_end"','"phase":"pre_step"')+tracker
    with pytest.raises(TaskError):load_registry((task_module(pre),))


def test_delayed_binding_is_preserved_not_executed(task_module):
    body=BINDING_MODULE.replace('"phase":"episode_end"','"phase":"pre_step"').replace('"function":"test.tracker",','"function":"test.tracker", "delayed":True,')
    body+='''
FUNCTIONS["test.tracker"] = FunctionSpec(kind="tracker", stages={"annotation"}, engines={"independent"}, params_type=Params, callable=create,
    bindings={"annotation":{"phase":"post_step"}})
'''
    registry=load_registry((task_module(body),))
    assert registry.functions["test.accept"].bindings["annotation"]["signals"]["grasp"]["delayed"] is True


@pytest.mark.parametrize("kind,signature",[("placement","request, *, params"),("metrics","sample, *, params"),("acceptance","final, *, params")])
def test_other_plain_roles(task_module,kind,signature):
    body=MODULE.replace('kind="predicate"',f'kind="{kind}"',1).replace('sample, *, params',signature,1)
    registry=load_registry((task_module(body),))
    assert resolve(registry,"test.check",kind=kind,stage="annotation",engine="mujoco").kind==kind


def test_defaults_factory_is_not_executed_at_registration(task_module):
    body=MODULE.replace('threshold: float = 0.03','threshold: float = __import__("dataclasses").field(default_factory=lambda: float("nan"))')
    registry=load_registry((task_module(body),))
    with pytest.raises(TaskError):validate_params(registry,"test.check",{},kind="predicate",stage="annotation",engine="mujoco")


def test_import_error_keeps_original_cause(task_module):
    with pytest.raises(TaskError) as raised:load_registry((task_module('raise RuntimeError("declared module failed")'),))
    assert raised.value.code=="TASK_IMPORT_ERROR"
    assert isinstance(raised.value.__cause__,RuntimeError)


def test_optional_reference_none_does_not_require_scene(task_module):
    body=MODULE.replace('from dataclasses import dataclass','from dataclasses import dataclass, field').replace('threshold: float = 0.03','object_id: str | None = field(default=None, metadata={"reference":"object"})')
    registry=load_registry((task_module(body),))
    result=validate_params(registry,"test.check",{},kind="predicate",stage="annotation",engine="mujoco")
    assert result.object_id is None


def test_nonfinite_literal_schema_is_rejected(task_module):
    body=MODULE.replace('from dataclasses import dataclass','from typing import Literal\nfrom dataclasses import dataclass').replace('threshold: float = 0.03','threshold: Literal[float("inf")] = float("inf")')
    with pytest.raises(TaskError):load_registry((task_module(body),))


def test_non_string_resolution_arguments_are_structured(task_module):
    registry=load_registry((task_module(),))
    for arguments in ({"stage":[]},{"engine":[]},{"kind":[]}):
        args={"kind":"predicate","stage":"annotation","engine":"mujoco"}|arguments
        with pytest.raises(TaskError):resolve(registry,"test.check",**args)


def test_binding_function_reference_must_be_string(task_module):
    body=BINDING_MODULE.replace('"function":"test.tracker"','"function":{}')
    with pytest.raises(TaskError):load_registry((task_module(body),))


def test_explicit_module_params_then_direct_plain_function_call(task_module):
    body=MODULE.replace('raise AssertionError("registration must not execute predicates")','return sample["value"] < params.threshold')
    registry=load_registry((task_module(body),))
    spec=resolve(registry,"test.check",kind="predicate",stage="annotation",engine="mujoco")
    params=validate_params(registry,"test.check",{"threshold":0.1},kind="predicate",stage="annotation",engine="mujoco")
    assert spec.callable({"value":0.09},params=params) is True
    assert spec.callable({"value":0.11},params=params) is False


def test_empty_declaration_module_still_has_source_identity(task_module):
    name=task_module('FUNCTIONS = {}\n')
    registry=load_registry((name,))
    assert not registry.functions
    assert str(__import__('pathlib').Path(sys.modules[name].__file__).resolve()) in registry.source_sha256
