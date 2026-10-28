# 구현 작업 목록

2026-10-26 최종 C Native 전환: [구현·검증 보고](../docs/native-dataset-transition.md). 사용자 확정에 따라 자체 Episode별 HDF5/Index/Descriptor/Migration을 제거하고 공식 불변 HDF5 segment + 최소 Metadata·영구 Curation·명시 LeRobot materialization으로 교체했다. NATIVE-01/02/03의 파일·공식 CPU 소비자 관문을 검증했다. 과거 D/R/RO 보고서·증거는 보존한다. 당시 BU/E·실물·UI·Trainer는 범위 밖이었으며 이후 진행 상태는 아래 체크를 따른다.

상태: **B00~B03·S01/S02·T01~T04·D01~D04(C Native 대체)·R01~R03·RO01~RO03의 해당 범위 및 BU01~BU04·E02/E05 기반 완료**. 실물 검증은 미완료다. E01은 실제 물리 기반과 q/qd/접촉 복구를 확인했으나 cube–cup 물체 잔차1.197188790mm가 OPEN이다. E03/E04 및 E06-b/c는 [이번 결과](../docs/simulation-workflows-bundle.md)의 기본 단일 env/Fixed/단일 Isaac Annotation Episode 범위까지 실제 검증했고, 남은 관문 때문에 전체 체크는 보류한다. L03 Dataset 소비자/지원 Merge와 L01 ACT smoke Training/Resume·L02 ACT Policy/독립 Validation을 검증했다. 설치 원 SmolVLA0.4.1의 SMOL-PAD-01은 보존하며, 이번 명시 scoped patch의 실제 학습/Resume·양 엔진1/4-env 검증은 문서 끝 확장 결과를 따른다. P01은 현재 Scene/ACT/단일 env/Fixed의 양 엔진 Rollout·기록·Resume를 검증했으며 C01/C02의 읽기 전용 검토·분포·Revision·Export도 검증했으며 P02/P03·L04는 미착수다. 최신 UI/X01의 승인 범위와 실제 부분 완료는 문서 끝의 UI 결과를 따른다. 아래 작업별 체크와 증거가 현재 상세 상태의 기준이다. [계획](plan.md)의 실제 하위 기능 의존성을 적용하며, 작업 번호를 전체 직렬 실행 순서로 취급하지 않는다. 실물·미검증 기능을 시험 완료로 표시하지 않는다.

P/B 원본은 읽기 전용이다. 파일 범위는 기존 architecture.md 경로를 축약했으며 새 계층을 뜻하지 않는다. 시험 파일 포함 약 5개를 넘는 작업은 착수 전 하위 작업으로 나눈다. 장치/Hub 시험은 허용된 외부 효과 범위에서만 실행한다.

- [x] **B00 — 기존 파일·버전·UI/CLI·외부 자산 inventory** ([공통 조사](plan.md))
  - 선행: —.
  - Files: 문서/조사 결과만.
  - Acceptance / Verify: 원본 hash·실제 호출 위치·실행 부수 효과 기록, 원본 변경 없음.
  - 결과: [조사 보고서](../docs/b00-inventory.md), [검증 증거](../docs/evidence/b00/verification.json). 56,100개 파일 stat·13,554개 선택 SHA-256 대조 변화 없음; v8 92개/Builder Export 264개 등록 파일 일치. 런타임·장치 시험은 미실행이며 B01 이후 작업/OPEN 확인 항목은 완료 처리하지 않음.

- [x] **B01 — 엔진별 stage trace·순수 판정 fixture 확보** ([공통 Baseline](plan.md))
  - 선행: B00.
  - 개발 기준: 기존 Sim5.1/Lab2.3/LeRobot0.4.1/MuJoCo3.3.7 유지. 최신 버전 조사는 참고 자료로 전환. 이번 B01은 실물 없이 별도 공간에서 실행한다.
  - Files: 별도 baseline 결과/증거.
  - Acceptance / Verify: V8-01/02/03 관련 입력·시점·경계·변동 기준 확보.
  - 결과: [B01 보고서](../docs/b01-baseline.md), [검증 증거](../docs/evidence/b01/verification.json). 양 엔진 네 단계 대표 실행·반복 및 29개 기존 시험 통과. Isaac DataGen strict IK 실패와 Isaac Evaluation 반복 차이를 Baseline으로 보존; 전체 기능 정상화 완료를 뜻하지 않음. 원본 56,100개 stat·14,209개 선택 SHA 변화 없음. 다음 작업 미착수.

- [x] **B02 — Episode/Resume 호환 표 작성** ([공통 자료 확인](plan.md))
  - 선행: B00.
  - Files: DATA-01/03·V8-04 조사 결과.
  - Acceptance / Verify: dtype/shape/관측·명령·영상·초기 상태·partition/RNG 매핑.
  - 결과: [B02 보고서](../docs/b02-episode-resume.md), [검증 증거](../docs/evidence/b02/verification.json). 대표 HDF5 17개 첫 Episode·612개 배열·영상/계약 검사, 원래 Resume/partition/lineage 25개 관찰, Canonical 9개 폴더와 seed/history 규칙 확인. 누락 정보·IK 기본값 대체·검증 전 복사 호출은 새 계약에서 구분/차단한다. 실제 변환·새 Writer/Resume·시뮬레이터 실행 없음; B01의 Isaac 실패/비결정성 유지. B03 이후 자동 착수 안 함.

