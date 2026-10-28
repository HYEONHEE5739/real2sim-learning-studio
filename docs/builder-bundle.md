# BU01~BU04 — Real2Sim Builder 묶음

2026-10-26. 상태: **BU01~BU04 구현·오프라인/공식 파일·렌더 검증 완료**. [SPEC](../SPEC-builder.md)의 Builder 책임을 구현했다. 실제 Isaac Lab Env·PhysX/Fabric·동적 로봇·센서 및 새 MuJoCo 실행 Workflow는 E01/E02 이후 관문이다. 실물·장치·외부 업로드·E 계열 구현은 시작하지 않았다. [C Native Dataset](native-dataset-transition.md)과 기존 Scene·Task·Recipe·Robot 제품/시험은 변경하지 않았다.

## 완료 기능과 실제 파일

| Task | 구현·기존 재사용 범위 | 검증 |
|---|---|---|
| BU01 | [project.py](../real2sim_builder/src/real2sim_builder/project.py): 프로젝트·evidence·입력·후보·scoped edit·선택/기각/승격·rollback. [reconstruction.py](../real2sim_builder/src/real2sim_builder/reconstruction.py): GLB import·segmentation·metric registration·후보 초기화·coverage/diagnosis·반복 정합 | 실제 저장 프로젝트 48물체/2카메라/14이미지·current와 final 후보의 차이·fresh signature. 22,779,224B 실제 scan의 10개 proposal/plane이 기존 함수·저장 결과와 exact |
| BU02 | [camera.py](../real2sim_builder/src/real2sim_builder/calibration/camera.py): 투영·K/extrinsics·정합. [geometry.py](../real2sim_builder/src/real2sim_builder/calibration/geometry.py): Geometry/mesh·reference FK·multipose/bootstrap/held-out·depth·undistortion. [physics.py](../real2sim_builder/src/real2sim_builder/calibration/physics.py): 측정 질량/지원면이 있는 passive 마찰 추정 | 기존 23개 함수의 연산 AST 보존, B01 기록 q의 6개 FK snapshot exact, B03 side/wrist의 6개 투영 오차 <1e-10px. 실제 MuJoCo passive-motion fixture·독립 held-out·degenerate/unknown 경계 |
| BU03 | [export.py](../real2sim_builder/src/real2sim_builder/export.py)와 [usd.py](../real2sim_builder/src/real2sim_builder/exporters/usd.py)·[mjcf.py](../real2sim_builder/src/real2sim_builder/exporters/mjcf.py): S01/S02 Scene Revision·Manifest·native closure·필수 Collision/model identity·새 destination publish | 실제 v8 근거를 포함한 70개 파일 패키지·이동·원본 접근 차단·공식 parser 재개방. native 참조 누락/중복 보정/변조 거부. publish 전후 강제 종료·I/O 오류 경계 |
| BU04 | [validation.py](../real2sim_builder/src/real2sim_builder/validation.py)·[rendering.py](../real2sim_builder/src/real2sim_builder/rendering.py)·[cli.py](../real2sim_builder/src/real2sim_builder/cli.py)·[ui.py](../real2sim_builder/src/real2sim_builder/ui.py): 지표/진단·MuJoCo/Blender 렌더·기존 명령/4탭·후보/리로드·검증 상태·신규 Export | 기존 CLI 21개 누락 0, clone 추가. 기존 Qt의 offscreen UI와 실제 arena worker import·오류 표시. 실제 MuJoCo EGL/Blender RGB·물체 mask |

기존 B의 함수 body를 새 Architecture의 소유 파일로 이관했다. 원본 app을 런타임 import하는 호환 Wrapper나 새 Manager/Adapter/서비스/저장 계층을 추가하지 않았다. 새 패키징은 [pyproject.toml](../real2sim_builder/pyproject.toml), runtime 소유 Python 파일은 __init__ 포함 15개다. camera/multipose/depth/preprocess/FK는 설계된 calibration 3파일에 배치했다.

## 프로젝트 소유권·후보·검증 상태

원본의 표시되지 않은 프로젝트는 기본 읽기 전용이다. 새 Project.create 또는 **명시적 clone**이 새 작업 공간의 owner marker를 만든다. readonly=False로 원본을 강제 쓰기 모드로 여는 것은 거부한다. zero image/evidence에서도 analyze·undistort가 쓰기를 시작하지 못하도록 진입점에서 검사한다. clone은 실행 중이거나 해석되지 않은 run.lock이 있으면 거부한다.

