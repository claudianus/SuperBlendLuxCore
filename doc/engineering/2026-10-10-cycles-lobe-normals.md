# 기존 Cycles Principled의 로브별 법선과 코트 법선

기존 Cycles 노드와 재질 설정을 수정하지 않고 기저·반사·코트·fuzz 법선을 각 로브에 전달한다. 강한 법선에서 앞면을 shading-normal 뒤면으로 오판하여 렌더가 검게 사라지던 문제와, 독립 Coat Normal을 무시하던 문제를 다룬다. 전체 Cycles 씬 호환 완료 기록은 아니다.

## 동작과 품질 계약

- Principled의 `Normal`은 원래 방향 데이터와 범프 체인을 유지한다. 반사·코트에는 원래 `material.cycles.use_bump_map_correction`에 따른 유효 반사 법선 보정을 적용한다. 확산은 원래 법선을 사용한다.
- 연결된 `Coat Normal`은 별도 native `coatnormal` 입력으로 전달한다. 코트 범프는 기저 범프 이전의 기하 미분으로 평가하며, 연결하지 않았으면 기저 법선을 따른다. fuzz는 기저·코트 방향을 코트 가중치로 혼합한다.
- Cycles 재질의 범프 보정은 원래 재질 설정과 로브 의미에 따라 확산에만 적용한다. 반사는 native microfacet masking을 유지한다. 보정을 꺼도 smoothed normal을 통한 뒤면 누수 방지 검사는 유지한다.
- SuperLuxCore 고유 OpenPBR의 Chiang/Conty/None 선택, 분광 기본값, EON 및 금속·굴절 BRDF는 유지한다. 원래 Cycles의 clamp나 Filter Glossy를 품질 맞춤용으로 새로 적용하지 않는다.
- 평가·샘플링·정방향/역방향 PDF를 각 로브 프레임으로 계산하고, 기하학적 반사/투과 의미를 별도 판정한다. 두 Principled를 섞는 Mix도 로브 법선 소유 계약을 유지한다. 모든 혼합 closure 및 양방향 광선 계약의 완전한 검증은 남아 있다.

설치된 Blender 5.2.1 LTS와 같은 소스 `9e2066aef7ef7e20c142ad7bd3303138a4304c93`를 바탕화면의 Blender 소스에서 확인했다. 주요 근거는 `intern/cycles/kernel/svm/closure.h`, `kernel/closure/bsdf.h`, `bsdf_util.h`, `bsdf_oren_nayar.h`다.

## 고정 private 소스 검증 결과

공개 전 2.11.21 private native SHA-256은 `4631c64817a7e44d36437c7a3f25ae93040938a0fc3e6045f6ad9ed6f8edb745`다. 아래 private 결과는 CPU와 Metal을 따로 초기화한 프로필과 고정된 전체 wheel로 검사했다. 현재 공개·사용자 설치 버전은 2.11.21이며, 서로 다른 빌드의 해시와 검수 결과를 별도로 기록한다.

`dev-tools/cycles-reflection-normal-test.py`는 CPU·Metal의 각각 25개 조건을 1280×720으로 비교한다. Cycles 64 samples와 native 기본 분광 128 samples, noise halt 비활성화 조건이다. 보정 켜기/끄기, diffuse roughness, 금속, 독립 코트 벡터·Bump, grazing normal, 앞/뒤면, 두 Principled의 Mix, 영벡터 fallback 및 투과를 포함한다. 금속·확산·코트 등 선택한 11개 조건은 평균 에너지 차이 2.5% gate도 적용한다. 투과의 전체 시각 호환을 그 gate의 통과 수로 세지 않는다.

이전 후보에서 global Chiang을 imported glossy에 추가 적용하여 강한 반사가 크게 어두워지는 원인을 확인했다. 로브 의미에 맞춘 진단에서 금속 평균 0.64369 대 Cycles 0.64400, 확산 0.37244 대 0.37248로 복원했다. 이어서 실제 뒤면 확산 누수 실패를 발견하여 support 검사를 추가했다. 이 전후 결과는 최종 고정 모듈의 통과 증거와 구분한다.

최종 고정 모듈에서 CPU·Metal 각각 25개 조건을 모두 통과했다. 선택한 11개 에너지 조건의 최대 차이는 CPU 1.032%, Metal 1.020%다. 보정 해제의 검은 반사·코트와 잘못된 뒤면 확산 방향도 원래 의미를 유지한다. 에너지 통과가 전체 제작 씬이나 모든 굴절/SSS의 호환 완료를 뜻하지 않는다.

