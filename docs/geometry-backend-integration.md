# 최신 로컬 UI·Support와 Geometry Backend 통합

> 2026-11-10 후속: VLM은 공통 Codex CLI로 전환했고 MASt3R/COLMAP 실행 코드는 제거했다. 현재 설정과 검증 범위는 [Codex VLM 전환](codex-vlm-migration.md)을 따른다. 아래 과거 실행·설치 기록은 당시 상태다.


> 2026-11-08 저장 구조 이전 후 현재 Scene 경로는 `workbench_runs/scenes/auto-version`, `pickplace-colorblock`이며 Cache는 Candidate `.cache`에 있다. 이 문서 아래의 옛 폴더명은 당시 실행 기록이다. 현재 저장/입력 역할·실제 이전 검증은 [저장 구조 이전 기록](storage-migration.md)을 따른다.

> **최신 적용 상태 (2026-11-08):** 통합본을 원래 `/home/hyeonhee/imitation_learnig_project`에 반영했다. 실행 위치는 원래 폴더이며 `./run_workbench_ui.sh`를 사용한다. DA3 제품 Worker/실행 분기를 제거했다. 아래 Worktree/독립 Smoke 절은 최종 적용 이전의 검증 이력이다. 기존 Scene 실제 실행 및 남은 제한은 문서 마지막 절을 따른다.

2026-11-08. 통합 Worktree는 `/home/hyeonhee/real2sim-learning-studio-integration-20261108`, 브랜치는 `feat/mast3r-colmap-integration`, 기준 HEAD는 `9384a09e86196d98f107992d1352aaac1dc3a8b8`이다. 원래 작업 폴더와 Backend Worktree의 파일·브랜치는 변경하지 않았다. Commit/Push/Merge·원래 폴더 교체·장치 연결은 하지 않았다.

## 백업과 통합 기준

저장소 밖 `/home/hyeonhee/real2sim-integration-backups/local-20261108-173502/`에 원래 29개 변경 파일 전체, Backend의 13개 변경 파일, 양쪽 binary Git diff·status·HEAD·SHA·mode Manifest를 보관했다. 복사한 모든 파일의 SHA를 확인했고 백업 디렉터리/파일 권한은 각각 700/600이다. Git에서 제외된 사용자 Dataset/인증 파일을 이 소스 백업에 넣지 않았다.

새 Worktree의 기준 소스에 **최신 로컬 29개 변경을 먼저 복원**했다. 그 위에 겹치지 않는 Backend 6개 파일을 추가하고 공통 파일을 책임별로 수정했다. 자동 Git Merge·Reset·Stash·Rebase는 사용하지 않았다. 별도 로컬 baseline 소스에서도 기존 전체 회귀를 실행했다.

## 충돌 해결과 변경 파일

| 경계 | 통합 내용 |
|---|---|
| `automation.py` | 최신 로그인 오류 분류·호출 예산·Checkpoint/재개·Support 적용 경로를 유지. `_reconstruct`의 Geometry 보고서/Metric 단계만 연결하고 아래 Solver 설정 전달 오류 수정 |
| `ui_reconstruction.py` | 최신 단일 화면이 기준. `runtime_needs`, 생성자의 단계 이름, `update_progress`만 변경. 5개 탭·수동 환경 폼을 가져오지 않음 |
| `inference.py`, `observations.py`, `calibration/registration.py`, 신규 `sfm.py` | 검증된 Backend의 Worker/상대 좌표/기존 metric 소비 계약을 추가. 최신 Support solver와 별도 중복 Solver를 만들지 않음 |
| `authoring.py`, `codex_cli.py`, `scene.py`, `initialization.py`, `editing.py`, `calibration/hybrid.py`, `calibration/joint.py` | 최신 로컬 bytes 그대로 보존. 가이드 원본 `CODEX_SCENE_GUIDE.md`도 동일 SHA 유지 |
| Workbench `session_page.py`, `session_operations.py` 및 기존 Capture 회귀 | 최신 Snapshot 복원·Project 전환 구현을 그대로 계승. `SceneInputs.open_reconstruction`의 기존 버튼 경로 유지 |
| 문서 | 원래 단일 UI·인증·Support 기록을 보존하고 `AUTO_SCENE_FITTING`, `SCENE_AUTHORING`, `SCENE_RULES`, 아키텍처/단일 UI 문서에 새 Backend 계약 연결 |
| 시험 | 최신 `test_reconstruction_ui.py` 유지 및 환경 누락 기대값 갱신. Backend 시험·신규 `test_geometry_ui_integration.py`로 단일 화면/버튼/진행 상태/Solver 진입 검증 |

