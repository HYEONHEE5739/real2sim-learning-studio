# S01 — Scene 패키지 JSON·Revision·파일 무결성 구현

2026-10-25. 상태: **S01 구현·파일 계약 검증 완료**. [SPEC](../SPEC-scene-package.md)의 S01 부분만 구현했다. S02 Transform/보정 적용 관계·Builder Export·UI·엔진 연결은 시작하지 않았다. 기존 v8을 새 형식으로 변환한 실행 패키지가 아니며 기존 Scene/Calibration/데이터/환경을 수정하지 않았다.

## 구현 파일과 책임

| 파일 | 구현 / 필요 이유 |
|---|---|
| [package.py](../scene_contract/src/scene_contract/package.py) | `load_scene`, `verify_files`, S01 범위의 `validate_scene`, 작은 데이터/오류 타입. 모든 구현이 한 소유 모듈에 있고 엔진·Asset parser·SDK를 import하지 않음 |
| [test_scene_package.py](../scene_contract/tests/test_scene_package.py) | 이동·변조·누락·경로·JSON·identity·참조·증거 접근의 실제 임시 파일 시험 |
| [pyproject.toml](../scene_contract/pyproject.toml) | 표준 setuptools 패키징 및 src/ 테스트 검색. Python>=3.11, S01 runtime 의존성 없음. pytest는 test optional dependency |
| [__init__.py](../scene_contract/src/scene_contract/__init__.py) | 일반 Python package의 진입점. 서비스/장치 시작 없음 |

기존 구현에서 재사용한 것은 immutable Manifest/파일 hash의 의미, Calibration source/execution identity와 외부 실행 의존성의 조사 결과다. 기존 Workspace loader나 Builder 구현을 import/복사하지 않았고 새로운 계약에 필요한 코드만 작성했다. 새 Interface·Adapter·Wrapper·ABC·registry·CLI·schema 프레임워크는 추가하지 않았다.

## 공개 함수와 오류

- `load_scene(entry: Path, *, expected: SceneIdentity | None = None) -> ScenePackage`: `scene.json`과 연결된 Metadata/Manifest를 읽고 파일·참조를 검증한다. 정확한 ID/Revision/manifest bytes SHA를 사용하며 최신 Revision 탐색·원본 repo fallback·쓰기·실행은 하지 않는다.
- `verify_files(root: Path, entries: tuple[FileEntry,...]) -> None`: 상대 경로·regular file·중복·크기·스트리밍 SHA-256을 검사한다.
- `validate_scene(scene, calibration) -> None`: **현재는 S01의 root 구조/schema/ID/units 검사**다. frame graph·SE(3)·보정 합성/적용 횟수·엔진 binding의 의미 검증은 S02다. 함수명이나 ScenePackage 반환을 이유로 그 검증이 끝났다고 해석하지 않는다.
- `SceneError`: `code`, `message`, `issues`의 field/reason/source, `effect=not_started`. `SCENE_INVALID`, `SCHEMA_UNSUPPORTED`, `SCENE_REVISION_MISSING`, `SCENE_INTEGRITY_MISMATCH`를 구분하고 원인 예외를 연결한다.

`ScenePackage`는 frozen data이며 scene/calibration의 중첩 dict/list도 읽기 전용 mapping/tuple로 반환한다. 입력 JSON 숫자와 상태를 임의 정규화하거나 보정/승격하지 않는다. 필드 전체를 다시 쓰거나 새로운 실행 기록을 생성하지 않는다.

## 구체화한 파일 계약

기존 설계의 scene.json/calibration.json/manifest.json 책임을 유지했다. **Manifest는 `{schema_version: 1, files: [...]}`**, 각 FileEntry는 `path`, `size_bytes`, `sha256`다. Scene ID/Revision은 scene.json에 한 번만 두며 Manifest가 scene.json을 hash로 고정한다. Manifest 자체는 목록에서 제외하고 Manifest 원문 bytes SHA가 실행 identity다.

실행 파일 참조는 다음 필드를 사용한다. 파일 경로처럼 보이는 모든 문자열을 무조건 참조로 해석하지 않는다.

