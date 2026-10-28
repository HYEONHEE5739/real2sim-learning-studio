# S02 — Frame Graph·SE(3)·Calibration 적용 관계

2026-10-25. 상태: **S02 구현·오프라인 검증 완료**. [SPEC](../SPEC-scene-package.md)과 [Interface](interfaces.md)의 좌표·보정 관계를 [S01](s01-scene-package.md) 파일 계약에 연결했다. 기존 원본·환경·B01~B03·S01 증거는 보존했다. Builder Export·UI·엔진/장치 연결·후속 작업은 시작하지 않았다. 이 보고서는 새 v8 실행 패키지의 변환·물리/렌더 검증 결과가 아니다.

## 파일과 호출 관계

| 제품 파일 | 책임 / 변경 |
|---|---|
| [transforms.py](../scene_contract/src/scene_contract/transforms.py) | `validate_transform`, `validate_frames`, `resolve_transform`. NumPy만 사용하며 reference matrix 검증/계산을 소유 |
| [package.py](../scene_contract/src/scene_contract/package.py) | `validate_scene`에 Frame·Geometry 참조 및 Calibration 관계 검사를 연결. `load_scene`은 파일 무결성 검증 후 보정 파라미터 파일의 실제 binding도 검사 |
| [pyproject.toml](../scene_contract/pyproject.toml) | 패키지 0.2.0. 기존 설계의 작은 공통 계산을 위해 NumPy>=1.26,<2 선언. 설치/업그레이드는 하지 않음 |
| [test_transforms.py](../scene_contract/tests/test_transforms.py) | 행렬·부모 회전·역변환·cycle·동적 기준값·긴 chain 시험 |
| [test_scene_package.py](../scene_contract/tests/test_scene_package.py) | 기존 S01 75개를 포함해 로더/보정 관계/identity의 실제 임시 파일 회귀. S01의 최소 보정 fixture에는 새 관계 검사에 필요한 robot joint_order를 명시 |

런타임 파일은 위 범위만 변경했다. 새로운 Interface/Adapter/Wrapper/ABC·Scene service·Calibration 실행기·등록 시스템은 추가하지 않았다. `load_scene → verify_files → validate_scene → validate_frames/보정 관계 검사 → 필수 파일 참조/실제 파라미터 binding` 순서다. 오류 타입은 기존 package.py에 유지하며 transforms는 그 오류를 사용한다. package.py는 함수 안에서 transforms를 import하므로 import 시 엔진/장치가 시작되지 않는다.

## Frame·Transform 계약

- `validate_transform(value, *, field="transform") → ndarray`: numeric real finite 4×4, homogeneous 마지막 행, 오른손 orthonormal 회전 검사. 결과는 float64 copy다. 원래 P `real2sim/profile.py:67 transform`처럼 float64로 읽고 행렬을 보정/직교화/단위 변환하지 않는다.
- 기존 `np.allclose`/`np.isclose` 조건을 명시했다. 마지막 행 atol=1e-8, rotation Gram/determinant atol=1e-5, 기존 기본값과 같은 rtol=1e-5다. 허용 오차를 새 결과에 맞춰 변경하지 않았다. 문자열·bool·complex를 새 JSON 숫자로 강제 변환하지 않는다.
- `validate_frames(frames)`: world가 유일한 root이고 기준 행렬은 canonical identity다. parent 누락·별도 root·cycle·잘못된 ID/행렬·state를 거부한다. Graph 검사는 반복문으로 처리하며 1,200개 frame chain을 시험했다.
- Frame은 `parent`, `T_parent_from_frame`, `state: reference`, 선택 `dynamic_source`다. named frame과 Geometry local_transform을 중복 저장하지 않는다. 명시된 frame_id/frame_ids/optical_frame_id/mount_frame_id를 검증하고 Geometry는 frame_id 또는 local_transform 하나를 사용한다. 실제 native body/joint/prim lookup은 엔진 단계다.
- `resolve_transform(frames, *, source, target, state="reference") → ndarray`는 열벡터 기준 **`inverse(T_world_target) @ T_world_source`**다. parent→child의 곱 순서를 유지하며 원래 코드와 같은 전체 `np.linalg.inv`를 사용한다. 회전을 transpose로 바꿔 근사 역변환하거나 결과를 강제로 identity로 만들지 않는다.
- dynamic_source가 있는 frame의 Metadata pose도 **기준 상태**다. `state="current"` 등은 FRAME_UNRESOLVABLE이며 engine의 현재 pose로 대체하지 않는다. 현재 pose를 자동 조회하거나 stale USD wrist pose를 재사용하는 구현은 없다.

