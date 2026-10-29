# Real/Sim — Scene 기반 Follower 읽기 전용 관측

2026-10-30. 기준 `c7c6ef1`(Capture 피드백 수정), 브랜치 `scene-preparation-v8`. **Real/Sim을 Scene·엔진 선택, 읽기 전용 연결, 네 이미지 Capture, 중단의 전용 화면으로 교체했다.** Input Data/Scene 메모·Candidate/재렌더·Leader/Teleoperation UI와 구형 Candidate 기반 실행 경로를 제거했다. 기존 Capture 화면과 공용 mode 분기로 처리하지 않는다.

## 사용 흐름과 의미

`./run_workbench_ui.sh` → **Real / Sim** → `pickplace_colorblock · scene-v8-native`와 **MuJoCo / Isaac Lab** 선택 → **Real/Sim 연결** → Follower를 사용자가 수동으로 움직여 관측 → **Capture** → **중단**.

선택 Scene에 Binding된 Follower·SDK/Precision·Camera 구성과 해당 엔진 설정을 자동으로 불러온다. Leader는 필요하지 않으며 생성·연결하지 않는다. 이 화면은 실물 모터 Goal/Torque를 보내지 않고 현재 토크 상태도 바꾸지 않는다. 실제 Follower의 측정 q로 Sim 관절 상태를 갱신하고 실제 엔진의 Side/Wrist RGB를 렌더한다. 추가 runtime offset·IK·Policy·실물 command binding 또는 Teleoperation 승인 단계가 없다.

Scene은 현재 Workspace Project에 등록된 **닫힌 실행 Package**다. Builder Candidate는 Scene 편집·정합을 검토할 때 쓰는 자료이며 이 화면의 선택 대상이 아니다. Builder 자체의 Project/Candidate/Export 계산과 과거 Evidence는 그대로 보존한다. Scene/장치/엔진 설정이 부족하거나 identity가 다르면 연결 준비에서 구체적으로 거부한다.

상단에는 Scene·엔진, 중앙에는 REAL SIDE / SIM SIDE / REAL WRIST / SIM WRIST, 하단에는 측정 관절값·세 조작·Paired Capture 목록을 둔다. 오른쪽의 Input Data·Scene 메모와 Candidate 패널은 없다. 하단 목록과 상세 창에서 **네 이미지**를 모두 재개방한다. 연결 중 Scene/엔진 변경을 막으며 중단 뒤에는 Preview/연결 표시를 종료 상태로 바꾼다.

[실제 Qt1320](evidence/real-sim-observation/real-sim-1320.png) · [1920](evidence/real-sim-observation/real-sim-1920.png). 두 화면은 **MEMORY Follower/Camera + 실제 Native MuJoCo** 시험이다. 합성 줄무늬는 실제 카메라로 위장한 이미지가 아니다. 실제 장치의 새 수동 움직임 시험을 수행한 화면으로 주장하지 않는다.

## 한 실행 경로와 기존 API

| 소유 파일 | 현재 책임 |
|---|---|
| `ui/real_sim_page.py` | 실행 Scene/엔진 선택, 세 조작, 네 Preview와 상태. SDK/물리 import 없음 |
| `ui/session_page.py` | 독립 CapturePage. Scene 자료/메모 및 별도 승인 Teleoperation 유지 |
| `ui/snapshot_table.py` | 두 화면이 공유하는 불변 관측 목록/선택 ID 상세, 네 썸네일 |
| `ui/session_operations.py` | 등록 Scene 목록·장치 Binding·설정 복원. 포트 연결 없음 |
| `robot/real_sim.py` | Follower/Camera 읽기 전용 수명, 관측 정합, frozen Capture·종료/취소 |
| `robot/scene_render.py` | Scene/Mapping/설정 identity, 실제 MuJoCo/Isaac의 측정 상태 적용·렌더 |
| `robot/render_transport.py`, `render_worker.py` | 소유한 렌더 자식, 최신 요청/2slot과 단일 frozen Pair 요청 |
| `robot/capture.py`, `snapshots.py`, `pairs.py` | 기존 시각/안정성 계산, Snapshot transaction·공식 Reader·Builder Pair 등록 |
| `robot/session_devices.py` | 공통 SDK/Precision/Camera 생성. Real/Sim은 Follower만 생성 |