| 필드 | 의미 |
|---|---|
| `asset_path` | 엔진 entry·Geometry/모델/엔진 binding 등 하나의 패키지 내부 실행 파일 |
| `asset_paths` | baked Calibration 결과 Asset 등 여러 실행 파일 |
| `required_files` | 엔진/로봇이 추가로 소비하는 Finger Collision·contact pad·관련 모델 등의 파일 목록 |
| `parameters_file` | 실행에 필요한 보정 파라미터 원본 파일. inline `parameters`와 하나만 사용 |
| `source_model_sha256`, `execution_model_sha256` | 각각에 해당하는 바이트가 Manifest에 실제 등록되어 있어야 함. 로봇 보정 encoder_mapping/robot_residual에서는 두 값 필수 |
| `input_asset_sha256` | 선언된 경우 대응하는 실행 입력 파일의 Manifest hash 검사. sensor identity로만 식별하는 Camera에 로봇 모델을 강제하지 않음 |

위 파일 참조는 Scene과 Calibration records에서 검사한다. `prim_path`, body/joint 이름·frame/Object ID, opaque 일반 문자열은 파일 경로가 아니다. 선언한 engine ID는 isaac/mujoco이며 engine마다 asset_path entry가 필요하다. mesh는 asset_path가 있어야 한다. scene-only 파일 검토 fixture에는 engine 선언을 비울 수 있지만, 이를 실행 가능한 엔진 지원으로 표시하지 않는다.

파일이 디스크에 있어도 Manifest에 없으면 거부한다. 절대 경로·URI·Windows drive/backslash·비정규 ./ 및 .. 경로·빈 경로·중복·패키지 밖으로 향하는 symlink를 거부한다. 내부 symlink는 대상도 패키지 안의 regular file이어야 한다. 이동성을 위해 내부를 가리켜도 절대 target인 symlink는 거부하고 상대 symlink만 허용한다. cwd나 기존 repo에서 누락 파일을 찾아 대체하지 않는다. JSON duplicate key·NaN/Infinity/overflow 및 잘못된 root/schema/type·알 수 없는 root/Manifest/record 필드도 거부한다. 중첩 물리/Geometry/Frame의 전체 필드 스키마와 수학 검증을 완료했다는 뜻은 아니다.

## Calibration·외부 의존성 보존 범위

S01은 보정 계산을 실행하지 않는다. 원래 프로필과 근거 모델·현재/실행 모델의 바이트 identity를 서로 구분하고 패키지에 등록하도록 검사한다. 모델 hash를 검사했다는 사실이 B03의 limits-only 모델 동등성이나 계수 검증을 대신하지 않는다. `application.mode`는 baked/runtime를 구분하나 중복 적용·의존 graph·순서 검증은 S02다.

기존 P `simulation/mjcf.py:100`은 `assets/SO101/mujoco/finger_convex_parts.json`, `simulation/workspace_scene.py:92`는 `usd_contact_pads.json`과 그 source hash 파일을 소비한다. 이 참조를 새 실행 Metadata의 required_files/asset_path 등으로 선언하면 등록 누락을 감지할 수 있다. 실제 로더를 패키지 상대 경로로 연결하는 코드는 아직 없다.

**USD/MJCF/URDF 또는 Finger Collision JSON 내부에만 있고 Metadata·Manifest 양쪽에서 빠진 의존성까지 자동 발견하지 않는다.** S01에 엔진/Asset parser를 넣지 않는 기존 설계대로, Export에서 공식 parser로 native 참조 closure를 확인·등록하고 엔진 loader/이동 시험으로 검증해야 한다. ASSET-FINGER-01은 계속 OPEN이다.

외부 보존 증거는 calibration.evidence의 ID→{sha256, location}이다. local 파일의 byte hash에 따라 available/mismatch, 없거나 읽을 수 없으면 unavailable, 원격 URI는 네트워크 접근 없이 unchecked를 반환한다. 필수 실행 파일과 달리 증거 접근 상태는 load를 차단하지 않으며 상태를 자동 검증 완료로 바꾸지 않는다. 로컬 증거 hash 읽기는 큰 파일에서 비용이 발생할 수 있고 별도 cache/DB는 만들지 않았다.

## 검증 결과

