# L03 — Native Dataset·Action 매핑·공식 소비자 검증

2026-10-27. **L03의 Dataset 변환·지원 범위 Merge·Curation/공식 소비자 검증을 완료했다.** 기존 Native C materialization을 보강했으며 새 Dataset 포맷이나 중간 대용량 변환 계층은 없다. ACT/SmolVLA의 실제 Dataset factory·DataLoader·공식 processor를 실행했다. Policy/model 가중치·forward/backward·optimizer·Training은 실행하지 않았고, L01/L02/L04 및 P/C/U/X 작업을 시작하지 않았다.

**학습 파일 호환성과 제어 배포 호환성은 다르다.** SmolVLA 0.4.1의 loss padding 키, MuJoCo float32 Policy 출력의 엄격한 관절 제한, 현재 Follower 보정/command binding에는 아래 미해결 관문이 있다. 이 결과를 Training 성공이나 실물 제어 승인으로 해석하지 않는다.

## 구현·계약 결정

변경 제품은 [data/lerobot.py](../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py) 한 파일, 새 시험은 [test_lerobot_dataset.py](../robot_learning_workbench/tests/test_lerobot_dataset.py)다. 기존 `data/native.py`, `curation.py`, 엔진·장치·Task·Builder·Recipe 계산은 변경하지 않았다. 원본의 값/정밀도/phase/identity는 보존용 Native에 그대로 남는다.

- 기존 `materialize`와 pinned LeRobot0.4.1 `_save_episode_data`·Metadata/save_episode·공식 statistics·finalize/publish를 재사용했다. 설치 SDK monkeypatch, Dataset subclass, Trainer hook은 없다.
- `control_contract(source)`는 관절 순서·model/Scene/Calibration·좌표·30Hz·카메라·학습 IO 의미를 명시한다. 알려진 Workbench 계약이 잘못되면 generic 외부 Dataset으로 낮춰 받아들이지 않는다. 외부 Dataset 열람에 Workbench Metadata를 강제하지 않으며, 의미를 입증하지 못한 입력은 자동 Merge하지 않는다.
- `merge(sources,output,split=None,independent=False,task=None)`는 같은 materialization 경로를 사용한다. 공식 aggregate의 shape/dtype 일치 요구와 영상 copy/concat 대신, 이미 검증된 공식 writer 경계를 직접 사용해 선택 rows를 재색인하고 MP4를 공유한다. 별도 Merge Writer·Manager·Adapter는 없다.
- 공식 `features.names`에 여섯 관절을 저장한다. 학습 지시문은 명시 `task` 또는 기록된 언어 task를 사용하고 code SHA/dict를 SmolVLA 언어 지시로 사용하지 않는다. 기본 새 Workbench projection에서 `feature_map`으로 IK 진단/측정 post-state를 Action 정답으로 바꾸면 생성 전에 거부한다.
- source Dataset/Episode UID·원 frame/time·domain/Resume parent·split과 원본 위치/identity를 작은 공식 Metadata/`workbench.json`에 남긴다. original/curated/materialized identity를 같다고 재명명하지 않는다. source UID는 Episode 식별이며 전체 payload 중복 content hash가 아니다.

## 학습 Observation·Action의 의미

권위 순서: **shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper**.

| 값 | 출처·공간·단위 | L03 학습에서의 처리 |
|---|---|---|
| `observation.state` | `obs/policy/joint_pos[t]`, pre-step measured model rad 6개 | 정확한 원래 행을 사용. MuJoCo 원본 float64, Isaac float32 |
| `action` | `joint_targets[t]`, 해당 step의 절대 model joint position target | 두 엔진 모두 기록된 float64 solver command를 사용. delta·도달 측정값이 아님 |
| 실제 적용 command | `ik/applied_joint_rad[t]`, Isaac float32 / MuJoCo float64 | 학습 feature에서 제외. target 정답을 대체하지 않고 차이·안전 경계를 비교하는 근거 |
| post-step q·grasp/contact | `states/*`, 실제 step 뒤 측정/판정 | 학습 feature에서 제외. 같은 t행의 pre observation으로 합치지 않음 |
| Mimic `actions` | 7축 TCP delta m/rotvec rad + 절대 gripper model rad | 6축 관절 Policy Action으로 사용하지 않음 |
| Side/Wrist | 같은 pre-step frame의 RGB640×480·30FPS | 재인코딩 없이 원 MP4와 공식 offset 연결 |
| IK·initial·attempt·success/lineage | Native Tensor/최소 실행 Metadata | 보존용 Native와 source 참조에 유지. 임의 학습 feature로 넣지 않음 |

