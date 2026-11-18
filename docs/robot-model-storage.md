# URDF 저장 위치와 Scene·Capture·실행 흐름

2026-11-17. 현재 소스와 로컬 설정·파일의 SHA 및 inode를 읽어 확인했다. 모델 제작·Capture·장치 연결·학습은 실행하지 않았다. 이 프로젝트는 별도 로봇 프로젝트의 Checkout에서 파일을 읽지 않는다.

## 지금 관리하는 로봇

새로 선택해 재사용하는 공용 로봇은 아래 폴더다. UI 이름은 **SO-ARM101 + Wrist Camera**, 저장 이름은 **so101_with_camera**다.

```text
workbench_runs/robot_rigs/so101_with_camera/
  rig.yaml                      선택 이름·모델 경로·Mount·SHA 목록
  so101_with_camera.urdf         카메라를 장착한 전체 로봇
  source/assets/so101-isaaclab/
    urdf/so101_isaaclab.urdf     카메라를 붙이기 전 기준 로봇
    meshes/                    그 기준 로봇의 Mesh
  assembly/                    카메라 USDA·Visual·Collision·Texture
  urdf_meshes/                 결합 URDF가 사용하는 OBJ·MTL
  provenance/                 제작 당시의 근거
```

기준 URDF와 결합 URDF는 역할이 다르다. 기준 파일은 원래 관절 구조와 FK가 보존됐는지 대조하는 근거이고, 카메라가 달린 모델을 쓸 때는 so101_with_camera.urdf가 진입 파일이다. URDF는 관절·링크·원점·축·한계 및 Mesh 위치를 정의하는 XML이며, 실제 외형은 연결된 STL/OBJ/Texture 파일에도 들어 있다. URDF 한 개만 복사하면 필요한 Mesh가 빠질 수 있다.

이전 so101-wrist-camera/v006 폴더는 제거했다. 이름 변경으로 모델을 다시 만들지 않았으며 고정 의존 파일 45개의 bytes를 보존했다. 결합 URDF SHA256은 e25eb2e51f7d5ded2e4dcd5f8154629f219acba9171c8fb8115f7fb50c3c6a5b다. 기존 Object Library의 단독 카메라 Asset 버전은 이 Robot Rig의 저장 이름과 별개다.

## Scene에 넣을 때

```text
Scene Prepare → Robot Model 선택
  → Scene/project.yaml에 rig.yaml 상대 경로와 SHA 저장
  → 새 Candidate Reconstruction 시작 시 선택 Rig 검증
  → Scene/input/robot/...에 URDF와 의존 파일 복사
  → Candidate에 robot_model 경로·SHA·관절 및 링크 Frame 기록
  → Export 시 해당 모델을 Package/assets/...로 보존
  → 시뮬레이션·재생·IK는 선택 Package의 모델 사용
```

선택 자체는 Project Metadata만 바꾼다. 로봇이 이미 들어간 다른 Candidate나 기존 Capture·Export를 교체하지 않는다. 현재 pickplace-new는 ../../robot_rigs/so101_with_camera/rig.yaml을 선택했고, pickplace-colorblock과 auto-version의 기존 모델 선택은 보존했다.

[scene_preparation.py](../robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py)의 robot_variants()가 목록을 만들고 select_robot_rig()가 선택 경로/SHA를 저장한다. [automation.py](../real2sim_builder/src/real2sim_builder/automation.py)의 reconstruct()가 이 설정을 가져오며 _run_stage_pipeline() 시작에서 SHA를 검사하고 [evidence.import_robot_rig()](../real2sim_builder/src/real2sim_builder/evidence.py)를 호출한다.

import_robot_rig()는 기존 [export.copy_native_asset()](../real2sim_builder/src/real2sim_builder/export.py)로 URDF·Mesh·MTL·Texture를 Scene 소유 입력에 복사한다. 같은 경로 구조와 내용이 이미 저장돼 있으면 재사용한다. FK로 Reference Visual과 링크 Frame을 만들고, 카메라의 고정 Mount/Optical Frame을 보존한다. 이 Reference 구성만으로 Isaac용 동적 Articulation이 완성됐다고 판정하지 않는다.

과거 Scene은 공용 Rig 선택 기능 이전에 URDF 또는 Capture를 직접 가져왔다. 따라서 기존 모델이 input/robot뿐 아니라 input/models, input/assets 또는 input/captures 아래에 있을 수 있다. 실제 사용 경로는 그 Scene의 robot_model.path가 결정하며, 파일 이름을 검색해 임의로 최신 모델을 고르지 않는다.

## 기능별로 무엇을 읽는가

