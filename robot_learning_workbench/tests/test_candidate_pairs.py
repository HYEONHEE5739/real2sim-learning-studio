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


def test_candidate_pose_is_measured_q_and_identity_is_frozen(tmp_path):
    from robot_learning_workbench.robot.real_sim import CandidateView
    p,c,m,mapping=candidate_fixture(tmp_path);view=CandidateView(p.root,c.root/'candidate_scene.yaml',m,mapping)
    original=copy.deepcopy(c.scene);q=np.array([.2,.1,0,0,0,0]);posed=view.pose(q)
    assert posed['frames']!=original['frames']and c.scene==original
    with pytest.raises(ValueError,match='joint|finite'):view.pose(np.zeros(5))
    changed=c.scene;changed['lights']['ambient']=value([.2]*3,'estimated');c.save(changed)
    with pytest.raises(ValueError,match='changed'):view.pose(q)


def test_real_mujoco_candidate_render_is_static_and_six_joint_pose_bound(tmp_path):
    from robot_learning_workbench.robot.real_sim import CandidateView,CandidateRenderer
    p,c,m,mapping=candidate_fixture(tmp_path);view=CandidateView(p.root,c.root/'candidate_scene.yaml',m,mapping)
    with CandidateRenderer(view,'mujoco',tmp_path/'render')as renderer:
        result=renderer.render([.2,.1,0,0,0,0])
    assert result['physics_steps']==0 and result['state_application']=='builder_measured_joint_fk'
    assert result['candidate_identity']==view.identity
    assert all(image.shape==(480,640,3)and image.dtype==np.uint8 for image in result['images'].values())
    np.testing.assert_array_equal(result['measured_q_rad'],[.2,.1,0,0,0,0])


def test_candidate_outside_project_or_wrong_model_mapping_is_not_rendered(tmp_path):
    from robot_learning_workbench.robot.real_sim import CandidateView
    p,c,m,mapping=candidate_fixture(tmp_path)
    with pytest.raises(ValueError,match='mapping'):CandidateView(p.root,c.root/'candidate_scene.yaml',m,{})
    wrong=tmp_path/'other.urdf';wrong.write_text('<robot/>')
    with pytest.raises(ValueError,match='model'):CandidateView(p.root,c.root/'candidate_scene.yaml',wrong,mapping)


def test_owned_renderer_process_uses_frozen_q_for_capture_and_closes(tmp_path):
    from types import SimpleNamespace as NS
    from robot_learning_workbench.robot.real_sim import RenderProcess
    import time
    p,c,m,mapping=candidate_fixture(tmp_path);out=tmp_path/'worker';out.mkdir()
    plan=NS(output_path=out,engine='mujoco',resolved_inputs={'project':{'root':str(p.root)},'candidate':{'path':str(c.root/'candidate_scene.yaml')},'robot_model':{'path':str(m)}})
    worker=RenderProcess(plan,mapping);q=[.1,0,0,0,0,0]
    try:
        worker.observe(q);deadline=time.monotonic()+20
        while worker.last_live is None:
            worker.poll();time.sleep(.02);assert time.monotonic()<deadline
        worker.capture({'id':'snapshot_test','sample':{'q_measured':q}})
        while True:
            result=worker.poll()
            if result is not None:break
            time.sleep(.02);assert time.monotonic()<deadline
        assert result['measured_q_rad']==q and result['physics_steps']==0
        assert all(rgb.shape==(480,640,3)for rgb in result['images'].values())
    finally:worker.close()
    assert worker.process.poll()is not None


def test_candidate_fk_urdf_bytes_must_match_measured_model(tmp_path):
    from robot_learning_workbench.robot.real_sim import CandidateView
    p,c,m,mapping=candidate_fixture(tmp_path);candidate_model=p.root/c.scene['robot_model']['path'];candidate_model.write_text(candidate_model.read_text().replace('0 0 0.04','0 0 0.05'))
    with pytest.raises(ValueError,match='model|URDF'):CandidateView(p.root,c.root/'candidate_scene.yaml',m,mapping)


def test_immutable_asset_hardlink_sharing_does_not_invalidate_candidate(tmp_path):
    import os
    from robot_learning_workbench.robot.real_sim import CandidateView
    p,c,m,mapping=candidate_fixture(tmp_path);view=CandidateView(p.root,c.root/'candidate_scene.yaml',m,mapping)
    os.link(m,tmp_path/'shared.urdf');assert view.pose([0.]*6)


def test_rerender_uses_existing_builder_landmark_and_object_mask_metrics(tmp_path):
    from robot_learning_workbench.robot.real_sim import CandidateView,CandidateRenderer
    from robot_learning_workbench.robot.capture import save_session
    from real2sim_builder.validation import compare
    from real2sim_builder.calibration.camera import project_point
    from real2sim_builder.rendering import Renderer
    from PIL import Image
    p,c,m,mapping=candidate_fixture(tmp_path);view=CandidateView(p.root,c.root/'candidate_scene.yaml',m,mapping);q=[0.]*6
    source=p.root/'input/captures/metric_fixture';source.parent.mkdir(parents=True,exist_ok=True);save_session(source,model=m,mapping=mapping,samples=[{'id':'sample1','timestamp_ns':100,'q_measured':q,'command_applied':False}],images=[{n:np.full((480,640,3),80,np.uint8)for n in('side','wrist')}],metadata={'project_id':p.info['id']})
    object_id=c.scene['objects'][-1]['id'];observation={'id':'metric_observation','camera':'side','path':str(next(source.glob('images/*side.png')).relative_to(p.root)),'split':'train','q_measured':q}
    evidence=p.evidence;evidence['images'].append(observation);point={'observation':observation['id'],'object':object_id,'point_fraction':[0,0,0],'uv':[0,0],'source':'synthetic_fixture'}
    point['uv']=project_point(c.scene,c.scene['cameras'][0],point)[0].tolist();evidence['landmarks'].append(point)
    with Renderer(c.scene,p.root,tmp_path/'mask','software-egl')as r:mask=r.mask('side',object_id)
    assert mask.any();mask_file=p.root/'input/fixture-mask.png';Image.fromarray(mask.astype(np.uint8)*255).save(mask_file);evidence['masks'].append({'image':observation['path'],'object':object_id,'path':str(mask_file.relative_to(p.root))});write(p.root/'input/evidence.yaml',evidence)
    with CandidateRenderer(view,'mujoco',tmp_path/'render')as renderer:result=renderer.render(q,source_capture=source)
    row=next(r for r in result['geometry']['side']if r['object']==object_id)
    assert row['landmark_rmse_px']==pytest.approx(0)and row['iou']==1 and row['evidence_status']=='EVALUATED_PROVIDED_EVIDENCE'


def test_candidate_never_silently_applies_historical_runtime_joint_offsets(tmp_path):
    from robot_learning_workbench.robot.real_sim import CandidateView
    p,c,m,mapping=candidate_fixture(tmp_path);s=c.scene;s['robot_model']['simulation_joint_offsets_rad']={'value':[.01]*6,'provenance':'estimated','evidence':['retired workflow']};write(c.root/'candidate_scene.yaml',s)
    with pytest.raises(ValueError,match='historical|offset'):CandidateView(p.root,c.root/'candidate_scene.yaml',m,mapping)
