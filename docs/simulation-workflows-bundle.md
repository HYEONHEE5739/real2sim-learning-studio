# E06-b · Isaac E03/E04 · E06-c — 실제 Workflow 연결

2026-10-27. **양 엔진 Fixed 배치 DataGen의 실제 성공·Native 저장·새 출력 Resume를 확인했다. 전체 E 계열 AC 완료는 아니다.** Isaac Random Reset·복수 Episode Annotation은 명시 차단하며, E01 cube–cup 충돌 이후 최대 성분 **1.197188790mm** 잔차는 OPEN이다. L/P/C/U/X는 시작하지 않았다. 원본·고정 SDK·기존 Scene Revision·Native C 저장 구조를 변경하지 않았다.

## 상태와 범위

| 작업 | 확인한 기능 | 남은 관문 |
|---|---|---|
| 선행 MuJoCo E03/E04·E06-a | 이전 778개 시험 및 제품/증거 identity 확인. 기존 실제 Source→Auto/Manual→공식 Pool, DLS 공통 계산 재사용 | 선택적 signal/metric·실물 입력은 이전 제한 유지 |
| E06-b MuJoCo | 실제 Mimic→DLS→물리 Step→Grasp AND Placement→Native publish, 실제 R03 worker, 누적 성공 2개 Resume | 이 Scene의 v8 uniform 후보가 기존 회전 Support 검사를 위반해 run 중단. Random 성공 수집·다른 Scene/장시간·다중 env는 미검증 |
| Isaac E03 | B01 명령 fixture로 실제 388 frame 수집, recording_only·pre-step 수치/640×480 영상·post-step telemetry·Native 재로드. fake Leader production run의 실제 물리/영상 저장·정리, 새 앱 Resume(누적2)·취소(완료0) 확인 | 실물은 금지/미검증. R03 기본 stage dispatch/실제 AppLauncher→Annotation→terminal은 audit/log bootstrap child로 실증; 부가 배포 환경은 미검증 |
| Isaac E04 | 새 앱의 production Annotation 단일 Episode 388 frame, 실제 replay/최종 물리 통과·공식 Pool. 자동 post221→pre222 및 수동 mark203 | 같은 앱 cross-stage/재생성 및 복수 Episode 복원 동등성 OPEN. 복수 Episode 입력은 시작 차단. 전체 pixel/센서 시간 동등성은 미검증 |
| E06-c Isaac | 위 단일 Episode 관문 통과 후 착수. 실제 R03 Fixed DataGen·Native 저장/재로드·새 worker Resume로 누적 성공 2개 | Random Reset은 legacy persistent RNG/continuation 검증 전 거부. E01 물체 잔차 원인·전체 Scene/정책 성공률은 OPEN |

따라서 기본 경로의 구현·실행 증거와 전체 task 체크를 구분한다. E03/E04/E06의 전체 완료 체크는 보류한다. 이번 결과는 실물 안전성 또는 학습 Policy 성능 증거가 아니다.

## 제품 변경과 재사용

