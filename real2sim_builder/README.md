# Real2Sim Builder

현재 VLM/레거시 정리 계약: [Codex VLM 전환](../docs/codex-vlm-migration.md). DA3/SAM/FLUX/Bria/CPD Runtime은 유지하고 시각 판단은 기존 Codex 로그인·모델·추론 강도를 공유한다.

체크포인트 포함 범위·최신 검증 한계와 로컬 모델/Runtime 경로 재설정은 [체크포인트 안내](../docs/simfoundry-checkpoint.md)를 따릅니다. 실제 Workspace 설정·가중치·진단 자료는 Git에 포함하지 않습니다.

Offline project/candidate reconstruction, calibration, review and immutable Scene packages. Runtime files follow the existing Architecture; Native Dataset storage is owned by the Workbench and is unchanged.

기본 진입점은 Scene Prepare의 **Auto Reconstruction**입니다. 기본 엔진은 SimFoundry Stage1–14이며 DA3 Nested Mixed Precision, SAM3/VLM 분해, Codex+Sandbox Blender Mesh, CPD Pose, 기존 USD/MuJoCo/Isaac 경계를 사용합니다. Stage별 Artifact·Stop/Resume와 기존 계정/모델/사용량·제작 기록 UI를 유지합니다. 실제 Runtime 준비와 부분 구현 범위는 [전환 기록](../docs/simfoundry-reconstruction-migration.md), 설정은 [템플릿](config/simfoundry-reconstruction.example.yaml)을 확인하세요. Source 기반 Real/Sim 재정합은 기존 흐름을 유지합니다.

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
