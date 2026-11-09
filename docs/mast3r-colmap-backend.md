# MASt3R + COLMAP Geometry Backend 전환

후속 2026-11-08: 아래 내용은 독립 Backend 구현 시점의 기록이다. 최신 로컬 단일 UI·Support 구현과의 통합 결과는 [통합 기록](geometry-backend-integration.md)을 따른다. 원 사용자 작업 폴더에는 아직 적용하지 않았다.

> 후속 최종 적용: 원래 프로젝트의 제품 Backend는 `mast3r_colmap` 하나로 전환했다. 아래 DA3 Legacy 지원과 이전 Worktree UI 설명은 전환 전 기록이다. 현재 실행법·실제 기존 Scene 결과는 [통합 기록](geometry-backend-integration.md) 마지막 절을 따른다.

2026-11-08. 기준 `9384a09e86196d98f107992d1352aaac1dc3a8b8`, 작업 브랜치 `feat/mast3r-colmap-backend`, Worktree `/home/hyeonhee/real2sim-learning-studio-review-20261106`. 원 사용자 폴더의 미커밋 29개 파일은 옮기거나 덮어쓰지 않았다. Commit/Push/Merge, 하드웨어 구동, 시스템 CUDA/Driver 변경은 수행하지 않았다.

## 실행 경로와 변경 소유권

| 위치 | 실제 변경 |
|---|---|
| `inference.run_models` | 기존 SAM·Object association 뒤 `sfm.backend`로 분기. 새 기본값 `mast3r_colmap`, 명시 DA3 및 저장된 과거 DA3 구성은 기존 Worker 사용 |
| `sfm.run_geometry` | 정적 train Mask·Camera/원본 identity 구성, 기존 `_runtime/_run_worker` 호출, 완료 단계별 캐시 게시/검증 |
| `sfm.mast3r_worker` | 공식 `forward_mast3r` GPU 추론, 정적 Mask 대응점 필터, `sparse_global_alignment`와 `get_dense_pts3d`로 공통 상대 Pointmap 생성 |
| `sfm.colmap_worker` | learned UV만 Database에 Import → `verify_matches` → `incremental_mapping` → 명시 BA → native Camera/Sparse Export → Dense 정합 |
| `sfm.robust_similarity/optical_depth` | 동일 픽셀의 MASt3R 3D와 COLMAP track XYZ를 robust Sim(3) 정합. 최적 K/distortion/W2C로 optical-Z 재투영, z-buffer·cheirality·원 픽셀 잔차 검사 |
| `calibration.registration.align_depth_batches` | 동일 SfM frame에는 상대 항등 변환만 사용. 다른 Component는 연결 근거 없이 합치지 않음. Legacy DA3 overlap 함수 유지 |
| `observations.predict_views` | 기존 baseline/실측 평면/실제 q·FK hand-eye에 상대 Camera 전달. COLMAP distortion과 confidence를 기하 계산에 반영 |
| `inference.build_point_clouds` | 새 단위 기록, 미등록/Depth 미해결 View 진단. 기존 metric 등록 후에만 `points_world_m` 게시 |
| `automation._reconstruct` | Geometry 보고서 및 Metric Registration 단계 연결. Modeling/Asset/fit_scene/Pair/Checkpoint/Physics/Export는 기존 경로 |
| `ui_reconstruction` | 검토 브랜치의 기존 환경 탭에 Backend와 설치된 두 interpreter·소스·Checkpoint 경로만 연결 |

새 Agent/Manager/별도 Scene 저장 구조는 없다. `scene_contract`·Workbench Teleop/학습/DataGen·Robot URDF·q/Mapping은 수정하지 않았다. 함수 호출 관계는 기존 `run_models → predict_views/register_views → build_point_clouds → modeling_groups → fit_clouds/fit_scene → Pair/Export`다. 기존 Codex 가이드 전달·Sandbox·Blender 자산 등록도 그대로 사용한다.

## Camera / Dense 계약

