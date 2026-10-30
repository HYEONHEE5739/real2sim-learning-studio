"""Local SO101 configuration ownership and USB identity discovery, never activation."""
from pathlib import Path
import copy,math,re,uuid
from ..data.native import file_sha256


def discover():
    # pySerial3.5 comports reports USB identity through OS metadata, without opening a bus.
    # https://pyserial.readthedocs.io/en/latest/tools.html#serial.tools.list_ports.comports
    from serial.tools.list_ports import comports
    serial=[{'path':p.device,'serial':p.serial_number,'vid':p.vid,'pid':p.pid,'description':p.description}for p in comports()]
    cameras=[{'path':str(p),'resolved':str(p.resolve()),'id':p.name}for p in sorted(Path('/dev/v4l/by-id').glob('*-video-index0'))]
    return {'serial':serial,'cameras':cameras}


def resolve_serial(identity,inventory=None):
    if not identity.get('serial'):raise ValueError('Stable USB serial identity required; tty number does not establish role')
    rows=discover()['serial']if inventory is None else inventory
    matches=[p for p in rows if p.get('serial')==identity['serial']and all(identity.get(k)is None or p.get(k)==identity[k]for k in('vid','pid'))]
    if len(matches)!=1:raise ValueError('USB identity missing or not unique (ambiguous); select the actual device')
    return matches[0]['path']


def mapping_coordinates_equal(a,b):
    """Connection port is local metadata; all measured coordinate/motor parameters stay exact."""
    from .calibration import mapper_from_metadata
    mapper_from_metadata(a);mapper_from_metadata(b)
    a=copy.deepcopy(a);b=copy.deepcopy(b)
    for m in(a,b):m.pop('sha256');m['profile']['identity'].pop('port',None)
    return a==b


def save_configuration(workspace,name,recipe):
    from real2sim_builder.files import write
    workspace=Path(workspace).resolve();slug=re.sub('[^a-z0-9]+','-',name.lower()).strip('-')or'so101'
    root=workspace/'devices'/(slug+'-'+uuid.uuid4().hex[:8]);root.mkdir(parents=True)
    write(root/'capture.yaml',recipe);return root/'capture.yaml'


def bind_configuration(project,path,workspace):
    from real2sim_builder.project import Project
    from real2sim_builder.files import read,write
    import os
    project=Project(project);project.require_writable();path=Path(path).resolve();workspace=Path(workspace).resolve()
    if not path.is_relative_to(workspace/'devices')or not path.is_file():raise ValueError('Device configuration must be owned by workspace/devices')
    info=read(project.root/'project.yaml');info['device_configuration']={'path':os.path.relpath(path,project.root),'sha256':file_sha256(path),'automatic_connect':False}
    write(project.root/'project.yaml',info)


def bound_configuration(project,workspace):
    from real2sim_builder.project import Project
    project=Project(project,read_only=True);binding=project.info.get('device_configuration')
    if not binding:return None
    path=(project.root/binding['path']).resolve();workspace=Path(workspace).resolve()
    if not path.is_relative_to(workspace/'devices')or not path.is_file()or file_sha256(path)!=binding['sha256']:raise ValueError('Bound device configuration missing or changed; review and bind again')
    return path


def configure_selected(workspace,name,choices,*,existing=None):
    """Persist explicit device choices; never invent motor/Precision calibration."""
    from real2sim_builder.files import write,read
    if choices.get('robot')not in('so101','cameras'):raise ValueError('Unsupported robot; register its model and SDK before use')
    if not choices.get('side')or not choices.get('wrist')or choices['side']==choices['wrist']:raise ValueError('Choose distinct Side/Wrist cameras')
    limits=choices.get('motion_limits',{})
    if limits and(set(limits)!={'max_command_step_rad','max_follow_error_rad'}or any(type(v)not in(int,float)or not math.isfinite(v)or v<=0 for v in limits.values())):raise ValueError('Both positive finite Teleoperation limits required')
    previous=read(existing)if existing else None;unchanged={}
    if choices['robot']=='so101':
        serials=[]
        for role,key in(('follower','device_profile'),('leader','leader_device_profile')):
            selected=choices.get(role)
            if not selected or not selected.get('serial'):raise ValueError(role+': choose a device with stable USB identity')
            serials.append(selected['serial'])
            if previous and key in previous['inputs']:
                source=(Path(existing).parent/previous['inputs'][key]).resolve();spec=read(source);identity=spec.get('usb_identity',{})
                if spec.get('role')==role and identity.get('serial')==selected['serial']and all(identity.get(k)is None or selected.get(k)==identity[k]for k in('vid','pid')):unchanged[key]=str(source)
        if len(set(serials))!=2:raise ValueError('Leader and Follower must be different USB devices')
    recipe={'schema_version':1,'stage':'scene_capture','inputs':{},'execution':{'device_source':'hardware'},'output':{'directory':str(Path(workspace).resolve()/'capture/new-session')}}
    if len(unchanged)==2 and previous:
        recipe=copy.deepcopy(previous);recipe.pop('engine',None);recipe['inputs'].pop('project',None);recipe['inputs'].pop('candidate',None)
        recipe['stage']='capture_session'if previous['stage']!='scene_capture'else'scene_capture'
        recipe['inputs']={k:str((Path(existing).parent/v).resolve())for k,v in recipe['inputs'].items()}
    if limits:
        if recipe['stage']!='capture_session':raise ValueError('Model/Precision binding is required before configuring Teleoperation')
        recipe['execution'].update(limits)
    path=save_configuration(workspace,name,recipe);root=path.parent
    cameras={n:{'index_or_path':choices[n],'width':640,'height':480,'fps':30}for n in('side','wrist')};write(root/'cameras.json',{'cameras':cameras});recipe['inputs']['camera_config']=str(root/'cameras.json')
    if choices['robot']=='so101':
        for role,key in(('follower','device_profile'),('leader','leader_device_profile')):
            if key in unchanged:recipe['inputs'][key]=unchanged[key];continue
            selected=choices[role];identifier='so101_'+role+'_'+re.sub('[^a-zA-Z0-9_-]','_',selected['serial'])
            calibration=root/'calibration'/role/(identifier+'.json');calibration.parent.mkdir(parents=True)
            spec={'role':role,'usb_identity':{k:selected.get(k)for k in('serial','vid','pid')},'calibration_path':str(calibration),'sdk':{'id':identifier,'port':selected['path'],'use_degrees':True,'calibration_dir':str(calibration.parent)}}
            write(root/(role+'.json'),spec);recipe['inputs'][key]=str(root/(role+'.json'))
    write(path,recipe);return path
