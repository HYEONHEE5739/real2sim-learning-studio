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
        from robot_learning_workbench.robot.calibration import execution_urdf
        import xml.etree.ElementTree as ET
        for link in ET.parse(execution_urdf(package)).findall('link'):
            if link.find('visual')is not None and link.find('collision')is None:
                raise ValueError('Robot Collision geometry required for link '+link.get('name','UNKNOWN'))
        canonical=read(package.root/'authored_scene.json')
        if 'robot_base'not in package.scene['frames']:raise ValueError('Robot Base frame is unresolved')
        cameras={c['id']:c for c in canonical['cameras']}
        if not {'side','wrist'}<=set(cameras):raise ValueError('Native adapters require declared Side/Wrist sensors')
        if cameras['side'].get('camera_type')!='side' or cameras['wrist'].get('camera_type')!='wrist':
            raise ValueError('Explicit Side/Wrist camera roles are required')
        if any(cameras[n]['resolution']!=[640,480]for n in('side','wrist')):
            raise ValueError('Native Side/Wrist adapters require an explicit 640x480 sensor grid')
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


def register_export(project,package_path,*,source_project_id=None):
    project.require_writable();root=Path(package_path).resolve();package=verify_package(root)
    with exclusive(project):
        info=read(project.root/'project.yaml');rows=info.get('execution_packages',[])
        existing=None
        for entry in rows:
            same_path=(project.root/entry['path']).resolve()==root
            same_revision=(entry['scene_id'],entry['revision'])==(package.identity.scene_id,package.identity.revision)
            if same_path or same_revision:
                if existing or not(same_path and same_revision and entry['manifest_sha256']==package.identity.manifest_sha256):
                    raise ValueError('Conflicting immutable native revision')
                existing=entry
        settings={};created=[];profiles={}
        try:
            for engine in package.scene['engines']:
                declared=read(root/'execution_profiles.json').get(engine,{})
                if set(declared)-{'pose','physics'}:raise ValueError('Only Native Pose/Physics profiles may be registered')
                profiles[engine]={}
                for mode,values in declared.items():
                    path=project.root/'configuration'/('native-'+package.identity.manifest_sha256+'-'+engine+'-'+mode+'.json')
                    from dataclasses import asdict
                    payload={**values,'render_type':'native','simulation_mode':mode,'scene_identity':asdict(package.identity)}
                    if path.is_symlink()or path.parent.is_symlink():raise ValueError('Native execution settings symlink is forbidden')
                    if path.exists():
                        if read(path)!=payload:raise ValueError('Immutable native execution settings changed')
                    else:write(path,payload);created.append(path)
                    profiles[engine][mode]=path.relative_to(project.root).as_posix()
                if 'pose'in profiles[engine]:settings[engine]=profiles[engine]['pose']
            row={'path':root.relative_to(project.root).as_posix()if root.is_relative_to(project.root)else str(root),'scene_id':package.identity.scene_id,'revision':package.identity.revision,
                 'manifest_sha256':package.identity.manifest_sha256,'source_project_id':source_project_id or project.info['id'],'engine_config':settings}
            row.update(engine_profiles=profiles,execution_readiness=read(root/'scene.json')['validation']['native_readiness'])
            if existing is None:
                write(project.root/'project.yaml',{**info,'execution_packages':[*rows,row]})
            elif existing!=row:
                raise ValueError('Registered native profile differs from verified package')
        except BaseException:
            for path in created:path.unlink(missing_ok=True)
            raise
        project.info=read(project.root/'project.yaml')
    return row
