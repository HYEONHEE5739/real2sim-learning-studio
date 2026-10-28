# Robot·Calibration·Capture 묶음 — RO01~RO03

2026-10-26. 상태: **RO01~RO03 계산·파일 계약·fake 장치/SDK 검증 완료, 실물 검증 BLOCKED**. R01~R03의 완료 증거와 현재 제품 SHA를 확인한 뒤 B03의 CAL-01/02·ROBOT-01/02를 선행 근거로 사용했다. 실제 로봇·모터·카메라·보정 장치 연결/명령, 시뮬레이터·정합 Export·UI·공식 Policy 실행·Hub 작업은 하지 않았다. 다음 묶음도 시작하지 않았다.

## 구현 범위와 재사용

| Task / 제품 파일 | 구현·검증 |
|---|---|
| RO01 / [calibration.py](../robot_learning_workbench/src/robot_learning_workbench/robot/calibration.py) | JOINTS·단위·raw/native/model·branch/정수 역변환·fit/review/held-out 검사·mapping hash·명시 프로필 읽기·limits-only 메모리 binding·Scene Encoder record 연결 |
| RO02 / [devices.py](../robot_learning_workbench/src/robot_learning_workbench/robot/devices.py), [control.py](../robot_learning_workbench/src/robot_learning_workbench/robot/control.py) | 명시 SDK 객체/설정, 연결·read·hold/activate·send·Stop·close·자원 정리, readonly CalibrationDevice, SDK 정수 인코딩/Teleop 공통 범위 계산 |
| RO03 / [capture.py](../robot_learning_workbench/src/robot_learning_workbench/robot/capture.py), devices.py의 CameraReader | host-time 정렬·안정성·pair 품질·RGB/해상도·blur·보정 snapshot 계약, bounded camera thread/프레임 copy·종료 오류 |

위 4개 소유 모듈과 일반 robot/__init__.py, test_precision_calibration.py/test_robot_lifecycle.py/test_capture_contract.py를 추가했다. 기존 Scene·Task·Episode·Recipe 제품/시험·task_modules.yaml·pyproject/환경 의존성은 바꾸지 않았다. 별도 Device ABC·Manager·plugin·registry·환경을 추가하지 않았다. Leader는 같은 SO101 bus 수명/읽기 구현만 재사용하고 Leader.send는 거부한다.

기존 precision.py의 fitter/검토·검증/branch·inverse와 hardware.encode_goal, core.Stability/assess_pair·capture_dataset의 계산을 사용했다. 원본 모듈을 런타임에 import하거나 원본 경로/활성 포인터/Git를 찾아 실행하는 호환 계층을 만들지 않았다. 일반 native degree/percent의 명시적 과거 관절 변환은 부분 Precision 프로필의 보정되지 않은 관절/오프라인 옛 자료 의미를 보존하기 위한 계산이다. MiniVLA 모델·학습·로더·평가·전용 변환은 없다.

## RO01 — 숫자 공간·identity

