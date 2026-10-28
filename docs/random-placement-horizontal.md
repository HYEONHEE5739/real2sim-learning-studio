# Random DataGen·신규 Scene 수평 배치 기준

2026-10-27. **Seed 없는 Workspace Random 배치와 신규 Scene의 선택적 수평 검사를 구현했다.** 기존 Scene2 v8의 좌표·보정·물성·Collision·Scene Revision을 변경하지 않았다. 실제 v9 생성/Export·Calibration·UI U/X·실물 장치 연결은 수행하지 않았다. 이번 정책은 사용자가 확정한 Random Pose 생성 규칙이며, 역사적 Source/Mimic/Training/Native Attempt Seed를 삭제하는 변경이 아니다.

## 실제 v8 기울기와 이전 실패 원인

[계산 및 실제 USD/MuJoCo 조사](evidence/random-placement/v8-geometry-diagnosis.json), [harness](evidence/random-placement/diagnose.py)를 확인했다. Quaternion의 identity 여부가 아니라 **실제 Table Collision의 World 법선**을 비교했다.

| 항목 | 실제 값과 해석 |
|---|---|
| World | Up Axis Z, 중력 `(0,0,-9.81)m/s²`. MuJoCo 실제 model.opt와 USD Up Axis, 고정 Isaac SimulationCfg 기본값/구성 경로 확인 |
| Robot Base | 기준 Transform identity, 기준 +Z=`(0,0,1)`, World +Z 대비 0°. 관절을 전부 0으로 만든다는 의미가 아님 |
| Table | 중심 World `(0.0001657644,-0.2199281034,0.0067367176)m`; 실제 윗면 법선 `(0.02043769674,0.04057931887,0.99896727646)`, 기울기 **2.604156329°** |
| 기존 Workspace/블록 | Profile의 Workspace 회전 및 Table·Marker·세 Cube 기준 +Z가 같은 기울기를 가짐. 로컬 Yaw 회전과 실제 표면의 Roll/Pitch 기울기를 구분함 |
| Collision 추가 회전 | Table의 Metadata Collision local_transform은 identity. 실제 USD Collision과 실제 MuJoCo geom 법선도 위 법선과 일치. 별도 Collider 기울기를 새로 추가한 문제가 아님 |
| 기존 Support 계약 | `table={object_id: table, placement_frame_id: world}`. 기존 sampler는 World XY에서 뽑고 World Z를 일정하게 계산하며, validator는 실제 회전 Table 좌표로 검사함 |

이전 historical sampler의 첫 후보를 동일한 과거 계산으로 재현했다. World XYZ는 `(-0.2013683893,-0.5867269112,0.0467367176)m`, Table 로컬 하단 Z는 `0.00895535136m`다. Table 윗면 로컬 Z=`0.025m`보다 **16.044648637mm 안쪽**이므로 기존 validator의 거부는 타당하다. 기존 범위는 Table 전체 bbox에서 margin을 뺀 중심 ±478/378mm이며 **150mm Workspace와도 다르다**. `+3mm` 높이만으로 이 넓은 경사면 전체에서 접촉 높이를 보장할 수 없다. 기존 validator를 완화하거나 v8을 수평화하지 않았다.

새 규칙은 실제 **Marker Object의 `object_marker` 로컬 평면**과 Collision 치수150×150mm를 사용한다. 이 평면은 v8에서는 World에 대해 기울어져 있으나, 실제 Table에 평행한 유효 배치 평면이다. 기존 Profile의 원점 `(0,0,0)` 및 Support의 legacy `world`와 Marker 중심을 혼동하지 않는다. 신규 수평 Scene에서는 이 로컬 +Z가 World +Z와 정렬되어야 한다.

## 구현과 수학·입력 계약

변경은 기존 [placement.py](../robot_learning_workbench/src/robot_learning_workbench/tasks/placement.py), 양 엔진의 source.py/reset_placements·datagen.py, [Builder project.py](../real2sim_builder/src/real2sim_builder/project.py)에 한정했다. 새 Manager/Collision Framework/Random Generator Framework·Dataset·Recipe 형식은 없다. T04의 `contact_pose`, convex hull 및 `polygon_distance`, S02 Transform, T01 FunctionSpec/검증, 기존 E05/DLS/Task·Native를 재사용했다.

`placement.random_workspace`는 명시 등록된 **DataGen용** 함수다. 예:

```yaml
objects:
  cube_red:
    placement:
      function: placement.random_workspace
      params:
        frame: object_marker
        support: table
        workspace: marker
```

