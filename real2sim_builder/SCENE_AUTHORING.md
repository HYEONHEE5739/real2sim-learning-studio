# Codex를 통한 Scene 제작·정합 가이드

이 문서는 현재 `real2sim_builder`의 Scene 제작 진입점이다. 기존 Builder 문서의 입력 감사·후보 편집·카메라/기하 정합 원칙을 현재 코드의 CLI와 Workspace 구조로 정리했다. 과거 실행 성적이나 기존 Scene의 보정값을 새 Scene의 검증 근거로 가져오지 않는다. 문서의 명령은 사용 예시이며, 이번 문서 작성에서 실행하지 않았다.

제작을 시작하기 전에 [Scene 제작 규칙](SCENE_RULES.md)을 함께 읽는다. 실측 우선순위·GLB/접촉·좌표·Camera/FK·독립 검증·Blender·물성 규칙을 주제별로 정리했다. [기존 문서 이관 지도](SOURCE_DOCUMENTS.md)는 원본 AGENTS와 docs 전체에서 가져온 내용 및 현재 방식과의 차이를 기록한다.

## 1. 사용자와 Codex의 역할

사용 흐름은 **Scene Prepare에서 새 Project·자료·메모 저장 → Codex에 제작 요청 → Builder로 Scene 제작 → Real/Sim에서 촬영 → Codex에 정합 수정 요청**이다.

사용자는 Builder 편집 UI를 직접 조작할 필요가 없다. Codex가 Project의 사진·Snapshot·메모를 읽고 물체와 배치에 관한 가설을 세운 다음, Builder Python API/CLI로 Candidate를 작성한다. Builder는 입력 소유권·좌표/스키마·후보 이력·렌더·수치 fitting·비교·Export를 처리한다. Markdown을 넣으면 자동으로 완성하는 내장 LLM 명령은 없다. `run`도 자연어 Scene 제작기가 아닌 기존 수치 처리 파이프라인이다.

작업 시작 시 사용자의 실행 범위를 확인한다. 코드/문서 작성만 요청했거나 테스트 금지 지시가 있으면 아래 렌더·평가·엔진 명령을 자동 실행하지 않는다. Builder 제작 자체에 실제 로봇 연결이나 모터 명령은 필요하지 않다.

## 2. 어디에 무엇이 있는가

기본 Workspace는 저장소의 `workbench_runs/`다. Scene Prepare에서 생성한 실제 Project 경로를 사용한다. 표시 이름과 폴더 이름은 다를 수 있으므로 폴더 안 `project.yaml`을 확인한다.

```text
workbench_runs/scenes/<project-folder>/
  project.yaml
  input/evidence.yaml           # 등록된 입력·메모·Capture 참조
  input/captures/<session>/     # Snapshot 또는 Real/Sim Pair 원본
  input/observations/<session>/ # model 미결합 Camera/SDK 관측
  working/current_scene.yaml   # 현재 authoring Scene (초기에는 없을 수 있음)
  scratch/agent/<candidate>/   # 후보 Scene·수치 보고서·렌더
  exports/<revision>/          # 닫힌 실행/검토 Package
  configuration/               # 등록된 엔진 설정
workbench_runs/devices/        # Scene과 연결된 장치 구성·보정
```

파일을 폴더 이름만 보고 전부 학습/보정 입력으로 사용하지 않는다. `evidence.yaml`, Capture manifest와 상태를 먼저 읽는다. 이미 자동 등록된 Capture를 다시 Import하지 않는다. 미완료 Pair의 Real 이미지가 남아 있어도 완성 Pair로 표시하지 않는다.

현재 이관된 예시는 `workbench_runs/scenes/pickplace-colorblock-b7a5592b`이며 실행 Package는 `exports/scene-v8-native`다. 새 Scene 제작 시 이 예시의 치수·카메라·관절 보정·물성을 근거 없이 복사하지 않는다.

## 3. 입력을 해석하는 기준

