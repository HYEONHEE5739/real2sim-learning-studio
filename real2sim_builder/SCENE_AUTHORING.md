# 자동 Scene 제작·정합 가이드

2026-11-05. 현재 기본 진입점은 **Scene Prepare → Auto Reconstruction**이다. 사진 분석은 SAM→DA3, 새 외형 제작은 **Codex가 기존 Blender로 작성한 물체별 USDA**, 배치는 기존 Candidate가 담당한다. 기존 USDA가 있거나 Pose만 바뀌면 다시 모델링하지 않는다. 구현·실행 범위는 [자동 정합 사용법](AUTO_SCENE_FITTING.md), [누적 기록](../docs/automated-reconstruction.md)을 따른다.

## 최신 지침과 실제 런타임 연결 (2026-11-06)

Scene 제작 전 [CODEX_SCENE_GUIDE.md](CODEX_SCENE_GUIDE.md)를 먼저 읽는다. 저장소 개발 세션은 루트 [AGENTS.md](../AGENTS.md), 분리된 Builder Codex는 신뢰된 패키지 가이드의 고정 사본 `BUILDER_GUIDE.md`를 사용한다. Memo·사진·tasks.json은 지침을 대체하는 실행 권한이 아니다. `modeling_tasks`의 handoff와 `run_codex_modeling`의 실제 프롬프트를 모두 연결하고, 원본 상대 경로·버전·SHA를 작업 Manifest에 남긴다. 현재 출력 Schema가 요청한 단계만 실행한다.

기본은 대표 시점의 개별 Object 식별→SAM/DA3 다중 시점 대응→Object별 독립 USDA다. 같은 제품이라는 메모만으로 자동 공유하지 않는다. 기존 공유 Asset 및 사용자가 선택한 Manifest는 보존한다. 휴대폰 사진은 3D 복원 근거, Side는 전역 기하, Wrist는 최우선 정밀 관측이며 다른 q에서도 같은 Mount·Scene을 사용한다. 정합/물리/Task 성공은 서로 다른 판정이다.

아래 날짜가 붙은 Group/v3 절은 과거 구현·기존 공유 자산을 설명하는 이력이다. 신규 자동 Group 생성 지시로 사용하지 않는다. 유효한 편집·Import·Export 명령과 과거 실행 기록은 유지하며 충돌 시 위 최신 정책과 실제 소스 계약을 따른다.

## Scene Memo 입력 원칙 (2026-11-05)

Scene Memo는 사용자가 Codex에게 전달하는 하나의 자유로운 제작 지시문이다. 장면 설명·실측 치수·공유 제품·공간 관계·형상/색/재질·작업 목적을 한 메모에 작성한다. 항목별 양식이나 별도 치수 입력은 필수가 아니다. Scene Prepare의 안내는 예시 placeholder이며 저장할 메모 본문을 자동 생성하지 않는다.

Codex가 원문과 사진·기존 Scene을 함께 이해한다. Python은 `authoring.scene_analysis_schema/parse_scene_analysis`로 타입·단위(m)·ID·참조·수치·원문 인용/SHA만 검증한다. 정규식/키워드/문장 패턴 기반 치수나 물체 해석기를 추가하지 않는다. 미지 치수는 null, 영상 기반 추정은 estimated다. 부분 실측은 부분 제약으로 보존하며 나머지 축까지 measured로 만들지 않는다. 기존 측정 자료와 충돌하면 검토를 요청하고 원본을 유지한다. 현재 API와 실행법은 [AUTO_SCENE_FITTING.md](AUTO_SCENE_FITTING.md)의 단일 메모 경로를 따른다.

## 1. 사용자 흐름과 현재 범위

