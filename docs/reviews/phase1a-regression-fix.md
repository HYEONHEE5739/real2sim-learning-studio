# Phase 1A — 핵심 결함 수정 및 아키텍처 회귀 검증

2026-11-14. 브랜치 `feat/simfoundry-style-reconstruction`, 기준 HEAD `97c029e195ab8587603fb3f240f2c1a6c0f91f52`. 사용자 Phase 1A 첨부 사양과 [기존 감사](full-codebase-audit.md)의 BUG-001–004를 현재 코드에서 재현한 뒤 순차 수정했다. 추가 A/B는 분석만 했다.

**COMPLETED — BUG-001–004 수정, 전체 1,927 passed / 실패0·오류0·skip0.** 기존 1,864개 시험 누락0·신규63개이며, 보호 자료 19,612개 파일의 변경·누락·신규0을 확인했다. 기존 감사 문서는 변경하지 않았다. 작업 시작 시 Index/추적 파일은 깨끗했고, 미추적 `full-codebase-audit.md`만 있었다. 과거 작업의 staged 23개 상태를 이번 시작 상태로 간주하지 않았다.

실행 근거는 저장소 밖 `/tmp/real2sim-phase1a-20261114-0bk3qjne/`에 있다. 임시 자료는 Git에 포함되지 않으며 삭제되면 보고서의 원시 로그를 다시 열 수 없다. 사용자 자료가 아닌 합성 Project/URDF/RGB·Fake 장치만 새 테스트에 사용했다.

## 1. 수정 요약

| 결함 | 확인한 원인 | 수정 후 행동 |
|---|---|---|
| BUG-001 | `fit_cameras`가 보호 Camera Pose도 최적화하고, 구형 `run`이 분석/기하/외관 중간 결과를 Current에 저장했다. 자동 `undistort_evidence`도 원 보정/관측을 재작성했다. | 기존 `editing.PROTECTED`의 Pose는 fit에서 제외. trial은 기존 scratch에 `validate`·`preserve` 후 저장. 검증 합격 때만 Current를 게시하고 이후 실패/Stop은 이전 Current의 정확한 바이트로 복원한다. |
| BUG-002 | 실제 `PrecisionSession`은 `CALIBRATED_MANUAL`을 쓰지만 Capture/Snapshot 공통 Reader가 이를 거부했다. | 기존 `mapping_contract` 한 곳에서 현재 상태와 Legacy `REVIEWED_MANUAL`/`VALIDATED_MANUAL`을 허용한다. 모두 관측용 수동 보정이며 독립 물리 검증이 아니다. |
| BUG-003 | Bound import가 모델/Mapping SHA·단위·역할을 누락하고, Unbound는 역할을 누락했다. Stage10은 역할 필드만 직접 검사했다. | Writer가 명시 역할을 추가하고, Bound/Unbound가 검증된 Manifest의 Identity·단위·역할을 같은 작은 Adapter로 전달한다. Sensor Registration과 Stage10은 기존 역할 해석 계약을 사용한다. |
| BUG-004 | Joint Solver의 `_posed`가 baseline의 FK만 복사하면서 Camera의 view별 Pose/K/Pixel 변환과 trial 변경을 버렸다. | 각 residual 평가에서 이미지별로 `observation_scene(trial, image, ...)`을 호출한다. 같은 이미지의 landmark는 그 평가 안에서 결과를 재사용한다. 별도 Camera 수학은 만들지 않았다. |

### BUG-001 — Current와 보호 Calibration

`cli.main → reconstruction.run → fit_cameras`의 공개 경로·인자는 유지했다. `Project.save_scene` 자체를 전역 변경하지 않았다. 이 API는 명시 입력·로봇·Capture import에도 사용되므로, 자동 실행의 보호를 구형 `run` 경계에 적용했다. Candidate의 기존 `validate`/`preserve`와 같은 보호 함수를 사용한다.

