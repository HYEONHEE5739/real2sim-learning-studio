# Codex-First Scene Builder와 제작 기록

> 후속 기본 엔진: [SimFoundry Stage 전환](simfoundry-reconstruction-migration.md). 이 문서는 이전 Codex-First 구현 이력과 유지되는 Source 기반 Real/Sim 경로를 기록한다.

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

초기 자동 호출에 `run_models`, `run_geometry`, `predict_views`, `metric_plane`, `fit_clouds`, `fit_scene`은 없다. UI의 SAM/MASt3R/COLMAP 필수 검사·단계 라벨도 제거한다. `inference.py`의 저장 NPZ/재투영 수학, `calibration/*`의 명시 고급 Calibration·landmark·FK·검증 기능은 사용처가 달라 보존한다. 이 보존은 제품 Depth Backend 지원이라는 뜻이 아니다. 환경·가중치·기존 Cache를 삭제하거나 재설치하지 않는다.

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


## 2026-11-09 후속 — 실제 반복 정합과 Real/Sim Export 연결

사용자는 초안 생성 뒤 실제 Simulator 비교·수정 반복을 수행하고, Scene을 Export해 Real/Sim에서 추가 캡처·정밀 정합과 물리 확인을 이어가는 흐름을 명확히 요청했다. 이전 실행은 최초 렌더와 첫 검토까지만 수행했고 실제 수정 반복·Export는 하지 않았다. 앞 절의 구현/시험 통과를 이 실제 반복의 완료로 해석하지 않는다.

새 Model Reference `wrist_camera_img3.jpg`가 기존 Evidence에 등록된 상태에서 후속 작업을 시작했다. Scene/Model/Capture 원본 19개를 유지한다. 실제 Qt ReconstructionDialog의 생성 시작 버튼을 눌러 QProcess→CLI→Backend로 실행한다. 이 UI 검증은 화면 없는 Qt에서 버튼 이벤트를 실행하며 사람이 화면을 직접 클릭한 것으로 표시하지 않는다. 실제 모델은 설치 catalog의 gpt-6.1-sol / high를 선택했다.

반복 연결에서 다음 문제를 재현·수정했다.

- 새 이미지 분석 후에도 예전 scene_plan을 유지하던 경로: 예전 계획은 feedback으로 보존하고 새 구성을 요청한다.
- 비교 입력에 실제 시점별 FK/Camera 변환이 없던 경로: actual render_context에 optical Camera/parent/Robot Link 변환을 넣는다. 이미지 기반 공유 Mount 추정은 estimated이며 정확한 실측 Transform을 초안 수정의 필수 조건으로 요구하지 않는다.
- 같은 자산의 초기 attachment를 매번 다시 적용해 나중 Pose 수정을 되돌리던 경로: 동일 부착 선언은 재적용하지 않는다.
- UI CLI의 --config가 원 Project 입력을 덮어쓰던 경로: Candidate 실행 override로 사용한다.
- 비영 왜곡의 Package 생성과 Real/Sim MuJoCo 비교가 단절된 경로: 원 authored Camera·Calibration을 보존하고 native pinhole 설명 및 camera_projection.json을 내보낸다. Authored Real/Sim 렌더가 원 왜곡을 적용한다. Native 동역학의 pinhole 요구를 임의 해제하지 않는다.
- 비교용 Export를 Real/Sim에서 선택해도 Articulation 필수 조건으로 실행을 거부하던 경로: 명시 render_type=authored일 때 기존 FK renderer로 Live 비교와 Pair 캡처를 실행한다. UI는 “FK 시각 비교 · 물리 실행 없음”을 표시하고 physics step 0을 기록한다. render_type=native의 기존 Articulation/physics stepping·접촉 경로는 유지한다. 비교용 패키지는 동역학/Task 실행 인증이 아니다.

새 실제 분석 request_013은 세 Model Reference를 wrist_camera_assembly에 연결하고 gripper Link 기준의 공유 estimated attachment를 반환했다. 실제 구성·반복·Export 결과와 최종 회귀는 완료 후 아래에 기록한다.

비교용 패키지의 Real/Sim 연결은 현재 선택된 `render_type=authored`에서만 FK 투영을 사용한다. Live 상태와 Pair에는 `state_application=authored_measured_fk`, `physics_steps=0`, 정확히 적용한 measured q를 남긴다. Native 선택은 종전 물리 stepping을 계속 사용하며, 비교용 패키지를 물리 Articulation이라고 바꾸지 않는다. 왜곡 원본 Camera는 `authored_scene.json`과 별도 manifest-covered `camera_projection.json`에 남고, native 파일만 pinhole 투영이다. 기존 별도 Native 동역학의 Camera/질량/Collision 요구를 없애지 않았다.

