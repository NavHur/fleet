---
name: stack
description: Native GitHub stacked PRs within Pedro's size budget. Use to measure a branch against the budget, split it into layers, carry review fixes through a stack, gate or publish one, or restack it onto a moved base. Not for code review.
---

# Stack

For agent dispatch in T3 Code, read `~/.config/t3-orchestration.md`.
Every check runs through the shared queue in `~/.config/host-validation.md`;
include that path in any handoff that validates.

Set `SKILL_DIR` to this skill's absolute directory. The scripts are in
`$SKILL_DIR/scripts`; each prints its usage with `--help`.

## Pick the task

| Task | Read |
| --- | --- |
| Measure a branch, a commit range or a layer | the size contract below |
| Split a branch into layers, build and gate them | [`references/split.md`](references/split.md) |
| Open the PRs of a built stack and report it | [`references/publish.md`](references/publish.md) |
| Carry review fixes through a stack, then push | [`references/fix-rounds.md`](references/fix-rounds.md) |
| Restack onto a base that moved | [`references/restack.md`](references/restack.md) |

Before any task that installs or gates (split, fix rounds, restack), read
[`references/repos.md`](references/repos.md) for the repository's setup and
gate commands.

## Size contract

Read `references/size-policy.md` for the canonical personal policy: the
pull request, layer and commit sizes, test-file classification,
generated-data exemptions, retirement exceptions, the stack length,
whole-file splits. Apply it only to Pedro's pull requests.

- Measure each layer against its direct parent and each commit against its
  own parent, under the policy's ceilings. Explain any layer under 12 KB
  weighted.
- Keep each behavior change with its tests. Fixtures, helpers, setup and test
  infrastructure count toward both ceilings.
- Every layer and every commit in it builds, typechecks and lints alone, is
  independently understandable and revertible, and the top reproduces the
  source exactly. The tests run once, on the top layer.

`scripts/diff_budget.py BASE HEAD` measures one pair from their merge-base, so
BASE can be a branch name (exit 2: a ceiling is exceeded); with `--per-commit`
it measures every commit in that range under the commit ceilings. It recognizes JS/TS
`*.test.*`/`*.spec.*`, Python and Go test names, lockfiles and
`linguist-generated` files; add `--test GLOB` for other verified test files and
`--generated GLOB` for verified generated paths, including the data exemptions
in the policy's command. Both paths of a rename must qualify.
`scripts/refresh_stack.py` measures every layer of a stack at once.

## Find the stack

A stack's identity (layers, branches, fork points, heads, PRs) comes from
`scripts/stack_layers.py`, for scripts and prose alike (ADR 0003). Most
scripts read it from a manifest directory: one file per layer, sorted in
stack order, whose format and hook contract are in the header of
`scripts/lib.sh`. A split writes the manifests. For a stack built one layer at
a time (`gh stack add`, hand-made branches), derive them from a branch of the
stack:

```bash
python3 "$SKILL_DIR/scripts/derive_manifests.py" --out "$plan/layers"
```

It reads `gh stack view --json` (or `--base B --branches B1 B2 ...`) and
writes `# branch:`, `# pr:` and `# base:` headers, so later commands need
neither `--prefix` nor `--base`.
