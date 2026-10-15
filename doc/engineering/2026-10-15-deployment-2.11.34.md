# 정식 배포 2.11.34, 2026-10-15

CPU 뷰포트에서 첫 커스틱이 1초 안에 보이게 하고, add-on 재설치 때 나던 TypeError를 고친 릴리즈다.

- 엔진 소스: `8cee823d55ebf8d5fa6dfe6498481ffb04536f35`
- add-on 소스: `8e514501b3b16c3d86dcb0f2a26d73c71eee58f8`
- 공개 릴리즈:
  - [wheels-v2.11.34](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.34)
  - [v2.11.34](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.34) (Latest)
- 두 tag 모두 위 소스 commit을 가리킨다.
- CI:
  - [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38655727594)
  - [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38658220128)
  - 두 CI 모두 성공했다.

## 포함 내용 (2.11.33 이후)

### 빠른 첫 커스틱 세대

- 문제: 자동 캐시 크기는 필름 픽셀당 포톤 2개다. 레티나 뷰포트(1800×1100)는 포톤 약 400만 개를 모아야 첫 세대가 들어왔다. 수영장 장면에서 5.94초 동안 커스틱이 없었다.
- 변경: 빈 캐시의 첫 백그라운드 세대는 저장 포톤 131072개에서 멈춘다. 반경은 그대로다(노이즈는 많지만 흐려지지 않는다). 교체 직후 전체 크기 세대가 업데이트 주기를 기다리지 않고 바로 시작한다.
- 끄기: `LUX_PGIC_QUICK_FIRST=0`
- 파이널 렌더(PATHCPU/PATHOCL의 CPU 추적 세대)에도 적용된다. GPU 포톤 적재(ingest) 모드는 그대로다.
- 수영장 장면(`scenes/pool`), RTPATHCPU, M5 Pro. 측정 중 부하 평균 약 20:

| 항목 | 2.11.33 | 2.11.34 |
| --- | ---: | ---: |
| 첫 세대 도착 (1800×1100) | 5.94초 | 0.37초 (probe 포함) |
| 전체 크기 세대 도착 | 6.4초 | 6.4초 |
| 바닥 밝기 1초 (1024×600, 2회) | 0.289 / 0.284 | 0.367 / 0.363 |
| 바닥 밝기 3초 | 0.305 / 0.368 | 0.466 / 0.459 |
| 바닥 밝기 30초 | 0.491 / 0.490 | 0.491 / 0.491 |

- 30초 수렴값이 같다. 빨라지기만 했고 결과는 바뀌지 않았다.
- 3초 시점에 2.11.33은 바닥이 노이즈뿐이고, 2.11.34는 물결 커스틱이 보인다. 1초 시점은 둘 다 아직 노이즈가 많다.

### add-on 재설치 TypeError

- 같은 Blender 세션에서 ZIP을 다시 설치하면 legacy alias 등록이 이전 로드의 클래스까지 훑었다. 그 클래스의 annotation은 이미 해제된 PropertyGroup을 가리켜 TypeError 3개가 났다.
- 지금 모듈이 정의한 클래스만 alias한다. alias 집합은 첫 설치와 같다.

## 검수

### 서명과 wheel 일치

- 네 wheel과 네 ZIP 모두 `gh attestation verify`를 통과했다.
- 각 ZIP 안의 `pysuperluxcore-2.11.34` wheel은 공개 wheel과 SHA-256이 같다.
- manifest 버전은 2.11.34다.
- macOS arm64 release wheel 직접 확인: `Version()` 2.11.34. 수영장 1800×1100 RTPATHCPU에서 첫 세대 0.52초, "quick first caustic generation" 로그, 전체 세대 6.74초 뒤 도착.

### 엔진 회귀 테스트 (로컬 빌드, 같은 소스)

- e117 CPU 뷰포트 캐시: 8/8
  - 8번(새 항목): 빠른 첫 세대 1회, 0.44초 뒤 전체 세대 도착.
  - 첫 세대 도착 0.46초(2.11.33 기록 0.78초).
- e116 다중 계면: 4/4
- e115 수영장 SDS: 10/10 (CPU 1.005, GPU 1.002, 패리티 0.997)
- e102 커스틱 라우팅 매트릭스: 14/14
- e54 매질 커스틱: 7/8
  - 4c GPU beam parity(0.0079 vs 0.0083)만 실패한다. 이번 수정 전에도 같은 값으로 실패했다.

### 새 프로필 설치

- 조건: macOS arm64 ZIP, Blender 5.2.1, 빈 `BLENDER_USER_RESOURCES`
- 같은 프로필에 ZIP을 두 번 설치했다. 두 번째 설치에서 TypeError가 나오지 않는다(2.11.33은 3개).
- `public-bundle-render-test.py`, 1280×720, 32 spp:

| 장치 | 2.11.33 | 2.11.34 | RGB 평균 (2.11.34) |
| --- | ---: | ---: | --- |
| CPU | 12.3 s | 11.2 s | 0.3371 / 0.3785 / 0.4612 |
| Metal (M5 Pro) | 5.5 s | 5.3 s | 0.3359 / 0.3771 / 0.4589 |

- Metal 첫 실행은 72.6초(새 바이너리 커널 컴파일)였다. 표의 값은 두 번째 실행이다.
- add-on 회귀 테스트(임시 HOME을 새 프로필로 연결, 실제 프로필은 건드리지 않음): e51 22/22, e49 188/188, e50 9/9, e37 22/22, e43 16/16

### 홈페이지

- 장면 이미지는 다시 렌더하지 않았다. 바뀐 건 첫 세대 시점뿐이고 수렴 결과는 같다. `renderVersion`은 2.11.32로 둔다.
- "점진적 커스틱 캐시" 설명에 "1초 안에 거친 첫 결과"를 추가했다. 다운로드 버전은 2.11.34다.

### 미검증·알려진 문제

- 실제 Blender 뷰포트에서 화면을 돌려 보는 대화형 확인은 하지 못했다. 엔진 수준(e117, pysuperluxcore 수영장 측정)만 확인했다.
- 빠른 첫 세대가 들어온 직후 약 1초는 바닥에 색 노이즈가 많다. 커스틱 무늬는 2~3초쯤부터 또렷하다.
- GPU 뷰포트(RTPATHOCL)에는 아직 커스틱 캐시가 없다.
- 측정 중 부하 평균이 높았다(약 20). 시간 수치는 흔들릴 수 있다.
- NVIDIA 실장비, Intel Mac, Windows Blender 설치는 검증하지 않았다.
- 사용자 실제 Blender 프로필은 갱신하지 않았다.

## 최종 ZIP SHA-256

- `SuperLuxCore-2.11.34-linux_x64.zip`: `89fc484aa1e3d4db43082380d24d318a4910e63b8a8ac594c1a7403fc42442d4`
- `SuperLuxCore-2.11.34-macos_arm64.zip`: `f6c2b014893373e8a84147aa9a6d8f266b07eae18a44c95db64c5146ec283b57`
- `SuperLuxCore-2.11.34-macos_x64.zip`: `3cd9cc17dc7015cc8c56a029019ad0351c7e7ccf8a82dc6a3457b5edfcf3b88f`
- `SuperLuxCore-2.11.34-windows_x64.zip`: `571cbe733ae7afcadd11201618ac4ff4c63ec9d749a57b35260b9b9b3b36f6d9`
