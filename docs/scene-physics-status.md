# scene-v9-auto-fit Collision·PhysX 확인

2026-11-01. **Real/Sim에서 충돌체가 있어도 관통하던 실행 경로를 수정했다.** Package의 컵·블록 Collision은 활성 상태였지만, Real/Sim이 q를 직접 지정하고 Physics Step을 생략해 물리 반응이 실행되지 않았다. 사용자 요구에 따라 interactive Real/Sim을 Source와 같은 목표 관절 제어·물리 Step 경로로 교체했다. 기존 Scene Package/물성을 중복 수정하지 않았고 실물 장치는 연결하지 않았다.

## 현재 포함된 물리 설정

| 대상 | Package 충돌체 | Isaac 실행 상태 |
|---|---:|---|
| 책상 | Box 1개 | 고정 충돌체 |
| 종이 | Box 1개 | 얇은 고정 충돌체 |
| 빨강·파랑·초록 블록 | 각각 Box 1개 | 각각 동적 RigidBody, 중력 적용, 추정 질량 20g |
| 컵 A/B | 각각 129개 | 바닥 1개 + 높이별 벽 128개, 열린 상단, Kinematic RigidBody |

컵은 기존 Pick/Place에서 고정된 작업 대상으로 사용하므로, 블록과 충돌하지만 컵 자체는 밀리거나 쓰러지지 않는다. 질량이 알려지지 않은 컵에 임의 질량을 추가해 동적 물체로 바꾸지 않았다. 컵을 밀거나 넘어뜨리는 기능은 현재 고정 Target 계약과 다른 작업이다.

현재 원본 Scene의 추정 마찰 계수는 블록 1.4, 컵/책상 1.0이고 반발 계수는 0이다. 실측 재료 특성이라는 뜻은 아니다. 손가락/로봇의 실행 Collision은 기존 native Robot USD 및 명시 Collision binding을 사용한다. authoring의 정적 참고 로봇 Mesh와 실제 Articulation은 구분한다.

