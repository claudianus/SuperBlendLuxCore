# 렌더 설정 기본값 기준, 2026-10-13

add-on의 렌더 기본값은 2026-09-28 `52dd9309` ("curated defaults pass — SOTA features on, deeper paths")에서 51개가 측정 없이 바뀌었다. 이 문서는 그 기본값을 다시 정한 규칙, 바뀐 값, 근거가 된 측정을 정리한다. 회귀 테스트는 `dev-tools/e49_render_defaults_test.py`가 맡는다.

## 문제

- **엔진 기본값 덮어쓰기:** 2.11.28 엔진은 동일 시간 측정을 근거로 Owen scrambling을 끄고, MNEE를 delta 표면이 있는 씬에서만 켜도록 바꿨다(`550ce7e12`). 그런데 add-on은 두 값을 모두 강제로 켠 채 export했다. 그래서 2.11.28 릴리즈 노트의 수렴 개선이 add-on 렌더에는 적용되지 않았다.
- **편향된 기능이 기본값:** variance clamp 1000이 켜져 있었다. 밝은 간접광이 조용히 잘려 Cycles나 엔진 단독 렌더와 결과가 달랐다.
- **경로 깊이:** 25/9/9/24(엔진 값 기준)로, Cycles 씬을 그대로 열었을 때 깊이가 Cycles와 달랐다. `path_depth`는 사용자가 명시한 Cycles 바운스만 읽기 때문에, 바꾸지 않은 Cycles 씬은 add-on 기본값을 쓴다.

## 규칙

- **R1, 정확성:** 편향된 기능은 기본값에서 끈다. 대상은 variance clamp와 filter glossy다. 엔진 기본값과 upstream BlendLuxCore도 같다.
- **R2, 사용자가 보는 상한은 Cycles 5.2를 따른다:**
  - samples 4096
  - bounces 12/4/4/12
  - pixel filter Blackman-Harris 1.5 px
  - animated seed 끔
  - OIDN denoise 켬(기존 값 유지)

  Cycles에서 넘어온 사용자가 같은 씬에서 같은 상한을 기대하기 때문이다.
- **R3, 가속 기능은 엔진이 단일 출처다:** guiding, MNEE, Owen, adaptive, LT focus, partition, portal weight, noise estimation, env light cache에는 엔진 기본값을 쓴다. auto gate가 있는 기능은 add-on이 값을 export하지 않고 엔진의 판단에 맡긴다. 엔진 기본값은 엔진 쪽에서 측정한 값이다.
- **R4, 엔진과 다르게 하려면 측정으로 이겨야 한다:** 동일 시간 two-seed 노이즈 벤치에서 이겨야 한다. 조건은 5개 씬 × CPU·Metal이다.
- **R5, 문서로 남긴 예외:** spectral은 켠 상태를 유지한다. 제품 정체성이다. Cycles 설정 가져오기 연산자는 Cycles와 맞추기 위해 이 값을 끈다.

halt noise level 3%는 측정 없이 이전 값을 그대로 둔다. 후속 과제로 남긴다.

## 바뀐 값

| 설정 | 이전 | 새 값 | 규칙 |
|---|---|---|---|
| Clamp Output | 켬 (1000) | 끔 | R1 |
| Adaptive Sigma | 4 | 6 | R3, clamp를 켰을 때만 의미 |
| Path depth total/diffuse/glossy/specular | 24/8/8/24 | 12/4/4/12 | R2 |
| Pixel filter | 끔, 2.0 | Blackman-Harris 켬, 1.5 | R2 |
| Halt samples | 2048 | 4096 | R2 |
| Animated Seed | 켬 | 끔 | R2 |
| Owen Scrambling | 켬 | 끔 | R3 |
| Adaptive Strength / Error Target | 0.9 / 0.01 | 0.95 / 0.02 | R3 |
| Noise estimation warmup/step | 16/16 | 32/32 | R3 |
| MNEE | 항상 강제로 켬, 2 vertex, 64 iter | 체크 시 엔진 auto gate, 1 vertex, 12 iter | R3 |
| Path Guiding | 켬 (RIS 2, warmup 128, …) | 끔 (엔진 값 RIS 0, warmup 256, glossy 0.3, depth 12, leaves 8192, swap 1M, freeze) | R3 |
| Light Rays (CPU) | 25% | 20% (partition 0.8) | R3 |
| Glossiness Threshold | 0.049 | 0.05 | R3 |
| Connection Probability | 0.3 | 0.5 | R3 |
| Caustic Focus ratio / radius | 70% / 0.02 | 50% / 0.01 | R3 |
| Portal Weight | 0.7 | 0.3 | R3 |
| Env Light Cache | 켬 | 끔 | R3, 미측정 |