MASt3R pointmap frame과 COLMAP world는 다른 상대 좌표다. Camera 중심만 정렬하거나 다른 모델의 Pose만 끼워 넣지 않는다. COLMAP Sparse track의 원 pixel을 실제 MASt3R resize/crop affine으로 옮겨 3D 대응을 만들고, 한 공통 Sim(3)을 RANSAC/재추정한다. 비공선 대응 최소 30개·60% 지지와 상대 extent 기준 잔차를 요구하며, 실패는 `UNRESOLVED`다. 기본 상대 잔차 한계 .03과 Dense 원 pixel 잔차 8px는 실행 설정/캐시 identity에 들어가는 구현 한계이며 실측 정확도 기준이 아니다.

Dense Depth는 변환된 가시 Pointmap을 COLMAP Camera로 재투영한 양의 optical-Z다. 원 픽셀 일관성·confidence를 통과한 전면 관측만 남기고, 구멍은 NaN/confidence 0으로 둔다. Sparse 점 보간·뒷면 생성·DA3 Depth 혼합은 없다. Camera 등록 성공과 Dense coverage는 별도 수치다.

기존 NPZ key `depth`, `intrinsics`, `extrinsics`, `conf`, `original_to_processed`를 유지하고 `distortion[N,5]`를 추가한다. Extrinsics는 optical World-to-Camera, Metadata 단위는 `sfm_relative`, `metric_scale_verified=false`, `common_frame`은 Backend cache/component ID다. `align_depth_batches`의 scale=1은 이미 같은 **상대** frame의 항등 변환이며 1m라는 뜻이 아니다. 서로 다른 Component는 별도 native 파일·결과로 보존하고 기존 metric 소비자에는 연결 관측을 요청한다.

물리 Camera ID·해상도·EXIF·명시 crop 조건이 같은 렌즈만 COLMAP K를 공유한다. 보호된 K/distortion은 고정하며 표현할 수 없는 렌즈/EXIF 조합은 제외한다. 기존 Side의 공유 고정 Pose, Wrist의 공유 Mount·measured-q/FK·Robot Base 등록은 기존 `predict_views/observation_scene`가 담당한다. 다른 배치/촬영 group을 섞거나 q를 만들어 넣지 않는다. 휴대폰만으로 Robot Base가 실측 등록됐다고 표시하지 않는다.

모든 SfM/BA/MASt3R Geometry 추론 입력은 train이다. Validation은 현재 `UNREGISTERED`/reference-only로 남고 별도 train-model localization은 **미구현**이다. 따라서 새 Backend에서 held-out Camera를 평가하려면 별도 독립 등록 근거가 필요하다. Validation을 train에 넣어 이 제한을 숨기지 않는다.

## 설정·실행·재개

설정 예와 기존 CLI/API는 [AUTO_SCENE_FITTING.md](../real2sim_builder/AUTO_SCENE_FITTING.md)를 따른다. `geometry.backend: mast3r_colmap`와 `python/source/model/colmap_python`이 필요하다. 새 Project는 이 Backend가 기본이다. `geometry.backend: da3`는 기존 `da3` 설정을 사용하고, `geometry` 없이 비어 있지 않은 `da3`가 저장된 기존 Project도 DA3로 명시 해석한다. SIFT fallback/자동 다운로드는 없다.

`inference/mast3r_colmap/<digest>`에는 입력 SHA·Mask·layout/split·Camera·매칭 설정·Python/MASt3R 소스/가중치/PyCOLMAP binary SHA가 결합된다. MASt3R 종료 후 COLMAP을 시작한다. COMPLETE·결과 SHA·산출물 SHA를 확인한 단계만 재사용한다. 중단된 시도는 새 시도로 실행하고 게시된 결과의 변경은 거부한다. 완료된 GPU 단계 뒤 Stop이면 다음 실행에서 GPU를 다시 추론하지 않고 남은 COLMAP부터 진행한다. 기존 process-group Stop/timeout/OOM 처리·Project lock을 사용한다.

