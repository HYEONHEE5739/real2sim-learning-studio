# SPEC: 공식 Native Episode·영상·Curation·Resume

ID: `episode-data`. 2026-10-26 사용자 최종 C 결정에 따라 현재 명세를 교체했다. [과거 D01~D04](docs/episode-data-bundle.md)와 [Native 조사](docs/dataset-storage-review.md)는 보존된 이력이며, 현재 제품은 [Native 전환](docs/native-dataset-transition.md)을 따른다. 기존 원본·Baseline·설치 환경은 불변이다.

## 범위·파일 책임

공식 Isaac Lab 2.3 EpisodeData/HDF5DatasetFileHandler와 LeRobot 0.4.1 Parquet/Metadata/processor 계약을 사용한다. MuJoCo는 CPU HDF5 데이터 계약만 공유하고 Isaac 실행기에 종속시키지 않는다. 실물 정책 자료의 공식 LeRobot recording API와 저장 publish 경계는 분리한다. 엔진·실물·UI·Trainer 구현을 이번 완료에 포함하지 않는다.

| 제품 | 책임 |
|---|---|
| data/native.py | 공식 Native segment의 소유·close/publish·복구·Resume·원본 HDF5/Canonical 명시 import |
| data/curation.py | 영구 비파괴 membership/order/range/split, reload/재편집·독립 전체 Episode export |
| data/lerobot.py | 정확한 학습 rows의 Native materialization, pinned 공식 writer/stats/Metadata + 원 MP4 offset |
| data/video.py | 공식 API에 없는 bounded 새 RGB streaming encoder만 유지 |
| recipe.py/run.py | Native 입력 identity·기록 Scene/active set·완료 이벤트/StageResult 검사 |

자체 episodes.py/migration.py·Index·Descriptor·source_ref Reader·과거 전용 테스트는 제거한다. 폐기한 Workbench A 포맷 loader/Wrapper/fallback은 만들지 않는다. 원래 P 프로젝트의 Common HDF5/Canonical NPY import와 폐기한 A 호환을 혼동하지 않는다.

## 보존·정상 경로

[B02](docs/b02-episode-resume.md)의 값·dtype·shape·unit·좌표/Quaternion·pre/post phase·Action/관측/target·initial·seed/attempt·pool 순서·lineage·수동 mark·outcome을 보존한다. 공식 Tensor 밖 S64/attrs와 필요한 provenance만 압축 Sidecar에 둔다. requested/applied·속도·runtime hash·RNG state의 과거 누락을 합성하지 않는다.

여러 Episode를 공식 data/demo_N에 기록하고 segment의 공식 close/flush → header/known-count → fsync → atomic directory publish로 완료 확정한다. 그 전 write_episode 반환은 pending이다. 매 Episode payload SHA·영상 전체 decode·기존 완료 재검증은 하지 않는다. 닫힌 MP4 header의 count/FPS/해상도만 정상 기록에서 검사하며 전수 bytes/PTS 대조는 별도 오프라인 증거다. 성공 조건을 새로 계산하지 않는다. 정상 완료 failure Evaluation도 공식 success=false로 완료될 수 있다.

## Curation·학습 격리

원본/curated/공식 LeRobot은 Catalog.kind로 구별한다. V1은 source identity·선택/제외 결과·순서·half-open frame range·분할만 JSON에 영구 저장한다. V2는 V1 범위 안에서 좁힌 선택이다. 다른 프로세스 reload 후 제외 자료가 복원되지 않는다. 이동/삭제/Metadata 변경은 명시 오류이며 identity-checked relocation만 허용한다. UI는 후속 구현이다.

설치 LeRobot episodes 필터에 의존하지 않는다. 명시 materialization으로 선택 rows만 official Parquet에 넣고 순서/frame alignment·episode boundary·source.frame_index/source.timestamp를 유지한다. 공식 상대 timestamp 재색인과 원 timestamp는 별도다. 공식 factory/DataLoader 소비까지 membership을 확인한다. 공식 __getitem__의 float32 도출과 raw Parquet의 원 float64 보존을 구분한다.

MP4는 원 bytes hardlink + 공식 video chunk/file/from_timestamp로 연결하고 재인코딩하지 않는다. 독립 export만 copy한다. 중간 GOP를 독립 clip으로 잘라 packet-copy 또는 재인코딩하는 기능은 제공하지 않는다. full MP4의 범위 밖 packet 보유와 학습 row 노출은 다르다. 중간 frame을 새 물리 initial로 해석하는 Native replay export는 차단한다.

공식 0.4.1 `_save_episode_data`가 필요한 부분은 버전 guard·source 근거를 명시한다. 공개 Metadata.save_episode/공식 feature stats를 사용하며 SDK/Trainer monkeypatch·subclass·설치 수정은 없다. 기존 MP4에 공식 기본 save_episode encoder를 호출하지 않는다.

## 장애·Resume

단일 출력 owner, 배타 intent claim과 payload identity, published intent 재조회로 중복 생성을 막는다. claimed/pending 결과 불명은 NATIVE_STATE_UNKNOWN이며 시간 초과 자동 재실행이 없다. OSError·SIGKILL 뒤 staging은 완료로 보이지 않고 이전 published Native는 공식 Reader로 재개방 가능해야 한다. LeRobot은 새 staging 전체를 finalize/Parquet footer 검사한 뒤 publish하며 기존 finalized root에 append하지 않는다.

Source/DataGen만 파일 경계 재개한다. 이전 owner inactive, 정확한 engine/Scene/Calibration/Task/model/recording/active set/seed/partition/RNG, DataGen annotated input/pool/IK code·model/frame/joint order/parameters/safety/seed reference를 요구한다. Source partition 잠금, 누적 budget·완료/history 개수 일치를 새 출력 효과 전에 검사한다. 불명 attempt는 명시 acknowledge 후 interrupted_unknown으로 소비하며 자동 성공·같은 seed 재실행은 없다. SciPy/Strict/Hold/불명 IK는 고정 Pinocchio DLS + Best Effort continuation이 아니다.

Archive import의 과거 누락은 그대로 사용 제한으로 남긴다. Annotation/Evaluation·중간 physics tick continuation, 전체 RNG checkpoint, 새 엔진 재현은 제공하지 않는다. Local filesystem rename/fsync 조건만 검증하고 NFS·전원 장애·사후 디스크 손상 전수 탐지를 약속하지 않는다.

## 완료 기준과 명령

- **episode-data-AC01**: 실제 B02 Common17/612 배열·Canonical9/104 배열, phase/annotation/attrs/영상 bytes·initial/lineage 보존. 실제 공식 HDF5 Reader/Mimic Pool 입력.
- **episode-data-AC02**: partial OSError/SIGKILL·재개방·미완료 노출0·이전 완료 보존·중복 intent/불명 결과 차단.
- **episode-data-AC03**: identity/IK/partition/history/budget Resume 검증, 100→80→70 영구 Curation과 실제 공식 Dataset membership/frame 격리, 50 실제 Episode의 저장·conversion/commit/Curation/materialization 비용 측정.

```bash
bash docs/evidence/native-dataset/run_tests.sh scene_contract/tests robot_learning_workbench/tests -q
```

현재 결과와 AC별 증거는 [전환 보고](docs/native-dataset-transition.md)에 기록한다. 이전 105개 폐기 포맷 테스트를 유지하기 위한 호환 구현은 없다. 실물·엔진 재생/IK/렌더·공식 학습 최적화·UI·장시간 병렬 부하는 후속 범위다. 기존 v8 판정/B01 실패와 비결정성·B03 실물 OPEN을 변경하지 않는다.
