# Codex용 자동 관측 제안·Side/Wrist/Object 공동 정합

2026-11-01. `workflow-restoration`의 소스 구현 안내다. 이번 변경은 **소스·문서 작성만** 수행했으며 테스트·CLI·검출·최적화·렌더러·UI·하드웨어를 실행 검증하지 않았다. 아래 명령은 구현한 인터페이스의 사용 예시이지 실행 성적이 아니다.

사용자는 Scene Prepare에 입력과 메모를 등록하고 Codex에게 Scene 제작을 요청한다. 아래 JSON 작성, 제안 검토와 CLI/Python 호출은 **Codex의 작업**이다. 사용자에게 Landmark 편집기나 CLI 조작을 요구하지 않는다. 별도 LLM 런타임·Agent 서버·자동 UI 클릭은 없다.

후속 사용자 요청으로 기존 Scene에 실제 적용한 기록은 [새 Fitter 재정합 결과](../docs/scene-auto-fitting-refit.md)에 있다. 최초 소스 작성 당시의 미실행 범위와 이 후속 실행을 구분한다. 종이/Workspace 경계의 포함·겹침 조건은 제거했다.

## 1. 기존 Project에서 시작

`SCENE_AUTHORING.md`, `SCENE_RULES.md`를 읽고 `project.yaml`, `input/evidence.yaml`, Capture manifest, `scene_state_id`, 요구 메모, Current Scene, OPEN Candidate와 Export 목록을 확인한다. 등록되지 않은 미디어를 전체 검색해 섞지 않는다. Current와 OPEN 후보 중 어떤 것을 baseline으로 쓸지 Codex가 명시한다.

기존 `Candidate.create`/`edit`/`save`로 초기 Metric Scene을 만든다. 알려진 CAD/GLB·실측 치수·Robot Base·URDF/Mapping을 보존한다. 이 도구는 사진만으로 CAD·보이지 않는 두께·실측 좌표를 발명하는 Scene 생성기가 아니다.

```bash
python -m real2sim_builder.cli inspect PROJECT
python -m real2sim_builder.cli candidate PROJECT create initial
# Codex가 기존 edit/save API로 Geometry/Frame/Camera/Support 초기값 작성
python -m real2sim_builder.cli auto-observe PROJECT --candidate initial --scene-state layout_01 --options observe.json
```

`--candidate`를 생략하면 `auto_observations` 후보를 Current 또는 빈 Scene에서 만든다. 기존 geometry가 없는 빈 후보는 객체별 검출 힌트도 부족하므로 일반적으로 Codex가 작성한 초기 후보를 지정한다. `--scene-state`를 생략하면 eligible 관측에서 유일한 선언 layout만 사용한다. 여러 layout이 있으면 선택을 요구하는 보고서를 반환한다. 다른 layout에는 초기 배치를 별도로 정의한 Candidate/Project를 사용한다.

공유 Camera·다물체를 조정할 때는 object scope가 없는 OPEN Candidate를 사용한다. 기존 단일 object scope를 자동으로 확장하지 않으며, 그 후보에서는 기존 scope 밖 관측 layer/Scene 변경을 저장할 수 없다.

## 2. 자동 관측 제안

`propose_observations(project, *, scene_state=None, options=None, candidate=None)`는 등록된 eligible Side/Wrist 이미지 ID·원본 SHA·해상도·measured q가 있는 관측만 읽는다. 누락된 q를 만들거나 Capture를 중복 Import하지 않는다. 이미지 SHA/order/해상도 불일치는 오류이며, 사용할 이미지가 없는 경우 `NEEDS_MORE_DATA` 보고서와 초안은 유지한다.

`observe.json` 예:

```json
{
  "min_area_px": 50,
  "max_components": 3,
  "objects": {
    "cube_red": {"hue_radius": 12},
    "cup_a": {"roi_xywh": [80, 60, 180, 220]}
  },
  "images": {
    "REGISTERED_IMAGE_ID": {
      "objects": {"cup_a": {"roi_xywh": [260, 0, 380, 470]}}
    }
  }
}
```

ROI와 색상은 Codex가 실제 입력을 보고 지정하는 추정값이다. 위 숫자는 형식 예시다. 색이 충분히 구분되는 객체는 HSV·morphology·연결 성분으로 가시 Mask/bbox를 제안한다. 사각형이면 순서 미확정 코너별 UV 제안도 생성한다. 컵은 edge/ellipse의 **보이는 rim** 제안, 일반 종이는 edge quad 제안이며 ArUco라고 간주하지 않는다. 로봇/그리퍼의 색 힌트는 같은 색의 다른 링크를 포함할 수 있어 ROI·물체 ID 검토가 필요하다.

실제 인쇄 패턴이 있을 때만 `pattern`을 명시한다.

```json
{"pattern": {"type": "aruco", "dictionary": "DICT_4X4_50", "object_ids": {"7": "printed_board"}}}
```

