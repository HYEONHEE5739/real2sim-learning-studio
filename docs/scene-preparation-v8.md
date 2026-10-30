# Scene 준비·v8 데이터 소유권 이관·장치 설정

후속 변경: [수동 Teleoperation 설정 제거·Precision 기준각·일반 Builder Export 연결](precision-export-integration.md). 아래 내용은 당시 검증 기록이며 현재 실물 Teleoperation 차단 상태는 후속 문서를 따릅니다.

2026-10-29. 기준 `8b565968542fcfbe8df37a71dd70ff1e2274c336`, 브랜치 `scene-preparation-v8`. **`pickplace_colorblock`을 현재 Workspace에 실제 생성하고, 이전 프로젝트 폴더 접근을 차단한 환경에서 Builder·보존 자료·양 엔진·Qt 설정 복원을 확인했다.** Capture의 기본 수동 Profile 폼과 추가 runtime joint offset 경로는 제거했다. 선택 Input/자유 메모와 장치 선택 중심의 한 구현으로 교체했다. 기존 공통 SDK·Precision·Encoding·Builder·R03 계약은 유지한다.

## 실제 위치와 사용

- Project: `/home/hyeonhee/imitation_learnig_project/workbench_runs/scenes/pickplace-colorblock-b7a5592b`
- UI 표시 이름: **`pickplace_colorblock`**
- 닫힌 실행 Package: 위 Project의 `exports/scene-v8-native`
- 장치 구성: `workbench_runs/devices/so101-pickplace-0b794e7c/capture.yaml`
- 실행 엔진 설정: Project의 `configuration/mujoco.json`, `configuration/isaac.json`
- 원본·Revision 근거: Project의 `input/migration/`

`./run_workbench_ui.sh` → Capture 또는 Real/Sim에서 Scene을 선택한다. `workbench_runs/scenes/*/project.yaml`을 조회하므로 이름으로 Project를 찾을 수 있다. 저장 장치 구성이 자동 선택되지만 포트를 열거나 Torque를 켜지 않는다. Real/Sim은 Current authoring Scene 또는 검토 Candidate와 엔진을 선택한 뒤 연결한다. Stage별로 부족한 Model/Mapping/Camera 조건을 확인한다.

Qt runtime도 이전 SO101 폴더에 있었으므로 기존 설치 bytes를 `workbench_runs/runtime/qt`에 복사했다. 새 설치/업그레이드는 하지 않았다. 실행 스크립트는 이 경로를 기본으로 사용하며 `QT_PYTHON`으로 별도 준비된 Qt interpreter를 지정할 수 있다. Backend·Isaac Lab은 기존 프로젝트 밖의 설치 환경을 사용한다. 이 로컬 runtime과 Scene 자산은 Git 공개 대상이 아니다.

## 이관 항목·새 소유권

기존 Builder Project 전체를 Clone한 결과가 아니다. 현재 `Project.create`/`Candidate.create`로 새 lifecycle을 만들고 필요한 실제 데이터를 소유 경로에 등록했다.

| 자료 | 현재 처리 |
|---|---|
| 기존 Canonical Scene | 원 Scene bytes/SHA를 `input/migration/source-scene.yaml`에 보존. 현재 authoring Scene은 새 이름·소유 모델 경로·명시 Geometry Binding으로 구성 |
| Input Evidence | 실제 이미지14장, 기존 Snapshot Dataset1개/관측9개(상태 그룹별7/1/1개) 및 관련 원본·Metadata·측정·시각·Calibration 근거를 내부 상대 경로로 보존 |
| Candidate5개 | 현재 Candidate API로 OPEN Revision 생성. 원 Candidate Scene/상태/보고서/수치/이미지 및 검증 가능한 Reconstruction 근거는 별도 이력으로 보존. 과거 ACCEPTED를 새 승인으로 승격하지 않음 |
| URDF/Mesh/Texture/Camera | authoring Input closure와 기존 v8 실행 Package 전체를 소유. Intrinsic/Extrinsic·Robot Base·Geometry는 기존 선언/검증 상태 유지 |
| 실행 Package | 파일85개, Manifest84개 항목. Isaac USD/Collision·MuJoCo·물성·Robot 모델 bytes와 기존 Revision identity 유지 |
| Device/SDK Calibration | Leader/Follower 구성과 원 SDK 보정 bytes를 별도 `workspace/devices/`에 보존. Scene에는 구성 경로·SHA·자동 연결 금지를 Binding |
| Precision | 기존 사용자 0도 기준 Profile와 원 모델 SHA/limit-only 증거를 복사. 물리 정확도·명령 안전 범위를 자동 승인하지 않음 |
| 엔진 설정 | 검증에 사용한 설정의 원 bytes/SHA를 이력으로 남기고 `package_root`만 소유 Package로 바꾼 실행 설정 등록 |

