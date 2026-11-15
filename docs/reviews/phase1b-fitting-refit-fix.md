# Phase 1B — 정합 결과 채택 및 Refit Layout 수정

2026-11-14. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `97c029e195ab8587603fb3f240f2c1a6c0f91f52`. [감사](full-codebase-audit.md)와 [Phase 1A](phase1a-regression-fix.md)의 실제 미커밋 코드에서 시작했다. 시작 HEAD의 파일만을 기준으로 이전 수정을 누락하지 않았다.

**COMPLETED — FIX-A/B 수정, 최종 전체 1,963 passed / 실패0·오류0·skip0, 실제 exit0.** 기존 1,927개 시험 누락0·신규36개이며 보호 파일19,612개 변경·누락·신규0을 확인했다. 이번 변경은 FIX-A/B에 한정한다. BUG-005–021/RISK-001–002는 수정하지 않았다.

실행 근거는 저장소 밖 `/tmp/real2sim-phase1b-20261114-or7ddub_/`에 있다. 임시 파일이 삭제되면 원시 로그를 열 수 없으며 제품이 이 경로에 의존하지 않는다. 사용자 Scene·Archive 대신 합성 Project/Camera/CAD/URDF/RGB·합성 Pair/Review Package를 사용했다. 설치·다운로드·실물 제어·온라인 AI·Isaac 실행·Commit/Push는 하지 않았다.

## 1. 수정 전 재현과 원인

| 범위 | 실제 재현 | 원인 |
|---|---|---|
| FIX-A | Solver가 RMSE를 줄이며 rank **2/6, IMPROVED**를 반환하고 Stage10이 그 Pose를 사용했다. prior0과0.2, Stop 후 재시작 모두 재현했다. | Stage10은 반환 Scene을 바로 사용했지만 Numeric에는 rank 부족을 거부하는 별도 채택 gate가 있었다. Solver의 진단용 `IMPROVED`와 자동 적용 가능 상태를 혼동했다. |
| FIX-B UI | 실제 Qt Table에서 A를 선택해도 Page가 A/B 전체 ID를 전달했고 Dialog는 마지막 Layout B를 골랐다. CLI→실제 Backend는 B를 Refit했다. | Page가 selection 대신 `self.rows` 전체를 전달하고 Dialog가 Candidate 재사용/config 두 곳에서 Project 마지막 Layout을 선택했다. |
| FIX-B Backend | 명시 A/B를 골라도 Layout 필터로 B가 빠지고 A만 실행됐다. A+없는 ID, 같은 Layout의 다른 Source Revision도 일부 선택을 버리고 실행할 수 있었다. | Layout → ID → Source의 순차 필터가 요청한 전체 집합의 완전성을 확인하지 않았다. |

FIX-A의 최초 RED는 **3 failed / 4 passed**, 3.29초·exit1이다. FIX-B 최종 수정 전 RED는 **11 failed / 9 passed**, 37.10초·exit1이다. 둘 다 실제 호출 경로를 검사했으며, 오류를 보기 위해 제품 소스를 임의 변조하지 않았다.

## 2. FIX-A — Solver와 Caller의 수용 의미

### Caller 조사와 변경 전후 정책

