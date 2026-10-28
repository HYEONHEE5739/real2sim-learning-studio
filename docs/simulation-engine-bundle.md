# E01·E02·E05 — Simulation Engine 기반 구현·검증

2026-10-26. **E02·E05 완료, E01 구성/실제 실행·복원·판정 시점 검증 완료, 전체 B01 수치 동등성은 OPEN**이다. 정적 USD/MJCF 로딩만으로 완료 처리하지 않았다. 실제 양 엔진 Step·접촉·상태 복원을 수행했고, E03/E04/E06·IK·실제 로봇/모터/카메라·외부 업로드는 시작하지 않았다. [SPEC](../SPEC-simulation-workflows.md), B01/B02/B03·S01/S02·[BU 결과](builder-bundle.md)를 기준으로 한다.

## 구현과 호출 흐름

| 작업 | 실제 파일·주요 함수 | 책임/상태 |
|---|---|---|
| E01 | [env_cfg.py](../robot_learning_workbench/src/robot_learning_workbench/engines/isaac/env_cfg.py): execution_inputs/build_env_cfg/spawn_robot, [mdp.py](../robot_learning_workbench/src/robot_learning_workbench/engines/isaac/mdp.py): reset_scene/apply_joint_targets, [state.py](../robot_learning_workbench/src/robot_learning_workbench/engines/isaac/state.py): initial_state/restore_episode/read_sample | 공식 AppLauncher 이후 ManagerBasedEnv/InteractiveScene/Articulation/MDP·관측·RigidObject·FrameTransformer·실제 ContactSensor·Camera 구성. 실제 실행/복원과 grasp tick/latch 검증. 전체 궤적 동등성 OPEN |
| E02 | [model.py](../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/model.py): build_model/ModelConfig, [control.py](../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/control.py): command_target/step, [state.py](../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/state.py): snapshot/restore_episode/reset_object_poses/read_sample | 공식 MjModel/MjData·관절/actuator·카메라/Geometry·실제 Finger/pad·10 substep/forward·opaque integration snapshot·관통 rollback. 실제 B01 재생/판정 시점 확인 |
| E05 | [mimic.py](../robot_learning_workbench/src/robot_learning_workbench/generation/mimic.py): source_pool/randomize_boundaries/plan_subtask/RandomStream, [reference](../robot_learning_workbench/src/robot_learning_workbench/generation/reference/) | 공식/기존 Mimic1.0.15의 필요한 CPU 단일 tool0 수학·Pool·source 선택·trajectory·offset/RNG 부분만 이관. 실행기/구형 Dataset Reader·IK 없음 |

`ScenePackage + 명시 엔진 설정 → 구체 EnvCfg 또는 MjModel/bindings → 공식 Step·state/sample` 흐름이다. 엔진 공통 Adapter/Manager·새 Dataset/Recipe 포맷을 만들지 않았다. E05는 caller가 전달한 수치 snapshot과 Native C의 공식 EpisodeData를 소비한다. 선택 결과/계획 생성은 Task 성공이나 완료 Episode를 뜻하지 않는다.

이번 concrete 설정은 Isaac의 명시 Mapping, MuJoCo의 ModelConfig다. Recipe의 PreparedRun을 실행 가능한 엔진 설정으로 해석하는 연결은 E03/E04에서 구현한다. 현재 Recipe/run worker가 이 엔진을 호출한다고 주장하지 않는다. 해당 경계의 오류 직렬화·장치/Writer 수명도 후속 범위다.

## 같은 Scene Revision과 보정·자산

두 엔진은 [prepare_scene.py](evidence/simulation-engine/prepare_scene.py)가 **완료된 BU03 API로 신규 Export한 동일 Revision**을 사용했다. BU 때의 임시 probe package는 이미 제거됐으므로 그 파일을 존재한다고 가정하지 않았다. 기존 Export·원본은 변경하지 않았다.

- scene_id: scene2-final-contact-review-20261014-932c8f2e, revision: scene.
- Manifest SHA: `a744733b80f07bc8406e13b2f1945478cb08d88253427dad1d665cba864782c6`, 등록 파일 74개.
- 실행 보정 URDF SHA: `f78814de0d341a4a46b2d37759e9206be7d66bca8445ea6867058c43dd6cd589`. historical/source/execution 모델 identity를 분리한다.
- v8 profile/task/physics와 기존 순수 compile_physics 결과를 패키지에 hash로 고정했다. [runtime-inputs.json](evidence/simulation-engine/runtime-inputs.json)은 시험의 명시 설정/참조이며 새 제품 저장 형식·Recipe DSL이 아니다.

