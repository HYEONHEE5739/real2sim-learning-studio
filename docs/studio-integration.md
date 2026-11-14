# Scene Prepare → Object Library → Real/Sim 통합

> 2026-11-13 후속: 아래 최초 CPU Viewer의 Texture Clip/가림 결함을 실제 컵/Blender 비교로 재현하고 OpenGL Depth Buffer 표시로 수정했다. 현재 Viewer 구현·Before/After·GPU 검증 범위는 [컵 Viewer 수정 기록](cup-viewer-rendering-fix.md)을 따른다. 아래 최초 실행 수치와 CPU 구현 설명은 당시 기록이다.

2026-11-13. 시작 HEAD a978e6e97ddab2682c3754dc50c19909ac8b94d3, feat/simfoundry-style-reconstruction, 시작 작업 트리 clean. 기존 API를 연결한 Library/Viewer, Stage10 Wrist 초기값, Real/Sim 수치 반복을 구현했다. 아래 검증 범위를 실제 사용자 Scene 완성과 구분한다. Commit/Push는 이번 요청에 포함되지 않아 수행하지 않는다.

## 구현 전 감사

| 기능 | 실제 실행 경로 | 확인한 공백 / 변경 경계 |
|---|---|---|
| Scene Prepare | SceneInputs → ReconstructionDialog → CLI reconstruct → automation Stage1–14 | Stage1–8 DA3/SAM/분해/원본 provenance/Native Asset/CPD 경로 존재. 실사진 정확도 미검증. 알고리즘 교체 안 함 |
| Stage10 | compile_scene → resolve_stage_world/resolve_sensor_world → register_sensor_views | Metric/FK 공유 Mount 경로 존재. 그리퍼 자기 관측 기반 seed 없음. 미해결 시 Stage8 산출물은 보존되지만 UI 상태 분리가 부족 |
| Asset Library | list/register/verify/publish/instance_operation → workspace/object_assets/ID/version | 불변 자산·다중 Scene 참조 구현. Workbench 전용 Library UI/조작 Viewer 없음 |
| USD/렌더 | object_assets.inspect_usda/_convert, rendering.Renderer/BlenderRenderer, exporters USD/MJCF | 실제 Mesh/UV/PreviewSurface 변환기 재사용 가능. VTK/PyVistaQt 미설치. PyQt CPU 뷰어를 선택; 새 패키지 설치 안 함 |
| Capture | robot.capture.prepare_snapshot/align_measured/assess_pair → capture.import_paired | 실제 measured history·스큐·안정성·Mapping/Model ID 검증 존재. host-read 시각을 노출 동기화로 오인하면 안 됨 |
| Real/Sim UI | RealSimPage → ReconstructionDialog(refit) → refit_pairs → _reconstruct | Capture/Source 선택·Stop/Best·Revision 보존 존재. refit 분기는 alignment_metrics 뒤 solver_executed=False이고 Codex 시각 반복. 수치 공유 Solver 연결 필요 |
| Solver | joint.fit_joint_scene, hybrid.fit_scene/alignment_metrics | 공유 Side/Wrist/Base/Object, 보호 측정·관측성·holdout 분리 존재. 합성 시험과 실사진 정확도 별개 |
| Physics/Task | validation.physics_probe, Stage12/14, Workbench tasks/engines | Passive probe·Review Package 경로 존재. 실제 Isaac/PickPlace·하드웨어 성공은 미검증. 자동 실물 구동 금지 |

읽은 기준: AGENTS.md, CODEX_SCENE_GUIDE.md, 기존 followup/Scene authoring/rules 문서 및 위 구현·시험. 최신 요청이 과거 Photo 강제 공동 렌더 정합 정책보다 우선한다. 이번 구현은 외부 추정 Pose를 정답으로 고정하는 새 루프를 추가하지 않는다.

보존 기준선: Git 제외 workbench_runs/diagnostics/studio_integration/before.json. 기존 Scene/Library/Runtime 18,347개 파일 SHA/크기. 기존 Source/Asset/Calibration을 실행 실험에 사용하지 않고 합성 fixture부터 검사한다.

## 이번 구현과 실행 연결

### 1. Object Library / 실제 USDA Viewer

