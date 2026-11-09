# Real2Sim 다중 시점 파이프라인 재설계

## 2026-11-09 현재 실행 계약 — Codex-First

제품 Auto Reconstruction은 Scene/Model 사진과 Memo를 Codex가 직접 분석하고, 기존 Sandbox Blender로 자산을 제작한 뒤 실제 Simulator 렌더를 보며 typed Scene plan을 반복 수정한다. SAM/DA3/MASt3R/COLMAP·Depth·Metric 등록은 초기 Scene 생성의 필수 단계가 아니다. 최초 Scene/각 Iteration/최종 결과의 실제 Visual Evidence를 Candidate에 보존하고 단일 UI에서 연다.

현재 소유권·전환 이유·실제 실행/검증 범위는 [Codex-First 제작 기록](codex-first-scene-builder.md)을 따른다. 아래의 과거 날짜별 Backend/수치·검증 기록은 당시 범위이며 현재 기본 실행 순서가 아니다. 기존 Calibration/FK/Renderer/Asset/Export 계약과 사용자 원본은 유지한다.


현재 작업판 크기 등록 실패의 증상·코드 경로·사진별 진단·설명 정정·미확정 원인은 [작업판 Metric 등록 문제 정리](workspace-metric-registration-issue.md)를 따른다(2026-11-09). 아래 날짜별 기록의 실행 범위는 그대로 보존한다.

2026-11-08 후속 통합: 최신 로컬 단일 UI·Codex 로그인/모델/사용량·Stop/Resume·Support 구현을 기준으로 MASt3R/COLMAP Geometry를 별도 Worktree에 통합했다. 원래 작업 폴더에 적용하거나 Commit/Push/Merge하지 않았다. 충돌 해결·실제 Scene Prepare 버튼/GPU 실행·회귀·백업/보존 범위는 [Geometry 통합 기록](geometry-backend-integration.md)을 따른다. 아래 날짜별 기록은 당시 실행 범위로 유지한다.

2026-11-05. 기준 `14996df88f54e7e6d2deb997a6553cf94df75595`. 작업 브랜치 `feat/real2sim-multiview`. 사용자 원본/기존 Review/Export를 변경하지 않고 코드와 독립 시험 Workspace에서 작업한다. 이 문서는 설계 결정과 실제 검증을 함께 갱신하며 미실행 결과를 성공으로 기록하지 않는다.

## A. 현행 감사와 교체 범위

| 기능/파일 | 현행 문제 | 처리/최종 책임 |
|---|---|---|
| Project/Candidate/Scene/Export | 불변 Revision·잠금·SHA는 필요 | KEEP, Domain/Data 소유권 유지 |
| Scene Memo/typed Codex 분석 | 단일 원문과 응답 검증은 목표에 부합 | KEEP, 의미 해석을 Python으로 복원하지 않음 |
| automation.py | 844줄에 의미분석/자산정책/CLI child/정합 orchestration 혼재 | REFACTOR, 단계 조율과 Pair source만 유지; 모델링 구현을 한 소유 모듈로 이동하고 호출자 전환 |
| inference.py SAM/DA3 Worker | 순차 child/cache와 원본 identity 유지 필요 | KEEP, 설치/가중치 변경 없이 기존 실행 경계 사용 |
| associate_instances | 이미지별 Box/unique 외에 공통 3D 대응 없음 | REPLACE, 같은 함수에서 metric/relative depth 공통 좌표 대응과 1:1 할당, 모호함은 미해결 |
| modeling_groups count gate | Mask 부족이 Asset 공유까지 차단 | DELETE, 부족 View 진단은 관측 책임; 확정 자산은 재사용 |
| build_point_clouds | 자산 모델링 완료 전에는 실행되지 않아 복원 3D가 모델링과 단절 | REFACTOR, Camera→관측→fusion을 모델링 이전 실행; 자산/형상/관측 상태 분리 |
| predict_views/register_views | 자동 등록 뒤 calibrated-only 경로가 다시 판정, 실측 치수만으로 자동 scale 초기화 없음 | REFACTOR, 자동 추정 결과와 명시 Calibration을 같은 등록 상태로 사용; 공통 lens/고정 Side/mount Wrist 제약 |
| object_assets list/UI | 모든 Manifest/USDA를 검증해 무관한 자산 손상에 실패 | REPLACE, metadata catalogue와 선택한 버전 strict verify를 구분 |
| fit_clouds/trimmed_icp | 알려진 형상과 가시점 초기화 | KEEP, 정합 초기값 책임 |
| fit_depth_bundle/fit_joint_scene | raw ray/shared Camera·FK 수학과 landmark solver | KEEP, 수치 초기화와 고급 명시 landmark 기능. 기본 closed loop와 중복 실행하지 않음 |
| refine_masks | 물체별 mask-only 최적화·고정 Camera, 다중 손실/최적 iteration 없음 | REPLACE, 한 Simulator render 공동 최적화로 대체 |
| compare_backends | 자동 실행마다 A/B/C 전부 수행 | REFACTOR, 명시 실험 비교만 유지; 제품 실행은 하나의 fit_scene 경로 |
| rendering.Renderer | 실제 MJ RGB/segmentation, Camera 갱신/depth 인터페이스 부족 | REFACTOR, RGB/mask/depth와 수치 pose/K 갱신; 상위 loss는 엔진 내부 미참조 |
| validation physics/Isaac child | 실제 실행·미검증 분리 필요 | KEEP, Blender/PhysX/Task 준비는 렌더 성공과 구분 |
| Real/Sim Pair source/refit | Manifest·measured q·원 Geometry 보존 필요 | KEEP, 같은 fit_scene를 쓰고 train/holdout 누출 검사 유지 |

## B. 최소 모듈 계약과 실행 순서

새 Manager/Agent/DB를 만들지 않는다. Domain은 현재 Project/Scene, Perception은 inference/observations, 수학은 calibration, 자산 저장은 object_assets, 모델링 실행은 authoring, Renderer는 rendering, 단계 조율은 automation이 소유한다. 구현 이동은 옛 정의/호출자를 함께 제거한다.

공통 데이터는 Image ID/SHA·physical camera·layout/split·원래 pixel affine·measured q·Mask·DA3 raw depth와 metric provenance다. 원본 RGB/q/모델·실측은 수정하지 않는다. 추정치/observability 실패를 calibrated/physical_verified로 승격하지 않는다.

기본 실행: 원문 의미 분석→SAM/DA3→공통 Camera/scale→다중 시점 관측/융합→필요 자산만 모델링/선택→공통 Scene 초기화→실제 Simulator 다중 View render 공동 loss→최선 유효 Candidate→별도 Pair 평가/정밀 정합→불변 Export. 각 단계에서 같은 Camera/Asset 조건을 다른 모듈이 다시 다르게 해석하지 않는다.

## 데이터 수명

원본 Input/Capture/실측/Calibration은 영구 보존, Asset Version과 Export는 명시 관리·불변, Candidate는 중단/재개용 보존이다. SAM/DA3/render cache는 재생성 가능하지만 현재 Candidate나 Export에서 참조한 cloud/Mask는 해당 closure의 일부다. 자동 삭제는 구현하지 않는다. Codex 입력/응답·Blender script·오류 로그는 필요한 실행 근거를 보존한다. 원본과 무관한 복제 history는 추가하지 않는다.



## C. 삭제·통합·수정한 구현

- **삭제/교체:** `refine_masks`의 물체별 고정 Camera mask-only loop를 삭제하고 `fit_scene`의 공동 native render loss로 교체했다. 자동 경로에서 A/B/C 세 solver를 모두 실행하던 호출을 제거했다. Mask 검출 개수가 Asset Group 공유를 차단하던 `OBSERVED_INSTANCE_COUNT_MISMATCH`를 제거했다.
- **통합:** `automation.py`의 분석 Schema/파서·Group 정책·Codex child·자산 연결 함수를 `authoring.py`로 이동했다. 구 정의나 호환 wrapper를 남기지 않고 CLI/UI/시험 호출자를 전환했다. `joint.parameter_blocks/apply_parameters`를 raw-depth와 render solver의 공통 수치 변수 정의로 사용한다.
- **내부 변경:** Library 목록은 메타데이터만 읽고 실제 선택 버전은 엄격히 검사한다. 잘못된 무관한 YAML/USDA가 전체 목록을 막지 않는다. 3D 융합 자료는 자산 제작 이전에 생성해 Codex의 실제 입력 NPZ로 전달한다. `Renderer`는 한 compiled MuJoCo Scene/context에서 pose/K/해상도를 갱신하며 RGB/segmentation/depth를 제공한다. Isaac은 같은 인터페이스의 `IsaacRenderer`로 pose/K·RGB/mask/optical depth를 제공하며, 실행 중 해상도 변경은 명시 재초기화가 필요하다. 기존 Workbench 정적 Isaac 렌더 클래스를 삭제하고 이 구현으로 통합했다.
- **신규 수치 기능:** 공통 depth 좌표의 관측 대응, fully-visible 실측 Support의 metric 초기화, EXIF/명시 crop·공유 optical frame 변환, native 다중 View fitting·best checkpoint와 최종 cloud 재투영을 구현했다. 새 Manager/Agent 프레임워크나 Dataset 포맷은 없다.

