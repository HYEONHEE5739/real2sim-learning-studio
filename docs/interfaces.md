# 구현 전 API·Interface 명세

2026-10-25 최종 결정: 새 플랫폼 개발 기준은 **Isaac Sim5.1 / Isaac Lab2.3 / LeRobot0.4.1 / MuJoCo3.3.7**이다. 업그레이드는 진행하지 않는다. 최신 버전 조사는 참고 이력이며 신규 환경 분리·분리 추론·업그레이드 대응 코드는 개발 범위에 포함하지 않는다. 기존 UI/엔진 worker의 필요에 따른 프로세스 분리는 유지한다.


후속 구현 명세의 범위·순서는 [기능 범위 색인](../CAPABILITY-MAP.md), v8 미확정 동작·실물/Calibration Interface·Episode 호환성의 착수 조건은 [구현 전 확인 목록](preimplementation-checks.md)에서 관리한다. Interface 방향 유지는 이 확인 항목의 검증 완료를 뜻하지 않는다.

작성: 2026-10-25. 상태: 상세 명세 및 S/T·D/R·RO01~RO03의 승인된 순수/파일/프로세스/fake 범위 구현. 별도 Schema 파일·패키지 변환은 생성하지 않았다. [요구사항](requirements.md)이 우선하며 [아키텍처](architecture.md)의 파일 배치와 [데이터 계약](data-contracts.md)의 저장 책임을 구체화한다. 기존 v8 원본과 계산·시점은 [이관 검증](migration-validation.md)을 따른다.

`api-and-interface-design` 스킬의 계약 우선, 입력 검증, 일관된 오류, 상태 소유권과 중복 실행 방지 원칙을 적용한다. 로컬 Python/파일/프로세스 Interface이며 REST 서버·DB·API gateway를 추가하지 않는다. 아래 타입과 signature는 문서 표기이고 새 ABC·Wrapper의 구현 요구가 아니다.

2026-10-25 구현 상태: [S01](s01-scene-package.md)과 [S02](s02-frames-calibration.md)의 Scene 파일·reference Frame Graph/SE(3)·보정 관계를 구현했다. [T01](t01-task-registry.md)의 명시적 Task 선언·파라미터/Scene 참조 검증도 구현했다. 아래 전체 Workflow/엔진 Interface나 Scene의 물리/렌더 동등성까지 구현·검증된 것은 아니다.

## 1. 공통 표기와 버전 원칙

- Python/JSON/YAML 이름은 기존 방향대로 snake_case, stage/state 값은 lower_snake_case, 오류 code는 UPPER_SNAKE_CASE. HTTP 예제의 naming을 로컬 계약에 기계적으로 적용하지 않는다.
- `SceneId`, `Revision`, `ObjectId`, `FrameId`, `RunId`, `EpisodeId`는 서로 다른 의미의 string 타입이다. Python에서는 NewType/type alias로 구별할 수 있고 런타임 클래스 계층은 필요 없다. 경로를 ID로 사용하지 않는다.
- `Sha256`은 소문자 64자리 hex, 수치는 finite, 길이 m/각도 rad/시간 s. `Matrix4`는 shape (4,4), `Vec3`는 (3,), quaternion의 표기는 이름에 순서를 명시한다. float32/64를 의미 없이 통일하지 않으며 v8 연산 dtype/순서는 기존 경로로 검증한다.
- `Map[K,V]`, `tuple[T,...]`는 읽기 전용 계약이다. 외부 파일을 읽는 함수가 타입·참조·수치 검사를 마친 뒤 내부 계산에서 파일 전체 검사를 반복하지 않는다. 엔진 실시간 상태와 사용자 Task 반환은 새 입력이므로 해당 진입점에서 검사한다.
- `schema_version: 1`은 첫 지원 계약이다. Schema/Task contract version, Scene Revision, 실행 코드 version은 별개다. 현재 runtime에 병렬 v1/v2 구현을 상시 유지하지 않고 필요한 경우 별도 migration으로 옮긴다. 과거 수치·시점은 버전 이름 변경으로 재해석하지 않는다.
- 선택 필드 추가도 기존 reader의 unknown-field 검사와 충돌할 수 있다. 지원 Schema minor/capability 협상 없이 자동 하위 호환이라고 주장하지 않는다. 초기에는 알려진 필드만 허용하고 호환 확장은 reader 검증을 함께 갱신한다. 단위·기본값·부등호·호출 phase 변경은 breaking change다.
- 사용자 메시지 문구/traceback은 기계 파싱 계약이 아니다. 오류 code·field path·상태/phase·기록 단위·commit 의미는 공개 계약이다.

## 2. 오류와 검증 위치

동일 프로세스의 명령 함수는 **정상 결과 반환 또는 계약 오류 예외**만 사용한다. 실패를 None/False/문자열로 혼용하지 않는다. 검증 UI도 같은 오류를 받아 표시한다. Task의 정상 `False`는 수행 실패이며 예외가 아니다.

오류 레코드: `code: str`, `message: str`, `issues: tuple[Issue,...]`, `effect: not_started|not_applied|applied|unknown`.

`Issue = {field: str, reason: str, expected?: JSONValue, actual?: JSONValue, source?: path, line?: int, object_id?: ObjectId, episode_id?: EpisodeId}`. 자격증명은 actual/로그에 넣지 않는다. 내부 예외는 원인 chain으로 보존하고 worker 외부에는 같은 오류 레코드로 직렬화한다. Scene 오류 타입은 `scene_contract/package.py`, 실행 오류 타입은 `run.py` 등 실제 소유 모듈에 둔다. 공통 exception 프레임워크를 만들지 않는다.

| code 예시 | 발생 위치 | 자동 재시도 |
|---|---|---|
| RECIPE_INVALID / INPUT_CHANGED | YAML·저장 파일 hash | 없음; 사용자가 수정/저장 |
| SCENE_INVALID | S01 JSON/ID/필수 참조/경로 구조 | 없음; source/field를 표시하고 수정 필요 |
| SCHEMA_UNSUPPORTED / SCENE_REVISION_MISSING / SCENE_INTEGRITY_MISMATCH | 패키지 load | 최신 Revision 대체 금지 |
| FRAME_UNRESOLVABLE / OBJECT_NOT_SELECTED | frame graph·생성 목록 | identity/default Object 대체 금지 |
| TASK_UNKNOWN / TASK_UNSUPPORTED / TASK_RESULT_INVALID | registry·사용자 함수 반환 | 함수/엔진 fallback 금지 |
| INVALID_PLACEMENT | Fixed 배치 | XY/자세 보정 금지 |
| PLACEMENT_EXHAUSTED | Random 물체별 1000회 후보 소진 | 해당 run 중단 |
| REQUEST_CONFLICT / OUTPUT_EXISTS / RUN_STATE_UNKNOWN | 실행 claim·복구 | 새 worker 자동 시작 금지 |
| EPISODE_CONFLICT / RESUME_INCOMPATIBLE | commit·재개 검사 | 원본/기존 Episode 변경 금지 |
| IO_ERROR / ENGINE_ERROR / DEVICE_ERROR | 외부 효과 | effect 확인 전 재시도 금지 |

검사는 (1) YAML/Metadata/manifest/입력 자료 로딩, (2) Task 등록·반환, (3) 엔진 binding/복원·live sample, (4) Episode commit, (5) UI IPC 수신, (6) Hub/공식 파일 응답 해석에서 한다. 공식 API 응답도 shape/content를 검증한다. UI 사전 검사와 worker 본 검사는 다른 프로세스에서 변경될 수 있는 입력을 각각 확인하는 것이며 내부 helper마다 중복 검사하라는 뜻은 아니다.

## 3. Scene 패키지 읽기·검증·Export

### 3.1 입력/출력 타입

| 타입 | 필드 |
|---|---|
| `SceneIdentity` | scene_id, revision, manifest_sha256 |
| `FileEntry` | path: package-relative POSIX path, size_bytes: int≥0, sha256 |
| `ScenePackage` | root: Path, identity, scene: SceneSpec, calibration: CalibrationSpec, files: tuple[FileEntry,...], evidence_access: tuple[EvidenceAccess,...] |
| `SceneSpec` | schema_version, units, frames: Map[FrameId,FrameSpec], objects: Map[ObjectId,ObjectSpec], robot, cameras, supports, engines, validation |
| `FrameSpec` | parent: FrameId\|None, T_parent_from_frame: Matrix4, state: reference; dynamic_source?: joint/body binding |
| `ObjectSpec` | name, role, frame_id, visual/collision GeometrySpec, physics, joints, task_geometry?, bindings: Map[Engine,EngineBinding] |
| `GeometrySpec` | kind: primitive\|mesh, primitive dimensions **또는** asset path, scale, frame_id **또는** local_transform; 둘 다 정의 금지 |
| `EvidenceAccess` | evidence_id, sha256, location, access: unchecked\|available\|unavailable\|mismatch |

ScenePackage는 검증된 데이터다. `step`, 장치 연결, frame별 lazy 파일 load를 가진 서비스 객체가 아니다. Object role과 물리적 움직임 여부는 다르다. Joint 상태·현재 pose는 엔진이 소유한다.

### 3.2 함수 계약

| 소유 파일 / signature | 입력 의미·출력 | 효과/오류 |
|---|---|---|
| package `load_scene(entry: Path, *, expected: SceneIdentity\|None = None) → ScenePackage` | entry는 scene.json; 모든 실행 필수 Metadata/파일·참조 확인 | 읽기 전용, 엔진 import 없음; expected 불일치 오류 |
| package `verify_files(root: Path, entries: tuple[FileEntry,...]) → None` | size/SHA·패키지 내부 closure 확인 | 실패는 구조화 예외; hash 검사만으로 동작 PASS 아님 |
| package `validate_scene(scene: SceneSpec, calibration: CalibrationSpec, *, files: tuple[FileEntry,...]\|None=None) → None` | ID·graph cycle·units·Frame/보정 선언 관계. files가 있으면 모델/결과·파라미터 파일 identity 대조 | 파일을 읽지 않음. file-based fit payload 확인은 load_scene이 수행. per-tick helper 아님 |
| transforms `validate_transform(value, *, field="transform") → Matrix4`, `validate_frames(frames) → None` | 기존 float64 SE(3) 검사 및 유일 world root·부모·cycle·reference state | 입력을 정규화/수정하지 않음 |
| transforms `resolve_transform(frames, *, source: FrameId, target: FrameId, state="reference") → Matrix4` | `p_target=T_target_from_source @ p_source` | 기준 graph만 처리, current/live 요청은 FRAME_UNRESOLVABLE. 엔진 조회 없음 |
| Builder export `export_revision(project, *, destination: Path) → SceneIdentity` | 검토 대상 candidate와 보정 identity를 고정해 새 패키지 생성 | staging 검증 후 publish, 기존 destination 교체 금지; 실패 시 기존 원본 불변 |

world root는 parent=None이며 root 변환 identity는 명시 검증한다. graph가 끊기거나 순환하면 실행 불가다. Calibration이 확정한 Transform의 inverse/transpose를 암묵 적용하지 않는다. frame graph의 기준값과 runtime pose를 같은 함수에서 추측해 혼합하지 않는다.

manifest의 자기 hash는 목록에서 제외한다. manifest bytes SHA가 SceneIdentity의 신뢰 기준이며 scene.json·calibration·필수 자산을 목록에 포함한다. 실행 중 파일 변경을 허용하지 않는 불변 export 계약이다. load 확인과 엔진 로딩 사이의 변경을 악의적 쓰기까지 방어한다고 보장하지 않으며 감지된 변경은 중단한다. 추적용 외부 증거 unavailable은 Scene validation 상태를 바꾸지 않는다.

