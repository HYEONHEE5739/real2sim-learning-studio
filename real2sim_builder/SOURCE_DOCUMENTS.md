# 기존 Builder 문서 검토·이관 지도

2026-10-31. 원본 기준 디렉터리: `/home/hyeonhee/soarm_isaaclab/real2sim-builder/`. `docs`의 Markdown 14개를 전체 읽었다. `AGENTS.md` 및 `CODEX_HANDOFF.md`도 확인했다. JSON 3개와 UI PNG 1개는 과거 결과 자료로 읽고 구분했다. 아래는 원문 복제가 아닌 현재 프로젝트용 주제별 정리다. 이전 폴더 없이도 [제작 가이드](SCENE_AUTHORING.md)와 [제작 규칙](SCENE_RULES.md)을 사용할 수 있다.

| 기존 문서 | 가져온 내용 | 그대로 적용하지 않는 내용 |
|---|---|---|
| `AGENTS.md` | 원본/실측 보호, offline 책임, 후보·평가·승격, 실행 범위 구분 | 옛 SO Adapter 및 smoke 실행을 현재 사용자 지시와 무관하게 강제하지 않음 |
| `docs/SCENE_REFINEMENT.md` | 입력 감사, 원인별 반복, per-pose 지표, 종료/인계 기준 | Scene2의 특정 치수/후보/옛 출력 경로 |
| `docs/AGENTIC_TOOLKIT.md` | 편집 API, Blender author/sync, freshness·rollback·provenance | app.cli, 옛 runtime offset, 과거 PASS를 새 검증으로 사용 |
| `docs/INPUTS.md` | 단위/좌표, 영상 split, Metadata·Mask·URDF·Depth·운동 근거 | 샘플 숫자를 실측으로 사용 |
| `docs/MULTIPOSE_CAPTURE.md` | 측정 q 고정, 공유 Camera/FK, scene-state·train/holdout, 원본 hash | 옛 UI/Session 폴더 구조·당시 downstream 미지원 상태를 현재 상태로 단정 |
| `docs/PAIRED_CAPTURE.md` | Real fitting / Runtime baseline / 새 Candidate 렌더의 세 방향 비교 | 과거 Workspace import 경로 |
| `docs/SCAN_INITIALIZATION.md` | GLB 검사·ROI·등록·실측 우선·상대 기하·불확실성 | 예시 scale/좌표·특정 Polycam 결과 |
| `docs/UNKNOWN_CAMERA_CALIBRATION.md` | Bootstrap/변수 그룹·rank·독립 quality·수동 FK 한계 | bootstrap 성공을 물리 Calibration 완료로 해석 |
| `docs/ARCHITECTURE.md` | Canonical 기반 양 exporter, 책임 분리, geometry/physics 경계 | 옛 app 패키지 구조·기존 export 교체 방식 |
| `docs/CONSUMING_SCENES.md` | Portable closure·엔진 좌표·reference/articulation·실행 범위 분리 | 옛 SO Adapter/registry/프로필 선택 절차 |
| `docs/LOCAL_RUN.md` | 기존 설치 활용·Qt/Worker/USD/Blender 환경 격리 | 과거 절대경로/임시 Qt 링크·당시 GPU 제한을 현재 사실로 단정 |
| `docs/VALIDATION.md` | 합성/실제/독립/물리 검증의 구분, 부족한 물체별 근거 | 26 PASS 등 과거 숫자의 재인증 |
| `docs/V2_IMPLEMENTATION_REPORT.md` | Object scope·coverage·paired identity·가설 진단 한계 | 추가 runtime joint offset, 특정 Scene 개선 수치 |
| `docs/GLB_CAMERA_IMPLEMENTATION_REPORT.md` | 부분 Scan 왜곡·등록 부족·카메라/접촉 미검증의 실제 사례 | 합성 PASS와 당시 제약을 현재 전체 구현 성적으로 사용 |
| `docs/REAL2SIM_BUILDER_IMPLEMENTATION_PROMPT.md` | 근거 우선순위·상호작용 기하 우선·canonical·기능 책임 | 역사적 개발 목표를 현재 구현 완료 기능으로 기술 |
| `CODEX_HANDOFF.md` | 장면별 가설의 변경 이력, best/Current/검토 Export 구분 | 과거 base-table 수평 강제·나중에 해제된 제약을 보편 법칙으로 적용 |

부속 자료 `docs/AGENTIC_REGRESSION.json`, `BLENDER_REGRESSION.json`, `so101_validation.json`, `ui_compare.png`는 과거 렌더/회귀와 UNVALIDATED/NEEDS_MORE_DATA 상태의 기록이다. 현재 작업에서 재실행하지 않았고 수치·이미지를 새 성공 증거로 복사하지 않았다.

현재 명령은 `real2sim_builder.cli`, 현재 자료는 `workbench_runs/scenes/<project>`가 기준이다. API/실행 인자는 현재 소스를 우선한다. 기존 문서 사이에서 날짜에 따라 달라진 내용은 최신 이력과 현재 코드를 함께 보고 판단한다. 기존 문서에 링크된 모든 외부 보고서/웹 문서까지 전수 조사했다는 뜻은 아니다.