패키지 기반 AuthoredRenderer와 Builder의 색 변환 불일치도 실제 픽셀 회귀로 재현했다. 비교용 AuthoredRenderer는 별도 MuJoCo Pose/Camera/색 변환 구현 대신 기존 Builder Renderer 또는 IsaacRenderer를 재사용한다. 같은 패키지·같은 q의 Builder/RealSim Side RGB가 정확히 일치하고, Wrist 왜곡도 같은 픽셀 변환을 적용하는 시험을 포함한다. 관련 Export·Real/Sim child·Native stepping·Qt 표시 시험 20개가 통과했다.

실제 구성 request_014는 Scene Photo Camera 8대와 공유 Side/Wrist 2대를 반환했다. Wrist의 방향·시선·공유 Mount를 바꾸고 기존 하우징 Link 부착을 유지했다. 실제 16개 View 렌더 이후 이전 실행의 동일 4개 Capture RGB/q와 대조하면 Wrist MAE는 각각 0.4359→0.1735, 0.5394→0.2857, 0.1884→0.1833, 0.5450→0.1739로 감소했고 윤곽 IoU도 네 View 모두 증가했다. Side 네 View의 MAE/IoU는 유지됐다. 이는 동일 train 영상의 렌더 개선이며 독립 Calibration/물리 정확도 증명이 아니다.

실제 검토 request_015는 `numeric`을 반환했다. 공유 Wrist Mount의 추가 보정과 컵이 뒤집혀 보이던 external_view_013 Camera의 방향 수정을 제안했다. 실측·q·Object Pose·하우징 attachment·K/왜곡은 그대로 두는 제안이다. 적용 전 실제 16개 Before 이미지는 `evidence/04_iterations/iteration_001`에 저장했다. After와 추가 검토·최종 채택 결과는 실제 실행 후 기록한다.

### 재개 실행에서 확인한 실제 결과

UI 버튼→실제 QProcess 실행은 2,597.16초 뒤 종료됐다. request_013 분석과 request_014 구성, request_015의 실제 수정 제안, 그 수정에 대한 MuJoCo 16 View Before/After까지 실행했다. request_016의 다음 원격 검토는 실제 `USAGE_LIMIT`으로 실패했다. 재조회에서도 300분 한도 잔여 0%였으며, 해당 시점 초기화 예정은 2026-11-09 18:14:53 KST였다. 이 과거 조회를 이후의 현재 계정 상태라고 해석하지 않는다.

`iteration_001`은 16개 Before/After와 Scene/Checkpoint가 모두 존재한다. 원본 RGB와 저장된 Before/After에서 같은 MAE/RMSE/edge IoU를 다시 계산한 결과, 공유 Wrist 수정은 네 Capture 모두 개선되고 Side 네 Capture는 동일했다. 함께 제안된 external_view_013 사진 Camera 수정 한 개가 기존 최선 기준에서 퇴보해 전체 시도는 채택되지 않았고 checkpoint_002로 복원됐다. 기준 완화나 원본 수정은 하지 않았다. 실제 수치와 탈락 View는 `evidence/04_iterations/iteration_001/comparison-summary.json`이다.

원격 사용량 때문에 새로운 판단은 요청하지 않는다. 이미 실제 Codex가 반환한 독립 Camera 수정 둘을 분리하고, 퇴보한 external_view_013은 최선으로 유지한 채 **동일한 Wrist 수정 수치만** `iteration_002`로 재생했다. 새 AI 응답이나 새 Mount 추정을 만든 것이 아니다. 원 응답 SHA·생략한 Camera·로컬 재검증 목적은 `evidence/04_iterations/wrist-only-replay.json`에 기록한다. 이 재생의 실제 채택·Export 결과는 아래 후속 결과를 따른다.

검토 예외 이후 Candidate 보고서는 FAILED인데 Project/UI 상태는 RUNNING으로 남던 문제도 실패 시험으로 재현하고 수정했다. 완료된 증거와 최선을 유지하면서 Project의 실패/중단 상태·stage·error code를 동기화한다. 관련 37개 회귀가 통과했다.

명시적 비교용 Export `exports/scene-codex-first-fit_001`을 생성했고, Manifest SHA `7172e25b93785b3f6ab0665424c65e9841f835e46eff4d383743b4c288c1acf8`로 검증했다. 원 Candidate/기존 Export를 바꾸지 않고 새 Revision을 등록했다. 실제 Real/Sim MuJoCo 렌더 자식이 기존 measured q를 받아 Side/Wrist 이미지를 반환했으며 Real/Sim 선택 목록에도 표시됐다. 실제 장치를 열거나 합성 관측을 실물 Capture로 등록하지 않았다.

Isaac의 첫 Real/Sim 검증에서는 필요 없는 고해상도 Photo Camera까지 Sensor로 생성해 GPU 메모리 할당 실패가 발생했다. 해당 소유 자식 프로세스만 종료하고 로그를 보존했다. 원 Scene/Package에 Camera를 삭제하지 않고 Real/Sim 임시 설명에서 Side/Wrist만 생성하도록 수정했다. Camera 수 제한과 픽셀 일치·Pair child를 포함한 관련 15개 시험이 통과했다. 실제 재시험 결과는 아래에 기록한다.

