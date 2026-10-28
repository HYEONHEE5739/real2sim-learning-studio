# B02 — Episode 필드·기록 시점·Resume 호환성 조사

실행일: 2026-10-25. 상태: **B02 조사·대표 계약 검증 완료**. 새 Writer·Reader·Resume 구현, 데이터 변환, 파일 병합, 시뮬레이터·실물 실행은 하지 않았다. B03 이후 작업도 시작하지 않았다. [새 데이터 계약](data-contracts.md), [Interface](interfaces.md), [Episode SPEC](../SPEC-episode-data.md)의 보존 조건을 구체화한다. 새 형식으로 실제 변환·왕복 재생이 검증되었다는 보고서가 아니다.

## 1. 범위와 근거

P는 `/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab`, O는 `/home/hyeonhee/soarm_isaaclab/soarm101_lab/outputs`다. 실제 읽은 파일의 경로·SHA·배열별 dtype/shape는 아래 증거에 있다. 실행 Python은 기존 `lerobot-arena`의 Python 3.11.15이며 Sim5.1/Lab2.3/LeRobot0.4.1/MuJoCo3.3.7 환경을 변경하지 않았다. 검증은 기존 코드와 같은 bytes인 B01 참조 복사본을 import하거나, 원래 함수 body를 그대로 추출해 메모리 sink로 호출했다.

| 증거 | 조사/검증 범위 |
|---|---|
| [inventory.json](evidence/b02/inventory.json) | O의 HDF5 후보 1,390개 header와 Canonical manifest 검색. Common 289개, schema 미지정 synthetic HDF5 1개, 비 HDF5 placeholder 1,100개 |
| [samples.json](evidence/b02/samples.json) / [입력 SHA](evidence/b02/sample-inputs.json) | 대표 HDF5 **17개에서 각 첫 Episode**와 해당 두 카메라 MP4·metadata·attempt history. HDF5/MP4 51개 hash |
| [field-compatibility.json](evidence/b02/field-compatibility.json) | **612개 배열 필드**의 논리적 목적지·dtype·shape·SHA, 기존 Reader/Validator·좌표/단위/관절/sidecar 일치 검사, B01 tick/frame 대조 |
| [resume-probes.json](evidence/b02/resume-probes.json) | 원래 guard body·읽기 전용 입력·메모리 commit sink로 확인한 **25개** Resume/partition/lineage 관찰. 18개 거부 사례 포함 |
| [legacy-rng.json](evidence/b02/legacy-rng.json) | 모델 전용 폴더를 제외한 Canonical **9개 폴더의 첫 Episode** NPY/JSON, 기존 scheduler/seed 규칙, 저장되어 있던 Resume fixture의 기존 Episode 2개 배열 비교 |
| [최종 검증](evidence/b02/verification.json) / [보존 대조](evidence/b02/preservation-after.json) | 근거 무결성·원본/B01 보존·작업 범위 |

1,100개 비 HDF5 파일은 모두 `workflow_validation/functional_refactor/path_execution/` 아래 9 byte `candidate` placeholder다. 실제 Episode 손상 1,100건으로 분류하지 않는다. Canonical manifest는 11개를 발견했으나 MiniVLA model/policy 전용 2개는 상세 조사·이관 대상으로 사용하지 않았다. 일반 Source의 옛 schema 이름에 `minivla`가 들어 있다는 사실만으로 로봇 기록의 좌표·단위를 버리지는 않는다. MiniVLA 모델/로더 이관은 계속 제외한다.

대표 입력에는 B01 Source/Annotation 양 엔진, MuJoCo DataGen, Evaluation 양 엔진과 O의 실제 Source·Annotation·DataGen·ACT 평가 success/failure·subset·과거 partition·수동 Annotation을 포함했다. `functional_refactor/source_writer`의 before/resume_after는 **과거 synthetic 검증 산출물**이며 이번에 다시 수집하거나 Resume한 데이터가 아니다. Corpus 전체의 모든 Episode를 payload 검증한 것은 아니다. 구형 schema 미지정 HDF5도 synthetic reader fixture이므로 실제 구형 Isaac 기록의 전수 호환 증거가 아니다.

## 2. 저장·읽기·완료 책임

