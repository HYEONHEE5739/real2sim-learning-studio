# Scene 준비·v8 소유권 이관·장치 설정

작업 기준 `8b565968542fcfbe8df37a71dd70ff1e2274c336`, 개발 브랜치 `scene-preparation-v8`. 첨부 명세 d272b454와 사용자의 A 제거→B 단일 구현 원칙을 따른다. 원본·기존 브랜치는 보존하고 Push/Merge·무인 모터 쓰기는 하지 않는다.

## 대체 범위와 실행 순서

1. Scene 자료 준비: 기존 Project/Evidence에 선택적 입력과 자유 메모 저장. 빈/메모/파일만 있는 Project도 생성 가능. 부족한 Model/Calibration은 해당 Reconstruction/Render/Control 단계에서 보고.
2. 실제 v8 이관: Project.create 후 유효한 Scene/Evidence/Assets/Candidate/측정/보정 closure를 새 소유 경로로 재구성. 통째 clone으로 끝내지 않음. 기존 닫힌 v8 Package bytes/Manifest/Revision은 보존한 채 Workspace 내부에 등록.
3. 장치 설정: 기존 수동 파일 선택 중심 기본 화면을 제거하고 Robot/Leader/Follower/Camera 선택과 자동 복원으로 교체. 기존 고급 JSON/YAML·Precision 탭은 역할을 유지하되 폐기 UI의 두 번째 경로로 남기지 않음. SDK 보정은 공식 수동 안내·현장 승인 절차로만 수행.
4. UI: Capture 오른쪽은 Input Data·밝은 자유 메모·저장. 장치 구성은 별도 설정 패널. Real/Sim은 Scene 선택으로 Project/Model/Camera/장치 Binding을 복원. 이전 기본 UI 분기·폐기 시험을 정리.
5. 격리 검증: 원본 삭제 없이 이전 application/data 경로 접근을 막고 새 Project/Package/장치설정/양 엔진/Qt를 재로드. SDK runtime과 원본 application source 의존성을 구분. 전체 회귀/wheel/독립 리뷰·보존.

## 조사로 확인한 중요 사항

- 기존 Builder Project는 Input 약48.6MB, scratch 약507MB, exports 약175MB다. 모든 scratch bulk를 복사하지 않고 검증 가능한 Candidate/보고서·필수 실제 Input closure를 보존한다.
- 기존 authoring Scene에는 명시 `simulation_joint_offsets_rad`가 있고 실행 Package에는 residual이 URDF Geometry에 이미 baked돼 있다. 새 실행에서 이 둘을 중복 적용하지 않는다. 기존 baked v8 bytes/의미는 보존하며, authoring의 추가 residual 자동 적용을 없애는 영향·동등성을 실제 FK로 검증한다. 불명확한 보정을 추정해 버리지 않는다.
- Qt venv도 이전 SO101 폴더 안에 있으므로 원본 폴더 제거 뒤 실행하려면 해당 기존 runtime 의존성도 별도로 소유해야 한다. SDK 설치/업그레이드 없이 필요한 기존 Qt runtime을 보존하고 새 실행 스크립트에서 선택한다.

아래 결과는 구현·실행 후 실제 근거로 갱신한다. 현재 이 문서는 작업 경계이며 완료 보고가 아니다.
