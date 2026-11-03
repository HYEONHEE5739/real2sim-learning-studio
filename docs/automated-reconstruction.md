# Automated Real2Sim Reconstruction

2026-11-03. 사용자 제공 구현 지시서(2026-11-03)의 Phase 0–7을 구현 기준으로 사용한다. 시작 브랜치는 `workflow-restoration`, HEAD는 `5030b48487271b8ec3178467f7141143d4ee0522`였고 작업 트리는 깨끗했다. 원격 Push/Merge는 이 작업에 포함하지 않는다. 기존 Scene/촬영/Calibration/모델/환경은 원본으로 보존한다.

## Phase 0 — 조사와 경계

기존 Builder 전체 회귀: `bash docs/evidence/builder/run_tests.sh real2sim_builder/tests -q --tb=short --junitxml=/tmp/reconstruction-baseline.xml`, **104 passed**. 이는 신규 AI 모델/자동 재구성 검증이 아니다. 로컬 SAM `sam31`은 Python 3.12, DA3 `da3`는 별도 Conda 환경이다. RTX 4060 Laptop 8GB가 있으며 설치 환경과 모델을 재설치하지 않는다. 실제 interpreter/checkpoint 경로는 실행 구성으로 전달하고 제품 코드에 사용자 절대 경로를 넣지 않는다.

### 함수 단위 소유권과 호출 방향

| 기존 파일 | 주요 함수 / 연결 | 이번 경계 |
|---|---|---|
| `project.py` | `Project.create/save_scene/signature/checkpoint`, `clone_project` → Scene/Evidence/Candidate | lifecycle·lock·원본 보호 유지 |
| `evidence.py` | `add_image/add_video/extract_videos/import_metadata/import_robot/asset_importer/copy_input` | RGB/측정/Robot 입력, GLB 거부 |
| `capture.py` | `load_session/load_snapshots/import_snapshots/import_paired`, `observation_scene` → `link_transforms` | 촬영 시각·mapping·원본 SHA·measured q 유지 |
| `observations.py` | `registered_images/propose_observations/commit_observation_proposals/annotation_evidence` | 고정·Wrist·외부 관측 구분, Candidate-local 파생 자료 |
| `initialization.py` | `apply_geometry_constraints/constrain`, Scan `initialize` | 실측 pair projection 유지, Scan 초기화 삭제, 실측 Geometry 초기화 |
| `calibration/camera.py` | `point_world/project_point/fit_cameras/fit_geometry/landmark_metrics` | optical(+Z forward)·원 해상도 기준 유지 |
| `calibration/geometry.py` | `link_transforms/reference_geometry/reference_model/fit/bootstrap/assess_camera/fit_depth_geometry` | URDF/FK·metric anchor·기존 Baseline 유지, Scan 조건 제거 |
| `calibration/joint.py` | `fit_joint_scene/_support/_posed` → measured-q `observation_scene`, robust least squares | 기존 Landmark Baseline, 외부 등록 View 허용 |
| `candidate.py` | `Candidate.create/save/edit/fit/evaluate/promote` | 새 알고리즘 결과도 같은 Candidate와 보호 검사 사용 |
| `scene.py` | `validate/value/checked_value/frame_world/world_pose/camera_calibration_signature` | 단위·provenance·measured/calibrated 보호, 명시 legacy 진단 |
| `export.py` | `export_revision/copy_native_asset/verify_native_closure/verify_package` → USD/MJCF | 기존 immutable Revision/Manifest·native 자산·Articulation 보존 |
| `validation.py` | `compare/mask_metrics/object_metrics/check/paired_identity` | 기존 overlay/수치·physics와 Task 성공 분리 |
| `reconstruction.py` | `analyze/run/validate_scene/diagnose/coverage` | Scene 단계 조율, 신규 자동 경로 연결; 새 Agent/Manager 없음 |
| `cli.py`, `ui.py` | `main`, `Window.add/start/start_worker/export_selected` | Scan 명령/전용 UI 삭제, 기존 화면·명령 확장 |
| Workbench `scene_preparation.py` | `save_inputs/scene_details/source_inputs` | 입력·측정 등록과 기존 실행 Package 선택 유지 |
| Workbench `ui/scene_inputs.py`, `session_page.py` | 자료·메모 저장 → Backend operations → Builder | 기존 Scene Prepare 확장; SDK/AI 모델은 GUI에서 소유하지 않음 |
| Workbench Source/Annotation/DataGen | `prepare_recipe` → 선택 Scene Package → concrete engine runners | 공개 Scene/Revision/관절·Dataset 계약 변경 없음 |

