# Studio UI 외형 통일과 연결·Teleop 버튼 통합

2026-11-17. `feat/simfoundry-style-reconstruction`, 시작 HEAD `8e02b1ae023a856694a40b947881f76b66410624`. 기존 미커밋 작업 위에 적용했다. 참고 이미지의 색·글자·버튼 표현을 기존 PyQt6 화면에 적용하며, 기존 네 탭·좌우 배치·Workflow 단계는 유지한다.

## 연결과 세 조작 버튼

Scene Prepare의 **로봇 연결 · Teleop**을 누르면 기존 Session을 연결하고 `OBSERVING`과 Teleop 사용 가능 여부를 확인한 뒤 기존 `teleop_start` 명령을 한 번 전송한다. 별도의 시작 버튼은 제거했다. 이 클릭 이전에 장치를 연결하거나 제어를 활성화하지 않는다. 카메라 전용 `scene_capture`는 Teleop을 요청하지 않는다.

오류·시작 거절·탭 이동·종료는 대기 중인 시작 의사를 취소한다. Teleop이 중단되면 **Teleop 다시 시작**을 직접 눌러 기존 연결에서 다시 요청한다. 반복 Progress나 Capture 완료를 이유로 자동 재시작하지 않는다. Backend의 장치 Identity·측정 Feedback·안전 Deadline·명령 ACK 검증은 그대로 사용한다.

하단은 **로봇 연결 · Teleop / 캡처 / 종료** 세 개를 같은 너비로 배치한다. 공통 `LiveSessionLayout`이 현재 왼쪽 카메라 영역의 너비를 따라 버튼 영역을 배분하므로 오른쪽 자료·메모 패널까지 침범하지 않는다. 작은 창에서도 하단 조작 영역은 페이지 스크롤 밖에 유지한다. Real/Sim의 기존 통합 연결과 세 버튼도 같은 외형을 쓴다.

## 외형 적용 범위

- 짙은 남색 배경, 단계가 구분되는 카드·입력·테이블, 청록 선택·연결 강조, 붉은 종료 버튼.
- DejaVu Sans와 한글 Noto Sans CJK KR 대체 글꼴, 제목·본문·상태 정보의 크기·굵기 구분.
- Qt에서 직접 그린 연결·카메라·종료 아이콘, 둥근 버튼·입력 테두리, Hover/Focus/Disabled 상태.
- Scene Prepare·Real/Sim·Workspace Pipeline·Precision Calibration과 기존 설정·기록·진단·Data Curation 창에 공통 스타일 적용.
- 메모·YAML/JSON 편집기의 흰색 로컬 스타일을 제거하고, Auto Reconstruction 창과 모델 선택 목록도 같은 팔레트로 통일.

카메라 RGB·렌더·OpenGL Viewport 처리와 원본 영상은 바꾸지 않는다. 운영체제 제목 표시줄·네이티브 파일 선택기의 외형은 OS 설정을 따른다.

## 실제 화면과 검사

스크린샷은 실제 PyQt6 Widget과 이벤트 루프를 `QT_QPA_PLATFORM=offscreen`으로 실행한 결과다. 기존 저장 Capture RGB를 읽어 재생하고 합성 UI 상태·기록 행을 넣었다. 새 촬영·실물 연결·로봇 제어·AI 모델 실행은 없다. Before는 작업 시작 시 복사한 소스를 별도 Python 경로로 실행해 만들었으며 제품 파일을 되돌리지 않았다.

- [Scene Prepare Before](../../workbench_runs/diagnostics/studio_ui_refresh_20261117_001/before/capture-1650x920.png) / [After](../../workbench_runs/diagnostics/studio_ui_refresh_20261117_001/after/capture-1650x920.png)
- [Real/Sim After](../../workbench_runs/diagnostics/studio_ui_refresh_20261117_001/after/real_sim-1650x920.png)
- [Workspace Pipeline After](../../workbench_runs/diagnostics/studio_ui_refresh_20261117_001/after/pipeline-0.png)
- [Precision Calibration After](../../workbench_runs/diagnostics/studio_ui_refresh_20261117_001/after/precision.png)
- [전체 Before/After 비교](../../workbench_runs/diagnostics/studio_ui_refresh_20261117_001/index.html)

1280×720 / 1650×920 / 1920×1080에서 두 화면의 요청한 창 크기가 유지된다. 세 버튼은 왼쪽 영상 영역 경계와 2px 이내로 맞으며 너비 차이는 2px 이하다. Scene Prepare 영상 높이는 각각 270/470/630px, Real/Sim 기본 4분할은 각각 118/218/298px다. 촬영 기록 0/20/100건과 팝업 반복 열기·닫기, 긴 안내의 스크롤, 기존 상세 보기·Capture·종료 명령 연결도 검사했다.

