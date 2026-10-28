# B03 — Precision Calibration·Robot·Camera·Device 계약 조사

실행일: 2026-10-25. 상태: **B03 조사·대표 오프라인 계약 검증 완료**. 제품 구현, 보정 활성화, Scene Export, 데이터 변환, 시뮬레이터 실행 및 실제 장치 연결·제어는 수행하지 않았다. CAL/ROBOT의 구현 선행 의미를 확인한 결과이며 **실물 검증 완료 보고서가 아니다**. B03 다음 작업은 시작하지 않았다.

## 1. 범위·근거·검증 수준

P=`/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab`, B=`/home/hyeonhee/soarm_isaaclab/real2sim-builder/app`, L=`/home/hyeonhee/miniconda3/envs/lerobot-arena/lib/python3.11/site-packages/lerobot`. 아래 코드 경로는 해당 루트 기준이다. 기존 Python 3.11.15와 Sim5.1/Lab2.3/LeRobot0.4.1/MuJoCo3.3.7 환경을 변경하지 않았다.

| 증거 | 실제 확인 범위 |
|---|---|
| [inventory.json](evidence/b03/inventory.json) | 원본 활성 포인터·21개 저장 프로필·5개 reference journal, v8 Metadata, 모델 identity, 설치 SDK AST 대조, 읽은 입력 79개 SHA, 실제 함수 위치 |
| [existing-tests.json](evidence/b03/existing-tests.json) | B01의 원본과 동일한 참조 복사본에서 기존 오프라인 시험 **75개 통과**, 15개 선택 제외. fake 장치·임시 프로필만 사용 |
| [calibration-probes.json](evidence/b03/calibration-probes.json) | 실제 Leader/Follower 프로필의 **60개 관절 표본**, 거부 조건 **12개**, v8 보정 URDF **6개 관절**·모델 적용 모드 대조 |
| [camera-probes.json](evidence/b03/camera-probes.json) | 저장된 optical/engine Transform·K, host 시각 경계·interpolation·fake CameraReader 등 **23개 검사 통과** |
| [device-probes.json](evidence/b03/device-probes.json) | 원래 수명 메서드 및 공식 SDK에 fake bus/port를 전달한 **23개 검사 통과**. 예외·부분 연결·Stop·토크 보존/해제 경로 포함 |
| [commands.json](evidence/b03/commands.json) / [최종 검증](evidence/b03/verification.json) | 인터프리터·실행 명령·조사 코드 identity·보존 대조·문서 검사 |

참조 복사본의 조사 대상 P 코드 SHA를 현재 원본과 대조했다. 테스트는 새 제품의 구현이나 새 장치 Driver 시험이 아니다. `Serial`/`VideoCapture` 호출 차단, `/dev/tty*`·`video*`·USB 접근 차단, 실제 ioctl·네트워크·실행 subprocess 제한, B03 밖 쓰기 제한을 둔 조사 harness를 사용했다. 원래 pytest 중 Qt/렌더/데이터 저장 등 이번 범위 밖 시험은 선택하지 않았다. 모델 증거 검색의 읽기 전용 `git log/show`와 NumPy의 `lscpu`만 subprocess 예외다.

초기 harness는 NumPy의 lscpu·URDF의 git 조회 및 임시 파일의 dir_fd 삭제까지 차단하여 실패했다. 해당 로그/JSON을 `*-guard-initial*`, `*-guard-second*`로 보존했고 읽기 전용 조회와 B03 내부 삭제의 경로 해석을 수정했다. 최종 시험의 차단 기록은 0개다. 이는 물리 장치의 상태를 측정했다는 뜻이 아니다. Device probe 로그의 `mock close failure` traceback은 의도한 예외 전파 시험 결과다.

## 2. CAL-01 — 관절 공간·순서와 Encoder 변환

권위 있는 순서는 P `so101_joint_mapping.py:JOINTS`의 `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper`다. **프로필 JSON의 키 순서를 관절 배열 순서로 사용하면 안 된다.** 실제 Follower 프로필의 wrist_roll/wrist_flex 저장 순서도 이 배열과 다르다.

