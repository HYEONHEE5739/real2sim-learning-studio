# 기존 테스트 실패 정리

2026-11-06. 리뷰 체크포인트 `6c90f776b7e2bd3a0aca19dcad41c016fda76015`에서 `fix/baseline-tests-20261106` 브랜치를 만들었다. 목표는 직전 전체 회귀의 66 failed / 28 errors를 해결하는 것이다. Scene 재제작·실물 연결·설치·학습·Push는 이 작업에 포함하지 않는다.

## 원인과 수정

| 최초 실패 수 | 원인 | 처리 |
|---:|---|---|
| 74 | 과거 시험 Package에서 USD가 삭제돼 Manifest 검증 단계에서 중단 | 보존된 동일 v8 Export에서 크기·SHA가 정확히 같은 누락 파일 9개만 복구. Manifest/Scene identity와 기존 파일은 수정하지 않음 |
| 10 | 삭제된 모델·processor·optimizer/RNG tensor를 과거 checkpoint에서 로드 | `tests/checkpoint_fixture.py`가 공식 LeRobot Policy·processor·상태 저장 API로 임시 fixture 생성. 원 학습 결과는 변경하지 않음 |
| 9 | 폐기한 Source seed·배치 제한, 이전 ACK·UI 문구·평가 category·학습 설정 기대 | 현재 사용자 흐름과 공식 API 책임에 맞춰 시험 변경. 삭제된 `validate_placements`의 두 시험만 제거 |
| 1 | Isaac 설정이 MuJoCo 모듈의 실행 URDF resolver를 import | resolver와 Manifest-owned asset 검사를 `robot/calibration.py`로 이동. MuJoCo·Isaac·Data Curation 호출자 전환, 기존 정의/중복 경로 제거 |

USD 복구 뒤에는 기존 오류에 가려졌던 seed 인자·fixture의 누락된 stage/tasks·현재 모델과 다른 과거 Native SHA도 확인했다. 모델 불일치를 허용하지 않는다. `tests/mujoco_fixture.py`에서 보존된 초기 상태/숫자 target을 입력으로 **현재 MuJoCo를 실제 실행해 새 Source를 기록**하고, 그 Source를 현재 자동 Annotation에 전달한다. 원 HDF5·Metadata·모델 SHA는 재라벨하지 않는다. 과거 Annotation의 다른 compiled model을 거부하는 시험도 추가했다.

임시 Policy는 초기화된 시험용 가중치다. 학습/수렴/Task 성공 근거가 아니며 checkpoint step은 시험용 라벨이다. 모델 forward가 필요한 검증은 공식 Policy를 실제 로드해 수행한다. 임시 파일은 process 종료 시 정리한다. 가중치를 다운로드하거나 Git에 넣지 않는다.

## 시험 자료 복구

삭제된 과거 USD를 다시 정리했을 때는 같은 Revision의 원 bytes가 있는 로컬 Package를 명시한다.

```bash
python3 robot_learning_workbench/tests/restore_scene_fixtures.py \
  --source workbench_runs/scenes/pickplace-colorblock-b7a5592b/exports/scene-v8-native \
  --fixture docs/evidence/e01-v8-collision/runspace/relocated/scene-v8-native \
  --fixture docs/evidence/simulation-engine/runspace/scene
```

복구 도구는 모든 누락 파일의 크기·SHA를 먼저 확인하고, 일치하는 bytes에 한해 hardlink(다른 파일시스템이면 복사)를 만든다. 기존 파일은 덮어쓰지 않고 Manifest를 다시 만들지 않는다. 일치하지 않는 자료나 원본이 없으면 실패한다. 이 과거 회귀는 로컬 보존 자료가 필요한 통합 시험이며 저장소 코드만으로 독립 재생성되는 전체 테스트 모음은 아니다.

## 검증

실행 기록은 Git 제외 `workbench_runs/baseline_cleanup_20261106/`에 보관한다. 최초 94개 시험 목록은 `initial-classification.json`, 원래 RED는 `initial-red.log`와 직전 전체 JUnit에 있다. 엔진/모델 경계 56개, UI/Recipe 계약 46개, 공식 Policy/외부 검증 경계 31개, 실제 MuJoCo workflow·복구 도구 회귀 79개가 각각 통과했다. 이 수치는 서로 겹치는 관련 묶음이며 합산한 고유 시험 수가 아니다.

전체 회귀 명령:

```bash
REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender \
bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests \
  -q --tb=short \
  --junitxml=workbench_runs/baseline_cleanup_20261106/full-suite.xml
```

최종 전체는 **1,441 passed / failed 0 / errors 0 / skipped 0**, 385.71초다. torchvision 영상 API deprecation 경고 4개는 남는다. 이전에는 모델 로딩 실패로 도달하지 못했던 외부 검증 두 시험도 실제 영상 decode까지 실행되어 경고가 표시된다. 패키지 설치/업그레이드로 경고를 숨기지 않았다.

`baseline-comparison.json`에서 기존 실패/오류 **92개가 통과**, 폐기한 배치 제한 시험 **2개 제거**, 미해결 기존 실패 **0**, 예상하지 않은 시험 누락 **0**을 확인했다. 시험 이름 변경 2개는 현재 Real/Sim 통합 Teleop UI와 공식 미등록 Policy 거부로 대응시켰다. 추가한 시험은 fixture 복구 2개와 과거 compiled model 불일치 거부 1개이므로 전체 수는 1,440→1,441이다. skip/xfail하거나 production의 Manifest·모델 일치 검사를 완화하지 않았다.

수정 Python 26개의 bytecode 없는 compile 검사와 `git diff --check`를 통과했다. 원본 Scene/Asset/Capture 등 보존 대상 **2,389개 SHA 변화 0 / 누락 0**이다. 복구한 9개는 삭제됐던 시험용 Package의 누락 파일이며 사용자 원본 Export를 변경하지 않았다. 리뷰 브랜치의 `6c90f776…`와 기존 개발/main 브랜치는 그대로다. 새 fix 브랜치의 미커밋 변경으로 유지하며 Commit/Push/Merge는 수행하지 않았다.