| Caller | Solver 결과/적용·저장·Best·Artifact | 이번 변경 |
|---|---|---|
| `calibration.joint.fit_joint_scene` | 보호/Scene·bounds·cheirality·각 group/holdout·aggregate RMSE 검사를 통과한 미검증 draft. Rank 부족은 needs 경고이며 `IMPROVED`일 수 있음. 자체 저장 없음 | **불변**. 전역 `IMPROVED` 금지·Residual 재정의 없음 |
| `reconstruction_stages.register_stage_sensors` → Stage10 `compile_scene` | 기존에는 반환 Scene을 재투영하고 Candidate/Stage Artifact에 사용할 수 있었음. Metric/World 등록 gate는 별도로 존재 | **Rank 부족 draft는 적용하지 않고 정합 직전 Scene 유지**. raw RMSE/Rank·needs를 보존하고 `UNRESOLVED`, `solver_status=IMPROVED`, `scene_adopted=false` 기록. 거부 Scene을 재투영·게시하지 않음 |
| `automation.refine_numeric_pairs` | 기존 rank 부족→`UNRESOLVED`, 원 Scene을 train 렌더로 평가하고 Best closure/restore. Holdout은 Best 선택에서 제외. Stop/failure도 Best 복원 | **불변**. Stage10의 새 predicate는 기존 Numeric과 같음 |
| `Candidate.fit('joint:scene')` → `calibration.geometry.fit` | 명시적 진단용 `IMPROVED` 초안을 Candidate에 저장하고 fit/joint-fit 보고. Current/승인 Revision 변경 없음 | **불변**. rank2/6 진단 초안을 계속 저장할 수 있음. 물리/보정 검증은 false |
| `calibration.hybrid.compare_backends` | landmark/hybrid에서 Joint 호출. 각 대안 Scene/metric·stage report 저장, 선택 대안 반환. 자동 정확도 winner/default는 None | **불변**. Rank 경고를 가진 초안도 비교 가능. 실제 검증 winner로 승격하지 않음 |

`pair_source`, `refine_numeric_pairs`, `fit_joint_scene`, `parameter_blocks`, `Candidate.fit`, `compare_backends`의 함수 AST가 Phase 1B 시작과 동일함을 별도 확인했다. Stage10만 자동 적용 경계에서 정책을 추가했다. Solver/직접/Hybrid의 용도를 바꾸는 공통 Manager나 전역 gate는 만들지 않았다.

### 잔차·관측 가능성·초안·검증의 구분

1. RMSE 감소는 관측한 픽셀과 더 잘 맞는다는 뜻이다.
2. 데이터 Jacobian의 Full Rank는 **현재 활성 변수와 수치 tolerance**에서 국소 Rank 부족이 관측되지 않았다는 뜻이다. 전역 유일해·실물 정확도를 증명하지 않는다.
3. 직접 Candidate/Hybrid는 경고를 포함한 미검증 draft를 저장·비교할 수 있다. Stage10/Numeric 자동 채택은 Full Rank가 필요하다.
4. Metric Anchor·Camera Calibration·물리·독립 실측 정확도는 별도 계약이다. Full Rank나 `IMPROVED`로 `calibrated`/`physical_verified=true`를 만들지 않는다.

Stage10의 센서 등록이 이미 완료되고 선택적 Joint refinement만 거부되면 센서 등록 결과 자체는 보존한다. `joint_refinement=UNRESOLVED`를 전체 정합 성공이나 독립 Calibration 완료로 해석하지 않는다. 전체 Stage Artifact의 완료는 해당 draft/입출력 계약이며 보정 인증이 아니다.

### Rank 수학 검토

기존 Solver는 `solution.jac[:3*len(train)] * radius[None,:]`로 Rank를 계산한다. 각 train CAD 관측의 x/y residual과 cheirality 항 뒤에 붙는 pose prior 행은 이 slice에서 제외된다. SciPy `soft_l1`의 가중치가 반영된 Jacobian이며, 활성 변수의 허용 translation/rotation 범위로 열을 스케일링한다. Holdout 행은 solve/Jacobian에 들어가지 않는다. 양의 depth에서 cheirality 항은 0이고, 뒤쪽 점이 남은 결과는 기존 검사로 거부된다.

설치 NumPy 1.26.0 소스에서 기본 tolerance가 `max(singular_value) * max(matrix_shape) * eps`임을 확인했다. 기존 `matrix_rank`의 SVD 수치 tolerance와 condition-number 보고를 유지했다. 새 임계값·가짜 Anchor·근거 없는 정밀도 기준은 추가하지 않았다. Camera/Object/Robot Base가 measured/calibrated면 `parameter_blocks`에서 제외되며, 고정 support yaw도 해당 활성 변수에서 제외하는 기존 코드를 유지했다. 실제 fixture에서 보호 Side/Table/Base까지 요청해도 변수는 estimated block의 6개뿐이다. prior0과0.2 모두 data Rank2/6으로 남고, 서로 다른 3D 모서리 관측은 Rank6/6으로 통과했다. Gauge/근접 퇴화의 완전한 판별이나 대규모 View 수치 안정성을 새로 증명한 것은 아니다.

