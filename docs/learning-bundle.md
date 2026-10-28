# L01·L02 — 공식 ACT Training·Resume·Policy·독립 Validation

2026-10-27. **L01의 ACT 실행과 L02의 ACT 로딩/추론·독립 Validation 범위를 구현·실행 검증했다. SmolVLA Training은 SMOL-PAD-01로 BLOCKED다.** 실제 작업 성공률·전체 학습 수렴·물리 Rollout·실물 안전성을 검증한 결과가 아니다. L04/P/C/U/X는 시작하지 않았다. [L03](l03-lerobot-dataset.md)의 Native C→공식 Dataset·Action/선택 계약을 그대로 재사용했다.

## 구현과 호출 경계

| 제품 파일 | 책임 |
|---|---|
| [learning/train.py](../robot_learning_workbench/src/robot_learning_workbench/learning/train.py) | 공식 config 검사·실행용 bytes 고정, `python -B -m lerobot.scripts.lerobot_train` child 실행·취소·로그/비유한 값 감시·닫힌 checkpoint 확인. 학습 loop·optimizer·scheduler를 구현하지 않음 |
| [learning/policy.py](../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py) | 공식 checkpoint 파일/identity 확인, 공식 ACT/processor 로딩·select_action→postprocessor, model rad 출력 shape/finite/order 및 선택적 strict limit 검사 |
| [learning/validate.py](../robot_learning_workbench/src/robot_learning_workbench/learning/validate.py) | 별도 worker에서 저장 Policy와 val Dataset 로드·실제 DataLoader/추론·MAE/RMSE/시간/RSS. Trainer가 자동 호출하지 않음 |
| [recipe.py](../robot_learning_workbench/src/robot_learning_workbench/recipe.py), [run.py](../robot_learning_workbench/src/robot_learning_workbench/run.py) | 기존 준비/claim/IPC/worker에 두 stage 연결. 공식 Dataset은 작은 Metadata hash+파일 목록/크기로 고정하며 매번 MP4 전체 hash/디코딩하지 않음 |

새 package initializer와 4개 시험 파일을 추가했다. 기존 Recipe/Runner 시험 2개는 실제 지원 상태에 맞춰 STAGE_UNAVAILABLE/미구현 Resume 기대를 명시 config 오류/필수 checkpoint 검사로 바꿨다. [작업 전 사본](evidence/learning-bundle/before/)을 보존했다. `data/lerobot.py`, Native·Curation·엔진·Scene·Builder·Task·Robot 계산과 pyproject 의존성은 변경하지 않았다. 별도 Trainer/Model Wrapper·Dataset 포맷·Manager·custom hook은 없다.

## L01 — 실제 ACT 학습과 공식 Resume

입력은 L03의 영구 Curation 결과 **train 2 Episode/152 frame, val 2/180 frame**이다. 양 엔진의 Fixed 생성 원본은 총4 Episode지만 학습에는 선택된 train 구간만 썼다. state와 action은 JOINTS 순서의 model rad 6개다. state는 pre-step measured, action은 해당 step의 recorded absolute joint target이며 solver/applied/post-state를 혼동하지 않았다. Side/Wrist RGB **640×480·30FPS**를 공식 Dataset/processor로 소비했다. 영상 재인코딩·Dataset bulk copy는 없다.

최종 실제 실행은 [scratch worker](evidence/learning-bundle/worker-final-results.json)와 [Resume worker](evidence/learning-bundle/worker-resume-final-results.json)다. `_runner` 주입 없이 Recipe→R03 worker→수정하지 않은 공식 CLI를 실행했고 중복 start는 같은 Handle을 반환했다.

| 설정 | 실제 값 |
|---|---|
| Policy | 공식 ACT, random initialization; backbone pretrained weights=None |
| 입력 | state6/action6, 양 camera640×480; 공식 float32 학습 Tensor |
| 모델 | chunk_size/n_action_steps=10, dim_model128, heads4, FF512, encoder/decoder/VAE encoder 각1 |
| 실행 | CUDA, batch1, workers0, seed1047, save/log 매1 step, AMP 기본 false |
| optimizer/scheduler | 공식 AdamW lr=1e-4, weight_decay=1e-4, grad_clip_norm=10; 공식 constant DiffuserScheduler/warmup0 |
| 외부 접근 | Hub/WandB·자동 env evaluation 비활성, HF offline. weight 다운로드/설치 없음 |

