# B01 — 기존 v8 실행·계산 Baseline

실행일: 2026-10-25. 상태: **B01의 대표 입력·경계 fixture 확보 완료**. 새 Workbench 구현·기존 결함 수정·업그레이드·실물 시험 결과가 아니다. B02 이후 작업은 시작하지 않았다. [원본 보존 대조](evidence/b01/preservation-after.json), [검증 판정](evidence/b01/verification.json), [전체 수치·배열·영상 색인](evidence/b01/captured-baseline.json)을 함께 본다.

## 1. 결정과 실행 범위

- 개발 기준은 **Isaac Sim 5.1 / Isaac Lab 2.3 / LeRobot 0.4.1 / MuJoCo 3.3.7**로 고정했다. [최신 버전 조사](version-compatibility.md)는 참고 이력이다. 환경 설치·업그레이드·분리 추론·업그레이드 대응 코드는 만들지 않았다.
- 기존 Native Source·Annotation과 미전환 workflow DataGen·Evaluation을 각각 실제 실행했다. 기존 수식과 실행 의미를 Reference로 삼으며 미완성된 구조를 새 아키텍처에 복사하지 않는다.
- 실물 Leader 대신 결정적인 가상 입력을 사용했다. 실제 Leader/Follower/CalibrationDevice 연결을 금지했고 serial·USB·video 장치 open도 차단했다. Source 결과는 **시뮬레이션 시연 기록**이며 실물 Teleoperation 검증이 아니다.
- 모든 출력·캐시·Kit 로그는 `docs/evidence/b01/`에 분리했다. 엔진용 GPU 접근은 사용했다. Python의 파일 감사 훅은 보조 방어이며 네이티브 SDK 전체에 대한 filesystem sandbox 보장은 아니다.
- 현재 구현이 가진 원래 `four_anchors`와 `uniform`을 Baseline으로 채취했다. 새 플랫폼에서 four_anchors를 제외한다는 승인과 과거 동작 보존을 구분한다.

## 2. 환경과 입력 identity

| 항목 | 실제 사용값 / 근거 |
|---|---|
| OS / GPU | Ubuntu 22.04.5, kernel 6.8.0-136, RTX 4060 Laptop 8188 MiB, driver 580.178.04 |
| 실행 Python | `/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python`, Python 3.11.15 |
| 라이브러리 | Sim 5.1.0.0, Lab `VERSION=2.3.0`, LeRobot 0.4.1, MuJoCo 3.3.7, Torch 2.7.0+cu128, NumPy 1.26.0, Transformers 4.57.1 |
| Lab 버전 표기 | 설치 distribution metadata는 `isaaclab=0.47.2`, checkout VERSION은 `2.3.0`; 서로 다른 표기를 임의로 바꾸지 않음 |
| 기존 코드 P | `/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab` |
| 기존 저장소 HEAD | `875e64fe6673e664f6fa8203d15ab103d488a6ad`; 미커밋 파일을 포함한 실제 파일 SHA가 기준 |
| Scene | `outputs/real2sim/environments/scene2_builder/v8`의 byte-identical 검증 복사본 |
| 검증 코드·Asset 복사 | `evidence/b01/runspace/soarm101_lab/`; 448개 파일과 역사적 URDF 별도 증거 |
| 반복 조건 | env 1개, Source/생성/평가 seed 1047. DataGen attempt seed는 원래 변환 결과 `892243098` |

[환경 상세](evidence/b01/environment.json), [입력 SHA와 실행 색인](evidence/b01/baseline-manifest.json), [참조 복사 SHA](evidence/b01/reference-copy.json)에 기록했다. 복사본의 루트 경로·출력 위치와 장치 입력을 바꾸었고 알고리즘 파일의 bytes는 바꾸지 않았다. 이 B01은 새 self-contained Scene Export나 이동 패키지 검증이 아니다.

기존 자료의 상대 경로는 `/home/hyeonhee/soarm_isaaclab/soarm101_lab/` 기준이다.

