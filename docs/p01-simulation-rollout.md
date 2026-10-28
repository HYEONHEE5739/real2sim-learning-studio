# P01 — ACT MuJoCo·Isaac Simulation Policy Rollout

2026-10-27. **단일 env·Fixed Scene의 ACT Rollout·Placement 평가·Native 기록·Episode 경계 Resume를 양 엔진에서 실제 검증했다.** [L01/L02](learning-bundle.md)의 **4-step smoke checkpoint**를 그대로 사용했다. 추가 Training·실물 연결·P02/P03·L04/C/U/X는 수행하지 않았다. 성공 Episode는 0개이며 실행 경로의 정상 동작과 학습 성능을 구분한다.

## 구현과 기존 기능 재사용

| 파일 | 구현·변경 |
|---|---|
| [MuJoCo evaluation.py](../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/evaluation.py) | E02의 실제 MjModel/MjData·Renderer·Step/Reset, L02의 공식 ACT·processor, T02의 post-step 평가, Native publish/실패 attempt를 연결 |
| [Isaac evaluation.py](../robot_learning_workbench/src/robot_learning_workbench/engines/isaac/evaluation.py) | 기존 v8 실행 USD/Collision·ManagerBasedEnv·실제 Camera/ContactSensor·Physics Step/복원을 직접 사용 |
| [learning/policy.py](../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py) | 실제 RGB uint8→공식 Dataset과 같은 float32 `[0,1]` BCHW·측정 state 입력, 원 Action/실제 payload의 strict 검사와 오류 진단 |
| [recipe.py](../robot_learning_workbench/src/robot_learning_workbench/recipe.py) | Evaluation의 명시 engine_config/resume_dataset/외부 policy_contract 입력, 평가 실행 코드 identity 고정 |
| [data/native.py](../robot_learning_workbench/src/robot_learning_workbench/data/native.py) | Evaluation의 완료 실패 Episode도 새 출력 Resume에서 보존·계수. 명시 Policy/평가 계약 identity 필수 |
| [Isaac annotation.py](../robot_learning_workbench/src/robot_learning_workbench/engines/isaac/annotation.py) | 기존 float32 target-local corner 계산에 optional params만 추가. 기존 Annotation 호출/판정은 그대로 |

새 시험은 [test_simulation_evaluation.py](../robot_learning_workbench/tests/test_simulation_evaluation.py) 14개다. 기존 R03의 `simulation_evaluation → engines.<engine>.evaluation.run` 연결을 사용하므로 run.py는 바꾸지 않았다. Native C·Builder·Scene·Task 수식·엔진 물리 구성·학습 파일·SDK는 변경하지 않았다. 새 공통 Env·Policy Framework·Manager·Dataset 포맷은 없다. 공유되는 것은 기존 inference/기록 함수와 작은 평가·오류 함수뿐이며 엔진 loop/수명은 각 엔진 파일이 소유한다.

## 실제 실행 결과

최종 코드 검증은 [MuJoCo 새 run](evidence/p01-rollout/mujoco-verified-results.json)/[새 출력 Resume](evidence/p01-rollout/mujoco-resume-verified-results.json), [Isaac 새 run](evidence/p01-rollout/isaac-verified-results.json)/[새 출력 Resume](evidence/p01-rollout/isaac-resume-verified-results.json)다. `_runner` 주입 없이 실제 R03 worker가 실행했다. Isaac의 시험 bootstrap은 보호 경로/장치 접근 audit와 Kit 로그 경로만 지정하고 엔진·센서·Task·결과를 대체하지 않는다.

| 최종 canonical 결과 | 완료 Episode | 적용 step | Placement 성공 | 최대 step 실패 | 안전 거부 |
|---|---:|---:|---:|---:|---:|
| MuJoCo, 새 run→Resume | 2 | 60+60 | 0 | 2 | 0 |
| Isaac, 새 run→Resume | 2 | 60+60 | 0 | 2 | 0 |

각 run의 timeout_s=2를 **30Hz 기준 최대60 control step**으로 해석한다. wall-clock 2초의 종료 제한은 아니다. 실제 속도는 아래 측정처럼30FPS보다 느리다. 모든 최종 Episode에서 양 손가락 contact bool은 false였고 StableGrasp/Placement 최초 post tick은 없다. Isaac ContactSensor 배열도 실제 값으로 저장했다. 접촉을 만들기 위해 Scene/Action을 조정하거나 force를 채우지 않았다. 이는 실제 센서에서 양성 접촉을 만드는 성공 grasp 시험이 아니며, 엔진 자체 양성 접촉/판정 Baseline은 기존 E/T02 증거에 남는다.

