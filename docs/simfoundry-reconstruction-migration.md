# SimFoundry 방식 Reconstruction 전환

> 2026-11-10 후속: VLM은 공통 Codex CLI로 전환했고 MASt3R/COLMAP 실행 코드는 제거했다. 현재 설정과 검증 범위는 [Codex VLM 전환](codex-vlm-migration.md)을 따른다. 아래 과거 실행·설치 기록은 당시 상태다.


**최신 상태(2026-11-10):** Phase F–H 보완과 전체1,751개 회귀 결과는 마지막 절 및 [알고리즘 보완 기록](simfoundry-algorithm-completion.md)을 따른다. 아래 2026-11-09 수치는 당시 실행 기록이다.

2026-11-09. 사용자 첨부 마스터 사양 기준. 기준 브랜치 `feat/ai-scene-authoring-v2`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`. 기존 staged 23개를 보존하고 `feat/simfoundry-style-reconstruction`를 생성했다. Commit/Push/Merge하지 않는다. 기존 Codex-First 기본 경로를 그대로 둔 채 이름만 바꾸는 방식은 사용하지 않는다.

**Stage 실행 경로는 구현했으며 원본과의 기능 차이는 아래 IMPLEMENTED/PARTIAL/BLOCKED로 구분한다. 전체 기능 완료를 뜻하지 않는다.** 실제 사용자 Scene의 E2E, 모델 추론, Isaac/로봇 구동은 이번 범위에서 금지한다. 기존 진단의 실제 DA3 수치는 과거 근거이며 이번 Synthetic/Mock 검증과 구분한다.

## 원본·변경 경계

원본: [NVlabs/SimFoundry](https://github.com/NVlabs/SimFoundry/tree/9e34ebefcd020583fbb755a8b57268dce78eca26), 고정 Commit `9e34ebefcd020583fbb755a8b57268dce78eca26`. 조사 소스·설정115개와 SHA는 Git 제외 `workbench_runs/diagnostics/simfoundry_migration/sources/manifest.json`에 있다. 사용한 포트의 저작권/Apache-2.0은 `real2sim_builder/third_party/`에 보존한다.

기존 미커밋 diff/index, baseline/RED/GREEN 실행 근거는 같은 진단 폴더에 보존한다. 제품 경로에 로컬 사용자 절대 경로나 진단 결과 의존성을 넣지 않는다. 사용자 Scene/Input/Candidate/Cache/Asset/Export를 재작성하지 않는다.

## 원본 Stage 대응

아래 원본 파일은 `scripts/pipeline/A_reconstruction/stages/` 기준이며, 연결 구현은 각 Phase 후 갱신한다.

| Stage | 원본 파일/함수와 알고리즘 | 입출력/런타임 | 프로젝트 소유권/차이 |
|---|---|---|---|
| 1 | `1b_process_raw_video.py:main/subsample_images`, FFmpeg 전체 프레임 추출 후 sorted stride subsample | RGB/video→frame/index/timestamp/contact sheet; FFmpeg/ffprobe | evidence 원본 보존, Candidate 안에만 추출. 기존 Scene Photo도 동일 frame artifact |
| 2 | `2_run_depth.py/2b_run_da.py:main`, `pipeline/depth_backends.py:DA3Backend.run/_plan_chunks/_merge_chunk_npzs` | 단일 inference 또는 overlap camera center Umeyama Sim(3), depth도 scale; Nested 모델/Python/CUDA | inference child/고정 Mixed 정책. 4×336 기본, overlap>=3, 퇴화 거부. 독립 World를 그대로 합치지 않음 |
| 3 | `frame_selection.py:score_frame/rank_frames/select_canonical_frame`, `3_segment_ground_plane.py:main` | support mask, object height/footprint/components/sharpness/clipping, hybrid VLM; Open3D 1cm RANSAC(선정2000회/최종1000회), SAM3/Gemini | 대표 frame ID 고정; SAM/plane child. 관측 근거 없는 바닥 추정 없음 |
| 4 | `4_unify_world_frame.py:main` | normal/centroid, R_tilt@R_roll@T(-origin), Camera→support +Z 명목 frame; cloud | calibration 수학. Robot World와 연결은 별도. 원 roll/tilt 수식 잔여 법선 오차도 보고. 실측 코너 QA는 보정 없이 별도 |
| 5 | `5_decompose_scene.py:main/compute_object_removal_order` | Gemini 식별→SAM3 Instance→hull/occlusion/support/near-first removal→RGB editing→Depth re-estimation/alignment; Gemini/FLUX/Imagen, DA3, ray runtime | 런타임·인증 없으면 NEEDS_RUNTIME. Memo는 context, Model Reference는 외형만. 다른 알고리즘 무음 대체 금지 |
| 6 | `6_upsample_object_images.py:main/call_image_editing_model` | Mask crop/padding/RGBA→서비스 image editing/upsampling | 기존 Image/Native 자산. 미실행 업샘플을 완료라 표시하지 않음 |
| 7 | `7_generate_object_meshes.py:main` | 원 Hunyuan/Pixal mesh→독립 object mesh | **의도적 교체:** 기존 authoring.run_codex_modeling + Sandbox Blender, USD/USDA/Native. World Pose를 결정하지 않음 |
| 8 | `8_match_object_poses.py:sample_fits/main` | Mask/Z/K→surface sampling10000, OBB diagonal pre-scale, diag/30 voxel, farthest sampling, SO(3) multistart rigid CPD(update scale false/true), target→source NN 후보, inverse fit; optional FoundationPose | Native mesh adapter, probreg/Open3D/선택 FoundationPose 런타임. 실측 축은 scale로 바꾸지 않음. ICP로 대체하지 않음 |
| 9 | `9_articulate_objects.py:main` | articulated object 판정/외부 articulation workflow | 선택적 provider, 기존 SO-ARM101 URDF/FK 보존. 미지원 관절 명시 |
| 10 | `10_compile_scene.py:main` | 먼저 local mesh scale/rotation/translation, 다음 selected Camera→support transform | 기존 Candidate/Scene/Instance 참조, source native frame 유지 |
| 11 | `11_make_objects_sim_ready.py:main` | collision decomposition, visual/material/mass metadata | 기존 visual/collision/물성 provenance. OmniGibson 의존은 기존 엔진 경계로 교체 |
| 12 | `12_stabilize_physics.py:stabilize_object/stabilize_all_objects/main` | passive gravity steps, 이동/회전 threshold와 max step, 침투 등 | 기존 MuJoCo/Isaac adapter. 실제 step과 Mock, unknown 물성을 분리 |
| 13 | `13_import_usd.py:main` | 원본 Omniverse native object import/USD | 기존 불변 USD/Package exporter, 승인 여부와 package 생성을 분리 |
| 14 | `14_create_og_scene.py:main/validate_scene_assets` | 원본 OG scene/robot/camera 구성 | **의도적 교체:** 기존 USD/Isaac/MuJoCo/Real-Sim. Side/Wrist 실제 센서만 기본 생성, Photo는 reference metadata 보존 |

## 계약과 Phase 현황

- 기존 `automation.reconstruct`, Project lock, control/checkpoint, Candidate를 실행 소유자로 유지한다. 새 Manager/DB/별도 앱은 만들지 않는다.
- `stage_artifacts.py`: stage_id/status/input/output manifest·SHA/runtime/config/coordinate/units/provenance/warnings/needs/error를 검증한다. COMPLETE는 실제 파일이 있어야 하고 symlink/경로 이탈/손상을 거부한다. Mock provenance를 real로 승격하지 않는다.
- `calibration/simfoundry.py`: optical backprojection, World-to-Camera 역변환, overlap>=3 Sim(3) 병합, roll/tilt R@T, 명시 코너 실측 QA. rank<2 Camera overlap은 NEEDS_MORE_DATA이며 scale을 발명하지 않는다.

| Phase | 상태 / 근거 |
|---|---|
| A | 원본 소스/설정 조사, Artifact 계약과 baseline 완료. 시작 전체 **1,665 passed**, warning4, 412.70s |
| B | Stage1–4 처리·실제 Child 호출 경로·원본 수학 연결. DA3/SAM 추론은 이번에 NOT_TESTED |
| C | Stage5–8 VLM/SAM/RGB editing/PriorDepth/Native Mesh/CPD/FoundationPose 경계, 기존 Codex+Blender handoff 연결. 원본 대비 차이는 아래 표 |
| D | Stage9 명시 미지원 Gate, Stage10 Scene/Camera 합성, Stage11–14 기존 Native 검증/Physics/Export/Renderer 연결. 새 관절·완전한 물리 안정화는 미완료 |
| E | 기존 UI의 Stage 진행/계정/Stop/Resume·Evidence 연결. Synthetic 및 전체 회귀 결과는 아래 최종 검증에 기록 |

## Stage 구현 상태와 실제 실행 경계

IMPLEMENTED는 코드·입출력·호출 경계 구현이며 실제 모델의 정확도를 뜻하지 않는다. Stage Artifact의 COMPLETE는 그 실행의 입출력 계약 완료 상태다. 구현 범위 PARTIAL인 Stage도 지원된 입력에서는 COMPLETE Artifact를 만들 수 있으며 provenance로 Mock 여부를 구분한다.

| Stage | 구현 상태 | 현재 구현 / 원본과 남은 차이 | 실제 Runtime 실행 여부 |
|---|---|---|---|
| 1 | IMPLEMENTED | Photo EXIF 정규화, 명시 scene_video의 FFmpeg/PTS/index/SHA/stride/contact sheet. 서로 다른 layout 거부. 기본 영상 후보15와 추론 batch 분리 | Child 경로 구현, Photo Synthetic 검사. 실제 사용자 영상 NOT_TESTED |
| 2 | IMPLEMENTED | 기존 성공 구성의 CPU strict FP32→BF16→두 Head/Camera 출력 FP32→CUDA, 4×336/overlap3 기본, 명시8/448 예산·VRAM Gate, W2C/Z/K/conf/affine, 원본 Umeyama merge. rank<2 overlap 추가 거부 | 실제 모델 추론 NOT_TESTED. 이전 DA3 실측은 이번 성공 근거로 재사용하지 않음 |
| 3 | IMPLEMENTED | 원본 FrameScore/rank 함수 포트, 높이/면적/component/clipping/sharpness/support/plane 평가, hybrid VLM shortlist, SAM3 + RANSAC 2000/1000·1cm | Synthetic Mask/Plane만 검사, 실제 SAM/VLM NOT_TESTED |
| 4 | IMPLEMENTED | 원본 roll/tilt 순서와 World points. 명시 4코너 실측 QA, 자동 scale 보정 없음. Robot World는 명시 등록 Gate | 수학 Synthetic 검증; 실측 정확도 NOT_TESTED |
| 5 | PARTIAL | Instance VLM→SAM3 point Mask→원본 denoise/수축 hull/ray removal order→RGB editing→DA3 geometric Z→PriorDepth conditioning/known-depth splice. 원본 RGB 정합 비율 .10 Gate. 원본의 SBERT/CLIP category refresh·Mask 중복 pruning/분리·세 종류 removal retry 전체 정책은 아직 동일하게 이식하지 않음. 낮은 original-pixel agreement는 묵인 대신 NEEDS_REVIEW | 실제 Provider 호출 코드 구현, Mock 흐름만 실행. 원격 인증/필수 로컬 모델 확인 필요 |
| 6 | PARTIAL | 원본 context .5/focus .1 margin, mask RGBA/nearest alpha, crop/padding/원관측 보존, 실제 editing provider. Native Codex 입력은 square crop 사용; 원본 provider-native ratio/rembg·선택 infill 전체 분기는 미이식 | Mock image service와 실제 이미지 처리 검사 |
| 7 | IMPLEMENTED | 의도된 교체: 기존 Codex CLI/Sandbox Blender/Asset 검증. 준비 RGB/Mask/Crop/Depth SHA를 실제 tasks References에 연결. Mesh만 제작하고 최종 Pose는 Stage8/10 소유 | Codex/Blender 결과만 Mock. 이번 실제 Mesh 제작 정확도 NOT_TESTED |
| 8 | PARTIAL | 원본 surface10000/OBB/diag÷30 voxel/farthest/multistart rigid CPD/scale/one-sided NN/inverse pose. 선택 FoundationPose register adapter. 실측 scale 거부. 원본 mesh front canonicalization/tilt baking 전체 분기는 미이식 | Native OBJ 생성과 CPD 입출력 Synthetic 검사. 실제 CPD/FoundationPose NOT_TESTED |
| 9 | BLOCKED | 새 Object 관절 생성은 NOT_SUPPORTED. 요청이 없으면 applicable=false이며 수행했다고 하지 않음. 원 articulate-anything/Hunyuan/partfield를 도입하지 않고 기존 SO-ARM URDF/FK 보존 | 새 관절 Runtime 없음 |
| 10 | PARTIAL | scale→mesh-to-selected-Camera→support→명시 Robot World 순서. Reference Camera Pose/K/Source/affine 보존. 미측정 Asset scale은 새 USDA 버전, 기존 root identity 유지. 기존 로봇·지지 자산 보존. 새 support surface의 독립 Asset 재구성은 자동 완성하지 않음 | Synthetic 조립/새 버전/원 Asset SHA 검사 |
| 11 | PARTIAL | 기존 별도 Visual/convex·compound Collision 엄격 검사, 기존 Blender Collision 재사용. 명시 또는 VLM mass/friction은 출처·불확실성 유지. 원본 OG asset conversion/추가 VHACD를 새로 이식하지 않음 | Mock VLM 및 기존 Native 검증만 |
| 12 | PARTIAL | 소유 Child→기존 MuJoCo/Isaac passive probe, bounded 1..2500 step/관통·최종속도/settled. 실제 step와 Mock 분리. 원본 최대10000 step의 순차 고정·자세 반영 및 slip/topple 검증 전체는 미구현. Probe 뒤 안정화 Pose를 승인 Scene으로 자동 적용하지 않음 | 이번 Physics Worker는 Mock. 실제 Isaac 물리 안정성 NOT_TESTED |
| 13 | IMPLEMENTED | 기존 USD/MJCF/Manifest/closure/실제 parser 검사를 사용한 미승인 Review Package. passed=false, 자동 Promote 없음. 기존 execution package 등록 계약 재사용 | 작은 Synthetic native package 생성·검증; 실제 사용자 Export 미생성 |
| 14 | PARTIAL | package 검증과 실제 MuJoCo/Isaac child import/render 경계. 공통 metadata Camera 선택, Side/Wrist만 기본 센서·Photo reference 유지. 현재 없는 Sensor Calibration/FK/Robot World를 자동 생성하지 않음. 기존 Real/Sim Source/측정 q/Capture 경로 보존 | Simulator worker만 Mock. 실제 센서 정합/Isaac/Task NOT_TESTED |

## Artifact·중단·재개

`automation.reconstruct` 기본 경로는 실제 `_run_stage_pipeline`이며, `refit_only=True`만 기존 Source 기반 `_refit_reconstruct`로 들어간다. MASt3R/COLMAP은 신규 경로에서 호출하지 않고 기존 파일·진단 API를 보존한다.

Candidate의 `reconstruction/simfoundry/stage_XX/attempt_XXX`에 결과를 저장한다. 완료 Artifact는 입력·출력 파일 SHA, 설정, 가이드 SHA, 구현 코드 SHA, Runtime/모델/소스 SHA를 검증한 뒤 재사용한다. 실패의 부분 파일과 타입/상태/needs/error는 별도 `failures/stage_N/attempt_XXX`에 복사해 보존한다. 상위 Stage가 실패해도 완료된 하위 Worker 응답은 검증 후 재사용해 원격 호출을 반복하지 않는다. Candidate Scene이 저장된 Stage 체크포인트 밖에서 바뀌면 자동 재개를 거부한다.

DA3의 실제 upper_bound resize→patch14 resize→batch center crop을 Worker가 frame별 affine으로 반환한다. 서로 다른 Chunk가 다른 pixel grid를 만들면 Depth/K를 몰래 resize하여 합치지 않고 NEEDS_MORE_DATA로 중단한다. Cache 재개 전에도 현재 Candidate의 Asset SHA를 검증한다. Runtime 인증값은 Candidate 설정을 쓰기 전에 거부하며 timeout은 유한한 1..3600초만 허용한다.

Memo와 Model Reference는 Stage2 입력이 아니다. 이를 추가해도 DA3를 다시 실행하지 않는 회귀가 있다. Memo는 Stage5/7, Model Reference와 신뢰 가이드는 Stage7의 Identity에 들어간다. Source Photo/실측의 변경을 임의로 이전 Cache와 섞지 않는다. GPU 모델은 기존 `inference._run_worker`의 소유 프로세스 그룹/timeout/Stop 경계를 통해 순차 실행한다.

Stage별 결과는 기존 Candidate Evidence index에 추가하며 단일 제작 기록 버튼으로 연다. 실제 이미지가 없는 단계는 이미지를 만들어 채우지 않는다. 모든 Mock Artifact와 Evidence에 execution=mock을 남기고, Mock Physics의 actual_physics_steps는 0이다.

## Runtime과 외부 서비스

제품에 개인 경로를 하드코딩하지 않았다. [기존 설정 템플릿](../real2sim_builder/config/simfoundry-reconstruction.example.yaml)의 `runtimes`를 Workspace 설정으로 제공한다. 경로는 설치/모델 탐색이나 다운로드 권한을 뜻하지 않는다. 파일 경로가 없거나 dependency import가 실패하면 해당 Stage에서 NEEDS_RUNTIME으로 보존한다. Model/Provider credentials는 환경에만 두고 설정 Manifest에 넣지 않는다. Nested model_options의 인증 필드도 거부한다.

필요한 Runtime:

- Stage1: 기존 FFmpeg/ffprobe.
- Stage2: 기존 DA3 Nested 고정 Snapshot, Torch/CUDA BF16. 이번에는 재로딩/추론하지 않았다.
- Stage3/5: 별도 설치된 SimFoundry Python 소스, SAM3/로컬 가중치, Open3D. Stage3 hybrid와 Stage5/11 VLM은 Gemini 인증 필요.
- Stage5/6: Gemini image 또는 원본 Imagen/FLUX provider 인증/로컬 모델, PriorDepthAnything 로컬 모델·원본 API, ray hull 의존성. 조건부 geometric backend는 DA3를 별도 Child로 재사용한다.
- Stage7: 기존 Codex 로그인/선택 모델·추론 강도, Blender/bwrap Sandbox. 로그인/Quota 실패는 Stage1–6의 완료 Cache를 지우지 않는다.
- Stage8: Open3D/probreg, 선택 FoundationPose/ScorePredictor/PoseRefinePredictor/nvdiffrast 및 로컬 weights.
- Stage12/14: 기존 Builder/scene-contract/USD/MuJoCo, 선택 IsaacLab/Kit 환경. 새 관절 Runtime은 지원하지 않는다.

`runtime-inventory.json`은 설치 디렉터리·배포 메타데이터만 읽은 기록이다. 그 결과를 모든 Provider의 import/인증/실행 성공이라고 해석하지 않는다. 인증을 조회하거나 원격 서비스를 호출하지 않았다. 이번 검증에서 실제 DA3/SAM3/VLM/Codex Mesh/FoundationPose/Isaac Physics/PickPlace 정확도는 모두 **NOT_TESTED**다.

## 검증과 보존

최종 소스에서 세 패키지 전체 회귀를 실행했다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short --junitxml=workbench_runs/diagnostics/simfoundry_migration/release-full.xml
```

