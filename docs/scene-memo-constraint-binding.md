# Stage 5 Memo 제약 Binding과 부분 Object 입력

2026-11-16. `feat/simfoundry-style-reconstruction`, HEAD `8e02b1ae023a856694a40b947881f76b66410624`의 기존 미커밋 구현 위에서 보완했다.

**실제 저장 사진·Memo의 제약 검증과 7개 Object의 Stage 6/7 입력 전달을 확인했다. 전체 Scene Reconstruction은 PARTIAL이다.** [실제 진단 보고서 A–H](../workbench_runs/diagnostics/scene_memo_constraint_binding_20261116_001/report.md), [실사진·개념도 HTML](../workbench_runs/diagnostics/scene_memo_constraint_binding_20261116_001/index.html), [엄격 검사](../workbench_runs/diagnostics/scene_memo_constraint_binding_20261116_001/strict-validation.json)가 근거다. 진단 폴더는 Git 제외 로컬 자료이며 제품 의존성이 아니다.

기존 `parse_scene_analysis`의 scalar/relation 검사는 대상 명칭이 개별 Object에 고유하게 연결된 literal witness를 요구한다. 실제 응답은 Photo/Reference Layout을 Capture Layout으로 사용했고, 복수 블록·컵의 공통 치수와 작업판 관계를 이 계약으로 표현하지 못했다. 기존 거부 규칙과 원 응답을 보존하면서 `authoring.scene_constraint_schema`와 `validate_scene_constraints`로 명시 집합·관계 타입을 추가했다.

Codex가 자유 Memo의 의미와 그룹 멤버를 선택한다. Python은 Memo/source-plan SHA, 인용문, Object/role/관측·Reference ID, 그룹 개수와 전체 멤버, 숫자·단위 및 관계식만 검증한다. 자연어 Regex Parser는 추가하지 않았다. `semantic_namespaces`는 Photo/Video 프레임·Reference·실제 Capture ID와 Capture Layout·기존 Robot Link 허용 목록을 분리한다. 모델 해석·숫자 인증과 독립 물리 Identity/정확도는 구분한다.

실제 결과:

| 대상 | 적용 | 남은 상태 |
|---|---|---|
| 블록 3개 | 한 번의 공통 24mm 선언 → 세 Object의 XYZ 0.024m | 별도 독립 측정 3건으로 만들지 않음 |
| 컵 2개 | 윗지름 0.070m, 높이 0.063m | 윗지름은 typed shape constraint, Geometry는 `[null,null,0.063]`; 아랫지름·내부 지름·벽 두께 unknown |
| 컵 쌍 | 외곽 간격 0.020m / 중심 거리 0.090m의 수학 일관성 | rim/축/높이 전제는 미검증, Pose 이동 없음 |
| 작업판 | 외곽 0.147×0.151m, 내부 0.143×0.147m, 안쪽 border 0.002m | border를 Z 두께로 사용하지 않음; 축 부호·원점·Robot World 미해결 |
| Robot / Camera | 기존 URDF 재사용 / 6개 외형 부품의 단일 Assembly | 실제 Link/Mount/Optical Calibration·센서 등록 미검증 |

`bind_memo_constraints`는 원 관측을 동결한 뒤 기존 Codex VLM 경로로 수정 요청을 최대 1회 실행한다. 응답과 실패를 저장하며 동일 입력의 저장 응답은 먼저 결정론적으로 재검증한다. 부분 JSON·출처/ID/수치 오류는 성공 Cache가 되지 않는다. Legacy 문법이 FULL이어도 미인증 Memo 치수가 남으면 별도 Binding을 요구하고, 검증 후 Object별 Coverage도 갱신한다. Stage 7에서도 raw 응답/SHA·Binding을 다시 검사하고 보호 실측 충돌·Object 누락/중복·Role/Constraint 소실을 거부한다.

`decomposition.observed_only: true`는 생성 없이 관측 입력만 준비하는 명시 범위다. Robot Mount가 미해결이어도 검증된 블록·컵 등 독립 Object 입력을 만들 수 있다. **정상 Orchestrator는 이 결과를 Stage 5 COMPLETE로 게시하지 않는다.** `OBSERVED_INPUTS_READY`/PARTIAL로 남기고, 전체 분해·Robot/Sensor 등록의 완료 조건을 유지한다. 이번 Stage 6은 관측 Crop만 실제 처리했고 Stage 7은 `modeling_tasks` 생성 직후 `execute_modeling=False`에서 중단했다. 실제 Mesh 생성 성공을 뜻하지 않는다.

이번 온라인 Codex 수정은 **1회**, 기존 `gpt-6.1-sol / max`, 349.644초였다. 최초 새 validator의 유효한 높이 `axis=z` 거부를 RED로 재현하고 고친 뒤 동일 응답을 오프라인 재검증했다. 추가 온라인 요청·DA3/SAM/FLUX/PDA/Blender/CPD 실행은 없다. 최종 **집중 127 passed**, 전체 pytest는 실행하지 않았다. 기존 7개 관측 NPZ/Mask의 SHA가 같고, 원본 사용자 데이터와 이전 진단은 변경하지 않았다. 상세 최종 보존 대조는 진단 보고서를 따른다.

원본 `pickplace_new / auto_001`에는 진단 Cache나 성공 상태를 적용하지 않았다. UI Resume은 Stage 1/2 재사용 증명이 통과하면 Stage 3 새 attempt에서 시작하며, 그대로 실행하면 새 Codex/SAM 호출이 필요하다. 진단 응답을 새 Candidate 소유 attempt에 명시적으로 가져와 동일성 검증하는 작업은 수행하지 않았다. 전체 Scene·실제 센서·물리·Task 정확도는 별도 검증 대상이다.
