# Verified compatibility deployment 2.11.24, 2026-10-10

[Engine wheels-v2.11.24](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.24)와 [Blender extension v2.11.24](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.24)를 공개했다. 두 tag가 아래 source commit과 일치하고 네 공개 ZIP asset digest가 검수한 서명 bytes와 같음을 확인했다. 실제 사용자 Blender 설치도2.11.24다.

기존 Cycles 그래프를 변경하지 않고 native 품질로 렌더하는 goal은 활성·미완료다. 이 배포는 검증한 수정 묶음이며 전체 제작 씬 호환률이나 99% 완료를 뜻하지 않는다.

Object/World true Vector Displacement의 Incoming은 Cycles의 displacement wi=N 계약을 사용한다. Backfacing의 native spectrum 부호를 바로잡아 전면·후면의 발광 Color/Strength를 보존한다. adapter의 정상0과 오류값 비교17곳을 identity로 분리하고 zero SSS Scale의 로컬 Lambert 한계와 Microfiber Sheen의 native SGGX-LTC fuzz 매핑을 반영했다. 일반 OpenPBR와 native 품질 기본값은 유지했다. 이전 Legacy native displacement geometry4조건도 array equality를 검증했다.

원본 engine commit은 `86c0bbf1fb180471fab2abf71c9d92734e9bce8c`, addon commit은 `53e6d9b42f0b7fee828588e84ae05c069b98dee7`다. exact ARM native SHA는 `c7439663dcbf734ce5296dee46bf3ed85d689c7381cbaa15330f4c24d0dff322`다. [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/37998654489)와 [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38002226498)가 완료됐다. Windows/macOS Intel/macOS ARM/Linux의 네 wheel과 네 ZIP에 대해 버전·소스·해시·서명·subject·빌드 invocation을 확인했다. Windows의 CRLF와 정확한 delvewheel1.13.2 부트스트랩만 정규화했다. ZIP Python371개는 frozen addon source와 같고 포함된 wheel 바이트는 engine CI의 서명된 wheel과 같다.

처음 bundle CI는 draft engine release의 Git tag가 없어 실패했다. 검수된 engine release를 정확한 source commit에 고정하여 공개한 뒤 같은 addon source의 재실행이 성공했다. 서명 생성 전의 ARM 프로필은 비공개 provisional 검수였으며 네 서명이 완료된 후 동일한 wheel bytes를 확인했다. 서명 실패를 건너뛰어 공개하지 않았다.

## 검수 범위

| 단계 | CPU | Metal | 합계 |
| --- | ---: | ---: | ---: |
| exact ARM CI wheel와 frozen adapter | 136 | 91 | 227 |
| 최종 ZIP 새 설치 | 91 | 91 | 182 |
| 실제 사용자 Blender 설치 | 91 | 91 | 182 |
| 합계 | 318 | 273 | 591 |

각 설치 backend의91조건은 Vector30, Normal Map8/smooth4/image Bump4, scalar displacement6, Backfacing8, Add/transparent/emitter9, zero export9, zero render7, 추가 Height0 6이다. CI CPU에는 native displacement space16, explicit context12, legacy geometry4, Mikk13을 더했다. 렌더는1280×720이며 단순 검사·변환 조건과 반복 회귀를 합친 숫자다. 독립적인 제작 씬 수나 호환률이 아니다. 원본 EXR·PNG·로그·metrics와 runtime guards를 보존했다. 각 단계의 Vector8·재질7 비교 시트, 총45장을 직접 확인했다.

추가 native 기본 spectral 제작 재질 beauty는720p/128spp, denoise OFF로 CPU·Metal2장을 렌더하고 직접 확인했다. 네 플랫폼 CI 성공과 별도로 engine·bundle NVRTC12.9 gate는 각23 CUDA program compile을 통과했다. NVIDIA 실제 하드웨어 렌더, 다른 플랫폼의 Blender/GPU 실행은 미검증이고 Intel CI runtime smoke는 skipped다.

현재1023조건 node census는 예외0·경고240조건이며 영상 호환 증거와 별개다. ColorRamp의 Alpha/HSV/Ease/linked HSV를 CPU·Metal RGB8조건으로 재확인했고 최대MAE약0.000215다. 추가 spectral16spp8조건과 비교 시트1장은 제한된 진단이며 pixel equality나 모든 HSL·hue 방향·curve mode 완료를 주장하지 않는다. renderer 기본 spectral 설정은 변경하지 않았다. 이 보조16조건은591개 배포 회귀 수에 포함하지 않는다.

## 실제 설치와 남은 범위

실제 Blender5.2.1LTS(`9e2066aef7ef`) 사용자 프로필의 native·dist-info·manifest는2.11.24이며 Python371개와 manifest가 최종 ZIP과 정확히 일치한다. `wheel_source=0`은 PYPI enum으로 이미 설치된 bundled-wheel fast path를 사용한다. CLI 업그레이드의 기존 RNA 등록 진단3개는 exit0이었고 이후 fresh payload 및182개 실제 CPU/Metal 회귀에는 해당 진단이 없다. 실행 중 GUI의 hot reload는 미검증이다. 이전2.11.23 설치·wheel·native·설정의 복구용 백업은 사용자 로컬 작업 공간에 보존했다.

[양수 standalone SSS의 확정 결함과 보조 경계 실험](2026-10-10-cycles-positive-sss-diagnostic.md)은 별도다. 현재2.11.24의 RANDOM_WALK/Scale.15/Roughness0 조건은 native/Cycles 평균 비율약5.2%로 실패한다. 실험용 IOR·shadow·two-sided 경계 변경은 이 배포에 포함하지 않았다. dynamic/per-channel zero SSS, Ashikhmin Sheen, scalar World/linked Normal, curved true-displacement Bump footprint, Vector BUMP/BOTH, displaced attributes, production GUI/workflow 등 남은 범위를 계속 검수한다. OSL·baking은 기존 유보 범위를 유지한다.

세 레포는 main과 기본 worktree만 남기는 정리 상태다. 이 문서에 대한 후속 commit은 배포 태그의 frozen source와 구분한다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.24-linux_x64.zip | `66030d1d86026ebb331eca63d0772b6add62ae2ec889c7b40fe76f25e87fdd20` |
| SuperLuxCore-2.11.24-macos_arm64.zip | `ae2e3a3a09b52ea19b8057cc24a403f0f0fa3ee8d3184145802f68fbd5cf46c7` |
| SuperLuxCore-2.11.24-macos_x64.zip | `fe34fa574d7b03eab9c3c8c496b5f3dcd9ef3d22264930b544192b1e0001fa46` |
| SuperLuxCore-2.11.24-windows_x64.zip | `3c2cad71fae39f7bb58425e33e2891f60b53e78659d80c608f502593735fa84f` |

증거: 작업 공간 `test-scenes/validation-2026-10-10/compatibility-deployment-2.11.24`의 proof, CI/서명/배포 기록, source/runtime identity, EXR/PNG 및 private rollback archive.
