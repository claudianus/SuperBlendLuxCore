# 정식 배포 2.11.28, 2026-10-13

2.11.27 이후 엔진 main의 40개 commit과 add-on main의 28개 commit을 한 번호로 묶은 정식 릴리즈다. 기존 Cycles 씬을 수동 변환 없이 렌더하는 전체 호환 goal은 계속 활성·미완료다.

- 엔진 소스: `4d1c87ee34b79bba0053fdb16abc2b52619e2b2b`
- add-on 소스: `9f4edaf3cd835cd9cf91f49600e1f29a87fdd91f`
- 공개 릴리즈:
  - [wheels-v2.11.28](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.28)
  - [v2.11.28](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.28) (Latest)
- 두 tag 모두 위 소스 commit을 가리킨다.
- CI:
  - [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38348076891): 네 플랫폼, NVRTC gate, attest 모두 성공.
  - [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38349892768): version lockstep, bundle, attest 모두 성공.
  - tag push run은 이미 공개된 릴리즈라서 건너뛰었다.

## 포함 내용

### PATHOCL·PATHCPU 동일 시간 수렴 개선 (`550ce7e12`)

- Sobol의 Owen scrambling을 기본으로 끔
- Distribution1D guide table
- MNEE는 delta 표면이 있는 씬에서만 켜짐
- 면광원·하늘만 있는 씬에서 light tracing 자동 생략
- 512K task와 upstream의 메모리 상한
- kernelTables LUT
- Vulkan clspv OpenPBR 수정
- Metal 씬별 타입 특수화

### Cycles BSSRDF 실험 경로 (CPU·device, adjoint·hybrid·rough)

- private 플래그로만 켜진다.
- 배포 add-on의 standalone SSS 경로와 품질 기본값은 바뀌지 않는다.

### VDB와 볼륨

- index-grid 재구성, Linear·cubic 필터
- 이름이 있는 grid와 grid별 affine 변환, sequence frame
- Principled Volume 흡수색의 제곱근 처리
- 유한 heterogeneous emission

### 장면 편집 시 상태 리셋

- film·adaptive luminance·native worker film·Metal host film 리셋
- blackbody SPD 캐시
- sparse Metropolis 초기화 수정

### 홈페이지

- Mac·PC 동일 시간 속도 비교를 추가했다.
- 다운로드 버튼이 rolling `latest` 대신 이 버전 ZIP을 가리키도록 바꿨다.
- 대표·비교 이미지는 2.11.27 표기 빌드로 렌더한 것이므로, 캡션은 `renderVersion` 2.11.27로 유지했다.

## 검수

### 서명

- 네 wheel과 네 ZIP 모두 `gh attestation verify`를 통과했다.
- 각 서명의 source digest는 위 엔진·add-on commit과 같다.

### wheel 일치

- 각 ZIP 안의 `pysuperluxcore-2.11.28` wheel은 공개 wheel과 SHA-256이 바이트 단위로 같다.
- manifest 버전은 2.11.28이다.
- Linux·Windows ZIP에는 NVRTC 12.9.86 wheel이 추가로 들어 있다.

### 새 프로필 설치

- 조건:
  - macOS arm64 ZIP
  - Blender 5.2.1 LTS(`9e2066aef7ef`)
  - 빈 `BLENDER_USER_RESOURCES`에 `extension install-file --enable`로 설치
- `dev-tools/public-bundle-render-test.py`를 기본 spectral 1280×720, 32 spp로 실행했다:

| 장치 | 버전 | 시간 | RGB 평균 | 오류 |
| --- | --- | ---: | --- | --- |
| CPU | 2.11.28 | 9.9 s | 0.3372 / 0.3786 / 0.4625 | 0 |
| Metal (Apple M5 Pro) | 2.11.28 | 5.7 s | 0.3359 / 0.3776 / 0.4607 | 0 |

- 두 장치의 평균 차이는 0.5% 미만이다.
- Metal 이미지를 직접 확인했다: Voronoi 텍스처, 금속 하이라이트, 유리 커스틱과 그림자 정상.
- Metal 시간에는 커널 캐시가 있었다. 같은 스크립트로 캐시 없이 처음 실행했을 때는 133 s였다.
- 이 검사는 smoke 수준이다. 2.11.27 배포처럼 154개 조건을 반복하는 검사는 이번에 다시 하지 않았다.

### 미검증

- NVIDIA 실장비의 2.11.28 ZIP 렌더는 하지 않았다. 앞선 속도 측정은 같은 소스의 개발 빌드로 했다.
- Intel Mac과 Windows Blender 설치도 검증하지 않았다.
- 실제 사용자 Blender 프로필은 갱신하지 않았다.

## 알려진 한계

- GPU에서 upstream이 아직 더 빠르다:
  - thin film: M5 Pro, RTX 5060 Ti 모두
  - velvet: RTX 5060 Ti (M5 Pro에서는 동률)
- 원인 후보는 task당 GPU 상태 크기다(GPUTask 912 vs 664 B 등). [gotchas](https://github.com/claudianus/SuperLuxCore/blob/main/doc/engineering/gotchas.md)에 기록했다.
- 일반 양수 standalone SSS는 여전히 Cycles보다 어둡다.
- displacement, OSL, baking은 열린 범위이거나 유보 상태다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.28-linux_x64.zip | `63a4f5fabf0a920bbdd7f4b844502c8b8f730150960cc89eb7c36cc2eab093e3` |
| SuperLuxCore-2.11.28-macos_arm64.zip | `522b2df6a1b370c391effb1266b0806a28ee5f4947dca49a909f1663cf761bfa` |
| SuperLuxCore-2.11.28-macos_x64.zip | `979a2896c110070ad198cbc07fefafa742244c1e8a80f7febdfa6be33fe4cbff` |
| SuperLuxCore-2.11.28-windows_x64.zip | `8abbd58be50de8d7f4134033dad5294d6818bae576edeeb7e5328118dd2e4ba6` |
