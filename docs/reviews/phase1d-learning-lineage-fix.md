# Phase 1D — LeRobot Checkpoint 및 Dataset Lineage 수정

2026-11-15. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `97c029e195ab8587603fb3f240f2c1a6c0f91f52`. [감사 BUG-006/007](full-codebase-audit.md)과 [Phase 1A](phase1a-regression-fix.md)·[1B](phase1b-fitting-refit-fix.md)·[1C](phase1c-isaac-camera-intrinsic-fix.md)의 실제 미커밋 Working Tree에서 시작했다.

**COMPLETED — BUG-006/007을 수정하고 최종 전체 2,024 passed / 실패0·오류0·skip0, 실제 exit0을 확인했다. 기존 1,984개 testcase 누락0·신규40개이며 보호 파일19,612개 변경·누락·신규0이다.** 실제 CPU Tiny ACT의 Scratch/Resume 각1 update도 완료했다. GPU 학습·실물·사용자 자료 실행과 정책 품질은 검증하지 않았다. 설치·다운로드·Commit/Push/Merge는 하지 않았다.

원시 근거는 저장소 밖 `/tmp/real2sim-phase1d-20261115-534a7mak/`에 있다. 이 폴더가 삭제되면 원시 로그를 열 수 없으며 제품은 해당 경로에 의존하지 않는다. 회귀 시험은 임시 Native HDF5·공식 LeRobot Parquet·유한한 작은 Tensor/공식 Training State 파일을 사용한다. 이 구조 fixture와 별도로 공식 Trainer의 **CPU Tiny ACT Scratch 1 update + Resume 1 update**도 실행했다. 어느 결과도 실제 로봇 정책 품질의 근거가 아니다.

## 1. BUG-006 원인과 공식 API

실제 호출은 `TrainingJsonDialog → ui.operations.execute('training_config') → validate_config/training_command → freeze_inputs → TrainPipelineConfig → 공식 Trainer/save_checkpoint → seal_checkpoint → checkpoint_record/Resume`다. UI·Trainer·별도 학습 Framework를 새로 만들지 않았다.

설치된 LeRobot **0.4.1**, Draccus **0.10.0**, Torch **2.7.0+cu128**, datasets **4.1.1**의 소스를 확인했다. 조사한 공식 파일 8개 SHA/함수 위치는 `installed-api-sources.json`, 실제 Config 관측은 `official-config-probe.json`에 있다. 설치·SDK 파일 변경 없이 기존 환경을 사용한다.

| 실제 공식 경계 | 확인한 동작 |
|---|---|
| `TrainPipelineConfig.from_pretrained` | Draccus로 전체 공식 기본 필드를 복원하고 Path·Enum·Policy config를 해석 |
| `TrainPipelineConfig.validate` | null/빈 job_name을 Policy 이름으로 정규화. scratch/fine-tune의 `use_policy_training_preset=true`면 Policy preset optimizer/scheduler 사용 |
| Resume validate | argv의 `--config_path`를 읽어 `policy.pretrained_path=소유 입력/pretrained_model`, `checkpoint_path=소유 입력 root`로 설정 |
| `make_policy` | 명시되지 않은 input/output features를 `dataset_to_policy_features`의 결과로 채운 뒤 모델 구성 |
| `save_checkpoint` | 변경된 TrainPipelineConfig와 실제 Policy config, processor, optimizer/RNG/Step을 공식 파일에 저장 |

기존 Sealer는 **정규화 전 요청 JSON**의 모든 명시 leaf를 저장된 Config와 literal 비교했다. 전체 UI JSON의 null과 Resume 경로 변경이 정상 Checkpoint를 거부했다. 요청 키가 적은 축약 scratch Config가 우연히 통과하는 것과 전체 UI 경로의 정상 동작은 다르다.

실제 CPU Config 예시는 다음과 같다. `optimizer`는 해당 ACT preset의 값이며 임의로 택한 학습률이 아니다.

