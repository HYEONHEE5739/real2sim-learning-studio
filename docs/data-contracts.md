# Scene·Recipe·Episode·실행 기록 데이터 계약

2026-10-25 최종 결정: 새 플랫폼 개발 기준은 **Isaac Sim5.1 / Isaac Lab2.3 / LeRobot0.4.1 / MuJoCo3.3.7**이다. 업그레이드는 진행하지 않는다. 최신 버전 조사는 참고 이력이며 신규 환경 분리·분리 추론·업그레이드 대응 코드는 개발 범위에 포함하지 않는다. 기존 UI/엔진 worker의 필요에 따른 프로세스 분리는 유지한다.

2026-10-25 보완: MuJoCo Finger Collision을 새 실행 패키지에 포함하고 manifest.json의 내부 상대 path/크기/SHA로 등록한다. 로더도 해당 패키지 root에서 해석하며 기존 repo의 절대 경로 fallback을 사용하지 않는다. 다른 경로·기존 repo 미노출 조건에서 loading/source hash/contact 자료를 검증해야 한다. 기존 v8은 그대로 둔다.


이 자료를 읽고 기록하는 함수의 입력·출력·오류·commit/Resume·UI 메시지 계약은 [API·Interface 명세](interfaces.md)에 구체화한다. 아래 예시는 저장 의미를 설명하며, 검증된 Schema 구현이나 실행 결과를 뜻하지 않는다.

2026-10-25: [S01 Scene 파일 계약](s01-scene-package.md)과 [S02 Frame/보정 관계](s02-frames-calibration.md)를 구현했다. 현재 reference Frame Graph와 Calibration 선언/fit binding을 검증한다. [T01](t01-task-registry.md)에서 명시 Task 목록·선언·dataclass 파라미터/Scene ID 참조 검증을 구현했다. [T02](t02-pick-place.md)의 v8 순수 판정/상태·입력 필드/등록과 B01 phase 대조도 구현했다. [T03](t03-placement-reset.md)의 v8 bbox Fixed/Random·RNG/검사도 구현했다. [T04](t04-collision-contact.md)의 지원 다면체/평면 접촉 배치도 구현했다. [D01~D04](episode-data-bundle.md)에서 Episode 저장/영상·변환·Resume/참조 계약의 파일 범위를 구현했다. [R01~R03](recipe-execution-bundle.md)의 저장 Recipe/준비·로컬 worker/IPC 기반도 구현했다. 실제 v8 Scene 패키지 변환·엔진/학습/장치 stage 실행은 미구현이다.

작성일: 2026-10-25. [통합 아키텍처](architecture.md)의 구현 전 상세 설계다. 예시의 파일·함수 이름은 새 계약 제안이며 아직 실행할 수 있는 파일을 생성하지 않았다. 예시용 Scene 경로는 실제 변환된 패키지 경로가 아니다.

## 1. 계약을 나누는 기준

| 자료 | 작성자 → 소비자 | 저장 제안 | 의미 |
|---|---|---|---|
| 편집 프로젝트 | Builder → Builder | 기존 편집 기능을 정리한 프로젝트 자료 | 후보/증거/미완료 작업; 실행 Revision과 구분 |
| 실행 Scene | Builder → Workbench/개발자 | JSON + native Asset | 불변 Revision, 기준 Geometry/Calibration |
| Capture 자료 | Workbench → Builder | 작은 JSON index + 원본 이미지/측정 파일 | 타임스탬프·장치/모델 identity·measured/command·좌표/단위·원본 hash |
| Recipe | 사용자/UI → worker | YAML | 한 단계의 선언, 자체 계산 언어 없음 |
| 실행 기록 | worker → UI/재현/Resume | JSON 요약 + JSONL 이벤트 + 저장 YAML | 실제 사용 설정/입력 identity/오류/진행 |
| Episode | Source/Annotation/DataGen → 후속 단계 | JSON index + HDF5 배열 + 영상 | 기록 시점·재생 상태·Annotation 보존 |
| 공식 학습 자료 | 변환/외부 → LeRobot | 공식 Dataset/Policy 형식 | 프로젝트 전용 Reader 없이 사용 |

JSON/YAML이라고 모든 것을 문자열 딕셔너리로 넘기지 않는다. 로딩 시 검사하고 계산에는 typed dataclass 또는 배열/수치 인자를 사용한다. 별도 객체 계층을 다중 변환하지 않는다.

## 2. Scene 패키지의 실제 파일 제안

v8의 profile.json은 9,926 bytes, task.json은 6,211 bytes, physics.json은 8,788 bytes, manifest.json은 33,231 bytes였다. Object·frame 정보는 함께 조회되며 작고, 기존 profile/task/physics에는 중복·Workflow 의미가 섞여 있다. 따라서 5개 책임을 5개 파일에 기계적으로 분리하지 않는다.

```text
scene_id/revision/
  scene.json                 # Object/frame/Geometry/Joint/엔진 설정/검증 요약/참조
  calibration.json           # 보정 record와 적용 의미·모델 identity·근거 참조
  manifest.json              # 실제 파일 목록과 SHA-256
  assets/
    robot/                   # 원본 identity용 URDF, 실행용 보정 자산, collision 부품
    scene/                   # USD/MJCF, mesh, texture, object fragments
  calibration/               # 실행에 필요한 encoder/camera 등 실제 자료
```

`scene.json`에 Object/frame/검증 요약을 묶고 Calibration을 분리한다. Calibration은 장치/모델 identity·적용 순서에 대한 독립 검토 대상이며 여러 Object가 참조한다. 파일 목록은 양이 더 많고 자동 생성되므로 manifest로 분리한다. 원본 사진/실험 증거는 모두 포함하지 않고 ID/SHA-256/보존 위치를 참조한다. 이 세 파일은 현재 데이터 기반 제안이며 대형 Scene에서 실제 이점이 생기면 Schema revision으로 분할할 수 있다.

### scene.json 필드