새 연결 시험은 구현 전에 분리된 버튼·배치 결함을 RED로 재현했다. 팔레트 시험은 흰색 로컬 스타일과 기존 모델 목록 배경을 RED로 확인한 뒤 갱신했다. Client 오류가 들어온 뒤 시작 의사가 남는 경우도 RED를 확인해 오류 표시 경계에서 취소했다.

마지막 관련 검사 **62 passed / 실패0 / 오류0 / skipped0, 실제 exit0, 17.78초**다. 연결·버튼 배치·팝업/스크롤·테마·기존 UI 계약과 아래 캐시 검사만 포함하며 실제 창은 띄우지 않는 `offscreen` Qt를 사용했다. 이전 집중35개와 Reconstruction UI11개는 이 묶음과 겹치므로 합산하지 않는다. 근거는 `release-ui-only.xml/log`다.

### 전체 회귀 시도와 사용자 요청에 따른 중단

처음에는 패키지 전체 회귀도 실행했다. 기존 `test_asset_view.py:viewport_check`가 OpenGL 검사를 위해 `QT_QPA_PLATFORM=xcb`를 명시하므로 전역 offscreen 설정과 별개로 Object Library/Viewport 실제 창이 열렸다. 사용자가 작업 화면 방해와 범위 초과를 지적하여 소유 Workbench pytest와 그 자식 프로세스를 종료했다(`release-workbench-stopped.json`). 이후 전체 회귀를 재실행하지 않았다. 이 작업에서 Object Library 제품 코드는 수정하지 않았다.

중단된 Workbench 로그에는 진행 중 실패 표식3개가 있고 최종 XML·요약은 없다. 이를 통과로 보고하지 않으며 이번 UI 범위 밖의 원인도 확정하지 않는다. Builder 전체 시도는 **927 passed / 2 failed**로 끝났고 Contract는 **140 passed / exit0**였다. Builder 실패2개는 아래의 UI SHA 변경에 대한 Stage1/2 캐시 검사였으며 수정 후 관련62개에서 통과했다. 수정 후 전체 회귀 통과 결과는 없다.

Reconstruction 외형 변경만으로 이전 Stage1/2 Artifact를 재사용하지 못하는 것을 확인했다. `ui_reconstruction.py`의 스타일 호출을 제외한 AST가 시작 복사와 같음을 검사하고, 기존 `stage_artifacts.py`의 검토된 변경 목록에 해당 파일의 **정확한 SHA**만 추가했다. 미검토 UI 변경은 여전히 차단하는 시험을 추가했으며 Worker·입력·모델·정밀도·출력 검증은 유지한다. 기존 Artifact를 쓰거나 추론을 다시 실행하지 않았다.

## 변경과 보존 경계

제품 UI 변경: Workbench의 `ui/session_page.py`, `view.py`, `theme.py`, `real_sim_page.py`, `scene_inputs.py`, `source_settings.py`, `pipeline_settings.py`, `recipe_editor.py`, `training_json.py`, `app.py`, `device_setup.py` 및 Builder의 `ui_reconstruction.py`다. `stage_artifacts.py`는 위의 기존 캐시 허용 SHA만 보완했다. 관련 Qt 시험을 갱신하고 `test_capture_connection_ui.py`와 `test_studio_theme.py`를 추가했다. `test_stage_cache_compatibility.py`에는 미검토 UI 변경 거부를 추가했다. 시작 시 있던 Backend·사용자 원본·기존 미커밋 변경은 이번 UI 수정과 구분한다.

시작 시 Python404개와 비교해 기존 제품13개·시험7개가 변경됐고 신규 시험2개를 포함한 Python22개의 bytecode 없는 compile과 `git diff --check`를 통과했다. 정확한 목록은 `change-inventory.json`이다. CameraView/LiveCameraView와 Backend의 기존 함수 AST는 시작 복사와 같다. 이전 조사에서 선택한 원본34개를 다시 대조해 SHA/크기 변경0을 확인했다. 이는 이번에 전체 Scene/Asset에 대한 새 전수 ledger를 만들었다는 뜻이 아니다. HEAD·브랜치·Git Index는 시작과 동일하다.

진단은 Git 제외 `workbench_runs/diagnostics/studio_ui_refresh_20261117_001/`에 저장한다. 이 폴더는 제품 실행 의존성이 아니다. 실물 로봇에서 연결 준비→Teleop 시작 Handshake는 이번에 실행하지 않았으며 실제 Qt와 Fake Backend 명령으로 검사했다. 기존 Capture 저장 시간이나 실물 제어 성능을 이번 외형 변경의 성공으로 확대하지 않는다. Commit/Push·Reset/Clean·설치·다운로드는 하지 않는다.