새 Manager·범용 Engine Adapter·Dataset 포맷을 만들지 않았다. 렌더 자식이 실제 Native 모델을 소유하고 Serial 관측은 부모 Session이 소유한다. Qt는 motor 계산·엔진·Torch를 실행하지 않는다. Source/Annotation/DataGen/Trainer의 물리·Task·명령 수식은 수정하지 않았다.

구형 CandidateView/CandidateRenderer/Isaac static Candidate runtime와 `paired_rerender` Stage를 제거했다. 해당 실행 전용 시험을 새 Native Scene/관측 시험으로 교체했다. 이관 시험에 필요한 순수 Builder authoring fixture만 분리해 유지한다. 기존 유한 `live.render_comparison` 구현도 삭제했으며 `real_sim` Stage에는 **명시 offline 보존 입력 검사만** 남긴다. 과거 저장 Recipe의 Candidate 입력이나 폐기 Stage를 몰래 새 실행으로 바꾸지 않는다.

## identity·기록·종료 계약

- Project에 등록된 Scene ID/Revision/Manifest와 실제 Package를 설정 복원 및 `prepare_recipe`에서 대조한다. Scene·engine_config는 해당 Project에 속해야 한다. 장치 연결 뒤 Prepared 입력을 재검사하고, render child를 만들기 직전에도 원 Prepared Scene/설정 SHA와 대조한다. 실행 중 Manifest/설정/자산 변경도 거부한다.
- Follower는 기존 공식 SDK·Precision·Raw/Native 검사를 재사용한다. 단순 port 번호로 역할을 결정하지 않는다. Memory 장치만 출력 경로의 독립 가상 port identity를 사용해 실물 Serial lease와 충돌하지 않는다. 실물 포트 잠금·읽기 전용 제한은 유지한다.
- Capture는 같은 frozen 측정 q에 대한 Real2+Sim2를 기존 `real2sim.snapshot/1`과 `real2sim.paired-observation/1`에 저장한다. `q_command=null`이며 학습 Action을 만들지 않는다. actual applied Sim state·dtype 차이와 Scene identity·Camera K/world pose·시각·비교 Metadata를 구분한다. 원 Real RGB를 편집하지 않는다.
- MuJoCo는 `qpos` + `mj_forward`, Isaac은 `write_joint_state_to_sim` + forward/render/Camera sensor를 사용한다. Physics rollout/Task Step은0이다. Isaac의 실제 float32 표현 차이는 `sim_joint_delta_rad`에 남기며 측정값을 원본과 exact인 것처럼 바꾸지 않는다. 기존 baked Geometry는 선택 Package의 실제 자산 그대로 사용하고 측정 q에 보정을 다시 더하지 않는다.
- Camera/joint skew100ms·age200ms·자세 안정성·새 Camera sequence 조건을 유지한다. Capture 버튼의 요청 가능 상태와 현재 저장 적격성을 분리하며 요청 후 최대5초 동안 유효 관측을 기다린다. 렌더는 비동기이므로 수신/렌더 age를 표시하며 실제와 Sim이 동시 노출됐다고 주장하지 않는다.
- 중단/취소가 같은 batch의 Capture보다 우선한다. 준비 중 중단이면 Worker를 시작하지 않으며, start 응답 대기 중이면 반환된 owned handle을 취소한다. Follower/Camera와 자신의 render child를 정리하고 terminal을 기다린다. 이미 완료한 Capture는 유지하고 진행 중 Pair가 중단되면 pending 위치·거부 ACK를 남긴다. Torque를 자동 해제하거나 다른 프로세스를 종료하지 않는다.

## 실제 검증

