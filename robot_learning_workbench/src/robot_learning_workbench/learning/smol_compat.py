"""Explicit, process-local fixed-source SmolVLA0.4.1 loss backport.

SDK files/classes are never overwritten or monkeypatched. The one pinned module
is compiled with these reviewed changes on its first import in an opted-in child.
Official key fix: https://github.com/huggingface/lerobot/pull/1717
Valid-scalar reduction: https://github.com/huggingface/lerobot/issues/3433
Apache-2.0 upstream copyright remains in the compiled original source.
"""
import hashlib
import importlib.abc
import importlib.util
from importlib.machinery import PathFinder
import sys

UPSTREAM_SHA256='f3195d94eac083b3360e0b8596f8fb6816f375d576f4d579698153b6e6846ec3'
MODULE='lerobot.policies.smolvla.modeling_smolvla'
PATCH_ID='smolvla-0.4.1-valid-action-loss-v1'


def patched_source(raw):
    if hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA256:raise ValueError('SmolVLA source identity differs from pinned0.4.1 patch')
    source=raw.decode()
    source=source.replace('actions_is_pad = batch.get("actions_id_pad")', '''actions_is_pad = batch.get("action_is_pad")
        if actions_is_pad is not None:
            if actions_is_pad.dtype != torch.bool or actions_is_pad.shape != actions.shape[:2]:
                raise ValueError("Expected bool action_is_pad[B,chunk]")
            # A padded target cannot affect valid predictions via suffix attention.
            actions = actions.masked_fill(actions_is_pad.unsqueeze(-1), 0)''',1)
    source=source.replace('loss_dict["losses_after_forward"] = losses.clone()', '''losses = losses[:, :, : self.config.action_feature.shape[0]]
        loss_dict["losses_after_forward"] = losses.detach().mean().item()''',1)
    source=source.replace('loss_dict["losses_after_in_ep_bound"] = losses.clone()', 'loss_dict["losses_after_in_ep_bound"] = losses.detach().mean().item()',1)
    source=source.replace('loss_dict["losses_after_rm_padding"] = losses.clone()', 'loss_dict["losses_after_rm_padding"] = losses.detach().mean().item()',1)
    source=source.replace('loss = losses.mean()', '''if actions_is_pad is None:
            loss = losses.mean()
        else:
            num_valid = ((~actions_is_pad).sum() * losses.shape[-1]).clamp_min(1)
            loss = losses.sum() / num_valid''',1)
    return source


class _FixedSource(importlib.abc.SourceLoader):
    def __init__(self,path):self.path=path
    def get_filename(self,fullname):return self.path
    def get_data(self,path):
        with open(path,'rb') as stream:return stream.read()
    def get_code(self,fullname):return compile(patched_source(self.get_data(self.path)),self.path,'exec')


class _OneModule(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname!=MODULE:return None
        spec=PathFinder.find_spec(fullname,path)
        if spec is None:raise ImportError(MODULE)
        return importlib.util.spec_from_file_location(fullname,spec.origin,loader=_FixedSource(spec.origin))


def enable():
    from ..data.lerobot import _pinned
    _pinned()
    if MODULE in sys.modules:
        module=sys.modules[MODULE]
        if not isinstance(module.__loader__,_FixedSource):raise RuntimeError('Enable explicit SmolVLA patch before official policy import')
        return
    if not any(isinstance(f,_OneModule) for f in sys.meta_path):sys.meta_path.insert(0,_OneModule())


def identity():
    from pathlib import Path
    return {'patch_id':PATCH_ID,'upstream_sha256':UPSTREAM_SHA256,'patch_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


if __name__=='__main__':
    import runpy
    enable();sys.argv=['lerobot_train',*sys.argv[1:]]
    runpy.run_module('lerobot.scripts.lerobot_train',run_name='__main__')
