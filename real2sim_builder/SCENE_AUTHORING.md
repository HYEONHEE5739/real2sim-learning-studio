# Codex를 통한 Scene 제작·정합 가이드

이 문서는 현재 `real2sim_builder`의 Scene 제작 진입점이다. 기존 Builder 문서의 입력 감사·후보 편집·카메라/기하 정합 원칙을 현재 코드의 CLI와 Workspace 구조로 정리했다. 과거 실행 성적이나 기존 Scene의 보정값을 새 Scene의 검증 근거로 가져오지 않는다. 문서의 명령은 사용 예시이며, 이번 문서 작성에서 실행하지 않았다.

제작을 시작하기 전에 [Scene 제작 규칙](SCENE_RULES.md)을 함께 읽는다. 실측 우선순위·GLB/접촉·좌표·Camera/FK·독립 검증·Blender·물성 규칙을 주제별로 정리했다. [기존 문서 이관 지도](SOURCE_DOCUMENTS.md)는 원본 AGENTS와 docs 전체에서 가져온 내용 및 현재 방식과의 차이를 기록한다.

## 1. 사용자와 Codex의 역할

사용 흐름은 **Scene Prepare에서 새 Project·자료·메모 저장 → Codex에 제작 요청 → Builder로 Scene 제작 → Real/Sim에서 촬영 → Codex에 정합 수정 요청**이다.

사용자는 Builder 편집 UI를 직접 조작할 필요가 없다. Codex가 Project의 사진·Snapshot·메모를 읽고 물체와 배치에 관한 가설을 세운 다음, Builder Python API/CLI로 Candidate를 작성한다. Builder는 입력 소유권·좌표/스키마·후보 이력·렌더·수치 fitting·비교·Export를 처리한다. Markdown을 넣으면 자동으로 완성하는 내장 LLM 명령은 없다. `run`도 자연어 Scene 제작기가 아닌 기존 수치 처리 파이프라인이다.

작업 시작 시 사용자의 실행 범위를 확인한다. 코드/문서 작성만 요청했거나 테스트 금지 지시가 있으면 아래 렌더·평가·엔진 명령을 자동 실행하지 않는다. Builder 제작 자체에 실제 로봇 연결이나 모터 명령은 필요하지 않다.

## 1-A. “Scene 만들어줘” 요청의 기본 처리 — Codex가 직접 Builder 호출

이 Builder의 실질 사용자는 **Codex**다. 사용자는 Scene Prepare UI에 사진/영상, 실측 치수, GLB, 로봇 모델과 작업 메모를 등록하고, 필요하면 Side/Wrist 여러 자세를 Capture할 뿐이다. **사용자에게 Builder의 fit target, Landmark 좌표 입력, CLI 사용을 요구하지 않는다.** Codex는 Project를 확인해 Builder CLI/Python API를 실행하고 후보 Scene을 생성·수정한다. 추가 LLM 런타임이나 UI 자동 클릭을 구현할 필요는 없다.

### Codex가 수행할 기본 순서

1. `project.yaml`, `input/evidence.yaml`, capture manifest, scene-state, 요구 메모, `working/current_scene.yaml`, OPEN Candidate, `exports/` 목록을 먼저 읽는다. 미등록 원본을 임의로 미디어 전체 검색하여 학습 입력으로 섞지 않는다.
2. 치수·Robot Base·URDF·measured q·실측 K 등 **신뢰할 수 있는 Anchor를 잠근다.** 한 layout에서만 물체 world pose를 공유하고, layout이 바뀌면 분리한다.
3. 기존 Candidate 생성·편집 API로 Geometry·Frame·Camera·Collision을 갖춘 **초기 Metric Scene Candidate**를 만든다. 알려진 GLB/치수가 있는데 영상을 보고 새 기하를 발명하지 않는다.
4. `auto-observe`로 Side/Wrist 이미지에서 Marker·Block·Cup·Gripper의 landmark/mask 후보를 추출한다. **자동 제안은 곧 실측이 아니다.** Codex가 물체 ID·3D/2D 대응점·가림을 검토하고 신뢰할 수 있는 관측을 선택한다.
5. Side/Wrist/공통 Object Pose **공동 Multi-view Fit**을 호출한다. Side는 공유 world camera pose, Wrist는 공유 link-local mount/FK, Object는 공유 world pose다. 하나의 pose를 View마다 다르게 만들지 않는다. K가 미측정이면 기존 bootstrap을 먼저 사용하고 fitting 상태를 estimated/optimized로 표시한다.
6. 다섯 자세 등 모든 사용 관측을 카메라·자세·물체별로 비교한다. Global RGB MAE만 낮추는 변경은 지양한다. Obj-mask 경계/코너 오차, robot/gripper 윤곽, supporter-plane 등을 구분한다.
7. Camera 오차를 Object geometry/물리량/Joint Offset으로 숨기지 않는다. 데이터가 모자라면 추정 Candidate를 저장하고, **어떤 시점에서 무엇을 추가 촬영하면 되는지**만 구체적으로 요청한다.
8. Candidate 검토 후 기존 `export_revision`으로 **새 Revision**을 내보낸다. ACCEPTED를 증빙할 독립 자료가 없으면 검토용 UNVALIDATED Export로 구분한다. 원본/기존 Scene은 덮어쓰지 않는다.

### 구현된 CLI 진입점

기존 Candidate·개별 정합·검토·Export:

