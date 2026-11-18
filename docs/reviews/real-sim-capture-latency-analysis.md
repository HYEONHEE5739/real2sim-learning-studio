# Real/Sim Capture 약 13초 지연 — 실물 기록 분석과 개선 설계

2026-11-18. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `25bb1cf083f2ce05a93c3bc2b9e290ba4f6cbf3b`. **원인 조사와 설계까지 수행했다. 대기열·렌더 스케줄·검증 정책·Teleop은 수정하지 않았다.** 다음 실행의 렌더 세부 시간을 구분하도록 기존 세 모듈에 시간 필드만 추가했다. 실물 장치 연결·구동, 새 Sim 렌더, AI 추론, 전체 회귀, Commit/Push는 실행하지 않았다.

## 결론

첫 촬영의 **`SIM_PAIR → REGISTERING`이 13.151초**다. 클릭부터 최종 등록 알림까지는13.978초이며, 원본 Side/Wrist/q는 클릭 후 **0.277초**에 이미 보존됐다. 두 번째와 세 번째는 렌더 순서를 기다리면서 최종 등록까지 각각 **26.183초·38.816초**로 늘었다.

대상은 **`auto_version / scene-codex-first-fit_001`**이다. 이 Scene의 렌더 함수가 매번 약7.4~7.6초 걸리고, 단일 Renderer에서 진행 중인 Live 렌더를 기다린 뒤 촬영용 렌더를 수행한다. 마지막 요청은 보존된 Live/촬영 결과로 이 선후 관계를 대조할 수 있다. 앞선 세 요청의 렌더 진입 전 구간은 약5.71~7.50초지만, 당시 요청 수신·실행 시작 계측이 없어 이를 전부 순수 폴링 대기로 확정하지 않는다.

`render_ms`는 GPU에서 RGB를 그리는 시간만 의미하지 않는다. `AuthoredRenderer.render`의 FK·Scene 검증·상태 갱신·두 RGB 생성 전체 구간이다. 이 Auto Scene은 매 q 갱신에 전체 자산/Collision 검증을 반복한다. 앞선 별도 조사에서는 **렌더·장치 없이 검증만8.274초**가 재현됐다. 따라서 반복 검증 경로가 핵심 개선 대상이다. Auto Reconstruction으로 만들었다는 사실 자체가 모든 Scene을 느리게 만든다는 뜻은 아니다.

## 1. 사용한 실제 Session

근거는 `workbench_runs/real_sim/.workbench-runs/<run_id>/events.jsonl`, `prepared.json` 및 출력 폴더의 `session-report.json`, `renderer/*.json`, `stdout.log`다. 등록 원본은 `workbench_runs/scenes/auto-version/input/captures/real_sim_20261118_01/`이다.

| 최근 실물 Session | R03 Run ID | Scene | Capture |
|---|---|---|---|
| real_sim_20261118_03 | 5e4c2ce9a4ee465fa0bf4009658bf5c7 | auto-version / scene-codex-first-fit_001 | 0건 |
| real_sim_20261118_02 | a54c60d503f84a0e8b017b3f067c0b0c | pickplace-colorblock / scene-v9-task-objects | 0건 |
| **real_sim_20261118_01** | **c4ffe82213d24f17925cb4bebee3fc66** | **auto-version / scene-codex-first-fit_001** | **4건 요청, 3건 등록, 중단 시1건 원본 보존** |

최신 두 Session에는 촬영이 없어 **가장 최근 촬영이 있는 실물 Session인 _01**을 분석했다. R03의 `device_source=hardware`를 확인했다. Mock이나 다른 Scene의 빠른 수치를 이번13초의 실측으로 사용하지 않았다.

R03 이벤트는 `seq`가 있지만 이벤트마다 절대 시각은 없다. UI의 REQUESTED 이벤트는 UI 내부에 있으므로 Worker가 보존한 `request.requested_ns`를 시작점으로 썼다. 나머지는 같은 호스트 monotonic ns인 `phase_times_ns`, `processing_times_ns`, `sim_timestamp`다. 카메라 노출 시각·하드웨어 동기 시각과는 구분한다.

