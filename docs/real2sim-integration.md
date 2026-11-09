# Real2Sim 입력·독립 자산·정합·Task 통합

## 2026-11-09 현재 실행 계약 — Codex-First

제품 Auto Reconstruction은 Scene/Model 사진과 Memo를 Codex가 직접 분석하고, 기존 Sandbox Blender로 자산을 제작한 뒤 실제 Simulator 렌더를 보며 typed Scene plan을 반복 수정한다. SAM/DA3/MASt3R/COLMAP·Depth·Metric 등록은 초기 Scene 생성의 필수 단계가 아니다. 최초 Scene/각 Iteration/최종 결과의 실제 Visual Evidence를 Candidate에 보존하고 단일 UI에서 연다.

현재 소유권·전환 이유·실제 실행/검증 범위는 [Codex-First 제작 기록](codex-first-scene-builder.md)을 따른다. 아래의 과거 날짜별 Backend/수치·검증 기록은 당시 범위이며 현재 기본 실행 순서가 아니다. 기존 Calibration/FK/Renderer/Asset/Export 계약과 사용자 원본은 유지한다.


2026-11-06. 사용자 「Real2Sim 전체 구현 보완 및 통합 지시서」를 기준으로 진행한다.
시작 HEAD `6c90f776b7e2bd3a0aca19dcad41c016fda76015`, 브랜치 `fix/baseline-tests-20261106`.
직전 테스트 정리 미커밋 28개를 유지한다. 해당 소스 상태에서 전체 1,441 passed, 실패/오류/skip 0을 확인했으며 이번 변경 전 기준으로 사용한다.
Commit/Push·설치 변경·하드웨어 구동은 범위 밖이다.

## 실행 계획과 소유권

1. Phase 1: 기존 `scene_preparation.save_inputs` → `observations.register_image/input_images`; Codex 대표 시점·개별 Instance → 기존 `associate_instances/cross_view_associations`; 기본 독립 자산, 명시 Manifest 재사용.
2. Phase 2: 기존 `predict_views`/Camera 변환 → `fit_scene` 공동 수치 정합; 전체 실행 예산·최선 결과; 구조적 잔차 → 기존 Codex/Blender 새 자산 버전 handoff.
3. Phase 3: 기존 Pair source identity·물리 probe·실제 엔진 검증 재사용. 정합용 관측과 독립 평가를 분리한다.
4. Phase 4: Codex의 구조화 Task 계획을 기존 Workbench Registry/Recipe로 검증·연결한다. 지원 안 되는 동작/관측을 성공으로 발명하지 않는다.
5. Phase 5: 관련 회귀·전체 통합·원본 보존·문서 정리. 합성 경계 시험과 실제 사용자 자료 E2E를 구별한다.

Scene Memo는 자연어 원문이며 Codex만 의미를 해석한다. Python은 수치·ID·참조·단위·Provenance를 검사한다. 기존 Project/Candidate/Asset Version/Export 구조를 사용한다.

## 진행 기록

- Scene Prepare RGB 누락 재현: 저장한 사진 2장이 `input_images`에서 0장. 수정 후 등록된 external/train RGB 2장, 미지 Camera와 q는 미지로 유지. 같은 파일 재저장은 원 기록을 보존한다. 한 업로드는 한 정적 배치이고 별도 업로드는 새 배치다. API의 명시 `scene_state`로 같은 배치를 선택할 수 있다. 기존 Capture를 자동 재분류하지 않는다.
- 전체 Solver 예산 재현: `max_iterations=5,max_evaluations=3`에서 기존 실제 MuJoCo objective가 9번 평가됨. 전체 fit 호출의 objective 평가 예산으로 수정하고 회귀를 추가했다. baseline/final 평가와 시간 제한은 별도로 명시하며, View 단위 시간 제한 보완은 남아 있다.

실행 근거는 Git 제외 `workbench_runs/integration_20261106/`에 저장한다. 아직 Phase 전체 완료 보고가 아니다.

### 통합 진행 — 관측, Task 연결, 미지 치수

