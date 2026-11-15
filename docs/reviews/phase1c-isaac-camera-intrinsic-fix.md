# Phase 1C — Isaac Camera Intrinsic 정합

2026-11-15. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `97c029e195ab8587603fb3f240f2c1a6c0f91f52`. [감사 BUG-005](full-codebase-audit.md), [Phase 1A](phase1a-regression-fix.md), [Phase 1B](phase1b-fitting-refit-fix.md)의 실제 미커밋 Working Tree에서 시작했다.

**COMPLETED — BUG-005의 정확한 K 설정·native USD Schema·Runtime readback·Consumer와 기존 회귀를 검증했다. 최종 전체 1,984 passed / 실패0·오류0·skip0, 실제 exit0이다. 기존 1,963개 누락0·신규21개이며 보호 파일19,612개 변경·누락·신규0을 확인했다. 실제 Kit/RTX Sensor 렌더는 NOT_TESTED다.** 아래 CPU 결과를 실제 Isaac 영상의 픽셀 정확도 검증으로 해석하지 않는다.

원시 자료는 저장소 밖 `/tmp/real2sim-phase1c-20261115-hjk25tqo/`에 있다. 이 폴더가 삭제되면 로그를 재열람할 수 없으며 제품은 해당 경로에 의존하지 않는다. 사용자 Scene 대신 기존 불변 시험 Package를 읽고 메모리에서 Camera K/해상도만 바꾼 합성 입력을 사용했다. 설치·다운로드·실물 제어·재구성 모델 추론·온라인 AI·Commit/Push/Merge는 하지 않았다.

## 1. 원인과 변경 전 재현

Scene/Manifest의 K와 해상도는 `execution_inputs → scene_execution_inputs → profile.cameras`까지 보존됐다. 손실은 `build_env_cfg`가 `f=(fx+fy)/2`로 줄이고 aperture offset을 생략한 부분에서 발생했다. 설치된 Lab의 기존 readback도 `fy=fx, cx=W/2, cy=H/2`를 강제하므로 spawn 설정만 고쳐서는 충분하지 않다.

640×480 입력에 대한 실제 RED 비교:

| 위치 | fx | fy | cx | cy |
|---|---:|---:|---:|---:|
| Scene / execution input | 600 | 800 | 300 | 210 |
| 변경 전 Workbench 설정에서 복원 | 700 | 700 | 320 | 240 |
| 차이, 설정−Scene | +100 | −100 | +20 | +30 |
| 변경 후 설정에서 복원 | 600 | 800 | 300 | 210 |
| 변경 후 실제 CPU USD Lens Schema readback | 600 | 800 | 300 | 210 |
| 변경 후 제품 Runtime hook의 CPU K buffer | 600 | 800 | 300 | 210 |

마지막 행은 Kit 생명주기를 대체한 시험용 Camera base + 실제 제품 `RuntimeCamera` hook + 실제 USD Camera + CPU Tensor 결과다. **실행 중인 GPU Sensor의 관측값은 아니다.**

## 2. 실제 설치와 지원 API

| 조사 대상 | 확인한 실제 상태와 제약 |
|---|---|
| Interpreter | 기존 `lerobot-arena`, Python 3.11.15 / Torch 2.7.0+cu128 / NumPy 1.26.0 / SciPy 1.15.3 |
| Isaac Lab | 소스 `v2.3.0`, Commit `3c6e67bb5c7ada942a6d1884ab69338f57596f77`; 배포 메타데이터의 `isaaclab=0.47.2`와 구분 |
| Isaac Sim | 배포 `5.1.0.0` |
| `PinholeCameraCfg.from_intrinsic_matrix` | 설치된 `utils/sensors.py:convert_camera_intrinsics_to_usd`를 호출. fx/fy 평균·offset 0으로 축약하므로 정확한 K용으로 사용할 수 없음 |
| Lab `Camera.set_intrinsic_matrices(matrices, focal_length=None, env_ids=None)` | 같은 손실성 converter를 사용. 인자 계약은 유지하되 기존 Workbench subclass에서 정확한 적용으로 override |
| Lab `_update_intrinsic_matrices` | horizontal aperture만 읽어 정방 픽셀·중심 주점으로 재구성. 기존 subclass에서 native Schema readback으로 override |
| Lab `_initialize_impl` | Sensor prim·buffer를 만든 뒤 `_update_intrinsic_matrices(_ALL_INDICES)`를 호출. 이 hook에서 각 Camera의 원 K를 적용 |
| Sim `Camera.set_opencv_pinhole_properties(cx, cy, fx, fy, pinhole)` | 설치 소스에서 native Schema 적용·속성 이름·12개 계수·`imageSize` 설정을 확인 |
| native USD Schema | 설치된 `OmniLensDistortionOpenCvPinholeAPI` resource plugin으로 CPU USD Stage에서 실제 Apply/Set/Get 성공 |