| 필드 | 요청 | 공식 저장 의미 |
|---|---|---|
| job_name | null | `act` |
| optimizer | null | AdamW: lr=0.00001, weight_decay=0.0001, grad_clip_norm=10, betas=[0.9,0.999], eps=1e-8 |
| scheduler | null | ACT preset은 null |
| input/output features | 미지정/빈 객체 | 실제 Dataset metadata의 feature type·shape로 채움 |
| Resume pretrained_path | 원 요청/이전 경로 | 새 출력의 형제 `.resume-input/pretrained_model` |
| Resume checkpoint_path | null/이전 실행 경로 | 위 소유 `.resume-input` root |

실제 공식 Validate/Save와 finite Tiny Checkpoint를 사용한 최초 RED는 **2 failed / 6 passed, 16.56초, exit1**이다. 하나는 전체 UI의 null/default, 다른 하나는 정규화된 정상 parent로 `training_command → freeze_inputs → 공식 Resume Validate → Save`를 진행한 독립 경로다. 두 경우 모두 모델 생성·학습은 없었다.

## 2. 요청·Resolved Config·Checkpoint 계약

기존 `policy.py`에 private 공식 Config 해석 함수를 두었다. 공식 parser/validator를 호출하며 optimizer preset, 모델 architecture, 학습 루프를 직접 구현하지 않는다. 공식 Validator가 argv를 읽는 구간만 소유 config_path로 범위를 제한하고 `finally`로 복원한다. 이미 존재하는 역사적 출력 디렉터리 때문에 재해석이 실패하지 않도록 Validate 중 출력 존재 검사에는 임시 경로를 사용하고 원 output_dir을 반환한다. 실제 train의 새 출력 존재 검사는 기존대로 유지한다.

학습 실행 전 **실제로 freeze한 입력 JSON**과 Resume의 기존 CLI overrides를 해석한다. Resume는 새 요청의 임의 설정으로 Trainer를 바꾸지 않고 소유 Checkpoint의 Config를 로딩한다. 미지정 features는 공식 `dataset_to_policy_features` 결과를 사용해 동일한 feature 분류로 채운다. 명시된 Policy feature 검사는 유지하며, 이 준비에 모델 생성자·Optimizer update는 필요하지 않다.

기존 `config`에는 요청 JSON을 그대로 보존하고, training-intent와 version1 Checkpoint record에 **선택 필드 `resolved_config`**를 추가한다. record schema_version·공식 디렉터리·파일명은 그대로다. 기존 Reader는 `config`를 계속 읽으며, resolved_config 없는 정상 v1 record도 실제 fixture로 읽고 Resume했다. 원 Checkpoint를 마이그레이션하거나 다시 쓰지 않았다.

Sealing의 비교 원칙:

- 실제 저장 Config는 parser로 기본 필드만 확장한다. **저장값에 Validate/preset을 다시 적용하지 않는다.** 실제로 바뀐 optimizer를 원래 preset으로 덮어 검사를 통과시키는 경로를 막는다.
- 제품 train 경로는 실행 전에 확정한 Resolved Config와 저장 결과를 엄격하게 비교한다. Architecture·feature·Dataset·Optimizer·학습 설정을 광범위하게 제외하지 않는다.
- 요청 자체를 공식 기본값으로 해석한 결과와 실제 frozen Config의 Resolved 결과도 비교한다. 이 결합을 실행 전과 Sealing에서 검사하므로 별도 resolved_config를 전달해 다른 Architecture/Dataset/steps 요청을 숨길 수 없다. 원 record의 요청만 바뀌었지만 hash에 묶인 공식 Config는 그대로인 경우도 Child를 시작하지 않는다.
- 기존 직접 Sealing 호출은 공식 정규화 결과와 Dataset feature 기본 채움, 또는 기존의 동일한 부분 Config를 비교한다. 부분 Config 호환도 optimizer/scheduler가 공식 해석과 같아야 한다. **raw null optimizer를 저장된 preset이라고 승인하지 않는다.**
- 명시한 optimizer/scheduler가 저장값과 다르면 계속 거부한다. 필수 Policy/processor/optimizer/RNG 파일, scheduler가 있으면 scheduler state, 모든 safetensors의 형식·유한값, 파일별 SHA·경로 폐쇄성을 유지한다.
- Step은 양의 정수이며 누적 steps 이하이어야 한다. Reader는 record Step과 SHA로 묶인 공식 training_step.json의 일치를 확인한다. resolved Dataset root와 봉인하는 Dataset identity도 일치해야 한다.

