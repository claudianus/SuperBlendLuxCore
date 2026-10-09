# Cycles valid-zero inputs, zero-radius SSS and Microfiber sheen

기존 Cycles 입력 0을 변환 실패로 오인하던 ERROR_VALUE 비교 17곳을 identity 비교로 수정했다. 실제 Blender RNA에서 SSS Scale/Roughness, Sheen Roughness, 그룹 출력 0에 연결한 Mix/Invert의 5개 오류를 공개 2.11.23 baseline으로 재현했다. 양의 값 대조와 실제 출력 없는 그룹의 경고/fallback은 유지한다.

0을 그대로 전달하는 것만으로는 SSS의 시각 의미가 보존되지 않았다. Blender 5.2.1 소스 9e2066aef7ef7e20c142ad7bd3303138a4304c93의 bssrdf_setup은 radius<1e-8인 채널을 Lambert diffuse로 전환한다. 상수/Value-node Scale<=0일 때 모든 채널의 정확한 표면 극한인 native matte를 사용한다. 양의 Scale은 기존 native bulk model이다. 연결된 Normal도 보존한다. 동적인 0 Scale, 작은 양의 radius 및 부분 채널 radius=0은 별도 잔여다.

기본 Sheen distribution=MICROFIBER를 Charlie로 대체하던 의미 차이도 수정했다. 기본 Microfiber는 native OpenPBR의 SGGX-LTC fuzz로 연결하고 다른 lobe weight는 0으로 설정한다. Blender node_sheen_bsdf.osl/bsdf_sheen.h와 대조했다. ASHIKHMIN은 native Charlie 근사가 남아 있으므로 경고로 노출하며 호환 완료로 세지 않는다. native OpenPBR/전송/품질 기본 정책은 바꾸지 않았다.

Private Blender 5.2.1, 1280×720, Spectral ON, 각64samples, denoiser/noise halt OFF. 매 프로세스의 native/pkg version, native 및 exporter 5개 hash를 확인했다. Native SHA-256은 0833c117bcdeb517c5d5c1eff9eb03202557e255aca23919a548e3e5896643e8이고 private runtime 2.11.23이다. 공개 2.11.23 be60dd8d native와 구분한다.

Live export 9개, CPU 렌더 7개, Metal 렌더 7개의 표적 acceptance(23개)가 통과했다. 초기 prototype 중복은 제외했다. 직접 입력과 Value/그룹 연결의 의미 불변성을 각 엔진 안에서 검사하며 원본 그래프를 바꾸지 않았다. 0 Scale SSS의 Cycles 대비 평균 밝기 차이는 CPU/Metal 약0.12%; Microfiber Roughness .25/.5/1은 약0.6% 이내이고 Roughness0은 두 엔진에서 어두운 극한이다. 모든 색·각도·복합 제작 씬의 완전한 수치 동등성을 뜻하지 않는다.

현재 adapter의 node census는 1023조건/예외0/경고240조건이다. 추가 경고1조건은 Ashikhmin 근사 공개이며 경고가 없는 모든 경우의 영상 호환을 증명하지 않는다. 완료 항목 비교 시트2개와 잔여 SSS 시트1개를 직접 확인했다.

추가 positive-SSS 입력 불변성 진단1개는 별도로 남긴다. Scale .15/Roughness0/SUN 장면에서 native 평균은 Cycles의 약5.3%이며 영상 의미는 아직 호환되지 않는다. 이를 성공한 호환 조건으로 합산하지 않는다. bulk/interface·sampling·산란 파라미터와 method/IOR 계약을 추가 진단해야 한다. 이를 해결하려고 native 품질을 낮추거나 Cycles 억제 설정을 강제로 상속하지 않았다.

소스 수정은 검증한 main 후보이며 공개 ZIP 반영은 미완료다. 2.11.24 engine 86c0bbf1fb180471fab2abf71c9d92734e9bce8c의 네 플랫폼 wheel/NVRTC CI는 37998654489에서 진행 중이다. 실제 사용자 설치는 공개2.11.23을 유지한다. 전체 Cycles 호환 goal은 활성·미완료다.

Evidence: workspace test-scenes/validation-2026-10-10/zero-subsurface-microfiber-candidate. Regression: dev-tools/cycles-zero-input-test.py 및 cycles-zero-render-test.py. Positive-SSS 진단, snapshot shader source, raw EXR/PNG와 원본 로그를 보존한다.