current Scene, candidate, 과거 export는 별개다. 기존 최종 후보는 `OPEN`, fresh report의 `passed=false`이며 새 검증 완료로 승격하지 않았다. 일반 Export는 fresh 통과 report가 필요하다. `allow_unvalidated=True`/CLI `--allow-unvalidated`는 명시적인 검토용 Export이며 stale signature는 여전히 거부한다. 추정/독립 검증/물성·물리 검증을 구분하고 measured q·치수·보정 상태를 임의 수정하지 않는다.

기존 71개 함수 중 70개의 연산 AST가 일치했다. import 이동·readonly guard·capture schema 이름 충돌 분리만 대조에서 제외했다. pipeline.run은 명시 destination과 unresolved lock 처리가 의도된 차이다. 검증 실패/NEEDS_MORE_DATA를 성공으로 바꾸지 않는다. 기존 Hold-out 재사용/미측정 질량/metric scale 미확인/공선점·평면점의 제한도 보존했다.

## Export와 Calibration·Collision 경계

`export_revision(project, *, destination, candidate=None, calibration=None, required_files=(), ...) → SceneIdentity`는 신규 경로에만 publish한다. `verify_package(path)`는 S01/S02 파일·모델·보정 선언과 native 참조 closure를 검사한다. 소스 USD는 읽기 전용 Layer로 열고 파생 참조만 anonymous layer에 수정한다. 기존 상대 참조가 유효하면 URDF/USD bytes를 불필요하게 재작성하지 않는다. 공유 Mesh를 먼저 복사해도 원본/보정 URDF의 상대 배치와 SHA가 유지된다.

USD 참조는 공식 UsdUtils를 사용한다. MJCF include는 **중첩된 파일도 주 MJCF 디렉터리 기준**이라는 공식 규칙으로 확장하며 node 순서·숫자 문자열을 유지한다. URDF mesh, MJCF mesh/texture, USD sublayer/reference/payload/asset, OBJ/MTL의 명시 참조를 수집한다. 누락/원격·해결 불명 참조는 자동 검색이나 네트워크 fallback 없이 오류다. MTL의 지원 밖 texture 옵션은 명시 오류다. 엔진 entry를 외부 파일로 교체하면서 생성된 binding을 재사용하는 옵션은 차단한다.

SO101은 Finger Convex Parts와 USD contact pads의 원 JSON 및 각 source SHA에 해당하는 실제 파일을 모두 요구한다. 누락을 임의 다른 파일로 대체하지 않는다. `scene.robot.collision`은 JSON과 source 파일을 **패키지 내부 상대 경로**로 연결한다. `exporters.mjcf.load_robot_collision(root, binding)`은 원본 ROOT 없이 해당 payload와 정확한 source hash를 읽는다. 실제 엔진 collider에 이를 설치하고 접촉을 검증하는 책임은 E01/E02다.

보정은 S02 선언으로 받으며 fitter/Encoder/Geometry residual을 Export에서 다시 실행하지 않는다. 실제 probe는 RO의 limits-only 모델 binding 결과·Leader/Follower mapping 및 v8 baked residual을 명시적으로 제공했고 세 모델 SHA를 보존했다. 보정 파라미터와 baked 결과 Asset 경로를 이관한 뒤 S02의 model/joint-order/dependency/hash/중복 적용 검사를 실행한다. active pointer를 실행 중 자동 선택하지 않는다. `calibration=None`은 빈 선언이며 보정 없음이 검증됐다는 뜻이 아니다. `robot.reference_snapshot_only=true`와 `validation.execution=NOT_TESTED`를 유지하고 E01/E02에서 실제 실행 모델·보정 binding을 확정해야 한다.

`required_files`의 일반 경로는 실행 필수 native Asset으로 closure를 검사한다. `{'source': ..., 'usage': 'identity_evidence'}`는 실행되지 않는 원본 근거 바이트다. 과거 원 모델이나 contact pad 추출 근거 USD는 `.source`로 복사해 hash를 보존한다. 후자의 OmniPBR.mdl 시스템 라이브러리를 새 Scene의 실행 의존성인 것처럼 취급하지 않는다. 새 생성 USD는 자체 mesh/material 표현이며 이 원본 근거 USD를 reference하지 않는다. 근거 파일을 실행 가능한 robot USD로 보고하지 않는다.

