"""Scene material preparation using the existing Builder Project/Evidence contract."""
from pathlib import Path
from real2sim_builder.project import Project
from real2sim_builder.files import read,write,sha
from real2sim_builder.candidate import exclusive


def list_scenes(workspace):
    result=[]
    for path in sorted((Path(workspace)/'scenes').glob('*/project.yaml')):
        project=Project(path.parent,read_only=True)
        result.append({'project':str(project.root),'id':project.info['id'],'name':project.info['name']})
    return result


def create_scene(workspace,name):
    return scene_details(Project.create(Path(workspace)/'scenes',name).root)


def robot_variants(workspace):
    """Discover named and versioned Workspace Rigs; no new database/loader."""
    rows=[];sources=set();workspace=Path(workspace).resolve()
    rigs=workspace/'robot_rigs'
    paths=set(rigs.glob('*/rig.yaml'))|set(rigs.glob('*/v*/rig.yaml'))
    for path in sorted(paths):
        if path.is_symlink()or not path.resolve().is_relative_to(rigs):continue
        record=read(path)
        if record.get('schema')!='real2sim.robot-rig/1':continue
        source=(path.parent/record['source_robot']).resolve()
        if record['source_robot_sha256']not in sources:
            rows.append({'name':'SO-ARM101','rig':None,'path':str(source),'model_sha256':record['source_robot_sha256']})
            sources.add(record['source_robot_sha256'])
        version=path.parent.name if path.parent.parent!=rigs else None
        label=record['name']if version is None or record.get('status')=='FINAL_VISUAL_MODEL'else record['name']+' · '+version+' · '+record['mount_status']
        rows.append({'name':record['name'],'version':version,
            'label':label,
            'rig':str(path.resolve()),'path':str((path.parent/record['model']['path']).resolve()),
            'model_sha256':record['model']['sha256'],'mount_status':record['mount_status'],'calibration_status':record['calibration_status']})
    return rows


def select_robot_rig(path,rig_path):
    """An explicit Scene preparation choice; existing Candidates are unchanged."""
    import os
    from real2sim_builder.evidence import load_robot_rig
    project=Project(path);project.require_writable()
    selected=None
    if rig_path:
        rig_path=Path(rig_path).resolve()
        if not rig_path.is_relative_to(project.workspace/'robot_rigs'):raise ValueError('Select a Workspace-owned Robot Rig')
        load_robot_rig(rig_path)
        selected={'path':os.path.relpath(rig_path,project.root),'sha256':sha(rig_path)}
    with exclusive(project):
        info=project.info
        if selected:info['robot_rig']=selected
        else:info.pop('robot_rig',None)
        write(project.root/'project.yaml',info)
    return scene_details(project.root)


def scene_details(path):
    project=Project(path,read_only=True);evidence=project.evidence;inputs=[]
    for kind,key in [('image','images'),('video','videos'),('document','documents'),('robot','robot_inputs'),('capture','capture_sessions')]:
        for row in evidence.get(key,[]):
            file=project.root/row['path'];status='MISSING'if not file.is_file()else'CHANGED'if row.get('sha256')and sha(file)!=row['sha256']else'REGISTERED'
            inputs.append({'kind':kind,'path':row['path'],'sha256':row.get('sha256'),'status':status,'role':row.get('role'),'name':row.get('original_name')or Path(row.get('source')or row['path']).name})
    from real2sim_builder.evidence import scene_memo
    memo=scene_memo(project)
    ready=False;needs=['Scene/Candidate not created; inputs may be saved independently']
    current=project.root/'working/current_scene.yaml'
    if current.is_file():
        from real2sim_builder.scene import validate
        try:validate(read(current),project.root,complete=True);ready=True;needs=[]
        except(ValueError,FileNotFoundError)as error:needs=[str(error)]
    return {'project':str(project.root),'id':project.info['id'],'name':project.info['name'],'inputs':inputs,'notes':memo['text'],'notes_saved':memo['saved'],'scene_memo':{k:v for k,v in memo.items()if k!='text'},'reconstruction_ready':ready,'needs':needs,'device_configuration':project.info.get('device_configuration'),'execution_packages':project.info.get('execution_packages',[]),
        'robot_variants':robot_variants(project.workspace),'robot_rig':project.info.get('robot_rig')}


