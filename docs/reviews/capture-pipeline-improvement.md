# Capture 접수·저장 분리와 Teleop 연속성 개선

2026-11-18. 작업은 11월17일에 시작했고 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `8e02b1ae023a856694a40b947881f76b66410624`의 기존 미커밋 변경을 보존했다. 앞부분은 **제품 수정 전에 정리한 조사·설계**이며 실제 구현·측정 결과는 후속 절에 구분한다. **두 화면의 요청 시점 관측 확보·최대4건 연속 접수·별도 저장을 구현하고 Memory 장치로 확인했다. 실물 USB·모터에서의 연속성은 NOT_VERIFIED다.** 전체 회귀·실물 구동·AI Pipeline은 실행하지 않았다.

## 확인한 현재 경로와 원인

작업 시작 소스에서 Scene Prepare는 Qt Capture → R03 `session_snapshot` → HardwareSession의 안정 관측 대기 → spawn Writer의 `SnapshotStore.prepare` → `finish`/Builder 등록 → 완료 ACK/촬영 기록 순서였다. Real/Sim은 안정 관측 확보 후 같은 Writer와 별도 RenderProcess에 고정 q를 보내고, 둘의 결과를 받은 뒤 Sim PNG·Pair·비교 이미지·등록을 끝냈다. 두 Session 모두 저장까지 끝나야 다음 요청을 받았다.

시작 소스로 기존 큰 Evidence를 **독립 Project로 복사**해 저장 경로를 재실행했다. prepare 1,766.5ms + finish 9,151.4ms = **10,917.9ms**, Evidence 읽기6회·쓰기1회다. 등록 경로의 불필요한 읽기5회를 기대값1회와 비교한 작은 시험도 RED였다. Writer를 미완료 상태로 둔 두 Session 시험에서는 두 번째 Capture 접수가 거절돼 RED였다. 원본 Capture·Scene을 쓰지 않았으며 저장 RGB/q Replay다.

| 작업 | 실행 위치 | 촬영 순간 필요 여부 / 현재 차단 |
|---|---|---|
| 클릭 시각·명령 ID | Qt → R03 명령 파일 | 순간 식별에 필요. 작은 명령만 전달 |
| 측정 q·Side/Wrist receipt 시각 | Session + 기존 CameraReader/제어 이력 | 순간 확보에 필요. 현재 안정 자세를 최대5초 기다림 |
| RGB 고정·시각 정합 최소 검사 | Session | 순간 확보에 필요. USB 노출 시각은 모름 |
| PNG·SHA·원본 Manifest | 기존 spawn Writer 1개 | 별도로 가능. 현재 다음 요청을 차단 |
| 같은 q의 Sim | 기존 RenderProcess | 나중에 가능. 원본 RGB/q를 대체하지 않음 |
| Pair/Overlay/Difference | spawn Writer | 나중에 가능. 원본 관측의 시간 정확성을 결정하지 않음 |
| Evidence 등록·전체 검증 | spawn Writer + Project lock | 나중에 가능. 현재 완료 ACK와 다음 요청을 차단 |
| Leader→Follower | 기존 별도 30Hz 제어 스레드 | 촬영과 독립. 실제 안전 오류에는 중지 유지 |

Overlay는 기존 `write_pair`가 Pair의 해시 closure에 함께 넣기 때문에 완료 전에 생성된다. 이 파일은 촬영 시점 확보에 필요하지 않다. 새 구조에서는 원본 저장 후 Pair 후처리로 넘기며, Pair 최종 게시 전의 SHA 검증 책임은 유지한다.

과거 실물 실패의 100ms freshness 중지는 현재 spawn Writer 수정 이전 실행이다. Capture 밖의 중지도 존재한다. 과거 개별 USB/OS/GIL 함수가 원인이었다고 확정하지 않는다. 현재 제어의 100ms freshness·200ms gap/deadline·UI heartbeat 한계는 바꾸지 않는다.

## 저장 대안 비교와 선택