세계 root의 identity는 새 계약의 canonical 값이다. 임의의 local Transform에 적용하던 기존 SE(3) tolerance를 바꾼 것이 아니다. v8의 world root fixture는 실제 identity이고 Workspace의 측정된 기울기/좌표는 child 행렬 그대로 유지한다.

## Calibration 적용 관계

`validate_scene(scene, calibration, *, files=None)`는 기존 두 인자 호출도 지원한다. files는 검증된 Manifest FileEntry 목록을 추가 제공하는 옵션이며 파일을 읽거나 hash 검사하는 API가 아니다. `load_scene`은 S01 `verify_files` 후 files를 전달한다.

검증 항목:

1. record/target·model hash·joint_order/frame_ids·evidence ID의 존재와 타입. 로봇에 결합된 보정은 Scene robot joint_order와 **순서까지** 같아야 한다. 카메라는 자신의 frame 및 sensor 또는 input Asset identity를 요구하고 로봇 정보를 강요하지 않는다.
2. baked는 asset_paths/input_calibration_ids/order_index, runtime은 phase/input_space/output_space/order_index다. known runtime phase는 device_observation/device_command/scene_initialization/camera_render이며 잘못된 모드/필드/시점을 거부한다.
3. dependency의 누락·중복·cycle, 같은 실행 문맥의 order_index 충돌, 의존 연산의 역순 및 output/input space 불일치를 거부한다. 서로 다른 단계의 dependency는 자료/fit 근거일 수 있으며 다른 단계의 보정을 자동 실행하지 않는다.
4. 실행 문맥은 target·mode·phase·input_space다. Leader/Follower 관측은 서로 다른 입력 공간으로 표현하고, Follower 관측/명령은 다른 phase다. 이를 하나의 보정 두 번으로 잘못 분류하지 않는다.
5. 같은 operation(kind/target/algorithm)의 파라미터 identity 또는 source/execution 모델 identity가 같은 경우, 같은 runtime 문맥의 중복/동시 대체 프로필 및 baked/runtime 중복을 거부한다. 파일별 파라미터 SHA와 inline JSON identity를 사용한다. baked는 겹치는 결과 Asset의 중복/순서도 검사한다.
6. baked의 execution_model_sha256가 선언된 출력 Asset의 Manifest hash와 맞아야 한다. residual의 기준 모델은 의존 encoder의 execution model과 일치해야 한다. 파일이 어디엔가 있다는 사실만으로 올바른 보정 결과 Asset으로 판단하지 않는다.

**v8 보존 규칙:** `precision_bound_residual`은 이미 Geometry에 baked된 알고리즘으로 취급하고 runtime 재선언을 거부한다. Geometry residual을 device observation/command의 q에 더하는 것도 거부한다. input_calibration_ids의 Encoder는 fit의 숫자 공간 근거이지, Encoder 변환까지 Geometry에 구워졌다는 뜻이 아니다. 유효한 Encoder runtime + residual baked 조합을 시험했다.

