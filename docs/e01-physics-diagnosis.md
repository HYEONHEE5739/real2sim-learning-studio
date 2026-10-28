# E01 — v8 ↔ Workbench Isaac 물리 차이 진단 및 수정

2026-10-26. **이관 오류 2건 수정·실제 엔진 재검증 완료. E01 수치/판정 보존 관문은 OPEN이다.** 수정한 제품에서 오차가 감소했다고 보고하지 않는다. 기존 보고서의 0.011330187rad/2.416924mm는 정확히 재현됐지만, 중복 collider를 제거한 현재 288-part 구성은 **0.145632699rad/29.650773mm, Grasp post222**다. 221에 맞추는 target/tolerance/판정 변경은 하지 않았다. E03/E04/E06은 시작하지 않았다.

이 문서는 [기존 엔진 보고서](simulation-engine-bundle.md)를 대체해 고쳐 쓰지 않는 후속 기록이다. B01~RO03·BU·E01/E02/E05의 기존 증거는 보존한다. 실제 시험은 별도 `evidence/e01-diagnosis/`에서 고정 Sim5.1/Lab2.3.0·Python3.11.15 환경으로 수행했다. 실제 로봇·모터·카메라 연결, SDK/원본/데이터 변경, 설치/업그레이드는 없다.

## 1. 비교 입력과 중요한 초기 상태 구분

B01 `annotation_isaac_A/data/dataset.hdf5`의 `data/demo_0/obs/policy/joint_pos` float32[388,6] 및 `obs/datagen_info/object_pose/cube_red` float32[388,4,4]를 사용한다. 물체 위치는 robot_base 좌표다. SHA는 `e2f5ec4ef55fc354b18d9553ea7668807c894a2b5eea9f846926b570aece325d`다.

비교는 새 실행 `post(t)` ↔ B01 `pre(t+1)`, t=0..386의 **387쌍**이다. `dq[t,j]=q_post[t,j]-q_B01_pre[t+1,j]`, `dp[t,k]=T_post[t,k,3]-T_B01_pre[t+1,k,3]`의 절댓값 최대다. XYZ 최대 성분이며 L2가 아니다. 마지막 post387에는 대응하는 B01 pre388이 없다. [실제 분석 코드](evidence/e01-diagnosis/analyze.py), [모든 step CSV](evidence/e01-diagnosis/per-step-errors.csv), [결과 JSON](evidence/e01-diagnosis/analysis.json), [변화 그래프](evidence/e01-diagnosis/errors.png)에 수치를 남겼다.

**당시 실행의 입력 Source 초기 상태와, Annotation 출력에 다시 저장한 초기 상태는 bitwise 같지 않다.** 기존 `native/annotation.py:_episode`는 원본 Source를 복원한 뒤 `measured_initial(first,base)`로 출력 초기 상태를 구성한다. 이때 pose→matrix/base변환→저장의 수치 경로가 들어간다. 예를 들어 cube_red의 float32 엔진 입력 차이는 Source−Annotation 순서로 X=-1.4901161e-8m, Z=-4.0978193e-8m, Quaternion 한 성분=-5.5879354e-9다. q는 float32로 전달하면 같다. 없는 정보를 만들어 보완하거나 기존 저장값을 수정하지 않았다.

- 당시 실제 Source: `/home/hyeonhee/soarm_isaaclab/soarm101_lab/outputs/workflow/sources/source_20261019_011706_fd32/origin/dataset.hdf5`, SHA `a38a92278e61d1f532904b99a5da7fa0ca96faca6ea509cb5f397f234cc87219`.
- 기존 v8 코드에 **당시 원본 Source 초기 상태**를 넣으면 B01 q 387쌍이 **exact**, 물체 위치는 저장 float32와 최대 **2.6747523e-9m**다. 별도 cube contact 계측 실행에서도 같은 결과였다.
- 기존 v8 코드에 **Annotation 출력 초기 상태**를 넣으면 q 최대0.002766579rad, 물체4.949748mm다. 동일 설정 두 재생은 q/qd/pose/velocity가 서로 exact였다. 이 변화의 입력 원인은 통제 실험으로 확인됐으며 비결정성으로 부르지 않는다.
- 이전 신규 E01 보고서는 Annotation 출력의 초기 상태를 사용했다. 따라서 당시 B01 실행과 엔진에 전달된 모든 초기 bit가 동일했다는 설명은 성립하지 않는다. 이는 초기 상태 재저장의 영향과 이관 오류를 구분해야 한다는 의미이며, 신규 collider 차이를 무시할 근거는 아니다.