AST 대조에서 `automation.py`의 다른 함수 11개와 단일 UI의 다른 메서드 26개는 원래 로컬과 같다. 인증 환경·로그인/계정 전환·모델/강도·사용량·실제 exec·Stop/Resume·UI 스타일을 이전 탭 구현으로 바꾸지 않았다. 상세 SHA/AST 결과는 `merge-preservation.json`에 남긴다.

## 통합 중 실제 발견·수정한 문제

1. 최신 로컬 `_reconstruct`는 `_fitting_configuration()`의 반환값을 받지만 `fit_scene(..., fitting)`에 사용할 변수를 정의하지 않았다. 실제 Solver 분기에 들어가면 `NameError`였다. 일반 생성/Pair 두 경우를 RED로 재현한 후 정규화된 `config['fitting']`을 전달했다. Pair의 치수/외관 최적화 차단도 시험했다. 원래 작업 폴더는 수정하지 않았다.
2. 새 Backend의 per-track 잔차 배열이 View/Object마다 모델링 입력에 반복되어 `tasks.json`이 약 17.9MB로 커졌다. 전체 잔차는 원 component 보고서에 유지하고 Depth batch metadata에는 공통 변환·요약만 전달했다. 정합 수학/Depth/유효 픽셀 기준을 바꾸지 않았다. 실제 작업자료는 약 712KB(696KiB)로 줄었다.
3. 기존 단일 UI가 진행 JSON을 YAML parser로 반복 읽어 실제 Smoke에서 표시/출력 처리가 늦어졌다. UI 진행 표시의 세 JSON 파일은 `json.loads`로 읽는다. 실행용 YAML 설정/Schema·Project 저장 구조는 유지한다.
4. 소유 child 종료 시험에서 `/proc` 존재 확인과 읽기 사이에 프로세스가 사라지는 시험 race를 만났다. 사라짐/좀비만 허용하도록 읽기 예외를 처리했다. 실행 중인 child를 통과시키거나 Stop 조건을 완화하지 않았다.

## 실제 버튼 → GPU → 동일 Candidate 재실행

독립 Project에 휴대폰 정적 배치 8장과 저장된 SAM/Geometry 실행 설정을 복사해 **Scene Prepare의 기존 Auto Reconstruction 버튼 → 현재 단일 Dialog → 실제 QProcess/CLI → `automation.reconstruct`**로 실행했다. 수동 환경 폼이나 대체 Runner는 없다.

이 Smoke의 계정/모델 목록은 fixture이며 원격 Codex 호출은 0회다. 실제 CLI에는 `--run-modeling`과 시험용 `--max-modeling-calls 0 --max-review-calls 0`을 함께 전달하여 모델링 인계 지점에서 멈췄다. SAM/MASt3R/COLMAP·Camera 등록·기존 모델링 작업자료 생성은 실제다. 인증 파일을 복사하거나 실제 계정을 전환하지 않았다.

| 결과 | 실제 측정 |
|---|---:|
| Camera 등록 | 8/8 |
| Sparse Point | 2,367 |
| BA 평균 재투영 오차 | 0.717132px |
| Dense/Sparse Sim(3) 지지 | 4,284 / 4,930 |
| MASt3R GPU Worker | 43.08초 |
| CUDA allocated / reserved peak | 3,238 / 4,714MiB |
| 첫 UI/CLI 전체 실행 | 82.01초 |
| 같은 Candidate 재실행 | 15.04초, SAM/MASt3R/COLMAP Worker 로그 mtime 불변 |
| 결과/종료 코드 | `WAITING_FOR_CODEX` / 2, Candidate `integrated` 재개 가능 |

`MASt3R Matching`, `COLMAP Registration / Bundle Adjustment`, `Dense Geometry Alignment`, `Metric Registration`, 관측/모델링 인계 단계가 실제 Project 상태로 전달됐다. 두 번째 실행에서는 완료된 GPU 단계가 다시 실행되지 않았다. 기존 Source Export를 게시하거나 변경하지 않았다.