이 알고리즘의 `precision_mapping_sha256`는 의존 Encoder 파라미터의 **실제 canonical mapping hash**와 일치해야 한다. 기존 so101.precision-joint-mapping/1의 SHA 계산·role·현재 모델 SHA·관절 순서를 확인한다. inline뿐 아니라 parameters_file도 `load_scene`이 JSON을 읽고 **읽은 bytes의 Manifest SHA까지** 확인한 뒤 검사한다. Manifest를 다시 계산해 파일 손상 검사를 통과하더라도 잘못된 fit binding은 거부한다.

파일 접근이 없는 `validate_scene` 단독 호출은 file-based 파라미터의 실제 payload binding까지 확인했다고 주장하지 않는다. 완전한 패키지 검증은 `load_scene`을 사용한다. fitter·Encoder 변환·limits-only 모델 재결합을 새 제품으로 이관한 것은 아니며 해당 계산은 RO01에 남는다. runtime에서 phase를 연결하고 실제 적용 횟수를 확인하는 시험도 엔진/장치 구현 단계다. 선언되지 않은 임의 Python 코드의 중복 실행까지 방지한다고 보장하지 않는다.

## 실제 근거와 수치 비교

P의 원래 profile.transform/pose 및 utils/transforms.pose_matrix 함수 body를 읽어 오프라인 reference로 사용했다. NumPy 1.26.0, SciPy 1.15.3, Pinocchio는 기존 환경 그대로 사용했으며 SciPy/Pinocchio는 **증거 harness 전용**이다. 새 공통 패키지의 runtime 의존성은 NumPy뿐이다.

| 비교 | 결과 / 근거 |
|---|---|
| v8 table·Object→World/Robot base | 실제 12개 배치와 Workspace Transform. 직접 기존 곱과 graph 결과의 bitwise 일치 확인 |
| Side optical pose | 저장 T_parent_camera와 world 결과 동일 |
| Wrist optical pose | B01 Isaac/MuJoCo Source에서 각각 0·중간·마지막 q, 총 6개 snapshot. calibrated URDF의 공식 Pinocchio BODY FK→기존 mount 곱과 graph 결과 동일 |
| Quaternion | 기존 pose의 xyz+wxyz와 명시적 xyzw 재배열을 기존 pose_matrix로 복원해 <=1e-12 비교. API는 matrix4를 사용하며 Quaternion 순서를 추측/재작성하는 함수를 추가하지 않음 |
| optical/OpenGL convention | Side/Wrist의 mount-parent 기준 optical→engine flip 합성과 왕복이 B03의 저장 행렬과 동일. 엔진 변환 함수를 새로 구현한 것은 아님 |
| SE(3) 경계 | homogeneous/rotation의 아래·같음·위, reflection·float32 camera 입력 등 8개에서 기존/신규 통과·거부 동일 |
| 6관절 Geometry 보정 | `R_origin × R_axis(offset)`을 graph로 합성. 기존 Quaternion 곱 식과 차이 최대 **4.440892098500626e-16**, 저장된 보정 URDF rpy 회전과 **9.08995101411847e-16** |
| 곱 순서 반전 | 반대 순서가 실제로 다른 결과를 내는 관절이 있음을 별도 수치로 기록. 이를 정답으로 대체하지 않음 |

Geometry 비교의 허용 오차 1e-12는 B03의 기존 대조 기준을 유지했다. matrix 곱과 SciPy Quaternion 곱/rpy 직렬화 사이의 float64 표현 차이를 구분한 것이며 bitwise 같은 경로라고 주장하지 않는다. **기존 Export의 Quaternion 곱을 새 matrix 코드로 교체하지 않았다.** Export는 이번 범위가 아니다.

숫자·입력 SHA·실제 좌표는 [numeric-probe.json](evidence/s02/numeric-probe.json)에 있다. Wrist 결과는 기록된 q에서 계산한 **오프라인 기준 snapshot**이지 PhysX/Fabric의 현재 pose/픽셀 재검증이 아니다. tool0를 gripper body 원점으로 혼동하지 않았다. Pinocchio의 gripper 이름이 joint와 BODY에 겹쳐 초기 harness가 실패하여 공식 FrameType.BODY로 명시했고, AST pose 함수의 transform 의존성도 명시했다. 초기 로그를 보존했으며 원본·기대값·tolerance를 변경하지 않았다.

