# Codex-First Scene Builder와 제작 기록

2026-11-09. 현재 로컬 체크포인트 `2f327e9c40e64f54b42ebd1751bd6f6bfa91a6db`에서 `feat/ai-scene-authoring-v2`로 구현한다. 이전 `review/auto-real2sim-scene-memo`의 automation.py 호출 경계를 읽어 참고했지만 Checkout/Reset/Worktree로 현재 코드를 대체하지 않았다. 첨부 사양의 Commit/Push 금지는 사용자의 이번 “브랜치 만들어 구현 후 Push” 지시로 대체한다. Merge·Force Push·실물 구동은 허가 범위가 아니다.

## 결정과 이유

제품의 기본 입력은 Scene Photos / Model References / 자유로운 Scene Memo다. 부분 Depth와 Metric 등록 성공을 초기 Scene 제작의 필수 조건으로 두던 경로는 폐기한다. Codex가 실제 이미지를 보고 Instance·형상·배치·추정 Camera를 해석하고, 기존 Sandbox Blender와 실제 Simulator 결과를 다시 검토한다.

새 Agent Framework/Manager/DB나 두 번째 실행기를 만들지 않는다. 기존 `automation.reconstruct` / `authoring.run_codex_modeling` / Candidate / Asset Library / Renderer / Checkpoint를 사용한다. `visual_evidence.py`는 실제 파일을 보존·표시하는 저장 책임만 가진다.

다른 대안인 Depth gate 완화·부분 점군의 외접 사각형으로 임의 scale 인증은 선택하지 않았다. 사진 기반 추정 Scene은 만들되 보호 실측·Calibration·measured q/FK를 수정하지 않으며 정확도/물리 인증을 별도로 남긴다.

## 실제 호출 흐름

```text
기존 Scene Prepare / Real-Sim 버튼
  → 단일 ReconstructionDialog: 공식 로그인/모델/Thinking/사용량/Stop/Resume
  → reconstruct 또는 refit-pairs: 기존 Project lock / Source Identity
  → modeling_tasks → run_codex_modeling(분석; 실제 --image)
  → typed Object/Reference/실측/관계/Task 계획 검증
  → 필요한 Object만 bpy → 기존 Sandbox Blender
  → 실제 USDA/Visual/Collision/치수 검사 + 4방향 렌더
  → run_codex_modeling(compose_scene=True)
  → apply_scene_plan → 기존 editing.apply / Candidate.save / preserve
  → alignment_metrics: 실제 MuJoCo 또는 기존 Isaac child
  → 최초 Scene과 실제 렌더/closure Checkpoint 동결
  → fitting_review → 같은 run_codex_modeling(review_fitting=True)
  → typed Scene plan 수정 또는 선택 새 Asset Version → 재렌더
  → View별 비퇴행 best Checkpoint / Stop·오류·예산 복원
  → 실제 passive physics / 센서 비교 / 최종 Evidence
```

초기 자동 호출에 `run_models`, `run_geometry`, `predict_views`, `metric_plane`, `fit_clouds`, `fit_scene`은 없다. UI의 SAM/MASt3R/COLMAP 필수 검사·단계 라벨도 제거한다. `inference.py`, `sfm.py`의 과거 NPZ/재투영/진단 수학, `calibration/*`의 명시 고급 Calibration·landmark·FK·검증 기능은 사용처가 달라 보존한다. 이 보존은 제품 Depth Backend 지원이라는 뜻이 아니다. 환경·가중치·기존 Cache를 삭제하거나 재설치하지 않는다.

## 입력·수정 계약

Scene Memo 의미는 Codex가 해석한다. Python은 실제 Schema, 출처, 인용, 단위, 참조 ID, 원본 이미지 bounds, rigid transform/K/공유 Camera 조건을 검증한다. 원격 CLI에는 실제 RGB를 `--image`로 첨부하고, 입력 manifest에 SHA와 역할을 기록한다. 경로 텍스트만 전달하고 이미지 분석 성공으로 처리하지 않는다.

Object별 Scene 관측과 Model Reference는 분리한다. 같은 cup도 별도 Instance이며 자동 제품 공유를 하지 않는다. 기존 명시 Asset 선택은 보존하고 재모델링은 선택 Object의 새 버전이다. Blender의 보이지 않는 뒷면/내부는 estimated다.

