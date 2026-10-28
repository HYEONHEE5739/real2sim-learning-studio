# Architecture completion — 작업 기록

2026-10-28. **진행 중**. 현재 브랜치는 `architecture-completion`, 기준은 Initial 공개 Commit `8a8210d13e31ea2c777e120f4e8fb0640050fec0`다. 이번 요청의6개 Phase를 순서대로 구현·검증한다. 자동 GitHub Push·실물 장치·새 v9/실측 Calibration은 수행하지 않는다.

## 비교 기준

GitHub와 로컬 원본의 main HEAD를 읽기 전용으로 대조했다.

- 기존 Builder `ad018a018711d03fb51c28242dfc2bd19b6d0b07`: `app/core/project.py` Git blob `e2e8d00f161b93ac3810bdb256a63e88b33cbde2` 일치. 원본 app36개 Python 파일의 함수/class 목록·SHA를 조사했다.
- 기존 SO101 `875e64fe6673e664f6fa8203d15ab103d488a6ad`: `workflow/adapters.py` blob `ba1ccea47d07dbc26ee1acf1578d2dfce2736bf3` 일치. 원본151개 Python 파일을 조사했다.
- 현재 설치 LeRobot0.4.1의 factory/config registry에는 ACT/Diffusion/SmolVLA/PI0/PI05/TDMPC/VQBeT/GROOT/SAC/reward_classifier가 등록돼 있다. 등록·config 생성·선택 의존성·학습/실제 Scene 배포 가능성은 각각 별개로 검사한다.
- 기존 Native C·Saturation·v8 Collision·Task phase·E01 물체 잔차는 기준을 유지한다. 과거966 PASS와 새 실행은 구분한다.

세 저장소의 기존 기능이 모두 동일하다고 가정하지 않는다. 원본의 범용 SimulationAdapter를 새 실행기에 다시 넣지 않으며, 기존 SO101의 SciPy/Strict·과거 명령 clip 정책은 승인된 DLS/Best Effort·Saturation 정책과 구분한다.

## Phase1 — 엔진 보조 함수

기록·IPC·Native 게시·Task/Policy binding의 엔진 무관 함수25개를 이동했다. 구체 MjData/ManagerBasedEnv loop·Step/Reset/Camera/Contact와 Env별 상태 수명은 유지한다. 실제 함수 목록은 로컬 `docs/evidence/architecture-completion/helper-moves.json`에 있다.

최초 경계 RED2개와 리뷰 경계 RED2개를 거쳐 집중74 PASS, 전체970 PASS를 확인했다. 실제 양 엔진1/4-env Source→Annotation→DataGen→Evaluation을 신규 출력에 각각8run/20 Episode로 검증했다. SDK cache write 보호 audit와 기존 Render/종료 warning은 허용/삭제하지 않는다.

독립 검토의 video→run 상위 의존은 정리 함수를 실행 소유자 run으로 옮겨 해소했다. 영상·장치 드라이버 파일은 기준 Commit과 byte-exact이며, Leader 구성만 robot/configuration.py에 있다. 기존 producer 예외였던 보조 함수의 분류만 유지해 기존 append를 보존하고 control/state/device/Mimic/Task 검사는 엄격하게 유지한다. 실제 원본 불변 복제본에서 양 엔진 Source8→9, MuJoCo DataGen6→7과 이동된 cleanup의 실제 평가를 확인했다. 오래된 초기 R01 자료는 기준 Commit 이전 video identity로도 이미 비호환임을 확인했으며 이를 임의로 완화하지 않았다. 두 축 리뷰의 High/Medium 잔여0이다. 후속 Phase의 완료를 이 결과로 주장하지 않는다.

## 남은 순서

1. Phase1 리뷰 지적·동일 경로 Resume·Prepared source coverage 마무리.
2. Builder Scene/Evidence/Capture/Candidate/Scan의 실제 책임 분리와 CLI/UI/Export 회귀.
3. 공식 Policy Factory/Trainer·fine-tune/Resume·Hub 경계와 실제 지원 상태/UI.
4. 장치·Calibration/Capture·real-policy의 오프라인/Fake/공식 SDK 계약; 실제 장치 상태는 미검증 유지.
5. UI의 신규 출력 기본값만 Stage별 workspace에 정리; 기존 경로 이동/포맷 변경 없음.
6. 양 엔진 실행·공식 소비자·학습/평가·UI 결과·전체 회귀/wheel·독립 리뷰·보존 종합.

