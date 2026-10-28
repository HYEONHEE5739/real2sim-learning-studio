"""Explicit Task declarations and parameter checks; no discovery or execution loop."""
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, field, fields, is_dataclass, replace
import hashlib
import importlib
import inspect
import keyword
import math
from pathlib import Path
import types
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable, Literal, Union, get_args, get_origin, get_type_hints

import yaml

if TYPE_CHECKING:
    from scene_contract.package import ScenePackage


@dataclass(frozen=True)
class Issue:
    field: str
    reason: str
    source: str | None = None

class TaskError(ValueError):

    def __init__(self, code: str, field: str, reason: str, source: str | None=None):
        self.code = code
        self.message = f'{field}: {reason}'
        self.issues = (Issue(field, reason, source),)
        self.effect = 'not_started'
        super().__init__(self.message)

def _name(value, field, code='TASK_DECLARATION_INVALID'):
    if not isinstance(value, str) or not value or any((not part.isidentifier() or keyword.iskeyword(part) for part in value.split('.'))):
        raise TaskError(code, field, 'expected an explicit dotted Python name')

def _module_names(value):
    if not isinstance(value, (list, tuple)):
        raise TaskError('TASK_MODULES_INVALID', 'modules', 'expected a module name list')
    seen = set()
    for index, name in enumerate(value):
        _name(name, f'modules[{index}]', 'TASK_MODULES_INVALID')
        if name in seen:
            raise TaskError('TASK_MODULES_INVALID', f'modules[{index}]', 'duplicate module')
        seen.add(name)
    return tuple(value)

def read_module_names(path: Path) -> tuple[str, ...]:
    """Read the flat YAML contract without importing any Task module."""

    class Loader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str) or key in result:
                raise ValueError('invalid or duplicate YAML key')
            result[key] = loader.construct_object(value_node)
        return result
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        raw = Path(path).read_bytes()
        if any((isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(raw))):
            raise ValueError('module lists do not use YAML anchors/aliases')
        data = yaml.load(raw, Loader=Loader)
        if not isinstance(data, dict) or set(data) != {'modules'}:
            raise ValueError('expected only the modules field')
        return _module_names(data['modules'])
    except (OSError, ValueError, yaml.YAMLError) as exc:
        if isinstance(exc, TaskError):
            raise
        raise TaskError('TASK_MODULES_INVALID', 'modules', str(exc), str(path)) from exc
KINDS = frozenset({'predicate', 'tracker', 'placement', 'metrics', 'acceptance'})
STAGES = frozenset({'source', 'annotation', 'datagen', 'simulation_evaluation', 'real_evaluation', 'real_sim'})
ENGINES = frozenset({'isaac', 'mujoco', 'independent'})
PHASES = frozenset({'episode_start', 'pre_step', 'post_step', 'episode_end'})
SAMPLE_FIELDS = frozenset({'episode_id', 'env_index', 'tick', 'phase', 'dt_s', 'pose_frame', 'object_poses', 'eef_pose', 'joint_positions', 'joint_order', 'contacts', 'linear_velocities', 'signals', 'grasp_inputs', 'placement_points'})

@dataclass(frozen=True)
class FunctionSpec:
    kind: str
    stages: frozenset[str]
    engines: frozenset[str]
    params_type: type
    callable: Callable
    requires: tuple[str, ...] = ()
    bindings: Mapping = field(default_factory=dict)
    contract_version: int = 1

@dataclass(frozen=True)
class TaskRegistry:
    modules: tuple[str, ...]
    functions: Mapping[str, FunctionSpec]
    source_sha256: Mapping[str, str]
    validators: Mapping[str, Callable]

def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple((_freeze(v) for v in value))
    return value

def _signature(fn, names, keyword_only, where):
    if (not inspect.isfunction(fn) or inspect.iscoroutinefunction(fn)
            or inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn)):
        raise TaskError('TASK_DECLARATION_INVALID', where, 'expected a synchronous Python function')
    parameters = tuple(inspect.signature(fn, follow_wrapped=False).parameters.values())
    invalid = any(
        p.kind != (inspect.Parameter.KEYWORD_ONLY if p.name in keyword_only
                   else inspect.Parameter.POSITIONAL_OR_KEYWORD)
        or p.default is not inspect.Parameter.empty for p in parameters
    )
    if tuple(p.name for p in parameters) != names or invalid:
        raise TaskError('TASK_DECLARATION_INVALID', where, f'expected parameters {names}, keyword-only {keyword_only}')