Scene 구성/수정 Schema는 `object_poses`, `cameras`, `support_anchors`, 선택 `lighting`, `needs`다. Pose는 parent 기준이다. Camera는 정확한 camera ID, 원본 해상도, K/왜곡, Camera-to-parent optical pose와 실제 image_ids를 참조한다. measured/calibrated·Robot geometry는 기존 보호 경로에서 변경을 거부한다. Side는 고정 공유, Wrist는 하나의 URDF Link Mount와 measured q다. 사용자 입력에 Camera 숫자 편집 양식을 추가하지 않는다.

Compound/Mesh 지지면의 기존 확정 관계에 Anchor가 없으면 기존 접촉 수학을 우회하지 않고 Codex에 보완을 요청한다. `support_anchors`는 기존 관계의 Object ID·Support ID와 실제 Collision 로컬 좌표의 점/단위 법선·영상 근거다. 제안한 평면과 실제 Collision 극점의 일치를 원 허용 오차로 검사한다. 이미 저장된 Anchor·관계·허용 오차 변경은 거부한다. 이 검사는 유한 지지면의 마찰·전도 안정성 인증이 아니다.

## Evidence와 재개

Candidate의 `evidence/index.json` / `index.html`이 제품 기록이다. 첫 Scene과 수정 Before는 변경 전에 보존한다. 실제 이미지가 없는 중단은 이미지 없는 STOPPED/FAILED로 남긴다. 각 Stage에는 Stage ID/status, run_identity, 입력 SHA, 가이드 SHA/버전, 실제 모델, 파일·이미지 SHA, 간결한 설계/수정 근거, 미확인 사항을 연결한다. 비공개 사고 과정이나 raw CLI 계정/토큰 출력을 저장하지 않는다.

Scene/Memo/개선 Memo가 같은 재개와 입력이 다른 새 실행은 구분한다. 이전 최초 Scene과 기록은 덮어쓰지 않고 새 attempt로 추가한다. 최선 선택은 같은 train View·q·Object 집합에서 View별 잔차가 악화되지 않은 경우만 한다. holdout은 수정·모델링·최선 선택에 사용하지 않는다. Scene closure와 설정·비교 결과를 함께 복원하며, 생성한 새 자산 버전과 실패 기록은 삭제하지 않는다.

Real/Sim의 Source Identity·이번 Capture ID·Reconstruction Memo를 유지한다. 새 비교는 measured q로 렌더하며 과거 runtime Sim q 차이를 새 FK 입력으로 사용하지 않는다. Pair 모드는 원 Scene Memo나 다른 Revision을 대체하지 않는다.

## 기존 기능 보존

읽기 쉬운 저장 경로, 두 기존 Project, 입력 역할, 원문 Memo, Codex 계정/모델/사용량, Blender Sandbox/Library, SO-ARM101 URDF/q, MuJoCo/Isaac, Capture/Teleop/Precision Calibration, Task/Dataset/DataGen/Training, 불변 Export 계약을 유지한다. 새 실행은 기존 `auto-version` Candidate에서 수행하며 새 Worktree/Workspace/사용자 Scene은 만들지 않는다.

## 검증 기록

아래는 진행 중 검증이며 실제 실행/전체 회귀 완료를 미리 선언하지 않는다. 최종 결과와 실제 Evidence 경로는 실행 후 이 절에 추가한다.

- 읽기 전용으로 이전 브랜치의 automation.py 844줄과 현재 분리 모듈의 호출 소유권을 비교했다.
- RED→GREEN: 실제 Native 렌더가 Depth Backend 없이 진행되는 경로, typed Camera/Object 보호, 실제 이미지 CLI 전달, 최초 Scene 동결, 새 Memo run 분리, 실제 Before/After 개선·best, 단일 UI 제작 기록.
- 실제 Blender Script → USDA + Front/Side/Top/Isometric(320×320) 시험을 통과했다. 이 시험의 Script는 통제된 입력이며 실제 원격 모델의 형상 이해 시험과 구분한다.
- 최초 연결 회귀는 108 passed / 10 failed였다. 새 WAITING_FOR_CODEX_SCENE 상태 허용 누락과 이전 Depth/Solver 실행을 요구하는 시험 계약을 구분해 보완 중이다. Skip/XFail로 처리하지 않는다.

### 기존 auto-version의 실제 실행에서 수정한 연결 오류

