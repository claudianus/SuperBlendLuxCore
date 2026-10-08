# Cycles 픽셀 필터 가져오기

2026-10-08에 미완료된 픽셀 필터 가져오기를 마무리했다.
Cycles 필터 폭은 종류별 샘플링 구간을 정하는 입력이고, 엔진 필터 폭은
지원 구간의 반지름이다. 모든 종류에 폭의 절반을 적용하면 틀린 결과가 나온다.

| Cycles 종류 | 엔진 종류 | 엔진 반지름 | Gaussian 감쇠 계수 |
|---|---|---|---|
| BOX | BOX | 폭 / 2 | 해당 없음 |
| GAUSSIAN | GAUSSIAN | 폭 × 1.5 | 8 / 폭² |
| BLACKMAN_HARRIS | BLACKMANHARRIS | 폭 | 해당 없음 |

근거는 Blender의 [필터 테이블 구현](https://github.com/blender/blender/blob/main/intern/cycles/scene/film.cpp)이다.
Gaussian은 폭을 3배, Blackman–Harris는 2배 확장한 뒤 대칭 샘플링 구간을
생성한다. Gaussian 평가 함수의 지수는 확장된 폭을 대입하면 -8x²/폭²이다.
엔진 Gaussian은 지지 구간 끝의 값을 빼므로 끝점의 극소 차이는 남는다.

기존 RNA의 반지름 최소값 0.5와 Gaussian 계수 최대값 10은 좁은 Cycles
필터를 잘라냈다. 기본값은 유지하면서 실제 가져오기 값이 저장되도록
하드 제한을 넓히고 UI의 소프트 제한을 유지했다.

`dev-tools/cycles-pixel-filter-test.py`는 Blender 5.2.1에서 3종 필터와
0.01·0.5·1.5·4.0 폭의 12조건을 검사한다. RNA에 저장된 값, 엔진 프로퍼티
내보내기, 반복 가져오기의 값 유지가 모두 통과했다. 내보내기 검사에서는
디노이저를 꺼서 기존 디노이저의 필터 비활성화 정책과 분리한다.

## 격리 개발 설치

`dev-tools/sync_dev_install.sh`의 `SUPERLUXCORE_EXT_BASE`로 확장 디렉터리를
지정할 수 있다. 설정 파일도 지정한 확장 디렉터리의 부모 `config/`에 저장한다.
격리 설치가 기본 사용자 프로필의 wheel 설정을 바꾸지 않도록 했다.

예시:

```bash
SUPERLUXCORE_EXT_BASE=/절대경로/격리프로필/extensions bash dev-tools/sync_dev_install.sh
```