S01의 manifest는 `{schema_version: 1, files: [FileEntry, ...]}`다. 파일 참조 `asset_path`, `asset_paths`, `required_files`, `parameters_file`은 package root 기준이며 반드시 등록되어야 한다. engine entry/mesh의 asset_path 누락, 선언된 Calibration model hash에 대응하는 파일 누락을 거부한다. native asset 내부 closure는 파싱하지 않는다. 외부 evidence는 local hash로 available/mismatch/unavailable, 원격 URI는 접근 없이 unchecked를 반환한다. SceneError는 현재 code/message/issues(field,reason,source)/effect=not_started를 제공하며 더 넓은 실행 오류/장치 effect는 아직 구현하지 않았다.

### 3.3 CalibrationSpec

`records: Map[CalibrationId, CalibrationRecord]`, `evidence: Map[EvidenceId, EvidenceRef]`.

CalibrationRecord의 계약 필드는 `kind`, `target`, `source_model_sha256`, `execution_model_sha256`, `algorithm_id`, `parameters 또는 parameters_file`, `application`, `validation`, `evidence_ids`다. 모델 hash·joint_order는 로봇 모델에 결합된 보정에서 요구하고, 카메라 등 다른 보정에는 해당 입력 Asset/센서 identity를 사용한다. 적용 대상에 없는 로봇 정보를 억지로 추가하지 않는다. application은 다음 두 형태다.

- baked: `asset_paths`, `input_calibration_ids`, `order_index`와 적용된 결과 identity. 실행기는 다시 적용하지 않는다.
- runtime: `phase`(device_observation/device_command/scene_initialization 등 알려진 단계), `input_space`, `output_space`, `joint_order 또는 frame_ids`, `order_index`. 실제 계산은 등록된 기존 구현이며 Metadata 수식을 eval하지 않는다.

기본 보정 없음과 모드 불명은 다르다. v8의 `urdf_identity`, `precision_bound_residual`, `legacy_scene_offsets` 의미를 algorithm/parameter로 식별하고 누락 시 추측하지 않는다. 새로운 record 포장으로 branch/양자화/관측·명령 구분을 없애지 않는다. v8 profile의 정확한 수치와 engine별 baked 결과는 migration 대조표로 고정한다.

S02의 runtime phase는 device_observation/device_command/scene_initialization/camera_render다. 문맥은 target/mode/phase/input_space이며 역할별 관측과 관측/명령을 구분한다. input_calibration_ids의 cycle·순서·입출력 공간과 joint/frame/model identity를 검증하되 fit 근거 dependency를 다른 phase의 실행 지시로 해석하지 않는다. 같은 문맥의 중복 operation/파라미터 또는 동일 모델의 대체 보정을 동시에 적용하지 않는다. baked는 겹치는 결과 Asset의 중복을 거부한다.

v8 precision_bound_residual은 baked Geometry이며 runtime 재적용을 거부한다. 실제 파라미터의 precision_mapping_sha256와 의존 encoder mapping의 canonical SHA·schema/role/model/joint_order를 확인한다. file-based 파라미터는 load_scene이 실제 JSON/읽은 bytes SHA까지 확인한다. 이 검사에 fitter·Encoder 계산·limits-only 재결합·장치 활성화는 포함하지 않는다. 다른 알고리즘의 실행 구현은 해당 소유 모듈에서 검증하며 S02에서 JSON 수식을 실행하지 않는다.

## 4. Recipe 읽기와 실행 입력 고정

`recipe.py`가 다음 타입과 함수를 소유한다. 중앙 models.py/범용 config framework는 추가하지 않는다.

| signature | 반환/검증 | 수행하지 않는 일 |
|---|---|---|
| `read_recipe(path: Path, *, expected_stage: Stage\|None = None) → RecipeDocument` | 원문 bytes·sha256·base_dir·stage별 typed spec; unknown/duplicate key/type 검사 | Python Task import·장치 연결·엔진 시작 |
| `prepare_recipe(doc: RecipeDocument, *, scene: ScenePackage\|None, tasks: TaskRegistry\|None, inputs: InputCatalog) → PreparedRun` | 참조/함수/파라미터/정책 호환, 실제 사용값·identity 확정 | 숨은 UI override·기록 상태 재배치 |

`RecipeSpec`는 stage로 구분하는 union이다. 최소 SourceSpec/AnnotationSpec/DataGenSpec/SimulationEvaluationSpec/TrainSpec/OfflineValidationSpec과 나머지 stage별 기존 표의 shape를 둔다. 공통 필드는 schema_version/stage/inputs/execution/output이며 engine/objects/functions는 적용 stage에서만 허용한다. 타입 내부의 None을 다른 stage 의미로 해석하지 않는다.

`PreparedRun`은 run_id 없는 실행 계획: `recipe_sha256`, `stage`, `engine?`, `resolved_inputs`, `scene_identity?`, `object_order`, `function_bindings`, `effective_settings`, `code_identity`, `output_path`. run ID와 상태는 run.py가 부여한다. 공식 LeRobot 학습은 Scene/Task registry 없이 준비 가능하다.

DataGen의 `effective_settings`에는 고정 Pinocchio DLS + Best Effort identity·파라미터·안전 조건을 시스템이 기록한다. Recipe/CLI/UI의 `ik_solver`/`ik_failure_policy` 및 수치 override는 지원 필드가 아니며 `RECIPE_INVALID`와 field path로 거부한다. 같은 값을 명시해도 허용 옵션이 되지 않으며, 숨은 UI override나 Task 등록을 통한 Solver 교체도 제공하지 않는다.

Recipe 상대 경로는 Recipe 부모 기준. 작업 출력은 신규 디렉터리만 허용하고 예전 결과 덮어쓰기는 거부한다. objects의 YAML 선언 순서를 보존해 `object_order`로 기록한다. 정렬로 기존 Random RNG 소비 순서를 바꾸지 않는다. defaults는 stage별 공식 설정 또는 명시된 제공 v8 profile에서만 오며 해석한 값/출처를 기록한다. Source 성공 gate, Annotation random reset, Evaluation grasp 필수 조건을 암묵 추가하지 않는다.

Annotation은 입력 Dataset의 SceneIdentity가 기준이다. Recipe의 추가 Scene 위치는 **동일 Revision/hash를 찾기 위한 위치**이며 다른 Scene 선택이 아니다. Dataset에 필수 identity가 없으면 migration/확인이 필요하고 최신 v8을 임의 대입하지 않는다.

엔진 binding은 엔진 시작 후 별도 확인한다. 준비 단계에서 구조/선언 검사를 통과한 것과 physics scene 검사를 통과한 것을 UI에서 구분한다. 장치를 실제 제어하거나 Episode를 시작하기 전에 필요한 검사가 모두 끝나야 한다.

## 5. Task 등록·호출 Interface

### 5.1 선언과 검색

`task_modules.yaml`의 `modules: tuple[str,...]`는 명시적 Python module 목록이다. 중복 모듈/등록 이름은 오류다. 외부 파일을 자동 검색하거나 Hub metadata의 module 문자열을 자동 import하지 않는다. 사용자 Python은 신뢰하고 등록한 코드이며 sandbox라고 주장하지 않는다.

모듈은 `FUNCTIONS: Map[str, FunctionSpec]`를 노출한다. FunctionSpec은 다음 작은 **선언 데이터**다. 단순 함수에 상속/데코레이터를 강제하지 않는다.

| 항목 | 타입 / 의미 |
|---|---|
| contract_version | int, 첫 값 1 |
| kind | predicate / tracker / placement / metrics / acceptance |
| stages | 허용 Stage 집합 |
| engines | 허용 Engine 집합; engine-independent이면 명시 |
| params_type | 해당 Task 파일의 dataclass 등 타입 정의; object/frame/support 참조 필드 표시 |
| requires | 필요한 상태 필드와 named signal 목록; 자유식/실행 코드 없음 |
| bindings | stage별 고정 호출 phase와 필요한 signal 제공 함수/파라미터 기본값; 필요할 때만 선언. Python 선언 자료이며 Recipe DSL이 아님 |
| callable | 일반 함수 참조 **또는** tracker factory; import string을 Recipe에 노출하지 않음 |

파라미터 검사는 registry에서 한 번 수행한다. type annotation으로 표현 못하는 관계는 Task 모듈의 `validate_params(params, scene) → None` 일반 함수로 제공할 수 있다. engine support를 단순 선언했다고 실제 구현 검증 완료로 표시하지 않는다.

T01의 실제 함수는 registry.py의 `read_module_names(path) → tuple[str,...]`, `load_registry(module_names) → TaskRegistry`, `resolve(registry, name, *, kind, stage, engine=None) → FunctionSpec`, `validate_params(registry, name, values, *, kind, stage, engine=None, scene=None, selected_objects=None) → P`다. registry는 module declarations와 검증된 callable의 map이다. 별도 manager/plugin factory 계층이 아니다. UI 조회 시 import하지 않고 명시 검증 worker가 제공하는 serializable 설명만 받는다. 실행 worker는 다시 원본 모듈을 읽고 identity를 확인한다.

T01 구체 계약: 모듈 목록은 YAML의 단일 `modules` list이며 duplicate/unknown key·anchor/alias·Python tag를 거부한다. FunctionSpec의 params_type은 dataclass이고 str/bool/int/finite float·Literal·Union/Optional·list/tuple/dict[str,T]·중첩 dataclass를 지원한다. Scene 참조 필드는 `field(metadata={"reference": "object"|"frame"|"support"})`로 표시한다. load_scene으로 검증된 ScenePackage를 받아 ID를 확인하고 생성 목록에서 빠진 task_object는 거부한다. 이름/관계의 실제 수식·좌표·단위 변환은 하지 않는다.

Task 엔진 ID는 Scene과 같은 isaac/mujoco이며 독립 계산은 단독 independent다. Recipe의 isaaclab 표기를 Scene/Task의 isaac로 명시 연결하는 책임은 R02 준비 단계이며 T01은 Recipe override/엔진 fallback을 수행하지 않는다. bindings의 stage별 자료는 `{phase, signals?: {name: {function, params?, delayed?}}}`다. 선언 provider의 역할/지원·부분 defaults·cycle·역 phase를 검사하고 보존하되 tracker 생성·signal 공급·Recipe 합성은 후속 단계다. T02에서 기본 task_modules.yaml에 robot_learning_workbench.tasks.pick_place를 등록했다. 등록이 엔진 실행/완성을 뜻하지 않는다.

TaskError는 code/message/issues(field,reason,source)/effect=not_started이며 TASK_MODULES_INVALID·TASK_IMPORT_ERROR·TASK_DECLARATION_INVALID·TASK_UNKNOWN·TASK_UNSUPPORTED·TASK_PARAMS_INVALID·OBJECT_NOT_SELECTED를 구분한다. TaskRegistry는 함수 map·모듈 순서·직접 source 파일 SHA·선택적 validate_params 참조의 읽기 전용 데이터다. source SHA는 간접 의존성 전체나 기존 import cache의 메모리 코드 identity를 증명하지 않는다. 신뢰된 모듈 import/type/default/custom validator의 Python 실행을 sandbox로 제한하지 않으며 Task 함수/factory는 등록/파라미터 검사에서 호출하지 않는다. 구체 사용/완료 경계는 [T01 보고서](t01-task-registry.md)를 따른다.