진행 상태는 MASt3R Matching → COLMAP Registration / Bundle Adjustment → Dense Geometry Alignment → Metric Registration으로 전달한다. 이후 기존 Object 모델링·Real/Sim Fitting·Physics/Review 단계를 유지한다.

## 실제 실행 결과

기존 비교 실험의 휴대폰 정적 배치 8장을 읽기 전용으로 가져와 별도 Project/Candidate에서 실제 `run_models()`를 실행했다. 기존 사진별 Camera ID를 보존했으며 동일 렌즈임이 확인되지 않은 ID를 임의로 합치지 않았다. 입력 이미지와 정적 Mask를 기록했고 Robot Mask 영역을 제외했다. 기존 실험과 달리 정적 Mask/매칭 필터를 적용했으므로 과거 4,169개 Point와 같은 수치를 요구하지 않았다.

| 항목 | 이번 실제 결과 |
|---|---:|
| COLMAP 등록 Camera | 8/8 |
| Sparse Point | 2,367 |
| BA 평균 재투영 오차 | 0.717132px |
| 검증된 이미지 쌍 / Inlier 대응 | 12 / 12,327 |
| Dense/Sparse 정합 지지 | 4,284 / 4,930 |
| 상대 extent 정규화 RMSE | 0.00412721 |
| MASt3R Worker | 45.01초 |
| PyCOLMAP·Dense Worker | 2.29초 |
| MASt3R CUDA allocated / reserved peak | 3,238 / 4,714MiB |
| 동일 입력 재실행 | 5.74초, SAM/MASt3R/COLMAP 추론 로그 6개 mtime 불변 |

GPU는 RTX 4060 Laptop 8GB, Driver 580.178.04다. MASt3R 공식 소스 `f5209afc300cec36239a7ac992263f36847bbba0`, DUSt3R `3cc8c88c413bb9e34c41db0e0eef99c2ee010b12`, Checkpoint SHA `e28f91b488554653e2b46ddae9c78c1143e0bcb2e27d3e26cdb0b717f1568eb2`를 사용했다. PyCOLMAP CUDA build 4.2.1이며 이번 learned matching은 MASt3R GPU, COLMAP 검증/BA는 CPU다. SIFT matcher 초기화 메시지는 공식 `verify_matches` 내부 로그이며 SIFT feature 추출/대체 매칭은 호출하지 않았다.

`sfm-colmap`에 공통 수치 함수를 불러오는 데 필요한 PyYAML 6.0.3/OpenCV 4.11.0.86/NumPy 1.26.4만 추가·정리했다(기존 NumPy 2.4.6). 기존 SAM/DA3/학습 환경·시스템 CUDA는 변경하지 않았다. 초기 실행의 빈 정적 매칭 edge·PyCOLMAP integer timeout API 오류는 수정했다. Sparse track마다 NPZ 전체를 다시 푸는 병목도 이미지당 한 번 읽도록 수정했다. 실패 로그를 최종 성공과 섞지 않는다.

8개 View의 유효 Depth pixel은 57,006 / 56,535 / 40,437 / 62,759 / 47,119 / 16,564 / 1,464 / 190이다. 마지막 두 View는 조밀한 표면이 거의 남지 않았다. 이 결과를 모든 표면이 복원됐다고 해석하지 않는다. 통과하지 못한 pixel을 보간해서 채우지 않았다.

실제 `predict_views → register_views → build_point_clouds → modeling_groups`를 호출했다. 상대 Camera는 생성됐지만 이 실험 Project에는 검증된 metric anchor/다양한 Wrist q가 없어서 **Metric Registration UNRESOLVED / 점군 NEEDS_MORE_DATA**다. 기존 모델링 자료 6개 Object 그룹은 만들었으나 새 원격 Codex/Blender 모델을 실행하거나 미터 Scene을 발명하지 않았다. 실사진 최종 `fit_scene`·Physics/Task·독립 GT 정확도 개선은 미검증이다. 합성 metric 근거와 실제 MuJoCo 렌더를 사용한 새 통합 시험은 새 Depth 계약 → metric cloud → 모델링 fusion → 기존 native `fit_scene` 연결을 별도로 확인한다.

