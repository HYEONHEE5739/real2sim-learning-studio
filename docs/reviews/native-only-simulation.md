# Native Simulation 전용 실행 전환

2026-11-18. `feat/simfoundry-style-reconstruction`, 시작 HEAD `8d5e219233e367fccfa6b7e2765aecbdbe50e32b`. 사용자 지시에 따라 Authored 실행 호환성을 제거했다. 이전 Isaac Camera Schema 수정과 미커밋 작업 위에 변경했으며 Commit/Push·설치·모델 추론·실물 장치 연결은 하지 않았다. 사용자 Scene/Asset/Capture/URDF/Calibration/과거 Package를 이전하거나 삭제하지 않았다.

## 결정과 새 실행 흐름

Auto Reconstruction과 직접 `export_revision()` 호출, CLI Export, 검증 후 Reconstruction Export가 같은 Native 프로필 생성을 거친다. 별도의 실행기나 마이그레이션 계층은 없다.

```text
Scene / Candidate
  → export_revision: SHA·closure·USD/MJCF parser
  → native_profiles: URDF / Mapping / Base / Camera / Collision / 초기 q 검사
  → execution_profiles.json + engine별 native_readiness
  → register_export: Revision/엔진/모드에 고정된 설정
      ├─ Real/Sim → Native Pose → measured q → FK/Native Camera, Physics Step 0
      └─ Source / Annotation / DataGen / 물리 평가 → Native Physics
                                                  → 목표 관절 / 중력 / 접촉 / 실제 Step
```

`--allow-unvalidated`는 미승인 Review 자료를 보존하는 허용이다. 실행 준비 부족을 허용하는 옵션이 아니다. URDF 등이 없는 Review Package는 구체적인 `native_readiness.*.needs`를 보존하고 실행 설정을 생성하지 않는다. Stage14는 선택 엔진의 Native Pose 설정이 없으면 `NEEDS_MORE_DATA`로 중단한다. Physics 물성이 부족하면 Pose 준비와 별도로 Physics를 차단한다. Parser/Loader 통과·시각 비교·물리 정확도·승인은 서로 다른 상태다.

Real/Sim은 등록된 `.pose`만, Source/Workspace Pipeline은 `.physics`만 선택한다. 잘못된 모드를 Recipe/Factory에서 거부한다. Annotation/DataGen이 Dataset에 고정된 기존 Native Physics `model_config`를 재생하는 경로도 유지하며, 불필요한 두 번째 설정 파일을 요구하지 않는다. 실제 Engine Loader가 그 모델·설정을 다시 검사한다. 선택한 엔진을 사용할 수 없으면 UI 연결 버튼을 막고 이유를 표시한다. 준비된 다른 엔진으로 자동 전환하거나 이전 Revision으로 돌아가지 않는다.

## 제거한 코드와 설정

- Workbench `robot/authored_render.py` 전체: `AuthoredRenderer`, Authored FK/센서 binding 및 비교 렌더 구현.
- `pose_render`의 Authored factory, `scene_render`의 Authored binding/모드 분기, Render Worker의 Authored 스케줄링 조건.
- Stage14 Worker의 Builder 정적 Renderer/IsaacRenderer 대체 실행 분기.
- Export/Registration의 Authored 기본값·공유 `export-authored-preview.json` 생성·임의 `engine_config` 등록 분기.
- `export_revision(execution_mode=...)`, `export_revision(engine_config=...)` 인자와 Reconstruction `simulator.mode` 선택 설정. 폐기한 설정은 명시적으로 거부한다.
- Recipe의 Authored 실행 코드 Identity 항목, UI의 Authored 상태 문구와 엔진 자동 대체.
- Authored 실행 전용 시험. 유지해야 하는 Mapping·왜곡·Timing·센서·Capture·재개 검사는 Native 시험으로 옮기거나 기존 Native 실제 시험과 연결했다. 과거 값 `AUTHORED_UNVALIDATED`는 Object Collision 제작 상태이므로 Scene 실행 모드와 혼동해 지우지 않았다.

## 유지한 Scene 데이터와 도구

