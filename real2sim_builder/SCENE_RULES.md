# Scene 제작 규칙 — 측정·기하·카메라·검토

2026-10-31. 기존 Builder의 `AGENTS.md`와 `docs`의 Markdown 14개 전체를 읽고 제작 규칙을 현재 프로젝트용으로 정리했다. 실행 순서는 [SCENE_AUTHORING.md](SCENE_AUTHORING.md)를 따른다. 이 문서는 수학/입력/판정 원칙이며 새 검증 결과가 아니다. 문서의 예시 수치나 과거 Scene 성적을 현재 Scene의 실측·성공으로 사용하지 않는다.

## Scene Memo 입력 원칙 (2026-11-05)

Scene Memo는 사용자가 Codex에게 전달하는 하나의 자유로운 제작 지시문이다. 장면 설명·실측 치수·공유 제품·공간 관계·형상/색/재질·작업 목적을 한 메모에 작성한다. 항목별 양식이나 별도 치수 입력은 필수가 아니다. Scene Prepare의 안내는 예시 placeholder이며 저장할 메모 본문을 자동 생성하지 않는다.

Codex가 원문과 사진·기존 Scene을 함께 이해한다. Python은 `authoring.scene_analysis_schema/parse_scene_analysis`로 타입·단위(m)·ID·참조·수치·원문 인용/SHA만 검증한다. 정규식/키워드/문장 패턴 기반 치수나 물체 해석기를 추가하지 않는다. 미지 치수는 null, 영상 기반 추정은 estimated다. 부분 실측은 부분 제약으로 보존하며 나머지 축까지 measured로 만들지 않는다. 기존 측정 자료와 충돌하면 검토를 요청하고 원본을 유지한다. 현재 API와 실행법은 [AUTO_SCENE_FITTING.md](AUTO_SCENE_FITTING.md)의 단일 메모 경로를 따른다.

## 1. 근거와 변경의 우선순위

- 근거의 우선순위는 **실측 → 유효한 Calibration → 알려진 Robot Geometry/FK → 시간 정합된 다중 관측 → 영상에서 계산한 측정 → 수치 최적화 → 시각적 추정**이다. 서로 충돌하면 출처·단위·개체·시점을 먼저 확인한다.
- 계산 가능한 값은 눈대중으로 대체하지 않는다. `value/provenance/evidence`를 보존하고 unknown은 unknown으로 남긴다. Optimizer가 수렴해도 optimized가 자동 measured/calibrated가 되지 않는다.
- measured/calibrated geometry·q·Camera를 화면이 맞아 보이도록 수정하지 않는다. 잘못된 실측을 정정해야 한다면 새 근거와 별도 변경 이력을 남긴다. 보호 검사를 통과하려고 provenance를 estimated로 낮추지 않는다.
- 원 사진·Snapshot·SDK/Precision·기존 Export는 유지한다. 새 Scene은 새 Project, 기존 정합 개선은 명시 baseline과 별도 Candidate를 사용한다. Current와 best OPEN Candidate가 다를 수 있으므로 실제 signature를 확인한다.
- RGB만으로 metric scale, 숨은 두께, 마찰, 물리 접촉 정확도를 확정할 수 없다. 자료 부족은 최소 추가 측정과 이유로 보고한다. 가능한 추정 Scene 제작까지 중단해야 한다는 뜻은 아니며 검토 결과를 UNVALIDATED로 구분한다.

## 1-A. 관측 배치와 실행 물체 구성

- 사용자 메모의 기본 구성요소/선택형 작업 물체를 각 Object의 `spawn: always|recipe`로
  명시한다. 역할·질량·RigidBody 여부로 생성 정책을 대신하지 않는다.
- Scene에는 선택할 수 있는 모든 자산과 관측 배치를 보존한다. 작업 실행 시 `recipe` 물체는
  Script에 선언한 것만 생성한다. 화면만 숨기고 충돌체·물리 상태를 남기지 않는다.