Scene Prepare의 **Object Library · 3D 보기**에서 연다. 목록·검색·버전·치수(m)/출처·Collision 상태·상세 정보, 새 USDA 등록·공용 게시·Candidate 인스턴스 추가·기존 Object 버전 지정을 제공한다. 목록은 기존 list_object_assets, 쓰기는 register/publish/instance_operation/Candidate.edit를 그대로 사용한다. 동일 카테고리를 자동으로 같은 Asset이라고 확정하지 않는다.

- 사용자 Scene의 원본을 직접 편집하지 않는다. UI에 선택한 **현재 Scene의 Candidate**만 변경한다. 없는 Candidate 이름에 추가하면 새 Candidate를 생성한다. 같은 Asset Version을 다른 Scene과 여러 인스턴스에서 공유해도 Pose는 독립적이다.
- Version 선택은 해당 버전을 로드한다. 기존 Scene의 버전 참조를 자동 갱신하지 않는다. 측정 치수 충돌은 기존 use_object_asset 검증이 거부한다.
- USDA는 Builder 백엔드의 inspect_usda/verify_object_asset/_convert로 읽는다. 실제 Mesh, Transform, UV, Material subset, Texture와 별도 Collision을 변환하며 임의 Box/Cylinder proxy를 쓰지 않는다. 소유 임시 디렉터리만 사용하고 원본 자산을 수정하지 않는다.
- 백엔드는 기존 BackendJob/QProcess다. Workspace의 기존 physics.source USD library/bin 경계를 전달하며 개인 경로를 소스에 넣지 않는다. 설치가 없으면 Runtime 오류를 표시한다.
- GUI에는 PyQt6 QImage/QPainter 기반 CPU triangle viewport를 내장했다. VTK/PyVista 계열은 기존 환경에 없어 설치하지 않았다. 로딩/변환은 백엔드 프로세스, 래스터 작업은 QRunnable로 분리했다. 대기 렌더는 최신 요청 하나로 합치고 닫을 때 취소한다. 버전 로딩 실패 시 이전 형상을 새 버전으로 표시하지 않는다.
- 우클릭 드래그 Orbit, 휠 Zoom, 가운데 드래그 Pan, Reset View. Visual / Collision / 반투명 Overlay, Local XYZ, Grid, 치수/출처를 표시한다. 선택한 Object의 실제 렌더를 목록 썸네일로 사용한다(선택 전 일괄 썸네일 생성은 하지 않는 lazy 방식).
- Material 지원은 기존 converter가 수용하는 UsdPreviewSurface diffuse/UV 이미지다. 미리보기 Texture mip는 최대1024px. PBR·조명·렌더 정확도나 실제 Collision 유효성 인증을 뜻하지 않는다. 교차 삼각형의 깊이 정렬과 투명 중첩에는 CPU painter 방식의 한계가 있다. 복잡한/미지원 Material은 기존 converter 오류로 명시한다.
- 컵의 내부와 Collision을 회전/Overlay로 검토할 수 있지만 Viewer만으로 개구부·파지·삽입 물리 성공을 판정하지 않는다. 단일 Hull로 내부를 막는 대체 Mesh는 생성하지 않는다.

### 2. Stage10 / 그리퍼 자기 관측 초기값

Stage1–8 알고리즘은 교체하지 않았다. Stage10에서 초기 Capture의 q/Manifest가 존재하고 Robot model이 아직 없다면 기존 captured_robot로 archived 모델·Mapping·FK 참조를 가져온다. 원본 Current Scene/URDF/q를 바꾸지 않고 Candidate에만 가져온다. 실제 Robot World/scale은 기존 독립 Anchor 또는 여러 Wrist/FK 경로가 계속 소유한다.

새 calibration/wrist.py는 **공유 T_link_camera 초기값**만 담당한다. 기존 승인 CAD landmark의 robot_link 프레임 또는 Robot Object의 link-local point_m과 실제 Wrist image ID/q를 연결해 자동 호출한다. 필요하면 기존 sensor_registration.gripper_mount 설정에 검토된 관측을 명시할 수 있다.

```yaml
sensor_registration:
  gripper_mount:
    WRIST_CAMERA_ID:
      observations:
        - image_id: ACTUAL_CAPTURE_IMAGE_ID
          landmarks:
            - link: ACTUAL_URDF_VISUAL_LINK
              point_m: [0.0, 0.0, 0.0] # 반드시 실제 검토된 CAD 점으로 교체
              uv: [0.0, 0.0]          # 실제 원본 upright pixel로 교체
              confidence: 1.0
              sigma_px: 3.0
```

