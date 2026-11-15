"""Device selection must precede the official loader, without editing saved configs."""
from pathlib import Path
from types import SimpleNamespace as NS
import json
import pytest
from robot_learning_workbench.learning.policy import load_policy
from robot_learning_workbench.data.native import file_sha256


@pytest.mark.parametrize('requested,saved',[('cpu','cuda'),('cuda:0','cpu')])
def test_requested_device_reaches_official_loader_and_input_processor_first(tmp_path,monkeypatch,requested,saved):
    import torch
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies import factory
    for name in ('config.json','policy_preprocessor.json','policy_postprocessor.json'):(tmp_path/name).write_text(json.dumps({'type':'act','device':saved}))
    (tmp_path/'model.safetensors').write_bytes(b'Loader boundary fixture; not model weights')
    before={p:file_sha256(p)for p in tmp_path.iterdir()}
    cfg=NS(device=saved,type='act');seen={}
    monkeypatch.setattr(PreTrainedConfig,'from_pretrained',lambda *a,**k:cfg)
    monkeypatch.setattr(torch.cuda,'is_available',lambda:True);monkeypatch.setattr(torch.cuda,'device_count',lambda:1)
    class Policy:
        config=cfg
        @classmethod
        def from_pretrained(cls,*args,config,**kwargs):
            seen['loaded_device']=config.device
            assert config.device==requested,'Official loader received the saved device before the request was applied'
            return cls()
        def to(self,device):seen['to']=str(device);return self
        def eval(self):return self
        def reset(self):pass
    monkeypatch.setattr(factory,'get_policy_class',lambda _:Policy)
    def processors(**kwargs):seen['processor']=kwargs['preprocessor_overrides']['device_processor']['device'];return None,None
    monkeypatch.setattr(factory,'make_pre_post_processors',processors)
    load_policy(tmp_path,device=requested)
    assert seen=={'loaded_device':requested,'to':requested,'processor':requested}
    assert before=={p:file_sha256(p)for p in tmp_path.iterdir()}


def test_cuda_request_is_rejected_before_official_loader_when_not_available(tmp_path,monkeypatch):
    import torch
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies import factory
    for name in ('config.json','policy_preprocessor.json','policy_postprocessor.json'):(tmp_path/name).write_text(json.dumps({'type':'act','device':'cpu'}))
    (tmp_path/'model.safetensors').write_bytes(b'boundary')
    monkeypatch.setattr(torch.cuda,'is_available',lambda:False)
    monkeypatch.setattr(PreTrainedConfig,'from_pretrained',lambda *a,**k:NS(device='cpu'))
    class Policy:
        @classmethod
        def from_pretrained(cls,*args,**kwargs):pytest.fail('Unsupported CUDA request reached model loading')
    monkeypatch.setattr(factory,'get_policy_class',lambda _:Policy)
    with pytest.raises(ValueError,match='CUDA|cuda'):load_policy(tmp_path,device='cuda:0')


def test_actual_tiny_official_act_saved_as_cuda_loads_on_cpu_without_cuda(tmp_path,monkeypatch):
    import torch
    from lerobot.configs.types import PolicyFeature,FeatureType,NormalizationMode
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    cfg=ACTConfig(device='cpu',input_features={'observation.state':PolicyFeature(FeatureType.STATE,(6,)),
        'observation.environment_state':PolicyFeature(FeatureType.ENV,(6,))},output_features={'action':PolicyFeature(FeatureType.ACTION,(6,))},
        normalization_mapping={kind:NormalizationMode.IDENTITY for kind in (FeatureType.STATE,FeatureType.ENV,FeatureType.ACTION)},
        dim_model=16,n_heads=2,dim_feedforward=32,n_encoder_layers=1,n_decoder_layers=1,n_vae_encoder_layers=1,
        latent_dim=4,use_vae=False,chunk_size=2,n_action_steps=1,pretrained_backbone_weights=None)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(23)
        policy=ACTPolicy(cfg)
    pre,post=make_pre_post_processors(cfg)
    policy.save_pretrained(tmp_path);pre.save_pretrained(tmp_path);post.save_pretrained(tmp_path)
    config=json.loads((tmp_path/'config.json').read_text());config['device']='cuda';(tmp_path/'config.json').write_text(json.dumps(config))
    before={p:file_sha256(p)for p in tmp_path.iterdir()if p.is_file()}
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES','');monkeypatch.setattr(torch.cuda,'is_available',lambda:False)
    loaded,pre,post,record=load_policy(tmp_path,device='cpu')
    assert all(p.device.type=='cpu'for p in loaded.parameters())and loaded.config.device=='cpu'
    assert any(getattr(step,'device',None)in('cpu',torch.device('cpu'))for step in pre.steps)
    assert before=={p:file_sha256(p)for p in tmp_path.iterdir()if p.is_file()}