| 대안 | 접수·누적 성능 | 호환·무결성·복구 | 복잡도·제어 영향 |
|---|---|---|---|
| A. YAML 유지·등록 transaction에서 한 번 읽기·안전한 C 파서·중복 축소 | 즉시 개선 가능. 전체 인덱스 읽기·쓰기는 N에 비례 | 기존 Reader·Project lock·원자적 쓰기 재사용 | 가장 작음. Writer 밖 제어에 파일 작업을 넣지 않음 |
| B. Capture별 Manifest + Scene 인덱스 | 큰 공통 정보의 반복을 줄임. 상위 인덱스도 계속 전체 재작성하면 O(N) 한계는 남음 | 기존 Capture Manifest/Pair와 해시를 활용 가능. Reader의 참조 해석과 게시 상태 구분 필요 | 중간. 대규모 입력 이전은 위험·비용이 있어 이번에 하지 않음 |
| C. SQLite transaction 인덱스 | 추가·조회·동시성에 유리. 이미지 자체 저장은 별도 | DB와 원본 파일의 이중 게시·백업·복구 계약이 추가됨 | 현재 규모에서 새 DB·별도 진실 원천을 만들 비용이 큼. 이번에는 제외 |

**A와 기존 Manifest를 이용한 B의 일부를 결합한다.** 한 등록에서 Evidence를 한 번 읽고 검증·추가·원자적 저장에 재사용한다. 새 이미지의 큰 `runtime_baseline`은 이미 불변 Pair에 있는 Mapping/Runtime/Scene/Camera 전체를 반복 저장하지 않고 Pair 경로·SHA를 참조한다. Project Reader는 이를 기존 완전한 이미지 관측 형태로 해석하고 저장 시 참조 형태를 유지한다. 예전 inline 항목은 그대로 읽고, 기존 파일 전체를 일괄 변환하지 않는다. 경로 이름과 Capture 원본은 유지한다.

따라서 parser 변경만으로 끝내지 않지만, 상위 YAML의 O(N) 비용 자체가 사라졌다고 주장하지 않는다. 100/1,000회 확장 크기·시간은 별도 측정한다. 이후 더 큰 규모에서 B의 append 인덱스/DB가 필요한지 실제 수치로 판단한다.

## 선택한 Capture 상태·실행 계약

연결 계약에는 `api-and-interface-design` 기준을 적용한다. 기존 `session_snapshot`에 선택적인 클릭 receipt 시각·촬영 정책을 추가하고 기존 빈 payload도 읽는다. UI와 Worker는 같은 호스트 monotonic clock을 사용한다. CameraReader의 이미 있는 최근90프레임 버퍼와 측정 q 이력에서 **요청 시각 이전의 가까운 관측**을 고른다. 늦게 도착한 요청을 현재의 새 프레임으로 바꿔 즉시 촬영이라고 표시하지 않는다. 실제 요청→프레임 차이와 receipt의 한계를 남긴다.

기본은 움직이는 순간도 보존하는 관측 Capture다. 0.6초 안정성은 정합 적격 여부에 사용하고, 움직임·워밍업·흐림·시각 차이가 큰 관측을 적격으로 자동 승인하지 않는다. 명시적인 정합 정책은 기존 안정성 조건을 요구한다. 측정 q·Raw·Mapping·100ms 시각 정합 검증은 유지한다.

기존 `snapshots.py`에 제한된 큐만 추가하고 새 Framework/Process Manager를 만들지 않는다. 진행 중 작업을 포함해 **최대4건**, Real RGB 원 배열 약7.03MiB(640×480×3×2×4)이며 IPC 복사·기존 CameraReader 버퍼 메모리는 별도다. **촬영 총횟수는4회로 제한하지 않는다. 아직 저장·Sim 처리·등록이 끝나지 않은 촬영4건을 동시에 받아두며, 하나가 끝나면 다음 촬영을 받을 수 있다.** Queue가 가득 차거나 같은 프레임뿐이면 명시적으로 거절한다. 접수한 작업을 조용히 버리지 않는다.

