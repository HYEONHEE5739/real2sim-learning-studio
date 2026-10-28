# C01/C02 — Native Data Curation 검토·분포·Revision·Export

2026-10-27. **C01/C02의 데이터 기능과 UI 호출 경계를 구현·실제 자료로 검증했다.** UI 페이지·U01~U04/X01/P02/P03은 시작하지 않았다. 기존 Native C·L03의 선택/재로드/Materialization/Merge를 그대로 재사용하며 새 Dataset 포맷·Curation Manager·중간 bulk 저장 계층은 없다.

## 구현 기능과 호출

변경 제품은 [data/curation.py](../robot_learning_workbench/src/robot_learning_workbench/data/curation.py) 한 파일이다. 새 시험은 [test_curation.py](../robot_learning_workbench/tests/test_curation.py)와 [test_curation_export.py](../robot_learning_workbench/tests/test_curation_export.py)다. Native/LeRobot 저장 코드·Recipe/Worker·엔진·Task·Scene·Robot·SDK·환경은 수정하지 않았다.

| API | 지원 기능·명시 범위 |
|---|---|
| `inspect_dataset(source, split=None)` | 선택 Episode ID/구간·원본 성공 여부/seed·category·lineage·역사적 partition·camera/format, 원 run의 attempt/미확정 intent·closed 상태 |
| `filter_episodes(...)` | 기록된 성공/실패·category·저장 split에 따른 현재 선택 ID 목록. 기록에 없는 성공을 추정하지 않음 |
| `distribution(source, fields=None, split=None, bins=20, chunk_frames=2048)` | 선택된 half-open 구간만 읽는 성분별 count/min/max/mean/std(ddof0)/histogram. dtype·unit·phase·frame·joint order·component shape 포함 |
| `compare_distributions(sources, ...)` | 같은 단위·phase·frame·관절 순서·성분 수의 통계를 공통 bin으로 비교. unknown 단위는 거부. 비교가 Merge 승인을 뜻하지 않음 |
| `position_distribution(source, object_id, scene, frame, split=None)` | 선택 구간 첫 기록 pose를 정확한 Scene Revision의 S02 reference Transform으로 변환. XYZ/XY·m·원/표시 Frame·원 frame ordinal 명시 |
| `review_frame(source, selection_id, frame, ...)` | 선택-relative index→원 frame, 기록 Action/State와 실제 decoded RGB·MP4 PTS. 누락/비-CFR frame을 이전 영상으로 숨기지 않음 |
| `rgb_statistics(source, camera, split=None, stride=1)` | decoded MP4의 채널별 min/max/mean/std·픽셀 수. 선택 구간에서 decode한 RGB 수와 통계에 사용한 표본 수를 각각 표시 |
| 기존 `save_curation/load_curation/select_split` | 선택/제외/순서/구간·train/val/test·V1→V2 재편집. split provenance·명시 relocation 보존 및 저장 문서 경계 검사 보강 |
| `split_dataset(source, train_fraction=.8, seed=0, assignments=None)` | 기존 v8의 seed 기반 Episode choice/반올림/원 순서와 명시 배정. 전역 RNG 불변 |
| `revision_history(source)` | 현재 Revision→parent→original/materialized identity와 선택 수/구간 길이 |
| 기존 `export_native`, `lerobot.materialize/merge` | full Episode 독립 Native archive, 선택 구간의 공식 LeRobot Export, 입증된 IO 계약만 Merge |

`distribution` 기본값은 Native의 `obs/policy/joint_pos`/`joint_targets`, 공식 Dataset의 `observation.state`/`action`이다. requested/applied·post-state는 별도 명시 필드로 읽는다. 원본 숫자의 dtype/shape를 바꾸지 않고 **통계 누산만 float64**로 한다. 실제 Isaac의 post contact force는 `states/contact_force_w`의 `[2,3]`, N/world로 다루며 MuJoCo의 bool `states/finger_contact`로 바꿔 끼우지 않는다. 성분을 펼쳐 계산하되 원래 component_shape를 보존하고 force에 관절 이름을 붙이지 않는다.

Curation 단계의 읽기 전용 함수는 Qt나 worker 수명을 요구하지 않는다. 다음 UI는 같은 함수로 자료를 로드하고 선택을 편집한 뒤 기존 새 Revision 저장/Export를 호출하면 된다. 긴 읽기는 UI가 기존 작업 실행 경계에서 취소/수명과 함께 관리해야 하며 이번에 별도 Manager/분석 Recipe stage나 UI thread를 만들지 않았다.

