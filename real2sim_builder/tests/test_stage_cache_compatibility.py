"""Pinned Stage1/2 compatibility never re-labels or edits original Artifacts."""
import copy
from pathlib import Path

import pytest

from real2sim_builder import stage_artifacts as stages


def _source_map(root):
    from real2sim_builder.files import sha
    return {str(p.relative_to(root)):sha(p)for p in root.rglob('*.py')}


def _case(tmp_path,stage_id=2):
    root=Path(stages.__file__).parent
    old={'kind':'real','operations':{('video'if stage_id==1 else'da3'):{
        'kind':'real','operation':'video'if stage_id==1 else'da3',
        'worker_sha256':stages._STAGE12_BASELINE_SOURCES['stage_workers.py'],
        'settings':{'model':'existing-fixed-snapshot','python':'existing-python'},
        'files':{'model.safetensors':'model-sha'},'precision':'existing-mixed-policy'}},
        'stage_implementation_sha256':dict(stages._STAGE12_BASELINE_SOURCES)}
    current=copy.deepcopy(old);current['stage_implementation_sha256']=_source_map(root)
    current['operations'][next(iter(current['operations']))]['worker_sha256']=current['stage_implementation_sha256']['stage_workers.py']
    inputs=stages.manifest([],{'previous_stage':'fixed-upstream-sha'})
    config={'depth':{'process_res':336},'schema':'simfoundry-stage/1'}if stage_id==2 else{'schema':'simfoundry-stage/1'}
    output=tmp_path/'prediction.npz';output.write_bytes(b'closed model output')
    artifact=stages.StageArtifact.create(stage_id,'COMPLETE',inputs,stages.manifest([output],{'depth':'saved'}),
        runtime_identity=old,config=config)
    artifact.validate(tmp_path)
    key=stages.cache_key(stage_id,inputs,config,old)
    return artifact,inputs,config,current,key


def _compatible(case,stage_id=2):
    artifact,inputs,config,current,key=case
    return stages.audited_stage12_compatibility(stage_id,artifact,inputs=inputs,config=config,current_runtime=current,saved_key=key)


@pytest.mark.parametrize('stage_id',[1,2])
def test_pinned_real_stage12_reuse_keeps_artifact_provenance_and_bytes(tmp_path,stage_id):
    case=_case(tmp_path,stage_id);artifact=case[0]
    original=copy.deepcopy(artifact.to_dict());data=(tmp_path/'prediction.npz').read_bytes()
    result=_compatible(case,stage_id)
    assert result and result['kind']=='audited-code-compatibility'
    assert result['baseline_commit']=='8e02b1ae023a856694a40b947881f76b66410624'
    assert result['stage_id']==stage_id
    assert artifact.to_dict()==original
    assert (tmp_path/'prediction.npz').read_bytes()==data


@pytest.mark.parametrize('change',['input','config','key','model','precision','interpreter','model_bytes'])
def test_changed_input_config_or_model_runtime_cannot_use_old_stage(tmp_path,change):
    case=list(_case(tmp_path));artifact,inputs,config,current,key=case
    if change=='input':inputs['data']['previous_stage']='different-sha'
    elif change=='config':config['depth']['process_res']=448
    elif change=='key':case[4]='different-old-cache-key'
    elif change=='model':current['operations']['da3']['settings']['model']='other-model'
    elif change=='precision':current['operations']['da3']['precision']='bf16-everything'
    elif change=='interpreter':current['operations']['da3']['settings']['python']='other-python'
    elif change=='model_bytes':current['operations']['da3']['files']['model.safetensors']='changed'
    assert _compatible(case)is None


@pytest.mark.parametrize('change',['failed','mock','stage3','unknown_baseline','worker_hash','extra_file'])
def test_noncomplete_mock_later_stage_or_untrusted_code_cannot_opt_in(tmp_path,change):
    case=list(_case(tmp_path));artifact,inputs,config,current,key=case;stage_id=2
    if change=='failed':artifact.status='FAILED'
    elif change=='mock':artifact.provenance['execution']='mock'
    elif change=='stage3':stage_id=3
    elif change=='unknown_baseline':
        artifact.runtime_identity['stage_implementation_sha256']['authoring.py']='untrusted-old-code'
        case[4]=stages.cache_key(2,inputs,config,artifact.runtime_identity)
    elif change=='worker_hash':current['operations']['da3']['worker_sha256']='unknown-worker'
    elif change=='extra_file':current['stage_implementation_sha256']['new_runtime.py']='new-source'
    assert _compatible(case,stage_id)is None


@pytest.mark.parametrize('change',['da3','affine_loader','global_binding','unrelated_module','export_registration','capture_diagnostics','ui_presentation'])
def test_changed_computational_dependencies_are_not_whitelisted_by_filename(tmp_path,monkeypatch,change):
    import shutil
    case=list(_case(tmp_path));copied=tmp_path/'builder';shutil.copytree(Path(stages.__file__).parent,copied)
    worker=copied/'stage_workers.py'
    if change=='da3':worker.write_text(worker.read_text().replace("infer_gs=False, use_ray_pose=False","infer_gs=True, use_ray_pose=False"))
    elif change=='affine_loader':worker.write_text(worker.read_text().replace("'calibration/simfoundry.py'","'calibration/other.py'"))
    elif change=='global_binding':worker.write_text(worker.read_text()+"\nda3 = video\n")
    elif change=='export_registration':
        p=copied/'registration.py';p.write_text(p.read_text()+"\n# Unreviewed settings producer change\n")
    elif change=='capture_diagnostics':
        p=copied/'validation.py';p.write_text(p.read_text()+"\n# Unreviewed diagnostics change\n")
    elif change=='ui_presentation':
        p=copied/'ui_reconstruction.py';p.write_text(p.read_text()+"\n# Unreviewed UI change\n")
    else:
        p=copied/'files.py';p.write_text(p.read_text()+"\n# Changed dependency\n")
    monkeypatch.setattr(stages,'__file__',str(copied/'stage_artifacts.py'))
    case[3]['stage_implementation_sha256']=_source_map(copied)
    case[3]['operations']['da3']['worker_sha256']=case[3]['stage_implementation_sha256']['stage_workers.py']
    assert _compatible(case)is None


def test_original_output_closure_remains_mandatory_for_caller(tmp_path):
    case=_case(tmp_path);artifact=case[0]
    (tmp_path/'prediction.npz').write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='integrity'):artifact.validate(tmp_path)
