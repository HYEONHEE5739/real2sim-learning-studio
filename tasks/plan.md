# 구현 및 검증 계획

2026-10-25 최종 결정: 새 플랫폼 개발 기준은 **Isaac Sim5.1 / Isaac Lab2.3 / LeRobot0.4.1 / MuJoCo3.3.7**이다. 업그레이드는 진행하지 않는다. 최신 버전 조사는 참고 이력이며 신규 환경 분리·분리 추론·업그레이드 대응 코드는 개발 범위에 포함하지 않는다. 기존 UI/엔진 worker의 필요에 따른 프로세스 분리는 유지한다.

작성: 2026-10-25. 상태: **B00·B01·B02·B03 조사/대표 검증 및 S01·S02·T01~T04 및 D01~D04 및 R01~R03·RO01~RO03의 승인된 파일/프로세스·오프라인/fake 범위 완료**. 이후 BU01~BU04·E02/E05 기반 및 E03/E04/E06의 일부 실제 엔진 경로를 추가 검증했다. 현재 범위/OPEN은 문서 끝의 2026-10-27 Workflow 결과와 todo 개별 체크를 따른다. [기능 색인](../CAPABILITY-MAP.md)에서 11개 SPEC으로 이동한다. 개별 완료는 새 Writer·장치/보정 실행기·Resume 구현 완료나 전체 OPEN 확인 항목 해제를 뜻하지 않는다.

2026-10-26 진행 원칙: 관련 3~5개 작업을 한 묶음으로 선정하고 각 Task의 작은 구현/시험이 통과하면 승인 대기 없이 다음 Task로 진행한다. 중요한 미승인 설계 변경·실제 장치/외부 업로드가 필요하면 중단/보고한다. 첫 묶음 [D01~D04](../docs/episode-data-bundle.md) 완료 후, 사용자의 후속 승인으로 [R01~R03 묶음](../docs/recipe-execution-bundle.md)도 수행했다. 후속 사용자 승인으로 [RO01~RO03](../docs/robot-operations-bundle.md)을 오프라인/fake 범위에서 완료했다. 후속 사용자 승인으로 [BU01~BU04](../docs/builder-bundle.md)의 프로젝트/정합·불변 Export·Builder UI/CLI를 구현했다. 파일/parser/정적 렌더와 실제 articulation/센서/접촉 관문을 구분한다. 다음 E01/E02는 권장 후보이며 자동 시작하지 않는다. 개별 긴 중간 보고 대신 증거 파일을 남기고 묶음 끝에 결과를 보고한다.

## 1. 의존성 적용 원칙

의존성은 작업 단위 전체 완료가 아니라 해당 하위 기능이 소비하는 계약/fixture의 준비 상태다. runtime 입력 의존성, 개발 순서, 통합 완료 조건을 구분한다. 필요한 계약이 없으면 가짜 값으로 실제 실행하지 않되, 명시적인 시험 fixture로 독립 코드 검증은 가능하다.

| 하위 기능 | 필요한 선행조건 | 기다릴 필요 없는 기능 |
|---|---|---|
| JSON/경로/Transform 검사 | 기존 좌표 의미와 계약 | Builder UI·실물·학습 |
| Task 등록 검사 | 함수 선언 계약 | 엔진·Episode writer |
| 판정 순수 계산 | 해당 기존 함수 Baseline/경계값 | 전체 Source/DataGen |
| Episode reader/writer | DATA-01 의미 매핑, DATA-02 시험 기준 | 실물·엔진 전체 구현 |
| YAML 파싱/claim/IPC | 해당 파일/메시지 계약 | 모든 stage runner |
| Builder 정합 | 저장 scan/camera/모델 자료·기존 계산 Baseline | 새 Capture 기능 |
| 외부 공식 Dataset 학습/Hub | 공식 버전/config/인증·자료 계약 | Scene·내부 writer·Task |
| 내부 LeRobot 변환 | Episode/action/영상 매핑 | DataGen 전체 구현 |
| Annotation/DataGen | 저장된 적합 입력·엔진 state·Task·writer | 새 Source 실물 수집 |
| Sim Evaluation | 엔진 state·Task·Policy 매핑 | DataGen·실물 평가 |
| Curation 분포/선택 | reader fixture·frame/unit | 실제 학습·평가 |
| UI 편집/로그/진행 | 파일/IPC fixture | 엔진·로봇 연결 |
| 실물 평가 | 장치/보정/Policy 제어 계약과 승인된 실물 시험 | DataGen 전체 완료 |

Isaac과 MuJoCo는 병행 가능하며 공유 파일 동시 수정은 작업별 소유 파일을 정해 충돌을 피한다. 이 계획은 병렬 에이전트 실행 지시가 아니다.

## 2. Baseline과 선행 확인


