# 2026-10-19 DLSS stability fix3 — Windows / Linux experimental

사용자가 확정한 대상: **fix1 / rendered viewport / Windows10 / RTX5070Ti / Blender5.2.2 LTS**. 새 렌더 기능을 동결하고 native 자원 정리와 DLSS 실패 처리 수정만 실험 배포했다. 이 안정성 패키징 단위는 완료했다. 실제 테스터의 정상 실행 종료 크래시와 RTX DLSS 품질·속도는 아직 하드웨어 재시험 전이며 전체 goal은 완료하지 않았다.

## 공개 산출물

- Windows: https://github.com/claudianus/SuperBlendLuxCore/releases/tag/experimental-windows-dlss-20261019-fix3
  - ZIP SHA256 `061f832dba291ed057b783c2cf9988bae2b4a789c726476e089a5e148b39375b` / 199310241bytes.
- Linux: https://github.com/claudianus/SuperBlendLuxCore/releases/tag/experimental-linux-dlss-20261019-fix3
  - ZIP SHA256 `40141aa32bb0ada0688fe811ff09ccbe5676cd8b98d05047507633120d9b50f5` / 230309405bytes.
- 배포 버전 `2.11.34+dlss.exp20261019.fix3`, package source `f66e9b1c37c05d525b7faf0f05b5950c5637f510`, addon source `fe7a9ce469377b807f587e1d088aa59151285d32`.
- 두 ZIP 공개 HEAD200, asset digest 및 기존 fix1/fix2/original Windows+Linux/stable asset ID/size/digest 보존을 확인했다. Linux 공개 과정에서 Windows fix3의 다섯 asset도 보존했다. Stable Latest는v2.11.34다. 게시한 ZIP만 검증된 제품이다; CI split-platform의 타 OS placeholder ZIP4개/24,242,912bytes는 해시 기록 후 로컬 제거했고 배포하지 않았다.

## 포함한 수정과 소스 보존

- DLSS unavailable/failed일 때 현재 세션의 유효한 DLSS 출력이 아닌 일반 film이 OIDN을 건너뛰던 뷰포트 결함을 수정했다. 기존 OIDN 조건·threshold를 유지하는 정상 fallback으로 복구한다.
- 이전 fix2의 OpenCL/Film/plugin/buffer cleanup 예외 격리와 ownership 정리를 포함한다. 테스터의 실제 GPU 크래시와 동일 원인이라고 확정하지 않는다.
- init/rollback/teardown 실패를 검출하고 실패한 native identity를 보존해 unsafe reuse를 차단한다. frame SDK parameter retirement/context pop 완료 후에만 output/history/ID/frame count를 publish한다. 기존 scratch를 재사용하며 ABI1을 유지한다. driver cleanup 실패 시 native GPU 메모리를 전부 회수했다고 주장하지 않는다.
- Windows native는 source-equivalence 확인 후 fix2의 renderer commit `62551c4a8cb0097d35536ece26a79460e5f19db7` / CI39196423363을 그대로 사용했다. PYD SHA256 `207328da3920d73aed7b0dfa0c33c8a65f8861799b53dcc2a895456f1217db70`. helper/provenance를 제외한 원본 wheel payload192개는 byte-identical이고 기존 license CRLF bytes도 유지했다.
- Linux native는 원래 실험판에 native cleanup이 없어 `524385a46906b71cc7b9f5f4d68b42b4014bc7a6` / CI39203919041에서 새로 빌드했다. Native SHA256 `1680363c39fbdf6997fcfcf47ca2d742f756cdd50decf575774822cf00f3a652`. 포장 전 원본 wheel payload185개를 byte-identical로 유지했다. 원래 native6d27→524385 source delta는 cleanup/helper25paths이며 .cl kernel 변경은 없다. 이것만으로 새/이전 binary의 image parity나 performance를 인증하지 않는다.
- Helper source `f3449d59676ebdf8fe1e3064e9d92ae36595eee6` / CI39202645597, runtime.cpp SHA256 `8d93fe68b0dee98a1cf6bde14ce0cb25f298a74d6de830c3dde308ad7ee02496`. Windows DLL `90b51d4228074218451b7e2023609fd26feb38e5097063b3521655a8fa4bb97b`, Linux SO `af8f1752c5dda35a6464eb5a37ac6778de098ec12f6954ed64de2b9e206fb2f6`. 이미 acceptance를 통과한 원본 binaries를 재사용했다. SDK pin9981c6350dc58c0ce21f024fd65e31e851c31689과 공식 NVIDIA runtime 해시/라이선스를 확인했다.
- Addon product Python은 fix2와 동일하며270개 accepted adapter hash를 확인했다. 미검증 Phase71–79 구현을 넣지 않았고 primary HEAD/index는 temp-index snapshot마다 보존했다. 사용자 기본 Blender 설치와 소유권 불명 WIP는 변경하지 않았다.

