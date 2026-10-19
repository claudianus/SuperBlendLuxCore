# 2026-10-19 — Coherent viewport preview versus latest-camera acknowledgement

이전 잠금 해제 후보는 heavy interaction 실패로 폐기했다. 이번 단위는 기존 동작의 exact consume/accept return 분기를 먼저 관찰하고, 원자적 네이티브 프레임을 표시하는 것과 최신 편집 완료를 인정하는 것을 분리했다. Public Windows/Linux fix4와 사용자 기본 설치, primary draw/viewport.py는 변경하지 않았다. 기능 확대/RTX 품질 승격은 하지 않았다.

기존 whole baseline ZIP을 재사용해 stock Blender5.2.2의 격리 profile에서 원본 GenmaB 씬을 실행했다. Main-thread Python trace로 실제 production return line을 기록했다. orbit 중 generation fence에서10개 읽기가 폐기됐고 그중7개는 ready/copied/camera-supported이며 이미 표시한 camera epoch와 worker tag보다 뒤처지지 않았다. 단순 post-fetch probe의 추정과 구분되는 실제 소비 분기 증거다. Trace는 실행시간에 영향을 주므로 성능 수치가 아니다.

새 private 후보 SHA2563ced6e9d5d75841d4e0d3bec2bf770fe9f6002170571483cabdbbf422952573b는 _fetch_pixels와 native/worker를 그대로 두었다. consume_async_update에서 동일 세션의 ready/copied/camera-supported snapshot만 이전 generation preview로 허용한다. future tag, 잘못된 session token, unsupported/legacy/CPU 및 stale denoise는 기존처럼 거부한다. _accept_pixels의 current_generation 인수는 해당 preview가 reset을 해제하거나 최신 편집을 완료로 인정하지 못하게 한다. 실제 camera epoch와 worker tag의 역행 방지는 유지한다. 픽셀·자료형·sampling/material/default·canonical DLSS frame 경로는 바꾸지 않았다. display snapshot은 canonical NGX 입력을 대체하지 않는다.

Production-body host contract15건 중 기존2개 시나리오가 실패했고 후보15/15가 통과했다. 기존 snapshot9/9 및 viewport visual12/12 모델 회귀도 통과했다. 모형 GPU buffer 결과이며 native/RTX 인증이 아니다. 실제 heavy Metal에서는 lagged preview9회가 표시됐고9회 모두 pending reset을 유지했다. 최종3732×2546 film은 finite, read/OIDN/session worker는 회수됐다. Private native8d0be06ed9d6cb0bb5550b3dc1013f89f09171d119ae6f9b8da2a4d24fad5df8는 이전 실험과 동일하며, 공개 fix4 Windows/Linux native와 다르다.

중요한 metric 감사: 기존 visible_latency_s 및 summary.responses는 request 이후 worker mutation tag를 확인하지만, native applied>=requested와 current-generation upload까지 보장하지 않는다. 과거 raw 수치는 보존하되 이를 strict 최신-camera 응답으로 부르지 않는다. 이번 후보의 별도 strict_current_latency_s는 current generation, native camera current, request 이후 tag 및 resize raster 조건을 함께 확인한다. 이 기준은 orbit0/30, resize2/14로 실패했다. 기존 legacy tag 기준은 baseline12/30+2/14, candidate8/30+2/14지만 속도/품질 비교 또는 최신-camera 통과로 쓸 수 없다. 두 새 실행의 geometry는3732×2546로 같았으나 shared/instrumented 독립 진단이며 ABBA/performance_eligible=false, speedup ratio=null이다. 이전1pixel setup 실패는 별도 이전 기록으로 보존한다.

따라서 후보는 private bounded contract로만 보존하고 배포/primary에 채택하지 않았다. 최신 프레임을 제시간에 생산하는 네이티브 작업과 카메라 적용 경계가 다음 진단 대상이다. UI request의 pose와 native applied pose를 독립적으로 연결하는 oracle 없이 새 성능/완료 주장을 하지 않는다. 기존 atomic metadata/buffer capacity/lease/timeout/Stop 계약도 유지해야 한다. 같은 완료 케이스를 반복하지 않는다.

두 실제 스크린샷을 직접 검수했다. 방/통로/바닥은 보이지만 dark region과 coarse spectral colored speckles가 심한 미수렴 화면이다. 최종 품질이나 DLSS 품질 비교 통과가 아니다. NGX evaluations0, 실제 RTX 정상 실행 종료/활성화/파이널/애니메이션/품질/속도, 광범위 Metal 위치 및 CPU/Metal 최종 이미지와 heavy 응답 전체 목표는 미완료다. 이전 worker/native 지문 결과로 대체하지 않는다.

감독 child4개는 모두 exit0/reaped, 잔류 자체 프로세스0. 최종 read-only ps 확인 후 두 자체 profile613476153 logical bytes를 제거했다. 신규 candidate ZIP, 기존 baseline ZIP/원본 shared wheel, logs/images/JSON/source candidate는 보존했다. Primary draw5b165fd8dca299676e06d1b79f4d747282dd768fd5df577aa2f8283ddfa94694, fix4 base18e31ba41e14d3c6ee56eed70a558107513c269e2a188fd2686431d275de912a, 원본 scene f63059830408f03dc6fb803f4fe924815cb7c35ad3aeb95e9cd13d140f1bbfed를 확인했다. 다른 WIP/process/files와 유료 서버 종료 상태를 보존했다.

Evidence: workspace dev-tools/reviews/2026-10-19/viewport-consume-fencing/report.json, exact-consume-analysis.json, goal-acceptance-matrix.json, cleanup.json, visual-review.json. 이전 turn과 이번 turn 모두 progress이며 full goal은 active/incomplete다.
