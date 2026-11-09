# 읽기 쉬운 저장 구조와 기존 데이터 이전

2026-11-08. 원래 `/home/hyeonhee/imitation_learnig_project`에서 실제 파일을 이전했다. 브랜치 `review/real2sim-multiview-20261106`, HEAD `9384a09e86196d98f107992d1352aaac1dc3a8b8`는 유지했다. Commit/Push/Merge·새 Worktree/Workspace/실제 Scene 생성·장치 구동·SDK Calibration 재실행은 하지 않았다. 아래 결과는 저장 구조 검증이며 실제 사진 복원 품질/물리 인증을 뜻하지 않는다.

## 변경된 실제 구조

```text
workbench_runs/
├── scenes/
│   ├── auto-version/                     # ID는 auto-version-ba737533 그대로
│   │   ├── input/
│   │   │   ├── scene_memo.txt
│   │   │   ├── scene_photos/scene_img1.jpg … scene_img8.jpg
│   │   │   ├── model_references/wrist_camera_img1.jpg … img2.jpg
│   │   │   └── captures/
│   │   │       ├── session_20261107_01/capture_001/ … capture_003/
│   │   │       └── session_20261107_02/capture_001/
│   │   └── scratch/agent/auto_mast3r_colmap/
│   │       ├── candidate_scene.yaml
│   │       ├── .cache/inference/           # SHA 기반 SAM/SfM/RGB/Cloud 캐시
│   │       ├── .cache/modeling/            # Crop·가시 점군 파생 자료
│   │       ├── modeling/codex/request_001/ …
│   │       └── blender/objects/build_001/
│   └── pickplace-colorblock/             # ID는 pickplace-colorblock-b7a5592b 그대로
├── devices/so101-pickplace/
├── object_assets/<asset_id>/v001/
├── calibration/sessions/
│   ├── precision_20261030_01/ … precision_20261030_04/
│   └── precision_20261030_01.yaml … precision_20261030_04.yaml
├── source/demo-retry1/ … demo-retry8/
└── curation/source/demo-retry6/ …
```

Capture 폴더에는 Side/Wrist PNG·state·metadata·capture_manifest와 완료 마커, 보관 Robot 의존 파일이 있다. 단일 Shot의 중첩 `shots/<UUID>`는 평탄화했고 원래 두 완료 마커가 있으면 `snapshot.COMPLETE`로 구분해 보존했다. 여러 장면 상태가 있는 과거 묶음은 `snapshots/snapshot_000001` 등의 기존 순차 구조를 유지한다. 배치를 합치거나 q/시간을 재계산하지 않았다. 실패한 Pending Capture도 별도로 남긴다.

새 Scene/장치 설정 폴더는 표시 이름을 정리한 이름을 사용하며 충돌은 `-2`, `-3`이다. 사진은 원본 이름, 같은 이름의 다른 내용은 `_2`, `_3`을 사용하고 같은 내용은 재사용한다. 내부 Project/Object/Image/Session Identity와 디스크 이름은 독립적이다. 새 Capture/Precision/실행 출력/모델링 Job은 날짜·순번이다. 임시 원자적 파일과 내부 IPC/Command ID는 계속 UUID를 사용한다.

## 코드 소유권

| 범위 | 실제 수정 위치 |
|---|---|
| 공통 이름/충돌/내용 중복·마이그레이션 잠금 | `scene_contract/naming.py`: `available_path`, `reserve_directory`, `numbered_path`, `copy_named`, `check_storage_available` |
| Scene 생성·내부 ID 분리 | `real2sim_builder/project.py`: `Project.create` |
| 원본 이름·Evidence 역할 | `evidence.copy_input/add_image`, `observations.register_image/input_images`, Workbench `scene_preparation.save_inputs/scene_details` |
| 입력 UI/실제 저장 전달 | `ui/scene_inputs.py`: Scene/Model 이미지 다중 선택·기타 자료 버튼·역할 그룹, 기존 `session_materials` 경로 |
| 장치/Precision | `robot/registration.save_configuration`, `robot/precision_storage.save_profile`, `ui/device_setup.py`, `ui/precision_page.py` |
| Capture/재열기 | `robot/snapshots.SnapshotStore`, Builder `capture._capture_destination/load_snapshots`, `ui/session_operations.saved_snapshots` |
| 자산 버전·재사용·검증 | `object_assets.register_object_asset/asset_manifests/verify_object_asset`, `scene.local_path` |
| Codex/Blender/정합 | `authoring`, `automation`, `rendering`, `calibration/joint.py`, `hybrid.py`: 순차 Job/Checkpoint·숨긴 Cache |
| Geometry 입력 역할 | `sfm.run_geometry/lens_group`, `inference.run_models`: 초기 복원과 Sensor/Pair 입력 구분 |
| Native Export/일반 출력 | `export.copy_native_asset`, `ui/paths.py`, `source_settings.py`, `pipeline_scripts.py`, `curation.py`, `data/revisions.py` |
| 미래 작업 지침 | `AGENTS.md`, `CODEX_SCENE_GUIDE.md`, 제작/규칙/자동 정합 MD |

