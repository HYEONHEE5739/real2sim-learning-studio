# Builder와 Workbench 전체 소스 정적 검토

2026-11-18 기준 커밋 `7a47f99`. 두 패키지의 `src` 아래 Python 파일 전체를 읽어 구문 트리·함수·모듈 의존성을 조사하고, 아래 판정은 호출부와 소비부의 구현을 대조했다. Builder 48개 파일 19,119줄, Workbench 123개 파일 20,364줄이다. Workbench 수치에는 포함된 Mimic 참조 구현도 들어간다. 두 패키지 사이에서 사용하는 scene_contract와 프로젝트 명세는 필요한 지점에서 대조했다. 전체 목록·구문 조사와 개별 분기의 상세 검토는 범위가 다르다. 테스트·UI·엔진·학습·실물 실행은 하지 않았으며 아래 영향은 코드에서 도출했다.

## 프로젝트가 연결하는 작업

1. **장면 관측.** Scene Prepare에서 사진·영상·물체 참고 이미지·메모·실측·로봇 Rig를 Project에 연결한다. 실물 Capture는 Follower의 측정 관절값, Side/Wrist 영상과 시각을 남긴다. 단일 관측으로 학습용 행동이나 정확한 카메라 보정을 확정하지 않는다.
2. **장면 제작.** Builder의 automation이 Candidate 하나의 Stage 순서·재개를 소유한다. Stage 1–4는 프레임, DA3 깊이, 대표 시점과 지지면, 좌표계를 만든다. 5–8은 메모·시각 정보로 물체를 분리하고 관측 이미지를 준비해 Codex/Blender로 자산을 만든 다음 자세를 정합한다. 9–12는 관절 지원 여부, Scene 조립, Collision·물성, 안정성을 다룬다. 13–14는 패키지 게시와 엔진 연결이다. Artifact의 완료·메시 파일 존재·물리 정확도는 별도 판정이다.
3. **Native 실행.** 등록된 Revision에서 Real/Sim은 Pose 프로필로 같은 측정 q의 Sim 영상을 만든다. Source·DataGen·Simulation Eval은 Physics 프로필로 물체와 로봇을 움직인다. 두 모드는 같은 Scene을 다른 질문에 사용한다. 첫째는 외형·카메라 정합, 둘째는 접촉과 작업 결과다.
4. **데이터와 정책.** Workbench의 Recipe가 Scene·엔진·Task·입력 파일을 확인하고 Run이 작업 프로세스를 관리한다. Source에서 시연을 기록하고 Annotation에서 구간을 지정한다. DataGen은 해당 시연을 이용해 새 에피소드를 만든다. Curation·Convert를 거쳐 LeRobot Dataset, 학습·재개, Checkpoint로 이어진다. Offline Eval은 기록된 관측에서 정책을 평가하고 Simulation Eval은 물리 엔진에서 실행한다. Real Eval은 실물 관측과 정책 추론, 별도 승인된 그리퍼 단발 시험을 지원한다. 정책의 팔 전체 자율 구동은 현재 지원 범위 밖이다.

## 발견 사항

우선순위는 잘못된 결과가 조용히 재사용되거나 이미 저장한 관측을 복구하기 어려워지는 경우를 먼저 둔다. 각 조건의 현장 발생 빈도는 측정하지 않았다. 아래 경로는 각 패키지의 Python 루트 기준이다.

