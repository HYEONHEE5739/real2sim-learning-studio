# B00 완료 보고 — 기존 구현·자산·실행 경계 조사

조사일: 2026-10-25. 범위: **B00만 수행**. [작업 목록](../tasks/todo.md) / [개발 계획](../tasks/plan.md). 상태: 정적 inventory·대응표·미확정 목록·보존 대조 완료. 엔진/장치/학습 실행 검증 완료를 뜻하지 않는다.

## 결과와 조사 범위

기존 Source/Annotation은 Native JSON 경로, DataGen/Evaluation은 기존 Workflow 경로, 학습은 공식 LeRobot subprocess 경로가 실제로 존재한다. Builder는 별도 프로젝트이며 v8은 Builder Export를 소비하는 실행 Workspace다. 기존 코드 구조를 통째로 이관하지 않고 기능·수식·입출력/수명 계약을 새 책임에 대응할 수 있다.

기존 코드/설정/Asset·데이터는 수정하지 않았다. 생성물은 이 보고서와 증거 JSON 3개, 수정은 todo의 B00 상태뿐이다. 11개 SPEC·아키텍처·기존 데이터 형식은 바꾸지 않았다. B01/B02/B03 및 실제 구현은 시작하지 않았다.

- 목록: 원본 루트의 56,100개 파일/파일 symlink, 합계 26,198,743,083 bytes(lstat 크기 합계; 할당량 아님). `.git`, `.aws`, `.codex`는 제외, directory symlink는 따라가지 않음.
- 해시: 코드·스크립트·Asset·v8·해당 Builder Export 등 보호 루트 전체와 그 외 설정 확장자, 13,554개 regular file SHA-256. 상세 선택 기준은 file-hashes.json에 기록했다.
- AST: 소스/스크립트/시험 298개 Python 파일, symbol 3,015개·CLI 선언 316개·UI 라벨 후보 237개 색인. 정적 선언 수이며 도달 가능한 기능/실행 성공 개수가 아니다. 동적 import·조건 분기의 완전 도달성은 검증하지 않았다.
- v8 Manifest 92개, 원본 Builder Export Manifest 264개 등록 파일: 누락 0 / hash 불일치 0. 외부 의존성 closure·렌더·물리 동등성 증명은 별도다.
- 실제 데이터 파일 존재 수: HDF5 1,390, H5 4, MP4 2,637, safetensors 1,216, NPY 968, Parquet 1,139. 전체 루트 집계로 검증 fixture/캐시 포함; 고유 Dataset/Policy 개수가 아니다. 본문/영상은 열거나 재생하지 않았다.

## 접근 경로와 실행 환경

| 대상 | 확인한 실제 위치 |
|---|---|
| 새 프로젝트 | `/home/hyeonhee/imitation_learnig_project`; 현재 설계 문서와 빈 제품 디렉터리, 구현 패키지/시험 없음 |
| IDE workspace | [robot_development.code-workspace](/home/hyeonhee/imitation_learnig_project/robot_development.code-workspace)의 `.`와 `../soarm_isaaclab` 두 루트 |
| 기존 코드 P | `/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab` |
| Builder B | `/home/hyeonhee/soarm_isaaclab/real2sim-builder/app` |
| 첫 Baseline v8 | `/home/hyeonhee/soarm_isaaclab/soarm101_lab/outputs/real2sim/environments/scene2_builder/v8` |
| v8이 기록한 Builder Export | `/home/hyeonhee/soarm_isaaclab/real2sim-builder/projects/scene2-final-contact-review-20261014-932c8f2e/exports/scene2-final-contact-review-20261014-932c8f2e-final_contact_review` |
| 공식 Isaac 소스 | `/home/hyeonhee/IsaacLab` 존재. 이번에 전체 저장소나 installed editable 소스를 해시 고정하지 않음 |

