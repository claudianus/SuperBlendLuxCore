# Cycles Bump zero Filter Width, 2026-10-10

공개2.11.24는 Bump Filter Width=0에서도 양수 precision floor로 Height 미분을 계산하여 원본의 입력 Normal 보존 의미를 바꾼다. 아래는 검증된 private 후보이며 공개 ZIP·실제 사용자 설치 반영은 미완료다. 전체 Cycles 호환 goal은 활성·미완료다.

Blender5.2.1LTS source `9e2066aef7ef7e20c142ad7bd3303138a4304c93`의 `intern/cycles/kernel/svm/displace.h::svm_node_set_bump`는 Filter Width0에서 center/dx/dy를 같은 위치에서 평가하고 zero perturbation이면 입력 Normal로 돌아간다. native CPU는 normal 선택 직후0폭을 처리한다. GPU는 모든 stack pop과 hitpoint restoration을 유지하고0폭에서는 gradient 계산만 생략한다. EVAL_FLOAT/EVAL_SPECTRUM/EVAL_BUMP와 표면 앞·뒤 방향 처리를 보존한다. 일반 native Bump와 양수 폭의 precision floor는 유지한다.

## 재현과 검수

공개2.11.24 exact native `c7439663dcbf734ce5296dee46bf3ed85d689c7381cbaa15330f4c24d0dff322`의 CPU·Metal에서0폭, linked Normal, outer-zero chain, inner-zero chain, Vector Math, MixRGB, backface의7조건씩 실패했다. RGB Normal pass MAE는 약.019〜.036이었다. sandbox 안의 Blender는 Python/render 전에 Metal 초기화 중 crash했으며 해당 시도는 검사 수에서 제외했다. sandbox 밖의 완전 재실행은 양쪽exit0으로7조건씩 실패를 재현했다.

Release native 후보는version2.11.24의 private build로 공개 wheel과 구분한다. full dylibs·순수Python package·metadata·cached wheel을 격리 profile에 맞추고 매 프로세스 native·pkg version·핵심 exporter5개 hash를 guard했다. CPU·Metal native SHA는 `981da75d3123e1a9bd9acab5cf2d0553ebaa7e3459311c027b36e6feb3a2767d`다.

| 대상 | CPU | Metal |
| --- | ---: | ---: |
| plane RGB 기존18 + 새zero-width7 |25|25|
| zero-width7의spectral Normal pass |7|7|
| zero-width7의smooth geometry |7|7|
| 합계 |39|39|

78조건 모두1280×720,16spp,denoise/noisehalt/clamp OFF로 통과했다. 최대RGB component MAE는plane약.000427, spectral약.0000134, smooth약.001369였다. 새로운0폭 plane 조건 대부분은MAE0이며 inner-zero chain도 양수 outer Bump의 의미를 보존한다. 원본 Cycles graph의node/socket/link가 유지되는지 검사했다.

원본 EXR·PNG·metrics·로그·runtime identity를 보존하고 baseline 비교3장, plane회귀7장, spectral2장, smooth2장 총14개 시트를 직접 확인했다. Normal 방향·색·surface detail이 일치하고 기존의 불필요한 gradient가 사라졌다. Normal/data 의미의 검수이며 모든 production beauty·GUI·platform 호환률을 뜻하지 않는다.

CUDA/NVIDIA·공개 ZIP·실제 사용자 설치는 다음 gate다. 현재 공개/실제 설치판은2.11.24다. native 품질 기본값, PDF/MIS/RR, 일반OpenPBR는 변경하지 않았다. 양수SSS 등 남은 호환 범위는 계속 작업한다.

증거: workspace `test-scenes/validation-2026-10-10/bump-filter-zero-candidate`.
