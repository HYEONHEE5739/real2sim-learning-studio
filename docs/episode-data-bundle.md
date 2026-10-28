# Episode Data 묶음 — D01~D04

2026-10-26. 상태: **D01~D04 파일/오프라인 범위 구현·검증 완료**. B02의 DATA-01/03·V8-04 근거를 사용했고, DATA-02/04는 구현 후 장애/부하 관문으로 확인했다. 엔진·장치·Recipe·UI·공식 LeRobot 변환을 선행조건으로 확대하지 않았다. 관련 작업을 순차 진행했으며 두 번째 묶음은 시작하지 않는다.

## 완료 기능과 파일

| Task | 구현·검증 |
|---|---|
| D01 | 불변 index snapshot·페이지 reader·부분 배열 읽기. Common /2 및 Canonical /1의 명시적 필드 매핑·새 출력 변환. 실제 B02 자료의 dtype/값/영상·lineage 보존 |
| D02 | Episode별 HDF5/영상 staging, 수치 즉시 소유·bounded RGB copy, 검증/flush·publish·atomic index commit, 동일 payload 재시도·다른 payload 충돌, 취소·오류·고아 보고 |
| D03 | 출력 생성 전 Resume 검사, Source/DataGen 예산·seed continuation, 명시 DLS identity 검사, 완료 Episode 참조·chain 평탄화·이동·독립 materialize export |
| D04 | 파일 소비자/누락·phase·unit 회귀, 실제 5/50 Episode 부하와 640×480 두 카메라 bounded 기록, 기존 경로와 처리량/메모리/파일 수 비교 |

제품 파일은 [data/episodes.py](../robot_learning_workbench/src/robot_learning_workbench/data/episodes.py), [data/video.py](../robot_learning_workbench/src/robot_learning_workbench/data/video.py), [migration.py](../robot_learning_workbench/src/robot_learning_workbench/migration.py), data/__init__.py 및 [패키징](../robot_learning_workbench/pyproject.toml)이다. 새 시험은 reader/migration/commit/video/failures/resume/export/consumers의 8개 파일이다. 각 세부 변경은 [묶음 범위](evidence/episode-data/scope.md)의 작은 단위로 검증했다. 기존 Task·Scene 구현/시험은 바꾸지 않았다.

기존 PyAV AsyncVideoWriter의 소유 copy·bounded queue·backpressure를 재사용했다. 영상 reader도 기존 exact CFR seek를 유지하고 context manager만 추가했다. 기존 Workspace/엔진/학습 코드를 새 제품에 import하지 않았다. 새 Manager·storage framework·변환 서비스·CLI는 없다. h5py>=3.14,<4와 av>=15,<16을 직접 의존성에 명시했으며 설치된 h5py3.16.0/PyAV15.1.0을 사용했다. 환경 설치·업그레이드는 없다.

## 저장·호출 계약

`EpisodeWriter(output, dataset_spec)`는 새 출력만 생성한다. Dataset spec은 stage/recording을 갖고, 실제 Resume에는 별도의 명시 execution identity가 필요하다. 동일 디렉터리의 writer 재개/과거 HDF5 append는 제공하지 않는다.

- `dataset.json`: schema_version=1, dataset_id, spec, 완료 EpisodeRefs, append-only attempt_history. 이 파일의 bytes SHA가 DatasetIdentity다.
- `episodes/<id>.h5`: 초기 상태·수치 배열. `episodes/<id>.json`: 필드 dtype/shape/SHA·단위/phase/가용성, metadata/lineage, media·outcome, HDF5 파일 identity를 가진 불변 descriptor.
- `media/<id>/<camera>.mp4`, `staging/<token>/`: 검증된 영상과 미완료 자료. `.writer.lock`은 로컬 writer 배타 잠금이다.

Descriptor JSON은 큰 필드/lineage 정보를 매 index 갱신마다 다시 쓰지 않고 작은 index에서 고정하기 위해 둔다. HDF5 자기 hash를 파일 내부에 넣는 순환도 피한다. Episode당 파일 하나가 추가되는 비용을 아래에서 측정했다. 새 저장 engine이나 metadata DB는 없다.

