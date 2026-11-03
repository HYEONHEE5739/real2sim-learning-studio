"""Read-only pipeline selectors; reuse Project registrations and Dataset readers."""
from pathlib import Path


def scenes(workspace):
    from ..scene_preparation import list_scenes
    from real2sim_builder.project import Project
    # Listing uses registration metadata. The existing prepare path checks the
    # complete selected Package; switching pages must not rehash every asset.
    rows=[]
    for item in list_scenes(workspace):
        project=Project(item['project'],read_only=True)
        for record in project.info.get('execution_packages',[]):
            scene=(project.root/record['path']/'scene.json').resolve()
            configs={key:str((project.root/value).resolve())for key,value in record.get('engine_config',{}).items()}
            if not scene.is_relative_to(project.root)or not scene.is_file()or any(not Path(p).is_relative_to(project.root)for p in configs.values()):continue
            rows.append({'name':project.info['name'],'project':str(project.root),'scene':str(scene),'scene_id':record['scene_id'],
                         'revision':record['revision'],'manifest_sha256':record['manifest_sha256'],'engines':sorted(configs),'engine_config':configs})
    return {'scenes':rows}


def dataset_inputs(workspace,path,stage):
    from ..data.native import load_catalog
    catalog=load_catalog(path);identity=catalog.execution.get('scene_identity')
    if not identity:raise ValueError('입력 데이터에 기록된 Scene identity가 없습니다. Scene을 명시적으로 선택하세요.')
    row=next((r for r in scenes(workspace)['scenes']if all(r.get(k)==v for k,v in identity.items())),None)
    if row is None:raise ValueError('입력 데이터와 정확히 일치하는 Scene Package를 찾지 못했습니다. 기록된 Scene을 명시적으로 선택하세요.')
    engine=catalog.execution.get('engine');engine='isaaclab'if engine=='isaac'else engine
    inputs={'dataset':str(catalog.root),'scene':row['scene']}
    if stage=='datagen':
        config=row['engine_config'].get('isaac'if engine=='isaaclab'else engine)
        if not config:raise ValueError('기록된 Scene 엔진 설정을 찾지 못했습니다.')
        inputs['engine_config']=config
    return {'inputs':inputs,'engine':engine}
