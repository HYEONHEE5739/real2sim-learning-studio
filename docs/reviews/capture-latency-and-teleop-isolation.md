# Capture 지연·Teleop 중지 재현과 저장 프로세스 분리

2026-11-17. `feat/simfoundry-style-reconstruction`, 시작 HEAD `8e02b1ae023a856694a40b947881f76b66410624`. 기존 미커밋 변경을 보존하고 Scene Prepare와 Real/Sim의 Capture 경로를 수정했다. **Memory 장치·실제 저장/Reader/등록 코드로 검증했으며, 실제 로봇의 연속 Capture는 미검증이다.** 공용 Robot 자산 전환은 [별도 구현 계획](robot-resource-migration-plan.md)이며 이번에는 모델이나 기존 Capture를 이동하지 않았다.

## 최신 실패와 재현 범위

사용자 세션 `c5d5391b446945ddba4934e3adfc0d68`의 실제 R03 이벤트는 다음 순서다.

| 이벤트 순번 | 관측 사실 |
|---|---|
| 4737 | `TELEOP_ACTIVE`, Teleop 활성 |
| 4812 | Capture 시작, `CAPTURING`, Teleop 활성 |
| 4815–4816 | Capture가 진행 중인 채 Teleop 비활성, `Stale feedback/Leader command` |
| 4846 | Snapshot 저장 완료, `OBSERVING`, Teleop 비활성 |
| 5038 | 사용자가 Teleop 재시작 |
| 11963 | Capture 밖에서 `Stale session heartbeat/control cycle`로 다시 중지 |

따라서 이번 Capture 중지는 단순 저장 예외가 아니다. 기존 코드의 100ms feedback/Leader freshness 검사가 실제로 중지시켰고 저장은 이후에 완료됐다. 이전 개선의 일반 `OSError` 처리와 선택 USB 식별 검사만으로 이 경로가 해결된 것은 아니다. 과거 이벤트에는 각 작업의 timestamp·CPU 구간 기록이 없어 특정 codec이나 함수가 당시 지연을 전부 만들었다고 확정할 수 없다. Capture 밖의 두 번째 중지도 별도 실물 원인이 **UNKNOWN**이다.

실제 코드에서 확인한 문제는 다음과 같다.

1. `HardwareSession`과 `RealSimSession`의 PNG/배열 계산/모델 SHA/Builder 등록이 `ThreadPoolExecutor`에 있었으므로 motor 제어 스레드와 Python GIL을 공유했다. thread 분리만으로 제어 실행을 보호하지 못했다.
2. `align_measured`는 같은 feedback packet의 전체 Precision 변환을 joint마다 여섯 번 반복했다. 결과는 한 번의 변환으로 충분하다.
3. Pair마다 두 Camera의 comparison PNG 여섯 장을 기본 압축6으로 작성했다. 이는 원본 Real/Sim RGB에서 만든 진단 자료다.
4. freshness 검사 실패가 `last_attempt` 생성보다 빨라 실패한 실제 cycle의 진단이 누락될 수 있었다.

`test_capture_workload_isolation.py`에서 실제 Session의 저장 executor에 **160ms 동안 자기 interpreter의 GIL을 유지하는 합성 C 작업**을 넣었다. 실제 `Teleoperation.tick`이 fresh Follower feedback을 얻은 직후 이를 시작하면 두 화면 모두 사용자 오류와 같은 `Stale feedback/Leader command`로 RED가 됐다. 이 시험은 동일 interpreter의 실행 방해 경계를 재현한 것이며, 실제 PNG encoder가 정확히 그 방식으로 160ms를 점유한다는 측정은 아니다.

## 수정한 실행 경계