| 시험 | 결과와 범위 |
|---|---|
| 새 UI/계약 RED→GREEN | Input/메모/Candidate/Teleoperation 없는 전용 화면, Scene/엔진과 세 조작, Qt에 SDK import 없음 |
| Native MuJoCo 관측 | Memory Follower의 Raw 측정을 바꾸자 실제 Scene 관절과 Side RGB가 바뀜. motor write API를 실패하도록 한 상태에서 Pair1 저장·Reader 소비·같은 batch Stop 우선 확인 |
| Qt→R03→Native MuJoCo | 실제 새 화면으로 연결 → 네 Preview → Capture2개/이미지8장 → 중단 → 두 행/네 썸네일 재개방. Leader 생성0·명령 budget 없음·실물 연결0 |
| Native Isaac | 별도 소유 child에서 실제 Scene 두 측정 자세 렌더. Side/Wrist640×480·두 자세의 영상 차이·실제 float32 q 적용을 확인. Physics Step0·실물 장치 연결0 |
| identity 반례 | 잘못된 등록 Manifest, 다른 Mapping, 실행 중 Manifest 변경, prepare 후 engine_config 변경을 재현하고 child 실행 전에 거부 |
| 중단 경합 | prepare 중 중단은 late start를 막고, start 응답 대기 중 중단은 실제 반환 handle에 cancel 전달 |
| 기존 기능 | Capture·SDK/Precision·Source/Annotation/DataGen·Native/Resume·Curation·ACT/SmolVLA/Diffusion·Hub·Builder·Scene Contract 회귀 |

**최종 전체1,153 passed / skipped0**, 기존 torchvision 영상 deprecation 경고4회다. 폐기한 Candidate/유한 비교 전용 시험을 삭제·교체했으므로 단순 신규 시험 수와 전체 순증을 혼동하지 않는다. 첫 전체는 구형 Real/Sim Teleoperation 버튼을 기대하던 UI 시험1건이 실패했고 현재 명세에 맞춰 수정했다. 초기 이동 자극 harness가 Memory SDK의 읽기 closure 대신 사용되지 않는 `present` 속성을 바꾸던 문제, Fake port lease가 실제 이름을 공유하던 문제도 각각 구분해 재현·수정 후 새 출력에서 실행했다. 실패 출력은 지우거나 성공으로 합치지 않았다.

Isaac에는 기존 Material cache write 차단 audit·USD/Fabric/렌더/종료 경고가 남을 수 있다. 실제 RGB/state 소비와 own-child 종료를 별도로 확인했으며 warning-free 또는 성능 benchmark라고 보고하지 않는다. 실제 두 자세의 렌더와 Memory를 사용한 실행은 새 실물 관측/현장 정확도 검증이 아니다. RGB 비교 결과만으로 Geometry/Calibration 성공을 승인하지 않는다.

독립 Spec/Standards 검토에서 등록 Scene identity와 Prepared→render 초기화 사이의 변경 반례를 수정했고 최종 High/Medium 잔여0이다. Workbench wheel은 새 증거 폴더에서 빌드하여 source/config bytes·compile·격리 import/CLI 및 실제 invalid-config Worker를 검사했다. 설치하지 않았고 lint/type 도구를 추가하지 않았다.

원본56,100개 stat·원본 Python187개 SHA·선택 과거/SDK57개 SHA·Policy/Capture 입력47개 SHA 변화0, 원본/소유 v8 전체 Manifest identity 일치를 확인했다. Scene/Calibration/Dataset/Checkpoint·설치 SDK를 수정·이동·삭제하지 않았다. 전체 corpus/SDK binary 전수 hash는 아니다. Git은 로컬 `scene-preparation-v8`만 사용하며 main 변경·Push/Merge를 하지 않는다. 자산/증거/런타임은 기존 공개 제외 정책을 유지한다.

실제 Follower를 손으로 움직이는 **새 실물 E2E**, 장시간/장치 단절·물리 정확도·Camera 노출 동기화는 이번에 검증하지 않았다. 새 현장 Calibration·실물 구동 권한을 부여하지 않는다. 사용자의 실행 중 창/장치는 강제로 재시작하지 않았다. 이미 열린 Python 창은 바뀐 코드를 자동 반영하지 않으므로 사용자가 연결을 중단하고 창을 닫은 뒤 `./run_workbench_ui.sh`로 다시 실행해야 한다.

근거는 로컬 `docs/evidence/real-sim-observation/`의 RED/GREEN·`tests-final.xml`·`ui-mirror-results.json`·`isaac-mirror-results.json`·두 축 review·wheel·보존/verification 및 PNG다. 기존 Capture 깜빡임/오류 표시 원인은 [Capture 피드백](capture-feedback.md)에 별도로 기록한다.
