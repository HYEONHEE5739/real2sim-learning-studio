#!/bin/bash
# Existing Qt and backend interpreters; no installation or environment activation.
set -eu
project_root=$(cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export PYTHONPATH="$project_root/scene_contract/src:$project_root/real2sim_builder/src:$project_root/robot_learning_workbench/src:/home/hyeonhee/IsaacLab/source/isaaclab${PYTHONPATH:+:$PYTHONPATH}"
exec /home/hyeonhee/soarm_isaaclab/soarm101_lab/.venv-real2sim-ui/bin/python3.11 -B -m robot_learning_workbench.ui.app --backend-python /home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python --task-modules "$project_root/robot_learning_workbench/task_modules.yaml" --workspace "$project_root/workbench_runs" "$@"