위 0 좌표는 자리표시자이며 자동 Anchor가 아니다. 원본 Role/이미지 SHA/Model SHA/Mapping/Joint 순서/q·pixel grid를 검증한다. Camera K/Distortion과 실제 Link parent가 필요하다. 사용자 보호 Calibration은 seed로 덮어쓰지 않는다.

1. 검토된 Gripper Mask가 있으면 실제 RGB에서 Contour와 유효 Corner를 추출한다. 대응되지 않은 특징점은 UNRESOLVED다. Corner만으로 URDF 점 Identity를 만들어 내지 않는다.
2. 각 measured-q로 archived URDF FK를 계산하고 gripper Visual 점을 Camera의 Mount Link 좌표로 옮긴다. 그리퍼/손가락 q가 다르면 실제 FK가 달라진다. 팔만 움직여 같은 상대 형상이 반복되면 independent_relative_configurations=1로 기록한다.
3. 기존 known-K PnP 초기값과 유한한 추가 seed(최대8개), 기존 project_pixels/distortion/픽셀 affine 및 bounded least_squares를 사용한다. 모든 q가 하나의 Mount를 공유한다. q·URDF·Base·Object 크기는 최적화 변수가 아니다.
4. 후보별 T, 양수 깊이, Training pixel RMSE, Jacobian rank와 Holdout 진단을 저장한다. PnP는 canonical Camera pixel로 계산하고, 잔차·sigma·RMSE는 affine/EXIF를 반영한 실제 관측 RGB pixel 단위다. 관측 sigma 안에서 비슷한 오차의 다른 해가 있으면 AMBIGUOUS로 남기고 적용하지 않는다.
5. 성공한 초기값도 estimated다. 자기 관측으로 Robot World를 결정하지 않는다. 기존 실측 Mount는 보존하고, 실제 하우징/그리퍼와 URDF Visual 외형 일치도는 NOT_VERIFIED다.

**PARTIAL:** Mask만 주어진 영상에서 자동 semantic CAD Keypoint 대응을 확정하는 기능은 없다. 기존 승인 특징점 또는 명시 대응이 필요하다. 순수 silhouette-only Mount 탐색/자동 모델 오차 진단은 이번 구현 범위가 아니다. 이 부족한 근거를 성공한 Mount로 감추지 않는다. 기존 Scene feature/FK 초기 등록 경로는 계속 사용할 수 있다.

Stage8의 유효 Object 결과와 Stage10의 Scene/Robot/Sensor 미해결 상태는 reconstruction.json의 completion 및 UI에서 별도로 표시한다. Stage10이 차단돼도 이전 Asset/Mask/Depth/CPD Artifact는 삭제하지 않는다.

### 3. Real/Sim 수치 Closed Loop

Real/Sim에서 Scene/엔진 선택 → 기존 Teleoperation/안정 Capture 수집 → 세션 종료 → **촬영 자료로 Scene 재정합**을 연다. 측정값·Camera·Scene State·Source Revision이 맞는 Capture만 사용한다. 이번 구현이 실물 Teleoperation을 자동 실행하지 않는다.

Dialog의 기본 **실측 q 기반 수치 공동 정합(Codex 호출 없음)**과 최대 반복(1–20)을 사용한다. 기존 Source 기반 Codex 구조 수정 경로는 체크 해제로 선택할 수 있다. Reconstruction Memo·Source 선택·Capture ID/엔진·Stop/Resume를 유지하며 수치 실행 때문에 로그인/선택 모델/Thinking Effort를 바꾸지 않는다.

수치 경로: refit_pairs → refine_numeric_pairs → 기존 register_sensor_views → joint.fit_joint_scene → 필요한 경우 hybrid.fit_scene → alignment_metrics → retain_fitting/restore_fitting. 새 최적화 엔진이나 Device 실행기는 없다.

