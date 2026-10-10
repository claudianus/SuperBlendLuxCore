# Cycles standalone positive SSS diagnostic, 2026-10-10

전체 호환 goal은 활성·미완료다. 이 기록은 2.11.24의 확정 잔여 결함과 보조 실험이며 제작용 수정을 뜻하지 않는다.

Blender 5.2.1 LTS 원본 `9e2066aef7ef7e20c142ad7bd3303138a4304c93`의 `blender/shader.cpp`에서 standalone Subsurface Scattering의 RANDOM_WALK는 `CLOSURE_BSSRDF_RANDOM_WALK_ID`로 매핑된다. `integrator/subsurface.h`는 IOR·Roughness에 따른 진입 방향을 샘플링하고 random walk 이후 출구에 가중치1 diffuse BSDF를 만든다. `subsurface_random_walk.h`는 해당 모드의 Van de Hulst 계수와 경계에서 평가한 albedo/radius를 사용하며 closure weight의 albedo를 나누어 중복 착색을 피한다. Skin과 Legacy의 처리는 별도다.

현재 adapter는 양수 Scale을 native OpenPBR 굴절 경계와 implicit CB15 bulk volume에 매핑한다. 원본의 standalone BSSRDF 계약과 구분해야 한다. 일반 OpenPBR, native 품질 기본값, PDF/MIS/RR 계약은 이 실험에서 수정하지 않았다.

## 현재 배포 엔진의 확정 진단

정확한 CI ARM 2.11.24 wheel, native SHA `c7439663dcbf734ce5296dee46bf3ed85d689c7381cbaa15330f4c24d0dff322`, adapter reader SHA `272410a7422a61d9a13c6a2d51a77aa1eee0059d234eb5b348623ef7ab86ec12`로 새 프로세스에서 검사했다. 동일한 Cycles 그래프를 유지했고 양수 Scale .15, Color .45, 기본 Radius, Roughness0, RANDOM_WALK, 1280×720, 64spp, spectral Metal을 사용했다. denoise·noise halt·clamp는 진단에서 껐다.

Cycles 선형 RGB 전체 평균은 0.0257641170, 수정하지 않은 native 결과는 0.0013268745로 비율 0.0515009다. 현재 native PNG도 직접 확인했다. 이 조건의 영상 호환은 실패다. 모든 양수 SSS 조건이나 Principled SSS 전체로 일반화하지 않는다. 2.11.24의 zero-Scale 로컬 Lambert 한계 통과와도 별개다.

## 보조 경계·계수 실험

아래는 원본 그래프를 바꾸지 않고 임시 프로세스의 native 속성만 바꾼 후보다. 설정·표면 모델이 변경되었으므로 production acceptance와 호환률에 포함하지 않는다.

| 2.11.24 후보 | native/Cycles 평균 비율 |
| --- | ---: |
| IOR1.4, specular0, shadow pass-through, CB15 | 0.551552 |
| IOR1.4, specular0, shadow pass-through, Van de Hulst | 0.450698 |
| IOR1, specular0, shadow pass-through, Van de Hulst | 0.938721 |
| null boundary, Van de Hulst | 0.932281 |

앞선 private 2.11.23 native `0833c117bcdeb517c5d5c1eff9eb03202557e255aca23919a548e3e5896643e8`의 IOR1+shadow+CB15 후보는 약95.3%였으나 공개 wheel과 구분한다. IOR1 후보들은 원본 IOR·진입·출구 의미를 보존했다고 검증하지 않았으며 배포하지 않았다.

기존 two-sided material의 null/glass 진입과 diffuse-transmission 출구를 조합한 추가 모델은 경고 허용 목록을 강제한 검사에서 평균 비율 약0.00130/0.000445로 실패했다. LT-OFF 보조 실행도 해결하지 못했다. 초기 네 실행은 변환기의 root 이름 불변식을 어겨 __CLAY__ fallback을 렌더했으므로 모두 제외했다. 참조 순서를 고친 이후의 strict 결과와 제외 사유를 각각 보존했다. 이름을 반환하는 과정과 경고를 검사해야 실제 후보를 평가할 수 있다.

## 다음 구현 계약

진입 시의 IOR·Roughness·Normal 및 closure weight, 원본 메서드의 내부 산란 계수, 출구 Normal·diffuse 처리, 물체와 volume 경계 상태를 함께 다뤄야 한다. 임의의 shadow override나 IOR 제거를 정식 수정으로 취급하지 않는다. 텍스처가 경계에서 평가되는 의미, mixed closures, per-channel/dynamic zero radius, Skin/Burley/Legacy, CPU·Metal 공통 경로와 양방향 PDF/MIS를 검수해야 한다. 기본 OpenPBR 품질 정책을 변경하지 않는다.

증거는 작업 공간 `test-scenes/validation-2026-10-10/zero-subsurface-microfiber-candidate/positive-sss-source-mapping-24`와 `positive-sss-exit-diagnostic-24`에 원본 소스, scripts, runtime identity, EXR/PNG, 로그, strict/제외 proof로 보존한다.

## Exact 2.11.25 recheck

새 frozen adapter와 exact2.11.25 CI native `e66147e203246a867f30e5e4e9008fa64a4c7a1767adbd1a92b2f1b2c4bafaa0`에서 동일한720p spectral64spp Metal 조건을 다시 검수했다. Cycles literal mean0.0257641170, native0.0013159815로 native/Cycles 비0.0510781이며 두 이미지를 직접 확인했다. native는 여전히 거의 검게 보이며 영상 호환은 실패다. 원본 graph는 그대로이고 native/linked Mean 차이 검사는 통과하지만 그 `passed` 필드는 cross-engine SSS 호환을 뜻하지 않는다. 이 진단을 배포 수용 검사627개에 포함하지 않는다. 이번 모든 채널 local diffuse limit 수정과 일반 양수 Radius의 이 결함은 구분한다. 증거는 `test-scenes/validation-2026-10-10/compatibility-deployment-2.11.25/positive-sss-diagnostic`에 보존한다.

추가 constant RGB(0,0,0)→SSS Scale 연결을 현재 native/source guard로 export 진단했다. `_socket`의 Color→Float가 `dotproduct` texture wrapper가 되므로 현재 local-limit resolver가 이를 상수0으로 해석하지 못하고 OpenPBR를 유지한다. 예상한 local diffuse routing과 다르다. graph는 그대로이며 이 추가 probe는 render를 실행하지 않았고 수용 검사 수에 포함하지 않는다. Value Scale와 RGB Radius의 검증 범위를 RGB Scale 전반으로 일반화하지 않는다. 증거: `compatibility-deployment-2.11.25/sss-rgb-scale-probe`.

상수 RGB/Vector→Scale의 후속 수정과 private 검수는 [Scale coercion 기록](2026-10-10-cycles-sss-scale-coercion.md)에 따로 기록한다. 공개2.11.25의 probe는 역사적 재현으로 남긴다. 이 수정은 일반 양수 SSS transport의 결함을 해결하지 않는다.
