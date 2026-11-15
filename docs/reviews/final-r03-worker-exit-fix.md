# Final Patch — NEW-03 R03 Worker 종료 상태

2026-11-15. `feat/simfoundry-style-reconstruction`, HEAD `97c029e195ab8587603fb3f240f2c1a6c0f91f52`. 기준은 [Phase 2B 최종 감사](phase2b-final-architecture-audit.md)의 NEW-03이다. 기존 Phase 1A–2B의 미커밋 변경을 기준선으로 보존하고 이 결함만 수정했다.

**COMPLETED — NEW-03 수정·RED/GREEN·실제 Child/Backend/Qt 통합·전체 회귀 exit0·사용자 원본 보존 대조를 완료했다.** 이 판정은 NEW-03의 범위이며 실제 사용자 Scene/Isaac/하드웨어 검증을 완료했다는 뜻이 아니다.

## 근본 원인과 수정 범위

기존 `run._monitor`는 `process.wait()`를 호출했지만, `run.json.status`가 이미 `completed/failed/cancelled`이면 아무 기록도 남기지 않았다. `RunStatus`와 UI에도 프로세스 종료 필드가 없어, 게시가 끝난 작업의 exit7과 정상 exit0을 구분할 수 없었다. terminal 결과를 보존하는 동작 자체가 결함인 것은 아니다. 실제 프로세스의 종료 사실을 별도로 기록하지 않은 것이 결함이다.

추가로 실제 단기 시작 Backend를 종료시킨 재현에서, 기존 daemon Monitor가 시작 프로세스와 함께 사라지는 것을 확인했다. 상태 필드만 추가한 중간 수정은 직접 Monitor 검사 13개를 통과했지만 이 경우에는 `exit_code=None`이었다. 따라서 기존 CLI의 숨겨진 `worker --monitor` 경계에서 실행 Child를 소유하고 기존 `_monitor`로 `wait()`하도록 연결했다. UI의 시작 Backend가 먼저 끝나도 이 소유 관계가 유지된다. 신규 Manager/서비스/Framework/제품 실행 모듈은 만들지 않았다.

시작 프로세스의 기존 daemon 경계는 Launcher 회수를 담당한다. 실제 execution PID와 일치하는 직접 Worker인 경우의 기존 종료 처리를 유지하며, Launcher의 종료를 실행 Worker의 종료로 기록하지 않는다. 실제 Worker의 signal 종료 코드와 Launcher의 shell용 반환값을 혼동하지 않는다.

## 상태 의미와 보존 계약

| 구분 | 의미와 현재 처리 |
|---|---|
| 작업 결과 | 기존 `run.json/result.json`의 `completed/failed/cancelled`, 작업 `error`, Episode/Attempt/Task 성공 여부를 유지한다. `completed`를 물리 Task 성공으로 해석하지 않는다. |
| 게시 결과 | 기존 Writer의 commit/close, Artifact 존재와 Dataset Catalog/Reader 검증으로 판단한다. 프로세스 exit0만으로 게시 성공을 만들지 않는다. |
| 프로세스 종료 | 실제 실행 Child의 `Popen.wait()` 반환값을 별도 `process_exit.json`에 원자적으로 기록한다. PID와 부모의 관측 시각 `observed_at_ns`를 포함한다. |
| 상태 조회 | `RunStatus.exit_code`와 `process_error`를 기본값 None으로 추가했다. 기존 필드·상태 문자열과 공개 함수 인자는 유지한다. CLI status에도 같은 값이 반환된다. |
| 비정상 종료 | nonzero 또는 음수 signal 코드는 `WORKER_EXIT_NONZERO` 진단이다. terminal 작업의 `error`와 별개이며 이미 게시된 파일을 삭제하거나 작업 상태를 failed로 덮어쓰지 않는다. |
| 미관측/Legacy | 종료 전 또는 기존 기록에 exit 파일이 없으면 `exit_code=null`. 0을 추측하거나 과거 파일을 변환하지 않는다. |
| 손상된 종료 기록 | 불완전 JSON/null/bool 코드는 `WORKER_EXIT_UNKNOWN`, `exit_code=null`이다. 정상 작업 결과를 실패 또는 정상 종료로 발명하지 않는다. |
| terminal 미게시 종료 | 기존 `failed/WORKER_EXITED` 처리를 유지하고 관측 종료 코드를 추가한다. command ACK나 부분 Writer를 성공 처리하지 않는다. |