| 필드 | 내용 / 불변 조건 |
|---|---|
| `schema_version`, `scene_id`, `revision` | 문법 버전과 Scene identity; ID와 디렉터리명은 별개 |
| `units` | length=m, angle=rad, time=s, mass=kg; 카메라 K는 pixel |
| `frames` | frame ID → parent, `T_parent_from_frame` 4×4, 기준 상태 의미 |
| `objects` | ID → name, role, frame, Geometry/Collision/Physics/Joint, engine bindings |
| `robot` | 모델/실행 자산 참조·관절 순서·기준 base·명령/관측 매핑 참조 |
| `cameras` | resolution, optical/mount frame, intrinsics/distortion 보정 record 참조; K 수치 중복 없음 |
| `supports` | 작업면 ID, frame, plane/영역, 배치 제약 참조 |
| `engines` | Isaac/MuJoCo 자산 진입점·실행 물성/센서 조건·시간 간격 |
| `calibration` | 상대 경로 `calibration.json`; 보정 값 중복 없음 |
| `manifest` | 상대 경로 `manifest.json` |
| `validation` | execution/geometry/physics/calibration 검증 상태와 보고서 참조 |

role은 `robot`, `camera`, `environment`, `task_object` 등 생성 선택 책임을 표현한다. 환경 role을 영구 정적 물체로 제한하지 않는다. Joint가 있는 문/서랍도 표현 가능하다. 실행 중 움직인 pose를 기준 Metadata에 써 넣지 않는다.

Object Geometry는 visual과 collision을 구분한다. 각 collision part는 primitive 파라미터 또는 파일/엔진 형상 참조, 로컬 Transform, scale를 가진다. 동일 mesh 바이트는 한 번 보관한다. 엔진의 convex decomposition이 다르면 engine binding에 다른 collision representation을 명시한다. Placement 판정이 과거 치수로 계산했다면 그 치수는 `task_geometry`의 의미 있는 파라미터로 보존하고 새 collision mesh에서 임의 재추정하지 않는다. T02의 task_geometry 소비 필드는 dimensions_m와 컵의 wall_m/bottom_diameter_m다. 검증된 Scene에서 private 계산 cache로 연결하고 Recipe 필드로 중복 입력하지 않는다. grasp_inputs/placement_points는 실행 중 수치 전달 자료이며 새 Metadata나 Episode 필드를 자동 생성하는 계약이 아니다.

같은 local Transform을 frames와 Geometry 양쪽에 저장하지 않는다. 이름 붙인 frame이 있으면 Geometry는 frame ID를 참조하고, 독립 좌표계로 조회할 필요가 없는 형상 offset은 해당 Geometry 안에 한 번만 둔다. camera K·distortion의 수치 원본은 Calibration record/참조 파일이며 camera 항목은 그 ID를 사용한다. 엔진이 요구하는 파생 K는 로딩 시 계산하고 적용 알고리즘/결과를 실행 기록에서 추적한다.

엔진 binding은 Object별로 명시한다. Isaac은 Asset 상대 경로·prim 경로·rigid/articulation/contact 관계를, MuJoCo는 MJCF fragment/entry와 body/joint/geom 이름을 가진다. 하나의 Object에 여러 geom을 허용한다. 실제 엔진 lookup과 대조하고 누락·중복 binding은 오류다. 비선택 Object를 제거할 수 없는 통짜 Asset은 export에서 선택 가능한 구조로 준비한다. 숨기기나 충돌 비활성을 미생성의 대체로 사용하지 않는다.

Joint 정보는 parent/child·type·axis·origin·limit·기준 joint state를 명시한다. 동적 joint frame의 Metadata Transform은 **기준 상태**이며 실시간 값은 엔진에서 얻는다. Task가 joint 값을 사용할 때 관절 이름과 단위를 검증한다.

예전 `cup_a → cup_a_visual` 대응은 새 logical Object `cup_a`의 visual/collision binding으로 명시한다. 문자열 규칙으로 `_visual`을 붙여 추측하지 않는다. 기존 기록의 ID 변환표는 migration 보고서에 남긴다. 블록 ID는 가능한 한 cube_red/blue/green을 유지한다.

### Transform과 좌표 규약

열벡터를 사용하고 `p_parent = T_parent_from_frame @ p_frame`이다. 행렬은 JSON에서 행별 배열로 저장한다. 오른손 좌표계이며 원본 optical 축 규약을 명시한다. 4×4 행렬이 기본 자세의 유일한 기준이고 quaternion/Euler를 중복 저장하지 않는다.

S02에서 Frame의 parent/T_parent_from_frame/state=reference 및 선택 dynamic_source를 검증한다. world가 유일 root이며 그 행렬은 canonical identity다. parent 누락/cycle/별도 root는 오류이고 dynamic_source의 기준값을 현재 pose로 대체하지 않는다. current 요청은 엔진 소유 상태를 사용해야 하며 공통 resolve_transform은 거부한다. Object/Robot/Camera/Support/Geometry의 명시된 frame 참조와 local_transform도 검증한다.

Recipe에서 명시 자세는 `orientation: {frame: <id>, quat_wxyz: [...]}`로 한다. quaternion은 finite·단위 길이 검사 후 사용하고 xyzw/wxyz 자동 추측을 하지 않는다. 내부 SciPy 호출에는 필요한 순서 변환을 한 지점에서 명시한다. 기본 자세 생략 시 Object 기본 frame chain으로 자세를 얻으며 Recipe 위치 frame으로 숫자를 재해석하지 않는다.

카메라 optical→MuJoCo camera convention, Isaac render intrinsics 등 기존 실행 변환은 엔진 코드가 소유한다. 원본 K/Transform을 새 Metadata로 바꾸며 렌더 편의를 위해 원본 값을 덮어쓰지 않는다.

### Calibration 적용 계약

`calibration.json`은 `schema_version`, `records`(보정별 ID), `evidence`(ID/SHA-256/location)를 둔다. 각 record는 다음 의미를 가져야 한다.

| 항목 | 요구 |
|---|---|
| 종류/대상 | encoder mapping, camera intrinsic/extrinsic, robot residual 등 구분 |
| 모델 identity | 원본 모델/보정된 실행 모델을 각각 식별; 단순 경로 비교 금지 |
| 입력/출력 의미 | raw counts, model radians, 관측/명령 구분, 관절 순서 |
| 변환 | 공식/알고리즘 version과 수치 파라미터; YAML/JSON 실행식 없음 |
| 적용 상태 | `baked`(실행 Asset에 반영) 또는 `runtime`, 단계·적용 대상·순서 |
| 결과/근거 | 실행 필수 값/파일, 외부 증거 ID, verified/estimated 등 원래 상태 |

원본 보정 프로필은 Calibration 자료로 보존하며 읽는 값의 유일한 원본 위치를 정한다. 같은 수치를 JSON record와 원본 파일 양쪽에 독립 작성하지 않는다. 기록된 적용 모드가 맞지 않으면 중단한다. v8 precision residual은 geometry 보정이지 관절 명령에 다시 더할 offset이 아니다. 기존 encoder branch 선택·round/int 양자화·역변환·limits-only model 허용 조건도 알고리즘의 일부다.