기존 Candidate `auto_mast3r_colmap`에서 설치 Codex CLI 0.166.0 / gpt-6.1-sol / low와 저장된 Builder 로그인을 사용했다. 실제 Scene 8장·Model Reference 2장·기존 Side/Wrist Capture 8장의 18개 RGB를 이미지 인자로 전달했다. `request_008`의 실제 분석은 기존 독립 Object 9개를 유지하고 두 Model Reference를 `wrist_camera_assembly`에만 연결했다. 하우징의 rigid Link attachment는 미확정으로 남겼다. 실제 분석과 Schema/Fake CLI 시험을 구분한다.

`request_009`의 최초 구성 응답은 Model Reference를 Scene 관측/Camera로 포함해 검증에서 거부했다. 해당 응답과 실패 기록을 보존하고, 실제 관측 역할에 따른 동적 image/camera/Object/frame enum을 출력 Schema에 연결했다. `request_010`은 Model Reference를 제외한 Scene Photo 8대와 공유 Side/Wrist 2대, 총 10대의 Camera 구성을 반환했다. Camera·배치는 estimated이며 원 Calibration·measured q/FK를 변경하지 않는다.

실제 책상 Collision은 상단 Z=0인 상자형 Mesh지만, 기존 접촉 계산은 compound/mesh의 지지면을 추측하지 않는다. 최초 실행은 확정 접촉 7개의 Anchor가 없어 중단됐다. 새 typed `support_anchors` 보완 요청에 `request_011`이 실제 Collision 로컬 좌표의 점/법선 7개를 반환했고 원 허용 오차로 검증·적용했다. 기존 관계 삭제·완화나 Mesh를 primitive로 바꾸는 처리는 하지 않았다.

이어 초기 Native compile에서 Wrist의 기존 비영 왜곡 계수를 pinhole MJCF로 내보내 거부되는 오류를 재현했다. 원 Camera를 유지한 채 임시 pinhole 설명으로 Native 모델을 만들고, 원 계수로 기존 `distort_render`를 적용하도록 연결했다. Native 초기 Collision query도 같은 임시 설명을 사용한다. 실제 Package Export의 pinhole 검증은 유지한다. 실패한 실행과 그 시점의 Evidence는 삭제하지 않았다.

### 최종 소스 회귀와 실제 엔진 실행

마지막 Native 왜곡 수정까지 포함한 세 패키지 전체 회귀는 **1,644 passed / 실패 0 / 오류 0 / skipped 0**, 448.80초, 기존 torchvision 경고 4회다. 근거는 로컬 `/tmp/real2sim-codex-first-checks/native-verified-suite.xml/log`다. 중간 전체 1,643개 통과와 구별한다. 이후 소스 동작을 바꾸지 않은 문서 갱신은 이 수치를 새로운 회귀 실행으로 표시하지 않는다. 변경 Python의 bytecode 없는 AST compile과 `git diff --check`도 확인했다.

실제 Blender bpy→USDA→4방향 렌더와 실제 Native Before/After·최초/최선 Checkpoint·중단 회귀는 통제된 입력/가짜 원격 응답 시험이다. 이를 실제 모델의 언어·형상 이해 정확도로 표시하지 않는다. 실제 `auto-version`에서는 기존 자산을 재사용했고, Scene/Camera 추정과 검토만 실제 원격 Codex 응답을 사용한다.

기존 Candidate에서 실제 MuJoCo RGB 비교 **16개(Scene Photo 8, Side 4, Wrist 4)**를 생성했다. 최초 Scene은 `evidence/03_first_scene/attempt_002`의 `scene_state.json`, `checkpoint.json`, 실제 렌더 16개로 동결했다. 앞선 attempt_001은 지지면 부족 실패 기록이다. 초기 Collision query는 `QUERIED`, physics step 0, 접촉 0개였다. 질량·마찰 부족으로 동역학은 실행하지 않았으며 무접촉 결과를 물리 안정성 인증으로 표시하지 않는다.

같은 Candidate의 객체·Geometry·Side/Wrist Camera와 measured q를 사용해 실제 소유 Kit child에서 Isaac 비교 **8개(Side 4, Wrist 4)**를 생성했다. 252.66초, physics step 0, 정상 종료다. 읽기 전용 렌더 설명에서 Photo Camera만 제외했으며 Candidate를 저장하지 않았다. 전후 Candidate Scene SHA가 동일했다. 자료는 `fitting/isaac-codex-first/scope.json`, `result.json`, `metrics.json` 및 소유 `isaac-*/previews`에 있다. 새 Scene·Workspace·Worktree나 실물 Capture를 만들지 않았다.