S02 baked residual의 명시 실행 URDF를 선택한다. runtime q에 residual을 다시 더하지 않고 active pointer/원본 repo fallback을 사용하지 않는다. reference robot snapshot은 물리 robot 대신 쓰지 않는다. MuJoCo에서는 해당 visual을 실제 link에 연결하고 기존 robot visual과 중복되지 않게 한다. Isaac에서는 static snapshot robot과 동적 물체·mounted fixtures를 제외한 layer를 만들고, 동적 articulation·물체/fixture를 따로 공식 API로 배치한다. 공식 URDF 변환의 파생 USD/cache는 새 실행 공간에만 기록한다.

MuJoCo는 package 안 Finger Convex Parts/source hash와 contact pad JSON을 검사해 실제 robot link의 mesh part/box collider로 생성한다. Isaac도 importer의 finger collider를 비활성화하고 동일 payload의 288개 convex mesh·2개 pad를 공식 USD Physics collider로 적용했다. 실제 source material(마찰1/1·반발0)도 원본 근거와 대조했다. 새 충돌 topology가 역사 USD의 cooking과 수치적으로 동일하다고 가정하지 않는다.

## 실제 엔진 실행 증거

### Isaac Sim5.1 / Isaac Lab2.3.0

[최종 실제 실행](evidence/simulation-engine/isaac/runs/sixth-full-phase/result.json)과 [B01 대조](evidence/simulation-engine/isaac/phase-baseline-comparison.json):

- 공식 ManagerBasedEnv가 실제 6관절 articulation·actuator·동적 물체를 생성하고, Source 24 control step 및 Annotation 388 control step을 실행했다. physics `1/240s × 8`, control30Hz다.
- reference robot 중복 없음, 실제 gripper/jaw와 tool0 binding, 288 Finger convex+2 contact pad collider를 확인했다. 양측 ContactSensor의 실제 힘이 측정됐고 threshold `>1e-4N`을 변경하지 않았다. 최대 힘은 약16.805N/17.803N이다.
- 640×480 RGB uint8 양 camera를 실제 렌더했다. wrist의 **현재 PhysX 부모 pose × optical mount**와 Camera 결과의 행렬 차이는 최대 `1.09e-7`이다. authored USD 정적 pose로 대체하지 않았다.
- 초기 q는 B01 Source와 exact, Source pre-step joint 차이 최대 `9.31e-10rad`다. 실제 root/joint/물체 pose·velocity 복원에서 joint/object는 exact, robot root pose 차이는 최대 `2.38e-7`이다. PhysX solver 내부의 임의 중간 tick checkpoint/bitwise replay를 보장한 것은 아니다.
- 기록된 세 블록/양 컵의 초기 상태와 명령을 그대로 재생했다. 새 StableGrasp 최초 post tick **221**, 기존 저장 first frame **222**, **전체 pre-step latch 배열 exact**다. 접촉 순간과 latch/저장 frame을 같은 시점으로 해석하지 않았다.

**수치 동등성 OPEN:** 같은 phase의 `post(t) ↔ stored pre(t+1)` 비교에서 관절 최대 `0.0113302rad`, 물체 위치 최대 `0.00241692m` 차이가 남는다. 접촉 전 관절 최대 `0.000168167rad`, 물체 위치 `5.22e-7m`다. 현재 importer/convex topology·historical USD·solver/cache/float 차이의 기여를 전부 분리하지 못했으며 이를 **승인된 정책 변경이나 이미 입증된 비결정성으로 분류하지 않는다**. AC01의 전체 numeric trace gate는 통과로 표시하지 않는다. 실제 RGB가 존재하지만 pixel 동일성/카메라 시간 동등성 전체도 미검증이다.