Resume는 공식 기본값 표현의 차이를 해석한 후 이전 요청·Resolved 의미를 비교한다. 누적 steps 증가, 새 output_dir, resume와 **이미 소유권이 확인된 pretrained 경로의 이동**만 허용한다. Policy Architecture·학습률/optimizer·scheduler·seed·batch·Dataset 의미 변경은 거부한다. DatasetIdentity, 기존 Checkpoint SHA/완결성, SmolVLA의 기존 compatibility identity 검사는 보존한다. 임의 다른 모델 가중치를 Resume 입력으로 통과시키지 않는다.

## 3. BUG-007 원인과 실제 원본 계보

기존 `NativeRun → resume_to → data.lerobot._origin → materialize/merge/curation → evaluate`를 조사했다. `evaluate`는 `source_episode_uid` 교집합만 확인했다. 현재 Native UID는 `(현재 Native Dataset ID, Episode ID)`에 묶이므로 Resume로 Dataset ID가 바뀌면 같은 inherited Episode도 UID가 달라진다.

| 계보 항목 | 실제 의미 / 보존 범위 |
|---|---|
| source_episode_uid | 저장된 Origin UID. 공식 재물질화/선택에서는 보존되지만 Native Resume의 새 Dataset ID와 전역 creator identity를 혼동할 수 없음 |
| source_native_alias | Native 파일의 device/inode·HDF5 key·Episode metadata에서 기존 코드가 계산. Hardlink에서 보존, 별도 파일 복사 시 변경 가능 |
| source_dataset_id / original_episode_id | Export나 현재 selection의 이름 대신 기존 Origin의 Dataset/Episode |
| source_parent_dataset_id | Native Resume parent. 빈 문자열은 명시된 root이고, 필드 누락과 다름 |
| Trim/Selection | 원 Episode의 UID/Alias를 보존하고 source_start/stop만 선택 범위를 나타냄. 서로 다른 Frame 범위도 독립 Episode로 승격하지 않음 |
| source/task ancestry | 같은 Task·source pool을 참고했다는 사실만으로 동일 기록 Episode라고 판정하지 않음 |

실제 합성 Native Source2개 Episode에 attempt/history를 기록하고 `resume_to`를 실행했다. Hardlink 원본/Resume는 inode가 같고, Export UID는 다르며 Alias는 같았다. 독립 복사 Resume는 inode/Alias가 달라도 parent가 원 Native Dataset을 가리키고 원 배열이 동일했다. `lineage-red-observed.json`에 실제 UID·Alias·Parent·inode·선택 범위를 저장했다.

최초 BUG-007 RED는 **6 failed / 3 passed, 7.00초, exit1**이었다. Hardlink/독립 복사 Resume, Trim·재물질화한 inherited Episode, 부분 Legacy 계보가 잘못 통과했다. 동일 원본의 별도 Export는 기존 UID 검사도 차단했고, 실제 독립 NativeRun과 다른 Episode는 정상 통과했다.

## 4. 공통 Lineage 판정

기존 `data/lerobot.py`의 `_origin`을 계속 사용한다. 기존 UID/Alias 생성식이나 Native Writer/Resume를 바꾸지 않는다. Export/Parquet·Provenance를 새 계보로 재작성하지 않는다.

같은 모듈의 작은 `episode_overlap` 함수가 다음을 반환한다.

| 판정 | 조건 | Offline Validation |
|---|---|---|
| 양수 overlap | 저장된 Origin UID 또는 Native Alias 중 하나라도 같음 | **DATA_LEAKAGE**, 첫 infer/predict 전 거부 |
| 0 | 모든 Origin의 필요한 식별자·engine·명시 parent 계보가 있고, 알려진 key 교집합과 Resume-family 모호성이 없음 | 기존 숫자 평가 허용, lineage_status=verified |
| None | 누락/불확실한 Origin, 또는 서로 다른 같은-domain Dataset 사이의 Resume-family creator 불확실성 | 알려진 Workbench contract이면 **DATA_LEAKAGE**로 거부. 외부 수치 비교는 실행할 수 있어도 unverified_external_provenance |

