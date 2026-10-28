# SPEC: Builder 편집·정합·Export

ID: `builder`. 작성: 2026-10-25. 상태: **BU01~BU04 구현·오프라인/공식 파일·정적 렌더 검증 완료, 실제 engine runtime 관문 OPEN**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). [구현 결과](docs/builder-bundle.md)는 실제 시험 범위와 미검증 관문을 구분한다.

## 목표와 범위

기존 Scene 제작·검토 기능을 독립 Builder에서 유지하고 실행용 불변 Revision을 생성한다. 범용 새 Scene Editor 기능을 확장하지 않는다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| B core/project.py, scene.py, candidates.py, evidence.py | 후보·선택·근거 상태 의미 | project.py 및 ui.py의 편집/검토 연결 |
| B reconstruction/scan.py, pipeline.py; calibration/camera.py fit_cameras, multipose.py fit 및 depth/physics/robot | registration/segmentation·정합·잔차·물성 추정 계산 | reconstruction.py, calibration/{camera,geometry,physics}.py |
| B exporters/package.py, usd/mujoco, blender, validation | 기존 엔진 형식/렌더·검증 계산 | export.py, exporters/{usd,mjcf}.py, validation.py, rendering.py, cli.py |

구현 파일 범위: `project.py, reconstruction.py, calibration/*.py, export.py, exporters/*.py, rendering.py, validation.py, cli.py, ui.py`. 경로는 real2sim_builder의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `real2sim_builder/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- 저장된 촬영·scan 자료로 재구성/정합 검증을 시작할 수 있다. Workbench Capture 완성을 기다리지 않는다.
- 최종 Export만 scene-package 계약과 CAL-01/CAL-02에 의존한다.
- 기존 project/candidate/export가 다른 자료임을 확인하고 동일 입력/선택 candidate Baseline을 고정한다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- 외부 MuJoCo Finger Collision과 실행 의존 자료는 새 Export에 포함하고 manifest.json에 path/size/SHA로 등록한다. 실제 로더도 패키지 내부 상대 참조를 사용한다. 이동 후 원본 repo를 숨긴 상태에서 로딩/source hash·접촉 자료 확인을 통과해야 builder-AC03을 완료할 수 있다. 기존 v8 원본은 보존한다.

- 편집 프로젝트와 Export를 구분한다. export_revision은 candidate·Calibration identity를 고정하고 신규 destination에만 publish한다.
- USD/MJCF의 중첩 참조·Mesh/Texture/URDF/Collision 의존성을 엔진별 exporter가 조사한다. 실행 필수 자료는 포함하고 외부 증거는 ID/hash/location으로 추적한다.
- 파생 파일의 원본/변환 이유를 기록하며 무변환 자산의 불필요한 재작성은 피한다. 이동 후 두 엔진 로딩 시험은 Export 완료 조건이다.
- 기존 편집/검토/렌더의 버튼·CLI 목록과 대응 화면을 대조한다. 추정·시각 검토를 물리 정합 검증으로 승격하지 않는다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## 검증과 완료 기준

- **builder-AC01**: 같은 scan/candidate 입력의 정합 결과·잔차·선택 상태 보존.
- **builder-AC02**: 신규 Revision Export가 이전 Revision과 원본을 변경하지 않음; 중단 시 부분 결과를 완성 패키지로 노출하지 않음.
- **builder-AC03**: 외부 원본 증거가 없어도 실행 필수 자산이 완전한 패키지는 이동 후 로딩 가능.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래는 **테스트 파일 및 환경 구축 후 사용할 목표 명령**이며 현재 실행하지 않았다. 실제 real2sim_builder 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest real2sim_builder/tests/test_builder_project.py real2sim_builder/tests/test_builder_calibration.py real2sim_builder/tests/test_builder_export.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 한계: BU의 파일·순수 계산·공식 parser/정적 렌더 회귀는 완료했다. PhysX/Fabric·실제 articulation/센서·native collider 적용/접촉은 E01/E02에서 검증한다. 근거 없는 값으로 명세를 채우지 않는다.

## BU 완료 기준의 증거 범위

[BU 묶음](docs/builder-bundle.md): AC01의 기존 정합/후보/지표·저장 입력 의미, AC02의 불변 신규 publish·강제 종료/I/O 경계, AC03의 Manifest/native closure·필수 Finger/pad/source/model bytes·이동 후 공식 MjModel/USD Stage 로딩을 확인했다. 실제 simulator task 실행·접촉은 AC03의 후속 통합 관문이며 파일 검증으로 대체하지 않는다. UI/CLI 기능과 실제 static EGL/Blender 렌더·전체692개 회귀를 대조했다.

## E01 native v8 실행 자산 보존 보완

2026-10-26 최종 결정: 신규 Revision Export는 기존 v8 실행 USD를 `isaac_robot_asset`으로 명시 수집할 수 있다. source physics/collider/instance/joint는 재생성하지 않고 모든 native 파일 참조를 package 내부 상대 경로로 고정하며 `robot.bindings.isaac.asset_path`에 기록한다. USD에 필요한 SDK material은 명시 `asset_resolutions`로만 읽고 상대 MDL module도 등록한다. 알 수 없는 모듈/누락은 거부한다. 원본·이전 Export를 쓰지 않으며48Object/2Camera/Frame/Calibration 정합을 다시 fitting하지 않는다. Isaac288 재생성은 폐기하고 MuJoCo의 기존 Finger JSON/source identity 요구는 유지한다. 기존 프로젝트/후보 편집·검증·새 Revision publish/UI·CLI 계약은 변경하지 않는다. [재검증](docs/e01-v8-collision-recovery.md)의 file/parser/actual engine 및 remaining numeric OPEN을 구분한다.

## 2026-10-27 신규 Scene 수평 초기 기준 준비

`project.validate_horizontal_layout`은 미래 새 Scene의 명시 box Table/Workspace/블록과 Robot Base 기준 +Z를 읽기 전용으로 검사한다. Table 상면과 Workspace 평면은 World XY에 평행/+Z이며 Workspace 전체와 블록 회전 Footprint가 실제 Support 안에 있어야 한다. 접촉 Z는 Geometry로 확인한다. Table 높이·Robot Base 위치는 독립적이며0으로 바꾸지 않는다. Camera extrinsics·joint axis/origin/URDF·고정 설치물은 자동 수평화하지 않는다.

기존 v8 validate/Export에 강제하지 않는 opt-in 함수이며 Calibration 승인 기능이 아니다. 결과의 calibration_verified=false를 유지한다. 이번에는 synthetic 메모리 fixture만 시험하고 **실제 v9 생성/Export·실물 Calibration·UI는 수행하지 않는다**. 일반 mesh/복합 기준면은 이 초기 box validator의 완료 범위가 아니다. [결과](docs/random-placement-horizontal.md).
