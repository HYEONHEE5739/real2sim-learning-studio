# Real/Sim DISCONNECTED — Isaac 렌즈 스키마 초기화 수정

2026-11-18. 먼저 Native/Capture 개선 41개 파일을 `8d5e219233e367fccfa6b7e2765aecbdbe50e32b`로 Commit/Push했고 현재 브랜치의 원격 SHA 일치도 확인했다. 사용자의 후속 DISCONNECTED 조사·수정은 그 뒤 별도로 진행했으며 **아래 수정은 로컬 미커밋 상태**다. 이전 미커밋 작업은 보존했다.

## 실제 종료 원인

최근 실패한 `real_sim_20261118_05`, `_06`의 Engine은 Isaac이다. 두 Session 모두 동일한 오류로 끝났다.

```text
Scene render failed: NOT_SUPPORTED: native OpenCV pinhole schema unavailable
```

`session-report.json`에는 Leader/Follower 연결과 실제 Frame 수신 기록이 있다. 첫 Sim 영상은 없고 `teleoperation_activation=null`, Capture 0건이다. **Isaac Camera의 초기화 예외가 Render Child에서 부모 Session으로 전달되고, 안전 정리 절차가 장치를 닫으면서 DISCONNECTED가 된 경우**다. 같은 날 `_04`의 MuJoCo Session은 Capture 10건, error 없음으로 구분된다.

| 기록 | 렌더 설정 생성, 한국 시각 | Render 오류 기록 | Session 종료 기록 |
|---|---|---|---|
| `_05` | 09:29:57.538 | 09:30:42.724 | 09:30:50.723 |
| `_06` | 09:31:49.933 | 09:32:26.606 | 09:32:34.468 |

이 시각은 파일 기록 시각이다. Worker 내부 연산 시간으로 해석하지 않는다. 이번 오류는 첫 Sim 영상 이전의 초기화 실패이며, 앞서 조사한 Capture Queue의 13초 처리시간과 별개다.

## 근본 원인과 재현

설치된 Isaac Sim 5.1의 `OmniLensDistortionOpenCvPinholeAPI` 리소스는 존재했다. 기존 코드가 이 플러그인을 첫 USD Stage보다 먼저 등록하지 않았다. USD SchemaRegistry가 초기 정의를 구성한 뒤에는 뒤늦은 플러그인 등록으로 해당 API를 사용할 수 없었다.

같은 Interpreter·같은 설치·같은 메모리 Camera·같은 K로 검사했다. Kit/로봇/실제 Camera는 이 재현에 필요하지 않았다.

| 변경한 한 가지 조건 | 실제 USD 결과 |
|---|---|
| 사전 등록 없음 | 같은 `native OpenCV pinhole schema unavailable` 재현 |
| 첫 Stage 생성 후 등록 | 같은 오류 재현 |
| 첫 Stage 생성 전 등록 | API 적용 및 비대칭·비중앙 K readback 통과 |

원래 Camera 계약 시험은 수집 단계에서 시험 코드가 직접 플러그인을 등록했으므로 실제 Render Worker의 등록 누락을 잡지 못했다. 새 시험은 **새 프로세스에서 실제 Worker 진입 함수를 호출**해 App/Package가 첫 Stage를 만드는 순서를 재현한다. Kit 실행 경계만 대역으로 바꾸고 USD Schema/Camera/K 적용은 실제 API를 사용한다.

