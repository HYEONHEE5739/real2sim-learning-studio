# 구현 명세 작성 범위와 검토 순서

작성: 2026-10-25. 상태: **Phase 0 검토안 — 기능 범위·의존성 승인 대기**.

[요구사항](docs/requirements.md), [아키텍처](docs/architecture.md), [데이터 계약](docs/data-contracts.md), [Interface](docs/interfaces.md), [이관 검증](docs/migration-validation.md)을 기준으로 한다. 새로운 아키텍처나 Python 패키지 목록이 아니라, 독립적으로 명세하고 검증할 작업 단위의 색인이다. 아래 ID는 이후 명세·계획·검증 결과에서 유지한다.

## 전제와 경계

- 기존 설계 방향을 유지한다. 아래 작업 단위를 이유로 폴더·서비스·Adapter·ABC를 추가하지 않는다.
- v8 양 엔진과 전체 기능이 완료 목표다. MiniVLA 및 자체 Trainer/학습 관리 이관은 제외한다.
- DataGen IK는 고정 Pinocchio DLS + Best Effort만 이관한다. SciPy IK·Strict/Hold·선택 UI/Recipe 옵션은 명시적 제외다. DLS/안전 계산과 StableGrasp AND Placement는 보존하며 B01 대비 정책 변경 영향은 별도 보고한다. 실제 구현·양 엔진 검증은 E06이고 이번에는 설계만 반영한다.
- 재사용은 계산·입출력 의미와 필요한 알고리즘의 재사용이다. 기존 의존성 그래프를 복사하는 뜻이 아니다.
- 조사로 확인 가능한 미정 사항은 먼저 코드·기록으로 해결한다. 기존 의미 변경이나 자료로 결정할 수 없는 중요한 선택만 사용자에게 묻는다.
- [구현 전 확인 목록](docs/preimplementation-checks.md)의 차단 항목은 관련 구현 착수 전에 해결한다. 문서 작성과 독립 영역의 조사는 계속할 수 있다.
- 진행 상태: B00~B03 조사/대표 검증과 [S01 파일 계약](docs/s01-scene-package.md)·[S02 Frame/보정 관계](docs/s02-frames-calibration.md)·[T01 명시 Task 등록](docs/t01-task-registry.md)·[T02 v8 순수 판정](docs/t02-pick-place.md)·[T03 v8 배치](docs/t03-placement-reset.md)·[T04 다면체/평면 접촉 배치](docs/t04-collision-contact.md)의 지원 범위를 완료했다. [D01~D04 Episode 묶음](docs/episode-data-bundle.md)의 파일/오프라인 저장·변환·Resume/참조 Export·부하도 완료했다. 실제 엔진 재생·공식 Dataset 변환·외부 업로드·실물 연결/제어는 수행하지 않았다. 두 번째 묶음은 자동 시작하지 않는다.

## 기능별 책임과 의존성

의존성은 제공 계약을 사용하는 방향이다. `A → B`는 A를 확보한 뒤 B를 구현·검증한다는 뜻이며, 런타임 Python import를 강제하지 않는다. 기존 자료를 사용하는 독립 실행을 막는 Workflow 순서도 아니다.

