# Pipeline Script UI

2026-11-03. Source Demo의 사용자 흐름을 Annotation·Mimic/DataGen·모델 학습·Sim 평가·Offline Validation·Hub 다운로드/업로드·Real Evaluation에 적용한다. Scene Prepare·Real/Sim·Precision·Data Curation·Source Demo는 이번 교체 대상이 아니다.

단계별 입력 선택과 흰색 YAML 편집기는 하나의 Recipe 버퍼를 사용한다. 숫자·배치·실행 방식·Resume·출력 경로는 YAML에서만 편집한다. 기존 폼과 전용 동기화 코드는 제거한다. Script 불러오기는 재저장 없이 준비하고, 저장 및 적용은 새 파일 또는 선택 파일을 저장한 뒤 준비한다. 준비와 실제 실행은 분리한다.

Annotation/DataGen 입력은 기존 Dataset/Revision 선택기를 사용하고 기록된 Scene identity와 일치하는 등록 Package를 연결한다. 가장 최근 Scene을 묵시적으로 대신 사용하지 않는다. 학습은 기존 공식 LeRobot JSON을 별도 편집·저장하며 YAML은 그 경로를 참조한다. Hub Resolve/업로드 승인/Repo 생성은 기존 Backend를 사용하고 원격 쓰기는 사용자 실행에만 연결한다. Real Evaluation은 현재 observe_only 계약을 유지하며 실물 자율 Rollout으로 표시하지 않는다.

구현 순서: 공통 Script/입력 패널 → 기존 실행 화면 연결과 구형 폼 제거 → 공식 JSON/Hub 동작 → 회귀와 화면 확인. 입력·코드 identity, R03 ACK, 기존 Worker/Dataset/Training 계약을 변경하지 않는다. 설정 변경은 준비 결과와 업로드 승인을 무효화하며, 준비 취소 후 늦게 도착한 응답으로 실행하지 않는다.


현재 화면은 단계별 입력 버튼·YAML·Recipe 불러오기·저장 및 적용으로 구성한다. Script 경로는 `workbench_runs/scripts/<stage>/`이고 결과 Dataset/Policy/평가/Hub receipt 경로는 YAML `output.directory`가 결정한다. 새 Script 기본값은 파일을 생성하지 않는다. 파일 선택과 저장은 명시적인 버튼 동작이다. 저장 위치를 바꾸면 상대 입력/출력 경로를 절대 경로로 보존한다. 기존 Script를 로드한 뒤에는 재저장 없이 실행할 수 있다. YAML 수정 후에만 저장·적용이 필요하다.

| 단계 | 입력과 설정 |
|---|---|
| Annotation | Source/선별 Revision, 기록된 Scene, `pick_place.annotation`의 물체/목표, auto/manual |
| Mimic/DataGen | Annotation/선별 Revision, 동일 Scene, objects/placement, 성공 함수, 개수/시도/Resume |
| 학습 | 공식 LeRobot Dataset, 공식 Training JSON, scratch/finetune/resume, 선택 Policy/Checkpoint |
| Sim 평가 | 실행 Scene, Policy, objects/placement, 성공 판정, 언어 지시문/평가 횟수/시간 |
| Offline Validation | 공식 Dataset, Policy, batch_size/max_batches |
| Hub 다운로드/업로드 | YAML의 repo_id/repo_type/revision, 업로드 artifact/parent Commit/명시 승인 |
| Real Evaluation | Policy·Follower/Camera/Precision, observe_only, max_frames. 실물 자율 구동 없음 |

Scene 목록은 Project 등록 metadata를 읽고 선택 Package의 전체 무결성은 기존 prepare에서 검사한다. Annotation/DataGen의 Dataset 선택은 기록된 Scene identity와 정확히 일치하는 Package를 연결한다. 같은 엔진 Annotation은 기록된 모델 설정을 사용한다. 임의의 다른 최신 Revision으로 바꾸지 않는다. 다른 엔진이나 외부 Package를 사용하는 경우 YAML에 필요한 설정을 명시한다.

YAML에서 `engine` 또는 `inputs.scene`을 직접 수정해도 엔진·Scene 선택 표시가 즉시 따라간다. 이 표시 갱신은 YAML의 주석·입력 내용을 다시 작성하지 않는다. Scene의 상대 경로는 Script 위치를 기준으로 해석하고 정확한 등록 Revision을 표시한다. 목록에 없는 경로는 외부 Scene으로 표시하며 전체 경로를 툴팁에 남긴다. 잘못된 YAML이나 알 수 없는 엔진은 이전 엔진을 선택한 것처럼 남기지 않는다. 화면에서 Scene을 선택할 때는 현재 YAML에 반영된 엔진의 구성을 연결한다. 직접 수정한 Script의 실행은 계속 저장·적용 후에만 가능하다.

