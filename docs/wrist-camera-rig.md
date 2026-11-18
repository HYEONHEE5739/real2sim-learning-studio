# SO-ARM101 + Wrist Camera

2026-11-17. 사용자 지정 저장 이름은 **so101_with_camera**다. Scene Prepare의 Robot Model에는 **SO-ARM101 + Wrist Camera**로 표시하며, 파일은 workbench_runs/robot_rigs/so101_with_camera/ 아래에 바로 둔다. Mount의 estimated / uncalibrated 상태는 툴팁으로 확인한다. 외형 선택은 센서 Calibration이나 물리 검증 완료를 뜻하지 않는다.

## 최종 파일과 UI에서 재사용하기

| 용도 | 파일 |
|---|---|
| 공용 Robot Rig / 이름·모델·Mount·파일 SHA | [rig.yaml](../workbench_runs/robot_rigs/so101_with_camera/rig.yaml) |
| 카메라를 장착한 전체 로봇 URDF | [so101_with_camera.urdf](../workbench_runs/robot_rigs/so101_with_camera/so101_with_camera.urdf) |
| Object Library의 카메라 단독 자산 | [wrist_camera_assembly/v006/manifest.json](../workbench_runs/object_assets/wrist_camera_assembly/v006/manifest.json) |
| 최종 렌더와 두 Capture의 Real / Sim 비교 | [이미지 모음](../workbench_runs/diagnostics/wrist_camera_refinement_20261116_001/index.html) |

1. Scene Prepare에서 사용할 Scene을 선택하거나 새 Scene을 만든다.
2. Robot Model에서 **SO-ARM101 + Wrist Camera**를 선택한다. 해당 Scene의 Project에 공용 Rig 상대 경로와 SHA가 저장된다.
3. 새 Candidate로 Reconstruction을 시작하면 선택한 URDF와 연결된 메쉬·재질·텍스처를 Scene 소유 입력으로 복사한다. 다른 로봇이 이미 들어간 Candidate는 새 Candidate를 사용해야 한다.

현재 pickplace-new의 선택을 새 경로와 Rig SHA로 갱신했다. 기존 Candidate·Capture·승인 Export의 로봇은 보존한다. 선택 목록을 이미 열어 두었다면 Scene 화면을 다시 열어 목록을 갱신한다.

다른 Workspace에서 쓰려면 robot_rigs/so101_with_camera **폴더 전체**를 그 Workspace의 robot_rigs 아래에 복사한다. Rig 안에 원본 로봇, 카메라 Assembly, OBJ/MTL/Texture 및 SHA 목록이 있으므로 URDF 한 파일만 옮기면 안 된다. Object Library에서도 단독 카메라를 사용할 경우 object_assets/wrist_camera_assembly/v006 전체도 함께 옮긴다. 단독 Asset의 버전 계약은 Rig의 저장 이름과 별개다. load_robot_rig()의 파일 SHA 검사를 통과한 모델만 선택한다. 모델·진단은 Git 제외 로컬 자료이므로 코드 저장소만 받아서는 제공되지 않는다.

## 원본 URDF는 어디에 있는가

이 프로젝트가 관리하고 실제 사용하는 기준 URDF는 공용 Rig 안에 있다. 다른 프로젝트 폴더에서 읽지 않는다.

```text
workbench_runs/robot_rigs/so101_with_camera/source/assets/so101-isaaclab/urdf/so101_isaaclab.urdf
```

카메라를 장착한 URDF와 기준 URDF·Mesh·Texture를 아래 폴더에 함께 보존한다. 원본 제작 이력에 과거 경로가 있어도 실행 시 그 위치를 탐색하거나 다시 불러오지 않는다.

```text
workbench_runs/robot_rigs/so101_with_camera/
  rig.yaml
  so101_with_camera.urdf
  source/assets/so101-isaaclab/urdf/so101_isaaclab.urdf
  assembly/          # 카메라 USDA / Visual / Collision / Texture
  urdf_meshes/       # URDF용 OBJ / MTL
  provenance/        # 제작 코드와 검증 근거
```

기준 URDF SHA256은 31da65a5af2b9b49531a79a410ca84e1cfe3eeac850818a330c2c8514f992960이다. 결합 URDF SHA256은 e25eb2e51f7d5ded2e4dcd5f8154629f219acba9171c8fb8115f7fb50c3c6a5b다. 저장 위치·URDF 파일명만 바꿨고 모델·Mesh·Texture의 bytes는 그대로다. Rig Manifest의 파일 경로와 선택 Project의 경로/SHA, 현재 비교 Scene의 연결 경로를 함께 갱신했다. [프로젝트 독립성 검증](project-isolation.md)은 실행·테스트·Qt 환경에서 다른 프로젝트에 접근하지 않는 조건을 기록한다.

## 전체 프로젝트는 어떤 URDF를 사용하는가

**전체 기능이 하나의 전역 원본 URDF를 자동으로 읽는 구조는 아니다.** 용도별로 명시적으로 선택하고 해당 데이터에 모델 사본과 SHA를 묶는다.

기능별 전체 호출 경로와 Capture의 모델 하드링크, 현재 Device가 실제로 선택한 모델은 [URDF 저장과 사용 흐름](robot-model-storage.md)을 따른다.

