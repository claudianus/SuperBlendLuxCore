# 정식 배포 2.11.33, 2026-10-15

유리를 여러 겹 지나는 커스틱을 설정 없이 렌더하고, CPU 뷰포트에서도 커스틱 캐시를 쓰도록 한 릴리즈다.

- 엔진 소스: `a7ad2aa443173c879dffedc52628716d641b8326`
- add-on 소스: `20aadb923fe0d312caf9f79601d4af34684facbd`
- 공개 릴리즈:
  - [wheels-v2.11.33](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.33)
  - [v2.11.33](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.33) (Latest)
- 두 tag 모두 위 소스 commit을 가리킨다.
- CI:
  - [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38631221684)
  - [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38636519759)
  - 두 CI 모두 성공했다.

## 포함 내용 (2.11.32 이후)

### 다중 계면 커스틱

- 문제: 코어의 기본 포톤 깊이는 4다. 바닥에 닿기 전에 델타 계면 3개까지만 지날 수 있다. caustic.auto가 켜지면 눈 경로는 캐시가 대신하는 빛 경로를 끊는다. 그래서 더 긴 체인은 어둡게 나왔다.
- 영향 범위: Python/SDL 사용자. Blender add-on은 원래 16을 내보냈다.
- 변경: caustic.auto가 켜지고 `path.photongi.photon.maxdepth`가 지정되지 않았으면 16으로 올린다. 직접 지정한 값은 그대로 둔다.
- 반경 탐색(probe)은 깊이 4로 고정했다. 깊이 16 probe는 시작을 0.9초 늦췄다.
- e116 결과(매트 바닥 위 유리판, 캐시 없는 PATHOCL 기준 대비):

| 장면 | 결과 |
| --- | ---: |
| PATHCPU 유리판 1장(계면 2개) | 1.002 |
| PATHCPU 유리판 3장(계면 6개) | 1.000 |
| PATHOCL 유리판 3장 | 1.000 |
| 참고: 포톤 깊이 4로 고정(RTPATHCPU) | 0.874 |

- 비용: 계면이 적은 장면에서는 이득 없이 포톤 추적만 길어진다. 홈페이지 pool(400×250, 256 spp)은 2.11.32의 7.7–7.9초에서 8.4–8.7초가 됐다(깊이 4로 지정하면 7.6–7.7초). 이미지 중앙값은 같다.

### CPU 뷰포트 커스틱 캐시 (RTPATHCPU)

- caustic.auto가 RTPATHCPU에서도 켜진다. Blender CPU 뷰포트가 이 엔진이다.
- 첫 세대는 백그라운드 작업자가 만든다. 반경 probe도 여기서 돈다. 그동안 뷰포트는 캐시 없이 바로 그린다.
- 세대가 준비되면 뷰포트가 그리는 스레드에서 렌더 스레드를 잠시 세우고 교체한다.
  - 첫 세대: 프레임을 다시 시작한다(그전까지 경로 추적한 SDS 반딧불이 평균에 남지 않게).
  - 이후 세대: 프레임을 이어서 누적한다.
- 카메라만 바뀐 편집은 캐시를 유지한다. 재질·조명·형상 편집은 캐시를 다시 만든다.
- add-on: CPU 뷰포트에서만 켠다. 재질 미리보기와 GPU 뷰포트(RTPATHOCL)는 계속 끈다.
- e117 결과(96×96, 유리판 3장):

| 항목 | 결과 |
| --- | --- |
| 첫 프레임 | 35 ms |
| 첫 세대 도착 | 0.78초 |
| 정상 상태 바닥 | 기준 대비 1.002 |
| 카메라 편집 20회 | 재생성 0회, 편집 중앙값 10.2 ms(캐시 끔 10.7 ms), 3초 뒤 바닥 0.995 |
| 재질(조명 세기) 편집 | 재생성 1회, 편집 11 ms, 수렴 1.000 |
| 세대 진행 중 중지 | 0.00초 |

- 수영장 960×720 뷰포트: 첫 세대까지 2.9–3.7초(유휴 상태 기준).
- 카메라를 계속 돌리는 동안 진행 중이던 세대는 편집마다 중단되고, 멈추면 다시 시작한다.

### pysuperluxcore 종료 크래시

- `Init(handler)`로 로그 핸들러를 등록한 채 Python이 끝나면 SIGSEGV(exit 139)가 났다. 2.11.32에도 있던 문제다.
- atexit에서 핸들러를 해제하도록 고쳤다.

## 검수

### 서명과 wheel 일치