```text
클릭 → 요청 ID·시각 → 관측 확보 → 저장 대기
                              └→ 기존 Writer: 원본 저장
                                            ├→ Scene Prepare 등록
                                            └→ 기존 RenderProcess: 고정 q의 Sim
                                               → Writer: Pair/비교·등록
별도 제어 스레드: TELEOP_ACTIVE 유지 ──────────────────────
```

요청/관측 확보/저장 대기/원본 저장/Pair 처리/등록 완료/실패를 Capture별로 표시한다. 접수 ACK는 `accepted`, 최종 ACK는 기존 `completed/rejected`다. 원본 저장 전 Session이 죽으면 접수만으로 저장 성공이 아니다. 원본이 저장된 뒤 후처리 실패·Stop이 나면 해당 원본과 실패 위치를 남기고 명시 재개·기존 Reader로 복구할 수 있게 한다. Stop은 제어를 먼저 중지하고 저장 자식의 소유 작업을 정리한다. 안전 예외 후 자동 Teleop 재활성화는 없다.

## 구현·집중 검증 결과

### 구현한 실행 경계

`SessionClient.send`가 클릭의 monotonic 시각과 요청 ID를 R03에 전달한다. UI는 먼저 **촬영 요청**만 표시한다. Session의 `freeze_capture`는 기존 CameraReader 최근90프레임과 측정 q 이력180개에서 요청 이전 관측을 고정한다. 요청이 1초 이상 지연되거나 유효한 관측이 없으면 거절한다. 요청 후 새 프레임을 대신 찍지 않는다. 실제 센서 노출 시각은 알 수 없어 host receipt 시각이라는 출처를 유지한다. 기존 200ms 관측 age·100ms 이미지/q 차이 검사는 유지한다.

기존 `snapshots.py` 안의 `CaptureQueue`가 최대4건을 관리한다. 기존 spawn Writer는 한 개이고 원본 저장을 먼저 수행한다. Scene Prepare는 그 뒤 등록하고, Real/Sim은 같은 고정 q로 기존 RenderProcess에 요청한 뒤 Pair/Overlay/Difference와 등록을 수행한다. Frozen Sim PNG는 제어 Interpreter에서 디코딩하지 않고 경로·해시만 받아 Writer에서 읽는다. Live Preview의 디코딩과 카메라 표시 코드는 보존했다.

큐의 개수는 원본 저장·렌더·등록 중인 작업을 모두 포함한다. 5번째는 `Capture queue full`로 거절하고 원래 요청의 실패 행에 이유를 표시한다. 같은 카메라 sequence를 다시 쓰는 요청도 거절한다. 처리량보다 빠르게 계속 찍을 수 있는 무제한 큐는 아니다. 진행 중 4건의 Real RGB만 약7.03MiB이며 IPC 복사·최근 프레임 버퍼·Writer 후처리 메모리는 별도다. 완료 작업은 큐에서 빠지고 실패 작업은 원본 경로·실패 상태를 남긴다.

두 UI는 같은 요청 ID의 행을 갱신한다. **촬영 요청 → 관측 확보 → 저장 대기 → 원본 저장 → Sim/Pair 처리(Real/Sim) → 등록 중 → 등록 완료**를 구분한다. 원본 저장 전 접수·등록 전 원본 저장을 최종 성공으로 표시하지 않는다. 저장 중에도 큐에 공간이 있으면 Capture 버튼은 활성 상태다. 연결과 Teleop 상태를 Capture 진행 상태로 덮어쓰지 않는다. 화면 배치·카메라 분할·팝업·연결/안전 중지 버튼은 재설계하지 않았다.

일반 관측은 움직이는 순간도 보존한다. 예전 최대5초 안정 자세 대기를 하지 않으며, 0.6초 안정성·샘플 간격·프레임 포함 구간·흐림은 정합 품질 판정으로 남긴다. 부적격 관측은 이미지별 `eligible=false`와 사유를 기록한다. 명시적 `policy=calibration`은 요청 때 이미 안정된 관측을 요구한다. Legacy 빈 payload는 Session 수신 시각을 사용하고 `session_receipt_legacy`로 구분한다. 과거 Archive의 정책 필드가 없으면 기존 calibration 정책으로 읽는다.