| 환경 | Python probe | 설치 METADATA에서 확인한 주요 버전 |
|---|---|---|
| .venv-mujoco | 3.10.12 | mujoco 3.3.7, numpy 2.2.6 |
| .venv-real2sim-ui | 3.11.15 | h5py 3.16.0, numpy 2.4.6, pyqt6 6.11.0 |
| lerobot-arena | 3.11.15 | h5py 3.16.0, isaaclab 0.47.2, isaacsim 5.1.0.0, lerobot 0.4.1, mujoco 3.3.7, numpy 1.26.0, torch 2.7.0+cu128 |
| lerobot | 3.12.13 | lerobot 0.6.1, mujoco 3.8.1, numpy 2.2.6, torch 2.11.0 |

버전은 engine import 없이 dist-info METADATA를 읽고, interpreter는 `-I -S -B -c 'import sys;print(sys.version);print(sys.executable)'`로 확인했다. import/렌더/CUDA/장치/Policy 실행 가능성까지 확인한 것은 아니다. METADATA 경로·hash는 inventory.json의 environments에 있다. 시스템 PATH에서 python은 없고 python3는 `/usr/bin/python3`, ffmpeg는 `/usr/bin/ffmpeg`; Blender는 PATH에 없었다. REAL2SIM_BLENDER override 유무는 증거에 기록했다. Blender 다른 설치 경로·GPU driver 동작은 확인하지 않았다.

[default_python](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/operations.py:52)은 기본 worker로 `lerobot-arena`를 선택한다. 별도 `lerobot`은 LeRobot 0.6.1/MuJoCo 3.8.1로 다르므로 같은 환경으로 취급할 수 없다. Isaac Lab 저장소 버전 표기와 설치 distribution 0.47.2도 서로 다른 식별자다. B01에서 실제 실행 interpreter/설치 소스/설정 identity를 함께 고정해야 한다.

의존성 선언은 Builder `pyproject.toml`의 NumPy/SciPy/Pillow/PyYAML/OpenCV 및 USD/MuJoCo/PyQt6/pytest/trimesh extras, 기존 `setup.py`의 psutil·sim/test/과거 model extras, MuJoCo requirements의 3.3.7 등을 확인했다. 기존 setup의 MiniVLA/qwen extras는 새 플랫폼 의존성 목록으로 복사하지 않는다. 선언 파일이 현재 환경을 완전 고정하는 lockfile이라는 근거는 없다.

## 기능과 새 설계의 대응

아래는 **코드 존재·대표 호출 경로 확인**이다. '재사용'은 알고리즘/계약을 뜻하며 현재 파일과 의존성 전체 복사를 뜻하지 않는다.

