# Object Library — Collision X-Ray Wireframe

> 후속 가독성 개선: 현재 기본값은 [Feature Edges25° / Hidden Opacity20%](object-library-wireframe-readability.md)이며, All Edges와 두 Edge Opacity를 UI에서 선택한다. 아래1,530개/Hidden65% 설명과 실행 수치는 최초 X-Ray 구현 당시 기록이다. 실제 원본 Geometry와 Depth 기반 Visible/Hidden 구분은 계속 유지한다.

2026-11-13. `feat/simfoundry-style-reconstruction`, HEAD `a978e6e97ddab2682c3754dc50c19909ac8b94d3`의 기존 미커밋20개를 보존하고 구현했다. **실제 cup_1/v001의 Visual Texture를 유지하면서 Collision65개 Part의1,530개 삼각형 Edge를 X-Ray로 표시한다.** 원본 Asset/Scene을 편집하지 않았고 Commit/Push·설치·모델 추론·사용자 Scene의 Physics/Task 실행은 하지 않았다.

## 사용 방법

Scene Prepare → **Object Library · 3D 보기** → Object/Version 선택. 목록·검색·버전·Viewport·Candidate 작업 배치는 유지했다.

| 설정 | 기본값 / 동작 |
|---|---|
| Show Visual | ON. 기존 정상 Texture 표면 표시 |
| Show Collision | OFF. 켜야 Edge를 표시함 |
| Collision Mode | X-Ray. Collision OFF 동안 선택은 보존하고 컨트롤은 비활성 |
| Visible Only | 현재 표면보다 앞에 있거나 같은 깊이의 Collision Edge만 청록 실선 |
| X-Ray | 위 청록 실선 + 가려진 Edge를 주황 점선으로 투시 |
| Visual Opacity | 0–100%, 기본100%. Visual 색상의 불투명도만 변경. Shape/Camera/Scale·보임/가림 분류는 유지 |
| Collision Only | Show Visual OFF + Show Collision ON. 원본 Collision 면과 Edge를 표시하며 선택한 Visible Only/X-Ray 정책을 유지 |
| Reset View | Orbit/Zoom/Pan만 초기화. 표시 옵션·Opacity 유지 |

우클릭 드래그 Orbit / 휠 Zoom / 가운데 드래그 Pan은 그대로다. Version 전환 뒤에도 표시 옵션을 유지하며 새 Geometry/Texture/Edge Buffer를 로드한다. Show Visual과 Show Collision을 모두 끄면 자산 표시는 없고 Grid/XYZ만 남는다.

![실제 Object Library에서 cup_1/v001 X-Ray](../workbench_runs/diagnostics/collision_xray_20261113_213859/xray-overlay-ui.png)

## 기존 경로 감사와 변경

`ObjectLibraryDialog → BackendJob → operations.object_library → asset_view.library_action/load_asset_view → verify_object_asset/inspect_usda/_convert → obj_data → AssetViewport`를 확인했다. USDA Converter는 Transform/Material subset/UV를 bake하고 CollisionAPI에 따라 Visual/Collision을 분리한다. `asset_view.py`는 실제 Mesh/Texture를 전달한다. 이번에는 이 경로의 Converter·Asset Loader·원본 USD/PNG를 변경하지 않았다.

이전 GL Overlay는 Collision 표면의 nearest layer만 반투명 합성했다. 이번 요청은 **전체 Collision Wireframe 투시**이므로 그 표시 정책을 명시적인 두 Checkbox/Mode/Opacity로 바꿨다. 기존 GL Depth Buffer/정상 Visual Shader/Qt Widget을 유지하며 CPU 삼각형 Painter로 되돌리지 않았다. Qt의 QPainter는 Grid 설명/XYZ 글자에만 사용한다.

### Edge 구성

`asset_viewport.triangle_edges(vertices, faces)`는 한 Collision Part의 triangle soup에서 정확히 같은 좌표의 vertex만 연결하고, 세 undirected edge를 정렬해 중복 제거한다. UV seam 때문에 인덱스가 다른 같은 좌표도 그 Part 안에서 합친다. 0길이 Edge를 제외하며 모든 삼각형 대각선은 유지한다.

**Part 간 Edge를 합치거나 거리 임계값으로 가까운 점을 지우지 않는다.** 서로 닿은 Part의 독립 경계·얇은 벽·내부 구조가 그대로 남는다. Asset 버전의 points/faces를 다시 쓰는 welding이 아니라 표시용 Edge Buffer의 중복 제거다. Part별 ID와 Edge 수를 진단에 기록했다.