- **최종 1,726 passed / 실패0 / 오류0 / skipped0**, 기존 torchvision 경고4회, Console 기준510.23초. 시작 baseline1,665개보다61개 늘었으며 skip/xfail로 우회하지 않았다.
- Stage 관련 **60 passed**(87.76초). 실제 Orchestrator/Manifest/Native Mesh/Scene/Package 코드를 사용하고 무거운 Worker만 Mock으로 교체했다. Stage1–14 각각의 Runtime 누락14개·Stop14개, 총28개 재개 경우가 포함된다. 이전 Stage Artifact SHA와 완료 Worker 호출 횟수 유지, 손상 차단을 검사했다.
- 기존 Scene Prepare→같은 Dialog→CLI 연결, 계정/모델/사용량/로그아웃 시작, 14개 진행 라벨, 기존 Source Real/Sim 경로 회귀를 포함한다. 기존 Codex Scene plan/수치 시험은 명시 고급 `_refit_reconstruct` 경계에서 계속 검사하며 기본 경로로 표시하지 않는다.
- Synthetic native USD/MJCF Review Package의 실제 exporter·closure·MuJoCo/USD parser 검사는 실행했다. 새 Physics/Simulator Worker는 Mock이며 실제 Physics Step=0이다. 이를 Isaac 또는 실사진 Scene 성공으로 보고하지 않는다.
- FrameScore와 `_object_mask_above_plane/_sharpness/_normalize/rank_frames` 5개는 고정 원본 소스와 AST가 같음을 별도 대조했다(`ported-source-comparison.json`). 조사한 원본115개 소스/설정의 SHA를 보존한다.
- 변경 Python32개를 bytecode 생성 없이 compile했고 `git diff --check`도 통과했다. wheel 설치/실제 Provider 초기화 검증을 실행했다는 뜻은 아니다.