### Evidence의 중복과 Reader 호환

조사한 Evidence 원본은 **1,592,257B, 세션12개, 이미지36개**다. 같은 JSON 직렬화 기준으로 이미지 목록1,060,808B 중 큰 Runtime Context가1,018,200B였다. 이는 YAML 파일의 바이트 비중과 직접 같은 수치는 아니지만 Mapping/Runtime/Scene/Camera를 이미지마다 반복한 비용을 보여준다.

새 Pair 등록에서는 `runtime_baseline_ref`에 Pair 경로/SHA·Sim 이미지 경로/SHA·카메라만 저장한다. 전체 Context는 불변 `pair.json`에 있으며 Reader는 Pair와 이미지 SHA를 검증하고 기존 `runtime_baseline` 필드를 복원한다. 같은 Pair는 한 읽기 안에서 재사용한다. 기존 inline 항목은 그대로 읽으며 자동으로 참조로 변환하지 않는다. `Project.read_evidence(resolve=False)`는 등록용 작은 원시 인덱스, 기존 `.evidence`는 소비자가 요구하는 전체 관측을 반환한다.

Capture 등록은 기존 Project lock 안에서 인덱스를 한 번 읽어 검증·추가·쓰기에 전달한다. `Project.write_evidence`를 기존 Evidence 작성 경로에 연결해, Reader에서 복원한 큰 Context가 다음 저장 때 다시 중복되지 않게 했다. 사진/관측/정합/Scene 연결 모듈의 해당 변경은 저장 함수 호출 교체이며 정합 수학 변경이 아니다. Pair 손상은 기존 Refit 소비자에서 `NEEDS_MORE_DATA / PAIR_SOURCE_MISMATCH`로 처리한다.

확장 시험에서 안전한 C YAML만으로는 1,000회 인덱스 읽기에 약1.91초가 남았다. 따라서 **파일 이름은 `evidence.yaml`로 유지하고, 새 인덱스 쓰기는 YAML 호환 compact JSON**을 사용한다. 기존 Reader의 JSON 경로와 원자적 임시 파일·fsync·replace를 재사용한다. Legacy 날짜처럼 JSON으로 표현할 수 없는 YAML 값은 안전한 YAML로 저장해 타입을 보존한다. JSON 또는 C 파서만 바꾼 것이 아니라 반복 파싱 제거와 Pair Context 중복 축소를 함께 적용했다.

이전 사진/Calibration/Builder/Reconstruction 소비자는 정규화된 필드로 읽는다. 새 참조를 가진 자료를 변경 전 코드로 되돌려 읽는 기능은 제공하지 않는다. 참조되는 Pair/이미지를 별도로 삭제하면 검증에 실패한다. 전체 인덱스 읽기·쓰기는 여전히 O(N)이고, 전체 관측 읽기에는 파일 SHA 검증 비용도 있다. 별도 DB나 새 폴더 계층은 만들지 않았다.

### 저장·등록 성능 전후

동일한 기존 Capture의 저장 RGB/q와 큰 Evidence를 각각 독립 진단 Project에 복사하고 실제 spawn Writer/Reader/등록을 실행했다. 프로세스 시작 시간은 아래에서 제외한다. 실제 카메라 촬영·Sim 엔진 실행은 아니다. 단회 측정이며 장시간 평균이나 실물 성능 보장이 아니다.

| 측정 | 시작 소스 | 개선 후 |
|---|---:|---:|
| 원본 저장·검증 `prepare` | 1,766.54ms | 120.03ms |
| Pair·검증·등록 `finish` | 9,151.36ms | 760.74ms |
| 합계 | **10,917.90ms** | **880.77ms** |
| Evidence 읽기 / 쓰기 | 6회 / 1회 | **1회 / 1회** |
| 개선 후 그 한 번의 Evidence 읽기 / 쓰기 | — | 366.83ms / 20.12ms |
| 개선 후 Pair/비교 이미지 생성 | — | 285.80ms |

