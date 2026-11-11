# Scene 제작 — SimFoundry Stages

현재 VLM/레거시 정리 계약: [Codex VLM 전환](../docs/codex-vlm-migration.md). DA3/SAM/FLUX/Bria/CPD Runtime은 유지하고 시각 판단은 기존 Codex 로그인·모델·추론 강도를 공유한다.

2026-11-09. 사용자는 Scene Prepare에 전체 장면 사진, Object별 참고 사진, 자유로운 Scene Memo를 저장한다. Object 의미·치수·관계는 Codex가 해석하며 Python 자연어 파서는 없다. 기본 Reconstruction은 DA3 Nested/SAM3를 사용하는 SimFoundry Stage1–14이며 MASt3R/COLMAP은 호출하지 않는다.

## 기본 제작

기존 단일 Auto Reconstruction 화면에서 로그인·모델·추론 강도·사용량을 확인하고 생성 시작/이어서 실행을 누른다. 입력 역할과 읽기 쉬운 저장 이름은 유지한다. 다른 배치의 Capture를 Scene 사진처럼 합치지 않는다.

Photo/Video 준비 → DA3 Mixed Depth/K/Pose → 대표 Frame/SAM3 지지면 → World Transform/실측 QA → VLM/SAM3 분해·RGB/Depth Inpainting → Crop/RGBA → Codex+Sandbox Blender Native Mesh → CPD/선택 FoundationPose → 선택 관절 처리 → Scene 조립 → Collision/물성 → 수동적 Physics Probe → 미승인 USD/MJCF Review Package → Simulator/Sensor 연결 순서다. 미지원 관절은 NOT_SUPPORTED, 필요한 Runtime/인증 부재는 NEEDS_RUNTIME으로 멈춘다. 상세 구현 상태와 원본 대비 차이는 [전환 기록](../docs/simfoundry-reconstruction-migration.md)을 따른다.

물체마다 독립 Asset/Instance가 기본이다. 명시된 기존 자산을 재사용하면 새 제작이라고 표시하지 않는다. 형상·재질 수정은 선택한 Object의 새 USDA Version, 배치는 Candidate Pose 변경이다. 기존 공유 Asset bytes는 수정하지 않는다.

## 기존 CLI

```bash
python -m real2sim_builder.cli reconstruct PROJECT --candidate NAME --run-modeling
python -m real2sim_builder.cli modeling-run PROJECT --candidate NAME
python -m real2sim_builder.cli blender-object-author PROJECT --candidate NAME --script author.py --objects OBJECT_ID
python -m real2sim_builder.cli refit-pairs PROJECT --candidate NAME --scene-state LAYOUT --run-modeling
```

`modeling-run`은 저장된 handoff의 단계를 수행한다. 기본 Stage7에서는 Mesh만 제작하고 World Pose는 Stage8/10이 결정한다. Source 기반 `refit-pairs`는 기존 typed Scene plan/비교 수정 loop를 유지한다. 모델/추론 강도/인증은 기존 공식 CLI 환경을 사용하며 원격 API key를 새로 넣지 않는다. 실패·사용량 제한·Stop은 상태와 실제 결과를 남기고 재개한다.

## 제작 기록

Candidate `evidence/index.html`을 UI의 **제작 기록 / 결과 이미지 보기**로 연다. 원본은 Scene/Model 사진임을, Box는 Codex annotation임을, Front/Side/Top/Isometric과 Scene 비교는 실제 렌더임을 구분한다.

```text
evidence/
  01_scene_analysis/attempt_*/
  02_object_modeling/OBJECT/attempt_*/
  03_scene_composition/attempt_*/
  03_first_scene/attempt_*/
  04_iterations/iteration_*/
    real_views/ sim_before/ sim_after/ comparisons/
    changes.json checkpoint.json report.md
  05_physics/attempt_*/
  06_final_comparison/attempt_*/
  index.json index.html
```

최초 Scene/Camera/Manifest/Checkpoint는 이후 수정 전에 저장하고 같은 입력에서 덮어쓰지 않는다. 각 Stage에는 실행 모델·가이드 SHA·실제 파일 SHA·간결한 설계/수정 근거·상태를 연결한다. 미실행 After/Physics 이미지는 만들지 않는다. Stop 후에도 완료 자료와 최초·최선 결과는 남는다.

## 좌표와 보호

Camera plan의 pose는 Camera-to-parent optical frame, Object pose는 기존 Object parent 기준이다. Side는 공유 고정 Pose, Wrist는 기존 URDF Link의 공유 Mount와 실제 measured q/FK를 사용한다. 사진 Camera와 미보정 Mount는 estimated이며 렌즈명·사진 수만으로 보정 완료가 되지 않는다.

