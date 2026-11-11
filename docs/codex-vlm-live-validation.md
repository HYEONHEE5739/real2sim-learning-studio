# MASt3R 잔여 파일 정리 및 Codex VLM 실제 검증

2026-11-11. `feat/simfoundry-style-reconstruction`, HEAD `4ffcac002661710571ad0b20a20715b98587a871`. 최신 첨부 지시로 승인된 MASt3R 전용 파일/소스 삭제와 Workspace 설정 이전을 수행했다. 기존 staged/미커밋 구현을 보존한다. 기록은 Git 제외 `workbench_runs/diagnostics/codex_vlm_live_validation/`에 둔다.

**결과: Phase A/B 완료, Phase C/D는 BLOCKED.** 기존 제품 경로의 실제 Codex VLM 요청을1회 시도했으나 900초 안에 최종 JSON이 없어 TIMEOUT으로 종료됐다. 자동 재시도0회이며 실제 이미지 이해·출력 Schema·Stage7 전달 성공을 주장하지 않는다.

## A. 승인된 디스크 정리

| 항목 | 삭제 전 실제 관측 | 결과 |
|---|---|---|
| `workbench_runs/sfm_comparison_20261108/src/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth` | 일반 파일, Symlink 아님, 2,754,910,614B, 할당2,754,916,352B, inode2010349, Hardlink1 | 지정 파일만 unlink, 부재 확인 |
| 같은 `src/mast3r` | 전용 소스285개 파일, 파일 할당 합계11,575,296B, root는 Symlink 아님 | 지정 디렉터리만 삭제, 상위 `src` 보존 |

현재 제품 코드·Runtime 설정·다른 제공 Workspace(`/home/hyeonhee/soarm_isaaclab`)에서 가중치의 활성 참조를 찾지 못했다. `auto-version/input/reconstruction.yaml`의 과거 `geometry` 설정이 참조하지만 현재 Stage2는 `runtimes.da3`를 사용하고 해당 legacy 실행기는 제거된 상태다. 이 과거 설정은 수정하지 않았다. 관측 가능한 프로세스의 command/path/open file/memory map에 일치가 없었다. `/proc` 접근 제한286개 프로세스는 검사 한계로 기록했다. 실행 중인 다른 모델을 종료하지 않았다.

`df -h /`: 사전 관측292G/248G/30G, 삭제 후 **292G/245G/33G**다. 바이트 기준 관측 여유 공간 증가 **2,766,868,480B(약2.58GiB)**다. 관측 사이의 다른 시스템 쓰기를 포함할 수 있으므로 unlink 파일 크기와 정확히 같은 수치라고 단정하지 않는다.

실제 삭제 목록/파일별 크기·inode는 `deletion-preflight.json`, 참조 검사는 `deletion-references.json`, 전후 df/부재는 `deletion-result.json`에 있다. 해당 실험 `REPORT.md`에는 원문 bytes 앞에 삭제/재현 제한 안내만 추가했다. 원래 실험 결과·이미지·로그·측정값은 삭제하지 않았다. MASt3R 실험 직접 재현에는 소스와 가중치를 다시 준비해야 한다.

HF/Conda Cache, DA3/PDA/SAM3.1/FLUX/T5/CLIP/VAE/Bria/SBERT, SimFoundry 소스와 사용자 Scene/Asset/Export는 정리 대상에서 제외했다. 다른 파일·모델 삭제는 0이다.

## B. 실제 Workspace 설정 이전

`workbench_runs/runtime/reconstruction.yaml`을 `workspace-before.yaml`로 백업하고 `workspace.diff`를 남겼다.

- 이전 `runtimes.vlm`: r2s-prior-depth Python, SimFoundry source, `model_options.model: gemini-3.1-pro-preview`.
- 이후 `runtimes.vlm`: **`provider: codex`, `timeout_s: 900`**만 유지.
- 이전 SimFoundry source를 **`runtimes.pose.simfoundry_source`**로 이동. 기존 r2s-cpd Python과 나머지 Pose 설정은 보존.
- DA3/SAM/FLUX/Bria/Pruning/PriorDepth/Blender/Physics/Simulator 등 다른 Runtime dict는 변경 전과 동일함을 검사했다.

