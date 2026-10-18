Windows DLSS experimental build / 윈도우 DLSS 실험판

This is an opt-in prerelease for Windows x64 and Blender 5.2 / Python 3.13. The internal engine and add-on version remains 2.11.34; the experimental release tag identifies this separate snapshot. Do not combine its wheel with the stable 2.11.34 add-on.

Install the **windows_x64.zip** asset through Blender → Edit → Preferences → Get Extensions → Install from Disk. The ZIP includes the matching renderer wheel, pinned CUDA NVRTC 12.9.86, the optional CUDA DLSS helper, and the official NVIDIA release Ray Reconstruction runtime. No additional pip install is needed. NVIDIA runtime terms are included separately inside the wheel.

Select an NVIDIA CUDA render device and DLSS in the denoiser settings. The bundled helper/runtime are discovered automatically; the backend/runtime preference fields can remain empty. An appropriate NVIDIA RTX GPU and driver with CUDA Ray Reconstruction support are required. Check the reported backend/status: an ordinary/OIDN fallback is not evidence that DLSS ran.

Included work:

- CUDA Ray Reconstruction integration, independent frame/guide delivery, camera history/reset handling, viewport and final-render integration, and explicit unavailability/fallback reporting.
- Camera and lifetime fixes, CPU orthographic depth of field, and the Phase70 tiled GPU minimum-depth data-cohort repair. Subsequent Phase71 progressive-data-coherence work is excluded.
- Separate raw render preservation; no silent quality/default reduction.

Validation boundaries:

- This Windows build must pass CUDA kernel compilation, Windows renderer build/import, DLSS helper ABI/loading and payload/RECORD checks, plus isolated stock Blender ZIP installation and CPU render before publication. These checks run on GPU-less CI and do not execute NGX.
- The Phase70 source baseline previously passed macOS CPU/Metal camera, 720p still/animation, frame-delivery/lifetime, EXR roundtrip and original heavy-scene functional tests. Those results are not Windows/RTX rendering or performance evidence.
- Actual RTX/NGX image quality, temporal stability, performance and full-scene acceptance remain incomplete. This is not a claim of DLSS 5 neural rendering, frame generation, full feature support, production quality, or a cold-start speedup.
- Known open issues include concurrent progressive/adaptive data-channel coherence, four shared-diagonal Metal intersection cases, slow preparation/resize, low-sample noise, and denoiser smearing in the heavy scene. The visual quality gate remains false.

윈도우 x64용 **실험판**입니다. DLSS CUDA 백엔드와 공식 NVIDIA Ray Reconstruction 런타임을 포함하며, 지원되는 RTX GPU·드라이버에서 DLSS를 선택할 수 있도록 구성했습니다. CI의 DLL 로딩·CPU 렌더 통과는 실제 RTX DLSS 화질·속도 검증을 뜻하지 않습니다. 실제 RTX 검증과 화질 게이트는 미완료이며 DLSS 5 뉴럴 렌더링 지원을 주장하지 않습니다. 기존 안정판과 구별되는 태그로 배포하고, 안정판 최신 릴리스는 유지합니다.