- 선택에서 빠진 부모 물체의 부속물도 빠져야 한다. `parent_object`를 실제 소유 관계에 맞게 선언한다.
- `task_object`는 Workbench Script의 Curation 분석 대상 flag이며 Builder의 생성 정책과 별개다.
  여러 작업 대상의 초기 위치를 고를 수 있도록 기록에 Object ID를 보존한다.
- 기존 닫힌 Scene과 과거 녹화는 보존한다. 새로운 생성 정책을 기존 데이터에 소급 적용하지 않는다.

## 2. 좌표·단위·모델 규칙

- Scene/Candidate는 Instance Pose·역할·물성의 기준이다. 새 물체의 Visual/UV/Material은 등록된 USDA가 기준이며, 같은 자산의 OBJ/PNG 파생물로 MJCF를 만든다. USDA와 Scene에서 배치 Pose를 따로 수정하지 않는다. 기존 Canonical Primitive·Robot 자산은 유지한다.
- 길이/translation은 m, 회전 관절은 rad, world는 오른손 +Z up이다. `T_parent_child`는 column vector를 child에서 parent로 옮긴다. Frame chain을 순서대로 곱한다.
- Optical Camera는 X right / Y down / Z forward다. Exporter의 OpenGL/USD 카메라 축 변환 후 동일 변환을 다시 적용하지 않는다.
- Box는 중심 pose와 전체 dimensions다. STL의 단위는 자동 확정되지 않으므로 m 여부 또는 명시 scale을 확인한다. 원 Mesh bytes는 고치지 않는다.
- mm 입력은 지원 importer에서 길이·translation만 m로 바꾼다. K/uv는 pixel, 관절값은 기존 rad다. 불명확한 배열을 일괄 1,000으로 나누지 않는다.
- Reference robot 외형과 제어 Articulation은 별개다. Scan 안의 로봇 Mesh를 실제 URDF/관절 제어 모델로 대체하지 않는다.
- 원 q·joint order·Model SHA·Mapping SHA·장치 Calibration identity를 보존한다. 이미 model rad인 측정에 Precision을 다시 적용하지 않는다. 다른 개체/Profile의 자료를 같은 것으로 합치지 않는다.
- 과거 `simulation_joint_offsets_rad`는 현재 추가 runtime 보정 경로로 사용하지 않는다. 기존 baked Geometry는 명시된 identity와 함께 보존한다. 새 정합에서 q나 모터 보정값을 바꿔 오차를 감추지 않는다.

## 3. Snapshot·Pair·사진의 의미

- 촬영 상태는 measured q다. command target, saved Sim q와 구분한다. Camera별 시간 정합 상태·sequence·blur·가림·해상도를 확인한다. Host 수신 시각을 exposure 동기화라고 부르지 않는다.
- 한 정적 장면에서 Robot pose만 달리한 관측을 함께 사용한다. 물체나 Base가 움직였으면 다른 layout으로 분리한다. scene-state 이름은 사용자 선언이지 물체 불변을 자동 입증한 값이 아니다.
- Snapshot Import는 알려진 Robot reference와 Camera 자료를 등록하는 것이며 테이블/컵을 자동 추론하는 명령이 아니다.
- 휴대폰 사진은 동일 렌즈·줌·정적 배치의 External View로 등록할 수 있다. 공통 K와 사진별 pose를 추정하고 metric 근거가 있을 때 정합에 사용한다. 미등록 사진을 Side/Wrist의 pixel calibration 입력으로 쓰지 않는다.
- Pair의 **Real은 fitting 대상**, 저장 Sim은 **그 당시 Runtime 기준 영상**이다. Candidate는 같은 측정 q로 새로 렌더한다. 저장 Sim을 후보 렌더 결과로 재사용하지 않는다.
- Real↔Runtime↔Candidate 비교 전에 q, Camera K/pose/resolution, Mapping, 엔진, Revision identity를 확인한다. 동등성이 unknown이면 RGB 차이만으로 Adapter나 렌더러가 원인이라고 확정하지 않는다.
- 완료/Manifest에 게시된 자료와 pending을 구별한다. 원 촬영 품질 경고를 숨기거나 실패한 촬영을 정상 촬영 수로 세지 않는다.

