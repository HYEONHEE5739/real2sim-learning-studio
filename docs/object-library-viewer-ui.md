# Object Library — 기본 슬라이더와 Advanced / Debug

2026-11-14. `feat/simfoundry-style-reconstruction`, 시작 HEAD `a978e6e97ddab2682c3754dc50c19909ac8b94d3`. 기존 미커밋25개를 보존하고 Object Library UI와 표시 상태 연결만 보완했다. 기존 Qt/OpenGL, 실제 USDA/Texture, Feature 수학과 버전 자산 계약을 사용한다. 새 패키지·Renderer·설치·DA3/SAM/FLUX 등 대형 모델 추론·Commit/Push는 없다.

## 현재 사용법

Viewport 바로 아래에 같은 폭의 세 슬라이더를 배치했다.

| Visual | Collision Front | Collision Hidden |
|---|---|---|
| **100%** | **0%** | **0%** |
| Visual 색상/불투명도 | 보이는 청록 Edge | 가려진 주황 점선 Edge |

초기 화면은 Visual Only다. Collision 방식은 X-Ray, Edge는 Feature Edges25°로 준비되지만 두 Collision Opacity가0%여서 선을 그리지 않는다. Front100%/Hidden20%로 올리면 기존 X-Ray Feature 표시를 볼 수 있고, 둘 다0%로 돌리면 Visual Only다. Reset View는 Camera만 초기화한다. 우클릭 Orbit, 휠 Zoom, 가운데 Pan을 유지한다.

![실제 cup_1/v001의 기본 UI](../workbench_runs/diagnostics/object_library_advanced_20261114_001346/cup-default.png)

기본 자산 정보는 직전 사용자 결정대로 **크기와 충돌 검증 상태 한 줄**이다. 최신 첨부의 Object ID/Version/출처/Material·Texture/Collision/물리 검증 항목은 Advanced 내부의 정보 영역에 보존했다. 긴 Evidence·원 Material 설명은 해당 정보의 Tooltip에 있으며 기본 화면에 원문·SHA를 펼치지 않는다. Viewport 안에는 Mesh·Grid·XYZ만 표시한다.

## Advanced / Debug

기본으로 접혀 있으며, 펼치면 Edge Mode/Feature Angle/Collision Mode/Collision Only와 자산 정보를 사용할 수 있다.

- All Edges는 전체 삼각형 Edge, Feature Edges는 기존 인접성·Silhouette 선택을 사용한다. Angle0–180°는 Feature에서만 활성화한다.
- Visible Only는 Hidden 슬라이더를 비활성화하고 값을 보존한다. X-Ray로 돌아가면 이전 값을 사용한다.
- **Collision Only는 토글**이다. 실제 불투명 Collision Surface와 선을 표시한다. 진단 중 세 슬라이더는 값을 보존한 채 비활성화하며, 진단의 Front100%/Hidden 최소20%를 사용한다. 해제하면 기존 세 값과 모드·Angle·Camera 상태로 돌아간다. 임시 자산이나 Proxy를 만들지 않는다.
- Advanced 접기/펼치기는 설정값을 바꾸지 않는다. Version 변경 시에도 세 값·모드·Angle·진단 상태는 유지하며, 기존처럼 새 버전의 Camera는 Reset한다.
- 고급 영역은 높이96–180px의 Scroll Area다. 긴 정보가 창 전체를 키우지 않도록 하고, 작은 창에서는 스크롤한다. 기본/고급 설정을 위해 별도 앱·상태 Manager를 추가하지 않았다.

## 렌더 상태 연결

기존 `AssetViewport.state`와 Shader Uniform을 사용한다. 기본 모드에서 `show_visual=True`를 유지하는 것은 투명 Visual의 깊이 기준을 남기기 위해서다. 기존 `show_visual=False`는 Collision Only의 불투명 Surface 진단 의미를 그대로 유지한다.

Visual0%는 **색상 pass만 생략**하고 Depth-only pass는 유지한다. 앞/뒤 Edge는 기존 Depth Buffer/LEQUAL·GREATER 판정이다. Front/Hidden이 모두0%이거나 Visible Only에서 Front만0%인 경우 UI는 `show_collision=False`를 전달해 불필요한 Collision Surface/Edge pass를 생략한다. Hidden0%/Visible0%의 개별 선 pass 생략과 기존 Blend/Depth Write 복원도 유지한다.

슬라이더는 원본 USD 변환이나 `BackendJob`을 재실행하지 않는다. 실제 컵의 Topology 객체·Visual/Collision/All VBO ID·Payload SHA를 조작 전후 대조했다. `collision_wireframe.py`, USDA Converter와 `asset_view.py`는 이번에 수정하지 않았다.

## 실제 GUI 검증

기존 공용 `cup_1/v001`, `block_blue/v001`을 실제 Library Backend→USD Converter→Qt OpenGL로 로딩했다. RTX4060 Laptop의 Desktop OpenGL4.1/24bit Depth Context에서 확인했다. QTest 마우스/Qt Wheel 이벤트와 실제 Widget 값 변경 Signal을 사용한 자동 GUI 검증이며, 화면을 AI로 생성하거나 Mock Mesh로 바꾼 결과가 아니다.

