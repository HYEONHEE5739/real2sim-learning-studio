# MuJoCo E03/E04 · E06-a — Source·Annotation·고정 IK

2026-10-27. **MuJoCo의 기본 Source/Manual·Auto Annotation 실행과 E06-a 공통 IK 계산을 구현·검증했다.** 실제 MuJoCo 3.3.7 Step/640×480 렌더·Native publish·공식 Mimic Pool을 사용했다. 실물 입력 장치는 연결하지 않았고, Isaac E03/E04·E06 엔진별 DataGen·L 작업은 시작하지 않았다. E01 cube–cup 충돌 이후 최대 성분 **1.197188790mm/tick310 Y 잔차는 OPEN**이다.

## 구현 범위와 실행 경계

| 작업 | 제품 파일 | 구현 |
|---|---|---|
| E03-MuJoCo | [source.py](../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/source.py) | RO Leader의 명시적 SDK 구성/보정 SHA 재검사, E02 모델·Step·Reset, T03/T04 명시 배치, pre-step 수치/RGB, 실제 initial 및 opaque snapshot, recording_only, save/discard/cancel/pause/step, Native C 완료 publish·새 출력 Resume |
| E04-MuJoCo | [annotation.py](../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/annotation.py) | 원래 Source initial 복원·명령 재생, T02 post-step tracker/최종 acceptance, 자동/수동 boundary, 완료 Episode만 publish, Source lineage·초기 상태 소유권, 취소/skip/물리 실패 |
| E06-a | [mimic.py](../robot_learning_workbench/src/robot_learning_workbench/generation/mimic.py) | 기존 Pinocchio DLS/FK 수식, `bind_kinematics`, `solve_dls`, `best_effort_candidate`, `IKResult`·`IKFailure`. 고정 Best Effort, 측정 seed와 직전 실제 적용 target의 역할 분리 |
| 기존 실행 연결 | [recipe.py](../robot_learning_workbench/src/robot_learning_workbench/recipe.py), [run.py](../robot_learning_workbench/src/robot_learning_workbench/run.py) | 구체 엔진 입력·Source 시간 설정·새 출력 Resume, 관련 실행 소스 identity 고정, Source save/discard와 stage 거부 ACK. 기존 worker 배타 claim·명령 중복 방지 재사용 |
| 시험/패키징 | [workflow 시험](../robot_learning_workbench/tests/test_mujoco_workflows.py), [IK 시험](../robot_learning_workbench/tests/test_datagen_ik.py), [pyproject](../robot_learning_workbench/pyproject.toml) | 신규 경계/실제 엔진 회귀. simulation optional에 설치된 `pin==2.7.0` 명시. 기존 환경에는 설치하지 않음 |

새 Manager·Adapter·통합 engine framework·Dataset 형식은 없다. 공식 `MjModel/MjData/mj_step/mj_forward/Renderer`, 공식 CPU `EpisodeData/HDF5DatasetFileHandler`, 완료된 Native C의 segment/attempt/Resume·AsyncVideoWriter를 직접 사용한다. Builder/Scene2의 좌표·물성·보정·Finger Convex 파일과 Scene Revision은 수정하지 않았다.

### Recipe·장치·명령

MuJoCo Source의 `inputs.engine_config`는 기존 **E02 ModelConfig 필드 그대로인 JSON**이다. `initial_joint_rad`, 순서가 있는 `active_object_ids`, `object_physics` 등을 명시한다. 새 설정 언어나 v8 원본 fallback이 아니다. 준비 시 파일 bytes를 고정하고 실행 시 단일 env·640×480·30Hz·선택 물체 순서를 확인한다. 실제 시험은 기존 패키지의 compiled physics를 읽었다. 다른 dt/물성을 동일 Baseline이라고 재해석하지 않는다.

