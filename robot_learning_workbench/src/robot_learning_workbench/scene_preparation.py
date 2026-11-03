"""Scene material preparation using the existing Builder Project/Evidence contract."""
from pathlib import Path
import tempfile
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


def scene_details(path):
    project=Project(path,read_only=True);evidence=project.evidence;inputs=[]
    for kind,key in [('image','images'),('video','videos'),('scan','scans'),('document','documents'),('robot','robot_inputs'),('capture','capture_sessions')]:
        for row in evidence.get(key,[]):
            file=project.root/row['path'];status='MISSING'if not file.is_file()else'CHANGED'if row.get('sha256')and sha(file)!=row['sha256']else'REGISTERED'
            inputs.append({'kind':kind,'path':row['path'],'sha256':row.get('sha256'),'status':status})
    notes=''
    if evidence.get('briefs'):
        row=evidence['briefs'][-1];file=project.root/row['path']
        if not file.is_file()or sha(file)!=row['sha256']:raise ValueError('Scene notes missing or changed')
        notes=file.read_text()
    ready=False;needs=['Scene/Candidate not created; inputs may be saved independently']
    current=project.root/'working/current_scene.yaml'
    if current.is_file():
        from real2sim_builder.scene import validate
        try:validate(read(current),project.root,complete=True);ready=True;needs=[]
        except(ValueError,FileNotFoundError)as error:needs=[str(error)]
    return {'project':str(project.root),'id':project.info['id'],'name':project.info['name'],'inputs':inputs,'notes':notes,'notes_saved':bool(evidence.get('briefs')),'reconstruction_ready':ready,'needs':needs,'device_configuration':project.info.get('device_configuration'),'execution_packages':project.info.get('execution_packages',[])}


def save_inputs(path,files,notes):
    """No input is required. Store context first; geometry import is explicit later."""
    from real2sim_builder.evidence import add_image,add_video,copy_input,add_brief
    from real2sim_builder.scan import import_scan
    project=Project(path);project.require_writable()
    if not isinstance(notes,str):raise ValueError('Scene notes must be text')
    files=[Path(p).resolve()for p in files]
    for file in files:
        if not file.is_file():raise FileNotFoundError(file)
    for file in files:
        if file.suffix.lower()=='.glb':import_scan(project,file);continue
        with exclusive(project):
            suffix=file.suffix.lower()
            if suffix in('.png','.jpg','.jpeg','.webp','.tif','.tiff'):add_image(project,file,camera='reference',context_only=True)
            elif suffix in('.mp4','.mov','.avi'):add_video(project,file,camera='reference')
            else:
                if suffix in('.urdf','.obj'):
                    from real2sim_builder.export import copy_native_asset,verify_native_closure
                    stored=copy_native_asset(file,project.root/'input/models');verify_native_closure(project.root,stored.relative_to(project.root).as_posix());relative=stored.relative_to(project.root).as_posix()
                else:relative=copy_input(project,file,'models'if suffix=='.stl'else'metadata')
                evidence=project.evidence;key='robot_inputs'if suffix=='.urdf'else'documents'
                rows=evidence.setdefault(key,[])
                if not any(row['path']==relative for row in rows):rows.append({'path':relative,'sha256':sha(project.root/relative),'source':str(file),'status':'UNVERIFIED_INPUT'})
                write(project.root/'input/evidence.yaml',evidence);project.invalidate()
    with exclusive(project):
        previous=scene_details(project.root)['notes']
        if previous!=notes or not project.evidence.get('briefs'):
            with tempfile.TemporaryDirectory(dir=project.root/'scratch')as temporary:
                file=Path(temporary)/'scene-notes.txt';file.write_text(notes);add_brief(project,file)
    return scene_details(project.root)


def source_inputs(path,engine):
    """Resolve a named Project's registered physics Package and Leader settings."""
    from scene_contract.package import load_scene,SceneIdentity
    from .robot.registration import bound_configuration
    project=Project(path,read_only=True);engine_key='isaac'if engine=='isaaclab'else engine
    if engine_key not in('mujoco','isaac'):raise ValueError('MuJoCo 또는 Isaac을 선택하세요.')
    records=[row for row in project.info.get('execution_packages',[])if engine_key in row.get('engine_config',{})]
    if not records:raise ValueError('선택한 Scene에 이 엔진의 실행 Package가 등록되지 않았습니다.')
    # Registration order is the Project's revision order; never fall back from a
    # broken newest revision to an older Package without the user's knowledge.
    record=records[-1];scene=(project.root/record['path']/'scene.json').resolve()
    settings=(project.root/record['engine_config'][engine_key]).resolve()
    if not scene.is_relative_to(project.root)or not settings.is_relative_to(project.root):raise ValueError('Scene 실행 자산은 선택 Project 내부에 있어야 합니다.')
    package=load_scene(scene,expected=SceneIdentity(record['scene_id'],record['revision'],record['manifest_sha256']))
    if engine_key not in package.scene['engines']:raise ValueError('Scene Package가 선택 엔진을 지원하지 않습니다.')
    config=read(settings)
    if config.get('render_type')=='authored':raise ValueError('이 Scene에는 비교용 렌더 설정만 있습니다. Builder에서 Source용 물리 실행 자산과 설정을 등록하세요.')
    workspace=project.root.parent.parent;configuration=bound_configuration(project.root,workspace)
    if configuration is None:raise ValueError('이 Scene에 장치 설정이 없습니다. Scene Prepare에서 Leader 장치 구성을 저장하세요.')
    device=read(configuration).get('inputs',{}).get('leader_device_profile')
    if not device:raise ValueError('이 Scene의 장치 설정에 Leader가 없습니다.')
    leader=(configuration.parent/device).resolve()
    if read(leader).get('role')!='leader':raise ValueError('Source는 Leader만 읽으며 실제 Follower를 제어하지 않습니다.')
    return {'name':project.info['name'],'project':str(project.root),'configuration':str(configuration),
        'inputs':{'scene':str(scene),'engine_config':str(settings),'device_profile':str(leader)}}