| 기능 | 실제 근거·입력 → 처리 → 출력 | 새 책임 / 조사 수준 |
|---|---|---|
| Builder 프로젝트·후보·증거 | [core/project.py](/home/hyeonhee/soarm_isaaclab/real2sim-builder/app/core/project.py), core/scene.py, candidates.py, evidence.py: 입력 자료 → 후보/선택·provenance | builder: project/ui; 정적 확인 |
| scan·재구성 | [import_scan/segment](/home/hyeonhee/soarm_isaaclab/real2sim-builder/app/reconstruction/scan.py:116), pipeline.py run: scan/constraints → 등록·분할·후보 | builder: reconstruction; 렌더/계산 미실행 |
| 카메라·Geometry·물성 | [fit_cameras](/home/hyeonhee/soarm_isaaclab/real2sim-builder/app/calibration/camera.py:41), multipose/depth/robot/physics: 관측·모델 → 정합/잔차/추정 | builder calibration; 실물 정합 인증과 구분 |
| Export·렌더·검증 | [export_package](/home/hyeonhee/soarm_isaaclab/real2sim-builder/app/exporters/package.py:13), verify_package:140, usd/mujoco, blender/backend.py, validation: 후보 → USD/MJCF/Manifest | builder export/rendering/validation; 등록 해시만 재검증 |
| Capture·Real/Sim | [Runtime](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/real2sim/runtime.py:31), hardware.py Leader/Follower, capture_dataset.py SnapshotDataset: 카메라/관절 → snapshot·영상/동기 조작 | robot-operations, policy-evaluation, UI; 장치 미연결 |
| Precision Calibration | [simulation_configuration](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/real2sim/precision.py:45), profile_for_model:326, PrecisionMapper:351, ProfileStore:480 | robot/calibration 및 scene 계약; 프로필 저장/활성화는 별도 부수 효과 |
| Source | [prepare/run](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/native/source.py:87) → native.mujoco/isaac → data.recording.SourceEpisode/data.source → DatasetWriter | simulation-workflows/source·episode-data; 최신 Native 경로 |
| Annotation | [_episode](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/native/annotation.py:98): recorded initial/actions → restore·pre record·post contact/grasp·manual/auto → 새 annotated 자료 | simulation-workflows/annotation; Source runner 재호출 아님 |
| DataGen | [execute](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/unified.py:16), [run_mujoco/run_isaac](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/datagen.py:138), mimic.py/reference: annotated pool → 선택·trajectory·IK·physics·채택 | generation 및 engine datagen; 성공/실패·budget 보존 |
| Task·Reset | [StableGrasp](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/real2sim/workspaces/grasp.py:9), environment.py task_success_details:19, reset.py sample:18, tasks.py validate_reset_pose | tasks 및 엔진 state; Native/legacy 사용자 함수 지원 범위는 다름 |
| Dataset 변환·Merge | [convert_dataset](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/episodes.py:17), learning/datasets.py, workflow/lerobot_merge.py | data/lerobot; 내부 Episode→공식 feature/action 매핑은 B02 대상 |
| 공식 Training | [training_command/train](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/learning/training.py:41) → `lerobot.scripts.lerobot_train` subprocess → checkpoint/log | learning/train; 기본값·rename_map·후처리를 무검증 복사하지 않음 |
| Offline Validation | [evaluate_checkpoint](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/learning/validation.py:47): Dataset/저장 policy → loss/샘플 지표 | learning/validate 독립 stage; Task 성공률 아님 |
| Policy·Sim Eval·Real Eval | [workflow/policy.py](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/policy.py), [evaluate_sim](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/evaluation.py:220), evaluate:471, operations.py execute_request:551 | policy-evaluation, learning/policy; 실물 동작 미검증 |
| Hub | [publish/import_dataset](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/hub.py:16), learning/datasets.py resolve_model:135 | hub 공식 API; 외부 업로드/다운로드 미실행 |
| Curation | [analyze/split/export](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/curation.py:147), curation_ui.py CurationDialog:373 | data/curation·ui/curation; 분포·수동 판단·subset/split/export |
| 저장·재생·Resume | [DatasetWriter](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/data/episodes.py:379), data/datasets.py, data/source.py, workflow/data_resume.py | episode-data/migration; 새 index/파일별 저장은 아직 설계뿐 |

운영 경로와 보호된 `tasks/manager_based/soarm101_lab`의 독립 fixed-scene 예제를 혼동하지 않는다. base_pick_place_teleop_env_cfg.py / so101_mimic_env_cfg.py / so101_mimic_env.py는 기존 보호 대상이며 새 Native Source가 이 예제를 사용한다고 판단하지 않는다. MiniVLA 원본과 과거 Checkpoint는 inventory에 보존했으나 이관/실행 대상에서 제외했다.

## Scene v8·Asset·Calibration inventory

v8은 `so101.workspace/1`, workspace_id=`scene2_builder`, version=8, 실행 status=READY다. Builder/재구성 status는 UNVALIDATED이고 validation_scope는 UNPROMOTED_CANDIDATE_REVIEW다. READY를 실측 정합·접촉·Task 실물 검증 완료로 해석하지 않는다.

