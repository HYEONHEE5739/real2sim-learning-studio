# 선택형 작업 물체와 Curation 분포

2026-11-02. `workflow-restoration`에서 구현했다. Source Script가 선택형 물체의 생성 목록을
결정하고, `task_object`는 Data Curation의 분석 대상을 결정한다. UI의 긴 품질 설명과
작은 분포 화면을 전체 폭 분포·간단한 Episode 요약으로 교체했다.

## Script와 Builder

```yaml
objects:
  cube_red:
    task_object: false
    placement:
      function: placement.random_workspace
      params: {frame: object_marker, support: table, workspace: marker}
  cube_blue:
    task_object: true
    placement:
      function: placement.random_workspace
      params: {frame: object_marker, support: table, workspace: marker}
```

이것은 기존 Recipe의 `objects` 부분이다. 빨강·파랑은 생성하고, 초록은 생성하지 않는다.
Curation은 파랑의 분포를 보여준다. 여러 `true` 대상이면 `Task objects`에서 고른다.
한 항목이라도 flag를 명시하면 `true`만 대상이며, 미지정 항목은 false다. flag가 전혀 없는
기존 Source Script는 선언 물체를 대상으로 기록한다. DataGen에 flag가 없으면 입력의
작업 대상을 계승한다. `single_task`와 실제 Task 성공 함수는 이 flag와 별개다.

Builder Object의 `spawn`은 `always` 또는 `recipe`다. `set_spawn`과 `add_object.spawn`으로
편집하고 Export의 `scene.json`에 보존한다. 이전 Package는 기존 manipuland role의
선택 의미를 유지하며 새 제작에서는 명시한다. Script/엔진의 작업 물체 목록은 Scene
카탈로그와 구분한다. 선택하지 않은 물체와 그 부속물은 MuJoCo 모델/충돌체 및 Isaac
활성 Prim/물리 Actor에서 빠진다. Annotation과 기록 Source replay는 녹화 당시 구성을
복원한다. 엔진 템플릿의 기본 3개 목록이 다시 들어오지 않게 했다.

Codex가 사용자 메모를 Builder에 반영하는 절차와 CLI 예시는
[SCENE_AUTHORING.md](../real2sim_builder/SCENE_AUTHORING.md#1-b-선택형-작업-물체와-실행-구성),
제작 규칙은 [SCENE_RULES.md](../real2sim_builder/SCENE_RULES.md#1-a-관측-배치와-실행-물체-구성)에 있다.
새 Scene 메모는 실제 편집 가능한 기본 양식으로 시작하며, 기존 메모와 저장한 빈 메모는
보존한다. 빈 칸·안내 문장을 실측값으로 해석하지 않는다.

## Curation

Task 객체의 **원 Episode 첫 기록 위치**를 표시한다. Trim 시작점과 구분하며, 이동에
성공한 물체를 궤적으로 추측하지 않는다. 기본 요약은 판정·포함/제외·시간·EE 정지·주의
항목만 표시한다. Jitter/RMS 계산은 상대 품질 힌트에 필요하므로 Backend에 유지하지만
기본 화면에는 나열하지 않는다. 분포는 전체 폭을 쓰고, 멀리 떨어진 로봇 원점이나 책상
전체 크기가 확대 범위를 줄이지 않는다. 점 클릭·포함/제외·Split은 유지한다. 다른 Dataset 배치 비교·비교 지우기는 후속 UI 정리에서 전용 처리 코드와 함께 제거했다.

작업 대상/시작 위치는 새 LeRobot 변환본의 Episode Metadata에도 저장한다. 영상/학습
feature를 추가하거나 Action을 바꾸지 않는다. 원 Native 파일을 제거한 합성 검사에서도
초기 분포를 읽었다. 기존 외부 Dataset에 없는 위치는 추정하지 않는다.

## 현재 Scene

- Project: `workbench_runs/scenes/pickplace-colorblock-b7a5592b`
- 새 실행 Revision: `exports/scene-v9-task-objects`
- 기반: `scene-v9-auto-fit`
- Manifest SHA: `5ebb8d5c6497f0bb79dca08ecd52a1b0e14d68d3ff377758d722dd28e26f427c`
- 빨강·파랑·초록 블록을 `spawn: recipe`로 명시했다. 기존 형상·배치·카메라·물성은 바꾸지 않았다.
- 새 Revision을 Project 실행 목록에 등록했다. Source가 Project 이름으로 최신 Package를
  해석하는 경로에서 선택되는 것을 확인했다. 과거 Export와 Dataset은 그대로 보존한다.
- Scene 제작/Real·Sim 정합용 원 배치는 보존한다. 작업 Script 실행이 생성 물체를 선택한다.

## 검증과 범위

전체 **1,140 passed / 70 failed / 28 errors / skipped 0**. 직전 전체의 실패/오류 ID 98개와
정확히 같으며 신규 실패는 0개다. 관련 집중 검사 16개는 모두 통과했다. 세 패키지의
wheel을 빌드하고 모듈 source bytes/compile을 검사했으며 설치하지 않았다.

실제 등록된 Scene으로 빨강만·파랑만·빨강+파랑 Recipe를 Prepare하고 실제 MuJoCo 모델과
Isaac USD 소비 경로를 확인했다. 별도 실제 Isaac ManagerBasedEnv에서도 파랑 한 개와
기본 컵 두 개의 Actor, Side/Wrist RGB 640×480을 확인했다. 이 검사는 Scene 로딩·Reset·
렌더이며 Task rollout이나 실물 성공 시험이 아니다. 실제 장치 연결·실물 Goal/Torque·새
학습/대량 DataGen·원격 쓰기는 실행하지 않았다.

과거 auto-fit Package 87개 파일과 원 Current authoring Scene의 SHA는 변경하지 않았다.
새 Candidate/Export는 UNVALIDATED_REVIEW이며 물리 보정 승인으로 승격하지 않는다.
Isaac의 기존 tool0 USD reference/Fabric/렌더 경고는 남아 있다. 다른 모델 구성을 가진
Annotation을 DataGen에 섞는 기존 일치 검사는 유지한다.

근거는 `/tmp/task-objects-focused-final.xml`, `/tmp/task-objects-full-final.xml`,
`/tmp/task-objects-regression-comparison-final.json`, `/tmp/task-scene-consumers.json`,
`/tmp/task-objects-isaac-result.json`, `/tmp/task-objects-distribution.png`,
`/tmp/task-objects-notes.png`와 새 Candidate의 `published.json`이다.
