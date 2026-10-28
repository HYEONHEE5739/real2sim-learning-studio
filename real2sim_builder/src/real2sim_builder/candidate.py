"""Existing Builder candidate responsibilities; authoring schemas unchanged."""
from pathlib import Path
from .editing import apply, check_scope, preserve
from contextlib import contextmanager
import copy
from .scene import empty, identifier, local_path, validate
import os
from .files import read, sha, write
import shutil


@contextmanager
def exclusive(project):
    project.require_writable()
    lock = project.root / 'working/run.lock'
    try:
        with lock.open('x') as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError('Project is busy; stop the active worker before editing')
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


class Candidate:

    def __init__(self, project, name):
        identifier(name)
        self.project = project
        self.name = name
        self.root = project.root / 'scratch/agent' / name
        if not (self.root / 'candidate.json').is_file():
            raise ValueError('Unknown candidate: ' + name)

    @classmethod
    def create(cls, project, name, target_object=None, allow=None):
        identifier(name)
        with exclusive(project):
            root = project.root / 'scratch/agent' / name
            scene = project.scene if (project.root / 'working/current_scene.yaml').exists() else empty(project.info['name'])
            scope = None
            if target_object is not None:
                if target_object not in {o['id'] for o in scene['objects']}:
                    raise ValueError('Unknown target object')
                fields = allow or ['pose']
                if not set(fields) <= {'pose', 'dimensions', 'visual', 'collision', 'color', 'material', 'physics'}:
                    raise ValueError('Invalid allowed object fields')
                scope = {'target_object': target_object, 'allow': fields}
            root.mkdir(parents=True, exist_ok=False)
            write(root / 'candidate_scene.yaml', scene)
            write(root / 'candidate.json', {'scope': scope, 'base_scene_sha256': sha(root / 'candidate_scene.yaml'), 'id': name, 'status': 'OPEN', 'base_signature': project.signature(scene), 'base_exists': (project.root / 'working/current_scene.yaml').exists()})
        return cls(project, name)

    @property
    def scene(self):
        return read(self.root / 'candidate_scene.yaml')

    @property
    def info(self):
        return read(self.root / 'candidate.json')

    def require_open(self):
        if self.info['status'] != 'OPEN':
            raise ValueError('Candidate is not open')

    def save(self, scene):
        self.project.require_writable()
        self.require_open()
        validate(scene, self.project.root)
        self.check_scope(scene)
        preserve(self.scene, scene)
        write(self.root / 'candidate_scene.yaml', scene)

    def check_scope(self, scene):
        if not self.info.get('scope'):
            return
        check_scope(self.project.scene, scene, self.info.get('scope'))

    def edit(self, operations):
        with exclusive(self.project):
            self.save(apply(self.scene, operations, self.project.root))
        return {'candidate': self.name, 'scene': str(self.root / 'candidate_scene.yaml')}

    def asset(self, path, kind='visual'):
        if kind not in ('visual', 'collision', 'textures'):
            raise ValueError('Unknown asset category')
        with exclusive(self.project):
            self.require_open()
            path = Path(path).resolve()
            digest = sha(path)
            dest = self.root / 'assets' / kind / (digest + path.suffix.lower())
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest != path:
                shutil.copy2(path, dest)
            scene = self.scene
            key = 'asset_' + digest[:16]
            scene['assets'][key] = {'path': dest.relative_to(self.project.root).as_posix(), 'sha256': digest, 'source': 'candidate imported asset', 'category': kind}
            self.save(scene)
        return {'asset': key, 'path': str(dest)}

    def evaluate(self, engine='blender', renderer='software-egl', validation=False, render_only=False):
        from real2sim_builder.rendering import Renderer
        from real2sim_builder.rendering import BlenderRenderer
        from real2sim_builder.validation import compare
        from real2sim_builder.reconstruction import validate_scene
        from PIL import Image, ImageOps
        import numpy as np
        with exclusive(self.project):
            self.require_open()
            scene = self.scene
            self.check_scope(scene)
            validate(scene, self.project.root, complete=engine != 'blender')
            validation = validation or ((bool(self.project.evidence.get('capture_sessions')) or bool(self.info.get('scope'))) and (not render_only))
            folder = self.root / 'renders' / engine
            factory = BlenderRenderer if engine == 'blender' else Renderer
            model = factory(scene, self.project.root, folder, renderer)
            blend = self.root / 'candidate.blend'
            if engine == 'blender' and blend.exists():
                build_signature = read(self.root / 'blender/canonical_signature.json')
                if build_signature != self.project.signature(scene):
                    raise ValueError('Blender workspace is stale; rebuild or sync explicitly')
                authored = read(self.root / 'blender/authored.json') if (self.root / 'blender/authored.json').exists() else {}
                sync = read(self.root / 'blender/sync.json') if (self.root / 'blender/sync.json').exists() else {}
                if authored.get('action') != 'build' or authored.get('blend_sha256') != sha(blend):
                    if sync.get('blend_sha256') != sha(blend) or sync.get('input_signature') != self.project.signature(scene):
                        raise ValueError('Explicit Blender synchronization required before evaluation; canonical is metric authority')
                model.blend = blend
            with model:
                if validation:
                    report, _ = validate_scene(self.project, scene, model, folder, {'mae': 0.12, 'reprojection_px': 5.0, 'silhouette_iou': 0.8})
                else:
                    rows = []
                    for index, obs in enumerate(self.project.evidence['images']):
                        if obs['split'] != 'train' or obs.get('eligible') is False:
                            continue
                        camera = next((c for c in scene['cameras'] if c['id'] == obs['camera']))
                        if camera['resolution'] != obs['resolution']:
                            raise ValueError('Camera/evidence resolution mismatch')
                        target = folder / 'previews' / f"{index:03d}_{obs['camera']}"
                        target.mkdir(parents=True, exist_ok=True)
                        from real2sim_builder.rendering import for_observation
                        with for_observation(self.project, scene, obs, model, folder / 'posed' / str(index)) as posed:
                            sim = posed.rgb(obs['camera'])
                        Image.fromarray(sim).save(target / (engine + '.png'))
                        metrics = {}
                        if not render_only:
                            real = np.asarray(ImageOps.exif_transpose(Image.open(local_path(self.project.root, obs['path']))).convert('RGB'))
                            metrics = compare(real, sim, target)
                            from real2sim_builder.validation import paired_diagnostics
                            paired = paired_diagnostics(self.project, obs, real, sim, target / 'paired')
                            if paired:
                                metrics['paired_diagnostics'] = paired
                        rows.append({'image': obs['path'], 'camera': obs['camera'], **metrics})
                    report = {'images': rows, 'scope': 'train render only' if render_only else 'train comparison', 'train_mae': float(np.mean([r['mae'] for r in rows])) if rows and (not render_only) else None, 'passed': False, 'needs': ['Independent held-out validation is required for acceptance']}
                report.update(engine=engine, input_signature=self.project.signature(scene))
                if engine == 'blender' and blend.exists():
                    report['blend_sha256'] = sha(blend)
            if validation and (self.project.evidence.get('capture_sessions') or self.info.get('scope')):
                baseline_folder = self.root / 'baseline' / engine
                with factory(self.project.scene, self.project.root, baseline_folder, renderer) as baseline_model:
                    baseline, _ = validate_scene(self.project, self.project.scene, baseline_model, baseline_folder, {'mae': 0.12, 'reprojection_px': 5.0, 'silhouette_iou': 0.8})
                report['baseline'] = baseline
                report['nonregression'] = nonregression(baseline, report, self.info.get('scope'))
            write(folder / 'metrics.json', report)
            write(self.root / 'metrics.json', report)
            if validation:
                import json
                with (self.project.root / 'working/calibration_holdout_usage.jsonl').open('a') as stream:
                    stream.write(json.dumps({'candidate': self.name, 'target': 'render_evaluation', 'holdout_observations': [r['observation'] for r in report.get('images', []) if r.get('observation') and r['split'] == 'validation']}) + '\n')
        return report

    def fit(self, target, options=None):
        from real2sim_builder.calibration.geometry import fit
        with exclusive(self.project):
            self.require_open()
            scene, report = fit(self.project, self.scene, target, options)
            if report['status'] == 'IMPROVED':
                self.save(scene)
            write(self.root / 'fit.json', report)
            if report.get('holdout_after'):
                import json
                images = {i.get('id'): i for i in self.project.evidence['images'] if i.get('id')}
                ids = report.get('holdout_observations') or sorted({r['observation'] for r in self.project.evidence['landmarks'] if r.get('observation') in images and images[r['observation']]['split'] == 'validation'})
                with (self.project.root / 'working/calibration_holdout_usage.jsonl').open('a') as stream:
                    stream.write(json.dumps({'candidate': self.name, 'target': target, 'holdout_observations': ids, 'status': report['status']}) + '\n')
        return report

    def reject(self):
        with exclusive(self.project):
            self.require_open()
            info = self.info
            info['status'] = 'REJECTED'
            write(self.root / 'candidate.json', info)
        return info

    def promote(self):
        with exclusive(self.project):
            self.require_open()
            p = self.project
            info = self.info
            scene = self.scene
            self.check_scope(scene)
            current = p.scene if (p.root / 'working/current_scene.yaml').exists() else empty(p.info['name'])
            preserve(current, scene)
            if p.signature(current) != info['base_signature']:
                raise ValueError('Candidate base is stale; create a new candidate')
            report = read(self.root / 'metrics.json')
            if report.get('input_signature') != p.signature(scene):
                raise ValueError('Candidate evaluation is stale')
            if (self.root / 'candidate.blend').exists():
                sync = read(self.root / 'blender/sync.json') if (self.root / 'blender/sync.json').exists() else {}
                if sync.get('blend_sha256') != sha(self.root / 'candidate.blend') or sync.get('input_signature') != p.signature(scene):
                    raise ValueError('Explicit Blender synchronization required before promotion')
            if report.get('scope') == 'train render only' or not report.get('images'):
                raise ValueError('Evaluate the candidate before promotion')
            if (p.evidence.get('capture_sessions') or info.get('scope')) and (not report.get('nonregression', {}).get('passed')):
                raise ValueError('Multi-pose promotion requires improved train metrics and non-regressing independent holdout: ' + str(report.get('nonregression')))
            validate(scene, p.root, complete=True)
            promoted = copy.deepcopy(scene)
            for asset in promoted['assets'].values():
                source = local_path(p.root, asset['path'])
                if source.is_relative_to(self.root):
                    category = asset.get('category', 'textures' if source.suffix.lower() in ('.png', '.jpg', '.jpeg') else 'visual')
                    target = p.root / 'working/assets' / category / (sha(source) + source.suffix.lower())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copy2(source, target)
                    asset['path'] = target.relative_to(p.root).as_posix()
                    asset['sha256'] = sha(target)
            validate(promoted, p.root, complete=True)
            rollback = p.root / 'scratch/agent/rollback.json'
            current_blend = p.root / 'working/blender/current.blend'
            previous_blend = p.root / 'scratch/agent/rollback.blend'
            previous_blend.unlink(missing_ok=True)
            if current_blend.exists():
                shutil.copy2(current_blend, previous_blend)
            write(rollback, {'scene': current, 'existed': info['base_exists'], 'state': p.state, 'promoted_signature': p.signature(promoted), 'had_blend': current_blend.exists(), 'report': read(p.root / 'working/validation/report.json') if (p.root / 'working/validation/report.json').exists() else None})
            previous = p.state
            try:
                p.save_scene(promoted)
                write(p.root / 'working/validation/report.json', {**report, 'passed': False, 'input_signature': p.signature(promoted), 'needs': ['Final cross-engine validation required after promotion'], 'validation_scope': 'VISUAL_ONLY'})
                p.update(status='DRAFT', stage=None, decision='CONTINUE', export=None, task='Candidate promoted; final cross-engine validation required', candidate=self.name)
                info['status'] = 'PROMOTED'
                write(self.root / 'candidate.json', info)
                blend = self.root / 'candidate.blend'
                if not blend.exists():
                    current_blend.unlink(missing_ok=True)
                if blend.exists():
                    target = p.root / 'working/blender/current.blend'
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(blend, target)
            except Exception:
                if info['base_exists']:
                    write(p.root / 'working/current_scene.yaml', current)
                else:
                    (p.root / 'working/current_scene.yaml').unlink(missing_ok=True)
                write(p.root / 'working/state.json', previous)
                restore_report(p, read(rollback).get('report'))
                if previous_blend.exists():
                    shutil.copy2(previous_blend, current_blend)
                else:
                    current_blend.unlink(missing_ok=True)
                info['status'] = 'OPEN'
                write(self.root / 'candidate.json', info)
                raise
        return {'candidate': self.name, 'status': 'PROMOTED', 'acceptance': 'not yet validated'}