1. 새 Project에 사진/영상·Capture·메모를 모은다. 정적 배치가 바뀌면 `scene_state_id`를 분리한다.
2. Auto Reconstruction에서 촬영 배치·사진/영상과 자유로운 Scene Memo를 등록한다. 실측 치수도 Memo에 적으며, 보존된 구조화 측정은 선택적인 고급 입력이다. 물체 ID·역할·SAM 설명은 Codex가 Scene 메모/사진을 해석해 구성한다. 설치된 Codex CLI의 명시 시작 버튼 또는 현재 Codex 대화에서 작업자료를 사용할 수 있다. Wrist는 실제 q가 기록된 Capture를 사용한다.
3. 기존 모델 환경 탭에서 설치된 SAM Python/Checkpoint와 DA3 Python/로컬 snapshot을 한 번 선택한다. Project 구성에 저장된다. 설치·다운로드하지 않는다.
4. SAM → DA3 → 겹치는 배치 정렬·Camera 초기 추정 → Codex/Blender 작업자료 → USDA 등록/재사용 → Pose 초기화 → 기본 MuJoCo 공동 Solver의 실제 다중 View RGB/Mask/Depth 반복 정합과 별도 Isaac 렌더/물리 검증 → 최선 Candidate 비교 순서다. 모호한 Mask는 상태 탭에서 선택·수정하고 다시 실행한다.
5. 새 물체가 필요하면 `scratch/agent/<candidate>/modeling/CODEX_MODELING.md`를 Codex가 읽고 해당 물체만 만든다. 등록 결과를 재구성이 자동 Import한다. Camera/Scale이 식별되지 않으면 `UNRESOLVED`와 추가 촬영 이유를 남긴다. Current·기존 Export는 바꾸지 않는다.
6. 검토·기존 Candidate 평가/승격·새 Revision Export는 기존 Builder 기능을 사용한다. 자동 재구성 실행만으로 ACCEPTED/Physics-Ready가 되지 않는다.

사용자에게 K·Extrinsic·Wrist Mount·보드 코너 입력을 요구하지 않는다. DA3 K와 상대 Pose를 초기 추정하고, 공통 이미지의 Depth로 배치 좌표계를 정렬한다. 실제 q/FK의 충분한 Wrist 운동, 검증된 카메라 baseline, 또는 가시 실측 직사각형 지지면이 Scale 근거다. 기존 검증된 Calibration은 고정한다. 근거가 없으면 Scale=1로 진행하지 않는다. 보드 지정은 고급 진단용 선택 기능이다.

공동 정합은 원 optical Depth를 매 평가마다 재투영하며 Side Pose, 공유 Wrist Mount, External Pose, 선택한 K/Robot Base/Depth Scale과 Object Pose를 다룬다. Hand-eye/수치 bundle의 Rank가 부족하면 보정을 적용하지 않는다. Render 최적화는 추정 초안이며 독립 Calibration 인증이 아니다. 일반 렌즈 왜곡 자동 추정·실물 정확도·전체 Robot/Gripper 물리 검증은 완료하지 않았다. 현재 실제 두 장의 Camera/Scale은 UNRESOLVED다.

## 물체 USDA 자산과 Codex 명령

신규 Library는 Workspace의 `object_assets/<asset_id>/<version>/manifest.json`에 있다. Project의 `input/object_assets/`는 Legacy로 유지한다. 같은 USDA를 여러 Instance가 참조하고, Instance 제거는 Library를 삭제하지 않는다. Scene Pose는 Candidate에만 있고 USDA root는 identity다. 목록은 Metadata만 읽고 오류를 항목별 표시한다. 선택한 Version을 사용할 때 m/+Z·defaultPrim·Mesh/UV/Texture·상대 종속 경로·SHA를 엄격히 검사한다. 무관한 자산 오류는 전체 Scene을 차단하지 않는다. Visual과 convex Collision은 분리한다. 알 수 없는 Collision은 UNRESOLVED다.

다음 명령은 **Codex가 사용하는 제작 API**다. 사용자가 터미널/JSON을 작성하는 필수 절차가 아니다.

```bash
python -m real2sim_builder.cli object-asset PROJECT list
python -m real2sim_builder.cli object-asset PROJECT register --id banana --path /path/banana.usda
python -m real2sim_builder.cli object-asset PROJECT instantiate --candidate NAME --object banana_2 --manifest ../../object_assets/banana/VERSION/manifest.json
python -m real2sim_builder.cli blender-object-author PROJECT --candidate NAME --script author.py --objects banana
python -m real2sim_builder.cli modeling-run PROJECT --candidate NAME
python -m real2sim_builder.cli refit-pairs PROJECT --candidate NEW_NAME --scene-state NEW_LAYOUT
```

