# SimFoundry Runtime — SAM3.1 / ComfyUI GGUF / PriorDepth / CPU CPD

> 2026-11-10 후속: VLM은 공통 Codex CLI로 전환했고 MASt3R/COLMAP 실행 코드는 제거했다. 현재 설정과 검증 범위는 [Codex VLM 전환](codex-vlm-migration.md)을 따른다. 아래 과거 실행·설치 기록은 당시 상태다.


**후속(2026-11-10):** FLUX Prompt 손실 수정 후 큐브/그림자 제거는 개선됐으나 배경 경계는 NEEDS_REVIEW다. Bria는 별도 명시 동의 뒤 CPU 환경·ONNX 설치, 합성1회 및 Workspace rembg 연결을 마쳤다. 아래는 당시 기록이며 최신 범위/수치는 [FLUX·Bria·VLM 후속 검증](flux-inpainting-validation.md)을 따른다.


**2026-11-10 후속 검증:** 신규 SAM3.1 Adapter 실제 Text1회는 성공했고, FLUX 실제 Object Removal1회는 호출 성공/품질 불합격(큐브 잔존)이었다. RGB→Depth 공통 영역 계약과 Workspace Runtime을 연결했다. 아래 설치·색 변경 시험은 당시 기록이며 최신 결과·Bria 범위·실제 설정 적용은 [로컬 Runtime 검증](local-runtime-validation.md)을 따른다. 전체 Scene E2E는 실행하지 않았다.

