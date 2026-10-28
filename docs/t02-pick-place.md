# T02 — v8 Placement·StableGrasp 판정 이관

2026-10-25. 상태: **T02 순수 계산·상태 추적·명시 등록 및 오프라인 검증 완료**. [SPEC](../SPEC-task-functions.md)의 T02만 수행했다. 배치/Reset·Recipe 실행기·UI·엔진/장치 연결·새 Writer·데이터 변환을 구현하거나 실행하지 않았다. 이번 결과는 새 엔진 실행/전체 v8 이관 완료 보고서가 아니다.

## 구현과 재사용 범위

| 제품 파일 | 변경 / 필요 이유 |
|---|---|
| [pick_place.py](../robot_learning_workbench/src/robot_learning_workbench/tasks/pick_place.py) | 기존 StableGrasp 수식/상태·Placement·release/drop 및 object_metrics 계산, 일반 함수와 Episode별 tracker factory, 같은 파일의 FUNCTIONS 선언 |
| [test_pick_place.py](../robot_learning_workbench/tests/test_pick_place.py) | B01 입력/경계 및 새 호출 계약·단계별 조건·입력 오류·참조/등록 시험 72개 |
| [registry.py](../robot_learning_workbench/src/robot_learning_workbench/tasks/registry.py) | 기존 SAMPLE_FIELDS에 `grasp_inputs`, `placement_points` 두 데이터 필드만 추가. 다른 로딩/검증 로직은 T01과 동일 |
| [task_modules.yaml](../robot_learning_workbench/task_modules.yaml) | `robot_learning_workbench.tasks.pick_place`를 명시 목록에 등록. 자동 검색 없음 |
| [pyproject.toml](../robot_learning_workbench/pyproject.toml) | 개발 패키지 0.2.0, 직접 쓰는 NumPy>=1.26,<2 명시. 기존 설치 NumPy1.26.0을 사용했으며 설치/환경 변경 없음 |

기존 P `real2sim/workspaces/grasp.py`의 수식과 상태를 이관했다. `observe(tick, relative, relative_quat, ee_position, object_position, left, right)`의 AST는 기존 `update`에서 메서드 이름만 바꾼 것과 동일하다. 새 `update(sample)`은 입력/phase·Episode 소유권을 확인하고 그 수식을 호출한다. 별도 Tracker Adapter/ABC나 상태 manager를 만들지 않았다.

P `simulation/mujoco_backend.py:success_details`와 `real2sim/workspaces/environment.py:task_success_details`의 순수 판정을 보존했다. 엔진 loader·IK·기존 workflow의 미완성 실행 구조는 가져오지 않았다. `release_evidence`와 `workflow/tasks.py:object_metrics`는 일반 계산 함수로 유지한다. 후자는 상태 dict를 호출자가 소유하며, Evaluation 성공 조건을 대신하지 않는다. MiniVLA 코드/호환 기능을 이관하지 않았다.

## 보존한 계산과 상태

- StableGrasp: 양측 접촉, 상대 drift <=0.006m, 상대 회전 <=10°, 창 안 EEF/물체 순이동 각각 >=0.005m, `(N-1)*dt + 1e-9 >=0.20s`다. 크기·힘의 크기·gripper release 조건을 추가하지 않았다. 기존 size 인자는 원래처럼 판정에 쓰지 않는다.
- 같은 tick 재호출은 창/진단을 새로 누적하지 않는다. tick 누락은 창을 비우고, drift/회전 초과 시 오래된 sample부터 제거하며, 완료 latch는 접촉 소실/진단 drop 이후에도 유지한다. sample은 원래처럼 float64 소유 copy로 보관하고 평가 후 창 크기를 제한한다.
- Placement: `inverse(T_target) @ T_object`, 기존 치수의 8꼭짓점, 높이별 컵 내부 반경/벽 두께, radial excess <=0.001m, 바닥 `>`/상단 `<`, 선속력 `<0.03m/s`를 보존했다. inside_region은 target-local bounds의 inclusive 판정이다. 판정용 치수를 Collision Geometry로 바꾸지 않았다.
- NumPy는 기존 곱/역행렬/연산 순서와 float64 경로를 유지한다. Tensor 입력은 기존 Torch 연산과 입력 dtype을 유지한다. 특히 float32 속도 임계값은 **Tensor에서 비교한 뒤** bool/진단 수치로 꺼낸다. float32(.03)를 Python float와 비교해 결과가 달라지는 회귀를 차단했다.
- release/drop 진단과 approach/transport/full_task_success 계산을 유지한다. transport는 기존 `>.04m`, 선택 정확도는 단일 물체에서 N/A다. 이 지표를 기본 Evaluation 성공의 추가 gate로 쓰지 않는다.

