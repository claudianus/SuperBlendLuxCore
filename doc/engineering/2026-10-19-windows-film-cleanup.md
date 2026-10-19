# Windows fix1 렌더드 뷰포트: Film GPU 정리 소유권 V2

사용자가 문제가 난 배포본을 `fix1`, 화면을 렌더드 뷰포트로 확인했다. 새 기능 작업은 동결한다. 이 기록은 Film GPU Image Pipeline 종료의 재현 가능한 C++ 예외/소유권 결함을 고친 범위이다. 테스터 Windows 10 / RTX 5070 Ti의 실제 크래시 원인 확정 또는 해결 판정은 아니다. 배포된 fix1 ZIP은 이번 작업으로 바뀌지 않았다.

## 재현과 수정

이전 `windows-opencl-followup/remaining-film-cleanup-failures.json`은 실제 Film 메서드에 GPU context push / queue finish / context pop 실패를 주입했을 때 세 가지 abort를 기록한다. 이번 수정은 GPU 정리 오류가 C++ 소멸자 밖으로 전파되는 것을 막으면서 소유권을 끝까지 정리한다.

- HardwareDevice에 `FreeBufferForDestruction() noexcept`를 추가하고 CUDA/OpenCL/Metal/Vulkan 및 GPU 플러그인 소멸자에 적용했다. 정상 작업의 throwing FreeBuffer API는 보존했다. CPU 버퍼 wrapper는 한 번 소비하며, CUDA own-context 진입 실패 시 다른 context에서 native free를 호출하지 않는다.
- Film은 worker를 join하고 context/queue 오류를 기록한 뒤 플러그인을 삭제한다. setter/copy는 새 소유권을 안정시킨 후 API 오류를 전달한다. 삭제된 포인터가 남아 다음 종료에서 다시 삭제되는 것을 막는다.
- V2는 buffer/OptiX 정리 실패 상태를 장치에 남긴다. 교체 후에도 오류를 정상 성공으로 숨기지 않고 세션 재시작을 요구한다. V1은 이 전파가 없어 보류하고 `candidate-v1/`에 별도 보존했다.
- Film의 hardware-only Context 종료는 장치별 push/stop/pop을 끝까지 시도하며 Context 소멸자의 throwing Stop 재진입을 막는다. intersection worker가 있는 Context는 일반 Stop 경로를 유지한다.

실제 드라이버가 native release를 거부한 메모리를 회수했다는 보장은 하지 않는다. wrapper 소유권 소비, 해제 시도, 실패 전파를 검사한다. access violation, 강제 driver 종료, device loss와 CUDA pop 오류의 모든 context 상태를 인증하지 않는다.

## 현재 V2 검증

Production method 본문을 사용하는 ASan/UBSan 검사: Film 소유권 35개, CUDA buffer 7개, OptiX 소멸자 5개, Metal/Vulkan cleanup 8개가 통과했다. frozen Windows source에서도 같은 Film 35개를 반복해 통과했다(추가 독립 35개로 합산하지 않는다). 기존 Film teardown 6개도 통과했다. OptiX/CUDA/Vulkan 오류는 mock이며 실제 RTX 검증이 아니다.

실제 native 반복은 PATHCPU 물리 렌더러에 CPU image pipeline 6회, OpenCL image pipeline 3회, Metal image pipeline 3회, 총 12세션이다. GPU 필터는 Bloom/색수차/Gaussian/Camera Response/배경 이미지/Gamma를 실행했고 hardware-plugin CPU fallback은 없었다. 파이프라인 교체 전후 raw RGB는 bit exact였다. 이는 GPU path tracer 전체의 CPU/Metal parity 시험이 아니다.

Stock Blender 5.2.2 LTS의 정상 GUI(no `-d`, no background)에서 OpenCL RTPATHOCL 렌더드 뷰포트의 interactive/paused OIDN 업로드와 worker 회수를 확인했다. DLSS가 CUDA를 요구하는 OpenCL 상태에서 OIDN을 건너뛰지 않는 이전 adapter 수정도 같은 설치로 확인했다. 실제 NGX evaluation은 0이다.

F12는 PATHCPU + CPU/Metal Image Pipeline 5개 케이스(정상 2, 잘못된 OIDN filter 오류, 다음 렌더 복구, addon Stop 요청 소비)가 통과했다. 모든 경우 자체 스레드 0개였다. Stop 검사에서 Blender는 render_complete를 보냈고 render_cancel callback은 없었다. ESC 취소 전체를 인증한 결과로 확대하지 않는다.

최초 GUI 실행은 cache hit 뒤에도 kernel 준비 109,795ms로 기존 90초 첫 프레임 기준을 실패했다. 실패 로그와 receipt를 `viewport-first-attempt/`에 보존했다. 한 번의 명시적 warm retry는 같은 기준을 통과했다. 기준을 늘리지 않았으며 cold start/성능 통과로 바꾸지 않는다. 다른 렌더가 병렬 실행 중이므로 모든 속도비/최적화 주장은 보류한다.

320×180 32-bit EXR 5개는 finite/nonblack을 확인하고 선형 픽셀 해시와 통계를 기록했다. ACES 2.0 PNG와 실제 뷰포트 화면을 직접 검수했다. 방향/색/실루엣과 오류 시 noisy Combined 보존을 확인했다. 저 SPP 및 pixel-size-4 뷰포트는 특히 paused 화면이 거칠다. 스크린샷만으로 denoising 효과나 최종 품질을 인증하지 않으며, 실제 OIDN 업로드는 FrameBuffer callback 계측으로 확인했다.

## 출처와 보존

