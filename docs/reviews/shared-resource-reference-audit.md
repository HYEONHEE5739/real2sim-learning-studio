# 공유 자원·참조 경로 조사 — URDF 외 분산 관리

2026-11-17. 브랜치 `feat/simfoundry-style-reconstruction`, HEAD `8e02b1ae023a856694a40b947881f76b66410624`의 현재 미커밋 작업 트리를 조사했다. **URDF 외에도 관리 기준이 여러 경계에 걸친 자원이 있다. 우선 정리할 대상은 로봇·Device 선택, 공유 보정의 갱신 범위, Camera identity, 실행 Scene/Runtime 선택의 출처다.** Capture·Export·Checkpoint의 고정 기록이나 엔진별 파생 파일까지 최신 파일 하나로 치환하는 방식은 재현성을 깨뜨린다.

이번 작업은 소스·로컬 메타데이터 조사와 문서 작성이다. 제품 코드·설정·사용자 자료를 변경하거나 이동·삭제하지 않았다. 테스트, 모델 추론, 시뮬레이터, 장치 연결, 설치, Commit/Push는 실행하지 않았다. 아래 개선안은 적용 전 제안이다.

## 조사 범위와 현재 실물

세 제품 패키지 `scene_contract`, `real2sim_builder`, `robot_learning_workbench`의 Python **177개**를 색인하고, 자원 선택·경로 해석·복사·공유·생산자/소비자 호출을 추적했다. 모든 함수의 정확성을 재감사하거나 모든 경로를 실행한 것은 아니다. Workspace의 지정된 이름별 저장 root를 조사했으며, 과거 최상위 실험 폴더·전체 diagnostics·외부 SDK/Conda/HF Cache·인증 파일은 전수 조사 대상이 아니다. 다른 프로젝트 체크아웃은 읽지 않았다.

| 조사한 현재 자료 | 관측 결과 |
|---|---|
| Scene Project | `auto-version`, `pickplace-colorblock`, `pickplace-new`의 3개 |
| 공용 Object Library | **9개 Asset ID / 11개 Version**, 239개 파일 |
| Scene 내부의 등록 Object Library | 세 Project의 `input/object_assets/*/*/manifest.json`은 0개. 일반 `input/assets`·모델 참조가 없다는 뜻은 아님 |
| Robot Rig | `robot_rigs` 46개 파일. 새 Scene은 `so101_with_camera/rig.yaml` 선택 |
| Device | 세 Project 모두 `devices/so101-pickplace/capture.yaml` 선택. 현재 바인딩 SHA는 일치 |
| Scene 저장 이력 | `pickplace-colorblock`은 Candidate Scene 14개, Export 폴더 10개, 등록 실행 Package 7개 |
| Dataset 계열 | 지정된 `source` root에 Native Dataset 8개, `curation`에 선택 기록 6개 |
| 학습/변환 저장소 | 지정된 `annotation`, `datagen`, `dataset`, `policy` root는 비어 있음. 아래 관련 동작은 **소스 확인**이며 실제 학습·Resume 실행 결과가 아님 |

개수·경로·SHA·inode 근거는 Git 제외 `workbench_runs/diagnostics/shared_resource_audit_20261117_001/resource-inventory.json`에 있다. 폴더 이름·Object 이름만으로 동일성을 판정하지 않았다.

## 자원별 전체 대응

표의 ‘기준’은 현재 실제 선택 경계다. 모든 행에 이미 단일 원본 관리가 완성됐다는 뜻이 아니다.