## 2. 단계별 실제 시간

아래는 **직전 단계부터의 초**다. 단계는 상태 게시 시각이며 비동기 Writer 내부 실행 시간과 동일하지 않다. prepare는 QUEUED 알림 게시 전에 이미 실행 중일 수 있다.

| 구간 | capture_001 | capture_002 | capture_003 | 네 번째, 등록 전 중단 |
|---|---:|---:|---:|---:|
| REQUESTED → OBSERVED | 0.106 | 0.082 | 0.088 | 0.087 |
| OBSERVED → QUEUED | 0.084 | 0.077 | 0.082 | 0.079 |
| QUEUED → RAW_SAVED 알림 | 0.109 | 0.112 | 0.109 | 0.106 |
| RAW_SAVED → SIM_PAIR | 0.045 | **10.389** | **23.294** | **36.306** |
| SIM_PAIR → REGISTERING | **13.151** | **15.138** | **14.859** | REGISTERING 없음 |
| REGISTERING → REGISTERED | 0.482 | 0.385 | 0.383 | REGISTERED 없음 |
| 클릭 → REGISTERED 알림 | **13.978** | **26.183** | **38.816** | 51.564초에 FAILED |
| 클릭 → 실제 원본 보존 완료 | **0.277** | **0.247** | **0.257** | **0.252** |

네 번째는 `Stopped before registration/Pair completion; sealed observation retained`로 종료됐고 pending 폴더의 원본 RGB/q가 남아 있다. Renderer 결과 파일이 있다는 이유로 Pair 등록 성공으로 승격하지 않았다.

첫 촬영의 클릭 기준 시각:

| 상태 | 클릭 후 초 |
|---|---:|
| REQUESTED | 0.000 |
| OBSERVED | 0.106 |
| QUEUED | 0.190 |
| RAW_SAVED 알림 | 0.299 |
| SIM_PAIR | 0.344 |
| REGISTERING | 13.496 |
| REGISTERED | 13.978 |

원본 보존은 `processing_times_ns.raw_saved_ns` 기준이다. RAW_SAVED 알림은 부모가 Future를 확인한 뒤 게시하므로 약22~23ms 늦다.

세 성공 결과의 `capture_elapsed_s`는13.932 / 26.136 / 38.765초다. 이 값은 `CaptureQueue.poll`이 완료 결과를 받고 `jobs.pop`을 하기 직전에 측정한다. REGISTERED는 정리·ACK 이후에 게시된다. UI의 Queue 감소 순간을 위 REGISTERED와 ns 단위로 동일시하지 않는다. UI의80ms 폴링과 실제 repaint 지연은 당시 계측이 없다.

후속 클릭 간격은2.921 / 2.302 / 1.931초, 등록 완료 사이 간격은 **15.126 / 14.935초**다. Queue는 실제4건까지 찼다. **첫 촬영에도13초짜리 Sim 구간이 있고**, 이후에는 앞선 렌더를 기다리는 시간이 추가된다. 초기화 한 번만 느린 현상으로 설명할 수 없다.

## 3. 렌더 연산·Live 대기·결과 전달

| SIM_PAIR → REGISTERING 구성 | 첫 촬영 | 두 번째 | 세 번째 | 근거 |
|---|---:|---:|---:|---|
| 보고된 렌더 함수 시작 전 구간 | 5.710초 | 7.501초 | 7.403초 | sim_timestamp − render_ms − SIM_PAIR, 계산값 |
| 촬영용 render_ms | **7.389초** | **7.581초** | **7.400초** | 저장된 함수 소요 시간 |
| 렌더 완료 → REGISTERING | 0.053초 | 0.057초 | 0.056초 | 저장된 완료/부모 상태 시각 차이 |
| 합계 | **13.151초** | **15.138초** | **14.859초** | 실제 상태 구간과 일치 |

