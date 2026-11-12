# Reconstruction 후속 통합 — Stage6 / Memo / Robot World

2026-11-13. `feat/simfoundry-style-reconstruction`, 시작 HEAD `23bcc2d0fd89d23e07e3c02cbadcf27b338b6720`. 직전 미커밋 19개(수정17·신규2) 위에서 작업했으며 시작 Index는 비어 있었다. 원본 패치와 19개 파일을 Git 제외 `workbench_runs/diagnostics/reconstruction_integration_followup/baseline/`에 보존했다. Reset/Clean/Stash/Merge/새 Worktree를 사용하지 않았다.

**구현·집중 검증과 새 Schema의 온라인 VLM 1회는 완료했다. 사용자 사진 Reconstruction, 실제 센서 정합 정확도, 실제 Mesh 제작·물리·Task 성공은 검증하지 않았다.** 기존 1,751개 전체 회귀 수치를 이번 변경의 검증으로 재사용하지 않는다.

## A. 직전 변경 19개의 실제 코드 대조

| 확인 대상 | 실제 경로와 결과 |
|---|---|
| Stage5 안전한 불확실성 | `instance_gate`: Identity/Box/Memo 충돌은 Object 검토. 숨은 형상·미측정 치수·Front만 안전하게 estimated 진행. 원 응답의 uncertain을 바꾸지 않음 |
| 원본/생성 Point | `decompose → pose_point_selection → prepare_objects → poses`: RGB/Z source map·low-confidence map과 원본 Camera XYZ/UV를 유지. 기본 original_only. 생성점의 별도 민감도 시험 없이 원본 관측으로 승격하지 않음 |
| FLUX 실패 | mask/outline/bbox의 제한 시도와 시도별 리뷰 Cache. negative/uncertain 제거 영상은 다음 RGB/Z로 승격하지 않음. 의존 순서 뒤 Object도 독립성 근거 없이 완료하지 않음 |
| Worker Cache | `automation.call`: Manifest/SHA/closure에 더해 response.json과 저장 data, real/mock execution을 대조. 다른 응답을 성공으로 재사용하지 않음 |
| 원본 보호 | 측정/Calibration/Asset 불변 계약 유지. 소유 Worker 그룹 종료는 기존 codex_cli.stop_child를 재사용. 실패 부분 파일은 실패 Artifact로 보존 |
| Stage10 연결 | 기존 `observations.register_views/register_sensor_views`에 persist=False로 연결. 부분 Scene은 진단 파일이며 승인 Scene으로 저장하지 않음 |

직전 보고서의 전수 raise/return 감사는 **당시 소스의 역사적 조사**다. 이번 변경 이후 행 번호·개수를 다시 전수 감사한 기록으로 해석하지 않는다.

## B. Stage6 생성물의 불확실성

`object_validity_schema/object_validity_gate`에 다음 Typed Assessment를 연결했다.

- 원래 validity/identity_preserved/other_objects_present/uncertain/reason 보존.
- observed_shape_preserved, foreground_valid, measurement_consistent.
- OBJECT_IDENTITY, FOREGROUND_MASK, OTHER_OBJECT_CONTAMINATION, HIDDEN_GEOMETRY, UNMEASURED_DIMENSIONS, TEXTURE_APPEARANCE, GENERATION_ARTIFACT.

validity=yes, Identity 보존, 혼입 없음, 관측 형상/Alpha/기존 실측에 문제가 없고 불확실성이 숨은 형상·미측정 치수에만 해당하면 `ESTIMATED_CONTINUE`다. uncertain=true는 그대로 남는다. 나머지는 Object ID·생성 이미지 SHA와 함께 OBJECT_REVIEW다. 이전 형식의 응답은 기존의 엄격한 uncertain=false 조건만 지원한다. 실제 CLI 응답은 새 Strict Schema를 요구한다.

기존 `check_valid` 옵션의 실행 범위를 유지했다. Upsample 이후 옵션 검사이며 infill-only에 새로운 VLM 호출을 몰래 추가하지 않았다. 이미 준비된 Object와 파일은 object_progress.json에 남기고, 보류 Object가 있는 전체 Stage를 성공으로 만들지 않는다. 생성 RGB의 depth_frame은 observed_original_only이며 새 이미지에 원본 Depth를 정합된 새 측정처럼 붙이지 않는다.

