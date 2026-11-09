# Auto Reconstruction — 로그인·사용량·중단·재개

2026-11-07. Scene Prepare의 기존 **Auto Reconstruction** 버튼으로 여는 창이다. Scene Prepare의 입력·저장·Capture UI는 변경하지 않았다. 이전 다섯 탭과 수동 물체/Mask/USDA/환경 편집 UI 및 그 이벤트 코드는 제거했다. 고급 모드는 없다.

## 사용법

1. Scene Prepare에서 Project의 사진·Capture·자유 Scene Memo를 저장한다.
2. Auto Reconstruction에서 **로그인**한다. 공식 Codex CLI가 브라우저 인증을 진행하며 이 창은 비밀번호나 토큰을 입력받지 않는다.
3. 공식 모델 목록과 해당 모델의 추론 강도를 선택한다. 목록 조회가 불가능하면 모델 ID를 직접 입력할 수 있다. 이때 지원 여부를 확인할 수 없는 추론 강도를 만들어 표시하지 않고 CLI 기본값을 사용한다. 목록이 있는 경우 지원되지 않는 모델/강도는 실행 전에 거부한다.
4. **생성 시작 / 이어서 실행**을 누른다. 저장된 `input/reconstruction.yaml`의 SAM 및 선택한 Geometry Backend 환경과 입력을 사용하고, 구조 수정 도중에는 해당 Candidate의 `review-config.yaml`을 사용한다. 필수 실행 파일·모델 경로가 없으면 누락 항목을 안내한다. 다운로드나 설치 경로 추측은 없다.
5. **중단**은 기존 Project control을 사용한다. worker가 완료된 자료를 보존하고 소유한 하위 프로세스를 정리할 때까지 기다린다. 창을 닫아도 실행 중이면 같은 종료 절차를 따른다.
6. 인증/사용량 문제라면 종료 후 **계정 전환**으로 공식 logout→login을 수행하고 같은 Candidate를 이어서 실행한다. 실행 중 계정 교체는 막는다.

`VISUAL_DRAFT_REVIEWED`는 시각 초안 검토 완료다. 물리 검증·실측 정확도·Task 성공을 의미하지 않는다. 부족한 입력과 정합 예산 소진은 완료로 바꾸지 않는다. 비교 RGB/overlay/difference와 반복 결과는 기존 Candidate 폴더에 자동 보존한다.

## 인증과 사용량

기본 Builder 인증 위치는 `~/.local/share/real2sim-builder/codex`다. 기존 VS Code/CLI의 `CODEX_HOME`은 자동으로 상속하지 않고 인증 파일도 복사하지 않는다. 개발자가 기존 로그인을 명시적으로 사용해야 할 때만 실행 환경의 `REAL2SIM_CODEX_HOME`으로 선택한다. 로그인·상태·App Server·실제 exec가 모두 같은 위치를 사용한다. 인증 폴더는 Project 밖이어야 한다.

계정 및 사용량은 공식 App Server stdio JSON-RPC의 `initialize`, `account/read`, `account/rateLimits/read`를 사용한다. `account/rateLimits/updated`가 조회 중 도착하면 최신 snapshot을 다시 읽는다. 모델 목록은 `model/list`를 사용한다. 설치 CLI의 version/help와 `login status`도 확인한다. 사용량 조회에는 추론 요청을 보내지 않는다.

`usedPercent`는 사용한 비율이다. 표시값은 `100 - usedPercent`이며 `windowDurationMins`가 300/10080일 때에만 5시간/주간으로 표시한다. 다른 기간은 실제 분으로 표시한다. `resetsAt`은 OS의 현지 시간 및 남은 시간으로 보여준다. 복수 bucket은 합산하지 않는다. 서버가 `normalModelSlug`를 제공하면 모델을 표시하고, 없으면 **적용 모델 미확인**으로 표시한다. 계정이 지원한다고 임의로 추정하지 않는다.

Qt의 별도 QThread에서 창 열기·실행 전·계정 전환 후·worker 완료 후·수동 새로고침·실행 중 60초 간격으로 조회한다. 계정 전환 시작과 조회 오류 시 이전 사용량을 지우고 늦게 도착한 이전 계정 응답을 버린다. 계정 이메일/플랜은 공식 응답에 있는 경우에만 메모리에 표시하며 Project나 실행 로그에 쓰지 않는다.

## 실행·재개 계약

`ui_reconstruction.ReconstructionDialog` → 기존 `reconstruct/refit-pairs --run-modeling` → `automation.reconstruct` → `authoring.run_codex_modeling` 흐름이다. 새 Pipeline/Agent 실행기를 만들지 않았다. 선택한 모델은 분석·USDA 제작·비교 판단의 모든 새 Codex 호출에 `--model`로 전달하고, 공식 목록에서 확인된 추론 강도는 `-c model_reasoning_effort=...`로 전달한다. `--ignore-user-config`를 유지한다. 계정 전환은 Scene identity나 Asset cache key를 바꾸지 않는다.

