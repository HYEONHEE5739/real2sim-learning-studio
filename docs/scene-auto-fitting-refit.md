# 새 Fitter 적용 · 종이 경계 조건 제거

2026-11-01. `scene-v9-joint-view`를 기준으로 새 자동 관측/`Candidate.fit('joint:scene')` 경로를 실제 실행했다. 선택 결과는 **`scene-v9-auto-fit`**, 원 Project의 Candidate는 `capture_20261101_auto_fit`이다. 원본/기존 Revision을 덮어쓰거나 Current를 promote하지 않았다. 실물 장치 연결·Goal/Torque·Training·Task physics 실행은 없다.

## 종이 경계 검사가 있었던 이유와 제거

사용자가 종이 안에 블록을 넣으라고 요구한 것은 아니다. 이번 새 Fitter 구현에서 추가한 과도한 조건이었다. 첫 실행의 `Object left its declared support: cube_red`는 실제 기존 배치가 종이 테두리에 걸쳐 있는데 전체 바닥 footprint가 종이 안에 있어야 한다는 검사에서 발생했다. 이후 겹침만 요구하도록 바꾼 중간 구현도 사용자 지시에 따라 제거했다.

`calibration/joint.py`에서 다음을 제거했다.

- `_support()`의 객체 중심이 support의 XY 사각형 안에 있어야 한다는 조건.
- 결과 저장 전 바닥 footprint 전체 포함/일부 겹침 검사.

현재 `supports`는 **어느 수평 높이에 Z를 결합할지** 정한다. 종이 테두리는 fitting 허용 영역이 아니며, 경계에 걸치거나 완전히 벗어나도 그 이유로 결과를 거부하지 않는다. 높이/upright, 사용자가 제공한 실측 치수·거리, q/URDF 보호, 수치 pose bound, 실제 관측 오차의 개선 여부는 별개로 유지한다. 테이블/종이를 늘려 검사를 통과시키거나 물체 Z를 바꾼 수정이 아니다.

기존 코드의 `scene.validate_horizontal_layout()`은 workspace/table footprint를 포함하는 **명시 호출용 초기 배치 진단**이다. `Candidate.save()`나 새 공동 fitter가 자동 호출하지 않는다. Workbench `tasks/placement.py`의 Reset support/명시 Random Workspace 검사도 Simulation 배치 함수의 계약이며, Scene 영상 정합의 종이 경계 저장 조건으로 사용하지 않는다. 이번에는 이 독립 기능을 변경하지 않았다.

## 사용 자료와 실제 선택

입력은 `real_sim_20261031_005103_ad8e28`의 기존 5개 Pair다. 원 Project에는 미결합 자료로 보관돼 있어, 별도 작업 Project에서 원 SHA·q·Mapping·source/baked URDF 관계를 대조한 뒤 기존 추정 Base/Camera에 결합한 **derived fit context**를 만들었다. 원 Evidence의 eligible=false나 원 Manifest/품질 판정은 바꾸지 않았다.

공식 Snapshot Reader의 품질 조건을 통과한 3개 자세/6개 이미지에서 자동 CV 제안을 만들고, Codex가 CAD 코너 대응 66개와 Mask 11개를 검토했다. Wrist 흐림 경고가 있는 나머지 2개 자세는 fitting에서 제외하고 결과 비교에만 남겼다. 이는 새로운 독립 촬영이 아니다. 같은 영상과 초기 Scene을 참고한 대응 선택이므로 in-sample 수치다.

공유 Side/Wrist/블록 변수를 함께 푼 첫 결과는 코너 RMSE를 줄였지만 실제 Native Wrist 그리퍼가 크게 나빠져 미채택했다. Camera prior를 강하게 둔 결과와 Camera를 고정한 결과도 비교했다. 현재 MVP에는 그리퍼 Mask 최적화가 없으므로 코너 자료만으로 카메라를 억지 조정하지 않았다. **최종 선택은 새 `joint:scene`의 Camera 고정 옵션으로 빨강/파랑 블록 XY/yaw만 보정한 후보**다. 초록 블록의 변경안도 silhouette 회귀로 제외했다. 전체 Camera/컵/그리퍼를 새로 더 정확히 보정했다는 결과가 아니다.