1. 기존 루트 P/B, v8, 실제 외부 자산·profile·설치 환경·UI/CLI 경로를 읽기 전용으로 목록화한다. 문서의 과거 줄 번호는 현재 파일에서 재확인한다.
2. 기존 실행의 출력/캐시/log·장치 연결 부수 효과를 조사한다. 원본에 쓰는 명령은 그대로 실행하지 않는다. 별도 시험 작업 공간에서 참조 코드를 사용하되 원본 hash와 차이를 기록한다.
3. Source/Annotation/DataGen/Evaluation별 두 엔진 fixture를 확보한다. scene/asset/calibration identity, seed/RNG, 초기 state, requested/applied/observed, 영상 frame, pre/post-step, 접촉, 판정 중간값, 실패·취소·Resume 사례를 포함한다.
4. 순수 계산은 경계값·상태 sequence를 채취한다. 물리/렌더는 동일 엔진 반복으로 변동을 측정하고 비교 기준을 고정한다. 신규 결과에 맞춰 기준을 수정하지 않는다.
5. 기존 Dataset은 Source·annotated·generated·subset/split·Resume 및 과거 형식별 표본을 선정한다. MiniVLA 전용 자료 변환은 제외한다.
6. [확인 목록](../docs/preimplementation-checks.md)의 ID별 구현 선행조건을 해제한다. 실제 새 writer 장애 시험 등은 구현 후 완료 조건으로 남긴다.

기존 실행이 실패하면 실패 자체를 기록한다. 근거 없는 성공 fixture를 만들거나 실행 불가를 검증 완료로 처리하지 않는다. 실제 장치 제어와 외부 업로드는 별도 승인된 시험에서만 수행한다.

### B02 조사 완료와 후속 구현 경계

[B02 보고서](../docs/b02-episode-resume.md) 및 [필드 대응 근거](../docs/evidence/b02/field-compatibility.json)를 D01/D03의 선행 자료로 사용한다. 기존 17개 HDF5 각 첫 Episode·612개 배열·영상/단위/phase, 원래 guard 25개와 Canonical/seed/history 근거를 확인했다. 새 Writer·실제 데이터 변환·시뮬레이터 Resume는 수행하지 않았다.

- D01은 recorded/derived/unavailable 구분, Isaac 요청값 누락·저장 target/engine 전달 dtype 차이·initial velocity 근거·snapshot 소유권·auto/manual/final event를 보존한다. B01 Annotation의 post tick/저장 frame 차이를 유지한다.
- D03은 검증을 복사/commit 전에 끝내고, 정책 identity 부재를 기본 SciPy/Strict로 채우지 않는다. 과거 SciPy + Best Effort도 신규 DLS와 다르다. seed/history/전역 budget·실제 pool 순서·partition을 검사하며 기존의 독립 Annotation/Evaluation replay를 검증된 continuation으로 확대하지 않는다.
- DATA-01/V8-04는 대표 근거 확보, DATA-03은 일부 근거 확보다. 새 Writer 장애/부하·새 참조 index 이동/공식 소비자 통합·실제 변환/재생은 해당 후속 구현의 완료 조건으로 남긴다. B01 Isaac DataGen 실패·Evaluation 비결정성과 DATAGEN-IK-01은 그대로 유지한다.
- B02 완료 후 다른 작업은 자동 시작하지 않는다.

### 확정된 DataGen IK 변경과 구현 시점

2026-10-25: 새 DataGen은 **Pinocchio DLS + Best Effort**만 사용한다. [SPEC의 고정 수치·안전 경계](../SPEC-simulation-workflows.md#datagen-ik-고정-계약)를 구현 기준으로 삼는다. SciPy IK·Strict/Hold 이관, Solver/Failure Policy 선택 UI·Recipe 필드, fallback/선택 계층은 계획에서 제외한다. B01은 변경 전 Reference로 보존하고 새 정책의 trace를 B01에 덮어쓰지 않는다.

- E05는 기존 Mimic reference/source 선택/offset/RNG 의미를 이관한다. 이 작업을 이유로 과거 IK dispatcher를 복사하지 않는다.
- E06 안에서 작은 단위로 진행한다: **a)** 기존 DLS + Best Effort 동일 입력 fixture 확인·공통 계산/안전 단위 검증, **b)** MuJoCo 연결·검증, **c)** Isaac 연결·검증. b/c는 공통 계산 계약 준비 후 독립 진행할 수 있고 완료에는 양쪽 증거가 필요하다. a는 generation/mimic.py 및 대응 시험, b/c는 해당 엔진 datagen/control 또는 MDP 및 대응 시험으로 분리하여 한 변경의 파일 수를 제한한다. 새 폴더·계층·상시 서비스는 추가하지 않는다.
- 관련 선행 확인은 DATAGEN-IK-01이며 전체 작업의 선행조건으로 확대하지 않는다. 계산 이관 전 원래 DLS/Best Effort 수식·모델/frame·측정 seed·limit·0.5 rad 경계 fixture를 확보한다. 실제 simulator 결과는 b/c에서 검증한다. 이 문단을 이유로 B03 등 다른 작업을 자동 시작하지 않는다.
- R01/R02는 IK 선택 필드 시작 차단·시스템 고정 설정 기록, D03/E06은 정책 identity가 다른 Resume 거부, U02/U04는 선택 UI 부재와 읽기 전용 진단 표시를 확인한다. 일반 YAML/IPC/UI mock 시험은 DataGen 전체 구현을 기다릴 필요가 없다.
- B01 SciPy + Strict 대비 trajectory/실패/성공률 변화는 승인된 변경으로 보고한다. 기존 DLS + Best Effort 계산 동등성과 별도 비교하며, StableGrasp/Placement·Calibration·recording 시점·기타 budget은 보존한다. 기존 strict 실패의 반복을 새 완료 기준으로 삼거나 새 정책 성공을 미리 가정하지 않는다.