기존 Current가 있으면 분석·기하·물리·외관 trial을 `scratch/candidate/scene.yaml`에만 저장한다. 합격 후 게시 직전에도 검사하고 Current가 시작 바이트와 달라졌으면 게시를 거부한다. Export가 Current를 읽는 기존 계약 때문에 합격 결과를 먼저 게시하되, Export/상태 갱신까지 성공하기 전에는 임시 backup을 유지한다. 실패/Stop이면 원자적 파일 교체로 원 바이트를 복원하고 lock/backup을 정리한다. 잘못된 기존 YAML을 읽다가 실패하는 경우에도 lock을 남기지 않는다. 기존 불변 Revision을 다시 쓰는 경로는 추가하지 않았다.

**호환성 예외는 기존 Current가 없는 새 Project의 첫 미확정 draft 생성**이다. 이미지 입력만으로 CLI를 시작한 뒤 부족한 근거를 요청하는 기존 동작을 유지한다. 기존 Current를 실패 중 덮어쓰는 것과 구분한다.

원본을 바꾸는 자동 undistortion을 제거하고 Renderer의 기존 transient pinhole/lens warp를 사용한다. 명시적 `undistort_evidence` API와 그 테스트는 그대로다. 보호 Camera를 `optimized`로 내려서 우회하지 않는다. estimated Camera의 기존 PnP/least-squares 수학은 유지했다.

### BUG-002 — 수동 보정 상태와 검증 의미

실제 `PrecisionSession.calculate → save/자동 적용 → load_profile → PrecisionMapper.metadata → Capture save_session 또는 SnapshotStore.prepare → load_session/mapping_contract`를 연결했다. Fake 장치의 `connect`, `release_for_calibration`, `sample`은 호출되면 실패하도록 막았다. 실제 모터/토크 API는 변경하지 않았다.

현재/구형 상태 모두 `physical_verified=false`를 유지한다. Mapping SHA·source URDF·Joint Order·rad 단위·유한/비영 계수 검사는 유지하고, bool을 계수로 사용하는 경우와 joint별 물리 검증 승격도 거부한다. Workbench의 참조 기록으로 계수를 재구성하는 기존 검증도 실제 호출했다. Builder의 portable validator가 모든 임의의 재해시된 비영 계수를 독자적으로 재추정한다고 주장하지 않는다.

### BUG-003 — Writer부터 Stage10까지

Continuous Capture, Snapshot, Pair 각각의 Bound/Unbound 경로를 실제 Writer/Reader/Import에 연결했다. 기록된 `q_measured`, Joint Order/Units, 모델/Mapping SHA를 소비 관측 행에 그대로 전달한다. Pair의 Sim baseline q를 실제 측정 q 대신 쓰지 않는다. 새 Writer의 `camera_type`은 이미 고정되어 있던 Side/Wrist 슬롯의 명시적 표현이다. 기존 schema와 필드를 제거하거나 변경하지 않았다.

구형 Writer의 **정확한 `side`/`wrist` stream ID**는 기존 `observations.camera_type` 계약으로 읽는다. 이미지 파일명·좌우 위치·Mount 추측으로 역할을 정하지 않는다. 임의 ID는 명시된 정상 역할이 필요하고, 없거나 알 수 없으면 import를 거부한다. 같은 센서가 세션 사이에서 다른 역할로 바뀌는 것도 거부한다.

Sensor Registration에서 기존 모델이 있으면 Side/Wrist 모두 모델/Mapping/Joint Order를 대조하고, 기존 `validate_joint_units`로 실제 URDF/MJCF의 rad/m 단위를 확인한다. Side의 고정 Camera와 Wrist의 공유 link Mount·측정 q 기반 FK는 유지한다. Scene Photo/Model Reference는 Capture로 바꾸지 않는다.