| 입력 | 사용할 정보와 한계 |
|---|---|
| Scene 메모/요구사항 MD | 물체 이름·역할·사용자가 명시한 실측·배치·목표 작업. 자연어만으로 측정 정확도를 인증하지 않음 |
| 사진·영상 | 외형·색·가림·상대 배치. RGB만으로 절대 크기나 Camera/Base를 확정하지 않음 |
| GLB/Scan | 표면·상대 배치의 초기 추정. 실측과 충돌하면 실측 제약을 반영하고 차이를 기록 |
| Snapshot | 원 RGB·측정 q·시각·Model/Mapping/Calibration identity. commanded q와 measured q 구분 |
| Real/Sim Pair | 같은 관측의 Real2장·Sim2장·선택 Revision·렌더 q·비교 결과. Sim 이미지는 새 실측이 아님 |
| URDF/Mesh/SDK/Precision | 모델과 좌표 변환의 출처. SDK Encoder 보정과 model-rad Precision은 별개 |
| Landmark/Mask/치수 | 근거가 있는 기하 비교. 후보 선택에 사용한 자료는 독립 최종 검증으로 재사용하지 않음 |

길이·위치는 m, 회전 관절은 rad, 세계 좌표는 오른손 +Z up, pose는 column vector에 적용하는 `T_parent_child`다. Camera 광학 좌표는 +X right/+Y down/+Z forward다. Box dimensions는 전체 크기, pose는 중심이다. K는 해당 영상 해상도와 결합하며 distortion을 조용히 버리지 않는다.

출처는 `measured/calibrated/derived/optimized/estimated/unknown`으로 구분한다. 없는 Robot Base·K·Extrinsic에 identity/임의 숫자를 넣고 실측이라 부르지 않는다. model 미결합 관측은 이미지 참고자료로 사용할 수 있지만 임의 6축 q나 action을 생성하지 않는다. 정지 관측 저장과 Reconstruction 보정 적격성은 별개다.

## 4. 현재 CLI와 편집 진입점

기존 명령 `python -m app.cli` 대신 **`python -m real2sim_builder.cli`**를 사용한다. 설치를 새로 하기보다 준비된 Backend interpreter와 이 저장소의 소스 경로를 사용한다. 로컬 환경 선택은 `../run_workbench_ui.sh`, USD 등 Export 의존성은 `../docs/builder-bundle.md`를 참고한다. Qt interpreter에 엔진 의존성이 있다고 가정하지 않는다.

아래 `PROJECT`, `edits.json`, `revision-001`은 실제 작업 경로와 새 이름으로 바꾼다. Scene Prepare가 이미 Project를 만들었으면 `new`는 필요 없다.

```bash
python -m real2sim_builder.cli inspect PROJECT
python -m real2sim_builder.cli candidate PROJECT create initial_scene
python -m real2sim_builder.cli candidate PROJECT edit initial_scene --edits edits.json
```

`edits.json`은 편집 연산의 JSON 목록이다. 지원 연산/필드는 [editing.py](src/real2sim_builder/editing.py), Scene 형식은 [scene.py](src/real2sim_builder/scene.py)를 기준으로 작성한다. `add_object`, `update_pose`, `update_dimensions`, `set_visual_mesh`, `set_collision`, `set_camera`, `set_material`, `set_lighting`, `set_workflow` 등을 사용한다. 수치 예제를 그대로 실제 Scene 값으로 쓰지 않는다.

외부 Mesh는 먼저 `candidate PROJECT asset initial_scene --path /path/to/mesh.obj --kind visual`로 소유 경로에 등록하고 반환된 asset ID로 참조한다. 입력 추가는 `add PROJECT PATH --kind brief|image|reference|video|measurements|calibration|scene|robot` 중 실제 종류를 하나 선택한다. GLB는 `scan PROJECT import --path /path/to/scan.glb` 경로다.

Python에서는 `real2sim_builder.project.Project`와 `Candidate`를 사용한다. `Candidate.create`는 Current Scene 또는 빈 Scene에서 시작한다. 다른 OPEN 후보를 자동 baseline으로 고르지 않는다. `Candidate.edit`는 잠금과 스키마/보호 필드 검사를 포함한다. 직접 `Candidate.save`를 사용할 때도 Project의 `exclusive` 잠금 안에서 수행한다. 실행 중 YAML 문자열 치환이나 lock 삭제로 충돌을 우회하지 않는다.