### 추가 지시: Scene Memo와 실측 통합

사용자 입력은 **자유로운 Scene Memo + RGB + 필요한 Robot Capture**다. 메모에는 치수·제품 공유·공간 관계·모델링 요구·작업 목적을 함께 적는다. Python에서 자연어 숫자/치수/키워드 파서를 만들지 않았다. `scene_preparation.save_inputs`와 `evidence.save_scene_memo`는 원문을 보존하는 기존 역할을 유지한다.

`authoring.scene_analysis_schema/parse_scene_analysis`의 Object `geometry`로 Codex가 해석한 치수(m)를 받는다. `geometry_specs`가 기존 구조화 측정/보호 Scene과 대조하고 `initialization.measured_geometry`, Camera metric 초기화, Asset Group/Blender 입력에 하나의 수치 자료를 전달한다. 새 기본 경로는 별도 `measurements` 사본을 생성하지 않는다. 기존 `measurements` 및 `evidence.import_metadata`는 보존된 고급 수치 입력이며 자연어 해석 경로가 아니다.

예를 들어 “컵 높이는 100mm야”는 Codex가 `[null,null,0.1]`로 구조화한다. 높이만 실측이며 나머지 축은 미지다. 제작 USDA는 알려진 축의 크기를 검사하고, 전체 bounds는 estimated로 보존하면서 `dimensions.constraints`에 원 부분 실측과 근거를 남긴다. 이미지 기반 추정·사용자가 원하는 디자인 치수를 실제 측정으로 표시하지 않는다. 인용문과 SHA 검증은 의미 해석이 옳다는 독립 증명이 아니다.

UI의 가로·세로·높이·벽 입력 열과 그 파싱/필수 완성 검사를 삭제했다. 기본 탭은 Scene Memo 원문·사진이며 Object/Asset 선택은 고급 탭이다. Scene Prepare의 placeholder도 필수 양식 대신 자유 메모 예시로 바꿨다. 기존 측정 데이터는 삭제하거나 추정값으로 덮어쓰지 않는다. 해석 값과 충돌하면 새 계획을 게시하기 전에 오류를 반환한다.

Support ID는 기존 upright/support fitting에 연결된다. 그 밖의 자유로운 공간 관계/형상 지시는 `modeling_notes`로 Codex에게 전달된다. 모든 자연어 관계를 수치 제약으로 자동 컴파일하는 기능은 구현하지 않았다.

## D. 실제 함수 호출 흐름

```text
Scene Prepare save_inputs → evidence.save_scene_memo / 기존 image·capture 등록
CLI reconstruct → automation.reconstruct → _reconstruct
  → authoring.analysis_required → modeling_tasks
  → modeling-run → run_codex_modeling → parse_scene_analysis → save_configuration
  → geometry_specs (기존 보호 실측과 충돌 검사)
  → inference.run_models (SAM 종료 후 DA3, cache)
  → associate_instances / cross_view_associations
  → captured_robot / initialization.measured_geometry
  → observations.predict_views / register_views
  → inference.build_point_clouds
  → authoring.modeling_groups (가시 metric points fusion)
  → group_asset / attach_modeled_assets 또는 run_codex_modeling → Blender author_object_assets
  → object_assets.register_object_asset / instance_operation
  → hybrid.fit_clouds (미지 Pose 초기화)
  → hybrid.fit_scene → joint.parameter_blocks / apply_parameters
      → capture.observation_scene (actual q/FK)
      → MuJoCo Renderer 또는 소유 Kit child의 IsaacRenderer
      → update_scene / rgb / mask / depth
      → 모든 train View loss → 최선 유효 Scene → holdout 별도 평가
      → reproject_observations → Candidate.save
  → validation.physics_probe / 별도 isaac_physics_worker
Real/Sim Pair → pair_source / refit_pairs → 같은 fit_scene
명시 Export → export_revision → 새 immutable Package / Manifest
```

`reconstruct`와 `modeling-run`은 기존 명시 실행 단계다. 미해석 메모는 `WAITING_FOR_CODEX_ANALYSIS`, 새 자산 제작은 `WAITING_FOR_CODEX`로 정지/재개한다. 전체 흐름을 사람이 누르지 않는 하나의 자동 원격 Codex 재시도 앱으로 포장하지 않았다. Codex가 기존 CLI/API를 순서대로 사용한다.

## E. 검증 결과와 남은 범위

시험/실행 자료는 Git 제외 `workbench_runs/multiview_architecture_20261105/`에 보존한다. 원 실제 RGB를 변경하거나 실물 로봇에 연결하지 않았다. 설치/업그레이드·새 학습·원격 Codex 호출·Commit/Push/Merge는 수행하지 않았다.

| 검증 | 결과와 범위 |
|---|---|
| 시작 전체 baseline | **1,297 passed / 66 failed / 28 errors / skipped 0** |
| 최종 전체 | **1,330 passed / 66 failed / 28 errors / skipped 0**, 2 warnings, 271.69s. 이후 체크포인트 수정의 관련19개도 모두 통과 |
| baseline 대조 | 같은 시험명/실패 종류의 94개, **신규 실패 0**. 제거된 과거 USD fixture 의존/기존 UI 기대값 등 baseline 문제는 해결하지 않음 |
| Memo→typed plan→geometry/modeling | 원문 그대로 전달하는 Fake Codex 응답으로 partial height/전체 치수·Support·SHA/인용문·NaN/음수/Boolean/잘못된 참조·보호 실측 충돌 검증. 실제 LLM의 언어 해석 정확도 시험은 아님 |
| 실제 Qt | 별도 치수 UI 제거, 고급 수치 설정/자산 선택/메모 bytes 재열기, 실제 Qt→CLI 상태 표시 확인. GUI에 AI/SDK/engine import 없음 |
| 실제 Blender | 선택 Group 단일 USDA/공유 Instance·입력 RGB/depth/융합 NPZ 전달·sandbox·기존 자산 보존·실패 retry 회귀 |
| 합성 실제 MuJoCo joint fit | 2 View, Camera/물체 초기 이동오차 각각 18mm. loss **1.46552 → 0.51457**, 최종 물체 이동오차 **2.596mm**, Camera **3.719mm**, 회전오차 각각 **0.003117rad / 0.001271rad**. 480평가 후 **BUDGET_EXHAUSTED**, 정밀 Calibration 성공으로 표시하지 않음 |
| native 갱신 | pose/K 갱신 RGB가 재compile과 일치, optical depth 수치 비교, 중단 시 최선 유효 checkpoint, heldout 최적화 제외 회귀 |
| 실제 SAM/DA3 | 보존 Side/Wrist 각1장. Side red Mask1·cup Mask2/AMBIGUOUS, Wrist query NOT_FOUND, DA3 양 depth 생성. 재실행 모델 cache 재사용 확인 |
| 실제 사진 전체 Scene E2E | **미완료**. 해당 정적 배치의 한 Wrist 자세와 부족한 metric 근거로 Camera/scale UNRESOLVED. 없는 q·scale·Mask를 채워 통과시키지 않음. 독립 validation/휴대폰 추가 사진 없음 |
| 공통 Isaac 렌더의 기존 로봇 Scene | 원 v9-task-objects Package를 읽기 전용으로 사용. 합성 q 변화0.04rad에서 Side/Wrist 두 영상640×480이 모두 갱신됨을 확인했다. 실제 장치 입력/구동은 없고 Physics Step0이다. `shared-isaac-robot/result.json`에 기록했다. |
| 실제 Isaac 기존 native Scene | 새 프로세스에서 joint target/40 physics step(초기화 포함48), 양 RGB640×480, 원 Manifest86파일 SHA 불변. 새 자산 전체 Task 성공 시험은 아님 |
| 실제 합성 컵 낙하 | Blender17 collision조각. 초기 MuJoCo600step의 **6.67mm 관통 실패**를 보존했다. 기본 접촉 응답에서 얇은 바닥을 통과하는 문제를 수정하고 **동일 컵**을 새로 Export하여 600step, block z≈**0.012999m**, 최종 관통 없음·settled=true를 확인했다. 별도 0.10/0.16/0.25m 낙하 회귀도 통과했다. 기존 Isaac 결과는 z≈0.013m다. |
| 실제 Isaac 공동 정합 | 독립 합성 2 View, 실제 RGB/mask/depth. 물체 초기 오차18mm → **0.249mm**, loss **1.143899 → 0.486174**, 두 Mask IoU1. 130평가 후 **BUDGET_EXHAUSTED**. Camera는 이 시험에서 고정이며 실사진 정확도·Camera 동시 수렴 검증이 아니다. 별도 새 프로세스 비교 렌더와 정상 종료도 확인했다. |

