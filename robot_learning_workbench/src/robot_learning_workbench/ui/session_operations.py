"""Short Builder calls used by the two session screens; no device connections."""
from pathlib import Path


def saved_snapshots(project):
    """Restore registered captures through the existing readers, without device IO."""
    from real2sim_builder.capture import load_session
    from real2sim_builder.files import read
    from real2sim_builder.scene import local_path
    rows=[];errors=[];seen=set()
    for record in project.evidence.get('capture_sessions',[]):
        try:
            root=local_path(project.root,record['path']).parent
            if root in seen:continue
            seen.add(root);stored=read(root/'capture_manifest.yaml')
            layouts={s.get('scene_state_id')for s in stored.get('snapshots',[])}
            if stored.get('schema')=='real2sim.snapshot/1'and len(layouts)>1:
                from real2sim_builder.capture import load_snapshots
                batches=[load_snapshots(root,scene_state=layout)for layout in sorted(layouts)]
                manifest=batches[0][0];samples=[sample for _,rows,_ in batches for sample in rows]
            else:manifest,samples,_=load_session(root)
            for sample in samples:
                images={i['camera']:str(local_path(root,i['path']))for i in sample['images']}
                for image in sample['images']:
                    if image.get('runtime_baseline'):images['sim_'+image['camera']]=str(local_path(root,image['runtime_baseline']['path']))
                state=read(local_path(root,sample['metadata_path']).parent/'state.json')if sample.get('metadata_path')else sample
                unix_ns=state.get('timestamps',{}).get('follower',{}).get('end',{}).get('unix_ns',state.get('unix_ns'))
                rows.append(dict(id=sample['id'],path=str(root),images=images,q_measured=sample['q_measured'],unix_ns=unix_ns,
                    timestamp_ns=sample['timestamp_ns'],session_id=manifest.get('session_identity',manifest['session_id']),paired=any(n.startswith('sim_')for n in images)))
        except (OSError,ValueError,KeyError,TypeError)as error:errors.append(record['path']+': '+str(error))
    for record in project.evidence.get('documents',[]):
        if record.get('role')!='unbound_sdk_camera_observation':continue
        try:
            path=local_path(project.root,record['path']);root=path.parent
            if not(root/'COMPLETE').is_file():raise ValueError('Incomplete observation')
            data=read(path);images={n:str(local_path(root,n+'.png'))for n in data['camera_timing']}
            if any(not Path(p).is_file()for p in images.values()):raise ValueError('Missing observation image')
            rows.append(dict(id=root.name,path=str(root),images=images,q_measured=[],unix_ns=data['camera_timing']['side']['read_end']['unix_ns'],
                session_id=data['session_id'],paired=False,kind='scene_materials'))
        except (OSError,ValueError,KeyError,TypeError)as error:errors.append(record['path']+': '+str(error))
    return sorted(rows,key=lambda row:(row.get('unix_ns')or 0,row['path'],row['id'])),errors


def catalog(path,workspace=None):
    from real2sim_builder.project import Project
    project=Project(path,read_only=True)
    from ..scene_preparation import scene_details
    details=scene_details(project.root)
    evidence=project.evidence;observations=project.root/'input/observations'
    capture_paths={row['path']for row in evidence.get('images',[])if row.get('capture_manifest')or Path(row.get('source')or'').is_relative_to(observations)}
    capture_paths.update(row['path']for row in evidence.get('documents',[])if row.get('role')=='unbound_sdk_camera_observation')
    # The preparation sidebar edits supplied materials, not the capture archive.
    details['inputs']=[row for row in details['inputs']if row['kind']!='capture'and row['path']not in capture_paths]
    details['snapshots'],details['snapshot_errors']=saved_snapshots(project)
    if workspace:
        from ..robot.registration import bound_configuration
        binding=bound_configuration(project.root,workspace);details['configuration_path']=str(binding)if binding else None
    return {**details,'project':str(project.root),'name':project.info['name'],'id':project.info['id']}


def execution_scenes(workspace):
    from ..scene_preparation import list_scenes
    from real2sim_builder.project import Project
    from scene_contract.package import load_scene,SceneIdentity
    rows=[]
    for item in list_scenes(workspace):
        project=Project(item['project'],read_only=True);registered=project.info.get('execution_packages',[])
        for record in registered:
            scene=(project.root/record['path']/'scene.json').resolve()
            try:
                package=load_scene(scene,expected=SceneIdentity(record['scene_id'],record['revision'],record['manifest_sha256']))
            except (ValueError,OSError):continue
            rows.append({'name':item['name'],'revision':record['revision'],'project':item['project'],'project_id':project.info['id'],'scene_id':record['scene_id'],'scene':str(scene),'engines':sorted(set(record.get('engine_config',{}))&set(package.scene['engines']))})
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
    if config is None:raise ValueError('장치 구성이 없습니다. Scene Prepare의 장치 설정을 먼저 저장하세요.')
    data=read(config);keys=('device_profile','calibration_profile','leader_device_profile','leader_calibration_profile','camera_config','robot_model','source_robot_model');inputs={k:str((config.parent/v).resolve())for k,v in data['inputs'].items()if k in keys}
    required={'device_profile','calibration_profile','camera_config','robot_model'}
    if not required<=inputs.keys():raise ValueError('Follower의 Model/Precision/Camera 구성을 확인하세요.')
    settings=(project.root/matches[0]['engine_config'][engine_key]).resolve()
    if not settings.is_relative_to(project.root):raise ValueError('Scene engine settings escaped selected Project')
    inputs.update(project=str(project.root),scene=str(scene),engine_config=str(settings))
    recipe={'schema_version':1,'stage':'paired_session','engine':engine,'inputs':inputs,'execution':{'device_source':data['execution']['device_source']},'output':{'directory':'new-real-sim'}}
    return {'project':str(project.root),'name':project.info['name'],'recipe':recipe,'configuration':str(config)}


def execute(operation,arguments):
    if operation=='session_execution_scenes':return execution_scenes(arguments['workspace'])
    if operation=='session_real_setup':return real_sim_setup(**arguments)
    if operation=='session_project':return catalog(arguments['path'],arguments.get('workspace'))
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