이번 작업은 위 설계 반영만 수행한다. E06 및 새 정책의 실제 실행·양 엔진 시험은 미착수 상태로 둔다.

## 3. 전달 단계와 관문

| 단계 | 구현/재사용 범위 | 관문과 완료 증거 |
|---|---|---|
| P0 조사·Baseline | 기존 코드 변경 없이 수식·호출·환경·자료·UI 조사 | 관련 OPEN 항목의 근거 및 baseline identity, 부수 효과가 통제된 재현 명령 |
| P1 계약·순수 계산 | scene-package/task-functions, 보정 오프라인 계산 | Transform·보정·판정/배치 경계 대조; 공식/공통 의존 분리 |
| P2 저장·실행 기반 | episode-data, recipe-execution | old→new 매핑, commit 장애/Resume, 중복 실행/미저장 설정 차단 |
| P3 Builder·장치/엔진 연결 | 기존 재구성·정합·export, 양 엔진 구성·state, 장치 수명 | 이동 패키지 로딩·Calibration 적용, 초기 state 복원, mock/실물 검증 분리 |
| P4 단계별 Workflow | Source/Annotation/DataGen, 공식 LeRobot 변환/학습/Hub | 각 단계 독립 실행, 정상 실패/중단 의미, 공식 상호운용 |
| P5 평가·Curation·UI | sim/real eval, Real/Sim, 전체 화면 통합 | 단계별 성공 조건·실물 제한·영상/분포/선택·저장 Recipe 실행 |
| P6 통합 회귀 | 새 Task 등록·이동·Resume·장애·전체 기능 대응 | 11개 SPEC AC와 관련 검증 증거 전부, 누락/미검증 공개 |

P1/P2/P3은 시간상 전체 직렬 배치가 아니다. 앞 표의 준비된 하위 기능은 먼저 진행한다. 실물이 없으면 해당 검증만 BLOCKED로 기록하고 외부 Dataset 학습이나 순수 계산 검증은 계속할 수 있다. 전체 제품 완료라고 표시하지는 않는다.

## 4. 작업 분해와 변경 관리

[todo.md](todo.md)의 각 작업은 약 5개 이하의 파일 변경을 목표로 한다. 표의 범위가 이를 넘으면 착수 전에 하위 작업으로 분해하고 기존 ID를 부모로 보존한다. 수치 계산 변경과 UI/저장 변경을 한 작업에 섞지 않는다. 새 패키지 경로는 architecture.md를 그대로 사용한다.

한 작업의 순서: 선행 자료/계약 확인 → 의미를 검증하는 시험 준비 → 최소 구현 → 해당 검증 → 결과/차이 기록. 변경되지 않은 전체 시험을 근거 없이 반복하지 않으며, 연결된 계약 변경 시 소비자 회귀만 추가한다. 완료 체크에는 SPEC AC와 실제 증거가 필요하다.

실패 시 이전 완료 자료를 보존하고 신규 변환/실행 출력으로 재시도한다. 원본에 rollback 변경을 가하지 않는다. 필드 삭제는 매핑/삭제 이유가 있어야 하며 필요한 정보를 확보하지 못하면 변환을 중단한다.

## 5. 주요 위험과 대응

