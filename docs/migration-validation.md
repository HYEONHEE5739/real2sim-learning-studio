# 기존 코드 이관·v8 보존·검증 계획

2026-10-25 최종 결정: 새 플랫폼 개발 기준은 **Isaac Sim5.1 / Isaac Lab2.3 / LeRobot0.4.1 / MuJoCo3.3.7**이다. 업그레이드는 진행하지 않는다. 최신 버전 조사는 참고 이력이며 신규 환경 분리·분리 추론·업그레이드 대응 코드는 개발 범위에 포함하지 않는다. 기존 UI/엔진 worker의 필요에 따른 프로세스 분리는 유지한다.



후속 기능별 명세는 [기능 범위 색인](../CAPABILITY-MAP.md)으로 추적한다. 현재 미확정 사항의 상태·해제 증거·구현 차단 범위는 [구현 전 확인 목록](preimplementation-checks.md)에서 관리하며, 아래 검증 매트릭스는 그대로 유지한다.

[API·Interface 명세](interfaces.md)의 계약 시험도 이관 검증에 포함한다. 중복 실행 요청, 응답 유실, Episode commit 경계, Task 상태 수명과 pre/post-step 호출 순서는 계산식 동등성과 함께 검증한다. 명세 작성만으로 이 시험을 통과한 것은 아니다.

작성일: 2026-10-25. [통합 설계](architecture.md), [데이터 계약](data-contracts.md)의 검증 계획이다. **실행 결과 보고서가 아니다.** 계획 작성 당시에는 코드/Metadata 읽기만 수행했다. 이후 2026-10-25 [B01](b01-baseline.md)에서 별도 공간의 기존 양 엔진 대표 Baseline 실행·경계 fixture를 확보했다. 신규 패키지 변환·제품 구현·실물 제어는 수행하지 않았다.

## 1. 원본과 조사 근거

| 이름 | 실제 위치 |
|---|---|
| 기존 로봇 코드 루트 P | `/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab` |
| 기존 Builder B | `/home/hyeonhee/soarm_isaaclab/real2sim-builder/app` |
| Baseline v8 | `/home/hyeonhee/soarm_isaaclab/soarm101_lab/outputs/real2sim/environments/scene2_builder/v8` |
| Builder 프로젝트 | `/home/hyeonhee/soarm_isaaclab/real2sim-builder/projects/scene2-final-contact-review-20261014-932c8f2e` |
| 원본 Builder export | 위 프로젝트의 `exports/scene2-final-contact-review-20261014-932c8f2e-final_contact_review` |

아래 상대 경로는 P 또는 B 기준이다. 미커밋 파일을 정리·되돌리지 않는다. 기존 보호 학습용 env 파일이나 과거 자료를 신규 구조에 맞추려고 직접 수정하지 않는다. 최신 native Source/Annotation과 과거 legacy 실행을 구분한다.

## 2. 기능별 기존 근거 → 새 책임

MiniVLA는 사용자 승인으로 이관·개발·검증 범위에서 제외한다. 관련 모듈·호환 계층·Checkpoint 로더·학습/추론/평가 및 전용 변환은 새 Workbench에 구현하지 않는다. 기존 P `learning/minivla/`와 관련 데이터·Checkpoint는 수정하거나 삭제하지 않는다. 아래 기능 보존과 완료 기준은 이 예외를 적용한다.

MiniVLA 개발 과정의 자체 LR 그래프·Training/Validation Loss 기록/시각화·학습 관리 코드도 ACT·SmolVLA로 이관하지 않는다. 공식 Trainer 기본 동작을 보존하고 필요한 표시는 공식 로그/결과를 읽는 독립 모듈로 구현한다. 코드가 MiniVLA 폴더 밖에 있더라도 이 제외 기준을 적용한다.

