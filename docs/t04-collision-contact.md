# T04 — 일반 Collision Geometry 평면 접촉 배치

2026-10-26. 상태: **T04의 지원 다면체·평면 범위 구현 및 오프라인 검증 완료**. [SPEC](../SPEC-task-functions.md)의 일반 Fixed/Random 배치 계산을 기존 placement.py에 추가했다. 곡면 primitive·비평면 지형·엔진별 충돌 표현의 자동 선택/변환은 지원하지 않으며 명시 오류다. 실제 물리 충돌/안정성, Builder Export·Recipe·Writer·UI·엔진 Reset은 구현하거나 실행하지 않았다. T03의 v8 경로와 선행 Baseline은 보존했다.

## 구현 파일·등록

| 파일 | 책임 |
|---|---|
| [placement.py](../robot_learning_workbench/src/robot_learning_workbench/tasks/placement.py) | ContactParams, 기존 요청/결과 타입 재사용, Scene Geometry 준비, 평면 접촉 높이·영역·투영 간격·Random 계산 및 같은 파일의 명시 선언 |
| [test_contact_placement.py](../robot_learning_workbench/tests/test_contact_placement.py) | 신규 53개 시험. T03 시험을 바꾸지 않고 일반 규칙의 입력/수학/실패 경계를 별도로 대조 |

제품 코드 변경은 placement.py 하나다. 기존 validate_params의 맨 앞에 ContactParams 분기만 추가했고, v8의 나머지 15개 함수/타입 정의는 AST 비교에서 동일했다. Task 등록·Scene 패키지·Transform 구현·판정 수식·기존 시험·task_modules.yaml·패키징/의존성은 변경하지 않았다. 이미 목록에 등록된 모듈의 FUNCTIONS에 `placement.contact_fixed_xy`, `placement.contact_random_xy`를 추가했다. 자동 검색·Manager·Adapter·엔진 API는 없다.

일반 함수는 `ContactParams(object, frame, support, rules='collision_contact', margin_m=0, separation_m=0)`와 기존 PlacementRequest/PlacementResult를 사용한다. 요청에도 rules_id='collision_contact'를 명시한다. 등록 stage는 Source/DataGen/Simulation Evaluation이며 Annotation의 initial 복원과 Source/Evaluation의 성공 판정을 바꾸지 않는다. 기존 `placement.fixed_xy/random_xy`는 계속 v8_preserved 전용이다. 새 규칙이 기존 설정을 자동 대체하지 않는다.

## Geometry·Support 계약

ScenePackage의 검증된 Metadata와 Manifest를 사용한다. 숫자 Geometry를 Recipe에 복사하지 않는다.

- `objects[id].collision`: 실제 충돌 부품의 비어 있지 않은 목록. 각 부품은 `kind`, 선택 `scale`(양수 XYZ, 기본 1), `frame_id` 또는 `local_transform` 중 하나를 갖는다. local_transform은 Object 로컬 기준이며 scale을 먼저 적용한다. 이름 붙인 부품 frame은 S02로 Object frame에 상대 변환한다.
- 지원 primitive는 `kind: primitive, primitive: box, dimensions_m: [x,y,z]`다. 중심 기준 상자에 로컬 Transform을 적용하므로 바닥/편심 원점도 표현한다.
- mesh는 `kind: mesh, asset_path: package-relative-path`다. 이번 오프라인 reader가 지원하는 파일은 JSON `{schema_version: 1, vertices_m: [[x,y,z],...], triangles: [[i,j,k],...]}`다. 유한 3D 꼭짓점, 인덱스, 중복/퇴화, 닫힌 일관된 방향의 edge와 convex 면 조건을 검사한다. concave 형상은 실제로 정의된 convex 부품들의 합으로 입력해야 한다. 원본 mesh를 임의 convex hull로 대체하지 않는다.
- mesh 파일은 S01 Manifest 등록·크기/SHA·내부 경로 검사를 다시 거치고 읽은 bytes의 SHA도 확인한다. native USD/MJCF/URDF/OBJ parser나 Export/변환기는 추가하지 않았다. 이 JSON은 부품 자산 계약이며 기존 native mesh의 충돌 동등성·자동 변환 완료를 의미하지 않는다. 필요 없는 별도 mesh 복사본을 생성하지 않았다.
- 일반 support는 `{frame_id, region_xy_m}`다. 지정 frame의 z=0, +Z 법선 평면과 반시계 방향의 엄격한 convex 경계 polygon으로 정의한다. 평면의 Transform은 frame graph에 한 번만 둔다. v8의 object_id/placement_frame_id 기반 support와는 별도 선언이다.
- Box/mesh 외 primitive, 열린 mesh, 단일 concave mesh, 비평면/구멍 있는 support, 엔진 binding에 별도 collision 표현이 있는 모호한 경우는 오류다. visual이나 task_geometry bbox로 fallback하지 않는다. 엔진별 실제 부품 선택은 후속 binding에서 확인해야 한다.

