"""Publish verified export references in their owning Project; no engine startup."""
from pathlib import Path
from .files import read,write
from .candidate import exclusive
from .export import verify_package


def native_profiles(package, options, image_records):
    """Verify new execution inputs with the existing loaders, never hardware.

    Pose readiness, physics input readiness and independent physical validation
    are different claims. A missing native input never selects authored rendering.
    """
    import copy
    import math
    from robot_learning_workbench.robot.calibration import JOINTS,mapper_from_scene
    profiles={};readiness={}
    try:
        if not package.scene['robot']:raise ValueError('Native execution requires an articulated robot/URDF')
        records=[n for n,r in package.calibration['records'].items()
            if r['kind']=='encoder_mapping' and r['application'].get('phase')=='device_observation']
        if len(records)!=1:raise ValueError('One manifest-bound Follower measured-q Mapping is required')
        mapper=mapper_from_scene(package,records[0],role='follower',phase='device_observation')
        canonical=read(package.root/'authored_scene.json')
        if 'robot_base'not in package.scene['frames']:raise ValueError('Robot Base frame is unresolved')
        cameras={c['id']:c for c in canonical['cameras']}
        if not {'side','wrist'}<=set(cameras):raise ValueError('Native adapters require declared Side/Wrist sensors')
        if cameras['side'].get('camera_type')!='side' or cameras['wrist'].get('camera_type')!='wrist':
            raise ValueError('Explicit Side/Wrist camera roles are required')
        frame=cameras['wrist']['frame'];mounted=False
        while frame is not None:
            mounted|=frame.startswith('robot_link_');frame=canonical['frames'][frame]['parent']
        if not mounted:raise ValueError('Wrist sensor requires a shared robot-link mount/FK')
        frame=cameras['side']['frame']
        while frame is not None:
            if frame.startswith('robot_link_'):raise ValueError('Side sensor must be fixed')
            frame=canonical['frames'][frame]['parent']
        q=options.get('initial_joint_rad')
        if q is None:
            q=next((row['q_measured'] for row in image_records
                if row.get('robot_model_sha256')==mapper.profile['urdf_sha256']
                and row.get('joint_names')==list(JOINTS) and row.get('q_measured')is not None),None)
        if not isinstance(q,(list,tuple)) or len(q)!=6 or any(type(x)not in(int,float)or not math.isfinite(x)for x in q):
            raise ValueError('Explicit six initial_joint_rad values or matching measured Capture are required')
        base=dict(initial_joint_rad=list(q),active_object_ids=[],object_physics={})
        dynamic=[n for n,o in package.scene['objects'].items()if o['role']=='task_object']
        physics_needs=[]
        for n in dynamic:
            physical=package.scene['objects'][n]['physics']
            for key in ('mass_kg','friction'):
                value=physical.get(key);value=value.get('value')if hasattr(value,'get')else value
                if type(value)not in(int,float)or not math.isfinite(value)or value<0 or(key=='mass_kg'and value==0):
                    physics_needs.append(n+': explicit positive mass / nonnegative friction required ('+key+')')
        for engine in ('mujoco','isaac'):
            row=dict(status='BLOCKED',pose='BLOCKED',physics='BLOCKED',physical_verified=False,needs=[])
            settings=copy.deepcopy(base)
            try:
                if engine=='mujoco':
                    from robot_learning_workbench.engines.mujoco.model import ModelConfig,build_model
                    build_model(package,ModelConfig(**settings),projection_adapter=True)
                else:
                    from robot_learning_workbench.engines.isaac.env_cfg import scene_execution_inputs
                    from pxr import Usd,UsdPhysics
                    inputs=scene_execution_inputs(package,settings,projection_adapter=True)
                    stage=Usd.Stage.Open(str(inputs['robot_usd']))
                    if not stage or not any(p.HasAPI(UsdPhysics.ArticulationRootAPI)for p in stage.Traverse()):
                        raise ValueError('Packaged Isaac USD has no ArticulationRoot; no static USD fallback')
                profiles[engine]={'pose':settings}
                row.update(status='READY',pose='READY',loader='COMPILED'if engine=='mujoco'else'DECLARATIONS_CHECKED',runtime='NOT_TESTED')
                if physics_needs:row['needs'].extend(physics_needs)
                else:
                    physical={**copy.deepcopy(base),'active_object_ids':dynamic}
                    if engine=='mujoco':build_model(package,ModelConfig(**physical))
                    else:scene_execution_inputs(package,physical)
                    profiles[engine]['physics']=physical;row['physics']='READY'
            except (ImportError,OSError,ValueError,KeyError,TypeError)as error:
                row['needs'].append(str(error))
            readiness[engine]=row
    except (ImportError,OSError,ValueError,KeyError,TypeError)as error:
        readiness={e:dict(status='BLOCKED',pose='BLOCKED',physics='BLOCKED',physical_verified=False,needs=[str(error)])for e in('mujoco','isaac')}
    return profiles,readiness


def register_export(project,package_path,*,engine_config=None,source_project_id=None,execution_mode='authored'):
    project.require_writable();root=Path(package_path).resolve();package=verify_package(root)
    with exclusive(project):
        info=read(project.root/'project.yaml');rows=info.get('execution_packages',[])
        if any((project.root/r['path']).resolve()==root for r in rows):raise ValueError('Export already registered; revisions are immutable')
        settings={};created=[];profiles={}
        try:
            for engine in package.scene['engines']:
                if engine_config is None and execution_mode=='native':
                    declared=read(root/'execution_profiles.json').get(engine,{})
                    profiles[engine]={}
                    for mode,values in declared.items():
                        path=project.root/'configuration'/('native-'+package.identity.manifest_sha256+'-'+engine+'-'+mode+'.json')
                        from dataclasses import asdict
                        payload={**values,'render_type':'native','simulation_mode':mode,'scene_identity':asdict(package.identity)}
                        if path.exists():
                            if read(path)!=payload:raise ValueError('Immutable native execution settings changed')
                        else:write(path,payload);created.append(path)
                        profiles[engine][mode]=path.relative_to(project.root).as_posix()
                    if 'pose'in profiles[engine]:settings[engine]=profiles[engine]['pose']
                elif engine_config is None:
                    if not (root/'authored_scene.json').is_file():raise ValueError('Authored export scene required for default render settings')
                    path=project.root/'configuration/export-authored-preview.json'
                    if path.is_symlink()or path.parent.is_symlink():raise ValueError('Default preview settings symlink is forbidden')
                    if path.exists():
                        if read(path)!={'render_type':'authored'}:raise ValueError('Default preview settings changed; supply explicit engine settings')
                    else:write(path,{'render_type':'authored'});created.append(path)
                    settings[engine]=path.relative_to(project.root).as_posix()
                elif engine in engine_config:settings[engine]=engine_config[engine]
            row={'path':root.relative_to(project.root).as_posix()if root.is_relative_to(project.root)else str(root),'scene_id':package.identity.scene_id,'revision':package.identity.revision,
                 'manifest_sha256':package.identity.manifest_sha256,'source_project_id':source_project_id or project.info['id'],'engine_config':settings}
            if execution_mode=='native':
                row.update(engine_profiles=profiles,execution_readiness=read(root/'scene.json')['validation']['native_readiness'])
            write(project.root/'project.yaml',{**info,'execution_packages':[*rows,row]})
        except BaseException:
            for path in created:path.unlink(missing_ok=True)
            raise
        project.info=read(project.root/'project.yaml')
    return row