terminal `run.json/result.json`은 종료 진단을 위해 다시 쓰지 않는다. 자동 재실행·Dataset 삭제·rollback·ACK 완료 발명은 없다. 기존 request/worker claim·명령·Preview·출력 경계를 유지한다.

Workflow UI는 `작업 completed`와 `Process exit 7 (비정상 종료)`를 함께 표시한다. 종료 전에는 `프로세스 종료 미확인`이다. `run_outcome.worker_finished`는 기존 terminal 작업 의미를 유지하고, 추가 `process_finished`는 관측된 exit의 존재를 뜻한다. Dataset 검증 상태 및 Task 성공률은 기존대로 별도로 표시한다.

Session UI도 terminal 작업을 한 번만 알린 후 새 Monitor의 종료 진단을 계속 조회한다. 늦은 nonzero는 기존 오류/로그 표시로 전달하고 terminal 결과를 다시 발행하지 않는다. Legacy 기록에는 새 Monitor 대기를 만들지 않는다.

## RED → GREEN과 Producer → Consumer

모든 신규 검사는 임시 폴더의 합성 입력과 유한 Child로 실행했다. 사용자 Dataset/Checkpoint/Scene을 입력으로 사용하거나 덮어쓰지 않았다. Qt는 기존 Runtime의 실제 `QApplication/WorkflowPage/SessionClient`를 offscreen으로 실행했으며, 사람의 화면 조작이나 GPU/Isaac 검증으로 표시하지 않는다.

| 실행 | 실제 결과 | 의미 |
|---|---|---|
| 수정 전 `monitor-red` | 13 failed, exit1, 1.74s | terminal exit0/7, failed3, cancelled0/9, 종료 전 조회, Legacy 3상태, nonterminal exit0/7, 실제 SIGTERM, Native Writer 보존 재현 |
| 수정 전 `integration-red` | 4 failed, exit1, 19.25s | 단기 시작 Backend, 실제 Producer→Qt/CLI 두 종료 코드, Legacy UI outcome |
| 상태 기록만 추가한 `monitor-green-owner-red` | 13 passed / 1 failed, exit1, 17.03s | 시작 Backend가 먼저 끝나면 기존 daemon Monitor가 종료 코드를 놓치는 별도 RED |
| `exit-green` | 17 passed, exit0, 6.31s | CLI Monitor 연결과 Workflow UI 수정 후 초기 통합 통과 |
| Session의 늦은 종료 `session-red` | 1 failed, exit1, 2.68s | terminal 전달 뒤 Session이 종료 진단 조회를 멈추던 경계 재현 |
| 첫 `release-focused` | 74 passed / 1 failed, exit1, 24.07s | 기존 실제 Worker SIGKILL 시험이 직접 Worker의 failed 전환 회귀를 검출. 기존 테스트를 수정하지 않고 Launcher 회수/실제 PID 경계를 수정 |
| 최종 `release-focused-verified` | **75 passed, exit0, 15.94s** | 신규 20개와 기존 R03/IPC/UI/Session 검사. skip/xfail 없음 |

서로 겹치는 실행이므로 통과 수를 합산하지 않는다. 중간 실패 로그도 보존한다.

실제 Producer는 기존 `execute(..., _runner=fixture)`를 사용해 Native Writer의 segment에 Episode 1개를 commit하고 close했다. 이는 실제 학습/Task Runner를 실행한 것이 아니라 기존 R03의 명시된 fixture 경계다. `StageResult`의 Artifact 존재·게시 Episode 개수 검사와 terminal 원자 게시를 거친 뒤, Child를 stdin gate에서 대기시키고 실제 exit0/7로 종료시켰다.

| 시점/Child | Backend | 실제 Qt 표시 | Native Consumer |
|---|---|---|---|
| terminal 게시 후 아직 실행 중 | completed, exit_code=null, task error=null | `작업 completed … 프로세스 종료 미확인 … Task 성공 0 / 실패 1` | 게시된 Episode 1개 |
| 정상 종료 | completed, exit_code=0, process_error=null | `Process exit 0 (정상 종료)` | Catalog/배열 읽기 통과 |
| 비정상 종료 | completed, exit_code=7, WORKER_EXIT_NONZERO | `Process exit 7 (비정상 종료)` | 동일 Episode·배열·모든 파일 SHA 유지 |