변경 전 SHA `29f1147bfe3bf2dcbce67f4286de085af1f1f1b7280c0ce3ea1fea1c7512ec72`, 이후 SHA `02345f185e59b941d182ec131d74c4ebc54464c169b3579b1353be7fa2fdc129`.

실제 `workspace_configuration()`으로 `auto-version`, `pickplace-colorblock`, `pickplace-new`의 Project Override를 병합했다. 세 Scene 모두 Effective VLM이 Codex이고 구형 Gemini key가 다시 주입되지 않았다. Front source와 CPD Python도 유지됐다. Scene Prepare/Auto Reconstruction UI는 변경하지 않았다. 같은 `automation.reconstruct → workspace_configuration` 진입이 이 설치값을 읽으며 전체 Reconstruction은 실행하지 않았다.

## C. 실제 Codex VLM

설치 CLI **0.166.0**, 기존 UI QSettings 선택 **gpt-6.1-sol / high**를 읽어 그대로 사용했다. 기존 Builder Codex Home/로그인과 image Capability를 공식 runtime에서 확인했다. 계정 식별값·토큰·인증 파일 내용은 저장하지 않았고 계정·모델 전환도 하지 않았다. 호스트 진단 Python의 PyQt import가 없어 QSettings의 기존 INI 저장값을 읽었으며 UI/환경을 재설치하지 않았다.

입력은 기존 독립 합성 `workbench_runs/diagnostics/local_runtime_validation/sam/synthetic_cup.png`(768×512)다. 밝은 손잡이 컵과 갈색 수평 지지면이 보인다. 사용자 Scene 이미지와 SHA가 같은 `sam31_test/scene.png`는 사용하지 않았다. 원본 SHA는 `1d50eaa62aeb133d7d0ef4befc9e96ee20230ea29404c0b1d8952fbab1f5ffd6`이며 `live-preflight.json`에도 기록했다.

기존 모듈만 호출하는 `live_harness.py`를 진단 폴더에 두고 `stage_runtime.invoke('vlm') → authoring.run_codex_vlm → codex_cli.execute`로 실행한다. 단독 CLI 성공을 제품 성공으로 바꾸지 않는다. Schema는 기존 `instance_schema(initial=True)` 및 그 안의 `scene_analysis_schema()`다. 원본 이미지 하나·자유 Memo·pixel metadata를 제공하며 K/Pose/실측/Model Reference는 제공하지 않았다.

별도 독립 Synthetic Project/Candidate는 진단 폴더 아래에서 입력·의미 응답의 소유권 검증에만 사용한다. 사용자 Scene pool에는 등록하지 않는다. 첫 준비 과정에서 Memo 상대 경로를 저장소 CWD 기준으로 해석한 Harness 오류를 수정했다. 이때 execute 시도는0회였고, 이미 만든 동일 fixture를 재사용했다. 제품 모델 호출의 재시도가 아니다(`preparation-error.json/log`).

**실행 결과: TIMEOUT / BLOCKED.** `online-budget.json`과 `live-result.json`의 실제 execute 시도는1회, 애플리케이션 재시도는0회다. 전체 호출 시간은 **901.937초**였다.

| 검사 | 실제 결과 |
|---|---|
| 기존 로그인/선택 모델/강도/이미지 Capability | preflight 통과, gpt-6.1-sol / high / CLI0.166.0 |
| 제품 실행 경로 | stage_runtime.invoke → authoring.run_codex_vlm → codex_cli.execute 진입 |
| 입력 이미지 | --image 입력 Manifest1개, 복사본 SHA/768×512 기록. 모델의 실제 이해는 확인 못함 |
| 최종 JSON | 없음 |
| 출력 Schema/컵 식별/Category/Box/관계/치수 검증 | NOT_TESTED — 검증할 최종 응답이 없음 |
| 제품 status.json | FAILED / TIMEOUT |
| 상위 Stage 상태 | NEEDS_RUNTIME. 상위 code는 null이며 별도 제품 status.json에 TIMEOUT이 남음 |
| codex.log | returncode -15, 선택 모델/강도/version만 저장 |
| 완료 Worker Manifest/재사용 Cache | 생성되지 않음. 실패·부분 응답을 완료 자료로 재사용하지 않음 |
| 로컬 종료 | 소유 visual 작업 프로세스 잔존0 확인. 원격 서버의 내부 실행/취소 상태는 확인하지 않음 |