Metric 등록은 `UNRESOLVED`다. 이 독립 시험에는 실측 anchor·다양한 Wrist q/FK가 없다. 따라서 실제 미터 Scene·새 USDA·정밀 `fit_scene`/Physics/Task 완료라고 보고하지 않는다. Backend의 기존 validation localization 미구현 및 저피복 View 제한도 그대로다. 새 원격 Codex/실제 계정 전환/Isaac Kit 실행은 이번 Smoke에 포함하지 않았고, 관련 기존 경로·SDK 경계는 회귀 및 원 소스 보존으로 확인한다.

추가로 실제 Workbench `Window`를 독립 interactive Workspace에서 열어, Scene Prepare Project 선택 → 입력 8장 표시 → 같은 Auto Reconstruction Dialog 호출도 확인했다. 장치 연결은 없었다.

## 실행 방법

원래 폴더 대신 이 Worktree에서 실행한다. 시험용 Workspace도 분리했다.

```bash
cd /home/hyeonhee/real2sim-learning-studio-integration-20261108
./run_workbench_ui.sh --workspace "$PWD/workbench_runs/backend_integration_20261108/interactive"
```

`Integration photo copy`는 원본을 수정하지 않는 독립 입력 사본이다. 단일 UI는 저장된 Geometry 설정을 읽으며 새 기본값은 `mast3r_colmap`이다. `geometry` 없이 예전 `da3` 구성이 저장된 Project는 DA3 Legacy로 명시 해석한다. 최신 계정 설정과 모델 선택은 기존 Builder 전용 `CODEX_HOME` 정책을 따른다. 실제 사용자는 공식 로그인 절차를 진행하며 이번 시험의 가짜 계정 상태는 제품 설정에 저장하지 않았다.

## 검증·보존 자료

Git 제외 `workbench_runs/backend_integration_20261108/`에 양쪽 입력 Manifest, 초기 RED/수정 GREEN, baseline/전체 JUnit, GPU 결과, UI 스크린샷, 원본 보존 대조를 보관했다. 중간 UI 지연 시험은 최종 GPU 결과와 구분해 보존한다.

| 검증 | 최종 결과 |
|---|---|
| 최신 로컬만 복원한 baseline | **1,565 passed / failed 0 / errors 0 / skipped 0**, 390.34초 |
| 통합 후 세 패키지 전체 | **1,583 passed / failed 0 / errors 0 / skipped 0**, 387.11초 |
| 새 Backend/단일 UI/Solver 연결 | baseline보다 18개 추가. RED 재현 후 GREEN 확인 |
| 경고 | 두 전체 실행 모두 기존 torchvision 경고 4회 |
| Syntax/공백 | 변경 Python 29개 bytecode 없는 compile, `git diff --check` 통과 |
| 원래 작업 폴더 | 29개 변경 파일 bytes/변경 목록/HEAD 동일 |
| 독립 Backend 폴더 | 13개 변경 파일 bytes/변경 목록/HEAD 동일 |
| 사용자 자료 | Scene/Asset/Capture/Export·Source·Calibration 등 **4,616개 SHA 변경·추가·누락 0** |
| 이전 Scene 보존 기준 | 이전 2,800개 SHA와도 변경·누락 0 |
| 설치 환경 | 기존 `sam31`, `da3`, `lerobot`, `lerobot-arena`의 `pip freeze` 동일. 이번 통합에서 설치/업그레이드 없음 |

소스 37개 변경은 최신 로컬 29개를 계승한 결과를 포함한다. 원래 로컬과 비교하면 21개는 bytes 그대로이며, 8개는 책임별 병합했고 8개는 신규 파일이다. 인증/사용량·Guide·Support 수학의 보존은 위 SHA/AST 대조로 확인한다. 원본 사진·q·실측·기존 Export를 새 추정치로 덮어쓰지 않았다.

주요 근거는 `local-baseline.xml`, `integrated-suite.xml`, `pipeline-red.xml/pipeline-green.xml`, `handoff-red.log/handoff-green.xml`, `gpu/result.json`, `interactive-result.json`, `merge-preservation.json`, `preservation-result.json`, `environments-preserved.json`, `final-source-manifest.json`이다. 회귀용 Scene/설정은 독립 복사본이고 Qt interpreter는 기존 환경을 재사용한다. 테스트용 cache 연결은 저장소 변경 목록에서 정리했으며 실행 데이터와 백업은 Commit 대상이 아니다.