Source와 Annotation의 target 배열은 float64 원값부터 exact이고, 각 실행의 실제 float32 target 시퀀스/조회 가능한 target buffer도 일치한다. 과거 B01 Annotation의 qd 전체는 저장돼 있지 않아 소급한 측정값으로 만들지 않았다. q가 B01과 exact인 **현재 v8 재생의 실제 qd**를 대조 자료로 사용했다.

## 2. 실제 실행 설정 차이

[실제 PhysX getter 대조](evidence/e01-diagnosis/runtime-comparison.json), [실행 Stage를 Flatten한 뒤 재조사한 physics/drive](evidence/e01-diagnosis/actual-usd-physics.json), [원본/패키지 collider 수치 감사](evidence/e01-diagnosis/standards-audit.json)를 함께 사용했다. EnvCfg 값만 같다고 결론내리지 않았다.

| 항목 | 기존 v8 실제 실행 | 수정 전 신규 → 현재 제품 / 판단 |
|---|---|---|
| 실행 모델 | `so101_execution_limits.usda` SHA `3b1f4afb…`; baked `so101_sim.urdf` SHA `f78814de…` | 같은 baked URDF SHA. 새 공식 importer USD SHA `bb611453…`. USD bytes/layout은 다름. `so101_sim.usda`와 실제 선택 모델을 혼동하지 않음 |
| root / articulation | `/Robot/root_joint`, fixed base, self-collision=false, solver32/1 | 실제 Stage 값 동일. reference snapshot robot을 추가 물리 robot으로 쓰지 않음 |
| 관절·body 순서 | shoulder_pan/lift, elbow_flex, wrist_flex/roll, gripper / 8 body | 실제 PhysX 순서 동일, tool0 포함. target model rad, scale1/default offset 없음 |
| 질량·COM·관성 | 실제 root PhysX getter의 8-body 값 | **exact**. Cube3/Cup2의 실제 mass/COM/inertia도 exact. 관성 누락을 발견했다는 보고가 아님 |
| link/joint Transform | 기존 보정 USD | 공통17 mesh의 vertex/face exact, link-local 점 최대1.249e-16m. 다만 실제 authored joint localRot0에 float32 차이(예: wrist_roll 약8.94e-8)가 있음. 일치하지 않는 값을 숨기지 않음 |
| joint limits | 기존 execution-limits USD | PhysX 최대1.1920929e-7rad 차이. URDF의 rad 명령 preflight는 유지. 임의 clipping/범위 변경 없음 |
| actuator | 실제 Kp=[55,30,25,12,7,4], Kd=[.7,.8,.7,.5,.5,.3], effort30, velocity약10, armature/friction0 | 실제 getter **exact**, drive type는 양쪽 force. authored USD의 stiffness/damping/maxForce 값은 서로 다르거나 runtime 값과 다름. 공식 ImplicitActuator가 적용한 PhysX 값과 구분 |
| importer metadata | 기존 USD의 JointEquivalentInertia 등 | 재계산된 metadata 수치 차이 존재. 실제 body inertia 및 적용 Kp/Kd와 같은 항목으로 간주하지 않음. 이 metadata만 오차 원인이라고 단정하지 않음 |
| dt / step / Scene | 1/240s ×8=30Hz; TGS, GPU broadphase/dynamics, Fabric=true, gravity 약9.81 | 실제 PhysicsScene attrs **동일**. CCD/stabilization/enhanced determinism 등의 설정도 동일. 같은 joint target을 공식 env.step에 전달 |
| Finger | 기존 STL mesh3개(gripper2/jaw1) 및 pad2, collision group에도 API 존재 | 수정 전에는 **기존3개가 활성인 채 convex288+pad2 추가**. 현재는 기존3개 비활성, 선언된288+2만 활성 |
| Collider 의미 | 전체 STL convex hull, pad는8-vertex Mesh convexHull; 기존 compound/group 구조 | 새 part hull 및 Cube pad. 같은 파일 근거/치수라고 같은 cooking·접촉 manifold가 되는 것은 아님. 288 분할 형상 요구는 유지하나 행동 차이까지 보존됐다고 승인 처리하지 않음 |
| offsets / materials | Cube .002/0, cup은 asset/PhysX 계산값 **.00034062506/0m** | 수정 전 cup258개에 .002/0을 추가한 오류 → **제거**. 현재 Cube/Cup 실제 offsets·material 값은 old와 exact |
| object/table | 원본 Builder collision/physics | Cube3/Cup258 collider geometry·local pose·재질 일치. static7 geometry/활성 상태 같음, table Transform 차이<=4.18e-13m |
| reset | env.reset→q/qd·dynamic 물체 write→forward/update | 새 API는 명시 root/velocity·fixed target도 복원. 실제 restore 회귀는 exact. 과거 Annotation 초기 값의 재저장 차이와 임의 중간 tick solver checkpoint를 구분 |

