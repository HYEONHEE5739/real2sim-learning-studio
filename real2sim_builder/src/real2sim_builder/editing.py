"""Existing Builder editing responsibilities; authoring schemas unchanged."""
from .scene import identifier, validate, value
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
        identified=bool(before)and all(isinstance(o,dict)and 'id'in o for o in before)
        by_id={o['id']:o for o in after}if identified and isinstance(after,list)else{}
        for i, old in enumerate(before):
            following = by_id.get(old['id'])if identified else after[i] if isinstance(after, list) and i < len(after) else None
            # Removing a placed asset instance preserves the independent
            # measured asset in the library; it does not edit its dimensions.
            if identified and following is None and path.endswith('.objects')and old.get('object_asset'):continue
            preserve(old, following, path + '.' + str(i))


def check_scope(before, after, scope):
    """Object ID keyed locks; shared frames/cameras/lights and other objects stay exact."""
    if not scope:
        return
    name = scope['target_object']
    fields = set(scope['allow'])
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
        if name:
            identifier(name)
        if op == 'use_object_asset':
            obj=next(o for o in result['objects']if o['id']==name)
            if obj.get('link')or obj['role']=='reference_robot':raise ValueError('Robot object cannot be replaced by a modeled asset')
            old=copy.deepcopy(obj)
            for key,row in operation['assets'].items():
                if key in result['assets']and result['assets'][key]!=row:raise ValueError('Object asset key conflict')
                result['assets'][key]=copy.deepcopy(row)
            for field in('visual','collision','object_asset'):obj[field]=copy.deepcopy(operation[field])
            dims=operation['dimension_record']
            protected=obj['dimensions']if obj['dimensions']['provenance']in PROTECTED else obj['dimensions'].get('constraints',{})
            if protected.get('provenance')in PROTECTED:
                for axis,known in enumerate(protected['value']):
                    if known is not None and not np.isclose(known,dims['value'][axis],rtol=.02,atol=1e-5):
                        raise ValueError('Asset dimensions disagree with existing measured geometry')
            if obj['dimensions']['provenance']not in PROTECTED:obj['dimensions']=copy.deepcopy(dims)
            preserve(old,obj,name)
        elif op == 'add_object':
            if any((o['id'] == name for o in result['objects'])):
                raise ValueError('Duplicate object ID')
            t = operation.get('pose', np.eye(4).tolist())
            shape = operation.get('visual', {'type': 'box'})
            obj = {'id': name, 'role': operation.get('role', 'fixture'), 'frame': operation.get('frame', 'world'), 'pose': value(t, 'estimated'), 'dimensions': value(operation.get('dimensions')), 'color': value(operation.get('color', [0.6] * 3), 'estimated'), 'visual': shape, 'collision': operation.get('collision', {'type': 'unknown'}), 'physics': {'mass_kg': value(None), 'friction': value(None)}}
            if operation.get('dimensions') is not None:
                obj['dimensions'] = value(operation['dimensions'], 'estimated')
            if operation.get('dimension_record'):obj['dimensions']=copy.deepcopy(operation['dimension_record'])
            if operation.get('unknown_pose'):obj['pose']=value(None)
            if operation.get('object_asset'):
                for key,row in operation['assets'].items():
                    if key in result['assets']and result['assets'][key]!=row:raise ValueError('Object asset key conflict')
                    result['assets'][key]=copy.deepcopy(row)
                obj['object_asset']=copy.deepcopy(operation['object_asset'])
            if 'spawn'in operation:obj['spawn']=operation['spawn']
            result['objects'].append(obj)
        elif op == 'remove_object':
            obj = next((o for o in result['objects'] if o['id'] == name))
            result['objects'].remove(obj)
        elif op in ('update_pose', 'update_dimensions', 'set_material', 'set_visual_mesh', 'set_collision'):
            obj = next((o for o in result['objects'] if o['id'] == name))
            if obj.get('object_asset')and op!='update_pose':raise ValueError('Edit geometry/material/collision through a new object asset version; instance edits change pose only')
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
        elif op == 'set_spawn':
            obj = next(o for o in result['objects'] if o['id'] == name)
            obj['spawn'] = operation['value']
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