## 5. 제작과 정합 반복

1. **입력 감사:** Project·원본 SHA·촬영 Session/scene-state·해상도·q와 Mapping 출처를 확인한다. 물체를 움직인 서로 다른 장면을 하나의 고정 배치로 합치지 않는다.
2. **초기 Scene:** 물체/Frame/Camera ID, 역할, visual과 collision을 분리해 작성한다. GLB의 모든 점을 충돌 형상으로 쓰지 않는다. 빈 컵에는 바닥과 벽/내부 공간이 있는 collision이 필요하다.
3. **원인별 정합:** Robot/FK·Base → Side Camera → 물체/테이블 기하 → Wrist mount/Camera → 전체 자세 비교 순으로 원인을 분리한다. Camera 오차를 물체 크기나 관절 q 변경으로 숨기지 않는다.
4. **후보 비교:** baseline, 가설, 변경/고정 변수, 사용 관측, 수치·overlay, 채택/거절 이유를 남긴다. 실제 측정 제약 위반이나 중요한 자세의 회귀를 숨기지 않는다.
5. **반복 종료:** 추가 개선이 없거나 원인을 구별할 자료가 부족하면 무엇을 더 촬영/측정해야 하는지 보고한다. 모든 후보를 승인 상태로 바꾸지 않는다.

실행이 요청된 범위에서 사용하는 명령 예:

```bash
python -m real2sim_builder.cli candidate PROJECT evaluate initial_scene --engine mujoco --renderer software-egl
python -m real2sim_builder.cli diagnose PROJECT --candidate initial_scene --engine mujoco
python -m real2sim_builder.cli coverage PROJECT --candidate initial_scene --engine mujoco
python -m real2sim_builder.cli candidate PROJECT promote initial_scene
python -m real2sim_builder.cli validate PROJECT --engine mujoco --renderer software-egl
```

`render`는 영상 생성, `evaluate`는 비교까지 수행한다. `promote`에는 최신 평가와 기존 보호 조건이 적용되며 promotion만으로 물리 정확성이 인증되지 않는다. 결과 JSON의 status/reason도 읽는다. Blender가 필요하면 기존 `blender-build → blender-author → blender-sync`와 `evaluate --engine blender`를 사용하며 새 Agent Framework를 만들지 않는다.

Camera fitting은 기존 `candidate ... fit ... --target bootstrap:side`, `intrinsics:side`, `camera:wrist`, `distortion:side`, `quality:side` 등을 사용한다. 필요한 옵션·대응점·자세 다양성은 현재 [calibration/geometry.py](src/real2sim_builder/calibration/geometry.py)를 확인한다. 수렴 자체를 calibrated로 표기하지 않는다. Wrist는 `T_world_base × FK(q_measured) × T_mount_camera` 관계를 유지한다.

이미 model rad인 q에 Precision Mapping을 다시 적용하지 않는다. **이전 문서의 `simulation_joint_offsets_rad` 추가 실행 보정은 현재 방식이 아니다.** 기존 v8의 baked Geometry와 명시 identity는 보존하고, 새 Scene 정합을 위해 과거 offset이나 측정 q를 임의 변경하지 않는다.

RGB MAE/RMSE는 외관 차이다. Landmark px, silhouette IoU, 실측 거리/접촉 residual 등 근거가 있는 지표를 함께 사용한다. 대응점/Mask가 없으면 기하 정확도는 미측정이다. 추정값과 실제 측정값, in-sample 개선과 독립 검증을 분리한다.

## 6. Export와 새 프로젝트에서 사용

```bash
python -m real2sim_builder.cli export PROJECT --destination PROJECT/exports/revision-001
python -m real2sim_builder.cli verify PROJECT/exports/revision-001
```

