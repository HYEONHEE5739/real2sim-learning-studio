# SimFoundry Reconstruction 체크포인트와 로컬 Runtime 복원

2026-11-11. `feat/simfoundry-style-reconstruction`의 제품 코드·시험·문서를 보존하는 체크포인트다. 기준 HEAD는 `4ffcac002661710571ad0b20a20715b98587a871`이며 커밋 메시지는 `feat(real2sim): integrate SimFoundry reconstruction and Codex VLM`이다. 이 문서는 소스 보존 범위와 로컬 재설정 방법을 기록하며 전체 Scene 제작 완료를 선언하지 않는다.

## 포함 기능과 검증 경계

- SimFoundry Stage1–14 조율, Artifact/입출력 SHA·Cache Identity, Stop/Resume, 단계별 Runtime/지원 범위 Gate와 기존 UI/Evidence 연결.
- DA3 Nested Mixed 로더, SAM3.1 Adapter, CPU pruning/SBERT·평면/CPD, 로컬 ComfyUI/FLUX·PriorDepth·Bria 호출 경계와 명시 RGB/Depth/Pixel Frame 계약.
- Stage7의 기존 Codex+Sandbox Blender 독립 USD Asset 제작과 Stage8/10 Pose·World 소유권, Native Asset 버전/충돌 검사·Review Package 연결.
- 공통 Codex CLI VLM, 기존 계정/모델/Effort/Usage와 제어 경계, 시각 분석용 제한 정책, timestamp 이벤트·완료 JSON 수집과 Stage5→7 분석 재사용.
- MASt3R/COLMAP 제품 실행기·전용 시험 제거. 저장된 과거 Depth/Camera 메타데이터 Reader와 공통 좌표/metric 수학은 보존.
- 기존 staged 23개의 센서/reference Camera 메타데이터 분리, 순차 Photo 렌더 자원 해제, measured-q Authored Real/Sim 비교와 Export 연결. 이번 범위와 무관한 staged 파일은 발견되지 않았다.
- 필요한 공개 Runtime 설정 템플릿·FLUX API 그래프와 이식 코드의 저작권 고지/Apache-2.0.

이번 Commit 준비에서 **최소 집중 검사 57 passed, 14.44초**, 실패/오류/skip 0을 확인했다. Stage Artifact/재개·손상 차단, 로컬 Runtime Mock·CPU RGB/Depth 계약, VLM Fake CLI/Schema/종료, Camera 역할/자원 수명, 실제 합성 MuJoCo Authored Export/FK 비교와 Qt 표시를 검사했다. Isaac 검사는 Mock/USD Schema 수준이며 Isaac GPU Simulation을 실행하지 않았다. 전체 pytest·AI Forward·온라인 Codex 호출은 이번 체크포인트 작업에서 실행하지 않았다. Python compile과 `git diff --check`도 별도로 확인한다.

과거 전체 1,751개 회귀, 실제 SAM/DA3/PDA/Bria/FLUX 시험과 Codex VLM 51.825초 성공은 각각 해당 기록의 범위다. 이번 최소 시험의 결과로 합산하거나 전체 최신 회귀 통과라고 표시하지 않는다. 주요 근거 문서는 [Stage 전환](simfoundry-reconstruction-migration.md), [알고리즘 보완](simfoundry-algorithm-completion.md), [로컬 연결](local-runtime-validation.md), [FLUX/Bria](flux-inpainting-validation.md), [Codex VLM 전환](codex-vlm-migration.md), [VLM 실행 안정화](codex-vlm-timeout-analysis.md)다. 오래된 설치 계획의 Gemini/원본 SAM3 경로는 당시 조사 기록이며 현재 기본 설정은 아래 템플릿과 실제 Worker를 따른다.

## Git에서 제외한 자료

