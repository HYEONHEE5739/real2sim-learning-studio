# Codex VLM TIMEOUT 분석과 실행 안정화

2026-11-11. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`. 기존 미커밋 구현과 staged 23개를 보존했다. **동일한 합성 컵으로 제품 VLM 경로의 온라인 실행 1회가 51.825초에 성공했고, 저장된 응답으로 Stage7 작업 입력 생성을 검증했다.** 실제 Mesh 제작과 사용자 Scene Reconstruction은 실행하지 않았다.

| 판정 | 결과 |
|---|---|
| LIVE_VLM_SUCCESS | 최종 JSON 수신, 정상 종료 코드 0, TIMEOUT 없음 |
| SCHEMA_VALID | 기존 Stage5 초기 Schema 통과, 컵 ID·Box·메모·불확실성 확인 |
| HANDOFF_VALID | 실제 응답 재사용, Stage7 파싱·Modeling Task 생성 및 동일 입력 재현 통과 |
| ACTUAL_MESH_NOT_TESTED | Blender/Codex 모델링 실행 0회 |
| 이전 900초 실패의 정확한 원인 | **UNKNOWN**. 당시 이벤트 시간·명령 본문·Timeout 직전 원 출력 파일 상태가 기록되지 않았음 |

이번 근거는 Git 제외 [진단 폴더](../workbench_runs/diagnostics/codex_vlm_timeout_analysis/)에 있다. 이전 [실패 기록](codex-vlm-live-validation.md)과 해당 원시 진단은 그대로 보존했다. 현재 성공을 과거 실패의 성공으로 소급하지 않는다.

## A. 이전 TIMEOUT에서 확인한 사실

### 타임라인과 명령

이전 CLI는 `0.166.0`, 모델은 `gpt-6.1-sol`, Thinking Effort는 `high`, 입력은 합성 RGB 768×512 한 장이다. 부모 예산 900초에 대해 전체 호출은 **901.937초** 후 TIMEOUT으로 끝났다.

| 순서 | 보존된 근거 | 이벤트 시각 / 소요시간 |
|---|---|---|
| CLI 시작 / `--image` 전달 | 당시 `run_codex_vlm`과 Harness의 명령 구성, 이미지 Manifest/SHA | 정확한 시작 시각·모델의 이미지 수신 시각 UNKNOWN |
| `thread.started` → `turn.started` | 이벤트 종류 집계 각 1개 | 각각 UNKNOWN |
| `item_0` agent_message 완료 | Tool 메타데이터 표본 | UNKNOWN. 본문 미보존 |
| `item_1` command 시작 → 완료 | exit 0 | 명령·시각·시간 UNKNOWN |
| `item_2`, `item_3` command 시작 → `item_3`, `item_2` 완료 | 두 명령 모두 exit 0 | 명령·시각·시간 UNKNOWN |
| 마지막 보존 이벤트 | `item_2` command 완료 | 이후 대기시간 UNKNOWN |
| 부모 Timeout / 소유 Child 종료 | `FAILED/TIMEOUT`, returncode -15 | 전체 호출 901.937초; 정확한 이벤트별 종료 시각 UNKNOWN |

원본 stdout은 임시 파일이었고 상세 내용은 종료 때 삭제됐다. 보존 표본에는 `turn.completed`, token usage, 오류 코드가 없다. 최종 Candidate용 answer와 완료 Worker Cache는 없다. **임시 작업 폴더의 원 answer가 Timeout 직전에 있었는지는 확인하지 못했다.** Child 그룹 잔존이 없었던 사실과 서버 쪽 요청 종료 여부는 다르며, 이전 원격 종료 상태는 UNKNOWN이다.

당시 프롬프트는 VLM에도 `BUILDER_GUIDE.md`와 `tasks.json`을 읽으라고 요구했다. 임시 CWD, 기존 Builder permissions profile과 승인 `never`를 사용했으나 작업 폴더는 쓰기 가능했고 Shell 도구를 별도로 비활성화하지 않았다. 세 명령이 실제 무엇을 읽었는지, 외부 파일 탐색·반복·Sandbox 거부가 있었는지는 보존 로그로 판단할 수 없다. exit 0만으로 명령의 필요성이나 보안을 증명하지 않는다.

### 원인 분류

아래 CONFIRMED는 관찰 사실 또는 재현된 결함의 확정이며, 모두가 이전 Timeout의 직접 원인이라는 뜻은 아니다.

| 가능성 | 분류 | 근거와 한계 |
|---|---|---|
| VLM에 파일 읽기 Agent 작업을 요구한 정책 | CONFIRMED | 당시 함수와 Prompt에서 확인. command 3건도 관측됨 |
| Tool 사용이 900초 지연을 만들었음 | SUPPORTED_HYPOTHESIS | 불필요한 실행 기회는 있었지만 각 명령 시간과 이후 시간 기록이 없음 |
| 모델 추론·Reasoning 지연 | UNKNOWN | reasoning 시간·상세 서버 상태 없음. `high`를 유지한 새 호출은 성공 |
| Schema 복잡도로 지연 | UNKNOWN | 크기는 측정했으나 병목이라는 근거 없음. 동일 Schema의 새 호출 성공 |
| 완료 결과를 기다리다가 Wrapper가 잃는 경로 | CONFIRMED, Fake 재현 | 유효 answer + `turn.completed` 뒤 CLI 종료가 지연되면 기존 Wrapper가 Timeout 처리. **과거 실행에서 이 경로가 발생했는지는 UNKNOWN** |
| 최종 JSON 파일 생성·수집 문제 | UNKNOWN, 과거 실행 | 임시 answer의 당시 존재 여부가 미기록. 새 Fake/실제 정상 수집은 검증 |
| Sandbox 권한 문제 | UNKNOWN | 거부 이벤트 근거 없음. command exit 0이 모든 파일 접근 성공을 뜻하지 않음 |
| 이미지 전달 누락 | UNKNOWN, 과거 모델 수신 | 명령/Manifest는 전달 구성을 지지하나 모델 수신 증거 없음. 새 호출은 실제 컵 내용과 일치 |
| 네트워크·전송 재시도 | UNKNOWN | 원 네트워크 로그 없음. 설치 CLI의 `unbounded_connection_retries=true`는 관측했지만 당시 재시도 근거가 아님 |
| 인증·사용량 제한 | UNKNOWN, 과거 실행 | 보존 표본에 관련 오류 없음. 전체 로그에 없었다고 단정하지 않음 |
| 부모 예산 초과와 소유 프로세스 종료 | CONFIRMED | 실제 TIMEOUT / -15. 예산 초과는 증상이며 근본 원인과 구분 |

정상 응답의 지연 분포나 Effort별 비교가 없어, `high`가 필수인지와 더 짧은 VLM 예산의 적정값은 UNKNOWN이다. 기존 UI 설정을 유지했으며 별도 Effort 기본값·UI를 추가하지 않았다. 현재는 기존 선택으로 실행 가능하다. 향후 작업별 Effort 분리는 실제 지연·품질 근거가 있을 때 검토한다.

## B. 실행 경계와 Prompt 수정

### 실제 CLI 지원 범위

설치 CLI의 Version/Help/`features list`를 직접 확인했다. `--image`, `--json`, `--output-schema`, `--output-last-message`, `--ignore-user-config`, `--ephemeral`, `--disable`, `--no-daemon`을 사용한다. 공식 [CLI reference](https://developers.openai.com/codex/cli/reference)도 대조했다. 미지원 `--no-tools` 같은 옵션은 만들지 않았다.

공식 설정에서 `features.shell_tool`은 명령 실행 제어이며, `model_instructions_file`은 기본 지침 교체, `project_doc_max_bytes`는 AGENTS 읽기 크기 제한이다. 이 세 계약을 사용했다. [OpenAI configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

VLM 실행에만 다음을 적용했다.

- 입력 Context·Memo·이미지 순서/SHA를 프롬프트에 직접 넣어 파일 읽기가 필요하지 않게 했다. 보이는 것과 Memo를 구분하고, 없는 실측·물체를 만들지 않으며 지정 JSON 한 번만 반환하도록 명시한다.
- 신뢰 Guide의 0·1·2·9절에서 시각 분석용 정책을 만들고 `VISUAL_POLICY.md`로 전달한다. 원본 전체 Guide 18,641B와 SHA도 보존한다. `model_instructions_file`과 `project_doc_max_bytes=0`을 VLM에만 지정한다.
- `shell_tool`, `code_mode_host`, `multi_agent`, `apps`, `plugins`, `browser_use`, `computer_use`, `image_generation`, `view_image`, `sleep_tool`, `hooks`, `skill_search`, `skill_mcp_dependency_install`, `goals`, `unbounded_connection_retries`를 비활성화한다. 실제 feature 조회에서 15개가 모두 false인지 Capability Gate로 검사한다.
- 기존 permissions profile에서 임시 작업 폴더를 read-only로 제한하고 도구 네트워크·web search 차단, 인증 파일 deny를 유지한다. `--no-daemon`으로 공유 백그라운드 서버를 사용하지 않는다. CLI 자신이 출력 파일을 저장하는 것은 실제 정상 동작으로 확인했다.

**제한 수준:** 프롬프트의 금지만으로 기술적 차단을 주장하지 않는다. Shell과 위 기능의 비활성화는 CLI 지원 기능으로 적용했지만 모든 내부·계획 도구의 등록 목록이 비었다고 증명한 것은 아니다. `unified_exec`는 `--disable`만으로 false가 되지 않아 비활성화 목록에 넣지 않았다. 명령 실행은 `shell_tool=false`로 제어한다. 도구 네트워크 차단은 모델 서비스 연결까지 끄는 설정이 아니다. 유한한 내부 전송 재시도 횟수는 UNKNOWN이며 별도 Provider를 만들지 않았다.

오프라인 `debug prompt-input` 검사도 저장소 밖 CWD에서 실행했다. 선택 시각 정책과 inline Context가 나타나고, 조사한 루트 AGENTS 및 기본 코딩 지침의 표식은 나타나지 않았다. 이는 해당 표식 검사 결과이며 숨겨진 모든 Context가 없다는 주장은 아니다. 이 명령은 추론을 요청하지 않았다.

### Schema와 Stage7 계약

| 정적 항목 | 결과 |
|---|---:|
| Schema UTF-8 크기, `json.dumps` 기본 표현 | 5,083B |
| 전체 `required` 항목 합 | 66 |
| Object Schema 노드, nullable 포함 | 13 |
| JSON 구조의 dict 노드 최대 깊이 | 14 |
| Array Schema 노드, nullable 포함 / maxItems 없는 노드 | 20 / 14 |
| 이전 request JSON 크기, 같은 직렬화 방식 | 7,152B |
| 새 실제 inline prompt / 시각 정책 | 2,094B / 7,839B |

깊이 14는 Schema JSON AST의 깊이이며 응답 Object가 14단 중첩된다는 뜻이 아니다. 이전 request JSON과 새 prompt는 서로 다른 포장 범위라 크기를 직접 속도 개선율로 해석하지 않는다. CLI에 전달한 전체 요청·이미지 토큰 크기와도 다르다.

**Schema는 이전 실제 요청과 동일하다.** Instance ID/Category/Box, 관계·Memo·치수 provenance, nullable/unknown, Model Reference와 Stage7 의미 정보 및 기존 Gate를 제거하거나 분할하지 않았다. 온라인 요청을 여러 번으로 나누지 않았다. `scene_analysis_schema`, `instance_schema`, `modeling_tasks`, `run_codex_modeling`의 AST는 작업 시작 백업과 같다.

변경 함수는 기존 세 제품 파일에 있다.

| 파일 | 변경과 경계 |
|---|---|
| `authoring.py` | `visual_policy`, `run_codex_vlm`: inline 입력·시각 정책·기술 제한·요청 기록·최종 출력 검증 |
| `codex_cli.py` | Capability 조사, `sandbox_args(read_only=...)`, 공통 `execute`의 선택적 이벤트/완료 감지. Stage7 기본값은 기존 동작 유지 |
| `stage_runtime.py` | VLM Cache Identity에 정책 버전 `codex-visual/2`, 정책 SHA와 feature 목록 반영 |

### 출력과 종료 처리

VLM에만 원자적인 `events.json`을 추가했다. 부모가 관측한 UTC/monotonic 시간, 이벤트 종류·안전한 item ID/type/status/exit code, 완료 여부·token 집계를 기록한다. 원격 이벤트 발생 시각과 차이가 있을 수 있다. 명령 본문·모델의 reasoning 원문·계정/토큰·raw Tool transcript는 저장하지 않는다. 일반 error는 기존 오류 분류 코드만 남긴다. stdout은 `pread`로 읽어 Child 쓰기 오프셋을 움직이지 않는다.

`turn.completed`와 실제 최종 파일의 Schema 검증이 **모두** 끝났는데 CLI가 계속 살아 있는 경우, 2초 종료 유예 뒤 소유 그룹을 정리하고 유효 결과를 수집한다. 이는 추론 제한시간을 줄인 것이 아니다. 그때의 -15와 controlled-exit 여부를 기록한다. 부분 JSON·파일 누락·Schema 실패·실패 이벤트는 이 경로로 성공시킬 수 없다. 정상 exit 0과 유효 마지막 메시지만 있는 기존 동작도 유지한다.

실제 이번 호출은 정상 종료 0이어서 이 종료 유예 경로를 사용하지 않았다. Stop/Timeout은 기존 checkpoint·프로세스 그룹 종료를 사용하고 성공 answer를 복사하지 않는다. 완료 Manifest는 성공 후 기존 Orchestrator의 책임이며 실패를 성공 Cache로 승격하지 않는다. CLI auth lock, 계정 Home/전환·모델/강도 선택·Usage 조회를 재사용한다. Stage7의 쓰기 Sandbox·모델링 함수는 바꾸지 않았다.

## C. 오프라인 검사와 실제 온라인 1회

### Fake CLI / 계약 시험

최종 집중 검사 **25 passed, 3.85초**, skip/xfail 없음. `release-focused.xml/log`가 근거다. 반복 RED/Green 수치를 합산하지 않았고 전체 회귀는 실행하지 않았다.

검사에는 inline 정책·Shell 제한, 정상 JSON/usage, 마지막 메시지만 존재, 완료 이벤트 뒤 파일 누락, Schema/JSON 오류, 인증/할당량 오류, 중간 command 뒤 무응답 Timeout, Stop, 부분 출력 폐기, 소유 Child 종료, 정책 변경 시 Cache Identity 변화, 기존 계정 선택과 Stage5→7 분석 재사용·변경 입력 거부가 포함된다. 실패 경로에는 완료 Worker Cache가 만들어지지 않는다.

추가 Fake 재현에서 유효 answer와 완료 이벤트 뒤 CLI만 잠드는 경우를 만들었다. 기존 코드가 TIMEOUT으로 결과를 잃는 RED를 확인하고, 완료 출력 검증 후 정리하는 GREEN을 확인했다. 테스트 수정 중 발생한 오류 이벤트 처리의 이름 충돌도 RED 로그와 수정 결과를 보존했다. 이것을 과거 온라인 실패의 원인 확정으로 사용하지 않는다.

### 실제 호출 결과

동일 입력 [synthetic_cup.png](../workbench_runs/diagnostics/local_runtime_validation/sam/synthetic_cup.png), SHA `1d50eaa62aeb133d7d0ef4befc9e96ee20230ea29404c0b1d8952fbab1f5ffd6`를 사용했다. 기존 UI 선택 **gpt-6.1-sol / high**와 로그인 Home을 그대로 사용하고, 이미지 Capability를 확인했다. 선택한 Effort·모델의 Silent Fallback은 없다.

실제 경로는 `stage_runtime.invoke('vlm') → authoring.run_codex_vlm → codex_cli.execute`다. 단순 CLI 호출로 대체하지 않았다. `online-budget.json`의 execute 시도는 **1회**, 애플리케이션 재시도 **0회**다. 내부 서비스 요청/전송 재시도 수는 이 횟수와 다를 수 있으며 UNKNOWN이다.

| 실제 관측 이벤트 | 부모 경과시간(s) | 한국 시각, 2026-11-11 |
|---|---:|---|
| process.started | 0.001 | 11:50:42.220 |
| thread.started | 0.214 | 11:50:42.433 |
| item_0 완료, type 미기록 | 0.625 | 11:50:42.844 |
| turn.started | 0.656 | 11:50:42.875 |
| agent_message 완료 | 49.456 | 11:51:31.675 |
| turn.completed | 49.464 | 11:51:31.683 |
| process.exited, returncode 0 | 50.174 | 11:51:32.393 |
| 전체 제품 호출 완료 | **51.825** | Harness 측정; 준비·검증 포함 |

이벤트에서 관측된 command_execution은 0건이다. type이 없는 item_0의 내용을 추측하지 않는다. turn 시작부터 완료까지 약48.81초이나 이를 순수 Reasoning/서버 추론 시간으로 분해할 근거는 없다. 실제 CLI usage는 **input 10,169 / cached input 0 / output 1,739 tokens**다. 반환 usage 집계이며 비용이나 독립 정확도 수치가 아니다.

900초 제한은 **늘리지도 줄이지도 않았다.** 정상 high 응답시간 분포가 없어 임의 축소하지 않았으며 이번 한 번의 51.825초만으로 새 전역 예산을 정하지 않았다. 기존 Workspace YAML과 UI 설정도 보존했다.

결과는 컵 `mug_1`, category `mug`, Box `[236,152,563,386]`로 768×512 안에 있다. 내부 Scene 분석에도 같은 ID와 지지면 `table_1`이 있다. 원 RGB를 확인했을 때 크림색 컵·오른쪽 손잡이·갈색 내부와 일치한다. 갈색 부분은 내용물인지 불확실하다고 남겼고 별도 물체로 확정하지 않았다. 두 Geometry는 null, 측정값 0개, 지지 관계는 visual_inference/PROPOSED이며 실제 접촉 인증이 아니다. 전체 `uncertain=true`는 숨은 형상·치수의 불확실성을 보존한 값으로, Scene 완성 판정이 아니다.

![실제 응답의 Box annotation — SAM Mask 또는 Sim 렌더가 아님](../workbench_runs/diagnostics/codex_vlm_timeout_analysis/live_annotation.png)

`status.json=COMPLETE`, 실제 answer와 response가 저장됐다. Harness가 **성공 후** 기존 manifest/cache_key 함수로 Worker Cache를 만들고 SHA/closure 검사를 통과했다. 전체 Stage5의 Cache/분해 실행을 했다는 뜻은 아니다. 소유 그룹 PID 45634의 잔존 프로세스 0개를 후속 확인했다. 이번 완료 이벤트와 로컬 종료를 확인했으나 이전 원격 요청의 종료 상태는 여전히 UNKNOWN이다.

## D. 실제 응답의 Stage7 Handoff

기존 `handoff_harness.py`를 새 진단 폴더로 복사해 사용했다. 실제 저장 answer와 Worker Manifest/SHA를 검증하고 `stages.meshes → parse_scene_analysis → modeling_tasks`의 기존 경로를 실행했다. 추가 `codex_cli.execute`와 `run_codex_modeling`은 금지 함수로 막고, 작업 입력을 만든 직후 중단했다.

- 실제 Scene Analysis SHA: `6fcb7c238e10e7e3f90d796a4f062dc2d42a974c1a2e93bf2015ff67dfad61f2`.
- Guide SHA: `cb24fcb1069b40572287e010db014df03c621b9704f5c5967303ae9238a7fa85`.
- 메모 SHA: `35d8a5c4b3c91bcd35cc80ae1d47caf7c31f82ec460ea711806609222682a0db`.
- Stage7 Task SHA: `bc19a342c97074c0e782611285799397478c633ed99789100ad38b671a93f39f`, 두 번의 CPU 재사용에서 동일.
- Task 상태 `WAITING_FOR_CODEX`: 분석 대기가 아니라 다음 모델링 실행 대기다. 새 의미 분석을 요청하지 않았다.
- Model Reference와 보호 측정값은 이번 합성 입력에서 각각 빈 목록·0개다. 실제 자료가 채워진 사례의 정합을 검증했다고 하지 않는다.

SAM/Depth Forward는 없으므로 Handoff 파일 참조 계약에만 빈 `NOT_RECORDED_mask.png`와 표식 NPZ를 사용했다. 실제 관측·Mask·Depth·실측값으로 승격하지 않았고 모델링/정합에 사용하지 않았다. 이는 **실제 VLM 의미 응답 + 실제 Stage7 작업 생성 + 명시 합성 Geometry 참조**의 검증이다. 전체 Stage5 분해·Stage7 Blender Mesh·Stage8 CPD 성공은 아니다. 추가 온라인 호출 0회, 실제 Mesh 생성 0회다.

## E. 보존과 다음 실행 범위

보호 ledger **18,506개 파일의 SHA/크기 변경 0·누락 0·신규 0**을 확인했다. 범위는 기존 Scene/Input/Capture/Calibration/Candidate/Cache/Export·공용 Asset·Workspace Runtime·이전 live 진단·local_runtime_validation이다. 전체 SDK/모델 디스크의 전수 대조는 아니다. 새 합성 Candidate와 산출물은 이번 진단 폴더 안에만 만들었다.

기존 staged23개 diff SHA `5e259fbe6370626a3b608b1b55bc3d12205ab69650731b1994f1c9b2184c3bb6`, HEAD/브랜치는 보존했다. Workspace Runtime SHA는 `02345f185e59b941d182ec131d74c4ebc54464c169b3579b1353be7fa2fdc129`로 유지했다. 이번 변경은 세 제품 파일·두 시험 파일·이 문서다. 이전 미커밋 작업과 구분한다. 변경 Python 5개 bytecode 없는 compile, `git diff --check`를 확인했다.

제품 VLM 경계는 이제 같은 합성 입력을 정상 완료할 수 있다. **한 번의 성공으로 지연 문제가 항상 해결됐다고 보장하지 않는다.** 이후 실패는 새 timestamp/event/종료 기록으로 대기 위치를 구분할 수 있다. 실제 사진에서 최소 Stage별 검증을 진행할 근거는 생겼지만 이번 범위에서는 실행하지 않았다.

남은 검증은 실제 복수 Instance/Model Reference·Memo 충돌/부분 실측 보호, SAM·FLUX 제거 품질·Depth와의 연결, Stage7 실제 Asset 제작, CPU CPD·Robot World 연결·metric QA, Side/Wrist의 공유 Calibration/FK·독립 Capture 비교, 실제 물리·Task다. VLM 성공을 이들의 성공으로 확장하지 않는다.

설치·다운로드·DA3/SAM/FLUX/PDA/Bria/CPD 재실행·사용자 Scene E2E·Isaac/실물 구동·전체 회귀·삭제·Commit/Push/Merge는 하지 않았다. UI/Guide 원문·Workspace Runtime·Stage7 모델링 함수와 Schema는 보존했다.

재검토 자료: `schema-prompt-analysis.json`, `policy-probe-outside-repo.json`, `contract-preservation.json`, `release-focused.xml/log`, `live-preflight.json`, `live-result.json`, `live-validation.json`, `handoff-result.json`, `process-cleanup.json`, `preservation-after.json`, `compile-check.json`, `change-inventory.json`, `summary.json`. 실제 job의 `request.json/input_manifest.json/events.json/answer.json/worker-cache.json`은 `live-result.json`의 result_folder로 연결된다. Git 제외 로컬 자료여서 저장소만 받으면 없을 수 있다.