| 경로 / 함수(P 기준) | 확인된 기존 동작 | 새 계약에 가져갈 의미 |
|---|---|---|
| `data/episodes.py:379 DatasetWriter`, `:431 commit`, `:477 close` | 임시 거대 HDF5에 수치/영상 검증 → private group/영상 → `data/demo_N` 이동, `committed=True`. close 때 sidecar 기록·최종 HDF5 exclusive hard link. 완료 수 0이면 HDF5를 publish하지 않음 | 완료 Episode와 pending을 구분하고 원본은 불변. 새 index commit과 기존 파일 내부 group commit은 다른 publish 경계 |
| `data/recording.py:13 SourceEpisode`, `:61 source_episode_values` | Source의 pre-step 수치/영상 복사, 관측·요청·적용 target 의미를 구분해 포맷팅 | 수집 phase/명령 단위/영상 대응. 기존 저장 형식을 복사하는 요구는 아님 |
| `data/recording.py:79 EpisodeBuffer`, `:105 append`, `:114 finish` | Annotation/DataGen/Evaluation의 pre-step 수치·영상, event·IK·initial state, 최종 post-step 이벤트를 마지막 action에 표시하는 계약 | 기록 phase와 최종 채택/완료를 분리. 물리 성공을 commit 자체와 혼동하지 않음 |
| `data/datasets.py:177 EpisodeDataset` | Common은 배열을 그대로 읽음. 구형 Isaac/Canonical 분기는 FK·frame·시점 변환을 수행할 수 있음 | 원래 값과 reader가 도출하는 값을 구분. 이번에는 legacy normalization/conversion 호출 안 함 |
| `data/episodes.py:144 EpisodeReader` | Curation용 bounded read, metadata로 pose/unit/영상 선택. 일부 누락 timestamp fallback 존재 | 검토용 reader의 fallback을 정밀 재생·Resume 증거로 확대하지 않음 |
| `data/episodes.py:54 LegacyEpisodeWriter` | manifest/provenance + Episode별 NPY/MP4/replay/outcome | 초기 상태·실제 dtype·옛 성공 의미·lineage 보존. 이번에 writer를 호출하지 않음 |

새 Episode별 HDF5·완료 index는 **설계만** 있다. 기존 `committed=True`·HDF5 flush 또는 읽기 성공을 새 transaction의 crash safety로 간주하지 않는다. 새 Writer의 disk full/video 실패·강제 종료·응답 유실·publish/index 사이 장애·부하 시험은 D02/D04의 미완료 항목이다.

## 3. 필드별 호환 표

목적지는 새 계약의 **논리적 의미**이며 구현 HDF5 경로나 Schema 파일을 생성한 것이 아니다. 전체 612개 개별 leaf 대응은 field-compatibility.json에 있다. 아래의 “그대로”는 현재 저장된 값·dtype·shape를 보존한다는 뜻이며, 파일에 없는 정보까지 복원했다는 뜻이 아니다.