def _declaration(name, spec):
    _name(name, 'FUNCTIONS.name')
    where = f'FUNCTIONS.{name}'
    if not isinstance(spec, FunctionSpec):
        raise TaskError('TASK_DECLARATION_INVALID', where, 'expected FunctionSpec')
    if type(spec.contract_version) is not int or spec.contract_version != 1:
        raise TaskError('TASK_DECLARATION_INVALID', where + '.contract_version', 'unsupported contract version')
    if not isinstance(spec.kind, str) or spec.kind not in KINDS:
        raise TaskError('TASK_DECLARATION_INVALID', where + '.kind', 'unknown role')
    for key, allowed in (('stages', STAGES), ('engines', ENGINES)):
        value = getattr(spec, key)
        if not isinstance(value, (set, frozenset, list, tuple)) or not value or any((not isinstance(v, str) or v not in allowed for v in value)):
            raise TaskError('TASK_DECLARATION_INVALID', where + '.' + key, 'expected explicit supported names')
    if any((len(set(getattr(spec, key))) != len(getattr(spec, key)) for key in ('stages', 'engines'))):
        raise TaskError('TASK_DECLARATION_INVALID', where, 'duplicate stage/engine')
    if 'independent' in spec.engines and len(spec.engines) != 1:
        raise TaskError('TASK_DECLARATION_INVALID', where + '.engines', 'independent cannot be combined with engines')
    if not isinstance(spec.params_type, type) or not is_dataclass(spec.params_type):
        raise TaskError('TASK_DECLARATION_INVALID', where + '.params_type', 'expected a dataclass type')
    _schema(spec.params_type)
    if not isinstance(spec.requires, (tuple, list)) or any(
        not isinstance(v, str) or (v not in SAMPLE_FIELDS
            and not (v.startswith('signals.') and v[8:].isidentifier()))
        for v in spec.requires
    ):
        raise TaskError('TASK_DECLARATION_INVALID', where + '.requires', 'unknown sample field or signal')
    if len(set(spec.requires)) != len(spec.requires):
        raise TaskError('TASK_DECLARATION_INVALID', where + '.requires', 'duplicate requirement')
    first = {'predicate': 'sample', 'metrics': 'sample', 'acceptance': 'final', 'placement': 'request'}
    names = ('params', 'episode') if spec.kind == 'tracker' else (first[spec.kind], 'params')
    _signature(spec.callable, names, set(names) if spec.kind == 'tracker' else {'params'}, where + '.callable')
    if not isinstance(spec.bindings, Mapping):
        raise TaskError('TASK_DECLARATION_INVALID', where + '.bindings', 'expected stage mapping')
    for stage, binding in spec.bindings.items():
        if (stage not in spec.stages or not isinstance(binding, Mapping)
                or set(binding) - {'phase', 'signals'}
                or not isinstance(binding.get('phase'), str)
                or binding.get('phase') not in PHASES):
            raise TaskError('TASK_DECLARATION_INVALID', where + '.bindings', 'unknown stage, phase or field')
        signals = binding.get('signals', {})
        if not isinstance(signals, Mapping):
            raise TaskError('TASK_DECLARATION_INVALID', where + '.bindings.signals', 'expected signal mapping')
        for signal, provider in signals.items():
            if (not isinstance(signal, str) or not signal.isidentifier()
                    or not isinstance(provider, Mapping)
                    or set(provider) - {'function', 'params', 'delayed'}
                    or not isinstance(provider.get('function'), str)
                    or not isinstance(provider.get('params', {}), Mapping)
                    or type(provider.get('delayed', False)) is not bool):
                raise TaskError('TASK_DECLARATION_INVALID', where + '.bindings.signals', 'invalid signal provider')
    return replace(spec, stages=frozenset(spec.stages), engines=frozenset(spec.engines), requires=tuple(spec.requires), bindings=_freeze(spec.bindings))