| 우선 | 조건과 코드 근거 | 사용자 영향 | 권장 수정 |
|---|---|---|---|
| 높음 | Workbench `robot/snapshots.py:303,325–329`, `robot/pairs.py:38–39`, Builder `capture.py:584`. 원본 Capture에 COMPLETE를 쓴 뒤 Pair 작성이 같은 snapshot의 metadata를 갱신한다. 상위 manifest SHA는 별도 파일 쓰기에서 나중에 갱신한다. | 두 쓰기 사이에 프로세스가 죽으면 RGB·q가 남아도 복구 시 metadata SHA 불일치로 거부될 수 있다. | 봉인된 원본은 고정하고 Pair를 별도 파생 manifest로 게시하거나, 새 버전 전체를 만든 뒤 단일 참조를 전환한다. |
| 높음 | Builder `export.py:460–469`에서 패키지 rename 후 Project에 등록한다. `reconstruction_stages.py:1640–1642,1656–1662,1675`의 재개 경로는 기존 패키지 검증 후 등록 정보를 조회한다. | 게시와 등록 사이에 중단되면 파일은 정상이어도 등록이 빠져 Stage 14에 엔진 설정을 전달하지 못한다. | 동일 경로·manifest SHA 등록을 반복해도 같은 결과가 되게 하고, 기존 패키지 재개에서도 등록을 완료한다. 충돌하는 기존 등록은 거부한다. |
| 높음 | Builder `automation.py:70–72,130`에서 Stage 7 캐시 입력에 support_asset이 없다. `reconstruction_stages.py:1027–1030`은 이 설정 유무로 지지면의 모델링 관측이 필수인지를 결정한다. | 별도 지지면을 제공해 Stage 7을 마친 뒤 설정을 제거하고 재개하면 지지면 누락을 재검사하지 않고 기존 결과를 쓸 수 있다. | Stage 7이 실제로 사용하는 지지면 유무를 키에 포함한다. 핸들러와 키 생성기가 같은 입력 정의를 사용하게 한다. |
| 높음 | Workbench `recipe.py:517,521,568` 및 `engines/mujoco/source.py:113`이 전체 경로에서 파일명만 남겨 코드 SHA 사전을 만든다. 엔진과 로봇 양쪽에 control.py, 엔진과 Task 양쪽에 evaluation.py가 있다. | 동명 파일 중 하나의 변경이 다른 실행 간 코드 식별값과 기록에서 사라질 수 있다. 준비한 한 실행에서 파일별 SHA를 확인하는 경로는 따로 있다. | 패키지명과 패키지 상대경로를 키로 쓰는 한 함수를 Recipe·엔진에서 공유한다. |
| 높음 | Workbench `engines/mujoco/source.py:136–140`은 작업 물체와 엔진에 설정된 상시 물체를 함께 허용한다. `engines/mujoco/datagen.py:24`, `engines/mujoco/evaluation.py:108`은 전체 활성 목록과 레시피의 배치 대상 목록이 같아야 한다. | 블록만 옮기면서 별도 동적 물체도 항상 존재하는 구성은 Source에서 허용되고 이후 DataGen이나 평가에서 거부될 수 있다. 정적 책상 하나가 있다는 것만으로 발생하는 문제는 아니다. | 작업·배치 대상 순서와 시뮬레이션에 존재하는 활성 물체 목록을 각각 기록한다. 재생할 모델은 Annotation의 전체 구성과 비교한다. |
| 중간 | Workbench `robot/snapshots.py:216–225`의 재시도는 Capture 루트에서 pair.json을 찾는다. 실제 작성자는 manifest가 가리키는 하위 snapshot에 쓴다(`robot/pairs.py:13,38`). Render Worker는 이미 처리한 같은 Capture ID를 건너뛴다(`robot/render_worker.py`의 seen). | Pair 저장 뒤 등록만 실패하면 재시도가 이미 있는 Pair를 놓치고 재렌더를 요청할 수 있다. 같은 ID가 마지막 처리 ID라면 새 결과 게시 여부가 기존 결과 파일 상태에 의존한다. | manifest의 snapshot 경로와 해시로 Pair를 확인하고 등록만 재시도한다. |
| 중간 | Workbench `robot/capture.py:344–365`는 URDF에서 참조한 OBJ까지 방문하지만 그 OBJ의 MTL·텍스처는 순회하지 않는다. Builder가 만드는 Rig는 실제로 OBJ→MTL→텍스처를 사용한다(`evidence.py:422–424`). Builder Export의 OBJ/MTL 수집은 이를 지원하지만 XML 참조 처리(`export.py:29–36`)는 URDF의 texture filename을 놓친다. | 파일 배치에 따라 한 컴퓨터에서는 보이던 재질이 Capture나 Export를 옮겼을 때 빠질 수 있다. Capture 모델 공유의 os.link 역시 서로 다른 파일시스템에서 실패한다. | 두 패키지가 동일한 모델 의존 파일 목록을 사용하게 한다. 공용 모델은 내용 해시로 참조하고 이동 가능한 Export에서 전체 파일을 묶는다. |
| 중간 | Workbench `learning/train.py:67–77`은 Resume 입력 디렉터리를 먼저 만들고 비 JSON 파일에 os.link를 호출한다. | 외장 디스크의 Checkpoint와 새 출력이 다른 파일시스템이면 EXDEV가 발생한다. 부분 디렉터리가 남으면 같은 경로 재시도도 실패할 수 있다. | 임시 경로에서 구성하고 교차 파일시스템이면 SHA 확인 후 복사한다. 전체 검증 후 게시한다. |
| 중간 | Workbench `recipe.py:89`에서 Real Eval의 episodes가 필수이고 timeout_s를 받을 수 있다. `robot/live.py:65,84,109–119`의 observe_only 루프는 max_frames로 종료하며 기본값은 1이다. 관측 전용에서도 매 프레임 RGB를 리스트에 쌓는다. | 사용자가 여러 에피소드를 지정해도 한 프레임으로 끝날 수 있고 긴 관측에서는 메모리 사용량이 증가한다. | 관측 모드 UI에는 실제로 적용할 프레임 수·시간만 노출하고 저장하지 않을 RGB는 해당 프레임 처리 후 해제한다. |
| 중간 | Builder `candidate.py:22–33`은 실행 중임을 표시하는 파일을 배타 생성하고 finally에서 지운다. `ui_reconstruction.py:297`은 파일 존재만으로 실행을 차단한다. | 강제 종료 뒤 파일이 남으면 실제 작업이 끝났어도 UI 재개가 막힐 수 있다. | OS가 프로세스 종료 시 해제하는 파일 잠금을 쓰고 PID·작업 ID는 진단용으로 기록한다. 정상 실행 중인 작업을 해제하지 않도록 한다. |