| 기존 필드 | 실제 dtype/shape·의미 | 새 계약의 책임 / 검증·제한 |
|---|---|---|
| `obs/policy/joint_pos` | MuJoCo float64, Isaac 대표 기록 float32, `[T,6]`, measured model rad | pre-step 관측·joint_order와 함께 그대로. command나 LeRobot 정규화 state로 재해석하지 않음 |
| `obs/policy/joint_vel` | Native Isaac Source에서 float32 `[T,6]`, rad/s. 다른 대표 경로에는 없음 | 측정 관측이 있으면 보존. 없는 속도를 0·유한 차분으로 만들어 measured로 저장하지 않음 |
| `joint_targets` | `[T,6]` model rad. Source Isaac=float32, MuJoCo=float64. **Isaac Annotation/Evaluation은 저장 target float64** | `commands.recorded_joint_target` 의미를 우선 보존. 엔진 전달 dtype/적용 phase는 별도 명시; 모든 저장 target이 실제 엔진 payload와 bitwise 같다고 가정하지 않음 |
| `collection/requested_action` | MuJoCo Source 대표 기록 float64 `[T,6]`, Leader mapping 후 clipping 전 model rad | 요청 명령으로 보존. Native Isaac Source의 저장 결과에는 이 필드가 없음. 다른 단계에도 없으면 `unavailable` |
| `collection/state`, `collection/action` | Source의 RobotCoordinates 변환값. 대표 metadata의 policy_units는 팔 rad·그리퍼 fraction | measured model rad/실제 적용 rad와 별개 telemetry. 그리퍼 fraction과 rad를 합치지 않음 |
| `collection/recorded_mimic_actions` | Native Isaac Source에서 float32 `[T,7]`; `native/isaac.py:299 step`이 만든 step 전후 EEF delta | 일반 `actions`와 별도 raw telemetry. 같은 이름의 Action이라고 덮어쓰거나 중복이라고 삭제하지 않음 |
| `actions` | 대표 Common은 float64 `[T,7]`; base-frame TCP translation delta m, rotvec rad, **그리퍼 절대 model rad** | measured 관절값/6축 target과 별개. 첫 delta 기준은 초기 measured EEF, 이후는 직전 **target** EEF. 누적 measured displacement로 다시 계산하지 않음 |
| `obs/datagen_info/eef_pose/tool0` | float32 `[T,4,4]`, robot_base 기준 measured EEF | 기존 Mimic 입력값 그대로. 원래 float64로 계산했을 가능성과 저장된 정밀도를 구분 |
| `obs/datagen_info/target_eef_pose/tool0` | float32 `[T,4,4]`, controller target; Source·평가의 joint-only 경로는 FK 도출 | 생성 target/FK 도출의 출처를 유지. measured EEF로 대체하지 않음 |
| `obs/policy/ee_state` | xyz+wxyz `[T,7]`, robot_base 기준. 대표 기록에서 float64 변환 표현 | matrix4와 의미가 같아도 quaternion·rounding·도출 관계를 확인한 뒤 정리. 변환 없이 실제 정밀도 보존 |
| `obs/datagen_info/object_pose/<id>` | float32 `[T,4,4]`, robot_base 기준 | Task/Mimic 입력 그대로. 공통 Object ID·frame 연결을 명시 |
| `obs/object_poses/<id>` | xyz+wxyz `[T,7]`, world 기준, 주로 float64 | 위 robot_base pose와 다른 frame. 초기 world pose와 비교하는 기존 검사 통과. 이름만 보고 동일 배열로 중복 제거하지 않음 |
| `obs/timestamp`, `action_timestamp` | float64 `[T,1]`, `[T]`, s; Source는 관측 sim clock, EpisodeBuffer는 `arange(T)/hz` | timestamp 원점/clock·control_dt·phase 보존. frame ordinal을 derive할 수 있어도 physics substep counter/실물 시계로 간주하지 않음 |
| `obs/camera_timestamps/{side,wrist}` | float64 `[T]`, 원래 관측 시간과 일치 | 카메라별 frame ordinal/상대 MP4 PTS와 연결. 실물 동시 촬영의 증거는 아님 |
| `external_videos` attr | camera별 상대 file·frames/fps·shape·SHA; MP4 H.264 640×480, RGB read는 uint8 | 파일 bytes·카메라 순서·PTS를 보존. `video_frame_indices`는 검증된 ordinal로 도출 가능, 당시 미압축 RGB를 복원했다고 주장하지 않음 |
| `initial_state/articulation/robot/*` | root xyz+wxyz/world, root_velocity `[linear,angular]` world, joint q/qd `[1,6]` | 단위 m/rad/s와 실제 기록 dtype 유지. base/root와 robot_base-relative 관측을 혼합하지 않음 |
| `initial_state/rigid_object/<id>/*` | root pose/velocity `[1,7]`/`[1,6]`, world | 선택 물체뿐 아니라 기록 Scene의 필요한 대상도 보존. 새 Recipe로 임의 재배치한 상태를 재생 initial로 사용하지 않음 |
| `legacy_initial_state` attr / `replay.json` | MuJoCo backend/model SHA/version/state_spec/integration_state | opaque 엔진 상태로 보존. 동일 모델·backend·version에서만 해석; 단순 q/qvel보다 많은 내부 상태를 버리지 않음. Annotation이 상속한 **원본 Source snapshot**일 수 있음 |
| `states/joint_pos`, `states/joint_vel` | Native Isaac Source의 float32 `[T,6]` **post-step** 관측 | pre-step obs와 별도 phase의 telemetry. 같은 t행에 있다고 pre-step 관측으로 합치지 않음 |
| `obs/events/*`, `subtask_term_signals/*`, `annotation` | uint8 `[T,1]`, boundary frame·method·timing | event 원천/phase·수동 mark·최종 post-step 매핑 구분. 실제 존재하는 동등 alias만 검증 후 정리 |
| `ik/*` | DataGen의 bool/int/float·candidate `[T,5]`, failure_reason `S64`; mm/deg/ms 지표 포함 | 각 단위를 보존·명시. mm/deg 필드를 m/rad로 이름만 바꾸지 않음. 실패 attempt의 전체 이유/진단 JSON도 보존; S64 잘린 내용을 추측 복원하지 않음 |
| `mimic_plan/<subtask>/*` | pre-IK target·gripper·noise, subtask별 길이는 전체 T와 다를 수 있음 | 계획·selection/boundary·seed와 함께 별도 생성 근거. 일괄 T 길이 검사나 실제 EEF 궤적으로 대체 금지 |

