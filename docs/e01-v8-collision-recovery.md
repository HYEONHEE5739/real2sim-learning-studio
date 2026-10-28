# E01 — v8 Native Collision 보존·Isaac 재검증

2026-10-26. **기존 실행 USD·Collision 이관과 실제 Isaac 재검증을 완료했다. 관절/접촉/Grasp 보존은 복구됐으나, 컵 충돌 이후 물체 위치 잔차 때문에 E01 전체 수치 관문은 OPEN이다.**

이번 사용자 결정에 따라 Isaac의288-part 생성 경로를 제거하고 **v8의 실제 `so101_execution_limits.usda`를 패키지에서 직접 참조**한다. 3 STL hull·Mesh pad2·collision group 계층·instance·joint frame·재질을 재작성하지 않는다. MuJoCo의 기존288-part 경로는 유지했다. 원본/이전 Revision·B01~RO03·BU/E의 이전 보고서·진단 증거는 수정하지 않았고 E03/E04/E06은 시작하지 않았다.

## 1. 변경 전후와 파일 책임

| 파일 | 변경 내용 / 이유 |
|---|---|
| [Builder export.py](../real2sim_builder/src/real2sim_builder/export.py) | `export_revision`의 명시적 `isaac_robot_asset`을 기존 native closure copier로 수집하고 `robot.bindings.isaac.asset_path`에 연결. 실제 실행 USD 의존성도 `verify_package`가 검사. SDK의 명시 MDL resolution과 상대 module closure 지원 |
| [Isaac env_cfg.py](../robot_learning_workbench/src/robot_learning_workbench/engines/isaac/env_cfg.py) | baked URDF의 rad한계/identity와 실제 실행 USD를 구분. 등록된 USD가 없거나 bytes가 다르면 거부. 공식 `UsdFileCfg/spawn_from_usd`로 참조하며 URDF 재import·convex288/Cube pad 생성·기존 collider 비활성화 helper 제거. 고정 target에 새 rigid-body 기본값을 덧씌우지 않음 |
| [Builder export 시험](../real2sim_builder/tests/test_builder_export.py) | native USD/MDL closure·이동·원본 불변·누락/미지원 거부·publish 실패 경계 추가 |
| [Isaac 시험](../robot_learning_workbench/tests/test_isaac_engine.py) | 새 Revision fixture로 input binding 검증. execution USD 누락 거부 추가. 폐기한288 collider 교체 함수 전용 시험 제거; 이전 증거는 보존 |

제품 수정은 위4개 파일뿐이다. `mdp.py/state.py`·Task/Calibration·Native Dataset C·Recipe·Robot·MuJoCo 코드는 변경하지 않았다. 새 Manager/Adapter/Registry·collider/solver 선택·fallback·UI/Recipe 옵션은 없다. 테스트를 통과시키려고 구형288 실행기를 남기지 않았다. 일반 Builder 프로젝트 로드/수정·validation·candidate·신규 Revision Export·UI/CLI는 기존 기능/시험을 유지한다. 새 native asset 입력은 Export 함수의 명시 파일 입력이며, 자동 원본 저장소 검색을 하지 않는다.

| 구성 | 이전 제품 | 현재 Isaac 제품 |
|---|---|---|
| robot | 보정 URDF를 공식 importer로 재생성 | 패키지에 복사한 기존 보정 실행 USD 직접 사용 |
| finger |288 hull+Cube pad2, 이전에는 원래 hull3개 중복까지 존재 | 원래 hull3개+원래8-vertex Mesh pad2 |
| 계층/cooking | 신규 Mesh/Cube 프림 생성으로 group·joint 변환/primitive 표현 차이 | native hierarchy·instance와 approximation·hull settings·joint frames 그대로 |
| 양 finger CollisionAPI | 그룹 구조가 없는290개 | **7개: 기존 group Xform2+STL 경로3+pad2** |
| PhysX articulation shape 용량 | 이전 분할 형상은321 등의 capacity | 기존과 현재 모두 **max_shapes50**. capacity/API 개수만으로 active cooked shape를 증명하지 않음 |
| MuJoCo | 검증된288 parts+pad | 변경 없음 |

`/gripper/collisions`, `/jaw/collisions`의 그룹 Xform에 있는 CollisionAPI와 실제 **UsdPhysics.CollisionGroup**은 구분한다. 비교한 old/new 실제 Stage에는 별도 UsdPhysics.CollisionGroup prim이 모두0개였고, native collider 계층과 self-collision=false 관계를 그대로 유지했다. 존재하지 않는 CollisionGroup schema를 새로 만들어 “복구”하지 않았다.

## 2. 새 Revision·파일 closure와 기존 정합 보존