이 Replay에서는 전체 약**12.4배**, 약**91.9%** 감소했다. 큰 기존 YAML을 처음 읽는366.83ms는 남아 있다. 개선 후에도 Pair 계산은 실제로 수행하며, 제거하거나 완료 상태를 앞당겨 시간을 만든 것이 아니다. `storage-before.json`, `storage-after.log`, `storage-result.json`이 근거다.

100/1,000회 확장 시험은 **새 촬영1회=Side/Wrist2장**의 메타데이터를 반복한 독립 인덱스다. 실제100/1,000회 촬영이나 모든 Pair/SHA를 복원하는 Reader 부하 시험이 아니다.

| 합성 촬영 수 | 이미지 수 | 새 인덱스 크기 | 원자적 쓰기 | 원시 읽기 | 반복하지 않은 Context(JSON 기준) |
|---|---:|---:|---:|---:|---:|
| 100 | 200 | 824,184B | 13.51ms | 8.73ms | 5,180,900B |
| 1,000 | 2,000 | 8,246,484B | 84.35ms | 45.74ms | 51,809,000B |

`scale-results.json`에 범위와 원 수치를 남겼다. 이 마지막 열을 사용자 디스크에서 이미 절약한 용량이라고 보고하지 않는다. 최초 탐색 중 세션 전체14장을 촬영1회로 세었던 결과는 `initial-overcount-*`에 보존하고 위 결과에서 제외했다.

### 연속 Capture와 제어 주기: 일곱 가지 시간을 분리

실제 Memory SDK·Session·제어 스레드·R03 명령/이벤트 파일·spawn Writer·Builder Reader를 연결했다. Real/Sim RenderProcess는 **합성 Sim RGB 응답**으로 대체했다. 두 Session 각각 약12초 동안 첫 등록 완료 전에 약100ms 간격의 요청3개를 전송했고, 추가 요청을 위한 Teleop 재시작은0회였다. 실물 연결·물리 Step·모델 Forward는0이다.

| 구간 | Scene Prepare: 3건 범위 | Real/Sim: 3건 범위 |
|---|---:|---:|
| ① 클릭 → Backend 접수 ACK | 133.41–196.96ms | 126.04–183.48ms |
| ② 클릭 → 요청 시점 관측 확보 | 63.27–105.58ms | 60.94–80.16ms |
| ③ 관측 확보 → 원본 저장·검증 완료 | 161.04–382.44ms | 207.18–379.87ms |
| ④ 원본 저장 → Sim/Pair 완료 | 해당 없음 | 551.83–1,106.35ms |
| ⑤ 클릭 → 전체 등록 완료 통지 | 1,049.19–1,278.41ms | 1,497.39–1,578.47ms |
| ⑥ 클릭 → 추가 접수 가능 상태 통지 | 173.12–244.40ms | 153.19–222.38ms |
| ⑦ Teleop 주기 p50 / p95 / 최대 | 33.47 / 34.05 / 141.08ms | 33.48 / 33.92 / 36.30ms |

①은 원본 저장 성공 ACK가 아니다. 로컬 UI의 촬영 요청 표시는 별도이고 실제 Qt→R03 계약 시험으로 확인했다. ⑥은 큐 상태 이벤트 시각이며 GUI의 실제 repaint 지연은 이 표에서 측정하지 않았다. 다음 클릭을 저장 완료까지 금지하지 않으므로 100ms 간격 접수도 가능했다. ④는 큐 대기·합성 응답·실제 비교 이미지 계산을 포함하며 실제 엔진 렌더 시간으로 보고하지 않는다. 원본 저장/Pair 시각은 Writer 내부 시각, 최종 통지는 부모 시각이다.

Scene Prepare357회, Real/Sim360회 제어를 수행했다. 요청 시각과 선택 프레임의 receipt 차이는 전체6건에서 **3.92–22.62ms**였다. 이후 프레임이 대신 선택되지 않는 것과 카메라별 보간 q가 등록에서도 보존되는 것을 별도 검사했다. UI heartbeat는 기존400ms 주기로 전달했다. Scene Prepare는 기존 Native Recorder의300행 저장도 실행했다. 기록 저장을 포함한 최대141.08ms 간격은 여전히 존재하며 hard real-time 보장으로 표현하지 않는다. `pipeline-results.json`과 두 `pipeline-*-final/result.json`이 근거다.