준비 단계에서 부품을 immutable NumPy 배열로 연결한다. 다른 task_object도 Geometry를 준비하되 미지원/잘못된 형상의 이유를 보유하고, 실제 occupied_poses로 사용될 때 오류로 거부한다. 선택하지 않은 물체의 Geometry 오류만으로 현재 물체 배치를 막지 않는다. 배치 함수 호출 중에는 파일을 읽지 않는다. 준비 자료가 현재 엔진의 형상/동적 pose와 같다는 검증은 아직 없다.

## 접촉 높이·영역·겹침 계산

Fixed는 **입력 frame의 물체 원점 X/Y를 정확히 유지**한다. 자세를 생략하면 Metadata의 Object 기본 자세를 입력 frame으로 변환하고, 명시한 3×3 자세는 그대로 사용한다. Quaternion 순서를 추측하거나 자세를 랜덤화하지 않는다.

작업면을 `n·p=d`, 입력 frame의 +Z를 e, z=0일 때 실제 충돌 꼭짓점을 q라 할 때 `z=(d-min(n·q))/(n·e)`를 사용한다. 구현은 Support frame에서 같은 식을 계산한다. 상자/convex 삼각 mesh의 최저점은 실제 꼭짓점에서 정확히 얻으며, 모든 부품 중 최저점을 사용한다. 회전·scale·offset·입력/Support frame을 반영한다. 입력 +Z와 법선의 내적이 1e-8 이하이면 이동 방향이 부적절하므로 거부한다. 비평면 접촉이나 중력에 대한 정적 안정성을 해결하는 함수가 아니다.

일반 규칙의 접촉 여유는 **0m**이며 3mm를 더하지 않는다. v8은 기존 3mm를 그대로 쓴다. 모든 부품을 Support 평면에 투영해 convex 영역의 각 경계 안에 있는지 검사한다. 영역 margin은 일반 Fixed와 Random 모두 적용한다. 일반 Geometry의 길이 허용 오차는 1e-9m이며 기존 v8의 1e-7/1e-6m 검사를 수정하지 않았다.

occupied_poses는 입력 frame의 현재 다른 task_object pose다. 각 부품의 실제 투영 polygon 사이 최소 거리를 검사한다. 복합 물체 전체를 한 bbox/hull로 합치지 않아 부품 사이 빈 공간을 유지한다. touch 또는 `distance <= separation + 1e-9m`는 거부한다. 이 방식은 **Support 방향의 2D 간격 검사**다. 높이가 달라 3D에서는 분리된 물체도 투영이 겹치면 보수적으로 거부할 수 있다. 결과는 `physical_collision_checked=false`, `overlap_rule=projected_parts_conservative_3d`이며 엔진 충돌 PASS가 아니다.

## Random·실패 예산

먼저 현재 자세/부품 footprint와 margin을 반영해 Support polygon에서 가능한 원점 이동 영역을 계산한다. 그 영역을 입력 frame XY로 옮긴 bounding rectangle에서 uniform 후보를 뽑고 정확한 polygon/부품 간격 조건을 검사한다. 위치 보정·영역 확장은 없다. 양의 면적을 가진 배치 영역이 없으면 draw 전에 INVALID_PLACEMENT다. Fixed는 딱 맞는 경계 위치도 허용 범위 안에서 검사한다.

- 후보 하나당 전달받은 RNG의 `uniform(low, high)` 호출 한 번, 물체별 최대 1,000회다. 객체 정렬·자체 seed·global RNG·batch 카운터를 추가하지 않았다.
- 후보 실패만 재추출한다. 잘못된 Geometry/Frame/자세/occupied ID와 비유한·범위 밖 RNG 응답은 즉시 오류다. RNG가 이미 소비됐다면 되돌리지 않는다.
- 한도 소진은 PLACEMENT_EXHAUSTED이며 물체/Support/frame/rule/version, 조건, bounds, 마지막 XY/거부 원인, occupied IDs, attempts=1000을 남긴다.
- 일반 규칙은 회전 footprint와 새 영역을 사용하므로 **v8과 같은 seed라도 같은 후보/분포/RNG 소비를 약속하지 않는다**. 기존 v8 함수에는 이 검사를 추가하지 않았으며 기존 소비 상태의 동등성을 따로 확인했다.
- 실제 실행 작업 중단·완료 Episode 보존·Writer abort·physics rollback과 엔진 충돌 후보의 예산 연결은 후속 실행기 작업이다. 여기서 sampler를 재호출해 예산을 초기화하는 로직은 없다.