기존 v8 `scripts/tools/convert_isaac2lerobot.py:load_actions`는 `joint_targets`를 사용하며, 기존 Policy observation/inference는 model rad 6축을 공식 processor 전후에 전달한다. 레거시 converter의 next_joint_pos fallback·Mimic Cartesian action 선택을 새 기본 학습 경로로 추가하지 않았다.

**정밀도 경계:** Parquet는 원래 float32/64를 보존한다. 혼합 Merge의 state 저장은 float64로 승격하여 float32 값을 정확하게 담는다. 설치된 공식 `__getitem__`/HF torch format과 normalizer는 float32 학습 Tensor를 만든다. 이것을 원본 float64 저장값과 bitwise 같다고 주장하지 않는다. `timestamp`는 공식 기본 feature float32이고 `source.timestamp`는 원래 float64다. 원 시계 값·frame ordinal을 별도로 보존하며 재샘플링하지 않는다.

그리퍼 Policy 단위도 **rad**다. legacy collection telemetry의 0..100° 예에서는 rad→degree=`rad*180/pi`, fraction=`rad/(100*pi/180)`이며 90°는0.9다. 이 fraction을 Policy Action으로 바꾸지 않는다. 실제 Follower SDK native는 arm degree/gripper percent이며 **Precision profile의 계수·encoder branch·양자화**를 거친다. 일반 fraction 공식을 Precision 역변환 대신 쓰거나 baked residual을 실제 q에 다시 더하지 않는다.

## 실제 4 Episode·선택·Merge 검증

입력은 [직전 E 묶음](simulation-workflows-bundle.md)의 최종 MuJoCo/Isaac resumed Native Dataset 각2 Episode, 각399 frame이다. 총 **4 Episode/1,596 control frame**, camera별1,596 frame이다. 이번에 시뮬레이터를 다시 실행하거나 Dataset을 재생성하지 않았다.

[수치 소비자](evidence/l03-lerobot/numeric-consumer-results.json):

- 각 엔진2 Episode/798 frame, Native Merge와 공식→공식 Merge 각각4 Episode/1,596 frame을 공식 LeRobotDataset으로 열었다.
- 모든 selected row의 observation/state·action은 source HDF5와 원래 값 그대로 비교했다. 원 frame/time도 exact다. 공식 episode_index/frame_index/global index·구간 길이와 timestamp의 공식 dtype 경계를 확인했다.
- 모든 수치 row를 공식 HF torch Dataset의 실제 DataLoader로 읽었다. 전체 영상 반복 seek 비용을 만들지 않고, LeRobotDataset `__getitem__` 및 실제 DataLoader의 RGB/action chunk/processor는 각 Episode 시작·중간·끝을 별도 검증했다. 전체 `__getitem__`를 모든 frame에서 반복했다고 주장하지 않는다.
- 공식 numeric episode/aggregate statistics는 같은 원 배열에서 공식 계산기로 산출한 값과 exact다. Policy feature 분류 결과는 state/action/Side/Wrist뿐이며 source provenance·IK·post telemetry가 들어가지 않는다.

[영구 선택](evidence/l03-lerobot/persistent-selection-results.json)과 [영상](evidence/l03-lerobot/video-consumer-results.json):