- Codex 구조화 계획에 대표 이미지와 이미지별 Box/Point, Task 의도를 받는다. 새 자산은 기본적으로 Object별 독립 제작하며 기존 공유 자산은 보존한다. 비슷한 Mask와 대표 시점/3D 대응의 충돌은 모호함으로 남긴다.
- 알려진 렌즈 왜곡과 EXIF/crop 좌표 변환을 Camera projection, depth 역투영, MuJoCo/Isaac 렌더 비교에 연결했다. 렌즈 왜곡 계수의 자동 추정 완료를 뜻하지 않는다.
- Export Manifest가 소유하는 구조화 Task만 Workbench가 읽는다. 지원하는 pick-place는 기존 Registry의 Annotation/DataGen/Sim Evaluation 함수와 매개변수로 연결한다. 사용자 YAML의 명시 함수는 덮어쓰지 않으며 지원되지 않는 Task/관측은 `NEEDS_IMPLEMENTATION`이다. Registry 검증을 실제 Task 성공으로 표시하지 않는다.
- 여러 시점의 유효 depth 근거가 있는 단순 Box/Sphere/Cylinder는 미지 치수 축을 공동 정합할 수 있다. 실측/보정 치수와 부분 실측 constraint, Robot 및 Library 자산은 고정한다. MuJoCo는 변경된 형상을 재compile해 mesh/inertia까지 갱신한다. 복잡한 USDA 형상 변경은 이 기능의 대상이 아니다.
- 실제 합성 MuJoCo 시험에서 잘못된 폭을 줄이고 실측 축을 유지하는 것을 확인했다. 별도 Isaac 렌더에서 폭 변경으로 Mask 46 pixel 변화, 왜곡 Mask/depth 변환, 원래 크기 복원을 확인했다. 해당 Isaac 시험의 physics step은 0이며 충돌/Task 검증이 아니다.
- Pair 재정합은 기존 Revision의 형상/재질 계약을 유지한다. 새 `optimize_dimensions`가 명시돼도 이 경로에서는 끈다. 요청값이 그대로 통과하던 회귀를 먼저 재현했다.

관련 회귀 `progress-suite-fixed.xml`: **324 passed**, 추가 집중 검사 `latest-focused.log`: **31 passed**. 이는 당시 변경까지의 관련 범위이며 전체 Workbench 회귀와 같지 않다. 실제 Isaac 결과는 `isaac-dimensions/result.json`에 보존했다. 중간 테스트의 변수 위치 오류와 과거 함수 소스 동일성 기대는 수정했고, Camera projection은 실제 OpenCV 계산과 대조한다.

남은 작업은 구조적 잔차에 따른 제한된 새 자산 모델링/재정합 반복, 실제 사진의 충분한 metric/독립 평가 자료를 이용한 전체 E2E, Task의 실제 엔진 실행 통합과 최종 전체 회귀다. 자동 시간 예산의 View 단위 중단과 정합 후 검사 비용도 추가 점검이 필요하다. 현재 구현을 전체 완료 또는 새 실제 Scene 승인으로 보고하지 않는다.

### 재개 후 실제 실행 확인

- `test_automation.py`와 치수 정합 회귀: **13 passed**. Pair의 `optimize_dimensions=true` 요청이 원 모델 치수를 바꿀 수 있는 경로를 차단했다.
- 설치된 SAM 3.1 모델로 기존 실제 Side RGB에 Positive Point를 전달했다. **실제 forward에서 Mask 1개, 640×480, 지정 점 포함**을 확인했다. 점은 과거 파생 SAM Mask 내부에서 골랐으므로 독립 사람 정답/물체 식별 정확도 시험은 아니다. `sam-point/summary.json` 및 원 Worker 결과를 보존한다.
- 기존 `preservation-before.json`의 **2,389개 SHA 변경0·누락0**을 재확인했다. 전체 설치 환경/모델 corpus 전수 hash는 아니다.

### 새 자산 버전의 추정 치수 교체

`editing.apply(use_object_asset)`가 모든 기존 치수를 실측처럼 잠그던 오류를 재현·수정했다. 보호된 전체/부분 치수만 기존 허용오차로 검사하고, 나머지 추정 축은 새 검증 Asset Version의 치수로 바꾼다. 부분 실측의 원 record는 `preserve`로 유지하며 이를 누락한 교체는 거부한다. 두 Instance 중 하나만 새 버전을 붙여 다른 Instance와 구 Manifest SHA가 그대로임을 확인했다. 신규 재현과 기존 Object Asset 회귀 **14 passed**. 이는 새 버전 교체 경로의 수정이며 Codex 자동 재모델링 반복 전체가 완성됐다는 뜻은 아니다.

## 현재 완료 기준 대조

