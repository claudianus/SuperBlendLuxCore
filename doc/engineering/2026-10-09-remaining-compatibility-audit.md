# Blender/Cycles 잔여 호환성 전수 검수

2026-10-09. 대상은 정식 2.11.13 ZIP의 확장 `4a546eea09fcc78d7cb7d347a85caba4f64980ac`, 엔진 `bc8e30604297ed5b82207a56a727b36d2d222db9`다. 이후 문서 커밋 `c5902a5b`에는 실행 코드 차이가 없다. 설치본은 `/tmp/slc-final-public-profile`이며 개발 빌드 경로를 추가하지 않았다.

검수 결과, 전체 99% 호환성 완료를 입증할 근거가 없다. 단순 노드 등록, 경고 후 대체와 영상 동등함을 분리해야 한다. 이 문서는 문제를 고치거나 배포본을 교체한 결과가 아니라 현재 배포본의 잔여 문제 검수 기록이다.

## 기준 소스와 검수 방법

사용자가 제공한 `/Users/modumaru/Desktop/code/blender-5.2`는 5.2.2 `d13f752e3b9c4f8c261cda552b1021f8bcc0382c`의 부분 체크아웃이었다. 설치된 Blender 5.2.1 실행 파일 해시와 공식 태그가 일치하는 `9e2066aef7ef7e20c142ad7bd3303138a4304c93`을 읽기용 Git 캐시에 확보했다. 작업 파일과 브랜치는 바꾸지 않았다. 대조한 커널·노드·카메라·패스 구현 20개 파일은 5.2.1과 5.2.2가 동일하고 버전 헤더만 달랐다. 증거의 `blender-5.2.1-source/source-metadata.json`에 목록을 기록했다.

- RNA 이름 102개 중 기반 ShaderNode·ShaderNodeCustomGroup·ShaderNodeTree 3개는 생성 불가였다. 실제 생성 가능한 노드는 99종이다. 기존 문서의 102개 모두 지원이라는 분모는 수정해야 한다.
- `cycles-remaining-audit.py`로 출력·열거 모드·숨겨진 Normal/Tangent 연결 입력·실제 이미지·RGBA/Noise/Hair/MapRange 조합 1,023조건을 실행했다. 38조건이 예외, 407조건이 경고였고 경고가 발생한 노드 유형은 53종이다. Mix ROTATION은 RNA 열거 목록에 있어도 ShaderNode에서 지정할 수 없으므로 1조건을 사용 불가로 분리했다.
- 이 검사는 변환기의 호출 결과다. 예외 없는 반환을 렌더 합격으로 세지 않는다. 데이터 없는 기본 Attribute·VolumeInfo 조건의 경고, 기본 그룹의 출력 부재, 합법적인 비활성 로브 입력은 미지원과 구분한다.
- `cycles-remaining-render-audit.py`로 25개 표적 조건을 1280×720·16샘플·RGB·클램프/노이즈 제거 꺼짐의 Cycles와 CPU/Metal 배포본에서 비교했다. 선형 EXR 평균 절대 오차를 사용한다. CPU 초기 Vector Map Range의 기본 0은 양쪽 검정으로 오류를 가렸으므로 비영 입력으로 다시 실행했다.
- Factor=1의 HSV 대조 조건을 제외한 24개는 영상 차이를 재현했다. 이는 실패를 겨냥한 표적 집합이므로 전체 기능의 실패율로 계산하지 않는다.
- `cycles-workflow-audit.py`는 실제 설정 가져오기, 패스 등록/필름 생성, DOF·파노라마와 볼륨 합성, 중복 이름 그룹 출력 결과를 기록한다. 전체 GUI나 완성된 컴포지터 그래프의 실행 검증과는 구별한다.

## 우선순위

현재 목록은 60개 작업 묶음이며 P0 5개, P1 35개, P2 20개다. 확정 결함과 미지원·미검증 범위를 함께 관리하는 목록이므로 모두 실행으로 확정한 버그라는 뜻은 아니다.