보존된 중간 이벤트에는 thread.started1 / turn.started1과 완료된 command_execution(exit0)이 있었다. 보존 표본에서 명시 인증/Quota error는 관측되지 않았지만 전 구간의 서비스/네트워크 상태를 확정할 수 없다. **최종 응답이 오지 않은 근본 원인은 UNKNOWN**이다. 모델의 이미지 미지원·인증 실패·사용량 소진으로 단정하지 않는다.

호출 전 공식 Runtime의 Usage window 조회값은 `live-preflight.json`에만 보존한다. turn.completed/token usage가 없으므로 소비 토큰/비용은 UNKNOWN이다. CLI 내부 개별 모델 턴/전송 재시도 수를 제품 execute1회와 동일하다고 추정하지 않는다. raw 계정 정보·token·tool transcript는 Project 로그에 저장하지 않았다.

`input_manifest.json`, 신뢰 Guide, sanitized codex.log/status와 진단 결과는 남겼다. `live-event-metadata.json`, `live-tool-metadata.json`은 이벤트 종류/상태만 기록한 표본이다. 완료 Worker Cache를 구성하는 Harness 코드는 성공 이후에만 실행되므로 이번에는 도달하지 않았다. 전체 Stage5 segmentation/removal은 실행하지 않았다.

## D. 실제 응답의 Stage7 전달

**BLOCKED / NOT_TESTED.** Phase C에 성공한 실제 JSON이 없어 `handoff_harness.py`를 실행하지 않았다. Fake 응답이나 중간 agent message를 실제 성공 응답으로 바꿔 넣지 않았다.

`handoff-result.json`에 Stage5 출력 Schema 검증/Stage7 Handoff/Cache 재사용은 미실행, 추가 온라인 호출0회, Blender Mesh 제작 NOT_TESTED를 기록했다. Stage7 실행 코드는 변경하지 않았다. 이전46개 Mock 통과 수치를 이번 실제 Handoff 성공으로 재사용하지 않는다.

작성한 Handoff Harness는 성공 응답이 있을 때 기존 SHA/Manifest를 검증하고 실제 `meshes()`의 parse/설정/`modeling_tasks()`까지만 실행하도록 제한한다. SAM/Depth가 없는 시험 입력을 실제 관측으로 만들지 않도록 빈 NOT_RECORDED 참조 fixture만 사용할 계획이지만, 이번에는 이 fixture와 Stage7 task도 생성하지 않았다. Synthetic 입력에 Model Reference/보호 실측은 없으며 원 Project의 해당 자료는 보존 대조로 확인했다.

## E. 실제 사진 Reconstruction 준비 상태

읽기 전용 조사 `reconstruction-readiness.json` 기준 `auto-version`에는 **Scene Photo8·Model Reference3·Capture8**이 있고 원본19개 SHA가 모두 일치한다. 카메라 정면 참고를 Scene Photo에 임의 추가하지 않았다. 메모/기존 Candidate/센서 자료를 재사용할 수 있으며 입력 역할을 그대로 유지한다.

현재 Candidate는 Object26개/Camera10개/Robot Link frame8개다. Camera K/Pose는 모두 estimated이며 이를 실제 Calibration으로 승격하지 않는다. `world_registration`, `metric_anchors`는 현재 Project 설정에 없다. 기존 Codex-first Candidate 상태가 새 SimFoundry E2E 완료를 의미하지 않는다.