### Camera 역할과 렌더 자원 수명

2026-11-09 후속. Real/Sim의 Camera ID 목록 필터를 공통 메타데이터 기반 선택으로 교체했다. `camera_roles`는 Image role/camera_type, 저장된 View 등록, 명시 Camera camera_type/purpose를 대조한다. 이름이 side인 사진 Camera도 reference로 처리하며 임의 이름의 Side/Wrist도 센서로 판별한다. 역할 충돌·미기록은 추측하지 않고 오류로 반환한다. Model Reference는 외형 context다.

`select_render_cameras`는 원 Scene을 바꾸지 않은 임시 렌더 설명만 반환한다. Real/Sim 기본 대상은 실제 센서이며, `render_views`는 MuJoCo/Isaac의 비교·고급 수치 정합에 같은 정책을 적용한다. 공유 센서 문맥은 재사용하고 사진은 요청한 Camera 한 대씩 렌더 후 닫는다. 센서와 사진 사이 전환도 이전 Camera의 렌더 자원을 먼저 해제한다. Isaac은 한 Scene/SimulationContext를 유지하며 Camera prim은 요청 시 활성화하고 Render Product/annotator만 전환한다. MuJoCo는 해당 View의 렌더 문맥을 닫는다. Isaac은 Replicator annotator를 직접 소유하고 detach→Render Product destroy→authored prim 제거→문맥 종료를 수행한다. SDK Camera의 지연 소멸에 의존하지 않으며 일부 detach가 실패해도 나머지 자원 해제를 시도한다. RGB 비교는 불필요한 Depth/분할 버퍼를 만들지 않는다. 최초 Scene/사진 8장의 Pose/K·등록·Evidence/Checkpoint는 그대로 보존한다. 새 회귀와 실제 엔진 검증 결과는 아래에 기록한다.

### 채택한 최선과 새 비교용 Export

`iteration_002`의 실제 16개 Before/After를 원본 RGB로 다시 평가해 퇴보 View 0개를 확인했다. Wrist MAE 네 개는 각각 0.285683→0.272126, 0.173896→0.164766, 0.173529→0.168729, 0.183292→0.173895이며 Side와 사진은 유지됐다. `checkpoint_003`을 선택했고 상태는 검토 예산 종료 `REVIEW_BUDGET_EXHAUSTED`다. 이는 request_015가 이미 반환한 동일 Wrist 수정만 재생한 결과이며 새 원격 판단은 없다. 자료는 `evidence/04_iterations/iteration_002/comparison-summary.json`이다.

명시 요청에 따른 새 비교용 패키지는 `exports/scene-codex-first-fit_002/scene.json`, Manifest SHA `afdf0d434c2a2431af65e5124037db86dd4776c61908a33c3ba5ad2d7fd9be72`다. 앞선 `_001`은 수정하지 않았다. 새 패키지는 Real/Sim 목록에 등록됐고 실제 MuJoCo RenderProcess의 measured-q Side/Wrist 렌더를 확인했다. `render_type=authored`, physics step0이며 Native Articulation 동역학·마찰·Grasp/Task 인증이 아니다. 실물 장치는 열지 않았다.

카메라 역할 수정 후 실제 MuJoCo 비교는 사진8장과 센서8 View를 모두 렌더했다. 생성 문맥9개(사진별8개, 공유 센서1개), 최대 동시 Camera2개, 종료 후 열린 문맥0을 확인했다. 원 Candidate Scene SHA는 불변이다. Isaac의 중간 진단에서 지연 소멸된 Camera의 빈 버퍼 오류와 고해상도 RGB+Depth+분할의 8GB GPU 초과를 보존했다. 최종 코드는 Replicator annotator를 직접 해제하고 비교에 필요한 출력만 요청한다. 고해상도 사진 한 대라도 모든 AOV를 요구하면 이 GPU의 용량을 넘을 수 있으며, 미사용 출력을 없애는 것은 RGB/Mask/Depth 손실 기준을 완화하는 변경이 아니다. 최종 실제 Isaac 결과와 전체 회귀는 검증 후 기록한다.

후속 실제 시험에서 사진별 Isaac SimulationContext까지 반복 생성하는 방식은 6개 View 뒤 native exit139로 종료돼 전체 통과로 기록하지 않았다. 같은 기존 Renderer 안에서 Scene/Geometry 문맥을 유지하고 `release_cameras`로 요청한 Camera의 annotator/Render Product만 해제하는 방식으로 수정했다. Reference Camera prim은 비활성 상태의 설명으로 남으며 상시 센서/버퍼가 아니다. 최종 재시험은 같은 입력과 기준으로 수행한다. 중간 실패·로그·사진은 `evidence/camera-role-verification/isaac_001`~`005`에 보존한다.
