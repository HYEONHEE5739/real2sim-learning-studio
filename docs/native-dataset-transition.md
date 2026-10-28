# C Native Dataset 전환 — 구현·보존·선택·복구

2026-10-26. 상태: **C 전환 구현과 파일·공식 CPU 소비자 검증 완료**. 사용자 최종 결정에 따라 이전 A 자체 저장을 교체했다. BU/E·실물·UI·Trainer 실행은 시작하지 않았다. [이전 조사·차단 보고](dataset-storage-review.md)와 B01~RO03·D/R의 보고서/증거는 수정하지 않았다.

## 1. 최종 구조와 공식 재사용

- Source/Annotation/Mimic 생성 및 필요한 MuJoCo 자료는 설치 Isaac Lab **2.3.0의 실제 EpisodeData/HDF5DatasetFileHandler**를 사용한다. 여러 Episode가 들어갈 수 있는 불변 HDF5 segment이며 엔진 앱이 없어도 CPU 자료 API를 사용한다.
- Workbench는 파일 수명과 공식 포맷 밖 정보만 맡는다. 작은 run.json, 한 번 압축하는 provenance.json.gz, segment의 ID/lineage/phase·영상 위치·지원 밖 S64·attempt Metadata다. 자체 배열 인코더·per-Episode Descriptor·완료 Index·중간 bulk 포맷은 없다.
- Curation은 원본과 구별되는 영구 JSON 선택/순서/half-open frame range/분할이다. 학습 시에만 정확한 선택 row를 공식 LeRobot **0.4.1 Parquet/MP4/Metadata**로 materialize한다. 실제 로봇용 신규 수집은 공식 Device/Dataset recording 경계를 사용하며 실제 장치 연결은 이번 범위가 아니다.
- 기존 MP4는 재인코딩 없이 hardlink하고 공식 video offset으로 구간을 연결한다. 독립 Export일 때만 copy한다. 다른 filesystem의 link 실패는 명시 오류이며 silent copy/fallback은 없다.