- [x] **B03 — Calibration·장치 계약 확인** ([조사 결과](../docs/b03-calibration-device.md))
  - 선행: B00.
  - Files: CAL-01/02·ROBOT-01/02 조사 결과.
  - Acceptance / Verify: [증거](../docs/evidence/b03/verification.json). 기존 오프라인 시험 75개, Camera/Device probe 각 23개, 실제 프로필 60표본·12거부·6관절 baked 회전 대조. SDK 예외 시 torque 재활성화·cleanup/port 해제 제약 기록. 실물/엔진 신규 실행은 미수행이며 CAL/ROBOT 후속 검증 OPEN. 원본/B01/B02 불변, 다음 작업 미착수.

- [x] **S01 — 패키지 JSON·ID·hash 검사** ([결과](../docs/s01-scene-package.md))
  - 선행: B00.
  - Files: package.py + test_scene_package.py.
  - Acceptance / Verify: scene-package-AC01/03; 이동/누락/변조/외부 증거 구분.
  - 결과: 75개 pytest 통과·실제 의존 파일 6개/8개 probe·wheel build/isolated import 통과. [증거](../docs/evidence/s01/verification.json). AC01/03의 파일/상태 부분만 완료. native closure/엔진 로딩·S02 frame/보정 적용 계산은 미완료이며 원본/B01~B03 보존. 다음 작업 자동 착수 안 함.

- [x] **S02 — Transform·보정 적용 관계 검사** ([결과](../docs/s02-frames-calibration.md))
  - 선행: B01/B03의 좌표 의미.
  - Files: transforms.py, package.py + 대응 시험.
  - Acceptance / Verify: scene-package-AC02/03; 계산·방향·중복 적용 경계.
  - 결과: [증거](../docs/evidence/s02/verification.json). 전체 138개 pytest·실제 v8 수치/경계 35개·Calibration 패키지 9개·wheel 검증 통과. reference graph/current 구분, 기존 곱/역행렬·Quaternion convention, dependency/단계/모델·정확한 mapping binding·중복 선언 차단. Export/엔진/실물 실행은 미수행, 원본/B01~B03/S01 보존. 다음 작업 자동 시작 안 함.

- [x] **T01 — Task 등록 선언·검증** ([결과](../docs/t01-task-registry.md))
  - 선행: B00.
  - Files: registry.py, task_modules.yaml + test_task_registry.py.
  - Acceptance / Verify: task-functions-AC03의 오프라인 부분. [증거](../docs/evidence/t01/verification.json): 신규 97개 + Scene 회귀 138개 = 235개 통과, wheel/isolated import·임시 모듈만 추가한 일반 함수 연결 통과. 원본·B01~S02 증거와 scene_contract 소스 불변. 기본 목록은 비어 있으며 T02 판정·실제 엔진/Recipe/UI 연결은 미착수. 다음 작업 자동 시작 안 함.

- [x] **T02 — v8 판정·상태 함수 이관** ([결과](../docs/t02-pick-place.md))
  - 선행: B01의 판정 fixture.
  - Files: pick_place.py + test_pick_place.py.
  - Acceptance / Verify: task-functions-AC01의 순수 계산/경계·기록 phase 부분. [증거](../docs/evidence/t02/verification.json): 전체 307개(신규 72), B01 실제 grasp 2,618회·Placement 13개 exact, 기존 Torch CPU float32 13개·접촉 9개·등록/wheel 통과. 판정 tick/저장 frame 차이와 Source/Evaluation 의미 유지. 배치·Recipe·UI·엔진 연결 미착수; 다음 작업 자동 시작 안 함.

- [x] **T03 — Fixed/Random·v8 배치** ([결과](../docs/t03-placement-reset.md))
  - 선행: B01의 V8-03, S02.
  - Files: placement.py + test_placement.py.
  - Acceptance / Verify: AC02의 v8 부분. [증거](../docs/evidence/t03/verification.json): 전체 348개(신규 41)·기존 81 batch/14 pose 경계/RNG·1000회·per-env seed·wheel 통과. four_anchors 제외·Fixed 선행 간격 검사 구분. T04/Recipe/Writer/UI/엔진 연결 미착수, 다음 작업 자동 시작 안 함.

- [x] **T04 — 일반 Geometry 접촉 배치** ([결과](../docs/t04-collision-contact.md))
  - 선행: T03·S01/S02.
  - Files: placement.py + test_contact_placement.py.
  - Acceptance / Verify: AC02의 지원 다면체/convex 평면 범위, AC03 등록. [증거](../docs/evidence/t04/verification.json): 전체 401개(신규 53), v8 81 batch/14 경계 및 실제 box 9개 비교·wheel·보존 대조. 입력 frame/회전·복합 형상·예산 검증. 곡면 primitive/비평면 support/native 변환 미지원; 물리 충돌·Recipe/Writer/UI/엔진 Reset 미검증. 다음 작업 자동 시작 안 함.

