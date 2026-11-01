# 새 SO-101 Scene 제작과 Workflow 연결

기존 Project/Scene을 덮어쓰지 않고 새 Builder Project와 Export Revision을 만든다. 실제 촬영·모터 동작은 사용자의 현장 조작이다. 이 안내의 명령은 제작 API 사용 예시이며 자동 실행되지 않는다. 이번 변경은 소스 구현만 수행했으며 UI·엔진·하드웨어 실행으로 확인하지 않았다.

**두 화면의 역할:** Scene Prepare는 완성된 Scene이 없는 새 Project에서 초기 Input·메모·실측 Snapshot을 모으는 단계다. 기존 Project는 명시적으로 열 때만 복원한다. Real/Sim은 제작한 Scene의 정합을 반복하는 단계다. 두 화면의 아래 목록은 이번 연결에서 촬영한 결과만 표시하며, 종료 후에도 유지하고 다음 실행을 시작하면 화면 목록만 비운다. Project를 열 때 과거 Capture를 일괄 표시하지 않는다. 오른쪽 Input 목록은 직접 추가한 자료이며 Capture 이력과 섞지 않는다.

새 촬영은 `input/captures/<실행 ID>/<Capture ID>/`에 모으며, model 미결합 Camera/SDK 자료는 `input/observations/<실행 ID>/<관측 ID>/`를 사용한다. Builder는 같은 Project가 이미 소유한 Capture를 그 자리에서 등록한다. 기존 폴더는 이동·삭제하거나 새 형식으로 변환하지 않는다.

Real/Sim은 **Capture한 관측만 촬영 결과로 저장**한다. 연결·Teleop 후 Capture 없이 정상 중단하면 해당 실행의 렌더 임시 폴더와 임시 Recipe를 정리한다. Real/Sim의 자동 Teleop Native Dataset 저장 경로는 제거했으며, 제어 진단은 최근 300행만 메모리에 유지한다. 오류·미완료 Capture가 있으면 진단과 원 관측을 보존한다. 기존에 저장한 실행은 삭제하지 않는다. R03의 숨김 실행/명령 이력은 촬영 자료와 별도로 유지한다.

실제 SDK 통신 중에는 관측 캐시 잠금을 잡지 않는다. Scene Prepare/RealSim은 제어 스레드가 게시한 측정 이력을 소비하므로 화면·저장 지연을 실제 관절 측정 누락으로 대신 판정하지 않는다. 실제 제어 deadline·Stop·포화/Encoding·관측 age/skew 검사는 유지한다. Pair 촬영은 같은 측정 q의 Sim 렌더와 Real Snapshot 저장을 병렬로 시작하고 두 결과가 준비된 뒤 기존 Reader·Builder 등록을 수행한다. Live 렌더 IPC는 중복 이미지 읽기와 디스크 fsync를 생략하는 임시 자료이며, Capture 게시·Manifest/SHA 및 R03 ACK의 기존 저장 계약은 유지한다. 이 변경의 실물 안정성·처리 시간은 아직 실행 확인하지 않았다.

Workspace Pipeline의 **Real 메뉴는 Real Evaluation 한 항목**이다. 중복된 Teleoperation·Scene Prepare·Precision·Real/Sim 진입 메뉴와 Fake/Gripper 전용 UI 코드는 제거했다. Scene Prepare·Real/Sim·Precision은 각각 상단 작업 탭을 사용한다. Real Evaluation의 현재 실행기는 실제 관측 Policy 추론이며, 자율 실물 모터 Rollout이 구현됐다는 뜻은 아니다.

Precision 화면은 **Precision 파일 선택 → 연결·선택 로봇 전체 토크 해제 → 기준 자세 기록·자동 계산 → 저장·자동 적용** 순서다. 화면을 열거나 준비 검사만 할 때는 포트를 열거나 토크를 바꾸지 않는다. 사용자가 연결 버튼을 누르면 선택한 Leader 또는 Follower의 6축 Torque를 해제하고 readback을 확인하며, Goal이나 Torque Enable은 보내지 않는다. 로봇을 지지한 상태에서 연결해야 한다. 종료할 때 토크를 자동으로 켜지 않는다.