P0는 실제 입력 조회 예외로 재질을 대체하는 문제, P1은 제작 장면의 색·에너지·매질·패스 의미를 바꾸는 문제, P2는 제한된 지원·추가 실행 검증이 필요한 범위다. 한 행은 하나의 작업 묶음이며 전체 기능 수의 분모가 아니다.

| ID | 우선순위 | 범위 | 판정 | 발견 내용 | 근거 |
|---|---|---|---|---|---|
| C01 | P0 | Magic Texture | 실행 예외 | Depth는 소켓이 아니라 tex_depth 속성이다. 존재하지 않는 입력 조회로 회색 대체 재질이 된다. | reader 3621; Blender node_shader_tex_magic.cc; 720p CPU·Metal |
| C02 | P0 | Noise 1D | 실행 예외 | 1D에서 Vector 입력이 제거되는데 무조건 조회한다. W를 받기 전에 실패한다. | reader 3362; Blender node_shader_tex_noise.cc; 720p CPU·Metal |
| C03 | P0 | Voronoi 1D | 실행 예외 | Vector 입력이 없는 1D에서 무조건 조회한다. Distance/Color/W 출력 검사에서 예외가 난다. | reader 3341; 노드 전수 변환 |
| C04 | P0 | White Noise 1D | 실행 예외 | 없는 Vector 입력을 조회한다. W 기반 1D 해시 경로가 없다. | reader 3428; 노드 전수 변환 |
| C05 | P0 | 벡터 Map Range | 실행 예외 | Vector 모드에서 없는 Value 입력을 조회한다. 비영 입력의 실제 렌더는 검게 나온다. | reader 2551; 720p CPU·Metal |
| C06 | P1 | Layer Weight Fresnel | 영상 불일치 | Blend를 무시하고 고정 IOR 1.45를 사용한다. Cycles는 eta=max(1-Blend,1e-5)와 앞/뒷면 조건을 적용한다. | reader 2713; Blender svm/fresnel.h; 720p CPU·Metal |
| C07 | P1 | Layer Weight Facing | 영상 불일치 | Cycles의 Blend 구간별 지수 변환과 1-pow(abs(dot),지수)를 재현하지 않는다. 연결 Blend·Normal도 지원하지 않는다. | reader 2724; Blender svm/fresnel.h; 720p CPU·Metal |
| C08 | P1 | Hue/Saturation Factor | 영상 불일치 | Factor를 읽고 최종 HSV 변환 결과와 원색을 혼합하지 않는다. Factor=0에서도 색이 바뀐다. | reader 2082; Blender svm/hsv.h; 720p CPU·Metal |
| C09 | P1 | ColorRamp Alpha | 영상 불일치 | Alpha 출력을 구분하지 않고 RGB band를 반환한다. 알파 값은 저장하지 않는다. | reader 2154; Blender svm/ramp.h; 720p CPU·Metal |
| C10 | P1 | ColorRamp 색 공간·보간 | 영상 불일치 | HSV/HSL와 색상 보간 방향을 무시한다. Ease/Cardinal/B-Spline을 한 cubic 경로로 합친다. RGB Linear/Constant 지원과 구분해야 한다. | reader 2159; 720p HSV·Ease CPU·Metal |
| C11 | P1 | Float Curve | 영상 불일치 | Factor를 무시한다. 9개 LUT, 0..1 출력 제한과 입력 구간 제한으로 세부 곡선·외삽도 손실된다. | reader 3670; Blender scene/shader_nodes.cpp FloatCurveNode; 720p CPU·Metal |
| C12 | P1 | Vector Curve | 영상 불일치 | 3개 채널 배열에 channel+1로 접근하여 마지막 채널에서 실패하고 입력을 그대로 반환한다. Factor도 미지원이다. | reader 3715; 720p CPU·Metal |
| C13 | P1 | RGB Curve | 소스 확정 제한 | 합성 곡선 하나만 휘도에 적용해 회색 band로 반환한다. 채널별 곡선·Factor·색 보존·외삽이 다르다. | reader 3670; Blender RGB/Vector/Float 곡선 컴파일 경로 |
| C14 | P1 | Gamma | 영상 불일치 | 일반 색 입력은 ERROR_VALUE를 반환한다. Image 입력 특례는 기존 좌표·투영·필터를 다시 구성하며 연결 Gamma도 별도 문제가 된다. | reader 2298; Blender svm/gamma.h; 720p CPU·Metal |
| C15 | P1 | RGBA Mix 클램프·외삽 | 영상 불일치 | FLOAT/VECTOR와 달리 clamp_result가 적용되지 않고, clamp_factor=false의 MIX 외삽도 엔진의 Mix 제한으로 손실된다. | reader 2796; 720p CPU 확인 |
| C16 | P1 | RGB 혼합 14개 모드 | 경고·대체 | Screen/Overlay/Soft Light/Hue 등 14개 모드를 단순 Mix로 대체한다. Divide의 Cycles 예외 처리와 Factor 경계도 별도 검증이 필요하다. | reader 663; MixRGB·RGBA 조합 전수; Screen 720p |
| C17 | P1 | Vector Math POWER/SIGN | 경고·영상 불일치 | Blender 5.2의 두 연산을 입력 통과로 대체한다. 나머지 연산의 등록과 구분한다. | reader 2809 이후 VectorMath; 720p CPU·Metal |
| C18 | P1 | Map Range 보간·클램프 | 경고·미지원 | Stepped/Smoothstep/Smootherstep은 ERROR_VALUE다. Clamp=false도 항상 클램프하며 역방향 범위·영폭 경계는 추가 실행 검증이 필요하다. | reader 2539; Blender svm/map_range.h |
| C19 | P1 | 흡수+산란 볼륨 Add/Mix | 변환·소스 확정 | 자식 중 clear가 있으면 합성도 clear로 지정한다. scattering 값이 있어도 엔진 ClearVolume은 SigmaS=0이다. | reader 4319; workflow-audit.json; 엔진 parsevolumes.cpp/ClearVolume |
| C20 | P1 | 한쪽이 빈 볼륨 Mix | 변환 확정 | 자식이 하나면 Factor를 적용하지 않고 그대로 반환한다. Factor=.25인 산란 입력도 전체 농도로 반환된다. | reader 4302; workflow-audit.json |
| C21 | P1 | Principled Volume 흑체 | 변환 확정 | Blackbody Intensity=1, Temperature=1500의 상수 발광도 무시하며 경고가 없다. 연결 Temperature/Tint 일부에만 경고한다. | reader 4275; Blender svm/closure.h; workflow-audit.json |
| C22 | P1 | Principled Volume 속성 | 소스 확정 제한 | Density/Color/Temperature Attribute 문자열을 계수에 연결하지 않는다. VDB 재질의 기본 density 이름만으로 밀도 격자를 읽는 경로와 Volume Info를 구분해야 한다. | reader 4275; export/volume.py::_material_volume_defs |
| C23 | P1 | 투명 필름 설정 가져오기 | 실행 변환 실패 | 실제 위치 scene.render.film_transparent 대신 없는 scene.cycles.film_transparent를 읽고 없는 scene.superluxcore.imagepipelines를 탐색한다. 실제 카메라 플래그가 false로 남았다. | operators/cycles_settings.py 140; workflow-audit.json |
| C24 | P1 | 바운스 수 가져오기 | 실행 변환 실패 | 0 total/diffuse/glossy를 건너뛴다. transparent_bounces 대신 transparent_max_bounces를 읽어야 하며 투명·투과 깊이 분리도 필요하다. | operators/cycles_settings.py 44; workflow-audit.json |
| C25 | P1 | 컴포지터 패스 연결 | 실행 변환 실패 | Cycles 플래그로 필름 출력은 일부 생성되지만 update_render_passes는 Combined만 등록하고 _add_passes도 Cycles 패스를 추가하지 않는다. Depth/Albedo는 필름 생성 루프에서도 제외된다. | export/aovs.py 110/136; engine/base.py 233; engine/final.py 280; workflow-audit.json |
| C26 | P1 | 패스 의미·식별자 | 소스 확정 제한 | Diffuse/Glossy/Transmission Color를 모두 ALBEDO로 합친다. Object Index는 Blender pass_index와 다른 해시 ID이며 재질 ID도 직접 보존 경로가 없다. Cycles 패스 이름과 엔진 이름의 연결도 필요하다. | cycles_compat.py::_PASS_OUTPUTS; utils.make_object_id; Blender sync.cpp |
| C27 | P1 | 무수정 모션 블러 전환 | 실행 변환 실패 | Blender render.use_motion_blur와 shutter를 가져오지 않는다. 확장 전용 enable와 물체별 opt-in이 필요하다. 실제 import 후 false/0.1로 남았다. | cycles_settings.py; export/motion_blur.py; workflow-audit.json |
| C28 | P1 | 진짜 변위·범프 모드 | 소스 확정 제한 | 재질 displacement_method에 따른 BUMP/DISPLACEMENT/BOTH를 존중하지 않고 출력 링크만으로 모양을 감싼다. 직접 높이 출력의 범프 대체, 연결 Normal·Scale·Midlevel, 월드 공간과 적응 세분화가 제한된다. | reader 217; object_cache.py::_apply_cycles_displacement; cycles_compat.py 191 |
| C29 | P1 | 벡터 변위 | 소스 확정 제한 | Midlevel을 읽지 않고 offset=0이다. Tangent/World 공간을 Object로 대체한다. 객체 변환·Normal 기준까지 실제 영상 검증이 필요하다. | reader 244; Blender svm/displace.h |
| C30 | P1 | Bump 연결·합성 | 경고·소스 제한 | 연결 Distance/Normal을 무시한다. Filter Width는 노드별 기본값 대신 트리 최대 기본값을 모든 bumped 재질에 적용한다. 다중 범프 체인 의미는 실행 검증이 필요하다. Blender도 Filter Width를 컴파일 시 값으로 사용하므로 연결 폭 자체의 차이는 확정하지 않는다. | reader 79/98/2365; Blender svm/displace.h |
| C31 | P1 | 일반 Normal 벡터 | 소스 검토·실행 미검증 | _normal_input의 일반 벡터 결과를 높이 bumptex로 전달한다. NormalMap·Bump 전용 경로 외의 임의 벡터 법선 의미, 앞/뒷면·비균일 변환을 별도 검증해야 한다. | reader 4107; 엔진 Texture::Bump |
| C32 | P1 | Principled Tangent·Coat Normal | 소스 확정 제한 | OpenPBR 경로는 Tangent를 읽지 않고 Coat Normal을 경고 후 무시한다. 코트와 기저 법선을 분리한 장면은 일치하지 않는다. | reader 938/1024; 활성 Normal 연결 검수 |
| C33 | P1 | Principled Thin Wall·분기 | 소스 확정 제한 | 정확히 full transmission·sharp일 때만 archglass다. 혼합 투과 OpenPBR는 Thin Wall을 사용하지 않으며 해당 분기에서 경고도 없다. 유리 최적화 분기와 코트·SSS·sheen 결합을 다시 검증해야 한다. | reader 1177/1201/1242 |
| C34 | P2 | Principled 모델·SSS | 소스 확정 제한 | distribution/subsurface_method를 OpenPBR 경로에서 선택하지 않는다. Random Walk/Burley/Skin, SSS IOR, fuzz·coat tint 및 박막의 실제 수치 동등성은 별도 판정이 필요하다. | reader 938; Blender scene/shader_nodes.cpp PrincipledBsdfNode |
| C35 | P1 | Diffuse Roughness | 소스 확정 제한 | Roughness 입력을 경고 없이 무시하고 항상 matte를 만든다. | reader 1513; 전체 연결 입력 검수 |
| C36 | P2 | Glass·Refraction 분포·박막 | 소스 확정 제한 | Glass의 Thin Film 입력을 읽지 않는다. sharp/rough/OpenPBR 분기와 Beckmann/GGX/Multiscatter 선택이 Blender의 전체 분포와 동등한지 미검증이다. | reader 1639/1880 이후 |
| C37 | P2 | Anisotropic·Metallic | 경고·소스 제한 | 연결 anisotropy/roughness를 등방성으로 대체하고 rotation/tangent 및 Metallic F82 Edge Tint·박막을 지원하지 않는다. | reader 1698/1748; 전체 모드·연결 입력 검수 |
| C38 | P2 | Principled Hair | 소스 확정 제한 | Coat·Random Roughness·Random Color 및 lobe weight 제어를 읽지 않는다. 연결 melanin은 상수 대체이며 Chiang/Huang 모델 이름 매핑만으로 영상 동등함을 판정할 수 없다. | reader 1820; Blender svm/closure.h; Hair 조합 검수 |
| C39 | P1 | 일반 Add Shader | 경고·소스 제한 | 표면 closure 두 개를 50/50 Mix로 바꿔 에너지를 절반으로 만든다. Transparent가 들어간 Add는 그 자식을 제거한다. 발광 특례와 일반 합성을 구분해야 한다. | reader 1381/1400/1489 |
| C40 | P2 | Toon·Ray Portal·AO·Tangent | 경고·대체 | Toon은 matte, Ray Portal은 transparent, AO는 비차폐 색/1, Tangent는 0이다. 기존 지원 표의 AO/Tangent 설명은 현재 변환과 다르다. | reader 3164/3990 이후; 전체 노드 검수 |
| C41 | P2 | Voronoi 전체 의미 | 경고·소스 제한 | 2D/4D·일부 feature·Color/Position/Radius/W를 근사·대체한다. Detail/Roughness/Lacunarity/Randomness 연결과 프랙털 계산도 전달하지 않는다. | reader 3300; 전체 모드·연결 입력 검수 |
| C42 | P1 | White Noise 해시 | 영상 불일치 | 3D도 Cycles hash_float3_to_float3와 다른 엔진 해시/RNG를 사용한다. 연결된 동일 씨앗의 색이 실제로 다르며 2D/4D는 3D 대체다. | reader 3416; 엔진 texture_whitenoise_funcs.cl; 추가 720p |
| C43 | P2 | Brick·Checker·Gabor | 경고·소스 제한 | Brick 색·배치·mortar smoothing·squash·연결 치수를 근사한다. Checker 연결 Scale은 경고 없이 무시한다. Gabor 3D·연결 파라미터·Orientation이 제한된다. | reader 2178/3445/3492; 전체 노드 검수 |
| C44 | P1 | 텍스처 Vector 소비 경로 | 경고·소스 제한 | 좌표 출력 자체와 텍스처 입력 매핑을 구분해야 한다. 다수 legacy texture의 임의 Vector·Generated·참조 Object 경로가 UV/local 기본값으로 대체된다. 좌표 단독 회귀 통과로 전체 재질을 보장할 수 없다. | reader 813/836; _vector_mapping_defs_impl |
| C45 | P2 | 좌표·Mapping·인스턴스 | 소스 확정 제한 | chained Mapping, 연결 TRS, Texture/Normal 타입, 인스턴스 공간, 변형 전 ORCO와 움직이는 reference/camera 공간 및 다른 뷰포트 카메라에 제한이 있다. | reader 718/629/2967/3067; Blender svm/tex_coord.h |
| C46 | P2 | Normal Map | 경고·소스 제한 | Tangent 외 공간을 지원하지 않는다. uv_map 이름을 이 분기에서 읽지 않으며 연결 Strength는 엔진 Mix 클램프를 거친다. 음수·1 초과 및 여러 UV 층은 별도 영상 검증이 필요하다. | reader 2339; Blender node_shader_normal_map.cc |
| C47 | P1 | 이미지 색 공간 | 소스 확정 제한 | sRGB를 단순 gamma=2.2, 나머지를 gamma=1로 처리한다. OCIO 입력 색 공간·선형 구간·프리멀티플라이 알파 계약을 직접 재현한 것이 아니다. | reader 1579; ImageExporter.export_cycles_node_reader |
| C48 | P2 | 이미지 투영·필터·시퀀스 | 경고·소스 제한 | Cubic/Smart→Linear, Mirror→Repeat, UDIM 한 타일, Movie/Sequence 전용 Cycles 경로 제한, BOX/SPHERE/TUBE 투영과 blend가 다르다. 이미지 있는 실제 변환 조건을 별도 집계했다. | reader 1550/1590; export/image.py 180 이후 |
| C49 | P2 | Geometry·Object·Particle·Point 입력 | 경고·대체 | Pointiness/Random per Island/Tangent, Object Color/Alpha, Particle Age/Lifetime/Velocity 등, Point 중심/Radius, Hair Length/Thickness/Tangent Normal의 부족을 기록한다. | reader 2390/2417/2436/2460/4020; 전체 출력 검수 |
| C50 | P2 | 속성·절차 기하 데이터 | 경고·소스 제한 | edge/string domain과 채널 예산 초과를 지원하지 않는다. Pointcloud는 구 인스턴스이며 Geometry Nodes가 생성한 인메모리 Volume은 지원하지 않는다. | named_attributes.py; pointcloud.py; volume.py 267 |
| C51 | P1 | 공간 볼륨·위상·경계 | 소스 확정 제한 | 복합 볼륨 asymmetry는 산란 계수 가중 대신 단순 혼합이다. 텍스처 world volume은 구간당 한 번 평가하며 material step/interpolation/sampling과 겹친 경계가 다르다. | reader 4350; world.py; volume.py; Blender shader.cpp volume 설정 |
| C52 | P2 | 월드·조명 그래프 | 경고·소스 제한 | 월드는 제한된 Background/환경/Sky 체인, Mix Shader 주 입력 선택, 연결 Strength와 Vector 변환만 처리한다. 일반 조명 색·강도 그래프, Light Falloff·material IES/Sky는 동일하지 않다. | light.py::_convert_cycles_world/_convert_cycles_light |
| C53 | P2 | 빛 연결·가시성·섀도 | 경고·소스 제한 | Shadow Linking 없음, receiver group 예산 제한, Glossy/Transmission/Volume visibility 세분화 부족, per-light max bounce/MIS/caustic 태그 및 shadow-off 제한이다. | cycles_compat.py 65/324/495 |
| C54 | P2 | DOF·파노라마·스테레오 | 실행 변환·소스 제한 | Blender DOF blades/ratio/rotation이 전용 bokeh로 복사되지 않는다. 파노라마 longitude 시작 오프셋·latitude·fisheye와 spherical stereo가 제한된다. | camera.py 152/204; engine/base.py 46; workflow-audit.json |
| C55 | P2 | 시간·토폴로지·뷰포트 | 소스 확정 제한 | rolling shutter/시간 위치·per-object steps·면광원 변환 제한, 셔터 중 topology/strand layout 변경은 static 대체다. 실시간 normal/vector/data 변경·다른 뷰 카메라 일치와 취소 응답은 GUI 재검증이 필요하다. | motion_blur.py; viewport.py/session_worker.py; Blender camera.cpp |
| C56 | P2 | AOV·Cryptomatte·Light Groups·노이즈 제거 | 경고·소스 제한 | Shader AOV·Crypto Asset/Accurate·Environment/Mist/SSS 패스 및 Cycles lightgroup 이름 연결을 지원표와 구분한다. Cycles denoiser 종류·품질·시간 처리·적응 샘플 기준을 동일하게 가져오지 않는다. | cycles_compat.py 559; aovs.py; properties/lightgroups.py; cycles_settings.py |
| C57 | P2 | 제작 장면 수렴·물리 모델 | 이전 검증 잔여 | 멩거·모래 및 향수병의 밝은 노이즈/국소 차이, 감실 coplanar 경계와 화이트 퍼니스 개별 SSS·유리·박막 차이는 이전 720p 보고서에 남아 있다. 이번 단일 노드 검수로 해결되었다고 세지 않는다. | 2026-10-09-production-render.md |
| C58 | P2 | OSL·베이킹·Eevee 전용 기능 | 미지원·별도 범위 | 사용자 OSL, Cycles bake, ShaderToRGB·Freestyle·일부 raster 개념은 일반 Cycles 제작 장면 호환성과 분리해 표시한다. 현재 요청에서 지원된 것으로 세지 않는다. | _UNSUPPORTED_NODE_NOTES; engine/base.py |
| C59 | P2 | 그룹·특성 조합·플랫폼 | 실행 미검증 | 기본 그룹 생성은 출력이 없어서 호출되지 않았다. 중첩·muted graph·shader/volume 경계 조합, 모든 모드의 모든 연결 조합, Windows/Linux/Intel GPU와 GUI 전수 실행은 별도 검증이 필요하다. | 검수 방법의 한계; 공개 ZIP 플랫폼 검증 범위 |
| C60 | P1 | 그룹의 중복 표시 이름 | 실행 변환 실패 | 서로 다른 식별자의 출력 두 개가 같은 표시 이름일 때 두 번째 출력도 첫 번째 출력으로 변환한다. 값 .8을 요청한 실제 그룹이 .1로 변환됐다. Group Input도 이름 조회를 사용하므로 같은 위험이 있으며 별도 실행 검증이 필요하다. | reader 2101/2116; workflow-audit.json duplicate_group_outputs |

