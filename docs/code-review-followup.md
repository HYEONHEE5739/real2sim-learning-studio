# 코드 리뷰 후속 수정 4건 — 새 명세 기준 재구현

2026-10-29. 기준은 `e1059579506de7bb6051918da3cc70e7f8b524d4`, 브랜치는 `architecture-completion`이다. 교체된 프롬프트와 사용자의 재시작 지시에 따라 **앞선 수정·신규 시험 14개 경로를 먼저 제거했다.** `b2d7888`에서 제품·시험 파일이 기준 Commit과 완전히 같은 것을 확인한 뒤 새 명세로 구현했다. 이전 구현에 호환 분기나 두 번째 구현을 덧붙인 결과가 아니다. 이전 Git 기록은 보존하지만 최종 소스에는 폐기한 함수·시험을 유지하지 않는다.

새 구현 Commit은 `1a745b7`, 독립 리뷰에서 발견한 경로 반례 수정은 `89de48b`다. 로컬 `main`과 `origin/main`은 모두 `8a8210d13e31ea2c777e120f4e8fb0640050fec0` 그대로다. Push·Merge·force push·설치·실물 연결은 수행하지 않았다.

## 재현한 문제와 수정

| 문제 | 기준 소스에서 확인한 원인 | 현재 처리 |
|---|---|---|
| Policy 폴더 선택 불일치 | Recipe/UI는 바로 아래 `config.json`만 확인하고 Loader는 내부 `pretrained_model/`도 찾았다. CLI Fine-tune은 소유 Processor 손상을 검사하지 않았다. | 하나의 가벼운 경로 함수로 해석하고, 실제 로딩·Processor·소유 Manifest/SHA 검사는 기존 Loader에 유지한다. Fine-tune도 기존 `checkpoint_record`를 호출한다. |
| 외부 Policy 독립 Validation | Dataset 계약과 `record.control_contract`를 무조건 비교하여 Workbench Metadata가 없는 공식 모델을 거부했다. | 공식 Feature 종류·입력/출력 shape를 검사한다. 외부 모델의 계약 없는 수치 비교를 허용하되 단위·로봇 제어 의미·lineage는 미검증으로 표시한다. |
| Builder Capture 의존성 누락 | 오프라인 Stage가 Builder Reader를 직접 쓰지만 설치 계약이 없었다. | `offline` 선택 의존성을 선언하고 해당 Stage의 준비·실행에서 명확한 의존성 오류를 제공한다. Reader는 복제하지 않는다. |
| Real Policy 사전 검사 누락 | Precision 역변환까지만 계산하고 승인 model/motor 교집합·Saturation·SDK 정수 encoding을 확인하지 않았다. | Teleop의 기존 순수 명령 계산을 공유하여 최종 SDK encoding 및 양자화 후 범위를 재검사한다. 정보 부족은 PARTIAL, 거부는 실패와 거부 보고서로 남긴다. |

기준 소스의 재현은 새 증거 영역 `docs/evidence/review-followup/logs/01-baseline-red.log`, `02-commands-red.log`에 있다. 초기 RED에는 아직 지원하지 않는 계약 입력 때문에 먼저 거부된 사례도 포함된다. 해당 입력이 지원된 이후에는 실제 Feature/단위/관절 순서 불일치 검사를 따로 통과시켰다. 시험 harness에서 빠진 `episodes`와 허용되지 않는 `seed`를 수정한 과정도 로그에 남겼으며 제품 설정 검사를 완화하지 않았다.

## 파일과 실제 호출

