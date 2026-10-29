"""Explicit authoring-data migration into owned Builder projects, not project cloning."""
from pathlib import Path
import copy,os,shutil
from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import read,write,sha
from real2sim_builder.scene import validate,local_path


def own_file(source,target,workspace,records):
    source=Path(source).resolve();target=Path(target);workspace=Path(workspace).resolve()
    if not target.resolve().is_relative_to(workspace):raise ValueError('Migration target must be owned by workspace')
    if not source.is_file():raise FileNotFoundError(source)
    digest=sha(source);pool=workspace/'.assets'/digest;pool.parent.mkdir(parents=True,exist_ok=True)
    if not pool.exists():
        temporary=pool.with_suffix('.pending');shutil.copyfile(source,temporary)
        if sha(temporary)!=digest:temporary.unlink();raise ValueError('Source changed during migration')
        os.replace(temporary,pool)
    if sha(pool)!=digest:raise ValueError('Owned asset hash changed')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if sha(target)!=digest:raise ValueError('Migration target conflict: '+str(target))
    else:os.link(pool,target)
    records.append({'source':str(source),'source_sha256':digest,'path':str(target.relative_to(workspace)),'sha256':digest})
    return target


def migrate_authoring(source,workspace,name):
    """Recreate lifecycle/identity; preserve valid source evidence and candidate inputs."""
    source=Project(source,read_only=True);workspace=Path(workspace).resolve();records=[]
    if(source.root/'working/run.lock').exists():raise ValueError('Source has an unresolved active writer')
    project=Project.create(workspace/'scenes',name)
    # Input snapshots already have internal hashes; their bytes and relative closure stay intact.
    for file in sorted((source.root/'input').rglob('*')):
        if file.is_file()and file!=source.root/'input/evidence.yaml':own_file(file,project.root/file.relative_to(source.root),workspace,records)
    write(project.root/'input/evidence.yaml',source.evidence)
    scene=copy.deepcopy(source.scene);scene['name']=name;validate(scene,project.root);project.save_scene(scene)
    candidates=[]
    for info in sorted((source.root/'scratch/agent').glob('*/candidate.json')):
        old_scene=read(info.parent/'candidate_scene.yaml');validate(old_scene,project.root)
        candidate=Candidate.create(project,info.parent.name);old_scene['name']=name;write(candidate.root/'candidate_scene.yaml',old_scene)
        record=candidate.info;record.update(base_signature=project.signature(scene),base_scene_sha256=sha(project.root/'working/current_scene.yaml'),source_revision={'sha256':sha(info),'status':read(info)['status']})
        write(candidate.root/'candidate.json',record)
        for file in sorted(info.parent.rglob('*')):
            # Large transient Blender/MJCF exports are reproducible outputs, not authoring inputs.
            if file.is_file()and file.suffix in('.json','.yaml','.txt','.md','.csv')and not any(part in('blender','baseline')for part in file.relative_to(info.parent).parts):
                own_file(file,project.root/'input/migration/candidates'/info.parent.name/file.relative_to(info.parent),workspace,records)
        candidates.append({'id':candidate.name,'source_scene_sha256':sha(info.parent/'candidate_scene.yaml'),'scene_sha256':sha(candidate.root/'candidate_scene.yaml')})
    own_file(source.root/'project.yaml',project.root/'input/migration/source-project.yaml',workspace,records)
    own_file(source.root/'working/current_scene.yaml',project.root/'input/migration/source-scene.yaml',workspace,records)
    own_file(source.root/'working/state.json',project.root/'input/migration/source-state.json',workspace,records)
    project.update(status='NEEDS_MORE_DATA',decision='REQUEST_USER_INPUT',needs=['Imported revisions require validation in the owned project; historical acceptance is not promoted'])
    report={'source_project_id':source.info['id'],'source_scene_sha256':sha(source.root/'working/current_scene.yaml'),'project':str(project.root),'name':name,'files':records,'candidates':candidates,'physical_verified':False}
    write(project.root/'input/migration/provenance.json',report)
    return report