| 기준 | 현재 상태 |
|---|---|
| AC01 기본 입력 | Scene Prepare RGB 자동 등록 구현·회귀. 서로 다른 업로드의 정적 배치를 자동 합치지 않음 |
| AC02 동일 물체 | 대표 시점/3D 대응·순서 반전/가림/의미 충돌 합성 회귀. 실제 동일 컵 다중 시점 정확도는 미검증 |
| AC03 독립 USDA | 독립 제작/명시 재사용/한 Instance 새 버전 교체 회귀. 구 자산 보존 |
| AC04 Memo 실측 | 기존 Codex typed 계획과 부분 실측 보호 재사용. Python 자연어 파서 없음 |
| AC05 복원 | 렌즈/EXIF/다중 시점 수치 경로와 SAM Point 실제 실행 확인. 실제 전체 Scene 복원 미완료 |
| AC06 재모델링 | 새 Asset 교체 시 추정 축 갱신 수정. 구조적 잔차 진단→제한된 Codex 재제작 반복은 미완료 |
| AC07 공동 정합 | 실제 native 정합과 미지 primitive 치수 추가. 전체 시간 예산/중단 경계 추가 점검 필요 |
| AC08 Pair | Source Revision 형상·재질 유지 회귀. 신규 실제 Pair 전체 재정합은 미실행 |
| AC09 물리 | 이번 Isaac 치수 시험은 렌더만 수행. 기존 물리 시험과 별도로 신규 Asset/Robot Task 통합 시험 필요 |
| AC10 Task | Export의 typed intent→기존 Registry→UI 설정 연결. 실제 엔진 Task Preparation/Evaluation 전체는 미완료 |
| AC11 보존 | 기존 2,389개 SHA 변경·누락0 |
| AC12 실제 E2E | NOT_VERIFIED. 개별 실제 모델/렌더와 합성 회귀를 전체 성공으로 합산하지 않음 |

### 전체 회귀와 후속 Identity 수정

전체 세 패키지 회귀 `full-suite.xml`은 **1,484 passed / 실패·오류·skip 0**, 기존 torchvision 경고4회로 완료됐다. 이 실행 이후 추가한 Asset 교체 수정은 별도 Builder 전체 `builder-after-remodel.xml` **295 passed**로 검사했다. 따라서 1,484 수치가 마지막 후속 수정까지 모두 포함한다고 해석하지 않는다.

대표 시점 대응 후 동일 Mask를 두 Object에 명시 지정한 충돌이 geometry 단계에서 재확정되는 오류를 추가 재현했다. 명시 Box/Point/선택 충돌은 모호함으로 남긴다. 반면 가림 때문에 후보가 하나뿐인 자동 매칭은 기존 3D 대응으로 해결할 수 있어야 하므로 이 경우와 구별한다. 첫 수정의 과도한 차단은 기존 occlusion 회귀가 잡았고, 두 경우를 구분하도록 수정했다.

## 사용자 검증 범위 변경: 단계 연결 우선

사용자의 후속 지시에 따라 정합 오차 목표/시각 품질 개선을 이번 완료 기준으로 삼지 않는다. Memo·RGB·q 전달, Codex 실행, 결과 수용, 제작·정합·Export·Pair 재정합으로의 연결, 실패 진단과 재개를 검증한다. 유효하지 않은 산출물을 성공으로 넘기지 않는 검사는 유지한다.

기존 `reconstruct`에 `run_modeling=True`를 추가했다. WAITING_FOR_CODEX_ANALYSIS/WAITING_FOR_CODEX에서 기존 `run_codex_modeling`을 호출하고, 분석이 저장한 typed configuration을 다시 읽어 같은 Candidate에서 재개한다. 기본 호출은 기존 수동 handoff를 유지한다. CLI는 다음과 같다.

```bash
python -m real2sim_builder.cli reconstruct PROJECT --candidate NAME --run-modeling --max-modeling-calls 2
```

이 옵션은 실제 기존 Codex child를 호출하므로 명시적으로 선택한다. 분석/모델 제작 호출을 합산하며 기본 최대2회다. 모델 실행 실패는 CODEX_MODELING 단계와 원인을 reconstruction.json/Project에 기록하고 Candidate를 유지한다. 재실행은 기존 cache/명시 자산 재사용 계약을 따른다. 실제 원격 Codex를 호출한 검증은 아직 없으며, orchestration 시험은 그 경계만 대체해 상태 전환·설정 재로드·호출 상한·오류 보존을 확인한다. 이는 구조적 잔차에 따른 자동 재모델링 계획 생성까지 구현했다는 의미가 아니다.