| 공간 | 단위·의미 | 실제 근거 / 보존 조건 |
|---|---|---|
| raw | homed Present_Position encoder count | `precision.py:199 raw_from_native`, `:208 native_from_raw`. 이미 Homing_Offset이 적용된 SDK 읽기다. 다시 빼지 않음 |
| native | 팔 calibration-relative degree, gripper 0..100 percent | `hardware.motor_specs`, SDK `_normalize/_unnormalize`. 팔 degree와 gripper percent를 하나의 각도 단위로 취급하지 않음 |
| model | 여섯 관절 URDF rad | `PrecisionMapper`, `representation.real_observation/real_action`. 물리 경계에서 한 번 변환 |
| policy | 공식 processor 입력·출력과 Dataset feature 계약 | model state/action과 일반 Source telemetry의 팔 rad·그리퍼 fraction을 구분. LeRobot 정규화는 processor 책임 |

resolution=P, 모터 calibrated 범위=[lo,hi]일 때 팔은 `native=(raw-(lo+hi)/2)*360/(P-1)`이다. gripper는 `(raw-lo)*100/(hi-lo)`이며 apply_drive_mode와 drive_mode가 켜진 경우에만 `100-value` 반전한다. arm DEGREES 분기에 gripper의 반전을 옮기지 않는다.

Precision의 모델값은 `q=rad_per_count*(unwrapped_raw-anchor_raw)+reference_angle_rad`다. fitting에는 `numpy.linalg.lstsq` 및 기존 검토/검증 조건을 사용한다. 1개 참조의 OFFSET_ONLY 추정과 독립 held-out 검증은 같지 않다. 원래 fitted 계수·reference·status를 다시 확인하는 `PrecisionMapper.__init__`을 생략하지 않는다.

- **관측:** `calibrated_to_observation` / `observed_positions`는 동일 raw packet과 native의 일치, 유한값·분기를 확인하고 모델 범위 밖 값도 보존한다. SDK가 clip한 gripper 표시값은 원 raw 근거로 복원할 수 있다. 모호한 half-turn(`abs(abs(delta)-period/2)<2 count`)은 오류다. 범위 밖 관측을 motor goal로 승인하지 않는다.
- **명령:** `urdf_to_calibrated`는 URDF bounds·calibrated motor range·유일한 encoder branch를 모두 검사한다. URDF 범위 내라도 모터가 표현할 수 없으면 거부한다. Python `round`와 정수 endpoint ceil/floor, branch tolerance `1e-7 count`, 역변환 확인을 보존한다. taught reference의 raw_domain을 전체 작동 범위로 잘못 제한하지 않는다.
- **SDK 전송 전:** `hardware.Follower.encode_goal`은 실제 SDK의 int 변환을 재현한다. float ULP 문제는 기존 최대 16회 `nextafter` 조건으로만 보정한다. 이는 Fixed XY 보정이나 새로운 제어 제한이 아니다. quantized model target을 다시 도출해 Sim과 비교한다.

60개 표본은 **모델·모터의 실제 공통 명령 범위**에서 추출했다. 관측한 최대 quantization 오차는 Leader `0.0007807138801166624 rad`, Follower `0.000768491353617895 rad`다. 이것을 새 tolerance로 채택한 것은 아니며 각 joint의 count당 각도 안에 드는지 검사했다. 원래 model 값과 quantized 값의 bitwise equality를 요구하지 않는다.

실제 Leader gripper는 모델 범위가 더 넓어도 이번 프로필의 표현 가능한 명령 범위가 약 `[-10.0°,81.6260°]`다. 처음 모델 범위만으로 추출한 `94.5°` 표본이 실제 motor-range 오류로 거부된 로그도 보존했다. Follower의 정수 목표 범위는 약 `[-9.9233°,99.9233°]`다. 이 범위를 물리 jaw opening의 실측값으로 해석하지 않는다.

## 3. CAL-01 — Calibration identity·적용 시점·중복 방지

| 실제 자료 | 확인된 값 / 의미 |
|---|---|
| Leader 활성 프로필 | `profile_a4ea4642b1da4587943331fb8083c322`, 6관절 REVIEWED_MANUAL, physical_verified=false |
| Follower 활성 프로필 | `profile_1a377745dd6441f0bacee6ff3f0a5690`, 6관절 REVIEWED_MANUAL, physical_verified=false |
| 저장 프로필의 원 URDF SHA | `3b676464eb11410752707021f9d07b988439b46e37d5605cdbfe9508de14e5dd` |
| 현재 기준 URDF SHA | `31da65a5af2b9b49531a79a410ca84e1cfe3eeac850818a330c2c8514f992960` |
| v8 residual의 기준 mapping SHA | `bcee6d870a3fc3c10283dbc564fad8f45ca2a1a89c67114a0af8054fd33b0f24` = 현재 메모리 binding 후 Follower mapping |

