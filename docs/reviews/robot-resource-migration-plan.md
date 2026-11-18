# Robot 공용 자원과 참조형 Capture 전환 계획

2026-11-17. 현재 미커밋 작업 트리의 실제 호출 계약을 조사한 **구현 전 계획**이다. 이 문서 작성으로 모델을 등록·이동·복사하거나 기존 Scene/Capture/Device/Precision/Export를 수정하지 않았다. 구현·모델 추론·하드웨어 검증 결과가 아니다. 소스 근거 목록과 영향 범위는 Git 제외 `workbench_runs/diagnostics/capture_latency_followup_20261117_001/migration-impact.json`에 기록한다.

목표는 **프로젝트의 공용 `assets/robots`에 불변 Robot 자원을 한 번 등록하고, 새 Capture에는 모델 ID·Revision·SHA만 저장하며, 다른 컴퓨터로 내보낼 때만 필요한 모델 파일을 bundle하는 것**이다. 자산 원본은 실행 결과를 모으는 `workbench_runs` 밖에 둔다. Capture마다 `model/` 트리를 만드는 현재 동작을 새 Writer에서 제거한다. UI에서 보이는 이름은 `so101_with_camera`로 유지하고 저장 Revision은 내부 불변 identity로 취급한다.

## 1. 현재 코드에서 동시에 바뀌어야 하는 계약

`SnapshotStore.prepare`에서 `share_model` 한 줄만 지우면 Capture를 읽을 수 없게 된다. 모델이 Capture root의 `files`에 있어야 한다는 전제가 여러 소비자에 걸쳐 있다.

| 현재 소유 모듈 / 함수 | 실제 현재 계약 | 전환 시 필요한 변경 |
|---|---|---|
| `scene_preparation.robot_variants/select_robot_rig` | `robot_rigs/*/rig.yaml`을 검색하고 Project에 경로+SHA 선택 저장 | 기존 UI 선택을 공용 Robot ID·불변 Revision으로 연결. 기존 Candidate를 자동 변경하지 않음 |
| `evidence.load_robot_rig/import_robot_rig` | Rig manifest 전체 SHA·원본 FK·Camera fixed joint를 검증하고 모델/Visual closure를 Project 안으로 복사 | 기존 Robot 소유 함수에 등록/해석 경계 추가. 새 Candidate는 자원 참조와 FK/Visual binding을 저장하며 Robot 파일 사본을 만들지 않음 |
| `registration.bind_configuration/bound_configuration` | Project는 Device `capture.yaml` 자체 SHA를 고정 | 새 Device 선택에 Robot resource를 명시 결합. 공유 Scene 자동 재지정과 역사 Snapshot 변경 금지 |
| `recipe.prepare_recipe/verify_prepared_inputs` | `robot_model`은 실제 파일 경로를 `_artifact`로 고정. SDK 보정은 별도 고정 | 기존 `robot_model.path` 소비 형태를 유지하면서 resource manifest/closure identity도 준비 입력에 고정. 시작 전 변조·누락 확인 |
| `calibration.profile_for_model` | Precision은 URDF byte SHA에 결합. 기존 제한값만 다른 URDF는 명시 source/execution bytes를 대조해 메모리에서 결합 | 새 ID로 SHA를 대신하지 않음. `urdf_sha256`와 closure SHA를 별도로 유지. Camera 추가·geometry 변화의 자동 보정 승계 금지 |
| `snapshots.SnapshotStore.prepare/finish` | 매 Shot `share_model` 후 모델 SHA와 PNG/state/metadata를 포함해 닫고 Builder에 in-place 등록 | 세션 준비 때 검증한 resource identity를 새 Snapshot manifest에 기록. Shot에는 실제 관측/판정만 저장 |
| `robot.capture.share_model/save_session` | URDF 의존 파일을 순회해 각 Capture `model/`에 hardlink하고 SHA 계산 | 새 참조형 Writer에서는 호출하지 않음. 기존 embedded 형식/명시 portable bundle의 코드 경계는 별도 유지 |
| `capture._sensor_fields/mapping_contract` | `manifest.files[robot.path]`에서 모델 SHA를 읽고 Mapping의 URDF SHA와 비교 | 저장 방식과 독립적인 검증된 모델 identity를 받도록 기존 함수 확장. 모델 file lookup을 직접 하지 않음 |
| `capture.load_session/load_snapshots/validate_model_files` | 모델·모든 dependency가 Capture root 안의 hashed `files`에 있어야 함 | 새 명시 schema의 참조/embedded 분기를 검증. Capture 파일 무결성과 Robot resource closure 검증을 분리 |
| `capture._import_session/register_unbound` | 모델 경로가 Capture root 안이라고 가정하며 bound이면 Robot을 import | 새 참조형 관측은 공용 모델 참조를 Scene/Evidence에 연결. 측정 q·원본 Mapping·K/Mount provenance 유지 |
| `scene.local_path` | Project 밖 참조는 정확한 `../../object_assets/<ID>/vNNN/...`만 허용 | Robot namespace를 별도 좁은 규칙으로 명시. 임의 `../..`나 임의 외부 경로를 허용하는 방식 금지 |
| `calibration.execution_urdf/package_asset` | Manifest 소유 Package 안의 파일만 반환. baked residual이 있으면 명시 execution URDF 선택 | 로컬 실행 참조형 계약을 도입하는 단계에서 검증된 자원 해석 결과를 사용. portable Package의 기존 경계는 유지 |
| MuJoCo `build_model/build_native_model`, Isaac `execution_inputs/scene_execution_inputs` | self-contained Package의 URDF/MJCF/USD binding 사용. 일부 경로는 `package.root/path`로 직접 읽음 | 공용 identity를 해석한 경로를 기존 binding 단계에서 전달. 직접 root join을 모두 점검해야 함 |
| `generation.mimic.bind_kinematics/SO101Kinematics` | 명시 URDF 파일의 byte SHA를 확인하고 Pinocchio `buildModelFromUrdf` 호출 | 검증된 resolved URDF를 전달하면 수학은 유지 가능. IK identity에 closure도 추가하되 joint order/좌표/solver 검증 유지 |
| `export.copy_native_asset/export_revision/verify_package` | dependency를 Package 안으로 복사하고 닫힌 manifest 검증 | 외부 bundle 시에만 실제 payload를 복사. URI를 그대로 외부로 내보내거나 Workspace 참조가 남은 bundle을 성공 처리하지 않음 |