별도 실제 취소는 MuJoCo 3 step, Isaac 4 step 뒤에 적용됐다. 각1 attempt·완료 Episode0개다. 최종 검증만 합치면 엔진별 **2실패+1취소=3 attempt**, 성공0, 성공률0/3이다. 실패·거부·오류·취소를 분모에서 임의 제외하지 않는다. 취소 run은 별도 Native 출력이며 resumed Dataset의2 attempt와 혼합 저장한 것은 아니다.

구현 중 재검증한 모든 실제 실행도 보존했다. **MuJoCo는 총5개 완료 실패 Episode+1취소, Isaac은 총4개 완료 실패 Episode+1취소**다. Resume에 상속된 기존 Episode는 다시 생성한 개수로 중복 계산하지 않았다. 초기 실행(first/release/final)은 구현 단계의 진단 결과이고 위 표는 최종 코드·identity가 고정된 verified/Resume 결과다. 결함 주입 시험의 unsafe/reset 예외는 이 실제 학습 Policy 성적에 포함하지 않는다.

## 입력·Action·Step 정렬

Scene은 이전에 검증한 `scene2-final-contact-review-20261014-932c8f2e / scene-v8-native`, Manifest `64bff80050a883880e7e6363dd3e5b2f517fd72bb96743e3e529c89a2dfaa3c9`다. 실행 kinematic URDF SHA는 `f78814de…`. ACT step4 model SHA는 `98ef706c10d6b888fcf92f5c1f07eebd02aae5bd5831b2aa7ed47d416000640b`다. Physics model identity는 엔진별로 별도 보존한다.

1. 고정 initial 복원·명시 Fixed placement 후 Policy Reset.
2. 명령 이전 실제 measured q와 Side/Wrist RGB640×480을 취득한다. uint8 RGB를 float32 `[B,3,H,W]`/255로 바꾸며 state는 `[B,6]` float32다. pre-step의 q를 post-step 상태로 덮어쓰지 않는다.
3. 공식 preprocessor → ACT select_action → 공식 postprocessor를 사용한다. **정규화된 값을 엔진에 보내지 않는다.** 결과는 JOINTS 순서의 **절대 model rad 6축**이며 gripper도 rad다.
4. 원래 후처리 Action과 적용 dtype payload를 각각 원본 URDF rad 한계로 strict 검사하고 실제 엔진 preflight를 추가로 호출한다. MuJoCo는 float64 payload, Isaac은 float32다.
5. pre-step 기록/영상 → 실제 Physics Step → post-step StableGrasp/Placement·부가 지표를 계산한다. Evaluation 성공 종료는 **Placement만**이다. grasp/transport/full_task_success는 별도 측정값이다.

[저장 소비자 검사](evidence/p01-rollout/consumer-results.json), [공식 Reader·초기 상태](evidence/p01-rollout/reader-resume-results.json):

- 양 엔진 각2 Episode에서 `pre_q[t+1] == post_q[t]` **배열 전체 exact**. 첫 observation은 기록 initial joint_position 및 명시 engine_config initial q와 exact다.
- `joint_targets`는 이 Policy의 후처리 원본 float32다. solver float64 DataGen 필드로 재명명하지 않는다. `commands/applied_joint_rad`는 실제 payload로 MuJoCo float64/Isaac float32다. 원 Action을 해당 dtype으로 바꾼 값과 exact이며 측정 q와 같은 값으로 취급하지 않는다.
- 공식 ACT chunk10의 queue 깊이는 각 Episode에서 **9,8,…,0을6회 반복**했다. 실제 model query6회/queue 소비60회이며 새 Episode의 초기 queue도 Reset됐다. queue 수치는 작은 HDF5 scalar telemetry로만 남겼다.
- episode-relative timestamp는 `arange(60)/30`. 실제 `obs/physics_timestamp[t+1] == states/physics_timestamp[t]`도 exact다. 엔진 clock과 상대 MP4 clock을 같은 원점이라고 가정하지 않는다.
- pre-step grasp는 직전 post-step latch와 exact다. 최종 post Placement 표시가 필요한 경우 기존 마지막 action 표시 규칙을 유지한다. 이번 실제 실행에는 Placement가 없었다.
- 양 엔진 각2 Episode·양 camera의 **240 frame/engine** 전체 MP4 PTS·frame count·640×480·30FPS를 확인했다. 시작/중간/끝 RGB를 실제 decode했고 비어 있는 영상이 아니었다. 실제 입력은 엔진 RGB이며 MP4는 새 Rollout의 원본 수집 encode다. 기존 Dataset MP4를 재인코딩한 것이 아니다. 원래 렌더 RGB와 lossy H.264 decoded RGB의 pixel exact는 주장하지 않는다.

