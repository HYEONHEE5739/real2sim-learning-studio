"""UI suggestions only. Explicit Recipe paths and Native layouts remain authoritative."""
from pathlib import Path
import uuid

GROUPS={'scene':'scenes','source':'source','annotation':'annotation','datagen':'datagen',
        'curation':'dataset','convert':'dataset','merge':'dataset','train':'policy',
        'simulation_evaluation':'evaluation','offline_validation':'evaluation','real_evaluation':'evaluation',
        'capture':'evaluation','precision_calibration':'evaluation','real_sim':'evaluation'}


def output_path(workspace,stage,name=None):
    group=GROUPS[stage];name=name or stage+'-'+uuid.uuid4().hex[:8]
    if not isinstance(name,str) or not name.strip() or name in ('.','..') or Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('One explicit Run name required')
    return Path(workspace).resolve()/group/name


def input_directory(workspace,stage,key):
    group='policy' if key in ('policy','checkpoint') else 'scenes' if key=='scene' else 'source' if key=='source_dataset' or key=='dataset' and stage=='annotation' else 'annotation' if key=='dataset' and stage=='datagen' else 'dataset' if key in ('dataset','artifact') else None
    return Path(workspace).resolve()/group if group else Path(workspace).resolve()
