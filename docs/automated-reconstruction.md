# Automated Real2Sim Reconstruction

최신 후속 변경은 [다중 시점 재설계 기록](real2sim-multiview-architecture.md)의 G절(2026-11-06)을 따른다. 공동 렌더 정합에서 train 관측의 기준·Wrist 움직임·원 pixel/depth·형상 대칭을 확인해 변수를 자동 선택하고, Geometry 뒤에 Appearance를 조정한다. 관측 부족 사유와 추가 촬영 안내를 보고서 및 초안 준비 판정에 연결했다. 아래 Phase 기록은 각 시점의 구현·검증 이력이며, 실제 사진 전체 E2E가 완료됐다는 의미는 아니다.

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

## 2026-11-04 — Codex/Blender·물체 USDA·Camera/Depth 공동 정합 확장

사용자 제공 「자동 Scene 제작·정합 시스템 개선」 지시서를 적용했다. 브랜치는 `feat/auto-real2sim`, 기준 HEAD는 `eb1a639ba1dc8cb4870c5f7609fb1d4d5333797a`다. 시작 시 남아 있던 Scene Prepare 연결 버튼 수정 3개 파일은 보존했다. 이 작업에서 Commit/Push/Merge·원본 Scene 교체·SDK/모델 설치·실물 연결/모터 구동은 하지 않았다. 앞 절의 결과는 당시 기록이며 아래는 새 실행 결과다.

### 변경과 실제 호출

| 경계 | 구현 |
|---|---|
| `automation.reconstruct` | SAM→DA3를 먼저 수행 → 기록 Robot/FK 참조 → Camera 초기 추정 → 실측 보존·Asset 재사용 → Codex 작업자료 → Pose 초기화 → 공동 정합/렌더 → 물리 진단 |
| `initialization.measured_geometry` | 실측 치수는 유지하되 신규 Primitive **Visual 생성은 제거**. 신규 외형은 unknown으로 두고 USDA를 기다림. 기존 Primitive/명시 Collision/Robot은 유지 |
| `object_assets` | 실제 OpenUSD 파싱, m/+Z·identity root·defaultPrim·Mesh/UV/Texture·상대 Closure·SHA 검사. 원본은 보존하고 불변 Library 버전과 OBJ/PNG 파생물 등록 |
| `Candidate.edit`/`editing` | 같은 Asset의 독립 Instance 추가/복제/제거·Pose 변경. ID별 측정 보호. 자산 외형/재질 변경은 새 Asset 버전으로 연결하며 기존 물체에 전파하지 않음 |
| `rendering.author_object_assets` | 기존 Blender Worker에 선택 물체 작업 추가. `bpy.ops.wm.usd_export`, 별도 convex Collision, `source.blend`·Texture 보존. bwrap 읽기 전용 filesystem/기본 `/dev`·명시 출력·network off |
| `automation.modeling_tasks/run_codex_modeling` | 원 사진/SAM Mask/Crop/Depth·메모·실측/보호 물체를 작업자료로 작성. 기존 Codex 세션 또는 명시 `codex exec` 사용. 객체가 미정이면 메모·사진의 Object/역할/SAM query 제안만 만들며 치수/물성을 발명하지 않음 |
| `observations.predict_views` | DA3 K를 원 RGB pixel로 복원. 공통 이미지 Depth로 Batch similarity 정렬. 검증된 Camera baseline 또는 측정 q/FK hand-eye로 Scale/Mount 초기화. 필요하면 링크별 운동 가설을 비교하며 fixed-link gauge를 보고 |
| `calibration.joint.fit_depth_bundle` | Side Pose·공유 Wrist Mount·External view·Object Pose와 선택적 K/Base/Depth Scale을 bounded least squares로 정합. raw ray를 매 평가마다 재투영하고 새 World cloud를 게시. q/URDF·실측/검증 데이터는 고정 |
| `automation.refit_pairs` | 기존 완료 Pair Reader/Import → 해당 촬영 배치의 Candidate → 같은 분석/정합. 저장 Sim은 역사 Runtime 진단. 측정 q와 Sim tracking 차이를 별도로 보존 |
| USD/MJCF·`validation.physics_probe` | Isaac은 USDA Reference, MuJoCo는 같은 자산의 UV Mesh·Texture·convex piece를 사용. Builder도 기존 Workbench와 동일한 `multiccd`를 사용. 실제 MuJoCo/PhysX probe와 미검증 상태를 분리 |
| 기존 Qt Dialog | Scene Prepare 배치 유지. 촬영 배치 선택·USDA 목록/등록·Codex 작업자료/명시 실행 추가. 보드 코너는 선택적 고급 진단으로 이동. Real/Sim 중단 후 동일 Dialog의 재정합 경로 제공 |

기존 `blender-build/author/sync`, Candidate scope·측정 보호·immutable Revision·Manifest·Native Robot/Articulation·Teleop·Precision·Source/Annotation/DataGen/Mimic/LeRobot·학습 실행 계약은 유지한다. 새 독립 앱/Agent Framework/Manager/학습 Serializer는 추가하지 않았다. 자산 단위 책임이 별개이므로 `object_assets.py` 한 모듈을 추가했으며 별도 버전 관리 시스템을 만들지 않았다.

### USDA 소유권과 Codex 실행

`input/object_assets/<asset_id>/<version>/manifest.json`은 entry/defaultPrim·단위·원점·치수 출처·Visual/Collision·Blender 원본·종속 파일 SHA를 기록한다. 원 USDA closure를 소유 복사하고 변경된 Physics MeshCollision markup은 파생본에만 적용한다. Scene의 `object_asset.entry_asset`가 해당 USDA를 참조하고 Pose는 기존 Scene에만 둔다. Source Mesh/Texture bytes는 Instance 복제마다 복사하지 않는다. Scene에서 제거해도 Library·이전 Export는 남는다. 다른 Project는 원 USDA entry를 자기 Library에 등록해 재사용한다.

Blender 설치는 **5.2.2 LTS**다. 실제 RNA의 USD Export 옵션을 조회하고 새 `export_textures_mode`와 기존 버전의 `export_textures` 차이를 처리했다. 일반 Visual은 PreviewSurface/이미지·UV 범위이며 절차적/지원되지 않는 Material 연결은 bake가 필요하다고 명시한다. 임의 Visual을 Collision으로 간주하지 않는다. 열린 컵은 바닥/벽 convex piece로 분리한다. Object Asset의 중첩 RigidBody/Articulation은 Scene/Robot 물리 소유권과 충돌하므로 거부한다.

설치된 공식 Codex CLI는 `0.164.0-alpha.11.1`이며 `exec`, workspace-write, 임시 비저장 세션, JSON schema 출력을 실제 help에서 확인했다. `modeling-run`은 원 저장소 밖 작업공간과 복사한 입력으로만 시작하고, 추가 writable root를 주지 않는다. 코드 생성 후 Blender는 별도 bwrap에서 실행한다. 사용자 시작 없이 재구성이 Codex를 숨겨서 호출하지 않는다. **실제 원격 Codex 추론은 이번에 실행하지 않았다.** CLI 경계는 Fake 응답으로 정상/분석·출력 경로를 시험했고, 이후 Blender/USD 검사는 실제였다. 기존 Codex 대화에서 `modeling/CODEX_MODELING.md`를 읽는 경로도 유지한다.

### Camera·원 관측·초안 상태

수동 K/Extrinsic/Mount/보드 pixel은 일반 흐름의 필수 조건이 아니다. DA3 초기값은 **PREDICTED**, 수치 보정은 **OPTIMIZED**, 식별 불가는 **UNRESOLVED**다. 충분한 근거 없이 VERIFIED/measured로 승격하지 않는다. Robot-base 좌표 gauge는 테이블 World의 실측이 아니다. 같은 사진을 겹쳐 쓰는 DA3 batch도 실제 Depth 대응으로 정렬하며 비연결 batch를 합치지 않는다. Batch 1은 공통 3D 대응이 없으면 상대 분리 상태를 유지한다.

새 Scene의 미결합 Snapshot/Pair에서도 촬영 배치·단위·모델/Mapping SHA를 보존해 자동 분석이 찾을 수 있도록 수정했다. 원 촬영은 그대로 두고 기록 URDF/FK를 Candidate 참조로 재사용한다. Camera 등록이 blur/skew/정지 품질 제외를 지우지 않도록 한다. Real/Sim tracking 차이는 q를 수정해 숨기지 않는다.

Geometry가 준비되면 `DRAFT_READY`와 검토용 Candidate를 반환할 수 있다. 이는 실행 Robot/Task 승인이나 `PHYSICS_READY`가 아니다. 미완료 모델링은 `WAITING_FOR_CODEX`, 의미 해석이 먼저 필요하면 `WAITING_FOR_CODEX_ANALYSIS`, Scale/관측 부족은 `NEEDS_MORE_DATA`로 남긴다. 기존 Current·Revision은 자동 승격/교체하지 않는다.

### 실행과 검증

최종 관련 회귀 명령:

```bash
REAL2SIM_BLENDER=/path/to/existing/blender bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests \
  robot_learning_workbench/tests/test_scene_note_template.py \
  robot_learning_workbench/tests/test_scene_observation.py \
  robot_learning_workbench/tests/test_device_setup_ui.py \
  robot_learning_workbench/tests/test_capture_connection_ready.py \
  robot_learning_workbench/tests/test_session_snapshots.py \
  robot_learning_workbench/tests/test_reconstruction_pair_integration.py \
  robot_learning_workbench/tests/test_real_sim_page.py -q --tb=short
```

**310 passed / 1 failed / skipped 0**. 실패는 앞 기록에도 있던 Real/Sim 버튼의 `Real/Sim 연결` 대 `Real/Sim 연결 · Teleop` 기대 차이다. 사용 중인 동작/검사를 바꿔 숨기지 않았다. 최초 HEAD의 Builder+Scene Contract baseline은 **274 passed**였다.

전체 3개 패키지 시험도 실행했다: **1,232 passed / 66 failed / 28 errors / skipped 0**, 기존 경고 2개. 실패·오류 **94개 전부**를 HEAD 소스의 별도 사본으로 동일 시험/동일 로컬 입력에서 다시 실행해 **66 failed / 28 errors**와 동일 case 집합을 확인했다. 주요 원인은 삭제된 과거 `scene.usda`/`so101_isaaclab_base.usd` 시험 입력과 오래된 UI 기대값이다. 이전 285/1이나 현재 관련 시험 통과 수를 전체 GREEN이라고 사용하지 않는다. 마지막 자산/미결합 Capture 보강 뒤에는 위 관련 시험을 다시 실행했다.