| 검증 | 실제 결과 / 증거 |
|---|---|
| pytest 전체 신규 suite | **75 passed, 0 skipped**. [JUnit](evidence/s01/unit-tests.xml), [최종 로그](evidence/s01/logs/08-final-suite.log) |
| TDD 작은 단위 | file 검사 25→JSON/load 40→참조/증거 50→필수 Asset 63→추가 경계 74→이동 불가능한 symlink 75. 각 핵심 신규 동작의 RED/GREEN 로그 보존 |
| 실제 의존 바이트 probe | **8개 검사 통과**. 실제 6개 입력의 복사본을 temporary synthetic fixture에만 사용. 이동, Manifest omission 6개, 같은 크기 Finger Collision 변조 차단. [결과](evidence/s01/dependency-probe.json) / [harness](evidence/s01/dependency_probe.py) |
| wheel build·독립 import | 표준 setuptools로 wheel 생성, isolated Python에서 wheel로 직접 import PASS. 엔진·Qt·LeRobot import 0, 기존 환경에 설치하지 않음. [결과](evidence/s01/build.json) |
| 원본·선행 증거 보존 | [전후 대조](evidence/s01/preservation-after.json). 기존 56,100개 stat·선택 14,916개 SHA 및 추가 입력 hash 비교. 전체 corpus/SDK binary의 전수 byte 비교는 아님 |
| 최종 검사 | [verification.json](evidence/s01/verification.json): 테스트/빌드/증거 hash·문서 링크·작업 경계 확인 |

실제 입력은 과거 근거 URDF(3b6764…), v8 기준 URDF(31da65…), v8 보정 URDF, Finger Convex Parts, USD Contact Pads, Follower 프로필이다. 파일/모델 hash를 확인했고 보정 수치나 파일 내용을 바꾸지 않았다. native asset parsing·Scene v8 재현·새 Scene export/변환·엔진 실행은 하지 않았으며 probe의 임시 패키지는 삭제했다. 보관된 wheel은 코드 배포 산출물이지 실행 Scene Export가 아니다.

실행 Python은 `/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python` 3.11.15, pytest 9.1.1이다. pip install·환경 업그레이드·환경 분리는 하지 않았다. 별도 lint/type 도구가 설치·설정되어 있지 않아 실행했다고 보고하지 않는다. 테스트·wheel 내 Python compile·isolated import를 수행했다. [commands.json](evidence/s01/commands.json)에 명령·cwd·산출물 identity를 남겼다.

## SPEC 대응·차이·남은 문제

- **AC01의 S01 부분:** 패키지 이동 후 Scene identity와 JSON Transform 수치 유지, 필수 파일 누락/크기/SHA·같은 크기 변조·패키지 외 경로 차단 완료. Transform 계산, native 전체 참조, 실제 엔진 로딩은 미완료다.
- **AC03의 S01 부분:** 검증 상태와 Calibration/model hash 보존·실행 파일/외부 증거 구분 완료. baked/runtime 중복 적용 및 동등성 계산은 S02에 남으므로 AC03 전체를 완료 처리하지 않는다.
- **AC02:** S02 미착수. 행렬의 유효성·frame graph·Transform resolve를 구현하지 않았다.
- 기존 v8 JSON은 새 schema_version 계약이 아니므로 직접 호환 loader로 읽지 않는다. B00~B03의 조사 의미를 새 계약으로 확인하며 향후 별도 변환한다. 기존 파일 포맷에 새 구조를 맞추거나 원본을 덮어쓰지 않는다.
- S01 file 검사 성공은 실물 Calibration/Task 성공, 장면·물성 검증, 새 데이터/Policy 호환성, Resume 완료를 의미하지 않는다. B01 Isaac DataGen 실패·Evaluation 비결정성, B02 시점/누락, B03 실제 장치/종료 미검증 상태는 그대로다.
- immutable export 계약으로 실행한다. 읽기 후 적대적인 외부 쓰기까지 막는 filesystem snapshot/lock 보장은 제공하지 않는다. 검증한 Metadata bytes와 Manifest의 일치 여부는 확인한다.

기존 계산/동작의 의도적 변경은 없다. 새 Metadata의 파일 참조 문법과 오류는 새 계약이며 실제 engine/Calibration 실행을 바꾸지 않았다. 새 프로젝트는 Git 저장소가 아니므로 commit/저장소 초기화는 하지 않았다. `incremental-implementation` 및 `test-driven-development` 스킬을 적용했으며 **S01만 완료하고 다음 작업은 자동 시작하지 않는다.**
