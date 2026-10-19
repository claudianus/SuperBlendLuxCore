# fix1 DLSS helper C ABI 종료 오류와 fix2 후보

이전 Film V2 작업 다음의 안정성 작업이다. 사용자 확인 범위는 `fix1 / 렌더드 뷰포트`, Windows 10 / RTX 5070 Ti 정상 실행 종료 크래시와 DLSS 선택 시 디노이징이 사라지는 증상이다. 새 기능/품질/성능 승격은 동결한다. 이 기록은 실제 테스터 크래시를 재현했다는 뜻이 아니다.

## 재현

작업 직전 helper runtime.cpp와 api.h는 배포된 fix1 core `5469737765d78c7604732d36cba9488bdc9c4b42`의 바이트와 일치했다. 실제 production `slc_dlss_destroy`, `releaseManager`, `Scope` 및 버퍼/instance 정리 메서드 본문을 별도 C caller에서 호출했다. CUDA/NGX와 객체 생성만 mock이며 실제 SDK/GPU는 사용하지 않았다.

정상 1/2 instance와 NULL은 통과했지만, instance owning-context 진입 및 마지막 manager shutdown-context 진입 오류의 1/2 instance 조합 네 가지는 SIGABRT(-6)로 종료했다. 기존 함수는 throwing CUDA Scope를 C ABI 함수의 catch 밖에서 만들고 있었다. 이는 독립적으로 확인된 코드 결함이며, 테스터의 실제 RTX crash stack은 여전히 없다.

## 수정 계약

- ABI 1을 유지했다. destroy(NULL)은 no-op이고 non-NULL instance는 한 번 소비한다.
- 소멸 경로는 throwing CUDA Scope를 사용하지 않는다. CUDA/NGX 오류는 비예외 검사로 기록한다.
- own-context 진입 실패 시 caller의 context에서 native 객체를 free하지 않는다. CPU wrapper/instance/scratch 소유권을 소비하고 native 소유권은 manager context에 남겨 마지막 context 정리에서 해제 시도한다.
- 정상 context에서는 동기화/feature/surface/texture/array를 끝까지 정리하며 개별 실패도 기록한다. 실패 상태는 공유 manager에 남긴다. 형제 instance는 계속 정리할 수 있으나 process/preset/create/resize 재사용은 Blender 재시작 전까지 거절한다.
- 최종 context destroy가 실패하면 context identity를 남기고 새 manager로 덮어쓰지 않는다. 실제 driver가 거부한 native 메모리를 회수했다고 주장하지 않는다.
- C ABI 바깥으로 C++ runtime/lock 예외를 내보내지 않는다. mutex lock 자체가 실패한 경우에는 공유 소유권을 안전하게 바꿀 수 없으므로 restart 진단만 남긴다. 이 드문 host-runtime 실패까지 leak-free라고 인증하지 않는다.

renderer 추정기/샘플링/가이드/재질/default를 바꾸지 않았다. Windows 후보에는 이전 viewport OIDN fallback 및 backend 표시, async error containment, OpenCL release, Film V2와 이번 helper 정리만 포함한다. 미수용 Phase71–79 private renderer 구현은 포함하지 않는다.

## 검증과 Windows 후보

Production 메서드/C caller ASan+UBSan 25개가 통과했다. 동일한 frozen source를 Windows MSVC로 빌드한 console 25개와 GUI-subsystem no-console 25개도 통과했다. GUI 검사는 subprocess stdio pipe를 넘기지 않으며 **실제 CRT stdout/stderr fd가 모두 -2인지** 25개 각각 확인했다. 콘솔 없는 fprintf 오류 출력 경로가 이 mock host를 종료하지 않았다는 근거다. Windows 검사는 ASan/UBSan을 사용하지 않는다. 이는 Blender GUI 전체 또는 RTX GPU 시험이 아니다.

fault 조합은 정상, instance push, shutdown push, synchronize, feature release, surface/texture/array destroy, instance pop, shutdown pop, NGX shutdown, context destroy의 1/2 instance 및 NULL이다. pop 오류는 유효한 pop이 실제 소비된 뒤 과거 비동기 오류를 반환하는 모델이며 모든 CUDA 오류 context 상태를 대변하지 않는다.

동결한 core/adapter export에서 host/viewport/UI/final-error/packaging 총 12개 명령을 통과했다. 원래 HEAD/index/status를 유지하는 temporary Git index로 아래 별도 브랜치만 구성하고 push했다. 기존 브랜치 또는 작업 트리를 reset/stage하지 않았다.

- Core: `62551c4a8cb0097d35536ece26a79460e5f19db7`
- Adapter: `7582980f5e8198bb189baa22d0226934e31cb6a5`
- Branch: `release/windows-dlss-stability-20261019-fix2`
- Candidate version: `2.11.34+dlss.exp20261019.fix2`
- CI: https://github.com/claudianus/SuperLuxCore/actions/runs/39196423363