중간 RED/수정 기록은 보존했다. Native Asset root에 scale을 붙여 기존 identity-root 검증에 막힌 경우는 root를 유지하고 새 버전 내부 자식 Xform으로 scale을 적용하도록 수정했다. 구형 기본경로의 대기 상태/가이드 버전 fixture는 새 Stage1·Guide 계약으로 갱신했고 테스트를 제거하지 않았다. 전처리 affine, 미설정 Runtime의 CWD 탐색 방지, 인증값 저장 전 거부, Cache가 Asset 손상을 숨기는 경우도 RED→GREEN으로 확인했다. 마지막 보완 전 전체1,722개 실행과 최종1,726개 실행을 구분한다.

보존 대조: 기존 `workbench_runs/scenes`와 공용 `object_assets`의 **7,786개 파일 SHA/크기 변경0·누락0·신규파일0**. 원래 Candidate/Cache/Input/실측/발행 Package를 다시 쓰지 않았다. 앞선 DA3 진단 폴더는 쓰기 대상으로 열지 않았으며, 이 두 root 밖의 과거 진단/SDK 전체는 시작 SHA ledger의 대상이 아니므로 전수 대조했다고 하지 않는다.

기준/최종 HEAD는 `4ffcac002661710571ad0b20a20715b98587a871`, 현재 브랜치는 `feat/simfoundry-style-reconstruction`이다. 시작 staged23개의 diff SHA `5e259fbe6370626a3b608b1b55bc3d12205ab69650731b1994f1c9b2184c3bb6`가 그대로이며 이번 수정은 추가 미커밋 변경이다. Commit/Push/Merge·설치·모델 다운로드·실제 사용자 E2E·실물 구동을 하지 않았다. 남은 부분을 전체 구현 완료로 선언하지 않는다.