Guide는 `2026-11-13-integration-v5`다. 변경된 Guide SHA, 요청 Schema, 구현 SHA가 기존 Cache Identity에 반영된다. Workspace 설정은 덮어쓰지 않았다.

## C. Memo의 Shape / Equality 제약

자유로운 한국어/영어 해석은 Codex가 담당한다. Python은 전체 Memo를 정규식 파서로 다시 해석하지 않고 **응답에 명시된 국소 인용과 관계의 수학**을 검증한다.

`geometry.dimension_relations`는 기존 scalar measurement_claims에 추가한 계약이다.

| 관계 | 검증·유도 |
|---|---|
| cube | 정육면체 인용 + 한 변 측정 → x=y=z. box 형상 필요 |
| cylinder | 지름 또는 2×반지름 → x=y. 높이는 독립 z 근거 필요. wall도 독립 값 |
| axes | 가로/세로/높이 및 길이/폭/두께 → 명시 x/y/z. 길이가 있을 때 폭은 y; 단독 width는 x |
| equal_dimensions / same_product | 명시 관계·전체 멤버 ID/subject 인용·reference_object_id 필요. 이미 검증된 측정만 상속; visual estimate에서 measured를 유도하지 않음 |

모든 관계는 statement_quote/relation_quote, 멤버별 object_id/subject_quote bindings와 각 측정의 field/axis_quote/clause_quote/value_quote/value/unit를 기록한다. clause_quote에는 한 수치/단위만 있어야 한다. 전체 관계 문장의 수치도 빠짐없이 대응해야 하므로 다른 Object의 추가 치수를 숨겨 공유하지 못한다. 단위는 mm/cm/m이며 Decimal로 변환한다. 부분 치수는 null을 유지한다.

유일한 명칭과 실제 Object ID가 대응하지 않으면 측정으로 인정하지 않는다. 한국어 조사와 명칭 일부(예: 컵과 컵받침)를 구분한다. 미지원·근거 없는 해석은 estimated/unknown이며 숫자/단위/축/참조가 모순된 응답은 거부한다. 논리적 파생은 원문 Memo SHA·관계·검증된 축 값을 derivation에 보존한다. `semantics_verified=false`는 그대로다. 인용·숫자 검증이 자연어 의미·물리 측정 정확도의 독립 인증은 아니다.

집중 시험에서 실제 ID red_block/blue_block/green_block에 각각 24mm 정육면체, 컵의 지름8cm·높이10cm, 반지름, 길이/폭/두께, 명시 동일 제품의 근거 상속을 확인했다. 기존 measured/calibrated 치수와 충돌하면 geometry_specs가 거부한다. 별도 치수 입력 폼이나 자동 공유 Asset 판정은 추가하지 않았다.

## D. Stage10 Robot World / Side / Wrist

기존 수치 모듈을 호출하는 두 초기화 경로를 Stage10 내부에 연결했다. 새 Solver·Manager·독립 파이프라인은 없다.

### D1. 독립 3D 대응점

`sensor_registration.world_anchors`에는 다음 필드가 필요하다.

```yaml
sensor_registration:
  world_anchors:
    - id: REPLACE_WITH_ANCHOR_ID
      group_id: REPLACE_WITH_INDEPENDENT_GROUP
      split: train  # validation은 최적화에서 제외
      support_point: [0.0, 0.0, 0.0]  # 예시 자리표시자; 실제 Stage4 좌표로 교체
      robot_world_point_m: [0.0, 0.0, 0.0]  # 실제 독립 측정으로 교체
      source: measured
      evidence: [REPLACE_WITH_ACTUAL_EVIDENCE]
```

`resolve_stage_world → calibration.registration.align_points(estimate_scale=True)`로 비공선 Train 대응점 3개 이상에서 proper rotation, translation, scale을 구한다. scale을 rigid 4×4의 회전부에 넣지 않는다. Anchor ID/그룹/동일 3D 점의 Train–Holdout 누수를 차단하고 Holdout은 fit 이후에만 평가한다.

