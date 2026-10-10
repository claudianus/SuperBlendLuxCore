# Private Cycles BSSRDF hybrid fixture and raw-region review

The private experimental wrapper supports CPUHYBRID alongside CPU eye, Metal
eye and LIGHTCPU. It selects the native experimental/adjoint opt-ins in process
and records separate eye/light halt budgets. The public reader is unchanged;
this is not positive-radius production SSS deployment.

Two authored Cycles graphs place sharp/rough Subsurface Scattering beneath a
closed sharp Glass slab. The fixture keeps its graphs/settings unchanged across
engines and fingerprints all materials, world graph, light values, transforms
and Cycles filter settings. The closed slab preserves an exterior medium.
1280x720 comparisons use Cycles128, eye128 and hybrid eye128/light512; actual
hybrid eye work is higher because of the partition. These are quality checks,
not matched-budget timing comparisons.

`cycles-bssrdf-regional-review.py` reads raw EXRs after rendering and removes
loaded images on exit. Its predefined radius240 interior circle excludes the
white background. It records exact input hashes, means and the unchanged 3%
per-channel gate against an independent CPU eye reference. It explicitly
records production_acceptance and directly_reviewed as false; image review
must be recorded separately. Failed diagnostic outputs can be measured without
being silently promoted to acceptance.

The initial hybrid's body was 36.4%/38.0% brighter, despite far smaller whole-frame
errors. The native PSR partition fix reduces the same region's sharp/rough
errors to 0.661%/1.030%. Direct review of the four corrected Cycles/hybrid PNGs
confirms shape, orientation, warm hue and scattering meaning. Strong chromatic
grain, especially in the rough hybrid, remains a production-quality issue.

The native unit also fixes forced Metropolis acceptance and a missing return in
Metal mirror PSR sampling. Exact native fingerprints and detailed scope are in
SuperLuxCore's matching engineering note. Exact new CI-wheel checks and broader
production adapter integration remain necessary; full Cycles compatibility is
an active goal, not a result of these private fixtures.