첫 행은 진행 중인 Live 잔여 시간, 자식의 요청 확인, 렌더 진입 전 `view.verify` 및 기타 전달 비용을 포함할 수 있다. **전부 폴링 대기라는 증거는 없다.** 마지막 구간도 PNG 생성·SHA·결과 게시·부모 폴링·finish 제출을 포함하므로 순수 IPC 시간으로 이름 붙이지 않는다.

### 마지막 Live와 네 번째 요청의 직접 대조

보존 결과는 `live_786` generation10과 네 번째 촬영 generation11이다.

| 항목 | 저장값 또는 계산값 |
|---|---:|
| Live render_ms | 7.497665초 |
| Live 함수 시작 역산 | 32587525895723ns |
| 촬영 요청 파일의 실제 제출 | 32587602506041ns |
| Live 완료 | 32595023560712ns |
| 촬영 제출 후 Live 잔여 시간 | **7.421055초** |
| 촬영 함수 시작 역산 | 32595037748697ns |
| Live 완료 → 촬영 함수 시작 역산 | 14.188ms |
| 촬영 함수 자체 | **7.332486초** |
| 촬영 제출 → 촬영 렌더 완료 | **14.767729초** |

촬영 요청은 Live 함수 실행 구간 안에 들어왔다. 같은 Renderer는 실행 중인 Live를 선점하지 못하고 완료 후 촬영을 처리했다. 역산 시작은 함수 내부 timestamp와 직후 render_ms 측정의 미세한 차이를 포함한다. 과거의 정확한 요청 파일 읽기 시각을 새로 만들어 넣지는 않는다.

### Auto Scene의 렌더 함수가 오래 걸리는 이유

현재 경로는 `render_worker → AuthoredRenderer.render → observation_scene → scene.validate`다. q로 FK를 계산할 때 `validate(..., complete=True)`를 호출한다. compound Collision Part마다 전체 assets를 가진 임시 Scene으로 재귀 진입하고 각 진입의 마지막에서 전체 자산을 다시 해시한다. Geometry가 바뀌지 않은 다음 Live/촬영에서도 반복된다.

앞선 [연결 지연 조사](real-sim-startup-latency-analysis.md)의 **별도 읽기 전용 단회 프로파일**:

| 동일 Scene 검증1회 | 앞선 측정 |
|---|---:|
| 총 시간 | 8.274초 |
| 재귀 포함 validate | 141회 |
| SHA 계산 | 64,296회 |
| 반복 논리 읽기 합계 | 3,903,444,423B |
| 자산 수 / 목록1회 논리 크기 | 456개 / 27,684,003B |

이번 촬영 내부를 다시 측정한 값은 아니다. 이번에도 반복 검증 경로를 확인했고 실제7.4초 함수 구간과 규모가 일관된다. **7.4초 중 GPU RGB 생성만 몇 ms였는지는 과거 로그에서 UNKNOWN**이다. 다음 실행을 위한 구간 계측을 추가했다.

stdout.log의 EGL/AMD 초기화 경고에는 작업별 지연 timestamp가 없다. 경고만으로13초를 드라이버 문제로 확정하지 않는다. 다른 Scene인 pickplace_colorblock / scene-v9-task-objects의 기존 Live는 약3~4ms였다. 모든 MuJoCo 또는 모든 Capture에 고정된13초 비용은 아니다.

## 4. PNG·SHA·비교 이미지·Evidence·Lock

### 실제 Writer 기록

`save_timing_ms`와 `processing_times_ns`에서 가져왔다. prepare에는 첫 네 구간이, finish에는 Pair/등록 등이 포함되므로 겹치는 값을 합산하지 않는다.

