"""Disposable official Policy fixtures; no learned weights or training claims.

Keep historical config/Dataset provenance read-only. Generate random initialized
weights and official processors/state in a temporary folder for contract tests.
The recorded step is a fixture label; no optimizer update is performed.
"""
import atexit
import json
from functools import lru_cache
from pathlib import Path
import tempfile


@lru_cache(maxsize=None)
def official_checkpoint(template):
    import torch
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
    from lerobot.policies.factory import get_policy_class,make_pre_post_processors
    from lerobot.utils.train_utils import save_training_state
    from robot_learning_workbench.learning.policy import seal_checkpoint
    template=Path(template)
    if template.name=='pretrained_model':template=template.parent
    record=json.loads((template/'workbench-checkpoint.json').read_text())
    config=record['config'];config['resume']=False
    cfg=PreTrainedConfig.from_pretrained(template/'pretrained_model',local_files_only=True)
    cfg.device='cpu';cfg.pretrained_path=None
    directory=tempfile.TemporaryDirectory(prefix='workbench-policy-fixture-')
    atexit.register(directory.cleanup);root=Path(directory.name)
    config['output_dir']=str(root/'training-output')
    config['policy']['device']='cpu';config['policy']['pretrained_path']=None
    # Isolate initialization from tests that intentionally seed their RNGs.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(17)
        policy=get_policy_class(cfg.type)(cfg)
        meta=LeRobotDatasetMetadata(config['dataset']['repo_id'],root=config['dataset']['root'])
        pre,post=make_pre_post_processors(cfg,dataset_stats=meta.stats)
        policy.save_pretrained(root/'pretrained_model')
        pre.save_pretrained(root/'pretrained_model');post.save_pretrained(root/'pretrained_model')
        optimizer=torch.optim.Adam(policy.parameters(),lr=1e-4)
        scheduler=None
        if config.get('scheduler'):
            import draccus
            from lerobot.optim.schedulers import LRSchedulerConfig
            scheduler=draccus.decode(LRSchedulerConfig,config['scheduler']).build(optimizer,config['steps'])
        save_training_state(root,record['step'],optimizer,scheduler)
    (root/'pretrained_model/train_config.json').write_text(json.dumps(config))
    seal_checkpoint(root,dataset=config['dataset']['root'],config=config,recipe_sha256='0'*64)
    return root