### Teleop 중단: 해결 범위와 미확정 원인

정상 Capture는 Session을 `CAPTURING`으로 바꾸거나 제어를 중지하지 않는다. PNG/해시/Evidence/비교 작업은 spawn Writer, Sim은 기존 RenderProcess다. 저장·등록 오류는 해당 Capture 실패로 남기고 정상 장치 연결과 기존 Teleop 허가는 유지한다. Memory 시험에서 실제 저장을 기다리거나 실패시켜도 제어 sequence가 계속 증가했다.

Device 오류·100ms freshness 오류·200ms gap/deadline·명시 Stop·heartbeat 소실의 기존 안전 중지는 보존했다. 실제 Memory 제어에120ms 지연을 주면 freshness 오류로 중지하고, 그 후 저장이 끝나거나 실패해도 자동 재활성화하지 않는 것을 두 Session에서 검사했다. `supervised.py`, `teleop_loop.py`, `devices.py`, `control.py`, `calibration.py`는 이번 시작 SHA와 같다.

과거 실물 R03 기록 `c5d5391b446945ddba4934e3adfc0d68`에서는 Capture 시작seq4812 뒤4815에서 활성 해제,4816에 freshness 오류,4846에 완료가 있다. Capture 밖seq11963에도 gap/heartbeat 중지가 있었다. 이 기록은 현재 spawn Writer 분리 전의 실행이다. **USB read/write·OS scheduling·GIL 중 어느 함수가 그 실물 지연을 만들었는지는 UNKNOWN**이다. 현재 Memory 성공으로 과거 원인을 확정하거나 앞으로 모든 실물 중단이 없다고 보장하지 않는다. Preview decode·R03 파일 이벤트·Native 제어 기록은 여전히 제어 Interpreter와 일부 자원을 공유한다. 안전 제한시간을 늘리거나 오류를 숨기는 자동 재시작은 추가하지 않았다.

### 실패·중단·재개

- 원본 저장 전 실패: 요청은 실패이며 부분 파일이 있으면 경로를 남긴다. 완료 Manifest가 없는 자료를 성공 등록하지 않는다.
- 원본 저장 후 Pair/등록 실패: 봉인된 원본을 보존하고 실패 단계·경로를 `pending_captures`에 남긴다. 기존 `pending_snapshot`도 첫 미완료 건으로 유지한다.
- 같은 Session의 `session_import`: 저장한 같은 요청을 명시 재시도한다. 현재 q나 새 프레임으로 대체하지 않는다. Renderer 자체가 실패하면 자동 재기동하지 않는다.
- Session 종료: 제어·장치를 먼저 중지한 뒤 이미 소유한 Writer 작업을 회수한다. 미등록 작업은 실패/보존 상태로 남기고 Writer를 join한다. UI도 최종 확인 없는 행을 완료로 표시하지 않는다.
- 세션 종료 후 봉인된 Archive는 기존 SnapshotStore의 명시 복구로 등록할 수 있다. SHA·Project·Dataset ID를 검사하며 이미 등록된 자료는 거절한다. Raw-only이면 Pair 없는 관측으로 등록하고 Sim을 만들어 넣지 않는다. 자동 검색·일괄 복구는 추가하지 않았다.

다음은 운영자가 **미등록 봉인 경로를 확인한 뒤** 사용하는 API 예다. 사용자 원본에 이 명령을 실행하지 않았다.

```python
from real2sim_builder.project import Project
from robot_learning_workbench.robot.snapshots import SnapshotStore

result = SnapshotStore.recover(Project(PROJECT_ROOT), SEALED_CAPTURE_DIRECTORY)
```

