# Data Curation 재생·로봇/물체·품질 검토

2026-11-02. Workspace Pipeline → Data Curation에서 Source, Annotation, DataGen,
LeRobot Dataset을 선택한다. 외부 Dataset과 저장된 Curation Revision도 열 수 있다.
상단 Dataset을 고르면 Episode·영상·분석이 바로 바뀐다. ‘선택 Dataset 열기’와
‘새로고침’ 버튼은 제거했으며 창을 다시 표시할 때 목록을 자동 검색한다.
빠른 연속 선택은 마지막 요청으로 전환하고, 빈 종류/읽기 오류에 이전 데이터가 남지 않게 한다.
포함 여부는 Episode 체크박스로 관리하고 ‘전체 N개 중 M개 포함 · 제외 K · 표시 L’을
항상 표시한다. ‘선택 Episode 제외/포함’ 버튼은 제거했다. 필터는 표시 개수만 바꾼다.
다른 Dataset으로 전환하기 전에 보존할 편집은 Revision으로 저장해야 한다.

## Split 저장과 Dataset Merge

Split이 모두 빈칸이면 포함·구간 편집을 `<이름>_r001.json` 하나로 저장한다.
train/val을 지정하면 같은 원본 폴더의 `<이름>_r001/train.json`, `val.json`으로 각각 저장한다.
예를 들어 포함 10개 중 train 8개·val 2개라면 두 Revision은 각각 8개와 2개만 가진다.
포함 Episode에 빈 Split이 섞이면 모두 지정하도록 안내한다. 비어 있는 역할은 파일을 만들지 않는다.

저장 후 train을 먼저 열고 두 역할의 저장 수를 상태에 알린다. 같은 원본의 Revision 목록에서
val도 따로 고를 수 있다. Annotation/DataGen 입력 선택창에서도 이 두 파일을 독립적으로 선택한다.
자동으로 두 실행을 시작하거나 생성 결과의 역할을 추측하지 않는다.

LeRobot Export는 **현재 열린 Revision 전체**를 변환한다. 내보내기 범위 선택은 제거했다.
학습용 train Revision을 열어 Export하고, val Revision을 열어 별도 Export한다.

Dataset Merge는 현재 편집 대상과 무관하게 여러 공식 LeRobot Dataset 폴더를 체크해서 선택한다.
Workspace 목록과 외부 폴더 추가를 지원하며, 둘 이상 선택한 뒤 새 출력의 상위 폴더를 고른다.
기존 공식 merge와 같은 계약/중복 검사를 사용하고, 완료하면 새 Dataset을 연다. 현재 미저장 편집이 있으면 그 편집을 유지하고 병합 결과 경로만 알린다.
원본을 수정하거나 현재의 Source/Revision을 자동으로 끼워 넣지 않는다.
상세 계약과 검증 범위는 [Split Dataset 문서](curation-split-datasets.md)를 따른다.

## Revision 위치·버전·다시 편집

위쪽 `전체 / Source / Annotation / DataGen / LeRobot Dataset` 목록은 원본을 고른다.
그 아래 Revision 목록은 해당 원본의 `원본 전체`와 저장한 선별본을 고른다.
선별본 이름 옆에는 그 데이터셋의 개수만 표시한다(`8 Episode`).
`Revision 열기`의 시작 폴더는 `workbench_runs/curation/`이다.

```text
workbench_runs/
  source/demo1/                       # 원본
  annotation/annotation1/             # 원본
  datagen/datagen1/                   # 원본
  dataset/lerobot1/                   # 공식 Dataset
  curation/
    source/demo1/기본선별_r001.json
    source/demo1/기본선별_r002.json
    annotation/annotation1/학습용선별_r001.json
    datagen/datagen1/정지구간제거_r001.json
    lerobot/lerobot1/분할_r001.json
```

Revision 저장 시 이름만 입력한다. 기존 Revision을 편집한 경우 이름이 미리 채워진다.
저장 위치와 다음 `r001/r002` 번호는 Backend가 결정하며 기존 JSON을 덮어쓰지 않는다.
Workspace 밖 또는 중첩 경로의 동명 Dataset은 원본 ID에서 만든 짧은 suffix로 구분한다.
목록은 폴더 이름뿐 아니라 원본 Dataset ID를 대조하여 다른 원본의 Revision을 섞지 않는다.

새 JSON은 기존 `curated_native/1` 선택 계약을 사용하며 원본 경로·identity, 포함 Episode의
구간·Split과 이름·버전·생성 시각을 저장한다. 제외한 Episode는 새 데이터셋의 구성에
포함하지 않는다. 이전 Revision ID는 이력 정보이고 새 JSON은 원본을 직접 참조한다.
따라서 r002를 읽기 위해 r001 JSON이 필요하지 않다. 원본 영상·관절 파일은 필요하다.

