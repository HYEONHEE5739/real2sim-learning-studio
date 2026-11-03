# 자동 Scene Reconstruction

2026-11-03. 기본 진입점은 `reconstruct`와 Scene Prepare/Builder의 **Auto Reconstruction** 폼이다. 기존 Codex 수동 편집 중심 흐름을 대체하는 구현을 진행 중이며, **전체 Physics-Ready 자동 생성 완료는 아니다.** 실행 기록·미완료 항목은 [단계별 기록](../docs/automated-reconstruction.md)을 따른다.

## 사용자 흐름

Scene Prepare에서 Project와 자료를 저장한 뒤 Auto Reconstruction을 연다. 사진의 정적 배치 ID, Camera/렌즈 ID와 유형, train/validation을 등록한다. 물체 표에는 ID·형상·역할·실측 크기(mm)·컵 벽 두께·Support·SAM 설명을 입력한다. 같은 색/모양의 물체를 하나의 ID로 추측하지 않는다. Wrist는 실제 q·단위·시각·Mapping이 있는 공식 Capture/Snapshot 입력을 사용한다.

기존 모델 환경 탭에서 SAM Python/Checkpoint와 DA3 Python/로컬 Model snapshot 폴더를 선택한다. 파일 경로는 Project의 `input/reconstruction.yaml`에 저장된다. 모델 설치·다운로드·원격 API·새 Agent 런타임을 사용하지 않는다. SAM 종료 후 DA3를 실행한다. DA3 batch 1..4, process resolution 140..504 범위이며 기본은 2/280이다.

측정된 World 위치·치수가 있는 보드를 사진에서 선택하고 네 모서리를 지정할 수 있다. 순서는 보드 local `(-X,-Y), (+X,-Y), (+X,+Y), (-X,+Y)`다. 알려진 K와 대응점으로 External PnP를 수행한다. World 위치가 미측정인 보드에 임의 위치를 넣지 않는다. 현재 Side/Wrist 자동 경로는 기존 검증된 K/pose/distortion을 사용하며, 일반 자동 렌즈 Calibration은 별도 미완료다.

실행 결과의 모호한 Mask는 상태 탭에서 사진·Object·Mask를 선택하고 **선택 Mask 사용**으로 명시한다. 잘못된 Mask는 원본과 같은 해상도의 이진 PNG를 지정한다. 같은 Candidate를 다시 실행하면 동일한 SAM/DA3 입력 캐시는 재사용하고 점군/정합을 다시 계산한다. 일반 사용자는 Raw JSON·4×4 Transform·ICP 설정을 작성할 필요가 없다.

사진·영상 등록은 RGB와 외부 mp4/mov/avi를 지원한다. 기존 `extract_videos`로 최대 12개 프레임을 샘플링하고 Source video SHA·frame index·실제 영상 시각·정적 배치 ID를 유지한다. 동일 영상 전체를 하나의 observation group으로 묶어 train/validation 누출을 거부한다. **Wrist 영상의 q 자동 동기화는 제공하지 않으며** 공식 Capture/Snapshot을 사용한다. 동일 영상은 독립 최종 검증 사진을 대신하지 않는다.

## CLI와 Python API

준비된 Builder Backend 환경에서 사용한다. 경로/이름은 예시이며 실제 측정값이 아니다.

```bash
python -m real2sim_builder.cli register-rgb PROJECT photo1.png photo2.png \
  --camera phone_main --type external --scene-state layout_1 --split train
python -m real2sim_builder.cli reconstruct PROJECT --candidate auto_1 --config reconstruction.yaml
# Project에 저장한 동일 구성으로 재실행
python -m real2sim_builder.cli reconstruct PROJECT --candidate auto_1
# 등록/물리만 따로 확인
python -m real2sim_builder.cli register-views PROJECT --candidate auto_1 --anchors anchors.yaml --scene-state layout_1
python -m real2sim_builder.cli physics-check PROJECT --candidate auto_1 --steps 500
```

`reconstruct --config`는 구성을 Project에 저장하고 실행한다. 같은 Candidate를 지정하면 기존 OPEN 후보의 추론 캐시를 사용할 수 있다. 다른 정적 배치·원본 변경에는 새 Candidate를 사용한다. 자료 부족은 종료 코드 2, 실패는 예외/비정상 종료로 구분한다. `control PROJECT stop`은 해당 Worker와 소유 모델 child만 종료하며, Candidate/중간 결과를 보존한다.

```python
from real2sim_builder.project import Project, Candidate
from real2sim_builder.automation import reconstruct, save_configuration
from real2sim_builder.observations import register_image, register_views
from real2sim_builder.inference import run_models, build_point_clouds
from real2sim_builder.calibration.hybrid import compare_backends

project = Project(project_path)
# UI와 같은 구조화된 구성. 일반 사용자는 UI를 사용한다.
save_configuration(project, config)
report = reconstruct(project, candidate="auto_1")
```

고급/API용 구성 예:

```yaml
scene_state_id: layout_1
sam:
  python: /path/to/existing/sam/python
  model: /path/to/sam3.1_multiplex.pt
  device: cuda:0
  imgsz: 1024
  timeout_s: 900
da3:
  python: /path/to/existing/da3/python
  model: /path/to/existing/DA3-SMALL/snapshot
  device: cuda:0
  batch_size: 2
  process_res: 280
  timeout_s: 900
objects:
  block:
    prompt: red cube
measurements:
  - id: block
    role: manipulable_object
    kind: box
    dimensions_m: [0.03, 0.03, 0.03] # 형식 예; 실제 측정값으로 바꿀 것
    evidence: [caliper_record]
fitting:
  backend: hybrid # provisional 요청값. 벤치마크 우승/기본값 선정이 아님
  supports: {block: table}
  max_evaluations: 100
```

