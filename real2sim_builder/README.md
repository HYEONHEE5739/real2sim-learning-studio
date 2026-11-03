# Real2Sim Builder

Offline project/candidate reconstruction, calibration, review and immutable Scene packages. Runtime files follow the existing Architecture; Native Dataset storage is owned by the Workbench and is unchanged.

기본 진입점은 Scene Prepare의 **Auto Reconstruction** 또는 Builder의 **Start Reconstruction**입니다. 기존 SAM 3.1/DA3 환경을 순차 실행하고 실측 Geometry·등록된 Camera·Candidate 기반 정합으로 연결합니다. 사용법은 [AUTO_SCENE_FITTING.md](AUTO_SCENE_FITTING.md), 제작 규칙은 [SCENE_RULES.md](SCENE_RULES.md), 이관 내역은 [SOURCE_DOCUMENTS.md](SOURCE_DOCUMENTS.md)를 따릅니다.

GLB/glTF 입력·Scan 모듈/CLI/UI는 제거했습니다. 과거 의존 자산은 원본 그대로 보존하며 새 정합/Export에서 `LEGACY_UNSUPPORTED`를 반환합니다. 실측 Geometry constraint는 `candidate PROJECT constrain NAME --options constraints.yaml`로 사용합니다.

현재 구현과 미완료 항목·실제 검증은 [단계별 기록](../docs/automated-reconstruction.md)에 있습니다. Camera/depth bundle adjustment·독립 Backend 선정·Isaac PhysX/Articulation 검증을 완료한 자동 Scene 생성기는 아직 아닙니다.

See [BU01–BU04 results](../docs/builder-bundle.md) for commands, fixed installed environments, original-source comparisons, test evidence and limitations.

Use `python -m real2sim_builder.cli --help`. Existing unmarked projects open read-only. `clone SOURCE NEW_DESTINATION` creates a separate editable project. `export PROJECT --destination NEW_PACKAGE` requires a fresh successful review; explicit `--allow-unvalidated` creates an unvalidated review package. `verify NEW_PACKAGE` verifies the Scene and native file closure.

MuJoCo and the installed Isaac Sim USD bindings are required for native Export parsing. They are not imported when opening the package or inspecting a project. Use the existing process-local USD path configuration documented in the bundle report. The optional UI uses the existing Qt interpreter and a separately selected calculation worker. No package installation or environment upgrade was performed during implementation.

Run the repository's recorded verification command:

```bash
bash docs/evidence/builder/run_tests.sh scene_contract/tests robot_learning_workbench/tests real2sim_builder/tests -q
```

Static USD/MJCF parsing and EGL/Blender rendering do not establish articulation, PhysX/Fabric, sensor or physical-contact equivalence. Those remain E01/E02 integration gates. No real robot or camera is connected by these APIs.