## 호출·Scene·등록 계약

일반 함수 `numpy_corners(object_pose, target_pose, dimensions_m)`와 `placement_details(points, linear_velocity, geometry, ...)`가 실제 계산을 제공한다. NumPy/이미 설치된 Torch Tensor 수치 입력을 받으며 엔진 API·Scene 객체·Writer를 감싸지 않는다. Torch는 Tensor 계산 때만 import하며 기본 모듈 등록에는 필요 없다. 실제 Isaac pose→corner 계산은 후속 엔진 binding에서 공식 math API를 사용해야 한다.

T01의 검증 가능한 입력 필드 두 개를 구체화했다. 이는 새 계층이 아니라 **기존 엔진 중간값을 재계산/정규화하지 않고 전달하기 위한 TaskSample 데이터**다.

| 입력 | 계약 |
|---|---|
| `grasp_inputs` | object_id, relative(EEF-local m), relative_quat, quaternion_order(wxyz/xyzw), ee_position/object_position(같은 위치 좌표계 m). 기존 계산에 전달된 수치/dtype/Quaternion 순서를 그대로 제공. 실제 B01 단계 trace는 모두 update_contact_grasp의 SciPy xyzw이며, 별도 native MDP term의 wxyz와 엔진 이름만으로 혼동하지 않음 |
| `contacts` | left/right measured bool, source_definition. `mujoco_body_pair_dist_le_0`, `isaac_contact_sensor_gt_1e_4_n`, `isaac_direct_contact_view_gt_0_01_n`을 구분. Episode 안에서 정의/Quaternion 순서 변경 거부 |
| `placement_points` | `{object_id: {target_id, points: 8x3}}`. 지정 target-local 좌표의 기존 꼭짓점과 native dtype. 다른 target에 대한 points나 누락 입력은 오류 |
| `linear_velocities` | Object ID→기존 world 선속도 3-vector(m/s). 서로 다른 dtype/device를 맞춘다는 이유로 조용히 cast하지 않음 |

기존 TaskSample의 tick/phase/dt_s/episode_id/env_index를 사용한다. 위 배열 추출·Quaternion/엔진 카메라 변환·접촉 센서/바디 lookup 구현은 하지 않았다. actual engine state를 다시 뽑지 않은 값으로 live 검증 완료를 주장하지 않는다.

`GraspParams(object)`와 `PickPlaceParams(object,target,relation,max_speed_m_s,bounds_m)`를 선언한다. object/target은 T01 Scene 참조 검사를 사용한다. 기존 모듈 `validate_params(params, scene)` hook은 이미 읽기 전용인 Scene의 object별 **task_geometry**에서 dimensions_m, wall_m, bottom_diameter_m를 확인해 immutable PlacementGeometry를 private `_geometry` cache에 연결한다. `_geometry`는 dataclass 입력 필드가 아니므로 YAML/호출자 입력으로 주입할 수 없다. 기준 Metadata·파일·Calibration을 수정하지 않으며 사용자 Recipe에 Geometry 복사를 요구하지 않는다. 보정/Transform 계산을 재실행하는 hook도 아니다.

FUNCTIONS의 6개 이름은 `pick_place.stable_grasp`, `pick_place.placement`, `pick_place.v8_metrics`, `pick_place.v8_annotation`, `pick_place.v8_datagen`, `pick_place.v8_evaluation`이다. 반환값은 일반 bool/metrics 또는 immutable SignalValue snapshot이다. `create_stable_grasp(*,params,episode)`가 Episode/env마다 새 상태를 만든다. 잘못된 live 입력은 TASK_SAMPLE_INVALID로 구분하며 정상 Task 실패 False와 혼동하지 않는다.