등록 후 scratch 정리 실패가 정상 Pair를 삭제하거나 실패로 바꾸지 않도록 경고로 분리했다. Sim 완료 뒤 Writer 제출이 실패하는 경우에도 큐를 비우고 원본을 보존한다. 강제 프로세스 종료/전원 장애가 원본 디스크 저장 전에 발생하면 메모리에 접수한 관측까지 보장할 수 없다. 요청 접수와 내구성 있는 저장을 구분한 이유다.

### 집중 테스트와 실제 변경 파일

초기 RED는 두 화면의 두 번째 요청 거절과 Evidence 반복 읽기, 움직이는 관측 거절, 손상 Pair의 기존 Consumer 상태 계약, 느린 YAML 인덱스, 세션 종료 후 복구 API 부재로 재현했다. 원래 오류·중간 수정 기록은 진단에 보존한다.

마지막 집중 묶음 **81 passed / 실패0 / 오류0 / skipped0, 22.56초**다(`release-focused.xml/log`). 이후 봉인 원본 복구와 Frozen PNG의 경로 전달→Writer 소비를 확인한 **2 passed / exit0, 2.71초**가 있으며 이 중 복구1개는 앞 묶음과 겹친다. **고유 시험82개**이고 반복 RED/GREEN 실행을 합산하지 않았다. 새 통합 시험은 실제 RenderProcess 생성자를 호출하지 않고 PNG 운반/소비만 검사했다.

범위는 Evidence 등록/Legacy Reader·센서 ID·Refit Pair guard, 두 Session의 연속4건/5번째 거절, 요청 시점 고정, 실제 spawn 저장·GIL 지연·안전 중지, 원본 보존·rename 뒤 실패/재개, R03 ACK, 두 UI 상태·행 갱신이다. Qt는 **offscreen**이며 Object Library 창·실제 GPU Viewer·전체 엔진·AI를 실행하지 않았다. **전체 회귀는 하지 않았다.**

이번 시작 소스 대비 Python 수정25개·신규3개·삭제0개다. 기존 미커밋 변경 전체와 구분한다.

| 소유 경로 | 파일 / 변경 책임 |
|---|---|
| `real2sim_builder/src/real2sim_builder/` | `files.py`, `project.py`: 안전한 읽기·작은 인덱스 저장 / `capture.py`: 단일 읽기·Pair 참조·Legacy/관측 정책 / `automation.py`: 손상 참조의 기존 Consumer 진단 |
| 같은 Builder 경로 | `evidence.py`, `observations.py`, `calibration/geometry.py`: 기존 Evidence 쓰기를 `write_evidence`로 연결 |
| `robot_learning_workbench/src/robot_learning_workbench/robot/` | `capture.py`: 요청 시점·관측 정책 / `snapshots.py`: 기존 Writer·큐·상태·복구 / `session.py`, `real_sim.py`: 두 Session 연결 / `render_transport.py`, `pairs.py`: Frozen PNG 디코딩을 저장 소비자로 이동 / `scene_observation.py`: Evidence 저장 연결 |
| `robot_learning_workbench/src/robot_learning_workbench/` | `run.py`: 선택적 요청 시각·정책·accepted ACK / `scene_preparation.py`, `scene_migration.py`: Evidence 저장 연결 |
| 같은 Workbench `ui/` | `session_client.py`, `session_page.py`, `real_sim_page.py`, `snapshot_table.py`, `view.py`: 요청·큐·완료·실패 상태만 연결 |
| 기존 시험 | Workbench `test_capture_save_continuity.py`, `test_capture_workload_isolation.py`; Builder `test_refit_capture_selection.py` |
| 신규 시험 | Workbench `test_capture_request_queue.py`, `test_capture_evidence_batch.py`, `test_capture_queue_ui.py` |

문서는 이 보고서와 이전 조사 문서의 후속 링크다. 제품은 진단 폴더를 import하지 않는다. Bytecode를 만들지 않는 compile 및 `git diff --check`를 확인했다. 기존 CameraView/LiveCameraView와 R03 `_monitor`/`read_status`의 AST도 시작과 같다.

### 원본 보호·사용 전 확인·남은 한계

