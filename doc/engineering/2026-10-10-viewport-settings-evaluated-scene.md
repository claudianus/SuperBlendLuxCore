# Viewport settings evaluated-scene update, 2026-10-10

공개·실제 사용자 설치는 검수한2.11.27이다. 이 코드는 후속 후보로 main에 반영하며 GUI 재시작·실제 UI control 및 공개 ZIP 검수는 남아 있다. 전체 Cycles unchanged-scene goal은 활성·미완료다.

## 재현과 수정

2.11.26 실제 GUI에서 Pixel Size를 API로1→2로 바꾼 뒤 120초가 지나도 frame 크기와 worker mutation이 그대로였다. 실제 property UI 조작을 하지 않았으므로 당시에는 원인을 확정하지 않았다.

현재 exact27 native 프로세스에서 원본 scene Pixel Size는2, evaluated scene은1로 재현했다. `depsgraph.update()`만 호출해도1이며 원본 scene의 `update_tag()` 후에는2가 된다. 기존 exporter/config/framebuffer는 evaluated scene을 읽으므로 redraw만으로 새 설정을 전달하지 못한다. 같은 후속 regression은 공개27의 첫 항목에서 Halt Time expected11/evaluated10으로 실패했다.

뷰포트 RNA21개에 공통 update callback을 연결했다. callback은 `self.id_data`인 원본 Scene에 update tag를 보내고 해당 window manager의3D view를 redraw한다. native RenderSession·Parse·Pause·Resume를 UI callback에서 호출하지 않는다. 기존 serial worker/config diff/rebuild가 변경을 적용한다. 기존 RNA type·default·description·limits와 native 품질/PDF/MIS/RR는 그대로이며 AST 비교로 기존 property 의미를 검증했다. F12 설정이나 Cycles 노드 그래프를 수정하지 않는다.

## 검수와 한계

별도 profile의 signed public27 native에서 CPU와 실제 METAL_GPU RT 세션으로 검사했다. source375PY는 공개27의374PY에서 viewport property file1개와 새 regression1개만 다르고 manifest는 공개ZIP과 같다.

- CPU·Metal 각각21 RNA 변경 및 원래 값 복원 후 evaluated value를 검수했다. 모든21개가 새 값으로 전달됐다.
- 각 backend에서 실제 spectral RT worker를1280×720으로 시작하고 Pause를 확인한 후 Pixel Size2→4→1로 바꿨다. config diff와 worker restart를 거쳐 film640×360→320×180→1280×720, mutation2→3→4, nonzero finite pixels, resume 및 halt timer 재기준화를 확인했다.
- 두 backend의 기존 Cycles material/world/light graph fingerprint는 그대로다. RNA42회·worker8 frame·paused resize6회는 후보 검수이며 공개27의154 수용 조건에 더하지 않는다.
- 읽은 frame은 최초 nonzero 부분 표본이다. 완전 수렴한 이미지·Cycles 영상 parity·성능 수치로 취급하지 않는다.
- 새 GUI 검수 프로세스는 동일 macOS bundle의 기존 사용자 Blender와 CUA binding을 신뢰성 있게 구분하지 못해 실제 rendered view/UI control을 검수하지 못했다. 이번에 만든 프로세스만 PID와 명령행을 검증해 종료했고 기존 사용자 창은 보존했다. GUI 성공을 주장하지 않는다.

Regression: `dev-tools/viewport_settings_update_test.py`; enabled add-on의 Blender `-b --python-exit-code1 --python <script>`에서 실행한다. `DEV=OCL`은 Metal preference와 GPU RT engine을 선택한다. `SUPERLUXCORE_AUDIT_DIR`은 증거 directory, `SUPERLUXCORE_VIEWPORT_FIXTURE`는 자체 검수용 원본 Cycles `.blend`를 선택한다. 이 regression은 headless native worker 검사이며 GUI 검사는 별도다.

증거는 workspace `test-scenes/validation-2026-10-10/viewport-settings-evaluated-scene`의 baseline/candidate/proof/runtime/CPU/Metal EXR/logs다. 공개ZIP·사용자 설치는2.11.27을 유지하며 일반 양수 BSSRDF 및 전체 제작 씬 호환 작업을 계속한다.
