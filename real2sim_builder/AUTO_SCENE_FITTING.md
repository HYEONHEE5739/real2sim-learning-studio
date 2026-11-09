# 자동 Scene Reconstruction

> 2026-11-08 저장 정책: Scene/Model 이미지 역할·사람이 읽는 이름·Asset 순차 버전은 [최신 Codex 지침](CODEX_SCENE_GUIDE.md)의 저장 경로 절을 따른다. 이전 경로 예시는 당시 검증 이력이며, 실제 현재 경로와 이전 결과는 [저장 구조 이전 기록](../docs/storage-migration.md)를 따른다.

2026-11-08 통합: 새 기본 Geometry는 **SAM3.1 → MASt3R → COLMAP SfM/BA → Dense 정합 → 기존 Metric 등록**이다. 최신 단일 UI·인증·Support 구현을 유지한다. DA3 제품 실행 경로는 제거했다. 과거 Cache·모델·환경·검증 이력은 보존한다. [통합 실행 기록](../docs/geometry-backend-integration.md)을 따른다.

## 현재 단일 화면 — 2026-11-07

Scene Prepare에서 입력을 저장하고 Auto Reconstruction에서 **로그인·모델/추론 강도·사용량 확인 → 생성 시작/이어서 실행 → 중단**만 사용한다. 기존 다섯 탭·수동 물체/Mask/USDA/환경 편집 UI는 삭제했다. 저장된 설정과 자료를 자동으로 읽으며 Backend CLI/API·Asset·Capture·비교 이미지·Checkpoint는 유지한다. [현재 사용법과 인증/재개 계약](../docs/auto-reconstruction-ui.md)을 먼저 따른다. 아래 날짜별 UI 설명은 당시 구현 이력이며 현재 화면의 사용 지시가 아니다.

## 단일 자유 메모 → Codex 구조화 해석 — 2026-11-04

사용자는 Scene Prepare의 메모에 자유롭게 설명하고 **Scene 자료 저장**을 누른다. 별도 문법/단어 목록은 없다. 저장 경로는 `<workspace>/scenes/<project>/input/scene_memo.txt`다. 줄바꿈·언어·기호를 보존하며, Qt에서 원문을 수정하지 않고 다시 저장할 때도 원래 줄바꿈을 유지한다. 새 Project와 빈 메모는 빈 입력으로 남긴다.

실측 치수도 이 메모의 일부다. 별도의 치수 표를 채울 필요가 없다. Codex가 원문과 이미지에서 Object/Asset Group, 치수, 역할·지지면 관계, 모델링 지시를 구조화한다. Python은 치수 문장·키워드를 파싱하지 않는다.

Codex 응답의 `geometry`는 null 또는 `kind`, `dimensions_m`(X/Y/Z, 모르는 축은 null), `source`, `evidence_quote`, `evidence`, `wall_m`, `support`를 갖는다. 예를 들어 “컵 높이는 100mm야”는 Codex가 `[null, null, 0.1]`로 반환한다. `user_memo`는 실제 치수를 명시한 원문 인용이 필요하다. 이미지/복원 추정과 원하는 디자인 치수는 `visual_inference`이며 실측으로 승격하지 않는다. 사용자에게 이 JSON을 작성하도록 요구하지 않는다.

검증된 계획은 `objects.<id>.geometry`에 저장한다. `authoring.geometry_specs`가 이를 보존된 Scene/선택적 기존 `measurements` 자료와 대조하고 Geometry·metric Camera 초기화·모델링에 같은 수치 입력을 전달한다. 기존 측정과 충돌하면 새 계획을 저장하지 않는다. 기존 구조화 측정 파일과 provenance는 그대로 보존하며 이 설정은 고급 선택 입력이다. 새 기본 경로는 `measurements`를 별도로 만들지 않는다.

일부 축만 실측이면 Blender 자산의 해당 축만 확인한다. 자산 전체 크기는 estimated, 알려진 축은 `dimensions.constraints`에 원 실측 출처와 함께 남는다. 실측이 전혀 없으면 기존 Robot/Calibration·다중 시점 기하를 사용하며, metric scale까지 관측 불가능하면 scale=1을 발명하지 않고 필요한 근거를 보고한다. 수평 Support 외 자유 공간 관계는 `modeling_notes`로 Codex에게 전달되며 모든 자연어 관계를 수치 최적화 제약으로 자동 변환하는 기능은 아니다.

```python
from real2sim_builder.evidence import scene_memo, save_scene_memo
save_scene_memo(project, "오른쪽 컵 두 개는 같은 제품이고 위치만 달라.\n")
current = scene_memo(project)  # text / sha256 / path / saved
```

기존 CLI 입력도 하나의 현재 메모를 갱신한다. 여러 파일을 주어도 병합 이력을 만들지 않으며 마지막 저장이 현재 내용이다.

```bash
python -m real2sim_builder.cli add PROJECT /path/prompt.txt --kind brief
python -m real2sim_builder.cli reconstruct PROJECT --candidate NAME
python -m real2sim_builder.cli modeling-run PROJECT --candidate NAME
```

새/변경된 메모가 미해석 상태면 `reconstruct`는 **SAM/Geometry 실행 전에** `WAITING_FOR_CODEX_ANALYSIS`와 `modeling/tasks.json`을 만든다. 명시 `modeling-run` 또는 현재 Codex 대화가 원문과 사진을 읽는다. `tasks.json`에는 하나의 `scene_memo.text/sha256`, 등록 사진/선택 Capture 배치·q/시각/Camera metadata, 기존 Object/Group과 보존된 측정 자료가 전달된다. 미등록 참고 사진은 문맥 입력이며 metric View로 승인되지 않는다. 다음 재구성에서 기존 SAM→MASt3R→COLMAP→Blender/Library→정합을 계속한다. Pair 재정합은 기존 Revision geometry 보존 경로를 유지한다.

공식 Codex CLI 응답 Schema는 `authoring.scene_analysis_schema()`가 단일 정의다. 최상위 필드는 `scene_memo_sha256`, `objects`, `asset_groups`, `needs`다. Object는 `id/prompt/role/category/asset_group/material_variant/modeling_notes/observations/geometry`, Group은 `id/members/relation_source/evidence_quote/change_kind/evidence`를 모두 제공한다. 미제공 문자열은 빈 문자열, 미관측 Box는 null이다. 이 계약은 Codex용이며 사용자가 JSON을 작성할 필요는 없다.

`parse_scene_analysis`는 필드·타입·ID 중복·Group 멤버/참조·Image ID/Box·현재 SHA·인용문 존재를 검사한다. 인용문의 **의미**는 Codex가 판단하며, 실제 인용문이 있다고 물리 동일성/정확도가 입증되지는 않는다. 실제 Mask 수/Association·실측 충돌·Manifest/Closure SHA 검사는 별도로 유지한다. `note_relation`, `modeling_change_evidence`와 현재/이력 메모 선택 API는 제거했다.

