# Leader Teleoperation 복구와 기존 워크플로우 이관 감사

2026-10-30. 기준 `3b6250038ca42e68fad5b682c261a9b4a27e59df`, 브랜치 `scene-preparation-v8`. **Real/Sim에서 빠진 Leader→Follower 경로와 Capture의 시작 차단을 수정했다.** 영상/저장이 제어 주기를 멈추던 문제도 실제 Qt 시험으로 찾아 별도30Hz Serial 제어 루프로 교체했다. 원본 프로젝트·Scene·Calibration·Dataset·Checkpoint·SDK를 변경하지 않았으며 실제 로봇 Goal/Torque는 보내지 않았다. 아래 Memory 시험을 실물 성공으로 해석하지 않는다.

## 원인과 바뀐 동작

기존 `soarm101_lab/real2sim/runtime.py`의 `start`·`tick_real`과 Real/Sim tick은 Leader 명령→Follower 적용→측정 q 기반 Sim을 연결했다. 새 프로젝트에서는 Real/Sim을 Follower 관측으로 바꾸며 Leader 입력·명령 제한·Worker 명령을 제거한 것이 직접 원인이었다. 기존 기능의 단순 코드 정리가 아니라 사용자 동작이 빠진 결과였다.

Capture는 이관 구성에 이동 제한이 없었는데 UI가 YAML 편집을 요구하며 시작 버튼을 비활성화했다. 추가로 토크가 꺼진 팔의 오래된 Goal과 측정값이 일치해야 제안을 만들고, 승인 전후 전체 측정값을 exact 비교하여1count 흔들림도 거부했다. 이 차단들을 단순히 없애지 않고 아래의 명시 승인·재검사 흐름으로 교체했다.

초기 Qt 시험은 승인 직후 활성 상태만 확인하여 이후 제어가 멈추는 문제를 놓쳤다. 저장 후 화면에 남은 `Stale session heartbeat/control cycle`을 직접 확인했고, 관측 처리를280ms 멈추면 Leader 제어도 멈추는 RED를 만들었다. Camera/렌더/파일·Preview와 같은 반복문에서 `tick()`을 호출하던 구조가 원인이었다. 200ms guard를 늘리지 않았다.

## 실제 사용

기존 연결을 중단하고 창을 닫은 뒤 `./run_workbench_ui.sh`로 새로 실행한다. 실행 중인 사용자의 창/장치/Worker를 강제로 종료하거나 재시작하지 않았다.

- **Capture:** Scene·장치 구성 선택 → 로봇 연결 → **Teleoperation 시작** → 이동 제한이 없으면 화면에서 두 값을 입력 → 현재 Model/Precision·방향·범위·자세와 초기화 동작 현장 확인/승인 → Leader 조작 → 자세 안정 후 반복 Capture → Teleoperation 중지/연결 해제.
- **Real/Sim:** 닫힌 실행 Scene·MuJoCo/Isaac 선택 → **Real/Sim 연결** → 이동 제한 검토 → Scene 초기화 뒤 현장 승인 → Leader가 실제 Follower를 제어하고 **Follower 측정 q**가 Sim에 반영 → Capture로 Real Side/Sim Side/Real Wrist/Sim Wrist 저장 → 중단. 승인을 취소한 경우 연결 버튼이 재승인 동작을 제공한다.
- 제한값은 장치 설정 기본 폼에서도 입력·새 구성으로 저장할 수 있다. JSON/YAML과 같은 버퍼를 사용하며 재연결을 강제하지 않는다. 임의의 승인된 하드웨어 제한 기본값은 만들지 않았다. Leader가 없는 구성은 관측만 가능하다고 명시한다.

Leader와 Follower의 시작 자세가 크게 다르면 승인 전에 수동으로 자세를 맞춰야 한다. 이동/추종 제한·Model/모터 범위·Mapping·SDK Encoder 오류를 UI 편의를 위해 우회하지 않는다. 실제 카메라 수신률과 노출 시간 정합은 이번에 개선/인증한 사항이 아니다. Capture는 기존 skew100ms·age200ms·안정성과 새 Camera sequence를 검사하며 최대5초 기다린다.