- Scene State/Source/Model/Mapping/실측 q는 기존 Pair reader 계약으로 검증한다. Sim은 observation_scene의 recorded q/FK를 사용한다. 명령 목표 q나 과거 Sim q로 대체하지 않는다.
- 기존 Capture의 timestamp/스큐/안정성·단위·Mapping/Model 검사를 유지했다. host read 시각 동기화는 hardware exposure sync와 다르며 기존 hardware_synchronized=false를 그대로 존중한다.
- 먼저 Camera/Base/Object Pose를 정합한다. Side는 고정 Pose 하나, Wrist는 고정 Link Mount 하나, 정적 Object도 Scene State 내 공유 Pose다. measured/calibrated 값과 q·URDF·scale/치수는 보호한다. 제한 Intrinsics는 기존 Native Solver의 관측성 Gate가 허용할 때만 설정할 수 있다.
- Joint 결과가 rank-deficient면 진단으로 보존하고 Scene을 확정하지 않는다. Native Solver의 기존 변수 선택·관측성 조건을 재사용한다.
- 승인된 비가림 silhouette만 기존 build_render_observations로 연결한다. 센서 Depth를 만들지 않는다. 가림/불명확한 Mask는 full silhouette로 승격하지 않고 reviewed landmark 또는 추가 관측을 요구한다. Renderer는 기존 Intrinsic/Distortion/FK 경계를 사용한다.
- RGB/Mask/Edge/Object surface residual과 Camera/Pose/Object별 landmark 오차를 기록한다. Appearance는 수치 Pose 루프에서 고정한다. RGB만으로 Camera/Geometry/Material 원인을 판정하지 않는다.
- Round의 before Scene/metrics, after Scene/렌더/metrics, solver/Train/Holdout ID 및 채택 여부를 저장한다. UI에 반복/채택 횟수와 Camera별 오차를 표시한다. Evidence 버튼으로 상세 파일을 확인한다.
- Training View의 어떤 기존 비교 항목도 악화되지 않는 개선만 Best로 채택한다. Holdout은 최적화/Best 선택에 사용하지 않고 진단에만 기록한다. Holdout 오차가 나빠지면 독립 정확도를 확인한 것으로 취급할 수 없다.
- Stop·예산·오류·악화는 Best를 복원한다. 입력 identity가 같은 중단 작업은 완료 Round를 보존하고 미완료 Round부터 재개한다. 추가 Capture/Source 변경은 별도 identity로 취급한다.
- Scene Prepare/발행 Revision은 유지한다. Geometry 수정을 자동 반복하지 않는다. 구조 수정이 필요하면 기존 Codex 검토/선택 Object의 새 Asset Version 경로를 별도로 사용하고, Appearance도 이후 별도 검토한다. 수치 루프에서 자동 Geometry→Appearance 전환까지 구현한 것은 아니다.

실제 Native 합성 검사에서 2개 고정 Side 시점의 CAD landmark 최적화·재렌더·Best 채택을 실행했다. 이 검사는 실제 Wrist 영상·사용자 사진·독립 정확도 시험이 아니다. q 공유/hand-eye 및 왜곡/픽셀 변환의 합성 시험과 구분한다.

### 4. Physics / Task 경계

기존 physics-check CLI/Stage12/14, MuJoCo/Isaac adapter와 Workbench Task Runner를 유지했다. UI/수치 정합 결과는 미승인 Candidate다. 실제 Passive probe와 실행되지 않은 Physics, 실제 Pick/Place 성공을 구분한다. 이번에는 실물 장치 명령·Isaac GPU Physics·실제 Task를 자동 실행하지 않았다. 원본 Export의 Calibration/안전 Gate를 약화하지 않았다.

## 실제 사진 전 확인한 입력 / Blocker

`auto-version`의 Current Scene을 읽기 전용으로 확인했다. Scene Photos8개는 서로 다른 external_view ID다. Current에 Robot model/Camera가 없고, validation split과 reviewed landmark도0개다. q와 capture_manifest가 존재하는 기록8개가 있으나, 그 개수가 typed Side/Wrist·Mapping·Calibration 검증 완료를 뜻하지 않는다. 명시 camera_type=side/wrist인 이미지 수는0개다. 기존 Candidate/Scene/사진은 수정하지 않았다.

따라서 이번 구현을 해당 사용자 Scene의 Reconstruction·정밀 정합 성공으로 표시하지 않는다. 기존 Capture의 실제 센서 역할/Model/Mapping과 timestamp를 검증해 등록하고, 실제 Support/World 대응 또는 충분한 Wrist/Scene 대응과 미사용 Holdout을 확보해야 한다. Gripper 경로는 추가로 URDF Visual의 실제 CAD/pixel 대응·K가 필요하다. Camera Pose나 Calibration을 임의 생성하지 않는다.