닫힌 Export를 덮어쓰지 않고 새 경로를 사용한다. 미검증 후보를 검토용으로 내보내야 한다면 `--candidate initial_scene --allow-unvalidated`를 명시하고 결과를 UNVALIDATED로 전달한다. 최신 입력/평가 및 파일 무결성 요구사항을 우회하지 않는다.

실행 자산은 필요에 따라 `--calibration /path/to/calibration.json`, `--isaac-robot-asset /path/to/articulated.usd`, `--mujoco-robot-asset /path/to/environment.xml`로 지정한다. 일반 Export의 현재 구현은 Project 실행 목록 등록까지 연결한다. 자세한 흐름은 [export.py](src/real2sim_builder/export.py), [registration.py](src/real2sim_builder/registration.py)다.

**정적 Scene 렌더, 물리 Simulation, 실물 제어는 서로 다른 준비 상태다.** Source/DataGen에는 실제 Articulation·관절/Actuator·Camera·초기 관절·active object·Task에 필요한 접촉 정보 등이 필요하다. 정적 USD 참조나 USD 파싱 성공을 Isaac 물리 실행 성공으로 보고하지 않는다. Real/Sim용 authoring 렌더 설정을 Source 물리 실행 설정으로 그대로 사용하지 않는다. Task/Placement 함수는 Workbench가 소유하며 Scene의 작업 메모만으로 시연·학습·성공 판정이 만들어지지 않는다.

사용자에게 Project 경로, 선택 Candidate와 Export Revision, Real/Sim에서 선택할 이름/엔진, 실제 수행한 확인, 미실행/미확인 항목을 전달한다. Capture 결과를 받은 다음 수정은 같은 Project의 새 후보·새 Export로 진행한다. 원 RGB·Snapshot·Calibration·기존 Package는 보존한다.

## 7. 다음 Codex에게 줄 요청 예시

```text
real2sim_builder/SCENE_AUTHORING.md를 먼저 읽어줘.
Project: workbench_runs/scenes/<내 프로젝트 폴더>
제작 요구사항: <내 MD 경로> 및 Project에 저장한 Scene 메모
input/evidence.yaml에 등록된 입력과 Snapshot을 이용해 Scene을 제작해줘.
원 촬영/보정 자료와 기존 Export는 보존하고, 새 Candidate/Revision을 사용해줘.
실측과 추정값을 구분하고, 자료가 부족한 항목은 구체적으로 알려줘.
이번에 실행할 범위: <예: 작성만 / MuJoCo 렌더 비교·Export까지>
```

정합 수정 요청에는 이번 Real/Sim `input/captures/<session>` 경로와 어떤 부분이 어긋나는지 덧붙인다. 이 가이드가 참조 문서이며 실제 요구사항은 사용자의 이번 지시를 따른다.

## 출처와 현재 코드 지도

기존 Builder의 `AGENTS.md`, `CODEX_HANDOFF.md`, `docs`의 Markdown 14개 전체와 현재 CLI/Project/Candidate 코드를 바탕으로 보강했다. 전체 목록은 [SOURCE_DOCUMENTS.md](SOURCE_DOCUMENTS.md)에 있다. 기존 문서의 `app.cli`, 옛 Adapter 등록 절차, 특정 Scene 치수/환경 경로, 과거 시험 결과, 추가 runtime joint offset은 새 작업 명세로 복사하지 않았다. 이 안내를 사용하는 데 이전 프로젝트 폴더가 필요하지 않다.

- [CLI](src/real2sim_builder/cli.py): 실제 명령/인자
- [Project](src/real2sim_builder/project.py) · [Candidate](src/real2sim_builder/candidate.py): 수명·편집·승격
- [Evidence](src/real2sim_builder/evidence.py) · [Capture](src/real2sim_builder/capture.py): 입력/관측 등록
- [Reconstruction](src/real2sim_builder/reconstruction.py) · [Validation](src/real2sim_builder/validation.py): fitting·진단·비교
- [현재 UI/Workflow 안내](../docs/builder-scene-guide.md): Scene Prepare·Real/Sim·Source 사용