실측·보호 관계·기존 Calibration 변경은 Candidate의 기존 preserve/validate에서 거부한다. 확정 접촉은 부모 지지면과 실제 Collision/Anchor를 기준으로 재계산한다. World origin=바닥 가정은 하지 않는다.

## 명시 고급 기능과 Export

Precision Calibration, 명시 landmark/수치 joint fitting, Teleop/Capture, Task/Recipe, Dataset/DataGen/Training 및 MuJoCo/Isaac Runner는 유지한다. 이 기능의 기하·FK·검증 유틸은 제품 Reconstruction에서 Depth backend를 실행한다는 뜻이 아니다.

기존 승인 Scene Revision/Manifest는 불변이다. Candidate의 시각 초안 완료는 승인 Export가 아니며 자동 Promote/Export하지 않는다. 실제 SDK Calibration/로봇 모터 구동도 이 제작 경로에서 수행하지 않는다.

실제 실행 범위와 제한은 [전환 기록](../docs/codex-first-scene-builder.md), 수치·물리 보존은 [SCENE_RULES](SCENE_RULES.md)를 따른다.

### Scene Export 후 Real/Sim 비교

사용자가 명시적으로 Export를 요청하면 검토 중인 Candidate도 기존 `export --candidate NAME --allow-unvalidated`로 새 비교용 Package를 게시할 수 있다. 기존 승인 Revision을 대체하지 않는다. 새 Package는 Real/Sim Scene 선택 목록에 등록되고, `render_type: authored`이면 같은 measured q로 Side/Wrist FK 이미지를 보여주며 Pair 캡처·Reconstruction Memo 재정합에 사용할 수 있다. 화면은 “FK 시각 비교 · 물리 실행 없음”을 표시한다.

이는 Native Articulation 물리 실행과 별도다. `render_type: native`의 중력·충돌·관절 목표 추종은 기존 실행 자산/물성 설정을 요구한다. 비교용 Export를 물리 검증 성공으로 표시하지 않는다. Photo Camera는 Package에 보존하되 Real/Sim 렌더에서는 Side/Wrist만 생성한다.

렌더 대상 선택은 `cameras.camera_roles/select_render_cameras`를 공통으로 사용한다. Image role/camera_type과 저장된 View 등록, 명시 Camera 메타데이터를 대조하며 ID 이름으로 추측하지 않는다. Real/Sim AuthoredRenderer는 확인된 Side/Wrist만 생성한다. `rendering.render_views`는 센서 자원을 재사용하고 Photo Camera는 한 대씩 렌더 후 자원을 해제한다. Isaac은 같은 Scene/SimulationContext를 유지하며 Camera만 활성화·전환하고, MuJoCo는 View 문맥을 닫는다. 이는 MuJoCo/Isaac 비교와 고급 `fit_scene`에 동일하게 적용되며 원 Scene·K/Pose·Calibration·q는 수정하지 않는다. Isaac은 Replicator annotator를 명시 detach한 뒤 자신의 Render Product와 authored prim까지 해제한다. Camera SDK 객체의 지연 소멸에 의존하지 않는다. 사진 RGB 비교는 RGB만, 물체 Mask 비교는 semantic output도 요청하며 Depth는 고급 수치 정합에서 사용한다. 역할 메타데이터가 없는 과거 Package는 이름을 보고 임의 센서를 만들지 않고 명시적인 오류를 반환한다.

## Stage Runtime 설정

[설정 템플릿](config/simfoundry-reconstruction.example.yaml)의 기존 Python/소스/모델 경로를 해당 Workspace 실행 설정에 명시한다. 자동 설치·다운로드는 없다. 영상 후보15장과 DA3 batch4장은 별도다. 4×336, overlap3이 기본이며 퇴화한 Camera 중심 정합은 거부한다. 인증이 없어도 가능한 초기 Stage를 저장하며 Stage7 Codex 또는 Stage3/5 서비스에서 필요한 인증을 안내한다.

Candidate `reconstruction/simfoundry/stage_XX/attempt_XXX/artifact.json`에 입출력 SHA·설정·Runtime·좌표·단위·Mock 여부를 보존한다. 실패는 별도 `failures/` Artifact, 완료된 Stage/하위 Worker는 SHA 검사 후 재사용한다. 기존 제작 기록 버튼은 같은 Evidence index를 연다. 원본·Camera Calibration·측정 q는 바꾸지 않는다.
