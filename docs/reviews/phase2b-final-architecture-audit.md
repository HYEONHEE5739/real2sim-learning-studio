# Phase 2B — 최종 Working Tree 감사와 실제 Scene 실험 준비

2026-11-15. `feat/simfoundry-style-reconstruction`, HEAD `97c029e195ab8587603fb3f240f2c1a6c0f91f52`. Phase1A–1D/2A의 **미커밋 Working Tree**를 시작점으로 동결했다. HEAD만 조사한 결과가 아니다. 이번 변경도 Commit/Push/Merge하지 않는다.

## 1. Executive Summary

**COMPLETED — 요청된23개 경계와 새 High 교차 결함2개를 검증·수정했다. 최종2,131 passed / 실패0·오류0·skip0, 실제 exit0이다. 보호19,612개 파일 변경·누락·신규0을 확인했다. 통제된 실제 Scene 진단은 GO, 실제 이미지/물리/실물 검증은 NOT_TESTED다. 종료 진단 Medium1개는 명시 Backlog로 남긴다.**

기존 수정23개를 실제 Producer/Consumer와 대조하면서 두 High 교차 결함을 재현하고 수정했다. Stage10의 고정 World 점군은 Camera Fit 후 소비 불가능해졌고, 직접 Joint/수치/렌더 호출의 Holdout 사용이 기록되지 않아 같은 자료가 독립 Calibration 감사로 다시 통과할 수 있었다. 경로 이식성에서도 고정 사용자 경로와 직접 UI 실행의 저장 보호 누락을 수정했다.

신규 교차 검사 **14 passed**, 실제 CPU Source→Annotation→Mimic→Curation→공식 LeRobot→ACT Scratch/Resume→MuJoCo 평가를 실행했다. ACT는 추가 학습1회씩 누적 Step1→2, 두 공식 Trainer의 exit0이다. 평가3 Step은 **정책 작업 실패**이며 R03 실행 완료와 구분한다. 재구성 Provider/실물의 성공을 뜻하지 않는다.

원시 근거는 저장소 밖 `/tmp/real2sim-phase2b-20261115-nragn39y/`에 있다. 삭제되면 원시 자료를 다시 열 수 없고 제품은 이 폴더에 의존하지 않는다. 기준 문서6개, AGENTS와 Scene Guide/Rules, 패키지 설정, 현재 소스와 Caller, 최초 RED·이전 최종 JUnit을 대조했다. 과거 통과 수를 이번 실행 결과로 대체하지 않았다.

시작 기록: tracked499개·기존 untracked28개 byte/SHA 백업, HEAD/브랜치/빈 Index diff, 보호 root19,612개 파일 ledger, 실제 **2,117개 testcase**의 JUnit Counter. 환경은 기존 `lerobot-arena` Python3.11.15, Torch2.7.0+cu128, LeRobot0.4.1/Draccus0.10.0/datasets4.1.1, NumPy1.26.0/SciPy1.15.3/MuJoCo3.3.7이다. Isaac Sim 배포5.1.0.0/Lab 배포0.47.2와 Lab 소스 v2.3.0은 구분한다. 설치하지 않았다.

## 2. BUG-001–021 + FIX-A/B 검증 Matrix

아래 파일명은 해당 패키지 `tests/` 기준이다. 기존 수정의 최초 재현은 각 Phase 보고서의 RED 로그와 대조했고, 이번 판단은 현재 소스·호출 경계·최종 회귀를 함께 기준으로 한다. 정상·거부·보존 검사를 실제 실행하지 않은 모델 정확도와 혼동하지 않는다.