`ProfileStore.active`는 포인터의 ID·프로필 hash와 계수/reference 검증을 수행한다. `hardware.attach_precision`은 role·장치 id·port·모터 id/model·calibration 파일 SHA·register spec·resolution·normalization/drive mode를 대조한다. port의 이동 허용 정책이 이미 구현되어 있다고 추측하지 않는다. 파일이 있다는 사실만으로 현재 연결된 장치와 같다고 판단하지 않는다.

`precision.profile_for_model:326`은 **전체 URDF 증거**를 비교하여 lower/upper limits만 다른 경우에 한해 메모리 copy의 limits/model hash를 변경한다. origin/axis/geometry/topology 등 다른 차이는 거부한다. `runtime_model_binding.persisted=false`이며 프로필 저장/활성화가 아니다. B01에 확보된 정확한 과거 URDF를 사용했고 hash 검사를 우회하지 않았다. 새 Scene 패키지는 필요한 원 모델 증거·binding 의미를 보유해야 하며 실행 때 원 저장소의 Git 존재에 의존하게 만들지 않는다. 실제 패키지 생성은 BU03/S02 이후 범위다.

`precision.simulation_configuration:45`의 **장치 숫자 공간과 시뮬레이션 Geometry 선택은 별개**다.

1. 신규 실행은 workspace·원 URDF·residual·Builder mapping evidence를 대조한다. v8은 `precision_bound_residual`이며 보정된 `so101_sim.urdf` / `so101_sim.usda`를 선택한다. explicit identity 검증은 원 Asset을 선택한다.
2. `workspaces/builder.py:309 calibrate_simulation_usd`가 Export 시 Geometry joint zero-frame을 바꾼다. URDF `R_origin × R_axis(offset)`, USD localRot0 같은 곱 순서, parent/child·고정 world anchor의 구분을 보존한다. **모델 관절 q에 residual을 다시 더하지 않는다.** 이번에는 Export 함수를 호출하지 않고 기존 파생 URDF만 비교했다.
3. 기존 6관절의 보정 회전은 원식과 최대 `7.771561172376096e-16` 차이였고 origin translation은 동일했다. 곱 순서를 뒤집은 수치도 증거에 따로 기록했다. USD joint layer 및 PhysX/Fabric 실행의 새로운 동등성 검증을 수행한 것은 아니다.
4. 기록 기반 실행은 기록된 simulation_model fingerprint·workspace/model/residual 및 backend/scene 정보를 상속한다. 오늘의 active pointer나 identity UI 설정으로 과거 상태를 바꾸지 않는다. 같은 engine/scene 계약의 정확한 상속을 대조했다.
5. 실제 Policy 실행 전 `require_hardware_policy_frame:154`는 precise Policy에 완전한 승인 Follower mapping과 model kinematics를 요구한다. `REVIEWED_MANUAL` 허용은 **기존 실행 조건**이며 physical validation 승격이 아니다. Sim baked residual을 실제 로봇 command에 더하지 않는다.

기존 `mapper_from_metadata`는 알 수 없는 schema를 DEFAULT_MAPPER로 돌리는 fallback이 있다. 이를 새 공개 계약의 “알 수 없는 보정=보정 없음” 규칙으로 이관하지 않는다. 알려진 legacy 근거와 잘못된/미지원 Metadata를 구분해 실행 전 차단한다. [Interface](interfaces.md)의 unknown Schema 오류 방향을 유지한다.

## 4. ROBOT-01 — 연결·활성화·정지·해제 계약

아래는 **원래 메서드**다. 새 공통 Device ABC/Adapter나 추가 worker 계층을 제안하는 표가 아니다. 새 소유 파일은 이미 설계된 robot/devices.py·control.py·calibration.py다.