실제 실행은 다음과 같다.

- **SAM/DA3:** 기존 설치/가중치로 보존 Side/Wrist 2장·Object query 4개를 별도 Project에서 실행. Side cube 1 Mask, Side cup 2개/AMBIGUOUS, Wrist 두 query NOT_FOUND. DA3 양 Depth **210×280**. K/Scale은 UNRESOLVED. 재실행의 모델 forward 로그 mtime 불변으로 캐시 재사용 확인. Source Project/Current/Evidence/RGB **31개 SHA 불변**. 두 장으로 새로운 정확한 Scene이 완성됐다는 결과가 아니다.
- **Blender/OpenUSD:** 새 물체만 작성·USDA 등록·기존 물체 보호·같은 Asset 여러 Instance·제거 후 Library 유지·실제 Texture closure와 OBJ UV 소비·Export 이동/원본 분리 확인. 금지된 다른 Project 파일 쓰기는 bwrap이 거부했고 원본을 유지했다. USDA 파싱만 성공한 Mock이 아니다.
- **공동 정합:** 별도 합성 fixture에서 Camera와 Object를 모두 어긋나게 한 뒤 원 optical depth 공동 fitting의 오차 감소·Camera/Object 복원·고정 Geometry 보존·World cloud 재생성을 확인. K/보드 없이 9개 합성 Wrist 자세로 공유 Mount/Scale을 복원하고 실제 q/FK 등록 경로를 소비. 동일 자세·비연결 DA3 batch·품질 제외는 unresolved/제외로 유지한다. 실물 위치/회전 정확도 증명이 아니다.
- **Pair:** 실제 SnapshotStore/Pair Writer/Reader를 Memory bus와 합성 RGB로 실행해, Scene 없는 새 Project의 촬영을 발견하고 Candidate에 기록 Robot을 결합·재정합 진입·Sim q 진단·원 파일 SHA 보존을 확인했다. 새 실물 촬영이나 실제 Leader 동작이 아니다.
- **새 USDA 물리:** 합성 자산 Scene에서 MuJoCo와 실제 PhysX를 각각 **350 Step** 실행, finite state와 지지 접촉 확인. 최초 MuJoCo의 단일 Mesh 접촉 침투와 최초 PhysX sensor/filter pattern 오류를 실제 로그에서 찾고 수정했다. 열린 컵의 분리 Visual·17개 convex Collision과 내부로 떨어지는 블록은 실제 Blender→USDA→MuJoCo/PhysX **각 600 Step**으로 확인했다. PhysX 블록 중심 z 약 0.013m는 이 합성 컵 바닥/블록 치수의 결과이며 실물 접촉 정확도가 아니다.
- **기존 실행 호환:** 보존된 v9 Native Scene을 production `SceneView/NativeRenderer`로 로드해 MuJoCo **60 Step**, Isaac **48 Step**과 두 Camera **640×480 RGB**를 소비했다. 실제 Articulation/목표 관절 physics 경로이며 실물 명령은 아니다. 원 Manifest 자산 **86개 SHA 불변**. 새 Asset의 로봇 grasp/전체 Task 성공을 검증한 결과로 확대하지 않는다.

관련 JUnit·전체 JUnit·94개 baseline 대조·모델/physics/native 로그·실행 스크립트·변경 파일 SHA는 기존 Git 제외 경로 `workbench_runs/scene_improvement_20261104/`에 보관한다. 모델 가중치를 복사하거나 내려받지 않았으며, 전체 설치 SDK/모든 Scene 파일을 전수 hash했다는 뜻은 아니다. 최초 진단/실패 로그도 보존한다. 별도 lint/type 설치·실행은 없다.

