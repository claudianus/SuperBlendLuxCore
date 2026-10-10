# Cycles standalone SSS local diffuse limit, 2026-10-10

공개 2.11.24는 Scale=0을 diffuse로 처리하지만 아주 작은 양수 Scale 또는 모든 채널이 0/작은 Radius이면 bulk volume으로 보내 거의 검게 렌더한다. 이번 어댑터 수정은 Cycles 원본의 모든 채널 local diffuse 한계를 보존한다. 일반 양수 반경의 standalone SSS 문제는 계속 미해결이며 전체 호환 goal은 활성·미완료다. 공개·사용자 설치판은 아직 2.11.24이고 이 수정은 2.11.25 후보다.

## 원본 의미와 구현

Blender 5.2.1 LTS source `9e2066aef7ef7e20c142ad7bd3303138a4304c93`의 `intern/cycles/kernel/closure/bssrdf.h::bssrdf_setup`는 scaled Radius가 float32 `1e-8`보다 작은 채널을 Lambert diffuse로 보낸다. 비교는 엄격한 `<`이며 BSSRDF method별 Radius remap 전에 수행한다. `svm/closure.h`는 Scale와 Radius를 곱한 뒤 0 이상으로 제한한다.

기존 graph를 수정하지 않고 literal 및 constfloat1/constfloat3 Value/RGB 출력을 해석한다. 모든 채널의 float32 Scale×Radius가 임계값 미만이면 기존 Matte 경로와 연결된 Normal을 사용한다. Radius 전체가 0이면 textured Scale도 diffuse다. 정확히 임계값인 채널, 부분 0 반경, 일반 양수 반경은 기존 OpenPBR 경로를 보존한다. 동적 Radius나 채널별 diffuse/BSSRDF 혼합의 일반 구현은 미완료다. 일반 native OpenPBR, PDF/MIS/RR와 품질 기본값은 변경하지 않았다.

## 검수와 한계

공개 2.11.24 native SHA `c7439663dcbf734ce5296dee46bf3ed85d689c7381cbaa15330f4c24d0dff322`와 full package/dylibs/metadata/cached wheel을 격리 profile에서 사용하고 수정 reader SHA `bbb11d9c3ba5e5fa624da585ecb646e26d3d87c1bb61e8c8374cf87e6d298019`를 guard했다. 새 native build가 아닌 어댑터만의 private 후보 검수다.

| 대상 | CPU | Metal |
| --- | ---: | ---: |
| local diffuse 렌더10 + 경계 export-only3 |13|13|
| valid-zero export 회귀 |9|9|
| zero/Sheen/Group 렌더 회귀 |7|7|
| 합계 |29|29|

58개 검사가 모두 통과했다. local diffuse paired render20개는 1280×720, spectral64spp, denoise/noisehalt/clamp OFF다. tiny Scale, zero/tiny Radius, Value links, RGB zero Radius, textured Scale+zero Radius, scaled-below-threshold, linked Normal을 포함한다. 일반9조건의 native/Cycles 평균 밝기 비는 약1.00118, linked Normal은 CPU0.98424117/Metal0.98423842로 약1.576% 낮다. 이 좁은 fixture의 2.5% 허용값을 통과했으며 픽셀 동일성·모든 SSS의 시각 호환을 의미하지 않는다. 정확히 임계값/부분0/일반양수3조건은 export type만 검수했으며 visual acceptance가 아니다.

공개본 CPU의6조건을 별도로 재현했으며 native/Cycles 평균 밝기 비가0.02095〜0.03126으로 거의 검게 나왔다. candidate 비교3장과 공개본 대비2장 총5개 시트를 직접 확인했다. 구체적인 sphere shading·방향·연결 Normal 형태를 보존하고 공개본의 검은 결과를 개선했다. graph/node/socket/link fingerprint가 그대로이고 NaN/변환 오류가 없다. node census1023조건은 exception0/warning 조건240이며 렌더 검사58개와 별도로 기록한다. 임시 메모리 override prototype는 수용 검사 수에 포함하지 않는다.

exact 2.11.25 CI wheel, frozen addon ZIP 및 실제 사용자 Blender 검수·배포는 다음 gate다. 일반 양수 Radius standalone SSS의 brightness/boundary 실패와 Nvidia 실장비, 다른 플랫폼 GPU, GUI hot reload는 완료 주장 대상이 아니다.

증거: workspace `test-scenes/validation-2026-10-10/sss-local-diffuse-limit-candidate`.

## Verified 2.11.25 follow-up

이 문서의 private 수정을 exactCI wheel, 최종 ZIP 및 실제 사용자 Blender의 CPU·Metal에서 재검수하고2.11.25로 배포했다. native SHA `e66147e203246a867f30e5e4e9008fa64a4c7a1767adbd1a92b2f1b2c4bafaa0`, frozen addon `bf3e0f50bc531d8a931f03f4de9fc606aa8869a3`다. 배포 검사627개와 비교시트61장, 기본 native beauty2장의 범위·한계는 [배포 검수 기록](2026-10-10-deployment-2.11.25.md)에 따로 기록한다. private 후보의 native/version/hash는 역사적 증거로 그대로 남긴다. 일반 양수 standalone SSS 등 잔여 호환 범위는 계속 작업한다.