## 수치와 한계

- 선택 대응점 코너 RMSE **5.54384 → 4.75692px**. 자유 변수 6개, data Jacobian rank 6.
- Side 빨강 Mask IoU 평균 **0.9195 → 0.9258**, Side 파랑 **0.8189 → 0.8316**.
- 보이는 Wrist 파랑 사례의 Mask IoU **0.8065 → 0.8765**, 중심 오차 **3.84 → 1.18px**.
- **회귀도 있음:** Side 파랑 중심 오차 평균 **0.41 → 3.16px**, Wrist 빨강 중심 오차 **4.89 → 5.17px**. Mask IoU 개선을 모든 지표/모든 자세의 개선으로 표시하지 않는다.
- 카메라/K/distortion·로봇 모델/측정 q·Base·물체 치수/수평/높이·컵 90mm 관계·visual/collision/물성은 유지했다. 빨강 XY 변화는 약 `[+0.287, -0.128]mm`, 파랑은 `[-1.284, -1.176]mm`다.
- 닫힌 새 Package를 **MuJoCo/Isaac 각각 저장 자세 5개·RGB 10장**으로 실제 렌더했다. Physics Step 0. 적용 q 차이는 MuJoCo 0, Isaac 최대 약 `4.04e-8rad`다. 새 물리 접촉/Task/실물 보정 검증이 아니다.
- 원본 입력·기존 `scene-v9-joint-view`·관련 model closure 등 선택 **1,556개 파일 SHA 변화 0**. 전체 디스크 전수 hash가 아니다. 새 Candidate/Export/설정 등록만 추가했다.

소프트웨어 EGL/AMDGPU 초기화 경고와 기존 USD tool0 reference 경고는 로그에 보존했다. 양 엔진 렌더 worker는 exit 0으로 완료했다. 전체 pytest/UI/학습/장치 시험을 새로 수행한 것은 아니다. 새 Fitter의 모든 Scene/렌즈/가림/성능을 검증한 결과도 아니다.

## 위치

- [새 반투명 비교 페이지](../workbench_runs/scene_autofit_20261101/compare.html): 이전/이후·엔진·자세·투명도 선택. 원 RGB를 warp/이동하지 않는다.
- [검토 Package](../workbench_runs/scenes/pickplace-colorblock-b7a5592b/exports/scene-v9-auto-fit)
- [수치·보존 결과](../workbench_runs/scene_autofit_20261101/verification.json)

Real/Sim에는 `pickplace_colorblock / scene-v9-auto-fit`으로 새 Revision을 등록했다. 실행 중 사용자 창은 재시작하지 않았다. Candidate는 OPEN이고 Export는 UNVALIDATED review다. 로컬 작업이며 Commit/Push/Merge는 수행하지 않았다.

재현 자료는 `workbench_runs/scene_autofit_20261101/`의 `context.json`, `observe-refined.json`, `selections-final.json`, `fit-final-options.json`, `fit-final-report.json`, 초기 거부/미채택 보고서·실제 Native 비교·양 엔진 로그다. 작업 Context의 `auto_final`에는 승인 derived 관측이 남고, 원 Project Candidate에는 그 관측/설정/보고서의 이력을 저장했다. 자동 추출을 실측 Evidence로 재Import하지 않았다. 해당 Workspace와 자산은 기존 Git 공개 제외 정책을 유지한다.

후속 사용자 요청의 [Collision·PhysX 조사 및 실제 720 Step 확인](scene-physics-status.md)은 위 Fitting/Physics Step 0 렌더와 별도 실행이다. 현재 Package의 충돌체는 활성 상태였고, 후속 확인을 위해 기존 Scene이나 물성을 변경하지 않았다.