| 용도 | 입력 |
|---|---|
| Annotation replay | `outputs/workflow/sources/source_20261019_011706_fd32/origin/dataset.hdf5`의 demo_0, 388 frame, 원래 MuJoCo Source |
| DataGen | `outputs/workflow/annotations/source_20261019_011706_fd32/origin/annotate_cube_red_to_cup_a_20261019_015955_db9b/dataset.hdf5`의 demo_0 |
| Evaluation | `outputs/workflow/models/act/train_cube_red_to_cup_a_20261018_010654_e162/checkpoints/050000/pretrained_model`의 실제 ACT 및 공식 processor |
| 실패 Annotation | 이번 가상 입력 Source의 24 frame Episode; 파지를 수행하지 않은 정상적인 거부 사례 |

Source는 red block·cup_a를 명시한 기존 Native 설정을 썼다. Annotation은 기록 당시 Scene 구성을 복원한다. DataGen은 기존 입력 및 기존 기본 물체 구성을 유지했고, Evaluation은 기존 active_object_ids로 red block을 선택했다. 서로 다른 단계의 물체 구성을 새 Recipe 의미에 맞추려고 통일하지 않았다. 평가 Policy 추론 장치는 MuJoCo=CPU, Isaac=CUDA이므로 두 엔진의 Policy 수치를 직접 동등성 비교하지 않는다.

### 실행 필수 역사적 모델 의존성

안전한 복사본에는 원본 `.git`이 없으므로 첫 Source 준비에서 historical URDF identity 검사가 실패했다. 현재 URDF로 대체하거나 검사를 끄지 않았다. 기존 Git commit `b7e6dbb30a2d12bfdc0a2ad5185aaec0e0426112`의 `assets/SO101/urdf/so101_isaaclab.urdf`를 읽기 전용으로 추출해 검증 공간에만 두었다. SHA-256은 `3b676464eb11410752707021f9d07b988439b46e37d5605cdbfe9508de14e5dd`다. 이후 원래 모델/profile 검사를 통과했다.

[추출 근거](evidence/b01/historical-model-evidence.json)는 **현재 로봇 Asset hash와 보정 근거 모델 hash를 별도로 보존해야 하는 이유**다. 새 패키지에서 Git 이력 검색에 의존하는 방식까지 재사용하라는 뜻은 아니다. Finger Collision·보정 모델·실행 필수 profile 포함 및 manifest 상대 참조는 기존 ASSET-FINGER-01/BU03의 미완료 검증으로 유지한다.

## 3. 실제 실행 결과

| 단계 / 대표 case | MuJoCo | Isaac |
|---|---|---|
| Source A/B/C | 각 24 frame, Episode 1개 기록, report passed=true | 각 24 frame, Episode 1개 기록, report passed=true |
| Annotation A/B | 각 388 frame, physical replay/StableGrasp/Placement 통과, accepted=1 | 같은 MuJoCo 기록을 cross-replay, 각 388 frame, accepted=1 |
| Annotation 실패 사례 | 24 frame 재생, grasp_failure, accepted=0; 성공 Episode 미저장 | 이번 실패 사례 미실행 |
| DataGen A/B | 각 1 attempt → 성공 1개, 399 step | 각 1 attempt → 2 step 후 strict IK 실패, 성공 0개 |
| 실제 ACT Evaluation A/B | 각 60 step 정상 종료, Task 성공 0, timeout/grasp_failure | 각 60 step 정상 종료, Task 성공 0, timeout/grasp_failure |

여기서 report의 `passed`는 실행 보고의 의미를 따른다. Evaluation의 passed=true를 Task 성공으로 바꾸어 읽으면 안 된다. 60 step은 control 30 Hz에서 2초의 제한된 Baseline이며 Policy 성능 평가용 성공률이 아니다. Source에는 성공 gate를 추가하지 않았다.

