"""User-selected Precision file save and automatic device-configuration binding."""
from contextlib import ExitStack
from pathlib import Path
import copy,os,uuid,yaml
from ..data.native import encoded,file_sha256,_sync
from .registration import save_configuration,bind_configuration


def _replace_bytes(path,raw,*,exclusive=False):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if exclusive:os.link(temporary,path)
        else:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def save_profile(session,profile,path,overwrite):
    session.unchanged();path=Path(path)
    if not path.is_absolute():raise ValueError('Absolute Precision file path required')
    path=path.resolve();workspace=session.workspace
    if path.suffix!='.json'or not any(path.is_relative_to(workspace/name)for name in('devices','calibration'))or path.is_relative_to(workspace/'calibration/history'):
        raise ValueError('Save Precision JSON under workspace/devices or workspace/calibration')
    if overwrite:
        if path!=session.source_profile or not path.is_file():raise ValueError('Existing save must target the selected Precision file')
    elif path.exists():raise ValueError('Save As requires a new file name')
    old=path.read_bytes()if path.exists()else None
    source=session.source_profile
    if source:
        history=workspace/'calibration/history'/(session.source_hash+'.json');history.parent.mkdir(parents=True,exist_ok=True)
        if history.exists():
            if file_sha256(history)!=session.source_hash:raise ValueError('Previous Precision history changed')
        else:_replace_bytes(history,source.read_bytes())
        profile.update(parent_sha256=session.source_hash,parent_path=str(history))
    configuration=copy.deepcopy(session.config)
    configuration['inputs']={key:str((session.configuration.parent/value).resolve())for key,value in configuration['inputs'].items()}
    key='calibration_profile'if session.role=='follower'else'leader_calibration_profile'
    configuration['inputs'][key]=str(path);configuration['inputs']['robot_model']=str(session.model)
    if {'calibration_profile','leader_calibration_profile','device_profile','leader_device_profile','camera_config'}<=configuration['inputs'].keys():configuration['stage']='capture_session'
    old_configuration=session.configuration
    same=configuration['inputs']=={key:str((old_configuration.parent/value).resolve())for key,value in session.config['inputs'].items()}and configuration['stage']==session.config['stage']
    target=old_configuration if same else save_configuration(workspace,'precision-'+session.role,configuration)
    previous={};changed=[];published=False
    try:
        with ExitStack()as locks:
            if target!=old_configuration:
                for metadata in sorted((workspace/'scenes').glob('*/project.yaml')):
                    info=yaml.safe_load(metadata.read_text());binding=info.get('device_configuration',{})
                    if not binding or(metadata.parent/binding['path']).resolve()!=old_configuration:continue
                    from real2sim_builder.project import Project,exclusive
                    project=Project(metadata.parent);locks.enter_context(exclusive(project));current=yaml.safe_load(metadata.read_text()).get('device_configuration',{})
                    if current!=binding or binding.get('sha256')!=session.config_hash:raise ValueError('Scene device binding changed; reload the device configuration')
                    previous[metadata]=metadata.read_bytes()
            session.unchanged();path.parent.mkdir(parents=True,exist_ok=True)
            if not overwrite and path.exists():raise ValueError('Save As target appeared during save')
            _replace_bytes(path,encoded(profile),exclusive=not overwrite);published=True;_sync(path.parent)
            try:
                for metadata in previous:
                    changed.append(metadata);bind_configuration(metadata.parent,target,workspace)
            except Exception:
                for metadata in reversed(changed):_replace_bytes(metadata,previous[metadata])
                raise
    except Exception:
        if published:
            if old is None:path.unlink(missing_ok=True)
            else:_replace_bytes(path,old)
        if target!=old_configuration:
            import shutil
            shutil.rmtree(target.parent)
        raise
    session.configuration=target;session.config=configuration;session.config_hash=file_sha256(target)
    session.source_profile=path;session.source_hash=file_sha256(path);session.profile=copy.deepcopy(profile)
    result={'path':str(path),'sha256':session.source_hash,'profile_path':str(path),'configuration_path':str(target),
        'source_configuration_path':str(old_configuration),'physical_verified':False,'sdk_calibration_changed':False,'automatically_applied':True}
    session.saved[str(path)]=result
    return result