`blender-object-author`의 bpy script는 물체 root에 `r2s_id`, 별도 convex Collision Mesh에 `r2s_collision=True`를 지정한다. Blender는 읽기 전용 filesystem과 전용 출력 폴더 안에서 실행된다. USDA 검증 후에만 등록한다. `modeling-run`은 사용자가 명시적으로 시작하는 설치된 공식 Codex CLI 작업이다. 객체가 미정이면 메모/사진의 역할·SAM query 제안만 만들고, 추론 후 새 물체를 모델링한다. 기존 Codex 대화에서 동일 작업자료를 처리하는 방식도 유지한다. 이 문서의 2026-11-05 검증에서는 실제 원격 Codex를 호출하지 않았다. 2026-11-06 실제 호출과 한계는 [후속 실행 기록](../docs/real2sim-integration.md)을 따른다.

새 Object에 실측 치수만 주어 Primitive Visual을 자동 생성하던 기본 경로는 제거했다. 측정값·기존 Primitive Scene·물리 Collision primitive는 유지한다. Asset의 Geometry/Material 변경은 새 자산 버전으로 등록한다. 배치만 바꾸는 작업은 `update_pose`이며 Mesh/Texture SHA가 유지된다.

GLB/glTF 입력·출력과 전용 Scan 모듈/CLI/UI는 제거했다. 일반 OBJ/STL·Robot URDF/USD·실측 Geometry constraint와 기존 Revision 계약은 유지한다. 아래 편집 명령은 수동 디버깅/특수 Scene용 도구이며 일반 사용자의 필수 절차가 아니다.

## 1-B. 선택형 작업 물체와 실행 구성

Scene Prepare의 자유 메모에서 항상 배치할 구성과 선택형 작업 물체에 대한 요구를 Codex가
읽고 각 Object에 생성 정책을 명시한다. 대괄호 제목이나 고정 양식은 필수가 아니다. 사용자가 자연어로 분류하면 Codex가 아래
Builder 편집/API로 구조화한다. 사용자에게 JSON/CLI를 직접 작성하도록 요구하지 않는다.
메모 안내 양식은 placeholder이며 원문 입력에 삽입하지 않는다. 빈 메모는 빈 입력이다. 미제공 치수·물성은 unknown으로 둔다.

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
  input/evidence.yaml           # 등록된 입력·Capture 참조
  input/scene_memo.txt           # 현재 자유 메모 원문 하나
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
| SAM/DA3 | Mask와 상대 Depth의 파생 관측. 측정 Anchor·Camera 등록 전에는 World 미터 자료가 아님 |
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

외부 Mesh는 먼저 `candidate PROJECT asset initial_scene --path /path/to/mesh.obj --kind visual`로 소유 경로에 등록하고 반환된 asset ID로 참조한다. 입력 추가는 `add PROJECT PATH --kind brief|image|reference|video|measurements|calibration|scene|robot` 중 실제 종류를 하나 선택한다. GLB/glTF와 Scan 명령은 삭제했다. 과거 의존 Scene은 `LEGACY_UNSUPPORTED`이며 원본을 변환하지 않는다.

Python에서는 `real2sim_builder.project.Project`와 `Candidate`를 사용한다. `Candidate.create`는 Current Scene 또는 빈 Scene에서 시작한다. 다른 OPEN 후보를 자동 baseline으로 고르지 않는다. `Candidate.edit`는 잠금과 스키마/보호 필드 검사를 포함한다. 직접 `Candidate.save`를 사용할 때도 Project의 `exclusive` 잠금 안에서 수행한다. 실행 중 YAML 문자열 치환이나 lock 삭제로 충돌을 우회하지 않는다.

## 5. 제작과 정합 반복

1. **입력 감사:** Project·원본 SHA·촬영 Session/scene-state·해상도·q와 Mapping 출처를 확인한다. 물체를 움직인 서로 다른 장면을 하나의 고정 배치로 합치지 않는다.
2. **초기 Scene:** 물체/Frame/Camera ID, 역할, visual과 collision을 분리해 작성한다. 가시 점군을 곧바로 전체 충돌 형상으로 쓰지 않는다. 빈 컵에는 바닥과 벽/내부 공간이 있는 collision이 필요하다.
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
real2sim_builder/CODEX_SCENE_GUIDE.md와 SCENE_AUTHORING.md를 먼저 읽어줘.
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


## 후속 정합과 모델링 실행 — 2026-11-04