`process_exit.json.pid`와 `run.json.worker_identity.pid`, 실제 `Popen.returncode`, CLI status의 exit_code가 일치했다. Session은 terminal `completed`를 한 번만 전달했고 늦은 exit7 경고도 한 번만 전달했다. Task 성공=false는 두 실행에서 모두 유지됐다. 따라서 게시 성공/작업 종료/Task 성공/프로세스 정상 종료를 합치지 않는다.

단기 시작 Backend 검사는 gate를 열기 전에 시작 프로세스의 실제 exit0을 확인한다. 이후 실행 Worker의 기존 TRAIN_CONFIG_INVALID 결과와 실제 exit1이 보존됐고, `wait()`로 해당 실행 PID가 회수됐음을 확인했다. 실제 장치/학습 초기화 성공을 의미하지 않는다.

추가로 기존 실제 SIGKILL/미완료 command ACK/게시 Episode 보존, request 중복 시작 방지, input SHA 변경 거부, Stop/취소 재전달, UI 저장·재개, Session의 마지막 Snapshot 이벤트 drain 시험을 그대로 통과했다.

## 변경 파일

이번 시작 상태 대비 제품 기존 5개 수정·시험 2개 신규·이 문서 1개 신규다. 앞선 Phase의 변경/신규 파일과 구분한다.

- `robot_learning_workbench/src/robot_learning_workbench/run.py`: 종료 Record/상태 조회/Monitor 소유·PID 경계.
- `robot_learning_workbench/src/robot_learning_workbench/cli.py`: 기존 worker의 숨겨진 Monitor 실행 옵션.
- `robot_learning_workbench/src/robot_learning_workbench/ui/operations.py`: 작업 결과와 별도의 exit/process_finished 전달.
- `robot_learning_workbench/src/robot_learning_workbench/ui/workflow.py`: 작업 결과·미관측/정상/비정상 종료 병기.
- `robot_learning_workbench/src/robot_learning_workbench/ui/session_client.py`: terminal 후 늦은 종료 진단 전달.
- `robot_learning_workbench/tests/test_worker_exit_status.py`: 16개 신규 검사.
- `robot_learning_workbench/tests/test_worker_exit_integration.py`: 4개 신규 검사.
- `docs/reviews/final-r03-worker-exit-fix.md`: 이 보고서.

기존 테스트를 수정·삭제하거나 skip/xfail로 우회하지 않았다. 기존 Phase 1A–2B 코드·문서 및 감사 보고서를 이번 결함 수정으로 다시 작성하지 않는다.

## 전체 회귀와 사용자 원본 보존

집중 검증 뒤 소스를 고정하고 기존 `docs/evidence/builder/run_tests.sh`의 환경·실행 방식을 재사용했다. HF/XDG Cache 출력만 이번 임시 폴더로 분리한 복사본으로 `real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests` 전체를 실행했다. 저장소의 원래 Wrapper는 변경하지 않았다. 실제 명령·시작/종료 시각·반환 코드는 `release-full-result.json`에 있다.

