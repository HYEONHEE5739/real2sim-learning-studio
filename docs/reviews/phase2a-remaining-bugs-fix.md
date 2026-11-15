# Phase 2A — 잔여 14개 결함 수정 및 회귀 검증

2026-11-15. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `97c029e195ab8587603fb3f240f2c1a6c0f91f52`에서 시작했다. **COMPLETED — BUG-008–021 전체14개 수정, 최종 전체2,117 passed / 실패0·오류0·skip0, 실제 exit0.** 기존 Phase1D2,024개 testcase 누락0·신규93개이며 보호 파일19,612개 변경·누락·신규0을 확인했다.

## 1. Executive Summary

Phase1D를 취소하거나 미완료 상태로 닫지 않았다. 실제 CPU Tiny ACT Scratch/Resume와 최종 전체 **2,024 passed / 실패0·오류0·skip0, exit0**, 원본 보존을 확인하고 해당 상태를 Phase2A 기준으로 동결했다. 기준 원시 JUnit은 `/tmp/real2sim-phase1d-20261115-534a7mak/release-full-verified.xml`이다.

BUG-008–021의 14개 수정과 신규 교차 시험 **93 passed / 실패0·오류0·skip0, exit0**, 22.49초를 확인했다. 그룹 A 관련 전체1,320개, B 관련 전체964개, C Workbench/이전 그룹1,227개와 추가 경계54개, D 집중70개가 통과했다. 서로 겹치는 시험이므로 합산하지 않는다. 최종 세 패키지 전체 **2,117 passed**, 기존 경고5개, Console890.03초 / JUnit889.988초 / wrapper892.831초, 실제 exit0이다. testcase `(classname,name)` Counter로 기존2,024개 보존과 신규93개를 대조했다.

기존 제품15개 파일을 수정했고 신규 제품 모듈·Framework·Manager·Registry·Dependency·CLI를 추가하지 않았다. 신규 시험13개 파일과 이 보고서만 추가했다. 이전 Phase의 기존 시험과 보고서는 수정하지 않았다. 사용자 자료를 수정하거나 Commit/Push/Merge하지 않는다.

원시 자료는 저장소 밖 `/tmp/real2sim-phase2a-20261115-55ekumkx/`에 있다. 제품·시험은 이 임시 진단 경로에 의존하지 않는다. 임시 폴더가 삭제되면 로그를 다시 열 수 없다는 보존 한계가 있다.

## 2. Bug Resolution Matrix

아래 GREEN은 최종 소스의 신규93개 교차 검사다. 전체 완료 여부는 §7을 따른다.