정상 실행 식별자는 Source의 `{source_mujoco,source_isaac}_{A,B,C}`, Annotation의 `{annotation_mujoco,annotation_isaac}_{A,B}`, `annotation_mujoco_failure`, DataGen의 `datagen_mujoco_A_valid`, `datagen_mujoco_B`, `datagen_isaac_{A,B}`, Evaluation의 `evaluation_mujoco_A_valid`, `evaluation_mujoco_B`, `evaluation_isaac_A_final`, `evaluation_isaac_B`다. 각 `evidence/b01/runs/<case>/data/report.json`이 원래 실행기의 보고서이며 `trace.jsonl`에 관측 기록이 있다.

Kit 종료 시 원래 루틴이 인터프리터를 종료해 harness의 마지막 result 기록에 도달하지 않는 사례가 있다. **종료 code 0이나 harness result.json 존재만으로 성공 처리하지 않았다.** 원래 report·Dataset·attempt 기록·frame 수를 확인했다. Isaac DataGen의 프로세스 exit 0도 성공 Dataset 생성을 뜻하지 않는다.

### Annotation 수치와 기록 시점

| 측정 | MuJoCo | Isaac cross-replay |
|---|---:|---:|
| 기록 대비 joint L2 최대 오차 | 5.100571820486155e-10 rad | 0.15540461187487115 rad |
| 기록 대비 물체 위치 최대 오차 | 1.836643820820217e-8 m | 0.02775257304178534 m |
| StableGrasp 최초 post-step tick | 222 | 221 |
| 저장된 pre-step grasp 최초 frame | 223 | 222 |
| 저장된 placement 최초 frame | 308 | 310 |

tick/frame은 0부터 센다. `native/annotation.py:98 _episode`는 **pre-step state·영상·현재 latch 기록 → 명령 실행 → post-step 접촉·상대 pose로 tracker 갱신**한다. 따라서 위 한 frame 차이는 현재 기록 계약이다. 수식만 이관하고 tracker 호출을 pre-step으로 옮기면 의미가 바뀐다. Isaac 오차는 원래 MuJoCo 데이터와의 cross-engine 차이이며 신규 코드 회귀 오차가 아니다.

### DataGen의 확인된 성공과 실패

MuJoCo는 기존 Mimic가 source index 0의 `[0,225]`, `[225,388]` 구간을 선택했고, 399 step 후 Placement AND latched StableGrasp를 통과했다. 최초 grasp post tick=231, 저장 grasp frame=232, place frame=332다. IK 시간 진단을 제외한 재실행 데이터와 attempt 내용이 일치했다.

Isaac은 두 번 모두 같은 source/seed에서 IK 세 번째 호출의 pose 조건을 통과하지 못하고, 이미 실행한 2 step 뒤 attempt를 중단했다. 해당 candidate의 위치 오차는 **0.0008103567233128162 m**, 회전 오차는 **0.1509191760094915 rad**이며 원래 회전 허용값은 **0.12 rad**다. optimizer convergence와 pose acceptance는 다르다. 실패 수치와 조건을 보존했고, 성공 fixture를 만들려고 tolerance·solver·입력·예산을 바꾸지 않았다. 이 조건의 Isaac 성공 DataGen trace는 확보되지 않았다. 이는 후속 이관에서 숨기지 말아야 할 Reference 실패다.

## 4. 동일 엔진 반복 비교

비교 단위는 저장된 배열의 dtype/shape/값과 디코딩한 영상·frame PTS다. HDF5 전체 bytes는 경로·metadata 등의 차이가 있으므로 그 자체를 수치 동등성으로 사용하지 않았다. 결과는 [repeat-variation.json](evidence/b01/repeat-variation.json)에 있다.

| 조건 | 수치 배열 | 영상 |
|---|---|---|
| MuJoCo Source A/B/C | 25/25 exact | PTS·디코딩 RGB exact |
| Isaac Source A/B/C | 26/26 exact | PTS 동일, RGB 차이 |
| MuJoCo Annotation A/B | 37/37 exact | PTS·RGB exact |
| Isaac Annotation A/B | 37/37 exact | PTS 동일, RGB 차이 |
| MuJoCo DataGen A/B | 60/61 exact; `ik_duration_ms`만 차이 | PTS·RGB exact |
| Isaac DataGen A/B | 성공 Dataset 없음; wall duration 제외 attempt 수치/분류 동일 | 성공 영상 비교 없음 |
| MuJoCo Evaluation A/B | 28/28 exact | PTS·RGB exact |
| Isaac Evaluation A/B | 22/28 exact; 같은 Task 실패 결과 | PTS 동일, RGB 차이 |

