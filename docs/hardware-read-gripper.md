# 실물 읽기·Capture·Observe Only·Gripper 단일 명령 경계

2026-10-29. `hardware-read-gripper-only`에서 구현했다. 기준은 병합된 `main`의 `ab94b87d3f579031db0c751f274c0ab7fe6b87e6`이며, 검토 기준 `7db7438`과 제품 tree가 같다. **실제 Leader/Follower 읽기, 양 엔진 Live Source, Camera Capture, measured-q 렌더 비교와 공식 Policy Observe Only를 실행했다. 실물 모터 목표·토크 명령은 보내지 않았다.**

실물 전체축은 **BLOCKED — ARM_MOTION_NOT_APPROVED**다. Gripper 단일 명령은 구현·Fake 검증했지만, 현재 command Calibration·토크/현재 Goal 조건·현장 확인·방향/작은 변위 승인이 충족되지 않아 **실제 구동은 BLOCKED**다. 이번 결과에 `GRIPPER_MOTION_VERIFIED`나 실물 6축 `END_TO_END_VERIFIED`를 부여하지 않는다.

## 구현과 재사용

| 책임 / 파일 | 실제 처리 |
|---|---|
| `robot/devices.py` | 공식 SDK의 port open·read·정규화·identity 검사를 재사용. 실물 SDK bus는 자동 읽기 전용, 전체축 activate/send 차단, disconnect는 `disable_torque=False`. 같은 포트의 관측 worker 중복 접속도 차단한다. |
| `robot/configuration.py` | 명시 SDK Calibration bytes·장치 ID·포트·Precision profile 확인 후 기존 Leader/Follower를 구성한다. Source의 기존 `create_leader`도 이 읽기 전용 경로를 사용한다. |
| `robot/control.py` | 기존 model/motor 교집합·inward Saturation·Precision inverse·SDK 정수 encoding을 유지한다. 기존 encoder에 그리퍼만 선택하는 경계를 추가했다. |
| `robot/live.py` | 기존 R03가 소유하는 유한 관측 loop. 실제 feedback/RGB·지연·Policy Action을 기록하며, 읽기 전용 Capture/Precision/Real-Sim/Observe와 별도 승인 Gripper trial을 연결한다. |
| `robot/teleoperation.py` | 기존 `command_target`/`encode_model_target`를 사용하는 메모리 장치 전체축 Teleop·공식 Policy loop. 실제 SDK serial 생성자를 호출하지 않는다. |
| `robot/capture.py` | `CameraReader`, `Stability`, `align_measured`, `prepare_snapshot`와 기존 Builder `real2sim.capture/1`을 사용한다. 별도 Dataset 형식을 만들지 않는다. |
| `robot/calibration.py` | 기존 `fit_joint`/`review_joint`로 보존 reference를 재검토하고 parent SHA를 가진 새 Revision만 저장한다. 원 SDK 보정 파일을 수정하지 않는다. |
| `recipe.py`, `run.py` | 저장 Recipe·Prepared identity·기존 worker·명령 ACK에 연결했다. Convert/Merge도 기존 materialize/merge 함수를 호출한다. |
| `ui/workflow.py`, `ui/operations.py`, `ui/hub.py` | Live Leader 선택, Teleop/실물 관측 모드, 측정/Sim 이미지 재개방, Profile Revision, Gripper 별도 승인, Repo 생성의 명시 승인을 연결했다. 엔진/Torch는 Qt 프로세스에서 실행하지 않는다. |

새 Manager·Control Framework·Trainer·Dataset 포맷은 없다. 엔진 Source/Annotation/DataGen/물리 계산과 Builder/Scene Contract 제품 코드는 변경하지 않았다. Native는 기존 포맷에서 Fake Teleoperation stage의 기록을 받도록 했다. 기존 저장 자료를 마이그레이션하지 않는다.

## 장치와 명령 차단 근거

