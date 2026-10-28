# Position Target Saturation — Isaac Annotation·DataGen 복구

2026-10-28. **최종 Position Target을 원 URDF 한계 안쪽으로 Saturation하도록 구현했고, 기존 Isaac Annotation index323 및 Random DataGen tick348 차단을 실제 엔진에서 해소했다.** 최종 코드의 Annotation은388frame·성공1 Episode, Random DataGen은399step·성공1 Episode를 Native에 저장했다. 공식 Reader/Mimic Pool/LeRobot/ACT processor 소비를 확인했다. 이전 No-Clipping 정책은 이번 사용자 결정으로 대체됐으며 과거 원본·보고서·증거는 수정하지 않았다.

## 원인과 보존한 모델

현재 실행 패키지는 기존 `scene2-final-contact-review-20261014-932c8f2e / scene-v8-native`다. Manifest는 `64bff80050a883880e7e6363dd3e5b2f517fd72bb96743e3e529c89a2dfaa3c9`, 실행 kinematic URDF는 `f78814de0d341a4a46b2d37759e9206be7d66bca8445ea6867058c43dd6cd589`다. Isaac은 기존 v8 실행 USD/Collision을 그대로 사용하며 URDF는 모델 identity·원래 rad 한계 근거다. MuJoCo 모델과 Pinocchio도 같은 승인된 실행 URDF를 사용한다. Geometry residual을 runtime q에 다시 더하지 않았다.

wrist_flex 상한이 정확한100°가 아닌 이유를 실제 원본 Git 이력으로 확인했다. **기존 decimal `1.65806rad`에 `math.radians(5)`를 더한 값**이 현재 `1.7453264625997165rad`이며 degree로는 `99.99984017946127°`다. 원본 revision `dcfff1773caa18bb5252bb68506e3277be3e0f3c`의 limit-only 변경과 당시 문서의5° 확장 기록이 근거다. 이번에는 이 값을 변경하지 않았고 현재 기계적 가동 범위가100°라고 추측하지 않았다. 원본 Git은 읽기 전용으로 조사했으며 새 Workbench는 Git 저장소를 만들거나 commit하지 않았다.

[소스/모델 identity](evidence/position-saturation/source-inventory.json), [실제 과거 limit diff](evidence/position-saturation/historical-urdf-limit.diff):

| wrist_flex 경계 | rad |
|---|---:|
| 원 float64 URDF upper |1.7453264625997165|
| 단순 float32 변환값 |1.7453265190124512|
| 단순 변환의 초과량 |5.641273470580188e-8|
| 원 한계 이하의 최대 float32 |**1.7453263998031616**|

과거 Source에 이미 저장된 값은 위의 float32 upper이므로 이 요청을 안쪽 값으로 바꾸는 차이는 **1.1920928955078125e-7rad, 1 ULP**다. DLS의 float64 upper에서 안쪽 float32로 가는 차이는 **6.279655484497937e-8rad**다. 요청값·반올림 초과량·최종 Saturation 변경량을 같은 수치로 보고하지 않는다.

## 수식과 구현 경계

기존 [robot/control.py](../robot_learning_workbench/src/robot_learning_workbench/robot/control.py)의 `checked_target`를 재사용했다. 각 관절의 승인된 원 한계를 `[L,U]`, 적용 dtype을 `d`라 하면:

```text
L_d = cast_d(L)
if float64(L_d) < L: L_d = nextafter_d(L_d, +inf)
U_d = cast_d(U)
if float64(U_d) > U: U_d = nextafter_d(U_d, -inf)
payload = cast_d(min(max(requested, float64(L_d)), float64(U_d)))
```

그 뒤 payload의 finite와 **원래 float64 L≤payload≤U**를 다시 검사한다. 구간 안에 표현 가능한 값이 없으면 거부한다. 범위 안 요청은 정상 dtype 변환 이외에 바꾸지 않는다. 큰 유한 초과도 제한하지만 NaN/Inf·문자열/bool/complex·잘못된 shape/order/unit은 유효 명령으로 바꾸지 않는다. URDF/모터 한계를 늘리거나 epsilon을 비교 조건에 추가하지 않는다.

