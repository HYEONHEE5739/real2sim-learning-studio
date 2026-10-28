# Real2Sim Learning Studio — 소스 중심 Initial 공개

2026-10-28. 사용자가 **Scene v8 자산을 제외한 소스 중심 공개**를 확정했다.
대상은 [HYEONHEE5739/real2sim-learning-studio](https://github.com/HYEONHEE5739/real2sim-learning-studio)의 `main`이다.
이전 자산 라이선스 관문은 해당 자산의 공개를 계속 제한하며, 검토된 소스 공개를 막는 조건으로 적용하지 않는다.

## 공개 대상

기존 **207개 파일·약2.7MiB**의 구조를 유지한다.

- `scene_contract`: 공통 Scene/좌표/Calibration binding 계약·tests·pyproject.
- `real2sim_builder`: Builder 소스·tests·pyproject·사용 문서.
- `robot_learning_workbench`: Source/Annotation/DataGen·Native/Curation·Learning/Evaluation·Qt UI·tests·패키지 설정·task registry.
- SPEC·CAPABILITY-MAP·Architecture/Interface·tasks와 기존 완료 보고서.
- 실행 shell, 실제 검증 설정에서 외부 경로만 치환한 Recipe/Config 예시.
- README·THIRD_PARTY_NOTICES·`.gitignore`와 제외 자산 inventory.

제품 소스·import·세 패키지 상대 경로는 변경하지 않는다. 이번 변경은 README 제목과 소스 공개 방침을 설명하는 공개용 문서4개뿐이다.

## 공개에서 제외하는 것

[자산 목록](scene-asset-inventory.csv)의 v8 Manifest84개·185,944,113B 및 Manifest는 전부 로컬에 남긴다. SO-101 Mesh/STL, 파생 USD, object texture/scan, URDF/Collision·Calibration 및 해당 provenance 원본을 부분적으로 공개하지 않는다. 목록의 파일명·크기·해시는 자산 payload가 아니다.

`docs/evidence/`, `.vscode/`, 로컬 workspace·SDK/Conda/가상환경·cache·build/wheel·HDF5/MP4/Parquet·checkpoint/pretrained weights·Preview/IPC/로그·인증 파일도 제외한다. `.gitignore`뿐 아니라 실제 Index 파일명을 직접 검토한다. JSON/YAML/USD/URDF/STL 확장자를 일괄 차단하는 정책은 사용하지 않는다.

로컬 Scene·Calibration·Dataset·증거·SDK는 삭제/이동/재생성하지 않는다. 기존 기계별 경로와 tests의 외부 fixture 의존성은 그대로 공개하며 README에서 설명한다.

## 소스 라이선스와 NOTICE

Mimic 순수 계산 subset은 파일별 copyright/SPDX, BSD-3-Clause `LICENSE`, Apache-2.0 `LICENSE-mimic`, 수정 범위 `NOTICE.md`와 `UPSTREAM.json`을 유지한다. SmolVLA 호환 코드는 설치0.4.1 Apache 소스의 명시적 변경으로 공개하고 원 copyright·Apache 원문 링크와 변경 내용을 THIRD_PARTY_NOTICES에 기록한다. SDK 전체나 모델 가중치는 번들하지 않는다.

검토된 공개 소스에서 재배포 불가로 판명된 제3자 파일은 발견되지 않았다. 미확인 Scene 자산의 재배포 허가를 소스 공개 허가로부터 추론하지 않는다. 자체 코드의 포괄 MIT/Apache LICENSE도 임의로 선택하지 않는다.

## 최종 검사와 Git 경계

이전 후보 목록·보존 SHA·비밀 패턴 scanner를 재사용하고 변경된 문서와 최종 Index를 확인한다. 대용량 Dataset/자산 전수검사·기존 physics/Training 재실행은 하지 않는다.

- Index 파일 누락/추가, 비밀 패턴·대용량/바이너리·환경/자산 payload 포함 여부 확인.
- README/공개 안내 상대 링크와 예제 syntax, 세 패키지·LICENSE/NOTICE 포함 확인.
- 제품/테스트·기존 로컬 데이터의 이전 보존 결과와 현재 변경분 대조.
- Remote owner/권한·빈 이력 확인 후 Initial Commit을 생성하고 일반 `git push -u origin main` 사용. force/history rewrite는 금지.
- Push 뒤 Remote commit·README·세 패키지를 확인하고 별도 clone에서 source compile·정적 import·CLI 범위를 검사.

검사와 Commit/Push·clone의 정확한 결과 및 최종 SHA는 로컬 전용 `docs/evidence/github-initial-push/`의 최종 보고서와 GitHub `main` 이력에 기록한다. 이전 보류 검사 증거는 `docs/evidence/github-upload/`에 그대로 보존한다.

기존 제품3파일의 whitespace 경고4건은 업로드를 위해 수정하지 않는다. 정적 비밀 패턴 검사는 모든 가능한 비밀의 부재 증명이 아니며 기존 사용자 경로는 README에 설명한 기계별 참조다. 원본 stat/선택 SHA 대조도 전체 SDK binary의 전수 증명으로 확대하지 않는다.

## Clone으로 가능한 범위

소스·아키텍처·tests·설정 검토, Python compile와 의존성이 갖춰진 환경에서 공통 패키지 import·CLI syntax/help를 확인할 수 있다. 기존966 PASS는 원래 환경의 회귀 근거이며 clean-clone 전체 suite 결과가 아니다.

**Scene v8 전체 패키지가 제공되지 않으므로 Clone 직후 완전한 Simulation 실행은 불가능하다.** 별도로 승인된 Scene/Calibration/assets, 고정 SDK, 테스트용 보존 fixture, Dataset/Checkpoint/캐시가 필요한 단계는 이를 공급해야 한다. 새 환경 설치·Physics·Training 성공은 보장하지 않는다. [외부 의존성](external-assets.md), [README](../README.md)를 따른다.