구형 정상 archive를 **다시 import하는 읽기 경로**와 역할만 빠진 기존 Unbound 관측의 Stage10 사용을 확인했다. 과거 결함 때문에 이미 Bound-import된 관측에 Identity 자체가 없는 경우를 자동 마이그레이션하거나 사용자 evidence에 새 hash를 써 넣지는 않는다. 그 자료의 복구는 원 Manifest 검증과 별도 명시 작업이 필요하다. 누락 Identity를 허용하는 fallback은 추가하지 않았다.

### BUG-004 — 이미지별 Camera Adapter

외부 Photo 두 장이 하나의 calibrated K/distortion을 공유하면서 각기 다른 Extrinsic을 가지는 실제 등록 경로를 검사했다. 전역 Pose가 null이어도 정상 처리한다. 두 번째 사진의 EXIF 180°·crop/resize affine·비영 tangential distortion도 기존 Adapter로 반영한다. 한 View만 perturb하면 해당 residual이 바뀌고 view 변수가 실제로 작동한다.

baseline FK-only 복사 함수를 제거했다. 모든 등록 View의 사전 검사는 유지하며, trial마다 Camera/K/Pixel grid·로봇 FK를 기존 Adapter로 다시 구성한다. 이는 trial을 정확히 반영하기 위한 CPU 비용이 있고 대규모 View 성능 비교는 별도로 측정하지 않았다. Adapter는 원 Scene을 수정하지 않는다.

Holdout은 보고/기존 veto에만 쓰고 변수를 만들거나 train residual에 넣지 않는다. `holdout_policy=report_only`에서 Validation landmark만 바꿔도 fitted Scene과 train report가 정확히 같음을 확인했다. 보호된 Side Calibration·공유 Wrist Mount·모델 Identity 및 서로 다른 q의 FK도 확인했다.

## 2. Architecture Impact

| 변경 경계 | Producer → Consumer / 영향을 받는 Caller | 유지한 계약 |
|---|---|---|
| 자동 Current 게시 | CLI `run` → `reconstruction.run` → 기존 fit/validation/export | CLI 명령/인자, Project/Candidate/Revision 소유권, estimated fit, 기존 보호 함수 |
| 수동 Precision 상태 | PrecisionSession/Mapper → Continuous/Snapshot/Pair → Builder `mapping_contract` | schema, hash/URDF/계수/순서/단위, 수동 보정과 물리 검증 구분 |
| Capture Identity | Workbench Writer → `load_session/load_snapshots` → Bound/Unbound import → `register_sensor_views` → Stage10 | 측정 q·역할·Frame/단위·공유 Sensor Parameter, source archive 불변 |
| Joint projection | Candidate/geometry/hybrid/Stage10/Numeric → `fit_joint_scene` → `observation_scene` → `project_point` | Optical Frame·Meter·World/FK 순서, 보호 Calibration, train/holdout 분리 |

공개 함수/메서드의 인자 AST를 시작 HEAD와 대조한 8개 제품 파일 모두 동일했다. `cli.py`, `project.py`, `candidate.py`, `ui_reconstruction.py`, Numeric acceptance, Renderer, Policy/Trainer/Task·Robot Control은 수정하지 않았다. 새 의존성/Manager/Framework/Registry/실행기는 없다. 기존 모듈 안의 작은 private 관측 Adapter만 추가하고 불완전한 private `_posed`는 제거했다.

`camera_type`의 명시 역할 우선 해석은 유지하며, default 표현식이 불필요하게 `image['camera']`를 먼저 읽던 동작만 없앴다. 이를 Stage10에서도 공통 사용한다. 완료 Artifact/Cache를 새 의미로 재해석하거나 삭제하지 않았다.

## 3. Regression Evidence

### 순차 RED → GREEN

수정 전 집중 baseline은 **134 passed**, 실패/오류/skip 0, 46.55초였다. 아래 Green은 해당 새 시험과 관련 기존 시험을 함께 실행한 값이므로 서로 합산하지 않는다.