이는 공식 지원 config로 작은 smoke 모델을 만든 것이며 ACT 기본 production 모델의 학습 성능을 검증한 것이 아니다. 실제 forward/backward/optimizer를 **2 step** 수행한 뒤 **누적4 step**까지 새 출력으로 Resume했다. 공식 로그의 loss는 step1/2 **70.746/75.681**, step3/4 **70.773/54.390**다. 표시된 반올림 값이며 성능 개선/일반화 근거로 사용하지 않는다.

[공식 학습 상태 복원](evidence/learning-bundle/resume-state-final-results.json): `load_training_state`로 step2와 optimizer state를 실제 복원했고 243개 optimizer Tensor와 step counter2→4, scheduler last_epoch2→4를 확인했다. model SHA도 바뀌었고 이전 checkpoint bytes는 그대로다. RNG state는 공식 경로로 복원하지만 **중단 없는 실행과 DataLoader/shuffle까지 bitwise 같은 continuation은 보장하지 않는다.**

공식 Resume는 config_path의 부모에서 checkpoint 위치를 정한다. 따라서 실행 소유의 표준 official checkpoint 배치에 JSON bytes를 복사하고 불변 weight/state를 hardlink한 `.resume-input`을 사용한다. 원본 config/checkpoint를 수정하거나 SDK parser를 패치하지 않는다. 허용되는 요청 변경은 누적 steps·새 output·resume뿐이며 Dataset/config 불일치는 거부한다. scratch도 실행 소유 JSON을 고정하므로 실행 중 원 설정 편집은 다음 실행에 적용된다.

### Checkpoint·오류·취소

공식 model/config·processor·optimizer/RNG/step·설정상 필요한 scheduler 파일을 확인하고 safetensors 가독성/finite·저장 config/초기 Dataset identity를 검사한 뒤 작은 `workbench-checkpoint.json`에 파일 SHA/step/Recipe/Dataset/control identity를 기록한다. 공식 저장 완료 뒤의 기록이며 별도 model bulk format이 아니다. 파일 존재·loss 로그만으로 완료 처리하지 않는다. owned checkpoint의 변경/누락·불완전/비유한 tensor는 거부한다.

[실제 취소](evidence/learning-bundle/worker-cancel-final-results.json): 공식 학습 child에 SIGTERM을 보내 종료(-15)를 확인했고 **정상 checkpoint1~3**을 유지했다. step4의 loss 기록은 완료 checkpoint4를 의미하지 않는다. 무응답 child의 bounded TERM→KILL은 모의 subprocess 경계로 별도 검사했다. 실제 GPU OOM/SIGKILL 전원 장애를 주입한 시험은 아니다.

NaN/Inf loss·gradient는 실패로 처리한다. child가 poll 사이에 끝나 최종 로그에서만 NaN을 발견하는 통제 fixture에서도 이전 정상 checkpoint는 남는다. 설정상 loss 로그가 한 번도 나오지 않는 step 간격은 실행 전에 거부한다. **표시용 수치 파싱 실패/형식 미인식은 Trainer 완료를 실패로 바꾸지 않으며** 원 공식 로그를 보존한다. 명시적 NaN/Inf 실패 관문은 사용자 요구에 따른 별도 검사다.

현재 cancel ACK의 completed는 child 종료 확인보다 앞설 수 있다. 실제 run terminal 상태는 종료/정리 후에만 나온다. ACK만으로 프로세스 종료를 판단하면 안 되며 [Spec 리뷰](evidence/learning-bundle/spec-review.md)의 Low 잔여 항목으로 남긴다.

## L02 — 실제 로딩·Action 후처리·독립 Validation

공식 `PreTrainedConfig` registry·`ACTPolicy.from_pretrained`·`make_pre_post_processors`를 사용했다. 이미 저장된 전체 모델을 복원할 때 backbone 다운로드를 막는 초기화 옵션만 메모리에서 None으로 둔다. 저장된 가중치/정규화 통계는 공식 파일에서 로드한다. 외부의 정상 official ACT Policy/config/processor 로딩에도 Workbench provenance/optimizer를 강제하지 않는다. 단 의미 미확인 외부 Policy를 자동으로 SO101 제어 호환이라고 승인하지 않는다.