`open_dataset`, `list_episodes(cursor,limit=1..1000)`, `read_episode`, `record.read_array(name,selection)`은 index commit 순서와 snapshot을 보존한다. 부분 읽기는 영상을 eager load하지 않는다. descriptor/HDF5/media hash·실제 HDF5 dtype/shape·추적되지 않은 배열/외부 link를 검사한다. 바뀐 index의 cursor, 누락/변조 파일은 오류다. `audit_dataset`은 미등록 파일/staging을 보고할 뿐 자동 채택/복구/삭제하지 않는다.

Live `recording.fields`는 필드별 dtype·한 frame shape·unit·phase·availability를 선언하고, `recording.cameras`는 RGB shape/FPS를 선언한다. `EpisodeFrame(tick,time_s,observation_phase,values,video_frame_indices)`의 수치 dtype을 바꾸지 않고 HDF5에 즉시 기록한다. 영상은 반환 전에 소유 copy를 bounded queue에 넣는다. 숫자는 동기 저장, 영상은 비동기 encoding이며 Preview는 관여하지 않는다. tick/time 증가·정확한 camera ordinal·필드/phase를 검사하고 누락 이미지를 복제하지 않는다. 초기 상태는 `metadata.initial_contracts`로 단위/근거를 선언할 수 있다. 선언이 없으면 unspecified로 남기며 measured 값이나 재생 가능 상태로 승격하지 않는다.

commit은 media finalize/PTS·배열 길이/해시 검증 → 파일/descriptor fsync → exclusive publish → index atomic replace·directory fsync다. index만 완료 기준이다. 같은 Episode ID/같은 semantic payload는 같은 참조, 다른 payload는 EPISODE_CONFLICT다. digest는 배열 내용/의미·metadata·media bytes/PTS·outcome을 포함하고 생성 시각이나 HDF5 물리 layout은 포함하지 않는다. Source/평가의 완결된 실패는 완료 기록일 수 있으며 성공 여부를 조작하지 않는다. Annotation/DataGen의 물리 채택 정책은 단계 실행기의 책임이다.

한 writer가 env별 buffer와 commit을 직렬화한다. 디스크/영상/수치 실패는 pending 성공 노출을 막고 이전 index를 유지한다. index 이후 응답 유실은 저장 상태를 조회하고, incoming digest가 확인된 경우에만 applied로 표시한다. `close/abort`는 완료 파일을 삭제하지 않는다. 검증은 로컬 POSIX filesystem/프로세스 장애 기준이며 전원 손실·NFS의 같은 내구성을 약속하지 않는다.

## B02 필드·phase·lineage 보존

Common /2는 17개 첫 Episode의 **612개 배열**을 B02의 논리 목적지로 옮겼다. 기존 Action을 float32 pose로 재계산하지 않았고 6관절 target·7축 TCP delta·collection telemetry를 분리했다. rad/fraction, mm/deg/ms, matrix4/xyz+wxyz와 frame을 보존했다. boolean IK 지표를 이름의 `pose`만 보고 pose 배열로 분류하지 않는다.

Isaac requested 누락과 별도 applied telemetry 부재는 unavailable이다. stored float64 target을 float32 실제 전달값으로 다시 쓰지 않았다. post-step states는 별도 telemetry이고 자동 Annotation grasp boundary는 MuJoCo 223, Isaac 222, DataGen MuJoCo 232로 유지했다. B01 physical post tick 222/221/231과의 차이는 그대로다. 수동 mark와 최종 post-step place의 마지막 action 표시도 이동하지 않았다. event 계약은 recorded_boundary로 표기해 새 pre-step 물리 측정으로 오인하지 않게 했다.

Canonical /1은 B02의 **9개 첫 Episode·104개 NPY 배열**을 추가 확인했다. raw_state/raw_action rad와 state/action의 원래 policy units를 구분하고 원본 replay.json/outcome/partition·manifest/provenance를 보존했다. FK·그리퍼 정규화·post→pre 재정렬을 실행하지 않았다. frame이 입증되지 않은 field는 None으로 남기고 원래 선언을 보관했다. 과거 좌표 schema 이름에 minivla가 들어 있는 로봇 데이터는 유지하지만 MiniVLA 모델/로더/학습 코드를 이관하지 않았다.