| 결함 | 수정 전 재현 | 수정 후 집중 검증 | 주요 검증 |
|---|---|---|---|
| BUG-001 | 11개 중 **9 failed / 2 passed**, 2.42s | **67 passed**, 8.58s | measured/calibrated 불변, estimated fit, 실패·Stop·2회 재시도, 원문 comment/Current bytes, 보정·관측 불변, 잘못된 보호/행렬 거부, 실제 CLI dispatch, Export 실패 rollback, lock 정리 |
| BUG-002 | 29개 중 **6 failed / 23 passed**, 3.55s | **95 passed**, 16.45s | 현재/Legacy 수동 상태 Writer→Reader, 변조 hash/URDF/zero/bool 계수/순서/단위/물리 flag/미지원 상태 거부, 원 profile 근거와 계수 재검증 |
| BUG-003 | 17개 중 **14 failed / 3 passed**, 6.39s | **94 passed**, 111.99s | Continuous/Snapshot/Pair × Bound/Unbound, 비표준 ID·명시 역할, 잘못된/없는 역할 거부, Identity 충돌, 구형 Archive, 실제 Sensor Registration→Stage10→FK, 원 archive SHA |
| BUG-004 | 5개 중 **4 failed / 1 passed**, 2.16s | **91 passed**, 45.25s | 두 Photo·global Pose null, view residual/변수, EXIF/pixel affine, Holdout 불사용, 고정 Side·두 q의 Wrist, 기존 Native Numeric refinement |

BUG-004 수정 전 특정 View의 residual은 21.628694687px였으며, 정상 `observation_scene` 기준 1.817143500px와 달랐다. 수정 후 같은 Adapter 기준으로 일치하고 합성 복원 residual은 테스트 기준 1e-5px 미만이다. 이 값은 합성 수학의 정확도이며 실제 Camera/Metric 정확도가 아니다.

중간 실패도 보존했다. BUG-001의 손상 YAML lock 회귀를 추가 재현해 수정했다. 기존 Camera fit 시험 두 개의 calibrated seed를 **estimated seed**로 바꿨다. 보호 Camera를 움직이던 옛 기대가 새 보호 요구와 모순되기 때문이다. 기존 solver AST 대조는 새 보호 guard를 정확히 검사한 뒤 그 한 guard만 제거하고 나머지 원본 수학 전체 AST를 계속 비교한다. 시험/기대 검사를 삭제하거나 skip/xfail하지 않았다.

### 전체 회귀 — 최종 결과

기존 `docs/evidence/builder/run_tests.sh`를 `/tmp`에 복사하여 HF/XDG cache 출력만 이번 임시 폴더로 돌렸다. 원본 실행 스크립트와 기존 환경은 변경하지 않았다. 설치된 Blender 경로를 지정하고 다음을 실행했다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash /tmp/real2sim-phase1a-20261114-0bk3qjne/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short \
  --basetemp=/tmp/real2sim-phase1a-20261114-0bk3qjne/release-full-temp \
  --junitxml=/tmp/real2sim-phase1a-20261114-0bk3qjne/release-full.xml