| 작업(ms) | 첫 촬영 | 두 번째 | 세 번째 |
|---|---:|---:|---:|
| 관측 검증 observation | 9.546 | 9.900 | 9.265 |
| 모델 공유/확인 model | 11.499 | 11.853 | 11.758 |
| 원본 PNG·메타데이터 게시 encode_seal | 100.044 | 98.817 | 101.913 |
| 원본 closure_check | 15.372 | 16.261 | 14.493 |
| **prepare 합계** | **136.461** | **136.831** | **137.428** |
| Pair 생성 pair | 316.789 | 202.329 | 204.191 |
| Evidence 등록, 내부 검증 포함 | **64.524** | **56.862** | **57.256** |
| **finish 전체** | **428.730** | **307.751** | **310.858** |
| **Writer 작업 합계, Sim 대기 제외** | **565.190** | **444.582** | **448.286** |

등록57~65ms는 `import_snapshots` 전체이며 Evidence 쓰기만의 시간이 아니다. Reader/SHA 확인·중복 검사·Evidence 등록을 함께 수행한다. 원본 PNG 개별 인코딩/SHA, Evidence JSON 쓰기만의 과거 시간은 **UNRECORDED**다. encode_seal 전체를 PNG 인코딩만의 시간으로 오인하지 않는다.

### compare()의 파일과 필요성

`pairs.write_pair`는 두 카메라에 `validation.compare(..., save_inputs=False, png_compress_level=1)`을 호출한다.

| 파일 | 카메라당 크기 | 내용 | 매 클릭의 원본 보존에 필요한가 |
|---|---|---|---|
| side_by_side.png | 1280×480 | Real/Sim 좌우 연결 | 진단용, 지연 생성 가능 |
| overlay.png | 640×480 | Real/Sim 50:50 평균 | 진단용, 지연 생성 가능 |
| difference.png | 640×480 | RGB 절대 차이 | 진단용, 지연 생성 가능 |
| side.png, wrist.png | 각각640×480 | 원본 Real | 필요 |
| sim_side.png, sim_wrist.png | 각각640×480 | 동결 q의 Sim | Pair 완성에 필요, 원본 보존 ACK와 분리 가능 |

완료 Capture당 원본2장·Sim2장·비교6장으로 PNG10장이다. `save_inputs=False`이므로 compare에서 Real/Sim을 재저장하는 중복은 이미 막혀 있다. MAE/RMSE/Canny edge IoU도 계산하지만 이 수치·이미지는 물리/보정 인증이 아니다.

비교6장의 실제 크기 합은2,148,605 / 2,136,119 / 2,208,408B, 3건 합계6,493,132B다. 네 실시간 영상은 비교6장을 기다릴 필요가 없다. `ResultsDialog`는 상세 보기에서 저장 PNG를 열거한다. Builder 진단도 비교 이미지를 사용하지만 원본 Pair로 나중에 생성할 수 있다. **기존 Archive의 비교 파일은 metadata hash closure에 포함돼 사후 삭제할 수 없다.**

### 실제 저장 RGB의 CPU Replay

기존3건의 Real/Sim PNG를 **진단 폴더에 복사**하고 실제 write_pair/compare를 한 번씩 실행했다. OpenCV thread1이며 원본에 링크를 추가하거나 쓰지 않았다. 생성된 비교6장 모두 기존 파일과 SHA가 같았다.

아래는 **이번 오프라인 Replay 시간**이며 당시 실물 시간과 구분한다. PNG 저장은 인코딩+쓰기다.

| Replay 작업(ms) | capture_001 | capture_002 | capture_003 |
|---|---:|---:|---:|
| Side: side_by_side PNG | 24.503 | 20.053 | 19.903 |
| Side: overlay PNG | 15.609 | 13.978 | 13.982 |
| Side: difference PNG | 17.232 | 15.188 | 15.369 |
| Wrist: side_by_side PNG | 17.268 | 17.132 | 18.029 |
| Wrist: overlay PNG | 12.571 | 12.245 | 13.180 |
| Wrist: difference PNG | 12.894 | 12.906 | 13.583 |
| **비교 PNG6장 합계** | **100.076** | **91.503** | **94.047** |
| 원본+Sim decode/convert | 15.108 | 14.369 | 14.448 |
| Pair 내부 SHA14회 합계 | 1.888 | 2.039 | 2.002 |
| Pair/metadata atomic JSON2회 | 27.269 | 27.461 | 30.999 |
| compare 내 PNG 외 계산 등 | 37.941 | 29.259 | 31.899 |
| **write_pair 전체** | **201.777** | **167.250** | **175.334** |

