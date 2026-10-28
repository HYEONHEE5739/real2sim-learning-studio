# Dataset 저장 아키텍처 재검토 — Native API·보존·복구 관문

2026-10-26. 상태: **설치 소스 조사·50 Episode 비교·호환성/장애 반례 재현 완료. 제품 전환은 BLOCKED.**

권장 방향은 **C: 단계별 공식 Native 포맷 + 필요한 최소 실행 Metadata**다. A의 자체 저장 포맷을 다음 엔진 연결의 기본으로 계속 확장하는 것은 권장하지 않는다. 다만 아래의 실제 반례 때문에 **C가 전체 요구를 충족한다고 최종 확정하지 않았고**, 사용자 지시의 “중대한 데이터 보존/Resume 문제가 있으면 보고하고 중단” 조건을 적용했다. 기존 제품 구현을 완료했다는 이유로 A를 채택한 것이 아니다. 대체물이 검증되기 전에 동작하는 제품 저장 코드를 삭제하거나 미검증 Native 구현으로 바꾸지도 않았다.

이번 변경은 이 보고서·현재 계획의 검토 관문·[조사 증거](evidence/native-data-review/verification.json)뿐이다. EpisodeWriter/Reader·Index·Descriptor·Migration/참조 저장 및 R 호출부는 **제거/수정하지 않았다**. 새 Native 제품 Writer·Wrapper·Adapter·fallback·중간 Dataset 포맷도 없다. 임시 실험 포맷은 증거 harness 안에서만 만들고 삭제했다. BU/E·실물·Trainer·Hub 작업은 시작하지 않았다.

## 1. 먼저 해결해야 하는 실제 차단 문제

### NATIVE-01 — LeRobot 0.4.1 설치본의 Episode 선택과 학습 경계

실제 50 Episode/21,284 frame으로 공식 LeRobotDataset을 생성·finalize·다시 읽었다. `episodes=[0]`은 404 frame, `[49]`는 459 frame만 보여야 하지만 **둘 다 21,284 frame/0~49 전체 Episode를 노출**했다. `num_episodes`만 1이었고 val `[49]`의 첫 item도 Episode 0이었다. 이는 추측이나 문서 비교가 아니라 실제 공개 생성자/`hf_dataset`/`__getitem__` 관찰이다. [결과](evidence/native-data-review/lerobot-api-results.json)

설치된 `load_hf_dataset`은 모든 Parquet을 읽고 선택 필터를 적용하지 않는다. `factory.make_dataset`은 episodes를 생성자에 넘길 뿐이다. 기본 Trainer의 EpisodeAwareSampler 호출도 `episode_indices_to_use`를 전달하지 않는다. 따라서 해당 선택값만으로 공식 학습의 train/val 격리를 보장할 수 없다. 실제 학습을 실행한 결과라고 확대하지 않는다.

공식 `split_dataset`으로 **별도 물리 Dataset**을 만들면 404/459 frame으로 올바르게 분리되는 것은 확인했다. 그러나 해당 경로는 수치 데이터를 복사·재색인하고, 영상이 있으면 `_keep_episodes_from_video_with_av`에서 decode/re-encode한다. “그냥 episodes 파라미터를 쓰면 복사 없는 Curation이 된다”거나 “공식 split은 항상 영상 무손실 참조다”라고 설계할 수 없다.

공식 HF `Dataset.select/filter` 또는 EpisodeAwareSampler의 선택 인자는 쓸 수 있는 후보지만, 현재 공식 train factory에 이를 연결할 공개 주입 인자가 있는 것은 아니다. 공식 Trainer/설치 환경을 패치하거나 호환 Dataset/Trainer를 몰래 추가하지 않았다. **영상 바이트를 공유하고 필요한 수치 재색인만 하는 Native materialization**도 후보이나, 현재 고정 API에서 실제 학습 경계까지 검증된 해결책으로 보고하지 않는다.

### NATIVE-02 — Native save/flush와 Episode commit·Resume는 같지 않음

[실제 API 장애 시험](evidence/native-data-review/crash-results.json):

