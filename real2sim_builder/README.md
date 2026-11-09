# Real2Sim Builder

Offline project/candidate reconstruction, calibration, review and immutable Scene packages. Runtime files follow the existing Architecture; Native Dataset storage is owned by the Workbench and is unchanged.

기본 진입점은 Scene Prepare의 **Auto Reconstruction** 또는 Builder의 **Start Reconstruction**입니다. Scene/Model 사진과 자유 메모를 Codex가 직접 분석하고, 기존 Blender에서 Object별 USDA를 제작·재사용한 뒤 실제 Simulator 렌더를 비교·수정합니다. SAM/DA3/MASt3R/COLMAP·Depth·Metric 등록은 제품 Reconstruction의 필수 단계가 아닙니다. 단일 실행 화면의 **제작 기록 / 결과 이미지 보기**에서 최초 Scene·반복 Before/After·실제 생성 파일과 실패 기록을 확인합니다. 사용법은 [AUTO_SCENE_FITTING.md](AUTO_SCENE_FITTING.md), 제작 규칙은 [SCENE_RULES.md](SCENE_RULES.md), 이관 내역은 [SOURCE_DOCUMENTS.md](SOURCE_DOCUMENTS.md)를 따릅니다.

GLB/glTF 입력·Scan 모듈/CLI/UI는 제거했습니다. 과거 의존 자산은 원본 그대로 보존하며 새 정합/Export에서 `LEGACY_UNSUPPORTED`를 반환합니다. 실측 Geometry constraint는 `candidate PROJECT constrain NAME --options constraints.yaml`로 사용합니다.

현재 구현과 실제 실행·미검증 범위는 [Codex-First 구현 기록](../docs/codex-first-scene-builder.md)에 있습니다. 과거 [단계별 기록](../docs/automated-reconstruction.md)은 당시 검증 범위로 보존합니다. 사진 기반 Camera/Pose 추정과 시각 초안은 실측 Calibration·접촉/마찰·Task 성공 인증과 구분합니다.

See [BU01–BU04 results](../docs/builder-bundle.md) for commands, fixed installed environments, original-source comparisons, test evidence and limitations.

Use `python -m real2sim_builder.cli --help`. Existing unmarked projects open read-only. `clone SOURCE NEW_DESTINATION` creates a separate editable project. `export PROJECT --destination NEW_PACKAGE` requires a fresh successful review; explicit `--allow-unvalidated` creates an unvalidated review package. `verify NEW_PACKAGE` verifies the Scene and native file closure.

MuJoCo and the installed Isaac Sim USD bindings are required for native Export parsing. They are not imported when opening the package or inspecting a project. Use the existing process-local USD path configuration documented in the bundle report. The optional UI uses the existing Qt interpreter and a separately selected calculation worker. No package installation or environment upgrade was performed during implementation.

Run the repository's recorded verification command:

```bash
bash docs/evidence/builder/run_tests.sh scene_contract/tests robot_learning_workbench/tests real2sim_builder/tests -q
```

Static USD/MJCF parsing and EGL/Blender rendering do not establish articulation, PhysX/Fabric, sensor or physical-contact equivalence. Those remain E01/E02 integration gates. No real robot or camera is connected by these APIs.