- Annotation/DataGen: post-step tracker, pre-step 수치/영상/이전 latch 저장, 최종 물리 통과는 **Placement AND latched StableGrasp**다. acceptance는 episode_end의 실제 최종 상태를 사용한다.
- 수동 Annotation: 위 함수는 물리 통과 구성요소다. 기존 manual mark 유효성·사용자 채택과 final place의 마지막 action 표시 규칙은 기존 단계 실행/Writer의 책임이며 제거하거나 새로 구현하지 않았다.
- Simulation Evaluation: 기본 종료는 **Placement**다. grasp/transport/full_task_success는 별도 계산/지표다. 실제 지표 연결은 P01에서 검증한다.
- Source 및 Real Evaluation에는 이 함수들을 성공 gate로 등록하지 않았다. Source의 recording_only 및 실물 human-review 의미를 유지한다.

binding은 post_step/pre_step/episode_end와 named grasp provider를 선언할 뿐 실행하지 않는다. Recipe의 명시 grasp 설정 또는 acceptance-only dependency에 object 파라미터를 공급하고 동일 tracker를 공유하는 전체 준비 로직은 R02/해당 stage에 남는다. T02는 새 tracker를 매번 acceptance 안에서 만들거나 필수 입력을 기본 성공값으로 채우지 않는다.

## 검증 결과

| 검증 | 실제 결과 |
|---|---|
| 신규 Task 시험 | **72 passed**, skip 0. B01 StableGrasp 15 sequence·Placement 13 snapshot, region/속도/회전·gap/latch/소유 copy, 단계별 truth table·입력/등록/Scene 계약 |
| 전체 회귀 | **307 passed**, skip 0 = 기존 Scene 138 + 등록 97 + T02 72. [JUnit](evidence/t02/unit-tests.xml), [로그](evidence/t02/logs/15-final-suite.log) |
| 실제 B01 grasp trace | **2,618회** update의 bool·진단 dict·sample 창 값이 기존 클래스 및 저장 trace와 exact 일치. 13개 실행 trace와 Source 2개를 확인. [결과](evidence/t02/baseline-comparison.json) |
| 실제 B01 NumPy Placement | 실제 고정 목표 pose와 저장된 물체 pose·속도의 13개 경계에서 boolean·speed·radial excess exact 일치. 이론상 경계 이름으로 기대값을 바꾸지 않음 |
| 기존 Torch 판정 CPU 대조 | 기존 함수/공식 math body의 float32 13개 fixture에서 boolean·speed/radial 중간값 exact 일치. 원래 Isaac GPU 실행을 재현한 시험은 아님 |
| 접촉·평가 진단 | B01의 9개 접촉 threshold fixture가 새 tracker에서 같은 결과. NumPy/Torch threshold를 통일하지 않음. transport .04m 아래/같음/위와 지표 의미를 기존 함수와 대조 |
| wheel | [build.json](evidence/t02/build.json). 소스/설정 비교·compile·임시 해제본의 isolated import·6개 등록/factory·latch smoke 통과. 기존 환경에 설치하지 않음 |
| 원본/기존 증거 | [보존 대조](evidence/t02/preservation-after.json): 56,100개 파일 stat 및 선택 15,022개 SHA 변화 없음. 전체 corpus/SDK binary 전수 byte 증명은 아님 |
| 추적 | [commands.json](evidence/t02/commands.json), [verification.json](evidence/t02/verification.json): 실행 환경·실제 명령·input/source/evidence SHA·작업 경계 |

B01 대응: Annotation MuJoCo post tick **222→저장 frame223**, Isaac **221→222**, MuJoCo DataGen **231→232**를 실제 저장 HDF5와 비교했다. 각 pre-step grasp 배열 전체가 새 tracker를 post-step에 갱신하기 전 snapshot과 exact 일치했다. 초기 실패 Annotation과 Isaac DataGen의 2 step 미완료 trace도 성공으로 바꾸지 않았다. B01 Evaluation 두 반복은 각각의 기존 입력과 따로 대조했으며 반복 간 차이를 없애지 않았다.