기준각을 0°로 기록하면 그 자세가 0°가 되고, 13°로 기록하면 그 자세가 13°가 된다. 한 자세는 기존 SDK 스케일을 사용한 영점 보정이며, 여러 자세는 기존 `fit_joint` 계산으로 기울기와 기준각을 맞춘다. 계산한 관절은 `CALIBRATED_MANUAL / physical_verified=false`로 저장하고 계수·관절·Model·SDK identity를 다시 확인한다. 별도 자세 검증이나 보정 적용 버튼은 없다. 사용자가 보정하지 않은 다른 관절 값은 유지한다.

**저장**은 선택한 Workspace Precision JSON을 교체하고, **다른 이름으로 저장**은 새 Precision JSON을 만든다. 둘 다 사용 장치 구성에 자동 반영되며, 새 구성이 필요하면 기존 구성에 정확히 연결된 Project Binding도 갱신한다. 기존 파일 bytes는 `calibration/history/<SHA>.json`에 보존한다. Workspace의 devices/calibration 밖 파일·SDK 보정 파일·닫힌 Scene Package를 덮어쓰지 않는다. Scene Package의 기존 Mapping identity를 자동으로 바꾸거나 새 물리 Calibration을 승인하지 않는다.

**Codex가 Builder를 사용하는 방법:** 사용자는 Scene Prepare에서 만든 Project 경로와 제작 요구사항 Markdown을 Codex에 전달한다. Codex는 파일·이미지와 `input/evidence.yaml`에 등록된 메모를 읽고, 이 저장소의 `real2sim_builder` Python API 또는 CLI를 호출한다. 별도 Workflow Scene 화면을 열 필요는 없다. 그 화면과 전용 검사/GUI 실행 코드는 제거했으며, 실행 단계는 각자 선택한 Scene Package를 기존 Recipe/R03 경로에서 검사한다.

예를 들어 다음은 Codex가 기존 Project 내용을 조회하고 첫 작업 후보를 만드는 실제 CLI 형식이다. 준비된 Builder Python 환경에서 실행하는 예시이며, 여기서 실행한 명령은 아니다.

```bash
python -m real2sim_builder.cli inspect /path/to/my-first-scene
python -m real2sim_builder.cli candidate /path/to/my-first-scene create initial-scene
```

첫 후보는 Current Scene이 없으면 빈 Scene에서 시작한다. Codex가 물체·좌표·카메라·물성을 정리해 `Candidate.edit`/`Candidate.save`로 작성하고, Builder의 렌더·평가·승격·Export를 호출한다. Builder는 입력 소유권·Scene 스키마·Revision·파일 무결성과 Export를 처리한다. Markdown을 이해하고 어떤 수정을 할지 판단하는 주체는 Codex이며, Builder에 프롬프트만 주면 완성 Scene이 나오는 단일 명령은 없다. 사진만으로 확정할 수 없는 치수·Camera/Base 보정은 추가 근거를 요구하거나 estimated/unknown으로 남긴다.

제작한 Scene을 Real/Sim에서 비교한 뒤에는 새 Capture 폴더와 수정 지시를 Codex에 전달한다. Codex는 같은 Project에서 다음 Candidate를 편집하고 새 Export Revision을 만든다. 원 촬영 자료와 기존 Export는 보존한다. 사용자 작업 순서는 **Scene Prepare 자료 준비 → Codex의 Builder 제작 → Real/Sim 비교 → Codex의 Builder 수정**이다.

