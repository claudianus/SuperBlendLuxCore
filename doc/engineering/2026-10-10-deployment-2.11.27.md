# Verified compatibility deployment 2.11.27, 2026-10-10

기존 Cycles 노드·설정 씬을 수동 변환 없이 SuperLuxCore 품질로 바로 렌더하는 전체 goal은 활성·미완료다. 이번 수정은 standalone SSS Scale·Radius에 연결된 상수 Math·Clamp·중첩 표현식이 0 또는 극소 반경을 만들 때 원본의 국소 확산 의미를 보존한다. 제작 씬 전체 호환률이나 99% 완료를 뜻하지 않는다.

제한된 상수 해석기가 add/subtract/scale/divide/clamp를 기존 constfloat1/3, makefloat3, dotproduct와 함께 평가한다. 모든 피연산자가 상수여야 하며 각 연산 결과는 float32로 양자화한다. cycle/depth16 guard를 적용하고 동적·지원하지 않는 식은 기존 경로를 유지한다. Cycles의 float32 Scale×Radius가 모든 채널에서 엄격히1e-8 미만이면 local diffuse와 입력 Normal을 보존한다. 정확한 임계값·양수 입력은 이 국소 경로로 바꾸지 않는다. 원본 Cycles 그래프는 수정하지 않는다. native material/kernel은2.11.25 이후 변경되지 않았으며 버전 metadata만 add-on/native lockstep으로 올렸다. PDF/MIS/RR 및 품질 기본값을 유지한다.

Frozen engine `3c0aff0ff3b262305bd78d3082556f76c3aeb16a`, addon `70822369438f41f168216085af3d649cf9aac128`, exact ARM native SHA `d29c2387496c2bb94700b7cbe09a4bb9cdde5c6f225056c6309e8dd3d752b2bf`다. [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38016464226)와 [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38018750061)의 전체 완료·성공을 확인했다. 네 wheel·네 ZIP의 버전·소스·해시·서명·subject·빌드 invocation을 검증했다. Windows는 정확한 delvewheel bootstrap 및 CRLF만 정규화했다. ZIP의 full wheel bytes는 서명된 CI wheel과 같고, 새 설치와 실제 사용자 설치의 Python374개 및 manifest는 최종 ZIP bytes와 같다. 실행 중 GUI의 native hot reload는 가정하지 않는다.

## 현재 빌드의 검수

| 단계 | CPU | Metal | 합계 |
| --- | ---: | ---: | ---: |
| exact CI wheel + frozen addon |41|41|82|
| 최종 ZIP 새 설치 |18|18|36|
| 실제 사용자 Blender 설치 |18|18|36|
| 합계 |77|77|154|

CI 각 backend는 새 표현식18조건(13 paired720p spectral64spp render +5 export-only controls), 기존 RGB/Vector coercion10조건(6 render +4 controls), local diffuse limit13조건(10 render +3 controls)을 검사했다. 최종 ZIP 및 실제 설치는 full payload byte 일치를 확인한 뒤 새 표현식18조건을 CPU·Metal에서 다시 검사했다. graph fingerprint, native/source hashes, finite pixels, 오류·경고 허용 목록 및 실제 METAL_GPU backend를 강제했다. 이 좁은 local diffuse fixture의 평균 밝기 허용값은2.5%이며 비트 동일성은 요구하지 않는다.154는 설치별 반복 검사·변환 조건의 합계이고 독립 제작 씬 수나 호환률이 아니다. private2.11.26 native 후보의82조건·5시트와 역사적2.11.25 검사는 현재 수용154조건에 더하지 않는다.

CI9장·새 ZIP4장·실제 설치4장 총17 비교시트를 직접 확인했다. 방향·실루엣·명암 및 linked Normal 응답을 검토했다. 기본 native spectral720p/128spp CPU·Metal beauty2장도 직접 확인했다. 절차적 diffuse, metallic highlights, glass, floor shadows와 이미지 방향을 확인했고 denoise-off128spp 잔여 noise는 보인다. 이 확인은 일반 SSS/제작 씬 전체 parity나 성능 측정이 아니다. 별도의 node census1023조건은 exception0/warning240이며 렌더 수용 검사가 아니다.

Engine·bundle NVRTC 각각23 CUDA 프로그램과 네 플랫폼 빌드를 통과했다. NVIDIA 실장비, 다른 플랫폼 Blender/GPU와 Intel CI runtime smoke(skipped)는 미검증이다.

## 실제 설치와 잔여 결함

Blender5.2.1LTS(`9e2066aef7ef`) 사용자 profile의 native/package/manifest는2.11.27이다. CLI 업그레이드의 기존 RNA 진단 3개는 exit0이며 이후 fresh payload와 실제 검사의 등록 진단은0이다. 이전2.11.26 full extension/native/wheel/config/userpref를 private rollback archive로 보존했다. Private archive는 GitHub 배포에 포함하지 않는다.

일반 양수 standalone SSS는 exact2.11.27에서도 실패한다. unchanged RANDOM_WALK, Scale.15, Roughness0의 Metal720p spectral64spp native/Cycles mean ratio는 0.0476042다. literal/linked 두 비교 이미지를 직접 확인했고 모두 거의 검게 보였다. 내부 literal/linked `passed`를 cross-engine parity로 취급하지 않으며154 수용 조건에서 제외한다.2.11.26 LT-OFF 보조 진단도 ratio0.0499917로 실패했고 path.hybridbackforward.enable=0을 실제 로그에서 확인했다. 이전2.11.25 깊이128 보조 실험도 해결하지 못했다. 이 override들을 배포하지 않았다. [양수 SSS 계약 진단](2026-10-10-cycles-positive-sss-diagnostic.md)을 따라 실제 BSSRDF 구현을 계속한다.

부분·동적 Radius/일반 표현식, Ashikhmin Sheen, scalar World·linked Normal, curved true-displacement Bump footprint, Vector BUMP/BOTH/displaced attributes, 이미지 매핑·pass·제작 씬·GUI·viewport/F12 등 전체 남은 범위를 유지한다. 사용자 OSL·baking은 기존 유보 범위다.2.11.26 GUI에서 실제F12와 기본CPU viewport의 표시는 검수했으나 API pixel-size 변경의 즉시 반영은 확정하지 않았다. 이 별도GUI 증거를 현재27 설치 검수154조건에 더하지 않는다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.27-linux_x64.zip | `df77700d23decbf3eae965a8bb5b92149a656e4d15eaa0e48017f3a4ed858560` |
| SuperLuxCore-2.11.27-macos_arm64.zip | `cf4edf0aaa0df9dfcc4e8485805623acf8136a4f9c1b3d506aab085fc40a7141` |
| SuperLuxCore-2.11.27-macos_x64.zip | `db30352b0b692c7e3221a1e88de7d96684b56fec944ad790a3cc016677f5801d` |
| SuperLuxCore-2.11.27-windows_x64.zip | `3a41bb86cb6dc11cfaf64c057950fe48435778faeef319e3383c174d62a67fb4` |

증거: workspace `test-scenes/validation-2026-10-10/compatibility-deployment-2.11.27`의 proof/source/runtime/CI/attestation와 EXR/PNG. 전체 goal은 계속 활성·미완료다.

## Public release completion

[Engine2.11.27](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.27)와 [artist-facing ZIP2.11.27](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.27)를 정식 공개했다. 두 tag와 target은 frozen source를 가리키고 네 public ZIP 서버 digest는 검수한 CI/서명 bytes와 같다. 실제 설치는2.11.27이며 전체 goal은 계속 활성·미완료다. 문서 후속 main commit과 frozen release source는 구분한다.