## 검증 범위

- Windows package CI39205017778: stock Blender5.2.2 LTS의 격리 한글 profile에서 fix2→fix3 전체 ZIP 업그레이드, installed native/helper 지문, ABI1/discovery, invalid-frame caller output 보존, CPU/DLSS-unavailable의 실제 OIDN 실행 및 EXR 전달.
- Linux native CI39203919041: 세 job 모두 성공,23/23 NVRTC programs compile, CIBW actual PATHCPU smoke, auditwheel 및 relocation. Linux package CI39205748905: 같은 stock Blender에서 original experimental→fix3 전체 ZIP 업그레이드와 installed native/helper/CPU OIDN/EXR 검사.
- Helper production-body fault fixtures: frame64/init45/teardown25를 각 Windows MSVC console/no-console 및 Linux 모드에서 통과했다. 같은 case의 플랫폼 반복이며 독립 bug 수가 아니다. no-console 실제 CRT fd=-2 확인. CUDA/NGX/texture는 모형이다.
- 실제 Windows helper PE64/ABI load와 Linux glibc2.28 helper/runtime ELF closure/load는 검증했다. helper GLIBC max2.25, runtime2.10. 실제 helper discovery는 CUDA driver unavailable; **이번 실제 NGX 평가0**.
- Windows/Linux 실제 설치 출력의 finite linear EXR 및128×72 ACES2 preview를 직접 검수했다. 중심 cube, orientation/silhouette, gray-blue background, nonblack image를 확인했다.2SPP 출력은 smoothed/coarse edges인 기초 smoke이며 최종 품질·정합성·애니메이션·speed proof가 아니다.
- packaging fixture6cases: UTF8 metadata/cache version/RECORD/.data/native 보존, helper replacement, wronghash 및 corrupt input RECORD 거부. 실제 Windows wheel을 별도 재포장해192payload 보존도 대조했다.
- 첫 package CI39204760002는 렌더 전 공식 Blender checksum의 Python urllib HTTP403으로 실패했다. curl로 전환하되 공식 SHA256 gate를 유지했다. 자체 superseded CI39204926822는 원본 CRLF license 보존을 추가하려고 비싼 다운로드 전 취소했다. 현재 binary/helper source에는 변화가 없으며 이전 실패/취소를 성공으로 바꾸지 않았다.
- release snapshot scoped diff-check는 통과했다. Primary addon의 unrelated export/__init__.py CRLF/trailing-whitespace WIP는 보존했으며 배포 snapshot에는 없다.

## 설치와 남은 실제 검증

OS에 맞는 **전체 ZIP**을 extension installer로 설치하고 Blender를 재시작한다. helper/runtime/NVRTC/license는 renderer wheel에 포함되어 별도 SDK 다운로드가 필요 없다. 예전 DLL/SO 개별 덮어쓰기를 하지 않는다. locator가 비어 있으면 번들 자동 탐색을 사용한다.

Rendered viewport는 GPU + add-on GPU Backend CUDA + DLSS denoiser를 선택해야 한다. OpenCL만으로 이 CUDA DLSS 경로가 활성화되지 않는다. `DLSS fallback` 상태는 성공한 NGX reconstruction이 아니고 일반 OIDN 경로임을 뜻한다. 사용자 backend/default를 자동 전환하지 않았다.

다음은 테스터의 실제 Windows10/RTX5070Ti에서 원래 GPU Image Pipeline 설정, 일반 실행(no -d), rendered viewport의 시작·중지·재시작을 정확한 fix3로 재시험하는 것이다. 현재 Windows CI는 Server2022 CPU 경로이고 no-console fault fixture는 실제 NVIDIA GUI viewport가 아니다. 실패가 지속되면 첫 실제 오류/stack/설치 지문을 기준으로 추적한다. 유료 RTX 서버는 종료된 상태를 유지하고 임의 재접속하지 않는다. 실제 RTX final/animation/quality/speed, Metal alignment 및 무거운 씬 orbit/resize의 전체 goal gates는 남아 있다. 새 기능 동결을 유지한다.

Evidence workspace `../dev-tools/reviews/2026-10-19/dlss-stability-package/`: report.json, snapshot.json, platform verification/visual/publication receipts, original Linux native wheel, two complete ZIPs, EXRs/PNGs 및 compressed CI logs를 보존했다. 네이티브/helper/package CI는 모두 종료됐다. cleanup-audit.json의 자체 감독8실행 모두 회수, 잔류 자체 process0, 사용이 끝난 unpack/profile/index/GitHub-cache/미사용 ZIP는 제거했다.
