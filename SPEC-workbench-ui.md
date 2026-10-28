# SPEC: Workbench UI 통합

ID: `workbench-ui`. 작성: 2026-10-25. 상태: **구현 전 검토용 명세**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). 이번 사용자 요청에 따라 SPEC과 계획을 함께 작성했으며 구현 착수 승인을 의미하지 않는다.

## 목표와 범위

기존 화면 역할·시각 구성을 유지하면서 설정은 저장 Recipe 중심으로 전환한다. Task별 설정 폼과 MiniVLA 자체 학습 화면은 승인 범위대로 제외한다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| P real2sim/ui.py, precision_ui.py; workflow UI/curation_ui.py | 전체 화면·버튼·영상·로그·장치/검토 흐름과 스타일 | ui/app.py, theme.py 및 각 단계 화면 |
| 기존 실행/설정 위젯 | 실제 단계 기능 보존; object/task 체크 폼은 Recipe로 대체 | ui/recipe_editor.py, workflow.py, preview.py |

구현 파일 범위: `ui/app.py, ui/recipe_editor.py, ui/workflow.py, ui/capture.py, ui/real_sim.py, ui/calibration.py, ui/curation.py, ui/preview.py, ui/theme.py`. 경로는 robot_learning_workbench의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `robot_learning_workbench/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- 편집·파일 저장·dirty·로그·mock worker UI는 엔진 없이 검증한다.
- 실제 단계 화면 연결 시 해당 단계 계약만 요구한다. 전체 workflow 완료를 UI 모든 부분의 착수 조건으로 삼지 않는다.
- 기존 화면 inventory·대표 화면/동작 증거를 확보하고 제거/대체 목록을 승인된 변경과 대조한다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- 외부 YAML 불러오기·내장 편집·같은 저장 위치·명시 저장을 제공한다. engine 선택은 버퍼를 변경하고 dirty 상태에서 실행을 막는다.
- stage mismatch·필드 오류는 위치/원인을 보여준다. 미저장 버퍼를 실행하거나 숨은 UI config로 덮어쓰지 않는다.
- Capture/RealSim/Work Pipeline/Precision Calibration/Curation/Source/Annotation/DataGen/Conversion/Training/Offline Validation/Sim·Real Eval/Hub 화면을 모두 대응한다.
- Preview·진행·로그는 worker를 읽으며 UI가 engine/robot 객체를 소유하지 않는다. 새 Task에 전용 UI 분기를 추가하지 않는다.
- 공식 학습 로그만 조회한다. 누락 LR/loss를 만들기 위해 모델 실행이나 Trainer 확장을 하지 않는다.
- DataGen IK는 고정 Pinocchio DLS + Best Effort다. 기존 Solver/Failure Policy 선택 UI와 Strict/Hold·SciPy 선택을 이관하지 않으며 Recipe 옵션으로 옮기지도 않는다. 고정 정책/수렴·안전 거부·Task 실패 진단은 필요 시 읽기 전용으로 표시한다. IK 수렴 표시를 Task 성공으로 표시하지 않는다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## 검증과 완료 기준

- **workbench-ui-AC01**: 기존 전체 기능 inventory 대응 누락 0; 제거 요소는 Recipe 대체/MiniVLA 제외/DataGen 고정 IK 승인 근거 표시. IK Solver/Failure Policy 선택 위젯·숨은 override 없음; 고정 정책 및 진단은 worker 결과 조회만 사용.
- **workbench-ui-AC02**: dirty·엔진 변경·stage 불일치·중복 실행·지연 mark/skip·취소·UI 종료 시험 통과.
- **workbench-ui-AC03**: Preview backlog/로그 누락·조회 오류가 Dataset 기록/Trainer 계산에 영향 없음; CLI와 저장 설정 일치.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래는 **테스트 파일 및 환경 구축 후 사용할 목표 명령**이며 현재 실행하지 않았다. 실제 robot_learning_workbench 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest robot_learning_workbench/tests/test_recipe_editor.py robot_learning_workbench/tests/test_ui_protocol.py robot_learning_workbench/tests/test_ui_workflows.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 한계: 앞의 선행 확인과 실제 회귀 시험은 미완료다. 구현 전 확인할 세부값은 확인 목록에서 해제하며 근거 없는 값으로 명세를 채우지 않는다.

## 2026-10-27 사용자 승인 범위와 실제 구현

최신 요청은 U01 기본 UI, U02 Source/Annotation/실제 Preview, U03 DataGen/Curation, U04 ACT/Evaluation, X01 UI 통합 순서다. 이 범위가 과거 U03 Capture/Calibration 및 전체 화면 inventory의 이번 구현 순서를 대체한다. 실물·Hub·Smol·v9는 이번에 확장하지 않는다. [실제 결과](docs/workbench-ui-bundle.md)에서 완료/부분/BLOCKED와 증거를 구분한다. 기존 AC01의 모든 장치 화면 완료를 체크하지 않는다.

이번 명령 정책은 Source/Teleop 및 실제 적용되는 모든 최종 target의 original/payload를 원래 URDF bounds로 strict 검사한다. float32 반올림 초과도 거부하며 DLS 내부 projection/Geometry clamp는 보존한다. 이 정책으로 보존 Isaac Source Annotation과 새 DataGen command가 거부되는 관문은 OPEN이다.

### 2026-10-28 후속 사용자 정책 — Position Saturation

위2026-10-27의 최종 target No-Clipping/rounding 거부는 최신 승인으로 대체됐다. 유한 최종 Position Target은 원 URDF limits 안의 dtype 표현 가능한 경계로 Saturation하고 원 요청/Applied/변경 mask·delta·Task 결과를 구분한다. 범위를 늘리거나 epsilon을 쓰지 않는다. 잘못된 입력/Calibration/Mapping·DLS candidate 및 previous-applied jump guard는 유지한다. [실제 복구](docs/position-saturation-recovery.md)는 보존 Isaac Source index323 재생 및 Random DataGen tick348 관문을 실제 Step/Native 소비자로 확인한다. 과거 UI 보고/증거는 변경하지 않는다.
