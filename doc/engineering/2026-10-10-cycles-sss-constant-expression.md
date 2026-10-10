# Cycles SSS constant arithmetic inputs, 2026-10-10

기존 Cycles 그래프를 변경하지 않고 native 품질로 바로 렌더하는 전체 goal은 활성·미완료다. 현재 공개·실제 사용자 설치는 [검수한2.11.27](2026-10-10-deployment-2.11.27.md)이다. 아래 private2.11.26 후보 수치는 역사적 수정 검수이고, 현재27의 공식 빌드·최종 ZIP·실제 설치 검수는 마지막 절에 구분한다.

## 결함과 수정

SSS Scale/Radius에 연결한 Math ADD(0,0), SUBTRACT(.25,.25), MULTIPLY(0,.15), DIVIDE(0,2), tiny arithmetic, Clamp와 중첩 산술·연결 Value/RGB·Vector SUBTRACT가 상수 표현식으로 해석되지 않아 local diffuse 대신 OpenPBR bulk 경로로 들어갔다. 수정 전 공개2.11.26의18조건 export 진단에서13조건이 이 routing에 실패했다. exact2.11.26 native720p spectral64spp Metal Math ADD Scale0의 native/Cycles mean ratio는 0.04934157이며 원본 graph를 유지한 native 이미지가 거의 검게 보였다.

SSS 전용의 bounded resolver를 add/subtract/scale/divide/clamp로 확장한다. 기존 constfloat1/3, makefloat3 및 dotproduct와 함께 모든 피연산자가 상수일 때만 평가한다. 각 산술 결과를 float32로 양자화하고 기존 all-channel strict Scale×Radius<1e-8 판정을 유지한다. cycle/depth16 guard 및 해석할 수 없는 texture/geometry 입력의 원래 경로를 유지한다. 동적 Math나 정확한 임계값·일반 양수 입력을 임의의 matte로 바꾸지 않는다. 원본 노드·설정·연결은 그대로이며 native material/kernel·OpenPBR·PDF/MIS/RR·품질 기본값은 바뀌지 않았다. 엔진 버전 metadata만 add-on/native lockstep을 위해27로 준비했다.

## 제한된 private 검수

공개2.11.26 exact native SHA `43c2f6df5193e4b5953fc533c3fd0ef945486f108d2048b4ceedb55779c42a31`에 candidate reader `7dd35540ac9a1fcffdbd4b1aeb2684957f51164e799a30b93cc6d271fcb6a235`를 격리한 전체ZIP 복제 프로필에서 검사했다. Python373개는 frozen26 source와 같고 reader만 위 후보로 바뀐다. native/source hashes, graph fingerprint, finite pixels, 경고·오류 허용 목록, fresh registration 및 실제 METAL_GPU backend를 guard했다.

CPU41·Metal41 총82조건이 통과했다. backend당 새18조건 중13조건은 paired720p spectral64spp render이고5조건은 양수2·Clamp 양수·정확한 임계값·dynamic UV Math의 export controls다. 기존 coercion10 및 local-limit13도 통과했다. 새13조건 native/Cycles 평균 비는 약1.00118이고 scoped2.5% 허용값 안이다. 새4 비교시트와 공개→후보 before/after1장, 총5장을 직접 확인해 실루엣·명암·방향과 국소 확산 의미를 검토했다. baseline export·실패 render와 최종 portable fixture18 export는82 native 조건에 합산하지 않는다. fixture를 정리할 때 AST가 같음을 확인했고 최종 portable18조건을 다시 통과했다.

이는 native26을 사용하는 private 후보 증거이다. native27 빌드, 다른 플랫폼 Blender/GPU, 최종 ZIP 및 실제 사용자 설치 성공을 뜻하지 않는다. 일반 양의 반경 standalone SSS는 exact26에서도 실패하고 이번 수정으로 해결되지 않는다. 일반 Math/Mix/Curve 표현식과 동적·부분채널 radius, Skin/Burley/Legacy 및 제작 워크플로를 완료로 세지 않는다. 사용자 OSL/baking은 기존 유보 범위를 유지한다.

근거: Desktop code의 Blender5.2 kernel/closure/bssrdf.h float radius local limit, kernel/svm/math.h 및 adapter의 Math/Vector socket 변환. native math/add.cpp,subtract.cpp,scale.cpp,divide.cpp,clamp.cpp의 평가 계약을 확인했다. 증거: workspace `test-scenes/validation-2026-10-10/sss-constant-expression-candidate`의 source/guard/metrics/EXR/PNG/QA/proof.

Canonical 레포 fixture의 strict18 export도 별도로 통과했다. reader bytes는 private 검수와 같고 source/version27 준비는 main에 반영한다. 이 당시의 공개·실제 설치26 및 private 후보 증거와 아래의 공식27 배포 검수를 구분한다.

## Verified2.11.27 deployment

현재 exact27 native `d29c2387496c2bb94700b7cbe09a4bb9cdde5c6f225056c6309e8dd3d752b2bf`와 frozen addon `70822369438f41f168216085af3d649cf9aac128`를 공식CI, 최종ZIP 새 설치 및 실제 사용자 Blender CPU·Metal에서 검수하고 배포했다.154 guarded conditions·17 직접 검토한 비교시트·2 native beauty 및 전체374PY/manifest/wheel bytes 검수는 [배포 기록](2026-10-10-deployment-2.11.27.md)에 따른다. private26 후보82조건·5시트를 현재27 수용 수치에 합산하지 않는다. 일반 양수 standalone SSS는 여전히 실패다.