`inputs.device_profile`은 `{calibration_id, calibration_path, sdk}`다. calibration_id는 Scene의 Leader/device_observation Encoder record, calibration_path는 명시된 SDK calibration 파일 절대 경로, sdk는 공식 SO101LeaderConfig 필드다. degree-native 설정과 실제 연결 후 mapping SHA를 재검사한다. 모델/센서/Resume 검사 후 연결·활성화하고 모든 종료 경로에서 RO close를 호출한다. Source는 Follower를 구동하지 않는다. 이 실제 장치 분기는 **미실행**이며 RO 모의 검증을 실물 안전성으로 승격하지 않는다.

Source `execution`에는 기존 episodes/seed와 명시적인 `episode_time_s`, `reset_time_s`를 받는다. 원래 wall-clock 수집 창과 control30Hz sleep을 유지하며, 기록된 명령 fixture는 명시 프레임 수로 실행한다. 영상 FPS는 시뮬레이션/인코딩 clock 계약이다. 현재 장비에서 실물 입력을 포함한 wall-clock 30Hz 지속 성능을 입증한 것은 아니다. pause 동안은 새 제어/기록을 멈추고 시간 창을 보류한다.

Source save는 현재까지의 비어 있지 않은 Episode만 저장하고, 빈 save/discard/cancel은 완료 Episode를 만들지 않는다. discard도 attempt를 소비하고 원래 reset cooldown을 거친다. step ACK는 실제 요청 횟수만큼 physics가 끝난 뒤 반환한다. 이미 닫힌 Episode의 cooldown에서는 cancel만 처리하며 다른 명령은 거부한다. 기존 request/worker claim 및 동일 command ID의 ACK 재사용은 R03을 그대로 사용한다.

선택적 Source signal/metric 실행 및 Annotation의 별도 metric 선언은 현재 **명시 오류로 거부**한다. 지원하지 않는 선언을 조용히 무시하지 않는다. 기본 v8 Source와 T02의 Annotation acceptance-only→grasp provider 계약을 검증했다. 임의 Task/여러 tracker 물체·다중 env의 전체 실행 지원을 완료했다고 주장하지 않는다.

## 수치·시점·초기 상태

Source는 측정 관절값과 requested model rad를 보존하고, URDF와 canonical gripper 0..100°의 교집합으로 target만 제한한다. collection state/action은 원래 팔 rad·gripper fraction float32, requested/target은 float64다. EEF/object/target matrix는 기존 float32 저장 경계를 유지한다. Action은 첫 measured EEF 이후 직전 **target EEF** 기준 translation/rotvec delta + 절대 gripper rad다. 새로운 post-step 관측으로 pre-step 행을 덮어쓰지 않는다.

Annotation은 Source의 정확한 opaque snapshot이 있으면 해당 engine/model/Scene/version 검증 후 사용하고, 과거 자료의 canonical initial만 있을 때는 그 기록을 복원한다. **Annotation 출력의 재측정 initial을 원 Source initial의 대체물로 사용하지 않는다.** `source_initial_snapshot`, `replay_initial_snapshot`, `initial_state_owner`, 원 Source dataset/Episode/key lineage를 구분한다. seed도 원래 공식 Episode에서 승계한다. 기록 unit/frame/joint_order/phase/camera 계약이 없거나 다르면 추측하지 않고 차단한다. 명시적 과거 HDF5 import/mapping 없이 과거 파일을 현재 실행 기록으로 승격하지 않는다.

Auto는 pre-step 이전 latch 저장→실제 Step→post-step tracker 한 번→최종 Placement AND latched StableGrasp다. Manual은 실제 물리 통과 후 interior grasp frame 하나가 있어야 채택하며, 사용자 boundary를 물리 최초 tick으로 바꾸지 않는다. 최종 post-step Placement는 기존처럼 마지막 action 행에 표시할 수 있다. Source의 recording_only, Evaluation의 Placement 종료 조건은 바꾸지 않았다.

## 실제 실행 증거