기존 finger의 활성 CollisionAPI는 **7개(그룹2+STL경로3+pad2)**, 수정 전 신규는293개, 현재는290개다. API 선언 수를 PhysX의 active cooked shape 수와 동일시하지 않는다. Tensor getter의 max_shapes에는 비활성/용량 슬롯도 포함될 수 있다. 공통 mesh의 exact 비교도 모든 compound cooking까지 같다는 증명은 아니다.

S02 baked residual을 q에 다시 더하는 중복 적용, joint ordering/target 시퀀스, 실제 mass/inertia·actuator·Scene solver 설정의 명확한 이관 누락은 이번 대조에서 발견하지 못했다. root/link pose·contact·q/qd는 실제 PhysX 버퍼에서 읽었고 fake 상태를 사용하지 않았다.

## 3. tick 187 / 203–204 / 303–332

[선택 tick의 실제 q/qd·link pose·contact point 자료](evidence/e01-diagnosis/selected-physics.json), [최초 접촉 전 비교](evidence/e01-diagnosis/before-first-table-contact.json), [방출/컵 충돌](evidence/e01-diagnosis/release-impact.json)에 원값이 있다. 아래의 force는 `get_contact_force_matrix(dt=1/240)`로 조회한 마지막 physics substep 값이며 control-step 최대/적분 충격량이 아니다.

### tick187 — 손가락–cube 접촉 이전의 jaw–table 반력

기존 q가 B01과 exact인 재생과 수정 전 신규를 비교하면 tick0..186의 target 차이0, q 최대1.1920929e-7rad, qd 최대3.9935112e-6rad/s다. q/qd까지 bitwise 동일했다고 주장하지 않는다. 명확한 첫 q 증가(>1e-6rad)는187이다.

두 실행 모두187에 처음 로봇 net contact force가 관측됐다. **jaw–table** pair 힘의 norm은 기존0.8957423N, 수정 전 신규0.9212371N이고 jaw–cube는 양쪽0이다. 따라서 “손가락 센서의 cube 접촉0 → 물리 접촉 자체가 없음”은 잘못된 해석이다. 그 반력은 articulation을 통해 shoulder_lift 등 q/qd에 영향을 준다. 신규 shoulder_lift 차이는 -0.0001620427rad다.

288 part를 기존 hull로 바꾼 **진단용** 실행의187 jaw–table 힘은0.8968166N로 바뀌고 q 차이도 달라진다. 형상/접촉 구성에 대한 민감성은 실제로 확인했다. 특정 part의 cooking/개별 접촉점 반력까지 최초 오차의 유일 원인으로 완전히 분해한 것은 아니며, compound group·pad primitive 및 미세 joint frame 차이의 개별 기여는 OPEN이다.

### tick203–204 — 같은 target에서 다른 접촉과 gripper q

203에서 B01/v8은 오른쪽 접촉true, 신규false다. jaw–cube 힘은 기존0.3796092N, 신규0이고,204에는 각각8.8122693N/10.5371815N으로 측정됐다. 단순 센서 threshold 차이를 만들거나 센서를 가짜로 채운 결과가 아니다.

203의 실제 world body 원점 차이(신규−기존)는 gripper 약[-.284,+.150,-.134]mm, jaw 약[-.311,+.214,-.168]mm다. 이는 접촉 표면점 자체가 아니라 body 원점이며 접촉점은 링크된 JSON에 별도로 있다. gripper q는 B01 .2763805091rad ↔ 신규 .2877106965rad, 차이 .0113301873rad다. target은 같다. 초기 pose 재저장과 collider 구성 차이를 통제 실험에서 분리했으며, 이관된 중복 collider가 불필요하다는 사실은 확인했지만 이를 제거하면 B01 접촉이 자동 복원되는 것은 아니었다.

221의 StableGrasp latch 일치는 원래 두 궤적의 물리 동등성 증거가 아니다. 현재 수정된288-part 제품은222이며 같은 pre-step 규칙으로 저장한다면223에 해당한다. 이번에 새 Episode 저장을 실행한 것은 아니다. Task 수식·dt·hold/latch·pre/post 저장 규칙은 변경하지 않았다.

### tick303–332 — 동일 방출 tick, 다른 방출 상태와 cup 충돌