SDK 메서드는 기존 Camera Prim에 `OmniLensDistortionOpenCvPinholeAPI`를 적용하고 `omni:lensdistortion:opencvPinhole:{fx,fy,cx,cy,imageSize}`를 쓴다. 이 동작을 기존 Lab Sensor의 Runtime Session Layer에서 사용했다. 별도 SDK Camera 생성자는 SyntheticData/Graph 등을 획득하고 aperture도 조정하므로, 두 번째 Sensor나 Render Product를 만들지 않았다. [Isaac Sim 5.1 Camera API](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/py/source/extensions/isaacsim.sensors.camera/docs/index.html#isaacsim.sensors.camera.Camera.set_opencv_pinhole_properties), [공식 OpenCV Pinhole 예제](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/sensors/isaacsim_sensors_camera.html)

해당 Lens Schema의 projection은 자체 fx/fy/cx/cy/imageSize를 사용한다. physical focal/aperture만 설정하는 것으로 이 경계의 정확성을 대신하지 않았다. `imageSize`는 CameraCfg의 실제 `(W,H)`와 같게 설정해 암묵적 해상도 재스케일을 피한다. 기존 f_stop=0은 유지했다. [Omniverse Lens Schema와 해상도 계약](https://docs.omniverse.nvidia.com/materials-and-rendering/latest/cameras.html)

설치된 SDK 8개 소스/Schema 파일의 SHA와 API 위치는 `installed-api-sources.json`에 있다. CPU 시험은 설치된 resource plugin을 `Plug.Registry`에 첫 Stage 생성 전 등록한 뒤 실제 Schema를 사용했다. 이 결과가 Kit의 extension 초기화 성공을 증명하지는 않는다. SDK 파일은 수정하지 않았다. API/Schema를 사용할 수 없으면 `NOT_SUPPORTED`가 포함된 `NotImplementedError`로 중단한다. 평균 K나 요청 K만 채운 buffer로 조용히 대체하지 않는다.

## 3. 수학·단위·좌표계

지원 범위는 기존 **왜곡 없는 zero-skew pinhole**이다. Scene에 저장한 K·실측·Camera Pose를 수정하지 않는다.

```text
K = [[fx, 0, cx], [0, fy, cy], [0, 0, 1]]
u = fx * X/Z + cx
v = fy * Y/Z + cy
```

ROS Optical의 +Z forward / +X right / +Y down, 기존 좌상단 이미지 좌표와 `(width,height)` 순서를 유지한다. half-pixel 보정을 새로 더하지 않았다. 기존 중심 주점 입력은 계속 `(W/2,H/2)`다.

필수 K와 실제 CPU Schema readback K로 계산한 예시는 다음과 같다(`projection-comparison.json`). 아래는 렌더된 feature의 관측 좌표가 아니다.

| Optical XYZ | Scene의 (u,v) | 변경 전 설정의 (u,v) | native Schema K의 (u,v) |
|---|---|---|---|
| (0,0,1) | (300,210) | (320,240) | (300,210) |
| (0.1,−0.1,2) | (330,170) | (355,205) | (330,170) |
| (0.5,0.2,4) | (375,250) | (407.5,275) | (375,250) |

Builder USD exporter/IsaacRenderer가 사용하는 physical parameter 수학과도 비교했다. 기존 F=24를 유지하고 다음과 같이 독립 focal/aperture/offset을 설정한다.

```text
horizontal_aperture = F*W/fx
vertical_aperture = F*H/fy
horizontal_aperture_offset = F*(W/2-cx)/fx
vertical_aperture_offset = F*(cy-H/2)/fy
```

F와 aperture/offset은 같은 USD Camera 단위로 취급하므로 비율에서 단위가 상쇄된다. 설치된 Lab docstring의 cm/mm 표기가 혼재한 것을 근거로 새 물리 센서 크기나 렌즈 보정을 만들지 않았다. 실제 투영은 pixel 단위의 native Lens Schema가 담당한다.

기존 Builder의 `isaac_render.py:update_scene`와 `exporters/usd.py`는 이미 이 physical 수학을 가진다. 다만 Builder에는 Lab Sensor의 buffer/초기화 경계가 없어 해당 Renderer를 Workbench에 끌어오지 않았다. Builder 함수·MuJoCo 수학은 불변이다. Builder physical 속성 비교만으로 그 경로의 실제 RTX 정확도를 새로 인증하지 않는다.

시험은 optical point 4개 이상에 대해 Scene K와 설정 복원 K의 projection을 비교한다. float64 설정 비교의 상대 오차는 몇 차례 곱셈/나눗셈에 해당하는 `8*eps`/`16*eps`를 사용한다. 소수 K 시험은 실제 native Schema의 float32 저장값을 읽어 다음 양자화 오차와 float64 Pose round-trip 산술 오차만 허용한다.

```text
|Δu| <= |X/Z|*|Δfx| + |Δcx| + arithmetic_bound
|Δv| <= |Y/Z|*|Δfy| + |Δcy| + arithmetic_bound
ΔK = float32(K) - K
arithmetic_bound = 64*eps_float64*max(1, |projected_pixel|)
```

이는 합성 점/유한한 해당 Pose 계산의 수치 오차 예산이다. 임의의 실제 Sensor 픽셀 허용치나 보정 정확도 기준이 아니다. GPU rasterization, 영상 feature 위치, lens shader의 픽셀 중심 구현은 이번에 측정하지 않았다.

## 4. Runtime 적용·갱신·입력 거부

1. `build_env_cfg`가 K의 3×3 numeric/finite/양수 fx·fy/zero-skew/동차행과 양의 정수 해상도를 **Isaac import·파생 Asset 생성 전** 검사한다. USD float32에서 표현할 수 없는 focal/속성도 거부한다. 기존 general Scene 경로의 nonzero distortion 거부는 그대로다.
2. 기존 CameraCfg의 class_type인 `RuntimeCamera`를 확장한다. Scene의 K를 factory 안에서 별도 소유 배열로 보존한다. Side/Wrist의 독립 K/해상도를 공유값으로 덮어쓰지 않는다.
3. InteractiveScene의 `{ENV_REGEX_NS}` 확장 이후에도 유지되는 고유 `Camera_<view>` 이름으로 초기 K를 찾는다. Runtime 재초기화에서는 초기 적용 상태를 다시 준비한다.
4. 초기 Lab hook에서 실제 각 환경의 기존 Camera Prim에 native Schema와 12개 zero distortion 계수를 적용한다. 참조된 Package/Calibration 파일 대신 Runtime Session Layer에만 author한다.
5. 이후 K 갱신은 native 속성·imageSize·zero distortion을 읽고 검증한 후 기존 `data.intrinsic_matrices`에 저장한다. Scene의 요청 K만 복사해 투영 변경을 가장하지 않는다.
6. `set_intrinsic_matrices`의 기존 인자 이름과 batch/선택 env 계약을 유지한다. 유효하지 않은 batch·NaN·음수 focal·범위 밖/중복 env ID는 전체 입력을 먼저 검사하고 write를 시작하지 않는다. 선택 env만 갱신하고 다른 env/Camera/원 Scene은 보존한다. `focal_length=None`일 때 cfg의 기존 physical focal을 유지하며 native pixel K는 그대로 적용한다.

`_update_poses`의 기존 Robot rigid-body view → mount offset → ROS orientation 계산은 AST가 시작과 같다. Camera-to-Parent Pose, `OffsetCfg(convention='ros')`, Robot Base·FK·Wrist Mount 수학과 data schema를 바꾸지 않았다. malformed K를 정상 Calibration으로 표시하거나 왜곡을 임의로 보정하지 않는다.

## 5. Caller와 Producer → Consumer

| 기존 Caller | Camera 생성/소비 | 이번 확인 |
|---|---|---|
| Isaac `source.py`의 단일/다중 환경 실행 두 경로 | 공통 `build_env_cfg`, `state.read_sample` | 두 호출과 Source 계약 유지, 기존 workflow 회귀 |
| `annotation.py` | 같은 factory와 `state.read_sample` | Camera/ROS K 전달 경로 유지, 기존 replay 회귀 |
| `datagen.py` Mimic/DataGen | 같은 factory, 기존 annotation/source state 경계 | 별도 축약 converter 없음, 기존 DataGen 회귀 |
| `evaluation.py` Simulation Evaluation | 같은 factory | 기존 실행/정책/Camera 계약 회귀 |
| `robot/scene_render.py:NativeRenderer` Isaac branch | 같은 factory와 Sensor data | 실제 K와 RGB grid를 metadata로 보존하는 통합 시험 |

새 통합 시험은 **제품 `build_env_cfg → RuntimeCamera hook → 실제 CPU USD Schema → K Tensor → state.read_sample`**를 실행했다. 독립 Side640×480/Wrist400×300의 K/RGB grid/ROS quaternion을 확인했다. Physics state와 Isaac SDK config/base/lifecycle만 test double이고 read_sample 자체를 mock하지 않았다. 실제 Source 파일 생성이나 정책 rollout 전체를 실행한 것은 아니다.

같은 Sensor로 실제 `NativeRenderer.render`의 Isaac 분기도 검사했다. 여기서 Wrist RGB400×300에도 `resolution=[640,480]`을 기록하던 관련 grid 불일치를 RED로 확인했다. **Isaac 분기의 이 한 줄만** 실제 RGB width/height로 변경했다. K/Pose/영상은 기존 Sensor data를 그대로 사용한다. 시험의 physics advance/render 호출은 test double이며 실제 PhysX/RTX 실행이 아니다. MuJoCo 분기는 변경하지 않았다.

## 6. RED → GREEN

| 실행 | 실제 결과 / Exit | 의미 |
|---|---|---|
| 변경 전 관련 baseline | 133 passed, 101.97s / 0 | 기존 Isaac + Phase 1A/1B 계약 |
| 최초 K 재현 최종 RED | 10 failed / 1 passed, 2.51s / 1 | 평균·중앙 주점 손실 및 입력 거부 부재 |
| 첫 설정 수정 | 22 passed, 24.58s / 0 | 설정 수학/입력 + 기존 Isaac Engine |
| Runtime 추가 RED | 6 failed / 7 passed / 4 deselected, 3.63s / 1 | 설정만으로는 native Schema·readback·setter가 완성되지 않음 |
| Runtime 연결 GREEN | 17 passed, 4.06s / 0 | 실제 USD native 속성과 제품 hook의 K buffer |
| Consumer/미지원 API RED | 2 failed / 19 passed, 4.94s / 1 | 400×300 metadata 오류, 미등록 Schema의 실제 `Tf.ErrorException` 처리 누락 |
| 위 두 결함 수정 GREEN | 32 passed, 27.10s / 0 | 새 Camera 21개 + 기존 Engine11개 |
| 제품 수정 집중 회귀 | **154 passed, 100.43s / 0** | 새 Camera21개 + baseline133개, Phase 1A/1B 포함 |

반복 묶음은 서로 겹치므로 합산하지 않는다. 새 시험 21개는 centered square/anisotropic/offcenter, 독립 K/해상도/ROS offset, invalid K, native schema, 다중 env 부분 setter·실제 focal 지정, 갱신 유지, float32 projection, 미지원 API 실패, 두 Consumer를 검사한다. 기존 시험은 수정·삭제·rename·skip·xfail하지 않았다.

## 7. 전체 회귀

아래 기존 wrapper의 복사본에서 HF/XDG cache 출력만 이번 `/tmp`로 바꿨다. 저장소의 실행 스크립트와 기존 환경은 수정하지 않았다. 기존 Python/Qt/USD/Blender 경계를 재사용한다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash /tmp/real2sim-phase1c-20261115-hjk25tqo/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short \
  --basetemp=/tmp/real2sim-phase1c-20261115-hjk25tqo/release-full-verified-temp \
  --junitxml=/tmp/real2sim-phase1c-20261115-hjk25tqo/release-full-verified.xml
```

첫 전체 실행 `release-full.xml/log`는 **1,972 passed / 12 failed**, 오류/skip0, Console **628.87s**, 실제 **exit1**이었다. Phase 1B testcase Counter를 대조해 **기존 1,963개 모두 존재·통과**하고, 실패12개가 새 Camera 시험에만 있음을 확인했다(`first-regression-comparison.json`). 성공한 전체 실행처럼 기록하지 않았다.

원인은 Kit 없는 시험의 Schema 등록 시점이었다. 앞선 시험에서 첫 USD Stage를 만들면 SchemaRegistry가 캐시되는데, 새 Camera fixture는 그 뒤 Lens plugin을 등록했다. 독립 실제 USD 프로세스에서 같은 순서를 실행해 등록된 plugin1개에도 `CanApplyAPI`가 미등록 Schema 오류를 내는 것을 재현했다(`late_schema_probe.json/log`). 신규 시험 파일의 등록 시점만 collection으로 옮겼다. 제품 코드를 바꾸거나 속성 저장을 Fake로 대체하거나 기대값/허용 오차를 완화하지 않았다. 기존 USD Engine 시험을 먼저 실행한 순서 검사는 **32 passed, 27.10s, exit0**이었다(`ordered-sdk-green.xml/log`).

등록 시점 수정 후 별도 최종 실행 `release-full-verified.xml/log`는 **1,984 passed / 실패0·오류0·skipped0**, Console **634.06s**, JUnit **634.024s**, 실제 **exit0**이다. `release-full-verified-result.json`에 실행 argv·시각·실제 exit·wrapper wall time636.873s가 있다. Phase 1B testcase `(classname,name)` Counter와 대조해 **기존 1,963개 누락0·신규21개**를 확인했다(`regression-comparison.json`). 기존 시험 변경·삭제·rename·skip·xfail은 없다. 첫 실패 실행이나 이전 통과 수를 최종 결과로 대신 쓰거나 두 실행을 합산하지 않았다.

경고5개는 기존 `record_property`/xunit2 경고1개와 torchvision 영상 API deprecation4개다. 기존 회귀의 실제 Native parser·합성 MuJoCo/EGL·Qt/OpenGL/Sandbox Blender·작은 CPU Policy Forward와 실제 Kit/RTX/센서 검증을 구분한다. 재구성 모델 Forward·고비용 온라인 AI·사용자 Scene E2E는 실행하지 않았다.

## 8. 변경 파일·보존

이번 Phase의 변경은 기존 제품 **2개 수정 + 신규 시험/문서 2개**, 삭제0이다.

- `robot_learning_workbench/src/robot_learning_workbench/engines/isaac/env_cfg.py`: 검증·정확한 physical/native 속성·기존 RuntimeCamera 초기화/readback/setter.
- `robot_learning_workbench/src/robot_learning_workbench/robot/scene_render.py`: Isaac metadata의 실제 영상 해상도 한 줄.
- `robot_learning_workbench/tests/test_isaac_camera_intrinsics.py`: 신규21개 재현/수학/Schema/Consumer 시험.
- `docs/reviews/phase1c-isaac-camera-intrinsic-fix.md`: 이 보고서.

변경 시작 tracked499개와 이전 untracked9개의 내용/SHA를 저장했다. 최종 대조에서 허용한 제품2개 외 tracked497개와 이전 untracked9개는 같았다. Phase 1A/1B 제품·시험·보고서와 기존 미커밋 변경을 그대로 보존했다. `execution_inputs`, `scene_execution_inputs`, `write_scene_assets`, `spawn_robot`, `_update_poses` AST, 기존 `build_env_cfg` 인자, MuJoCo render branch AST, 조사한 SDK8개 SHA도 동일하다(`contract-preservation.json`, `change-inventory.json`). Source/Annotation/DataGen/Evaluation과 Builder Renderer는 수정하지 않았다.

종료 후 보호 root의 **19,612개 파일 SHA/크기와 전체 경로 집합 변경0·누락0·신규0**을 확인했다(`preservation-after.json`). 보호 root는 `workbench_runs/{scenes,object_assets,capture,calibration,runtime,source,dataset,datagen,annotation,evaluation,curation,policy,scripts}`다. 원본 Scene/Input/Capture/Calibration/Candidate/Cache/Asset/Export/Dataset을 보존했다. SDK/모델 Cache/홈 전체의 전수 검증과 구분한다.

변경 Python3개는 bytecode 없는 compile을 통과했고 최종 전체 실행 시작 때의 SHA와 같다. 새 파일 whitespace와 `git diff --check`도 통과했다(`compile-check.json`). HEAD/브랜치는 시작과 같으며 Index diff SHA는 빈 diff의 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`로 유지했다. Commit/Push/Merge·reset/clean/checkout/stash·환경 변경은 하지 않았다. 최종 보고서만 시험 종료 후 결과를 갱신했고 제품/시험 코드는 재변경하지 않았다.

## 9. 검증 한계와 위험

- **실제 AppLauncher/Kit/RTX RGB·Depth 렌더, GPU Sensor K, 영상 속 3D landmark의 픽셀 위치는 NOT_TESTED.** 사용자가 고비용 Isaac 실행을 별도 승인하도록 제한했으므로 이번에는 시작하지 않았다. 추가 승인 없이 CPU 설정/실제 USD Schema·수학·기존 회귀로 검증했다. GPU 실측을 완료로 보고하지 않는다.
- Isaac Lab private 초기화/readback hook 두 곳과 Sim5.1 native Schema에 의존한다. 다른 SDK 버전의 지원은 미검증이다. Schema 적용 불가/일치하지 않는 imageSize·왜곡 계수는 실패하며 평균값 fallback은 없다.
- K의 native 저장과 Sensor buffer는 float32다. 소수 값의 양자화는 그대로 보고하며 double 정밀도의 무손실 보존이라고 하지 않는다. 실제 shader/rasterization 오차는 별도다.
- 별도 Camera/Sensor/Render Product/Framework/Manager·외부 패키지·새 CLI/Scene schema를 추가하지 않았다. USD read/write는 초기화/명시 K setter에서 수행하고, 기존 매 프레임 pose/이미지 갱신 루프는 바꾸지 않았다. 실제 GPU 처리량/VRAM 변화는 측정하지 않았다.
- Source Package/Scene의 K나 Extrinsic을 Simulator 제약에 맞춰 다시 쓰지 않는다. native API setter의 예기치 않은 USD 쓰기 실패는 Runtime 오류로 중단한다. 외부 USD 편집의 원자적 rollback 시스템을 새로 구현한 것은 아니다.
- BUG-006–021/RISK-001–002, 실제 센서 Calibration/FK/독립 Real-Sim 정확도·물리 검증은 범위 밖으로 유지한다.

재검토 자료: `baseline-code.json`, `baseline-focused.xml/log`, `impact-analysis.md`, `installed-api-sources.json`, `extension-dependencies.json`, `caller-audit.json`, `native-schema-probe.json/log`, `projection-comparison.json`, `camera-red-final.xml/log`, `runtime-red.xml/log`, `runtime-green.xml/log`, `consumer-red.xml/log`, `consumer-green.xml/log`, `release-focused.xml/log`, `release-full.xml/log`, `first-regression-comparison.json`, `late_schema_probe.json/log`, `ordered-sdk-green.xml/log`, `release-full-verified.xml/log`, `release-full-verified-result.json`, `regression-comparison.json`, `contract-preservation.json`, `tested-files.json`, `change-inventory.json`, `preservation-after.json`, `compile-check.json`, `verification-summary.json`.