오프라인 reference에 NumPy1.26.0/Torch2.7.0+cu128(CPU Tensor만 사용)/SciPy1.15.3/h5py와 Python3.11.15를 사용했다. SciPy는 증거 harness의 Quaternion 변환 전용이며 제품 의존성/IK로 추가하지 않았다. 기존 Sim5.1/Lab2.3/LeRobot0.4.1/MuJoCo3.3.7 환경은 그대로다. 엔진/장치 실행, 설치/업그레이드·환경 분리·새 Policy 실행은 하지 않았다. 별도 lint/type 도구는 설정/설치되어 있지 않아 실행했다고 주장하지 않는다.

## 시험 중 수정한 입력·도구와 남은 한계

- 초기 grasp 시험은 contact가 없는 sequence의 진단 hold_seconds=0을 dt로 잘못 읽었다. B01 harness에 명시된 dt로 수정했고 원본·fixture·수식을 바꾸지 않았다.
- 초기 Placement 시험은 center의 **블록 pose**를 target pose로 간주했다. set-pose Quaternion 왕복 때문에 radial 진단에 약 1e-16 차이가 났다. B01의 실제 target snapshot을 사용한 뒤 13개 exact 일치했으며 tolerance를 늘리지 않았다.
- probe에서 Evaluation Isaac의 Quaternion 순서를 엔진 이름으로 분류하던 표시를 실제 update_contact_grasp 호출 근거에 따라 xyzw로 수정했다. raw 배열·기대값·판정 수식은 바꾸지 않았으며 별도의 native MDP wxyz 경로와 구분한다. 초기 harness도 보존했다.
- 기존 Isaac 함수는 corners를 기본 float32로 만든다. float64 pose를 넣은 시험 harness는 dtype mismatch로 실패했다. 기준을 수정하지 않고 실제 float32 경로로 대조했다. GPU/PhysX/Fabric의 원시 quaternion/force buffer 전체는 B01에 없으므로 이 CPU fixture를 live 동일성으로 확대하지 않는다.
- registry의 source hash는 실제 소스 파일을 읽는다. wheel ZIP을 직접 sys.path에 넣은 첫 smoke는 이 조건 때문에 실패했다. 정상 설치와 같은 파일 형태로 **증거 디렉터리 안에서만 임시 해제**해 시험했다. direct zipimport의 Task source identity는 지원하지 않으며 zip loader/Wrapper를 추가하지 않았다. 실패 로그도 보존했다.

T02는 task-functions-AC01의 **순수 수식·상태/경계 및 저장 phase 대조**, AC03의 실제 v8 함수 등록 부분을 완료했다. 실제 엔진에서 native 중간값을 추출하고 기존 dt·접촉 branch·MDP 호출 횟수/시점을 유지하는 검증은 E01/E02/E04/E06/P01에 남는다. 새로운 contact extractor/engine binding·multi-env reset 연결을 검증한 것은 아니다. placement/reset AC02와 전체 플랫폼 완료를 표시하지 않는다.

기존 성공 의미·Threshold·Calibration/Quaternion 곱을 의도적으로 변경하지 않았다. 새 입력 검증·명시 등록·중간값 전달 필드/target identity·Scene task_geometry binding은 새 호출 계약이다. B01의 Isaac DataGen 실패/Evaluation 비결정성, B02의 누락/Resume/IK identity, B03의 실물/검증 상태는 그대로다. 신규 DLS + Best Effort 및 배치·Recipe·UI·엔진 연결은 미착수다.

`incremental-implementation`과 `test-driven-development`를 적용했다. 스킬의 별도 definition-of-done.md는 이전 확인과 같이 가용 위치에 없어 읽었다고 주장하지 않으며 SPEC·테스트·빌드·보존 대조로 범위를 검증했다. Git 저장소가 아니므로 초기화/commit은 하지 않았다. **T02만 완료하며 다음 작업은 시작하지 않는다.**