- 네 wheel과 네 ZIP 모두 `gh attestation verify`를 통과했다.
- 각 ZIP 안의 `pysuperluxcore-2.11.33` wheel은 공개 wheel과 SHA-256이 같다.
- manifest 버전은 2.11.33이다.
- macOS arm64 release wheel 직접 확인: `Version()` 2.11.33, RTPATHCPU에서 caustic.enabled=True, 포톤 깊이 16, 정상 종료.

### 엔진 회귀 테스트 (로컬 빌드, 같은 소스)

- e117 CPU 뷰포트 캐시: 7/7
- e116 다중 계면: 4/4
- e115 수영장 SDS: 10/10 (CPU 1.004, GPU 1.003, 패리티 0.999)
- e102 커스틱 라우팅 매트릭스: 14/14
- e54 매질 커스틱: 7/8
  - 4c GPU beam parity(0.0078 vs 0.0082)만 실패한다. 2.11.30 이전부터 있던 실패다.

### 홈페이지 장면 A/B (2.11.32 release wheel vs 2.11.33, 400×250, 256 spp, seed 2개)

| 장면 | 평균 비율 | seed 간 차이 | 버전 간 차이 |
| --- | ---: | ---: | ---: |
| pool | 0.973 | 0.565 | 0.141 |
| spectrum | 1.001 | 0.096 | 0.008 |
| hologram | 1.000 | 0.078 | 0.010 |

- pool의 평균 차이는 반딧불 노이즈다. 2.11.32끼리도 seed 따라 1.8% 다르고, 중앙값은 0.312/0.328 대 0.311/0.314로 같다.
- 그래서 홈페이지 이미지는 다시 렌더하지 않았다. `renderVersion`은 2.11.32로 둔다.
- 홈페이지 "점진적 커스틱 캐시" 기능 설명에 다중 계면과 CPU 뷰포트를 추가했다. 다운로드 버전(`version`)은 2.11.33으로 올렸다.

### 새 프로필 설치

- 조건: macOS arm64 ZIP, Blender 5.2.1, 빈 `BLENDER_USER_RESOURCES`
- `public-bundle-render-test.py`를 1280×720, 32 spp로 실행했다:

| 장치 | 2.11.32 | 2.11.33 | RGB 평균 (2.11.33) |
| --- | ---: | ---: | --- |
| CPU | 11.2 s | 12.3 s | 0.3372 / 0.3786 / 0.4616 |
| Metal (M5 Pro) | 5.5 s | 5.5 s | 0.3358 / 0.3771 / 0.4589 |

- Metal 첫 실행은 161초였다. 새 바이너리라 커널을 처음 컴파일한 시간이고, 두 번째 실행이 5.5초다.
- RGB 평균은 2.11.32와 0.05% 안에서 같다.
- add-on 회귀 테스트(임시 HOME을 새 프로필로 연결, 실제 프로필은 건드리지 않음):
  - e51: 22/22 (CPU 뷰포트 라우팅 6개 추가)
  - e49: 188/188
  - e50: 9/9
  - e37: 22/22
  - e43: 16/16

### 미검증·알려진 문제

- 실제 Blender 뷰포트에서 화면을 돌려 보는 대화형 확인은 하지 못했다(백그라운드 Blender는 view_draw를 실행하지 않는다). 엔진 수준(e117)과 add-on export 라우팅(e51), 그리고 add-on이 카메라 회전 때 카메라 속성만 보낸다는 코드 확인으로 대신했다.
- GPU 뷰포트(RTPATHOCL)에는 아직 커스틱 캐시가 없다. 교체 프로토콜이 없다.
- 측정 중 다른 프로그램이 돌아 부하 평균이 높았다(최대 약 56). 시간 수치는 흔들릴 수 있다.
- NVIDIA 실장비, Intel Mac, Windows Blender 설치는 검증하지 않았다.
- 사용자 실제 Blender 프로필은 갱신하지 않았다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.33-linux_x64.zip | `d7d23f193c4772e95dc60914bce28e03a86ab9e0285a6b9dad639cd878f23510` |
| SuperLuxCore-2.11.33-macos_arm64.zip | `4dd5d1103faa7c5a08f503c51366fca47f91002a0e0a627c08a0915f9dbd59d2` |
| SuperLuxCore-2.11.33-macos_x64.zip | `6268e7223190e7b5065adec827cc840aa773448718ce99fc36dec16a86a46d82` |
| SuperLuxCore-2.11.33-windows_x64.zip | `69b6fa7fa70335073861586ac4c70144c569db61c99241a039dfffcc456997d8` |

- Rolling `latest` 번들도 2.11.33 wheel로 다시 만들었다([wheels-latest CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38639260658), [bundle_latest CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38642934122)).