| 기능 | 기존 코드 근거 | 새 위치 | 현재 확인 수준 |
|---|---|---|---|
| Scene 편집/후보/증거 | B `core/project.py`, `scene.py`, `candidates.py`, `evidence.py` | Builder project | 코드 존재; 이관 후 기능 검증 필요 |
| scan 재구성/등록/분할 | B `reconstruction/scan.py` import_scan/segment/registration, `pipeline.py:124 run` | reconstruction | 알고리즘·Scene 후보 갱신 의미 보존 |
| 카메라/Geometry/물성 정합 | B `calibration/camera.py:41 fit_cameras`, `multipose.py:25 fit`, depth/physics/robot | Builder calibration | 추정 결과를 물리 검증으로 간주하지 않음 |
| export/렌더/검증 | B `exporters/package.py:13 export_package`, `:140 verify_package`, usd/mujoco, blender, validation | export/exporters/rendering/validation | 참조 closure와 실제 엔진 로딩 검증 필요 |
| Capture/RealSim | P `real2sim/runtime.py`, `real2sim/ui.py` | robot/capture, real_sim + 대응 UI | UI 기능과 장치 수명 함께 보존 |
| Precision Calibration | P `real2sim/precision.py`, `precision_ui.py` | robot/calibration + UI | raw↔model·identity·잔차 적용 계약 확인 |
| Source | P `native/source.py:87 prepare`, `:121 run`, `native/isaac.py`, `native/mujoco.py`, `data/recording.py` | 엔진별 source, data | 기존 기록 검증 보고 일부 존재; 신규 미검증 |
| Annotation | P `native/annotation.py:98 _episode`, `:166 run` | 엔진별 annotation | manual/auto·물리 채택·state 복원; old annotation runner로 되돌리지 않음 |
| DataGen | P `workflow/datagen.py:138 run_mujoco`, `:310 run_isaac`, `workflow/mimic.py` | 엔진별 datagen + generation | reference/예산·Task 실패를 유지; IK는 승인된 고정 DLS + Best Effort, SciPy/Strict/Hold 이관 제외 |
| DataGen 고정 IK | P `utils/so101_kinematics.py:157 inverse_kinematics`, `simulation/ik.py:DLS_PARAMETERS`, `solve_selected` best_effort 분기 | 기존 generation/mimic + 엔진 datagen/control/MDP 책임 | DLS 계산·측정 seed·finite/limit/0.5 rad jump 보존; 선택 dispatcher·fallback 제외 |
| 등록 Task/Reset | P `workflow/task_scripts.py`, `task_terms/`, `real2sim/workspaces/reset.py`, `tasks.py` | tasks | legacy 사용자 함수 지원 범위를 현재 native와 혼동하지 않음 |
| 변환/Merge | P `learning/datasets.py`, `workflow/lerobot_merge.py`; 기존 변환 스크립트 | data/lerobot | 공식 API 연결·action 의미 검증 |
| Training | P `learning/training.py training_command/train` | learning/train | 공식 실행 연결만 참고; 자체 loop/LR/Loss 관리 이관 금지, 학습 종료 후 자동 검증 연결은 제외 |
| Offline Validation | P `learning/validation.py` | learning/validate | 독립 실행 단계; Trainer 삽입 금지, loss/샘플 검증은 Task 성공률 아님 |
| Sim/실물 평가 | P `workflow/evaluation.py:220 evaluate_sim`, `workflow/policy.py`, `workflow/mujoco.py`, `workflow/operations.py` | 엔진별 evaluation, robot/evaluation | 코드 구현과 실제 로봇 검증을 구분 |
| Hub | P `workflow/hub.py`, `learning/datasets.py` | hub | upload/download/commit·오류·UI 기능 보존 |
| Curation | P `workflow/curation.py`, `curation_ui.py:373 CurationDialog` | data/curation, ui/curation | 영상·분포·제외·split·export 보존 |
| 실행/저장/Resume | P `workflow/operations.py:551 execute_request`, `workflow/data_resume.py`, `data/source.py`, `data/episodes.py:379 DatasetWriter` | run/data/episodes | Episode 경계 재개, 원본 불변·새 출력 |

현재 검토는 대표 호출 경로와 화면 기능에 근거한다. 구현 착수 시 각 영역의 기존 버튼/CLI/예외를 체크리스트로 전수 대조하고, 표에 없는 세부 기능을 임의 삭제하지 않는다. 신규 공식 기능으로 교체할 때도 수치/입출력 의미를 확인한다.

## 3. v8 Asset·Metadata 변환 대응

