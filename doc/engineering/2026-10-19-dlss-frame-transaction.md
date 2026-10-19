# DLSS 프레임 게시 트랜잭션

공개 fix2는 보존하고 init 후보59f2a176e99102b5e44fbcde0a554fd846f9d8cc 위에서 별도 helper의 프레임 반환 계약을 검증했다. 새 기능/렌더 추정기/기본값 변경은 없다. 이 작업은 실제 Windows10/RTX5070Ti 테스터 크래시 또는 DLSS 화질/속도 인증이 아니다.

## 재현과 수정

전체 production Instance::process / Parameters / C API 본문을 그대로 컴파일해 C caller로 호출했다. GPU texture/resize/CUDA/NGX는 mock이다. baseline12개 중 정상2개는 통과했지만 정리 실패10개는 계약을 위반했다. context pop 오류를 무시하고 output/history/count를 게시했고 parameter 정리 실패도 인식하지 못했다.

GPU 결과는 기존 scratch에 두고, parameter 정리와 context 복원이 성공한 뒤 caller output으로 복사한다. 같은 시점에 history/last IDs/성공 frame count를 게시한다. 실패는 output/raw guide를 바꾸지 않으며 정리 실패 상태의 추가 처리를 차단한다. Parameter destroy 결과를 검사하며 resize의 parameter 정리 실패 뒤에는 추가 SDK allocation/evaluation에 진입하지 않는다. API.h에는 frames가 성공적으로 게시된 출력 수임을 문서화했으며 ABI layout/signature는 그대로다. 새 full-frame 임시 버퍼는 만들지 않고 기존 copy 위치를 옮겼다.

Instance::process에서 제거한 게시 줄과 추가한 resize cleanup guard를 제외하면 validation/SDK params/evaluate/readback/alpha 본문이 정확히 일치한다. init/resize/release/destroy 본문도 동일하다. main PYD/커널은 수정/재빌드하지 않았다. 이는 실제 렌더 이미지의 품질 검증을 대신하지 않는다.

초기 구현238fa710ff0138532ddcba0df4a986da1743d8a5의 CI39202280362는 58-case fixture를 통과했다. 실제 resize도 parameter 객체를 만드는 점을 fixture에 반영하자 cleanup 실패 뒤 추가 SDK 호출 두 건이 드러났다(missing-midframe-guard.json). 실제 guard를 추가하고 current64-case/새 source/새 CI로 다시 검증했다. 이전 후보의 통과를 최신 후보에 재사용하지 않았다.

## 최신 검증

Current64case는 native/upscale, 첫/연속 프레임, pop 소비/미소비, 파라미터 할당/정리, evaluate/sync/upload/download/resize 실패, nonfinite 값과 잘못된 입력/용량/budget/alias/중복/NULL/poison 재시도를 다룬다. 정상 fixture의 HDR RGB/alpha는 exact이며 모든 raw guide 배열은 byte equality로 검사했다. 선택된 pop model 외 임의의 실제 드라이버 상태 복구는 인증하지 않는다. 실패한 SDK parameter handle은 model에 남기며, 추가 호출을 막았다는 결과이지 native 메모리 회수 증거가 아니다.

로컬 ASan64, Linux CI64와 init45/teardown25/OpenCL모델35, Windows console/no-console 각각 frame64/init45/teardown25가 통과했다. GUI process는 실제 CRT stdout/stderr fd=-2를 확인했다. 반복을 독립 버그 수로 합산하지 않는다.

공식 SDK9981c6350dc58c0ce21f024fd65e31e851c31689로 Windows DLL과 Linux glibc2.28 helper를 빌드했다. 두 실제 라이브러리 모두 ABI1/load/invalid-frame output 보존/create discovery/close를 통과했으나 create는 CUDA driver unavailable이었다. 실제 NGX 평가0, RTX/quality/performance gate=false이다.

Linux는 공식 NVIDIA runtime도 glibc2.28 컨테이너에서 직접 로드했다. helper 최대 요구 GLIBC2.25, runtime 최대2.10이며 DT_NEEDED는 gate의 기본 system library 집합 안에 있다. libstdc++/libgcc sidecar는 필요하지 않다. container는 manylinux tag를 사용했고 실제 RepoDigest는 ci-linux/manylinux-image-digest.json에 남겼다. 이 loader/dependency 검사는 실제 GPU 호환성 인증이 아니다.

CI https://github.com/claudianus/SuperLuxCore/actions/runs/39202645597의 세 job이 모두 통과했다. Source commit `f3449d59676ebdf8fe1e3064e9d92ae36595eee6`, runtime SHA256 `8d93fe68b0dee98a1cf6bde14ce0cb25f298a74d6de830c3dde308ad7ee02496`, Windows helper `90b51d4228074218451b7e2023609fd26feb38e5097063b3521655a8fa4bb97b`, Linux helper `af8f1752c5dda35a6464eb5a37ac6778de098ec12f6954ed64de2b9e206fb2f6`. 각 artifact ABI JSON/source hash와 실제 바이너리 해시를 대조했다.

## 보존 및 다음 단계

Temporary index로 branch를 구성해 primary HEAD/index/status와 unrelated WIP를 보존했다. owned patch 역적용은 exact init 후보를 복구한다. default Blender 설치 및 공개 fix2의 여섯 자산 내용은 바꾸지 않았다. 새 후보는 설치/패키징/공개하지 않았다. 임시 compiler/cache/index는 정리하고 원본 helper DLL/SO, JSON, CI 압축 로그는 남긴다.

다음은 component별 출처를 유지하며 안정성 batch를 설치 가능한 ZIP으로 검증하는 일이다. Windows PYD 재사용은 renderer source 동등성을 먼저 확인한다. Linux는 helper만 바꿔서는 native cleanup 수정이 포함되지 않으므로 renderer 수정도 포함해야 한다. 개별 DLL/SO를 설치 경로에 수동 덮어쓰지 않는다. 실제 RTX 정상 실행 뷰포트/F12/애니메이션/무거운 씬 품질·반응성·속도 및 전체 목표는 여전히 미완료다.

근거: workspace dev-tools/reviews/2026-10-19/dlss-frame-transaction/report.json, baseline-parameter-lifetimes.json, fixed-parameter-lifetimes.json, source-preservation.json, artifact-verification.json, ci-host/, ci-windows/, ci-linux/, ci-run.json, ci-full.log.gz.