2026-11-10. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`. 최신 사용자 첨부 지시를 적용했다. 앞선 조사에서 권고했던 **새 공식 SAM3 환경/가중치 설치는 채택하지 않고 기존 Ultralytics SAM3.1을 재사용**한다. 이전 조사 문서는 이번 작업 시작 시 Git 제외 진단 백업에 보존했다.

**SAM3.1 어댑터와 로컬 편집 Worker를 연결하고, PriorDepth와 CPU CPD의 작은 실제 실행은 각각 1회 성공했다. 사용자가 FLUX 라이선스 동의와 진행을 명시했고, 지정 Q4 GGUF·CLIP·T5·VAE의 다운로드/SHA 검증 및 512px 합성 편집 1회도 성공했다. 전체 통합 완료나 사용자 Scene 완성으로 보고하지 않는다.**

Stage1–14, Scene Prepare UI, Candidate/Source/Checkpoint, Codex 계정·모델·사용량, 기존 Real/Sim 경로를 유지한다. 기존 `da3`, `sam31`, `lerobot-arena`에 패키지를 설치하거나 업그레이드하지 않았다. 실제 사용자 이미지 E2E, DA3/SAM 기존 추론 반복, 전체 pytest, Isaac/로봇 구동 및 Commit/Push/Merge는 수행하지 않았다.

## 현재 구성과 실제 검증

| 구성 / Stage | 설치 환경 | API 연결 | 실제 실행 | 남은 조건 |
|---|---|---|---|---|
| DA3 / 2, 5 | 기존 `da3` 유지 | 기존 Mixed loader 유지 | 이번 미실행, 과거 성공 근거만 유지 | 새 구성에서 전체 연결 미검증 |
| SAM3.1 / 3, 5 | 기존 `sam31`, `sam3.1_multiplex.pt` | Ultralytics Text/Point 어댑터 + 별도 CPU 후처리 | Predictor 대역을 이용한 입출력 계약, 기존 실제 추론 반복 없음 | 새 어댑터의 실제 모델 Forward는 미검증 |
| FLUX / 5, 6 | 신규 `r2s-comfy`, ComfyUI + GGUF 노드 | localhost API Workflow/Job/상태/결과/Stop/해제 연결 | 필수 노드 13종 확인 및 실제512px 합성 편집 **1회 성공** | 실제 제거/Infill/Upsampling 및 기하 보존 품질은 미검증 |
| PriorDepth / 5 | 신규 `r2s-prior-depth` | 고정 소스 + NVIDIA patch, 명시 checkpoint binding | 합성 RGB128×96 / prior / geometric Z 추론 **1회 성공** | 큰 처리 해상도·실제 생성 RGB 품질/Scale 정확도는 미검증 |
| probreg / 8 | 신규 `r2s-cpd`, CPU | 실제 Signature와 기존 Worker 일치 | 작은 비대칭 합성 점군 CPD **1회 성공** | Native Mesh 다중 시작 전체 실행·실제 관측 정확도는 미검증 |
| Codex+Blender / 7 | 기존 유지 | 기존 Sandbox 경로 | 이번 제작 미실행 | 원격 호출·실제 Asset 제작 별도 검증 |
| MuJoCo/Isaac / 12, 14 | 기존 유지 | 기존 Camera 역할·Child 유지 | 이번 시뮬레이터 미실행 | 별도 검증, Side/Wrist만 기본 센서 |

## Stage별 실행 경계

- `automation.reconstruct → _run_stage_pipeline → stage_runtime.invoke → inference._run_worker`를 유지한다. 별도 앱/Manager/실행 프레임워크는 추가하지 않았다.
- Stage3 `support`는 **`support_masks`(sam31 GPU) → 종료 → `support_planes`(r2s-cpd CPU/Open3D)** 순서다. 원래 1cm RANSAC과 2000/1000회 Plane 수학은 유지한다.
- Stage5 `segments`는 **`segments_raw`(sam31 GPU) → 종료 → `segments_post`(r2s-cpd CPU/SBERT/pruning/association)** 순서다. SBERT는 처음부터 CPU에서 명시 Snapshot을 로딩한다. 기존 Mask pruning·분리·모호한 Identity 거부는 유지한다.
- 나뉜 Child도 기존 `call` Provider의 Worker Cache를 통한다. CPU 후처리 누락으로 실패한 경우 완료된 SAM 결과를 재사용할 수 있으며, SHA/Manifest가 맞지 않으면 사용하지 않는다. Stage5 runtime identity에 `segments`와 CPU 후처리 설정을 포함한다.
- 원본 Stage5 전체 파일을 import하던 `removal`을 제거했다. 고정 소스의 denoise·Hull/ray 순서·cycle-safe support-level 수학을 기존 `calibration/decomposition.py`에 포트했다. GPU SAM, 공식 `sam3`, PDA, CLIP의 불필요한 전이 import를 하지 않는다. 수학/임계값은 유지하고 의존성 import만 분리했다. 사용하지 않는 원본 시각화 helper는 Worker 인터페이스가 아니다.
- GPU Child는 기존 소유 Process Group과 Timeout/Stop을 사용한다. Builder의 모델·Simulator Child는 사용자별 파일 잠금으로 직렬화한다. DA3/SAM3.1/FLUX/PDA를 동시에 유지하지 않는다. 다른 앱이 사용하는 GPU까지 이 잠금이 통제하는 것은 아니다.
- DA3의 기존 Mixed dtype 정책과 예산은 유지한다. 새 경계의 최소 free VRAM은 SAM4096/PDA5120/FLUX6144MiB이며, 설정으로 더 높일 수 있다. 이 Gate는 실측 Peak나 성공 보장이 아니다.

## SAM3.1 어댑터

[sam31_adapter.py](../real2sim_builder/src/real2sim_builder/sam31_adapter.py)는 설치된 Ultralytics8.4.199의 `SAM3SemanticPredictor`, `SAM3Predictor`를 사용한다. 기존 환경과 `/home/hyeonhee/sam31_test/sam3.1_multiplex.pt`를 재사용하며 `half=True`, **`quantize=16`**, batch1 정책을 명시한다. 실제 설치 소스는 FP16 선택에 `quantize`를 사용하므로 half만 켰다고 FP16 성공으로 간주하지 않는다.

PIL RGB를 Ultralytics ndarray 입력의 BGR로 한 번 변환한다. 반환 Mask가 공급된 upright RGB 해상도와 다르면 resize로 숨기지 않고 거부한다. Mask/Box/Confidence와 checkpoint SHA·패키지 버전·좌표계·추정 provenance를 기록한다. Text 탐지의 후보 순서가 Object ID가 되지 않으며, 기존 일대일 기하 대응이 모호하면 AMBIGUOUS다.

Point는 하나의 Object에 대한 여러 positive/negative hint를 한 묶음으로 전달한다. **Ultralytics의 공개 Point API와 원본 SAM3의 세션/`multimask_output` API는 동일하지 않다.** 후보 반환을 활용하되 원본과 같은 Interactive 상태나 후보 개수를 보장하지 않는다. 이번에는 실제 SAM Forward를 반복하지 않았다. 입력 색·좌표·Point 묶음·Confidence 계약만 Predictor 대역으로 확인했다.

## FLUX ComfyUI GGUF 연결

소스:

- ComfyUI: `61e524bdba7a4e193b45c2697f1af83c1beb86d6`
- city96/ComfyUI-GGUF: `6ea2651e7df66d7585f6ffee804b20e92fb38b8a`
- 설치 위치: `/home/hyeonhee/.local/share/real2sim-runtime/src/ComfyUI`
- 환경: `r2s-comfy` (기존 da3를 새 이름으로 복제한 뒤 이 환경에만 필요한 Comfy 패키지 추가)

`diffusers`를 새로 설치하는 경로를 추가하지 않았다. ComfyUI/GGUF의 실제 requirements를 사용했고 기존 Torch2.7.1+cu126은 새 환경에서도 유지됐다. ComfyUI가 요구하는 frontend/template wheel도 설치돼 디스크 사용량에 포함된다. `pip check`는 성공했다.

[버전 관리 API Workflow](../real2sim_builder/config/flux-kontext-gguf.api.json)와 [comfy_edit.py](../real2sim_builder/src/real2sim_builder/comfy_edit.py)를 Stage5/6가 공용으로 사용한다. `UnetLoaderGGUF → DualCLIPLoader(CPU) → CLIPTextEncode → FluxGuidance → ReferenceLatent(VAEEncode reference) → KSampler(empty batch1 latent) → VAEDecode → SaveImage`다. Kontext 참조 Conditioning을 사용하며, 입력 Latent를 일반 img2img처럼 denoise하는 것으로 대체하지 않는다.

Worker가 **자신의 ComfyUI 서버만** `127.0.0.1`의 빈 포트에 실행한다. 기존 사용자의 서버·Queue에 접속하거나 종료하지 않는다. `--offline --lowvram --reserve-vram 1 --cpu-vae`, batch1/최대512px, custom node는 GGUF만 허용한다. HTTP Proxy를 사용하지 않는다. 모델 파일·API 노드·모델 Catalog 검증 후 `/prompt`로 제출하고 Job ID와 `/history` 상태를 기록한다. 생성 RGB 크기와 Output 경로를 검증한다. 종료 때 `/interrupt`, `/free`를 요청하고 소유 서버를 terminate/kill하여 상주 모델을 남기지 않는다. 부모 Stop/Timeout은 동일 Process Group 전체를 종료한다.

FLUX 자체가 정확한 Mask를 지키는 모델이라고 가정하지 않는다. Stage5는 원본 RGB와 annotation RGB를 별도로 전달한다. 생성 RGB를 원래 해상도로 옮긴 뒤 **Mask 밖 픽셀은 annotation 없는 원본에서 byte 단위로 복사**한다. 그 안쪽만 합성 RGB를 사용하며 원본 관측으로 표시하지 않는다. Stage6의 전체 Crop 생성은 전체 합성으로 기록한다. 현재 경계 블렌딩은 추가하지 않았다. Mask 바깥 보호는 실제 512px 합성 편집에서도 byte 일치를 확인했다. 색 변경은 관찰했으나 원시 출력의 큐브 크기/윤곽도 달라졌고 보호 합성본에 Mask 경계 절단 흔적이 남았다. 이는 모델 로딩/호출 성공이며 실제 Object 제거·기하 보존 품질 검증은 아니다.

### 선택 모델·용량·라이선스 — 동의 후 지정 파일 설치 완료

| 역할 | 출처 / 고정 Revision | 파일 | Bytes | 상태 |
|---|---|---|---:|---|
| Q4 transformer | QuantStack/FLUX.1-Kontext-dev-GGUF @2d083027732f81e5548620b57ac47da22d30aa5a | flux1-kontext-dev-Q4_K_S.gguf | 6,797,337,888 | 설치·SHA 검증 완료 |
| CLIP | comfyanonymous/flux_text_encoders @6af2a98e3f615bdfa612fbd85da93d1ed5f69ef5 | clip_l.safetensors | 246,144,152 | 설치·SHA 검증 완료 |
| T5 | 같은 저장소/Revision | t5xxl_fp8_e4m3fn_scaled.safetensors | 5,157,348,688 | 설치·SHA 검증 완료 |
| VAE | Comfy-Org/Lumina-Image-2 @5b072540ef86570fecb8249c505f23d5bdeb88cd | split_files/vae/ae.safetensors | 335,304,388 | 설치·SHA 검증 완료 |

선택 네 파일 합계 **12,536,135,116B ≈12.54GB**. 전체 저장소·Q3 대체 모델·FP16 T5를 받지 않는다. VAE는 ComfyUI 공식 Kontext 튜토리얼이 연결한 파일이며 SHA256 `afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38`가 BFL 배포 VAE와 같다. 공개 파일 메타데이터와 SHA는 진단 `flux-download-plan.json`에 기록했다.

[QuantStack 모델 카드](https://huggingface.co/QuantStack/FLUX.1-Kontext-dev-GGUF)는 원본의 사용 제한이 유지됨을 명시한다. [BFL FLUX.1 Kontext-dev 라이선스](https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev/blob/main/LICENSE.md)를 확인한 사용자의 비상업 연구·평가용 사용 동의가 필요하다. GGUF 저장소가 ungated인 것을 동의로 간주하지 않는다. 첨부 §3의 요청에 따라 동의를 질문했고, 사용자가 “라이선스 동의 했지? 어 계속 진행해”라고 명시한 뒤에만 지정한 네 파일을 다운로드했다. 동의 기록은 진단 `flux-license-consent.json`에 있다. 토큰 없이 공개 파일을 받았으며 접근 절차를 우회하지 않았다. CLIP/T5와 해당 VAE 배포 메타데이터는 Apache2지만 FLUX transformer의 조건을 대체하지 않는다.

[공식 ComfyUI Kontext 안내](https://docs.comfy.org/tutorials/flux/flux-1-kontext-dev), [GGUF 노드](https://github.com/city96/ComfyUI-GGUF), [텍스트 인코더 배포](https://huggingface.co/comfyanonymous/flux_text_encoders), [VAE 배포](https://huggingface.co/Comfy-Org/Lumina-Image-2/blob/main/split_files/vae/ae.safetensors)가 근거다. 위 Revision·파일만 준비해 SHA와 노드 Catalog를 확인한 뒤 합성512px 편집을 **1회** 실행했고 성공했다. Q3/FP16 T5/다른 Transformer를 추가 다운로드하지 않았다. HF Cache와 Comfy 모델 경로는 같은 inode의 하드링크여서 가중치 본체를 복사하지 않았다. 이 단일 512px 실행의 실측은 아래 후속 결과에 기록한다.

## PriorDepthAnything

별도 `r2s-prior-depth`는 기존 da3를 새 이름으로 복제해 Torch2.7.1+cu126/NumPy1.26.4를 재사용했다. 고정 PDA `8c029cbca669443fe0bbf8dcefb5f91ad531084d`에 고정 SimFoundry `9e34ebefcd020583fbb755a8b57268dce78eca26`의 `PriorDepthAnything.patch`를 check/apply했다. `--no-deps -e` 설치 후 실제 필요한 `torch_cluster==1.6.3+pt27cu126` binary wheel을 추가했다. Torch2.2.2/NumPy1.25.2 요구를 기존 환경에 설치하지 않았다.

가중치는 `Rain729/Prior-Depth-Anything` @`25b3bfcf85209fb015e3b15259f4df8b6f13bb16`의 `depth_anything_v2_vitl.pth`와 **v1.0** `prior_depth_anything_vitb.pth` 두 개만 받았다. 합계 **1,731,985,924B**. Worker는 명시된 Snapshot 디렉터리를 `mde_dir/ckpt_dir`로 전달하므로 설정 경로와 실제 가중치가 분리되지 않는다. `_1_1`이나 다른 크기·V2 가중치를 섞지 않는다.

PDA 카드의 Apache2 표기와 하위 DepthAnythingV2 Base/Large의 CC-BY-NC4.0 조건은 별개다. [PDA 저장소](https://github.com/SpatialVision/Prior-Depth-Anything), [NVIDIA 패치](https://github.com/NVlabs/SimFoundry/blob/9e34ebefcd020583fbb755a8b57268dce78eca26/patches/PriorDepthAnything.patch), [하위 가중치 조건](https://github.com/DepthAnything/Depth-Anything-V2#license)을 따른다.

RGB / known prior / geometric 배열은 같은 Pixel Grid인지 검사한다. 원래 선택 Camera Optical-Z와 처리 해상도 K·추정 단위를 명시해 전달한다. **설치된 PDA API는 K를 입력받지 않으므로 K는 좌표 일치 검사와 출처 기록에 사용하며, 내부에서 Camera 보정을 한다고 표시하지 않는다.** 원본 PDA의 sparse-prior Scale/Shift 정합과 FP32 최소제곱 override를 유지한다. 최종 Known Depth는 원본으로 정확히 splice하고 생성 픽셀 Mask를 별도로 저장한다. PDA가 제공하지 않은 calibrated Confidence는 `null`이다.

실제 작은 추론 결과:

| 항목 | 실측 |
|---|---:|
| 입력 | 합성 RGB128×96, known optical-Z에 중앙 hole, 같은 Grid geometric Z |
| 호출 수 / 결과 | 1회 / COMPLETE |
| Child 전체 시간(Import·로딩·출력 포함) | 8.695s |
| nvidia-smi 전체 GPU 관측 Peak | 2,502MiB |
| RSS 관측 Peak | 3,424,112,640B ≈3.19GiB |
| 로딩 후 Torch allocated / reserved | 1,730,411,008 / 1,774,190,592B |
| Torch allocated / reserved Peak | 1,764,706,304 / 1,826,619,392B |
| Known Depth 보존 | true |
| 출력 | depth.npy, 유한·양수·원래 shape / generated_pixels.npy |

nvidia-smi/RSS는 표본 관측 Peak이며 시스템 배경 사용과 짧은 Peak 누락 가능성을 포함한다. 이 작은 입력의 성공을 실제 Stage5 해상도·FLUX 생성 영상·실측 기하 정확도 검증으로 확대하지 않는다. 임의 dtype 변경·양자화·모델 소스 수정 재시도는 하지 않았다.

## CPU CPD와 후처리 환경

신규 `r2s-cpd`: Python3.11, NumPy1.26.4, SciPy1.15.3, Open3D0.20.0, probreg0.3.8, trimesh4.5.1, skimage0.25.2, Shapely/rtree/embreex. probreg은 Native wheel을 이 환경에서 빌드했다. SBERT CPU 후처리를 위해 CPU Torch2.7.1+cpu, SentenceTransformers5.1.2/Transformers4.57.1을 같은 환경에 추가했다. `pip check`는 성공했다.

SBERT는 `sentence-transformers/all-mpnet-base-v2` @`e8c3b32edf5434bc2275fc9bab85f82640a19130`의 선택 파일만 준비했다. model.safetensors 437,971,872B 외 tokenizer/config 포함 총량은 진단 Manifest에서 확인한다. Apache2 모델이며 이번에는 Encoder Forward를 실행하지 않았다. 공식 SAM3 및 SAM용 선택 OpenAI CLIP ViT-B/16 가중치는 받지 않았다. Comfy용 clip_l은 위 FLUX 묶음으로 별도 설치했다.

실제 probreg Signature:

```text
registration_cpd(source, target, tf_type_name='rigid', w=0.0,
                 maxiter=50, tol=0.001, callbacks=[],
                 use_color=False, use_cuda=False, **kwargs)