Resume-family 판정은 기존 Merge의 보수적 규칙을 추출해 **Merge와 Validation이 같이 사용**한다. Native Resume는 각 inherited Episode의 영구 creator를 따로 저장하지 않으므로, 다른 같은-domain Dataset들에 parent가 있으면 복사본의 독립성을 추측하지 않는다. 서로 충돌하는 parent 기록도 불확실성으로 처리한다. 기존 Merge/Curation의 UID·Alias·split 보호는 유지한다.

실제 독립 두 NativeRun은 Episode 이름·수치 배열이 같아도 허용한다. 한 canonical Resume Run 안에서 inherited Episode와 **Resume 후 실제 새로 쓴 Episode**의 서로 다른 저장 selection도 허용한다. 반대로 여러 Resume branch의 creator가 불명확하면 독립이라고 표시하지 않고 canonical Dataset과 저장 selection을 사용하도록 안내한다. 새 Creator ID를 발명하거나 폴더 이름·데이터 경로·배열 동등성만으로 계보를 결정하지 않는다.

## 5. Producer → Consumer와 실제 실행 경계

신규 Checkpoint 시험은 실제 UI backend의 전체 ACT JSON, 공식 `TrainPipelineConfig` Parse/Validate/Save, 공식 Training State 저장기, 제품 `training_command/freeze_inputs/seal_checkpoint/checkpoint_record`를 사용한다. 작은 safetensors는 구조 검사용이다. 공식 Trainer 전체 최적화·학습된 정책의 로딩/품질까지 실행했다는 뜻은 아니다.

### 별도 실제 CPU Trainer Smoke

기존 공식 ACT가 지원하는 `observation.environment_state` 입력을 설치 소스로 확인했다. 영상 없이 state/ENV-state/action 각6개, 합성2 Episode·8 Frame, **8,686 Parameter**의 ACT를 사용했다. 공식 UI Config를 줄여 dim_model16/dim_feedforward32/head2/encoder1/decoder1/VAE layer1/latent4/chunk2/action_steps2, batch1, CPU, worker0, seed17로 제한했다. 각 실행에는90초 취소 deadline을 두었다.

| 실제 실행 | Update/누적 Step | 공식 Child exit | 제품 train 경계 시간 | 결과 |
|---|---|---:|---:|---|
| Scratch | 1 / 1 | 0 | 9.049s | 실제 forward/backward/optimizer·공식 저장·Sealing 성공 |
| Resume, 새 출력 | 추가1 / 2 | 0 | 9.147s | 실제 로컬 weights/optimizer/RNG 복원·새 저장·Sealing 성공 |

실제 optimizer는 공식 AdamW preset이며 Resume pretrained_path는 새 `.resume-input/pretrained_model`이었다. Step1 원 Checkpoint 전체 파일 SHA를 전후 대조했고 같았다. GPU는 `CUDA_VISIBLE_DEVICES=''`로 차단했으며 모델 다운로드·영상 학습·사용자 데이터는 사용하지 않았다. 이는 이 작은 수치 ACT 조건에서의 학습/저장 계약 검증이며 일반 영상 모델 수렴이나 GPU 학습 성공을 뜻하지 않는다.

최초 Harness가 반환값의 존재하지 않는 `StageResult.outputs`를 읽어 수집 오류를 냈다. 이때 공식 Scratch는 이미 exit0/Step1 봉인 성공이었다. 올바른 `output_refs`로 수집기를 고쳐 **Scratch를 반복하지 않고 Resume 1 update만** 이어갔다. 오류 로그와 `summary.json`을 보존하고, 최종 성공은 `actual-cpu-trainer/verified-summary.json`과 두 `training-result.json`에 기록했다. 이후 요청/Resolved 결합 보완 뒤에는 실제 두 Checkpoint의 복사본으로 최종 Sealing만 재확인했다(`final-code-artifact-recheck.json`); 추가 학습0회, 원 파일 변경0이다.

