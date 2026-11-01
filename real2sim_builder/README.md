# Real2Sim Builder

Offline project/candidate reconstruction, calibration, review and immutable Scene packages. Runtime files follow the existing Architecture; Native Dataset storage is owned by the Workbench and is unchanged.

**Codex로 Scene을 만들거나 정합할 때는 [Scene 제작·정합 가이드](SCENE_AUTHORING.md)를 먼저 읽으세요.** Scene Prepare 입력/메모 → Builder Candidate 제작 → Export → Real/Sim 비교의 현재 절차와 CLI, 다음 작업 요청 예시를 정리했습니다.

상세 제작 기준은 [SCENE_RULES.md](SCENE_RULES.md), 기존 AGENTS/docs 전체의 반영 내역은 [SOURCE_DOCUMENTS.md](SOURCE_DOCUMENTS.md)에 있습니다.

See [BU01–BU04 results](../docs/builder-bundle.md) for commands, fixed installed environments, original-source comparisons, test evidence and limitations.

Use `python -m real2sim_builder.cli --help`. Existing unmarked projects open read-only. `clone SOURCE NEW_DESTINATION` creates a separate editable project. `export PROJECT --destination NEW_PACKAGE` requires a fresh successful review; explicit `--allow-unvalidated` creates an unvalidated review package. `verify NEW_PACKAGE` verifies the Scene and native file closure.

MuJoCo and the installed Isaac Sim USD bindings are required for native Export parsing. They are not imported when opening the package or inspecting a project. Use the existing process-local USD path configuration documented in the bundle report. The optional UI uses the existing Qt interpreter and a separately selected calculation worker. No package installation or environment upgrade was performed during implementation.

Run the repository's recorded verification command:

```bash
bash docs/evidence/builder/run_tests.sh scene_contract/tests robot_learning_workbench/tests real2sim_builder/tests -q
```

Static USD/MJCF parsing and EGL/Blender rendering do not establish articulation, PhysX/Fabric, sensor or physical-contact equivalence. Those remain E01/E02 integration gates. No real robot or camera is connected by these APIs.
