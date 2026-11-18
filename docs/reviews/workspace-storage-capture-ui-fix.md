# Workspace 정리·Capture 연속성·영상 UI 개선

2026-11-17. `feat/simfoundry-style-reconstruction`, 시작 HEAD `8e02b1ae023a856694a40b947881f76b66410624`. 기존 미커밋 구현 위에서 이번 요청 범위를 수정했다. 파일 생성·소유권 조사는 [폴더 수명 보고서](workspace-storage-lifecycle-audit.md), 자원 선택 경계는 [공유 자원 조사](shared-resource-reference-audit.md)를 따른다.

## 반영한 동작

- Scene Prepare는 Side/Wrist 영상을 크게 표시하고 촬영 목록을 `촬영 기록` 버튼으로 펼친다. Real/Sim은 `Side 크게 / Wrist 크게 / 4분할`을 선택하며 촬영 목록·Refit Memo는 `촬영 기록 / Scene 재정합`으로 펼친다.
- Live 영상은 원 비율을 유지한 화면 채움 확대다. 화면 비율이 다르면 가장자리 일부가 잘린다. **더블클릭하면 원본 전체 프레임을 큰 창으로 확인**한다. 원본 RGB·Capture 해상도·Camera K를 바꾸는 처리가 아니다.
- 화면 모드 전환·확대는 연결을 다시 만들거나 Teleop 명령을 보내지 않는다. 확대 창에서도 Qt 이벤트 루프가 유지돼 기존 프레임 갱신·세션 polling을 계속 처리한다.
- 제어 주기에서 전체 USB/Camera 목록을 반복 열거하지 않고 연결된 포트의 fresh USB 식별 정보를 확인한다. 최초 장치 선택의 중복 식별 검사, serial/VID/PID 검증, 기존 제어 기한·heartbeat·명시 Stop은 유지한다.
- Capture의 일반 파일 I/O 오류는 해당 저장을 실패로 표시하되, 정상 작동 중인 Teleop의 기존 활성화를 취소하지 않는다. 장치/정합 등 다른 오류는 기존 중지 경계를 유지한다. 안전 중지를 자동 재시작하는 코드는 없다.
- Capture JSON을 느린 YAML parser로 반복 해석하는 경로를 줄이고, Pair metadata 변경이 없는 일반 Capture의 manifest는 불필요하게 다시 쓰지 않는다. SHA·모델 의존성·측정값·등록 검증은 유지한다.
- 새 Export의 동일한 기본 authored 설정은 Project 안의 `configuration/export-authored-preview.json` 하나를 재사용한다. 명시 사용자 설정은 그대로 사용한다. 기존 공유 설정이 바뀌었으면 덮어쓰지 않고 거부하고, 등록 실패 때에는 해당 작업이 새로 만든 자동 설정만 제거한다.
- UI를 여는 것만으로 사용하지 않은 Pipeline 출력 폴더를 모두 생성하던 동작을 제거했다. 각 producer가 실제 저장할 때 기존 출력 경로를 생성한다.

## 느린 저장과 Teleop 중지의 근거

최근 실제 `real_sim_20261116_03/session-report.json`은 저장 예외가 아니라 `Control deadline exceeded before Goal transmission`으로 끝났다. 실패 시 follower/leader read는 각각 약1.293/1.185ms였지만, 직전 성공과 다음 feedback 사이에는 약1,665.5ms가 있었다. 당시 세부 구간 timestamp가 없어 **과거 지연의 단일 원인은 확정하지 않았다.**

수정 전 `_check_identity → resolve_serial → discover`는 제어 주기에서 전체 직렬 포트와 Camera 경로를 열거했고, target encoding에서도 다시 호출될 수 있었다. 설치된 PySerial3.5 소스를 확인했으며, Linux `SysFS(selected_port)`는 통신 포트를 열지 않고 해당 tty의 OS 식별 정보만 읽는다. 최초 선택에는 전체 목록의 유일성 검사를 유지하고 연결 중 검사를 이 경계로 제한했다. Linux/PySerial API가 없거나 메타데이터를 읽을 수 없으면 확인 실패로 중지한다. TTL Cache로 장치 변경을 숨기지 않는다. [선택/연결 검증](../../robot_learning_workbench/src/robot_learning_workbench/robot/registration.py), [제어 소비자](../../robot_learning_workbench/src/robot_learning_workbench/robot/devices.py)

