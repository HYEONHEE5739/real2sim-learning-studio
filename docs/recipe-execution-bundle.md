# Recipe·Execution 묶음 — R01~R03

2026-10-26. 상태: **R01~R03 파일/작업 프로세스 기반 구현·검증 완료**. D01~D04의 완료 증거와 현재 제품 hash를 먼저 확인했으며 R 작업의 선행 차단 문제는 없었다. 실제 R 목록은 3개이므로 다른 작업을 끼워 넣지 않고 R01→R02→R03으로 진행했다. 실제 engine/학습/장치 stage는 아직 미구현이며 이 보고서는 전체 Workflow 실행 완료를 뜻하지 않는다.

## 완료 범위·파일

| Task | 구현·검증 |
|---|---|
| R01 | 저장 YAML의 단일 stage·필드/타입·중복 key·비유한 값·tag/alias·engine/역할 검사. DataGen IK 선택/override 거부 |
| R02 | Scene·Task·Episode identity 연결, Object 선택/순서·frame/함수/params 검증, 배치 요청 분리, named signal 의존 연결, 입력 고정/재검사·CLI 준비 |
| R03 | request/output/worker 배타 claim, 같은 의도의 재전송·상태 불명 처리, 같은 interpreter의 별도 worker, 상태/결과·JSON IPC·ACK/대상/중복 명령·취소·Preview metadata |

제품 파일은 [recipe.py](../robot_learning_workbench/src/robot_learning_workbench/recipe.py), [run.py](../robot_learning_workbench/src/robot_learning_workbench/run.py), [cli.py](../robot_learning_workbench/src/robot_learning_workbench/cli.py) 3개다. 시험은 test_recipe.py/test_recipe_preparation.py/test_run_claims.py/test_worker_protocol.py다. 기존 Scene·Task·Episode 제품/시험·패키징·task_modules.yaml·의존성은 바꾸지 않았다. 별도 Manager·Adapter·launcher·Registry·설정 언어를 추가하지 않았다.

기존 execute_request의 request 파일→선택 Python worker→stdout/stderr log 경계를 참고했다. UI options 대신 저장 Recipe의 bytes SHA를 고정하고 기존 공개 Scene/Task/Episode 함수를 직접 호출한다. 공식 SDK 사용은 [설치 소스 검토](evidence/recipe-execution/official-api-review.json)에 기록했다. 시뮬레이터·Trainer·장치를 실행한 검증은 아니다.

## R01 — Saved Recipe

`read_recipe(path,expected_stage=None)`은 원문을 한 번 읽어 raw/sha256/base_dir/검증된 불변 RecipeSpec을 반환한다. RecipeSpec 하나에서 stage별 필드 계약을 분기하며 비어 있는 단계별 Wrapper class를 만들지 않았다. `inputs/execution/output`은 필요하고 engine은 simulation/real_sim 단계에서 isaaclab/mujoco다. 생성 대상 objects와 함수 역할은 적용 stage에만 허용한다. Source에는 success/acceptance gate를 허용하지 않고 Annotation에는 objects 재배치를 허용하지 않는다.

키 중복·unknown field·타입 변환·NaN/Infinity·YAML object/tag·anchor/alias·표현식/임의 hook 순서는 거부한다. seed는 uint32, budget/count는 양의 정수다. datagen의 ik_solver/ik_failure_policy/ik_configuration/ik_parameters/ik_identity 등 선택 필드는 고정값을 써도 오류다. 일반 Task params는 T01의 선언 타입으로 검증한다. 계산/조건은 YAML에서 실행하지 않는다.

경로는 canonical Recipe 파일의 부모 기준이다. Recipe symlink는 먼저 resolve해 API/CLI/worker가 같은 부모를 사용한다. 상대 Scene/Asset 경로와 혼합하지 않는다. 오류는 code/field/source와 가능한 YAML line으로 반환한다. 임의 수치·배치 기본값을 새로 만들어 기존 설정을 대체하지 않는다. 제공 Task dataclass의 기존 defaults와 stage 고정 phase는 해석된 binding에 기록한다.