SHA14회는 Replay의 `pairs.file_sha256` 호출이다. Renderer·Reader·등록·Scene 전체 검증까지 포함한 수가 아니다. compare_total은 PNG 저장을 포함하므로 원시 profile의 모든 합계를 더하면 이중 계산된다.

비교 이미지 지연 생성의 근거는 되지만 이를 없애면13초가 해결된다는 근거는 아니다. 반면 **렌더 함수 안에서 반복되는 Scene 전체 SHA**는 별도의 큰 비용이다.

### Project Lock과 중복 검사

- `SnapshotStore.finish`는 `candidate.exclusive(project)` 안에서 Pair 생성·closure·등록을 한다.
- Lock은 working/run.lock을 exclusive create하고 이미 있으면 **즉시 Project busy 오류**를 낸다. 기다리는 retry/sleep 루프가 없다.
- 내부 Project Lock은 ContextVar 재진입이어서 자기 Lock 해제를 기다리지 않는다.
- Reader의 .capture.lock shared flock은 해당 파일이 있을 때만 사용한다. 조사한 네 Capture 폴더에는 없었다.
- OS 파일 생성 자체의 시간은 별도 미기록이다. 그래도 성공한 finish 전체가 **0.308~0.429초**여서13초를 Project Lock 대기로 설명할 수 없다.
- 같은 Sim PNG를 transport 검증→hardlink 검증→metadata SHA로 반복 확인한다. 쓰기 완료·소유권·변경 감지 경계를 검토하면 줄일 여지가 있지만 이번 Pair SHA 합계는 약2ms다. 일괄 검증 제거의 우선순위는 낮다.
- Raw closure, Pair 추가 뒤 closure, Evidence 입력 해시는 각 게시 경계를 확인한다. 변경 파일만 검증하거나 같은 불변 transaction 안의 검증 결과 재사용을 검토할 수 있다. 단순 경로 Cache로 검증을 건너뛰면 원본 변경을 놓칠 수 있다.

## 5. 원본 저장 후에도 Queue가 차 있는 이유

현재 흐름:

`CaptureQueue.request → spawn Writer.prepare → RAW_SAVED → RenderProcess.capture → Writer.finish/write_pair/import_snapshots → jobs.pop → ACK/REGISTERED`

capacity=4는 원본 저장 대기만이 아니라 **Sim/Pair/등록까지 끝나지 않은 전체 촬영 작업**의 제한이다. 그래서 Raw가 안전해도 슬롯을 반환하지 않는다.

이는 처리량을 넘는 요청으로 메모리·디스크·미완료 Pair가 무제한 쌓이는 것을 막고 완료 ACK를 등록된 Artifact와 일치시킨다. 다만 UI에서 단순히 “Capture 저장 중”으로 보이면, 이미 원본 저장이 끝난 사용자는 촬영 자체가 느리다고 느낀다.

RenderProcess.capture는 동결 요청이 이미 있으면 거부하며 자식도 렌더 한 건을 끝내야 다음 요청을 읽는다. Queue는 렌더 결과를 받은 뒤 다음 Raw를 제출하므로 이전 등록이 끝나기 전에도 다음 렌더를 시작할 수 있다. **모든 단계 전체가 직렬인 것은 아니지만 Sim 렌더 서버는 한 번에 한 건**이다.

자식 루프는 Capture를 Live보다 먼저 검사한다. 하지만 진행 중인 Live를 선점하지 못하며 현재 Capture 완료 후 부모가 다음 Capture를 제출하기 전에 새 Live가 시작될 수도 있다. Auto Scene의 Live가7초 이상이면 이 간격이 큰 병목이다.

### 이번 기록의 Teleop