컵 probe는 최종 접촉 관통이 1mm를 넘으면 settled=false로 보고한다. 낙하 수정은 MJCF collision의 `solref="0.004 1"`이다. 2ms step에서 4ms 시간상수의 임계 감쇠를 사용하며, 기존 Native 접촉 패드와 같은 수치 설정이다. 실측 물성값으로 기록하지 않는다. timestep만 줄이거나 mesh를 primitive로 바꾸는 진단으로는 문제가 해결되지 않았고, 접촉 응답 변경으로 동일 모델의 실패가 해결됐다. 기존 사용자 Export bytes는 수정하지 않았다. 이 한 낙하 시험을 모든 물체/Robot/Task의 물리 준비 완료로 확대하지 않는다.

초기 생성은 추정 일반 물체의 색·roughness/metallic과 조명 ambient/energy를 공동 변수로 사용한다. 실측·보정값, Robot, Texture 색, 불변 공용 Asset 재질은 변경하지 않는다. Pair 재정합은 원 Revision 재질 보존을 위해 appearance/lighting을 끈다. MuJoCo 재질은 Phong 근사이며 Isaac PBR과 동일 수치가 동일 Pixel을 보장하지 않는다. 합성 2 View의 실제 MuJoCo 색 정합에서 양 View RGB 손실 감소와 Geometry 불변을 확인했다.

Isaac은 `fitting.engine: isaac`으로 같은 solver를 별도 Kit 프로세스에서 실행한다. 한 실행에서 compiled Scene과 Camera를 재사용한다. 단독 worker는 결과 파일을 닫은 뒤 공식 기본값인 빠른 종료를 사용한다. 설치 Runtime의 느린 확장 종료는 USD shutdown에서 정지했으며 진단 로그를 보존했다. 오류 파일을 exit code와 함께 검사하므로 빠른 종료가 실패를 성공으로 바꾸지 않는다. 명령 소비는 worker 하나가 담당하고, 부모는 native 호출에 갇힌 worker의 Stop/timeout을 제한한다. 정상 Stop은 현재 최선 상태를 재투영해 보존하며, 강제 종료에서는 마지막으로 완료된 반복의 일관된 Camera/점군 체크포인트를 사용한다. Camera signature가 이전 반복에 머물던 오류를 RED→GREEN으로 고쳤다. 별도 Isaac K 중심점 시험에서 요청한 (+12px, −8px)가 실제 Mask에서도 정확히 같은 이동으로 나타났다.

**남은 범위:** distortion fitting, 불변 공용 Asset의 자동 Material Variant 제작·정합은 구현하지 않았다. 모든 모호한 물체 대응/퇴화 Camera가 자동 해결되는 것은 아니다. 정합 수렴·실측 정확도·독립 검증·물리 준비·Task 성공은 서로 다른 상태다. User Stop/iteration budget과 성공을 구분하며 실제 사진의 새 승인 Export를 만들지 않았다. 추가 독립 사진/여러 Wrist 자세가 없는 현재 입력으로 사용자 목표 전체의 무인 E2E가 완료됐다고 보고하지 않는다.

`continuation-suite.xml`, `continuation-baseline-comparison.json`, `checkpoint-green.xml`, `baseline-comparison.json`(이전 전체), `numeric-fitting.json`, `real-models-result.json`, `native-isaac-summary.json`, `cup-physics-summary.json`(초기 실패), `cup-fixed-result.json`, `isaac-joint-fit-result.json`, `isaac-fit-comparison.json`, `preservation-after.json`을 각각 근거로 사용한다. 중간 실행의 Blender 환경 변수 누락 9개와 메시지 계약을 아직 갱신하지 않은 시험1개는 중간 로그에 남겨두었고, 기존 설치 경로/새 계약으로 수정한 뒤 최종 전체 회귀에 포함했다.

## F. 유지보수 평가

1. **Object 모델링 정책:** `authoring.py`의 Group/재사용/명시 모델링 선택을 수정한다. 저장·closure 검증 방식 변경은 `object_assets.py`의 책임이다.
2. **Camera Solver 교체:** 초기화는 `observations.predict_views`와 `calibration/registration.py`, 공동 최적화 변수/수학은 `calibration/joint.py`. 원본 Camera/관측 계약은 유지한다.
3. **Renderer 교체:** `update_scene/rgb/mask/depth`의 해상도·optical depth 계약을 충족하면 상위 loss를 유지할 수 있다. Isaac도 같은 반복 갱신 계약을 구현했고 기존 Workbench 정적 렌더가 이를 사용한다. Kit 수명은 소유 자식 프로세스에 한정한다.
4. **SAM/DA3 교체:** Worker/출력 정규화·cache identity는 `inference.py`. 공통 Image/Mask/raw depth/K/pose·단위 계약을 유지하면 Scene 저장 포맷에 모델 클래스가 들어가지 않는다.
5. **Scene 독립성:** Project별 Input/Camera/q/메모/Config/Candidate가 독립적이다. 공용 Asset은 정확한 ID/Version으로만 공유한다.
6. **과거 USDA/Export:** 기존 bytes를 고치지 않고 새 자산 버전/새 Package를 게시한다. 이번 원본 보호 대조는 `preservation-after.json`의 2,389개 SHA에서 변경0을 확인했다. 전체 SDK/corpus 전수 검사는 아니다.
7. **동일 책임의 중복:** 자동 mask-only loop/중복 parameter 생성/자동 A·B·C 실행을 제거했다. wrapper로 구 실행을 남기지 않았다.
8. **남겨둔 solver 이유:** 명시 landmark API와 raw-depth API는 다른 입력을 다루는 고급 수치 기능이고, `compare_backends`는 명시 실험이다. 기본 자동 경로는 이들을 연달아 실행하지 않는다.
9. **가장 복잡한 모듈:** `authoring.py`는 원문·Schema·Group·자산 선택·sandbox handoff 때문에 복잡하고, `inference.py`는 모델별 crop/EXIF/depth/cross-view 변환 때문에 복잡하다. 자동 단계 조율과 분리해 각각의 입출력·회귀를 고정했다. 밀집된 기존 코드 스타일의 가독성 개선 여지는 남는다.
10. **확장 위치:** 새 인식 모델은 inference의 공통 출력, 새 constraint는 joint의 변수/수학, 새 renderer는 rendering의 실제 RGB/depth 계약, 자산 정책은 authoring을 수정한다. 새 병렬 pipeline/Manager를 만들 필요가 없다.

## G. 후속 1 — 관측에 따른 자동 정합 전략

2026-11-06. 이번 범위는 기존 공동 렌더 solver에 **자동 변수 선택과 Geometry→Appearance 단계**를 적용하는 것이다. 기존 실제 사진의 전체 Scene 제작 완료나 새로운 승인 Export를 뜻하지 않는다. 사용자 데이터와 이전 미커밋 구현을 보존한다.

`joint.select_parameters`는 기존 `parameter_blocks`의 변수 정의를 재사용한다. 기본적으로 K·Depth Scale·Robot Base도 검토하지만 관측이 부족하면 현재 값을 유지한다. 실제 q/FK·보호 실측/Calibration은 그대로 고정한다. `hybrid.fit_scene`는 선택한 좌표만 최적화하고, 선택하지 않은 블록은 `apply_parameters`에 넘기지 않는다. 따라서 값이 같다는 이유로 고정 변수를 `optimized`로 바꾸지 않는다.

| 판단 | 실행 동작 |
|---|---|
| Camera/Object 공동 이동의 기준 부재 | Camera를 고정하고 같은 물체와 연결된 고정 Camera/가시 기준 물체를 요청 |
| Wrist 자세 부족·단일 회전축·q 누락 | 공유 Mount 고정. 실제 q를 포함한 두 축 이상의 서로 다른 자세 요청 |
| 같은 렌즈의 시점·입체 관측 부족 | K 고정. EXIF 회전을 실제 Camera 움직임으로 세지 않음 |
| World/optical 점군만 있고 원 pixel/depth 없음 | Camera/K/Scale 변경에서 제외. 고정 Camera의 물체 정합에는 기존 World 점군 사용 가능 |
| Robot Base와 함께 움직이는 기준 또는 연결되지 않은 다른 사진의 기준 | Base/Camera를 풀기 위한 World 근거로 사용하지 않음 |
| 무늬 없는 단순 구/수직 원통 | 관측으로 구분할 수 없는 회전은 기존 방향 유지. Texture/자식/비대칭 Collision/공용 Asset은 단순 규칙에서 제외 |
| 색·조명 상호 보상 | 고정 색 기준이 없으면 조명 유지, 외관만 조정 |

holdout 사진은 변수 선택·손실·최선 상태 선택에 사용하지 않는다. 선택은 유효 train 관측만 사용한다. `report.observability`와 반복별 `history[].strategy`에 활성 변수, 고정 좌표, 이유와 추가 자료 안내를 저장한다. 필수 Camera/Object 근거 부족은 `automation.draft_readiness`에 전달하여 낮은 손실만으로 준비 완료가 되지 않게 했다. 선택적인 K/Scale/Base 고정은 진단에 남기되 전체 정합을 일괄 거부하지 않는다.

