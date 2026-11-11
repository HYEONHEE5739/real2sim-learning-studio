# SimFoundry 알고리즘 보완 — Phase F–H 진행 기록

> 2026-11-10 후속: VLM은 공통 Codex CLI로 전환했고 MASt3R/COLMAP 실행 코드는 제거했다. 현재 설정과 검증 범위는 [Codex VLM 전환](codex-vlm-migration.md)을 따른다. 아래 과거 실행·설치 기록은 당시 상태다.


2026-11-10. 기존 `feat/simfoundry-style-reconstruction`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`에서 진행한다. 기존 staged23개와 앞선 미커밋 구현을 보존한다. Phase F/G/H 코드 보완과 집중 검증을 마쳤으며 최종 전체 회귀 결과는 마지막 절에 기록한다.

## Phase F

- Stage5: 원본 Category VLM 주기 갱신, SBERT(선택 CLIP) 의미적 Mask pruning, SAM3 text-first/point fallback, 기하 중복/경계/지지면 아래 Mask 제거, Mask 분리, 안정된 Instance ID 대응, mask→outline→bbox 각 seed0–2 제거 재시도를 연결했다. 기존 Hull/ray 순서·DA3/PriorDepth known-depth 보존을 유지한다.
- 원본의 SBERT/CLIP은 Category refresh 모델이 아니다. 이 어댑터는 추가 GPU 점유를 줄이기 위해 SBERT의 기본 실행 장치를 CPU로 지정하며 실제 Encoder 추론은 이번에 실행하지 않았다. VLM이 Category 목록을 갱신하고 Encoder는 Mask 간 의미 유사도 판정에 사용된다. 완전히 같은 두 Box를 원본 pruning이 모두 제거하는 경우도 재현했다. 이를 성공한 Instance 관측으로 바꾸지 않고 NEEDS_REVIEW로 중단한다.
- Stage6: Provider-native 종횡비 선택, 10% focus/50% context, RGBA/nearest alpha, 선택 Infill, Upsampling, Bria RemBG, typed validity 확인을 연결했다. 원본의 malformed validity→valid=True 처리는 사용하지 않는다. 생성 이미지에는 원관측 Depth를 정합된 새 Depth처럼 부여하지 않는다. RemBG는 명시된 로컬 ONNX만 사용하도록 로딩 경계를 제한한다.
- Stage8: 기존 CPD 후보 수학을 유지하고 후보별 변환/오차를 보존한다. 원본 Tilt consensus와 Yaw rectangle math를 Native +Z에 맞춰 연결하고 원본 software-render/VLM front 선택을 Child에서 호출한다. Native canonical backend는 auto Tilt baking 대상이 아니다. 새 Asset 내부의 Visual/Collision을 함께 회전하고 Pose를 역보상한다. 보호된 실측 축을 바꾸는 Canonical rotation은 검토를 요구한다.
- `phase_f_h/phase-f.xml/log`: **43 passed**, 86.28초. Pure Geometry, 실제 Native USD/Asset/parser, Mock Stage 흐름을 구분한다. 실제 CPD/Front VLM/RemBG 추론은 실행하지 않았다. 확인한 기존 환경에는 probreg가 없어 실제 CPD 수치 검증은 NEEDS_RUNTIME이다.

## 검증 경계

실제 사용자 E2E·모델 Forward·설치·다운로드·Commit/Push는 수행하지 않는다. 중간 Phase의 집중 수치를 합쳐 전체 회귀 수치로 사용하지 않는다.

## Phase G

Stage9 신규 관절은 NOT_SUPPORTED를 유지한다. Stage10은 명시된 로컬 크기·두께·Transform·출처를 가진 지지면의 독립 USD Asset 등록을 추가했다. 부분 평면에서 외곽이나 두께를 발명하지 않으며 기존 지지면을 덮어쓰지 않는다. Stage11은 기존 Visual/convex·compound 검증을 유지하고 추가 CoACD/VHACD 요청을 미지원으로 명시한다.

Stage12는 최대10,000 Step의 제한, 실제 MuJoCo Pose 시계열과 Before/After·위치/회전·접선 이동/Up축 변화·20Step 안정 구간을 기록한다. 원본의 매Step 속도 강제 초기화는 사용하지 않는다. 안정화 Pose는 진단 제안으로 저장하며 실제 실행·settled·일치하는 명시 리뷰와 기존 preserve/validate를 모두 통과해야 Candidate에 적용한다. Mock 결과/보호된 실측/확정 접촉을 덮어쓸 수 없다. Isaac은 Pose 기록 경계를 추가했으나 실행하지 않았고 관통 검증이 없는 상태에서 settled를 확정하지 않는다. Stage13/14의 불변 Review Package와 실제 센서/Reference Camera 구분을 유지했다.

`phase_f_h/phase-g.xml/log`: **64 passed**, 88.48초. 실제 합성 MuJoCo 접촉/중력, Native USD/Asset/parser와 Mock Stage 연결 결과다. 새 관절/추가 collision decomposition/Isaac 물리·실물 Task는 검증하지 않았다.

## Phase H — Runtime와 입력 계약

모델 초기화·Forward·원격 생성·인증 조회 없이 기존 Interpreter에서 import와 Signature를 조사했다. `phase_f_h/runtime-api-results.json`과 환경별 `*-api.json`이 근거다.

| 경계 | 실제 확인 | 남은 조건 |
|---|---|---|
| DA3 (`da3`) | DepthAnything3.inference import/Signature, 기존 Nested Snapshot/revision 존재, Open3D import | Forward 미실행. Mixed 가중치 분리 함수 AST가 작업 시작 전과 동일함을 확인 |
| SAM (`sam31`) | Interpreter 및 기존 SAM3.1 Multiplex 가중치 존재 | 원본 SimFoundry가 import하는 `sam3`와 `sentence_transformers`/skimage/Shapely는 이 환경에서 import 실패. 기존 Ultralytics 계열 가중치의 원본 SAM3 호환성을 추정하지 않음 |
| SBERT/CLIP/VLM/Image Editing/PriorDepth | 보존된 원본 Wrapper의 함수/호출 경로 비교 | 완전한 설치 SimFoundry Runtime·의존성·로컬 모델 경로가 아직 설정되지 않음. 인증/서비스 호출은 NOT_TESTED |
| CPD | `da3`, `lerobot-arena`, `lerobot`에서 probreg import 실패 | NEEDS_RUNTIME. 다른 Solver로 대체하거나 실제 CPD 복원 오차를 만들지 않음 |
| 원본 Mask 수학 | 기존 `lerobot`에서 skimage/Shapely import 및 순수 pruning/분리 계산 실행 | 이 CPU 환경의 존재가 SAM3 추론 환경 완성을 뜻하지 않음. 기본 회귀는 의존성 누락 Gate와 의존성 없는 순수 수학을 검사 |
| RemBG / CoACD | 조사한 추론/Builder 환경에서 import 실패 | 명시 로컬 Bria ONNX/RemBG 필요. 추가 CoACD/VHACD Native 변환은 NOT_SUPPORTED |
| FoundationPose | estimater/nvdiffrast import 실패. 원본 Stage8의 register 호출과 인자 확인 | 실제 register/추론 미실행. 자동 설치·다른 알고리즘 대체 없음 |
| MuJoCo / USD | MuJoCo import/API와 실제 Synthetic CPU physics/parser; 기존 Builder library path에서 USD import | Bare env의 USD 실패와 설정된 library path의 성공을 구분. Boost `Stage.Open`의 Python Signature는 노출되지 않아 실제 Native parser 시험으로 보완 |
| Blender/Sandbox/FFmpeg | 실행 파일 존재, 기존 회귀, Synthetic FFmpeg 실제 decode/PTS/stride | 사용자 영상/원격 Codex 제작은 미실행 |
| Isaac | 기존 설치 경계·Child 계약과 Mock 확인 | AppLauncher/Kit·GPU E2E/Physics는 NOT_TESTED. import 성공으로 보고하지 않음 |

Stage1 정적 입력에서 Photo/Video를 사용하고 Model Reference와 Side/Wrist를 제외한다. Stage7은 Candidate 소유의 Stage1 프레임 ID/SHA/해상도를 분석·모델링 양쪽에서 검증한다. 새 프레임의 변경은 분석 Cache identity에 들어간다. Video-only에서 Project 사진 목록에 없는 ID를 다시 찾던 오류를 RED→GREEN으로 수정했다. Model Reference는 실제 Object별 LINKED 근거로 전달하며 Capture의 measured q는 context에 보존한다. Schema 응답만 Fake CLI로 만들었고 실제 run_codex_modeling의 sandbox handoff/Schema/참조 검증을 실행했다.

Photo+Reference+Memo, Video-only+Reference+Memo, 각 입력에 Side/Wrist+Synthetic measured q를 추가한 네 조합을 검사했다. UI 입력 폼은 바꾸지 않았다. 새로운 video frame을 Project 원본 사진 목록에 등록하지 않았고 기존 Source 기반 Real/Sim 경로를 바꾸지 않았다.

실제 소유 Child에 대한 Stop/Timeout/프로세스 그룹 종료 및 의존성 누락 `result.json`도 검사했다. 무거운 모델은 초기화하지 않았다. Stage6 typed validity 거부와 제거 9회 소진 뒤 Depth Worker 호출 차단도 별도로 확인했다. 중간 UI 회귀 1건은 테스트 실행 명령의 REAL2SIM_BLENDER 누락이었으며, 기존 설치 경로를 명시한 재실행에서 통과했다.

## 함수별 원본 비교와 남은 차이

| Stage / 원본 함수 | 이번 구현과 검증 | 상태 / 원본과의 차이 |
|---|---|---|
| 1–4 frame/depth/selection/world | 기존 구현 보존, 실제 FFmpeg 합성 영상 검증 추가 | IMPLEMENTED 코드 경계. 실제 DA3/SAM Forward와 독립 Metric QA 미검증 |
| 5 get_primary_object_name / choose_prompt_point_from_bbox | 원본 AST 동일, 실제 선택 수학 | IMPLEMENTED. 자유 Memo 정규식 파서가 아님 |
| 5 SAM3.prune_redundant_masks / prune_masks_below_surface / disentangle_masks | source self 제거·lazy import·구조적 Encoder 인터페이스 외 수학 유지. CPU 수학 실행 | IMPLEMENTED 지원 분기. 동일 Box 모두 제거하는 원본 동작을 남기되 불완전 Instance를 검토 Gate로 처리 |
| 5 category refresh / compute_object_removal_order / RGB removal / PriorDepth | VLM 주기·SBERT 의미 검사·ray 순서·3종×3회 재시도와 known-depth splice | IMPLEMENTED 지원 분기 / 실제 Provider NOT_TESTED. 원본의 invalid object 진행 옵션 대신 NEEDS_REVIEW. Instance ID는 일대일 기하 대응이 모호하면 확정하지 않음 |
| 6 crop/pad/edit/remove_background/validity | 원본 focus/context/native ratio, RGBA/Alpha, 선택 Infill, Upsample/RemBG, 검증 분기 | IMPLEMENTED 지원 Provider. Stage6 native ratio는 기존 Gemini/FLUX에 연결한다. Imagen3는 원본 Stage5 제거에만 사용되며 Stage6 설정은 명시적으로 NOT_SUPPORTED다. 원본 GPT 분기는 추가하지 않음. malformed validity를 성공으로 바꾸지 않음. RemBG 로컬 가중치 경계는 원본 다운로드 로더를 제한하는 어댑터 |
| 7 generate_object_meshes | 기존 Codex+Sandbox Blender / Native Asset | 의도적 교체. Hunyuan/GLB 없음. World Pose는 Stage8/10 소유 |
| 8 sample_fits / inverse fit | Surface/OBB/voxel/farthest/SO3/rigid CPD/scale/one-sided NN, 후보별 변환 보존 | PARTIAL 전체 Stage. 실제 probreg Runtime 부재로 수치 오차/재시작 수렴/대칭 복원 미검증. 추정 결과는 UNVERIFIED |
| 8 upright_from_fit / front_canonicalization | Tilt consensus·Yaw math 10개 함수의 원본 AST 동일. 원본 software render/VLM front Wrapper 호출. Native +Z↔source +Y proper rotation, Asset/Pose 역보상 | 코드 구현 및 Synthetic 수학 검증. 실제 front/FP 미검증. Native canonical backend는 auto Tilt를 굽지 않음. Front가 모호하면 의미적 방향을 확정하지 않음 |
| 8 FoundationPose.register | 원본 register K/RGB/Z/Mask/iteration 경계, Native Mesh/scale | PARTIAL. 현재 Adapter는 FP register 뒤 기하 보존 Canonical 변환을 적용한다. 원본의 post-FP Tilt 재판정 전체 분기를 동일 실행했다고 주장하지 않음 |
| 9 articulation | 기존 Robot URDF/FK 불변, 요청 없으면 applicable=false | BLOCKED 신규 관절. 최소 지원은 기존 Robot 관절 보존·검증이며 신규 Object 관절 생성은 NOT_SUPPORTED |
| 10 compile mesh scale/rotation/translation→camera_to_world | Native 새 자산 버전·원본 root 유지·역보상 Pose, 독립 지지면, 저장 직후 재개 재사용 | PARTIAL. Support는 명시 치수/두께/Transform 필요. 부분 평면의 전체 Support Mesh 자동 복원이나 DA3→Robot World 추정은 하지 않음 |
| 11 collision / physical properties | 기존 authored convex/compound 검증·불변 Asset·물성 출처/unknown Gate 유지 | PARTIAL. 원본 `generate_collision_meshes`의 CoACD/pymeshlab 변환을 이식한 것은 아님. 실패 시 컵을 막는 단일 Hull 대체 없음 |
| 12 stabilize_object / stabilize_all_objects | 실제 Step, Pose 시계열·최종 속도·관통·위치/회전 안정 구간, Support 법선 기준 접선 이동, 검토된 Candidate Pose 반영 | PARTIAL. 원본 강제 속도0/순차 고정은 사용하지 않음. Slip/Topple의 이동 진단은 물성·안정성 인증이 아님. Isaac 관통/settled 미확정 |
| 13 immutable package | 기존 exporter/closure/parser, 미승인 Review | IMPLEMENTED 코드. 자동 Promote 없음. 실제 사용자 Export 미생성 |
| 14 simulator integration | 현재 Candidate의 실제 최신 Pose snapshot과 센서 목록을 Worker에 전달, package identity/Side/Wrist/reference 보존 | PARTIAL. 실제 Isaac/센서 정합/Source-Annotation-DataGen-Task E2E는 미실행 |

`phase_f_h/source-port-comparison.json`: Tilt/Yaw/Point Prompt 관련 **12개 함수 AST 동일**, 기존 조사 원본 **115개 SHA 변경0**. SAM pruning은 self/lazy-import/Protocol 어댑터 차이를 별도 명시한다. Native +Z→source +Y 변환은 determinant+1의 회전이며 source front +Z는 Native -Y에 대응한다.

추가 확인 원본: [SimFoundry collision conversion](https://github.com/NVlabs/SimFoundry/blob/9e34ebefcd020583fbb755a8b57268dce78eca26/simfoundry/utils/asset_conversion_utils.py)의 `generate_collision_meshes`는 CoACD/convex와 pymeshlab을 사용한다. 해당 helper의 VHACD 분기는 확인되지 않았다. 기존 조사115개에는 없던 이 helper는 온라인 읽기로 보완했고 제품으로 복사하지 않았다. RemBG의 로컬 경계 근거는 [공식 Bria Session](https://github.com/danielgatis/rembg/blob/main/rembg/sessions/bria_rmbg.py) 및 [BaseSession](https://github.com/danielgatis/rembg/blob/main/rembg/sessions/base.py)이며 설치 API/실제 ONNX 실행은 여전히 미검증이다.

## 최종 회귀·보존

마지막 Provider 설정 거부와 안정화 Pose 재개 검사까지 포함한 세 패키지 전체 회귀: **1,751 passed / 실패0 / 오류0 / skipped0**, 기존 torchvision 경고4개, Console 기준517.15초. `phase_f_h/release-full-verified.xml/log`가 근거다. 이전 전체1,726개와 비교해 수집 시험25개가 늘고 기존 시험명 삭제0이며 skip/xfail로 우회하지 않았다. 마지막 거부 검사 전 전체1,748개(518.09초)와 구분한다.

집중 검사: Phase F43개, Phase G64개, Runtime/UI/영상/분해 관련38개, 마지막 연결15개, Provider 거부/안정화12개가 각각 통과했다. 서로 겹치는 시험이므로 합산하지 않는다. 실제 합성 CPU MuJoCo 300Step의 Before/After·연속 안정 구간·명시 검토 후 Candidate 반영 및 재개도 실행했다. 이 결과는 `synthetic-physics-evidence/physics.json`과 NPZ에 복사 보존했다. 가상의 수치를 실제 CPD/모델/사용자 Scene 결과처럼 사용하지 않았다.

보존 대조: 기존 Scene/Input/Capture/Calibration/Candidate/Cache/Export 및 공용 Asset root **7,786개 파일 SHA/크기 변경0·누락0·신규0**. 조사 원본115개 SHA 변경0, 변경 Python52개 bytecode 없는 compile 및 `git diff --check` 통과. SDK/모델/과거 진단 전체의 전수 SHA 대조는 아니다.

브랜치 `feat/simfoundry-style-reconstruction`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`를 유지한다. 기존 staged23개 diff SHA `5e259fbe6370626a3b608b1b55bc3d12205ab69650731b1994f1c9b2184c3bb6`는 시작과 동일하다. 이번 변경도 미커밋 상태이며 Commit/Push/Merge·설치·모델 다운로드·실제 사용자 E2E·실물 구동을 하지 않았다.