S02는 baked/result Asset SHA, runtime phase/input/output/order_index, input_calibration_ids의 dependency/순서·Frame/joint/model identity와 중복 적용을 검사한다. Leader/Follower 관측은 다른 input_space, 관측/명령은 다른 phase다. fit 근거 dependency는 그 보정이 결과 Asset에 같이 baked되었다는 뜻이 아니다. v8 precision_bound_residual의 mapping fingerprint는 실제 Encoder 파라미터와 일치해야 하며, file-based 값은 load_scene에서 읽어 Manifest bytes SHA도 확인한다. direct validate_scene은 file payload를 읽지 않으므로 이를 완료된 파일 검증으로 간주하지 않는다. 실제 계산/단계 연결과 Encoder 모델 재결합 이관은 후속 구현이다.

캡처에서 생성한 원본 장치 프로필을 Builder가 임의 재추정하지 않는다. Builder는 Scene 정합 결과와 장치 프로필 identity를 묶고 runtime 적용 여부를 명시한다. 실행기는 패키지의 보정과 실제 장치 설정의 호환성을 확인한다. 시뮬레이션 완전성은 실물 장치 연결 성공을 뜻하지 않는다.

[B03 근거](b03-calibration-device.md)에 따라 다음 의미를 보존한다. 이는 필드를 중복 추가하거나 기존 형식을 복사하라는 요구가 아니다.

- raw Present_Position은 이미 homing 적용된 count, native는 팔 degree/그리퍼 percent, model은 JOINTS 순서의 6 rad다. 프로필 JSON의 key 순서는 배열 순서가 아니다. observation·requested·encoded/SDK-returned goal·physical measured를 구분하고 SDK 반환을 실물 도달 ACK로 기록하지 않는다.
- saved profile의 원 모델 identity와 limits-only 메모리 binding의 실행 identity·persisted=false를 구분한다. 동일 수치/프로필을 중복 저장하지 않으면서 필요한 정확한 모델 증거를 패키지에 포함한다. URDF baked `R_origin × R_axis` 및 USD counterpart와 residual fitting의 mapping identity를 유지하고 command에 재적용하지 않는다.
- raw K/distortion, render K, optical mount와 runtime 동적 camera pose의 출처를 명시한다. 카메라/관절 시각은 host read interval이며 exposure/hardware sync 미가용이다. Capture의 quaternion xyzw와 Episode wxyz도 계약별로 구분한다.
- REVIEWED_MANUAL·physical_verified=false, runtime READY와 Builder UNVALIDATED를 각각 보존한다. Stop/cleanup·configure/send 실패의 effect가 불명확하면 오류/미확정으로 기록하며 토크 해제·실물 Task 성공을 만들어 채우지 않는다. 실제 장치/새 변환·엔진 적용 검증은 미완료다.

### 무결성·Revision

S01에서 Manifest를 `schema_version: 1`, `files: [{path, size_bytes, sha256}, ...]`로 구체화했다. Scene ID/Revision은 scene.json에 두고 Manifest가 그 파일을 hash로 고정한다. 실행 파일 참조는 `asset_path`/`asset_paths`, 추가 의존성은 `required_files`, 보정 파라미터 파일은 `parameters_file`이다. 이 필드들은 모두 package root 기준 상대 경로이며 Manifest 등록이 필수다. `parameters_file`과 inline `parameters`는 하나만 사용한다. prim_path·body/joint 이름·일반 문자열을 파일로 추측하지 않는다.

모델에 결합된 Calibration의 source_model_sha256/execution_model_sha256 및 선언된 input_asset_sha256는 해당 바이트의 Manifest 등록을 검사한다. Finger Collision, contact pad 및 보정 근거 URDF도 실행 소비 Metadata에 선언해야 한다. native 파일 내부에만 있고 Metadata·Manifest 양쪽에서 빠진 참조를 S01이 자동 발견하지 않으며, 공식 parser를 이용한 Export closure와 실제 loader 검증은 계속 후속 범위다.

manifest에는 정규화된 상대 경로·파일 크기·SHA-256을 중복 없이 기록한다. symlink가 패키지 밖 실행 파일을 가리키면 이동 가능한 export로 승인하지 않는다. 내부 참조는 실제 엔진의 기준 파일/meshdir 규칙대로 해석해 패키지 안에 닫혀 있어야 한다.

S01은 이동성을 위해 symlink target도 상대 경로만 허용한다. 현재 패키지 내부를 가리켜도 절대 target은 이동 후 원래 위치에 의존하므로 거부한다. 상대 target 역시 최종 regular file이 패키지 내부에 있어야 한다.

해시 순환을 피하기 위해 manifest는 자기 자신을 파일 목록에서 제외하고 scene.json/calibration.json/실행 자산을 포함한다. 실행 기록에 manifest 파일 자체의 SHA-256을 남겨 전체 목록을 고정한다. 동일 패키지를 이동하면 상대 경로/내용 hash가 같으므로 identity는 유지된다. Revision 레이블만 같고 hash가 다르면 오류다.

Scene registry DB를 만들지 않는다. 사용자가 지정한 패키지 위치 또는 설정된 소수 검색 루트에서 정확한 ID/Revision/hash를 찾아야 한다. 없으면 경로 선택을 안내할 수 있으나 최신 Revision으로 대체하지 않는다. 실행은 원본 패키지에 파일을 쓰지 않는다. 선택 물체 Scene 조합은 작업 임시 공간/메모리에서 수행한다.

## 3. Recipe 계약

### 공통 규칙