| 파일 / 도구 | 현재 필요한 참조 |
|---|---|
| `authored_scene.json` | Package 내부로 경로를 옮긴 Scene 원본. MuJoCo Native 모델이 Visual/Collision/Material·로봇 Link 부착물을 조립하며, Isaac의 Static/Mounted/Dynamic USD 분리와 Wrist mount 계산도 읽는다. Task 추출·Source 기반 재정합·Pair Scene SHA도 참조한다. 이름을 바꾸거나 제거하지 않았다. |
| `scene.json`, `scene.xml`, `scene.usda` | Manifest-bound Scene 계약과 Native Geometry/Material 입력. Native Robot Articulation·Runtime 모델을 구성할 때 사용한다. 정적 Scene 파일을 Authored Preview로 실행하는 연결은 제거했다. |
| `provenance.json` | 원본 Scene/Memo/Evidence/검증 출처. Native 입력의 출처를 보존하며 원 Project를 찾아 실행하는 fallback이 아니다. |
| `calibration.json`, URDF·Mesh·Collision closure | Follower Mapping, Source/Execution Model SHA, Joint 순서·한계, Base/FK와 Collision의 실행 근거. 원본 bytes는 보존한다. |
| `camera_projection.json` | 원래 K/Distortion/Pixel Grid와 Native Real/Sim의 명시적 왜곡 후처리 계약. Source/DataGen의 미지원 왜곡을 0으로 고쳐 통과시키지 않는다. |
| Builder `rendering.py`, `isaac_render.py`, exporter | 사진/Asset 제작·수치 정합과 Native 파생 자산 생성을 위한 내부 기하 도구. 실행 Package의 Authored 호환 Renderer로 사용하지 않는다. |
| 과거 Scene/Export/진단 | 파일 보존. Native 프로필이 없는 과거 등록은 실행 엔진을 제공하지 않으며 자동 변환하지 않는다. |

기존 `scene_migration.register_package`는 Native 프로필과 준비 메타데이터가 없는 Package를 **복사 전에** 거부한다. 과거 Native 실행 자산을 다루는 기하/Calibration 수학을 Authored 실행 코드로 오인해 제거하지 않았다. 제품에 특정 `auto_version`/Scene 이름을 위한 예외를 추가하지 않았다.

## 실행 준비 검사와 사용법

공통: Manifest·실제 파일 SHA/closure, URDF와 정확한 여섯 Joint·Mapping의 모델 SHA, 유한한 초기 model rad/Joint Limits, Robot Base, 고정 Side·robot-link에 부착된 공유 Wrist, 명시 역할·K·640×480 Grid를 검사한다. Visual이 있는 Robot Link에 Collision이 없으면 Link 이름과 함께 차단한다. Object Visual/compound/convex Collision의 기존 검증은 유지한다.

MuJoCo는 실제 `build_model` Compile을 수행한다. URDF Link의 관성 입력이 없으면 불명확한 `NoneType` 오류로 Export를 중단하던 경로도 RED로 재현하고, Link 이름·inertial mass/tensor가 필요하다는 차단 사유로 바꿨다. Isaac은 패키지 안의 USD binding과 `ArticulationRoot`를 요구한다. 정적인 Robot USD나 다른 엔진으로 대체하지 않는다. Physics는 활성 Object의 양수 mass와 비음수 friction을 추가로 검사한다. 값의 `measured/estimated/unknown` 출처와 `physical_verified=false`를 유지한다. Loader 준비를 독립 물리·센서 보정 인증으로 승격하지 않는다.

```python
export_revision(project, destination=new_package, allow_unvalidated=True,
                native_options={"initial_joint_rad": six_explicit_model_radians})
# Follower Mapping은 Scene의 robot_model.mapping 또는 native_options["mapping"].
# initial_joint_rad를 생략하면 모델 SHA/Joint 순서가 맞는 실제 Capture가 필요하다.
```