실행 자료는 profile.json(좌표/카메라/Geometry), task.json(대상/성공/reset/물성), physics.json, manifest.json, provenance.json, builder/scene.yaml·scene.xml·scene.usd, scene 및 assets다. JSON 원문 값은 inventory.json의 v8_metadata에 저장했다. source_profile_sha/task_sha/robot_asset_sha와 mapper·모델 identity도 포함한다.

| 실제 Object ID | 형상 / dimensions m | T_workspace의 위치 xyz m |
|---|---|---|
| `background_roller` | cylinder / [0.13, 0.13, 0.65] | [-0.279030262, -0.241824527, 0.087808616] |
| `cube_blue` | box / [0.024, 0.024, 0.024] | [0.080555666, -0.296809279, 0.035308616] |
| `cube_green` | box / [0.024, 0.024, 0.024] | [-0.04287924, -0.163324947, 0.035308616] |
| `cube_red` | box / [0.024, 0.024, 0.024] | [-0.048339588, -0.294904216, 0.035308616] |
| `cup_a_visual` | cup_proxy / [0.07, 0.07, 0.065] | [-0.135352645, -0.279995395, 0.055308616] |
| `cup_b_visual` | cup_proxy / [0.07, 0.07, 0.065] | [-0.143579379, -0.190372179, 0.055308616] |
| `marker` | box / [0.15, 0.15, 0.0005] | [0.021093515, -0.22838789, 0.023058616] |
| `marker_edge_back` | box / [0.15, 0.0015, 0.0005] | [0.021093515, -0.30338789, 0.023558616] |
| `marker_edge_front` | box / [0.15, 0.0015, 0.0005] | [0.021093515, -0.15338789, 0.023558616] |
| `marker_edge_left` | box / [0.0015, 0.15, 0.0005] | [-0.053906485, -0.22838789, 0.023558616] |
| `marker_edge_right` | box / [0.0015, 0.15, 0.0005] | [0.096093515, -0.22838789, 0.023558616] |

로봇 베이스는 profile의 T_world, Workspace는 별도 T_world다. 테이블도 별도 T_workspace다. 카메라는 side의 parent=world, wrist의 parent=gripper, 두 영상 640×480, optical convention=`x_right_y_down_z_forward`다. K/distortion·mount·모든 행렬을 증거에 기록했다. 이는 현재 엔진 렌더에서 실제 같은 값이 적용됐다는 실행 증명은 아니다.

작업 블록은 cube_red/cube_blue/cube_green, targets는 cup_a→cup_a_visual와 cup_b→cup_b_visual이며 3×2의 6개 Pick & Place 정의가 있다. marker는 Reset 지지면으로 지정된다. recipe 예시의 red_block은 실제 ID가 아니므로 이관 시 Metadata의 cube_red를 써야 한다.

기존 task.json의 Reset 기본은 **four_anchors**, clearance 0.003m, margin 0.01m, separation 0.005m, jitter 0.02m다. 이번 새 프로젝트는 승인대로 four_anchors를 제외하고 명시 uniform/Fixed를 제공할 계획이다. 원본 기본을 변경하지 않았고, Native JSON의 objects={}는 Builder Pose라는 별도 경로다. 'Recipe 생략=기존 four_anchors'로 일괄 해석하지 않는다.

Asset graph에는 v8의 기준 URDF/USD와 limit/보정 파생 파일, Mesh·Builder visual/collision·texture, 원본 robot assets를 구분해야 한다. manifest robot_asset=`assets/SO101/usd/so101_execution_limits.usda`, identity_robot_asset=`assets/SO101/usd/so101_joint_limits.usda`다. 텍스트 URDF/XML/USDA 참조는 inventory.json asset_text_references에 색인했지만 binary USD의 전체 nested reference를 엔진으로 resolve하지 않았다.