| 범위 | 처리 |
|---|---|
| `workbench_runs/**` | Scene/Input/Capture/Candidate/Asset/Export, 모든 진단·Cache·실제 Runtime YAML·Qt 환경을 로컬에 보존; Stage하지 않음 |
| 사용자 사진/영상·생성 USD/Asset 바이너리·Dataset | 복사·수정·삭제 없이 로컬에 보존; 새 Commit에 포함하지 않음 |
| HF/모델 Cache, `.pt/.pth/.safetensors/.gguf/.onnx`, Conda/SDK 환경 | 새 Commit에 포함하지 않음. 독립 설치물·라이선스 조건 유지 |
| 인증·Codex 계정/토큰·키·개인 설정·로컬 절대경로 설정 | 새 Commit에 포함하지 않음. 인증 원문은 열람하지 않음 |
| `docs/evidence/**`, 테스트 출력·로그·임시 파일 | 기존 ignore 정책 유지; 로컬 증거로만 사용 |

기존 `.gitignore`가 Workspace/실행 데이터·주요 환경/Cache·인증 파일을 제외하는 것을 확인했다. 디렉터리 단위 `git add -A`를 사용하지 않고 아래 검토한 파일 경로만 Stage한다. 문서의 과거 실행 경로·모델 ID·SHA와 제외된 진단 링크는 재현 이력이며 실제 Runtime 설정 파일이 아니다. 저장소만 Clone하면 해당 링크의 로컬 파일·모델은 없다.

## 로컬 전용 Runtime 재설정

이번 작업에서는 기존 Workspace 설정과 사용자 파일을 변경하지 않았다. 다른 설치 위치에서 사용하는 경우 아래 절차를 **사용자가 별도로 적용**한다. 자동 설치/다운로드/모델 초기화가 포함된 절차가 아니다.

1. 기존 `da3`, `sam31`, ComfyUI/GGUF, 패치된 PriorDepth, CPU Open3D/probreg/SBERT, Bria CPU 환경 및 Builder/Blender·USD 설치를 보존하거나 각 모델 조건에 따라 따로 준비한다. Git Clone/checkout은 이 환경과 가중치를 설치하지 않는다. DA3는 기존 Nested revision `b2359bdf726fb44ef62acca04d629dcf158053e7`과 검증된 Mixed 정책을 유지한다.
2. [공개 YAML](../real2sim_builder/config/simfoundry-reconstruction.example.yaml)은 경로·Scene 옵션을 포함한 **템플릿**이다. `/EXISTING/...`는 자리표시자이며 실제 로컬 경로가 아니다. 이를 그대로 실행하거나 기존 Project/Candidate 설정에 덮어쓰지 않는다.
3. 실제 Workspace 루트가 `WORKSPACE`이고 Scene이 `WORKSPACE/scenes/NAME`이면 설치 기본값 위치는 **`WORKSPACE/runtime/reconstruction.yaml`**이다. 파일 최상위에는 `runtimes`만 둔다. 나머지 `depth`, `support`, `image_preparation`, `pose`, `physics` 등의 Scene 옵션은 기존 Project/명시 실행 설정의 책임이며 Workspace 기본값에 섞지 않는다.
4. 현재 Workspace 파일이 있으면 백업·검토 후 필요한 경로 항목만 직접 갱신한다. 새 파일 작성 예시는 아래처럼 존재하는 파일을 거부하도록 한다. `/EXISTING/...`를 자신의 실제 경로로 검토·변경하기 전에는 Reconstruction을 시작하지 않는다.

```bash
# 저장소 루트에서, 기존 Builder Python과 Workspace 경로를 직접 지정한다.
R2S_PROJECT="$PWD"
R2S_BUILDER_PYTHON=/PATH/TO/EXISTING/builder/bin/python
R2S_WORKSPACE=/PATH/TO/EXISTING/workspace
"$R2S_BUILDER_PYTHON" -B - "$R2S_PROJECT" "$R2S_WORKSPACE" <<'PY'
from pathlib import Path
import sys, yaml
repo, workspace = map(Path, sys.argv[1:])
target = workspace / 'runtime/reconstruction.yaml'
template = repo / 'real2sim_builder/config/simfoundry-reconstruction.example.yaml'
if target.exists():
    raise SystemExit('Existing runtime preserved; review a backup and edit paths manually.')
target.parent.mkdir(parents=True, exist_ok=True)
data = yaml.safe_load(template.read_text())
with target.open('x') as stream:
    yaml.safe_dump({'runtimes': data['runtimes']}, stream, sort_keys=False)
print('Template only: replace /EXISTING paths locally before running Reconstruction.')
PY
```