| 위험 | 대응 / 승인 필요 조건 |
|---|---|
| v8 callback/센서 시점 변경 | V8-01/02 trace 비교; MDP 재배치로 의미가 바뀌면 보고 |
| DataGen 고정 IK의 의도된 변화 | DLS + Best Effort 수식·안전 조건 동일 입력 대조, B01 SciPy + Strict 대비 영향 별도 보고; 성공 판정은 완화하지 않음 |
| Calibration baked/runtime 중복 | CAL-01 적용 graph·identity·횟수 대조 |
| Random 예산/engine collision 결합 차이 | V8-03 조사 후 보존; 미승인 재시도 변경 금지 |
| Native segment/공식 materialization의 영상/시점 손실 | DATA-01 매핑, DATA-02 장애, DATA-03 소비자, DATA-04 부하 검증 |
| 공식 LeRobot 지원/Resume 버전 차이 | 설치 버전 config/processor 대조; 자체 Trainer로 우회 금지 |
| 실물 timeout/중지 결과 불명 | ROBOT-01/02; 제어 재전송 금지·실물 시험 별도 |
| 기능 목록 누락 | 기존 버튼/CLI inventory에 보존/Recipe 대체/명시 제외 사유 전수 대응 |

## 6. 문서·명령 상태

정확한 목표 테스트 명령은 각 SPEC, 공통 환경/명령 규칙은 [spec-conventions.md](../docs/spec-conventions.md)에 있다. [S01](../docs/s01-scene-package.md)의 파일 계약과 [S02](../docs/s02-frames-calibration.md)의 transforms.py·보정 관계·회귀 tests를 구현했다. B00 조사와 [B01](../docs/b01-baseline.md)의 별도 공간 대표 실행, [B02](../docs/b02-episode-resume.md)의 읽기 전용 필드/guard 검증, [B03](../docs/b03-calibration-device.md)의 보정 수치/장치 mock 계약 조사를 수행했다. [T01](../docs/t01-task-registry.md)의 Workbench 명시 목록·Task 선언/파라미터/참조 검증과 패키징을 구현했다. [T02](../docs/t02-pick-place.md)의 순수 v8 판정/StableGrasp·등록·B01 phase 대조를 구현했다. [T03](../docs/t03-placement-reset.md)의 v8 bbox Fixed/Random·SE(3)/간격·seed/RNG·오류를 구현했다. [T04](../docs/t04-collision-contact.md)의 다면체/평면 접촉 배치도 구현·오프라인 검증했다. 곡면/비평면/native 변환 및 물리 검증은 완료로 표시하지 않는다. [D01~D04](../docs/episode-data-bundle.md)의 Episode 파일/영상·reader/migration·Resume/참조 Export와 대표 부하도 검증했다. [R01~R03](../docs/recipe-execution-bundle.md)의 Saved Recipe·Scene/Task/Episode 준비·별도 worker/claim/IPC·CLI도 구현했다. 실제 engine/학습/장치 runner·재생/Resume와 UI 연결은 미착수다. train Resume의 공식 output/config_path 검증은 L01에 남으며 일반 신규 출력으로 재해석하지 않는다.

B03은 RO01/RO02/RO03/P02/P03의 관련 선행 의미를 확보했지만 새 구현/실물 완료가 아니다. RO01은 raw/native/model·정수 양자화·limits-only binding·baked residual의 기존 fixture를 사용한다. RO02는 부분 연결/Precision.close 예외·configure 실패 후 torque enable·disconnect 실패 후 port 미해제·UI 종료의 effect/정리를 작은 mock 단위로 검증한다. RO03/P02/P03은 camera host 시각과 exposure를 구분하고 실제 장치/엔진 검증을 별도로 수행한다. 기존 Stop hold/단계별 명령 의미를 임의 변경하지 않는다. 이번에는 어떤 후속 작업도 자동 시작하지 않는다.

참조 스킬 planning-and-task-breakdown은 로컬 검색에서 찾지 못했다. 이번 계획은 제공된 spec-driven-development의 명시된 의존성·병행·검증 관문·작업 크기 기준으로 작성했다. 없는 스킬을 읽었다고 간주하지 않는다. 추가 아키텍처 선택은 하지 않았다.

2026-10-26 RO01~RO03: 명시 프로필/모델 증거 계산·Scene Encoder 연결, SDK 정수 목표/구체 장치 수명·cleanup/effect, CameraReader/시간·Capture snapshot 계약을 구현했다. 전체647개(신규76)·원래 수치 exact·wheel·보존을 검증했다. 실제 장치 AC03은 BLOCKED다. 기존 Stop hold/관측·명령 단위/기준 모델·B03 physical_verified=false는 유지한다. Snapshot 파일 publish·ProfileStore 활성화/UI·장치 Recipe runner·엔진 Real/Sim/Policy 연결은 미완료이며 이후 해당 작업의 범위로 관리한다.

2026-10-26 최종 C Native 전환: [구현·검증 보고](../docs/native-dataset-transition.md). 사용자 확정에 따라 자체 Episode별 HDF5/Index/Descriptor/Migration을 제거하고 공식 불변 HDF5 segment + 최소 Metadata·영구 Curation·명시 LeRobot materialization으로 교체했다. NATIVE-01/02/03의 파일·공식 CPU 소비자 관문을 검증했다. 과거 D/R/RO 보고서·증거는 보존하며 BU/E·실물·UI·Trainer 실행은 시작하지 않는다.