근거는 [OpenUSD SchemaRegistry](https://openusd.org/dev/api/class_usd_schema_registry.html), [NVIDIA 렌즈 스키마](https://docs.omniverse.nvidia.com/kit/docs/omni.usd.schema.omni_lens_distortion/latest/index.html), [Isaac Sim 5.1 Camera](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/sensors/isaacsim_sensors_camera.html) 및 설치된 SDK의 Camera 구현이다. 공식 문서의 API와 로컬 설치의 이름이 일치함을 확인했다. 초기화 순서의 영향은 위 실제 재현으로 확인했다.

## 수정

- `engines/isaac/env_cfg.py`: 기존 설치의 배포 메타데이터로 렌즈 USD 리소스를 찾는 `prepare_camera_schema()`를 추가했다. 명시적으로 호출한 Child에서만 등록하며 Kit/장치/모델을 초기화하지 않는다. 누락·중복 설치는 `NEEDS_RUNTIME`으로 거부한다.
- `robot/render_worker.py`: Isaac일 때 AppLauncher와 Scene 로딩보다 먼저 등록한다. `startup_times_ns.camera_schema_registered`를 남긴다. MuJoCo 경로는 바꾸지 않았다.
- Builder `stage_workers.py`: Native Isaac Stage14도 Package parser가 첫 USD Stage를 열기 전에 같은 준비 함수를 호출한다.
- 신규 `test_isaac_schema_bootstrap.py`: 실제 Worker/Stage14 순서, 반복 호출 시 Camera 불변, Runtime 누락의 명시 실패를 검사한다.
- 기존 `test_isaac_camera_intrinsics.py`: 생성자를 생략하는 한 Metadata fixture에 현재 NativeRenderer가 요구하는 Joint Limits/Projection 입력을 채웠다. 제품의 Limit 검사를 완화하지 않았다.

K·Camera Calibration·URDF·Scene·Joint Mapping을 바꾸지 않았다. `CanApplyAPI` 실패를 숨기거나 기본 중앙 K로 대체하지 않는다. Session 오류 시 안전 종료와 100ms Freshness·Stop·Heartbeat·제어 Deadline도 그대로다. 특정 Scene ID나 Asset에 대한 예외 처리는 없다.

## 검증 결과와 한계

새 Worker 및 Stage14 시험은 수정 전 각각 RED를 확인하고 수정 후 GREEN을 확인했다. 신규 시험 4개와 직접 관련 기존 시험을 합쳐 **고유 31개가 최종 통과**했다. 기존 묶음은 26개 통과·fixture 누락 1개 실패였고, 그 1개를 수정 후 별도로 통과시켰다. 전체 회귀는 실행하지 않았다.

실제 Kit/RTX에는 독립 합성 Cube·Camera만 생성했다. 원래 스키마 오류 없이 RGBA `[480,640,4]` 영상을 생성했고 8프레임 갱신 뒤 K readback도 원래 수치였다. Shader 영상 생성까지 약 **10.17초**다. 이 수치는 실물 Real/Sim 전체 연결 시간이 아니다. 영상의 독립 Metric Calibration이나 사용자 Scene 정합을 인증하지 않는다.

**Kit Smoke 전체 프로세스는 정상 종료하지 못했다.** Frame 생성 후 `SimulationApp.close()`의 `omni.usd` 감시기 정리에서 대기하는 스택을 확인했고, 소유한 테스트 프로세스만 45초 제한과 5초 정리 유예 뒤 종료했다. GPU 메모리가 기준선 수준으로 반환되고 잔존 테스트 Child가 없음을 확인했다. 따라서 결과 JSON의 `FRAME_RENDERED`를 전체 실행 `PASS`로 승격하지 않았다. 기존 제품 RenderProcess의 유한 종료/TERM/KILL 경계는 유지했다.

중간 GPU Harness에는 SDK Camera 확장 미로드 오류와 Orchestrator 대기도 있었다. 이를 로그에 보존한 뒤 실제 제품 Camera와 같은 Replicator RenderProduct/Annotator 계층으로 직접 확인했다. 설치·SDK 소스 수정·다른 Renderer 대체는 하지 않았다. 실제 영상과 종료 실패를 구분한다.

기존 실패 로그와 이번 Kit 실행에는 대량의 `Failed to create change watch ... ENOSPC`도 있다. 조회 당시 디스크는 약 33GB 여유, `max_user_watches=65536`이다. 감시 리소스 문제와 스키마 오류를 동일 원인으로 단정하지 않는다. 스키마 오류는 파일 감시를 사용하지 않는 USD만으로도 재현됐다. 호스트 전역 sysctl이나 다른 사용자 프로세스는 변경하지 않았다.

**수정한 스키마 초기화 결함은 재현·회귀 검사로 해결을 확인했다. 실물 재연결, 사용자 Scene의 네 영상, Teleop 연속성 및 SDK의 정상 종료까지 완료한 상태는 아니다.** 자동으로 장치를 다시 연결하거나 Teleop을 시작하지 않았다. 사용자 UI에서 다음 연결을 만들면 새 Render Child가 수정된 초기화 코드를 읽는다.

## 원본·미커밋 작업 보존

이번 조사 시작의 Python 317개 SHA와 대조해 위 제품 3개와 기존 fixture 1개만 변경됐음을 확인했다. 신규 파일은 집중 시험과 이 보고서다. 변경 Python 5개를 bytecode 없이 compile했고 `git diff --check`도 통과했다. HEAD는 Push한 `8d5e219`이며 Index는 비어 있다. 다른 미커밋 구현은 수정하지 않았다.

이전 Native/Capture 작업의 보호 ledger 19,490개와 현재 파일 19,820개를 다시 비교했다. 누락 0개, 기존 19,489개는 SHA/크기가 같다. 차이는 `pickplace-colorblock/input/evidence.yaml` 1개와 Capture 파일 330개 추가다. 추가 파일은 기존 `real_sim_20261118_04` 10건과 `session_20261118_02` 5건에 속한다. 가장 늦은 추가 파일 기록은 09:33:20.154, Evidence 기록은 09:33:20.272로, 이번 조사 baseline 생성 09:36:25.500 이전이다. 따라서 이전 작업의 “신규 0”을 이번 조사에 그대로 인용하지 않는다. 이 사용자 촬영 자료는 그대로 보존했으며 이번 재현은 별도 진단 폴더에만 썼다. 전체 SDK/모델 디스크를 전수 SHA 대조한 것은 아니다.

진단은 Git 제외 `workbench_runs/diagnostics/real_sim_disconnect_20261118_001/`의 `session-findings.json`, `schema-*-*.log`, `schema-early.log`, `schema-late.log`, `bootstrap-red.xml/log`, `stage14-red.xml/log`, `bootstrap-contracts.xml/log`, `focused-existing.xml/log`, `metadata-fixture-green.xml/log`, `focused-summary.json`, `kit-camera-smoke.log`, `kit-camera-result.json`, `kit-synthetic-camera.png`이다. 최초 GPU Harness 실패와 종료 Timeout 로그도 보존했다. 제품은 이 진단 폴더를 읽지 않는다.
