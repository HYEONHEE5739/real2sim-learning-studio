# Real2Sim Learning Studio

**Real2Sim, Imitation Learning & Simulation Evaluation**

Scene authoring, simulation data collection/generation, non-destructive curation,
official LeRobot training and simulation policy evaluation in a Qt Workbench.
The backend uses Isaac Lab/Isaac Sim, MuJoCo and LeRobot APIs.

**Source-only release:** the source, tests, package definitions and documentation
are published together. The complete Scene v8 package, including SO-101 meshes,
derived USDs, textures and calibration assets, is not distributed. **A clone alone
cannot run the complete simulation workflow.** Supply an intact, authorized Scene
package and the pinned SDK environments separately.

## Architecture

| Package | Responsibility |
|---|---|
| [scene_contract](scene_contract/) | Shared read-only Scene package, asset integrity, frame and Calibration binding contracts. |
| [real2sim_builder](real2sim_builder/) | Reconstruction, alignment/calibration review and immutable USD/MJCF Scene exports. |
| [robot_learning_workbench](robot_learning_workbench/) | Recipe/Worker execution, simulation workflows, Native datasets, curation, learning, evaluation and Qt UI. |

The three sibling packages retain their existing import structure. Builder and
Workbench use `scene_contract`; simulation engines own live physics state.

## Workflow

Scene Builder → Source → Annotation → Fixed/Random DataGen → Curation →
official LeRobot Dataset → official Policy Training → Simulation Evaluation.

## Features

- Actual Isaac and MuJoCo execution; independent environments tested at `env_num=1/4`.
- Pre-step state/RGB and requested/applied position targets; separate post-step Task results.
- Pinocchio DLS + Best Effort; inward position-target Saturation within approved model limits.
- Fixed placement and entropy-based Workspace Random placement; no Random Pose seed restoration.
- Source/DataGen append to the same Native dataset path, immutable closed segments and attempt history.
- Original/curated/materialized separation, selection, trim, split, distributions and compatible Merge.
- Official LeRobot Dataset materialization with existing encoded video sharing.
- Official LeRobot Registry/Factory and CLI training, local fine-tuning, checkpoints/Resume and independent validation. ACT, SmolVLA and Diffusion have smoke execution evidence; other registered models require their own inputs/dependencies and validation.
- Commit-pinned Hugging Face Dataset/Policy downloads and explicit, parent-commit guarded uploads to existing Repos. Smoke validation performs no uploads.
- Project-based Capture and Real/Sim with measured Follower state, four-image capture and registered Builder Export revisions. General authored exports use measured FK rendering; preserved v8 keeps its native renderer.
- Manual reference-angle Precision Calibration: Raw collection, Fit, separate-pose review, immutable Profile save and explicitly approved device configuration revision. SDK Motor Calibration is a separate procedure.
- Hardware connections remain read-only. Manual Teleoperation budget inputs have been removed; physical six-axis Teleoperation is blocked (`ARM_CONTROL_SPEC_UNVERIFIED`) until verified device control specifications are available. Memory control and existing safety/encoding/watchdog checks remain. Physical motion is unverified.
  Gripper-only one-shot code requires its separate command binding and supervised approval; autonomous real Policy motor control remains disabled.
- Qt workflow pages and selected-environment Side/Wrist 640×480 latest-frame Preview.

The SmolVLA path explicitly compiles one SHA-pinned LeRobot 0.4.1 module with a
documented padding-loss compatibility change. Installed SDK files remain unchanged.

## Requirements and installation status

Validated local environments: Python **3.11.15**, NumPy **1.26.0**, Torch
**2.7.0+cu128**, Isaac Sim **5.1**, Isaac Lab **2.3.0**, MuJoCo **3.3.7**,
Pinocchio **2.7.0** (`pin`), LeRobot **0.4.1**, PyQt6/Qt **6.11.0**.
The Qt frontend and engine/learning backend use separate existing interpreters.
Per-package dependencies are in each `pyproject.toml`.

**This is not yet a self-contained, freshly install-tested distribution.** Scene v8,
calibration/assets, collected datasets, checkpoints and pretrained caches are local
dependencies; they are not silently replaced by sample data. Some regression tests
also require the preserved local B01/B02/B03 evidence and original projects.
See [external assets and reproducibility](docs/external-assets.md).

After separately provisioning the pinned SDK environments, the package installation
order is `scene_contract` → `real2sim_builder` → `robot_learning_workbench`, using the
three local directories. This order follows package dependencies; no clean-machine
installation or automatic Isaac/CUDA provisioning is claimed.

## Usage

On the original configured workstation:

```bash
./run_workbench_ui.sh
```

That script currently contains workstation-specific interpreter/Isaac Lab paths.
For a separately provisioned workstation, the existing UI entry point accepts explicit
interpreters and paths. From the repository root, with `QT_PYTHON`, `BACKEND_PYTHON`,
`ISAACLAB_ROOT` and `WORKBENCH_WORKSPACE` set to your own existing installations:

```bash
PYTHONPATH="$PWD/scene_contract/src:$PWD/real2sim_builder/src:$PWD/robot_learning_workbench/src:$ISAACLAB_ROOT/source/isaaclab" \
  "$QT_PYTHON" -B -m robot_learning_workbench.ui.app \
  --backend-python "$BACKEND_PYTHON" \
  --task-modules "$PWD/robot_learning_workbench/task_modules.yaml" \
  --workspace "$WORKBENCH_WORKSPACE"
```

In a backend environment where the three packages are available, use a saved Recipe:

```bash
python -B -m robot_learning_workbench.cli validate /path/to/recipe.yaml
python -B -m robot_learning_workbench.cli prepare /path/to/recipe.yaml \
  --task-modules robot_learning_workbench/task_modules.yaml
python -B -m robot_learning_workbench.cli run /path/to/recipe.yaml \
  --task-modules robot_learning_workbench/task_modules.yaml --request-id unique-run-id
```

New Run output suggestions use `scenes/`, `source/`, `annotation/`, `datagen/`,
`dataset/`, `policy/` and `evaluation/` under the Workspace. Explicit saved Recipe
paths stay authoritative; collection Resume appends to the selected existing Dataset.

Review and adapt the [Recipe/config examples](examples/README.md) first. They are
copies of exercised settings with local paths replaced; external inputs must be
provided before `prepare` or execution. Physical motion requires explicit on-site approval;
see the Capture session report for read-only operation and remaining hardware limits.

## Current limitations

Feature parity with the former applications is incomplete. New-angle Precision Calibration,
normal Builder Export registration for Real/Sim, a new Hub repository’s first upload and
autonomous real Policy rollout remain gaps; see the [workflow audit](docs/leader-teleop-recovery.md).

- Validation focuses on the preserved v8 Scene; v9 and new measured Calibration are unfinished.
- Real Follower command binding, motor-range approval and physical safety are unverified.
  Physical arm motion is blocked; measured Camera/Joint skew can also block Observe Only inference.
- `env_num=1/4` was tested; arbitrary N, all Scenes, long runs and OOM recovery are not certified.
- Preview polling targets approximately 30Hz; actual simulation/Preview throughput is lower.
- ACT/SmolVLA/Diffusion short smoke training does not establish convergence or task success. The earlier canonical
  rollout matrix recorded 20 maximum-step failures per engine, Placement success **0**.
- The historical Isaac cube–cup position residual **1.197188790mm** remains OPEN.
- Same-path collection Resume is an Episode boundary operation, not an exact mid-physics checkpoint.

The local Studio now owns `pickplace_colorblock` under `workbench_runs/scenes/`,
with its closed v8 Package and a separate device configuration binding. Selecting
this Scene restores configuration without connecting hardware. Capture supports
optional Input Data and free-form notes; new users can start with cameras alone.
Unbound observations remain reference evidence and do not acquire robot actions or
model-radian semantics. See [Scene preparation and v8 migration](docs/scene-preparation-v8.md).
These local assets and the copied Qt runtime are excluded from Git; a clone still
requires separately provisioned assets and SDK/Qt environments.

## Documentation

- [Architecture](docs/architecture.md) · [Interfaces](docs/interfaces.md) · [Capability map](CAPABILITY-MAP.md)
- [Tasks](tasks/todo.md) · [Plan](tasks/plan.md)
- [Scene package SPEC](SPEC-scene-package.md) · [Simulation SPEC](SPEC-simulation-workflows.md)
- [Learning SPEC](SPEC-lerobot-learning.md) · [Curation SPEC](SPEC-data-curation.md)
- [Native Dataset transition](docs/native-dataset-transition.md)
- [Saturation recovery](docs/position-saturation-recovery.md)
- [Resume/Multi-Env/SmolVLA/Preview results](docs/resume-multienv-smolvla-preview.md)
- [Publication review](docs/github-upload-preparation.md)
- [Scene preparation, owned v8 and device setup](docs/scene-preparation-v8.md)
- [Precision Calibration and Builder Export integration](docs/precision-export-integration.md)
- [Leader Teleoperation recovery and workflow audit](docs/leader-teleop-recovery.md)
- [Earlier read-only Real/Sim implementation](docs/real-sim-observation.md)
- [Capture status and button fixes](docs/capture-feedback.md)
- [Persistent Capture / Real-Sim sessions](docs/capture-paired-sessions.md)
- [Architecture completion and feature transfer](docs/architecture-completion.md)
- [Live observation, Capture and gripper approval boundary](docs/hardware-read-gripper.md)
- [Four code-review fixes and verification](docs/code-review-followup.md)
- [Original Qt UI restoration and current Worker integration](docs/ui-original-restoration.md)

Historical reports contain local absolute paths and links to `docs/evidence/`.
Those preserved evidence directories are excluded from publication; such links are
not downloadable release artifacts or independently reproducible CI results.

## Licensing

See [third-party notices](THIRD_PARTY_NOTICES.md). Existing BSD/Apache notices are
retained. A blanket MIT/Apache license for the project's own code has not been
selected on the owner's behalf. Public source visibility alone does not grant
an additional open-source license. Scene asset redistribution requires separate
provenance review.