- 새 구체 실행 파일: `engines/mujoco/datagen.py`, `engines/isaac/source.py`, `annotation.py`, `datagen.py`. 공식 SDK·기존 Scene/Task/Native C·E05/E06-a를 직접 호출한다. 별도 engine execution Adapter/Manager·Dataset 포맷은 없다.
- `generation/mimic.py`에는 B02의 기존 numeric IK 필드/dtype/단위로 기록하는 `ik_record`만 추가했다. DLS 수식·고정 Best Effort·측정 seed·joint order·model/frame identity·finite/limit/0.5rad guard는 이전 계산을 사용한다. SciPy/Strict/Hold/선택 옵션/fallback은 없다.
- `recipe.py`: DataGen의 명시 `resume_dataset`, 기존 2000 step 상한의 선택 `max_episode_steps`, 실행 관련 파일 hash 고정. DataGen model 설정은 Annotation을 상속하며 별도 engine_config override는 거부한다. `run.py`: Isaac AppLauncher 카메라 활성화와 기존 구체 stage dispatch를 사용한다. 실제 worker에서 fast shutdown이 terminal 기록 전 process를 종료하는 반례를 확인해 공식 `fast_shutdown=False`로 수정했다. 물리/제어 설정은 바꾸지 않는다.
- `isaac/state.py`: 원래 v8처럼 고정 robot root는 Scene anchor를 사용하고 q/qd를 복원한다. 관측된 root telemetry를 다시 쓰면서 생기는 round-trip drift를 피한다. Scene과 호환되지 않는 고정 base/속도는 **효과 전에 거부**한다. 원래 v8의 base 비교 `atol=1e-5`를 재사용했으며 판정 tolerance를 바꾸지 않았다. raw Source initial을 수정하거나 정규화하지 않는다.
- `isaac/mdp.py`: 실제 step 후 비유한 articulation/rigid state를 오류로 처리한다. 이미 적용된 명령의 효과를 not_applied라고 표시하거나 자동 재전송하지 않는다.
- 데이터: 관측은 pre-step, tracker는 post-step이다. DataGen의 `joint_targets`는 **float64 solver command**, `ik/applied_joint_rad`는 실제 엔진 payload(Isaac float32/MuJoCo float64)다. 이전 적용 reference는 실제 step 뒤에만 갱신한다. post-step q/latch 및 실제 contact telemetry는 명시 `states/*` Tensor로 보존하며 pre-step 관측으로 합치지 않는다. S64 이유는 Native 최소 보존 Metadata로 dtype/shape/bytes를 유지한다. 전체 q/force/IK trace를 production JSON에 중복 저장하지 않는다.

## 실제 실행 결과

최종 코드의 실제 R03 실행을 포함한 비교 대상은 `runs/mujoco-worker-release-final`→`runs/mujoco-resumed-release-final`, `runs/isaac-worker-datagen-first`→`runs/isaac-worker-datagen-resume`이다. Resume의 2개 중 첫 Episode는 이전 불변 자료 참조이고, 새 실제 생성은 두 번째 1개다. 앞선 진단/재검증의 중복 성공을 최종 2개에 더하지 않는다.

| 최종 자료 | Episode / attempt | 각 frame | Grasp post / 저장 pre | 유효 비수렴 적용 | 최대 실제 arm target 점프 |
|---|---|---|---|---|---|
| MuJoCo 최초+Resume | 누적 2 / success1,2 | 399 / 399 | 228 / 229 | 각29 | 약0.108825588rad |
| Isaac 최초+Resume | 누적 2 / success1,2 | 399 / 399 | 228 / 229 | 각29 | 약0.108453676rad |

모두 최종 StableGrasp latch AND Placement가 실제로 참이었다. 실패/미완료를 성공 Dataset으로 넣지 않았다. attempt1 seed=892243098이며 SeedSequence([1047,1])다. MuJoCo reset seed stream은 기존 단일 worker 규칙으로 attempt 수만큼 소비하고 성공 수로 재시작하지 않는다. Isaac Fixed 배치는 Reset draw가 없다는 별도 identity를 기록한다. 과거 Isaac의 persistent per-env Random RNG를 MuJoCo reset stream으로 바꾸지 않았다.

**B01과의 차이:** B01 DataGen의 SciPy+Strict와 새 DLS+Best Effort의 궤적/수렴 실패는 승인된 정책 변경이다. 이번 Fixed 시험은 table 중심과 X 방향 55mm 간격의 명시 Recipe 초기 배치도 사용했으므로, 궤적 차이 전체를 IK만의 효과로 분리했다고 주장하지 않는다. Scene/보정/물성은 불변이다. B01의 최초 Grasp tick231을 새 정책의 정답으로 강제하지 않았으며, 새 post228→pre229도 같은 저장 phase 계약이다. B01 Isaac DataGen 실패를 성공으로 덮어쓰지 않았다.

### Annotation과 초기 상태