실패 기록도 보존했다. first는 partial callable의 config 직렬화 실패, third는 한 grasp frame을 teleport 복원한 뒤 양측 힘이 동시에 나오지 않았다. fourth는 rad→USD degree→float32 끝값의 1ULP 차이를 새 guard가 거부했다. 허용 오차나 clipping을 추가하지 않고 **고정된 URDF의 rad 한계**로 명령 preflight를 수정했다. fifth/sixth의 전체 물리 재생에서는 실제 양측 접촉이 확인됐다. 단일 frame의 실패를 가짜 force나 조건 완화로 바꾸지 않았다.

Isaac 로그에는 공식 URDF 변환의 massless tool0 visual 참조, Fabric visual path, RTX/DLSS·종료 관련 warning이 남아 있다. 없다고 보고하지 않는다. Step/센서/복원 증거와 구분하며 전체 visual/pixel 회귀는 후속 검증이 필요하다. 실패한 fourth의 app 종료가 남아 있어 해당 **자체 시험 child만** 종료했고, 최종 실행 child는 정상 종료했다.

### MuJoCo3.3.7

[실제 실행](evidence/simulation-engine/mujoco/actual-engine.json), [phase 대조](evidence/simulation-engine/mujoco/phase-baseline.json):

- 6joint/6position servo, calibrated URDF·실제 mesh/convex part·pad·object free joint·live wrist camera. physics `1/300s × 10`, control30Hz를 보존한다. 모델을 parser로 열기만 한 시험이 아니다.
- 공식 mj_step/mj_forward로 실제 움직임·물리 contact를 확인했다. intersection contact fixture는 엔진 contact manifold/힘 검사용이며 정상 Reset·성공 grasp라고 주장하지 않는다. 실제 B01 Annotation 재생에도 bilateral contact가 발생했다.
- `mjSTATE_INTEGRATION`의 ctrl/act/warmstart 등 공식 state를 model/Scene/version에 결합한다. 같은 snapshot 복원 후 반복 실행과 **package 이동 후 snapshot 복원/재실행이 exact**다. 모델 SHA에서 로컬 절대 root를 identity로 사용하지 않는다.
- 잘못된 모델/version/Scene·finite/shape·고정 base/target 변경을 효과 전에 거부하고, 관통 `<-1e-6m` 배치 실패는 원래 state로 rollback한다. 배치 sampler/RNG·재시도 예산은 추가하지 않는다.
- B01 Source24 frame 관절 차이 최대 `2.22e-16rad`, Annotation388 frame 최대 `3.48e-14rad`. 저장 float32 EEF matrix 비교 약`2.98e-8`, 물체 위치 약`1.49e-8m`를 그대로 보고한다. dtype가 다른 저장값을 exact라고 이름만 바꾸지 않았다.
- StableGrasp 최초 **post222 → 저장 frame223**, pre-step latch 전체 exact다. Source recording_only/기본 Evaluation Placement 종료 의미를 변경하지 않았다.
- 실제 side/wrist RGB160×120 uint8과 현재 optical pose를 확인했다. 이는 B01의 전체 640×480 영상/픽셀 동등성 시험은 아니다.

## E05 Mimic 계산

[공식/기존 source identity](evidence/simulation-engine/mimic/source-identity.json), [실제 B01 계획](evidence/simulation-engine/mimic/baseline-comparison.json):

공식 설치 Mimic1.0.15와 기존 이식본의 34개 필요한 symbol 연산을 대조하고 라이선스·NOTICE·UPSTREAM를 패키지에 포함했다. official math/DatagenInfo/Pool/Waypoint/selection 계산을 직접 사용 가능한 pure subset으로 보존했다. eager simulator import/전체 DataGenerator 실행기·구형 Dataset Reader·config framework는 이관하지 않았다.

B01 MuJoCo DataGen A/B 각각 seed **892243098**, source_index0, 원래 pool 순서, 경계 `[0,225)/[225,388)`, 길이 **231+168** pre-IK waypoint의 pose/gripper/noise 배열이 dtype/shape/값 exact다. Auto Annotation 저장 frame223/222의 half-open 끝224/223과 manual203→204를 유지한다. Pool 끝+1을 physical grasp tick으로 오해하지 않는다.

명시 순서의 Source Episode/official EpisodeData를 읽고 단일 tool0 CPU 계산만 지원한다. RandomStream은 기존 NumPy/Torch CPU stream·draw 순서를 보존하고 외부 RNG를 복원한다. GPU RNG·SkillGen·다중 arm·동시 generation execution은 지원/검증했다고 주장하지 않는다. **IK는 없음**: 이전 SciPy·Strict/Hold·solver 선택을 복원하지 않았다. DLS+Best Effort와 실제 attempt budget/성공 채택·Native Writer 연결은 E06이다.