미지원/미확인 legacy schema, variable/object 배열, virtual/external HDF5 storage는 명확히 거부한다. schema 미지정 구형 Isaac의 실제 물리 재생·불명 단위/초기 상태를 추정하는 자동 converter는 없다. 이 범위를 전체 과거 format 지원으로 확대하지 않는다.

## Resume·참조 경계

`prepare_resume(previous, requested)`의 requested는 향후 PreparedRun이 전달할 **직렬화된 stage plan mapping**이다. Recipe/PreparedRun 구현을 추가하지 않았다. 비교 항목은 stage, recording 전체, engine, Scene ID/Revision/manifest SHA, Calibration/model/Task/code identity, active object 순서, seed/RNG 규칙·partition이며 DataGen은 annotated input identity·실제 pool 순서·IK identity를 추가한다.

- Source는 cumulative 완료 수부터 기존 `(base_seed+attempt)%2**32` 규칙을 사용한다. discard/미저장 시도나 전체 RNG state의 정확 복원을 주장하지 않는다. 명시 execution 및 기록 metadata의 Source partition 잠금도 확인한다.
- DataGen은 `max(history.attempt)+1`과 전역 max_attempts를 사용한다. success history와 완료 Episode identity/개수를 대조하고 과거 시도를 삭제/덮어쓰지 않는다. 기록된 seed/policy가 부모 계약과 모순되어도 거부한다.
- Pinocchio DLS + Best Effort의 고정 수치/finite·limits/0.5rad jump·측정 seed·joint/model/frame·계산 코드 SHA를 검사한다. SciPy + Best Effort도 다른 정책이다. 같은 값이라도 잘못된 bool/numeric 타입, 누락, Strict/Hold는 거부한다. 이 검증은 IK 계산 구현/실제 성공 증거가 아니다.
- 변환된 과거 자료에 없는 현재 Scene manifest/코드/IK identity를 자동 채우지 않았다. 따라서 형식 변환만으로 continuation이 허용되지 않는다. 기존 Annotation/평가에는 새 continuation을 만들지 않고 독립 replay와 구분한다.

`resume_to_output`은 검사를 끝낸 뒤 새 writer에 완료 Episode 참조와 history를 등록한다. source_ref는 origin DatasetIdentity/Episode ID와 상대 위치이며, 실제 payload 소유자로 평탄화한다. 살아 있는 source writer·변경된 index·누락 hash는 거부한다. 관련 트리를 같이 옮기면 참조가 유지되고, 일부만 옮겨 원본이 없으면 오류다. `materialize_dataset`은 별도 출력에 배열과 MP4 bytes를 복사해 독립 자료를 만들고 원래 content digest를 publish 전에 대조한다. source는 수정하지 않는다.

## 시험·부하 결과

[JUnit](evidence/episode-data/unit-tests.xml), [명령/identity](evidence/episode-data/commands.json), [최종 검증](evidence/episode-data/verification.json), [task별 증거 색인](evidence/episode-data/task-results.json)에 상세 결과가 있다.

- **전체 506 passed, skip 0**: 기존 401개 + 신규 Episode 105개. RED/GREEN 로그를 보존했다.
- Common 17개/612개 배열은 dtype·shape·C-order 값 bytes SHA가 B02와 exact, 영상 34개는 원 MP4 SHA 동일. 전체 PTS/길이 검사를 수행했다. [왕복 결과](evidence/episode-data/roundtrip.json)
- Canonical 9개/104개 배열과 영상 18개, 원 replay JSON·units를 실제 자료로 대조했다. 새로운 Scene 변환/엔진 재생은 아니다.
- disk full·video finalize·수치 append·publish/index 전후 오류·응답 유실·동일/다른 payload와 env별 buffer를 시험했다. 실제 child의 os._exit 및 SIGKILL 이후에도 index 기준 완료 파일을 읽었다. 고아를 성공 자료로 채택하지 않았다.
- 참조 chain 평탄화·트리 이동·독립 Export 후 원본 제거·누락/변조·active writer·partition·history/IK mismatch를 시험했다. 순수 파일 segment 준비 검증이며 Source/DataGen 실행 loop의 실제 재개 시험은 아니다.
- wheel build/compile·독립 import·수치 commit/read/export·기존 10개 Task 등록이 통과했다. 기존 환경에 설치하지 않았다.

