"""Short Builder calls used by the two session screens; no device connections."""
from pathlib import Path


def catalog(path,workspace=None):
    from real2sim_builder.project import Project
    from real2sim_builder.files import read
    project=Project(path,read_only=True);candidates=[]
    for scene in sorted(project.root.glob('scratch/agent/*/candidate_scene.yaml')):
        info=read(scene.parent/'candidate.json');candidates.append({'name':info['id'],'status':info['status'],'path':str(scene)})
    current=project.root/'working/current_scene.yaml'
    if current.is_file():candidates.append({'name':'Current authoring Scene','status':'DRAFT','path':str(current)})
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
            state=read(shot/'state.json')
            snapshots.append(dict(id=row['id'],path=str(path.parent),status='SAVED',q_measured=state['q_measured'],timestamp_ns=state['timestamp_ns'],unix_ns=state.get('timestamps',{}).get('follower',{}).get('end',{}).get('unix_ns'),quality=metadata.get('quality_warnings',[]),paired='pair.json'in metadata['files'],images={i['camera']:str(shot/i['path'])for i in metadata['images']},calibration_approved=False))
    for record in sorted((project.root/'input/observations').glob('*/COMPLETE')):
        root=record.parent;observation=read(root/'observation.json');snapshots.append({'id':root.name,'path':str(root),'unix_ns':observation['camera_timing']['side']['read_end']['unix_ns'],'q_measured':[],'images':{n:str(root/(n+'.png'))for n in('side','wrist')},'quality':[observation['reason']],'paired':False,'kind':'scene_materials'})
    from ..scene_preparation import scene_details
    details=scene_details(project.root)
    if workspace:
        from ..robot.registration import bound_configuration
        binding=bound_configuration(project.root,workspace);details['configuration_path']=str(binding)if binding else None
    return {**details,'snapshots':snapshots,'project':str(project.root),'name':project.info['name'],'id':project.info['id'],'candidates':candidates,'captures':evidence.get('capture_sessions',[])}


def execute(operation,arguments):
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