- `schema_version: 1`, `stage`, `inputs`, `execution`, `output`을 공통 축으로 한다. 선택 필드 생략과 빈 값은 구분한다.
- engine은 시뮬레이션 단계에서 `isaaclab` 또는 `mujoco`; Training 등에서는 입력하면 관련 없는 필드 오류로 안내한다.
- unknown field/중복 key/잘못된 type/NaN/Infinity, 임의 YAML object tag, include/상속/표현식은 허용하지 않는다. scalar/list/mapping만 해석한다.
- Recipe의 상대 경로는 **저장된 Recipe 파일의 부모** 기준이다. Scene 안 경로는 Scene 계약 기준이다. 사용자가 셸 문자열을 실행 명령으로 넣지 않는다.
- Scene ID는 Metadata에서 읽고 run이 정확한 Revision/hash를 고정한다. Source/DataGen 신규 실행은 Scene 입력 필요; Annotation은 입력 Dataset의 Scene identity를 기준으로 해석한다. 명시 Scene 경로가 있으면 동일 identity여야 한다.
- objects는 생성 목록이다. 생성 대상이 없거나 생략됐을 때 임의 기본 블록을 추측하지 않는다. 신규 v8 제공 Recipe에는 목록·배치 규칙을 명시한다. 과거 경로의 기본 동작은 변환할 때 명시 설정으로 옮겨 보존한다.
- 기준 환경은 목록에서 제외되어도 유지한다. task_object만 선택한다. 제거한 물체를 함수가 참조하면 오류다.
- DataGen IK는 고정 **Pinocchio DLS + Best Effort**다. `ik_solver`, `ik_failure_policy`, DLS 파라미터·점프 한도 override를 Recipe 필드로 제공하지 않는다. 과거 옵션을 포함하면 해당 field의 `RECIPE_INVALID`로 시작을 막으며, 값이 고정 정책과 같아도 무시하거나 자동 변환하지 않는다. Task 함수 등록도 다른 IK 경로를 선택하는 우회 수단으로 사용하지 않는다.

### 단계별 입력/출력

| stage | 입력·필수 의미 | 허용 특수 필드 / 결과 |
|---|---|---|
| `source` | Scene, 장치 매핑 | engine/objects; source Episode, 성공 gate 불필요 |
| `annotation` | source Dataset, 기록 Scene | engine/functions, auto/manual·환경 수; annotated 새 Dataset. objects 재배치 금지 |
| `datagen` | annotated Dataset + 호환 Scene | engine/objects/functions, seed·목표 성공수·시도 budget; 생성 Episode/실패 시도 |
| `simulation_evaluation` | Policy + Scene | engine/objects/functions, Episode 수·시간 제한; 결과/영상/지표 |
| `real_evaluation` | Policy + 장치/관측/보정 계약 | engine 없음, 실물 기록; Scene 계약이 필요하면 inputs로 명시 |
| `convert`, `merge` | 내부 Episode 또는 공식 Dataset 목록 | 공식 Dataset feature mapping/출력 repo ID |
| `train` | 공식 Local/Hub Dataset, 선택 Policy/공식 config | Scene/engine/objects/functions 불필요; checkpoint/log |
| `offline_validation` | Dataset + Policy | loss batch/샘플 결과 |
| `hub_upload`, `hub_download` | Dataset/Policy 경로·repo ID/commit | 공식 Hub 결과; credential 값 기록 금지 |
| `capture`, `precision_calibration`, `real_sim` | 장치/촬영·프로필 입력; real_sim은 Scene | 실제 기존 역할에 맞는 필드; 결과 자료/프로필. 모터 명령은 명시 실행 |

Curation의 선택/재생은 UI 상호작용이다. 저장/분할 작업은 선택된 Episode ID 목록을 결과에 기록해 재현한다. 이를 임의 Task 실행으로 추상화하지 않는다. 수동 Annotation의 mark/pause/skip도 실행 중 제어 메시지이며 Recipe를 매 프레임 다시 저장하지 않는다.

### 배치와 역할별 함수

각 Object의 `placement`는 `function` + `params`로 표현한다. 제공 함수 `placement.fixed_xy`/`placement.random_xy`를 기본으로 하고 새 Reset도 같은 등록 방식으로 추가한다. `functions`는 stage의 signal/acceptance/success/metrics 등 **의미가 정해진 역할**에 등록 함수를 연결한다. 사용자 YAML이 hook 순서나 엔진 step을 프로그래밍하지 않는다.

`params`는 함수가 선언한 타입·필수값·Object/frame/support 참조 계약으로 검사한다. 단계별 함수 역할에는 반환 종류(boolean/event/pose/metric)를 검사한다. 배열 shape/단위/환경 인덱스도 호출 계약이다. UI에 새 함수 전용 입력 폼을 만들지 않는다.

v8은 제공 Recipe에서 `rules: v8_preserved`를 명시한다. 이 규칙은 v8 보존 계산·3mm 여유·margin/separation을 정의하는 제공 기능이며 Scene 기준 형상은 Metadata에서 읽는다. 새 일반 규칙 `collision_contact`는 실제 collision Geometry/자세로 계산한다. v8에 자동 교체하지 않는다. 규칙 이름·정의와 사용 버전을 결과에 기록한다.

### Source 예시

```yaml
schema_version: 1
stage: source
engine: mujoco
inputs:
  scene: ../scenes/scene2_builder/v8_migrated/scene.json
  device_profile: ../devices/leader.json
objects:
  cube_red:
    placement:
      function: placement.random_xy
      params:
        frame: workspace
        support: marker_top
        rules: v8_preserved
execution:
  episodes: 10
  seed: 42
output:
  directory: ../runs/source_red_001
```

`marker_top`는 새 계약에서 export할 support ID 제안이다. 실제 v8 marker shape/Transform으로 도출·검증해야 하며 현재 존재하는 ID라고 주장하지 않는다. 기본 자세는 Builder Metadata에서 얻는다. 실행은 선택하지 않은 blue/green을 생성하지 않는다.

### Annotation 예시

```yaml
schema_version: 1
stage: annotation
engine: isaaclab
inputs:
  dataset: ../runs/source_red_001/dataset
functions:
  acceptance:
    function: pick_place.v8_annotation
    params: {object: cube_red, target: cup_a}
execution:
  mode: manual
  num_envs: 1
output:
  directory: ../runs/annotated_red_001
```

입력 Dataset의 Scene identity로 정확한 패키지를 찾는다.
동일 엔진 재생과 cross-engine Annotation을 구분해 기록한다. cross-engine도 동일 Scene/Calibration Revision을 사용하되 엔진별 실제 상태 복원 가능성·제어 의미를 검사한다. MuJoCo native solver 배열을 Isaac에 그대로 대입하지 않는다. 기존 canonical 상태 replay를 유지하며 엔진 간 bitwise 동등성을 주장하지 않는다.

### DataGen 예시

