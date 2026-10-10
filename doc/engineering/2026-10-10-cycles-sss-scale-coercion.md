# Cycles SSS Scale data coercion, 2026-10-10

기존 Cycles 그래프를 수정하지 않고 native 품질로 바로 렌더하는 전체 goal은 활성·미완료다. 현재 공개·실제 사용자 설치는 [검수한2.11.26](2026-10-10-deployment-2.11.26.md)이다. 아래의2.11.25 native/private 후보 수치는 역사적 수정 검수이고, 후속2.11.26 공개·설치 검수는 마지막 절에 구분한다.

## 확인한 결함과 수정

상수 RGB 또는 Combine XYZ 출력을 standalone SSS Scale에 연결하면 `_socket`이 Color→Float의 OCIO luma 계수 또는 Vector→Float의 평균 계수로 `dotproduct` data wrapper를 만든다. 이전 local diffuse resolver는 constfloat1/3만 처리하므로 wrapper 아래의0 또는 아주 작은 상수를 알아내지 못하고 OpenPBR bulk 경로를 유지했다. RGB 검정색, gray/green tiny Scale, Vector0/tiny Scale, RGB0+linked Normal의6개 export 조건이 공개2.11.25에서 실패했다.

exact2.11.25 CI native와 공개 adapter로 RGB(0,0,0)→Scale를720p spectral64spp Metal에서 재현했다. Cycles mean0.0267720483, native0.0013240108로 비율0.04945497이다. 원본 graph는 그대로이며 native 이미지가 거의 검게 보이는 것을 직접 확인했다. 일반 양수 SSS 결함과 별개의 유효한 zero Scale 연결이다.

SSS 전용 resolver가 constfloat1/3, 모든 입력이 상수인 makefloat3, 상수 dotproduct를 따라가 실제 wrapper의 luma/average 계수를 보존한다. cycle 및16단계 depth guard를 두고 해석되지 않는 texture/geometry 입력은 그대로 기존 경로에 남긴다. 결과와 Scale×Radius의 판정은 기존 float32 local diffuse threshold 계약을 따른다. 원본 노드·설정·연결은 변경하지 않는다. 일반 OpenPBR, native material/kernel, MIS/PDF/RR와 품질 기본값은 이 unit에서 수정하지 않았다. 엔진은 add-on/native 버전 lockstep을 위해 release metadata만2.11.26으로 올렸다.

## 제한된 검수

기존 exact2.11.25 native SHA `e66147e203246a867f30e5e4e9008fa64a4c7a1767adbd1a92b2f1b2c4bafaa0`에 candidate reader SHA `0435ad6ec9c1c5ed6f1bd50845fb8964639437d56a003f5512dbd774b6df09a0`를 별도 private 프로필에서 검사했다. native/source hash, 원본 graph fingerprint, finite pixels, 변환 오류, fresh registration diagnostics와 실제 METAL_GPU backend를 guard했다.

CPU23·Metal23 총46조건이 통과했다. 새10조건 중6조건은 Cycles/native paired720p spectral64spp 렌더,4조건은 RGB 정확한 임계값·RGB/Vector 양수·dynamic UV→Scale의 export routing control이다. 기존 local limit13조건도 두 backend에서 통과했다. plain zero/tiny Scale의 native/Cycles mean ratio는 약1.00118이고 RGB0+linked Normal은 약0.98424로 scoped2.5% 허용값 안이다. 비교시트5장과 공개 빌드→후보 before/after1장, 총6장을 직접 확인했다. 최종 portable fixture의 strict export10조건도 따로 확인한다. baseline export·실패 진단 및 fixture port 검사를46개의 native 회귀 조건에 합산하지 않는다.

이 결과는 이 상수 data-wrapper 수정의 private 검수다.2.11.26 CI wheel/ZIP 및 실제 사용자 설치 성공을 뜻하지 않는다. 일반 양수 standalone SSS는 exact2.11.25에서 여전히 native/Cycles mean ratio0.0510781로 실패했다. dynamic/per-channel Radius, 일반 Math/Mix graph의 상수 해석 및 전체 제작 씬·GUI·다른 플랫폼 GPU 검수는 별도 범위다. OSL·baking은 기존 유보 범위를 유지한다.

원본 근거: Desktop code의 Blender5.2 `scene/shader_nodes.cpp` ConvertNode constant_fold, `scene/shader.cpp` linear_rgb_to_gray, `kernel/svm/convert.h`, `kernel/closure/bssrdf.h`. native DotProductTexture는 Spectral::ScopePause로 data channel의 dot을 평가한다. 증거: workspace `test-scenes/validation-2026-10-10/sss-scale-coercion-candidate`의 source, guards, baseline/candidate metrics·EXR·PNG와 reviewed QA.

## Verified 2.11.26 deployment

이 범위의 수정을 exactCI wheel, 최종 ZIP 새 설치 및 실제 사용자 Blender CPU·Metal에서 검수하고2.11.26으로 배포했다. native SHA `43c2f6df5193e4b5953fc533c3fd0ef945486f108d2048b4ceedb55779c42a31`, frozen addon `cf15b9ea76553ced859ec77a57fb19ac9c54c0f6`다.86 guarded conditions·9 비교시트·2 native beauty의 범위와 한계는 [배포 검수 기록](2026-10-10-deployment-2.11.26.md)에 따로 기록한다. private 후보의2.11.25 native 증거는 역사적 기록이며 current26 acceptance와 합산하지 않는다. 일반 양수 SSS는 여전히 실패다.