Revision은 **선별된 하나의 논리 데이터셋**이다. 원본 10개에서 2개를 빼고 저장하면,
그 Revision에는 8개만 표시되고 전체 개수도 8개다. 원본 Episode ID는 유지하므로
번호 사이가 비어 있을 수 있다. 그 8개에서 하나를 더 제외하면 새 Revision은 7개가 된다.
원본에 있던 제외 Episode를 복구하거나 Trim 구간을 다시 늘리려면 `원본 전체`를 열어
새로 선별한다. 현재 Revision 안에서는 그 선택 범위를 넘어 확장하지 않는다.
통계·영상·로봇 경로·LeRobot Export도 같은 선별본을 읽는다. 아직 저장하지 않은 편집은
먼저 Revision으로 저장해야 한다. 원본 목록에는 원본 Dataset만 표시한다.

Annotation의 입력 Dataset 선택창은 Source 원본과 그 Revision을, DataGen은 Annotation
원본과 그 Revision을 선택할 수 있다. `외부 Dataset 폴더`와 `Revision 파일`로 다른 위치의
자료도 고를 수 있다. 선택한 경로는 기존 Recipe의 `inputs.dataset`에 들어간다.
예를 들어 Source 10 → 선별 8 → Annotation 8 → DataGen → 선별 Revision → LeRobot
변환 순서로 사용한다. 저장된 `single_task`도 그대로 계승한다.

**Episode 단위 제외와 Frame Trim은 구분한다.** Annotation/DataGen의 물리 재생은
기록된 초기 상태가 있는 완전한 Episode만 허용한다. 중간부터 자른 Frame 구간은
새 시작점의 물리 상태를 기록하지 않았으므로 기존 `REPLAY_INITIAL_UNAVAILABLE`로
거부한다. Trim된 선별본을 LeRobot 학습 데이터로 변환하는 경로는 지원한다.

`data/revisions.py`는 위치/버전과 편집 문맥을 소유하고 기존 `data/curation.py`가 실제
선택 검증·불변 JSON 게시·재로딩을 담당한다. Qt `revision_picker.py`는 목록 표시만 한다.
기존 Canonical Revision Reader는 선택한 Episode만 반환하는 의미를 유지한다.
기존 파일은 자동으로 이동하지 않는다. 예전 위치의 JSON을 `Revision 열기`로 열어
다시 저장하면 새 관리 경로에 원본을 참조하는 Revision을 만든다.
원본이 바뀌거나 없어진 경우 기존 identity 검사를 유지하며, 목록에는 읽기 오류로 표시한다.

선별 데이터셋 후속 검증: 관련 집중 검사 54개 통과, 입력 선택·Recipe·공식 LeRobot
소비자 검사 4개 통과. 실제 저장된 `filltered_r001.json`을 Qt에서 열어 8개만 표시하고
`전체 8개 중 8개 포함`임을 확인했다. 이 읽기 검사 전후 Revision/원본 run.json SHA는
같다. 합성 데이터의 10→8→7 재선별·원본 payload 불변·Trim/Split 계승과 양 단계의
Revision 입력 선택도 확인했다. 실제 엔진·로봇·학습 실행 검증은 아니다.

최종 전체는 **1,130 passed / 70 failed / 28 errors**다. 직전 전체 결과와 실패/오류 ID
98개가 모두 같으며 신규 실패는 0개다. Workbench wheel의 Python 모듈 114개가 현재
소스 bytes와 일치하고 compile되며 새 선택창을 포함한다. wheel 설치는 하지 않았다.
근거는 `/tmp/revision-subset-focused.xml`, `/tmp/revision-inputs-final.log`,
`/tmp/revision-subset-full.xml`, `/tmp/revision-subset-regression-comparison.json`,
`/tmp/revision-selected-eight.json` 및 `/tmp/revision-selected-eight.png`다.

주의 표시 안정화 후속 검사는 20개 통과했다. 사용자 `new_r001.json`을 실제 Qt에서 열어
`8 Episode`·`확인 필요 0`과 1·2번 경고 해소를 확인했고, Revision/원본 run.json SHA는
불변이다. 수정 전 두 Episode의 EE 정지 비율과 정지 명령 비율은 원본/선별본에서
같았으나, 선별된 8개로 비교 기준을 다시 계산하면서 경고가 추가된 것이 원인이었다.
이제 원본 기준을 유지하되 Trim 수치는 재계산한다. 근거는
`/tmp/revision-quality-focused.xml`, `/tmp/revision-quality-full.xml`,
`/tmp/revision-quality-regression-comparison.json`, `/tmp/revision-quality-eight.png`다.

## Source 작업 문장 계승

새 Source Script의 `execution.single_task`에 실제 작업 문장을 입력한다.

```yaml
execution:
  single_task: "Pick the red cube and place it in cup 1."
  num_episodes: 20
```