```

**1,927 passed / 실패0·오류0·skipped0**, Console **574.03초**, JUnit **573.940초**, exit 0이다. 이전 감사의 JUnit 1,864개 testcase ID를 Counter로 대조해 기존 누락0·추가63개를 확인했다. 신규 수는 Current12 + Precision29 + Capture17 + Joint5이며 기존 시험명은 삭제하지 않았다. 별도의 Rank/Qt Refit 분석 probe도 마지막 수정 상태에서 **2 passed, 2.05초**였다. 집중 실행과 전체 실행의 통과 수를 합산하지 않는다.

경고 5개는 JUnit `record_property`/xunit2 경고1개와 torchvision 영상 API deprecation4개다. 시험 오류나 skip으로 처리하지 않았다. 변경 Python **13개**의 bytecode 없는 compile, 제품 **8개 파일**의 공개 Signature AST 불변, 관련 제품/공개 진입 모듈 **11개**의 실제 import와 기존 USD import, `git diff --check`를 확인했다. Import 검사는 모델/장치 생성자를 호출하지 않고 GPU를 비활성화했다. 전체 회귀를 실행한 Python은 기존 `lerobot-arena` 3.11.15, NumPy1.26.0, SciPy1.15.3이다.

새 시험은 실제 serializer/등록/PnP/SciPy solver/FK와 최소 Fake 장치·Renderer를 사용한다. BUG-001의 합격/Export 실패 시나리오는 실제 CLI/`run`에 Fake Renderer/합격 report를 넣은 경계 검증이며 실제 장면 합격을 뜻하지 않는다. 기존 전체 회귀의 Native parser·MuJoCo/EGL·Qt/OpenGL/Sandbox Blender, 일부 작은 랜덤 초기화 CPU Policy Forward와 실제 AI Reconstruction/Isaac/하드웨어 검증을 구분한다.

## 4. 추가 의심 사항 — 분석만 수행

### A. Jacobian Rank와 결과 채택: 불일치 확인

실제 `fit_joint_scene`은 data-only scaled Jacobian의 Rank 부족을 `needs`에 기록하지만 수용 veto로 사용하지 않는다. 보호/Scene validation·bound·cheirality·Camera/pose/object 회귀·Holdout·aggregate improvement를 통과하면 `IMPROVED`일 수 있다. Stage10은 반환 Scene을 사용하고 Candidate에 저장할 수 있다. 반면 `automation.refine_numeric_pairs`는 `rank < parameter_count`면 `UNRESOLVED`로 바꾸고 원 Scene/Best를 유지하는 명시 정책이 있다. 공유 Solver가 미검증 draft를 반환하고 Numeric caller가 더 엄격한 정책을 쓰는 코드 차이는 확인했으나, Stage10에서 왜 이 veto를 생략했는지 의도까지 확인하지는 못했다.

합성 동일 CAD 점 4행·고정 calibrated Side·object pose6에서 **rank 2/6, IMPROVED**, RMSE 1.344252288 → 약 9.32e-10px였다. Stage10은 변경 Pose를 Candidate에 `optimized`로 저장했고 Numeric은 solver `UNRESOLVED`/전체 `NEEDS_MORE_DATA`, 채택 iteration 0으로 원 Pose를 유지했다. Current는 바뀌지 않았다. 같은 한 점으로 회전/깊이 전체를 결정할 수 없으므로 전체 Pose의 provenance를 6자유도 모두 확인됐다는 뜻으로 쓰면 안 된다. 결과는 기존 `OPTIMIZED_UNVERIFIED_DRAFT`/`physical_verified=false`와 Rank 경고를 유지한다.

이 probe는 cloud 생성·이미 준비된 sensor registration·Numeric render metric을 stub으로 제한했다. 실제 Solver/Stage10 caller/Candidate save/Numeric 채택 로직은 실행했다. Stage10 전체 모델 실행이 아니다. **최소 후속안:** Stage10 caller에 Numeric과 같은 Rank veto를 적용하고 기존 Scene을 유지하며 보고서만 남긴다. 공유 Solver를 바꾸기 전 직접 Candidate/hybrid Caller의 draft 의미를 확인해야 한다. 이번에는 수정하지 않았다.

### B. Refit Capture/Scene State: UI 오류 확인, 검사한 Backend는 차단

실제 Qt `ReconstructionDialog`의 Candidate 재사용과 `configuration()`은 선택 Capture ID와 별개로 Project의 마지막 runtime-baseline Layout을 고른다. 선택 A/Layout A 뒤에 미선택 B/Layout B가 있으면 config는 A ID를 유지하면서 Layout B를 고른다.

같은 probe의 실제 Backend `refit_pairs`는 Layout·선택 ID·Source Identity 교집합이 비어 **NEEDS_MORE_DATA / PAIR_SOURCE_UNRESOLVED**를 반환했다. Candidate 생성 0, evidence 변경 0이었다. 검사한 서로 다른 ID 사례에서 B 데이터를 대신 사용하거나 Layout을 섞은 결과는 없었다. config probe의 Source Identity는 합성이며 실제 Package 로딩 성공 근거가 아니다.

기존 `pair_source`는 Source/Pair SHA·Package/Scene·모델/Mapping을 확인하고 Candidate 재사용도 Source Revision/Layout을 확인한다. 기본 SnapshotStore의 중복 Dataset ID 차단과 `static_layout_verified=false`는 유지했다. 같은 Layout label만으로 실제 물체가 그대로였음을 증명하지 않는다.

**최소 후속안:** 선택 Capture와 Source Identity에 해당하는 유일 Layout을 먼저 결정하고, 누락/여러 Layout을 거부하며 그 결과를 config와 Candidate 재사용 양쪽에 공유한다. Backend의 기존 Identity 검사를 유지한다. 이번에는 수정하지 않았다. 추가 P0 원본 손상/명백한 하드웨어 안전 문제는 재현되지 않았다.

## 5. 변경 파일·SHA·보존

제품 8개, 기존 시험 1개, 새 시험 4개, 이 보고서 1개가 이번 변경 범위다. 기존 감사 문서는 보존 대상이다.

| 파일 | 변경 이유 / Caller |
|---|---|
| `real2sim_builder/src/real2sim_builder/calibration/camera.py` | BUG-001: 기존 보호 Pose를 자동 fit에서 제외; 구형 `run` |
| `real2sim_builder/src/real2sim_builder/reconstruction.py` | BUG-001: trial 보호/검증과 합격 게시·실패 rollback; 구형 CLI |
| `real2sim_builder/src/real2sim_builder/capture.py` | BUG-002 공통 수동 상태 검증, BUG-003 source 관측 Adapter·Bound/Unbound 역할·Identity 전달 |
| `real2sim_builder/src/real2sim_builder/observations.py` | BUG-003 역할 공통 해석·Sensor model/mapping/order/units 검증 |
| `real2sim_builder/src/real2sim_builder/reconstruction_stages.py` | BUG-003 Stage10의 기존 역할 해석 함수 재사용 |
| `real2sim_builder/src/real2sim_builder/calibration/joint.py` | BUG-004 trial별 기존 관측 Camera/FK Adapter 사용 |
| `robot_learning_workbench/src/robot_learning_workbench/robot/capture.py` | BUG-003 Continuous Bound/Unbound Writer의 명시 역할 |
| `robot_learning_workbench/src/robot_learning_workbench/robot/snapshots.py` | BUG-003 Snapshot/Pair 공통 Writer의 명시 역할 |
| `real2sim_builder/tests/test_builder_calibration.py` | BUG-001 estimated 정상 fit·퇴화 거부 fixture와 정확한 보호 guard/나머지 원본 AST 검사 |
| `real2sim_builder/tests/test_current_calibration_protection.py` | 신규 12 case: 보호 Camera·Current·실패/중단/CLI/Export·lock |
| `robot_learning_workbench/tests/test_precision_capture_contract.py` | 신규 29 case: 실제 Precision 계산/저장→Writer→Reader, Legacy/부정 입력 |
| `real2sim_builder/tests/test_capture_sensor_contract.py` | 신규 17 case: 실제 Capture/Snapshot/Pair→Import→Sensor Registration→Stage10·FK |
| `real2sim_builder/tests/test_joint_camera_adaptation.py` | 신규 5 case: 실제 Photo 등록→Joint Solver·EXIF/Pixel·Holdout·Side/Wrist |
| `docs/reviews/phase1a-regression-fix.md` | 신규 보고서. 문서 자신의 최종 SHA는 자기 참조 대신 외부 최종 inventory에 기록 |

SHA256 전체값이다. 위 경로 표에 대응하도록 Builder/Workbench 접두사를 줄였다.

| 파일 | 수정 전 | 수정 후 |
|---|---|---|
| `Builder/calibration/camera.py` | `9feb074dc07f0b9d91b7b837c18bd2aa3a66d9b164ad092f04c35f11c2cb9e3c` | `8633076307fe857567be18d6b6dd757441b9e0074021808bc8f6c5059a6e1d2b` |
| `Builder/calibration/joint.py` | `e6e2f6ddd4ad278c37609833065cd9781effc137e6b8324d215c5176c91eca0b` | `07933e1c669d9e5db84c10b04a44f94021b4f87c2b711e885bea6b008651c1c1` |
| `Builder/capture.py` | `12e2ac78c5b0425fcbe59161b9830d27aac10840be4ca381dd96d1e7fc46ee7f` | `aa12d92f784767e01bff9ed501b2ec6446a1c8da0a84e256258ed799f066aea0` |
| `Builder/observations.py` | `2240494ba3cfe41eaa9226460f5143dd1394e71a886eb59af5bdedbfe7ed6294` | `e8e3059530a2d2363e0f4e94b10150060cf686b5881962cdecd4ff9dbe02290c` |
| `Builder/reconstruction.py` | `d1ca7a3c4796e13eb1a68271004fd41e1bc8978ee192c19ad87e13079ddc4b9d` | `371b18e683e68a6c6893c067dddde011f8db7a64ef0cf58fc9d7f2811f373ada` |
| `Builder/reconstruction_stages.py` | `3322f2e09ee6cc50dabb28dc1d419488a386af7678b19d74a57dd9532b4f017f` | `ecf3149d339fda79e33c7f89992398d2b131d14d718101a32f94b8348d048113` |
| `Builder/tests/test_builder_calibration.py` | `dde15fdb0733a5e2b4af157124db8c7550d187a6219382bdde5d6a13d5269821` | `17b92862a7232aeba89fd9f291791842080ecb0c970107e21d1ffe416662b8be` |
| `Workbench/robot/capture.py` | `b56e7df5063325a6a04ea371518155b253b8e66d874f4fee5b05842415b02a28` | `fc290f2d0527d5d606f3043878ac5038f827867b194412dc45b27f476d206ed5` |
| `Workbench/robot/snapshots.py` | `29726d7795676520cc07d90a3fd9a3b4f8338129ddca0ef21c047469179e7d7d` | `86e43879cda50d5fcf0c1409a1d35e253fd4643b03439ee39d1c1bee4a070082` |
| `Builder/tests/test_capture_sensor_contract.py` | `NEW` | `bfc9ecbeafb7cc3448263183b8cf4105395d51de3eec90fd1d57c9521b40e39a` |
| `Builder/tests/test_current_calibration_protection.py` | `NEW` | `1c029d29056457caffdbe146777a86fd133a80e04ed15d98fef4ee4736511bc9` |
| `Builder/tests/test_joint_camera_adaptation.py` | `NEW` | `4669728623eec9278395a656dfb966eb7c6d3d1a4042f3ebf0fadf301b74d5fc` |
| `Workbench/tests/test_precision_capture_contract.py` | `NEW` | `1376259bacbb1648e2500bdb157c39e85492816e5f82a28dec93f83a14e166aa` |

기존 감사 문서 SHA256은 `f511b9b1d794441cf81bf976e80f28404708a4783918d9cb361ea9489353b9af`로 시작과 동일하다. 추적 파일 499개를 시작 ledger와 대조했고 이번 변경은 **추적 수정9개 + 신규5개 = 14개**, 삭제0·범위 밖 수정0이다. 테스트한 Python 13개 SHA도 최종 상태와 동일하다. 기존 미추적 감사 문서는 이 14개에 포함하지 않는다.

보호 대조는 `workbench_runs/` 아래 `scenes`, `object_assets`, `capture`, `calibration`, `runtime`, `source`, `dataset`, `datagen`, `annotation`, `evaluation`, `curation`, `policy`, `scripts`의 시작 파일 **19,612개**를 대상으로 전체 SHA256/크기·경로 집합을 확인한 것이다. **변경0·누락0·신규0**이다. 이 범위의 Scene/Input/Calibration/Candidate/Cache/Asset/Export 및 Dataset은 보존했다. 홈 전체·SDK·모델 Cache 전체를 전수 SHA 대조한 것은 아니다.

HEAD/브랜치는 시작과 같고 staged diff SHA256도 변경이 없는 상태의 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`로 불변이다. reset/clean/checkout·Commit/Push/Merge는 수행하지 않았다.