Candidate의 `modeling/scene_memo_<SHA>.txt`와 `modeling/codex/<job>/answer.json`은 당시 실행의 고정 입력/응답 증거다. 현재 메모 버전 관리 기능이 아니다. 같은 입력 재요청은 SHA를 검증한 응답을 재사용한다. 메모를 바꾸면 새 분석을 요청하고, 무관한 USDA를 자동으로 재모델링하지 않는다. 새 Export는 `scene_memo.txt` 원문·SHA를 Package Manifest/`provenance.json`에 고정한다. 과거 Export는 수정하지 않는다. 이전 구현에서 생성한 열린 작업/검증 보고서는 signature 계약 변경으로 갱신이 필요할 수 있다.

메모·modeling_notes의 경로처럼 생긴 문자열은 파일 접근 요청으로 실행하지 않는다. 등록·SHA 고정된 입력 파일만 복사한다. 기존 Codex/Blender sandbox, 네트워크/하드웨어 경계는 유지한다. 이번 검증의 Codex 응답은 Fake이며 실제 자연어 이해 정확도 검증과 구분한다.

## Workspace 공용 Library·현재 메모·Object 복원 — 2026-11-04

Scene Project는 Input/메모/Capture/q·Camera·Config·Object Pose·Candidate·Export를 소유한다. USDA Geometry/Texture/UV/Collision/Blender 원본은 Workspace 공용 `object_assets/<asset_id>/<version>/`에 둔다. Revision은 같은 Project 안의 결과 이력이며 새 Project가 아니다. Asset ID/Version과 개별 Object ID·Group을 구분한다.

Workbench가 선택한 Workspace의 기존 `<workspace>/scenes/<project>` 구조를 사용한다. `Project.workspace`는 Project pool의 부모이며 사용자 홈 경로를 하드코딩하지 않는다. Builder CLI의 `--projects`도 같은 pool 규칙을 사용한다. 신규 등록/Blender 결과는 공용 Library에 원자적으로 게시하고 Scene에 전체 자산을 복제하지 않는다. 다른 Scene에서 기존 Asset을 쓰려면 Auto Reconstruction 표의 **Workspace** Manifest를 명시 선택한다. 같은 Category나 파일 이름으로 자동 확정하지 않는다.

기존 `Project/input/object_assets/`는 **Legacy** 목록으로 유지한다. 기존 Scene/Revision을 수정하지 않는다. 선택 자산의 **선택 Legacy 자산을 공용 Library에 등록**은 검증한 파일 Closure를 같은 Asset ID/Version으로 공용 저장소에 게시하고, 과거 참조는 그대로 둔다. 이후 필요한 Instance만 공용 Manifest를 선택한다. 원본 또는 기존 공용 버전과 충돌하면 중단한다.

```bash
python -m real2sim_builder.cli object-asset PROJECT list
python -m real2sim_builder.cli object-asset PROJECT register --id paper_cup --path /path/paper_cup.usda
# 실제 VERSION은 list 결과의 64자리 SHA 버전이다.
python -m real2sim_builder.cli object-asset PROJECT instantiate --candidate NAME --object cup_2 \
  --manifest ../../object_assets/paper_cup/VERSION/manifest.json --pose pose.yaml
python -m real2sim_builder.cli object-asset PROJECT publish \
  --manifest input/object_assets/paper_cup/VERSION/manifest.json
```

`../../object_assets/`는 Backend가 인식하는 제한된 Workspace 상대 참조다. 일반 외부 경로나 임의 `..`를 허용하지 않는다. Project 확인·정확한 Asset ID/64자리 Version·Library 내부 파일·Symlink/Traversal·Manifest/종속 SHA를 검사한다. 다른 Workspace/임의 홈 파일을 경로로 지정하지 않는다. 동일 Workspace 등록에는 하나의 process 간 Lock과 staging→rename을 사용한다. 사용 중이면 명확하게 실패하고 기존 버전을 바꾸지 않는다. Scene/Instance 삭제는 Library 삭제가 아니다. 기존 Blender Sandbox는 공용 Library 전체를 읽거나 쓰도록 확장하지 않는다. 검증·등록은 Blender 밖 Backend가 담당한다.

Scene의 Asset 참조에는 정확한 ID/Version, Manifest SHA와 Asset key가 들어간다. Export는 기존 `copy_native_asset`으로 필요한 USDA/Texture/OBJ/Collision/Manifest를 Package 내부에 고정하고 USD/Texture 참조를 재배치한다. Library가 없어도 닫힌 Export를 검증/로딩할 수 있다. 새 Asset Version 등록은 다른 Scene이나 과거 Revision을 갱신하지 않는다. 명시 Project Clone의 다른 Workspace 이동에는 사용 중인 버전만 복사하고 무관한 공용 자산을 복제하지 않는다.

현재 Scene 메모는 Project의 **`input/scene_memo.txt` 하나**다. `evidence.scene_memo(project)`가 원문과 UTF-8 SHA를 읽고, `save_scene_memo(project, text)`가 원자적으로 갱신한다. 같은 내용을 저장하면 파일을 다시 쓰지 않는다. 빈 내용은 그대로 빈 입력이며 UI의 안내 양식은 placeholder일 뿐 Codex 입력이 아니다. 과거 `current_brief` 또는 마지막 `briefs` 파일은 canonical 파일이 없을 때만 읽기 전용으로 복원한다. 과거 파일/Export를 지우거나 새 이력을 추가하지 않으며 `scene_briefs` 배치별 메모 선택은 활성 경로에서 사용하지 않는다.

Codex가 현재 원문을 해석한다. Backend는 자연어 정규표현식 없이 구조·출처를 검사한다. 메모 변경 후 이전 인용문이 여전히 남아 있더라도 과거 응답을 새 SHA로 다시 결합하지 않는다. 새 Codex 해석을 요청하고 영향받는 Group만 검토한다. 명시 Manifest·실측·USDA·과거 Export는 보존한다. 다른 Project 메모를 검색하지 않는다.

Auto Reconstruction은 Current Scene + 실측 + 저장 Config의 Object 합집합을 복원한다. USDA/실측/Mask가 없는 Object도 표시한다. Group/provenance·명시 자산·modeling_action/request ID·Mask 선택·진행 Candidate를 유지하고, 불러오지 못한 자산도 자동 선택으로 되돌리지 않는다. 저장 도중 보이지 않는 Object를 삭제하지 않는다. **선택 물체 삭제**는 Reconstruction Config의 명시 제거이며 공용 자산이나 Current Scene 원본 삭제가 아니다. 역할/보호 실측 충돌은 표시하고 저장을 막는다. Scene의 실제 Geometry 삭제는 기존 Candidate 편집으로 별도 수행한다.

검증·현재 제한과 원본 보존은 [누적 기록](../docs/automated-reconstruction.md)의 Workspace Library 절을 따른다. 실제 AI 호출을 통제 응답으로 대체한 시험과 Blender/OpenUSD/MuJoCo·Qt 실제 실행을 구분한다.

## Asset Group·재사용·Object Sandbox — 2026-11-04 추가 안정화

Object ID는 Scene Instance, Category는 의미적 종류, Asset Group은 공유할 Geometry/외형 관계, Asset ID/Version은 등록된 불변 USDA, Manifest는 실제 자산 파일의 SHA/종속 참조다. 같은 Category나 같은 SAM Prompt만으로 그룹을 합치지 않는다. Codex가 사용자 명시 관계로 분류한 응답은 현재 메모 SHA·인용문 존재·대상 참조를 검사해 **user_declared/CONFIRMED**로 기록한다. 이 상태는 출처 표시이며 Python이 의미나 실제 제품 동일성을 증명했다는 뜻이 아니다. 사진만 보고 추론한 공유 관계는 **estimated/PROPOSED**다. 직접 그룹을 선택한 관계도 user_declared이며 physical_verified로 승격되지 않는다.