검증 자료는 Git 제외 `workbench_runs/diagnostics/simfoundry_migration/`의 `baseline.xml/log`, `release-focused.xml/log`, `release-full.xml/log`, `verification-summary.json`, `preservation-after.json`, `change-inventory.json`, `compile-check.json`이다.

## 실제 사진 E2E 전 남은 항목

1. 영상만 있는 입력과 Scene Memo를 함께 사용하는 경우의 Stage7 의미 분석/참조 Schema 연결은 별도 확인이 필요하다. 현재 Photo 기반 Synthetic Smoke와 영상 프레임 추출 어댑터가 이를 자동으로 증명하지 않는다.
2. 기존 설치만 사용해 각 Provider API/로컬 가중치·환경·인증을 별도로 확인한다. 이번 요청은 실제 모델 실행을 허용하지 않으므로 실행 성공을 추정하지 않는다.
3. Stage5의 원본 category/mask pruning·removal retry, Stage6 provider crop/rembg 분기, Stage8 canonicalization의 미이식 범위를 해결하거나 별도 승인된 범위로 명확히 제한한다.
4. Stage9 새 관절과 Stage10 새 지지면 Asset, Stage12 안정화 Pose 적용·미끄럼/전도 검증은 미완료다. 기존 로봇 World와 DA3 Support의 명시 등록을 준비한다.
5. 실측 코너·공유 Side/Wrist Calibration/FK와 독립 Capture를 확보해 metric QA·동일 measured-q 비교를 수행한다. 현재 추정 단위를 물리 정확도로 승격하지 않는다.
6. 실제 E2E는 별도 사용자 지시 후 수행한다. 이번 Synthetic Smoke 성공만으로 실사진 Scene이나 승인 Export를 만들지 않는다.

