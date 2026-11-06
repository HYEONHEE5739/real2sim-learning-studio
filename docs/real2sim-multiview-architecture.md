# Real2Sim 다중 시점 파이프라인 재설계

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