실제 USB identity를 확인한 Leader는 `5AE6054683`, Follower는 `5AE6056779`이며 각각 `/dev/ttyACM0`, `/dev/ttyACM1`로 해석됐다. motor ID는 JOINTS 순서 1~6, 모델은 `sts3215`다. Leader SDK Calibration SHA는 `64c786df…`, Follower는 `28be25b5…`다. 카메라는 기존 `/dev/cam_side`와 `/dev/cam_wrist`를 사용했다. 이 ID 일치는 물리 Calibration 정확도 승인이 아니다.

공식 `SO101Follower.connect/configure`의 전체 관절 설정 경로를 호출하지 않고 bus의 연결·읽기만 사용했다. 실물 bus의 `activate/send`는 연결 전부터 거부한다. `stop/close`도 전체 Goal 재전송·Home·Torque Enable/Disable을 수행하지 않는다. Gripper 예외 경로 외에는 실물 Goal 쓰기가 없다.

실제 read probe는 bound instance의 register-write/torque API를 실패하도록 감시했다. 금지 API 호출 시도는 0이었고, cleanup은 port closed/torque preserved였다. 최종 읽기 검사의 **6축 Goal·Torque 전후 값이 모두 같았다.** 모든 torque 값은 0이었으며 활성화하지 않았다. 이것은 소스/Fake 호출 추적·실제 register 대조 근거이며 별도 serial wire analyzer 시험은 아니다.

## 실제 실행과 상태

| 기능 | 확인한 결과 | 상태 / 범위 |
|---|---|---|
| Leader/Follower read | 각각 실제 Raw/Native/model-rad feedback 및 Calibration register 검사. 별도 유한 probe 각8회 | HARDWARE_READ_VERIFIED. 명령·토크 변경 없음 |
| 실제 Camera | Side/Wrist RGB640×480, 원 RGB PNG 및 host receipt 시각 저장 | HARDWARE_READ_VERIFIED. 초기 독립 수집 Side 약15.536FPS, Wrist 약8.292FPS. 설정30FPS와 실제 처리율을 구분 |
| Live Leader→MuJoCo Source | 완료1 Episode /14 frame·양 RGB·requested/applied | END_TO_END_VERIFIED: 읽기→Simulation→Native. 실물 Follower 동작 아님 |
| Live Leader→Isaac Source | 완료1 Episode /4 frame·양 RGB·requested/applied | 같은 제한의 END_TO_END_VERIFIED. 기존 v8 physics/Collision 유지 |
| 실제 Capture | 최종 Qt 버튼→실제 R03→24 measured sample/48 PNG→공식 Builder Reader | HARDWARE_READ_VERIFIED / UI 저장 경로 END_TO_END_VERIFIED. 관측 loop 약20.215Hz |
| Builder Import | 새 검토 Project에 Capture 및 Real/Sim 참고 이미지 연결, 검토 Candidate 생성 | 기존 Import API 소비 확인. Candidate 미승격·Export 없음·v8 수정 없음 |
| Precision | 실제 Raw/SDK Calibration 확인, 기존 reference fit/residual 재검토 | 읽기는 VERIFIED, 새로운 독립 각도 기준/물리 Calibration은 PARTIAL |
| Real/Sim | 양 엔진에서 실제 측정 q를 상태에 반영하고 Side/Wrist 렌더 | HARDWARE_READ_VERIFIED. 실제 로봇 명령0·Physics Step0. MuJoCo float64, Isaac float32 상태 표현 구분 |
| 전체축 Teleop/Policy | 메모리 장치의 mapping/limit/encoding/send/readback/Native | FAKE_VERIFIED. 공식 ACT/SmolVLA/Diffusion 각3 frame, 합9 frame |
| 실물 Gripper | 단일 motor6 Goal의 계산·승인·취소·SDK packet 경계 | IMPLEMENTED / FAKE_VERIFIED. 실제 motion BLOCKED |
| 실물 전체축 Policy | 실제 SDK activate/send 및 full-real mode 차단 | BLOCKED — ARM_MOTION_NOT_APPROVED |