## 4. RGB/Depth·실측 기하·접촉

- GLB/glTF Import/Export 및 전용 Scan 경로는 제거했다. 기존 파일은 삭제하지 않으며 의존 Scene은 신규 fitting/export에서 `LEGACY_UNSUPPORTED`로 진단한다. 일반 OBJ/STL과 Robot 모델은 유지한다.
- 실측 치수와 기존 CAD가 Geometry의 기준이다. SAM Mask·DA3 Depth/K/Extrinsic은 derived/estimated이며 measured로 승격하지 않는다.
- DA3 K·상대 Camera Pose를 PREDICTED로 기록한다. 겹치는 원본 이미지의 Depth로 독립 Batch를 similarity 정렬하고, 비연결 Batch는 UNRESOLVED다. 실제 metric baseline, 다양한 측정 q/FK 운동의 식별 가능한 hand-eye, 또는 실측 직사각형 지지면의 유효 가시 Depth가 있을 때 metric 초안으로 정렬한다. Robot-base gauge는 테이블/World 실측이 아니다. 사용자에게 수동 행렬·보드 코너를 필수로 요구하지 않는다. DA3 pose만으로 scale=1을 가정하지 않는다.
- Mask 원 해상도→DA3 resize/crop 변환과 K를 기록한다. 부분 표면의 bbox는 전체 물체 크기가 아니다. Depth는 optical Z이며 보이지 않는 뒷면을 관측점으로 만들지 않는다.
- 컵 중심 거리 `d = r₁ + r₂ + rim_gap`은 측정된 원형 지름, 같은 높이, 평행한 upright 축이라는 전제가 필요하다. 같은 support plane 관계가 절대 table 높이까지 결정하지는 않는다.
- 현재 상대 Geometry 도구는 겹치지 않는 pair 관계를 처리한다. 결합된 다물체 graph의 해결을 자동 가정하지 않는다. 불확실성을 생략했을 때 수치 tolerance는 실제 측정 정확도가 아니다.
- Workspace 종이/marker를 물리 지지 테이블로 취급하지 않는다. Finger 접촉 사진에서 접촉면·tip 위치·가림을 확인하며 임의 tool0 점을 실제 접촉점으로 확정하지 않는다.
- 과거 Scene2의 강제 수평/Base-table 접촉은 이후 사용자 지시로 바뀐 장면별 가설이다. 새 Scene에 보편적 법칙으로 적용하지 않는다. 실제 수평 여부·접촉·기울기는 해당 장면 근거로 정한다.

## 5. Camera와 FK 정합

