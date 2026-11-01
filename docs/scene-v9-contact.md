# 촬영 기반 수평 Scene·양 엔진 외형·접촉 수정

2026-11-01 종합 정합: 최신 등록 Revision은 **`scene-v9-joint-view`**, Candidate는 `capture_20261101_joint_view`다. 직전 `scene-v9-wrist-restored`를 기준으로 Side/Wrist 각각의 optical 위치·방향·공통 fx/fy 초점거리, 블록의 XY/yaw, 컵 중심 거리90mm를 유지하는 공동 배치, 종이/테두리의 XY/yaw를 함께 fitting했다. 모든 자세는 하나의 Side와 하나의 Wrist mount/K를 공유하며 q·실측 치수·로봇 모델·지지 높이·수직축·Collision 형상/물성을 바꾸지 않았다. 적용 초점거리는 Side845.5→818.6px, Wrist544.5→556.9px이고 방향 변화는 각각 약2.04°/2.18°다. 초점거리는 배율을 정하는 값이며 원 촬영의 defocus를 복원한 것은 아니다.

평가는 블록만 보던 이전 방식에서 **Wrist 그리퍼 외곽·접촉 패드 표식·물체 윤곽·Cup rim·종이 경계·물체–그리퍼 pixel 간격**을 함께 보는 방식으로 바꿨다. 실제 Native 렌더는 양 엔진 각각5자세/10장·Physics Step0이며 모두 exit0이다. RGB로 추출한 보라색 그리퍼 경계의 평균 대칭 오차는 MuJoCo4.81→2.76px, Isaac4.84→2.75px이고 양쪽 모두5개 자세에서 감소했다. 보이는 블록4개 사례의 실제 RGB 간격 오차는 최대2.06/2.39px다. 이는 영상 내 추정이며 실제3D 거리/실물 접촉의 계측 결과가 아니다. 회색 패드 중심은 수동 추정 표식 대비 약11.5px 잔차가 남고, 표식 불확실성·촬영 blur·가림도 남는다. **전체 그리퍼가 완전히 겹친다고 주장하지 않는다.**

같은5개 기존 관측을 fitting과 비교에 사용했으므로 독립 검증은 아니다. Side의 일부 물체/자세별 윤곽에는 약1px 정도의 국소 회귀가 남는다. 목표 그룹을 함께 비교한 검토 후보로 게시했으며 물리 Calibration/Task 성능 승격은 없다. 원 관측과 직전 Package237개 파일 SHA 변화0, 컵90mm·수평·높이·치수/로봇/원 Collision 보존을 확인했다. 제품 코드·SDK·실물 장치에는 변경/연결을 하지 않았다.

`compare.html`은 현재/이전 기준·엔진·자세·투명도를 선택하고 **Wrist 그리퍼 동일 영역2배 확대 겹침**을 제공한다. 이미지 좌표를 warp하거나 이동해 맞추지 않는다. 근거는 `joint-selected.json`, `joint-view-verification.json`, `scene-v9-joint-view/*-native-metrics.json`, `joint-observations.json` 및 작은 fitting/미채택 실험 기록이다. Scene Package는 `exports/scene-v9-joint-view`, 설정은 `configuration/scene-v9-joint-view-{mujoco,isaac}.json`이다. 원래의 Current authoring Scene은 별도이며 Candidate는 OPEN/review Export다.


2026-11-01 Wrist 회귀 수정: **당시 복원 Revision은 `scene-v9-wrist-restored`**다. 앞선 `scene-v9-aligned`는 블록 mask IoU가 좋아졌지만 같은 Wrist 영상의 컵 rim 중심 추정 오차가 A 약20→37px, B 약26→34px로 커졌다. 블록 지표만으로 전체 화면의 개선을 판단한 것이 원인이며, 해당 후보를 REJECTED로 바꾸고 실행 목록에서 철회했다. 원 Package와 비교 근거는 보존한다.