Authoring 이관 기록은1,225개 파일 관계를 남긴다. 약507MB의 생성 중간 Blender/임시 baseline bulk는 실행 입력이 아니므로 재복제하지 않았다. 필요한 Candidate 근거와 닫힌 실행 자산은 보존했다. 실제 입력 약48.6MB와 닫힌 Package 약185MB 등은 `.assets/<SHA>`의 소유 bytes로 복사한 후 Workspace 내부 hardlink로 공유한다. **원본 폴더 파일을 hardlink하여 삭제·수정 수명에 종속시키지 않았다.** 이전 위치는 provenance 문자열로 남을 수 있으나 실행 파일 위치로 사용하지 않는다.

기존 실행 Revision은 `scene2-final-contact-review-20261014-932c8f2e / scene-v8-native`, Manifest SHA는 `64bff80050a883880e7e6363dd3e5b2f517fd72bb96743e3e529c89a2dfaa3c9`다. 새 Project는 이 닫힌 Revision의 소유권과 원 Project 관계를 기록한다. 새 authoring Scene이 기존 Package를 재Export한 것처럼 표시하지 않는다. 새로운 물리 검증/v9 생성은 하지 않았다.

## SDK·Precision·Residual의 구분

SDK Calibration은 개체의 Raw Encoder→SDK degree/percent 해석이다. Precision은 기존 사용자 기준 자세→model rad Mapping이다. 둘의 bytes·모델/개체 identity·역변환/정수 encoding 검사를 유지한다.

삭제한 것은 authoring의 `simulation_joint_offsets_rad`를 읽어 매번 측정 q에 더하던 추가 실행 경로와 그 시험이다. 현재 Scene 검사는 이 구형 필드를 명시 거부한다. 역사 Scene에는 원 필드를 그대로 보존했다.

기존 v8의 Geometry에 이미 baked된 보정은 제거하거나 새로 맞추지 않았다. 원 측정 모델 SHA는 `31da65a5af2b9b49531a79a410ca84e1cfe3eeac850818a330c2c8514f992960`, baked 실행 모델은 `f78814de0d341a4a46b2d37759e9206be7d66bca8445ea6867058c43dd6cd589`다. Current 및 해당 과거 Candidate는 기존 Package의 명시 baked Geometry record와 Mapping에 결합한다. 원래 residual이 없던 Candidate는 unbaked 모델을 유지한다. **적용 q는 측정 q 그대로이며 추가 delta는0이다.**

세 수치 자세에서 과거 FK(q+offset)와 기존 baked URDF의 FK(q)의 최대 행렬 원소 차이는 약`1.055e-15`였다. Geometry 의미를 확인한 수치 시험이며 실제 물리 정확도 증명이 아니다. Package Manifest와 model/mapping identity는 준비·실행·변경 감시에서 다시 확인한다. Identity에서 제외한 port는 좌표 보정값이 아닌 로컬 연결 정보뿐이다.

## 장치 선택과 새 사용자 흐름

장치 설정의 기본 화면은 Robot(SO-101/카메라만)·Leader·Follower·Side·Wrist·검색/저장/상태다. 기존 Profile 경로 폼 및 출처 없는 명령 budget 기본값을 제거했다. 고급 Recipe JSON/YAML에서 Model·Precision·SDK Calibration·명령 제한·Camera 세부 설정을 명시 편집할 수 있다. 기존 검증 구성에서 카메라만 바꾸면 같은 역할·USB 개체의 Calibration/Precision/Model 참조는 유지한다. 다른 개체에는 기존 보정을 이어 붙이지 않는다.

