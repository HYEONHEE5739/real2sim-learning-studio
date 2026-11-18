# Real/Sim Scene 선택·연결 지연 조사

2026-11-18. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `25bb1cf083f2ce05a93c3bc2b9e290ba4f6cbf3b`. 사용자가 문의한 두 대기를 구분해 현재 코드와 기존 실물 실행 기록을 조사했다. **Scene 선택은 전체 Package 조회·검사를 기다리고, 연결은 장치 준비와 Sim 초기화·첫 영상까지 기다린다. 느린 `auto_version`에는 매 영상 갱신 시 전체 기하 검증을 반복하는 큰 병목이 있다.** 이번에는 원인을 조사했으며 제품 코드를 수정하지 않았다.

## Scene을 고른 뒤 버튼이 늦게 활성화되는 경로

`ui/real_sim_page.py`의 버튼 활성 조건은 `BackendJob`이 끝났고 `template`이 준비됐을 때다. 다음 작업을 마칠 때까지 버튼이 비활성화된다.

1. `refresh_scenes → session_execution_scenes`: 모든 Project의 등록된 실행 Package에 `load_scene`을 호출한다. 이름만 가져오는 조회가 아니라 Manifest와 파일 SHA까지 검사한다.
2. `loaded → load_selected → session_real_setup`: 고른 Package를 다시 읽고 연결된 장치 설정·엔진 설정을 찾아 실행 Recipe를 만든다.
3. 이 결과를 받아 `template`을 설정하고 버튼을 활성화한다.

현재 `showEvent`는 탭을 열 때 `force=True`로 목록을 다시 조회한다. 목록 응답을 받으면 선택값이 같아도 `load_selected`를 다시 호출한다. 1.5초 타이머가 매번 무조건 전체 재검사하는 것은 아니다. 평소에는 Project 파일의 시각/크기가 바뀌었는지 비교하고, 탭 표시 때 강제 조회한다.

실제 Qt `BackendJob/QProcess`로 읽기 전용 호출을 각각 한 번 측정했다.

| 범위 | 시간 | 검사량 |
|---|---:|---|
| 실행 Scene 목록 조회 | 1.428초 | Package9개 / 파일 해시1,090회 |
| `auto_version` 선택 설정 조회 | 0.251초 | 선택 Package1개 |

이는 기존 파일이 있는 현재 환경의 단회 측정이다. 사용자의 클릭부터 실제 버튼 repaint까지를 측정한 값이나 cold disk 최악 시간은 아니다. 이 검사만으로 사용자가 겪은 수십 초 대기 전체를 설명한다고 주장하지 않는다. 목록과 같은 선택의 반복 조회가 불필요한 추가 대기를 만드는 구조는 확인됐다.

## 버튼을 누른 뒤 Real/Sim 연결이 오래 걸리는 경로

`SessionClient`는 `prepare` 작업을 끝낸 뒤 별도 `start` 작업으로 R03 Worker를 실행한다. 그 과정에서 입력 Package·Mapping 등을 검사하고 장치 생성자와 `SceneView`를 준비한다. R03 Worker도 실행 전 입력 동일성을 다시 확인한다.

`RealSimSession.connect` 안에서는 기존 spawn Writer 준비 → Leader/Follower 연결 → Side/Wrist 시작 → 입력 재확인 → RenderProcess 생성이 순서대로 진행된다. Renderer 부모와 자식 모두 `SceneView`를 만든다. `render_type=authored`이면 `validate_binding`에서 Builder Scene 전체를 검증한다. 자식은 MuJoCo용 Scene 변환·모델 준비를 수행한다.

Real 카메라에 영상이 들어와도 `RealSimSession.observe`는 **첫 Sim 영상이 도착해야** `CONNECTING → OBSERVING`으로 바꾼다. UI의 명시 연결 요청으로 예약된 Teleop 시작도 이 상태 전환 이후다. 따라서 Real·Sim의 준비 시간이 연결 대기에 함께 반영된다.

## 확인한 큰 병목: 매 프레임 전체 기하 검사

느린 기존 실행은 `auto_version / scene-codex-first-fit_001`의 authored 비교 Scene이었다. 전체 Package는245파일·112,470,872B다. Builder의 `authored_scene.json`에는 자산456개가 있다.

`AuthoredRenderer.render → observation_scene → scene.validate`가 q로 포즈를 갱신할 때마다 전체 검증을 호출한다. `scene.validate`는 compound Collision Part를 검사할 때 Scene의 자산 목록 전체를 넣어 자기 자신을 재귀 호출하고, 각 호출의 마지막에서 **전체 자산 SHA**를 다시 계산한다. 같은 불변 Geometry를 여러 번 읽는 비용이 매 영상에 붙는다.

