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
    scene=copy.deepcopy(source.scene);scene['name']=name;scene.get('robot_model',{}).pop('simulation_joint_offsets_rad',None);validate(scene,project.root);project.save_scene(scene)
    candidates=[]
    for info in sorted((source.root/'scratch/agent').glob('*/candidate.json')):
        old_scene=read(info.parent/'candidate_scene.yaml');old_scene.get('robot_model',{}).pop('simulation_joint_offsets_rad',None);validate(old_scene,project.root)
        candidate=Candidate.create(project,info.parent.name);old_scene['name']=name;write(candidate.root/'candidate_scene.yaml',old_scene)
        record=candidate.info;record.update(base_signature=project.signature(scene),base_scene_sha256=sha(project.root/'working/current_scene.yaml'),source_revision={'sha256':sha(info),'status':read(info)['status']})
        write(candidate.root/'candidate.json',record)
        for file in sorted(info.parent.rglob('*')):
            # Large transient Blender/MJCF exports are reproducible outputs, not authoring inputs.
            if file.is_file()and file.suffix in('.json','.yaml','.txt','.md','.csv','.png','.jpg')and not any(part in('blender','baseline')for part in file.relative_to(info.parent).parts):
                own_file(file,project.root/'input/migration/candidates'/info.parent.name/file.relative_to(info.parent),workspace,records)
        candidates.append({'id':candidate.name,'source_scene_sha256':sha(info.parent/'candidate_scene.yaml'),'scene_sha256':sha(candidate.root/'candidate_scene.yaml')})
    own_file(source.root/'project.yaml',project.root/'input/migration/source-project.yaml',workspace,records)
    own_file(source.root/'working/current_scene.yaml',project.root/'input/migration/source-scene.yaml',workspace,records)
    own_file(source.root/'working/state.json',project.root/'input/migration/source-state.json',workspace,records)
    project.update(status='NEEDS_MORE_DATA',decision='REQUEST_USER_INPUT',needs=['Imported revisions require validation in the owned project; historical acceptance is not promoted'])
    report={'source_project_id':source.info['id'],'source_scene_sha256':sha(source.root/'working/current_scene.yaml'),'project':str(project.root),'name':name,'files':records,'candidates':candidates,'physical_verified':False}
    write(project.root/'input/migration/provenance.json',report)
    return report


def register_package(project,source,workspace):
    """Own an already-closed executable revision without rewriting its identity."""
    from scene_contract.package import load_scene
    from dataclasses import asdict
    source=Path(source).resolve();package=load_scene(source/'scene.json');destination=project.root/'exports'/package.identity.revision
    records=[]
    for file in sorted(source.rglob('*')):
        if file.is_file():own_file(file,destination/file.relative_to(source),workspace,records)
    owned=load_scene(destination/'scene.json')
    if owned.identity!=package.identity:raise ValueError('Closed package identity changed while registering')
    row={'path':str(destination.relative_to(project.root)),'scene_id':owned.identity.scene_id,'revision':owned.identity.revision,'manifest_sha256':owned.identity.manifest_sha256,'source_project_id':package.identity.scene_id}
    info=read(project.root/'project.yaml');info.setdefault('execution_packages',[]).append(row);write(project.root/'project.yaml',info);project.info=info
    write(project.root/'input/migration/package-provenance.json',{'identity':asdict(owned.identity),'files':records,'relation':'same closed execution revision, new authoring project ownership; not a re-export'})
    return {**row,'path':str(destination)}


def adopt_registered_geometry(project,package_path):
    """Reference existing baked v8 assets explicitly; archive its retired runtime offsets."""
    import numpy as np
    from scene_contract.package import load_scene
    package=load_scene(Path(package_path)/'scene.json');records=package.calibration['records']
    baked=[(key,r)for key,r in records.items()if r['kind']=='robot_residual'and r['application']['mode']=='baked']
    if len(baked)!=1:raise ValueError('One explicit historical geometry revision required')
    name,record=baked[0];files={f.sha256:package.root/f.path for f in package.files}
    measured=files[record['source_model_sha256']];geometry=files[record['execution_model_sha256']]
    paths=[project.root/'working/current_scene.yaml',*sorted((project.root/'scratch/agent').glob('*/candidate_scene.yaml'))];rows=[]
    source_root=project.root/'input/migration'
    for path in paths:
        scene=read(path);model=scene['robot_model'];historical=read(source_root/'source-scene.yaml')if path.parent.name=='working'else read(source_root/'candidates'/path.parent.name/'candidate_scene.yaml')
        had_residual='simulation_joint_offsets_rad'in historical['robot_model']
        model['path']=str((geometry if had_residual else measured).relative_to(project.root));model['model_sha256']=sha(geometry if had_residual else measured)
        model['measurement_model_path']=str(measured.relative_to(project.root));model['measurement_model_sha256']=sha(measured)
        if had_residual:model['geometry_binding']={'package':str((package.root/'scene.json').relative_to(project.root)),'calibration_id':name}
        model.pop('simulation_joint_offsets_rad',None);validate(scene,project.root);write(path,scene)
        rows.append({'path':str(path.relative_to(project.root)),'geometry_sha256':model['model_sha256'],'measurement_sha256':sha(measured),'q_adjustment_rad':[0.]*len(model['joint_names']),'historical_residual_archived':had_residual})
    for path in paths[1:]:
        info=read(path.parent/'candidate.json');info.update(base_signature=project.signature(project.scene),base_scene_sha256=sha(paths[0]));write(path.parent/'candidate.json',info)
    report=read(project.root/'input/migration/provenance.json');report['geometry_adoption']=rows
    for row in report['candidates']:row['scene_sha256']=sha(project.root/'scratch/agent'/row['id']/'candidate_scene.yaml')
    write(project.root/'input/migration/provenance.json',report)
    return {'measurement_model':str(measured),'geometry_model':str(geometry),'rows':rows}