Isaac Evaluation의 최대 절대 차이는 `joint_targets` **0.01603829860687256 rad**, 관측 `joint_pos` **0.014725685119628906 rad**, 저장 action **0.0024917862408895732**다. action의 단위는 기존 action metadata를 따르며 joint rad로 다시 이름 붙이지 않는다. action 차이는 첫 frame부터, 관측 joint 차이는 frame 1부터 나타났다. Source·Annotation에서도 Isaac 영상 픽셀 차이가 있었다. Evaluation side/wrist 영상의 평균 절대 RGB 차이는 각각 약 1.078/1.132(0..255)다.

영상 차이와 추론 차이의 인과관계, 압축 전 Policy 입력, CUDA 결정성은 이번에 분리 검증하지 않았다. 디코딩 MP4만으로 원인을 단정하지 않는다. 두 번의 측정 차이를 새 허용 오차로 채택하지 않았으며 신규 구현은 이 변동을 구분해 검증해야 한다. 추가 결정성 분석은 해당 평가 연결의 미확정 항목이다.

## 5. 판정·Reset 경계 fixture

[boundary-fixtures.json](evidence/b01/boundary-fixtures.json)은 실제 기존 함수를 호출한 **StableGrasp 15개 sequence, Placement 13개 상태, Reset 두 모드와 1,000회 소진**의 입력·중간값·출력을 담는다. [contact-reset-fixtures.json](evidence/b01/contact-reset-fixtures.json)은 접촉 추출 9개와 실제 MuJoCo rollback 2개다. 제어된 접촉 입력 시험과 실제 물리 실행을 구분한다.

| 대상 / 원래 위치(P 기준) | 확인된 의미 |
|---|---|
| `real2sim/workspaces/grasp.py:9 StableGrasp` | 양측 접촉, relative drift ≤6 mm, relative angle ≤10°, EEF/물체 순이동 각각 ≥5 mm, `(N-1)*dt+1e-9 ≥0.20 s`; 동일 tick 중복·tick 누락·latch 수명은 기존 unit/sequence로 확보 |
| `simulation/mujoco_backend.py:237 success_details` | target-local 8 꼭짓점, cup 높이별 반경/벽 두께, radial excess ≤1 mm, 바닥/상단 엄격 부등호, 선속도 <0.03 m/s |
| `native/isaac.py:388 annotation_contacts` / `workflow/adapters.py:349 contacts` | Native Annotation 및 sensor 분기 >1e-4 N, Evaluation direct contact view >0.01 N; 후자의 sensor fallback은 >1e-4 N. 엔진·분기 값을 통일하지 않음 |
| `simulation/mujoco_backend.py`의 `finger_contacts` | 지정 target/finger body pair, contact.dist ≤0. controlled -1e-8/0/+1e-8 입력에서 True/True/False |
| `real2sim/workspaces/reset.py:17 sample` | 원래 모드별 seed/RNG 전후 상태·물체 순서·높이 채취; uniform 충돌 후보 1,000회 소진 시 ValueError, sample_index 증가 없음 |
| `native/mujoco.py:22 reset_objects` / backend `reset_object_poses:219` | 후보 생성 뒤 엔진 적용 1회. support 밖/Geometry 관통 시 오류 및 qpos/qvel exact rollback; 이 API에서 자동 재추출 0회 |

기하학적 sampler의 1,000회와 **엔진 적용 실패 후 재시도**는 다른 계약이다. 새 Interface의 모든 충돌을 같은 예산으로 재추출하는 설명을 v8에 자동 적용하면 기존 동작이 달라질 수 있다. [구현 전 확인 목록](preimplementation-checks.md)의 V8-03에서 보존 경계를 명시했다. v8의 높이 계산·3 mm 여유를 일반 Geometry 접촉 배치로 교체하지 않았다.