| 메서드(P real2sim 기준) | 입력/반환·효과 | 확인 수준 |
|---|---|---|
| `hardware.Leader.connect() → None` | 명시된 port/calibration 사용, direct bus connect·read 검증, 자동 보정/일반 configure 금지 | 코드·fake 경로. calibration mismatch의 로컬 cleanup 누락은 §7 |
| `Follower.connect() → None` | direct bus connect 후 정확한 6 `.pos`·native mode·calibration identity·limits·mapping·register 진단. 실패하면 close 시도 | 코드·기존 mock. “실패 cleanup도 읽기 전용”이라고 주장하지 않음 |
| `Leader/Follower.read() → (native, interval)` | 단일 raw packet→SDK normalize, last_raw·host monotonic/unix read interval 보유. 실패를 0으로 바꾸지 않음 | 오프라인 raw/normalize 시험 |
| `Follower.activate() → None` | calibration 재검사→토크 해제→raw Present 읽기→같은 raw Goal write→Goal readback 동일→공식 configure | fake 순서·readback 실패 검증. **activation부터 쓰기 부수 효과 존재** |
| `Follower.encode_goal(native) → (encoded_native, normalized_encoded)` | 읽기 전용 SDK 인코딩 preflight·last_encoded_goal_raw. 아직 전송하지 않음 | 설치 SDK를 포트 없이 호출한 기존 시험 포함 |
| `Follower.send(native) → (sdk_returned_native, interval)` | finite/full joints·범위·calibration 메모리/파일 SHA 재검사 후 공식 send_action | 반환은 SDK가 전송하려던 값. 실물 도달/접촉 ACK가 아님 |
| `Runtime.start()` | 매핑·피드백/목표 검사 후 activate, 이후 tick에 새 명령 | fake Start 시험. 큰 시작 자세 차이를 막는 새 guard는 현재 없음 |
| `Runtime.stop()` / `Follower.stop()` | 새 goal 중단·마지막 goal 유지. Stop을 토크 해제/물리 즉시 정지로 표현하지 않음 | 원래 메서드의 no-write 검증 |
| `Follower.close()` | 공식 disconnect 또는 부분 연결 bus.disconnect(disable_torque=True) | fake와 SDK 소스. 실패한 torque release가 완료됐다고 표시하지 않음 |
| `CalibrationDevice.connect/sample/close` | 보정 전용 exclusive port, 자동 configure 금지, readonly 관측. close는 disable_torque=False | 실제 ioctl/port는 사용 안 함. 해제 실패 후 finally의 disconnect를 mock 검증 |
| `Calibration.command('release', payload)` | 선택 관절만, supported_and_approved=true와 torque readback=0 필요 | 기존 FakeCalibrationDevice 시험. 실제 토크 해제 미실행 |

Precision의 프로필 save/activate/restore는 **소프트웨어 기록/포인터 변경**이고 모터 Homing_Offset/calibration register 쓰기와 다르다. 이번의 기존 Fake 장치 시험은 B03 임시 디렉터리에만 프로필을 만들었고 원본 포인터는 바꾸지 않았다. 실제 reference 수집은 선택 관절의 torque=0, raw/native read 일치·두 raw read 이동량 <=3 count, train/validation 분리와 제외 사유 journal을 보존해야 한다.

SDK configure의 부수 효과를 축소해서는 안 된다. L `robots/so101_follower/so101_follower.py:148 configure`와 `motors/feetech/feetech.py:222 configure_motors`는 Operating_Mode·P/I/D·Return_Delay_Time·Acceleration 등을 쓰며 gripper의 torque/current 관련 설정도 쓴다. 기존 motion diagnostics가 readonly라는 사실이 **activate 전체가 readonly이거나 기존 register 값을 모두 유지한다는 뜻은 아니다**.

## 5. ROBOT-02 — Sim/Real 명령과 평가