| 파일 | 변경 책임 |
|---|---|
| `recipe.py` | `policy_model_path`: 공식 Model root/소유 Checkpoint root/직접 leaf 해석. 실제 소유 leaf 선택도 부모 Manifest까지 Prepared identity에 포함. SDK 보정 파일과 실행 Control 소스도 고정. |
| `learning/policy.py` | 같은 경로 해석 후 기존 공식 Factory/Processor·Manifest/SHA 검사. Simulation에서는 명시 계약 및 absolute model-radian 의미와 충돌하는 Aloha/delta 옵션을 거부. |
| `learning/train.py` | 공식 `pretrained_path`와 Recipe 선택을 같은 모델 폴더로 비교하고 소유 Checkpoint의 무결성을 검사. 공식 Trainer/Resume는 그대로 사용. |
| `learning/validate.py` | 공식 `dataset_to_policy_features`로 실제 Dataset과 비교. 기존 학습 Dataset identity 및 Episode 중복 검사를 유지. |
| `ui/workflow.py`, `ui/learning.py` | 같은 모델 이름·경로 표시, 공식 Fine-tune JSON에는 실제 모델 폴더를 저장. 독립 Validation에서 기존 `policy_contract` 입력도 선택 가능. |
| `pyproject.toml`, `robot/offline.py` | Builder 선택 의존성, 기존 Capture Reader 호출, 계산 전용 SDK 검사 및 명시 결과. |
| `robot/control.py` | 기존 Teleop의 model/motor 교집합부터 최종 encoder 검사를 `encode_model_target` 한 구현으로 공유. `command_target`는 기존 Leader 변환 후 이를 호출. |

경로 함수는 Recipe/UI에서 필요한 파일 배치만 해석한다. GUI가 경로를 표시하려고 Torch·LeRobot·물리 엔진을 import하지 않도록 실제 Policy 로딩은 계속 `learning/policy.py`가 소유한다. 새 Policy Loader·Manager·Adapter·Dataset 포맷은 없다.

독립 리뷰에서 **부모에 Manifest가 있는 별도 공식 모델 폴더를 부모 모델로 바꾸는 반례**를 찾았다. 소유권을 실제 `pretrained_model/` 자식에만 한정했다. ACT Checkpoint 내부의 `downloaded_diffusion/`를 선택하면 이제 그 Diffusion 폴더와 모델을 유지한다. RED→GREEN·실제 Loader·최종 Worker를 모두 확인했다.

### 경로와 Checkpoint 요구사항

- 공식 모델 폴더에는 config/weight/processor가 필요하며 Workbench Manifest나 optimizer를 강제하지 않는다.
- 소유 Checkpoint root 또는 leaf를 선택하면 기존 closed-record·SHA·Processor 검사가 적용된다. 소유 기록을 가진 leaf를 독립 외부 모델로 낮춰 검사하지 않는다.
- Training Resume는 기존 Checkpoint/training_state 계약을 요구한다. Policy 선택만으로 학습 상태 복원을 승인하지 않는다.
- 잘못된 경로에는 필요한 공식 Model/Checkpoint/leaf 구조를 안내한다. 경로 해결을 위한 config/weight 복사는 없다.

## Offline Validation과 Simulation의 구분

**Offline Validation**은 공식 preprocessor → `select_action` → 공식 postprocessor의 예측값을 Dataset action과 비교한다. 모든 입력/출력 Feature 종류와 shape를 확인하고 action shape·finite를 검사한다. History/queue와 Episode Reset은 기존 공식 Policy 경로를 유지한다.

외부 Policy에 계약이 없으면 `contract_source=features_only`, `control_contract=null`, `units=unspecified_dataset_units`, `mae`/`rmse`로 보고한다. Dataset에 rad라는 표기가 있더라도 그것만으로 외부 Policy 출력의 의미를 승인하지 않는다. 확인되지 않은 Scene·Calibration·단위를 만들거나 값을 변환하지 않는다. 명시한 `policy_contract`가 Dataset의 검증된 계약과 일치하면 rad 지표를 사용할 수 있다. 기존 소유 Checkpoint의 계약은 계속 엄격하게 검사한다.

모든 독립 Validation은 `robot_control_approved=false`다. 외부 모델의 학습 원본을 알 수 없으므로 `lineage_status=unverified_external_provenance`다. 내부 모델은 기존 학습 Dataset identity와 원 Episode UID 중복 검사를 유지한다.