| 우선순위 / 범위 | 기존 실제 근거 | 남은 실제 통합 검증 |
|---|---|---|
| 1 Stage1/2 | 저장 Photo 원본 SHA, 과거 DA3 Nested Mixed 추론/VRAM | 선택 layout, 실제 Photo의 Depth/Pose·overlap 병합·독립 metric QA. 이번 DA3 Forward0 |
| 2 Stage3/5 | SAM3.1 독립 합성 text1 성공 | 실제 SAM Mask↔Instance ID 대응과 Support Plane. 한 컵 의미 응답은 다중 물체 대응 정확도 인증이 아님 |
| 3 Stage5 제거 | 기존 실제 FLUX에서 큐브/그림자 제거 개선 | 배경 패턴/Mask 경계 불연속은 NEEDS_REVIEW. 실제 Scene 제거 결과의 Codex Gate 필요 |
| 4 Stage5 Depth | 과거 PDA 작은 독립 입력 Forward | 실제 생성 RGB·known prior·grid/scale 연결. 이번 PDA Forward0 |
| 5 Stage6 | Bria 합성 CPU1 및 기존 FLUX 실행 근거 | 실제 Infill/Upsample Object Identity/Alpha/숨은 면 불확실성. 이번 FLUX/Bria0 |
| 6 Stage7/8 | 과거 Native 제작 경로·CPU CPD 작은 계산, 이번 의미 handoff 범위 | 실제 형상 정확도, Front와 실제 CPD Pose. 이번 Blender/CPD0 |
| 7 Stage4/10/11 | 기존 수학/Native/Scene 계약 | DA3 Support→Robot World 명시 등록, Camera Extrinsic·실측 scale/축/Support 관계. 현재 설정에 명시 등록 없음 |
| 8 센서/Stage12–14 | 기존 Side/Wrist/FK/불변 Package와 과거 독립 엔진 시험 | 다른 measured q의 공유 Mount/Side Calibration, 실제 settling/관통·물성·최종 PhysX Task 성공. 이번 Isaac/로봇0 |

Runtime 경로 존재 검사는 설치/API/추론 성공과 구분한다. FoundationPose는 여전히 미설정 선택 기능이다. 실제 장면 의미·기하·센서·물리 정확도를 한 장의 합성 VLM 결과로 인증하지 않는다.

## F. 보존과 범위

시작 ledger **18,462개 파일** 대조 결과, 승인된 `workbench_runs/runtime/reconstruction.yaml` **1개 변경만** 확인했다. 그 밖의 보호 파일 변경0·누락0·신규0이다. 실험 REPORT는 승인된 안내문 뒤에 이전 원문 bytes가 그대로 유지됨을 검사했다. 가중치/전용 소스 외 삭제0이며 상위 src/기존 실험 산출물은 남겼다.

HEAD와 시작 staged diff SHA `5e259fbe6370626a3b608b1b55bc3d12205ab69650731b1994f1c9b2184c3bb6`는 불변이다. 추적 파일의 기존 unstaged diff도 시작과 동일하다. 제품 코드/UI 변경0, 신규 package/model 설치0이다. 진단 Harness Python2개를 bytecode 없이 compile했고 `git diff --check`를 확인했다. pytest 호출0회이며 이전46개 결과를 재실행하지 않았다.

핵심 근거: `preservation-after.json`, `workspace-migration.json/diff`, `deletion-preflight.json`, `deletion-result.json`, `source-reference-confirmation.json`, `live-preflight.json`, `live-result.json`, `live-validation.json`, `handoff-result.json`. 이번에 허용한 원 Workspace YAML 변경과 실험 REPORT 안내 추가를 제외하고 사용자 Scene/Input/Capture/Calibration/Candidate/Cache/Asset/Export를 변경하지 않는다. 신규 설치·모델 다운로드·전체 pytest·Stage1–14 E2E·무거운 모델 Forward·Commit/Push/Merge는 수행하지 않는다.

## G. 다음 실행 우선순위

1. **온라인 최종 응답 미수신 원인 확인이 먼저다.** 기존 서비스/CLI/네트워크 경계를 좁혀 확인하고, 추가 실제 요청은 후속 사용자 지시 범위에서만 수행한다. 이번에 모델/강도를 낮추거나 계정을 바꾸거나 재호출하지 않았다.
2. 최종 JSON을 실제로 받은 뒤 출력 Schema/이미지 의미/Box/실측 unknown 계약을 검증하고, 그 **같은 응답**으로 Stage7 Handoff를 수행한다. Mesh 제작과 온라인 재분석은 그 Handoff 검사에 필요하지 않다.
3. 그다음 실제 Photo의 SAM Instance 대응·FLUX 제거 경계·PDA/Bria 입력 연결과 Stage7 형상·Stage8 Pose를 독립 단계로 검증한다. 기존 성공 모델을 일괄 재실행하지 않는다.
4. Camera/metric·Robot World와 Side/Wrist 공유 Mount/FK의 독립 근거를 확보한 뒤 전체 Scene/settling/Export/Real-Sim·PhysX Task 평가로 진행한다.

이번 네 항목 중 **MASt3R 잔여 파일 삭제와 Workspace 설정 이전은 완료**, 실제 온라인 의미 응답과 그 응답의 Stage7 전달은 **BLOCKED**다.