- Wrist optical pose는 `T_world_base × FK(q_measured) × T_mount_camera`다. 각 관측의 q를 고정하고 K/mount를 공유한다. 자세마다 독립 Camera를 맞춰 잘못된 FK를 숨기지 않는다. Housing 외형은 optical mount 측정값이 아니다.
- Robot/FK·Base → Side Camera → Geometry → Wrist → 전체 자세 재평가 순으로 원인을 나눈다. 필요하면 제한된 변수 그룹을 번갈아 최적화한다. Focal 오차를 물체 크기로, Camera translation을 물체 이동으로 상쇄하지 않는다.
- FK는 3D link/landmark를 제공하지만 실제 사진의 2D uv를 자동 찾지는 않는다. Codex가 추정한 pixel은 estimated다. Metric anchor는 근거 있는 geometry/registration이어야 한다.
- K는 해상도와 결합한다. Crop/resize/EXIF 회전 시 좌표 관계를 확인한다. Distortion 보정은 원본을 보존하고 영상·Mask·Landmark에 일관되게 적용한다. 왜곡 계수를 조용히 0으로 바꾸지 않는다.
- 현재 unknown-camera bootstrap은 train 12대응·holdout 4대응과 비공면 깊이 분포를 요구한다. Wrist는 3개 이상 pose와 약 10° 이상 방향 다양성을 확인한다. 이것은 현재 fitter의 조건이며 모든 카메라 보정법의 보편적 최소치가 아니다.
- Bootstrap은 초기 shared focal/extrinsic 추정이다. 중심점·aspect/distortion을 고정한 초기 추정을 실제 lens 보정 완료로 부르지 않는다. 이후 intrinsics/camera 그룹과 별도 k1 distortion, quality audit를 구분한다.
- Rank/scaled Jacobian/condition/불확실성으로 focal-depth-translation 등의 구분 가능성을 본다. 현재 quality audit는 train 12개와 별도 Session verification 6개 이상의 대응 조건도 갖는다. 정확한 현재 조건은 [geometry.py](src/real2sim_builder/calibration/geometry.py)를 따른다.
- Manual Precision/FK를 사용한 Wrist를 물리 calibration 인증으로 승격하지 않는다. K/pose/distortion/resolution/registration/FK identity가 바뀌면 이전 audit 결과를 그대로 적용하지 않는다. Inspection camera는 실제 observation camera와 구분한다.

### 자동 관측과 공동 정합

- 종이/Workspace 테두리는 자동 Fitting의 XY 허용 영역이 아니다. 블록이 경계에 걸치거나 밖에 있어도 저장을 거부하지 않는다. `supports`는 명시한 수평면의 높이·upright 결합이며, Workspace 배치 함수나 Task의 배치 제한과는 별개다.

- 일반 흐름은 Scene Prepare의 자동 재구성이다. 사용자 Object 목록과 SAM prompt로 시작하며 유료 VLM이나 Codex의 반복 좌표 수정은 필수 조건이 아니다. 자동 등록이 불가능한 경우 필요한 실측·Calibration을 명시한다.
- 자동 Detector의 mask/UV 제안은 `estimated/derived`로 기록한다. CV 검출 confidence는 Camera/3D/실측 확신이 아니다. 가려진 컵 림이나 보이지 않는 Block corner를 2D에서 임의 확정하지 않는다.
- `same scene_state_id`의 물체는 **여러 camera×pose에서 하나의 world pose**를 공유한다. 새 layout은 다른 Scene State로 분리한다.
- Side는 고정 extrinsic, Wrist는 `T_world_base × FK(q_measured) × T_link_camera`라는 **하나의 link-local camera mount**를 공유한다. 각 자세별로 별도 Wrist extrinsic을 만들지 않는다.
- 실측 K/치수/Robot Base/q/URDF는 잠그고 미확정 Camera Pose, Wrist Mount, Object XY/Yaw 등 필요한 변수를 제한적으로 공동 최적화한다. `measured/calibrated` 보호는 유지한다.
- 한 view나 특정 Gripper만 좋아지고 컵·블록이 나빠지는 후보는 전체 개선으로 자동 승격하지 않는다. camera×pose×object 지표를 같이 본다.
- 초안 제작을 위해 독립 검증 자료를 강제하지는 않는다. **Draft Fit은 optimized/unverified**, 독립적 수치 검토/물리 검증은 별개의 결정이다. 단 실제 모델·시간·Camera·좌표·자산 불일치는 거부한다.
- 외형 렌더와 접촉용 collision은 분리해서 다룬다. 픽셀을 맞추기 위해 마찰, 손가락 충돌 형상이나 측정 q를 바꾸지 않는다.
- 최소 추가 촬영을 요청할 경우 `어느 Camera`, `어느 자세/시점`, `어떤 가림을 풀지`, `왜 해당 관측이 필요한지`를 Codex가 구체적으로 제시한다.

