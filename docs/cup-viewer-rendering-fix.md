# cup_1/v001 Viewer 렌더링 수정

> 후속: 현재 Object Library는 [Collision X-Ray Wireframe](object-library-collision-xray.md)의 Show/Mode/Opacity UI를 사용한다. 아래 nearest Collision 면의 투명 Overlay 설명은 최초 GPU 수정 당시 기록이며, 정상 Visual/Depth Buffer 경로는 계속 유지한다.

2026-11-13. `feat/simfoundry-style-reconstruction`, HEAD `a978e6e97ddab2682c3754dc50c19909ac8b94d3`의 기존 미커밋19개 위에서 진행했다. **줄무늬와 잘못된 가림은 Viewer 결함으로 재현됐으며, 원본 USDA를 바꾸지 않고 Qt OpenGL 표시 경로로 수정했다.** 실제 Cup/GUI 결과와 합성 회귀를 아래에서 구분한다. Commit/Push·설치·모델 추론·사용자 Scene 재구성은 하지 않았다.

## 재현과 원인

경로는 `SceneInputs → ObjectLibraryDialog → BackendJob → operations.object_library → asset_view.library_action/load_asset_view → verify_object_asset/inspect_usda/_convert → obj_data → AssetViewport`다. USD/PNG 변환은 기존 백엔드 프로세스에서 실행한다. 원본 Texture와 Material Binding, material subset, Transform, CollisionAPI 분리는 기존 Converter를 그대로 사용한다.

실제 입력은 공용 Library의 `cup_1/v001/usd/cup_1.usda`다. Native USD에는 Visual Shell1개/1,024개 polygon, Collision65개가 있다. 기존 Converter는 Material subset에 따라 Visual2개/2,048 triangles와 Collision65개/1,020 triangles로 전달한다. Viewer의 총67개 part는 이를 읽은 것이며 67개의 새 Object를 만들었다는 뜻은 아니다. 원본 Shell은 rightHanded, doubleSided=true, subdivision=none, faceVarying normals4,096개다. 원본 PNG2개는 각각512×512이며 Alpha는 전 Pixel255다. 원본 컵의 Texture 투명도 때문에 생긴 줄무늬가 아니다.

같은 원본 USDA를 **Blender 5.2.2 LTS의 Native USD Import → Cycles CPU**로 직접 읽었다. Converter 결과를 Blender의 원본 대조로 사용하지 않았다. Collision은 원본 visibility/용도에 맞게 별도로 제외했다. 반면 Viewer는 실제 Converter의 Mesh/UV/Texture를 사용했다. 렌더링은 새 진단 폴더에만 저장하고 Blend/Asset 버전을 저장하지 않았다.

| 분리 실험 | 실제 결과 | 판정 |
|---|---|---|
| 기존 Flat Shading + Texture | 컵 표면 전반에 가느다란 줄무늬 | 증상 재현 |
| Texture만 비활성 | 같은 Mesh에 줄무늬가 사라짐. 내·외벽 가림 문제는 별도 | Mesh 자체 파손으로 볼 근거 없음 |
| Lighting만 비활성 | 줄무늬가 남음 | Flat Shading이 주원인은 아님 |
| QRegion 정수 Clip만 부동소수 QPainterPath로 변경한 진단 | 큰 줄무늬 감소. 글자가 내부/뒷면에서 비정상적으로 나타나는 문제는 남음 | `poly.toPolygon()`/정수 영역의 삼각형별 Texture Clip 틈이 확인된 원인 |
| 평균 Triangle 깊이 정렬만 반전 | 일부 면이 바뀌지만 교차/얇은 벽의 올바른 가림은 보장되지 않음 | 정렬 방향 조정만으로 해결 불가 |
| 교차하는 두 Triangle의 최소 재현 | 앞면 색이 좌/우에서 달라야 하나 기존 Viewer는 양쪽 모두 파랑. 제출 순서에 의존 | 픽셀별 Depth가 없는 Painter 방식의 결함 |
| Backface Culling 분리 | 수정 후 양면/뒷면 제거 결과는212픽셀 차이. 줄무늬 재발 없음 | 원본 Shell은 doubleSided이므로 기본 양면 표시 유지. Backface를 숨겨 문제를 감추지 않음 |
| Visual / Collision / Overlay 분리 | 줄무늬는 Visual만 표시해도 발생. Overlay와 독립 | Collision이 Visual에 섞여 생긴 문제가 아님 |
| 투명 Collision의 앞·뒤 Triangle/제출 순서 | 수정 후 가장 앞의 보이는 층만 합성, 제출 순서와 후면 추가가 결과를 바꾸지 않음 | Depth prepass로 투명 누적/가림 결함 수정 |

