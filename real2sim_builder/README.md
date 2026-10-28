# Real2Sim Builder

Offline project/candidate reconstruction, calibration, review and immutable Scene packages. Runtime files follow the existing Architecture; Native Dataset storage is owned by the Workbench and is unchanged.

See [BU01–BU04 results](../docs/builder-bundle.md) for commands, fixed installed environments, original-source comparisons, test evidence and limitations.

Use `python -m real2sim_builder.cli --help`. Existing unmarked projects open read-only. `clone SOURCE NEW_DESTINATION` creates a separate editable project. `export PROJECT --destination NEW_PACKAGE` requires a fresh successful review; explicit `--allow-unvalidated` creates an unvalidated review package. `verify NEW_PACKAGE` verifies the Scene and native file closure.

MuJoCo and the installed Isaac Sim USD bindings are required for native Export parsing. They are not imported when opening the package or inspecting a project. Use the existing process-local USD path configuration documented in the bundle report. The optional UI uses the existing Qt interpreter and a separately selected calculation worker. No package installation or environment upgrade was performed during implementation.

Run the repository's recorded verification command:

```bash
bash docs/evidence/builder/run_tests.sh scene_contract/tests robot_learning_workbench/tests real2sim_builder/tests -q
```

Static USD/MJCF parsing and EGL/Blender rendering do not establish articulation, PhysX/Fabric, sensor or physical-contact equivalence. Those remain E01/E02 integration gates. No real robot or camera is connected by these APIs.
