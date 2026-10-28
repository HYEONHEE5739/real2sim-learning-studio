# SPEC: 양 엔진 Source·Annotation·DataGen

ID: `simulation-workflows`. 작성: 2026-10-25. 상태: **E02·E05 기반 완료, E01 실제 실행 기반 구현·검증 및 전체 numeric 동등성 OPEN; 단계별 Workflow 미착수**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). 이번 사용자 요청에 따라 SPEC과 계획을 함께 작성했으며 구현 착수 승인을 의미하지 않는다.

## 목표와 범위

v8을 Isaac Lab과 MuJoCo 양쪽에서 즉시 사용할 수 있도록 단계별 기존 실행을 보존한다. 엔진 loop 통합을 목표로 하지 않는다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| P native/source.py prepare/run, native/annotation.py _episode/run, native/isaac.py, native/mujoco.py | 기록·복원·수동/자동 채택·pre/post 시점 | engines/{isaac,mujoco}/{source,annotation,state}.py |
| P simulation/mjcf.py, workspace_scene.py, mujoco_backend.py 및 기존 control | 보정 asset·finger collision·물리/센서 의미; SciPy IK/Strict/Hold 제외 | Isaac env_cfg/mdp, MuJoCo model/control |
| P workflow/datagen.py run_mujoco/run_isaac, workflow/mimic.py 및 reference | source 선택·waypoint/offset·seed·budget·Task 실패 분류; IK는 아래 고정 계약으로 변경 | generation/mimic.py, reference 및 엔진 datagen.py |
| P utils/so101_kinematics.py inverse_kinematics, simulation/ik.py DLS_PARAMETERS·solve_selected의 best_effort 분기 | DLS 계산·측정 seed·candidate 안전 검사만 재사용; Solver dispatch/정책 선택은 제외 | 기존 generation/mimic.py의 공통 계산 및 엔진 datagen.py 연결 |

