# 작업판 크기 등록 실패 — 부분 Depth와 다중 시점 3D 복원 진단

2026-11-09. 대상은 원래 프로젝트의 `auto-version`, Candidate `auto_mast3r_colmap`이다. 현재 로컬 소스와 실제 저장 결과를 기준으로 작성했다. **문제는 아직 해결되지 않았으며, 이 문서는 증상·확인된 사실·미확정 원인·다음 확인 사항을 구분한 기록이다.**

## 1. 현재 상황

사진에서 작업판을 선택한 **2D Mask는 육안상 대체로 올바르다.** 그러나 Mask 안의 모든 픽셀에 유효한 3D Depth가 생성된 것은 아니다. 일부 사진은 3D 점이 드문드문 남아 있으며, 이를 합쳐 실제 크기를 맞추는 단계에서 실패한다.

현재 오류:

```text
Observed support aspect ratio disagrees with measurements; check mask/occlusion
```

이 문구만으로 Mask가 잘못됐다고 판단하면 안 된다. 현재 계산은 가시 3D 점의 범위를 검사하므로, **부분 Depth·이상점·Camera/Depth 추정 또는 시점 간 정렬 문제**도 같은 오류로 나타날 수 있다.

- Candidate: `OPEN`, 기존 작업을 보존한 상태다.
- Metric 등록: `UNRESOLVED`, 실제 미터 단위 Photo 점군 생성은 미완료다.
- 작업판 자산: 수정된 `workspace_paper/v002`가 Candidate에 적용돼 있다.
- 새 `auto-version`의 최종 Photo 렌더 정합·Side/Wrist 공동 정합·실행용 승인 Export: **미완료**다.
- 기존 `pickplace-colorblock` 실행 Package와 그 렌더 시험은 별도이며, 새 `auto-version` 완성을 증명하지 않는다.

## 2. 사용자가 확인한 실제 입력

### 작업판 실측 정정

컵 두 개가 나란히 놓인 방향을 작업판 **로컬 Y**, 그에 수직인 방향을 로컬 X로 정의했다. 이것을 미확인 World/Robot 축과 같다고 가정하지 않는다.

| 구분 | X | Y | 근거 |
|---|---:|---:|---|
| 검은 선 바깥 경계 | 147mm | 151mm | 사용자 실측 |
| 검은 선 폭 | 2mm | 2mm | 사용자 실측 |
| 안쪽 흰 영역 | 143mm | 147mm | 바깥 치수에서 양쪽 선 폭을 뺀 계산 |

기존의 150×150mm 정사각형 설명은 사용자 요청으로 정정했다. 현재 [Scene Memo](../workbench_runs/scenes/auto-version/input/scene_memo.txt)의 SHA는 `597fff395798cf7d2452817f5fc8a95f392c96ba320fd5a55e9af2497782dcac`다. 종이 두께는 여전히 미측정이며, 자산의 렌더용 0.15mm 두께는 estimated다.

실측과 검은 선 폭은 기존 Blender 경로로 새 `v002`에 반영했다. `v001`과 다른 Object·Robot/FK·기존 Export는 보존했다. **모델의 치수 수정과, 관측 3D를 실제 크기로 등록하는 문제는 별개다.**

### 촬영 카메라

사용자는 Scene 사진 8장을 모두 **Samsung Galaxy A35 5G 후면 기본 1배 광각, 같은 렌즈/배율**로 촬영했다고 확인했다.

- 저장된 JPEG 8장은 모두 4080×3060이다.
- 현재 파일에는 Make/Model/FocalLength/FNumber/Lens/배율을 확인할 EXIF가 없다. 기종·렌즈 일치는 사용자 확인이며 EXIF나 Calibration으로 검증한 값은 아니다.
- 현재 실행 결과의 `physical_camera_id`는 8장 모두 `null`이다. 기존 복원에서는 사진마다 K/왜곡을 따로 추정했다.
- **사용자 확인을 반영한 공유 렌즈 설정 및 재복원은 아직 실행하지 않았다.** 문서 작성 전에 해당 작업을 조사하던 중, 사용자가 사진 2·8의 시각화와 문제 정리를 요청했다.
- 모델명·명목 화각만으로 K나 왜곡 계수를 실측값으로 만들지 않는다. 같은 렌즈로 처리하더라도 각 사진의 촬영 위치/회전은 독립적이다.

