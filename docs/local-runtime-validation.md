# 로컬 Runtime 실제 검증 및 Workspace 연결

> 2026-11-10 후속: VLM은 공통 Codex CLI로 전환했고 MASt3R/COLMAP 실행 코드는 제거했다. 현재 설정과 검증 범위는 [Codex VLM 전환](codex-vlm-migration.md)을 따른다. 아래 과거 실행·설치 기록은 당시 상태다.


**후속(2026-11-10):** FLUX Prompt 손실 수정 후 큐브/그림자 제거는 개선됐으나 배경 경계는 NEEDS_REVIEW다. Bria는 별도 명시 동의 뒤 CPU 환경·ONNX 설치, 합성1회 및 Workspace rembg 연결을 마쳤다. 아래는 당시 기록이며 최신 범위/수치는 [FLUX·Bria·VLM 후속 검증](flux-inpainting-validation.md)을 따른다.


2026-11-10. `feat/simfoundry-style-reconstruction`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`. 최신 첨부 지시 기준으로 **SAM Text 1회·FLUX Object Removal 1회만 실제 실행**했다. 패키지 설치/업그레이드·모델 다운로드·전체 회귀·사용자 Scene E2E·Commit/Push/Merge는 하지 않았다.

| 구분 | 실제 결과 |
|---|---|
| SAM3.1 신규 Adapter Forward | **성공**, 합성 컵 Mask1개 / Confidence0.88623 |
| FLUX Object Removal Forward | **호출 성공**, 결과 RGB512×512 반환 |
| FLUX 제거 품질 | **불합격** — 빨간 큐브와 그림자가 남음 |
| Stage RGB→Depth 계약 | **통과**, 기존 PDA 배열 Replay Mock / 신규 PDA Forward0회 |
| Stage3/5/6 집중 Smoke | **통과**, CPU/대역 검증, 실제 Stage 전체 실행 아님 |
| Workspace Runtime | **적용**, 설치 경로·모델 SHA 확인, Reconstruction 실행0회 |
| 전체 Scene / 실제 센서·기하·물리 정확도 | **NOT_TESTED** |

## 실제 실행과 자원

| 항목 | SAM3.1 Text | FLUX Object Removal |
|---|---:|---:|
| 입력 | 독립 합성 컵768×512 | 독립 합성 테이블·빨간 큐브512×512, 정확한 Mask·빈 배경 GT |
| 호출 | 1회, prompt=`cup` | 1회, seed0 / Q4_K_S / batch1 / 20step |
| Worker 전체 시간 | 21.458s | 127.206s |
| 내부 API 시간 | Adapter16.045s | Comfy Prompt109.15s |
| 전체 GPU 관측 Peak | 5,475MiB | 6,417MiB |
| 소유 프로세스 GPU 관측 Peak | 4,720MiB | 5,678MiB |
| RSS 합 관측 Peak | 7,624,077,312B ≈7.10GiB | 15,208,861,696B ≈14.16GiB |
| PSS 합 관측 Peak | 7,619,704,832B ≈7.10GiB | 14,860,583,936B ≈13.84GiB |
| Worker 종료 후 전체 GPU | 752MiB | 666MiB |
| OOM / Timeout / 추가 추론 재시도 | 없음 / 없음 / 0회 | 없음 / 없음 / 0회 |

nvidia-smi/RSS는 약150ms+조회 비용 간격의 표본 관측이며 PSS는 매5번째 표본이다. 전체 GPU 값은 Desktop 등 배경 사용을 포함하고 RSS 합은 공유 Page를 중복 계산할 수 있다. SAM의 Torch allocated/reserved Peak는 각각3,400,269,824 / 4,815,060,992B다. FLUX의 Torch allocator Peak는 수집하지 않았다. 같은 GPU에서 순차 실행했고 소유 Child가 종료됐음을 확인했다.

## SAM3.1 — 실제 Adapter

기존 `sam31` / Ultralytics8.4.199 / `sam3.1_multiplex.pt`를 사용했다. checkpoint SHA256은 `0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6`이다. 모델 파라미터의 실제 dtype은 전부 `torch.float16`, `model.fp16=True`, `quantize=16`이었다. Adapter는 수정하지 않았다.

기존 `/home/hyeonhee/sam31_test/scene.png`는 Scene 파일12개와 같은 SHA여서 이번 입력에서 제외했다. 독립 PIL 합성 컵을 만들고 Text1회만 실행했다. Box `[236.25,152.25,562.0,384.75]`, bool Mask `[512,768]`, Confidence0.88623을 반환했다. Predictor가 실제 받은 BGR 배열은 입력 RGB의 채널 반전과 byte 단위로 일치했다. Stage3 후보/Stage5 raw mask의 Shape·Box·Confidence 저장 계약에 맞고, Overlay에서 컵의 본체·손잡이 선택을 확인했다.

[합성 입력](../workbench_runs/diagnostics/local_runtime_validation/sam/synthetic_cup.png) · [실제 SAM Overlay](../workbench_runs/diagnostics/local_runtime_validation/sam/overlay.png) · [결과 JSON](../workbench_runs/diagnostics/local_runtime_validation/sam/result.json)

합성 그림이므로 실제 사진 검출 정확도/Support 인식/물체 Identity를 인증하지 않는다. 실제 Point Forward는 **0회**, 이전 API 계약 검증만 재사용했다. Stage3 실제 Plane fitting·Stage5 pruning/SBERT Forward 전체는 수행하지 않았다. 종료 때 Adapter의 할당량8,519,680B가 잠시 남았지만 소유 프로세스 종료 후 GPU 예약은 반환됐다.

## FLUX — 실제 물체 제거 실패와 경계 비교

이전 색 변경과 같은 ComfyUI/GGUF Workflow·Offloading·20step을 사용했다. 모델 Revision/실제 경로/SHA는 Worker 결과에 있다. Prompt는 빨간 큐브와 그림자·초록 안내선을 제거하고 배경을 복원하도록 전달됐다. Object Removal의 실제 `image_edit` Worker를 사용했으며 사용자 사진·SAM Mask와 무관한 정확한 Synthetic Mask로 검증했다.

![원본 / 빈 배경 GT / 원시 출력 / 합성 방법 비교](../workbench_runs/diagnostics/local_runtime_validation/flux_removal/comparison.png)

**실제 결과에는 큐브와 그림자가 남았다.** 원시 출력의 빨간 픽셀19,244개, 입력18,343개이며 제거되지 않은 것이 육안으로도 확인된다. 기존 `removal_is_valid()`는 초록 안내선 잔존 검사여서 이 실패를 놓칠 수 있다. 이 단일 입력/설정의 실패 원인을 모델 자체나 특정 노드 하나로 확정하지 않는다. 이를 제거 성공으로 기록하지 않았다.

| CPU 합성 방법 | 원 Mask 밖 정확 보존 | 경계의 빈 배경 GT 대비 MAE(0–255 RGB) | 판단 |
|---|---|---:|---|
| 기존 Hard Mask | true | 47.17 | 큐브 잔존, 제거 실패 |
| 안쪽 Feather2px | true | 48.47 | 개선 없음 |
| 안쪽 Feather4px | true | 49.94 | 개선 없음 |
| 안쪽 Feather8px | true | 50.73 | 개선 없음 |
| Dilation5px + Hard | false(선언한 확대 영역 밖은 true) | 47.17 | 원 Mask 밖3,850픽셀 추가 변경, 제거 실패 |

원시 출력은 Mask 밖 배경도 GT 대비 MAE3.33만큼 바뀌고, 수평 나뭇결 위치도 조금 변했다. Hard 합성은 Mask 밖을 정확히 보존하지만 내부 큐브와 복원되지 않은 패턴을 해결하지 못한다. **Feather/Blur를 제품 기본값에 추가하지 않았다.** 실패한 배경 생성을 블렌딩으로 숨기지 않았고 Seed/Steps/모델 변경·추가 생성은 하지 않았다. 평가는 이 합성 배경의 비교이며 일반 Scene 품질 임계값으로 사용하지 않는다.

제품 Stage5에는 기존 VLM 호출 경계의 **명시적 제거 품질 확인**을 추가했다. 로컬 FLUX 결과는 안내선 검사 뒤에도 `{"removed":"yes","reason":"실제 영상 근거"}`를 받아야 Depth 단계로 진행한다. 부정/잘못된 응답은 NEEDS_REVIEW, Runtime/인증 누락은 기존 NEEDS_RUNTIME으로 남는다. 실제 VLM 호출은 이번에 하지 않았고 CPU 계약 테스트로만 확인했다. Worker의 COMPLETE는 RGB 생성 완료일 뿐 제거 품질 합격이 아니다.

## FLUX → PriorDepth 데이터 계약

기존 코드에서 FLUX RGB 합성은 원 Object Mask, Depth hole은 5px 확장 Mask여서 영역이 달랐다. **원래 있던 5px Dilation 수학을 공용 `removal_region()`으로 옮겨 같은 허용 영역을 RGB와 Z에 전달**했다. 새 정합 기준을 완화한 변경이 아니며, 편집 허용 영역과 원 Object Mask는 별도 파일이다. Feather는 추가하지 않았다.

`depth_inpainting_inputs()`는 실제 Stage5가 쓰는 경계다. 원본 RGB/Z, 생성 RGB, Generated Mask, Known prior, K, Pixel Frame·단위·Provenance를 저장하고 다음을 검사한다.

- RGB/Depth/Mask Grid 일치, 양수·유한 Z, 유효 K.
- 선언한 편집 영역 밖 RGB 불변, `prior==0`과 생성 허용 Mask 정확 일치.
- 알려진 Depth는 원 bytes/값 유지, 최종 PDA 결과에서 Known Depth 불변 검사 유지.
- FLUX 반환은 원 Pixel Grid로 복원하므로 K를 그대로 유지. Worker는 내부 처리 Resize Affine과 원시 출력 경로도 반환한다.

이번 실제 FLUX RGB를128×96으로 옮기는 CPU Replay에서 중심 Pixel Affine `A`와 `K_new=A@K_old`의 역투영 광선 일치를 확인했다. 기존 PDA 성공 출력은 해당 크기 배열로만 재사용했고, 새 hole은 이번 FLUX Mask를 변환한 것이다. **기존 PDA 출력이 이번 RGB에 대한 새 모델 예측이라고 주장하지 않는다.** Replay Mock1회, PriorDepth/DA3 Forward0회이며, 현재 제거 RGB 자체가 실패했으므로 새 Depth의 내용·물리 Scale 정확도는 NOT_TESTED다. PDA의 K는 입력 Grid 검증용이며 실제 API 내부 Calibration을 뜻하지 않는다. 생성 Depth는 estimated, 독립 Metric 검증과 calibrated Confidence는 없다.

[연결 계약 JSON](../workbench_runs/diagnostics/local_runtime_validation/depth_contract/result.json)

## Stage6와 Bria 필요 범위

현재 `prepare_objects()`의 실제 경로를 확인했다.

- **관측 Crop만 사용**: `upsample:false`, `infill:false`이면 원래 SAM Mask를 nearest alpha로 보존한 Context/Focus RGBA Crop을 만들며 Bria 호출이 없다. 이 지원 범위는 CPU Smoke에서 확인했다. 숨은 면 완성/업샘플/RemBG 정밀화를 했다고 표시하지 않는다.
- **Upsample**: 기본 `upsample:true`, `remove_background:true`면 생성 후 Bria를 호출한다. `remove_background:false`면 실행은 가능하지만 `alpha_source=NOT_REFINED`이며 정밀 Alpha를 생성했다고 하지 않는다.
- **Infill**: 현재 경로는 생성 후 Bria를 호출한다. 원 관측의 SAM Alpha를 새 형상에 그대로 씌우면 새로 생성한 영역을 잘라낼 수 있어 Bria와 동등하지 않다. 이번에 이 경로를 우회하지 않았다.

따라서 **관측 Crop 모드는 Bria 없이 성립하지만 현재 기본 생성/정밀 Alpha 경로는 Bria Runtime이 필요**하다. 설정을 몰래 관측 전용으로 바꾸지 않았다. 미설정 RemBG는 NEEDS_RUNTIME으로 남긴다.

필요 시 별도 CPU 환경 `r2s-rembg`, Bria `bria-rmbg-2.0.onnx`(1,024,331,469B), `rembg.remove/BriaRmBgSession/CPUExecutionProvider`를 기존 `background_remove` Worker에 연결한다. Bria custom 비상업 모델 조건/상업 계약은 [모델 조건](https://huggingface.co/briaai/RMBG-2.0)을 확인해야 한다. 이번에는 설치·다운로드하지 않았다. 기존 원본 SAM Alpha Crop과 원본 SimFoundry의 Bria 정밀화의 차이를 보존한다.

## Workspace Runtime 적용

실제 설정: [workbench_runs/runtime/reconstruction.yaml](../workbench_runs/runtime/reconstruction.yaml). 이전 파일이 없어 신규 작성했으며, 부재 기록과 Diff는 진단에 남겼다. `runtimes`만 저장하고 Scene/Input/Capture/Candidate 설정은 바꾸지 않았다. `automation.reconstruct`는 이 설치 기본값을 읽되 **Project/명시 설정이 우선**하고 중첩 사용자 경로도 보존한다. UI는 변경하지 않았고 기존 UI→CLI→reconstruct 경로에서 적용된다. Source refit 경로는 바꾸지 않았다.

| Runtime | 연결 |
|---|---|
| DA3 | 기존 da3 / b2359... Snapshot, Mixed loader 불변 |
| SAM | 기존 sam31 / multiplex.pt, FP16 quantize16 |
| RGB 편집 | r2s-comfy / 지정 GGUF·인코더·VAE / 기존 API Workflow |
| Depth Inpainting | r2s-prior-depth / 고정 패치 소스·vitl+vitb v1.0 Snapshot |
| Plane/CPD | r2s-cpd / Open3D·probreg CPU |
| Pruning | r2s-cpd / 로컬 SBERT Snapshot, Encoder 실제 Forward 미실행 |
| Codex/Blender | 기존 CLI 및 bwrap / 실제 `/home/hyeonhee/apps/blender/blender` |
| Physics/Simulator | 기존 lerobot-arena / 기존 Isaac USD source+bin Bootstrap |
| VLM | 기존 설치 Gemini Wrapper/SDK, 인증·모델 사용 가능성 NOT_QUERIED |
| RemBG/FoundationPose | 빈 Interpreter로 명시 NEEDS_RUNTIME, 자동 설치/대체 없음 |

실제 Runtime Import/Signature 일괄 검사는1회 했다. 모델 경계들은 통과했으나 USD 동적 라이브러리 누락으로 실패했다. 이 실패를 보존한 뒤 **해당 USD Import만1회** 재확인했고, 기존 `source/bin`을 Child의 `LD_LIBRARY_PATH`에 전달하자 통과했다. Physics/Kit는 초기화하지 않았다. 다른 모델 Import/Forward는 반복하지 않았다.

현재 상속된 `REAL2SIM_BLENDER`는 사라진 `/home/hyeonhee/apps/blender-5.2.2/blender`였다. Workspace의 `runtimes.blender.executable`로 실제 설치를 연결하고 해당 Reconstruction 실행 범위에서만 기존 환경 선택기를 적용·복원한다. 기존 환경변수 자체나 인증은 수정하지 않았다. Blender Runtime Identity에 실행 파일 SHA가 포함된다. Codex 계정/모델/Usage/로그인 기능은 바꾸지 않았다.

실제 모델 경로·SHA는 `configured-models.json`, 검증된 FLUX Manifest는 이전 `flux-models.json`과 이번 Worker 결과에서 일치한다. 인증키/토큰을 설정에 넣지 않았다. 설정 적용은 성공했지만 Auto Reconstruction을 실행하지 않았으므로 Stage 전체 성공의 근거는 아니다.

## 변경·테스트·보존

제품 변경: `stage_runtime.py`(Workspace 기본값·Blender 선택 범위), `automation.py`(기존 진입 연결/Identity), `inference.py`(소유 엔진 Child USD Bootstrap), `reconstruction_stages.py`(RGB/Z 공통 영역·명시 제거 리뷰), `calibration/decomposition.py`(기존 Dilation 공용화), `comfy_edit.py`(원시 결과·Affine/미검증 품질 출처), Runtime 예시 YAML. 모두 기존 모듈에서 수정했으며 Framework/Manager/별도 입력 폼을 추가하지 않았다. 신규 파일은 집중 테스트와 이 보고서다. `sam31_adapter.py`와 DA3 loader AST는 시작 상태와 동일하다.

실행 횟수:

- 실제 SAM Text1 / Point0, FLUX 제거1. DA3/PDA/CPD 신규 실행은 각각0.
- 새 CPU 집중 테스트 **고유5개 통과**: 초기3개 Green1회(그 안에 Stage3/5/6 Smoke1개), 추가 USD Bootstrap1개·Blender 선택1개는 각 별도 Green1회. RED는 미구현 계약2건과 Bootstrap/Blender 각1건으로 총4건을 기록한3개 호출이다. 전체 pytest 호출은 RED3+Green3=6회이며 전체 회귀를 호출한 것은 아니다.
- CPU 경계 합성 비교1회(5가지 후처리), 기존 PDA 배열 Replay1회. 모델 재생성 없음.
- Runtime 일괄 API/설정 검사1회 + 실패한 USD 경계만 재확인1회. Blender 파일 확인 뒤 동일 검사의 설정 적용을 이어갔으며 전체 모델 검사를 재실행하지 않았다.
- 변경 Python은 bytecode 없는 compile 검사, `git diff --check` 확인. 기존1,751개 통과 수치를 이번 변경의 전체 회귀로 표시하지 않는다.

Scene/Input/Capture/Candidate/Cache/Asset/Export **7,786개 시작 ledger를 종료 시 대조해 변경0·누락0·신규0**을 확인했다. Workspace Runtime 설정 추가는 이 보호 root 밖의 명시 요청된 변경이다. Git Index의 기존 staged 변경과 HEAD는 보존하고 Commit/Push/Merge하지 않았다.

진단: `workbench_runs/diagnostics/local_runtime_validation/`의 SAM/FLUX `result.json`, `resources.json`, CPU `quality.json`, 연결 계약·설정 Diff/Import 로그·보존 대조. 제품은 이 진단 폴더를 import하지 않는다. 남은 문제는 **FLUX의 실제 제거 품질 실패**, VLM 인증/실제 판단 미검증, 기본 생성 경로의 Bria 미설정이다. 실제 사용자 전체 Scene E2E는 이번에 수행하지 않았다.