실행 산출물은 Git 제외 `workbench_runs/backend_migration_20261108/`의 `runtime/actual-result.json`, `integration-result.json`, `summary.json`, `cache-result.json`, `index.html`, `depth.png`, `cloud.png`와 단계별 로그/공식 Sparse 모델이다. 원본 입력은 이전 `sfm_comparison_20261108` 결과와 분리했다.

## 최신 로컬 UI와 통합할 때

원 사용자 폴더의 최신 단일 UI·Codex 로그인/모델/사용량·Support 제약 변경을 이 이전 Worktree로 덮어쓰지 않는다. 공통 충돌 파일은 `automation.py`, `ui_reconstruction.py`, `AUTO_SCENE_FITTING.md`, `SCENE_AUTHORING.md`, `SCENE_RULES.md` 및 아키텍처 문서다. 안전한 통합은 현재 29개 변경을 먼저 별도 체크포인트/보관한 후 파일별로 검토하는 후속 작업이다. 이번에는 수행하지 않았다.

특히 단일 UI에는 5개 탭·수동 환경 폼을 가져오지 않는다. 최신 저장 설정을 읽는 곳에서 `sfm.backend()`와 Geometry runtime 누락 진단을 연결하고 기존 단계 표시가 새 `Project.state.stage`를 보여주게 한다. 로그인/모델/사용량·Checkpoint/Support 알고리즘은 최신 로컬 구현을 보존한다. `inference.py`, `observations.py`, `calibration/registration.py`, 신규 `sfm.py`를 소유 기능 단위로 통합하고, `automation._reconstruct`에는 Geometry 보고서/Metric 단계 변경만 반영한다. 실제 공통 수정 경로는 위 6개와 `tests/test_reconstruction_ui.py`를 합친 7개다. UI 시험도 이전 탭 구조의 기대값을 복사하지 않고 최신 단일 UI에 Backend 계약만 추가해야 한다.

## 검증과 한계

전용 수학·캐시·Stop/OOM·held-out 제외·정적/Robot Mask·실제 MuJoCo 소비 시험 **12개 통과**. 실제 GPU 결과와 이 합성/모의 시험을 구분한다. 최종 전체 회귀는 **1,533 passed / failed 0 / errors 0 / skipped 0**, 360.77초, 기존 torchvision 경고 4회다(`release-suite.xml/log`). 변경 Python 8개는 bytecode 없이 compile했고 `git diff --check`도 통과했다.

최초 독립 기준 HEAD 회귀는 1,501 passed / 20 failed였다. 원인은 Git에 없는 장치 설정/Scene fixture였다. 기준 소스는 그대로 두고 필요한 자료만 독립 폴더에 복사한 뒤 해당 20개를 다시 실행해 모두 통과했다(`baseline-fixtures.xml`). 중간 전체 실행의 추가 8개 실패는 존재하지 않는 Blender 환경 변수 경로였고 설치된 Blender 경로를 명시해 해결했다. 시험 기대값 완화/skip/xfail로 통과시키지 않았다. 회귀용 Scene/설정 복사본과 Qt/cache 연결은 로컬 실행 자료이며 Commit 대상이 아니다.

원 사용자 폴더의 **미커밋 29개 파일의 SHA 목록 digest가 시작 시점과 동일**하다(`95e88916893171fbe8ce5075e42de877e40ff696f97311ca96ede80e86874ecf`). 원 Scene/Asset/Capture/Export 보존 대조 **2,800개 SHA 변경 0 / 누락 0**을 확인했다. 기존 `sam31`, `da3`, `lerobot`, `lerobot-arena`의 `pip freeze`도 동일하다(`preservation.json`, `environments-preserved.json`). 전체 사용자 홈/SDK를 전수 검사했다는 뜻은 아니다. 독립 validation localization, 새 실사진 metric Scene/승인 Export, 모든 장면의 Camera 정확도·Grasp/마찰 물리 인증은 이번 결과로 완료하지 않는다.
