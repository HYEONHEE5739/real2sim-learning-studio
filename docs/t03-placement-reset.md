# T03 — v8 Fixed/Random 배치·Reset 순수 계산

2026-10-25. 상태: **T03 구현·오프라인 검증 완료**. [SPEC](../SPEC-task-functions.md)의 T03, [Interface](interfaces.md#54-배치-입력)의 v8 보존 경로만 구현했다. T04 일반 Collision Geometry 접촉 배치·Recipe·Writer·UI·엔진/장치 연결·실제 Reset은 시작하지 않았다. 기존 원본/환경과 B00~B03·S01/S02·T01/T02 증거는 보존했다.

## 파일과 책임

| 제품 파일 | 구현 / 변경 이유 |
|---|---|
| [placement.py](../robot_learning_workbench/src/robot_learning_workbench/tasks/placement.py) | uniform 후보·간격·높이, 기존 SE(3)/회전 bbox 검사, Fixed/Random 일반 함수·데이터 타입·등록 선언·per-env seed 계산 |
| [test_placement.py](../robot_learning_workbench/tests/test_placement.py) | 실제 B01 uniform/RNG, 경계·실패·Scene/등록·지원 범위 시험 41개 |
| [task_modules.yaml](../robot_learning_workbench/task_modules.yaml) | 명시 목록에 `robot_learning_workbench.tasks.placement` 추가 |
| [test_pick_place.py](../robot_learning_workbench/tests/test_pick_place.py) | Source 성공 gate 검사의 범위를 pick_place 이름으로 한정하는 **assert 1줄** 수정. 새 Source 배치 함수는 성공 gate가 아니므로 전체 registry를 금지하던 검사를 바로잡음. 수식·fixture·기대 수치는 변경하지 않음 |

registry.py·pick_place.py·scene_contract·기존 패키징/의존성은 변경하지 않았다. 표준 데이터 타입은 한 파일에 두고 Task/Engine ABC·Adapter·Randomizer manager·설정 언어·신규 계층을 만들지 않았다. 기존 WorkspaceRandomizer 전체나 env reset 코드를 복사하지 않았다. Workbench 개발 패키지는 기존 0.2.0이며 이번 wheel은 별도 증거 디렉터리에 생성했다.

## 재사용한 기존 의미

P=`/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab`.

- `real2sim/workspaces/reset.py:WorkspaceRandomizer.sample`의 uniform 계산을 사용한다. `limit = support_half_xy - object_size_xy/2 - margin`, `xy = center_xy + rng.uniform(-limit,limit)` 순서를 보존한다.
- 각 기존 물체와 **X/Y 중 한 축이라도** `abs(delta) > (size + other_size)/2 + separation`이면 분리된 것으로 본다. strict `>`이며 두 축 모두 분리하도록 바꾸지 않았다. 회전/실제 collision shape를 간격 계산에 추가하지 않았다.
- 높이는 기존 `support_center_z + support_half_z + object_size_z/2 + .003`이다. support/object 회전이나 원점이 다르다고 새 접촉 높이로 보정하지 않는다.
- `workspaces/tasks.py:validate_reset_pose`의 full inverse·회전한 bbox 8꼭짓점·support XY 1e-7m/하단 1e-6m 허용 오차와 기존 SE(3) 검사를 보존한다. S02 reference transform 검증의 다른 tolerance로 교체하지 않았다.
- `reset_workspace`의 per-env seed 계산은 단일 env일 때 base seed, 여러 env에서는 `int(SeedSequence([seed,index]).generate_state(1)[0])`다. `environment_seed`는 그 수치만 제공하며 RNG를 만들거나 global seed를 설정하지 않는다.

four_anchors는 신규 지원에서 제외한다. 과거 four_anchors fixture·자료를 uniform으로 고쳐 쓰지 않았다. uniform에서 원래 사용하지 않았던 yaw/jitter 옵션이나 edge_uniform이라는 별도 선택을 만들지 않았다. margin=0의 기존 uniform 계산은 지원한다.

## 공개 함수·Scene·요청 계약

`placement.fixed_xy(request, *, params)`와 `placement.random_xy(request, *, params)`를 T01의 FUNCTIONS에 `kind=placement`로 등록했다. Source/DataGen/Simulation Evaluation에서 선택 가능하며 순수 계산은 엔진 독립이다. Annotation에는 등록하지 않아 기록 초기 상태 복원을 Random Reset으로 대체하지 않는다. 등록 선언이 양 엔진 실제 실행 검증을 뜻하지 않는다.

`PlacementParams(object, frame, support, rules='v8_preserved', margin_m=.01, separation_m=.005, clearance_m=.003)`는 frozen dataclass다. clearance는 v8의 3mm만 지원한다. Object/Frame/Support ID는 기존 T01 검사를 사용한다. 모듈 validate_params hook은 검증된 ScenePackage에서 필요한 기준 bbox/pose를 읽어 private read-only context를 만든다. 사용자 입력으로 context를 넣을 수 없다.

T03의 Metadata 연결은 다음과 같다. 수치/Geometry를 supports에 중복 저장하지 않는다.

- object의 `task_geometry.dimensions_m`: 기존 reset bbox 치수. 시각/Collision mesh에서 다시 추정하지 않는다.
- `supports[id].object_id`: 기준 support body Object ID. 치수와 pose는 이 Object에서 읽는다.
- `supports[id].placement_frame_id`: v8 규칙이 계산되던 기준 좌표계. T03의 frame은 이 값과 같아야 한다.
- object의 frame_id 및 Scene Frame Graph: 기본 자세와 support 중심을 얻는다. 기존 parent-relative 행렬이 직접 존재하면 그 값을 사용해 World 왕복의 불필요한 rounding을 피하고, 그 외 reference 계산은 S02 resolve_transform을 사용한다. 현재 엔진 pose를 추측하지 않는다.

**T03은 v8의 기록 배치 좌표계에서만 legacy bbox 규칙을 제공한다.** 다른 입력 frame(World 등)을 이 규칙으로 재해석하지 않고 준비 시 오류로 막는다. 원점/크기/자세를 실제 Collision Geometry에 반영하는 일반 Fixed/Random 접촉 배치와 다른 입력 frame의 일반 평면 계산은 T04에 남는다. 전체 좌표계/배치 요구를 완료한 것은 아니다.

`PlacementRequest`는 object_id/frame_id/support_id, occupied_poses, 명시 rng, 선택 xy_m/orientation, rules_id다. occupied_poses는 **동일 frame의 현재 다른 작업 대상 pose**이며 실제 생성 목록/상태와 연결하는 책임은 실행 단계에 있다. 환경 Cup/테이블을 가짜 작업 대상 obstacle로 추가하지 않는다. orientation은 해석 완료한 3x3 회전이며 생략하면 Builder Metadata의 기본 자세를 쓴다. Quaternion 변환·자세 랜덤화는 추가하지 않았다.

`PlacementResult`는 object_id/frame_id/읽기 전용 pose/attempts/rules_id/diagnostics다. diagnostics에는 support/선언된 조건·rules_version=1·legacy_bbox·physical_collision_checked=false를 남긴다. 이 값은 엔진 collision PASS가 아니다.

### Fixed와 Random의 검사 경계

- Fixed는 xy_m를 그대로 두고 기존 높이를 계산한다. 기존 회전 bbox/support 검사와 선언된 bbox separation을 통과해야 한다. 위치 조정·범위 확대·RNG 호출은 없다. attempts=0은 **Random 추출 0회**라는 뜻이다. margin은 Random 범위에만 사용하고 Fixed의 support 허용 오차를 바꾸지 않는다.
- 기존 pose-only validator에는 pair separation 검사가 없었다. 새 Fixed 함수는 승인된 “겹치거나 배치 조건을 위반하면 실행 차단” 요구에 따라 그 검사를 선행한다. 이를 기존 Fixed/물리 loader가 이미 수행했던 검사라고 보고하지 않는다.
- Random은 기존 uniform 범위/축별 간격만 후보 채택 조건으로 사용한다. 회전 footprint 검사나 엔진 관통 검사를 새 재추출 조건으로 합치지 않는다. 별도 validate_v8_pose와 엔진 검사는 **기존 호출 경계에서** 수행해야 한다. Random 결과의 support_pose_checked=false는 이 구분이다.
- 명시 자세 때문에 높이가 부족하거나 실제 Geometry에 관통하는 경우 v8 높이를 자동 조절하지 않는다. 기존 MuJoCo pose 적용 실패는 오류·rollback이며 sampler를 다시 호출하지 않는다. 이 물리 동작을 T03에서 구현/재실행한 것은 아니다.

## RNG·예산·오류·상태 소유권

함수는 전달된 RNG만 사용하고 자체 seeding·전역 RNG·정렬·추가 draw를 사용하지 않는다. 실행 단계가 물체 순서대로 호출하면서 앞선 결과/기존 고정 물체를 occupied_poses로 전달한다. 실제 RNG의 생성/lifetime·Source attempt seed·DataGen SeedSequence·병렬 schedule·Resume의 이어가기 정책은 해당 실행/저장 단계의 책임이며 T03에서 새로 정하지 않았다.

기존 sample_index는 전체 batch 성공 뒤에만 증가한다. 새 함수는 물체별 결과/추출 횟수만 반환하므로 그 batch/episode 카운터를 만들지 않았다. 이후 실행기는 모든 물체가 준비된 뒤 기존 의미대로 카운터/초기 상태를 기록해야 한다. per-object 함수를 호출했다는 이유로 sample_index를 여러 번 올리거나 성공 Episode 수로 seed를 새로 만들면 안 된다.

Random 물체별 1,000회 한도는 고정이며 별도 retry/예산 선택 옵션이 없다. 모두 소진하면 PLACEMENT_EXHAUSTED에 object/support/frame/rules/조건·attempts=1000·마지막 XY·occupied IDs를 남긴다. 잘못된 형상/식별자·음수 조건·비유한/범위 밖 RNG 응답은 INVALID_PLACEMENT 등 구조 오류이며 재추출로 숨기지 않는다. 이미 소비한 RNG를 되돌리지 않는다.

기존 원본/Scene/occupied 입력에 쓰지 않는 순수 함수다. 실행 작업 중단·완료 Episode 보존·미완료 성공 데이터 금지·Writer abort/Resume는 E03/E06/D02/D03의 통합 조건으로 유지한다. **실제 작업 중단이나 저장 안전성을 T03에서 시험했다고 주장하지 않는다.**

## 검증 결과와 SPEC 완료 범위

| 검증 | 실제 결과 |
|---|---|
| 신규 배치 시험 | **41 passed**, skip 0. B01 3회 uniform/전후 RNG, Fixed XY·3mm·기본/명시 자세·readonly, strict 간격, 1,000회/fit=0/구조 오류, seed·지원 stage/frame 검사 |
| 전체 회귀 | **348 passed**, skip 0 = 기존 Scene 138 + 등록 97 + T02 72 + T03 41. [JUnit](evidence/t03/unit-tests.xml), [최종 로그](evidence/t03/logs/09-final-suite.log) |
| 기존 함수 대조 | 3개 seed·3개 물체 순서/선택·3개 margin·3회 batch = **81개**. 성공 54개, fit 불가 27개에서 위치/실패 여부·RNG 상태 exact. 실제 B01 uniform 3회와 Fixed 동일 XY의 Z도 exact. [결과](evidence/t03/baseline-comparison.json) |
| 회전/수치 경계 | 기존 validator와 **14개** SE(3)·support XY/하단 허용 오차·회전/reflection 상태의 통과/거부 일치. 허용 오차를 늘리지 않음 |
| 실패·Seed | B01 ConstantRng 1,000회 및 원래 sample_index=0 확인, 동일 새 실패/시도 수. 기존 AST의 per-env seed 12개 exact, global NumPy RNG 불변 |
| 등록·빌드 | 기본 목록 8개 함수, placement 일반 함수 연결. [wheel](evidence/t03/build.json) 소스/설정/compile·임시 해제본 isolated import·기존 latch/새 sampling/seed smoke 통과, 환경 설치 없음 |
| 보존 | [대조](evidence/t03/preservation-after.json): 기존 56,100개 stat와 선택 15,070개 SHA. 원본·환경·Baseline/선행 보고서·증거 변화 0. 새 프로젝트 T02 test의 의도된 assert 1줄만 별도 검증/기록 |
| 추적 | [commands.json](evidence/t03/commands.json), [verification.json](evidence/t03/verification.json), [허용된 테스트 수정](evidence/t03/permitted-test-change.json)에 명령·입력/코드·증거 identity/범위 기록 |

참조 대조는 기존 원본의 **순수 class/function body**를 메모리에서 실행하고 읽기 전용 v8 숫자와 임시 합성 Scene 계약 fixture를 사용했다. 실제 Scene Export/변환이나 엔진 실행이 아니다. B01 four_anchors의 같은 seed 결과와 신규 uniform이 다르다는 점도 별도 확인했다. 이는 승인된 지원 방식 변경이며 과거 자료를 새 분포로 재해석하지 않는다.

SPEC task-functions-AC02의 **v8 uniform·3mm·Fixed 검증/간격·seed/예산·오류 부분**과 AC03의 새 파일/로딩 목록 연결을 완료했다. 원점·복합 Collision Geometry·일반 접촉 높이 AC02는 T04 미착수다. 실제 엔진 충돌/rollback·기록 시점/작업 중단·통합 회귀는 미완료다. T01/T02의 판정 수식/접촉/latch·Source recording_only·Annotation 초기 상태·Evaluation Placement 종료 의미는 변경하지 않았다.

Python3.11.15/NumPy1.26.0/pytest9.1.1/PyYAML6.0.2의 기존 환경을 사용했다. 설치/업그레이드·환경 분리·시뮬레이터/장치 제어·Hub 접근을 하지 않았다. 별도 lint/type 도구는 설정/설치되어 있지 않아 실행했다고 주장하지 않는다. 스킬이 참조한 별도 definition-of-done 문서는 가용 위치에 없어 읽었다고 주장하지 않으며 SPEC·시험·빌드·보존으로 범위를 확인했다. Git 저장소를 만들거나 commit하지 않았다.

B01 Isaac DataGen 실패/Evaluation 비결정성, B02 저장 누락·정책별 Resume, B03 물리 검증/종료의 OPEN 상태 및 ASSET-FINGER-01은 그대로다. **T03만 완료하고 다음 작업은 자동 시작하지 않는다.**
