"""Small Task contract helpers; concrete engines own observations and stepping."""
import numpy as np


def contact_object(plan):
    consumers=[b for b in plan.function_bindings.values()if 'grasp_inputs'in b.requires or 'contacts'in b.requires]
    objects={getattr(b.params,'object',None)for b in consumers}
    if None in objects:raise ValueError('Finger contact samples require an explicit params.object on the consuming Task function')
    if len(objects)>1:raise ValueError('One sample cannot represent contacts for multiple objects; declare a single contact object')
    return next(iter(objects),None)


def placement_bindings(plan):
    return [b for b in plan.function_bindings.values()if 'placement_points'in b.requires]


def add_placement_points(plan,row):
    from .pick_place import numpy_corners
    row['placement_points']={}
    for binding in placement_bindings(plan):
        params=binding.params;dimensions=plan.scene.scene['objects'][params.object]['task_geometry']['dimensions_m']
        row['placement_points'][params.object]={'target_id':params.target,'points':numpy_corners(row['object_poses'][params.object],row['object_poses'][params.target],dimensions)}
    return row


def predicate(plan,role,row):
    binding=plan.function_bindings[role]
    for field in binding.requires:
        if field.startswith('signals.'):
            if field.split('.',1)[1]not in row.get('signals',{}):raise ValueError(binding.name+': missing '+field)
        elif field not in row:raise ValueError(binding.name+': missing sample field '+field)
    result=plan.tasks.functions[binding.name].callable(row,params=binding.params)
    if type(result)is not bool:raise ValueError(binding.name+': Task condition must return bool')
    return result


def recorded_signals(signals):
    return {name:bool(getattr(value,'value',value))for name,value in signals.items()}


def placement_signal(plan,row):
    # Preserve the historical pre-step diagnostic only when the declared Task
    # explicitly consumes Pick & Place geometry. Custom Tasks need no cup/grasp.
    bindings=[b for b in placement_bindings(plan)if b.name in('pick_place.placement','pick_place.annotation','pick_place.v8_datagen','pick_place.v8_evaluation','pick_place.v8_metrics')]
    if not bindings:return False
    from .pick_place import v8_placement
    return v8_placement(row,params=bindings[0].params)


def metrics(plan,row):
    return {role:plan.tasks.functions[b.name].callable(row,params=b.params)for role,b in plan.function_bindings.items()if b.kind=='metrics'and b.phase==row['phase']}


def annotation_events(episode,*,manual_frame=None,manual_events=None):
    import torch
    episode.pre_export();signals=episode.data['obs'].get('datagen_info',{}).get('subtask_term_signals',{})
    if manual_frame is not None:
        length=len(episode.data['joint_targets']);signal=torch.from_numpy((np.arange(length)>=manual_frame).astype(np.uint8)[:,None]);signals['grasp']=signal;episode.data['obs']['events']['grasp']=signal
    for name,frame in(manual_events or {}).items():
        length=len(episode.data['joint_targets'])
        if not 0<frame<length-1:raise ValueError('Manual subtask boundary must be inside the recorded Episode')
        signal=torch.from_numpy((np.arange(length)>=frame).astype(np.uint8)[:,None]);signals[name]=signal;episode.data['obs']['events'][name]=signal
    events={}
    for name,values in episode.data['obs'].get('events',{}).items():
        indices=torch.nonzero(values.reshape(len(values),-1).any(1))
        if len(indices):events[name]=int(indices[0,0])
    return events


def mimic_objects(plan):
    """Mimic remains object-relative pick/transport; custom acceptance is separate."""
    params=plan.function_bindings['acceptance'].params;settings=plan.effective_settings['execution']
    object_id=settings.get('mimic_object',getattr(params,'object',None));target=settings.get('mimic_target',getattr(params,'target',None))
    if object_id is None or target is None:raise ValueError('Object-relative Mimic needs execution.mimic_object and execution.mimic_target, or acceptance params.object/target. Replacing Task success alone does not define a new Mimic algorithm.')
    if object_id not in plan.scene.scene['objects']or target not in plan.scene.scene['objects']:raise ValueError('Mimic object/target must name declared Scene objects')
    return object_id,target


def update_signals(plan,row,trackers,signals):
    from .pick_place import SignalValue
    # Delayed signals have a false pre-step latch before their first update.
    # Publish every declared channel from frame zero, preserving array alignment.
    for name in trackers:
        signals.setdefault(name,SignalValue(False,-1,'episode_start',{'initialized':True}))
    for name,tracker in trackers.items():
        if plan.function_bindings['signals.'+name].phase==row['phase']:
            row['signals']=dict(signals);signals[name]=tracker.update(row)
    row['signals']=dict(signals)


def success_at(plan,row):
    return predicate(plan,'success',row)if plan.function_bindings['success'].phase==row['phase']else False