소스는 Builder `exporters/usd.py`의 `PhysicsCollisionAPI`/`PhysicsRigidBodyAPI` 및 Workbench `engines/isaac/env_cfg.py`의 `write_scene_assets()`/`build_env_cfg()`다. API가 이름에 `Physx`를 포함하지 않아도 USD Physics Collision/RigidBody 스키마는 시뮬레이터가 소비하는 물리 속성이다. [CollisionAPI](https://openusd.org/release/api/class_usd_physics_collision_a_p_i.html), [RigidBodyAPI](https://openusd.org/release/api/class_usd_physics_rigid_body_a_p_i.html)와 설치된 실행 결과를 대조했다.

## 실제 실행 확인

선택된 `scene-v9-auto-fit`의 닫힌 Package를 production `SceneView` → `NativeRenderer` → `ManagerBasedEnv`로 열었다. 원본 SDK/자산을 변경하지 않고 별도 Workspace 런타임 레이어를 생성했다.

- Physics dt는 1/240초다. 3개 블록을 각각 원 위치보다 30mm 높이로 옮기고 480 Step(2초) 진행했다. 모두 원 지지 높이에 안착했다. 기록상 원 중심 위치와의 차이는 최대 약 `8.33e-9m`지만 이는 작은 합성 정착 probe의 수치이며 실제 Calibration 정밀도가 아니다.
- 블록을 각 컵 왼쪽 65mm 위치에서 수평 0.4m/s로 이동시키고 컵마다 120 Step(0.5초) 진행했다. Cup A/B에서 최대 전진한 중심 위치는 컵 중심 기준 각각 약 −43.561/−43.562mm였다. 벽을 통과하지 않고 반응했으며 컵의 위치 변화는 0이었다.
- 전체 720 Step을 실제 PhysX로 진행했다. 첫 probe는 결과/판정 저장 후 Isaac 종료 과정에서 exit 139가 발생했다. Tensor/Stage 참조를 함수 수명 안에서 먼저 해제한 별도 재검사는 같은 720 Step을 완료하고 exit 0으로 종료했다. SDK 설치 파일은 변경하지 않았다. 런타임에서도 블록 각 1개·컵 각 129개 충돌체가 활성 상태였다.

이는 **블록–지지면 정착과 블록–컵 외벽 충돌** 확인이다. 컵 내부 낙하/모든 방향·속도·모든 자세, 로봇 grasp/Task 성공, 실물 접촉/마찰 정확도까지 새로 검증한 것은 아니다. 기존 렌더/SDK 경고는 로그에 보존했다.

## Real/Sim 실행 경로 수정

기존 `NativeRenderer.render()`는 MuJoCo `qpos` 또는 Isaac `write_joint_state_to_sim()`으로 매번 관절 상태를 직접 지정하고 forward/render만 수행했다. `physics_steps=0`이었으므로 활성 Collider가 있어도 충돌 반응을 계산하지 않았다. 사용자 확인에 따라 이 동작을 live Real/Sim에서 제거했다.

현재 `create_renderer()`의 native 실행 경로는 다음과 같다.

- **MuJoCo:** 기존 `engines.mujoco.control.step()`을 사용한다. 목표값 검사를 거쳐 position servo target을 설정하고 정해진 substep만큼 `mj_step()`을 진행한다. 매 tick 관절 상태를 덮어쓰지 않는다.
- **Isaac:** Source/DataGen의 기존 `mdp.apply_joint_targets()` → 공식 `env.step()`을 사용한다. 목표값/유한 상태 검사·기존 PD/force limit·dt/decimation·Collider를 공유한다.
- **자식 Worker:** 최신 Real q는 Sim 목표값이다. 새 preview 요청이 없는 동안에도 마지막 목표로 물리를 진행한다. 한 프로세스가 엔진과 렌더를 소유하며 실물 Serial 제어는 기존 별도 루프에 남는다. render가 제어 간격보다 느린 부하에서는 wall-clock realtime을 보장하지 않으며 실제 simulation time/step을 기록한다.
- **표시/Pair:** Real 측정값, 검사 후 Sim target, 실제 Sim q, 추종 차이, simulation time/physics step, 움직인 물체들의 world pose를 구분한다. Pair의 기존 `applied_sim_joint_rad`/`sim_q_measured_rad`는 실제 Sim 상태이며 Real q와 같다고 강제하지 않는다. Builder 재개방에도 이 Metadata를 보존한다. 정지 관측의 실물 `q_command=null`은 유지하며 새 학습 Action을 만들지 않는다.

UI에는 `Follower 측정값`과 `Sim 관절값 · 최대 추종 차이`를 따로 표시한다. 충돌/중력/관성 때문에 실제 Follower q와 Sim q가 달라질 수 있다. 충돌을 숨기려고 Sim 상태를 다시 Real q로 맞추지 않는다. 실물 Teleoperation의 승인·정지·토크 정책은 변경하지 않았다.

Source/Annotation/DataGen/Sim Evaluation의 기존 물리 Step 경로를 계속 사용한다. Source의 frame 기반 수집 시간/저장 계약도 변경하지 않았다. 별도의 범용 Physics Manager/새 Dataset 포맷은 없다.

## 정합용 저장 자세 렌더와 물리 실행

Scene 제작/Fitting에 필요한 measured-q 투영은 `pose_render.PoseRenderer`/`create_pose_renderer()`라는 명시적인 **오프라인 계산 진입점**으로 분리했다. Builder의 기존 관측 FK 렌더도 해당 목적을 유지한다. interactive Worker는 이 진입점을 호출하지 않는다. 물리 Articulation/설정이 없는 authored-only Export를 live Real/Sim에서 정적 렌더로 대체하지 않고, native 물리 자산/설정이 필요하다는 오류를 제공한다.

과거 저장 Pair·비교 이미지의 `physics_steps=0`을 새 물리 실행 성적으로 바꾸지 않는다. 과거 `compare.html`의 정적 영상도 당시 결과이며, 새 Runtime 동작으로 재실행한 결과가 아니다.

## 변경 경로의 실제 확인

- 수정 전 production factory의 gravity/step 시험이 `physics_steps == 0`으로 실패하는 RED를 저장했다. 수정 후 같은 MuJoCo 시험에서 중력 낙하·시간 진행·joint target 응답이 확인됐다.
- MuJoCo production render child에서 preview를 한 번만 요청한 뒤 대기해도 physics step이 계속 누적되는 것을 확인했다. 실제 RealSimSession + 명시 Memory 장치 + Native MuJoCo의 네 이미지 Pair/cleanup을 재검사했다. 이는 실물 모터 실행이 아니다.
- **실제 Isaac production factory → NativeRenderer:** 총 976 physics substep/약 4.067초의 control interval을 실행했다. 3개 블록의 30mm 낙하/안착, 두 컵 외벽 반응, 목표 q와 실제 q의 차이 및 실제 물체 pose Metadata를 확인했다. 컵 벽 충돌 시 중심의 최대 상대 X는 약 −45.042/−45.034mm였다. 이 Worker는 exit 0으로 종료했다.
- **현재 Scene의 Source Demo:** 기존 MuJoCo `collect_episode()`로 simulation 8 frame/약 0.2667초를 실제 수집·Native 저장·Reader 재개방했다. 들어 올린 블록은 지지면으로 내려왔다. recording-only Episode 1개이며 Task 성공 주장이 아니다. Isaac Source는 이번에 별도 Episode 수집을 반복하지 않았고, 동일 `apply_joint_targets()`/`env.step()` 경로를 위 실제 Isaac 실행에서 소비했다.
- UI에서 Real/Sim 수치를 바꿔 표시하지 않는 시험, Sim/Real q가 다른 Pair를 저장/공식 Reader로 재개방하는 시험, 기존 Export/Builder 회귀를 포함해 **관련 136 passed**다.

전체 회귀는 별도로 **1,091 passed / 71 failed / 28 errors**였다. 삭제된 과거 Evidence USD/Checkpoint와 기존 UI/제어 기대 등의 실패가 남는다. 현재 HEAD `7a97b49`의 소스를 별도 작업 사본에서 실행한 기준 회귀는 **1,087 passed / 73 failed / 28 errors**였으며, 현재 실패/오류 99개 항목 모두 기준에서도 재현됐다. 기준 사본에만 있는 2개 Policy 경로 assertion은 사본 경로 alias 차이다. **추가된 실패 항목은 없었지만 전체 green이라고 보고하지 않는다.** 마지막 UI/Pair 시험 추가는 위 관련 136개 실행에서 확인했다. 과거 삭제된 대용량 시험 자산을 복원하거나 제품 검사를 완화해 통과시키지 않았다.

## 사용과 보존

기존 Real/Sim을 중단하고 창을 닫은 뒤 `./run_workbench_ui.sh`로 다시 실행한다. 같은 `pickplace_colorblock / scene-v9-auto-fit`을 선택하면 새 코드의 물리 경로를 사용한다. 새 토글이나 YAML 모드를 켤 필요가 없다. 실행 중 사용자 프로세스를 강제 종료하지 않았다.

Scene Package·원본 Capture·Calibration·Dataset·Checkpoint는 변경하지 않았다. 이 수정에 별도 Scene Revision은 필요하지 않았으며 Runtime 소스/시험/문서를 수정했다. 새로운 설치·학습·실물 연결·Git Commit/Push/Merge는 하지 않았다. 실측 마찰·모든 접촉 조건·전체 Task 성공·장시간 성능/안전성까지 검증한 것은 아니다.

근거는 로컬 `workbench_runs/scene_physics_20261101/`의 `baseline-audit.json`, 초기/정리 후 `physx-*-result`/로그, `interactive-isaac-result.json`, `source-current-scene.json`, RED/GREEN·`related-tests.xml`, `full-tests.xml`, `baseline-full-tests.xml`, `baseline-comparison.json`이다. 공식 API 근거는 [MuJoCo mj_step](https://mujoco.readthedocs.io/en/3.3.7/APIreference/APIfunctions.html#mj-step), [Isaac ManagerBasedEnv](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html)이며 설치된 고정 SDK와 실제 실행을 함께 사용했다.