| 자원 | 현재 기준과 사용처 | 비슷한 자료가 추가로 생기는 곳 | 판단과 정리 방향 |
|---|---|---|---|
| Robot URDF·Mesh·Rig | Project의 `robot_rig`, Device의 `robot_model`, Scene/Package의 `robot_model`·엔진 binding | Candidate 모델, Capture `model/`, Export 모델/실행 USD·MJCF | **선택 기준 분산 확인.** 새 제작의 Rig 선택과 Device/FK 모델 호환성을 함께 확인해야 한다. Capture/Export의 기존 모델은 고정 기록으로 보존 |
| Object USDA·Texture·Collision | 공용 `object_assets/<ID>/<Version>`; Reader는 Scene-local 등록 자산도 지원 | 원본 Blender 산출물, Rig의 Camera 사본, Package closure, Viewer 임시 OBJ/PNG | Library가 이미 공용 기준 역할을 한다. 같은 이름의 Scene Object가 자동으로 그 Library 자산에 연결되는 것은 아님. 임시 변환과 고정 Package는 별도 역할 |
| Device 구성 | Project가 `devices/.../capture.yaml` 경로+SHA로 선택 | follower/leader JSON, Camera stream JSON, 외부 경로의 Precision·SDK 보정 | 중앙 선택은 있으나 참조 파일의 소유 경계와 변경 영향이 여러 파일에 걸림 |
| SDK 보정·Precision·Mapping | Device 입력의 선택 파일; Precision은 SDK·motor·모델 identity에 결합 | `calibration/history`, Snapshot Mapping, Package `calibration.json` | **공유 저장 범위 확인 필요.** SDK 보정·raw→model 매핑·baked 보정은 의미가 달라 하나의 JSON으로 합칠 대상이 아님 |
| Camera·Mount·World | USB stream은 Device; 광학 K·왜곡·Mount·World는 Scene/보정 기록 | Capture Camera snapshot, Candidate registration, Export Camera, Pair `sim_cameras` | 물리 센서 identity와 광학/Mount 보정의 연결 보강 후보. Scene별 World pose와 공유 가능한 렌즈 보정을 구분 |
| Scene 상태 | Working Current, Candidate, 등록된 실행 Package | Export의 `authored_scene.json`, `scene.json`, `scene.xml`, `scene.usda` | **사용자가 선택한 실행 Revision을 명확히 해야 함.** 편집 상태와 실행 Package는 같지 않음. 엔진별 파일은 파생 형식 |
| 모델 Runtime·Provider | Workspace `runtime/reconstruction.yaml`의 기본값 + Project/명시 설정 | Candidate 최초 config, review-config, Stage/Worker attempt의 설정·SHA | resolver가 존재함. 실제 적용값과 각 키의 출처를 보여주는 것이 우선. 최초 config는 현재 실행값과 다를 수 있음 |
| Codex 모델·가이드·Memo | 모델/effort는 UI→프로세스 선택; 가이드는 저장소 원본; Memo는 Scene 입력 | job `runtime.json`, 복사 Guide, Memo snapshot, 분석 JSON·모델링 task | 원문/선택과 실행 증거를 구분. 과거 요청의 복사 Guide·Memo를 새 원본처럼 편집하면 안 됨 |
| 엔진·Task 설정 | 등록 Package의 engine config, Recipe의 명시 입력, 등록 Task 모듈 | prepared input, Dataset execution contract, Annotation/DataGen 설정 | 이미 동일성·충돌 검사 존재. 최신 전역 설정으로 과거 기록을 자동 치환하지 말 것 |
| 원본 RGB·Capture·Model Reference | Scene Evidence의 역할·SHA·scene state | sandbox 입력 사본, Crop/Mask/Depth, 제작 기록 이미지 | 역할과 촬영 상태가 다른 입력은 합치지 않음. Crop·생성 RGB·Depth는 원본과 다른 파생 자료 |
| Dataset·Curation·변환 | Native 원본과 identity; Curation은 원본 선택 참조 | Resume segment, 공식 LeRobot Parquet/영상, `workbench.json` | **무조건 전체 복제하는 구조가 아님.** Curation은 metadata-only, Resume/변환 영상은 기본 하드링크 경로가 있음 |
| Policy·Checkpoint·Cache | 명시 Policy/Checkpoint + Dataset identity; Stage별 입력·구현·Runtime SHA | `.resume-input`, 요청/해결/실제 저장 config, Worker Cache·실패 기록 | Checkpoint의 세 설정은 의미가 다름. Cache와 실행 이력의 보존·정리 정책은 원본 선택 통합과 분리 |

## 먼저 정리할 실제 경계

### 1. Robot Rig와 Device 모델이 아직 같은 선택에서 나오지 않는다