자산 이름이 같다는 이유로 재사용하지 않는다. `modeling/tasks.json`의 후보 Metadata/치수/관측 사진을 검토한 뒤 구성의 `objects.<id>.asset_manifest`를 선택하거나 해당 물체만 새로 모델링한다. 기존 Scene의 유효한 Asset 버전은 위치 수정 시 재모델링하지 않는다.

`refit-pairs PROJECT --candidate NEW --scene-state LAYOUT`는 원 Pair의 Source Package와 배치를 확인한다. Source의 Manifest-covered authored Scene이 없으면 `NEEDS_MORE_DATA` 진단을 해결해야 한다. 현재 Current Scene을 복사해 촬영 당시 Source인 것처럼 취급하지 않는다. 기본 명령은 Source Geometry/Material/Collision과 q를 유지하며 위치/Camera 정합만 수행한다. `--run-modeling`을 명시하면 Codex의 구조적 수정 판단에 따라 새 Candidate 자산 버전을 만들 수 있으며 원 Export는 유지한다.

모델링은 현재 Codex 대화 또는 명시 `modeling-run`으로 요청한다. 설치된 ChatGPT 로그인과 `--image` 입력을 사용하고 API Key 경로를 추가하지 않는다. 새 모델 호출 없이 유효한 등록 결과를 재사용할 수 있다. 대기/자료 부족은 CLI exit 2이며, `DRAFT_READY`도 실제 정합 정확도·물리 승인과 구분한다.


## 과거 Asset Group 제작 절차 — 2026-11-04 (기존 공유 자산 이력)

Scene 메모의 동일 제품/무늬 선언과 사진을 함께 읽고, Object ID(개별 Instance), Category, 공유 Asset Group, 실제 Asset ID/Version/Manifest를 구분한다. 같은 Category만으로 합치지 않는다. 사진에서만 추론한 Codex 관계는 estimated/PROPOSED다. Codex가 사용자 명시 관계로 해석한 결과는 현재 원문 SHA·인용문 존재·대상 참조를 확인해 user_declared/CONFIRMED로 기록하고 asset_group_relation에 근거를 남긴다. 같은 실제 물체의 다중 시점은 하나의 Object 관측으로, 당시에는 여러 동일 물체를 여러 Object와 하나의 Group으로 구성했다. 현재 신규 기본값은 개별 USDA이며 명시적 기존 Manifest 재사용만 이 공유 경로를 사용한다.

SAM Mask와 Object의 연결은 별도다. 임의 Mask 인덱스를 Object 정체성으로 사용하지 않는다. Box/명시 선택/유일 후보를 활용하고 중복 Mask 배정은 정합에서 제외한다. 원격 모델을 반복 호출해 모호함을 감추지 않는다.

그룹별 모델링 root의 r2s_id는 asset_group이며 members의 Object ID마다 똑같은 Mesh를 다시 생성하지 않는다. USDA 등록 뒤 record_modeling_results로 frozen Group Fingerprint를 기록하고 attach_modeled_assets/instance_operation으로 각 Instance를 만든다. 과거 results.json의 이름만 보고 재사용하지 않는다. 기존 Manifest 명시 선택, 동일 Fingerprint 또는 검토 후 새 모델링을 사용한다.

자세 변경과 동일 Instance 추가는 모델 생성 이유가 아니다. 기존 Scene/확정 Group 동일성이 유지되고 형상 변경 근거가 없으면 새 사진/Mask를 관측으로 받아 기존 Manifest를 재사용한다. 생성 Fingerprint와 원 입력 SHA는 그대로 두고 새 관측 이력을 분리한다. 실측/형상/Material 변화는 해당 그룹을 검토한다. Material 차이는 material_variant 또는 별도 Group/Asset으로 처리한다. Group 분리는 필요한 Object 참조만 새 Asset으로 옮기며 원 USDA는 보존한다.

Blender에는 지정 입력과 설치 런타임만 제공한다. host 전체 root/home/인증 파일/환경변수 접근을 전제로 한 스크립트를 작성하지 않는다. 입력 Texture는 Path(__file__).parent / 'inputs' 안에서 읽는다. 상세 Config와 Sandbox/캐시 조건은 AUTO_SCENE_FITTING.md의 최신 Asset Group 절을 따른다.


## v3 모델링 요청과 재사용

