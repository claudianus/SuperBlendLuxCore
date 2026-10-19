# Adapter repository consolidation — 2026-10-19

The complete pre-existing adapter WIP was committed as `01823295`, preserving
DLSS integration, worker Stop ownership, camera snapshots, resize transactions,
SSS export policy, regression probes and detailed engineering reports.

All five remote release/review branches and the dirty Phase72 validation
worktree are now ancestors of local main. Older snapshot code and CRLF-only
node changes were superseded by current source. Production Python contents and
the stable 2.11.34 manifest were preserved from the checkpoint. Missing original
Windows release/fix2 engineering documents were imported. The validation
worktree and its temporary preservation branch were retired after ancestry and
clean-status checks.

Fourteen adapter host regression scripts passed using the existing native
Python 3.13 venv; the seven-case production-body viewport Stop ownership test
also passed. Native Release/CPU/Metal and packaging checks are recorded with
the renderer maintenance report. This does not certify actual RTX/NGX image
quality, heavy viewport response or a new installed-addon release. The final
documentation commit uses `[skip ci]`; public package publication is outside
this repository-maintenance change.

See the renderer's
`doc/engineering/2026-10-19-repository-consolidation.md` and workspace
`dev-tools/maintenance/2026-10-19-main-cleanup/` for complete merge, storage,
dependency, source-preservation and verification receipts. Workspace helper
scripts and authored research evidence remain preserved outside the component
repositories. Identical historical evidence files now share hard links; keep
them immutable and create a new copy for new experiments.
