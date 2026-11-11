"""Ultralytics SAM3.1 adapter; imported only by the owned SAM child.

Coordinates are those of the supplied upright RGB, including point prompts.
This does not implement the original SAM3 video/interactive state API.
"""
from pathlib import Path
import hashlib
import importlib.metadata


class SAM31:
    def __init__(self, model, *, confidence_threshold=.5, imgsz=1024, device='cuda:0'):
        if not Path(model).is_file():
            raise FileNotFoundError('Existing SAM3.1 checkpoint required')
        self.model = str(model)
        self.options = dict(model=self.model, task='segment', mode='predict',
                            half=True, quantize=16, device=device, conf=confidence_threshold,
                            imgsz=imgsz, save=False, verbose=False)
        self.predictor = None
        self.kind = None

    def _predict(self, image, kind, **prompts):
        import numpy as np
        import torch
        from ultralytics.models.sam import SAM3Predictor, SAM3SemanticPredictor
        if self.kind != kind:
            self.close()
            cls = SAM3Predictor if kind == 'point' else SAM3SemanticPredictor
            self.predictor = cls(overrides=self.options.copy())
            self.kind = kind
        # set_image accepts BGR ndarrays, unlike the PIL/RGB boundary here.
        rgb = np.asarray(image.convert('RGB'))
        self.predictor.set_image(np.ascontiguousarray(rgb[..., ::-1]))
        result = self.predictor(**prompts)[0]
        if result.masks is None:
            return [], np.empty((0, 4)), np.empty(0)
        masks = result.masks.data.detach().cpu().numpy() > 0
        if masks.shape[1:] != rgb.shape[:2]:
            raise ValueError('SAM3.1 returned masks outside the input pixel frame')
        boxes = result.boxes.xyxy.detach().cpu().numpy()
        scores = result.boxes.conf.detach().cpu().numpy()
        if len(boxes) != len(masks) or not np.isfinite(scores).all():
            raise ValueError('SAM3.1 mask/box/confidence contract mismatch')
        return list(masks), boxes, scores

    def predict_segmentation(self, image, category):
        return self._predict(image, 'text', text=[category])

    def predict_segmentation_with_point(self, image, *, point_coords, point_labels,
                                        multimask_output=True):
        # One physical object, multiple hints. Ultralytics chooses mask candidates;
        # its public call does not expose original SAM3 multimask_output semantics.
        return self._predict(image, 'point', points=[point_coords], labels=[point_labels])

    def provenance(self):
        with Path(self.model).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        return {'backend': 'ultralytics_sam31', 'version': importlib.metadata.version('ultralytics'),
                'checkpoint': self.model, 'sha256': digest, 'half': True, 'quantize': 16,
                'pixel_frame': 'supplied upright RGB', 'identity_verified': False,
                'point_api': 'SAM3Predictor; no original SAM3 session/multimask guarantee'}

    def close(self):
        import torch
        self.predictor = None
        self.kind = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