경계 fixture의 수치 출력 자체가 기준이다. 예를 들어 코드상 상단은 strict `<`지만 target/world 왕복 후 이론상 `top0` 입력이 수치상 경계 아래가 되어 True였다. nominal equality라는 이름만 보고 False로 고치지 않는다. dtype·변환 순서·실제 변환 결과도 함께 보존한다. 속도 0.03 m/s는 실제 False였고, radial 경계 ±1e-9 m 입력도 기록했다.

실행 control dt는 기존 30 Hz이며 MuJoCo Source/생성은 1/300 s×10, Isaac Builder Scene 구성은 1/240 s×8을 사용한다. 단계별 원래 cfg/recorded dt를 기준으로 하며 두 엔진의 physics dt를 통일하지 않는다. 모든 runtime 내부 상태/원시 force buffer를 전수 채취한 것은 아니다.

## 6. 기존 구조와 재사용 경계

| 기능 | 실제 호출과 보존 대상 | 그대로 복제하지 않을 구조 |
|---|---|---|
| Native Source | `native/source.py:87 prepare`, `:121 run` → `native/{mujoco,isaac}.py`; measured/requested/applied·초기 state·pre-step 영상·recording_only 의미 | 기존 JSON/bridge/import 연결을 새 YAML 계약에 강제하지 않음 |
| Native Annotation | `native/annotation.py:98 _episode`, `:166 run`; initial restore·manual/auto 채택 의미·pre/post-step 경계 | 다른 단계와 강제 공통 loop를 만들지 않음 |
| DataGen | `workflow/datagen.py:138 run_mujoco`, `:310 run_isaac`, Mimic reference·source 선택/RNG·IK pose 검증·budget·실패 분류 | 미전환 unified/adapters 경로 자체를 신규 Engine ABC/Wrapper로 이식하지 않음 |
| Evaluation | `workflow/evaluation.py:220 evaluate_sim`, 기존 Policy/processor·Placement 종료·별도 grasp/transport/full_task 지표 | 기존 구조의 MiniVLA import/의존성을 새 Workbench에 이식하지 않음 |

검증용 byte-identical 전체 참조 복사에는 과거 MiniVLA 소스도 들어 있다. 이는 원래 import graph를 조사하기 위한 **B01 증거**이며 신규 플랫폼 모듈·호환 계층이 아니다. MiniVLA 모델·학습·추론은 실행하지 않았다. 이관 제외 결정은 그대로다.

## 7. 검증 절차와 보존 증거

기존 시험 두 파일 `test_stable_grasp.py`, `test_native_annotation.py`를 복사본에서 실행했다. **29 passed in 5.05 s**. [시험 로그](evidence/b01/logs/existing-unit-tests.log). 후자의 mock/scheduler 시험 통과를 실제 물리 replay와 혼동하지 않으며 실제 v8 실행은 위 표의 독립 증거다.

실제 명령은 `evidence/b01/logs/<case>.command.json`, stdout/stderr는 `<case>.log`다. [harness](evidence/b01/harness/run_case.py)는 장치 대체·관측용 wrapper·출력 분리만 담당한다. 공식 AppLauncher로 Isaac을 시작한 뒤 원래 runtime을 실행한다. 원본 파일을 수정하는 monkey patch는 없으며, 프로세스 안에서 관측 함수와 가상 장치만 연결했다. 기존 함수의 결과·예외는 그대로 반환한다.

초기 검증 harness의 준비 실패도 삭제하지 않았다: historical URDF 누락, 원래 output 보호에 걸린 harness `config.json` 이름, request의 top-level renderer 누락, Isaac App 시작 순서, tracer의 잘못된 counter 속성이다. 이를 수정한 것은 harness이며 기존 제품 코드 결함으로 분류하지 않았다. `*_A_valid`/`*_A_final` 등의 정상 재실행과 구분한다. 초기 일부 command 기록에는 실행 당시 harness SHA가 없어 현재 SHA를 과거 SHA로 소급 기재하지 않았다.

