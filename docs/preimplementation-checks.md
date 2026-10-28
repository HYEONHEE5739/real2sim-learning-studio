# 구현 전 확인 목록

작성: 2026-10-25. [기능 범위 색인](../CAPABILITY-MAP.md)의 선행 확인 자료다. 기존 [Interface](interfaces.md) 방향은 유지한다. **v8의 대표 조건은 B01에서 근거를 확보했으며, 실물/Calibration·저장 및 남은 실행 범위는 OPEN이다.** 버전 사전 조사의 정적 근거 확보와 실제 실행 검증은 아래 별도 상태로 구분한다. 기존 조사 사실은 migration-validation.md에 근거하며 문서 작성만으로 검증 상태를 승격하지 않는다.

## 최신 버전 조사 — 개발 선행조건에서 제외

2026-10-25 최종 결정: 새 플랫폼 개발 기준은 **Isaac Sim5.1 / Isaac Lab2.3 / LeRobot0.4.1 / MuJoCo3.3.7**이다. 업그레이드는 진행하지 않는다. 최신 버전 조사는 참고 이력이며 신규 환경 분리·분리 추론·업그레이드 대응 코드는 개발 범위에 포함하지 않는다. 기존 UI/엔진 worker의 필요에 따른 프로세스 분리는 유지한다.

근거: [버전 호환성 조사](version-compatibility.md), [증거](evidence/version-compatibility/validation.json).

| ID / 상태 | 완료 또는 필요한 근거 | 차단 범위 |
|---|---|---|
| V-COMPAT-01 정적 근거 확보 | 공식 tag/전체 의존성·현재 설치 graph, 명시 충돌/metadata 해결 결과 | 설치/실행 완료를 뜻하지 않음; B01은 기존 환경 사용 |
| V-COMPAT-02 적용 안 함(업그레이드 취소) | 별도 환경 정확한 wheel/lock·docopt build·native import·GPU/renderer 확인 | 신규 버전 실제 채택 |
| V-COMPAT-03 적용 안 함(업그레이드 취소) | Dataset reader/변환·Policy/processor/action·공식 학습 입력 대조 | 새 학습/추론의 자료 호환 완료 |
| V-COMPAT-04 적용 안 함(업그레이드 취소) | 기존 B01 대비 신규 engine v8 Scene/Calibration/contact/stage 회귀 | 신규 engine을 v8 지원 완료로 표시 |
| V-COMPAT-05 적용 안 함(업그레이드 취소) | 분리 추론의 동기 시점·지연·VRAM/throughput | 환경 배치 최종 확정 |
| ASSET-FINGER-01 OPEN(runtime 적용/접촉) | [BU03](builder-bundle.md)에서 실제 Finger/Contact/source 모델 포함 70파일 Manifest·native closure·상대 payload 로더·이동 후 공식 MjModel/USD parser 확인. 원본 접근 차단 및 source hash 대조 통과 | E01/E02의 실제 robot collider 설치·접촉/rollback·물리 실행. 파일/parser 성공으로 해제하지 않음 |

## 관리 방식

후속 [상세 SPEC 색인](../CAPABILITY-MAP.md)과 [개발 계획](../tasks/plan.md), [작업 목록](../tasks/todo.md)에서 이 ID를 참조한다. 11개 범위 승인과 명세 작성은 OPEN 항목의 해제를 뜻하지 않는다. 관련 하위 기능의 구현 전에 필요한 의미 확인만 차단하며 독립 기능의 병행 작업은 허용한다.

- 상태: OPEN → 조사 중 → 근거 확보 → 확인 완료. 근거 확보만으로 확인 완료로 바꾸지 않는다.
- 확인 완료에는 실제 원본 파일/함수·버전, 대표 입력, 관찰 결과, 보존할 의미, 수용 기준, 차이·영향과 검토 결과가 필요하다.
- 기존 동작이 명세와 다르면 명세를 기준으로 원본이 틀렸다고 판단하지 않는다. 승인된 변경인지 대조하고 미승인 의미 변경은 사용자 결정 전 보류한다.
- 차단은 해당 의미에 의존하는 구현에만 적용한다. 무관한 문서·조사 작업을 전체 중단시키지 않는다.
- 원본 실행이 새 파일을 원본 폴더에 쓰지 않도록 출력 경로와 부수 효과를 먼저 확인한다. 장치 제어가 필요한 시험은 별도 실물 시험 승인 후 수행한다.