현재 기본 명령은 `reconstruct PROJECT --candidate NAME`이다. SAM→DA3는 기존 환경에서 순차 실행하고, 새 Visual은 Codex/Blender 자산을 등록한다. 원 optical Depth·pixel 좌표·Mask·SHA·Scale 근거를 보존한다. Hybrid의 공동 정합에서 Camera/K/Scale이 바뀌면 매번 raw ray를 재투영하고 새 World cloud를 게시한다. 이전 World cloud를 그대로 쓰지 않는다. 실측 q·Geometry·Robot과 검증된 카메라는 고정한다. Rank가 부족하면 UNRESOLVED다. 공동 렌더 정합은 선택한 MuJoCo/Isaac의 실제 segmentation을 쓰며 미관측 fragment 영역을 배경으로 강제하지 않는다. 독립 Backend 우승 선정과 실제 정확도는 미검증이다. [AUTO_SCENE_FITTING.md](AUTO_SCENE_FITTING.md)에 현재 API와 제한을 기록한다.

## 6. 외형·충돌·물성·작업의 분리

- 상호작용에 중요한 기하를 먼저 맞추고 재질·색·texture·조명은 그 뒤에 조정한다. Photorealism보다 위치·크기·접촉 구조가 우선이다.
- Visual과 collision은 별도다. 컵은 열린 상단과 바닥/벽을 표현하며, 화면 색 오차를 줄이려고 collision 두께를 바꾸지 않는다. Mesh visual에 단순 box collision을 붙였다면 미검증 가설임을 남긴다.
- 정적 참고 로봇의 외형만 Export한 결과를 관절 제어 가능한 로봇으로 보고하지 않는다. USD 구조 로딩은 Isaac Articulation/PhysX/Fabric/Camera 실행과 다르다.
- 질량·마찰·관성·damping·restitution은 실측/동작 근거가 있어야 물리값으로 승인한다. Unknown mass를 임의 기본값으로 동적 물체라고 선언하지 않는다. 추정 runtime 물성을 사용하면 별도 출처를 기록한다.
- 기존 passive sliding fitting은 제한된 운동·알려진 조건·독립 trajectory에 관한 도구다. 임의 action replay, 모든 물성 역추정, 실제 grasp 성공을 지원한다는 뜻이 아니다. 물성으로 기하/시간 오차를 숨기지 않는다.
- `scene.workflow`는 명시 작업 의도/ID/역할/관측/Reset/성공 조건의 metadata다. 없는 작업을 자동 발명하지 않는다. Scene 제작과 Source·Mimic·학습·Policy 실행은 별도 책임이다. 새 물체의 가짜 성공 시연을 만들지 않는다.

## 7. Blender 편집 규칙

- 기존 candidate blend와 기존 Blender subprocess를 사용한다. `r2s_id/r2s_role`과 Camera의 resolution/pixel aspect 등 현재 sync 계약을 지킨다. 보이는 미등록 물체를 조용히 누락시키지 않는다.
- 새 물체는 `blender-object-author`로 해당 물체만 작성한다. `r2s_id` root와 별도 `r2s_collision=True` Mesh를 사용하고 물체 USDA를 등록한다. 기존 전체 Scene의 `blender-build/author/sync`는 유지하지만 새 물체 추가에 전체 Scene 재생성을 요구하지 않는다.
- USDA 자산은 m/+Z·identity root·defaultPrim·상대 종속 파일·UV/Texture를 포함한다. 실제 Collision은 convex piece별로 확인하며 컵 내부를 Visual의 단일 hull로 막지 않는다. Asset root의 중첩 RigidBody/Articulation은 허용하지 않고 Scene Instance 및 기존 Robot 실행 자산이 담당한다.
- Author 뒤 canonical sync를 수행하고 최신 signature를 확인한다. 각 measured-q 렌더에서 authored mesh/material을 유지한다. 수정 전 canonical로 새 blend를 생성해 수정 결과를 잃지 않는다.
- UV/texture·scale baking과 collision을 구분한다. Procedural material은 지원 범위에 맞게 명시 bake/simplify하며, 임의 복잡한 node graph가 양 엔진에 동일하게 전달된다고 가정하지 않는다.
- Blender/Qt/USD 환경은 준비된 실행환경과 프로세스별 라이브러리 경로를 사용한다. 문서의 옛 환경 경로만 믿고 SDK 설치·업그레이드를 하지 않는다.

