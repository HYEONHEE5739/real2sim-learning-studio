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