[실제 chunk 검사](evidence/learning-bundle/policy-queue-final-results.json): normalized `[1,10,6]`에 공식 postprocessor를 적용한 model rad 절대 target과 10회 `select_action` queue 소비 결과가 exact였다. Reset 후 첫 action도 exact이며 checkpoint 변경은 없었다. 선택한 chunk10개는 strict model bounds를 통과했다. 이 표본을 전체 출력의 제어 적합성이나 물리 성공으로 확대하지 않는다.

[독립 Validation worker](evidence/learning-bundle/validation-final-worker-results.json)는 저장된 step4를 새 process에서 로드하고 실제 DataLoader·양 RGB·pre-step state로 **180 batch** 추론했다. train의 recorded Dataset identity를 재확인한 뒤 source Episode UID 교집합0을 확인한다. 누락/변경 identity·train/val 중복은 출력 생성 전에 거부한다. Episode마다 Policy queue를 Reset하며 batch_size1만 지원한다. Trainer의 loss나 train 재생 결과를 Validation으로 사용하지 않았다.

[최종 지표](evidence/learning-bundle/runs/offline-validation-final/validation.json), JOINTS 순서:

| 관절 | MAE rad | RMSE rad |
|---|---:|---:|
| shoulder_pan | .02304165 | .02855057 |
| shoulder_lift | .50270826 | .74076974 |
| elbow_flex | .36672732 | .47876531 |
| wrist_flex | .11131359 | .12184781 |
| wrist_roll | .06598980 | .06891400 |
| gripper | 0 | 0 |

그리퍼0은 이번 짧은 선택 구간의 target/통계 조건에 따른 값이며 grasp 학습 성공이 아니다. 이 지표는 **후처리된 queued action과 같은 frame의 기록 target** 비교다. 실제 물리 작업 성공률은 unmeasured다.

## SMOL-PAD-01 — 실제 forward 반례, Training BLOCKED

설치 소스 `SmolVLAPolicy.forward:324`는 `batch.get('actions_id_pad')`를 읽는다. 실제 공식 Dataset/processor batch에는 `action_is_pad`만 있었고 중간 processor의 키 변환은 없었다. [최소 실제 forward](evidence/learning-bundle/smol-padding-final-results.json)는 캐시된 local SmolVLM config·random weights, VLM/expert 각1 layer·chunk4, 실제 RGB/state와 `[False,True,True,True]` padding을 사용했다. weight 다운로드·optimizer step은 없다.

동일 noise/time에서 원 batch loss=**2.1944031715**, pad 키 제거 loss도 exact 동일했다. loss는 padded action까지 포함했다(진단 tensor96개 요소). 통제 실험으로 loss가 인식하는 키를 추가했을 때 **.4925189614**였으나 이 변경은 증거 harness의 비교 입력뿐이다. 제품 converter/Trainer/SDK에는 키 치환을 넣지 않았다. chunk1을 해결책으로 채택하지 않았고 SmolVLA 학습/전체 지원을 완료 처리하지 않는다.

## Strict float32·Follower·P01 관문

[기록값의 실제 MuJoCo command preflight](evidence/learning-bundle/control-boundary-results.json): 각399 frame Episode의 원 float64 command는 통과했지만 float32 변환 뒤 **4 frame/Episode**의 wrist_flex가 거부됐다. upper=1.7453264625997165rad, float32=1.7453265190124512rad로 **5.64127347e-8rad** 초과다. `validate_action(...,limits=...)`도 같은 값을 거부한다. 한계 확대·clipping·기록 target 수정은 없다. 이는 IEEE 표현 차이이고, 위 실제 NN의 더 큰 예측 오차와 별개다.

`infer`는 공식 postprocessor 뒤 model rad를 반환하고 순서/6축/finite를 검사한다. 정확한 model limits를 제공하면 strict 검사하며 초과는 POLICY_ACTION_UNSAFE다. 독립 Validation은 물리 배포용 model binding을 요구하지 않아 오차 지표만 산출한다. **limits 미제공 결과를 제어 승인으로 간주하면 안 된다.** 엔진 적용 시 기존 엔진 preflight도 필수다. 모든 실제 Policy 출력의 limit 적합성/제어 안정성과 Rollout은 P01 미검증이다.

