# Scene 제작 규칙 — 측정·기하·카메라·검토

2026-10-31. 기존 Builder의 `AGENTS.md`와 `docs`의 Markdown 14개 전체를 읽고 제작 규칙을 현재 프로젝트용으로 정리했다. 실행 순서는 [SCENE_AUTHORING.md](SCENE_AUTHORING.md)를 따른다. 이 문서는 수학/입력/판정 원칙이며 새 검증 결과가 아니다. 문서의 예시 수치나 과거 Scene 성적을 현재 Scene의 실측·성공으로 사용하지 않는다.

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

- Canonical authoring Scene에서 USD/MJCF를 각각 만든다. USD→MJCF 변환을 Scene의 기준으로 삼지 않는다.
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
- 휴대폰 참고사진은 context-only로 읽는다. 촬영 Camera가 미결합인데 Side/Wrist의 pixel calibration 입력처럼 쓰지 않는다.
- Pair의 **Real은 fitting 대상**, 저장 Sim은 **그 당시 Runtime 기준 영상**이다. Candidate는 같은 측정 q로 새로 렌더한다. 저장 Sim을 후보 렌더 결과로 재사용하지 않는다.
- Real↔Runtime↔Candidate 비교 전에 q, Camera K/pose/resolution, Mapping, 엔진, Revision identity를 확인한다. 동등성이 unknown이면 RGB 차이만으로 Adapter나 렌더러가 원인이라고 확정하지 않는다.
- 완료/Manifest에 게시된 자료와 pending을 구별한다. 원 촬영 품질 경고를 숨기거나 실패한 촬영을 정상 촬영 수로 세지 않는다.

## 4. GLB·실측 기하·접촉

- GLB는 복원된 표면/배치의 초기 추정이다. glTF의 명목 metre/+Y up만으로 스캔의 실제 scale과 robot-world 등록이 검증되지는 않는다. GLB를 원 LiDAR depth로 표기하지 않는다.
- 먼저 bounds, transform, 연결 성분, 퇴화면, 열린 경계, UV/재질을 확인한다. Plane 제거/voxel cluster는 분리 제안이며 의미 분류가 아니다. 사진·texture와 대조해 물체 ID/ROI를 정한다.
- 실측 dimensions·중심 거리·rim gap을 실제 Candidate geometry에 반영하고 residual을 남긴다. Scan의 전역 scale을 무조건 고정하지 않는다. 여러 길이 비율이 다르면 부분 왜곡·누락 면·ROI 오류를 별도 가설로 남긴다.
- Metric 등록은 최소 3개 비공선 3D–3D 대응과 근거 있는 world 좌표가 필요하다. Scale/rotation/translation·rank·residual을 함께 본다. 등록 없는 scan-local 검토 후보는 world 정합 완료가 아니다.
- 부분 표면의 bbox는 전체 물체 bbox가 아니다. 반대편 면의 관측 근거 없이 숨은 두께를 확정하지 않는다. Depth는 optical Z이며 rectified RGB/K와 맞아야 한다. GLB 기반 추정과 실제 depth/cloud의 근거 수준을 혼동하지 않는다.
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

### Codex 자동 관측과 공동 정합

- 종이/Workspace 테두리는 자동 Fitting의 XY 허용 영역이 아니다. 블록이 경계에 걸치거나 밖에 있어도 저장을 거부하지 않는다. `supports`는 명시한 수평면의 높이·upright 결합이며, Workspace 배치 함수나 Task의 배치 제한과는 별개다.

