# NVIDIA SimFoundry attribution

Portions of the stage geometry and stage processing code are adapted from
[NVlabs/SimFoundry](https://github.com/NVlabs/SimFoundry), commit
`9e34ebefcd020583fbb755a8b57268dce78eca26`.

Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
Licensed under Apache License 2.0; see [SimFoundry-LICENSE](SimFoundry-LICENSE).

Source files include `simfoundry/pipeline/depth_backends.py`,
`simfoundry/pipeline/frame_selection.py`,
`scripts/pipeline/A_reconstruction/stages/4_unify_world_frame.py`,
and `8_match_object_poses.py`. Source URLs and deliberate differences are
recorded in `docs/simfoundry-reconstruction-migration.md`.
Runtime providers may use the separately installed original project. No models,
user images, downloaded source checkout, or credentials are bundled here.

Additional ports/adapters in Phase F–H use `simfoundry/models/sam_v3.py`,
Stage5/6 decomposition/preparation, `simfoundry/pipeline/upright_from_fit.py`,
`simfoundry/pipeline/front_canonicalization.py`, and Stage12 motion thresholds.
Native +Z adapters preserve the original +Y helpers and explicitly change basis.
The local-only RemBG loader retains Bria's original prediction implementation;
its local weight path adapter prevents model downloads.

### Local Runtime adapter follow-up (2026-11-10)

`calibration/decomposition.py` also ports the unchanged numerical denoising,
ray removal-order and cycle-safe support-level functions from the pinned
`processing_utils.py`, Stage5 and `pipeline/support_graph.py`. Imports are lazy;
no original SAM/VLM/model modules are imported by the CPU removal worker.
The denoising portions retain the upstream ACDC authors (Stanford Vision and
Learning Lab), Copyright (c) 2024, and NVIDIA modifications, Copyright (c) 2026,
under Apache-2.0. Visualization helpers are not part of the worker interface.

Ultralytics SAM3.1 and ComfyUI/GGUF remain separately installed dependencies;
their model and code licenses are not relicensed by these adapters.