| ID | 현재 수정과 실제 Caller/Consumer | 정상·거부·보존 및 교차 근거 | 최종 상태 |
|---|---|---|---|
| BUG-001 | `reconstruction.run` trial→preserve/validate→게시, `camera.fit_cameras` 보호 Pose 제외 | `test_current_calibration_protection`: estimated fit, calibrated/measured 거부, Stop/실패/Export rollback·손상 YAML·Current bytes | PASS — 현재 소스·회귀 확인 |
| BUG-002 | Precision 생산 `CALIBRATED_MANUAL`→Mapper→Capture Reader. 물리 검증 false | `test_precision_capture_contract`: 실제 계산/저장/관측, Legacy 수동 상태, model/hash/계수/단위 손상 거부 | PASS — 현재 소스·회귀 확인 |
| BUG-003 | Capture/Snapshot/Pair Writer→Reader→Import→센서 등록의 model/mapping/units/role | `test_capture_sensor_contract`, Workflow B: Bound/Unbound·비표준 Camera ID/역할 충돌, 원 Archive/q 불변 | PASS — 현재 소스·회귀 확인 |
| BUG-004 | Joint residual이 View별 `observation_scene`의 Pose/K/EXIF/crop/FK 사용 | `test_joint_camera_adaptation`: 공유 Photo 두 Pose·전역 Pose 없음·한 View 변경·Validation 제외·Side/Wrist 공유 Mount 보존 | PASS — 현재 소스·회귀 확인 |
| BUG-005 | `build_env_cfg`→RuntimeCamera native Lens Schema/readback→state/NativeRenderer | `test_isaac_camera_intrinsics`: 비대칭/off-center K, 부분 env setter·잘못된 K 거부·400×300 Consumer; 실제 Kit는 미실행 | PASS — 현재 소스·회귀 확인 |
| BUG-006 | UI full JSON→공식 Config 정규화→freeze→Trainer→Seal→Resume | `test_checkpoint_config_resolution`, Workflow C: null/default·정상 Resume, optimizer/architecture/Step/Dataset 변조 거부·원 Checkpoint 보존 | PASS — 현재 소스·회귀 확인 |
| BUG-007 | `_origin/episode_overlap`→Merge/Curation/Offline Validation | `test_validation_episode_lineage`: UID/Alias/복사 Resume/Trim/불명확 family 차단, 진짜 독립 Episode 허용·첫 추론 전 거부 | PASS — 현재 소스·회귀 확인 |
| BUG-008 | Project checkpoint의 control 파일 atomic claim; Pause도 같은 소유권 | `test_reconstruction_control_race`: 새 Stop interleaving·Pause·Lock/읽기 전용; 새 명령을 옛 consumer가 삭제하지 않음 | PASS — 현재 소스·회귀 확인 |
| BUG-009 | 공식 Writer staging/complete→Catalog/Discovery | `test_dataset_publication_visibility`: 진행 중/실패·rename/intent 오류 비노출, Legacy 정상 읽기·기존 Dataset SHA | PASS — 현재 소스·회귀 확인 |
| BUG-010 | USDA Converter의 planar concave ear clipping, 원 corner/UV/subset 유지 | `test_asset_semantic_geometry`: L면 면적/coverage·winding/시작점, unsupported 교차·비평면 거부, 구형 convex quad/zero-area cap 보존 | PASS — 현재 소스·회귀 확인 |
| BUG-011 | 새 semantic SHA→Asset Reader/Instance/portable Export; Legacy metadata 재도출 | 같은 시험: Pose/type/color/entry 변조 거부·원 자산 bytes 및 기존 content SHA/Version 의미 유지 | PASS — 현재 소스·회귀 확인 |
| BUG-012 | Direct Candidate Joint 채택→scope/preserve→공통 재투영→save | `test_direct_fit_observation_refresh` + 신규 `test_actual_joint_fit_keeps_stage_world_points_consumable_without_inventing_raw_depth`: 실제 Full Rank solve·Camera/Mount/Base·반복/미채택 | PASS — 현재 소스·회귀 확인 |
| BUG-013 | Stage10의 typed cloud→등록→Hybrid Consumer; 이번 fixed World 의존성 보완 | `test_stage_cloud_contract` + 위 교차 시험: 원 cloud/Mask/grid/SHA 보존, Camera 변경 뒤 소비 가능·unknown Legacy stale 거부 | PASS — 현재 소스·회귀 확인 |
| BUG-014 | Stage6 최종 enhanced→infilled→observed 선택→validity→Stage7 References | `test_prepared_image_handoff`: 2×2×2 조합·infill-only·빈 Alpha/격자 거부·원 RGB/Z/Mask SHA | PASS — 현재 소스·회귀 확인 |
| BUG-015 | 요청 Device를 공식 from_pretrained 이전 cfg와 입력 Processor에 적용 | `test_policy_requested_device`: saved CUDA→CPU, 반대 요청/지원 없는 CUDA 거부·파일 불변. 이번 실제 ACT/Eval도 CPU | PASS — 현재 소스·회귀 확인 |
| BUG-016 | 중복 Step rejected ACK, 원 Step 유지; Qt matching terminal ACK까지 Pending | `test_step_command_conflicts`: 실제 R03/Qt·같은 ID replay·다른 ID·Cancel·vector 거부 | PASS — 현재 소스·회귀 확인 |
| BUG-017 | 평가 steps0는 initial_state_satisfied/success=false/policy_executed=false | `test_evaluation_initial_state`: 양 엔진 초기/pre/post Step·Native failure Attempt/Resume·빈 Episode 금지. Workflow C는 실제3 Step 실패 게시 | PASS — 현재 소스·회귀 확인 |
| BUG-018 | R03 gripper 승인은 prepared one-shot mode/command calibration/budget/full-motion OFF만 전달 | `test_gripper_r03_approval`: 정확한 Proposal1회 memory write·다른 모드/ID/Cancel/Timeout0회. 하드웨어 미연결 | PASS — 현재 소스·회귀 확인 |
| BUG-019 | Convert/Merge Episode·decoded frame·게시 직전 Cancel checkpoint, Writer finally 종료 | `test_conversion_cancel`: 실제 변환/병합/Video 취소·staging 보존·기존 자료 불변·일반 IO 오류와 Cancel 분리 | PASS — 현재 소스·회귀 확인 |
| BUG-020 | 두 Source 엔진의 함수/Parameters가 공통 execution contract/Resume fingerprint에 포함 | `test_source_function_contract`: MuJoCo scalar·명시 Fake Isaac vector·동일 Append 허용/변경 거부·함수 없는 Legacy 유지 | PASS — 현재 소스·회귀 확인 |
| BUG-021 | Curation Quality는 실제 Task 대상 ID만 사용 | `test_quality_target_identity`: Distractor/순서 교체·복수/미기록 null·원 success/selection 불변 | PASS — 현재 소스·회귀 확인 |
| FIX-A | Stage10/Numeric 자동 채택 Full Rank gate; Direct/Hybrid 미검증 draft와 분리 | `test_joint_acceptance_policy`: rank2/6+RMSE 개선도 자동 적용 거부, rank6/6 허용·Stop/재개·보호 Scene/Best | PASS — 현재 소스·회귀 확인 |
| FIX-B | Qt 선택 Capture→같은 Source/Layout resolver→Dialog/CLI→Backend 재검사 | `test_refit_capture_selection`: A/B·혼합/누락/Source/Pair 변조 거부·기존 Candidate/Evidence 보존·명시 Layout CLI 호환 | PASS — 현재 소스·회귀 확인 |

독립 탐색에서 기존 BUG-012/013의 개별 통과만으로 교차 계약을 승인하지 않았다. 두 검토자가 각각 실제 Producer/Consumer의 stale 오류를 재현했고, 하나는 **대체하지 않은 SciPy Solver**로 확인했다. 전체23개에 대한 현재 소스 대조·테스트/Caller 감사는 아래 통합·회귀·정적 자료와 함께 해석한다. 병렬 검토자의 원시 probe는 교차 경계 탐색 근거이며 모든 모듈을 별도 검토자가 전수 승인했다는 뜻은 아니다.

## 3. RISK-001/002 분석 및 조치

### RISK-001 — 실제 경로 결합과 저장 보호

세 패키지 제품 Python **177개**의 AST/Import·절대 경로 literal과 Launcher를 조사했다. Fixture/과거 기록/문서 예제는 제품 의존성과 구분했다. 기존 Launcher의 `/home/...` Backend/IsaacLab, Recipe/Training JSON의 특정 사용자 보호 prefix를 확인했다.

