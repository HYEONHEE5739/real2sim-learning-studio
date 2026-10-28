# B01 전 버전·환경 호환성 조사

> **참고 자료로 보존 — 현재 개발 방향 아님.** 2026-10-25 최종 결정: 새 플랫폼 개발 기준은 **Isaac Sim5.1 / Isaac Lab2.3 / LeRobot0.4.1 / MuJoCo3.3.7**이다. 업그레이드는 진행하지 않는다. 최신 버전 조사는 참고 이력이며 신규 환경 분리·분리 추론·업그레이드 대응 코드는 개발 범위에 포함하지 않는다. 기존 UI/엔진 worker의 필요에 따른 프로세스 분리는 유지한다.

조사일: 2026-10-25 (Asia/Seoul). 상태: **정적 조사 및 메타데이터 해결 시험 완료, 실행 호환성 미검증**. 이번 요청의 마지막 지시인 '먼저 정적 의존성 분석과 설치 가능성 검증만'을 적용했다. B01의 엔진 trace/fixture 실행, 업그레이드, 설치, 빌드, 학습/추론, 데이터 변환은 수행하지 않았다. 기존 환경·원본 Scene/Calibration/데이터를 변경하지 않았다.

## 1. 판단과 권장 조합

목표 버전은 공식 배포가 확인된다. 다만 **LeRobot 0.6.1 SmolVLA + Isaac Lab 3.0 공식 관리 환경 + MuJoCo 3.17.0을 하나의 Python 환경에 모으는 조합은 채택할 수 없다.** Transformers와 MuJoCo 조건이 겹치지 않고, 공식 lock/전이 패키지 차이도 있다. 강제 override나 --no-deps로 통과시키는 방법은 권장하지 않는다. [LeRobot v0.6.1 선언](https://github.com/huggingface/lerobot/blob/v0.6.1/pyproject.toml), [Isaac Lab v3.0.0 선언](https://github.com/isaac-sim/IsaacLab/blob/v3.0.0/pyproject.toml)

| 용도 | 권장 조합 / 상태 |
|---|---|
| B01 기준 환경 | 기존 lerobot-arena: Python3.11.15 / Sim5.1.0 / Lab 저장소2.3.0(distribution0.47.2) / Torch2.7.0+cu128 / NumPy1.26.0 / LeRobot0.4.1 / MuJoCo3.3.7. 원본 그대로 보존. 설치 선언상의 부채가 있어도 먼저 고치지 않음 |
| 새 학습·추론·변환 후보 | **별도 Python3.12** / LeRobot0.6.1 / Torch2.11.0 / TorchVision0.26.0 / NumPy2.2.6 / Transformers5.5.4 / TorchCodec0.11.1 / PyAV15.1.0. 공식 LeRobot lock은 Torch cu128 소스도 제공. 실제 도입 시 해당 프로파일의 CUDA wheel source/hash까지 고정 |
| MuJoCo 신규 후보 | 별도 Python3.12 / MuJoCo3.17.0 / NumPy2.2.6. ACT 학습/평가와 같은 환경의 메타데이터 해결 성공. SmolVLA와도 선언상 양립 가능하나 source-only docopt 빌드는 이번에 미검증 |
| Isaac 신규 검토 후보 | 별도 Python3.12 / Isaac Sim6.2.0.0 / Lab v3.0.0 공식 workspace/lock / Torch2.11 cu130 / Transformers5.10.4 / 관리 MuJoCo3.12.x. **현재 GPU는 full Sim6.2 공식 최소 VRAM 기준 미달**. 이 컴퓨터에서 신규 기준 엔진으로 채택/실행 가능하다고 확정하지 않음 |
| UI | 기존 Qt 전용 환경 분리 방향 유지. 학습/Isaac 패키지를 UI 프로세스에 모두 설치할 필요 없음 |

이는 최종 환경 구조 승인이나 새 RPC 계층 구현이 아니다. 학습/시뮬레이션 분리는 유력 후보이고 Dataset·Policy 교환과 지연/VRAM 시험 후 확정한다. B01은 신규 후보가 아니라 기존 환경에서 수행해야 한다. 새 target engine은 기준 확보 후 별도 회귀 대상이다.

## 2. 조사 범위와 '전체 의존성'의 의미

선택 정책은 ACT·SmolVLA, Dataset·Training·Evaluation이다. 모든 로봇/정책 extra를 동시에 설치하도록 요구하지 않는다. 조사에서는 다음을 모두 기록했다.

- 공식 LeRobot v0.6.1: 직접 의존16개·optional group69개, 공식 uv.lock333개 package node/994개 dependency edge.
- 공식 Lab v3.0.0: 직접 의존63개·optional group23개, 공식 uv.lock439개 node/1,137개 edge. root가 의존성을 중앙 관리하며 core 하위 Manifest만 보면 안 된다.
- 두 lock의 registry node를 합친 **정확한 버전별 653개 패키지**의 Requires-Python/Requires-Dist/extras 조회. 일반 PyPI648개와 CUDA/NVIDIA wheel 메타데이터5개를 모두 확보했다. x86_64 wheel은 해당 플랫폼 METADATA로 보완했다. 최종 조회 성공/제한은 [증거 요약](evidence/version-compatibility/validation.json)에 기록한다.
- 현재 네 환경의 **518개 distribution record, 6,390개 선언 edge**를 정적으로 검사했다. 서로 다른 환경의 동일 이름은 별도 record다. base marker와 선택 extra를 구분했고, Linux x86_64/Python 버전에 맞춰 판정했다.
- lock 공통 이름에서 버전 집합이 다른79개를 전부 색인했다. 다른 platform/optional branch의 차이도 포함하므로 79개 모두를 hard conflict라고 부르지 않는다.

추가로 두 lock의 메타데이터 선언 edge7,639개를 검사했다(LeRobot3,205/Lab4,434). 공식 platform marker·prerelease 허용·override를 적용한 가능한 Linux/Python3.12 부모의 기본 선언에서는 각 lock 내 불일치가 발견되지 않았다. 모든 extras를 동시에 활성화한 완전 resolver 증명은 아니다. 원시 요구/적용 override/허용 후보와 비활성 platform 차이는 [전체 edge 감사](evidence/version-compatibility/all-edges-audit.json)에 남겼다.

전체 선언 그래프와 **실제로 선택한 프로파일**의 해결 결과를 구분한다. lock의 모든 플랫폼/모든 extras를 함께 import해 봤다는 뜻이 아니다. 소스 코드가 runtime에 선언 외 모듈을 요구하는 경우, 공유 라이브러리 ABI, 모든 wheel의 실물 실행까지 정적 그래프만으로 증명할 수 없다. 조회 실패/메타데이터 미확보를 숨기지 않고 증거에 남긴다.

증거: [원본 출처·hash](evidence/version-compatibility/source-index.json), [공식 선언·lock 그래프](evidence/version-compatibility/dependency-graphs.json), [버전별 전체 패키지 메타데이터](evidence/version-compatibility/package-metadata.json), [현재 설치 그래프](evidence/version-compatibility/local-environments.json), [분석/해결 결과](evidence/version-compatibility/graph-analysis.json).

## 3. 실제 하드웨어·운영체제

| 항목 | 읽기 전용 확인 결과 | 의미 |
|---|---|---|
| OS/아키텍처 | Ubuntu22.04.5 / Linux6.8.0-136 / x86_64 / glibc2.35 | Sim6.2 wheel의 OS/glibc 축에는 부합. Ubuntu22.04는 공식 문서에서 deprecated |
| CPU/RAM | Ryzen7 8845HS, 16 logical CPU; MemTotal32,132,708KiB(약30.6GiB) | 메모리 여유·동시 학습/렌더 실행은 별도 측정 필요 |
| GPU | NVIDIA GeForce RTX4060 Laptop, **8188MiB**, compute capability8.9 | CUDA13 compute 축은 충족하나 Sim6.2 full RTX 최소표의 RTX4080/16GB에 미달 |
| 드라이버 | **580.178.04** | CUDA13의580 계열 최소 축은 충족. Sim6.2 tested Linux driver595.58.03과 같지 않음 |
| 로컬 CUDA Toolkit | `/usr/local/cuda-12.4`, SDK12.4.1 | PyTorch wheel의 cu128/cu130 runtime과 다름. nvcc toolkit 버전만으로 wheel 실행 불가라고 판단하지 않음 |
| 영상 라이브러리 | 시스템 FFmpeg4.4.2; libavcodec58/libavformat58/libavutil56 존재 | 파일 존재는 TorchCodec·EGL·CUDA decoder import/영상 일치 시험이 아님 |

처음 sandbox nvidia-smi는 /dev/nvidia 접근이 없어 실패했다. 읽기 전용 외부 조회는 성공했으므로 호스트 드라이버 고장으로 보고하지 않는다. GPU UUID는 수집물에서 제외했다. CUDA toolkit의 version.json에 있는 bundled driver 수치와 실제 커널 driver580.178.04도 혼동하지 않는다.

근거: [Sim6.2 요구사항](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html), [Sim Python/glibc 조건](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_python.html), [CUDA13 driver 조건](https://docs.nvidia.com/deploy/cuda-compatibility/610/minor-version-compatibility.html). OS·driver가 일부 축을 만족해도 VRAM 미달이 해소되지는 않는다. 작은 headless Scene이 동작할 가능성과 공식 full Sim 지원은 별개다.

## 4. 실제 충돌과 양립 가능한 범위

| 경로 | 요구 조건 | 판단 |
|---|---|---|
| LeRobot0.6.1 → Python vs 기존 Sim5.1 환경 | >=3.12 vs 현재3.11 | Python3.11을 유지한 직접 설치 불가. 기존 환경은 업그레이드하지 않음. target Lab3도 >=3.12,<3.13이어서 신규끼리의 Python 교집합은3.12 |
| SmolVLA → transformers-dep vs Lab3 | >=5.4,<5.6 vs ==5.10.4 | **hard conflict**, 교집합 없음. ACT에 이 extra 조건을 억지로 적용하지 않음 |
| Newton1.6.1[sim]·Lab override → MuJoCo vs target | ~=3.12.0 vs ==3.17.0 | **hard conflict**. Lab 내부 MuJoCo/Newton backend와 기존 native MuJoCo worker는 다른 실행 경로 |
| LeRobot → NumPy vs Lab official lock | >=2,<2.3 vs locked2.5.1 | 해당 lock 그대로 함께 사용 불가. 단 Lab 기본 >=2와의 선언 교집합2.0~2.2는 있음; 모든 Lab 조건과 공식 검증까지 성립한다는 뜻은 아님 |
| LeRobot → packaging vs Lab lock | >=24.2,<26 vs locked26.0 | 해당 lock 그대로 불가. Lab override>=20,<27과의 일반 교집합은24.2~25.x. 강제 변경을 이미 공식 검증된 조합으로 취급하지 않음 |
| LeRobot training → datasets4.8.5 → fsspec vs Lab managed | >=2023.1,<=2026.2 vs >=2026.6 | **관찰한 pinned Dataset 조합의 hard conflict**. datasets 전체 미래 버전이 영구 불가라고 확대하지 않음 |
| Transformers → tokenizers/Hub | LeRobot lock0.22.2/Hub1.26 vs Lab0.23.0rc0/Hub1.16.1 | 버전 차이와 선택 구간을 기록. 상위 Transformers 불일치를 tokenizers만 바꿔 해결할 수 없음 |
| Torch/TorchVision | target2.11.0/0.26.0 | 상위 선언 교집합 있음. CUDA source·NVIDIA runtime·triton3.6·ABI는 별도 |
| TorchCodec | LeRobot dataset은 >=0.3,<0.12로 넓게 허용 | 실제 Torch2.11에는 공식 matrix의0.11 계열 선택. solver가 통과해도 임의 TorchCodec 조합을 허용하지 않음 |
| NumPy2 ABI | SciPy/h5py/pandas/OpenCV/Pin·cmeel·USD 관련 native wheel | NumPy 범위만 맞추는 것으로 import ABI 검증 완료 아님. 정확한 wheel/platform·native soname 대조 필요 |
| USD·schemas·urllib3 | Sim transitive pin과 Lab root의 override | Lab 공식 설치가 의도적으로 조정. plain pip의 원시 충돌과 공식 uv 해결을 구분 |

공식 Lab는 newton-usd-schemas, usd-exchange, fsspec, packaging, urllib3, Torch 등의 전이 조건을 override한다. **override는 constraints 교집합과 달리 요구를 교체**한다. 이를 LeRobot의 비지원 Transformers/Dataset 조건을 무시하는 근거로 사용하지 않는다. Lab 공식 lock에는 tokenizers0.23.0rc0·일부 dev/RC 패키지도 있고 공식 prerelease=allow가 적용된다. GA 제품 버전이라고 모든 전이 패키지가 stable이라는 뜻은 아니다.

Lab 코멘트의 fsspec 상향 설명과 실제 Torch2.11 wheel의 `fsspec>=0.8.5`는 다르다. 여기의 높은 조건은 실제 Lab override에서 나온다. [공식 Lab root override](https://github.com/isaac-sim/IsaacLab/blob/v3.0.0/pyproject.toml)

공식 root 주석과 실제 패키지 METADATA가 다른 사례도 확인했다. Sim core의 packaging은 실제 >=23.2,<=26.0이며 schemas는==0.5.0이다. 주석의 과거 ==26.0/==0.2.0 요청을 그대로 현물 충돌로 세지 않는다. 반면 asset-isolated/robot-schema의 usd-exchange==2.3.0, asset-isolated의 usd-optimize==1.1.0, kernel의 urllib3==2.7.0은 이번 METADATA에 실제 존재하며 Lab override와 다르다. 선택 OVPhysX0.6.4의 packaging<24는 LeRobot>=24.2와 직접 충돌하지만 full Sim만 쓸 때 이 선택 extra를 필수로 간주하지 않는다.

### 나머지 직접·간접 패키지에서 확인한 항목

- 수치: NumPy/SciPy/numba/llvmlite/pandas/pyarrow/h5py의 Python marker와 wheel 범위. target lock 사이 SciPy1.18/1.17, Pin3.4/3.9 등 차이는 그래프에 기록하며 즉시 불가로 단정하지 않는다.
- 모델: Torch/TorchVision/TorchCodec/accelerate/peft/safetensors/Hub/tokenizers/sympy/triton 및 CUDA toolkit/bindings. TorchCodec의 native compatibility는 [공식 matrix](https://github.com/pytorch/torchcodec#compatibility-with-torch-versions)와 대조한다.
- 데이터·네트워크: datasets4.8.5/pyarrow25/pandas2.3.3/fsspec2026.2/aiohttp, requests/httpx/urllib3, protobuf/grpcio, wandb/pydantic. selected extra에서만 조건을 활성화한다. 예를 들어 legacy robot extra의 protobuf 상한을 ACT 기본 조건으로 오인하지 않는다.
- 영상/UI: PyAV15.x·FFmpeg shared lib, OpenCV headless와 full 패키지의 cv2 namespace 중복. **Sim6.2 core는 opencv-python-headless-noffmpeg4.14.0.94rc3를 요구**하고 LeRobot은 opencv-python-headless<4.14를 요구한다. 서로 다른 distribution이 같은 cv2를 제공하는 문제여서 solver가 둘을 넣어도 안전한 공존 증거가 아니다. 현재 lerobot 환경은 opencv-python5.0.0.93과 headless4.13.0.92가 함께 있으므로 METADATA 충돌0이어도 실제 cv2 파일 소유/GUI backend는 확인 필요다. 이번에 삭제하지 않았다.
- 로봇/IK: feetech/pyserial, 선택 placo/pin/cmeel-urdfdom/tinyxml ABI. LeRobot은 placo<0.9.16·cmeel-urdfdom<5·tinyxml2<11 상한 이유를 공식 Manifest에 적고 있다. 장치 extras를 전부 설치하기보다 필요한 SO101 경로를 추후 선택한다.
- MuJoCo3.17 base: absl-py, etils[epath], glfw, numpy, PyOpenGL, websockets>=13. Python>=3.10, CUDA 필수 조건 없음. sysid/usd extras는 별도 그래프이고 native MuJoCo와 mujoco-warp/MJX를 같은 패키지로 취급하지 않는다. [공식 MuJoCo 선언](https://github.com/google-deepmind/mujoco/blob/3.17.0/python/pyproject.toml)

## 5. 설치 가능성 시험 결과

`uv pip compile`만 사용했다. Python3.12와 Linux x86_64-manylinux_2_35를 지정하고 `--no-build --no-cache --no-python-downloads`로 metadata를 해결했다. **sync/install/run/build를 하지 않았다.** 전체 argv·return code·입력·출력은 [resolver 결과](evidence/version-compatibility/resolver/extra-results.json)에 있다. 최초 자동 interpreter 탐색의 경고가 있어 명시적 기존 Python3.12 경로로 보완했으며 두 결과를 모두 보존했다.

| 프로파일 | 결과 | 입증 범위 |
|---|---|---|
| MuJoCo3.17 + NumPy2.2.6 | resolve 성공 | Python3.12/Linux wheel 메타데이터에서 의존성 해결 |
| LeRobot0.6.1 training/evaluation(ACT) + MuJoCo3.17 + Torch2.11/TV0.26/TC0.11.1 | resolve 성공 | 해당 selected profile의 설치 후보. ACT 학습/추론·EGL 실행 검증 아님 |
| 위 조합 + SmolVLA/Transformers5.5.4 | docopt0.6.2 wheel 부재로 no-build 시험 중단 | num2words→docopt의 source build가 필요. 버전 모순이나 SmolVLA 실행 불가를 뜻하지 않음 |
| SmolVLA + Transformers5.10.4 | resolve 실패 | 직접 버전 조건 불일치 |
| MuJoCo~=3.12.0 + 3.17.0 | resolve 실패 | 직접 버전 조건 불일치 |
| LeRobot + NumPy2.5.1 | resolve 실패 | LeRobot NumPy 상한과 official lock 수치 차이 |
| LeRobot + packaging26.0 | resolve 실패 | 상한 불일치 |
| datasets4.8.5 + fsspec>=2026.6 | resolve 실패 | 전이 조건 불일치 |

SmolVLA의 docopt는 현재 lerobot 환경에 이미 설치되어 있으며 선택된 training/smolvla/evaluation closure107개 node/205개 active 선언에서 불일치는0이다. 이 사실과 공식 lock을 근거로 설치 후보라고 평가하지만, 새 환경의 source wheel 빌드/실제 import까지 통과했다고 말하지 않는다. 모든 optional extra의 단일 환경 설치 성공도 주장하지 않는다.

Lab3+Sim6.2 전체에 plain pip compile을 적용해 공식 설치 가능 여부를 판정하지 않았다. 공식 uv workspace/전용 인덱스/lock/override가 필요한 설치이며 **전용 환경 실제 설치·Kit/RTX import는 미실행**이다. 현재 하드웨어도 full Sim 최소 조건에 미달하므로 설치 가능과 지원·실행 가능을 합치지 않는다.

## 6. 현재 환경의 부채와 보존

현재 METADATA 전체 기본 marker 검사: lerobot-arena325개 패키지에서5개 선언 불일치, lerobot159개/.venv-mujoco22개/.venv-real2sim-ui12개는 기본 선언 불일치0이다. arena의 항목은 ipython→psutil>=7(현재5.9.8), LeRobot→packaging>=24.2(현재23), onnx→typing_extensions>=4.15(4.12.2), rerun-sdk→NumPy>=2(1.26), stable-baselines3→Torch>=2.8(2.7)이다.

이것은 'Baseline을 고치라'는 결론이 아니다. 사용하지 않는 경로·기존 vendor/override·runtime 정상 여부는 다를 수 있다. **기존 환경을 그대로 고정하고 B01 실행 시 이 부채와 실제 사용 경로를 함께 기록한다.** 반대로 현재0.6.1 환경의 선언0도 import·SmolVLA 학습·렌더 성공을 의미하지 않는다. editable source `/home/hyeonhee/lerobot_061`도 배포 wheel과 완전히 같다고 가정하지 않는다.

## 7. 환경 간 Dataset·Policy 연결과 성능

Dataset 변환은 시뮬레이터 프로세스가 내부 Episode/영상·좌표/명령 의미를 기록하고, LeRobot0.6.1 환경의 공식 Dataset API가 파일을 읽어 변환하는 기존 책임 분리를 유지한다. 같은 Python의 NumPy 객체를 pickle로 공유하지 않고 저장 계약의 dtype/shape/단위/기록 시점을 확인한다. 변환 후 공식 reader·feature/fps/PTS·stats·action·episode 경계와 실제 학습 입력을 비교한다.

LeRobot0.4.1도 Dataset v3를 사용할 수 있다. **버전이 바뀌었다고 전부 재변환하지 않는다.** 실제 meta/info의 codebase_version과 reader 요구를 확인해 필요한 경우에만 별도 결과를 만든다. 공식 v3 이전 형식은 공식 migration 범위를 검토하고 원본은 보존한다. [태그 v0.6.1 Dataset v3 안내](https://github.com/huggingface/lerobot/blob/v0.6.1/docs/source/lerobot-dataset-v3.mdx)

Policy는 config/safetensors뿐 아니라 pre/postprocessor·normalization stats·tokenizer·camera/feature/joint/action 계약을 함께 고정한다. 0.4.1에서 저장한 checkpoint의0.6.1 로딩·같은 관측의 전처리/tensor/action 비교와 episode reset/chunk 상태 시험이 필요하다. processor 이전의 더 오래된 모델에만 공식 normalization migration이 필요할 수 있으며 모든0.4.1 모델을 해당 대상으로 단정하지 않는다. [공식 backward compatibility](https://github.com/huggingface/lerobot/blob/v0.6.1/docs/source/backwardcomp.mdx)

SmolVLA 추론을 Isaac 프로세스 밖에서 실행하는 경우:

- 기존 worker 구조 안의 평가 경계에서 관측→Policy 요청→동일 tick action 반환의 최소 연결을 검토한다. 새 범용 서비스/Adapter를 먼저 구현하지 않는다.
- 공식 v0.6.1 async PolicyServer/RobotClient는 대안이지만 실제 Robot을 대상으로 하며 Isaac/MuJoCo에 즉시 연결되는 client라고 가정하지 않는다. chunk·threshold·aggregation·wall time 변경은 기존 동기 평가 동작을 바꾸므로 검증 없이 채택하지 않는다. [해당 태그 async 문서](https://github.com/huggingface/lerobot/blob/v0.6.1/docs/source/async.mdx)
- 같은 컴퓨터 두 프로세스는 모델/engine별 CUDA context·버퍼를 가지므로 8GB VRAM 경합이 커질 수 있다. 학습과 RTX 시뮬레이션 동시 실행을 기본 요구로 두지 않는다.
- 두640×480 RGB uint8 영상은 step당1,843,200bytes, 30Hz이면 약55.3MB/s의 raw payload다. 여기에 host/device 복사·직렬화·preprocess·추론 지연이 더해진다. 이는 산술 규모이며 성능 측정 결과가 아니다. 압축을 임의 추가하면 픽셀/관측 의미가 바뀔 수 있다.
- wall-clock 지연과 시뮬레이션 tick을 구분해 p50/p95/최대 지연, dropped/stale action, frame age, 처리량·VRAM을 측정한다. B01의 기존 관측/명령 시점과 종료 tick을 유지할 수 있는지 먼저 비교한다.

따라서 MuJoCo+LeRobot 동일 환경은 설치 후보, Isaac+LeRobot 분리 추론은 검증 후보이며, 최종 배치는 파일/Policy 연동·성능·동작 시험 후 결정한다.

## 8. v8 이관의 예상 변경 범위

기존 Native Source/Annotation은 사용자가 먼저 전환한 구현이고 DataGen/Evaluation은 아직 미전환 경로다. **기존 계산·동작은 Reference로 쓰되 미완성된 실행 구조는 복제하지 않는다.** 엔진별 공식 API와 이미 확정한 책임 배치에 맞춰 구현한다.

| 범위 | 필요한 검토·변경 | 반드시 보존할 의미 |
|---|---|---|
| Isaac Env/Scene/MDP·state | Lab3 공식 backend/config·ProxyArray .torch/.warp, write index/mask, actuator API | env index·dtype·reset/step·command clip·pre/post 시점 |
| quaternion | Lab3는 XYZW, 기존 데이터/수식은 WXYZ | 엔진 경계 명시 변환; 과거 저장값 재해석 금지, 모든 Sim low-level API까지 일괄 변경 금지 |
| contact/Grasp | PhysX6.2 force_matrix_w는 normal+friction total, explicit normal 필드와 구분 | 기존5.1 측정량·threshold·시간/window/latch; 이름만 유지하면 결과가 바뀔 수 있음 |
| camera/Calibration | experimental camera/physics API, Fabric pose·URDF importer/schema·USD 적용 확인 | K/distortion/mount/frame·residual 합성 순서·model identity·보정 적용 횟수 |
| Source/Annotation | 새 공식 API 연결, 기록 초기 상태 복원·manual/auto 채택 | Source gate 없음, Annotation Placement AND latched Grasp, 기록/판정 tick |
| DataGen/Eval | 기존 reference Mimic/IK/RNG/budget를 새 실행에 연결; 평가 contact_view 변경 조사 | 정상 IK/Task 실패, 배치 실패, Placement 종료/추가 지표 구분 |
| MuJoCo3.3.7→3.17 | CPU API는 유지되나 solver/contact·inertia·asset/texture·state field 변경 점검 | DT/decimation·collision geometry·physics·성공 계산·실제 pose trajectory |
| 공식 LeRobot | CLI/config/feature/processor API·Dataset writer/finalize 및 checkpoint 수용 검사 | 공식 Trainer 기본 loop/optimizer/scheduler, 독립 Offline Validation |

상세 공식 근거와 실제 기존 파일 대응은 [Isaac 조사](isaac-upgrade-research.md). [MuJoCo3.17 changelog](https://github.com/google-deepmind/mujoco/blob/3.17.0/doc/changelog.rst)의 solver 종료/접촉 변경 때문에 같은 MjModel/MjData API 호출 가능성이 물리 동등성을 뜻하지 않는다. 새 batch/Filament를 기본으로 채택하지 않는다.

Finger Collision은 새 Export에 실제 참조 파일과 필요한 source를 포함하고 **manifest.json에 path/size/SHA 등록**한다. MuJoCo loader는 package root와 내부 상대 path로 읽게 바꾼다. 새 패키지를 다른 절대 경로로 옮기고 기존 repo가 보이지 않는 조건에서 모델 compile·contact source hash 확인·한 step 시험을 해야 완료다. 파일 존재만으로 끝내지 않으며 v8 원본은 변경하지 않는다. 이번에는 요구·검증 계획만 갱신했다.

## 9. 후속 검증 관문

| 관문 | 필요한 결과 | 이번 상태 |
|---|---|---|
| V-COMPAT-01 선언/그래프 | 공식 tag/metadata·전체 extras/전이 graph·명시 충돌 | 조사 완료. 실패/제한 포함 증거 저장 |
| V-COMPAT-02 신규 설치·native import | 별도 환경 exact lock/index, docopt build, Torch/TC/Pin/USD/EGL/RTX import | 미실행 |
| V-COMPAT-03 Dataset·Policy | 기존 자료→0.6.1 reader/변환·학습 batch·추론/action·processor 비교 | 미실행 |
| V-COMPAT-04 신규 엔진 v8 | Scene/Calibration/camera/state/contact·stage trace/성공 경계 대조 | 미실행. B01 기존 엔진 Baseline이 선행 |
| V-COMPAT-05 분리 실행 성능 | 동기 관측/action 시점·지연·VRAM/throughput·drop/stale 검사 | 미실행, 환경 배치 최종 결정 전 필요 |
| ASSET-FINGER-01 패키지 | 파일/manifest/loader 상대 참조·이동 후 old repo 없는 로딩 | 미구현/미실행 |

V8/CAL/DATA/ROBOT의 기존 OPEN 항목은 해제하지 않는다. 현재 권고는 기존 Baseline 보존 + 별도 학습/변환·MuJoCo 후보 검증 + 하드웨어 조건을 충족하는 Isaac 신규 검토다. 이번 조사 결과를 승인된 업그레이드·새 아키텍처 구현으로 간주하지 않는다.