CLI에는 `--initial-joint-rad Q1 Q2 Q3 Q4 Q5 Q6`, 선택 `--mapping FILE`을 제공한다. 임의의 0 자세를 실측으로 생성하지 않는다. Reconstruction YAML은 `simulator.engine`과 필요 시 `simulator.native_options`를 사용한다. `simulator.mode`는 제거했다. 생성된 `configuration/native-<manifest>-<engine>-pose.json`과 `-physics.json`은 서로 다른 실행 의미와 Revision identity를 가지므로 합치거나 덮어쓰지 않는다.

기존 UI/로컬 Runtime 설정은 이번에 다시 저장하지 않았다. 과거 Authored Package가 남아 있더라도 실행 호환 설정을 자동 생성하지 않는다. 필요한 입력을 검토한 새 Native Revision만 게시한다.

## Isaac 실제 검증과 미해결 항목

기존 렌즈 스키마 사전 등록을 보존했다. Native Package parser가 Kit보다 먼저 USD Stage를 열면 PhysX 스키마도 늦게 등록되는 결함을 별도 Child에서 RED로 재현했다. 설치된 `plugInfo.json`의 실제 alias `PhysxSceneAPI`로 검사한 RED와 수정 후 GREEN을 보존했다. 최초 시험에서 C++ 클래스 이름을 API alias로 쓴 Harness 오류 로그도 구분해 남겼다.