Lineage 시험은 실제 Native HDF5·attempt/history·Hardlink/복사 Resume·Curation/Trim·공식 LeRobot materialize/rematerialize를 사용했다. `evaluate`의 Policy 로딩과 infer/predict만 test double이고 실제 Dataset catalog/DataLoader·계보 판정은 제품 코드다. 작은 수치 결과는 Mock 추론 결과이며 정책 정확도가 아니다. 불필요한 PreparedRun pinning은 기본 seam에서만 대체했고, 추가 통합은 **실제 Sealer의 record → 실제 Recipe prepare/verify → evaluate**를 통과시켰다.

검사한 긍정/부정 범위:

- UI 전체 null/default 정규화, 정상 Scratch/Fine-tune/Resume·새 출력, 기존 v1 record.
- 실제 Architecture/Optimizer/Dataset/steps 변경, seed/batch/다른 pretrained 경로의 Resume 거부.
- Step 범위·record/공식 파일 불일치, SHA 손상·불완전 파일·다른 Dataset identity 거부.
- 같은 원본 별도 Export, UID가 다르지만 Alias가 같은 Hardlink Resume, Alias까지 바뀐 복사 Resume, 동일 계보의 파일 복사, Trim·공식 재물질화, 중복이 섞인 Validation의 첫 batch 전 차단.
- 진짜 독립 기록·다른 Episode·canonical Resume 후 새 Episode 허용, 부분 Legacy의 불확실성 유지.

기존 `test_official_training.py`의 두 Fake Child 사례는 정규화 전 raw JSON을 그대로 저장해 공식 Trainer와 달랐다. 실제 Validate를 출력 생성 전에 수행하고 공식 Save·기존 fixture의 실제 Policy features를 쓰도록 fixture만 고쳤다. 완료/Nonfinite·앞서 봉인한 Checkpoint·수정된 editable Config에 대한 기존 assertion은 유지한다. 저장 성공을 위해 제품 검증 기준을 낮추지 않았다. 기존 시험명·검사 삭제, skip/xfail은 없다.

## 6. 검증 결과

| 묶음 | 실제 결과 / Exit | 의미 |
|---|---|---|
| 변경 전 관련 baseline | 44 passed, 38.02s / 0 | 기존 학습·Resume·Checkpoint·Validation·Merge/Curation |
| BUG-006 최초 RED | 2 failed / 6 passed, 16.56s / 1 | 실제 공식 기본값/Resume 경로 |
| BUG-006 첫 구현 검사 | 12 failed / 12 passed, 61.63s / 1 | Tiny state-only fixture에 불필요한 ACT image 검증과 부분 optimizer 비교 오류를 발견·수정 |
| Config 비교 수정 후 | 2 failed / 22 passed, 78.81s / 1 | 기존 Fake Child의 raw 저장 차이 확인 |
| Fake 저장 순서 첫 보완 | 2 failed / 22 passed, 74.67s / 1 | 출력 생성 뒤 Validate하던 fixture 순서 오류 |
| BUG-006 관련 Green | 36 passed, 162.20s / 0 | 신규20개 + 기존16개 |
| raw null 저장 추가 RED→Green | 1 failed, 10.36s / 1 → 2 passed, 26.17s / 0 | null을 preset으로 승인하지 않으며 Legacy 정상 record 호환 유지 |
| BUG-007 RED | 6 failed / 3 passed, 7.00s / 1 | 실제 inherited origin과 Legacy 불확실성 |
| BUG-007 수정 집중 | 44 passed, 15.69s / 0 | 신규 초기9개 + 기존 관련35개 |
| 관련 통합 | 109 passed, 경고2, 228.10s / 0 | 당시 신규35개와 기존 학습/Validation/Merge/Resume |
| Resolved가 다른 요청을 숨기는 추가 RED→Green | 3 failed / 1 passed, 24.14s / 1 → 7 passed, 51.68s / 0 | 요청과 실제 frozen/저장 의미의 직접 결합 |
| Frozen Config 선검사 | 1 passed / 39 deselected, 17.62s / 0 | 의미가 바뀐 요청은 최적화 Child 시작 전 거부 |
| 최종 경계 보완 | 22 passed, 44.10s / 0 | 공식 저장 Fake 회귀 + 최종 Lineage14개, fixture 원본 SHA teardown 포함 |
| 최종 전체 회귀 | **2,024 passed, 경고5, 851.63s / 0** | 기존1,984개 누락0·신규40개 |