- [x] **D01 — 새 reader·변환 매핑** ([묶음 결과](../docs/episode-data-bundle.md))
  - 선행: B02.
  - Files: data/native.py·curation.py·lerobot.py + Native 시험 (최종 C 전환, 과거 D 코드 제거).
  - Acceptance / Verify: episode-data-AC01; 원본 불변 및 필요한 필드 누락 보고.
  - B02 근거: 실제 612개 leaf 대응·dtype/단위/phase를 사용한다. Isaac 요청값 부재·저장 target/engine cast·initial 속도 근거·snapshot 소유권·manual/auto/final event를 보존하며 없는 값을 만들어 채우지 않는다. Common 17개/612 배열·Canonical 9개/104 배열과 영상 bytes 보존을 실제 변환으로 검증했다. [Task 증거](../docs/evidence/episode-data/task-results.json). 엔진 재생은 후속 범위다.

- [x] **D02 — 영상·buffer·commit** ([묶음 결과](../docs/episode-data-bundle.md))
  - 선행: D01·DATA-02 시험 기준.
  - Files: data/native.py·video.py·lerobot.py + Native commit/영상/강제 종료 시험.
  - Acceptance / Verify: episode-data-AC02의 로컬 파일 관문 통과. 응답 유실/디스크·수치·영상 오류, publish/index 전후 os._exit/SIGKILL·고아 보고·동일/다른 payload 검증. [증거](../docs/evidence/episode-data/task-results.json). 전원/NFS·엔진 통합 미검증.

- [x] **D03 — Resume·참조 export** ([묶음 결과](../docs/episode-data-bundle.md))
  - 선행: D02·V8-04.
  - Files: data/native.py·curation.py + identity/attempt/영구 선택/독립 Export 시험.
  - Acceptance / Verify: episode-data-AC03 파일 범위 통과. exact identity/partition·IK/history/seed·새 출력 참조·chain 평탄화/이동/독립 Export. 실제 Source/DataGen loop 재개는 미검증. [증거](../docs/evidence/episode-data/task-results.json).
  - DataGen 보완: 고정 DLS + Best Effort identity·파라미터·안전 조건 비교. 과거 SciPy/Strict/Hold 또는 불명 IK run은 continuation 거부하며 과거 provenance는 보존한다.
  - B02 근거: SciPy + Best Effort도 신규 DLS와 다른 계약이다. IK 누락 기본값 대체·code identity 미검사를 이관하지 않고 history/호환 검사를 복사·commit 전에 완료한다. Source discard/RNG 한계·DataGen max(history.attempt)/전역 budget·실제 source pool 순서와 기존에 없는 Annotation/Evaluation continuation을 구분한다.

- [x] **D04 — 저장 부하·소비자 회귀** ([묶음 결과](../docs/episode-data-bundle.md))
  - 선행: D02.
  - Files: episode 시험/측정 문서.
  - Acceptance / Verify: DATA-03/04 파일 소비자·대표 부하 관문 통과. 실제 5/50 Episode 및 404 frame×2 camera 640×480 측정. 새 검증 경로가 느린 비용도 보고했다. 전체 회귀 506개·skip 0·wheel/보존 PASS. [측정](../docs/evidence/episode-data/load-results.json). 공식 L03/Curation·실제 엔진 부하 미검증; 두 번째 묶음은 자동 시작하지 않음.

- [x] **R01 — YAML 파싱·stage 검증** ([묶음 결과](../docs/recipe-execution-bundle.md))
  - 선행: B00.
  - Files: recipe.py + test_recipe.py.
  - Acceptance / Verify: AC01의 선언 검증 통과. unknown/중복/type/비유한/tag/alias·단계별 engine/역할·IK 선택 거부, canonical Recipe 경로. [Task 증거](../docs/evidence/recipe-execution/task-results.json).
  - DataGen 보완: `ik_solver`/`ik_failure_policy`·수치 override는 시작 전 필드 오류. 옵션이 없는 YAML에 고정 DLS + Best Effort 적용; 선택값을 다른 위치로 옮겨 노출하지 않는다.

- [x] **R02 — 준비·정확한 입력 identity** ([묶음 결과](../docs/recipe-execution-bundle.md))
  - 선행: R01·S01/T01 해당 참조만.
  - Files: recipe.py, cli.py + test_recipe.py.
  - Acceptance / Verify: AC01/03의 준비·CLI 부분 통과. Scene/Task/Episode/입력 SHA·object 순서·단일 signal dependency·변경 검사·공식 config 중복 output 검사. 공식 Trainer resume는 L01 검증 대기이며 덮어쓰지 않음. [증거](../docs/evidence/recipe-execution/task-results.json).

- [x] **R03 — worker claim·IPC·중지** ([묶음 결과](../docs/recipe-execution-bundle.md))
  - 선행: R01.
  - Files: run.py, cli.py + claim/protocol 시험.
  - Acceptance / Verify: AC02/03 로컬 프로세스/IPC 부분 통과. 동시 claim·출력 중복·spawn/worker 불명·ACK/대상/중복·cancel·실제 fixture child/SIGKILL·stdout 분리. 전체 571개(신규 65)·wheel·보존 검증. 실제 미구현 stage는 STAGE_UNAVAILABLE. UI/장치/engine 실행 검증은 후속이며 다음 묶음은 자동 시작하지 않음.