[대표 부하](evidence/episode-data/load-results.json)는 B02의 실제 50개 DataGen 자료(21,284 frame, 두 카메라)를 원본 불변으로 사용해, 분리된 child process에서 순차 측정했다. 임시 결과는 검증 뒤 삭제했다. warm-cache 로컬 관측이며 범용 성능 기준은 아니다.

| 작업 | 기존 경로 | 새 경로 |
|---|---:|---:|
| 5 Episode 복사/검증 | 0.295s | 2.367s |
| 50 Episode 복사/검증 | 2.288s | 21.472s |
| 50 Episode peak RSS | 145.0MiB | 218.1MiB |
| 50 Episode 파일 수 | 102 | 202 |
| 50 Episode 총 bytes | 107,867,633 | 87,993,579 |

새 경로는 전체 영상 decode/PTS와 파일·필드 hash·index 검증 비용을 부담하므로 기존 복사 경로보다 약 9.4배 느렸다. 이를 성능 동등으로 표시하지 않는다. 이 자료의 새 경로는 약 991 numeric frames/s이며 전체 비용을 기록했다. 5→50개에서 peak RSS가 frame 수 10배에 비례해 늘지는 않았지만 장시간 안정성/임의 규모를 증명한 것은 아니다.

별도 live RGB 시험은 **404 frame×2 camera, 640×480/30Hz**였다. 기존 encoder만 1.457s/176.1MiB, 새 수치 append+encoder+commit/read는 1.846s/191.1MiB였다. 비교 범위가 달라 전체 workflow의 전후 성능으로 해석하지 않는다. 새 기록의 총 처리량은 약 219 frame/s, queue peak=8이고 누락은 없었다. 시뮬레이터/GPU/다중 worker가 함께 동작할 때의 tail latency·실시간 성능은 미검증이다. 측정 때문에 검증을 생략하거나 저장 구조를 추가 분할하지 않았다.

## 남은 항목과 의도된 변경

기존 거대 HDF5에서 Episode별 payload/descriptor·완료 index로 publish 경계가 바뀐 것이 승인된 저장 방식 변경이다. 검증된 파일 참조는 중복 대용량 복사를 줄이고 공유 Export에서 materialize한다. 과거 IK 기본값 fallback·코드 identity 누락 허용·history 검증 전 복사는 제거했다. 계산/성공 조건·Calibration 적용·기록 시점 자체는 바꾸지 않았다.

DATA-01/02/03/04의 **이번 파일/오프라인 증거**를 확보했다. 실제 엔진 restore/recording과 실행 중 Resume, Curation/L03 공식 LeRobot 소비자·학습/processor, 장치·장시간 다중 worker/전원 장애 검증은 각각 해당 후속 Task에 남긴다. 원본 v8의 새 Scene package identity 매핑도 Builder Export 이후 검증해야 한다.

B01 Isaac DataGen 실패/Evaluation 비결정성, B03 physical_verified=false 및 장치/Calibration OPEN, ASSET-FINGER-01은 그대로다. 원본/환경과 B01~T04 보고서·증거의 [보존 대조](evidence/episode-data/preservation-after.json)를 수행했다. 전수 stat와 선택 SHA이며 전체 대용량 corpus/SDK binary의 전수 byte 증명은 아니다. Git 저장소가 아니므로 초기화/commit은 만들지 않았다. 별도 lint/type 도구는 설정되지 않아 실행했다고 보고하지 않는다. **첫 묶음을 끝내고 중단한다.**