| Runtime 키 | 로컬에서 연결할 항목 |
|---|---|
| `preparation` / `blender` | 기존 Python / Blender 실행 파일. `runtimes.blender.executable`은 실행 범위에서 기존 선택기를 설정하고 복원 |
| `da3` | 기존 Python, DA3 `src`, Nested Snapshot. Mixed 정밀도 로직·가중치 변경 없음 |
| `sam3` | 기존 Ultralytics SAM3.1 Python / `sam3.1_multiplex.pt`. 원본 SAM3와 동일 API/가중치라고 가정하지 않음 |
| `image_edit` | 기존 ComfyUI Python/소스/모델 디렉터리, 검토한 Workflow 경로. 저장소 기본 그래프는 `real2sim_builder/config/flux-kontext-gguf.api.json` |
| `image_edit_removal` / `image_edit_objects` | 선택 Stage5/6의 전체 Runtime override. 없으면 기존 `image_edit` 사용; 자동 Backend 교체 없음 |
| `decomposition` | CPU 환경 Python / 로컬 SBERT Snapshot |
| `prior_depth` | 패치된 PDA Python/소스 / 실제 vitl+vitb v1.0 Snapshot |
| `rembg` | CPU 환경 Python / 동의한 Bria ONNX. 새 다운로드를 자동 실행하지 않음 |
| `pose` | CPU Open3D/probreg Python, `simfoundry_source`는 기존 고정 전체 SimFoundry checkout. CPU Front 렌더가 실제 읽는 경로 |
| `vlm` | `provider: codex`, `timeout_s: 900`만. 과거 Gemini의 python/source/model_options를 남기면 명시 Legacy Gate에서 거부 |
| `physics` / `simulator` | 기존 Builder/엔진 Python, 필요한 기존 USD 라이브러리 root(`pxr`와 `bin`). Isaac 설치와 일반 Python USD 경계를 구분 |
| `foundationpose` | 선택 기능의 기존 Python/소스. 미준비 상태에서 활성화하지 않음 |

Project/명시 설정이 Workspace보다 우선하며 중첩 키는 병합된다. 따라서 오래된 `runtimes.vlm`을 `provider` 한 줄만 추가해 이전했다고 판단하지 않는다. Project override도 읽기 전용으로 확인하고 필요한 **VLM 블록 전체**를 명시적으로 이전해야 한다. API 키/토큰/비밀번호는 Runtime YAML에 넣지 않는다.

Codex는 기존 Scene Prepare의 로그인·모델·Thinking Effort를 선택한다. Builder의 기존 `REAL2SIM_CODEX_HOME`, `REAL2SIM_CODEX_MODEL`, `REAL2SIM_CODEX_EFFORT` 계약을 유지하며 인증 파일을 저장소로 복사하지 않는다. 홈/SDK/모델의 개인 경로를 제품 소스나 공개 YAML에 하드코딩하지 않는다. 실제 설정과 가중치 경로는 로컬 SHA/Runtime Identity로 검증한다.

설정 확인은 YAML shape/허용 키·경로 존재·실행 권한·가중치 SHA, 각 환경의 `pip check`와 import/Signature부터 수행한다. 모델 생성자/Forward는 별도 실행 범위다. 필요 Runtime이 없으면 기존 `NEEDS_RUNTIME`, 데이터·기하가 부족하면 `NEEDS_MORE_DATA`/`NEEDS_REVIEW`를 유지한다. 8GB GPU에서는 모델 Child들을 순차 실행하고 종료·메모리 반환을 확인한다.

