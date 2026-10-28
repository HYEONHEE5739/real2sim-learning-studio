# SPEC: Data Curation

ID: `data-curation`. 작성: 2026-10-25. 상태: **구현 전 검토용 명세**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). 이번 사용자 요청에 따라 SPEC과 계획을 함께 작성했으며 구현 착수 승인을 의미하지 않는다.

## 목표와 범위

기존 영상·Episode 검토·위치 분포·제외·split·export 기능을 유지한다. 부족 영역 판단과 Recipe 위치 입력은 사람이 수행한다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| P workflow/curation.py, curation_ui.py CurationDialog | 분포/선택/제외/split/export·영상 검토 의미 | data/curation.py 및 ui/curation.py 소비 계약 |
| 기존 Episode/공식 Dataset reader | 지원 데이터의 선택/보존 의미 | Native Catalog·공식 HDF5/LeRobot API 사용 |

구현 파일 범위: `data/curation.py, ui/curation.py`. 경로는 robot_learning_workbench의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `robot_learning_workbench/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- 고정된 Episode index/분포 fixture로 엔진·학습 없이 검증한다.
- 영상/배열 소비는 DATA-01/03; 공식 Dataset export만 lerobot 변환 계약에 의존한다.
- 기존 화면/필터/split 규칙의 inventory와 결과 Baseline을 확보한다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- Curation 위치 표시에는 좌표계 ID·단위를 포함한다. 표시 위치를 같은 frame의 Recipe XY로 해석할 수 있어야 한다.
- 제외/분할/선택은 원본 삭제가 아닌 새 결과·선택 Episode ID/seed/규칙 기록이다. Source partition 잠금을 보존한다.
- 영상 timeline과 frame index를 대응시키며 누락을 이전 frame으로 숨기지 않는다.
- subset은 불변 참조 가능, 독립 공유 export는 materialize한다. 자동 부족 영역 탐지/추천·Recipe 자동 연결은 구현하지 않는다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## 검증과 완료 기준

- **data-curation-AC01**: 기존 선택/필터/split 입력의 Episode 집합·순서·분포 결과 일치.
- **data-curation-AC02**: 표시 frame/unit과 Recipe 좌표 변환 검증; 누락 자료 오류 명시.
- **data-curation-AC03**: 원본 hash 유지, subset 참조/이동/독립 export 재로딩 및 Source partition 잠금 확인.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래는 **테스트 파일 및 환경 구축 후 사용할 목표 명령**이며 현재 실행하지 않았다. 실제 robot_learning_workbench 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest robot_learning_workbench/tests/test_curation.py robot_learning_workbench/tests/test_curation_export.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 한계: 앞의 선행 확인과 실제 회귀 시험은 미완료다. 구현 전 확인할 세부값은 확인 목록에서 해제하며 근거 없는 값으로 명세를 채우지 않는다.


## 2026-10-26 최종 Native 저장 전환

2026-10-26 최종 C Native 전환: [구현·검증 보고](docs/native-dataset-transition.md). 사용자 확정에 따라 자체 Episode별 HDF5/Index/Descriptor/Migration을 제거하고 공식 불변 HDF5 segment + 최소 Metadata·영구 Curation·명시 LeRobot materialization으로 교체했다. NATIVE-01/02/03의 파일·공식 CPU 소비자 관문을 검증했다. 과거 D/R/RO 보고서·증거는 보존하며 BU/E·실물·UI·Trainer 실행은 시작하지 않는다.

영구 선택/구간/split·V1 재로드/V2·독립 Export API는 data/curation.py로 구현했다. 분포 시각화·추천·UI·실제 Policy/Task 성공 분석은 구현하지 않았으므로 C01/C02 전체 완료로 표시하지 않는다. 중간 구간의 학습 materialization과 물리 initial 복원은 구별한다.


## 2026-10-27 C01/C02 구현·검증 상태

[C01/C02](docs/curation-bundle.md)는 기존 Native C 선택/재로드·공식 L03 Export/Merge를 재사용했다. AC01/02의 선택/필터/split·정확한 선택 통계·frame/unit·좌표 변환과 AC03의 원본 보존/참조·이동/독립 Export/공식 소비 경계를 실제4 Episode 및 과거50 Episode로 검증했다. 새 Workbench UI는 구현하지 않았다.

선택 통계와 원본 outcome/전체 run attempt는 구분하며 trimmed Episode의 성공을 재판정하지 않는다. seed/rule·부모 identity와 명시 relocation은 작은 Revision JSON에 보존하고 source partition을 현재배정으로 재명명하지 않는다. unknown 단위·누락 field/frame을 추측하거나 자동 Merge/추천하지 않는다. 영상 UI 조작·장시간/대용량 부하와 전체 content dedup은 미검증이다.