실제 Source388의 q와 float32 target은 B01과 exact였다. 새 앱의 production Annotation q는 그 Source와 exact이고, post q/qd 및 선택한 gripper/jaw→cube_red 힘은 E01 최종 실행 trace와 exact다. 자동 post221/저장222, 공식 Pool half-open 끝223을 구분한다. manual mark203은 물리 최초 grasp tick을 이동한 값이 아니다. MuJoCo의 기존 post222/pre223도 유지한다. [저장 배열 직접 대조](evidence/simulation-workflows/b01-alignment-results.json)에서도 q/latch exact이며 cube_red 위치 성분 최대차는 저장 pre311의 Y에서0.0011971890926361084m다. 이는 저장 float32 표현 기준으로, E01의 post310 float64 성분 잔차와 같은 OPEN을 가리킨다.

원래 Source initial과 Annotation 재저장 initial은 각각의 소유권을 Metadata에 남긴다. 고정 robot base의 측정값 재쓰기 진단·같은 앱 cross-stage reuse에서 관측된 q 차이는 [수명/복원 진단](evidence/simulation-workflows/isaac-restore-diagnosis/result.json)에 보존했다. 동일 설정 반복 비결정성이라고 단정하지 않는다. 새 앱 단일 단계의 성공으로 같은 앱 재사용·복수 Episode까지 완료 처리하지 않는다.

### 실패·취소·복구

- 실제 MuJoCo 2 step 뒤 cancel: 완료 Episode 0. 첫 실제 DLS step 뒤 통제된 invalid candidate: 완료 0·ik_failure, 이전 실제 적용 reference와 initial/실패 진단 보존. actual 모델 상한 바로 위 float32 gripper 입력은 clipping 없이 0 step ik_failure. 이는 fault fixture이고 자연 발생 성공 시험과 구분한다.
- 실제 DataGen child를 두 번째 attempt의 2 step 뒤 SIGKILL: 이전 완료 1개는 공식 파일로 읽히고 미완료는 노출 0. unknown intent의 Resume는 `NATIVE_STATE_UNKNOWN`. 최초 harness의 잘못된 기대 코드만 수정했고 물리 child를 다시 실행하지 않고 저장된 crash 상태를 검증했다.
- 실제 R03 Isaac worker는 최초에 전체 Step/commit 뒤 SDK의 기본 fast shutdown이 process0으로 종료되어 WORKER_EXITED였다. 공식 설정 `fast_shutdown=False`로 수정한 실제 재실행은 terminal completed/fixture_runner=false·q exact·post221을 확인했다. 이어 최종 코드의 DataGen 및 새 worker Resume도 terminal completed로 끝났다. 시험 bootstrap은 audit/Kit log 경로만 제공하며 stage/센서/결과를 대체하지 않는다.
- 실행 중 Annotation validation이 추가되어 code identity가 바뀐 중간 버전의 Resume는 `RESUME_INCOMPATIBLE`로 거부됐다. hash 검사를 완화하지 않았고 코드가 고정된 release→Resume를 따로 실제 검증했다.
- MuJoCo uniform probe는 v8 bbox 높이/기울어진 Support 검사의 충돌로 `INVALID_PLACEMENT`에서 중단했다. 위치·높이·margin·RNG 재추출로 통과시키지 않았다. 이 run은 성공 0/미해결 claim이며 자동 Resume 불가다. 현재 Revision의 legacy placement 의미에 대한 후속 근거가 필요하다.
- Isaac Source/Annotation/DataGen의 지원은 앱당 단일 stage/단일 env다. 최초 Source 수명 harness는 같은 앱에서 두 번째 환경을 생성하다 정체되어 자체 child만 종료했다. 추가 stack/close marker는 새 앱 Source의 정상 close·return을 확인했고, 새 앱 Resume는 누적2개(각2 frame), 별도 cancel은 완료0개였다. Source 종료 실패로 일반화하지 않는다. 실제 장치의 중지/토크/포트 해제 검증은 하지 않았다.

## 검증·증거