새 Framework/Manager/영구 Converter/구형 Reader·Alias·Symlink는 없다. `naming.py`는 정상 저장 시 사용하는 작은 공통 경로 함수이며 구형 경로를 탐색하거나 변환하지 않는다. 데이터 이전 프로그램은 저장소 밖 복구 영역에만 있다.

## SHA/UUID 용도 분리

전수 검색의 생성·참조 지점은 외부 백업의 `identifier-audit.json`(105개)에 파일/행과 함께 남겼다.

- **사용자 경로:** Project UUID 접미사, 원본 사진의 SHA 이름, Device 접미사, Session/Precision UUID, Asset SHA 버전, Job UUID는 읽기 쉬운 이름/순번으로 교체했다.
- **내부 ID:** Project/Image/Object/Session·Command·Dataset ID는 논리 동일성을 위해 보존하거나 별도 생성한다. 파일명과 같다고 가정하지 않는다.
- **무결성:** RGB/모델/Mapping/Snapshot/Package SHA·Manifest 검사를 유지한다. 바뀐 경로 메타데이터의 파일 SHA와 참조는 새 값으로 전파했다.
- **Cache:** SAM/SfM/RGB/점군 Fingerprint는 `.cache` 안에 보존한다. 경로/소스/역할이 바뀌어 Cache Identity가 달라지면 이전 결과를 같은 결과로 속여 사용하지 않는다.
- **자산/Calibration 이력:** Asset `version`은 `v001` 등이고 `content_sha256`는 별도다. 같은 생성 요청이 아닌 동일 내용도 재사용할 수 있다. 새 요청의 완료 근거는 기존 Candidate Job 기록에서 별도로 확인한다. Precision은 내용 SHA/Parent 연결을 유지하며 새 History는 순차 이름을 쓴다.
- **원자적 저장:** `.building`, `.tmp`, `.workbench-runs`·IPC 등의 내부 식별은 안전을 위해 유지한다.

## 이미지 역할과 Camera Identity

Scene Prepare에는 `＋ Scene 이미지 추가`, `＋ Model 이미지 추가`, `기타 자료 추가`가 있다. 처음 두 버튼은 여러 이미지를 선택하고 `role: scene_photo` / `model_reference`를 저장한다. 기타 자료는 기존 URDF/USD/OBJ/STL·영상·문서·측정 경로를 유지한다.

Scene 사진만 초기 Scene SfM에 사용한다. Model 사진은 Codex 분석 및 Blender 모델링 참고 자료로 전달하고 SAM/SfM/정합 Loss에는 넣지 않는다. Side/Wrist Capture는 측정 q를 갖는 Sensor/Real-Sim 관측으로 보존하며 초기 Scene SfM에 섞지 않는다. 기존 Pair 재정합 호출에서는 Sensor Geometry 실행을 허용한다. 별도 Camera/Scale Solver를 만들지 않았다.

`auto-version`의 Scene 사진 8장, Model 사진 2장을 저장된 원본 이름으로 구분했다. Capture 배치와 사진 배치의 ID를 합치지 않았다. 초기 실행 설정의 배치는 `photos_159bdef6114e`로 선택했다. 기존 Candidate/이전 Capture 기반 실행 보고서·자산은 보존한다. `pickplace-colorblock`의 기존 Capture를 이름만 보고 일반 사진으로 재분류하지 않았다.

미확인 휴대폰 렌즈는 `physical_camera_id: null`과 별도 `external_view_번호` 관측 Binding을 사용한다. 기존 Image ID는 보존한다. COLMAP은 명시 물리 렌즈 ID가 없으면 View마다 K를 분리하고, 실제로 동일한 렌즈임이 선언된 경우에만 해상도/EXIF/crop 조건과 함께 공유한다. 사진 SHA를 렌즈 Identity로 사용하지 않는다.

## 이전 절차와 보존 근거