[실제 Export 코드](evidence/e01-v8-collision/prepare_scene.py)는 원본 Builder 프로젝트의 기존 `final_contact_review` 후보와 v8의 profile/task/physics·보정 선언을 읽는다. scene 재제작·segmentation/registration 재실행·Camera/Robot fitting은 하지 않았다. 기존 BU03 API로 **신규 `scene-v8-native` Revision**만 publish했다.

- scene_id=`scene2-final-contact-review-20261014-932c8f2e`, revision=`scene-v8-native`.
- Manifest SHA=`64bff80050a883880e7e6363dd3e5b2f517fd72bb96743e3e529c89a2dfaa3c9`, 등록84개 파일.
- 실행 USD source SHA=`3b1f4afb02f7b062fff2d0823d014fa808bfeaa05b4a6e0518edc3b1b1f1cc44`. 로컬 경로를 패키지 상대 참조로 바꾼 파일은 파생 SHA를 Manifest에 등록하고 source SHA는 provenance에 남긴다.
- 실행 URDF SHA=`f78814de0d341a4a46b2d37759e9206be7d66bca8445ea6867058c43dd6cd589`; baked residual을 q에 다시 더하지 않는다.
- [패키지 감사](evidence/e01-v8-collision/package-audit.json): robot native closure10개 파일 전부 Manifest 등록, 기존/패키지의 composed joint/collision/mass/transform42개 prim 속성 exact. 원본·현재·실행 모델 identity는 서로 구분한다.
- 이전 Scene과 **48 Object/Geometry/물성·Frame·Support·2 Camera K/extrinsics/mount·Calibration record**가 exact다. provenance의 원래 Builder Scene도 exact다. Camera raw K를 새 렌더 K로 덮어쓰지 않는다.
- publish 뒤 패키지를 `runspace/relocated/scene-v8-native`로 이동했다. 이전 위치는 없으며 모든 실제 엔진 child는 이동한 패키지를 재로드했다. [이동 기록](evidence/e01-v8-collision/package-move.json). native reference는 패키지 내부 상대 경로이고 원본 repo의 geometry를 런타임 fallback으로 읽지 않는다.

기존 USD는 `OmniPBR.mdl`을 SDK resolver에서 찾는다. 이를 누락으로 무시하지 않고 **명시 resolution map**으로 SDK 원본을 읽어 OmniPBR/상대 module을 패키지에 복사했다. 알 수 없는 절대 MDL import를 모두 SDK로 취급하는 검토 반례는 수정했다. 지원 범위는 설치된 OmniPBR의 단순 상대 module과 알려진 `::df/state/math/base/tex/anno/debug/nvidia::core_definitions`다. 미지원/custom module은 ASSET_UNSUPPORTED다. SDK의 표준 MDL runtime과 Isaac 설치 자체는 실행 의존성으로 남는다. SDK와 독립인 포맷/패키지라고 주장하지 않는다. MDL 저작권 문구는 파일 그대로 보존했다.

MuJoCo가 사용하는 Finger Convex JSON·Pad 및 정확한 source hash 파일은 계속 등록한다. 이 공유 파일을 삭제하지 않고, **Isaac이 해당 JSON을 읽어288개를 생성하는 제품 코드만 제거**했다.

## 3. B01 실제 재생 — 원본 Source initial 기준

이번 B01 재현은 당시 Annotation이 실제로 읽었던 Source initial을 사용한다. [이전 진단](e01-physics-diagnosis.md)의 Annotation 재저장 initial 차이는 별도 보존하며 데이터 자체를 고치지 않았다.

- Source=`/home/hyeonhee/soarm_isaaclab/soarm101_lab/outputs/workflow/sources/source_20261019_011706_fd32/origin/dataset.hdf5`, SHA `a38a92278e61d1f532904b99a5da7fa0ca96faca6ea509cb5f397f234cc87219`.
- B01 Annotation 저장 SHA=`e2f5ec4ef55fc354b18d9553ea7668807c894a2b5eea9f846926b570aece325d`.
- 입력 target float64 배열은 Source/Annotation에서 exact이며 실제 전달 float32 target과 PhysX target buffer도 exact다. 388 control step을 수행하고 **B01 pre(t+1) ↔ 신규 post(t), t0..386의387쌍**을 대조했다. 마지막 post387에는 B01 pre388이 없다.
- q는 B01 저장 float32와 **387쌍 모든6관절 exact**. qd는 B01에 저장되지 않았으므로 과거 측정값을 만들어 비교하지 않았다. B01 q를 exact 재현한 이전 v8 실제 재생의 qd와 **388 step exact**다.
- StableGrasp 최초 **post221**, pre-step latch 배열 **exact**, B01 저장 first frame222다. 새 Writer/실제 Episode 저장을 실행한 것은 아니며 기존 frame222와 새 pre-step snapshot을 대조했다.
- 최초 로봇–table 힘187, 오른쪽 cube 접촉203, 양측204 및 전체 robot contact force 배열이 기존 재생과 exact다. 판정 threshold·hold/latch·곱 순서·Quaternion 순서·dt를 변경하지 않았다.
- 실제 dt1/240×8, TGS/GPU/Fabric·root32/1·self-collision=false·Kp/Kd·effort/velocity limits·관절 limits·mass/COM/inertia가 v8과 같다. 이번 native USD 사용으로 이전 importer joint-frame/limit 차이가 제거됐다.
- [실제 Stage/PhysX 감사](evidence/e01-v8-collision/runtime-audit.json): contact offset/material의50 shape-slot 행은 multiset exact(슬롯 나열 순서 차이와 실제 값 차이를 구분). native source의 approximation·pad Mesh·collision tree를 유지하고 실제 힘/kinematics까지 검증했다.