```yaml
objects:
  cup_1:
    category: paper_cup
    role: receptacle
    prompt: paper cup
    asset_group: paper_cup_A
  cup_2:
    category: paper_cup
    role: receptacle
    prompt: paper cup
    asset_group: paper_cup_A
```

이 명시 Config는 컵 두 개를 하나로 합치는 뜻이 아니다. `paper_cup_A` 모델링 작업 하나가 생성되고 `cup_1`, `cup_2`는 같은 Manifest로 생성되는 서로 다른 Object/Pose다. 그룹 필드가 없는 과거 Config는 Object별 개별 그룹으로 동작한다. 같은 형상이라도 실제 색/무늬가 다르면 `material_variant: red`처럼 구분하여 별도 불변 Asset으로 처리한다. 새 Material 시스템은 추가하지 않았다.

Codex 의미 분석은 개별 Object 수/ID·Category/Role·Prompt·Group·근거·불확실성·이미지별 Box를 제안한다. 같은 물체의 Side/Wrist 사진은 한 ID의 복수 관측이며, Group과 Mask/Object 대응은 독립이다. 응답은 `scene_analysis_schema()`의 엄격한 계약을 사용한다. 과거 축약 응답을 활성 실행에서 임의 보완하지 않는다. 치수/물성/Camera/q를 분석 응답에서 만들어 채우지 않는다.

동일 RGB·SAM 모델·Prompt/Box/추론 설정은 한 SAM 작업/Mask 캐시를 공유한다. 개별 Object ID는 덮어쓰지 않는다. `associate_instances`는 명시 Mask 선택, 이미지별 Box 또는 유일 후보를 사용한다. Mask 순서/Asset Group/미해결 Camera를 3D 정체성 근거로 사용하지 않는다. 같은 이미지의 같은 Mask가 둘 이상의 Object에 선택되면 **AMBIGUOUS**로 남기고 점군 정합에 넣지 않는다. 기존 Mask 선택 UI로 해결한다. 촬영 배치가 다르면 기존 배치 계약대로 분리한다.

`modeling/tasks.json`의 `/2` 작업은 그룹별 members·관측/Mask/Crop/Depth·기록 치수·메모·관계 provenance와 Fingerprint를 포함한다. `modeling/results.json`의 `/2`는 groups 아래 Fingerprint·Manifest SHA·멤버를 저장한다. 기존 assets 목록은 호환 조회용으로 남지만 Object 이름만으로 자동 재사용하지 않는다.

Fingerprint에는 중복을 제거한 형상 관련 member 정보, 실제 RGB/Mask/Crop/Depth 내용 SHA, 기록 치수/출처, 메모 SHA, 형상 제약과 생성 설정/계약 버전이 들어간다. 절대 경로·실행 시각·Scene Pose·Instance 이름 자체는 들어가지 않는다. 그래서 동일 입력 재실행/배치만 수정/동일 Instance 추가는 모델링을 반복하지 않는다. 사진·Mask 변경 시 생성 Fingerprint는 달라지지만, 유효한 기존 Scene 참조 또는 사용자 확정 공유 관계와 형상 서명이 유지되면 자산을 재사용한다. 원 생성 Fingerprint는 변경하지 않고 `reuse_observations`에 새 관측을 기록한다. 형상/실측/외형 변화는 검토하며, 유효한 Scene 참조도 없는 과거 이름별 결과는 `LEGACY_RESULT_REVIEW_REQUIRED`, 그룹 분리는 `GROUP_RELATION_CHANGED`다. 메모 변경 자체가 모든 그룹을 무효화하지는 않는다.

**새 시점 사진은 무조건 재모델링 사유가 아니다.** 기존 Scene/확정 Group으로 같은 물체가 연결돼 있으면 재사용하며, 불명확하면 표의 USDA 목록에서 Manifest를 선택할 수 있다. 새 형상/외형이면 **검토 후 새 모델링**을 선택한다. 미해결 그룹은 `ASSET_GROUP_UNRESOLVED`로 두며 `modeling-run`은 새 원격 작업을 시작하지 않고 exit 2로 검토를 요청한다. 직접 CLI Config를 편집할 때는 `asset_manifest` 또는 검토 후 `modeling_action: new`를 사용한다. 다른 그룹/원 USDA는 바꾸지 않는다. 기존 실측 치수와 모순되는 물체로 바꾸는 작업은 기존 보호 검사를 유지하므로 별도 Object ID/새 자료로 구성해야 한다.

Blender Object Authoring은 `--ro-bind / /`를 사용하지 않는다. 빈 루트에 실제 설치 Blender executable, bpy로 찾은 SYSTEM/LOCAL 리소스, ldd로 확인한 라이브러리 디렉터리/로더, 필요한 시스템 폰트/설정, Worker 소스 파일만 읽기 전용으로 노출한다. 작업 폴더가 유일한 호스트 쓰기 경로이고 author.py/inputs는 그 안에서도 읽기 전용이다. `/tmp`는 전용 임시 filesystem, `/dev`는 최소 가상 장치, `/proc`는 새 PID namespace이며 네트워크는 차단한다. HOME은 `/nonexistent`, locale/PATH/temp/thread 설정만 전달하며 부모의 API Key/토큰/인증/Python/loader 환경변수는 전달하지 않는다. 입력 symlink는 거부한다. 런타임/Sandbox 구성을 확인할 수 없으면 권한을 늘리지 않고 중단한다. 일반 Scene Renderer의 환경/실행 방식은 유지한다.

사용자는 Scene Prepare에서 사진·Scene Memo 저장 → Auto Reconstruction/Codex 분석 → 공유 Group 검토 → 필요 시 Mask 선택 → 모델링 실행 → 정합/비교 순으로 사용한다. 표에서 Group/종류를 확인·수정할 수 있다. Codex는 그룹마다 Blender root `r2s_id=asset_group` 하나를 작성하고, `blender-object-author --objects ASSET_GROUP ...`로 등록한다. Backend가 기존 instance_operation으로 개별 Instance를 만든다.

이번 안정화에서는 새 원격 Codex 호출 없이 Fake CLI 응답과 기존 Blender 스크립트를 사용했다. 동일 컵 2개 → 그룹 1개 → 실제 Texture/Collision USDA 1개 → Instance 2개 → 실제 640×480 MuJoCo RGB를 시험했다. RGB/Mask와 치수는 통제 fixture이며 실제 사진 정합 정확도/새 SAM·DA3·원격 모델링 성공으로 보고하지 않는다. 실제 자료의 Camera/Scale·Object 연결이 부족하면 기존 NEEDS_MORE_DATA/AMBIGUOUS를 유지한다.

## v3 — 새 모델링 요청·메모 사실·관측 재사용

선택 우선순위는 **미완료 새 모델링 요청 → 명시 Manifest → 유효한 기존 Scene Asset → 검증된 자동 캐시 → 검토**다. Manifest/원본 SHA·실측 충돌·관측 수량 진단은 유지한다. 명시 선택도 무효 Manifest나 서로 다른 실측 치수를 승인하지 않는다.