- Isaac 공식 `write_episode`에서 두 번째 Episode의 관측 배열 쓰기에 OSError를 주입했다. 재개방 시 Episode 수는 2이고 불완전 `demo_1`이 노출됐다. `success=True` attr는 배열보다 먼저 쓰여 있어 부분 Episode에도 남았다. 관측은 비어 있었다. 공식 Reader의 목록/개수/성공 attr만으로 완료를 판정하면 안 된다.
- LeRobot에서 `save_episode()`가 반환된 뒤 별도 시험 child에 SIGKILL을 보냈다. `info.json`은 완료 수 1을 광고하지만 데이터 Parquet footer와 Episode Metadata가 완결되지 않아 공식 Reader 재개방에 실패했다. 오프라인 설정으로 Hub fallback도 차단했다.
- 첫 Episode는 finalize한 뒤 같은 Dataset을 재개방하여 두 번째를 저장하고 SIGKILL한 경우도 시험했다. 첫 Parquet과 Meta Episode 파일은 남지만 새 Parquet footer가 없고, 이미 `meta/info.json`/`stats.json`은 갱신돼 **Dataset 전체 공식 재개방이 실패**했다. 이전 파일 bytes가 남는 것과 이전 완료 Dataset을 읽을 수 있는 것은 다르다.
- Isaac `open(r+)`는 demo_count를 모든 group 수로 설정하고 기존 env_args를 메모리 `_env_args`로 복원하지 않는다. 이후 `add_env_args`를 호출하면 기존 attrs를 작은 새 dict로 바꿀 수 있음을 임시 파일에서 확인했다. 이를 Workbench Resume 구현으로 그대로 쓰면 안 된다.

LeRobot `finalize()`는 필수이며 정상 완료 경로에서는 동작한다. 하지만 마지막 정상 finalize 한 번이나 Sidecar에 complete=true를 적는 것만으로 다음 쓰기의 장애까지 안전해지지는 않는다. **닫힌 Native shard/segment를 불변 보존하고 staging→검증→publish하는 경계**, 단일 출력 소유권·미완료 제외·원본 불변 새 run Resume·중복 의도와 attempt history의 commit 순서를 먼저 구체화/검증해야 한다. 이것을 빌미로 폐기 대상 자체 Index/Descriptor를 새 이름으로 복제하지 않아야 한다. 현재 연구는 그 새 복구 구현을 만들거나 검증한 것이 아니다.

### NATIVE-03 — 기존 MP4를 공식 Dataset에 무손실로 연결하는 경계

실제 원본 H.264에서 decode한 RGB 8 frame을 공식 `LeRobotDataset.add_frame/save_episode` 기본 경로로 저장했다. 저장 경로는 `libsvtav1` 기본 encoder를 호출했고 결과는 AV1(libdav1d decoder)였다. **RGB 최대 차이 129**, decoded RGB exact=false였다. 해당 예제의 PTS/time_base는 일치했지만 영상 바이트/화질은 보존되지 않았다. 이 결과의 용량을 개선 수치로 사용하지 않았다.

설치 API에는 `create/add_frame/save_episode/finalize` 수준에서 이미 있는 MP4를 등록하고 원본 packet을 그대로 유지하는 인자가 없다. `_save_episode_video`는 임시 영상을 생성하고 concat/이동·메타데이터를 갱신한다. `LeRobotDatasetMetadata.save_episode`와 영상 utility를 사용한 **명시적 Native 변환**은 후보지만, private 경계·feature stats·shard index·timestamps를 중복/불일치 없이 연결하는 검증이 필요하다. 메서드 monkeypatch·가짜 image feature·비디오 key 누락·원본 재인코딩으로 통과시키지 않았다.

이 세 관문은 “Native 포맷이 원리적으로 불가능”하다는 주장이 아니다. **공식 API 기본 동작을 연결하는 것만으로 현재 요구가 충족되지 않으며**, 대체 경계가 검증되기 전 제품을 삭제/교체하지 않겠다는 중단 근거다.

## 2. 조사한 설치 소스와 실제 소비자