실제 컵은 Visual Shell1개가 Material subset2개/2,048 triangles로 변환되고 Collision은65개/1,020 triangles다. Collision의 unique Edge는 총1,530개이며 GL_LINES의 vertex3,060개로 전달한다. 임의의 Box/Wireframe proxy가 아니다. 전체 삼각형 Edge가 요구되므로 원본의 세밀한 바닥 triangulation과 겹치는 독립 Part 경계는 확대해 검토해야 한다. 선을 보기 좋게 만들기 위해 일부 Part/내부 Edge를 제거하지 않았다.

### 깊이와 Opacity

1. Show Visual이 ON이면 Visual의 Depth를 먼저 구성하고 기존 Texture/조명으로 nearest 표면을 렌더한다. Opacity100%의 기존 표면을 유지한다. 낮은 Opacity는 해당 표면 색을 배경과 합성한다.
2. Show Collision이 ON이면 **모든 Collision 면을 Depth에만 추가**한다. Visual OFF인 Collision Only에서는 이 면을 불투명하게 표시한다. 이 union depth가 Visual·Collision의 자기 가림과 다른 Part의 가림을 판단한다.
3. Edge는 같은 Camera/정규화 좌표로 투영하고 Depth Write를 끈다. X-Ray의 hidden pass는 `GL_GREATER` + 주황(alpha0.65) 점선, visible pass는 `GL_LEQUAL` + 청록 실선이다. Visible Only는 hidden pass만 생략한다.
4. 점선은 Shader에서 Segment 시작점으로부터의 화면 Pixel 거리로 생성한다(10px 주기,5px 표시). 줌할 때 실제 Edge 위치는 유지하고 화면상 점선 간격만 일정하게 유지한다. 보이는 선을 나중에 그려 중첩 지점에서 청록색이 우선한다.
5. 면의 `polygon offset(1,1)`은 같은 표면 Edge의 Z-fighting을 줄이는 래스터 깊이 보정이다. World/Camera/Mesh Transform을 이동시키지 않는다. Grid와 Line은 가림 판정용 Depth를 쓰지 않는다.

Depth Test를 끄고 모든 선을 같은 색으로 덧칠하는 방식이 아니다. Opacity0에서도 Show Visual ON이면 Visual depth를 유지한다. 따라서 선이 가려졌다는 색상 의미가 Opacity에 따라 바뀌지 않는다. Visual 자체를 가림 판단에서 제외하려면 **Show Visual을 OFF**한다. 임의 다층 투명 Material/PBR의 물리적 광전달을 새로 구현한 것은 아니다.