기존 `SnapshotStore.prepare/finish`를 세션 소유의 **spawn 자식 프로세스 한 개**에서 실행한다. 새 Process Manager/DB/Framework는 없다. 표준 `ProcessPoolExecutor`의 별도 interpreter와 `spawn`을 사용해 활성 serial bus·camera·renderer·Project 객체를 상속하지 않는다. 소유 R03 process group 안에 남고, 기존 종료 경계에서 장치를 먼저 멈춘 뒤 저장 프로세스를 join한다. [Python 프로세스 executor](https://docs.python.org/3.11/library/concurrent.futures.html#concurrent.futures.ProcessPoolExecutor), [spawn 계약](https://docs.python.org/3.11/library/multiprocessing.html#contexts-and-start-methods)

- 연결 전에 자식 초기화·기존 Reader import·mapping/model 검증을 끝낸다. 초기화 실패 상태에서 장치를 열지 않는다.
- OpenCV의 내부 thread 수는 **저장 자식에서만 1**로 제한한다. 전체 호스트·기존 환경·Renderer 설정은 바꾸지 않는다.
- 상태·RGB는 수신 시점에 고정해 전달한다. 저장 시각을 새 촬영 시각처럼 쓰지 않고 원 measured q·Camera receipt time·Mapping을 유지한다.
- `last_sequences`, 완료 응답, rename 뒤 등록 실패의 pending 경로는 한 자식의 Store에 유지한다. 부모의 capture eligibility에도 완료된 sequence를 반영한다. 프로세스마다 Store를 새로 만들어 같은 frame을 재사용하는 방식이 아니다.
- rename 이후 등록이 실패하면 실제 보존 경로도 예외의 직렬화 상태로 부모에 전달한다. 두 화면의 pending/report에 이미 없어진 staging 경로만 남기지 않는다. Scene Prepare의 기존 명시 `session_import` 재시도는 같은 sealed Capture를 등록하며 원본을 다시 생성하지 않는다.
- 기존 closure/SHA·정합·Project lock·원자적 rename·등록 검증을 유지한다. 파일 I/O 오류/데이터 오류/실제 제어 중지의 기존 구분과 명시 Stop도 유지한다.
- `align_measured`는 packet당 한 번 변환한 여섯 값을 재사용한다. arm interpolation·gripper hold와 기존 허용 시간은 같다.
- `validation.compare`에 lossless PNG 압축 선택값을 추가하고 **Capture Pair만 1**을 사용한다. 다른 호출의 기본값은 기존6이다. RGB·MAE/RMSE/edge IoU와 파일 종류는 같다. [Pillow PNG 압축 옵션](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#png)

100ms freshness, 200ms control deadline, heartbeat·identity·Mapping 검사 및 실제 오류 시 중지를 완화하지 않았다. 정지 후 자동 reactivation도 없다. 실패 cycle의 `last_attempt.timing_ms`에 heartbeat age/control gap/identity/feedback age/leader age/preflight를 남겨 이후 지연을 구분한다. 이는 관측된 local timing이며 실물 통신 원인의 자동 판정이 아니다.

## 저장 시간 비교

원본 `pickplace-colorblock/input/captures/real_sim_20261117_03/capture_001`의 **저장된 RGB·측정 q·Mapping·19개 feedback sample**을 읽어 독립 빈 Project에 Replay했다. 원본은 읽기만 했다. 새 촬영·새 Sim render·새 motor control은 없으며, 사용자 Project에 재등록하지 않았다. 생성물은 이번 진단 폴더에만 있다.

| 같은 저장 Replay | 작업 시작 코드 | 프로세스 분리·계산/PNG 수정 후 |
|---|---:|---:|
| 첫 Capture prepare+finish | 696.6ms | 451.0ms |
| 두 번째 Capture prepare+finish | 1,039.8ms | 781.1ms |

프로세스 분리만 적용한 중간 비교는 685.2/1,033.2ms로 wall time 개선이 크지 않았다. **분리의 목적은 제어 interpreter 보호**다. OpenCV thread1만으로는 625.3/1,027.7ms였으며 이것만으로 GIL stress RED를 해결할 수 없었다. 최종 시간 개선에는 반복 변환 제거·빠른 PNG encoding이 포함된다. 순차 소수 표본이며 호스트 부하/파일 cache의 영향을 받는다. 실제 사용자의 전체 ‘캡처 처리 중’ 시간, observation 안정 대기·renderer·USB·UI 전송 시간을 인증한 값이 아니다.

별도 PNG-only 비교는 compression6→1에서 두 Camera의 comparison 생성403.2→127.1ms였다. 여섯 PNG의 합계는1,681,408→2,023,285B로 약20.3% 늘었다. **해독한 RGB 배열과 수치 지표는 정확히 같았다.** 원본 Real/Sim RGB의 해상도·K·색을 낮추거나 손실 압축하지 않았다.

각 새 Snapshot 응답에 `save_timing_ms`(observation/model/encode_seal/closure_check/prepare/pair/finish/total)와 `capture_elapsed_s`를 기록한다. Store 시간과 세션의 전체 요청 경과시간을 구분한다.

## UI와 재실행

두 화면 모두 `최신 영상·관절 정합 확인 중 / 영상·측정값 저장 중 / 같은 자세의 Sim 영상 대기 중 / Capture 등록 중`과 경과시간을 표시한다. Capture 진행과 Teleop 활성은 별개다. 실제 비활성 상태이면 `Teleop 중지됨`을 함께 표시하며, 저장 완료를 Teleop 재활성화로 취급하지 않는다.

앞선 큰 Preview·`Side 크게/Wrist 크게/4분할`·더블클릭 전체 영상 기능은 유지했다. 사용자 스크린샷에는 이전4분할·작은 중앙 영상 배치가 남아 있었다. 실행 중인 Python UI가 읽은 widget 코드는 소스 파일 수정만으로 교체되지 않으므로 **현재 앱을 정상 종료 후 같은 실행법으로 다시 켜야 한다.** 사용자 UI/세션을 강제 종료하거나 제어 명령을 보내지 않았다.

실제 Qt widget/painter로 저장 Capture를 재생해 확인했다. 아래는 새 촬영/새 물리 렌더가 아니며 진행 시간0.3초도 UI 검사용 합성 label이다.

- [Real/Sim 큰 Side·저장 단계 표시](../../workbench_runs/diagnostics/capture_latency_followup_20261117_001/real_sim-save-progress.png)
- [Scene Prepare 저장 단계 표시](../../workbench_runs/diagnostics/capture_latency_followup_20261117_001/capture-save-progress.png)
- [저장은 진행하고 Teleop은 중지된 경우](../../workbench_runs/diagnostics/capture_latency_followup_20261117_001/real_sim-stopped-teleop.png)

Qt 검사는 backend 연결을 차단한 채 실제 image fill·전체 영상 확대·두 sensor/4분할 전환·진행 상태/Teleop 상태 구분을 검사한다. 저장 이미지 bytes와 입력 해상도는 바꾸지 않는다.

## RED/GREEN·회귀

| 검증 | 근거 |
|---|---|
| 두 Session의 동일 GIL→freshness 중지 RED | `red-isolation.xml/log`, 두 경우 모두 사용자 오류 문자열 재현 |
| 분리 후 해당 stress + 기존 저장 오류/Stop GREEN | `green-isolation.xml/log`, 12 passed |
| 반복 변환18회→샘플3회 RED | `red-alignment.xml/log`; 개선 후 기존 interpolation/정밀 보정 계약 통과 |
| 실제 Writer→Reader→Project 연속 Capture | `green-capture.xml/log`, 65 passed 묶음. Memory 장치, render만 합성 대역 |
| 상태/Qt 표시 RED→GREEN | `red-progress.xml/log` → `green-progress.xml/log`, 29 passed |
| PNG encoding/픽셀 계약 RED→GREEN | `red-png.xml/log` → `green-storage.xml/log`, 35 passed 묶음 |
| 실제 freshness 거부·실패 cycle 기록 | `red-deadline-diagnostic.xml/log` → `green-control.xml/log`, 33 passed 묶음 |
| 자식의 rename 이후 등록 실패·보존 경로·명시 재시도 | `red-rename-report.xml/log` → `green-final-capture.xml/log`, 22 passed 묶음 |

중간 묶음은 서로 겹치므로 합산하지 않는다. 제어가 실제로 늦으면 여전히 중지하는 검사와 종료 후 자식 PID 미잔존, 연속 두 Capture의 기존 Reader/SHA/등록·측정 q 보존을 포함한다. 사용자 장치·렌더러는 실행하지 않았다.

빠른 PNG 옵션의 Builder 소스 변경 때문에 보수적인 Stage1/2 cache proof가 먼저 거부한 RED도 보존했다. 변경이 Stage1/2 계산·입력과 무관함을 검토하고 **이번 exact validation.py SHA만** 기존 감사 목록에 추가했다. 이름만 같은 후속 변경은 거부하는 시험을 추가했으며 모델/설정/입력/원출력 SHA 검사는 유지한다. 기존 DA3/SAM 산출물이나 Cache를 다시 쓰지 않았다.

최종 코드에서 세 패키지 전체 회귀를 실행했고 **모두 실제 exit0**을 확인했다. 앞선2,324개 통과를 이번 수정의 결과로 대신하지 않는다.

| 최종 전체 회귀 | 결과 | Console 시간 |
|---|---:|---:|
| `real2sim_builder/tests` | 929 passed, 실패/오류/skip0 | 386.15s |
| `robot_learning_workbench/tests` | 1,267 passed, 실패/오류/skip0 | 585.71s |
| `scene_contract/tests` | 140 passed, 실패/오류/skip0 | 0.46s |
| 합계 | **2,336 passed, 실패0·오류0·skipped0** | 병렬 구간이 있어 시간을 합산하지 않음 |

기존 torchvision 경고4개와 JUnit `record_property` 경고1개가 있다. 이전 최종2,324개 대비12개 추가·기존 시험명 삭제0이며 skip/xfail로 우회하지 않았다. rename 이후 실패 경로 보완 전 Workbench1,265개 통과와 중단된 최초 Builder 전체 실행은 위 최종 수치와 구분한다.

명령은 기존 wrapper를 재사용했다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh <package>/tests \
  -q --tb=short --junitxml=<진단 XML>
```

근거는 `release-builder.xml/log`, `release-workbench.xml/log`, 해당 `*.exit.json` 및 `full-contract.xml/log`, `regression-summary.json`이다. 진단 runner는 wrapper의 실제 exit code를 남기는 시험용 도구이며 제품 실행 의존성이 아니다.

## 변경·보존과 한계

이번 제품 변경은 `robot/snapshots.py`, `robot/session.py`, `robot/real_sim.py`, `robot/capture.py`, `robot/pairs.py`, `robot/supervised.py`, `ui/view.py`, `ui/session_page.py`, `ui/real_sim_page.py`, Builder `validation.py`, `stage_artifacts.py`다. 신규 실행 Framework/Manager/환경은 없다. 테스트·문서의 정확한 시작 대비 목록은 최종 `change-inventory.json`에 기록한다.

작업 시작 대비 **18개 파일: 제품11개·테스트5개·문서2개**다. 기존 수정15개·신규3개이며 이전부터 있던 미커밋/미추적 상태와 이번 신규 여부는 구분한다. 변경 Python16개를 bytecode 없이 compile했고 `git diff --check`도 통과했다.

기존 Scene/Input/Capture/Candidate/Calibration/Asset/Export·Rig·Device 및 이전 보호 ledger의 **21,362개 파일 SHA/크기 변경0·누락0**, 조사한 Scene/Object/Rig/Device root 신규파일0을 대조했다. 이번 진단·임시 시험 Project는 이 보존 root 밖이다. 전체 SDK/모델/환경 디스크를 전수 대조했다는 뜻은 아니다. HEAD·브랜치·Git Index SHA도 시작과 같다. `preservation-before/after.json`, `git-preservation.json`, `compile-check.json`이 근거다.

모델 공용화·기존 Capture 삭제·UI/Device의 모델 재지정은 하지 않았다. 공용 모델 전환은 새로운 Snapshot 참조 규격과 Reader/UI/Device/엔진/Export 소비자 변경을 함께 해야 하며, `share_model`만 지우면 현재 Reader가 자료를 손상으로 거부한다. 권장 위치와 단계별 변경·완료 검사는 [공용 Robot 자원 전환 계획](robot-resource-migration-plan.md)에 있다.

실물 USB/OS scheduling/다른 프로그램 부하에서의 장시간 안정성·실제 Camera buffering·Isaac 물리는 **NOT_TESTED**다. 표준 Python 프로세스 분리가 hard realtime 보증은 아니다. 앞으로도 진짜 stale/identity/SDK 오류가 발생하면 자동 재시작하지 않고 실제 failed-cycle timing을 확인해야 한다. Capture 밖의 과거 heartbeat/control gap 오류까지 원인이 확정됐다고 보고하지 않는다.

Scene Prepare 중 검증된 Model/Precision으로 Teleop하는 `capture_session`이 이번 저장 분리 대상이다. 모델 미결합 관측 전용 `scene_capture`는 원래 Teleop 권한이 없으며 이번에 저장 구조를 바꾸지 않았다. Native Teleop HDF5 기록도 기존 `Recorder` 경계를 유지한다. 모든 종류의 기록 작업을 새 프로세스로 옮겼다는 뜻은 아니다.

설치·다운로드·AI Forward·사용자 Scene 재구성·URDF/Calibration/Asset 수정·실물 연결/모터 송신·Reset/Clean/Commit/Push/Merge는 하지 않았다. 신규 자원과 시험 산출물은 진단/임시 Project에 한정했다.
