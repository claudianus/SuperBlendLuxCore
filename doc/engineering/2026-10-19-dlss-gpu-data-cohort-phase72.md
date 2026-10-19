# DLSS GPU 데이터 일관성 — Phase72, 2026-10-19

진행 상태는 active이며 전체 DLSS 지원·화질·성능 게이트는 미완료다. 기존 Linux/Windows 공개 실험판을 변경하지 않았다. 이번 후보는 Phase70 동결 소스 + Phase71 데이터 snapshot + Phase72 queued retirement 수정이며, 동시 진행 중인 최신 SSS/WIP의 결합 바이너리 검증을 대신하지 않는다. 사용자 기본 Blender와 원본 .blend는 보존했다.

## 변경과 지문

`src/slg/engines/pathoclbase/pathoclbaseoclthreadkernels.cpp`의 queued wavefront SPLAT 뒤에 `CommitFilmData` dispatch6줄을 추가했다. NEXT_SAMPLE에서 sample record를 재사용하기 전에 최근접 depth의 전체 data snapshot을 전달한다. 기존 dense 경로에는 있던 retire 단계가 queued 경로에서 빠진 것이 원인이었다. 257×145/64 targetSPP 재현에서 이전 후보의 위치·깊이 불일치37,265/37,265픽셀이 수정 후보에서0이 됐다.

주 checkout에는 이6줄만 반영했다. 파일 before SHAa8f7f5cc4bcfd4f382cf5474d1d95342bd339f73dfcf6c0057c17f1e15b0ffb8 → after SHA34a65fcafc787ad568a44762cc71150ac4bd7b1f78c3726bc79d72ec52bafdf5이며, 격리 빌드의 동일 파일과 byte-identical이다. 나머지 파일 bytes와 primary index를 보존했다. 결합 primary SSS/WIP를 새로 빌드하거나 기본 설치에 반영하지 않았다.

- built native: `5d69a29c77b89e650d7e9c05804ccf9beff8724d5321e2c0282dcf3c91d87bbf`
- installed/ZIP native: `69d4acdcbc4d2fa17e52b46c0551935a7b6eefa2003c0e3e33aa13eea0e58e03`
- 원본 후보 wheel: `0a5ff46efd6a3044e32662c6b3db7d882aa596617b22f035b44fb80e2ef6ea7f`
- compiled kernel archive: `bde5885b2901d408e7d723933d0d5569e06dbcf060145bf54b1371c41409de40`
- worker: `42b73271104fad4402863bf97299d1a0c96f8e3e9cdd8e178e444444fa79fe2b`; framebuffer: `483077a5f25f9782d20133598e68bf25c9b8a0ece54ca6a8efe2cc314ac6af73`
- 격리 실제 ZIP: `2088f04bafb60923a02c9735e61cb7764b3df26275cdc83f7780011079a7a274` (102594008bytes), Phase70 어댑터270개 byte-identical

## 현재 검증과 실패

257×145/128 target meanSPP: CPU SOBOL, Metal SOBOL/overlap8/RT/RT-fovea/RANDOM/METROPOLIS/wavefront8개가 full coverage와 depth/position/object/material/UV/geometric normal/shading normal/static motion 검사를 통과했다. 렌즈 위치를 worldXY에서 독립 역산해 depth를 재계산하는 추가 oracle도8개 모두 통과했다.

1280×720/128 target meanSPP: 위8개 중 wavefront를 제외한7개가921,600픽셀 전부 채움, depth/position 및 보조 속성 불일치0을 통과했다. 독립 lens oracle 최대 depth 오차는 1.85817743e-06; 초점면의 물리적 고정 emission.02/1 oracle 최대 오차는 2.38418579e-07였다. blur RMSE는 유한 샘플 진단이며 일반 씬 품질/속도 근거가 아니다. 실제 sample min/max/mean은 각 결과에 기록했고, 요청128을 픽셀당 정확128로 주장하지 않는다.

**720p wavefront는 기존 per-case180초 제한 초과로 실패**했다. 총253.713s 뒤 하네스가 exit1로 종료됐고 child는 회수됐다. 8-case720p 전체 pass가 아니다. 원래600초/4GiB supervisor와180초 case 기준을 유지했다. 현재 UpdateStats가 full UpdateFilm을 수행하고 fixture는10ms마다 호출하므로, next diagnostic은 실제 진행 카운터와 readback 호출 빈도를 동결 baseline과 함께 관찰해 새 commit kernel과 계측 비용을 분리해야 한다. 아직 성능 원인 확정/속도비는 없다.