raw Stage 경로는 기존 `gripper/WorkspaceMount/<부품>` ↔ 신규 `gripper/<부품>`으로, **collisionEnabled=false인14개 카메라 mount 부품**에서 다르다. 이 경로를 정규화하면 robot joint/collision/mass/transform/drive 속성이 exact다. raw missing-path28개를 숨기지 않고 JSON에 남겼다. 이를 active finger hull 또는 PhysX contact 차이로 오인하지 않는다.

[최종 실행 A](evidence/e01-v8-collision/runs/final-native-A/result.json), [B](evidence/e01-v8-collision/runs/final-native-B/result.json), [step CSV](evidence/e01-v8-collision/per-step-errors.csv), [분석 코드](evidence/e01-v8-collision/analyze.py), [수치 JSON](evidence/e01-v8-collision/analysis.json), [그래프](evidence/e01-v8-collision/errors.png).

| 조건 | 관절 최대 차이 rad | 물체 XYZ 최대 성분 차이 | 최초 Grasp |
|---|---:|---:|---:|
| 지난 분할288 제품·Annotation initial | .145632699 / tick301 gripper |29.650773mm / tick304 Z |222 |
| 지난 진단용 hull·Source initial(재import 모델) | .004931480 / tick203 gripper |4.019409mm / tick307 Y |221 |
| **현재 native USD·Source initial, A/B** | **0 / 모든 비교 q exact** |**1.197188790mm / tick310 Y** |**221** |

q가 모두 같으므로 “최대 q 오차 tick0”이라는 argmax 결과는 최초 관절 오차라는 의미가 없다. **관절 차이 발생 tick은 없음**이다. 위치는 float32 저장/float64 pose 표현 차이가 첫 step부터 존재할 수 있다. 물리 상태 차이는 아래처럼 이전 v8 actual replay와 별도로 판별했다.

## 4. 남은 위치 차이와 통제 실험

현재와 old v8 Source-initial 재생의 cube pose matrix는 tick0..305에서 최대 약2.22e-16 수준의 표현 차이이며 **world velocity는 exact**다. 최초 velocity 차이는 **tick306의 cube–cup_a 충돌**이다. 이후 회전/settling 경로가 달라지고310의 robot_base Y에서 최대1.197188790mm가 된다. q/qd와 robot–table/cube 힘은 이 구간에서도 exact다. XYZ 최대 성분을 L2 거리라고 부르지 않는다.

동일 설정 A/B는 q/qd·cube pose/velocity·robot 힘 및 cube contact matrix 모두 **exact**였다. 따라서 이번 잔차를 입증된 비결정성이라고 부르지 않는다. cup collider local transform·geometry는 exact이며, “눈에 보이는 형상이 같다”만으로 모든 PhysX contact 상태/접촉점 순서가 같다고 결론내리지 않는다.

별도 증거 harness에서 한 조건씩 바꿨다.

| 조건 | 결과 / 해석 |
|---|---|
| 고정 cup snapshot을 현재 Scene pose로 대체해 복원 | 잔차 불변. Source의 수치값을 임의 보정해 제품에 넣지 않았고 fixture 실험으로만 남김 |
| 고정 cup에 쓰는 root pose/velocity 호출 자체 생략 | 잔차 불변. 해당 원인으로 단정하지 않아 제품 state.py를 변경하지 않음 |
| 고정 target의 rigid-body override 제거 | 잔차 불변. 기존 v8의 native 설정 보존을 위해 제품에서 불필요 override는 제거 |
| 기존 v8 cup USD2개를 closure-copy해 직접 사용 | 잔차 불변. target asset 교체 기능/선택 옵션을 제품에 추가하지 않음 |

**원인 미확정:** 컵 충돌 시 contact manifold·solver 내부 상태/shape/actor 순서 등의 기여를 특정하지 못했다. 이를 버그로 확정하거나 “충돌 hull이 달라서”라고 반복하지 않는다. native robot 이관으로 q/Grasp는 복구됐지만 full object numeric gate는 통과하지 못했다. SDK를 수정하거나 target/pose/Calibration/성공 판정을 보정해서 차이를 없애지 않았다.

