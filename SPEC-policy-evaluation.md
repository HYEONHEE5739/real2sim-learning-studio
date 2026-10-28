# SPEC: Simulation·실물 평가·Real/Sim

ID: `policy-evaluation`. 작성: 2026-10-25. 상태: **구현 전 검토용 명세**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). 이번 사용자 요청에 따라 SPEC과 계획을 함께 작성했으며 구현 착수 승인을 의미하지 않는다.

## 목표와 범위

공식 Policy 추론을 기존 시뮬레이션/실물 제어 의미에 맞게 연결한다. 엔진별 단계 성공 조건과 실물 기록 의미를 유지한다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| P workflow/evaluation.py evaluate_sim, policy.py, mujoco.py, operations.py | 관측/명령·rollout·평가 지표·종료 의미 | engines/{isaac,mujoco}/evaluation.py |
| P real2sim/runtime.py 및 workflow 실물 실행 경로 | Real/Sim 동기·장치 제한·실물 평가 기록 | robot/evaluation.py, robot/real_sim.py |

구현 파일 범위: `engines/isaac/evaluation.py, engines/mujoco/evaluation.py, robot/evaluation.py, robot/real_sim.py`. 경로는 robot_learning_workbench의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `robot_learning_workbench/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- 공식 LeRobot0.4.1 Policy를 기존 엔진 환경에서 사용한다. 업그레이드 충돌 해소용 분리 추론·async·별도 RPC는 구현하지 않는다. 기존 관측/processor/action·동기 시점을 보존한다.

- Policy→action의 오프라인 매핑은 저장 샘플로 먼저 검증한다.
- sim 평가는 엔진 state/Task/Policy 계약만 필요하고 DataGen 전체 완료에 의존하지 않는다.
- 실물은 ROBOT-01/02, CAL-01/02 완료와 실물 시험 승인이 필요하다. sim 성공으로 대체하지 않는다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- 기본 Simulation Evaluation은 Placement 성공 종료이며 grasp/transport/full_task_success는 별도 지표다. Annotation의 성공 조건을 재사용한다는 이유로 강제하지 않는다.
- checkpoint/processor·camera feature·joint order·측정/명령 공간을 검증한 후 rollout한다. 필요한 매핑을 확인할 수 없으면 시작 차단한다.
- 실물 성공 자동화는 기존 확인된 기능만 이관한다. 현재 알 수 없는 접촉/성공을 시뮬레이션 판정으로 채우지 않는다.
- Real/Sim은 구체 엔진 함수와 장치 모듈을 직접 연결하고 새 공통 Env를 만들지 않는다. 취소·timeout·장치 해제의 기존 의미를 보존한다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## 검증과 완료 기준

- **policy-evaluation-AC01**: 양 엔진 baseline의 최초 종료 tick·Placement/추가 지표 및 정상 Task 실패 분류 일치.
- **policy-evaluation-AC02**: 외부 공식 Policy에 전용 provenance가 없다는 이유만으로 차단하지 않되 action/관측 미확인은 차단.
- **policy-evaluation-AC03**: 실물 관측→명령→중지의 승인된 시험 기록 확보; sim/실물 검증 상태 별도 표시.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래는 **테스트 파일 및 환경 구축 후 사용할 목표 명령**이며 현재 실행하지 않았다. 실제 robot_learning_workbench 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest robot_learning_workbench/tests/test_simulation_evaluation.py robot_learning_workbench/tests/test_real_evaluation_contract.py robot_learning_workbench/tests/test_real_sim.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 한계: 앞의 선행 확인과 실제 회귀 시험은 미완료다. 구현 전 확인할 세부값은 확인 목록에서 해제하며 근거 없는 값으로 명세를 채우지 않는다.


## 2026-10-27 P01 구현·실행 범위

[P01](docs/p01-simulation-rollout.md)은 현재 Scene/공식 ACT/단일 env/Fixed에서 AC01의 Placement 전용 성공·post-step 지표·정상실패·기록 phase, AC02의 official Policy/명시 IO binding·strict 원값/payload 검사를 실제 양 엔진으로 검증했다. 각 엔진2 Episode×60step은 모두 max_steps 실패이며 성공 최초 tick은 없다. 다른 B01 checkpoint/조건의 전체 수치 동등성이나 실제 성공률을 완료 처리하지 않는다.

이번 사용자 결정으로 clip/clamp/rate 평활화/직전 target Hold·fallback 없이 원Action과 적용dtype를 기존 model limits로 거부한다. 기존 v8 ActionGuard의 clip/rate 동작과의 의도된 차이를 보고했다. Native 완료 failure는 새 출력 Resume에서 보존하고 취소/불완전은 정상 Episode로 공개하지 않는다. P02/P03·AC03 실물·장시간·Random/같은앱 복수Episode는 미검증이다. 기존 E01/Smol/Follower OPEN도 해제하지 않는다.