## 코드 책임과 명령 경계

| 파일 | 현재 책임 |
|---|---|
| `ui/session_operations.py`, `recipe.py`, `run.py` | 저장된 Leader/Precision/제한 보존, Prepared identity와 실제 UI 준비, 양 Session의 R03 제어 명령 |
| `ui/teleop_controls.py`, `device_setup.py` | 공통 이동 제한 폼·현재 제안의 현장 승인. YAML 편집 중 불완전 입력도 보존하며 장치 SDK를 import하지 않음 |
| `ui/session_page.py`, `real_sim_page.py` | Capture 시작과 Scene 준비 후 승인 연결, 세 동작의 Real/Sim UI, 숨김/종료의 권한 중지 |
| `robot/supervised.py` | 기존 Saturation·교집합·Precision inverse·SDK 정수 encoding, 제안·현재 상태 재검사, 제한·추종·deadline |
| `robot/teleop_loop.py` | 양 Session이 공유하는30Hz SDK 단독 소유, 취소 확인·고정 측정 cache·300행 bounded 기록 queue |
| `robot/session.py`, `real_sim.py` | 관측/Camera·Capture transaction·Native 기록 소비·종료. Sim에는 Leader 목표 대신 측정 q 전달 |

```text
저장 구성/제한 → R03 준비 → 관측 연결 → 현장 승인
                          → 30Hz Leader→Mapping/Encoding→Follower
                          → 고정 Raw/Native/q/시각 cache
                          → Camera/Native Scene 렌더/원 Snapshot·Pair/Builder 등록
```

활성 중 Follower와 Leader의 Serial은 제어 루프만 읽고 쓴다. UI/렌더/파일 작업은 함께 고정된 측정 cache를 사용한다. 비활성일 때만 직접 Follower 읽기로 복귀한다. Recorder는 제어 행을 별도로 받아 기존 Native에 기록하며 Snapshot의 `q_command=null`, Teleop Native의 `training_ready=false`는 유지한다. MuJoCo/Isaac은 실제 닫힌 v8 자산·기존 Mapping을 사용하고, Sim 관절 상태 적용과 RGB만 수행한다. 추가 q offset·IK·Physics/Task Step은 없다. Isaac float32 차이를 별도로 기록한다.

승인 SHA에는 장치/Calibration/Mapping·범위·Raw/Goal/Mode/Torque·이동 제한이 결합된다. 토크가 켜진 축의 Goal 불일치는 계속 거부한다. 미구동 축은 **명시 승인 후** 현재 Raw로 Goal을 정렬하고 readback 뒤 Torque를 켠다. Leader Torque 해제도 승인 내용이다. 인코딩 직후와 Torque 직전에 다시 읽어 승인 자세 대비1count 초과 변화·범위 초과를 거부한다. 승인창의1count 흔들림 허용은 좌표나 기계 범위를 확장하는 epsilon이 아니다. 자동 Home·무승인 Hold·모터 재설정·SDK configure는 없다.

이 권한은 **현재 연결의 감독 Leader Teleop 전용**이다. 관측 Calibration을 `device_command` 또는 physical_verified로 재명명하거나 Gripper/자율 Policy 권한을 주지 않는다. 현장 사용자가 해당 Mapping·방향·범위를 확인해야 한다. 이번 무인 시험에서는 그 확인을 실제 장치에 대해 자동으로 채우지 않았다.

Stop/cancel은 같은 batch의 시작/Capture보다 우선하고 Goal 직전에도 확인한다. 기존 feedback100ms·control/send200ms·UI heartbeat1.5s 및 Session3s guard는 유지한다. Stop은 제어 thread 종료를 기다리고 새 Goal을 막으며 Torque를 유지한다. SDK 호출 종료가 불명하면 동일 bus를 동시에 disconnect하지 않고 다른 소유 자원 정리 후 실패/unknown을 보고한다. timeout·쓰기 실패는 자동 재전송하지 않는다.