Live Source는 움직임을 새로 만들도록 사용자에게 요구하지 않고 현재 Leader feedback을 읽었다. 시뮬레이션에서는 기존 6축 Step을 수행했다. Source의 success는 `recording_only`이며 Annotation/DataGen의 grasp AND placement 성공이 아니다. MuJoCo 기존 Source는 post-state 배열을 저장하지 않아 pre[t+1]=post[t]를 증명했다고 보고하지 않는다. Isaac Source에는 그 배열 exact를 확인했다. 저장된 양쪽 Source의 `joint_targets`와 Applied는 exact다.

Source의 저장/폐기/취소는 기존 R03 command 경로에 연결했다. 이번 실제 장치 실행은 bounded 자동 종료와 기록을 확인했으며, 모든 수동 버튼·장치 장애를 새로 실물 주입한 것은 아니다. 관련 상태·취소·partial publish·cleanup은 순수/Fake 및 기존 회귀로 검사했다.

## 공식 Policy Observe Only

기존 checkpoint와 공식 Factory/processor/`select_action`/postprocessor를 사용했다. RGB는 실제 uint8를 float32 BCHW `[0,1]`로 바꾸며 state는 measured model rad6이다. 후처리된 Action은 기록만 하고 `send`를 호출하지 않는다. 새 학습/가중치 다운로드는 없다.

| 실제 관측 실행 | 추론 / Queue | 해석 |
|---|---|---|
| ACT 최종 bounded 진단 | 3 frame, Queue9→8→7. 첫 호출 약205.962ms, 이후 약2.910/2.607ms | 실제 입력/공식 queue 소비. 같은 수정 전 3-frame 실행의 Wrist 시간 정합 실패도 별도 보존 |
| SmolVLA | 3 frame, Queue3→2→1. 첫 호출 약5,906.404ms, 이후 약4.260/3.849ms | 기존 SHA 고정 padding 호환 경로 유지. queue 소비를 network forward3회로 보고하지 않음 |
| Diffusion | 초기 유효 실제 입력1 frame, 약30.377ms. 이후 3-frame 실행은 Wrist stale/skew로 실패 | 단일 추론 확인과 연속 입력 BLOCKED를 구분. 최종 Hardware Queue 연속 검증은 미완료 |

이 시간은 CPU 추론의 작은 표본이며 전용 benchmark가 아니다. Action을 계산한 시점까지의 observation latency에는 추론 시간도 포함한다. Camera/Joint skew100ms·age200ms 경계를 완화하지 않았다. ACT/Diffusion의 실패한 3-frame attempt를 성공 횟수에서 숨기지 않는다. 마지막 ACT 추가 진단은 수정된 오류 기록 경로를 확인하려고 실행한 별도 bounded attempt이며 앞선 실패를 덮어쓰지 않았다.

읽기 전용 실행 오류는 `FAILED`·수집된 Observation·오류를 저장하고 원 예외를 전파한다. Observation 행 수가 성공한 추론 횟수와 항상 같지는 않다. Policy Reset/port/camera cleanup을 수행한다. 초기 Smol/Diffusion 진단의 queue 숫자는 `_action_queue`만 보던 제한이 있었고, 현재는 공식 `_queues['action']`도 검사하며 알 수 없는 구조는 `null`로 기록한다. 이전 0을 실제 empty queue 증거로 재사용하지 않는다.

## Capture·Calibration·Real/Sim의 의미

Capture는 실제 q·Raw/Native·시각·원 RGB·mapping·파일 SHA를 저장한다. 임의 Action을 q에서 만들지 않는다. 따라서 **모터 적용 명령이 없는 정지 관측 Capture를 6축 Action 학습 Demonstration으로 자동 Export하지 않는다.** Simulation Source처럼 실제 적용 목표가 있는 Native는 기존 Curation/LeRobot 경로를 그대로 쓴다.