SO-101 포트는 저장된 USB serial/VID/PID를 현재 OS 검색 결과와 대조한다. `/dev/ttyACM0`를 Leader로 가정하지 않는다. 누락·중복·다른 개체는 연결 전에 거부하며 사용자가 해당 장치를 선택해야 한다. Camera는 기존 `/dev/v4l/by-id/...-video-index0` 경로를 복원한다. 현재 연결 장치의 물리 Side/Wrist 역할을 영상 내용으로 추측하지 않는다. USB serial이 없거나 여러 장치가 모호하면 자동 승인하지 않는다.

새 SO-101은 장치 선택으로 구성 파일 위치와 개체별 SDK 보정 출력 경로를 준비한다. 존재하지 않는 보정값을 생성하지 않는다. **SDK Calibration 버튼**은 현장 감독 확인 후 별도 R03 Worker에서 공식 `calibrate()`를 호출한다. 공식 `input`과 Range 기록의 `enter_pressed()`를 UI 응답·현재 prompt ID·취소·deadline에 연결한다. 공식 motor range 계산은 복제하지 않는다. 이 절차는 Torque Disable·Operating Mode/Homing/Calibration 레지스터 쓰기를 포함하므로 사용자의 현장 응답이 필요하다. 기존 보정 파일은 덮어쓰지 않는다. 이번에는 실제 보정 쓰기를 실행하지 않았고 실제 공식 Range 숫자 루프를 사용하는 Fake로 완료/취소를 검증했다.

새 개체에 사용자 Precision/model 결합이 없으면 SDK-native 관측 또는 Camera-only 경로 `scene_capture`를 사용한다. 기존 mapped Snapshot/Pair Session에 mode 분기를 억지로 추가하지 않았다. Builder의 기존 reference image/document Evidence에 원 RGB·수신 시각·Raw/SDK native 측정을 저장하며 `model_state=null`, `action=null`, Calibration 적격성false다. 임의 model-rad 관절값·6축 학습 Action·새 Dataset 포맷을 만들지 않는다. model-rad 결합이 있는 기존 장치는 기존 Snapshot/Pair 계약을 계속 사용한다.

실물 Teleoperation은 기존 별도 현장 승인·새 proposal·현재 Goal/Feedback·model/motor/Precision 교집합·Encoding·watchdog 경계를 유지한다. 명령 변화/추종 budget은 관측에 필요하지 않으며 **값이 없으면 motion proposal을 거부**한다. 이관 장치 구성에는 임의 motion budget을 넣지 않았다. SDK 보정 완료를 Precision 정확도나 실물 6축 구동 승인으로 표시하지 않는다.

## 선택 Input·메모와 UI 책임

Capture 오른쪽은 Input Data 추가·등록 목록·밝은 자유 메모·Scene 자료 저장이다. URDF/Mesh/GLB/사진/측정은 모두 선택 사항이다. 기존 Builder `add_image`/`import_scan`/`copy_native_asset`/`add_brief`를 사용한다. 빈 Project·빈 메모·메모만·사진/자료만·GLB만·URDF closure만 저장하고 재개방했다. 없는 Robot Base/K/Extrinsic을 identity나 가짜 측정값으로 채우지 않는다. Reconstruction/Export/Render 준비가 부족하면 해당 검증에서 이유를 표시한다.

| 파일 | 현재 책임 |
|---|---|
| `scene_preparation.py`, `scene_migration.py` | 선택 자료 저장/조회, 명시 데이터 소유권·Revision 이관 |
| `robot/registration.py` | 영속 로컬 구성·USB discovery/해석·Scene Binding |
| `ui/scene_inputs.py`, `ui/device_setup.py` | 선택 입력/메모 버퍼, 기본 장치 선택·고급 Recipe·감독 Calibration UI |
| `robot/scene_observation.py` | model 미결합 RO 관측→기존 Builder Evidence |
| `robot/sdk_calibration.py` | 공식 SDK interactive 입출력을 R03에 연결한 별도 감독 절차 |
| 기존 Session/Candidate/Renderer | 검증된 mapped 관측·명시 Teleoperation·Pair·렌더·저장 수명 유지 |