설치 소스·버전·SHA는 [기존 조사 목록](evidence/native-data-review/source-inventory.json)과 [이번 검증](evidence/native-dataset/verification.json)에 연결했다. [Isaac 공식 handler](https://github.com/isaac-sim/IsaacLab/blob/v2.3.0/source/isaaclab/isaaclab/utils/datasets/hdf5_dataset_file_handler.py), [공식 Mimic Pool](https://github.com/isaac-sim/IsaacLab/blob/v2.3.0/source/isaaclab_mimic/isaaclab_mimic/datagen/datagen_info_pool.py), [LeRobot 0.4.1](https://github.com/huggingface/lerobot/blob/v0.4.1/src/lerobot/datasets/lerobot_dataset.py)의 설치 파일을 그대로 사용한다.

기존 MP4를 기본 save_episode에 넣으면 AV1로 다시 인코딩되므로 converter는 버전 guard 아래 **공식 `_save_episode_data` + 공개 Metadata.save_episode + 공식 feature stats**를 직접 호출한다. private API 경계를 숨기지 않으며 SDK monkeypatch·Dataset/Trainer subclass·설치 수정은 없다. 기존 MP4 변환과 신규 RGB recording의 공식 create/add_frame/save_episode/finalize를 구분한다.

## 2. 제품 교체와 현재 API

| 파일 | 현재 책임 |
|---|---|
| [data/native.py](../robot_learning_workbench/src/robot_learning_workbench/data/native.py) | 공식 파일의 소유·불변 segment publish·복구/새 출력 Resume, 원래 Common HDF5/Canonical NPY의 명시 import |
| [data/curation.py](../robot_learning_workbench/src/robot_learning_workbench/data/curation.py) | 영구 Curation·재로드·재편집·선택/분할, 전체 Episode 독립 공식 Native export |
| [data/lerobot.py](../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py) | 선택 rows의 공식 Native materialization·원 MP4 offset·LeRobot staging/finalize/publish |
| [data/video.py](../robot_learning_workbench/src/robot_learning_workbench/data/video.py) | 새 RGB의 bounded PyAV streaming encoder만 유지. 기존 encoder class AST 동일 |
| [recipe.py](../robot_learning_workbench/src/robot_learning_workbench/recipe.py), [run.py](../robot_learning_workbench/src/robot_learning_workbench/run.py) | Native 입력/Scene identity와 완료 이벤트·StageResult 검사. train의 curated/raw HDF5 입력은 명시 materialization 요구 |

**제거:** 제품 data/episodes.py·migration.py, 자체 Reader/Writer/Index/Descriptor/reference export/array hash·영상 Reader/cache 계층과 전용 시험 8파일/105개. 폐기한 A 포맷 호환 함수·fallback은 남기지 않았다. 원래 P 프로젝트의 Common/Canonical import는 별개의 명시 도구이며 archive_only로 과거 누락 identity를 추측하지 않는다. [제거 목록](evidence/native-dataset/removed.json).

Workbench 패키지는 breaking 저장 API 변경으로 0.3.0이다. optional native extra는 LeRobot==0.4.1이며 설치/업그레이드는 하지 않았다. Isaac 데이터 도구는 고정 설치 소스 PYTHONPATH로 검증했다. 제품에 새로운 Manager/Framework/장치·엔진 추상화를 추가하지 않았다. 공식 API·작은 자료 타입/함수 계약은 [Interface §7](interfaces.md#7-native-episodecurationpublishresume)에 있다.

## 3. NATIVE-01 — 영구 Curation과 실제 소비자 격리

100개 합성 Episode의 원본에서 20개 제외 → V1의 80개 저장 → **별도 Python 프로세스 종료/재로드** → 10개 추가 제외 → V2의 70개 저장을 확인했다. 원본 100개의 전체 파일 SHA는 동일했고 Curation 버전마다 배열/영상 복사는 0이다. V1/V2 각각을 실제 공식 LeRobotDataset으로 만들어 **80/70 Episode, 400/350 frame**과 membership을 확인했다. 원본과 view는 Catalog.kind로 구분한다.

순서·frame range·train/val/test 분할은 JSON에 영구 보존한다. V2에서 V1 범위를 넓히거나 제외 항목을 자동 복원하지 않는다. 원본 이동/삭제/Metadata 변경은 CURATION_SOURCE_INVALID이며 명시 relocation도 같은 identity를 확인한다. 현재 UI 구현은 없다.

설치본 episodes 필터에 의존하지 않는다. 선택 rows만 담긴 공식 Parquet을 만들어 공식 **make_dataset와 DataLoader**가 정확한 Episode/범위만 소비하는 것을 시험했다. 실제 50개 자료의 Curation에서도 train **30 Episode/12,354 frame**, val **10/4,315**가 정확히 분리됐고 첫 선택 구간은 원본 frame10:30이었다. 원본 timestamp/frame index는 별도 source.timestamp/source.frame_index에 남고 공식 상대 시계/색인은 재구성한다. 실제 Trainer 최적화·학습 loop는 실행하지 않았다.

각 선택은 하나의 연속 half-open 구간이다. 중간 구간을 독립 물리 replay Episode로 만들 때 필요한 새 initial state를 만들어내지 않고 REPLAY_INITIAL_UNAVAILABLE로 차단한다. 구간 학습은 LeRobot materialize를 사용한다. 전체 Episode의 독립 Native export는 원 배열/원 MP4/global provenance를 보존하며 실제 copy를 수행한다. 불연속 구간 접합·GOP 중간 독립 MP4 crop/remux/re-encode는 구현하지 않았다.

## 4. NATIVE-02 — 정상 경로·publish·Resume

정상 경로는 공식 EpisodeData.add/pre_export/write_episode·flush/close를 사용한다. 알고 있는 time-series T/shape, 닫힌 영상 header의 count/FPS/해상도와 공식 HDF5 header를 확인한다. **매 Episode 전체 SHA·영상 전체 decode·과거 완료 자료 재해시는 없다.** 큰 원 provenance는 매 segment에 반복 저장하지 않고 한 번 gzip 보존한다.

완료는 segment의 official close → known-count/header → fsync → segment Metadata → 디렉터리 atomic rename이다. write_episode의 demo key는 pending이며 여러 Episode가 같은 segment에 있으면 publish 전까지 모두 pending이다. segment 수명은 성공/seed/RNG 수명과 다르다. LeRobot은 새 staging 전체를 finalize하고 Parquet footer/count를 확인한 뒤 publish한다. 이미 finalized한 이전 root에 쓰지 않는다.

검증된 실패 경계:

- 실제 h5py/Parquet Writer **OSError**를 주입해 부분 쓰기를 재현했다. pending은 완료 목록/성공으로 노출되지 않고 이전 published 파일 bytes가 동일했다.
- 폐기 가능한 child만 **SIGKILL**했다. 공식 HDF5 Reader는 이전 segment를 다시 읽었고, 이전 finalized LeRobot Dataset도 재개방됐다. 새 Parquet staging은 성공 Dataset 경로에 존재하지 않았다.
- 같은 intent/같은 요청은 기존 결과, 다른 요청은 conflict다. rename 후 ACK 유실도 같은 intent 재조회로 완료 1개를 확인한다. 불명 pending은 자동 재시도하지 않는다.
- inactive owner·Scene/Calibration/Task/model/engine/기록 frame·phase·unit·joint/active set/partition/RNG·seed를 비교하고 DataGen의 annotated input/source pool/IK code·model/frame/parameters/safety/측정 seed reference를 요구한다. 누락과 SciPy/Strict/Hold·다른 identity는 새 출력 생성 전에 거부한다.
- accepted attempt와 완료 Episode ID/개수, 누적 목표·전역 budget을 비교한다. Source partition은 이어 수집을 막는다. Source seed wrap과 DataGen1047/attempt1→892243098 및 다음 attempt를 검증했다.
- pending attempt는 명시 recovery acknowledgement 후에도 **interrupted_unknown**이다. 이전 seed를 재실행하거나 성공으로 승격하지 않는다. 새 run으로 닫힌 segment를 공유하며 이전 파일을 append하지 않는다.

과거 archive의 누락 runtime identity·RNG 전체 state를 만들지 않는다. B02의 원래 Source discard/옛 Resume seed 제한과 새 명시 claim continuation을 구분한다. old Source/DataGen이 새 정확 Resume로 소급 승격되지 않는다. Annotation/Evaluation 또는 물리 중간 tick continuation은 없다. 로컬 filesystem atomic rename/fsync 범위이며 NFS·전원 장애·사후 디스크 손상 전수 탐지 보장이 아니다. 원본/링크된 파일은 불변으로 사용해야 한다.

## 5. NATIVE-03·B02 의미·공식 Mimic

[보존 probe](evidence/native-dataset/preservation-probe.json)에서 B02 **Common17개 첫 Episode/612 배열**, Canonical **9개/104 배열**의 값·dtype·shape·bytes와 원 attrs/근거를 확인했다. numeric은 공식 HDF5/CPU Reader로 읽고 S64는 dtype/shape/원 bytes의 압축 Metadata로 보존했다. 요청/적용/측정값을 합치거나 누락 값을 채우지 않았다. 원래 initial·opaque replay·Mimic plan·seed/lineage·IK 진단/attempt history를 보존했다.

자동 Annotation의 MuJoCo post tick222→저장223, Isaac221→222, manual203은 그대로다. 공식 Pool의 half-open 끝224/223/204와 물리 판정 tick을 구분한다. 실제 설치 Pool/DatagenInfo를 사용했으며 eager simulator import만 namespace path로 피하고 gripper-action callback fixture를 제공했다. [50개 전체 Pool 입력](evidence/native-dataset/mimic-pool.json)은 5개 Native segment에서 명시적 기존 HDF5 lexical source pool 순서로 로딩했다. 실제 엔진/IK 연결 시험은 아니다.

50개 자료의 **3,050개 배열과 100개 원 H.264 MP4 bytes**를 별도 오프라인에서 대조했다. 원 bytes이므로 PTS/FPS/해상도/packet 순서를 바꾸지 않았으며 [기존 전수 PTS 근거](evidence/native-data-review/video-contract-results.json)도 보존했다. 선택 구간은 official video chunk/file/from_timestamp로 연결하고 공식 item의 실제 decoded RGB가 원 구간과 exact인 것을 확인했다. MP4 파일에 범위 밖 packet이 남는 것과 학습 row 노출은 다르다. 독립 copy도 재인코딩하지 않는다.

Raw Parquet의 float64 state/target/time은 exact였고 공식 __getitem__의 float32 변환은 공식 학습용 도출이다. 보존 원본을 float32로 덮어쓰지 않는다. 기본 학습 feature는 model rad 관측/기록 target projection이며 그리퍼 fraction·별도 측정 applied action으로 주장하지 않는다. 실제 Policy/processor action 의미는 L/P 통합에서 확인한다. 기존 HDF5의 나머지 initial/IK/plan을 Parquet projection이 모두 담는다고 주장하지 않는다. Embedded-image import·VFR/비정수 FPS 변환은 명시 미지원이며 영상 feature를 조용히 누락하지 않는다.

## 6. 50 Episode 용량·처리 비용

동일한 실제 DataGen **50개/21,284 control frame/두 카메라**다. 압축 품질·수치 정밀도를 낮추거나 배열/영상을 누락해 줄인 수치가 아니다. [전체 측정](evidence/native-dataset/benchmark.json), [기록 비용](evidence/native-dataset/record-cost.json), [디스크 상세](evidence/native-dataset/disk-accounting.json).

| 경로 | Dataset 논리 bytes / MiB | 파일 수 | 생성/변환 s | 프로세스 Peak RSS MiB |
|---|---:|---:|---:|---:|
| 이전 원본 layout group-copy 기준 | 77,469,473 / 73.88 | 101 | 0.166 | 113.00 |
| 폐기한 A 실제 migration/commit | 87,993,579 / 83.92 | 202 | 20.183 | 221.69 |
| **이번 C 공식 Native, 10 Episode×5 segment** | **76,018,207 / 72.50** | **118** | **2.128** | **602.71** |
| C→공식 LeRobot 학습 projection + 원 MP4 | 59,051,360 / 56.32 | 106 | 47.173 | 962.72 |

앞 두 행은 보존된 **이전 측정값**이며 이번에 폐기한 코드를 다시 실행하지 않았다. 같은 실제 입력 SHA/50개 자료다. 원본 group copy는 동일한 내구성 Writer timing이 아니고 A와 C는 완료 단위/수명·import 비용이 달라 속도 비율을 엔진 처리량 보장으로 해석하지 않는다. LeRobot 행은 학습 projection이며 전체 보존 archive와 같은 정보량의 용량 개선 수치로 사용하지 않는다.

C archive는 A보다 **13.61%**, 이전 원본 layout copy보다 **1.87% 작았다**. 공식 Torch import만으로 약537.46MiB였고 C 최종602.71MiB다. A보다 높은 Peak RSS를 숨기지 않으며 engine에 이미 Torch가 있는 경우의 추가 메모리나 GPU 메모리로 환산하지 않는다.

| 구분 | 측정 |
|---|---|
| 생성 중 공식 EpisodeData.add | 실제50개/830,076 time-series field sample, **2.645s**; pre_export stack **0.424s**, 원 값 exact |
| Episode 종료 후 공식 write+닫힌 media link/header | 50개 합계 **0.921s** |
| 5 segment close/fsync/최소 검증/publish | 합계 **0.252s** |
| 기존 자료 명시 import 전체 | **2.128s**, 원본 읽기/한 번의 입력 SHA·변환·write/commit 포함 |
| 별도 전수 arrays/media 오프라인 검증 | **1.460s**, 정상 commit 경로 밖 |
| 실제50 Curation V1(40개) 저장/재로드/V2(35개) 저장 | **0.103/0.045/0.095s**, JSON3546/3142B, bulk copy0 |
| 학습 materialization 전체50 / train30 / val10 | **47.173/26.917/9.414s**; 공식 stats용 선택 영상 decode·Parquet/Metadata·finalize 포함 |
| 신규 RGB 기록 입력388 frame×2 camera | append/backpressure **0.796s**, encoder close **0.049s**, 공식 수치 write **0.005s**, segment commit **0.023s** |

신규 RGB 행은 원 프레임 공급 decode를 timer 밖에 두고 기존과 같은 H.264 CRF18 encoder 수명을 측정한 것이다. 실제 camera/engine 시간도, 원 MP4 무손실 변환의 용량 비교도 아니다. 위 비용은 합계가 아니라 서로 분리한 측정이고 CPU/warm filesystem 조건이다.

**논리 크기와 실제 점유:** Native와 학습 Dataset 디렉터리의 단순 크기 합은 약128.81MiB지만 공유 MP4 inode를 한 번만 세면 75.41MiB, filesystem block 점유는 75.66MiB였다. 학습 projection의 별도 수치/Metadata가 약3.06MB 추가된다. 공식 Reader가 만든 21,284-row Arrow cache는 별도 약3.44MB/3.29MiB block이다. cache는 Dataset bytes에 숨겨 포함/제외하지 않고 별도 집계했으며 이번 검증 cache는 측정 후 삭제했다.

실제 기존 입력 파일 자체(HDF5+100MP4)는 105,885,181B/100.98MiB이며 앞선 **재구성 group-copy 기준73.88MiB와 다른 물리 파일 크기**다. 기존 원본도 유지하고 Native와 학습 projection을 함께 두면 공유 영상을 제외해도 **123.25MiB block + Arrow cache**였다. 원본까지 유지하는 상황의 총 점유가 줄었다고 주장하지 않는다. 이번 임시 변환 결과는 삭제했으며 실제 원본은 변경하지 않았다.

**5GiB급 실측은 없고 비증가를 보장하지 않는다.** 두 공식 포맷의 수치 projection, 독립 export, filesystem link 지원/블록, 복구 staging, cache를 별도로 봐야 한다. 정상 기록의 비용을 줄이려고 영상/정밀도/보존 의미를 버리지 않았다.

## 7. 완료 증거·차이·남은 실행

- **604 passed, skip0**, 기존 Scene/Task/Robot/Recipe 회귀 포함. 과거647개 중 폐기 포맷105개를 제거했고 기존542개+새 Native60개+새 Recipe 경계2개를 검증했다. [JUnit](evidence/native-dataset/unit-tests.xml), [최종 로그](evidence/native-dataset/logs/54-final-suite.log). 공식 torchvision 영상 deprecation warning2개는 고정 SDK의 경고이며 환경을 변경하지 않았다.
- [wheel](evidence/native-dataset/build.json): 소스/config 일치·compile·isolated import·CLI/실제 unavailable-runner worker smoke PASS. 설치하지 않았고 폐기 코드가 wheel에도 없다. lint/type 도구는 프로젝트에 설정/설치되어 있지 않아 실행했다고 주장하지 않는다.
- [보존](evidence/native-dataset/preservation-after.json): 기존56,100개 파일의 size/mtime/symlink-target 대조 변화0. 15,518개 SHA 기준선에서 승인된 제품/테스트 교체만 제외하고 변화0. 전체 corpus/SDK binary 전수 byte 검증은 아니다. 공유 hardlink 생성/삭제에 따른 inode ctime·link count는 이 대조의 보장 대상이 아니다. 원본 Source/환경·과거 증거·보고서는 불변이다.
- [명령/identity](evidence/native-dataset/commands.json), [최종 확인](evidence/native-dataset/verification.json)에 source·probe·제품·시험 hash와 AC/관문을 연결했다. incremental-implementation/TDD의 작은 RED/GREEN 단위로 진행했고 Git 저장소 초기화/commit은 하지 않았다.

의도된 변경은 **저장 포맷/API·완료 단위·영구 비파괴 선택·명시 학습 materialization·정상 전수 검증 제거**다. Dataset identity는 payload SHA가 아닌 Metadata identity이며 임의 사후 손상을 항상 검출하지 않는다. 새 attempt claim/history가 명시돼 과거 누락을 추정하는 Resume는 거부한다. v8 계산·성공 조건·Calibration·dtype/phase·IK 정책은 변경하지 않았다.

남은 범위는 실제 양 엔진 기록/복원·Mimic 실행/IK·실시간 센서/렌더·장시간 다중 env/worker 부하·실제 정책 processor와 train/resume·Curation UI·독립 GOP crop/export·5GiB workload다. B01 Isaac DataGen 실패/평가 비결정성, B03 실물 안전성·ASSET-FINGER-01도 그대로 OPEN이다. **이번 Dataset 전환까지만 완료하고 BU/E나 다음 묶음은 시작하지 않는다.**