- **2,151 passed / failure0 / error0 / skipped0, 실제 exit0**. Console 874.18초, JUnit 874.137초, Wrapper 전체 877.034초다. 전체 회귀를 중간에 끊거나 수집 결과로 대체하지 않았다.
- 기존 2,131개의 `(classname, name)` 목록을 직전 Phase 2B의 실제 JUnit과 Counter로 대조했다. **기존 2,131개 전부 보존·누락0, 신규20개**다. 기존 시험 파일의 수정/삭제0, skip/xfail 우회0이다.
- 경고5개는 기존 `record_property/xunit2` 경고1개와 torchvision video deprecation4개다. 경고를 오류나 테스트 누락으로 숨기지 않았으며 이번 범위에서 환경을 업그레이드하지 않았다.
- 전체 실행 동안 제품·시험 Python **386개 SHA 변경0**. 변경 Python **7개**의 bytecode 없는 compile과 `git diff --check`도 exit0이다. 수정 제품5개의 기존 공개 함수 인자를 AST로 대조했으며, RunStatus의 새 기본값 필드는 위 계약과 같이 추가했다.
- 보호 대상 **19,612개 → 19,612개, SHA/크기 변경0·누락0·신규0**. Scene/Input/Capture/Candidate, Dataset/Checkpoint/Calibration/Asset 및 기존 Runtime 경로의 사용자 원본을 보존했다.
- 실제 통합 Child **3개**(정상0·게시 후7·단기 시작 Backend 뒤 실패1)는 기록된 실행 PID가 `/proc`에 남아 있지 않았다. Qt exit/CLI status/실제 wait 반환값을 보존했다. 초기 보존 검사 보조 스크립트가 pytest의 잘린 임시 폴더 이름을 놓친 오류는 prefix를 수정해 재확인했다. 제품/시험 실패나 전체 회귀 재실행은 아니다.
- 브랜치와 HEAD는 시작과 동일하다. Index diff SHA는 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`로 불변이다. 이전 미커밋 구현을 보존하고 이번 8개 파일만 추가 변경했다. Commit/Push/Merge/Reset/Clean/Checkout/Stash를 하지 않았다.

근거 폴더: `/tmp/real2sim-final-r03-exit-20261115-ikvw40ex/`. 저장소의 실행 의존성이 아니다. 시작 코드 530개와 보호 대상 19,612개 파일을 SHA/크기 목록으로 보존했다. 보호 범위는 기존 `workbench_runs/{curation,policy,source,evaluation,annotation,capture,scenes,object_assets,dataset,datagen,runtime,calibration,scripts}`다. 홈 전체·외부 SDK·모델 디스크의 전수 SHA 대조라고 주장하지 않는다.

재검토 파일: `monitor-red.xml/log`, `integration-red.xml/log`, `monitor-green-owner-red.xml/log`, `session-red.xml/log`, `release-focused.xml/log`, `release-focused-verified.xml/log`, **`release-full.xml/log/result.json`**, `regression-comparison.json`, `tested-files.json`, `public-contract-check.json`, `compile-check.json`, `diff-check.json`, `change-inventory.json`, `final-patch-only.diff`, `preservation-after.json`, `index-head-preservation.json`, `process-cleanup.json`, `verification-summary.json`이다. 실제 Qt 표시 문자열과 CLI 응답은 `release-full-temp/test_actual_producer_exit_back0/ui-backend.json` 및 `...back1/ui-backend.json`에 있다. 로컬 임시 근거이므로 저장소만 받아서는 없을 수 있다.

## 잔여 위험과 실행 범위

1. Legacy 기록이나 관측자 자체의 강제 종료/호스트 전원 차단처럼 exit를 수집할 수 없는 경우에는 실제 코드를 복구할 근거가 없다. null/UNKNOWN을 유지한다. 이 패치는 내구성 있는 작업 결과를 정상 Interpreter 종료의 증거로 바꾸지 않는다.
2. 원자 기록 시 디스크 오류가 발생하면 exit 파일이 없을 수 있다. 코드 0으로 대체하지 않는다. post-exit 기록 자체의 물리적 디스크 장애·전원 차단을 실제로 주입하지 않았다.
3. Session이 terminal 뒤 Monitor의 미관측 종료를 기다리는 동안 상태 조회는 계속될 수 있다. 새 작업·UI 종료 시 기존 선택/수명 경계를 따른다. 무조건 강제 kill이나 새 복구 서비스를 도입하지 않았다.
4. 명시적으로 내부 `cli worker`를 Monitor 없이 직접 호출하면 수집자는 별도로 필요하다. 제품 `start`/UI 경로는 새 `--monitor` 경계를 사용한다. 기존 직접 execute/Legacy 결과에 exit0을 소급 부여하지 않는다.
5. Linux `/proc`·기존 Interpreter/Qt 환경에서 검증한다. 실제 Isaac shutdown, GPU Driver fault, 하드웨어 연결·장시간 학습/외부 SDK 종료까지 인증하는 검증은 아니다. Phase 2B의 다른 미검증 기능은 그대로다.

새 AI 모델/사용자 Scene E2E/실물 장치 실험·설치/다운로드·환경 변경·Reset/Clean/Checkout/Stash/Commit/Push/Merge를 수행하지 않는다. 전체 회귀는 기존 시험을 그대로 실행하며, 새 별도 학습/재구성 실험은 추가하지 않는다.