```yaml
schema_version: 1
stage: datagen
engine: mujoco
inputs:
  scene: ../scenes/scene2_builder/v8_migrated/scene.json
  dataset: ../runs/annotated_red_001/dataset
objects:
  cube_red:
    placement:
      function: placement.fixed_xy
      params:
        frame: workspace
        support: marker_top
        xy_m: [0.02, -0.01]  # 형식 예시; 실제 배치 검증 필요
        rules: v8_preserved
functions:
  signals:
    grasp:
      function: pick_place.stable_grasp
      params: {object: cube_red}
  acceptance:
    function: pick_place.v8_datagen
    params: {object: cube_red, target: cup_a}
execution:
  target_successes: 100
  max_attempts: 1000
  seed: 43
output:
  directory: ../runs/generated_red_001
```

max_attempts는 생성 budget 예시이며 Random XY 물체별 1,000회와 다른 카운터다. 기존 생성 seed 규칙(명시 seed와 Source seed 관계 포함)과 budget 계산을 보존한다. DataGen subtask 계획·offset·selection은 등록된 제공 Task의 선언에서 얻고 신규 Task는 자신의 선언을 추가한다. 위 acceptance는 이미 계산된 동일 grasp tracker의 latch를 읽고 중복 tracker를 생성하지 않는다.