- **Native Source:** P `native/source.py:121 run`은 엔진/센서 검사 후 Leader를 연결하고 준비 시 고정한 mapping SHA를 재대조한다. Leader read→observed_positions→model rad requested→model/gripper bounds clipping→Sim 적용/기록이다. Source의 Leader 활성화는 수동 조작을 위한 토크 해제이며 실제 Follower를 구동하는 단계가 아니다. B02의 Isaac requested 누락·pre/post telemetry 의미는 그대로다.
- **Real/Sim Teleop:** `runtime.command_target:385`는 Leader model 요청, 모델/engine·모터 공통 범위, strict inverse, SDK integer goal, 다시 도출한 Sim model target을 구분한다. tick은 **Follower.send를 먼저**, 그 뒤 Sim.step을 실행한다. Sim step 실패가 이미 전송한 물리 명령을 취소하지 않는다. 이 경로의 오류 effect를 무조건 not_applied로 기록하면 안 된다.
- **수동 비교:** `set_measured_pose`는 실제 Follower feedback을 Sim에 표시한다. 범위 밖이면 원 관측을 보존하고 Sim은 마지막 유효 pose를 표시한다. feedback을 clip해 실제 측정값으로 저장하거나 follower goal을 보내지 않는다.
- **실제 Policy 평가:** `workflow/evaluation.py:471 run`, `:12 real_start_pose`. enable_motion 필수→공식 Policy/processor 로딩→카메라 시작/최대10초 준비→Follower connect→Policy/보정 frame 검사→float64 measured hold 역변환 검사→activate 순서다. 최초 camera frame 대기와 Follower 활성화의 순서를 보존한다.
- 실행 중 model observation은 policy float32, 공식 pre→select_action→post의 여섯 finite model rad action은 URDF로 clip한 후 strict inverse·encode_goal·encoded model bounds 확인·send를 수행한다. motor 범위 오류를 조용히 다른 command로 대체하지 않는다. camera host read가 500ms를 넘으면 오류다. 이 값을 Capture의 200ms와 통일하지 않는다.
- 기존 real 평가 결과의 `task_success='unmeasured; human review required'`를 확인했다. 실행 루프 SUCCEEDED가 실제 Grasp/Placement 성공을 뜻하지 않는다. Sim의 자동 Placement 종료 조건을 실물 평가에 새로 붙이지 않는다.

예전 평가 파일의 MiniVLA 이름이 붙은 경로 helper/Checkpoint 분기는 새 제품 이관 대상이 아니다. 유지할 것은 공식 ACT·SmolVLA의 processor/action 의미와 위 장치 계약이며 MiniVLA 호환 구현을 복사하지 않는다. DataGen의 0.5rad/step IK guard를 Teleop/실물 평가에 이미 있는 제어 제한처럼 해석하지 않는다.

## 6. CAL-02 — 카메라 Geometry·좌표·시각

| 항목 | 확인된 구현 / 보존할 조건 | 이번 검증의 한계 |
|---|---|---|
| Builder→v8 mount | B calibration/camera.py `project_point/fit_cameras`, P workspaces/builder.py:160. world optical pose 또는 `inverse(T_world_gripper) @ T_world_camera`로 gripper-local mount | 기존 자료·코드 조사. fit 재실행/실물 재보정 안 함 |
| 기준 값 | v8 side parent=world, wrist parent=gripper, K/distortion/resolution·T_parent_camera 저장. optical은 x-right/y-down/z-forward | 양 camera의 inverse/engine 왕복·투영 수치 검사. 실제 pixel/metric 오차를 측정한 것은 아님 |
| virtual/render K | profile.py:236 `render_k`: f=(fx+fy)/2, cx=w/2, cy=h/2. 원 K/distortion은 별도 유지 | 원본 K를 virtual K로 덮어쓰면 안 됨. synthetic 비대칭 K로 별도 동작 확인 |
| MuJoCo camera | mjcf.py의 `T_optical.R @ diag(1,-1,-1)` OpenGL convention | 행렬 왕복만 검사. 새 renderer 결과 검증 아님 |
| Isaac camera | CameraCfg ROS optical offset·update_latest_camera_pose, native/isaac.py:76 RuntimeCamera._update_poses의 PhysX/Fabric parent+mount 합성, runtime.snapshot의 실제 pos_w/quat_w_ros/K | authored USD wrist pose만 읽는 것으로 대체 금지. 이번엔 Isaac/pxr 실행 안 함 |
| 시각 | CameraReader의 read_start/read_end는 host monotonic+unix, exposure timestamp 없음. nominal fps는 hardware sync 증거 아님 | 실제 USB buffering/exposure latency·카메라 사이 동기 미검증 |
| frame 수명 | 90개 deque, RGB uint8 copy, 읽기 실패 전파, nearest는 복사본 반환 | nearest 자체는 freshness를 검사하지 않음. Capture/Evaluation 각 호출부 검사 필요 |
| close | stop event→join .5s→disconnect→join1s | thread가 실제 끝났다는 보증은 없음. blocking camera/SDK의 실물 종료 시험 필요 |

