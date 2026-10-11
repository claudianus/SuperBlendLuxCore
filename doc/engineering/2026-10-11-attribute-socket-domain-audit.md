# Attribute 소켓·데이터 영역 후속 감사 — 2026-10-11

현재 VDB index/Linear/Cubic 배포 단위와 분리한 읽기 전용 소스 감사다. 이 감사에서는 어댑터·네이티브 코드를 수정하거나 Blender 프로세스를 실행하지 않았다. 아래 결함은 기존 Cycles 그래프의 데이터 의미를 바꾸는 후속 작업이며, 전체 호환성 비율이나 실렌더 통과를 뜻하지 않는다.

## 버전과 증거 범위

- 제공된 Blender 소스: `/Users/modumaru/Desktop/code/blender-5.2`, HEAD `d13f752e3b9c4f8c261cda552b1021f8bcc0382c`.
- 실제 설치 버전: 기존 VDB 검사 기록의 Blender `5.2.1 LTS`, build hash `9e2066aef7ef`. 소스 HEAD와 설치 빌드가 다르므로 설치 실행 계약은 별도의 작은 Cycles 회귀로 확인해야 한다.
- `test-scenes/validation-2026-10-11/vdb-grid-reconstruction/factor-rgba-cpu/metrics.json`의 `authored_attribute_sockets`에는 Attribute의 Factor 소켓이 `display_name="Factor"`, `identifier="Fac"`로 기록돼 있다. 같은 파일은 기존 VDB 검사 증거이며 이 감사에서 새로 실행한 surface 검사가 아니다.
- 어댑터 HEAD `4549a8ee57756c20c3b63213d5f5fb6b83071520`에 현재 VDB 작업 변경이 있는 상태의 파일을 읽었다. 네이티브 HEAD는 `ed9aebd4fc901bc5bb5d3787eb4303b767eca87e`다. 다음 소스 위치는 이 시점의 행 번호다.

## 확인한 Cycles surface 계약

주된 근거는 제공된 소스의 `intern/cycles/kernel/svm/attribute.h`다. `scene/shader_nodes.cpp:6240–6297`은 Color/Vector를 FLOAT3, Fac를 FLOAT, Alpha를 FLOAT_ALPHA로 컴파일한다.

| 원본 데이터 | Color / Vector | Fac | Alpha | 소스 위치 |
| --- | --- | --- | --- | --- |
| Float | `(v,v,v)` | `v` | `1` | `attribute.h:93–99` |
| Float2, UV | `(x,y,0)` | **x** | `1` | `attribute.h:101–121` |
| Float3 | 원래 세 채널 | **산술 평균** `(x+y+z)/3` | `1` | `attribute.h:147–154` |
| Float4 / RGBA | 첫 세 채널 | **RGB 산술 평균** | 네 번째 채널 | `attribute.h:124–144` |

Fac의 평균은 RGB 휘도 Y와 다르다. 파랑 `(0,0,1)`은 Cycles 계약에서 `1/3`이며, 현재 native Y는 `0.072169`다. Float2 `(0.8,0.1)`의 Fac는 `0.8`이며 평균 `0.3` 또는 Y `0.2416528`이 아니다.

없는 surface Attribute의 계약은 섣불리 모든 출력 0으로 통일하면 안 된다. 이 소스의 SVM은 `attribute.h:30–40`에서 없는 속성의 descriptor type에 output type 숫자를 넣는다. `kernel/svm/types.h:58–70`에 의해 Color/Vector는 FLOAT, Fac는 FLOAT2, Alpha는 FLOAT3 경로가 되고, triangle의 없는 element는 `kernel/geom/triangle.h:334–337`에서 0을 돌려준다. 따라서 이 소스의 일반 Attribute는 Color/Vector/Fac=0, Alpha=1 경로다. OSL의 `kernel/osl/shaders/node_attribute.osl:14–29`는 없는 Alpha 기본값 0이므로 차이가 있다. OSL은 기존 보류 범위이며, 설치 Cycles SVM의 실제 출력을 먼저 확인한다.

Vertex Color 노드는 별도 계약을 가진다. 이름이 비면 활성 렌더 색 속성을 요청한다(`scene/shader_nodes.cpp:5153–5163`). 없는 Vertex Color의 Color와 Alpha는 둘 다 0이다(`kernel/svm/vertex_color.h:24–39`). 기존 RGBA의 Color/Alpha는 각각 RGB와 authored alpha를 보존한다.

## 확인한 어댑터 결함과 범위