Follower는 L03의 shoulder_lift motor-range 거부와 Scene의 `device_command` 부재가 그대로다. model rad→승인된 command Precision inverse→encoder branch/range/SDK 정수 검사가 필요하며 관측 binding을 자동 재사용하지 않는다. 실제 명령·로봇/모터/카메라 연결은 없다. E01 cube–cup1.197188790mm와 Random/복수 Episode 등 기존 OPEN도 유지한다.

## 시간·메모리·회귀·보존

| 실제 경로 | 시간 | CPU Peak RSS | GPU 측정 |
|---|---:|---:|---|
| 공식 scratch2 step | child9.374s / R03전체15.448s | child2280.125MiB | nvidia-smi 장치 전체 peak1213MiB |
| 공식 Resume2→4 | child9.966s / R03전체16.618s | child2297.438MiB | 장치 전체 peak1193MiB |
| CPU Validation180 | 평균 추론17.123ms/batch | process1254.340MiB | CPU 추론 |
| Smol 진단 forward3회 | 11.004s | process2179.613MiB | Torch peak allocated760.268MiB |

GPU 전체 사용량은 desktop/다른 사용량을 포함한 polling 값이며 모델 단독 allocation이나 순간 최대의 보장이 아니다. CPU RSS도 import/모델/Arrow를 포함한다. Validation은 최종 실행에서 다른 검증과 병행했으므로 전용 성능 benchmark가 아니다. Checkpoint는 새 출력에 저장했고 원 Dataset·영상은 공유한다.

**최종 전체832 passed, skipped0**, 이전815+신규17. [JUnit](evidence/learning-bundle/unit-tests.xml), [로그](evidence/learning-bundle/logs/46-final-suite.log), [wheel](evidence/learning-bundle/build-workbench.json). wheel source/config bytes·compile·isolated import/CLI·실제 invalid-config worker 거부를 확인했고 환경에 설치하지 않았다. torchvision 기존 warning2개는 남는다. 별도 lint/type 도구를 새로 설치/실행하지 않았다.

[Standards](evidence/learning-bundle/standards-review.md)는 미해결 문서 기준 위반0/선택적 중복 목록 heuristic1, [Spec](evidence/learning-bundle/spec-review.md)은 High/Medium 해소/위 cancel ACK Low1이다. Git 저장소가 없어 작업 전 사본/파일 SHA를 기준으로 독립 검토했으며 Git diff/commit을 수행했다고 보고하지 않는다. 단순화는 사용하지 않는 import 제거와 중복 metrics parser 정리만 했고 Trainer 계층을 추가하지 않았다.

[보존](evidence/learning-bundle/preservation-after.json): 원본56100개 파일 stat와 선택205개 SHA의 미승인 변경0. B01/B02/B03·선행 보고서/검증 root·Native 입력과 L03 결과·선택 SDK 소스 등이 대상이다. 모든 과거 증거/대용량 corpus/SDK binary를 이번에 전수 byte hash했다는 뜻은 아니다. 설치/업그레이드·환경 분리·원본 변경·Hub 업로드가 없다.

[설치 소스](evidence/learning-bundle/source-inventory.json), [명령](evidence/learning-bundle/commands.json), [최종 검증](evidence/learning-bundle/verification.json)에 입력/코드/증거 identity와 초기 실패·RED/GREEN을 남긴다. 초기 공식 registry 미등록, ACTConfig 대신 다형 config loader 필요, 테스트 harness의 subprocess patch 범위 오류를 수정했고 원본 데이터/판정/허용 오차는 바꾸지 않았다.

AC01의 실제 ACT train, AC02의 ACT 공식 processor/checkpoint/Resume·Policy/독립 추론 부분을 검증했다. Smol 학습 AC02와 Hub/L04·물리 제어 P01/P03·장시간/OOM/전원 장애는 미완료다. **P01의 제한된 Simulation Rollout을 준비할 학습/로딩 경계는 확보했지만 제어 호환 완료는 아니다. strict float32/출력 검사 계약을 유지한 별도 검증이 필요하다. 이번은 L01/L02에서 중단한다.**
