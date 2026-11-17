# Scene Prepare / Real·Sim — 촬영 기록 펼침과 화면 높이

> 2026-11-17 최신 외형·조작: Scene Prepare 연결과 Teleop 시작을 한 버튼으로 합치고 하단 세 버튼을 왼쪽 영상 영역에 맞췄다. 공통 남색·청록 스타일과 최신 검증은 [Studio UI 변경](studio-ui-refresh.md)을 따른다. 촬영 기록·진단 로그의 오른쪽 팝업은 유지한다.

> 2026-11-17 후속 UI 요청: 촬영 기록과 진단 로그를 제목줄 오른쪽 버튼으로 열리는 별도 창으로 전환했다. 현재 동작은 마지막 「오른쪽 버튼과 팝업 전환」 절을 따른다. 아래 13%/22%는 이전 펼침 패널 구현·측정 기록이다.

2026-11-17. `feat/simfoundry-style-reconstruction`, 시작 HEAD `8e02b1ae023a856694a40b947881f76b66410624`. 이번 변경은 두 실시간 화면의 배치와 표시 크기에 한정한다. 기존 미커밋 작업 위에 적용했으며 장치 연결·모델 추론·사용자 Capture 생성은 실행하지 않았다.

## 원인과 수정

이전 화면은 촬영 기록을 카메라와 같은 세로 레이아웃에 그대로 추가했다. 테이블 높이만 제한해도 제목·폴더 안내·재정합 메모의 최소 높이가 합쳐져 부모 페이지를 키웠다. 실제 Qt에서 1280×720 창을 요청해도 두 화면 모두 높이가 1093px로 늘어났다. 숨겨진 Workflow 탭의 최소 높이도 현재 실시간 탭의 축소를 방해했다. `QLabel`의 원본 Pixmap 크기가 최소 크기로 전파되는 문제도 있었다.

두 화면은 기존 `view.py`의 공통 UI 배치를 사용한다.

- 촬영 기록은 기본 접힘이다. 세로 `QSplitter`에서 기록을 열면 기본 높이는 창 높이의 약 13%, 최대 높이는 **22%**다. 구분선으로 늘릴 수 있으며 행 수는 부모 높이에 영향을 주지 않는다.
- 같은 `SnapshotTable`을 유지하고 행은 테이블 안에서 스크롤한다. Real/Sim의 긴 경로·재정합 메모 등은 기록 영역 자체의 스크롤로 접근한다.
- 카메라·설명·입력 영역에는 페이지 `QScrollArea`를 둔다. 작은 창이나 긴 오류 문구는 스크롤로 확인한다. 기록을 접거나 펼칠 때 카메라가 보이는 위치로 이동한다.
- Teleop·Capture·중단/종료 버튼과 기록 열기 버튼은 스크롤 밖 하단에 고정한다. 카메라 스트림·명령·저장 로직은 바꾸지 않는다.
- **기록 크게 보기**는 같은 표를 모델리스 창으로 옮긴다. 선택 행·실시간 새 행·기존 더블클릭 상세 보기를 유지하며 원래 화면의 중단 버튼도 사용할 수 있다. 창을 닫으면 표를 복귀시킨다.
- Scene Prepare는 Side/Wrist **2분할**, Real/Sim 기본값은 **4분할**이다. 기존 Side 크게/Wrist 크게 선택도 유지한다.
- 실시간 탭에만 현재 페이지의 최소 높이를 적용한다. 영상 표시 Widget의 최소 크기는 원본 RGB 해상도와 분리한다. 원본 영상·렌더 방식·전체 영상 더블클릭 기능은 유지한다.

작은 창에서는 제목이나 관절·안내 정보 일부가 스크롤 뒤에 있을 수 있다. 이를 창 밖으로 밀어 버리지 않고 스크롤로 접근하게 했으며 카메라와 조작 버튼을 우선 표시한다. 전체 기록과 메모를 동시에 넓게 보려면 확대 창을 사용한다.

## 실제 Qt 검증

설치된 PyQt6의 실제 `Window`·Widget·스타일·이벤트 루프를 `QT_QPA_PLATFORM=offscreen`에서 실행했다. 저장된 `pickplace-colorblock` Capture 영상을 **읽기 전용 재생**했고 기록 행은 합성했다. 화면에 이 구분을 표시했다. 새 센서 촬영이나 물리 로봇 검증은 아니다.

1650×920 / 1920×1080 / 1280×720 × 두 화면 × 기록 0/20/100건, **18개 조합**에서 실제 창 크기·카메라/버튼의 visible region·기록 높이·스크롤 범위를 확인했다. 각 조합에서 접기/펼치기를 5회 전환했다.

| 창 크기 | 펼친 기록 높이 | Scene Prepare 영상 높이(각) | Real/Sim 영상 높이(각) |
|---|---:|---:|---:|
| 1650×920 | 119px | 250px | 136px |
| 1920×1080 | 140px | 358px | 205–206px |
| 1280×720 | 93px | 250px | 100px |