| ID | 책임 / 기존 설계 위치 | 직접 선행 계약 |
|---|---|---|
| scene-package | Scene·Transform·Calibration 적용 정보·무결성·Revision 계약: scene_contract | — |
| builder | 편집·재구성·정합·검토·렌더·Export 및 Builder UI | scene-package |
| task-functions | v8 판정·배치 계산·등록 선언: tasks | scene-package |
| episode-data | 기록·영상·Reader·commit·Resume 및 기존 자료 변환: data/episodes, video, migration | scene-package |
| robot-operations | 장치·Precision Calibration·제어·Capture·자료 계약: robot/devices, calibration, control, capture | scene-package |
| recipe-execution | Recipe 검증·실행 기록·작업 프로세스·IPC: recipe, run, cli | scene-package, task-functions, episode-data |
| simulation-workflows | 양 엔진 구성·Source·Annotation·DataGen·공유 Mimic: engines, generation | recipe-execution, robot-operations |
| lerobot-learning | 공식 Dataset 변환/Merge·학습·Policy 로딩·독립 Offline Validation·Hub·선택적 로그 조회 | recipe-execution |
| policy-evaluation | 양 엔진 Policy 평가·실물 평가·Real/Sim: engines/*/evaluation, robot/evaluation, real_sim | simulation-workflows, lerobot-learning |
| data-curation | 분포·검토·제외·split·export: data/curation | episode-data, lerobot-learning |
| workbench-ui | Recipe 편집·실행·영상·로그·전체 단계별 화면: ui | recipe-execution, robot-operations, simulation-workflows, lerobot-learning, policy-evaluation, data-curation |

builder는 Capture의 코드에 의존하지 않고 확인된 촬영·보정 자료 계약을 소비한다. scene-package는 보정 계산을 구현하는 모듈이 아니다. robot-operations의 실물 시험은 장치 기능의 완료 조건이지만, 시뮬레이션의 순수 계산 검증을 시작하기 위한 조건은 아니다.

lerobot-learning의 일반 학습/Hub는 Scene·내부 Episode를 런타임 필수 입력으로 요구하지 않는다. 내부 자료 변환 기능만 episode-data 계약을 사용한다. simulation-workflows의 Source만 필요한 장치 입력을 사용하며 Annotation/DataGen에 실물 로봇을 요구하지 않는다. UI는 전체 통합 완료 의존성을 표시한 것이며 Recipe 편집기 등 독립 부분은 먼저 검증할 수 있다.

## 구현·검증 순서 제안

| 순서 | 범위 | 진행 조건 |
|---|---|---|
| 0 | 기존 코드/자료/버전·UI inventory, Baseline 수집 절차 확정 | 확인 목록의 증거 경로·담당 범위 지정; 실행은 별도 착수 후 |
| 1 | scene-package, v8 계산·보정·Episode 계약 확정 | 해당 미확정 항목 해소; 새로운 Schema로 기존 의미 손실 없음 |
| 2 | task-functions, episode-data, robot-operations의 오프라인 부분, builder | 계약별 명세 승인; 해당 순수 계산/저장 fixture 확보 |
| 3 | recipe-execution 및 UI 편집/프로세스 기능 | 기록·등록 계약 준비; 실제 장치 없이 프로세스/오류 시험 |
| 4 | simulation-workflows 양 엔진; lerobot-learning 병행 가능 | 엔진별 상태·시점/복원 확인; 학습은 공식 실행 동등성 확인 |
| 5 | policy-evaluation, data-curation, 나머지 UI 통합 | 입력 기능 완료; 실물 제어는 장치 계약과 실물 시험 승인 충족 |
| 6 | 전체 회귀·이동·Resume·새 함수 등록 검증 | 기능별 증거 충족; 한 엔진만으로 v8 완료 판정 금지 |

이 순서는 모든 기능의 명세·검증 책임을 나누기 위한 제안이다. builder 전체 완료를 기존 v8 패키지의 오프라인 검증보다 먼저 요구하지 않으며, 실패한 선행 계약을 미지원 표시로 감추고 전체 완료로 처리하지 않는다.

## 승인 후 명세 산출물

기능별로 `SPEC-<ID>.md`를 이 색인 옆에 작성한다. 기존 설계 내용을 복제하지 않고 해당 절을 참조하며, 각 문서에 다음 항목을 포함한다.

1. 목표·소비자·범위와 비목표.
2. 실제 기존 파일/함수별 재사용 범위와 새 구현 파일/책임.
3. 선행 확인 ID와 필요한 Baseline/fixture, 차단 해제 근거.
4. 입력·출력·오류·상태 수명과 기존 Interface 연결.
5. 실행 환경·정확한 검증 명령·테스트 위치·코드 스타일. 아직 없는 CLI를 실행 가능한 명령으로 표시하지 않는다.
6. 수치/경계/저장/실행 검증과 기능별 완료 기준·미검증 범위.
7. 항상 할 일 / 변경 전 논의할 일 / 금지할 일.

명세 승인 후 계획과 작은 작업 목록을 작성한다. 구체 계획 분해에는 스킬이 참조한 planning-and-task-breakdown의 가용성·규칙을 확인한다. 지금은 개별 명세, tasks/plan.md, 작업 목록을 작성하거나 구현을 시작하지 않았다.

개발 버전은 기존 Sim5.1/Lab2.3/LeRobot0.4.1/MuJoCo3.3.7로 확정했다. [최신 버전 조사](docs/version-compatibility.md)는 참고 자료이며 업그레이드·분리 추론 구현은 범위 밖이다.

2026-10-26 [RO01~RO03 묶음](docs/robot-operations-bundle.md): AC01 계산·identity/AC02 대표 fake 수명·오류/RO03 Capture 준비 계약 완료. 전체647개(신규76). 실제 장치 AC03은 BLOCKED이며 engine/Policy/UI/프로필 활성화·Snapshot publish/장치 Recipe runner는 완료로 표시하지 않는다. 다음 후보 BU01~BU03은 제안만 한다.


## 2026-10-26 최종 Native 저장 전환

2026-10-26 최종 C Native 전환: [구현·검증 보고](docs/native-dataset-transition.md). 사용자 확정에 따라 자체 Episode별 HDF5/Index/Descriptor/Migration을 제거하고 공식 불변 HDF5 segment + 최소 Metadata·영구 Curation·명시 LeRobot materialization으로 교체했다. NATIVE-01/02/03의 파일·공식 CPU 소비자 관문을 검증했다. 과거 D/R/RO 보고서·증거는 보존하며 BU/E·실물·UI·Trainer 실행은 시작하지 않는다.