B01 원 trace와 신규 모두 마지막 양측 접촉302,303부터 양측false다. 신규만 먼저 놓았다는 설명은 하지 않는다.303의 world 선속도는 기존[.00368249,.00434838,-.27388030]m/s, 수정 전 신규[.00481509,.00156835,-.27431405]m/s이며 각속도도 다르다.303..305에는 cube–cup_a/table 힘이0이었다.

306에 **양쪽 모두 cube–cup_a 접촉**이 측정됐다. 마지막 substep 힘 norm은 기존 0.135326N, 수정 전 신규 2.255482N 수준이며 반사·회전/미끄러짐이 다르다.306의 선속도는 기존[.181391,-.115641,.063098], 신규[.239463,.001632,.068029]m/s다. 이후 settling 동안 위치 차이가 누적돼332의 robot_base X 성분에서 **-0.0024169236m**가 된다. 이 값을 단순 자유낙하 한 항이나 컵 offset 오류만으로 설명하지 않는다. offset만 기존 값으로 복원한 통제 실험에서는 q/pose/velocity가 바뀌지 않았다.

## 4. 수정과 단일 조건 실험

제품 변경은 [env_cfg.py](../robot_learning_workbench/src/robot_learning_workbench/engines/isaac/env_cfg.py) 및 [test_isaac_engine.py](../robot_learning_workbench/tests/test_isaac_engine.py)뿐이다. [실제 diff](evidence/e01-diagnosis/product.diff).

1. `_disable_imported_finger_colliders`: 기본 PrimRange가 instance 자손을 건너뛰는 재현 시험을 RED로 확인했다. 공식 USD 지침대로 실행 layer에서 instance를 해제한 뒤 기존 finger collider를 끈다. 원본 USD·다른 wrist collider·참조 바이트는 보존한다. 작은 nested-instance 독립 리뷰도 통과했다. 원본 asset 변경/새 Manager 없음.
2. target cup에는 기존에 없던 `.002/0` override를 하지 않는다. dynamic Cube 설정은 유지한다. 실제 PhysX getter로 cup의 원래 auto offset 복원을 확인했고, 잘못된 값의 RED 및 수정 후 GREEN 근거를 보존했다.

| 실제 실행 / 바꾼 조건 | q 최대 rad / tick·관절 | 위치 최대 mm / tick·축 | Grasp / latch |
|---|---|---|---|
| 수정 전 신규 재현 | .011330187 /203 gripper | 2.416924 /332 X |221 / B01 exact |
| 중복 collider만 제거 | .145632699 /301 gripper |29.650773 /304 Z |222 / 불일치 |
| 위 상태에서 cup offset만 복원 = 현재제품 A/B | .145632699 /301 gripper |29.650773 /304 Z |222 / 불일치 |
| 현재제품에 원본 Source initial만 사용 | .141768336 /301 gripper |29.848876 /304 Z |222 / 불일치 |
| 위 조건에서288part만 끄고 기존 hull 활성(진단 전용) | .004931480 /203 gripper |4.019409 /307 Y |221 / exact |
| 기존v8 + Annotation 출력 initial, 동일설정2회 | .002766579 /203 gripper |4.949748 /308 Y |221 / exact |
| 기존v8 + 원본 Source initial, 별도계측 포함2회 | **0 / 전체q exact** |.000002675 /289 Z |221 / exact |

진단용 legacy hull은 evidence harness 조건이며 **제품 선택 옵션/fallback으로 추가하지 않았다**. 현재제품 A/B의 q/qd/pose/velocity는 exact, cup offset만 바꾼 전후도 exact다. 원본 Source를 넣은 기존 실행 역시 재현됐다. 이번 자료에서 남는 차이를 검증된 비결정성이라고 부르지 않는다.

첫 numeric reproduce의 exact assert는 차이 재현을 위한 RED 신호이며, 모든 다른 물리 실행에 bitwise equality라는 새 tolerance를 강제한 것이 아니다. collider 재현 시험은 실제 USD instance 참조를 사용한다. 물리 결과의 최대값·실패 latch를 가려서 GREEN으로 표시하지 않는다.

## 5. 실제 회귀·보존·리뷰