## 현재 Stage 함수 대응

기본 진입점은 `automation.reconstruct → _run_stage_pipeline`이다. 아래 처리 함수는 모두 `reconstruction_stages.py`에 있고, 소유 Child는 `stage_workers.py`, 기존 process control 연결은 `stage_runtime.py → inference._run_worker`다.

| Stage | 현재 처리 함수 | Worker / 기존 모듈 |
|---|---|---|
| 1 | `prepare` | `video`; evidence Photo/명시 Video |
| 2 | `depth` | `da3`; calibration.simfoundry merge/pixel affine |
| 3 | `support` | `support`, `vlm`; calibration.frame_selection |
| 4 | `world` | calibration.simfoundry support_transform/metric_qa |
| 5 | `decompose` | `vlm`, `segments`, `removal`, `image_edit`, `da3`, `depth_inpaint` |
| 6 | `prepare_objects` | `image_edit`; 실제 RGBA/Crop 처리 |
| 7 | `meshes` | authoring modeling_tasks/run_codex_modeling/attach_modeled_assets; hybrid.surface_mesh |
| 8 | `poses` | `cpd`, 선택 `foundationpose` |
| 9 | `articulate` | 요청 없음 명시 applicable=false, 요청 있음 NOT_SUPPORTED |
| 10 | `compile_scene` | Candidate.save, object_assets.scaled_asset_operation |
| 11 | `simulation_ready` | scene.validate/support_metrics, 선택 `vlm` 물성 추정 |
| 12 | `stabilize` | `physics` → validation.physics_probe; Isaac은 child AppLauncher |
| 13 | `package_scene` | export_revision/verify_package; passed=false Review |
| 14 | `simulator_integration` | `simulator` → 공통 Camera 선택 + Renderer/IsaacRenderer |

