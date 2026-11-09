# Scene 수치·좌표·원본 보호 규칙

2026-11-09. Codex-First 제작에서도 기존 Project/Candidate/Scene/Asset/Export 검증이 최종 책임을 가진다. 최신 실행 가이드는 [CODEX_SCENE_GUIDE](CODEX_SCENE_GUIDE.md)다.

## 원본과 수명

원본 RGB/영상·Scene Memo·Capture·measured q·Mapping·실측·기존 Scene/Asset Version/승인 Export는 보존한다. 사용자 사진을 수정해 정합시키지 않는다. 원본과 결과의 SHA/Identity를 비교하며 경로 이름만으로 동일성을 판단하지 않는다.

Scene 이름은 사람용 경로이고 내부 Project ID/Manifest와 별개다. `input/scene_photos`, `input/model_references`, Session/Capture의 읽기 쉬운 이름과 충돌 번호를 유지한다. 이전 불변 Package를 새 경로로 자동 Rewrite/변환하거나 Symlink를 추가하지 않는다.

Asset은 USD/USDA와 독립 Visual/Collision/Material/Version이다. 변경은 새 버전, 동일 내용은 기존 내용 SHA로 재사용한다. GLB/Scan은 새 기본 경로에 도입하지 않는다. 재생성 가능한 Cache라도 현재 Candidate/Export closure가 참조하면 자동 삭제하지 않는다.

## 수치와 출처

- 단위는 m/rad, World는 오른손 +Z다. Transform은 유한한 rigid 4×4, 회전은 proper orthonormal이다. NaN/Inf/Boolean 숫자와 퇴화 K를 거부한다.
- optical X right/Y down/Z forward, Camera pose는 Camera-to-parent다. Blender Camera의 -Z 시선과 변환한다. 원본 해상도·EXIF·crop/pixel affine을 보존한다.
- measured/calibrated는 보호한다. 사진 기반 치수/K/Pose/Mount/광원은 estimated. 수치 API의 optimized도 물리 보정 인증이 아니다. 없는 측정은 null/unknown.
- 부분 실측을 전체 축 measured로 확장하지 않는다. 제작 Asset의 전체 bounds는 estimated일 수 있으며 알려진 축의 constraints와 인용·SHA를 유지한다.
- Scene Memo 의미는 Codex가 해석하고 Python은 Schema·참조·인용·단위·유한성·원본 bounds를 검증한다. 인용과 SHA 일치는 의미 정확도의 독립 증명이 아니다.

## 배치와 센서

한 Scene 배치의 Object Pose는 여러 시점에 공통이다. 다른/모호한 Capture 배치를 같은 정적 Object 배열로 합치지 않는다. Model Reference는 특정 Object의 외형 근거이며 실제 장면 Camera Calibration/정합 View가 아니다.

Side는 하나의 고정 Camera, Wrist는 하나의 실제 URDF Link Mount다. 실제 measured q·관절 이름/순서/Mapping SHA/Robot model SHA/타임스탬프를 보존한다. 프레임별 q offset이나 임의 Wrist extrinsics로 오차를 감추지 않는다. 새 Candidate 비교는 measured q로 렌더하며 과거 runtime Sim q 차이는 진단으로 남긴다.

확정 Support는 지지면의 접선 XY·법선 Yaw와 명시 상대 자세를 사용한다. 높이/법선 정렬은 실제 Collision 극점/Contact Anchor에서 정한다. 경사면, parent-before-child, 치수/새 Asset 후 접촉 재계산을 유지한다. 보호된 Pose/관계를 Solver나 Codex가 삭제·완화할 수 없다. 영상 추정은 PROPOSED, 자료 부족은 NEEDS_MORE_DATA, 충돌은 CONSTRAINT_CONFLICT다.

## 렌더·반복·Evidence

Scene 생성은 Depth/Metric Registration 성공을 필수로 하지 않는다. 실제 RGB/실측으로 초안을 추정하되, 같은 train 입력의 이미지 잔차를 독립 정확도라고 부르지 않는다. holdout은 수정 판단/모델링/최선 선택에 넣지 않는다.

최초 Scene과 각 수정 Before는 저장 후 덮어쓰지 않는다. 실제 렌더/스크립트/자산/Scene 파일만 Evidence에 연결한다. Box annotation은 SAM Mask가 아니다. 후처리나 추정 이미지를 실제 물리 결과처럼 제시하지 않는다. 공개할 판단은 관측 근거·선택한 설계·적용한 변경 요약이며 비공개 사고 과정이 아니다.

모든 비교 가능한 train View가 악화되지 않은 개선만 최선으로 채택한다. 동률/트레이드오프/실패/Stop/예산 종료는 기존 최선을 유지하며 전체 최적해를 보장하지 않는다. 같은 원본의 재개는 검증된 결과를 재사용하고 다른 입력/Memo의 기록은 새 run_identity로 구분한다.

## 물리와 승인

실제 MuJoCo/Isaac의 접촉·중력 결과, 실제 센서 비교, 정밀 Calibration, 물성·Grasp·Task 성공은 각각 별개다. RGB 일치나 낮은 loss로 마찰/질량/접촉 안정성을 인증하지 않는다. 미측정 물성에 엔진 기본값을 사용했다면 측정값이라고 표시하지 않는다.

렌더의 physics step0과 실제 physics stepping을 구분한다. 유한 평면 접촉은 마찰·전도·파지 안정성의 증명이 아니다. 미지원 관측/Task는 NOT_SUPPORTED/NOT_VERIFIED다. Candidate는 기존 validate/preserve/check_scope를 통하며 자동 Promote/Export·로봇 구동을 하지 않는다.

## 기존 고급 API

명시 Calibration/landmark/joint/검증 도구와 Renderer/Exporter의 기존 기하 수학은 유지한다. `inference.py`/`sfm.py`의 과거 결과 소비·진단 유틸은 제품 Auto Reconstruction의 실행 의존성이 아니다. 실제 사용처를 확인하지 않고 SDK/FK/Collision/정밀 보정 기능을 제거하지 않는다.