기존 `QT_PYTHON/BACKEND_PYTHON/ISAACLAB_ROOT/WORKBENCH_WORKSPACE`와 CLI를 재사용했다. 프로젝트 위치는 script 자신 기준, CLI override는 기존 마지막 값 우선이다. 현재 계정의 기존 기본 설치 경로를 명시된 기본값으로 보존하고, 설정된 실행 파일/Isaac 소스가 없으면 해당 변수명으로 오류를 낸다. Isaac 소스를 설정하지 않은 MuJoCo UI에 새 설치를 강제하지 않는다. README에 기본값/명시 설정을 기록했다. 실행 가능한 임의 다른 Python을 탐색하지 않는다.

저장 보호는 현재 계정·Qt/Backend prefix·명시 Isaac/Conda·기존 Workspace 보호 경계를 같은 helper로 검사한다. symlink의 실제 목적지도 검사한다. 설치 prefix는 알려진 bin 배치에서만 도출하고, 알 수 없는 wrapper/없는 Interpreter 경로로 파일시스템 전체를 보호하지 않는다. 실행 파일 자체는 별도로 보호한다. PipelineSettings는 Editor에 소유 parent를 전달한다. 직접 UI 진입의 Source/Device Editor는 기존 소유 BackendJob의 Interpreter를 사용한다. 새 설정 DB/설치기는 없다.

공백이 있는 재배치 프로젝트/다른 계정에 해당하는 임시 홈, 명시 경로·잘못된 경로·CLI 우선순위·실제 Qt Editor 거부를 검사했다. **다른 OS 계정/다른 PC의 실제 SDK/GUI E2E는 미실행**이다. 로컬 Runtime YAML의 절대 경로는 자동 이전하지 않는다.

### RISK-002 — Validation과 최종 독립 Test

| 자료 | 실제 사용 | 최종 독립 정확도 의미 |
|---|---|---|
| train/fitting | 잔차/변수·초기값·렌더 Best 최적화 | 없음 |
| 저장 split=validation | Joint/직접 Camera fit의 veto, Candidate nonregression, 반복 렌더/사용자 검토 | 선택용 Validation; 최종 Test가 아님 |
| Numeric report_only | train만 Best/solve에 사용하고 validation은 보고 | 사람의 후속 선택에 사용될 수 있어 소비 이력 유지 |
| 최종 미사용 Test | Scene/자산/K/Mount/Mapping을 고정한 뒤 새 Side/Wrist 세션으로 단회 평가 | 확보·평가·검토 전까지 NOT_RECORDED/NOT_VERIFIED |

직접 Joint Solver가 본 `pose_3`을 기존 `quality:camera`가 다시 `CALIBRATED`로 승인하는 실제 반례를 확인했다. 원 Camera 수학이 아닌 **사용 이력의 Caller 누락**이었다. 같은 기존 `working/calibration_holdout_usage.jsonl`에 Direct Joint/Depth Bundle/수치 metric/Hybrid fit 최종 진단/alignment/Scene validation의 사용을 기록한다. 사용한 Scene digest·목적·ID를 남기며 원 Capture/Pair/split/기존 이력은 재작성하지 않는다. veto뿐 아니라 보고용 사용도 기록한다. 새 프레임의 근거 없는 독립성을 추정하지 않는다.

Scene validation의 반복 진단은 `MULTIPOSE_GEOMETRY_DIAGNOSTIC`, `independent_verification=false`, `final_independent_test=NOT_RECORDED`로 표시한다. `passed`는 기존 선언 기준 통과이며 독립/물리 인증이 아니다. 새 미사용 자료의 제한된 `assess_camera` 감사는 보존하고, 이미 사용한 자료는 기존 fresh-holdout gate로 거부한다. 기존 Wrist Mapping 미확인 오류가 먼저 드러나는 순서도 보존했다. 과거 누락 이력을 거짓으로 채우지 않았으며, **이력이 없다는 것만으로 과거 자료를 새 Test로 인정하지 않는다.**

Scene Rules의 “holdout을 선택에 쓰지 않는다”와 기존 veto의 용어 차이를 정리했다. 저장 validation/holdout_policy 이름과 수학은 유지하고, 최종 미사용 Test를 반복 Validation과 구분한다. Codex 모델링에 최종 Test를 수정 근거로 제공하지 않는다. 새 사진은 촬영하지 않았다. 구체 절차는 §13이다.

## 4. Architecture / Complexity Audit

| 책임 경계 | 확인한 계약 / 결과 |
|---|---|
| Scene·Project·Candidate | Current/Revision 불변, trial/candidate에서만 수정, preserve/validate/scope 및 원자적 제어 소유권 유지 |
| Stage Runner·Worker·Artifact | Runner가 실행·Stop/재개, Worker가 Runtime, Artifact가 SHA/closure/단위/provenance. 완료 Mock을 실제 추론으로 승격하지 않음 |
| Camera/World·관측 | Camera-to-parent Optical/DA3 W2C, m/rad·pixel affine·measured q/FK 유지. raw-relative cloud와 fixed World의 의존성 의미 분리 |
| Library·Native Export | USDA 원본/Version·semantic binding, 독립 Visual/Collision·Exporter closure 재사용. 기존 Asset 재생성/Viewer 교체 없음 |
| UI·R03·명령 | UI는 상태/ACK 표시, R03는 소유 Worker·allowlist/취소, 엔진은 Step/Task 수행. UI에서 SDK/토크 실행 없음 |
| Native·Curation·LeRobot | 게시/미완료/계보·선택 의미를 각 소유 경계에서 검사. Legacy 공식 Dataset 읽기와 새 staging 비노출 구분 |
| Training·Checkpoint·Evaluation | 공식 Parser/Trainer/processor 사용, 요청/Resolved/실제 저장 의미 결합. 학습 완료·정책 Task 성공·독립 성능은 별도 |

177개 제품 Python의 AST/Import inventory, 주요 공개 진입과 위23개 Caller/Consumer를 대조했다. 이는 외부 SDK/모든 런타임 조합의 동적 전수 검증이 아니다. 이번에는 기존 모듈의 helper와 호출 경계만 보완했다. 새 제품 모듈/Framework/Dependency/Manager/Registry나 CLI 옵션·Scene/Dataset/Checkpoint schema version 변경은 없다.