기록 queue가 가득 차면 다음 Goal 전에 중지한다. Recorder가 수락한 행만 queue에서 제거하고, 기록 실패는 같은 Session의 재승인을 차단한다. 소유 Camera/렌더/Writer 정리는 계속하고 Worker는 실패한다. 기존 `session-report.json`에 최대300행 미기록 명령의 값/시각·개수·오류를 진단으로 보존하며 이를 정상 Episode나 재전송 입력으로 사용하지 않는다. 저장 장치 오류로 보고서도 쓸 수 없는 상황의 무손실/자동 복구를 보장하지 않는다.

## 검증 결과

최종 전체 **1,179 passed / skipped0**, 기존 torchvision 영상 deprecation 경고4회다. Builder/Scene Contract·Recipe/Hub/Qt·Source/Annotation/DataGen·Native/Resume/Curation·ACT/SmolVLA/Diffusion 회귀를 포함한다. 새 Training·Hub 쓰기나 실물 구동은 수행하지 않았다.

- 실제 Qt→R03에서 **Memory만** 자동 승인하여 Capture와 Real/Sim 각각 활성 제어를5초 유지하고, Capture 저장·1320/1920 화면 갱신 뒤에도 활성/오류 없음을 확인한 뒤 중지했다. 기존 첫 UI 시험의 늦은 제어 중단을 숨기지 않고 별도 보존했다.
- 별도 production RealSim Session에서 Memory Leader를 움직여 Follower 측정값 변화, **실제 Native MuJoCo와 Isaac**의 q/RGB, 네 이미지 Pair와 Reader를 확인했다. 엔진별 선택한 release Capture1개이며 초기 실행/상속 자료를 합산하지 않는다. Physics Step0이고 실제 장치가 움직인 시험이 아니다.
- Goal 초기화 중 자세 변경·승인 거부·powered Goal 불일치·1count jitter·Stop 직전 읽기 경합·제어 중 관측280ms 대기·queue 초과·기록 실패 시 정리/보고서·준비 취소·잘못된 YAML 등 실제 호출 seam의 RED→GREEN을 확인했다.
- 수정 중 발견한 UI의 삭제 함수 import도 production `prepared()` 재현으로 고쳤다. 첫 전체의 공유 포트 시험 실패는 Memory helper의 가상 port 분리 뒤 해당 시험이 같은 port를 지정하지 않았기 때문이었다. 실제 포트 잠금 검사를 완화하지 않고 명시 공통 가상 port로 다시 검증했다.
- Workbench wheel source/config bytes·compile·격리 import/CLI·실제 invalid-config Worker를 확인했고 설치하지 않았다. 별도 lint/type 도구를 설치·실행했다고 주장하지 않는다.
- 독립 Spec/Standards 검토에서 나온 준비 경로·활성화 자세 경합·종료/기록 실패 지적을 재현·수정했다. 리뷰 범위와 실제 하드웨어 검증은 별개다.

공식 Native Reader로 Qt 실행의 Capture 제어200행·Real/Sim 제어280행을 재로드하여 Applied=joint_targets·다음 측정 상태 연결을 확인했다. Snapshot/Pair Reader와 원 RGB640×480도 확인했다. 이 수치는 Memory 제어 기록이며 실물 명령/성공 Episode 수가 아니다.

최종 Qt 화면: [Capture1320](evidence/leader-teleop-recovery/final-capture-1320.png) · [Real/Sim1320](evidence/leader-teleop-recovery/final-real_sim-1320.png). 실제 UI와 Native 렌더이며 줄무늬 Camera는 명시 Memory 합성 입력이다. 표시 FPS/age를 실물 성능 수치로 보고하지 않는다.

## 기존 전체 워크플로우 코드 감사

기존 `soarm101_lab`·Builder의 실제 호출과 현재 모듈을 대조했다. 아래는 코드 연결 상태와 이관 공백이며 이번에 전체 물리/학습 E2E를 새로 실행했다는 표가 아니다.

