# SPEC: Scene 패키지 계약

ID: `scene-package`. 작성: 2026-10-25. 상태: **S01·S02 구현·오프라인 검증 완료, Export/엔진 검증 미착수**. [승인된 범위](CAPABILITY-MAP.md) / [개발 계획](tasks/plan.md).

2026-10-25 진행: [S01](docs/s01-scene-package.md)의 파일 계약과 [S02](docs/s02-frames-calibration.md)의 Frame Graph·SE(3)·Calibration 관계를 구현했다. 실제 엔진 로딩/전체 실행 동등성은 아직 검증하지 않았다.

## 목표와 범위

Builder Export와 Workbench가 같은 Scene·Transform·Revision·Calibration 의미를 읽도록 한다. 계산·엔진 객체·장치 연결을 계약 패키지에 넣지 않는다.

기존 [아키텍처](docs/architecture.md)의 파일 책임을 유지한다. 이 명세 ID를 이름으로 하는 새 런타임 패키지·계층을 만들지 않는다. [공통 명세 규칙](docs/spec-conventions.md)을 이 명세의 일부로 적용한다.

## 기존 코드 재사용과 새 구현

P/B 실제 루트는 [이관 근거](docs/migration-validation.md#1-원본과-조사-근거)에 정의되어 있다. 아래는 기존 조사에 근거한 이관 대상으로, 이번에 실행 검증한 목록이 아니다.

| 기존 근거 | 재사용할 의미 / 제외 | 새 구현 책임 |
|---|---|---|
| 기존 v8 profile/task/physics/manifest, Builder exporters/package.py export_package/verify_package | 값의 출처·참조 그래프·검증 의미 재사용; 기존 JSON 구조 복제 금지 | package.py: 새 JSON 계약·무결성·참조/Revision 검사 |
| P real2sim/workspaces/builder.py 및 precision.py | 보정 결과 identity·합성 순서 근거만 사용 | transforms.py: 공유 SE(3) 계산; 보정 전체를 공통 패키지로 옮기지 않음 |

구현 파일 범위: `package.py, transforms.py`. 경로는 scene_contract의 기존 설계 src 아래이며 task_modules.yaml 등 설정은 설계된 프로젝트 루트에 둔다. 모든 파일을 한 작업에서 만들지 않는다. 테스트는 `scene_contract/tests/`에 둔다.

## 하위 기능 선행조건과 병행 범위

- 단순 JSON/ID/경로 검사는 다른 모듈 없이 구현·시험 가능하다.
- 보정 필드 확정·v8 변환은 CAL-01/CAL-02의 해당 자료 의미 확인 및 Baseline이 선행한다.
- 외부 Finger Collision·보정 robot asset을 포함한 의존 파일 목록을 확보한다. 92/264개 해시 대조 기록은 closure 완료 증거가 아니다.

확인 상태는 [구현 전 확인 목록](docs/preimplementation-checks.md)에서 관리한다. 해당 항목의 **구현 선행 의미 확인**과 **구현 후 회귀 통과**를 분리한다. 관련 Baseline이 없는 v8 실행 의미는 새 코드로 먼저 추정하지 않는다.

## 입력·출력·실패·상태 계약

- Finger Collision 실행 참조는 package files와 manifest.json에 등록된 필수 내부 파일이다. 기존 repo 절대 경로를 암묵 fallback으로 쓰지 않는다. 엔진별 실제 loader와 이동 후 로딩 증거는 builder/simulation-workflows와 연결하며 파일 hash 확인만으로 scene-package-AC01의 실행 호환성까지 완료로 간주하지 않는다.

- `load_scene(entry, expected)`는 ScenePackage를 반환하며 expected ID/Revision/manifest hash 불일치 시 실패한다.
- 패키지 내부 상대 경로·중복 ID·단위·frame cycle·필수 파일·calibration 적용 횟수를 검사한다. Asset 파서 의존성을 작은 공통 패키지에 넣지 않고 엔진별 참조 closure는 Export에서 확인한다.
- Transform 방향은 T_target_from_source; dynamic current pose를 reference pose로 대체하지 않는다.
- manifest 자기 hash는 제외하고 manifest bytes를 실행 기록에 고정한다. 외부 증거 부재는 접근 상태이며 실행 필수 자료 완전성과 별개다.

구체 타입·호출은 [Interface](docs/interfaces.md), 저장 필드는 [데이터 계약](docs/data-contracts.md)을 따른다. 같은 오류/Schema를 이 문서에 별도 버전으로 정의하지 않는다. 외부 입력 경계에서 검증하고 정상 Task 실패를 예외/구현 실패로 바꾸지 않는다.

## 검증과 완료 기준

- **scene-package-AC01**: 이동한 패키지에서 같은 identity와 Transform; 필수 파일 하나의 변조/누락은 시작 전 오류.
- **scene-package-AC02**: 비영점 부모 회전·왕복·단위 경계 입력의 기존 계산 결과 일치.
- **scene-package-AC03**: Calibration baked/runtime 중복 적용 거부; v8 READY/UNVALIDATED 상태 유지.

검증은 순수 계산/파일 계약 → 실제 엔진 또는 공식 도구 통합 → 해당 UI/장치 사용 흐름으로 나눈다. 엔진별 물리 반복 변동을 먼저 측정하고 tolerance를 근거 없이 늘리지 않는다. 승인된 four_anchors 제외·Recipe UI 변경과 미승인 회귀를 구분한다.

산출 증거: 원본 코드/환경 identity, fixture hash, 실행 명령, expected/actual, 수치·시점 차이, 정상 실패/구현 오류 분류, 미검증 범위. 각 AC와 시험 결과를 연결한다. 미실행·skip·장치 부재는 PASS가 아니다.

## 환경·명령·스타일

S01/S02의 실제 검증 명령은 기존 환경을 변경하지 않고 아래와 같이 실행했다. `pyproject.toml`의 pythonpath=src를 사용하므로 editable 설치가 필요 없다. test_scene_package.py와 test_transforms.py를 포함한다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python -B -m pytest scene_contract/tests -q -p no:cacheprovider
```

S02는 S01 위에 reference Frame Graph/SE(3), joint/frame/model identity·dependency/phase/order/중복 적용·v8 정확한 fit binding 검증을 연결했다. 전체 138개 pytest와 실제 v8 수치 35개/Calibration 패키지 9개 검사가 통과했다. AC02 순수 계산과 AC03의 선언/상태/중복 차단을 확인했으며 **load_scene 성공을 엔진 실행 검증으로 취급하지 않는다**. 실제 보정 실행기/센서/Export 적용 횟수는 후속 구현에서 검증한다.

기술 스택·의존성 고정 및 Build/CLI 명령 확정 절차는 [공통 명세 규칙](docs/spec-conventions.md)을 따른다. 아래는 **테스트 파일 및 환경 구축 후 사용할 목표 명령**이며 현재 실행하지 않았다. 실제 scene_contract 의존성을 설치한 Python을 사용한다.

```bash
python3 -m pytest scene_contract/tests/test_scene_package.py scene_contract/tests/test_transforms.py -q
```

한 Python 환경에 Isaac·MuJoCo·Qt·LeRobot을 모두 강제 설치하지 않는다. 엔진별 테스트 파일은 해당 환경에서 나누어 실행한다. 장치 시험은 일반 pytest에 자동 포함하지 않고 별도 명시 실행으로 분리한다. 테스트 파일 분할은 실제 fixture/환경에 맞추되 AC 추적은 유지한다.

## 작업 경계와 남은 확인

- 항상: 기존 원본 불변, Baseline/확인 ID 추적, 공식 API 우선, 입력 의미·실패/중지 보존.
- 논의 필요: 조사 결과가 확정 요구와 충돌하거나 계산/데이터 의미 변경이 필요한 경우. 통상적인 함수 배치·시험 작성은 반복 승인 대상이 아니다.
- 금지: MiniVLA 이관, 상태/threshold 임의 완화, 미완료 자료 성공 처리, 기능 구분을 이유로 새 추상 계층 추가.
- 현재 한계: S01/S02의 오프라인 회귀는 완료했으나 native Export/실제 엔진·장치/실물 검증은 미완료다. 관련 확인 목록에 근거 없는 값이나 완료 상태를 채우지 않는다.
