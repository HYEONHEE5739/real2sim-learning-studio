#!/bin/bash
# Existing Qt and backend interpreters; no installation or environment activation.
set -eu
project_root=$(cd -- "$(dirname -- "$0")" && pwd)
qt_python=${QT_PYTHON:-$project_root/workbench_runs/runtime/qt/bin/python3.11}
backend_python=${BACKEND_PYTHON:-$HOME/miniconda3/envs/lerobot-arena/bin/python}
workspace=${WORKBENCH_WORKSPACE:-$project_root/workbench_runs}
# Keep argparse's existing last-option-wins contract, including explicit CLI paths.
launch_args=("$@")
for ((i=0; i<${#launch_args[@]}; i++)); do
    case ${launch_args[i]} in
        --backend-python) backend_python=${launch_args[i+1]:-} ;;
        --backend-python=*) backend_python=${launch_args[i]#*=} ;;
    esac
done
if [[ ! -f "$qt_python" || ! -x "$qt_python" ]]; then
    printf 'QT_PYTHON is not an existing executable: %s\n' "$qt_python" >&2; exit 2
fi
if [[ ! -f "$backend_python" || ! -x "$backend_python" ]]; then
    printf 'BACKEND_PYTHON / --backend-python is not an existing executable: %s\n' "$backend_python" >&2; exit 2
fi
isaaclab_source=
if [[ -n ${ISAACLAB_ROOT:-} ]]; then
    isaaclab_source=$ISAACLAB_ROOT/source/isaaclab
    if [[ ! -d "$isaaclab_source" ]]; then
        printf 'ISAACLAB_ROOT/source/isaaclab does not exist: %s\n' "$isaaclab_source" >&2; exit 2
    fi
elif [[ -d "$HOME/IsaacLab/source/isaaclab" ]]; then
    isaaclab_source=$HOME/IsaacLab/source/isaaclab
fi
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export BACKEND_PYTHON="$backend_python"
export PYTHONPATH="$project_root/scene_contract/src:$project_root/real2sim_builder/src:$project_root/robot_learning_workbench/src${isaaclab_source:+:$isaaclab_source}${PYTHONPATH:+:$PYTHONPATH}"
exec "$qt_python" -B -m robot_learning_workbench.ui.app --backend-python "$backend_python" --task-modules "$project_root/robot_learning_workbench/task_modules.yaml" --workspace "$workspace" "$@"