## 변경 파일

시작 staged23개의 diff는 보존했다. 아래는 시작 index 이후의 수정/신규 파일이며 이전 기능 변경과 이번 Stage 전환을 구분한다.

기존 파일 수정 (26개):

- `AGENTS.md`
- `docs/codex-first-scene-builder.md`
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
- `real2sim_builder/src/real2sim_builder/evidence.py`
- `real2sim_builder/src/real2sim_builder/inference.py`
- `real2sim_builder/src/real2sim_builder/object_assets.py`
- `real2sim_builder/src/real2sim_builder/ui_reconstruction.py`
- `real2sim_builder/tests/test_automation.py`
- `real2sim_builder/tests/test_camera_depth_bundle.py`
- `real2sim_builder/tests/test_codex_guidance.py`
- `real2sim_builder/tests/test_codex_scene_builder.py`
- `real2sim_builder/tests/test_codex_scene_plan.py`
- `real2sim_builder/tests/test_fitting_checkpoint.py`
- `real2sim_builder/tests/test_geometry_ui_integration.py`
- `real2sim_builder/tests/test_reconstruction_flow.py`
- `real2sim_builder/tests/test_reconstruction_ui.py`
- `robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py`

신규 파일 (19개):

- `docs/simfoundry-reconstruction-migration.md`
- `real2sim_builder/config/simfoundry-reconstruction.example.yaml`
- `real2sim_builder/src/real2sim_builder/calibration/frame_selection.py`
- `real2sim_builder/src/real2sim_builder/calibration/simfoundry.py`
- `real2sim_builder/src/real2sim_builder/reconstruction_stages.py`
- `real2sim_builder/src/real2sim_builder/stage_artifacts.py`
- `real2sim_builder/src/real2sim_builder/stage_runtime.py`
- `real2sim_builder/src/real2sim_builder/stage_workers.py`
- `real2sim_builder/tests/test_simfoundry_geometry.py`
- `real2sim_builder/tests/test_stage_artifacts.py`
- `real2sim_builder/tests/test_stage_compilation.py`
- `real2sim_builder/tests/test_stage_decomposition.py`
- `real2sim_builder/tests/test_stage_mesh_handoff.py`
- `real2sim_builder/tests/test_stage_pipeline.py`
- `real2sim_builder/tests/test_stage_pixel_transforms.py`
- `real2sim_builder/tests/test_stage_pose.py`
- `real2sim_builder/tests/test_stage_runtime.py`
- `real2sim_builder/third_party/SIMFOUNDRY_NOTICE.md`
- `real2sim_builder/third_party/SimFoundry-LICENSE`