### D2. Metric Support + measured-q Wrist

별도 world_anchors가 없을 때 명시된 실제 작업판 전체 4코너와 실측 크기에서 scale 추정을 보존한다. **부분 점군의 외접 사각형은 이 입력을 대신하지 못한다.** 작업판 치수만으로 Base Pose를 만들지 않는다.

`resolve_sensor_world`는 원본 Photo XYZ/UV를 명시적인 임시 Support gauge로 전달하고 기존 `register_sensor_views(initialize_base=True)`를 호출한다. 이 안의 기존 Photo feature/PnP → archived URDF FK → wrist_from_motion을 사용한다. 최소4개 localized measured-q 자세와 기존 full-rank 조건이 필요하다. 공동 Mount 하나와 Support에서의 Base 변환을 추정한다. 새로운 per-q Mount나 Camera Pose를 생성해 오차를 숨기지 않는다.

기존 Robot Base가 calibrated/measured이면 그 World를 보존해 Support 변환을 합성한다. 고정된 World 기준이 없을 때만 실제 FK/Mount fit으로 위치를 구한 Base를 새 estimated World gauge로 삼는다. 이미 보호된 World Camera/Object가 있는데 Base가 미해결이면 임의 gauge로 바꾸지 않고 독립 World 대응을 요구한다. 보호 Mount/K/Mapping/q는 변경하지 않는다. 여러 Wrist fit의 Base가 다르면 하나를 임의 선택하지 않는다.

이 경로에서 Side는 독립적인 Base 근거가 아니다. Wrist 대응·운동이 부족하면 가능한 scale, 부분 Camera/Mount 진단 Scene과 구체적인 needs를 남기고 Robot World=UNRESOLVED로 중단한다. 부분 결과는 `support_sensor_initialization/` 또는 sensor_partial_scene.yaml이며 Candidate 승인으로 저장하지 않는다.

### D3. Geometry 합성 / 공동 정합 / 렌더 경계

- 공통 scale을 미측정 Mesh 크기, Object 위치, Reference Camera 위치 및 원본 Photo cloud XYZ에 일관되게 적용한다. Camera 회전, 처리 K와 pixel affine은 scale하지 않는다.
- 실측 Mesh가 비단위 scale 수정과 충돌하면 `METRIC_SCALE_REQUIRES_REFIT`로 corrected-point Stage8 재정합을 요구한다. 실측 Asset을 축소/확대해 덮어쓰지 않는다. Support Asset의 명시 Transform도 재검토한다. 자동 Stage8 역실행은 이번 구현 범위가 아니다.
- `register_views`는 명시 view_anchors 분기, `register_sensor_views`는 기존 고정 Side/공유 Wrist 경로를 유지한다. Side/Wrist는 DA3 Photo 입력으로 섞이지 않는다.
- reviewed landmark가 있으면 기존 `joint.fit_joint_scene`에 연결한다. Camera 역할은 관측 메타데이터로 구별하고 이름이 wrist인 고정 Side도 올바르게 취급한다. 기존 보호 변수와 Train/Holdout 분리를 유지한다.
- `sensor_registration.render_refinement.enabled=true`일 때만 기존 `hybrid.fit_scene/alignment_metrics`에 연결한다. 기본은 false이며 이번에는 실제 Simulator 렌더를 실행하지 않았다. 기존 Source 기반 Real/Sim Pair 경로도 유지했다.
- Stage11–14의 simulation_ready/stabilize/package_scene/simulator_integration 함수는 시작 HEAD와 AST가 같다. 승인·물리·Task 기준을 완화하지 않았다.

### D4. 지표와 검증 범위