## 8. 평가·후보 선택·종료

- Train은 fitting/후보 선택, holdout은 일반화 비교다. 동일 영상이나 거의 같은 pose를 양쪽에 나누지 않는다. 독립 검증은 가능한 별도 Session을 확보한다.
- 후보를 고르는 데 이미 본 holdout은 더 이상 blind final audit가 아니다. 코드의 사용 이력 외에 Codex가 본 자료도 기록한다. 부족한 자료를 독립 자료로 재명명하지 않는다.
- Global MAE만으로 테이블/물체/컵을 승인하지 않는다. Object·pose·camera별 Landmark px, silhouette IoU, boundary/centroid/bbox, rim residual, 접촉/치수 mm residual을 근거가 있는 범위에서 기록한다. 없는 관측은 null/NOT_EVALUABLE이다.
- Scoped candidate는 다른 물체/공유 Camera를 고정하고 허용 변수만 수정한다. Baseline과 같은 observation coverage로 비교한다. Coverage 도구의 가시성 예측은 실제 표면 전체 관측·로봇 도달 가능성 인증이 아니다.
- 각 실험에 baseline/candidate, 가설, 변경/고정 변수, 전후 수치·overlay, 주요 회귀, 채택/거절 이유와 uncertainty를 남긴다. 3–5개 실험 권고는 의미 있는 가설 탐색이지 횟수 채우기 요구가 아니다.
- 개선이 있으면 허용 범위에서 반복한다. 개선 정체, 식별 불가능, 필요한 최소 추가 자료가 명확함, 자원 한계가 종료 이유다. 한 번 MAE가 낮아졌다는 이유만으로 완료하지 않는다.
- Stale signature·측정 보호·nonregression 검사를 우회하지 않는다. `promote`는 최종 물리 승인과 다르다. 검토용 최선 후보와 Current/promoted/ACCEPTED를 구분한다.

## 9. 게시·보존·인계

- 닫힌 Package는 새 Revision에 게시하고 상대 asset 경로/SHA·출처·불확실성을 보존한다. 원본 경로는 lineage이며 실행 의존성으로 남기지 않는다.
- 최신 validation이 없는 결과는 명시 review Export로 구분한다. UNVALIDATED도 검토 실행은 가능할 수 있지만 정합 승인·Task 성공과 같지 않다.
- 파일/스키마 검사, MuJoCo compile, USD parser, 실제 양 엔진 runtime, 독립 정합, 실물 접촉/Task를 각각 보고한다. 실행 금지/미실행은 그대로 남긴다.
- 현재 프로젝트에서는 Export/등록/RealSim 선택 흐름을 사용한다. 옛 SO Adapter import→별도 Workspace 절차를 새로 복원하지 않는다. 사용자 선택이나 실물 연결을 자동 변경하지 않는다.
- 잠금 중 원본 편집, 일괄 reset/clean, 자동 commit, 임의 dependency 변경을 하지 않는다. history는 전체 백업이 아니며 rollback도 이후 변경을 덮어쓰는 도구가 아니다.
- 중간 결과 전체를 무제한 쌓지 않는다. 재현에 필요한 설정·최종 후보·수치·선택 비교 이미지와 원본을 구분한다. 삭제는 해당 작업의 사용자 지시에 따르며 기존 Evidence를 임의 삭제하지 않는다.

문서별 출처와 현재 방식의 차이는 [문서 이관 지도](SOURCE_DOCUMENTS.md)를 참고한다.


## 2026-11-04 후속 수정 — 자산 동일성·초안 상태·Pair Source