## No Clipping 정책·실패 분류

명령의 원 dtype/shape/6축 순서와 finite, 원값/적용 payload의 모델 limits를 검사한다. 큰 초과·1ULP 초과·float32 변환 초과 모두 거부한다. `ActionRejected`에는 원 Action/dtype/shape, 적용 dtype, joint 이름·limit·초과량·단계(original/payload), command_applied=false가 있다. 입력을 clip하거나 직전 target으로 Hold/fallback하지 않는다.

Isaac의 기존 엔진 preflight는 float32로 변환된 bounds를 비교하므로 **P01이 원래 float64 URDF 한계로 먼저 검사**하고 그 뒤 기존 API도 호출한다. 엔진의 기존 다른 stage 동작을 바꾸지 않고 이 P01 strict 경계를 적용한다. 기존 MuJoCo float32 wrist 문제도 아래 경계 fixture에서 계속 거부한다.

[시험](evidence/p01-rollout/logs/24-provenance-green.log): 원 float64 upper1.7453264625997165rad가 float32 변환 후1.7453265190124512rad가 되면 약5.64127e-8rad 초과로 거부한다. 큰 초과/nextafter/NaN/shape 오류도 거부했다. **통제 결함 주입**으로 두 번째 Policy 출력을100rad로 바꾼 실제 MuJoCo 시험에서는 step 호출1회만 발생하고 거부된 tick1은 적용/기록하지 않았다. 1-frame 완료 실패 Episode와 거부 진단이 남았다. 실제 smoke Policy가100rad를 출력했다는 증거가 아니며 실제 성적의 안전 거부 수는0이다.

기본 종료 category는 placement_success, max_steps, action_safety_rejection, engine_error/camera_error/policy_error/execution_error, cancelled다. observed Reset 오류도 attempt 실패/history에 남긴 뒤 원래 오류 code/issues/effect·traceback을 전파한다. 실제 step 이후 Task/센서 오류는 not_applied라고 추정하지 않는다. 취소/오류로 끝나 기록이 불완전하면 완료 Episode를 publish하지 않는다. 정상 최대 step/안전 거부로 종료돼 이미 적용한 행이 완결된 경우에는 success=false인 완료 Episode를 보존한다. 첫 명령 거부처럼0 frame이면 Episode는 만들지 않고 실패 attempt만 남긴다.

### 기존 v8/B01 대비 차이

기존 `workflow/policy.py:ActionGuard.apply`에는 model clip과 rate/tracking 제한이 있었다. **사용자의 이번 명시적 no-clipping 결정에 따라 이를 이관하지 않았다.** 속도 평활화·target 수정도 없다. 이는 승인된 제어 정책 차이이며 기존 수치 동등성을 주장할 수 없다.

B01 Evaluation은 별도 과거 checkpoint/활성 물체/초기 조건을 사용한다. 따라서 현재4-step ACT의 live 궤적을 B01 q와 같다고 비교하지 않는다. 기존 T02의 StableGrasp 수식/Placement 경계와 판정 phase는 그대로 재사용했으며 [T02 기존 입력 대조](evidence/t02/baseline-comparison.json)와 새 전체 회귀를 적용했다. B01에서 쓰던 grasp_failure 같은 부가 설명을 관찰 근거 없이 이번 종료 원인으로 추정하지 않고 **최대60 step 도달·Placement false**를 그대로 기록한다. contact/grasp/transport 지표는 실제 관측값으로 별도 남는다.

## Native·Resume·취소·오류 수명