- [x] **BU01 — 프로젝트·재구성** ([builder](../SPEC-builder.md))
  - 선행: B00·저장된 후보/scan Baseline.
  - Files: project.py, reconstruction.py + project 시험.
  - Acceptance / Verify: builder-AC01 오프라인 완료. 실제 저장 후보/scan·registration/segmentation exact·current/후보·evidence/승격 조건 보존. [BU 묶음](../docs/builder-bundle.md).

- [x] **BU02 — 카메라·Geometry·물성 정합** ([builder](../SPEC-builder.md))
  - 선행: B03의 관련 정합 fixture.
  - Files: calibration의 3개 파일 + calibration 시험.
  - Acceptance / Verify: builder-AC01 정합 계산 완료. 기존 23함수·B03 투영·B01 FK exact/경계·held-out·passive 물성 fixture. 실물 검증 상태 승격 없음.

- [x] **BU03 — Export closure·Revision** ([builder](../SPEC-builder.md))
  - 선행: S01/S02·BU01/02 결과 계약.
  - Files: export.py, exporters/usd.py, exporters/mjcf.py + export 시험.
  - Acceptance / Verify: builder-AC02 및 AC03 파일/공식 parser 부분 완료. 실제 70파일 package·48좌표/2카메라·source/실행 모델 SHA·이동 fresh child·MuJoCo/USD parser·Finger/pad 상대 로더 확인. SIGKILL 전후/오류·기존 Revision 불변. 실제 articulation/collider 설치·접촉은 E01/E02 OPEN.
  - 보완: Finger Collision 파일을 새 패키지와 manifest.json에 등록하고 로더의 참조를 패키지 내부 상대 경로로 연결한다. BU03에서 원본 파일 접근 차단 후 native file 로딩/source hash를 확인했다. 실제 로봇 collider 적용·접촉 검증까지 완료했다는 뜻은 아니며 E01/E02에 남긴다.

- [x] **BU04 — 검토·렌더·Builder UI** ([builder](../SPEC-builder.md))
  - 선행: BU01·저장된 렌더 fixture.
  - Files: validation.py, rendering.py, ui.py, cli.py + 시험.
  - Acceptance / Verify: 기존 21 CLI·4탭/후보·상태·검토·신규 Export 연결. offscreen Qt/실제 worker·MuJoCo/Blender static RGB/mask 통과. 전체692개 회귀·wheel·보존. 실제 Isaac/동적 엔진 흐름은 E01/E02 이후.

- [x] **RO01 — Precision Calibration 계산** ([robot-operations](../SPEC-robot-operations.md))
  - 선행: B03 CAL-01.
  - Files: robot/calibration.py + precision 시험.
  - Acceptance / Verify: AC01 순수 계산 완료. B03 60개 표본/mapping hash exact·branch/roundtrip/limits-only/관측·명령·Scene 연결. [묶음 결과](../docs/robot-operations-bundle.md).

- [x] **RO02 — 장치 수명·제어 제한** ([robot-operations](../SPEC-robot-operations.md))
  - 선행: B03 ROBOT-01.
  - Files: robot/devices.py, robot/control.py + lifecycle 시험.
  - Acceptance / Verify: AC02 fake 범위 완료. 공식 SDK 실패 body·timeout/중복 Stop/close·부분 연결·포트/나머지 자원/중단 정리·effect unknown. 실물 안전 증명 아님.

- [x] **RO03 — Capture·동기 자료** ([robot-operations](../SPEC-robot-operations.md))
  - 선행: RO01/02·CAL-02.
  - Files: robot/capture.py + capture 시험.
  - Acceptance / Verify: host-time/안정성/frame/snapshot 계약·fake CameraReader 완료. 전체647개(신규76)·wheel·보존 검증. AC03 실물 시험은 BLOCKED/미검증. Snapshot publish/Recipe runner/UI/엔진 연결은 후속이며 다음 묶음은 시작하지 않음.

- [ ] **E01 — Isaac 구성·복원** ([simulation-workflows](../SPEC-simulation-workflows.md))
  - 선행: S01/S02·B01/B03 관련 state.
  - Files: isaac/env_cfg.py, mdp.py, state.py + Isaac 시험.
  - 이전 증거 / Verify: 공식 실제 Env 구성/Step·RGB·동적 wrist·당시288convex+2pad·restore, B01 post221/pre222 latch exact 근거 확보. 전체 Annotation 수치는 최대0.01133rad/2.42mm 차이로 AC01 numeric 동등성 OPEN/BLOCKED, 독립 리뷰도 미완료. [엔진 묶음](../docs/simulation-engine-bundle.md). E01 전체 완료 체크는 보류.
  - 후속 [E01 물리 진단](../docs/e01-physics-diagnosis.md): instance 내부 기존 collider3개 비활성화 누락과 cup offset override 수정. 당시288-part 제품은 q최대0.145633rad/위치29.6508mm·Grasp222로 보존 OPEN. 기존 v8+당시 Source initial은 B01 q exact 재현; Annotation 출력 initial 재저장 차이와 분리. 독립 Standards/Spec patch 리뷰 완료. E03/E04/E06 미착수, E01 완료 체크 보류.

  - 최종 사용자 결정에 따른 [v8 native Collision 복구](../docs/e01-v8-collision-recovery.md): 기존 실행USD를새Revision에closure수집·이동후직접spawn. Isaac288생성/기존collider해제 제거, MuJoCo288유지. B01 Source initial의q/qd exact·Grasp221/latch exact, 실제Step/Reset/RGB·748회귀·두wheel 통과. 물체306이후최대1.197188790mm/tick310 Y 잔차로 전체E01 OPEN. 다음Workflow 미착수.