실제 OS metadata만 60회 읽은 조사에서는 전체34포트 검색 median3.419ms/P953.878ms, 선택 포트 검사 median0.165ms/P950.180ms였다. serial/VID/PID 결과는 일치했다. 이는 조회 당시 측정이며 과거 200ms 초과를 단독 설명하는 결과는 아니다. 별도 deterministic test에서 전체 검색에만 가상220ms 지연을 주면 원래 `Teleoperation.tick`이 사용자 기록과 동일한 기한 초과로 실패했고, 선택 포트 경계로 수정한 뒤 통과했다. 실제 모터 송신은 Memory 장치다.

또 두 Session의 저장 결과 handler가 `OSError`까지 무조건 `control.stop()`으로 처리하는 독립 결함을 RED로 재현했다. 정상 저장 Future를 기다리는 동안 Teleop을 계속하는 구조는 이미 있었으며, 이를 새로 만든 것처럼 보고하지 않는다. 이번 수정은 일반 파일 I/O 실패와 장치·무결성 실패의 중지 의미를 구분한다. [Scene Prepare 결과 처리](../../robot_learning_workbench/src/robot_learning_workbench/robot/session.py), [Real/Sim 결과 처리](../../robot_learning_workbench/src/robot_learning_workbench/robot/real_sim.py)

### 합성 저장 비교

같은 Memory SDK·16.1MB/14파일 모델 closure·빈 임시 Project·합성640×480 RGB로 Capture2회를 측정했다. cProfile·1ms observer thread가 있는 동일 harness 조건이며 실제 사용자 Scene/Pair 렌더를 실행한 수치가 아니다.

| Capture | 수정 전 Prepare+Finish | 수정 후 Prepare+Finish |
|---|---:|---:|
| 1 | 896.94ms | 207.10ms |
| 2 | 990.44ms | 298.25ms |

수정 전 프로파일에서 YAML 읽기26회에 누적 약1,368ms가 사용됐다. JSON으로 기록한 `.yaml` manifest를 JSON으로 먼저 읽고, 일반 YAML block/flow는 기존 safe parser로 처리한다. 이 조건의 observer 최대 간격은17.1ms→8.53ms였으며, 이 측정은 GIL만 분리한 값이 아니고 수정 전에도 200ms stall을 재현하지는 못했다. 원본 Capture의 변경을 숨기기 위해 SHA 검사를 생략하거나 기존 모델 파일을 다시 쓰지 않았다.

## 실제 Qt 화면 검증

원본은 `pickplace-colorblock/input/captures/real_sim_20261116_03/capture_002`의 저장된 Side/Wrist·Sim PNG다. **기존 Capture를 Qt에서 재생한 화면**이며 새 센서 촬영·새 시뮬레이션 렌더가 아니다. Backend catalog는 harness에서 차단했고 실제 Qt widget/layout/painter를 offscreen platform에서 구동했다. Before는 작업 시작에 복사한 UI 소스를 별도 프로세스에 로드했으며 제품 파일을 Reset/Checkout하지 않았다.

1320×900 동일 창에서 Scene Prepare의 각 표시 영역은488×235→488×335, Real/Sim은 4분할 각631×약109에서 기본 Side 비교631×420으로 커졌다. 면적 수치는 위 재생 화면 조건이며 상태 label·창 크기에 따라 달라진다. 4분할도 계속 선택할 수 있다.

| 화면 | Before | After |
|---|---|---|
| Scene Prepare | [기존 화면](../../workbench_runs/diagnostics/workspace_storage_capture_ui_20261117_001/before-capture.png) | [큰 영상·접힌 촬영 기록](../../workbench_runs/diagnostics/workspace_storage_capture_ui_20261117_001/after-capture.png) |
| Real/Sim | [기존 작은 4분할](../../workbench_runs/diagnostics/workspace_storage_capture_ui_20261117_001/before-real_sim.png) | [Side 크게](../../workbench_runs/diagnostics/workspace_storage_capture_ui_20261117_001/after-real_sim.png) |
| 추가 모드 | — | [Wrist 크게](../../workbench_runs/diagnostics/workspace_storage_capture_ui_20261117_001/after-real_sim-wrist.png), [4분할](../../workbench_runs/diagnostics/workspace_storage_capture_ui_20261117_001/after-real_sim-four.png) |

