"""Stage10 registration producers must satisfy the real render-cloud consumer.

Numerical/render refinement alone is replaced after real cloud_inputs checks;
retained calibrated Side/Wrist registration and on-disk RGB/NPZ are real.
"""
import copy

import numpy as np
import pytest
from PIL import Image

from real2sim_builder import observations,reconstruction_stages as stages
from real2sim_builder.calibration import hybrid
from real2sim_builder.files import sha,write
from real2sim_builder.scene import camera_calibration_signature
from real2sim_builder.stage_artifacts import StageNeeds
from test_builder_export import legacy_scene
from test_direct_fit_observation_refresh import _fixture


def _sensor_context(tmp_path):
    project,candidate,wrist,raw,optical=_fixture(tmp_path,'mount',protected=True)
    scene=candidate.scene
    scene['cameras'].append(copy.deepcopy(legacy_scene()['cameras'][0]))
    evidence=project.evidence
    wrist_row=evidence['images'][0]
    wrist_row.update(capture_manifest='input/synthetic-capture.yaml',role='capture')
    write(project.root/'input/synthetic-capture.yaml',{'scope':'synthetic pre-registered sensor metadata'})
    write(project.root/'input/evidence.yaml',evidence)
    wrist=copy.deepcopy(wrist_row)
    signature=observations.source_record_digest(wrist)
    scene['view_registrations'][wrist['id']]['image_record_sha256']=signature
    scene['reconstruction_observations']['clouds'][0]['dependencies']['image_record_sha256']=signature
    joint={key:wrist[key]for key in('q_measured','joint_names','joint_units','mapping_sha256','robot_model_sha256','image_timestamp_ns','joint_timestamp_ns')}
    for label,color in [('photo',(17,36,91)),('side-capture',(31,65,122))]:
        path=tmp_path/(label+'.png');Image.new('RGB',(160,120),color).save(path)
        row=observations.register_image(project,path,camera='side',camera_type='side',scene_state='layout',joint_record=joint)
        if label=='photo':photo=row
        else:
            evidence=project.evidence
            next(item for item in evidence['images']if item['id']==row['id']).update(capture_manifest='input/synthetic-capture.yaml',role='capture')
            write(project.root/'input/evidence.yaml',evidence)
    original=candidate.root/'original_points.npz'
    pixels=np.array([[45.,35.],[65.,35.],[65.,55.],[45.,55.]])
    points=np.c_[pixels/100.,np.ones(4)]
    np.savez_compressed(original,camera_points=points,uv_processed=pixels)
    mask=candidate.root/'photo-mask.png';Image.new('L',(160,120),255).save(mask)
    previous={2:{'frames':[{'id':photo['id'],'role':'scene_photo','path':str(project.root/photo['path'])}],
        'original_to_processed':[np.eye(3).tolist()]},
        4:{'camera_to_support':np.eye(4).tolist()},
        6:{'objects':[{'id':'block','source_frame_id':photo['id'],'original_points':str(original),'mask':str(mask)}]}}
    anchor={'source':'measured','evidence':['synthetic independently specified square corners'],
        'observed_corners_camera_m':[[0,0,1],[.1,0,1],[.1,.1,1],[0,.1,1]],'dimensions_xy_m':[.1,.1]}
    registration={'support_to_world':np.eye(4).tolist(),'scale':1.,'provenance':'calibrated','evidence':['synthetic coordinate registration']}
    config={'scene_state_id':'layout','metric_anchors':[anchor],'world_registration':registration,
        'sensor_registration':{'metric_review':{'accepted':True,'anchors_sha256':stages.stage_digest([anchor]),
            'evidence':['synthetic explicit review']},'joint':{'enabled':False},'render_refinement':{'enabled':True}}}
    candidate.save(scene)
    return project,candidate,previous,config