- **새 모델링:** 표의 `검토 후 새 모델링`을 선택하면 같은 Group의 행에 `modeling_action: new`와 하나의 `modeling_request_id`가 들어간다. 저장·재시도는 이 ID를 유지한다. 새 선택 동작은 새 요청 ID를 만든다. 원격 코드는 해당 그룹만 작성하고, Blender 등록 결과의 `generation_request_id`를 대조한 뒤 `request_status: REGISTERED`로 완료한다. 동일 Mesh라도 새 요청은 새 불변 Version이다. 기존 Library/Manifest는 보존한다.
- **부분 성공:** 각 Asset 등록 직후 결과를 기록한다. 다음 그룹이 실패해도 성공한 요청은 재시도에서 제외한다. 이미 완료한 요청을 다시 실행해 모델을 중복 호출하지 않는다. CLI에서 별도의 새 요청을 원하면 새 `modeling_request_id`를 지정한다. 같은 ID를 계속 쓰는 것은 같은 작업의 재실행이다.
- **메모 출처:** Codex가 `scene_memo_sha256`, `objects`, `asset_groups`, `needs`를 반환한다. Group마다 `relation_source`, `evidence_quote`, `change_kind`, `members`, `evidence`를 받는다. Python은 원문에 인용문이 있는지와 SHA·구조만 검사하며 긍정/부정·언어·키워드를 다시 분류하지 않는다. `semantics_verified=false`를 유지한다. 사진 추론은 estimated/PROPOSED, unknown은 UNRESOLVED다.
- **제품 관계와 Mask:** 같은 제품 선언은 공유 Group을 확정하지만 SAM의 Mask를 임의 Object에 배정하지 않는다. Mask가 모호하면 Object Association만 검토한다. 여러 물체를 관측해야 하는 이미지에서 후보가 부족하면 `OBSERVATION_COUNT_REVIEW_REQUIRED`로 별도 보고한다. 가림/미검출인지 실제 개수 충돌인지는 자동 확정하지 않는다.
- **관측과 모델:** RGB/Mask/Crop/Depth·메모 SHA를 담은 생성 Fingerprint는 불변 이력이다. Object/Asset 동일성은 기존 Scene의 ID/Version 참조 또는 사용자 확정 공유 관계다. 형상·실측·Material 조건이 같고 새 변경 근거가 없으면 이동·회전·추가 Side/Wrist·배경/조명 변화는 Pose/Camera 정합 입력으로 처리한다. 새 Crop은 내용별 경로에 저장해 과거 생성 Crop도 덮어쓰지 않는다. 같은 Category의 새 Object만으로 재사용하지 않는다.
- **변경 검토:** 형상 제약/실측 변경 및 Codex가 현재 메모에 대해 반환한 `change_kind=geometry|appearance|uncertain`은 `MODEL_INPUT_CHANGED`/`ASSET_DIMENSION_CONFLICT`/`SHAPE_CHANGE_REVIEW_REQUIRED`로 검토한다. 무늬 변경은 새 Material Variant를 선택할 수 있으며 기존 Geometry/Collision 파일을 삭제하지 않는다. 새 사진의 숨은 형상 차이를 자동 판별하는 모델은 추가하지 않았다. 발견한 차이는 메모/형상 제약/Variant로 명시해야 한다. 원시 SAM/DA3 캐시와 정합 관측 SHA 검사는 계속 수행한다.

고급 Config의 독립 새 요청 예:

```yaml
objects:
  cup_1:
    prompt: paper cup
    category: paper_cup
    asset_group: paper_cup_A
    modeling_action: new
    modeling_request_id: request_cups_revision_2
  cup_2:
    prompt: paper cup
    category: paper_cup
    asset_group: paper_cup_A
```

한 행에 지정한 새 요청은 Group 전체에 적용된다. UI는 같은 Group 행을 함께 갱신한다. 다른 Group은 기존 Manifest를 유지한다. `modeling/tasks.json`과 `modeling/results.json`의 `/2` 구조에 요청/생성 입력/재사용 관측/이력을 추가하며 새 Scene Schema나 Asset DB를 만들지 않는다.

v3 검증은 Fake Codex CLI와 실제 Blender/OpenUSD/MuJoCo, 기존 회귀를 사용한다. 새 원격 Codex·실제 SAM/DA3 재추론·하드웨어 구동은 하지 않았다. 상세 결과·기존 실패 대조·실사진 미검증 범위는 [누적 기록](../docs/automated-reconstruction.md)의 v3 절을 따른다.

## 이전 사용법·검증 기록 — 2026-11-04

기존 Scene Prepare의 Preview·Teleop·Capture·Input·메모 배치는 유지한다. Auto Reconstruction 안에서만 **촬영 배치 선택, USDA 자산 선택, Codex 작업자료/명시 CLI 실행, 재정합**을 확장했다.

1. 사진·Side/Wrist Capture·메모를 Project에 모은다. 실제 물체 배치가 바뀌면 촬영 배치를 나눈다. Wrist q·시각·URDF·Mapping은 기존 관측을 그대로 쓴다.
2. Codex가 메모/사진에서 Object ID·역할·SAM prompt를 구성한다. 신규 Project의 목록이 비어 있으면 최초 Auto Reconstruction이 분석 작업자료를 만든다. 현재 Codex 대화 또는 `USDA·Codex 모델링` 탭의 명시 CLI 버튼으로 목록을 만들고 다시 실행한다. AI가 제안한 물체 목록은 estimated이며 실측 치수/물성을 만들어 채우지 않는다.
3. SAM 종료 → MASt3R GPU 대응/Pointmap → COLMAP SfM/BA·Dense 정합 → Camera/K 초기 추정 순서다. K·Extrinsic·Mount·보드 코너 입력은 필수가 아니다. 알려진 baseline 또는 충분히 다양한 측정 Wrist q/FK가 없으면 Scale/World는 UNRESOLVED다. 카메라만 추정된 상대 초안을 실제 미터 Scene으로 승인하지 않는다.
4. 실측 치수는 보존하며 새 Primitive Visual을 만들지 않는다. Asset/Object 이름 일치만으로 새 사진의 물체를 기존 USDA에 자동 연결하지 않는다. `ASSET_MATCH_UNRESOLVED` 작업자료에서 치수·역할·사진·후보 Metadata를 검토하고 `objects.<id>.asset_manifest`를 명시 선택하거나 새 모델링을 진행한다. 이미 Scene이 참조하는 유효한 자산은 배치 변경 시 그대로 쓴다. 기존 USDA를 선택하거나, `modeling/tasks.json`·`CODEX_MODELING.md`를 Codex가 읽고 필요한 물체만 기존 Blender로 작성한다. 그룹당 root `r2s_id=asset_group`, 별도 convex Collision Mesh `r2s_collision=True`, m/+Z·UV·Image/PreviewSurface Material 계약이다.
5. `blender-object-author`는 격리된 Blender 출력의 USDA를 OpenUSD로 읽고 Mesh/Texture/상대 Closure·단위·원점·SHA·convex Collision을 확인한다. Library에 불변 버전으로 등록하고 `modeling/results.json`을 쓴다. Auto Reconstruction 재실행이 그룹 Fingerprint와 Manifest를 검증한 결과만 Import하고 추론 캐시를 재사용한다.
6. 같은 자산으로 Object Pose를 초기화하고 Hybrid의 raw-depth Camera/Object 공동 정합을 수행한다. Camera·K·Scale이 변할 때 ray를 재투영하고 World 점군도 새로 게시한다. Side는 공유 Pose, Wrist는 공유 Link Mount, External은 이미지별 Pose다. 수치적으로 식별 불가능하거나 독립 View가 악화되면 보정을 적용하지 않는다.
7. `DRAFT_READY`는 필수 Geometry/Camera/Pose·자산 검증과 실제 Backend 정합, 유효한 train 관측의 유한한 RGB 렌더/비교 결과가 있는 초안이다. Cloud 없음·validation만 있음·정합 실패/필수 정보 미해결이면 `NEEDS_MORE_DATA`, 새 모델링은 `WAITING_FOR_CODEX`, 물체 의미 분석은 `WAITING_FOR_CODEX_ANALYSIS`다. Project Status·`reconstruction.json`·Qt 표시는 같은 상태이며, `reconstruct/refit-pairs`의 CLI exit는 초안 준비 0 / 대기·추가 자료 필요 2 / 예외 1이다. `PHYSICS_READY`, ACCEPTED나 Task 성공이 아니다. 기존 Candidate 평가와 새 Review Export를 사용하고 Current·과거 Revision을 덮어쓰지 않는다.