유지보수상 다음은 **판단성 Backlog**이며 재현된 결함 수에 더하지 않는다. AST branch-node 수는 McCabe 복잡도나 성능 수치가 아니다.

| 항목 | 관찰 / 판단 | 이번 결정 |
|---|---|---|
| 큰 함수·Divergent Change 가능성 | `authoring.run_codex_modeling`326행/branch node106, `recipe.prepare_recipe`204행/117, Hybrid fit206행 | 장기 분리 후보. 이번에 Stage/학습 Framework를 재설계하지 않음 |
| Repeated Switches 가능성 | CLI/Recipe/R03/UI의 Stage/명령 dispatch | 소유자가 다른 공개 경계라 일괄 통합하지 않음. allowlist·ACK 교차 시험 유지 |
| Data Clumps/Primitive Obsession 가능성 | Camera/q/파일 SHA 및 Artifact/Checkpoint JSON | 기존 공개 dict/Schema를 typed-framework로 교체하지 않음. 실제 검증기/출처 경계 유지 |
| 중복 검사 | UI prepare와 Worker 실행 전 SHA, Library/Export closure, checkpoint seal/read | 변경 가능 시점·소유권이 달라 필요한 재검사. 무조건 제거하지 않음 |
| 이력 중복/성능 | 기존 Candidate journal과 새 수치 소비 이력이 함께 남을 수 있음. Offline validation은 error/latency list 축적 | 정확성을 우선 보존. 대량 자료 성능·집계/streaming 개선은 별도 측정 후 진행 |

### Standards

AGENTS/Scene Rules의 원본·좌표·독립 검증 규칙에 비춰 고정 World 자료의 stale 채택, Holdout 재사용 승인, 사용자별 저장 보호 누락을 재현했다. 각각 기존 모듈에서 수정했다. 측정/실물 결과 발명·원본 변경·새 실행 Framework는 관측하지 않았다. 큰 함수·반복 dispatch·JSON 데이터 묶음은 위 표의 판단성 유지보수 우려이며 문서 위반으로 단정하지 않는다. 병렬 Standards probe는 World cloud/Camera/Base/Object 대조를 제공했고, 최종 저장 보호·전체 소스 검토는 주 작업자가 보완했다.

### Spec

사용자 §3/§6의 Producer→Consumer/Calibration 의존성 요구에서 BUG012×013 교차 누락, §5의 “이전 Holdout을 독립 Test로 재분류 금지”에서 실제 재사용 승인 누락을 확인해 수정했다. §4의 경로 이동/기존 설정/오류 요구도 최소 보완했다. §7의 CPU 학습/Resume/평가는 실행했고, 실제 대형 모델·Isaac·실물 미실행은 요청된 경계다. Mock A를 실제 Provider E2E로 보고하지 않는다. 병렬 Spec probe는 대체 없는 Solver 및 Holdout 반례를 제공했다.

두 축의 원시 finding은 별도로 보존했다. Standards 축: 교차 보호/의미 문제3종(수정), 최상위 High. Spec 축: 교차 누락 High2종과 이식성 보완(수정), 추가 종료 진단 Medium1종(아래 Backlog), 최상위 High. 위 유지보수 판단은 이 수에 합산하지 않는다. 병렬 탐색은 사용량 제한으로 최종 요약 전 종료돼, 전수 독립 승인으로 주장하지 않고 주 작업자의 소스/반례/통합 검증으로 보완했다.

## 5. Producer → Consumer 통합 검증

### Workflow A — Stage1–14

작은 합성 RGB4장과 Model Reference를 실제 Project에 등록하고 기존 `_run_stage_pipeline`→14개 Artifact→Candidate→실제 Native USDA/Manifest→Review Export/closure/parser를 통과했다. **DRAFT_READY, 14 Stage**, harness4.713초. 재개 시14개 Artifact SHA/재사용과 Provider 호출 증가0, 원 입력 SHA 불변을 확인했다.

DA3/SAM/VLM/편집/CPD·Mesh 제작 Provider/Physics/Simulator는 명시 Mock이다. Stage12 실제 Physics Step0, Stage14 센서 정확도 NOT_VERIFIED다. 이것은 **실제 Orchestrator/Native 저장·Package 계약 + Mock Provider 연결**이며 실사진 Reconstruction/Isaac 성공이 아니다. Stage별 Runtime/Stop 28개 재개·부분 실패·손상 Cache 차단은 기존 통합 회귀에서도 검사한다. 근거: `workflows-ab/result.json`의 A, 실제14개 `artifact.json`/Package.

### Workflow B — Capture→등록→Fit→Save→재투영→진단

실제 Capture Writer/Reader/Import, 서로 다른 Side/Wrist K, 합성6관절 URDF와 명시 q 두 자세의 RGB4장, 실제 센서 등록과 Candidate Joint Fit을 연결했다. RGB와 Calibration/q 값은 합성이다. 하드웨어·렌더는 미실행이다.

| 관측 | 실제 결과 |
|---|---|
| Side K | fx410/fy390/cx310/cy235 |
| Wrist K | fx520/fy470/cx318/cy242 |
| 등록 | REGISTERED_ESTIMATED |
| 실제 Joint solve | rank6/6, train RMSE13.878013→4.699e-14px |
| 반복 Validation 진단 | 32점, RMSE6.865e-14px, behind-camera0 |
| 새 독립 감사 시도 | 같은 자료이므로 NEEDS_MORE_DATA / fresh holdout required |
| 보존 | Archive·Current·Evidence·Camera/Frame·q 불변 |

숫자는 무잡음 합성 기하의 산술 잔차이며 실물 정확도가 아니다. Candidate save/재투영 뒤 실제 Consumer까지 통과했다. 별도 신규 cloud 교차 시험은 raw-derived 및 Stage10 fixed World를 함께 소비한다. 부족 Rank의 미채택과 Full Rank 채택·보호 값·Stop/재개는 FIX-A 회귀와 대조했다.

