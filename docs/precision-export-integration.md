# Teleoperation 설정 정리·Precision 기준각·Builder Export 연결

2026-10-30. 기준 `b6ba771d9bae5b0e5c992075fd351e617666a633`, 새 브랜치 `precision-export-integration`. 기존 Scene/Calibration 원본은 유지하고 세 요청 범위를 구현했다. main 변경·Push·Merge·실제 장치 연결·모터 명령·새 학습은 수행하지 않았다.

## Teleoperation

목표 변화/추종 오차 수동 입력 팝업·장치 설정 필드·Recipe/Worker 전달·해당 값에 종속된 검사를 삭제했다. 숨겨진 rad 기본값도 없다. URDF/승인 motor 교집합, inward Saturation, Precision inverse, SDK 정수 인코딩/양자화 범위, 실제 Feedback, 초기 Leader/Follower/Goal 정합, 현장 승인, 통신 deadline/watchdog, Stop/Cancel/정리는 유지한다. 초기 자세 정합은 SDK 정수 Encoder 좌표로 확인한다.

**현재 장치에는 급격한 명령 변화와 추종 실패를 판정할 검증된 제어 사양이 없다. 실물 Teleoperation은 `ARM_CONTROL_SPEC_UNVERIFIED`로 거부한다.** 입력창을 없앤 결과를 실물 구동 복구로 표시하지 않는다. Memory 경로는 실제 serial 장치를 만들지 않으며 기존 승인·제어·중단 시험을 유지한다. Gripper/자율 Policy에 새로운 권한을 부여하지 않는다.

## Precision 사용 순서

`4 · Precision Calibration` → 저장된 장치 구성/Leader 또는 Follower/Workspace 소유 URDF 선택 → 측정 연결 → 관절 선택 → 사용자가 팔을 지지하고 Torque가 이미 꺼진 상태에서 기준 자세로 직접 맞춤 → 기준각(예: 0°) 입력/현재 Raw 기록 → 필요한 자세 추가 → Fit → 보정 전·후 각도/기록별 오차 확인 → Fit 근거 Review 또는 **별도 검토 자세** 검증 → 새 Profile 저장 → 명시 승인 적용.

- SDK Motor Calibration과 다른 절차다. 기준 자세를 자동 구동하거나 Torque를 변경하지 않는다.
- 기존 `CalibrationDevice`, `fit_joint`, `review_joint`, `validate_joint`, `PrecisionMapper`를 사용한다. Qt는 SDK를 소유하지 않고 R03 `precision_session`이 측정·명령 ACK·heartbeat·종료를 소유한다.
- 새 Profile은 `workspace/calibration/<role>/`에 새 ID/부모 SHA/장치·SDK 보정·URDF identity로 저장한다. 기존 Profile/config 파일을 덮어쓰지 않는다. 기준/계산/Review가 바뀐 뒤 과거 저장본 적용은 draft SHA로 거부한다.
- 적용은 새 `workspace/devices/precision-<role>-.../capture.yaml`을 만든다. Capture 화면에서 원 구성을 선택 중이면 새 구성을 선택한다. Project에 영속 Binding하려면 Capture의 장치 설정 저장을 사용한다. 닫힌 Scene의 기존 Calibration을 자동 재승인하지 않는다. Real/Sim은 계속 선택 Scene의 Calibration identity를 검사한다.
- 관절별 결과는 Backend가 현재 관절/candidate/reference로 반환하며 UI는 선택 관절과 맞는 결과만 표시한다. `physical_verified=false`; 수동 기준 자체의 정확도·실물 Calibration 수집은 별도 현장 검증 대상이다.

구형 Precision의 유한 Live 관측/UI 분기는 삭제했다. 독립적인 `precision_calibration` 오프라인 Profile 검사·재검토 API는 유지하며, 현재 Recipe는 명시 `mode: offline`만 허용한다. 별도 Runtime Joint Offset은 복원하지 않았다.

## Builder Export → Real/Sim

성공한 기존 `export_revision`이 Manifest/Native closure를 검증한 뒤 Builder 소유 `registration.register_export`로 Project의 기존 `execution_packages`에 등록한다. 새 Scene Manager/Exporter/Adapter는 없다. 이관 코드의 소유 파일 복사 책임은 유지하되 등록 Metadata 작성은 같은 함수가 맡는다. 읽기 전용 원본 Project는 등록을 위해 수정하지 않는다.