### 5.2 호출 형태와 상태 자료

| 종류 | signature | 반환 의미 |
|---|---|---|
| predicate | `fn(sample: TaskSample, *, params: P) → bool` | 순수 판정; false는 정상 실패 |
| metrics | `fn(sample: TaskSample, *, params: P) → Map[str, MetricValue]` | finite 수치/명시 unavailable 값과 단위 |
| tracker factory | `create(*, params: P, episode: EpisodeContext) → Tracker` | Episode/env별 새 인스턴스 |
| tracker update | `update(sample: TaskSample) → SignalValue` | 지정 phase에서 한 번 갱신; bool/필요 diagnostics |
| acceptance | `fn(final: TaskSample, *, params: P) → bool` | 이미 갱신된 signal·최종 상태를 조합, 새 tracker 생성 없음 |
| placement | `fn(request: PlacementRequest, *, params: P) → PlacementResult` | 좌표가 명시된 pose/후보 횟수 반환; 엔진에 직접 쓰지 않음 |

EpisodeContext는 `episode_id, env_index, engine, control_dt_s, scene_identity`를 갖는 읽기 전용 자료다. 엔진이나 writer 핸들을 포함하지 않는다.

Tracker는 update가 있는 구체 객체의 구조적 계약이며 ABC/base class를 새로 만들지 않는다. 기존 StableGrasp를 일반 factory에서 생성할 수 있다. immutable SignalValue는 `value: bool, tick, phase, diagnostics`이며 nullable 성공을 true로 바꾸지 않는다.

TaskSample은 `episode_id, env_index, tick, phase, dt_s, pose_frame, object_poses, eef_pose?, joint_positions?, joint_order?, contacts?, linear_velocities?, signals`와 T02의 `grasp_inputs?`, `placement_points?` 중 requires에 필요한 자료만 담는다. pose는 Matrix4, contacts는 대상 ID·left/right boolean과 `source_definition`(threshold/body pair)이다. Engine env/model/data, 파일 reader, control command API는 넣지 않는다. World↔robot_base↔target local 변환 책임과 quaternion 변환은 기존 식에 맞춰 binding에서 명시한다. current sample의 pose_frame을 기준 Metadata의 frame으로 오해하지 않는다.

엔진 소유 ndarray/tensor는 다음 step으로 변할 수 있다. 동기 함수 호출 중 읽기 전용으로 빌려주고, tracker가 창에 보관할 값과 writer 비동기 입력은 소유하는 복사본을 만든다. full image/tensor를 Task마다 CPU로 복사하지 않는다. 다중 환경 tracker는 env_index별로 분리하며 전체/일부 reset 때 해당 인스턴스만 새로 만든다.

T02 구체 계약: sample/episode는 읽기용 mapping 자료다. `grasp_inputs={object_id, relative, relative_quat, quaternion_order, ee_position, object_position}`는 기존 tracker 직전 중간값을 그대로 전달한다. `placement_points={ObjectId: {target_id, points: 8x3}}`는 기존 target-local corner 계산의 결과이며 다른 target의 배열은 거부한다. raw quaternion/point dtype을 바꾸거나 엔진 간 pose 계산을 새 공통 식으로 대체하지 않는다. T01 registry는 이 두 requires 필드만 추가 인식하며 native 추출/공식 MDP 연결은 엔진 단계다.

T02의 `GraspParams(object)`와 `PickPlaceParams(object,target,relation,max_speed_m_s,bounds_m)`는 Task 파일의 일반 dataclass다. 모듈 validate_params hook이 Scene의 task_geometry 치수를 확인해 immutable PlacementGeometry를 private cache에 연결한다. cache는 YAML 입력 필드가 아니며 기준 Metadata를 변경하지 않는다. user-provided Collision Geometry로 기존 판정 치수를 대체하지 않는다.

`create_stable_grasp(*,params,episode)`가 소유한 상태의 `update(sample) → SignalValue`는 post_step에서만 수행한다. `observe(...)`는 기존 raw 수식 그대로인 계산 경계다. pre_step 저장은 completed의 이전 값을 snapshot하며 update로 앞당기지 않는다. SignalValue는 value/tick/phase/읽기 전용 diagnostics이고 object/contact 정의·Quaternion 순서를 남긴다. contacts는 measured bool과 구분된 source_definition을 요구한다. 새 live 입력 오류는 TASK_SAMPLE_INVALID다. T02 함수 6개의 phase/역할·입력·미완료 통합 범위는 [결과 보고서](t02-pick-place.md)를 따른다.

### 5.3 v8 호출 순서

| 시점 | Source | Annotation / Production DataGen | Simulation Evaluation |
|---|---|---|---|
| Episode 시작 | 선택 배치 적용 후 실제 initial 저장 | Annotation은 기록 initial 복원, DataGen은 새 배치; 새 tracker | 평가 초기 배치·새 지표 상태 |
| pre_step(t) | observed q/이미지, requested/applied target 기록 | 기존 이벤트 배열은 이 시점 latch를 기록 | 기존 평가 경로의 관측/Policy 입력 |
| 물리 실행 | 공식 엔진 제어/substep | 공식 엔진 실행 | 공식 엔진 실행 |
| post_step(t) | 요구한 Source 신호만; 기본 성공 gate 없음 | 접촉/상대 pose → StableGrasp.update 한 번 → release 진단 | 기존 평가의 접촉/지표 갱신과 Placement 검사 시점 유지 |
| Episode 종료 | 사용자 저장/취소 의미 | Placement AND latched grasp, manual mark 조건은 별도 | 기본 Placement 성공 시 종료; full_task_success는 별도 지표 |

registry는 phase를 임의 정렬하지 않는다. stage의 제공 v8 function binding이 호출 시점을 소유하고 사용자 Recipe가 pre/post-step을 선택하지 않는다. acceptance가 grasp를 requires로 선언하면 준비 시 기존 named signal binding을 연결한다. 이미 선언된 동일 grasp는 재사용하고 conflicting params/두 인스턴스는 오류다. 누락 시 암묵 fallback이 아닌 제공 v8 binding의 명시된 기본 dependency를 사용해 effective_settings에 기록한다. 이로써 기존 Annotation 예시의 acceptance-only Recipe도 필요한 tracker가 명확히 연결된다.

Task signal dependency는 값 의존 관계만 표현한다. cycle 또는 동일 tick에 post 결과를 pre에서 요구하면 오류다. 이전 tick latch를 pre에 기록하는 v8 계약은 명시된 delayed input으로 구분한다. 범용 DAG 스케줄러를 추가하지 않고 해당 stage의 고정 평가 순서에서 검사한다.

StableGrasp의 threshold/window/tick/latch, Placement의 8꼭짓점/속도/부등호는 기존 계산을 그대로 사용한다. engine contact 차이는 source_definition으로 남긴다. 새로운 Task 판정 추가를 위해 기존 v8 함수를 수정하지 않는다.

### 5.4 배치 입력

PlacementRequest: `object_id`, `frame_id`, `support_id`, `orientation`(해석 완료), `collision_geometry`, `occupied_poses`, `rng`, `rules_id`. Fixed는 추가 `xy_m`, Random은 허용 영역·margin/간격의 검증된 조건을 받는다. rng는 seed stream 소유자가 넘기며 함수가 전역 RNG를 새로 seed하지 않는다.

PlacementResult: `object_id, frame_id, pose: Matrix4, attempts: int, rules_id, diagnostics`. 함수는 위치 보정/영역 확대를 하지 않는다. Random 1,000회는 후보 검사 총 횟수이고 바깥 stage가 카운터를 초기화해 다시 호출하지 않는다. 구조 오류는 후보 실패로 세지 않고 즉시 오류다. 일반 Geometry 배치에서 엔진 로딩 후 확인 가능한 충돌 후보를 재추출한다면 동일 예산을 사용한다. 다만 [B01](b01-baseline.md)에서 확인한 v8 MuJoCo는 sampler 후보 예산과 별개로 engine pose 적용 실패 시 즉시 오류·rollback하고 이 API에서 재추출하지 않는다. 이 v8 경계는 그대로 보존하며 일반 배치 규칙을 암묵 적용하지 않는다.

v8 3mm·기존 sampling 검사와 collision_contact의 일반 계산은 별도 rules_id로 구분한다. Recipe에서 자세를 변경했다면 새 계산을 요구하는 입력이므로 v8 기본 자세 Baseline 동등성으로 취급하지 않는다. 새 지원이 기존 동작을 바꿔야 하는 경우만 사용자 결정 대상으로 올린다.

T03 구체화: placement.py의 frozen PlacementRequest/PlacementResult/PlacementParams와 `fixed_xy(request, *, params)`, `random_xy(request, *, params)`를 제공한다. Request의 xy_m/orientation/rng/occupied_poses는 실행 준비가 제공하는 데이터이며 orientation 생략 시 Metadata default를 사용한다. T03은 collision_geometry를 읽거나 일반 접촉 높이를 계산하지 않는다. object.task_geometry.dimensions_m, supports[id].object_id/placement_frame_id와 S02 reference graph를 사용한다. v8_preserved는 기록된 placement_frame에서 기존 bbox 높이+3mm를 계산하며 다른 frame/일반 규칙을 자동 대체하지 않는다.

Fixed는 XY를 유지하며 기존 support/회전 bbox와 선언 separation을 검사한다. Random은 기존 uniform/축별 separation만 재추출 조건이며 후속 pose/engine 검사를 재시도 예산에 합치지 않는다. attempts는 Random draw 횟수(Fixed=0)다. Result.pose와 diagnostics는 read-only이며 physical_collision_checked=false를 명시한다. PLACEMENT_EXHAUSTED는 object/support/frame/rules·조건/attempts/마지막 XY를 기록하고 run 중단에 연결해야 한다. 실제 중단·완료 Episode 보존·물리 rollback/Writer 검증은 후속 단계다.

`environment_seed(seed,index,*,num_envs)`는 원래 per-env SeedSequence 계산만 제공하고 RNG 생성/전역 seed를 수행하지 않는다. 전체 batch sample_index·Robot joint 초기화·Source/DataGen seed continuation은 stage 소유이며 per-object 함수를 호출할 때 증가시키지 않는다. 등록은 Source/DataGen/Simulation Evaluation으로 한정하고 Annotation initial 복원에 사용하지 않는다. 수치/지원 범위·의도된 Fixed 선행 검사와 four_anchors 제외는 [T03 결과](t03-placement-reset.md)를 따른다.

T04 구체화: 같은 모듈의 `placement.contact_fixed_xy/contact_random_xy`는 ContactParams(object/frame/support, rules=collision_contact, margin_m=0, separation_m=0)와 기존 요청/결과 타입을 사용한다. v8 함수/파라미터를 자동 대체하지 않는다. 지원 범위는 box 또는 폐쇄 convex triangle mesh 부품과 convex 평면 support다. 준비 시 Scene의 collision 목록/Manifest를 읽고 불변 배열로 연결하며 배치 호출은 파일/엔진을 접근하지 않는다. 자세 생략 시 Metadata 기본 자세를 사용하고 입력 frame XY를 유지한 +Z 접촉 높이를 계산한다.

