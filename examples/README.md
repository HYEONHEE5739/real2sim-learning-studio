# Recipe and configuration examples

These are copies of settings exercised in the preserved 2026-10-28 integration
work. Only external file/output paths were replaced; they are **templates**, not
self-contained demonstrations. No Scene, dataset, pretrained cache or checkpoint
is embedded here. See [external inputs](../docs/external-assets.md).

- `source-mujoco.yaml`: numeric simulation Source stream,2 additional Episodes.
- `annotation-isaac.yaml`: full Source replay with4 actual vector environments.
- `datagen-mujoco-random.yaml`:4 additional successful Episodes,8 attempts, entropy Workspace Random.
- `evaluation-act-mujoco.yaml`: ACT checkpoint, Fixed placement,4 environments; Placement success gate.
- `train-act.yaml` / `act-smoke.json`: official ACT2-step smoke configuration.
- `train-smolvla.yaml` / `smolvla-smoke.json`: official SmolVLA2-step smoke configuration with the pinned loss compatibility.

Recipe input/output paths are resolved relative to the Recipe. The official
training JSON uses paths relative to the child working directory; the supplied
JSON examples assume execution from the repository root. Supply an intact
authorized v8 package in `assets-private/scene-v8-native`,
compatible datasets/model configuration/checkpoint under `datasets` and
`checkpoints`, and the exact expected local cached VLM for SmolVLA. Those paths
are ignored by Git. Edit both the training Recipe and official JSON consistently.
The example model-config path is an external input; no unverified replacement
physics configuration is generated.

For Source/DataGen, `execution.resume: true` means append to the specified existing
`output.directory`; `num_episodes` is the **additional** target. DataGen also
requires a finite additional attempt budget. `env_num` controls independent
environments. It is unrelated to the model checkpoint Resume option of Training.

Validate syntax with `python -m robot_learning_workbench.cli validate examples/NAME.yaml`.
Use `prepare` with the repository's `task_modules.yaml` only after supplying inputs.
No placeholder is an instruction to connect real hardware or automatically download weights.

`hub/download.yaml` demonstrates an explicitly pinned official cache download.
The receipt contains the real cache snapshot path to select in Curation/Training;
no extra bulk Dataset copy is created in the receipt directory. Existing local
Datasets and local official Policy/processor folders remain selectable directly.
`hub/upload.yaml` is deliberately unapproved: select an existing Repo, resolve its
current Commit/visibility, review the artifact and explicitly confirm before use.
The UI clears saved upload approval when reopening a Recipe. No token belongs in
these files. Uploading is separate from the offline official Trainer.

Training accepts installed official Policy config types. Select a registered model
and generate its actual default config in the Training page, then edit official
fields and save. `mode: finetune` requires both the Recipe `inputs.policy` and an
absolute matching local `policy.pretrained_path` in the official training JSON.
`mode: resume` retains the closed Workbench checkpoint/Dataset identity contract.
Registry membership does not imply SO101 Simulation or hardware compatibility.

Offline Robot inspection uses `execution.mode: offline`; no serial/camera device is
constructed or connected. `robot/precision-offline.yaml` reads a preserved profile.
Its `device_profile` JSON contains `role: leader|follower` and `sdk` with the
installed official SO101 Config fields (including matching `id`, `port`, and
`use_degrees: true`). Constructor-config checks do not establish physical safety.
Capture/Real-Sim inspection additionally selects `inputs.capture_session` (an
existing committed Builder Capture/Snapshot directory). `camera_config` contains
`cameras` keyed by the recorded camera IDs, each with its `resolution`.

A saved Capture can be internally valid yet unbound to the selected Scene. Policy
inference requires an explicit `device_profile.calibration_id` observation binding
and compatible measured model/radian Mapping. Historical model changes remain
PARTIAL until approved equivalence evidence is supplied. Command conversion also
requires a matching explicit `command_calibration_id` at `device_command` phase;
no observation binding becomes a command approval. Live hardware modes remain
unsupported. Offline Real Policy is an inspection, not a real rollout success.