위 수치는 펼친 상태의 Qt Widget 높이다. 기록 0/20/100건에 따라 커지지 않는다. 20/100건은 표 내부 스크롤이 생기며 카메라와 조작 버튼은 모든 조합에서 전체 표시됐다. 920/1080 높이에서는 Project/Scene 선택기도 가려지지 않는지 별도 검사했다. 구분선의 최대 허용 높이는 22%이며 위 표는 기본 펼침 높이다.

확대 창에서 행 선택을 유지한 채 새 행 추가·영상 갱신 이벤트를 실행했다. 접기/확대 동작은 제어 명령을 보내지 않았고 기존 Capture·Teleop·중단/종료 슬롯은 같은 명령으로 연결됐다. 긴 안내 50줄·긴 저장 경로에서도 스크롤 끝의 정보와 재정합 버튼에 접근했다.

수정 전 RED 2개와 원래 UI의 실패 위치를 보존했다. 이후 카메라 최소 높이·숨은 탭 제약을 수정했고, 스크린샷 검토에서 선택기가 불필요하게 밀리는 중간 배치를 발견해 기본 높이를 조정했다. 중간 RED/GREEN 실행 수치를 합산하지 않는다.

- 최종 집중 UI 검사: **27 passed**, 11.52초. 신규 시험 2개와 기존 카메라·Capture·Real/Sim·UI 회귀를 포함한다.
- 최종 Workbench 전체 회귀: **1,269 passed / 실패0 / 오류0 / skipped0, 실제 exit 0**, 기존 torchvision 경고4개, Console 기준 **546.53초**. `release-workbench.xml/log/exit.json`에 보존했다. 이전 작업의 1,267개와 시험명을 대조해 신규2·삭제0을 확인했다. 기본 펼침 높이를 조정하기 전의 중간 전체 실행(1,269개, 543.44초)과 구분한다.
- Builder/scene-contract 제품 코드는 이번에 변경하지 않았다. 앞선 전체 회귀 결과를 이번 실행으로 합산하지 않는다.

## Before / After 이미지

모두 실제 Qt 창의 `grab()` 결과다. Before는 제품 수정 전에 저장했고, After는 최종 배치에서 같은 저장 영상·행 수를 사용했다. Before가 요청 높이보다 커진 경우 원래 창 전체를 그대로 저장했다.

| 화면 / 요청 크기 / 기록 수 | Before | After |
|---|---|---|
| Scene Prepare / 1650×920 / 20 | [이전](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/before-capture-1650x920-n20.png) | [수정](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/after-capture-1650x920-n20.png) |
| Real/Sim / 1650×920 / 20 | [이전](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/before-real_sim-1650x920-n20.png) | [수정](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/after-real_sim-1650x920-n20.png) |
| Scene Prepare / 1280×720 / 100 | [이전](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/before-capture-1280x720-n100.png) | [수정](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/after-capture-1280x720-n100.png) |
| Real/Sim / 1280×720 / 100 | [이전](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/before-real_sim-1280x720-n100.png) | [수정](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/after-real_sim-1280x720-n100.png) |

[18개 전체 비교](../../workbench_runs/diagnostics/capture_panel_layout_20261117_001/index.html)는 해상도·행 수별 원본 스크린샷을 연결한다. 진단 폴더는 Git 제외 로컬 자료이며 제품 실행 의존성이 아니다.

## 변경 범위와 보존

이번 작업 시작 상태 대비 제품 UI 4개 수정, 시험 1개·이 문서 1개 신규다.

- `robot_learning_workbench/src/robot_learning_workbench/ui/view.py`: 공통 Scroll/Splitter/확대 창과 표시 최소 크기.
- `robot_learning_workbench/src/robot_learning_workbench/ui/session_page.py`: 기존 2분할 카메라·기록·조작 행 배치.
- `robot_learning_workbench/src/robot_learning_workbench/ui/real_sim_page.py`: 기존 기록/재정합 배치와 기본 4분할.
- `robot_learning_workbench/src/robot_learning_workbench/ui/app.py`: 숨은 탭의 높이가 실시간 페이지를 키우지 않게 제한.
- `robot_learning_workbench/tests/test_capture_panel_layout.py`: 18개 조합과 확대/갱신/제어 연결·긴 안내 검사.

작업 전 복사와 대조해 두 페이지와 Window의 기존 메서드는 생성자 외 AST 동일함을 확인했다. `CameraView` 원본 클래스도 AST 동일하다. Backend 제어·Capture·Stream 파일은 시작 복사와 SHA가 같으며 `SnapshotTable`도 변경하지 않았다. 기존 사용자 Scene/Asset/Capture/Dataset/모델 원본은 쓰기 대상으로 사용하지 않았다.

이전 작업의 사용자 리소스 **21,362개** SHA/크기 ledger를 다시 대조해 **변경0·누락0**을 확인했다. 해당 ledger 이후 추가된 Capture/Real·Sim 실행 파일 88개도 발견했으며, 모두 이번 UI 작업 시작보다 이른 mtime/ctime이었다. 이 파일들을 삭제하거나 수정하지 않았다. 이번 시작 시점의 새 사용자 리소스 ledger는 만들지 않았으므로 이전 ledger와 이번 시작을 같은 기준선으로 주장하지 않는다.