- 기존 `save_curation/load_catalog/select_split`을 그대로 사용했다. 별도 creator process 종료 뒤 view를 재로드하여 각 엔진의 train=`datagen-1[5,81)` 76 frame, val=`datagen-2[13,103)` 90 frame을 복원했다.
- 공식 train은2 Episode/152 frame, val은2/180 frame, 제외 view는1/76 frame이다. train/val 원 Episode UID 교집합0이며 공식 학습 row에는 선택하지 않은 Episode/frame이 없다.
- 영상 파일에는 구간 밖 packet이 남지만 공식 row와 `from_timestamp` offset은 선택 frame만 읽는다. 각 Episode 시작·중간·끝의 공식 decoded RGB는 정확한 원본 pre-step frame과 pixel exact다. 모든 MP4는 동일 device/inode hardlink다. 품질·코덱·FPS·해상도를 낮추지 않았다. 기존 전체 PTS 증거와 선택 구간 CFR 검사를 재사용한다.
- Curation 전체 bulk copy는0이다. 독립 Export 요청의 copy 옵션은 기존 계약대로 남아 있고, 자동 cross-filesystem copy fallback은 없다.

### Merge 지원과 거부 경계

엔진이 다르다는 사실만으로 합치거나 배제하지 않는다. 두 실제 입력은 동일 Scene Revision/Manifest·Calibration·실행 kinematic URDF SHA·joint order·model rad absolute command·pre-step observation·camera frame identity/shape·30Hz가 입증되어 Merge했다. 물리 엔진별 model hash·dt/substep/solver topology는 그대로 domain provenance에 남긴다. 학습 IO 호환성은 양 엔진 물리 분포가 같거나 E01 잔차가 해결됐다는 주장이 아니다.

다른 Scene/모델·보정·관절 이름/순서·단위·camera/control 계약 또는 미확정 의미는 `MERGE_INCOMPATIBLE`/`CONTROL_CONTRACT_INVALID`로 거부한다. 저장 dtype만 다르면 float32→float64의 정확한 승격을 허용한다. Native와 official format family를 한 호출에 섞는 Merge는 지원하지 않으며 각각 명시 materialize 후 합친다.

Resume lineage의 한계도 차단한다. 현재 Native parent는 run 수준이므로 독립 copy된 원본/Resume의 각 inherited Episode creator를 완전히 복원할 수 없다. **동일 engine/domain에서 parent가 있는 여러 canonical Dataset을 섞지 않고 하나의 resumed Dataset을 선택한 뒤 Curation을 파생**해야 한다. 새 inode만으로 독립 입력이라고 판단하지 않는다. 원 origin이 없는 과거 archive·기존 Metadata가 부족한 official 자료도 자동 Merge하지 않는다. 관련 원본+독립 Resume 및 curated archive 중복 반례를 재현·거부했으며 Native C 저장 구조를 바꾸거나 근거 없는 provenance를 만들지 않았다. 이 제한은 전체 전역 content dedup 기능이 아니다.

## ACT·SmolVLA 공식 processor와 다음 학습 관문

[실제 processor 결과](evidence/l03-lerobot/processor-consumer-results.json)는 고정 설치 소스의 공식 factory/config·normalizer·postprocessor·이미 캐시된 실제 SmolVLM tokenizer를 사용했다. 네트워크 다운로드·모델 weight 로드·정책 forward는 없다. 캐시 snapshot/hash를 기록했고 설치/캐시를 수정하지 않았다.

- ACT 기본 chunk100: state `[B,6]`, action `[B,100,6]`, RGB `[B,3,480,640]`.
- SmolVLA 기본 chunk50: state `[B,1,6]`, action `[B,50,6]`, 같은 RGB. `adapt_to_pi_aloha=false`, `use_delta_joint_actions_aloha=false`로 model rad 절대 명령 의미를 유지한다. 모델 내부32차원 padding은 실제 학습/model 단계이며 L03에서 새 action 차원으로 저장하지 않는다.
- 실제 normalization은 공식 `(x-mean)/(std+eps)`, unnormalization은 공식 식 그대로다. 시험에서 max roundtrip 차이 약5.96e-8rad를 관측했다. eps를 제거하거나 원 target을 재작성하지 않았다.
- language task는 실제 문장, Smol newline/tokenization 후 관측 토큰이다. `pad_language_to='longest'` 기본값에서 이번 문장은13 tokens였으며 max48 고정 길이라고 가정하지 않았다.
- action chunk는 선택 Episode 끝에서 마지막 target으로 clamp되고 `action_is_pad`가 붙는다. train의 끝에서 다음 val/다른 Episode action을 읽지 않는다.