## 3. Mask와 3D 점군은 다르다

크기 등록에 사용된 작업판 Mask는 사진 **1·2·3·8**에 있다. 사진 2는 그리퍼가 가린 부분이 제외돼 있다. 나머지 사진에 Mask가 없다는 사실과, SfM Camera 등록 여부는 별도다.

[원본·Mask·겹쳐 보기](../workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap/fitting/workspace-mask-review/workspace-masks.png)

![작업판 Mask 비교](../workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap/fitting/workspace-mask-review/workspace-masks.png)

사진 2·8의 오른쪽 그림은 **가용 3D 점을 추정 평면에 투영한 결과**다. 초록 점은 실제 점군, 주황 사각형은 그 점들을 감싸는 최소 면적 사각형이다. 흰 점선은 실측 비율을 비교하기 위한 참고 도형으로, 관측된 종이 경계나 보정 결과가 아니다.

![사진 2·8의 원본과 부분 점군](../workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap/fitting/workspace-mask-review/workspace-2-8-3d.png)

**이전 설명 정정:** “사진 2의 작업판은 1.47배, 사진 8의 작업판은 1.62배로 늘어났다”는 표현은 부정확했다. 정확히는 **남아 있는 3D 점들을 감싼 사각형의 긴 변/짧은 변 비율**이다. 사진 픽셀의 비율도, 실제 종이 전체의 크기를 정확히 복원했다는 값도 아니다. 부분 점군이므로 이 수치만으로 작업판의 실제 변형이나 렌즈 왜곡을 단정할 수 없다.

## 4. 실제 수치 진단

동일한 원 RGB·Mask·Depth NPZ를 고정하고 기존 `object_points()`와 `metric_plane()`를 사용했다. 실제 작업판의 외곽 긴 변/짧은 변은 **151/147 ≈ 1.027211**이다.

| 사진 | 가용 3D 점 | Mask 내 유효 Depth | 점군 범위 비율 | 평면 비평탄 지표 | 사진별 기존 검사 |
|---|---:|---:|---:|---:|---|
| 1 | 1,031 | 8.77% | 1.04886 | 0.01911 | ESTIMATED |
| 2 | 4,406 | 40.06% | 1.47227 | 0.12025 | UNRESOLVED |
| 3 | 9,162 | 48.67% | 1.03631 | 0.02318 | ESTIMATED |
| 8 | 551 | 5.99% | 1.61988 | 0.01349 | UNRESOLVED |

「유효 Depth」는 처리 해상도로 옮긴 Mask 픽셀 중 양수·유한 Depth가 있는 비율이다. 원 사진에서 작업판이 얼마나 보이는지나 모델의 신뢰도 퍼센트를 의미하지 않는다. 비평탄 지표는 중심화 점군 SVD의 `s[2]/s[1]`이며 기존 허용 기준은 0.08이다.

- 사진 2는 평면 검사도 실패한다. Mask가 평평한 종이를 골랐어도, 복원된 점들은 같은 정도로 평평하지 않다.
- 사진 8은 점이 적고 조각난 상태다. 범위를 종이 전체의 치수로 해석하기 어렵다.
- 사진 1은 비율 검사는 통과하지만 Depth 비율이 8.77%뿐이다. **비율 통과만으로 완전한 관측이라고 볼 수 없다.**
- 네 사진의 점 15,150개를 합치면 범위 비율은 1.457866이다. 새 실측을 사용해도 두 축 scale 차이 지표가 약34.66%여서 기존 12% 기준을 초과한다.
- 안쪽 흰 영역143×147mm로 계산한 진단도 약34.59%로 실패했다. 외곽/내곽 치수의 혼동만으로 현재 실패를 설명할 수 없다.

개별 기존 검사를 통과한 사진1·3만 사후 선택하면 비율1.03643, 추정 scale≈0.07409가 계산된다. **이는 진단용 결과이며 Production 등록에 적용하지 않았다.** 결과가 맞는 사진만 선택하면 편향된 성공 처리가 될 수 있고, 사진1의 낮은 Depth 범위도 해결되지 않는다.