**Simulation Rollout**은 기존 `policy_contract` 또는 소유 계약을 통해 Scene/Calibration/실행 모델·SO101 순서·6축·model rad 절대 target·pre-step state·Side/Wrist 구성·30Hz를 검증한다. 계약 없음·degree·다른 관절 순서·delta/Aloha 변환은 거부한다. Offline Validation 통과를 이 승인으로 승격하지 않는다. 물리 Step·Task 성공 판정·Native 저장 계산은 수정하지 않았다.

## Builder 의존성과 오프라인 명령 검사

선택 설치 계약은 `robot-learning-workbench[offline]`이며 wheel Metadata의 요구사항은 `real2sim-builder>=0.1,<0.2`, `lerobot==0.4.1`이다. 별도로 준비된 기존 환경을 검사했으며 이번에 설치하지 않았다. Builder는 Workbench에 의존하지 않아 순환 의존이 없다. 독립 backend import/Training prepare는 Builder import를 차단한 subprocess에서도 통과했다. Capture/Real-Sim/Real Policy 보존 자료 검사는 Builder가 없으면 `STAGE_DEPENDENCY_MISSING`으로 거부한다. `precision_calibration`의 보존 profile 검사는 Capture Reader를 요구하지 않는다.

Real Policy 계산 흐름:

```text
보존 Capture↔Scene/관측 Calibration 결합 검사
→ 공식 Policy/processor 추론
→ 명시 device_command Calibration 결합 검사
→ 실행 URDF 및 승인 motor/Precision 범위 교집합
→ checked_target의 기존 inward Saturation
→ strict Precision inverse / encoder branch
→ 기존 Follower.encode_goal의 SDK 정수 인코딩
→ 양자화된 model target의 최종 범위 검사
→ inspection report
```

SDK 보정 원본은 **기존 `device_profile.calibration_path`**로 지정한다. Recipe가 해당 파일 bytes를 별도 Prepared artifact로 고정하고 profile의 보정 SHA와도 비교한다. 새 Recipe 입력 형식이나 추가 UI 폼을 만들지 않았다. 파일이나 command binding이 없으면 PARTIAL이며 encoding 검증 통과로 표시하지 않는다.

SDK 검사는 구체 Feetech serial 생성자를 호출하지 않는다. 공식 `MotorsBus.__init__`의 데이터 테이블 초기화 및 `_normalize/_unnormalize`, 기존 `Follower._check_identity(hardware=False)`와 `encode_goal`만 사용한다. 시리얼 handle·연결·레지스터 읽기·토크·send는 없다. 정상/초과 요청, motor 제한, 교집합 없음, NaN/Inf/shape/unit/order, encoder branch·양자화·SDK 불일치 및 보정 identity 반례를 시험했다.

보고서는 원 요청, Saturation, bounds, encoded model target, native target, SDK integer goal과 encoding 가능 여부를 구분한다. Encoding 사전검사에서 거부하면 `REJECTED` 보고서를 남기고 원 예외를 전파하여 Worker는 실패한다. 그 이전의 잘못된 Policy 출력·binding 오류는 기존 R03 실패/error record로 남으며 명령 변환을 수행하지 않는다. 실패를 정상 완료로 바꾸지 않는다. `command_sent=false`, `hardware_connected=false`, `physical_verified=false`는 유지한다. 수치 encoder 검증은 실물 안전성 승인이 아니다.

## 새 검증 결과와 한계