def save_inputs(path,files,notes,*,scene_state=None):
    """No input is required. Store context first; geometry import is explicit later."""
    from real2sim_builder.evidence import add_image,add_video,copy_input,save_scene_memo
    project=Project(path);project.require_writable()
    if not isinstance(notes,str):raise ValueError('Scene notes must be text')
    entries=[(Path(p['path']).resolve(),p.get('role','scene_photo'))if isinstance(p,dict)else(Path(p).resolve(),'scene_photo')for p in files]
    files=[file for file,role in entries]
    for file in files:
        if not file.is_file():raise FileNotFoundError(file)
        if file.suffix.lower() in ('.glb','.gltf'):raise ValueError('LEGACY_UNSUPPORTED: GLB/glTF 입력은 제거되었습니다. 실측 치수와 RGB 또는 OBJ/STL을 사용하세요.')
    # A single upload declares one static layout. Later uploads remain separate
    # unless the caller explicitly selects the same layout; Capture is never relabelled.
    from uuid import uuid4
    from real2sim_builder.observations import register_image
    from real2sim_builder.scene import identifier
    state=identifier(scene_state)if scene_state else 'photos_'+uuid4().hex[:12]
    for file,role in entries:
        with exclusive(project):
            suffix=file.suffix.lower()
            if suffix in('.png','.jpg','.jpeg','.webp','.tif','.tiff'):
                digest=sha(file)
                existing=next((i for i in project.evidence['images']if i.get('sha256')==digest and i.get('scene_state_id')and i.get('role')==role),None)
                if existing:
                    if scene_state and existing['scene_state_id']!=scene_state:raise ValueError('Existing RGB belongs to another static layout')
                else:
                    row=register_image(project,file,camera='external_view_'+str(len(project.evidence['images'])+1).zfill(3),camera_type='external',scene_state=state,role=role)
                    evidence=project.evidence
                    next(i for i in evidence['images']if i['id']==row['id'])['physical_camera_id']=None
                    project.write_evidence(evidence)
            elif suffix in('.mp4','.mov','.avi'):
                if role!='scene_photo':raise ValueError('Scene Video belongs in Scene inputs, not Model Reference images')
                add_video(project,file,camera='reference',max_frames=15,role='scene_video',scene_state=state)
            else:
                if suffix in('.urdf','.obj','.usd','.usda','.usdc'):
                    from real2sim_builder.export import copy_native_asset,verify_native_closure
                    stored=copy_native_asset(file,project.root/'input/models');verify_native_closure(project.root,stored.relative_to(project.root).as_posix());relative=stored.relative_to(project.root).as_posix()
                else:relative=copy_input(project,file,'models'if suffix=='.stl'else'metadata')
                evidence=project.evidence;key='robot_inputs'if suffix=='.urdf'else'documents'
                rows=evidence.setdefault(key,[])
                if not any(row['path']==relative for row in rows):rows.append({'path':relative,'sha256':sha(project.root/relative),'source':str(file),'status':'UNVERIFIED_INPUT'})
                project.write_evidence(evidence);project.invalidate()
    save_scene_memo(project,notes)
    return scene_details(project.root)


def source_inputs(path,engine):
    """Resolve a named Project's registered physics Package and Leader settings."""
    from scene_contract.package import load_scene,SceneIdentity
    from .robot.registration import bound_configuration
    project=Project(path,read_only=True);engine_key='isaac'if engine=='isaaclab'else engine
    if engine_key not in('mujoco','isaac'):raise ValueError('MuJoCo 또는 Isaac을 선택하세요.')
    records=project.info.get('execution_packages',[])
    if not records:raise ValueError('선택한 Scene에 이 엔진의 실행 Package가 등록되지 않았습니다.')
    # Registration order is the Project's revision order; never fall back from a
    # broken newest revision to an older Package without the user's knowledge.
    record=records[-1];scene=(project.root/record['path']/'scene.json').resolve()
    settings_path=record.get('engine_profiles',{}).get(engine_key,{}).get('physics')
    if not settings_path:
        needs=record.get('execution_readiness',{}).get(engine_key,{}).get('needs',[])
        raise ValueError('Native Physics 실행 준비가 부족합니다: '+'; '.join(needs))
    settings=(project.root/settings_path).resolve()
    if not scene.is_relative_to(project.root)or not settings.is_relative_to(project.root):raise ValueError('Scene 실행 자산은 선택 Project 내부에 있어야 합니다.')
    package=load_scene(scene,expected=SceneIdentity(record['scene_id'],record['revision'],record['manifest_sha256']))
    if engine_key not in package.scene['engines']:raise ValueError('Scene Package가 선택 엔진을 지원하지 않습니다.')
    config=read(settings)
    if config.get('render_type')!='native'or config.get('simulation_mode')!='physics':raise ValueError('Source에는 Native Physics 설정이 필요합니다. Native Pose는 영상 비교용입니다.')
    workspace=project.root.parent.parent;configuration=bound_configuration(project.root,workspace)
    if configuration is None:raise ValueError('이 Scene에 장치 설정이 없습니다. Scene Prepare에서 Leader 장치 구성을 저장하세요.')
    device=read(configuration).get('inputs',{}).get('leader_device_profile')
    if not device:raise ValueError('이 Scene의 장치 설정에 Leader가 없습니다.')
    leader=(configuration.parent/device).resolve()
    if read(leader).get('role')!='leader':raise ValueError('Source는 Leader만 읽으며 실제 Follower를 제어하지 않습니다.')
    return {'name':project.info['name'],'project':str(project.root),'configuration':str(configuration),
        'inputs':{'scene':str(scene),'engine_config':str(settings),'device_profile':str(leader)}}