### 렌즈 왜곡 가설 비교

현재 Backend는 왜곡을 무시하지 않는다. 미보정 Camera에 대해 COLMAP의 `SIMPLE_RADIAL` 모델로 focal과 k1을 추정하고, Depth 재투영 및 optical ray 역투영에 왜곡을 전달한다.

| 동일 점군 생성 조건 | 합친 점군 범위 비율 | 실제 크기 등록 |
|---|---:|---|
| 현재 추정 왜곡 적용 | 1.457866 | UNRESOLVED |
| 왜곡 계수0 가정, 나머지 동일 | 1.449218 | UNRESOLVED |

이 대조에서 왜곡0은 **원인 분리용 가정**이며 실제 Camera에 적용하지 않았다. 현재 추정 계수의 유무만으로 실패가 해결되지 않는다는 뜻이지, 실제 렌즈나 K 추정이 정확하다는 증거는 아니다. 현재 방식의 렌즈 모델 적합성·초점거리 오차·휴대폰 JPEG의 보정 영향은 미검증이다.

## 5. 코드에서 어디서 막히는가

```text
Scene Photos → SAM Mask → MASt3R → COLMAP Pose/K/왜곡
  → 상대 optical-Z Depth
  → observations.predict_views()
      → object_points(): Mask 안의 유효 Depth만 3D로 역투영
      → 사진별 점을 같은 상대 좌표계로 변환
      → np.concatenate(samples): 가용 점을 합침
      → metric_plane(): 평면·점군 범위·실측 치수 비교
      → UNRESOLVED
  → metric World 점군/최종 Scene 정합으로 진행하지 못함
```

