# Object Library — Feature Edges와 Wireframe 가독성

> 최신 UI(2026-11-14): 기본 화면은 Visual100% / Collision Front0% / Collision Hidden0%의 세 슬라이더다. Mode/Angle/Collision Only와 추가 자산 정보는 접힌 [Advanced / Debug](object-library-viewer-ui.md)에 있다. 아래 Hidden20% 초기값과 컨트롤·회귀 수치는 당시 Wireframe 구현 기록이다. Feature 수학과 실제 원본 Geometry는 유지한다.

> 2026-11-14 후속 UI 정리: 자산 설명은 **크기와 충돌 검증 상태 한 줄만** 표시한다. 메모 원문·SHA·Material/렌더러 설명과 Viewport 하단의 기술 문구를 제거했고 상세 정보 UI는 추가하지 않았다. [현재 블록 UI](../workbench_runs/diagnostics/object_library_summary_20261113_235958/block_blue-summary.png) · [현재 컵 UI](../workbench_runs/diagnostics/object_library_summary_20261113_235958/cup_1-summary.png). 기존 Asset View 집중8개 통과(8.94초), 실제 블록/컵 Preview에서 표시·겹침 없음·종료를 확인했다. 아래 전체 회귀와 이전 UI 캡처는 Wireframe 구현 당시 기록이며 이번에는 전체 회귀를 반복하지 않았다.

2026-11-13. `feat/simfoundry-style-reconstruction`, HEAD `a978e6e97ddab2682c3754dc50c19909ac8b94d3`. 기존 미커밋22개를 보존한 상태에서 Viewer/UI와 관련 테스트·문서만 보완했다. **실제 cup_1/v001에서 All Edges1,530개를 유지하고, 기본 Feature Edges25°에서는 같은 시점의 주요 윤곽398개를 표시한다.** Hidden Opacity 기본값은20%다. Asset/Scene/URDF/Capture·실측·Reconstruction·Calibration·Physics·Robot Control을 수정하지 않았다. 설치·모델 추론·Commit/Push는 없다.

## 현재 UI와 사용

Object Library의 기존 검색/목록/Version/Viewport 배치를 유지한다. **Show Collision**을 켜면 X-Ray + Feature Edges + 낮은 Hidden Opacity로 시작한다.

| 설정 | 초기값 / 범위 |
|---|---|
| Show Visual / Show Collision | ON / OFF |
| Collision Mode | X-Ray. Visible Only도 유지 |
| Edge Mode | **Feature Edges**. All Edges로 기존 전체 삼각형 진단 가능 |
| Feature Angle | **25°**, 0–180°. All Edges에서는 비활성 |
| Visible Edge Opacity | **100%**, 0–100% |
| Hidden Edge Opacity | **20%**, 0–100%. X-Ray에서만 활성 |
| Visual Opacity | 기존100%, 0–100% |
| Collision Only | 기존 Collision 면과 선택한 Edge를 단독 표시 |
| Reset View | Camera만 초기화. 표시 옵션 유지 |

우클릭 Orbit / 휠 Zoom / 가운데 Pan을 유지했다. Version 변경 뒤에도 옵션은 유지한다. Visual Opacity는 형상이나 깊이 분류를 바꾸지 않는다. Edge Opacity는 선 색상의 Alpha만 바꾸며, Hidden0%는 Visible Only와 같은 숨은 선 제외 결과를 낸다. Collision Only의 불투명한 **면**과 Edge Opacity는 별개다.

![같은 실제 컵·Camera·Zoom의 All / Feature / 낮은 Hidden 강조 비교](../workbench_runs/diagnostics/wireframe_features_20261113_223252/before-after.png)

왼쪽은 이전 촘촘한 설정(All/Hidden65%), 가운데는 같은 Hidden65%에서 Feature25°만 적용한 결과, 오른쪽은 Feature25°/Hidden20% 새 기본 표시다. Geometry 선택과 Opacity 효과를 분리한 비교이며 새로 모델링한 컵이나 AI 생성 UI 이미지가 아니다.

## 기존 실행 경로와 변경 경계

`ObjectLibraryDialog → BackendJob → operations.object_library → asset_view.load_asset_view → verify_object_asset/inspect_usda/_convert → obj_data → AssetViewport`를 확인했다. 기존 Converter가 실제 USD Transform/Material/UV와 CollisionAPI를 분리하고, `asset_view.py`가 실제 Mesh/Texture를 전달한다. 이 경로와 원본 자료는 그대로다.