첫 촬영부터 네 번째 종료까지 진행 이벤트1,643개 중1,641개가 `TELEOP_ACTIVE/true`이고 마지막2개만 `DISCONNECTING/false`였다. **이번 기록에서 촬영마다 Teleop이 꺼졌다는 증거는 없다.** 과거 Stale feedback 중단과 이번 Queue 지연을 같은 현상으로 합치지 않는다.

제어 소유자와 Writer/Renderer 프로세스 분리를 유지한다. 촬영 후 Teleop을 자동 재시작하거나 freshness/heartbeat 기준을 늘리는 설계는 제안하지 않는다. 활성 상태 기록만으로 독립 모터 추종 품질을 인증한 것도 아니다.

## 6. 가장 단순한 개선 설계 — 이번에는 적용하지 않음

### 우선1: 불변 Geometry 전체 검증 반복 줄이기

기존 AuthoredRenderer/observation_scene/scene.validate 경계를 재사용한다. 연결 시 Geometry·Model·Collision·자산 SHA를 충분히 검증하고 동일성을 유지한다. 매 q에는 FK·좌표·유한값·관절 범위 등 변경된 상태를 확인한다. 파일/Scene/Mapping이 바뀌면 전체 검증을 재수행하거나 실행을 차단한다.

compound Part마다 전체 자산을 재해시하는 중복부터 줄인다. 파일 변경 감지는 유지해야 한다. **개선 후 렌더 속도는 미측정**이며 다른 Scene의3~4ms를 보장값으로 쓰지 않는다.

### 우선2: 기존 Queue에서 원본 보존과 후처리 완료 분리

새 Manager/DB 없이 기존 Queue/Writer/R03에 두 의미를 명시한다.

1. 클릭 시 Side/Wrist와 각 시각의 측정 q를 동결한다.
2. Writer.prepare가 원본·Manifest·closure를 게시하면 **촬영 수락 슬롯과 큰 RGB 메모리를 반환**하고 “원본 저장됨”을 알린다.
3. sealed 경로/ID/SHA만 작은 후처리 목록에 남겨 Sim/Pair/등록을 수행한다.
4. Pair/등록 완료 후에만 최종 등록 성공을 알린다. 원본 보존을 REGISTERED로 잘못 표시하지 않는다.
5. **후처리 목록도 유한하게 제한**하고 디스크 부족/지속 적체 시 명시적으로 새 촬영을 제한한다. Raw에서 슬롯만 비우고 처리량을 무한히 늘리는 방식은 쓰지 않는다.
6. 종료 시 원본을 보존하고 미완료 후처리의 명시적 재개를 지원한다. 현재 복구 함수는 Raw-only를 자동 재렌더하지 않으므로 이 경계는 후속 구현·검증이 필요하다.

원본 보존 후 다음 촬영을 허용할 수 있다. 그러나 Sim이 계속 촬영 속도보다 느리면 유한 Queue는 언젠가 차므로 우선1도 필요하다. 현재0.25초를 모든 환경의 촬영 속도로 보장하지 않는다.

### 우선3: 단일 Renderer의 Capture 우선권 보완

동결 촬영 backlog를 기존 IPC로 알리고 Capture 사이에 새 Live를 시작하는 간격을 줄인다. 실행 중 렌더의 선점·다수 GPU/엔진 Context 병렬 생성은 피한다. Raw는 먼저 보존하고 Live age와 후처리 진행을 구분한다.

### 우선4: 비교6장은 상세 보기 시 생성

원본 RGB·Sim RGB·q·시각·Calibration/Scene/Model SHA·Pair 핵심 메타데이터를 먼저 완성한다. Overlay/Difference/병렬 비교는 상세 보기나 명시 진단 때 생성하고 원본 SHA로 묶는다. 기존 비교 파일은 그대로 보존하고 **새 Capture에만** 선택적 파생 진단 계약을 정의한다. Reader/ResultsDialog도 함께 확인해야 한다.