## 구조 판단과 우선순위

Builder의 장면 제작, scene_contract의 패키지, Workbench의 실행·데이터라는 분리는 유지할 가치가 있다. 실제 취약점은 경계를 넘는 같은 사실을 두 곳에서 다르게 해석할 때 생긴다. 예를 들면 “패키지 파일이 생겼다”와 “UI에서 실행 가능한 Revision이 등록됐다”, “Task 대상이다”와 “물리 세계에 존재한다”가 서로 다르다.

1. 먼저 Capture 봉인·복구와 Export 등록부터 고친다. 정상 촬영·게시의 결과를 중단 뒤에도 그대로 사용할 수 있게 하는 변경이다.
2. 다음으로 Stage 입력 키, 코드 식별 경로, 물체 목록을 Producer와 Consumer가 공유한다. 기존 StageArtifact·Recipe·scene_contract에 담으면 된다.
3. 그 뒤 이식성과 운영을 보완한다. Rig 의존 파일, Resume 입력, 오래된 잠금, Real Eval의 UI 옵션이 대상이다. UI 패키지와 Builder를 한꺼번에 분해하는 일은 우선순위가 낮다.
4. 프로젝트별 실험 준비는 별도다. 최종 Rig의 물성·Mapping, Robot World 및 센서 정합, 새 Native Export와 Isaac의 마지막 RGB/종료 문제는 [기존 준비 상태 검토](scene-to-real-eval-readiness.md)를 따른다. 이번 정적 검토로 그 실행 결과를 갱신하지 않았다.