def load_registry(module_names: tuple[str, ...]) -> TaskRegistry:
    """Import only the trusted, explicitly listed modules. Never call Task functions."""
    if not isinstance(module_names, tuple):
        raise TaskError('TASK_MODULES_INVALID', 'modules', 'expected a tuple from read_module_names')
    names = _module_names(module_names)
    functions = {}
    validators = {}
    sources = {}
    for module_name in names:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise TaskError('TASK_IMPORT_ERROR', module_name, str(exc)) from exc
        declarations = getattr(module, 'FUNCTIONS', None)
        if not isinstance(declarations, Mapping):
            raise TaskError('TASK_DECLARATION_INVALID', module_name + '.FUNCTIONS', 'expected mapping')
        _record_source(module, sources, module_name)
        validator = getattr(module, 'validate_params', None)
        if validator is not None:
            _signature(validator, ('params', 'scene'), set(), module_name + '.validate_params')
        for name, value in declarations.items():
            _name(name, 'FUNCTIONS.name')
            if name in functions:
                raise TaskError('TASK_DECLARATION_INVALID', name, 'duplicate registered name')
            spec = _declaration(name, value)
            functions[name] = spec
            if validator is not None:
                validators[name] = validator
            for obj in (spec.callable, spec.params_type, validator):
                if obj is None:
                    continue
                _record_source(obj, sources, name)
    registry = TaskRegistry(names, MappingProxyType(functions), MappingProxyType(sources), MappingProxyType(validators))
    for name, spec in functions.items():
        for stage, binding in spec.bindings.items():
            for signal, provider in binding.get('signals', {}).items():
                target = functions.get(provider['function'])
                if target is None or target.kind != 'tracker' or stage not in target.stages or ('independent' not in target.engines and (not spec.engines <= target.engines)):
                    raise TaskError('TASK_DECLARATION_INVALID', f'{name}.bindings.{stage}.{signal}', 'unknown or incompatible tracker')
                try:
                    _parameters(target.params_type, provider.get('params', {}), f'{name}.bindings.{stage}.{signal}.params', partial=True)
                except TaskError as exc:
                    raise TaskError('TASK_DECLARATION_INVALID', exc.issues[0].field, exc.issues[0].reason) from exc
    _validate_binding_order(functions)
    return registry

def _record_source(obj, sources, name):
    try:
        source = inspect.getsourcefile(obj)
        if source:
            path = Path(source).resolve()
            sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, TypeError) as exc:
        raise TaskError('TASK_IMPORT_ERROR', name, 'cannot identify Task source') from exc

def resolve(registry: TaskRegistry, name: str, *, kind: str, stage: str, engine: str | None=None) -> FunctionSpec:
    if not isinstance(name, str) or name not in registry.functions:
        raise TaskError('TASK_UNKNOWN', 'functions.name', 'unknown registered function')
    spec = registry.functions[name]
    if (not isinstance(kind, str) or not isinstance(stage, str)
            or (engine is not None and not isinstance(engine, str))
            or kind != spec.kind or stage not in spec.stages
            or engine not in {None, 'isaac', 'mujoco'}
            or ('independent' not in spec.engines and engine not in spec.engines)):
        raise TaskError('TASK_UNSUPPORTED', name, 'role, stage or engine is unsupported')
    return spec

def _hints(cls):
    try:
        return get_type_hints(cls, include_extras=True)
    except Exception as exc:
        raise TaskError('TASK_DECLARATION_INVALID', cls.__name__, 'cannot resolve parameter annotations') from exc

def _reference_type(annotation):
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is str:
        return True
    if origin in (Union, types.UnionType):
        return all((a is type(None) or _reference_type(a) for a in args))
    return origin in (list, tuple) and all((a is Ellipsis or _reference_type(a) for a in args))