최종 상태는 VERIFIED(actual), CODE_READY(연결됐으나 실제 실행 미검증), PARTIAL, UNSUPPORTED, EXCLUDED로 구분한다. 현재 문서는 완료 보고서가 아니다.

## Phase2 — Builder 역할별 모듈

`project.py`의 기존 공개 이름은 direct alias로 유지하고 내부 caller는 실제 소유 모듈을 사용한다. 새 scene/files/evidence/capture/editing/cameras/candidate/scan/initialization은 현재 알고리즘을 그대로 가진 목적별 파일이며 새로운 계층/Manager/저장 포맷이 아니다. Project lifecycle은 project.py, bounded review loop는 reconstruction.py가 소유한다.

기준 project.py 약1,900줄→약200줄, reconstruction.py1,036→약400줄이다. 이동64개 함수/class는 import를 제외한 AST exact. 파일 이동 과정의 schema constant 누락은 기존 상대 Geometry 회귀가 재현했고 원 상수를 올바른 소유 모듈로 옮겨 고쳤다. Capture/Project 집중54 PASS, Builder 전체103 PASS, 전체973 PASS, 마지막 import 정리 후 Builder103 PASS다. 실제 보존 v8 Manifest84개/SHA 및 native USD/MJCF/URDF closure를 읽기 전용 검증했다. 원본 프로젝트/Scene/Export를 재작성하지 않았다. 두 축 독립 리뷰의 High/Medium 잔여0.

## Phase3 — 공식 LeRobot 경계

ACT/SmolVLA 이름 whitelist를 설치된 공식 Registry/Config/Policy Factory로 교체했다. 10개 등록 설정과 실제 model class import를 조사하며, 등록 자체를 학습/Scene 지원 완료로 표시하지 않는다. 공식 Trainer로 신규 Diffusion 1step→2step Resume 및 별도 local fine-tune1step을 실행했다. 양 엔진1/4-env에서 공식 Diffusion history2/queue4로 각각6step Evaluation을 완료했다. 성공률이 아닌 실제 실행 경로 증거다. 기존 ACT/SmolVLA와 Diffusion의 독립 Validation도 각각8batch를 실행했다.

Hub는 명시 Resolve→Commit 고정→공식 cache snapshot 경로를 반환한다. `lerobot/pusht` Commit `7628202a2180972f291ba1bc6723834921e72c19`를 실제 다운로드하고 공식 Reader/DataLoader/Curation으로206 Episode/25,650frame을 열었다. 2축 PushT action을 SO101 rad로 재명명하지 않았다. 불완전한 외부 v3 Metadata와 구형 v2 Dataset, processor가 없는 구형 ACT Hub Policy는 명시 거부하며 원본을 자동 마이그레이션하지 않는다. Policy 다운로드 자체는 `lerobot/act_aloha_sim_transfer_cube_human` 고정 Commit에서 확인했다.

업로드는 명시 버튼/저장 요청, Repo 종류/공개 범위, 현재 Remote parent Commit 일치가 필요하며 기존 Repo만 대상으로 한다. 실제 업로드는 요구대로 미수행; 공식 API의 통제 fixture로 경계와 결과 Commit 기록을 검증한다. Token을 Recipe나 결과에 저장하지 않는다. Cache blob을 제외한 외부 escaping symlink는 거부한다. 장시간 전송은 기존 R03 child/취소 수명을 사용한다. 새 Policy/Trainer/Dataset 프레임워크는 없다.

독립 Spec 리뷰의 Scratch/가중치 의미 혼동·외부 심볼릭 링크 유출·Registry 응답 race와 Standards 리뷰의 승인 표시/Recipe 불일치·Fine-tune 상대 경로를 수정했다. Spec 보고서는 수정 확인을 기록했지만 최종 agent turn은 서비스 usage limit으로 종료됐다. Standards의 두 건은 주 에이전트의 실제 Qt/실행 및 소스 확인으로 closure했으며 독립 재검토 완료라고 보고하지 않는다. 외부 공식 Dataset의 독립 Validation은 IO 오차만 측정할 수 있으며 lineage가 없으면 train/val 격리를 입증했다고 표시하지 않는다. SO101 배포 검사는 여전히 별도 strict 계약을 요구한다.

Phase3 최종 전체 회귀981 PASS/skip0, 기존 torchvision warning2개. 실제 UI의10개 페이지·Registry/config·승인 초기화, ACT/Smol/Diffusion Validation 및 Diffusion 양 엔진1/4 실행을 구분해 검증했다.