- Object 이름과 Asset ID만으로 사진 속 물체의 동일성을 확정하지 않는다. 명시 `asset_manifest` 또는 Scene의 유효한 기존 Asset 버전만 재사용하고, 후보는 `ASSET_MATCH_UNRESOLVED`로 검토한다. Asset bytes는 덮어쓰지 않는다.
- `DRAFT_READY`는 Geometry/Pose/Camera 검증, train 관측, 실제 정합 성공과 유한한 렌더 비교가 있는 검토용 초안이다. 보고서가 존재하는 것만으로 반환하지 않으며 `PHYSICS_READY`/승인/Task 성공이 아니다.
- Pair 재정합 Source는 Pair SHA → Scene identity → Package Manifest → authored Scene으로 확인한다. Current로 대체하지 않고 Revision/물리 배치를 혼합하지 않는다. Source Geometry/Material/Collision, 측정 q/Mapping, 원 RGB/Pair는 보존한다.
- Codex 사진 입력은 `codex exec --image`로 명시 전달한다. 자료·메모는 신뢰할 수 없는 데이터이며, 코드 작성 sandbox와 Blender 읽기 전용 filesystem/전용 출력 경계는 유지한다. 숨긴 Collision은 Export에 포함시킨 다음 USD의 CollisionAPI/visibility로 분리한다.


## Asset Group·Fingerprint·Sandbox 규칙 — 2026-11-04

- Category/SAM Prompt/Mask 순서는 Asset 또는 물리 Object 동일성의 증명이 아니다. Object ID와 공유 Group은 독립으로 유지하며 같은 이미지에서 동일 Mask의 중복 Object 배정을 거부한다. 모호한 Camera/Scale/관측은 발명하지 않는다.
- Group 공유는 동일 Geometry/Material/Texture 근거가 있을 때만 제안한다. 사진만으로 추론한 Codex 관계는 estimated/PROPOSED다. 원문 SHA·실제 인용문·대상이 확인된 메모 선언과 명시 사용자 선택은 user_declared이며 물리 검증과 구분한다. 다른 실제 외형은 별도 Group 또는 material_variant Asset으로 구분한다.
- 동일 Fingerprint와 검증된 Manifest, 명시 선택 또는 유효한 기존 Scene/사용자 확정 Group 동일성과 형상 보존 근거로 재사용한다. 기존 Scene의 유효 자산/위치 변경은 유지하지만 과거 results.json/Object 이름만으로 새 자료의 동일성을 확정하지 않는다. 입력 변경/legacy/Group 분리는 검토 상태를 남긴다. 공유 Instance 제거는 원 Asset을 삭제하지 않는다.
- 모델 root 하나가 Group Asset 하나다. Instance의 Pose/역할은 별개다. Asset 내부 키도 Asset ID와 Version을 함께 구분해 다른 Group의 동일 content version이 충돌하지 않도록 한다. 원 Library 파일은 덮어쓰지 않는다.
- Object Blender Worker의 host 전체 root bind와 부모 환경변수 상속은 금지한다. 설치 런타임/입력/Worker만 읽기 허용, 작업 출력만 host 쓰기 허용, 입력 symlink 거부, 네트워크 차단이며 구성 실패 시 확대 fallback은 없다. 일반 Scene Rendering은 별도 기존 경로를 유지한다.


## v3 우선순위·생성 이력 보존

- 새 모델링 요청은 그룹별 request ID로 캐시보다 우선한다. 완료 요청의 재실행과 독립 새 요청을 구별하고 등록된 성공은 실패 그룹 재시도에서 제외한다. 기존 USDA/Manifest는 불변으로 남긴다.
- 명시 Manifest > 유효한 Scene Asset 참조 > 자동 캐시 순서를 지킨다. 실측·Manifest 무효·관측 수량 충돌은 명시 선택으로 무시하지 않는다.
- 생성 Fingerprint/참조 SHA를 새 관측의 Fingerprint로 덮어쓰지 않는다. Crop도 내용별 경로로 보존한다. Observation 변경은 Pose/Camera 정합 입력이며 실제 형상/Material 변경은 검토한다. RGB/Mask SHA 변경 자체는 물체가 달라졌다는 증거가 아니다.
- 사용자 동일 제품 선언과 추정 Mask/Object 연결을 독립 기록한다. Python의 메모 인용 검사는 현재 SHA와 원문 substring 존재 검사뿐이다. 문장 의미·동일/상이 제품·형상 변경은 Codex가 해석하며, 인용문 존재는 의미/물리 동일성 증명이 아니다. 근거 없는 자동 승격은 하지 않는다.


