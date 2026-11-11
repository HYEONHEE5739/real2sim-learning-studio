# FLUX Object Removal 개선·Bria·VLM 검증

> 2026-11-10 후속: VLM은 공통 Codex CLI로 전환했고 MASt3R/COLMAP 실행 코드는 제거했다. 현재 설정과 검증 범위는 [Codex VLM 전환](codex-vlm-migration.md)을 따른다. 아래 과거 실행·설치 기록은 당시 상태다.


2026-11-10. `feat/simfoundry-style-reconstruction`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`. 기존 설치·Stage1–14를 유지했다. **직접 확인한 Prompt 손실을 수정한 뒤, 같은 합성 입력으로 FLUX를 1회만 실행했다. 큐브·그림자 제거는 개선됐지만 배경 선과 합성 경계가 남아 최종 품질은 NEEDS_REVIEW다.** 사용자 Scene E2E·승인 Export·Commit/Push/Merge는 실행하지 않았다.

| 항목 | 결과 | 실제 실행 여부 | 남은 문제 |
|---|---|---|---|
| Kontext Workflow | 설치 노드/저장 Workflow/공식 템플릿 대조 | 정적 검증 | 공식 템플릿과 Latent/해상도 차이는 아래 구분 |
| Mask Conditioning | **없음** — Mask는 후합성용, Annotation RGB만 Reference로 입력 | 기존 실제 입력 byte 비교 | 정확한 Mask-conditioned 모델이 아님 |
| Object Removal Prompt | **Worker의 덮어쓰기 오류 수정**, 문맥·ID·보존 대상 전달 | Unit + 수정 후 Forward1회 | 일반 Scene/동일 물체 다중 Instance 판별 미검증 |
| 기존 CPU 품질 분석 | GT 기준 전후 수치 비교 | CPU 비교1회 | 배경 선 이동·경계 불연속 |
| Mask-conditioned 대안 | Fill 모델/공식 노드/GGUF 존재 확인 | 소스·공개 메타데이터만 | 새 모델 다운로드0, 8GB 실행 미검증 |
| Bria RemBG | **동의 후 설치·Workspace 연결 완료** | CPU 합성1회 성공 | 실제 생성 Object/Stage6 연속 품질 미검증 |
| Gemini VLM | SDK Schema/Wrapper/오류·재시도 계약 확인 | 유료 요청0, SDK 구성 및 Mock | 인증 NEEDS_AUTH, 서비스/계정 가용성 미검증 |
| Stage5/6 연결 | 단계별 Provider 선택·증거 충돌 차단 | 짧은 Mock Smoke1회 | 실제 Stage 연속 실행 미검증 |
| FLUX 수정 후1회 추론 | RGB 생성·큐브/그림자 제거 성공 | 실제512px/20step/seed0/batch1 | 배경 품질 NEEDS_REVIEW, 추가 생성 없음 |

## 직접 확인한 오류와 추정 원인

**직접 오류:** Stage5가 전달한 `request.prompt`를 `comfy_edit.edit()`가 일반 제거 문장으로 덮어썼다. 이전 시험의 그림자·수평 나뭇결 복원 지시가 최종 `CLIPTextEncode`에 도달하지 않았다. `edit_prompt()`를 분리해 호출자의 문장을 유지하고 Annotation 방식, Object ID, 보존할 다른 Instance, Scene Memo를 데이터 문맥으로 전달한다. Stage5 자체 Prompt도 가려졌던 표면·질감·조명·원근과 그림자 제거를 명시한다. Python으로 Memo의 자연어를 다시 해석하지 않는다.

**재현 근거:** 새 Prompt 계약의 RED와 수정 후 GREEN, 이전 실제 Workflow의 Prompt와 새 Workflow 비교를 보존했다. 실제 GPU 비교에서 변경된 노드는 **3번 Positive Text뿐**이다. 모델·Seed0·20step·CFG1·Denoise1·해상도512·입력·Mask·GT·Offloading은 그대로다. 해당 시험의 개선과 Prompt 수정의 관계를 지지하지만 임의 Scene에서 항상 제거가 성공한다고 일반화하지 않는다.

**확정하지 않은 원인:** 모델의 일반적인 편집 한계, 512px 예산, 원시 배경 패턴 이동의 세부 원인을 특정하지 않았다. 실패를 Feathering이나 재생성 반복으로 숨기지 않았다.

## 공식 Workflow 및 실제 데이터 흐름

[공식 Kontext 안내](https://docs.comfy.org/tutorials/flux/flux-1-kontext-dev)와 [공식 JSON 템플릿](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/flux_kontext_dev_basic.json)을 읽고, 설치된 ComfyUI/GGUF 소스와 비교했다. 조회한 템플릿 bytes와 SHA는 Git 제외 진단 `sources/official-kontext.json`, `official-kontext-source.json`에 있다.

| 지점 | 현재 구현 | 공식 템플릿과의 비교·판정 |
|---|---|---|
| Transformer | `UnetLoaderGGUF` + 기존 Q4_K_S | 공식은 일반 Loader. QuantStack의 Kontext 변환 모델·기존 검증 SHA 재사용 |
| Encoders/VAE | CLIP-L + scaled FP8 T5 + ae | 공식의 선택 파일과 일치, CPU 실행은 로컬 예산 정책 |
| Reference | `VAEEncode → ReferenceLatent` | 실제 RGB 참조가 연결됨 |
| Conditioning | 로컬은 Guidance→ReferenceLatent | 공식은 ReferenceLatent→Guidance. 서로 다른 Conditioning 항목을 추가하며, 차이를 실패 원인으로 확정하지 않음 |
| Sampling Latent | 로컬 EmptySD3LatentImage | 조회한 공식은 VAEEncode Latent. 두 경로 모두 Denoise1; 이번에는 바꾸지 않아 원인을 혼합하지 않음 |
| Sampling 값 | CFG1 / Euler / simple /20step / Denoise1 / Guidance2.5 | 공식과 동일한 해당 값, Seed는 고정 비교 |
| Resize | 로컬 최대512, crop 없이 비율 유지·16배수 | 공식 FluxKontextImageScale의 약1MP와 다름. 8GB/이번512px 지시 때문에 확대하지 않음 |
| Positive/Negative | Positive Text→Reference/Guidance→Sampler, Negative ZeroOut | Text 연결 정상, 직접 발견한 오류는 Text 내용 덮어쓰기 |
| Mask | 모델 입력 Socket에 연결되지 않음 | 기본 공식 Kontext도 명시 Mask Conditioning 경로가 아님 |
| Output | SaveImage의 실제 파일→원시 출력 보존→원본 보호 합성 | 다른 이미지로 교체되지 않음. 반환 경로/Shape·raw_path 확인 |

GGUF 헤더만 읽어 `img_in.weight`가 GGUF 차원 순서 `[64,3072]`임을 확인했고 가중치를 GPU에 추가 로딩하지 않았다. 설치 소스·모델 ID·SHA·헤더가 현재 Kontext 선택과 일치한다. 이것을 Fill 모델의 Mask 입력 구조로 해석하지 않는다.

실제 경로:

```text
원 RGB + Object Mask/ID + Scene Memo
  → Stage5 Annotation RGB(초록 outline/mask/bbox)
  → edit_prompt(명시 지시·보존 대상·문맥)
  → RGB Resize → VAEEncode → ReferenceLatent + Text → Kontext
  → Raw RGB 보존 → 명시 Removal Region 안만 합성
  → 픽셀 증거 + 구조화 VLM 검토
  → 모두 유효할 때만 같은 Region의 Depth hole → PriorDepth