생성 MJCF·USD는 현재 Builder의 **reference geometry snapshot**이다. 기존 Workspace의 관절 제어·센서·접촉·dt/solver 또는 PhysX articulation을 이미 이관한 것이 아니다. 모델 근거/원본/보정 Asset은 패키지에 있지만 실제 제어 모델 조립과 중복 snapshot 제거는 엔진 구성에서 검증한다.

## 실제 검증 결과

| 검사 | 결과 / 증거 |
|---|---|
| 전체 회귀 | **692 passed, 0 skipped** = 기존 604 + Builder 88. [JUnit](evidence/builder/full-suite.xml), [로그](evidence/builder/logs/41-final-suite.log). 기존 torchvision deprecation 경고 2개 |
| 실제 프로젝트/scan | [bu01-probe.json](evidence/builder/bu01-probe.json), [함수 대조](evidence/builder/bu01-ast-comparison.json). 원본 current를 후보로 덮어쓰지 않음 |
| 정합/FK | [calibration-source.json](evidence/builder/calibration-source.json). B03 좌표·방향/Quaternion·K 및 B01 기록 q 보존. 실제 장치 보정 검증 아님 |
| 기존 native Export 대조 | [original-export-comparison.json](evidence/builder/original-export-comparison.json): 기존 final 후보 Export와 48개 body 및 13개 native 배열이 exact. geom 330개·pose/quat/size/friction/contact flags·camera pose/quat/fovy 포함. 물리 실행 동등성 아님 |
| 실제 Export/이동 | [export-probe.json](evidence/builder/export-probe.json): Manifest 70파일, 48개 world 행렬·카메라 2개 K/pose exact. 새 프로세스에서 원본 프로젝트 Python open 차단 후 공식 MuJoCo 330 geom·USD 482 prim 재개방, Finger 3 mesh/contact pad 2 payload·source hash 확인 |
| 보정/누락 오류 | 실제 과거/기준/보정 URDF SHA 유지. Finger 제거와 runtime residual 중복 선언은 거부, 잘못된 결과는 publish하지 않음 |
| 중단/내구성 | [crash-tests.xml](evidence/builder/crash-tests.xml): 자체 disposable child를 publish 전/직후 SIGKILL. 전자는 destination 미노출·해석 불명 lock 보존, 후자는 완성 파일 재개방·기존 경로 재사용 거부. 앞선 Revision 불변. disk full·stale input·directory fsync 오류 시험 포함 |
| 실제 렌더 | [render-probe.json](evidence/builder/render-probe.json): 설치 MuJoCo3.3.7 software EGL와 Blender5.2.2 LTS에서 160×120 uint8 RGB와 실제 물체 mask. mask는 각각 219/190 pixel. 서로 같은 픽셀/센서 결과라고 주장하지 않음. [렌더 파일](evidence/builder/renders/) |
| UI/CLI | [inventory](evidence/builder/bu04-inventory.json). 기존 21명령·4탭/입력/후보·정합/상태/비교/Export 기능. offscreen Qt·실제 input worker·저장 상태 오류·stale preview 제거. 실물 화면/대화형 장치 사용 흐름 아님 |
| wheel | [build.json](evidence/builder/build.json): 0.1.0 wheel, 15개 파일 bytes·compile·별도 isolated 해제본 import/CLI/new/clone smoke. 기존 환경에 설치하지 않음 |
| 검토·정리 | [Standards](evidence/builder/review-standards.md), [Spec](evidence/builder/review-spec.md): 별도 에이전트 검토 후 actionable 잔여 0. 큰 모듈을 이유로 새 계층을 만들지 않음. 중복 import만 별도 정리 |
| 보존 | [preservation-after.json](evidence/builder/preservation-after.json): 기존 56,100개 stat·선택 15,607개 SHA 변화 0. 전체 corpus/SDK binary의 전수 byte 검증은 아님 |

테스트에서 사용한 장치 API는 없다. passive 물성 fixture는 공식 MuJoCo CPU 시뮬레이션이며 로봇 Workflow 실행은 아니다. CLI export/verify는 실제 S01/S02·USD/MJCF 파일을 사용하고 가짜 성공으로 대체하지 않는다. 테스트 실패·수정 전 로그도 보존했다. wheel smoke 초기 실패는 cv2의 순수 계산 import를 장치 연결과 혼동한 검사, clone 인자/초기 Scene fixture 오류였으며 제품 동작을 기대값에 맞춰 바꾸지 않았다.

## 사용과 실행 환경