구형 `ui/session_settings.py`와 해당 파일 중심 기본 UI 시험은 삭제했다. 새 기능이 이전 실행의 호환 분기로 공존하지 않는다. Session 화면 약221줄, 장치 설정 약121줄, 입력 패널21줄로 역할을 나눴다. UI는 motor 계산을 하지 않는다. Scene 선택 조회 중에는 실행·자료 편집을 잠그고, 실패 시 이전 Project/장치 구성으로 실행하지 않는다. 동일 Dataset 안의 서로 다른 Snapshot ID도 각각 표시한다.

[Capture1320](evidence/scene-preparation-v8/capture-1320.png) · [1920](evidence/scene-preparation-v8/capture-1920.png) · [Real/Sim1320](evidence/scene-preparation-v8/real_sim-1320.png) · [장치 설정](evidence/scene-preparation-v8/capture-device-setup.png) · [실제 Camera-only Capture](evidence/scene-preparation-v8/new-user-camera-capture.png) · [선택 Snapshot 상세](evidence/scene-preparation-v8/selected-snapshot-detail.png). 기존 v8 Scene 선택 화면은 연결 전 상태이며 예시 FPS/관절값을 실제 측정으로 채우지 않았다. Camera-only 화면은 실제 카메라 RGB이고 model-rad는 미결합이다.

## 실제 격리·E2E 결과

원본을 삭제하지 않고 `bwrap`으로 **`/home/hyeonhee/soarm_isaaclab` 전체를 빈 디렉터리로 가렸다.** 현재3개 소스 패키지·소유 Workspace·기존 외부 SDK 환경으로 실행했다. 장치 검색은 OS metadata만 읽으며 별도 audit는 실제 Serial 사용 및 원본/설치 SDK 파일 쓰기를 막았다. Camera-only 시험은 Serial spec 자체가 없는 구성으로 실행했다.

| 시험 | 실제 결과 / 한계 |
|---|---|
| Builder/근거 | Project 열기, 이미지14장 SHA, Snapshot9개/세 scene-state의 공식 Reader, Candidate5개, 모델 closure·보정·구성·원/소유 Manifest 재로드 |
| MuJoCo | 소유 v8의 실제 Native 실행 모델 compilation, authoring Current Scene의 양640×480 실제 렌더. 새 Training/DataGen 시험 아님 |
| Isaac | 소유 v8 실제 ManagerBasedEnv 로딩·Reset·6축 측정 상태·양 Camera sensor 소비. 별도 Current Scene static Candidate 렌더도 완료. 실제 로봇 연결 없음 |
| Qt 자동 복원 | Capture/RealSim의 `pickplace_colorblock` 목록·이름·장치 구성·Camera/USB 선택 복원, 연결 시작0,1320/1920 화면 확인 |
| 새 사용자 Camera-only | 새 빈 Scene 생성→메모/문서→카메라 선택/구성 저장→실제 R03 Capture2개→Builder 자동 등록→종료→새 창에서 자료/메모/장치 복원. URDF/Precision/Serial device 생성0 |
| mapped Capture/Pair | 명시 MEMORY 장치, 기존 mapped Snapshot2·실제 MuJoCo Pair2 및 MEMORY에만 자동 승인한 Teleoperation. 실제 모터 동작과 구분 |
| SDK setup | 선택 구성/기존 보정 보존/개체 변경, 공식 Range loop Fake·취소·메시지/파일 보호. 실제 SDK Calibration 쓰기 미실행 |

Isaac은 기존 USD tool0 reference/Fabric/렌더·종료 경고와 audit가 막은 SDK Material cache 쓰기 예외를 남겼다. 정상 로딩·센서 소비 및 terminal을 별도 확인했으며 warning-free라고 주장하지 않는다. 초기 harness의 Snapshot scene-state 선택 누락, sensor 이름 오류, 닫힌 output 재사용 오류는 별도 실패 로그로 보존하고 새 출력에서 다시 검증했다. 실제 Source/Task gate·Native Physics trajectory 동등성이나 실물 정확도 검증으로 해석하지 않는다.

