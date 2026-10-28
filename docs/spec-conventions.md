# 기능별 SPEC 공통 규칙

2026-10-25 최종 결정: 새 플랫폼 개발 기준은 **Isaac Sim5.1 / Isaac Lab2.3 / LeRobot0.4.1 / MuJoCo3.3.7**이다. 업그레이드는 진행하지 않는다. 최신 버전 조사는 참고 이력이며 신규 환경 분리·분리 추론·업그레이드 대응 코드는 개발 범위에 포함하지 않는다. 기존 UI/엔진 worker의 필요에 따른 프로세스 분리는 유지한다.


작성: 2026-10-25. [기능 색인](../CAPABILITY-MAP.md)의 11개 SPEC에 공통 적용한다. 이 명세 문서 자체가 구현·Baseline 실행·실물 제어의 실행 지시는 아니다. 실제 작업은 사용자 승인 범위를 따르며 현재 B00~B03과 S01·S02·T01~T04·D01~D04의 승인된 범위만 수행했다.

## 기술 스택과 코드 위치

기존 설계의 Python, NumPy, JSON/YAML, HDF5/영상, PyQt6 및 공식 Isaac Lab·MuJoCo·LeRobot을 사용한다. 기존 조사에서 사용한 Isaac Lab 2.3.0, MuJoCo 3.3.7, LeRobot 0.4.1과 Mimic 이식본 1.0.15는 **기존 환경 유지 결정에 따른 개발 기준**이다. 실제 Python/Isaac Sim/CUDA/SDK/라이브러리 버전과 패키지 출처는 Baseline에서 고정한다. 이 문서를 이유로 업그레이드하거나 신규 의존성을 자동 설치하지 않는다.

기존 architecture.md의 세 프로젝트와 tests/ 위치를 유지한다. SPEC의 테스트 파일명은 검증 책임을 제안한 것이며 런타임 계층 추가가 아니다. 단위/계약/엔진 통합/실물 시험을 구분한다. fixture의 원본 경로·hash·채취 시점·장치/엔진·dtype를 기록하고 대용량 원본은 문서나 Git에 복사하지 않는다.

## 실행 명령 계약

2026-10-25 S01·S02의 scene_contract 파일/Transform/보정 관계와 테스트를 구현했다. [S01](s01-scene-package.md)/[S02](s02-frames-calibration.md)의 pytest/wheel 명령은 실제 검증했으며 기존 환경에 설치하지 않았다. [T01](t01-task-registry.md)의 235개 통합 pytest(신규 Task 97 + Scene 138)·Workbench wheel/독립 import도 실제 검증했다. 기존 환경에 설치하지 않았다. [T02](t02-pick-place.md)의 전체 307개 pytest와 기존 B01 raw 입력 대조·wheel 임시 해제본 import도 검증했다. [T03](t03-placement-reset.md)의 전체 348개 pytest·v8 Reset 참조 대조·wheel도 검증했다. [T04](t04-collision-contact.md)의 전체 401개 pytest·v8 보존/실제 box 수치 대조·wheel도 검증했다. [D01~D04](episode-data-bundle.md)의 전체 506개 pytest·실제 Common/Canonical 변환·로컬 장애/Resume·대표 부하·wheel도 검증했다. 나머지 아래 명령은 해당 구현 이후의 형식이다. 각 작업은 실행할 Python의 절대 경로와 버전, cwd, argv, 환경/출력 위치를 증거에 남긴다. `python3`는 해당 작업용 환경의 실행기를 뜻한다.

```bash
# 해당 프로젝트의 pyproject 및 테스트 구현 이후, 각각 맞는 환경에서 실행
python3 -m pip install -e ./scene_contract
python3 -m pytest scene_contract/tests -q
python3 -m pip install -e ./real2sim_builder
python3 -m pytest real2sim_builder/tests -q
python3 -m pip install -e ./robot_learning_workbench
# 실제 단위/통합 테스트 파일은 각 SPEC의 명령으로 선택한다.
```

Isaac/장치/Hub 시험을 무조건 전체 pytest 실행에 포함하지 않는다. 테스트 선택·환경 검사는 설치 단계에서 구성하고 skip을 통과로 세지 않는다. Build backend·lint 도구는 기존 저장소 설정과 설치 환경 확인 후 최소한으로 선택하며, 없는 build/lint 명령을 실행 가능하다고 쓰지 않는다. 공식 학습 CLI의 정확한 config/flags는 설치된 LeRobot 버전에서 확인한 뒤 학습 작업 증거에 남긴다. 신규 CLI는 architecture.md의 run/validate/inspect-scene 방향을 유지하고 실제 argparse 계약 확정 후 실행 예시를 갱신한다.