**외부 의존성 누락 주의:** [finger collision loader](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/simulation/mjcf.py:100)가 isaac_matched physics profile에서 사용하는 기존 assets/SO101/mujoco/finger_convex_parts.json은 실제 존재하고 SHA를 확보했지만 v8 Manifest에는 없다. [contact pad loader](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/simulation/workspace_scene.py:92)의 usd_contact_pads.json은 원본과 v8 등록 자료가 존재한다. 패키지 92개 파일 일치만으로 외부 의존성이 모두 포함됐다고 할 수 없다. 새 Export에서 실행 closure에 포함할 대상이다.

Calibration은 outputs/real2sim/joint_calibration 아래 leader profile 7개/reference 1개, follower profile 14개/reference 4개와 active.json이 있다. active 현재 포인터와 v8 Manifest에 고정된 과거 mapper/profile은 서로 다른 근거로 기록했다. 외부 LeRobot calibration cache 후보는 접근 가능한 실제 경로·hash만 증거에 기록했고 활성 장치 검증은 하지 않았다.

v8 profile의 simulation_joint_offsets_rad는 estimated이며 Precision mapping SHA에 결합된다. [simulation_configuration](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/real2sim/precision.py:45)은 urdf_identity / precision_bound_residual / legacy_scene_offsets를 구분한다. [calibrate_simulation_usd](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/real2sim/workspaces/builder.py:309)는 기존 origin 회전 뒤에 axis offset을 곱해 URDF/USD 파생 결과를 쓴다. ProfileStore.save/activate와 장치 command는 관측 변환과 별개이며, 이관 시 적용 공간/순서/횟수를 유지해야 한다. 수치 fixture 확보는 B03이며 이번에 수행하지 않았다.

## UI·CLI·부수 효과

[MainWindow tabs](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/real2sim/ui.py:75)에 Real2Sim Capture, Real/Sim, Workspace Pipeline, Precision Calibration이 있고 [WorkflowPanel](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/ui.py:31)에 Source·Annotation·DataGen·Conversion·Merge·Training·Validation·Dataset/Policy 업로드·Sim/Real 평가 및 Data Curation 진입이 있다. Capture/Calibration/Workflow/Curate의 라벨·선언 callback 색인은 증거에 있다. GUI를 띄워 화면을 시각 비교한 결과는 아니다.

새 UI는 전체 기능을 대응시키고 기존 task/object 체크·중복 설정 폼을 Recipe로 대체한다. Source/Annotation의 현 JSON 편집은 새 YAML 편집으로 연결하되 UI 버퍼 직접 실행을 하지 않는다. 기존 TrainingLossPlot 및 MiniVLA 자체 학습 관리 코드는 그대로 이관하지 않고 공식 로그 조회 방향을 따른다.