### 실제 최종 판단과 재개 가능한 범위

실제 `request_012`는 원본/Sim/Overlay/Difference를 검토한 뒤 **`needs_data`**를 반환했다. Wrist 전체 Capture에서 실제 그리퍼는 아래쪽으로 들어오지만 Sim Robot이 위쪽을 가리고, 블록 순서·종이/컵 위치가 다르다고 지적했다. Side의 한 Capture에서도 jaw 윤곽 차이를 지적했다. 하우징의 Robot Link parent·housing-to-link Transform과 optical-to-housing 관계가 미확정이며, 얕은 Photo 시점의 컵/책상 투영 반전은 Camera 방향 문제로 판단했다. 이를 임의의 per-q Mount, 실측/q/URDF 변경 또는 허용 오차 완화로 통과시키지 않았다.

최종 상태는 **NEEDS_MORE_DATA / Candidate OPEN / Resume 가능**이다. 실제 원격 요청은 분석·구성 계열 4회(`008`–`011`, 거부 응답 포함), 검토 1회(`012`)다. 기존 자산 9개를 재사용했고 이번 실제 실행에서 신규 Asset Version은 만들지 않았다. 실제 검토가 수정 대신 추가 근거를 요청했으므로 **실제 Iteration Before/After 수정은 실행되지 않았다.** 최종 선택은 최초 유효 Scene이며 최선 Checkpoint `fitting/checkpoints/checkpoint_001`을 보존했다. 통제된 실제 MuJoCo Before/After 개선 회귀와 이 실제 실행의 미수정 종료를 구분한다.

| 확인할 자료 | 기존 Candidate 안의 위치 |
|---|---|
| UI 제작 기록 전체 | `evidence/index.html` / `index.json` |
| 실제 이미지 분석·Object 연결 | `evidence/01_scene_analysis/attempt_001` |
| 재사용 Object별 Manifest·Geometry | `evidence/02_object_modeling/<Object ID>/attempt_001` |
| 최초 전체 Scene·16개 실제 렌더·closure | `evidence/03_first_scene/attempt_002` |
| 최종 MuJoCo 원본/Sim/Overlay/Difference | `fitting/final/previews/<image_id>` |
| 실제 Codex 검토·미해결 근거 | `modeling/codex/request_012/answer.json`, `fitting/codex-review.json` |
| 최종 Scene·실행/재개 상태 | `candidate_scene.yaml`, `reconstruction.json` |
| 초기 Collision 및 미실행 동역학 | `physics/physics.json`, `evidence/05_physics` |
| 실제 Isaac Side/Wrist 비교 | `evidence/05_isaac_sensor_render/attempt_001`, `fitting/isaac-codex-first` |
| 최종 선택 Scene의 실제 이미지 | `evidence/06_final_comparison`의 마지막 attempt |

위 경로의 루트는 `workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap`이다. 원본 사진·실행 자료는 Git 제외이므로 저장소만 내려받으면 로컬 이미지가 없다. 이 문서에 사용자 사진·바이너리를 복제해 Commit하지 않는다. `scene_plan.needs`에는 구성 응답 당시 Codex가 렌더를 수행하지 않았다는 문장도 역사적으로 남아 있다. **그 이후 Builder가 실행한 실제 16개 Native 렌더·Collision query 및 별도 Isaac 8개 비교는 위 Evidence가 근거**이며, 과거 단계의 문장을 최종 실행 여부로 해석하지 않는다.

최종 보존 대조는 기존 **5,146개 파일에서 누락 0, 보호 대상 변경 0, 기존 Cache 변경 0**이다. 현재 Candidate와 auto-version의 실행 상태·추가 history 기록만 바뀌었다. 두 Project history의 기존 prefix SHA는 동일하다. Evidence에 포함한 실제 파일 303개의 SHA도 모두 일치했다. 근거는 `/tmp/real2sim-codex-first-checks/preservation-final.json`이다. 환경 재설치·모델 다운로드·실물 모터 구동·기존 Package 수정·Merge·Force Push는 수행하지 않았다.

이번 변경은 Codex-first 제작/검토/증거/재개 경로와 실제 Scene 초안을 제공한다. 현재 auto-version의 Wrist/Side 정밀 정합, rigid Camera 하우징 attachment, 수치 정확도·독립 검증·물성·Grasp/Task 성공, 새 승인 Export는 완료하지 않았다. 구현 회귀 통과나 초안 렌더를 그 완료 증거로 확대하지 않는다.