Native C의 닫힌 공식 HDF5 segment→검사→publish를 사용한다. 기존 Evaluation failure Episode는 완료/미완료와 별개다. official Reader에서 **success=false·60 frame**으로 열렸고 실패가 성공으로 승격되지 않았다.

- run execution에 Policy 전체 closed-record digest, model/config/processor 파일 SHA map·checkpoint step·학습 Dataset identity, Scene/Calibration/physics model·Task·seed·phase·고정 배치/평가 계약을 보존한다. Episode에는 실제 raw Recipe SHA도 남는다.
- Resume는 새 출력에 이전 segment와 영상을 hardlink하고 새 Episode를 추가한다. 이전 Native identity/파일 bytes는 불변이며 상속 HDF5/MP4는 같은 inode였다. 누적 episodes는 성공 개수가 아니라 **평가 attempt 목표**다. raw Recipe의 새 output/누적 목표 변화와 실제 semantic evaluation 계약 변화를 구분한다.
- [실제 자료 불일치 시험](evidence/p01-rollout/reader-resume-results.json)은 양 엔진의 Policy·Scene·Model·평가 계약 변경8건을 출력 생성 전에 RESUME_INCOMPATIBLE로 거부했다. 불명 claim을 시간 경과만으로 재실행하지 않는 기존 Native 경계도 시험했다. 중간 physics tick Resume는 제공하지 않는다.
- [실제 cancel·보존](evidence/p01-rollout/cancel-preservation-results.json): MuJoCo3/Isaac4 step 뒤 취소, 완료 Episode0·clean close·미해결 claim0. 같은 cancel command ID를 두 번 보내도 단일 명령으로 처리됐다. 중복 start도 같은 Handle을 반환했다.
- [취소 뒤 새 출력 준비](evidence/p01-rollout/cancel-resume-contract-results.json)도 취소 attempt1을 보존하고 다음 번호2로 준비되는 것을 확인했다. 이 검사는 추가 engine rollout 없이 Native 계약만 확인했으며 attempt2 실행 완료로 보고하지 않는다.
- Reset 실패 및 close/abort 실패는 제어된 fault fixture로 검사했다. Isaac env.close 예외가 있어도 Native owner.close를 시도하며 모든 video abort를 시도한 뒤 오류를 수집한다. **실제 SDK 오류/장치 단절을 일으킨 시험은 아니다.**

HDF5의 observation/action/state와 영상을 대용량 JSON으로 복제하지 않는다. MuJoCo opaque 초기 snapshot은 초기 상태 재생 근거로 Episode Metadata에만 두고 attempt/summary에서는 반복하지 않는다. Native summary는 작은 outcome/지표만 담는다.

## 시간·메모리·실행 경고

최종 verified/Resume 결과에서 ACT inference는 **CPU**, Isaac physics/render는 GPU다. CPU/GPU 간 별도 RPC·분리 추론 프로세스를 만들지 않았다.

| 실제 run | control FPS | 평균 select_action+후처리/preflight | Episode 실행 s | process Peak RSS MiB |
|---|---:|---:|---:|---:|
| MuJoCo verified |13.672|24.407ms|4.388|2912.922|
| MuJoCo Resume 새 Episode |16.966|16.178ms|3.536|2334.262|
| Isaac verified |8.943|15.144ms|6.709|7135.512|
| Isaac Resume 새 Episode |7.931|17.226ms|7.565|7160.953|

FPS는 Reset·렌더·기록 단계이며 engine/AppLauncher/Policy 로딩을 포함하는 worker 전체 시간은 각각12.833/11.705/81.168/83.142s다. 평균 inference는 chunk 재추론과 queue 소비를 함께 평균한 값이며 모든 frame에서 network forward를 수행한 시간은 아니다. 설정상 영상/물리30Hz를 wall-clock30FPS 달성으로 보고하지 않는다. 병행 회귀/엔진 작업의 부하가 포함된 측정이며 전용 benchmark가 아니다.

Isaac nvidia-smi 장치 전체 peak는 verified4765MiB/Resume4826MiB(취소 실행4893MiB)다. desktop·Kit/GPU 기타 사용을 포함하는 polling 값이고 모델 단독 peak가 아니다. MuJoCo는 이 시험에서 software EGL 렌더/CPU inference로 실행했고 별도 GPU memory 측정을 하지 않았다. CPU RSS에는 모델/SDK/렌더/Arrow import가 포함된다.