Support는 frame_id(그 frame의 z=0 평면)와 반시계 region_xy_m polygon이다. primitive box는 dimensions_m, mesh는 asset_path의 JSON schema_version=1/vertices_m/triangles를 사용하며 각 부품은 scale 및 frame_id XOR local_transform이다. 파일 등록/무결성과 폐쇄 convex 조건을 검사한다. 곡면·비평면·미지원 native 형상은 오류이며 task bbox로 대체하지 않는다. 자세/footprint로 가능한 원점 영역을 계산한 뒤 입력 frame XY bounding rectangle에서 후보를 뽑아 검증한다. 후보당 uniform 1회·최대1000회, 구조 오류는 즉시 중단한다. 부품별 투영 간격은 높이가 분리된 물체도 거부할 수 있는 보수적 2D 검사이며 physical_collision_checked=false다. 완전한 3D collision/solver·안정성·엔진 형상 동등성 검증은 아니다. 일반 길이 tolerance=1e-9m, +Z/법선 내적>1e-8이며 v8 tolerance/3mm/RNG와 분리한다. [T04 보고서](t04-collision-contact.md)에 파일 계약·오류/예산·미지원 범위를 명시했다.

## 6. 엔진별 실행과 공식 API

공유하는 것은 PreparedRun/TaskSample/Episode contract이며 엔진 runtime 객체는 공유하지 않는다. 다음은 각 구체 모듈의 함수이며 공통 Engine Interface를 만들라는 뜻이 아니다.

| 모듈 | signature / 공식 호출 | 책임 |
|---|---|---|
| isaac/env_cfg.py | `build_env_cfg(scene, prepared) → ManagerBasedEnvCfg` | InteractiveSceneCfg/Articulation/RigidObject/Camera/ContactSensor 구성 |
| isaac/mdp.py | 공식 Term signature `fn(env, ...)`; Event는 env_ids 포함 | 공식 Action/Observation/EventTermCfg에 필요한 계산 연결 |
| isaac/state.py | `read_sample(env, env_index, phase, tick) → TaskSample`; `restore_episode(env, env_ids, initial) → None` | scene/root/joint 기록 복원, 기준 pose 검증, 센서 갱신 시점 |
| mujoco/model.py | `build_model(scene, prepared) → (MjModel, bindings)` | 실행 MJCF 조합, 실제 body/geom/joint lookup |
| mujoco/state.py | `read_sample(model, data, bindings, phase, tick) → TaskSample`; `restore_episode(model,data,bindings,initial) → None` | qpos/qvel·필요 state·mj_forward·기록 복원 검증 |
| 각 엔진 source/annotation/datagen/evaluation.py | 각 파일의 `run(prepared: PreparedRun, *, events, commands) → StageResult` | 해당 엔진 loop·수명·writer 소유; stage.py라는 추가 파일 없음 |

`events`는 `Callable[[WorkerEvent], None]`, `commands`는 `Callable[[], tuple[Command,...]]` 형태의 전달·비차단 수신 함수다. 별도 event bus 객체를 만들지 않는다. 지원하지 않는 명령은 명시적으로 거부하며 Training에 pause/step을 구현하기 위해 공식 Trainer를 변경하지 않는다.

StageResult는 `status: completed|cancelled`, `output_refs`, `completed_episodes`, `attempt_summary`다. 오류는 예외로 run이 failed 기록을 만든다. engine 루프의 동작을 통일하기 위해 return tuple을 강제로 Gym step 형태로 바꾸지 않는다.

Isaac은 worker의 선택 분기에서 공식 AppLauncher를 만들고 이후 engine imports를 수행한다. 공식 `ManagerBasedEnv.step/reset/reset_to`, asset `write_root_pose_to_sim/write_joint_state_to_sim` 중 기존 기록 의미에 맞는 것을 사용한다. reset_to가 있다고 automatic startup/reset event를 중복 적용하지 않는다. MuJoCo는 `MjData(model)`, `mj_step`, `mj_forward`, 공식 state API를 직접 사용한다. 기록 snapshot과 물리 step 사이에 참조 배열을 변형하지 않는다.