| 최종 소스 검증 | CPU | Metal |
|---|---:|---:|
| 720p 법선·코트 조건 | 25 | 25 |
| Add Shader 회귀 | 5 | 5 |
| Normal Map 회귀 | 8 | 8 |
| Bump 회귀 | 5 | 5 |
| 표적 BIDIR 조건 | 5 | 해당 없음 |
| 독립 기저·코트 Bump 720p 장면 | 1 | 1 |

별도로 native 속성 export/reparse/texture 변경 3개와 native/imported 거친 유리의 CPU 백색로 8개를 통과했다. 백색로는 32픽셀의 수치 회귀이며 제작 장면 검증 수에 포함하지 않는다. 최종 720p 비교 시트 4개, native 장면 2개 및 Cycles 기준 장면 1개를 직접 검수했다. 구 형상의 윤곽과 기저·코트의 서로 다른 반사가 반영된다. 유리 색·노이즈 차이는 남은 범위에 기록했다.

원본 EXR/PNG, metrics, build/설치/렌더 로그와 소스 fingerprint는 workspace `test-scenes/validation-2026-10-09/phase18/lobe-normal-candidate-2.11.21`에 보존한다. 검사에서 허용한 장면 경고는 기본 Eevee light-probe-volume 옵션을 무시한다는 진단뿐이며, 법선 검수 50조건에는 경고·렌더러 오류가 없다.

## 공개 CI·최종 ZIP·실제 설치 검증

엔진 소스 `00a3afb7205d856327b0f16f76f94dbad1967105`와 확장 소스 `84f93cce73087062c73708249097a1c3fe14d5f1`는 main에 반영했고 2.11.21로 공개했다. [네 플랫폼 wheel CI](https://github.com/claudianus/SuperLuxCore/actions/runs/37955453896)와 [최종 ZIP CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37961431687)는 성공했다. 모든 wheel/ZIP의 해시·서명·고정 소스·런타임 파일을 검사했고, 각 ZIP의 367개 Python 파일이 확장 소스와 같다. Intel Mac runtime smoke는 GPU 없는 runner에서 생략되므로 네 플랫폼의 Blender 실렌더를 의미하지 않는다.

공개 ARM native SHA-256은 `0f61daf90d3ad2cb6082d59f837e73fea657133fce39983f82d303b4d985d295`다. 이 모듈로 CI 112개, 최종 ZIP CPU·Metal 40개, 실제 사용자 설치 CPU·Metal 40개를 통과했다. CI 법선 50조건의 선택 에너지 gate 최대 차이는 CPU 1.030279%, Metal 1.015726%다. 총 192개는 회귀·설치·작은 수치 검사이며 독립 제작 씬 수나 전체 호환률이 아니다. 공개 모듈의 비교 시트 6개, 720p native 장면 6개와 Cycles 기준 장면 1개를 직접 검수했다.

현재 실제 Blender 5.2.1 LTS 프로필은 최종 ZIP의 Python·manifest와 공개 ARM 모듈을 사용하며 번들 wheel 설정이다. 새 프로세스의 등록 진단은 없고 실제 Metal GPU 사용도 로그로 확인했다. 업그레이드 CLI의 RNA 등록 진단 3개와 GUI 핫리로드 미검증은 따로 기록한다. [배포 기록](2026-10-10-deployment-2.11.21.md)에 공개 릴리스, 실제 설치, 플랫폼 범위 및 보존 증거가 있다. 별도의 legacy nested releaser는 작업 생성 전 `startup_failure`였고 성공한 standalone builder로 배포했다.

## 남은 범위

Principled Tangent, 커브 전용 보정 경계, 넓은 굴절·SSS·박막·코트 조합, legacy/Null과의 Mix 및 모든 BIDIR/VCM/light-tracing 경로, viewport/F12와 제작 씬·타 플랫폼 실행은 남아 있다. Flat metal grazing 백색로의 약 1% 에너지 초과 및 mapped transmission 밝기 차이도 별도 문제로 유지한다. 공개 wheel·최종 ZIP·실제 사용자 설치의 위 검증은 완료했으며, 이 잔여 의미·제작 검수 범위를 배포 완료와 구분한다.
