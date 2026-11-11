import numpy as np
import pytest
from pathlib import Path
from PIL import Image
from real2sim_builder.files import read,sha
from test_stage_pipeline import synthetic_project
from test_stage_decomposition import DecompositionModels


class PoseModels(DecompositionModels):
    def __call__(self,operation,request,folder):
        if operation=='vlm'and request.get('task')=='scene_instances'and not self.identifications:
            answer=super().__call__(operation,request,folder)
            answer['answer'].update(memo_consistent=True,uncertain=False,evidence=['synthetic observed block'],
                scene_analysis={'scene_memo_sha256':request['context']['memo']['sha256'],
                    'objects':[{'id':'block','prompt':'red block','role':'manipulable_object','category':'block',
                        'modeling_notes':'observed red block','observations':[],'representative_view':None,
                        'geometry':None,'support_relation':None,'model_references':[],'robot_attachment':None}],
                    'capture_layouts':[],'task':None,'needs':[]})
            return answer
        if operation=='canonicalize':
            self.calls.append(operation);return {'rotation':np.eye(3).tolist(),'front':{'status':'ambiguous','meaningful_front':'NOT_VERIFIED'}}
        if operation=='cpd':
            self.calls.append(operation);folder.mkdir(parents=True,exist_ok=True)
            assert Path(request['mesh']).suffix=='.obj'
            assert np.load(request['points']).shape[1]==3
            return {'rotation':np.eye(3).tolist(),'translation':[0,0,.9],
                    'scale':1.,'status':'UNVERIFIED','rmse_m':.001}
        return super().__call__(operation,request,folder)


def fake_codex_mesh(candidate,**kwargs):
    """Mock only the expensive Codex/Blender result; real native adapter follows."""
    assert not kwargs.get('compose_scene')
    task=read(candidate.root/'modeling/tasks.json')
    assert task['groups']['block']['references']
    assert task.get('stage_scene_analysis') and task['status']=='WAITING_FOR_CODEX'
    candidate.edit([{'op':'add_object','id':'block','role':'manipulable_object',
        'dimensions':[.1]*3,'visual':{'type':'box'},'collision':{'type':'box'},'unknown_pose':True}])
    return {'status':'REGISTERED_UNVALIDATED'}


def test_actual_stage7_handoff_native_mesh_and_stage8_contract(tmp_path,monkeypatch):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);worker=PoseModels()
    monkeypatch.setattr('real2sim_builder.authoring.run_codex_modeling',fake_codex_mesh)
    config={'scene_state_id':'layout','execute_modeling':True,'support':{'frame_selection':{'mode':'heuristic','min_component_px':4}},'image_preparation':{'size':32}}
    r=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=8)
    assert r['status']=='STAGES_COMPLETE'
    a=read(r['stages']['7']['artifact'])['output_manifest']['data']
    assert a['modeling_calls']==1 and a['world_pose_authored_by_codex']is False
    assert Path(a['objects'][0]['mesh']).is_file()
    b=read(r['stages']['8']['artifact'])['output_manifest']['data']
    assert b['objects'][0]['status']=='UNVERIFIED'and b['accuracy']=='NOT_VERIFIED'


def test_protected_scale_is_rejected_even_if_a_worker_returns_it(tmp_path):
    from real2sim_builder.reconstruction_stages import poses
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    p=Project.create(tmp_path/'projects','protected');c=Candidate.create(p,'test')
    obj={'id':'block','mesh':'native.obj','camera_points':'points.npy','scale_protected':True}
    def malicious(*args):return {'rotation':np.eye(3).tolist(),'translation':[0,0,1],'scale':1.2}
    with pytest.raises(ValueError,match='protected measured'):
        poses(c,{}, {7:{'objects':[obj]}},tmp_path,malicious)
