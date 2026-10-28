# Third-party notices and publication boundaries

## Isaac Lab / Mimic calculation subset

`robot_learning_workbench/src/robot_learning_workbench/generation/reference/`
contains the deliberately limited, adapted Isaac Lab 2.3.0 / Mimic 1.0.15 CPU
calculation subset. Per-file copyright and SPDX headers remain intact.

- `math.py`: BSD-3-Clause; full text in [LICENSE](robot_learning_workbench/src/robot_learning_workbench/generation/reference/LICENSE).
- Mimic data/selection/trajectory files: Apache-2.0; full text in [LICENSE-mimic](robot_learning_workbench/src/robot_learning_workbench/generation/reference/LICENSE-mimic).
- [NOTICE](robot_learning_workbench/src/robot_learning_workbench/generation/reference/NOTICE.md)
  describes import/subset adaptations; [UPSTREAM.json](robot_learning_workbench/src/robot_learning_workbench/generation/reference/UPSTREAM.json)
  records installed source identities. Its absolute paths are historical provenance.
- Official source: https://github.com/isaac-sim/IsaacLab/tree/v2.3.0

## LeRobot SmolVLA compatibility

`learning/smol_compat.py` contains an explicit worker-local compatibility change
for the pinned Apache-2.0 LeRobot 0.4.1 `modeling_smolvla.py` source. The upstream
copyright/license header remains in the compiled original module. The source file
in the installed SDK is not modified or bundled wholesale.

- Copyright 2025 HuggingFace Inc. team.
- Apache-2.0 text: [LICENSE-mimic](robot_learning_workbench/src/robot_learning_workbench/generation/reference/LICENSE-mimic).
- Source: https://github.com/huggingface/lerobot/blob/v0.4.1/src/lerobot/policies/smolvla/modeling_smolvla.py
- Compatibility rationale: https://github.com/huggingface/lerobot/pull/1717
  and https://github.com/huggingface/lerobot/issues/3433
- Changed behavior: read `action_is_pad`, exclude padded targets from model input,
  restrict loss to the actual Action dimensions and normalize by valid scalar count.

## External dependencies and Scene assets

SDK installations, downloaded model weights, datasets and the preserved v8 Scene
are not part of the source-only Git payload. Their licenses remain their owners'.
NVIDIA OmniPBR MDL files in the local Scene contain redistribution notices, but
this does not establish the license of accompanying robot meshes, converted USDs,
scans or textures. The upstream SO-ARM repository's license alone cannot establish
that every local derivative came from a particular licensed revision.

See [asset inventory](docs/scene-asset-inventory.csv) and
[external dependency review](docs/external-assets.md). Do not infer that absent
assets are optional or that publication rights have been approved.

## Project-owned code

No existing root LICENSE was present. This preparation does not assign a new
license to the owner's original code or to ported local Builder/workflow code.
Third-party license terms above continue to apply to their respective portions.