DataGen은 입력 Annotation의 `model_config`를 계승하므로 마찰·질량 등을 Script에 다시 적을 필요가 없다. 선택적인 `inputs.engine_config`가 있다면 두 엔진 모두 기존 설정 해석 함수를 사용해 실제 적용할 설정을 비교한다. 같은 값은 허용하며 `package_root`의 로컬 경로, 기본값 생략, 6축 각도의 목록/관절명 표현 차이는 실행 의미에 맞게 해석한다. 값이 다르면 입력 준비 및 실행의 공통 `load_inputs`에서 `INPUT_CONFLICT`로 차이가 있는 항목(예: `object_physics.cube_red.material.dynamic_friction`)을 알린다. 별도 설정을 조용히 무시하거나 Annotation의 물리를 덮어쓰지 않는다. 기록된 설정이 누락된 Annotation도 새 설정으로 대체하지 않는다. 물리 조건을 바꾸려면 그 조건으로 새 Source/Annotation을 준비한다.

학습 화면의 **공식 Training JSON 편집**은 설치 Registry의 실제 모델 기본 JSON을 만들거나 기존 JSON을 읽는다. 모델별 필드를 유지하고 현재 YAML의 Dataset·출력·Mode를 맞춘 새 JSON 파일을 저장한다. 원 JSON은 덮어쓰지 않으며 Dataset/출력 일치는 기존 Backend가 재검사한다. 학습 루프·optimizer·scheduler를 UI에 구현하지 않는다.

Hub Revision 조회는 명시한 Repo/Revision을 조회하여 고정 Commit을 YAML에 넣는다. 조회 중 Script가 바뀌면 그 결과를 덮어쓰지 않는다. Repo 생성은 별도 확인 후 수행한다. 업로드는 `confirm_upload: true`인 저장 Script와 실행 시 현재 artifact/Repo에 대한 확인이 모두 필요하다. UI를 열거나 Script를 불러오는 것만으로 원격 쓰기를 하지 않는다. 토큰 입력/표시/저장 UI를 추가하지 않았다.

기존 숫자·배치·실행 방식·Resume 폼, TrainingSettings, HubSettings와 전용 동기화 코드는 제거했다. 기존 영상·Preview Env·Manual Annotation 명령·R03 ACK·LossChart·Run 재열기·결과 확인은 유지한다. Manual Annotation 버튼은 manual 모드에서만 보인다. 이전 Run을 다시 시작하는 숨은 출력 변경 버튼은 없으며 Resume는 YAML로 명시한다.

시작·중단과 재열기의 후속 수정: 준비/시작 응답 대기 중 중단은 현재 요청에 기억한다. 시작 응답을 받은 뒤 새 Run에 동일한 cancel ID로 취소를 전달하고 실제 terminal 상태까지 기다린다. 창 종료도 같은 경로를 사용한다. 이전 Run의 handle은 새 시작 전에 분리하며, 중단 전달 실패 시 같은 ID로 사용자가 재시도할 수 있다. 취소 ACK만으로 Worker 종료를 표시하지 않는다.

**기존 Run 열기**는 새 Worker를 만들지 않는다. 저장된 `recipe.yaml`을 요청 SHA와 비교하고 엔진·실행 방식·Preview Env 범위·Manual 신호/버튼을 복원한다. 시작 준비 중이라 snapshot이 아직 없으면 요청에 결합된 원 Script를 같은 SHA일 때만 읽는다. 표시한 설정은 상대 경로를 보존한 미저장 초안이며 Run snapshot이나 현재 원 Script를 덮어쓰지 않는다. 재실행하려면 별도의 Script로 저장·적용해야 한다.

화면 확인은 빈 임시 Workspace에서 실제 Qt와 읽기 전용 Backend 조회로 수행했다. 1320×900·1920×1080의 8개 화면과 저장 버튼 노출을 확인했다. 이미지/수치 Preview를 실제 실행 결과로 채우지 않았다. 실제 Source 데이터의 Scene 조회도 읽기 전용으로 확인했다. 실물 연결·원격 쓰기는 실행하지 않았다. 전체 회귀의 기존 실패와 오류를 해결한 작업으로 주장하지 않는다.