## 3. FIX-B — 선택 ID·Source·Layout 연결

### 실제 식별자 계약

현재 `SnapshotStore.prepare(identifier)`의 pending ID, Manifest snapshot ID, `finish()['id']`, SnapshotTable row ID와 import 관측의 `snapshot_id`는 같다. **Archive dataset/session ID·폴더 이름·observation image ID와는 별개다.** 현재 Writer는 한 Capture Archive에 snapshot 하나를 저장하므로 일부 이름이 같아도 다른 필드를 임의 교환하지 않는다.

구형 정상 Archive도 Reader가 실제 snapshot ID를 `snapshot_id`로 보존한다. 임의로 파일명/접두사에서 Capture ID를 추정하는 Reader는 만들지 않았다. 같은 snapshot ID가 다른 Archive에 나타나 선택이 모호하면 거부한다.

### 수정한 경로

```text
SnapshotTable의 실제 선택 행
  → RealSimPage.open_refinement
  → automation.select_refit_pairs(전체 ID·Source·Layout 검증)
  → ReconstructionDialog(같은 선택으로 Candidate 재사용·config)
  → Qt Start Signal → 기존 launch/CLI refit-pairs
  → refit_pairs(같은 resolver 재검사)
  → 기존 input_images·pair_source의 SHA/Package/모델/Mapping 검증
  → 그 집합의 image_ids만 Candidate/수치 정합에 전달
```

- Real/Sim 페이지에서 행 선택과 다중 선택을 사용한다. 선택이 없으면 목록 전체로 대체하지 않고 안내한다. Source/Layout을 확인한 뒤에만 기존 Reconstruction Memo 저장·Dialog 열기를 수행한다.
- 기존 `automation.py`에 작은 함수 `select_refit_pairs`를 추가했다. 명시 ID **전부**가 존재하고 Pair·image ID·Layout 메타데이터가 있으며, 한 Source/한 Layout인지 검사한다. 빈 집합/부분 누락·잘못된 Source·혼합 Layout/Source를 조용히 걸러내지 않는다.
- Resolver는 읽기 전용 메타데이터/기존 Pair SHA·Identity 검사다. UI에서 모델/Simulator/native renderer를 초기화하지 않는다. 실제 Package/native closure·Robot/Mapping 검증은 기존 Backend의 `pair_source`가 계속 담당한다.
- Dialog의 초기 Candidate 재사용과 `configuration()`이 같은 resolver를 사용한다. Source Revision/Layout이 맞는 OPEN Candidate만 재사용한다. Launch 때도 재확인하여 열린 이후 바뀐 선택 메타데이터를 마지막 Layout으로 대체하지 않는다.
- Backend는 선택 집합을 먼저 결정한 뒤 `input_images`로 실제 RGB/q/단위를 검증하고 선택 image ID의 전부가 남았는지 확인한다. 기존 `pair_source`와 Candidate의 완전한 Source Revision record 대조를 그대로 사용한다.
- 선택 오류를 기존 Candidate의 `reconstruction.json`에 덮어쓰던 부수 효과를 제거했다. 오류 결과/Project 진행 상태는 반환하되 이전 Candidate/보고서/Best는 그대로다.

### 호환성

UI의 **빈 선택 거부**는 의도된 새 동작이다. 기존 공개 CLI `refit-pairs --scene-state ...`는 ID를 생략해 **명시한 Layout/Source 그룹**을 선택하는 경로를 유지한다. 명시 ID가 있으면 전체 집합을 검사하고, ID가 없는 CLI는 이전의 명시 Source 필터를 유지한다. 어느 경우에도 마지막 Project Layout을 추정하지 않는다. 기존 함수/CLI 인자·저장 schema는 바꾸지 않았다.