- [x] **E02 — MuJoCo 구성·복원** ([simulation-workflows](../SPEC-simulation-workflows.md))
  - 선행: S01/S02·B01/B03 관련 state.
  - Files: mujoco/model.py, state.py, control.py + MuJoCo 시험.
  - Acceptance / Verify: AC01의 E02 기반 범위 완료. 실제 MjModel/MjData 6joint/servo·Finger/pad·Step/contact/rollback·opaque state/이동 후 exact replay. B01 Source24/Annotation388·post222/pre223 latch exact; 전체743개 회귀·wheel/보존. E03/E04 runner는 없음.

- [ ] **E03 — Source 양 엔진** ([simulation-workflows](../SPEC-simulation-workflows.md))
  - 선행: E01/E02 각각·D02·T03·R03.
  - Files: 각 엔진 source.py + 각 시험.
  - Acceptance / Verify: simulation-workflows-AC02; 엔진별 작업으로 나누어 pre-step 기록/취소 검증; 장치 사용 시 RO02.
  - [x] E03-MuJoCo 기본 Source: 실제 Step/640×480 영상·pre-step 기록·Native publish/새 출력 Resume·취소/강제종료 검증. [결과](../docs/mujoco-workflows-ik.md). 실물 Leader 및 선택적 signal/metric 실행은 미검증/미지원.
  - [x] E03-Isaac 기본 단일 stage/단일 env 수집: 실제 388 frame·pre/post 구분·Native/640×480 영상, fake Leader production run의 실제 Step/정리. [결과](../docs/simulation-workflows-bundle.md). 실물·같은 앱 재생성은 OPEN. R03 실제 Isaac Annotation child는 정상 종료/terminal까지 검증(로그/audit bootstrap만 사용). 전체 체크 보류.

- [ ] **E04 — Annotation 양 엔진** ([simulation-workflows](../SPEC-simulation-workflows.md))
  - 선행: E01/E02 각각·D02·T02·R03.
  - Files: 각 엔진 annotation.py + 각 시험.
  - Acceptance / Verify: simulation-workflows-AC01/02; 저장 source fixture로 manual/auto·복원/채택.
  - [x] E04-MuJoCo 기본 Manual/Auto: 원 Source 초기 상태→실제 replay→T02→공식 Pool, post222/pre223·manual203 보존. Native 완료/lineage·취소/실제 worker 검증. [결과](../docs/mujoco-workflows-ik.md).
  - [x] E04-Isaac 단일 Episode 기본 Manual/Auto: 실제 Source→새 앱 replay→공식 Pool·post221/pre222 및 manual203, E01 q/qd/선택 접촉력 exact. [결과](../docs/simulation-workflows-bundle.md).
  - [ ] E04 복수 Episode Isaac 복원 동등성·선택적 별도 metric: 미검증/명시 거부. E01 물체1.197188790mm 잔차 OPEN.

- [x] **E05 — 공유 Mimic 계산 이관** ([simulation-workflows](../SPEC-simulation-workflows.md))
  - 선행: B01 DataGen trace.
  - Files: generation/mimic.py 및 reference + mimic 시험.
  - Acceptance / Verify: AC03의 E05 공통 계산 완료. 작은 reference subset/라이선스·34symbol 연산, B01 A/B seed/selection/boundary/231+168 waypoint dtype·배열 exact. CPU 단일 tool0, IK·attempt 실행/성공 채택은 E06 미착수.
  - 경계: source 선택/offset/RNG 계산을 이관하며 과거 Solver dispatcher·SciPy IK·Strict/Hold를 복사하지 않는다. 고정 IK 계산/연결 시험은 E06 범위다.