`pickplace-new/project.yaml`은 `../../robot_rigs/so101_with_camera/rig.yaml`을 선택한다. 그러나 세 Project가 공유하는 Device의 `robot_model`은 `pickplace-colorblock`의 **기존 `scene-v8-native` Export 아래 URDF**다. `pickplace-colorblock`의 Working Scene도 별도 `so101_sim.urdf`를 사용한다. 따라서 ‘모든 로봇 소비자가 지금 robot_rigs에서 직접 읽는다’는 설명은 맞지 않는다.

Scene Prepare의 Rig 선택은 Project metadata를 바꾸며 기존 Candidate를 바꾸지 않는다. Reconstruction은 선택한 Rig를 Candidate에 명시 import한다. Source 실행은 그와 별도로 **등록된 Package의 모델/엔진 binding**을 선택하고 Device 입력을 결합한다. 이 연결을 경로 하나로 몰래 바꿀 수 없는 이유는 Precision과 Mapping이 모델 SHA·좌표계에 묶이기 때문이다. 새 카메라 고정 링크가 붙은 URDF라도 호환성 확인 없이 기존 실측 매핑을 재지정하면 안 된다. [Rig 선택](../../robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py#L42), [Reconstruction import](../../real2sim_builder/src/real2sim_builder/automation.py#L33), [Source 입력 선택](../../robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py#L124), [실제 Device](../../workbench_runs/devices/so101-pickplace/capture.yaml#L8)

개선 방향은 **새 제작용 로봇의 선택은 공용 Rig로 모으고, 각 소비자가 선택한 모델 SHA와 호환 Mapping을 기존 준비 단계에서 대조하는 것**이다. MuJoCo/Isaac에는 그 Rig에서 만들어 검증한 엔진별 binding을 전달하고, 과거 Capture·Package는 당시 모델을 계속 사용해야 한다. 자세한 기존 경로는 [Robot 모델 저장 설명](../robot-model-storage.md)을 따른다. 이번에 모델을 재지정하지 않았다.

### 2. 공유 Device/Precision 변경이 다른 Scene의 다음 실행에 전파될 수 있다

Project 바인딩은 `capture.yaml` 자체 SHA를 확인한다. 하위 Camera/SDK/Precision 파일은 실행 준비 때 개별 고정한다. 따라서 같은 recipe SHA가 같은 하위 설정을 영구 의미하지 않는다. 준비 후 입력 변경은 기존 `verify_prepared_inputs`가 차단하므로, 실행 도중 무검사로 바뀐다는 주장과는 구분한다. [Device 바인딩](../../robot_learning_workbench/src/robot_learning_workbench/robot/registration.py#L40), [전이 입력 고정](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L407), [실행 전 재확인](../../robot_learning_workbench/src/robot_learning_workbench/recipe.py#L561)

현재 `save_profile`은 같은 선택 파일 덮어쓰기라면 기존 Device 경로를 유지하고, Save As 등으로 경로가 달라지면 새 Device 구성을 만든 뒤 **이전 Device 구성을 공유한 Project들을 자동 rebind**할 수 있다. ‘지금 연 Scene 하나의 저장’으로만 이해하면 영향 범위를 오해한다. 이전 Precision history는 남고, 게시된 Capture/Package를 찾아 갱신하지는 않는다. [저장·history](../../robot_learning_workbench/src/robot_learning_workbench/robot/precision_storage.py#L18), [공유 Project rebind](../../robot_learning_workbench/src/robot_learning_workbench/robot/precision_storage.py#L47)

우선 기존 저장 화면에서 공유 Project와 반영 범위를 설명하고, 이후 새 보정 Revision을 누가 채택할지 명시하는 정책을 정하는 편이 적절하다. 현재 follower/leader의 SDK→Precision SHA는 일치하며, 이번 조사에서 잘못된 보정을 재현한 것은 아니다.

### 3. Camera라는 이름으로 다른 역할의 자료가 흩어져 있다

Device `cameras.json`은 USB stream·해상도·fps다. Capture의 `calibration/cameras.json`은 K·왜곡·Mount·출처다. Scene/Package의 Camera는 해당 Revision의 World/FK 정합까지 포함한다. Camera 하우징 USDA는 이 중 어느 광학 보정도 대신하지 않는다. 같은 `side`/`wrist`라는 이름만으로 모든 자료가 동일 센서·렌즈·Mount라고 볼 수 없다. [stream 소비자](../../robot_learning_workbench/src/robot_learning_workbench/robot/session_devices.py#L59), [Camera signature](../../real2sim_builder/src/real2sim_builder/scene.py#L45), [등록 관측의 SHA 결합](../../real2sim_builder/src/real2sim_builder/observations.py#L81)

현재 코드에서 USB identity와 광학/Mount 보정 identity를 직접 대조하는 연결은 조사한 경로에서 확인하지 못했다. 이것은 검사 경계의 개선 후보이며 실제 오연결을 실행 재현했다는 뜻은 아니다. Working·후보·Export의 K 차이는 Revision별 정합 결과로 확인했고, 그 차이 자체를 중복 권위 결함으로 분류하지 않았다. 공유할 대상은 **물리 센서·촬영 mode에 대응하는 렌즈 보정과 명시 Mount Revision**, Scene에 남길 대상은 **World 배치·정합 결과**다. [상세 Camera 조사](shared-resource-config-findings.md#3-camera라는-이름-아래-서로-다른-다섯-자원이-있다)

### 4. Library에 있는 Object와 Scene에 실제 배치된 Object는 별도다

Object Library Reader는 공용 root와 Scene-local 등록 root를 함께 찾는다. 이번 실물에는 후자의 manifest가 없으므로, 현재 같은 Asset Version 두 개가 양쪽에서 경쟁하는 사례를 발견한 것은 아니다. 공용 등록은 source fingerprint/content SHA로 같은 등록을 재사용하고, Scene Instance는 Library 파일을 직접 참조한다. [두 root 검색](../../real2sim_builder/src/real2sim_builder/object_assets.py#L26), [중복 등록 재사용](../../real2sim_builder/src/real2sim_builder/object_assets.py#L208), [Instance 참조](../../real2sim_builder/src/real2sim_builder/object_assets.py#L360)

반면 현재 `pickplace-colorblock/working/current_scene.yaml`의 `object_asset` 바인딩은 **0개**다. 같은 이름의 컵·블록이 Library에 있어도 이 Scene의 Object가 자동으로 그 Asset을 사용하는 것은 아니다. 기존 import/Scene geometry를 유지한 상태일 수 있으므로, 앞으로 같은 Object를 재사용하려면 ID·Version·manifest SHA를 명시 선택해야 한다. 기존 Local Asset을 공용 Library로 게시하는 API도 옛 Scene 참조를 자동 변경하지 않는다. [명시 게시](../../real2sim_builder/src/real2sim_builder/object_assets.py#L334), [UI의 명시 assign/instantiate](../../real2sim_builder/src/real2sim_builder/asset_view.py#L41)

Visual·Collision·Texture를 각각 다른 최신 자산으로 선택하게 하지 말고 동일 Asset Version의 묶음으로 유지하는 것이 맞다. Preview는 검증한 USDA를 임시 폴더에서 OBJ/PNG로 변환한 뒤 메모리에 읽는다. 별도의 영구 Viewer 원본 저장소를 만드는 구조는 아니다. [Preview 변환](../../real2sim_builder/src/real2sim_builder/asset_view.py#L15)

### 5. 편집 중 Scene과 실제 시뮬레이션 Scene이 다른 Revision일 수 있다

Working Current는 승인된 편집 상태, Candidate는 제안 작업, Export는 고정 Package다. 현재 Source는 선택 Project의 해당 엔진에 **마지막으로 등록된 실행 Package**를 사용하며, 깨진 최신 Package에서 과거 것으로 몰래 fallback하지 않는다. 따라서 Library나 Current를 수정한 것만으로 기존 MuJoCo/Isaac 실행 Package가 갱신되지 않는다. Export 폴더 10개와 등록 Package 7개의 차이도 모든 폴더가 실행 대상으로 등록되는 계약이 아니므로 그 자체로 결함은 아니다. [Current 저장](../../real2sim_builder/src/real2sim_builder/project.py#L202), [Candidate promote](../../real2sim_builder/src/real2sim_builder/candidate.py#L237), [실행 Package 선택](../../robot_learning_workbench/src/robot_learning_workbench/scene_preparation.py#L124)

이 경계는 없애기보다 기존 UI에서 **편집 Candidate / Current / 선택 실행 Package의 ID·Revision·SHA**를 구분해 설명해야 한다. 변경을 채택할 때 새 Package를 만들고 명시 등록하는 기존 경로를 유지한다.

### 6. Runtime 설정은 여러 파일이 있지만 우선순위가 있다

SimFoundry는 명시 config 또는 Project 입력을 선택한 후 Workspace의 `runtimes`를 기본값으로 재귀 병합한다. Project/명시값이 우선한다. UI는 해당 Candidate의 `review-config.yaml`이 있으면 이를 선택해 CLI에 전달할 수 있다. 반면 `reconstruction-config.yaml`은 최초에만 기록되고 현재 설정의 유일한 권위가 아니다. 실제 Stage attempt의 config/runtime identity가 해당 실행 근거다. [실행 설정 선택](../../real2sim_builder/src/real2sim_builder/automation.py#L327), [Workspace 병합](../../real2sim_builder/src/real2sim_builder/stage_runtime.py#L40), [후보 review 설정](../../real2sim_builder/src/real2sim_builder/ui_reconstruction.py#L25), [최초 설정 저장](../../real2sim_builder/src/real2sim_builder/automation.py#L42)

현재 Workspace와 `pickplace-new/auto_001` 최초 기록의 `runtimes`는 YAML 데이터로 일치했다. 기존 refit 기록에는 옛 `runtime_sources`·`sam/geometry` 필드가 남지만 현재 소비자가 확인되지 않았으며, 제거된 MASt3R 실행이 살아 있다는 근거로 삼지 않았다. Refit은 Workspace 병합 전 별도 경로로 분기한다. [상세 Runtime 조사](shared-resource-config-findings.md#4-runtime-현재-기본값명시-override최초-실행-기록실제-stage-기록의-역할이-다르다)

정리할 것은 우선순위를 새로 여러 개 만드는 일이 아니라 **기존 resolver가 결정한 실제 경로·SHA·값의 출처를 한 번에 보여주는 일**이다. 환경별 설치 위치는 Workspace Runtime에 두고 각 실행에는 그 선택을 고정한다. 인증은 파일 통합 대상이 아니다.

## 복사본이 있어도 유지해야 할 것

### Native 형식과 엔진 파생물

Object USDA·Blender 작업 파일·OBJ/Texture·Collision은 역할이 다르다. Export의 `scene.xml`과 `scene.usda`도 같은 Scene을 MuJoCo/Isaac용으로 만든 형식이다. 엔진이 항상 URDF 하나를 직접 로드하도록 바꾸면 기존 material·collision·calibration binding을 잃을 수 있다. [엔진별 Export](../../real2sim_builder/src/real2sim_builder/export.py#L382)

Package의 native dependency는 상대 참조를 유지하며 복사하고, 하나의 Export 안에서는 `copied`로 재사용한다. 다른 Export 사이에서는 별도 파일이 생길 수 있다. 이미 Export 안의 자산을 다시 source로 사용하면 그 내부 디렉터리 구조까지 다음 Package에 포함돼 경로가 길어진다. 실제로 동일한 약 23.24MB Robot USD가 10개 경로/10 inode에 존재했고, 일부는 `exports/scene-v8-native/assets/...`가 다시 중첩돼 있다. 과거 경로 이름에 다른 프로젝트 이름이 남은 것과 현재 외부 checkout을 읽는 실행 의존성은 구분했다. [native 복사·목적지 내 재사용](../../real2sim_builder/src/real2sim_builder/export.py#L89), [Package 소유 closure](../../real2sim_builder/src/real2sim_builder/export.py#L335)

조사 범위의 native model/image에서 **완전히 같은 bytes의 중복 그룹 725개**를 찾았다. 그룹마다 inode 중복을 제외한 추가 파일 payload의 논리 크기를 합하면 **3,087,665,662B**다. 이는 삭제 가능한 용량이나 실제 회수 공간의 측정이 아니다. Package closure·제작 증거·별도 소유권이 필요하고, 파일시스템의 공유 block 여부도 전수 확인하지 않았다. 이번에 삭제 후보로 지정하거나 정리하지 않았다.

### Capture와 하드링크

Capture의 `share_model`은 현재 모델과 상대 Mesh dependency에 `os.link`를 사용한다. Capture마다 URDF가 보이는 것이 새 모델 제작을 뜻하지 않는다. Native Dataset Resume와 일부 영상 재사용도 기본 하드링크다. 단, 하드링크는 쓰기 방지나 Copy-on-write가 아니므로 직접 원본 파일을 고쳐도 안전한 독립 백업이라고 이해하면 안 된다. 기존 SHA 검사는 변경을 검출하며 원천 쓰기 방지를 제공하는 것은 아니다. [Capture 모델 공유](../../robot_learning_workbench/src/robot_learning_workbench/robot/capture.py#L303), [Dataset 공유 계약](../../robot_learning_workbench/src/robot_learning_workbench/data/native.py#L196), [Resume 새 실행 소유권](../../robot_learning_workbench/src/robot_learning_workbench/data/native.py#L463)

### 원본 입력·Memo·AI 실행 기록

Scene의 현재 Memo는 `input/scene_memo.txt`이고 과거 실행에는 당시 문장/SHA를 남긴다. 분석 JSON·Constraint·Task는 그 원문을 해석한 결과다. 가이드도 저장소의 신뢰 원본을 sandbox로 복사한다. 격리한 Codex 실행이 실시간으로 사용자 입력·가이드를 읽어 달라지는 일을 막고 재현할 목적이므로 복사본을 현재 원문처럼 갱신해서는 안 된다. Scene Photo, Model Reference, Side/Wrist Capture는 역할과 layout identity가 달라 같은 이미지 bytes여도 모든 소비자에 무조건 합치지 않는다. [Memo 원본/저장](../../real2sim_builder/src/real2sim_builder/evidence.py#L552), [모델링 입력 동결](../../real2sim_builder/src/real2sim_builder/authoring.py#L1265), [Stage 입력·Worker 재사용 검증](../../real2sim_builder/src/real2sim_builder/automation.py#L78)

### Dataset·Checkpoint·실행 설정

Curation은 원본 Dataset identity·상대 경로·Episode/Frame 선택만 저장한다. 현재 6개 기록도 이 형식이다. 공식 LeRobot 변환은 Parquet 행·index를 만들고 영상은 기본 공유 경로를 사용한다. Dataset을 여러 단계에서 본다는 이유로 매번 전체 영상이 새로 복사된다고 볼 수 없다. [선택 참조 저장](../../robot_learning_workbench/src/robot_learning_workbench/data/curation.py#L38), [공식 Dataset 변환](../../robot_learning_workbench/src/robot_learning_workbench/data/lerobot.py#L405)

엔진 설정은 Recipe·prepared input·Dataset 실행 계약에 반복 기록되지만, replay/datagen에서 충돌하는 설정을 검사한다. 학습의 요청 config·default를 해결한 config·실제 Checkpoint가 저장한 config도 다른 의미다. Resume는 Dataset identity와 설정을 대조하고 JSON을 복사하며 나머지 Checkpoint 파일은 하드링크로 준비한다. 이 기록을 최신 config 하나로 바꾸는 것은 Resume/재현 계약을 깨뜨린다. 이번 지정 root에는 해당 실제 Checkpoint가 없으므로 이 판단은 코드 경계 확인이다. [Replay/DataGen 설정](../../robot_learning_workbench/src/robot_learning_workbench/data/recording.py#L99), [Resume 확인·입력 고정](../../robot_learning_workbench/src/robot_learning_workbench/learning/train.py#L40), [요청/실제 Checkpoint 대조](../../robot_learning_workbench/src/robot_learning_workbench/learning/policy.py#L152)

## 통합을 진행한다면 사용할 기준과 순서

목표는 **자원 종류별 제작 기준과 명시 Version 선택을 하나로 하고, 각 실행은 선택한 버전의 고정 기록을 사용하는 것**이다. 모든 소비자가 변경 가능한 `latest` 파일을 읽게 하는 방식은 피한다. 기존 Project·Candidate·Library·Device·Recipe·Package의 소유권을 유지하고 별도의 전역 Manager/DB를 추가할 필요는 없다.

| 순서 | 기존 소유 모듈에서 할 일 | 보존·검증할 경계 |
|---|---|---|
| 1. 실행 선택을 확인 가능하게 만들기 | `scene_preparation`, `registration`, `recipe`, `stage_runtime`이 이미 해결한 Robot/Device/Calibration/Camera/Package/Runtime의 경로·ID·SHA·출처를 기존 화면/manifest에 모음 | 현재 선택과 기록된 Snapshot을 구분. 새 resolver가 기존 것과 별도로 다른 선택을 하지 않도록 함 |
| 2. Robot·Device 연결 | 공용 Rig를 새 제작의 기본 선택으로 사용하고 Device/FK/Precision/엔진 binding과 모델 identity를 대조 | 새 Rig와 과거 보정이 맞지 않으면 명시적인 호환성 검토. 오래된 Capture·실측·Package는 재작성하지 않음 |
| 3. Camera·보정 Revision | 기존 Camera/Device 저장에 물리 센서·mode·Mount와 보정 identity 연결, 공유 Precision 저장의 반영 범위를 명시 | 다른 Scene에 대한 자동 영향과 기존 단일 실행 입력 불변 검사를 모두 검증. World 정합은 Scene 소유 |
| 4. Object 참조 | 공용 Library의 ID·Version·manifest SHA로 새 Instance를 명시 생성/연결; 실제 사용하는 자산과 Library 목록의 관계를 표시 | 원래 Object pose·부분 실측·Collision·Texture 유지. 같은 이름만으로 기존 Scene Object를 재지정하지 않음 |
| 5. 실행 Revision/설정 출처 | Current/Candidate/선택 Package와 실제 Runtime override 출처를 기존 제작/실행 기록에서 구분 | 새 채택은 새 Package/등록 경로. 옛 review-config·attempt 기록을 현재값으로 덮어쓰지 않음 |
| 6. 저장량 최적화 | 그 뒤 `export.copy_native_asset`·기존 공유 함수를 기준으로 새 산출물의 dependency layout/재사용을 검토 | 독립 이동·변조 검출·closure·hardlink 쓰기 위험을 시험한 뒤 결정. 기존 Package/Capture를 삭제·재배치하는 작업은 별도 |

후속 구현 검증은 Synthetic Producer→Consumer로 Rig 선택→Candidate→새 Package→MuJoCo/Isaac binding 해석, 같은 Device를 공유한 두 Project의 보정 저장 범위, Camera identity mismatch, Library Version 변경과 기존 Package 불변, Runtime override 출처, Dataset/Checkpoint 재현을 나누는 것이 적절하다. 이번 문서 작업에서 모델/하드웨어 정확도나 엔진 가동 성공을 주장하지 않는다.

## 조사 산출물과 보존

추가 문서는 이 보고서와 [Device·Camera·Runtime 보충 조사](shared-resource-config-findings.md) 두 개다. Git 제외 진단 폴더에는 `git-before.json`, `preservation-before.json`, `source-scan.json`, `resource-inventory.json`, 조사 스크립트·로그를 남겼다. 이 자료는 제품 Runtime 의존성이 아니다.

최종 대조에서 기존 소스/문서 **572개 SHA 변경0·누락0**, 보호 root **18,566개 파일 SHA/크기 변경0·누락0·신규0**을 확인했다. 소스/문서 범위의 신규 파일은 위 두 보고서뿐이다. 로컬 근거 링크 **125개**의 대상·행 번호·문서 anchor 확인과 `git diff --check`가 통과했고, HEAD·브랜치·Git Index를 보존했다. 결과는 같은 폴더의 `completion-check.json`, `preservation-after.json`, `document-check.json`이다. 전체 디스크·외부 모델·환경의 전수 보존 검사라는 뜻은 아니다.