```bash
python -m real2sim_builder.cli inspect PROJECT
python -m real2sim_builder.cli candidate PROJECT create initial
python -m real2sim_builder.cli candidate PROJECT fit initial --target bootstrap:side
python -m real2sim_builder.cli candidate PROJECT fit initial --target camera:wrist
python -m real2sim_builder.cli candidate PROJECT evaluate initial --engine mujoco
python -m real2sim_builder.cli export PROJECT --destination PROJECT/exports/revision-002 --candidate initial --allow-unvalidated
```

이번에 소스로 연결한 자동 제안·명시 반영·공동 정합(실행 검증 미수행):

```bash
python -m real2sim_builder.cli auto-observe PROJECT --candidate initial --scene-state layout_01
python -m real2sim_builder.cli auto-observe PROJECT --commit scratch/agent/initial/observations/DIGEST/proposals.json --selections selections.json
python -m real2sim_builder.cli candidate PROJECT fit initial --target joint:scene --options fit-options.json
```

이 API의 구현 책임·관측 제안 스키마·최적화 변수·Codex 사용 순서는 [`AUTO_SCENE_FITTING.md`](AUTO_SCENE_FITTING.md)를 따른다. 현재 MVP는 검토된 3D–2D Landmark로 공동 최적화하며, 승인 silhouette는 기존 평가에서 비교한다. 렌더 Mask 반복 최적화와 자동 3D corner 확정은 구현하지 않았다. 실행 허용 범위는 사용자의 요청을 따른다.

### Codex에게 요청할 최소 사용자 문장

> `real2sim_builder/SCENE_AUTHORING.md를 읽고, 내가 Scene Prepare에 등록한 Project의 사진/GLB/실측/Side·Wrist Capture로 새 Scene 만들어줘. 기존 원본은 보존하고 새 Candidate·Export Revision을 만들어.`

## 1-B. 선택형 작업 물체와 실행 구성

Scene Prepare 메모의 `[항상 배치할 구성요소]`와 `[선택형 작업 물체]`를 Codex가 먼저
읽고 각 Object에 생성 정책을 명시한다. 사용자가 자연어로 분류하면 Codex가 아래
Builder 편집/API로 구조화한다. 사용자에게 JSON/CLI를 직접 작성하도록 요구하지 않는다.
메모 양식의 빈 칸과 안내 문장은 사용자 측정값이 아니다. 미제공 치수·물성은 unknown으로 둔다.

- `spawn: always`: 기본 구성요소. 물리적으로 static이라는 뜻은 아니다.
- `spawn: recipe`: Source/DataGen/Sim 평가 Script의 `objects`에 포함될 때 생성하는 물체.
- 컵·블록 같은 이름이나 색으로 역할을 추측하지 않는다. 조작할 컵도 선택형일 수 있다.
- 형상, 충돌, 물성, `role`은 생성 정책과 별개다. 선택에서 빠진 물체의 부속 장식도 함께 빠진다.
- Scene 제작/Real·Sim 정합은 원 관측 배치를 유지한다. Script 기반 작업 실행이 선택형
  물체의 구성·배치를 결정하며, Annotation/기록 Source replay는 기록 당시 구성을 복원한다.
- 기존 Dataset/Export의 물체 구성은 소급 변경하지 않는다. 정책 변경은 새 Candidate/Export로 만든다.

`add_object`에 `spawn`을 지정하거나 기존 Candidate에서 `set_spawn`을 사용한다.
예를 들어 `object-spawn.json`의 내용은 다음과 같다.

```json
[
  {"op":"set_spawn","id":"cube_red","value":"recipe"},
  {"op":"set_spawn","id":"cube_blue","value":"recipe"},
  {"op":"set_spawn","id":"cube_green","value":"recipe"}
]
```

```bash
python -m real2sim_builder.cli candidate PROJECT edit CANDIDATE --edits object-spawn.json
```

Workbench Recipe의 `objects.<id>.task_object: true`는 **Data Curation의 Task objects/초기
위치 분포 대상**이다. 생성 여부와 혼동하지 않는다. `false`라도 `objects`에 넣으면 생성한다.
한 항목이라도 flag를 명시하면 `true`인 물체만 대상이 된다(나머지는 false). flag가 전혀 없는
기존 Source Script는 선언한 물체를 대상으로 기록한다. Annotation은 이를 계승하고,
DataGen은 별도 flag가 없으면 입력의 작업 대상을 계승한다. 실제 Task 성공 함수/작업 문장을
이 flag가 대신하지 않는다.

예를 들어 빨강·파랑을 생성하고 파랑만 분석 대상으로 쓰는 Script의 `objects` 일부:

```yaml
objects:
  cube_red:
    task_object: false
    placement:
      function: placement.random_workspace
      params: {frame: object_marker, support: table, workspace: marker}
  cube_blue:
    task_object: true
    placement:
      function: placement.random_workspace
      params: {frame: object_marker, support: table, workspace: marker}
```

이 예시에서 `cube_green`은 생성하지 않는다. 분포는 파랑의 원 Episode 첫 기록 위치를
보여주며 여러 `true` 대상이면 Curation에서 고른다. 객체 ID/Frame/Support는 해당 Scene의
실제 선언을 사용한다. 입력 Annotation과 모델 구성이 다른 DataGen은 기존 모델 일치 검사를
유지하므로, 원하는 물체 구성으로 수집·Annotation한 자료를 사용한다.

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
3. **원인별 정합:** Robot/FK·Base와 카메라 초기값을 확인하고 자동 제안을 검토한 뒤 `joint:scene`으로 공유 Camera·물체 배치를 공동 정합한다. Side/Wrist·물체별 잔차로 지배적 원인을 좁혀 개별 fitting을 보완한다. Camera 오차를 물체 크기나 관절 q 변경으로 숨기지 않는다.
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