| BUG | 기존 원인 | 최소 수정 / 실제 Caller | 변경 제품 | 재현 시험 파일 / GREEN | 상태 |
|---|---|---|---|---|---|
| 008 | control.json read 뒤 새 Stop이 replace되면 옛 소비자가 새 파일을 unlink | Project checkpoint가 고유 파일로 atomic rename하여 소유권 확보 후 자기 claim만 읽고 삭제. Pause loop도 같은 경계 사용 | `project.py` | `test_reconstruction_control_race.py`; 정상/pause interleaving, Lock·read-only·반복 제어 | GREEN |
| 009 | 닫힌 부분 LeRobot Metadata를 Discovery/Direct Reader가 완료 Dataset으로 해석 | `.staging`은 목록·직접 읽기에서 차단. 새 변환은 게시 상태를 기록하고 rename 성공 뒤에만 complete. 실패 자료는 보존 | `data/lerobot.py`, `data/curation.py` | `test_dataset_publication_visibility.py`; 첫 Episode 후 실패, 진행 중 목록, rename/intent 실패, Legacy 정상 읽기 | GREEN |
| 010 | Concave n-gon에 첫 vertex fan을 적용하여 외부 면·반전 삼각형 생성 | 원 corner index로 planar concave ear clipping. Convex fan·UV/material subset·winding 유지. 지원하지 않는 concave non-planar/self-intersection 명시 거부 | `object_assets.py` | `test_asset_semantic_geometry.py`; L 면적/coverage·3시작점×2orientation·UV/재질·기존 cap/quad | GREEN |
| 011 | content digest에 실제 Instance가 소비하는 Pose/Visual/Collision/Material 의미 정보 누락 | 새 Manifest는 content SHA와 결합한 semantic SHA. 구형 Manifest는 임시 폴더에서 USDA Metadata 재도출·비교. 기존 content SHA/Version/Scene Manifest binding 유지 | `object_assets.py` | 같은 파일; 신규/Legacy Pose·type·color·entry 변조 거부, 실제 새 Instance/portable export | GREEN |
| 012 | Direct Joint Fit만 채택 후 Raw 기반 World cloud·Camera signature 재투영 누락 | scope/preserve 통과 후 기존 `hybrid.reproject_observations`를 재사용하고 Candidate.save. Solver 및 각 Caller의 Rank 정책 유지 | `candidate.py` | `test_direct_fit_observation_refresh.py`; Camera/Mount/Base·반복 fit·미채택/보호값. 별도 실제 Solver2회 | GREEN |
| 013 | Stage10가 기존 cloud를 불완전 행으로 대체해 Hybrid의 units/frame/mask/split/group 계약 실패 | 기존 typed cloud 보존, 원 Photo의 픽셀 affine·Mask를 이용한 완전한 추정 World 관측을 추가. Source SHA·단위·split/group·dependency 명시 | `reconstruction_stages.py` | `test_stage_cloud_contract.py`; 실제 Stage10→등록→cloud_inputs, enabled/disabled/no sensor/metric 부족 | GREEN |
| 014 | Infill-only 최종 이미지가 Stage7에 빠지고 validity도 Upsample에만 적용 | 최종 선택 enhanced→infilled→observed focus. 동일 최종 파일/SHA로 validity와 Stage7 References 생성. Alpha·외부 Mask 격자 검사 | `reconstruction_stages.py` | `test_prepared_image_handoff.py`; 2×2×2 조합·빈 Alpha/격자 거부·원 RGB/Z/Mask SHA | GREEN |
| 015 | 공식 from_pretrained에 saved CUDA를 넘긴 뒤 뒤늦게 CPU.to | 요청 Device/지원 CUDA index를 검증하고 메모리의 cfg.device를 공식 Loader 전에 변경. 입력 Processor도 요청 장치 사용 | `learning/policy.py` | `test_policy_requested_device.py`; saved CUDA→CPU, 반대 요청, CUDA 부재 거부, 실제 Tiny ACT CPU load | GREEN |
| 016 | 진행 중 Step 충돌을 ValueError로 처리해 Worker 실패 | 다른 ID는 Rejected ACK, 같은 pending ID는 원 완료 ACK 대기. 첫 Step 유지. UI는 matching terminal ACK까지 Pending 유지 | `commands.py`, `ui/workflow.py` | `test_step_command_conflicts.py`; 실제 R03 파일/ACK·Cancel·vector 거부·실제 Qt Pending | GREEN |
| 017 | 초기 성공 steps0/epNone을 Policy 성공으로 게시하려 해 Native 불변식과 충돌 | 공통 evaluation_result가 initial_state_satisfied/success=false/policy_executed=false로 구분. 기존 Native failure Attempt로 기록하며 빈 Episode 생성 금지 | `tasks/evaluation.py`, `data/publication.py` | `test_evaluation_initial_state.py`; 양 엔진 episode_start/pre_step0/post_step·실제 Native publication/resume/성공률 | GREEN |
| 018 | Schema/runner의 gripper_approve가 R03 allowlist에 없음 | 검증한 Plan의 단발 모드·명시 command calibration/budget·full-motion OFF에서만 승인 envelope 전달. 실제 proposal/TTL/일회성 장치 검사는 기존 runner 책임 | `run.py` | `test_gripper_r03_approval.py`; R03→memory gripper, 다른 모드/잘못된 Proposal·Cancel 양순서·Timeout 거부 | GREEN |
| 019 | Convert/Merge 진입 때만 Cancel polling | 기존 materialize/merge/video/publish에 선택적 checkpoint 전달. Episode·각 Video frame·게시 직전 검사, finally로 공식 Writer 종료 후 Cancel ACK | `data/lerobot.py` | `test_conversion_cancel.py`; 첫 Episode/merge/video decode 취소·Writer close·Staging/원본·실패/성공 구분 | GREEN |
| 020 | source_functions가 live wrapper에만 있고 Isaac vector는 plan 누락 | 양 엔진 기존 execution_contract에 함수/Parameters 구성을 옮기고 기존 vector caller에서 plan 전달. Native continuation 검증 재사용 | `engines/{isaac,mujoco}/source.py` | `test_source_function_contract.py`; 실제 Metadata·Append drift 거부/동일 허용, 실제 MuJoCo/명시 Fake Isaac Vector 배열 | GREEN |
| 021 | lift/movement가 active_objects[0]을 선택 | 기존 task_object_ids를 재사용. 단일 Task 대상만 계산하고 0개/복수/미기록은 명시 상태와 null. Quality Hint만 변경 | `data/quality.py` | `test_quality_target_identity.py`; Distractor/순서 교체·복수/누락·Legacy 단일 및 원본 SHA | GREEN |