## BU01~BU04 완료와 다음 선행조건

2026-10-26 [Builder 묶음](../docs/builder-bundle.md)을 완료했다. 실제 저장 후보/scan·B03 정합·70파일 이동 package·MuJoCo/USD parser·Blender/EGL 정적 렌더·UI/CLI·전체692개 회귀·wheel/보존 근거를 남겼다. Native Dataset C 및 기존 계산 제품은 변경하지 않았다.

E01/E02는 독립 진행 가능하나 관련 Calibration/모델 identity·실제 collider/root/joint·동적 센서/카메라·initial restore를 각각 검증해야 한다. Builder의 reference_snapshot_only robot 표현을 이미 실행 가능한 articulation으로 취급하지 않는다. ASSET-FINGER-01 파일 closure/상대 payload 로딩은 확보했으며 runtime 접촉은 OPEN이다. E03/E04는 각 엔진 state 준비 뒤, E05는 저장 자료로 독립, E06은 공통 DLS + Best Effort 계약 뒤 엔진별 검증을 진행한다. 이번 작업에서 E 계열은 시작하지 않았다.

## E01·E02·E05 구현·실행 결과와 제한

2026-10-26 [엔진 묶음](../docs/simulation-engine-bundle.md): E02 실제 MuJoCo model/state/control·B01 trace/latch·이동 및 E05 pure Mimic 계획은 완료했다. E01의 실제 articulation·physics Step·카메라/센서·Finger/pad·restore 및 B01 grasp post221/pre222는 확인했으나 전체 수치 trace는 차이가 남아 AC01 관문은 OPEN/BLOCKED다. 기존 Isaac Evaluation 비결정성으로 이 차이를 자동 설명하지 않는다. 독립 Standards/Spec agent는 서비스 limit으로 실행되지 않아 리뷰 미완료다.

같은 BU03 신규 Revision/Manifest74파일을 양 엔진에서 사용했다. reference snapshot을 실제 robot과 중복 배치하지 않고 고정한 calibrated URDF/Collision source hash를 사용한다. 상세 근거·실제743개 회귀·wheel·원본 보존은 보고서에 연결했다. Native Dataset C 계약/제품은 변경하지 않았다.

다음 E03/E04의 MuJoCo 연결은 준비된 concrete ModelConfig/model/state/sample을 사용할 수 있다. Isaac 연결은 관련 미확정 수치/접촉/센서/pixel 영향을 먼저 검토한다. E05는 E06 공통 계산의 선행자료지만 새 DLS 계산/엔진 IK를 이번에 구현하지 않았다. E03/E04/E06은 자동 시작하지 않는다.

## E01 후속 물리 차이 진단

2026-10-26 [실제 비교·수정](../docs/e01-physics-diagnosis.md): imported finger instance collider3개 비활성화 누락 및 cup .002m offset override를 수정했다. 기존 v8에 당시 Source initial을 넣으면 B01 q가 exact 재현되며, Annotation에 재저장한 initial과 수십 nm 차이가 있는 조건을 별도 통제했다. 당시288-part 제품의 오차는 최대0.145632699rad/29.650773mm, Grasp post222여서 E01 수치/판정 보존은 OPEN이다. 동일 설정 반복은 exact였고 이 차이를 비결정성으로 분류하지 않는다. 두 축 patch 리뷰·744개 회귀·wheel·실제 Step/contact/restore/RGB 검증은 물리 보존 관문을 대체하지 않는다. 기존 hull은 진단용 실험뿐이며 제품 fallback/옵션을 추가하지 않았다. 관련 Isaac Workflow 전에 collider compound/cooking·pad 및 초기 상태 재현 범위를 해소해야 한다. E03/E04/E06은 시작하지 않았다.

## E01 v8 native Collision 보존 최종 결정·실행

2026-10-26 사용자 결정으로 Isaac288구성은 폐기하고 기존v8 실행USD의hull3/pad2/그룹/instance/joint 설정을 직접 package binding으로 이관했다. 새Revision의48Object/2Camera/Calibration은 exact이며 native closure/상대path·Manifest·이동을 검증했다. MuJoCo288경로는 그대로 유지했고 실제 E02 재생 비교값도 이전과 exact다. [현재 결과](../docs/e01-v8-collision-recovery.md): 당시 원본Source initial·target의388step q/qd·contact·Grasp221/pre222 latch를 복구했다. 신규 object는306 cup충돌 이후 최대1.197188790mm/tick310 Y 차이가 남고 동일설정반복은 exact다. fixed-target writes·rigid props·원래cupUSD 교체 실험은 잔차에 영향이 없어 state.py 또는 target pose 보정을 추가하지 않았다. E01 full numeric gate는 OPEN이며 E03/E04/E06은 자동 시작하지 않는다.