GLB 의존성은 `scan.py` → `initialization.initialize`/`reconstruction` → CLI/UI와 Workbench Input에 집중돼 있다. 카메라 signature, object-scope 편집, joint fit, validation에도 `scan_initialization` 조건이 있다. `trimesh`는 OBJ/STL/Robot 일반 형상·Exporter에서도 쓰이므로 유지한다. 과거 Scan Project는 inspect로 읽을 수 있지만 신규 편집/정합/Export는 명시 `LEGACY_UNSUPPORTED`로 거부한다. 원본을 변환하거나 삭제하지 않는다.

### 구현 순서와 데이터 경계

1. GLB Import/Registration/전용 코드·시험 제거. 실측 Geometry constraint는 독립 Candidate API/CLI로 유지.
2. 입력 Image ID/SHA·layout·물리 camera ID·type·resolution·registration 상태를 기록. 고정 Camera 공유, Wrist는 실제 q/FK, External은 view별 pose. 등록 불가 View는 `UNREGISTERED/REFERENCE_ONLY`.
3. Candidate의 파생 폴더에서 SAM → 종료 → DA3를 순차 실행. 각 interpreter·checkpoint·parameters·입력/Calibration SHA를 cache key에 결합. NPZ/PNG/JSON만 출력. 예측은 estimated/derived이며 measured가 아니다.
4. 실측 primitive/기존 CAD와 Robot에서 Candidate 구성. 가시 depth를 metric anchor에 정렬하고 점군으로 역투영. 크기·q·검증된 Camera/Robot은 고정.
5. 기존 Landmark / Trimmed ICP+Mask / Hybrid를 같은 입력·held-out View에서 비교. 선택 근거가 부족하면 기본 Backend를 검증 완료로 표시하지 않음.
6. 기존 Collision/Revision과 실제 MuJoCo/Isaac physics 검사를 연결. 렌더 성공을 Physics-Ready/Task 성공으로 승격하지 않음.
7. Scene Prepare/Builder의 기존 입력·상태·비교·Export UI에 연결. 일반 Scene 제작에 Codex의 좌표 수정/Raw JSON 입력을 요구하지 않음.

각 단계의 실패는 원본을 보존하고 해당 파생 결과만 미완료로 남긴다. Metric Anchor·같은 정적 배치·Wrist q/Calibration이 없는 경우 `NEEDS_MORE_DATA`로 멈춘다. 실제 검증하지 않은 단계/Backend를 완료로 기록하지 않는다.

### 공식 소스 조사