### 주요 의미와 호환성

- **Stop:** 원자적 claim은 명령 소비 시점의 파일 소유권을 보장한다. 기존 한 슬롯의 최신 명령 교체 의미를 새 Queue로 바꾸지 않는다. Worker가 읽은 뒤 도착한 새 명령을 지우지 않으며 다음 checkpoint에서 처리할 수 있다. Project Lock·소유 프로세스 종료 계약은 그대로다.
- **Fit:** Stage10/Numeric의 Full Rank 자동 채택 Gate는 유지했다. Direct Candidate/Hybrid가 기존처럼 Rank 부족의 미검증 진단 초안을 저장·비교하는 정책을 전역 veto로 바꾸지 않았다. 수치 개선·signature 갱신을 독립 Calibration이나 물리 인증으로 승격하지 않는다. 공유 Solver·광학 수학은 수정하지 않았다.
- **실제 BUG-012 수치:** 별도 합성 Side 관측에서 실제 SciPy Solver2회를 실행했다. Rank6/6, RMSE2.630541→1.093e-13px 및 1.284570→6.112e-14px, raw-derived World 오차0이었다. 각 fit 중 원 NPZ/Current/Evidence/Object는 불변이다. 두 합성 진실 Camera를 설정하기 위한 fit 사이의 landmark 변경은 기록했으며 사용자 관측을 변경한 것이 아니다. Renderer/AI/하드웨어는 이 probe에서 실행하지 않았다.
- **Asset:** 기존 10개 Library 버전의 읽기 전용 검증을 실제 수행했다. 초기 planarity 검사와 zero-area 거부는 기존 컵과 충돌하여 수정했다. 순수 convex non-planar quad와 rank<2 cap은 기존 fan을 유지하고, planar concave만 올바르게 분할한다. 원 USDA·Texture·Collision은 수정하지 않는다. 구형 Manifest를 재저장하거나 기존 content SHA를 교체하지 않는다.
- **Stage10:** 새 행은 기존 DA3 추정 Photo point와 명시 World 등록에서 도출한 추정 근거다. Sensor의 Metric Depth를 생성하지 않았다. 새 point 파일은 fixed World 근거이며 raw depth residual을 지원한다고 표시하지 않는다. 원 cloud·source image·Mask·단위·split/group과 실제 consumer 검사를 유지한다. 등록 및 numerical/render 경계를 대체한 시험을 실제 센서/기하 정확도 검증으로 보고하지 않는다.
- **Stage6:** 초기에 외부 RGB/Mask를 필수로 요구하여 기존 NPZ-only Crop 호출2건을 깨뜨렸다. NPZ 자체 격자는 항상 검사하고 별도 참조는 제공된 경우 검사하도록 복구했다. 기존 시험을 삭제하거나 기대값을 낮추지 않았다. 생성 RGB에는 원 Depth를 새 추정값인 것처럼 붙이지 않는다.
- **Dataset:** 새 `workbench-publication.json`은 선택적 게시 상태이며 Native/공식 LeRobot payload schema를 바꾸지 않는다. 구형·외부의 정상 공식 Dataset은 기존 Metadata로 읽는다. 실패 Staging·미완료 marker는 이름 변경 뒤에도 Reader에서 성공으로 간주하지 않는다. 자동 복구·삭제·성공 승격은 없다. 이미 닫힌 파일의 게시 직전 Cancel도 final Dataset을 만들지 않는다.
- **Device:** 공식 Loader/Processor를 재구현하지 않았다. 저장 config/weights는 읽기 전용이다. 입력 Processor와 Policy가 요청 Device를 사용하고 공식 Postprocessor의 CPU 반환 의미는 유지한다. CUDA 비가시 별도 Child에서 소형 무작위 초기 ACT6,086 Parameter를 CPU로 로딩했다(`cpu-policy-probe.json`, 실제 exit0). CUDA availability monkeypatch 없이 available=false/initialized=false, 원 파일 SHA 불변과 Forward/Training0회를 확인했다. 이 로딩은 학습/추론 성공이나 CUDA 메모리 측정을 뜻하지 않는다.
- **Source:** 함수 선언이 없는 Legacy Source에는 빈 source_functions 필드를 새로 강제하지 않는다. 새 선언의 Parameters가 다르면 기존 Native continuation 검사가 거부한다. 과거 Recorded 실행에 해당 Parameters가 기록되지 않았다면 같다고 추정해 Append하지 않는다. 구형 Dataset의 일반 읽기는 유지한다.
- **Zero-step:** 초기 Task 상태가 만족돼도 실행한 Policy가 없으므로 `success=false`, category `initial_state_satisfied`, `initial_state_success=true`, `policy_executed=false`다. Native의 기존 failure Attempt에 사유를 보존하고 별도 집계를 추가했다. 성공률의 기존 분모는 모든 기록 Attempt이므로 초기 미수행도 분모에 들어가며 Policy 성공 분자에는 들어가지 않는다. 새 Native outcome enum이나 가짜 Action Row는 없다.
- **Gripper:** 실제 Motor/Serial/Cameras를 연결하지 않았다. Memory SDK의 단일 goal write만 성공 시험에서1회 관측했고, 잘못된 승인·취소·시간 초과는0회다. 이 결과를 실제 물리 명령 성공으로 해석하지 않는다. 승인 전달은 장치 Capability/정확한 Calibration/Proposal·TTL 검증을 대신하지 않으며 full-axis 권한을 추가하지 않는다.
- **Curation:** Task 대상이 여러 개이면 단일 scalar Lift의 의미를 임의 선택하지 않고 `MULTIPLE_TASK_OBJECTS`와 null로 둔다. 대상 없음·미기록은 각각 `NO_TASK_OBJECT`/`NOT_RECORDED`다. 단일 대상은 `target_object_id`와 `AVAILABLE`을 기록한다. 원 Episode success/include/exclude/split은 바꾸지 않는다.