- [ ] **E06 — DataGen 양 엔진 연결** ([simulation-workflows](../SPEC-simulation-workflows.md))
  - [x] E06-a: 고정 Pinocchio DLS + Best Effort 공통 계산·실제 기존 DLS 비교·invalid/jump/limit·Native IK identity 거부 경계. [결과](../docs/mujoco-workflows-ik.md).
  - [x] E06-b MuJoCo 기본 Fixed 실행: 실제 Mimic/DLS/Step/Grasp AND Placement/Native·worker·Resume 누적 성공2개, 각399 frame. [결과](../docs/simulation-workflows-bundle.md).
  - [x] E06-c Isaac 기본 Fixed 실행: 단일 Episode Annotation 관문 뒤 실제 R03 생성·Native·새 worker Resume 누적 성공2개, 각399 frame.
  - [x] 신규 Random Pose: 실제 Workspace/Geometry·24mm surface gap·Seed 없는 생성·native payload preflight·실패 attempt/새 출력 Resume. [결과](../docs/random-placement-horizontal.md). 기존 v8 변경/실제 v9 생성·UI 미수행.
  - [ ] E06 전체 관문: 신규 entropy Workspace Random은 양 엔진 fresh-worker/새 출력 Resume로 검증. 기존 seeded uniform의 v8 Support 위반은 역사적 경로로 남기며 신규 Pose에 RNG continuation을 요구하지 않음. 같은 Isaac 앱 복수 Reset/Annotation·다중 env/장시간·전체 E01 numeric 보존은 OPEN. 기본 성공만으로 전체 완료 체크하지 않음.
  - 선행: E01/E02 각각·D03·T02/T03·E05의 소비 계약, DATAGEN-IK-01의 관련 fixture. 전체 작업을 기계적 직렬 선행조건으로 사용하지 않는다.
  - Files: 기존 generation/mimic.py, 해당 엔진 datagen.py 및 명령 연결 파일(control.py/MDP), 대응 시험. 아래 하위 변경으로 나누어 한 번에 모두 수정하지 않는다.
  - 하위 a: 기존 Pinocchio DLS + Best Effort 동일 입력 fixture → 공통 계산·finite/limits/직전 적용 팔 명령 대비 0.5 rad/step 경계·유효 미수렴 candidate 적용 시험.
  - 하위 b/c: a 계약 준비 후 MuJoCo/Isaac 연결을 각각 구현·검증. 공식 엔진 구조·state/previous_command 수명·좌표·pre/post 기록을 확인하고 양쪽 증거로 완료 판정.
  - Acceptance / Verify: simulation-workflows-AC02/03; 고정 DLS + Best Effort만 사용, annotated fixture·예산/배치중단·Resume·latched StableGrasp AND Placement 채택. B01 SciPy + Strict 대비 정책 변화와 미승인 회귀를 별도 보고.
  - 금지: SciPy IK·Strict/Hold 이관·Solver/Failure Policy 선택 UI/Recipe 옵션·자동 fallback. 이번 문서 갱신에서는 계산 구현/시뮬레이터 실행을 시작하지 않는다.

- [ ] **L01 — 공식 학습 실행** ([lerobot-learning](../SPEC-lerobot-learning.md))
  - 선행: B00·공식 버전/입력 fixture.
  - Files: learning/train.py + official_training 시험.
  - Acceptance / Verify: [L01/L02 결과](../docs/learning-bundle.md). ACT 공식 CLI scratch2→누적4step Resume·optimizer/scheduler/RNG/step·취소/닫힌 checkpoint 보존·새 출력 검증. Scene 없이 실행한다. Smol 실제 forward에서 padding loss 포함을 재현했으므로 전체 L01 체크는 보류한다.
  - BLOCKED: SMOL-PAD-01; SDK patch/키 치환/chunk1 우회 없음. 전체832개·wheel/독립 리뷰·원본 보존 PASS. 긴 학습/OOM·물리 배포는 미검증.

- [x] **L02 — Policy·독립 검증** ([lerobot-learning](../SPEC-lerobot-learning.md))
  - 선행: 공식 Policy/Dataset fixture.
  - Files: learning/policy.py, validate.py + policy/offline 시험.
  - Acceptance / Verify: AC02/03의 지원 ACT 범위. 저장 step4의 별도 worker/실제 val DataLoader180batch·pre/select_action/post·chunk10/Reset·train-val UID 교집합0·checkpoint 불변. 외부 official ACT 로딩도 provenance를 강제하지 않음.
  - 제어 관문: strict float32 wrist 초과는 명시 거부, NN 예측 오차와 구분. Follower command binding/motor-range·P01/P03 Rollout·Smol 학습은 미검증/차단. 실제 작업 성공률은 주장하지 않음.

- [x] **L03 — 공식 Dataset 변환/Merge** ([lerobot-learning](../SPEC-lerobot-learning.md))
  - 선행: D01·DATA-03/action 매핑.
  - Files: data/lerobot.py + lerobot_dataset 시험.
  - Acceptance / Verify: AC01의 Dataset 범위 완료. [실제 결과](../docs/l03-lerobot-dataset.md): 생성4 Episode/1596 frame의 공식 Reader/DataLoader·RGB/offset·정규화·ACT/SmolVLA processor, Native/official Merge·선택/분할 격리·원래 float64 command 검증. 전체815개·wheel·리뷰/보존.
  - 지원 경계: 동등 Scene/보정/model/단위/관절순서/camera/control 계약, canonical resumed Dataset 하나/engine. origin 미확인 archive·동일 engine Resume branch 복수 Merge는 거부. 실제 train/Policy 실행은 L01/L02에 남음.
  - 후속 관문: SMOL-PAD-01 공식 action_is_pad vs loss actions_id_pad, MuJoCo float32출력 wrist 상한 초과4frame/Episode, Follower command binding/모터 범위 미확정. SDK/target/한계 변경 없음.

- [ ] **L04 — Hub·필요 시 로그 조회** ([lerobot-learning](../SPEC-lerobot-learning.md))
  - 선행: 공식 Hub·log 계약.
  - Files: hub.py, learning/results.py(필요 시) + 시험.
  - Acceptance / Verify: lerobot-learning-AC03; 로그 실패가 학습 불변, upload는 승인된 저장소 시험.