세 물체를 배치할 때는 Recipe의 순서 있는 세 Object에 각각 위 함수를 선언한다. `workspace`는 실제 Scene Object ID, `frame`은 그 Object의 Frame ID다. 불명확한 별도 Workspace 크기/원점을 추측하지 않는다. Workspace·Support는 명시 box, 배치 Object는 box/compound primitive Geometry를 지원한다. Collision local_transform·scale·원점을 적용한다. 지원하지 않는 형상/동적 설치물은 검증 없이 통과하지 않는다.

- 실제 Collision 꼭짓점을 Yaw 회전한 후 `low=-workspace_size/2-min(vertices_xy)`, `high=workspace_size/2-max(vertices_xy)`를 계산한다. 기본150mm/24mm의 중심은 ±63mm다. 크기 변경과45° Yaw 경계를 시험했다. 63mm를 상수로 저장하지 않는다.
- 기본 Roll/Pitch는 Workspace 로컬0, Yaw 기본0이다. 선택적 `yaw_rad`를 주면 실제 회전 Footprint를 쓴다. World의 v8 기울기를 없애는 회전이 아니다.
- Z는 기존 T04 `contact_pose`로 실제 Support 윗면과 Collision 최저 꼭짓점이 접촉하도록 계산한다. 임의 clearance를 더하지 않는다. v8 Marker의 원점이 Table 윗면보다0.25mm 위이므로 기본 Cube 중심의 Marker 로컬 Z는 **11.75mm**다.
- 블록끼리는 convex Footprint 사이 Euclidean 최단 거리 **>=24mm**다. 축 정렬24mm 블록의 일렬 중심48mm, 대각선·겹침·Yaw·반올림 경계를 시험했다. Task 대상/목표 Cup의 역할을 유지하며 Cup을 grasp 대상 또는24mm 블록으로 재명명하지 않는다.
- 현재 collision-enabled 고정 물체/다른 작업 물체도 검사한다. Cup/compound의 전체 convex hull과 원통의64각 외접 prism은 **보수적인 오프라인 장애물 검사**다. 실제 PhysX/MuJoCo의 모든 곡면/오목 접촉을 완전히 대체하지 않는다. 로봇 링크/동적 장착물의 현재 Collision 전체는 native 검사 영역이다.
- 모든 대상의 후보를 먼저 계산한다. 아직 배치하지 않은 대상의 과거 위치를 장애물로 쓰지 않고, 앞서 계산한 새 위치와 고정 장애물을 검사한다. 대상의 순서를 바꾸지 않는다. Fixed/Random 혼합 대상 batch는 현재 명시 오류이며, 고정 장애물은 엔진의 현재 고정 상태로 제공한다.
- 이상적 float64 Pose뿐 아니라 **native XYZ/Quaternion payload**도 적용 전에 재검사한다. Isaac float32 변환으로 정확한24mm가 `23.9999983268mm`가 되는 반례는 거부한다. Pose 이동·경계 확대·관절 Clipping으로 통과시키지 않는다.

### 난수·예산·실패·기록

각 함수 호출은 `np.random.default_rng()`를 **인자 없이** 호출한다. Pose Seed/RNG 입력·XY/자세 override·RNG 상태 저장/복원은 없다. Recipe execution.seed와 Native claim.seed는 기존 Mimic/Attempt identity이며 Pose로 전달하지 않는다. 새 DataGen은 과거 `random_xy/contact_random_xy`의 Seed 경로를 명시 거부한다. 역사적 순수 sampler·Source·기존 Fixed 계산/Seed stream은 보존한다.

물체별 후보 예산은 기존 상수1000회다. 소진하면 `INVALID_PLACEMENT`와 Object/Frame/Workspace·조건·사유·시도 수를 남기며 무효 후보를 엔진에 쓰지 않는다. 전체 DataGen attempt는 기존 max_attempts의 유한 예산을 사용한다. 배치 실패도 실패 attempt로 seal/publish하고 성공 Episode를 만들지 않는다. 원본 Scene을 고치거나 외부에서 후보 예산을 초기화해 무한 재시도하지 않는다.

MuJoCo는 검증한 batch를 기존 native Reset에 전달하고 관통 검사 실패 시 integration state를 rollback한다. Isaac은 기존 공식 상태 복원 API를 사용하며 offline Geometry PASS를 physical Collision PASS로 표시하지 않는다. SDK Reset 실패는 `engine_reset_error/effect=unknown`; 부분 쓰기 가능성이 있으면 Object별 applied도 `unknown`이다. 이를 후보 거부/미적용으로 숨기지 않는다.

Native의 작은 실행 Metadata/attempt에는 Object/Frame, 로컬 Pose, 요청 World Pose, 실제 payload, 관측된 적용 World Pose, 유효성·physical 검사 범위와 실제 Task outcome을 남긴다. 대용량 관절/RGB는 기존 HDF5/MP4만 사용한다. 완료 Segment·영상은 새 출력 Resume에서 공유/보존하며 RNG를 복원하지 않고 새 Pose를 만든다. 새 규칙/code identity가 다른 과거 실행은 continuation으로 받지 않는다.