시작 ledger에 넣은 **선택 원본35개**의 SHA/크기를 재대조해 변경·누락0을 확인했다. 기존 큰 Evidence, 조사한 Capture RGB/q/Manifest·모델 의존 파일·과거 R03 기록이 포함된다. 전체 Scene/Asset/Conda/Cache의 전수 대조라고 주장하지 않는다. 독립 진단 Project만 쓰고 사용자 Scene·Calibration·Rig/URDF를 수정하거나 일괄 이전하지 않았다. HEAD·브랜치·Git index는 시작과 같다. 설치·다운로드·Commit/Push·Reset/Clean은 하지 않았다.

실행 중인 UI/Session은 새 코드를 자동으로 읽지 않으므로 앱을 다시 시작해야 적용된다. 실물 검증은 별도 지시 후 Side/Wrist 스트림·실제 USB 제어에서 연속 Capture와 로그를 확인해야 한다. 실제 MuJoCo/Isaac Pair 렌더 부하는 이번 합성 응답 시험으로 보장하지 않는다. 상위 인덱스의 O(N), 큐4건의 backpressure, 실물 제어 타이밍, Native Recorder/Preview의 잔여 공유 비용은 유지되는 한계다. 이번 결과는 **구현·Memory 통합 검증 완료**, **실물 연속성 NOT_VERIFIED**로 구분한다.

진단은 Git 제외 `workbench_runs/diagnostics/capture_pipeline_improvement_20261117_001/` 한 곳에 둔다. `source-before`, 시작 diff/index/SHA, `selected-originals-before.json`, `storage-before.log`, `boundary-red.xml/log`가 시작 근거다. 제품은 이 폴더에 의존하지 않는다.

## 후속 Git Checkpoint 범위

2026-11-18 사용자 지시로 현재 브랜치에 Capture 개선을 게시한다. 앞선 절의 HEAD/미커밋 보존 수치는 구현 작업 종료 당시 기록이다. Checkpoint에는 이번 개선과 필요한 기존 spawn Writer·손실 없는 빠른 PNG·Capture 화면/팝업 연결·제어 타이밍 진단을 포함한다. 같은 파일에 섞인 Reconstruction·Robot Rig 선택 등의 변경은 분리해 로컬에 남긴다. 사용자 원본, 진단/Runtime 디렉터리, 모델·Cache·장치 Calibration 파일·인증·개인 설정은 포함하지 않는다.

새 설치는 저장소의 Builder/Workbench 환경과 별도 Qt Interpreter가 필요하다. 검증에 사용한 로컬 `docs/evidence/` 자료와 `workbench_runs/runtime/qt/`는 Git에 포함되지 않는다. 기존 테스트의 동결 모델/장치 메타데이터 의존성은 유지하므로 새 Clone에서 이번 로컬82개 결과가 자동으로 재현된다고 주장하지 않는다. 테스트용 SDK Calibration은 기존 동결 Profile의 값/해시에서 임시 디렉터리로 복원하며, 사용자 Calibration JSON 복사본을 새로 게시하지 않는다. 실제 로봇 설정으로 사용하는 파일은 아니다.

Checkpoint 후보 **45개 파일**을 별도 Git Tree로 구성해 혼합된 로컬 코드와 분리하고, 그 코드에서 Capture·Teleop 집중 시험 **95 passed / 실패0 / 오류0 / skipped0, exit0, 25.73초**를 확인했다. 앞선82개와 중복되므로 합산하지 않는다. 새 DB·추론·하드웨어·전체 회귀는 실행하지 않았다. Reconstruction/Rig 변경은 같은 파일 안에서도 제외했으며, 테마는 Capture 버튼이 의존하는 아이콘 함수만 포함한다. 게시할 변경에서 인증값 패턴과1MiB 초과 파일은 발견되지 않았고 `git diff --check`를 통과했다. 선택 목록과 실제 테스트 명령/종료 코드는 Git 제외 `workbench_runs/diagnostics/capture_git_checkpoint_20261118_001/selection.json`, `selected-focused-exit.json`에 있다.