통합 코드만 이 별도 Worktree에 준비됐다. 원래 폴더에 적용하는 작업은 수행하지 않았으며 별도 사용자 승인 전까지 진행하지 않는다.

## 원래 프로젝트 최종 적용 및 기존 Scene 실행 (2026-11-08)

이번 후속 요청은 위의 Worktree 분리 제약을 해제하고 원래 프로젝트 적용을 명시 승인했다. 실행 위치는 `/home/hyeonhee/imitation_learnig_project`, 브랜치는 `review/real2sim-multiview-20261106`, HEAD는 `9384a09e86196d98f107992d1352aaac1dc3a8b8` 그대로다. Commit/Push/Merge·장치 구동·환경 설치는 하지 않았다. 새 Worktree/Project/날짜별 실험 폴더도 만들지 않았다.

원래 29개 미커밋 파일을 백업 SHA와 다시 대조한 뒤 통합본 37개 파일을 원래 폴더에 적용했다. 추가 적용 전 사본·Manifest는 기존 외부 백업의 `final-apply-182915/`에 보존한다. 이후 아래 실제 실행 오류를 필요한 소스와 회귀로 수정했다. 원래 29개 구현을 삭제하거나 옛 탭 UI로 되돌리지 않았다. 원래 실행 스크립트 `./run_workbench_ui.sh`를 사용하면 된다.

### 제품 Backend와 지침

- `inference.run_models`는 SAM 종료 후 MASt3R → COLMAP → Dense 정합으로 실행한다. DA3 실행 분기·Worker·probe·기본 선택·UI Runtime 분기를 삭제했다. DA3 환경/가중치/이전 캐시와 과거 검증 기록은 보존한다.
- `sfm.backend`는 이전 `da3` 설정만 있는 경우에도 `mast3r_colmap`을 선택한다. 실제 새 Runtime 경로가 있어야 하며 자동 설치·다운로드·fallback은 없다. 명시 `geometry.backend: da3`는 제거된 Backend로 거부한다.
- 기존 대상 Scene의 `input/reconstruction.yaml`에는 설치된 SAM/MASt3R/COLMAP Runtime을 저장했다. 별도 실행 Launcher나 사용자 필수 입력 폼을 추가하지 않았다. 단일 UI의 로그인·모델·사용량과 원래 Support/Checkpoint/Pair/Export 경로를 유지한다.
- 분리된 Codex용 가이드도 MASt3R/COLMAP 용어로 갱신하고 개정판/SHA 기록을 유지했다. 최초 분석·모델링의 당시 가이드 사본은 덮어쓰지 않는다.

### 실제 기존 입력과 UI 경로

기존 `workbench_runs/scenes/auto-version-ba737533`에 Candidate `auto_mast3r_colmap`을 만들었다. 원본 입력을 재등록하거나 메모를 다시 작성하지 않았다. 기존 Evidence는 Capture Side/Wrist 8장(실제 q 4개)과 휴대폰/카메라 참고 사진 10장이다. 두 저장 배치 `layout_auto_version_ba737533`, `photos_159bdef6114e`를 동일 배치라고 임의 합치지 않았다. 휴대폰 사진은 이번 Capture 정합의 별도 배치 문맥/자산 형상 입력으로 Codex에 전달했다. 이 결과의 SfM 8장 분모는 Capture 배치이며 휴대폰 전체 SfM 성공으로 보고하지 않는다.

실제 Workbench `Window` → Scene Prepare Project 선택 → 저장 사진·메모·Snapshot 표시 → `Auto Reconstruction` 버튼 → 단일 Dialog의 시작/재개 → 실제 QProcess → CLI `reconstruct --run-modeling` 경로를 QTest로 실행했다. Qt platform은 offscreen이며 사람이 데스크톱에서 조작한 UX 시험은 아니다. 실제 CLI는 0.166.0, 기존 Builder 로그인과 저장된 `gpt-6.1-sol`/`low`를 사용했다. 계정 전환·인증 파일 복사·가짜 로그인·모델링 호출 상한 0은 사용하지 않았다. 모델링/검토 상한은 기존 기본값 6/3이다. 정합 설정 예산은 4 iteration/120 evaluation이었다. 이 실행에서는 정합 진입 전 자료 부족으로 종료했다.

