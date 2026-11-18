# Workspace 파일 생성·참조·폴더 수명 조사

2026-11-17. `feat/simfoundry-style-reconstruction`의 현재 작업 트리를 읽었다. 이 문서는 정리 전 저장 구조 조사 결과다. **후속 구현·실제 삭제·보존 검증은 [작업 결과](workspace-storage-capture-ui-fix.md)를 따른다.** 아래 삭제 후보·용량을 현재 모두 남아 있는 자료라고 해석하지 않는다. 외부 프로젝트 체크아웃·인증 파일·모델 Forward·장치는 조사에 사용하지 않았다.

조사 근거는 Git 제외 `workbench_runs/diagnostics/workspace_storage_capture_ui_20261117_001/storage-audit.json`이다. 전체 Workspace의 stat를 읽고, 지정된 제품 저장 root의 JSON/YAML **1,463개**를 파싱했다. 과거 출처 문자열도 참조로 나타날 수 있으므로 기존 경로가 존재하는 것과 실제 실행에서 읽는 것을 구분했다. 아래 용량은 논리 bytes이며 hardlink가 있는 파일은 경로마다 합산됐다. 안전하게 회수할 수 있는 물리 공간의 측정이 아니다.

## 최상위 폴더의 의미

| 폴더 | 생성자와 역할 | 조사 시 논리 크기 | 정리 판단 |
|---|---|---:|---|
| `scenes/` | Scene Prepare가 소유하는 Project, 입력·Candidate·발행 Package | 7.052GiB / 7,710개 파일 | 실제 UI의 기준. 통째 삭제 대상 아님 |
| `object_assets/` | 공용 Object Library의 불변 USDA/Texture/Collision Version | 11.5MiB / 239개 | Asset 원본. 보존 |
| `robot_rigs/` | 선택할 로봇+Camera 조립 URDF와 고정 dependency | 24.8MiB / 46개 | 로봇 원본. 보존 |
| `devices/` | USB 역할·SDK/Precision·Camera stream 선택 | 약0.09MiB / 10개 | 현재 3개 Project가 공유. 보존 |
| `runtime/` | `reconstruction.yaml`과 실제 Qt Python 설치 | 0.775GiB / 10,561개 | `qt/bin/python3.11`을 UI launcher가 실제 사용. 부산물로 지우면 UI 실행이 깨짐 |
| `.assets/` | 이전 과정에서 Workspace가 소유한 SHA별 파일을 저장하고 Scene에 hardlink한 pool | 0.269GiB / 663개 | 이름만 보고 Cache로 삭제하지 말 것. 소유권·hardlink 범위 확인이 필요 |
| `capture/`, `real_sim/` | 연결할 때 쓴 Recipe YAML, R03 실행·종료 기록, 과거 Capture 결과 | 0.148GiB / 768개, 0.188GiB / 857개 | UI 실행 기록과 실제 측정 자료가 섞임. 전체를 test output으로 분류하지 않음 |
| `calibration/` | Precision 세션·이전 Profile history·보정 근거 | 23.4MiB / 90개 | 실측/보정 이력. 보존 |
| `source/`, `curation/` | Native 데모 Dataset과 원본 선택 Revision | 27.6MiB / 396개, 약6.4KiB / 7개 | Curation은 선택 JSON만 기록. 사용자 Dataset 보존 |
| `annotation/`, `datagen/`, `dataset/`, `policy/`, `evaluation/` | 각 Pipeline의 이름별 출력 pool | 현재 비어 있음 | 코드가 쓰는 표준 목적지. 빈 디렉터리를 임의 다른 용도로 합칠 이유 없음 |
| `scripts/` | 사용자가 저장한 Pipeline 설정/Script | 약2.5KiB / 4개 | 설정 입력. 보존 |
| `.review/` | Curation 영상 전달용 임시 PPM/JSON | 약3.52MiB / 6개 | 정상 Reader 종료 시 삭제되는 임시 자료. 11월2일 잔여 폴더는 활성 Reader 확인 후 정리 후보 |
| `diagnostics/` | 개발 진단·테스트·모델 검증·보존 ledger | 조사 시작 약0.623GiB | 제품 실행 자료와 다르지만 보고서의 근거가 있음. 당시 결과의 보존/폐기 정책을 적용할 영역 |
| 날짜가 붙은 `scene_*`, `real_codex_flow_*`, `sfm_comparison_*` 등 | 이전 기능 개발·비교·독립 실험 | 아래 표 | 현재 UI의 표준 저장 pool과 분리되는 과거 실험. 각 경로의 참조·자산 독립성을 확인한 뒤 제거 가능 여부 판정 |