- [x] **P01 — 양 엔진 Policy 평가** ([policy-evaluation](../SPEC-policy-evaluation.md))
  - 선행: E01/E02·T02·L02·D02.
  - Files: 각 엔진 evaluation.py + sim 평가 시험.
  - Acceptance / Verify: [P01 결과](../docs/p01-simulation-rollout.md). 현재 Scene/ACT/단일 env/Fixed 범위에서 실제 MuJoCo/Isaac 각2 Episode×60step(새 worker Resume 포함), 모두 Placement false/max_steps. 각1취소에서 partial 공개0. 공식 RGB/state→pre/select_action/post·strict 원값/payload·실제 Physics·post tracker·Native/공식 Reader/새 출력 Resume 검증.
  - 전체846개·wheel·독립 Standards/Spec 리뷰·원본 보존 PASS. Placement 성공 Episode0·안전 거부0(실제Policy); 거부/Reset/cleanup 경계는 별도 fault fixture. 성공률/과거 다른 checkpoint 궤적 동등성을 주장하지 않음.
  - OPEN 유지: E01 1.197188790mm·strict float32·SMOL-PAD-01·Follower binding/motor range·Random/같은 Isaac 앱 여러 Episode·장시간/물리 강제 종료. P02/P03은 시작하지 않음.

- [ ] **P02 — Real/Sim 연결** ([policy-evaluation](../SPEC-policy-evaluation.md))
  - 선행: RO01/02·E01 또는 E02.
  - Files: robot/real_sim.py + real_sim 시험.
  - Acceptance / Verify: policy-evaluation-AC03; 동기·제어/중지, 장치 사용 승인 별도.

- [ ] **P03 — 실물 평가** ([policy-evaluation](../SPEC-policy-evaluation.md))
  - 선행: L02·RO01/02·ROBOT-02.
  - Files: robot/evaluation.py + real 평가 계약 시험.
  - Acceptance / Verify: policy-evaluation-AC02/03; action 매핑·중지·실물 증거, sim 대체 금지.

- [x] **C01 — 분포·검토·split** ([data-curation](../SPEC-data-curation.md))
  - 선행: D01·기존 분포/선택 fixture.
  - Files: data/curation.py + curation 시험.
  - Acceptance / Verify: [C01/C02 결과](../docs/curation-bundle.md). 기존 선택/재로드 API를 보강해 original outcome/attempt 범위·선택 구간/분할 통계·공통 histogram 비교·정확한 RGB/PTS·Scene reference 위치/m/frame·seed/rule·Revision lineage를 검증. 실제4 Episode와 과거50 Episode/21284frame·기존 split AST 배정 exact.
  - 전체868개·wheel·독립 Standards/Spec 리뷰·원본 보존 PASS. unknown 단위 비교/누락 frame·field는 오류. historical Source partition/수집 잠금 보존. 자동 부족 영역 탐지·추천/Recipe 자동 입력은 없음. UI 사용 흐름은 U에서 미검증.

- [x] **C02 — subset·독립 Export** ([data-curation](../SPEC-data-curation.md))
  - 선행: C01·D03, 공식 export만 L03.
  - Files: data/curation.py + curation_export 시험.
  - Acceptance / Verify: AC03의 선택/참조/이동·독립 Export·공식 소비. 실제 V1/V2→프로세스 종료→동일 선택, train66/val110frame·원 Episode UID 교집합0, 원 MP4 hardlink·명시 독립copy bytes exact/재인코딩0. 기존 L03 materialize/merge 계산은 변경하지 않음.
  - 명시 relocation은 같은 identity 검사 후 V2에 상대 resolution을 저장. full Native archive와 trimmed 학습 materialization을 구분하며 미측정 initial을 합성하지 않음. UI·더 큰 영상/장시간 부하·전역 content dedup은 미검증. U01~U04/X01/P02/P03 미착수.

- [x] **U01 — Workbench 기본 UI·Scene·저장 Recipe·Run** ([현재 범위](../docs/workbench-ui-bundle.md))
  - 실제 Qt6.11 기동·기존 Builder child·Scene 검사·dirty/prepare/start/cancel/status/기존 결과 재개방.
- [ ] **U02 — Source·Annotation·실제 RGB Preview**
  - Source 실제 보존 입력·MuJoCo Auto/Manual·양 엔진 Live payload/cleanup 검증. 실물 수집 미실행.
  - 2026-10-28 Saturation 후속 검증에서 Isaac 보존 Source index323 재생/Native 저장 관문 해소. 이전 strict 거부 증거는 보존하며 실물 수집 등 나머지 범위는 별개.
- [ ] **U03 — Fixed/Random DataGen·Curation**
  - 기존 함수 직접 UI 연결·MuJoCo Fixed/Random 생성/Resume·선택/Trim/Split/Revision/공식 Export 소비 검증.
  - Isaac Random fresh-worker/Resume 실패 attempt/목표 미달 표시 검증. 후속 Saturation으로 tick348 통과·새 success Episode/Native 공식 소비를 확인. 전체 X01 범위는 별도.
- [x] **U04 — ACT Training·Simulation Evaluation (이번 승인 범위)**
  - 공식 ACT 새 smoke2→4step Resume·loss/checkpoint, 기존 검증 checkpoint로 양 엔진60step 실패/취소 실제 UI 실행.
  - Smol/실물/작업 성공률 검증은 제외. 과거 전체 화면 inventory 완료를 의미하지 않음.
