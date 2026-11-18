# pickplace_new — Scene Memo 연결 감사와 Stage3 보완

2026-11-16. `feat/simfoundry-style-reconstruction`, 기준 HEAD `8e02b1ae023a856694a40b947881f76b66410624`. 실제 Scene 사진5장·Reference6개·저장된 Memo를 기존 Codex/SAM 경로로 검증했다. **Stage3 문제는 해결했으나 전체 의미 연결과 Scene 완성은 PARTIAL**이다.

- [시각 보고서 HTML](../workbench_runs/diagnostics/scene_memo_semantic_audit_20261116_001/index.html)
- [상세 결과·완료 판정](../workbench_runs/diagnostics/scene_memo_semantic_audit_20261116_001/report.md)
- [Stage1–14 Memo/Artifact 흐름](../workbench_runs/diagnostics/scene_memo_semantic_audit_20261116_001/stage-memo-flow.md)
- [원본/Codex/SAM 5장 비교](../workbench_runs/diagnostics/scene_memo_semantic_audit_20261116_001/images/all_frames_comparison.png)
- [Memo 요구사항29개 CSV](../workbench_runs/diagnostics/scene_memo_semantic_audit_20261116_001/memo-coverage.csv)

진단 자료는 사용자 사진을 포함한 로컬 Git 제외 파일이다. 저장소만 내려받으면 존재하지 않을 수 있다. 사용자 이미지·가중치·Runtime 설정을 저장소 문서에 복제하지 않았다.

## 결과와 한계

| 항목 | 실제 판정 |
|---|---|
| Memo 원문·SHA 전달 | PASS |
| 실제 Codex 의미 분석 | PARTIAL:19항목 제안, 치수/배치 엄격 계약 실패 |
| 실제 SAM 연결 | 37개 Frame/Object 마스크 연결, 물리 Identity는 UNIQUE_ESTIMATED/REVIEW |
| Stage3 | PASS:scene9.jpg 선정, 기존0.5 기준 유지 |
| Stage4 | CPU 입력·좌표 변환 PASS; 독립 Metric QA/Robot World 미검증 |
| Stage5 | 7개 초기 관측 동결 후 MEMO_CONSTRAINT_REVIEW; 전체 분해 PARTIAL |
| Stage6–14 | 계약 집중 회귀만 확인, 이 Scene 실제 실행 NOT_TESTED |
| 실제 전체 Scene/물리/Task | NOT_TESTED |

새 Memo의 컵 높이는 **63mm**다. 이전 자산65mm를 사용하지 않았다. 블록24mm·작업판147×151mm 등 원문은 보존했지만 고유 Object에 대한 수치 근거의 엄격 검증이 실패해 생성 Geometry에 적용하지 않았다.

Stage3은 기존에 모든 평면 위 형상을 물체로 간주해 Robot/폼롤러/주변 장비의 잘림 때문에 모든 프레임을 거부했다. 이제 원래 적격 프레임이 없는 clipping 실패에만 기존 Scene 분석 Schema/CLI와 실제 SAM을 활용하는 preview를 수행한다. 역할이 연결된 context Mask만 제외하고 Unknown과 Target은 남긴다. Target 잘림·Plane·면적·높이 제한을 완화하지 않았다. 마스크 생성과 독립 Object ID 검증은 구별한다.

초기 사진의 모든 Object를 완벽하게 인식해야 Stage3을 시작하는 구조나 Stage5를 선행 조건으로 요구하는 순환은 만들지 않았다. 전체 Memo 계획과 active 분해 관측을 분리하고, 보류 치수·미관측 Fixture/Support가 모델링 단계에서 묵인되지 않도록 Gate를 추가했다. 카메라 작은 부품은 아직 별도 SAM 분할이 아니며 Robot Mask도 전체 팔 형상의 완전한 분리가 아니다.

## 구현 경계

- [reconstruction_stages.py](../real2sim_builder/src/real2sim_builder/reconstruction_stages.py): 공통 Semantic Preview, 원래 clipping/새 scoped clipping 분리, Stage5 관측 재사용·보류 Gate, Stage7 Memo 누락 Gate.
- [authoring.py](../real2sim_builder/src/real2sim_builder/authoring.py): 기존 엄격 파서는 유지하고, Geometry/Layout을 적용하지 않은 시각 관측 projection을 추가했다.
- [stage_workers.py](../real2sim_builder/src/real2sim_builder/stage_workers.py): 기존 SAM raw와 원본 pruning/unique assignment/disentangle 수학을 재사용한 CPU Preview 후처리.
- [automation.py](../real2sim_builder/src/real2sim_builder/automation.py), [stage_artifacts.py](../real2sim_builder/src/real2sim_builder/stage_artifacts.py): Stage3 Memo/Reference/설정 Identity와 고정 baseline의 Stage1/2 호환 검증. 원본 Artifact를 새 코드 실행으로 재작성하지 않는다.

## 검증과 보존

고유 **109개 집중 시험 통과**다. 107개 묶음과 후속59개의 중복을 제거한 수이며 전체 pytest가 아니다. RED/중간 Fixture 실패와 GREEN 기록을 진단 폴더에 보존했다. 변경 Python11개 구문 검사와 `git diff --check`도 통과했다.

실제 Codex application 요청1회, SAM GPU child5개(text23+point fallback10 Adapter Forward), 마지막 분리 보완은 저장 raw Mask의 CPU 재처리만 했다. 신규 DA3/PDA/FLUX/Blender/Isaac/실물 실행0회다. 기존 DA3 Mixed 경로와 원래 수치·Scene 분석 파서는 유지했다.

보호 파일 **19,706개 SHA/크기 변경0·누락0·신규0**, 기존 Viewer 수정·교재9개·Git Index/HEAD/브랜치 불변을 확인했다. 원본 `pickplace_new/auto_001`의 진행 상태·Cache·완료 Artifact는 수정하지 않았다. 실행은 진단 폴더 안의 독립 owned Project에서만 수행했다. Commit/Push·설치·다운로드는 하지 않았다.

## 다음 UI 실행

원본 Stage1/2는 입력·모델·Runtime·기존 Artifact와 고정 dependency proof가 모두 일치할 때만 재사용 가능하다. 실제 새 SHA 대조는 [재개 검증](../workbench_runs/diagnostics/scene_memo_semantic_audit_20261116_001/tests/resume-compatibility.json)에 있다. 진단의 Semantic/SAM Cache를 원본 Candidate에 몰래 복사하지 않았으므로, 원본에서 새로 시작하면 Stage3 분석/분할 요청이 발생할 수 있다.

바로 전체 재구성 완주를 권하지 않는다. 우선 Overlay의 ID·Mask, 카메라 부품을 하나의 장착 구조로 연결하는 방법, Robot Link, Memo의 공유 실측 결합을 검토해야 한다. 엄격 검증 전에는 Stage5 생성/Stage7 모델링을 차단한다. 추가 사진이 반드시 필요하다고 단정하지 않으며, 현재 불확실성을 성공으로 바꾸지 않는다.
