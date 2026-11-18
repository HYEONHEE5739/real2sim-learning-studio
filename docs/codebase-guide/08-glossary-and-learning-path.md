# 08. 용어와 학습 경로: 한 함수를 이해한 뒤 다음 Consumer로 이동하기

[처음](README.md) · [구조](01-system-architecture.md) · [재구성](02-scene-reconstruction.md) · [좌표·자산](03-camera-assets-simulation.md) · [학습](04-robot-learning.md) · [결함](05-bug-fixes-explained.md) · [코드 지도](06-source-code-atlas.md) · [실습](07-execution-and-debugging.md) · [용어](08-glossary-and-learning-path.md)

메카트로닉스에서 알고 있는 FK/IK·제어·카메라 수학을 출발점으로 삼는다. 새로 익힐 부분은 “그 계산이 어떤 자료와 권한을 받아 어느 프로세스에서 실행되고, 실패하면 누가 무엇을 보존하는가”다. 이 장의 과제는 코드 읽기 과제이며 실제 실행 지시가 아니다.

## 목차

- [1. 먼저 알아둘 Python 구조](#learning-python)
- [2. 프로세스와 상태 용어](#learning-process)
- [3. 데이터와 Geometry 용어 사전](#learning-glossary)
- [4. 네 가지 Resume](#learning-resume)
- [5. 권장 학습 순서](#learning-order)
- [6. 처음 열 핵심 코드 10개](#learning-ten-files)
- [7. 읽고 이해했는지 확인하는 질문](#learning-questions)

<a id="learning-python"></a>
## 1. 먼저 알아둘 Python 구조

### 1.1 파일이 모듈이고 모듈들이 패키지를 이룬다

`robot_learning_workbench/src/robot_learning_workbench/run.py`는 `robot_learning_workbench.run` 모듈이다. `from .recipe import ...`의 점은 같은 package 안에서 시작하라는 뜻이다. Repository 최상위 폴더 이름만 PYTHONPATH에 넣는 것과 각 `src`를 넣는 것은 다르다. [실습의 경로 설정](07-execution-and-debugging.md#debug-environment)을 먼저 읽는다.

`__init__.py`는 package namespace다. 이 프로젝트의 import만으로 실제 장치·엔진을 시작하지 않는다는 목표와, 모든 module import가 가볍다는 주장은 다르다. 예를 들어 `generation.mimic`은 NumPy/Torch 수학을 import한다. GUI는 필요한 Backend를 선택해서 불러오고 실제 엔진 AppLauncher나 serial connect를 명시 실행 시점에 둔다. Atlas는 import 관계와 실제 dispatch를 구별해 표시한다.

### 1.2 dataclass는 작은 계약을 눈에 보이게 만든다

`StartRequest`, `WorkerRequest`, `RunStatus`, `PreparedRun`은 데이터를 담는 dataclass다. 필드가 정해져 있어 함수 사이에서 필요한 값이 드러난다. `@dataclass(frozen=True)`는 그 객체 속성 재할당을 막는다. 참조한 외부 파일이 변하지 않는다는 뜻은 아니다. 따라서 SHA·file manifest를 별도로 확인한다.

[run.StartRequest · L61](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L61) → [run.WorkerRequest · L73](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L73) → [run.RunStatus · L89](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L89)와 [recipe.PreparedRun · L234](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L234)을 비교한다. StartRequest의 expected SHA는 검토한 저장본을, WorkerRequest는 어느 Interpreter와 token으로 실행하는지를, RunStatus는 관측한 상태를 나타낸다. 같은 dict로 모든 의미를 대신하지 않은 이유다.

### 1.3 type hint와 실제 검증은 다르다

`exit_code: int | None`라는 표시는 IDE/독자에게 계약을 알린다. Python이 모든 입력을 자동으로 검사하지 않으므로 `read_status`에는 실제 type 검사가 있다. bool은 Python에서 int의 subclass이기 때문에 `isinstance(True,int)`는 true다. 이 코드의 많은 안전 경계에서 `type(value) is int`를 사용하는 이유다. 숫자처럼 보이는 JSON이 실제 Step·해상도·정상 종료 코드인지 별도로 검사한다.

### 1.4 property는 디스크를 읽을 수도 있다

`project.scene`이 단순 메모리 속성처럼 보여도 [project.Project.scene · L122](../../real2sim_builder/src/real2sim_builder/project.py#L122)은 `working/current_scene.yaml`을 읽는다. `candidate.scene`도 후보 YAML을 읽는다. 두 줄에서 이 property를 다시 읽으면 같은 객체 reference를 돌려받는다고 가정하면 안 된다. 저장 전에 원본 signature가 그대로인지 검사하는 것은 다른 편집·프로세스와의 충돌을 막는 데 필요하다.

### 1.5 context manager는 “마지막 정리”를 코드 구조로 표현한다

`with NativeRun(...)`이 끝나면 Writer를 닫고, `with exclusive(project)`가 끝나면 lock을 해제한다. 중간 return/예외가 있어도 `finally`가 실행되는 이유를 [candidate.exclusive · L17](../../real2sim_builder/src/real2sim_builder/candidate.py#L17)에서 읽자. 다만 SIGKILL/전원 차단은 Python finally의 정상 실행을 보장하지 않는다. 그래서 staging/claim/부분 로그를 보고 UNKNOWN으로 남기는 경계가 필요하다.

### 1.6 callback과 closure는 엔진과 IPC를 분리한다

`execute`는 Runner에게 `events(event)`와 `commands()` 함수를 전달한다. Renderer/Task loop는 QProcess나 파일 protocol을 직접 다 알 필요가 없다. 이 함수들은 바깥 state와 lock을 기억하는 closure다. [run.execute · L475](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L475)의 내부 함수와 [run._run_stage · L443](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L443)의 전달 코드를 함께 본다. callback은 원격 Agent를 뜻하지 않는다. 매 Step의 성공 predicate도 Python 함수 호출이다.

### 1.7 generator는 여러 환경을 한 Step씩 진행하게 한다

`replay_steps/generation_steps/rollout_steps` 같은 generator는 전체 Episode를 한 번에 끝내지 않고 진행 상태를 yield한다. Vector/parallel 조율자는 각 환경을 번갈아 진행하고 commands/ACK/recording과 연결한다. Engine num_envs가4라는 말과 네 프로세스에서 같은 seed로 네 번 실행했다는 말은 다르다. 자세한 source→plan 전달은 [학습 장](04-robot-learning.md)에서 읽는다.

### 1.8 copy는 수학적 불변성을 대신하지 않는다

`deepcopy(scene)`는 기존 메모리 dict를 직접 수정하지 않게 해준다. 그러나 만든 사본이 실측을 훼손했는지는 [editing.preserve · L10](../../real2sim_builder/src/real2sim_builder/editing.py#L10)가 확인하고, 형식/좌표/파일 identity는 validate/manifest가 확인한다. Camera를 고쳤을 때 derived Cloud를 갱신하는 것도 별도다. 이 셋을 “사본을 만들었으니 안전”으로 묶지 않는다.

<a id="learning-process"></a>
## 2. 프로세스와 상태 용어

| 용어 | 이 저장소에서의 뜻 | 코드로 확인할 질문 |
|---|---|---|
| Process | 독립 Python/Blender/Codex/Trainer 실행 단위 | 누가 Popen/QProcess하고 stdout/종료를 회수하는가? |
| Thread | 같은 프로세스 안의 병행 실행 | shared state/lock이 있는가? daemon thread의 부모가 끝나면 어떻게 되는가? |
| Worker | 저장 요청을 실행하는 역할 | R03 Worker인지 Builder Provider Child인지 구분했는가? |
| Backend | Qt 밖에서 파일/준비/실행 시작을 처리하는 Python | 단기 JSON operation인지 긴 작업인지 확인했는가? |
| Event loop | Qt의 입력·신호·timer를 처리하는 반복 | 화면 thread에서 모델/엔진 계산을 직접 기다리고 있지는 않은가? |
| polling | 상태·event·Preview를 일정 주기로 읽는 것 | 최신 값을 보되 같은 terminal/경고를 두 번 표시하지 않는가? |
| Command | 사람이 보낸 intent | command_id·run_id·Episode/env/tick의 근거가 맞는가? |
| ACK | Worker가 명령을 어떻게 처리했는지 남긴 영수증 | queued/accepted/completed/rejected가 다른 시점임을 확인했는가? |
| timeout | 특정 실행 경계의 제한 시간 | R03 전체/Trainer Cancel/Codex/GPU Child 중 어디 예산인가? |
| cancelled | 협력적 중단 결과 | Writer closure/부분 결과/OS exit가 완료됐는지 별도로 봤는가? |
| completed | 작업 Runner가 완료 결과를 게시함 | 정책 Task가 성공했는가? Dataset은 읽히는가? process exit는 관측됐는가? |
| unknown | 관측 근거가 없어 상태를 확정할 수 없음 | PID 재사용/관측자 종료/Legacy/부분 claim을 0이나 성공으로 바꾸지 않았는가? |

[run.read_status · L130](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L130), [ui.session_client.SessionClient.poll · L53](../../robot_learning_workbench/src/robot_learning_workbench/ui/session_client.py#L53), [ui.operations.run_outcome · L16](../../robot_learning_workbench/src/robot_learning_workbench/ui/operations.py#L16)을 같은 화면에 열어 읽으면 Producer/Backend/Consumer가 보인다. exit7은 작업 상태를 대체하는 새 status 문자열이 아니라 별도 `process_error`다.

<a id="learning-glossary"></a>
## 3. 데이터와 Geometry 용어 사전

### 3.1 파일과 게시 계약

| 용어 | 프로젝트 안의 구체적 의미 | 첫 코드 |
|---|---|---|
| Schema | 필수 key/type/단위/허용 상태의 문법·의미 계약 | [scene.validate · L90](../../real2sim_builder/src/real2sim_builder/scene.py#L90), [recipe._validate · L111](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L111), [package.validate_scene · L459](../../scene_contract/src/scene_contract/package.py#L459) |
| JSON / YAML | 저장 인코딩. format이 같다고 schema가 같지 않음 | [files.read · L6](../../real2sim_builder/src/real2sim_builder/files.py#L6), [run._decode · L44](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L44) |
| Manifest | 어떤 파일·SHA·의미가 이 Artifact/Package에 속하는지 기록 | [stage_artifacts.manifest · L42](../../real2sim_builder/src/real2sim_builder/stage_artifacts.py#L42), [package.verify_files · L77](../../scene_contract/src/scene_contract/package.py#L77) |
| Artifact | 실제 생성한 파일과 그 identity·provenance | [stage_artifacts.StageArtifact · L71](../../real2sim_builder/src/real2sim_builder/stage_artifacts.py#L71) |
| content SHA | 정확한 byte/선언 값에 대한 digest | [files.sha · L29](../../real2sim_builder/src/real2sim_builder/files.py#L29), [data.native.digest · L41](../../robot_learning_workbench/src/robot_learning_workbench/data/native.py#L41) |
| semantic SHA | 파일 외에 Consumer가 해석하는 metadata 의미도 묶는 digest | [object_assets._semantic_digest · L267](../../real2sim_builder/src/real2sim_builder/object_assets.py#L267) |
| Integrity | 의도한 자료와 현재 자료가 같은가 | [object_assets.verify_object_asset · L275](../../real2sim_builder/src/real2sim_builder/object_assets.py#L275) |
| Provenance | measured/calibrated/estimated/derived/unknown과 근거 | [scene.value · L13](../../real2sim_builder/src/real2sim_builder/scene.py#L13) |
| Identity | 이름/경로와 분리된 Scene/Dataset/Asset의 동일성 | [package.SceneIdentity · L101](../../scene_contract/src/scene_contract/package.py#L101), [data.native.DatasetIdentity · L110](../../robot_learning_workbench/src/robot_learning_workbench/data/native.py#L110) |
| Atomicity | 불완전한 새 상태를 Consumer가 완료 자료로 보지 않게 하는 게시 경계 | [run._atomic · L31](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L31), [data.native.NativeRun · L211](../../robot_learning_workbench/src/robot_learning_workbench/data/native.py#L211) |
| Transaction | 준비·검증·게시·실패 정리의 묶음 | [export.export_revision · L305](../../real2sim_builder/src/real2sim_builder/export.py#L305) |
| Staging | 아직 완료 Consumer에 노출하면 안 되는 소유 중간 출력 | [data.lerobot.create_staging · L135](../../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py#L135) |
| Publication | 검증된 자료를 공식 Reader가 소비할 수 있게 전환 | [data.lerobot.publish · L149](../../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py#L149), [data.publication.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/data/publication.py#L1) |
| Closure | entry가 참조하는 모든 네이티브/texture 파일 집합 | [export.verify_native_closure · L180](../../real2sim_builder/src/real2sim_builder/export.py#L180) |
| Claim | 한 request/worker/attempt를 누가 시작했는지 기록 | [run.start · L171](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L171), [data.native.NativeRun.claim_attempt · L257](../../robot_learning_workbench/src/robot_learning_workbench/data/native.py#L257) |
| Idempotency | 같은 ID·같은 의도로 중복 요청해도 같은 결과/handle | [run.send_command · L348](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L348), [run.start · L171](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L171) |
| Cache | 입력/설정/구현/모델 identity가 같을 때 검증 후 재사용할 결과 | [stage_artifacts.cache_key · L29](../../real2sim_builder/src/real2sim_builder/stage_artifacts.py#L29) |
| Race condition | 읽기와 삭제 사이 새 Stop이 들어오는 것 같은 시간 순서 결함 | [project.Project._consume_control · L189](../../real2sim_builder/src/real2sim_builder/project.py#L189) |

Hash는 암호화나 의미의 진실성 인증이 아니다. 사용자가 잘못 대응시킨 점을 해시로 묶어도 잘못된 점이다. immutable Package와 잘못된 Scene도 동시에 존재할 수 있다.

### 3.2 Robot Geometry

| 용어 | 구체적 의미 | 오해 방지 |
|---|---|---|
| Frame | 좌표를 표현하는 기준축 | World/Base/Link/Optical/Object를 구분 |
| Extrinsic | 여기서는 기록에 따라 W2C 또는 Camera-to-parent | 변수 이름과 반환 계약을 보고 inverse 방향 확인 |
| Intrinsic K | focal pixel scale와 principal point | Resize/crop 후 원 K를 그대로 쓰지 않음 |
| Optical Z | Camera +Z 축의 Depth | 점까지의 range와 다름 |
| Pixel affine | 원 sensor pixel과 처리 image pixel 사이 A | 단순 shape 변경과 다름 |
| FK | named measured q와 모델로 Link pose 계산 | 파일명/6개 숫자만으로 동일 Robot이라 하지 않음 |
| Hand-eye | 한 Camera Mount와 로봇 운동 사이 공유 Transform 추정 | 각 q에 독립 Camera를 맞추는 문제와 다름 |
| Gauge | 관측만으로 정할 수 없어 선택한 기준 | support +Z를 Robot World 측정으로 부르지 않음 |
| Residual | 예측과 실제 관측 차이 | 좋은 잔차가 잘못된 모델을 배제하지 않음 |
| Jacobian | 변수 변화가 residual에 주는 미분 | prior를 데이터 관측 가능성과 혼동하지 않음 |
| Rank | 독립적으로 관측한 변수 방향 수 | rank6/6이 실물 정확도 인증은 아님 |
| Condition number | 독립 방향 사이 sensitivity 불균형 | full rank여도 불안정할 수 있음 |
| raw-relative Cloud | optical point/ray와 상대 Depth를 보존한 자료 | Camera fit 후 새 World point가 필요 |
| fixed_world Cloud | anchor로 World에 묶은 자료 | Camera fit 뒤 점을 따라 움직이면 안 됨 |
| Collision | 엔진 접촉에 쓰는 별도 형상 | Viewer cyan 선이나 authored hull 존재가 접촉 검증은 아님 |
| Feature/Silhouette | normal 각도/경계와 시선별 외곽선 | 65Part라는 개수가 65의미 있는 모서리를 증명하지 않음 |

수식과 구현은 [03장](03-camera-assets-simulation.md)에 한 번만 상세히 둔다. 이 표는 코드 속 용어를 해석하는 출발점이다.

### 3.3 Dataset과 Policy

| 용어 | 구체적 의미 | 첫 코드 |
|---|---|---|
| Episode | 한 시도의 정렬된 관측·명령·metadata | [data.native.NativeEpisode · L116](../../robot_learning_workbench/src/robot_learning_workbench/data/native.py#L116) |
| Frame | record loop의 한 샘플, 실제 시간/phase와 정렬 | [data.recording.record_frame · L14](../../robot_learning_workbench/src/robot_learning_workbench/data/recording.py#L14) |
| Action | 문맥에 따라 7D EE delta+gripper 또는 6D absolute joint target | [data.lerobot.control_contract · L38](../../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py#L38) |
| Observation | RGB/q/상태 등 Policy/Task가 소비하는 관측 | [learning.policy.observation_batch · L108](../../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py#L108) |
| Annotation | 기록된 demo에서 Subtask/신호/acceptance 경계 부여 | [engines.mujoco.annotation.run · L99](../../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/annotation.py#L99) |
| Mimic | 원 demo Subtask를 Object pose에 맞춰 변환/보간하는 계산 | [generation.mimic.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/generation/mimic.py#L1), [generation.reference.data_generator.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/generation/reference/data_generator.py#L1) |
| IK | 목표 EE pose를 joint target으로 바꾸는 계산 | [generation.mimic.solve_dls · L291](../../robot_learning_workbench/src/robot_learning_workbench/generation/mimic.py#L291) |
| Curation | 원 data payload를 복사하지 않고 선택/trim/split 선언 | [data.curation.save_curation · L38](../../robot_learning_workbench/src/robot_learning_workbench/data/curation.py#L38) |
| Lineage | 현재 Episode가 어떤 원 Episode/Resume 계보에서 왔는지 | [data.lerobot._origin · L196](../../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py#L196) |
| Leakage | train에 쓰인 원 Episode가 평가에 재등장하는 것 | [data.lerobot.episode_overlap · L235](../../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py#L235) |
| Feature mapping | Native 필드와 공식 Policy feature의 의미/shape/단위 대응 | [data.lerobot.materialize · L292](../../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py#L292) |
| ACT | LeRobot의 구현을 사용한 action chunking policy | [learning.policy.load_policy · L213](../../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py#L213) |
| Processor | 관측/정규화·출력의 공식 전후처리 | [learning.policy.observation_batch · L108](../../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py#L108), [learning.policy.predict · L256](../../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py#L256) |
| Resolved Config | null/default/Resume relocation을 공식 parser가 해석한 값 | [learning.policy._resolved_request · L46](../../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py#L46) |
| Seal | Checkpoint의 필수 파일/유한 값/설정/Dataset/Step을 검증해 record 게시 | [learning.policy.seal_checkpoint · L152](../../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py#L152) |
| Task success | 현재 predicate가 실제 engine/관측에서 판정한 결과 | [tasks.evaluation.evaluation_result · L15](../../robot_learning_workbench/src/robot_learning_workbench/tasks/evaluation.py#L15) |
| Initial-state success | Policy 동작 전 배치만으로 목표가 이미 만족됨 | [tasks.evaluation.evaluation_result · L15](../../robot_learning_workbench/src/robot_learning_workbench/tasks/evaluation.py#L15) |
| Independent Test | solver/선택/사용자 반복 수정에 소비하지 않은 새 자료 | [observations._record_holdout_usage · L23](../../real2sim_builder/src/real2sim_builder/observations.py#L23) |

<a id="learning-resume"></a>
## 4. 네 가지 Resume

처음 읽을 때 가장 혼동하기 쉬운 이름이다.

**Reconstruction Resume**는 Candidate의 완료 Stage/Worker Artifact를 입력·설정·code/model/Source SHA와 함께 다시 검증해 재사용하는 것이다. 입력을 바꾸고 예전 Cache를 무조건 믿지 않는다. 멈춘 Stage의 부분 결과는 실패 근거로 남지만 성공 Cache로 승격하지 않는다.

**Native Source/Datagen Resume**는 이미 게시한 Episode와 attempt seed/lineage를 보존하면서 추가 자료를 생성하는 것이다. 기존 Family의 미확인 Episode를 독립 평가 자료로 추측하지 않는다.

**Training Resume**는 Optimizer/Scheduler/RNG/Step을 가진 공식 Checkpoint에서 누적 학습을 이어가는 것이다. config의 허용 변경과 Dataset identity를 검증하고 새 출력에 동결한다. 단순 `load_state_dict(weights)`와 같지 않다. 미세조정(finetune)은 다른 목적의 초기 가중치 로딩이므로 mode도 구별한다.

**UI 재개방**은 저장 Script/RunHandle을 읽어 화면을 복원하는 것이다. 자체로 작업을 다시 실행하는 명령이 아니다. 한 단어의 Resume를 네 곳에 같은 의미로 적용하지 말자.

<a id="learning-order"></a>
## 5. 권장 학습 순서

| 순서 | 읽을 내용 | 종이에 그려 볼 것 | 이해 확인 |
|---:|---|---|---|
| 1 | README → 01장 | Qt/단기Backend/장기Worker의 세 수명 | Backend 응답이 와도 작업이 끝난 것은 아닌가? |
| 2 | scene.value/validate → Project/Candidate | Current·Candidate·Revision | 값과 provenance가 어떻게 같이 이동하는가? |
| 3 | 02장 입력 → Stage1–4 | Photo/Reference/Capture, K/Z/pose | pixel grid와 Robot World는 언제 정해지는가? |
| 4 | Stage5–8 → Asset/Viewer | Mask/Crop/generated RGB/NPZ → native Mesh/Pose | Codex가 결정하는 값과 Python solver가 결정하는 값은 무엇인가? |
| 5 | 03장 Frame/FK/K → Stage10 | 각 Transform의 source/target | Wrist와 Photo Camera를 같은 자유 변수로 두면 왜 잘못되는가? |
| 6 | Joint residual/rank → Cloud | trial projection와 Consumer dependencies | 잔차 감소와 채택이 왜 다를 수 있는가? |
| 7 | 04장 Source/Annotation/Mimic | pre-step record, post-step Task, attempt | action과 applied target/measured q가 같은가? |
| 8 | Native/Curation/LeRobot | pending→commit, 선택/trim/lineage | 파일이 존재하지만 읽으면 안 되는 시점은 언제인가? |
| 9 | Config/Trainer/Seal/Resume | 요청/해석/저장 config, Step·RNG | null/default 차이가 진짜 설정 변경인가? |
| 10 | Evaluation/R03/NEW-03 | Task result·publication·process exit | completed+exit7을 어떻게 해석하는가? |
| 11 | 05장 26개 결함과 두 위험 | 각 Producer→Consumer의 빠진 계약 | 같은 유형의 회귀를 어떤 assertion으로 잡는가? |
| 12 | 06/07장 → 자기 기능 하나 추적 | UI button부터 최종 파일 Reader까지 | 함수 이름만 찾는 대신 실제 Consumer까지 따라갔는가? |

하루에 모든 파일을 읽을 필요는 없다. 한 함수에서 입력 schema와 출력 Consumer를 찾아 연결한 뒤 관련 테스트의 assertion을 확인하면 된다. 빨리 실행해 보는 것이 항상 더 깊은 이해는 아니다. 장치/모델이 필요 없는 읽기 과제부터 시작한다.

<a id="learning-ten-files"></a>
## 6. 처음 열 핵심 코드 10개

이 표는 기능 중요도의 절대 순위가 아니라, 처음부터 구현하지 않은 소유자를 위한 연결 순서다. 파일 path는 실제 구현으로 연결한다.

| # / 파일 | 읽는 이유 | 먼저 볼 함수 | 이어서 볼 파일 | 이해하고 나면 알게 되는 것 |
|---:|---|---|---|---|
| 1. [ui.app.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/ui/app.py#L1) | 프로그램의 화면 구획과 소유 객체를 봄 | Window.__init__, main | ui/workflow.py, ui/session_page.py | 화면 선택·버튼·작업 실행이 서로 다른 단계임 |
| 2. [ui.workflow.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/ui/workflow.py#L1) | start/Stop/Step/state의 실제 UI 연결 | start_run, job_finished, poll | ui/jobs.py → ui/operations.py | 위젯 요청이 Backend/RunHandle/ACK가 되는 경로 |
| 3. [run.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L1) | 중복 실행 방지·상태·종료를 묶는 중심 | start, execute, _run_stage, _monitor | recipe.py, cli.py | 작업 완료와 프로세스 종료의 차이 |
| 4. [recipe.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L1) | 저장 Script와 해석된 실행 계약의 경계 | read_recipe, prepare_recipe, verify_prepared_inputs | tasks/registry.py, scene_contract/package.py | 상대 경로/함수/설정/Source SHA를 실행에 고정하는 법 |
| 5. [project.py · L1](../../real2sim_builder/src/real2sim_builder/project.py#L1) | 입력·Current·제어·작업 소유권의 시작 | Project.create, signature, checkpoint | candidate.py, evidence.py | 원본과 mutable 작업 상태를 분리하는 이유 |
| 6. [automation.py · L1](../../real2sim_builder/src/real2sim_builder/automation.py#L1) | Stage 전체와 기존 Refit의 조율 | reconstruct, _run_stage_pipeline, refit_pairs | reconstruction_stages.py, stage_runtime.py | 자동 재구성 기본 경로와 명시 Refit 경로 차이 |
| 7. [reconstruction_stages.py · L1](../../real2sim_builder/src/real2sim_builder/reconstruction_stages.py#L1) | 14단계가 실제로 소비/생성하는 것을 봄 | prepare, depth, decompose, meshes, compile_scene | stage_workers.py, authoring.py, object_assets.py | 모델 이름과 실제 호출조건·Artifact가 어떻게 연결되는가 |
| 8. [calibration.joint.py · L1](../../real2sim_builder/src/real2sim_builder/calibration/joint.py#L1) | 로봇·카메라 수학이 software 계약이 되는 곳 | parameter_blocks, fit_joint_scene, apply_parameters | capture.py, calibration/hybrid.py | residual/rank/채택·Cloud 갱신의 구분 |
| 9. [data.native.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/data/native.py#L1) | 데이터 완료·불변성의 실제 기반 | NativeRun, load_catalog, resume_to | data/lerobot.py, data/curation.py | Episode writer commit과 Dataset identity의 의미 |
| 10. [learning.train.py · L1](../../robot_learning_workbench/src/robot_learning_workbench/learning/train.py#L1) | 자체 코드와 공식 Trainer의 책임 구분 | training_command, freeze_inputs, train | learning/policy.py, learning/validate.py | 요청/공식 config/Checkpoint/Resume를 안전하게 묶는 법 |

`scene.py`, `object_assets.py`, `scene_contract/package.py`, `generation/mimic.py`, `learning/policy.py`도 곧 따라 읽어야 한다. 열 개 표에 없다는 이유로 중요하지 않은 파일은 아니다. 본문은 한 화면의 클릭부터 다음 파일로 이어지는 경로를 우선했다.

<a id="learning-questions"></a>
## 7. 읽고 이해했는지 확인하는 질문

- 검증된 asset version의 texture만 다르게 보인다면 source USDA, converter, viewport 중 어느 경계를 각각 확인할까?
- Native dataset의 첫 Episode만 저장된 상태에서 cancel되면 원본/부분 Writer/Reader에 어떤 결과가 남아야 할까?
- full rank이지만 train과 validation에 같은 Capture group이 섞였다면 독립 정확도라고 말할 수 있을까?
- Scene scale이 m라고 선언됐지만 anchor가 없으면 measurement 정확도를 설명할 근거가 충분한가?
- sealed Checkpoint가 생겼는데 Trainer 프로세스는 살아 있을 수 있는가? 어떤 marker와 Caller를 확인해야 할까?
- 새 Stop을 전달했다는 이유만으로 `cancelled`를 UI가 먼저 표시하면 어떤 사실을 잃을까?

답은 [26개 결함 해설](05-bug-fixes-explained.md)과 [안전한 추적 실습](07-execution-and-debugging.md)에 있다. 정답 문장 외우기보다 실제 source line과 assertion으로 설명할 수 있는지를 기준으로 삼는다.