## 2026-10-27 — MuJoCo Workflow·E06-a

[구현 결과](../docs/mujoco-workflows-ik.md): E03/E04는 준비된 MuJoCo concrete model/state와 Native C·Recipe/worker를 연결했다. Source24·신규 Source388→실제 Manual/Auto Annotation·공식 Pool·영상/PTS·Resume/중단을 검증했다. E06-a는 기존 DLS 수식과 고정 Best Effort 공통 계산/identity만 구현했다. 기본 v8 Workflow 범위이며 선택적 Source signal/metric·Annotation 별도 metric은 명시 거부한다. 실물·Isaac E03/E04·E06-b/c·L 계열은 미착수다. E01 1.197188790mm 잔차와 독립 리뷰 OPEN을 유지한다. 다음 작업은 자동 시작하지 않는다.


## 2026-10-27 — Simulation Workflow 엔진 연결

[실제 결과](../docs/simulation-workflows-bundle.md): E06-b와 E06-c의 Fixed 단일 env 생성·Native publish·새 출력 Resume에서 각각 누적 성공2개/399 frame을 확보했다. E06-c는 새 앱의 단일 Episode Isaac Annotation q/qd/선택 robot force exact·post221/pre222 및 공식 Pool 관문 뒤 시작했다. E01 cube–cup1.197188790mm 잔차는 그대로다.

Isaac Source 실제 기록 및 fake 입력 production 수명, 단일 Episode Manual/Auto Annotation은 구현했다. 물리 장치/같은 앱의 환경 재생성은 미완료다. 실제 R03 Isaac child의 terminal 이전 fast shutdown 오류는 공식 fast_shutdown=False로 수정했다. Annotation 및 DataGen/Resume child가 terminal completed로 끝남을 재검증했다. 복수 Episode Annotation은 복원 동등성 확인 전 차단하고, Isaac Random DataGen은 과거 persistent per-env RNG/continuation 확인 전 거부한다. MuJoCo v8 uniform probe의 기울어진 Support 위반은 run 중단으로 남겼으며 sampling/높이를 자동 보정하지 않는다.

B02 stored float64 DataGen command와 실제 float32 Isaac payload를 분리했다. 직전 실제 적용 payload 대비 finite/limits/>.5rad guard, post-step tracker/pre-step 기록, 최소 Native Metadata를 유지했다. L03의 공식 Dataset/action 매핑 검증은 다음 독립 후보이며 L/P/C/U/X는 시작하지 않았다. 전체 E03/E04/E06 AC 체크는 남은 관문을 기준으로 보류한다.


## 2026-10-27 — L03 공식 Dataset·Action 계약

[검증 보고](../docs/l03-lerobot-dataset.md): 기존 Native C materialization을 data/lerobot.py 안에서 재사용하여 실제 생성4 Episode/1596 frame을 공식 LeRobot0.4.1 Dataset으로 변환·Merge했다. pre-step measured model rad→observation.state, 기록된 float64 joint_targets→action이며 actual applied/측정 post-state/IK를 정답으로 대체하지 않는다. 공식 __getitem__/DataLoader·영상 offset·통계·ACT/SmolVLA processor/tokenizer 및 영구 Curation train152/val180frame의 격리를 검증했다. MP4는 재인코딩 없이 공유한다.

동등 Scene/Calibration/model/joint/unit/camera/control 계약만 Merge하고, 하나의 canonical resumed Dataset/engine에서 선택을 파생한다. creator가 불명한 Archive·동일 engine의 독립 Resume branch 복수 Merge는 차단한다. Native C·Curation 저장을 새 포맷으로 바꾸지 않았다.

L03 Dataset 범위 완료와 실제 학습/추론 준비 완료를 구분한다. SMOL-PAD-01은 공식 action_is_pad와 SmolVLA.forward actions_id_pad 불일치로 L01 기본 chunk loss-padding 관문이다. MuJoCo float32 Policy 출력의 wrist 상한 초과(각4frame), 현재 Follower command phase binding 부재/초기 motor-range 거부는 L02/P 제어 계약 관문이다. target/허용 오차/SDK를 바꾸지 않았고 L01/L02/L04·P/C/U/X는 시작하지 않았다. E01 잔차와 E 계열 Random/복수 Episode OPEN은 그대로다.


## 2026-10-27 — L01 ACT·L02 Policy/독립 Validation

[L01/L02 결과](../docs/learning-bundle.md): 기존 L03 선택 Dataset·Recipe/Runner를 재사용해 official CLI ACT scratch2step/누적4step Resume, 닫힌 checkpoint identity·optimizer/scheduler/RNG 복원, 취소와 기존 정상 checkpoint 보존을 검증했다. 학습 config는 실행 소유 bytes로 고정하고 Resume는 공식 checkpoint 배치의 JSON 사본/불변 state hardlink를 사용한다. 원본 설정/가중치를 수정하거나 custom Trainer를 넣지 않았다.