## 실제 산출물 확인

Workspace의 기존 Native Asset **10개 버전**을 읽기 전용 검증했고 모두 Native validation PASS였다. block_blue/green/red, cup_1/2, desk, foam_roller, workspace_paper v001/v002, wrist_camera_assembly다. Collision 상태는 기존 `AUTHORED_UNVALIDATED`를 유지한다. 파서/Manifest/Geometry 검증 통과가 실물 치수의 독립 검증이나 Collision/Task 물리 인증은 아니다.

실제 `cup_1/v001`을 새 Object Library Dialog → BackendJob → USD converter → 내장 Viewer로 열었다. **67개 실제 Visual/Collision Mesh**를 읽었고, 로딩/렌더 중 GUI heartbeat 154회를 관측했다. 이는 이 자산의 비동기 응답성 확인이며 임의 대형 Mesh의 FPS 보장은 아니다. 열린 컵 내부를 확인할 수 있으나 Texture seam·투명 중첩·triangle 깊이 정렬 차이가 남는다. 원본 USDA/Texture는 변경하지 않았다.

- [실제 컵 Visual](../workbench_runs/diagnostics/studio_integration/existing-cup-visual.png)
- [컵 Collision Overlay](../workbench_runs/diagnostics/studio_integration/existing-cup-collision.png)
- [Library 화면](../workbench_runs/diagnostics/studio_integration/existing-cup-library.png)
- [실제 USD/Texture의 합성 Viewer 검사](../workbench_runs/diagnostics/studio_integration/viewer-actual-usd.png)

위 이미지는 사용자 사진 Reconstruction을 새로 실행한 결과가 아니다. 기존 USDA를 새 Viewer로 읽은 이미지와 합성 자산 검사다.

합성 Native 수치 Round에서는 두 고정 Side View의 CAD landmark를 최적화하고 MuJoCo로 재렌더했다. `native-loop-fixed.xml`의 RGB MAE(0–1)는 각각 **0.000124592 → 0.000001157**, **0.000123434 → 0.000001362**로 감소했다. 이 잔차는 같은 합성 입력에 대한 Training 결과다. 실제 Wrist/다중 q/독립 Holdout 정확도나 실사진 Geometry 품질로 해석하지 않는다. 실제 공유 q/FK·Wrist·그룹 누수·픽셀 affine은 별도 합성 수학/계약 시험으로 검사한다.

## 검증 기록

새 Library loader/무결성/교차 Scene 참조, Qt Viewer/실제 USD·Texture 로딩/마우스 조작/닫기, Gripper 공유 FK·동일 상대시점·불충분한 점·Crop·Train/Holdout 누수·관측 pixel 단위, numeric Stop/Resume/Best·실제 Native render·CLI 완료 상태를 검사했다. 최종 집중 묶음 **13 passed**, 6.46초다(`final-release-focused.xml/log`). 이전 `final-connected`13개와 중간 집중55개는 겹치므로 합산하지 않는다.

실제 Native Round를 추가하며 접촉 정규화와 파생 점군의 외부 소유 경로 때문에 Best 복원이 실패하는 RED를 재현했다. 기존 preserve/validate/SHA 검사를 유지하고 baseline에서 Candidate 소유의 파생 관측을 일관되게 구성하도록 수정했다. 마지막 Holdout 검사에서는 저장된 Mount list의 행렬 변환 오류와 리사이즈 후 canonical pixel 잔차를 실제 RGB pixel처럼 표시하는 문제를 RED→GREEN으로 수정했다(`gripper-pixels-red*.xml/log`).

Viewer의 `payload=None`만으로는 완료된 QRunnable의 Mesh 참조가 해제되지 않는 것도 실제 Qt/weakref로 재현했다. 렌더 완료/실패에서 task 참조를 해제하고 닫을 때 pending을 취소했다. 마우스/Texture 시험을 유지하면서 실제 payload의 garbage collection을 검사하도록 기존 시험을 강화했다(`viewport-release-probe.json`, `viewer-release-red.xml/log`, `final-release-focused.xml/log`). 취소한 작업은 소유 스레드의 종료 콜백에서 해제한다.