## 코드 스타일

snake_case, 소유 모듈에 작은 타입, 일반 함수 우선, 명시적 입력/단위·반환을 사용한다. 예시는 문서용으로 파일을 생성하지 않는다.

```python
# 문서용 signature 예시: 실제 계산은 검증된 기존 수식을 사용한다.
def placement(sample: TaskSample, *, params: PlacementParams) -> bool:
    ...
```

None/False/문자열로 오류를 혼용하지 않는다. 정상 Task false와 계약 오류를 구분하고 오류 code/field/effect를 보존한다. 입력 경계에서 검증하며 모든 helper에 같은 검사를 복제하지 않는다. 등록 함수에 기반 클래스·새 Adapter를 강제하지 않는다.

## 시험 전략과 완료 정의

- 단위: 순수 Transform·Calibration·판정·배치의 동일 입력 비교, threshold 아래/같음/위, latch/window·누락 tick·예외를 검사한다.
- 계약: Metadata/Recipe/Task/IPC/저장/Resume의 정상·오류·부분 실패를 검사한다.
- 엔진 통합: 각 엔진의 기존 Baseline과 신규 실행을 비교한다. 다른 엔진을 정답으로 삼지 않는다.
- 공식 도구: 변환 결과의 공식 reader/학습 사용과 공식 Trainer 단독 실행 대비 설정·processor·checkpoint 의미를 확인한다.
- UI/실물: 기존 기능 inventory를 대조하고 실물 제어 시험은 명시 승인된 조건에서 수행한다.

임의 coverage 비율 대신 각 SPEC AC 및 migration-validation.md의 관련 경계 사례를 모두 추적한다. 물리 반복 횟수·허용 수치 오차·부하 한도는 Baseline 측정과 기존 dtype/연산 순서에 근거해 신규 결과를 보기 전에 정한다. 결과가 달라진 뒤 tolerance를 맞춰 통과시키지 않는다. 순수 계산은 exact 비교 우선이다.

각 결과에는 SPEC AC, 확인 항목 ID, 기존 근거, 입력 identity, 실행 명령, expected/actual, 차이·영향, 미검증 범위를 남긴다. 코드 존재·mock 통과·엔진 한쪽 통과·장치 부재 skip만으로 전체 완료를 표시하지 않는다.

## 경계

항상 원본 불변·새 출력·공식 API 우선·기존 단위/좌표/시점/명령 의미를 유지한다. 계산 의미 변경·필수 자료 부재·공식 지원 불일치는 먼저 보고한다. 새로운 제품 기능·서비스·DB·추상 계층, MiniVLA, custom Trainer, 자동 부족 영역 분석을 추가하지 않는다. 배치·Recipe UI 변경 등 이미 승인된 예외는 다시 승인받지 않고 차이 기록으로 관리한다.

2026-10-25 승인 예외: DataGen IK는 **Pinocchio DLS + Best Effort 단일 방식**으로 정했다. SciPy IK·Strict/Hold·선택 UI/Recipe 옵션은 이관하지 않는다. [simulation-workflows SPEC](../SPEC-simulation-workflows.md#datagen-ik-고정-계약)의 기존 DLS 수식·안전 경계와 StableGrasp AND Placement는 보존하고, B01 SciPy + Strict 대비 실행 궤적/실패 결과 변화는 의도된 변경으로 보고한다. B01 원본 증거·과거 IK provenance를 재작성하지 않으며 다른 정책 run을 새 정책 Resume로 혼합하지 않는다. 이번 결정 반영은 문서 작업이고 실제 구현·양 엔진 검증은 DataGen 단계에서 수행한다.

2026-10-26 RO01~RO03 검증: [실제 명령](evidence/robot-operations/commands.json)의 기존 interpreter로 오프라인 guard 아래 전체647개(신규76)를 통과했다. wheel/독립 import/계산·기존 CLI/worker smoke와 보존을 검증했다. runtime 의존성 설치/업그레이드는 없으며 OpenCV blur와 공식 SDK factory는 기존 설치 라이브러리를 호출하는 구체 경계다. 물리 장치·실물 AC03은 BLOCKED다.