1. **자료 준비:** 사진/영상, GLB·Mesh, 물체별 실측 치수(m), 역할, Robot Base 위치, SO-101 URDF와 Mesh closure, Side/Wrist Intrinsic·Extrinsic·해상도, 필요하면 Capture/Snapshot을 준비한다. 미측정 값은 estimated/unknown으로 구분한다.
2. **Builder 입력:** Scene Prepare의 새 Project에 사진/영상·GLB·치수/카메라 Metadata·Robot Model·Capture와 메모를 저장한다. Codex는 이 Project를 Builder로 열어 사용한다. `add --kind robot`은 URDF closure와 모델 정보를 Project가 소유하도록 저장한다. 관측자료만 등록한 상태와 Reconstruction 가능한 보정자료를 구분한다.
3. **Scene 작성:** `working/current_scene.yaml` 또는 Candidate 편집 API로 Object·Frame·Geometry·물성·카메라를 정의한다. 동적 물체에는 양수 질량을 선언한다. 관절은 SO-101 6축 이름/순서, rad 단위를 유지한다. Camera를 wrist link에 부착하려면 해당 `robot_link_*` Frame을 명시한다.
4. **검토/보정:** Candidate Render·Real/Sim Pair·Landmark/Mask·측정 자료로 비교하고 Builder의 Review/Validation/Promote를 수행한다. Pixel 차이를 물리 Calibration 정확도로 간주하지 않는다. Precision은 SDK Encoder 보정과 별도이며 런타임 q offset을 추가하지 않는다.
5. **실행 자산:** MuJoCo는 선언된 URDF로 현재 SO-101 Position Servo 모델을 구성하거나, 관절·Position Actuator·물체 Free Joint·EEF Site·Camera를 포함한 전체 MJCF를 제공한다. Isaac은 Articulation/Collision/관절 물성이 있는 SO-101 USD를 제공한다. Builder의 정적 Robot reference USD를 실행 Articulation으로 대체하지 않는다.
6. **Export:** 기존 Export API/CLI/UI로 새 경로에 게시한다. UI의 실행 USD·전체 MJCF·Calibration 경로는 선택 사항이며, 선언하지 않은 실행 모델/보정은 자동으로 만들어 넣지 않는다. 성공한 Export는 Project의 Real/Sim 목록에 자동 등록된다.

```bash
python -m real2sim_builder.cli export /path/to/project \
  --destination /path/to/project/exports/revision-001 \
  --calibration /path/to/calibration.json \
  --isaac-robot-asset /path/to/articulated-so101.usd
```

전체 실행 MJCF를 소유하려면 `--mujoco-robot-asset /path/to/environment.xml`을 추가한다. 미검증 Candidate의 Review Export는 사용자가 명시한 `--candidate ID --allow-unvalidated`로 구분한다. Export 등록만으로 실제 장치나 Simulation을 시작하지 않는다.

```text
project/
  project.yaml
  input/                    # 소유 사진·Scan·URDF closure·실측 근거
  working/current_scene.yaml
  scratch/agent/<candidate>/
  exports/revision-001/
    scene.json
    calibration.json
    manifest.json
    authored_scene.json     # Package 내부 경로로 재배치된 Builder Scene
    provenance.json
    scene.xml / scene.usda
    assets/...
  configuration/            # Revision별 Real/Sim 정적 렌더 설정
```

**Workflow 엔진 설정은 물리 실행 설정이다.** Real/Sim의 `render_type: authored` 설정을 Source 물리 실행 설정으로 사용하지 않는다. Source용 `engine_config`에는 `initial_joint_rad` 6축 초기 자세와 `active_object_ids`를 선언한다. 물성은 Scene에서 읽고 필요하면 `object_physics`로 명시한다. Isaac의 새 Scene에는 v8의 `baseline_metadata`가 필요하지 않다. 선택 엔진의 자산·URDF·카메라가 실제로 존재해야 한다.