## R02 — 준비·identity·호출

`prepare_recipe(doc,scene=None,tasks=None,inputs=None)`은 run ID 없는 PreparedRun을 만든다. resolved_inputs, scene_identity, object_order, function_bindings, effective_settings/code_identity, output_path, pending_checks를 가진다. `summary()`는 JSON용 자료, sha256은 준비 결과 identity다. `verify_prepared_inputs`는 실행 직전 파일/Scene/Dataset/Task·실행 코드의 변경을 다시 확인한다.

- Scene은 S01/S02 load_scene으로 검증하고 Recipe engine 이름 isaaclab을 Scene/Task의 isaac으로 명시 매핑한다. 미선언 engine entry는 오류다. 실제 body/joint/센서 lookup은 engine binding 단계다.
- objects의 YAML 순서를 object_order로 유지한다. task_object만 선택하고 삭제/미선택 대상의 Task 참조는 T01이 거부한다. 고정/Random 배치 함수를 준비 중 실행하거나 RNG를 소비하지 않는다.
- xy_m와 orientation은 PlacementRequest 자료로 분리한다. Task params에는 object를 필요한 선언에만 공급한다. bool 회전값을 숫자로 coercion하지 않고 S02 SE(3) 검사를 사용한다. 기본 자세·Geometry는 기존 Scene/Task 계약을 사용한다.
- functions의 signals/acceptance/success/metrics는 정해진 kind로 resolve한다. acceptance-only v8 선언은 등록된 provider와 공통 object params로 grasp tracker 하나에 연결한다. 명시 신호와 default provider의 params가 다르면 오류다. pre/post/episode_end phase를 기록할 뿐 factory/predicate/tracker를 호출하지 않는다. Source recording_only·Annotation 복원·Evaluation Placement 의미는 그대로다.
- Annotation/DataGen은 입력 Episode Dataset의 정확한 Scene identity를 요구한다. Recipe의 Scene 위치나 API에서 제공한 패키지도 같은 Revision/hash여야 한다. 과거 형식 변환만으로 없는 manifest/코드 identity를 채우지 않는다. 제공 Scene의 위치도 resolved_inputs에 고정한다.
- 입력 JSON은 읽은 bytes와 파일 hash를 대조한다. 디렉터리 artifact는 파일별 SHA를 고정하며 공식 Hub snapshot의 일반 file symlink도 실제 target bytes로 검사한다. directory/broken symlink의 암묵 탐색은 하지 않는다.
- Local 공식 Dataset/공식 config는 Scene·Task 없이 준비할 수 있다. API InputCatalog는 URI·40자리 revision·로컬 경로/identity를 고정한 snapshot을 받을 수 있다. CLI/worker의 자동 Hub 다운로드/해결은 아직 없으며 미해결 URI는 INPUT_UNRESOLVED다. remote revision 검증은 resolver 소유이며 여기서 네트워크 검증 완료로 표시하지 않는다.

PreparedRun의 pending_checks는 실제 engine 초기 상태 복원, 장치/Calibration, 공식 Policy/processor/Training, DataGen IK runtime identity를 구분한다. 고정 DLS + Best Effort 수치/안전 계약은 기록하지만 아직 없는 solver/model/code identity를 만들지 않는다. 공식 training_config의 명시 output_dir/dataset.root는 Recipe와 일치해야 하며 조용히 덮어쓰지 않는다. MiniVLA policy는 거부한다.

공식 LeRobot 0.4.1 source에서 Resume가 local config_path/checkpoint 경로와 기존 output을 사용하는 것을 확인했다. 따라서 train mode=resume에는 일반 신규 출력 제약을 적용해 다른 의미로 바꾸지 않고 **STAGE_VALIDATION_PENDING**으로 L01 공식 검증까지 보류한다. start도 해당 출력/작업 디렉터리를 예약하기 전에 이 조건을 거부한다. 학습 loop/optimizer/scheduler/validation hook은 만들지 않았다.