변경은 기존 GL Viewer의 Edge 선택과 Uniform/UI 전달이다. 별도 Renderer·3D Framework를 추가하거나 QPainter 삼각형 표시로 되돌리지 않았다. 새 `ui/collision_wireframe.py`는 **표시용 NumPy 인접성 계산만** 소유하며 USD 로딩·저장·렌더·Scene 작업을 수행하지 않는다.

## Edge 선택 방식

### All Edges

Part 내부에서 정확히 같은 좌표를 공유하는 Triangle Edge를 중복 제거한다. 모든 유효 Triangle의 Edge와 대각선을 유지하고, Part 사이의 독립 경계를 임의 연결하지 않는다. Zero-area Triangle과 동일한 중복 Triangle은 분석에서 제외한다. 실제 컵에는 이 두 종류가 없으며 기존1,530개 Edge가 그대로다.

### Feature Edges

1. Triangle soup를 exact coordinate 기준으로 분석하고 Edge별 인접 Face와 단위 Normal을 저장한다. 원본 vertices/faces를 변경하는 welding은 아니다. Triangle 크기에 대한 상대적인 부동소수 한계로 Zero-area/degenerate Normal을 제외하며 NaN Normal을 만들지 않는다.
2. Boundary Edge는 유지하고, Face가3개 이상 붙는 Non-manifold Edge도 유지한다. 두 Face가 붙는 Edge는 Normal 사이 각도가 선택한 Feature Angle 이상일 때 남긴다. 같은 평면의 triangulation 대각선은 제외한다.
3. **Part ID나65개라는 개수를 Feature 근거로 사용하지 않는다.** 닫힘·일관된 winding·0이 아닌 부피를 확인한 Part에서, 같은 경계를 가진 반대 방향의 면 패치가 정확히 맞닿을 때만 표시 분석상 내부 접합면으로 처리한다. 삼각형 대각선이 달라도 coplanar patch의 경계로 비교한다.
4. Part 사이에 새 Edge를 만들거나 거리 임계값으로 떨어진 점을 붙이지 않는다. 접합이 입증된 경우에도 선택되는 모든 선분은 원본 Triangle Edge의 부분집합이다. 열린/Non-manifold/모호한 다중 접합·일치하지 않는 Part 경계는 보수적으로 유지한다. 임의의 겹침을 Boolean Union/CSG로 고치는 기능은 아니다.
5. 정상적으로 닫힌 Part의 signed volume으로 분석 Normal 방향을 맞춘다. 면 방향이 반대인 동일 Solid 두 개를 내부 접합으로 오인해 전체 윤곽을 지우지 않도록 검사한다. **원본 면 순서나 표시용 표면 Geometry를 바꾸지 않는다.**
6. 각도만으로 Edge를 지우지 않는다. 카메라 방향에 대해 인접 Normal의 앞/뒤 부호가 바뀌는 Edge를 **Silhouette**으로 추가한다. 따라서 완만한 곡면에서도 외곽 윤곽이 남고 Orbit에 따라 갱신된다. Boundary와 구조적 Edge는 Angle과 무관하게 유지한다.

실제 컵은65개 Collision Part/1,020개 Triangle이며, 정확한 접합 패치63쌍을 확인했다. 이 분석과 각도·Silhouette 선택으로 기본 시점의1,530개가398개로 줄었다(**약74% 감소**). 원본에 정확히 일치하지 않는 접합이나 작은 틈을 임의로 수리하지 않는다. 남은 선을 실제 물체의 물리적 Feature로 인증하는 기능도 아니다.