MuJoCo의 전체 MJCF를 직접 사용할 때 `robot_base_body`, `eef_site`, `finger_bodies`를 engine config에 선언할 수 있다. 초기 Robot Base는 Scene Frame과 같아야 한다. StableGrasp처럼 접촉을 소비하는 Task에는 두 Finger Body가 필요하다. 일반 Task에 이 접촉 입력을 강제하지 않는다.

**Source Demo:** Scene 이름 또는 `project.yaml`이 있는 최상위 Project 폴더와 상단 MuJoCo/Isaac을 선택한다. 선택 엔진에 가장 최근 등록된 실행 Revision과 Scene에 연결된 Leader 구성을 자동으로 해석한다. 원래의 Leader/Encoder/모델·Scene 계약과 파일 무결성 검사는 유지한다. 물리 실행 자산이 없는 Project나 비교용 정적 렌더만 있는 Project를 Source 실행 Scene으로 승격하지 않는다. Follower나 실제 Camera는 Source에서 연결하지 않으며, Side/Wrist는 선택 Scene의 Simulation Camera다.

오른쪽은 기본값이 채워진 흰색 YAML Script 편집기와 **Recipe 불러오기 / 저장 및 적용**이다. Script 기본 저장 폴더는 `workbench_runs/scripts/source/`이며 파일명을 표시하고 전체 경로는 툴팁으로 제공한다. 저장 및 적용은 파일 이름을 고르는 창을 열고 저장·입력 준비를 한 번에 수행한다. 별도 검사 버튼·새 출력 버튼·Source 입력 방식·장치 Profile·엔진 설정 파일·숫자 폼은 없다. Script를 불러오면 저장 없이 실행 준비를 수행한다. 준비 결과가 없는 저장 파일도 데모 기록 시작에서 준비 후 실행한다. YAML을 수정했을 때만 저장 및 적용이 필요하다. 준비 완료만으로 장치/Simulation을 시작하지 않는다.

```yaml
schema_version: 1
stage: source
engine: mujoco
inputs:
  scene: /path/to/workbench_runs/scenes/my-first-scene
execution:
  seed: 1047
  env_num: 1
  num_episodes: 10
  episode_time_s: 60.0
  reset_time_s: 0.0
  resume: false
output:
  directory: /path/to/workbench_runs/source/my-demonstrations
objects: {}
functions: {}
```

`output.directory`는 Episode Dataset 경로이며 Script 저장 경로와 별개다. 같은 Dataset에 추가 수집하려면 이 경로를 유지하고 `resume: true`로 저장·적용한다. `num_episodes`는 이번에 추가할 저장 Episode 수다. 현재 실제 Leader 수집은 `env_num: 1`이며, 기존 수치 Stream의 다중 환경 실행을 독립 Live Leader 입력 지원으로 표시하지 않는다. UI의 Replay 입력과 구형 Source 폼/전용 실행 연결은 제거했다. 기존 명시 CLI의 수치 Stream 수집 API와 보존 Dataset Reader는 독립 기능으로 유지한다.

Live Source의 녹화 종료는 `ceil(episode_time_s × 30)` 프레임 제한과 실제 경과 시간 제한 중 먼저 도달하는 조건이다. 렌더가 느리면 20초 동안 600프레임보다 적게 수집될 수 있다. 저장 영상과 관측 시각은 30Hz의 Simulation tick 기준이므로 실제 촬영 소요 시간과 다를 수 있다. `reset_time_s`는 Episode 사이 실제 대기 시간이다. 이번 변경에서는 이 시간 계약을 변경하지 않았다.

`pickplace_colorblock`에서 빨간 큐브만 Marker 작업 영역 안에 랜덤 배치할 때는 아래처럼 `objects` 전체를 지정한다. 지정하지 않은 파랑·초록 물체는 Scene 초기 상태를 유지한다. Workspace 함수는 기존 충돌 형상·기울어진 Support·24mm 표면 간격 검사를 사용한다. `placement.random_xy`의 과거 v8 수평면 계산을 이 함수로 묵시적으로 바꾸지 않는다.

