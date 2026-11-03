# Workflow Pipeline 감사

2026-11-03. `workflow-restoration`, HEAD `7a97b49fff97700d6076936e8c773b164de14cea`와 현재 미커밋·미추적 코드를 검토했다. 최근 UI뿐 아니라 Source→Annotation→DataGen→Curation/LeRobot→Training/Resume→Sim/Offline 평가, Hub 및 Real 경계를 읽었다. 제품 코드는 수정하지 않았다. 실물 연결·원격 쓰기·새 학습·엔진 실행은 하지 않았다. 아래 재현은 Mock Qt/SDK 경계 또는 읽기 전용 입력 준비다.

후속 수정 상태: 아래 **시작 응답 중 중단 유실**, **기존 Run 재열기 복원 누락**, **YAML 엔진 동기화**, **DataGen 설정 해석**은 수정했다. 원래 재현 경로는 감사 이력으로 남긴다. Qt와 실제 파일 기반 cancel IPC에서 지연된 새 handle 대상 취소·이전 Run 격리·중복/재시도·창 종료·snapshot SHA/설정 복원을 확인했다. YAML 수정→화면 선택의 역방향 갱신과 양 엔진의 명시 설정 충돌 검사도 각각 RED→GREEN으로 확인했다. Hub 브랜치 항목은 남아 있다.

## Standards — 실행 상태와 단일 설정

### P1: 시작 응답 대기 중 중단 요청 유실

`ui/workflow.py:173`에서 시작 요청 후 busy 상태가 되지만 아직 handle이 없다. `cancel_run():206`은 prepare 취소 또는 기존 handle만 처리하여 이 구간의 중단을 기억하지 않는다. `job_finished():203`은 늦게 도착한 handle을 그대로 받아 실행 중으로 표시한다. 이전 terminal handle이 있으면 그 이전 Run으로 cancel을 보낸다. Mock Qt에서 시작 대기 중 중단→늦은 시작 성공 순서를 재현했다. R03 취소/ACK와 사용자 중단 의도 계약(`docs/interfaces.md`)에 맞게 새 handle 수신 즉시 취소하도록 시작 상태에 결합해야 한다.

### P2: YAML 엔진 변경과 Scene 선택이 서로 다른 상태 사용

`ui/pipeline_settings.py:50`의 YAML 변경은 라벨만 갱신한다. Scene 선택 `:92`는 별도 engine ComboBox 값을 읽는다. YAML을 `isaaclab`으로 수정한 뒤 Isaac Scene을 선택하면 이전 `mujoco` 값을 기준으로 거부하거나 MuJoCo 설정을 삽입한다. 적용/재로드 때만 ComboBox가 맞춰지므로 선택 순서에 따라 결과가 달라진다. Mock Qt에서 두 값의 불일치를 확인했다. `docs/pipeline-script-ui.md`의 단일 Recipe 버퍼 계약 위반이다.

### P2: 기존 Run 재열기 시 실행 설정 복원 누락

`ui/workflow.py:154`는 worker request를 읽지만 handle/context만 복원한다. 실행 방식·엔진·Preview Env 범위·Manual 버튼 표시·신호 목록을 복원하지 않는다. 새 창에서 manual Annotation 또는 다중 Env Run을 열면 필요한 Manual 패널이 숨겨지고 Env 0만 선택 가능하다. Mock Qt에서 빈 execution, 숨긴 패널, Env maximum 0을 확인했다. 기존 Manual/Preview/재열기 유지 요구를 충족하지 못한다.

## Spec — 선언한 실행 의미 보존

### P1: Hub 업로드 Revision 조회가 대상 브랜치를 지움

`ui/hub.py:42`는 다운로드뿐 아니라 업로드에서도 `inputs.revision`을 조회 SHA로 바꾼다. `learning/hub.py:57`은 그 값을 다시 조회하므로 main이 A→B로 바뀌어도 A 자체를 재조회하여 기존 parent 확인을 통과한다. Mock API에서 `revision=main,parent=A`는 HUB_CONFLICT, UI가 만든 `revision=A,parent=A`는 upload_folder 호출까지 진행함을 확인했다. 네트워크를 사용하지 않았고 서버가 SHA 대상을 받아들이는지는 시험하지 않았다. 업로드의 브랜치 이름을 유지하고 고정 SHA는 parent_commit에만 기록해야 한다.

### P2: DataGen의 명시 engine_config가 조용히 무시됨

MuJoCo `engines/mujoco/datagen.py:24`, Isaac `engines/isaac/datagen.py:21`은 설정 helper에 Annotation의 기록된 model_config를 넘긴다. helper는 이 값을 YAML의 engine_config보다 우선한다. UI에서 선택·수정한 JSON은 해시만 고정되고 실제 실행 설정에는 반영되지 않으며 충돌 오류도 없다. 기록된 모델 일치를 유지하려면 다른 설정 선언을 거부하거나 차이를 명시해야 한다. 임의 물리 설정으로 기존 Annotation의 identity를 우회하는 수정은 해법이 아니다.