공식 API 근거는 [Blender USD Export](https://docs.blender.org/api/current/bpy.ops.wm.html), [OpenUSD References](https://openusd.org/release/api/class_usd_references.html), [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive/), [Isaac SimulationContext](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/py/source/extensions/isaacsim.core.api/docs/index.html), [MuJoCo 다중 접촉](https://mujoco.readthedocs.io/en/3.3.5/computation/)이며 설치된 실제 API/실행 결과를 우선 확인했다.

### 사용자 사용법과 남은 범위

1. **새 Scene:** Scene Prepare에서 새 Project·촬영·메모를 저장 → Auto Reconstruction. Object 목록이 비어 있으면 Codex 메모 분석/작업자료 → 다시 분석 → 신규 자산 모델링 → 같은 Candidate 재실행. 실측 치수는 선택 입력이며 미제공 값은 측정값으로 만들지 않는다.
2. **기존 USDA 추가:** Dialog의 Library 등록/물체별 선택 또는 Codex의 `object-asset register/instantiate` → 새 Instance만 fitting. 기존 Mesh/Texture는 재사용한다.
3. **새 물체 제작:** Codex가 `modeling/tasks.json`과 원 사진을 읽고 해당 물체만 bpy로 작성 → `blender-object-author` 또는 명시 `modeling-run` → USDA 검증/등록 → 재실행이 결과를 자동 Import한다.
4. **배치만 변경:** 새 촬영 배치로 완료 Pair를 모으고 Real/Sim 중단 후 재정합 → 새 Candidate. Asset 재모델링/원 관측 수정 없이 Pose/식별 가능한 Camera 변수만 보정한다.

**아직 전체 무인 Scene 제작 완료는 아니다.** 실제 원격 Codex CLI 모델링, 일반 렌즈 왜곡의 자동 복원, 실제 사진에서의 Mount-link/Scale 정확도, 부족한 View의 자동 의미/Instance 연관·실패 수정, 모든 새로운 Object/Articulation·Gripper 접촉·Task 성공, 독립 사진/자세의 Backend 우승/실제 mm 정확도는 미검증 또는 미완료다. 현재 제공된 두 실제 사진에는 충분한 Scale/독립 검증 근거가 없어 Camera UNRESOLVED와 모델링 작업자료를 남겼다. 기존 최종 Scene/Calibration/Revision을 바꾸거나 이를 성공한 새 Scene으로 게시하지 않았다.

## 2026-11-04 — 코드 리뷰 후속 수정 및 통합 검증

사용자 지시서 `Real2Sim 자동화 코드 리뷰 후속 수정 및 통합 검증`의 네 항목을 기존 미커밋 구현 위에서 수정했다. 브랜치는 `feat/auto-real2sim`, 기준 HEAD는 `eb1a639ba1dc8cb4870c5f7609fb1d4d5333797a`다. 아래 기록은 앞 절의 구현 당시 미완료 기록에 대한 후속 결과이며, 그 당시 실패를 삭제하지 않는다. Commit/Push/Merge·설치·실물 장치 연결은 수행하지 않는다.

### A. 수정한 문제와 실제 원인

1. **이름만 같은 USDA 자동 재사용:** `automation.modeling_tasks`가 Asset ID의 단일 버전을 새 물체에 자동 부착하던 분기를 제거했다. `asset_manifest` 명시 선택은 `attach_modeled_assets`/`verify_object_asset`로 ID·Version·Manifest 위치와 종속 파일 SHA를 확인한다. Scene의 기존 유효한 USDA 참조는 유지한다. 이름만 맞는 후보는 `ASSET_MATCH_UNRESOLVED`와 치수/버전/Collision Metadata·사진/Crop/Mask를 작업자료에 남긴다. 다른 자산을 조용히 선택하지 않으며 필요한 Object만 모델링한다. 동일 Asset의 다중 Instance·불변 Library·삭제 후 보존 계약은 유지한다.
2. **보고서 존재 → DRAFT_READY 오판:** `hybrid.backend_ready`/`compare_backends`가 실제 성공한 solve와 유한한 train RGB 비교를 확인한다. `automation.draft_readiness`가 완전한 Geometry/Pose/Camera 및 자산 검사를 추가한다. Cloud 없음, validation만 존재, Backend 실패/UNRESOLVED, 필수 Visual/Pose 누락과 NaN은 초안 준비로 반환하지 않는다. 모델 제작 대기는 `WAITING_FOR_CODEX`, 의미 분석 대기는 `WAITING_FOR_CODEX_ANALYSIS`다. Project Status 허용 상태와 `reconstruction.json`/Qt 표시를 일치시켰다. `reconstruct/refit-pairs`: 초안 준비 exit 0, 대기·자료 부족 exit 2, 예외 exit 1. `DRAFT_READY`를 ACCEPTED/PHYSICS_READY로 승격하지 않는다. 해당 상태를 구분하지 않던 기존 두 시험의 기대값은 요구사항에 맞게 수정했다.
3. **Pair가 다른 Current에서 시작:** `capture` Reader가 원 Pair의 `scene_identity/source_scene`을 보존하고 `automation.pair_source`가 원 Pair SHA·Package Scene identity·Manifest·manifest-covered `authored_scene.json`을 확인한다. 오래된 등록 행에 identity가 빠져 있어도 원 Pair JSON에서 SHA 확인 후 읽으며 원 기록을 수정하지 않는다. `Candidate.create`의 명시 Source 인자로 촬영 Revision에서 파생하고 Current는 대체 Source로 사용하지 않는다. 다른 Revision/배치/기존 Candidate 결합은 진단으로 거부한다. 새 Real/Sim 렌더 결과에는 Source Package 경로와 authored Scene SHA를 더 남긴다. `refit_only`는 Source Geometry/Material/Collision을 재모델링하거나 교체하지 않는다. q/Mapping/원 RGB/Pair는 유지한다. 기존 Package의 명시 baked Geometry와 측정 모델이 다른 경우에는 이미 검증된 `robot_residual`의 source/execution SHA 관계만 허용하며 임의 SHA alias나 q offset은 도입하지 않는다.
4. **실제 Codex 이미지 입력 미검증:** `run_codex_modeling`은 설치 CLI의 `--image`로 RGB/Crop/Mask를 명시 첨부한다. Image ID에 연결된 DA3 NPZ의 depth/confidence/K/extrinsics·픽셀 변환과 Camera 추정 상태, 메모, 기록 치수를 같은 `tasks.json`에 전달한다. 미검증 추정치를 measured로 바꾸지 않는다. 기존 ChatGPT 인증을 쓰며 별도 API 키/endpoint 환경 변수를 child에 넘기지 않는다. 인증/사용량/CLI 옵션/응답 누락/Timeout/Stop 상태와 로그를 보존한다. 유효한 등록 결과는 재호출하지 않는다. Blender 호출도 소유 process group의 중단·Timeout을 처리한다.

추가로 실제 생성 코드에서 `hide_render=True`인 Collision이 USD Export에서 빠지는 문제를 재현했다. Object Worker가 Collision을 Export 대상으로 포함한 뒤 USD CollisionAPI와 invisible 분리를 적용한다. Blender 기본 이름의 Mesh/Xform 병합으로 custom property가 빠지는 경우도 별도 Geometry data 이름으로 보존했다. 이 수정은 새로 만드는 격리 Blender 자산에만 적용한다.

### B. 실제 ChatGPT Codex CLI → Blender → USDA

`codex --version`은 **0.166.0**, `codex login status`는 **Logged in using ChatGPT**였다. 사용자 인증/설정을 변경하거나 API 키로 전환하지 않았다. 실제 CLI help와 [공식 CLI 옵션](https://learn.chatgpt.com/docs/cli/reference), [비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)을 대조했다.

원격 모델은 **소형 물체 한 개에 대해 1회** 호출했다. 별도 시험 Project/Candidate에서 기존 실제 Side/Wrist 사진·SAM Mask/Crop과 DA3 자료, 기존 기록 치수 **24mm**를 입력으로 썼다. Codex가 사진을 읽고 빨간 블록 bpy 코드·Crop 기반 image texture·별도 convex Collision을 생성했다. Blender는 기존 설치본, OpenUSD는 기존 Library 검사를 사용했다. 최종 자산은 Visual 1개·Collision 1개·PNG Texture를 포함하며 Candidate에 추가한 뒤 실제 MuJoCo **320×240 RGB**를 렌더했다. 이 시험은 모델링 연결 확인이며 실제 Scene 정합/색 정확도·그리퍼 Task 성공 시험이 아니다.

첫 실제 실행은 숨긴 Collision 누락으로 실패했다. 원 로그/생성 코드/미완료 자산을 유지하고 Worker 수정 뒤 **같은 생성 Python을 재사용**했다. 원격 모델을 다시 호출하지 않았다. 렌더 harness의 임시 Table에 mass/friction의 null record가 빠진 오류도 별도 로그에 남기고 해당 disposable fixture만 보정했다. 사용자 Table/Robot/Scene을 변경한 것이 아니다. 첫 실패를 Fake 성공으로 대체하지 않았으며 로컬 `real-codex.log`, `real-codex-resume.log`, `real-codex-render.log`, `real-codex-summary.json`으로 구분한다. 실제 원격 인증 실패·한도 초과를 유도하는 추가 호출은 하지 않았다. 그 분기는 Fake CLI 경계 시험이다.

### C. 회귀·보존

자산 이름 충돌, 무정합 초안 판정, 대기 상태, 사진 입력 미첨부, 숨긴 Collision에 대해 수정 전 실패 로그를 남긴 뒤 수정했다. 기존 시험 파일에 사례를 추가했으며 새 Mock Framework/별도 앱을 만들지 않았다. 실측/기존 자산 파일을 테스트 통과 목적으로 변경하지 않았다.

검증 명령:

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short --junitxml=/tmp/reconstruction-review-final-full.xml
```

최종 전체 회귀는 **1,249 passed / 66 failed / 28 errors / skipped 0**, 기존 경고 2회다(총 1,343 case, 약 211초). 기준 HEAD 소스로 재현해 둔 기존 Baseline의 실패·오류 94개와 test name/kind 집합이 모두 같으며 **신규 실패 0**이다. 누락된 과거 테스트 USD/Scene 자산과 기존 UI 기대값 등을 이번 수정의 성공으로 바꾸거나 보호 검사를 완화하지 않았다. 전체 GREEN은 아니다. `baseline-comparison.json`은 기준 JUnit과 최종 JUnit 경로·동일 실패 94개·신규 실패 빈 목록을 기록한다.

첫 전체 실행은 **1,244 passed / 67 failed / 28 errors**였다. 새 `WAITING_FOR_CODEX` 상태를 여전히 `NEEDS_MORE_DATA`로 기대하던 기존 시험 1개가 추가 실패한 것을 수정하고 최종 전체 회귀를 다시 실행했다. 별도 관련 통합은 **319 passed / 1 failed**였으며 그 실패는 기존 Real/Sim 버튼 문구 기대값이다. 최종 Source/상태/Pair 집중 검사는 **18 passed**다. 실제 Native fitting + RGB/overlay를 사용하는 기존 fixture에서 유효한 `icp_mask` 초안의 DRAFT_READY도 확인했다. validation-only/Cloud 없음/미해결 모델/NaN/필수 Geometry·Pose 없음은 각각 거부한다.

변경 Python **33개**를 bytecode 없이 구문 검사했고 `git diff --check`를 통과했다. 별도 lint/type 도구를 설치하거나 실행했다고 주장하지 않는다. 모델링 오류·Timeout·Stop은 경계 시험과 실제 Blender 시험을 구분하고, 실제 원격 Codex 호출은 1회만 수행했다.

원본 `pickplace-colorblock-b7a5592b`의 Project/Current·input(사진/Capture/Calibration·자산)·configuration·exports **2,389개 파일 SHA 변화 0**을 확인했다. 원 SDK/계정 인증 파일 전체의 전수 hash 주장은 아니다. 실제 장치/API를 호출하지 않았다. `.gitignore`와 main/workflow-restoration/HEAD를 유지하고 작업 소스·시험·문서만 로컬 변경으로 남긴다. 증거는 Git 제외 `workbench_runs/reconstruction_review_20261104/`에 보관한다.

### D. 남은 실제 검증과 다음 Scene 작업

- 단일 빨간 블록의 실제 모델링 연결은 확인했지만 모든 모양/Texture/복잡한 열린 물체의 자동 모델링 품질을 보장하지 않는다. 원격 인증/한도/옵션 오류는 실제 계정을 실패시킨 시험과 구분한다.
- 독립 held-out 사진/실측 Pose가 없으므로 실제 mm/회전 정확도·Backend 우승 선정은 여전히 미검증이다. 일반 렌즈 왜곡 복원, 모든 Wrist Mount 식별, 완전한 Robot/Gripper Task 검증도 앞 절의 미완료 범위를 유지한다.
- 과거 Package에 Manifest-covered authored Scene이 없거나 원 Source가 유실된 Pair는 `PAIR_SOURCE_UNRESOLVED`다. 현재 Scene으로 대신 진행하지 않는다. 기존 v8 실행 Package의 존재만으로 당시 authoring Scene을 복원했다고 표시하지 않는다.
- 다음 실제 Scene 검증은 Source Package가 확인되는 **한 Revision·한 물리 배치**의 여러 Side/Wrist 관측을 새 Candidate에 재정합 → 두 View overlay와 수치 검토 → 별도 physics/독립 관측 확인 → 명시 Review Export 순서다. 이번 작업은 기존 최신 Scene/Revision을 교체하지 않는다.

## 2026-11-04 — Asset Group·재사용 검증·Blender Sandbox 안정화

사용자 지시서 `Real2Sim 자동 Scene 제작 안정화 — Asset Group, 재사용 검증, Blender Sandbox`를 기존 미커밋 작업 위에서 수행했다. 브랜치/HEAD는 `feat/auto-real2sim` / `eb1a639ba1dc8cb4870c5f7609fb1d4d5333797a`로 유지한다. 새 Agent/Asset DB/Material 시스템·환경 설치·Commit/Push/Merge·실물 연결은 없다.

### 원인과 변경한 함수

| 문제 | 기존 원인 | 수정 경계와 동작 |
|---|---|---|
| 잘못된 모델 결과 재사용 | `attach_modeled_assets`/`run_codex_modeling`이 Object 이름과 과거 assets 목록을 사용 | `modeling_groups/group_asset/record_modeling_results`로 그룹별 내용 Fingerprint와 Manifest SHA를 검증한다. legacy/변경 결과는 검토하며 명시 Manifest 선택은 유지 |
| 동일 제품의 중복 모델링 | 각 Object가 모델링 task/root 하나를 만들었음 | Config에 Category/asset_group/관계 provenance, `/2` tasks/results에 그룹 members·근거·Fingerprint를 기록. 그룹당 root/Asset 하나, 기존 instance_operation으로 여러 Object 생성 |
| 같은 Prompt/Mask의 중복·오배정 | SAM 캐시에 Object ID 포함, 후보 Mask를 개별 Object와 연결하는 독립 검사 부족 | `inference.run_models`는 RGB/모델/Prompt/Box/설정 기준 캐시를 공유하고 Object ID를 별도로 복원. `associate_instances`가 명시 선택/Box/유일 후보를 검사하고 같은 이미지의 동일 Mask 중복 배정을 AMBIGUOUS로 유지 |
| Object Blender가 호스트를 읽을 수 있음 | root 전체 ro-bind와 부모 환경 상속 | `rendering.object_sandbox/object_worker_environment`의 빈 루트·실제 런타임 허용 목록·전용 출력·최소 환경으로 교체. 일반 Renderer 경로는 유지 |

그룹을 나눌 때 같은 내용 Version을 가진 서로 다른 Asset ID의 내부 asset key가 충돌하는 문제도 재현했다. `object_assets.instance_operation`의 키에 ID와 Version을 함께 반영하여 해당 Instance의 참조만 바꿀 수 있도록 했다. 기존 Library/Version bytes는 수정하지 않았다.

### 메모 → 분석 → 관측 → 모델 공유

메모 원문과 사진은 기존 Project Evidence에서 Codex 분석 입력으로 전달한다. 의미 분석 JSON Schema에 Category, asset_group, group_status/group_evidence, material_variant, 이미지별 관측/Box를 추가했다. 같은 실제 물체의 Side/Wrist 사진은 한 Object의 여러 관측이며, 같은 제품의 다른 두 물체는 두 Object와 공유 Group이다. Category가 같다는 이유로 합치지 않는다. 과거 id/prompt/role만 있는 응답과 Group 없는 Config는 각각 개별 그룹으로 처리한다. Codex의 관계/Box는 estimated, 근거 있는 그룹 제안은 PROPOSED, 사용자가 UI/Config에서 직접 선택한 관계는 user_declared다. 실제 검증/physical_verified로 승격하지 않는다. 알 수 없는 q/치수/물성/Camera는 분석 응답으로 채우지 않는다.

SAM 후보의 순서는 Object ID가 아니다. `associate_instances`가 이미지별 Box/명시 Mask/유일 후보를 사용하고, 그룹 관계나 미해결 Camera에서 3D 정체성을 만들어 내지 않는다. 동일 Mask가 두 Object에 배정되면 둘 다 AMBIGUOUS이며 점군에 포함하지 않는다. 기존 Mask 선택 UI를 계속 사용한다. Group의 모든 멤버 관측/원 RGB·Mask/Crop·Depth·기록 치수·메모를 하나의 모델링 자료에 모으되 개별 관측의 불확실성을 유지한다.

모델링 task의 object_id/root r2s_id는 그룹 ID다. members의 cup_1/cup_2마다 Blender 모델을 다시 생성하지 않는다. `record_modeling_results`가 그룹 Fingerprint와 검증된 USDA Manifest SHA를 기록하고 `attach_modeled_assets`가 개별 역할/Pose를 가진 Instance를 만든다. Scene Schema/Project/Candidate/Export 형식은 확장하지 않고 Config와 기존 모델링 작업자료 안에서 관리한다. 동일 형상이라도 실제 외형이 다르면 material_variant별 별도 불변 Asset을 허용한다. 공유 Instance를 제거해도 원 Asset과 다른 Instance는 유지한다. Group 분리는 GROUP_RELATION_CHANGED로 확인하고 필요한 Object만 새 자산을 선택/모델링한다.

### Fingerprint와 UI/CLI 사용

Fingerprint는 정규화·중복 제거한 형상 관련 멤버 정보, RGB/선택 Mask/Crop/Depth 내용 SHA, 명시 치수와 provenance/evidence, 메모 SHA, 형상 제약·생성 설정 및 계약 버전으로 구성한다. 절대 경로·실행 시각·Scene Pose·Instance ID 자체는 제외한다. 동일한 Instance 추가나 역할/배치만 바뀌면 공유 Geometry를 다시 생성하지 않는다.

동일 Fingerprint+유효 Manifest는 자동 재사용한다. 마지막 검토에서 Scene Signature에 아직 포함되지 않은 Mask의 변경도 실행/캐시 반환 전에 frozen SHA와 대조하도록 추가했다. 복사된 RGB/Mask/Depth 내용도 원 작업 SHA와 일치해야 한다. RGB/Mask/치수 변경은 해당 그룹을 MODEL_INPUT_CHANGED로, Fingerprint 없는 과거 결과는 LEGACY_RESULT_REVIEW_REQUIRED로 검토한다. 메모 전체가 바뀌면 어느 물체에 영향을 주는지 추측하지 않고 작업자료를 재검토한다. 이는 물체 동일성 인식 모델이 아니다. 새 시점 사진만으로 무조건 재모델링하지 않으며 기존 Manifest를 명시 선택하면 재사용한다. 기존 실측 치수와 모순되는 새 물체는 기존 보호 검사를 유지하므로 새 Object ID/자료로 구성해야 한다.

Auto Reconstruction의 기존 물체 표에 `물체 종류`와 `공유 Asset Group`을 표시한다. USDA 선택은 `자동 판정 / 기존 유지`, `검토 후 새 모델링`, 기존 Manifest 목록이다. 새 모델링 선택은 Config의 modeling_action: new, 명시 자산 선택은 asset_manifest다. 기존 UI의 설정 보존/CLI 실행 경로에 연결했고 전면 개편하지 않았다. `modeling-run`은 불확실한 Group/변경·Legacy 결과에 대해 원격 작업을 시작하지 않고 ASSET_REUSE_REVIEW_REQUIRED/exit 2를 반환한다. `blender-object-author --objects GROUP ...`도 frozen 그룹 결과를 기록한다. 전체 Config/API 예시는 `real2sim_builder/AUTO_SCENE_FITTING.md`의 최신 절을 따른다.

### 실제 Sandbox 권한

Object Authoring은 `--ro-bind / /`를 제거했다. 신뢰된 설치 Blender로 SYSTEM/LOCAL 리소스 위치를 조회하고 ldd로 실제 라이브러리/로더를 확인한다. executable, 해당 리소스/라이브러리 디렉터리, 필요한 시스템 font/config, Worker 소스 파일만 읽기 전용으로 제공한다. 빈/상위/위험한 리소스 경로와 누락 의존성은 오류로 중단한다. 환경 경로를 사용자 절대 경로로 코드에 고정하지 않았다.

호스트 쓰기는 작업 출력 폴더 하나뿐이고 그 안의 author.py/inputs도 읽기 전용이다. `/tmp`는 별도 임시 filesystem, `/dev`는 최소 가상 장치, `/proc`는 새 PID namespace다. 네트워크를 차단하고 HOME=/nonexistent, PATH/locale/temp/thread 설정만 전달한다. 부모의 Key/토큰/인증/Python/loader 환경변수는 Worker와 Object용 capability/runtime probe에도 상속하지 않는다. 입력 symlink를 복사 전에 거부한다. 실패 시 root bind나 환경 상속으로 확대하지 않는다. 일반 Scene Rendering의 worker_environment/실행 경로는 유지한다.

테스트 전용 가짜 인증 파일과 FAKE_AUTH_ACCESS_TOKEN으로 읽기/환경 차단을 확인하고, 호스트 loopback listener에 접속할 수 없는 것을 확인했다. 실제 인증 파일이나 개인 파일 내용을 읽어 시험하지 않았다. 정상 Texture 로딩·UV/Material·숨긴 Collision 포함 USDA Export, Closure 검증, 전용 출력 및 기존 외부 쓰기 거부가 함께 통과했다. 모든 Blender 배포판/추가 Python 패키지까지 지원한다고 주장하지 않으며, 확인할 수 없는 런타임은 명확하게 실패한다.

### 검증과 원본 보존

수정 전 Sandbox 파일 노출, Group 작업/안전한 legacy 재사용 부재, Mask/Object 연결 부재, Group 분리의 asset key 충돌을 실패 시험으로 남긴 후 수정했다. 기존 시험 파일에 사례를 추가했고 별도 Mock Framework/테스트 앱은 만들지 않았다.

- **동일 종이컵 2개:** 메모 관계와 통제 640×480 RGB/두 Mask → Box로 독립 Object 연결 → 그룹 task 1개 → Fake CLI 코드 응답 → 실제 Blender의 열린 컵+Texture/17 convex Collision → OpenUSD Library 1개 → 두 Instance/독립 Pose → 실제 MuJoCo 640×480 RGB. 삭제 후 Asset 보존·Group 분리·Material variant 별도 자산도 시험했다. Crop/원 RGB/Mask 대응과 같은 Prompt의 SAM 작업 1회·재실행 캐시를 확인했다.
- **모호함:** Box/선택 근거가 없는 두 컵은 AMBIGUOUS다. 같은 Category의 다른 컵은 별도 Group이며, 불명확한 그룹은 모델링을 시작하지 않는다. 다른 시점은 한 Object의 이미지별 관측으로 보존하고 명시 기존 Manifest 재사용을 허용한다.
- **캐시:** RGB/Mask/치수 변경·legacy·Group 분리·Pose 변경·Instance 추가·경로 이동·중단 후 유효 결과 재사용을 검사했다. 변경되지 않은 그룹/Library SHA를 보존한다.
- **실행 범위:** 이번에는 **새 원격 Codex 호출 0회**다. SAM/DA3/Codex 경계 시험은 통제 응답/기존 작업자료를 썼으며 새 실데이터 inference·원격 의미 분석·사진 정합 정확도 시험으로 보고하지 않는다. Blender/OpenUSD/MuJoCo와 640×480 렌더는 실제 실행이다. 독립 검증 사진/Camera·Scale 근거가 부족하면 기존 NEEDS_MORE_DATA/AMBIGUOUS를 유지한다. Physics/Task 승인이나 새 Isaac E2E를 추가로 주장하지 않는다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short --junitxml=/tmp/asset-group-release.xml
```

최종 전체 **1,260 passed / 66 failed / 28 errors / skipped 0**(1,354 case, 약 227초, 기존 경고 2회). 기존 Baseline의 실패·오류 94개와 test name/kind 집합이 모두 같으며 신규 실패 0이다. 대조 결과를 아래 보존 verification에 남긴다. 별도 최종 집중 검사 **36 passed**, 640×480 Texture 예제 재확인 **1 passed**다. 앞선 전체 실행은 1,256 및 1,259 passed/66 failed/28 errors였으며 추가 회귀·마지막 frozen 입력 검사를 포함해 최종 전체를 실행했다. 전체 GREEN이라고 보고하지 않는다. Python 34개 구문 검사와 git diff --check를 수행했고 별도 lint/type 도구 설치/실행은 없다.

원본 Project/Current/input(사진·Capture·Calibration·자산)/configuration/exports **2,389개 SHA 변화 0**을 확인한다. 계정/SDK 전체 corpus 전수 hash 주장은 아니며 설치 환경과 원본 RGB/Dataset은 수정하지 않았다. `.gitignore`와 HEAD/main/workflow-restoration은 유지한다. 증거와 통제 컵 예제는 Git 제외 `workbench_runs/asset_groups_20261104/`에 작은 로그/JUnit/예제 USDA·PNG로 보관한다. 모델 가중치·학습 결과를 복제하지 않는다.

사용자는 Scene Prepare에 사진·실측·메모를 저장하고, 동일 제품/색·무늬 차이를 메모에 분명히 적는다. Auto Reconstruction/Codex 분석의 개별 Object와 공유 Group을 확인하고 모호한 Mask는 선택한다. 기존 물체의 새 시점이면 기존 Manifest, 새 외형이면 검토 후 새 모델링을 선택한다. 이후 그룹별 모델링 → Instance 구성 → Camera/Object 정합 → Side/Wrist 비교 → 기존 명시 Review Export 순서다. 이번 통제 예제를 실제 사용자 Scene의 완성·원격 분석 정확도·모든 촬영 조건의 무인 성공으로 승격하지 않는다.

## 2026-11-04 — v3 모델링 우선순위·메모 관계·관측 재사용

사용자 v3 후속 수정 지시서에 따라 세 가지 재사용 문제를 기존 Group/Library/Project 경계에서 수정했다. 시작과 종료 HEAD는 `eb1a639ba1dc8cb4870c5f7609fb1d4d5333797a`, 브랜치는 `feat/auto-real2sim`이다. 앞 단계의 미커밋 변경은 유지하고 Commit/Push/Merge는 하지 않는다. 위의 과거 기록 중 “사진/Mask 변경은 무조건 MODEL_INPUT_CHANGED”, “메모를 분석한 관계는 항상 estimated”라는 설명은 아래 조건으로 대체된다.

### 실제 원인과 소유 함수

| 문제 | 실제 원인 | 수정 파일·함수와 결과 |
|---|---|---|
| 새 모델링을 골라도 기존 자산 반환 | `group_asset`가 요청의 완료 여부를 구별하지 않고 Fingerprint/Manifest부터 반환 | `automation.modeling_groups/group_asset/modeling_tasks/run_codex_modeling/record_modeling_results`, `ui_reconstruction.group_asset_choice/configuration`: Group별 새 요청 ID를 먼저 검사하고 성공한 요청만 재사용 |
| 사용자 동일 제품 메모도 관계 미확정 | 의미 분석의 모든 관계를 Codex 추정으로 기록하고 원문의 명시 사실을 따로 구조화하지 않음 | `automation.note_relation/run_codex_modeling`: 메모 SHA·실제 인용문·subject·members를 검증해 사용자 명시 관계를 분리 |
| 재촬영이 모델 변경으로 취급됨 | 전체 RGB/Mask/Crop/Depth/메모 Fingerprint를 물체 동일성과 함께 사용 | `automation.modeling_groups/group_asset/modeling_change_evidence/attach_modeled_assets`: 생성 입력은 보존하고 기존 Scene/확정 Group 동일성에 따른 관측 재사용 이력을 별도 기록 |
| 과거 캐시가 Scene 선택을 되돌림 | 캐시와 이미 선택된 Scene Asset의 우선순위가 반대 | `group_asset`에서 명시 요청/Manifest 다음에 유효한 Scene 참조를 확인 |
| 과거 생성 Crop 내용이 바뀜 | 같은 Object/Image 이름으로 Crop을 덮어씀 | `modeling_groups`에서 RGB·Mask·영역 내용 기반 Crop 경로 사용. 과거 생성 참조 파일을 보존 |

`object_assets.register_object_asset`는 선택적 generation_id를 Version 계산과 Manifest의 generation_request_id에 결합한다. `rendering.author_object_assets`는 Group별 request_ids와 등록 callback을 받고, CLI `blender-object-author`도 같은 요청 ID/결과 기록을 사용한다. 별도 Manager/DB/Agent나 Scene Schema를 추가하지 않았다. 기존 Object Blender Sandbox·SAM/DA3·Camera/Object 정합의 원본 검사를 유지한다.

### 요청 우선순위와 부분 성공

미완료 `modeling_action=new`는 기존 Fingerprint/Manifest보다 먼저 `NEW_MODEL_REQUESTED`가 된다. 같은 Group의 UI 행은 하나의 modeling_request_id를 공유하고 저장/재시도에 유지한다. 등록 시 Manifest의 generation_request_id가 frozen 요청과 맞아야 `request_status=REGISTERED`가 된다. 같은 Mesh를 생성해도 새 요청은 새 불변 Version이며 과거 Asset을 삭제/덮어쓰지 않는다. 성공한 Group은 즉시 기록하므로 다음 Group이 실패해도 재시도는 미완료 Group만 실행한다. 같은 완료 요청을 다시 실행해 원격 모델을 중복 호출하지 않는다. 새로 선택하거나 고급 Config에서 새 request ID를 지정하면 별도 요청이다.

그 다음 우선순위는 명시 Manifest, 유효한 기존 Scene 참조, 검증된 자동 캐시, 검토다. 이전 관계 불확실성은 유효한 Manifest 직접 선택으로 해소할 수 있다. 반면 잘못된 Manifest/SHA·실측 치수 충돌·같은 Group의 상충 자산·관측 수량 문제는 승인하지 않는다. 명시하지 않은 Group/Object는 모델링 대상에 넣지 않는다.

### 메모 사실과 Object Association

메모 원문과 SHA를 분석 입력으로 보내고 group_sources의 실제 quote/subject/members를 Project의 등록 메모와 대조한다. 긍정적인 동일 제품/모델 공유 선언이면 user_declared/CONFIRMED로 기록한다. 사진에서 “비슷해 보인다”는 추정, 부정/불확실한 문장, 없는 인용문, 틀린 SHA/멤버는 estimated/PROPOSED 또는 UNRESOLVED로 유지한다. Object와 메모 대상의 grounding은 추정이며 물리적 동일성 검증으로 표시하지 않는다. 기존 사용자 Group/Manifest/요청 선택은 의미 분석 재실행으로 덮어쓰지 않는다.

동일 제품 컵 2개는 Object Instance 2개·Group 1개로 남는다. SAM의 어느 Mask가 어느 Object인지 모호하면 그 Association만 검토하며 제품 관계를 다시 묻지 않는다. 관측된 여러 Object에 비해 모든 해당 이미지의 후보 Mask 수가 부족하면 OBSERVATION_COUNT_REVIEW_REQUIRED로 별도 보고한다. 이 진단은 가림/미검출 가능성을 함께 남기고 실제 개수 충돌을 확정하지 않는다. 메모에서 확정한 내용을 조용히 바꾸거나 Mask를 복제해 채우지 않는다.

### 생성 Fingerprint와 Object Identity

생성 Fingerprint는 당시 RGB/Mask/Crop/Depth·메모 SHA·실측/형상/생성 조건을 기록한다. 재촬영 입력을 과거 생성 입력인 것처럼 덮어쓰지 않는다. 기존 결과의 fingerprint_inputs/references/notes는 유지하며 다른 Version 생성 시 history에도 보존한다. Crop 파일도 내용별 경로로 남긴다.

Object Identity는 기존 Scene의 Asset ID/Version 참조 또는 사용자 확정 공유 관계와 형상/실측 서명을 사용한다. 이 조건이 유지되면 이동·회전·새 Side/Wrist·배경/조명 변화는 ASSET_IDENTITY_REUSE/EXISTING_SCENE_ASSET로 재사용하고 Pose/Camera 정합 입력으로 전달한다. 새 입력의 Fingerprint/RGB SHA는 reuse_observations에 별도 기록한다. Category가 같은 새 컵만으로 자동 재사용하지 않는다.

치수/형상 제약/Material Variant 변경이나 해당 물체의 형상·무늬·재질 변경 메모는 해당 Group을 검토한다. 단순 위치/회전 메모와 다른 블록의 변경은 컵 모델링을 무효화하지 않는다. 무늬 변경에는 Material Variant/새 자산을 선택할 수 있으며 원 Geometry/Collision은 삭제하지 않는다. 텍스처만 바뀐 새 자산에서 Geometry/Collision을 자동 분리 재조합하는 새 시스템은 추가하지 않았다.

새 사진에서 이전에 보이지 않던 형상 차이를 독립적으로 판정하는 Re-ID/임베딩 모델은 구현하지 않았다. 현재는 기존 관계·실측·형상 제약·메모의 변경 근거를 보수적으로 사용한다. 사진만으로 발견해야 하는 미기록 형상/재질 차이는 여전히 검토 한계다. 메모의 모든 자연어 표현을 이해한다고 주장하지 않으며 출처/긍정 선언/대상 확인이 안 되면 자동 승격하지 않는다.

### 검증과 제한

기존 시험 파일에 재현 사례를 추가했다. 같은 Fingerprint에서 새 요청 무시, 명시 Manifest와 미확정 관계 충돌, 메모 출처 미반영을 RED로 확인했다. 마지막으로 과거 캐시의 Scene 참조 되돌림과 Crop 덮어쓰기 역시 실제 호출에서 RED→GREEN으로 수정했다.

- 메모 원문으로 확정된 두 컵 → 독립 Mask Association → Group 1개 → Fake Codex 코드 응답 → 실제 Blender 열린 컵/Texture/17 convex Collision → OpenUSD Library 1개 → 독립 Pose의 Instance 2개 → 실제 MuJoCo 640×480 RGB를 확인했다. 예제는 `workbench_runs/v3_modeling_20261104/example/`다.
- 단순 Pose 수정·재촬영 관측·동일 제품 Instance 추가는 재모델링하지 않고 원 생성 Fingerprint를 보존한다. 측정/형상/무늬 변경과 새 Category-only Object는 검토한다. 원 Library/다른 Group SHA를 확인했다.
- Fake CLI + 실제 Blender로 새 요청이 해당 Group만 새 Version을 만들고, 동일 완료 요청에는 추가 코드 호출이 없는 것을 확인했다. 2개 Group 중 첫 등록 성공 후 두 번째의 오목 Collision 실패를 만들고, 재시도에는 두 번째 Group만 작성하는 것을 확인했다. 이전 두 Asset은 SHA 불변이다.
- Qt의 같은 Group 행에 요청 ID 공유·반복 저장 안정성·자동/Manifest 선택 전환을 시험했다. 원문 인용 위조·관측 개수 부족·Mask 중복/모호함·frozen Mask SHA·기존 Sandbox 회귀도 포함한다.

집중 검사 **48 passed**(`/tmp/v3-final-focused.xml`)다. 마지막으로 관계 provenance 필드 없이 YAML에 직접 지정한 Group도 의미 분석 재실행에서 유지하는 RED→GREEN을 포함했다. 최종 전체 회귀 결과와 Baseline 대조는 아래 검증 결과에 기록한다. 앞선 전체는 1,267/1,268/1,271 passed·66 failed·28 errors였으며 마지막 Config 보존 검사 전 결과다. 중간 전체 1회는 이미 수집된 옛 UI 시험 행 수 기대를 수정한 뒤 자체 pytest만 중단했으며 최종 결과로 세지 않는다. 첫 예제 보존 스크립트의 Project 상위 경로 오류도 수정 후 다시 보존했다. 제품/원본은 그 오류로 변경되지 않았다.

새 원격 Codex 호출 **0회**, 새 실제 SAM/DA3 inference **0회**, 실물 연결/모터 명령 **0회**다. 모델 경계는 통제 응답이고 Blender/OpenUSD/MuJoCo는 실제 실행이다. 독립 실사진·실제 재배치 물체의 동일성·원격 메모 추출 정확도·미관측 형상 차이 자동 검출·실제 mm 정합/전체 PhysX Task 성공은 이번 검증으로 승인하지 않는다. 기존 설치 환경/SDK/모델과 Sandbox를 변경하지 않았다.

최종 전체 명령:

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short --junitxml=/tmp/v3-complete.xml
```

최종 **1,272 passed / 66 failed / 28 errors / skipped 0**(1,366 case, 233.85초, 기존 경고 2회). 직전 Asset Group Baseline의 실패·오류 94개와 test name/kind 집합이 모두 같고 **신규 실패 0**이다. 기준 대비 성공 시험은 12개 늘었다. 전체 GREEN은 아니다. 기존 실패에는 보존되지 않은 과거 USD fixture 경로와 이전 UI 기대값 등이 남는다. 이를 테스트 삭제·보호 완화로 통과시키지 않았다. 최종 소스의 집중 검사 48개·Python 34개 구문 검사·git diff --check도 통과했다. 별도 lint/type 설치·실행은 없다.

원본 Project/Current/input(사진·Capture·Calibration·USDA/Robot 자산)/configuration/exports **2,389개 SHA 변화 0**이다. 전체 SDK/corpus 전수 hash 주장은 아니다. `.gitignore`는 변경하지 않았고 기존 미커밋 변경은 유지했다. main=`ab94b87d3f579031db0c751f274c0ab7fe6b87e6`, workflow-restoration=`5030b48487271b8ec3178467f7141143d4ee0522`와 HEAD는 그대로다. Commit/Push/Merge·설치·실물 구동은 수행하지 않았다.

작은 보존 자료는 Git 제외 `workbench_runs/v3_modeling_20261104/`의 `verification.json`, `baseline-comparison.json`, `preservation-{before,after}.json`, `source-sha256.json`, 최종 JUnit/로그·RED 기록·`example/`다. 모델 가중치/Runtime/학습 출력은 복제하지 않았다. 실제 사용법과 Config 예는 [AUTO_SCENE_FITTING.md의 v3 절](../real2sim_builder/AUTO_SCENE_FITTING.md#v3--새-모델링-요청메모-사실관측-재사용)에 반영했다. API/CLI는 기존 `reconstruct`, `modeling-run`, `blender-object-author`와 같은 Project/Candidate/Export를 사용한다.

## 2026-11-04 — Workspace 공용 Asset Library·현재 메모·Object 복원

사용자 「Scene/Asset 관리 구조 개선 및 기존 문제 A·B 해결」 지시서에 따라, 앞선 미커밋 구현을 보존한 채 기존 Project/Asset/Revision 경계만 확장했다. 브랜치 `feat/auto-real2sim`, HEAD `eb1a639ba1dc8cb4870c5f7609fb1d4d5333797a`를 유지한다. 원본 Project 강제 이관·자산 삭제·Commit/Push/Merge는 하지 않는다.

### 기존 구조와 변경된 소유권

기존 `register_object_asset`는 Project의 `input/object_assets`를 정본으로 사용했다. `instance_operation`과 Export도 Project 내부 경로를 전제로 했다. 이제 기존 Workspace의 `<workspace>/scenes/<project>` 생성 구조를 사용하고 `Project.workspace`에서 pool의 부모를 얻는다. Workbench `--workspace`와 Scene 생성 경로가 동일 기준이다. 제품 코드에 사용자 홈/설치 절대 경로를 넣지 않았다.

```text
<workspace>/
  object_assets/<asset_id>/<64자리 version>/
    manifest.json
    usd/                         # USDA와 상대 Texture/Material 종속 파일
    visual_*.obj, collision_*.obj, texture_*.png
    source.blend                 # Blender 제작 시 보존
  scenes/<project>/
    input/                       # 이 Scene의 사진·메모·Capture·Robot/Calibration 근거
      evidence.yaml              # briefs 이력 + current_brief 참조
      reconstruction.yaml        # 개별 Object/Group/선택/Mask/요청/Candidate
      object_assets/             # 기존 Legacy만 유지
    working/, scratch/, exports/<revision>/
  devices/
```

Scene Project와 Asset Group/Object Instance 및 Export Revision을 합치지 않는다. 같은 Asset ID/Version을 A/B Scene에서 선택해도 Input/메모/q/Camera/Pose/Config/Candidate는 해당 Scene에 남는다. Revision은 같은 Scene의 불변 결과이며 새 Scene이 아니다. Library는 Geometry/UV/Material/Texture/Collision/Blender 원본을 공유한다. 일반 Scene 사용을 위해 전체 Closure를 Project마다 복사하지 않는다.

### 실제 수정 파일·함수와 참조 계약

| 파일·함수 | 변경과 보호 경계 |
|---|---|
| `project.Project.workspace/create`의 기존 pool 구조 | 선택한 Workspace에서 공용 저장소 위치 결정. 기존 Project 이름/폴더를 바꾸지 않음 |
| `object_assets.register_object_asset/library_write` | 신규 Blender/USDA를 Workspace Library의 staging→rename으로 게시. Project lock과 process 간 flock을 함께 사용. 다른 Scene의 동시 등록은 busy로 거부 후 재시도 |
| `object_assets.asset_manifests/list_object_assets/verify_object_asset` | Workspace와 Legacy 목록/검증. 같은 ID라도 다른 파일은 별도 Version이며 Category/이름으로 병합하지 않음 |
| `scene.local_path` | 일반 package-relative 경계 유지. `../../object_assets/<ID>/<64-hex-version>/<file>`만 제한된 Workspace 참조로 해석. 버전/Traversal/Symlink 검사로 임의 외부 경로는 거부 |
| `object_assets.instance_operation` | Instance의 Asset ID/Version, USDA entry와 Manifest asset key/SHA 기록. Geometry/Collision/Texture는 공용 파일 참조이고 Pose/역할은 Scene에 보존 |
| `object_assets.publish_object_asset`, CLI `object-asset publish` | Legacy를 검증 후 공용 Library에 같은 버전으로 명시 복사. Manifest/파일 충돌은 거부. 원본 및 과거 Scene 참조는 전환하지 않음 |
| `project.clone_project` | 다른 Workspace로 명시 Clone할 때 Current/Candidate가 참조하는 공용 버전만 새 Library에 게시. 무관한 Library 전체를 복사하지 않음 |
| 기존 `export.export_revision/copy_native_asset`, USD/MJCF exporter | Resolver를 통해 읽은 자산을 Package 안에 소유·상대 경로로 재배치. ID/Version/Manifest SHA와 당시 Scene/Evidence 기록 유지. 기존 Export를 갱신하지 않음 |
| `evidence.current_briefs/add_brief`, Workbench `scene_preparation.scene_details/save_inputs` | 현재 메모 선택/표시/저장과 이력을 분리 |
| `automation.note_relation/modeling_groups/run_codex_modeling` | 현재 메모만 분석/인용 검증, 변경된 메모 의존 관계 재검토. 기존 새 요청 우선·생성 Fingerprint·Mask/Depth 검사를 유지 |
| `ui_reconstruction.ReconstructionDialog/configuration/refresh_assets/finished` | 미측정·미모델링 Config Object 복원, 공용/Legacy 목록, 선택/요청/Candidate 보존과 충돌 진단 |

새 Resolver class/Asset DB/Agent Framework는 추가하지 않았다. 공용 Asset 참조는 위의 제한된 경로 namespace만 확장한다. Asset ID/Version/Manifest·파일 SHA·USD Closure 검사를 유지하며 Blender Sandbox를 넓히지 않는다. Blender가 공용 Library를 직접 수정하지 않고 Backend가 검증/등록한다. `.register.lock`은 Workspace 등록 소유권용 작은 파일이며 Stage/Runtime 결과가 아니다.

### Legacy와 Export Revision

Legacy `input/object_assets`는 목록과 기존 Manifest로 계속 읽는다. `object-asset PROJECT publish --manifest input/object_assets/ID/VERSION/manifest.json` 또는 기존 Dialog의 선택 Legacy 등록으로 공용 저장소에 게시할 수 있다. 복사 전 원 Manifest/전체 종속 파일을 검증하고 복사한 모든 파일 SHA를 다시 검사한다. 같은 Asset ID/Version에 다른 내용이 있으면 중단한다. 기존 Scene/Export를 자동 retarget하거나 원본을 삭제하지 않는다. 원하는 Instance만 명시 공용 Manifest로 교체한다.

Export는 공용 USDA/Texture/Collision/파생 Mesh/Manifest를 기존 규칙으로 Closure에 포함한다. 공용 경로를 실행 의존성으로 남기지 않고 `authored_scene.json`의 실제 assets도 Package 내부 경로로 바꾼다. provenance의 원 위치 문자열은 실행 파일 참조와 구분한다. Library의 다음 Version을 만들거나 다른 Scene의 참조를 바꿔도 과거 Export는 원 ID/Version/SHA를 유지한다. Scene/Instance 제거는 공용 버전 삭제 기능을 호출하지 않는다.

### 문제 A — 현재 메모와 이력

이전 UI는 `briefs[-1]`을 표시했지만 `note_relation/modeling_groups`는 과거 briefs 전체를 검색했다. 현재 메모에서 삭제된 동일 제품 문장이 과거 SHA를 통해 user_declared로 다시 인정될 수 있었다.

`add_brief`는 메모를 내용별 파일에 보존하고 `briefs`에 ID/path/SHA 이력을 추가한 뒤 `current_brief`를 갱신한다. `current_briefs`가 UI·Codex 입력·관계 검증·모델링 입력의 공통 선택 함수다. Legacy에 pointer가 없으면 기존 UI와 같은 마지막 메모를 읽기만 하며 원본을 강제 변환하지 않는다. 포인터가 이 Project 이력에 없거나 실제 SHA가 다르면 실패한다. 빈 메모 저장도 현재 기록이며 과거 메모로 fallback하지 않는다.

고급 API `add_brief(..., scene_state=...)`는 배치별 `scene_briefs` 참조도 보존한다. 기본 UI의 메모는 Project의 현재 메모다. 다른 Project 이력은 검색하지 않는다. 이전 Export 안의 당시 Evidence JSON은 수정하지 않는다.

현재 메모 변경 시 메모를 인용한 Group은 해당 인용문을 현재 원문에서 재검증한다. 같은 선언이 유지되면 새 현재 SHA에 연결하고, “다른 제품으로 교체했다”처럼 과거 선언이 사라지면 그 Group을 `ASSET_GROUP_UNRESOLVED`로 재검토한다. 단순 다른 블록 위치 수정과 같은 메모 추가로 무관한 Group을 모두 폐기하지 않는다. 실측·기존 USDA·이전 Export는 삭제하지 않는다. 직접 선택한 Manifest는 기존 검증 경로를 사용한다.

### 문제 B — Object와 미완료 상태 복원

이전 표는 Current Scene과 measurements만으로 행을 만들고, 저장 시 표에 없는 Config Object를 걸러냈다. Codex가 분석한 Object가 치수/Geometry 없이 Config에만 있으면 재오픈 때 사라지고 다음 저장으로 제거될 수 있었다.

이제 Current Scene + 실측 + Config Object의 합집합을 복원한다. USDA/실측/Mask 부재는 누락 이유가 아니다. Group/provenance·Category·명시 자산·modeling_action/request ID·Mask 선택·진행 Candidate를 유지한다. 목록에서 찾지 못한 선택 Manifest도 “확인 필요” 선택지로 보존하고 Backend 검증에서 다룬다. Config 또는 Project의 최근 Candidate를 복원하며 의미 분석 결과에도 Candidate를 기록한다.

화면에 안 보인다는 이유로 Object/측정을 삭제하지 않는다. 선택 물체 삭제는 Reconstruction Config의 명시 제거이며 공용 Asset이나 Current Scene Geometry를 지우지 않는다. Current Geometry 제거는 기존 Candidate 편집으로 별도 수행한다. 보호 실측/역할 충돌은 표시하고 저장을 막으며 조용히 덮어쓰지 않는다. 새 Group/모델 요청은 앞선 v3의 그룹별 ID/완료/부분 재시도 계약을 유지한다.

### 실제 검증과 남은 범위

수정 전 과거 메모 인용 승격과 미측정 Object 재오픈 누락을 각각 실패 시험으로 확인했다. 공용 경로·Symlink·다른 Workspace Clone도 먼저 재현하고 수정했다. 초기 공용 Export 시험의 검토 보고서 누락과 자기 Export에 따른 state 변경까지 불변으로 요구한 harness 오류는 기존 `Candidate.evaluate(engine='mujoco')`와 올바른 보존 구간을 사용해 수정했다. Export 보호를 완화하거나 결과 상태를 조작하지 않았다.

- **메모:** A의 v1 동일 제품 선언→v2 다른 제품 교체에서 현재 관계를 승격하지 않고 해당 Group을 재검토한다. v1 파일과 이력은 보존한다. B 메모를 A의 근거로 쓰지 않는다. 같은 선언을 유지한 채 다른 블록 위치 설명만 추가하면 컵 관계를 새 현재 메모에 연결한다. Legacy 최신 선택은 원 Evidence SHA를 바꾸지 않는다.
- **Qt 복원:** 실제 offscreen Qt의 창 닫기/재오픈과 두 독립 Python/Qt 프로세스에서 `cup1/cup2/red_block` 미측정·미모델링 상태, Group·자산 선택/누락 선택·새 모델 요청 ID·Mask 선택·Candidate를 저장/복원했다. B Scene의 공용 Asset 메뉴도 실제 Qt에서 확인했다. UI에는 USD/torch/엔진 모듈을 import하지 않는다. 화면에 없는 Object의 자동 삭제를 제거했고 명시 삭제는 Config에만 적용한다.
- **A/B 독립성·버전:** 같은 Workspace의 A 두 Instance와 B 한 Instance가 같은 Manifest를 참조한다. B 작업 중 A 자료 SHA와 과거 Export를 보존하고, Version B를 새로 만들거나 B의 Instance만 교체해도 A/과거 Revision은 Version A를 유지한다. Source 삭제나 Instance 제거가 Library 삭제를 호출하지 않는다.
- **동시성·Legacy:** 두 Scene의 별도 프로세스가 공용 등록 소유권을 공유한다. busy 시 두 번째 등록을 거부하고 해제 뒤 같은 자산 등록은 idempotent다. Legacy publish의 API/CLI·모든 종속 SHA/동일 Version·원본/Scene 참조 불변을 확인했다. 다른 Workspace Clone은 실제 참조 버전만 게시하고 무관한 자산을 복제하지 않는다.
- **독립 Export:** 공용 Library를 분리한 뒤 A/B Export의 Manifest/Closure를 검증했다. 기존 실제 OpenUSD reference/UV/Texture와 MuJoCo compilation/접촉 회귀도 통과했다. JSON parser 결과만으로 물리 Task 성공을 표시하지 않는다.

추가 실제 harness는 `workbench_runs/workspace_library_20261104/check_workflow.py`다. 통제 컵 스크립트를 **실제 Blender에서 한 번** 제작해 공용 USDA 1개를 등록하고 A 두 Instance/B 한 Instance로 사용했다. 각 Scene의 독립 합성 metric 점군으로 기존 `fit_clouds`를 실행해 12mm/6mm 초기 XY 오차를 줄이고, 실제 MuJoCo 640×480 RGB와 Review Export를 만들었다. 두 Scene 모두 ESTIMATED이며 수치 이동 잔차는 약 7.45e-10m였다. 이는 정확히 알려진 합성 Mesh 표본의 수치 결과이며 실사진/mm 정확도 증거가 아니다. Cup의 회전 대칭은 기존 보고서의 ambiguity를 유지한다. Package를 Library 없이 검증한 뒤 예제 탐색을 위해 예제 Library만 복원했다.

이번 새 원격 Codex 호출·실제 SAM/DA3 재추론·실물 연결은 **0회**다. 의미 분석/Mask/Depth 경계는 기존 통제 응답 회귀이며 Blender/OpenUSD/MuJoCo·Qt는 실제 실행이다. 실제 Side/Wrist/Robot 촬영부터 원격 분석→전체 재구성까지의 새 무인 실물 E2E, 독립 사진 정확도, Isaac runtime/물리 Task 승인, 장시간/전원 장애는 새로 검증하지 않았다. 기존 Pair Source/q/Calibration/Export 보호 회귀는 유지했다.

전체 명령:

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short --junitxml=/tmp/workspace-library-release.xml
```

최종 전체 **1,281 passed / 66 failed / 28 errors / skipped 0**(1,375 case, 232.17초, 기존 경고 2회). 직전 v3 Baseline의 실패/오류 94개와 test name/kind 집합이 같으며 **신규 실패 0**이다. 전체 GREEN은 아니며 과거 USD fixture/이전 UI 기대값 등의 기존 실패는 그대로다. 이번에 9개 회귀 사례를 추가했다. 마지막 UI의 보이지 않는 측정 보존/명시 삭제의 supports·Mask 참조 정리는 별도 실제 Qt 검사로 재확인했다. 최종 집중 결과·구문/보존 대조는 아래 verification에 기록한다.

최종 집중 **65 passed**, 마지막 Qt **4 passed**, 변경 Python **35개 구문 검사**와 `git diff --check`를 통과했다. `check_portable.py`로 예제 Library를 실제로 사용할 수 없게 한 상태에서 A/B Package의 **OpenUSD Stage/Reference Mesh 로딩과 MuJoCo 모델 compilation**도 확인했다. 첫 portable harness의 `/Asset/Visual` 가정은 Blender가 `/Asset/cup/...`를 출력하는 계층과 달라 실패했고, 실제 Reference 아래 Mesh를 검사하도록 수정했다. 제품/Asset을 바꿔 이 진단을 숨기지 않았다. 결과는 `portable-results.json`이다. OpenUSD parser 로딩은 Isaac Sim 런타임 실행과 구별한다.

원본 Project/Current/input(촬영·메모·Calibration·Robot/Asset)/configuration/과거 exports **2,389개 SHA 변화 0**을 확인했다. 전체 SDK/corpus 전수 hash는 아니다. 새 공용 기능의 검증 자료는 별도 통제 Workspace에서만 만들었다. 원본 내부 Library를 이 작업에서 일괄 publish/이동하지 않았다. 실제 Workspace 공용 폴더는 첫 신규 등록/publish 시 생성하며 기존 Project는 Legacy 선택을 유지한다.

`.gitignore`, main=`ab94b87d3f579031db0c751f274c0ab7fe6b87e6`, workflow-restoration=`5030b48487271b8ec3178467f7141143d4ee0522`와 현재 HEAD는 유지한다. 기존 미커밋 변경을 포함해 현재 Git 변경 경로는 40개이며 이 작업에서만 새로 40개를 수정했다는 뜻이 아니다. 설치/모델/SDK 변경·원본 삭제·Commit/Push/Merge는 없다.

근거는 Git 제외 `workbench_runs/workspace_library_20261104/`의 `verification.json`, `baseline-comparison.json`, 원본 보존 전후 SHA, 최종 전체/집중 JUnit·RED/GREEN 로그, `check_workflow.py`/`workflow-result.json`, `check_portable.py`/`portable-results.json`, 통제 `example_workspace/`다. 가중치/Runtime/학습 결과를 복제하지 않았다. 사용법은 [자동 Scene 제작](../real2sim_builder/AUTO_SCENE_FITTING.md)의 최신 Workspace 절, [제작 지침](../real2sim_builder/SCENE_AUTHORING.md), [규칙](../real2sim_builder/SCENE_RULES.md), [Workbench 안내](builder-scene-guide.md)에 맞췄다.

## 2026-11-04 — Scene 메모 처리 책임 정리

이 절이 현재 메모 계약이다. 앞선 v3/Workspace 절의 `add_brief/current_briefs`, 메모 정규표현식·현재 포인터·새 SHA로 관계 재결합 설명은 당시 구현 기록이며 아래 방식으로 대체했다. 공용 Asset Library, Workspace Clone/이관 기능 자체는 이번 작업에서 변경하지 않았다. 브랜치 `feat/auto-real2sim`, HEAD `eb1a639ba1dc8cb4870c5f7609fb1d4d5333797a`와 이전 작업의 미커밋 변경은 유지한다.

### 조사·제거와 현재 호출 경로

기존 흐름은 Scene Prepare `save_inputs` → 임시 MD → `add_brief` → 내용별 메모 파일·`evidence.briefs/current_brief/scene_briefs` → `current_briefs` → 표시/모델링 입력이었다. `automation.note_relation`은 언어별 동일/상이 제품 표현·대상·긍정 선언을 다시 판별했고 `modeling_change_evidence`는 형상/무늬/재질 키워드로 변경 근거를 판별했다. Codex가 해석한 의미를 Backend가 다시 분류하고, 같은 문장이 남아 있으면 과거 관계를 새 메모 SHA에 재결합하는 책임이 있었다.

현재 흐름은 다음과 같다.

```text
SceneInputs.saveRequested(files, literal_text)
  → scene_preparation.save_inputs
  → evidence.save_scene_memo → input/scene_memo.txt
  → scene_details / evidence.scene_memo → 같은 원문·UTF-8 SHA
  → reconstruct: 미해석/변경 메모이면 SAM/DA3 전에 분석 작업자료 생성
  → modeling_tasks: Candidate에 당시 메모 고정 + 사진/선택 Capture 배치/q/시각/기존 Object/실측
  → 명시 run_codex_modeling: Codex가 원문·사진을 해석
  → parse_scene_analysis: 응답 구조·인용 출처·SHA 검사
  → input/reconstruction.yaml Object/Group 저장
  → 기존 SAM→DA3→Blender/Library→정합→Candidate/Export
```

현재 Codex 대화에서도 같은 작업자료/Schema를 사용한다. 사용자가 자연어를 특정 단어 목록이나 JSON으로 바꿀 필요는 없다. 최초 미해석 메모에서는 객체가 이미 수동 설정돼 있어도 새 설명을 건너뛰지 않는다. Pair 재정합은 원 Revision의 Geometry를 보존하는 기존 경로를 유지한다.

삭제한 활성 API는 `note_relation`, `modeling_change_evidence`, `current_briefs`, `add_brief`다. 관련 호출자·이전 정규표현식 시험을 새 원문/구조 계약으로 바꿨으며 제품 코드에 옛 응답을 임의 보완하는 호환 분기를 추가하지 않았다. `briefs/current_brief`는 canonical 파일이 없는 과거 Project에서 현재 또는 마지막 메모 한 개를 읽는 최소 호환에만 남긴다. 배치별 `scene_briefs` 선택·과거 문장 병합·새 이력 append는 하지 않는다. 과거 파일/Export는 삭제하지 않는다.

### 저장·Codex 입력과 응답 계약

현재 저장 위치는 `<workspace>/scenes/<project>/input/scene_memo.txt`다. 원자 저장하고 같은 bytes 저장은 mtime/내용을 바꾸지 않는다. 빈 메모를 저장하면 빈 파일이 현재이며 이전 문장으로 돌아가지 않는다. UI 안내는 placeholder다. Qt에서 수정하지 않은 원문을 다시 저장할 때도 CRLF·언어·기호를 유지한다. 텍스트를 JSON으로 전달할 때는 JSON parser를 사용해 YAML parser의 surrogate pair/이모지 차이를 피한다.

`modeling/tasks.json`에는 한 `scene_memo`의 원문/SHA와 고정 파일 경로, Object/Group·명시 실측, 등록 사진과 선택 Capture의 관측 metadata, Camera/Robot의 기존 수치/identity가 들어간다. 미등록 참고 사진도 문맥으로 전달하되 metric 등록/실측 q를 발명하지 않는다. CLI 입력의 원문·고정 파일 bytes·현재 signature/SHA를 시작 전과 종료 후에 확인한다. 원문이나 modeling_notes에 등장한 경로 문자열을 파일 접근 명령으로 사용하지 않는다. SHA를 갖춘 등록 입력 참조만 복사하며 기존 Codex/Blender sandbox는 유지한다.

`scene_analysis_schema()`가 Codex용 계약을 정의한다. Object 종류/개수·Instance·Group·사용자 명시 관계와 사진 추론의 구분·형상/외형 변경은 Codex가 판단한다. Python `parse_scene_analysis`는 정확한 필드/타입, Object/Group ID 중복, Group 멤버/참조, Image ID/중복 View/finite Box, 현재 메모 SHA, 정확한 인용문 substring 존재만 검사한다. 추가 필드나 임의 치수/q/Calibration을 분석 응답에 넣어 실측으로 만들 수 없다.

관계는 `relation_source=user_memo|visual_inference|unknown`, `evidence_quote`, `members`, `change_kind=none|geometry|appearance|uncertain`과 근거를 기록한다. 사용자 명시 출처는 user_declared/CONFIRMED, 사진 추론은 estimated/PROPOSED, 불명확한 관계는 UNRESOLVED다. **인용문 존재는 의미나 실물 동일성의 증명이 아니다.** 모든 분석 관계에 `semantics_verified=false`와 해석 주체를 남긴다. 같은 제품 선언이 SAM Mask 대응을 대신하지 않으며 Mask 중복/개수/Association·실측 치수 충돌·USDA/Manifest/Closure SHA 검사와 물리 검증 경계는 유지한다.

### 수정·재열기와 자산 호환

메모가 바뀌면 과거 응답은 당시 SHA를 유지하고 새 해석을 요청한다. 과거 인용문이 새 원문에도 남아 있다는 이유로 Backend가 과거 관계를 재승격하지 않는다. 새 Codex의 Group별 변경 종류와 실측/형상 조건에 따라 해당 자산을 검토하고 무관한 USDA를 일괄 재모델링하지 않는다. 명시 자산·새 모델링 request ID·완료/부분 실패 재시도 우선순위는 유지한다. Codex가 저장 Object를 응답에서 누락해도 자동 삭제하지 않고 미해결 검토로 남긴다.

같은 작업자료를 다시 요청하면 `scene_analysis`의 응답 경로/SHA·Schema를 확인해 재사용한다. UI 재열기/동일 메모 저장만으로 모델을 호출하지 않는다. Object/Group/선택 USDA/배치 설정은 기존 Config로 복원한다. A/B Project의 메모/분석은 섞지 않는다.

Candidate의 `modeling/scene_memo_<SHA>.txt`와 `modeling/codex/<job>/answer.json`은 실행 입력/응답 보존이며 새 메모 버전 관리 시스템이 아니다. 새 Export는 당시 메모 원문을 `scene_memo.txt`로 소유하고 `provenance.json` 및 Manifest에 SHA를 고정한다. 이후 현재 메모를 바꾸거나 Export를 이동해도 이전 Package는 불변이다. signature 계약이 바뀌었으므로 예전 열린 modeling task/검증 보고서는 기존 재구성/검토 경로에서 갱신해야 한다. 과거 Revision은 자동 수정하지 않는다.

### 검증·한계

관련 집중 회귀 **94 passed / failed 0 / errors 0 / skipped 0**. 최종 전체는 **1,297 passed / 66 failed / 28 errors / skipped 0**(1,391개, 기존 경고 2회)다. 직전 기준 **1,281 passed / 66 failed / 28 errors**(1,375개)와 testcase 이름·failure/error 종류를 대조해 기존 실패/오류 94개가 모두 동일하고 신규 실패 0·해결 0임을 확인했다. 폐기한 자연어 의미/이력 시험을 새 계약 시험으로 교체했고 순증 16개다. 기존 fixture 자산 부재·UI 기대값 등의 실패를 통과시키려고 제품 차단·시험을 임의 변경하지 않았다. 실행 명령: `REAL2SIM_BLENDER=<기존 설치 Blender> bash docs/evidence/builder/run_tests.sh real2sim_builder/tests robot_learning_workbench/tests scene_contract/tests -q --tb=short --junitxml=workbench_runs/scene_memo_refactor_20261104/full-suite.xml`. 상세 비교는 `baseline-comparison.json`과 `verification.json`이다. 주요 검사는 다음과 같다.

- 한국어·영어·일본어 등 다양한 문장의 구조 응답 수락, 존재하지 않는 quote/이전 SHA 거부. Fake Codex로 계약을 검사했으며 실제 자연어 이해 정확도 시험이 아니다.
- Fake CLI에 원문/줄바꿈/이모지 전달, 일반 문장의 사적 JSON 경로 비수집, 잘못된 JSON/중복 ID/없는 Group/잘못된 Box/중복 View 거부, 실패 응답 진단 보존.
- 실제 Qt 저장 버튼→Backend Input 저장→Fake CLI 분석→Object/Group/선택 USDA 저장→새 Qt process 재열기. Scene별 메모 독립성·빈 입력·Legacy 원본 불변·같은 내용 재저장·고정 메모 변조·응답 SHA 변조·중복 호출 방지를 확인했다.
- 실제 Blender의 열린 컵/Texture/분리 Collision 자산 1개→Instance 2개→MuJoCo RGB, Group별 새 요청/부분 실패 재시도, 공용 Library·독립 Export, Mask 개수 충돌·실측 보호 회귀를 유지했다. 합성/통제 fixture이며 실제 촬영 정합 정확도/새 로봇 구동 증거가 아니다.
- 기존 Project/Current/input/Calibration/Robot/과거 Export **2,389개 SHA 변화 0**. 전체 SDK/corpus 전수 hash는 아니다. 실제 Workspace 공용 Library는 아직 첫 등록 전이며 공용 자산 회귀는 별도 임시 Workspace에서 수행했다.

수정된 Python 40개(이전 미커밋 작업 포함)의 bytecode 없는 compile과 `git diff --check`를 통과했다. 이번 메모 작업에서 변경한 경로는 19개이며 이전 작업을 포함한 전체 미커밋 경로는 45개다. `.gitignore`·main·workflow-restoration·현재 HEAD와 staging은 그대로다.

이번 작업의 새 원격 Codex 호출, 새 실제 SAM/DA3 inference, 실물 연결/모터 명령은 모두 0이다. Blender/OpenUSD/MuJoCo와 Qt 회귀 실행은 실제 설치 환경을 사용하며 설치/업그레이드하지 않았다. 독립 실사진/실측 정확도, 일반 자연어 해석 정확도, 전체 PhysX Task, 장시간/전원 장애는 새로 검증하지 않았다. Commit/Push/Merge와 Workspace 복제/이관 변경은 수행하지 않는다.

사용법은 [단일 자유 메모 계약](../real2sim_builder/AUTO_SCENE_FITTING.md)에 반영했다. 소량 로그/JUnit·SHA/기준 비교는 Git 제외 `workbench_runs/scene_memo_refactor_20261104/`에 보관하며 모델 가중치/Runtime/전체 임시 결과는 복제하지 않는다.


## 2026-11-05 — 다중 시점 구조 재설계 및 통합 Scene Memo

후속 작업은 `feat/real2sim-multiview`, 기준 `14996df88f54e7e6d2deb997a6553cf94df75595`에서 진행했다. 위의 역사적 단계별 수치는 당시 실행 기록이며 현재 결과로 소급 수정하지 않는다. 현재 코드 감사·교체 목록·실제 호출 흐름·시험 결과·남은 범위는 [다중 시점 파이프라인 보고서](real2sim-multiview-architecture.md)에 기록한다.

Scene Memo에는 실측 치수도 포함된다. Codex가 원문/사진을 이해하고 Python은 구조화된 값만 검증·실행한다. 별도 필수 치수 표는 삭제했으며 기존 측정 데이터는 보존한다. 후속 전체 1,330 passed, baseline과 동일한 66 failed/28 errors, 신규 실패0이다. 이후 중단 체크포인트 수정의 관련19개도 통과했다. 일반 물체의 추정 appearance/lighting 공동 변수와 Isaac native 반복 렌더를 추가했고 기존 Workbench 정적 Isaac 렌더를 같은 구현으로 통합했다. 앞서 실패한 동일 MuJoCo 컵 낙하는 접촉 응답 수정 후 관통 없이 통과했다. 실제 사진의 완성 Scene E2E·독립 정확도, 공용 Asset의 자동 Material Variant·distortion 정합은 미완료다. 물리 준비 완료나 전체 자동화 완료로 표시하지 않는다.