## 2026-11-10 후속 — Phase F–H 보완 및 검증

Stage5 Category VLM/SBERT·SAM3 pruning/Instance 분리·세 종류 제거 재시도, Stage6 Provider-native crop/Infill/Upsample/RemBG/검증, Stage8 Tilt/Front/Yaw와 Native 새 버전·역보상 Pose를 보완했다. 기존 Runner/Artifact/Codex+Sandbox Blender/Scene Prepare/Real-Sim을 재사용했다. Stage10은 명시된 크기·두께·Transform의 독립 Support Asset과 재개를 지원하며, Stage12는 실제 Pose 시계열·안정 구간과 matching review를 통한 Candidate 반영을 기록한다. Stage14는 안정화 후 최신 Candidate snapshot을 사용한다.

Photo/Video-only 각각에 Memo·Model Reference를 전달하고 Side/Wrist의 Synthetic measured q를 정적 DA3 입력과 분리하는 네 조합을 검증했다. Video 프레임을 Stage7에서 Project 원본 사진으로 다시 찾던 오류를 수정했다. Imagen3는 원본 Stage5 제거용이며 Stage6 종횡비 계약이 없는 설정은 명시적으로 NOT_SUPPORTED다.

최종 전체 **1,751 passed / 실패0 / 오류0 / skipped0**, 기존 경고4개, 517.15초다. 직전 전체1,748개와 마지막 보완 후1,751개를 구분한다. 이전 전체1,726개 대비 시험25개 증가·기존 시험명 삭제0이다. 보호 대상 Scene/공용 Asset **7,786개 파일 변경0·누락0·신규0**, 원래 staged23개 diff SHA 불변, HEAD/브랜치 불변이다. 변경 Python52개 compile 및 diff whitespace 검사도 통과했다. 기존 변경16개·신규7개·삭제0개는 이번 Phase 시작 대비 수치이며 이전 Stage 전환 변경과 구분한다.