같은 준비 함수가 설치된 lens/PhysX 리소스를 첫 Stage 이전에 등록하며 Source/Annotation/DataGen/평가 Recipe도 parser 이전에 호출한다. 실제 USD에서 lens 적용·K readback·PhysX API 적용을 확인했다. 모듈 import만으로 Kit나 장치를 초기화하지 않는다. [OpenUSD SchemaRegistry](https://openusd.org/dev/api/class_usd_schema_registry.html)의 등록 타입/Prim 정의 계약을 대조했으며, 초기화 순서에 따른 차이는 로컬 새 프로세스로 재현했다.

실제 Isaac 검증에는 사용자 Scene 대신 합성 6관절 URDF/Mapping과 독립 Articulation USD를 생성했다. 첫 실행은 PhysX 스키마 오류로 abort(exit134)했다. 수정 뒤에는 Native Pose/Physics 선언 검사, 실제 `ManagerBasedEnv` Scene 생성과 simulation start까지 진행했다. **RGB 생성 전에 `Invalid object in Py_Graph in getWrappedGraphFromNode`가 발생했고 `SimulationApp.close()`에서 세그멘테이션 오류(exit139)가 났다.** 이 실행에서 Native RGB/Joint/Contact 검증 성공을 주장하지 않는다. 같은 로그의 MDL 컴파일·Hydra 생성 실패·change-watch ENOSPC의 정확한 인과관계는 미확정이다. SDK·전역 sysctl을 고치거나 다른 Renderer로 우회하지 않았다.

이전 작업의 `omni.usd` 감시기 종료 대기와 이번 종료 세그멘테이션 오류는 별도 미해결 항목이다. 소유 Child에 60초+5초 종료 상한을 두었으나 이번 두 실행은 각각 abort/segfault로 먼저 끝났다. 정상 종료·Isaac Native 영상/물리 검증 완료로 보고하지 않는다. 동일 실패를 설정만 바꿔 무한 재시도하지 않았다. 실물 Real/Sim 재연결·Teleop·실측 정합·Task 성공도 미검증이다.

진단은 Git 제외 `workbench_runs/diagnostics/native_only_transition_20261118_001/`에 있다. 제품은 진단 폴더를 import하지 않는다. 집중 시험·보존 대조의 최종 수치는 아래 마감 기록을 따른다.

## 집중 시험

최종 집중 묶음 **107 passed / 실패0 / skipped0 / 29.93초 / exit0**. Export/Registration/Stage13–14, 실제 MuJoCo Native Pose/Physics, UI 선택, 새 프로세스 USD 스키마, Camera 수학·메타데이터, 폐기 설정 거부와 closure가 대상이다. 관련 경로·시험 노드를 명시했으며 전체 회귀를 실행하지 않았다.

그 외 직접 관련 등록·Stage1–14 Stop/Runtime 재개 **33 passed / 49.53초**, Native Session/Memory Capture 묶음 최종 고유 **13개 통과**, 관성 입력 누락 및 변경된 MuJoCo 모델의 실제 Pose/Physics **11 passed / 6.05초**를 확인했다. 서로 겹치는 시험을 합산하지 않은 **고유 149개가 최종 통과**, skip/xfail 우회는 없다. 이전 107개를 마지막 추가 시험의 전체 수치로 표시하지 않는다.

- RED: 직접 Export의 Authored 기본값, 과거 등록의 실행 노출, 잘못된 Camera Grid·Robot Collision의 준비 완료, 늦은 PhysX 스키마, 관성 입력 누락의 불명확한 예외. 각각 수정 전 실패와 수정 후 통과를 보존했다.
- 실제 MuJoCo: 같은 q의 RGB·Camera 동일성, Wrist FK 변화, NaN/Limit 거부, 실제 중력·접촉·관절 목표/실제값 구분, Native Producer→Recipe→소유 Render Child→frozen Capture 전달. 실제 Native Physics 시험에서 30 control interval을 진행하고 중력 낙하·접촉·추종 오차를 확인했다. Pose는 Physics Step 0이다.
- Memory Session: 기존 Native 자산의 읽기 전용 복사본과 모의 장치를 사용했다. Follower motor write 금지 상태에서 Real Side/Wrist와 같은 measured q의 Sim Side/Wrist 네 영상 저장을 확인했다. 별도 저장 중 제어 권한 유지 시험도 Memory Device로 수행했다. 실제 Serial/Camera를 열지 않았다.
- 실제 Qt offscreen: Native Pose/Physics 상태 문구·목록과 선택 재사용, 선택 엔진이 불가능할 때 연결 차단·명시 선택 뒤 진행을 확인했다. Object Library 창이나 무관한 전체 UI 회귀를 실행하지 않았다.
- 준비 검증과 물리 승인 분리: missing robot/mapping/q/mount/resolution/collision/inertial, 잘못된 모드/폐기 설정, 손상 Package와 변경 설정을 차단하며 미승인 Package/Candidate 상태를 유지한다.

중간 실패도 남겼다. 로봇 없는 Fixture에 대한 과거 `DRAFT_READY` 기대값 28개를 Native Stage14 차단 및 완료 Stage Cache 보존으로 갱신했다. 기존 Authored FK 렌더 5개 parameter case에 해당하는 전용 시험 3함수는 제거하고 Native 실행/Mapping/Camera/왜곡/리소스 시험을 유지했다. 새 Capture 시험의 PNG 지연 디코딩 계약과 기존 Session의 Physics Step/시간 기대값도 수정했다. 테스트 기대를 완화해 물리 실행으로 표시하지 않고, Pose의 실제 Step/시간 0을 검증한다. 실제 Isaac 실패는 이 pytest 통과 수치에 포함하지 않는다.

근거: `native-only-red.xml/log`, `consumer-red.xml/log`, `input-red.xml/log`, `physx-schema-identifier-red.xml/log`, `physx-schema-green.xml/log`, `inertial-red.xml/log`, `inertial-native-green.xml/log`, `release-focused.xml/log`, `registration-resume-green.xml/log`, `native-session-green.xml/log`, `native-capture-pose-verified.xml/log`, `native-code-identity-green.xml/log`, `test-summary.json`. Isaac 로그와 실패 JSON은 pytest XML과 별도로 보존했다.

## 마감·보존과 변경 파일

작업 시작에 보존한 `workbench_runs/{scenes,object_assets,robot_rigs,devices,calibration,runtime,source}` **19,820개 파일 / 9,188,981,471B**를 종료 시 SHA·크기로 대조했다. **변경0·누락0·신규0**이다. 사용자 Scene, 기존 Capture/URDF/Mesh/Asset/Calibration/Export/Runtime 설정도 이 범위에 포함된다. 전체 SDK/모델/Conda 디스크를 전수 대조한 것은 아니다.

작업 시작 HEAD `8d5e219233e367fccfa6b7e2765aecbdbe50e32b`, 현재 브랜치·Git Index를 보존했다. 기존 다른 미커밋 작업을 되돌리지 않았다. 변경 Python **33개**는 bytecode 없이 compile했고 `git diff --check`도 통과했다. Camera의 `_pinhole_properties`, `_set_native_pinhole`, `_native_pinhole_matrix` AST가 시작 상태와 같다. Capture·Queue·Teleop·R03 실행 소유권의 `real_sim.py/control.py/teleop_loop.py/snapshots.py/pairs.py/run.py`도 시작 SHA와 같다.

이번 시작 상태 대비 **수정38·신규2·삭제1, 총41개 파일**이다. 이전 미커밋 작업과 구분한 목록이다. 신규 제품 모듈은 없고 제품 삭제는 Authored Renderer 한 파일뿐이다. 설치/다운로드·AI 모델 Forward·실물 구동·전체 회귀·Commit/Push/Reset/Clean을 수행하지 않았다.

### 수정

- `README.md`
- `docs/precision-export-integration.md`
- `docs/reviews/native-simulation-capture-improvement.md`
- `real2sim_builder/README.md`
- `real2sim_builder/SCENE_AUTHORING.md`
- `real2sim_builder/config/simfoundry-reconstruction.example.yaml`
- `real2sim_builder/src/real2sim_builder/automation.py`
- `real2sim_builder/src/real2sim_builder/cli.py`
- `real2sim_builder/src/real2sim_builder/export.py`
- `real2sim_builder/src/real2sim_builder/reconstruction_stages.py`
- `real2sim_builder/src/real2sim_builder/registration.py`
- `real2sim_builder/src/real2sim_builder/stage_runtime.py`
- `real2sim_builder/src/real2sim_builder/stage_workers.py`
- `real2sim_builder/tests/test_execution_export.py`
- `real2sim_builder/tests/test_export_settings_reuse.py`
- `real2sim_builder/tests/test_render_targets.py`
- `real2sim_builder/tests/test_stage_compilation.py`
- `robot_learning_workbench/src/robot_learning_workbench/engines/isaac/env_cfg.py`
- `robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/model.py`
- `robot_learning_workbench/src/robot_learning_workbench/recipe.py`
- `robot_learning_workbench/src/robot_learning_workbench/robot/pose_render.py`
- `robot_learning_workbench/src/robot_learning_workbench/robot/render_worker.py`
- `robot_learning_workbench/src/robot_learning_workbench/robot/scene_render.py`
- `robot_learning_workbench/src/robot_learning_workbench/scene_migration.py`
- `robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py`
- `robot_learning_workbench/src/robot_learning_workbench/ui/pipeline_inputs.py`
- `robot_learning_workbench/src/robot_learning_workbench/ui/real_sim_page.py`
- `robot_learning_workbench/src/robot_learning_workbench/ui/session_operations.py`
- `robot_learning_workbench/tests/test_capture_render_timing.py`
- `robot_learning_workbench/tests/test_capture_stage_queues.py`
- `robot_learning_workbench/tests/test_capture_workload_isolation.py`
- `robot_learning_workbench/tests/test_export_registration.py`
- `robot_learning_workbench/tests/test_isaac_schema_bootstrap.py`
- `robot_learning_workbench/tests/test_native_reconstruction_execution.py`
- `robot_learning_workbench/tests/test_real_sim_observation.py`
- `robot_learning_workbench/tests/test_real_sim_page.py`
- `robot_learning_workbench/tests/test_scene_migration.py`
- `robot_learning_workbench/tests/test_scene_selection_performance.py`

### 신규

- `docs/reviews/native-only-simulation.md`
- `robot_learning_workbench/tests/test_native_only_execution.py`

### 삭제

- `robot_learning_workbench/src/robot_learning_workbench/robot/authored_render.py`

마감 근거: `change-inventory.json`, `compile-check.json`, `diff-check.log`, `test-summary.json`, `completion-check.json`, `preservation-after.json`, `isaac-runtime-summary.json`. 생성한 Isaac 테스트 Child의 잔존 프로세스는 0개이며 GPU 메모리는 관측 기준선 수준으로 반환됐다.