```text
Workspace/object_assets/<asset_id>/<version>/
  manifest.json       # 단위·원점·치수 출처·defaultPrim·SHA/종속 목록
  usd/<object>.usda   # Texture·참조 파일은 내부 상대 경로
  visual_*.obj        # 같은 USDA의 MuJoCo용 UV 유지 파생물
  collision_*.obj     # 별도 convex piece
  texture_*.png
  source.blend        # Blender로 제작했다면 보존
```

Instance별 Pose는 Candidate에만 있다. 동일 Asset 복제는 Mesh bytes 복제가 아니다. Instance 제거 뒤 Library와 이전 Export는 보존한다. Geometry/Material/Collision 변경은 새 Asset version, 배치 변경은 기존 `update_pose`다.

Codex가 사용하는 실제 CLI:

```bash
python -m real2sim_builder.cli reconstruct PROJECT --candidate NAME
python -m real2sim_builder.cli object-asset PROJECT list
python -m real2sim_builder.cli object-asset PROJECT register --id cup --path /path/cup.usda
python -m real2sim_builder.cli object-asset PROJECT instantiate --candidate NAME --object cup2 --manifest ../../object_assets/cup/VERSION/manifest.json
python -m real2sim_builder.cli blender-object-author PROJECT --candidate NAME --script author.py --objects cup
python -m real2sim_builder.cli modeling-run PROJECT --candidate NAME
python -m real2sim_builder.cli refit-pairs PROJECT --candidate NEW --scene-state LAYOUT
python -m real2sim_builder.cli physics-check PROJECT --candidate NAME --engine mujoco --steps 350
python -m real2sim_builder.cli physics-check PROJECT --candidate NAME --engine isaac --steps 350
```

Python API는 `object_assets.register_object_asset/list_object_assets/instance_operation`, `Candidate.edit`, `rendering.author_object_assets`, `automation.reconstruct/refit_pairs/run_codex_modeling`다. 같은 Workspace의 Project는 공용 목록에서 동일 Manifest를 직접 선택한다. 다른 Workspace로 명시 Clone하면 참조한 버전만 새 Workspace Library에 복사하며, 독립 Export는 필요한 Closure를 패키지 안에 포함한다. 기존 Project 내부 Manifest도 계속 읽는다.

`modeling-run`은 설치된 공식 `codex exec`를 **명시 시작할 때만** 실행한다. 원 저장소 밖 임시 작업공간·workspace-write·추가 writable root 없음·명령 network off로 코드 작성을 제한한다. 생성 script는 위 Object Sandbox의 빈 루트·런타임 허용 목록·최소 환경·전용 출력에서 Blender로 실행한다. 실패/timeout/중단은 해당 child만 정리한다. 현재 Codex 대화에서 작업자료를 읽는 방식도 지원한다. 2026-11-04 후속 검증에서는 **CLI 0.166.0의 기존 ChatGPT 로그인으로 실제 모델 호출 1회**를 수행했다. `--image`로 원본 RGB·Crop·SAM Mask를 첨부하고, 같은 Image ID의 DA3 depth/confidence/Camera 추정 및 메모·기록 치수를 `tasks.json`에 전달했다. 실측으로 표시되는 것은 명시 기록 치수뿐이다. 실제 생성 코드 → Blender → Texture/Collision USDA 등록 → Candidate 추가 → MuJoCo RGB를 확인했다. 첫 Export의 숨긴 Collision 누락은 수정 후 생성 코드를 재사용했으며 두 번째 원격 호출은 하지 않았다. 상세 실패·재개·합성 fixture 보정과 원본 보존 범위는 누적 기록을 따른다.

Real/Sim은 중단 후 **촬영 자료로 Scene 재정합**에서 같은 Dialog를 연다. 기존 Pair Reader의 Real RGB·측정 q·Revision·Sim q 차이를 사용한다. 원 Pair SHA와 Scene identity/Manifest를 검사하고 해당 Package의 Manifest에 포함된 `authored_scene.json`에서 새 Candidate를 만든다. Current가 달라도 촬영 당시 Source를 사용하며, Source가 없거나 서로 다른 Revision/배치가 섞이면 `PAIR_SOURCE_UNRESOLVED`/`PAIR_SOURCE_MISMATCH`/`PAIR_LAYOUT_MISMATCH`로 중단한다. Current를 대체 Source로 추측하지 않는다. Source와 배치가 다른 기존 Candidate도 재사용하지 않는다. 재정합은 Source Geometry·Material·Collision을 보존하고 Object Pose와 Camera 변수만 조정한다. 저장 Sim은 과거 Runtime 진단이며 새 Candidate의 정답으로 최적화하지 않는다. 동일 정적 배치의 여러 자세를 함께 사용하고, 재배치는 다른 촬영 배치를 선택한다. `refit-pairs --dataset PATH`는 미등록 완료 Pair를 기존 Import로 등록할 때만 사용한다. 기존 Import의 identity/품질 판단을 우회하지 않는다.

실제 검증 범위·기존 회귀 실패·미완료 목록은 [누적 기록의 2026-11-04 절](../docs/automated-reconstruction.md)을 따른다. 합성 Camera 복원과 실제 사진 정확도는 별개다. 독립 검증 사진/자세가 없어 Backend 우승·실제 mm 정확도는 미검증이며, 일반적인 자동 Lens Distortion·자동 Mount-link 식별·전체 Robot/Gripper Task 물리 검증도 완료하지 않았다. 프로그램이 손쉽게 식별되지 않는 Scale을 1로 만들지 않는다.

## 이전 2026-11-03 구현 당시 사용법·기록

아래는 앞 단계의 기록이다. 현재 실행 순서와 새 API는 위 절을 따른다. 수동 보드와 Camera 고정에 대한 설명은 당시 제한이다.