Geometry와 Appearance는 같은 solver 안에서 순서대로 실행한다. 외관 변수가 있으면 반복 예산의 앞쪽 절반(올림)을 기하에 배정하고 나머지를 외관에 사용한다. 기하가 먼저 수렴하거나 조정할 변수가 없으면 외관으로 전환한다. 기존 중단·평가 예산·View별 퇴보 제한·최선 체크포인트는 유지한다. Pair의 외관 보존 옵션도 유지한다.

이 판단은 **보수적인 기하 조건 기반 선택**이다. 전체 수치 Jacobian rank·통계적 불확실성·임의 Mesh의 근사 대칭까지 해석하는 완전한 observability solver는 아니다. 기본 자세 중복 기준은 이동 5mm/회전 0.035rad, Wrist 두 축 회전은 회전 벡터 두 번째 특잇값 0.05rad다. 임계값 통과를 실측 정확도나 물리 Calibration 인증으로 표시하지 않는다.

### 검증 기록

`workbench_runs/fitting_strategy_20261105/`에 초기 RED와 수정 후 결과를 보존한다. 전용 16개 시험은 단일 View/gauge, 독립된 기준, Wrist 퇴화·q 누락, holdout 제외, 대칭과 비대칭 Collision, 외관 단계, 실제 MuJoCo 실행과 원본 불변을 다룬다. 기존 관련 회귀를 포함한 **62개가 통과**했다. 픽셀 없는 optical 점군으로 Camera를 조정하던 경우와 다른 사진의 기준으로 Base를 풀던 경우도 각각 실패를 재현한 후 수정했다.

최종 전체는 **1,346 passed / 66 failed / 28 errors / skipped 0**, 기존 경고 2개, 257.52초다(`full-suite.xml/log`). 직전 `continuation-suite.xml`의 **1,330 passed / 66 failed / 28 errors**와 대조해 같은 시험명·실패/오류 종류의 94개가 남고 **신규 실패 0**임을 확인했다(`baseline-comparison.json`). baseline 실패를 통과시키려고 제품/시험을 변경하지 않았다. 수정 Python 4개의 bytecode 없는 compile 검사와 `git diff --check`도 통과했다.

원본 보존 대상 **2,389개 SHA 변화 0 / 누락 0**을 재확인했다(`preservation-after.json`). 전체 SDK/corpus 전수 검사는 아니다. Commit/Push/Merge와 설치·하드웨어 연결은 수행하지 않았다. 증거·실행 자료는 기존 Git 제외 경로에만 보존한다.

실제 사진의 부족한 Camera/metric 근거, 독립 validation 사진 부재, 공용 Asset의 자동 외관 Variant와 기존 전체 baseline 실패는 이번 범위에서 해결했다고 보고하지 않는다. 이번에 실제 Isaac·SAM/DA3·하드웨어를 다시 실행하지 않았으며 합성 MuJoCo 시험과 이전 엔진 검증을 구분한다.

## H. 기존 전체 테스트 실패 정리

2026-11-06. 리뷰 체크포인트 `6c90f776b7e2bd3a0aca19dcad41c016fda76015`에서 별도 `fix/baseline-tests-20261106` 브랜치로 후속 정리했다. 앞 절의 66 failed / 28 errors는 당시 기록이며, 이번 전체 회귀는 **1,441 passed / failed 0 / errors 0 / skipped 0**, 385.71초, torchvision 경고 4개다.

최초 원인은 누락 Scene USD 74건, 삭제된 checkpoint fixture 10건, 구형 테스트 계약 9건, Isaac→MuJoCo import 1건이었다. 동일 SHA의 시험 자산 복구·임시 공식 Policy fixture·현재 MuJoCo에서 새로 기록한 Source/Annotation을 사용했다. URDF/Manifest 검사는 공통 Calibration 모듈로 이동했고 기존 모델 불일치 거부는 유지한다. 기존 실패 92개는 통과했고, 폐기된 배치 제한 함수의 시험 2개는 제거했다. 현재 난수/배치 충돌 회귀는 유지하며 skip/xfail을 추가하지 않았다.

원본 보존 대상 2,389개 SHA는 변화 0이다. 전체 실제 사진 Scene 제작 완료·실물 검증을 이 결과로 승격하지 않는다. 원인별 수정·로컬 시험 자료 복구법·전체 대조는 [테스트 정리 보고서](test-baseline-cleanup.md)에 있다. 코드/시험/문서는 새 fix 브랜치의 미커밋 변경으로 남기며 기존 리뷰 Commit과 원격 브랜치는 변경하지 않았다.


## 2026-11-06 후속: 비교 판단과 수정 실행 연결

연속 실행은 정합 후 Codex에 원본/렌더/overlay/difference를 전달하고, 구조화 판단에 따라 수치 재정합 또는 선택 Object의 새 자산 제작→재정합을 이어간다. 기존 `run_codex_modeling` 실행 경계를 재사용한다. `reconstruct`와 `refit-pairs`의 `--run-modeling` 및 기존 UI 연속 실행 버튼에 연결했다. 호출 상한·중단·오류와 시각적 완료를 구분한다.

검증용 View는 수정 판단/모델링 feedback에서 제외한다. 기본 분석·모델링 최대6회, 비교 최대3회다. 시각 판단 완료는 `VISUAL_DRAFT_REVIEWED`이며 숫자 정확도·물리 준비·Task 성공과 별개다. 상세 계약과 남은 범위는 [통합 기록](real2sim-integration.md)의 마지막 절에 기록했다.


### 후속: 반복 간 최선 checkpoint

연속 실행에서 비교 가능한 train View별 지표가 악화되지 않은 개선 결과를 보존하고, 모델 재제작 후 악화·중단·예외·예산 소진 시 선택한 Scene과 Candidate 참조 파일·설정·비교 결과를 함께 복원하도록 연결했다. 원본/자산 버전은 변경하지 않는다. 동률/트레이드오프는 이전 결과 유지이며 전체 시각 품질의 최적해 보장은 아니다. 자세한 선택·복원 계약과 검증은 `real2sim-integration.md` 마지막 절을 따른다.

### 후속 실제 실행 결과

실제 Codex 응답→SAM/DA3→Codex bpy→Blender 자산8개 등록과 실제 비교 이미지 검토를 실행했다. 기존 authored Scene을 새 Package로 게시한 후 Workbench/Qt 선택·native MuJoCo20step·Memory Pair 저장→Source Revision 확인→재정합 진입도 확인했다. 새 자동 복원 Scene 자체는 Camera/metric scale 미확보로 `NEEDS_MORE_DATA`이며 전체 승인 완료가 아니다. 발견한 도구 handoff·Point batch·측정 계승·Pair 옵션/포트 비교·실행 설정 등록 수정과 정확한 범위는 `real2sim-integration.md`의 실제 실행 절에 기록한다.

### 최신 지침과 분리된 Codex 실행

2026-11-06 첨부 AGENTS/`CODEX_SCENE_GUIDE.md`를 소스 및 기존 제작/규칙 문서와 대조해 반영했다. 내부 임시 Codex 작업 폴더에는 신뢰된 원본의 `BUILDER_GUIDE.md`를 명시 복사하고, 분석·모델링·검토 전에 읽으라고 실제 CLI 프롬프트에 전달한다. 가이드 SHA/개정판과 출력 Schema를 기존 작업 기록에 남긴다. 실제 Codex 분석/모델링 양쪽의 문서 읽기→현재 Schema 응답→실제 Blender 등록, 이후 재개까지 확인했다. Camera/scale 미확보는 별도 미완료로 유지한다. 세부 검증과 문서 충돌 정리는 `real2sim-integration.md`의 최신 지침 절을 따른다.

## 2026-11-07 — 확정 지지·접촉·상대 자세 제약

기준 HEAD `9384a09e86196d98f107992d1352aaac1dc3a8b8`, 브랜치 `review/real2sim-multiview-20261106`. 이번 변경은 물리 배치 제약에 한정한다. Camera/Scale 초기화, URDF Import, 장치/Capture 등록 경로는 수정하지 않는다. 원본은 보존하고 독립 시험 Project에서 실행한다. Commit/Push는 하지 않는다.

### 실행 경로와 책임