## 아직 미완료 또는 미검증인 기능

- 최신 전체 소스의 전수 회귀는 이번에 반복하지 않았다. 실제 사용자 사진의 새 SimFoundry Stage1–14 연속 E2E, 실제 Scene/승인 Export·Task 성공도 이번 체크포인트의 검증 대상이 아니다.
- VLM 실사용 근거는 합성 컵 1회와 Stage7 작업 입력 전달까지다. 실제 다중 Instance/부분 실측·Model Reference가 있는 새 Scene에서의 의미 정확도와 실제 Mesh 제작은 별도 검증이 필요하다. 과거 VLM 900초 실패의 정확한 원인은 UNKNOWN이다.
- FLUX Kontext는 정확한 Mask conditioning 모델이 아니다. 합성 큐브 제거 개선 후에도 배경 선/경계 품질은 NEEDS_REVIEW이며 실제 다중 Object/Stage5→PDA→Stage6 연속 품질은 미검증이다.
- 실사진 기하·CPD 수렴·절대 scale, Support→Robot World 등록, 공유 Side/Wrist Calibration/Mount·measured q/FK의 독립 Capture 비교를 실제 입력으로 확인해야 한다. 모델의 metric 표시는 실측 정확도 인증이 아니다.
- 새 Object articulation, 추가 CoACD collision 변환은 현재 NOT_SUPPORTED 범위가 있다. Stage10 Support는 명시 크기/두께/Transform이 필요하다. FoundationPose 선택 Runtime 및 실제 Isaac 관통/안정화·Grasp/마찰/Task 정확도는 별도 검증한다.

아래 목록은 이번 체크포인트의 포함/제외 범위다. Push 후 로컬/원격 Commit SHA와 남은 변경은 최종 보고 및 Git 제외 `workbench_runs/diagnostics/simfoundry_checkpoint/`에 기록한다.

## 포함 파일 목록

### 수정 (44개)

- `AGENTS.md`
- `docs/auto-reconstruction-ui.md`
- `docs/automated-reconstruction.md`
- `docs/codex-first-scene-builder.md`
- `docs/geometry-backend-integration.md`
- `real2sim_builder/AUTO_SCENE_FITTING.md`
- `real2sim_builder/CODEX_SCENE_GUIDE.md`
- `real2sim_builder/README.md`
- `real2sim_builder/SCENE_AUTHORING.md`
- `real2sim_builder/SCENE_RULES.md`
- `real2sim_builder/SOURCE_DOCUMENTS.md`
- `real2sim_builder/pyproject.toml`
- `real2sim_builder/src/real2sim_builder/authoring.py`
- `real2sim_builder/src/real2sim_builder/automation.py`
- `real2sim_builder/src/real2sim_builder/calibration/hybrid.py`
- `real2sim_builder/src/real2sim_builder/cameras.py`
- `real2sim_builder/src/real2sim_builder/cli.py`
- `real2sim_builder/src/real2sim_builder/codex_cli.py`
- `real2sim_builder/src/real2sim_builder/evidence.py`
- `real2sim_builder/src/real2sim_builder/export.py`
- `real2sim_builder/src/real2sim_builder/inference.py`
- `real2sim_builder/src/real2sim_builder/isaac_render.py`
- `real2sim_builder/src/real2sim_builder/object_assets.py`
- `real2sim_builder/src/real2sim_builder/rendering.py`
- `real2sim_builder/src/real2sim_builder/ui_reconstruction.py`
- `real2sim_builder/src/real2sim_builder/validation.py`
- `real2sim_builder/tests/test_ai_reconstruction.py`
- `real2sim_builder/tests/test_automation.py`
- `real2sim_builder/tests/test_camera_depth_bundle.py`
- `real2sim_builder/tests/test_codex_guidance.py`
- `real2sim_builder/tests/test_codex_scene_builder.py`
- `real2sim_builder/tests/test_codex_scene_plan.py`
- `real2sim_builder/tests/test_fitting_checkpoint.py`
- `real2sim_builder/tests/test_geometry_ui_integration.py`
- `real2sim_builder/tests/test_reconstruction_flow.py`
- `real2sim_builder/tests/test_reconstruction_ui.py`
- `robot_learning_workbench/src/robot_learning_workbench/recipe.py`
- `robot_learning_workbench/src/robot_learning_workbench/robot/authored_render.py`
- `robot_learning_workbench/src/robot_learning_workbench/robot/real_sim.py`
- `robot_learning_workbench/src/robot_learning_workbench/robot/render_worker.py`
- `robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py`
- `robot_learning_workbench/src/robot_learning_workbench/ui/real_sim_page.py`
- `robot_learning_workbench/tests/test_export_registration.py`
- `robot_learning_workbench/tests/test_real_sim_page.py`

