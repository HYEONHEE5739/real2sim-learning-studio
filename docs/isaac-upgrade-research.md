# Isaac Sim 6.2 / Isaac Lab 3.0 사전 호환성 조사

> **참고 자료로 보존 — 현재 개발 방향 아님.** 2026-10-25 최종 결정: 새 플랫폼 개발 기준은 **Isaac Sim5.1 / Isaac Lab2.3 / LeRobot0.4.1 / MuJoCo3.3.7**이다. 업그레이드는 진행하지 않는다. 최신 버전 조사는 참고 이력이며 신규 환경 분리·분리 추론·업그레이드 대응 코드는 개발 범위에 포함하지 않는다. 기존 UI/엔진 worker의 필요에 따른 프로세스 분리는 유지한다.

조사일: 2026-10-25 (Asia/Seoul). 범위: 공식 배포·설치·Manifest·API의 정적 조사. **설치, 환경 변경, engine import, 시뮬레이션·학습·추론, B01 Baseline 실행을 수행하지 않았다.** 이 문서는 기존 아키텍처를 대체하지 않는다. LeRobot/MuJoCo 및 현재 설치 환경 전체 그래프의 통합 판단은 상위 호환성 보고서에서 다룬다.

## 1. 배포 식별과 권장 출발점

공식 `v3.0.0` 릴리스는 10월 20일 공개된 GA이며 commit 표시는 `e3f7d9f`다. Sim 6.2/Python 3.12/PyTorch 2.11/CUDA 13/Warp 1.17/Newton 1.6.1을 대상으로 한다. 9월의 `v3.0.0-EA`는 Sim 6.1 대상이므로 혼합하면 안 된다. [공식 v3.0.0 릴리스](https://github.com/isaac-sim/IsaacLab/releases/tag/v3.0.0)

확인 기준은 `develop`이 아닌 v3.0.0 태그의 root `pyproject.toml`과 `uv.lock`이다. 단, 태그도 실제 도입 시 commit SHA와 파일 hash로 고정해야 한다. 아래는 설치 가능한 공식 조합의 후보이며 이 컴퓨터에서 실행 검증된 조합이 아니다.

## 2. 직접·선택 의존성과 공식 해결 규칙

주요 직접 조건:

| 축 | 공식 root 조건 |
|---|---|
| Python | >=3.12,<3.13 |
| NumPy / Torch / TorchVision | >=2 / ==2.11.0 / ==0.26.0 |
| Transformers / Warp | ==5.10.4 / ==1.17.0 |
| Newton / USD provider | newton[sim]==1.6.1 / usd-exchange==3.0.1 |
| 수치·입출력 | scipy>=1.11, h5py>=3.15, numba>=0.63.1, pillow>=12.3 |
| 로봇 IK | pin, pin-pink==3.3.0, daqp==0.8.5 (Linux 조건) |

선택 extras: isaacsim, ov/ovphysx/ovrtx, importers, mimic, teleop, video, tetrahedralization, test/dev, RL/시각화. `all`≠모든 extras. 기본 Newton/full Sim 선택을 구분한다. core Manifest는 version28.0.0/dependencies=[]이며 의존성은 root에서 중앙 관리한다. [root Manifest](https://github.com/isaac-sim/IsaacLab/blob/v3.0.0/pyproject.toml), [core Manifest](https://github.com/isaac-sim/IsaacLab/blob/v3.0.0/source/isaaclab/pyproject.toml)

공식 lock은 Python 3.12와 Linux x86_64/aarch64·Windows AMD64의 marker별 전이 패키지·wheel hash를 제공한다. 확인한 예시는 NumPy 2.5.1, Transformers 5.10.4, MuJoCo/MuJoCo-Warp 3.12.0, TorchVision 0.26.0+cu130이다. tokenizers·Hub·safetensors, Newton/importer/USD, 수치/영상, NVIDIA 바이너리 가지까지 확인 대상이다. lock 전체의 모든 extras가 이 프로젝트의 실제 필수 의존성이라는 의미는 아니다. [공식 v3.0.0 uv.lock](https://github.com/isaac-sim/IsaacLab/blob/v3.0.0/uv.lock)

**공식 uv override는 전이 조건을 교체한다.** 아래는 공식 적용이며 다른 제품의 비지원 버전 강제까지 정당화하지 않는다.

| 공식 override | 해결하려는 가지 / 의미 |
|---|---|
| mujoco~=3.12.0, mujoco-warp~=3.12.0 | 관리되는 Lab 환경은 3.12.x; 3.17.0을 끼우는 것은 이 계약 밖 |
| newton-usd-schemas>=0.5 | root 주석은 구형 ==0.2.0 교체를 설명하나, 이번 6.2 실제 METADATA는 ==0.5.0; 현물과 주석을 구분 |
| usd-exchange==3.0.1, usd-optimize~=1.3.1 | Sim importer의 ==2.3.0 요청 교체; 같은 OpenUSD build 유지 |
| fsspec>=2026.6.0 | 공식 root 주석은 Sim core ==2026.2.0/Torch 충돌을 이유로 제시. 실제 Torch2.11 base wheel METADATA의 fsspec>=0.8.5와는 구분 |
| packaging>=20,<27 | OVPhysX <24와 조정; 실제 Sim core METADATA는 >=23.2,<=26.0, lock은26.0 |
| urllib3>=2.8.0 | kernel의 구형 pin 교체 |

통합 조사에서 확인한 [Torch 2.11 PyPI METADATA](https://pypi.org/pypi/torch/2.11.0/json)의 base 요구는 fsspec>=0.8.5다. root 주석을 wheel의 정확한 요구사항으로 인용하지 않는다. Lab 관리 override 자체는 >=2026.6.0이다. Torch/TorchVision·NumPy·Newton도 override된다. **plain pip 실패≠공식 Lab 설치 불가**다. workspace/lock/index까지 확인한다. constraints의 조건 교집합과 다르다. [공식 override 선언](https://github.com/isaac-sim/IsaacLab/blob/v3.0.0/pyproject.toml#L390-L414)

### LeRobot과 한 환경에 둘 때의 판단

SmolVLA가 요구하는 Transformers 집합에 5.10.4가 없다면 같은 Python에서 공식 두 조건을 동시에 만족할 수 없다. 정확한 LeRobot 0.6.1 extra·module 조건과 Hub/tokenizers/accelerate/peft까지 함께 비교해야 한다. 버전 숫자 하나를 강제하거나 `--no-deps`로 설치하는 것은 공식 지원 해결책이 아니다. Lab의 관리 MuJoCo 3.12.x와 별도 MuJoCo 3.17.0도 분리해서 판단한다. 이것은 root constraint에서 도출한 분석이며 LeRobot 실행 시험 결과가 아니다.

## 3. OS·GPU·CUDA 조건

Sim 6.2 Python wheel은 Python 3.12와 Linux GLIBC 2.35+를 요구한다. NVIDIA는 전용 Python 환경을 안내하며 기존 환경 설치가 의존성과 editable 설치를 교체할 수 있다고 명시한다. Torch 2.11 cu128/cu130 설치 경로도 문서에 있다. [Sim 6.2 Python 설치](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_python.html)

Lab3의 기본 CUDA13 경로는 compute capability 7.5+와 Linux driver >=580.65.06을 요구한다. 이 수치는 **full Sim의 테스트 드라이버 기준과 동일하지 않다.** [Lab 3 설치 조건](https://docs.nvidia.com/isaaclab/3.0/isaac-lab/installation#system-requirements)

Sim 6.2 x86_64 문서는 Ubuntu 22.04/24.04·Windows11, RAM32GB·VRAM16GB·RTX4080급을 최소 표로 제시하며 Linux tested driver는595.58.03이다. Ubuntu22.04 지원은 deprecated지만 아직 제외되지는 않았다. RT Core 없는 A100/H100은 지원하지 않는다. 이 컴퓨터의 Ubuntu22.04/glibc2.35만으로 렌더링/GPU 지원을 확정할 수 없다. [Sim 6.2 요구사항](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html)

## 4. v8 이관의 API·계산 의미 영향

다음은 공식 3.0 변경과 기존 실제 호출의 대응이다. 기존 P 루트는 `/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab`이다.

| 변경 | 기존 위치 / 필요한 대응 |
|---|---|
| Quaternion WXYZ → XYZW | P native/isaac.py:191,256,335,350과 workspaces/environment.py:24. 저장 데이터 WXYZ를 재해석하지 말고 엔진 경계에서 명시 변환 |
| `.data.*` → ProxyArray | joint/root/contact·sensor 데이터는 `.torch`/`.warp` 접근을 명시. reset 후 이전 view 재사용 금지 |
| index/mask write 분리 | native/isaac.py:350~356 초기 복원·reset은 `_index`의 partial shape/env_ids 의미를 대조 |
| backend·schema 변경 | native/isaac.py:128~139의 PhysX 속성은 새 공식 schema/fragment에 대응. Newton 기본 선택으로 물리를 바꾸지 않음 |
| actuator target API | 기존 set_joint_position_target의 solver limit·target 적용 시점을 새 actuator 소유 API와 대조 |

이 변경은 함수 이름 교체만으로 완료되지 않는다. quaternion/센서·현재 view의 좌표·수명·step 시점을 기존 Baseline과 비교해야 한다. [공식 Lab 3 migration](https://docs.nvidia.com/isaaclab/3.0/isaac-lab/migrating-to-3-0), [ProxyArray 갱신·reset 수명](https://isaac-sim.github.io/IsaacLab/develop/source/how-to/proxy_array.html)

**Grasp의 중요한 의미 변화:** Sim PhysX6.2의 `force_matrix_w`와 `net_forces_w`는 normal+friction의 total이다. normal만 필요한 경우 새 명시 normal 필드와 구분해야 한다. 기존 native/isaac.py:389와 workflow/adapters.py:353은 `force_matrix_w` norm을 사용하므로, 이름을 유지하면 같은 threshold라도 판정이 달라질 수 있다. 기존5.1 측정량/시간 평균을 먼저 고정하고 새 필드를 선택해야 한다. Evaluation의 직접 contact_view 경로도 별도 확인한다. [공식 contact force 의미 표](https://docs.nvidia.com/isaaclab/3.0/isaac-lab/migrating-to-3-0#assets-actuators-and-sensors)

Sim6 계층의 camera/physics sensor API도 변경된다. physics sensor의 생성·읽기(`get_data`)와 step 유효성·timing을 확인해야 한다. 저수준 Sim physics-sensor constructor의 orientation 예시는 여전히 WXYZ이므로 모든 4-vector를 일괄 XYZW 변환하면 안 된다. [공식 physics sensor migration](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/migration_guides/isaac_sim_6_0/sensors_physics_to_experimental_physics.html), [공식 camera migration](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/migration_guides/isaac_sim_6_0/sensors_camera_to_experimental_rtx.html)

URDF importer는 새 Python pipeline이며 과거 URDFParseAndImportFile은 제거됐다. USD 재생성이 필요하면 articulation root·world joint·collision·drive·unit·mimic schema를 대조해야 한다. 기존 v8의 보정 USD/URDF 원본을 재생성해 덮어쓰지 않는다. [공식 asset pipeline migration](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/migration_guides/isaac_sim_6_0/urdf_mjcf_importer_exporter_pipeline.html)

| Workflow | 변경 범위 / 보존 검증 |
|---|---|
| Scene·Calibration | importer/physics schema·좌표/회전 경계; 기존 geometry residual 적용 순서·identity·3mm 변경 금지 |
| Source | Env/MDP/관측 access·영상·command write; pre-step 기록·dtype·실제 applied command 보존 |
| Annotation | initial restore·contact/Tracker 시점; Placement AND latched Grasp·manual mark 의미 보존 |
| DataGen | 기존 Mimic reference/IK/RNG/실패예산을 보존하며 엔진 state·write만 새 API 연결; 최신 Mimic으로 무검증 교체 금지 |
| Evaluation | Placement 종료와 grasp 부가지표·contact_view 경로·최초 tick을 분리 검증 |

이 마지막 표는 공식 API 변경을 기존 코드에 적용해 도출한 영향 분석이다. 해당 기능이 신규 버전에서 실행되었다는 증거는 아니다. 기존 미완성 Workflow 구조의 복제나 새 Wrapper/ABC 추가는 요구하지 않는다.

## 5. 권고와 미검증 목록

- 기존5.1/Lab2.3/Python3.11/LeRobot0.4.1 환경은 그대로 Baseline용 보존한다. 신규 Isaac 검토는 별도 Python3.12 환경의 공식 v3.0.0+Sim6.2 경로로 분리한다.
- v8은 우선 `isaacsim_physx`/기존 RTX 의도를 명시하고 검증한다. Lab3 기본 Newton 또는 OVPhysX/OVRTX는 같은 엔진으로 간주하지 않는다.
- 최종 채택 전 필요: 정확한 extras별 resolver/lock 분석, NVIDIA wheel/Kit 의존성 가용성, driver/GPU 확인, App 생성·단일 scene load, USD closure·보정/FK/camera, restore/한 step/contact/영상, 단계별 기록/판정, Policy/Dataset 양방향 소비 검증.
- 이번에는 resolver 설치/다운로드 패키지 실행·GPU import·학습·추론·물리 시험을 하지 않았다. 공식 lock 존재는 현재 컴퓨터의 설치/실행 검증을 대신하지 않는다. 모든 extras의 상호 결합이 동시에 지원된다는 주장도 하지 않는다.