- Scene 이름·Revision·Project ID·지원 선언 엔진을 Real/Sim 목록에 표시한다. Project Metadata 변경 시 자동 갱신하며 활성 Session 중에는 선택을 바꾸지 않는다. 손상된 Package는 제외하고 빈 목록에서는 이전 실행 Recipe/연결 상태도 지운다.
- Scene을 선택하면 기존 장치 Binding, Model/Precision/Camera, 해당 Revision의 엔진 설정을 복원한다. Export/목록 조회/선택만으로 장치·Simulation을 실행하지 않는다. Model/Mapping/Camera가 부족한 Scene은 등록과 연결 준비 상태를 구분한다.
- 일반 Export에는 재배치된 authoring Scene을 `authored_scene.json`으로 Manifest에 포함한다. 원 provenance와 실행 자산을 보존하며 원 Project 경로를 FK 입력으로 사용하지 않는다. 명시 외부 Export 경로도 등록된 Package identity로 검사한다.
- 일반 Export의 `render_type: authored`는 기존 Builder FK/기하/카메라로 **측정 q 그대로** 정적 렌더한다. 기존 v8 NativeRenderer와 책임을 구분한다. URDF SHA/6축 순서·Mapping·Side/Wrist640×480, 있으면 Scene 관측 Calibration까지 확인한다. 물리/Task Step이나 승인되지 않은 q offset은 없다. 엔진 선언/Parser 통과는 실제 물리 실행 인증이 아니다.

## 검증과 제한

- Builder 전체·Scene Contract 전체 및 직접 영향을 받는 Workbench 주요 회귀 **376 passed**. 최종 리뷰 수정 뒤 해당 화면/Worker/Teleop/Export·제어 주기 집중 **68 passed**, 마지막 SDK 파일 결합 공통화 후 해당 identity/장치/화면 집중 **32 passed**. 중복 실행 수를 더해 전체 시험 수로 보고하지 않는다. 과거 가중치/USD Evidence를 삭제한 상태에서 전체 역사 E2E를 재생성하거나 새 Training을 실행하지 않았다.
- Raw 기준 수집→Fit→별도 자세 Review→불변 저장→승인 적용은 Memory 시험으로 확인했다. 실제 R03 자식 Worker에서도 Memory SDK 측정·기준 기록·영속 ACK·종료를 확인했다. 실제 장치를 대체한 시험임을 구분한다.
- 작은 합성 6축 Builder Export→등록→Real/Sim 준비→실제 MuJoCo RGB를 확인했다. 별도 Isaac 시험도 두 q에서 Side/Wrist640×480 uint8 RGB 변화와 측정 q 적용을 확인했다. 기존 v8 Physics 동등성/실물 정확도 시험은 아니다.
- Isaac의 standalone STOP callback으로 렌더러 종료가 멈추는 문제를 재현하고, 설치된 Isaac Lab의 public context cleanup 순서로 수정했다. 이후 렌더 결과는 완료됐으나 SDK `SimulationApp.close()`의 framework 종료 대기가 남아 시험 소유 프로세스는 timeout으로 정리했다. 제품의 기존 렌더 자식 TERM/KILL 상한은 유지한다. SDK Material cache 쓰기는 보호 audit가 거부했으며 경고 없는 정상 종료로 보고하지 않는다.
- 실제 Qt 화면을 확인했다. 독립 Spec/Standards 리뷰의 관절별 표시 경합·빈 catalog 잔존·폐기 UI 설정을 RED→GREEN으로 고쳤고 최종 High/Medium 잔여0 확인을 받았다.
- 기존 Workspace v8 Package/Project/원 장치 구성·Profile **96개 SHA 변화0**, 이전 정리 시 보존한 Runtime/Scene/config **98개 SHA 변화0**을 확인했다. 원본/설치 SDK 전체 binary corpus 전수 hash를 주장하지 않는다. `.gitignore`·자산/Runtime/Evidence 공개 제외 정책을 유지한다.

주요 새 책임은 `robot/precision.py`, `ui/precision_page.py`, Builder `registration.py`, `robot/authored_render.py`다. 기존 제어 계산/Native/Builder 계약을 복제하지 않았다. 실물 수집·실측 정확도·동적 제어 사양·실물 Teleoperation·장시간/장치 단절은 미검증이다. 새로운 Hub 최초 업로드/자율 Policy 등 다른 미완료 기능은 시작하지 않았다.

로컬 근거: `docs/evidence/precision-export-integration/`의 재현/수정 로그, `targeted-tests.xml`, `final-focused-tests.xml`, `isaac-result.json`, `precision-tab.png`, 보존 대조. 이 폴더는 Git 공개 제외다.
