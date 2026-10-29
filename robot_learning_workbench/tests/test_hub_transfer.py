from types import SimpleNamespace
import pytest


def test_resolve_pins_commit_and_download_reuses_official_cache(tmp_path,monkeypatch):
    from robot_learning_workbench.learning import hub
    calls=[]
    class API:
        def repo_info(self,repo_id,**kw):calls.append(kw);return SimpleNamespace(sha='a'*40,private=False)
    monkeypatch.setattr(hub,'api',lambda:API())
    monkeypatch.setattr(hub,'snapshot_download',lambda **kw:(calls.append(kw) or str(tmp_path)))
    resolved=hub.resolve('owner/data','dataset','main')
    assert resolved['commit']=='a'*40
    assert hub.download(resolved)==str(tmp_path)
    assert calls[-1]['revision']=='a'*40 and 'local_dir' not in calls[-1]


def test_upload_needs_explicit_scope_parent_and_confirmation(tmp_path,monkeypatch):
    from robot_learning_workbench.learning import hub
    (tmp_path/'meta').mkdir();(tmp_path/'meta/info.json').write_text('{}')
    calls=[]
    class API:
        def repo_info(self,*args,**kw):return SimpleNamespace(sha='a'*40,private=True)
        def upload_folder(self,**kw):calls.append(kw);return SimpleNamespace(oid='b'*40,commit_url='https://huggingface.co/owner/data/commit/'+ 'b'*40)
    monkeypatch.setattr(hub,'api',lambda:API())
    with pytest.raises(ValueError):hub.upload(tmp_path,'owner/data','dataset',parent='a'*40,private=True,confirm=False)
    with pytest.raises(ValueError):hub.upload(tmp_path,'owner/data','dataset',parent='c'*40,private=True,confirm=True)
    assert not calls
    result=hub.upload(tmp_path,'owner/data','dataset',parent='a'*40,private=True,confirm=True)
    assert result['commit']=='b'*40 and calls[0]['parent_commit']=='a'*40
    assert 'token' not in calls[0] and 'delete_patterns' not in calls[0]


def test_upload_rejects_disguised_external_credential_symlink(tmp_path,monkeypatch):
    from robot_learning_workbench.learning import hub
    artifact=tmp_path/'artifact';(artifact/'meta').mkdir(parents=True);(artifact/'meta/info.json').write_text('{}')
    secret=tmp_path/'token';secret.write_text('controlled-fixture-secret');(artifact/'notes.bin').symlink_to(secret)
    monkeypatch.setattr(hub,'api',lambda:pytest.fail('Must reject before any remote call'))
    with pytest.raises(ValueError,match='symlink'):hub.upload(artifact,'owner/data','dataset',parent='a'*40,private=True,confirm=True)


def test_create_repository_needs_explicit_approval_and_never_reuses_existing(tmp_path,monkeypatch):
    from robot_learning_workbench.learning import hub
    calls=[]
    class API:
        def create_repo(self,**kw):calls.append(kw);return 'https://huggingface.co/datasets/owner/new-data'
    monkeypatch.setattr(hub,'api',lambda:API())
    with pytest.raises(ValueError):hub.create_repository('owner/new-data','dataset',private=True,confirm=False)
    assert calls==[]
    out=hub.create_repository('owner/new-data','dataset',private=True,confirm=True)
    assert out['private'] is True and calls==[{'repo_id':'owner/new-data','repo_type':'dataset','private':True,'exist_ok':False}]


def test_empty_remote_repository_is_explicitly_blocked_instead_of_typeerror(monkeypatch):
    from robot_learning_workbench.learning import hub
    monkeypatch.setattr(hub,'api',lambda:SimpleNamespace(repo_info=lambda *a,**kw:SimpleNamespace(sha=None,private=True)))
    with pytest.raises(ValueError,match='initial')as error:hub.resolve('owner/empty','dataset','main')
    assert error.value.code=='HUB_EMPTY_REPOSITORY'