| 기능 | 실제 입력과 사용 목적 | 소유 코드 |
|---|---|---|
| Robot Model 목록·선택 | 공용 rig.yaml을 읽고 Project에 상대 경로·SHA 저장 | scene_preparation.py → UI scene_inputs.py |
| Scene 제작·로봇 가져오기 | 선택 Rig 또는 명시 URDF의 Native 파일을 복사하고 링크별 외형·Frame 구성 | automation.py → evidence.import_robot_rig / import_robot |
| 사진·Wrist/Side 정합 | Scene의 robot_model.path와 관측별 measured q로 FK. 고정 Mount와 Robot Base를 조합해 링크·Camera 위치 계산 | observations.py / calibration.geometry.link_transforms |
| Scene 시각 렌더 | 위 과정에서 얻은 실제 Mesh·링크 Pose·Camera를 기존 Renderer에 전달. 렌더마다 공용 폴더의 최신 URDF를 다시 선택하지 않음 | rendering.py / isaac_render.py / robot.authored_render.py |
| Precision Calibration | 명시 inputs.robot_model에서 관절 이름·축·한계를 읽고 Profile의 모델 SHA와 대조. source_robot_model은 기존 Profile의 다른 모델 이력을 검증하는 근거 | robot/precision.py / session_devices.py / calibration.py |
| 실제 관절 관측·제어 | 모터 Encoder↔모델 rad 변환은 검증된 Precision Mapping 사용. URDF의 관절 한계와 모델 SHA를 검사. URDF가 실제 모터를 직접 움직이는 것은 아님 | robot/devices.py / control.py / teleoperation.py |
| Capture / Real-Sim 저장 | 실행 Recipe의 inputs.robot_model을 SnapshotStore에 전달. q·RGB·Mapping과 함께 모델 파일 및 SHA를 보존 | robot/session.py / real_sim.py → snapshots.py → capture.share_model |
| Capture 가져오기·재사용 | 해당 Capture의 robot.path와 Manifest SHA를 읽고 단위·관절·Mapping·모델을 검사. Calibration이 없으면 관측만 등록 | real2sim_builder/capture.py의 load_session / import_snapshots / import_session |
| Scene Export | Scene이 가진 URDF와 의존 파일을 Package/assets/...에 보존하고 scene.robot.asset_path에 기록 | real2sim_builder/export.py |
| MuJoCo | 선택 Package의 execution_urdf()를 읽어 관절·Collision 구성. 명시된 동적 MJCF가 있으면 그 바인딩도 사용하고 URDF와 FK/Identity 대조 | engines/mujoco/model.py / robot/calibration.py |
| Isaac | Package의 모델 Identity·관절 정보는 URDF로 확인. 실제 PhysX Articulation은 Package의 명시된 robot.bindings.isaac USD를 사용 | engines/isaac/env_cfg.py |
| Mimic / Datagen / IK | 선택 Package의 실행 URDF와 SHA로 Pinocchio 모델 구성, tool0 FK/IK 및 관절 순서 검사 | generation/mimic.py의 bind_kinematics / SO101Kinematics 및 엔진 datagen.py |
| Dataset 3D Preview·평가 | Dataset에 기록된 실행 URDF SHA와 선택 Package가 같은지 검사 후 링크별 Mesh/FK 재생. Sim 평가는 같은 Package의 엔진 사용 | data/review_scene.py / engines/*/evaluation.py |
| LeRobot 변환·학습·Checkpoint | 일반 학습은 Dataset 이미지·관절·Action Tensor를 사용. URDF를 매 Step 읽어 3D 모델을 만드는 것은 아님. 모델 SHA·Scene·Calibration을 control_contract/lineage로 전달·검사 | data/lerobot.py / learning/train.py / learning/policy.py |
| Policy 실행·오프라인 검증 | Policy의 관절 순서·단위·로봇 SHA·Camera/Scene 계약을 현재 실행과 비교 | learning/policy.py의 policy_inputs / robot/live.py / offline.py |

패키지 모델 선택은 [robot/calibration.py](../robot_learning_workbench/src/robot_learning_workbench/robot/calibration.py)의 execution_urdf()가 담당한다. 명시된 baked robot_residual이 있으면 그 보정 모델, 없으면 scene.robot.asset_path를 사용한다. package_asset()은 Package 밖 경로와 Manifest에 없는 파일·변경된 SHA를 거부한다. 따라서 과거 보정 실행 모델과 카메라 부착 모델을 파일명만 바꿔 서로 대체하지 않는다.

## 현재 Capture는 어떤 URDF를 가져오는가

현재 Device 설정 workbench_runs/devices/so101-pickplace/capture.yaml의 inputs.robot_model은 아래 **프로젝트 내부의 기존 Export**를 가리킨다.

```text
workbench_runs/scenes/pickplace-colorblock/exports/scene-v8-native/
  assets/31da65a5af2b9b49531a79a410ca84e1cfe3eeac850818a330c2c8514f992960/
    urdf/so101_isaaclab.urdf
```

즉 새 Scene용 공용 Rig와 현재 Capture용 모델 선택은 별도다. 새 Robot Model을 선택했다고 기존 Device의 Precision Profile·Capture 모델이 카메라 부착 URDF로 자동 바뀌지 않는다. 카메라 Rig는 고정 관절이 추가되어 파일 SHA가 다르므로 현재 계약에서는 명시적인 모델/Mapping 검토 없이 같은 Calibration으로 승인하지 않는다. 이번 작업은 Device 설정과 Calibration을 바꾸지 않았다.

현재 Capture 모델 선택이 예전 Scene Export에 묶여 있는 점은 실제 설정 상태다. 이를 공용 로봇에서 독립 관리하도록 재구성한 작업은 이번에 수행하지 않았다. 기준 위치를 설명하면서 이 설정도 이미 새 Rig로 옮긴 것처럼 표시하지 않는다.

## Capture마다 URDF가 보이는 이유

q_measured의 의미는 URDF의 관절 이름·축·원점과 Mapping에 달려 있다. 같은 숫자라도 다른 모델에서 링크나 Wrist Camera 위치가 달라질 수 있다. 따라서 Capture는 당시 모델과 Mapping을 함께 남겨 나중에도 같은 관측을 해석할 수 있게 한다.

```text
input/captures/<session>/capture_001/
  side.png / wrist.png
  state.json                 측정 q와 시간 정보
  metadata.json
  capture_manifest.yaml     모델 경로·모델/Mapping/의존 파일 SHA
  model/urdf/so101_isaaclab.urdf
  model/meshes/...
```

이것은 Capture마다 새 로봇을 추정·모델링하는 작업이 아니다. [robot/capture.py](../robot_learning_workbench/src/robot_learning_workbench/robot/capture.py)의 share_model()은 모델과 선언된 Native 의존 파일에 **os.link()로 하드링크**를 만든다. 별도 폴더의 경로를 가지지만 동일한 디스크 파일 데이터를 공유한다. 기존 원본 경로를 지워도 다른 하드링크가 있으면 데이터는 남으며, 외부 폴더로 따라가는 Symlink와 다르다.

실제로 real_sim_20261116_03의 capture_001과 capture_002 안 URDF는 둘 다 **15,967B, 같은 inode**, 같은 SHA 31da65...다. 이들은 현재 Capture용 scene-v8-native의 URDF와도 같은 inode다. 두 번 재생성한 로봇이 아니다.

이번 읽기 전용 조사에서 robot_rigs/scenes/devices의 .urdf 및 .urdf.source는 59개 경로·6종 내용이었다. 그중 input/captures 아래에는 과거/미완료 경로를 포함해 21개 URDF 경로가 있었고, 실제 inode는 2개였다. 이 수치는 완료 Capture 개수나 전체 Mesh 디스크 용량이 아니다. Scene/Export의 복사본은 별도 inode인 경우도 있어 모든 경로가 하나의 하드링크라고 일반화하지 않는다.

하드링크는 변경 불가능한 데이터로 취급한다는 전제다. 한 경로의 파일을 직접 덮어쓰면 같은 inode의 Capture 모델까지 영향을 받을 수 있다. 현재 Reader가 SHA 불일치를 검출하지만 파일시스템 자체의 쓰기 방지나 Copy-on-Write를 제공하는 것은 아니다. 새 형상은 공용 모델을 별도 제작·명시 선택하고, 저장된 Capture·Export의 모델은 편집하거나 개별 삭제하지 않는다.

## 현재 검증 근거

저장 이름 변경은 관련 테스트 36개 통과, 실제 Qt에서 so101_with_camera 선택·툴팁 확인, Native MuJoCo URDF/검토 Scene 로딩, 고정 의존 45개와 기존 데이터 SHA 보존까지 확인했다. 외부 Checkout을 가린 자식 Namespace에서 검사했으며 AI 추론·하드웨어 연결·이번 Native 검사 중 Physics Step은 0이다. 전체 회귀와 실제 센서/물리/Task 검증을 새로 실행한 결과는 아니다.

실제 경로·SHA·inode 목록은 [URDF 저장 조사](../workbench_runs/diagnostics/robot_rig_rename_20261117_001/urdf-storage-inventory.json), 이름 변경 검증은 [completion-check.json](../workbench_runs/diagnostics/robot_rig_rename_20261117_001/completion-check.json)에 있다. 로컬 진단은 Git 제외 자료다. 기존 Scene·Capture·Calibration·Asset의 내용을 이 설명 작업으로 바꾸지 않았다.
