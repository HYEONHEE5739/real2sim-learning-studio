"""Shared Task evaluation/Annotation acceptance; no concrete engine imports."""
import numpy as np
from ..data.native import digest,DataError


def accept_annotation(physical_passed,frames,mode,marks):
    if mode not in ('auto','manual'):raise ValueError('Unknown Annotation mode')
    if not physical_passed:return False,None
    if mode=='auto':return True,None
    if len(marks)!=1 or not 0<marks[0]<frames-1:return False,None
    return True,marks[0]



def evaluation_result(*,placed,grasp,steps,limit):
    return dict(success=bool(placed),category='placement_success' if placed else 'max_steps' if steps>=limit else 'task_failure',
                steps=steps,grasp_latched=bool(grasp),placement=bool(placed))



def evaluation_execution(plan,execution,record):
    from ..recipe import _plain
    if any(b.kind=='placement' and b.name not in ('placement.fixed_xy','placement.random_workspace') for b in plan.function_bindings.values()):raise ValueError('Evaluation supports Fixed or Workspace Random placement')
    params=plan.function_bindings['success'].params
    if plan.function_bindings['success'].name!='pick_place.v8_evaluation':raise ValueError('P01 preserves explicit v8 Placement evaluation')
    for binding in plan.function_bindings.values():
        if binding.kind=='tracker' and getattr(binding.params,'object',None)!=params.object:raise ValueError('P01 tracker must observe the evaluated object')
        if binding.kind=='metrics' and (getattr(binding.params,'object',None)!=params.object or getattr(binding.params,'target',None)!=params.target):raise ValueError('P01 metric object/target mismatch')
    steps=max(1,int(np.ceil(plan.effective_settings['execution'].get('timeout_s',10)*30)))
    execution.update(policy_identity=digest(record),policy_checkpoint_step=record['step'],policy_files=record['files'],policy_training_dataset=record.get('dataset_identity'),
        evaluation_contract=digest({'bindings':_plain(plan.function_bindings),'max_steps':steps,'control_policy':'position_saturation_inward_v1','policy_device':'cpu','task_instruction':plan.effective_settings['execution'].get('task_instruction')}),
        episodes=plan.effective_settings['execution']['episodes'],max_steps=steps,rng_policy='entropy_workspace_poses_no_rng_resume_v1' if any(b.name=='placement.random_workspace' for b in plan.function_bindings.values()) else 'fixed_initial_base_seed_plus_attempt_minus_one')
    execution['recording'].update(timestamp_clock='episode_control_relative',engine_clock='physics_simulation_seconds',applied_command='commands/applied_joint_rad')
    return execution



def trackers_for(plan,eid,*,env_index=0):
    return {role.split('.',1)[1]:plan.tasks.functions[b.name].callable(params=b.params,episode={'episode_id':eid,'env_index':env_index,'control_dt_s':1/30}) for role,b in plan.function_bindings.items() if b.kind=='tracker'}



def post_evaluation(plan,row,trackers,signals,state,initial_positions,report):
    from ..tasks.pick_place import object_metrics
    for name,tracker in trackers.items():signals[name]=tracker.update(row)
    row['signals']=dict(signals);binding=plan.function_bindings['success'];placed=plan.tasks.functions[binding.name].callable(row,params=binding.params)
    if type(placed) is not bool:raise ValueError('Evaluation predicate must return bool')
    grasp=bool(signals.get('grasp') and signals['grasp'].value)
    for key,value in (('first_grasp_post_tick',grasp),('first_placement_post_tick',placed)):
        if value and report.get(key) is None:report[key]=row['tick']
    report['metrics']=object_metrics(plan.object_order,binding.params.object,{n:p[:3,3] for n,p in row['object_poses'].items()},row['eef_pose'][:3,3],state,grasp,placed,initial_positions)
    for role,b in plan.function_bindings.items():
        if b.kind=='metrics':report.setdefault('declared_metrics',{})[role]=plan.tasks.functions[b.name].callable(row,params=b.params)
    return placed,grasp



def report_limit(plan):return max(1,int(np.ceil(plan.effective_settings['execution'].get('timeout_s',10)*30)))

