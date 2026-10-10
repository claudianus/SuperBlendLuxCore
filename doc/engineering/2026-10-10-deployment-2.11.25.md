# Verified compatibility deployment 2.11.25, 2026-10-10

기존 Cycles 그래프를 바꾸지 않고 native 품질로 바로 렌더하는 goal은 활성·미완료다. 이번 배포는 Bump 폭0과 standalone SSS의 모든 채널 local diffuse 한계를 보존한다. 제작 씬 전체 호환률이나99% 완료를 뜻하지 않는다.

Cycles Bump Filter Width=0일 때 입력 Normal을 유지하고 GPU texture stack과 hitpoint restoration을 보존한다. 양수 폭과 일반 native Bump는 그대로다. adapter는 standalone SSS의 float32 Scale×Radius가 모든 채널에서 엄격히1e-8 미만이면 원본 local diffuse와 Normal을 보존한다. Value Scale 및 Value/RGB Radius와 textured Scale+zero Radius도 포함한다. 부분0·정확한임계값·일반양수 Radius는 기존 경로를 유지하며 이 세 export control은 SSS visual acceptance가 아니다. 일반 OpenPBR, MIS/PDF/RR와 품질 기본값은 변경하지 않았다.

engine frozen source `48c4659d0691f007a2d9c8a36d3d5c58778bf0a8`, addon frozen source `bf3e0f50bc531d8a931f03f4de9fc606aa8869a3`, exact ARM native SHA `e66147e203246a867f30e5e4e9008fa64a4c7a1767adbd1a92b2f1b2c4bafaa0`다. [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38007003671)와 [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38010633568)가 완료됐다. 네 wheel·네 ZIP의 버전·소스·해시·서명·subject·빌드 invocation을 검증했다. Windows의 CRLF와 정확한 delvewheel bootstrap만 정규화했다. ZIP의 Python372개와 manifest는 설치 파일과 정확히 같고 포함된 engine wheel은 서명된 CI wheel bytes와 같다.

## 실제 렌더 검수

| 단계 | CPU | Metal | 합계 |
| --- | ---: | ---: | ---: |
| exact CI wheel + frozen addon |188|143|331|
| 최종 ZIP 새 설치 |74|74|148|
| 실제 사용자 Blender 설치 |74|74|148|
| 합계 |336|291|627|

CI 각 backend143조건은 기존91(Vector30, Normal Map8/smooth4/image Bump4, scalar displacement6, Backfacing8, emitter9, zero export9/zero render7, Height0 6)에 Bump39(RGB25, spectral7, smooth7)와 SSS local limit13을 더한 것이다. CI CPU에는 native space16/context12/legacy4/Mikk13을 더했다. SSS13 중10조건은720p spectral64spp paired render이고3조건은 export-only다. 새 ZIP·실제 설치는 exact native/Python372개의 byte 일치를 확인하고 변경 영향에 맞춘74조건(zero export9, zero render7, SSS13, Bump39, Height0 6)을 CPU·Metal에서 다시 검수했다. CI에서 통과한 변경되지 않은 이전 발광·Vector/Normal 검사는 설치마다 반복하지 않았다. 검사·변환 조건 및 설치별 반복을 합친 수이며 독립 제작 씬 수나 호환률이 아니다. 원본 그래프 fingerprint, finite pixels, 변환 오류, 현재 native/source hashes와 실제 Metal backend를 guard했다.

CI에서 Vector8·기존 재질7·Bump11·SSS3 비교시트29장, 새 ZIP·실제 설치에서 zero 재질2·Bump11·SSS3 각각16장씩 총61장을 직접 확인했다. Normal 방향·색·displacement geometry·front/back emission·valid-zero·Sheen·diffuse SSS와 linked Normal 형태를 검토했다. 기본 native spectral 재질 beauty720p/128spp CPU·Metal2장도 직접 확인했다. SSS의 linked Normal은 좁은 fixture의2.5% 평균밝기 허용값으로 검수했으며 픽셀 동일성은 요구하지 않는다. node census1023조건 exception0/warning240은 렌더 검사와 별도다.

네 플랫폼 빌드와 engine·bundle NVRTC 각각23 CUDA program compile을 통과했다. Nvidia 실장비 렌더, 다른 플랫폼 Blender/GPU 렌더와 Intel CI runtime smoke(skipped)는 미검증이다.

## 사용자 설치와 남은 범위

실제 Blender5.2.1LTS(`9e2066aef7ef`) 사용자 profile의 native·package·manifest는2.11.25다. 최종 ZIP과 Python372개·manifest가 같다. CLI 업그레이드 중 기존 RNA 등록 진단3개는 exit0이며 이후 fresh payload 및148개 실제 회귀에는 진단이 없다. 실행 중 GUI hot reload는 미검증이다. 이전2.11.24 full extension/native/wheel/config/userpref의 private rollback archive를 사용자 로컬에 보존했다.

[일반 양수 standalone SSS](2026-10-10-cycles-positive-sss-diagnostic.md)는 여전히 미해결이다. exact2.11.25 CI native에서도720p spectral Metal RANDOM_WALK/Scale.15/Roughness0의 native/Cycles mean ratio0.0510781과 거의 검은 이미지를 확인했다. bulk-volume 경계의 일반 문제를 이 local limit 수정으로 해결했다고 주장하지 않는다. 상수 RGB→Float Scale wrapper의 zero routing(export 진단·render 미검증), partial/dynamic Radius, Ashikhmin Sheen, scalar World/linked Normal, curved true-displacement Bump footprint, Vector BUMP/BOTH/displaced attributes, 제작 씬·GUI·viewport/F12·pass·workflow 등의 남은 범위를 계속 작업한다. 실험용 SSS IOR/shadow/boundary override는 배포하지 않았다. OSL·baking은 기존 유보 범위를 유지한다.

세 레포는 main과 기본 worktree만 남기는 정리 상태를 확인한다. 문서 후속 commit과 release frozen source는 구분한다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.25-linux_x64.zip | `280dfb3cc31644258bc7d2318a10eb34a6fbf1e04fa10f8456191585158b5935` |
| SuperLuxCore-2.11.25-macos_arm64.zip | `8da5eb008d78d56e6cd03ee2dbd302d2625e09a3fd8614a1a4ab436a460791ef` |
| SuperLuxCore-2.11.25-macos_x64.zip | `04e8f24cfa063c68a6d5cc894fc412ce8f25cbd65b0b8c3e14bdd276368bf274` |
| SuperLuxCore-2.11.25-windows_x64.zip | `f88c0c5f252722b82dbc30d5f9c498d6e17ba7638d956080d4f7f94bfa7d1e64` |

증거: workspace `test-scenes/validation-2026-10-10/compatibility-deployment-2.11.25`의 source/runtime/proof/CI/attestation와 EXR/PNG, 별도 private rollback archive.

## Public release completion

[Engine2.11.25](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.25)와 [artist-facing ZIP2.11.25](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.25)를 정식 공개했다. 두 Git tag와 target commit은 위 frozen source를 가리키고 네 public ZIP의 서버 digest는 검수한 CI/서명 bytes와 같다. 실제 사용자 설치는2.11.25이며 전체 호환 goal은 활성·미완료다. 문서의 후속 main commit은 release frozen source와 구분한다.
