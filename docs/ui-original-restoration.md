# 기존 UI 원형 복원 — 조사와 이관

2026-10-29. 브랜치 `ui-original-restoration`, 기준 `f5cb9b251dfb5080d09b699ba8ff03cba486a139`. main/기존 hardware branch는 병합하지 않는다. 이번 범위는 표현·조작 흐름과 기존 Recipe/R03 연결이다. 원본 UI·Scene·Dataset·Checkpoint·Calibration·SDK는 불변이며 실물 Goal/Torque를 실행하지 않는다.

## 소스와 기준 화면

원본 SO101의 `real2sim/ui.py:Window`, `precision_ui.py:PrecisionPanel`, `workflow/ui.py:WorkflowPanel`, `workflow/curation_ui.py:CurationDialog`, `workflow/theme.py`, `workflow/view.py`와 Builder `app/ui/window.py`를 조사했다. Qt/PyQt6 설치6.11.0, 같은 offscreen QPA·DPI에서1320×900/1920×1080을 사용한다. 원본은 별도 임시 Workspace에서 실제 Qt Widget을 구성했다. motor/camera device open·구형 worker subprocess는 audit로 금지했다. Widget/스타일은 대체하지 않았으며 막힌 Registry 조회 때문에 모델 선택 목록의 초기 상태는 실행 환경의 정상 목록과 다를 수 있다. 빈 데이터 기준 화면이며 실제 실행 UX를 증명하는 것은 아니다.

| 기존 요소 | 원본 실제 소유 | 현재 대응 / 이관 결정 |
|---|---|---|
| Main4탭 | `real2sim.ui.Window`, Capture / Real-Sim / Workspace / Precision | `ui.app.Window` 상위 탭 복원. Scene/Teleop/Hub 등은 Pipeline 내부에서 접근 |
| Dashboard Header/Nav | `WorkflowPanel`, margins12·spacing16, Nav200px | `ui.app`의 Pipeline shell, 원본 objectName/style·버튼 위치 재사용 |
| 중앙/우측 분할 | `WorkflowPanel`, splitter850/390, 설정 minimum320 | `ui.workflow` Viewer/설정 분리. 저장 Recipe가 유일 실행 입력 |
| Preview/Log | `CameraView`, media splitter500/180 | 원본 CameraView paint/비율과 카드·로그 배치 이관. 기존 R03 latest-frame 소비 |
| 실행/수동 제어 | `WorkflowPanel` actionCard, source save/discard, annotate commands | 기존 prepare/start/cancel/ACK 호출 유지. 지원 stage 버튼만 표시 |
| DataGen 설정 | `WorkflowPanel`, Task/배치/목표/예산 | 기존 Object 표·count 값 연결. 승인 제외 Solver/Strict/Hold/RandomPoseSeed 미복원 |
| Curation | `CurationDialog`, 좌 Episode/우 영상·timeline, 접힌 분석/구성 | `ui.curation`의 기존 Native API를 사용해 표현과 조작 이관. 구형 reader/job 미복원 |
| Training | `WorkflowPanel`, 우 설정·중앙 진행/로그·별도 Loss | `TrainingSettings`·공식 로그 LossChart 재배치. MiniVLA/LR 자체 Trainer 미복원 |
| Capture/RealSim | `real2sim.ui.Window`, 실제2영상/4분할·공유 우설정 | 현재 hardware read/capture/렌더 결과 API만 연결. 팔 명령/자동 Torque 없음 |
| Precision | `PrecisionPanel`, 현재값/기준표/접힌 상세·검토 | 보존 근거/Raw 읽기·Revision만 연결. release/home/실물 Calibration 자동 수집 미복원 |
| Builder | `app.ui.window.Window`, projects280/1000·Inputs/Run/Compare/Result | 기존 독립 Builder UI 유지, Scene 검사는 BackendJob. v8 읽기 전용 |
| Hub | 원본 Workflow 입력·업로드 영역 | 현재 공식 HubSettings/API·명시 승인만 유지. 새 숨은 token/remote 변경 없음 |

원본 old UI의 JSON/구형 Task selector·실행 루프·MiniVLA·motor 동작 버튼은 최신 사용자 계약에 따라 대체/제외한다. 화면 복원은 과거 backend 의미·위험한 명령을 복원할 권한이 아니다. 기능상 차이는 최종 결과에 남긴다.

## 구현 순서

1. 원본 Style·CameraView·Main4탭·Pipeline shell을 복원하고 실제 Qt geometry/상태 보존 시험.
2. Workflow Viewer/설정/고급 Recipe 분리 및 stage별 버튼·Preview/진행/로그·학습 설정 연결.
3. Curation 목록·영상·timeline·Trim/Split/분석/Revision/Export 연결.
4. Capture/RealSim/Precision의 표현·결과·안전 상태 및 Builder/Hub 흐름 확인.
5. 동일 크기 Before/After 비교, 실제 R03/공식 도구 통합·전체 회귀/wheel·두 축 리뷰·원본 보존.

로컬 근거는 `docs/evidence/ui-original-restoration/`. 원본187개 Python SHA와56,100개 파일 stat 및 기준249개 tracked bytes를 작업 전 고정했다. 원본 렌더링과 실제 새 Worker 실행 증거를 구분한다.