## 검증 결과

| 항목 | 결과 / 증거 |
|---|---|
| 전체 회귀 | **401 passed, skip 0** = 기존 348 + 신규 53. [JUnit](evidence/t04/unit-tests.xml), [로그](evidence/t04/logs/08-final-suite.log) |
| 신규 Geometry 경계 | 중심/바닥/편심 원점, 부품 scale/offset·named frame, 기본/명시 자세, 회전 Support·다른 입력 frame, compound gap·triangle footprint, margin/간격·배치 불가, 잘못된 mesh/경계/입력, 1,000회·draw 상태 |
| v8 순수 함수 재대조 | **81 batch** 위치/실패·RNG exact, **14 pose 경계**, seed 12개 및 1000회 실패 조건 유지. [기존 비교](evidence/t04/baseline-comparison.json) |
| 실제 v8 Geometry 숫자 | B01의 native scene.xml에서 box collision의 치수·identity offset을 읽고 profile Transform/실제 uniform 3 batch와 대조한 **9개 사례**. 해석적 box support 높이와 ≤1e-12m 일치. v8 높이와 일반 접촉 높이 차이는 3mm. World/Workspace 최대 행렬 차이 **6.938893903907228e-18**. [Geometry 비교](evidence/t04/geometry-comparison.json) |
| v8 코드 보존 | 기존 함수/클래스 **15개 AST 동일**. validate_params의 새 타입 분기만 비교에서 분리. T01/T02와 기존 시험/등록 목록도 변경 없음 |
| 패키징 | [wheel](evidence/t04/build.json) source/config·compile·임시 해제본 isolated import·10개 등록/기존 latch/새 contact smoke 통과. 기존 환경 설치 없음 |
| 보존 | [전후 대조](evidence/t04/preservation-after.json). 기존 파일 stat·선택 SHA 및 선행 증거 비교. 이번 제품 변경 허용 파일은 placement.py 하나. 전체 대용량 corpus/SDK binary의 전수 byte 검증은 아님 |
| 재현 | [commands.json](evidence/t04/commands.json), [verification.json](evidence/t04/verification.json), 각 RED/GREEN 로그·harness |

실제 v8 비교는 XML의 수치 읽기와 임시 synthetic Scene binding이다. 새 Scene Export·Asset 변환·엔진 로딩을 한 것이 아니다. 새 접촉 계산에는 기존 동일 구현이 없으므로 해석적 식과 기하 불변조건을 기대값으로 사용했다. v8 높이/분포를 새 결과의 정답으로 바꾸지 않았다.

중간 경계 시험에서 self-intersecting polygon의 양의 turn만으로는 충분하지 않음을 확인하여 실제 convex 경계 순서도 검증했다. 비정상 RNG의 오류 진단에서 소비한 draw 수를 보존했고, 모호한 primitive 필드도 준비 시 거부하도록 고쳤다. 수치 기대값이나 기존 Baseline을 바꾸지 않았다. 초기 실패/중간 시험 로그도 보존했다.

## 완료·미검증 경계

AC02의 중심/바닥/편심·회전·복합 collision 및 Fixed/Random 접촉 높이와 오류를 **지원 다면체/convex 평면 범위**에서 완료했다. AC03은 같은 Task 파일/명시 목록 경로로 등록됨을 확인했다. 곡면 형상·비평면/구멍 support·native mesh parser/변환·실제 엔진 collision/접촉 solver·동역학 안정성·공식 엔진의 representation 일치 여부는 지원/검증 완료로 표시하지 않는다.

Python3.11.15/NumPy1.26.0/pytest9.1.1 및 기존 패키징 환경을 사용했다. 설치·업그레이드·환경 분리·실물/카메라/엔진 실행이 없다. 별도 lint/type 도구는 설정·설치되지 않아 실행했다고 보고하지 않는다. 신규 runtime 의존성은 없고 모든 수치 계산은 기존 NumPy를 쓴다.

B01 Isaac DataGen 실패/Evaluation 비결정성, B02의 저장/Resume·IK identity, B03 Calibration/장치 OPEN 및 ASSET-FINGER-01은 그대로다. DLS IK·Writer·Recipe·UI·Reset 연결은 시작하지 않았다. incremental-implementation과 test-driven-development 순서로 작은 단위 시험을 진행했다. 참조 definition-of-done 문서는 가용 위치에 없어 SPEC·시험·빌드·보존을 관문으로 사용했다. Git 저장소 초기화/commit도 하지 않았다. **T04 이후 작업은 시작하지 않고 중단한다.**
