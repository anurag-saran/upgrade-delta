# .upgrade-delta/ — the vendorable bundle

**Generated** by `scripts/sync-vendor-bundle.sh`. Do not edit files here by hand;
change the sources and re-run the sync script.

| Bundle path | Source of truth |
|-------------|-----------------|
| `upgrade_delta.py` | repo root `upgrade_delta.py` |
| `catalogs/` | repo `catalogs/` |
| `jacoco/` | `integration/jacoco/` |
| `real-pipeline/` | `integration/tekton/real-pipeline/` plus shared tasks from `integration/tekton/task-upgrade-delta-*.yaml` |

Copy this directory wholesale into a target application repository so the live/real
pipeline can run standalone. See `real-pipeline/README.md` for setup.