기존 Reconstruction UI의 Codex 버튼을 `Codex 분석·제작·정합 이어서 실행`으로 연결했다. 별도 앱/실행 관리자를 만들지 않고 현재 설정을 기존 CLI에 전달한다. 당시 Pair 재정합은 수치 정합만 수행했다. 아래 후속 연결에서 명시 연속 실행을 Pair에도 연결했다. 단계 전환/실패와 UI 관련 집중 검사 **8 passed**이며, 원격 Codex 호출 자체는 대체한 검사임을 유지한다.

`connected-flow.xml`: Codex handoff·실제 Blender 제작/등록·자동 단계 연결·Qt·Pair 회귀 **53 passed**. Codex 응답은 테스트 실행 파일로 대체하고 Blender와 USDA 검증은 실제 구현을 사용한다. 이후 Stop 반환/기본 수동 모드의 무호출 회귀를 추가했다. 이 결과는 실제 Codex 서비스의 언어 해석이나 실제 자료 전체 Scene 제작을 검증한 것이 아니다.

## Wrist 우선 정합과 Codex 비교 자료

사용자 후속 지시: 휴대폰 다중 시점은 3D 형상·가림 복원 근거이고, Scene 정합/완료 판단은 Wrist 최우선·Side 보조다. 실제 q는 변경하지 않으며 한 시점만 맞추기 위한 기하 왜곡을 허용하지 않는다.

`fit_scene`는 사진 전체의 단순 평균 대신 Camera 역할별 평균을 가중 합산한다. 기본 가중치는 Wrist4 / Side2 / external0.5이며 `fitting.view_weights`로 명시 조정할 수 있다. 이는 운영 우선순위이지 실측 정확도로 보정된 상수가 아니다. 휴대폰 사진 개수가 늘어도 Wrist의 비중이 줄어들지 않는다. 기존 각 View 악화 제한은 유지한다. Wrist 자료가 없는 복원도 실행할 수 있지만 `wrist_observed=false`를 남긴다.

Codex 분석·모델링 payload에 같은 view_policy를 전달한다. 정합 후 `fitting/codex-review.json`에는 Memo 원문, 현재 Object, 입력 signature, Wrist→Side→external 순서의 Real/Sim/overlay/difference 이미지 경로·SHA와 잔차를 담는다. 파일 누락/Scene 변경 시 오래된 결과로 검토하지 않는다. 상태는 `WAITING_FOR_CODEX_REVIEW`이며 검토 자료 생성 자체를 완료 판단이나 물리 검증으로 승격하지 않는다.

이 단계 당시 연결은 비교 자료 생성까지였다. 이 자료에 대한 Codex의 구조화 판단 수용→선택 Object 새 버전 제작→재정합 반복 및 최선 결과 선택은 여전히 후속 구현 대상이다. 품질 수치 목표를 맞추는 실험보다 이 호출/자료 전달 계약 검증을 우선한다.

## 카메라 역할 변경 지시서 반영 (2026-11-06)

첨부 `a58db5e3-1b48-4cdd-bd77-9fab47099a1b`의 지시는 기존 작업에 통합한다. 휴대폰은 3D 복원 근거, Side는 전역 구조, Wrist는 정책 관측이다. 기존 역할별 가중치는 탐색 우선순위일 뿐 완료 기준이 아니다.

`alignment_metrics`가 원 관측의 camera_type과 q_measured를 그대로 기록하고 `validation.camera_quality`에서 카메라별 수치·위반·자료 부족을 분리한다. `fitting.camera_quality`에 역할별 `metrics`의 min/max와 `evidence`를 명시한 경우 각 View를 검사한다. 임의 허용 기준을 기본값으로 넣지 않는다. 근거가 없거나 지표가 없거나 Side/Wrist 관측이 부족하면 NOT_VERIFIED, 어느 한 카메라라도 기준을 넘으면 NOT_MET이다. 서로 다른 Wrist q가 두 개 이상인 것은 최소 자료 확인일 뿐 Hand-Eye 관측 가능성 증명이 아니다.

모든 명시 이미지 기준을 만족해도 CRITERIA_MET_UNVERIFIED로 기록하며 물리/Calibration 인증으로 승격하지 않는다. 이 판정을 Codex 비교 자료와 reconstruction 단계 보고서에 연결했다. 수치 Solver가 초안을 준비해도 카메라 기준 미확인 상태는 최상위 NOT_VERIFIED로 표시한다. 입력 부족 때문에 휴대폰 복원을 금지하거나 기존 Candidate/산출물을 삭제하지 않는다.

이 시점에는 Codex의 구조화 원인 판단과 새 Asset 제작·재정합 반복이 남아 있었으며, 아래 후속 연결에서 구현했다. Python 자연어 진단 규칙이나 임의 실측값은 추가하지 않았다.