2026-11-03. 기본 진입점은 `reconstruct`와 Scene Prepare/Builder의 **Auto Reconstruction** 폼이다. 기존 Codex 수동 편집 중심 흐름을 대체하는 구현을 진행 중이며, **전체 Physics-Ready 자동 생성 완료는 아니다.** 실행 기록·미완료 항목은 [단계별 기록](../docs/automated-reconstruction.md)을 따른다.

## 사용자 흐름

Scene Prepare에서 Project와 자료를 저장한 뒤 Auto Reconstruction을 연다. 사진의 정적 배치 ID, Camera/렌즈 ID와 유형, train/validation을 등록한다. 물체 표에는 ID·형상·역할·실측 크기(mm)·컵 벽 두께·Support·SAM 설명을 입력한다. 같은 색/모양의 물체를 하나의 ID로 추측하지 않는다. Wrist는 실제 q·단위·시각·Mapping이 있는 공식 Capture/Snapshot 입력을 사용한다.

현재 단일 UI는 저장된 SAM·MASt3R·COLMAP Runtime을 사용하며 환경 탭을 제공하지 않는다. 아래 과거 SAM/DA3 시험 기록은 당시 검증 이력이며 현재 실행 지시가 아니다.

측정된 World 위치·치수가 있는 보드를 사진에서 선택하고 네 모서리를 지정할 수 있다. 순서는 보드 local `(-X,-Y), (+X,-Y), (+X,+Y), (-X,+Y)`다. 알려진 K와 대응점으로 External PnP를 수행한다. World 위치가 미측정인 보드에 임의 위치를 넣지 않는다. 현재 Side/Wrist 자동 경로는 기존 검증된 K/pose/distortion을 사용하며, 일반 자동 렌즈 Calibration은 별도 미완료다.

실행 결과의 모호한 Mask는 상태 탭에서 사진·Object·Mask를 선택하고 **선택 Mask 사용**으로 명시한다. 잘못된 Mask는 원본과 같은 해상도의 이진 PNG를 지정한다. 같은 Candidate를 다시 실행하면 동일한 SAM/DA3 입력 캐시는 재사용하고 점군/정합을 다시 계산한다. 일반 사용자는 Raw JSON·4×4 Transform·ICP 설정을 작성할 필요가 없다.

사진·영상 등록은 RGB와 외부 mp4/mov/avi를 지원한다. 기존 `extract_videos`로 최대 12개 프레임을 샘플링하고 Source video SHA·frame index·실제 영상 시각·정적 배치 ID를 유지한다. 동일 영상 전체를 하나의 observation group으로 묶어 train/validation 누출을 거부한다. **Wrist 영상의 q 자동 동기화는 제공하지 않으며** 공식 Capture/Snapshot을 사용한다. 동일 영상은 독립 최종 검증 사진을 대신하지 않는다.

## CLI와 Python API

준비된 Builder Backend 환경에서 사용한다. 경로/이름은 예시이며 실제 측정값이 아니다.

```bash
python -m real2sim_builder.cli register-rgb PROJECT photo1.png photo2.png \
  --camera phone_main --type external --scene-state layout_1 --split train
python -m real2sim_builder.cli reconstruct PROJECT --candidate auto_1 --config reconstruction.yaml
# Project에 저장한 동일 구성으로 재실행
python -m real2sim_builder.cli reconstruct PROJECT --candidate auto_1
# 등록/물리만 따로 확인
python -m real2sim_builder.cli register-views PROJECT --candidate auto_1 --anchors anchors.yaml --scene-state layout_1
python -m real2sim_builder.cli physics-check PROJECT --candidate auto_1 --steps 500
```

`reconstruct --config`는 구성을 Project에 저장하고 실행한다. 같은 Candidate를 지정하면 기존 OPEN 후보의 추론 캐시를 사용할 수 있다. 다른 정적 배치·원본 변경에는 새 Candidate를 사용한다. 자료 부족은 종료 코드 2, 실패는 예외/비정상 종료로 구분한다. `control PROJECT stop`은 해당 Worker와 소유 모델 child만 종료하며, Candidate/중간 결과를 보존한다.

```python
from real2sim_builder.project import Project, Candidate
from real2sim_builder.automation import reconstruct
from real2sim_builder.authoring import save_configuration
from real2sim_builder.observations import register_image, register_views
from real2sim_builder.inference import run_models, build_point_clouds
from real2sim_builder.calibration.hybrid import fit_scene

project = Project(project_path)
# UI와 같은 구조화된 구성. 일반 사용자는 UI를 사용한다.
save_configuration(project, config)
report = reconstruct(project, candidate="auto_1")
```

고급/API용 구성 예 (기존 수치 측정 자료가 있을 때만 `measurements`를 선택적으로 사용한다. 일반 입력은 Scene Memo이며 아래 표를 작성할 필요가 없다):

```yaml
scene_state_id: layout_1
sam:
  python: /path/to/existing/sam/python
  model: /path/to/sam3.1_multiplex.pt
  device: cuda:0
  imgsz: 1024
  timeout_s: 900
geometry:
  backend: mast3r_colmap
  python: /path/to/existing/sfm-mast3r/bin/python
  source: /path/to/official/mast3r
  model: /path/to/existing/MASt3R_checkpoint.pth
  colmap_python: /path/to/existing/sfm-colmap/bin/python
  device: cuda:0
  process_res: 512
  iterations: 100
  timeout_s: 900
objects:
  block:
    prompt: red cube
measurements:
  - id: block
    role: manipulable_object
    kind: box
    dimensions_m: [0.03, 0.03, 0.03] # 형식 예; 실제 측정값으로 바꿀 것
    evidence: [caliper_record]
fitting:
  supports: {block: table}
  max_iterations: 4
  max_evaluations: 120 # 반복당 native loss 평가 예산
  minimum_improvement: 0.0001
  patience: 2
  optimize_intrinsics: false # 관측 가능한 변수만 Codex가 선택; 실측 K는 고정
```

선택적 기존 `measurements`는 box/cylinder/sphere/container/mesh다. 메모에서 해석한 새 치수는 `objects.<id>.geometry`로 전달하며 두 설정을 중복 작성하지 않는다. Container에는 `wall_m`, 선택 `round`, `bottom_diameter_m`를 선언한다. 기존 CAD/Robot은 재생성하지 않는다. 실측으로 보호된 치수와 Robot은 수정하지 않는다. `mass_kg/friction`을 제공하면 `physics_source`를 명시하며 기본 provenance는 estimated다. 새 Object pose는 unknown이며 metric 관측 없이 identity pose를 넣지 않는다.

`anchors.<image_id>`는 `world_points_m`, `uv_px`, `source: measured|calibrated`, `evidence`다. `selections.<image_id>.<object_id>`는 Mask 후보 index 또는 수정 PNG 경로다. `objects.<id>.images.<image_id>.box_xyxy`는 원 해상도 Box hint다. 명시 `image_ids`로 같은 배치의 일부 사진만 모델 추론에 사용할 수 있다. 원본 이미지·관절 기록을 덮어쓰지 않는다.