DA3/Open3D/MuJoCo/USD의 실제 import/API와 Synthetic CPU physics/parser를 검사했다. DA3 Mixed 함수 AST는 작업 시작 전과 동일하다. 원본 SimFoundry/SAM3/Encoder·PriorDepth·probreg·RemBG·FoundationPose에는 설정/의존성 누락이 확인돼 실제 Forward 성공으로 표시하지 않았다. 인증 조회·실제 모델 생성·사용자 사진 E2E·Isaac GPU/실물 실행·설치/다운로드·Commit/Push/Merge는 하지 않았다.

신규 Object 관절은 BLOCKED다. Stage8 실제 CPD/Front/FP, 자동 Support 전체 복원, 추가 CoACD 변환, Isaac 관통/안정성과 실물 Task는 여전히 미지원 또는 미검증이다. 위 2026-11-09 PARTIAL 표와 E2E 준비 목록은 당시 기록이며, 최신 함수별 구현 상태·의도적 차이·Runtime 누락·검증 경계는 [알고리즘 보완 기록](simfoundry-algorithm-completion.md)을 따른다. 전체 Stage/실제 사용자 Scene이 모두 완료됐다고 선언하지 않는다.

증거: Git 제외 `workbench_runs/diagnostics/simfoundry_migration/phase_f_h/`의 최종 JUnit/log, Runtime API, Source 비교, 보호 대조 및 `verification-summary.json`.