17개 첫 Episode는 기존 `validate_episode`와 추가 header/sidecar 검사를 통과했다. 모든 leaf dtype·shape·bytes SHA를 확인하고 논리적 목적지를 부여했다. 이는 **새 저장 형식 round-trip PASS가 아니다**. 저장 float32 target pose로 Action을 재계산하면 대표 기록에서 작은 차이가 관찰되므로 원래 Action을 삭제하고 재계산값으로 대체하지 않는다. 관측한 최대 차이에는 m/rad/그리퍼가 섞여 있어 하나의 단위·새 tolerance로 채택하지 않았다.

### 명령 정밀도와 누락의 구체적 경계

- `native/source.py:197` 부근은 requested를 모델 bounds로 clipping하고 Isaac target은 float32로 만든 뒤 기록/적용한다. MuJoCo Source의 requested/action telemetry는 남지만 `data/source.py:69` 이후 Isaac 분기는 collection을 `recorded_mimic_actions`로 교체하므로 **Isaac requested telemetry는 저장되지 않는다**.
- `native/annotation.py:132` 이후는 읽은 command를 pre-step buffer에 저장한다. Isaac batch는 이후 float32 엔진 action에 넣는다. DataGen의 `workflow/datagen.py:293` 이후도 buffer에는 원래 command를 기록하고, 별도로 engine dtype에 넣는다. 따라서 stored float64 target과 engine payload float32를 혼동하지 않는다.
- 새 계약은 `recorded / derived(근거 포함) / unavailable / not_applicable`를 구분한다. 과거에 없는 requested를 recorded target으로 복제하거나, 엔진 cast로 도출한 값을 실제 저장된 applied telemetry라고 표기하지 않는다. 새 수집에서는 필요한 요청·전달·적용 정보를 명시적으로 기록하되 과거 누락을 소급해 채우지 않는다.
- `data/recording.py:61`의 Common Source 초기 속도는 0으로 포맷팅한다. Native Isaac 초기 상태는 실제 root/joint velocity 복사이고, replay buffer는 `measured_initial`을 쓴다. 기본 0과 측정 0은 다른 근거다. 옛 Canonical reader에는 `unrecorded legacy velocity; replay validation required` 표기도 존재한다. 누락 속도·solver 내부 상태를 모두 측정 완료로 승격하지 않는다.
- Isaac Annotation 산출물에도 MuJoCo Source에서 상속된 `legacy_initial_state` attr가 있다. 이를 Isaac의 현재 snapshot으로 붙이면 안 된다. `native/mujoco.py:restore_recording`의 backend/model 조건과 원본/실행 backend 구분을 유지한다.

## 4. Annotation·DataGen·Evaluation의 phase와 outcome