기존 Project lock과 최선 checkpoint를 유지하고 `reconstruction.json.resume`에 Candidate·입력 signature·완료/미완료 단계·재개 가능 상태를 기록한다. 성공한 Codex 호출/검토 횟수를 계승해 중단으로 전체 호출 예산을 무한히 초기화하지 않는다. 분석은 메모·Evidence SHA와 저장 응답 SHA를 확인한다. 등록된 USDA는 기존 fingerprint/Manifest 검증, SAM/DA3는 기존 cache 검증을 통과해야 재사용한다. 새 사진이 추가되었다는 이유만으로 유효한 USDA를 재생성하지 않는다.

검토 호출에서 실패한 경우 입력·설정·최선 checkpoint가 일치하면 저장된 비교 결과로 검토부터 이어간다. 정합 도중 중단된 경우 기존 수치 solver의 최선 Scene에서 재시작한다. 중단된 ephemeral Codex 세션이나 optimizer의 중간 메모리를 복원한다고 가정하지 않는다. 부분 손상된 응답·자산·checkpoint를 완료로 사용하지 않는다.

공식 구조화 오류 코드가 있을 때 사용량/인증/모델/네트워크 실패를 구분한다. CLI가 텍스트 오류만 제공한 경우 일반 실행 실패로 남기며 `429`나 `quota`라는 단어만으로 사용량 소진이라고 단정하지 않는다. 로그인 상태와 모델 catalog는 재개 후 새 호출 직전에 다시 검사한다.

## Sandbox와 기록

선택 모델·추론 강도·CLI version은 `modeling/codex/<job>/runtime.json`에 기록한다. Schema·Guide SHA·선별된 입력/출력 기록은 유지한다. raw CLI stdout/stderr는 Project에 남기지 않고 익명 임시 파일에서 구조화 오류를 검사한 뒤 폐기한다. `codex.log`에는 종료 코드와 실행 선택값만 기록한다.

공식 permissions profile로 임시 모델링 작업 폴더 쓰기·최소 시스템/설치 CLI 읽기·도구 네트워크 차단을 지정한다. 인증 파일은 읽기 금지다. CLI가 자체 sandbox helper를 실행하는 `CODEX_HOME/tmp`만 읽기 허용하며 인증 파일은 복사하지 않는다. `--ephemeral`, 출력 Schema, 가이드 SHA, 기존 Blender bwrap Sandbox를 유지한다. CLI stdin은 닫아 Qt worker의 입력 파이프를 기다리지 않게 한다. 소유한 process group만 종료하며 별도 사용자 프로세스는 건드리지 않는다.

공식 근거: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Permissions](https://learn.chatgpt.com/docs/permissions). 설치된 CLI 0.166.0의 help 및 생성한 JSON Schema와 대조했다. 설치본이 필수 CLI 옵션을 지원하지 않으면 명시 오류로 멈춘다.

## 검증 범위

- 모의 CLI/Qt: 독립 인증 환경, 공식 logout→login 순서, 사용량 기간/bucket/잔여량, 실패/계정 전환 시 초기화, 모델·강도 인자, 구조화 오류, 동일 Candidate 재개, 분석/자산 재사용, 기존 종료/원본 보호 회귀.
- 실제 CLI: 사용자 승인한 기존 로그인 환경을 이번 시험에만 명시 사용했다. App Server 로그인/공식 모델 목록/사용량 조회와 최소 Scene 분석 Schema 응답을 확인했다. 실제 로그아웃·다른 사용자 로그인·사용량 강제 소진은 하지 않았다.
- 새 Builder 전용 인증 환경은 로그인 전이다. 실제 브라우저 로그인은 사용자가 공식 절차로 진행한다.
- 실제 최소 분석은 사진 없는 독립 시험 Project에서 추가 RGB 자료를 요청하는 결과다. 전체 실사진 Scene 생성이나 새로운 물리 정확도 검증으로 확대하지 않는다.

로그·JUnit·UI 배치 캡처는 Git 제외 `workbench_runs/auto_reconstruction_ui_20261107/`에 보존한다. UI 배치 이미지의 사용량은 합성 예시이며 실제 계정 수치가 아니다. 최종 테스트 수치와 원본 보존 결과는 아키텍처 문서의 해당 날짜 절에 기록한다. Commit/Push는 하지 않는다.

2026-11-07 후속: Scene Prepare에서 Project 선택 시 등록된 Capture와 Camera-only 관측을 아래 Snapshot 표에 복원한다. Side/Wrist 썸네일·측정 관절값·기록 시각과 더블 클릭 상세 보기를 재사용하며 새 연결에서도 기존 목록을 유지한다. 다른 Project로 전환하면 해당 Project의 목록으로 교체한다. 미완료/손상 자료는 완료된 캡처로 표시하지 않고 조회 오류를 안내한다. `auto_version`의 기존 캡처 4개를 읽기 전용으로 확인했고, 관련 Snapshot/관측/Qt 회귀 11개가 통과했다.

2026-11-08 통합: 새 기본 Geometry는 `mast3r_colmap`이다. 저장된 MASt3R Python·공식 소스·Checkpoint 및 COLMAP Python을 읽고 누락 항목만 안내한다. 기존 DA3 구성의 명시 Legacy 해석은 유지한다. MASt3R Matching, COLMAP Registration/BA, Dense Geometry, Metric Registration 상태를 같은 단일 화면에 표시한다. 기존 로그인·모델·사용량·중단·재개 컨트롤은 변경하지 않았다. [통합 기록](geometry-backend-integration.md)을 따른다.
