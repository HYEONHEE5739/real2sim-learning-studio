# SPEC: 장치·Capture·Precision Calibration

ID: `robot-operations`. 작성: 2026-10-25. 상태: **RO01~RO03 오프라인/fake 범위 구현·검증 완료, AC03 실물 BLOCKED**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). 최초 명세 이후 사용자의 승인으로 [RO 묶음](docs/robot-operations-bundle.md)을 구현했다. 실물 검증 완료를 뜻하지 않는다.

## 목표와 범위

기존 로봇/카메라 연결과 Capture·보정 계산·제어 의미를 보존한다. 실물 검증과 오프라인 수치 검증은 별개로 기록한다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. [B03](docs/b03-calibration-device.md)에서 기존 계산·대표 mock 계약의 근거를 확보했다. 새 구현이나 실물 검증 완료 목록은 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| P real2sim/runtime.py, ui.py | 연결/종료·joint/camera snapshot·동기·오류 처리 | robot/devices.py, capture.py, control.py |
| P real2sim/precision.py simulation_configuration/profile_for_model, precision_ui.py; workspaces/builder.py calibrate_simulation_usd | encoder branch/역변환/양자화·identity·잔차 적용 | robot/calibration.py 및 해당 UI 연결; geometry residual의 엔진 적용은 엔진 책임 |

구현 파일 범위: `robot/devices.py, robot/calibration.py, robot/control.py, robot/capture.py`. 경로는 robot_learning_workbench의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `robot_learning_workbench/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- ROBOT-01은 장치 수명/명령 구현 전, CAL-01은 보정 계산 전, CAL-02는 camera 동기/pose 연결 전에 확인한다.
- 저장된 encoder/모델/영상 fixture의 오프라인 계산은 장치 연결 없이 병행한다.
- 실제 모터 시험은 별도 사용자 승인과 기존 중지/제한 계약 확인 후 수행한다. UI skeleton은 이를 기다리지 않는다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- 장치 식별·connect/read/command/stop/disconnect는 [B03 §4](docs/b03-calibration-device.md#4-robot-01--연결활성화정지해제-계약)의 실제 signature·단위·부수 효과를 기준으로 한다. 근거 없는 공통 Device interface를 발명하지 않는다.
- 입력 공간(raw/native/model), 관절 순서, observation과 requested/applied command, clipping/timeout과 오류 후 연결 상태를 명시한다.
- 보정 프로필은 model identity에 결합한다. baked geometry residual을 joint command에 다시 더하지 않고 homing offset도 중복 적용하지 않는다.
- Capture 자료는 camera/joint 시각·frame/unit·Calibration identity와 소유 파일을 기록한다. 새 자료 저장은 원본 profile 덮어쓰기와 분리한다.
- 조회/탭 전환은 장치를 연결하지 않는다. UI 종료/취소·연결 끊김은 기존 중지 절차와 결과 불명 상태를 보존한다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

### B03으로 구체화한 보존·오류 경계

- 관절 배열은 JOINTS 순서로 고정하며 프로필 JSON key 순서를 사용하지 않는다. raw count(이미 homing 적용)·팔 native degree/gripper percent·6 model rad·policy feature/processor를 구분한다. 관측은 범위 밖 원값을 보존하고 command는 모델/모터/encoder branch·정수 양자화를 검사한다.
- profile_for_model은 전체 모델 증거에 따른 limits-only **메모리 copy**이며 활성화/저장이 아니다. role/device/calibration·프로필 hash를 대조하고 알 수 없는 schema를 legacy로 자동 대체하지 않는다. v8의 baked residual은 원 회전×축 보정 순서와 source mapping binding을 유지하고 q/하드웨어 명령에 다시 더하지 않는다.
- Stop은 새 goal 중단·마지막 목표 유지, 일반 disconnect는 torque release 요청, readonly Calibration disconnect는 torque 상태 유지다. 모의 activate에서 raw Present→Goal→readback→공식 configure 순서를 검증했다. SDK send 반환을 실제 측정 feedback으로 저장하지 않는다.
- 공식 configure는 register 쓰기 및 torque 재활성화가 있으며 예외에서도 enable_torque가 실행될 수 있다. SDK torque release 실패는 port close 전 실패할 수 있다. RO02는 Leader 부분 연결·Precision.close 예외·CameraReader join timeout·UI 종료와 중복 close의 자원 정리와 effect unknown을 검증해야 한다. 현재 구조의 cleanup 누락을 새 필수 동작으로 복사하지 않되 물리 정지 의미를 임의 변경하지 않는다.
- CAL-02는 raw K/distortion과 virtual render K, optical과 엔진 camera convention, 동적 PhysX/Fabric wrist pose, host receipt와 exposure 시각을 구분한다. Capture 100ms/200ms와 평가 stale 500ms, 팔 보간/gripper left hold의 기존 조건은 단계별로 보존한다.
- 실제 평가의 official processor→action→URDF clip→strict inverse/SDK encoding→send를 유지한다. float64 hold preflight와 float32 policy observation은 다르며 실제 Task 성공은 기존처럼 미측정/사람 검토다. 실물 시험은 미완료다.

## 검증과 완료 기준

- **robot-operations-AC01**: encoder 경계·roundtrip·limits·양자화·모델 mismatch·적용 횟수 fixture 통과.
- **robot-operations-AC02**: mock 연결 실패/timeout/중복 종료에서 수명·오류 상태 일치; mock 통과를 실물 검증으로 표시하지 않음.
- **robot-operations-AC03**: 승인된 실물 시험의 관측/명령/중지·Capture 동기 결과를 별도 증거로 확보.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래 suite는 기존 Python/PYTHONPATH로 실행했으며 [명령·증거](docs/evidence/robot-operations/commands.json)에 실제 환경을 기록했다. 실제 robot_learning_workbench 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest robot_learning_workbench/tests/test_robot_lifecycle.py robot_learning_workbench/tests/test_precision_calibration.py robot_learning_workbench/tests/test_capture_contract.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 근거: [RO01~RO03](docs/robot-operations-bundle.md)의 AC01 계산·identity와 AC02 대표 fake 수명/오류 검증 완료. 전체647개(신규76)·wheel/보존·원래 함수 exact 대조. RO03 host-time/안정성/frame/snapshot 준비 계약 구현. AC03 및 실제 장치/엔진·UI/프로세스 상실의 물리 Stop/토크/포트 상태는 BLOCKED/미검증이다. Snapshot 파일 publish/프로필 활성화 UI·Recipe runner는 완료로 표시하지 않는다.