새 Capture는 `.pending`에서 공식 Reader 검증 후 최상위 `COMPLETE`를 마지막에 공개한다. 모델/mesh는 원본 bytes를 공유하고 RGB는 원본 PNG다. Camera frame 재사용은 실제 sequence로 구분한다. Host receipt 시각이며 hardware exposure 동기화가 아니다. 최종 Capture의 Wrist blur/texture heuristic은 부적격 경고였고, Builder는 명시 static interval·새 Calibration 승인이 없는 이미지를 calibration-eligible로 승격하지 않았다.

Scene을 지정한 Capture만 기존 base/camera 선언을 Builder에 전달한다. provenance는 `inherited_scene_unverified`, `mapping_verified=false`, `physical_verified=false`다. Scene 없는 관측 Capture는 Reader 재로드와 Builder의 base/camera 결합 준비 상태를 구분해야 한다. 기존 SDK Calibration/Profile에 새 각도/기계적 한계/임의100°를 넣지 않았다.

Real/Sim RGB는 photometric 차이만 계산했다. 초기 실제 MuJoCo Side/Wrist MAE는 약106.521/199.358, Isaac은 약158.317/212.519(0~255 RGB)였다. 대응 Landmark가 없어 기하 오차는 unmeasured다. 일부 Camera/Joint skew도 report에 보존한다. 이 값을 metric Calibration 오차나 새 보정 성공으로 해석하지 않는다. 기존 E01 cube–cup1.197188790mm 잔차는 OPEN이다.

## Gripper 승인 경계와 남은 조건

`gripper_proposal`은 명시 `device_command` binding, 원 모델/승인 motor/Precision 범위 교집합, 현재 Raw/Goal/torque/mode, 실제 SDK 정수 변환과 양자화 후 범위를 검사한다. 기본 이동량·방향은 없다. current Goal과 feedback 불일치·torque0·stale feedback·calibration 변경·허용 budget 초과는 거부한다. 토크를 자동 켜거나 현재 위치를 Hold로 재전송하지 않는다.

승인은 현재 proposal SHA·motor6 target raw·감독/위험 제거/정지 수단의 명시 확인에 결합한다. 제안은30초 후 무효이며 현재 연결에서 한 번만 소비한다. 같은 batch에 cancel이 있으면 승인보다 우선한다. 사전 읽기 도중 Stop도 전송 전에 다시 확인한다. 중복 승인·전송 timeout·feedback 오류 뒤 재전송하지 않는다. 적용 여부 불명은 `FAILED/effect=unknown/command_sent=unknown`으로 기록한다.

**현재 v8에는 승인된 device_command 결합이 없고, 실제 torque는0이다. 안전 방향/작은 변위·현장 감독/주변 위험 제거/전원 차단도 승인받지 않았다.** 이 상태에서는 구동 승인 질문만으로 실행할 수 없다. 필요한 보정/안전 범위 근거를 먼저 준비한 후, 현장 감독과 명시 단일 동작 승인을 별도로 받아야 한다. 이번에 해당 명령이나 torque 전환을 수행하지 않았다.

## Dataset·Hub·UI

실제 Live Source의 영구 선택 구간 각4 frame을 새 Revision에 저장하고 production R03 Convert로 공식 Dataset을 만들었다. 호환 Merge 결과는2 Episode/8 frame이며 공식 `LeRobotDataset`/DataLoader가 state/action6축·양 RGB640×480을 소비했다. Action은 해당 엔진의 Applied를 공식 float32로 읽은 값과 exact다. 원 Episode UID/선택 offset·영상 공유·기존 계약 검사를 유지한다. 고유 Camera sequence와 기록 control frame의 의미도 구분한다.