위 예시는 IK 선택 필드 없이 **Pinocchio DLS + Best Effort**로 실행한다. 고정 수치는 [상세 SPEC](../SPEC-simulation-workflows.md#datagen-ik-고정-계약)에 정의하고 시스템이 해석된 실행 기록에 넣는다. 유효한 candidate의 적용은 성공 Episode 채택과 별개이며, `pick_place.v8_datagen`은 기존 StableGrasp latch AND Placement를 유지한다.

### Simulation Evaluation / Training 예시

```yaml
schema_version: 1
stage: simulation_evaluation
engine: isaaclab
inputs:
  scene: ../scenes/scene2_builder/v8_migrated/scene.json
  policy: ../models/act/pretrained_model
objects:
  cube_red:
    placement:
      function: placement.random_xy
      params: {frame: workspace, support: marker_top, rules: v8_preserved}
functions:
  success:
    function: pick_place.v8_evaluation
    params: {object: cube_red, target: cup_a}
  metrics:
    function: pick_place.v8_metrics
    params: {object: cube_red, target: cup_a}
execution:
  episodes: 20
  seed: 44
output:
  directory: ../runs/evaluation_001
```

```yaml
schema_version: 1
stage: train
inputs:
  dataset: hf://owner/dataset
  training_config: ../training/act.json
execution:
  mode: scratch
output:
  directory: ../models/act_run_001
```

training_config는 공식 LeRobot config다. 실행기는 Dataset·output 등 중복 필드의 불일치를 오류로 처리하고 실제 사용한 공식 config를 결과에 기록한다. hf 경로는 실행 준비에서 공식 snapshot으로 resolve하고 commit을 기록한다. CLI 자체를 YAML에 shell command로 노출하지 않는다. 외부 Dataset에 Scene/Task provenance를 요구하지 않는다.

Training Recipe는 공식 Trainer 설정을 전달하며 UI 그래프용 custom training loop·LR scheduler·optimizer·validation hook을 선언하는 필드를 만들지 않는다. 공식 config에서 지원하는 로깅 설정을 우선 사용하고 MiniVLA 전용 학습 관리/지표 Schema를 가져오지 않는다.

Offline Validation은 별도 Recipe에서 Dataset과 저장된 Policy/Checkpoint를 선택하고 별도 output/run identity로 실행한다. Training config에 프로젝트 검증 루프를 삽입하거나 자동으로 Offline Validation을 실행하지 않는다. 공식 Trainer 기본 검증 결과가 있다면 별도 Offline 결과와 출처를 구분한다.

## 4. 배치 계산의 상세 의미

Fixed XY는 물체 **원점의 X/Y**를 지정 frame에서 고정한다. 평면 작업면에서는 지정 frame의 +Z 방향으로 원점을 이동시켜 collision 최저점이 작업면에 닿게 하는 계산을 사용한다. 작업면 법선 n과 입력 frame Z축 e의 내적이 0에 가깝거나 음수라 해석이 부적합하면 오류다. World/Workspace의 XY를 서로 같은 수치로 취급하지 않는다.

수학 후보: 작업면을 `n·p=d`, z=0일 때 모든 충돌점의 world 위치를 q로 두면 `z=(d-min(n·q))/(n·e)`다. Geometry local transform·scale·물체 자세를 q에 반영한다. primitive는 해석적 support 값을, convex/mesh는 실제 충돌 표현의 support 값을 사용한다. 이것은 명시 XY를 유지하는 평면 배치이며 임의 비평면 지형/속이 빈 지지면 전체를 해결하는 알고리즘은 아니다. 미지원은 명시 오류 또는 등록된 별도 배치 함수가 필요하다.

실제 접촉 Geometry가 엔진마다 다르면 계산한 z도 다를 수 있다. 두 엔진의 차이를 기록하고 원본 v8 동작과 각 엔진 안에서 비교한다. v8 보존 경로는 기존 높이+3mm 공식을 유지한다. 일반 규칙의 검사나 Geometry를 보존 경로에 조용히 덧씌워 성공률을 바꾸지 않는다.

Random XY는 기존 uniform 분포·범위 계산·간격·배치 순서를 보존한다. 일반 Geometry 규칙에서는 허용 영역 내 후보를 뽑고 footprint/충돌 검사를 수행한다. Fixed를 먼저 배치하고 Random을 검사하는 혼합 규칙의 RNG/순서 영향은 이관 검증에 포함한다. 물체별 1,000회 소진은 작업 중단이며 이미 완료 데이터는 유지한다. 초기 겹침, metadata 오류, IK 실패, 수행 실패는 다른 오류다.

T03 지원 범위: v8_preserved의 축 계산 기준은 supports[id].placement_frame_id로 명시하고 support body는 object_id로 참조한다. 수치/기하를 중복 저장하지 않는다. v8 전용 Task 함수는 그 기록 frame에서만 동작한다. 다른 입력 frame과 일반 Collision Geometry 접촉 높이는 T04의 별도 collision_contact 함수가 지원 범위 안에서 처리한다. Fixed에 적용하는 bbox separation은 새 선행 검사이며, 원래 pose-only validator/실제 엔진 검사가 이미 수행했던 것으로 기록하지 않는다. batch 카운터·Robot reset·데이터 보존은 실행기/Writer의 후속 책임이다.

T04 구체 계약: 일반 support는 `{frame_id, region_xy_m}`이며 frame의 z=0이 평면, +Z가 법선이다. region은 반시계 convex polygon이다. object.collision은 실제 부품 목록으로 box(kind=primitive, primitive=box, dimensions_m) 또는 mesh(kind=mesh, asset_path)를 받는다. 부품별 scale(기본 [1,1,1])과 frame_id 또는 Object-local local_transform을 사용한다. mesh Asset의 현재 지원 형식은 JSON `{schema_version: 1, vertices_m, triangles}`이며 Manifest에 등록된 폐쇄 convex triangle mesh여야 한다. 원본 native Asset을 자동 변환하지 않고, 엔진별 실제 표현이 다른 경우 선택/동등성 확인을 후속 binding에 남긴다.

일반 높이는 여유 0m의 평면 접촉이다. Fixed/Random 모두 margin을 적용하고 부품별 투영 polygon의 거리로 separation을 검사한다. Random은 footprint가 들어갈 원점 영역을 계산한 뒤 입력 frame XY bounding rectangle에서 uniform 후보를 뽑고 영역·occupied 조건을 검사한다. 후보당 draw 1회, 최대 1000회이며 이 일반 규칙의 분포/RNG 소비는 v8과 다를 수 있다. v8 함수는 변경하지 않는다. 투영 검사는 보수적 2D 조건이고 물리 충돌/안정성 PASS가 아니다. curved primitive·concave 단일 mesh·비평면/구멍 support는 명시적 미지원이다. 상세 수치/자료/완료 경계는 [T04](t04-collision-contact.md)를 따른다.

## 5. Episode·Annotation·영상·Resume

### 공식 Native 저장 구성

```text
worker_run_directory/        # run.py의 status/events/Recipe, Dataset payload와 별개
native_dataset_directory/
  run.json                   # dataset_id/execution/closed, 작은 파일
  provenance.json.gz         # 한 번 보존하는 원 attrs/근거/문자열 진단
  .writer.lock
  .claims/<intent>.json      # 실행 의도 재전송/불명 상태
  attempts/<number>.json     # 예약 seed·attempt, 성공 상태는 sealed segment가 소유
  .staging/<intent>/         # 외부 완료 목록에 노출하지 않음
  segments/<order>-<intent>/
    data.hdf5                # 실제 공식 data/demo_N, 여러 Episode 가능
    segment.json.gz          # id/lineage/phase·영상 위치/성공과 attempt, 자체 array descriptor 아님
    media/demo_N/*.mp4       # 원본 bytes link 또는 명시 독립 copy
curated_v1.json              # source identity/선택/순서/범위/split만 저장
training_dataset/            # 명시 materialization 후 official Parquet·MP4·meta
```

공식 close와 저비용 header/known-count 검사, fsync 뒤 디렉터리 publish가 완료 기준이다. 별도 자체 index/배열 Descriptor/파일 SHA 재검사는 없다. 이전 published segment를 다시 열어 쓰지 않는다. 오류·SIGKILL에서 pending은 자동 채택하지 않으며 새 run Resume만 지원한다. Curation은 bulk payload를 복제하지 않고 학습 시 정확한 선택 rows만 공식 LeRobot으로 materialize한다. 원 MP4는 재인코딩 없이 offset 참조하며 동일 filesystem에서 hardlink한다. 독립 Export만 copy, 다른 filesystem에서 silent fallback은 없다.

원본 provenance와 S64/opaque JSON은 최소 압축 Metadata에 보존한다. 배열은 공식 HDF5 이외의 자체 bulk 포맷으로 포장하지 않는다. archive_only import는 기록에 없는 runtime identity/속도/requested/RNG state를 채우지 않으며 재생·Resume에 필요한 identity 부족은 차단한다.



### 의미 계약

| 필드군 | 필수 의미 |
|---|---|
| Dataset identity | schema, Dataset ID, 작성 run, 참조 Scene ID/Revision/manifest SHA, robot/보정 계약 |
| Episode identity | 고유 ID, source lineage, 완료 상태, 생성 seed/시도, annotations |
| initial_state | robot base/joint q/qd, objects pose/velocity, 기록된 필요한 엔진 상태·적용 시점 |
| time | control dt, physics dt/decimation, tick/timestamp, pre/post-step 명시 |
| observations | measured joint, EEF/object poses, 카메라 frame index, 각 frame/unit |
| commands | requested와 실제 clipped/applied joint targets 구분; controller target EEF |
| task inputs/events | contact 정보/추출 의미, grasp latch·subtask 경계·manual marks |
| outcome | physical success, annotation acceptance, 평가 metrics와 실패 분류 각각 |

관측 obs[t]는 command[t]를 적용하기 전인지 후인지 명시한다. 기존 Source/Annotation pre-step 기록과 post-step grasp update를 그대로 보존한다. LeRobot action으로 무엇을 변환하는지 명시하고 measured q를 target으로 조용히 바꾸지 않는다. 기본 gripper를 임의로 [0,1] 정규화하지 않는다.

### B02에서 확인한 필드 가용성과 기록 phase

2026-10-25 [B02 대응표](b02-episode-resume.md)와 [612개 필드 근거](evidence/b02/field-compatibility.json)를 적용한다. 실제 변환·새 Writer 검증 완료를 뜻하지 않는다.

- 기존값의 `recorded`, 근거를 포함한 `derived`, `unavailable`, `not_applicable`을 구분한다. 새 수집 단계에서 요구할 값과 과거에 없는 값을 분리하며, 누락 requested/applied 명령·측정 속도·RNG state·코드 hash를 가짜로 채우지 않는다. 필수 재생/Resume 정보가 없으면 해당 사용을 차단하고, 일반 열람/공식 학습에 불필요한 필드를 강요하지 않는다.
- `joint_targets`는 먼저 **기록된 모델 관절 target** 의미로 보존한다. Native Isaac Source는 float32 target을 기록·적용하지만, Isaac Annotation/Evaluation의 저장 target은 float64이고 실제 engine payload는 float32가 될 수 있다. command 기록 dtype·전달 dtype·phase를 명시하고, 엔진 cast로 도출한 값은 실제 기록된 applied telemetry와 구분한다. Native Isaac Source에는 `collection/requested_action`이 없으며 이를 적용값으로 복제하지 않는다.
- `actions`는 `[T,7]` TCP delta m/rotvec rad+절대 그리퍼 model rad다. `collection/state/action`의 그리퍼 fraction, 6관절 target, `collection/recorded_mimic_actions`의 step 전후 raw delta와 구분한다. 저장된 float32 pose에서 원래 Action을 재계산해 덮어쓰지 않는다.
- `states/joint_pos/joint_vel`은 Native Isaac Source의 post-step telemetry로 보존하고 pre-step observation과 합치지 않는다. initial velocity의 기본 0과 측정 0도 근거가 다르다. MuJoCo opaque state는 소유 backend/model/version/state_spec와 함께 보존하며 Annotation이 상속한 Source snapshot을 실행 엔진의 현재 snapshot으로 재해석하지 않는다.
- 자동 Annotation은 B01 MuJoCo physical grasp post tick 222→저장 frame 223, Isaac 221→222다. 수동 Annotation의 mark frame·Mimic boundary와 물리 최초 판정 tick은 별개다. 최종 post-step placement를 마지막 action frame에 표시한 경우도 event의 원천/phase를 남긴다. 일반 과거 signal을 한 칸 이동해 물리 tick을 만들어내지 않는다.
- 영상은 각 카메라 frame ordinal·원래 timestamp clock·상대 MP4 PTS·SHA로 연결한다. ordinal은 검증 후 도출 가능하지만 센서 동기 시각이나 손실된 미압축 RGB를 복원했다는 뜻은 아니다.

Annotation은 원본 Dataset을 수정하지 않고 새 결과를 만든다. 실제 재시뮬레이션에서 새 관측/영상이 만들어졌다면 원본과 동일하다고 참조하지 않는다. Curation의 순수 subset/annotation-only 부가 결과는 불변 input Episode를 ID/hash로 참조하여 큰 배열/영상을 복사하지 않을 수 있다. 공유용 독립 export 시 필요한 참조를 materialize하고 누락을 검사한다.

Resume는 이전 자료를 읽기 전용 입력으로 두고 새 run/segment를 만든다. Scene/Calibration/active objects/Task 함수·기록 의미·입력 Dataset identity를 비교한다. 기존 완료 Native segment는 새 출력에 hardlink하며 이전 파일을 재작성하지 않는다. Source partition 잠금, DataGen 동일 annotated input 요구 등 기존 규칙은 유지한다. RNG state/seed stream·completed budget 등 기존 재개에 필요한 값을 보존한다. 이는 Episode 경계 재개이며 실행 중 물리 상태의 임의 tick 재개를 새로 약속하지 않는다.

DataGen Resume에는 실제 IK 알고리즘·Best Effort 적용 의미·고정 파라미터·안전 조건·계산 코드 identity도 포함한다. 과거 SciPy/Strict/Hold run 또는 필수 IK identity가 확인되지 않은 run은 새 정책으로 이어 생성하지 않고 `RESUME_INCOMPATIBLE`로 거부한다. 과거 Episode 열람·변환·학습 사용이나 적합한 annotated 입력에서 시작하는 새 DataGen run까지 막는 규칙은 아니다. 과거 기록의 solver/policy 명칭·수치·실패를 새 값으로 다시 쓰지 않는다.

B02에서 실제 과거 `scipy_ls + best_effort` 생성 자료도 확인했다. 정책 이름이 Best Effort라고 신규 Pinocchio DLS와 같게 취급하지 않는다. 옛 `_resume`의 IK 누락→SciPy/Strict 기본값 대체 및 코드 identity 미검사는 이관하지 않는다. resume_to는 identity·완료/attempt history·호환 검사를 기존 Episode 복사나 새 commit **전에** 끝낸다. 역사적인 Scene/코드 hash가 없으면 현재 hash를 당시 기록으로 소급 기재하지 않는다.

Source의 기존 seed 규칙은 base seed+attempt이고 Resume에서 attempt는 완료 Episode 수로 다시 시작한다. 미저장/discard 시도와 RNG state 전체의 정확한 복원을 보장하지 않는다. DataGen은 완료 성공 수와 별개로 `max(history.attempt)`·성공/실패/중단·전역 attempt budget을 보존한다. source pool의 실제 HDF5 key 순서와 화면용 numeric Episode 순서도 분리한다. 동일 seed만으로 병렬 schedule·Reset RNG·Policy/영상 결정성을 주장하지 않는다.

기존 Native Annotation과 workflow Evaluation에는 이번에 확인한 Source/DataGen식 continuation 경로가 없다. 선택 데이터의 독립 replay/재실행과 Resume를 구분하고, 없는 기능을 이미 검증된 것으로 표시하지 않는다. 실패 attempt만 있고 완료 Dataset이 publish되지 않은 경우도 필요한 Native 완료/identity/history 없이 재개 가능 Dataset으로 꾸미지 않는다.

공식 학습 Resume는 공식 optimizer/checkpoint 상태를 사용한다. Scene을 사용하지 않은 학습 run에 Scene Revision을 억지로 요구하지 않는다.

## 6. 실행 기록과 오류 계약

`run.json`: run ID, stage, 상태, 사용한 Recipe SHA/정규화 config, 입력 자료 ID/hash/위치, Scene/Revision/manifest SHA(사용 시), Calibration identity, 엔진·라이브러리·Task 코드 identity, 출력, 시작/종료, 완료/실패/배치 시도 통계. 저장 Dataset의 run.json/provenance/공식 파일이 데이터 identity를 소유하며 worker 실행 기록은 그 identity를 참조한다. 별도 수동 Recipe 사본 관리가 필요하지 않다.

상태는 prepared/running/completed/cancelled/failed로 충분하다. Episode Task 실패가 곧 run failed는 아니다. 오류 사건에는 code, stage, Episode/Object ID, field path, expected/actual, 시도 횟수, 관련 입력 identity를 담는다. raw 예외 traceback은 로그에 남기고 UI에는 원인과 해결 위치를 먼저 보여준다.

초기 배치 한도 소진은 `PLACEMENT_EXHAUSTED`, Fixed 무효는 `INVALID_PLACEMENT`, Scene 누락/불일치는 `SCENE_REVISION_MISSING`/`SCENE_INTEGRITY_MISMATCH`로 구분한다. 정확한 코드명은 구현 검토에서 조정 가능하나 의미를 합치지 않는다. Grasp/Task/IK 실패는 기존 DataGen 분류와 budget을 따른다.

DataGen의 IK 진단에는 고정 알고리즘/정책 identity, 파라미터, 측정 seed/직전 적용 명령·candidate/적용 명령, native 수렴·반복 수·pose 오차/진단 통과, shape/finite/limits/jump 유효성 및 중단 사유를 남긴다. 기존 진단 단위·시점을 보존하며 같은 설정은 run/generation 계약에 한 번 기록하고 Episode가 참조한다. 이는 시스템 provenance이며 사용자 선택 옵션이 아니다. 미수렴·pose 오차 초과만으로 attempt를 실패 처리하지 않으며, 부적합 candidate는 미적용·실패 attempt로 기록한다. Task 성공은 StableGrasp AND Placement로 별도 기록하고 미완료/미채택 attempt를 성공 Dataset에 넣지 않는다. B01 SciPy + Strict와의 정책 차이를 의도된 변경으로 연결한다.

무결성 확인은 수치/물리 동등성 증명이 아니다. Scene 검증 상태, 원본 증거 접근 가능성, 현재 실행 결과는 다른 필드로 유지한다. UNVALIDATED v8을 패키지화했다는 이유로 VERIFIED로 바꾸지 않는다.

## 7. 공식 Dataset / Policy 계약

### 학습 로그와 시각화 계약

- 공식 Trainer가 작성한 로그·결과를 원본 지표로 사용한다. 학습 loop·scheduler·optimizer·validation 처리에는 UI를 위한 변경을 가하지 않는다.
- 추가 조회 모듈이 필요하면 지표 이름·값·공식 step/time·출처 run/로그를 읽어 표시한다. 로그에 없는 LR/Validation Loss를 Trainer 내부에서 새로 수집하도록 확장하지 않는다. 누락은 미제공으로 표시하고 step/집계 의미를 임의 변경하지 않는다.
- 공식 학습 로그, 공식 Trainer 자체의 검증 로그, 별도 Offline Validation 결과를 구분한다. 서로 다른 Dataset/Checkpoint/step의 지표를 같은 Training/Validation curve로 조용히 합치지 않는다.
- 공식 로그를 불필요하게 자체 이력 DB나 두 번째 학습 관리 저장소에 복제하지 않는다. 필요한 표시용 cache는 삭제 가능한 파생 자료이며 학습 Resume/Checkpoint의 기준이 아니다.
- 읽기/파싱/시각화 실패는 조회 오류다. 공식 학습 계산·scheduler·optimizer·저장 상태를 변경하지 않는다. Offline 결과도 원래 학습 Checkpoint를 수정하지 않는다.

내부 Episode의 부가 정보는 공식 Dataset 필수 조건으로 전파하지 않는다. 공식 create/add_frame/save_episode/finalize와 공식 aggregate 기능을 사용한다. 이미지/영상 재인코딩은 공식 형식상 필요한 경우에만 수행하고 이미 호환되는 파일을 불필요하게 재저장하지 않도록 확인한다. 내부 자료와 학습 자료는 의미가 다르므로 변환 결과 생성 자체를 금지하는 것은 아니다.

Policy 입출력 feature·camera key·joint order·action 의미·normalization/processor를 검사한다. 일반 학습 호환 검사와 Sim/실물 실행 호환 검사를 분리한다. 외부 Policy에 프로젝트 provenance가 없다는 이유만으로 일반 학습/로딩을 막지 않는다. 평가에 필요한 매핑을 확인할 수 없으면 명시적으로 요구하고 추측해서 모터 명령을 만들지 않는다.

MiniVLA는 개발·이관 범위에서 제외한다. MiniVLA Checkpoint 로더·호환 계층·전용 데이터/Checkpoint 변환·학습/추론/평가 계약을 만들지 않는다. 기존 MiniVLA 자료는 원본 위치에 보존하며 새 계약으로 변환할 의무가 없다. Policy 계약은 ACT·SmolVLA 등 지원 대상의 공식 LeRobot CLI/API·processor·Checkpoint 형식을 기준으로 한다. 정책 종류를 늘리기 위한 자체 통합 프레임워크는 만들지 않는다.

2026-10-26 [RO01~RO03](robot-operations-bundle.md): 프로필 bytes SHA와 canonical mapping hash, source/execution 모델 identity·limits-only 메모리 binding을 구분한다. Capture 준비 결과의 model_rad/관절 순서·측정 history·host receipt interval·카메라 원 RGB/해상도·mapping/model identity를 보존하고 hardware_synchronized=false를 명시한다. Unknown mapping/누락 관측/NaN을 기본값으로 채우지 않는다. Stop·SDK ACK·포트 close는 물리 정지/도달/토크 해제 증거가 아니다. 준비 계약을 검증했으며 실제 Capture 파일 publish·촬영/실물/엔진 연결·AC03은 미완료다.

2026-10-26 최종 C 전환: **공식 Native 파일 + 최소 실행 Metadata**를 구현했다. NATIVE-01/02/03의 로컬 파일·공식 CPU 소비자 관문을 통과했다. [전환 보고](native-dataset-transition.md)를 현재 계약으로 사용한다. 이전 [비교·차단 보고](dataset-storage-review.md)는 수정하지 않은 조사 이력이다. 엔진·실물·UI·공식 Trainer 학습 실행은 미검증이며 BU/E를 시작하지 않았다.


## 2026-10-27 P01 Evaluation의 Native 완료·Resume

simulation_evaluation의 완료 Episode는 success=true인 Placement뿐 아니라 정상 max_steps/완결된 안전 거부의 success=false 기록도 포함한다. 적용0 frame/취소/엔진 오류로 부정확한 중간 기록은 Episode를 publish하지 않고 관측된 attempt/outcome만 남긴다. 기존 C NativeRun/segment만 사용하며 새 Dataset 형식이 아니다.

Evaluation Resume는 source/datagen과 별도로 policy_identity/evaluation_contract를 필수로 검사한다. 모델/processor/학습 Dataset·Scene/Calibration/엔진 모델·Task/단위/phase/seed/배치/시간/strict 명령 정책이 같아야 하며 새 output에 닫힌 segment를 공유한다. success attempt뿐 아니라 episode_id가 있는 failure도 완료 Episode 목록과 대조한다. episodes는 누적 평가 attempt 목표다. 기존 Source/DataGen의 성공 채택/Resume 검사는 변경하지 않았다.

원 Policy 후처리 Action인 joint_targets, commands/applied_joint_rad, pre obs와 post states, engine physics timestamps와 Episode-relative 30Hz 영상 시각을 구분한다. 큰 배열은 official HDF5에만 기록하며 summary JSON에 복제하지 않는다. [실제 결과](p01-simulation-rollout.md)를 참조한다.