## 5. 실제 실행·회귀·보존

- **실제 Isaac**:388 control step, actual articulation/target/q/qd/contact·2camera640×480 RGB uint8·현재 PhysX wrist mount를 확인했다. 종료 snapshot mount 행렬 차이최대3.0349414e-7이며 RGB는 비균일 실제 render다. pixel 동등성·모든 영상 frame의 timestamp 동등성까지 증명한 것은 아니다.
- **Reset/restore**: 최종 A/B에서 robot root pose/velocity·joint q/qd 및 Cube3/Cup2 root pose/velocity가 시작 snapshot과 모든 필드 exact다. 이것을 임의 중간 tick solver/warmstart checkpoint 지원으로 확대하지 않는다.
- **MuJoCo3.3.7**: 새 Scene Revision으로 실제 Step/contact·state restore/replay·RGB를 수행했다. [결과](evidence/e01-v8-collision/mujoco/phase-baseline.json). B01 Source q최대2.2204460e-16rad, Annotation3.4805492e-14rad로 이전 E02와 exact 같은 비교값. Annotation post222/pre223 latch exact. robot geometry/JSON/수식·controller는 변경하지 않았다.
- **전체748 passed, skipped0**, [JUnit](evidence/e01-v8-collision/unit-tests.xml), [로그](evidence/e01-v8-collision/logs/19-full-suite.log). 기존 torchvision deprecation warning2개가 있다. 일반 단위시험 숫자를 물체 궤적 동등성 PASS로 사용하지 않는다.
- [Workbench wheel](evidence/e01-v8-collision/build-workbench.json) 및 [Builder wheel](evidence/e01-v8-collision/build-builder.json): source bytes/compile·isolated import·실제 미구현 stage 거부 worker/CLI·Builder clone smoke 통과. 환경에 설치하지 않았다. 기존0.4.0/0.1.0 개발 버전은 유지하고 새 wheel SHA로 식별한다.
- [Standards](evidence/e01-v8-collision/final-standards-review.md), [Spec](evidence/e01-v8-collision/spec-review.md) 독립 검토를 수행했고 MDL closure finding은 RED→수정→GREEN 후 해제했다. 최소 helper/직접 API만 남기고 별도 단순화 refactor는 하지 않았다. Git 저장소가 없어 Git 절차/commit을 수행했다고 보고하지 않는다.
- 최초 Export의 미해결 SDK material 참조·시험의 closure 파일 수 오기(실제3을4로 예상)는 로그에 보존하고 입력/시험을 바로잡았다. 원본·geometry·tolerance는 바꾸지 않았다. `tool0/visuals`의 기존 unresolved prim 및 Fabric/RTX/SDK deprecation warning은 남는다. SDK material-cache에 쓰려는 Python 동작은 readonly audit가 차단했으며 설치 원본 쓰기를 허용하지 않았다.
- [원본/선행 증거 보존](evidence/e01-v8-collision/preservation-after.json)·[최종 검증](evidence/e01-v8-collision/verification.json)에 작업 전후 stat·선택 SHA·신규 package hash·명령을 남긴다. 기존56,100개 파일 stat·선택17,153개 SHA는 허용된 제품4파일 외 변화0이다. 전체 corpus/SDK binary 전수 hash 증명은 아니다. 기존 Scene Revision·실제 Source/Annotation·환경·이전 보고서는 그대로다.

공식 근거는 설치된 Lab2.3 `spawn_from_usd/UsdFileCfg/ImplicitActuator`·PhysX tensor API와 [공식 spawner 문서](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.sim.spawners.html), [OpenUSD dependency API](https://openusd.org/release/api/dependencies_8h.html)다. incremental-implementation/source-driven-development/diagnosing-bugs/TDD 및 실제 로컬 code-review/code-simplification/documentation-and-adrs 지침을 적용했다.

## 6. 완료 경계와 직접 확인

**v8 native robot Collision 구조의 이관·관절/Grasp/latch 복구는 검증됐으며 E01 전체는 OPEN이다.** 아직 해결하지 못한 cube–cup 충돌 이후1.197mm 잔차, pixel/센서 시점 전체·다양한 Scene/multi-env/장시간 동작은 별도 관문이다. 이 결과로 E03/E04/E06을 자동 시작하지 않는다.

직접 확인할 곳: (1) `robot.bindings.isaac.asset_path`와 Manifest의10개 native closure, (2) `env_cfg.execution_inputs/spawn_robot`의 단일 USD 경로와 제거된288 생성 코드, (3) 최종 A/B의 Grasp221/latch exact와 `analysis.json`의306 이후 object 잔차를 함께 확인한다. 원본 Source initial과 Annotation 재저장 initial은 계속 다른 근거로 관리한다.