사용자의 `검토 후 새 모델링`은 기존 캐시/Manifest보다 우선한다. Group별 modeling_request_id를 저장하고 성공한 Asset 등록 즉시 완료 처리한다. 실패 후에는 미완료 그룹만 다시 실행한다. 새 요청은 새 불변 Version이며 과거 USDA를 덮어쓰지 않는다. 명시 Manifest 선택은 과거 관계 미확정만 해소하고 실측 충돌·파일 무효·관측 수량 문제를 숨기지 않는다.

메모에서 동일 제품이라고 명시한 문장을 확인했으면 다시 동일성 질문을 만들지 않는다. Mask가 모호하면 제품 공유 관계와 구별하여 Association만 검토한다. 기존 Scene의 자산 선택을 오래된 자동 캐시로 되돌리지 않는다. Category만 같은 새 Object에 기존 자산을 임의 연결하지 않는다. 새 사진에서 형상/무늬 차이를 발견하면 형상 제약·Material Variant·명시 새 모델링으로 표현하며 단순 이동·회전을 그 근거로 삼지 않는다. 실제 함수·구성 예와 제한은 AUTO_SCENE_FITTING.md의 v3 절을 따른다.


## Workspace 소유권과 현재 메모

같은 Workspace의 여러 Scene은 공용 Library의 정확한 ID/Version을 선택해 참조한다. 새 Scene에 같은 USDA를 매번 복제/모델링하지 않는다. Project별 Input/Capture/q·Camera·메모·Pose·Config는 공유하지 않는다. 기존 Project 내부 Library를 강제 이동하거나 과거 Revision을 갱신하지 않는다. `object-asset publish --manifest ...`는 검증한 Legacy 버전을 공용 Library에 복사할 뿐 Scene 참조를 전환하지 않는다. 다른 Workspace Clone은 사용 버전만 옮기고, Export는 필요한 Closure를 독립 Package에 고정한다.

현재 메모는 `input/scene_memo.txt` 하나이며 `evidence.scene_memo`로 읽는다. `briefs/current_brief`는 canonical 파일이 없는 Legacy의 최소 읽기 복원에만 사용한다. Codex가 현재 원문과 사진을 해석해 Object/Group·관계 출처·정확한 인용문·변경 종류를 반환한다. Python은 SHA/구조/인용문 존재만 검사하고 자연어 의미를 다시 분류하지 않는다. 인용문 존재는 의미/물리 동일성 증명이 아니며 `semantics_verified=false`다. 과거 인용문을 새 메모 SHA로 자동 재결합하지 않는다. 메모 변경 후 새 Codex 해석을 요청하고 영향받는 Group만 검토한다. Object 표는 Config만 존재하는 미모델링 Object도 복원하며 목록·Group·Mask·요청·선택 자산을 유지한다. API/응답 Schema/CLI는 AUTO_SCENE_FITTING.md의 단일 자유 메모 절을 따른다.


## 현재 연속 실행과 Task 연결

```bash
python -m real2sim_builder.cli reconstruct PROJECT --candidate NAME --run-modeling --max-modeling-calls 6 --max-review-calls 3
python -m real2sim_builder.cli refit-pairs PROJECT --candidate NEW --scene-state LAYOUT --run-modeling
```

분리된 Codex는 매 호출마다 `BUILDER_GUIDE.md`를 먼저 읽은 뒤 분석 Schema 또는 `{"script":"author.py"}` Schema를 따른다. 가이드는 사용자 입력 경로에서 읽지 않는다. 가이드 SHA가 달라지면 이전 분석 응답을 현재 지침으로 실행한 응답처럼 재사용하지 않는다. 기존 Asset은 문서 변경만으로 자동 재제작하지 않는다. 개별 child timeout·오프라인·Sandbox·최선 checkpoint 보존은 유지한다.

Memo의 Task는 Codex가 Object ID에 연결한 typed intent로 반환한다. 현재 지원하는 pick-place는 기존 Registry/Annotation/DataGen/Evaluation 함수를 재사용하며 unsupported 관측/Task는 `NEEDS_IMPLEMENTATION`으로 남긴다. 매 Step에 Codex를 호출하지 않는다. 준비된 물리 실행 설정은 Python `export_revision(..., engine_config={...})`로 함께 등록할 수 있고, 설정 없는 검토용 Export를 자동 물리 실행 승인으로 승격하지 않는다.
