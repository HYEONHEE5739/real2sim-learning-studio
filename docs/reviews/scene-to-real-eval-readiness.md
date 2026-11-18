# Scene Prepare부터 Real Eval까지: 실행 준비 검토

2026-11-18. 브랜치 `feat/simfoundry-style-reconstruction`, 검토 기준 HEAD `8d5e219233e367fccfa6b7e2765aecbdbe50e32b`와 당시 미커밋 코드·신규 문서/시험을 함께 검토했다. 이 문서의 로컬 상태는 조회 시점의 기록이며, 다른 컴퓨터에 같은 데이터가 설치되어 있다는 뜻은 아니다.

**Scene Prepare에서 입력 준비와 Scene 초안 제작을 시작할 수 있다. 현재 저장 상태로 전체 파이프라인을 Real Eval까지 연속 실행할 준비가 끝난 것은 아니다.** Native 실행에 필요한 입력이 없으면 차단하며, 실물 정책 실행은 현재 관측·추론 및 승인된 그리퍼 단발 시험만 지원한다.

## 실제 조회한 현재 상태

- `pickplace_new`: `so101_with_camera` Rig를 선택했다. 기존 `auto_001`의 저장된 상태는 Stage3의 `No canonical frame satisfies support/object/visibility requirements`다. 이 상태는 과거 실행 결과이며 최신 코드로 같은 사진이 통과한다는 증거가 아니다. 게시된 실행 Package가 없다.
- `pickplace_colorblock`: 과거 등록 Revision 7개에 새 `engine_profiles`가 없다. Native 전용 UI는 이들을 실행 가능한 Pose/Physics 선택으로 제공하지 않는다. 과거 Package를 자동 변환하지 않는다.
- Workspace Runtime은 Codex VLM·DA3·SAM3.1·로컬 편집·PriorDepth·RemBG·CPU CPD·Blender 등의 지정 경로가 존재한다. 경로 존재만 확인했으며 이번에 모델을 초기화하거나 로그인·서비스 가용성을 조회하지 않았다. FoundationPose는 선택 Runtime이며 미설정이다.
- `auto_version` 전용 데이터는 앞선 명시 요청에 따라 삭제됐다. 공유 Object Library·Rig·다른 Scene은 보존했고 이번 Commit에도 사용자 데이터는 포함하지 않는다.

## 단계별 진행 조건과 실패 가능 지점

| 구간 | 현재 코드가 연결하는 경계 | 현재 확인한 제약 / 시작 전 확인 |
|---|---|---|
| Scene Prepare | Project·입력 이미지/영상·Memo·Model Reference·Robot Rig·장치 구성 | 이미지의 정적 배치를 구분한다. Model Reference를 Scene 관측으로 사용하지 않는다. Rig 선택은 시각/FK 모델 선택이며 새 Calibration 승인이 아니다. |
| Stage1–4 | 프레임 준비 → DA3 → VLM 의미 계획/SAM/대표 시점/평면 → Support 좌표 | 실제 입력의 가림·Mask·평면·대표 시점이 부족하면 중단할 수 있다. 새 코드가 과거 Stage3 실패를 반드시 해결한다고 보장하지 않는다. 8GB GPU에서는 모델 Child를 순차 실행하고 기존 DA3 Mixed 정책을 유지한다. |
| Stage5–8 | Memo 제약·분해·이미지 처리 → Codex/Blender 독립 Asset → CPU CPD/Front | Object Identity·실측 인용·생성물 품질·모델 Runtime·Codex 응답/Quota·대칭/퇴화 CPD가 검토·실패 사유다. 개별 과거 모델 성공과 이 Scene의 전체 제작 성공은 구분한다. |
| Stage9–10 | 기존 Robot 관절 보존·Scene 합성·Robot World/센서 등록 | 새 Object articulation은 미지원. 현재 `pickplace_new/auto_001` 설정에는 metric/world anchors, World 등록, metric review, Native mapping이 없다. Stage10의 명시 정합 Gate를 통과할 준비가 필요하다. |
| Stage11–14 | Collision/물성 → 실제 물리 진단 → Native Export/등록 → Simulator | 현재 최종 카메라 Rig의 `wrist_camera_mount_link`와 기하 없는 `camera_optical_frame`에는 inertial이 없다. 현재 MuJoCo 로더는 이를 요구하므로 차단된다. 부착물 물성의 근거와 기하 없는 고정 Frame에 대한 로더 처리 범위를 별도로 해결해야 한다. Optical Frame에 물리 질량을 임의로 만들라는 뜻이 아니다. |
| Real/Sim | Native **Pose** 프로필·같은 measured q의 Side/Wrist 비교 | 유효한 새 Native Pose Export가 선행된다. 현재 Device Precision과 최종 Rig의 URDF SHA가 다르다. 기존 관절 축/한계의 일치 검토와 명시 Mapping 연결이 필요하며 외형 변경만 보고 보정을 재승인하지 않는다. |
| Source → Annotation → DataGen | Native **Physics**, Task 함수·단계 구간, 실제 Episode 기록 | 물체 mass/friction/Collision·Task Object ID·관절·카메라·Scene identity가 맞아야 한다. Source/Annotation에 실패했거나 유효한 구간이 없으면 생성 자료가 생기지 않을 수 있다. Scene 제작 성공만으로 grasp/place 물리가 검증되지 않는다. |
| Curation → Convert → Train | Native 선택/계보 → 공식 LeRobot Dataset → 공식 Trainer/Checkpoint | 명시적인 Dataset 변환·feature/state/action 순서·RGB Grid·Task·학습 설정·Processor가 필요하다. 저장된 Dataset/모델/보정 계약이 달라지면 Resume나 평가가 차단된다. |
| Offline / Simulation Eval | 독립 Episode 계보 검사·정책 계약·Native Physics 실행 | 학습 자료와 검증 자료 중복·불명확한 계보는 독립 성능으로 승인하지 않는다. Sim 평가 완료는 Task 성공과 별개다. 실제 정책 품질은 이번에 시험하지 않았다. |
| Real Eval | `robot/live.py`의 관측·정책 추론, 별도 승인된 `gripper_once` | **정책이 팔 6관절을 움직이며 반복 Pick & Place 하는 경로는 지원하지 않는다.** `enable_motion`/미지원 모드는 연결 전 거부한다. 그리퍼 시험은 명시 승인 후 정책 출력의 gripper 성분만 1회 사용한다. Teleop의 Leader→Follower 구동과 다른 기능이다. |