ChArUco는 `type: "charuco"`, `dictionary`, `squares: [가로 칸 수, 세로 칸 수]`, `square_length_m`, `marker_length_m`, `object_id`를 실제 보드 사양으로 제공한다. OpenCV의 aruco 모듈이 없으면 해당 검출을 생략하고 부족한 의존성을 보고한다. 새 패키지나 대형 모델을 자동 다운로드하지 않는다.

출력은 `scratch/agent/<candidate>/observations/<입력 digest>/proposals.json`, Mask PNG, 관측별 preview PNG다. 같은 geometry·옵션·관측으로 재실행하면 같은 제안을 반환한다. Candidate geometry가 바뀌면 새 입력 digest를 사용한다. 개별 제안에는 다음 필드가 있다.

- `id`, `image_id`, `scene_state_id`, `camera`, `feature_id`, `uv_px` 또는 `mask_path`
- `object_id: null`, `object_hint`, `detector`, `confidence`, `occluded: null`
- `source_image_sha256`, 관측 Metadata digest, `provenance: derived`
- 코너 순서와 3D 대응은 기본 미확정. `confidence`는 검출 확신이지 metric/Calibration 확신이 아님

## 3. Codex가 제안을 검토·반영

Codex가 preview와 원본을 읽고 객체 ID·가림·동일 CAD corner 여부를 검토한 뒤 `selections.json`을 쓴다. 가려진 코너를 임의 확정하지 않는다. Mask만 승인해도 이후 비교에는 쓸 수 있지만, 현재 MVP의 공동 최적화에는 검토된 3D–2D 대응점이 필요하다.

```json
[
  {
    "proposal_id": "MASK_PROPOSAL_ID",
    "object_id": "cube_red",
    "occluded": false
  },
  {
    "proposal_id": "CORNER_PROPOSAL_ID",
    "object_id": "cube_red",
    "point_fraction": [-0.5, -0.5, 0.5],
    "correspondence_verified": true,
    "sigma_px": 3,
    "occluded": false
  }
]
```

`point_fraction`은 **실제 CAD에서 같은 점임을 확인한 경우에만** 사용한다. 또는 객체 local 좌표의 `point_m` 하나를 지정한다. 코너 proposal은 이미 `uv_px`를 갖고 있으며, Codex가 수정할 때만 selection에서 `uv_px`를 명시한다. 일반 bbox/ellipse의 중심을 곧바로 물체의 metric 중심으로 사용하지 않는다. 같은 CAD 점·관측을 다시 반영하면 중복 Landmark를 늘리지 않는다.

```bash
python -m real2sim_builder.cli auto-observe PROJECT \
  --commit scratch/agent/initial/observations/DIGEST/proposals.json \
  --selections selections.json
```

Python 진입점은 `commit_observation_proposals(project, proposal_file, *, selections)` 또는 `Candidate.commit_observations(...)`다. `selections` 생략으로 모두 승인하지 않는다. 파일은 해당 후보의 observations 안에 있어야 하고, 이미지·관측 Metadata·geometry·Mask가 바뀌면 다시 제안해야 한다.

반영 위치는 **Candidate Scene의 `derived_observations`**다. `input/evidence.yaml`을 수정하거나 `import_metadata(kind='measurements')`로 가짜 실측을 만들지 않는다. 승인 후에도 `derived`, `physical_verified=false`다. 가림을 확인하지 않은 색상 Mask는 `visible_fragment`, rim Mask는 `visible_rim`으로 남겨 전체 object-ID silhouette와 잘못 비교하지 않는다. 명시적으로 비가림을 확인한 `silhouette`만 기존 Mask 비교에 사용한다.

## 4. 공동 Scene Fit

```bash
python -m real2sim_builder.cli candidate PROJECT fit initial --target joint:scene --options fit.json
```

```json
{
  "scene_state": "layout_01",
  "cameras": ["side", "wrist"],
  "objects": ["cube_red", "cup_a", "cup_b"],
  "supports": {"cube_red": "table", "cup_a": "table", "cup_b": "table"},
  "translation_bound_m": 0.05,
  "rotation_bound_rad": 0.3,
  "pose_prior": 0.2,
  "min_confidence": 0.2,
  "max_group_regression_px": 2,
  "max_nfev": 100
}
```

Python API는 `Candidate.fit('joint:scene', options)`, 순수 결과 함수는 `calibration.joint.fit_joint_scene(project, scene, options=None) -> (scene, report)`다. 기존 `calibration.geometry.fit`이 같은 target으로 연결하며 `reconstruction.fit_snapshot_scene(candidate, options=None)`도 같은 Candidate 경로를 사용한다. 기존 일반 `run()`의 분석·물리·Export 의미는 바꾸지 않는다.

