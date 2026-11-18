# 별도 로봇 프로젝트 의존 제거

2026-11-17. 사용자 결정: 이 프로젝트는 별도 soarm_isaaclab Checkout의 코드·환경·로봇 파일을 실행 입력으로 사용하지 않는다. 현재 브랜치의 기존 미커밋 구현 위에서 참조를 조사하고 테스트·Qt 환경의 잔여 의존을 제거했다. Commit/Push·설치·모델 추론·하드웨어 실행은 하지 않았다.

## 현재 소유 경로

| 대상 | 이 프로젝트의 관리 위치 |
|---|---|
| 최종 로봇 이름 | SO-ARM101 + Wrist Camera |
| Rig Manifest | workbench_runs/robot_rigs/so101_with_camera/rig.yaml |
| 결합 로봇 URDF | 같은 폴더의 so101_with_camera.urdf |
| 기준 로봇 URDF | 같은 폴더의 source/assets/so101-isaaclab/urdf/so101_isaaclab.urdf |
| 카메라 Mesh·Texture | 같은 폴더의 assembly 및 urdf_meshes |
| Scene 입력 | 선택 Rig를 해당 Scene의 input/robot 및 input/assets로 복사 |
| 실행·학습 | 선택 Export Package에 등록된 execution URDF/USD |
| Real Capture | workbench_runs/devices/so101-pickplace/capture.yaml의 프로젝트 내부 경로 |
| Qt Python | workbench_runs/runtime/qt/bin/python3.11 |

이름에 so101-isaaclab이 들어가는 내부 폴더도 현재 프로젝트 안의 실제 파일이며 외부 폴더로 향하는 Symlink가 아니다. Rig의 기준 URDF SHA는 31da65a5af2b9b49531a79a410ca84e1cfe3eeac850818a330c2c8514f992960, 결합 URDF SHA는 e25eb2e51f7d5ded2e4dcd5f8154629f219acba9171c8fb8115f7fb50c3c6a5b로 유지한다. 독립성 검증 이후 사용자 요청으로 저장 이름을 so101_with_camera로 바꿨으며 [현재 사용법](wrist-camera-rig.md)을 따른다.

## 확인된 잔여 의존과 수정

앱의 현재 Robot Rig·Capture 설정은 이미 프로젝트 내부 사본을 사용하고 있었다. 그러나 일부 회귀 테스트가 별도 Checkout을 직접 열거나 그곳의 Qt Python을 실행했다. Qt 환경을 과거에 복사한 뒤 남은 진입 스크립트도 있었다.

- Builder/UI 테스트의 Qt Python을 현재 Workspace의 환경으로 변경했다.
- Camera Solver의 기존 AST 비교는 저장소에 이미 보존된 동일한 알고리즘 Snapshot을 사용한다. 외부 소스 파일을 읽지 않는다.
- RGB/Mask Metrics는 알려진 변경 면적·픽셀 값·교집합/합집합으로 독립적인 기대값을 계산한다. 비교 대상 모듈을 외부 프로젝트에서 import하지 않는다.
- 실제 Renderer 시험은 현재 프로젝트의 합성 Scene Fixture를 사용한다.
- Precision의 공유 Fixture는 기존 Inventory를 메모리에서만 복사해 내부에 보존된 동일 Profile/URDF로 연결한다. 원 Inventory와 Calibration 수치는 수정하지 않는다.
- Fake Teleop/Capture 시험의 SDK Calibration은 이 프로젝트에 이미 있던 두 파일을 SHA 그대로 작은 고정 Test Fixture로 복사했다. Leader의 파일명이 Device Identity의 일부이므로 원래 파일명을 유지한다. 실제 장치는 생성·연결하지 않는다.
- Qt 환경의 8개 실행 스크립트 Shebang, 3개 Activation Script와 pyvenv.cfg의 오래된 선택 Metadata를 수정했다. 패키지·Python Binary·Conda 환경은 변경하지 않았다.

새 Manager·Loader·호환 Runtime을 만들지 않았고 제품의 모델 선택·Capture·Export 계약은 바꾸지 않았다. UI의 저장 보호 목록에서도 특정 로봇 프로젝트 이름을 제거했다. 다른 Checkout은 이름 대신 상위 Git 경계로 보호하여 무관한 프로젝트의 파일을 덮어쓰지 않도록 했다. 현재 프로젝트의 정상 저장과 SDK 보호는 유지한다. 임의 이름의 다른 Checkout에 대한 수정 전 RED도 별도로 확인했다.