| 경로 | 저장/판정 시점과 보존 조건 |
|---|---|
| Source | 관측/영상·command를 물리 step 전에 기록. 새 Native의 success_source는 `recording_only`; 과거 Source의 `simulation_place_condition` 성공 attr는 과거 의미로 보존 |
| Annotation auto | pre-step obs/영상·이전 latch 기록 → command/physics → post-step contact/relative pose로 tracker update. B01 MuJoCo **post tick 222 → 저장 frame 223**, Isaac **221 → 222** |
| Annotation manual | 물리 통과를 요구한 뒤 사용자가 지정한 grasp frame으로 signals/annotation을 덮어쓰는 현재 동작. 조사한 manual artifact의 frame은 **203**, method=`manual_grasp_and_measured_place`. 이것을 physical first-grasp tick+1로 재해석하지 않음 |
| Production DataGen | pre-step event 기록과 post-step tracker. B01 MuJoCo physical grasp post tick=231, 저장 frame=232. 성공은 latched StableGrasp AND Placement |
| EpisodeBuffer.finish | 최종 post-step placement를 확인한 경우 마지막 action frame에 place 이벤트를 표시할 수 있음. 마지막 frame의 표시는 그 pre-step 순간의 접촉/성공을 추가 측정했다는 뜻이 아님 |
| 기본 Evaluation | pre-step policy observation/command 기록, post-step 지표/Placement 검사. 성공 종료는 Placement, grasp/transport/full_task_success는 별도 지표. 완결된 실패 Episode도 `committed=True`일 수 있음 |

같은 boolean 배열을 물리 latch·Mimic boundary·수동 mark로 동시에 설명하지 않는다. B01의 trace는 자동 물리 판정과 저장 frame 차이를 실제로 확인한 증거다. 모든 과거 Episode에 raw contact·tracker sample window·post-step 최초 tick이 저장된 것은 아니므로 일반적으로 signals를 한 칸 옮겨 “원래 물리 판정”을 복구하지 않는다. 중간 tick tracker/물리 Resume는 약속하지 않는다.

Annotation은 `native/annotation.py:224 save`가 결과를 입력 ordinal 순서로 commit하면서 채택된 Episode를 `demo_N`으로 재번호화한다. 실패/skip은 report/progress에 남고 성공 Dataset에는 들어가지 않는다. 따라서 원본 Dataset+Episode identity·source_lineage와 새 output Episode ID를 나눠야 한다. Evaluation의 success/failure 폴더 분류도 완료/미완료와 별개다.

## 5. Metadata·Seed/RNG·순서 대응

| 기존 정보 | 새 계약 / 조사 결과 |
|---|---|
| root/data의 env_args·coordinate sidecar | Dataset 수준 semantic contract. schema/version·joint_order·mapping·calibrated model·scene_configuration·units를 단일 근거로 묶고 중복은 값 일치 확인 후 정리 |
| legacy Workspace identity | workspace_id/version/source_revision/profile SHA/robot Asset/mapper 등이 기록됨. **새 Scene package의 Revision/manifest SHA는 아직 없음**. 나중의 실제 변환 대응표·검증 결과 없이 최신 Scene hash를 넣지 않음 |
| episode_id/source_group/source_lineage·mimic_source_segments | 원본 Source identity와 선택 subtask lineage 보존. 숫자 demo_N만을 전역 Episode ID로 사용하지 않음 |
| source_partition | 과거 서명된 train/val 증거·membership·hash·lineage 보존. 원본 Source 이어 수집 잠금 유지. 현재 Curation role과 별개 |
| curation attr·curation_origin/source_episode | 현재 subset/export 역할/원본 Episode 선택 근거. 조사한 subset 17개는 signed source_partition이 없음. 폴더 이름만으로 train/val 잠금을 새로 부여하지 않음 |
| Source seed | 새 Native는 legacy_provenance.source_native.seed와 physical/run config 기록. Episode seed=`(base_seed+attempt)%2**32`; Resume의 attempt 시작은 writer.count. **discard·미저장 시도 수/전체 RNG state가 저장되는 계약은 아님** |
| DataGen seed/history | generation_seed + attempt 번호 → `SeedSequence([seed,attempt])`. B01 1047/attempt1 → 892243098. `generation/attempts_json` 또는 검증 가능한 attempts.json, 성공/실패/중단·선택 source·초기 구성·budget를 보존 |
| DataGen 재개 카운터 | 원래 scheduler는 `max(history.attempt)`부터 이어가고 max_attempts는 누적 전역 한도. 메모리 history `[success1,ik_failure2,interrupted3]`에서 다음 claim은 **4,5,None**. 성공 Episode 수만으로 다음 seed를 정하면 틀림 |
| DataGen RNG | RandomStream의 NumPy RandomState/Torch state는 실행 메모리에 있으며 저장된 Episode/attempt가 그 state 전체를 직렬화하지 않음. attempt seed·계획/초기 구성으로 확인 가능한 범위만 사용. worker별 Reset RNG 소비·병렬 schedule까지 seed 하나로 재현 보장하지 않음 |
| Evaluation seed/Policy | run/evaluation/seed와 개별 Episode 초기 구성·Policy 참조 보존. Policy chunk/processor/RNG·렌더 전체 상태 checkpoint와 같은 의미는 아님. B01 Isaac 반복 차이는 미확정 상태 유지 |
| Episode/source pool 순서 | 일반 reader.names는 숫자 순, mimic_names는 HDF5 key 순서. 20개 자료는 `demo_0,demo_1,demo_10,…` pool과 숫자 순서가 다름. source_index 해석을 위해 **실제 pool 순서** 보존; 새 index commit 순서와 분리 |