구형 관측에 `scene_identity`가 없더라도 **SHA가 맞는 기존 `pair.json`**에서 완전한 Identity를 읽는 경로를 유지했다. Pair 변조·Package Manifest 변조·모델 SHA/Joint Order/Mapping SHA 불일치를 실제 합성 Package/Robot fixture로 거부했다. 기존 `pair_source`의 baked binding·model/mapping 좌표 검사도 코드상 그대로다. 새로운 Alias/Identity 허용 규칙은 없다.

## 4. 검증 결과

### 순차 재현·수정

| 실행 | 결과 | 의미 |
|---|---:|---|
| Phase 1B 변경 전 집중 baseline | **113 passed**, 31.15s | Phase 1A 네 결함·기존 Stage/Numeric/UI/Pair 경로 |
| FIX-A 수정 전 | **3 failed / 4 passed**, 3.29s, exit1 | rank2/6의 Stage10 채택과 Stop 후 같은 오류 |
| FIX-A 수정 후 집중 | **88 passed**, 113.65s, exit0 | 신규 최종8개 + 기존 Native Numeric/Stage/Hybrid·per-view Camera |
| FIX-B 수정 전 최종 | **11 failed / 9 passed**, 37.10s, exit1 | 실제 Qt 선택 오류·Candidate 재사용·Backend 부분 선택 |
| FIX-B Backend 첫 검사 | **1 failed / 22 passed**, 15.32s | ID 없는 기존 CLI Source 필터의 정상 호환성 회귀 발견 |
| 위 호환성 수정 후 | **23 passed**, 14.52s, exit0 | 명시 전체 ID 검증과 기존 명시 Layout/Source CLI를 구분 |
| FIX-B UI 첫 검사 | **3 failed / 33 passed**, 35.51s | 구형 UI unit fixture가 Capture 없이 실행하거나 source_revision을 문자열로 축약함 |
| UI fixture 계약 갱신 후 | **36 passed**, 38.03s, exit0 | 신규 실제 Qt/CLI 경로와 기존 UI/계정·Page 시험 |
| 추가 Package/Robot·기존 Candidate 보호 | **8 passed**, 11.13s, exit0 | 실제 모델이 있는 Source Package 정상·SHA/순서/Mapping 변조 거부, 빈 선택/다른 Layout/Source에서 Candidate 전체 파일 불변 |

같은 시험이 여러 묶음에 들어가므로 통과 수를 합산하지 않는다. 최초 재현 Harness의 Export review report 누락·Bare Backend의 PyQt6 부재는 `refit-red.log`에 보존했다. 합성 fixture에 필요한 report를 쓰고 기존 Qt 패키지 경로만 Backend sitepackages 뒤에 추가했다. 패키지를 설치하거나 환경을 변경하지 않았다.

### 실제 실행 범위

FIX-A는 실제 PnP/등록·SciPy Joint Solver·Stage10 caller·Candidate save·Numeric Best checkpoint·Hybrid Artifact 저장을 사용했다. cloud 준비·이미 준비된 Sensor Registration·render metric은 명시 stub이다. 실제 Source/모델 Forward 또는 Stage10 전체 E2E는 아니다.

FIX-B는 실제 Review Package exporter/parser, SnapshotStore/Pair Writer→Reader→Import, Qt row 선택과 Refit/Start button signal, Dialog configuration, CLI `main` dispatch, `refit_pairs/pair_source`, Candidate 생성/저장을 실행했다. `start_cli`의 프로세스 transport만 같은 argv로 in-process CLI에 연결했고, 그 이후 비싼 Numeric render/fit만 stub으로 대체했다. 실제 Qt 설정 함수만 Mock하여 성공 처리한 것이 아니다. 실제 센서/실물·새 모델 생성은 없다.

### 기존 테스트 변경 이유

기존 시험은 삭제·이름 변경·skip/xfail하지 않았다. 수정한 기존 UI 시험 3개 파일의 top-level 시험명과 skip/xfail 호출을 시작 AST와 대조했고, 신규 파일에도 skip/xfail이 없다(`test-preservation-static.json`). `test_reconstruction_ui.py`의 두 fixture에 명시 Capture ID/완전한 Source Identity를 넣었으며, latest Layout은 **그 Capture를 실제로 선택한 경우**에 계속 사용한다. 이전 fake source_revision 문자열을 기존 실제 dict 계약으로 바꿨다. 기존 launch·Candidate 재사용 assertion은 유지하고 선택 ID 전달 assertion을 추가했다.