원시 근거 파일: `baseline-code.json`, `baseline-protected.json`, `impact-analysis.md`, 결함별 `*-red*.xml/log`와 `current-final`, `precision-green`, `capture-green`, `joint-green`의 XML/log, `release-full.xml/log`, `regression-comparison.json`, `additional-analysis-final.xml/log`, `rank-acceptance-probe.json`, `refit-selection-probe.json`, `import-check.json`, `compile-interfaces-inventory.json`, `preservation-after.json`, `final-verification.json`, `verification-summary.json`. 이 보고서의 최종 SHA도 `final-verification.json`의 파일 행에 기록한다.

## 6. 최종 판정

**COMPLETED — 요청된 Phase 1A BUG-001–004 수정 및 회귀 안정성 검증 범위.** 네 결함의 RED/GREEN, 실제 Producer→Consumer 연결, 기존 정상 Workflow/API·CLI, 전체 회귀, 컴파일/import, 데이터/Index 보존 대조를 통과했다. 새로운 회귀는 이번 실행에서 관측되지 않았다. 테스트가 모든 실환경 조합이나 성능을 증명한다는 뜻은 아니다.

| 완료 조건 | 판정 / 근거 |
|---|---|
| BUG-001–004 원인 수정·재현 시험·생산자/소비자 연결 | 통과; 각 결함의 집중 GREEN과 전체 회귀 |
| 기존 Workflow·공개 API/CLI·이전 정상 archive | 통과; 기존 1,864개 누락0, 공개 Signature 불변, Legacy/직접 Writer round-trip |
| 원본 Scene/Calibration/Asset/Dataset/Index 보호 | 통과; 19,612개 파일 불변, 감사 문서/HEAD/Index 불변 |
| 불필요한 새 추상화/의존성·시험 삭제/skip/xfail·검증 완화 없음 | 확인; 변경 범위 14개, 좁은 기존 모듈 수정, 정확한 보호 guard/원본 solver AST 비교 유지 |
| 전체 회귀·정적 compile/import·diff 검사·변경 사유/전후 SHA 기록 | 통과; 위 실행 결과와 inventory |
| A/B 교차 검증 | 분석 완료, 결함/차단 근거와 최소 수정안만 기록; 이번 제품 수정에 혼합하지 않음 |

남은 실제 검증은 사용자 실사진 E2E, DA3/SAM/FLUX/PDA/Bria 등 재구성 모델 Forward, 실제 센서/측정 q의 정밀도와 Robot World 정합, Isaac/PhysX·실물 Task다. 이번 시험의 합성 subpixel residual이나 Fake 장치 연결을 그 성공으로 확대하지 않는다.

기존 감사의 BUG-005 이후와 A/B의 독립 결함은 이번에 고치지 않았다. 특히 BUG-012의 직접 Joint Fit 후 dependency signature 갱신 문제는 별도 Caller 문제로 남으며 이번 per-view residual 수정으로 해결됐다고 하지 않는다. 보호 Identity가 누락된 과거 Bound import의 자동 복구, 대규모 View 성능, 중단된 OS/전원에서의 전체 Export transaction 복구도 이번 검증 범위가 아니다.

패키지 설치/업그레이드·모델 다운로드·실제 로봇/모터/그리퍼 동작·고비용 AI/Isaac 장시간 실행·사용자 자료 변경·Commit/Push/Merge는 수행하지 않았다.