## 회귀·보존·완료 범위

**최종 전체 1,145 passed / skipped0**다. source/config-byte wheel 검사는 로컬 `docs/evidence/scene-preparation-v8/verification.json` 및 JUnit에 고정한다. 기준1,122개 대비 순증23개이며, 폐기한 기본 Profile UI 시험을 신규 사용 흐름 시험으로 교체한 결과도 포함한다. 기존 torchvision deprecation 경고4회는 남는다. ACT/SmolVLA/Diffusion·Recipe/Hub/Qt·Builder·Scene Contract·Native/Resume/Curation의 회귀를 수행했다. 새 학습이나 정책 weights 다운로드는 하지 않았다. wheel은 증거 폴더에서 빌드·compile·격리 import/CLI 및 실제 invalid-config Worker를 검사했고 설치하지 않았다. 별도 lint/type 도구 설치·실행은 없다.

독립 Standards/Spec 리뷰에서 SDK Range Enter/취소, 설정 요청 경합·파일 오류, Geometry Manifest 감시, 같은 개체 보정 보존, 실패 Scene 선택의 이전 Project 사용 문제를 재현·수정했다. 현재 두 축 High/Medium 잔여0이다. 마지막 Snapshot 목록·상세의 선택 ID 불일치도 별도 RED→GREEN으로 닫았다. 이전 경로 격리 상태에서 실제 `snapshot_000009`의 원본4장만 상세에 표시되는 것을 확인했다.

원본56,100개 stat·원본 Python187개 SHA·선택 과거/SDK57개 SHA·보존 Policy/Capture 입력47개 SHA 변화0, 원본/소유 v8 전체 Manifest identity 일치를 확인했다. 전체 SDK binary/corpus 전수 byte hash는 아니다. Source·Scene/Calibration/Dataset/Checkpoint·설치 SDK를 수정·이동·삭제하지 않았다. main은 `ab94b87d3f579031db0c751f274c0ab7fe6b87e6` 그대로이며 Push/Merge는 수행하지 않는다. Workspace/자산/증거/runtime은 기존 `.gitignore` 공개 제외 정책을 유지한다. 기준 Commit 대비 변경은 제품 코드24개·시험12개·문서/실행 스크립트6개, 총42개 파일(+1,388/−285줄)이다. 폐기한 `ui/session_settings.py` 삭제를 포함한다. 변경 파일 목록은 로컬 `final-changed-files.json`에 남겼다.

남은 실제 검증은 새로운 개체의 현장 SDK Calibration, Precision/Camera/Base의 실측 정확도·장시간/장치 장애, 승인된 실제6축 Teleoperation과 Task 성공이다. 이번 실물 Goal/Torque 명령은0이다. 기존 E01 cube–cup1.197188790mm 잔차·physical_verified=false를 승격하지 않았다. 이전 폴더는 삭제하지 않았으며 사용자가 삭제하기 전에도 필요한 로컬 runtime/Workspace와 설치 SDK 환경은 별도로 보존해야 한다. 이번 결과는 독립 로딩/자료 제작·관측/렌더 범위의 검증이며 모든 장치·Scene·장시간 실행의 보장이 아니다.

근거: `inventory.json`, `migration-result.json`, `geometry-binding-analysis.json`, `independence-builder-mujoco.json`, `independence-native-isaac.json`, `ui-independence.json`, `new-user-camera-results.json`, `memory-results.json`, `tests-final-detail.xml`, 두 wheel 결과·보존 대조·RED/GREEN 및 두 축 리뷰. 기존 증거 폴더는 Git에 올리지 않는다.

공식 경계: [pySerial USB metadata](https://pyserial.readthedocs.io/en/latest/tools.html#serial.tools.list_ports.comports), [Qt 다중 파일 선택](https://doc.qt.io/qt-6.11/qfiledialog.html#getOpenFileNames), [LeRobot0.4.1 SO101 Calibration](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/robots/so101_follower/so101_follower.py), [공식 Motor range loop](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/motors/motors_bus.py). 설치된 고정 소스와 실제 시험을 우선 근거로 사용했다.