### 신규 (43개)

- `docs/codex-vlm-live-validation.md`
- `docs/codex-vlm-migration.md`
- `docs/codex-vlm-timeout-analysis.md`
- `docs/flux-inpainting-validation.md`
- `docs/local-runtime-validation.md`
- `docs/simfoundry-algorithm-completion.md`
- `docs/simfoundry-checkpoint.md`
- `docs/simfoundry-reconstruction-migration.md`
- `docs/simfoundry-runtime-setup.md`
- `real2sim_builder/config/flux-kontext-gguf.api.json`
- `real2sim_builder/config/simfoundry-reconstruction.example.yaml`
- `real2sim_builder/src/real2sim_builder/calibration/canonicalization.py`
- `real2sim_builder/src/real2sim_builder/calibration/decomposition.py`
- `real2sim_builder/src/real2sim_builder/calibration/frame_selection.py`
- `real2sim_builder/src/real2sim_builder/calibration/simfoundry.py`
- `real2sim_builder/src/real2sim_builder/comfy_edit.py`
- `real2sim_builder/src/real2sim_builder/reconstruction_stages.py`
- `real2sim_builder/src/real2sim_builder/sam31_adapter.py`
- `real2sim_builder/src/real2sim_builder/stage_artifacts.py`
- `real2sim_builder/src/real2sim_builder/stage_runtime.py`
- `real2sim_builder/src/real2sim_builder/stage_workers.py`
- `real2sim_builder/tests/test_codex_vlm.py`
- `real2sim_builder/tests/test_codex_vlm_execution.py`
- `real2sim_builder/tests/test_decomposition_algorithms.py`
- `real2sim_builder/tests/test_depth_geometry_contract.py`
- `real2sim_builder/tests/test_flux_removal_contracts.py`
- `real2sim_builder/tests/test_local_runtime_validation.py`
- `real2sim_builder/tests/test_local_stage_runtimes.py`
- `real2sim_builder/tests/test_pose_canonicalization.py`
- `real2sim_builder/tests/test_render_targets.py`
- `real2sim_builder/tests/test_simfoundry_geometry.py`
- `real2sim_builder/tests/test_stabilization_evidence.py`
- `real2sim_builder/tests/test_stage_artifacts.py`
- `real2sim_builder/tests/test_stage_compilation.py`
- `real2sim_builder/tests/test_stage_decomposition.py`
- `real2sim_builder/tests/test_stage_mesh_handoff.py`
- `real2sim_builder/tests/test_stage_pipeline.py`
- `real2sim_builder/tests/test_stage_pixel_transforms.py`
- `real2sim_builder/tests/test_stage_pose.py`
- `real2sim_builder/tests/test_stage_runtime.py`
- `real2sim_builder/tests/test_stage_video_authoring.py`
- `real2sim_builder/third_party/SIMFOUNDRY_NOTICE.md`
- `real2sim_builder/third_party/SimFoundry-LICENSE`

### 삭제 (2개)

- `real2sim_builder/src/real2sim_builder/sfm.py`
- `real2sim_builder/tests/test_sfm_geometry.py`
