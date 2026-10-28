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

## Phase4 — 실물 경로의 오프라인 경계

기존 Leader/Follower/CalibrationDevice/CameraReader의 수명·mapping·encoder·cleanup 계산을 재사용했다. 실제 ACT checkpoint/processor 출력→Saturation된 승인 model/motor 교집합→Precision inverse→SDK 정수 encoding→Fake Follower send/close를 시험했다. SDK 생성자의 공식 Config dataclass만 별도 검사하며 실물 SDK Device/포트를 생성하거나 연결하지 않는다.

`robot/offline.py`는 기존 R03의 capture/precision_calibration/real_sim/real_evaluation Stage에서 **명시 offline** 보존 입력 검사만 수행한다. Builder가 소유한 Capture Reader·기존 profile fitter/검증과 Policy API를 호출하고 작은 inspection report만 저장한다. 새로운 Capture 저장 포맷/실행 프레임워크가 아니다. Qt에는 오프라인임을 명시한 네 화면을 연결했다. 실물 Calibration 수집·토크·실측 정확도·실제 Policy Rollout은 UNSUPPORTED/미검증이며 검사 worker 완료와 구분한다.

원래 보존 snapshot/Precision 근거를 새 worker에서 읽었다. Capture는 내부 clock/image/model SHA가 유효하더라도 현재 Scene과 mapping/model/단위가 결합되지 않으면 PARTIAL이다. 이 상태에서 Policy inference/command 변환을 수행하지 않는다. 한계가 다른 역사 모델의 SHA를 같다고 재명명하지 않는다. 실물 command record가 없는 현재 v8을 자동 승인하지 않는다.

Phase4 실제 Qt→기존 R03 worker의 보존 Precision 검사, 실제 저장 Snapshot/Capture 및 Real/Sim 입력 검사를 완료했다. Real Policy 보고서는 과거 Capture 결합 부재 때문에 PARTIAL·inference_performed=false·command_sent=false다. 공식 SDK/Fake 장치·Policy 집중110 PASS. 독립 Spec/Standards 두 축의 identity/단위/실행 코드 누락 지적을 수정하고 High/Medium0 closure를 받았다. Camera/Scene Calibration identity도 명시 결합이 없으면 승격하지 않는다. 전체 회귀의 진행 중 스냅샷과 최종 집중 검사를 구분하고 Phase6에서 다시 고정 코드 전체를 검증한다.

## Phase5 — UI 출력 기본 위치

UI 새 Run의 출력 제안만 source/annotation/datagen/dataset/policy/evaluation/scenes로 정리했다. `ui/paths.py`는 경로를 반환하며 Dataset을 만들거나 옮기지 않는다. 저장 Recipe를 열 때 명시 output을 덮어쓰지 않고, 명시 append 중에는 새 출력 제안을 거부한다. 과거 fresh-worker Run의 계속 실행 버튼도 기존 output+resume=true+추가 Episode 계약을 편집하도록 수정했다. 역사 identity가 다르면 prepare가 명시 거부하며 자동 복사/수정하지 않는다.

Curation/공식 Export/Merge·Training Config 저장 대화상자와 다음 단계 입력 선택은 해당 폴더를 먼저 제안한다. 빈 Workspace Builder를 열 수 있지만 Scene은 사용자 New 동작 전에는 생성하지 않는다. 실제 Qt에서 저장 경로 보존/새 제안/append/계속 실행/Scene 미생성을 확인했다. 기존 run.json/segments/attempts/HDF5/MP4/공식 checkpoint 형식은 변경하지 않았다. 동일 영상·Native segment·Checkpoint를 새 등록 포맷으로 복제하지 않는다.

Phase5 전체987 PASS/skip0 및 최종 UI 집중21 PASS, 두 축 독립 리뷰 High/Medium0. 신규 단계 경로에서 양 엔진1/4의 실제 통합 실행을 진행하며 전체 결과는 Phase6에 집계한다.