후속 구현은 기존 `data/recording.py`의 공통 입력 계약에 `datagen_settings`를 두고 양 DataGen `load_inputs`에서 사용한다. Annotation 설정을 반환하며, 명시 JSON이 있으면 기존 MuJoCo/Isaac 설정 해석 후 비교하여 충돌 항목을 보고한다. UI의 실행 준비도 같은 `load_inputs`를 사용하므로 환경 생성이나 Dataset 출력 전에 거부한다. 별도 설정 없음·동등한 설정·마찰/질량/시간 간격 충돌·기록 누락·잘못된 관절 수를 임시 Native 입력으로 검사했다. 옛 parser가 `engine_config` 자체를 거부해야 한다던 시험은 실제 두 엔진 호출을 검사하는 시험으로 교체했다. 새 시뮬레이션·실물 동작 검증은 수행하지 않았다.

## 단계별 확인 범위와 제한

| 단계 | 현재 확인/남은 제한 |
|---|---|
| Source | 기존 전용 UI/Leader→Sim 경로 유지. 실물·새 Episode 수집은 이번 감사에서 수행하지 않음 |
| Annotation | 실제 보존 `source/demo_test`와 `scene-v9-task-objects`를 읽기 전용 prepare하여 runtime_ready 확인. 출력 폴더 생성 없음. 물리 Replay 성공 증명은 아님 |
| DataGen | Annotation pool/기존 Mimic·IK·Native 연결. 기록된 설정 계승·명시 설정 충돌 검사를 수정함. 완전한 Annotation Episode와 모델 일치 필요 |
| Curation/LeRobot | Episode 선별·Trim·별도 train/val Revision·변환 경로 유지. Trim된 Revision은 Annotation/DataGen에서 REPLAY_INITIAL_UNAVAILABLE로 거부하는 현재 제한이 있음 |
| 학습/Resume | 공식 JSON/Trainer/processor/Checkpoint 경계 유지. 이번에는 새 학습/Resume 실행을 하지 않음 |
| Sim/Offline 평가 | 공식 Policy·독립 Dataset 검사 경로 유지. 공유 Source/Mimic 조상까지 독립성을 증명하지 않음 |
| Hub | 다운로드 고정 Commit, 업로드 기존 Repo parent 검사. 위 브랜치 손실 결함과 별도로 새 빈 Repo 최초 업로드는 지원하지 않음 |
| Real | 현재 UI는 observe_only. 실제 자율 Policy Rollout은 미구현이며 이번 감사에서 모터를 구동하지 않음 |

## 시험 결과 해석

직전 전체 회귀 `/tmp/pipeline-ui-full.xml`은 1,156 passed / 68 failed / 28 errors였다. 실패·오류 96건 중 74건은 이전 Scene Manifest가 요구하는 파일 부재(56+18건)였다. 나머지에는 삭제/누락된 과거 Policy weights·processors, 구형 시험 기대값, 실제 설계 문제 등이 섞여 있다. 전부 최신 실행 오류이거나 전부 무해한 구형 시험이라고 해석하면 안 된다. 그 실행에 포함된 폐기된 Policy 라벨 UI 시험은 이후 입력 선택 방식의 시험으로 교체했다. 현재 관련 회귀 `/tmp/pipeline-ui-verified.xml` 60 passed는 위 전체 물리/학습 E2E 완료를 뜻하지 않는다.

수정 순서는 시작/중단 경합 → Hub 대상 브랜치 → YAML 엔진 상태 → Run 재열기 복원 → DataGen 설정 선언의 의미다. Standards 3건, Spec 2건이며 각 축의 최상위 문제는 각각 시작 취소 유실과 업로드 브랜치 손실이다.

2026-11-03 후속 검증: YAML 선택 동기화 6건과 DataGen 설정 14건, 총 20건 통과(`/tmp/pipeline-sync-datagen-cases.xml`). UI·R03·Recipe·Native·Source를 포함한 확대 검사는 173 passed / 1 failed(`/tmp/pipeline-sync-datagen-final.xml`)였으며, 실패는 직전 전체 결과에도 존재한 `test_excluded_minivla_policy_is_rejected_before_official_loader`다. 이 작업에서 해당 구형 모델 제외 정책을 다시 추가하거나 시험을 숨기지 않았다. 확대 검사 후 Isaac 각도 표현 정규화의 추가 관절 누락을 재현·수정했고 최종 20건에 포함했다. 전체 회귀의 기존 실패를 모두 해결했다는 뜻은 아니다.