## Codex 비교 판단 → 수정 → 재정합 연결

기존 `run_codex_modeling`에 비교 검토 모드를 통합했다. 같은 child 실행·timeout·중단·SHA 검사를 사용하며 별도 Agent/Manager를 추가하지 않았다. Codex에는 Wrist/Side의 원본·렌더·overlay·difference를 실제 파일로 전달한다. 응답의 action/Object ID/image evidence/reason만 구조 검사하며 Python은 원인 문장을 재해석하지 않는다.

- `numeric`: 같은 Candidate와 기존 공유 Camera/Object solver로 다시 정합한다. 지정 Object만 scope에 반영하고 q·실측 보호는 유지한다.
- `remodel`: 진단과 당시 비교 이미지의 고정 사본을 기존 모델링 handoff에 전달한다. 선택 Object의 새 request/version을 제작·등록한 뒤 정합한다. 기존 Asset/Export는 덮어쓰지 않는다.
- `complete`: `VISUAL_DRAFT_REVIEWED`로 종료한다. Side/Wrist 및 복수 measured Wrist q가 없거나 명시 수치 기준이 실패하면 자료 부족으로 남긴다. 사용자 수치 허용값이 없어도 Codex의 시각 판단을 기록할 수 있지만 수치 검증·물리 인증은 별개다.
- `needs_data`: 이유와 Candidate를 보존하고 종료한다.

`reconstruct --run-modeling`과 `refit-pairs --run-modeling`에서 실행한다. 기본 분석/모델링 child 최대6회, 비교 child 최대3회이며 CLI의 `--max-modeling-calls`, `--max-review-calls`로 조정한다. 각 child timeout은 기존900초다. 일반 Pair 실행은 기존 형상 보존 수치 정합이고, 명시 연속 실행 중 구조 수정 판단이 나온 경우에만 새 Candidate 자산 버전을 사용한다. Source Revision과 원 Capture/q는 유지한다.

각 비교 전 Scene/metrics와 판단을 `fitting/reviews/<id>/`에 보존한다. 수치 solver 내부 최선 checkpoint는 기존 구현을 사용한다. 이 단계의 단순 Scene 사본은 독립 Export나 완전한 closure가 아니었다. 아래 후속 checkpoint 구현에서 반복 간 보존·복원을 추가했다. 마지막 시각 판단과 물리 준비/Task 성공을 동일시하지 않는다.

검증은 단계 연결 중심이다. 가짜 Codex CLI 경계에서 실제 child 실행·4종 비교 이미지 전달·응답 검사를 확인했고, 분기 시험에서 numeric→remodel→모델 등록→재정합→complete 및 호출 상한/Stop/원 구성 보존을 확인했다. 기존 실제 Blender/USDA 검사도 회귀에 포함한다. 원격 Codex 서비스와 실사진의 무인 제작 성공을 실행한 결과는 아니다. Commit/Push·설치·하드웨어 연결은 하지 않았다.

후속 검증: Builder 전체 **313 passed** (`review-connected-final.xml`). 이후 held-out 비교 자료 제외 수정은 관련 **33 passed** (`review-final-focused.xml`)로 확인했다. 두 실행 모두 실패/skip0이며 `git diff --check` 통과다. 전체313 결과가 마지막 held-out 추가 시험까지 포함한다는 의미는 아니다. 처음 발견한 UI 기대값 실패는 Pair 연속 실행을 금지하던 이전 시험을 새 공개 동작으로 갱신해 해결했다. 로그/JUnit은 Git 제외 `workbench_runs/integration_20261106/`에 보관한다.

## 반복 간 최선 Scene 보존·복원

연속 실행의 각 비교 결과에서 동일 train image ID·camera 역할·measured q·Object ID 집합과 같은 원 Evidence/Memo를 확인한다. MAE/RMSE/edge IoU 및 Object mask IoU·중심 오차·표면 잔차가 유한해야 한다. 모든 비교 항목이 이전 이하이고 적어도 하나가 개선된 경우 새 checkpoint를 채택한다. 평균값으로 Wrist/Side 악화를 숨기지 않는다. 트레이드오프나 동률·비교 불가능한 결과에서는 이전 checkpoint를 유지하는 보수적 선택이며, 절대 정확도 인증이나 시각적 전역 최적해 주장이 아니다. validation View는 선택 점수에 사용하지 않는다.

