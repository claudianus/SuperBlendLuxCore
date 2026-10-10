# Verified compatibility deployment 2.11.26, 2026-10-10

기존 Cycles 그래프를 변경하지 않고 SuperLuxCore 품질로 바로 렌더하는 전체 goal은 활성·미완료다. 이번 배포는 standalone SSS Scale에 연결된 상수 RGB·Vector의 0 및 극소 값이 원본의 국소 확산 의미로 렌더되도록 수정한다. 제작 씬 전체 호환률이나 99% 완료를 뜻하지 않는다.

RGB→Float의 선형 휘도 dotproduct 및 Vector→Float의 평균, float→Vector makefloat3 변환을 제한된 상수 해석기가 평가한다. Cycles의 float32 Scale×Radius가 모든 채널에서 엄격히 1e-8 미만이면 local diffuse와 입력 Normal을 보존한다. 정확한 임계값·양수·동적 입력의 기존 경로, 원본 그래프와 일반 native OpenPBR는 그대로다. native material/kernel은 2.11.25와 같고 엔진은 add-on/native lockstep을 위한 버전 metadata만 바뀌었다. PDF/MIS/RR 및 품질 기본값을 변경하지 않았다.

engine frozen source `40f07d9248c12b396776e3ff901f68bfb07b514b`, addon frozen source `cf15b9ea76553ced859ec77a57fb19ac9c54c0f6`, exact ARM native SHA `43c2f6df5193e4b5953fc533c3fd0ef945486f108d2048b4ceedb55779c42a31`다. [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38013084262)와 [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38015030851)가 완료됐다. 네 wheel·네 ZIP의 버전·소스·해시·서명·subject·빌드 invocation을 검증했다. Windows는 정확한 delvewheel bootstrap과 CRLF만 정규화했다. 최종 ZIP에 포함된 엔진 wheel은 서명된 CI bytes와 같고, 새 설치 및 실제 사용자 설치의 Python 373개와 manifest는 최종 ZIP bytes와 같다.

## 실제 렌더 검수

| 단계 | CPU | Metal | 합계 |
| --- | ---: | ---: | ---: |
| exact CI wheel + frozen addon |23|23|46|
| 최종 ZIP 새 설치 |10|10|20|
| 실제 사용자 Blender 설치 |10|10|20|
| 합계 |43|43|86|

CI 각 backend에서 새 SSS coercion 10조건(6 paired 720p spectral64spp render, 4 export controls)과 기존 local diffuse limit 13조건(10 paired render, 3 export controls)을 검사했다. 최종 ZIP 및 실제 설치는 전체 native/Python/manifest byte 일치를 확인한 뒤 수정 영향에 맞춘 coercion 10조건을 CPU·Metal에서 다시 검사했다. 변경되지 않은 native kernel에 대한 이전 2.11.25의 627조건은 역사적 증거이며 이번 86조건에 더하지 않는다. 이 수는 검사·변환 조건과 설치별 반복의 합계이고 독립 제작 씬 수 또는 호환률이 아니다. graph fingerprint, finite pixels, 오류·경고 허용 목록, native/source hashes 및 실제 METAL_GPU backend를 강제했다. 좁은 local diffuse fixture의 평균 밝기 허용값은 2.5%이며 비트 동일성은 요구하지 않는다.

CI 비교시트5장, 새 ZIP2장, 실제 설치2장 총9장을 직접 확인했다. 방향·실루엣·명암 및 linked Normal 응답을 검토했다. 기본 native spectral 720p/128spp CPU·Metal beauty2장도 직접 확인해 절차적 diffuse·translucent·glossy/refractive 재질의 색·조명·하이라이트를 검사했다. 128spp 잔여 noise는 보이며 이 확인을 제작 SSS 전체 parity나 성능 측정으로 취급하지 않는다. node census 1023조건 exception0/warning240은 렌더 검사와 별도다.

engine·bundle NVRTC 각각23 CUDA program compile과 네 플랫폼 빌드를 통과했다. NVIDIA 실장비 렌더, 다른 플랫폼 Blender/GPU와 Intel CI runtime smoke(skipped)는 미검증이다.

## 사용자 설치와 남은 범위

실제 Blender5.2.1LTS(`9e2066aef7ef`) 사용자 profile의 native·package·manifest는2.11.26이다. CLI 업그레이드 중 기존 RNA 등록 진단 3개는 exit0이며 이후 fresh payload 및 실제 검사에는 진단이 없다. 실행 중 GUI hot reload는 미검증이다. 이전2.11.25 full extension/native/wheel/config/userpref의 private rollback archive를 사용자 로컬에 보존했다.

[일반 양수 standalone SSS](2026-10-10-cycles-positive-sss-diagnostic.md)는 현재 exact2.11.26에서도 실패한다. 원본720p spectral64spp Metal RANDOM_WALK, Scale.15, Roughness0의 native/Cycles mean ratio는 0.0493380이며 literal/linked 두 비교 이미지를 직접 확인했다. 둘 다 거의 검게 렌더된다. 이 진단의 내부 literal/linked `passed`는 cross-engine 호환을 뜻하지 않으며 배포 수용86조건에서 제외했다. 이전2.11.25의 경로 깊이128 보조 실험도 해결하지 못했다. 임시 IOR/shadow/boundary 및 깊이 override는 배포하지 않았다.

부분·동적 Radius와 일반 그래프 표현식, Ashikhmin Sheen, scalar World/linked Normal, curved true-displacement Bump footprint, Vector BUMP/BOTH/displaced attributes, pass·이미지 매핑·제작 씬·GUI·viewport/F12 등 전체 남은 범위를 계속 작업한다. 사용자 OSL·baking은 기존 유보 범위를 유지한다. 세 레포의 main/origin과 기본 worktree 정리 상태를 확인하며 문서 후속 commit과 release frozen source는 구분한다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.26-linux_x64.zip | `839ec8faea2238427e9bfcd49ac69e8bf9361c73189b239c90d7920cfbacbd14` |
| SuperLuxCore-2.11.26-macos_arm64.zip | `b80f0ad519a99d9d8e82bad1d9d338d039a7dd278479e6211784b0ca66bf3bcc` |
| SuperLuxCore-2.11.26-macos_x64.zip | `e9f00d53dae8bd14305f53745f0b1d5eba0d94dac81b90985d23e0caaace734c` |
| SuperLuxCore-2.11.26-windows_x64.zip | `3960e4b5d0191d2dff10270b0214267a3d16a41f6cac72407a2ffc8aadd10d69` |

증거: workspace `test-scenes/validation-2026-10-10/compatibility-deployment-2.11.26`의 proof/source/runtime/CI/attestation와 EXR/PNG. Private rollback archive는 배포 자산에 포함하지 않는다.

## Public release completion

[Engine2.11.26](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.26)와 [artist-facing ZIP2.11.26](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.26)를 정식 공개했다. 두 Git tag와 target commit은 frozen source를 가리키고 네 public ZIP의 서버 digest는 검수한 CI/서명 bytes와 같다. 실제 사용자 설치는2.11.26이며 전체 호환 goal은 활성·미완료다. 문서 후속 main commit은 release frozen source와 구분한다.