- 본 시스템에서 영상 관측 생성/선택과 Fitting 도구 실행 주체는 **Codex**이며 일반 사용자가 Landmark 편집기를 조작하지 않는다.
- 자동 Detector의 mask/UV 제안은 `estimated/derived`로 기록한다. CV 검출 confidence는 Camera/3D/실측 확신이 아니다. 가려진 컵 림이나 보이지 않는 Block corner를 2D에서 임의 확정하지 않는다.
- `same scene_state_id`의 물체는 **여러 camera×pose에서 하나의 world pose**를 공유한다. 새 layout은 다른 Scene State로 분리한다.
- Side는 고정 extrinsic, Wrist는 `T_world_base × FK(q_measured) × T_link_camera`라는 **하나의 link-local camera mount**를 공유한다. 각 자세별로 별도 Wrist extrinsic을 만들지 않는다.
- 실측 K/치수/Robot Base/q/URDF는 잠그고 미확정 Camera Pose, Wrist Mount, Object XY/Yaw 등 필요한 변수를 제한적으로 공동 최적화한다. `measured/calibrated` 보호는 유지한다.
- 한 view나 특정 Gripper만 좋아지고 컵·블록이 나빠지는 후보는 전체 개선으로 자동 승격하지 않는다. camera×pose×object 지표를 같이 본다.
- 초안 제작을 위해 독립 검증 자료를 강제하지는 않는다. **Draft Fit은 optimized/unverified**, 독립적 수치 검토/물리 검증은 별개의 결정이다. 단 실제 모델·시간·Camera·좌표·자산 불일치는 거부한다.
- 외형 렌더와 접촉용 collision은 분리해서 다룬다. 픽셀을 맞추기 위해 마찰, 손가락 충돌 형상이나 측정 q를 바꾸지 않는다.
- 최소 추가 촬영을 요청할 경우 `어느 Camera`, `어느 자세/시점`, `어떤 가림을 풀지`, `왜 해당 관측이 필요한지`를 Codex가 구체적으로 제시한다.

현재 구현은 `auto-observe` → Codex의 명시 `--commit … --selections …` → `candidate … fit … --target joint:scene`이다. 승인 관측은 Candidate의 `derived_observations`에만 보존하며 원본 Evidence의 실측으로 Import하지 않는다. 공동 단계는 K·distortion·치수를 고정하고 Landmark를 최적화한다. Mask-boundary 반복 최적화는 미구현이고 전체 silhouette 비교만 기존 평가에서 제공한다. 가림 미확정 Mask/컵 rim은 전체 silhouette로 취급하지 않는다. 정확한 옵션과 소스 구현의 미검증 범위는 [AUTO_SCENE_FITTING.md](AUTO_SCENE_FITTING.md)를 따른다.

## 6. 외형·충돌·물성·작업의 분리

- 상호작용에 중요한 기하를 먼저 맞추고 재질·색·texture·조명은 그 뒤에 조정한다. Photorealism보다 위치·크기·접촉 구조가 우선이다.
- Visual과 collision은 별도다. 컵은 열린 상단과 바닥/벽을 표현하며, 화면 색 오차를 줄이려고 collision 두께를 바꾸지 않는다. Mesh visual에 단순 box collision을 붙였다면 미검증 가설임을 남긴다.
- 정적 참고 로봇의 외형만 Export한 결과를 관절 제어 가능한 로봇으로 보고하지 않는다. USD 구조 로딩은 Isaac Articulation/PhysX/Fabric/Camera 실행과 다르다.
- 질량·마찰·관성·damping·restitution은 실측/동작 근거가 있어야 물리값으로 승인한다. Unknown mass를 임의 기본값으로 동적 물체라고 선언하지 않는다. 추정 runtime 물성을 사용하면 별도 출처를 기록한다.
- 기존 passive sliding fitting은 제한된 운동·알려진 조건·독립 trajectory에 관한 도구다. 임의 action replay, 모든 물성 역추정, 실제 grasp 성공을 지원한다는 뜻이 아니다. 물성으로 기하/시간 오차를 숨기지 않는다.
- `scene.workflow`는 명시 작업 의도/ID/역할/관측/Reset/성공 조건의 metadata다. 없는 작업을 자동 발명하지 않는다. Scene 제작과 Source·Mimic·학습·Policy 실행은 별도 책임이다. 새 물체의 가짜 성공 시연을 만들지 않는다.

## 7. Blender 편집 규칙

- 기존 candidate blend와 기존 Blender subprocess를 사용한다. `r2s_id/r2s_role`과 Camera의 resolution/pixel aspect 등 현재 sync 계약을 지킨다. 보이는 미등록 물체를 조용히 누락시키지 않는다.
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