def _schema(cls, seen=()):
    if cls in seen:
        raise TaskError('TASK_DECLARATION_INVALID', cls.__name__, 'recursive parameter schemas are unsupported')
    hints = _hints(cls)
    for item in fields(cls):
        if not item.init:
            raise TaskError('TASK_DECLARATION_INVALID', item.name, 'parameters must be constructor fields')
        annotation = hints[item.name]

        def check_type(t):
            origin = get_origin(t)
            args = get_args(t)
            if t in (str, int, float, bool, type(None)):
                return
            if isinstance(t, type) and is_dataclass(t):
                _schema(t, seen + (cls,))
                return
            if origin is Literal and args and all((type(a) in (str, int, float, bool, type(None)) and (type(a) is not float or math.isfinite(a)) for a in args)):
                return
            if origin in (Union, types.UnionType, list, tuple, dict):
                if not args or (origin is dict and (len(args) != 2 or args[0] is not str)):
                    raise TaskError('TASK_DECLARATION_INVALID', item.name, 'unsupported container annotation')
                for arg in args:
                    if arg is not Ellipsis:
                        check_type(arg)
                return
            raise TaskError('TASK_DECLARATION_INVALID', item.name, 'unsupported parameter annotation')
        check_type(annotation)
        reference = item.metadata.get('reference')
        if reference is not None and (reference not in ('object', 'frame', 'support') or not _reference_type(annotation)):
            raise TaskError('TASK_DECLARATION_INVALID', item.name, 'reference requires object/frame/support string(s)')
        if item.default is not MISSING:
            try:
                _value(item.default, annotation, item.name)
            except TaskError as exc:
                raise TaskError('TASK_DECLARATION_INVALID', item.name, 'invalid parameter default') from exc

def _value(value, annotation, where):

    def invalid():
        raise TaskError('TASK_PARAMS_INVALID', where, 'value does not match the declared parameter type')
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType):
        for arg in args:
            try:
                return _value(value, arg, where)
            except TaskError:
                pass
        invalid()
    if origin is Literal:
        if not any((type(value) is type(arg) and value == arg for arg in args)):
            invalid()
        return value
    if annotation is type(None):
        if value is not None:
            invalid()
        return None
    if annotation is float:
        if type(value) not in (int, float):
            invalid()
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            invalid()
        return value
    if annotation in (str, int, bool):
        if type(value) is not annotation:
            invalid()
        return value
    if isinstance(annotation, type) and is_dataclass(annotation):
        if isinstance(value, annotation):
            value = {f.name: getattr(value, f.name) for f in fields(annotation)}
        return _parameters(annotation, value, where)
    if origin in (list, tuple):
        if not isinstance(value, (list, tuple)):
            invalid()
        if origin is tuple and (not (len(args) == 2 and args[1] is Ellipsis)):
            if len(value) != len(args):
                invalid()
            result = [_value(v, t, f'{where}[{i}]') for i, (v, t) in enumerate(zip(value, args))]
        else:
            result = [_value(v, args[0], f'{where}[{i}]') for i, v in enumerate(value)]
        return tuple(result) if origin is tuple else result
    if origin is dict:
        if not isinstance(value, Mapping):
            invalid()
        return {_value(k, str, where + '.key'): _value(v, args[1], where + '.' + str(k)) for k, v in value.items()}
    invalid()

def _parameters(cls, values, where, *, partial=False):
    if not isinstance(values, Mapping):
        raise TaskError('TASK_PARAMS_INVALID', where, 'expected parameter mapping')
    hints = _hints(cls)
    declared = {f.name: f for f in fields(cls)}
    if set(values) - declared.keys():
        raise TaskError('TASK_PARAMS_INVALID', where, 'unknown parameter field(s): ' + repr(list(set(values) - declared.keys())))
    result = {name: _value(value, hints[name], where + '.' + name) for name, value in values.items()}
    if partial:
        return result
    for name, item in declared.items():
        if name not in result:
            if item.default is not MISSING:
                value = item.default
            elif item.default_factory is not MISSING:
                try:
                    value = item.default_factory()
                except Exception as exc:
                    raise TaskError('TASK_PARAMS_INVALID', where + '.' + name, 'parameter default factory failed') from exc
            else:
                raise TaskError('TASK_PARAMS_INVALID', where + '.' + name, 'required parameter missing')
            result[name] = _value(value, hints[name], where + '.' + name)
    try:
        return cls(**result)
    except Exception as exc:
        raise TaskError('TASK_PARAMS_INVALID', where, 'parameter construction failed') from exc