Isaac Random은 **한 fresh worker당 한 attempt**만 수행한다. 목표/예산이 남으면 `fresh_worker_required`를 결과에 남기고 종료한다. 다음 worker에서 Resume한다. 같은 앱 여러 Reset의 동등성은 계속 OPEN이며 자동 worker 반복 Manager를 만들지 않았다.

## 신규 Scene 수평 기준 준비

`real2sim_builder.project.validate_horizontal_layout(scene, *, table, workspace, blocks, robot_frame='robot_base')`는 기존 authoring Scene을 **읽기만 하는 opt-in 검사**다. 기존 `validate`나 v8 Export에 강제 적용하지 않는다.

명시 box Table·Workspace·블록을 지원한다. Table 실제 윗면/World +Z 정렬, Workspace 전체의 Table 포함과 실제 X/Y 치수, 블록 바닥 접촉·회전 Footprint 포함, Robot Base +Z 정렬을 검사한다. Table 높이와 Robot Base 위치를 독립적으로 반환하고 어떤 Z도0으로 바꾸지 않는다. 카메라·관절/URDF·고정 설치물의 회전을 덮어쓰지 않으며 `calibration_verified=False`를 반환한다. 일반 mesh/복합 Table 설치 기준면은 새로 승인된 기준면 계약 없이는 이 초기 box 검사로 검증됐다고 주장하지 않는다.

synthetic 메모리 fixture에서 높이0.5m, 별도 Base 위치(0.3,0,0.6)m, 기울어진 Camera 보존·Table/Base/블록/Workspace 기울기 거부·Workspace 전체/블록 경계 시험을 했다. **v9 프로젝트/Revision/실행 패키지를 생성한 시험이 아니다.**

향후 UI에서 별도 v9을 생성한 뒤 기준면/치수를 명시하고 이 검사를 적용한다. 그 뒤 Robot Calibration → Precision Calibration → 실제 Real2Sim Camera Capture → 실제/Simulation 오차 분석 → 필요한 추가 Simulation Calibration → 새 Revision Export를 진행해야 한다. 기존 v8 Calibration을 새 수평 Scene에 자동 승인하지 않는다.

## 실제 엔진 결과·회귀·한계

최종 수치는 [release MuJoCo](evidence/random-placement/release/mujoco-results.json), [release Isaac](evidence/random-placement/release/isaac-results.json), [공식 Reader/영상/수치 소비자](evidence/random-placement/release-consumer-results.json)에 있다. 개발 중 결과도 별도 폴더에 보존하며 누적 Resume Episode를 신규 생성 수로 중복 계산하지 않는다. 성공 여부는 기존 **StableGrasp AND Placement**이며 IK 미수렴과 별개다. 성공을 위해 Scene·Target·IK·Task threshold·Collision을 조정하지 않았다.

| 최종 release 결과 | 신규 Random Episode | 성공/실패 attempt | frame | 실제 최소 블록 간격 | 최초 StableGrasp post tick |
|---|---:|---|---:|---|---|
| MuJoCo 새 run→Resume | 2 | 성공2·실패0 | 각399 | 40.026377/54.284741mm | 230/230 |
| Isaac fresh worker→Resume | 2 | 성공2·실패0 | 각399 | 37.063701/29.488461mm | 230/229 |

최종 Random은 총 **4 Episode/1,596 control frame**이다. 이는 이번 작은 표본의 결과이며 성공률 추정이 아니다. 별도 개발 중 실행 결과는 이전 폴더에 보존했고 이 표에 합치지 않는다. IK native 미수렴도 안전 조건을 통과한 경우 기존 Best Effort 그대로 적용했다. 각 Episode의 미수렴 step은 MuJoCo84/83, Isaac63/82이며 실패로 숨기거나 수렴으로 재분류하지 않았다. 실제 양측 접촉이 있었고, 적용 arm jump 최대는0.352074694rad로0.5rad 경계 안이었다.

Fixed 회귀도 실제 MuJoCo 새 run→Resume 누적2 Episode, Isaac 별도 fresh worker1 Episode가 성공했다. [기존 Fixed 비교](evidence/random-placement/fixed-baseline-comparison.json)는 선택한8개 배열 경로(joint_targets/actions/pre·post q/grasp latch/applied command/cube_red pose)의 dtype/shape/값이 **모두 exact**임을 확인했다. MP4 픽셀 전체 동등성이나 기존 E01 cube–cup 잔차 해결을 의미하지 않는다.

