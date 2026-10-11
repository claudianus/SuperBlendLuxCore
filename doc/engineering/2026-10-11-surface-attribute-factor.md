# Surface Attribute Factor 실제 실패 재현과 후속 후보 — 2026-10-11

**마무리 상태: 진단 후보만 검증했으며 제작 적용·배포하지 않았다.** 사용자 마무리 요청에 따라 이번 종료 범위에서 Factor patch의 primary 적용·커밋·설치·배포를 보류하고, 검토 가능한 patch와 수정 전후 원본 증거를 후속 작업으로 남긴다. 현재 배포 단위에 이 후보의 runtime 변경을 포함하지 않는다.


새 driver `dev-tools/cycles-surface-attribute-factor-test.py`는 stable identifier `Fac`로 선택한 출력만 Emission Color/Strength에 연결한다. 빨강 Float3, 초록 FLOAT_COLOR, 파랑 BYTE_COLOR, 비대칭 Float3, 비대칭 Float2, scalar control의 6개 사례를 두 경로에 배치한 **12개 패널**, 각 패널의 독립 interior patch **5개**다. Cycles authored graph·mesh는 두 렌더 사이에 바뀌지 않는다. 원본 state와 독립 타입별 기대값은 `atlas-fixture.json`에 고정했다.

실제 Blender 5.2.1 LTS/build `9e2066aef7ef`의 CPU RenderEngine에서 1280×720, 요청 64 SPP로 실행했다. frozen portable 후보 native SHA `e04d60b9011933cfd383a96219b5e774c552ea58d49ebe8c6bb97c6383590503`, reader SHA `d03113cbc9b104bb3f53544d0a633dee41c70fefea668ea7652ec793756708a7`를 사용했다. 분광 기본값을 저장하고 RGB·Light Tracing OFF 진단으로 실행한 뒤 모든 수정한 설정을 finally에서 복원했다. 이 RGB 진단은 분광 품질 기본값을 변경하는 작업이 아니다.

| 사례 | 독립 Cycles 기대 RGB, 두 연결 경로 공통 | 실제 frozen native RGB, 두 연결 경로 공통 | 판정 |
| --- | --- | --- | --- |
| 빨강 Float3 `(1,0,0)` | `(1/3,1/3,1/3)` | 약 `(1,0,0)` | 두 패널 실패 |
| 초록 FLOAT_COLOR `(0,1,0,.25)` | `(1/3,1/3,1/3)` | 약 `(0,1,0)` | 두 패널 실패 |
| 파랑 BYTE_COLOR `(0,0,1,.25)` | `(1/3,1/3,1/3)` | 약 `(0,0,1)` | 두 패널 실패 |
| Float3 `(.1,.4,.9)` | 약 `(.466667,.466667,.466667)` | 약 `(.1,.4,.9)` | 두 패널 실패 |
| Float2 `(.8,.1)` | `(.8,.8,.8)` | 약 `(.8,.1,0)` | 두 패널 실패 |
| Float `.4` | `(.4,.4,.4)` | 약 `(.4,.4,.4)` | 유지 회귀 두 패널 통과 |

- Cycles **12/12 패널, 60/60 patch 통과**, 최대 patch 평균 절대 오차 `4.6491623e-7`.
- Native CPU 실제 eye **69 SPP**, 유한 raw RGB. **10/12 패널 실패, scalar 두 패널 통과**, 최대 절대 오차 **0.8**. 고정 patch 평균 오차/spread 허용값은 각각 **0.005**이며 실패를 인정받기 위해 넓히지 않았다.
- 원본 PNG 두 장을 직접 확인했다. Cycles의 두 행은 모두 중립 회색이며, native 두 행은 빨강/초록/파랑/비대칭 파랑/주황으로 나타난다. scalar control만 동일한 중립 회색이다. 패널 기하가 누락되는 문제가 아니라 Factor 값의 채널 의미가 누출되는 문제다.
- `metrics.json`은 **complete=true, passed=false**, `native_semantic_failure_reproduced=true`를 유지한다. Blender와 bounded wrapper는 **returncode=1**, terminal/reaped=true로 종료했다. 이 실패를 배포 readiness로 사용하지 않는다.
- guard wrapper는 기존 VDB `run-render.py`와 byte-identical이며, 별도 evidence 디렉터리에서 실행했다. 실제 profile의 **192 엔진 payload, 374 Python, 3 설정, 1 전체 캐시 wheel**이 전후 동일하다. 추가 profile을 생성하지 않았고 종료한 worker를 reap했다.

원본 증거 디렉터리는 `test-scenes/validation-2026-10-11/surface-attribute-factor/portable-surface-factor-baseline/`이다. 두 PNG/EXR, authored `.blend`, fixture, metrics, 실제 profile isolation inventory를 보존했다. 상위의 `portable-surface-factor-baseline-diagnostic-proof.json`은 원본 해시·직접 검토·예상 실패·종료/reap을 연결한다. 다음 수정 후보는 같은 gate와 fixture로 **수정 전 실패→수정 후 통과**를 증명해야 한다. Metal/분광/다른 scene의 실행은 이번 CPU 재현에서 검증하지 않았다.

## 별도 임시 프로필의 좁은 수정 후보