`automation.retain_fitting/restore_fitting`은 기존 Candidate 내부 `fitting/checkpoints/<id>/`에 Scene, signature가 참조한 Candidate 소유 파일, 설정, 모델링 연결 결과, metrics, 비교 이미지 및 physics 보고서를 복사한다. 외부 원본/불변 자산은 복제하거나 덮어쓰지 않고 SHA를 확인한다. 복원 전 저장 SHA를 검사하며 복원 후 signature를 다시 확인한다. 실패한 모델·자산 버전은 삭제하지 않는다.

완료·자료 부족·호출 상한·Stop·예외 종료 시 선택 checkpoint를 복원한다. 최신 시도가 시각적 완료였더라도 다른 이전 Scene을 복원했다면 `BEST_RESTORED_UNVERIFIED`로 표시하여 완료 판단을 이전 Scene에 옮기지 않는다. 마지막 시도 단계와 선택한 Scene 단계도 분리해 기록한다. 수치 solver 내부 최선 보존은 그대로 유지한다. 선택은 현재 연속 실행 범위이며 과거 실행 전체를 다시 순위 매기는 라이브러리 관리 기능은 아니다.

검증: Builder 전체 **320 passed**. 이후 시각적 완료 상태의 잘못된 승계 방지 시험 및 비교 handoff 파일 복원 추가를 포함한 최종 집중 회귀 **15 passed**. `git diff --check` 통과. `best-checkpoint-suite.*`, `best-checkpoint-focused.*`는 기존 Git 제외 증거 폴더에 보관한다. 모델 child 응답을 대체한 단계 연결 시험이며 실제 사진 정확도 최적화·원격 Codex 실행·하드웨어 검증을 주장하지 않는다.

## 실제 Codex·Blender·Export·Workbench 실행 (2026-11-06)

사용자 요청 2·3번을 실제 실행했다. ChatGPT 로그인된 기존 Codex CLI를 호출했고, 응답을 가짜 실행 파일로 대체하지 않았다. 실행은 Git 제외 `workbench_runs/real_codex_flow_20261106/`의 독립 Project에서 수행했다. 사용자의 Current/Export/Capture를 직접 수정하지 않았다. Camera/로봇 하드웨어에는 연결하지 않았다.

### 실제 입력 분석과 모델 제작

원 등록 Capture의 Side/Wrist RGB와 measured q·구조화 측정값을 복사하고 한국어 실행 메모를 전달했다. 실제 Codex가 8개 Object 계획을 반환했고, 기존 SAM 3.1/DA3 모델 실행 뒤 Codex가 bpy 스크립트를 작성했다. 그 스크립트를 실제 Blender sandbox에서 실행하여 자산 8개를 등록했다. 최초 실패 출력은 보존하고 수정 후 동일 스크립트를 재실행했다. 이는 실제 새 자산 제작/등록 확인이며 장면 전체 복원 성공과 다르다.

실행에서 발견해 수정한 연결 오류:

- 기존 숫자 측정을 `user_memo`로 잘못 되돌려주는 응답: 전달문에서 기존 측정 계승과 메모 인용의 차이를 명시했다. 잘못된 인용 검사는 유지한다.
- SAM 복수 Point+Box 입력: 한 Object의 복수 점을 `[1,N,2]`, label을 `[1,N]`로 전달하도록 수정했다. 기존에는 서로 다른 Object batch로 처리돼 Tensor 크기 오류가 발생했다.
- Codex→Blender의 `tasks.json` 누락: 스크립트와 입력 자료 외에 실제 구조화 작업 파일도 sandbox로 전달한다.
- Asset 붙이기 전후 측정 record의 role/provenance 및 container→compound kind 변화: 원 측정의 의미를 유지하고 기본값을 일관되게 정규화했다. 새 자산을 붙였다는 이유로 동일 입력을 바뀐 측정으로 판단하지 않는다. 이전 실행에서 이미 생성된 자산은 검증 Manifest를 명시 선택해 재개했다.
- Capture URDF가 있는 Robot을 또 RGB Object로 초기화하는 경로: `reference_robot`는 기존 captured Robot 경로를 사용한다.
- Codex 비교 검토가 read-only 파일 읽기까지 금지하던 전달문: tasks.json 읽기는 허용하고 제작/쓰기 실행은 금지한다. Object/image 참조는 JSON Schema enum으로 정확한 ID만 반환하게 했다.
- `refit-pairs` CLI의 연속 실행 옵션이 `import-paired`에 잘못 붙어 있던 오류를 수정했다.