개념은 공식 [ROS2 joint_saturation_limiter의 position min/max 제한](https://raw.githubusercontent.com/ros-controls/ros2_control/master/joint_limits/src/joint_saturation_limiter.cpp)과 같다. ROS Controller 전체를 복제하거나 velocity/acceleration/braking 정책·ROS 의존성을 추가한 것은 아니다. dtype 경계 계산은 설치 NumPy1.26과 [공식 nextafter API](https://numpy.org/doc/1.26/reference/generated/numpy.nextafter.html)를 사용한다.

| 경로 | 실제 변경 / 유지 |
|---|---|
| Teleop | 기존 Calibration/URDF/선택 engine/승인 motor 범위의 교집합으로 Saturation한 뒤 기존 Precision inverse와 SDK 정수 encoding을 계산. encoded q를 다시 검사. **순수/fake SDK 시험만 수행, 실물 전송 없음** |
| Source | Leader model-rad 요청과 실제 payload 분리. 기존 canonical gripper 범위도 교집합으로 유지. 유한 범위 초과로 Episode를 중단하지 않으며 invalid mapping/보정/NaN/Inf는 기존 실패·정리 경로 |
| Annotation | 원 Source 파일·initial state·명령은 읽기 전용. 재생용 payload만 Saturation. 기록된 원 Cartesian goal/수동 boundary와 Task 수식을 재계산하지 않음 |
| DataGen | Mimic·Pinocchio DLS·Best Effort candidate 계산/진단 유지. 별도 candidate validity/limit/jump 실패를 Saturation으로 살리지 않음. 유효 candidate의 native payload에 Saturation을 적용하고 **직전 실제 적용 arm target 대비0.5rad guard**를 다시 검사 |
| Evaluation | 공식 processor/postprocessor의 원 Action을 별도로 남기고 실제 Position Target을 Saturation. Placement 성공 조건·관측/Task phase 유지. malformed/nonfinite Policy 출력은 여전히 명시 실패 |

Isaac 공식 JointPositionAction은 기존 `scale=1`, `use_default_offset=False`, 관절 순서 보존 설정으로 실제 Articulation position target에 전달한다. MuJoCo는 기존 model의6개 position actuator `data.ctrl`에 적용한다. 양 엔진의 기존 Step/Reset·Camera/Contact·Native 수명 구조를 통합하거나 새 Command Manager를 만들지 않았다. DLS 반복 내부 projection은 그대로다. Saturation은 Position Target의 계약이며 실제 측정 q를 한계 안으로 덮어쓰거나 물리 상태/실물 안전성을 보장하는 처리가 아니다.

## Native와 학습 Action

새 결과는 다음 필드를 같은 control row에 기록한다.

| 필드 | 의미 |
|---|---|
| `joint_targets` | **실제 적용 목표**, 모델 절대관절 rad6. 새 학습 Action의 출처 |
| `commands/requested_joint_rad` | 원 Source 요청/solver float64 command/공식 postprocessor 원 Action. 원래 값과 dtype 보존 |
| `commands/applied_joint_rad` | 실제 payload. Isaac float32, MuJoCo float64 |
| `commands/saturation_mask` | bool6, 안쪽 표현 가능 구간으로 제한한 관절 |
| `commands/saturation_delta_rad` | float64 `applied-requested`. 일반 dtype 반올림도 수치로 남으므로 mask와 함께 해석 |
| 기존 `ik/*`, `states/*`, Task/접촉 | solver 진단과 post-step 실측/판정. Applied 또는 pre-step observation으로 혼동하지 않음 |

행별 mask/delta에서 작은 Episode/attempt summary의 횟수·관절별 count·최대 **masked** 변경량을 계산한다. 원 bulk 배열/영상을 JSON으로 복제하지 않는다. 통계 집계만 실패하면 `status=unavailable`을 명시하고 영상/Native 자원 정리를 계속한다. 실제 기록 실패·물리 적용 불명 오류를 정상 적용으로 바꾸는 fallback은 없다.

새 recording은 `position_target_policy=saturation_inward_v1`, `joint_targets_role=applied`를 선언한다. 공식 LeRobot control contract에도 `command_processing={position_target_policy: saturation_inward_v1, training_target: applied}`를 보존한다. 기존 `data/lerobot.py`의 materialize/merge와 공식 processor를 사용하며 중간 포맷/Trainer를 추가하지 않았다.

**과거 Dataset의 joint_targets를 새 Applied라고 재명명하지 않는다.** 이전 requested-target 계약과 새 applied-target 계약의 자동 Merge를 거부하고, 정책이 다른 Native Resume도 기존 identity 검사로 차단한다. 기존 Native/LeRobot/checkpoint는 그대로다. 같은 새 계약의 Isaac/MuJoCo Dataset은 공식 형식으로 Merge했다. dtype 승격·공식 학습 float32 변환 경계는 기존 L03과 같다.

Parquet/raw HF 값은 원 Native 적용값과 exact, 공식 Dataset/torch 학습 item은 float32다. 따라서 MuJoCo float64 target은 학습 소비에서 약1e-8rad 수준 표현 차이가 남을 수 있다. Isaac 적용 payload는 이미 float32이므로 해당 변환에서 exact다. 과거 LeRobot 학습 정밀도 경계를 숨기거나 원 Dataset을 고치지 않았다. ACT normalizer/postprocessor의 작은 roundtrip 오차도 최종 엔진 Saturation·한계 재검사를 거치며 실물 승인으로 해석하지 않는다.

## 실제 엔진 복구와 회귀

실제 설치 환경은 Python3.11.15 / NumPy1.26.0 / MuJoCo3.3.7 / Isaac Sim5.1·Lab2.3.0 / Pinocchio2.7.0 / LeRobot0.4.1이다. SDK 설치·업그레이드·소스 패치·실물 장치 연결은 없다. 실제 Qt→production R03 Worker를 사용했으며 runner·물리·센서·Task를 fake로 대체하지 않았다. Isaac에는 기존 Fabric/렌더·종료 warning 및 보호 audit가 차단한 SDK cache 쓰기 예외가 남을 수 있으며 warning-free 실행으로 보고하지 않는다. 실제 Step/정상 terminal·보존 대조와 구분한다. offscreen 파일 선택 자동화와 읽기 전용 audit는 기존 시험 방식을 재사용했다.

| 최종 검증 경로 | 실제 결과 | Saturation |
|---|---|---|
| **Isaac Annotation release** | **388frame·성공1 Episode**. index323 이후를 실제 재생했고 최초 StableGrasp **post221→저장222**, 최종 물리 gate 통과 | wrist_flex index323~336의14step, 최대1.1920928955078125e-7rad |
| **Isaac Random DataGen release** | **399step·성공1 Episode**, latched StableGrasp AND Placement. 원래 tick348 차단을 넘어 완료·Native 저장 | wrist_flex tick348~351의4step, 최대6.279655484497937e-8rad |
| MuJoCo Auto Annotation |388frame·성공1, post222→저장223 유지 |0|
| MuJoCo Fixed DataGen |399step·성공1. 정상 범위6개 배열 경로 dtype/shape/값이 기존 Baseline과 exact |0|
| MuJoCo Random DataGen |399step·성공1. 새 entropy pose의 실제 Step/Task·Native 결과 |0|
| MuJoCo Source 수치 입력 probe |실제3step·Native1 Episode, `recording_only`. wrist 요청100rad→승인 상한1.7453264625997165rad; 실제 장치 없음 |3step|
| ACT Evaluation 양 엔진 |엔진별60step·정상 완료 실패1, Placement 성공0. 기존4-step smoke checkpoint 그대로 사용 |이번 실제 Policy 출력은0, Task 실패와 구분|

최종 Isaac release는 각각 worker 전체115.007s/121.665s다. AppLauncher/준비/렌더/기록/종료를 포함하며 wall-clock30FPS나 성능 개선으로 해석하지 않는다. 개발 초기 recovery도 별도 output에 Annotation1/DataGen1 성공을 보존했다. **표는 release 결과이고 초기 실행을 합치거나 같은 Episode를 중복 계수하지 않았다.**

실제 release Native에서 모든 적용 target이 원 URDF limits 안임을 확인했다. index323과 tick348의 requested/applied/mask/delta 실제 행은 [consumer-results.json](evidence/position-saturation/consumer-results.json)에 있다. DataGen의 실제 previous-applied arm jump 전체가0.5rad 이하이며 비수렴 candidate는 기존 Best Effort 진단 그대로다. Saturation 때문에 IK를 수렴으로 재분류하지 않았다.

Isaac Annotation의 **전체 pre-step grasp latch 배열도 역사적 Annotation과 exact**다. 하지만 Saturation된 관절 명령과 그 이후 물리 궤적까지 원 Source와 exact라고 주장하지 않는다. E01 cube–cup1.197188790mm 잔차를 이번에 해결/재측정한 것도 아니다.

## 공식 소비자와 데이터 무결성

- [공식 Reader/숫자/영상](evidence/position-saturation/consumer-results.json): HDF5 Reader 재로드, Requested 원 Source 대조, Applied=`joint_targets`, delta 식·mask·한계 및 pre[t+1]=post[t] 검사. 각 camera640×480·30FPS·frame count·전체 PTS, 실제 RGB decode 확인.
- [추가 실제 결과](evidence/position-saturation/additional-consumer-results.json): MuJoCo Random·양 엔진 Evaluation의 공식 Reader와 Task outcome/명령 field 확인. 실제 Policy와 결함 주입100rad fixture를 구분한다.
- 설치 공식 Mimic Pool이 새 Isaac Annotation을 직접 소비했다. subtask boundary는 `[0,223)/[223,388)`이며 저장 first222에 공식 Pool의+1 half-open 경계를 적용한 것이다. 물리 post221과 혼동하지 않는다. CPU Pool의 gripper callback fixture는 기존 방식이고 전체 공식 Isaac DataGenerator 실행 완료를 뜻하지 않는다.
- 새 양 엔진 DataGen을 각각 공식 LeRobotDataset으로 만들고 같은 새 계약의 Merge2 Episode/798frame을 소비했다. 실제 `__getitem__`·DataLoader에서 state/action6축·Side/Wrist RGB를 읽었다. 영상은 원 MP4 hardlink로 공유하며 재인코딩/해상도 저하가 없다.
- [공식 ACT 소비자](evidence/position-saturation/act-consumer-results.json): 실제 Dataset factory·chunk10·DataLoader·공식 normalization/postprocessor를 사용해 tick348 주변을 포함한7개 frame을 검사했다. Action은 실제 payload이며 IK/post-step 진단이 학습 feature에 포함되지 않는다. 전체 Training을 추가하거나 작업 성공률/일반화 성능을 주장하지 않았다.
- Curation은 기존 함수로 Applied·Requested·delta의 rad/command phase 통계를 구분한다. 변경된 계약의 Merge/Resume 거부, finite/order/unit·shape 오류, 상·하한·작은 overshoot·큰 finite 요청·표현 가능 값 없는 구간을 시험했다.

## 테스트·리뷰·보존

최종 전체 **946 passed, skipped0 = 이전926 + 신규20**. 기존 torchvision warning2개는 남아 있다. [JUnit](evidence/position-saturation/unit-tests-release.xml), [전체 로그](evidence/position-saturation/logs/33-full-suite-release.log), [wheel](evidence/position-saturation/build-workbench.json). Workbench wheel source/config bytes·compile·isolated import/실제 invalid-config worker smoke를 확인했으며 환경에 설치하지 않았다. 설정된 별도 lint/type 도구는 없어 실행했다고 주장하지 않는다.

과거 No-Clipping 기대의 테스트는 새 승인 정책에 맞춰 바꾸고 작업 전 사본을 보존했다. NaN/Inf/order/unit·Calibration·IK invalid/jump·Task/물리·Native 저장 안전성 시험은 유지했다. 초기 실패는 기존14개의 strict 거부 기대가 정책과 달라진 결과, 소비자 harness의 HF torch float32를 raw float64로 잘못 비교한 문제, summary 집계 오류 시 cleanup이 건너뛰어질 수 있는 문제를 구분한다. dtype 비교 harness는 raw format과 학습 format을 분리했고 실제 원 수치를 고치지 않았다.

독립 [Spec](evidence/position-saturation/spec-review.md) / [Standards](evidence/position-saturation/standards-review.md) 리뷰를 수행했다. Spec의 추가 High/Medium0, Standards의 summary-error cleanup Medium1은 실제 fault RED→GREEN으로 수정하고 재검토를 통과했다. 단순화는 기존 `checked_target`·record_frame·공식 materialization을 재사용하고 중복 최종 범위 검사 경로를 한 수학으로 연결한 범위다. 새로운 Control Manager·설정 모드·Dataset/Trainer/Adapter 계층은 없다.

[보존 대조](evidence/position-saturation/preservation-after.json)는 원본56,100개 stat·선택 SHA 및 이전 제품/시험 Python 사본을 비교했다. 미승인 변경0, Scene 전체 Manifest 검증 통과다. 이전 B/UI/Native/학습 산출물과 SDK는 그대로다. 전체 corpus/SDK binary를 전수 byte hash했다는 뜻은 아니다. 명령·입력·코드 identity와 범위는 [commands.json](evidence/position-saturation/commands.json), [최종 검증](evidence/position-saturation/verification.json)에 있다.

## 남은 범위

**float32 표현 차이 때문에 Isaac Annotation/DataGen 전체를 막던 관문은 해소했다.** 향후 새 실행은 Saturation 계약으로 수행하고, 과거 strict 계약의 출력을 같은 의미로 Resume/덮어쓰지 않는다.

실물 Follower command binding·motor-range 승인/안전성, 같은 Isaac 앱 복수 Reset/Annotation·다중 env/장시간, E01 물체 잔차, SmolVLA padding, v9/실측 Calibration은 그대로 OPEN이다. 포화된 Position Target이 항상 작업 성공·물리 상태 한계 준수·실물 안전을 보장하지 않는다. 이번 실제 성공 Episode는 작은 표본이며 전체 성공률 추정이 아니다. 이번 구현/복구에서 중단하며 후속 기능을 자동 시작하지 않는다.