[소스 목록·SHA·함수 위치·호출부](evidence/native-data-review/source-inventory.json)를 기록했다. Isaac Lab은 `/home/hyeonhee/IsaacLab/VERSION=2.3.0`, 읽기 전용 git describe도 v2.3.0이다. core extension의 `__version__=0.47.2`를 Isaac Lab 배포 버전으로 혼동하지 않았다. LeRobot은 기존 환경의 0.4.1이다. Python3.11.15·NumPy1.26.0·Torch2.7.0+cu128·h5py3.16.0·datasets4.1.1·PyArrow25.0.1·av15.1.0을 변경하지 않았다.

| 공식 경계 | 확인한 실제 계약 | Workbench가 맡아야 할 최소 책임 |
|---|---|---|
| Isaac `EpisodeData` | nested Tensor, seed/env_id/success, action/state cursor·pre_export. 일반 독립 데이터 객체 | 엔진 상태/수학을 바꾸지 않고 기존 배열·phase·step 의미를 이 객체에 제공 |
| `HDF5DatasetFileHandler.create/open/load_episode/write_episode/flush/close` | `data/demo_N`, env_args, gzip Tensor arrays. Reader는 모든 leaf를 torch.tensor로 읽음 | 파일 수명·입력 identity·완료/불완료 경계. 문자열 등 지원 밖 데이터는 별도 근거로 보존 |
| Isaac `RecorderManager.export_episodes` | Env별 Episode.pre_export→공식 handler.write_episode, 성공/실패 export 모드·flush | Source에 성공 gate를 새로 넣지 않고 기존 stage별 의미 유지. 모든 엔진을 RecorderManager로 감쌀 이유 없음 |
| Isaac Source/Annotation/DataGen scripts·Mimic recorders | 공식 Recorder·초기 state·pre/post observation·datagen_info와 subtask signal | 기록된 initial과 원래 latch/boundary 시점을 전달. 공식 reset/termination 기본값을 기존 v8 의미로 추측하지 않음 |
| `DataGenInfoPool.load_from_dataset_file/add_episode` | 공식 HDF5 Episode·eef/object/target pose·subtask signals·env.actions_to_gripper_actions를 소비 | 기존 Source pool 순서/선택과 action gripper 의미·고정 Task binding을 명시 |
| LeRobot `create/add_frame/save_episode/finalize` | v3.0 Parquet frame data·tasks·stats·Episode metadata·MP4, 파일별 chunk/file index와 video offset | 공식 스키마/저장 API 사용, 원 의미를 확인한 명시적 변환. 새 중간 대용량 포맷은 필요 없음 |
| LeRobot `LeRobotDatasetMetadata` | Metadata buffer(기본10), info/stats 갱신과 Parquet writer 수명 별개 | SDK의 in-memory counter/파일 존재를 Workbench commit으로 오인하지 않음 |
| LeRobot Dataset/공식 split/delete/merge | constructor episodes 선택의 설치본 반례, 물리 split의 복사/영상 재인코딩 | 선택·제외/분할은 먼저 비파괴 선택 Metadata, 실제 소비자 격리와 필요한 export는 별도 검증 |