바뀌지 않은 값:

- spectral: R5
- OIDN denoise, halt noise level 3%
- GPU light rays 25%: 엔진 taskfraction 0.25와 같다.
- vertex connection 끔: 엔진 기본값과 같다.
- volume depth -1: 엔진 의미와 같다. Volume 산란은 Diffuse 깊이로 센다.

pixel filter는 기본값이 켜져 있어도 `is_pixel_filtering_forced_disabled` 규칙이 그대로 적용된다. denoiser와 hybrid light tracing이 모두 켜진 최종 렌더에서는 필터가 꺼지고, 실제로 적용되는 곳은 denoiser가 꺼진 렌더다.

## 측정

동일 시간 two-seed 노이즈로 측정했다.

- 장비: Apple M5 Pro, CPU와 Metal(`opencl.devices.select=010`)
- 엔진: 2.11.28 wheel
- 렌더: 800×500, 30초
- 지표: `test-scenes/showcase-2026-10-12/publish.py`의 `noise()`. seed 42와 seed 7 렌더의 픽셀별 차이로 구한 상대 RMS 휘도 노이즈다.
- 속도: (엔진 기본값 노이즈 / 변형 노이즈)². 1보다 크면 그 변형이 엔진 기본값보다 빠르다는 뜻이다.
- 공통 조건: 모든 레그에서 spectral은 켰다. clamp·경로 깊이·pixel filter는 노이즈 지표로 정하지 않고 규칙으로 정하므로 모든 레그에서 같게 뒀다.
- 스크립트: `bench_defaults.sh`, `CONF=engine|addon|guiding|adaptive`

변형:

- `addon`: 2.11.28 add-on이 기본 씬에서 export하던 가속 설정 전체. Owen, guiding, MNEE 강제 켜기, adaptive 0.9/0.01, LT focus 0.7/0.02, connectprob 0.3, glossiness 0.049다.
- `guiding`: 그중 guiding 설정만.
- `adaptive`: 그중 adaptive 0.9/0.01만.

| 씬 | 장치 | addon | guiding | adaptive |
|---|---|---|---|---|
| bronze | CPU | 0.80 | 1.00 | 1.02 |
| bronze | Metal | 1.02 | 1.07 | 1.06 |
| roughness | CPU | 0.92 | 0.99 | 1.13 |
| roughness | Metal | 0.90 | 0.98 | 0.95 |
| thinfilm | CPU | 0.82 | 1.00 | 1.13 |
| thinfilm | Metal | 0.89 | 1.00 | 0.98 |
| velvet | CPU | 0.70 | 1.00 | 1.10 |
| velvet | Metal | 0.84 | 1.02 | 0.97 |
| sssheads | CPU | 0.74 | 0.87 | 1.03 |
| sssheads | Metal | 1.19 | 1.08 | 1.04 |

- **addon 전체:** 10개 중 8개에서 졌다. 기하평균 0.87이니 엔진 기본값이 같은 노이즈에 약 15% 빠르다. Owen의 손실은 엔진 쪽에서 이미 측정했다(`550ce7e12`).
- **guiding:** 대부분 무승부다. sssheads CPU에서 0.87로 지고 sssheads Metal에서 1.08로 이긴다. 두 장치 모두에서 이기지 못했으므로 R4에 따라 끈다.
- **adaptive 0.9/0.01:** CPU에서는 5개 씬 모두 이겼다(1.02~1.13, 기하평균 1.08). Metal에서는 0.95~1.06으로 무승부였다(기하평균 1.00). 두 장치 모두에서 이기지 못했으므로 add-on은 엔진 값을 따른다. CPU 쪽 이득은 엔진 기본값을 다시 정할 근거로 남긴다. 엔진이 바뀌면 add-on은 R3에 따라 같이 따라간다.

원본 결과:

- `test-scenes/showcase-2026-10-12/bench-def-s42/`
- `test-scenes/showcase-2026-10-12/bench-def-s7/`
- 로그: `bench-def.log`, `bench-knob.log`

## 남은 일

- 엔진 Sobol adaptive 기본값(0.95/0.02)을 CPU 0.9/0.01 결과로 다시 검토한다. 장치별 기본값이 될 수도 있다.

- env light cache는 실내 env 씬에서 전처리 비용 대비 노이즈 이득을 측정한 뒤 다시 정한다.
- halt noise level 3%의 근거를 측정한다.