일반 Canonical 기록의 raw_state/raw_action은 float64 model rad, state/action은 float32이며 unit metadata는 팔 rad/그리퍼 fraction이다. object_pose는 workspace matrix4이고 필요 시 object_poses.npy는 workspace xyz+wxyz float32다. FK 도출·static target 반복·초기 속도 0·구형 post→pre `initial[0]+post[:-1]` 정렬은 기존 reader가 수행하는 변환으로 표시하고 이번에는 호출하지 않았다. 실제 구형 Isaac raw Episode 전체가 대표 corpus에 있다는 근거는 없어 해당 분기의 물리 재생 호환은 추가 확인 대상이다.

## 6. 기존 Resume 호출과 검증 결과

| 경로 / 원래 함수 | 확인한 의미 | 새 계약에서의 판단 |
|---|---|---|
| Native Source `native/source.py:87 prepare`, `:121 run`, `data/source.py:23 resume` | workspace/calibration/model·Scene/Reset·native physical config·partition·기존 seed를 검사하고 새 writer로 기존 완료 Episode 복사. episode 목표는 누적 총수이며 기존 수보다 커야 함 | 과거를 읽기 전용 입력으로 삼는 의미 유지. seed가 같아도 discard를 포함한 정확 RNG continuation이라고 주장하지 않음 |
| Native Annotation `config/run` | config에 Resume 필드가 없고 recorded initial에서 선택 Episode를 독립 replay. 완료/skip/실패 진행을 기록 | “Annotation Resume 이미 구현됨”이라고 표시하지 않음. 과거 결과를 입력으로 재실행하는 것과 중단 작업 재개를 구분 |
| 현재 DataGen worker `workflow/operations.py`의 공통 Episode 경로 → `unified.execute` → `datagen._resume` | backend/workspace/tasks/source fingerprint 사전 검사 + source pool/coordinate/followup/seed/IK 비교 + 기존 완료 성공 Episode 복사 + attempt history 검증 | 새 prepare_resume가 필요한 검사를 **복사·commit 전**에 모두 수행해야 함. 미전환 구조를 그대로 이관하지 않음 |
| 구형 DataGen `workflow/data_resume.py:25 validate`, `:45 combine` | workspace/task·active set·동일 annotated 경로 등 검사. NEW segment만 병합 교체; Common 분기는 실제 migration을 호출할 수 있음 | 조사만 하고 combine/migrate/compress는 이번에 호출하지 않음. 현재 worker `_resume`와 구형 combine을 중복 실행하지 않음 |
| Evaluation `evaluate_sim` | Episode 기록·성공/실패·중단 결과는 있으나 현재 조사한 경로에 DataGen식 resume_data/history continuation 없음 | generic Resume API가 있다고 과거 평가가 이어 실행 가능하다고 간주하지 않음. 독립 새 평가와 기록 재생으로 구분 |

25개 probe는 원래 함수 body와 실제 읽기 전용 입력을 사용하고 `writer.commit`은 메모리 sink로 가로챘다. 상위 검사 metadata 변형은 통제된 fault fixture이며 실제 데이터를 고치지 않았다. Source catalog의 실제 content lineage와 partition hash 검사는 별도 원래 함수로 수행했다. **실제 Writer/병합·데이터 변환·엔진 Resume 시험이 아니다.**

확인 결과:

- 같은 B01 SciPy + Strict DataGen과 같은 Native Source는 메모리 sink에 복사 요청이 발생했다. backend/source pool/coordinate/seed/solver/policy/solver parameter·Source physical/Reset/model/Calibration·partition mismatch 등은 거부했다.
- 이전 generation_configuration의 IK 정보가 빠져도 현재 `_resume`는 기본 SciPy + Strict로 해석해 수용할 수 있었다. 별도 code identity 차이는 검사하지 않았다. 이것을 새 계약의 허용 규칙으로 이관하지 않는다.
- attempt success 개수와 완료 Episode 수가 다른 controlled 입력은 거부했지만, **그 전에 새 writer에 해당 Episode를 복사하는 호출 2회가 있었다**. 원본은 불변이고 기존 초기화 예외 경로는 새 writer를 폐기하지만, 새 읽기 전용 prepare_resume에서는 이 검사를 효과 발생 전에 끝내야 한다.
- 구형 상위 validator는 annotated 입력 **경로 이동**을 다른 입력으로 거부한다. 새 계약은 내용/identity가 검증된 동일 자료의 경로 이동과 실제 내용 변경을 나누되, 옛 path-sensitive fingerprint를 새 identity와 같다고 이름만 바꾸지 않는다. `utils/artifact_identity.py`는 HDF5 이름과 참조 MP4도 hash에 포함한다.
- 기존 synthetic Source Resume 산출물의 과거 demo_0/demo_1은 원래 dtype와 모든 배열값이 같았다. 이 관찰이 새 Writer·현재 실물 수집·모든 Resume의 검증을 대신하지 않는다.

## 7. IK identity와 새 Resume의 필수 경계

| 자료 | 실제 확인값 / 역할 | 새 DLS + Best Effort continuation |
|---|---|---|
| B01 MuJoCo DataGen | `scipy_ls` + `strict`, 이전 command seed, 기존 SciPy 파라미터/Strict 정책 | **거부**. 변경 전 Baseline으로 보존 |
| 실제 과거 빨간 블록 DataGen 50개 | `scipy_ls` + `best_effort`, generation_seed=1432209183, jump reject | **거부**. Best Effort 이름이 같아도 solver/seed/계산이 다름 |
| 과거 DLS + Hold/Strict 또는 미확인 identity | 이름/일부 필드만 있거나 고정 계약과 다름 | **거부**. 누락을 현재/기본 정책으로 채우지 않음 |
| 신규 Pinocchio DLS + Best Effort | 고정 파라미터·측정 seed·joint order·모델/frame·finite/limit/>0.5 rad jump·code identity를 실제 실행 때 기록해야 함 | 이 값과 다른 모든 Resume 계약이 일치할 때만 허용 가능. **아직 구현/실행 검증 안 됨** |

읽기/학습/자료 변환과 “이어 생성”은 다르다. 적합한 annotated 원본으로 새 DataGen run을 시작하는 것은 가능하며, 다른 solver로 생성한 과거 성공/실패/attempt 통계를 같은 정책의 누적 실적으로 섞지 않는다. 과거 필드를 새 정책으로 다시 쓰거나 SciPy/Strict/Hold 호환 실행기를 추가하지 않는다. UI/Recipe에는 solver/policy 선택을 만들지 않는다.

새 prepare_resume의 필수 비교:

1. 완료 index·Episode/media·입력 자료 identity 및 누락/변조. Scene/Calibration 정확한 Revision·manifest hash와 원본→신규 mapping 근거. 아직 없는 hash를 생성된 사실처럼 채우지 않음.
2. engine/기록 phase·frame/unit·joint/action 의미·active objects·Task 계산/파라미터·partition. 동적/정적 초기 상태와 opaque snapshot의 소유 backend/model/version.
3. DataGen의 명시 IK identity·고정 수치·seed/jump 기준·code identity, annotated input 내용/순서·source pool 순서, attempt history/성공 commit 개수·전역 max attempt·지원 seed continuation.
4. 필수 정보가 없으면 해당 continuation을 `RESUME_INCOMPATIBLE` 등 명확한 오류로 막는다. 유효한 과거 데이터의 열람·공식 학습에 Resume 전용 요건을 불필요하게 강요하지 않음.
5. 모든 검사는 새 출력 기록/기존 Episode 참조 등록 전에 끝낸다. 원본 불변·새 run/output·Episode 경계 재개를 유지한다. 실제 구현과 장애 검증은 D01/D02/D03/E06의 작업이다.