근거는 설치 파일 자체다. 교차 확인 링크: [Isaac HDF5 v2.3.0](https://github.com/isaac-sim/IsaacLab/blob/v2.3.0/source/isaaclab/isaaclab/utils/datasets/hdf5_dataset_file_handler.py), [Mimic Pool v2.3.0](https://github.com/isaac-sim/IsaacLab/blob/v2.3.0/source/isaaclab_mimic/isaaclab_mimic/datagen/datagen_info_pool.py), [LeRobot v0.4.1](https://github.com/huggingface/lerobot/blob/v0.4.1/src/lerobot/datasets/lerobot_dataset.py). LeRobot 고정 tag는 웹에서도 확인했다. 생성된 Isaac API 문서 URL은 도구로 접근되지 않아 설치 소스·고정 tag 근거를 사용했다. 최신 버전으로 결론을 대체하지 않았다.

## 3. A/B/C 비교와 권장 구조

| 기준 | A: Episode별 HDF5 + 자체 Index | B: 공식 포맷만 단계별 사용 | C: 공식 포맷 + 최소 실행 Metadata |
|---|---|---|---|
| 공식 호환성 | 내부 이름/파일 layout을 Mimic/LeRobot에 다시 변환해야 함 | 정상 지원 경로는 가장 직접적. 단 모든 기존 정보/완료 의미를 표현하지 못함 | Native API를 직접 소비하며 누락 의미만 보존. 차단 관문 해결 필요 |
| 데이터 복제 | 내부 포맷→Native→LeRobot 중간 저장 가능. 참조 export는 비복사이나 전용 Reader 필요 | 중간 자체 포맷 제거. 공식 split/영상 기본 저장은 복사·재인코딩 가능 | Native 자료의 선택은 Metadata 중심, 불가피한 공식 포맷 간 명시적 변환만 |
| 총 용량 | 이번 50개 87,993,579B. 원본 layout보다 큼 | 실제 선택/영상 경로에 따라 다름. HDF5/Parquet 하나가 항상 작다는 보장 없음 | HDF5+원본MP4+최소 보존 실험 75,895,734B. 전체 제품/5GiB 결과는 아님 |
| 속도·메모리 | 검증/해시/Descriptor 비용이 있고 자체 유지보수 필요 | 공식 구현 재사용. Torch/Arrow import·buffer/cache 비용 존재 | 이번 write는 A보다 빠르지만 프로세스 Peak RSS는 증가. 복구 경계가 아직 다름 |
| Curation | 기존 자체 참조 index/view에 묶임 | 설치본 episodes 선택 반례·공식 split 재인코딩 | 비파괴 선택과 Native 소비자에 전달되는 격리를 함께 검증해야 함 |
| Resume/장애 | 당시 자체 transaction 시험이 있음. Native에 그대로 연결되지 않음 | Native save/flush만으로 완료/원본 불변 재개 보장 없음 | 최소 실행 Sidecar + 불변 Native publish 경계가 필요. 아직 미검증 |
| 유지보수·연결 비용 | 독자 Writer/Reader/Migration와 두 Native 경계 유지 | 가장 작지만 정보를 누락하면 요구 위반 | 불필요한 독자 저장을 없애고 필수 provenance/안전성만 보유하는 방향이 적합 |

**C를 우선 후보로 선택한다. 단 생산 구조로의 최종 채택·전환은 NATIVE-01/02/03 통과 전까지 보류한다.** B는 필수 의미/안전성을 생략하면 채택할 수 없고, A는 “이미 구현됐다”는 이유로 유지할 근거가 되지 않는다.

단계별 후보 배치:

- Source/Annotation/Mimic DataGen: 공식 Isaac HDF5의 배열·initial state·datagen_info·signal을 직접 사용한다. RGB를 HDF5에 무조건 raw tensor로 중복 저장하면 기존 MP4 대비 큰 용량 증가가 생길 수 있으므로 자동 선택하지 않는다.
- MuJoCo Source/DataGen/Simulation Evaluation: 소비자가 Mimic/정밀 재생이면 **같은 공식 HDF5 데이터 계약**을 쓸 수 있다. handler/CPU EpisodeData는 실제로 Sim app 없이 import·사용했다. 포맷이 Isaac 계열이라는 이유로 MuJoCo 실행기를 Isaac Env로 감싸거나 Gym step을 통일할 필요는 없다. 도구 의존성과 엔진 실행 의존성은 구분한다.
- 실제 로봇의 policy용 수집/평가: LeRobot 장치·Dataset이 자연스러운 후보다. 그러나 model rad·raw/native·requested/applied·host time와 공식 policy feature/정규화는 구분한다. 명시적 보정/부가 telemetry가 공식 feature로 표현 가능한지 먼저 매핑해야 하며, simulator 초기 상태를 억지로 요구하지 않는다. 실제 장치나 새로운 포맷 수집을 시험한 것은 아니다.
- 학습/오프라인 검증: 공식 LeRobotDataset/processor/Trainer. HDF5→LeRobot의 필요한 명시적 변환은 허용하되 그 사이에 Workbench bulk format을 두지 않는다. 데이터 보존용 원본과 공식 학습 item의 float32 도출을 구분한다.

Sidecar 후보는 Recipe/Scene·Calibration·Task/IK code identity, seed/attempt history, lineage/selection·partition 서명, 단위/frame/phase·가용성, 실행 outcome·영상 참조/PTS 근거와 Native Tensor 밖 진단이다. joint/image/pose 같은 원래 대용량 수치 payload를 Sidecar로 복제하거나 자체 array Descriptor/Writer를 되살리는 용도가 아니다. 과거에 없는 Scene hash·RNG state·requested telemetry를 새로 만들어 넣지 않는다.

## 4. 실제 보존·Mimic/LeRobot 호환성

### Isaac/Mimic

[실제 Reader/Pool 결과](evidence/native-data-review/isaac-api-results.json): B02의 17개 대표 HDF5 첫 Episode 중 15개는 공식 Reader에서 **490개 배열 값/dtype/shape**가 그대로 읽혔다. DataGen 2개는 `ik/failure_reason: |S64` 때문에 torch 변환에서 거부됐다. 고정 문자열 배열을 삭제하거나 float로 cast하지 않았다.

원래 배열 key·dtype·shape를 그대로 공식 EpisodeData에 넣고 S64만 별도로 보존한 임시 실험은 공식 Reader/Pool에서 읽혔다. 50개 실제 DataGen에서는 **3,000개 Tensor 배열 + 50개 S64 배열**, seed/IK/lineage 등 모든 기존 root/data/Episode attr를 보존했다. [Metadata 실험](evidence/native-data-review/metadata-results.json)의 gzip Sidecar는 308,240B였으며 문자열의 원 dtype/shape/bytes까지 roundtrip했다. 이는 최종 Sidecar Schema나 transaction 구현을 확정한 결과가 아니다.

실제 Annotation MuJoCo/Isaac/manual 각1개를 공식 Pool에 직접 입력했다. first grasp 저장 frame은 223/222/203이고, 공식 half-open subtask 끝은 224/223/204다. B01의 자동 physical post tick 222/221→저장 frame223/222와 manual boundary를 바꾸지 않았다. Pool의 first1+1 slice 끝을 물리 판정 tick으로 해석하지 않는다. 기존 reference Pool도 같은 +1 식을 쓰는 것을 소스로 확인했다.

Pool/DatagenInfo는 설치된 **수정하지 않은 실제 모듈**이다. eager datagen/__init__의 simulator import를 피하려고 조사 namespace path로 해당 child module을 로드했고, 최소 gripper-action callback fixture를 제공했다. 공식 HDF5 Reader/EpisodeData는 정상 import다. 이를 전체 Mimic Environment/IK/physics 연결 완료로 확대하지 않는다.

### LeRobot

[실제 API 결과](evidence/native-data-review/lerobot-api-results.json): 공식 create/add_frame/save_episode/finalize로 실제 50개의 measured joint·recorded target·원 timestamp 3개 feature를 저장/재개방했다. raw Parquet/HF 값은 float64로 exact였다. 그러나 공식 `__getitem__`은 list를 torch.tensor로 바꿔 float32를 반환했고 첫 state 최대 차이는 약 5.46e-8이었다. **Parquet가 float64를 못 저장한다는 뜻은 아니다.** dtype 보존용 raw read와 공식 학습용 item 변환을 분리해야 한다.

해당 LeRobot 실험은 수치 projection만이다. 영상·initial state·Mimic plan/IK 전체를 포함한 완전한 대체 Dataset 또는 정책 학습 가능성 검증으로 보고하지 않는다. action feature에 넣은 recorded target은 model rad의 저장 실험이며 기존 policy action 의미/그리퍼 단위를 확정한 변환이 아니다.

### 영상·순서·기타 의미

[100개 MP4 계약](evidence/native-data-review/video-contract-results.json)은 실제 50 Episode 양 camera의 **42,568 frame** 전체 PTS·FPS30·640×480·SHA를 읽기 전용으로 확인했다. 비교 출력의 100개 MP4는 원본 bytes SHA와 같았다. 재인코딩/해상도 저하/프레임 누락으로 용량을 줄이지 않았다. B02의 dtype·phase·관측/명령·initial·seed/IK/lineage 원문은 보존 실험과 원 Metadata 대조로 확인했다. 실제 새 run Resume나 engine 재생으로 검증했다고 주장하지 않는다.

## 5. 50 Episode 저장·속도·메모리 비교

동일한 실제 DataGen **50 Episode/21,284 control frame/두 camera**, warm-cache 로컬 filesystem, 별도 Python process로 측정했다. [측정 결과](evidence/native-data-review/benchmark-results.json), [실행 코드](evidence/native-data-review/benchmark.py).

| 경로 | 총 저장 bytes / MiB | 파일 수 | 생성/저장 s | 검증 읽기 s | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|
| 기존 원본 layout의 HDF5 group·MP4 copy | 77,469,473 / 73.881 | 101 | 0.166 | 0.958 | 113.004 |
| 현 Workbench A의 실제 migration·commit | 87,993,579 / 83.917 | 202 | 20.183 | 1.852 | 221.688 |
| 공식 HDF5 + 원 MP4 + gzip 보존 Metadata 실험 | 75,895,734 / 72.380 | 102 | 1.378 | 2.070 | 584.711 |

Native 실험의 bytes는 A 대비 **약13.75% 감소**, 원본 layout 대비 **약2.03% 감소**다. 그러나 공식 write의 장애 보장은 A의 transaction과 같지 않으므로 **동등하게 안전하면서 14배 빠른 제품**이라고 결론내리지 않는다. 원본 copy도 수집 Writer의 내구성·검증 전체를 수행한 timing이 아니다. 현재 A는 3,050개 배열 및100 MP4 bytes를 재검사했고 Native도 Tensor/별도 S64와 영상 모두 확인했다.

Native process의 Torch/Isaac import 후 baseline Peak는 약517.71MiB, 최종584.71MiB였다. A는 import 후74.34MiB, 최종221.69MiB다. baseline 차이를 포함한 Peak 증가를 숨기지 않는다. 이미 Torch가 있는 engine process에서의 추가 작업량이나 GPU 메모리/실시간 수집 성능으로 환산하지 않는다.

LeRobot 3-feature projection은 2,831,176B/5파일, 저장·finalize5.648s·검증읽기0.157s·Peak861.34MiB였다. **영상/나머지 배열이 없으므로 위 전체 Dataset의 용량 개선 비교에 쓰지 않는다.** HF Arrow cache는 실험 공간의 별도 cache에 생겼고 비교 데이터 디렉터리 bytes에 포함되지 않는다. 누적 cache를 특정 포맷 한 번의 순수 용량으로 혼합하지 않는다. 임시 Dataset 출력은 제거했고 재현 harness/JSON/log는 남겼다.

**5GiB 실자료 workload는 실행하지 않았다.** 위 50개 자료에 대한 수치이며 “기존5GB가 항상 더 커지지 않는다”는 보장은 없다. shard 크기/메타데이터·Arrow cache·배포용 materialization·복구용 임시 파일·두 공식 포맷을 함께 보유하는 경우가 용량을 늘릴 수 있다. 최종 C의 단일 보유 원칙·encoded video 공유/명시 export·불변 publish 경계를 정한 뒤 실제5GiB급 자료로 확인해야 한다.

## 6. 제품 정리·호출부 변경의 예정 범위와 현재 상태

대체물을 확정하면 제거할 대상은 새 Workbench의 `data/episodes.py` 자체 Reader/Writer/Index/Descriptor/Resume/reference export, 그에 묶인 `migration.py`, `data/video.py` 중 대체되는 encoding/해시 연결과 과거 전용 테스트다. 단 공식 API에 없는 필수 media 수명/소유권까지 근거 없이 삭제하는 결정은 하지 않는다. 기존 P/B/Baseline/실제 Dataset·완료 보고서/증거는 항상 보존한다.

현재 A는 canonical `observations/...`, `commands/...`를 Episode별 HDF5에 기록하므로 `data/demo_N/obs/datagen_info` 소비자인 공식 Reader/Pool에 바로 연결되지 않는다. A→Mimic HDF5와 A→LeRobot 변환을 추가하면 독자 포맷이 중간 비용으로 남는다. C가 검증되면 이런 중간 계층을 제거하는 것이 맞다.

R 호출부 영향은 다음과 같다. [전체 참조 목록](evidence/native-data-review/source-inventory.json)의 제품/시험14개 파일에 기록했다.

- recipe.py: dataset.json/open_dataset/DatasetIdentity/파일 hash helper 의존을 Native 파일·공식 Metadata·선택/실행 identity 경계로 교체.
- run.py: 완료 Episode IPC 검증과 StageResult 개수 확인을 Native의 검증된 완료 publish 경계로 교체. 단순 get_num_episodes/total_episodes로 대체하면 이번 반례가 재현된다.
- D01~D04 전용105개 시험은 폐기 포맷과 함께 정리하고 Native 호환/보존/장애 시험으로 대체. R의 실제 fixture worker/SIGKILL 시험도 새 Native 경계로 바꿔야 한다. 기존 test를 통과시키는 호환 Wrapper는 만들지 않는다.
- RO/Scene/Task 계산은 저장 서비스에 묶을 필요가 없다. 기존 pure 계산·물리 의미는 유지하고 Capture의 snapshot/host-time 계약과 Episode bulk format을 혼합하지 않는다.

이번에는 **위 제품 파일과 기존 테스트를 하나도 수정/삭제하지 않았다.** 새 제품 구현 파일도 없다. 기존647개 PASS 증거와 현재 제품/시험 SHA가 그대로인지 확인했다. 제품 변경이 없어 동일 suite를 중복 실행하지 않았으며, 이번 Native probe를 기존 제품 회귀 재실행으로 보고하지 않는다.

## 7. 재개 전 관문·보존·남은 실행 검증

| 관문 | 확인할 결과 | 현재 |
|---|---|---|
| NATIVE-01 | 공식0.4.1 학습 경계까지 train/val membership 정확, 원 encoded 영상의 불필요한 복제/재인코딩 없음 | **BLOCKED** — constructor 선택 반례. 수치 physical split만 정상 확인 |
| NATIVE-02 | 닫힌 이전 Native 자료 불변, 오류/SIGKILL 후 공식 Reader 재개방, incomplete 성공 노출0, idempotent Resume/attempt/IK 비교 | **BLOCKED** — 기본 write/save/flush 반례. 최종 최소 publish/복구 설계·시험 미완료 |
| NATIVE-03 | 원 MP4 packet/RGB/PTS/FPS/크기 보존하며 공식 LeRobot reader·metadata·feature stats 일치 | **BLOCKED** — 기본 경로 재인코딩. 무손실 import/영상 공유 경계 미완료 |

Sidecar의 필요성 자체는 S64/lineage/identity 보존 실험으로 확인했다. 이 Sidecar를 복구·완료 protocol까지 포함한 검증된 최종 설계라고 주장하지 않는다. 해결 후보는 닫힌 Native segment의 publish, Native split materialization에서 수치만 필요한 만큼 재색인하고 영상 packet을 공유하는 방식, pinned 공식 Metadata/utility 기반 명시적 importer다. 최종적으로 직접 필요한 공식 API만 쓰며 자체 Index·Descriptor·Reader 호환 계층을 되살리면 안 된다.

[보존 대조](evidence/native-data-review/preservation-after.json)는 기존 56,100개 파일 stat·선택 SHA·B01~RO03/D/R 증거/보고서·현재 제품/시험을 확인한다. 조사 입력 및 설치 소스의 SHA도 별도 대조했다. 전체 corpus/SDK binary의 전수 byte 증명은 아니다. 설치/업그레이드·환경 분리·원본 수정·실제 Dataset 변경·로봇/카메라 연결·SDK 모터 명령·Hub 업로드는 없다. 폐기 가능한 실험 child만 SIGKILL했으며 실제 worker/장치 프로세스는 건드리지 않았다. 초기 영상 probe의 camera key 가정 오류는 실제 Metadata key로 고쳤고 최초 로그를 남겼다.

B01 Isaac DataGen 실패/Evaluation 비결정성·B02 과거 누락/정책별 Resume·B03 실물·ASSET-FINGER-01은 그대로다. Native CPU Reader/Pool 검증은 공식 engine state restore·IK/물리/렌더·새 영상 수집 검증을 대체하지 않는다. **이번은 데이터 아키텍처 재검토의 차단 결과 보고이며 BU/E나 다음 구현 묶음을 시작하지 않는다.**