- `scene.support_relations/support_binding/contact_gap/supported_pose/support_metrics`: 기존 `geometry_constraints.supports` 및 고급 `fitting.supports` 정규화, 순환/충돌 검사, 지지면 좌표·실제 Collision 극점/Contact Anchor·수치 진단. World 수평/Origin=바닥 가정은 없다. Mesh는 실제 Vertex/Part Transform/Scale을 읽는다. 복잡한 지지면은 명시 Support Anchor, Geometry가 없는 Frame은 명시 Mount Anchor가 필요하다.
- `initialization.project_supports/apply_geometry_constraints`: 부모 지지면부터 초기화하고 기존 거리 제약과 함께 적용한다. 측정된 Pose를 수정해 통과시키지 않는다. 기울어진 지지면과 `parallel:false`의 상대 회전을 유지한다. 아직 Pose/Geometry가 없는 초안은 진단을 남기고 추정 Offset을 만들지 않는다.
- `hybrid.initial_poses/trimmed_icp/fit_clouds/fit_scene`, `joint._support/parameter_blocks/select_parameters/apply_parameters/fit_depth_bundle/fit_joint_scene`: 같은 접촉 계산으로 ICP의 매 가설·갱신과 native/raw-depth/landmark 정합 변수에 반영한다. 확정된 Object/Robot Base는 접선 XY+법선 Yaw만 허용하며 Z/상대 Roll/Pitch는 접촉에서 결정된다. Yaw 제한이 0이면 XY만, 제한이 있으면 최초 Heading 기준으로 유지해 iteration마다 회전 한계를 재설정하지 않는다. 치수 변경 후 접촉을 다시 계산한다.
- `authoring.scene_analysis_schema/parse_scene_analysis/run_codex_modeling`: 치수 인용과 별도의 `support_relation` 출력·근거를 받는다. 영상 추정/과거 근거 없는 `geometry.support`는 PROPOSED이며 자동 확정하지 않는다. Python 자연어 파서는 없다. 신뢰된 Codex 가이드의 지원 관계 지침과 SHA/버전을 기존 sandbox 전달 경로에 반영한다.
- `editing.apply/preserve`, `automation._reconstruct/retain_fitting`, 기존 Candidate 검증/Export: 새 Asset 교체·Pair·Checkpoint에서 관계를 계승한다. 확정 관계의 삭제·허용 오차 변경은 정합이 수행할 수 없다. 후보 채택/저장은 기존 validate/preserve를 통하며 별도 Support Manager나 Solver는 없다.
- `validate_horizontal_layout`: 명시 Support가 있으면 같은 지지면 기준 진단을 사용한다. 과거 별도 수평 Box 배치 도구의 검사는 해당 명시 호출에만 남긴다. Reconstruction 보고서/UI에 Object/Support ID·출처·Gap/침투·상대 자세/법선/Mount 오차·허용 DOF를 표시한다. Anchor가 존재해도 알려진 Collision이 관통하면 제약 위반이다.

### 확인한 동작과 범위

명시 Support의 잘못된 초기 Pose, 경사면/이미 기울어진 물체, 중첩 지지와 치수 변경, Frame Origin과 다른 Mount, ICP 각 가설·Parameter Block·landmark Solver·실제 RGB Loss의 native Renderer 반복, 새 Asset 적용, 확정 제약 삭제/완화 거부를 시험했다. 단순 근접만으로 Support를 확정하던 자동 감지를 제거했으므로 기존 variable-selection fixture에는 의도한 명시 Support를 추가했고, 자유 회전 Sphere 시험은 Support가 없는 상황을 유지했다. 기존 측정 pair의 공통 지지축 제약도 보존했다.

실제 MuJoCo와 Isaac/PhysX에서 단순 Box의 접촉·중력 300 Step을 각각 실행했다. Isaac 최종 높이 약 0.350000024m, 접촉력 약 0.29428N, 활성 Collision 2개를 확인했다. 이는 합성 물체 접촉 시험이며 실측 파라미터·Robot Articulation/Gripper·경사면의 미끄럼 안정성·Task 성공 검증이 아니다. 새 Camera/Scale 초기화나 실제 사진의 최종 재구성 완료를 주장하지 않는다. 실제 로봇 명령/새 모델 추론/원격 Codex 실행은 없다.

수치 접촉은 유한한 평면의 마찰 안정성·전도 안정성·Grasp 물리 인증을 대신하지 않는다. 복잡한 Support Mesh에 유일한 접촉면을 자동 추정하지 않으며 부족하면 NEEDS_MORE_DATA, 영상 가설은 NEEDS_REVIEW, 확정 관계 충돌은 CONSTRAINT_CONFLICT로 남긴다. 원본 Scene에 새로운 관계를 임의 일괄 등록하지 않는다.

검증 기록은 Git 제외 `workbench_runs/support_constraints_20261107/`의 RED/GREEN 로그, JUnit, Isaac `result.json`, 보존 대조에 있다. 최종 회귀 수치는 아래에 기록한다.

최종 검증: 전체 세 패키지 회귀 **1,541 passed / failed 0 / errors 0 / skipped 0**, 기존 torchvision 경고 4회, 396.45초(`full-suite.xml`). 이 실행 후 접촉면 부족 처리와 UI 후속 변경을 포함한 Builder 회귀 **354 passed**(`builder-release.xml`), 마지막 법선/Yaw 진단 수정은 Support·Qt UI·Checkpoint **37 passed**(`release-focused.xml`)로 확인했다. 따라서 전체 수치를 마지막 후속 수정까지 재실행한 결과로 해석하지 않는다. 최종 관련 검사에 남은 실패는 없다. 중간 UI 시험의 가짜 Process에 `state()`가 없어 발생한 종료 오류는 실제 QProcess를 복원하도록 harness를 수정했다. 법선 각도 계산의 acos 미소 오차는 허용 오차를 늘리지 않고 cross/dot atan2로 수정했다.

Camera 초기 각도 오차를 준 실제 MuJoCo RGB 정합은 50평가에서 RGB Loss 약 **0.01410 → 0.01047**, `BUDGET_EXHAUSTED`였다. 렌더에 전달된 각 Trial과 Best Scene에서 접촉·상대 자세 제약이 유지됨을 검사했다. 수치 품질 인증이나 최종 Scene 성공으로 승격하지 않는다. 별도 원본 보존 대조 **2,389개 SHA 변경 0·누락 0**, bytecode 없는 변경 Python compile 검사와 `git diff --check`를 수행했다. 기존 실행 자료/SDK·모델 전체를 전수 hash한 것은 아니다.

## 2026-11-07 — Auto Reconstruction 단일 실행 화면

Scene Prepare에서 열리는 `ui_reconstruction.ReconstructionDialog`의 다섯 탭과 수동 물체/Mask/USDA/환경 편집 코드를 제거했다. 로그인·계정 전환, 공식 모델/추론 강도, 실제 사용량, 저장 입력으로 연속 생성, 중단/동일 Candidate 재개만 제공한다. Scene Prepare의 입력·저장 화면과 기존 Solver/URDF/Capture/접촉 알고리즘은 이번 UI 변경에서 수정하지 않았다. 앞 절의 미커밋 접촉 제약 구현은 보존했다.

`codex_cli.py`는 설치 CLI의 help/version/login status 및 공식 App Server stdio 계정·사용량·모델 조회를 담당한다. 기본 인증은 `~/.local/share/real2sim-builder/codex`에 격리하고 인증 파일을 복사하지 않는다. 계정 데이터는 화면 메모리에만 존재한다. QThread 비동기 조회, 60초 갱신, 실제 기간/bucket 분리·100-usedPercent·reset 시각, 실패/전환 시 이전 계정 데이터 제거를 구현했다. 수동 모델 ID 대체 입력은 catalog 조회가 안 될 때 사용하며 미확인 강도를 임의 활성화하지 않는다.

기존 `authoring.run_codex_modeling`에 모델/추론 강도 전달과 `runtime.json`의 CLI version 기록을 연결했다. 분석·모델링·비교 판단이 같은 CODEX_HOME/선택 모델을 사용한다. 인증/모델/사용량/네트워크의 명시 구조화 오류를 구분하고 텍스트만 있는 오류는 일반 실패로 유지한다. Project 로그에는 raw CLI 출력/계정 정보 대신 종료 코드와 모델 선택값만 남긴다. 공식 permissions profile로 인증 파일/작업 외 파일 읽기와 도구 네트워크를 막으며, CLI sandbox helper 경로만 읽기 허용한다. 최초 실제 시험에서 인증 홈 전체 deny가 helper 실행까지 막은 실패를 확인하고 해당 최소 경로만 허용한 뒤 재시험했다. 인증을 Sandbox에 복사하거나 네트워크를 열어 해결하지 않았다.

Project lock·기존 control/checkpoint/Asset 검증을 재사용한다. `reconstruction.json.resume`에 현재 signature·완료/미완료 단계·Candidate를 기록하며 성공한 원격 호출 횟수를 계승한다. 분석은 메모·Evidence·응답 SHA, USDA는 기존 fingerprint/Manifest로 재사용한다. 검토 중 실패는 설정과 최선 checkpoint가 일치하면 정합을 반복하지 않고 검토부터 재개한다. 자료 없는 분석이 같은 캐시 응답을 반복하던 경로는 한 번 확인 후 `NEEDS_MORE_DATA`로 종료하도록 고쳤으며 캐시 재사용을 원격 호출 횟수로 계산하지 않는다. 중단된 ephemeral 세션을 복원한다고 가정하지 않는다.

검증 자료는 Git 제외 `workbench_runs/auto_reconstruction_ui_20261107/`에 있다.

