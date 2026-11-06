"""Translate typed Scene intent into existing, explicitly registered Task bindings."""
from .registry import SAMPLE_FIELDS, validate_params


def exported_task(scene):
    """Read only the selected immutable Package, never the mutable authoring Project."""
    import hashlib,json,yaml
    from real2sim_builder.authoring import task_intent
    files={entry.path:entry for entry in scene.files}
    if 'authored_scene.json' not in files:return None
    def read(name):
        path=(scene.root/name).resolve()
        if name not in files or not path.is_relative_to(scene.root.resolve()):
            raise ValueError('Task configuration is outside the Scene manifest')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=files[name].sha256:raise ValueError('Scene Task configuration changed')
        return raw
    authored=json.loads(read('authored_scene.json'))
    ref=authored.get('reconstruction_configuration')
    if not ref:return None
    raw=read(ref['path'])
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('Scene Task configuration changed')
    return task_intent(yaml.safe_load(raw),scene.scene['objects'])


def task_recipe(scene, intent, registry, stage, engine):
    from real2sim_builder.authoring import task_intent
    intent=task_intent({'task':intent},scene.scene['objects'])
    result=dict(status='NO_TASK',functions={},instruction='',needs=[],execution_verified=False,
                source_sha256=dict(registry.source_sha256))
    if intent is None:return result
    result['instruction']=intent['instruction']
    needs=list(intent['needs'])
    if intent['kind']!='pick_place':needs.append('Task kind is not implemented: '+intent['kind'])
    if not intent['object_id'] or not intent['target_id']:needs.append('Explicit object and target IDs required')
    needs.extend('Unsupported observation: '+field for field in intent['required_observations']
                 if field not in SAMPLE_FIELDS and field!='signals.grasp')
    if needs:return result|dict(status='NEEDS_IMPLEMENTATION',needs=needs)
    names={'annotation':('acceptance','pick_place.annotation'),
           'datagen':('acceptance','pick_place.v8_datagen'),
           'simulation_evaluation':('success','pick_place.v8_evaluation')}
    if stage not in names:raise ValueError('Task configuration supports Annotation, DataGen and Sim Evaluation')
    role,name=names[stage]
    params=dict(object=intent['object_id'],target=intent['target_id'])
    functions={role:dict(function=name,params=params),
               'metrics':dict(function='pick_place.v8_metrics',params=dict(params))}
    for key,decl in functions.items():
        validate_params(registry,decl['function'],decl['params'],kind='predicate' if key=='success' else key,
                        stage=stage,engine=engine,scene=scene)
    # Acceptance binds the registered post-step grasp tracker during prepare_recipe.
    # This checks configuration only; it does not run the engine or establish Task success.
    return result|dict(status='CONFIGURED',functions=functions,
        criterion='placement' if role=='success' else 'stable_grasp_and_placement',
        motion='existing object-relative pick/place; requires annotated Source' if stage=='datagen' else None)
