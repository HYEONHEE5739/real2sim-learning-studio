from pathlib import Path
import pytest
from robot_learning_workbench.learning import policy,train


def test_registered_configs_come_from_official_factory():
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies import factory
    rows=policy.policy_catalog()
    assert {r['type'] for r in rows}==set(PreTrainedConfig.get_known_choices())
    assert {'act','smolvla','diffusion','pi0','pi05'} <= {r['type'] for r in rows}
    diffusion=next(r for r in rows if r['type']=='diffusion')
    assert diffusion['config']['n_obs_steps']==factory.make_policy_config('diffusion').n_obs_steps
    assert 'horizon' in diffusion['fields']


def test_diffusion_training_not_rejected_as_unknown(tmp_path):
    config=dict(policy=dict(type='diffusion',push_to_hub=False,pretrained_backbone_weights=None),dataset=dict(root=str(tmp_path/'data'),repo_id='local/data'),output_dir=str(tmp_path/'out'),steps=1,batch_size=1,save_freq=1,log_freq=1,eval_freq=0)
    train.validate_config(config,dataset=tmp_path/'data',output=tmp_path/'out',mode='scratch')
    config['policy']['type']='invented'
    with pytest.raises(ValueError,match='not registered'):
        train.validate_config(config,dataset=tmp_path/'data',output=tmp_path/'out',mode='scratch')


def test_finetune_requires_matching_local_checkpoint(tmp_path):
    import json
    config=dict(policy=dict(type='diffusion',push_to_hub=False),dataset=dict(root=str(tmp_path/'data'),repo_id='local/data'),output_dir=str(tmp_path/'out'),steps=1,batch_size=1,save_freq=1,log_freq=1,eval_freq=0)
    with pytest.raises(ValueError,match='pretrained_path'):train.validate_config(config,dataset=tmp_path/'data',output=tmp_path/'out',mode='finetune')
    model=tmp_path/'model';model.mkdir();(model/'model.safetensors').write_bytes(b'fixture');(model/'config.json').write_text(json.dumps({'type':'act'}));config['policy']['pretrained_path']=str(model)
    with pytest.raises(ValueError,match='type'):train.validate_config(config,dataset=tmp_path/'data',output=tmp_path/'out',mode='finetune')


def test_scratch_never_silently_uses_policy_pretrained_path(tmp_path):
    config=dict(policy=dict(type='act',push_to_hub=False,pretrained_path=str(tmp_path)),dataset=dict(root=str(tmp_path/'data'),repo_id='local/data'),output_dir=str(tmp_path/'out'),steps=1,batch_size=1,save_freq=1,log_freq=1,eval_freq=0)
    (tmp_path/'model.safetensors').write_bytes(b'fixture')
    with pytest.raises(ValueError,match='Scratch'):train.validate_config(config,dataset=tmp_path/'data',output=tmp_path/'out',mode='scratch')


def test_prediction_preserves_external_action_shape_without_scene_approval():
    import torch
    class Policy:
        def select_action(self,batch):return torch.tensor([[1.,2.]])
    result=policy.predict(Policy(),lambda b:b,lambda a:a,{})
    assert result.shape==(1,2)
    with pytest.raises(ValueError):policy.infer(Policy(),lambda b:b,lambda a:a,{},contract=None)
