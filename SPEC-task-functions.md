# SPEC: Task 등록·판정·배치

ID: `task-functions`. 작성: 2026-10-25. 상태: **T01~T04 지원 범위의 순수 계산/등록 오프라인 검증 완료; 엔진 통합 미착수**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). 이번 사용자 요청에 따라 SPEC과 계획을 함께 작성했으며 문서 전체의 구현 착수 승인을 의미하지 않는다. 후속 사용자 승인으로 [T01](docs/t01-task-registry.md)과 [T02](docs/t02-pick-place.md)를 수행했다. AC01의 순수 수식/상태·경계/phase 및 AC03 등록 부분을 검증했으며 [T03](docs/t03-placement-reset.md)에서 AC02의 v8 uniform/3mm·Fixed 검사·seed/RNG·1000회/오류 부분도 검증했다. [T04](docs/t04-collision-contact.md)에서 AC02의 지원 다면체/convex 평면 접촉 배치를 구현했다. 곡면 primitive·비평면 support·native 변환은 미지원이며 실제 엔진/Recipe/UI 통합은 미완료다.

## 목표와 범위

v8의 순수 계산과 상태 판정을 재사용 가능한 Python 함수로 제공한다. 새 Task 파일·명시적 등록만으로 선택할 수 있고 core/UI 분기를 추가하지 않는다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| P real2sim/workspaces/grasp.py StableGrasp; environment.py task_success_details; simulation/mujoco_backend.py success_details | latch/window·target-local 8꼭짓점·속도/부등호 계산 | tasks/pick_place.py 함수·상태 factory·등록 선언 |
| P real2sim/workspaces/reset.py sample, tasks.py validate_reset_pose | uniform·크기/margin/separation·3mm·검사 순서 | tasks/placement.py fixed/random 및 별도 collision_contact |
| P workflow/task_scripts.py, task_terms | 기존 단계별 호출 의미만 참고 | tasks/registry.py 명시 모듈 목록·이름/파라미터 검증 |

구현 파일 범위: `tasks/registry.py, tasks/pick_place.py, tasks/placement.py, task_modules.yaml`. 경로는 robot_learning_workbench의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `robot_learning_workbench/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- registry의 중복/타입/미지원 검사부터 독립 시험할 수 있다.
- v8 순수 판정은 기존 함수의 동일 입력 Baseline과 V8-01/V8-02의 관련 의미 확인 후 이관한다. live 접촉 binding은 엔진 단계에서 검증한다.
- placement는 V8-03 확인 후 구현한다. 기존 후보 추출/엔진 실패 예산의 차이를 1000회라는 숫자만으로 합치지 않는다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- FUNCTIONS 선언·plain predicate·tracker factory·acceptance·placement는 interfaces.md 5절을 따른다. Episode/env별 상태를 분리하고 반복 tick 갱신/누락 tick/latch를 보존한다.
- Annotation/Production DataGen은 Placement AND latched StableGrasp; 기본 Evaluation은 Placement. Source에 성공 gate를 추가하지 않는다.
- Fixed는 XY 보정 없이 오류, Random은 허용된 재추출 한도 소진 시 run 중단. Task 수행 실패·IK 재생성 예산은 별도다.
- 작업 대상 생성 목록, Metadata default 자세, frame/작업면, collision 기반 높이와 v8 규칙을 구분한다. 네 anchor 방식은 신규 제공 기능에서 제외하되 과거 기록 의미는 유지한다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## 검증과 완료 기준

- **task-functions-AC01**: 기존 모든 부등호 경계, 0.2초 창·반복/누락 tick·drift·latch와 최초 성공 tick 일치.
- **task-functions-AC02**: 중심/바닥/편심 원점·회전·복합 collision의 Fixed/Random 접촉 높이; v8 3mm 결과 별도 일치.
- **task-functions-AC03**: 임시 테스트 Task 모듈+등록 목록만으로 선택 가능; 기존 core/UI 수정 없음.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래 전체 명령은 **테스트 패키지의 의존성을 설치한 경우 사용할 기본 명령**이다. T01/T02/T03/T04는 source checkout PYTHONPATH와 기존 interpreter로 검증했고 실제 명령/환경을 각 결과 보고서에 남겼다. 실제 robot_learning_workbench 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest robot_learning_workbench/tests/test_task_registry.py robot_learning_workbench/tests/test_pick_place.py robot_learning_workbench/tests/test_placement.py robot_learning_workbench/tests/test_contact_placement.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 한계: 등록 97개·Scene 138개·T02 판정/호출 72개, T03 41개와 T04 53개를 포함한 총 401개 시험을 통과했다. B01 raw grasp 2,618회와 저장 pre-step frame을 대조했다. T03 v8 배치/RNG와 T04 지원 Geometry의 오프라인 비교는 완료했고 live signal/엔진 연결과 AC 전체의 실제 엔진 회귀는 미완료다. 구현 전 확인할 세부값은 확인 목록에서 해제하며 근거 없는 값으로 명세를 채우지 않는다.

## 2026-10-27 승인 변경 — Workspace Random Pose

사용자 결정: 신규 DataGen Random Pose는 `placement.random_workspace` / `workspace_entropy_v1`을 사용한다. 실제 Workspace Object의 로컬 평면·Collision X/Y 치수(현재 Marker150×150mm), Object Collision 형상/원점/scale, Support 실제 윗면으로 XY 영역과 접촉 Z를 계산한다. 기본 Roll/Pitch0·Yaw0이며 명시 yaw_rad는 실제 회전 Footprint로 검사한다. 기본24mm Cube 중심 범위±63mm는 치수에서 도출하며 상수가 아니다. 블록 Footprint 최단 거리>=24mm, 고정 장애물 비중첩, Workspace/실제 Support 포함을 요구한다.

Pose는 인자 없는 `np.random.default_rng()`만 사용한다. Pose Seed·RNG state/continuation·임의 XY/orientation override를 받지 않는다. 기존 Source/Mimic/Training/Native Seed 및 T03 역사적 sampler를 삭제하지 않는다. 새 DataGen에서는 seeded `random_xy/contact_random_xy`를 지원 경로로 선택할 수 없다. Fixed의 기존 수치/순서/Seed 의미는 보존한다.

물체별1000회 유한 후보 검사 후 INVALID_PLACEMENT를 기록하며, 검증된 전체 batch만 적용한다. native XYZ/Quaternion dtype 변환 후에도 strict Geometry 경계를 검사한다. 무효 Pose를 적용하거나 좌표 보정/한계 확대/관절 Clipping으로 통과시키지 않는다. 기존 T04의 contact_pose/hull/polygon_distance를 재사용하며 새 Manager/Framework는 없다. 실제 곡면/오목·robot link collision은 offline Footprint 검사와 구분한다.

[구현·경계·실제 엔진 검증](docs/random-placement-horizontal.md). 기존 T03/v8_preserved·T04/collision_contact의 조사/기대값을 새 Random 규칙으로 바꾼 것이 아니다.