- **최종 전체 1,026 passed / skipped 0**, 기준 987개에 신규 39개. Scene Contract·Builder·Capture·Source/Annotation/Fixed/Random·Native/Resume·Curation/LeRobot·Training/Resume·Factory·Validation/Evaluation·Hub 경계·Qt/출력 경로 회귀를 포함한다. torchvision의 같은 영상 deprecation 경고가 4회 발생했다. 별도 lint/type 도구를 설치하거나 실행하지 않았다.
- 실제 공식 ACT·SmolVLA·Diffusion을 각각 root/leaf/외부 무계약/외부 명시 계약으로 **R03 Worker 12건×3batch** 소비했다. 보존 weight·실제 공식 Dataset/DataLoader/RGB/processor/inference를 사용했다. 외부 형식 시험은 보존된 공식 모델 파일을 수정 없이 참조한 것으로, 새로운 Hub 다운로드나 외부 학습 provenance 검증이 아니다.
- 마지막 부모 소유권 수정 후에는 별도 공식 Diffusion 폴더의 **추가 Worker 1건×3batch**, 실제 Loader 반례 및 최종 전체 회귀를 수행했다. 앞선 12건과 마지막 수정의 검증 범위를 구분한다.
- 이번에 학습을 추가하거나 Isaac 전체 물리 workflow를 새로 실행한 것은 아니다. Training/Resume·물리 workflow의 회귀 시험, 위 실제 공식 추론, controlled Capture/Policy 및 Fake/순수 SDK 시험을 구분한다. 과거 실제 Training/Simulation 증거를 이번 실행 횟수로 세지 않는다. 작업 성공률이나 수렴을 주장하지 않는다.
- Workbench·Builder wheel은 새 증거 폴더에서 빌드했다. source/config bytes·compile·격리 import/CLI, 실제 invalid-config Worker, 선택 의존성 Metadata를 확인했다. 환경에 설치하지 않았다.
- 독립 Standards 최종 미해결 0건, Spec 최종 High/Medium 0건. 부모 소유권 Medium을 재현·수정하고 독립 재검토를 통과했다.

실물에서는 승인된 command Calibration/실제 motor range·encoder branch·양자화·토크 release·timeout·카메라 시간 결합·정지/취소 등을 별도로 확인해야 한다. 현재 v8의 command binding·실측 정확도·E01 물체 잔차를 해결했다고 보고하지 않는다. 기존 Smol 호환 모듈의 SHA 고정 방식, Scene v8/Collision·Mimic/IK·Saturation 정책도 유지한다.

## 보존·Git·근거

원본 **56,100개 파일 stat·선택 57개 SHA 변화 0**, v8 전체 Manifest 검증 통과다. 이번 실제 소비에 사용한 Dataset/Checkpoint **53개 파일 SHA 전후 변화 0**도 확인했다. 전체 SDK binary/대용량 corpus를 전수 byte hash했다는 뜻은 아니다. 원본 파일을 이동·재생성·재보정하거나 SDK 소스를 수정하지 않았다.

최종 비교는 `git diff e105957...HEAD`다. 폐기 구현의 복원 Commit 다음 새 코드 Commit과 반례 수정만 현재 제품 차이를 구성한다. 제품 변경은 위 9개 파일이며 Builder/Scene Contract 제품 코드는 변경하지 않았다. 최종 변경은 제품/패키지 설정 9개·시험 5개·문서 3개, 총 17개 파일이다. 새 시험은 `test_policy_paths.py`, `test_external_validation.py`, `test_offline_dependencies.py`, `test_offline_commands.py`이며 기존 `test_offline_validation.py`의 PreparedRun fixture만 실제 입력 필드에 맞췄다. 기존 main은 그대로이며 요청 없이 GitHub로 Push하지 않는다.

상세 로컬 근거는 `docs/evidence/review-followup/`의 `restart.json`, `verification.json`, `final-tests-release.xml`, `actual-model-results.json`, `nested-worker-results.json`, `read-only-inputs-after.json`, `preservation-after.json`, 두 wheel 결과 및 RED/GREEN 로그다. 증거 폴더는 기존 공개 제외 정책을 유지한다.

공식 API 근거: [LeRobot0.4.1 Policy 로딩](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/policies/pretrained.py), [Dataset Feature 변환](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/datasets/utils.py), [Motor 정규화·인코딩](https://raw.githubusercontent.com/huggingface/lerobot/v0.4.1/src/lerobot/motors/motors_bus.py). 실제 고정 설치 소스와 실행 시험을 우선 근거로 사용했다.