첫 합성 Capture가 모든 View에 같은 체크무늬 bytes를 써 train/validation source-image leakage로 **정상 거부**된 기록도 보존했다. 그 실패를 숨기거나 gate를 완화하지 않고 새 합성 입력에서 View별 marker를 달리해 검사했다. 새 사용자 사진의 독립성을 증명한 것이 아니다. 근거: `workflows-ab/result.json` B, `workflows-ab-rejected-identical-input.log`.

### Workflow C — 실제 CPU 학습과 평가

기존 읽기 전용 수치 동작 fixture를 **새 CPU MuJoCo 실행에 입력**했다. 옛 opaque Snapshot/모델 identity를 현재 실행이라고 재라벨하지 않았다. Source388프레임·실제 Annotation1 Episode→Mimic/DLS399프레임1 Episode→Curation4프레임→공식 LeRobot Writer/Parser→실제 R03 Convert/Train/Resume/Simulation Evaluation을 실행했다.

Mimic의 합격 predicate는 임시 Task의 명시적 **trajectory-completion smoke**다. 물리적 grasp/place 합격이 아니다. Annotation은 기존 실제 CPU Replay/Task 계산이다. 새로운 DataGen Episode는 새 identity를 가지며 Annotation ancestry/source pool을 보존하고, Curation→LeRobot의 원 DataGen Episode UID·frame 범위→학습 Dataset identity를 확인했다.

ACT는 Side/Wrist640×480 RGB와6차원 state/action을 유지하고 pretrained weights=None, CPU, batch1/worker0, dim_model16/FF32/head2/encoder1/decoder1/VAE1/latent4/chunk2로 제한했다. 영상 Backbone은 공식 ResNet18이므로 이전 Phase1D의 영상 없는8,686 Parameter 모델과 같은 구성이라고 표시하지 않는다. GPU/모델 다운로드0이다.

| 실행 | 실제 결과 |
|---|---|
| CPU Source+Annotation | 388프레임/1 Episode, harness9.036s |
| CPU Mimic/DLS+Native 게시 | 399프레임/1 Episode, 5.430s; 합성 transport predicate |
| 공식 Convert R03 | completed, fixture_runner=false; Parser4프레임·원 UID 일치 |
| 공식 ACT Scratch | 실제1 update/Step1, Trainer exit0, 11.786s, Child RSS 관측 Peak1250.78MiB |
| 공식 ACT Resume | 추가1 update/Step2, Trainer exit0, 12.530s, Child RSS 관측 Peak1256.59MiB; parent Checkpoint SHA 불변 |
| 실제 CPU Policy+MuJoCo 평가 R03 | 3 Control Step/3 infer 호출, max_steps/success=false, failure Attempt·실제 Episode 게시, Worker completed |

R03 Train/Resume 준비·봉인 포함 harness46.303s, 평가8.739s다. Control Step은 엔진의 기존 decimation을 포함하며 내부 Physics Step 수를 별도로 계측하지 않았다. infer 호출에는 action queue 사용도 포함되며 내부 신경망 Forward 횟수를 별도 계측하지 않았다. 두 학습 update의 loss는 기록일 뿐 품질/수렴 근거가 아니다. 전환·Native/기록·모델/물성은 기존 제품 경계를 사용했고 새로운 학습 Framework는 없다.

Harness의 Task callable 인자명과 `_origin`의 cache 인자를 잘못 적어 수집이 중단된 로그도 보존했다. 정상 완료한 Source/Annotation/Mimic/Convert/학습을 반복하지 않고 결과를 재검사하며 이어갔다. Convert의 마지막 harness 시간1.225s는 이미 완료된 Worker를 재사용한 소비자 확인 구간이며 최초 변환 전체 시간이라고 보고하지 않는다. 전체 E2E 시간을 단순 합산하지 않는다.

실제 R03 Worker4개의 PID 종료를 확인했다. 부분 자료의 비노출·Cancel/Writer close와 zero-step 의미는 신규 Workflow의 성공으로 대신하지 않고 기존 명시 부정 회귀를 함께 실행한다. 근거: `workflow-c/result.json`, `r03/*/run.json`, 두 `training-result.json`, 실제 봉인 Checkpoint·공식 Parquet/MP4·Native HDF5.

## 6. 기존 동작 및 Legacy 호환성

- Direct Candidate/Hybrid의 Rank 부족 **미검증 진단 초안**은 허용하고 Stage10/Numeric 자동 채택의 Full Rank gate를 보존했다. 전역 Solver 수용 의미를 바꾸지 않았다.
- raw optical point는 실제 K/Pose/q에 재투영한다. 명시 fixed World는 점 bytes/경로를 유지하고 현재 Camera 의존성만 갱신한다. 의미를 알 수 없는 구형 비-raw cloud에 marker를 발명해 stale 검사를 통과시키지 않는다. 기존 결과는 보존하고 cached 입력으로 새 진단을 준비해야 할 수 있다.
- 구형 Asset semantic SHA 부재의 metadata 재도출, 기존 content SHA·Version·Native exporter, 외부 정상 공식 Dataset/기존 Checkpoint v1 Reader를 유지했다. Stage6 NPZ-only 관측 Crop·함수 없는 Source도 유지한다.
- UI/Backend 공개 함수 필수 인자와 CLI는 유지한다. 새 옵션/패키지/생성기는 없다. `geometry_binding`은 기존 derived cloud의 선택 metadata다. Scene/Dataset/Checkpoint schema version을 교체하지 않았다.
- 반복 검증의 report scope 문자열은 의도적으로 DIAGNOSTIC으로 정정했다. 과거 파일은 변환하지 않는다. 저장 `passed`는 기존 시각/기하 기준이며 추가 독립/물리 상태를 함께 읽어야 한다. 저장 validation split과 legacy field 이름도 그대로다.
- 로컬 Runtime YAML/모델/Conda/계정 설정은 수정하지 않았다. 런처의 홈 기본값은 현재 계정으로 해석하며, 사용자 명시 경로와 CLI override가 우선한다. 다른 호스트에서 필요한 기존 설치·모델 경로는 사용자가 명시해야 한다.