| 검증 | 결과 / 증거 |
|---|---|
| B01 Source 24 frame의 실제 신규 수집→Native 재로드 | [source-baseline.json](evidence/mujoco-workflows/source-baseline.json). target/requested/timestamp, float32 EEF/target/object 및 collection state/action exact. measured q 최대 **2.220446049250313e-16rad**, Action 최대 **1.0255549565291684e-15**. dtype/shape 동일. Action 열은 m/rad/gripper가 혼합되어 하나의 물리 단위 최대값으로 해석하지 않음 |
| 원래 Source initial/명령 388 frame→신규 Source→자동/수동 실제 Annotation | [final-actual-results.json](evidence/mujoco-workflows/final-actual-results.json). 신규 Source와 Annotation q 전체 **exact**. B01 Annotation q와 각각 최대 **5.082686355128985e-10rad**. 원 Source initial과 과거 Annotation 재저장 initial의 차이를 지우지 않음 |
| 자동/수동 시점 | 자동 최초 post **222**, 저장 first **223**, B01 grasp 배열 전체 exact. 수동 first **203**, 최종 물리 gate 통과. 새 입력에 맞춰 threshold/tolerance를 늘리지 않음 |
| 설치된 공식 Mimic Pool | [official-consumer.json](evidence/mujoco-workflows/official-consumer.json). 공식 Reader/Pool이 실제 새 Annotation을 읽음. auto `[0,224)/[224,388)`, manual `[0,204)/[204,388)`. Pool half-open 끝+1을 물리 tick으로 해석하지 않음 |
| 영상 | 자동/수동 각 양 camera 388 frame, 640×480, 30FPS, 모든 MP4 PTS의 `arange(T)/30` 차이 **0s**. 새 엔진 렌더의 RGB 입력이며 과거 MP4와 pixel exact라는 주장이 아님. Native publish는 완성된 같은 영상 파일을 공유하며 재인코딩하지 않음 |
| 실제 production worker | [worker-results.json](evidence/mujoco-workflows/worker-results.json). Recipe→R03 실제 worker→MuJoCo Manual Annotation→Native 완료 1개. `_runner` 주입 없음. 중복 start 같은 Handle, 중복 mark203 같은 완료 ACK, 정상 terminal |
| 실제 Source runner·Resume | 새 시험의 fake **Leader 입력만** 사용하고 모델/Step/Renderer/Writer는 실제. 새 출력에 cumulative 1→2, attempt seed7→8, 원본 Native identity 불변, 취소 완료0개·close 호출. 실물 Encoder/버스 시험과 구분 |
| 실제 collector 강제 종료 | [crash-results.json](evidence/mujoco-workflows/crash-results.json). 자체 시험 child만 SIGKILL. 첫 2frame Episode는 공식 Reader로 재개방, 다음 실제 Step 중 끊긴 Episode 노출0. 불명 claim의 자동 Resume는 `NATIVE_STATE_UNKNOWN`, 새 출력 생성0 |

공식 Pool은 설치된 수정 없는 child module을 namespace 경로로 읽어 eager simulator import를 피했다. gripper action callback은 배열 계약 fixture다. 이것을 Isaac Environment/Mimic 전체 DataGenerator 실행 완료라고 확대하지 않는다. 영상 검증 도구의 NativeEpisode 속성명 오류는 별도 소비자 script에서 수정하여 **이미 완료된 실제 실행을 반복하지 않고** 검증했다. 초기 실패 로그도 보존했다.

## E06-a 수치·안전 경계

기존 DLS의 float64·Jacobian·`pin.log3`·곱/반복 순서를 유지한다. 파라미터는 position1/orientation.01/iterations200/tolerance1e-3/damping1e-3/step.3이다. damping을 제곱하거나 measured seed를 previous target으로 바꾸지 않았다. mutable Pinocchio Data는 바인딩 인스턴스별 소유다.

candidate의 shape/finite, model limit±1e-7, 직전 **실제 적용** arm target과 `max(abs(delta)) > .5rad`를 검사한다. 정확히 .5는 통과한다. 유효하지만 미수렴/pose 진단 기준 초과인 candidate도 Best Effort 명령 후보로 반환한다. 부적합 candidate는 `IKFailure(code=IK_INVALID_CANDIDATE,effect=not_applied)`이며 Hold/clipping/fallback으로 대체하지 않는다. 진단은 finite JSON으로 남고 command_applied=false다. 이 공통 함수는 명령을 적용하거나 previous target을 갱신하지 않는다.