전체 회귀는 세 패키지를 같은 checked wrapper로 실행한다.

```bash
REAL2SIM_BLENDER=/PATH/TO/EXISTING/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short \
  --junitxml=workbench_runs/diagnostics/studio_integration/release-complete.xml
```

**최종 수정본 전체 1,849 passed / 실패0 / 오류0 / skipped0**, Console 기준 **554.54초**다(`release-complete.xml/log`). 경고5개는 기존 torchvision 영상 경고4개와 JUnit xunit2에서 record_property를 사용하는 측정 기록 경고1개다. 경고를 숨기거나 skip/xfail로 우회하지 않았다. 실행 중 세 패키지 소스/시험 **356개 Python SHA 변경0**을 확인했다. Viewer의 마지막 참조 해제까지 포함한 같은 소스의 결과이며, 중간 통과 수치를 합산하지 않는다.

중간 실행을 최종 통과로 합산하지 않는다.

- `release-full`: 구현 보완 중 중단, 548 passed 뒤 KeyboardInterrupt. 완료된 전체 회귀가 아니다.
- `release-final`: 1,843 passed / 4 failed. 네 개는 기존 HEAD를 별도 archive로 읽은 검사에서도 동일하게 실패한 영상/Photo Stage7 fixture였다. Stage5가 이미 분석을 제공하는 경로와 별도 Stage7 fallback 검사를 구분하도록 fixture를 명시하고, 분석 SHA/Memo/Model Reference 검증은 유지했다. 기존 시험 삭제/skip은 없다. 수정 뒤 해당 파일5개가 통과했다. 첫 archive Harness의 Guide 누락 실패는 유효한 baseline에서 제외하고 교정한 로그를 구분한다.
- `release-verified`: 1,846 passed / 1 failed. 테스트가 실행되는 14:12:36.762에 CLI 소스를 수정해, 14:12:36.438의 Stage1 Artifact와 14:12:38.150의 재개 Artifact에서 `cli.py` SHA만 달라졌다. 기존 전역 구현 identity 무효화가 발생했고 stateful Mock의 재호출이 빈 Instance를 반환했다. 캐시 규칙이나 테스트 기준을 완화하지 않았다. 소스 고정 후 해당 재개 시험은 단독 **1 passed**였다. 근거는 `stage-cache-invalidation.json`, `resume-stable.xml/log`다.
- `release-stable`: 소스356개 SHA 변경0인 전체 실행 **1,849 passed / 실패0 / 오류0 / skipped0**, 565.69초. 이후 확인한 Viewer의 완료 작업 참조 해제를 추가한 최종 소스는 `release-complete`로 구분한다.

### 실제 실행 수준

| 검증 대상 | 이번 실행 / 한계 |
|---|---|
| Python/Qt/Native USD | 실제 새 Dialog·비동기 Backend·USD parser/UV Texture·Visual/Collision·마우스 조작·해제 확인 |
| Gripper Mount | 실제 SciPy/OpenCV/URDF FK 수학을 합성 CAD/pixel에서 실행. 실제 Wrist RGB의 semantic CAD 대응은 미검증 |
| 수치 Closed Loop | 기존 joint solver와 실제 합성 MuJoCo RGB 재렌더·Best/Stop/Resume 확인. 실제 사용자 Pair 미실행 |
| Blender/Sandbox | 기존 합성 회귀는 실제 설치 Blender/bwrap을 호출하며 Codex 응답은 fake CLI다. 새 사용자 Object 제작/온라인 모델링은 실행하지 않음 |
| Passive Physics | 기존 합성 CPU MuJoCo 300Step/Pose/안정 구간 시험과 Task 성공을 구분. 사용자 Scene의 파지·컵 삽입은 미검증 |
| DA3/SAM/FLUX/PDA/Bria 및 Codex 온라인 | 이번 신규 Forward/온라인 호출0회. 기존 기록을 이번 실사진 성공으로 사용하지 않음 |
| Isaac GPU/PhysX·실제 Robot | 실행0회. 기본 렌더 센서 Side/Wrist·Photo reference 보존 계약을 유지 |