## 7. 전체 회귀 및 실제 Exit Code

기존 wrapper를 `/tmp`에 복사하여 HF/XDG Cache 출력만 격리했다. 실제 설치 Blender 경로와 기존 Qt/USD/Backend를 사용한다. 제품 실행 파일·환경을 설치/수정하지 않았다.

| 검사 | 결과 | 근거 |
|---|---|---|
| 경로 이식성 최초 RED | 5 failed/1 passed, .28s | `portability-red.xml/log` |
| Cloud/Holdout 실제 교차 RED | 4 failed/1 passed, 5.77s | `cross-red.xml/log` |
| 첫 수정 교차 | 11 passed, 3.05s | `cross-green.xml/log` |
| 관련 기존 회귀 최초 | 1 failed/50 passed, 11.52s; Wrist mapping 오류 우선순위 | `focused.xml/log` |
| 오류 순서 보존 후 | 51 passed, 11.76s; 기존 시험/기대 변경0 | `focused-verified.xml/log` |
| 직접 UI 소유 Backend RED | 1 failed, .23s | `owner-red.xml/log` |
| 직접 Editor 보완 후 신규14개 | **14 passed, 3.91s, exit0** | `final-new-verified.xml/log` |
| 첫 전체 실행 | **1,163 passed까지 중단**, 경고1, Console608.87s, 실제 exit2 | `release-full.xml/log/result.json` |
| 첫 완료한 전체 실행 | **2,129 passed / 2 failed**, 오류/skip0, 경고5, Console865.19s, 실제 exit1 | `release-full-verified.xml/log/result.json` |
| 저장 호환성 보완 | 40 passed, 8.99s, exit0 | `portability-compat.xml/log` |
| 마지막 prefix 경계/기존 Script 검사 | 23 passed, 1.64s, exit0 | `portability-compat-final.xml/log` |
| 최종 전체 실행 | **2,131 passed / 실패0·오류0·skip0**, 경고5, Console864.77s, 실제 exit0 | `release-full-final.xml/log/result.json` |

첫 전체 실행은 직접 Source/Device Editor의 추가 보호 결함을 재현한 뒤, 최종 수정 소스 전체로 다시 검사하기 위해 SIGINT로 종료했다. 이를 성공한 전체 회귀로 보고하지 않는다. 그때 발견한 test failure를 숨긴 것이 아니며 당시 종료 시점 실패0/완료하지 않은 나머지를 구분한다.

이어진 첫 전체 완료에서는 기존 `test_load_apply_and_prepare_identity_do_not_start_or_overwrite_input`과 `test_training_json_save_preserves_official_fields_and_source_config`가 실패했다. `/no/worker`처럼 설치 prefix를 알 수 없는 Backend를 `/` 전체로 해석해 정상 Script/JSON 저장까지 막은 회귀였다. 설치 prefix 식별 범위만 고치고, 원 실행 파일/알려진 설치/Workspace 보호와 기존 시험의 assertion을 유지했다. 2,117개 기준 testcase는 이 실패 실행에도 전부 있었고 신규14개였다. 실패 실행과 최종 재실행, 서로 겹치는 집중 수치는 합산하지 않는다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash /tmp/real2sim-phase2b-20261115-nragn39y/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short \
  --basetemp=/tmp/real2sim-phase2b-20261115-nragn39y/release-full-final-temp \
  --junitxml=/tmp/real2sim-phase2b-20261115-nragn39y/release-full-final.xml
```

최종 JUnit의 `(classname,name)` Counter로 **기준2,117개 누락0·신규14개**를 확인했다. 최종2,131개 모두 성공이고 error/skipped/xfail로 우회하지 않았다. Console864.77s / JUnit864.727s / wrapper867.568s, 실제 exit0이다. 기존 테스트 파일 변경·삭제·rename0이며 신규14개는 Builder6개 + Workbench8개다. 경고5개는 기존 record_property/xunit2 한 건과 torchvision 영상 API deprecation 네 건이다.

변경/신규 Python **12개** bytecode 없는 compile, 기존 공개 Signature **10개 제품 파일** 불변, 관련 Backend16개·Qt7개 모듈 import, shell syntax와 `git diff --check`를 확인했다. Import probe는 모델/엔진/장치를 생성하지 않았다. 최종 실행 시작 때 동결한 **384개 Python 소스/시험 SHA**가 종료 뒤에도 같았다. 기존23개 primary testcase 실행 매핑은 `audit-matrix.json`, 최종 Counter는 `regression-comparison.json`에 있다. 이후 문서만 마감했고 제품/시험 코드를 다시 수정하지 않았다.

## 8. 사용자 원본 파일 보존 결과

기준 ledger는 `workbench_runs/{curation,policy,source,evaluation,annotation,capture,scenes,object_assets,dataset,datagen,runtime,calibration,scripts}` **19,612개**의 전체 경로/크기/SHA다. Scene/Input/Calibration/Robot Base/Wrist Mount/Candidate/Cache/Asset/Export/Dataset/Checkpoint를 포함한다. **시작/종료19,612개 파일의 SHA·크기·전체 경로 집합 변경0·누락0·신규0**을 확인했다(`preservation-after.json`).

별도로 시작 tracked499개와 기존 untracked28개를 byte 백업했고, 허용된 이번13개 수정 외 시작 파일의 변경/삭제0을 확인했다. 기존 untracked28개와 이전 Phase의 테스트/보고서를 보존했다. 조사한 Camera/LeRobot SDK 소스16개는 이전 SHA와 최종 SHA가 같았다. HEAD/브랜치/Index는 시작과 같으며 Index diff SHA는 빈 diff의 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`다. Reset/Clean/Checkout/Stash·Commit/Push/Merge를 하지 않았다. 전체 SDK/Conda/모델 Cache/홈 디스크 전수 대조라고 확대하지 않는다. 새 합성 Project/Capture/Native/Dataset/Checkpoint는 이번 `/tmp` 아래에만 생성했다. 원본을 새 이름으로 옮기거나 삭제/마이그레이션하지 않았다.

## 9. 새로 발견한 결함과 수정 결과