사용한 계약은 [Khronos glDepthFunc](https://raw.githubusercontent.com/KhronosGroup/OpenGL-Refpages/main/gl4/glDepthFunc.xml), [polygon offset](https://raw.githubusercontent.com/KhronosGroup/OpenGL-Refpages/main/gl4/glPolygonOffset.xml), [GLSL4.10 interpolation/Shader](https://registry.khronos.org/OpenGL/specs/gl/GLSLangSpec.4.10.pdf), [Qt6.11 GL 자원 수명](https://doc.qt.io/qt-6.11/qopenglwidget.html#resource-initialization-and-cleanup)을 대조했다. 기존 OpenGL4.1/NVIDIA 환경을 재사용하며 추가 설치는 없다.

## 실제 컵 GUI 산출물

아래 PNG는 **기존 cup_1/v001을 실제 ObjectLibraryDialog/BackendJob/GL로 읽고 컨트롤을 조작해 캡처한 이미지**다. AI 생성 UI 이미지나 새로 모델링한 컵이 아니다. 각 PNG의 `-ui.png`는 컨트롤을 포함한 실제 Dialog 화면이다. 선택된 Candidate 목록을 읽었지만 추가/버전 지정/등록 버튼은 실행하지 않았다.

| 이미지 | 표시 내용 |
|---|---|
| [Visual Only](../workbench_runs/diagnostics/collision_xray_20261113_213859/visual-only.png) | 정상 Texture Visual만 표시, 새 기본값 |
| [Collision Only](../workbench_runs/diagnostics/collision_xray_20261113_213859/collision-only.png) | 실제 Collision 면 + Edge만 표시. Visual 없음 |
| [Visible Only Overlay](../workbench_runs/diagnostics/collision_xray_20261113_213859/visible-only-overlay.png) | Visual 위의 보이는 청록 Edge만 표시, 숨은 선은 제외 |
| [X-Ray Overlay](../workbench_runs/diagnostics/collision_xray_20261113_213859/xray-overlay.png) | Visual + 청록 앞 Edge + 주황 점선 뒤/내부 Edge |
| [위에서 본 X-Ray](../workbench_runs/diagnostics/collision_xray_20261113_213859/top-xray.png) | Pitch80°. 열린 내부·안쪽 벽·바닥 triangulation과 가려진 경계 |
| [측면 X-Ray](../workbench_runs/diagnostics/collision_xray_20261113_213859/side-xray.png) | Pitch0°. 외벽 뒤의 Collision Edge까지 투시 |
| [Opacity45%](../workbench_runs/diagnostics/collision_xray_20261113_213859/opacity-45.png) / [0%](../workbench_runs/diagnostics/collision_xray_20261113_213859/opacity-0.png) | 같은 Camera/Geometry에서 Visual 색상만 감소. 선 위치·깊이 분류 유지 |
| [마우스 조작 후](../workbench_runs/diagnostics/collision_xray_20261113_213859/mouse-orbit-zoom-pan.png) | 실제 우클릭·휠·가운데 드래그 후 결과 |

![실제 컵의 여섯 표시/시점 비교](../workbench_runs/diagnostics/collision_xray_20261113_213859/modes-overview.png)

외벽/내벽/바닥은 **실제 저장된 Collision 형상**을 보여 준다. 물체의 Collision이 실제 하드웨어와 정확히 맞는지 또는 컵 삽입이 가능한지는 이 화면으로 인증하지 않는다. 기존 `AUTHORED_UNVALIDATED` 상태를 유지한다.

실제 RTX4060 Laptop OpenGL4.1/24bit Depth Buffer에서 65개 Part/1,530 Edge를 처리했고 GL error0이었다. GUI heartbeat115회, 원본 Payload SHA 불변, 닫기 후 Buffer/Texture/VAO/Shader 해제를 확인했다. 실제 마우스 회전·확대·Pan·Reset과 두 Checkbox/Mode/Opacity를 조작했다. Header/Backend/SHA 검증의 상세 수치는 `gui-check.json`에 있다.

Visual Only 회귀는 이전 정상 GL 구현의 보존본과 **동일 cup payload/766×424/Camera에서 Grid·축만 제외해 직접 대조**했다. **변경 Pixel0, 최대 Channel 차0**이었다(`visual-regression.json`). 이전 저장 PNG의 Grid/축까지 포함한 별도 비교에는35Pixel 차이가 있어, 자산 표면 보존과 화면 장식 차이를 구분했다. 앞선 Blender 비교를 이번 Shader 변경의 독립 새 Blender 실행으로 표시하지 않는다.

## 테스트

새 기능을 먼저 실패하는 테스트로 만들었다. RED에서는 Edge 함수 부재, 숨은 선 미표시, Opacity 미반영 및 UI 속성 부재를 확인했다. GPU 구현 뒤 다음을 검사했다.

- Triangle soup의 공유 Edge/반복 면 중복 제거, 서로 다른 두 Part의 같은 경계 보존.
- Visual 뒤에 숨은 Edge는 Visible Only에서 제외하고 X-Ray에서 주황 점선으로 표시. 반대 방향으로 회전하면 같은 Edge가 청록색으로 전환.
- Opacity0에서 같은 가림 분류 유지, Show Collision OFF에서 hidden/visible pass 모두 미표시.
- Coplanar Edge가 주황색으로 오판되지 않으며 반복 Face를 추가해도 화면이 겹쳐 진해지지 않음.
- Opacity0/50/100의 실제 Pixel 합성, 데이터/Transform/Scale 불변, Reset이 표시 설정을 유지.
- 실제 Native Asset v001(red)→v002(blue)→v001 전환과 Show/Mode/Opacity 유지, 이전 버전 SHA 불변.
- Edge VBO를 포함한 버전 변경/종료 GL 자원 해제, 기존 Texture/마우스·Native Asset 회귀.

**집중26개 통과**, 13.90초(`release-focused-verified.xml/log`). 기존8개 Library/Viewer 검사와14개 Native Asset 검사에 새4개가 더해진 수치다. 중간 RED/Green은 합산하지 않는다. UI 검사 중 Opacity 변경 직후 이전 Frame을 읽은 Harness는 repaint 완료를 기다리도록 수정했다. Coplanar Edge 색 검사에서 하단 LCD 안티앨리어싱 글자를 선으로 집계한 경우는 3D 영역으로 한정해 교정했다. 실제 선은 정상임을 Probe PNG로 확인했고 가림 기준을 완화하지 않았다.

세 패키지 최종 전체 회귀는 **1,856 passed / 실패0 / 오류0 / skipped0**, Console 기준 **550.09초**, 프로세스 종료 코드0이었다(`release-full.xml/log`, `release-exit.json`). 기존1,852개에서 새4개가 늘었다. 경고5개는 기존 torchvision 영상 경고4개와 JUnit record_property 기록 경고1개다. 실행 중 소스/시험 **357개 Python SHA 변경0**을 대조했다. 중간 집중·RED/Green 수치를 최종 전체에 합산하지 않는다.

```bash
REAL2SIM_BLENDER=/PATH/TO/EXISTING/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -vv --tb=short
```

첫 전체 실행은 약31%에서 SIGTERM(returncode143)으로 종료돼 JUnit이 없었다. 직접 원인은 UNKNOWN이며 pytest의 실패 Assertion 보고는 없었다. 당시 소스 SHA도 불변이었다. 그 로그를 `release-interrupted.log`로 보존하고, 기존 wrapper를 별도 process session에서 상세 로그로 실행한 위 최종 결과와 구분한다. 제품 실행기를 바꾼 것이 아니며 중단 실행을 통과로 표시하지 않는다.

GPU 확인은 실제 X11 Qt Context에서 수행했다. Offscreen QPA에서 성공한 것처럼 Mock으로 대체하지 않았다. 기존 전체 회귀의 합성 MuJoCo Step/Runner·Native Asset/Sandbox 검사를 사용자 컵의 물리·파지·Task 성공으로 해석하지 않는다. DA3/SAM/FLUX/PDA/Bria·Codex 온라인·실제 Isaac/실물 Robot·사용자 Scene Task는 실행하지 않았다.

## 파일과 보존

이번 제품 수정은 기존 `asset_viewport.py`(Edge/Depth/Opacity/해제)와 `object_library.py`(표시 컨트롤)다. `asset_view.py`, USD Converter, Scene/Asset/URDF/Capture/실측·Calibration 경로는 그대로다. 기존 `test_asset_view.py`는 새 표시 정책에 맞춰 같은 보호 조건을 검사하고, 새 `test_collision_xray.py`에 GPU 회귀4개를 추가했다. 이 문서와 기존 사용 문서에 현재 동작을 기록한다.

보호 기준선의 기존 Scene/Input/Capture/Candidate/Asset/Export 및 Workspace Runtime **18,347개 파일**을 종료 시 SHA/크기·누락·신규 기준으로 대조해 **변경0·누락0·신규0**을 확인했다. 원본 컵 Entry SHA256도 시작·종료 모두 `f1d6a0634a2465f715261e163b9515777d75f58de9be24396c5eb5f9d98f49cd`다. 전체 SDK/모델 디스크의 전수 대조를 뜻하지 않는다.

시작 미커밋20개 중 Viewer/UI·관련 테스트와 문서5개만 이번 범위에서 수정했고, 나머지15개는 byte 단위로 그대로다. 신규 파일은 `test_collision_xray.py`와 이 문서2개다. 현재 **22개 미커밋 파일, staged0개**이며 브랜치/HEAD/Index 불변이다. Commit/Push/Merge·Reset/Clean·새 Worktree는 없다. 변경 Python18개 bytecode 없는 compile, `git diff --check`, 신규 파일을 포함한 whitespace 검사도 통과했다. 좁은 인증 리터럴·개인 절대경로 검사 발견0개이며 전체 저장소 보안 감사라는 뜻은 아니다.

보존·변경 경계 근거는 `preservation-after.json`, `release-source-after.json`, `task-boundary.json`, `task-only.patch`, `change-inventory.json`, `completion-check.json`에 있다. Asset Loader/Converter와 이전 수치 정합·Runtime 기능은 재작성하지 않았다.

진단은 Git 제외 `workbench_runs/diagnostics/collision_xray_20261113_213859/`의 baseline_sources/patch, RED/GREEN/JUnit, 실제 GUI PNG·JSON, Visual 회귀 대조와 보존 ledger에 있다. 제품은 이 진단을 import하지 않는다. Desktop OpenGL4.1 이상과 실제 GL Context 요구는 기존과 같고, 복잡 PBR/임의 투명 Material·실물 물리 정확도는 별도 검증이다.