검사 당시 VDB 서명 배포 단위의 primary repository exports와 portable profile은 바꾸지 않았다. 소유한 별도 임시 프로필에 266 runtime Python 파일을 개별 복사하고, 기존 native payload 192개 및 whole wheel만 immutable hardlink로 공유했다. 바뀐 runtime 파일은 그 임시 복사본의 `export/cycles_node_reader.py`와 `export/named_attributes.py` 두 개다. source-only Normal/BSSRDF 누락을 보존했고 VDB volume adapter와 native Y의 의미는 바꾸지 않았다. 이 임시 프로필은 검사 종료 후 이미 삭제했다.

- volume 분기 뒤의 surface Attribute에서 stable identifier `Fac` 및 구 display name `Fac`/신 display name `Factor`를 동일하게 인식한다.
- RGB 색·Float3 Factor는 기존 channel texture helper와 평균 helper로 **산술 평균 scalar**를 만든다. native의 전역 `hitpointcolor`/`hitpointgrey` Y 계약은 유지한다.
- named attribute lookup에 원본 `data_type`을 추가해 Float2 Factor를 **x scalar**로 보존한다. scalar AOV와 다른 Attribute 출력의 기존 계산은 유지한다.
- 기존 emission export는 Color와 Strength를 texture 곱으로 만든다. 따라서 수정 전 실제 Strength 경로도 scalar 타입 변환을 보장하지 않고 RGB를 누출했다. 수정 후보가 Factor 자체를 scalar texture로 만들면서 두 연결 경로를 함께 복원한다.

reviewable patch는 `test-scenes/validation-2026-10-11/surface-attribute-factor/surface-factor-preview-against-8b0b53ae.patch`다. primary addon commit `8b0b53aeae7581b5d1c68054f450cafed9af3b5b`에 `git apply --check`가 통과한다. primary exports에 적용·커밋·push하지 않았다. 두 변경된 preview adapter 원본을 `preview-adapter/export/`에 byte-for-byte 보존했다.

## 후보 CPU / pure Metal 실제 검사

같은 driver·독립 expectation·0.005 오차/spread gate를 사용해 CPU와 pure Metal을 각각 실행했다. 각 실행은 Cycles CPU baseline과 native 렌더를 포함한다. 모든 실제 Blender worker는 CONFIG/EXTENSIONS/RESOURCES 경로를 명시·확인했고, bounded owner가 종료를 기다려 reap했다.

| 임시 후보 실행 | 통과 패널 / 독립 patch | native actual eye SPP | 최대 평균 채널 절대 오차 | 상태 |
| --- | --- | --- | --- | --- |
| CPU | 12/12, 60/60 | 67 | `4.5884046e-7` | 통과 |
| pure Metal | 12/12, 60/60 | 67 | `1.6480285e-6` | 통과; native CPU disabled |

두 Cycles baseline도 각각 12/12 패널 및 60/60 patch를 통과했다. 모든 raw RGB는 유한하다. 원본 PNG **4장**을 직접 확인했다. native CPU/Metal 둘 다 모든 패널이 Cycles와 같은 중립 회색이며, 타입별 밝기와 실루엣이 일치한다. 수정 전 나타났던 RGB/Float2 주황색 누출이 사라졌다. 원본 authored graph·mesh 및 설정 복원 검사도 통과했다.

- identity: `profile-surface-factor-preview-identity.json`, native SHA는 동일한 `e04d60b9…`, whole wheel SHA는 동일한 `c725c1bc…`다. signature=false, diagnostic_only=true다.
- preview reader SHA: `4e43035def05fe965f253591765742192598fa2be2c13fd9a5dfa5786f2ea924`.
- preview named_attributes SHA: `d563d590d7b38bb2be6644c796d90c5fb3e84fdc4d11ae96663a41bb246887de`.
- CPU owner session 26095 / Blender 82196, Metal owner session 90783 / Blender 82309: **returncode=0, complete/terminal/reaped=true**.
- 각 guard의 실제 profile **192 payload / 374 Python / 3 설정 / 1 cached wheel**은 전후 동일하다. primary reader/named source와 portable의 266 runtime PY·192 payload·whole wheel도 실행 전후 동일하다.
- `preview-surface-factor-proof.json`이 identity, patch, 두 worker의 metrics/state/isolation, 원본 PNG/EXR/blend/fixture, 두 preview adapter의 해시와 직접 검토를 연결한다. primary 적용 및 실제 설치·서명 wheel QA는 아직 수행하지 않았다.

증거를 저장하고 두 owner를 reap한 뒤 임시 profile을 즉시 제거했다. `preview-stage-cleanup.json`에 논리 크기 **404,629,764 bytes** 제거, 그중 공유 hardlink **384,784,525 bytes**, single-link 파일 **19,845,239 bytes**를 기록했다. 공유 원본 portable의 바이트는 보존했다. 물리적 SSD 회수량을 별도로 측정하지 않았으므로 이 논리 크기를 물리 공간 회수량으로 보고하지 않는다.

reviewable patch의 primary 적용과 최종 signed native를 유지한 새 staging·실제 설치 CPU/Metal 검증은 **사용자의 이번 마무리 요청에 따라 보류한 후속 작업**이다. 이번 preview는 POINT-domain 6개 값/타입의 RGB Factor→Color/Strength 진단이다. CORNER/FACE 유지 회귀, 다른 Attribute 출력, 연결 식 조합, 기본 분광, namespace/UV/없는 값, GUI·제작 씬·타 플랫폼은 이 좁은 후보에서 검증한 것으로 세지 않는다. 전체 Cycles 호환 goal은 계속 미완료다.