- 권위 있는 순서는 shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper다. 프로필 JSON 순서를 배열 순서로 사용하지 않는다.
- raw는 이미 Homing_Offset이 적용된 encoder count, native는 팔 degree/그리퍼 0..100 percent, model은 6관절 rad다. 관측 범위 밖 값은 원 측정 근거로 보존하며 명령 허용과 구분한다.
- 기존 분기/half-turn·모델/모터 범위·Python round·ceil/floor·1e-7 count·정수 역변환을 보존했다. raw feedback과 activation hold write에서 원 정수 packet을 float로 바꾸지 않는다.
- fit_joint/review_joint/validate_joint와 PrecisionMapper가 원 reference·계수를 다시 확인한다. OFFSET_ONLY/REVIEWED_MANUAL/VALIDATED_MANUAL과 physical_verified=false를 구분한다. 소프트웨어 fit 통과를 물리 정합으로 승격하지 않는다.
- load_profile은 지정 파일 bytes SHA·role/device identity를 검사한다. 활성 프로필을 자동 선택/저장/활성화하지 않는다. mapper_from_metadata는 지원 schema·joint_order·hash/content를 확인하고 불명 schema를 기본 mapper로 대체하지 않는다.
- profile_for_model은 변경 시 source_model/execution_model의 전체 bytes와 SHA를 요구한다. 전체 XML에서 여섯 관절 lower/upper만 제외한 비교, 원 limits 대조 후 메모리 copy만 갱신한다. Git/원 저장소 조회를 제거했으며 runtime_model_binding.persisted=false와 B03 mapping hash는 동일하다.
- mapper_from_scene은 S01/S02가 검증한 package의 필수 파일을 재확인하고 선언된 Encoder/runtime/role/phase·모델 identity로 연결한다. baked residual을 Encoder나 q 보정으로 재실행하지 않는다. Geometry 보정 생성/엔진 적용기는 이번 범위가 아니다.

## RO02 — SDK·연결·명령·실패

Follower/Leader는 명시적으로 전달된 공식 SDK 객체 또는 동일 구체 API의 fake를 사용한다. from_config는 설치 LeRobot 0.4.1의 구체 클래스를 지연 생성하는 경계이며 connect와 분리한다. 기존 role/port/device·calibration 파일/모터 id/model/spec·mapping identity를 확인한다. Leader의 과거 identity.id는 선택 calibration 파일명이고 Follower는 SDK device id다. 이 차이를 임의 통일하지 않았다.

connect는 bus.connect만 호출하여 자동 configure/calibrate를 피한다. Follower activate는 disable torque→원 raw Present→같은 Goal→Goal readback→공식 configure 순서다. Leader activate는 토크 해제만 한다. Feedback read는 원래의 단일 raw packet을 normalize하고 host read interval을 기록한다. 매 read/SDK encoding에 추가 하드웨어 calibration 조회를 넣지 않는다. encode/send의 파일·mapping·register spec 검사는 메모리/파일 검사다.

encode_goal은 기존 최대16회 nextafter 보정과 공식 int() encoding을 유지한다. command_target은 Teleop에만 공통 모델/엔진/모터 범위→strict inverse→SDK 정수 목표→같은 Sim model 목표를 계산하며 send/Sim.step은 하지 않는다. Policy/replay에 Teleop clipping을 자동 적용하지 않는다. DataGen의 0.5rad IK jump guard를 새 장치 제한으로 추가하지 않았다.

- Stop은 새 goal 전송 중단·마지막 목표 유지다. bus write/토크 해제/물리 즉시 정지가 아니다. SDK send 반환도 실제 도달 feedback이 아니다.
- 입력/identity 오류로 send 전 실패하면 effect=not_applied, SDK 전송 timeout/configure 부분 실패는 unknown이다. send timeout 후 재시도를 막으며 자동 명령 replay가 없다.
- 공식 SDK configure의 torque_disabled finally가 **실패 때도 enable_torque를 호출**하는 실제 함수 body를 fake bus로 실행했다. 실패 뒤 owner는 release 요청/close를 시도하지만 물리 토크 상태를 보장하지 않는다.
- SDK disconnect가 torque release 전에 실패하면 closePort까지 가지 않을 수 있다. owner가 포트 정리를 별도로 시도하고 원 오류·port_closed·torque_state를 함께 남긴다. 포트가 닫혀도 torque_state=unknown/unmeasured이며 안전 정지 완료로 쓰지 않는다.
- close_devices는 첫 자원 오류/KeyboardInterrupt 뒤에도 나머지 소유 자원을 정리하고 오류를 모아 보고한다. 정상/오류 이후 중복 close가 모터 write를 반복하지 않는다. 실패/불명 상태는 반환 CleanupResult나 DeviceError.cleanup에 남긴다.
- CalibrationDevice는 exclusive port와 readonly 관측, approved=true인 선택 관절 release+Torque_Enable=0 readback을 구분한다. close/unlock 실패에서도 disable_torque=False로 정리하여 원 토크 보존 의미를 유지한다. 실제 ioctl은 시험에서 fake였다.