기존 외부 백업 `/home/hyeonhee/real2sim-integration-backups/local-20261108-173502/storage-migration/`에 전체 Workspace 사본과 원래 미커밋 소스 사본·diff를 보존했다. 기존 Runtime 환경/가중치도 백업의 일부지만 제품은 백업을 읽지 않는다. 디스크 여유를 확인하고 기존 파일을 덮어쓰기 전에 SHA 목록을 만들었다.

- 전체 Inventory: **28,021개 항목 / 일반 파일 23,297개 / 기존 Symlink 6개**.
- JSON/YAML을 실제 구조로 파싱하고 참조 관계 **63,828개**를 조사했다. 이름 매핑 **246개**, 실제 영향 항목 **7,163개**. Dry-run 목적지 충돌 0, 미해결 경로 기준점 0.
- 백업 28,021개 항목 대조 오류 0. 별도 임시 Workspace/Scene에서 성공을 대신하지 않았다.
- 원래 위치를 원자적 단위로 잠근 뒤 Rename/Move했다. 중간 상태에는 `.storage-migration-in-progress`로 일반 UI/Project 진입을 막았으며 검증 후 해제했다.
- 메타데이터 818개의 경로를 다시 작성하고 실제 bytes에 따른 Manifest SHA를 의존 순서대로 전파했다. 객체 Manifest의 Project 상대 자기 참조와 중간 SHA가 남은 참조도 실제 소비자로 확인해 바로잡았다. Curation Parent Identity 6건을 변경된 메타데이터에 맞춰 갱신했다. 이것을 새 승인·물리 검증으로 표시하지 않는다.
- 최종 원본 파일 **22,475개 SHA 불변**, **822개는 경로/Manifest/설정 등 메타데이터 변경**, 누락 0. 이미지·영상·HDF5·USD/URDF/OBJ·가중치 등 비메타데이터 원본 변경 0. 새 Symlink 0. 불변 Package 파일 변경 0.

완료 마커가 없는 과거 Snapshot 자료 30건은 이전 전후 같은 `Incomplete snapshot dataset`이다. 새로 성공으로 승격하거나 지우지 않았다. 정상 자료의 신규 읽기 실패는 0이다. 빈 옛 `input/media` 디렉터리 하나만 비었음을 확인한 뒤 제거했다.

일회성 도구와 경로 매핑·이동 Journal은 위 외부 백업의 `inventory.py`, `graph.py`, `plan.py`, `prepare.py`, `apply.py`, `finalize.py`, `refresh_integrity.py`, `verify_final.py`다. 제품 소스에서 호출하거나 import하지 않는다. 복구가 필요하면 모든 Worker/UI를 먼저 종료하고 데이터 사본과 대응 소스를 함께 복원해야 한다. 현재 Runtime에 이전 경로를 연결해 두지 않았다.

## 실제 소비 기능 검증

| 항목 | 확인 결과 |
|---|---|
| 두 Project | 새 경로로 로드, 기존 내부 ID 유지 |
| 사진 | Scene 8장·Model 2장 원본 내용 SHA 유지, 메모 원문 SHA 유지 |
| Snapshot 목록 | `auto-version` 4개, `pickplace-colorblock` 16개. 여러 배치 묶음도 각 배치를 따로 읽어 표시, 오류 0 |
| Capture 내용 | 측정 q·Timestamp·Mapping과 Side/Wrist 대응이 이전 전후 동일 |
| Precision | 실제 Session 4개와 대응 **YAML Recipe 4개**, 각 `precision-report.json` 유지. 원 Inventory에 Calibration XML은 **0개**였다. XML을 임의 생성하거나 YAML을 XML이라고 보고하지 않음 |
| SDK/프로필 | Follower/Leader 실제 Precision Profile 로드 통과. USB Serial/SDK ID/실제 Calibration 파일 이름·Encoder 수치 보존 |
| 자산 | 공용 9개 `v001`, Closure/SHA 엄격 검증 통과. 기존 Candidate에서 9개 모두 `ASSET_IDENTITY_REUSE`, 재제작 없음 |
| Candidate | `auto_mast3r_colmap`은 OPEN, Signature 파일 317개 확인. 과거 미완성 정합 상태는 그대로 보존 |
| Package | 발행된 15개 Package 검증 통과, 내부 bytes 불변. `pickplace-colorblock` Source는 기존 `scene-v9-task-objects`를 새 Project 경로에서 선택 |
| Dataset | Native Dataset 20개 로드 통과, Dataset ID·Episode ID/개수·Frame 수 불변. Curation Parent 갱신 후 모든 저장 Revision 로드 통과 |
| UI | 원래 Workbench Window/QProcess로 Project 선택·두 이미지 버튼·동일 자료 저장·메모/Evidence SHA 불변·Snapshot 표시·Auto Reconstruction 열기 확인. 파일 대화상자만 자동화 |
| Scene/Task 실행 경계 | 전체 회귀의 실제 MuJoCo/Blender와 Memory 장치 시험으로 기존 Pair/Source/Export/학습·Curation 경로 검사. 실물 모터·SDK 재보정 없음 |