Qt Viewer는 CPU 방식이며 Isaac GPU 검증의 증거가 아니다. 기존 GTK/EGL/AMDGPU fallback 및 torchvision 경고는 실제 테스트 실패와 구분한다. 설치·모델 다운로드·Conda 변경은 없다.

## 사용 순서

1. **Scene Prepare:** Scene Photo/명시 Video, Memo, Object별 Model Reference를 기존 입력 화면에 저장하고 **Auto Reconstruction**을 연다. 기존 Runtime 설정과 Codex 모델/강도를 확인하고 새 Candidate 이름으로 실행한다. 동일 입력은 검증된 Artifact를 재사용하며 제작 기록에서 Stage별 실제 결과를 확인한다. Side/Wrist는 Scene Photo로 섞지 않는다. 이번 작업에서는 이 버튼으로 사용자 Scene을 실행하지 않았다.
2. **Library:** **Object Library · 3D 보기**에서 검색 → Object ID → Version을 선택한다. 우클릭 Orbit, 가운데 드래그 Pan, 휠 Zoom, Reset View와 보기 모드로 실제 자산을 검토한다. Candidate 이름/Object ID를 입력해 추가 또는 기존 인스턴스의 버전을 지정한다. 새 USDA 등록은 기존 Native 검증을 거치며 기존 버전을 덮어쓰지 않는다.
3. **초기 Sensor:** 유효 Capture의 실제 Model/Mapping/q, Camera 역할/K/Distortion과 World 근거를 준비한다. Gripper seed는 위의 검토된 CAD/pixel 관측을 사용한다. 부족한 정보는 Stage10의 needs로 확인한다. Object Artifact 완료와 센서 정확도는 별도다.
4. **Real/Sim:** 기존 Scene/엔진·Source를 선택하고 사용자가 Teleoperation에서 Side/Wrist Capture를 수집한다. 세션을 종료한 뒤 **촬영 자료로 Scene 재정합** → 수치 공동 정합/반복 횟수를 선택한다. Camera/Scene State/q·Mapping 검증 실패는 먼저 해결한다. Holdout은 학습에 사용하지 않은 Capture 그룹으로 분리한다.
5. **결과:** 반복별 Before/After·Train/Holdout·Solver/Best를 제작 기록에서 확인한다. Stop 후 같은 입력으로 재개한다. 수치 Draft 채택은 독립 Calibration/물리 승인과 다르며, 이후 기존 Physics Probe/Task 경로를 별도로 검증한다. 실제 장치 구동을 자동으로 시작하지 않는다.

## 구현 상태와 남은 한계

| 항목 | 상태 | 남은 조건 |
|---|---|---|
| 공용 Asset 관리 / 내장 Viewer | VERIFIED 지정 합성·기존 컵 범위 | 대형 Mesh 성능·복잡 PBR·투명 정렬 정확도 미검증 |
| Stage1–8 기존 알고리즘 | PRESERVED / 실제 사진 정확도 NOT_VERIFIED | 이번 사용자 사진 Depth/Mask/CPD/E2E 재실행 없음 |
| Stage10 공유 Gripper seed | PARTIAL | 검토된 CAD/pixel 대응·K·Robot Link가 필요. Mask-only 자동 대응/실제 외형 차이 판정 없음 |
| Robot World / Side/Wrist 등록 | 기존 수치 경로 연결, 실제 정확도 NOT_VERIFIED | 독립 World/Metric 근거 또는 관측 가능한 FK/Scene 데이터와 Holdout 필요 |
| Real/Sim 반복 수치 정합 | VERIFIED 합성 / 실제 사용자 Pair NOT_VERIFIED | 두 실제 센서의 대응·Calibration·Scene State·measured-q와 독립 평가 필요 |
| Geometry→Appearance 후속 수정 | PARTIAL | 기존 고급 Codex/선택 Asset 새 버전 경로는 유지. 수치 실패에서 자동 구조 수정까지 진행하지 않음 |
| Isaac·파지·컵 삽입·실물 Task | NOT_VERIFIED | 별도 엔진/Collision/접촉/Task 실행 증거 필요 |

진단 경로는 Git 제외 `workbench_runs/diagnostics/studio_integration/`이다. 제품은 이 폴더를 import하지 않는다. Markdown에 연결된 로컬 PNG/로그는 저장소만 받으면 없을 수 있다.

## 변경 파일과 데이터 보호