| 항목 | 재현된 원인 / 최소 수정 | 검증 |
|---|---|---|
| NEW-01, High | Stage10 fixed World NPZ에는 raw-relative가 없는데, accepted fit의 helper는 raw/render_only만 의존성을 갱신. 명시 fixed World marker와 해당 Camera bookkeeping 갱신만 추가 | 실제 Solver rank6/6 채택→save→cloud_inputs 통과, source/Current/World NPZ SHA 불변; unknown Legacy 거부 |
| NEW-02, High | 직접 Joint·수치·렌더 Caller가 기존 Candidate 사용 journal을 우회해 소비 Holdout을 fresh로 재승인 | 기존 ledger의 소비 경계 보완. veto/report-only/metric 모두 재사용 거부, fresh 고정 Scene 감사는 보존. 반복 report는 독립 false |
| RISK-001에서 확인, Medium | Launcher/UI가 한 계정에 결합, 환경변수 미사용·다른 계정 저장 보호 누락·직접 Source/Device Editor의 Backend 정보 누락 | 명시 기존 설정/CLI·소유 BackendJob/공통 prefix 검사. 재배치·오류·symlink·직접 Qt 거부 통과 |
| NEW-03, Medium, **미수정 Backlog** | R03 `_monitor`는 이미 terminal인 record의 process exit code를 보존하지 않는다. 합성 completed record 뒤 실제 Python exit7을 주면 read_status는 completed 유지 | `postcommit-exit-probe.json/log`. Task/산출물 commit 뒤의 비정상 종료 진단 공백이며 정상 Workflow C의4 Worker는 종료 확인. 아래 제한·실험 절차에서 구분 |

원본 손상·Calibration 오인·데이터 누출·실행 차단과 직접 관련된 부분만 수정했다. NEW-03의 재현은 최소 terminal fixture와 실제 종료 프로세스이며 실제 Task가 거짓 성공했다는 재현은 아니다. 이미 commit된 산출물의 성공과 Interpreter 종료 실패를 분리해 기록하고 UI가 소비하는 설계가 필요하다. 여기서 commit된 Dataset을 삭제하거나 Worker를 자동 재실행하지 않는다. 생명주기/최종 상태 계약까지 확장하는 변경은 이번23개 안정화와 별도 Backlog로 남긴다. 미수정 사실을 숨기거나 정상 R03 네 실행으로 이 경우까지 해결됐다고 하지 않는다.

Phase2B 시작 대비 변경 목록:

- 실행/제품: `run_workbench_ui.sh`; Builder의 `calibration/{geometry,hybrid,joint}.py`, `observations.py`, `reconstruction.py`, `reconstruction_stages.py`; Workbench의 `ui/{paths,pipeline_settings,recipe_editor,training_json}.py`.
- 기존 문서: `README.md`, `real2sim_builder/SCENE_RULES.md`.
- 신규: `real2sim_builder/tests/test_final_audit_contracts.py`, `robot_learning_workbench/tests/test_runtime_portability.py`, 이 보고서.

Phase2B 시작 대비 **16개 = 기존13개 수정 + 신규3개**, 삭제0이다. 제품/Launcher11개, 기존 문서2개, 신규 시험2개·이 보고서1개다. 이전 Phase의 미커밋 변경과 구분한다. 기존 테스트 삭제/변경/rename·기대값 완화0이며, 전후 SHA·공개 Signature는 `change-inventory.json`, `final-verification.json`에 보존했다. Workflow A/B/C 뒤 추가 제품 수정은 Qt 경로 보호뿐이며 해당 통합의 수치/런타임/Writer/Trainer/엔진 소스는 같았다(`runtime-core-code-preservation.json`). AI·학습을 반복하지 않았다.

## 10. 미실행 GPU/Isaac/실물 검증

실제 DA3/SAM/FLUX/PDA/Bria/SBERT/CPD의 새 추론·온라인 Codex/VLM·장시간 GPU 학습·AppLauncher/Kit/RTX/PhysX·실물 로봇/그리퍼·새 사용자 사진/센서 촬영은 실행하지 않았다. 패키지/모델 설치·다운로드·인증 조회도 없다. 실제 CPU ACT2 updates와3 Step MuJoCo 평가, 회귀의 작은 CPU 계산/Qt/Native parser/Blender는 위 미실행과 별도로 보고한다.

## 11. 잔여 위험 및 제한사항

1. Full Rank/무잡음 합성 오차는 전역 유일해·실물 Metric 정확도가 아니다. 실제 Side/Wrist Calibration/Mount/FK·Robot World·독립 q/사진 검증이 필요하다.
2. 현재 SDK 조합에 대한 검증이다. 타 계정/타 PC 새 설치, 다른 USD/Lens/LeRobot API·CUDA/드라이버 조합은 미검증이다. 기존 optional Runtime·FLUX 제거 품질/Provider availability는 별도 진단 대상이다.
3. Native USD 지원 topology·Preview/PBR·신규 관절/추가 collision decomposition 등의 기존 지원 한계를 회귀 통과로 해결했다고 하지 않는다. 새 실제 Scene은 Stage별 NEEDS_RUNTIME/NEEDS_REVIEW/NEEDS_MORE_DATA에서 멈출 수 있다.
4. 구형 불완전 cloud/미기록 Source Parameters/불명확 Resume lineage는 근거를 발명하지 않고 거부한다. 사용 ledger가 없던 과거 자료의 독립성은 UNKNOWN이다.
5. Cancel은 기존 checkpoint 경계이며 하나의 blocking IO/외부 SDK 호출 내부의 무조건 즉시 종료를 보장하지 않는다. 부분 staging은 보존·비노출이며 자동 성공 복구하지 않는다.
6. 전체 회귀의 일부 fixture는 이 호스트의 보존된 과거 evidence/SDK에 의존한다. 깨끗한 설치의 재현성/대량 자료 성능·오랜 실행 안정성은 이번 감사로 인증하지 않는다.
7. NEW-03: R03의 completed 표시는 이미 게시된 작업 결과이지 모든 Interpreter shutdown의 exit0 증거가 아니다. 실제 CPU 네 Worker/두 Trainer 종료는 확인했지만 post-commit crash의 지속 exit metadata/UI 표시는 미완료다. 첫 통제 실험은 완료 표시와 별도로 소유 PID/종료·Artifact/Writer closure를 확인해야 한다. 실제 Isaac/실물 Worker의 종료 정확성까지 이번에 인증하지 않는다.

