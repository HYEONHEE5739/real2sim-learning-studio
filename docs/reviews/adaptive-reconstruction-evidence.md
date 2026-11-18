# 물체별 Geometry 제작과 Visual Evidence Dashboard

2026-11-19. 기준 HEAD `7a47f99`. 검증 대상은 독립 임시 Project였다.

## 실행과 재개

사진과 Scene Memo로 **새로 생성**하면 기존 Stage 3의 의미 분석과 Mask를 재사용한다. 대표 프레임에 해당 분석이 없으면 Stage 5의 기존 식별 요청에서 형상과 치수 근거를 받는다. Python은 출처가 있는 구조화 치수, 형상, 원본 픽셀의 Mask와 유한한 3D 관측을 검사한다. 물체 이름이나 색상으로 제작 방식을 결정하지 않는다.

- 완전한 실측 Box, Sphere, Cylinder는 기본 형상으로 생성한다. 관측 범위가 실측 경계 상자의 대각선을 초과하면 실측값을 보존하고 검토를 요청한다. 이 검사는 한 방향의 모순을 발견할 수 있으며 모든 표면의 일치를 입증하지는 않는다.
- 단순하고 열린 원형 컵은 윗지름·밑지름·높이·벽 두께를 확인해 제작한다. 바닥 두께는 벽 두께와 같다고 추정한 값으로 계획에 남긴다. 손잡이와 불규칙한 표면, 불충분한 치수는 상세 Mesh 경로를 사용한다.
- 기존 자산은 명시된 Manifest와 버전, 파일 SHA, 알려진 치수를 검사한다. 기존 Rig와 센서 조립체의 재사용은 Builder가 관리한다.
- 제거 여부는 제작 방식과 따로 결정한다. 관측이 확보되고 다른 타깃과 Box가 분리된 직접 제작 물체는 제거를 건너뛸 수 있다. 가림·상호 지지 관계가 있거나 대상 관측이 불완전하면 기존 제거 순서를 유지한다. Stage 6은 직접 제작해도 원본 Mask, Crop, 정합용 점을 보존한다. Stage 8은 실제 관측으로 Pose를 구하는 기존 경로를 사용한다.

기존 Candidate에서 정책 식별값이 다르면 새 계산을 시작하기 전에 중단한다. 같은 정책으로 실행한 Candidate는 기존 Stage와 Worker Manifest 검증을 거쳐 재개한다. 중단된 Stage 7의 결정론적 자산은 계획 식별값, 등록 영수증과 자산 SHA를 검사해 다시 연결한다.

## 사용 화면과 기록

기존 **제작 기록 / 결과 이미지 보기**에서 Stage 1–14를 탐색한다. 새 실행의 종료 시 Candidate의 `evidence/index.html`에도 Dashboard를 게시한다. RGB, 추정 Z와 confidence, Mask 레이어, 지지면 좌표계 점군, 물체별 입력·형상·투영, Scene·Collision, 엔진 준비 상태를 확인할 수 있다. 원본에 연결된 Real/Sim Pair와 측정 q가 없는 Stage 14는 비교 결과를 표시할 수 없다. 계산 결과와 별도로 기록한 Worker 시간은 요청부터 반환까지의 경과 시간이다. GPU 커널 시간과 서비스 내부 재시도 횟수는 알 수 없다.

완료된 Artifact를 읽어 독립 디렉터리에 Dashboard만 만들 때는 Builder의 기존 Python 환경에서 다음 명령을 사용한다. 출력은 Candidate 밖의 새 디렉터리여야 한다.

```bash
python -m real2sim_builder.evidence_dashboard "$CANDIDATE" "$NEW_OUTPUT"
```

## 측정 결과

동일 SHA의 합성 사진으로 두 개의 독립 Project를 만들고 한쪽에서만 상세 Mesh 경로를 강제했다. 표에는 실제 Orchestrator 경과 시간을 기록했다. 양쪽 모두 모델 Worker와 외부 모델링 호출에는 대역을 사용했다.

| Stage | 상세 경로 (초) | 직접 제작 (초) |
|---|---:|---:|
| 5 분해 | 0.267 | 0.141 |
| 6 이미지 준비 | 0.129 | 0.074 |
| 7 제작 | 0.123 | 0.132 |
| 8 정합 | 0.116 | 0.096 |

블록 하나에서 DA3 요청은 2→1회, Instance VLM은 3→1회, RGB 편집 Worker는 3→0회(상세 경로의 1회는 Provider 정보 요청), Depth Inpainting은 1→0회, 모델링은 1→0회였다. 양쪽 모두 최초 support와 segments, CPD를 호출했다. 직접 제작 경로에서 이 물체의 계획 0.8ms, 이미지 준비 2.6ms, 자산 생성 약 30ms, 대역을 포함한 Pose 처리 약 26ms를 관측했다. 실제 서비스의 속도·비용 차이는 미측정이다.

- 블록·별도 복잡 물체가 함께 있는 경우와 가림 관계가 선언된 경우를 Stage 13까지 검사했다. 가림 관계에서 블록 제거를 유지했고, 두 경우 모두 상세 제작 요청은 한 번이었다.
- 두 컵의 실제 등록 Collision을 읽어 24mm 정육면체의 꼭짓점이 중간 높이의 내부 공간에 놓이며 벽과 바닥에 충돌 영역이 존재하는지 검사했다.
- 별도 소형 리그로 직접 생성한 24mm 블록을 Export하고 MuJoCo Native Pose의 Side/Wrist 렌더와 Native Physics의 실제 Step을 실행했다.
- 별도 CPU probreg 실행에서 24mm 합성 정육면체의 보이는 세 면, 8개 초기값, 고정 Scale 1을 사용했다. 약 2.00초, 중심 오차 7.24mm, 대칭 Chamfer RMSE 4.73mm였다. 정밀 배치·회전 정확도는 미검증이다.
- Chrome headless에서 14개 Stage, 실제 Mask 가시성 전환과 휠 확대 후 Canvas 픽셀 변화를 확인했다. Dashboard 재생성 전후 임시 Candidate의 파일 목록과 SHA를 대조했다.

제품 변경 위치는 `adaptive_geometry.py`, `authoring.py`, `reconstruction_stages.py`, `automation.py`, `stage_resume.py`, `evidence_dashboard.py`, `ui_reconstruction.py`다. 시험은 `test_adaptive_evidence.py`, `test_stage_pipeline.py`, `test_semantic_stage_handoff.py`, `test_native_reconstruction_execution.py`에 있다. 이 목록은 이번 기능 수정 범위이며 같은 파일의 선행 미커밋 작업도 존재한다.

최종 관련 집중 검사 98개, 실패 0개, 오류 0개, 건너뜀 0개. 실사진 모델 추론, Isaac 전체 실행, 실물 로봇 및 전체 회귀는 이번 검증 범위 밖이다. 사용자 Candidate에는 접근하지 않았다.