`test_geometry_ui_integration.py`의 Refit 진행 표시 fixture도 Capture 없이 생성하던 부분에 명시 선택만 추가했다. 진행 단계·Camera·렌더 문구/강조·단일 화면 검사는 그대로다. 이 계약 누락은 첫 전체 회귀에서 발견하고 단일 재현 RED **1 failed**, 0.25초 → 해당 파일 GREEN **7 passed**, 5.83초로 확인했다. 최종 전체 회귀는 이 수정 뒤 다시 실행했다.

`test_real_sim_page.py`의 Memo 버튼 smoke는 기존처럼 Memo/Dialog 경계만 Fake지만, 실제 선택 행과 ID·Source 메타데이터를 넣어 새 계약을 충족한다. 별도 신규 test는 실제 Package/Pair/Qt/Backend를 사용한다. 빈 선택을 정상으로 만들기 위해 제품에 시험용 bypass를 추가하지 않았다.

### 최종 전체 회귀 — 완료

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash /tmp/real2sim-phase1b-20261114-or7ddub_/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short \
  --basetemp=/tmp/real2sim-phase1b-20261114-or7ddub_/release-full-verified-temp \
  --junitxml=/tmp/real2sim-phase1b-20261114-or7ddub_/release-full-verified.xml
```

사용한 wrapper는 기존 `docs/evidence/builder/run_tests.sh`의 HF/XDG 출력 경로만 이번 `/tmp`로 바꾼 복사본이다. 기존 스크립트/환경은 수정하지 않았다. 첫 전체 실행(`release-full.xml/log`)은 **1,962 passed / 1 failed**, 오류/skip0, 627.44초·실제 exit1이었다. 실패는 위에서 재현·갱신한 진행 UI fixture 1건뿐이다.

수정 뒤 별도 최종 실행(`release-full-verified.xml/log`)은 **1,963 passed / 실패0·오류0·skipped0**, Console **634.20초**, JUnit **634.162초**, 실제 프로세스 **exit0**이다. JUnit testcase `(classname,name)` Counter를 Phase 1A 원시1,927개와 대조해 **누락0·추가36개**를 확인했다. 추가는 FIX-A8개 + FIX-B28개다. Phase 1A 신규63개도 전부 유지됐다. 이전 통과 수를 이번 결과로 대신 쓰거나 반복 실행 수를 합산하지 않았다.

경고5개는 기존 `record_property`/xunit2 경고1개와 torchvision 영상 API deprecation4개다. 실패/오류/skip으로 처리하지 않았다. 이 환경의 실제 Native parser·MuJoCo/EGL·Qt/OpenGL/Sandbox Blender·작은 CPU Policy Forward 회귀와 실제 센서·재구성 모델·Isaac 검증은 구분한다.

## 5. 아키텍처 영향과 보호 대조

새 외부 의존성/설치·전역 상태 Manager·DB·Renderer·Solver는 없다. 기존 `automation.py`의 읽기 전용 함수 하나와 기존 Dialog의 private Adapter만 추가했다. SnapshotTable 공통 구현·Writer·Capture schema는 그대로이며 RealSimPage만 행 선택을 설정한다.

Phase 1A 기준 파일을 `/tmp/before`에 보존했고, 네 제품 파일의 기존 공개 함수/메서드 인자 AST가 모두 같았다. 추가 공개 함수는 `select_refit_pairs` 하나다. 새로운 선택 오류는 반환/GUI 안내로 노출한다. 기존 API를 조용히 다른 Provider/마지막 Layout으로 넘기지 않는다.

Stage10 Cache는 기존 전체 Python 구현 SHA와 입력/설정/상위 Artifact identity를 사용한다. 완료 Artifact를 삭제하거나 기존 Rank 부족 결과를 새 성공으로 재해석하지 않는다. Numeric 함수와 Best/Resume·train/holdout 정책은 그대로다. 실제 Stop→재시작에서도 Stage10 Rank gate를 다시 적용했다.

초기 변경 Python 8개와 이후 보완한 UI fixture를 포함한 최종 **9개** 모두 bytecode 없는 compile을 통과했다. 기존 Qt 패키지/Backend 경계를 사용해 관련 모듈 **8개**와 기존 USD import를 실제로 확인했다. 모델/장치 생성자는 호출하지 않았고 GPU를 비활성화했다. NumPy Dispatcher의 source 위치를 읽는 임시 Harness의 introspection 오류는 unwrap으로 바로잡아 별도 로그에 보존했으며 제품 import 실패는 아니다. 실행 환경은 기존 `lerobot-arena` Python3.11.15/NumPy1.26.0/SciPy1.15.3과 설치된 Qt 경계다.

최종 대조에서 Phase 1A의 기존 수정과 시작 미추적6개(감사/Phase 1A 보고서2개·시험4개)를 보존했다. Phase 1B가 수정한 Stage10 함수 외에 Phase 1A의 제품 함수는 재작성하지 않았다. 시험한 Python8개는 최종 SHA가 같으며, 나머지 새 Capture 시험1개는 마지막 EOF 빈 줄만 제거했다. 해당 변경은 위치 포함 AST와 컴파일 코드가 완전히 같음을 확인했다(`post-test-formatting.json`). 실행 의미 변화가 없어 전체 시험을 반복하지 않았다. 또한 네 제품 파일의 기존 공개 인자 AST도 유지됐다. 추적 파일499개와 시작 미추적6개를 기준으로 범위 밖 수정·삭제0이다.

보호 root는 `workbench_runs/`의 `scenes`, `object_assets`, `capture`, `calibration`, `runtime`, `source`, `dataset`, `datagen`, `annotation`, `evaluation`, `curation`, `policy`, `scripts`다. 이 안의 **19,612개 파일 SHA256/크기와 전체 경로 집합**을 전후 대조해 **변경0·누락0·신규0**을 확인했다. Scene/Input/Capture/Calibration/Candidate/Cache/Asset/Export/Dataset을 보존했다. 홈 전체·Conda/SDK·모델 Cache 전체의 전수 SHA 검사라는 뜻은 아니다.

HEAD/브랜치와 staged diff는 불변이다. Index diff SHA256은 시작과 같은 빈 diff의 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`다. 최종 변경은 **기존7개 수정 + 신규3개 = 10개**, 삭제0이다. 기존 Phase 1A의 미커밋 변경과 이 수치를 구분한다. `git diff --check`와 신규 파일의 whitespace 검사도 통과했다. Commit/Push/Merge·reset/clean/checkout/stash는 하지 않았다.

