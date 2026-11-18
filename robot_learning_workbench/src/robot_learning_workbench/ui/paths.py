"""UI suggestions only. Explicit Recipe paths and Native layouts remain authoritative."""
from pathlib import Path
import os
import sys

GROUPS={'teleoperation':'source','scene':'scenes','source':'source','annotation':'annotation','datagen':'datagen',
        'curation':'curation','convert':'dataset','merge':'dataset','train':'policy',
        'simulation_evaluation':'evaluation','offline_validation':'evaluation','real_evaluation':'evaluation',
        'capture':'evaluation','precision_calibration':'evaluation','real_sim':'evaluation'}


def output_path(workspace,stage,name=None):
    from scene_contract.naming import numbered_path
    group=GROUPS[stage];name=name or numbered_path(Path(workspace)/group,stage).name
    if not isinstance(name,str) or not name.strip() or name in ('.','..') or Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('One explicit Run name required')
    return Path(workspace).resolve()/group/name


def input_directory(workspace,stage,key):
    group='policy' if key in ('policy','checkpoint') else 'scenes' if key=='scene' else 'source' if key=='dataset' and stage=='annotation' else 'annotation' if key=='dataset' and stage=='datagen' else 'dataset' if key in ('dataset','artifact') else None
    return Path(workspace).resolve()/group if group else Path(workspace).resolve()


def protected_destination(path, *, backend_python=None, workspace=None):
    """Preserve original projects and installed runtimes for the current account."""
    target=Path(path).resolve()
    roots=[Path.home()/name for name in ('miniconda3','IsaacLab')]
    roots.extend((Path(sys.prefix),Path(sys.base_prefix)))
    for name in ('ISAACLAB_ROOT','CONDA_PREFIX'):
        if os.environ.get(name):roots.append(Path(os.environ[name]))
    python=backend_python or os.environ.get('BACKEND_PYTHON')
    if python:
        executable=Path(python).expanduser().absolute()
        roots.append(executable)
        # A command/wrapper outside a bin layout does not identify an install
        # prefix. In particular /no/worker must never protect the whole '/'.
        prefix=executable.parent.parent
        if executable.parent.name=='bin'and prefix!=Path(prefix.anchor):
            container=prefix.parent.parent if prefix.parent.name=='envs'else prefix
            roots.append(prefix if container==Path(container.anchor)else container)
    if workspace:roots.extend(Path(workspace)/name for name in ('scenes','devices','runtime','.assets'))
    if any(target.is_relative_to(root.resolve()) for root in roots):return True
    # Other checkouts are protected by their own Git boundary, without knowing
    # any unrelated project's name or installation location.
    project=Path(__file__).resolve().parents[4]
    return any(parent!=project and (parent/'.git').exists() for parent in target.parents)