- **744 passed, 0 skipped**, 기존743개+instance collider 회귀1개. [JUnit](evidence/e01-diagnosis/unit-tests.xml), [로그](evidence/e01-diagnosis/logs/17-full-suite.log). 기존 torchvision deprecation warning2개는 남는다.
- 실제388 control step·종료 시점 양 camera640×480 RGB uint8·현재 PhysX 부모×mount를 확인했다. 현재제품 종료 snapshot의 wrist mount 행렬성분 오차최대1.2659975e-7, robot root/joint 및 Cube3/Cup2 pose/velocity restore는 시작 snapshot과 **모든 필드 exact**다. [현재제품 결과](evidence/e01-diagnosis/runs/corrected-B/result.json), [runtime 회귀 검사](evidence/e01-diagnosis/runtime-regression.json).
- 물리 접촉은 실제 view/sensor 값이다. 기존 + 원본 initial의 Grasp221/B01 latch exact는 재현됐다. **현재제품 Grasp222/latch 불일치는 회귀 실패/OPEN**이며 generic pytest 통과로 대신하지 않는다. pixel 동일성·모든 센서 timestamp·임의 solver 내부 checkpoint는 미검증이다.
- [wheel](evidence/e01-diagnosis/build.json): source/config bytes·compile·isolated import·CLI/실제 worker의 미구현 stage 거부 smoke 통과. 같은 개발 패키지0.4.0이며 새 wheel SHA로 식별한다. 기존 환경에 설치하지 않았다. 설정된 lint/type command는 없어 수행했다고 보고하지 않는다.
- [Standards 리뷰](evidence/e01-diagnosis/final-standards-review.md)와 [Spec 리뷰](evidence/e01-diagnosis/spec-review.md) 두 독립 검토에서 제품 patch의 추가 차단 결함은 없었다. 물리 보존 OPEN은 별도다. 단순화 검토 후 작은 helper/두 설정만 유지하고 다른 코드 정리는 하지 않았다. Git 저장소가 없어 Git diff/commit을 수행했다고 주장하지 않는다.
- 최초 조사 harness의 cfg partial 직렬화·잘못된 Articulation property·table filter·cube contact report 누락 실패도 로그/결과에 남겼다. 올바른 native 조회로 고친 뒤 재실행했다. cube report를 활성화한 진단용 계측은 이전 q/pose 결과를 그대로 재현했다. query 실패를 force0으로 바꾸지 않았다.
- Isaac의 기존 tool0 visual unresolved reference·Fabric/RTX 및 deprecation warning은 남는다. SDK material-cache에 쓰려는 Python 동작은 읽기 전용 audit가 차단했고 로그에 남았다. 쓰기 제한을 해제해 통과시키지 않았다. 실제 RGB/Step 성공을 무경고 종료라고 설명하지 않는다.
- [보존 대조](evidence/e01-diagnosis/preservation-after.json), [명령/identity](evidence/e01-diagnosis/commands.json), [최종 검증](evidence/e01-diagnosis/verification.json)에 원본·이전 완료 증거·선택 SDK 소스 및 이번 입력 SHA를 기록한다. 기존56,100개 stat·선택16,623개 SHA 변화0(허용된 제품2파일 제외)다. 전체 corpus/SDK binary 전수 byte 검증은 아니다.

## 6. 완료 판단과 남은 관문

**E01 완료 불가.** 288-part 요구와 v8 Isaac의 실제 기존 collision/cooking 구성이 같지 않다는 사실이 확인됐다. 중복/컵 override 이관 오류는 수정했지만 현재 분할 형상은 B01 궤적과 grasp tick을 보존하지 못한다. 기존 hull 진단에서도 남는 수치의 compound/group collision·pad Mesh/Cube·joint frame/importer 미세 차이별 기여는 완전히 분리하지 못했다. 이를 임의로 보정하거나 기존 USD로 제품을 되돌리지 않았다.

후속 판단에는 기존 Isaac의 compound/cooked shape와 요구된288part의 물리 의미를 어떻게 맞출지, 과거 Annotation의 재저장 초기 상태로 어느 재현 수준을 약속할지 명시해야 한다. Scene·Native Dataset C·Calibration/Task 계약을 근거 없이 바꾸거나 이 문제를 새로운 비결정성으로 면제하지 않는다. B01 Isaac DataGen 실패·Evaluation의 별도 비결정성, B02 누락/Resume identity, B03 실물 검증 상태는 그대로다. **이번은 E01 진단·확인된 오류 수정까지만 수행하고 E03/E04/E06은 시작하지 않는다.**

공식 근거: [OpenUSD instance 편집/탐색](https://openusd.org/release/api/_usd__page__scenegraph_instancing.html), [Lab2.3 URDF converter](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.sim.converters.html), [Lab2.3 ContactSensor](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.sensors.html#isaaclab.sensors.ContactSensor). 실제 tensor API·공식 converter와 ImplicitActuator의 설치 소스도 읽고 SHA를 남겼다. incremental-implementation/source-driven-development/diagnosing-bugs/TDD 및 두 축 review·최소화·문서 기록 지침을 적용했다.