- [ ] **X01 — UI 실제 통합 및 전체 플랫폼 관문**
  - MuJoCo의 Source 입력→Annotation→DataGen→Curation→LeRobot→ACT/Evaluation, 재시작·취소·자체 child SIGKILL·원본 보존 검증.
  - Isaac Annotation/DataGen의 이전 strict 경계는 후속 Saturation으로 복구했다. 그 외 전체 플랫폼/실물 관문은 유지한다. 원래 전체 플랫폼/실물/모든 SPEC AC 회귀 완료로 승격하지 않음.

## 이번 UI 범위 밖에 유지하는 화면/실행

과거 U03의 Capture/RealSim/Calibration 화면 전체와 P02/P03·Hub·Smol 지원은 최신 요청에서 제외했다. RO의 함수/fake 증거를 실물 실행으로 승격하지 않으며 v9 생성/Calibration도 시작하지 않는다.

## 2026-10-28 최종 Position Target Saturation

[복구 결과](../docs/position-saturation-recovery.md). 이전 최종 target No-Clipping 요구는 사용자 승인으로 대체했다. 원 URDF/Calibration/SDK/기존 Dataset은 그대로다. Source/Teleop/Annotation/DataGen/Policy는 승인 한계 안의 dtype 경계로 Saturation하고 Requested·Applied·mask·delta를 구분한다. DLS 내부 계산/invalid candidate 거부/previous-applied0.5rad guard는 유지한다. 새 `joint_targets`는 Applied이며 이전 requested-target 자료와 자동 Merge/Resume하지 않는다. 실물·v9·Smol·E01 물체 잔차를 완료로 승격하지 않는다.

## 2026-10-28 요청 묶음 — Resume/Multi-Env/Smol/Preview

이 절의 R01/M01/M02/L04는 **이번 요청의 단계 이름**이며 기존 Recipe R01·Hub L04 체크를 재정의하지 않는다. [통합 결과](../docs/resume-multienv-smolvla-preview.md).

- [x] R01 확장: Source/DataGen 같은 Native 경로 추가·추가 목표/예산·2+2·고유 ID/보존·명시 crash Resume·Qt 연결. physics 중간 tick 재현은 범위 아님.
- [x] M01: 실제 MuJoCo1/4-env Source stream·Annotation·DataGen·ACT/Smol Evaluation, independent MjData/render/thread/Task/IK/queue·단일 publish·부분 재시작.
- [x] M02: 실제 Lab vector1/4-env·8 camera/contact·origin-relative initial·partial Reset·Source/Annotation/DataGen/Evaluation. vector pause는 전체 Scene, per-env single-step은 명시 미지원.
- [x] L04 확장 Smol: scoped pinned-source padding/valid-count loss·실제 backward·공식 Trainer/Checkpoint/Resume·독립 Validation·양 엔진 Fixed/Random1/4 Rollout. production 모델 수렴/성공률·원래 Hub L04는 별개.
- [x] U05: 선택 Env640×480 latest-only mmap Preview·최대 약30Hz 표시 loop·실제 FPS/지연·영상 PTS/정리·Qt 설정.
- [x] X02 승인 범위: 실제 각 엔진 matrix20 Episode·Native/LeRobot/Curation·새 자료 ACT/Smol smoke/Resume·UI 재열기·취소/강제 종료/보존·전체 회귀/wheel/독립 리뷰.
- [ ] 유지 OPEN: E01 물체 잔차1.197188790mm, 실물 command binding/motor-range/physical_verified=false, v9/실측 Calibration, 모든 Scene/N>4/장시간/OOM/전원 장애·wall-clock30FPS·production 학습 성능. 실물·Hub·후속 작업은 시작하지 않음.


## 2026-10-28 — Architecture completion (current request)

Read-only comparison baseline: Studio8a8210d, original Builderad018a0, SO101875e64f; GitHub main representative blobs match local originals. Work on architecture-completion branch; no automatic push.

- [x] Phase1a: move engine-neutral recording/command helpers; preserve math/phase.
- [x] Phase1b: Native publish/Task helpers and Prepared coverage; actual1/4-env regression.
- [x] Phase2: separate Builder scene/evidence/capture/candidate/scan responsibilities without changing API/exports.
- [x] Phase3a: installed official Policy registry/factory + Trainer fine-tune/Resume.
- [x] Phase3b: pinned Hub Dataset/Policy download and explicit opt-in upload; UI/Runner; no smoke uploads.
- [x] Phase4: offline/fake device/Capture/Calibration/real-policy contract and truthful stage availability.
- [x] Phase5: stage-scoped UI output defaults and input selection; no existing-data relocation.
- [ ] Phase6: actual engine1/4 flows, official consumers/train/Resume/evaluation, full suite/wheels/reviews/preservation; feature-state report.

Each Phase precedes the next; isolate thin slices, run focused checks, preserve SDK/original/evidence. Status meanings: VERIFIED(actual), CODE_READY(wired/unexecuted), PARTIAL, UNSUPPORTED, EXCLUDED. Hardware, uploads, newv9/real calibration are not executed by smoke validation.
