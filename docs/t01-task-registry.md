# T01 — Task 함수 명시적 선언·등록·파라미터 검증

2026-10-25. 상태: **T01 구현·파일/함수 계약 검증 완료**. [SPEC](../SPEC-task-functions.md)의 T01과 [Interface](interfaces.md#5-task-등록호출-interface)를 구현했다. T02 판정 수식·StableGrasp 상태 구현, 배치 함수·Recipe 실행기·UI·엔진 연결은 시작하지 않았다. 기존 v8을 실행하거나 Task의 물리 결과를 새 구현과 비교한 보고서가 아니다.

## 구현 파일과 책임

| 파일 | 책임 / 필요 이유 |
|---|---|
| [registry.py](../robot_learning_workbench/src/robot_learning_workbench/tasks/registry.py) | YAML 명시 목록 읽기, FunctionSpec 선언·지원/호출 형태·파라미터·참조 검사. 함수 map과 작은 데이터/오류 타입을 이 소유 파일에 둔다 |
| [task_modules.yaml](../robot_learning_workbench/task_modules.yaml) | 승인된 Python 모듈의 순서 있는 목록. 현재 `modules: []`; v8 판정은 T02 이후 실제 구현과 함께 등록한다 |
| [test_task_registry.py](../robot_learning_workbench/tests/test_task_registry.py) | 임시 Task 모듈·YAML·실제 S01/S02 ScenePackage를 사용한 계약 시험 97개 |
| [pyproject.toml](../robot_learning_workbench/pyproject.toml) 및 두 `__init__.py` | 설계된 Workbench의 표준 src 패키징과 tests 검색. Python>=3.11, scene-contract>=0.2,<0.3·PyYAML>=6,<7; pytest는 test optional. 장치/엔진 시작 없음 |

첫 증분에서 패키징·목록 검증(제품/시험 파일 5개), 다음 증분부터 선언·파라미터·경계 검증(registry/test 및 YAML)으로 나누었다. 런타임 구현은 registry.py 하나다. 서비스·Plugin manager·자동 검색·Task ABC·데코레이터·Engine Adapter·동적 UI 폼 생성기는 추가하지 않았다. 기존 Task loader의 실행 구조를 복사하지 않았다. **scene_contract 소스·테스트는 변경하지 않았다.**

## 공개 함수와 선언

- `read_module_names(path) → tuple[str,...]`: `{modules: [...]}`만 읽으며 모듈을 import하지 않는다. YAML 중복 key·이름/모듈 중복·타입·알 수 없는 필드·Python tag·anchor/alias를 거부한다. 파일 경로/`module:function`은 모듈 이름이 아니다. 빈 목록은 유효하다.
- `load_registry(module_names: tuple[str,...]) → TaskRegistry`: 목록의 이름을 모두 검사하고 명시 순서대로 표준 importlib로만 import한다. 각 모듈의 `FUNCTIONS`를 읽어 이름 중복·선언·callable·params schema·명시 binding을 검사한다. 디렉터리 scan·entry-point 탐색·자동 reload·fallback은 없다.
- `resolve(registry, name, *, kind, stage, engine=None) → FunctionSpec`: 정확한 등록 함수와 지원 조건을 확인한다. 다른 함수/엔진/역할로 대체하지 않는다. 반환된 `callable`은 원래 일반 함수 참조 그대로다.
- `validate_params(registry, name, values, *, kind, stage, engine=None, scene=None, selected_objects=None) → P`: dataclass 파라미터를 구성하고 타입·Scene 참조·선택 목록·모듈의 선택적 관계 검사를 수행한다. Task 판정 함수나 tracker factory는 호출하지 않는다.

`TaskRegistry`는 modules/functions/source_sha256/validators를 가진 frozen 데이터이며 manager 메서드 계층이 아니다. 선언의 stages/engines/requires/bindings와 map은 읽기 전용 복사본이다. params_type·callable 자체는 개발자가 제공한 Python 참조다. 실행 엔진·Writer·장치 핸들을 등록 데이터에 감싸 넣지 않았다.

`FunctionSpec`은 `kind`, `stages`, `engines`, `params_type`, `callable`, 선택 `requires`, `bindings`, `contract_version=1`이다. 개발자는 자신의 Task 파일에 dataclass와 일반 함수를 쓰고 `FUNCTIONS`에 선언한 뒤 목록에 모듈 이름을 추가한다. 임시 모듈만 추가하는 AC03 시험에서 core/UI 변경 없이 조회·파라미터 검증·일반 함수 직접 호출까지 확인했다. 이 시험 함수는 v8 알고리즘을 대신하지 않는다.

역할은 predicate/tracker/placement/metrics/acceptance다. 현재 Task가 소비되는 단계는 source/annotation/datagen/simulation_evaluation/real_evaluation/real_sim이다. Training에는 Task hook을 연결하지 않는다. 엔진 ID는 Scene 계약과 같은 `isaac`/`mujoco`, 엔진 독립 계산은 단독 `{independent}`다. engine=None은 독립 선언에서만 허용한다. Recipe 문서의 UI/직렬화 명칭 `isaaclab`과 Scene/Task ID `isaac`의 명시적 이름 연결은 R02의 준비 단계 책임이며, T01은 Recipe를 파싱하거나 이름을 암묵 대체하지 않는다.

호출 signature는 기존 Interface의 이름/keyword-only 구분을 검사한다: predicate·metrics는 `(sample, *, params)`, acceptance는 `(final, *, params)`, placement는 `(request, *, params)`, tracker factory는 `(*, params, episode)`. async/generator·문자열 import 참조·임의 callable 객체·추가 인자를 거부한다. 등록 검사는 factory를 인스턴스화하지 않는다. `Tracker.update`·Task 반환값·live sample의 수치 검사는 해당 구현/호출 경계에 남긴다.

## 파라미터와 Scene 연결

`params_type`은 Task 파일의 dataclass다. str/bool/int/유한 float, Literal, Optional/Union, list/tuple/dict[str,T], 중첩 dataclass를 지원한다. bool을 int로, 문자열을 수치로 강제 변환하지 않는다. float 필드의 정수 입력은 수치 그대로 허용하고 list→선언된 tuple 구성 이외의 수치 정규화·단위/좌표 변환은 하지 않는다. 누락 필수값·unknown 필드·잘못된 기본값·미지원/재귀 type schema를 거부한다. default_factory 결과는 실제 파라미터를 구성할 때 검사한다.

참조 필드는 `field(metadata={"reference": "object"|"frame"|"support"})`로 표시한다. string·optional string·그 목록/tuple에 적용한다. 검사에는 **load_scene으로 검증된 ScenePackage**의 objects/frames/supports만 사용한다. Scene 파일을 다시 읽거나 Transform/Calibration을 재계산하지 않는다. 실제 참조가 없으면 Scene을 강제하지 않는다. 생성 목록을 받으면 빠진 task_object 참조는 OBJECT_NOT_SELECTED이며 고정 환경 cup 참조는 목록에서 빠져도 유효하다. 값/컨테이너는 호출자 입력과 분리해 구성한다.

type만으로 표현하기 어려운 관계는 Task 모듈의 `validate_params(params, scene) → None` 일반 함수를 사용한다. 반환값/예외를 검사하고 원인 chain을 보존한다. 등록된 Python과 type annotation/default/검증 함수는 신뢰한 개발자 코드다. import 자체의 Python 부수 효과를 sandbox로 차단한다는 보장은 없다. UI import/장치 연결은 이번에 구현하지 않았다.

## requires·binding 검증의 경계

requires는 Interface의 TaskSample 필드와 `signals.<name>`만 허용한다. bindings는 `stage → {phase, signals?}`이며 phase는 episode_start/pre_step/post_step/episode_end, provider는 `{function, params?, delayed?}`다. 이는 Python 선언 데이터이고 Recipe 자유식/설정 언어가 아니다.

선언된 provider는 등록된 tracker여야 하며 역할·stage·engine 지원과 제공된 부분 파라미터의 필드/타입이 맞아야 한다. 명시된 의존 cycle과 뒤 phase의 결과를 같은 tick의 앞 phase에서 요구하는 선언을 거부한다. 이전 tick 입력은 delayed=true로 구분하며 그 값을 보존한다. **순서를 실행하거나 바꾸는 scheduler는 없다.**

필수 params의 전체 공급·Scene 참조·signal 충돌/동일 tracker 공유·requires의 최종 충족 여부는 Recipe와 Scene을 합치는 R02/단계 실행에서 검사해야 한다. 명시 provider의 부분 defaults가 등록 검사에 통과했다고 실행 가능한 계획이 완성된 것은 아니다. T01은 missing signal을 자동 생성하거나 StableGrasp 인스턴스를 만들지 않는다.

오류는 `TaskError(code, message, issues, effect=not_started)`다. code는 TASK_MODULES_INVALID/TASK_IMPORT_ERROR/TASK_DECLARATION_INVALID/TASK_UNKNOWN/TASK_UNSUPPORTED/TASK_PARAMS_INVALID/OBJECT_NOT_SELECTED를 구분하고 field/reason/source와 원인 예외를 보존한다. not_started는 Task 실행이 시작되지 않았다는 의미이며 신뢰한 Python import가 무효과라는 뜻은 아니다. 정상 predicate False는 직접 호출의 정상 결과다.

source_sha256는 모듈·직접 callable/params_type/검증 함수의 조회 가능한 소스 파일 바이트 hash다. 빈 FUNCTIONS 모듈도 기록한다. importlib의 기존 module cache를 우회하지 않으며, 이 목록만으로 간접 import 전체·현재 메모리의 bytecode·실행 환경 재현성을 증명하지 않는다. 새 worker에서의 입력 고정·코드 identity 전체 기록은 R02/R03에 남는다.

## 검증과 증거

| 항목 | 결과 |
|---|---|
| 신규 Task 등록·파라미터 시험 | **97 passed**, skip 0. 명시 목록/미검색·중복·오류·5개 역할·factory 미실행·Scene 참조·phase/cycle·delayed·독립 함수 직접 호출 |
| S01/S02 회귀 포함 전체 suite | **235 passed**, skip 0: Scene 138 + Task 97. [JUnit](evidence/t01/unit-tests.xml), [최종 로그](evidence/t01/logs/08-final-suite.log) |
| 증분 RED/GREEN | 목록 16 → 선언 41 → params 74 → 관계/오류 91 → 추가 입력 94 → 참조/직접 호출 96 → 빈 모듈 identity 97. 실패 재현·수정 로그를 보존 |
| wheel | [build.json](evidence/t01/build.json). 소스/설정 bytes 비교·compile·isolated wheel import·임시 Task 선언/params/직접 호출 통과. S02 wheel을 사용했고 기존 환경에 설치하지 않음 |
| 보존 | [전후 대조](evidence/t01/preservation-after.json): 기존 56,100개 stat·선택 14,994개 SHA, B01~B03/S01/S02 보고서·증거와 scene_contract 제품/테스트 변경 없음. 전체 corpus/SDK binary의 전수 byte 비교는 아님 |
| 최종 확인 | [verification.json](evidence/t01/verification.json), [commands.json](evidence/t01/commands.json): 명령·환경·source/evidence identity·문서 링크·작업 범위 |

Python은 기존 `/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python` 3.11.15이며 pytest9.1.1/PyYAML6.0.2와 설치된 의존성을 사용했다. pip install·환경 업그레이드·새 환경 생성은 하지 않았다. 별도 lint/type 도구는 설정/설치되어 있지 않아 실행했다고 주장하지 않는다. 테스트 임시 Scene은 합성 계약 fixture이며 기존 v8 패키지 변환이나 엔진 시험이 아니다.

## 차이·남은 작업·중단 경계

기존 판정/좌표/Calibration 계산·성공 기준·tick/frame·IK 정책을 변경하지 않았다. 구형 task_scripts의 구조를 가져오지 않고 새 명시 목록과 타입/오류 계약을 구현한 것이 새 동작이다. B01 판정 Baseline·Isaac DataGen 실패/Evaluation 비결정성, B02의 기록 누락/phase/정책별 Resume와 B03 장치/검증 상태는 그대로다.

AC03의 **오프라인 선언/연결 부분**을 완료했다. 실제 새 Task의 엔진 상태 공급·결과/phase·UI 연결까지 검증된 것은 아니다. AC01 판정 회귀와 AC02 배치는 T02 이후에 남는다. 기본 목록이 비어 있으므로 현재 v8을 바로 실행하는 완성된 Workbench가 아니다.

`incremental-implementation`과 `test-driven-development`의 작은 검증 단위를 적용했다. 스킬이 참조한 `/home/hyeonhee/.agents/references/definition-of-done.md`는 지정 위치 및 가용 스킬 경로 검색에서 발견되지 않아 읽었다고 간주하지 않았다. SPEC의 T01 범위·테스트·빌드·보존 대조를 완료 근거로 남겼다. Git 저장소가 아니므로 저장소 초기화/commit은 하지 않았다. **T01만 완료하며 다음 작업을 시작하지 않는다.**