증거는 Git 제외 `workbench_runs/diagnostics/simfoundry_migration/phase_f_h/`의 baseline, RED/GREEN 로그, `release-full-verified.xml/log`, `regression-comparison.json`, `runtime-api-results.json`, `source-port-comparison.json`, `da3-policy-preservation.json`, `preservation-after.json`, `index-preservation.json`, `compile-check.json`, `change-inventory.json`, `verification-summary.json`이다. 단계 연결 Mock, 실제 Pure Geometry/Native parser/CPU physics, 실제 Runtime API, 모델 Forward 미검증, 사용자 E2E 미검증을 구분한다.

## 실제 E2E 전에 필요한 준비

1. 기존 설정 템플릿의 Runtime을 실제 호환 설치에 연결한다. 원본 SimFoundry/SAM3·Encoder·PriorDepth/Bria·probreg·선택 FoundationPose의 누락을 해결해야 한다. 이번 작업은 이를 설치하거나 자동 다운로드하지 않았다.
2. 서비스 Provider 자격은 사용자 환경에서 별도 제공해야 한다. 이번에 인증의 유효성을 조회하거나 원격 생성을 실행하지 않았다.
3. 실측/Calibration·Robot World 등록·Side/Wrist 공유 Mount/FK·독립 Capture를 유지하며 실제 Metric QA를 준비한다. DA3 model-estimated m나 CPD 잔차로 독립 정확도를 인증하지 않는다.
4. 실제 모델/사용자 사진 E2E는 별도 지시 후 수행한다. 새 물리 관절, 자동 Support 전체 복원, 추가 CoACD 변환, Isaac 관통/안정성·Grasp/Task 성공은 여전히 미지원 또는 미검증이다.