| 지표 | 기록 / 이번 확인 |
|---|---|
| Metric scale / Base anchor fit | Train RMSE와 Holdout RMSE, Anchor SHA/ID/분리. 알려진 Synthetic Sim(3)의 scale2·R,t 복원 및 Holdout 오차 <1e-12m 조건 통과 |
| Side/Wrist reprojection | joint 결과의 Camera/Pose/Object별 before/after·holdout 그룹. 실제 CPU Synthetic landmark 최적화에서 Train/Holdout 개선 확인; 실사진 정확도 NOT_TESTED |
| 공유 Wrist Mount / Base | 기존 motion rank/rmse/scale/T_relative_base/T_link_camera. 합성 URDF/measured-q의 실제 FK·hand-eye 계산, Mount/Base <1e-6 matrix 오차 조건 통과. PnP/feature 입력은 Fake이므로 실제 영상 국소화 성공의 증거가 아님 |
| Object Pose | 기존 joint 변경 변수·보호 치수·그룹 회귀 검사. 독립 Object Pose 정확도 NOT_VERIFIED |
| Holdout RGB/Mask | 명시된 기존 렌더 경로만 지원. 이번 실제 RGB/Mask 렌더 비교 NOT_RUN |
| 물리/Task | NOT_TESTED. 낮은 영상 오차나 Stage 완료로 승인하지 않음 |

World Anchor의 관측 오차 모델/독립 실측이 없어 정확도 인증 threshold를 새로 만들지 않았다. 자동 출력은 estimated이며 calibrated/metric_accuracy_verified/physical_verified로 승격하지 않는다. 기존 full-rank/PNP/Hand-eye 기준을 느슨하게 바꾸지 않았다.

## E. 새 Schema 온라인 1회

기존 합성 컵 768×512, SHA `1d50eaa62aeb133d7d0ef4befc9e96ee20230ea29404c0b1d8952fbab1f5ffd6`를 사용했다. 기존 UI 선택 gpt-6.1-sol/high와 로그인 Home을 유지했다.

`stage_runtime.invoke('vlm') → authoring.run_codex_vlm → codex_cli.execute` 실제 경로로 **1회, 재시도0회**, 전체48.539초에 성공했다. turn.completed 및 정상 종료0을 확인했고 TIMEOUT은 없었다. CLI usage는 input11,251 / cached0 / output1,688 tokens다. 서버 내부 전송 재시도 횟수는 UNKNOWN이다.

mug_1의 Identity=IDENTIFIED, Box=ASSOCIATED, Memo=CONSISTENT, uncertainties=[HIDDEN_GEOMETRY, UNMEASURED_DIMENSIONS], 전체 uncertain=true를 실제로 반환했다. container의 dimensions_m는 모두 null, measurement_claims와 dimension_relations는 빈 배열이다. **실측 치수 해석의 온라인 정확도를 증명한 결과가 아니다.** 해당 관계의 숫자 계약은 Offline Fake/Synthetic 시험으로 구분한다.

Strict Schema·Box 범위·Instance ID·Stage5 gate·Manifest/SHA/Cache Identity를 검증했고, 실제 응답을 Stage7 parse/modeling_tasks에 재사용해 두 CPU 재생성의 Task SHA가 같음을 확인했다. Task 상태 WAITING_FOR_CODEX는 모델링 실행 대기다. Handoff의 measurement_count=1은 unknown 치수의 geometry spec 하나를 센 값이며 실제 측정값 개수가 아니다. 실제 치수는 0개다.

SAM/Depth Forward가 없으므로 Handoff의 Mask/Depth 파일은 NOT_RECORDED 표식과 빈 합성 참조다. 실제 관측이나 Mesh 제작에 사용하지 않았다. 추가 온라인 호출·Blender Mesh 제작은 0회다. 기존 실패/진단은 덮어쓰지 않았다.

## F. 집중 검증과 보존

마지막 집중 묶음 **175 passed / 실패0 / 오류0 / skipped0**, Console120.68초. 전체 pytest가 아니다. 증거: `release-focused.xml/log`. 중간 RED/GREEN 수치를 더해 성공 수를 부풀리지 않았다. 이전 Guide 버전 상수의 불일치와 fixture의 등록 누락도 실패 기록으로 보존하고 수정했다.

