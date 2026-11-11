# Codex VLM 통합 및 MASt3R/COLMAP 실행 제거

> 2026-11-11 후속: 승인된 MASt3R 가중치/전용 소스를 삭제하고 Workspace를 Codex로 실제 이전했다. 기존 제품 경로의 온라인1회는900초 TIMEOUT으로 종료됐으며 실제 의미 응답/Stage7 전달은 BLOCKED다. [실사용 검증 기록](codex-vlm-live-validation.md)을 따른다. 아래는 이전 작업의 기록이다.


2026-11-10. `feat/simfoundry-style-reconstruction`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`. 이번 첨부 지시에 따라 기존 미커밋 구현 위에서 작업했다. **코드 연결과 최소 Mock/계약 검증을 완료했다. Codex 온라인 VLM은 LIVE_NOT_TESTED다.** 실제 모델 Forward·사용자 Scene Reconstruction·전체 회귀·설치·다운로드·디스크 삭제·Commit/Push/Merge는 하지 않았다.

## 1. 실제 호출 위치와 교체 결과

기존 호출은 `stage_runtime.invoke → stage_workers.vlm → SimFoundry Gemini`였다. Stage8은 별도로 `stage_workers.canonicalize → canonicalize_front(..., vlm=Gemini)`를 호출했다. SDK Schema Adapter `_StructuredGeminiClient`도 있었다. 두 실행과 Adapter를 제거했다.

현재 경로는 `stage_runtime.invoke('vlm') → authoring.run_codex_vlm → codex_cli.execute`다. Stage7 `authoring.run_codex_modeling`도 **동일한 `codex_cli.execute`**를 사용한다. 별도 인증·프로세스 관리자·UI·Agent Framework는 만들지 않았다.

| Stage | 실제 기존 VLM 용도 | 현재 연결 및 보존 조건 | 검증 상태 |
|---|---|---|---|
| 1·2 | VLM 호출 없음 | Photo/Video 준비와 DA3 Nested 경로 유지 | 이번 모델 Forward 없음 |
| 3 | hybrid 모드의 적격 대표 프레임 선택 | Codex가 적격 shortlist의 index만 반환. heuristic 모드에는 호출 없음. SAM/평면/FrameScore 수학 유지 | Schema/연결 코드 확인, 실제 hybrid 판단 LIVE_NOT_TESTED |
| 4 | VLM 호출 없음 | Support World/실측 QA 유지 | 이번 실제 metric QA 없음 |
| 5 | Instance/Category 갱신·장면 분해 | Codex가 ID/Category/Description/Box/Support/관계/가림 불확실성/Memo 일치 여부 반환. 최초 응답에 기존 `scene_analysis_schema`의 치수·참조·Task 의미 분석 포함 | 짧은 분해 Mock 및 Stage7 전달 검증 |
| 5 | 로컬 FLUX 제거 결과 검토 | Before RGB → Removal Mask → Generated RGB 순으로 전달. 기존 `removal_review_schema` 전체 필드와 Pixel Evidence 유지 | 실제 요청의 Mask 포함 및 uncertain 차단 Mock 통과 |
| 6 | Upsampling 이후 `check_valid` 옵션의 생성물 validity | 관측 RGB/Mask와 생성 RGB를 비교. validity·identity_preserved·other_objects_present·uncertain·reason 반환 | 관측 Crop Smoke/Schema·호출 코드 확인. 실제 생성물 판단 미실행 |
| 7 | 기존 Codex 의미 분석 후 Blender 제작 | Stage5 의미 응답의 SHA/Memo/Guide/입력 SHA를 검증하고 기존 파서로 해석해 재사용. 보호 실측 충돌 검사. 기존 Codex+Sandbox Blender/USDA 제작 유지 | Stage5 분석을 넣은 실제 Native Mesh handoff Mock에서 추가 분석 없이 모델링 1회 확인 |
| 8 | coarse/fine 의미적 Front 선택 | 원본 CPU software yaw 렌더는 `front_views` Child, 의미 선택은 공통 Codex. 원본 coarse 45°/fine ±22.5°·7.5° 및 기존 Yaw/Native 좌표 변환 유지. NONE/uncertain은 identity 회전·ambiguous | 짧은 Mock 및 Native Stage7/8 연결 통과. 실제 Front/CPD 실행 없음 |
| 9·10 | VLM 호출 없음 | 기존 articulation 미지원 Gate와 Scene 합성 유지 | 이번 실제 실행 없음 |
| 11 | 미측정 mass/friction 추정 | 해당 unknown Object에만 Codex 호출. Object ID를 한정한 Schema와 기존 estimated/보호 물성 검증 유지 | 호출/Schema 정적 확인, 실제 판단 미실행 |
| 12–14 | VLM 호출 없음 | Physics/불변 Review Package/Simulator·센서 선택 유지 | 이번 Physics·Isaac·사용자 Export 미실행 |

Codex는 기하를 측정하거나 실측/Calibration/FK를 덮어쓰지 않는다. CPD/수치 Pose·DA3 Z·SAM Mask·FLUX RGB 생성·Bria Alpha는 각 기존 모듈의 책임이다. Stage6 validity는 Upsampling 이후의 옵션 실행 분기에만 있으며, infill-only에는 기존처럼 VLM 호출이 없다.  모든 Stage에 새 판단을 무조건 추가하지 않았다.

## 2. 공통 CLI·모델·Schema 계약

설치 CLI는 **0.166.0**이다. 실제 `codex --version`, `codex exec --help`에서 `--image <FILE>...`, `--output-schema`, `--output-last-message`, `--json`, `--ignore-user-config`, `--ephemeral`을 확인했다. 모델 catalog는 기존 Builder의 `models_cache.json`에서 **모델 ID와 input_modalities만** 조사했다. 저장된 10개 모델은 text/image 입력을 표시했다. 이 조사로 현재 계정의 접근 권한·실제 이미지 판단 성공까지 확인한 것은 아니다.

공식 명령 계약도 [OpenAI CLI reference](https://developers.openai.com/codex/cli/reference)와 [non-interactive 문서](https://developers.openai.com/codex/noninteractive)를 대조했다. 실제 설치 버전의 help와 로컬 모델 메타데이터를 실행 판정의 기준으로 사용한다.

- 기존 UI가 주입하는 `REAL2SIM_CODEX_MODEL`/`REAL2SIM_CODEX_EFFORT`와 기존 `REAL2SIM_CODEX_HOME`을 공유한다. VLM에는 명시 선택 모델이 필요하며 미지원/미확인 이미지 Capability는 NEEDS_RUNTIME이다. 다른 모델로 자동 전환하지 않는다.
- 기존 App Server snapshot/selection_args, 로그인/로그아웃, 계정 전환의 auth lock과 사용량 API를 재사용한다. 새 API Key 입력이나 인증 파일 복사를 추가하지 않았다. 이번에는 실제 계정·Usage 조회나 온라인 exec를 실행하지 않았다.
- 기존 공식 permissions profile을 사용한다. 외부 인증/홈 파일 읽기와 도구 네트워크는 차단하고, 신뢰 Guide·SHA·복사한 입력·Schema를 격리된 임시 CWD에 전달한다. VLM도 CODEX_HOME이 Project 안에 있으면 거부한다.
- 모든 VLM 요청은 명시 JSON Schema를 요구한다. CLI의 constrained output과 별도로 Builder가 사용하는 type/nullable/required/additionalProperties/enum/배열·수치 bounds를 검사한다. 누락·추가 필드·JSON Parse 오류·비유한 값은 성공으로 저장하지 않는다. 이후 Instance/실측/제거 검증도 유지한다.
- Runtime/Guide·입력 이미지 SHA/Context·Memo·Schema·Prompt·Mask는 기존 Stage/Worker Cache Identity에 들어간다. Stage5 Model Reference도 Stage Identity에 포함한다. 전체 Python 구현 SHA 검증과 완료 Manifest 검증을 유지한다.
- 모델 Capability의 안정된 필드만 Identity에 넣는다. catalog의 조회 시각이나 계정 식별값이 바뀌었다는 이유로 같은 판단을 반복하지 않는다. 선택 모델·Effort·이미지·Memo·Schema·관련 파일이 달라지면 기존 결과를 그대로 재사용할 수 없다.
- Stage5 `scene_analysis`는 원본 메모와 이미지·Guide SHA, Stage7 source_views Identity를 검증한 뒤 파싱한다. 기존 측정/자산 선택은 보호하며 분석을 생략했다고 의미 검증을 생략하지 않는다. 최초 Scene 분석 이후의 생성 RGB에는 별도 제거/validity 판단이 필요하다.

`codex_cli.execute`가 소유 프로세스 그룹·timeout·checkpoint·Stop·종료를 담당한다. 자동 재시도는 없다. 오류 이벤트는 기존 AUTHENTICATION_FAILED/USAGE_LIMIT/MODEL_UNAVAILABLE/NETWORK_FAILED 분류를 사용한다. 로그에는 return code와 모델 선택만 저장하며 raw 계정/토큰/tool transcript는 저장하지 않는다. 원자적 answer/status와 완료 Worker Manifest가 없는 응답은 재사용하지 않는다. 사용량은 기존 공식 rate-limit 화면 기준이며 이번에 새 토큰량/비용 추정치를 만들지 않았다.

## 3. 기존 Workspace 설정의 명시적 이전 필요

**사용자 Project/Workspace YAML은 수정하지 않았다.** 현재 `workbench_runs/runtime/reconstruction.yaml`에는 이전 Gemini의 `runtimes.vlm.python/simfoundry_source/model_options`가 그대로 있다. 이 상태를 실제 실행하면 해당 VLM 경계에서 **NEEDS_RUNTIME / LEGACY_VLM_CONFIG**가 나온다. 기존 경로를 몰래 무시해 다른 Provider로 실행하지 않는다.

현재 [예시 YAML](../real2sim_builder/config/simfoundry-reconstruction.example.yaml)의 새 계약은 다음과 같다.

```yaml
runtimes:
  vlm:
    provider: codex
    timeout_s: 900
  pose:
    python: /EXISTING/r2s-cpd/bin/python
    simfoundry_source: /EXISTING/SimFoundry