| 기존 자료 | 새 계약 | 보존/정리 기준 |
|---|---|---|
| profile.json workspace/robot_base/object T_workspace | scene.json frames/objects | 행렬 방향·부모 관계 동일; world/local 중복 파생값은 필요 시 계산 |
| profile cameras/optical_axes/wrist_mount | scene camera/frame + Calibration | K·distortion·optical convention·mount·실행 렌더 변환 구분 |
| profile geometry/dimensions·task success | object task_geometry + 등록 판정 params | 판정용 치수를 collision mesh로 임의 교체하지 않음 |
| task dynamic/targets | Object role/binding + 명시 v8 Recipe | 블록 생성 목록과 고정 cup 구분; alias 명시 |
| task physics/object_physics와 physics.json | scene object 물성 + 근거 상태 | 중복 값의 우선순위를 실제 loader에서 확인한 뒤 단일 원본 선정 |
| task reset/robot_initial_joint_rad | v8 placement 규칙/Recipe + robot 기준 상태 | uniform/margin/separation/clearance/초기 joint 보존; four_anchors 제외 기록 |
| builder USD/MJCF/mesh·robot URDF/USD | assets의 native 파일 | 원본/파생 identity·기하·충돌·물성 보존 |
| 외부 `assets/SO101/mujoco/finger_convex_parts.json` | package assets/robot collision | P `simulation/mjcf.py:100`의 실제 실행 의존성 포함 |
| 외부 `assets/SO101/mujoco/usd_contact_pads.json` | package assets/robot collision | P `simulation/workspace_scene.py:92`의 실제 실행 의존성 포함 |
| joint calibration active/profile/model evidence | calibration.json + 실행 필수 profile/모델 | active 포인터를 나중 값으로 resolve하지 않고 당시 identity 고정 |
| manifest/provenance·UNVALIDATED 근거 | 새 manifest + 검증 요약·외부 증거 참조 | 기존 중복 경로/내부 구조는 제거 가능, 검증 상태 승격 금지 |

Builder의 편집 current Scene, 검토 candidate, export Scene이 같다고 가정하지 않는다. v8 baseline이 실제 참조한 export와 파일 graph를 기준으로 변환한다. 패키지에 없는 외부 robot/collision/profile을 찾을 때 누락을 기록하고 다른 파일로 대체하지 않는다.

원본은 보존하고 새 출력 디렉터리를 사용한다. 변환기는 입력 경로가 출력과 같거나 기존 출력이 있으면 거부한다. 변환 보고서는 원본→새 필드/파일·삭제 이유·추가값 근거·각 hash·수치 차이를 남긴다. 새 필수 값이 없으면 추정해 채우지 않는다.

## 4. 보존해야 할 수학·시간 의미

### Calibration

- P `real2sim/precision.py:45 simulation_configuration`: urdf_identity/precision_bound_residual/legacy_scene_offsets의 기존 적용 모드를 구분한다.
- `profile_for_model:326`: 모델 hash 및 limits-only 변경 허용의 기존 의미를 보존한다. historical URDF identity를 최신 모델로 조용히 교체하지 않는다.
- encoder raw/native 변환의 범위·drive mode·branch·anchor/rad_per_count·정수 양자화·역변환을 보존한다. 관측의 범위 외 처리와 명령 제한을 혼동하지 않는다. homing offset을 이중 적용하지 않는다.
- P `real2sim/workspaces/builder.py:309 calibrate_simulation_usd`: 원점 회전과 축 offset 곱 순서·관절 parent/child 관계 유지. geometry residual을 q 명령에 다시 더하지 않는다.
- side/wrist camera K·해상도·mount, optical frame→엔진 카메라 변환, Isaac Fabric의 실제 wrist pose를 보존한다. 이관 시 원본 파라미터와 엔진 렌더 파생값을 분리한다.

### Placement

P `simulation/mujoco_backend.py:237 success_details`, `real2sim/workspaces/environment.py:19 task_success_details` 기준:

- `inverse(T_target) @ T_object`로 목표 로컬 좌표 변환.
- 기존 dimensions의 bounding box 8개 꼭짓점을 사용한다. 새 배치용 collision Geometry와 별개다.
- 컵 반경은 높이별 선형 보간에서 wall thickness를 뺀 값. radial excess `<= 0.001 m`.
- 최저 꼭짓점 `> -h/2 + wall - 0.002 m`, 최고점 `< h/2`의 엄격 부등호.
- 선속력 `< max_speed_m_s`이며 v8은 0.03 m/s. angular 속도·dwell·gripper release를 새로운 필수조건으로 추가하지 않는다.
- inside_region 분기는 target-local bounds의 inclusive 검사를 그대로 유지한다.

### StableGrasp와 단계별 성공

P `real2sim/workspaces/grasp.py:9 StableGrasp` 기준:

- 양측 접촉, 상대 위치 drift `<= 0.006 m`, 상대 회전 `<= 10°`.
- 창 안 EEF와 물체의 순이동 각각 `>= 0.005 m`.
- 유지 시간 `(N-1)*dt + 1e-9 >= 0.20 s`.
- 같은 tick 재호출은 누적하지 않음, tick 누락은 창 초기화, drift 초과 시 오래된 sample 제거, 완료 latch 유지, 평가 이후 창 크기 제한.
- size 인자가 있다고 실제 판정에 사용한다고 해석하지 않는다. grasp에 물체 높이·접촉 면적·force 크기 조건을 새로 넣지 않는다.
- MuJoCo finger contact는 지정 body pair와 `contact.dist <= 0`; Isaac Annotation/DataGen의 contact sensor는 `> 1e-4 N`; 기존 Evaluation 경로의 threshold는 별도 확인·보존(기존 조사에서 `> 0.01 N`). 서로 같게 통일하지 않는다.
- release/drop 진단은 latch를 자동 취소하는 성공 조건이 아니다. gripper 변화·접촉 소실·상대 drift·유지 시간을 기존대로 계산한다.

Annotation/Production DataGen은 Placement AND latched StableGrasp. 기본 Simulation Evaluation은 Placement에서 성공 종료하며 grasp/transport/full_task_success는 별도 지표다. Source는 시연 기록 단계이며 임의 성공 gate를 추가하지 않는다. Legacy distance/gripper proxy 또는 center-only 판정은 별도 과거 경로로 구분해 데이터 의미를 보존한다.

Annotation은 initial state를 복원하고 pre-step 관측/이미지를 기록한 뒤 명령을 실행하며 post-step 접촉으로 tracker를 갱신한다. 수동 mark는 기존 물리 통과를 대신하지 않는다. 기존 위치에서 실행하던 판정을 다른 MDP 시점으로 옮기면 수학이 같아도 동등하지 않다.

### Reset과 물리 실행

- P `real2sim/workspaces/reset.py:18 sample`: uniform XY 범위·물체 크기·margin·separation·물체 순서·seed, 물체별 1,000회. 높이 `support_z + half_support_z + half_object_z + clearance`; v8 clearance=0.003 m.
- four_anchors 제외만 승인된 분포 변경으로 표시한다. 과거 four_anchors 데이터의 metadata를 uniform으로 바꾸지 않는다.
- P `real2sim/workspaces/tasks.py:442 validate_reset_pose`: SE(3)와 회전한 꼭짓점; support XY tolerance 1e-7 m, 하단 tolerance 1e-6 m.
- P `simulation/mujoco_backend.py:219 reset_object_poses`: 변경 대상 관련 penetration `< -1e-6 m` 거부·rollback. Isaac에 동일 검사 존재를 추측하지 않는다.
- 기존 조사 기준 MuJoCo physics 1/300 s×10, Isaac 1/240 s×8로 control 30Hz. 동일 control rate라는 이유로 physics dt를 통일하지 않는다. 실제 실행 경로별 cfg를 baseline에 기록한다.
- 새로운 Geometry 접촉 배치는 별도 지원 기능이며 v8 높이·자세·접촉/solver 동작과 비교한다. 사용자 자세 변경은 새로운 입력이며 원래 기본 배치와 결과가 같다고 주장하지 않는다.

### 승인된 변경: DataGen 고정 IK