포함 범위: Stage6 hidden/identity/Alpha/오염·관측 provenance, 한국어 3색 정육면체·원통·axes·equality·오류 witness·보호 치수, Sim(3)/holdout leakage·unresolved metric scale, 실제 CPU joint/FK/shared mount, metadata 역할, 기존 Worker cache/Stop/timeout/descendant 종료, Stage1–14의 Runtime/Stop/재개, Native Review Package·승인 계약. 무거운 Worker는 Mock이다. 실제 probreg CPD/SAM/DA3/FLUX/PDA/Bria/Isaac/로봇 실행은 하지 않았다.

보호 ledger **18,517개 파일 SHA/크기 변경0·누락0·신규0**. Scene/Input/Capture/Calibration/Candidate/Cache/Export·공용 Asset·Workspace Runtime·이전 local_runtime_validation/직전 gate 진단을 포함한다. SDK·가중치 디스크 전체의 전수 SHA 대조는 아니다. 기존 DA3 loader·SAM3.1 Adapter·공통 CLI·Scene/Candidate·hybrid 및 Stage11–14 등 11개 보호 계약을 HEAD와 대조했다. 변경 Python17개를 bytecode 생성 없이 compile했고 git diff --check를 통과했다. 기존 환경 설치/업그레이드·모델 다운로드·사용자 E2E는 하지 않았다.

## G. 로컬 Runtime 재연결

개인 설치 경로·가중치·인증은 Commit하지 않는다. 새 Checkout에서는 [예시 YAML](../real2sim_builder/config/simfoundry-reconstruction.example.yaml)의 `/EXISTING/...`만 실제 보유 Interpreter/소스/가중치 경로로 교체해 Git 제외 `workbench_runs/runtime/reconstruction.yaml`에 연결한다. 기존 파일이 있으면 별도 백업하고 필요한 키만 병합한다. 샘플 파일 전체로 덮어쓰지 않는다. Project/명시 설정이 Workspace보다 우선한다.

1. da3.python/source/model은 기존 Nested b2359bdf726fb44ef62acca04d629dcf158053e7 Snapshot과 Mixed loader 그대로 사용한다.
2. sam3는 기존 sam31/MultiPlex checkpoint, image_edit는 기존 ComfyUI/GGUF·인코더·VAE/Workflow, prior_depth는 패치 소스·vitl+vitb v1.0, rembg는 승인된 Bria ONNX를 연결한다. 이 문서가 재다운로드 지시를 뜻하지 않는다.
3. pose는 기존 CPU Open3D/probreg Interpreter와 front 렌더용 원본 SimFoundry source를 연결한다. physics/simulator는 기존 Builder/MuJoCo/Isaac USD source와 bin Bootstrap, Blender는 실제 기존 executable을 연결한다.
4. VLM은 provider:codex/timeout_s만 사용한다. 기존 UI의 로그인·모델·Thinking Effort를 선택하고, 계정 Home/키를 YAML에 쓰거나 복사하지 않는다. 구형 Gemini vlm 블록은 기존 전환 문서대로 명시 이전한다.
5. 각 Interpreter에서 `python -B -m pip check`와 실제 Worker Import/Signature를 먼저 확인한다. 경로 확인만으로 모델 Forward·E2E·Isaac 성공을 선언하지 않는다. [기존 Runtime 문서](local-runtime-validation.md)와 [설치 조사](simfoundry-runtime-setup.md)는 당시 실행/미검증 범위를 함께 읽는다.
6. 실제 anchors/capture_layouts·reviewed landmarks·measured-q/모델·Mapping SHA를 기존 Reconstruction 설정으로 제공한다. 예시의 0 좌표·ID를 실제 측정으로 취급하지 않는다. 센서 부족 시 needs를 먼저 해결한다.

이번에 실제 Workspace YAML·UI 선택·계정 설정은 변경하지 않았다.

## H. 체크포인트와 남은 Blocker

이번 Commit은 직전 19개와 이번 관련 소스·테스트·문서만 포함한다. workbench_runs의 실제/합성 Scene·진단·Runtime, Asset/Export, 가중치/Cache/Conda, 인증·개인 설치 경로 설정을 제외한다. 불필요한 파일 삭제와 다른 브랜치 변경은 없다.