## v8 실행·계산 보존

| ID / 상태 | 확인할 사항과 기존 조사 근거 | 해제에 필요한 증거 | 차단 범위 |
|---|---|---|---|
| V8-01 대표 근거 확보 | native Source/Annotation, workflow DataGen/Evaluation의 실제 dtype·배열·tick·pre/post-step·센서 갱신 경로 | 엔진·단계별 호출표, 동일 입력 trace, 중간값/최초 성공 tick 및 반복 변동 측정 | task-functions의 엔진 연결, simulation-workflows, policy-evaluation |
| V8-02 대표 근거 확보 | grasp.py StableGrasp와 Isaac 평가 contact 추출. 1e-4 N/0.01 N 등 기존 조사값이 각 실행에서 쓰이는 위치 | 실제 생성 sensor/body pair·threshold·호출 시점·reset/latch 수명 확인; 단계별 경계 fixture | contact binding 및 성공 판정 연결 |
| V8-03 대표 근거 확보 | reset.py sample, tasks.py validate_reset_pose, MuJoCo reset_object_poses의 1000회·rollback·관통 검사 결합 | 후보 추출과 엔진 적용 실패의 재시도 경계/횟수·순서·RNG 소비·3mm 결과 기록 | placement 및 엔진 reset. Interface의 동일 예산 표현을 검증 없이 v8에 적용 금지 |
| V8-04 대표 근거 확보(B02) | Native Source/current DataGen·구형 combine·없는 Annotation/Evaluation continuation, seed·budget·partition·IK identity 구분 | B02 guard/카운터/기록 근거 확보; 실제 신규 Resume·병렬 RNG·누락 정보 처리는 후속 구현 검증 | episode-data Resume, DataGen 이어 생성 |

### B01 확인 범위 — 2026-10-25

[B01 결과](b01-baseline.md), [수치/배열/영상](evidence/b01/captured-baseline.json), [경계 fixture](evidence/b01/boundary-fixtures.json), [접촉/rollback](evidence/b01/contact-reset-fixtures.json), [검증](evidence/b01/verification.json)에 대표 입력과 실제 결과를 고정했다. 세 항목을 전 범위 확인 완료로 승격하지 않는다.

- V8-01: env=1, seed=1047에서 Source 24 frame, Annotation 388 frame 양 엔진 실행 및 반복 확보. MuJoCo DataGen 399 step 성공, Isaac DataGen 2 step 후 동일 strict IK 실패. 실제 ACT 평가는 양 엔진 60 step 실패 Episode를 정상 기록했다. Annotation은 post-step grasp tick 다음 pre-step frame에 latch를 저장한다. Isaac 평가/영상 반복 차이의 원인은 미확정이며 임의 tolerance를 승인하지 않는다. 여러 env/seed/Task·장기 성공 평가 trace는 없음.
- V8-02: 기존 StableGrasp 15 sequence·기존 unit 시험과 contact 추출 9 경계 입력 확보. Native sensor >1e-4 N / Evaluation direct view >0.01 N 및 fallback 차이를 코드와 제어 입력으로 확인했다. MuJoCo 지정 body pair와 dist≤0을 보존한다. 실제 센서 raw force 전체 분포·다중 env 검증은 남는다.
- V8-03: 원래 four_anchors와 uniform의 RNG/높이, uniform 1,000회 소진 확보. MuJoCo 엔진 적용 실패는 support/penetration 오류 후 qpos/qvel rollback이고 이 API에서 재추출하지 않는다. sampler 재추출과 엔진 적용 실패를 같은 계약으로 취급하지 않는다. Interface의 일반 collision 후보 예산으로 v8 동작을 자동 변경하지 않으며 engine별 재시도 연결은 이 근거를 기준으로 확정한다.
- B01은 V8-04·CAL/ROBOT/DATA를 완료 처리하지 않았다. 이후 [B02](b02-episode-resume.md)의 대표 필드/Resume 근거와 [B03](b03-calibration-device.md)의 보정·장치 오프라인 근거를 확보했으며 상태는 아래와 같다. 새 구현/실물 회귀가 완료된 것은 아니다.