Qt 테스트는 화면 가장자리의 실제 pixel을 검사해 letterbox 제거를 확인하고, 원본 pixmap 크기 불변·더블클릭 확대·모드 전환·촬영 기록 펼침·두 창 크기의 기존 조작을 검사했다. 공통 `CameraView`는 기존 Episode/Calibration·기록 썸네일용 동작을 유지하고, 두 Live 화면만 같은 파일의 `LiveCameraView`를 사용한다. OpenGL Object Viewer는 이번에 수정하지 않았다.

## 삭제한 부산물과 남긴 자료

사용자의 정리 지시에 따라 현재 코드·저장 metadata의 실행 참조를 조사한 뒤 다음만 삭제했다.

| 분류 | 처리 |
|---|---|
| 날짜별 개발 실험20개 | `scene_*`, `sfm_comparison_20261108`, `real_codex_flow_20261106` 등. 목록·용량·역할은 [수명 조사 표](workspace-storage-lifecycle-audit.md#과거-실험-폴더-목록)에 있음 |
| 오래된 임시 Preview | `.review`의 2026-11-02 하위 폴더5개. `.review` 전체나 현재 UI의 새 namespace를 삭제하지 않음 |
| 미사용 자동 설정 | `pickplace-colorblock/configuration`의 `export-<hash>-<engine>.json`18개. 내용은 모두 동일 authored wrapper이며 Project/저장 Recipe의 참조가 없음을 재확인 |
| 미사용 빈 출력 폴더 | `annotation`, `datagen`, `dataset`, `policy`, `evaluation`5개를 `rmdir`로 제거. 내용이 있었다면 제거하지 않는 방식 |

20개 실험·Preview·설정 삭제의 합계는 **5,941개 파일 / 2,215,835,191B(약2.06GiB 논리 용량)**다. 삭제 직전/직후 여유 공간 차이는 약2.07GiB였으나 동시 디스크 사용·하드링크 영향이 있어 확정 회수량과 구분한다. 과거 실험의 symlink2개는 링크만 제거하고 대상 `docs`·Workspace를 따라 삭제하지 않았다. 최초 정리 검사는 이 링크를 발견해 삭제 전에 멈췄으며, 대상을 기록하고 비추적 삭제 경계를 보완한 뒤 실행했다.

삭제 전 exact path·bytes·SHA·inode·이유를 `deletion-manifest.json`으로 남겼다. `deletion-result.json`과 `empty-folders-removed.json`은 실행 결과다. 동일 Workspace 안에 원시 파일 전체를 다시 복제해 보관하지 않았다. 과거 보고서의 해당 로컬 실험 링크와 `fit_provenance.source_context`는 역사적 출처로 남으며, **그 원시 자료는 이제 로컬에서 열 수 없다.** 이를 현재 실행 입력처럼 재사용하거나 삭제 전 수치를 새 결과로 바꾸지 않는다.

보존 대상은 현재 세 Scene Project의 입력·Capture·Candidate·발행 Package, Object Library/Rig, Device/Runtime, Calibration·Dataset과 `.assets`다. `runtime/qt`는 UI Python 환경이므로 부산물이 아니며, `.assets`는 소유권이 있는 shared 파일 pool이다. `auto-version/scratch`의 큰 Evidence·Cache와 기존 Export는 현재 기록/재개 참조가 있어 삭제하지 않았다. 과거 diagnostics도 문서 근거·모델/소스/보존 기록이 있어 일괄 삭제하지 않았다. 따라서 **모든 `scratch`나 과거 기록을 필요 없는 것으로 취급한 정리는 아니다.**

정리 후 기존 Reader로 Project3개·등록 Package9개·Library Version11개·`so101_with_camera` Rig를 확인했다. 첫 Reader 조사에서 USD library bootstrap을 빠뜨린 실패는 로그에 보존했고, 기존 USD source/bin 경로로 다시 확인해 통과했다. Kit/엔진/장치 초기화는 하지 않았다.

## 앞으로의 폴더 관리 기준

사용자 화면의 Scene 내부 항목은 아래처럼 나뉜다.

| 항목 | 의미 |
|---|---|
| `project.yaml` | Scene ID·장치/Rig 선택·등록 실행 Package 목록 |
| `input/` | 원본 Photo/Reference/Memo·실측 Capture와 Evidence |
| `working/` | Current Scene·현재 상태·lock·최근 처리 보고서 |
| `scratch/agent/<Candidate>/` | 미채택 제안·Reconstruction attempt·제작 근거·재개 Cache |
| `exports/<Revision>/` | 배포/재현용 닫힌 USD/MJCF/Native Package |
| `configuration/` | 해당 Project가 선택한 엔진 실행 설정 |
| `history.jsonl` | Scene 작업·채택 이력 |

Capture는 이미 `Session/capture_NNN/`의 두 소유 단계로 저장되고, 각 Capture root에 이미지·state·metadata가 있다. UUID별 `shots/...`를 매번 추가하지 않는다. 모델은 하드링크로 공유하고, Evidence 등록은 Project 내부 경로를 그대로 사용해 두 번째 전체 복사를 만들지 않는다. R03의 작은 command/ack/exit 기록은 중복 실행 방어와 상태 조회에 사용된다. 영상 Preview는 두 slot을 재사용한다.

가장 긴21단계 경로는 과거 Export closure를 다시 Export의 원본으로 포장한 영향이 컸다. **새 출력은 공용 Rig/Library의 정돈된 closure에서 시작**하는 것이 적절하다. 이미 발행한 Package를 폴더 이름만 평탄화하면 상대 참조·SHA·보정 identity가 깨지므로 이번에 옮기지 않았다. 개발 실험은 앞으로 `diagnostics/<작업>/` 아래에 한정하고, 임시 엔진 파생물은 producer 종료 시 정리하며, Evidence/Checkpoint/완료 manifest의 참조는 보존하는 순서를 권한다. 새 Manager/DB·자동 광역 삭제 기능을 추가하지 않았다.

추가 개선 후보는 Pair마다 저장하는 `comparison/<side|wrist>/`의 overlay/difference/side-by-side PNG다. 원본 Real/Sim RGB에서 다시 계산할 수 있으므로, 앞으로는 수치·원본을 고정하고 결과 창에서 메모리로 생성하면 쓰기와 하위 폴더를 줄일 수 있다. 현재는 이 PNG까지 Capture manifest가 해시하므로 **기존 Capture에서 삭제하면 무결성이 깨진다.** 이번에는 기존 계약을 유지하고, 향후 producer와 결과 창을 함께 바꿀 항목으로 분리했다. 연결별 Recipe/R03 기록도 촬영 이미지와 중복되지 않는 작은 실행 기록이며, 실패·미완료 저장 복구를 위해 이름만 보고 제거하지 않았다.

## 검증과 변경 범위

RED는 실제 Qt letterbox/확대 부재, 미사용 출력 폴더 생성, Capture I/O 실패에 의한 Teleop 중지, 제어 중 전체 장치 열거, JSON 재파싱·manifest 재작성, 동일 자동 설정 중복·실패 잔여를 각각 재현했다. 정상 pending save 중 Teleop 진행, 명시 Stop, DeviceError 중지, 실제 SnapshotStore 파일 보존은 별도 guard다.

전체 회귀에서 기존 Project Mock의 `info` 누락1개와 Stage7 fixture의 Stage3 입력 누락8개를 발견했다. 작업 시작 소스를 별도 임시 트리에서 복원한 비교에서도 **9개가 같은 오류로 실패**했고, 제품의 요구 검사를 우회하지 않고 fixture를 현재 Project/Stage 입력 계약에 맞췄다. 테스트 이름·검증 assertion은 제거하지 않았다.

Capture reader/Export 등록의 변경은 기존 Stage1/2 cache의 전역 구현 SHA에도 영향을 준다. 기존 감사 재사용 경계를 유지하도록 **이번에 검토한 두 파일의 exact SHA만** 추가로 인정했다. DA3/Stage1/2 Worker·입력·설정·모델·출력 closure 검사와 원 Artifact provenance/bytes는 유지하며, 알려지지 않은 후속 파일 변경은 계속 재사용을 거부한다. 정상 재사용과 unknown dependency 변조 거부를 함께 검사했다. 기존 저장 Cache 파일을 재작성하거나 모델을 다시 실행하지 않았다.

최종 소스를 고정한 뒤 세 패키지의 **전체 테스트를 각각 실행하고 모두 실제 exit0**을 확인했다. 테스트·AI 모델·하드웨어 실행을 구분하며, 중간 집중 묶음은 겹치므로 합산하지 않는다.

| 최종 전체 회귀 | 결과 | Console 시간 |
|---|---:|---:|
| `real2sim_builder/tests` | 927 passed, 실패/오류/skip0 | 435.11s |
| `scene_contract/tests` | 140 passed, 실패/오류/skip0 | 0.48s |
| `robot_learning_workbench/tests` | 1,257 passed, 실패/오류/skip0 | 569.15s |
| 합계 | **2,324 passed, 실패0·오류0·skipped0** | 병렬 실행이므로 위 시간을 전체 경과시간으로 합산하지 않음 |

기존 torchvision 경고4개와 JUnit `record_property` 경고1개가 있었다. 최초 중간 전체 실행의11 failed/2,311 passed와 마지막 결과를 구분한다. 중간 실패는 위의 기존 fixture9개와 이번 구현 SHA 변경으로 재사용 proof를 거부한2개였으며 모두 집중 RED/GREEN을 거쳐 해결했다. 시험을 삭제하거나 skip/xfail로 우회하지 않았다.

실행 명령은 각 패키지 경로에 대해 다음과 같으며, 원본 로그는 `final-builder`, `final-contract`, `final-workbench`의 XML/log다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash docs/evidence/builder/run_tests.sh <package>/tests \
  -q --tb=short --junitxml=<해당 진단 XML>
```

보존 기준21,351개 파일 중 삭제를 승인한 **미참조 자동 설정18개를 제외한21,333개는 SHA/크기 변경0·누락0·신규0**이다. 현재 Scene/Input/Capture/Candidate/Asset/Export·Rig·Calibration·Dataset·Runtime은 그대로다. 기존 다른 소스/문서의 변경0, HEAD·브랜치·Git Index 불변, 이번 변경 Python21개 bytecode 없는 compile과 `git diff --check`도 확인했다.

이번 작업 시작 상태 대비 **23개 파일: 기존 수정16개·신규7개**다. 이전부터 있던 미커밋/미추적 파일의 Git 상태와 이번 작업의 신규 여부는 다르다.

| 범위 | 파일 |
|---|---|
| Builder 제품3개 | `files.py`, `registration.py`, `stage_artifacts.py` |
| Workbench 제품9개 | `robot/devices.py`, `robot/registration.py`, `robot/session.py`, `robot/real_sim.py`, `robot/snapshots.py`, `ui/app.py`, `ui/view.py`, `ui/session_page.py`, `ui/real_sim_page.py` |
| 기존 테스트4개 | `test_local_runtime_validation.py`, `test_prepared_image_handoff.py`, `test_stage_cache_compatibility.py`, `test_capture_session_ui.py` |
| 신규 테스트5개 | `test_export_settings_reuse.py`, `test_capture_save_continuity.py`, `test_capture_storage_performance.py`, `test_control_identity_latency.py`, `test_live_camera_layout.py` |
| 신규 문서2개 | 이 보고서와 `workspace-storage-lifecycle-audit.md` |

검증 자료는 Git 제외 `workbench_runs/diagnostics/workspace_storage_capture_ui_20261117_001/`의 `change-inventory.json`, `task-only.patch`, `deletion-manifest.json`, `deletion-result.json`, `empty-folders-removed.json`, `preserved-readers.json`, `preservation-before.json`, `preservation-after.json`, `compile-check.json`, `document-check.json`, `regression-summary.json`, `completion-check.json`과 RED/GREEN·GUI·지연 측정 기록이다. 제품 코드는 이 진단 폴더를 import하지 않는다.

### 남은 실물 검증과 적용

현재 실행 중인 UI 프로세스를 강제로 종료하거나 사용자의 연결을 재시작하지 않았다. 수정 UI는 앱을 정상 종료 후 다시 켰을 때 적용된다. 실제 장치의 USB/CPU/디스크/렌더 부하에서 장시간 Teleop·연속 Capture 시간과 새 오류 여부는 **NOT_TESTED**다. 이번 결과는 합성 제어/저장·기존 파일 Reader·Qt 화면 검증이며, 실제 로봇이 다시 멈추지 않는다는 보증은 아니다. 제어 기한을 늘리거나 안전 중지를 자동 해제하지 않았다.

설치·다운로드·AI Forward·사용자 사진 Reconstruction·Isaac/로봇 구동·URDF/실측/Calibration 변경·Commit/Push/Merge는 수행하지 않았다.