핵심 소스: [Native 준비 검사](../../real2sim_builder/src/real2sim_builder/registration.py), [Rig 가져오기](../../real2sim_builder/src/real2sim_builder/evidence.py), [Stage10](../../real2sim_builder/src/real2sim_builder/reconstruction_stages.py), [MuJoCo URDF 처리](../../robot_learning_workbench/src/robot_learning_workbench/engines/mujoco/model.py), [Recipe 준비](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py), [정책 계약](../../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py), [Real Eval 범위](../../robot_learning_workbench/src/robot_learning_workbench/robot/live.py).

Isaac은 별도 미해결이다. 직전 Native 실제 시험은 RGB 생성 전 그래프 오류와 종료 세그멘테이션 오류(exit139)가 있었다. Schema 검사 통과를 실제 Isaac 운용 성공으로 확장하지 않는다. 이번에는 재실행하지 않았다. [Native 전환 검증 기록](native-only-simulation.md)을 따른다.

## 권장 진행 순서

1. Scene Prepare에서 기존 `pickplace_new`를 선택하거나 새 Project를 만든다. Scene 이미지·배치별 구분·Model Reference·원문 Memo·실측을 저장한다. 실제 장치 연결은 사용자의 명시 조작으로만 시작한다.
2. `SO-ARM101 + Wrist Camera` 선택을 확인하되, Capture에 사용할 URDF/Mapping과 제작에 사용할 Rig의 결합을 먼저 검토한다. 기존 Capture/q/Calibration을 새 모델에 맞춰 덮어쓰지 않는다.
3. Auto Reconstruction의 단계별 입력·Mask·Object ID·실측 제약·제작 결과를 확인한다. 일부 Object 초안이 생성됐다는 이유로 Robot World나 Scene 완료를 승인하지 않는다.
4. 독립 metric anchor·Robot World·Side 고정/Wrist 공유 Mount·measured q/FK·Mapping·Rig 물성을 준비한다. 차단 사유가 남으면 그 사유를 해결한 뒤 새 Native Export를 만든다.
5. Native Pose로 실제 Side/Wrist 정합을 확인하고, Native Physics에서는 중력·Collision·관절·Task를 별도로 확인한다. 그 뒤 Source→Annotation→DataGen→Curation→Convert→Train/Resume→Sim/Offline Eval을 단계별로 진행한다.
6. 현재 Real Eval에서는 관측·추론 검증까지 진행할 수 있다. 팔 전체의 정책 실행은 별도의 구현·실물 안전 검증 작업이 필요하다. 이를 우회해 `enable_motion=true`로 바꾸지 않는다.

## Standards / Spec 검토

### Standards

커밋 직전 검토에서 세 가지를 확인했다. 실제 사용자 Calibration을 복사한 신규 JSON 2개는 제외한다. 테스트는 이미 추적 중인 고정 프로필에서 임시 SDK 입력을 재구성하는 기존 helper를 재사용하며 사용자 보정 파일을 읽지 않는다. 로컬 Qt 설치를 무조건 요구하던 시험은 임시 checkout의 기본 Runtime 선택을 검사하도록 바꿨다.