- **전체795 passed, skipped0**, 기존 torchvision deprecation warning2. [JUnit](evidence/simulation-workflows/unit-tests-final.xml), [로그](evidence/simulation-workflows/logs/69-full-suite-final.log). 기존778개와 신규17개다. 실제 Isaac 앱 실행은 pytest 수와 별도다.
- [공식 consumer 검증](evidence/simulation-workflows/generated-consumer-final-results.json): 실제 양 엔진 생성 Episode4개를 설치된 수정하지 않은 공식 HDF5 Reader/DataGenInfoPool로 재로드했다. 모든 저장된 post q→다음 pre q, post latch→다음 pre latch가 exact다. float64 stored/candidate arm exact, 실제 payload finite·0.5rad guard 통과, lineage/초기 상태/IK identity 존재를 확인했다.
- 양 camera의 모든 생성 RGB decoded uint8/640×480, 399 frame, 30FPS, PTS=ordinal/30을 검증했다. 실제 Isaac force와 MuJoCo bilateral contact가 존재한다. 원본 영상의 재인코딩이나 historical pixel equality 시험이 아니다. 기존 libx264/CRF18 계약을 유지한다.
- [wheel](evidence/simulation-workflows/build-workbench.json): source/config bytes·compile·reference 라이선스·isolated import·실제 미구현 train worker의 STAGE_UNAVAILABLE 검증. 환경에 설치하지 않았다. 새 dependency/업그레이드/환경 분리는 없다. 별도 lint/type 도구 실행을 주장하지 않는다.
- [Standards](evidence/simulation-workflows/standards-final-review.md): hard 위반0, 작은 IK summary 중복 heuristic1. 구체 엔진 루프를 합치는 추상화는 추가하지 않았다. [Spec](evidence/simulation-workflows/spec-final-review.md): 발견한 float32 저장 회귀를 수정하고 실제 산출물로 재검증했다. 부분 지원을 전체 AC 통과로 표시하지 않는다.
- [보존 대조](evidence/simulation-workflows/preservation-after.json): 기존56,100개 파일 stat 및 선택18,342개 SHA의 미승인 변화0. 기존 전체 corpus/SDK binary의 전수 byte 증명은 아니다.
- [명령·identity](evidence/simulation-workflows/commands.json), [최종 검증](evidence/simulation-workflows/verification.json), [보존 대조](evidence/simulation-workflows/preservation-after.json)에 원본 stat/선택 SHA와 제품/입력/증거 identity를 기록한다. Git 저장소가 아니므로 commit을 만들지 않았다.

공식 API는 설치 소스와 [Isaac Lab2.3 ManagerBasedEnv](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html), [Mimic Pool](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab_mimic/isaaclab_mimic.datagen.html), [MuJoCo3.3.7 Python](https://mujoco.readthedocs.io/en/3.3.7/python.html), [Isaac Sim5.1 SimulationApp 종료 설정](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/py/source/extensions/isaacsim.simulation_app/docs/index.html)을 기준으로 한다. 공식 Pool child module의 eager simulator import를 피하는 namespace 설정은 증거 harness에만 있으며 새 Plugin/제품 Wrapper가 아니다.

## 남은 관문과 다음 범위

E01 물체 잔차·Isaac Random RNG continuation·다중 Episode Annotation·같은 앱 재사용·장시간/다중 env·공식 Policy/학습 의미 매핑은 OPEN이다. 잔차를 허용 오차 변경이나 fake 접촉으로 없애지 않았다. 이번 Fixed 생성들에서는 Grasp/Placement 및 기록 의미를 확인했지만 전체 Scene/성공률에 대한 영향을 일반화하지 않는다.

이 자료를 입력으로 **L03의 공식 Dataset/action/processor 매핑 검증을 다음 후보**로 삼을 수 있다. 그 검증 전 “학습 호환 완료”라고 하지 않는다. 외부 공식 Dataset의 L01/L02는 독립적이다. 이번에는 Learning 및 L/P/C/U/X를 시작하지 않는다.