구현 파일 범위: `engines/isaac/{env_cfg,mdp,state,source,annotation,datagen}.py, engines/mujoco/{model,state,control,source,annotation,datagen}.py, generation/mimic.py, generation/reference/`. 경로는 robot_learning_workbench의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `robot_learning_workbench/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- 개발/검증 기준은 Sim5.1/Lab2.3·MuJoCo3.3.7이다. B01에서 기존 v8을 고정한다. Native Source·Annotation의 전환과 DataGen·Evaluation 미전환 경로는 계산·행동 Reference이며 미완성 구조는 복제하지 않는다.

- 엔진별 V8-01/02/03, 적용되는 CAL-01/02와 Episode 기록 매핑·Baseline을 확보한다.
- recorded fixture로 Annotation/DataGen을 검증할 수 있으며 Source 실물 장치나 Builder 전체 완료를 기다리지 않는다.
- Isaac과 MuJoCo는 독립 구현·검증 가능하다. 완료는 양쪽 결과가 모두 필요하다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- Isaac은 AppLauncher 후 import, SceneCfg/EnvCfg/MDP/공식 state API; MuJoCo는 MjModel/MjData와 mj_step/mj_forward를 직접 사용한다. 기존 control/physics dt를 엔진 간 통일하지 않는다.
- 선택 블록만 실제 생성하고 robot/table/camera/cup 기준 배치는 유지한다. 원본 Scene은 쓰지 않는다.
- Source pre-step 관측/영상·명령 기록, Annotation recorded initial 복원과 post-step tracker, manual mark/skip/취소 의미를 보존한다.
- DataGen은 annotated 자료와 호환 Scene을 사용한다. 초기 배치 1000회 실패는 run 중단한다. IK는 아래 승인된 DLS + Best Effort 계약을 적용하며 Task 실패/재생성 budget은 기존 의미를 유지한다.
- reference Mimic의 라이선스/upstream·알고리즘 identity를 보존한다. 공식 구조 활용을 이유로 검증 없는 최신 알고리즘 교체나 MuJoCo 공식 Mimic 지원 주장을 하지 않는다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## DataGen IK 고정 계약

확정: 2026-10-25 사용자 지시. **Pinocchio DLS + Best Effort 단일 경로**만 구현한다. SciPy IK Solver, Strict/Hold 분기·선택 UI·Recipe 옵션·호환 fallback은 구현하지 않는다. 최종 DataGen 성공은 기존 **latched StableGrasp AND Placement**이며 IK 수렴과 별개다. 다음 수치는 기존 코드에서 확인한 보존 대상이며, 이번 문서 갱신에서 실행 검증한 결과는 아니다.

### 계산과 명령의 구분

| 항목 | 고정할 의미 / 근거(P 기준) |
|---|---|
| 실제 DLS 파라미터 | `simulation/ik.py:DLS_PARAMETERS`: position_weight=1.0, orientation_weight=0.01, max_iterations=200, tolerance=1e-3, damping=1e-3, step_size=0.3. `inverse_kinematics` 함수 signature의 기본값으로 바꾸지 않음 |
| 모델·seed | `utils/so101_kinematics.py:SO101Kinematics`의 모델/frame/joint lookup과 float64 계산. SO101 팔 5개 관절의 현재 **측정값**으로 시작. 직전 명령은 jump 기준이며 seed로 대체하지 않음. 그리퍼 목표는 별도로 보존 |
| 좌표 | target을 기존 방식대로 robot_base의 4×4 pose로 변환. 보정된 모델 identity·joint order·FK/엔진 frame 관계 유지, residual 이중 적용 없음 |
| 오차·Jacobian | translation=`target-current`, rotation=`pin.log3(R_target @ R_current.T)`, `LOCAL_WORLD_ALIGNED` Jacobian의 팔 joint velocity 열. 활성 행에 기존 position/orientation weight를 적용 |
| DLS update | `dq = Jw.T @ solve(Jw @ Jw.T + damping*I, ew)` 후 step_size 곱. damping을 제곱한 식으로 바꾸지 않음. 기존 weighted norm `< tolerance`, 반복/종료·반환 진단 시점과 순서 보존 |
| 반복 내부 관절 제한 | DLS가 각 반복에서 모델 limit으로 q를 제한하는 기존 동작 유지. 최종 검사 실패 candidate를 clipping해서 적용하는 정책과 구분 |
| 상태 소유 | env/worker별 Pinocchio mutable Data 및 previous_command 분리. 엔진 runner가 소유하며 공유 계산에 필요한 수치만 전달; 모델/장치/step을 감싼 새 Adapter·ABC 없음 |

### Best Effort 적용 경계

1. target·측정 관절·직전 명령·limits의 shape와 finite 값을 확인한다. SO101은 6개 전체 명령/관절값과 (6,2) limits, 팔 candidate shape=(5,) 계약이다. 부적합 입력을 수렴 실패로 덮어쓰지 않는다.
2. 기존 `solve_selected` best_effort 검사대로 candidate의 shape/finite 및 팔 limits를 확인한다. 관절 제한 위반 비교는 `q < lower-1e-7` 또는 `q > upper+1e-7`다. 그리퍼 목표 역시 원래 limits와 1e-7 경계 검사를 보존하고 solver가 최적화하지 않는다. 엔진의 실제 명령 경계도 별도로 유지·검증한다.
3. 팔 5개 관절 각각에 대해 **직전 실제 적용 명령**과의 절대 차이를 계산한다. `max(abs(candidate_arm-previous_command_arm)) > 0.5 rad`이면 거부한다. 실제 값이 정확히 0.5인 경우 이 검사 자체는 통과하며, 경계 전후·dtype/좌표를 시험한다. dt로 나눈 속도 검사나 DLS 내부 iteration당 한도로 바꾸지 않는다. Episode reset/restore 때 previous_command를 실제 초기 명령으로 설정하고, 적용되지 않은 candidate로 갱신하지 않는다.
4. 안전 검사를 통과하면 DLS 미수렴 또는 pose 진단 기준 초과여도 candidate+gripper 목표를 적용한다. 기존 pose 진단 기준(position 0.003 m, rotation 0.12 rad)은 **기록 지표**이며 적용·채택 gate가 아니다. native 수렴, pose 진단 통과, candidate 유효성, command 적용, Task 성공을 구분한다.
5. candidate의 shape/finite/limit/jump 검사가 실패하면 **해당 attempt를 즉시 중단**하고 invalid 원인과 미적용 상태를 기록한다. 측정 자세 Hold·다른 solver 재시도·명령 clipping으로 대체하지 않는다. 정상 분류된 실패 후 다음 attempt 허용 여부는 기존 max_attempts/목표 성공수 budget을 따른다. 초기 배치 소진의 run 중단 정책과 혼동하지 않는다.
6. 원래 pre-step 기록 → 명령 적용/physics → post-step tracker → 종료/채택 시점을 유지한다. IK가 명령을 적용했다는 이유로 성공 Episode를 commit하지 않는다. StableGrasp/Placement 공식·threshold·접촉·latch·시점은 그대로다.

### 변경 비교와 구현 단계 시험

- [B01](docs/b01-baseline.md)의 SciPy + Strict trace·원본·실패 결과는 변경하지 않는다. 신규 결과를 기존과 같게 만드는 시험이 아니라 **승인된 IK 변경의 영향**(명령/궤적/실패 분류/성공률)을 같은 입력에서 보고한다. 기존 Isaac의 strict 실패가 새 정책에서 성공할 것이라고 미리 단정하지 않는다.
- DLS 계산 자체는 기존 Pinocchio DLS + Best Effort 함수에 같은 모델/target/측정값/previous command를 주어 candidate·진단·안전 거부를 비교한다. 기존 B01 성공률을 새 정책의 정답으로 삼지 않는다. 이 fixture는 **DataGen 구현 착수 시** 별도 증거에 확보하며 B01 증거를 덮어쓰지 않는다.
- 단위 시험: 실제 DLS 식/파라미터/seed/frame/limit 내부 처리, 유효한 미수렴·오차 초과 candidate의 적용, 잘못된 shape/NaN/Inf/limit/그리퍼, jump 0.5 바로 아래/같음/위, reset/restore·부분 env reset·명령 미적용 시 previous_command 수명. 수치 수렴만으로 Task 성공이 되지 않는지 확인한다.
- 계약 시험: `ik_solver`, `ik_failure_policy`, solver 파라미터/한도 override 등 실행 선택 필드는 시작 전에 `RECIPE_INVALID`와 field 위치로 거부한다. Python fallback·UI 선택 위젯도 없음을 확인한다. 고정 정책은 시스템 결과에 기록한다.
- 양 엔진 시험: 동일 annotated input/Scene/seed의 target·변환·측정 seed·candidate·적용 명령·physics 추적·grasp/place 결과를 기록한다. Isaac은 공식 SceneCfg/EnvCfg/MDP와 상태 API, MuJoCo는 MjModel/MjData/mj_step을 사용한다. 두 엔진의 물리/접촉 수치를 강제로 동일화하지 않는다.
- Resume 시험: 과거 SciPy/Strict/Hold 또는 identity 미확인 run을 새 고정 정책의 continuation으로 받지 않는다. 과거 자료 열람/독립 annotated 입력 사용과 DataGen Resume를 구분한다. 새 고정 계약끼리도 code/파라미터/입력 identity 등 기존 검사를 통과해야 한다.

공통 계산은 기존 `generation/mimic.py` 책임 안에서 한 번 구현하고 각 엔진의 `datagen.py`가 모델·Data·측정 상태·좌표 변환·적용을 연결한다. MuJoCo `control.py`/Isaac MDP는 해당 엔진의 명령 및 physics 책임을 유지한다. Solver plugin/registry/추상 계층이나 별도의 IK 선택 시스템을 만들지 않는다. 이번에는 명세만 수정했으며 이 절의 시험은 모두 구현 단계 계획이다.

## 검증과 완료 기준

- **simulation-workflows-AC01**: 엔진별 같은 초기 입력의 pose/joint/camera/contact·기록 시점·판정 trace 비교 통과.
- **simulation-workflows-AC02**: Source/Annotation/DataGen 각각 정상·실패·취소·Resume 경로, 완료 Episode 보존.
- **simulation-workflows-AC03**: DataGen source 선택·RNG/offset·budget 의미 보존. DLS + Best Effort 계산/안전 경계는 기존 해당 함수와 비교하고 B01 SciPy + Strict 대비 trajectory/실패 결과 차이는 승인된 변경으로 보고. 양 엔진 완료·StableGrasp AND Placement 채택·정상 Task 실패 분류 확인.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경·DataGen 고정 IK 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래는 **테스트 파일 및 환경 구축 후 사용할 목표 명령**이며 현재 실행하지 않았다. 실제 robot_learning_workbench 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest robot_learning_workbench/tests/test_isaac_workflows.py robot_learning_workbench/tests/test_mujoco_workflows.py robot_learning_workbench/tests/test_mimic_regression.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 한계: 앞의 선행 확인과 실제 회귀 시험은 미완료다. 구현 전 확인할 세부값은 확인 목록에서 해제하며 근거 없는 값으로 명세를 채우지 않는다.

## E01·E02·E05 현재 증거 범위

[엔진 묶음](docs/simulation-engine-bundle.md)의 실제 양 엔진 Step/contact/restore·현재 camera/RGB와 E05 B01 계획을 확인했다. AC01의 E02 기반과 E01 event phase/latch는 검증했으나 Isaac 전체 numeric trace는 미해결 차이가 있어 통과로 표시하지 않는다. AC02의 Source/Annotation/DataGen runner/취소/Resume와 AC03의 E06 DLS/실행/채택은 여전히 미구현이다. 전체743개 단위/회귀 통과를 이러한 미완료 관문의 대체 증거로 사용하지 않는다.

### 이전 E01 물리 차이 진단 관문 (아래 최종 결정으로 구현 변경)

[후속 진단](docs/e01-physics-diagnosis.md)에서 imported instance collider 중복과 target cup offset override를 수정했다. 당시288-part 제품의 Grasp post222/수치 차이는 AC01 보존 실패/OPEN이며, 과거 수정 전221 latch 증거를 현재 제품의 회귀 통과로 사용하지 않는다. 기존 v8+당시 원본 Source initial은 B01 q exact이고 Annotation 출력 initial 재저장 영향은 별도로 확인했다. 수치 tolerance·판정·target 보정 또는 구형 hull 제품 fallback을 추가하지 않았다. 744개 일반 회귀·실제 실행 및 독립 patch 리뷰 완료와 E01 물리 보존 완료를 구분한다. E03/E04/E06은 여전히 미착수다.

### E01 최종 v8 Collision 보존 계약

2026-10-26 사용자 결정: Isaac은 기존 v8 실제 실행 USD의3 STL convex hull·Mesh pad2·group/instance·물리/재질/joint frame을 보존한다. 새288-part 생성·Cube pad 재작성·URDF 재import·기존 collider 비활성화 코드는 제거하며 solver/collider 선택·fallback을 만들지 않는다. Builder는 명시 native robot USD와 closure를 신규 Revision에 등록하고 E01은 package binding을 직접 사용한다. MuJoCo의 검증된288 경로는 바꾸지 않는다.

B01 재현은 당시 원본 Source initial과 target을 사용하며 Annotation 재저장 initial의 차이는 별도 호환성 증거로 보존한다. [현재 결과](docs/e01-v8-collision-recovery.md):388step q/qd·robot contact·Grasp post221 및 pre222 latch 복구, 동일 설정 A/B exact. Cube는306의 cup 충돌 이후 위치 최대1.197188790mm/tick310 Y 잔차가 있어 full AC01은 OPEN이다. 일반748개 회귀/Stage 속성·closure/이동/Reset/RGB 시험으로 이를 면제하지 않는다. E03/E04/E06은 시작하지 않았다.


## 2026-10-27 — MuJoCo E03/E04 및 E06-a 확인 범위

[결과](docs/mujoco-workflows-ik.md)의 실제 수집/Native 재로드·원 Source initial 재생·Manual/Auto·공식 Pool/MP4·worker/중복 명령·중단/새 출력 Resume는 AC02의 **MuJoCo 기본 Workflow 부분**이다. 별도 optional signal/metric 실행 및 양 엔진 AC 전체 완료가 아니다. AC03의 E06-a는 실제 기존 DLS candidate/진단/Best Effort와 동일 입력 비교·0.5rad 및 limit/identity 경계를 검증했다. 엔진 DataGen 명령 적용·이전 target 수명·Task 성공 채택/성공률은 E06-b/c에 남긴다. E01 cube–cup 이후 물체 위치 최대1.197188790mm 잔차는 계속 OPEN이다.

## 2026-10-27 Random Pose 정책 변경·실행 경계

신규 Random DataGen은 Seed 없는 `placement.random_workspace` batch를 기존 Fixed와 같은 Mimic→DLS Best Effort→엔진 Step→StableGrasp AND Placement→Native publish 흐름에 제공한다. Pose RNG 복원/continuation은 요구하지 않는다. **AC03의 기존 Mimic source/offset/noise·Attempt/Training Seed 보존은 계속 요구하며 Pose Seed와 구분한다.** v8 Scene·Frame·Collision·IK/Task 기준은 변경하지 않는다.

Geometry 실패는 INVALID_PLACEMENT 실패 attempt로 완료 처리하며 성공 Episode를 만들지 않는다. SDK Reset/부분 쓰기 오류는 별도 engine_reset_error/effect=unknown으로 기록·전파한다. 이미 완료된 Native segment는 새 출력 Resume에서 불변 보존하고 다음 attempt의 Pose는 새로 생성한다. 구 정책/Scene/model/code/배치 계약이 다르면 continuation을 거부한다.

Isaac은 한 fresh worker당 Random 한 attempt로 제한한다. 목표/전체 예산이 남으면 fresh_worker_required를 반환하며 다음 worker에서 Resume한다. 이 결과로 같은 앱 복수 Reset/복수 Annotation·다중 env/장시간 동등성을 해제하지 않는다. MuJoCo는 기존 native Reset 관통 검사/rollback을 사용한다. offline Geometry와 실제 물리 Collision PASS는 구분한다. [실제 실행·기록·Fixed 회귀](docs/random-placement-horizontal.md).

## 2026-10-28 최종 Position Target 정책 갱신

사용자 승인으로 최종 엔진 position command는 원 URDF 안의 native dtype 경계로 Saturation한다. 이는 앞의 **유효하지 않은 IK candidate를 clip해서 살리지 않는다**는 조건을 바꾸지 않는다. Pinocchio DLS/Best Effort 계산·shape/finite/기존 candidate limit·0.5rad previous-applied jump 조건은 유지한다. 통과한 candidate의 float32 변환으로 발생하는 초과는 안쪽 `nextafter` 경계로 제한하고 최종 payload의 jump/finite/원 한계를 다시 확인한다.

새 Source/Annotation/DataGen/Evaluation의 학습 target `joint_targets`는 Applied이고, Requested/solver command·Saturation mask/delta는 `commands/*`에 별도 보존한다. 과거 Source·Baseline·Native/LeRobot 파일은 수정하지 않는다. Task 수식과 pre/post-step phase, Source recording_only·Annotation/DataGen grasp AND placement·Evaluation Placement 성공은 유지한다. [실제 복구 보고](docs/position-saturation-recovery.md)에서 정책 차이와 엔진 결과를 구분한다.
