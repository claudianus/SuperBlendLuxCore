# 정식 배포 2.11.32, 2026-10-14

수영장 바닥 같은 SDS 커스틱을 설정 없이 렌더하도록 고친 릴리즈다. 2.11.30, 2.11.31은 wheel만 공개했고 add-on 번들은 draft로 남겼다. 2.11.32가 이 둘을 대체한다.

- 엔진 소스: `5a888cccdae9717ba54dd472bf9392be348245be`
- add-on 소스: `207f76e2069cc76d734482cd9756e7d361f87030`
- 공개 릴리즈:
  - [wheels-v2.11.32](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.32)
  - [v2.11.32](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.32) (Latest)
- 두 tag 모두 위 소스 commit을 가리킨다.
- CI:
  - [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38557765731)
  - [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38561409609)
  - 두 CI 모두 성공했다.

## 포함 내용 (2.11.29 이후)

### 무설정 SDS 커스틱 (2.11.30)

- `path.photongi.caustic.auto`가 Disney(Principled) 바닥도 커스틱 수신면으로 인정한다.
- add-on의 `caustic_mode=auto`는 PATH 계열 엔진에서 `caustic.enabled`를 내보내지 않는다. 그래서 장면을 보고 켤지 말지를 엔진이 정한다.
- e115 수영장 테스트 기준, 기준 이미지 대비 비율:

| 바닥 | CPU | GPU |
| --- | ---: | ---: |
| 매트 | 1.004 | 1.000 |
| Disney | 1.005 | 0.995 |

### 산란 매질 씬 제외 (2.11.31)

- 안개처럼 산란하는 매질이 있으면 caustic.auto가 캐시를 켜지 않는다.
- 이유: fogbeam 씬에서 캐시를 켜면 BIDIRCPU 기준보다 3.4배 밝게 나왔다(빔 안에서는 11.5배). 원인은 아직 열려 있다.
- 산란이 0인 맑은 물은 계속 켠다(e115 6번).

### 커스틱 조회 반경 자동값 (2.11.32)

2.11.31의 캐시는 정확했지만 매우 느렸다.

- 원인:
  - 자동 반경이 화면의 2%(800px 폭에서 약 16px)였다. 이 값은 간접광 캐시에 맞춘 크기다.
  - 커스틱 광자는 픽셀당 약 2개로 배정된다. 그래서 눈 경로 정점마다 수백 개의 광자를 모았고, 광자마다 BSDF를 한 번씩 평가했다.
- 변경: 커스틱 반경을 그 값의 1/5(약 3px)로 줄였다.
- 1/10로 줄이면 낮은 주파수 얼룩이 보였다.

수영장 800×500, 20초, 캐시 상태별 결과:

| 설정 | spp |
| --- | ---: |
| 캐시 끔 | 218 |
| 2.11.31 자동 | 24 |
| 2.11.32 자동 | 145 |

- 2.11.32에서는 커스틱 선도 더 선명하다.
- 1600×1000에서는 캐시 끔 61, 2.11.32 자동 24 spp다. 첫 캐시 패스 비중이 커서 차이가 더 크다.

### 홈페이지

모든 SuperLuxCore 이미지를 2.11.32 release wheel로 다시 렌더했다(`finals-2.11.32.sh`). fogbeam은 캐시가 꺼지는 씬이라 2.11.31 렌더를 유지했다.

- 같은 시간 동안의 spp, 2.11.30 → 2.11.32:

| 이미지 | 2.11.30 | 2.11.32 |
| --- | ---: | ---: |
| pool (120초) | 16 | 124 |
| spectrum (120초) | 68 | 405 |
| hologram (90초) | 55 | 222 |
| hero (2400×1350, 600초) | 76 | 912 |

- spp는 로컬 빌드 렌더 기준이고, release wheel 재렌더 영수증은 `docs/evidence`에 있다.
- 퍼니스 수치를 2.11.30에서 다시 쟀다(1024 spp):

| 거칠기 | 업스트림 | CPU | Metal |
| ---: | ---: | ---: | ---: |
| 0.5 | 0.846 | 0.997 | 0.991 |
| 1.0 | 0.251 | 0.998 | 0.975 |

- Disney 배경이 업스트림보다 밝은 이유를 페이지에 밝혔다. 업스트림은 조명 샘플링한 Disney 셰이딩에 cos θ를 두 번 곱하고, 포크는 2.11.28에서 이를 고쳤다.

## 검수

### 서명과 wheel 일치

- 네 wheel과 네 ZIP 모두 `gh attestation verify`를 통과했다.
- 각 ZIP 안의 `pysuperluxcore-2.11.32` wheel은 공개 wheel과 SHA-256이 같다.
- manifest 버전은 2.11.32다.

### 엔진 회귀 테스트 (로컬 빌드, 같은 commit)

- e115 수영장 SDS: 10/10
- e102 커스틱 라우팅 매트릭스: 14/14
- e54 매질 커스틱: 7/8
  - 4c GPU beam parity(0.0078 vs 0.0083)만 실패한다.
  - 이 실패는 2.11.30 이전부터 있었다.

### 새 프로필 설치

- 조건: macOS arm64 ZIP, Blender 5.2.1, 빈 `BLENDER_USER_RESOURCES`
- `public-bundle-render-test.py`를 1280×720, 32 spp로 실행했다:

| 장치 | 2.11.29 | 2.11.31 | 2.11.32 | RGB 평균 (2.11.32) |
| --- | ---: | ---: | ---: | --- |
| CPU | 7.4 s | 50 s | 11.2 s | 0.3371 / 0.3785 / 0.4616 |
| Metal (M5 Pro) | 5.6 s | 61 s | 5.5 s | 0.3359 / 0.3770 / 0.4588 |

- RGB 평균은 2.11.29와 0.1% 안에서 같다.
- Metal 이미지를 직접 확인했다. 유리 커스틱이 정상이다.
- add-on 회귀 테스트: 임시 HOME을 새 프로필로 연결해 실행했고, 실제 프로필은 건드리지 않았다.
  - e49: 188/188
  - e50: 9/9
  - e51: 13/13
  - e37: 22/22
  - e43: 16/16

### 미검증·알려진 문제

- NVIDIA 실장비, Intel Mac, Windows Blender 설치는 검증하지 않았다.
- 사용자 실제 Blender 프로필은 갱신하지 않았다.
- 산란 매질과 커스틱 캐시를 함께 쓸 때의 바이어스는 원인을 찾지 못했다. 자동 경로에서만 막았고, 손으로 켜면 여전히 나타난다.
- `wheels-v2.11.30` wheel은 공개 상태이고 이 바이어스가 있다.
- add-on draft v2.11.30, v2.11.31은 삭제하지 않았다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.32-linux_x64.zip | `0042a1922e6cbab5506df35b37e0a06a4d822d8f9f8d7cb93744f62df003d91d` |
| SuperLuxCore-2.11.32-macos_arm64.zip | `99a03c5017225483cf3a2cb631e21ac506bbdf99a9c58c6eaefad62b4150dec4` |
| SuperLuxCore-2.11.32-macos_x64.zip | `10a5529dc0a1f9220cbc5001f6218d129ad2d216aba14202804e4e9116d8b33a` |
| SuperLuxCore-2.11.32-windows_x64.zip | `e458e3b72e2246bc63cd1013a122c3555575c03f348c98d66e2762939008d836` |