## RO03 — Camera·Capture

CameraReader는 공식 OpenCVCamera의 connect/read/disconnect를 명시 사용하고 import/조회만으로 연결하지 않는다. RGB·원 해상도, 요청/보고 설정·buffer request 수락 여부를 구분하고 90개 deque·소유 frame copy·nearest를 유지한다. nearest는 freshness 보장이 아니다. close는 .5s join→disconnect→1s join을 시도하며 thread 생존/오류를 종료 완료로 숨기지 않는다.

시간은 host monotonic/unix receipt interval이다. exposure/hardware sync는 가용하지 않으며 hardware_synchronized=false다. align_measured는 model 좌표에서 팔 선형 보간/그리퍼 왼쪽 hold, interpolation/nearest 100ms 경계를 유지한다. Stability는 .6s·최소3표본·gap<=.2s·팔 span<=1°·그리퍼<=2points이며 tip spread는 진단이다. assess_pair의 100ms/200ms·.035rad/2points 경계를 보존했다. 평가의 별도 stale 500ms 조건으로 바꾸지 않았다.

prepare_snapshot은 명시 mapping·joint_order·실제 measured history·raw/native 근거·200ms/100ms·안정 창·RGB uint8·원 해상도·blur>=10을 검사한다. 팔/그리퍼·요청/적용/관측을 합치지 않고 passive 관측에 motor command를 허용하지 않는다. 누락/NaN·불명 mapping/시간을 가짜 측정으로 채우지 않는다. blur 경고는 calibration 대상 제외이며 이미지를 다른 frame으로 복제하지 않는다. 기존 snapshot 반환(measured/카메라 records/warnings)에 mapping/model identity·joint_order/units·hardware_synchronized=false를 명시하고 반환 Metadata는 소유 copy다.

원 K/distortion/optical mount와 가상 render K를 분리했다. B03 optical→OpenGL flip 행렬의 숫자만 대조했으며 엔진 카메라 변환·현재 Fabric pose·픽셀/물리 정합은 구현/검증하지 않았다. 이번 Capture 범위는 준비/유효성/시간·프레임 수명 계약이다. Snapshot 파일 publish·ProfileStore save/activate UI·Recipe stage runner/장치 IPC·Real/Sim 연결은 완료로 표시하지 않는다. Episode Writer를 Capture 전용 형식으로 복제하지 않았다.

## 검증 증거·결과

**전체 647 passed, skip 0 = 기존 571 + 신규 76**. [JUnit](evidence/robot-operations/unit-tests.xml), [Task별 결과](evidence/robot-operations/task-results.json), [명령/identity](evidence/robot-operations/commands.json), [최종 검증](evidence/robot-operations/verification.json)을 남겼다.