새 설정은 `geometry.backend: mast3r_colmap`을 사용한다. `da3`만 남아 있는 구성도 새 Backend를 선택하며, 실행에는 저장된 MASt3R/COLMAP Runtime 경로가 필요하다. 명시 `geometry.backend: da3`는 제거된 Backend로 거부한다. 현재 대상 Scene은 다른 필드를 보존한 채 새 설정으로 전환했다. 과거 DA3 Cache·모델·Conda 환경은 삭제하거나 새 Geometry로 재해석하지 않는다. train/validation·상대 Scale·Sim(3)·distortion·단계별 캐시 계약은 [Backend 구현 기록](../docs/mast3r-colmap-backend.md)을 따른다. 현재 단일 UI는 저장된 경로를 읽고 누락 항목만 안내한다.

## 좌표·근거·캐시

- 원 해상도 Mask와 MASt3R의 실제 resize/center-crop 행렬을 결합한다. 모델의 예측 K를 실제 Calibration으로 부르지 않는다. 같은 물리 렌즈는 하나의 K를 공유하고 이미지별 resize/crop/EXIF optical 회전을 적용한다. 알 수 없는 crop·거울 반전은 추측하지 않는다.
- Metric 기준은 검증된 Camera baseline, 다양한 실제 q/FK의 hand-eye, 또는 실측 직사각형 지지면의 가시 Depth다. 지지면 기반 World 원점·축은 명시 좌표 gauge이며 측정된 Robot Base가 아니다. 부분/비평면/크기비 불일치로 식별할 수 없으면 scale=1로 진행하지 않는다. 결과 점군은 derived/estimated다.
- 유효 Depth·confidence·Mask 경계를 필터링하고 가시 점만 생성한다. 가려진 면을 관측으로 채우지 않는다. EXIF 방향은 원본을 보존한 Candidate-local upright RGB로 한 번만 변환하고 SAM/Geometry/코너 지정에서 같은 좌표를 사용한다. Distortion 자동 제거는 아직 제공하지 않으며 undistorted calibration 자료가 필요하다.
- `inference/sam/<digest>`는 이미지/Object/Prompt·모델·Runtime별 캐시, `inference/mast3r_colmap/<digest>`는 입력 SHA·정적 Mask·Camera·설정·Runtime·소스·모델별 캐시다. 과거 `inference/da3`는 기록으로 보존한다. Measurement는 모델 추론 key에 넣지 않으며 바뀐 치수로 정합을 다시 수행한다.
- `reconstruction_observations`는 Candidate-local NPZ/PNG와 SHA·단위·World frame·scale/Camera 근거를 보존한다. Project signature가 이 파일을 포함한다. 실행 설정도 Candidate-local `reconstruction-config.yaml`에 고정한다. Project의 현재 설정 수정은 원본 Evidence 변경으로 취급하지 않으며, 실행에서 쓴 설정은 Candidate signature와 새 Export에 함께 보존한다. Camera/source가 바뀐 점군은 다시 만든다.
- Current와 과거 Export는 자동으로 교체하지 않는다. 최종 패키지는 기존 `export`로 새 경로에 게시하며 파생 NPZ/Mask도 소유 경로로 재배치한다.

## 정합과 결과 읽기

자동 실행은 `automation.reconstruct → hybrid.fit_scene` 한 경로다. 알 수 없는 물체 pose는 `fit_clouds`로 초기화한다. 이어 선택한 MuJoCo 또는 Isaac의 실제 RGB/Mask/optical depth를 모든 유효 train View에서 렌더하고 공통 Camera/Object 변수를 제한적으로 갱신한다. 원 optical ray를 매 평가에서 현재 K/pose로 재투영한다. Side pose와 Wrist mount는 물리 Camera별 하나이고 measured q·실측 치수·보호된 Calibration은 고정한다. 명시 Support의 upright/높이를 보존하며 종이 테두리를 XY 제한으로 쓰지 않는다.

`fitting/report.json`(Isaac은 `fitting/isaac-*/report.json`)은 반복별 공동 loss, View/Object 지표, 최선 상태와 종료 이유를 기록한다. RGB는 0..1 robust 차이, Mask는 누락/초과 비율, Edge는 영상 대각선으로 정규화한 거리, Depth/Metric은 기본 5mm 척도다. 기본 가중치는 RGB .15 / Mask 1 / Edge .5 / Depth .25 / Metric .25 / Prior .005다. 한 View가 기준보다 .05 넘게 나빠지는 갱신은 채택하지 않는다. 정상 중단/오류에서는 최선 상태를 재투영해 `best-scene.yaml`과 Candidate에 보존한다. Native 강제 종료에서는 마지막으로 완료된 반복의 Camera/점군이 일치하는 체크포인트를 보존한다. 예산 소진은 `BUDGET_EXHAUSTED`이고 정합 성공이 아니다. Validation은 최적화/최선 상태 선택에 사용하지 않는다.

`fitting/final/previews/<image_id>/`에 overlay·difference·side-by-side를 저장한다. `compare_backends`는 명시 실험 API에만 남으며 자동 실행이나 기본 Backend 선택에 쓰지 않는다. 실험 구성의 `backend`는 이 비교 함수에서만 의미가 있다. 삭제한 `refine_masks`는 사용하지 않는다.

`미검증 초안 새 Export`는 기존 명시 review Export이며 승인과 구분한다. `reconstruction.json`에는 필요한 추가 근거가 나온다. `physics/physics.json`은 해당 Candidate의 실제 MuJoCo 수동 물체 probe다. Isaac은 `physics-check ... --engine isaac`의 별도 native child로 검사한다. 실행하지 않은 엔진/Robot/Task는 NOT_TESTED다. 실제 사진의 전체 E2E 한계와 재설계 결과는 [현재 검증 기록](../docs/real2sim-multiview-architecture.md)을 따른다.

## 기존 디버깅/검토 인터페이스

`auto-observe`의 기존 HSV/Marker/Landmark proposal/commit과 `candidate ... fit --target joint:scene`은 baseline/특수 보정용으로 유지한다. 새 자동 경로의 필수 Codex 작업이 아니다. `candidate evaluate`, `promote`, `export`, `verify`의 기존 보호·Revision/Scene Contract는 유지한다. 자동 재구성만으로 이 검토를 우회하거나 Teleop/학습을 실행하지 않는다.

### 공동 렌더 엔진과 외관 설정

기존 Reconstruction 설정의 `fitting`에서 지정한다. UI 프로세스에 Kit를 로드하지 않는다.

```yaml
fitting:
  engine: mujoco  # 또는 isaac: 별도 Kit child, 같은 공동 solver
  max_iterations: 4
  max_evaluations: 120  # iteration당 평가 예산
  optimize_appearance: true
  optimize_lighting: true
  native_timeout_s: 900  # Isaac child의 일시정지 외 실행 제한
```

초기 생성은 appearance/lighting을 기본 활성화한다. 추정 일반 물체의 색·roughness/metallic, ambient/광원 energy만 변경하고 보호 실측·Robot·공용 Asset의 불변 재질·Texture는 보존한다. Pair 재정합은 원 재질을 유지하므로 두 옵션을 비활성화한다. 불변 공용 Asset의 재질 변경은 명시 새 Version/Variant 작업이며 이 최적화에서 자동 생성하지 않는다. MuJoCo 재질은 Phong 근사이고 두 엔진의 색상 동등성 인증이 아니다. distortion은 최적화하지 않는다.

