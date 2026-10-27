# stack_layers.py owns stack identity; lib.sh asks it

A stack's identity (layer order, branches, stack base, fork points, heads, pull requests) is read only by `skills/split-stacked-prs/scripts/stack_layers.py`. The bash scripts get names and branches from `stack_layers.py layers` and the base from `stack_layers.py base` through lib.sh, even though a few lines of `sed` would read the same headers without starting Python. Before this, lib.sh, refresh_stack.py, restack.py and review-loop each parsed manifests or looked PRs up in their own way, and each fix landed in one copy while the others drifted. lib.sh still parses a layer's contents (whole and staged paths, commit sections) in bash, because only build_layers.sh and fix_layers.sh read those.

## Considered Options

- **A bash reader in lib.sh, with Python shelling out to it.** Rejected: the PR lookup and the tests belong in Python, and bash callers need only names, branches and the base.
- **Two readers kept in step by a parity test.** Rejected: the test would catch drift after it happens; one reader cannot drift.