| 항목 | 현재 경로와 정확한 위치 | 의미와 후속 변경 |
| --- | --- | --- |
| Factor 소켓 인식 | `export/cycles_node_reader.py:3575`, `3611`은 display name `Fac`만 검사한다. `3607`의 fallback 구분도 동일하다. VDB 경로의 `3546–3547`만 identifier와 Factor 이름을 처리한다. | surface에도 안정적인 identifier를 적용해야 한다. 단, 이름 변경만으로 아래 평균 결함은 고쳐지지 않는다. Scalar vertex/triangle AOV는 두 분기의 texture type이 같아 이름 결함만으로 값이 바뀌지는 않는다. |
| 색·Float3 Fac가 Y 또는 RGB로 변환됨 | generic KIND_COLOR Fac는 `3575–3587`에서 `hitpointgrey channel=-1`, 색 레이어 Fac는 `3611–3615`에서 동일하다. Factor 이름은 `3596` 또는 `3625`의 `hitpointcolor`로 빠진다. | Fac를 세 채널 산술 평균의 scalar texture로 명시해야 한다. Float 소켓에 연결하면 두 native texture 모두 Y를 읽으며, Color/Vector에 연결하면 Factor 이름 경로는 원본 RGB가 노출될 수 있다. |
| Float2 원본 타입 소실 | `export/named_attributes.py:51–56`, `98–99`가 Float2/Float3를 같은 KIND_COLOR로 분류하고 `148–155`가 Float2를 `(x,y,0)`으로 저장한 뒤 map에 kind/index만 남긴다. | Fac의 x 선택과 Float3 평균을 구분할 원본 타입 정보를 보존해야 한다. `_volume_grid_scalar`를 모든 generic vector에 그대로 적용하는 것으로 해결되지 않는다. |
| named UV는 Vector만 조회하고 기본 반복함 | `cycles_node_reader.py:3555–3563`은 Vector 출력만 UV lookup한다. UV 이름은 `named_attributes.py:82–87`에서 generic 수집에서 제외된다. `SuperLuxCore/src/slg/scene/parsetextures.cpp:448–450`의 uv.wrap 기본값은 true다. | Color/Fac/Alpha도 같은 UV 속성을 조회해야 한다. Vector는 `wrap=false`로 음수·1 경계·1 초과 좌표를 보존해야 한다. native `src/slg/textures/uv.cpp:33–38`은 이미 반복하지 않는 경로를 제공한다. Fac는 x, Alpha는 1이어야 한다. |
| 속성 namespace 무시 | reader의 `3532`는 VDB gate에만 `attribute_type==GEOMETRY`를 사용하며 `3553–3627`은 OBJECT/INSTANCER/VIEW_LAYER도 geometry 이름으로 조회한다. | 이름이 겹치면 틀린 mesh 데이터를 반환하고, mesh에 없으면 0.5 fallback이다. Cycles는 `intern/cycles/blender/shader.cpp:127–141`, `585–589`에서 namespace를 분리한다. Object/Instancer는 `blender/object.cpp:380–395`, `423–427`에서 개별 object/dupli context를 읽는다. View Layer는 `blender/shader.cpp:1572–1594`에서 evaluated scene/layer 속성을 별도로 상수화한다. 이 세 범위의 완전 지원은 각각 검증해야 한다. |
| 없는 속성의 회색 대체 | reader `3602–3608`은 모든 미해결 경로에 0.5를 반환한다. | 일반 Attribute와 Vertex Color의 소스 계약에 모두 어긋난다. 일반 Attribute의 Alpha를 포함한 설치 SVM 계약을 확인한 뒤 노드·출력별 기본값을 적용해야 한다. |
| Vertex Color의 빈 layer name | reader `3526–3528`에서 빈 문자열을 그대로 쓰고 `_color_attribute_index`(`1041–1050`)는 이름의 정확한 일치만 찾는다. | `layer_name=""`에서 활성 렌더 색 속성 fallback이 없다. 두 색 레이어의 활성 렌더 대상을 바꾸는 실제 검사로 복원한다. |
| FACE vector 수집 누락 | `named_attributes.py:93–99`는 FACE scalar만 수집하고 FACE Float2/Float3는 누락한다. Cycles `intern/cycles/blender/mesh.cpp:72–83`, `168–206`, `235–248`는 지원되는 generic 타입의 FACE 데이터를 삼각형마다 전달한다. | Float2/Float3 FACE 도메인은 현재 미해결 fallback으로 떨어진다. 기존 scalar FACE와 분리한 후속 기능으로 삼각형 또는 확장 color carrier를 설계한다. |

native Y의 근거는 `SuperLuxCore/src/slg/textures/hitpoint/hitpointcolor.cpp:29–34`, `73–82`다. `HitPointColorTexture::GetFloatValue`와 `HitPointGreyTexture channel=-1`은 색의 `.Y()`를 반환한다. `SuperLuxCore/include/luxrays/core/color/color.h:324–325`의 Spectrum Y 계수는 `(0.212671, 0.715160, 0.072169)`이다. GPU도 `include/slg/textures/hitpoint/texture_hitpoint_funcs.cl:25–30`, `141–156`에서 같은 Y를 사용한다. 공통 native Y 의미를 바꾸면 다른 사용자 texture가 영향을 받으므로 Cycles 어댑터의 Fac 변환에서 처리하는 것이 좁은 수정이다.