호출 근거: [Isaac Lab 2.3.0 envs](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html), [MuJoCo 3.3.7 Python](https://mujoco.readthedocs.io/en/3.3.7/python.html). 설치 코드에서도 ManagerBasedEnv.reset/reset_to/step, ActionTermCfg/ObservationTermCfg/EventTermCfg를 확인했다. 버전 업그레이드는 이번 설계 범위가 아니다.

### DataGen IK의 고정 호출 경계

`generation/mimic.py`의 일반 계산 함수는 engine handle 없이 보정 모델의 Pinocchio 계산 상태, robot_base 기준 target pose, 측정 관절값, 직전 실제 적용 명령, 그리퍼 목표 및 관절 limits를 받는다. 반환은 적용 가능한 6관절 명령과 진단이며, 부적합 candidate는 기존 오류 전달 방식으로 해당 attempt 중단을 알린다. Solver/Failure Policy/튜닝 인자는 없다. 작은 결과 자료/오류는 소유 모듈에 두며 새로운 Solver Interface·ABC·factory는 만들지 않는다. 수치와 경계는 [상세 SPEC](../SPEC-simulation-workflows.md#datagen-ik-고정-계약)을 따른다.

엔진 `datagen.py`가 env별 mutable Pinocchio Data·previous_command를 소유한다. 측정 팔 관절값은 DLS seed이고 previous_command는 **팔 관절별 >0.5 rad 점프 검사 기준**이다. reset/restore에서 초기 적용 명령을 고정하고 실제 명령 적용 뒤 갱신한다. DLS 미수렴/pose 진단 실패와 candidate 안전 거부를 구분하며, 유효한 candidate는 Best Effort로 적용하고 Hold·SciPy fallback은 없다. 엔진 제어·physics는 기존 공식 경로를 사용한다.

stage는 안전 거부를 실패 attempt로 분류하고 기존 budget 안에서 처리한다. 미수렴 진단만으로 성공/실패를 확정하지 않으며, 성공 채택은 **latched StableGrasp AND Placement**다. pre-step 기록·post-step 접촉/tracker·종료 시점은 기존대로 유지한다. 이번 결정은 DataGen에 적용하며 Annotation·기본 Simulation Evaluation 판정 계약을 변경하지 않는다.

## 7. Native Episode·Curation·publish·Resume

2026-10-26: C를 최종 채택했다. 폐기한 A의 EpisodeWriter/Reader/Index/Descriptor/source_ref API는 제공하지 않는다. B02의 원래 배열 경로·dtype·단위·phase·initial·성공 의미를 공식 HDF5에 그대로 넣는다. S64 등 Tensor 밖 필드와 attrs/lineage/identity만 압축 Sidecar에 보존한다.

| 소유 파일 / 호출 | 계약 |
|---|---|
| native `native_api()` | 설치 Isaac Lab 2.3의 실제 EpisodeData/HDF5DatasetFileHandler 반환, lazy import |
| `NativeRun(output,execution,metadata=None)` | 새 출력·단일 파일 소유권. 실행 제어 run.py의 run_dir와 저장 Dataset 디렉터리는 구분 |
| `run.segment(intent_id,request=None)` | 같은 실행 의도/같은 요청은 기존 published 결과, 다른 요청 conflict, 불명 pending은 NATIVE_STATE_UNKNOWN |
| `segment.write_episode(official_episode,episode_id,metadata,media)` | 공식 pre_export/write_episode, known T/shape·닫힌 MP4 header만 검사. 반환 demo key는 pending |
| `segment.commit()` | 공식 flush/close → HDF5 header/count·파일 fsync → segment.json.gz → 디렉터리 atomic publish. 여기서만 완료 |
| `load_catalog(path,expected=None)` | published segment/공식 HDF5 또는 공식 LeRobot Metadata, curated JSON을 판별. `.staging` 제외 |
| `open_native(ep)` | 실제 공식 handler. 호출자가 close, 엔진 import/실행 없음 |
| `read_array(ep,name,frames=True)` | h5py의 공식 HDF5 hyperslab; 전체 Episode/영상 eager copy 없음 |
| `recover(root,acknowledge_interrupted=False)` | inactive owner 확인; pending을 보고. 명시 확인해도 interrupted_unknown, 자동 성공/재시도 없음 |
| `resume_to(previous,output,execution,independent=False)` | 모든 필수 identity/history/budget 검사 후 새 출력에 닫힌 Native 파일 hardlink. 독립 copy는 명시 옵션 |
| `import_hdf5` / `import_canonical` | 원래 프로젝트 자료의 명시 import. archive_only로 누락 runtime identity를 추측하지 않음. A 포맷 loader 없음 |

DatasetIdentity는 `dataset_id,metadata_sha256`다. Metadata SHA는 실행/완료 segment·보존 provenance identity이며 배열/영상의 전체 SHA가 아니다. NativeEpisode는 episode_id/file/key/num_frames/metadata/media/source_root/start/stop/selection_id/format의 작은 참조 자료다. Catalog.kind는 native/curated/lerobot를 구별한다. 닫힌 파일은 불변이며 정상 close의 status 변경은 데이터 identity를 바꾸지 않는다.

정상 commit에서 배열 전체 SHA, 영상 전체 decode/PTS 검사, 기존 완료 파일 재해시는 하지 않는다. 파일 손상 전수 audit는 별도 오프라인 검증이다. 실제 지원 보장은 동일 로컬 filesystem의 atomic rename/fsync와 단일 writer 범위이며 전원 장애/NFS·적대적 사후 변경 보장이 아니다. 완료 전의 여러 Episode는 한 segment 실패 시 모두 pending으로 남는다. segment 크기를 실행 단계가 정하고 sample/seed/성공 조건과 혼동하지 않는다.

### 7.1 영구 Curation

`save_curation(path,source,exclude=(),order=None,frame_ranges=None,splits=None,split_provenance=None)` → Catalog, `load_curation(path,expected=None,relocations=None)` → Catalog, `select_split(catalog,split)` → Episode tuple. 새 V2는 V1 membership/range 안에서 편집하며 제외 자료가 자동 복원되지 않는다. source identity·순서·half-open frame range·disjoint train/val/test membership만 JSON에 저장한다. 원본 배열/영상은 복사하지 않는다. 삭제/이동/Metadata 변경은 CURATION_SOURCE_INVALID이며 명시 relocation도 같은 identity를 확인해야 한다. API/UI는 kind로 원본과 view를 구별한다.

`export_native(source,output,split=None,segment_episodes=10)`은 전체 Episode의 독립 공식 HDF5/원 MP4 copy다. 중간을 자른 구간에 과거 initial state를 새 initial처럼 붙이지 않고 REPLAY_INITIAL_UNAVAILABLE로 차단한다. 구간 학습 export는 LeRobot materialize를 사용한다. 원본에 없는 initial state가 필요한 재시뮬레이션은 후속 명시 실행이다.

### 7.2 LeRobot 학습 materialization

`materialize(source,output,split=None,feature_map=None,independent=False,task=None)`는 선택한 Episode/구간만 official Parquet에 재색인하고 원본 frame/time을 source.frame_index/source.timestamp로 함께 보존한다. 선택 안 된 수치 row는 output에 없으므로 공식 factory/Trainer는 episodes 필터 없이 사용한다. 영상은 원 MP4 hardlink 및 official video offset이다. 선택 범위 밖 packet이 파일에는 남을 수 있지만 공식 item/학습 row에는 노출되지 않는다. independent=True일 때만 원 MP4 전체 copy하며 GOP 중간 독립 clip/remux/re-encode는 구현하지 않았다.

설치 0.4.1의 pinned `_save_episode_data` + 공개 Metadata.save_episode/공식 stats를 사용한다. private 호출을 숨기지 않고 버전 guard로 차단하며 SDK monkeypatch/Trainer/subclass는 없다. 기본 save_episode는 기존 MP4 변환에 호출하지 않는다. 새 real recording은 공식 create/add_frame/save_episode/finalize를 그대로 쓸 수 있고 동일 staging publish 경계를 쓴다. output이 이미 있거나 이전 staging이 남으면 자동 append/재시도하지 않는다.

Raw Parquet float64와 공식 __getitem__ float32 도출을 구분한다. 기본 매핑은 measured model joint state와 기록된 model joint target이며 별도 측정 applied action/LeRobot gripper fraction이라고 주장하지 않는다. Policy/processor action 의미 확인은 L/P 단계다. 원래 raw time·dtype·전체 Mimic/IK/initial을 학습 projection 대신 보존용 Native에서 유지한다.

### 7.3 Resume identity와 시점

Source/DataGen과 P01의 simulation_evaluation은 완료 파일 경계 재개를 지원한다. Evaluation의 추가 identity·실패/완료 의미는 아래 P01 절을 따른다. engine/Scene/Calibration/Task/model/recording frame·unit·phase·joint order/active objects/partition/RNG policy/seed가 명시돼야 한다. DataGen에는 annotated_input/source_pool_order와 IK solver/policy/code/model/frame/joint_order/parameters/safety/seed_reference가 필수다. 고정 Pinocchio DLS + Best Effort만 continuation하며 SciPy/Strict/Hold/불명 identity는 거부한다. Source partition 자료는 수집 이어가기를 거부한다. 실제 runtime binding은 E06의 책임이고 이번에 가짜 hash를 생성하지 않았다.

성공 attempt와 완료 Episode identity/개수 일치, max attempt·누적 목표를 출력 생성 전에 검사한다. Source 새 claim은 base_seed+attempt-1, DataGen은 SeedSequence([seed,attempt]); 미확정 attempt 번호/seed를 다시 실행하지 않는다. B02 옛 discard/RNG 전체 state 누락이 정확 continuation으로 승격되는 것은 아니다. 중간 physics tick/Annotation/Evaluation continuation은 제공하지 않는다.

B01의 post tick222→저장223, Isaac221→222, manual203은 원 배열 그대로다. 공식 Pool의 half-open 끝 first1+1을 post-step 물리 tick으로 재해석하지 않는다. Source recording_only, Annotation/DataGen 채택 AND, Evaluation Placement 종료/완료 failure 의미는 그대로다.


## 8. UI↔작업 프로세스 계약

### 8.1 실행 함수와 고정 입력

`run.py`에 `start(request: StartRequest) → RunHandle`, `execute(request: WorkerRequest) → RunResult`, `send_command(handle, command) → CommandReceipt`, `read_status(run_dir) → RunStatus`를 둔다. 이전 start/execute/cancel 표현을 구체화한 것이며 새 중간 계층은 아니다. cancel은 kind=cancel 명령으로 처리한다.

StartRequest: `request_id, recipe_path, expected_recipe_sha256, expected_stage, task_modules_path?, expected_modules_sha256?, output_path`. UI/CLI가 저장 파일을 읽어 만든 값이다. task_modules는 장치/학습처럼 필요 없는 stage에서 생략한다. effective output은 Recipe와 일치해야 한다. 같은 request_id는 같은 실행 의도의 재전송에서 유지하고 별개의 새 실행만 새 ID를 사용한다.

RunHandle은 `run_id, request_id, run_dir`와 로컬 제어 채널 참조를 반환한다. RunStatus는 `status, phase, progress, last_event_seq, error?`, RunResult는 `run_id, status, output_refs, error?`다. 반환된 핸들만으로 장치 동작 성공을 뜻하지 않는다.

WorkerRequest는 위 고정값과 `run_id`, 선택된 Python 환경 정보를 포함한다. worker는 저장 YAML을 **한 번 읽은 bytes**로 hash와 parse를 수행한다. 검사 후 다시 원본 파일을 읽어 설정을 바꾸지 않는다. 이후 편집은 다음 실행에만 적용한다. 공식 training_config·module 목록·Scene·Dataset도 실행 준비에서 identity를 고정한다.

### 8.2 중복 start와 결과 불명

- run root의 request claim 파일은 `O_CREAT|O_EXCL` 등 단일 배타 생성으로 선점한다. 존재 검사 후 생성하는 방식은 사용하지 않는다. 선점 후 payload SHA/run ID/상태를 durable 기록한 뒤 worker를 시작한다.
- 같은 key+같은 payload: 실행 중이면 기존 RunHandle 반환, 종료됐으면 기존 결과 위치 반환. 다른 payload는 REQUEST_CONFLICT.
- 선점은 되었으나 기록/worker 상태를 확인할 수 없으면 RUN_STATE_UNKNOWN. 시간 초과만으로 새 worker를 띄우거나 기존 claim을 지우지 않는다. PID만으로 실행 identity를 판정하지 않는다.
- worker 시작에도 같은 run의 worker claim을 두어 UI 이중 클릭/동시 요청으로 두 모터/엔진 실행이 시작되지 않게 한다. claim은 run 수명 기록과 함께 보존하며 짧은 TTL을 두지 않는다. 자동 재전송은 기록이 보존된 run 범위에서만 지원한다.
- process exit를 확인해 실패로 확정하는 것과 통신이 끊겨 효과를 모르는 상태는 구분한다. unknown은 UI의 관측 상태이지 이미 저장된 정상 Episode를 실패/삭제하는 명령이 아니다. 하드웨어 명령과 Hub 업로드의 불명 결과는 자동 재실행하지 않는다.

### 8.3 메시지 형식과 순서

각 메시지 envelope는 `{protocol_version: 1, run_id, seq, kind, payload}`다. seq는 해당 송신 stream에서 증가한다. 명령에는 `command_id`와 대상 `episode_id?/env_index?`가 추가된다. JSON control channel과 engine stdout 로그를 분리해 라이브러리 출력이 JSON parser를 깨뜨리지 않게 한다. 기존 로컬 IPC 방식 안에서 구현한다.

| 방향/kind | payload 핵심 | 동작 |
|---|---|---|
| worker→UI status | phase: preparing/running/stopping/terminal, run status, progress counters | 최신 상태 snapshot으로 복구 가능 |
| worker→UI log | level, message, source | 읽기용; 제어 명령으로 해석 금지 |
| worker→UI episode_committed | Native Episode 참조, Dataset metadata identity | 완료 index에서 재확인 가능 |
| worker→UI preview | camera, slot/generation, frame index/time | 공유 메모리 등 기존 채널 참조; 덮어쓴 frame은 버림 |
| worker→UI error | 공통 오류 레코드 | machine code와 사용자 설명 분리 |
| worker→UI command_ack | command_id, accepted/rejected/completed, applied_tick? | 수신과 적용 완료 구분 |
| UI→worker pause/resume/step | 대상 env/Episode, step 횟수(지원 시) | stage별 허용 검사; 미지원이면 거부 |
| UI→worker mark/skip | 대상 Episode, event name/표시 tick | 실제 적용 tick을 ack; 뒤늦은 다른 Episode 적용 금지 |
| UI→worker cancel | reason | 반복 요청 무효과, 안전 경계에서 정리 |

동일 command_id+같은 payload는 기존 ack를 재사용하고 step/mark를 두 번 적용하지 않는다. 다르면 오류. 적용 중 응답이 끊기면 명령 상태를 확인하고 새 ID로 재전송하지 않는다. 물리 명령의 완전 exactly-once 보장은 하지 않으며 재접속 후 unresolved command는 명시 오류로 남긴다.

진행/Preview는 최신 상태로 합칠 수 있다. command ack/error/terminal/commit은 임의 누락하지 않고 run 파일/event 기록으로 재조회 가능해야 한다. 영상 Preview 속도가 Dataset 기록 속도를 제한하지 않는다. UI 종료는 기존 장치 종료/협력 cancel 정책을 따르고 headless CLI와 동일하게 취급해 장치를 방치하지 않는다. 구체 장치 중지 동작은 기존 안전 계약을 보존한다.

UI 이벤트 조회 `read_events(run_dir, after_seq, limit=200) → EventPage`는 제한된 페이지를 반환한다. terminal 결과는 프로세스 연결 상태가 아니라 run record를 기준으로 표시한다. 무제한 로그 전체를 매번 다시 읽지 않는다.

## 9. LeRobot·결과 조회·Offline Validation

학습 실행 Interface는 `train(prepared: PreparedRun, *, events, commands) → StageResult`다. 역할은 공식 config 검증/정확한 실행 argv·환경 기록/프로세스 수명 관리뿐이다. 공식 [LeRobot 0.4.1 train](https://github.com/huggingface/lerobot/blob/v0.4.1/src/lerobot/scripts/lerobot_train.py)을 사용하고 loop/optimizer/scheduler/validation에 UI hook을 넣지 않는다. 공식 log 원문을 읽는 것으로 metrics를 가져오며 custom Trainer를 만들지 않는다.

필요 시 `learning/results.py`의 `read_metrics(log_ref, *, cursor=None, limit=200) → MetricPage`만 추가한다. MetricPoint는 `name, value, step?, time?, source_run, source_kind, source_location`. 없는 LR/Validation Loss는 unavailable이며 새 forward/검증을 실행해 채우지 않는다. train→results 의존은 없고 UI→results→공식 output 읽기만 있다.

Offline Validation은 별도 `evaluate(spec: OfflineValidationSpec) → ValidationResult`: input Dataset identity·저장 Policy/Checkpoint identity·공식 processor, batch 설정을 받는다. 결과는 자체 run에 기록하고 원본 checkpoint/optimizer를 쓰지 않는다. Training 종료 후 자동 호출하지 않는다. MiniVLA 코드·학습 관리·그래프·Checkpoint 호환 구현은 없다.

Dataset 변환은 공식 create/add_frame/save_episode/finalize 기능과 새 Episode 의미 매핑만 연결한다. 외부 LeRobot Dataset에 프로젝트 Scene identity를 추가하도록 요구하지 않는다. Hub의 metadata/path/feature 응답은 로딩 진입점에서 검사하고 인증 값은 snapshot하지 않는다.

## 10. Interface 검증 및 남은 확인

| 계약 시험 | 기대 |
|---|---|
| 잘못된 frame/object/함수/파라미터/type·unknown Schema | 공통 code/field로 시작 차단; identity fallback 없음 |
| 같은 Scene 다른 경로, 같은 Revision 다른 bytes | 전자는 동일 identity, 후자는 오류 |
| engine callback과 동일 tick의 tracker 재호출 | 기존 latch/window·첫 성공 tick 유지, 중복 갱신 없음 |
| acceptance-only v8 설정 | 명시 제공 dependency로 grasp 인스턴스 1개, pre/post 순서 동일 |
| DataGen 고정 IK | 선택 필드 시작 차단; 유효 미수렴 candidate 적용, shape/finite/limit/jump 거부, StableGrasp AND Placement로 채택; B01 대비 승인 변경 보고 |
| 두 start 동시 요청 / 같은 key 다른 payload | worker 한 개 / conflict |
| claim 후 crash / worker 시작 후 ack 유실 | unknown 또는 기존 상태 조회, 자동 이중 시작 없음 |
| commit 전/후 응답 유실 / 같은 Episode 다른 payload | index 기반 복구 / conflict, 미완료 성공 노출 없음 |
| 순서 뒤바뀐 mark/중복 step/취소 후 명령 | 대상/command identity 검사, 이중 적용/다른 Episode 전파 없음 |
| Missing Revision/보정/Task identity Resume | 오류; 최신·다른 함수로 대체 없음 |
| 공식 학습 로그 누락·results 오류 | 표시만 실패, Trainer 계산·Resume 유지 |

이번 명세에서 결정한 것은 호출/오류/수명 계약이다. 검증을 수행한 결과는 아니다. 2026-10-25 [B01](b01-baseline.md)에서 대표 stage의 dtype·배열·grasp 시점, contact threshold 분기, Reset 실패 경계와 반복 차이를 확보했다. 이 명세 자체가 새 구현 검증 결과는 아니다. 여러 env/seed·추가 SDK 상태 필드·raw force 전체·각 단계 Resume seed continuation은 추가 확인이 필요하며 숫자를 추측하지 않는다. Isaac DataGen strict IK 실패와 Isaac Evaluation 반복 차이를 신규 구현의 성공/결정성 검증 완료로 해석하지 않는다. 기존 동작과 충돌하면 그 항목만 질문/보고한다.

추가 계층 검토: HTTP/DB 없음, Engine ABC 없음, Task base class 없음, 모든 stage 공통 step 없음, 별도 launcher/command bus service 없음. 데이터 타입·오류 타입은 소유 파일에 둔다. Scene 계약과 IPC/Episode 효과의 검사만 강화하며 기존 Calibration·판정의 계산 의미를 바꾸지 않는다.

## 11. B03에서 확인한 장치·Calibration 경계

[B03](b03-calibration-device.md)의 원래 함수·수치·오류 경로를 §3/8의 계약에 연결한다. 아래 이름은 기존 구체 클래스/함수의 의미이며 새 Device ABC나 Wrapper를 추가하지 않는다. 재배치는 architecture.md의 robot/devices.py·calibration.py·control.py·capture.py 책임 안에서 한다. 신규 구현/실물 검증은 아직 없다.

| 원래 Interface | 입력/반환·효과 계약 |
|---|---|
| raw_from_native/native_from_raw | scalar + 모터 resolution/normalization/drive/calibration spec. homed count↔팔 degree/gripper percent. Homing_Offset 재적용 금지 |
| profile_for_model(profile, model_hash) | identity가 같거나 전체 URDF 증거에서 limits-only 변경인 경우 메모리 copy 반환. 저장/활성화 없음 |
| PrecisionMapper.calibrated_to_observation(native, raw=None) | JOINTS 이름의 finite packet→model rad 관측. raw/native 일치·branch 검사, 범위 밖 측정 보존 |
| PrecisionMapper.urdf_to_calibrated(q) | model rad→유일한 유효 정수 encoder를 표현하는 native 목표. 모델/모터 범위·branch 오류는 goal 전 거부 |
| Leader/Follower.connect/read | 명시 device identity·기존 calibration, 자동 보정 금지. read 반환 native+host interval과 별도 raw 근거를 구분. connect 성공은 activate/도달 성공이 아님 |
| Follower.activate/encode_goal/send | raw hold readback 후 공식 configure, readonly SDK encoding preflight, 실제 send의 세 효과를 구분. 반환 SDK native와 측정값은 다름 |
| stop / close / calibration release | last-goal hold / 일반 torque release 요청 / 승인된 선택 joint release를 구분. readonly Calibration.close는 torque 유지 |
| CameraReader.nearest/close | 복사 RGB+host read interval 또는 missing/error. nearest 자체는 freshness 보장 없음. join timeout을 종료 완료로 해석 금지 |

모든 배열은 JOINTS 순서이며 프로필 JSON의 key 순서와 다를 수 있다. policy observation float32, activation preflight float64·raw 정수, model/Telemetry의 기존 dtype를 임의 통일하지 않는다. raw K/distortion·virtual K·optical mount와 runtime pose, host monotonic/unix와 exposure 미가용을 명시한다. 새 schema는 불명 mapping을 DEFAULT_MAPPER로 자동 대체하지 않는다.

§2의 effect는 실제 장치 단계에 맞게 기록한다. 검사 실패로 send 이전이 확인된 경우 not_applied지만, configure의 finally torque enable·send 뒤 Sim 오류·SDK timeout/close 실패는 적용/해제 완료를 추측하지 않는다. `DEVICE_ERROR`와 error source·단계·known effect를 보유하고 자동 명령 재전송을 하지 않는다. Calibration/자원 수명 실패를 일반 Task false로 바꾸지 않는다.

§8 cancel acknowledgement와 worker 종료는 실제 torque/port 상태 증명이 아니다. 기존 Stop hold·Calibration close의 토크 유지 의미를 보존하면서 owner가 종료를 처리해야 한다. 기존 Leader/Precision cleanup 누락과 sim backend UI close의 stop 분기는 RO02/U03의 명시 검증 대상이다. UI 종료·heartbeat·SDK timeout의 실제 latency와 물리 상태는 이번 B03에서 측정하지 않았다.

ROBOT-02 실제 평가는 공식 Policy/processor를 사용하고 Task 성공을 자동 측정하지 않았다는 현재 의미를 유지한다. B01/B02의 Sim 성공 판정·Annotation tick/frame 차이·기록 계약과 혼합하지 않는다. 현재 개발 버전·DataGen 고정 DLS 정책·MiniVLA 제외도 변경하지 않는다.


### RO01~RO03 구현 경계 — 2026-10-26

[묶음 결과](robot-operations-bundle.md)의 calibration.py는 `load_profile(path,expected_sha256?,role?,identity?)`, `profile_for_model(profile,model_hash,*,source_model:bytes|None,execution_model:bytes|None)`, `mapper_from_scene(package,calibration_id,*,role,phase)`를 제공한다. 변경 모델은 S01/S02의 등록된 전체 모델 bytes/SHA가 필요하며 Git/active 포인터를 조회하지 않는다. mapper_from_metadata는 불명 schema를 거부한다. baked residual은 Encoder 변환으로 재적용하지 않는다.

`Follower/Leader(device,*,profile,calibration_path,identity,model_hash,source_model?,execution_model?)`는 구체 공식 SDK 객체/fake를 받는다. from_config의 SDK 생성과 connect는 별도다. raw read packet/activation hold는 원 정수다. read는 추가 하드웨어 calibration 조회 없이 단일 raw packet을 normalize한다. connect/activate에서 hardware identity를 검사하고 encode/send에서 파일·메모리 identity를 재검사한다. Leader id의 과거 파일명 의미와 Follower SDK id를 유지한다. `DeviceError`는 code/phase/issues/effect/cleanup, `CleanupResult`는 port_closed/torque_release_requested/torque_state/errors를 보유한다. `close_devices({name:device})`는 모든 소유 자원을 시도한 뒤 오류를 합친다. 추가 Manager는 없다.

`CalibrationDevice(device,*,role,identity,calibration_path)`의 sample/live와 `release(joint,approved=True)`는 읽기와 선택 joint 쓰기를 구분한다. close는 torque 상태 보존 요청이다. `CameraReader(camera,*,device,resolution)`는 thread/90 frame bounded copy/nearest/close를 소유한다. join timeout은 DEVICE_ERROR/unknown이며 종료 완료가 아니다.

capture.py의 align_measured/Stability/assess_pair/prepare_snapshot은 B03 수식·경계를 유지한다. snapshot의 기존 반환 필드에 mapping/model identity·joint_order/units·hardware_synchronized=false를 명시한다. 반환 Metadata는 소유 copy다. 실제 camera acquisition/물리 정지·촬영 동기·현재 engine pose·Snapshot publish/프로필 UI/장치 Recipe runner는 이번 통과 범위에 포함하지 않는다. AC03 실물은 BLOCKED다.

### Native 저장 경계 재검토 — 2026-10-26

2026-10-26 최종 C 전환: **공식 Native 파일 + 최소 실행 Metadata**를 구현했다. NATIVE-01/02/03의 로컬 파일·공식 CPU 소비자 관문을 통과했다. [전환 보고](native-dataset-transition.md)를 현재 계약으로 사용한다. 이전 [비교·차단 보고](dataset-storage-review.md)는 수정하지 않은 조사 이력이다. 엔진·실물·UI·공식 Trainer 학습 실행은 미검증이며 BU/E를 시작하지 않았다.

## 12. BU01~BU04에서 구체화한 Builder 경계

[Builder 묶음](builder-bundle.md)의 Project/Candidate는 기존 편집 자료를 사용한다. 기존 unmarked 프로젝트는 readonly이며 새 Project.create/clone_project(source, destination)만 새 작업 공간 소유권을 가진다. 자동 원본 수정·active 보정 대체를 하지 않는다.

`export_revision(project, *, destination, candidate=None, calibration=None, required_files=(), engine_sources=None, scene_id=None, revision=None, allow_unvalidated=False, isaac_robot_asset=None, asset_resolutions=None) → SceneIdentity`는 고정 후보/보정 선언을 새 경로에 publish한다. 기존 destination 거부·fresh signature·S01/S02·native closure 검증을 수행한다. `engine_sources` 교체는 binding 미검증이므로 지원하지 않는다. publish 후 directory fsync 실패는 EXPORT_STATE_UNKNOWN/effect=unknown과 위치를 남기고 결과를 삭제하지 않는다. 중단 뒤 lock을 자동 해제하거나 무조건 재실행하지 않는다.

`verify_package(path) → ScenePackage`는 파일·Calibration·native 참조를 검사한다. `exporters.mjcf.load_robot_collision(root, binding)`은 package-relative Finger/pad와 정확한 source identity를 읽는다. 실제 collider 설치/엔진 제어는 E01/E02다. required_files의 일반 path는 실행 파일이며 {source, usage: identity_evidence}는 실행되지 않는 원본 근거 bytes다. Calibration None은 빈 선언이고 robot.reference_snapshot_only/NOT_TESTED 상태로 남는다. 외부 근거 파일을 실행 가능 모델로 승격하지 않는다.

현재 생성 USD/MJCF는 Builder reference geometry snapshot이다. 정적 파일 parsing과 EGL/Blender 렌더가 완료되어도 Isaac articulation/PhysX/Fabric·동적 카메라·센서·실제 contact/solver 의미가 검증된 것은 아니다. C Native Dataset·Curation·Resume 계약은 변경하지 않는다.

## 13. E01·E02·E05의 실제 엔진 기반 경계

[엔진 묶음](simulation-engine-bundle.md)에서 `isaac.build_env_cfg(package, settings, *, runtime_directory, device, num_envs)`와 `mujoco.build_model(package, ModelConfig)`를 구현했다. settings는 명시 engine 입력 자료이며 기존 PreparedRun→입력 조립/worker 실행을 이미 연결한 API가 아니다. `ModelConfig`를 PreparedRun.effective_settings['mujoco']에 제공하는 명시 경계도 가능하나 R02가 현재 이를 생성한다고 주장하지 않는다.

Isaac runtime_directory는 immutable Scene 밖의 신규 경로다. package의 `robot.bindings.isaac.asset_path` 실행 USD를 공식 `UsdFileCfg/spawn_from_usd`로 직접 참조해 root/joint·기존 collider/camera/sensor를 연결하고 reference robot snapshot은 제외한다. baked 실행 URDF는 rad 한계·모델 identity를 확인하는 별도 근거이며 재import fallback은 없다. `initial_state/restore_episode`는 world root·joint·물체의 Episode 경계 상태이며 PhysX 임의 solver checkpoint가 아니다. `apply_joint_targets`는 패키지 URDF rad 한계와 실제 float32 payload로 preflight한다. 2026-10-28 승인 정책에 따라 유한 Position Target은 원 한계 안쪽의 dtype 표현 가능 경계로 Saturation한다. 한계 확대/epsilon 완화/IK fallback은 없다.

MuJoCo `snapshot/restore_episode`는 공식 mjSTATE_INTEGRATION·model SHA·SceneIdentity·backend version을 검사한다. canonical initial의 고정 base/target은 pose/zerovelocity를 대조하고, 선택된 free object 상태를 복원한다. `reset_object_poses`의 관통은 rollback하며 RNG·placement 예산을 소비하지 않는다. 실제 Step 뒤의 샘플은 post_step, 저장 관측과 비교할 때 다음 pre_step으로 phase를 명시한다.

E05의 source_pool은 공식 EpisodeData/명시 EpisodeID 순서를 소비한다. randomize_boundaries와 plan_subtask는 수치만 계산하며 engine/Writer/IK를 호출하지 않는다. 반환 source index/half-open boundary/waypoint는 성공·완료를 의미하지 않는다. CPU tool0 이외 지원·GPU RNG 동등성을 주장하지 않는다.

기존 Shape/dtype·단위·Quaternion/Calibration·pre/post 의미를 유지한다. E01 전체 numeric trace는 OPEN, E03/E04/E06 runner 및 Native C commit/Resume 연결은 후속이다. 구조화 worker 오류/effect 직렬화까지 현재 concrete 함수만으로 구현됐다고 해석하지 않는다.

### E01 v8 Collision 보존 결정 (2026-10-26)

`isaac_robot_asset`은 명시적으로 제공한 기존 실행 USD이며 Builder native closure 수집 후 `robot.bindings.isaac.asset_path`에 패키지 상대 경로로 기록한다. `asset_resolutions`는 unresolved SDK material 이름→명시 로컬 원본 파일 매핑이다. 알려진 pinned MDL runtime 모듈만 외부 SDK 의미로 허용하고 상대 module을 패키징하며 알 수 없는 module은 거부한다. 기존 필수 asset/manifest·이전 Revision 불변·보정 baked/runtime 계약을 유지한다. 이는 collider 선택·자동 검색·fallback API가 아니다. Isaac의288 생성·기존 collider 비활성화 경로는 제거하고 기존 USD의 hull/pad/그룹/instance를 그대로 사용한다. MuJoCo Finger JSON과 해당 엔진의288 계산은 유지한다. [실제 재검증](e01-v8-collision-recovery.md): Source initial의388step q/qd·Grasp221/pre222 latch 보존, object settling 최대1.197188790mm/tick310 Y는 OPEN이다.


## 2026-10-27 — MuJoCo Source/Annotation 실행 연결

[구현 경계](mujoco-workflows-ik.md): Source의 inputs.engine_config는 기존 E02 ModelConfig 필드 JSON, inputs.resume_dataset은 불변 Native C 입력이다. execution.episode_time_s/reset_time_s를 명시한다. device_profile은 calibration_id/calibration_path/sdk이며 RO Leader mapping identity를 Scene과 재대조한다. 실제 장치 연결은 이번에 실행하지 않았다. Source는 save/discard 명령을 추가 지원하며 explicit episode_id가 필요하다. 빈 save는 완료 Episode를 만들지 않고 cooldown에 들어간다. cooldown에는 cancel 외 명령을 rejected(reason)로 응답한다. 실제 step 완료 이후 ACK하며 stage가 거부 사유를 가진 rejected ACK를 반환할 수 있다. 기존 중복 command ID/worker claim 규칙은 유지한다.

Annotation은 기록된 original Source의 ModelConfig/units/frame/joint order/pre-step clock을 검증하고 원 Source initial을 복원한다. 수동 boundary는 실제 물리 통과 후 별도로 채택한다. 별도 Source signal/metric 및 Annotation metric 실행은 현재 지원하지 않아 명시 오류이며 무시하지 않는다. 단일 env 기본 v8 경로를 검증했다.

E06-a bind_kinematics/solve_dls는 URDF SHA·robot_base/tool0·m/rad·관절 순서를 고정하고 측정 seed/previous_applied를 구분한다. 반환 IKResult는 후보 명령/진단/고정 identity, IKFailure는 invalid candidate와 not_applied를 나타낸다. 이 함수는 engine target/previous 상태를 갱신하지 않으며 엔진 DataGen 연결은 미착수다.


## L03 — 공식 Dataset 변환·Merge의 구현 경계

2026-10-27 [구현·근거](l03-lerobot-dataset.md). `data.lerobot.control_contract(source)`는 검증된 JOINTS/model rad/pre-step measured state와 recorded absolute joint_targets의 의미 및 Scene/Calibration/모델·카메라/control clock identity를 반환한다. 외부 공식 Dataset에 이 Metadata를 강제하지 않으며 불명 의미의 자동 Merge는 거부한다.

기존 `materialize`에 `merge(sources,output,*,split=None,independent=False,task=None)`를 연결하며 같은 공식 writer를 사용한다. 현재 Native끼리 또는 official끼리만 지원하고 family 혼합은 먼저 별도 명시 materialize한다. float32/64 저장의 정확한 승격은 허용하나 joint order/unit/action/observation/camera/control 계약 차이는 거부한다. 새 caller용 Signature 인자 타입은 소유 모듈에 있다.

관절 feature names·source.dataset_id/source.episode_uid·원 frame/time·split·domain/parent를 최소 provenance로 보존한다. 같은 원 Episode의 train/val 배정을 차단한다. 하나의 canonical resumed Dataset/engine에서 선택하며 creator가 입증되지 않은 Archive나 복수 Resume branch의 Merge는 거부한다. content dedup/독립 blob index를 만들지 않는다. 언어 task는 명시 문장 또는 기록된 task를 사용하고 Task 코드 hash를 대신 쓰지 않는다.

known Workbench projection은 관측 obs/policy/joint_pos와 action joint_targets만 학습 IO다. 상태·IK·applied 진단으로 바꿔 넣지 않는다. 공식 timestamp float32와 source.timestamp float64를 구분한다. pinned official stats/normalization/MP4 offsets를 사용하며 frame/time·camera 불일치와 비유한값은 저장 성공으로 숨기지 않는다. 실제 Policy 실행/Training과 SMOL-PAD-01 및 제어 경계 관문은 L01/L02/P에 남긴다.


## 2026-10-27 L01/L02 — 공식 실행·닫힌 checkpoint·독립 추론

`learning.train.train(plan, *, events, commands)`는 R03이 전달한 고정 PreparedRun에서 공식 LeRobot CLI child를 실행한다. Train Recipe의 `inputs.dataset/training_config`, `execution.mode=scratch|resume`, 새 `output.directory`를 사용한다. Resume에는 `inputs.checkpoint`의 닫힌 checkpoint root가 필수다. 공식 JSON의 dataset.root/output_dir/resume는 Recipe와 일치해야 하며 Hub/WandB/pretrained 다운로드·자동 환경평가는 이 runner에서 거부한다. ACT 지원 범위이며 Smol Training은 SMOL-PAD-01로 거부한다.

공식 child에 실행 소유 config bytes를 전달한다. Resume는 official parser의 checkpoint 부모 해석을 위해 새 표준 checkpoint 배치에 config JSON을 복사하고 불변 Tensor/state를 hardlink한다. 기존 원본 config/checkpoint를 수정하지 않으며 누적 steps/new output/resume 이외 변경은 거부한다. 저장 config·초기 Dataset identity·Tensor finite·필수 official state를 확인한 checkpoint만 `workbench-checkpoint.json`으로 연결한다. 이는 공식 모델 파일을 감싸는 새 bulk format이 아니다.

`learning.policy.load_policy(path, *, expected=None, device='cpu')`는 공식 ACT·pre/postprocessor·기록을 반환한다. owned checkpoint는 파일 SHA/완료를 검증하고, 외부 official artifact는 자체 model/config/processor로 로딩하며 전용 provenance/optimizer를 강제하지 않는다. 의미 미확인 외부 artifact를 자동으로 SO101 배포에 승인하지 않는다.

`infer(policy, pre, post, batch, *, contract, limits=None)`는 공식 pre→select_action→post 결과를 model rad 절대6축으로 검사한다. limits가 있으면 원 한계 안쪽의 dtype 표현 가능 경계로 Position Saturation한다. 호출자는 올바른 명시 control contract/model limits를 제공해야 한다. `validate_action`은 JOINTS/단위/shape/finite를 검사하며, limits가 주어진 최종 목표만 Saturation한다. limits 없는 measured observation/Offline 값은 변경하지 않는다. limits 없는 Offline 결과는 제어 승인 아님. 실제 엔진·Follower 전송과 P01/P03은 별개다.

`learning.validate.evaluate(plan, *, events, commands)`는 별도 offline_validation worker로 `inputs.dataset/policy`, `execution.batch_size=1/max_batches`와 새 output을 사용한다. checkpoint에 기록한 train Dataset identity 및 source Episode UID 격리/IO 일치를 확인한 뒤 실제 val DataLoader로 추론하며 Episode마다 queue를 Reset한다. MAE/RMSE(rad), 시간/RSS, physical_success=unmeasured를 기록한다. owned provenance가 없는 외부 Policy의 train/val membership을 추측하지 않는다.

상세 [실행·미검증 경계](learning-bundle.md). cancel ACK completed는 현재 child 정리보다 앞설 수 있고 terminal run 상태가 실제 종료 기준이다.


## 2026-10-27 P01 — Simulation Evaluation 연결

기존 `simulation_evaluation` stage가 `engines/{mujoco,isaac}/evaluation.run(plan, *, events, commands)`를 호출한다. 필수 inputs.scene/policy 및 기존 objects/functions.success를 사용한다. `engine_config`, `resume_dataset`, 외부 official Policy용 `policy_contract`를 선택 입력으로 추가한다. 실제 runner에는 명시 engine_config가 필요하다. execution.episodes/seed와 선택 timeout_s/num_envs/headless를 사용하며 현재 num_envs=1·Fixed만 지원한다. timeout_s는 30Hz의 최대 control step으로 환산하고 기본10s=300step이다. wall-clock timeout이 아니다.

ACT/processor는 L02 그대로 사용한다. owned Policy는 기록된 control contract를 쓰고 외부 official ACT는 명시 policy_contract로 live IO 의미를 입증해야 한다. provenance 부재 자체를 이유로 거부하지 않는다. Scene/Calibration/URDF·JOINTS·pre-step measured state·model rad 절대 Action·camera640×480/30Hz·feature shape를 비교한다.

`observation_batch(joints,cameras,*,joint_order)`는 실제 pre-step measured q와 RGB uint8을 공식 Dataset과 같은 float32 batch로 만든다. `preflight_action(action,*,limits,applied_dtype,diagnostics=None)`는 유한 Position Target을 원본 rad limit 안쪽의 native dtype 경계로 Saturation한 뒤 재검사한다. 자동 Hold/fallback·한계 확대는 없다. `ActionRejected.diagnostics`는 원 Action/dtype/shape·적용 dtype·관절/한계/초과량·command_applied=false를 보유한다. malformed/nonfinite inference도 명시 safety failure로 기록한다. 실제 engine preflight는 그 뒤 호출한다.

pre-step observation/RGB·joint_targets(후처리 원값), commands/applied_joint_rad(실제 payload), states/*(post-step measured/Task/contact), policy/action_queue_remaining, pre/post physics timestamp를 구분한다. Evaluation 성공은 Placement이며 grasp/transport/full_task_success는 별도 지표다. category는 placement_success/max_steps/action_safety_rejection/engine_error/camera_error/policy_error/execution_error/cancelled다. 미관측 실패 원인을 추정하지 않는다.

Native execution에는 전체 Policy record digest·파일/processor SHA·checkpoint step/학습 Dataset identity와 평가 계약을 기록한다. raw Recipe SHA는 각 Episode에 남긴다. Resume는 출력/누적 목표가 달라도 동일한 실제 함수/파라미터/명령/시간 계약인지 확인한다. 완료 failure Episode도 새 출력으로 상속하므로 attempt 상태 failure와 success=false는 미완료라는 뜻이 아니다. 취소/불완전/적용 불명 중간 step은 정상 Episode로 공개하지 않는다. 성공률 분모는 취소/거부/오류를 포함한 기록된 모든 attempt다.

오류는 원 code/issues/effect·traceback을 보존하고 실제 적용 뒤 오류를 not_applied로 표시하지 않는다. Reset의 관측된 실패를 history에 기록하고 불명 crash claim은 자동 Resume하지 않는다. 모든 영상 abort와 Native owner close를 시도한다. 실제 Task 성공0과 실행 경로 검증 완료를 구분한 [결과](p01-simulation-rollout.md)를 기준으로 한다.


## 2026-10-27 C01/C02 — UI가 직접 소비할 Curation 함수

새 UI 계층 없이 data/curation.py의 일반 함수를 사용한다. `inspect_dataset(source, *, split=None)`는 현재 선택의 original outcome/seed/lineage/역사적 partition과 별도 원 Native run attempt scope를 반환한다. 취소/pending은 완료 Episode로 추가하지 않는다. `filter_episodes`는 기록된 성공/category/split으로 ID를 고른다. `revision_history`는 현재→parent→원본/공식 materialized identity를 반환한다.

`distribution(source, *, fields=None, split=None, bins=20, chunk_frames=2048)`는 선택 half-open 구간의 성분별 population mean/std·min/max·histogram과 scope/dtype/shape/unit/phase/frame/order를 반환한다. 기본 Native 필드는 pre measured obs/policy/joint_pos와 recorded joint_targets다. applied/post-state/Task 필드는 명시 요청하며 원 Action을 대체하지 않는다. 누산만 float64이고 원 저장 정밀도는 그대로다. `compare_distributions(sources, ...)`는 같은 의미/단위/shape의 공통 bin 비교이며 Merge 승인이나 부족 영역 추천이 아니다.

`review_frame(source, selection_id, frame, *, cameras=None, fields=None)`의 frame은 선택-relative이며 원 ordinal/기록값·RGB numpy copy/정확한 MP4 PTS를 같이 반환한다. 누락/non-CFR 구간은 이전 frame으로 숨기지 않는다. `rgb_statistics(source, camera, *, split=None, stride=1)`는 선택 구간 decode RGB 수와 통계 표본 수를 나누어 반환한다. stride가 decoder workload를 같은 비율로 줄이는 보장은 없다.

`position_distribution(source, object_id, *, scene, frame, split=None)`는 정확한 recorded Scene Revision에서 선택 구간 첫 robot_base matrix pose를 reference Frame으로 옮긴 XYZ/XY(m) 목록이다. 없는 Frame·누락 pose·단위 미확인은 오류이며 live/current pose나 새로운 reset initial을 합성하지 않는다.

`split_dataset(source, *, train_fraction=.8, seed=0, assignments=None)`는 기존 v8 Episode choice/반올림/순서를 유지하고 전역 RNG를 바꾸지 않는다. 생성 결과의 splits와 split_provenance를 save_curation에 함께 넘기면 seed/규칙/당시 source identity·배정이 저장된다. V2의 현재 membership과 원 배정 provenance는 구분한다. seed가 기록되지 않은 명시 배정은 None이다. 같은 원 Episode UID/alias의 train/val/test 중복을 막으며 알려지지 않은 모든 조상의 독립성을 보장하지 않는다.

같은 identity를 검증한 명시 relocation은 검토 호출과 Native Export에서 유지한다. V2 저장 시 작은 상대 resolution map을 보존하므로 기존 부모를 수정하지 않고 프로세스 종료 뒤 다시 열 수 있다. **변경하지 않은 L03 materialize/merge에는 임시 relocation view를 먼저 영구 V2로 저장한 뒤 전달한다.** 기존 Export의 full Native archive와 trimmed LeRobot materialization 구분은 그대로다. [검증/지원 경계](curation-bundle.md)를 기준으로 UI 조작·thread·작업 취소는 후속 U에서 연결한다.

### 2026-10-27 — Seed 없는 Workspace Random 및 신규 Scene 검사

위5.4의 caller-owned rng 계약은 기존 v8/일반 contact sampler에 해당한다. 새 DataGen `placement.random_workspace`는 명시 `WorkspaceParams(object,frame,support,workspace,rules='workspace_entropy_v1',separation_m=.024,yaw_rad=0)`를 사용하고 PlacementRequest.rng/xy_m/orientation을 거부한다. Pose 생성은 default_rng()이며 Recipe execution.seed/Native claim.seed는 기존 Mimic/Attempt identity다. 새 DataGen은 기존 seeded Random bindings를 거부한다.

`workspace_reset_poses(plan,occupied_world)`는 기존 Task module의 단순 batch 계산이다. 원래 위치의 moving 대상은 제외하고 고정 collision-enabled obstacle/앞선 새 Pose로 검사한다. 전체 Pose/작은 diagnostics를 반환하며 engine state를 쓰지 않는다. `validate_workspace_payload`는 native dtype/Quaternion 직렬화 후 strict Footprint 경계를 다시 검사한다. 동적 robot link contact는 공식 engine 검사 영역이다.

실제 reset_placements는 신규 규칙에서 Object별 local/requested_world/payload/applied_world/observed_world Pose와 validation을 반환한다. 실패 전 미적용·검증된 rollback·부분 SDK 쓰기의 unknown을 구분하며 실패 attempt에도 근거를 보존한다. Native 저장/Resume 형식·Task 판정·IK 정책은 재사용한다. Isaac Random 다음 attempt는 새 worker이며 fresh_worker_required로 표시한다.

`real2sim_builder.project.validate_horizontal_layout(scene, *, table, workspace, blocks, robot_frame='robot_base')`는 opt-in 읽기 전용 초기 box-layout 검사다. 높이/Base 위치/Camera/URDF·Calibration 값을 수정하지 않고 calibration_verified=false다. [적용 범위·실제 결과](random-placement-horizontal.md).

## 2026-10-28 Position Target Saturation / Applied Action

`robot.control.checked_target(target, *, limits, applied_dtype, joint_order=JOINTS, units='model_rad', diagnostics=None)`가 공통 최종 경계다. `float32(U)>U`이면 `nextafter(float32(U),-inf)`를 상한으로, `float32(L)<L`이면 `nextafter(float32(L),+inf)`를 하한으로 삼는다. 실제 representable 구간이 없거나 shape/order/unit/finite/Calibration/model binding이 무효면 거부한다. 범위 안 목표는 정상 dtype 변환 이외에 바꾸지 않는다.

새 Native의 `joint_targets`는 학습용 **실제 적용 절대 model-rad 목표**다. `commands/requested_joint_rad`에 원 요청/solver command, `commands/applied_joint_rad`에 payload, `commands/saturation_mask`(bool6), `commands/saturation_delta_rad`(applied-requested float64)를 정렬해 저장한다. delta에는 정상 dtype rounding도 남지만 Saturation mask와 집계는 안쪽 경계 밖으로 제한한 관절만 센다. pre-step measured observation/post-step telemetry는 기존 의미다.

실행 recording은 `position_target_policy=saturation_inward_v1`, `joint_targets_role=applied`를 선언한다. `control_contract.command_processing={position_target_policy: saturation_inward_v1, training_target: applied}`는 새 공식 LeRobot Metadata에서도 보존하며 과거 requested-target 자료와 자동 Merge하지 않는다. 과거 Native/LeRobot을 수정하거나 새 계약으로 재명명하지 않는다. Resume는 기존 identity 검사로 정책이 다른 실행을 거부한다.

DataGen은 기존 DLS/Best Effort candidate의 별도 유효성/limit/0.5rad jump 검사를 통과한 뒤 최종 engine payload를 Saturation하고 직전 실제 적용 arm target 대비0.5rad를 다시 검사한다. candidate 미수렴 진단을 수렴으로 바꾸지 않는다. 실물 Follower의 command binding/encoder/range 승인과 SDK 전송은 별도이며 이번에 활성화하지 않는다. 상세 실행/보존은 [결과](position-saturation-recovery.md)에 기록한다.

## 2026-10-28 확장 — 추가 수집·Vector·Smol·Preview

[실제 통합 결과](resume-multienv-smolvla-preview.md)가 이번 사용자 요청 R01/M01/M02/L04/U05/X02의 기준이다. 과거 같은 번호의 작업과 구분한다.

- Source/DataGen `execution.num_episodes`는 추가 완료 수(Source recording_only)/추가 성공 수(DataGen), `execution.resume=true`는 기존 `output.directory` Native에 immutable segment를 추가한다. DataGen `max_attempts`도 이번 추가 예산이며 runtime에서 기존 소비 수를 더한다. legacy cumulative 필드·새 출력 `resume_dataset`과 동시 사용하지 않는다. `resume=false`는 기존 출력에 쓰지 않는다.
- UI/새 Recipe의 환경 수는 `env_num`(기본1)이다. 내부에서 `num_envs`로 해석하며 두 이름 동시 선언을 거부한다. Episode/attempt ID와 `env_index`는 별개다. Resume에서 Env 수만 바꾸는 것은 데이터/모델/recording 계약이 같을 때 가능하다.
- Source `inputs.source_dataset`는 엔진/모델/recording이 일치하는 명시적 수치 stream이다. device_profile과 배타적이며 실물 시연 수집을 뜻하지 않는다. Source placement 생략 시 원 Source initial을 사용한다. Source 구간으로 새 수집은 가능하지만 Annotation은 original initial의 complete Source만 재생한다. complete Annotation Curation `[0,num_frames)`는 DataGen pool로 허용한다.
- Isaac vector는 Env별 pre/target/post generator와 한 공식 vector Step을 쓴다. canonical initial은 `initial_frame=scene_world`, 실제 offset은 `engine_env_origin`으로 보존한다. vector pause/resume는 run-global, Env별 single-step은 거부한다. Manual mark/skip는 Env/Episode/frame을 명시한다.
- 기존 경로 append는 Dataset ID·과거 HDF5/영상/segment header를 보존한다. producer execution 이력은 작은 run Metadata에 남는다. state/model/MDP/control/Calibration/IK·Task/recording 불일치는 거부하며, inactive 미완료 attempt는 명시 Resume에서 unknown으로 소비한다. frozen Curation을 갱신 Catalog에 자동 rebase하지 않는다.
- SmolVLA는 공식0.4.1 Trainer/Policy/processor와 project-owned fixed-source loss patch를 사용한다. patch/upstream/source SHA는 Checkpoint·Resume·Prepared identity에 고정한다. Evaluation `execution.task_instruction`은 명시 문장이다. Action은 공식 postprocessor 뒤 절대 model rad6→기존 Saturation이다.
- Preview는 실제 AsyncVideoWriter 입력 중 선택 Env의640×480 Side/Wrist, 최대 갱신 약30Hz(34ms Qt timer)다. camera별 two-slot mmap·generation/header 확인, 최신 frame만 제공하며 Native 영상 품질·PTS는 바꾸지 않는다. 실제 FPS·지연은 측정값으로 별도 보고한다.