재실행 시 `harness/launch.py <stage> <engine> <새로운_case_ID> ...`를 arena Python으로 호출하고 해당 case의 `command.json` 인자를 따른다. 기존 case ID는 재사용하지 않는다. 이 경로의 절대 위치는 조사 공간에 결합되어 있으며 새 이동 패키지 API가 아니다. 원본 Dataset은 읽기 전용으로 열고 신규 출력에 기록한다.

원본 대조 결과:

- `/home/hyeonhee/soarm_isaaclab`의 `.git` 제외 **56,100개** 파일 stat: 추가·삭제·size/mtime/symlink 변경 0.
- 기존 코드·Asset·설정 및 선택한 설치 Metadata/Isaac setup 등 **14,209개 SHA-256**: 차이 0.
- 검증 복사 **448개**의 원본/복사 SHA: 차이 0. historical Git blob도 기록된 hash와 일치.
- 기존 Dataset payload 전체의 실행 **전** hash와 외부 SDK 모든 binary hash는 수집하지 않았다. 입력 전체 hash는 Baseline identity로 별도 기록했으며, 이를 실행 전후 전체 byte 대조로 과장하지 않는다.
- 패키지 설치·환경 변경·기존 파일 정리·실물 제어·Hub 업로드 없음. 새 프로젝트는 Git 저장소가 아니므로 commit은 수행하지 않았다. 기존 저장소에 조사 결과를 commit하지 않았다.

## 8. 남은 문제와 완료 경계

B01은 대표 Baseline 확보 작업으로 완료한다. **모든 기존 기능 정상화, 양 엔진 제품 이관 완료, 실물 정합 검증 완료를 뜻하지 않는다.**

| 남은 항목 | 현재 근거 / 후속 경계 |
|---|---|
| Isaac DataGen 성공 trace | 이번 strict IK 실패는 반복 재현; 다른 성공 입력·장기 생성의 검증은 없음. 조건 완화 없이 원인/영향을 다루어야 함 |
| Isaac Evaluation 결정성 | 영상 및 6개 배열 반복 차이, 원인 미확정. 신규 평가 연결에서 원시 입력/추론/물리 원인을 분리할 필요 |
| 원시 접촉/다중 환경 | 실제 stage의 boolean 및 controlled threshold fixture 확보. raw force buffer 전체·env 여러 개·여러 seed·다른 색상 Task 전수 검증 없음 |
| 과거 자료/Resume | 대표 initial replay·배열 확보. 전체 형식 호환 표·partition/seed continuation·Resume·새 writer 장애/부하 시험은 B02/D 계열 미착수 |
| Calibration/실물 | 기존 identity 검사를 통과해 사용한 상태이며 실물/calibration 계약 전수 확인은 B03. 로봇·카메라 연결 없음 |
| Asset 패키지 이동 | 현재 복사 공간에서 로딩. 새 Export manifest에 Finger Collision 및 모든 외부 의존성 상대 경로를 연결하는 BU03/ASSET-FINGER-01 미수행 |
| 렌더 경고 | Isaac tool0 visuals/Fabric 및 작은 렌더 해상도 관련 경고는 각 Kit 로그에 보존. 원본을 수정해 제거하지 않음 |

V8-01/02/03은 아래 대표 조건의 **근거 확보**로 갱신하며 전 범위 확인 완료로 올리지 않는다. 승인된 설계와 충돌할 때 원래 동작과 승인된 변경을 구분하고 새 수식/허용 오차를 임의 채택하지 않는다. B02 이후 작업은 자동 시작하지 않는다.

## 내가 직접 확인할 것

1. 실행 표에서 workflow 정상 종료와 Task 성공/실패를 분리했는지 확인한다. 특히 Isaac DataGen 실패와 2초 Evaluation 제한을 검토한다.
2. Annotation의 post-step tick과 저장 pre-step frame 차이를 신규 구현의 비교 기준으로 사용한다.
3. 후속 작업 착수 때 해당 입력·hash·원본 판정·미검증 범위를 연결한다. 이 보고서는 실물 제어 승인이나 다음 작업 착수 지시가 아니다.
