# Phase73 Metal viewport resize preview checkpoint

This bounded change was verified before Windows GPU teardown became the user's priority. The broader rendering/DLSS goal remains active.

`engine/viewport.py` SHA256 `7ef9814b482cc236a3a8005b15448240d752201d3a92c4423ab35aecd75f7bc3` uses the existing opt-in reduced-resolution interaction preview for large ordinary Metal RTPATHOCL viewport dimension changes. Both current and requested engines must be RTPATHOCL. CPU restart behavior, config-only changes, DLSS branches, and the full-resolution idle restore are preserved.

The final v3 local ZIP SHA256 is `ada9e33b1fc8d4b28bcd10c24c2b9932dfb9a08ccec6e9dc21bd81bca92b725c`. Its native/wheel/kernel are the Phase72 candidate, with only this adapter source change; it is not a public Windows/Linux hotfix and does not include the later teardown changes.

Twenty interaction contracts and eleven resize contracts passed. Four stock Blender 5.2.2 final/animation CPU/Metal cases passed with twelve exact EXR reopen checks. Workers drained. ACES2 and raw sheets were directly reviewed; the simple opaque fixture remains a smoke test, not broad reconstruction quality acceptance.

The corrected same-harness original-building scene probe observed 2/14 resize updates for the baseline and 5/14 for final v3 Metal. CPU remained 2/14. Nine Metal resize observations still missed the strict before-next-input condition. The sample populations differ and shared/cache-intact execution is ineligible for speedup or cold-start claims. The original building file SHA256 remained `f63059830408f03dc6fb803f4fe924815cb7c35ad3aeb95e9cd13d140f1bbfed`. Heavy output was still dark/noisy/coarse and did not pass final quality acceptance.

Timeline analysis showed repeated config updates and deferred camera edits; this is a next diagnostic hypothesis, not a proven additional cause. The 720p wavefront timeout, historical Metal edge misses, current RTX acceptance and wider material/motion/volume gates remain open. Superseded v1/v2 ZIPs/profiles and obsolete raw duplicates were removed, reclaiming 1,439,406,320 bytes; final artifacts, identities, logs and review images were retained.

Evidence: workspace `dev-tools/reviews/2026-10-16/dlss/phase73/phase73-report.json`, `visual-review.json`, `prototype-cleanup.json`, and per-case receipts. Default Blender installation was not changed and this local candidate was not published.