## 외부 Checkout을 사용할 수 없는 상태에서 검증

다른 프로젝트의 실제 폴더는 변경하지 않았다. Bubblewrap의 자식 Mount Namespace 안에서만 해당 경로를 빈 tmpfs로 가려 Python·Qt·Native Loader가 그 파일들을 읽을 수 없도록 했다.

수정 전에는 기존 6개 사례가 외부 소스·Profile·Qt Python 누락으로 실패했다. Qt Activation의 별도 RED도 확인했다. 직접 참조 수정 이후 드러난 Inventory/SDK Calibration 간접 참조와 Leader 파일명 Identity 오류도 각각 실패 기록을 보존하고 수정했다.

최종 **144 passed / 실패0 / 오류0 / skipped0**, 실제 exit0, 43.80초다. Builder Calibration/Diagnostics/Renderer·실제 Qt UI·CPU MuJoCo·Precision·Fake Teleop/Capture·Rig/Stage 전달·UI 선택 관련 13개 시험 파일이다. 원격 AI·실물 하드웨어는 실행하지 않았고 전체 pytest를 반복하지 않았다.

동일한 격리 조건에서 다음 실제 로컬 파일도 검증했다.

- 최종 v006 Rig의 전체 SHA·Native Closure, MuJoCo URDF 로딩과 관절 6개.
- 기존 scene-v8-native / scene-v9-task-objects Package 및 각 execution URDF.
- 실제 Capture 두 개의 불변 Manifest 로딩.
- 현재 Device 설정 입력 7개의 프로젝트 내부 소유 경로·존재.
- 최종 검토 Scene의 Native MuJoCo 로딩과 연결 파일의 내부 소유 경로.
- Qt Python의 실제 prefix·sys.path 및 Activation·진입점.

Native 검증의 물리 Step=0, 하드웨어 연결=0, AI 추론=0이다. 기존 회귀 중 합성 CPU Physics와 메모리 기반 SDK API 시험은 별도로 포함된다. 실제 Reconstruction·Isaac Kit·센서 정합·물리/Task 정확도 성공을 뜻하지 않는다.

격리 시험은 저장소 루트에서 다음 형태로 재현한다. 첫 경로는 자식 프로세스에서 가릴 대상이며 프로젝트 입력 경로가 아니다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
bwrap --die-with-parent --bind / / --dev-bind /dev /dev \
  --tmpfs /home/hyeonhee/soarm_isaaclab \
  /bin/bash docs/evidence/builder/run_tests.sh \
  robot_learning_workbench/tests/test_runtime_portability.py \
  robot_learning_workbench/tests/test_precision_calibration.py \
  real2sim_builder/tests/test_robot_rig.py -q --tb=short
```

## 이력과 보존

과거 불변 Export·Capture·마이그레이션 보고서의 source/provenance 문자열은 당시 출처 기록으로 보존한다. 예전 진단·실험 스크립트는 당시 실행 기록이며 현재 제품의 실행 경로가 아니다. 문자열을 없애려고 과거 Artifact나 SHA Manifest를 재작성하지 않았다. 현재 Native 의존 파일과 Project/Device/Rig/Runtime 실행 설정에서는 외부 Checkout 참조가 발견되지 않았다.

사용자 Scene/Input/Capture/Calibration/Asset/Export·최종 Rig는 변경하지 않았다. 보호 ledger **18,566개 중 Qt Text 12개만 변경**, 나머지 18,554개 SHA/크기 불변·누락0·신규0이다. 원래 미커밋 구현과 Git HEAD/Index도 보존했다. 제품 변경은 UI 저장 보호 함수 하나이며, 테스트 10개 파일과 문서를 갱신하고 작은 Calibration JSON Fixture 2개를 추가했다. 파일별 목록은 아래 진단에서 확인한다.

근거: Git 제외 workbench_runs/diagnostics/project_isolation_20261116_001/의 foreign-blocked-red.xml/log, qt-activation-red.xml/log, checkout-protection-red.xml/log, release-protected.xml/log, independent-runtime.json, all-local-references.json, qt-relocation.json, preservation-after.json, summary.json. 저장 보호 보완 전 release-verified.xml/log의 144개 통과와 최종 실행을 구분한다. 초기 Namespace에서 /dev/null 접근이 거부된 준비 실패는 namespace-setup-failure.log로 별도 보존하고 제품 결함 RED와 구분한다.