위 예시는 execution 일부이며 기존 Scene·장치·출력과 다른 설정은 유지한다.
양 엔진 Source는 문장을 Native execution에 저장한다. Annotation은 원 실행 Metadata를
계승하고, DataGen prepare는 입력 Annotation의 문장을 effective execution으로 가져와
새 Native에도 보존한다. Resume의 기존 semantic identity 검사에 이 값도 포함된다.
문장은 물체·대상 컵·성공 판정 설정을 대신하지 않는다.

Curation에는 문장 입력칸이 없고 저장된 작업 설명만 표시한다. Revision은 원 실행을
참조하므로 문장을 별도로 입력하지 않는다. LeRobot Export·Merge는 각 입력의 문장을
사용하고 공식 task/task_index로 저장한다. 여러 작업의 공식 Dataset을 다시 선별·Merge해도
Episode별 문장을 유지한다. 저장된 문장과 다른 Export override는 거부한다.

과거 Dataset을 수정하거나 문장을 자동 생성하지 않는다. 문장이 없는 기존 데이터는
명시 `execution.task_instruction`이 있는 기존 Convert Recipe로 별도 변환할 수 있다.
과거 Source Script는 새 수집 전에 `single_task`를 명시하고 새 데이터에 기록한다.

## 재생

Side/Wrist는 저장된 해상도의 MP4를 디코딩하며 화면 비율을 유지해 확대한다.
재생 시간은 저장된 timestamp를 따른다. 1×는 기록 시간과 같은 속도이고,
느린 화면에서는 지난 표시 프레임을 건너뛰어 현재 기록 시각을 따라간다.
이는 Dataset 프레임을 삭제하거나 영상을 다시 저장하는 동작이 아니다.
일시정지·슬라이더 이동은 해당 원본 프레임을 정확히 요청한다.

기존의 프레임별 BackendJob/프로세스 생성·영상 재열기 경로를 재생에서 제거했다.
`ui/review_client.py`가 하나의 `ui/review_worker.py` 프로세스를 유지한다.
`data/review.py`는 선택 Episode의 HDF5/공식 Reader와 Camera별 디코더를 유지한다.
표시 요청은 실행 중 하나와 최신 대기 요청 하나만 보유한다.
기존 two-slot RGB mmap을 이용하고, Qt는 받은 RGB를 표시한다.
프레임 표시마다 전체 Dataset을 다시 읽거나 상태 문구를 갱신하지 않는다.
창을 닫으면 이 창의 재생 프로세스와 임시 Preview만 정리한다.

## 로봇·물체 경로

기록된 Scene identity와 실행 URDF SHA가 일치하는 Workspace Export를 찾는다.
Builder의 기존 FK와 원 모델을 사용해 **측정 관절 상태**로 로봇을 표시하고,
물체는 같은 프레임에 저장된 object pose로 움직인다. Physics를 재실행하지 않는다.
표시용 Mesh는 축약하며 원 Scene Mesh·충돌체·Dataset은 바꾸지 않는다.
원 모델이나 단위/좌표 근거가 없는 Dataset은 모델 표시 불가를 안내한다.
EEF/물체 pose가 없는 일반 LeRobot Dataset에 가짜 경로를 만들지 않는다.
3D/XY/XZ/YZ, 드래그 회전, 휠 확대를 사용할 수 있다.

`recording_only`는 **Source Demo · 성공 판정 전**으로 표시한다.
기록 완료를 Task 성공으로 분류하지 않는 기존 저장 의미는 유지한다.

## 확인 필요와 분포

- Episode 목록의 주황색과 ‘확인 필요’ 필터는 검토 힌트다. 자동 제외하거나
  성공/실패·Split을 바꾸지 않는다.
- 기존 Curation 규칙의 EE 정지(<2mm/s), 정지 명령(모든 축 <1°/s), 팔/그리퍼
  명령 가속도 RMS를 기록값으로 계산한다. 비교 가능한 Episode가 5개 이상이면
  중앙값 ±3×spread를 사용한다. spread는 `max(1.4826×MAD, abs(중앙값)×0.1, 1e-6)`이다.
  비교 기준은 원본 Dataset 전체에 고정한다. 다른 Episode를 제외했을 뿐인 경우 남은
  Episode의 경고가 새로 생기거나 사라지지 않는다. 중첩 Revision도 같은 원본 기준을 쓴다.
  Trim하면 해당 구간의 수치를 다시 측정해 같은 기준과 비교하므로 경고가 달라질 수 있다.
  바뀌지 않은 구간은 이미 읽은 원본 수치를 재사용한다. 짧거나 긴 시간, 높은 정지 비율과
  팔 Jitter를 주의 표시하며 누락된 측정은 추정하지 않는다.