L02의 실제 ACT/processor·후처리·chunk/Reset 및 독립 val180batch를 검증했다. train/val source Episode UID 중복0이고 checkpoint 불변이다. 전체832개·wheel·독립 Standards/Spec 리뷰/원본 보존 통과(낮은 cancel ACK 선행 의미는 보고서에 남음).

SMOL-PAD-01은 실제 forward에서 padded action이 loss에 포함되어 Training BLOCKED다. SDK 키 수정/monkeypatch/chunk1 우회는 없다. MuJoCo strict float32 경계와 Follower command binding/motor-range·E01 잔차·E Random/복수 Episode OPEN은 유지한다. P01은 추론 기반은 준비됐지만 strict 제어 검사/실제 Rollout이 별도 필요하다. L04/P/C/U/X는 시작하지 않았다.


## 2026-10-27 — P01 ACT 실제 Simulation Policy Rollout

[P01 결과](../docs/p01-simulation-rollout.md): L02 ACT4step checkpoint·기존 E01/E02·T02·Native C·R03을 연결해 양 엔진 실제 Policy/RGB/state/Step/Task/기록을 검증했다. 최종 canonical resumed Dataset은 엔진별2 Episode/120step·모두 max_steps 실패다. 실제 취소 각1회는 부분 Episode를 publish하지 않았다. 성공 Episode나 성능 수렴을 요구해 Action/Scene을 수정하지 않았다.

사용자 확정 정책으로 어떠한 clipping/rate 평활화/Hold도 추가하지 않는다. 원 Action과 실제 float32/64 payload를 원래 rad 한계로 strict 검사한 뒤 기존 engine preflight도 호출한다. v8 ActionGuard의 clip/rate 제한을 복사하지 않은 차이를 명시한다. 성공 종료는 Placement이고 latched grasp/transport는 별도 지표다.

Native Evaluation은 완료 실패 Episode와 attempt를 보존해 새 출력/worker로 이어간다. Policy/processor/training Dataset·Scene/model/Task/고정Recipe 실행 계약이 다르면 차단하며 미확정 claim은 자동 재시도하지 않는다. 최종846개·wheel·독립리뷰·원본 보존 통과. 물리 잔차·Random/같은Isaac앱 여러Episode·Smol·strictfloat32/Follower OPEN을 유지하고 P02/P03·L04/C/U/X는 시작하지 않았다.


## 2026-10-27 — C01/C02 Data Curation

[C01/C02 결과](../docs/curation-bundle.md): 기존 Native C·L03 선택/공식 materialize/merge를 재사용하고 data/curation.py에서 검토/outcome·원 run attempt와 선택 scope·분포/비교·정확한RGB/PTS·참조좌표/m·split seed/rule·Revision lineage/relocation을 보강했다. 새 Manager/Dataset/중복 저장 계층이나 UI는 없다.

실제 양 엔진4 Episode의 V1/V2·선택구간·train66/val110frame 공식 소비, 원 Episode UID 격리, 독립 Export·이동과 원본 불변을 검증했다. 과거 실제50 Episode/21284frame을 소유 임시 Native로 한 번 준비해 분포 .175s·split/save .744s를 측정했고 기존 v8 배정이 exact였다. unknown 단위/누락 자료는 추측하지 않는다. 전체868개·wheel·독립 리뷰·보존 통과.

UI는 준비된 일반 함수를 직접 호출할 수 있지만 조작/그리기/thread/취소/종료 흐름은 U01~U04의 별도 관문이다. 실제 E01 잔차·Random/복수 Episode·SmolVLA·Follower binding/실물 OPEN은 유지한다. C01/C02에서 중단하고 U/X/P02/P03은 자동 시작하지 않는다.

## 2026-10-27 — Random Pose 단순화·신규 Scene 초기 기준

사용자 승인에 따라 신규 DataGen Random은 Seed 없는 Workspace Pose 함수로 바꿨다. 과거 절의 persistent Pose RNG continuation 관문은 이 신규 규칙에 적용하지 않는다. 기존 Seed sampler/Source·Mimic·Training·Native Attempt identity는 보존한다. 실제 v8 Table 경사2.604156329°와 legacy World sampler의 높이/범위 차이를 재현했고 원본 수평화 없이 Marker 로컬150mm·surface gap24mm로 계산했다.

