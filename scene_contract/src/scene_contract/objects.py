"""Scene instance membership, independent of physical role and task targets."""


def spawn_mode(obj):
    # Old packages expressed selectability through their manipuland role.
    return obj.get('spawn','recipe'if obj.get('role')in('manipulable_object','task_object')else'always')


def present_objects(scene,selected):
    objects=scene['objects'];selected=set(selected)
    if not selected<=objects.keys():raise ValueError('Selected object is absent from the Scene catalogue')
    excluded={name for name,obj in objects.items()if spawn_mode(obj)=='recipe'and name not in selected}
    while True:
        children={name for name,obj in objects.items()if obj.get('parent_object')in excluded}
        if children<=excluded:break
        excluded.update(children)
    if selected&excluded:raise ValueError('A selected object requires its parent object to be selected')
    return tuple(name for name in objects if name not in excluded)


def active_objects(scene,selected,configured=()):
    """Recipe replaces optional template instances; always-present bodies remain."""
    if not set(configured)<=scene['objects'].keys():raise ValueError('Engine configuration names an unknown Scene object')
    present=set(present_objects(scene,selected))
    return tuple(dict.fromkeys([*selected,*(name for name in configured if name in present and spawn_mode(scene['objects'][name])=='always')]))
