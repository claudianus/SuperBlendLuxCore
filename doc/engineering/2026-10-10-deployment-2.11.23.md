# SuperLuxCore 2.11.23 CUDA 수정 및 macOS 배포 검수

전체 Cycles 호환 goal은 활성·미완료이며, 비트/픽셀 동일함이나 호환률 99%를 주장하지 않는다. 기존 Cycles 제작 씬의 시각·논리 의미를 보존하고 SuperLuxCore native Spectral·OpenPBR 품질과 전송 추정기를 유지한다. 사용자 OSL·베이킹은 기존 유보 범위다.

엔진 소스 `8f2aa09c40620ff7cca6b226a74fb44433963755`, wheel CI [37989036418](https://github.com/claudianus/SuperLuxCore/actions/runs/37989036418). 확장 소스 `fb1938df4d0d392ec5ba09e64506b62484537cdb`, bundle CI [37992675256](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37992675256). 네 플랫폼 빌드와 휠·ZIP 서명/subject/source/build invocation 검증을 통과했다. 최종 ZIP의 Python 368개는 확장 소스와 동일하고, 포함 엔진 휠은 검증한 CI 휠과 동일하다. Windows의 고정 delvewheel 초기화 블록 세 개와 CRLF만 허용한 소스 대조다. Intel runtime smoke는 CI에서 생략됐다. 다른 플랫폼 Blender/GPU 실제 렌더를 뜻하지 않는다.

CUDA 수정을 포함한다: OpenCL 전용 벡터 리터럴·scalar→float3·벡터 any 비교·누락된 sign emulation과 vstore4의 잘못된 w 저장 위치. 엔진 CI의 NVRTC 12.9와 최종 번들 CI의 hash-pinned NVRTC가 각각 23개 CUDA 프로그램을 컴파일했다. 네 PathOCL 변형은 RGB/분광·terminator 0/1/2·wavefront on/off를 포함한다. 모든 36개 PathOCL 조합이나 NVIDIA 하드웨어 렌더 완료를 의미하지 않는다. 공개 2.11.21/22의 CUDA 커널 컴파일 결함을 기록했고 이 버전에서 수정했다.

CI ARM native SHA-256 `be60dd8d537ece9e699c8857f6f531b817f0e233cf3049ef99f65c1d425be5c6`. 이 native와 핵심 exporter 소스 hash를 매 Blender 프로세스에서 확인했다. CPU 75개·Metal 46개, 합계 121개 조건과 정상 Height=0 추가 12개가 통과했다. 기본 Spectral ON, 1280×720, denoiser/noise halt OFF. 128-sample native material beauty CPU·Metal 각 한 장과 Vector 비교 시트 6개를 직접 확인했다. 이 유한 표적 검사는 독립 제작 씬 수나 호환률이 아니며, beauty의 glass/noise 수렴 차이도 남아 있다.

최종 새 프로필과 실제 사용자 설치는 각 CPU 52개·Metal 52개 검사를 통과했다. 각 backend의 Vector 24개, Normal Map/smooth/image Bump 16개, scalar displacement 6개 및 정상 Height=0 추가 6개다. CI 133개와 두 설치 단계 208개를 합쳐 총 341개 표적·회귀 검사다. CI·최종·실제의 Vector 비교 시트 18개를 직접 확인했다. 독립 제작 씬 수나 호환률은 아니다.

실제 Blender 5.2.1 LTS (`9e2066aef7ef`)의 사용자 프로필에서 native·dist-info·manifest는 2.11.23이며 Python 368개와 manifest는 공개 ZIP과 정확히 같다. `wheel_source=0`은 PYPI enum으로, 이미 설치된 번들 휠 fast path를 사용한다. CLI 업그레이드의 기존 RNA 등록 진단 3개는 exit 0이었고, 이후 새 프로세스의 payload 검수와 104개 렌더에는 해당 진단이 없다. 기존 GUI 프로세스 hot reload는 미검증이다. 실제 이전 2.11.22 확장·native 패키지·설정·userpref는 workspace `test-scenes/validation-2026-10-10/cuda-fix-2.11.23/previous-install-2.11.22`에 보관했다.

잔여 결함은 분리한다. 공개 2.11.23 true-displacement Geometry Incoming의 독립 12개 기하 조건(평면/변하는 smooth normal, identity/회전/비균일 transform, Object/World)이 모두 실패했다. Blender 5.2.1 소스 `shader_setup_from_displace`의 `wi=N`과 달리 고정 +Z를 사용한다. 이 진단은 통과 수에 포함하지 않았다. Vector BUMP/BOTH, scalar World/linked Normal, 곡면 Bump의 미분값, 변위 후 Normal Map attributes, adaptive/cage·mixed-material/group·제작 GUI 및 타 플랫폼 실렌더도 남아 있다.

검증 파일은 workspace `test-scenes/validation-2026-10-10/cuda-fix-2.11.23`에 보관한다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.23-linux_x64.zip | `e486f0794f3ceff6c29c77beae4fec46488abf42eb86a61ef2515f27539da0f5` |
| SuperLuxCore-2.11.23-macos_arm64.zip | `086be26174b339306c136f10a7236cf2b70e8bed1fa3202415e557a5ed8d6f2b` |
| SuperLuxCore-2.11.23-macos_x64.zip | `bf318d120379e4b6d2ce8f2f65b10cc89877c608409e8479b7ba2c2772f80661` |
| SuperLuxCore-2.11.23-windows_x64.zip | `752519df49c3706e79e5eaae4e5d87c952ba16a271baaf3eb69d0e9008dde50e` |