실제 pybind ownership15계약, native final-delivery5그룹(독립 frame lease/반복 전달·stale acknowledgement 거부/hold backpressure/dynamic halt cap/편집·resize·정지/release-to-latest) 통과. Control과 accumulated processing의 raw/AOV10채널은 해당 고정 씬·sample 구간에서 bit-exact였다. NGX 실행은0이다. 별도 wavefront before/after color/count가 동일하지 않았던 결과를 이 bit-exact 결과로 대체하지 않는다.

실제 stock Blender5.2.2LTS의 새 격리 profile에 ZIP을 설치했다. Source/dev sys.path override 없이 native와270개 어댑터 지문을 확인한 뒤 CPU/Metal720p 스틸 + 각2프레임 카메라 애니메이션4케이스를 모두 통과했다. Combined EXR6개와 별도 canonical native RGB EXR6개, 총12개 roundtrip의 최대 오차0. Worker/read/OIDN 작업은 각 종료 전에 drain됐다. CPU/OIDN fallback이며 RTX DLSS 애니메이션 검증이 아니다.

## 원본 무거운 씬 UI

원본 GenmaB SHA f63059830408f03dc6fb803f4fe924815cb7c35ad3aeb95e9cd13d140f1bbfed. 582objects/39materials/31images/1,094,248polygons/70,986,225texels. 원본 geometry/texture/bounce/샘플·재질 품질 설정을 낮추지 않았다. 실제 최종 viewport는3733×2310이며 UI screenshot5120×2622도 보존했다. CPU·Metal 각각30orbit/14실제area resize, 최종 유한 framebuffer와 worker drain 확인.

|관측값|CPU|Metal|
|---|---:|---:|
|첫 이미지 s|7.464|87.886|
|view_draw p95 ms|8.185|3.239|
|새 프레임 확인 orbit|27/30|27/30|
|새 프레임 확인 resize|2/14|2/14|
|확인된29/44이벤트의 새 프레임 p95 ms|483.104|493.758|
|관측 PPID-tree RSS peak GiB|6.862|6.002|

16GiB/600초 기존 heavy guard 그대로 사용했다. 사용자 승인 shared-allowed functional 모드이며 performance_eligible=false다. macOS 내부 cache를 지우지 않았고 이전157초와의 cold-start 개선율이나 CPU/Metal 속도비를 만들지 않는다. 낮은 draw p95가 전체 frame 반응성 달성을 의미하지 않는다. resize의12개 새 프레임 미확인은 미완료로 남긴다.

직접 검수한 간단한 fixture는 정상 geometry/색 위치/카메라 이동을 보였으나 raw는 매우 noisy하고 OIDN이 배경·그림자를 부드럽게 만든다. 원본 무거운 씬은 어둡고 강한 spectral grain/firefly가 남으며 Metal에는 거친 preview block이 보인다. quality_gate=false다.

## 남은 실제 목표

720p wavefront timeout과 실제 resize fresh-frame coverage, Metal 첫 화면87.886s, 무거운 씬의 시각적 품질을 개선해야 한다. Phase68의 과거4개 shared-diagonal Metal literal-ray miss는 정확한 현재 후보에서 재검증·수정이 필요하다. 신규 RTX/NGX GPU 검증은 사용자가 비용 때문에 서버를 종료해0이며, 기존 서버에 재접속하거나 유료 서버를 요구하지 않는다. 실제 SDK 뷰포트·파이널·애니메이션·재질/투명/볼륨/광학·path motion·upscale·시간축 안정성과 품질·속도 게이트가 남아 있으므로 전체 goal을 완료로 표시하지 않는다.

증거는 workspace `dev-tools/reviews/2026-10-16/dlss/phase72/phase72-report.json`, candidate/product identities, primary-host-integration.json, 720p partial progress 및 failure receipt, independent lens/emission oracles, ownership/final-delivery/actual ZIP 결과, heavy CPU/Metal JSON·실제 screenshot·raw buffers, visual-review.json에 있다. ZIP 포장 중 하네스 ZipInfo 재사용 오류와 CPython SO 파일명 가정 오류는 수정했고, 불완전한 자체 ZIP·빈 profile과 사용이 끝난 임시 디렉터리/bytecode cache는 정리했다. 검증 ZIP·원본 wheel·native build·두 격리 profile은 다음 동결 baseline/candidate 진단에 필요해 보존한다. 공개 릴리스·기본 설치는 이번 후보로 교체하지 않았다.