양 엔진 실제 Random과 새 worker/출력 Resume·Fixed 회귀, Geometry/native dtype 경계와 미래 Scene의 opt-in 수평 validator는 [결과](../docs/random-placement-horizontal.md)를 따른다. 같은 Isaac 앱 여러 Reset/복수 Annotation·E01 물체 잔차·SmolVLA/Follower/실물 관문은 유지한다. UI·v9 생성/Export·실제 Calibration·다음 구현은 이번 범위가 아니다.

## 2026-10-27 Phase0·U01~U04·X01 UI 결과

[실제 UI 보고](../docs/workbench-ui-bundle.md)의 최신 사용자 범위를 적용했다. 기존 Recipe/Worker/Native/엔진/공식 Trainer를 직접 연결하고 Qt와 backend의 기존 인터프리터를 분리 사용한다. Phase0 no-clipping은 원 command와 실제 payload를 원 URDF limits로 strict 검사하며 알고리즘 내부 projection은 보존한다.

MuJoCo의 저장 Source→Auto/Manual Annotation→Fixed/Random DataGen/새 출력 Resume→Curation/공식 Export→ACT2~4step/평가를 실제 UI로 확인했다. Isaac 실제 RGB/Random 실패 attempt→fresh worker Resume/평가·취소도 확인했으나, 보존 Source 및 새 DLS 명령의 float32 상한 초과로 Annotation/DataGen 성공 연쇄는 BLOCKED다. U/X 전체 완료로 체크하지 않는다. 실물/Smol/v9/동일 Isaac 앱 Reset/E01 잔차는 기존 OPEN이다. 후속은 strict 정책을 유지하는 별도 입력/명령 경계 결정이며 이번 작업에서 원본을 보정하거나 다음 기능을 자동 시작하지 않는다.

## 2026-10-28 Position Saturation 후속 복구

현재 최종 command 정책은 [Saturation 보고](../docs/position-saturation-recovery.md)와 갱신된 Interface를 따른다. 과거 P01/UI No-Clipping 기록은 역사적 실행 근거로 남으며 현재 정책으로 적용하지 않는다. 실제 Isaac Annotation388frame/Random DataGen399step의 상한 변환 차단을 해소하고 Native/공식 소비자를 확인한다. 기존 URDF/Physics/Task·Native 원본은 수정하지 않는다. 전체 플랫폼/실물/장시간/Smol/v9는 별도 관문이며 이번에 자동 시작하지 않는다.

## 2026-10-28 — 요청된 확장 묶음 결과

[Resume/Multi-Env/Smol/Preview](../docs/resume-multienv-smolvla-preview.md)는 직전 Saturation을 재사용해 R01(추가 수집)→M01/M02(실제 독립 환경)→L04(고정 Smol patch/공식 학습)→U05(최신 RGB)→X02를 연결한 결과다. 기존 같은 번호 작업의 의미는 보존한다.

Native 추가/producer-history·unknown intent 경계를 먼저 검증하고 MuJoCo native state/thread, Isaac official vector/partial reset, 모델별 queue와 loss/Checkpoint identity를 연결했다. original→curated→official materialization은 기존 함수를 사용하며 bulk 포맷을 추가하지 않았다. 동등한1-env Fixed 수치와Task/phase·Saturation은 유지했다. 실제 matrix의 Placement 성공0은 smoke 학습 결과이며 실행 실패로 왜곡하지 않는다. FPS·메모리/범위 한계는 통합 결과를 따른다. 기존 E01 잔차·실물·v9/장시간 관문을 해제하거나 다음 묶음을 자동 시작하지 않는다.


## 2026-10-28 — Architecture completion (current request)

Read-only comparison baseline: Studio8a8210d, original Builderad018a0, SO101875e64f; GitHub main representative blobs match local originals. Work on architecture-completion branch; no automatic push.

- [x] Phase1a: move engine-neutral recording/command helpers; preserve math/phase.
- [x] Phase1b: Native publish/Task helpers and Prepared coverage; actual1/4-env regression.
- [x] Phase2: separate Builder scene/evidence/capture/candidate/scan responsibilities without changing API/exports.
- [x] Phase3a: installed official Policy registry/factory + Trainer fine-tune/Resume.
- [x] Phase3b: pinned Hub Dataset/Policy download and explicit opt-in upload; UI/Runner; no smoke uploads.
- [x] Phase4: offline/fake device/Capture/Calibration/real-policy contract and truthful stage availability.
- [ ] Phase5: stage-scoped UI output defaults and input selection; no existing-data relocation.
- [ ] Phase6: actual engine1/4 flows, official consumers/train/Resume/evaluation, full suite/wheels/reviews/preservation; feature-state report.

Each Phase precedes the next; isolate thin slices, run focused checks, preserve SDK/original/evidence. Status meanings: VERIFIED(actual), CODE_READY(wired/unexecuted), PARTIAL, UNSUPPORTED, EXCLUDED. Hardware, uploads, newv9/real calibration are not executed by smoke validation.