```

후속 설정 변경 시 기존 파일을 백업하고 **vlm 블록 전체**를 위 계약으로 바꾼다. 기존 `vlm.simfoundry_source` 경로는 Stage8 CPU Front 렌더용 `pose.simfoundry_source`로 명시 연결한다. Workspace defaults는 중첩 병합되므로 Project 설정에 `provider: codex`만 추가하면 과거 Python/model_options가 남을 수 있다. 이 경우도 진단하며 숨겨서 무시하지 않는다. 나머지 DA3/SAM/FLUX/PDA/Bria/CPD/Blender/Physics 설치 경로는 유지한다.

Gemini 이미지 생성 설정도 `LEGACY_IMAGE_PROVIDER`로 명시 진단한다. Codex는 이미지 생성기가 아니며 현재 로컬 ComfyUI FLUX 경로를 유지한다. 선택 Imagen3/기존 FLUX 생성에 쓰는 외부 SimFoundry 공통 Wrapper는 삭제하지 않았다. 그 외부 파일 안의 Gemini 정의를 직접 수정하거나 기존 SDK 설치를 제거하지 않았다. 우리 제품의 Gemini VLM Client·직접 SDK Import는 제거했다. project pyproject에는 원래 google-genai 의존성이 없어 제거할 새 항목도 없었다.

## 4. MASt3R/COLMAP 실행 제거와 저장 자료 호환성

제거한 제품 파일은 `real2sim_builder/src/real2sim_builder/sfm.py`다. MASt3R GPU/COLMAP Worker·Backend 선택·런타임 Resolver·실행 전용 정합/재투영 구현이 함께 제거됐다. `inference.py`의 해당 probe/dispatch/import와 colmap 전용 Runtime 처리를 제거했다. 현재 제품/시험에서 이 모듈을 import하는 참조는 없다. Conda env list에서 `sfm-mast3r`/`sfm-colmap` 부재를 확인했고 재생성·재삭제하지 않았다.

`inference.run_models`는 명시 SAM-only 관측에만 사용한다. 제거된 자동 Geometry 실행을 요청하면 쓰기 전에 **LEGACY_GEOMETRY_UNSUPPORTED**로 거부하고 DA3 Stage2 사용을 안내한다. 기본 Reconstruction은 기존 SimFoundry Stage2 DA3이며 Source 기반 Codex-first 재정합도 유지한다.

저장된 `mast3r_colmap` Backend 문자열, common_frame/component, 기존 NPZ/Mask/점군/Camera는 삭제·변환하지 않았다. 기존 `validate_depth_output/object_points/build_point_clouds`, `observations`, calibration/metric/좌표·렌즈 수학은 유지한다. 이전 자료는 기존 메타데이터로 읽을 수 있으며 제거된 Backend를 재실행하는 것과 구분한다. Source Package·실측·Side/Wrist Calibration/Mount/measured q/FK·Robot Base는 변경하지 않았다.

`test_sfm_geometry.py`는 제거한 실행 전용 시험과 현재도 필요한 계약을 분리했다. 공통 Frame/component 분리, metric anchors/cloud/fusion, 배열·픽셀·왜곡, 소유 Child Stop/OOM, Native fitting 계약은 `test_depth_geometry_contract.py`의 DA3/저장 메타데이터 fixture로 이전했다. 옛 Backend 기본값/공식 SfM 모델 실행·전용 rasterizer/lens grouping 같은 제거한 기능의 시험만 삭제했다. 이번에 이전한 Native 렌더 fitting 시험을 새로 실행하지는 않았다.

단일 UI의 저장 설정 열기/기존 Scene Prepare 버튼·인증 컨트롤 시험은 유지한다. 옛 설정을 읽는 fixture의 Backend 문자열은 호환성 확인용이다. 과거 실행/설치 문서에는 최신 전환 안내를 붙여 당시 기록임을 표시했다. 과거 실행 수치·실제 사진 Evidence를 새 결과로 재작성하지 않았다.

## 5. 디스크 조사 — 삭제 0개

`disk-inventory.json`에 경로·logical bytes·inode별 할당량·hardlink·참조·현재 HF Snapshot/Conda env 목록을 저장했다. 용량은 실제 stat/du 조사값이며 예상 다운로드량이 아니다.

| 대상 | 실제 관측 용량 | 참조와 처리 |
|---|---:|---|
| `workbench_runs/sfm_comparison_20261108/src/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth` | 2,754,910,614B / 할당2,754,916,352B | 과거 auto-version 설정/진단이 참조. 실행기는 제거했지만 재현 이력 보존 필요. **별도 승인 전 삭제 금지** |
| 같은 `src/mast3r` | logical10,833,191B / 할당11,575,296B | 과거 원본 소스. 별도 승인 전 삭제 금지 |
| Conda `pkgs` | logical6,108,653,429B / 고유 inode 할당4,489,367,552B | 활성 env와 공유 가능. 단일 링크 파일 할당 상한1,718,317,056B도 실제 안전 회수량은 아님. `conda clean` 실행 안 함 |
| FLUX GGUF/T5/CLIP/VAE | 4개, logical12,536,135,116B | 모두 HF blobs와 같은 inode. ComfyUI와 Cache를 별도 12GB 복제라고 더하지 않음. 활성 가중치 보존 |
| HF Cache | DA3 Nested/PDA/SBERT/FLUX 인코더·VAE/GGUF Snapshot 확인 | 전부 보존. DA3-SMALL도 발견했으나 현재 연결 미확인으로 보존. legacy MASt3R/COLMAP HF 모델 디렉터리는 이번 검색에서 발견되지 않음 |

여유 공간 관측 약 **29.94GiB**. 홈 전체/외부 디스크를 전수 조사한 것은 아니다. 사용자 이미지·진단 결과·공유 Cache·가중치·외부 Runtime Source는 하나도 삭제하지 않았다.

## 6. 실제 검사와 변경·보존

실행 근거는 Git 제외 `workbench_runs/diagnostics/codex_vlm_migration/`이다. 이 폴더는 제품 의존성이 아니다.

- **고유 46개 최소 시험 통과**, skip/xfail로 우회하지 않았다. 전체 회귀가 아니다. 동일 시험의 RED/Green/후속 수치는 합산하지 않는다.
- 마지막 공통 CLI/새 VLM 계약 묶음 **24 passed**(`final-cli.xml/log`), 제거 Mask 전달·uncertain Gate 별도 **1 passed**(`removal-mask.xml/log`).
- Stage5–7–8 Mock/Native Mesh 전달·저장 Legacy UI·공통 Depth/Metric 배열·Guide 계약을 포함한 앞선 묶음21개 및 후속 묶음21개를 기록했다. 초기 공통 함수 부재 RED, 새 함수 Path import 누락/시험의 YAML log를 JSON으로 읽은 오류, Guide version fixture 불일치와 수정 결과도 로그에 남겼다.
- 기존 계정 Home·로그인/선택·Usage bucket·auth lock·분류·Stop/timeout/소유 그룹 종료 시험은 Mock/fake CLI로 검사했다. 실제 Codex exec·모델 응답·인증/Usage 서비스 호출은 **0회**다.
- GPU/AI 모델 추론 **0회**, DA3/SAM/FLUX/PDA/Bria/CPD 재실행 **0회**, Isaac/실물 로봇·실제 사용자 E2E **0회**. 짧은 Native USD/Mesh/수학 처리를 실제 모델 Forward로 표시하지 않는다.
- 보호 ledger는 Scene/Input/Capture/Calibration/Candidate/Cache/Export·공용 Asset·기존 local_runtime_validation·Workspace Runtime **18,462개 파일**이다. 최종 SHA/크기·누락·신규 대조는 `preservation-after.json`을 따른다. 전체 SDK/모델 디스크의 전수 SHA 대조라는 뜻은 아니다.
- DA3 `da3` Worker 함수 AST와 SAM3.1 Adapter는 작업 시작과 동일하다. 설치된 모델/외부 SimFoundry 소스를 고치지 않았다.
- 기존 staged23개 diff SHA는 `5e259fbe6370626a3b608b1b55bc3d12205ab69650731b1994f1c9b2184c3bb6`로 유지한다. 이번 변경은 추가 unstaged/untracked 상태다. Commit/Push/Merge/새 Worktree 없음.

제품 변경은 기존 `codex_cli.py`, `authoring.py`, `stage_runtime.py`, `stage_workers.py`, `reconstruction_stages.py`, `automation.py`, `inference.py`와 예시 YAML/Guide에 한정한다. `sfm.py`를 삭제했다. 신규 제품 실행 모듈은 없다. 변경·신규·삭제 시험과 문서의 정확한 목록, Python compile/정적 참조 검사는 `change-inventory.json`, `compile-check.json`, `static-check.json`에 있다. 이번 변경과 이전 미커밋 구현을 구분한 목록이다.

## 7. 다음 실제 검증의 조건

| 범위 | 구현/Mock | 이번 실제 Forward | 다음 조건/Blocker |
|---|---|---|---|
| 공통 Codex VLM | 연결·Schema·오류/중단/Cache 계약 완료 | LIVE_NOT_TESTED | 구형 Workspace VLM 설정 명시 이전, 기존 UI 모델/강도 선택, 실제 이미지 최소 호출에 대한 후속 실행 지시 |
| Stage3 | shortlist Schema·연결 완료 | 미실행 | 실제 SAM/평면 후보 뒤 hybrid 시각 선택 검증 |
| Stage5 | Instance/메모 공통 분석·제거 Gate·Stage7 재사용 Mock 완료 | 미실행 | 실제 Instance/치수/관계 의미 정확도와 실제 FLUX 제거 영상 검토 |
| Stage6 | 원 관측/Mask/생성물 validity 계약 완료 | 미실행 | `check_valid` 옵션에서 실제 Identity/Alpha 검증. FLUX/Bria는 기존 설치 유지 |
| Stage7·8 | 기존 Blender/Native 연결과 공통 분석 재사용·Front Mock 완료 | 미실행 | 실제 Codex Mesh 제작/Front 판단/CPU CPD 수치 검증은 별도 범위 |
| Stage11 | typed estimated 물성 호출 연결 | 미실행 | 영상 추정과 실측 구분, 실제 물성·물리 검증을 별도로 수행 |
| Stage1·2·4·9·10·12–14 | 기존 경로 보존 | 이번 미실행 | 기존 Robot World/센서 Calibration·물리/지원 범위 Blocker는 이전 문서대로 유지 |

실제 온라인 VLM, 전체 Stage E2E와 Scene 완성을 완료했다고 보고하지 않는다. 설정 이전만으로 실사진 Geometry·제거 품질·물리·Task 정확도가 해결되는 것도 아니다.

## 8. 최종 마감 및 이번 변경 파일

2026-11-11 중단 후 마감. 추가 모델/온라인 실행 없이 기존 검증 기록을 확인했다. 변경 Python **17개**의 bytecode 없는 compile과 `git diff --check`를 확인했다. 계정/모델/추론 강도 미지원 진단의 RED→Green도 `selection-red.xml`, `selection-green.xml`에 남겼다. 전체 회귀는 재실행하지 않았다. 보호 대상 **18,462개 파일 변경0·누락0·신규0**, Git Index/HEAD 불변을 다시 확인했다(`completion-check.json`).

이번 작업 시작 상태 대비 **36개 파일 변경**(수정31·신규3·삭제2)이다. 이전부터 있던 미커밋 구현과 구분한 목록은 다음과 같다.

- `docs/auto-reconstruction-ui.md` — 수정
- `docs/automated-reconstruction.md` — 수정
- `docs/codex-first-scene-builder.md` — 수정
- `docs/codex-vlm-migration.md` — 신규
- `docs/flux-inpainting-validation.md` — 수정
- `docs/geometry-backend-integration.md` — 수정
- `docs/local-runtime-validation.md` — 수정
- `docs/simfoundry-algorithm-completion.md` — 수정
- `docs/simfoundry-reconstruction-migration.md` — 수정
- `docs/simfoundry-runtime-setup.md` — 수정
- `real2sim_builder/AUTO_SCENE_FITTING.md` — 수정
- `real2sim_builder/CODEX_SCENE_GUIDE.md` — 수정
- `real2sim_builder/README.md` — 수정
- `real2sim_builder/SCENE_AUTHORING.md` — 수정
- `real2sim_builder/SCENE_RULES.md` — 수정
- `real2sim_builder/SOURCE_DOCUMENTS.md` — 수정
- `real2sim_builder/config/simfoundry-reconstruction.example.yaml` — 수정
- `real2sim_builder/src/real2sim_builder/authoring.py` — 수정
- `real2sim_builder/src/real2sim_builder/automation.py` — 수정
- `real2sim_builder/src/real2sim_builder/codex_cli.py` — 수정
- `real2sim_builder/src/real2sim_builder/inference.py` — 수정
- `real2sim_builder/src/real2sim_builder/reconstruction_stages.py` — 수정
- `real2sim_builder/src/real2sim_builder/sfm.py` — 삭제
- `real2sim_builder/src/real2sim_builder/stage_runtime.py` — 수정
- `real2sim_builder/src/real2sim_builder/stage_workers.py` — 수정
- `real2sim_builder/tests/test_ai_reconstruction.py` — 수정
- `real2sim_builder/tests/test_codex_guidance.py` — 수정
- `real2sim_builder/tests/test_codex_vlm.py` — 신규
- `real2sim_builder/tests/test_depth_geometry_contract.py` — 신규
- `real2sim_builder/tests/test_flux_removal_contracts.py` — 수정
- `real2sim_builder/tests/test_geometry_ui_integration.py` — 수정
- `real2sim_builder/tests/test_local_runtime_validation.py` — 수정
- `real2sim_builder/tests/test_sfm_geometry.py` — 삭제
- `real2sim_builder/tests/test_stage_decomposition.py` — 수정
- `real2sim_builder/tests/test_stage_pose.py` — 수정
- `real2sim_builder/tests/test_stage_runtime.py` — 수정