## 원본·선택 구간·split·성공의 구분

모든 분포 결과의 scope에 Catalog identity/kind·split·Episode 수·선택 frame 수·원 half-open 구간을 기록한다. 전체 Dataset과 train/val을 함께 평균하지 않는다. 현재 view의 성공 표시는 **원래 전체 Episode의 기록 outcome**이며 잘라낸 구간을 새로 물리 판정한 성공이 아니다. attempt history는 원 Native run 전체의 범위로 별도 표시한다. 취소/실패 attempt에 없는 Episode를 만들거나 Dataset 내 완료 수와 동일시하지 않는다.

V2는 V1의 선택/구간 안에서 편집하며 원본 제외 자료를 자동 복원하지 않는다. 원본에서 명시적으로 새 분기를 만들 수 있다. frame index는 선택-relative와 original을 나누어 반환한다. Materialized Dataset에서는 original index가 해당 공식 Episode의 ordinal이며 더 이전 Native 원 frame/time은 기존 `source.frame_index/source.timestamp`로 보존된다. task 상태가 학습 projection에 없다면 요청 시 CURATION_FIELD_MISSING이며 0으로 채우지 않는다. 공식 projection에 실행 outcome/attempt가 없으면 unavailable/None으로 표시하고 Policy 성능을 추정하지 않는다.

Split은 현재 선택 ID/원 순서를 유지한다. 같은 원 Episode UID/Native alias를 서로 다른 role에 배정하면 거부한다. 역사적 Source partition/lineage는 원문 근거로 보존하고 현재 Curation 배정으로 재명명하지 않는다. Native의 partitioned Source 이어 수집 잠금은 기존 그대로다. **서로 다른 생성 Episode의 공유된 Source/Mimic 조상까지 독립이라고 증명한 것은 아니다.** split 결과는 알려진 Episode identity 기준이며 전체 전역 content dedup 기능이 아니다. Merge의 Resume-family/unknown-origin 거부는 L03 그대로다.

Seed 기반 split은 다음처럼 결과를 함께 저장한다. `split_provenance`는 선택 JSON의 작은 optional Metadata이며 기존 schema_version=1을 그대로 읽는다.

```python
allocation = split_dataset(source, train_fraction=.8, seed=1047)
view = save_curation(path, source,
    splits=allocation['splits'], split_provenance=allocation)
```

새 JSON에 generator seed·규칙·당시 source identity/배정을 보존한다. 이후 V2에서 일부 Episode를 제외해도 원 배정의 provenance와 현재 membership을 구분한다. 명시 배정인데 생성 seed를 제공하지 않은 경우 rule=explicit_episode_membership/seed=None으로 남긴다. 기록하지 않은 seed를 만들어 넣지 않는다.

## 이동·lineage·Export 경계

원본이 이동하면 자동 검색/fallback 대신 기존 `load_curation(..., relocations={old:new})`로 **같은 identity**를 입증한다. 검토/통계/frame/Revision history와 Native Export는 그 명시 해석을 유지한다. 새 V2 저장 시 상대 경로 resolution map을 작은 JSON에 보존하므로 원래 V1을 바꾸지 않고 프로세스 종료 뒤에도 재로드된다.

기존 L03 `materialize/merge`는 변경하지 않았다. **임시 relocation을 적용한 V1을 이 함수에 넘길 때는 먼저 경로 해석을 보존한 V2를 저장**한다. 일반 V1/V2와 새 저장 V2는 기존 API로 바로 처리된다. 미확인 origin이나 다른 Scene/model·보정/단위/관절/camera/control 계약을 자동 Merge하지 않는다.

`export_native`는 완전한 공식 HDF5 Episode의 독립 archive다. 잘라낸 학습 구간의 새 initial state를 측정했다고 주장하지 않고 REPLAY_INITIAL_UNAVAILABLE로 거부한다. trimmed 구간은 명시 LeRobot materialize를 사용한다. 독립 archive에 현재 Curation의 role을 원래 Source partition으로 부여하지 않는다. 공식 학습용 split은 선택된 Revision에서 직접 materialize한다.

## 실제 자료·공식 소비자 검증

[실제 생성 자료 결과](evidence/curation-bundle/actual-data-results.json): 이전 E 묶음의 최종 resumed Native **MuJoCo2+Isaac2 Episode**, 각399 frame을 읽기 전용으로 사용했다. 새 수집/학습을 수행하지 않았다.

