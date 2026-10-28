from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import pytest
from robot_learning_workbench import run as w
from robot_learning_workbench.recipe import read_recipe


def request(tmp_path,request_id='intent'):
    (tmp_path/'data/meta').mkdir(parents=True,exist_ok=True);(tmp_path/'data/meta/info.json').write_text('{}');(tmp_path/'train.json').write_text('{"policy":{"type":"act"}}')
    path=tmp_path/'train.yaml';path.write_text('''schema_version: 1
stage: train
inputs: {dataset: data, training_config: train.json}
execution: {mode: scratch}
output: {directory: output}
''')
    return w.StartRequest(request_id,path,read_recipe(path).sha256,'train',tmp_path/'output')


def test_concurrent_same_request_starts_only_one_process(tmp_path,monkeypatch):
    calls=[]
    class Process:
        pid=123456
    monkeypatch.setattr(w.subprocess,'Popen',lambda *a,**kw:(calls.append(a),Process())[1])
    req=request(tmp_path)
    def start(_):
        try:return w.start(req)
        except w.RunError as ex:
            assert ex.code=='RUN_STATE_UNKNOWN';return None  # in-progress durable claim, never launch again
    with ThreadPoolExecutor(max_workers=8) as pool:handles=list(pool.map(start,range(8)))
    handle=next(h for h in handles if h)
    assert len(calls)==1 and w.start(req).run_id==handle.run_id
    assert all(h is None or h.run_id==handle.run_id for h in handles)
    with pytest.raises(w.RunError) as ex:w.start(replace(req,expected_recipe_sha256='f'*64))
    assert ex.value.code=='REQUEST_CONFLICT'


def test_partial_claim_is_unknown_and_not_removed(tmp_path,monkeypatch):
    req=request(tmp_path);root=tmp_path/'runs';(root/'requests').mkdir(parents=True)
    path=root/'requests'/(w._sha(req.request_id.encode())+'.json');path.write_bytes(b'')
    with pytest.raises(w.RunError) as ex:w.start(req,run_root=root)
    assert ex.value.code=='RUN_STATE_UNKNOWN' and path.read_bytes()==b''


def test_different_requests_cannot_reserve_same_output(tmp_path,monkeypatch):
    class Process:pid=123456
    calls=[];monkeypatch.setattr(w.subprocess,'Popen',lambda *a,**kw:(calls.append(a),Process())[1])
    req=request(tmp_path);w.start(req)
    with pytest.raises(w.RunError):w.start(replace(req,request_id='second'))
    assert len(calls)==1


def test_actual_invalid_training_config_is_failed_before_output(tmp_path):
    import time
    handle=w.start(request(tmp_path))
    for _ in range(200):
        status=w.read_status(handle.run_dir)
        if status.status in ('failed','completed','cancelled'):break
        time.sleep(.02)
    assert status.status=='failed' and status.error['code']=='TRAIN_CONFIG_INVALID'
    assert not (tmp_path/'output').exists()


def test_claim_without_spawn_ack_is_unknown_and_never_relaunched(tmp_path,monkeypatch):
    req=request(tmp_path);root=tmp_path/'runs';(root/'requests').mkdir(parents=True)
    run_id='a'*32;directory=root/run_id;directory.mkdir();w._status(directory,'prepared','preparing')
    claim=root/'requests'/(w._sha(req.request_id.encode())+'.json')
    w._atomic(claim,{'run_id':run_id,'run_dir':str(directory),'payload_sha256':w._sha(w._bytes(req))})
    calls=[];monkeypatch.setattr(w.subprocess,'Popen',lambda *a,**kw:calls.append(1))
    with pytest.raises(w.RunError) as ex:w.start(req,run_root=root)
    assert ex.value.code=='RUN_STATE_UNKNOWN' and not calls
