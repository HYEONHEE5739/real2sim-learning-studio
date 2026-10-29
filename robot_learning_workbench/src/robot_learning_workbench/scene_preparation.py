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
    return {'project':str(project.root),'id':project.info['id'],'name':project.info['name'],'inputs':inputs,'notes':notes,'reconstruction_ready':ready,'needs':needs,'device_configuration':project.info.get('device_configuration'),'execution_packages':project.info.get('execution_packages',[])}


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
                relative=copy_input(project,file,'models'if suffix in('.urdf','.stl','.obj')else'metadata');evidence=project.evidence;key='robot_inputs'if suffix=='.urdf'else'documents'
                rows=evidence.setdefault(key,[])
                if not any(row['path']==relative for row in rows):rows.append({'path':relative,'sha256':sha(project.root/relative),'source':str(file),'status':'UNVERIFIED_INPUT'})
                write(project.root/'input/evidence.yaml',evidence);project.invalidate()
    with exclusive(project):
        previous=scene_details(project.root)['notes']
        if previous!=notes:
            with tempfile.TemporaryDirectory(dir=project.root/'scratch')as temporary:
                file=Path(temporary)/'scene-notes.txt';file.write_text(notes);add_brief(project,file)
    return scene_details(project.root)