## 핵심 수식과 원인

Layer Weight Fresnel은 Blend를 IOR로 바꾸어야 한다. [Blender 원문](https://github.com/blender/blender/blob/9e2066aef7ef7e20c142ad7bd3303138a4304c93/intern/cycles/kernel/svm/fresnel.h)의 `svm_node_layer_weight`는 `eta=max(1-Blend,1e-5)`와 앞/뒷면 분기를 사용한다. Facing은 Blend<.5에서 `2*Blend`, 그 외에서 `.5/(1-Blend)`로 바꾸고 `1-pow(abs(dot),지수)`를 계산한다. 현재 고정 IOR와 직접 blend 지수 경로는 다르다.

[HSV 원문](https://github.com/blender/blender/blob/9e2066aef7ef7e20c142ad7bd3303138a4304c93/intern/cycles/kernel/svm/hsv.h)은 Factor로 변환색과 원색을 혼합한다. 현재 reader는 Factor를 읽지만 정의에 넣지 않는다. ColorRamp는 [RGBA와 별도 Alpha 출력](https://github.com/blender/blender/blob/9e2066aef7ef7e20c142ad7bd3303138a4304c93/intern/cycles/kernel/svm/ramp.h)을 전달해야 하며, 현재 RGB 3채널 band만으로 Alpha를 처리할 수 없다.

볼륨 Add/Mix가 `clear`를 만들면 엔진 `src/slg/scene/parsevolumes.cpp:152`는 산란 텍스처를 읽지 않는다. `src/slg/volumes/clear.cpp:42`의 SigmaS는 0이다. 흡수와 산란을 합친 결과에 scattering 키가 남아 있다는 사실만으로 동작을 보장할 수 없다.

컴포지터는 필름 출력과 RenderEngine 패스 등록이 모두 필요하다. 현재 Cycles 플래그 20종의 엔진 출력 요청을 생성해도 기본 확장 AOV 플래그를 켜지 않으면 등록 목록은 Combined 하나다. DEPTH와 ALBEDO는 필름 출력 생성의 별도 처리에서도 Cycles 요청이 빠진다. 실제 최종 전달·이름·색 패스 분해까지 회귀가 필요하다.

## 증거와 수정 순서

증거는 작업 공간 `test-scenes/validation-2026-10-09/remaining-audit`에 보존한다. 전체 변환 속성·경고·예외는 `node-export-audit.json`, 실제 등록 소켓은 `node-inventory.json`, 워크플로는 `workflow-audit.json`, 선형 영상 수치는 각 CPU/Metal 폴더의 `metrics.json`이다. 원본 EXR와 PNG를 함께 보존한다. 대표 8조건 비교표와 전체 25조건의 Metal 비교표 4장을 생성하고 직접 검토했다. RGBA 결과 클램프는 PNG 표시 단계의 범위 제한 때문에 같은 색처럼 보이지만 선형 EXR에서 차이가 난다. CPU·Metal의 선형 오차를 합친 `render-summary.json`에서는 CPU Vector Map Range 재검증 결과를 사용한다. 기존 metrics의 RGB 평균은 float32 누적 오차가 있을 수 있으므로 판정에 사용하지 않았으며, 스크립트의 후속 실행은 float64 평균을 사용한다.

1. P0 다섯 노드군의 동적 소켓 조회를 고치고 재질 대체가 없음을 검증한다.
2. LayerWeight·HSV·Ramp·Curve·Gamma·RGBA와 WhiteNoise 수식을 고치고 표적 720p 실패를 회귀 게이트로 바꾼다.
3. 흡수/산란 합성과 흑체/VDB 속성, 변위·법선의 의미를 복원한다.
4. 투명 필름·모션·깊이와 컴포지터 패스 이름/데이터 전달을 잇는다.
5. 물리 모델·절차 좌표·조명/세계·시간·인스턴스 조합과 실제 제작 장면을 높은 샘플 수로 검증한다.

[노드별 호출 검수 목록](2026-10-09-node-audit-catalog.md)과 [기계 판독 문제 목록](2026-10-09-remaining-issues.json)을 함께 사용한다. 전체 99% 판정에는 입력/모드/워크플로 합격 집합과 영상 기준을 먼저 명시해야 한다. 이전 [제작 장면 비교](2026-10-09-production-render.md) 및 [배포 검증](2026-10-09-deployment.md)은 해당 범위에서 유효하며 이번 검수의 잔여 문제를 해소한 근거가 아니다.

## 720p 선형 영상 비교 수치

두 엔진의 같은 입력을 비교한 평균 절대 오차다. 오류를 겨냥한 표적 집합이며 전체 호환률의 분모가 아니다. 샘플 수 16의 순수 발광 노드 비교에 한정한다.

| 조건 | 인자 | CPU 평균 절대 오차 | Metal 평균 절대 오차 |
|---|---:|---:|---:|
| layer_fresnel | 0.2 | 0.025672 | 0.025672 |
| layer_fresnel | 0.5 | 0.073596 | 0.073596 |
| layer_fresnel | 0.8 | 0.405672 | 0.405672 |
| layer_facing | 0.2 | 0.568735 | 0.568735 |
| layer_facing | 0.5 | 0.201437 | 0.201437 |
| layer_facing | 0.8 | 0.060743 | 0.060743 |
| hsv_fac | 0 | 0.493333 | 0.493333 |
| hsv_fac | 0.25 | 0.370000 | 0.370000 |
| hsv_fac | 1 | 0.000000 | 0.000000 |
| ramp_alpha | 0.3 | 0.246667 | 0.246667 |
| ramp_hsv | 0.3 | 0.200000 | 0.200000 |
| ramp_ease | 0.3 | 0.028000 | 0.028000 |
| floatcurve_fac | 0 | 0.080000 | 0.080000 |
| floatcurve_fac | 0.25 | 0.060000 | 0.060000 |
| vectorcurve | 0.25 | 0.020000 | 0.020000 |
| gamma | 2 | 0.230000 | 0.230000 |
| noise1d | 0 | 0.565994 | 0.565994 |
| magic | 0 | 0.486525 | 0.486525 |
| maprange_vector | 0 | 0.433333 | 0.433333 |
| vector_sign | 0 | 0.566667 | 0.566667 |
| vector_power | 0 | 0.203333 | 0.203333 |
| rgba_clamp_result | 1 | 0.200000 | 0.200000 |
| rgba_factor_extrapolate | 1.5 | 0.150000 | 0.150000 |
| rgba_screen | 0.5 | 0.070000 | 0.070000 |
| white3d | 0 | 0.303416 | 0.303416 |
