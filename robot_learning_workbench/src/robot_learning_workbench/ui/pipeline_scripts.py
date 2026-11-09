from scene_contract.naming import numbered_path
"""Defaults and file semantics for the existing pipeline Recipe contract."""
from pathlib import Path
import uuid
import yaml
from .paths import output_path


INPUTS={
    'annotation':('dataset','scene'), 'datagen':('dataset','scene','engine_config'),
    'train':('dataset','training_config'), 'simulation_evaluation':('scene','engine_config','policy'),
    'offline_validation':('dataset','policy'), 'hub_download':('repo_id','revision'),
    'hub_upload':('artifact','repo_id','revision'),
    'real_evaluation':('policy','device_profile','calibration_profile','camera_config'),
}


def default_script(stage,workspace,engine):
    execution={
        'annotation':dict(mode='auto',env_num=1,headless=True),
        'datagen':dict(seed=1047,env_num=1,num_episodes=100,max_attempts=200,resume=False,headless=True),
        'train':dict(mode='scratch'),
        'simulation_evaluation':dict(seed=1047,env_num=1,episodes=10,timeout_s=20.0,headless=True,task_instruction=''),
        'offline_validation':dict(batch_size=1,max_batches=10),
        'hub_download':dict(repo_type='dataset'),
        'hub_upload':dict(repo_type='dataset',parent_commit='',private=True,confirm_upload=False),
        'real_evaluation':dict(mode='observe_only',episodes=1,max_frames=300,enable_motion=False,task_instruction=''),
    }[stage]
    data=dict(schema_version=1,stage=stage)
    if stage in ('annotation','datagen','simulation_evaluation'):data['engine']=engine
    output=Path(workspace)/'dataset'/numbered_path(Path(workspace)/'dataset',stage).name if stage in('hub_download','hub_upload')else output_path(workspace,stage)
    data.update(inputs={key:''for key in INPUTS[stage]},execution=execution,output={'directory':str(output)})
    if stage in ('annotation','datagen'):
        data['functions']={'acceptance':{'function':'pick_place.annotation'if stage=='annotation'else'pick_place.v8_datagen','params':{'object':'','target':''}}}
    if stage in ('datagen','simulation_evaluation'):data['objects']={}
    if stage=='simulation_evaluation':
        data['functions']={'success':{'function':'pick_place.v8_evaluation','params':{'object':'','target':''}}}
    text=yaml.safe_dump(data,sort_keys=False,allow_unicode=True)
    if stage=='annotation':text=text.replace('mode: auto','mode: auto  # auto / manual')
    if stage=='train':
        text=text.replace('mode: scratch','mode: scratch  # scratch / finetune / resume')
        text+='# finetune은 inputs.policy, resume는 inputs.checkpoint를 추가하고 공식 JSON도 같은 방식으로 설정하세요.\n'
    if stage in ('annotation','datagen','simulation_evaluation'):
        text+='# object / target에는 선택한 Scene의 물체 ID를 입력하세요. 다른 작업은 등록된 함수를 선언합니다.\n'
    if stage in ('datagen','simulation_evaluation'):
        text+='# objects에 사용할 선택형 작업 물체와 placement 함수를 선언하세요.\n'
    if stage in ('simulation_evaluation','real_evaluation'):text+='# task_instruction에는 Policy가 수행할 실제 작업 문장을 입력하세요.\n'
    return text


def rebase_paths(data,base):
    """Keep relative input/output meaning when saving the same script elsewhere."""
    for key,value in data.get('inputs',{}).items():
        if key in ('repo_id','revision')or not value:continue
        if isinstance(value,str)and not value.startswith('hf://')and not Path(value).is_absolute():data['inputs'][key]=str((base/value).resolve())
    output=data.get('output',{}).get('directory')
    if output and not Path(output).is_absolute():data['output']['directory']=str((base/output).resolve())
    return data
