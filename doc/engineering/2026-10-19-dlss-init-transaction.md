# DLSS 초기화 트랜잭션 소유권 수정

공개 fix2의 별도 helper 초기화 실패 경로를 검토했다. 최신 우선순위는 Windows fix1 정상 실행 렌더드 뷰포트 크래시와 디노이징 폴백 안정성이다. 새 기능은 동결하며 실제 RTX 크래시 해결/100% DLSS 지원 판정은 아직 하지 않는다. 공개 fix2 자산은 그대로다.

## 재현과 수정

작업 전 runtime.cpp는 공개 fix2 core `62551c4a8cb0097d35536ece26a79460e5f19db7`의 바이트와 일치했다. 전체 production manager/create/destroy 본문을 C caller에서 실행하는 CUDA/NGX mock으로 정상 2개 대비 실패 10개(다섯 유형의 단일/복수 생성 시도)를 확인했다. 생성 직후 pop 실패가 rollback 밖에 있어 context가 남았고, 마지막 init pop은 무시됐다. rollback context destroy/NGX shutdown 실패도 재사용 차단에 반영되지 않았다. 초기화 후 manager 문자열 할당 실패는 handle을 반환하지 않고 refs=1/context=1을 남겼다.

문자열을 native context 취득 전에 준비하고 성공한 상태를 move로 게시한다. 생성 이후 모든 단계를 rollback 범위에 넣고 pop/push 결과를 확인한다. 실패한 pop을 무조건 반복하지 않고 NGX 종료가 필요하면 자신의 context를 다시 취득한다. destroy 실패의 identity를 보존하며 정리 실패 후에는 restart 전까지 재사용을 거절한다. 실패한 native destroy가 실제 메모리를 회수했다는 보장은 하지 않는다. [NVIDIA context 관리 명세](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__CTX.html)는 current context destroy의 pop 동작과 pop에서 과거 비동기 오류를 반환할 수 있음을 설명한다.

초기 allocation injector는 std::string의 정확한 allocation 크기를 가정했다. libc++ capacity rounding 때문에 실패 주입이 되지 않았던 두 calibration 기록을 보존하고, 단계별 첫 큰 할당을 대상으로 수정했다. 실제 assertion은 유지했다. 최종 baseline은 refs/context 잔류를 출력하며, 수정본은 문자열 준비 실패 시 native 취득 0을 확인한다.

## 검증 범위

로컬 ASan/UBSan init45/기존 teardown25가 통과했다. Linux CI의 init45/teardown25/OpenCL reference model35도 통과했다. Windows MSVC에서는 console/no-console 각각 init45와 teardown25가 통과했고 GUI 프로세스의 실제 stdout/stderr fd=-2를 확인했다. 플랫폼 반복을 독립 버그 수로 합산하지 않는다. selected pop model은 stack entry 소비/미소비 두 형태를 다루며 모든 driver state 인증은 아니다.

공식 SDK9981c6350dc58c0ce21f024fd65e31e851c31689로 Windows helper를 빌드하고 PE64/ABI1/실제 DLL 로드를 확인했다. 실제 create는 `CUDA driver is unavailable` 오류를 반환했으며 close(NULL)은 정상 종료했다. 실제 GPU context 생성 성공이나 NGX 평가 결과로 해석하지 않는다(NGX 평가0).

CI: https://github.com/claudianus/SuperLuxCore/actions/runs/39200602879 (두 job success). Candidate `59f2a176e99102b5e44fbcde0a554fd846f9d8cc`, runtime SHA256 `ba4b0120ecb7cca15fb6c529864ee706d42781151205785aed09908a4e7f645a`, helper DLL SHA256 `b3d895952395d109273fd354c919bca2b87b63d30a5a5dd409383f646c9d371f`.

production delta는 별도 helper runtime.cpp 한 파일이다. Frame process/resize/manager release/destroy와 C process entry의 본문 해시가 fix2와 일치하며 ABI header/렌더러/커널은 바뀌지 않았다. 따라서 main PYD를 재빌드하지 않고 helper target만 검증했다. 이는 새 CPU/Metal/Blender 품질 또는 성능 검증을 대신하는 결과가 아니다.

Temporary Git index로 candidate를 만들었고 primary HEAD/index/status를 보존했다. owned patch를 역적용하면 exact fix2 source로 돌아간다. 수정본은 현재 Blender에 설치하거나 새 ZIP으로 공개하지 않았다. 기존 fix2 여섯 자산의 크기/해시 일치를 확인했다. 테스트 compiler/cache 임시파일은 정리하며 원본 DLL/JSON/압축 CI 로그를 보존한다.

근거: workspace dev-tools/reviews/2026-10-19/windows-dlss-init-transaction의 report.json, baseline-final.json, fixed-final.json, source-preservation.json, artifact-verification.json, ci-host/, ci-windows-helper/, ci-run.json, ci-full.log.gz. 다음은 frame-processing Scope pop 오류와 caller output 계약을 재현 검토하고 Linux helper/dependency 및 component별 패키징 검증을 진행한다. 실제 Windows10/RTX5070Ti 정상 실행 뷰포트 재시험은 계속 미완료다.
