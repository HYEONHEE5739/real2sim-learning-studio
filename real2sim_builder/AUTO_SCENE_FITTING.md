# Codex-First Auto Reconstruction

2026-11-09. 현재 제품 실행은 사진·Memo → Codex → Blender → 실제 렌더 → Codex 수정의 단일 경로다. 과거 Depth/Metric 등록을 전제로 한 자동 복원 설계를 교체했다. 명시 수치 Calibration API는 유지한다.

## 입력과 실행

Scene Prepare의 Scene Photos / Model References / Scene Memo를 저장하고, 단일 Auto Reconstruction 화면에서 공식 Codex 로그인·모델·Thinking·사용량을 확인한다. 생성 시작/재개, Stop, 제작 기록 보기 버튼을 사용한다. SAM/DA3/MASt3R/COLMAP 환경 설정은 필요하지 않다.

기존 CLI도 같은 `automation.reconstruct`를 사용한다.

```bash
python -m real2sim_builder.cli reconstruct PROJECT --candidate CANDIDATE --run-modeling
python -m real2sim_builder.cli refit-pairs PROJECT --candidate CANDIDATE --scene-state LAYOUT --run-modeling
```

수동 handoff 상태는 WAITING_FOR_CODEX_ANALYSIS / WAITING_FOR_CODEX / WAITING_FOR_CODEX_SCENE이다. `--run-modeling`은 기존 CLI 경계를 연속 사용한다. 분석·제작·구성 호출은 최대6회, 비교는 최대3회가 기본이다. 무제한 원격 재시도는 하지 않는다.

## 실제 실행 순서

1. 원문 Memo·SHA와 Scene/Model RGB를 고정한다. 실제 CLI `--image`로 Instance/참고 연결/부분 실측/Robot attachment를 분석한다.
2. 필요한 독립 Object Asset만 bpy Script를 생성하고 기존 Sandbox Blender와 USDA/Collision/실측 검사를 통과한다. 재사용은 REUSED로 구분한다.
3. Codex가 실제 Asset dimensions와 사진으로 Object Pose, Virtual Camera K/pose, 필요한 ambient를 추정한다. `apply_scene_plan` → 기존 보호 Candidate edit를 사용한다.
4. Depth/Metric gate 없이 실제 Simulator를 렌더하고 첫 전체 Scene을 동결한다.
5. Codex가 real/sim/overlay/difference를 비교하고 구체적인 Scene plan 수정, 선택 재모델링, needs_data, complete를 선택한다. 자동 Depth Solver를 연달아 실행하지 않는다.
6. Iteration마다 원본 RGB·Before/After·변경 값·이유·Checkpoint를 보존한다. 모든 train View에서 비교 가능한 개선만 최선으로 보존하고, 악화/Stop/실패/예산 소진에는 최선을 복원한다.
7. passive physics와 Source Capture의 same-measured-q Side/Wrist 비교는 실제 결과를 기록한다. 독립 정확도·물리·Task 인증과 구분한다. Candidate는 OPEN이며 Promote/Export는 명시 작업이다.

## 기록과 소유권

`Candidate/evidence/index.html`은 네트워크가 필요 없는 실제 이미지 목록, `index.json`은 Stage/status/run_identity/입력 SHA/가이드/모델/실제 파일 목록이다. 첫 Scene은 같은 입력의 재개에서 불변이며 입력이나 Memo가 다르면 별도 attempt가 된다.

- `authoring.py`: 원문 분석, Schema/Parser, Object 참고 연결, Codex/Blender handoff, typed Scene plan.
- `automation.py`: 기존 lock/control/호출 예산/Checkpoint 안의 단일 실행 경로.
- `visual_evidence.py`: 실제 파일만 동결·표시하는 작은 저장 모듈. Agent/Manager/DB가 아니다.
- `rendering.py` / `isaac_render.py`: 실제 RGB와 Object Front/Side/Top/Isometric.
- `candidate.py` / `editing.py` / `object_assets.py`: 원본 보호, 불변 Asset Version, 검증.

## 상태의 의미

사진의 K/Pose/형상은 estimated다. 낮은 이미지 오차는 Camera Calibration/물리/Task의 증명이 아니다. Side/Wrist가 없어도 사진 Scene을 제작할 수 있지만 센서 정확도는 NOT_VERIFIED다. Box annotation은 SAM Mask가 아니며 부분 점군이나 생성 RGB를 실측 근거로 만들지 않는다.

상세 계약은 [Codex 가이드](CODEX_SCENE_GUIDE.md), [Scene 제작](SCENE_AUTHORING.md), [수치·보호 규칙](SCENE_RULES.md), [구현·검증 기록](../docs/codex-first-scene-builder.md)을 따른다.