## 6. 변경 파일

Phase 1A 시작 HEAD 대비 전체 diff가 아닌 **Phase 1B 시작 Working Tree 대비** 범위다.

| 파일 | 변경 이유 / 호출 경계 |
|---|---|
| `real2sim_builder/src/real2sim_builder/reconstruction_stages.py` | FIX-A: Stage10 자동 채택 Rank gate·거부 진단/Scene 유지. Phase 1A Capture 역할 수정 보존 |
| `real2sim_builder/src/real2sim_builder/automation.py` | FIX-B: 전체 선택 resolver·Backend 완전성 검사·실패 시 기존 Candidate report 보존 |
| `real2sim_builder/src/real2sim_builder/ui_reconstruction.py` | FIX-B: 같은 Source/Layout 선택으로 Candidate 재사용·config/launch 검증 |
| `robot_learning_workbench/src/robot_learning_workbench/ui/real_sim_page.py` | FIX-B: 실제 선택 행만 전달·빈/혼합 선택 안내, 검증 후 Memo 저장 |
| `real2sim_builder/tests/test_joint_acceptance_policy.py` | 신규8개: Rank/Prior/Full Rank/보호/Stop/Holdout·Numeric/Direct/Hybrid |
| `real2sim_builder/tests/test_refit_capture_selection.py` | 신규28개: 실제 Writer/Package/Qt→CLI/Backend, ID/Source/Layout·Identity와 기존 Candidate 보호 |
| `real2sim_builder/tests/test_reconstruction_ui.py` | 기존 시험명/검사 유지, 축약 fixture를 명시 선택·typed Source 계약에 맞춤 |
| `robot_learning_workbench/tests/test_real_sim_page.py` | 기존 Memo smoke에 실제 선택 행·Source fixture와 ID 전달 검사 |
| `real2sim_builder/tests/test_geometry_ui_integration.py` | 기존 Refit 진행/인증 컨트롤 시험에 명시 Capture 선택 fixture 추가 |
| `docs/reviews/phase1b-fitting-refit-fix.md` | 신규 보고서. 문서 자신 SHA는 외부 최종 inventory에 기록 |

