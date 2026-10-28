"""Existing Builder editing responsibilities; authoring schemas unchanged."""
from .scene import cameras_audited, identifier, validate, value
import copy
import numpy as np


PROTECTED = {'measured', 'calibrated'}


def preserve(before, after, path='scene'):
    if isinstance(before, dict):
        if (before.get('provenance') in tuple(PROTECTED) or before.get('source') in tuple(PROTECTED)) and before != after:
            raise ValueError('Protected measured/calibrated field: ' + path)
        if isinstance(after, dict):
            for key, old in before.items():
                if key in after:
                    preserve(old, after[key], path + '.' + key)
                else:
                    preserve(old, None, path + '.' + key)
        else:
            for key, old in before.items():
                preserve(old, None, path + '.' + key)
    elif isinstance(before, list):
        for i, old in enumerate(before):
            following = after[i] if isinstance(after, list) and i < len(after) else None
            preserve(old, following, path + '.' + str(i))


def check_scope(before, after, scope):
    """Object ID keyed locks; shared frames/cameras/lights and other objects stay exact."""
    if not scope:
        return
    name = scope['target_object']
    fields = set(scope['allow'])
    if before.get('scan_initialization') and fields & {'pose', 'dimensions'} and (not cameras_audited(before)):
        raise ValueError('Scan object pixel refinement requires audited camera calibration first')
    old = {o['id']: o for o in before['objects']}
    new = {o['id']: o for o in after['objects']}
    if old.keys() != new.keys():
        raise ValueError('Object scope forbids add/remove')
    for identity, obj in old.items():
        following = new[identity]
        if identity != name:
            if obj != following:
                raise ValueError('Locked object changed: ' + identity)
        else:
            for key in set(obj) | set(following):
                if key not in fields and obj.get(key) != following.get(key):
                    raise ValueError('Locked object field: ' + key)
    for key in (set(before) | set(after)) - {'objects', 'assets'}:
        if before.get(key) != after.get(key):
            raise ValueError('Locked scene group changed: ' + key)
    if 'visual' not in fields:
        if before['assets'] != after['assets']:
            raise ValueError('Locked assets changed')
    else:
        for key, row in before['assets'].items():
            if after['assets'].get(key) != row:
                raise ValueError('Accepted asset changed in place')


def apply(scene, operations, root):
    result = copy.deepcopy(scene)
    for operation in operations:
        op = operation['op']
        name = operation.get('id')
        if result.get('scan_initialization') and op in ('update_pose', 'update_dimensions') and (not cameras_audited(result)):
            raise ValueError('Scan object pixel refinement requires camera audit first; use measurement/registration evidence for metric initialization')
        if name:
            identifier(name)
        if op == 'add_object':
            if any((o['id'] == name for o in result['objects'])):
                raise ValueError('Duplicate object ID')
            t = operation.get('pose', np.eye(4).tolist())
            shape = operation.get('visual', {'type': 'box'})
            obj = {'id': name, 'role': operation.get('role', 'fixture'), 'frame': operation.get('frame', 'world'), 'pose': value(t, 'estimated'), 'dimensions': value(operation.get('dimensions')), 'color': value(operation.get('color', [0.6] * 3), 'estimated'), 'visual': shape, 'collision': operation.get('collision', {'type': 'unknown'}), 'physics': {'mass_kg': value(None), 'friction': value(None)}}
            if operation.get('dimensions') is not None:
                obj['dimensions'] = value(operation['dimensions'], 'estimated')
            result['objects'].append(obj)
        elif op == 'remove_object':
            obj = next((o for o in result['objects'] if o['id'] == name))
            result['objects'].remove(obj)
        elif op in ('update_pose', 'update_dimensions', 'set_material', 'set_visual_mesh', 'set_collision'):
            obj = next((o for o in result['objects'] if o['id'] == name))
            old = copy.deepcopy(obj)
            evidence = operation.get('evidence', ['agent candidate hypothesis'])
            if op in ('update_pose', 'update_dimensions'):
                obj['pose' if op == 'update_pose' else 'dimensions'] = value(operation['value'], 'estimated', evidence)
            elif op == 'set_material':
                if 'color' in operation:
                    obj['color'] = value(operation['color'], 'estimated', evidence)
                obj.setdefault('material', {}).update({k: value(v, 'estimated', evidence) for k, v in operation.items() if k in ('roughness', 'metallic')})
                if 'texture' in operation:
                    obj['visual']['texture'] = operation['texture']
            elif op == 'set_visual_mesh':
                obj['visual'] = {'type': 'mesh', 'asset': operation['asset'], 'scale': operation.get('scale', [1, 1, 1]), 'source': 'agent_authored', 'provenance': 'estimated'}
                if operation.get('texture'):
                    obj['visual']['texture'] = operation['texture']
            else:
                obj['collision'] = copy.deepcopy(operation['value'])
            preserve(old, obj, name)
        elif op == 'set_camera':
            cameras = result['cameras']
            existing = next((c for c in cameras if c['id'] == name), None)
            if existing is None:
                existing = {'id': name, 'frame': operation.get('frame', 'world'), 'pose': value(None), 'K': value(None), 'distortion': value([0.0] * 5, 'estimated'), 'resolution': operation['resolution']}
                cameras.append(existing)
            old = copy.deepcopy(existing)
            for key in ('pose', 'K', 'distortion'):
                if key in operation:
                    existing[key] = value(operation[key], 'estimated', operation.get('evidence', []))
            for key in ('frame', 'resolution', 'purpose'):
                if key in operation:
                    existing[key] = operation[key]
            preserve(old, existing, name)
        elif op == 'set_workflow':
            previous = result.get('workflow', {})
            result['workflow'] = copy.deepcopy(operation['value'])
            preserve(previous, result['workflow'], 'workflow')
        elif op == 'set_lighting':
            old = copy.deepcopy(result['lights'])
            result['lights']['ambient'] = value(operation['ambient'], 'estimated', operation.get('evidence', []))
            if 'sources' in operation:
                result['lights']['sources'] = [{'id': r['id'], 'type': r['type'], **{k: value(r[k], 'estimated') for k in ('pose', 'color', 'energy', 'size')}} for r in operation['sources']]
                for previous in old.get('sources', []):
                    following = next((r for r in result['lights']['sources'] if r['id'] == previous['id']), {})
                    preserve(previous, following, 'light.' + previous['id'])
            preserve(old, result['lights'], 'lights')
        else:
            raise ValueError('Unsupported edit operation: ' + op)
    validate(result, root)
    return result

