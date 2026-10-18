# Installed CPU SSS interior-loop delivery

The core now defaults to a dedicated non-emitting homogeneous SSS eye loop,
exact per-walk coefficient reuse, deferred unused boundary shading and
certified zero-contribution NEE elision. Physical coefficients, phase, global
geometry, refractive interfaces, spectral mode, path budgets and PDF/MIS/RR
compensation are preserved. Optical-position boundary guiding and albedo-
weighted transport-channel proposals improve sampling. No denoiser, clamp,
similarity/diffusion replacement or geometry reduction is used. See the core
doc/engineering/2026-10-19-sss-interior-loop.md for eligibility and fallbacks.

Actual stock Blender5.2.2LTS d13f752e3b9c loads final native
272cb66812472d4203ffe0ab35ff4aba8f50ac11b0ef1de76b712f453a561c82
from its installed dependency folder without an override. Complete wheel
d619c7bafbe5e18432af691121dd0445c57d349cf41838a7c63d405a73f875c0
is in workspace dist/sss-loop-cpu-20261019. CPU spectral F12 completes all
144 samples per pixel and saved linear EXR equals engine RGB exactly. All393
installed adapter Python files are preserved. Wheel cache, LOCAL source and
191 hashed installed files in RECORD are read back after host exit.

The fixture matches geometry/lights/authored optical inputs/filter/CPU4threads
and uses320x180 raw EXR with denoising/clamping/adaptive sampling off. Native
refractive bulk and Cycles nonlocal BSSRDF are distinct models, each with its
own finite4096SPP reference retained from the earlier study.

Same-binary execution-only ABBA100SPP:9.945s generic versus6.247s dedicated.
Matched seed17 previous81SPP/new144SPP:8.708s/8.696s mean ABBA. RGB3seed SSS
RMSE lower16.2--22.3 percent; empirical variance lower34.6 percent and standard
deviation19.2 percent. Those3seed quality times average8.277s/8.708s (5.2
percent more wall for the new budget), distinct from matched seed17 ABBA.
Cycles400SPP averages8.997s and is visibly much smoother. Spectral81/144SPP
means11.163s/9.935s, empirical variance lower44.3 percent (std25.4 percent).
These are small-fixture shared-host observations, not global speed/quality
certification; the native artifact includes pre-existing local core WIP.

sss_loop_compare.py runs explicit JSON plans with sequential owned process
groups, bounded admission waits and timeout cleanup. sss_matched_benchmark.py
records full per-pixel sample counts, native identity, raw/EXR equality and
host settings. sss_compare_analyze.py --references points to the earlier
model-specific references. Keep factory-startup tests in explicit isolated
resources/config/extensions roots; actual-profile validation uses a fresh
unsaved scene/world without factory-startup. Retired temporary profiles and
packages can be reconstructed from the complete retained wheels.

Evidence: workspace test-scenes/validation-2026-10-19/sss-loop/report.json,
fingerprints.json, matched-variance.json, convergence.json, matched-rgb.png,
installed-spectral/result.json and the installation readback receipt.