엔진·GPU·장치 생성 없이 해당 Scene의 `validate(..., complete=True)`만 한 번 실행해 다음을 확인했다.

| 검증1회 내부 작업 | 실제 측정 |
|---|---:|
| 총 시간 | **8.274초** |
| 재귀 호출을 포함한 `validate` | **141회** |
| 자산 SHA 계산 | **64,296회** |
| 반복 해시의 논리적 읽기 합 | **3,903,444,423B** |
| Mesh 읽기 / 검사 Face 합 | 410회 / 7,464개 |
| 자산 목록의1회 논리적 크기 | 27,684,003B |

3.90GB는 파일을 복제하거나 다운로드했다는 뜻이 아니다. 같은 자산을 반복 읽은 합계이며 OS 파일 Cache가 실제 디스크 접근 일부를 줄일 수 있다. 단일 저우선순위 프로세스에서 측정했고 모델 Forward·렌더·USB 접근은 하지 않았다.

## 실제 기존 기록과의 대조

기존 `real_sim_20261118_01`은 위 `auto_version`을 선택한 실물 세션이다.

| 보존 기록의 구간 | 값 / 한계 |
|---|---|
| R03 `prepared.json` 게시 → Renderer `config.json` | 약12.018초. 파일 mtime 차이이며 장치별 연결 시간을 분리한 계측은 아님 |
| Renderer 설정 저장 → `ready.json` | 약15.168초. 자식 Scene 검증·변환·모델 준비를 포함 |
| 첫 영상의 `render_ms` | **7,821.93ms** |
| 후속 서로 다른 영상의 `render_ms` | 7,434.97 / 7,383.77 / 7,366.18ms 등 |

첫 영상뿐 아니라 다음 영상에도 수초가 걸린다. 이번 순수 검증8.274초와 일관된 규모이며, 코드에서 전체 검증의 반복 호출도 확인했다. 위 파일 시각과 `render_ms`를 사용자의 클릭부터의 정확한 총 지연으로 합산하지 않는다. prepare/start 이전 대기와 이벤트별 시각은 별도다.

`real_sim_20261118_02`의 다른 Scene인 `pickplace_colorblock / scene-v9-task-objects`는 첫 `render_ms`가 **4.16ms**, 다음 값들이 약3–4ms였다. 따라서 모든 Scene이 같은 속도인 것은 아니다. 이 Scene에 실제 로봇을 다시 연결하거나 이번에 새 Sim을 실행해 비교한 결과는 아니다.

느린 세션의 로그에는 software rendering 요청과 EGL/AMD 장치 초기화 경고도 있다. 코드상 authored MuJoCo Renderer의 기본 모드는 `software-egl`이다. 다만 이번 순수 기하 검사만으로8초가 재현됐으므로 EGL 경고를 전체 지연의 단일 원인으로 확정하지 않는다. 실제 GPU 사용·드라이버 별도 검증은 하지 않았다.

## 개선할 위치

- Scene 목록은 가벼운 목록 조회와 선택 Package의 완전한 검사를 분리하고, 같은 선택을 다시 여는 경우 불필요한 재조회를 줄인다. 실행 전 원본 동일성 검사는 유지해야 한다.
- 불변 Mesh/Collision/자산 전체 검증과, 매 q 변경 때의 유한값·좌표·포즈 검사를 분리한다. 파일이 바뀌면 전체 검증을 다시 수행해야 한다. 특히 compound Part마다 전체 자산을 재해시하는 경계를 먼저 줄일 필요가 있다.
- Scene 초기화·장치 준비·Sim 준비·첫 영상 대기를 화면에서 구분해 표시한다. Sim 준비 전 제어를 무조건 허용하는 변경이나 안전 검사를 생략하는 방식으로 대기를 숨기지 않는다.
- 렌더 모드 변경은 기하 병목을 정리한 후 별도 장치/Context 검증으로 판단한다. 이번 조사에서 드라이버·환경·Scene 설정을 변경하지 않았다.

## 조사 범위·보존

제품/시험 코드 변경0, 로봇/카메라 연결0, 새 Sim/AI 실행0, pytest/전체 회귀0이다. 기존 Scene/Capture/URDF/Calibration·실행 중 세션을 수정하거나 종료하지 않았다. 위 성능 값은 읽기 전용 함수/Qt QProcess 호출과 기존 기록 조사이며 실물 재현 테스트가 아니다. 앞선 영상 잘림 수정과 다른 미커밋 변경도 보존했다. Commit/Push는 하지 않았다.

근거는 Git 제외 `workbench_runs/diagnostics/real_sim_startup_analysis_20261118_001/`의 `selection-results.json`, `qt-selection-results.json`, `validation-results.json`, `historical-startup.json`, `verification-summary.json`이다. 진단 스크립트는 제품 실행 경로에 연결하지 않았다.