`capture_dataset.align_measured:47`는 시간 정렬된 **model 값으로 팔을 선형 보간**하고 gripper는 왼쪽 sample을 유지한다. nearest/extrapolation 및 interpolation gap의 100ms 경계·+1ns 오류를 대조했다. Capture JSON quaternion xyzw와 Episode xyz+wxyz는 각각의 계약이며 같은 배열로 간주하지 않는다.

`core.Stability`는 기본 .6s 창·최소3 samples·최대 gap .2s·팔 span <=1°·gripper span <=2 percentage points를 검사한다. tip spread는 별도 진단이며 추가 gate가 아니다. `assess_pair`/`prepare_snapshot`은 host age <=200ms, camera/joint skew·read interval/spread <=100ms와 안정 창 coverage를 사용한다. pair의 arm error <=.035rad, gripper <=2points 경계를 확인했다. 이미지 RGB/원 해상도·measured history 검증 등 실제 저장 전 검사도 유지한다.

`eligible_for_calibration=true`는 기존 소프트웨어 pairing heuristic이며 hardware_synchronized=false다. active profile은 REVIEWED_MANUAL/physical_verified=false, v8은 runtime READY와 Builder UNVALIDATED·PROVISIONAL_TASK_PHYSICS를 함께 가진다. 이번 수치 검증으로 어느 상태도 승격하지 않았다.

## 7. 실제 실패 경로와 새 계약의 비교

| 항목 | 확인된 기존 동작 | 새 계약에서 유지/남길 경계 |
|---|---|---|
| raw/native mismatch·nonfinite·model/mapping hash mismatch | 거부 또는 no-new-goal, 실패 관측을 0으로 바꾸지 않음 | 동일 의미 보존; DEVICE_ERROR/CAL 오류와 입력 field 식별 |
| Stop / UI heartbeat | runtime.run:924: heartbeat 부재/age>3s, loop gap>.75s에서 stop | 협력 중단은 loop가 돌아야 처리됨. 즉시 모터 비상정지/최대 latency 보장 아님 |
| Leader.connect calibration mismatch | bus 연결 후 예외, 메서드 안의 close 이전에 빠져나올 수 있음 | owner cleanup 필요. fake로 로컬 누락 확인; 일반 공식 connect로 바꾸며 자동 보정하지 않음 |
| Precision.close 예외 | Calibration.close의 device 순회·Runtime.disconnect_hardware의 precision.close에서 나머지 정리가 중단될 수 있음 | 종료 완료/모두 해제 성공으로 표시 금지. RO02에서 정리 범위·실패 효과 검증 필요 |
| SDK configure 예외 | torque_disabled context의 finally가 enable_torque 호출 | fake 공식 코드로 확인. `configure 실패=토크 꺼짐` 보장 불가, 부분 적용/unknown 상태와 후속 cleanup 필요 |
| SDK disconnect 토크 해제 실패 | disable_torque가 raise하면 closePort 전 종료 가능 | 포트/토크 모두 해제됐다고 추측 금지. physical readback·재접속/중지 전략 미검증 |
| Real send 뒤 Sim 오류 / SDK timeout | 실제 send가 이미 발생했을 수 있음 | unknown/applied 효과를 보존, 자동 전송 재시도·rollback 완료 주장 금지 |
| UI 종료 | ui.py:470은 real/calibration에 disconnect, sim backend에는 stop을 보내는 분기가 있음; cancel_connect는 지연 연결 요청 제거 | Qt/프로세스 전체 종료 시험 미실행. Real/Sim 소유 장치를 모두 해제하는지 RO02/U03에서 확인. 창 닫기=항상 torque release로 쓰지 않음 |

이 표는 기존 구조/예외 처리의 제약을 복사하라는 요구가 아니다. 수치·명령·관측·Stop 의미는 보존하고 기존 설계의 명시적 자원 소유·오류 effect 계약에 맞춰 검증한다. **새 구현에서 수정하거나 정상 종료를 보장했다고 보고하지 않는다.** 외부 동작 의미를 바꿔야 하는 결정은 관련 구현 전에 차이·영향을 별도로 보고한다.