- 상세 분석의 **Task objects**는 기록된 작업 대상만 고른다. Source Script의
  `objects.<id>.task_object`로 지정하며, 여러 대상이면 선택창에서 바꾼다. Scene 전체 물체나
  이름에 `cube`가 들어간 물체를 임의로 나열하지 않는다. 초기 위치는 Trim 시작이 아닌
  **원 Episode 첫 기록 위치**다. 물체를 고르고 점을
  클릭하면 해당 Episode가 열린다. 분포는 패널 전체 폭을 쓰며, 멀리 있는 로봇 원점/책상 전체가
  점들의 확대 범위를 축소하지 않는다. 기본 요약은 판정·포함/제외·시간·EE 정지·주의만
  표시한다. RMS 등 상세 수치는 기본 화면에서 제거했으며 주의 계산의 수치 근거는 유지한다.
  LeRobot 변환은 작업 대상의 시작 위치를 Episode metadata에 보존하므로 Native 파일이
  없어도 새 변환본의 초기 분포를 볼 수 있다. 과거 외부 Dataset에 없는 위치는 추정하지 않는다.
  주의는 주황 테두리, 제외는 회색,
  Train/Validation은 각 색으로 보인다. 기록된 Random Workspace 근거가 있으면
  지지면/허용 중심 경계와 로봇 기준 위치도 표시한다.
- 다른 Dataset 배치 비교와 비교 지우기 버튼 및 전용 비교 경로는 제거했다.
  현재 Dataset의 Task objects 선택·초기 위치 분포·점 클릭은 유지한다.
- 관절값 히스토그램과 관절값 Dataset 비교 화면은 제거했다. 관절 움직임은 시간 그래프에서
  확인하며, 물체 초기 위치 분포와 품질 주의 표시는 유지한다.
- 프레임 번호 입력칸과 ‘저장 Frame 검토’ 버튼은 제거했다. 재생바를 움직이면 해당 영상과
  기록을 자동으로 읽는다. Trim은 표의 원본 시작·끝 셀을 클릭해 편집한다. 별도 구간 입력칸은 제거했다.
- 끝 프레임은 포함하지 않는다. 표의 **원본 최대 끝** 열은 Trim을 바꿔도 원본 전체 프레임 수를 유지한다.
  Revision의 편집 가능 구간은 셀 설명에 표시하며, 정수 편집기는 그 구간 안의 시작 < 끝을 유지한다.
- 표의 Split 셀을 클릭하면 빈칸·`train`·`val`을 선택한다. 별도 Split 지정 선택창·버튼은 제거했다.
- Train 비율·Split Seed·배치 미리보기는 한 줄에 있다. 저장된 현재 선택에서 미리보기하면
  표와 점 색을 갱신하고 분석 패널을 열어 물체 분포로 자동 이동한다. 미리보기 결과는 Revision 저장으로 확정한다.
- 원본 attempt JSON 영역은 제거했다. 저장 오류는 상태에, Export/Merge 완료 시 출력 경로를 상태에 표시한다.
  원본의 attempt·진단 Metadata는 변경하지 않는다.
- LeRobot Export는 현재 선택된 독립 Revision의 모든 Episode와 Trim을 사용한다.
- Trim과 Split 편집은 ‘Dataset 구성’, 포함/제외는 Episode 체크박스에서 한다. 변경한 선택은 새
  Revision에 저장한 뒤 Export에 사용한다. 원 HDF5/MP4는 덮어쓰지 않는다.

실제 로컬 `demo-b633eb88-retry6`(10 Episode/3,986 frame)을 읽기 전용으로 열었다.
짧은 시간 주의 2개, 원 Scene 기반 로봇/물체 표시, 1× 영상의 약30 표시 frame/s,
축약 Mesh 보기의 약24 표시 frame/s를 짧은 offscreen Qt 관측에서 확인했다.
전체 하드웨어·모든 Dataset의 FPS 보장은 아니다. 기존 영상에 이미 들어간
초록색 tool0 표시는 원 MP4를 편집하지 않으므로 그대로 보인다.

초기 재생 개편의 관련 회귀는 99개 통과했다. Source 문장 계승·자동 선택/개수 표시 후속
검사는 실제 Qt/Backend 경로 24개 통과, 전체 회귀는 1,112 passed / 70 failed / 28 errors이며,
이전 실행과 비교한 신규 실패/오류 ID는 0개다. 기존 실패를 이번 기능의
성공으로 합산하지 않는다. 빠른 Seek·되감기, 네 Dataset 종류, Trim/Revision,
누락 Camera의 이전 프레임 차단, 창 재열기와 소유 Worker/임시 Preview 정리를
별도 실제 Qt/Backend 경로로 확인했다. JUnit과 화면 확인 자료는 `/tmp/curation-*`에
두었고 대용량 Evidence 폴더를 새로 만들지 않았다.