## R03 — 수명·IPC·오류

`start(StartRequest)`는 저장 SHA/stage/output·모듈 목록을 확인하고 별도 worker를 실행한다. StartRequest의 request_id는 같은 실행 의도의 재전송에서 유지한다. expected_prepared_sha256은 앞선 검증 결과까지 고정하려는 호출자가 제공할 수 있다. worker는 YAML을 한 번 읽은 bytes로 hash/parse하고 이후 편집은 현재 실행에 적용하지 않는다. 동일 request/payload는 기존 handle/result, 다른 payload는 REQUEST_CONFLICT다. 부분 claim·spawn ACK 불명은 RUN_STATE_UNKNOWN이며 새 worker를 자동 시작하지 않는다.

기본 run root는 output.parent/.workbench-runs이고 run.json/worker_request.json/recipe.yaml/prepared.json/결과·제어 기록을 둔다. Stage output은 별도 새 디렉터리로 예약만 해서 D02 EpisodeWriter의 신규 경로 계약과 충돌하지 않게 한다. `.workbench-output-<hash>.json`은 같은 출력으로 다른 request가 동시에 진입하는 것을 막는다. request/output/worker claim은 짧은 TTL로 삭제하거나 실패 뒤 자동 재사용하지 않는다. 실패 후 새 실행은 새로운 의도와 출력 경로를 사용한다.

worker는 sys.executable과 현재 package 위치를 사용한다. source checkout을 위한 PYTHONPATH 전달은 같은 interpreter의 import 경로이며 새 환경/launcher가 아니다. Isaac은 concrete runner가 존재할 때 공식 AppLauncher를 먼저 만들고 engine import를 수행하도록 경계를 뒀다. 현재 실제 runner 파일이 없으면 **STAGE_UNAVAILABLE**이며 config/fixture로 성공 처리하지 않는다. 알려진 source/annotation/datagen/evaluation 및 train의 구체 함수에 연결할 자리만 있고 새 stage plugin 체계는 없다.

- commands/<id>.json은 배타 생성하고 sender/worker가 control.lock 아래서 publish/read한다. seq/run/target/지원 kind·payload와 64KiB 제한을 검사한다. 완료/접수된 명령 파일은 매 tick 재독하지 않는다.
- 같은 command ID/payload는 기존 queued/accepted/rejected/completed ACK를 조회하며 다른 payload는 충돌이다. step/mark/skip은 completed ACK에 실제 applied_tick이 필요하다. 다른 Episode/env로 늦게 도착한 명령은 거부한다. Training의 pause/step은 지원하지 않는다.
- cancel은 협력 중단이다. 장치 torque/port 상태나 물리 즉시 정지를 의미하지 않는다. accepted 뒤 죽은 worker의 명령을 완료로 승격하거나 자동 replay하지 않는다.
- events.jsonl은 JSON 전용이고 events.idx의 고정 offset으로 제한된 페이지를 seek한다. stdout/stderr는 stdout.log에 분리해 라이브러리 출력이 제어 메시지가 되지 않는다. episode_committed는 D02 완료 index에서 실제 identity를 재확인한다.
- Preview는 camera/slot/generation/frame/time metadata 한 개만 메모리에 coalesce하고 다음 control/status 기록에 snapshot으로 내보낸다. read_preview로 조회하며 별도 seq를 사용한다. 매 frame 파일/영상 복사나 control log 적재를 하지 않는다. 실제 shared-memory renderer/다중 camera UI 연결은 U02의 후속 범위다.
- worker nonce와 PID/start_ticks/boot ID로 관측을 구분한다. 부모가 실제 process exit를 확인하면 WORKER_EXITED로 실패를 남기고, 관측할 수 없는 worker는 unknown이다. PID만으로 다른 프로세스를 같은 run으로 판단하거나 재시작하지 않는다.