최종 실제 MuJoCo Random 실행은8.829s, 새 Episode Resume6.701s였고 process peak RSS는1690.7/1984.8MiB였다. Isaac worker 전체 시간은108.657/102.256s, Fixed100.043s이며 AppLauncher·구성·렌더·저장·종료를 포함한다. Isaac Peak RSS/GPU peak는 이번 harness에서 별도로 측정하지 않아 수치를 만들지 않는다. 제어/영상30Hz는 계약이며 이 시간을 wall-clock30FPS로 보고하지 않는다.

Isaac에는 기존 tool0 visual 참조·Fabric/RTX/종료 warning과 보호 audit가 차단한 SDK material_cache 쓰기의 비동기 예외가 남았다. 실제 physics/렌더/Native 완료와 worker terminal은 확인했지만 warning-free라고 보고하지 않는다. 설치 경로 쓰기를 허용해 해결하지 않았다.

공식 Native Reader로 각399 frame을 읽고 measured pre[t+1]=post[t], pre-step latch=직전 post latch, float64 solver command/엔진별 actual payload, 원래30Hz timestamp를 검사했다. 초기 실제 root pose와 저장 initial은1e-15 비교, float32 저장 matrix 경계는 별도 오차 수치로 보고한다. Camera 양쪽640×480·30FPS·399 frame 전체 PTS를 확인하고 시작/중간/끝 실제 RGB를 decode했다. 영상 재인코딩이나 원 Dataset 수정은 없다.

실제 새 배치 적용과 physics 성공 증거를 controlled failure 시험과 구분한다. 1000회 소진·구조 오류·변경 치수·Yaw·24mm diagonal·부동소수점 payload 경계·SDK 오류/부분 쓰기·실패 claim seal/미완료 Episode0은 별도 fixture다. 실제 Random 취소/SIGKILL/전원 장애를 이번에 새로 주입한 것은 아니며 기존 Native/Workflow 회귀를 재실행했다.

**최종 전체895 passed, skipped0 = 기존868+신규27**. 기존 torchvision deprecation warning2개가 남는다. [JUnit](evidence/random-placement/unit-tests.xml), [최종 로그](evidence/random-placement/logs/47-final-suite.log). Workbench와 Builder wheel의 source bytes/compile·isolated import/CLI smoke를 확인했으며 환경에 설치하지 않았다. [Workbench build](evidence/random-placement/build-workbench.json), [Builder build](evidence/random-placement/build-builder.json). 별도 lint/type 도구를 설치하거나 실행했다고 주장하지 않는다. [명령·입력/코드](evidence/random-placement/commands.json), [최종 검증](evidence/random-placement/verification.json)에 범위와 산출물 SHA를 기록했다.

Standards 독립 리뷰 지적은 모두 해소했다. Spec 독립 리뷰의 초기4건과 추가 payload 반례를 수정했다. **마지막 수정 후 독립 Spec 재검토는 서비스 usage limit으로 실패**했으므로 최종 경계/부분 쓰기 진단의 closure는 주 에이전트의 source/RED→GREEN 검증이다. [두 축 리뷰](evidence/random-placement/spec-review.md), [Standards](evidence/random-placement/standards-review.md)에 한계를 기록했다. 단순화는 기존 Geometry·freeze·Native 함수를 재사용하고 별도 계층을 만들지 않는 범위다. Git 저장소가 없어 사전 파일 사본과 SHA를 사용했으며 commit/diff 절차를 수행했다고 보고하지 않는다.

[보존 대조](evidence/random-placement/preservation-after.json)는 원본56,100개 stat와 선택230개 SHA를 비교한다. 미승인 변화0이며 SDK·이전 입력/완료 보고서·선택 검증 root를 포함한다. 모든 대용량 corpus/SDK binary/과거 증거 전체의 전수 byte 검증은 아니다. Scene package 전체 Manifest를 재검증했다. 설치/환경 업그레이드·원본 Dataset 수정·외부 업로드·실물 연결은 없다.

기존 E01 cube–cup1.197188790mm 잔차·같은 Isaac 앱 복수 Reset/복수 Annotation·다중 env/장시간·SMOL-PAD-01·Follower command binding/motor range·physical_verified=false는 유지한다. 과거 Random RNG continuation 관문은 **이번 신규 entropy Pose 정책에는 적용하지 않으며**, 역사적 stream 동등성을 검증한 것으로 바꾸지도 않는다. 현재 실제 표본의 성공을 모든 Random 배치의 성공률·Grasp 접근 보장으로 일반화하지 않는다. **이번 작업까지만 수행하며 UI·v9 생성/Calibration·후속 구현은 시작하지 않는다.**