```yaml
objects:
  cube_red:
    placement:
      function: placement.random_workspace
      params:
        frame: object_marker
        support: table
        workspace: marker
```

영상 영역에서 RIGHT는 저장/다음 배치, LEFT는 폐기/같은 물체 초기 상태·속도 복원, Q/중단은 미완료 Episode를 버리고 종료한다. Script 편집 영역의 화살표는 글 편집에 사용한다. 저장 자료 재생은 Data Curation에서 한다. 기존 구체 엔진 Runner·Native 저장·Resume 계약을 사용하며 이번 UI 변경에서 물리 Step/Reset/Task 판정을 수정하지 않았다.

**Task 함수:** 신뢰하는 Python 모듈을 `task_modules.yaml`에 추가하고 기존 `FunctionSpec`으로 Params dataclass·단계·필요 Sample 필드를 선언한다. YAML의 `functions.signals`, `acceptance`, `success`, `metrics`에서 함수를 선택한다. Predicate/Acceptance는 `bool`, Tracker는 기존 Signal 계약, Metric은 유한 수치를 반환한다. 새로운 Placement도 기존 `PlacementRequest`/`PlacementResult`와 Frame/Support 계약을 사용한다. 서로 다른 물체에 Fixed/Random/사용자 함수를 섞어 선언할 수 있다.

**후속 단계:** Source → Annotation(원 초기 상태·적용 Target Replay) → DataGen → Curation → 공식 LeRobot Dataset → 공식 Policy 학습 → Simulation Evaluation. 다른 엔진에서 Annotation하려면 해당 엔진 config를 명시한다. 이 경로는 Replay 시도를 허용할 뿐 물리 결과 동등성을 뜻하지 않는다.

Mimic은 기존 물체 기준 Pick & Place 생성기다. 다른 Acceptance 함수는 연결할 수 있지만 궤적은 기존 알고리즘이다. Acceptance Params에 object/target이 없으면 `execution.mimic_object`/`mimic_target`으로 명시하고, Annotation에 필요한 grasp 경계가 실제 기록돼 있어야 한다. 일반 Task 성공 함수만 바꾸어 임의 동작의 Mimic 지원을 주장하지 않는다.

실물 Teleoperation은 Scene Prepare의 **텔레옵 시작** 버튼 또는 **Real/Sim 연결 · Teleop** 동작으로 바로 시작한다. 별도 체크리스트·승인 팝업·제안 SHA 전달 단계는 없다. 연결만 하는 Capture 버튼은 관측으로 시작하며, 화면 열기·설정 복원만으로 구동하지 않는다. 시작 명령을 받은 Worker가 현재 장치/보정·Position Mode·Feedback·목표를 확인하고, 미구동 축에 인코딩된 Leader 목표를 설정한 뒤 Torque를 켠다. 따라서 시작 시 실제 Follower가 움직일 수 있다. 측정값은 그대로 보존하며 실제 목표만 기존 model/motor/Precision 교집합으로 제한한다. SDK Encoding·Watchdog·Stop/Cancel과 중단 시 Torque 유지 정책은 유지한다. 이번 변경으로 실기 동작을 확인한 것은 아니며, 자율 Follower Policy Rollout은 아직 구현하지 않았다.

Scene Prepare의 기본 조작은 **로봇 연결 → 텔레옵 시작 → 캡처 → 종료**다. 종료는 Teleop 제어·카메라·장치 연결과 해당 Session Worker를 정리하고 저장된 Snapshot은 유지한다. 촬영 대기는 화면에 짧게 표시하며 시간 정합·안정성의 상세 진단은 기존 결과/로그에 남긴다. Real/Sim의 Scene 목록 조회는 JSON 계약·Manifest를 확인하며 USD SDK나 엔진을 초기화하지 않는다.