```

기존 Worker의 surface sampling/OBB/voxel/farthest/SO(3)/rigid CPD/scale/one-sided NN/inverse fit 인자와 호환된다. ICP나 GLB 의존성을 도입하지 않았다. 실제 작은 비대칭80점 정합은 `use_cuda=False`, scale1.07과 알려진 작은 R,t를 사용해 **registration_cpd 1회** 실행했다. 정합 연산0.00699s, Child 전체2.601s, 대응점 RMSE≈4.20e-17였다. 노이즈 없는 정확한 대응 Synthetic 결과이며 다중 시작 수렴·대칭·실제 Mesh/부분 점군 정확도는 아니다.

## 로컬 설정과 설치 기록

버전 관리 템플릿은 [simfoundry-reconstruction.example.yaml](../real2sim_builder/config/simfoundry-reconstruction.example.yaml)이다. 개인 절대 경로를 제품 기본값으로 넣지 않았다. 이번 설치 경로를 채운 검토용 `runtime-configuration.yaml`은 Git 제외 진단 폴더에만 생성했다. 기존 Workspace/Scene/Candidate 설정에는 저장하지 않았다.

| 설정 | 연결 |
|---|---|
| da3 | 기존 da3 Python / 기존 Source / b2359... Snapshot |
| sam3 | 기존 sam31 Python / 기존 multiplex.pt, FP16 quantize16 |
| pose | r2s-cpd; Support Plane 및 CPD CPU 수학 |
| decomposition | r2s-cpd / 명시 SBERT Snapshot; pruning·ray order |
| image_edit | r2s-comfy / ComfyUI source/models / API Workflow / provider=comfy_gguf |
| prior_depth | r2s-prior-depth / 패치된 Source / 고정 vitl+vitb Snapshot |
| vlm | r2s-prior-depth / 고정 SimFoundry source; Gemini는 텍스트 판단용으로 유지 |
| physics/simulator | 기존 Builder/Isaac 환경. Calibration/q/FK 변경 없음 |
| rembg / foundationpose | 기존 미설정 상태를 유지; 없는 Runtime을 완료로 표시하지 않음 |

이미지 편집의 Gemini/Imagen3/기존 FLUX Diffusers 경로는 명시 선택으로 남긴다. 기본 RGB 편집은 ComfyUI GGUF다. VLM 식별·validity·front 판단에는 여전히 Gemini 등 인증이 필요하며 이번에는 인증/계정/서비스를 조회하지 않았다. 새 별도 입력 폼을 만들지 않았다.

새 환경 세 개의 `pip check`는 통과했다. 기존 da3도 통과하며 sam31의 platformdirs 누락, lerobot-arena의 NumPy/typing_extensions/Torch/psutil/packaging 충돌은 앞선 조사와 같고 이번에 고치지 않았다. 새 환경에만 openai/google-genai 및 원본 SimFoundry editable 설치를 추가했다. 이것을 모든 원본 SimFoundry 모듈 import 성공으로 해석하지 않는다.

설치 직후 `du`/버전·소스 Commit/패치·패키지 목록과 로그는 진단 폴더에 기록했다. 처음 파일시스템 여유는 약61GB, 설치 후 조회는 약36GB였다. 환경 복제·wheel/conda/HF Cache·사용자 시스템 변동을 포함하므로 차이를 모델 용량만으로 표시하지 않는다. 신규 모델은 PDA 두 파일·SBERT 선택 파일과, 동의 후 준비한 FLUX/CLIP/T5/VAE 네 파일이다. DA3/SAM 가중치는 재다운로드하지 않았다. FLUX 묶음은 12,536,135,116B이며 파일 본체를 중복 복사하지 않았다.

## 최소 검증·보존과 다음 단계

- 변경 모듈 계약 테스트 **4 passed**: SAM RGB/BGR·Mask/Point/Confidence 계약, Kontext Workflow·비편집 픽셀 보호, remote endpoint 거부, Stage3/5/6/8 Mock 연결 Smoke. 마지막 소스에서 4개만 재확인했으며 1,751개 전체 회귀는 실행하지 않았다. 중간 RED 2건은 아직 추가하지 않은 Comfy 모듈 import 실패였고 구현 후 통과했다.
- 실제 CPU CPD 1회, 실제 PDA 합성 추론1회, Comfy localhost CPU API Catalog 확인1회 및 동의 후 실제 FLUX 합성 편집1회다. 실제 SAM/DA3 재추론·사용자 사진 E2E·Isaac Physics는 0회다. 이번 동의 후 작업에서는 기존 CPD/PDA/pytest를 반복하지 않았다.
- 모델/Runtime 없음, Stop/Timeout/OOM은 기존 소유 Child/StageNeeds 경계로 전달한다. Comfy Worker의 정상 완료/서버 종료/VRAM 반환은 실제 모델 실행에서 확인했다. OOM/Stop 강제 중단의 모델 해제를 이번에 유발해 시험한 것은 아니다. API/계약 확인과 모델 실행 검증을 구분한다.
- 기존 staged23개·HEAD를 유지한다. Scene/Input/Capture/Candidate/Cache/Asset/Export의 시작 ledger **7,786개를 종료 시 대조해 변경0·누락0·신규0**을 확인했다. 기존 staged23개 diff도 동일하며 DA3 loader 함수 AST도 시작 상태와 같다. 이번 실행은 진단 폴더에만 새 실험 자료를 쓰며 기존 Scene을 열어 저장하지 않았다.

진단 위치: `workbench_runs/diagnostics/local_runtime_integration/`. 주요 자료는 `contracts-final.xml/log`, `sources.json`, `environments.json`, `flux-download-plan.json`, `comfy-api/result.json`, `cpd/result.json`, `prior/result.json`, 각 `runtime.log/resources.json`, `runtime-configuration.yaml`, 보존 대조 JSON이다. 제품은 이 진단 경로를 import하지 않는다.

실제 Reconstruction 전 남은 조건은 **실제 제거/Infill/Upsampling의 품질·기하 보존 검증**, VLM 인증/사용 가능한 모델, 기본 Stage6 RemBG의 Bria Runtime(현재 미설정), 선택 Front/FP 경계, 기존 Robot World 등록과 Side/Wrist Calibration/FK다. 누락을 다른 모델로 몰래 대체하거나 임의 해상도/임계값으로 통과시키지 않는다. 실제 사용자 이미지 E2E는 별도 후속 작업이다.

### 이번 변경 파일

기존 미커밋 구현 위에 다음 13개 파일을 수정/추가했다. Git Index는 Stage하지 않았다.

- 기존 수정: `automation.py`, `stage_runtime.py`, `stage_workers.py`, `reconstruction_stages.py`, `calibration/decomposition.py` (모두 `real2sim_builder/src/real2sim_builder/` 아래).
- 기존 수정: `real2sim_builder/pyproject.toml`, `real2sim_builder/config/simfoundry-reconstruction.example.yaml`, `real2sim_builder/third_party/SIMFOUNDRY_NOTICE.md`, 이 문서.
- 신규: `real2sim_builder/src/real2sim_builder/sam31_adapter.py`, `comfy_edit.py`(같은 디렉터리), `real2sim_builder/config/flux-kontext-gguf.api.json`, `real2sim_builder/tests/test_local_stage_runtimes.py`.

변경 Python7개는 bytecode 없는 compile 검사, 마지막 코드의 선택 계약4개 및 `git diff --check`를 확인했다. 설치된 모델의 전체 라이브러리·모든 Runtime을 전수 검증한 것은 아니다. 전체 테스트 통과 수치를 이번 변경에 재사용하지 않는다.

## 라이선스 동의 후 FLUX 실제 실행 결과 — 2026-11-10

기존 `stage_workers.py --worker image_edit`와 동일한 Comfy Worker에서 **Synthetic RGB512×512, batch1, seed0, 20step, Q4_K_S**로 단 한 번 실행했다. GPU 동시 모델은 없었다. 요청은 “파란 큐브만 주황색으로 변경, 형상/위치 및 빨간 구와 배경 유지”이며 사용자 사진을 사용하지 않았다.

| 항목 | 실제 결과 |
|---|---:|
| Worker / Job | COMPLETE, exit0 / `f667352e-70b0-43bb-bd66-594e01b509d7` |
| 전체 Child 시간(서버 시작·모델 로딩·생성·SHA·종료 포함) | 116.956s |
| Comfy Prompt 실행시간(로딩/인코딩/샘플링/디코딩 포함, 서버 로그) | 100.56s |
| 전체 GPU 관측 Peak | 6,636MiB |
| 소유 프로세스 GPU 관측 Peak | 6,062MiB |
| Worker+서버 RSS 합 관측 Peak | 15,085,916,160B ≈14.05GiB |
| Worker+서버 PSS 합 관측 Peak | 14,442,724,352B ≈13.45GiB |
| 실행 후 전체 GPU 사용량 | 566MiB |
| OOM / Timeout / 재시도 | 없음 / 없음 / 0회 |
| 반환 RGB | uint8 [512,512,3] |
| 비편집 영역 byte 일치 | true |
| 편집 영역에서 달라진 픽셀 | 24,913 |
| 남은 소유 Child | 없음 |

GPU/RSS는 약150ms+조회 비용 간격의 표본 관측값이고 PSS는 매5번째 표본이다. RSS 합은 공유 Page를 중복 셀 수 있어 PSS와 구분한다. Torch allocated/reserved Peak를 별도로 수집하지 않았으므로 nvidia-smi 값을 Torch Peak로 표시하지 않는다. 로그는 CPU Text Encoder/CPU FP32 VAE, GGUF F32/Q4_K/BF16 혼합 저장, UNet 일부 GPU 로딩과 CPU Offload를 확인했다. 단순 autocast 또는 일반 Diffusers 모델을 GGUF 실행으로 보고한 결과가 아니다.

![합성 입력 / 원시 FLUX 출력 / 비편집 영역 보호 합성본](../workbench_runs/diagnostics/local_runtime_integration/flux/comparison.png)

주황색으로의 변경은 관찰했다. 다만 원시 출력에서 큐브의 폭/윤곽과 위치, 빨간 구/배경도 소폭 변했고 보호 합성에서는 원래 Mask 경계에 잘린 흔적이 보인다. **비편집 영역 보존과 실제 생성 성공은 확인했지만, 형상·Pose 보존 또는 Scene 품질 통과는 아니다.** 추가 생성·블렌딩/임계값 변경으로 성공처럼 처리하지 않았다. Stage5 Object 제거, Stage6 실제 Infill/Upsampling, VLM 판단과 연속 Stage E2E는 실행하지 않았다.

결과: [비교 이미지](../workbench_runs/diagnostics/local_runtime_integration/flux/comparison.png), [실측/검증 JSON](../workbench_runs/diagnostics/local_runtime_integration/flux/resources.json), [Worker 결과](../workbench_runs/diagnostics/local_runtime_integration/flux/result.json), [Job 상태](../workbench_runs/diagnostics/local_runtime_integration/flux/job.json). 모델의 실제 경로·SHA·Bytes는 `flux-models.json`과 Worker 결과 모두에 기록했다. 이번 후속에서는 제품 Python/환경 패키지를 추가 수정하지 않고, 승인된 모델 설치·독립 진단 스크립트·이 문서만 갱신했다.
