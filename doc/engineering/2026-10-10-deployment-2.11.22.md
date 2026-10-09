# SuperLuxCore 2.11.22 공개 ZIP 및 macOS Blender 배포

범위: 기존 Cycles의 true Vector Displacement Object/World/Tangent 공간, 연결 Scale/Midlevel, 정상 0 입력을 원본 그래프·UV·메시 변경 없이 렌더한다. Native Spectral·OpenPBR 품질 정책과 전송 추정기는 유지한다. 전체 호환 goal은 활성·미완료다.

엔진 소스 bd1bfff02c4661ca2a41fefb595b8280fc06e16f, wheel CI 37984419834. 확장 소스 9fcf4e873e04acbda387568f3d0ff0e708053a57, bundle CI 37987937078 attempt 2. 최초 번들 실패는 버전 릴리스에 원본 휠 자산이 없던 문제였고, 동일한 서명된 CI 휠 네 개를 추가한 뒤 재실행했다. 공개 엔진 릴리스에는 원본 휠과 플랫폼 ZIP 둘 다 있다.

네 플랫폼의 metadata/source/hash/signature/source commit/build invocation/subject 검증 통과. Windows의 고정 delvewheel 1.13.2 초기화 블록 세 개와 CRLF만 허용해 원본 Python을 대조했다. 최종 확장 ZIP은 각 368개 Python 소스가 일치하고 포함 엔진 휠도 CI 휠과 정확히 같다. Windows/Linux/ARM installed smoke 통과, Intel runner runtime smoke 생략. 타 플랫폼 실제 Blender/GPU 검증을 뜻하지 않는다.

CI의 native 29개와 Blender CPU·Metal 92개, 합계 121개 검사 통과. 정상 Height=0 추가 12개 검사 통과. 1280×720, Spectral ON, denoiser/noise halt OFF. Node export 1,023조건은 예외 0, 경고 239이며 렌더 호환률이 아니다. 비교 시트 6개와 64-sample native beauty 6개/Cycles 기준 3개를 직접 확인했다. 곡면의 UV 없는 접선 seam은 Cycles에도 존재한다. Native noise/경계·수렴 차이는 동일하다고 주장하지 않는다.

ARM native SHA-256 e5198b1edc3e9f30222d54b098f91c03d097f37277db5774260dc254fa3dad7c. Pybind11 default argument의 translation-unit 간 ABI 불일치를 모든 binding TU의 공통 compile definition으로 수정했다. Windows/Linux import crash와 Windows MSYS DLL 경로 수집도 해결했다.

최종 새 프로필 CPU·Metal 104개, 실제 사용자 설치 CPU·Metal 104개 검사를 통과했다. 각 단계는 Vector 24개, Normal Map/smooth/image Bump 16개, scalar displacement 6개와 Height=0 추가 6개씩이다. CI 121개와 Height=0 추가 12개를 합쳐 전체 341개 표적·회귀 검사다. 독립 제작 씬 341개나 호환률을 의미하지 않는다. CI·최종·실제 단계의 Vector 비교 시트 18개 및 0 입력 시트 3개를 직접 확인했다.

실제 Blender 5.2.1 LTS (`9e2066aef7ef`)의 `/Users/modumaru/Library/Application Support/Blender/5.2`에서 로드된 native·dist-info·manifest 버전은 2.11.22다. 실제 Python 368개와 manifest는 최종 ZIP과 정확히 같다. `blc_settings.json`의 `wheel_source=0`은 PYPI enum이며 이미 설치된 번들 휠의 fast path를 사용한다. 업그레이드 CLI의 기존 RNA 등록 진단 3개는 종료 코드 0이었고, 이후 새 실제 프로세스의 등록·104개 렌더 검사에는 해당 진단이 없다. GUI의 기존 프로세스 핫리로드는 미검증이다. 실제 이전 2.11.21의 확장·native 패키지·설정·userpref는 workspace `test-scenes/validation-2026-10-10/vector-displacement-2.11.22/previous-install-2.11.21`에 보관했다.

**확인된 CUDA 제한:** 네 플랫폼 wheel 빌드/import smoke와 macOS CPU·Metal 검증은 NVIDIA CUDA 커널 컴파일을 실행하지 않았다. 공개 직후 반영된 원격 수정 `af7b918f796311960dd8753a40488a3d850c94cf`는 2.11.21/22의 OpenCL 벡터 리터럴·scalar→float3·any 비교·sign 누락 및 CUDA vstore4 구현 오류를 수정했다. 2.11.22 Windows/Linux NVIDIA CUDA 경로는 컴파일 실패로 미지원 상태다. 이 제한은 두 공개 릴리스 설명에도 기록했다. 버전 2.11.23과 NVRTC의 실제 커널 컴파일 게이트가 main에 반영됐으며 [CI 37989036418](https://github.com/claudianus/SuperLuxCore/actions/runs/37989036418)의 NVRTC 검사와 ARM 빌드가 통과했다. 네 플랫폼·새 ZIP·설치 검증은 이 문서 시점에 진행 중이다. CUDA 수정 완료/실제 NVIDIA 렌더 완료를 주장하지 않는다.

잔여: Vector BUMP/BOTH, scalar World/linked Normal, true displacement Geometry Incoming 및 곡면 Bump 미분값, 변위 후 Normal Map attributes, adaptive/cage/mixed-material/group/제작 GUI와 타 플랫폼 실렌더. 픽셀 일치·99% 완료를 주장하지 않는다. OSL/베이킹은 기존 유보 범위다.

검증 원본과 서명·CI/실제 runtime guard 로그는 workspace `test-scenes/validation-2026-10-10/vector-displacement-2.11.22`에 보존한다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.22-linux_x64.zip | `de6352f66e57cd273cd7458cccaae5748805fcbe210550f6081835ff702c0a81` |
| SuperLuxCore-2.11.22-macos_arm64.zip | `26dead39046dfd7bd2b9ceb5122fb3cb5fa60428038d4c741045ada2ac9ec165` |
| SuperLuxCore-2.11.22-macos_x64.zip | `e14b81a734b34607f5e1ace919c99e030d941510a10ea33008e3225f15d481ac` |
| SuperLuxCore-2.11.22-windows_x64.zip | `61071cde624fb431415818204d9b640a34bb86178f7aac5db60ae04727463d85` |