V2 installed native: `8d0be06ed9d6cb0bb5550b3dc1013f89f09171d119ae6f9b8da2a4d24fad5df8`.
Built native: `373d588b049b49266cce2346b1c673980828bc0db763cefc2d0bf08a439a308d`.
Wheel: `a337638ec74a97798dd33b9abb8136daabd743e4dc755dc6a2d114bc8a7c0442`.
Kernel archive: `bde5885b2901d408e7d723933d0d5569e06dbcf060145bf54b1371c41409de40` (변경 없음).

macOS private native에는 기존 Phase71–79 WIP가 보존돼 있다. 제안된 Windows 입력은 fix1 core `5469737765d78c7604732d36cba9488bdc9c4b42`에 이전 feedback/OpenCL 및 이번 Film V2만 더한 23개 frozen source 파일이다. 12개 수정 메서드의 본문은 primary/private/frozen에서 일치한다. 미수용 renderer WIP를 Windows 입력에 합치지 않았다. Windows binary는 아직 만들거나 공개하지 않았다.

22개 파일의 owned patch를 역적용하면 작업 직전 바이트를 정확히 복구한다는 검사를 통과했다. V1과 V2를 섞지 않고 wheel/로그/EXR/PNG를 보존했다. 현재 및 V1/실패/첫 export를 포함한 21개 supervisor receipt가 모두 reap 상태이며 자체 잔류 프로세스는 없었다. 사용이 끝난 V2 profile 306,748,315 logical bytes를 정리했다. V1 profile도 별도 정리 기록이 있다. 기본 Blender 설치와 다른 렌더 프로세스는 수정하지 않았다.

다음 작업은 별도 DLSS helper의 `slc_dlss_destroy`가 throwing CUDA Scope를 C ABI 바깥으로 내보내는지 재현하고 수정하는 일이다. 그 후 bounded Windows candidate CI/정상 GUI RTX 검증으로 이어간다. 현재 결과만으로 Windows 크래시 해결·DLSS 작동·100% 지원을 선언하지 않는다.

근거: workspace `dev-tools/reviews/2026-10-19/windows-film-cleanup/report.json`, `candidate-identity.json`, `source-preservation.json`, `combined-candidate-manifest.json`, `cleanup-audit.json`. 과거 V1 JSON 내부의 원래 경로는 역사적 경로이며, 같은 이름의 V2 파일 결과로 해석하면 안 된다.

## OpenCL 오류 모델 정정

후속 검수에서 테스트의 `clReleaseContext` mock이 실패한 버퍼의 native handle까지 무조건 지우던 가정을 정정했다. [공식 context lifetime 명세](https://registry.khronos.org/OpenCL/specs/unified/refpages/man/html/clReleaseContext.html)는 연결된 메모리 객체도 해제돼야 한다고 규정한다. 같은 frozen Windows production 본문에 수정된 모델로 35개를 다시 실행했다. 모두 host 소유권/오류 계약을 통과했으며, buffer release 실패 5개는 native handle이 남는 것을 명시적으로 확인했다. 이전 CI의 `context reclaimed` 문구는 이 실패 조건에서 실제 GPU 메모리 회수 근거가 아니다. 현재 production 후보/바이너리는 변경하지 않았다. 상세 receipt: workspace `dev-tools/reviews/2026-10-19/windows-dlss-runtime-cleanup/ownership-corrected-opencl-model.json`. GPU 정리 오류가 보고되면 추가 시험 전 Blender를 재시작해야 한다.

## fix2 공개 완료

[Windows experimental fix2](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/experimental-windows-dlss-20261019-fix2)를 별도 prerelease로 공개했고 실제 다운로드 HEAD 200, 길이 199,307,648 bytes 및 GitHub asset SHA-256 일치를 확인했다. 기존 fix1 자산과 stable Latest `v2.11.34`는 보존했다.

ZIP SHA-256: `49dcf1e834679861f9ca42c58f08108a1bfef61bd813be1bd241a62daf40ceeb`. Native pyd: `207328da3920d73aed7b0dfa0c33c8a65f8861799b53dcc2a895456f1217db70`. Helper DLL: `af7049ef8cb7919a2b748e5022d2ede3d23e5855a0a9240b08cac59bfa255d19`. Native 바이너리 13개 해시는 `experimental-provenance.json`에 있다. 원래 wheel의 nonmetadata payload 189개 바이트가 패키징 후 보존됐고 adapter 270개 해시가 일치했다.

CI39196423363의 여섯 job과 실제 stock Blender5.2.2 fix1→fix2 업그레이드가 통과했다. 최종 로그에서 CPU fallback의 INTEL_OIDN component denoise 실행을 확인했다(`windows-cpu-fallback.log`). 실제 Windows 생성 128×72 2-SPP EXR은 finite/nonblack이며 ACES2 preview를 직접 검수했다. 이는 RTX/NGX 또는 복잡한 씬 품질 인증이 아니다. 실제 NGX evaluation은 0, quality/RTX acceptance는 false이다.

최초 artifact verifier의 LF 가정이 Windows METADATA의 정상 CRLF에 실패한 기록은 보존했다. 표준 email header parser로 고쳐 같은 산출물을 재검증했다. production/binary 변경은 없다. 실패 포함 supervisor receipt 5개가 모두 reap 상태, 잔류 자체 프로세스 0개이다. raw wheel 비교용 중복 다운로드, 임시 visual profile, gh cache를 정리했고 원본 ZIP/EXR/log/provenance는 남겼다.

현재 목표 전체는 미완료이며 실제 Windows10/RTX5070Ti 정상 실행 뷰포트 재시험이 남아 있다. 새 기능 동결과 실제 GPU 없이 DLSS 품질/속도/100% 지원을 선언하지 않는 경계를 유지한다.
