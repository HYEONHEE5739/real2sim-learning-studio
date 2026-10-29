"""Short Builder calls used by the two session screens; no device connections."""
from pathlib import Path


def catalog(path):
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
    return {'snapshots':snapshots,'project':str(project.root),'name':project.info['name'],'id':project.info['id'],'candidates':candidates,'captures':evidence.get('capture_sessions',[])}


def execute(operation,arguments):
    if operation=='session_project':return catalog(arguments['path'])
    if operation=='session_new_project':
        from real2sim_builder.project import Project
        return catalog(Project.create(arguments['directory'],arguments['name']).root)
    if operation=='session_snapshots':
        from real2sim_builder.capture import load_snapshots
        manifest,rows,_=load_snapshots(arguments['path']);return {'manifest':manifest,'rows':rows}
    raise ValueError('Unknown session operation')
