# Source 랜덤 배치와 Seed 정리

2026-11-02 사용자 요청. Source YAML의 execution.seed를 제거하고 random_xy를 random_workspace처럼 호출별 새 난수로 배치한다.

- Source 입력/기본 UI Script에 Seed 필드가 없다. 기존 Seed 필드는 명시적으로 거부하므로 편집 가능한 Source Script에서 제거한다.
- random_xy/contact_random_xy/random_workspace는 각 호출에서 인자 없는 numpy.random.default_rng()를 생성한다. 외부 RNG 주입은 받지 않는다. 기존 범위·겹침·접촉·정수/유한성 검사는 유지한다.
- 양 엔진의 배치 호출은 Seed를 전달하지 않는다. 고정 배치는 기존 좌표를 유지한다. 저장/폐기 후 Retry의 기존 초기 상태 복원은 유지한다.
- 새 Source와 그 Seed 없는 입력을 재생하는 Annotation의 실행/attempt/Episode에는 쓰지 않는 Seed를 만들지 않는다. 과거 입력에 기록된 Seed는 Annotation의 원본 이력으로 보존할 수 있다. 과거 Dataset의 Seed/초기 상태는 그대로 읽으며 수정하지 않는다.
- DataGen의 Mimic Seed와 Sim Evaluation의 실행 Seed, Curation Split Seed는 유지한다. 배치 Seed로 쓰이지 않도록 분리한다.
- 기존 형식의 새 Run 이어 수집은 원본 의미/코드/배치 정책 검사를 통과해야 하며, 이번 변경을 위해 과거 계약을 재작성하거나 완화하지 않는다.
- 새 Source/Annotation에는 실제 저장된 초기 자세로 재생한다. 새 Seed 없는 Source의 Native Resume를 검증한다.
- Source 스크립트 수정은 현재 소유한 편집용 workbench_runs/scripts 아래 stage: source YAML만 대상이다. 저장 실행 Snapshot, Dataset, Evidence, SDK/Scene은 수정하지 않는다.

검증: pytest RED→GREEN, 양 엔진 Source 계약·배치 seam, Native Reader/Resume, 공식 Dataset 소비자, Qt 기본 Script. 실제 Leader 연결·모터 명령·새 학습은 수행하지 않는다. 검증 산출물은 /tmp를 사용한다.

현재 편집용 Source 스크립트 4개에서 execution.seed 행만 제거했다: `workbench_runs/scripts/source/test.yaml`, `test_source.yaml`, `test_source2.yaml`, `test_source3.yaml`. 문장/물체/저장 위치/시간/Resume 설정은 유지했다. 전후 SHA와 원문 복원용 사본은 `/tmp/source-seed-script-migration.json`에 기록했다.

## 최종 검증

핵심 집중 검사 **167 passed**, Seed 없는 Source/Annotation Native 읽기·Source append·공식 LeRobot 변환과 Qt 기본 Script를 확인했다. 전체 **1,145 passed / 69 failed / 28 errors / skipped 0**. 직전 실패·오류 98개 중 폐기한 Source Seed wrap 검사 1개를 새 Seed 없는 attempt/partition 검사로 교체했으며, 남은 97개는 같은 기존 항목이다. 새 회귀 실패는0개다. 사용하지 않게 된 배치 Seed 파생/검사와 DataGen의 별도 reset Seed 소비 루프도 제거했다. Mimic의 attempt Seed와 수식·기존 하위 uniform sampler의 수치 검증은 유지한다.

근거: `/tmp/source-rng-final-focused.xml`, `/tmp/source-rng-final-full.xml`, `/tmp/source-rng-regression-comparison.json`, `/tmp/source-rng-consumers.log`, `/tmp/source-seed-script-migration.json`. 새 패키지 설치·원본 Dataset/Scene/SDK 변경·실물 장치 연결/Goal/Torque·Git Push/Merge는 수행하지 않았다.