| 사용자 작업 | 현재 코드 상태와 누락 |
|---|---|
| Capture·Leader Teleop·Real/Sim | 이번 수정 대상. UI→R03·공통 제어·실제 양 엔진/Memory 검증. 현장 실물 연속 구동은 미검증 |
| Precision 기준각 Calibration | **미이관**. 기존 `precision.CalibrationSession.command`의 기준 수집→fit→review→activate가 현재 UI에 없다. 현재는 읽기/기존 Profile 재검토이며 SDK Encoder Calibration 버튼이 이를 대체하지 않음 |
| Builder Import·검토·Export | 기존 기능 호출은 있으나 **일반 Export→Real/Sim 등록 연결 누락**. 선택 목록은 `execution_packages`만 읽고 제품 writer는 이관용 `scene_migration.register_package`뿐이다. 이관된 v8 선택 성공을 새 Scene 전체 사용성으로 주장할 수 없음 |
| Source→Annotation→Fixed/Random DataGen | 구체 양 엔진 Runner·기존 StableGrasp/Placement·DLS/Best Effort·Saturation·Native 저장 연결 있음. 이번에는 회귀/코드 대조이며 새로운 전체 Task 성공률 검증 아님 |
| Curation→공식 Dataset→Training/Resume→독립 Validation→Sim Evaluation | 기존 Reader/materialize·공식 Factory/Trainer/processor·구체 평가 Runner 연결. ACT/SmolVLA/Diffusion 회귀와 과거 smoke 범위, 모든 모델/새 학습·일반화 성공을 뜻하지 않음 |
| Hub Download·기존 Repo Upload | 고정 Commit/입력 검사·parent-commit 업로드 연결. **새 빈 Repo 최초 업로드 공백**: 생성 뒤 resolve가 HUB_EMPTY_REPOSITORY로 거부하고 uploader는 parent SHA를 요구함 |
| 실물 자율 Policy | **명시 미완료**. 현재 Observe/Fake/Gripper 한정. 기존 실제 Policy rollout과 완전 동등하지 않으며 이번 Leader Teleop 승인을 자율 Policy 승인으로 확대하지 않음 |

`Workspace Pipeline`의 별도 Teleoperation 페이지는 기존 Fake/Gripper 계약이며, 실제 감독6축 작업은 위 Capture/RealSim Session에서 수행한다.

따라서 **전체 워크플로우의 상위호환 완료는 아니다.** 위 공백 네 가지를 남은 작업으로 명시했으며 이번 버그 수정 뒤 자동으로 다른 기능·실물 구동·원격 쓰기를 시작하지 않는다. 승인된 DLS/Saturation·공식 LeRobot/native 경계를 폐기하고 옛 범용 Adapter/자체 Trainer를 복원하는 방식으로 해결하지 않았다.

원본56,100개 stat·원본 Python187개 SHA·선택 SDK/과거57개 SHA·보존 Policy/Capture47개 SHA 변화0과 v8 전체 Manifest identity 일치를 확인했다. 전체 SDK/corpus 전수 byte hash는 아니다. 로컬 개발 브랜치만 사용하고 main 변경·Push/Merge는 없다. 자산/런타임/증거는 기존 Git 공개 제외 정책을 유지한다.

근거: 로컬 `docs/evidence/leader-teleop-recovery/`의 RED/GREEN 로그·최종 JUnit·실제 엔진/Qt 결과·wheel·보존·Spec/Standards·verification. 마지막으로 직접 확인할 것은 새 창에서 두 화면의 연결→현장 승인→Leader 추종→Capture→중단이며, 함수는 `Teleoperation.start/tick`, `TeleoperationLoop`, 각 Session의 `observe/close`다. 상태 `TELEOP_ACTIVE`, 측정 q 기반 Sim, 네 이미지 저장과 중단 후 새 Goal 차단을 현장에서 별도로 확인해야 한다.