실제 원격 호출은 분석 응답 3회(최초 2회는 아래 계약 오류), USDA 모델링 1회다. 검증된 완료 호출은 분석 1회+모델링 1회이며 재개에서 새 호출 없이 결과를 재사용했다. UI의 진단 스크린샷에서는 계정 식별정보를 생략했다. 인증 토큰/파일을 Project·Sandbox 입력에 저장하지 않았다.

### 실제 실행에서 수정한 오류

1. 다른 저장 배치의 참고 사진이 Codex 문맥에서도 빠지던 입력 선택을 수정했다. 원본 `scene_state_id`를 유지하고 `context_only`로 전달한다. SfM 배치를 섞지 않는다.
2. 분석 전에 Capture의 보관 URDF·FK를 Candidate에 가져오도록 기존 `captured_robot` 호출 순서를 수정했다. 원 URDF SHA/Mapping/q는 그대로다.
3. 실제 첫 응답은 대표 이미지와 그 이미지의 Box/Point 관측이 달라 검증에서 거부됐다. 프롬프트에 같은 대표 이미지의 가시 힌트를 요구하도록 명시했으며 검증을 완화하지 않았다.
4. 기존 URDF Object를 Support로 참조한 실제 두 번째 응답을 신규 물체 목록만으로 거부하던 문제를 수정했다. 기존 Object ID도 허용하되 unknown/self 참조 거부는 유지한다.
5. 작업판의 150×150mm XY는 측정이고 두께는 unknown이다. 기존 Metric Plane 초기화에 부분 XY/Workspace 근거도 전달하도록 수정했다. 두께를 채워 넣거나 보호된 원점을 임의로 표면으로 해석하지 않는다.
6. MASt3R 정적 대응 그래프가 Side/Wrist 두 묶음으로 끊기면 모든 결과를 버리던 처리를 수정했다. 연결된 묶음별로 공식 global alignment를 사용하고, 공식 API의 image index도 묶음 안에서 다시 매긴다. 서로 다른 상대 좌표계를 합치거나 고립된 시점에 점군을 발명하지 않는다. 중간 local-index 오류와 수정 이력을 보존했다.
7. 유효 Depth가 없는 Mask에서 왜곡 역투영이 빈 배열을 OpenCV로 보내던 오류를 재현/수정했다. 빈 관측은 빈 ray/pixel 결과이며 임의 Depth 보간은 없다.
8. 모델링 완료 후 Geometry 오류가 발생하면 완료 호출 횟수가 보고서에서 사라지던 재개 오류를 수정했다. 이미 누락된 이번 2회는 실제 성공 Job/응답 SHA에서 복구했고 `resume-counter-repair.json`에 근거를 남겼다. 새 모델링 요청/재제작으로 대체하지 않았다.

### 검증된 산출물과 멈춘 조건

| 항목 | 기존 Scene의 실제 결과 |
|---|---|
| SAM | Capture 8장·9개 물체 Query의 Mask/모호함 기록 |
| MASt3R | 실제 GPU 실행 43.04초, allocated/reserved peak 3,238/3,924MiB |
| COLMAP | 실제 검증/SfM/명시 BA, 등록 **전체 8 View 중 Wrist 3개**; Side 4장 및 나머지 Wrist 1장은 미등록 |
| Sparse / BA | 128점, 평균 재투영 오차 **0.487823px** |
| 대응 | 검증 9 pair, Inlier 2,183 / learned 2,184 |
| Dense/Sparse | 상대 정합 지지 308/309, extent 정규화 RMSE **0.008967**, 상대 좌표이며 미터 아님 |
| 유효 Depth | 등록 3 View에 각각 28,785 / 6,688 / 21,832 pixel; 구멍 보간/숨은 면 생성 없음 |
| 실제 Blender | 블록 3개, 작업판, 컵 2개, 책상, Foam Roller, Wrist Camera Assembly **9개 독립 USDA Asset 등록** |
| 재개 | 같은 Candidate, 분석/USDA 재생성 없이 기존 Asset 9개 재사용. 최종 재개 UI/CLI 81.03초 |
| Metric / Mount | **UNRESOLVED**, metric cloud 0개 |
| 최종 상태 | **NEEDS_MORE_DATA**, Candidate OPEN/재개 가능, 시각/물리 승인 없음 |
| `fit_scene` / 비교 Loss | Metric 관측·Object Pose 미확보로 **진입하지 않음**, Loss 감소를 주장하지 않음 |
| MuJoCo / Isaac | 이 Candidate의 완전한 Scene 렌더·물리 실행 **미검증**. 없는 Pose/Calibration으로 렌더 성공을 만들지 않음 |
| Export | 새 승인 Scene/실행 Package를 게시하지 않음. 과거 Export 불변 |