| 진입점 | 실제 기능·입력 | 실행 시 주의할 효과 |
|---|---|---|
| Builder `real2sim-builder` / `python -m app.cli` | new/add/import-*/scan/candidate/run/control/status/validate/export/verify/ui; argparse 원문은 증거 | 프로젝트/candidate·요청·렌더/log·Export 쓰기, Blender subprocess |
| scripts/real2sim/real2sim_ui.py | 통합 Qt UI | UI 생성 자체와 장치 connect/start 조작 구분 |
| scripts/real2sim/workflow.py | source-template/annotation-template/task-template/discover, ready/run/worker, import-builder/import-hdf5/migrate, import-hf-* 등 | template도 output 쓰기; ready/discover도 실제 구현의 읽기/resolve 범위를 조사 후 사용할 것 |
| scripts/real2sim/real2sim_sim.py | --backend isaac/mujoco/real/calibration, --workspace | 엔진/장치 생성 및 runtime 상태/log, calibration profile 쓰기 가능 |
| scripts/real2sim/workspace.py | preview/teleop/smoke | 선택에 따라 engine·장치·report/dataset 출력 |
| scripts/teleoperation/*, scripts/mimic/*, scripts/inference/*, scripts/mujoco/check_env.py | 독립 예제·기존 데이터 생성/평가·엔진 점검 | import/AppLauncher/장치/데이터 쓰기 경로가 있어 B00에서 실행하지 않음 |

기존 stage 이름 annotate/sim_eval/validate/hf_dataset/hf_policy와 신규 annotation/simulation_evaluation/offline_validation/hub_*는 공개 설정 변환 대응이 필요하다. 새 YAML로 이름만 바꾸고 과거 기록의 의미를 덮어쓰지 않는다.

확인한 쓰기/외부 효과: native.source.run은 output.mkdir·Leader.connect/activate·DatasetWriter/영상, native.annotation.run은 출력/worker·기록; DatasetWriter는 임시 HDF5·영상 rename/copy·최종 publish; operations는 output root·lock·request·subprocess; RuntimeLauncher는 workspace runtime_startup.log와 process control; Precision ProfileStore는 저장/활성화; training.train은 config/command/checkpoint provenance와 subprocess·조건부 train-end Offline Validation; Hub는 원격 push/pull; Builder는 candidate/렌더/Export를 쓴다. `--help`도 module top-level import를 실행할 수 있어 이번에는 AST만 읽었다.

## 보존·새 설계 차이와 미확정 사항

| ID/항목 | B00에서 확인한 사실 | 후속 확인 / 처리 |
|---|---|---|
| V8-01 | Native pre record/post physics 코드 존재, 엔진별 상태 형식 다름 | B01 actual trace·dtype·센서 update·최초 성공 tick. OPEN 유지 |
| V8-02 | [IsaacAdapter.contacts](/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow/adapters.py:349)는 contact_views 경로 **>0.01 N**, sensor fallback **>1e-4 N**. native.isaac.annotation_contacts:389도 >1e-4 | evaluation.py:334의 표준 Isaac 경로는 rigid_contact_view를 만들어 전달한다. 다른 호출부까지 동일하다고 일반화하지 않으며 실제 force/시점 Baseline은 B01에서 확인. OPEN 유지 |
| 성공 의미 | evaluation.py:376은 post-step update 후 place_success를 기본 success로 사용. adapters.native_success:174는 place AND tracker.completed | 기존 단계별 차이 유지. Annotation/Mimic/User Task 계약을 분리 |
| V8-03 | 기존 sampler와 MuJoCo rollback/penetration 검사가 분리되어 있음 | candidate/engine 적용 실패 예산의 실제 결합은 B01에서 확인. 새 동일 1000회 규칙을 기존 동작으로 단정 금지 |
| V8-04 | native Source의 seed+attempt와 Resume completed count 기준 코드 존재 | 버린 attempt 이력을 전부 복원한다고 주장 금지. B02 stage별 RNG/partition 대조 |
| CAL-01/02, ROBOT-01/02 | 프로필/active/mapper·raw/native/model·장치 connect/activate/send/stop 수명 코드 존재 | B03 실제 signature/단위·보정 branch·camera 동기·실물 제한/중지 fixture. OPEN 유지 |
| DATA-01~04 | 기존 DatasetWriter는 **단일 Common HDF5 내 demo 그룹 commit**, close 시 bundle publish | 새 Episode별 HDF5/index는 저장 방식 변경. compatibility/flush/취소·부하 시험 전 채택 완료 금지 |
| 공식 Training | 기존 learning.training.train은 validation 입력이 있으면 학습 종료 후 별도 검증을 자동 실행 | 신규 합의는 독립 명시 stage이므로 자동 호출 이관 제외; 공식 Trainer 수학은 변경하지 않음 |
| 공유 모듈의 MiniVLA 결합 | operations.py:19는 과거 MODEL_ROOT를 minivla.config에서 import | 기능만 재배치하고 해당 import/로더/과거 graph·학습 관리는 새 Workbench에 가져오지 않음 |
| 외부 의존성 | Finger collision JSON·서로 다른 worker 환경, PATH Blender 부재 | package closure·정확한 interpreter/버전/렌더 환경은 구현 전 고정 |
| 과거 보고서 | Native Source Phase1/1.5·Native Integration REPORT는 현재 존재, Annotation Phase2·scene2_final_contact_refinement REPORT는 문서 지정 경로에 없음 | 현재 없는 경로를 실행 검증 완료 근거로 인용하지 않음. 다른 위치 탐색/원자료 대조는 후속 확인 |

기존 구현의 수식·threshold·실행 시점을 이번에 바꾼 것은 없다. 위 표의 변경은 이미 합의한 신규 목표와 기존 사실의 대응이다. Geometry 접촉 배치·새 Task registry·YAML·Episode index·self-contained Scene package는 아직 구현되지 않았다.

## 검증 증거와 재확인

| 산출물 | 내용 |
|---|---|
| [inventory.json](evidence/b00/inventory.json) | 원본 파일 stat·symlink, AST symbol/import/CLI/UI/효과 후보, 환경 METADATA, v8 원문/Export Manifest·보정 경로·자료 수·보고서 접근 상태 |
| [file-hashes.json](evidence/b00/file-hashes.json) | SHA-256 선택 기준·보호 루트·파일별 크기/hash |
| [verification.json](evidence/b00/verification.json) | 조사 전후 stat/선택 해시·Manifest·문서 링크/명세 대응 점검 결과와 실행하지 않은 검증 |

조사 도구는 표준 Python os.walk/lstat/hashlib/json/ast/XML와 safe YAML parser, 선택 interpreter의 sys.version probe다. 기존 앱 모듈을 import하거나 기존 CLI/pytest·GUI·시뮬레이터·로봇·Hub를 실행하지 않았다. 증거 JSON은 코드 내용을 저장한 복사본이 아니라 조사값/정적 선언 색인이며, token/password·환경변수 전체를 수집하지 않았다.

저장된 해시를 재확인하는 읽기 전용 명령(새 프로젝트 루트 기준):

```bash
python3 - <<'PY_CHECK'
import hashlib, json
from pathlib import Path
m = json.loads(Path('docs/evidence/b00/file-hashes.json').read_text())
root = Path(m['root'])
for item in m['entries']:
    h = hashlib.sha256()
    with (root / item['path']).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    assert h.hexdigest() == item['sha256'], item['path']
print('selected original file hashes match')
PY_CHECK
```

대형 Dataset/Checkpoint/미디어 전체 payload, 제외 디렉터리, 선택되지 않은 외부 symlink target은 byte 전체 보존을 검증하지 않았다. stat/hash 대조 구간은 최초 inventory snapshot 이후이며, 그 이전 명령도 읽기 전용이지만 비교 가능한 before snapshot은 없다. atime·디렉터리 mtime까지 완전 불변이라고 주장하지 않는다. 환경의 .git은 접근 제한된 placeholder이며 git status가 저장소를 찾지 못해 commit/diff를 만들지 않았다. 기존 프로젝트에 git init/자동 commit을 하지 않았다.

이번 변경은 조사 문서/증거이므로 런타임 build/typecheck/pytest는 해당 없음이다. 원본 기존 시험 파일을 AST로 색인한 것과 시험 실행은 구분한다. B00 완료 근거는 inventory/기능 대응/미확정/부수 효과/보존 대조이며, 다음 작업 완료 체크는 하지 않는다.

## 내가 직접 확인할 것

1. 이 보고서의 기능 대응표·외부 Finger Collision·환경 차이·누락 보고서 항목을 검토한다. 이번 B00 확인을 위해 UI/CLI나 로봇을 실행할 필요는 없다.
2. native.source.prepare/run, native.annotation._episode, workflow.adapters.IsaacAdapter.contacts, data.episodes.DatasetWriter를 열어 보존할 호출·저장 경계를 확인한다.
3. verification.json에서 manifest/hash/stat 대조와 미실행 목록을 확인한다. B00만 완료이고 나머지 작업/OPEN 항목은 미완료 상태여야 한다.