| 캡처 | 실제 표시 |
|---|---|
| [기본 화면](../workbench_runs/diagnostics/object_library_advanced_20261114_001346/cup-default.png) | Visual100 / Front0 / Hidden0, Advanced 접힘 |
| [X-Ray](../workbench_runs/diagnostics/object_library_advanced_20261114_001346/cup-xray.png) | Front100 / Hidden20, Feature25° |
| [Advanced 펼침](../workbench_runs/diagnostics/object_library_advanced_20261114_001346/cup-advanced.png) | 기존 Mode·Angle·진단·자산 정보 |
| [Collision Only](../workbench_runs/diagnostics/object_library_advanced_20261114_001346/cup-collision-only.png) | 실제 Collision 면과 Edge 단독 진단 |
| [작은 창](../workbench_runs/diagnostics/object_library_advanced_20261114_001346/cup-small-advanced.png) | Advanced를 펼친 실제900×720 창, 정보/슬라이더/버튼 겹침 없음 |
| [블록 기본](../workbench_runs/diagnostics/object_library_advanced_20261114_001346/block-default.png) / [X-Ray](../workbench_runs/diagnostics/object_library_advanced_20261114_001346/block-xray.png) | 기존 block_blue/v001 |

Visual Only 복귀, Visual45%/0%, All1,530개↔Feature398개, Angle25°↔89°, Visible Only, Collision Only 해제 복원, Advanced 유지, Orbit/Zoom/Pan/Reset을 확인했다. 설정/마우스 중 Backend 재호출0회, Payload·원 VBO 유지, GL error0이다. Version은 기존 `workspace_paper v001→v002→v001`로 실제 전환한 뒤 컵으로 돌아왔다. 새 Cup Version은 만들지 않았다. 닫기 뒤 Buffer/Texture/Shader/VAO/Topology/Payload 해제를 확인했다.

긴 Object ID·Evidence·부분 미확인 치수와 900×720 배치는 별도 합성 Payload의 실제 Qt 시험으로 확인했다. 그 합성 입력을 실제 컵 관측이나 실측으로 사용하지 않았다.

## 테스트·보존·변경

새 기능이 없는 UI 기본값과 Visual0%의 불필요한 색상 draw를 RED로 확인한 뒤 보완했다. Advanced의 고정 높이 때문에900×720로 줄지 않는 RED도 확인하고 스크롤 높이 제약을 수정했다. 중간 GUI의900×791 결과는 `layout-before/`에 보존하고 최종900×720 결과와 구분한다.

최종 집중 **34 passed**, 23.77초다. 기존 Native Asset/Texture·깊이·모드·버전·마우스/자원·Feature 검사에 새2개를 더했다. 기존 테스트를 삭제하거나 skip/xfail하지 않았다.

Python 소스/테스트360개의 SHA를 고정한 세 패키지 전체 회귀는 **1,864 passed / 실패0 / 오류0 / skipped0**, 기존 경고5개, Console 기준577.77초다. `release-full.xml/log`의 최종 집계와 각 테스트 결과가 근거다. 중단된 것은 부모 exec/수집기이며 독립 그룹의 pytest는 끝까지 실행됐다. 직접 종료 코드는 수집하지 못해 UNKNOWN으로 남겼고 exit0이라고 추정하지 않는다. `release-exit-observation.json`에 최종 로그/XML 대조와 소유 그룹 잔존0을 기록했다. 전체 회귀를 재시작하거나 성공 수치를 이전 실행에서 가져오지 않았다.

이번 제품 변경은 `ui/object_library.py`의 배치·기존 상태 연결과 `ui/asset_viewport.py`의 Visual0% 색상 pass 생략뿐이다. 관련 기존 `test_asset_view.py`를 새 UI 조작으로 갱신하고 `test_library_display_controls.py`를 추가했다. SCENE_AUTHORING과 이전 Wireframe 기록에는 현재 사용법 링크를 남겼다. Geometry/Collision 생성·Reconstruction·Calibration·Physics·Robot Control은 변경하지 않았다.

진단은 Git 제외 `workbench_runs/diagnostics/object_library_advanced_20261114_001346/`다. `before.json`의 기존 Scene/Input/Capture/Calibration/Candidate/Asset/Export·Workspace Runtime **18,347개 파일 SHA/크기 변경0·누락0·신규0**을 종료 시 확인했다. 모든 SDK/외부 모델 디스크를 전수 대조했다는 뜻은 아니다.

기존 미커밋25개 중 아래5개만 이번 범위에서 추가 수정했고 나머지20개는 byte 단위로 같다. 신규2개를 포함해 현재 미커밋27개이며 Index는 비어 있다. HEAD/브랜치 불변, 실행 전후360개 Python SHA 변경0, 미커밋 Python21개 bytecode 없는 compile, `git diff --check`와 문서 링크 검사를 통과했다. Vertex/Fragment Shader, upload/feature_buffer/draw/cleanup/마우스 함수의 AST와 원본 `collision_wireframe.py`/`asset_view.py` SHA도 보존했다.

| 구분 | 이번 변경 파일 |
|---|---|
| 제품 수정 | `robot_learning_workbench/src/robot_learning_workbench/ui/object_library.py`, `robot_learning_workbench/src/robot_learning_workbench/ui/asset_viewport.py` |
| 기존 테스트 수정 | `real2sim_builder/tests/test_asset_view.py` |
| 신규 테스트 | `real2sim_builder/tests/test_library_display_controls.py` |
| 기존 문서 수정 | `real2sim_builder/SCENE_AUTHORING.md`, `docs/object-library-wireframe-readability.md` |
| 신규 문서 | `docs/object-library-viewer-ui.md` |

`task-only.patch`, `geometry-preservation.json`, `gui-result.json`, `release-focused-final.xml/log`, `release-full.xml/log`, `preservation-after.json`, `compile-check.json`, `completion-check.json`에 실행 근거를 남겼다. 제품은 이 진단 폴더를 import하지 않는다. 전체 회귀의 합성 Native/CPU physics 검증은 사용자 Scene의 Physics/파지/Task 성공과 구분한다. 사용자 Scene Reconstruction·실물 구동은 이번 범위에서 실행하지 않았다. 실행 중인 앱은 재시작해야 새 UI를 읽는다.