정확한 차단 조건은 `metric-diagnostic.json`에 있다. 현재 `predict_views`는 자동 Wrist 부착 링크 탐색과 `wrist_from_motion`에 **최소 4개 등록 Wrist Pose**를 요구한다. 원 Capture의 q는 4개지만 COLMAP 등록은 3개라 이 조건을 통과하지 못한다. 작업판 대안에서도 등록된 Wrist 한 장에만 Workspace Mask가 있고 그 영역의 유효 Dense 표면점은 **0개**였다. 다른 등록 Wrist 두 장에서는 Workspace Mask가 검출되지 않았다. 미등록 Side 사진의 Mask나 문맥 전용 다른 배치의 사진으로 이를 대신하지 않았다. 실측 작업판 크기가 없어서 막힌 것이 아니며, 별도 수동 Robot Base 거리 입력을 필수로 추가하지 않았다.

다음 시도에 필요한 것은 같은 정적 물체 배치에서 서로 겹치는 Side/Wrist 시야와 유효 복원으로 연결되는 추가 Wrist 관측이다. 작업판이 충분히 보이는 연결 시점도 필요하다. 이는 이번 자료의 관측 한계이며, 저장된 사진을 삭제/재작성하라는 뜻은 아니다. 상대 Camera 등록, mm 정확도, 최종 Scene, 물리/Task 성공을 구분한다.

### 원본 및 작업 자료 보존

대상 Scene의 작업 전 파일 **100개** 중 기존 RGB/메모/Evidence/Capture/URDF/Mapping/Project 등 **99개 SHA 불변**, 누락 0이다. 변경된 1개는 허용된 실행 상태 `working/state.json`이다. 더 넓은 이전 원본 목록 **4,616개**에서도 변경은 같은 state 1개뿐이며 기존 Scene/Asset/Capture/Export·Dataset 파일은 그대로다. 원래 29개 소스 백업은 SHA 대조 오류 0이다. 새 설정/Candidate/Cache·새 Asset Version과 실행 로그만 추가했다. 전체 사용자 홈/SDK를 전수 hash한 것은 아니다.

실행·실패/재개·JUnit·보존 대조 자료는 모두 해당 Scene의 `scratch/agent/auto_mast3r_colmap/`에 있다. 주요 파일은 `ui-execution-third-result.json`, `ui-resume-result.json`, `ui-final-result.json`, `inference/results.json`, `modeling/results.json`, `reconstruction.json`, `metric-diagnostic.json`, `preservation-final.json`이다. 중간 실패를 최종 정상 재개의 성공으로 덮어쓰지 않았다. 실제 데이터가 부족한 상태를 새 승인 Export나 학습 가능한 최종 Scene으로 보고하지 않는다.

### 최종 회귀

원래 프로젝트에서 `REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender bash docs/evidence/builder/run_tests.sh real2sim_builder/tests scene_contract/tests robot_learning_workbench/tests -q --tb=short --junitxml=<해당 Candidate>/final-suite.xml`을 실행했다. **1,591 passed / failed 0 / errors 0 / skipped 0**, 392.55초, 기존 torchvision 경고 4개다. 이전 통합 1,583개에 실제 실행 오류 회귀 8개를 추가했다. Mock/수치/실제 Blender·MuJoCo 소비 시험이 포함되며, 이를 미완성인 실제 사진 Candidate의 Isaac 렌더·최종 Task 성공으로 해석하지 않는다.

변경 Python **32개**의 bytecode 없는 compile 및 `git diff --check`를 통과했다. 최종 변경 파일은 **40개**(기존 미커밋 포함)이며 `source-final.json`에 파일/SHA를 기록했다. `.gitignore`는 HEAD와 동일하고 실행 자료는 Git 제외 상태다. HEAD/브랜치·기존 백업을 보존했고 Commit/Push/Merge는 수행하지 않았다.