기존 파일11개 수정·신규8개·삭제0개이며, 시작 index는 비어 있었다. 기능 소유권은 다음과 같다.

| 파일 | 변경 이유 |
|---|---|
| `real2sim_builder/src/real2sim_builder/asset_view.py` (신규) | 기존 Native Asset 검증/변환/Library API의 UI 진입점 |
| `robot_learning_workbench/src/robot_learning_workbench/ui/object_library.py` (신규) | 기존 Workspace 자산 목록/버전/명시 Candidate 작업 Dialog |
| `robot_learning_workbench/src/robot_learning_workbench/ui/asset_viewport.py` (신규) | 실제 삼각형/Texture의 비동기 Qt CPU Viewport |
| `robot_learning_workbench/src/robot_learning_workbench/ui/jobs.py`, `operations.py`, `scene_inputs.py` | 기존 BackendJob/USD Bootstrap/Scene Prepare 버튼 연결 |
| `real2sim_builder/src/real2sim_builder/calibration/wrist.py` (신규) | shared Gripper CAD/FK-to-pixel Mount 초기값과 진단 |
| `real2sim_builder/src/real2sim_builder/reconstruction_stages.py` | Stage10 archived Robot/Gripper 연결·변경 Camera 관측 갱신 |
| `real2sim_builder/src/real2sim_builder/automation.py` | Object/Scene/센서 상태 구분과 기존 Solver/Best를 사용하는 수치 Round |
| `real2sim_builder/src/real2sim_builder/calibration/joint.py` | 수치 반복의 Holdout 진단 전용 정책, 기존 기본 동작 유지 |
| `real2sim_builder/src/real2sim_builder/ui_reconstruction.py`, `cli.py` | 반복 UI/결과·수치 Draft CLI 정상 완료 구분 |
| `robot_learning_workbench/src/robot_learning_workbench/ui/real_sim_page.py` | 선택한 엔진을 재정합 Dialog에 전달 |
| `real2sim_builder/tests/test_asset_view.py`, `test_gripper_mount.py`, `test_numeric_refinement.py` (신규) | 새 기능·실제 Native/Qt·오류/재개 회귀13개 |
| `real2sim_builder/tests/test_stage_video_authoring.py` | 기존 Stage7 fallback fixture를 실제 계약에 맞춰 명시 |
| `real2sim_builder/SCENE_AUTHORING.md`, `docs/studio-integration.md` (신규) | 실행법·변경 경계·검증·미완료 상태 |

기존 Scene/Input/Capture/Calibration/Candidate/Cache/Asset/Export와 Workspace Runtime은 시작 ledger의 **18,347개 파일**을 종료 시 SHA/크기·누락·신규 기준으로 대조해 **변경0·누락0·신규0**을 확인했다. 모든 새 실행 fixture는 진단 또는 pytest 임시 경로에만 만들었다. 기존 측정/q/URDF/Calibration·Asset Version·공유 참조를 재작성하지 않았다. SDK/모델 디스크 전체를 SHA 대조했다는 뜻은 아니다.

브랜치 `feat/simfoundry-style-reconstruction`, HEAD `a978e6e97ddab2682c3754dc50c19909ac8b94d3`는 시작 상태를 유지한다. **19개 파일이 미커밋이며 staged0개**다. Commit/Push/Merge·새 Worktree는 없다. Stage1–8 핵심 함수, DA3 Mixed/CPD, Codex 모델링 및 후반 Stage 등15개 함수 AST가 HEAD와 같음을 대조했다. 변경 Python17개 bytecode 없는 compile, `git diff --check`, 신규 파일까지 포함한 whitespace 검사가 통과했다. 작업 파일의 좁은 인증 리터럴/개인 절대경로 검사에 발견0개, 1MiB 초과 파일0개다. 전체 저장소의 보안 감사라는 뜻은 아니다.

최종 SHA/compile/whitespace/index 대조는 `completion-check.json`, `compile-check.json`, `preservation-after.json`, `change-inventory.json`에 있다. 사용자 데이터·진단·런타임/모델/계정 파일은 소스 변경 목록에 포함하지 않는다. Library·수치 반복 연결의 합성/Native 검증과 실제 사용자 Scene/센서/Isaac/Task의 미검증 상태를 구분하며 전체 프로젝트가 완성됐다고 선언하지 않는다.
