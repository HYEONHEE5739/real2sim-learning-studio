import copy,json
from pathlib import Path
import numpy as np
import pytest
from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import write,sha
from real2sim_builder.evidence import import_robot,copy_input
from real2sim_builder.scene import empty,value
from robot_learning_workbench.robot.calibration import JOINTS


def candidate_fixture(tmp_path):
    project=Project.create(tmp_path/'projects','Static candidate fixture');model=tmp_path/'robot.urdf'
    links=['base']+['link'+str(i)for i in range(6)]
    body=''.join('<link name="'+n+'"><visual><geometry><box size="0.025 0.025 0.04"/></geometry></visual></link>'for n in links)
    for i,n in enumerate(JOINTS):body+='<joint name="'+n+'" type="revolute"><parent link="'+links[i]+'"/><child link="'+links[i+1]+'"/><origin xyz="0 0 0.04" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-2" upper="2" effort="10" velocity="1"/></joint>'
    model.write_text('<robot name="fixture">'+body+'</robot>');mapping={'joint_order':list(JOINTS),'output':'urdf_joint_radian','fixture':True}
    import_robot(project,model,joints=dict.fromkeys(JOINTS,0));scene=project.scene
    from real2sim_builder.calibration.geometry import link_transforms
    fk=link_transforms(model,dict.fromkeys(JOINTS,0))
    for obj in scene['objects']:
        if obj.get('link'):obj['link_local_pose']=(np.linalg.inv(fk[obj['link']])@np.asarray(obj['pose']['value'])).tolist()
    scene['robot_model']={'format':'urdf','path':copy_input(project,model,'models'),'model_sha256':sha(model),'joint_names':list(JOINTS),'mapping':mapping}
    t=np.eye(4);t[:3,:3]=[[1,0,0],[0,-1,0],[0,0,-1]];t[:3,3]=[0,0,.8]
    scene['cameras']=[dict(id=n,frame='world',pose=value(t.tolist(),'estimated'),K=value([[500.,0,320.],[0,500.,240.],[0,0,1]],'estimated'),resolution=[640,480],distortion=value([0.]*5,'estimated'))for n in('side','wrist')]
    project.save_scene(scene);candidate=Candidate.create(project,'candidate_one');return project,candidate,model,mapping