Wrist optical pose·K와 컵 배치/부착 decal을 `scene-v9-no-cable` 값으로 복원하고, 블록의 수평 XY 조정만 유지했다. 책상/베이스 수평·물체 크기/높이·컵 중심 거리90mm·관절/SDK/충돌은 그대로다. 복원은 새 Candidate `capture_20261101_wrist_restore` 및 새 Package로 작성했다. 이는 Wrist를 이전 기준으로 되돌린 조치이며 전체 실측 정합을 완료했다는 뜻이 아니다. 비교 페이지의 기본값을 복원 결과로 바꾸고, 문제가 있던 aligned도 별도로 선택해 확인할 수 있다. 근거는 `wrist-check-*.json`, `wrist-ablation/results.json`, `wrist-restoration-report.json`이다.


복원 후 양 엔진 각각 5자세·10장 Native 렌더를 완료하고 exit 0을 확인했다. 모든 자세의 Wrist optical transform/K가 이전 기준과 일치하며, 컵 rim 회귀 검사는 RED→GREEN으로 통과했다. 보호 파일237개 SHA 변화0을 확인했다. 원래 남아 있던 컵/팔 외형 잔차까지 해결한 것은 아니다.


2026-11-01 앞선 추가 정합(이후 Wrist 회귀로 철회): Revision은 **`scene-v9-aligned`**, Candidate는 `capture_20261101_alignment`다. 기존 5개 관측을 사용해 블록의 수평 위치와 하나의 공통 Wrist optical mount·focal을 함께 조정했다. 컵 배치는 실측 중심 거리 **90mm**와 동일 지지면을 유지하는 공동 이동/회전으로 제한했다. 책상·로봇 베이스·물체 수직축, 측정 q·로봇 모델·물체 치수·높이·충돌·물성은 유지했다. Side 카메라를 변경한 두 실험은 자세별 회귀 때문에 채택하지 않았다. 손목 카메라 외형과 팔 윤곽 잔차는 남으며, 이번에 해당 로봇/외형 geometry를 수정했다고 주장하지 않는다.

양 엔진의 실제 Native measured-q 렌더를 각각 **5자세·Side/Wrist 10장** 수행했고 두 프로세스 모두 exit 0으로 종료했다. RGB 색상으로 추출한 블록 mask 13개(320×240)의 평균 IoU는 MuJoCo **0.690→0.850**, Isaac **0.687→0.849**이며 각 13개 비교 모두 개선됐다. 이 값은 Scene 전체 정확도나 물리 검증 점수가 아니다. 같은 기존 자료를 fitting/비교에 사용했으므로 독립 검증이라고 부르지 않는다. 컵 rim 표식은 수동 pixel 추정이며 별도 실측 Calibration을 대체하지 않는다.

`workbench_runs/scene_refinement_20261031/compare.html`에서 자세·엔진·**개선 전/후**를 선택해 원본과 반투명 겹침을 확인한다. `alignment-report.json`에 엔진별 원 수치, Manifest identity와 보호 파일 **237개 SHA 변경0**을 기록했다. `alignment-joint-fit.json`, `alignment-objects-constrained-fit.json`과 폐기한 fitting 보고서를 함께 보존한다. 새 Package는 `exports/scene-v9-aligned`, 설정은 `configuration/scene-v9-aligned-{mujoco,isaac}.json`이다. Candidate는 OPEN/review Export이고 물리 Calibration 승격·실물 연결·추가 촬영·제품 코드 변경은 수행하지 않았다.


후속 외형 수정: 카메라 위로 길게 나온 `wrist_camera_cable`을 사용자 요청으로 제거한 **`scene-v9-no-cable`**을 등록했다. 케이블의 visual/collision만 제거하고 나머지 물체·카메라·Calibration은 동일하다. 아래 `scene-v9-contact`는 직전 물리/정합 검증 기준이며 보존한다. 비교 페이지는 최신 케이블 제거 렌더를 표시한다. 근거는 `workbench_runs/scene_refinement_20261031/no-cable-verification.json`이다.