코드 경계 구현, Synthetic 수학, Mock 연결, 실제 Runtime import/API, 실제 모델 Forward, 실제 사용자 E2E는 서로 다른 검증 상태다. 일부 Runtime이 없다는 이유로 다른 알고리즘으로 바꾸거나 이번 기록을 실제 Scene 완성으로 승격하지 않는다.

## 이번 변경 파일

Phase F–H 시작 상태 이후 기존 파일16개 수정·신규7개·삭제0개다. 앞선 Stage 전환과 기존 staged23개는 이 수치와 구분한다. `validation.py`는 기존 추적 파일의 수정이며 신규 모듈이 아니다. UI 제품 코드는 이번 Phase에서 변경하지 않았다.

기존 파일 수정:

- `docs/simfoundry-reconstruction-migration.md`
- `real2sim_builder/CODEX_SCENE_GUIDE.md`
- `real2sim_builder/config/simfoundry-reconstruction.example.yaml`
- `real2sim_builder/src/real2sim_builder/authoring.py`
- `real2sim_builder/src/real2sim_builder/automation.py`
- `real2sim_builder/src/real2sim_builder/object_assets.py`
- `real2sim_builder/src/real2sim_builder/reconstruction_stages.py`
- `real2sim_builder/src/real2sim_builder/stage_runtime.py`
- `real2sim_builder/src/real2sim_builder/stage_workers.py`
- `real2sim_builder/src/real2sim_builder/validation.py`
- `real2sim_builder/tests/test_codex_guidance.py`
- `real2sim_builder/tests/test_stage_compilation.py`
- `real2sim_builder/tests/test_stage_decomposition.py`
- `real2sim_builder/tests/test_stage_pose.py`
- `real2sim_builder/tests/test_stage_runtime.py`
- `real2sim_builder/third_party/SIMFOUNDRY_NOTICE.md`

신규 파일:

- `docs/simfoundry-algorithm-completion.md`
- `real2sim_builder/src/real2sim_builder/calibration/canonicalization.py`
- `real2sim_builder/src/real2sim_builder/calibration/decomposition.py`
- `real2sim_builder/tests/test_decomposition_algorithms.py`
- `real2sim_builder/tests/test_pose_canonicalization.py`
- `real2sim_builder/tests/test_stabilization_evidence.py`
- `real2sim_builder/tests/test_stage_video_authoring.py`