시작 감사/Phase 1A 문서·기존 신규63개 테스트를 보존했다. 보호 자료 대조와 전체 회귀 근거는 위 절을 따른다.

SHA256 전후 전체값이다. `Builder/`는 `real2sim_builder/src/real2sim_builder/`, `Workbench/`는 `robot_learning_workbench/src/robot_learning_workbench/`를 줄인 것이다. 새 테스트는 패키지별 tests 경로다. 문서 자신 SHA는 외부 inventory에만 기록한다.

| 파일 | Phase 1B 시작 | 수정 후 |
|---|---|---|
| `Builder/automation.py` | `e052cfddbd075d198f87da766dabe55950b030be9f03abc9d10079bb2295d39a` | `40a696003aaeaf98a31fc6024ea57e4c9c0ae574fefd10dc2c51c55abc36af12` |
| `Builder/reconstruction_stages.py` | `ecf3149d339fda79e33c7f89992398d2b131d14d718101a32f94b8348d048113` | `7793672c3ec3cc266ebef7962c3347c2dc5bebbb6aedbec25f1340544765b262` |
| `Builder/ui_reconstruction.py` | `280e7e6d1daa618779508844a15db4a564e7c8a59144df55c4cf1fbfbbe5ed0a` | `00abc12d6aad7db1664b68d5e082d02976127e72a4338a17c9a5a616e1723eec` |
| `Builder/tests/test_geometry_ui_integration.py` | `ddfb0ad3316eb6d91480e3a520fc2bb93bfdf66cb8f1250bee6dfd6a7c77def5` | `e3bc00398607ee5daaf225c543950b339f422e1cdc9f9d3670032b84bab01f57` |
| `Builder/tests/test_joint_acceptance_policy.py` | `NEW` | `de2ad81aca63e0e7108f6da1c71c42883fe13f17329b091ba978b131afc8f579` |
| `Builder/tests/test_reconstruction_ui.py` | `bffe651d44889b3a5d088f2ee0969af00d0d38bd1abe68162f77dace1dc8ffe4` | `850fded9781482f6f196fa82e1677c20b6f82383f1cef6c4338266030d1b1550` |
| `Builder/tests/test_refit_capture_selection.py` | `NEW` | `b044c7979495e68ce6d0844e781c8ec52a6a87f0a321b0fc33216b31faba8728` |
| `Workbench/ui/real_sim_page.py` | `983c23fcaacb07423de7940e5e1d343763517bfe302e8e84184101ac5374ef8d` | `a32fcca74428766e0cd3ee7499dd60f5201fd626e4eb4c25d908f8a208b806f5` |
| `Workbench/tests/test_real_sim_page.py` | `6acbe6cc9cd1283d3db169f2a3bdfd85334724e3ef182d9c40ee872f60b78713` | `4fa1063a7053b45907ab9890f632537448e8e1d0517af9d929dbec1babbd53e1` |

## 7. 최종 판정과 검증 공백

**COMPLETED — 요청된 FIX-A/FIX-B 수정과 회귀 안정성 검증 범위.** 두 결함의 수정 전 실패, 수정 후 정상/거부 경로, 실제 Producer/Consumer 및 Qt/CLI/Backend 연결, 전체 회귀와 원본 보존 대조를 통과했다. 이번 시험에서 신규 회귀는 관측되지 않았다.