| 위치 | 책임 / 현재 확인 사항 |
|---|---|
| [sfm.py:304](../real2sim_builder/src/real2sim_builder/sfm.py#L304), `lens_group()` | 명시 물리 렌즈 ID와 해상도·EXIF/crop 조건으로 K 공유 여부 결정. 현재 결과는 물리 렌즈 ID 미설정 |
| [sfm.py:310](../real2sim_builder/src/real2sim_builder/sfm.py#L310), `colmap_worker()` | 미보정 렌즈는 SIMPLE_RADIAL, 보호된 렌즈는 기존 명시 Calibration 사용 |
| [inference.py:37](../real2sim_builder/src/real2sim_builder/inference.py#L37), `object_points()` | 원 Mask와 처리 픽셀 변환, 유효 Depth·confidence, optical ray/왜곡으로 가시점 생성. 없는 Depth는 만들지 않음 |
| [observations.py:215](../real2sim_builder/src/real2sim_builder/observations.py#L215), `predict_views()` | 등록 Camera/선택 Depth Batch의 점들을 모아 실제 크기 등록 시도 |
| [observations.py:331](../real2sim_builder/src/real2sim_builder/observations.py#L331) | 사진별 관측을 합친 후 `metric_plane(np.concatenate(samples), ...)` 호출 |
| [registration.py:212](../real2sim_builder/src/real2sim_builder/calibration/registration.py#L212), `metric_plane()` | SVD 평면 검사, 투영 Convex Hull의 최소 면적 사각형, 두 축 scale 차이 검사 |

현재 `predict_views()`의 이 경로에는 사진별 Depth 가시 범위·개별 평면 품질을 판정한 뒤 합치는 단계가 없다. `metric_plane()`은 불완전한 사각형을 완전한 실측으로 처리하지 않으려는 함수이지만, **현재 입력 계약에는 해당 점군이 실제 사각형 경계를 충분히 관측했는지 증명하는 정보가 없다.** 조각난 점군에서도 사각형 범위는 계산되므로, 비율 실패뿐 아니라 우연한 비율 통과도 주의해야 한다.

확인된 것은 **부분/저품질 Depth의 범위를 실제 작업판 범위와 직접 비교하는 취약한 처리와 현재 실패 재현**이다. 저품질 Depth를 만든 근본 원인이 Camera, MASt3R Pointmap, Dense/Sparse 정렬, 가림 중 무엇인지는 아직 확정하지 않았다.

## 6. 다음에 확인·수정할 사항

아래는 후속 작업이며 구현·검증 완료 목록이 아니다.

1. 사용자 확인을 근거로8장의 물리 렌즈 Identity를 연결한다. 해상도/crop 조건을 확인하고 K/왜곡을 공유하되 사진별 Pose는 따로 추정한다. 기존 결과를 보존하고 새 캐시에서 비교한다.
2. 사진별 Mask 경계와 실제 Depth 유효 영역을 비교한다. 작업판 전체 경계가 확보됐는지, 가림·깊이 구멍·이상점인지 구분한다. 단순 점 개수만으로 완전성을 결정하지 않는다.
3. 전체 점군을 합치기 전에 개별 평면·Camera 간 재투영·3D 일관성을 확인한다. 가능한 경우 가시 경계/Corner와 실측 직사각형을 활용하는 기존 수치 기능을 검토한다.
4. 부분 관측은 부분 관측으로 유지한다. 근거 없는 면 채우기, 결과 비율이 맞는 사진만 선택하기, 실제 치수나 허용 오차 변경으로 통과시키지 않는다.
5. 수정 후 기존 실패 입력에서 metric 근거가 생기는지 확인하고, 그다음 실제 Photo 렌더 정합·Side/Wrist 공동 정합으로 진행한다. 단순 검사 통과를 Camera 정확도·물리 인증·완성 Scene으로 보고하지 않는다.

과거 원격 Codex 분석의 사용량 실패는 별도 이력이다. 현재 문서의 수치 진단은 저장 결과를 읽어 수행했으며 사용량과 관계없이 같은 실패를 재현했다. 과거 계정 상태를 현재 계정 상태라고 보고하지 않는다.

## 7. 재현과 증거

작업 루트: `/home/hyeonhee/imitation_learnig_project`

Candidate: `workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap`

| 자료 | 내용 |
|---|---|
| [pipeline-camera-distortion-diagnostic.json](../workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap/pipeline-camera-distortion-diagnostic.json) | 사진별 비율·가용 Depth·K/k1·왜곡0 대조·사후 부분집합 진단 |
| [pipeline-workspace-measurement.json](../workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap/pipeline-workspace-measurement.json) | 실측 정정 전/후 및 안쪽 치수 대조, metric 실패 |
| [workspace-measurement-correction.json](../workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap/workspace-measurement-correction.json) | 사용자 정정 근거·새 메모 SHA·v002 적용 이력 |
| [workspace-measurement-verification.json](../workbench_runs/scenes/auto-version/scratch/agent/auto_mast3r_colmap/workspace-measurement-verification.json) | 외곽/내측/선 폭·다른 Object/Robot 보존·메모 재열기 검증 |
| `.cache/inference/results.json` | 현재 실제 SAM Mask 및 MASt3R/COLMAP 결과·Depth Batch 참조 |
| `fitting/workspace-mask-review/` | Mask 비교 PNG, 사진2·8의 3D 시각화 PNG와 JSON |

로컬 재현 명령:

```bash
cd /home/hyeonhee/imitation_learnig_project
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=scene_contract/src:real2sim_builder/src:robot_learning_workbench/src \
/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python \
  /home/hyeonhee/real2sim-integration-backups/local-20261108-173502/storage-migration/diagnose_workspace_camera.py
```

이 도구는 기존 RGB/Mask/NPZ SHA를 확인하고 Camera·Scene·원본을 바꾸지 않은 채 진단 JSON만 갱신한다. 모델 추론·GPU 복원·실물 구동을 하지 않는다. 관측 Data/Cache와 외부 복구 도구는 Git 제외 로컬 자료이므로 저장소만 내려받으면 링크·재현 입력이 없을 수 있다. 실제 사용자 이미지를 문서와 함께 Git에 복사하지 않았다.

이번 요청은 문서 정리만 수행했다. 제품 코드·촬영 입력·Calibration·Candidate Scene·자산·Export를 수정하지 않았고 테스트를 새로 실행하지 않았다. 기존 전체1,616개 통과는 앞선 소스 회귀 결과이며, 이 실제 Scene의 metric 실패가 해결됐다는 의미는 아니다. Commit/Push는 하지 않았다.
