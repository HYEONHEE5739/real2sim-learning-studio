# Capture 조작·정합 상태 표시 수정

> 현재 동작은 [Leader Teleoperation 복구·워크플로우 감사](leader-teleop-recovery.md)를 따릅니다. 아래는 이전 구현 당시의 결과이며, Real/Sim의 Leader 제어 누락·Capture 제한값 UI·제어 주기 분리는 후속 작업에서 수정했습니다.

2026-10-30. 기준 `c3bff2a`, 브랜치 `scene-preparation-v8`. 사용자가 실행 중인 Session의 로그를 읽고 Qt 재현 시험으로 Capture 점멸·Teleoperation 오류 덮어쓰기를 확인했다. 기존 Session을 종료하거나 실물 장치에 새로 접속하지 않았다.

- Capture 버튼은 매 status마다 True→False로 바뀌던 구현을 제거하고 한 번에 최종 상태만 적용한다. 프레임별 저장 적격성과 촬영 요청 가능 여부를 분리한다. 연결 중 요청은 가능하고 대기/저장/종료 중에는 차단한다. 실제 저장은 기존 최대5초 대기와 안정성·100ms skew·200ms age·새 Camera sequence 검사를 그대로 통과해야 한다.
- 현재 Wrist의 관측 수신률은 약8.4FPS/119ms 간격이다. 100ms 정합 기준을 일시적으로 넘는 구간이 있으므로 새 프레임을 기다린다. 낮은 실제 FPS를30FPS로 고쳤거나 Camera 노출 동기화를 달성했다고 주장하지 않는다. age/시간차/안정성·Gripper percentage point 수치를 구분해 이유를 표시한다.
- 실제 Teleoperation 거부 원인은 구성의 명령 변화/추종 오차 제한 미설정이었다. 이 메시지가 다음 Camera status에 덮여 숨겨졌다. 별도 오류 영역에 보존하고 구성 미완료 때는 시작을 막고 이유를 표시한다. 제한값을 임의로 넣거나 실제 Goal/Torque를 보내지 않았다. 기존 현장 승인·초기 Goal/feedback·Mapping/Encoding·watchdog 검사는 유지한다. 거부된 proposal만으로 빈 Native recording을 만들지 않는다.

기준 코드의 RED는 `docs/evidence/capture-session-feedback/01-ui-red.log`, `02-request-red.log`, `03-teleop-red.log`, Gripper 진단은 `13-gripper-reason-red.log`다. 집중36 PASS 후 실제 Stability를 사용하는 추가 Gripper 진단을 포함한8개 시험이 통과했다. 직전 전체1,152 PASS/skip0·기존 경고4회는 추가 Gripper 시험 이전 실행이며, 후속 Real/Sim 변경을 포함한 최종 전체 결과와 구분한다.

실제 사용 Session의200개 timing status를 Qt에 재생한 결과 Capture 버튼은 처음1회 활성화된 후 반복 전환0이었다. 실제 장치 연결 없는 MEMORY CameraReader를 Side약14.7FPS/Wrist약8.1FPS로 실행하고 기존 Session/Writer/Builder·공식 Reader에서 새 Snapshot2개를 소비했다. 요청 뒤 새 측정값으로 저장됐고 각 Camera/joint skew는100ms 이내, command는null이다. 실제 새 촬영/실물 구동 시험과 구분한다. 초기 harness의 normalized Reader에 없는 `q_command`를 찾던 오류는 원 state.json을 직접 대조하도록 고쳤고 별도 새 출력에서 재실행했다.

읽기 전용 확인·최소 수정 범위에서 Scene/Calibration/Dataset/Checkpoint 및 SDK 원본은 보존한다. 실행 중인 사용자의 창은 Python 코드를 자동 갱신하지 않는다. 새 UI/Worker를 사용하려면 사용자가 연결을 해제하고 창을 닫은 뒤 `./run_workbench_ui.sh`로 다시 열어야 한다. 실행 중인 Session을 에이전트가 강제로 재시작하지 않는다.