이번 Replay 기준 PNG 저장 약0.1초와 촬영당 약2.1~2.2MB를 줄일 여지가 있다. 주 병목 해결의 대체 수단은 아니다.

## 7. 최소 계측과 검증

과거 기록을 다시 쓰지 않고 **다음 실행 결과에만** 다음을 추가한다.

| 기존 파일 | 추가 기록 | 유지 |
|---|---|---|
| robot/authored_render.py | render_phase_times_ns: verify, observation_scene, update_scene, 카메라별 RGB, metadata 완료 | 기하/검증 호출·렌더 순서 |
| robot/render_worker.py | render_transport_times_ns: 제출/읽기, render 진입/복귀, 카메라별 PNG·SHA, 결과 게시 직전, 직전 작업 ID/Live 여부/구간 | 단일 자식·요청 선택·PNG·원자 게시 |
| robot/render_transport.py | 부모 결과 읽기 시작/검증 완료·SHA 소요 | 소유 경로·SHA 확인·live decode·frozen path 전달 |

기존 write_pair가 이 필드를 pair.json에 보존한다. result_ready는 JSON 게시 **직전**이어서 부모 read까지의 차이는 게시+스케줄/폴링 지연이다. 게시 직후의 정확한 시간을 같은 결과에 기록했다고 주장하지 않는다. 직전 작업에는 실제 게시 복귀 시각도 남긴다. Legacy에 없는 Worker timestamp를0으로 채우지 않는다.

RGB 구간도 엔진 API의 벽시계 시간이며 GPU kernel profiler 시간과 다르다. 추가 계측으로 실물 장치를 다시 실행하지 않았다.

이번 요청과 직접 관련된 **4개 시험만** 실행했다.

- 신규3개: 시간 필드 부재 RED3건 → 추가 후 GREEN. Fake Renderer를 기존 Worker 루프에 연결해 Live 도중 Capture 도착·실제 PNG/Transport/SHA·Pair 전달을 검사했다. 엔진/장치 생성은 없다.
- Legacy 시간 누락 유지와 authored 세부 구간을 포함한다.
- 기존 PNG/비교 계약1개 통과.
- **4 passed, 0.47초**, timing-green.xml/log. 전체 pytest·Object Library·별도 GUI 창을 실행하지 않았다.
- Python4개 bytecode 없는 compile 및 git diff --check 확인.

변경 파일은 위 제품3개, `robot_learning_workbench/tests/test_capture_render_timing.py`, 이 보고서다. 조사 대상 원본 Session/Capture **120개 SHA/크기 변경0·누락0·신규0**, 기존 미커밋 파일 **79개 변경0**을 확인했다. HEAD·브랜치·기존 Index diff도 동일하다. 전체 디스크/모든 Scene의 전수 감사라는 뜻은 아니다.

근거는 Git 제외 `workbench_runs/diagnostics/real_sim_capture_latency_20261118_001/`의 historical-timeline.json, pair-replay-profile.json, 재현 스크립트, RED/GREEN, compile-check.json, verification-summary.json이다. 제품이 진단 폴더를 참조하지 않는다.

## 세 질문에 대한 답

- **13초는 어디인가?** 첫 촬영의 Sim 요청부터 Writer finish 제출까지13.151초다. 촬영용 함수7.389초와 진입 전 구간5.710초가 대부분이며 원본은0.277초에 저장됐다. 후속 촬영은 차례 대기가 누적된다.
- **매번 필요한가?** 새 q의 Sim은 Pair 완성에 필요하다. 불변 전체 검증의 반복, Live 한 번을 더 기다리는 간격, 비교6장 즉시 저장은 촬영 수락의 필수 조건이 아니다.
- **어떻게 바꿀까?** 먼저 Auto Scene의 반복 검증 비용을 줄이고 기존 Queue에서 원본 보존 ACK/슬롯과 제한된 Sim 후처리를 분리한다. 기존 Teleop 소유자·안전 기준은 유지한다. **이번에는 구조를 구현하지 않았다.**
