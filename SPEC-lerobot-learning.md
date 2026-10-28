# SPEC: 공식 LeRobot·변환·학습·Hub

ID: `lerobot-learning`. 작성: 2026-10-25. 상태: **구현 전 검토용 명세**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md). 이번 사용자 요청에 따라 SPEC과 계획을 함께 작성했으며 구현 착수 승인을 의미하지 않는다.

## 목표와 범위

공식 Local/Hub Dataset과 ACT·SmolVLA 등을 공식 CLI/API로 학습·로딩·공유한다. 프로젝트 전용 provenance를 일반 학습 조건으로 강제하지 않는다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| P learning/datasets.py, workflow/lerobot_merge.py | 기존 action/feature 의미와 변환/merge 기능 | data/lerobot.py 공식 Dataset 기능 연결 |
| P learning/training.py training_command/train, validation.py; workflow/policy.py, hub.py | 공식 실행 설정/processor 의미·독립 검증·Hub 기능만 참고 | learning/{train,validate,policy}.py, hub.py |
| 기존 학습 UI | MiniVLA 자체 graph/loop/LR/loss 관리 제외 | 필요 시 learning/results.py 공식 로그 읽기 전용 |

구현 파일 범위: `data/lerobot.py, learning/train.py, learning/validate.py, learning/policy.py, learning/results.py(필요 시), hub.py`. 경로는 robot_learning_workbench의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `robot_learning_workbench/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- 개발 기준은 LeRobot0.4.1이다. 기존 공식 CLI/API·processor를 사용하며 최신 버전 조사에 따른 환경 분리·업그레이드 코드는 구현하지 않는다.

- 외부 공식 Dataset 학습/Hub·공식 policy 로딩은 Scene/내부 writer/엔진 없이 독립 검증한다.
- 내부 변환만 DATA-01/03과 기존 action/영상 Baseline이 필요하다.
- 공식 config·CLI/processor·Resume·로그 형식은 설치 버전에서 확인한다. 최신 문서만 보고 버전을 업그레이드하지 않는다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- 학습 loop/optimizer/scheduler/Trainer validation은 공식 구현이 소유한다. custom hook·자동 Offline Validation·MiniVLA loader는 만들지 않는다.
- 공식 config를 정확히 전달하며 공식 단독 실행과 resolved config/환경을 대조한다. Training Recipe에는 engine/Scene이 필요 없다.
- Offline Validation은 저장된 Dataset/Policy로 별도 run·결과를 만들고 checkpoint/optimizer를 변경하지 않는다.
- Policy feature/camera/joint/action/processor 매핑은 명시한다. 학습 호환성과 실제 제어 호환성을 구분한다.
- Hub upload/download·commit pin·오류는 공식 API로 처리한다. 토큰은 기록하지 않고 외부 쓰기 시험은 허가된 저장소에서만 한다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## 검증과 완료 기준

- **lerobot-learning-AC01**: 변환 결과를 공식 도구로 읽고 학습; 외부 Dataset 학습에 전용 metadata 강제 없음.
- **lerobot-learning-AC02**: ACT/SmolVLA 지원 대상별 공식 config/processor·checkpoint/Resume 검증; 모든 policy 조합 지원으로 확대하지 않음.
- **lerobot-learning-AC03**: 로그 조회 off/on·파싱 실패가 Trainer 상태에 영향 없음; Offline Validation 독립; Hub upload/download identity 확인.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래는 **테스트 파일 및 환경 구축 후 사용할 목표 명령**이며 현재 실행하지 않았다. 실제 robot_learning_workbench 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest robot_learning_workbench/tests/test_lerobot_dataset.py robot_learning_workbench/tests/test_official_training.py robot_learning_workbench/tests/test_offline_validation.py robot_learning_workbench/tests/test_policy_contract.py robot_learning_workbench/tests/test_hub.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 한계: 앞의 선행 확인과 실제 회귀 시험은 미완료다. 구현 전 확인할 세부값은 확인 목록에서 해제하며 근거 없는 값으로 명세를 채우지 않는다.


## C Native 전환의 명시적 변환 경계

2026-10-26 [Native 전환](docs/native-dataset-transition.md): data/lerobot.py는 official0.4.1 `_save_episode_data`와 공개 Metadata.save_episode/공식 stats를 버전 고정해 호출한다. 기존 MP4의 기본 save_episode 재인코딩을 피하기 위한 명시 converter이며 SDK monkeypatch/Trainer hook은 없다. 영구 Curation을 선택 rows만 있는 Native materialization으로 전달한다. 학습 자체·공식 processor/Policy action 매핑 검증과 L01의 실제 train/resume는 여전히 미착수다. 신규 recording의 공식 create/add_frame/save_episode/finalize 경계와 별개다.


## 2026-10-27 L03 구현·공식 소비자 관문

[L03](docs/l03-lerobot-dataset.md)은 AC01의 변환·지원 Merge·선택/구간·공식 Dataset/DataLoader/영상/processor 준비 부분을 검증했다. AC01의 실제 Training·AC02 Policy/checkpoint/Resume는 L01/L02 범위로 남긴다. Policy state/action은 JOINTS 순서 model rad, pre-step measured/해당 step absolute recorded joint_targets다. applied/측정 post-state·Mimic delta·IK 진단은 학습 target 대체물이 아니다. Native/Parquet의 원 dtype와 공식 float32 학습 Tensor 도출을 구분한다.

SMOL-PAD-01(설치0.4.1 action_is_pad vs SmolVLA loss actions_id_pad)은 L01의 padding 의미 검증 전 해제하지 않는다. 공식 chunk1 후보의 no-pad Dataset 확인은 Training 검증이 아니다. MuJoCo Policy float32 경계·Follower command binding/motor-range 거부는 L02/P의 명시 해결 전 제어 호환 완료로 표시하지 않는다.


## 2026-10-27 L01/L02 실행 상태

[결과](docs/learning-bundle.md): AC01 실제 ACT train 및 AC02의 ACT config/processor·checkpoint/Resume·정규화 후 Policy 출력·독립 Validation을 검증했다. 새 Workbench 학습/추론 모듈은 수정 없는 공식 CLI/API를 호출하며 학습 loop를 소유하지 않는다. 외부 official Dataset/ACT artifact에 전용 provenance를 강제하지 않는다. Workbench 소유 checkpoint의 provenance/완료 검사는 자체 실행의 Resume·train/val 격리 근거다.

SmolVLA AC02는 실제 loss masking 반례로 BLOCKED. AC03의 독립 Validation/표시 parser 오류 분리는 검증했으나 Hub/L04는 미착수다. Policy float32 strict limit 거부·Follower command binding/모터 범위·물리 Rollout은 별도 관문이며 ACT smoke를 전체 제어 호환 완료로 표시하지 않는다.