기존 카메라 기저도 determinant=-1이었다. 화면 X/Y 축과 깊이 축이 오른손 Camera로 일치하지 않았다. **수정 후 determinant=+1의 직교 기저를 사용하며 양의 Pitch는 컵 위에서 내려다본다.** 원본 Object 좌표/UV/World Pose를 바꾼 것이 아니다. 비교에는 화면 X/Y projection과 ortho scale을 명시적으로 맞췄다. 같은 UI 숫자만 보고 같은 Camera라고 가정하지 않았다. 기존 Painter의 pitch=-30과 수정 View의 pitch=+30이 비교 이미지의 같은 projection이다. 정확한 기준 Camera-to-World는 `blender-reference.json`에 저장했다.

![같은 projection의 기존 Viewer / Native Blender / 수정 Viewer](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/before-after-reference.png)

![Texture·조명·Clip·Overlay 분리 실험](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/ablation-comparison.png)

## GPU Viewport 선택과 구현

설치된 GUI 환경은 PyQt6 **6.11.0**, Qt **6.11.2**다. PyOpenGL/VTK/PyVistaQt는 없다. 공개 문서와 실제 설치 Binding을 대조했고 새 패키지를 설치하지 않았다.

| 대안 | 현재 환경 / 변경량 | 선택 |
|---|---|---|
| QPainter 정렬/Clip 보완 | 설치 불필요. Triangle 내부에서 앞뒤가 교차하는 경우 전체 면 순서로 정답 표현 불가 | 제외 |
| QOpenGLWidget + Qt OpenGL | 기존 PyQt6에 포함. 기존 QWidget 위치에 내장하고 Mouse/Signal·Backend 유지 가능 | **적용** |
| QOpenGLWindow | 기존 Qt에 있으나 QWidget UI에는 Window Container 경계가 추가됨 | 현재 Dialog에는 불필요 |
| PyVistaQt/VTK | 기존 환경 미설치. QtInteractor와 별도 VTK/PyVista 계층 필요 | 설치/의존성 증가를 피함 |
| Qt Quick 3D | QML Scene Graph와 Geometry/Texture 전달 계층이 필요. 현재 Widgets UI의 변경 범위가 커짐 | 이번 범위에서 제외 |