서로 겹치는 묶음을 합산하지 않는다. 중간 실패와 최종 성공을 구분하며 원시 xml/log를 보존한다. 기존 1,984개는 Phase 1C의 이전 전체 기준이며 이번 최종 JUnit의 `(classname,name)` Counter와 대조했다. **누락0, 신규40개 = Config/Checkpoint26개 + Lineage14개**다. 기존 시험명 삭제·rename·skip·xfail은 없다.

첫 전체 실행은 추가 요청/Resolved 의미 결합 검사를 반영하기 위해 SIGINT로 중단했다. 당시 **560 passed**, Console223.39s, 실제 exit2/KeyboardInterrupt였고 실패·완료한 전체 실행으로 보고하지 않는다(`release-full.xml`, `release-full.log`, `release-full-result.json`).

최종 소스의 별도 전체 실행은 다음과 같다. 기존 wrapper의 HF/XDG Cache 출력만 이번 `/tmp`로 옮긴 복사본이며 원 실행 파일·환경은 그대로다.

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
  bash /tmp/real2sim-phase1d-20261115-534a7mak/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short \
  --basetemp=/tmp/real2sim-phase1d-20261115-534a7mak/release-full-verified-temp \
  --junitxml=/tmp/real2sim-phase1d-20261115-534a7mak/release-full-verified.xml
```

`release-full-verified.xml/log`는 **2,024 passed / 실패0·오류0·skipped0**, Console851.63s, JUnit851.593s다. `release-full-verified-result.json`의 실제 process exit는0, wrapper wall time854.465s다. 경고5개는 기존 record_property/xunit2 경고1개와 torchvision 영상 API deprecation4개다. 이전 실행을 최종 결과로 대체하거나 중단 실행과 합산하지 않았다.

## 7. 변경 범위와 보존

이번 제품 변경은 기존 파일4개에 한정한다.

- `learning/policy.py`: 공식 Config 해석/Resume 의미 비교, 요청·resolved 분리, Sealing/Step/Dataset 결합.
- `learning/train.py`: 실제 frozen Config로 실행 전 Resolved 확정, intent·모니터/종료 Sealing에 전달.
- `data/lerobot.py`: 기존 Origin의 완전성 판정, 공통 Origin key/Resume-family·overlap 함수. 기존 Merge 규칙 재사용.
- `learning/validate.py`: UID-only 대신 위 계보 판정. 기존 Policy/control/features 검사·단위·로봇 승인 금지는 유지.

기존 시험1개 수정(`test_official_training.py`), 신규 시험2개(`test_checkpoint_config_resolution.py`, `test_validation_episode_lineage.py`), 이 보고서1개다. 사용자 데이터·Native/Checkpoint Writer 형식의 재설계·새 Manager/학습 Framework/외부 의존성은 없다. CLI와 기존 필수 인자는 그대로이며 Sealer의 선택 keyword 하나만 추가했다.

시작 tracked499개·이전 untracked11개의 실제 내용을 백업했다. 최종 대조에서 이번 수정5개 외 tracked494개와 이전 untracked11개 SHA가 같다. Phase 1A~1C의 제품·시험·보고서와 기존 미커밋 변경을 보존했다. 이번 변경은 **기존 제품4개·시험1개 수정 + 시험2개·문서1개 신규 = 8개**, 삭제0이다(`change-inventory.json`).

보호 root는 `workbench_runs/{scenes,object_assets,capture,calibration,runtime,source,dataset,datagen,annotation,evaluation,curation,policy,scripts}`다. 종료 후 **19,612개 파일의 SHA/크기·전체 경로 집합 변경0·누락0·신규0**을 확인했다(`preservation-after.json`). Scene/Input/Calibration/Capture/Candidate/Cache/Asset/Export/Dataset/Policy/Checkpoint를 보존했다. 모델 Cache·SDK·홈 전체의 전수 검증이라고 확대하지 않는다.

변경 Python7개의 bytecode 없는 compile과 최종 전체 실행 시작 시의 SHA 일치를 확인했다. 기존 공개 인자/CLI는 보존했으며 `seal_checkpoint`만 선택 keyword `resolved_config`가 추가됐다. `load_policy/policy_inputs/infer/predict/validate_action`, 기존 `validate_config/freeze_inputs/stop_child`, control_contract/publish/merge 등의 함수 AST도 시작과 같다(`contract-preservation.json`). 공식 SDK8개 소스 SHA는 불변이다. `git diff --check`와 신규 파일 whitespace 검사도 통과했다.

HEAD/브랜치와 Git Index는 시작과 같다. Index diff SHA는 빈 diff의 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`다. Reset/Clean/Checkout/Stash·Commit/Push/Merge·환경 변경은 하지 않았다. 실제 CPU Trainer 잔존 프로세스0도 확인했다(`cpu-trainer-process-cleanup.json`).