## 이름을 유지한 항목과 한계

발행된 Package 내부의 해시 기반 파일명과 원래 `authored_scene`/provenance는 Manifest·과거 Dataset/Pair의 Scene Identity에 포함돼 있어 바꾸지 않았다. Project 폴더만 옮겨도 Package가 자체 상대경로로 검증되므로 이 이름 변경만을 위해 새 Scene Identity를 발명하지 않았다. 기존 Dataset/Pair가 참조하는 승인 이력을 보존한다. 새 Export는 새 저장 코드를 사용한다. Package 내부 옛 절대경로가 provenance 문장에 남아 있어도 현재 실행은 등록된 새 Project 경로와 Package 자체 파일을 사용한다.

날짜별 과거 실험 폴더는 이미 목적/날짜가 읽히고 외부 보고서에서 참조되므로 이력을 하나로 합치거나 무조건 재명명하지 않았다. 그 안에서 실제 연결된 자산/입력 참조는 조사·이전했다. 출처가 불명확한 파일은 이름으로 역할을 추측하지 않는다. 과거 로그의 문자열과 독립 백업에는 당시 경로가 남는다. 이는 Runtime Converter나 Alias가 아니다.

내부 ID·숨긴 캐시 Hash·임시/Worker 파일에는 필요한 기술 식별자가 남는다. 모든 SHA/UUID 문자열을 없앴다는 주장이 아니다. 예전 실제 Scene Reconstruction의 Metric/Mount 미해결 상태도 이번 저장 이전으로 해결됐다고 표시하지 않는다. 새 실사진 복원·Codex 모델 추론·Isaac/PhysX 전체 Scene 재실행·실물 동작은 이번 저장 검증에서 새로 수행하지 않았다.

## 현재 실행

```bash
cd /home/hyeonhee/imitation_learnig_project
./run_workbench_ui.sh
```

Scene Prepare에서 기존 표시 이름 `auto_version` 또는 `pickplace_colorblock`을 선택한다. 데이터는 새 폴더에서 열린다. 새 입력은 Scene/Model 버튼으로 구분하고, 장치/Precision 파일은 새 경로를 선택한다. 새로 촬영하거나 기존 메모를 다시 작성할 필요는 없다. Worktree를 바꿔 실행하지 않는다.

## 최종 회귀·검사 결과

원래 프로젝트에서 다음 세 패키지 전체를 실행했다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short --junitxml=<외부 백업>/release-suite.xml
```

**1,600 passed / failed 0 / errors 0 / skipped 0**, 395.96초, 기존 torchvision 경고 4개다. 이전 작업의 1,591개 통과를 이번 결과로 대신하지 않았다. 중간 101개 실패는 UI 문법·격리 Blender import·옛 이름/계층 기대값 등으로 분류했고, 이후 남은 4개 옛 경로 기대값도 새 실제 구조에 맞춰 수정했다. 같은 기능의 q/Pair/학습 Task·Episode 수 검증은 유지했으며 skip/xfail이나 검사 완화로 통과시키지 않았다.

새 이름/내용 중복, Asset v001/v002와 같은 내용 재사용, Scene/Model 역할·모델링 전달·SfM 제외, 미확인 렌즈 K 분리, 여러 배치 Snapshot 표시를 회귀로 추가했다. 현재 Source/Pair 관련 통합 시험은 실제 MuJoCo와 Memory 장치이며 실물 구동이 아니다. 기존 실제 Candidate의 9개 자산 재사용 및 Snapshot 4/16개, 두 UI 버튼→실제 Backend 저장 왕복은 별도로 확인했다.

최종 근거는 외부 백업의 `release-suite.xml/log`, `preservation-final.json`, `actual-data-validation.json`, `ui-verification.json`, `ui-save-verification.json`, `audit-before.json`, `audit-after.json`, `path-plan.json`, `rewrite-plan.json`이다. 최초 실패·중간 수정 로그와 이동 Journal도 보존했다. 테스트/도구가 원본을 삭제하거나 새 물리 검증 상태를 만들지 않았다.
