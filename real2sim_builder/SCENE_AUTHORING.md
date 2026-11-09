# Scene 제작 — Codex-First

2026-11-09. 사용자는 Scene Prepare에 전체 장면 사진, Object별 참고 사진, 자유로운 Scene Memo를 저장한다. Object 의미·치수·관계는 Codex가 해석하며 Python 자연어 파서는 없다. 제품 Reconstruction은 SAM/DA3/MASt3R/COLMAP을 실행하지 않는다.

## 기본 제작

기존 단일 Auto Reconstruction 화면에서 로그인·모델·추론 강도·사용량을 확인하고 생성 시작/이어서 실행을 누른다. 입력 역할과 읽기 쉬운 저장 이름은 유지한다. 다른 배치의 Capture를 Scene 사진처럼 합치지 않는다.

Codex의 실제 멀티모달 입력 → 구조화 Object/참고 연결 → bpy Script → Sandbox Blender → USDA/Collision/부분 실측 검사 → Scene 배치·추정 Camera → 실제 Simulator 렌더 → Codex 수정 검토 순서다. 초기 Scene 생성에 Depth 성공을 요구하지 않는다.

물체마다 독립 Asset/Instance가 기본이다. 명시된 기존 자산을 재사용하면 새 제작이라고 표시하지 않는다. 형상·재질 수정은 선택한 Object의 새 USDA Version, 배치는 Candidate Pose 변경이다. 기존 공유 Asset bytes는 수정하지 않는다.

## 기존 CLI

```bash
python -m real2sim_builder.cli reconstruct PROJECT --candidate NAME --run-modeling
python -m real2sim_builder.cli modeling-run PROJECT --candidate NAME
python -m real2sim_builder.cli blender-object-author PROJECT --candidate NAME --script author.py --objects OBJECT_ID
python -m real2sim_builder.cli refit-pairs PROJECT --candidate NAME --scene-state LAYOUT --run-modeling
```

`modeling-run`은 저장된 handoff의 단계를 수행한다. 자동 Scene 구성은 reconstruct의 기존 실행 loop가 typed Scene plan 모드로 호출한다. 모델/추론 강도/인증은 기존 공식 CLI 환경을 사용하며 원격 API key를 새로 넣지 않는다. 실패·사용량 제한·Stop은 상태와 실제 결과를 남기고 재개한다.

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