[ik-comparison.json](evidence/mujoco-workflows/ik-comparison.json): 실제 B01 DataGen의 8 target/measured/previous fixture를 읽어 **기존 Pinocchio DLS candidate·native 진단·Best Effort 명령 exact**를 확인했다. B01의 원래 SciPy+Strict 실행을 신규 DLS 실행 결과로 바꾸지 않았다. 추가 실제 DLS unreachable target의 유효 미수렴과 0.5 경계·limit epsilon·invalid candidate·model/frame/unit/order·정책/code/seed identity가 다른 Native continuation 거부를 검증했다. Native 실행의 model SHA와 IK의 URDF SHA는 각자의 identity이며 혼합하지 않는다.

**E06-b/c의 실제 DataGen 실행·이전 target 수명·attempt 채택·StableGrasp/Placement 성공률 검증은 미착수**다. Source·Annotation 성공을 DLS DataGen 성공으로 보고하지 않는다. SciPy IK/Strict/Hold·solver 선택 UI/Recipe는 추가하지 않았다. SciPy Rotation은 기존 좌표 변환 계산에만 사용한다.

## 검증·리뷰·보존과 남은 항목

**전체 778 passed, skipped 0**, 기존 torchvision warning 2개. [JUnit](evidence/mujoco-workflows/unit-tests.xml), [최종 suite 로그](evidence/mujoco-workflows/logs/44-final-suite.log), [wheel](evidence/mujoco-workflows/build-workbench.json), [commands](evidence/mujoco-workflows/commands.json), [최종 확인](evidence/mujoco-workflows/verification.json)에 실제 결과를 기록한다. 별도 lint/type 도구는 설치·설정되어 있지 않아 실행했다고 주장하지 않는다. 기존 torchvision deprecation warning은 남아 있다.

[리뷰](evidence/mujoco-workflows/review.md): code-review 스킬의 두 독립 agent는 서비스 usage limit으로 종료됐다. 주 에이전트는 Standards/Spec 두 축을 점검하여 잘못된 cooldown ACK·discard cooldown 누락·수집 시간창·nonnumeric IK 진단 오류를 수정하고 재검증했다. **독립 리뷰는 OPEN**이다. unused import 제거와 attempt/final status의 반복 trace 축소만 단순화했고 기존 수치 식은 바꾸지 않았다. Git 저장소가 없어 Git 전용 diff/commit을 수행했다고 보고하지 않는다.

[보존 대조](evidence/mujoco-workflows/preservation-after.json)는 기존 폴더 stat와 선택 SHA·선행 보고서/증거·SDK source·Scene package를 확인한다. 전체 대용량 corpus/SDK binary 전수 byte 검증은 아니다. 변경은 새 Workbench의 명시 허용 파일·신규 runner/시험·이번 증거/문서뿐이다.

기존 대비 의도된 실행 경계는 이미 확정된 Native C의 불변 segment publish/새 출력 Resume·명시 attempt history와 Recipe/IPC다. discard를 추적하지 못한 과거 Source Resume를 정확한 RNG continuation이라고 승격하지 않는다. 신규 실행은 기록한 attempt 순서로 이어가며 partition/identity/불명 상태를 검사한다. Solver 정책 변경은 기존 승인된 DLS+Best Effort 단일 방식이다.

남은 실제 검증은 Leader 실물 연결·토크/해제·USB/timeout·실시간 수집, 다양한 Scene/여러 물체·다중 env/사용자 Task의 전체 실행, 별도 signal/metric 실행, Isaac Workflow, E06 엔진별 연결 및 전체 장시간 부하다. B02 과거 누락/Resume 제한, B03 실물 미검증·v8 UNVALIDATED, E01 물체 잔차는 유지한다. **이번 묶음까지만 수행하고 다음 작업은 자동 시작하지 않는다.**