## 8. 남은 한계와 다음 검증

- 실제 장시간 GPU 학습·모델 다운로드·사용자 Dataset/Checkpoint·실물 제어·Isaac 렌더는 이번 범위에서 실행하지 않는다. 실제 CPU 수치 Tiny ACT2 updates, 기존 전체 회귀의 작은 CPU Policy Forward, 신규 구조 fixture/Mock 추론을 구분한다.
- 공식 Config 해석은 고정 설치 LeRobot0.4.1에 의존한다. SDK 업그레이드의 Config/feature/Resume 규칙은 별도 검증이 필요하다. SDK 파일을 patch하거나 새 Trainer를 만들지 않았다.
- Schema version1에 resolved_config가 없는 기존 record는 읽을 수 있다. 기존 요청과 저장 Config 자체가 손상됐거나 더 이상 필요한 로컬 Dataset/가중치를 읽을 수 없는 경우를 자동 복구하지 않는다.
- UID/Alias/Parent는 저장 provenance의 의미다. 계보가 없는 임의 외부 복사본의 creator를 배열·이름으로 알아내는 전역 중복 탐지 기능은 추가하지 않았다. 모호한 자료는 verified로 승격하지 않는다.
- 여러 같은-domain Resume Dataset을 비교할 때 creator가 증명되지 않으면 보수적으로 차단한다. 이는 기존 Merge 경계와 일치하며, canonical Run의 저장 selection으로 독립 Episode를 명시할 수 있다.
- 대규모 Dataset/다수 Checkpoint에 대한 성능 benchmark는 하지 않았다. 계보 검사는 metadata를 읽고 비교하며 영상/배열 전체를 유사도 검사하지 않는다.
- BUG-001–005의 이전 수정과 BUG-008–021/RISK-001–002는 변경하지 않는다. 다음 실제 학습 검증은 별도 허용된 범위에서 작은 CPU 실행부터 진행하고 원본 대신 별도 출력만 사용한다.

완료 근거는 `baseline-code.json`, `before/`, `baseline-protected.json`, `impact-analysis.md`, `installed-api-sources.json`, `official-config-probe.json`, `checkpoint-red-agent-final.xml/log`, `checkpoint-final.xml/log`, `lineage-red-agent.xml/log`, `lineage-red-observed.json`, `lineage-green.xml/log`, `release-focused.xml/log`, `resolved-binding-red.xml/log`, `resolved-binding-green.xml/log`, `frozen-preflight-green.xml/log`, `final-boundary.xml/log`, `actual-cpu-trainer/verified-summary.json`, `actual-cpu-trainer/final-code-artifact-recheck.json`, `release-full-verified.xml/log`, `release-full-verified-result.json`, `regression-comparison.json`, `change-inventory.json`, `contract-preservation.json`, `compile-check.json`, `preservation-after.json`, `verification-summary.json`에 있다. 이 보고서의 최종 SHA는 `completion-check.json`에 기록한다.