## 3. Architecture Impact

기존 `Project/Candidate` 명령·Lock·저장, Stage Runner/Artifact, canonical USD Converter/Library, R03 Worker/ACK, 양 엔진 Source, 공식 LeRobot Writer/Loader, Native Episode/Attempt/Resume 계약을 유지했다. 모듈 책임을 다른 시스템으로 옮기거나 엔진 Step Loop를 통합하지 않았다.

신규 제품 helper는 기존 파일 안의 atomic control 소비, polygon corner 분할, Manifest semantic digest, 게시 상태 판정이다. 각각 기존 경계에서만 호출한다. 신규 예외는 R03 Cancel과 일반 IO 실패를 구분하기 위한 내부 `_ConversionCancelled`다. Cancel은 Writer finally 종료 이후 ACK하며 일반 예외를 성공/취소로 삼키지 않는다.

기존 API 필수 인자는 그대로다. `publish/merge/materialize/_video_window`에는 선택적 `checkpoint=None`, 내부 `_poll_commands`에는 선택적 `plan=None`만 추가했다. CLI 변경·새 Dependency·공개 Dataset/Scene schema 교체는 없다. Asset Manifest의 semantic SHA, Stage6 prepared_image와 Dataset 게시 marker는 additive이며 Legacy 경로를 명시적으로 검증했다.

Phase1A Current/Calibration 보호, Phase1B 자동 Rank/선택 Layout·Capture Gate, Phase1C Camera K/native lens schema, Phase1D 공식 config seal·Dataset lineage는 보존했다. `contract-preservation.json`에 함수 AST·Signature 대조를 기록한다. Scene Validator·Native continuation·공식 checkpoint sealer·광학/Joint 수학·Robot 안전 함수는 이 Phase에서 수정하지 않았다.

## 4. Regression Evidence

