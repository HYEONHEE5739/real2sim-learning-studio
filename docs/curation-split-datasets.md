# Curation: 독립 Split Revision과 Dataset Merge

2026-11-02 사용자 요청. 기존 Curation/Project/Dataset 계약을 재사용하며 새 포맷이나 실행 프레임워크를 만들지 않는다.

## 범위와 순서

| 모듈 | 책임 | 의존 |
|---|---|---|
| split-revisions | 포함/구간 편집을 train/val별 독립 Revision으로 저장 | 기존 save_curation/Reader |
| dataset-merge | 여러 공식 LeRobot Dataset 선택 및 병합 | 기존 discover_datasets/lerobot.merge |

구현 순서: 저장 규칙과 원본 보존 → UI/입력 경로 연결 → 다중 병합 → 회귀.

## 동작 계약

- Split이 모두 빈칸이면 기존처럼 `<name>_r001.json` 한 개에 포함 Episode만 저장한다.
- train/val이 지정되면 `<name>_r001/train.json`, `val.json`에 각각 해당 Episode/Trim만 저장한다. 비어 있는 역할은 파일을 만들지 않는다.
- 포함 Episode에 지정/빈칸이 섞이면 저장 전에 모두 지정하도록 안내한다. 제외 Episode의 역할은 저장 대상을 늘리지 않는다.
- 분할된 두 파일은 같은 버전/원본을 공유하며 각각 직접 열기·재선별·Annotation/DataGen 입력이 가능하다. 이전 Revision 파일은 실행 의존성이 아니다.
- 기존 선택의 범위·원본 identity·역할 중복 검사는 유지한다. 원본 배열/영상/Scene/SDK는 수정하지 않는다.
- 묶음은 숨겨진 staging 디렉터리에서 기존 Writer/Reader로 준비하고 디렉터리 rename으로 함께 게시한다. 실패한 준비물을 정상 목록에 노출하지 않는다.
- Revision 저장 결과는 역할별 경로와 개수를 반환한다. UI는 첫 저장본을 열고 저장된 모든 역할/개수를 알린다. LeRobot Export는 열린 선별본 전체를 변환한다. 범위 선택 UI는 제거한다.
- Dataset Merge는 현재 열린 Native/Revision을 암묵적으로 넣지 않는다. 공식 LeRobot Dataset 폴더를 둘 이상 명시 선택하며, 외부 폴더 추가와 중복 선택 방지를 제공한다.
- 기존 materialize/merge의 제어 의미·영상·중복 원 Episode·분할 충돌 검사를 유지한다. 새 출력만 생성하며 현재 편집이 저장돼 있으면 성공한 병합 Dataset을 다시 열고, 미저장 편집 중이면 해당 선택을 유지하며 결과 경로를 알린다.
- Source 역할이 Annotation/DataGen의 역할 메타데이터로 자동 전파되는 기능이나 학습 UI 자동 분할은 추가하지 않는다. 사용자가 각 독립 Revision을 해당 실행의 입력으로 선택한다.

## 파일과 스타일

저장: `data/revisions.py`; 공통 Writer: `data/curation.py`. UI: `ui/curation.py`, 작은 전용 병합 대화상자. 작업 IPC: `ui/operations.py`. 시험은 기존 `tests/test_curation_revisions.py`, `test_revision_ui.py` 및 병합 시험에 둔다.

```python
saved = save_revision(workspace, source, name, splits={'train': train_ids, 'val': val_ids})
# 반환: {'train': Catalog(...), 'val': Catalog(...)} 또는 {'all': Catalog(...)}
```

## 검증·경계

- RED→GREEN: 각각의 선택/구간·공식 Reader·하위 실행 입력, 부분 지정 거부, 실패 롤백, 동시 저장, 기존 Revision 재열기.
- 실제 offscreen Qt 버튼/다중 선택/저장 결과/Export와 실제 공식 Dataset merge/Reader를 검증한다. 새로운 학습·시뮬레이터·하드웨어는 실행하지 않는다.
- 집중 시험: `bash docs/evidence/builder/run_tests.sh robot_learning_workbench/tests/test_curation_revisions.py robot_learning_workbench/tests/test_revision_ui.py robot_learning_workbench/tests/test_split_revision_datasets.py robot_learning_workbench/tests/test_dataset_merge.py -q --tb=short`
- 전체 회귀: `bash docs/evidence/builder/run_tests.sh scene_contract/tests real2sim_builder/tests robot_learning_workbench/tests -q --tb=short`
- 검증 산출물은 `/tmp`에 둔다. 설치·새 의존성·원본 데이터 변경·Push/Merge는 하지 않는다. 기존 실패 98개와 새 실패를 구분한다.

## 완료 검증

집중 검사 52개 통과. 최종 Merge 4개 검사에는 미저장 편집 보존과 실제 Qt→8/2 저장→공식 Writer 각각 Export→10개 Merge→Reader 재개방을 포함한다. 합성 입력이며 실제 장치·학습·시뮬레이션을 새로 실행하지 않았다.

최종 전체 **1,149 passed / 70 failed / 28 errors / skipped 0**. 직전 전체 회귀의 기존 실패·오류 98개와 항목이 같으며 새 실패는 0개다. 신규 14개 검사와 기존 저장/입력/UI 시험을 현재 계약으로 수정했다. 원본/기존 Revision 보존, 단계별 입력, 부분 지정 거부, 둘째 파일 실패 롤백, 동시 버전 생성, 구형 통합 Revision 재열기/새 버전 분리, 3개 공식 Dataset의 실제 Action exact를 확인했다.

근거: `/tmp/split-datasets-final-focused.xml`, `/tmp/dataset-merge-final.xml`, `/tmp/split-datasets-final-full.xml`, `/tmp/split-datasets-regression-comparison.json`. 별도 도구 설치·Training·Hub 쓰기·Git Push/Merge는 하지 않았다.
