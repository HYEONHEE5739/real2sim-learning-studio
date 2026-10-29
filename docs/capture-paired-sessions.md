# Real2Sim Capture / Real-Sim — 지속 Session 구현

2026-10-29. 기준 `1e645745fc9d2d31ecfd1e48e535630bb495511d`, 개발 브랜치 `capture-paired-sessions`. 첨부 시안의 구성·버튼 배치를 기준으로 한다. 이미지의 FPS/관절값/상태를 실제 측정값으로 사용하지 않는다. main/기존 브랜치·원본 Scene/Dataset/Calibration/SDK는 보존하며 Push/Merge와 무인 실물 Goal/Torque 시험을 하지 않는다.

## 조사한 책임과 변경 경계

기존 `robot/live.py`는 최대300 frame의 유한 RO 관측·저장 결과 비교다. 이를 지속 Session에 억지로 확장하지 않는다. `capture_session` / `paired_session`의 명시 R03 stage와 `robot/session.py`가 연결·명령·종료 수명을 소유한다. UI 두 탭은 별도 Session 화면이며 범용 WorkflowPage의 유한 Capture/RealSim 조작을 대체한다. 독립 Offline/Observe/Precision/Policy/Gripper 검사와 명시 과거 Recipe는 유지하되 새 Session 화면에서 두 수명을 혼합하지 않는다.

- Session: Leader/Follower/Camera 한 번 연결, 명시 command ACK·연결 해제/작업 종료·오류·watchdog. UI에는 SDK 객체 없음.
- Teleoperation: 기존 command_target/encode_model_target/SDK encoding 재사용. 별도 현장 승인 capability를 가진 명령 채널만 실제 쓰기 가능. 기존 RO Follower의 activate/send 차단은 유지한다.
- Capture: 사용자 Snapshot 명령마다 실제 Follower 관측·원 RGB·시각·품질·Identity를 기존 real2sim.capture/1로 보존. 정지 측정을 학습 Action으로 만들지 않는다.
- Real/Sim: frozen measured q와 명시 Candidate/Model/Camera identity의 비동기 Render. 실제 노출과 동시 렌더로 표현하지 않는다. 원 Real을 보존한 파생 Pair/재렌더 결과를 저장한다.
- Builder: 기존 Project/Evidence/Import/Scan/사진/관측 Scene 계산·Renderer 사용. Scene 전의 미결합 Capture는 등록 가능하되 기하 Calibration에는 부적격/NEEDS_MORE_DATA다.

기존 Builder import는 완전한 Robot Base/Camera 선언을 전제로 한다. 미확인 Transform/K를 identity나 가짜 측정값으로 채워 통과시키지 않는다. Capture 등록과 Reconstruction 적격성의 경계를 명시적으로 분리한다. Project는 mutable Evidence를 소유하므로 준비 identity는 Project ID/project.yaml과 명시 Candidate/입력 bytes를 고정하며 추가 Snapshot 때문에 Project 전체를 불변 파일 집합으로 취급하지 않는다.

## 안전 및 실행 계약

Connect는 읽기 전용이다. 관절 Mapping·Calibration bytes·실제 Identity/모터 범위·model bounds를 검사한다. Start Teleoperation은 현재 연결의 승인 제안과 현장 감독/위험 제거/정지 수단/방향·범위 확인에 결합한 한 번의 명시 ACK다. 초기 Goal/Feedback·모드/토크를 읽어 확인하고 급격한 동작 가능성이 있으면 BLOCKED다. Stop/Disconnect는 새 Goal을 차단하며 승인하지 않은 Home/Hold/자동 Torque 해제를 하지 않는다. UI heartbeat·명령 age·feedback·jump/follow error 위반은 송신을 차단한다. 실물 Policy 자동제어는 이번 권한에 포함되지 않는다.

Snapshot은 Project/Session/command ID로 중복 처리를 막는다. Pending 저장→Hash/Reader 확인→Builder transaction 등록→UI 완료 순서다. 미확인/blur/stale 관측을 Calibration 성공으로 승격하지 않는다. 기존 Camera skew100ms/age200ms를 확대하지 않는다. Real/Sim은 동일 q 기반 Pair이며 hardware synchronized exposure가 아니다.

## 작업 순서와 검증

1. Session/명령/장치 승인 경계와 Fake 시험.
2. Scene 없는 Snapshot·Project 자동 등록·복구·수동 외부 입력.
3. Candidate의 측정 q Render·Pair·비교·재렌더.
4. 시안 기반 두 화면·장치 설정 공통 버퍼·기존 UI 연결 정리.
5. 실제 Qt/Worker/Fake E2E·허용된 RO 읽기·실 엔진 Render·전체 회귀/wheel·독립 두 축 리뷰·보존.

실제 실물 6축 동작은 현장 사용자 승인 없이는 검증하지 않는다. 구현/Fake/실제 RO/실제 Render/실물 구동을 구분해 최종 결과를 기록한다.