- [SimFoundry pipeline](https://github.com/NVlabs/SimFoundry/blob/main/scripts/pipeline/README.md), A_reconstruction의 depth/plane/world/decompose/mesh/pose/compile/physics 단계: 단계 분리·캐시·시각/충돌 분리만 참고. Apache-2.0. OmniGibson과 생성형 Mesh 경로는 도입하지 않는다.
- [RoboSkills track](https://github.com/openrobokit/roboskills/blob/main/src/roboskills/workflows/real2sim/track.py), [align](https://github.com/openrobokit/roboskills/blob/main/src/roboskills/workflows/real2sim/align.py): 최근접 대응 trimming·rigid fitting·known geometry scale 원리를 정적 공유 World 문제로 재구현. MIT. 프레임별 추적·관측 부재 시 scale=1 fallback은 채택하지 않는다.
- [DA3 API](https://github.com/ByteDance-Seed/Depth-Anything-3/blob/main/src/depth_anything_3/api.py): 설치 소스의 `DepthAnything3.inference`/입력 처리/mini_npz를 우선 확인. 코드 Apache-2.0; 모델은 설치된 로컬 snapshot으로만 실행한다.
- [Ultralytics SAM predictor](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/models/sam/predict.py), [Meta SAM3 license](https://github.com/facebookresearch/sam3/blob/main/LICENSE): 기존 외부 Runtime만 실행하며 코드·모델을 재배포하지 않는다. 설치 Ultralytics의 실제 SAM3SemanticPredictor API를 확인한다. SAM 모델의 별도 license와 Ultralytics license를 혼동하지 않는다.
- [RoboSimStudio](https://github.com/robosimstudio/robosimstudio): Apache-2.0. Physics 검증/실패 원인 구분만 참고하며 Agent 실행 구조를 가져오지 않는다.

외부 파일은 조사용 `/tmp/real2sim-reconstruction-reference/`에만 보관한다. 실제 조회 Commit/license 목록과 함수 호출 지도는 로컬 조사 기록이며 제품에 외부 소스를 대량 복사하지 않는다.

## 단계별 구현·검증 기록

아래에 각 Phase의 변경, 명령, 결과와 다음 단계 제한을 추가한다. 전체 목표가 완료됐다는 뜻은 아니다.

### Phase 1 — GLB 삭제와 실측 명령

`scan.py`와 Scan initialize/CLI/UI/Workbench 입력 경로를 삭제했다. 단순 버튼 숨김이 아니다. Scan 전용 시험은 폐기한 기능과 함께 제거하고, 원본 inspect·GLB/glTF 거부·입력 batch 보호·실측 constraint 명령 시험으로 교체했다. `calibration/registration.py`에 일반 rigid/similarity/plane 수치 계산을 분리했다. `candidate PROJECT constrain NAME --options FILE`은 기존 실측 pair projection을 호출한다. 기존 OBJ/STL·Robot native closure·Container/Compound exporter는 유지한다.

실행: `bash docs/evidence/builder/run_tests.sh real2sim_builder/tests -q --tb=short --junitxml=/tmp/reconstruction-phase1.xml` → **106 passed**. GLB 거부 6개 RED→GREEN과 원본 보존 확인은 `/tmp/reconstruction-phase1-{red,green}.*`에 남겼다. 기존 Scan Project를 자동 변환하지 않는다.

### Phase 2 — 사진·영상·Camera 등록

`observations.register_image/register_sources/input_images/register_views`를 추가했다. Camera type/ID·배치·해상도·SHA·split·영상 group·원/파생 관계를 유지한다. External은 알려진 K와 실측 World Anchor의 PnP, Side는 기존 검증된 고정 Calibration, Wrist는 기존 Mount와 실제 q/FK를 사용한다. 불명확한 일반 사진에는 q를 만들지 않는다.

Wrist 별도 사진 기록은 모델/Mapping SHA·rad/order·image/joint 시각을 요구한다. `observation_scene`에 legacy Session ID가 없는 등록 Wrist도 실제 q/FK를 적용하도록 수정하고 별도 회귀로 확인했다. 수동 Precision을 physical_verified로 승격하지 않으며, 수치 Mapping 검사를 물리 인증과 구분한다. 과거 공식 Capture metadata를 재등록으로 덮어쓰지 않는다. Camera/원본 record가 바뀌면 등록·metric cloud가 stale로 판정된다.

외부 영상은 기존 `extract_videos`를 선택 영상에 재사용하고 최대 12개 프레임·영상 SHA·실제 timestamp·frame index를 등록한다. 전체 영상을 같은 group으로 묶어 train/validation 누출을 거부한다. 새 Wrist 영상의 일반 q 자동 동기화는 구현하지 않았다. 모터·Camera 하드웨어 연결은 없다.

Phase 2 전체 Builder **110 passed**(`/tmp/reconstruction-phase2.xml`). 재개 후 추가 등록/Wrist/영상 시험도 통과했다. 실제 q 대신 가상 값을 넣은 시험 fixture는 실물 Calibration 증거가 아니다.

### Phase 3 — 실제 SAM/DA3 Worker와 캐시

`inference.py`는 기존 interpreter/checkpoint를 설정에서 읽고 SAM 종료 → DA3 순서로 실행한다. child별 timeout·Project Stop·소유 process group 정리를 사용한다. 별도 process로 비관련 프로세스를 유지하는 취소 시험을 통과했다. 모델/SDK 소스·설치 환경을 수정하거나 패키지를 설치하지 않았다.

SAM은 Object/image별 Prompt/Box·모델 SHA·Runtime/API·설정 digest를 캐시하며 유사 컵의 복수 Mask를 AMBIGUOUS로 남긴다. DA3는 ordered batch·Calibration·모델/설정을 캐시한다. 기존 Python API로 depth/conf/K/world-to-camera와 실제 input processor의 resize/crop을 기록한다. GLB/gsplat/3DGS는 사용하지 않는다. EXIF는 원본을 보존한 Candidate-local upright RGB로 통일한다.

실제 실행은 기존 `pickplace-colorblock-b7a5592b`의 **static_001 Side/Wrist 각 1장**이다. SAM 요청은 각 사진의 red cube/paper cup으로 총 4개였다. Side red cube: Mask 1개, Side cup: Mask 2개/AMBIGUOUS, Wrist의 두 query: NOT_FOUND. DA3는 양 사진의 210×280 depth를 생성했다. 검출되지 않은 물체·식별을 만들어 채우지 않았다. 초기에 DA3 namespace package의 `spec.origin=None` probe 실패를 기록하고 `submodule_search_locations` 처리 후 재실행했다.

재개 후 실제 pipeline도 실행했고 **NEEDS_MORE_DATA**였다. 검증된 Camera/가시 metric depth Anchor가 부족해 Pose/새 Scene을 발명하지 않았다. Project/Current/Evidence/원 RGB **29개 SHA 불변**을 확인했다. 같은 입력 재실행에서 SAM/DA3 job log mtime이 불변이므로 모델 forward 없이 캐시가 재사용됐다. 마지막 child 종료 후 GPU 사용량은 약 621MiB 표본이었다(전체 성능 benchmark가 아님).

실행 harness/log: `/tmp/reconstruction-runtime/{check_pipeline.py,check_cache.py,final-runtime.log,pipeline-summary.json}`. 후보와 모델 산출물은 기존 Project의 `scratch/agent/auto_ai_runtime_20261103/`에 있다. 이 폴더는 승인된 최신 Scene/새 Export가 아니다. 전체 과거 자산·SDK corpus를 전수 hash했다고 주장하지 않는다.

### Phase 4 — 측정 Geometry와 관측 점군

`initialization.measured_geometry`가 Box/Cylinder/Sphere/Open Container를 명시 실측으로 구성한다. 기존 측정 치수·Robot을 바꾸지 않고 새 Pose는 unknown이다. 보이지 않는 벽/치수/물성을 AI로 채우지 않는다. 복잡한 CAD는 기존 OBJ/STL 경로다.

`inference.build_point_clouds`는 등록된 Camera와 실제 보드의 visible World-to-pixel Anchor로 Depth 비율을 추정한다. 근거가 없으면 scale=1로 진행하지 않는다. Mask boundary/invalid depth/confidence를 걸러 가시 점만 World 미터로 변환하며 결과 provenance는 derived다. Candidate-local NPZ/Mask·단위·SHA·Camera/원본 record·scale 근거를 `reconstruction_observations`에 보존한다. Project signature와 새 Export closure가 이 파일을 포함한다.

실측 크기 보존·열린 컵·unknown pose·실측 컵 pair 거리 보존·RGB/depth pixel 변환·EXIF·metric anchor·실제 NPZ/PNG 연결·원본 불변 시험을 통과했다. 현재 실제 촬영의 metric 점군 생성은 부족한 Anchor/Calibration 때문에 미완료다. Side/Wrist의 일반 자동 Calibration·새 Robot/Base 자동 등록까지 구현됐다는 뜻은 아니다.

### Phase 5 — ICP/Mask/Hybrid 초안 비교, 부분 구현

`calibration/hybrid.py`에 known-size surface sampling, multi-start rigid trimmed ICP, degeneracy/coverage/대칭 대안 보고를 구현했다. 물체 크기·Robot·q는 바꾸지 않는다. 명시 수평 Support 또는 실측 same-support pair의 upright 축을 보존한다. 기존 측정 pair projection을 정합에 적용한다.

Mask 보정은 실제 MuJoCo segmentation을 사용한다. Body pose만 갱신한 마스크가 새로 compile한 렌더와 같은지 시험했다. Fragment에는 미관측 부분을 배경으로 강제하지 않고, Mask coverage만으로 optical depth가 떠다니지 않도록 robust depth surface 항을 함께 사용한다. 실제 MuJoCo를 쓰는 합성 fixture에서 Mask 개선·크기 보존을 확인했다. 실물 사진 fitting 정확도 검증이 아니다. held-out cloud는 초기화/ICP/Mask loss에 사용하지 않는다.

`compare_backends`는 같은 입력에서 A landmark, B ICP-mask, C hybrid 초안과 공통 camera/object별 RGB·Mask·가시 표면 잔차 및 overlay를 저장한다. **현재 이 통합 비교의 metric Camera는 고정이다.** Camera를 바꾼 뒤 이전 World cloud를 그대로 쓰지 않기 위한 제한이며, raw depth를 재투영하는 Camera/depth bundle adjustment는 미구현이다. 기존 shared Camera/Mount landmark fitter는 별도 API로 남아 있다. 반복 초기값의 독립 수렴률·사람 수정 횟수 benchmark도 완료하지 않았다.

사용자 답변으로 독립 validation/external 사진이 없음을 확인했다. 현재 Project에는 26장이 모두 train이다. 따라서 **winner/default_backend=null**, 실제 mm 위치·회전 정확도와 최종 기본 Backend 선정은 미검증이다. Hybrid는 provisional 요청값일 뿐 우승한 방식이 아니다. 실제 자료 없이 Phase 5 완료를 선언하지 않는다.

### Phase 6 — 물리 probe와 Export, 부분 구현

`validation.physics_probe`는 기존 MJCF collision exporter로 실제 중력/접촉 Step을 진행한다. unknown mass/friction을 임의 default로 채우지 않는다. 시험 fixture에서 **250 Step**·finite state·contact를 확인했다. 기존 USD/MJCF·Container/Compound/자산 closure 회귀와 파생 NPZ/Mask의 review Export 소유권을 확인했다.

**Isaac/PhysX 실제 Step, Robot Articulation 충돌, 컵에 블록을 떨어뜨리는 독립 검증 및 실측 물성 검증은 미완료**다. 보고서에 NOT_TESTED로 남기고 PHYSICS_READY/Task 성공을 반환하지 않는다. 새 실물 구동·새 학습·정책 rollout은 하지 않았다. 실제 Scene Package를 자동 게시하거나 기존 최신 Revision을 바꾸지 않았다.

### Phase 7 — UI·CLI 연결, 부분 구현

새 독립 앱 대신 `ui_reconstruction.ReconstructionDialog`를 기존 Builder Start 및 Scene Prepare Auto Reconstruction에서 공유한다. 사진/영상 등록, Object 실측 표, 기존 환경 경로, 보드 코너 지정, Mask 후보/수정 PNG, 상태/추가 자료, 중단, 명시 미검증 초안 Export를 연결했다. 현재 설정은 Project의 `input/reconstruction.yaml`이며 실행 구성은 Candidate-local `reconstruction-config.yaml`에 고정하고 signature/Export closure에 결합한다. Mask 선택 같은 실행 설정 수정으로 Current의 원본 Evidence를 재등록하거나 Candidate base를 무단 rebase하지 않는다. 전체 실행은 기존 Project lock을 유지하고 중첩된 Candidate 작업만 같은 실행 context에서 허용하며 다른 thread/process는 거부한다.

Qt UI에 모델·MuJoCo·USD·SDK를 import하지 않는 시험과 실제 Qt→CLI 구성 저장→NEEDS_MORE_DATA 반환을 확인했다. 재실행이 실패하면 이전 성공/자료 부족 보고서를 다시 표시하지 않는 RED→GREEN도 확인했다. 일반 사용자에게 Raw JSON/4×4/ICP 수치 작성을 요구하지 않는다. 복잡한 Object association 편집, 초기 Camera/Robot/Base Calibration 전체 마법사, 일반 물체별 자동 실패 수정·최종 물리 승인까지 이어지는 무인 E2E는 미완료다. 기존 Teleop/Annotation/Mimic/LeRobot 엔진이나 Dataset 계약은 수정하지 않았다.

### 현재 검증·보존 상태

주요 RED→GREEN은 `/tmp/reconstruction-{phase1,phase2,phase3,phase4,render-update,mask-fit,physics-probe,wrist-binding}*`와 각 새 pytest case다. 통합 명령은 다음과 같다.

```bash
bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests \
  robot_learning_workbench/tests/test_scene_note_template.py \
  robot_learning_workbench/tests/test_device_setup_ui.py \
  robot_learning_workbench/tests/test_scene_observation.py \
  robot_learning_workbench/tests/test_real_sim_page.py \
  -q --tb=short --junitxml=/tmp/reconstruction-final-release.xml
```

최종 관련 회귀는 **285 passed / 1 failed / skipped 0**(286개, `/tmp/reconstruction-final-release.xml`)다. 실패 1개는 아래 기준 HEAD의 기존 UI 기대값 문제다. 수정 소스 34개는 bytecode를 쓰지 않고 compile 검사했으며 `git diff --check`도 통과했다. 최종 JUnit/로그·실제 모델 결과·소스 SHA는 Git 제외 경로 `workbench_runs/reconstruction_implementation_20261103/`에 약 50KB로 보관했다. 모델 가중치·전체 임시 출력은 복사하지 않았다. 기존 `test_real_sim_has_scene_engine_and_observe_capture_stop_without_authoring_or_teleop`는 기대 `Real/Sim 연결`과 기준 HEAD의 실제 `Real/Sim 연결 · Teleop`이 다른 실패다. 기준 커밋의 해당 제품 코드와 현재 코드가 같은 것을 확인했으며 이번 작업에서 테스트/제품 버튼을 바꿔 통과시키지 않는다. 다른 전체 Workbench/학습/Task E2E를 새로 실행했다고 주장하지 않는다.

원본 Scene/실측/촬영·설치 환경을 삭제/변환하지 않았다. `.gitignore`는 유지하고 Workspace/모델/Runtime/실험 자료를 Git에 추가하지 않는다. HEAD/main 변경·Commit·Push·Merge는 수행하지 않았다. 현재 작업은 미완료 항목이 있는 로컬 소스/문서 변경으로 유지한다.