## 패키지 통합·검증 결과

- **전체 pytest 138개 통과, skip 0개.** [JUnit](evidence/s02/unit-tests.xml), [로그](evidence/s02/logs/11-final-suite.log). S01의 기존 75개와 새 Frame/Calibration 경계를 함께 검증했다.
- 실제 Leader/Follower 프로필을 B03과 같은 read-only reference 계산으로 현재 모델에 메모리 binding한 mapping SHA는 Leader `0eabde8c…`, Follower `bcee6d87…`이며 v8 residual 근거와 일치했다. 원본/현재/보정 모델 파일 및 양 역할 관측·Follower 명령·baked residual을 **임시 계약 fixture**로 구성해 **9개 검사**를 통과했다. [calibration-probe.json](evidence/s02/calibration-probe.json)
- 파일 패키지 이동 후 identity·Transform/보정 metadata 유지, 잘못된 binding·모델·관절 순서·cycle·중복·runtime residual·baked 결과 오류를 차단했다. fixture는 테스트 후 삭제했고 실제 Scene Export나 데이터 변환은 하지 않았다.
- [wheel 검증](evidence/s02/build.json): 빌드·source 대조·compile·isolated wheel import 및 resolve_transform smoke 통과. 기존 환경에 설치하지 않았다. 엔진·Qt·LeRobot·장치를 import/시작하지 않았다.
- [보존 대조](evidence/s02/preservation-after.json): 기존 56,100개 파일 stat와 선택 14,947개 SHA, 이번 probe 입력 SHA를 비교한다. 전체 corpus/외부 SDK binary의 전수 byte 검증은 아니다.
- [최종 검증](evidence/s02/verification.json)과 [commands.json](evidence/s02/commands.json)에 인터프리터·명령·코드/산출물 identity·문서 검사·작업 경계를 기록했다. 별도 lint/type 도구는 설치/설정되지 않아 실행했다고 주장하지 않는다.

## 완료 경계·남은 문제

S02의 Frame Graph·reference SE(3) 계산과 Calibration 선언 관계/중복 검사는 완료했다. SPEC AC02의 순수 계산·경계와 AC03의 Metadata 중복/상태 보존 부분을 검증했다. **AC01의 실제 엔진 로딩 및 전체 SPEC의 실행 동등성은 미완료**다.

기존 v8 JSON을 새 형식으로 읽는 Legacy loader나 변환기를 만들지 않았다. native USD/MJCF/Finger 내부 참조 closure, 새 Export·자산 이동 후 실제 loader, 동적 카메라 센서 시점·픽셀/물리, RO01의 실제 보정 계산 이관, RO02의 종료 오류·실물 시험은 후속 범위다. ASSET-FINGER-01·CAL/ROBOT의 해당 OPEN 항목을 해제하지 않는다.

B01 Isaac DataGen 실패·Evaluation 비결정성, B02의 기록 phase/tick·누락 정보와 정책별 Resume, B03 physical_verified=false·v8 UNVALIDATED 상태는 그대로다. 기존 동작/성공 판정·보정값을 변경하거나 검증 상태를 승격하지 않았다. 새 schema_version=1의 예정된 S02 검증이 추가되어 불완전한 S01 synthetic fixture는 robot joint_order 등 필수 관계를 명시하도록 수정했다. 실제 사용자 자료를 변환한 것은 아니다.

`incremental-implementation`과 `test-driven-development`를 적용해 테스트→최소 구현→검증을 나누어 진행했다. 새 프로젝트는 Git 저장소가 아니므로 저장소 초기화/commit은 하지 않았다. **S02만 완료하고 다음 작업은 자동 시작하지 않는다.**