- 엔진별 V1은 datagen-1 `[5,81)`/datagen-2 `[13,103)`, V2는 각각 **`[7,40)`33 frame / `[15,70)`55 frame**이다. 저장→creator process 종료→별도 Python 재로드의 선택 상태가 exact였다. V2의 parent identity도 유지했다.
- 모든 선택 수치 행의 state/action/grasp/contact 분포를 직접 NumPy float64 누산과 비교했다. histogram 성분별 합은 선택 행 수와 같았다. train33/val55와 view 전체88 frame을 별도로 확인했다.
- 각 Episode의 처음·중간·끝 Action/State·RGB와 PTS를 대응했다. `rgb_statistics`는 엔진별 Side88 frame을 실제 decode하고 stride10의 **10 frame**만 통계에 사용했다. 원래 압축 전 RGB를 복구했다고 주장하지 않는다.
- 실제 Scene에는 `workspace`라는 Frame ID가 없다. 묵시적으로 만들지 않고 기존 Recipe가 사용하는 **world** Frame으로 위치를 표시했다. 별도의 회전·이동 workspace fixture에서는 `inverse(T_world_display) @ T_world_robot_base @ T_robot_object`를 비교했다. 위치는 선택 구간 첫 pose이며 물리 reset initial을 대신하지 않는다.
- 기존 `merge`로 공식 **train2 Episode/66 frame**, **val2/110 frame**을 생성했다. 모든 Action row와 source.frame_index는 선택값과 exact였고 train/val source Episode UID 교집합0이었다. 실제 공식 LeRobotDataset `__getitem__`의 양 camera/action/state를 읽었으며 영상은 원 MP4와 같은 inode다. 영상 재인코딩/불필요한 전체 bulk copy가 없다.
- 동일 view를 두 번 Merge하는 요청은 기존 L03 경계에서 거부했다. unknown contract/다른 단위/Resume branch의 거부도 기존 시험을 재사용한다. 성공한 cross-engine IO 호환성과 물리 분포 동일성을 혼동하지 않는다.
- P01 완료 실패 자료는 엔진별2 Episode 모두 recorded_success=false로 검토됐다. 취소 자료는0 Episode와1 cancelled attempt로 표시됐다. pending/불명 intent도 완료 목록에 섞지 않는다.

[독립 Export](evidence/curation-bundle/independent-export-results.json)는 실제 MuJoCo399 frame1 Episode를 사용했다. full Native 독립 export의 숫자는 exact, 양 MP4는 별도 inode·bytes SHA exact, partition identity는 원본 그대로였다. archive 이동 후 official Native payload를 다시 열었다. 별도 trimmed33 frame의 공식 LeRobot 독립 export도 MP4 bytes가 같고 재인코딩이 없었다. 이 명시 독립 복사는 일반 Curation 선택의 참조/공유와 구분한다.

## 50 Episode·성능·용량

[50 Episode 측정](evidence/curation-bundle/benchmark50-results.json)은 B02에서 검증한 실제 과거 DataGen50 Episode/21,284 frame을 기존 명시 import API로 **소유한 임시 Native 공간에 한 번** 준비했다. 이전 임시 Native benchmark 출력은 이미 삭제돼 존재한다고 가정하지 않았다. 원 MP4는 hardlink로 사용했고 임시 출력은 시험 후 삭제했다. 이전 payload 전수 검증을 모든 helper에서 반복하지 않았다.

| 측정 | 결과 |
|---|---:|
| 임시 official Native 준비 |3.068s|
| state/action50 Episode 분포·histogram, chunk128 |.175s|
|40/10 split 배정·Revision 저장|.744s|
| 작은 선택 Revision |5,229B|
| 선택 자체 bulk copy |0|
| 해당 process Peak RSS |594.758MiB|

50개의 전체 수치 통계가 직접 NumPy와 일치했고, 원래 v8 `split_dataset` 함수 body를 오프라인 실행한 배정/순서와 **exact**였다. 이는 기존 `_selection`의 구형 reader를 새로 이관한 결과가 아니다. 검사할 Episode 목록만 같은 읽기 전용 경계로 제공했다. 원본에 저장되지 않은 run attempt 전체를 추측하지 않으므로 이 import 자료의 attempt 수는0이다. import에는 명시 runtime recording 단위가 없어 통계 단위는 **unknown**으로 표시했다. B02 지식을 숨은 단위 주입으로 쓰지 않으며 이 상태의 Dataset 간 단위 비교는 거부한다.