### 관측에 따른 자동 변수 선택

공동 렌더 정합은 `joint.select_parameters`에서 **train 관측만** 보고 조정할 변수를 선택한다. 사용자가 매번 Camera/Object 목록을 작성할 필요는 없다. `optimize_intrinsics`, `optimize_depth_scale`, `robot_base`는 기본적으로 후보에 포함하되 아래 조건이 부족하면 현재 값을 고정한다. 명시 `false`는 해당 변수를 제외한다. `true`가 관측 부족이나 보호된 실측을 우회하지는 않는다.

- Camera/Object가 함께 움직여도 구별할 수 없는 경우 Camera를 고정한다. 같은 물체를 관측하는 고정 Camera 또는 위치가 고정된 가시 기준 물체가 필요하다. 다른 사진에만 있는 무관한 기준과 함께 움직이는 Robot Base는 기준으로 빌려 쓰지 않는다.
- Wrist Mount는 실제 q가 있는 서로 다른 자세 3개 이상, 두 축 이상의 회전 변화가 필요하다. 같은 자세 사진이나 검증용 사진을 더해 이 조건을 채우지 않는다. 렌즈 K에는 서로 다른 시점 3개 이상과 비평면 점군 근거도 요구한다.
- Camera·K·Scale을 변경하려면 원 pixel 좌표와 relative depth가 필요하다. World/optical 점군만 남은 자료로 Camera를 변경하지 않는다. 고정 Camera의 기존 World 점군은 물체 위치 정합에 계속 사용할 수 있다.
- Depth Scale에는 같은 batch의 실측 크기와 서로 다른 시점이 필요하다. Robot Base에는 Wrist 관측과 연결된 World 기준이 필요하다. 조건을 충족한 값도 추정 결과이며 실측 Calibration으로 승격하지 않는다.
- 무늬 없는 단순 구의 회전, 수직 원통의 yaw는 현재 방향을 유지한다. Texture·자식 물체·비대칭 Collision·공용 Asset에는 이 단순 대칭 규칙을 적용하지 않는다. 일반 Mesh의 대칭이나 모든 퇴화를 자동으로 판별하는 기능은 아니다.
- 색 기준이 고정된 가시 물체 없이 색과 조명을 동시에 바꾸면 서로 보상할 수 있으므로 조명은 고정하고 외관만 조정한다.

처음에는 Geometry 변수만, 이후에는 Appearance 변수만 실행한다. 외관 변수가 있으면 `max_iterations`의 앞쪽 절반(올림)을 Geometry에 배정하고 나머지를 외관에 사용한다. Geometry가 먼저 수렴하거나 조정할 변수가 없으면 바로 외관 단계로 넘어간다. `max_iterations: 1`에서 Geometry 변수가 있으면 외관 단계까지 실행하지 않는다. 기존 평가 예산·최선 체크포인트·중단 처리는 유지한다.

`fitting/report.json`의 `observability.geometry/appearance`에 활성 변수와 고정한 좌표·이유·추가 자료 안내가 나온다. `history[].strategy`는 실제 반복 단계다. 필수 Camera/Object 근거가 부족한 경우 `observability.needs`를 초안 준비 판정에 전달하므로 낮은 loss만으로 준비 완료가 되지 않는다. 선택적 K/Scale/Base의 고정 사유는 별도로 표시하며 그 자체로 전체 실행을 중단하지 않는다.

이 선택은 보수적인 기하 조건 검사다. 자세 중복 기준은 이동 5mm·회전 약 2도 미만이고, Wrist 두 축 회전은 기준 자세 대비 회전 벡터의 두 번째 특잇값 0.05rad 초과를 사용한다. 이는 실측 정확도 보증이나 전체 수치 Jacobian의 rank/불확실성 분석을 대체하지 않는다.

Isaac 렌더는 반복 중 Physics Step 없이 RGB/semantic mask/optical depth를 읽는다. 센서 초기화와 정합의 물리 준비/Task 검증은 별개다. 실행 중 Camera 해상도를 바꾸려면 재초기화한다. 중단/예산 초과는 성공으로 기록하지 않으며 완료된 체크포인트를 보존한다.

### 확정 Support와 접촉 (2026-11-07)

Codex 분석의 `support_relation`은 `geometry`의 치수와 별도 근거를 가진 같은 Object 출력 필드다. `support`, `source: user_memo|visual_inference`, `evidence_quote`, `evidence`, `parallel`을 사용한다. 사용자 설치 관계 인용은 CONFIRMED, 영상만의 추정은 PROPOSED로 `fitting.supports`에 저장한다. 신규 응답은 `geometry.support=null`; 과거 별도 근거 없는 해당 필드는 제안으로만 읽는다.

확정 관계는 Candidate의 기존 `geometry_constraints.supports`에 결합되어 Export에도 남는다. 초기 Pose와 관계없이 지지면 좌표의 접촉·상대 자세를 적용한다. Dimensions/새 Asset 연결·Pair 정합에도 같은 계산을 재사용한다. 미확정 관계는 자동 수평화하지 않는다. 경사면·중첩 지지·Robot Mount와 진단의 필드는 [SCENE_RULES.md](SCENE_RULES.md)의 2026-11-07 절을 따른다. 새로운 실행 명령이나 별도 Support 설정 파일은 없다.


## 2026-11-08 최신 연결 계약: Photo 정합 → 센서 정합 → Pair 개선

Scene Prepare는 저장된 Scene Photos만 초기 MASt3R/COLMAP에 사용한다. Model References는 Codex가 실제 이미지 내용과 Scene Memo로 Object별 `model_references`에 연결하며 SfM/정합 Loss에는 넣지 않는다. `robot_attachment`는 실제 URDF Link와 추정 외형 pose이며 Optical Mount와 별개다.

기존 `reconstruct PROJECT --candidate NAME --run-modeling`과 단일 UI는 Photo View별 추정 K/optical pose에서 native 렌더·공동 `fit_scene`을 실행한 뒤 센서 초기화와 Photo+Side/Wrist 공동 정합으로 이어진다. 사진의 픽셀 잔차는 학습 잔차이며 독립 정확도가 아니다. 실제 q·실측·Support·공유 고정 Side/공유 Wrist Mount를 유지한다. Capture는 초기 SfM에 넣지 않고 기존 Camera 또는 Photo metric feature PnP와 FK로 등록한다. 관측 부족/서로 다른 배치를 임의 합치지 않는다. `capture_layouts`의 SAME_LAYOUT 근거가 없으면 정적 물체 대신 Robot 관측만 허용한다.

Real/Sim은 기존 `촬영 자료로 Scene 재정합` 버튼과 별도 Reconstruction Memo를 사용한다. source Package Identity와 Paired Capture를 같은 `refit-pairs`에 전달한다. 메모는 원본 Scene Memo와 분리되며 Source가 다르면 거부한다. 수정된 자산은 새 버전, Scene은 기존 Candidate에 보존하고 사용자의 검토 없이 Source/Export를 덮지 않는다. 센서 Mask-only 행에는 depth/물성을 만들어 넣지 않는다. 실제 Photo/센서/물리 실행 결과와 미실행 상태는 `docs/real2sim-multiview-architecture.md`의 최신 절에서 구분한다.