2026-10-25 사용자 결정으로 **Pinocchio DLS + Best Effort**만 신규 DataGen에 이관한다. [상세 수치·명령 경계](../SPEC-simulation-workflows.md#datagen-ik-고정-계약)와 [요구사항](requirements.md)을 따른다. B01의 SciPy + Strict 실행·원본·실패 trace는 변경하지 않는다. 기존 기능 보존의 명시적 예외이며, 다른 Calibration·판정·물리 시점을 변경할 권한은 아니다.

검증은 두 비교로 나눈다. 첫째, 동일 모델/target/측정 seed/직전 명령으로 **기존 DLS + Best Effort** 계산과 새 계산·안전 거부·그리퍼·좌표 처리를 비교한다. 둘째, B01 입력을 새 고정 정책으로 실행해 명령·궤적·오차·실패/채택 결과의 차이를 승인된 정책 변경 영향으로 보고한다. B01의 strict 실패를 재현하는 것이 새 정책의 완료 조건은 아니며, 새 정책의 성공을 미리 보장하지 않는다. 비교용 DLS fixture 채취 및 양 엔진 실행은 DataGen 구현 단계에서 새 증거에 기록한다.

미수렴·pose 진단 기준 초과만으로 candidate를 버리지 않고 안전한 candidate를 적용한다. shape/finite/limits 및 직전 적용 팔 명령 대비 >0.5 rad 점프 위반은 attempt 중단이다. Task 성공은 기존 latched StableGrasp AND Placement다. Source/Annotation·기본 Evaluation 판정은 변경하지 않는다. 과거 provenance는 원래 IK 의미를 보존하며, 다른 IK 계약의 run을 새 정책 Resume로 받지 않는다. SciPy의 다른 정합/변환 용도는 IK Solver 제외와 별개다.

## 5. 이관 순서와 완료 기준

| 단계 | 수행 | 완료 기준 |
|---|---|---|
| 0. 읽기 전용 inventory | 파일 graph·함수 호출·UI/CLI 목록·환경 version·검증 artifact 수집 | 확인/미확인 구분, 외부 의존성 목록 |
| 1. Baseline 고정 | 기존 v8 엔진별 입력/seed/초기 상태/중간 계산/기록 출력 저장 | 원본 불변, 반복 실행 변동 범위와 실제 실행 환경 기록 |
| 2. 데이터 계약/패키지 변환 | 새 Scene package 생성·SHA/경로 closure·Calibration 적용 계획 | 다른 경로에서 같은 Scene/보정 결과, 누락 참조 0 |
| 3. 순수 계산 이관 | grasp/place/reset/변환·입출력 의미 | 동일 입력 경계값·상태 sequence 비교 통과 |
| 4. Source/Annotation 양 엔진 | 공식 구성과 UI worker·영상/기록·수동 동작 | 기존 numeric/event/time 비교, 승인된 변경만 차이 |
| 5. DataGen/Evaluation | reference 연결·고정 DLS + Best Effort·budget·판정/실패 분류 | DLS 계산/안전 경계 대조·양 엔진 새 정책 trace, B01 대비 의도된 차이와 미승인 회귀 분리; Evaluation 기존 의미 유지 |
| 6. Conversion/학습/Hub/Curation | 공식 상호운용·기존 화면/기능 | 공식 CLI로 읽기/학습, 외부 Dataset 사용, 내부 기록 비종속 |
| 7. Capture/Calibration/실물 | 장치 제어·기록·설정/중지·보정 적용 | 명시 승인된 실물 시험 결과로 검증; simulator 결과로 대체 금지 |
| 8. 통합 회귀 | 전체 기능·Resume·이동·새 Task 등록 사례 | 양 엔진 v8 즉시 사용, Task 추가에 core/UI 수정 없음 |

위 순서는 기능 범위를 축소하는 MVP가 아니다. 명시적 제외 대상인 MiniVLA를 제외한 기존 필수 기능의 이관·검증이 완료 목표다. Policy 학습·추론은 공식 LeRobot과 ACT·SmolVLA 등 지원 대상에 대해 검증하며 MiniVLA 이관/호환 검증은 완료 조건이 아니다. 코드 존재만으로 기능을 완료 표시하지 않는다. 새 Task 검증은 최소 테스트 함수를 등록하는 방식이며 서랍 기능을 미리 구현하지 않는다.

## 6. 검증 매트릭스

| 대상 | 입력/경계 | 비교 / 실패 기준 |
|---|---|---|
| Transform | 비영점 부모·회전·왕복·wrist 동적 mount | 행렬/pose 오차와 단위·방향; 불명 frame 오류 |
| Calibration | encoder 분기 경계·limits·관측/명령·roundtrip·모델 mismatch | 값/예외/적용 횟수 일치; residual 이중 적용 탐지 |
| Placement | 각 꼭짓점 벽/바닥/상단 근처, speed 임계값 바로 아래/같음/위 | boolean와 height/wall/speed 중간값·엄격/포함 부등호 |
| Grasp | 접촉 해제·반복/누락 tick·0.2초 경계·drift/angle/motion 경계 | sample 창/latch와 최초 확정 tick |
| 새 배치 | 중심/바닥/편심 원점, 여러 collision part, 회전, 기울어진 frame | 작업면 거리·XY 유지·관통·footprint; 미지원 오류 |
| v8 배치 | 동일 seed/순서·3mm·1000회 소진·Fixed 오류 | 초기 pose·RNG 소비·오류/중단, 정상 Episode 보존 |
| Annotation | 저장 initial·pre/post-step·수동 mark·skip·취소 | 수치/시점·accepted bool·출력 completeness |
| DataGen | 동일 annotated input/seed·budget, 기존 DLS + Best Effort 수치, B01 SciPy + Strict 이력 | DLS/Best Effort만 이관; 수식·안전 경계 및 StableGrasp AND Placement 보존. trajectory/실패 분류 차이는 승인된 IK 변경으로 보고 |
| DataGen IK 안전·수렴 | 유효 미수렴 candidate, shape/NaN/Inf/limits/그리퍼, jump 0.5 아래/같음/위, reset/restore | 유효 candidate 적용·부적합 미적용/attempt 실패; Hold/fallback/최종 clipping 없음. DLS 반복 내부 limit 처리 유지 |
| DataGen 선택·Resume | Recipe의 과거 IK 옵션, 과거 solver/policy run·불명 identity | 선택 필드 시작 차단·UI 선택 위젯 없음, 다른 IK 계약 Resume 거부, 과거 provenance 불변 |
| Episode 저장 | 비디오 오류·disk full·cancel·worker kill·index 갱신 중 실패 | 완료 index 원본 보존, 미완료 성공 노출 0, 고아 처리 보고 |
| Resume | 같은/다른 Revision·Calibration·Task code·partition·입력 Dataset | 정확한 호환만 진행, 최신 자동 대체 0, 중복 완료 Episode 0 |
| Scene 이동 | 다른 절대 경로, 외부 증거 없음, Asset 누락/byte 수정 | 전자는 실행 가능, 필수 누락/hash 불일치는 시작 차단 |
| UI | dirty·engine 변경·잘못된 stage·로그/영상 backlog·중지 | 저장 YAML만 실행; Preview 손실이 기록 손실로 번지지 않음 |
| LeRobot | 변환 Local/Hub·외부 dataset·공식 train/resume/processor | 공식 도구 사용 가능, 불필요한 Scene 검사 없음 |
| 학습/시각화 분리 | 공식 CLI 단독 실행과 Workbench 실행, 로그 조회 켜짐/꺼짐·로그 누락/파싱 실패 | 같은 공식 config, Trainer override/hook 없음, 조회 실패가 학습 상태를 바꾸지 않음 |
| Offline Validation 독립성 | 저장된 Dataset/Policy를 별도 run으로 검증 | Training 내부/종료 후 암묵 실행 없음, 원본 Checkpoint/optimizer 변경 없음 |
| Task 등록 | 기존 입력만 쓰는 새 모듈, 이름 중복/지원 엔진 누락 | core/UI 변경 없이 연결, 미지원 시작 전 오류 |

동일 순수 계산은 exact 비교를 우선하고 dtype/연산 순서 변경으로 불가하면 사전 정의한 근거 있는 tolerance를 사용한다. 물리/영상은 seed만으로 bitwise 동일하다고 가정하지 않는다. 각 엔진의 반복 Baseline 변동을 먼저 측정한다. 엔진 간 차이는 별도 표에 남기며 한쪽 결과에 맞춰 다른 엔진 threshold를 변경하지 않는다.

## 7. 현재 검증 수준과 제한

- [B02 결과](b02-episode-resume.md): 대표 HDF5 17개 첫 Episode·612개 배열·영상/단위/관절/계약 및 원래 Resume/partition/lineage 25개 관찰을 확보했다. requested 누락·stored target/engine dtype·initial velocity 근거·opaque snapshot 소유권·수동/자동 event·seed/history/pool 순서를 구분했다. 새 Writer/변환/Resume 구현·장애/부하 회귀 시험 결과가 아니다.
- 신규 Resume는 과거 IK 누락의 기본 SciPy/Strict 대체와 code identity 미검사를 이관하지 않는다. SciPy + Best Effort도 신규 DLS와 다른 계약이며, history/identity 검증은 새 Episode 복사·commit 전에 끝낸다. 기존에 없는 Annotation/Evaluation continuation을 구현 완료로 표시하지 않는다.

- [B01 결과](b01-baseline.md): Source·Annotation 대표 실행/채택, MuJoCo DataGen 성공, Isaac DataGen 반복 strict IK 실패, 양 엔진 60 step ACT 평가 실패 기록을 확보했다. 기존 시험 29개 통과. 기존/신규 비교 또는 모든 v8 정상 동작 완료를 뜻하지 않는다. Isaac 평가 반복 차이 원인은 미확정이다.
- Reset 경계 확인: MuJoCo 후보 sampler의 1,000회와 engine pose 적용 실패는 별개이며, 후자는 재추출 없이 rollback한다. 이를 일반 Geometry 배치 재시도 의미로 자동 교체하지 않는다.

- 앞선 읽기 전용 조사에서 Workspace manifest 92개 등록 파일과 Builder export 264개 등록 파일의 해시 일치가 기록되었다. 이것은 모든 외부 참조 closure나 실행 동등성 검증이 아니다. 이번 문서 작성에서 새 패키지 hash를 계산한 것은 아니다.
- 기존 Native Source/Annotation 및 공식 LeRobot 통합 검증 artifact가 있으나 전체 Stage·실물·모든 Policy가 검증된 것으로 확대하지 않는다. 손실되거나 현재 없는 REPORT 경로는 실행 증거로 인용하지 않는다.
- v8은 실행 READY와 장면/물성 UNVALIDATED를 구분한다. 패키지 이관 성공이 실물 정합 검증 완료를 뜻하지 않는다.
- 기존 reference Mimic는 1.0.15 이식본이며 SkillGen/다중 로봇 등을 지원한다고 가정하지 않는다. 공식 body 비교와 현재 이식본의 버전 검증이 필요하다.
- 새 기능인 Geometry 기반 접촉 배치, 새 Schema, Episode별 저장, 공통 Task 등록의 양 엔진 연결은 설계만 존재한다. 구현/회귀 검증 결과가 없다.

## 8. 구현 착수 시 보고 형식

2026-10-25 [S02](s02-frames-calibration.md)에서는 S01의 파일 계약에 reference 좌표·Calibration 선언 관계를 연결했다. 138개 회귀 시험과 실제 v8 수치/경계 35개·보정 패키지 9개 검사를 통과했다. 원본과 선행 보고서는 보존했으며 새 v8 Export·실행/물리 동등성이나 보정 실행기 이관 완료를 뜻하지 않는다. 해당 근거는 RO01/Builder/각 엔진 구현 때 사용하고 후속 작업을 자동 시작하지 않는다.

2026-10-25 [B03](b03-calibration-device.md)에서 CAL-01/02·ROBOT-01/02의 기존 계산·대표 mock/코드 근거를 확보했다. 실제 활성 프로필의 saved/current URDF identity·limits-only 메모리 binding, 60개 표본·12개 거부와 v8 6관절 `R_origin × R_axis`를 대조했다. 기존 시험 75개와 Camera/Device probe 각 23개가 통과했으며 신규 장치/Calibration 구현·실물 시험은 하지 않았다.

이관 시 관측 범위와 명령 범위, raw/native/model·joint order, baked Geometry와 command 보정, raw K와 virtual K, host receipt와 exposure를 분리한다. Stop hold·일반 Disconnect torque release·readonly Calibration disconnect torque 유지를 보존한다. configure 예외의 SDK torque enable, Leader/Precision cleanup 누락·disconnect 시 port 미해제·real send 뒤 Sim 오류는 RO02/P02/P03의 실패 효과/종료 검증 항목으로 남긴다. 기존 구조의 누락을 그대로 복사하거나 이미 해결된 것으로 표시하지 않는다. B01 Isaac DataGen 실패·Evaluation 비결정성, B02 tick/frame 및 누락 정보도 그대로다.

각 기능은 확인된 기존 구현 / 새 구현 / 검증 입력 / 수치·동작 결과 / 승인된 변경과 미승인 회귀 / 차이·영향 / 미검증 범위로 보고한다. DataGen의 고정 DLS + Best Effort 변경은 승인 범위로 기록하되 성공 판정·안전 threshold를 추가 완화하지 않는다. 미승인 조건 완화·새 기본값·새 엔진 결과를 임의 정답으로 채택하지 않는다. 문서상 요구와 기존 코드의 결함이 충돌하면 차이를 먼저 보고한다.

사용자 검토에서는 먼저 전체 책임/파일 구조, 다음 Scene·Recipe·Episode 계약, 마지막 보존/검증 대응표를 확인하면 된다. 이 문서의 승인만으로 기존 원본을 수정하거나 로봇을 움직이는 작업을 시작하지 않는다.
