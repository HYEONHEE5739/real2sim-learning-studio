"""Short Builder calls used by the two session screens; no device connections."""
from pathlib import Path


def catalog(path,workspace=None):
    from real2sim_builder.project import Project
    from real2sim_builder.files import read
    project=Project(path,read_only=True)
    evidence=read(project.root/'input/evidence.yaml')
    snapshots=[]
    from real2sim_builder.files import sha
    for source in evidence.get('capture_sessions',[]):
        path=project.root/source['path']
        if sha(path)!=source['sha256']:raise ValueError('Registered Capture manifest changed')
        manifest=read(path)
        if manifest.get('schema')!='real2sim.snapshot/1':continue
        for row in manifest['snapshots']:
            shot=path.parent/row['path'];metadata=read(shot/'metadata.json')
            if sha(shot/'metadata.json')!=row['metadata_sha256'] or sha(shot/'state.json')!=metadata['files']['state.json']:raise ValueError('Capture metadata changed')
            state=read(shot/'state.json');images={i['camera']:str(shot/i['path'])for i in metadata['images']}
            if 'pair.json'in metadata['files']:
                if sha(shot/'pair.json')!=metadata['files']['pair.json']:raise ValueError('Pair metadata changed')
                pair=read(shot/'pair.json');images.update({'sim_'+n:str(shot/file)for n,file in pair['sim_images'].items()})
            snapshots.append(dict(id=row['id'],path=str(path.parent),status='SAVED',q_measured=state['q_measured'],timestamp_ns=state['timestamp_ns'],unix_ns=state.get('timestamps',{}).get('follower',{}).get('end',{}).get('unix_ns'),quality=metadata.get('quality_warnings',[]),paired='pair.json'in metadata['files'],images=images,calibration_approved=False))
    for record in sorted((project.root/'input/observations').glob('*/COMPLETE')):
        root=record.parent;observation=read(root/'observation.json');snapshots.append({'id':root.name,'path':str(root),'unix_ns':observation['camera_timing']['side']['read_end']['unix_ns'],'q_measured':[],'images':{n:str(root/(n+'.png'))for n in('side','wrist')},'quality':[observation['reason']],'paired':False,'kind':'scene_materials'})
    from ..scene_preparation import scene_details
    details=scene_details(project.root)
    if workspace:
        from ..robot.registration import bound_configuration
        binding=bound_configuration(project.root,workspace);details['configuration_path']=str(binding)if binding else None
    return {**details,'snapshots':snapshots,'project':str(project.root),'name':project.info['name'],'id':project.info['id'],'captures':evidence.get('capture_sessions',[])}


def execution_scenes(workspace):
    from ..scene_preparation import list_scenes
    from real2sim_builder.project import Project
    from real2sim_builder.files import read
    rows=[]
    for item in list_scenes(workspace):
        project=Project(item['project'],read_only=True);registered=project.info.get('execution_packages',[])
        for record in registered:
            scene=(project.root/record['path']/'scene.json').resolve()
            if not scene.is_relative_to(project.root)or not scene.is_file():continue
            rows.append({'name':item['name'],'revision':record['revision'],'project':item['project'],'scene':str(scene)})
    return {'scenes':rows}


def real_sim_setup(workspace,project,scene,engine):
    from real2sim_builder.project import Project
    from real2sim_builder.files import read
    from ..robot.registration import bound_configuration
    project=Project(project,read_only=True);scene=Path(scene).resolve();engine_key='isaac'if engine=='isaaclab'else engine
    matches=[r for r in project.info.get('execution_packages',[])if(project.root/r['path']/'scene.json').resolve()==scene]
    if len(matches)!=1:raise ValueError('Choose a registered executable Scene Package')
    from scene_contract.package import load_scene,SceneIdentity
    registered=matches[0];load_scene(scene,expected=SceneIdentity(registered['scene_id'],registered['revision'],registered['manifest_sha256']))
    if engine_key not in('isaac','mujoco')or engine_key not in matches[0].get('engine_config',{}):raise ValueError('Selected Scene has no bound configuration for this engine')
    config=bound_configuration(project.root,workspace)
    if config is None:raise ValueError('장치 구성이 없습니다. Real2Sim Capture의 장치 설정을 먼저 저장하세요.')
    data=read(config);keys=('device_profile','calibration_profile','leader_device_profile','leader_calibration_profile','camera_config','robot_model','source_robot_model');inputs={k:str((config.parent/v).resolve())for k,v in data['inputs'].items()if k in keys}
    required={'device_profile','calibration_profile','camera_config','robot_model'}
    if not required<=inputs.keys():raise ValueError('Follower의 Model/Precision/Camera 구성을 확인하세요.')
    settings=(project.root/matches[0]['engine_config'][engine_key]).resolve()
    if not settings.is_relative_to(project.root):raise ValueError('Scene engine settings escaped selected Project')
    inputs.update(project=str(project.root),scene=str(scene),engine_config=str(settings))
    recipe={'schema_version':1,'stage':'paired_session','engine':engine,'inputs':inputs,'execution':{'device_source':data['execution']['device_source']},'output':{'directory':'new-real-sim'}}
    details=catalog(project.root,workspace)
    return {'project':str(project.root),'name':project.info['name'],'recipe':recipe,'snapshots':[r for r in details['snapshots']if r.get('paired')],'configuration':str(config)}


def execute(operation,arguments):
    if operation=='session_execution_scenes':return execution_scenes(arguments['workspace'])
    if operation=='session_real_setup':return real_sim_setup(**arguments)
    if operation=='session_project':return catalog(arguments['path'],arguments.get('workspace'))
    if operation=='session_catalog':
        from ..scene_preparation import list_scenes
        return {'scenes':list_scenes(arguments['workspace'])}
    if operation=='session_materials':
        from ..scene_preparation import save_inputs
        save_inputs(arguments['path'],arguments['files'],arguments['notes']);return catalog(arguments['path'],arguments['workspace'])
    if operation=='session_devices':
        from ..robot.registration import discover
        return discover()
    if operation=='session_device_configure':
        from ..robot.registration import configure_selected
        return {'path':str(configure_selected(arguments['workspace'],arguments['name'],arguments['choices'],existing=arguments.get('existing')))}
    if operation=='session_device_save':
        from ..robot.registration import save_configuration
        return {'path':str(save_configuration(arguments['workspace'],arguments['name'],arguments['recipe']))}
    if operation=='session_bind':
        from ..robot.registration import bind_configuration
        bind_configuration(arguments['path'],arguments['configuration'],arguments['workspace']);return catalog(arguments['path'],arguments['workspace'])
    if operation=='session_new_project':
        from real2sim_builder.project import Project
        return catalog(Project.create(arguments['directory'],arguments['name']).root,Path(arguments['directory']).parent)
    if operation=='session_snapshots':
        from real2sim_builder.capture import load_snapshots
        manifest,rows,_=load_snapshots(arguments['path']);return {'manifest':manifest,'rows':rows}
    raise ValueError('Unknown session operation')