```

이전 실제 `comfy_input/input.png`는 `annotated_rgb.png`와 byte 일치하며 초록 픽셀을 포함했다. 따라서 “Annotation을 모델이 보지 못했다”는 가설은 배제했다. **Object Mask 자체는 모델 Conditioning에 전달되지 않는다.** Synthetic Mask에는 이미 그림자 영역이 포함돼 있다. 실제 SAM Mask에 그림자가 자동 포함된다고 가정하지 않는다. 기존5px 확장 영역도 그림자 추론이나 독립 가림 검증이 아니다.

## 수정 후 실제1회 결과와 CPU 비교

![원본·GT·이전 실패·수정 결과·합성·Mask](../workbench_runs/diagnostics/flux_inpainting_validation/comparison.png)

| GT 기준 지표 | 이전 합성 | 수정 후 합성 |
|---|---:|---:|
| 빨간 Object 픽셀 | 18,628 | **0** |
| Object 영역 RGB MAE | 68.92 | **4.04** |
| 그림자 영역 RGB MAE | 31.59 | **2.25** |
| 제거 영역 RGB MAE | 58.46 | **3.54** |
| 경계 Gradient 오차 | 44.65 | **3.21** |
| 원 Mask 밖 원본 byte 일치 | true | true |

원시 출력의 빨간 픽셀도19,244→0이다. 육안으로 큐브와 그림자가 사라졌다. 다만 원시 출력의 나뭇결 선이 이동했고 합성 결과에서는 기존 선과 이어지지 않는다. 합성본의 선 주변 GT 오차도 남았다. **제거 자체는 개선, 배경 구조·경계 품질은 검토 필요**로 구분한다. 다른 Object는 이 Fixture에 없으므로 보존 정확도는 NOT_APPLICABLE이며 일반 다중 Object 성공으로 보고하지 않는다. 수치들은 이 GT가 있는 Synthetic Case의 진단이며 제품의 일반 성공 임계값으로 하드코딩하지 않았다. 이전 Feather/Dilation 비교는 보존된 결과만 재사용하고 제품 기본값은 바꾸지 않았다.

| 실제 자원 | 수정 후1회 |
|---|---:|
| Worker 전체 시간 | 120.744s |
| Comfy Prompt 시간 | 103.97s |
| 전체 GPU 관측 Peak | 6,562MiB |
| 소유 프로세스 GPU 관측 Peak | 6,062MiB |
| RSS 합 관측 Peak | 15,105,650,688B ≈14.07GiB |
| PSS 합 관측 Peak | 14,663,947,264B ≈13.66GiB |
| 종료 후 전체 GPU | 456MiB |
| OOM / Timeout / 추가 GPU 재시도 | 없음 / 없음 /0회 |

표본은 약150ms+조회 비용, PSS는 매5번째 표본이다. 전체 GPU는 배경 사용을 포함하고 RSS는 공유 Page를 중복 셀 수 있다. Torch allocator Peak는 따로 측정하지 않았다. 원시·합성 RGB는 generated/estimated이며 실측 RGB가 아니다. 해당 결과를 PriorDepth에 실제 전달하거나 Stage5 전체 루프를 실행하지 않았다.

## 성공 판정과 Stage5/6 Provider

`removed=yes`만으로는 통과하지 않는다. 로컬 제거는 다음 증거가 필요하다.

- 실제 원시/합성 RGB·Object Mask·Removal Region 파일과 일관된 Pixel Grid.
- Object Mask가 허용 Region 안에 있고, 해당 영역이 실제 변했으며 비편집 픽셀은 정확히 보존됨.
- VLM의 `removed`, `object_remaining`, `other_objects_preserved`, `background_continuous`, `uncertain`, `reason`, `evidence`가 모두 유효하고 서로 모순되지 않음.

이미지 미존재·복사된 원본·비편집 영역 변경·불명확한 판단은 NEEDS_REVIEW다. 단순 픽셀 변화는 Object 부재의 독립 증명이 아니며, 이번에는 추가 SAM Forward로 검출하지 않았다. VLM+픽셀 검사는 필요한 Gate이지 물리·기하 정확도 인증은 아니다. 실패 RGB를 정상 결과로 Depth 단계에 넘기는 경로는 Mock Smoke에서 차단했다.

기존 `image_edit` 인터페이스를 유지하면서 선택적 **`runtimes.image_edit_removal`(Stage5), `runtimes.image_edit_objects`(Stage6)**를 추가했다. 각 Override는 기존과 같은 완전한 Runtime spec이다. 없으면 `runtimes.image_edit`를 사용한다. Backend를 몰래 바꾸지 않으며 단계별 Identity에도 해당 선택이 들어간다. 실제 Workspace의 이미지 Provider 선택은 바꾸지 않았고 예시 YAML에 분리 방법만 기록했다. 이후 Bria 동의 뒤에는 승인된 rembg 키만 설치 경로로 연결했다.

## Mask-conditioned 대안

현재 Kontext에 Mask Socket만 추가해 Fill로 바꿀 수 있다는 근거는 없다. [공식 Fill Workflow](https://docs.comfy.org/tutorials/flux/flux-1-fill-dev)는 별도 [FLUX.1-Fill-dev](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev) 가중치와 Image/Mask를 받는 Inpaint Conditioning을 사용한다. 설치 ComfyUI의 `InpaintModelConditioning`은 concat latent/mask와 noise mask를 만들지만, 그 노드의 존재만으로 현재 Kontext가 해당 trained conditioning을 소비한다고 가정하지 않는다. 단순 Latent noise-mask 제한도 Fill과 동등한 검증 결과가 아니다.

추가 모델 후보는 [YarvixPA/FLUX.1-Fill-dev-GGUF](https://huggingface.co/YarvixPA/FLUX.1-Fill-dev-GGUF) @`78b83f1da140a4dcd6466580516544e1f6effe3e`, `flux1-fill-dev-Q4_K_S.gguf` **6,809,920,800B**다. 변환 배포자는 [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) 사용을 안내한다. 기존 CLIP-L/T5/VAE를 재사용할 수 있는 구조이나 정확한 로컬 결합·8GB Peak/RAM 성공은 **UNKNOWN**이다. 원본 가중치는 별도23,804,922,408B이며 이번에는 어느 것도 받지 않았다. 원본 FLUX dev 비상업 라이선스/접근 조건은 변환 후에도 유지된다.

정확한 Mask 제어가 필요하면 별도 Fill 경로가 검토 대상이지만, 이번 결과만으로 새 대형 모델 도입이 필수라고 확정하지 않는다. Kontext Prompt 수정으로 제거는 개선됐고 배경 품질 검토는 남는다. 검증되지 않은 Fill Adapter/새 양자화/CPU Offload 알고리즘을 구현하지 않았다.

## Bria RemBG — 명시 동의 후 설치·연결 완료

Stage6는 관측 Crop만이면 원 SAM Alpha로 동작하지만, 기존 Infill 및 기본 Upsampling 뒤 정밀 Alpha 경로는 `background_remove`를 호출한다. 생성 형상에 원 관측 Mask를 그대로 씌우는 것은 Bria 정밀화와 같지 않으므로 이 경로를 우회하지 않았다.

[Bria 모델 조건](https://huggingface.co/briaai/RMBG-2.0)을 확인한 사용자가 **“Bria 조건을 확인했고 비상업 연구·평가용 사용에 동의”**라고 명시한 뒤 설치했다. 이전 FLUX 동의로 대체하지 않았으며 동의 기록은 `bria-consent.json`에 있다. [공식 RemBG Bria Session](https://github.com/danielgatis/rembg/blob/main/rembg/sessions/bria_rmbg.py)이 사용하는 공개 Release 파일을 받았고 HF 로그인/접근 동의를 우회하지 않았다.

- 새 환경: `r2s-rembg`, Python3.12.16 / RemBG2.0.87 / ONNX Runtime1.31.1 / NumPy2.5.4. 기존 환경에는 패키지를 설치하지 않았다.
- 모델: `/home/hyeonhee/.local/share/real2sim-runtime/models/bria-rmbg-2.0.onnx`, **1,024,331,469B**, SHA256 `5b486f08200f513f460da46dd701db5fbb47d79b4be4b708a19444bcd4e79958`. 본체는 한 경로에만 보관하며 Worker 자동 다운로드는 없다.
- 별도 API Import/Signature 및 `CPUExecutionProvider` 존재를 확인했다. 새 Conda 환경의 선택 IPython/Jupyter 의존성 누락은 `psutil/pygments/python-dateutil`만 추가해 해소했고 최종 `pip check`는 성공했다.
- 실제 Worker는 **CPUExecutionProvider만** 사용했다. 사용 가능한 Provider 목록에 Azure가 있다는 사실은 Azure 서비스 호출이나 GPU 실행을 뜻하지 않는다.

작은 독립 Synthetic Cup 입력으로 `stage_workers.py --worker background_remove`를 **1회** 실행했다. 입력은 이전 독립 SAM 시험의 합성 그림이며 Scene 사진·신규 FLUX 생성은 사용하지 않았다. Worker의 최대 변512px 전처리와 기존 Bria Session 내부1024px 정규화를 사용한 뒤 원래 해상도로 Alpha를 복원했다.

| 실제 결과 | 값 |
|---|---:|
| Worker | COMPLETE / exit0 |
| 전체 Child 시간(Import·모델 로딩·추론·SHA·저장 포함) | 53.942s |
| 소유 프로세스 GPU 관측 Peak | 0MiB |
| 전체 시스템 GPU 관측 Peak | 448MiB — 배경 프로세스 사용 |
| RSS 관측 Peak | 9,961,820,160B ≈9.28GiB |
| PSS 관측 Peak | 9,958,426,624B ≈9.27GiB |
| 반환 | RGBA768×512, 유한 Alpha0–255 |
| 원본 RGB / 해상도 보존 | true / true |
| OOM / Timeout / 재추론 | 없음 / 없음 /0회 |

![Bria 합성 컵 입력 / Alpha / RGBA 비교](../workbench_runs/diagnostics/flux_inpainting_validation/bria/comparison.png)

컵 본체·손잡이를 남기고 배경·테이블·그림자가 제거된 것을 육안 확인했다. 이 합성 입력의 Alpha 실행/형식 검증이며 실제 생성 형상 전체의 정밀 Alpha나 실측 Mask 정확도를 인증하지 않는다. Numba는 설치된 TBB 버전을 이유로 해당 선택 threading layer를 비활성화하는 경고를 남겼지만 ONNX CPU 추론은 완료됐다. TBB를 임의 업그레이드하거나 모델 재추론으로 반복하지 않았다.

기존 Workspace 설정을 백업하고 **`runtimes.rembg`만** 설치 Python/모델 경로와300초 Timeout으로 병합했다. 다른 Runtime 및 Project 입력·Calibration은 그대로이며 `bria-runtime-application.json`과 `workspace-runtime-bria.diff`에 근거가 있다. 기존 Stage6 `background_remove`가 이 경계를 재사용한다. 전체 Stage6 생성 루프/Auto Reconstruction은 실행하지 않았다. `alpha_source`는 generated-image Bria refinement이며 원본 SAM Mask와 구분한다.

## Gemini VLM — 무료 로컬 계약 확인, 실제 요청0

설치된 `google-genai==3.0.0`, 고정 SimFoundry Wrapper를 조사했다. 설정 `gemini-3.1-pro-preview`는 Wrapper의 허용 목록과 [공식 모델 안내](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview)에 있는 이미지 입력·텍스트/구조화 출력 모델이다. **현재 계정·지역에서 사용 가능한지는 확인하지 않았다.** 환경 API Key/ADC 경로 설정·기본 ADC 파일이 확인되지 않아 NEEDS_AUTH로 기록했다. 자격정보 내용·인증 토큰을 읽거나 출력·생성하지 않았다.

기존 Wrapper의 RGB/Prompt/인증/Cache를 재사용한다. 제거 검토에 한해 작은 lazy client adapter가 SDK `GenerateContentConfig`에 JSON MIME과 `response_json_schema`를 넣는다. Schema는 Prompt/Cache Identity에도 들어가 옛 응답이 새 계약으로 재사용되지 않는다. [공식 Structured Output](https://ai.google.dev/gemini-api/docs/structured-output)을 참고했고, 실제 설치 SDK에서 해당 설정을 생성·검증했다. 서비스가 응답을 준 시험은 아니다.

원본 Wrapper는 `n_retries=1`이어도 HTTP429에 예산을8회로 늘린다. 이를 읽기/실패 계약 테스트로 확인해 **소유 Child 안에서만 상한1**로 제한했다. 설치 원본은 수정하지 않았다. SDK Timeout과 기존 부모 Stop/Timeout/Process Group 경계를 유지한다. Wrapper가 감싼 예외의 원인 체인에서401/403/429를 분류하고, 원격 오류 원문은 Project 로그에 남기지 않는다.

성공 응답이 있을 때 반환 Token 사용량만 노출할 수 있게 했다. `cost=null`이며 가격·결제계정 조회나 비용 추정을 하지 않는다. SDK+Wrapper Mock에서 Schema 전달, 이미지 목록, 불명확한 판단 거부, Token metadata, 인증 오류 분류를 확인했다. 실제 Gemini 유료/무료 서비스 요청은0회다. Stage8의 별도 원본 front Wrapper 등 모든 VLM 분기를 실제 실행했다고 주장하지 않는다.

## 변경·검증·보존

수정 함수/파일:

- `comfy_edit.py`: `edit_prompt`, `edit` — 명시 지시 보존·Mask Conditioning 부재 표시.
- `reconstruction_stages.py`: 제거 Prompt/문맥·단계 역할, `removal_evidence/removal_review_schema/reviewed_removal` — 픽셀·판단 충돌 Gate.
- `stage_runtime.py`: `runtime_key/identity/invoke`, `automation.py`: 단계별 Provider Identity.
- `stage_workers.py`: 기존 Gemini의 Schema/사용량/제한·예외 원인 분류, Bria 실제 모델/Provider/Alpha provenance.
- Runtime 예시 YAML, 관련 기존 테스트 계약과 신규 `test_flux_removal_contracts.py`, 이 보고서/최신 기록 링크.

이번 검사: 계약 테스트3개, SDK 대역+Stage5/6 Mock Smoke2개, 인증 예외1개,429 예산1개 — **고유7개 통과**. 초기 Prompt/경로/증거 계약의 RED3건과429 예산 RED1건은 보존했다. 전체 pytest/Stage1–14 E2E는 실행하지 않았다. 실제 FLUX Forward1회, CPU 전후 품질 비교1회, GGUF 헤더·Workflow 정적 검사, SDK 로컬 Schema 구성 확인만 수행했다. SAM/DA3/PDA/CPD 추가 실행0, 동의 후 Bria CPU 실행1회, Gemini 서비스 요청0, Isaac/하드웨어0이다. Bria 설치 뒤 추가 GPU 실행이나 pytest 재실행은 하지 않았다.

신규 대형 Inpainting 모델 다운로드0B, Bria 동의 후 승인 ONNX1,024,331,469B·신규 CPU 환경1개(`du` 기준821M)를 준비했다. Wheel/Conda Cache와 공유 파일을 포함한 총 디스크 증감은 이 합계와 다를 수 있으며 최종 파일시스템 여유는 약24G였다. 기존 환경 패키지 설치/업그레이드는0이다. 기존 Scene/Asset 및 직전 진단 root의 **7,901개 시작 파일을 종료 시 SHA/크기 대조해 변경0·누락0·신규0**을 확인했다. Git Index와 HEAD를 보존하고 실제 Workspace Runtime은 승인된 rembg 키만 바꿨으며 다른 설정은 그대로다. Commit/Push/Merge하지 않는다.

진단: `workbench_runs/diagnostics/flux_inpainting_validation/`의 `workflow-static.json`, `quality.json`, `comparison.png`, `flux/result.json/resources.json`, SDK 준비·Schema JSON, RED/GREEN/Smoke 로그, 보존 대조. 제품은 이 폴더를 import하지 않는다. 남은 Blocker는 **배경 패턴/경계 품질, Gemini 인증/실제 판단 미검증, 실제 생성 Object의 Stage6 Alpha 품질 미검증**이다. 전체 사용자 Reconstruction은 실행하지 않았다.