정상으로 보이는 범위도 구분한다. 기존 POINT/CORNER/FACE scalar의 AOV lookup과 scalar/vector Alpha=1, 등록된 색 레이어의 Color/Alpha 분리는 구조상 Cycles 계약과 맞는다. 이번 감사는 이 경로들의 설치 실행·기본 분광 수렴을 새로 검증한 것이 아니다. 기존 `dev-tools/e14_named_attribute_test.py:118–125`는 scalar Fac와 vector Color만 사용하므로 벡터/색 Fac, UV, 없는 값, namespace 충돌을 검출하지 못한다.

## 제안하는 작은 수정·회귀 단위

현재 서명 VDB staging의 어댑터 바이트는 유지한다. 아래 1번을 그 다음의 독립 수정 단위로 진행하고 나머지는 별도 범위로 분리한다.

1. **surface 소켓·기본값·타입 변환:** 공통 stable socket helper, KIND_COLOR의 RGB 평균, Float2 x 선택을 구현한다. Float2/Float3 원본 타입 보존이 필요하다. 빈 Vertex Color 활성 레이어와 없는 값 기본값은 설치 Cycles 출력을 먼저 확인한다.
2. **UV Attribute:** 모든 출력의 named UV lookup과 wrap=false를 적용한다. raw UV Vector/Color, x Factor, Alpha 1을 같은 scene에서 확인한다.
3. **Object/Instancer/View Layer namespace:** 각각의 evaluated context를 확보한다. shared material을 사용하는 두 object와 같은 mesh/속성 이름을 가진 충돌 조건을 반드시 포함한다. dupli/instance가 없는 상태와 있는 상태도 분리한다.
4. **FACE vector 도메인:** 기존 scalar/AOV와 POINT/CORNER 채널 보존·예산 처리까지 확인한 다음 확장한다.

표적 실제 회귀는 하나의 1280×720 orthographic emission atlas를 사용하면 셰이딩 노이즈와 좌표를 분리할 수 있다. Cycles 원본 그래프를 유지한 CPU/pure Metal SuperLuxCore 렌더, raw linear 채널, 직접 PNG 검토와 실제 profile 전후 해시를 함께 기록한다. 최소 atlas 항목은 다음과 같다.

- POINT/CORNER scalar와 FACE scalar: Color/Vector/Factor/Alpha. 색이 같은 scalar는 Fac 이름 회귀만 검출하지 못하므로 유지 회귀로 쓴다.
- Float3 및 FLOAT_COLOR/BYTE_COLOR: 빨강·초록·파랑과 비대칭 `(0.1,0.4,0.9)`. Factor를 **Emission Color와 Strength에 각각** 연결한다. 그래야 RGB를 반환하는 Factor 경로와 Y 평균 오류를 모두 검출한다. authored alpha=0.25도 별도 패널에 둔다.
- Float2 `(0.8,0.1)`와 named UV `(-0.25,1.25)`, `(1,0.4)`: Color/Vector는 원본 세 채널, Factor는 x, Alpha는 1로 검사한다. 양수 단위 UV만 쓰면 wrap 결함을 놓친다.
- 없는 일반 Attribute와 없는 Vertex Color, 빈 Vertex Color layer name 및 활성 렌더 색 레이어 교체. 일반 Attribute Alpha를 Vertex Color Alpha와 같은 값으로 가정하지 않는다.
- namespace 단위에는 mesh의 `paint=(1,0,0)`와 object의 같은 이름 속성 `paint=(0,0,1,0.25)`를 충돌시킨다. 두 object가 같은 material과 mesh를 공유하되 object 값은 다르게 두어 material export/cache가 object context를 섞는 것도 검출한다. Instancer/View Layer는 각각 독립 source/installed baseline을 만든다.
- 도메인 단위에는 삼각형마다 다른 FACE Float3/Float2를 넣어 미해결 값·인접 면 보간·welding 회귀를 검출한다.

소켓 이름 alias만 바꾼 mock 검사는 값의 평균, 실제 socket→Color 변환, mesh 수집, instance context를 증명하지 못한다. 기존 test 파일은 유지하고 위 단위를 별도 실제 Blender driver로 추가하는 것이 적절하다. 각 단위가 완료되면 수정 전 실패 기록, 수정 후 원본 그래프 불변·유한값·요청 SPP·native/adapter identity·profile 보존 증거를 남긴다.

## 남은 구현과 우선순위

가장 좁고 바로 드러나는 후속 결함은 **surface Color/Float3/Float2 Factor의 의미**다. named UV와 없는 기본값도 작은 어댑터 단위로 해결할 수 있다. Object/Instancer/View Layer와 FACE vector는 export context/데이터 carrier를 건드리는 별도 작업이다. Generated volume carrier, 중첩 매질, 실제 GUI/F12, 큰 시뮬레이션과 제작 씬/플랫폼 검수는 현재 VDB 보고서의 잔여 범위를 그대로 유지한다. 이 감사는 해당 작업들의 완료 상태를 변경하지 않는다.