최적화 변수는 카메라마다 공유 pose 하나, 물체마다 공유 world pose 하나다. Side는 고정 카메라, Wrist는 link-local mount이며 관측마다 기존 `observation_scene`의 **measured-q FK**를 사용한다. q·URDF·Robot Base·치수·K·distortion·물성은 공동 단계에서 변경하지 않는다. 실측/보정된 pose도 잠근다. 초기 K/pose가 없으면 기존 `bootstrap:<camera>`/`intrinsics:<camera>` 단계를 먼저 수행한다. 해당 기존 단계도 후보의 승인 관측 layer를 읽지만 원래 독립 holdout/metric anchor 조건은 유지한다. 이 MVP가 그 조건을 완화해 unknown K를 자동 확정하지 않는다.

지지 객체는 명시 `supports` 또는 기존에 거의 같은 높이인 수평 box support surface에서 판단한다. 평평하고 upright인 경우 XY/yaw만 최적화하고 Z는 support top+객체 높이로 계산한다. 비수평/미결합 객체에는 이 가정을 강제하지 않고 pose6을 사용한다. Codex는 실제 support/얇은 상부 물체를 확인해 mapping을 지정한다. 임의 종이를 큰 물리 테이블로 간주하지 않는다.

명시 거리·same-support 제약은 기존 `apply_geometry_constraints`의 독립 pair projection을 재사용한다. 영향을 받는 pair 양쪽을 함께 선택하거나 실측 pose anchor를 유지한다. 겹치는 다물체 제약 graph는 새 Solver를 추가하지 않아 지원하지 않는다. 최종 Candidate의 보호/스키마 검사를 통과하지 않으면 저장하지 않는다.

물체 목록을 생략하면 train 대응점에 실제로 등장한 manipulable/receptacle만 선택한다. 거리 제약 projection 뒤에도 pose 이동 bound와 선언 support의 높이를 재확인한다. 종이/Workspace 테두리 안에 들어가야 한다는 조건이나 테두리와의 겹침 조건은 없다. `supports`는 수평 높이 결합이며 XY 작업구역 제한이 아니다. 명시 선택하지 않은 물체를 관측 없이 자동 정합한 것으로 보고하지 않는다.

잔차는 `project_point`의 원본 해상도 pixel 좌표다. 가시성·confidence·`sigma_px`를 반영하고 camera×observation×object별로 정규화한다. pose prior와 soft-L1 least-squares를 사용한다. 일부 그룹이 설정한 pixel 한계보다 나빠지면 `NOT_IMPROVED`로 남기며 Candidate geometry는 저장하지 않는다. 독립 holdout을 반드시 요구하지 않고 Draft Fit을 허용하되, 없는 검증을 만들어내지 않는다.

`fit.json`, `joint-fit.json`에는 before/after RMSE, 그룹/최악 outlier, 관측 coverage, 변수·bounds/bound hit, data Jacobian rank/condition, 부족한 근거, `IMPROVED|NOT_IMPROVED|NEEDS_MORE_DATA`를 기록한다. rank 부족/metric anchor 미확정이면 relative-only·추가 관측 요구를 명시한다. prior를 넣어 full rank인 것처럼 보고하지 않는다. `IMPROVED`도 `OPTIMIZED_UNVERIFIED_DRAFT`이며 자동 promote/Export하지 않는다.

## 5. 비교와 새 Revision

실행이 허용된 별도 작업에서 기존 `Candidate.evaluate` 또는 아래 명령을 호출한다.

```bash
python -m real2sim_builder.cli candidate PROJECT evaluate initial --engine mujoco
python -m real2sim_builder.cli diagnose PROJECT --candidate initial --engine mujoco
python -m real2sim_builder.cli export PROJECT \
  --destination PROJECT/exports/revision-002 --candidate initial --allow-unvalidated
```

승인된 `silhouette`와 Landmark는 기존 `validation.object_metrics`에 연결한다. 기존 compare의 side-by-side/overlay/difference PNG와 관측별 object JSON을 사용한다. 새 UI 창은 없다. Source SHA와 후보 Mask는 기존 signature에 포함하고, Export는 승인 Mask를 Package 내부 상대 경로로 복사한다. 원 촬영·기존 Export·SDK/Precision/URDF·Dataset/Checkpoint는 수정하지 않는다.

## 구현 범위와 남은 제한

- 구현: 기본 CV 제안, 후보 전용 review/commit, 기존 개별 fitting과의 관측 연계, 공유 Side/Wrist/Object Landmark 공동 Draft Fit, 기존 Mask 평가/Overlay·Export 연결.
- 미구현: 반복 렌더를 포함하는 Mask-boundary 최적화, 자동 3D corner correspondence 확정, 범용 learned segmentation, 가려진 전체 형상의 복원, 겹치는 물체 거리 graph Solver. rim/fragment는 inspection-only이고 현재 전체 silhouette loss에 넣지 않는다.
- 이번 변경의 실행 검증은 하지 않았다. 의존성/API 호환·실제 검출 품질·수렴·성능·각 Scene의 회귀·물리 정확도는 미확인이다. 독립 촬영이 부족하면 Codex는 Camera·자세·가림·필요 이유를 구체적으로 제시하고 추가 자료를 요청한다.