def _render_consumers(monkeypatch):
    checked=[]
    def inspect(project,scene):
        rows=hybrid.cloud_inputs(project,scene)
        for row in rows:
            assert row['units']=='m'and row['frame']=='world'
            assert row['split']in('train','validation')and row['group_id']
            assert sha(project.root/row['mask'])==row['mask_sha256']
            with np.load(project.root/row['path'],allow_pickle=False)as a:
                assert a['points_world_m'].ndim==2 and a['points_world_m'].shape[1]==3
                if row.get('render_only'):assert len(a['points_world_m'])==0
        checked.append(copy.deepcopy(rows))
    def fit(project,scene,folder,options):
        inspect(project,scene)
        return scene,{'status':'NOT_IMPROVED','physical_verified':False,'scope':'test numerical boundary'}
    def compare(project,scene,folder,options):
        inspect(project,scene);return {'images':[],'physical_verified':False}
    monkeypatch.setattr(hybrid,'fit_scene',fit);monkeypatch.setattr(hybrid,'alignment_metrics',compare)
    return checked


def test_stage10_sensor_registration_reaches_real_cloud_contract_before_render(tmp_path,monkeypatch):
    project,candidate,previous,config=_sensor_context(tmp_path)
    scene=candidate.scene;original=copy.deepcopy(scene['reconstruction_observations']['clouds'])
    source={path:sha(path)for path in[project.root/row['path']for row in original]}
    checked=_render_consumers(monkeypatch)
    folder=candidate.root/'stage10';folder.mkdir()
    result,report=stages.register_stage_sensors(candidate,config,scene,previous,folder)
    assert report['status']=='REGISTERED_ESTIMATED'and len(checked)==2
    retained={row['path']:row for row in result['reconstruction_observations']['clouds']}
    for row in original:assert retained[row['path']]==row
    assert all(sha(path)==before for path,before in source.items())
    assert len(observations.registered_images(project,'layout',scene=result)[0])>=2
    # No sensor depth inference ran. Any new sensor-only row must remain RGB
    # evidence with zero points, not fabricated metric geometry.
    sensor_ids={image['id']for image in project.evidence['images']if image.get('capture_manifest')}
    for row in result['reconstruction_observations']['clouds']:
        if row['image_id']in sensor_ids and row['path']not in{item['path']for item in original}:
            assert row.get('render_only')is True


def test_stage_sensor_correspondences_do_not_replace_existing_typed_clouds(tmp_path):
    project,candidate,previous,config=_sensor_context(tmp_path)
    before=candidate.scene;old=copy.deepcopy(before['reconstruction_observations']['clouds'])
    folder=candidate.root/'cloud-producer';folder.mkdir()
    result=stages.stage_sensor_clouds(candidate,before,previous,folder,config['world_registration'])
    current={row['path']:row for row in result['reconstruction_observations']['clouds']}
    assert all(row['path']in current and current[row['path']]==row for row in old)
    assert candidate.scene==before


@pytest.mark.parametrize('case',['disabled','no_sensor','metric_insufficient'])
def test_optional_sensor_refinement_gates_preserve_existing_scene_and_clouds(tmp_path,monkeypatch,case):
    project,candidate,previous,config=_sensor_context(tmp_path)
    before=candidate.scene;candidate_sha=sha(candidate.root/'candidate_scene.yaml')
    if case=='disabled':config['sensor_registration']['enabled']=False
    elif case=='no_sensor':
        evidence=project.evidence
        for image in evidence['images']:image.pop('capture_manifest',None)
        write(project.root/'input/evidence.yaml',evidence)
    else:config['metric_anchors']=[]
    monkeypatch.setattr(hybrid,'fit_scene',lambda *args:pytest.fail('Refinement must not start without its evidence gate'))
    folder=candidate.root/'gated';folder.mkdir()
    if case=='metric_insufficient':
        with pytest.raises(StageNeeds)as error:stages.register_stage_sensors(candidate,config,before,previous,folder)
        assert error.value.status=='NEEDS_MORE_DATA'
    else:
        result,report=stages.register_stage_sensors(candidate,config,before,previous,folder)
        assert result==before and report['status']in('NOT_REQUESTED','NOT_AVAILABLE')
    assert sha(candidate.root/'candidate_scene.yaml')==candidate_sha