| 실행 경로 | 실제 모델 선택과 저장 위치 | 소유 코드 |
|---|---|---|
| Scene Prepare | Workspace의 robot_rigs/*/rig.yaml 및 기존 버전별 Rig를 읽고 Project에 상대 경로·SHA 저장 | robot_learning_workbench/scene_preparation.py의 robot_variants / select_robot_rig |
| Auto Reconstruction | 선택 Rig의 SHA 검증 → 해당 Scene의 input/robot에 Native URDF와 의존 파일 복사. Visual 입력은 input/assets에도 저장 | automation.reconstruct / _run_stage_pipeline → evidence.import_robot_rig → export.copy_native_asset |
| Scene Export | Scene의 모델을 불변 Export의 assets/<SHA>/...에 복사하고 Manifest에 등록 | real2sim_builder/export.py |
| Real Capture | Device의 inputs.robot_model과 Precision Mapping의 URDF SHA를 대조. Capture마다 모델 사본과 측정 q/Mapping을 보존 | robot/session.py → robot/snapshots.py의 SnapshotStore → robot/capture.py |
| MuJoCo / Isaac / 실행·학습 | 선택한 Export Package의 scene.robot.asset_path 또는 명시된 baked Calibration 모델 사용. Isaac의 명시 USD 경로도 Package 계약을 따름 | robot/calibration.py의 execution_urdf / package_asset 및 기존 엔진 Adapter |

현재 so101-pickplace Device의 capture.yaml은 pickplace-colorblock/exports/scene-v8-native 안의 원본 URDF 사본을 명시한다. 별도 source_robot_model은 devices/so101-pickplace/precision/source-model.urdf.source이며 다른 이력의 파일이다. 둘을 최신 Rig로 자동 치환하지 않았다. 현재 scene-v9-task-objects도 자체 Package의 so101_sim.urdf 및 Isaac 바인딩을 사용한다.

따라서 새 Scene에서 Robot Model을 선택하는 것과 기존 Real Capture/Mapping/Calibration 또는 과거 실행 Package를 새 로봇으로 교체하는 것은 별도 작업이다. 새 Rig는 기존 관절 6개를 유지하지만 모델 SHA가 다르므로 예전 Calibration을 자동 재승인하지 않는다.

## 최종 모델과 검증 범위

카메라 Visual은 camera_body / mounting_housing 두 Mesh이고 케이블은 없다. Collision은 별도 5개 convex 근사다. 고정 그리퍼 본체에 Mount와 Optical 고정 관절 2개를 더했으며 원래 구동 관절·축·한계·FK는 보존한다. 카메라 K/왜곡은 null이고 Mount는 estimated / uncalibrated다.

v006 제작 당시 실제 MuJoCo 3.3.7 Native URDF 로딩·기존 관절 6개·Optical Frame 및 두 Capture의 measured q에 대한 본체 FK를 검사했다. 기존 pickplace-colorblock Scene의 검토 사본에 결합 로봇을 넣고 동일 Side Camera와 기록 q로 렌더했다. 실제 GUI에서 두 상태 전환과 정상 종료도 확인했다. 물리 Step과 하드웨어 연결은 0이다. 최종 이미지와 검증 요약은 위 이미지 모음의 final/에 남겼다.

사진의 미관측 내부, 테이프·반사·투과, 정확한 실측 치수, Wrist 센서 정합·Hand-Eye·Robot World·Isaac PhysX·동적 Collision·Task 성공은 미검증이다. v005의 과거 Box 오차를 v006의 독립 정확도로 사용하지 않는다.

## 저장 이름 변경 검증

이름으로 바로 저장된 Rig를 목록에서 찾지 못하는 RED를 확인하고, 기존 검색 함수에서 해당 구조를 지원하도록 보완했다. 관련 Rig·Stage 전달·Qt 선택 시험 **36 passed / 실패0 / skipped0**, 실제 exit0이다. 새 경로의 Native URDF/메쉬 의존성·검토 Scene·Project 선택을 확인하며 기존 45개 고정 의존 파일은 모두 같은 SHA를 유지한다. 이전 Rig 경로와 빈 상위 폴더를 제거했고 Symlink나 이전 경로 대체 Reader를 만들지 않았다. 근거는 workbench_runs/diagnostics/robot_rig_rename_20261117_001/에 있다.

## 이전 정리 기록 — 2026-11-16

사용자 요청에 따라 참조가 없는 Robot Rig v002/v005, 카메라 Asset v002~v005 및 중간 제작·진단 파일 2,028개(논리 크기 1,614,777,417B)를 삭제했다. 최종 v006 Rig/Asset, 최종 이미지·재생 Scene·검증 요약은 남겼다. 구형 제작 문서는 이 문서로 통합했다.

**카메라 Asset v001은 기존 auto-version Scene·체크포인트가 참조하므로 보존했다.** 이를 삭제하면 기존 자료가 깨진다. 구형 Robot Rig 선택 항목은 남아 있지 않다. 기존 Scene/Input/Capture/q/Calibration/Export와 최종 형상 파일은 보존하며 Commit/Push하지 않았다. 이번 이름 표시·선택 변경의 테스트와 SHA 보존 근거는 workbench_runs/diagnostics/wrist_camera_finalization_20261116_001/에 기록한다.

이름 표시·툴팁의 수정 전 RED를 확인했고, 관련 Rig/Stage 전달/UI 선택 테스트 **35 passed / 실패0 / skipped0**, 실제 exit0을 확인했다. 전체 회귀는 반복하지 않았다. 삭제 후 실제 v006 URDF와 최종 검토 Scene을 MuJoCo Native Loader로 다시 열었고 의존 파일 50개를 확인했다. 보호 ledger 18,357개 중 위 Metadata 2개만 변경됐고 18,355개는 SHA/크기 불변, 누락·신규0이다. 최종 Rig의 고정 의존 파일 45개와 외부 원본 URDF도 불변이다. 이번에는 센서/물리 검증·모델 추론·하드웨어 실행을 하지 않았다.