- 전체 세 패키지: **1,557 passed / 실패 0 / skipped 0**, 기존 torchvision 경고 4회, 375.34초(`full-suite.xml`).
- 이후 검토 재개·프로세스 종료·로그 보호 수정 포함 Builder: **370 passed**(`builder-release.xml`). 마지막 catalog fallback·자료 부족 중단·Pair UI 선택을 포함한 관련 **75 passed**(`release-focused.xml`). 마지막 진행 라벨의 중복 재배치 제거는 UI **8 passed**(`ui-release.xml`)로 확인했다. 전체 1,557개가 모든 마지막 후속 수정까지 재실행된 수치라는 뜻은 아니다.
- 실제 공식 CLI **0.166.0**: 기존 로그인 환경을 이번 시험에만 명시 사용해 account/model/usage 조회, 최소 Scene 분석 Schema 응답, 동일 Candidate 분석 캐시 재사용을 확인했다. Qt→실제 CLI worker→저장 분석 재사용→`NEEDS_MORE_DATA` 표시도 확인했다. 이 UI 연결 시험은 추론 단계 진입 전 중단되는 환경 fixture이며 실제 SAM/DA3 재실행이 아니다. 실제 계정 로그아웃/전환과 강제 사용량 소진은 수행하지 않고 모의 CLI로 분리 시험했다.
- 실제 CLI sandbox에서 합성 인증 파일·작업 외 파일·우회 symlink 읽기 모두 거부, socket 생성 EPERM, 작업 폴더 쓰기 허용을 확인했다(`sandbox-result.json`). 실제 인증 파일 내용을 읽는 시험은 하지 않았다.
- 원본 대조 **2,389개 SHA 변경 0·누락 0**. 설치/모델/기존 Export·Scene·Capture를 변경하지 않았다. 변경 Python compile 및 `git diff --check`를 확인했다. Commit/Push하지 않았다.

실제 최소 분석은 사진 없는 독립 시험 Project에서 추가 자료를 요청한 결과다. 완성 Scene의 시각/물리 정확도나 실물 Task 성공을 새로 인증한 것이 아니다. 새 Builder 전용 인증 폴더는 아직 로그인 전이며, 사용자가 공식 로그인 절차를 한 번 진행해야 한다. 상세 사용법·기록과 제한은 [Auto Reconstruction UI](auto-reconstruction-ui.md)에 있다.

## 2026-11-08 — 원래 폴더 적용 및 기존 auto_version 실제 실행

별도 통합본을 원래 프로젝트에 적용했다. 최신 단일 UI/계정/Support를 보존하고 DA3 제품 실행 경로를 제거했다. 기존 `auto-version-ba737533`에서 실제 UI→QProcess→Codex 분석/Blender와 MASt3R/COLMAP을 실행했다. USDA 9개를 등록하고 재개에서 재사용했다. 전체 8 View 중 Wrist 3개가 등록됐으며 Sparse 128점, BA 0.487823px다. Metric/공유 Mount는 미해결이다. 등록된 Wrist가 기존 최소 4개 조건보다 적고, 작업판 Mask의 유효 Dense 점이 0개여서 정합·최종 Scene 렌더/승인 Export는 수행하지 않았다. 최종 상태는 `NEEDS_MORE_DATA`이며 전체 회귀는 **1,591 passed, 실패/오류/skip 0**이다. 실제 입력·중간 오류·재개·보존과 범위는 [최종 통합 실행 기록](geometry-backend-integration.md)의 마지막 절에 있다.

## 2026-11-08 — 저장 이름·입력 역할·실제 데이터 이전

원래 Workspace의 두 Scene, Capture, 장치 설정, Precision 4개 Session/Recipe, 공용 Asset 9개, 관련 Candidate·Dataset/Curation 참조를 읽기 쉬운 저장 구조로 실제 이전했다. 기존 ID·측정·발행 Package를 보존했다. Scene/Model 사진을 각각 분리하고 Side/Wrist Capture는 초기 SfM에서 제외했다. 전체 절차·SHA/읽기 대조·UI 및 회귀 범위는 [저장 구조 이전 기록](storage-migration.md)을 따른다. 저장 이전을 기존 실제 사진의 Metric 정합 완료로 해석하지 않는다.

## 2026-11-08 후속 — Photo 렌더 정합에서 센서 공동 정합으로 연결

최신 사용자 지시 `Real2Sim 전체 Reconstruction 파이프라인 완성 및 Real/Sim 반복 정합`을 적용한다. 이전의 “휴대폰은 초기 복원 근거만 사용” 범위를 확장했다. **Scene Photo의 추정 optical Camera/K를 그대로 Virtual Camera로 사용해 다중 View 렌더 정합을 수행한 다음, Side/Wrist 센서 관측을 추가한다.** 최종 정책 관측은 계속 Wrist 우선이며 Side·사진·실측·FK를 희생하지 않는다. 과거 검증 수치는 당시 실행 기록으로 보존한다.

- `authoring.scene_analysis_schema/parse_scene_analysis`: Object별 `model_references`(image_id, 시각 근거, LINKED/AMBIGUOUS), 실제 URDF Link의 `robot_attachment`, Capture 배치의 `capture_layouts`를 구조화한다. Python은 의미를 파싱하지 않고 참조·역할·Transform·근거를 검증한다. Model Reference를 모든 Object에 방송하던 경로를 제거했다. 가이드 변경은 분석 응답 캐시를 무효화하되 기존 검증된 자산 버전은 내용/Identity로 재사용한다.
- `automation._reconstruct`: Photo Geometry→metric registration→Asset 재사용/제작→Photo native fitting 및 별도 비교 저장→`observations.register_sensor_views`→센서 SAM/RGB 관측→같은 `hybrid.fit_scene`의 Photo+Sensor 공동 정합으로 연결한다. 센서는 초기 SfM에 넣지 않는다. 다른/모호한 Capture 배치의 정적 물체는 한 배치의 Object Pose로 합치지 않고 Robot 관측만 허용한다.
- `register_sensor_views`: 기존 Package의 공유 Camera 우선 재사용. 미설정 Camera는 원 Photo pixel/metric cloud와 센서 RGB의 SIFT 대응으로 OpenCV PnP를 초기화한다. 미지 K는 non-planar 대응에서 focal을 추정하고 principal point/aspect/왜곡 가정을 미검증으로 남긴다. Side는 한 공유 Pose, Wrist는 metric pose와 기존 measured-q/FK hand-eye의 공유 Mount/Base를 사용한다. 별도 SfM·새 수치 Fitting Solver가 아니다. 대응 실패와 운동 퇴화는 센서별 NEEDS_MORE_DATA다.
- `inference.build_render_observations`/`hybrid.fit_scene`: 센서 RGB/Mask만 있는 관측도 같은 loss에 넣는다. 이 행은 render_only/점 수0이며 depth/metric residual을 발명하지 않는다. 사진의 raw optical cloud는 유지하며 Camera 변경 뒤 재투영한다. `rendering.render_scene`은 미설정 센서를 일시 렌더 설명에서만 제외한다. 원 Candidate에는 남기고 최종 readiness에서 미완료를 구분한다. Object/Collision 완성 검사를 생략하지 않는다.
- `fit_clouds`: 지지 부모의 pose가 없는 초기화에서 자식부터 접촉 projection해 실패하던 순서를 부모 우선으로 바로잡았다. 부모 관측이 없으면 원인을 남기며 pose를 만들지 않는다. 확정 접촉 수학·허용 오차는 유지한다.
- Real/Sim의 기존 재정합 버튼 위 `Reconstruction Memo`를 추가했다. `evidence.save_reconstruction_memo`는 검증된 source Package Identity에 메모를 연결하고 원본 Scene Memo를 바꾸지 않는다. `refit_pairs`가 동일 Source의 Candidate-local 메모를 고정하고 비교 판단/모델링에 전달한다. 구조적 재모델링도 Pair 모드를 유지하며 초기 Photo 복원을 다시 시작하지 않는다. 과거 Sim q의 추종 차이는 진단이며 새 비교는 measured q를 사용한다. 자동 Promote/Export·하드웨어 제어를 추가하지 않는다.

아래 후속 검증 결과를 추가하기 전에는 이 변경의 전체 회귀/실사진 완성을 선언하지 않는다.

기존 실행 Package에 AI 실행 설정/프롬프트가 없는 경우도 처리한다. `authoring.runtime_configuration`은 같은 Workspace에 명시 저장된 설치 설정만 재사용하며 다른 Project의 Object/메모·인증 정보는 가져오지 않는다. 서로 다른 설치 설정이 여러 개면 임의 선택하지 않는다. Pair 모드는 Geometry Worker가 필요 없으므로 UI에서 SAM만 실행 전 검사한다. Source Object의 이미지 연결 정보가 없으면 Codex가 기존 Source ID에 대한 관측 계획을 분석하고 Candidate의 `review-config.yaml`에 저장한다. 원 Project의 초기 제작 설정을 덮어쓰지 않는다.

기존 Real/Sim 버튼은 선택된 Source Package Identity와 이번 실행의 Capture ID를 함께 전달한다. 같은 Project의 과거 다른 Revision/실행 Pair가 섞이지 않는다. Mask 검출 실패 시에도 등록된 Source Camera와 measured q로 실제 새 RGB/overlay/difference를 저장해 Codex에 진단을 요청한다. 이 경로는 RGB 비교이며 Metric/Geometry 최적화를 실행했다고 표시하지 않는다. Model Reference 연결/기존 메모의 의미를 Python으로 추정하는 경로는 없다.