실제 비교 검토에서는 원 Side/Wrist와 Simulator RGB·overlay·difference 총8장을 전달했다. Codex는 정확한 image ID 근거와 함께 `numeric`을 반환했다. Wrist fingertip/inner-jaw·배경 경계, Side의 cup rim/cube/marker 잔차를 지적했고, 형상 변경에 앞서 공유 Camera/배치 정합을 요구했다. 이를 시각적 정합 완료나 물리 인증으로 표시하지 않았다.

### Export·Workbench·Pair 연결

기존 authored Scene의 필요한 자산만 독립 Project로 복사해 새 Package를 Export했다. 기존 Calibration이 참조하는 Leader/Follower 모델과 baked Robot USD closure를 명시 포함했다. `export_revision(..., engine_config={...})`로 이미 준비된 Project 소유 엔진 설정을 함께 등록할 수 있도록 연결했다. 기본 비교 Export를 물리 실행 승인으로 자동 바꾸지 않는다.

새 Revision identity:

- Scene: `execution-check-74768ee5`
- Revision: `checkpoint`
- Manifest SHA: `64a311a74aba8771b5ad18ef3377e9c403197f708fa043240c84340f06667585`

Workbench catalogue에서 이 identity를 확인하고, 실제 native MuJoCo에서 관절 target 두 번·총20 physics step·Side/Wrist 각각480×640×3 RGB를 소비했다. Qt 창에서도 해당 Scene 선택→Package·엔진 설정 준비→재정합 버튼 활성화를 확인했다. 선택 UI는 Memory 구성이고 연결 시작0이다.

별도로 명시 Memory Follower/Camera와 실제 MuJoCo 렌더로 Pair를 저장하고 공식 Reader/`refit_pairs`로 재개했다. Source Revision identity가 위 Export와 정확히 같고 Capture bytes가 변하지 않았음을 확인했다. 이 단계에서 포트만 달라진 Precision Mapping을 Builder가 다른 좌표계로 거부하던 오류를 수정했다. Workbench와 Builder가 공통 비교 함수를 사용하고 SHA·모터/계수/USB 개체 등은 계속 비교한다. 실제 로봇 Capture나 실물 Teleoperation 시험이 아니다.

### 현재 한계와 실행 판정

새로 제작한 자산의 전체 Scene과 저장된 14장 Capture 경로 모두 현재 Solver가 공통 Camera·metric scale을 확보하지 못해 `NEEDS_MORE_DATA`로 끝났다. 따라서 **새 자동 복원 Scene의 정합 완료→최종 승인 Export→실물 Real/Sim 전체 성공은 아직 확인하지 못했다.** 기존 authored Scene의 Export/실행 연결 확인을 새 자동 복원 성공으로 합산하지 않는다. 원본 Camera provenance를 `calibrated`로 바꾸거나 scale/q를 만들어 진행하지 않았다.

실제 Isaac 실행은 이번 후속 범위에서 추가하지 않았다. 새 Package는 양 엔진 closure/Manifest 검사를 받았지만 이번 native 실행은 MuJoCo다. 관측한 기존 USD tool0 reference 및 EGL 경고는 로그에 유지한다.

회귀: Builder 전체와 관련 Workbench 경로 **341 passed**, 이후 최종 handoff/검토/Pair CLI 집중 검사 **6 passed**. 새 실패0, `git diff --check` 통과. JUnit·실제 응답·원/파생 이미지·스크립트·모델 결과·Qt 화면·보존 결과는 위 Git 제외 실행 폴더에 남긴다. 원격 Push/Merge·환경 설치는 하지 않았다.

최종 보존 대조는 이전 기준2,389개 SHA 변경0·누락0이다(`preservation.json`). 독립 실행 Project의 소유 lock도 모두 해제됐다. 이는 전체 SDK/모델 corpus 전수 검사가 아니다.

## 최신 Codex 지침의 실제 런타임 반영 (2026-11-06)

사용자 첨부 `real2sim_codex_guidance_20261106.zip`의 루트 `AGENTS.md`와 `real2sim_builder/CODEX_SCENE_GUIDE.md`를 반영했다. 개발용 AGENTS와 분리된 런타임 가이드의 역할을 구분한다. 기존 문서의 유효한 CLI·과거 검증 성적을 남기면서, 필수 치수 폼·같은 제품의 자동 Group 공유·양 엔진 공동 Solver 완료처럼 읽힐 수 있는 현재 안내를 최신 자유 메모·Object별 독립 USDA·실제 엔진별 구현 범위에 맞췄다.