케이블 제거 후 양 엔진 각각 5자세·10장(640×480)을 재렌더하고 확인했다. Isaac은 결과 저장 후 프로세스 종료 코드143(SIGTERM)이므로 정상 종료 검증과는 구분한다.

2026-10-31. `real_sim_20261031_005103_ad8e28`의 저장된 다섯 자세를 사용했다. 실제 장치 연결·Goal/Torque 명령은 없다. 기존 v8과 촬영 원본은 보존했다.

## 사용할 Scene

Project: `workbench_runs/scenes/pickplace-colorblock-b7a5592b`

실행 Revision: **`exports/scene-v9-contact`**. Real/Sim에서 `pickplace_colorblock / scene-v9-contact`를 선택한다. Source의 Project 선택은 등록된 최신 Revision을 사용한다. 기존 v8도 선택 목록에 유지한다. 실행 중인 창/Worker를 자동 재시작하지 않았다.

Manifest SHA: `841525fca2bc454e757666dc5a669af9794f084e91f7aaf5eed9db706b0368b6`

양 엔진 설정은 `configuration/scene-v9-contact-mujoco.json`, `configuration/scene-v9-contact-isaac.json`이다. Builder 후보는 `scratch/agent/capture_20261031_upright`다. 후보는 OPEN이며, 독립 실측 Calibration을 통과한 ACCEPTED Scene으로 승격하지 않았다. 기존 `working/current_scene.yaml`도 덮어쓰지 않았다. 다음 정합 작업은 이 후보 또는 새 실행 Package의 `authored_scene.json`을 기준으로 시작한다.

[다섯 자세 Real / 이전 MuJoCo / 새 MuJoCo / 새 Isaac 비교](../workbench_runs/scene_refinement_20261031/compare.html)

## 변경 내용

- Table·Marker·세 Block·두 Cup의 Z축을 정확히 수직으로 유지했다. Robot Base는 수평 좌표 기준을 유지한다. 관절 자세·카메라 장착 각도·가로로 누운 배경 롤러를 임의로 직립시키지 않았다.
- Side 사진의 Marker 모서리와 Block 윗면 중심 7점을 수동 추정해, K와 물체 치수를 고정하고 Side Camera pose만 맞췄다. 초기 좌표별 RMSE 약 41.2px에서 약 3.8px로 줄었다. 사진에서 추정한 같은 Session의 맞춤 점이며 독립 검증이나 물리 Calibration 인증이 아니다. Wrist Camera/Precision/q는 수정하지 않았다.
- Isaac을 기준으로 MuJoCo 로봇 색을 맞췄다. 새 Scene의 MuJoCo 설정에만 `visual_color_gamma=1/2.2`를 사용하고 로봇 reference 색을 조정했다. 원 사진이나 저장 RGB에 후처리 보정을 하지 않는다. 기본 gamma=1은 기존 동작을 유지하며, 별도 precompiled MJCF에는 이 설정을 조용히 무시하지 않고 거부한다. 그림자·표면 반사·배경 처리 차이까지 pixel-identical하지는 않다.
- Isaac 카메라 부품 누락은 `AssetBase`가 USD의 장착 변환을 기본 원점으로 덮어쓰는 문제였다. `env_cfg.py`에서 실제 link-local 위치/회전을 초기 상태로 전달한다. 수정 전 부품이 원점에 겹치는 것을 재현했고, 수정 후 검사한 부품의 행렬 최대 오차는 약 `6.2e-8` 이하였다.
- Table/Block/Cup에는 기존에도 충돌 선언이 있었다. 새 설정에서는 배경 롤러·카메라 몸체 등 물리 부품의 충돌도 활성화하고, 잉크·Marker 테두리 같은 장식은 별도 두꺼운 장애물로 만들지 않았다. Block friction은 추정값 1.4로 설정했다. 실측 마찰계수가 아니다.
- Isaac 손가락은 전체 형상을 감싼 convex hull 때문에 MuJoCo와 다른 위치에서 잡혔다. 새 USD overlay에서 기존 손가락 collision group을 비활성화하고, MuJoCo가 쓰는 동일한 convex 분할 vertices/faces와 URDF local transform을 사용한다. 실제 1mm contact pad는 유지한다. 원 USD/URDF/SDK는 수정하지 않았다.