## Workspace Asset·Scene 메모·Object 설정 보존

- USDA 정본은 Workspace 공용 Library, 개별 관측/메모/Robot/Camera/Instance Pose는 Scene Project 소유다. Revision은 같은 Project의 불변 결과다. Scene 삭제가 Library 삭제를 뜻하지 않는다.
- 공용 버전은 ID/Version/Manifest와 전체 종속 SHA로 선택한다. Category로 동일 제품을 추측하지 않는다. 제한된 Workspace Asset 경로 외의 외부 경로·Traversal·Symlink는 허용하지 않는다. Blender Sandbox를 확장하지 않는다.
- 기존 내부 자산은 읽기 호환으로 보존한다. 명시 publish의 실패·새 Version 생성이 원본/다른 Scene/이전 Export를 변경하면 안 된다. Export는 Library 없이 로딩 가능한 Closure를 소유한다.
- 현재 메모는 `input/scene_memo.txt` 하나다. `scene_memo/save_scene_memo`가 원문/SHA를 읽고 저장한다. 과거 current_brief/briefs는 파일이 없을 때 읽기 전용 복원에만 사용하고 scene_briefs 배치 선택/이력 추가를 실행하지 않는다. 다른 Scene·과거 문장을 현재 근거로 병합하지 않는다. 빈 입력을 가짜 설명으로 채우지 않는다. 메모 변경은 새 Codex 해석을 요구하며 과거 응답 SHA를 다시 쓰지 않는다. Export는 당시 원문/SHA를 독립 Package에 보존한다.
- Object 정보는 Current/실측/Config의 합집합으로 복원한다. 자산/치수/Mask 부재는 Object 삭제 이유가 아니다. 사용자 명시 삭제 외의 목록 축소, Manifest→자동 선택 되돌림, 모델 요청 ID 초기화를 하지 않는다. 충돌은 명시한다.

## 다중 시점 제품 경로 (2026-11-05)

- `authoring`은 메모 의미/Asset Group/모델링 정책, `automation`은 단계 조율만 소유한다. 새 사진·Pose·조명·Mask가 달라도 명시 Asset ID/Version과 형상이 같으면 재사용한다.
- Mask 부족은 관측별 문제다. 확정 Asset 공유를 차단하지 않는다. 공통 Depth 좌표의 1:1 대응과 명확한 seed로 Instance를 연결하며 대칭·모호함은 미해결로 남긴다. SAM index는 물체 ID가 아니다.
- 기본 최적화는 `hybrid.fit_scene` 하나다. 모든 유효 train View를 같은 Scene에서 실제 native RGB/Mask/Depth로 평가한다. `compare_backends`는 명시 실험 비교에만 사용한다.
- Metric cloud를 만든 뒤 Camera를 움직이면 원 optical ray에서 재투영한다. 오래된 World 점군으로 Camera를 맞추지 않는다. 물리 Camera의 공통 K·Side pose·Wrist mount와 이미지별 EXIF/resize/crop을 구분한다.
- 반복 예산 소진은 성공이 아니다. 수렴·개선·View별 회귀 한계를 기록하고 최선 유효 Candidate를 보존한다. Train과 독립 검증을 혼동하지 않는다. Appearance/실물 정확도/Task 성공은 RGB loss 감소로 승인하지 않는다.
- 원본·측정·사용 자산 Version·Export는 보존한다. 미사용 캐시 자동 삭제는 기본 동작이 아니다.