- RO01 25개: B03 실제 Leader/Follower **60개** 표본·mapping SHA exact, command/observation 경계·모델/identity·부분/fit/held-out·Scene 연결.
- RO02 27개: fake 연결/activation/Stop·timeout·부분 연결/중복 close·모든 소유 자원/KeyboardInterrupt 정리·readonly Calibration, 실제 공식 SDK configure/finally/disconnect/normalization/정수 encoder 함수의 fake 입력 실행.
- RO03 24개: B03 camera/time 경계·stability·nearest/소유 copy·실제 fake camera thread·join timeout·snapshot/blur·누락/잘못된 입력·부분 profile raw 그리퍼 saturation 보존.
- [수치 대조](evidence/robot-operations/numeric-comparison.json): 원래 PrecisionMapper와 60관절 표본, 원래 Runtime.command_target과 **5개 Teleop 목표**, Stability **5개 sequence**, snapshot 원래 measured 필드·카메라 records·warnings **exact**. 전역 NumPy RNG 불변이다. 실제 프로필/URDF와 합성 host-time/RGB fixture의 계산이며 실물 촬영 자료로 새 검증한 것이 아니다.
- [wheel](evidence/robot-operations/build.json): 최종 소스/config 일치·compile·isolated robot import/계산·기존 CLI/실제 worker의 STAGE_UNAVAILABLE 오류 통과. 설치하지 않았으며 SDK/engine/device를 import·시작하지 않은 smoke다.
- [오프라인 guard](evidence/robot-operations/offline-guard.json): 테스트 부모에서 장치 경로/실제 ioctl/네트워크와 기존 환경 쓰기를 차단했고 위반 0개다. 기존 R의 로컬 fixture subprocess는 별도이며 실제 stage runner를 사용하지 않는다.
- [보존 대조](evidence/robot-operations/preservation-after.json): 기존 전체 파일 stat와 선택 SHA, B01~T04·D/R 보고서/증거 및 기존 제품/시험/패키징을 비교한다. 전체 대용량 corpus/SDK binary의 전수 byte 증명은 아니다.

시험 중 fake normalize가 부분 packet을 처리하지 못한 오류를 실제 SDK 방식으로 고쳤다. 초기 unknown normalization·키 누락 검사를 강화했고, raw hold/feedback의 정수 보존·중단 시 cleanup·추가 calibration read 부재를 RED/GREEN으로 확인했다. 실패 로그를 보존했고 B03 기대 수치·원본·tolerance를 바꾸지 않았다. 초기 full suite644 후 해당 경계 3개를 추가해647로 검증했다.

## 의도된 차이·남은 관문

의도된 차이는 명시 모델 증거 공급(Git/active 자동 resolve 제거), 지원되지 않는 schema/mode/비수치 입력 차단, 부분 연결/정리 오류의 누락 방지와 effect 상태 명시, Capture identity/소유 copy다. 알려진 정상 수식·곱 순서·Quaternion·Threshold·관측/명령 단위·Stop hold는 변경하지 않았다. 일반 SDK configure의 register 값을 임의 변경하는 제어기를 추가하지 않았다.

AC01의 새 계산·identity 회귀와 AC02의 대표 fake 수명/오류는 검증했다. **AC03 및 CAL/ROBOT의 실물 항목은 BLOCKED/미검증**: 실제 register/file 일치·motor 방향/held-out 정합·torque/readback·port/케이블/SDK timeout·UI/프로세스 상실의 실제 Stop 지연·camera exposure/buffering/실해상도/실제 pairing·공식 Policy 명령/도달이다. fake에서 release/close가 통과해도 실제 안전 정지/토크 해제/포트 정리가 증명된 것이 아니다.

B01 Isaac DataGen 실패/Evaluation 비결정성, B02 phase/tick·저장 누락/IK별 Resume, v8 UNVALIDATED/프로필 physical_verified=false·ASSET-FINGER-01은 그대로다. 신규 IK·Scene Export·엔진 연결·Policy·UI 작업을 시작하지 않았다. Python3.11.15와 기존 NumPy/PyYAML/h5py/OpenCV/LeRobot 설치 환경을 사용했고 설치/업그레이드·환경 분리는 없다. 별도 lint/type 도구는 설정되지 않아 실행했다고 주장하지 않는다. Git 저장소 초기화/commit도 하지 않았다.

다음 후보는 **BU01~BU03: Builder 프로젝트/재구성→정합→Export closure**다. 저장 후보/scan·정합 fixture의 선행조건을 먼저 확인하고, Finger Collision·contact pad·보정 근거 모델을 package/manifest/실제 상대 참조로 연결하는 검증을 진행할 수 있다. 실제 engine 이동/로딩 검증은 E01/E02까지 분리한다. **제안만 하며 자동 시작하지 않는다.**