`execute`의 fixture runner 주입은 SPEC의 독립 프로토콜 시험용 Python seam이며 run.json에 fixture_runner=true를 기록한다. Recipe/CLI에서 arbitrary runner 경로를 선택할 수 없고 실제 worker는 기본 dispatch만 쓴다. StageResult/status/counter/output이 잘못되면 STAGE_RESULT_INVALID다. 테스트용 completed/cancelled를 실제 Training/로봇 실행 성공으로 확대하지 않는다.

## 검증·보존

**전체 571 passed, skip 0** = 기존 506 + 신규 65. [JUnit](evidence/recipe-execution/unit-tests.xml), [Task별 증거](evidence/recipe-execution/task-results.json), [명령/identity](evidence/recipe-execution/commands.json), [최종 검증](evidence/recipe-execution/verification.json)을 남겼다.

- YAML·stage/engine·Scene/frame/Object/function/params·입력 변경·고정 IK·새 Task 모듈·단일 grasp dependency·CLI 준비를 시험했다. 준비 과정에서 Task 계산/factory를 실행하지 않았다.
- 동시 start·같은/다른 payload·부분 claim·출력 충돌·두 번째 worker·실제 STAGE_UNAVAILABLE child를 검증했다.
- 실제 별도 fixture process에서 ACK/중복 step·mark·대상 오류·cancel·stdout 분리를 시험했다. SIGKILL 뒤에도 D02에 저장한 Episode를 읽었고 unresolved ACK를 재실행하지 않았다.
- sender의 command 파일이 완성되기 전에 worker가 읽는 실제 경쟁 조건을 발견해 동일 lock 경계로 수정하고 deterministic thread/process 시험을 추가했다. 잘못된 producer/result/회전 bool과 snapshot 변경도 별도 RED/GREEN으로 검증했다.
- wheel build/compile·독립 CLI 준비·실제 worker subprocess가 통과했다. 초기 smoke의 짧은 대기/진단 보존을 개선하고 실패 로그를 유지했다. 최초 child stderr가 저장되지 않은 실패의 정확한 원인을 확정했다고 주장하지 않는다. 이후 stderr/status를 보존하고 10초 상한 내 상태 기반으로 확인했다. 기존 환경 설치/변경은 없다.

Python3.11.15 및 기존 PyYAML/NumPy/h5py 환경을 썼다. 원본과 B01~T04·D01~D04 증거의 [보존 대조](evidence/recipe-execution/preservation-after.json)를 수행했다. 기존 전체 파일 stat와 선택 SHA이며 전체 대용량 corpus/SDK binary의 전수 byte 증명은 아니다. Git 저장소 초기화/commit은 하지 않았고 별도 lint/type 도구는 설정되어 있지 않아 실행했다고 보고하지 않는다.

AC01의 선언/준비, AC02의 로컬 claim/프로세스/ACK, AC03의 CLI·공유 guard/미지원 명령 부분을 검증했다. 실제 UI dirty 편집·Preview 화면(U01/U02), engine lookup/복원/실행·실행 중 Resume(E 계열), 공식 Trainer/processor/Hub(L 계열), 실제 stop/장치 lifecycle(RO 계열)은 미검증이다. B01 Isaac DataGen 실패/Evaluation 비결정성·B03 실물 OPEN·ASSET-FINGER-01은 그대로다.

다음 후보는 **RO01·RO02·RO03**의 보정 계산→장치 수명 mock→저장 Capture fixture/동기 검증 묶음이다. RO01/02는 B03, RO03은 RO01/02와 CAL-02를 선행으로 사용하므로 순차 연결할 수 있다. 실제 장치 시험은 별도 승인된 범위에서만 가능하며 이 제안으로 시작하지 않는다. **R 묶음을 완료하고 중단한다.**