### 실제 실행으로 발견한 추가 연결 오류

정적 SfM Mask의 허용 역할에 `workspace`와 `background`가 빠져 작업판/배경 물체가 제외되는 오류를 재현·수정했다. Robot/명시 `exclude_from_sfm`는 계속 제외한다. 서로 다른 SfM Component를 하나로 합치지 않는 원칙은 유지하면서, 분리된 Component가 하나라도 있으면 모든 View를 거부하던 처리를 수정했다. 가장 많은 등록 train View를 가진 Component를 상대 기준으로 사용하고 나머지는 미해결 상태로 보존한다. 같은 Image가 여러 Component에 있어도 선택한 Camera prediction의 정확한 Depth Batch를 사용한다. 이 선택의 scale=1은 상대 좌표계 항등변환이며 미터 스케일이 아니다. 검증 View는 선택에 사용하지 않는다.

CLI 0.166.0의 실제 오류는 code 없이 `error`/`turn.failed`의 “You’ve hit your usage limit.” 문장으로 전달됐다. 기존 code-only 분류기가 이를 일반 모델링 실패로 표시했다. 해당 공식 오류 이벤트의 실제 선행 문장만 추가로 인식하며 임의 tool/model 출력의 quota 키워드는 분류하지 않는다. 계정/URL/토큰 원문은 Project 로그에 보관하지 않는다. 실제 App Server `account/rateLimits/read`도 300분 한도 잔여0%, 주간 잔여67%를 확인했다. 이 조회는 추론을 요청하지 않는다. 확인 당시 reset은 2026-11-08 23:28:34 KST다. 자동 계정 교체나 인증 파일 복사는 하지 않았다.

### 실행 결과 — 성공한 연결과 완료하지 못한 단계

| 실행 | 실제 결과 / 해석 |
|---|---|
| 기존 Scene Prepare UI | `auto_version` 선택→기존 Auto Reconstruction 버튼→실제 QProcess CLI. gpt-6.1-sol/low, Codex CLI0.166.0, 저장된 Builder 로그인 사용. 새 가이드/분석 Schema·18개 semantic context 이미지가 실제 작업 입력에 전달됐다. **원격 분석은 사용량 소진으로 실패**. 이번 Schema의 실제 모델 응답 성공으로 보고하지 않는다. |
| 기존 Camera/Scene/Model 입력 | Scene 사진8장, Model 참고2장, 기존 Capture4개를 원래 ID/SHA/배치로 보존. 초기 SfM에는 Scene 사진8장만 전달했다. Model/Capture 이미지는 초기 SfM에서 제외했다. 새 Model Reference→Object 및 Attachment의 실제 언어/시각 판정은 quota 때문에 미완료이며 Schema/참조 검증과 Fake CLI 시험만 완료했다. |
| Photo GPU/Geometry 단계 | 기존 의미 계획과 자산을 사용하는 **분리된 단계 실행**으로 실제 SAM→MASt3R→COLMAP을 실행했다. 역할 수정 전: 검증5쌍/693 Inlier, Sparse2 View/64점이었으나 dense/sparse Sim(3) 실패로 게시된 Geometry View0. 수정 후: 검증6쌍/2,584 Inlier(learned2,628), 두 Component(2 View/41점/0.66696px, 4 View/413점/1.04368px). 두 Component의 dense/sparse 상대 정합 성공, 고유 등록 View5/8. 한 View가 두 Component에 있으므로 관측 개수를 고유 사진 수로 부풀리지 않는다. |
| Metric 등록 | 4 View Component를 기준으로 선택했다. 작업판 Mask의 유효 가시점15,150개를 `metric_plane()`에 전달했지만 **관측 종횡비와 실측150×150mm가 불일치**하여 거부했다. 허용 오차를 바꾸지 않았다. `metric_attempts`에 Object/View/점 수/거부 원인을 기록했다. 두 Component를 억지로 연결하거나 scale을 발명하지 않았다. |
| 실제 auto-version 최종 상태 | 기존 Candidate `auto_mast3r_colmap` OPEN/재개 가능, 기존 자산9개 재사용·신규 버전0. 실제 Photo metric cloud0이므로 **Photo 최종 Sim 렌더·수치 fit_scene·센서 공동 정합·새 승인 Export는 미완료**다. UI 실행의 quota 실패와 별도 Geometry 단계의 NEEDS_MORE_DATA를 구분한다. 과거 Source를 auto-version 결과로 대체하지 않았다. |
| 기존 Real/Sim 버튼 | 등록된 `pickplace-colorblock`의 `scene-v9-task-objects`를 Memory Device로 사용. 실제 Paired Capture1개를 `input/captures/refit_flow_002/capture_001`에 저장하고 네 RGB, measured q, runtime Sim q·Timestamp/Source Identity를 확인했다. 메모는 Source에 연결하고 원 Scene Memo는 보존했다. |
| Pair 재정합 | 기존 UI 버튼→Source/이번 Capture ID→Candidate `refit_001`→기존 Backend를 실행했다. **Codex 분석/검토 응답만 Fake**, SAM은 실제 로컬 Worker, MuJoCo는 실제 Native 렌더다. 합성 Memory 영상에서 대상 Mask를 얻지 못해 Geometry 최적화는 수행하지 않았으나 동일 measured q의 Side/Wrist 새 RGB·overlay·difference를 저장하고 Fake 검토까지 전달했다. Source Package bytes 불변. 이를 실물 정합/물리 개선으로 보고하지 않는다. |
| Isaac 비교 | 같은 `refit_001`과 측정 q에서 소유 Kit child의 실제 `alignment_metrics(engine='isaac')`를 실행했다. Side/Wrist 두 비교 이미지 생성, 약39.68초, physics step0, 정상 종료. 이것은 기존 실행 Scene 렌더 시험이며 새 auto-version Scene의 완성·Isaac 물리/Grasp 성공이 아니다. |
| 수치/제어 연결 회귀 | 기존 실제 MuJoCo fixture로 Photo fitting→센서 추가→동일 Candidate의 공동 fit_scene, Mask-only 관측(Depth 생성0), PnP 미지 K/퇴화 거부, 부모 Support 우선 초기화, Stage별 중단·Checkpoint·Fake quota/재개, Source/실측/q 보호를 검사했다. 합성/Mock 검증과 위 실사진/GPU 실행은 별개다. |

남은 원인은 단순히 “사진이 부족하다”로 단정하지 않는다. 최신 Model Reference/Instance 분석은 실제 계정 한도로 실행되지 않았고, 현재 보존된 계획에서 얻은 Mask/상대 Geometry는 작업판의 실측 비율 검사를 통과하지 못했다. 새 분석 뒤 Mask Identity/가림과 현재 Component의 Geometry를 다시 판단해야 한다. 독립 검증 사진·실물 접촉/물성 관측도 새로 생기지 않았다. 임의 질량/마찰 추정 자동 적용이나 미지원 물리 관측을 검증 완료로 만드는 경로는 추가하지 않았다.

실행 자료는 기존 Candidate 폴더의 `pipeline-ui-result.json`, `pipeline-account-diagnostic.json`, `pipeline-photo-stage-before-static-role-fix.json`, `pipeline-photo-stage.json`, `pipeline-metric-diagnostic.json`, `.cache/inference/results.json` 및 기존 `workbench_runs/real_sim/refit-flow-result.json`, `refit-flow-validation.json`에 있다. MuJoCo 비교는 `pickplace-colorblock/scratch/agent/refit_001/fitting/final/previews`, Isaac 비교는 같은 Candidate의 `fitting/isaac-comparison/isaac-f50d105b421248279069fc5da32aa71f/previews`에 생성됐다. 별도 Worktree/Workspace/시험용 Scene을 만들지 않았다. 시험 도구와 원 미커밋 소스 백업은 기존 외부 복구 영역 `storage-migration/`에 두며 제품은 이를 import하지 않는다.


### 최종 회귀와 보존 대조