실제 최신4 Episode 검토/통계/위치·RGB·Revision 작업은 엔진별 약.98/.95s, 공식 train/val Merge는 약.81/1.02s였다. 두 엔진 V1+V2 선택 JSON 합은 각각1,161/1,159B였다. 전체 실제 소비자 process Peak RSS는865.266MiB이며 Torch/Arrow/LeRobot import를 포함한다. warm local filesystem의 작은 workload이고 UI 응답시간이나5GB급 성능 보장이 아니다. decoded_frames는 선택 구간의 RGB 수이며 seek 시작 keyframe부터 구간 전까지의 내부 decode는 포함하지 않는다. RGB stride는 통계 표본을 줄이지만 현재 구현은 선택 구간을 연속 decode하므로 **decode 비용이 stride만큼 감소한다고 주장하지 않는다.**

## 회귀·리뷰·보존·남은 범위

**868 passed, skipped0 = 이전846+신규22**, 기존 torchvision warning2개. [JUnit](evidence/curation-bundle/unit-tests.xml), [로그](evidence/curation-bundle/logs/23-full-suite.log), [wheel](evidence/curation-bundle/build-workbench.json). source/config bytes·compile·isolated import/기존 실제 CLI invalid-config 경계를 확인했고 환경에 설치하지 않았다. 별도 lint/type 도구를 설치/실행하지 않았다. 전체 회귀에는 기존 실제 MuJoCo 시험이 포함되지만 이번 Curation 실자료 probe는 저장 자료만 읽었다.

[Standards](evidence/curation-bundle/standards-review.md)/[Spec](evidence/curation-bundle/spec-review.md) 독립 리뷰의 입력 검증·split provenance·단위·relocation·RGB workload 표시 지적을 RED→GREEN으로 수정했다. 최종 미해결 지적0이다. 단순화 검토에서는 기존 선택/공식 writer를 다시 만들지 않고 공통 Catalog·좌표·수치 읽기 함수만 재사용했다. 새 Manager/중간 Reader class/Framework는 추가하지 않았다. Git 저장소가 없어 [작업 전 사본](evidence/curation-bundle/before/curation.py)과 SHA를 기준으로 검토했으며 Git diff/commit을 수행하지 않았다.

[보존](evidence/curation-bundle/preservation-after.json)은 기존56100개 파일 stat와 선택228개 SHA(source/SDK/기존 보고서·검증 root·Native 입력/L03 결과)를 대조했고 미승인 변화0이었다. 원본 숫자/영상/Scene/Calibration·고정 SDK·모든 과거 증거는 수정하지 않았다. 선택된 SHA·전체 기존 파일 stat 범위의 검증이며 대용량 corpus/모든 과거 증거 payload/SDK binary의 전수 byte 검증은 아니다. 명령·설치 source·제품/증거 identity는 [commands.json](evidence/curation-bundle/commands.json)과 [최종 확인](evidence/curation-bundle/verification.json)에 기록한다.

초기 probe는 없는 workspace Frame과 Isaac에 없는 finger_contact 필드를 요청해 명시 거부됐다. 실제 있는 world/force field로 harness를 고쳤다. 또 NumPy의 원래 float32 평균과 제품의 float64 누산 평균을 비교한 오차는 **같은 float64 통계 경계로 reference를 계산**해 확인했다. 원 데이터/숫자 정밀도·물리 판정/tolerance를 수정하지 않았다. 실패 로그도 남겼다.

C01 AC01/02의 선택/필터/split·통계·frame/unit 및 C02 AC03의 원본 보존·참조/이동/독립 Export·공식 소비 경계를 검증했다. UI의 영상·3D/2D 표시·사용자 조작/취소·thread 응답, 더 큰 영상 연속 검토와 장시간 부하, 미지원 구형 projection의 누락 데이터 복원은 미검증이다. 자동 부족 영역 탐지·추천·Recipe 자동 입력은 없다.

E01 물체1.197188790mm 잔차·Random/복수 Episode 제한·SmolVLA padding·Follower binding/motor range·실물 미검증은 그대로 OPEN이다. **C01/C02까지만 수행하고 U01~U04/X01/P02/P03은 시작하지 않는다.**

공식 근거: [h5py hyperslab](https://docs.h5py.org/en/stable/high/dataset.html#reading-writing-data), [NumPy1.26 histogram](https://numpy.org/doc/1.26/reference/generated/numpy.histogram.html), [PyAV seek/decode](https://pyav.org/docs/stable/api/container.html#av.container.InputContainer.seek). PyAV stable 문서는9.0.2로 표시돼 설치15.1.0의 실제 API/영상 시험을 함께 근거로 삼았다. [설치 소스 identity](evidence/curation-bundle/source-inventory.json)를 우선한다.
