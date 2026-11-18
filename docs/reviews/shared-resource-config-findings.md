# 공유 자원 조사 보충: Device·Precision·Camera·Runtime

조사일: 2026-11-17. 대상은 feat/simfoundry-style-reconstruction의 현재 작업 트리다. 시작 시 다수의 수정·미추적 파일이 있었으며 구현 파일은 변경하지 않았다. 이 문서는 소스와 workbench_runs 메타데이터의 읽기 조사다. 테스트, 모델 추론, 시뮬레이터, 장치 연결, 외부 soarm_isaaclab 체크아웃, 인증 파일은 실행하거나 읽지 않았다.

## 자원군별 요약

| 자원군 | 현재 선택·소유 경로 | 갱신 범위와 고정 경계 | 판단 |
|---|---|---|---|
| Device 구성 | workspace/devices/<이름>/capture.yaml을 Project의 device_configuration.path+sha256으로 선택 | 등록은 새 폴더를 만들고, Project는 recipe 파일 SHA를 확인한다. 실행 준비 때 recipe가 참조한 파일도 개별 고정한다. | 중앙 선택은 이미 있다. 전이 의존성의 현재값과 Project에 저장한 recipe SHA를 구분해서 보여줄 필요가 있다. [D1](../../robot_learning_workbench/src/robot_learning_workbench/robot/registration.py#L32), [D2](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L407) |
| SDK 보정·Precision | follower/leader.json → SDK calibration_path, capture.yaml → 별도 Precision JSON | SDK 보정 생성은 기존 파일을 거부한다. Precision은 같은 파일 덮어쓰기 또는 Save As가 가능하며, 이전 profile을 history에 보존한다. Save As는 같은 구성을 공유한 Project들을 자동으로 새 구성으로 옮길 수 있다. | SDK 보정, raw→model 매핑, 실행 Snapshot은 다른 자원이다. 공유 저장의 영향 범위가 가장 직접적인 관리 위험이다. [P1](../../robot_learning_workbench/src/robot_learning_workbench/robot/sdk_calibration.py#L7), [P2](../../robot_learning_workbench/src/robot_learning_workbench/robot/precision_storage.py#L18) |
| 실제 Camera stream | Device의 cameras.json: USB 경로·해상도·fps | 같은 로봇을 다시 선택해도 새 cameras.json을 만들며 Capture는 이를 읽어 Side/Wrist를 구성한다. | Camera 하우징 Mesh·광학 K·Mount·World와 별개다. 이름이 같은 capture/calibration/cameras.json과 합치면 안 된다. [C1](../../robot_learning_workbench/src/robot_learning_workbench/robot/registration.py#L59), [C2](../../robot_learning_workbench/src/robot_learning_workbench/robot/session_devices.py#L59) |
| 광학·Hand-eye·World 정합 | Builder Scene/후보의 cameras, frames, view_registrations; Export의 scene.json·authored_scene.json | 정합은 후보 값을 바꾸고 registration을 signature에 묶는다. Package·Capture는 해당 시점 값을 보존한다. | Revision별 K/Mount 차이는 정상이다. USB 물리 센서 선택과 optical/mount identity 연결은 현재 확인한 경로에서 약하다. [C3](../../real2sim_builder/src/real2sim_builder/scene.py#L45), [C4](../../real2sim_builder/src/real2sim_builder/observations.py#L81), [C5](../../real2sim_builder/src/real2sim_builder/export.py#L253) |
| 모델 Runtime·Provider | SimFoundry: 명시 config 또는 Project 입력, 그 위에 Workspace runtimes를 기본값으로 병합 | Project/명시값이 우선한다. runtime identity·stage config·파일 SHA는 stage attempt에 보존한다. Candidate reconstruction-config.yaml은 최초에만 기록한다. | 여러 파일이 모두 현재 권위인 것은 아니다. 실제 선택 결과와 각 키의 출처를 보여주는 작은 개선이 유효하다. [R1](../../real2sim_builder/src/real2sim_builder/automation.py#L327), [R2](../../real2sim_builder/src/real2sim_builder/stage_runtime.py#L40), [R3](../../real2sim_builder/src/real2sim_builder/automation.py#L42) |
| Codex 모델·가이드 | UI의 공통 QSettings → 실행 프로세스 환경변수 → 기존 authoring 호출 | 모델/effort는 YAML 모델 설치 설정과 별도다. 호출 폴더에는 실제 runtime.json과 복사한 가이드를 보존한다. | 현재 선택과 과거 호출의 모델 기록을 구분해야 한다. 기존 Geometry 재사용은 모델 선택 변경만으로 반드시 무효화되지 않는다. [X1](../../real2sim_builder/src/real2sim_builder/ui_reconstruction.py#L221), [X2](../../real2sim_builder/src/real2sim_builder/ui_reconstruction.py#L291), [X3](../../real2sim_builder/src/real2sim_builder/authoring.py#L1237) |

## 1. 공유 Device 구성: 이미 중앙화됐지만, SHA의 범위와 공유 저장 범위가 다르다

현재 실제 Project 세 개가 모두 ../../devices/so101-pickplace/capture.yaml을 선택한다. 세 Project의 저장된 바인딩 SHA는 조사 시점 capture.yaml의 실제 SHA와 일치했다. 이는 이름으로 추정한 공유 관계가 아니라 같은 해석 경로를 직접 비교한 결과다.

- [auto-version/project.yaml:5](../../workbench_runs/scenes/auto-version/project.yaml#L5)
- [pickplace-colorblock/project.yaml:62](../../workbench_runs/scenes/pickplace-colorblock/project.yaml#L62)
- [pickplace-new/project.yaml:5](../../workbench_runs/scenes/pickplace-new/project.yaml#L5)
- 선택된 [Device capture.yaml:3](../../workbench_runs/devices/so101-pickplace/capture.yaml#L3)

바인딩 작성자는 registration.bind_configuration이고, bound_configuration은 workspace/devices 소유권·파일 존재·capture.yaml SHA를 검증한다. capture.yaml이 참조하는 cameras.json·Precision·SDK 보정의 SHA는 Project 바인딩의 전이 해시에 들어가지 않는다. 따라서 capture.yaml 바이트가 그대로인 상태에서 하위 JSON의 내용이 바뀌면 같은 Project 바인딩으로 다음 실행이 새 값을 읽을 수 있다. 반면 prepare_recipe는 직접 입력 JSON과 SDK 보정 파일을 별도로 고정하고 실행 직전에 verify_prepared_inputs로 재확인한다. 현재 구현은 단일 실행의 준비 후 변경을 막지만, Project가 같은 장치 구성을 가리키는 동안 모든 하위 설정이 영구 고정된다는 계약은 아니다. [registration.py:40–56](../../robot_learning_workbench/src/robot_learning_workbench/robot/registration.py#L40), [recipe.py:407–434](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L407), [recipe.py:561–576](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L561)

실제 선택된 capture.yaml은 follower/leader·양쪽 Precision·Camera·Robot·source model 경로를 한 묶음으로 가진다. 그중 robot_model은 pickplace-colorblock의 기존 scene-v8-native Export 아래 URDF다. 동시에 pickplace-new의 Project는 별도 robot_rigs/so101_with_camera/rig.yaml을 선택한다. 두 선택이 함께 존재하는 것은 현재 메타데이터 사실이다. 두 모델이 의미적으로 동등하거나 틀렸다는 판단은 이 보충 조사에서 하지 않았으며, Robot 모델 조사와 함께 해소할 선택 경계다. [capture.yaml:4–10](../../workbench_runs/devices/so101-pickplace/capture.yaml#L4), [pickplace-new/project.yaml:9](../../workbench_runs/scenes/pickplace-new/project.yaml#L9)

configure_selected는 같은 로봇 USB identity를 다시 고르면 기존 device_profile 파일을 참조하고, 두 역할이 모두 같으면 기존 recipe의 입력을 복사한다. Camera 설정은 새 구성 폴더에 새로 저장한다. 따라서 새 Device 구성 폴더가 자기 폴더의 JSON만 소유한다는 가정도 맞지 않는다. 안정적인 USB serial로 선택한 역할은 보존되며 연결 port는 런타임의 로컬 메타데이터로 해석한다. [registration.py:64–89](../../robot_learning_workbench/src/robot_learning_workbench/robot/registration.py#L64), [configuration.py:25–39](../../robot_learning_workbench/src/robot_learning_workbench/robot/configuration.py#L25)

## 2. SDK 보정·Precision·기록된 Mapping: 세 종류를 하나의 Calibration 파일로 합치면 안 된다

SDK 보정은 장치 homing/range 정규화 입력이고, Precision은 그 보정 SHA·motor identity·URDF SHA에 묶인 raw→model 좌표 매핑이다. 관측 장치 생성자는 SDK의 id/calibration_dir가 정확히 선택한 파일을 읽는지 확인하고, SDK 파일 SHA가 Precision identity의 calibration_sha256과 같은지도 검사한다. 현재 follower·leader 양쪽의 SDK 파일 SHA는 선택된 Precision identity와 일치했다. Precision의 /dev/ttyACM0·1와 Device의 /dev/serial/by-id 경로 표기가 다르다는 사실만으로 보정 불일치라 할 수 없다. 생성 시 안정 USB identity로 port를 해결하고 복사한 profile identity의 port를 갱신하기 때문이다. [configuration.py:10–38](../../robot_learning_workbench/src/robot_learning_workbench/robot/configuration.py#L10), [실제 follower 선택](../../workbench_runs/devices/so101-pickplace/follower.json), [실제 leader 선택](../../workbench_runs/devices/so101-pickplace/leader.json), [follower Precision](../../workbench_runs/devices/so101-pickplace/precision/follower.json), [leader Precision](../../workbench_runs/devices/so101-pickplace/precision/leader.json)

공식 SDK 보정 생성은 기존 calibration 파일을 덮어쓰지 못하고, 새 Device 구성을 선택하도록 요구한다. 관측용 생성 경로와 보정 실행 경로도 분리돼 있다. 그러므로 오래된 Capture의 calibration JSON을 최신 Device 보정으로 바꾸는 동기화는 현재 계약을 깨뜨린다. [sdk_calibration.py:7–14](../../robot_learning_workbench/src/robot_learning_workbench/robot/sdk_calibration.py#L7), [configuration.py:20](../../robot_learning_workbench/src/robot_learning_workbench/robot/configuration.py#L20)

Precision 저장의 영향 범위는 다음과 같다.

1. 기존 선택 profile이 있으면 이전 바이트를 workspace/calibration/history/precision_*.json에 보존하고 parent_sha256/parent_path를 기록한다.
2. 같은 입력 경로·stage를 유지하는 덮어쓰기는 기존 capture.yaml을 계속 사용한다. 이 파일을 선택한 모든 Project의 미래 실행이 새 profile 내용을 읽을 수 있다.
3. Save As 등으로 입력 경로가 바뀌면 새 Device 구성을 만든다. workspace/scenes/*/project.yaml을 순회해 기존 구성 경로를 공유한 Project들을 잠근 후 새 구성에 자동 rebind한다. 바인딩을 선택한 현재 Scene 하나로 한정하지 않는다.
4. 이미 출판한 Capture/Package를 찾아 갱신하지 않는다. 저장 result도 SDK 보정은 바뀌지 않았고 physical_verified=False라고 명시한다.

이 동작은 추측이 아니라 save_profile의 분기다. 공유 Device를 여러 Scene에서 쓸 때 저장의 영향 범위를 검토 화면에 표시할 이유가 있지만, 현재 공유 자체를 오류라고 단정할 근거는 없다. [precision_storage.py:18–44](../../robot_learning_workbench/src/robot_learning_workbench/robot/precision_storage.py#L18), [precision_storage.py:47–76](../../robot_learning_workbench/src/robot_learning_workbench/robot/precision_storage.py#L47)

기록·실행 경계에는 이미 필요한 방어가 있다. SnapshotStore는 선택된 Mapping을 deep copy하고 모델 SHA와 대조한 뒤 manifest의 joint_mapping에 넣는다. Scene Package의 encoder_mapping은 선언된 device_observation/device_command phase와 모델 identity로 읽는다. Real/Sim SceneView는 기록된 Mapping과 현재 follower 좌표를 대조하며, portable 좌표 비교는 검증한 Mapping에서 port만 제외한다. 이들은 살아 있는 대체 권위가 아니라 실행 증거 또는 호환성 제약이다. [snapshots.py:10–15,36–42](../../robot_learning_workbench/src/robot_learning_workbench/robot/snapshots.py#L10), [calibration.py:430–453](../../robot_learning_workbench/src/robot_learning_workbench/robot/calibration.py#L430), [scene_render.py:23–37](../../robot_learning_workbench/src/robot_learning_workbench/robot/scene_render.py#L23), [capture.py:75–85](../../real2sim_builder/src/real2sim_builder/capture.py#L75)

Package의 calibration.json도 별도 기능이다. parameters 또는 parameters_file 중 하나, application.mode/phase/order, 모델/센서 identity와 중복 적용을 검증한다. baked geometry와 runtime encoder mapping을 중복 적용하지 않도록 검사한다. 예를 들어 기존 scene-v9-task-objects/calibration.json에는 leader/follower encoder_mapping과 baked residual이 함께 있다. 세 항목을 이름이 비슷한 보정 중복으로 제거하면 실행 계약을 훼손한다. [package.py:240–309](../../scene_contract/src/scene_contract/package.py#L240), [package.py:329–374](../../scene_contract/src/scene_contract/package.py#L329), [실제 calibration.json](../../workbench_runs/scenes/pickplace-colorblock/exports/scene-v9-task-objects/calibration.json)

## 3. Camera라는 이름 아래 서로 다른 다섯 자원이 있다

Camera 하우징 Geometry, 실제 RGB stream 선택, optical intrinsics/distortion, link-to-optical Mount, Scene World 배치는 별개의 자원이다. Device cameras.json에는 USB index_or_path·width·height·fps만 있고 K·extrinsics는 없다. 현재 선택된 파일은 Side/Wrist의 /dev/v4l/by-id 경로를 가진다. Capture 생성자는 두 stream 역할과 640×480/30fps, 서로 다른 장치 경로를 확인한다. 이름이 같은 과거 capture/calibration/cameras.json은 K·distortion·parent·T_parent_camera·provenance를 가진 보정 시점 기록이다. [실제 Device cameras.json](../../workbench_runs/devices/so101-pickplace/cameras.json), [session_devices.py:59–73](../../robot_learning_workbench/src/robot_learning_workbench/robot/session_devices.py#L59), [실제 Capture 광학 기록](../../workbench_runs/scenes/pickplace-colorblock/input/captures/session_20261014_01/capture_001/calibration/cameras.json)

현재 optical 값은 Revision 경계마다 다를 수 있고 실제로 다르다.

| 실제 경로 | Side fx | Wrist fx | 해석 |
|---|---:|---:|---|
| [working/current_scene.yaml:3548](../../workbench_runs/scenes/pickplace-colorblock/working/current_scene.yaml#L3548) | 845.522540768306 | 544.4746416104862 | 현재 Working Scene의 optimized 값; quality는 ESTIMATED |
| [refit_001/candidate_scene.yaml:3494](../../workbench_runs/scenes/pickplace-colorblock/scratch/agent/refit_001/candidate_scene.yaml#L3494) | 818.6424552164815 | 556.948906574842 | 해당 후보의 joint-fit 근거가 있는 optimized 값; quality는 ESTIMATED |
| [scene-v9-task-objects/scene.json](../../workbench_runs/scenes/pickplace-colorblock/exports/scene-v9-task-objects/scene.json) | 818.6424552164815 | 556.948906574842 | 해당 Export가 보존한 값; validation은 ESTIMATED |

이 차이는 여러 현재 권위가 경쟁한다는 증거가 아니다. Export는 전달된 Scene의 K·distortion·pose를 Package 형식으로 복사한다. Pair 렌더는 선택된 Package와 그 authored_scene 또는 native engine에서 Camera를 읽는다. 측정 q에 대해 만든 sim_cameras와 Scene identity는 pair.json에 역사적 Runtime baseline으로 남는다. Working Scene을 바꿔도 기존 Package·Pair를 자동 갱신해서는 안 된다. [export.py:253–264](../../real2sim_builder/src/real2sim_builder/export.py#L253), [authored_render.py:10–22,47–61](../../robot_learning_workbench/src/robot_learning_workbench/robot/authored_render.py#L10), [scene_render.py:86–96](../../robot_learning_workbench/src/robot_learning_workbench/robot/scene_render.py#L86), [pairs.py:29–33](../../robot_learning_workbench/src/robot_learning_workbench/robot/pairs.py#L29)

Candidate의 view registration은 원본 image SHA·image record digest·camera_calibration_signature로 묶이며 K/Mount가 바뀌면 stale을 거부한다. camera signature에는 카메라 frame/K/pose/distortion뿐 아니라 World registration과 Wrist의 Robot model/base도 포함한다. 또 bound Capture import는 mount·resolution·센서 보정 변경을 거부하거나 명시 reconciliation을 요구한다. 이것은 갱신해야 할 파생 registration과 지켜야 할 불변 Capture를 이미 구분한 부분이다. [scene.py:45–55](../../real2sim_builder/src/real2sim_builder/scene.py#L45), [observations.py:93–104](../../real2sim_builder/src/real2sim_builder/observations.py#L93), [capture.py:255–290](../../real2sim_builder/src/real2sim_builder/capture.py#L255)

남는 관리 위험은 물리 Camera identity의 연결이다. 조사한 Camera 구성 검사는 stream 역할·mode·장치 중복을 확인하고, optical signature는 Scene의 수치·frame·World/Robot 관계를 확인한다. 이 두 경로에서 USB 센서 identity와 사용한 optical/Mount 보정의 identity를 직접 대조하는 연결은 확인되지 않았다. Snapshot은 camera_metadata를 state.json에 기록하지만 기본 Camera manifest는 stream id·resolution을 가진 관측 기록이며, Builder의 _sensor_fields도 camera_type·model/mapping identity를 옮긴다. 따라서 같은 side/wrist 이름만으로 다른 렌즈·Mount를 같은 보정 자원으로 간주해서는 안 된다. 실제 잘못된 Camera 연결이 발생했다는 재현 결과는 없으며, 이것은 소스 수준의 검사 경계다. [session_devices.py:62–72](../../robot_learning_workbench/src/robot_learning_workbench/robot/session_devices.py#L62), [snapshots.py:24–42](../../robot_learning_workbench/src/robot_learning_workbench/robot/snapshots.py#L24), [capture.py:14–27](../../real2sim_builder/src/real2sim_builder/capture.py#L14), [scene.py:45–55](../../real2sim_builder/src/real2sim_builder/scene.py#L45)

공유 후보는 물리 센서·촬영 mode에 묶인 intrinsics와 명시 Mount revision이다. World pose는 해당 Scene 정합에 속하며, 하우징 Mesh의 치수·위치로 보정을 인증할 수 없다. consolidation을 하더라도 이 경계와 estimated/calibrated 상태를 유지해야 한다. 이는 위 source 계약에서 도출한 설계 제안이다.

## 4. Runtime: 현재 기본값·명시 override·최초 실행 기록·실제 stage 기록의 역할이 다르다

SimFoundry 기본 실행은 다음 순서다.

1. reconstruct의 config 인수가 있으면 이를 사용한다. 없으면 Project input/reconstruction.yaml, 그것도 없으면 빈 mapping이다.
2. workspace/runtime/reconstruction.yaml의 runtimes만 기본값으로 읽고 중첩 mapping을 재귀 병합한다. Project/명시 config에 있는 키가 우선하며 중첩 키의 명시 None/빈 값도 임의 기본값으로 대체하지 않는다.
3. 명시 scene_state와 CLI의 execute_modeling/max_modeling_calls/modeling_timeout_s를 적용한다.
4. Blender runtimes.blender.executable이 있으면 기존 REAL2SIM_BLENDER selector를 실행 범위 동안 덮어쓴 뒤 복구한다.

별도 image_edit_removal/image_edit_objects가 있으면 Stage5/6이 각각 이를 사용하고, 없으면 image_edit로 fallback한다. 따라서 비슷한 Provider 설정 두 개가 무조건 중복된 현재값인 것도 아니다. [automation.py:327–343](../../real2sim_builder/src/real2sim_builder/automation.py#L327), [stage_runtime.py:40–88](../../real2sim_builder/src/real2sim_builder/stage_runtime.py#L40)

현재 Workspace 설정은 DA3/SAM3·image edit·rembg·CPD·physics·simulator·Blender 설치 경로를 가진다. pickplace-new/auto_001의 reconstruction-config.yaml에도 합쳐진 runtimes가 있다. 조사 시 두 runtimes mapping은 YAML 데이터로 같았다. 외부 경로가 실제 설치됐거나 모델 내용이 적합한지는 검사하지 않았다. [Workspace Runtime:1](../../workbench_runs/runtime/reconstruction.yaml#L1), [후보 최초 Runtime 기록:3](../../workbench_runs/scenes/pickplace-new/scratch/agent/auto_001/reconstruction-config.yaml#L3)

중요한 기록 구분: _run_stage_pipeline은 reconstruction-config.yaml이 없을 때만 쓴다. 재개할 때 이 파일을 무조건 현재 실행 권위로 다시 읽지는 않는다. 현재 인수와 Workspace 설정으로 stage별 subset/runtime identity를 만들고, 그 signature가 같은 stage만 재사용한다. 실제 attempt artifact에는 해당 실행의 config와 runtime_identity가 보존된다. 그러므로 Workspace 설정 변경 후 최초 reconstruction-config.yaml만 보면 현재 실행을 잘못 설명할 수 있다. 이 파일을 갱신해 역사적 기록을 바꾸기보다 기존 제작 기록에서 최초 설정과 이번에 해결한 설정의 역할을 명확히 보여주는 편이 맞다. [automation.py:42](../../real2sim_builder/src/real2sim_builder/automation.py#L42), [automation.py:128–176](../../real2sim_builder/src/real2sim_builder/automation.py#L128), [automation.py:194–208](../../real2sim_builder/src/real2sim_builder/automation.py#L194)

Runtime identity는 설정뿐 아니라 선택된 파일의 SHA, worker/adapter 구현 SHA를 기록한다. 따라서 경로·이름만 보고 동일 모델이라고 합치거나, 모든 stage를 Workspace 변경과 동시에 재실행하는 정리도 맞지 않는다. 현재 모델 경로 외부의 실제 bytes는 본 조사에서 읽지 않았다. [stage_runtime.py:91–120](../../real2sim_builder/src/real2sim_builder/stage_runtime.py#L91)

UI에는 추가 우선순위가 있다. saved_configuration은 Project input/reconstruction.yaml을 읽은 뒤 해당 Candidate review-config.yaml이 있으면 전체 설정을 그 내용으로 대체한다. UI는 이 결과를 임시 configuration.yaml로 만들어 CLI에 명시 전달한다. 따라서 Project 설정 파일을 고쳤더라도 열린 후보의 review-config가 선택되는 경우가 있다. 이는 구조적 수정의 최신 plan 재개를 위한 동작이고, 값의 출처를 표시하면 혼란을 줄일 수 있다. [ui_reconstruction.py:25–37](../../real2sim_builder/src/real2sim_builder/ui_reconstruction.py#L25), [ui_reconstruction.py:291–305](../../real2sim_builder/src/real2sim_builder/ui_reconstruction.py#L291)

기존 Real/Sim refit은 reconstruct에서 Workspace 병합 전에 별도 경로로 빠지고 자신의 explicit/Project config를 사용한다. 현재 refit_001/review-config.yaml에는 과거 sam/geometry와 다른 Project의 runtime_sources 출처가 남아 있다. 그러나 현재 src에서 runtime_sources 소비자는 검색되지 않았고 inference.run_models 호출자도 검색되지 않았다. run_models 자체도 segmentation_only 외 geometry 실행을 거부한다. 따라서 이 파일을 현재 MASt3R가 자동 실행되거나 다른 Project의 설정을 현재 다시 읽는 증거로 쓰면 안 된다. 이는 보존된 구식 필드가 현재 설정처럼 보이는 가독성 문제다. [automation.py:329–332,430–435](../../real2sim_builder/src/real2sim_builder/automation.py#L329), [실제 refit review-config:3–21](../../workbench_runs/scenes/pickplace-colorblock/scratch/agent/refit_001/review-config.yaml#L3), [inference.py:470–477](../../real2sim_builder/src/real2sim_builder/inference.py#L470)

## 5. Codex 선택은 Runtime YAML과 별도의 프로세스 선택이다

UI는 QSettings(Real2Sim, BuilderCodex)에 마지막 모델·effort를 저장하고, 현재 UI 선택 또는 저장된 preference를 모델 목록의 기본값보다 먼저 사용한다. launch는 이 선택을 REAL2SIM_CODEX_MODEL/REAL2SIM_CODEX_EFFORT로 child에 넣는다. Workspace의 runtimes.vlm은 provider=codex·timeout만 허용하며 모델·effort 등 추가 VLM 키는 구형 설정으로 거부한다. 따라서 모델 선택 UI와 provider YAML은 서로 다른 소유권이다. [ui_reconstruction.py:67,221–246](../../real2sim_builder/src/real2sim_builder/ui_reconstruction.py#L221), [ui_reconstruction.py:304–316](../../real2sim_builder/src/real2sim_builder/ui_reconstruction.py#L304), [stage_runtime.py:145–152](../../real2sim_builder/src/real2sim_builder/stage_runtime.py#L145)

실제 모델링은 environment 선택을 읽고, 없으면 사용 가능한 기본 모델을 조회하는 경로가 있다. VLM은 명시 모델을 요구한다. 둘 다 같은 selection_args로 --model/effort를 검증하고 실제 runtime 기록을 남긴다. CLI는 --ignore-user-config로 실행하므로 일반 사용자 config.toml을 이 저장소 설정의 숨은 기본값이라고 추정하면 안 된다. 기존 기록의 예로 auto-version/modeling/codex/request_016/runtime.json에는 gpt-6.1-sol·high·CLI 버전이 남아 있다. 이는 그 요청의 증거이며 현재 UI preference를 증명하지 않는다. 인증·QSettings 파일은 본 조사에서 읽지 않았다. [authoring.py:1250–1263](../../real2sim_builder/src/real2sim_builder/authoring.py#L1250), [authoring.py:1666–1677](../../real2sim_builder/src/real2sim_builder/authoring.py#L1666), [authoring.py:1371](../../real2sim_builder/src/real2sim_builder/authoring.py#L1371), [실제 runtime.json](../../workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap/modeling/codex/request_016/runtime.json)

가이드 원본은 authoring._codex_guidance의 저장소 CODEX_SCENE_GUIDE.md다. 이를 별도 작업 폴더와 기록에 복사하며 SHA를 보존한다. 복사본은 실행 입력의 증거이고 편집할 새 원본이 아니다. 모델링 함수는 이미 유효한 자산이 있으면 새 모델 선택을 해석하기 전에 재사용 반환할 수도 있다. 모델/effort 변경이 모든 이전 Object를 재모델링하라는 명령이라고 볼 수 없다. VLM stage의 runtime identity에는 환경의 모델/effort와 guide SHA가 포함된다. [authoring.py:14–22](../../real2sim_builder/src/real2sim_builder/authoring.py#L14), [authoring.py:1237–1267](../../real2sim_builder/src/real2sim_builder/authoring.py#L1237), [stage_runtime.py:91–99](../../real2sim_builder/src/real2sim_builder/stage_runtime.py#L91)

## 제안하는 작은 정리 순서

1. **기존 선택 함수의 결과를 명시한다.** registration.bound_configuration·recipe.prepare_recipe·stage_runtime.workspace_configuration·기존 제작 기록을 재사용해, 선택된 resource path/byte SHA/역할/출처와 공유 Project 수를 표시한다. Device recipe SHA와 전이 설정 SHA, 최초 실행 설정과 이번 실행 설정을 분리해서 보여준다. 새 Manager나 별도 앱을 만들 필요가 없다.
2. **Device/Precision 저장의 영향 범위를 분명히 한다.** 현재 공유 Save As가 어느 Project를 rebind하는지, 같은 파일 덮어쓰기가 어느 미래 실행에 반영되는지 기존 저장 흐름에서 설명한다. 변경 정책을 정할 때도 현재 Snapshot/Package를 일괄 갱신하지 않는다.
3. **Camera의 물리 연결을 보강한다.** 기존 stream 선택과 optical calibration 사이에 센서 identity·촬영 mode·Mount revision의 명시적 연결을 둔다. World 정합·하우징 geometry를 물리 렌즈 보정과 합치지 않는다. 실측/보정값이 없는 경우 estimated/unknown을 유지한다.
4. **Runtime 출처와 재사용 의미를 정리한다.** Runtime 기본값·Project override·후보 review plan·attempt 기록·현재 Codex 프로세스 선택을 기존 결과 화면에서 구분한다. 현재 소비되지 않는 legacy 필드는 원본 기록을 보존하면서 현재 선택 항목처럼 노출하지 않는다. 그 뒤 필요할 때만 기존 resolver에 공통 설치 경로 참조를 모은다.
5. **역사적 기록의 중복은 별도로 다룬다.** Capture Mapping, Package parameters, recipe/prepared snapshot, 가이드 복사본, runtime.json은 증거 경계다. bytes가 같아도 같은 의미의 live resource라고 볼 수 없고, 이름이 같아도 같은 센서/렌즈/보정이라 할 수 없다.

위 순서는 구현 제안이며 이번 조사에서 적용하지 않았다. 현재 확정한 문제 범위는 공유 선택·갱신 영향·출처 가시성과 물리 Identity 연결의 경계다. 단일 실행 중 설정 drift 차단, Camera registration stale 검사, Package calibration 중복 적용 차단이 이미 있는 점도 보존해야 한다. 실제 사진·실물 q·광학 정확도·물리 정확도·Runtime 가동 여부를 검증한 보고서는 아니다.