Hub download/기존 Repo parent-commit upload는 기존 기능을 유지한다. 새 Repo 생성은 공식 `HfApi.create_repo`를 명시 repo/type/private/confirm으로 호출하며 Fake API 검증했다. **실제 Hub 생성/업로드는 미수행**이다. 빈 Repo의 첫 commit 업로드는 현재 parent-commit guarded uploader로 지원하지 않아 `HUB_EMPTY_REPOSITORY`로 막는다. Repo 생성 버튼을 첫 업로드 완료로 표시하지 않는다. 토큰은 Recipe/결과에 넣지 않는다.

Qt는 실물/Simulation/Fake 모드를 구분하고 팔 구동 버튼을 제공하지 않는다. Gripper 승인 버튼은 worker의 유효 제안 전에는 비활성이다. 실제 offscreen Qt/QTest에서 Fake ACT 저장 실행, 실제 Capture 버튼 실행, 보존 Capture/Real-Sim 재개방과 양쪽 이미지 표시를 확인했다. 파일 선택만 자동화했으며 production worker·SDK read·Camera를 Fake로 대체하지 않았다. 사람이 장기간 사용한 UX 검증은 아니다.

## 검증·보존·완료 경계

**최종 전체 1,069 passed / skipped0**, 기준1,026개에서 신규43개다. 기존 torchvision 영상 deprecation 경고4회가 남는다. Workbench/Builder wheel의 source/config bytes·compile·격리 import/CLI 및 invalid-config 실제 worker를 검사했고 설치하지 않았다. 별도 lint/type 도구를 설치하거나 실행했다고 주장하지 않는다.

원본 **56,100개 stat·선택 과거/SDK57개 SHA 변화0**, v8 전체 Manifest 검증 통과다. 추가로 실제 소비한 Policy/processor/state·명시 Capture/Calibration 입력47개 파일의 전후 SHA 변화0을 확인했다. 전체 SDK binary/대용량 corpus 전수 hash 증명은 아니다. 최종 근거는 `final-tests-final.xml`, `build-workbench.json`, `build-builder.json`, `preservation-after.json`, `read-inputs-after.json`이다. 원본 Scene/Calibration/Dataset/Checkpoint 및 설치 SDK를 변경하지 않았고, 새로운 v9·Training·실물 arm 동작·원격 Hub 쓰기·GitHub Push/main Merge는 수행하지 않았다. 현재 변경은 별도 개발 브랜치에만 저장한다.

독립 Standards/Spec 두 축 리뷰의 최종 High/Medium 잔여는0이다. 취소 우선·중복 승인·부분 Fake 취소·Policy provenance/Queue 기록·Capture 완료 표시·Builder Import 항목·오류 기록을 실제 RED→GREEN으로 수정했다. 마지막 실제 Camera 검사에서 드러난 시간 정합/blur 제한은 성공으로 고치지 않고 남긴다.

정밀한 물리 Calibration, 시간 정합이 보장되는 연속 실제 Policy 입력, 승인된 Gripper 단일 구동, 실제 전체축 Teleop/Policy, 장시간/장치 단절·전원 장애, 실물 Task 성공은 미검증이다. Camera timestamp는 수신 시각이며 노출 시각이 아니다. 실물 전체축 차단과 원본 보존을 유지한 상태에서 이번 작업을 중단한다.

로컬 근거: `docs/evidence/hardware-read-gripper/`의 `consumer-results-final.json`, `official-consumer.json`, `ui-results.json`, `release-v2-capture-result.json`, 실제 장치 read 및 Policy 결과, 최종 JUnit/wheel/보존/두 축 review/verification 기록. 증거 폴더는 기존 Git 공개 제외 정책을 유지한다.

공식 경계 근거: [LeRobot0.4.1 MotorsBus](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/motors/motors_bus.py), [Feetech bus](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/motors/feetech/feetech.py). 설치 SDK 소스와 실제 읽기/Fake 호출 검증을 우선 근거로 사용했다.