마지막 수정까지 포함해 원래 폴더에서 세 패키지 전체 회귀를 다시 실행했다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short --junitxml=<기존 외부 백업>/reconstruction-pipeline-verified.xml
```

**1,616 passed / 실패0 / 오류0 / skipped0**, 391.36초, 기존 torchvision 경고4회다. 저장 이전 직후의 1,600개와 비교해 수집 시험은16개 늘었다. 기존 시험의 의미를 유지하며 새 계약의 입력/Mock 및 작은 화면 배치를 갱신했다. 중간 전체 실행의 가이드 SHA fixture·작은 UI 높이·Mock의 새 keyword 미지원 실패와 수정 기록은 보존했다. 관련 집중 회귀128개도 통과했다. 실제 Codex/MASt3R/SAM/Isaac 실행의 범위는 위 표와 구분하며, 전체 pytest 통과를 실사진 Scene 완성으로 해석하지 않는다.

이번 작업 전 외부 백업에 원 미커밋 소스73개와 diff를 보관했다. 보존 대조는 원 Scene/Input/Export 파일2,494개와 기존 공용 자산 payload209개를 대상으로 한다. 기존 RGB·q·Mapping·메모·모델·발행 Package는 불변이며 누락0이다. 두 Project history는 기존 bytes를 유지하고 새 실행 기록만 추가했다. `pickplace-colorblock/input/evidence.yaml`에는 명시 Memory/Fake 시험 Capture만 새로 등록했다. 원 Capture를 바꾸거나 합성 Capture를 실물 관측으로 표시하지 않았다. 기존 자산9개에 새 버전은 만들지 않았다. 실행 자료가 추가된 것과 원본이 수정된 것을 구분한다.

현재 브랜치 `review/real2sim-multiview-20261106`, HEAD `9384a09e86196d98f107992d1352aaac1dc3a8b8`를 유지한다. Commit/Push/Merge·설치·실물 모터 구동은 하지 않았다. 원래 미커밋 구현과 저장 이전 자료는 보존한다. 실제 auto-version의 남은 단계는 **새 Codex 분석 성공 → 작업판 Mask/실측 비율 문제 판단 → metric 등록 → Photo 및 센서 공동 정합 → 검토/Export**다. 한도 초기화 후 기존 Candidate에서 이어서 실행할 수 있지만, 한도 해제만으로 metric 문제까지 해결됐다고 보장하지 않는다.

## 2026-11-09 — 사용자 실측 정정: 직사각형 작업판

사용자가 이전 150×150mm 정사각형 설명을 정정하고 기존 Scene Memo 및 Candidate에 적용하도록 명시 요청했다. 대상은 `auto-version`이다. 컵 두 개가 나란한 방향을 작업판 로컬 Y로 정의하며, 외곽 X147/Y151mm, 각 변 검은 선 폭2mm, 안쪽 흰 영역 X143/Y147mm다. 이 축 정의를 미확인 World 축/Camera Pose로 확정하지 않는다. 종이 두께는 여전히 미측정이며 기존 렌더용0.15mm는 estimated다.

기존 외부 복구 영역의 `workspace-measurement-before.tar.gz`에 수정 전 메모·구성·Candidate·모델링 결과를 보존했다. `evidence.save_scene_memo`로 150mm 정사각형 문장을 직사각형 설명으로 교체하고 다른 문장은 유지했다. 새 메모 SHA는 `597fff395798cf7d2452817f5fc8a95f392c96ba320fd5a55e9af2497782dcac`다. 현재 Codex 세션이 사용자 발언을 이해해 `objects.workspace_paper.geometry`에 `[0.147,0.151,null]`과 새 인용·SHA를 기록했다. Python 자연어 파서나 가짜 원격 Codex 응답을 만들지 않았다. 다른 Object의 과거 분석은 당시 SHA로 남기며, 다음 전체 실행에서 새 메모에 대한 분석 캐시 검사는 그대로 적용된다.

기존 정사각형 자산 `workspace_paper/v001`은 변경하지 않았다. 기존 Blender sandbox `author_object_assets`를 통해 작업판만 `v002`로 등록하고 동일 Candidate `auto_mast3r_colmap`에 연결했다. 흰 중심143×147mm와 네 검은 테두리(각2mm)를 실제 Mesh로 구성하고, 외곽147×151mm의 별도 convex Collision을 유지했다. 사용자 정정이 허용한 해당 Object의 XY 측정 제약만 새 근거로 교체했다. 다른 Object·Robot/FK·지지 제약·불변 Export와 제품의 보호 검사는 변경하지 않았다. 두께나 재질을 실측/물리 인증으로 승격하지 않았다.

실제 기존 Photo RGB/Mask/상대 Geometry를 재사용해 크기 등록을 다시 계산했다. 이는 새 SAM/MASt3R/Codex 분석 실행이 아니라 **실측 변경 효과를 분리한 수치 재시도**다. 가시점15,150개의 평면 최소 면적 사각형 종횡비는 약1.457866, 새 외곽 비율151/147은1.027211이다. 두 축 scale 차이 지표는 기존37.26% → 새34.66%이며 기존12% 허용 기준을 여전히 초과한다. 안쪽 흰 영역143×147mm를 사용하는 진단도34.59%로 실패했다. 안쪽 치수를 외곽 치수 대신 몰래 적용하거나, 허용 오차/scale을 바꿔 통과시키지 않았다. **치수 정정은 반영했지만 metric 등록은 UNRESOLVED이며 최종 Photo/센서 정합·승인 Export는 아직 미완료**다. 다음 원인 조사는 작업판 Mask·가림과 상대 3D Geometry를 대상으로 한다.

산출물은 같은 Candidate의 `workspace-measurement-correction.json`, `pipeline-workspace-measurement.json`, `workspace-measurement-verification.json`, 기존 `blender/objects/build_003` 및 공용 `workspace_paper/v002`다. 최초 새 모델의 평면 Material subset에서 JSON의 `1e-09`가 기존 YAML Reader에서 문자열로 읽혀 Manifest 동등성 검사가 거부된 실패는 `blender/objects/build_002/rejected-registration`에 보존했다. 새 실패 결과만 정상 Library에서 분리하고, 각 Material Mesh에 기존 추정 종이 두께를 가진 형상으로 재제작했다. 기존 자산/Reader/검증 허용 오차는 고치지 않았다. 기존 Reader의 JSON 지수 표기 호환 문제는 별도 남은 코드 문제이며 이번 데이터 정정에서 해결했다고 보고하지 않는다.

실제 Blender 제작·엄격 Asset Manifest/Closure·Candidate 검증·내측/외측/선 폭 수치·Scene Prepare의 메모 재열기를 확인했다. 제품 소스는 이번 정정에서 변경하지 않아 전체1,616개 회귀를 다시 실행하지 않았으며, 그 수치는 앞 작업의 소스 회귀 기록이다. 새 Scene/Worktree·설치·하드웨어·Commit/Push/Merge는 수행하지 않았다.

### 2026-11-09 후속 — A35 광각 가설과 사진별 Depth 분리 진단

사용자는 Scene 촬영 기기가 Galaxy A35 5G 후면 광각이라고 알렸다. 저장된8장에는 EXIF Make/Model/FocalLength/FNumber/Lens/배율 정보가 없어 원 파일에서 렌즈 Identity를 독립 확인하지 못했다. 모델명이나 명목 화각으로 실측 K/왜곡 계수를 생성하지 않는다. 현재 `sfm.colmap_worker`의 미보정 Camera는 SIMPLE_RADIAL의 focal/k1을 추정하며 `object_points`에서 해당 왜곡을 반영한다. 왜곡 처리가 전혀 없는 경로는 아니다.

같은4개 등록 View·원 RGB/Mask/NPZ SHA를 고정한 읽기 전용 비교에서 현재 왜곡 적용 시 합친 작업판 종횡비1.457866, 왜곡0 가정 시1.449218로, 둘 다 실제151/147=1.027211과 불일치했다. 왜곡0은 원인 분리용 대조이며 Calibration에 적용하지 않았다. 이 차이만으로 실제 렌즈 추정 오류가 없다고 증명하지는 않는다.

사진별로 보면 img3은 비율1.03631/평면 비평탄 지표0.02318, img1은1.04886/0.01911로 기존 metric_plane의 조건을 통과한다. img2는1.47227/0.12025로 기존 평면 조건0.08도 실패하며, img8은1.61988이고 Mask 내 유효 Depth가 약5.99%뿐이다. img1도 유효 Depth8.77%여서 비율 통과만으로 완전한 관측이라고 볼 수 없다. img3은48.67%, img2는40.06%다. Mask가 온전해도 Dense Depth는 부분 관측이라는 점을 구분한다.

개별 기존 검사 통과 View만 합치는 **진단용 사후 부분집합**은 비율1.03643/scale≈0.07409로 계산되지만, 선택을 결과 비율에 의존했으므로 Production 등록에 적용하지 않았다. 현재 전체 View를 먼저 합친 뒤 직사각형/평면 검사를 수행하는 경로에서 저품질·부분 Depth 관측이 전체 extent를 왜곡하는 직접적인 실패 양상을 재현했다. Camera/Depth 추정에서 이 오차가 생긴 근본 원인은 아직 확정하지 않았다. 후속 수정은 결과에 맞는 사진 골라내기 대신 View별 가시 범위·평면/다중 View 일관성 검사를 통해 판단해야 한다. 실제 렌즈 공유는 촬영 배율/렌즈가 같다는 사용자 확인 또는 독립 근거가 필요하다.

근거는 같은 Candidate의 `pipeline-camera-distortion-diagnostic.json`과 외부 복구 영역의 읽기 전용 `diagnose_workspace_camera.py`다. 이 진단에서 원본·Camera·설정·Candidate Scene·발행 Package나 제품 코드를 바꾸지 않았다. 새 GPU/원격 Codex 추론은 수행하지 않았다.