def _references(params, scene, selected, where):
    for item in fields(params):
        value = getattr(params, item.name)
        path = where + '.' + item.name
        ref = item.metadata.get('reference')
        if ref is not None and value is not None and (value != []) and (value != ()):
            if scene is None:
                raise TaskError('TASK_PARAMS_INVALID', path, 'ScenePackage is required for references')
            table = scene.scene[{'object': 'objects', 'frame': 'frames', 'support': 'supports'}[ref]]

            def check(v):
                if v is None:
                    return
                if isinstance(v, (list, tuple)):
                    for part in v:
                        check(part)
                    return
                if v not in table:
                    raise TaskError('TASK_PARAMS_INVALID', path, 'unknown Scene ' + ref + ' ID: ' + v)
                if ref == 'object' and selected is not None and (table[v].get('role') == 'task_object') and (v not in selected):
                    raise TaskError('OBJECT_NOT_SELECTED', path, 'task object is absent from the creation list: ' + v)
            check(value)

        def nested(v, p):
            if is_dataclass(v):
                _references(v, scene, selected, p)
            elif isinstance(v, (tuple, list)):
                for i, part in enumerate(v):
                    nested(part, f'{p}[{i}]')
            elif isinstance(v, dict):
                for k, part in v.items():
                    nested(part, p + '.' + k)
        nested(value, path)

def validate_params(
    registry: TaskRegistry, name: str, values: Mapping, *, kind: str, stage: str,
    engine: str | None = None, scene: 'ScenePackage | None' = None,
    selected_objects: tuple[str, ...] | None = None,
):
    """Construct checked parameters. Never execute the registered Task/factory."""
    spec = resolve(registry, name, kind=kind, stage=stage, engine=engine)
    if selected_objects is not None:
        if not isinstance(selected_objects, tuple) or any((not isinstance(v, str) for v in selected_objects)) or len(set(selected_objects)) != len(selected_objects) or (scene is None) or any((v not in scene.scene['objects'] for v in selected_objects)):
            raise TaskError('TASK_PARAMS_INVALID', 'objects', 'invalid explicit object selection')
    params = _parameters(spec.params_type, values, name + '.params')
    _references(params, scene, selected_objects, name + '.params')
    validator = registry.validators.get(name)
    if validator:
        try:
            result = validator(params, scene)
        except Exception as exc:
            raise TaskError('TASK_PARAMS_INVALID', name + '.params', str(exc)) from exc
        if result is not None:
            raise TaskError('TASK_PARAMS_INVALID', name + '.params', 'validate_params must return None')
    return params

def _validate_binding_order(functions):
    """Check declared edges only; do not build or run a stage scheduler."""
    order = {name: i for i, name in enumerate(('episode_start', 'pre_step', 'post_step', 'episode_end'))}
    for stage in STAGES:
        edges = {name: [] for name in functions}
        for name, spec in functions.items():
            binding = spec.bindings.get(stage, {})
            for provider in binding.get('signals', {}).values():
                target = provider['function']
                edges[name].append(target)
                phase = functions[target].bindings.get(stage, {}).get('phase')
                if phase and order[phase] > order[binding['phase']] and (not provider.get('delayed', False)):
                    raise TaskError('TASK_DECLARATION_INVALID', f'{name}.bindings.{stage}', 'later-phase signal requires explicit delayed input')
        done = set()
        for start in edges:
            active = set()
            stack = [(start, False)]
            while stack:
                node, leaving = stack.pop()
                if leaving:
                    active.remove(node)
                    done.add(node)
                    continue
                if node in active:
                    raise TaskError('TASK_DECLARATION_INVALID', f'{node}.bindings.{stage}', 'cyclic signal dependency')
                if node in done:
                    continue
                active.add(node)
                stack.append((node, True))
                stack.extend(((child, False) for child in reversed(edges[node])))
