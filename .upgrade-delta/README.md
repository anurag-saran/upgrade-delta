# .upgrade-delta/ — the vendorable bundle

This directory is meant to be copied WHOLESALE into the root of a target application
repository (not used from inside the upgrade-delta tool repo itself). It contains everything
the live/real pipeline needs to run standalone in that repo: the tool (`upgrade_delta.py`),
the Lightwell catalog, and the pom-diff-driven pipeline scripts and Task/Pipeline YAML.

See `real-pipeline/README.md` for the full setup guide.