`measurements`는 box/cylinder/sphere/container다. Container에는 `wall_m`, 선택 `round`, `bottom_diameter_m`를 선언한다. 기존 CAD/Robot은 재생성하지 않는다. 실측으로 보호된 치수와 Robot은 수정하지 않는다. `mass_kg/friction`을 제공하면 `physics_source`를 명시하며 기본 provenance는 estimated다. 새 Object pose는 unknown이며 metric 관측 없이 identity pose를 넣지 않는다.

`anchors.<image_id>`는 `world_points_m`, `uv_px`, `source: measured|calibrated`, `evidence`다. `selections.<image_id>.<object_id>`는 Mask 후보 index 또는 수정 PNG 경로다. `objects.<id>.images.<image_id>.box_xyxy`는 원 해상도 Box hint다. 명시 `image_ids`로 같은 배치의 일부 사진만 모델 추론에 사용할 수 있다. 원본 이미지·관절 기록을 덮어쓰지 않는다.

## 좌표·근거·캐시

- 원 해상도 Mask와 DA3의 실제 resize/center-crop 행렬을 결합한다. 모델의 예측 K를 실제 Calibration으로 부르지 않는다. 현재 metric 역투영은 알려진 undistorted K를 요구한다.
- World Anchor의 optical 깊이와 DA3 깊이 비율을 robust median으로 추정한다. 근거가 없으면 scale=1로 진행하지 않는다. 측정 Anchor를 썼어도 결과 점군은 derived/estimated다.
- 유효 Depth·confidence·Mask 경계를 필터링하고 가시 점만 생성한다. 가려진 면을 관측으로 채우지 않는다. EXIF 방향은 원본을 보존한 Candidate-local upright RGB로 한 번만 변환하고 SAM/DA3/코너 지정에서 같은 좌표를 사용한다. Distortion 자동 제거는 아직 제공하지 않으며 undistorted calibration 자료가 필요하다.
- `inference/sam/<digest>`는 이미지/Object/Prompt·모델·Runtime별 캐시, `inference/da3/<digest>`는 순서 있는 이미지 batch·설정·Calibration·모델별 캐시다. Measurement는 모델 추론 key에 넣지 않으며 바뀐 치수로 정합을 다시 수행한다.
- `reconstruction_observations`는 Candidate-local NPZ/PNG와 SHA·단위·World frame·scale/Camera 근거를 보존한다. Project signature가 이 파일을 포함한다. 실행 설정도 Candidate-local `reconstruction-config.yaml`에 고정한다. Project의 현재 설정 수정은 원본 Evidence 변경으로 취급하지 않으며, 실행에서 쓴 설정은 Candidate signature와 새 Export에 함께 보존한다. Camera/source가 바뀐 점군은 다시 만든다.
- Current와 과거 Export는 자동으로 교체하지 않는다. 최종 패키지는 기존 `export`로 새 경로에 게시하며 파생 NPZ/Mask도 소유 경로로 재배치한다.

## 정합과 결과 읽기

A `landmark`: 기존 `fit_joint_scene`. B `icp_mask`: 고정 크기 Geometry와 가시 점군의 trimmed ICP 후 실제 MuJoCo Mask 보정. C `hybrid`: ICP → 기존 공동 Landmark → Mask 보정. 하나의 정적 배치에서 물체 World pose를 공유한다. 명시 수평 Support가 있으면 roll/pitch/Z를 유지한다. 가림 Mask fragment를 전체 silhouette로 취급하지 않는다.

`fitting/comparison.json`은 동일 입력의 세 초안과 단계별 수치·Runtime과 같은 입력의 per-view RGB/Mask/가시 표면 오차·overlay를 기록한다. 현재 비교는 metric Camera를 고정하며 **Camera/depth bundle adjustment와 독립 성능 근거로 최종 Backend를 선정하는 단계는 미완료**다. 따라서 `winner/default_backend`는 null이다. Ground truth가 없는 경우 mm 정확도를 제공하지 않는다.

`renders/auto_<backend>/previews/<image_id>/`에 반투명 overlay·difference·side-by-side를 저장하고 기존 Builder Compare에서 선택한다. `미검증 초안 새 Export`는 기존 명시 review Export를 호출하며 정상 승인/승격과 구분한다. `reconstruction.json`에는 진행 단계와 필요한 추가 근거가 나온다. `physics/physics.json`은 실제 MuJoCo 수동 물체 중력·접촉 Step만 수행한다. Isaac PhysX Step, Robot Articulation 충돌, Cup block-drop, 독립 물성 검증은 별도 미완료로 표시한다. 정적 렌더나 parser 결과를 Physics-Ready/Task 성공으로 승격하지 않는다.

## 기존 디버깅/검토 인터페이스

`auto-observe`의 기존 HSV/Marker/Landmark proposal/commit과 `candidate ... fit --target joint:scene`은 baseline/특수 보정용으로 유지한다. 새 자동 경로의 필수 Codex 작업이 아니다. `candidate evaluate`, `promote`, `export`, `verify`의 기존 보호·Revision/Scene Contract는 유지한다. 자동 재구성만으로 이 검토를 우회하거나 Teleop/학습을 실행하지 않는다.