최신 관찰에서 Linux teardown, Windows console/no-console, wheel packaging 및 NVRTC gate가 통과했다. 공식 runtime 서명 확인과 실제 Windows SDK/helper DLL 컴파일 단계도 통과했다. 본체 native wheel 빌드가 실행 중이며, 최종 helper artifact hash/ABI 및 stock Blender installed ZIP 업그레이드 검증은 후속 단계이다. 아직 새 release는 공개하지 않았으며 published fix1은 그대로다. 진행 상태는 workspace evidence의 `ci-current.json`과 GitHub job 상태가 권위 자료다. observation timeout을 작업 종료로 해석하거나 새 run을 중복 시작하지 않는다.

작업 전/후 두 소스 파일은 owned patch 역적용으로 exact fix1 바이트 복구를 확인했고, 작업 후 소스는 frozen commit과 일치한다. 임시 host compiler 제품, 부분 export, temporary index는 즉시 정리했다. 새 로컬 Blender/GPU 작업 또는 기본 설치 변경은 없다. 실제 NGX evaluation/RTX 품질/무거운 씬 반응성/성능 acceptance는 여전히 미완료다.

근거: workspace `dev-tools/reviews/2026-10-19/windows-dlss-runtime-cleanup/`의 `report.json`, `baseline-faults.json`, `fixed-faults.json`, `ci-windows-no-console/`, `source-preservation.json`, `frozen-preflight.json`, `snapshot.json`, `push-receipt.json`.

## OpenCL 오류 모델 정정

후속 검수에서 테스트의 `clReleaseContext` mock이 실패한 버퍼의 native handle까지 무조건 지우던 가정을 정정했다. [공식 context lifetime 명세](https://registry.khronos.org/OpenCL/specs/unified/refpages/man/html/clReleaseContext.html)는 연결된 메모리 객체도 해제돼야 한다고 규정한다. 같은 frozen Windows production 본문에 수정된 모델로 35개를 다시 실행했다. 모두 host 소유권/오류 계약을 통과했으며, buffer release 실패 5개는 native handle이 남는 것을 명시적으로 확인했다. 이전 CI의 `context reclaimed` 문구는 이 실패 조건에서 실제 GPU 메모리 회수 근거가 아니다. 현재 production 후보/바이너리는 변경하지 않았다. 상세 receipt: workspace `dev-tools/reviews/2026-10-19/windows-dlss-runtime-cleanup/ownership-corrected-opencl-model.json`. GPU 정리 오류가 보고되면 추가 시험 전 Blender를 재시작해야 한다.

## fix2 공개 완료

[Windows experimental fix2](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/experimental-windows-dlss-20261019-fix2)를 별도 prerelease로 공개했고 실제 다운로드 HEAD 200, 길이 199,307,648 bytes 및 GitHub asset SHA-256 일치를 확인했다. 기존 fix1 자산과 stable Latest `v2.11.34`는 보존했다.

ZIP SHA-256: `49dcf1e834679861f9ca42c58f08108a1bfef61bd813be1bd241a62daf40ceeb`. Native pyd: `207328da3920d73aed7b0dfa0c33c8a65f8861799b53dcc2a895456f1217db70`. Helper DLL: `af7049ef8cb7919a2b748e5022d2ede3d23e5855a0a9240b08cac59bfa255d19`. Native 바이너리 13개 해시는 `experimental-provenance.json`에 있다. 원래 wheel의 nonmetadata payload 189개 바이트가 패키징 후 보존됐고 adapter 270개 해시가 일치했다.

CI39196423363의 여섯 job과 실제 stock Blender5.2.2 fix1→fix2 업그레이드가 통과했다. 최종 로그에서 CPU fallback의 INTEL_OIDN component denoise 실행을 확인했다(`windows-cpu-fallback.log`). 실제 Windows 생성 128×72 2-SPP EXR은 finite/nonblack이며 ACES2 preview를 직접 검수했다. 이는 RTX/NGX 또는 복잡한 씬 품질 인증이 아니다. 실제 NGX evaluation은 0, quality/RTX acceptance는 false이다.

최초 artifact verifier의 LF 가정이 Windows METADATA의 정상 CRLF에 실패한 기록은 보존했다. 표준 email header parser로 고쳐 같은 산출물을 재검증했다. production/binary 변경은 없다. 실패 포함 supervisor receipt 5개가 모두 reap 상태, 잔류 자체 프로세스 0개이다. raw wheel 비교용 중복 다운로드, 임시 visual profile, gh cache를 정리했고 원본 ZIP/EXR/log/provenance는 남겼다.

현재 목표 전체는 미완료이며 실제 Windows10/RTX5070Ti 정상 실행 뷰포트 재시험이 남아 있다. 새 기능 동결과 실제 GPU 없이 DLSS 품질/속도/100% 지원을 선언하지 않는 경계를 유지한다.