**SMOL-PAD-01 — L01 실제 학습 BLOCKED/확인 필요:** 설치0.4.1 Dataset/processor는 `action_is_pad`를 제공하지만 `SmolVLAPolicy.forward`는 `actions_id_pad`를 조회한다. 공식 기본 chunk에서 padding은 실제로 생긴다. loss가 이를 의도대로 제외하는지 L03에서 통과로 표시하지 않는다. SDK patch·키 monkeypatch·custom Trainer를 추가하지 않았다. 공식 `chunk_size=1,n_action_steps=1` config와 Dataset에서 padding 없는 후보는 확인했으나 Training 실행 검증/최종 학습 설정 선택은 L01에 남긴다. 이번4개 Episode만으로 학습/일반화 성공률을 주장하지 않는다.

## 실제 제어 경계·미해결 사항

[순수 제어 의미 검사](evidence/l03-lerobot/control-meaning-results.json)는 실제 엔진/버스 호출 없이 기존 preflight와 Precision inverse를 사용했다.

| 경계 | 관측 / 후속 책임 |
|---|---|
| Isaac | float64 recorded command→공식 float32 학습 target은 당시 실제 applied payload와 exact. 원 `joint_targets`와 payload의 차이를 삭제하지 않음 |
| MuJoCo | float32 학습 target을 float64로 전달하면 원래 actual float64 target과 최대약5.95484e-8rad 차이. 각 Episode4 frame의 wrist_flex는 strict upper1.7453264625997165rad보다 float32값1.7453265190124512rad가 약5.64127e-8rad 큼. 기존 `command_target`은 거부. tolerance 확대/clipping/target 수정을 하지 않음. L02/P01의 명시 제어 계약 결정·검증 필요 |
| Follower | sampled frame0의 shoulder_lift target은 현재 calibrated motor 범위 밖으로 strict inverse가 거부. 나머지 표본의 encoder 양자화 roundtrip도 원 명령과 bitwise 동일하지 않음. model-limit 적합성과 motor-limit 적합성은 다름 |
| Scene의 실제 command binding | 현재 follower record는 `device_observation`만 선언됨. `device_command` 요청을 기존 Scene API가 거부했다. 관측 mapper의 같은 순수 inverse 수식을 오프라인 비교했으나 이를 command binding 승인으로 바꾸지 않음. L02/P03 및 명시 Scene/장치 계약 검증 필요 |

정규화된 Policy 내부 출력을 모터에 보내면 안 된다. 공식 postprocessor 뒤 model rad 절대 명령을 엔진 preflight로 전달하고, 실물은 승인된 `device_command` mapping·strict inverse·SDK integer encoder 검사를 거쳐야 한다. 여기서 실제 Policy/엔진 배포·Follower command를 구현하거나 전송하지 않았다.

E01 cube–cup 위치1.197188790mm 잔차, Isaac Random persistent RNG·복수 Episode Annotation·같은 앱 재사용, MuJoCo 현재 Scene legacy uniform 배치, B02 과거 누락·B03 physical_verified=false/실물 미검증 상태는 모두 유지한다.

## 시간·메모리·용량

warm local filesystem, 고정 Python3.11.15/LeRobot0.4.1, 각 변환 별도 process. 수치/영상 선택과 공식 stats 계산·finalize·publish 시간을 포함한다. 기존 불변 데이터에 대해 고비용 payload 전수 검사를 매 helper마다 반복하지 않는다.