HEAD/Index는 시작과 같고 변경 Python 5개 bytecode 없는 compile·`git diff --check`가 통과했다. 근거는 `preservation-after.json`, `verification-summary.json`이다. 이는 모든 외부 SDK/모델 디스크의 전수 대조를 뜻하지 않는다. Commit/Push/Reset/Clean은 실행하지 않았다.

진단: `workbench_runs/diagnostics/capture_panel_layout_20261117_001/`의 `before-geometry.json`, `after-geometry.json`, `red.xml/log`, `final-focused.xml/log`, `release-workbench.xml/log/exit.json`, `behavior-preservation.json`, `preservation-after.json`, `verification-summary.json`.

## 오른쪽 버튼과 팝업 전환

Scene Prepare의 제목줄 오른쪽에 **촬영 기록 / 진단 로그**, Real/Sim의 제목줄 오른쪽에 **촬영 기록 / Scene 재정합** 버튼을 배치했다. 메인 페이지의 펼침 패널·진단 로그 영역과 「기록 크게 보기」 보조 버튼을 제거했다. 카메라 표시 공간과 하단의 기존 Teleop·Capture·중단/종료 버튼은 유지한다.

버튼은 모델리스 창을 연다. 창마다 기존 표·메모·로그 Widget 하나를 계속 사용한다. 닫았다 열어도 선택 행·재정합 메모·로그가 유지되고, 닫혀 있는 동안 들어온 새 Capture와 로그도 같은 Widget에 추가된다. 같은 버튼을 다시 누르면 이미 열린 창을 앞으로 가져오며 창을 복제하지 않는다. 페이지 전환·메인 창 종료 시 팝업을 닫고 내용은 페이지 수명 동안 보존한다. 기존 CameraView/LiveCameraView와 Backend·Capture 저장·제어 로직은 변경하지 않았다.

최신 집중 Qt 검사 **24 passed, 11.12초**다. 1650×920 / 1920×1080 / 1280×720 × 두 화면 × 기록 0/20/100건, 18개 조합에서 창을 반복 열고 닫아도 카메라 높이가 그대로이고 버튼이 보이는지 확인했다. 표 내부 스크롤·기존 상세 보기·모델리스 창에서의 영상/기록 갱신, 로그 재열기, 긴 안내·재정합 영역 스크롤도 검사했다. 기존 펼침 패널을 기대하던 시험은 새 팝업 요구사항으로 갱신했다. 새 진단 로그 동작 시험은 구현 전에 RED였으며, 부모 종료 시 팝업이 남는 경우도 RED를 확인해 페이지 Hide 경계에서 닫도록 수정했다.

최종 Workbench 전체 회귀 **1,270 passed / 실패0 / 오류0 / skipped0, 실제 exit0**, 기존 torchvision 경고4개, Console 기준 **578.69초**다. 이전 1,269개에서 신규 진단 로그 시험1개가 늘었고 기존 시험명 삭제는 없다. 이전 통과 결과를 이번 변경의 회귀로 대신하지 않았다.

실제 PyQt6(offscreen) 스크린샷이다. 저장된 Capture RGB 재생과 합성 기록/로그이며 새 센서 촬영이나 로봇 연결은 없다.

- [Scene Prepare 메인 화면](../../workbench_runs/diagnostics/capture_history_popups_20261117_001/capture-main.png)
- [Scene Prepare 촬영 기록 창](../../workbench_runs/diagnostics/capture_history_popups_20261117_001/capture-history.png)
- [Scene Prepare 진단 로그 창](../../workbench_runs/diagnostics/capture_history_popups_20261117_001/capture-log.png)
- [Real/Sim 메인 화면](../../workbench_runs/diagnostics/capture_history_popups_20261117_001/real_sim-main.png)
- [Real/Sim 촬영 기록·Scene 재정합 창](../../workbench_runs/diagnostics/capture_history_popups_20261117_001/real_sim-history.png)

1650×920에서 Scene Prepare 영상 높이는 각429px, Real/Sim 기본4분할 영상 높이는 각224px였다. 팝업의 열림/닫힘으로 이 높이가 바뀌지 않았다.

이번 수정은 UI의 `view.py/session_page.py/real_sim_page.py`, 관련 `test_capture_panel_layout.py/test_capture_session_ui.py`, 이 문서다. 이전 미커밋 구현은 보존한다. 근거는 Git 제외 `workbench_runs/diagnostics/capture_history_popups_20261117_001/`의 RED/GREEN·`focused.xml/log`, 최종 회귀, `gui-results.json`, `verification-summary.json`이다.

두 페이지의 기존 생성자 외 메서드와 `CameraView/LiveCameraView`는 시작 복사와 AST 동일하며 Backend 제어·저장 소스는 SHA 동일하다. 이전 조사에서 선택한 사용자 원본34개도 SHA/크기 변화가 없었다. 이34개는 이번에 새로 만든 전수 원본 ledger가 아니다. HEAD·Git Index와 기존 변경을 보존했고 변경 Python5개 bytecode 없는 compile·`git diff --check`를 확인했다. Commit/Push·장치 구동은 하지 않았다.