## 12. 최종 Go/No-Go 판정

**COMPLETED / 제한된 GO.** 알려진23개 경계·새 High2개의 수정 및 최종 회귀/보존을 확인했다. Medium 종료 진단 Backlog와 실제 검증 공백은 아래 판단에서 제외해 숨기지 않는다.

| 판정 | 상태 | 의미 |
|---|---|---|
| CODE_STABILIZATION_COMPLETE | **TRUE — 요청 안정화 범위** | 알려진23개·새 High2개 해결/검증, 전체2,131개 exit0·원본 보존. Medium1개는 명시 Backlog |
| READY_FOR_CONTROLLED_REAL_SCENE_TEST | **TRUE — 통제된 진단에 한정** | 새 Workspace/Candidate, Stage별 예산/Stop·PID/Artifact 확인. 전체 Scene 완성·무인 GPU/실물 운용 승인은 아님 |
| REAL_WORLD_VALIDATED | **FALSE / NOT_TESTED** | 새 실사진·독립 Calibration·Isaac/실물·작업 품질 결과 없음 |

## 13. 실제 Scene 첫 실험 순서와 관측 지표

1. **동결/분리:** 사용자 원본 SHA·Scene/Asset/Calibration/URDF/Mapping/Capture identity와 Runtime/가중치 경로·Revision을 읽기 전용으로 기록한다. 새 진단 Workspace/Candidate와 명시 예산을 만든다. 기존 Current/발행 Package를 자동 대체하지 않는다. Memo/Model Reference/Photo/Side/Wrist 역할과 한 배치를 확인한다.
2. **Runtime/API 선점검:** 현재 설치의 import/Signature·로컬 Snapshot 존재·idle VRAM/RAM을 확인한다. 인증값은 기록하지 않는다. 모델 재다운로드/다른 모델 fallback 없이 누락을 보고하고 해당 Stage에서 멈춘다.
3. **소형 Stage별 진단:** 별도 지시 범위에서 1 Photo/336부터 기존 Mixed DA3 정책을 실행한다. 모델은 하나씩 종료 후 다음으로 간다. depth/conf/K/E·finite·frame/pixel affine·scale provenance, 단계 시간·GPU allocated/reserved/관측 Peak·RAM·오류/자식 종료를 기록한다. R03 완료 표시만으로 종료를 추정하지 말고 소유 PID/종료 및 Artifact/Writer closure를 별도로 확인한다. OOM이면 범위를 늘리지 않는다.
4. **기하/제작 경계:** Support/World·Instance ID/Mask·실측 anchor를 검사한다. 독립 Robot World 등록 없이 Support를 Robot Base로 간주하지 않는다. FLUX/생성 품질 실패를 합성/후처리로 숨기지 않는다. Stage7은 새 Asset Version, Stage8은 실제 관측/가림·대칭·보호 scale·후보 오차를 기록한다. 실제 Runtime이 검증되지 않은 구간은 완료로 표시하지 않는다.
5. **정합/선택:** fitting=train과 반복 validation의 Capture ID/그룹/SHA·measured q를 실행 전에 정한다. Side/Wrist 서로 다른 K와 공유 Mount/FK를 유지한다. train 잔차와 rank/condition/group 회귀·부족 관측을 함께 보고하고 자동 채택 Full Rank gate·Current 보호를 지킨다. validation을 본 모든 선택/검토는 사용 이력에 남긴다.
6. **최종 Test 사전 분리:** 최종 Scene/Asset·K/Pose·Robot Base/Mount·URDF/Mapping·설정/Script SHA와 train/선택 ID·기존 ledger SHA를 고정한다. 그 뒤 새 Side/Wrist의 동기화된 RGB·실제 q·단위·시각/세션을 **오차를 보기 전에** 별도 Test 목록으로 동결한다. 인접 frame/동일 이미지/이미 선택에 쓴 Pair는 제외한다. 획득/하드웨어 실행은 별도 사용자 지시 범위다.
7. **고정 Scene 단회 평가:** 기존 `observation_scene`/공유 FK/Renderer와 metric 함수로 같은 measured q의 RGB·landmark·mask 오차를 카메라/자세별 측정한다. 이 경로에서 fit/refit/Codex 모델링/Best 선택을 호출하지 않는다. 필요 시 기존 별도 진단 Project에서 동결 Scene과 새 입력만 연결한다. Scene/Asset SHA 전후 일치, Side/Wrist 각각 RMSE/MAE/IoU/중심·경계 오차/coverage·q 다양성, 실측 단위와 mapping/time 오차를 보고한다. 허용 기준/출처는 결과를 보기 전에 정하며 관측 후 완화하지 않는다.
8. **판정과 소진:** 데이터/관측·Metric uncertainty 조건이 부족하면 NOT_VERIFIED/NEEDS_MORE_DATA다. 실패 Test를 수정에 사용했다면 그 ID는 소진된 Validation으로 남기고 새 Test를 확보한다. 수동/영상 기준 통과와 독립 카메라 정확도·중력/마찰·grasp/task 성공은 각각 따로 검증한다. Review Package·Simulation 준비를 실물 정책 성공으로 승격하지 않는다.

재검토 자료: `baseline-code.json`, `before/`, `baseline-protected.json`, `environment-architecture-inventory.json`, `imports.json`, `audit-matrix.json`, `standards/cloud.xml/log`, `spec/*probe.json`, RED/GREEN JUnit·로그, `workflows-ab/result.json`, `workflow-c/result.json`, 공식 Trainer/R03 기록, `postcommit-exit-probe.json/log`, `process-cleanup.json`, `runtime-core-code-preservation.json`, `tested-files.json`, 최종 `release-full-final.xml/log/result.json`, `regression-comparison.json`, `change-inventory.json`, `preservation-after.json`, `final-verification.json`.