Feature/Boundary/Non-manifold 구분과 시점 기반 Silhouette의 기준은 [VTK Feature Edges 정의](https://vtk.org/doc/nightly/html/classvtkFeatureEdges.html), [VTK Silhouette 정의](https://vtk.org/doc/nightly/html/classvtkPolyDataSilhouette.html)를 대조했다. **VTK는 설치하거나 사용하지 않았다.** 현재 NumPy/Qt 코드를 확장한 구현이며 해당 Framework와 모든 세부 동작이 같다고 주장하지 않는다.

## Cache·Shader·Depth

- Asset/Version Payload를 로드할 때만 면의 인접성·Normal·접합·전체 Edge를 계산한다. 이 Cache는 현재 Viewer가 소유하고 Version 전환/닫기에서 해제한다. 진단 폴더나 별도 Runtime Cache를 제품 의존성으로 사용하지 않는다.
- Feature Angle 변경은 저장된 cosine/구조적 Edge에서 정적 Mask만 갱신한다. Orbit은 저장된 Normal로 Silhouette Mask만 계산한다. 선택 집합이 같으면 Feature VBO도 다시 쓰지 않는다. Zoom/Pan은 정규화 좌표의 선을 그대로 투영한다.
- 전체 Mesh/Texture/All Edge VBO는 설정 변경 때 다시 업로드하지 않는다. 필요한 경우 **선택된 Feature Edge VBO만** 갱신한다. Opacity는 Uniform/Blend 상태만 바꾼다.
- 기존 Visual/Collision union Depth를 유지한다. Visible Edge는 `LEQUAL`의 Cyan, Hidden은 `GREATER`의 Orange 점선이다. 두 pass 모두 선의 Depth Write를 끈다. 0%는 해당 pass를 생략하고100%도 기존 Alpha Blend/Depth 구분을 유지한다. [Khronos Blend 계약](https://raw.githubusercontent.com/KhronosGroup/OpenGL-Refpages/main/gl4/glBlendFunc.xml)을 사용한다.
- 기존 polygon offset과 표면 Texture 표시를 유지했다. 모드 변경 후 Depth Write/Blend 및 GL 오류를 검사했다. 기존 [Qt GL 자원 해제 계약](https://doc.qt.io/qt-6.11/qopenglwidget.html#resource-initialization-and-cleanup)에 따라 Feature VBO·Topology Cache도 해제한다.

실제 GUI에서 Edge Mode/Angle/세 Opacity·Mouse를 변경하는 동안 **Backend 호출0회**, 같은 Topology 객체와 Visual/Collision/All VBO ID 유지, 원본 Payload SHA 불변을 확인했다. 실제 컵의 Topology 계산 표본은 약36ms였지만 임의 대형 Mesh의 FPS/로딩 시간 보장은 아니다.

## 실제 cup_1/v001 GUI 결과

모든 아래 화면은 기존 공용 Asset을 실제 `ObjectLibraryDialog → BackendJob → Qt OpenGL`로 읽고 캡처했다. 각 파일의 `-ui.png`에는 실제 컨트롤을 포함한 Dialog가 있다.

| 파일 | 표시 내용 |
|---|---|
| [All Edges](../workbench_runs/diagnostics/wireframe_features_20261113_223252/all-edges.png) | 기존1,530개, Hidden65%. 전체 삼각형 진단 유지 |
| [Feature Edges](../workbench_runs/diagnostics/wireframe_features_20261113_223252/feature-edges.png) | Feature25°/398개, Hidden65%. 동일 Camera/Zoom |
| [Feature + Hidden20%](../workbench_runs/diagnostics/wireframe_features_20261113_223252/feature-hidden20.png) | 새 기본값. 앞 윤곽/뒤 Collision을 낮은 Alpha로 구분 |
| [Top View](../workbench_runs/diagnostics/wireframe_features_20261113_223252/top-feature.png) | 입구·내벽·바닥 원형 윤곽 보존 |
| [Side View](../workbench_runs/diagnostics/wireframe_features_20261113_223252/side-feature.png) | 외곽 Silhouette과 뒤쪽 Collision |
| [실제 UI](../workbench_runs/diagnostics/wireframe_features_20261113_223252/feature-hidden20-ui.png) | 새 컨트롤·선택한 Object/Version |
| [Opacity 비교](../workbench_runs/diagnostics/wireframe_features_20261113_223252/hidden-opacity-comparison.png) | 같은 시점의 Hidden0/20/50/100% |

![입구·내벽·바닥·측면의 실제 Feature 표시](../workbench_runs/diagnostics/wireframe_features_20261113_223252/feature-views.png)

| Feature Angle | 기본 시점에서 선택된 Edge |
|---:|---:|
| 1° | 582 |
| 10° | 398 |
| **25°** | **398** |
| 89° | 329 |
| 120° | 202 |

높은 Angle은 일부 실제 crease도 줄이는 사용자 선택이다. 기본25°에서 중요한 윤곽 보존을 확인했고, 각도와 무관한 곡면 Silhouette은 별도 유지한다. 표의 수치는 이 컵/시점의 표시 선 수이며 복원 정확도나 물리 QA 수치가 아니다.

기존 Cup v001만 보유하므로 새 Cup Version을 만들지 않았다. **기존 workspace_paper v001→v002→v001을 실제 Library Combo로 전환하고 cup_1/v001로 돌아오는 검사**를 했다. 별도의 합성 red/blue Native Asset 회귀에서도 버전별 Texture·설정 유지와 이전 버전 SHA를 검사했다.

실제 RTX4060 Laptop/OpenGL4.1/24bit Depth Buffer에서 GL error0, Timer heartbeat337회, Orbit/Zoom/Pan/Reset/Collision Only·Visible Only/X-Ray/Opacity를 확인했다. 열린 실제 Dialog에 QTest 마우스·Qt Wheel 이벤트를 보내고 실제 Combo/Slider 값 변경의 Qt Signal을 실행한 GUI 자동 검증이다. 가짜 Qt Context나 렌더 이미지를 붙인 Mock UI가 아니다. Viewer 종료 뒤 Feature/All/Surface Buffer, Texture, Shader, VAO, Topology/Payload 해제를 확인했다. 계측값과 상태는 `gui-check.json`이다.

## Before/After 보존 비교

이전 Viewer 코드 보존본과 수정본을 **동일 실제 Cup Payload/Camera/766×424**, Grid/축을 제외해 대조했다.

| 비교 | 변경 Pixel / 최대 Channel 차 |
|---|---:|
| Visual Only | **0 / 0** |
| All Edges + 기존 Hidden65% | **0 / 0** |

즉 Feature를 선택하지 않으면 기존 정상 Texture/Visual/전체 Wireframe을 같은 조건으로 재현한다. 이 비교는 새 Blender/PBR 정확도 인증이 아니라 기존 검증된 GL 표시의 회귀 검사다. `render-regression.json`에 결과가 있다.

## 테스트와 보존

Feature 함수/필드가 없는 RED를 먼저 확인하고 Geometry/GL/UI를 연결했다. 집중 **32개 통과**, 17.51초(`release-focused-verified.xml/log`)다. 기존26개에 새6개가 추가됐다. 중간 실행 수치는 합산하지 않는다.

새 검사는 Boundary/dihedral Angle/Non-manifold, Zero-area/duplicate, 서로 떨어진 Part의 가짜 연결 차단, 대각선이 다른 접합면, reversed winding의 동일 Solid 보존, 완만한64면 곡면의 Angle89° Silhouette·회전 갱신, Cache/VBO 유지, 실제 Alpha0/20/50/100 합성, GL Depth/Blend 복원 및 빈 Feature Buffer의 GL 오류0을 포함한다. 기존 Native Asset/Texture/버전/마우스/자원 해제·All Edges 검사도 유지했다.

추가 점검에서 반대 winding의 동일 Solid를 접합으로 오인하는 RED를 재현해 보완했다. 그때 실행 중이던 전체 회귀는 소유 Process Group만 중단하고 `release-interrupted.log`로 보존했다. 중단 실행을 전체 통과로 보고하지 않는다.

최종 Python 소스·테스트359개의 SHA를 고정한 뒤 세 패키지 전체 회귀를 끝까지 실행했다. **1,861 passed / 1 failed / 오류0 / skipped0**, 기존 경고5개, Console 기준555.20초다(`release-full.xml/log`, exit1). 새6개와 기존 Viewer 검사는 모두 통과했다. skip/xfail이나 삭제로 실패를 숨기지 않았다.

남은 실패는 변경하지 않은 `test_cancel_releases_only_the_owned_model_process_group`의111행이다. 자식 PID72450의 `/proc/.../stat`가 종료 중 `X`를 반환했는데 시험이 부재 또는 `Z`만 허용해 실패했다. [Linux proc_pid_stat 문서](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html)는 `X`를 Dead, `Z`를 Zombie로 구분한다. 사후 PID는 남아 있지 않았다. 이 시험과 `inference.py`, `codex_cli.py`는 HEAD와 동일한 SHA이며 해당 시험은 Viewer를 호출하지 않는다. **동일 시험의 코드 변경 없는 단독 재확인1회는 통과**, 0.29초다(`cancellation-recheck.xml/log`). 관측된 종료 상태를 누락하는 기존 순간 상태 Assertion 문제로 판단하며, 이번 Wireframe 범위 밖의 시험/프로세스 코드는 수정하지 않았다. 전체 실행의1건 실패를 단독 통과로 덮거나 전체 Green이라고 보고하지 않는다. `cancellation-analysis.json`에 원 traceback·소스 대조·재확인을 보존했다.

이번 제품 변경은 `asset_viewport.py`, `object_library.py`와 새 계산 helper `collision_wireframe.py`다. `asset_view.py`·USD Converter·Calibration/Reconstruction/Physics/Robot Control은 그대로다. 관련 기존 테스트/문서를 갱신하고 `test_wireframe_features.py`와 이 문서를 추가했다.

보호 기준선은 기존 Scene/Input/Capture/Candidate/Asset/Export·Workspace Runtime **18,347개 파일**과 기존 미커밋22개다. 종료 SHA/크기 대조에서 **변경0·누락0·신규0**을 확인했다. 컵 USDA SHA는 `f1d6a0634a2465f715261e163b9515777d75f58de9be24396c5eb5f9d98f49cd`로 시작과 같다. 원본 Texture·Collision을 포함한 보호 root를 대조했으며 SDK/모델 디스크 전체 전수 검증을 뜻하지 않는다.

기존 미커밋22개 중 이번 범위6개만 추가 수정하고 나머지16개는 byte 단위로 보존했다. 신규3개를 포함해 현재 미커밋25개이고 Git Index는 비어 있다. HEAD/브랜치 불변, 실행 전후359개 Python SHA 변경0, 미커밋 Python20개 bytecode 없는 compile 및 `git diff --check`를 확인했다. Commit/Push/Reset/Clean은 하지 않았다. 진단은 Git 제외 `workbench_runs/diagnostics/wireframe_features_20261113_223252/`에 있으며 제품은 이를 import하지 않는다. 기준선·이번 변경만의 patch·자원/GUI·회귀/실패·보존 근거는 `before.json`, `task-only.patch`, `gui-check.json`, `render-regression.json`, `completion-check.json`에 있다.

이번 변경 파일은 다음9개다. 이 목록은 기존22개 미커밋 전체 변경과 구분한다.

| 파일 | 이번 변경 |
|---|---|
| `robot_learning_workbench/src/robot_learning_workbench/ui/asset_viewport.py` | 기존 GPU Viewer에 Feature VBO/Cache와 Edge Opacity Uniform 연결 |
| `robot_learning_workbench/src/robot_learning_workbench/ui/object_library.py` | Wireframe Mode/Angle/Opacity 컨트롤·기존 상태 전달 |
| `robot_learning_workbench/src/robot_learning_workbench/ui/collision_wireframe.py` | 신규. 표시용 인접성·접합·Feature/Silhouette 수학 |
| `real2sim_builder/tests/test_asset_view.py` | 실제 Library UI·버전/상태 회귀 확장 |
| `real2sim_builder/tests/test_collision_xray.py` | All Edges/이전 Alpha를 명시해 기존 깊이·전체 Edge 검사 유지 |
| `real2sim_builder/tests/test_wireframe_features.py` | 신규. Geometry/Cache/Alpha/실제 GL6개 |
| `real2sim_builder/SCENE_AUTHORING.md` | 새 기본값과 사용법 연결 |
| `docs/object-library-collision-xray.md` | 과거 기본값과 이번 Feature 개선 구분 |
| `docs/object-library-wireframe-readability.md` | 신규. 이번 구현·실제 GUI·회귀/한계·보존 기록 |

지원 환경은 기존 Desktop OpenGL4.1 이상의 Qt Context다. 임의의 교차/겹침을 정확한 Boolean 경계로 정리하는 기능, 복잡 PBR·다층 투명 재질, 실제 Collision/파지/Task 정확도는 이번 범위가 아니다. 원본 Collision의 작은 틈이나 미확인 형상을 임의 보정하지 않는다. 전체 회귀의 합성 MuJoCo/Runner 결과도 사용자 Scene의 물리·실물 성공과 구분한다.