Commit 메시지: `feat(real2sim): refine reconstruction gates and sensor alignment`. 이 문서를 포함한 체크포인트 SHA는 `git log -1 --format=%H -- docs/reconstruction-integration-followup.md`로 재현한다. 실제 Commit/Push/로컬·원격 SHA 대조 결과는 Git 제외 `workbench_runs/diagnostics/reconstruction_integration_followup/push-receipt.json`과 완료 응답에 기록한다. Commit 내부에 자기 자신의 SHA를 하드코딩하지 않는다.

원격: [현재 기능 브랜치](https://github.com/HYEONHEE5739/real2sim-learning-studio/tree/feat/simfoundry-style-reconstruction). Force Push/Merge하지 않는다.

실사진 실행 전에 필요한 것:

- 실제 전체 작업판 코너 대응·치수 출처 또는 독립 Support/Robot World 점 대응. 크기만으로 Base를 결정하지 않음.
- 같은 정적 배치의 Side/Wrist, archived Robot model/Mapping 및 measured-q/시간 동기·충분한 Wrist 운동. 보호된 기존 World가 있으면 그 World와 Base의 독립 연결.
- 실제 Photo→sensor feature/PnP 품질, 렌즈/가림/노출 차이 검증. 이번 Fake PnP를 실사진 결과로 바꾸지 않음.
- reviewed CAD landmarks, 미사용 독립 Capture, Side/Wrist 각각의 RGB/Mask/landmark 평가. 보정 Pair의 오차와 독립 정확도 구분.
- 비단위 scale과 실측 Asset 충돌 시 corrected-point Stage8 재정합. 자동 역실행은 미구현.
- 실제 생성물/제거·Depth/Alpha·Mesh/CPD 정확도, Robot World 센서 정밀도, 실제 물리·Grasp/Task. Runtime 연결과 합성 수학 검증만으로 이들을 완료라 하지 않음.

## I. 포함 / 제외 파일 목록

총22개(기존 추적18개 수정·신규4개·삭제0개). 직전19개와 이번 추가3개(joint.py 수정, 후속 테스트·문서)를 합친 범위다.

- `docs/reconstruction-gate-review.md`
- `docs/reconstruction-integration-followup.md`
- `real2sim_builder/CODEX_SCENE_GUIDE.md`
- `real2sim_builder/README.md`
- `real2sim_builder/config/simfoundry-reconstruction.example.yaml`
- `real2sim_builder/src/real2sim_builder/authoring.py`
- `real2sim_builder/src/real2sim_builder/automation.py`
- `real2sim_builder/src/real2sim_builder/calibration/joint.py`
- `real2sim_builder/src/real2sim_builder/calibration/registration.py`
- `real2sim_builder/src/real2sim_builder/inference.py`
- `real2sim_builder/src/real2sim_builder/observations.py`
- `real2sim_builder/src/real2sim_builder/reconstruction_stages.py`
- `real2sim_builder/src/real2sim_builder/stage_artifacts.py`
- `real2sim_builder/src/real2sim_builder/stage_workers.py`
- `real2sim_builder/tests/test_codex_guidance.py`
- `real2sim_builder/tests/test_codex_vlm.py`
- `real2sim_builder/tests/test_flux_removal_contracts.py`
- `real2sim_builder/tests/test_local_runtime_validation.py`
- `real2sim_builder/tests/test_reconstruction_followup.py`
- `real2sim_builder/tests/test_reconstruction_gates.py`
- `real2sim_builder/tests/test_scene_memo_contract.py`
- `real2sim_builder/tests/test_stage_runtime.py`

실행 자료는 디렉터리 단위로 제외했다: workbench_runs/ 전체(Scene·Input·Capture·Candidate·Cache·Asset·Export·진단·runtime), 로컬 모델·Conda·HF Cache, 인증 및 개인 설치 경로 설정. 개별 사용자 파일을 이동·삭제하거나 stage하지 않았다. 정확한 포함 파일 SHA/크기와 제외 분류는 precommit-review.json, 보존 대조는 preservation-after.json에 있다.