| 완료 조건 | 최종 판정 |
|---|---|
| FIX-A 부족 Rank 거부·Full Rank 채택·보호 Scene/Best | 통과; 실제 Solver/Stage10/Numeric·Stop 재시작·Holdout 검사 |
| Direct/Hybrid 진단 초안과 자동 채택 의미 구분 | 보존; 실제 Caller/Artifact 검사·기존 함수 AST 불변 |
| FIX-B 실제 선택 Capture/Layout/Source 사용 | 통과; 실제 Qt signal→CLI→Backend 및 A/B·혼합/누락 거부 |
| Backend Package/Pair/model/mapping SHA·순서 검증 | 보존; 실제 합성 Package/Robot 정상 및 변조 거부·`pair_source` AST 불변 |
| 기존1,927개/Phase1A와 사용자 자료 보존 | 통과; 기존 시험 누락0, 원본19,612개 불변, 시작 미커밋 내용 보존 |
| 전체 회귀·Compile/Import·공개 인자·diff 검사 | 통과; 위 실제 결과·최종 inventory 참조 |
| 새 의존성/전역 구조·무관한 결함 수정 | 없음; 기존 모듈의 작은 resolver와 Caller gate에 한정 |

남은 검증/위험:

- Full Rank는 scaled numerical Jacobian의 국소 조건이며 전역 유일해·Metric/실물 정확도 증명이 아니다. condition-number 추가 안전 기준이나 수치 tolerance 변경은 근거 없이 도입하지 않았다.
- 직접 Candidate/Hybrid는 기존처럼 Rank 부족 미검증 초안을 사용할 수 있다. 그 Artifact를 Calibration 승인으로 취급하면 안 된다. BUG-012 등 이번 범위 밖의 독립 Caller 문제는 그대로다.
- 실제 사용자 센서·로봇·실사진 E2E, DA3/SAM/FLUX/PDA/Bria 추론, Isaac/PhysX·실물 Task는 **NOT_TESTED**다. 기존 전체 회귀의 작은 CPU Policy Forward/Native parser·MuJoCo/EGL·Qt/Blender 검증과 구분한다.
- 정상 Writer의 현재 UI row ID와 archive snapshot ID 일치는 확인했다. Identity/역할 자체가 누락된 과거 불완전 자료를 자동 복구하거나 파일명으로 해석하는 기능은 추가하지 않았다.
- 선택 resolver는 원본 Pair를 매번 확인한다. 다량 Capture에서 Dialog opening/refresh의 읽기 비용은 별도 성능 benchmark를 하지 않았다. Backend는 실행 시 다시 검사하므로 UI 결과만으로 원본 무결성을 믿지 않는다.
- 기존 `refit_pairs(dataset=...)`의 명시 Archive import 계약은 유지했다. 이번 UI 검증은 이미 정상 import된 Capture 선택 경로이며, 새 Archive import와 이후 오류 전체를 하나의 rollback transaction으로 재설계하지 않았다.

자동 Commit/Push/Merge 없이 변경 내역과 검증 결과만 보고한다.

원시 근거 목록: `baseline-code.json`, `before/`, `baseline-protected.json`, `impact-analysis.md`, `baseline-focused.xml/log`, `rank-red.xml/log`, `rank-green.xml/log`, `refit-red-final.xml/log`, `refit-backend*.xml/log`, `refit-ui*.xml/log`, `refit-guards.xml/log`, `refit-progress-*.xml/log`, `release-full.xml/log`, `release-full-verified.xml/log`, `exit-codes.json`, `verification-summary.json`, `regression-comparison.json`, `test-preservation-static.json`, `contract-preservation.json`, `caller-change-scope.json`, `import-check.json`, `tested-files-final.json`, `post-test-formatting.json`, `preservation-after.json`, `final-verification.json`. 보고서 자신의 최종 SHA는 `final-verification.json`에 기록한다.