근거: [Qt 6.11 QOpenGLWidget](https://doc.qt.io/qt-6.11/qopenglwidget.html), [QOpenGLWindow](https://doc.qt.io/qt-6.11/qopenglwindow.html), [PyVistaQt QtInteractor](https://qt.pyvista.org/usage.html), [Qt Quick 3D](https://doc.qt.io/qt-6.11/qtquick3d-index.html). 이 비교는 설치된 환경과 현재 Widget 통합 범위에 대한 판단이며 모든 플랫폼의 성능 비교가 아니다.

`asset_viewport.py`의 표면 표시를 `QOpenGLWidget`/VBO/Shader/Depth Buffer로 교체했다. 개인 경로, 새 Launcher/Asset 저장소/Simulator Sensor는 추가하지 않았다.

- 정규화된 실제 Mesh 좌표와 Float UV를 GPU로 전달한다. Triangle별 정수 Clip과 CPU Texture 합성을 제거했다. GPU Texture sampling, 반복 Wrap, mipmap과 선형 Filter를 사용하며 원본 PNG는 그대로다.
- Opaque Visual/Collision은 픽셀별 Depth Test/Write를 사용한다. 평균 깊이 정렬을 사용하지 않는다. 실제 Camera 기저를 오른손으로 통일했다.
- Overlay는 Visual을 렌더한 뒤 Collision의 depth-only pass → 같은 nearest depth에만 반투명 색 합성을 한다. 숨은 뒷벽을 X-ray처럼 표시하거나 Triangle 순서대로 겹겹이 투명 합성하지 않는다. Collision 모드는 원본 Collision만 불투명하게 표시한다.
- Flat normal 기반 간단한 양면 조명을 유지한다. 원본 smooth normals/PBR/그림자/금속성·roughness·투명 Material의 완전한 재현은 이번 수정 범위가 아니다. 이 차이는 줄무늬/가림 결함과 구분한다. 원본 컵의 두 diffuse Texture는 정상 표시된다.
- Grid/Local XYZ/Scale은 유지했다. 3D 표면은 GL로, 글자만 QPainter로 표시한다. 우클릭 Orbit, 휠 Zoom, 가운데 Pan, Reset, mode/version 선택 및 기존 rendered/error Signal을 유지했다.
- 버전 갱신 시 이전 VBO/Texture를 current context에서 해제하고 다시 업로드한다. 닫기와 context 파괴에서도 Buffer/Texture/Shader/VAO를 명시적으로 해제한다. Qt의 [자원 해제 계약](https://doc.qt.io/qt-6.11/qopenglwidget.html#resource-initialization-and-cleanup), [Texture API](https://doc.qt.io/qt-6.11/qopengltexture.html)를 따르며 별도 PyOpenGL 설치는 없다.
- 기존 USD 로딩/변환은 BackendJob에 남는다. GPU Buffer는 Asset 변경 시 갱신하고 Mouse 조작마다 USD를 다시 읽지 않는다. 복잡 자산 전체의 성능 검증을 완료한 것은 아니다.

실제 Desktop X11 Context는 **NVIDIA RTX4060 Laptop / OpenGL4.1.0 / driver580.178.04**, 기본 FBO Depth attachment **24bit**다. 실제 GUI에서 `glGetError=0`과 context/버퍼 상태를 확인했다. 최초 진단의 구형 `GL_DEPTH_BITS` query는 Core Context에서 지원되지 않아 값을 폐기했다. PyQt에 노출되지 않은 FBO depth-size query만 진단 스크립트에서 기존 Context의 공식 함수 주소로 조회했다. 제품은 그 ctypes query에 의존하지 않는다.

## Blender 비교와 실제 GUI 확인

조명/Normal/PBR 차이가 Texture 정합을 가리지 않도록 **Native Blender emission**과 **Viewer unlit diffuse**도 따로 비교했다. 같은 projection의 766×424 이미지에서 컵의 cream/red 색 기반 ROI Mask IoU는 **0.98126**, 경계를 한 Pixel 제외한31,015개 내부 Pixel의 RGB 평균 절대차는 **0.500 /255**, 최대 Channel 차는69였다. 색 기반 Mask·AA/필터·경계의 차이가 포함된 비교이며 정확한 Geometry silhouette GT나 물리/실측 정확도 지표는 아니다. 정상 렌더러와 비슷해 보인다는 말만으로 원본 품질을 인증하지 않는다.

![조명 제외 Native Blender / GL Texture 비교](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/unlit-reference-comparison.png)

실제 **ObjectLibraryDialog → 실제 BackendJob → cup_1/v001**에서 다음을 실행했다. 기존 공용 자산을 읽기만 했고 Candidate/Asset을 새로 저장하지 않았다.

| 동작 | 실제 결과 |
|---|---|
| Native USDA 로딩 | Visual2 + Collision65 part, 총67개 |
| 우클릭 드래그 | yaw35→75°, pitch30→40°, 화면 변경 |
| 휠 | Zoom1→1.15 |
| 가운데 드래그 | Pan [0,0]→[30,20] px |
| Reset | Zoom1, Pan[0,0], 기본 Orbit 복원 |
| Visual / Collision / Overlay | 실제 UI Combo를 전환해 각 PNG 저장. 컵 내부/외벽·Collision 분리 확인 |
| UI 응답 | 검사 동안 10ms Timer heartbeat97회. 대형 Mesh FPS 보장은 아님 |
| 종료 | glIsBuffer/glIsTexture로 소유 Buffer/Texture 해제 확인, Shader/VAO·payload 해제 |
| Version | 합성 Native 자산 v001(red)→v002(blue)→v001을 실제 Library Combo로 로딩. 이전 Version 파일 SHA 불변 |

- [실제 Library 창](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/gui-library-default.png)
- [회전 후 컵](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/gui-cup-orbit.png)
- [확대·이동 후](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/gui-cup-zoom-pan.png)
- [실제 GUI Visual](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/gui-cup-visual.png), [Collision](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/gui-cup-collision.png), [Overlay](../workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/gui-cup-overlay.png)

## 회귀와 보존

실패를 먼저 재현한 `depth-red.xml/log`에서 좌/우 모두 파란색으로 나왔다. 수정 후 교차 Triangle/제출 순서 반전이 통과했다. 추가로100개 가는 strip의 모든 내부 Pixel에 Texture 색이 연속되는지, version reload, 실제 GPU Buffer/Texture 삭제와 투명 Collision의 nearest layer를 검사한다. 기존 Mouse·Texture·Library·Asset 불변 검사도 유지했다.

**집중22개 통과**, 10.52초(`release-viewer-assets.xml/log`). 기존 CPU 그림 검사를 없애서 성공시키지 않았다. 두 실제 Viewer 검사는 offscreen QPA 대신 실제 Desktop `xcb`/GPU Context에서 같은 Mouse/UV/해제 검사를 실행하며 기준을 강화했다. 화면이 없는 환경에서 이를 실제 GPU 검사 성공으로 표시하지 않는다.

세 패키지 전체 회귀는 최종 소스를 고정해 **1,852 passed / 실패0 / 오류0 / skipped0**, Console 기준 **547.10초**였다(`release-full.xml/log`). 경고5개는 기존 torchvision 영상 경고4개와 JUnit record_property 경고1개다. 세 패키지 소스/시험 **356개 Python SHA 변경0**을 확인했다. 중단된 첫 전체 실행은 약31%에서 종료돼 `release-interrupted.log`로 보존했으며 완료 수치에 합산하지 않는다.

```bash
REAL2SIM_BLENDER=/PATH/TO/EXISTING/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short
```

종료 후 보호 ledger **18,347개 파일의 SHA/크기 변경0·누락0·신규0**을 대조했다. Scene/Input/Capture/Calibration/Candidate/Cache/Asset/Export 및 Workspace Runtime 범위이며 SDK/모델 디스크 전체의 전수 대조라는 뜻은 아니다. 컵 원본 Entry SHA256은 시작·종료 모두 `f1d6a0634a2465f715261e163b9515777d75f58de9be24396c5eb5f9d98f49cd`다. 기존 미커밋19개 중 이번 Viewer/시험/문서에 필요한6개만 수정했고 나머지13개는 byte 단위로 그대로다. 신규 파일은 이 보고서1개다.

브랜치/HEAD/Index는 시작 상태를 유지한다. 현재 **20개 미커밋 파일, staged0개**이며 Commit/Push/Merge·Reset/Clean·새 Worktree는 없다. 변경 Python17개의 bytecode 없는 compile 및 `git diff --check`가 통과했다. 최종 `preservation-after.json`, `release-source-after.json`, `task-boundary.json`, `task-only.patch`, `change-inventory.json`, `completion-check.json`에 근거가 있다.

AI 모델 Forward·Isaac·실물 Robot·Task는 실행하지 않았다. Blender CPU 참조 렌더와 Qt의 실제 GPU 표시를 구분한다.

이번 제품 수정은 `asset_viewport.py`(실제 렌더), `asset_view.py`(표시 지원 범위 설명), `object_library.py`(상태 문구)이며 기존 Converter/Material/Collision 분리 코드는 변경하지 않았다. `test_asset_view.py`와 이 문서·기존 사용 문서에 결과를 남긴다. 이전 기능의 미커밋 구현을 되돌리지 않았다.

## 지원 범위와 사용

기존 Scene Prepare의 **Object Library · 3D 보기**에서 같은 `cup_1`/`v001`을 선택한다. 새 버전 생성이나 모델 재구성은 필요 없다. 세 보기 모드와 Mouse 조작은 이전과 같다.

**Desktop OpenGL4.1 이상과 Qt OpenGL Context가 필요**하다. 현재 Ubuntu22.04/X11/NVIDIA에서 실제 확인했다. QPA `offscreen`은 이 Widget의 GPU Context를 제공하지 않으므로 명시 오류를 표시한다. 잘못된 CPU 정렬 방식으로 자동 후퇴하지 않는다. Wayland/macOS/원격 Headless GL 환경·OpenGL ES·모든 복잡 PBR Material은 미검증/미지원이다. 패키지/Driver를 자동 설치하지 않는다.

열린 컵 내부가 보이는 것과 실제 Gripper 충돌·컵에 블록이 들어가는 물리 성공은 다르다. 기존 `AUTHORED_UNVALIDATED` Collision 상태를 유지하며, 원본 Geometry/실측/Scene·Asset SHA를 보존한다. 불확실한 원본 형상이나 물리 성능을 Viewer 수정으로 완료 처리하지 않는다.

진단은 Git 제외 `workbench_runs/diagnostics/cup_viewer_fix_20261113_151359/`에 있다. baseline_sources/patch, Blender 참조·Camera Matrix, 원본 Metadata, Before/After/ablation PNG, GUI 조작/GL resource JSON, RED/GREEN/전체 회귀·보존 대조를 포함한다. 제품은 진단 폴더를 import하지 않는다.