def rollback(project):
    project.require_writable()
    with exclusive(project):
        path = project.root / 'scratch/agent/rollback.json'
        record = read(path)
        if project.signature() != record['promoted_signature']:
            raise ValueError('Current scene changed after promotion; refusing rollback')
        if record['existed']:
            write(project.root / 'working/current_scene.yaml', record['scene'])
        else:
            (project.root / 'working/current_scene.yaml').unlink(missing_ok=True)
        blend = project.root / 'working/blender/current.blend'
        if record.get('had_blend'):
            blend.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project.root / 'scratch/agent/rollback.blend', blend)
        else:
            blend.unlink(missing_ok=True)
        restore_report(project, record.get('report'))
        project.update(**{k: v for k, v in record['state'].items() if k not in ('updated_at', 'task')}, task='Candidate promotion rolled back')
        path.unlink()
    return {'status': 'ROLLED_BACK'}


def restore_report(project, report):
    project.require_writable()
    path = project.root / 'working/validation/report.json'
    if report is None:
        path.unlink(missing_ok=True)
    else:
        write(path, report)


def nonregression(baseline, candidate, scope=None):
    """Photometry and geometry must not trade away held-out evidence."""
    failures = []
    improved = False
    for split in ('train', 'validation'):
        old = baseline.get('multipose', {}).get(split, {})
        new = candidate.get('multipose', {}).get(split, {})
        if not new.get('count') or new.get('count') != old.get('count'):
            failures.append(split + ' requires the same independent pose correspondences')
            continue
        if new['behind_camera'] > old['behind_camera']:
            failures.append(split + ' points behind camera')
        if split == 'train':
            improved |= new['rmse_px'] < old['rmse_px'] - 1e-06
            if new['rmse_px'] > old['rmse_px'] + 1e-06:
                failures.append('train reprojection regressed')
        elif new['rmse_px'] > old['rmse_px'] + 1e-06:
            failures.append('holdout reprojection regressed')
    old_rows = {r['image']: r for r in baseline['images']}
    if set(old_rows) != {r['image'] for r in candidate['images']}:
        failures.append('Evidence observations missing or added')
    for row in candidate['images']:
        old = old_rows.get(row['image'])
        if old is None:
            failures.append('Evidence changed')
            continue
        old_objects = {o['object']: o for o in old.get('objects', [])}
        if set(old_objects) != {o['object'] for o in row.get('objects', [])}:
            failures.append('Object evaluation coverage changed')
        for obj in row.get('objects', []):
            previous = old_objects.get(obj['object'], {})
            for key in ('landmark_rmse_px', 'boundary_chamfer_px', 'center_error_px'):
                a = previous.get(key)
                b = obj.get(key)
                if a is not None and (b is None or ((row['split'] == 'validation' or (scope and obj['object'] != scope['target_object'])) and b > a + 1e-06)):
                    failures.append('Object geometry regressed or evidence lost: ' + obj['object'] + ' ' + key)
                if row['split'] == 'train' and a is not None and (b is not None):
                    improved |= b < a - 1e-06
            if (row['split'] == 'validation' or (scope and obj['object'] != scope['target_object'])) and previous.get('iou') is not None and (obj.get('iou') is None or obj['iou'] < previous['iou'] - 1e-06):
                failures.append('Object IoU regressed: ' + obj['object'])
        if row['split'] == 'train':
            improved |= row['mae'] < old['mae'] - 1e-06
            continue
        if row['mae'] > old['mae'] + 1e-06:
            failures.append('holdout MAE regressed: ' + row['image'])
        old_masks = {r['object']: r for r in old['silhouettes']}
        for mask in row['silhouettes']:
            previous = old_masks[mask['object']]
            if mask['iou'] < previous['iou'] - 1e-06:
                failures.append('holdout silhouette regressed: ' + mask['object'])
            if previous['center_error_px'] is not None and (mask['center_error_px'] is None or mask['center_error_px'] > previous['center_error_px'] + 1e-06):
                failures.append('holdout center error regressed')
    if scope and set(scope['allow']) & {'pose', 'dimensions', 'visual', 'collision'}:
        geometric_gain = any((o.get(k) is not None and n.get(k) is not None and (n[k] < o[k] - 1e-06) for row in candidate['images'] if row['split'] == 'train' for n in row.get('objects', []) if n['object'] == scope['target_object'] for o in old_rows.get(row['image'], {}).get('objects', []) if o['object'] == n['object'] for k in ('landmark_rmse_px', 'boundary_chamfer_px', 'center_error_px')))
        if not geometric_gain:
            failures.append('Scoped geometry requires object evidence improvement; global MAE alone is insufficient')
    if not improved:
        failures.append('No train improvement')
    return {'passed': not failures, 'failures': failures, 'policy': 'train improvement and independent holdout nonregression; not final acceptance'}