근거: [UI Rig 선택](../../robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py#L20), [Rig 검증/import](../../real2sim_builder/src/real2sim_builder/evidence.py#L418), [Snapshot Writer](../../robot_learning_workbench/src/robot_learning_workbench/robot/snapshots.py#L70), [모델 공유](../../robot_learning_workbench/src/robot_learning_workbench/robot/capture.py#L304), [Capture reader](../../real2sim_builder/src/real2sim_builder/capture.py#L475), [Capture 모델 containment](../../real2sim_builder/src/real2sim_builder/capture.py#L425), [Scene 경로 제한](../../real2sim_builder/src/real2sim_builder/scene.py#L64), [Recipe 입력 고정](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L385), [Precision 승계 제한](../../robot_learning_workbench/src/robot_learning_workbench/robot/calibration.py#L366).

## 2. 제안하는 저장 구조

```text
imitation_learnig_project/
  assets/robots/
    so101_with_camera/
      <closure_revision>/
        manifest.json
        so101_with_camera.urdf
        meshes/...
        textures/...          # 실제로 필요한 경우만
        rig.yaml              # Camera assembly/estimated mount 근거
  workbench_runs/scenes/<Scene>/
    project.yaml              # 새 제작에 선택한 Robot 참조
    input/captures/<Session>/capture_001/
      capture_manifest.yaml   # Robot ID + Revision + SHA
      state.json
      metadata.json
      side.png, wrist.png
      pair.json, sim_*.png    # paired 관측일 때만
      COMPLETE
```

`closure_revision`은 display name이 아닌 내부 불변 Revision이다. 한 모델을 수정하면 새 Revision이며 기존 폴더를 덮어쓰지 않는다. 최소 구현은 closure SHA를 내부 Revision으로 사용하는 것이다. UI에 `v006` 같은 제작 중 번호를 다시 강요할 필요가 없다.

이 그림은 **신규 등록 규격**이다. 기존 URDF의 상대 참조를 유지한 채 등록하려면 원래 entry 경로와 필요한 최소 상대 layout을 보존해야 한다. 모양만 위처럼 맞추려고 기존 URDF의 파일명/상대 경로를 고치면 byte SHA가 달라진다. 정돈된 경로로 새 URDF를 작성하는 경우는 명시적인 derived model로 등록하고 source SHA·변환 내역을 남겨야 한다. 기존 Precision의 모델 identity를 그 새 SHA로 몰래 바꾸지 않는다.

`assets/robots`는 Robot 모델과 fixed attachment의 공용 원본이다. 현재 `workbench_runs/robot_rigs/so101_with_camera`는 제작·검토 과정에서 만든 위치이며, 장기적인 원본 위치로 유지할 필요는 없다. 실제 이전은 새 등록/참조 경계를 만든 뒤 수행해야 한다. Scene World pose·측정 q·USB port·SDK 보정·실행 로그·Capture PNG를 이곳에 섞지 않는다. Optical K/Hand-eye가 보정되지 않은 Rig는 `estimated/uncalibrated`를 유지한다. 로봇 Geometry와 촬영 보정을 하나의 ‘정확한 Camera 모델’로 승격하지 않는다.

## 3. 모델 ID와 content identity

아래는 새 manifest의 **제안 필드**이며 현재 구현 schema가 아니다.

```json
{
  "schema": "real2sim.robot-resource/1",
  "resource_id": "so101_with_camera",
  "revision": "<closure_sha256>",
  "entry": "so101_with_camera.urdf",
  "urdf_sha256": "<entry byte SHA>",
  "closure_sha256": "<canonical dependency descriptor SHA>",
  "files": {
    "so101_with_camera.urdf": {"sha256": "...", "bytes": 123},
    "meshes/body.stl": {"sha256": "...", "bytes": 456}
  },
  "joint_names": ["..."],
  "units": {"length": "m", "angle": "rad"},
  "lineage": {"source_urdf_sha256": "...", "source_closure_sha256": "...", "operation": "explicit_import"}
}
```

`closure_sha256`은 정렬한 canonical descriptor의 schema·entry·각 상대 파일 경로/크기/SHA를 hash한다. URDF만 같고 Mesh·MTL·Texture·USD sublayer·MJCF include가 달라지는 경우를 구분해야 한다. 생성 시간·사용자 절대 경로는 content descriptor에서 제외한다. `manifest_sha256`은 완료된 manifest bytes의 hash로 **Capture 참조에** 넣고, manifest 자신에게 자신의 SHA를 넣는 순환 구조를 만들지 않는다.

URDF byte SHA는 기존 Precision/IK의 의미를 유지한다. Closure SHA는 실제 로딩하는 전체 Geometry/Material/엔진 dependency의 무결성이다. engine-derived USD/MJCF는 converter 코드·옵션·source closure를 포함한 별도 파생 identity로 등록한다. 같은 모델 이름만으로 URDF·물리 USD·MJCF를 서로 대체하지 않는다.

`lineage`에는 원본·변환 결과의 URDF/closure identity와 변환 종류·script/options SHA를 연결한다. 실제 old bytes를 보존해야 기존 보정의 source/execution 대조가 가능하다. 최초 resource 등록과 같은 요청의 반복 등록은 기존 ID+closure Revision을 재사용하고 생성 파일/폴더를 늘리지 않는다. 다른 ID의 의미적 모델을 외형이 같다는 이유로 자동 병합하는 기능은 추가하지 않는다.

## 4. Capture 참조 계약

기존 `real2sim.snapshot/1`은 embedded model을 요구한다. 필드를 빼고 계속 `/1`이라고 쓰면 기존 소비자가 정상 자료를 손상으로 판정하므로, 새 저장 계약은 **명시적인 새 Snapshot schema**가 필요하다. 예를 들면 `/2`의 `robot.storage=workspace_reference`와 다음 참조다.

```json
{
  "robot": {
    "storage": "workspace_reference",
    "resource": {
      "id": "so101_with_camera",
      "revision": "<closure_revision>",
      "manifest_sha256": "...",
      "urdf_sha256": "...",
      "closure_sha256": "..."
    },
    "mapping_verified": false
  }
}
```

Capture `files`에는 PNG/state/metadata/Pair 등 **자기가 소유한 파일만** 넣는다. 공용 모델 파일은 Capture-relative 파일처럼 위장하지 않는다. Mapping snapshot·measured q·시간·Camera identity·품질/미검증 상태는 지금처럼 해당 Capture에 고정한다. 저장소 간 위치가 달라져도 의미가 같은 기록을 보존하기 위한 작은 JSON이며 모델의 수천 파일 복제를 뜻하지 않는다.

Reader에는 기존 UI/Recipe 입력 준비 경계가 선택한 **공용 자산 root context**를 전달하고, 그 root의 `robots/<ID>/<Revision>`만 해석한다. 현재 `Project.workspace`는 `workbench_runs`를 가리키므로 그대로 `/assets`를 붙이면 위 제안과 다른 위치가 된다. 프로젝트의 `assets` root를 명시 전달하도록 같이 고쳐야 한다. Capture 상위 폴더 수를 추측하거나 홈/다른 프로젝트/과거 이름/모델 Cache에서 찾아다니지 않는다. ID의 path traversal, symlink escape, manifest/entry/closure SHA 불일치, 미등록 dependency, 누락된 Revision은 실패시킨다. 같은 ID의 최신 Revision으로 자동 대체하지 않는다.

같은 세션의 모든 Shot은 세션 시작 때 고정한 resource를 사용한다. 저장 도중 UI에서 모델 선택을 바꾸더라도 진행 세션이 바뀌지 않으며 다음 명시 연결에서만 채택한다. 새 Capture를 저장할 때 `model/`·Mesh·Texture·URDF hardlink가 하나도 생성되지 않는 것을 완료 기준으로 삼는다.

## 5. 등록·동시 실행·불변성과 성능

공용 자원 등록은 기존 Asset 등록의 lock/`.building`/SHA/원자적 rename 패턴을 기존 Robot 소유 함수에서 확장한다. 같은 ID+동일 closure의 동시 등록은 한 번 게시하고 나머지는 검증 후 재사용한다. source가 등록 중 바뀌면 publish하지 않는다. 다른 closure는 새 Revision으로만 등록하며 현재 모델 파일을 덮어쓰지 않는다. 새 전역 Process Manager·Registry DB·별도 서비스는 필요하지 않다.

모델 검증은 등록·세션 준비·시작 전 검증·외부 Export에서 전체 closure를 확인한다. control tick/각 PNG 저장 때 동일 Mesh 전체를 다시 읽지 않도록, 검증된 manifest/URDF·실행 모델을 세션 입력으로 고정한다. 세션이 모델 파일을 다시 열어야 할 때는 기존 준비 입력 불변 검사를 적용한다. stat fingerprint를 성능 cache에 쓸 수 있지만 **stat만으로 cryptographic 무결성이 증명된다고 표현하지 않는다.** 공유 모델의 source가 바뀌면 실패해야 하며 잘못된 bytes를 같은 ID로 받아들여서는 안 된다.

OS 소유자가 원본을 직접 덮어쓰는 것을 API 수준 불변성만으로 완전히 막을 수는 없다. 등록된 자원은 일반 경로에서 편집하지 않고 새 Revision을 만드는 계약·읽기 전용 권한·작성 lock을 함께 둔다. 모델 삭제는 참조 Capture·Project·Device·Package·Dataset lineage까지 확인한 명시 정리에서만 허용하고 자동 GC를 추가하지 않는다.

## 6. 로컬 실행과 외부 Package를 구분해야 한다

**Capture만 참조형으로 바꾸는 것은 첫 단계다.** 현재 MuJoCo/Isaac은 닫힌 `ScenePackage` 안의 파일을 요구하므로, 기존 `export_revision`을 계속 모든 로컬 실행에 사용하면 Capture의 중복은 사라져도 로컬 Package의 모델 사본은 남는다. 이것을 ‘외부 Export에서만 bundle’의 전체 완료라고 보고하면 안 된다.

현재 `scene_contract.package._relative/_path`는 `..`·외부 파일을 거부하고 `package_asset`은 manifest 소유 파일만 읽는다. Isaac에는 `package.root/path` 직접 접근도 있으며, 실행 URDF·physics-enabled USD를 따로 검증한다. MuJoCo도 명시 native MJCF 또는 URDF-derived compilation을 사용한다. Pinocchio는 URDF 경로와 byte SHA를 받아 joint order/solver identity를 검증한다. [Package 경계](../../scene_contract/src/scene_contract/package.py#L38), [model resolver](../../robot_learning_workbench/src/robot_learning_workbench/robot/calibration.py#L481), [MuJoCo binding](../../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/model.py#L213), [Isaac binding](../../robot_learning_workbench/src/robot_learning_workbench/engines/isaac/env_cfg.py#L82), [Pinocchio binding](../../robot_learning_workbench/src/robot_learning_workbench/generation/mimic.py#L269)

전체 목표까지 구현할 때는 **기존 Package 모듈 안에 명시적인 로컬 자원 참조 계약과 검증 context를 추가**해야 한다. Portable `/1` Package의 containment 규칙을 전역으로 풀지 않는다. 로컬 전용 schema/version에서 logical asset reference와 resource ID/closure를 선언하고, 준비 단계가 명시 Workspace에서 검증한 immutable resolution을 제공한다. 기존 `package_asset`·엔진 binding은 그 resolution을 사용하게 하고 직접 `root/path` 소비자도 같은 경계로 바꾼다. Portable Package에는 local resolution이 필요 없고 여전히 자기 root만으로 읽혀야 한다.

Runtime에 필요한 MJCF/USD layer 등은 공용 모델을 source로 한 파생 cache 또는 실행 전용 임시 layer로 관리한다. 모델 원본을 고치거나 매 Capture마다 다시 생성하지 않는다. 컴파일 identity에는 resource closure·converter·옵션을 넣어 다른 컴퓨터의 절대 경로가 바뀌었다고 다른 물리 모델이 되거나, 다른 Mesh를 같은 identity로 취급하지 않도록 한다. 이 부분은 Source/Annotation/DataGen/Policy의 model identity와 함께 회귀해야 한다.

## 7. 외부 Export·오프라인 재배치

외부로 내보낼 때 기존 `export.copy_native_asset`의 closure 검증/원자적 게시를 재사용하되, 입력은 과거 Export 안의 모델이 아니라 공용 자원 manifest에서 해결한다. URDF 상대 참조는 보존하거나 명시 파생 URI rewrite와 provenance를 기록한다. Workspace 경로·symlink·절대 모델 경로를 외부 manifest에 남겨서는 안 된다. [Native closure 복사](../../real2sim_builder/src/real2sim_builder/export.py#L89), [닫힌 Package 검증·게시](../../real2sim_builder/src/real2sim_builder/export.py#L425)

단일 Capture bundle은 자체 모델 closure를 포함할 수 있다. 여러 Capture를 한 번에 내보내면 bundle의 공용 `resources/robots/<ID>/<Revision>`를 한 번 포함하고 개별 Capture는 bundle manifest가 선언한 그 자원을 참조하게 한다. 이때 `../..`로 임의 밖을 읽는 reader를 추가하는 대신, 명시 archive context 안에서만 같은 ID/Revision/SHA를 해석한다. 원본 Capture manifest는 그대로 보존하고 새 bundle manifest가 원본 Capture SHA와 embedded resolution을 연결한다. 원본 Capture의 ID/측정 q를 Export 때문에 재작성하지 않는다.

검증은 Workspace/환경변수/네트워크 없이 별도 위치에 복사한 bundle을 실제 reader로 여는 시험이다. 누락 dependency·잘못된 closure·변경된 Mesh·상대 경로 escape는 실패해야 한다. Offline 성공이 로봇 물리·센서 Calibration 성공을 의미하지는 않는다.

## 8. 기존 자료 보존과 단계별 구현

기존 embedded `/1` Capture·URDF·Rig·보정·ScenePackage는 해당 reader와 bytes를 유지한다. 기존 이름을 자동 검색해 새 위치로 연결하는 runtime converter/alias/symlink는 추가하지 않는다. 신규 Writer만 새 자원 계약을 사용한다. 과거 모델 폴더를 제거하며 참조형으로 바꾸는 작업은 별도 사용자 지시·원본 ledger·복구 가능한 일회성 마이그레이션이 필요하며 이번 계획에 포함하지 않는다.

| 단계 | 최소 구현 범위 / 기존 소유 위치 | 필수 시험·완료 판정 |
|---|---|---|
| A. 공용 등록·해석 | `evidence`의 Robot 검증, `export`의 closure 조사, 기존 Asset lock/원자적 게시 패턴 | 같은 입력 반복/동시 등록의 payload 수 불변. URDF가 같아도 Mesh 변경 시 다른 closure. traversal·symlink·누락·등록 중 변경 거부 |
| B. UI/Device/Precision 선택 | `scene_preparation`, `registration`, `recipe`, `calibration` | UI→저장→재열기→PreparedRun에서 같은 ID/Revision/URDF/closure. 두 Project 공유 변경의 영향 명시. 구형 Device/Calibration bytes 불변 |
| C. 참조형 Capture | `SnapshotStore`, 기존 Builder Capture reader/import | 실제 Writer→Reader→Evidence integration. 1/10/100 Shot에서 공용 모델 payload·file 수 불변, 각 Shot `model/` 없음. q/Mapping·시간·PNG SHA·Pair 보존. 원자적 실패/중복ID/Stop·재개 확인 |
| D. 참조형 Builder Scene | `scene.local_path`, `evidence.import_robot_rig`, 기존 FK/렌더 소비자 | 두 Scene이 동일 공용 모델을 쓰고 새 Robot closure 사본을 생성하지 않음. Robot-only namespace escape 거부. 기존 Object Library 경계 보존 |
| E. 로컬 엔진 binding | `scene_contract.package`, `calibration.execution_urdf/package_asset`, MuJoCo/Isaac 기존 입력 준비 | Producer→local Scene→MuJoCo/Isaac input 해석→Pinocchio가 같은 URDF/closure 사용. 다른 모델·baked Calibration·메모리 Replay identity 충돌 거부. 엔진별 실제 실행은 각 별도 허용 범위에서 보고 |
| F. 외부 bundle | 기존 `export`와 Capture import/export 경계 | 여러 Capture의 모델 payload 한 번 포함. 별도 root·Workspace 없음·오프라인 reader 성공. 원본 Capture/Package SHA 불변, resource 누락 시 export 실패 |
| G. 기존 회귀·수명 | 기존 Stage/Capture/Device/Policy/Native Package 시험 | `/1` 읽기·기존 Package relocation·실측 보호·Dataset lineage·실행 종료 진단 보존. 새 자원 정리 시 참조 중 Revision 삭제 거부 |

성능 완료 기준은 임의의 ‘몇 초 이하’만으로 정하지 않는다. 같은 입력·동일 디스크의 기준 실행과 비교해 등록/초기 준비와 Shot 저장을 따로 측정하고, **Capture 증가에 비례해 모델 순회·hash·hardlink·파일 수가 늘지 않는지**를 검증한다. 이미지 encoding·실제 paired Sim render·원자적 fsync·Evidence 갱신은 별도 시간으로 기록한다. Capture 저장이 느린 다른 원인을 공용 모델 전환만으로 해결됐다고 보고하지 않는다.

이번 조사에서 바뀐 것은 이 계획 문서와 영향 JSON뿐이다. 위 A–G 구현, 공용 모델 실등록, 기존 Capture 정리, 로컬 엔진 참조 전환, 외부 bundle 이식 검증은 **미실행**이다.