| 검사 | 실제 결과 | 원시 근거 |
|---|---|---|
| A Stop/Step RED | 9 failed / 4 passed, 0.75s | `group-a-red-control-final.xml/log` |
| A Direct Fit RED | 4 failed / 2 passed, 1.15s | `bug012-red-agent.xml/log` |
| A Cancel/UI RED | 4 failed / 1 passed, 3.19s | `cancel-ui-red.xml/log` |
| A 신규 GREEN | 24 passed, exit0 | `group-a-green-verified.xml/log/result.json` |
| A 관련 전체 | 1,320 passed, 경고3, 720.30s, exit0 | `group-a-regression.xml/log/result.json` |
| B Asset RED | 6 failed / 6 passed, 1.68s | `assets-red-verified.xml/log` |
| B Stage RED | 5 failed / 12 passed, 3.11s | `stage-red-verified.xml/log` |
| B 기존 호환성 첫 회귀 | 2 failed / 960 passed, 357.67s, exit1 | `group-b-regression.xml/log/result.json` |
| B 호환성 수정 후 전체 | 964 passed, 경고1, 355.72s, exit0 | `group-b-regression-verified.xml/log/result.json` |
| C 게시/Device RED | 5 failed / 2 passed, 8.15s | `data-device-red.xml/log` |
| C Source RED | 3 failed, 1.96s | `source-functions-red-verified.xml/log` |
| C 추가 게시 실패 RED | rename 후 표시1 failed / intent Writer 종료1 failed | `pub-renamed-red`, `pub-intent-red` |
| C 신규 첫 GREEN | 10 passed, 7.15s, exit0 | `group-c-green.xml/log` |
| C 후속 전체 경계 | 54 passed, 경고3, 45.78s, exit0 | `group-c-boundary-verified.xml/log` |
| C Workbench/앞선 그룹 | 1,227 passed, 경고4, 536.33s, exit0 | `group-c-regression.xml/log/result.json` |
| D 초기상태/품질 RED | 9 failed / 3 passed, 2.13s | `eval-quality-red-verified.xml/log` |
| D Gripper RED | 1 failed / 7 passed, 1.60s | `gripper-red.xml/log` |
| D 집중/인접 회귀 | 70 passed, 22.40s, exit0 | `group-d-green.xml/log` |
| 최종 신규 교차 | 93 passed, 22.49s, exit0 | `all-bugs-crosscheck.xml/log/result.json` |
| 최종 세 패키지 전체 | **2,117 passed, 경고5, 890.03s, 실제 exit0** | `release-full-verified.xml/log/result.json` |
| Phase1D testcase Counter | **기존2,024개 누락0·신규93개, 삭제/rename/skip0** | `regression-comparison.json` |

첫 재현의 fixture 작성 오류와 후속 수정 기록도 보존했다. USD Vt int 배열, 별도 Pose 없는 Export fixture, 미완성 테스트 문법, Tiny rollout codec/contacts fixture를 바로잡은 뒤 원래 결함을 재현한 RED를 표에 사용했다. B 회귀의 실제 제품 호환성 실패는 fixture 오류와 구분한다. 초기 RED/Green/회귀 수치를 서로 더하지 않는다.

DA3/SAM/FLUX/PDA/Bria 등의 재구성 모델 Forward·고비용 GPU 학습·실제 Kit/PhysX·로봇/센서 E2E는 실행하지 않았다. 실제 합성 CPU MuJoCo·Native/LeRobot Writer/Parser·Qt/R03·USD 수학과, 명시 Fake Isaac physics/Codec/Policy IO·Remote Provider를 구분한다. 기존 전체 시험에 포함된 작은 CPU Policy 계산을 새 학습 검증이라고 보고하지 않는다.

## 5. Data Preservation / 변경 목록

작업 시작 전 실제 Working Tree499개 추적 파일·기존 미추적14개를 복사하고 HEAD/Index와 보호 root의 경로·크기·SHA를 기록했다. 보호 대상은 `workbench_runs/{scenes,capture,calibration,source,annotation,datagen,curation,dataset,policy,evaluation,object_assets,runtime,scripts}`이며 Scene/Input/Stage Cache·Capture·측정·Asset·Dataset·Policy/Checkpoint를 포함한다.

**최종 보호 대조: 시작/종료19,612개 파일의 경로·크기·SHA 변경0·누락0·신규0.** `preservation-after.json`이 근거다. 조사 범위 밖 모든 모델/SDK/홈 전체의 전수 불변을 주장하지 않는다. 기존 SDK 소스8개의 SHA는 시작과 동일하고 패키지 설치/업그레이드·다운로드를 하지 않았다. Git Index/HEAD/브랜치는 시작과 같고 Commit/Push/Merge/Reset/Clean/Checkout/Stash는 수행하지 않았다.

이번 Phase만의 제품 변경15개:

- Builder: `candidate.py`, `project.py`, `object_assets.py`, `reconstruction_stages.py`.
- Workbench: `commands.py`, `data/curation.py`, `data/lerobot.py`, `data/publication.py`, `data/quality.py`, `engines/isaac/source.py`, `engines/mujoco/source.py`, `learning/policy.py`, `run.py`, `tasks/evaluation.py`, `ui/workflow.py`.

신규 시험은 표의13개 파일이고 신규 문서는 이 파일이다. 기존 시험 수정·삭제0개, 신규 제품 모듈0개다. 정확한 전체 경로는 `change-inventory.json`에 있다. 이전 Phase의 미커밋 변경을 이번 수정 수에 합치지 않는다.

변경/신규 Python28개의 bytecode 없는 compile·Signature·새 skip/xfail 부재 및 `git diff --check`를 확인했다. 최종 전체 실행 시작 시 저장한 Python 소스 SHA와 종료 소스 SHA가 모두 같음을 확인했다. 실제 Backend14개 모듈 및 별도 Qt Interpreter의 workflow Import도 통과했으며 모델/Simulator/장치 생성자는 호출하지 않았다.

## 6. Remaining Risks

1. **RISK-001은 분석만 유지:** launcher/일부 UI의 특정 홈 설치·보호 경로 결합은 이식성 위험으로 남는다. 이번에 Runtime/Framework를 재설계하거나 설치 경로를 바꾸지 않았다. 다른 호스트 E2E는 미검증이다.
2. **RISK-002는 분석만 유지:** 반복 선택에 쓴 Holdout은 최종 독립 정확도 자료가 아니다. 기존 사용 ledger·보호 Gate를 유지했으며 새 미사용 Wrist/Side Pair의 물리/기하 정확도를 인증하지 않는다.
3. 실제 다중 사진/DA3·SAM·FLUX·PDA·Bria 추론, Codex 온라인 판단, Isaac Kit/PhysX·실물 로봇/그리퍼는 이번에 실행하지 않았다. Runtime·Metric Calibration·Wrist/Side·Task 정확도의 이전 미검증 범위는 남는다.
4. USD polygon 지원은 기존 convex fan과 planar simple concave 영역이다. holes·self-intersection·concave non-planar의 임의 보정이나 기존 Asset 재저장은 지원하지 않는다. Preview의 PBR 정확도 등 이전 한계도 그대로다.
5. Dataset 게시의 rename 뒤 marker 기록이 실패하면 final 경로가 있어도 미완료로 차단하며 명시 점검이 필요하다. 자동 재시도/복구로 완성시키지 않는다. Cancel 응답은 Episode/decoded frame/게시 checkpoint 단위이며 한 시스템 IO/decode 호출 내부를 강제 중단하는 새 Thread는 없다.
6. Source의 과거 미기록 Parameters, 초기 상태의 이미 만족된 Task, 복수 Curation Task 대상은 근거를 발명해 이전 정상 성공으로 맞추지 않는다. 각각 continuation 거부·미수행 Attempt·null 품질 상태를 유지한다.

## 7. Final Verdict

**COMPLETED — BUG-008–021 전체14개 해결. 남은 해당 BUG0개.** 기존 BUG-001–007/FIX-A/B의 수정·시험과 Phase1A–D의 미커밋 변경을 보존했다. 기존 시험 수정·삭제·rename·skip·xfail0, 신규93개 포함 전체2,117개 실제 exit0, 보호 파일19,612개 불변, HEAD/Index/브랜치 불변 및 `git diff --check` 통과를 확인했다.

최종 아키텍처 감사에서는 이번 명령 소유권/ACK·Writer 게시 상태·typed cloud·Asset semantic binding·Task Parameters의 기존 책임 경계를 검토하면 된다. 실제 사용자 E2E, 독립 Wrist/Side/Metric QA, Isaac/물리/실물 Task와 RISK-001/002는 §6의 별도 미검증/설계 위험으로 유지한다. 이 미검증을 회귀 통과로 승격하지 않았다.

최종 근거: `verification-summary.json`, `regression-comparison.json`, `preservation-after.json`, `contract-preservation.json`, `compile-check.json`, `change-inventory.json`, `tested-files.json`, `import-core.json`, `import-ui.json`, `cpu-policy-probe.json`, `legacy-asset-readonly.json`, `final-verification.log`. Source·Native·Safety·Solver AST와 기존 Signature를 대조했다. 원시 JUnit 및 실제 프로세스 종료 결과와 함께 재검토할 수 있다. Commit/Push/Merge하지 않았고 이번 수정도 미커밋 상태다.