## 8. 새 파일 책임과 후속 검증 관문

| 기존 재사용 범위 | 이미 설계된 새 책임 | 구현 전에 확보한 근거 / 아직 남은 것 |
|---|---|---|
| precision.py raw/native/model·fit/review/validation·identity | robot/calibration.py, Scene 계약의 보정 선언 | 이번 계산/프로필 근거 확보. RO01의 새 구현·변환 fixture 회귀 필요 |
| hardware.py + 공식 LeRobot motor/camera API | robot/devices.py | 모의 수명·SDK 소스 확인. RO02의 모든 예외/중복 close·worker/실물 시험 필요 |
| runtime.command_target/start/stop·feedback 진단 | robot/control.py | 공간·양자화·적용 순서 확인. Sim/Real 실제 상호작용은 P02/장치 시험 필요 |
| CameraReader·Stability·prepare_snapshot | robot/capture.py | 저장 Metadata/host-time 근거 확보. 실물 동기/촬영/렌더 비교는 RO03/E01/E02 필요 |
| Builder camera/robot 정합·baked Asset 생성 | 기존 Builder calibration/export + 엔진 state | 기존 곱 순서·pose/identity 보존. BU02/BU03의 actual export·이동·엔진 회귀 필요 |
| 공식 Policy+processor→장치 | learning/policy.py + robot/evaluation.py | ROBOT-02 의미 확보. P03 실물 시험 및 공식 Policy action 실제 증거 필요 |

CAL-01은 **대표 오프라인 근거 확보**, CAL-02/ROBOT-01/02는 **코드·대표 mock/수치 근거 확보, 실물/해당 엔진 실행 OPEN**이다. 관련 순수 계산·mock 구현을 시작할 정보는 확보했지만 AC01/02의 새 구현 회귀나 AC03의 실물 완료를 뜻하지 않는다. 새 장치 signature·오류·소유권은 [Interface](interfaces.md#11-b03에서-확인한-장치calibration-경계)와 [장치 SPEC](../SPEC-robot-operations.md)에 연결했다.

실제 장치가 필요한 항목: 현재 장치 register/파일 동일성, 모터 방향·각도/held-out 정합·gravity 상태·토크 readback, 연결 실패/케이블 단절/SDK timeout·중복 종료 후 포트 소유, camera exposure/buffer/실해상도·안정 창, UI/프로세스 상실 때 실제 중지 지연, 공식 ACT·SmolVLA의 실물 action/processor·실행 결과다. 이번에는 어느 장치도 연결하지 않아 모두 미완료다.

## 9. 보존·범위 확인

[보존 대조](evidence/b03/preservation-after.json)는 기존 폴더 56,100개 파일의 stat와 선택된 코드/설치 Metadata·SDK 소스·B01/B02 증거/보고서 등 14,848개 SHA, 이번 조사 입력 79개 SHA를 비교한다. 전체 대용량 corpus 또는 SDK binary의 작업 전후 byte 검증은 아니다. B01/B02의 보고서·증거와 원본 활성 포인터·모델·환경을 변경하지 않았다.

B01 Isaac DataGen의 strict IK 실패와 Isaac Evaluation 비결정성, B02의 requested 누락·기록 phase·자동 Annotation post tick→저장 frame +1 및 manual boundary 차이는 그대로 남긴다. 신규 DLS + Best Effort 구현·검증이나 다른 IK 정책의 Resume 허용을 수행하지 않았다. 새 Writer/데이터 변환·RO01 이후 제품 구현도 없다.

산출물은 B03 조사 harness·JSON·log와 관련 설계/계획 문서뿐이다. 연결된 [incremental-implementation 스킬](/home/hyeonhee/.agents/skills/incremental-implementation/SKILL.md)의 작은 검증 단위·범위 제한을 적용했다. 별도 `ental-implementation` 스킬은 가용 경로에 없어 링크된 스킬을 사용했다. 새 프로젝트가 Git 저장소가 아니므로 commit은 만들지 않았다. **B03만 완료하고 다음 작업은 자동 시작하지 않는다.**