**B01 Isaac DataGen 실패는 그대로다.** 성공 Episode 0개여서 원래 writer가 최종 HDF5를 publish하지 않았고 attempt/report는 남았다. 이를 완료 Dataset이나 Resume 가능 상태로 만들어 채우지 않았다. 새 계약에서 0개 완료·실패 attempt만 있는 run의 재개 가능 여부도 필수 index/identity/history가 실제 존재하는지로 검사해야 한다. 이번에는 새 형식을 만들지 않았다.

## 8. 확인 상태·남은 검증·완료 경계

| 항목 | B02 결과 / 후속 범위 |
|---|---|
| DATA-01 | 대표 필드/단위/dtype/phase/명령 정밀도/initial 근거 확보. 실제 old→new 변환·왕복 재생과 누락 처리 검증은 D01/엔진 연결에 남음 |
| V8-04 | 현재 Source/DataGen과 구형 경로·없는 Annotation/Evaluation continuation 구분, seed/history/partition/IK 거부 경계 근거 확보. 실제 Resume 실행은 미수행 |
| DATA-03 | Reader·lineage·partition·pool 순서와 Resume 소비 계약의 대표 근거 확보. 새 참조 index 이동/export·Curation/LeRobot 통합은 미검증 |
| DATA-02/04 | 새 Writer 구현·장애/부하 시험 미착수. B02 읽기 성공으로 해제하지 않음 |
| B03/CAL/ROBOT | 조사한 기록의 보정 identity는 보존하지만 Calibration 계산·장치 계약 전수 확인과 실물 시험은 미착수 |
| DATAGEN-IK-01 | 고정 정책 결정 유지. DLS + Best Effort 구현·동일 입력 fixture/양 엔진 실행은 E06에서 검증 |
| 기존 미확정 사항 | Isaac DataGen strict IK 실패·Isaac Evaluation 수치/영상 비결정성은 B01 상태 그대로. 수치 tolerance나 판정 조건을 변경하지 않음 |

새 형식이 요구하는 정보 중 과거에 없는 requested/applied telemetry·속도 측정 근거·runtime 코드 hash·RNG state·새 Scene manifest는 “변환하면 자동 확보됨”으로 처리하지 않는다. 각 자료의 실제 필수 기능을 기준으로 확인 가능한 값을 도출하거나 누락 상태/사용 제한을 기록한다. 필요한 초기 상태·identity를 입증하지 못하는 재생/Resume는 차단한다.

추가·변경 산출물은 B02 조사 harness/JSON/log 및 관련 문서뿐이다. 기존 폴더 56,100개 파일 stat와 선택한 기존 코드/설치 Metadata·B01 전체 증거/보고서 등 15,120개 SHA를 대조했고 변경은 없었다. 조사 중 확보한 sample/영상/Canonical 자료 192개 hash도 이후 대조에서 일치했다. 후자는 조사 중 읽기 시점의 identity이며 corpus 전체 payload의 작업 전후 byte 증명은 아니다. P/O·설치 환경을 수정하거나 B01 증거를 갱신하지 않았다.

실제 명령·인터프리터·검증 코드 identity는 [commands.json](evidence/b02/commands.json)에 있다. 새 프로젝트는 Git 저장소가 아니므로 commit을 만들지 않았고 기존 저장소에도 조사 자료를 쓰지 않았다. 링크된 incremental-implementation의 범위·검증 원칙을 적용했으며 별도의 mental-implementation 스킬 파일은 가용 경로에서 확인되지 않았다.

## 내가 직접 확인할 것

1. Source Isaac의 누락 요청값, Isaac stored target과 float32 전달값, 초기 속도 근거를 새 Schema가 거짓 측정값으로 채우지 않는지 확인한다.
2. 자동 Annotation의 post tick/저장 frame 차이와 수동 boundary·최종 post-step place 표시를 각각 유지한다.
3. 후속 D01/D03/E06에서 이 대응표와 실제 입력 SHA를 사용해 구현·변환·Resume를 검증한다. 이번 B02 완료만으로 해당 작업을 자동 시작하지 않는다.