## 실제 검사

- 최종 Revision의 MuJoCo·Isaac 각각 저장된 다섯 measured-q를 적용하고 Side/Wrist를 렌더했다. Isaac 최종 렌더 프로세스는 exit 0이었다. Real/Sim의 이 경로는 계속 Physics Step 0 상태 미러링이다. 여기서 물체를 물리적으로 집어 올리는 작업과 Source/물리 시뮬레이션을 구분한다.
- MuJoCo 실제 물리 검사: Table 위 세 Block 안정화, 무중력 상태에서 손가락을 닫은 뒤 중력을 켠 합성 hold를 검사했다. 약 1.50초 hold의 상대 미끄러짐은 약 0.0091mm였다. World 위치 변화 약 5.33mm는 대부분 팔 처짐이므로 slip으로 혼동하지 않는다.
- Isaac: 30mm 위에서 Block을 떨어뜨려 Table/Marker 높이로 내려와 정지하는 것을 확인했다. 480 step/2초 검사다. 최종 분할 충돌체의 합성 grasp는 양쪽 약 4.77/4.79N, 0.5초 이후 상대 위치 변화 약 `4.0e-8m`였다. Fixed pad 평면과 Cube 면은 약 0.40mm 수치 침투 상태이며, 양의 공중 간격으로 잡히는 상태가 아니다. 초기 수렴 구간을 제외한 이 수치를 일반적인 성공률로 사용하지 않는다.
- Isaac 물리 probe는 결과 저장 후 종료에서 exit 139가 발생했다. 결과 파일과 계산 완료는 확인했지만 프로세스 전체 정상 완료로 보고하지 않는다. 기존 tool0 visual reference/Fabric 경고도 남아 있다. 실제 장시간 Task/모든 자세의 안정성은 미검증이다.
- Builder·Scene Contract·이번 appearance 시험은 **246 passed**. 전체 기존 회귀는 **1,089 passed / 71 failed / 28 errors**다. 삭제된 과거 USD/Checkpoint Evidence 참조 실패와 기존 UI·함수 이관 불일치가 포함된다. 이번 범위 밖 실패를 고치거나 전체 통과로 표시하지 않았다.

## 보존·근거

원 v8 및 해당 촬영 자료 **235개 파일 SHA 변화 0**. 기존 Scene/SDK/Precision/Dataset/Checkpoint 원본 변경, Git Push/Merge는 없다. 이번 제품 수정은 MuJoCo 색 변환과 Isaac 장착 변환이며, 기존 작업 트리의 다른 수정은 보존했다.

근거는 `workbench_runs/scene_refinement_20261031/`의 `final-verification.json`, `mount-check-red.json`, `mount-check.json`, `appearance-comparison.json`, `contact-probe.json`, `isaac-drop-result.json`, `isaac-grasp-before.json`, `isaac-grasp-result.json`, 각 렌더와 로그다. 중간 `scene-v9-upright*`는 검토 이력으로만 남기고 UI 등록에서는 제거했다. Workspace/자산/검증 출력은 기존 Git 제외 정책을 유지한다.

이 결과는 수평 제약 아래의 시각 정합 및 제한된 시뮬레이션 접촉 수정이다. 물리 정확도, 마찰의 실측 인증, 모든 자세의 무미끄럼, 전체 회귀 통과를 뜻하지 않는다.