| 출력 | frame / Episode | 변환 s | Peak RSS MiB | 논리 bytes | 이번 새 allocated bytes |
|---|---:|---:|---:|---:|---:|
| MuJoCo | 798 / 2 | 3.665 | 872.60 | 2,291,932 | 229,376 |
| Isaac | 798 / 2 | 3.857 | 883.07 | 3,671,662 | 208,896 |
| Native→Merge | 1,596 / 4 | 5.714 | 886.33 | 5,855,957 | 319,488 |
| Official→Merge | 1,596 / 4 | 6.220 | 922.59 | 5,855,839 | 319,488 |
| train 구간 | 152 / 2 | 2.968 | 845.29 | 2,892,928 | 126,976 |
| val 구간 | 180 / 2 | 3.196 | 860.18 | 2,894,425 | 131,072 |

논리 bytes는 공유 MP4 전체 크기를 포함한다. 새 allocated는 원본과 hardlink로 공유된 영상을 제외한 이번 출력의 새 inode block 합이다. 작은 구간이 전체 영상 크기를 논리적으로 참조하는 것을 숨기지 않는다. Peak에는 Torch/Arrow/LeRobot import가 포함되고 import 전 baseline peak는약72~73MiB다. cache·별도 보존 원본·다른 비교 출력까지 합친 디스크 전체 사용량과 한 output의 수치를 혼합하지 않는다. 5GB급 workload나 실시간 동작 성능으로 일반화하지 않는다. [개별 측정](evidence/l03-lerobot/native-merge-final-materialization.json)에 파일 수·공유 bytes·baseline도 있다.

## 회귀·리뷰·보존·완료 기준

**전체815 passed, skipped0**, 기존 torchvision warning2개다. 기존795개+신규20개다. wheel의 source/config bytes·compile·isolated import/CLI 및 미구현 train worker의 STAGE_UNAVAILABLE도 통과했다. 원본56,100개 stat·선택160개 SHA의 미승인 변화0(실제 개수는 preservation-after 기록 기준). 전체 corpus/SDK binary 전수 hash 증명은 아니다. 빌드·원본 보존은 [최종 검증](evidence/l03-lerobot/verification.json), [JUnit](evidence/l03-lerobot/unit-tests.xml), [wheel](evidence/l03-lerobot/build-workbench.json), [보존 대조](evidence/l03-lerobot/preservation-after.json), [명령/소스 identity](evidence/l03-lerobot/commands.json)에 기록한다. 실제 Dataset/processor 검증과 unit suite를 구분하며 full Training은 미수행이다. Git 저장소가 없어 commit을 만들지 않았고 설치/업그레이드·환경 분리·실물/Hub 접근도 없다. 별도 lint/type 도구가 없는 상태에서 실행했다고 보고하지 않는다.

[Standards 리뷰](evidence/l03-lerobot/standards-review.md)의 인자 타입 누락을 수정했다. [Spec 리뷰](evidence/l03-lerobot/spec-review.md)의 두 번째 Dataset 관절 이름·saved camera/clock·NaN timestamp·독립 Resume/Archive 중복 반례를 RED→GREEN으로 수정/명시 거부했다. 리뷰는 각 지원 경계 안에서 확인했으며 남은 Training/제어 관문을 해제하지 않는다. 단순화는 반복 contract 계산 제거와 helper 책임 정리만 수행했고 새 범용 검증 프레임워크는 추가하지 않았다.

L03의 AC01 중 **공식 Dataset 변환·선택·지원 Merge·DataLoader/action 의미/영상·processor 준비** 부분을 완료했다. AC01의 실제 train 및 AC02 Policy/Resume 실행은 L01/L02, Hub는 L04다. 이번 작업은 L03에서 멈춘다.

공식 source: [LeRobot0.4.1 ACT processor](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/policies/act/processor_act.py), [SmolVLA processor](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/policies/smolvla/processor_smolvla.py). 최종 근거는 설치 소스의 hash/함수 위치이며 웹 fixed tag와 차이가 있으면 설치본을 기준으로 한계를 기록했다.