또한 Cube edge와 별도 height가 모순돼도 `VALIDATED/measured` 직육면체로 통과하던 결함을 재현했다. 17mm Cube edge와 18mm height의 같은 행·다른 행·역순 3가지가 수정 전 모두 실패(거부하지 못함)했다. 두 값을 SI Decimal로 대조해 모순이면 거부하도록 최소 수정했다. 17mm와 1.7cm의 정상 동일 치수는 유지한다. Memo를 자연어 규칙으로 다시 파싱하거나 원본 치수를 바꾸지 않는다.

### Spec

Native 전용 실행·원본 보호·자동 엔진 대체 금지와 단계별 계약은 유지한다. 현재 확인한 6개 준비/지원 제약은 실행 프로필 부재, 최종 Rig 관성, 새 모델 Mapping, World/센서 anchors, 팔 전체 Real Eval 미지원, Isaac 실제 실행 실패다. 이를 코드 연결 완료나 Mock 통과로 해결됐다고 보고하지 않는다. 이번 검토가 모든 외부 Runtime·사진·Task 조합의 무오류를 보장하는 것은 아니다.

## 로컬 자원 재연결과 Commit 범위

Commit은 제품 코드·시험·문서·경로가 일반화된 예시 YAML만 포함한다. `workbench_runs` 전체, Scene/Input/Capture/Dataset/Checkpoint/Calibration/Asset/Export, 모델·Cache·Conda·인증·개인 경로 설정은 제외한다. 기존 학술/개발 이력의 문서와 이미 추적 중인 고정 테스트 Evidence를 새 사용자 데이터로 덮어쓰지 않는다.

다른 컴퓨터에서는 다음 자원을 별도로 준비한다. 소스 Commit만으로 로컬 Rig·이미지·가중치가 복원되지 않는다.

- `run_workbench_ui.sh`: 기존 설치를 `QT_PYTHON`, `BACKEND_PYTHON`, 선택 `ISAACLAB_ROOT`, `WORKBENCH_WORKSPACE`로 지정한다. 저장소 밖 다른 프로젝트의 Robot 모델을 자동 검색하지 않는다.
- Workspace `runtime/reconstruction.yaml`: [Runtime 예시](../../real2sim_builder/config/simfoundry-reconstruction.example.yaml)의 `runtimes`를 기존 설치의 실제 경로에 연결한다. Workspace 기본값보다 Project/명시 설정이 우선하므로 오래된 override도 확인한다. `vlm.provider: codex`, Native 엔진 선택을 사용하며 폐기된 `simulator.mode`나 Gemini VLM 설정을 가져오지 않는다.
- `robot_rigs/so101_with_camera/rig.yaml` 및 URDF/Mesh·Object Library·Device 구성은 별도 로컬 자원이다. 폴더명만 복원하지 말고 Manifest/SHA·실제 모델/Mapping·Mount를 확인한다. Capture/Export 원본을 재작성하지 않는다.
- Codex 로그인·모델/강도는 기존 UI 계정을 사용한다. 토큰·키·계정 파일을 Git이나 Runtime YAML에 넣지 않는다. 새 다운로드·설치·규약 동의는 이 문서로 수행되지 않는다.

이번 검증의 실제 명령·집중 시험 XML·민감정보/파일 크기 검사·제외 목록·원격 SHA 대조는 Git 제외 `workbench_runs/diagnostics/native_pipeline_checkpoint_20261118_001/`에 보존한다. 전체 pytest, AI Forward/학습, 사용자 Scene Reconstruction, 실물 연결/구동은 실행하지 않는다. 새 MuJoCo 합성 시험과 Mock/Schema 시험은 실제 Scene·정책·실물 정확도와 구분한다.

## 체크포인트 집중 시험 결과

- Memo 제약·보정 시험 입력·UI 실행 경로 등 집중 시험 59개 통과. 파이프라인 관련 17개 시험 파일에서 208개 중 206개 통과, 2개 실패.
- 실패는 `test_pinned_real_stage12_reuse_keeps_artifact_provenance_and_bytes[1/2]`다. 기준 Commit 이후 자료 저장 경로가 `project.write_evidence`로 바뀌어 보호된 입력 함수 4개의 AST가 달라졌고, Builder 모듈 일부의 SHA도 기존 승인 목록과 다르다. 현재 코드는 호환성을 증명할 수 없어 과거 Artifact의 재사용을 거부한다. 사용자에게는 이어서 실행할 때 RGB 준비·DA3 추론을 새 attempt에서 다시 수행할 수 있다는 의미다. 같은 서명의 정상 Cache는 기존 경로에서 재사용한다. 새 Scene 최초 실행에는 이 구버전 Cache 조건이 없다. 다음 호환성 승인에는 변경된 입력 처리와 Worker 의존성 검증이 필요하다.
- 보호 대상으로 기록한 16,521개 파일에서 SHA·크기 또는 파일 링크 대상 변경, 누락, 신규 파일이 없었다. 디렉터리 링크는 파일 대조 범위 밖이다.