기존 arena Python과 별도 설치된 Qt Python을 그대로 사용했다. NumPy1.26·SciPy1.15.3·MuJoCo3.3.7 및 Sim5.1 내 USD0.24.5를 확인했다. UI 쪽 NumPy2가 계산 worker에 섞이지 않도록 QProcess의 Python 경로를 분리한다. 새 conda/venv·pip install·업그레이드는 수행하지 않았다.

CLI는 `python -m real2sim_builder.cli --help`이며 `new`, `clone`, `inspect`, `scan`, `candidate`, `validate`, `export --destination`, `verify`를 제공한다. 원본을 편집하려면 먼저 새 경로로 clone한다. 검토용 후보는 CLI의 `--candidate ... --allow-unvalidated`로 명시하고 실행 검증 완료로 취급하지 않는다.

설치 전 개발 경로/공식 USD process-local 경로는 [run_tests.sh](evidence/builder/run_tests.sh)에 기록했다. UI 실행 시 기존 Qt Python을 사용하고 `REAL2SIM_WORKER_PYTHON`은 arena, `REAL2SIM_USD_PYTHONPATH`는 기존 Sim omni.usd.libs 디렉터리, 해당 `bin`은 **그 프로세스의** LD_LIBRARY_PATH로 제공한다. Blender는 기존 `REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender`를 사용한다. 전역 shell/환경 파일은 바꾸지 않는다. Blender child는 자신의 Python/공유 라이브러리를 사용하도록 host 경로를 제거한다.

공식 근거와 조회 한계는 [official-sources.json](evidence/builder/official-sources.json)에 있다. [MuJoCo3.3.7 include](https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html#include), [OpenUSD dependencies](https://openusd.org/release/api/dependencies_8h.html), [Qt QProcess](https://doc.qt.io/qt-6/qprocess.html)를 설치 API/실제 시험과 함께 대조했다. Blender 공식 웹 페이지는 접근 오류여서 새 버전 API를 웹에서 확인했다고 주장하지 않는다. 별도 lint/type 도구가 설정/설치되지 않아 실행하지 않았다.

## 의도된 차이·완료 경계

의도된 변경은 원본 read-only/명시 clone, 새 destination만 허용하는 Manifest/Revision Export, source evidence/runtime 파일의 구분, stale/누락/중복 보정 차단, 잘못된 상태·preview 표시 수정이다. K/Transform/Quaternion 곱·정합 수식·물성 추정/검증 상태를 의도적으로 바꾸지 않았다. 자동 export/검증 상태 승격·숨은 active Calibration 선택을 하지 않는다.

AC01의 저장 자료·순수 정합/선택·렌더 지표와 AC02의 새 publish·원본/이전 Revision 보존, AC03의 파일 closure·이동·공식 native parser 로딩 부분을 검증했다. **AC03의 실제 Isaac/MuJoCo 로봇 실행 및 접촉 검증은 남아 있다.** POSIX 로컬 filesystem의 cooperating writer 조건이며 전원 장애/NFS·적대적 동시 쓰기까지 crash safety를 증명하지 않는다. SIGKILL의 stale lock/임시 공간은 자동 삭제/재사용하지 않고 상태 확인 대상으로 남긴다.

후속 관문:

1. E01/E02: 패키지에서 실제 articulation·모델/보정·필수 collider를 조립하고 root/joint/opaque initial state를 복원한다. PhysX/Fabric 동적 camera pose·센서 시점·접촉/rollback/dt·필수 URDF/USD identity를 검증한다. ASSET-FINGER-01의 **실제 collider 적용/접촉** 부분은 OPEN이다.
2. E03/E04: 엔진별 Source/Annotation의 Native Dataset·pre/post-step·B01 tick/frame·정상 실패/취소를 연결한다.
3. E05는 기록 fixture로 Mimic 공통 계산을 독립 진행 가능하다. E06은 고정 Pinocchio DLS + Best Effort 공통 검증 후 각 엔진을 연결한다.

B01 Isaac DataGen 실패·Evaluation 비결정성, B02 기록/Resume identity·IK 정책 구분, B03 실물/종료·physical_verified=false, v8 UNVALIDATED는 그대로다. Git 저장소가 없어 초기화/commit/PR을 수행하지 않았다. 요청된 Skill의 실제 지침을 적용했으며 별도 definition-of-done 파일이 없다는 한계는 기존과 같다. **BU01~BU04까지만 진행했고 E 계열은 자동 시작하지 않는다.**