근거: [UI launcher](../../run_workbench_ui.sh#L5), [Workspace 소유 Asset pool](../../robot_learning_workbench/src/robot_learning_workbench/scene_migration.py#L9), [Pipeline 목적지](../../robot_learning_workbench/src/robot_learning_workbench/ui/paths.py#L7), [Curation preview 정리](../../robot_learning_workbench/src/robot_learning_workbench/ui/review_client.py#L63).

## Scene 폴더 안의 7개 항목

사용자 화면의 `configuration`, `exports`, `input`, `scratch`, `working`, `history.jsonl`, `project.yaml`은 각각 다른 수명과 소비자를 가진다.

| 항목 | 만들어지는 때 / 연결되어 사용되는 곳 | 유지할 것과 개선점 |
|---|---|---|
| `project.yaml` | Scene 생성 시 ID·이름을 기록. Device/Rig 선택과 등록 실행 Package 목록을 추가 | Scene 디렉터리 이름만으로 ID를 결정하지 않음. 핵심 참조이므로 보존 |
| `input/` | Photo/Reference/Memo를 저장하고 Capture를 추가. Evidence가 역할·SHA·촬영 상태를 연결 | 원본 관측. `scene_photos`, `model_references`, `captures`, `observations`는 서로 다른 역할 |
| `working/` | 편집 Current, 소유권·상태·lock·최근 import 보고서 | 현재 상태와 동시 실행 방어. lock은 단순 쓰레기 파일이 아님 |
| `scratch/agent/<Candidate>/` | Reconstruction/Refit를 시작하면 Candidate·attempt·분석·Mesh·Cache·Evidence를 저장 | 진행 재개·제작 기록·채택 전 작업. ‘scratch’라는 이름만으로 전부 삭제하면 안 됨. 임시 엔진 파생물과 보존 Evidence를 나누는 개선 여지가 큼 |
| `exports/<Revision>/` | 닫힌 USD/MJCF/Native Package를 발행 | 과거 실행이 재현되도록 고정. UI는 등록된 Package를 명시 선택하므로 Current를 바꿔도 과거 Package는 바뀌지 않음 |
| `configuration/` | Export 등록 시 엔진별 설정 경로 생성 또는 사용자가 명시한 설정 저장 | 현재 Package가 참조한 파일과 미등록 자동 wrapper를 구분할 수 있음 |
| `history.jsonl` | Scene 작업 이력을 추가 기록 | 사용자 원본·채택 이력. 삭제하면 역추적 근거를 잃음 |

근거: [Project 생성](../../real2sim_builder/src/real2sim_builder/project.py#L94), [Candidate 생성](../../real2sim_builder/src/real2sim_builder/candidate.py#L45), [Export 등록](../../real2sim_builder/src/real2sim_builder/registration.py#L8), [실행 Package 선택](../../robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py#L124).

현재 `auto-version`은 약4,675MiB 중 `scratch`가 약4,377.5MiB다. 그 안의 기존 `auto_mast3r_colmap` Candidate는 `evidence` 약2,204MiB, `diagnostics` 약1,006MiB, `fitting` 약675.8MiB, `modeling` 약321.2MiB, `.cache` 약162MiB를 가진다. 이것들은 AI 모델 가중치가 아니라 생성된 비교·렌더·작업 근거가 대부분인 영역이다. 그러나 Evidence index·Cache manifest·현재 Candidate가 참조하므로 생산자/소비자 관계를 끊은 뒤 정리해야 한다.

`pickplace-colorblock`은 약2,394.4MiB 중 `exports` 약1,788.8MiB, `input` 약499.6MiB다. 10개 Export 폴더 중 7개가 현재 등록돼 있다. 미등록이라고 즉시 삭제할 수 있는 것은 아니다. 오래된 Capture의 Scene identity나 보정 이력에서 쓸 수 있으므로, 등록 여부와 측정 자료의 참조를 함께 봐야 한다.

## Capture 한 번에 무엇이 생기는가

Scene Prepare 연결은 `capture/session_<날짜>_<순번>.yaml`, Real/Sim 연결은 `real_sim/real_sim_<날짜>_<순번>.yaml`을 먼저 만든다. YAML은 선택된 Project·Device/엔진 입력과 실행 출력 경로를 고정한다. [Scene Prepare 연결](../../robot_learning_workbench/src/robot_learning_workbench/ui/session_page.py#L157), [Real/Sim 연결](../../robot_learning_workbench/src/robot_learning_workbench/ui/real_sim_page.py#L135)

R03는 출력 옆 `.workbench-runs/<run_id>/`에 `run.json`, `worker_request.json`, event index/log, command/ack, process exit를 저장한다. 출력 경로를 중복 사용하지 못하도록 `.workbench-output-<hash>.json/.lock`을 만든다. 이 파일은 UI 상태 조회·중단·중복 시작 방어·종료 진단에 쓰인다. Capture 버튼을 누를 때마다 새 전체 엔진 환경을 설치하는 파일은 아니다. Preview는 Camera별 **두 PPM slot을 덮어쓰며 재사용**하고 정상 종료 때 삭제한다. 매 frame 파일을 무한 생성하는 방식이 아니다. [R03 시작·reservation](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L171), [Preview 재사용·정리](../../robot_learning_workbench/src/robot_learning_workbench/run.py#L575)

모델·Precision에 결합된 Capture는 다음과 같다.

```text
scenes/<Scene>/input/captures/<Session>/capture_001/
  capture_manifest.yaml
  state.json                 # 당시 measured q/시간/장치 정보
  metadata.json              # 이미지·파일 SHA·품질
  side.png, wrist.png         # 실제 센서 RGB
  pair.json, sim_*.png        # Real/Sim인 경우 추가
  model/...                  # 당시 URDF와 dependency
  COMPLETE
```

새 Snapshot 코드는 이미 한 장의 `shots/<UUID>` 계층을 만들지 않고 Capture root에 이미지와 state를 저장한다. 저장 중에는 `pending_<id>`로 쓰고 검증 뒤 `capture_NNN`으로 rename한다. Scene 안에 이미 저장한 Capture를 Evidence에 등록할 때는 in-place 경로를 사용해 전체 폴더를 다시 복사하지 않는다. [Snapshot 생성·완료](../../robot_learning_workbench/src/robot_learning_workbench/robot/snapshots.py#L17), [in-place import](../../real2sim_builder/src/real2sim_builder/capture.py#L195)

`model/`은 `os.link`로 기존 URDF/Mesh를 공유한다. 각 Capture에 파일 이름이 여러 번 보여도 별도 모델 제작/전체 bytes 복제라고 볼 수 없다. 다만 file SHA는 매 Capture 검증에서 재확인할 수 있으며, 하드링크는 쓰기 방지나 Copy-on-write가 아니다. [모델 closure 공유](../../robot_learning_workbench/src/robot_learning_workbench/robot/capture.py#L303)

모델·Precision이 아직 없는 관측 전용 Scene Prepare는 `input/observations/<Session>/<Observation>/`에 RGB와 `observation.json`을 만든다. q가 없으면 없는 상태로 보존하고 정합용 Capture라고 꾸미지 않는다. 이 형식에 URDF를 넣기 위해 임의 모델을 생성하지 않는다. [관측 전용 저장](../../robot_learning_workbench/src/robot_learning_workbench/robot/scene_observation.py#L69)

## 중복·폴더 깊이에서 실제로 확인한 부분

1. **오래된 native closure의 중첩.** Workspace에서 가장 깊은 파일 경로는 21단계였다. `copy_native_asset`은 URDF/USD 상대 dependency를 보존하고 하나의 Export 안에서 이미 복사한 파일을 재사용한다. 이미 Export 안에 들어간 자산을 다음 Export의 원본으로 삼으면 `assets/.../exports/.../assets/...`가 다시 들어갈 수 있다. 새 출력의 기준을 공용 Rig/Library의 정돈된 closure로 맞추면 줄일 수 있다. 이미 게시한 Package의 폴더만 flatten하면 URDF/USD 상대 참조·SHA·Calibration identity가 깨질 수 있으므로 원본을 일괄 재작성하면 안 된다. [복사 layout](../../real2sim_builder/src/real2sim_builder/export.py#L89)
2. **등록되지 않은 자동 엔진 wrapper.** `pickplace-colorblock/configuration`에 현재 `execution_packages`가 참조하지 않는 `export-<sha>-{isaac,mujoco}.json` **18개, 합558B**가 있다. 내용은 모두 `{"render_type":"authored"}`다. 생성자는 Export 등록 함수다. 다른 저장 Recipe가 참조하는지 확인하면 불필요 파일을 판정할 수 있다. 나머지 미등록 named 설정6개는 내용과 사용 의도를 확인하지 않고 버리지 않는다.
3. **역사적 진단·독립 실험이 Workspace root에 섞여 있다.** 날짜별 실험20개는 현 제품 소스에 exact path 문자열 참조가 없고 과거 보고서가 연결한다. 일부에는 생성 Mesh/독립 Project·사용자 입력 사본도 있다. UI의 현재 Project 자료와 분리된 실험이라는 사실만으로 유일한 자산/관측이 없다고 보장하지 않는다. 현행 Project의 소유 closure가 완전하고 남길 원본이 별도로 있는지 확인 후 폐기할 수 있다.
4. **비정상 종료 후 Preview 잔여.** `.review`의 11월2일 잔여물은 정상 종료 정리 계약의 임시 출력이다. Reader가 사용 중이지 않다면 보관할 사용자 원본이 아니다.
5. **이미 잘 공유하는 부분도 있다.** Curation은 원본 선택 metadata만 저장한다. Native Resume·영상은 하드링크 재사용 경계가 있다. Preview는 slot을 재사용한다. 이들을 더 복잡한 전역 자산 Manager로 바꿀 필요는 없다.

## 과거 실험 폴더 목록

아래 목록은 **정리 검토 목록**이며 이 문서 작성자가 삭제한 목록이 아니다. 현 제품 소스에서 exact `workbench_runs/<폴더>` 참조는 0개였고, 대다수는 과거 문서가 연결한다. `scene_autofit`의 `fit_provenance.source_context`는 현재 Candidate의 역사 출처에도 남는다. `sfm_comparison`의 문자열 언급은 과거 설정/로그에 남지만 제거된 실행기를 현재 다시 가동한다는 뜻은 아니다.

| 경로 (`workbench_runs/` 아래) | 논리 크기 MiB | 성격 |
|---|---:|---|
| `sfm_comparison_20261108` | 854.39 | 폐기된 SfM 비교 실험·로그·결과, 과거 문서2개 참조 |
| `real_codex_flow_20261106` | 823.47 | 독립 개발 Project/모델링·비교 실행 |
| `scene_autofit_20261101` | 198.13 | 수치 정합 비교. 현재 Candidate에 역사 출처 참조 있음 |
| `multiview_architecture_20261105` | 125.94 | 과거 다중 View 실험 |
| `scene_improvement_20261104` | 44.09 | 개선 검증 |
| `scene_refinement_20261031` | 36.61 | 과거 Scene 수정 비교 |
| `reconstruction_review_20261104` | 5.85 | Reconstruction 검토 |
| `scene_physics_20261101` | 5.61 | 물리 진단 |
| `guidance_20261106` | 3.79 | Guide 전달 검증 |
| `workspace_library_20261104` | 3.15 | Library 검증 |
| `asset_groups_20261104` | 2.39 | Asset 그룹 검증 |
| `v3_modeling_20261104` | 1.88 | 모델링 검증 |
| `scene_memo_refactor_20261104` | 1.04 | Memo 경계 검증 |
| `review_checkpoint_20261104` | 0.96 | 과거 checkpoint 진단. 현재 조사한 문서 exact path 참조도 없음 |
| `integration_20261106` | 0.60 | 통합 검증 |
| `fitting_strategy_20261105` | 0.50 | 정합 전략 검증 |
| `auto_reconstruction_ui_20261107` | 0.45 | UI smoke |
| `support_constraints_20261107` | 0.41 | 지지 관계 검증 |
| `baseline_cleanup_20261106` | 0.35 | baseline 조사 |
| `reconstruction_implementation_20261103` | 0.05 | 초기 구현 결과 |

## 더 깔끔하게 관리할 순서

1. **이름별 제품 pool은 유지하고 개발 실험 생성을 `diagnostics/<작업>/`로 한정한다.** 지금처럼 root에 날짜별 개발 Project를 계속 추가하지 않는다. 실행/원본과 진단의 소유 경계를 먼저 분명히 한다.
2. **Capture의 Session→Capture 두 단계는 유지한다.** Session은 연결/장치/실행 identity, Capture는 순간 관측이다. 한 번 연결한 상태에서 여러 Capture를 저장하면 동일 세션 자료를 재사용할 수 있다. 파일을 평탄하게 한 폴더에 섞어 q/시간 대응을 잃지 않는다.
3. **새 Rig/Asset의 closure를 원본으로 사용한다.** 과거 Export를 새 자산의 source로 재귀 포장하지 않는 것이 긴 경로를 예방한다. 각 실행의 선택 Version·SHA는 기존 manifest에 남긴다.
4. **연결 Recipe·R03 실행 기록과 임시 Preview의 수명을 구분한다.** 종료된 IPC Preview는 삭제하고, command/ack·exit 상태·측정 저장 경로는 재현/문제 진단에 필요한 작은 기록으로 유지한다. 요청 ID/예약 파일을 무작정 삭제해 중복 실행 방어를 없애지 않는다.
5. **자동 생성 설정은 재사용하고 미등록 파일은 생성 시 남기지 않는다.** 기본 authored wrapper는 Package identity+engine에 대한 기존 파일을 재사용하고 등록 실패 시 새로 만든 wrapper만 정리하는 식으로 기존 `register_export` 경계에서 다룰 수 있다. 사용자 named 설정은 명시 Version 선택을 유지한다.
6. **Candidate의 큰 엔진 임시 파생물과 Evidence를 구분한다.** 삭제 가능한 재생성물에는 기존 producer와 입력 SHA를 남기고, Evidence index·Checkpoint·완료 Cache가 참조한 파일은 독립 보존한다. 새 청소 Framework/DB 없이 기존 생성 함수의 `finally`·완료 단계에서 관리하는 것이 작다.
7. **폐기한 실험의 manifest와 삭제 이유는 작게 남긴다.** 파일 내용을 또 복사해 같은 Workspace에 ‘백업’하면 디스크 절감이 없다. 과거 보고서에 로컬 원시 자료가 폐기됐음을 기록해 유효한 근거 파일이 여전히 있는 것처럼 표시하지 않는다.

통합·정리 적용 시에는 현재 UI에 등록된 Project/Package/Asset·측정 Capture·Calibration·Dataset·Rig를 실제 reader로 열어 확인하고, 삭제 대상 제외 원본 SHA를 대조해야 한다. 본 조사는 새 형식으로 옮기거나 파일을 삭제한 결과가 아니며, 현재 작업의 구현/정리 담당자가 최종 판정을 내린다.