변경은 기존 `authoring.py` 경로 안에 있다. `modeling_tasks`가 가이드 사본과 참조/SHA를 담은 `CODEX_MODELING.md`를 생성하고, `run_codex_modeling`이 Project/사용자 경로와 무관한 소스 가이드를 매 호출의 `BUILDER_GUIDE.md`로 복사한다. 분석/모델링/비교 프롬프트는 해당 작업 전에 가이드를 전부 읽도록 명시한다. 원본 상대 경로·개정판·SHA는 `input_manifest.json`과 `tasks.json`에, 당시 실제 프롬프트와 출력 Schema는 기존 실행 폴더에 고정한다. 개발자용 통합 절을 추가 작업 권한으로 사용하지 않게 명시한다.

가이드의 SHA-256은 `ef6f7a46a537d7fa2db37e49728a86b959427fa36153b7571aba7bcf6c717657`, 개정판은 `2026-11-06`이다. 패키지 wheel에는 같은 원본을 `share/real2sim_builder/CODEX_SCENE_GUIDE.md`로 포함한다. 설치는 수행하지 않았다. 사용자 Memo로 가이드를 교체하지 못하고, handoff symlink와 child 실행 중 가이드 변조를 거부한다. 분석 캐시에는 가이드 SHA를 남겨 구 지침 응답을 새 지침 실행으로 표시하지 않는다. 기존 자산은 지침 문서 수정만으로 자동 재제작하지 않는다. 기존 offline·workspace-write·API Key 미전달·Blender bwrap 제약을 유지하며 분석/모델링 출력 Schema를 확대하지 않았다. 모델링의 추가 응답 필드도 Python에서 거부한다.

실제 실행은 Git 제외 `workbench_runs/guidance_20261106/`의 독립 Project에서 진행했다. 기존 실제 Side 이미지와 한 물체 제작 메모를 입력으로 실제 Codex 분석과 모델링을 호출했다. 두 child 모두 로그에서 `/bin/bash -lc 'cat BUILDER_GUIDE.md'`, exit0을 확인했다. 분석은 현재 `scene_analysis_schema`로 수용됐고, 모델링은 `script` 단일 필드 응답으로 실제 Blender에서 독립 USDA·충돌체를 등록했다. 작업별 SHA·응답 필드·읽기 명령은 `actual-guidance-verification.json`에 고정한다. 이는 실제 서비스 실행이며 Fake CLI의 응답 대체 시험과 구분한다.

이 실행에서 메모의 box 실측이 USDA compound 충돌체 부착 후 `mesh` 측정으로 바뀌어 Fingerprint가 달라지는 재개 오류를 재현했다. 기존 치수·근거는 유지하고 원 구조화 측정 형상(kind)을 계승하도록 수정했다. 이후 재개에서 `ASSETS_READY`로 기존 자산을 받았으며 새 Codex 호출/재제작 없이 진행했다. Camera/scale은 여전히 미확보라 결과는 `NEEDS_MORE_DATA`다. 가이드 연결 성공을 새 실제 Scene 정합·물리/Task 전체 완료로 표시하지 않는다.

전체 3패키지 회귀 `full-suite.xml`은 **1,520 passed / failed0 / errors0 / skipped0**, 기존 torchvision 경고4회다. 이 실행 이후의 메모 형상 계승·Schema 기록 변경은 별도 최종 관련 회귀로 검사한다. wheel은 원본 가이드 SHA 일치와 소스 포함 여부를 검사하며 설치/업그레이드하지 않는다. 실행 로그·가중치·실사진·생성 USDA는 Git 제외 정책을 유지한다.

이번 요청의 앞부분에는 Commit/Push 금지가 있었으나 마지막에 지정 리뷰 브랜치 업로드를 명시했으므로, 최신 업로드 요청을 기준으로 검토된 코드·테스트·문서만 일반 Push하는 범위로 처리한다. 기존 main/개발 브랜치를 Merge하거나 Force Push하지 않는다.

최종 관련 회귀는 **53 passed / failed0 / errors0 / skipped0** (`guidance_20261106/release-focused.xml`)다. 최종 wheel의 authoring 소스와 가이드 bytes가 작업 트리와 일치하며 설치하지 않았다. 업로드 대상은 코드·테스트·문서79개이고 변경 파일에 대한 비밀정보 패턴·binary·1MiB 초과 파일 검사에서 문제0을 확인했다. 이 검사는 모든 종류의 비밀정보 부재를 수학적으로 증명하는 검사가 아니다. `.gitignore`와 로컬 원본/실행 출력 제외 정책은 유지한다.