## 테스트·빌드·보존·리뷰

- **전체743 passed, skipped0** = 이전692 + 신규51. [JUnit](evidence/simulation-engine/unit-tests.xml), [실행 로그](evidence/simulation-engine/logs/05-final-suite.log). 실제 Isaac 별도 app 실행은 이 숫자와 구분한다. torchvision 기존 deprecation warning2개가 있다.
- Workbench0.4.0 wheel의 source bytes·compile·reference 라이선스와 isolated import/실제 미구현 runner의 STAGE_UNAVAILABLE 경로를 확인했다. [build.json](evidence/simulation-engine/build.json). 기존 환경에 설치하지 않았다. optional simulation 의존성만 명시했고 고정 SDK를 업그레이드하지 않았다.
- [보존 대조](evidence/simulation-engine/preservation-after.json): 기존56100개 stat·선택15991개 SHA 변화0. 기존 Workbench pyproject의 의도된 버전/optional dependency/package-data 변경만 별도 허용했다. Native C·Scene·Task·Recipe·RO·Builder 제품/기존시험·모든 선행 증거는 변경하지 않았다. 새 시험용 Scene의 Manifest/전체 파일 bytes도 작업 후 대조했다. 전체 corpus/SDK binary 전수 hash 증명은 아니다.
- [리뷰](evidence/simulation-engine/review.md): Standards/Spec 두 독립 agent는 서비스 usage limit으로 종료됐다. 주 에이전트의 두 축 점검·명령 경계 수정은 기록했으나 **독립 리뷰는 미완료**다. [단순화](evidence/simulation-engine/simplification.json)는 새 MuJoCo state의 unused local 제거만 수행했다. 실제 Skill 문서를 읽었고 Git 전용 절차를 수행했다고 주장하지 않는다.
- 명령·SDK source/input/product identity와 한계는 [commands.json](evidence/simulation-engine/commands.json), [verification.json](evidence/simulation-engine/verification.json)에 있다. source-driven은 설치 소스와 [공식 Lab2.3 Env](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html), [asset state](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.assets.html), [MuJoCo state API](https://mujoco.readthedocs.io/en/3.3.7/APIreference/APIfunctions.html#mj-getstate), [Mimic](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab_mimic/isaaclab_mimic.datagen.html)를 사용했다.

## 후속 연결 준비와 남은 관문

E02는 E03/E04의 MuJoCo Source/Annotation 연결에 필요한 model/state/sample/control 경계가 준비됐다. E05는 E06에 수치 계획을 전달할 수 있다. E01도 실제 실행 기반은 있으나 전체 B01 궤적/접촉·pixel/센서 시점 차이를 관련 Isaac Workflow 이전에 추적해야 한다. **E01 전체 numeric preservation 및 독립 코드 리뷰는 미완료**로 남긴다. multi-env 부분 restore·여러 Scene/로봇·장시간 solver 안정성·강제 종료 리소스·headless 종료 모든 예외도 추가 검증이 필요하다.

B01 Isaac DataGen Strict 실패·Evaluation 비결정성, B02 과거 누락/Resume identity·pre/post 기록, B03 실물/검증 상태, v8 UNVALIDATED는 그대로다. 해당 B01 결과를 새 정책 성공으로 바꾸지 않았다. 이번 실제 시뮬레이션 결과는 실물 정합/안전성을 증명하지 않는다. ASSET-FINGER-01은 실제 collider 적용/물리 접촉 근거를 확보했지만 historical Isaac contact topology의 전체 동등성 부분은 OPEN이다.

## 내가 직접 확인할 것

1. E01 최종 result의 실제 forces·restore와 phase-baseline의 numeric OPEN을 함께 확인한다.
2. MuJoCo snapshot/restore_episode·Isaac apply_joint_targets/restore_episode·Mimic plan_subtask의 입력/출력과 단위를 살펴본다.
3. E03/E04/E06은 아직 시작하지 않았다. 다음 작업을 정할 때 Isaac 미확정 수치와 독립 리뷰를 먼저 구분해 검토한다.