Isaac 로그에는 기존 deprecated extension·Fabric/render/종료 warning과 **보호 audit가 차단한 SDK 경로 material_cache.json 쓰기의 비동기 예외**가 남았다. 엔진/Policy Step·RGB/저장/정상 terminal을 확인했지만 warning-free 실행은 아니다. 쓰기를 허용하거나 설치 파일을 바꾸지 않았다. full Manifest reload와 checkpoint hash, 원본 stat/선택 SHA는 이후에도 일치했다. 해당 경고를 물리 실패나 해결된 문제로 감추지 않는다.

## 최종 검증·완료 경계

**846 passed, skipped0 = 이전832+신규14**, 기존 torchvision warning2개. [JUnit](evidence/p01-rollout/unit-tests.xml), [로그](evidence/p01-rollout/logs/28-final-suite.log), [wheel](evidence/p01-rollout/build-workbench.json). wheel source/설정 bytes·compile·isolated import·실제 CLI invalid-config 경계를 검증했으며 환경에 설치하지 않았다. 별도 lint/type 도구를 설치하거나 실행했다고 주장하지 않는다.

[Standards](evidence/p01-rollout/standards-review.md)/[Spec](evidence/p01-rollout/spec-review.md) 독립 리뷰의 지적은 모두 해소했다. RED/GREEN 및 실제/모의 오류 증거를 구분했다. 단순화는 공통 strict preflight·짧은 outcome/오류/encoder cleanup 함수를 재사용한 범위이며 엔진 수명을 추상화하지 않았다. [작업 전 사본](evidence/p01-rollout/before/) 기준으로 검토했고 Git 저장소가 없어 Git diff/commit을 수행하지 않았다. incremental-implementation·source-driven-development·TDD·diagnosing-bugs·code-review·code-simplification·documentation-and-adrs의 실제 지침을 적용했다. 별도 definition-of-done 문서는 가용 위치에 없어 읽었다고 주장하지 않는다.

[보존](evidence/p01-rollout/preservation-after.json): 원본56100개 stat와 선택223개 SHA의 미승인 변화0. 이전 보고서/검증 root·현재 Native 입력·L03 결과·선택 SDK·제품 코드가 대상이며 모든 과거 증거/대용량 corpus/SDK binary 전수 byte 검증은 아니다. 기존 Scene Manifest 전체와 ACT checkpoint 파일은 별도 재확인했다. 설치/업그레이드·환경 분리·추가 학습·Hub·실물 연결은 없다. 명령/코드·입력 근거는 [commands.json](evidence/p01-rollout/commands.json), [최종 증거](evidence/p01-rollout/verification.json)에 남긴다.

P01의 **단일 env·현재 Scene·ACT·Fixed·실제 Step/판정/기록·새 출력 Resume**는 검증했다. AC01의 Task 의미/phase와 정상 failure, AC02의 공식 Policy/명시 매핑 경계를 확인했다. 과거 B01 checkpoint와 같은 궤적/성공 최초 tick 재현이나 모든 Scene/Policy/Tracker·장시간·물리 강제 종료·GPU OOM을 완료로 표시하지 않는다. 실제 Placement 성공 Episode는 없으며 그 제한을 유지한다.

기존 E01 cube–cup1.197188790mm 잔차, MuJoCo strict float32 상한, SMOL-PAD-01, Follower device_command/motor range, Isaac Random RNG·복수 Episode Annotation·같은 앱 복원 검증 등 OPEN은 그대로다. 이번 Resume는 **새 worker**이므로 같은 Isaac 앱에서 여러 Episode 동등성을 해제하지 않는다. P02 Real/Sim·P03 실물은 RO command binding/장치 승인·실제 검증이 따로 필요하다. **P01에서 중단하며 후속 작업을 자동 시작하지 않는다.**

공식 API 근거: [LeRobot ACT0.4.1](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/policies/act/modeling_act.py), [Isaac Lab2.3 Env](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html), [MuJoCo3.3.7](https://mujoco.readthedocs.io/en/3.3.7/python.html). MuJoCo 웹 문서 조회가 실패한 항목은 설치3.3.7의 실제 API/기존 E02 실행 근거를 사용했다. 최종 소스 identity는 [설치 소스](evidence/p01-rollout/source-inventory.json)에 기록한다.
