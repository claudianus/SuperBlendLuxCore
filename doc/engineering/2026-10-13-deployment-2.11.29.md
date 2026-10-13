# 정식 배포 2.11.29, 2026-10-13

add-on의 렌더 기본값과 GPU API 표시를 고친 릴리즈다. 엔진 코드는 2.11.28과 같고, 버전 번호만 add-on과 맞춰 올렸다(lockstep). 기존 Cycles 씬을 수동 변환 없이 렌더하는 전체 호환 goal은 계속 활성·미완료다.

- 엔진 소스: `5e1455a24cbed2b5a26c2aa477fd991a2bbb6942`
- add-on 소스: `70c61239fe77a4b3bfa63241799515d8cc3302fc`
- 공개 릴리즈:
  - [wheels-v2.11.29](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.29)
  - [v2.11.29](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.29) (Latest)
- 두 tag 모두 위 소스 commit을 가리킨다.
- CI:
  - [Wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38381821221)
  - [Bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38384655367)
  - 두 CI 모두 성공했다.

## 포함 내용

### 렌더 기본값 (add-on `d10e2806`)

2.11.28 add-on의 기본값은 엔진 기본값을 덮어썼다:

- Owen scrambling 강제
- MNEE를 모든 씬에서 강제로 켬
- guiding 켬
- variance clamp 1000

그래서 2.11.28 엔진의 수렴 개선이 add-on 렌더에는 닿지 않았다. 동일 시간 두 시드 벤치(5개 씬 × CPU·Metal)에서 이 기본값은 엔진 기본값에 10개 중 8개를 졌다(기하평균 0.87).

새 기준 R1~R5와 측정 결과는 add-on 저장소의 `doc/engineering/2026-10-13-render-defaults.md`에 있다.

### GPU API 표시 (add-on `165f7acd`)

- CUDA가 없는 빌드(macOS)의 환경설정에는 "OpenCL"이라는 고정 글자만 보였다. 실제 렌더는 Metal로 돌았다.
- 이제 빌드에 들어 있는 API를 모두 고를 수 있다.
- Devices 패널에 현재 API를 표시한다.

### 정리

- add-on GitHub Pages를 삭제했다(`0ab1e5bf`).
- 홈페이지의 매뉴얼 링크를 지웠다(`0c83d93bc`).
- 홈페이지 다운로드 링크를 2.11.29로 바꿨다.

## 검수

### 서명과 wheel 일치

- 네 wheel과 네 ZIP 모두 `gh attestation verify`를 통과했다.
- 각 ZIP 안의 `pysuperluxcore-2.11.29` wheel은 공개 wheel과 SHA-256이 바이트 단위로 같다.
- manifest 버전은 2.11.29다.

### 새 프로필 설치

- 조건:
  - macOS arm64 ZIP
  - Blender 5.2.1 LTS
  - 빈 `BLENDER_USER_RESOURCES`에 `extension install-file --enable`로 설치
- `dev-tools/public-bundle-render-test.py`를 1280×720, 32 spp로 실행했다:

| 장치 | 버전 | 시간 | RGB 평균 | 오류 |
| --- | --- | ---: | --- | --- |
| CPU | 2.11.29 | 7.4 s | 0.3372 / 0.3785 / 0.4615 | 0 |
| Metal (Apple M5 Pro) | 2.11.29 | 5.6 s | 0.3358 / 0.3771 / 0.4590 | 0 |

- 두 장치의 평균 차이는 0.6% 미만이다.
- Metal 이미지를 직접 확인했다. Voronoi 텍스처, 금속 하이라이트, 유리 커스틱과 그림자가 정상이다.
- 경고는 Eevee 전용 light probe 설정을 무시한다는 안내뿐이다.
- add-on 회귀 테스트:
  - e49 기본값: 188/188
  - e50 무설정 렌더: 9/9
  - e37 adapter parity: 22/22
  - e43 guiding export: 16/16

### 미검증

- NVIDIA 실장비, Intel Mac, Windows Blender 설치는 검증하지 않았다.
- 사용자 실제 Blender 프로필(현재 2.11.27)의 갱신은 자동 권한에서 거부되어 사용자가 직접 설치한다.
- v2.11.28 add-on 릴리즈 노트 정정도 자동 권한에서 거부되어 정정문만 준비했다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.29-linux_x64.zip | `49c399bed2f7a69d41f957683247a5ed0c8618d0adfef10cc69fef5165ce0960` |
| SuperLuxCore-2.11.29-macos_arm64.zip | `c4a136cbfa55f1c3b7477740a26c2aa90885f192bc8db697a065687820344e96` |
| SuperLuxCore-2.11.29-macos_x64.zip | `73a1aeb6c2e07893aac3007ed2b8fa4e3312cf3946782c55d680a5e73cec4d59` |
| SuperLuxCore-2.11.29-windows_x64.zip | `0b9caa593e9679eed616b74ba4b770290b4e5f98f6df9dca1a8b3984a4185794` |
