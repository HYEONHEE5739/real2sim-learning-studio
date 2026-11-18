# Object Library — OpenGL Context 정리 중 native crash 수정

2026-11-16. `feat/simfoundry-style-reconstruction`, 기준 HEAD `8e02b1ae023a856694a40b947881f76b66410624`. 기존 미추적 교재 9개를 보존하고 Viewer 수명 처리만 수정했다. Scene 제작·모델 추론·설치·Commit/Push는 수행하지 않았다.

## 증상과 확인한 원인

Object를 선택하다 간헐적으로 다음 로그 뒤 프로그램이 종료되는 문제가 보고됐다.

```text
QOpenGLTexture::setData() requires a valid current context
Requires a valid current OpenGL context.
Texture has not been created
```

기존 `AssetViewport.cleanup()`은 자기 Context를 `makeCurrent()`하여 VBO/Texture/Shader/VAO를 해제하고 `doneCurrent()`를 호출했다. 그 직전에 **다른 Viewer의 Context가 current였는지 저장·복원하지 않았다.** 다른 Viewer가 Texture를 업로드하는 중 이 정리가 끼어들면 그 Viewer의 후속 GPU 명령은 current Context가 없는 상태에서 실행될 수 있었다.

두 실제 Qt/OpenGL Viewer로 새 업로드 시작 시 이전 Viewer의 종료를 겹치도록 고정했다. 수정 전 `CURRENT_BEFORE=True → CURRENT_AFTER=None`과 위 경고, **SIGSEGV(-11, shell의 139)**를 재현했다. 이 재현은 수명 처리의 겹침을 결정적으로 삽입한 것이다. 사용자의 당시 core/stack은 제공되지 않아 실제 클릭 시 어떤 종료 callback이 끼어들었는지까지 확정하지 않는다. 일반 reload/reparent 반복만으로는 최초 탐색에서 재현되지 않았다.

Qt는 한 thread에 하나의 current Context를 사용하며, GL 자원 처리에는 해당 Context가 필요하다. [Qt Context 계약](https://doc.qt.io/qt-6.11/qopenglcontext.html#thread-affinity), [QOpenGLWidget 자원 정리](https://doc.qt.io/qt-6.11/qopenglwidget.html#resource-initialization-and-cleanup)를 설치된 API와 대조했다.

## 최소 수정

[AssetViewport.cleanup](../robot_learning_workbench/src/robot_learning_workbench/ui/asset_viewport.py#L294)에서 다음을 처리한다.

1. 이전 current Context와 Surface를 저장한다.
2. 자기 Context로 전환된 것을 확인한 뒤 자기 GPU 자원만 해제한다.
3. `finally`에서 정리한 Context를 해제하고, 이전의 다른 유효 Context/Surface를 복원한다.

이전 Context가 없으면 정리 후에도 없는 상태를 유지한다. Texture·Geometry·Shader·Depth/X-Ray 수학과 Object Library UI/Backend는 변경하지 않았다. 전체 Viewer 교체나 새로운 Context Manager도 추가하지 않았다.

## RED → GREEN과 GUI 검증

| 검사 | 실제 결과 |
|---|---|
| 새 수명 회귀 3개, 수정 전 | 2 failed / 1 passed, 5.23초 |
| 동일 3개, 수정 후 | 3 passed, 4.91초 |
| 원래 native crash 재현 스크립트, 수정 후 | exit0, Context 복원, 해당 Qt 경고 0개 |
| 기존 Asset/Viewer·Wireframe 회귀 | 14 passed, 13.61초 |
| 실제 Library→Backend→USD Converter→Qt/OpenGL | 15회 자산/버전 선택, Dialog 4개, 17.76초, 해당 경고 0개 |

신규 시험은 [test_viewport_context_lifecycle.py](../real2sim_builder/tests/test_viewport_context_lifecycle.py)다. 다른 Viewer가 current인 상태의 이전 Viewer 종료, Texture upload와 겹치는 종료, 이전 current Context가 없는 정리를 검사한다. 실제 Texture 생성·출력 색·자원 해제를 확인하며, native crash는 별도 Qt 자식 프로세스 안에 격리된다.

```bash
bash docs/evidence/builder/run_tests.sh \
  real2sim_builder/tests/test_viewport_context_lifecycle.py \
  real2sim_builder/tests/test_asset_view.py \
  real2sim_builder/tests/test_wireframe_features.py -q --tb=short
```

위 세 파일은 이번에 신규 3개와 기존 14개로 나누어 실행했다. **고유 17개 통과, skip/xfail 없음**이며 전체 프로젝트 회귀를 재실행한 것은 아니다.

실제 GUI에서는 기존 `cup_1/v001`, `cup_2/v001`, 세 블록과 `workspace_paper/v001↔v002`를 사용했다. 컵은 Converter가 반환한 Visual 2개·Collision 65개다. Orbit/Zoom/Pan/Reset, Collision 전환, 실제 다른 Dialog 종료와 컵 업로드의 겹침, 닫기 후 자원 해제를 확인했다. 환경은 PyQt 6.11.0 / Qt 6.11.2 / NVIDIA RTX 4060 Laptop, 실제 Viewer Context는 OpenGL 4.1·Depth 24bit다.

증거 폴더는 `/tmp/real2sim-viewport-context-20261116-qf4ybwqh/`다. `context-red.xml`, `context-green.xml`, `viewer-regression.xml/log`, `repro-red.log/json`, `repro-green.log/json`, `library-stress.json/log`와 실제 GUI 캡처 `cup-visual-after.png`, `cup-xray-after.png`를 보존했다. `/tmp` 자료는 로컬 임시 증거이므로 저장소만 받으면 존재하지 않는다. 실패 전에 정상 화면을 저장하지 못했으므로 Before 이미지가 있다고 하지 않는다.

## 보존과 한계

Scene/Input/Capture/Calibration/Candidate/Asset/Export·Dataset·Runtime 등을 포함하는 시작 ledger **19,613개 파일**을 종료 후 SHA/크기로 대조했다. 변경0·누락0·신규0이다. 기존 교재 Markdown9개와 Git Index·HEAD·브랜치도 보존했다. 기존 추적 파일 중 변경한 것은 `asset_viewport.py` 하나이며, 새 파일은 회귀 시험과 이 보고서다. `git diff --check`와 두 Python 파일의 bytecode 없는 구문 검사를 확인했다.

이 수정은 재현된 Context 유실 경로를 해결한다. 다른 Driver/OS/Wayland 또는 모든 native 종료 원인을 인증하지 않는다. 실행 중인 앱은 Python 모듈을 이미 로딩했으므로 완전히 종료한 뒤 다시 실행해야 수정 코드가 적용된다.
