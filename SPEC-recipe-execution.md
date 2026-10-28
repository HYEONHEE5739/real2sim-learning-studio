# SPEC: Recipe·작업 프로세스·IPC

ID: `recipe-execution`. 작성: 2026-10-25. 상태: **R01~R03 파일/로컬 작업 프로세스 기반 구현·검증 완료**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). 최초 명세 작성은 구현 승인이 아니었다. 후속 사용자 승인으로 2026-10-26 [R 묶음](docs/recipe-execution-bundle.md)을 수행했다. 실제 engine/학습/장치/UI 통합 완료를 의미하지 않는다.

## 목표와 범위

저장된 YAML만 실행하고 UI/CLI가 같은 검증·상태 기록을 사용한다. 새로운 launcher/service/command bus는 추가하지 않는다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| P workflow/operations.py execute_request 및 기존 실행/IPC 코드 | stage별 실행·중지·상태·오류 의미 | recipe.py, run.py, cli.py에 책임 재배치 |
| 기존 UI 저장/실행 흐름 | 명시적으로 승인한 Recipe 방식으로 변경 | 원문 hash·dirty 검사·worker 설정 snapshot |

구현 파일 범위: `recipe.py, run.py, cli.py`. 경로는 robot_learning_workbench의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `robot_learning_workbench/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- YAML 순수 검사·중복 요청·프로세스/IPC 시험은 가짜 작업 함수로 독립 검증한다.
- Scene/Task 참조는 해당 계약이 필요할 때만 연결한다. 일반 Training에 Scene/Task registry를 요구하지 않는다.
- 장치 중지/명령 IPC만 ROBOT-01과 연결되며 기존 pause/step 의미는 stage별 확인한다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- read_recipe/prepare_recipe, StartRequest/WorkerRequest는 interfaces.md 4/8절을 따른다. 원문 bytes를 한 번 읽어 hash/parse하며 외부 config와 모듈 identity도 고정한다.
- 같은 request ID+payload는 기존 handle, 다른 payload는 충돌. 배타 claim 후 상태 불명일 때 자동 재시작하지 않는다.
- control 메시지와 stdout 로그를 분리한다. command ID·대상 Episode·applied tick으로 중복/지연 명령을 거부한다.
- Native publish 완료와 terminal 기록은 Preview 채널 손실과 분리한다. 작업 오류와 정상 Task 실패를 구분한다.
- 실행 output 신규 예약은 공식 Trainer Resume 규칙을 임의 덮어쓰지 않는다. 공식 checkpoint 입력/출력 제약을 해당 버전에서 확인하고 충돌을 보고한다.
- DataGen의 고정 Pinocchio DLS + Best Effort는 사용자 선택값이 아니다. `ik_solver`, `ik_failure_policy` 및 DLS/안전 한도 override 필드는 `RECIPE_INVALID`와 field 위치로 거부한다. 고정 정책과 같은 값도 허용하지 않으며 숨은 UI/CLI override·자동 변환을 만들지 않는다. 시스템은 실제 고정 IK identity/값을 effective_settings/결과에 기록한다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## 검증과 완료 기준

- **recipe-execution-AC01**: 잘못된 stage/engine/object/frame/function/중복 key/NaN 및 DataGen IK 선택/override 필드는 실행 전 필드 오류. IK 필드 없는 Recipe는 고정 DLS + Best Effort로 해석되고 실제 정책은 시스템 기록에서 확인 가능.
- **recipe-execution-AC02**: 저장 이후 파일 변경·이중 클릭·claim crash·ack 유실에서 숨은 설정 변경/이중 실행 없음.
- **recipe-execution-AC03**: 미지원 pause/step은 거부; dirty UI 실행 차단과 CLI 단독 실행이 동일 계약 사용.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 실제 검증은 기존 interpreter/PYTHONPATH로 수행했고 [commands.json](docs/evidence/recipe-execution/commands.json)에 기록했다. 아래는 같은 suite의 명령 예시다. 실제 robot_learning_workbench 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest robot_learning_workbench/tests/test_recipe.py robot_learning_workbench/tests/test_recipe_preparation.py robot_learning_workbench/tests/test_run_claims.py robot_learning_workbench/tests/test_worker_protocol.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 근거: 전체 571개(신규 R 65)·skip 0, 실제 fixture child/명령·ACK·취소·SIGKILL·완료 Episode 보존·wheel CLI/worker 및 원본 보존을 검증했다. AC01 선언/준비, AC02 로컬 claim/프로토콜, AC03 CLI/공유 guard·미지원 명령 부분을 완료했다. 실제 UI dirty 흐름·engine/공식 Trainer/Policy/Hub·장치 stop·실행 중 Resume는 후속이다. 미구현 stage를 성공 처리하지 않는다. [Task 증거](docs/evidence/recipe-execution/task-results.json).


## 2026-10-26 최종 Native 저장 전환

2026-10-26 최종 C Native 전환: [구현·검증 보고](docs/native-dataset-transition.md). 사용자 확정에 따라 자체 Episode별 HDF5/Index/Descriptor/Migration을 제거하고 공식 불변 HDF5 segment + 최소 Metadata·영구 Curation·명시 LeRobot materialization으로 교체했다. NATIVE-01/02/03의 파일·공식 CPU 소비자 관문을 검증했다. 과거 D/R/RO 보고서·증거는 보존하며 BU/E·실물·UI·Trainer 실행은 시작하지 않는다.