### DataGen IK 결정 후 검증 범위 — 2026-10-25

새 정책은 **Pinocchio DLS + Best Effort 단일 방식**으로 확정했다. 이는 미정 선택지가 아니라 승인된 B01 대비 변경이며 [상세 SPEC](../SPEC-simulation-workflows.md#datagen-ik-고정-계약)에 수치·안전 경계·시험을 정의한다. 기존 B01 SciPy + Strict의 실패를 새 구현이 그대로 재현할 필요는 없으며, 새 정책의 성공도 아직 확인하지 않았다. B01 문서·증거를 수정하지 않는다.

| ID / 상태 | 구현 단계에서 필요한 확인 | 차단 범위 |
|---|---|---|
| DATAGEN-IK-01 OPEN(정책 확정·실행 미검증) | 기존 DLS + Best Effort 동일 입력 fixture, 수식/파라미터·측정 seed·모델/frame·finite/limit·직전 적용 팔 명령 >0.5 rad 거부·유효 미수렴 적용, 양 엔진 state/기록·Task 채택·Resume·선택 옵션 부재 | DataGen E06의 고정 IK 계산/양 엔진 완료 판정. 무관한 Source/Annotation·독립 기능을 차단하지 않음 |

기존 함수와 fixture를 대조하는 선행 확인은 DataGen 구현 착수 때 수행하고, 구현 후 회귀 결과와 구분한다. IK API·수치 정책을 새로 고르는 질문은 하지 않는다. B01에서 얻은 판정/Calibration/기록 시점 보존 요구는 유지하고, 승인된 IK 궤적 차이를 그 보존 검증의 면제로 사용하지 않는다. 이번 문서 변경에서 구현·시뮬레이션·장치 실행은 하지 않았다.

## 실물 로봇·Calibration Interface

| ID / 상태 | 확인할 사항과 기존 조사 근거 | 해제에 필요한 증거 | 차단 범위 |
|---|---|---|---|
| ROBOT-01 대표 mock·코드 근거 확보(B03), 실물 OPEN | connect/activate/send/stop/close 및 CameraReader의 수명·SDK 부수 효과·UI 종료 분기 | B03의 원래 메서드/fake bus 시험 확보. configure 예외의 torque 재활성화·cleanup 누락·port close 실패·UI/SDK timeout 실제 종료는 RO02/U03 검증 필요 | 관련 mock 구현 선행 의미 확보; 실물 제어/종료 완료 판정은 계속 차단 |
| CAL-01 대표 오프라인 근거 확보(B03) | 실제 활성 6관절 프로필·limits-only 모델 binding·raw/native/model·정수 goal·v8 baked residual | 60개 표본·12개 거부·6관절 URDF 회전 대조. 새 구현/변환·USD/엔진 적용 회귀와 물리 정합은 미완료 | 순수 계산 구현 선행 의미 확보; 신규 보정/패키지 동등성 완료와 실물 검증을 대체하지 않음 |
| CAL-02 대표 수치·코드 근거 확보(B03), 엔진/실물 OPEN | optical/mount/raw K/virtual K·PhysX/Fabric pose 소유·host read 시각 | 23개 camera/시간 경계 검사. 실제 exposure/buffering·픽셀 정합·새 엔진 pose/복원은 RO03/E01/E02 검증 필요 | 오프라인/mocked 카메라 계약 구현 가능; capture/real_sim 실물 및 엔진 연결 완료는 미검증 |
| ROBOT-02 코드·시작 자세 근거 확보(B03), 실물 OPEN | 공식 processor→finite model action→URDF clip→strict inverse/encode/send; 결과는 실제 task_success 미측정 | float64 hold preflight·mapping 검사 근거 확보. 실제 Policy/action·SDK 도달/중지·카메라 stale 동작은 P03 검증 필요 | 실물 평가 계약 구현 가능; 실제 제어·성공 검증 완료는 차단 |

장치 계약은 현재 interfaces.md의 범용 실행 계약만으로 완료된 것으로 간주하지 않는다. 위 조사 후 구체 signature와 단위·자원 소유·오류 상태를 robot-operations 명세에 넣고 Interface 문서에서 연결한다. 새로운 장치 추상 계층을 만들라는 요구가 아니다.

### B03 확인 범위 — 2026-10-25

[B03 보고서](b03-calibration-device.md), [검증 증거](evidence/b03/verification.json), [구체 Interface](interfaces.md#11-b03에서-확인한-장치calibration-경계)를 따른다. 기존 오프라인 시험 75개와 카메라/장치 probe 각 23개를 통과했다. 실물 로봇·카메라·보정 장치 연결, 실제 torque/goal·Exposure·신규 엔진 실행은 하지 않았다. REVIEWED_MANUAL·physical_verified=false 및 v8 UNVALIDATED를 승격하지 않는다.

Stop의 last-goal hold와 일반 Disconnect의 torque release, readonly Calibration disconnect의 torque 유지가 다르다. SDK configure 실패의 finally enable_torque, torque release 실패의 port 미해제 가능성, Leader/Precision cleanup 누락 및 real send 이후 Sim 오류는 B03 §7의 후속 검증 항목이다. 오류를 일괄 not_applied/완료로 처리하거나 자동 명령 재전송하지 않는다. 기존 수식·의미를 보존하면서 종료 실패를 새 구현에서 해결/검증하는 범위는 RO02/P02/P03에 남으며 이번에 구현하지 않았다.

## Episode 저장 변경과 호환성

### S02 보정·좌표 계약 구현 상태

2026-10-25 [S02](s02-frames-calibration.md)에서 reference Frame Graph/SE(3)와 Calibration dependency/phase/order·모델/관절 identity·중복 선언을 구현했다. v8의 실제 mapping fingerprint와 Geometry 곱 순서를 오프라인 대조했다. file-based fit binding은 load_scene이 실제 파라미터 bytes까지 확인하며 direct validate_scene의 파일 미확인과 구분한다. 이후 RO01~RO03에서 새 Encoder/fitter/limits-only 계산과 fake 장치 수명·Capture 준비 계약을 구현/검증했다. CAL-02의 실제 센서·현재 pose, ROBOT의 실제 제어/종료 및 ASSET-FINGER-01의 native closure/엔진 로딩은 계속 미완료다. S02 성공으로 이 상태를 승격하지 않는다.

| ID / 상태 | 확인할 사항과 기존 조사 근거 | 해제에 필요한 증거 | 차단 범위 |
|---|---|---|---|
| DATA-01 파일 왕복 검증(D01~D04), 엔진 재생 OPEN | 기존→새 논리 필드, dtype·단위·pre/post·requested/applied·initial/event 가용성 | 17개 첫 Episode·612개 배열·영상/계약 검사. 실제 신규 변환·왕복 재생·누락 처리 검증은 D01 이후 | 새 저장 Schema·writer·migration의 관련 필수값 및 검증 |
| DATA-02 로컬 장애 관문 통과(D02), 엔진/전원/NFS OPEN | commit 순서·영상 종료·index 갱신·중단 및 원본 불변 | 응답 유실·writer 종료·disk full·video 실패·publish 후 index 전 장애의 시험 설계와 구현 후 결과; 완료 누락/중복·고아 파일 처리 확인 | writer 채택. 설계 시험 기준 먼저 확정, 구현 후 장애 시험 통과 전 완료 금지 |
| DATA-03 파일 Resume/참조 검증(D03), 공식 소비자 OPEN | 기존 Reader/Resume/lineage·pool 순서·partition 및 새 참조 계약 | B02의 읽기/guard 근거 확보. 새 index 참조 이동·독립 export·LeRobot/Curation 통합은 미검증 | Resume/curation/변환 통합 |
| DATA-04 대표 부하 측정(D04), 전체 엔진 부하 OPEN | Episode별 파일 수·매 commit hash/index 갱신 비용·비동기 copy/backpressure | 기존 자료 규모·해상도·빈도로 대표 부하 정의, 원본과 새 경로 처리량/메모리/기록 손실 비교. 한도는 측정 근거로 확정 | 저장 방식의 최종 채택; 성능 문제를 이유로 미완료 데이터 노출 금지 |

2026-10-26 [D01~D04 증거](episode-data-bundle.md)에서 Common 17개/612 배열·Canonical 9개/104 배열, 영상 bytes/phase, index 장애·강제 종료, 엄격 Resume·참조 이동/독립 Export, 5/50 Episode 및 두 카메라 부하를 검증했다. 위 해제 근거 열의 기존 목표 중 파일/오프라인 부분만 충족했으며 엔진 재생·공식 LeRobot/Curation 연결·장시간/다중 worker·전원 장애는 계속 OPEN이다. 성능 비용을 보고하고 검증을 생략하지 않았다.

이관 호환성은 과거 프로그램이 새 형식을 그대로 읽어야 한다는 뜻이 아니다. 새 플랫폼의 모든 필요한 소비자가 변환 결과를 같은 의미로 읽고 재생할 수 있어야 한다. 구형 reader를 무기한 유지하거나 불필요한 양방향 writer를 추가하지 않는다. 기존 원본은 비교·복구용으로 보존한다.

### B02 확인 범위 — 2026-10-25

[B02 보고서](b02-episode-resume.md) 및 [검증 증거](evidence/b02/verification.json)를 따른다. Native Isaac Source의 requested 누락, Isaac의 저장 target/engine 전달 dtype 차이, default/measured initial velocity, Source에서 상속된 opaque snapshot 소유권, 자동/수동 event와 최종 post-step 매핑을 구분한다. 과거 데이터는 누락을 숨겨 채우지 않는다.

원래 Resume guard/partition/lineage 25개 관찰과 seed/history 카운터 검사를 수행했지만 **새 Resume 구현 검증은 아니다**. 기존 IK 누락의 기본값 대체·코드 identity 미검사·history 검증 전 복사 호출은 새 prepare_resume에 이관하지 않는다. 과거 SciPy + Best Effort도 새 DLS와 다른 계약이다. B01 Isaac DataGen 실패와 Evaluation 비결정성은 그대로 유지하며 DATAGEN-IK-01·CAL/ROBOT·DATA-02/04를 해제하지 않는다.

## 증거 기록 양식

각 ID의 후속 조사 결과에는 다음을 남긴다: 상태 / 조사한 원본·버전 / 기존 호출 경로 / 입력 fixture 위치·hash / 측정 또는 코드로 확인한 결과 / 승인된 변경과의 차이 / 영향받는 기능 ID / 해제 여부·이유 / 남은 실행 검증.

코드 조사로 해제할 수 있는 구현 선행조건과 구현 후에만 수행 가능한 회귀 시험을 구분한다. 아직 구현하지 않은 writer의 장애 시험을 구현 착수 조건으로 요구하는 순환은 만들지 않는다. 다만 보존할 의미와 시험 기준을 모른 채 writer부터 만들지는 않는다.

### RO01~RO03 후속 관문 — 2026-10-26

[RO 묶음](robot-operations-bundle.md)에서 CAL-01 계산/모델 binding·Scene Encoder 연결, ROBOT-01 대표 fake 수명/공식 SDK 실패 경로·자원 정리, CAL-02 host-time/안정성/Capture 준비 계약을 검증했다. 전체647개(신규76)·B03 수치 exact·wheel/보존 통과다. CAL-01/02·ROBOT-01/02의 실물/engine/Policy/UI 부분은 OPEN이며 AC03은 BLOCKED다. 실제 torque/register/port 종료·camera exposure/동기·물리 Stop latency는 장치를 연결하지 않아 미검증이다. 이 결과로 B01 미확정·B02 저장/Resume·ASSET-FINGER-01을 해제하지 않는다.

### Dataset Native 전환 관문 — 2026-10-26

[비교 결과](dataset-storage-review.md). C가 우선 후보이며 현재 제품 교체는 아래 관문을 해결할 때까지 보류한다. 기존 D/R/RO 증거를 삭제하거나 완료 검증을 소급 변경하지 않는다. 관련 저장/학습/Curation 소비 경계에만 적용한다.

| ID / 상태 | 실제 근거 | 해제할 결과 |
|---|---|---|
| NATIVE-01 BLOCKED | 설치0.4.1에서 episodes=[0]/[49] 모두50개 전체 노출. 수치 physical split은 정상 | 공식 학습까지 train/val membership·통계/영상 연결 정확, 불필요한 대용량 복제 없음 |
| NATIVE-02 BLOCKED | HDF5 오류 후 partial success 노출, LeRobot SIGKILL 후 footer/Metadata 불일치 | 닫힌 Native 자료 불변 publish·공식 Reader 복구·미완료 노출0·Episode 경계 Resume/IK/attempt 검증 |
| NATIVE-03 BLOCKED | 공식 기본 저장이 H264→AV1 재인코딩,8frame RGB 차이 재현 | 기존MP4 packet/RGB/PTS/FPS/해상도 보존과 공식 Dataset read/feature stats/shard Metadata 일치 |

새 제품 Native 구현은 없으며 BU/E 작업을 자동 시작하지 않는다.


## 최종 C Native 전환 관문

2026-10-26 최종 C Native 전환: [구현·검증 보고](native-dataset-transition.md). 사용자 확정에 따라 자체 Episode별 HDF5/Index/Descriptor/Migration을 제거하고 공식 불변 HDF5 segment + 최소 Metadata·영구 Curation·명시 LeRobot materialization으로 교체했다. NATIVE-01/02/03의 파일·공식 CPU 소비자 관문을 검증했다. 과거 D/R/RO 보고서·증거는 보존하며 BU/E·실물·UI·Trainer 실행은 시작하지 않는다.

NATIVE-01: 명시 LeRobot materialization/공식 factory·DataLoader 선택 격리. NATIVE-02: 불변 segment·partial/OSError/SIGKILL·정확 identity/attempt Resume. NATIVE-03: 원 MP4 bytes/offset/실제 decoded RGB. 엔진/정책/실물·UI 종단 시험은 여전히 OPEN이다.

### BU01~BU04 파일·정합 관문

2026-10-26 [Builder 묶음](builder-bundle.md)에서 기존 정합·후보·입력 의미와 신규 패키지 closure/이동·공식 parser/정적 렌더·UI/CLI를 검증했다. 원본 보존 및 기존 Native Dataset C 계약을 유지했다. 위 S01/S02/RO 시점의 미완료 서술은 당시 결과이며, 현재 파일 관문은 이 결과로 보완한다. CAL-02의 실제 동적 센서/카메라·ROBOT 실물·ASSET-FINGER-01의 실제 collider/접촉은 계속 OPEN이다.

### E01·E02 실제 collider·physics 기반 결과

2026-10-26 [엔진 묶음](simulation-engine-bundle.md)에서 동일 새 Revision의 실제 articulation·Finger convex/pad·Step·camera/접촉·state restore를 확인했다. ASSET-FINGER-01의 파일/실제 collider 적용·물리 접촉 근거는 확보했다. MuJoCo B01 post222/pre223, Isaac post221/pre222 latch를 보존했다. Isaac 전체 관절/물체 궤적 차이와 pixel/전체센서동등성은 OPEN이며 기존 B01 Evaluation 비결정성으로 자동 해제하지 않는다. 실물 검증 상태도 그대로다. E01 전체 AC01 및 독립 리뷰는 미완료이며 E03/E04/E06은 시작하지 않았다.
