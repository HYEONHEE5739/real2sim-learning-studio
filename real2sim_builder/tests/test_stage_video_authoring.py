import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from real2sim_builder.files import read,sha
from real2sim_builder.project import Project
from real2sim_builder.evidence import add_video,save_scene_memo
from real2sim_builder.observations import register_image
from real2sim_builder.automation import _run_stage_pipeline
from test_stage_pose import PoseModels,fake_codex_mesh
from test_modeling_handoff import semantic_reply
from test_scene_memo_contract import fake_cli


@pytest.mark.parametrize('video,capture',[(False,False),(True,False),(False,True),(True,True)])
def test_static_inputs_and_memo_reach_stage7_actual_semantic_schema(tmp_path,monkeypatch,video,capture):
    p=Project.create(tmp_path/'projects','Video authoring');memo='Synthetic single red block, keep reference appearance.'
    save_scene_memo(p,memo)
    image=tmp_path/'image.png';rgb=np.full((32,32,3),100,np.uint8);rgb[12:20,12:20]=[220,20,20];Image.fromarray(rgb).save(image)
    if video:
        v=tmp_path/'synthetic.mp4';v.write_bytes(b'synthetic video provider fixture')
        add_video(p,v,camera='phone',role='scene_video',scene_state='layout')
    else:
        for i in range(4):register_image(p,image,camera='photo_'+str(i),camera_type='external',scene_state='layout')
    ref=register_image(p,image,camera='model',camera_type='external',scene_state='layout',role='model_reference')
    if capture:
        register_image(p,image,camera='side_sensor',camera_type='side',scene_state='layout')
        import hashlib
        joint={'q_measured':[.1,-.2],'joint_names':['joint_a','joint_b'],'joint_units':['rad']*2,
            'mapping_sha256':hashlib.sha256(b'synthetic mapping').hexdigest(),'robot_model_sha256':hashlib.sha256(b'synthetic robot').hexdigest(),
            'image_timestamp_ns':1000000,'joint_timestamp_ns':1000000}
        register_image(p,image,camera='wrist_sensor',camera_type='wrist',scene_state='layout',joint_record=joint)
    before=sha(p.root/'input/evidence.yaml')
    class Models(PoseModels):
        def __call__(self,op,req,folder):
            if op=='vlm'and req.get('task')=='scene_instances'and not self.identifications:
                response=super().__call__(op,req,folder)
                # This fixture specifically exercises Stage7's semantic fallback.
                # Parent PoseModels now supplies reusable Stage5 analysis, covered
                # by test_stage_pose/test_codex_vlm; do not skip that fallback here.
                response['answer'].pop('scene_analysis',None)
                return response
            if op=='video':
                folder.mkdir(parents=True,exist_ok=True);frames=[]
                for i in range(4):
                    path=folder/('frame_'+str(i)+'.png');Image.open(image).save(path)
                    frames.append({'id':'video_frame_'+str(i),'path':str(path),'sha256':sha(path),'resolution':[32,32],'frame_index':i,'timestamp':i/30})
                return {'frames':frames}
            return super().__call__(op,req,folder)
    from real2sim_builder.authoring import run_codex_modeling as original
    seen=[]
    def codex(c,**kw):
        from real2sim_builder.authoring import run_codex_modeling
        task=read(c.root/'modeling/tasks.json');assert task['scene_memo']['text']==memo
        views=[r for r in task['source_images']if not r['observation']['context_only']]
        assert len(views)==4 and all(r['observation']['camera_type']=='external'for r in views)
        assert ref['id']in{r['image_id']for r in task['source_images']}
        if capture:
            wrist=next(r for r in task['source_images']if r['observation']['camera_type']=='wrist')
            assert wrist['observation']['context_only']and wrist['observation']['q_measured']==[.1,-.2]
        if task['status']=='WAITING_FOR_CODEX_ANALYSIS':
            selected=views[0]['image_id'];obj={'id':'block','prompt':'red block','role':'manipulable_object','category':'block','modeling_notes':'synthetic',
                'representative_view':{'image_id':selected,'evidence':'synthetic visible block'},
                'observations':[{'image_id':selected,'box_xyxy':[12,12,20,20],'points':[],'evidence':'synthetic visible block'}],
                'model_references':[{'image_id':ref['id'],'status':'LINKED','evidence':'synthetic explicit reference'}]}
            answer={'scene_memo_sha256':task['scene_memo']['sha256'],'objects':[{**obj,'geometry':None}],'task':None,'needs':[]};cli=tmp_path/'codex';fake_cli(cli,memo,json.dumps(answer));seen.append('schema')
            return original(c,executable=cli,timeout_s=20)
        seen.append('mesh')
        # This is Stage7 analysis, not the parent's retained Stage5 response.
        # Authenticate that actual fallback answer before mocking Mesh creation.
        configuration=read(c.root/'reconstruction-config.yaml');analysis=configuration['scene_analysis']
        assert analysis['memo_sha256']==task['scene_memo']['sha256']
        assert sha(p.root/analysis['path'])==analysis['sha256']
        assert configuration['objects']['block']['model_references'][0]['image_id']==ref['id']
        assert task['status']=='WAITING_FOR_CODEX'and task['groups']['block']['references']
        c.edit([{'op':'add_object','id':'block','role':'manipulable_object','dimensions':[.1]*3,
            'visual':{'type':'box'},'collision':{'type':'box'},'unknown_pose':True}])
        return {'status':'REGISTERED_UNVALIDATED'}
    monkeypatch.setattr('real2sim_builder.authoring.run_codex_modeling',codex)
    cfg={'scene_state_id':'layout','execute_modeling':True,'support':{'frame_selection':{'mode':'heuristic','min_component_px':4}},'image_preparation':{'size':32}}
    result=_run_stage_pipeline(p,candidate='test',config=cfg,worker=Models(),through_stage=7)
    assert result['status']=='STAGES_COMPLETE'and seen==['schema','mesh']
    assert sha(p.root/'input/evidence.yaml')==before


def test_actual_ffmpeg_synthetic_video_pts_and_stride(tmp_path):
    import subprocess
    from real2sim_builder.stage_workers import video
    path=tmp_path/'input.mp4';folder=tmp_path/'frames';folder.mkdir()
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=64x48:r=4:d=1','-c:v','mpeg4',str(path)],check=True)
    result=video({'video':str(path),'source_sha256':sha(path),'candidates':2,'output':str(folder)})
    assert result['decoded_frame_count']==4
    assert [f['frame_index']for f in result['frames']]==[0,2]
    assert [f['timestamp']for f in result['frames']]==[0.,.5]
    assert all(f['resolution']==[64,48]and sha(f['path'])==f['sha256']for f in result['frames'])
