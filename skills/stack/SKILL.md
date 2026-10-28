---
name: stack
description: Native GitHub stacked PRs, layers of small commits within Pedro's byte-size ceilings. Use to split a large branch into dependency-ordered layers, to carry review fixes through, gate, or re-measure an existing stack, or to restack one that fell behind its base. Not for code review.
---

# Stack

For agent dispatch in T3 Code, read `~/.config/t3-orchestration.md`.
Every check runs through the shared queue in `~/.config/host-validation.md`;
include that path in any handoff that validates.

Set `SKILL_DIR` to this skill's absolute directory. The scripts are in
`$SKILL_DIR/scripts`; each prints its usage with `--help`. The manifest format
and the hook contract are in the header of `scripts/lib.sh`; `stack_layers.py`
answers a stack's layers (branch, fork point, head, PR) for scripts and prose.

## Enforce the contract

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

## 1-5. Split, build and verify

Read [`references/split.md`](references/split.md): source and recovery
points, inventory, layer design, the build, and every layer's gates.
[`references/repos.md`](references/repos.md) holds each repository's setup
and gate commands.

## 6. Publish with native GitHub stacks

```bash
gh stack init --base "$base_branch" "$branch_1" "$branch_2" "$branch_3"
gh stack submit --auto
gh stack view
```

`--auto` opens drafts. When the `origin` owner is `PedroNavHur`, add `--open`
so they open ready for review; for any other owner, keep them draft. Write every
PR body with the `pr` skill's template. Under Summary, add why the boundary is
atomic and the layer's parent and next layer; under Merge Danger, add notes on
migrations, rollout order, and generated output. Then write the size and gate lines into every body:

```bash
python3 "$SKILL_DIR/scripts/refresh_stack.py" --manifests "$plan/layers" --prefix "<source>-" \
  --base "$merge_base" --gates "$LOG_DIR" --update-prs
```

Verify each PR targets its direct parent and the bottom PR targets the base.
Close or supersede the original PR only when the user authorized it.

## 7. Fix rounds on an existing stack

1. Manifests: reuse the build's. For a stack built one layer at a time
   (`gh stack add`, hand-made branches), derive them from a branch of the stack:

   ```bash
   python3 "$SKILL_DIR/scripts/derive_manifests.py" --out "$plan/layers"
   ```

   It reads `gh stack view --json` (or `--base B --branches B1 B2 ...`) and
   writes `# branch:`, `# pr:` and `# base:` headers, so later commands need
   neither `--prefix` nor `--base`.
Review rounds **converge locally, push once**. A round costs review and fix
time only; the per-layer gates, the push, its pre-push gates and the PR-body
refresh run once, after the last round. Gating every layer and pushing after
each round costs 25 to 75 minutes on this host, even for a three-line fix.

2. Review the local layer heads (`git rev-parse` of each stack branch), not the
   pushed ones. Run `pedro-best-practices` audits local-only; a review loop
   posts its results after the push (`review-loop`'s finish step).
3. Make all fixes on one branch off the top (the fixed source), then carry them
   down into their layers from a worktree where no stack branch is checked out:

   ```bash
   bash "$SKILL_DIR/scripts/fix_layers.sh" --source "$fixed" --manifests "$plan/layers" --fix-msgs "$plan/fix-msgs"
   ```

   One commit per changed layer (message `fix-msgs/<layer>`, else
   `fix-msgs/default`), the layers above rebased along. A fix to a `~path`
   without a hook goes into the lowest layer it merges into cleanly. On a
   conflict it stops mid-rebase: resolve, `git rebase --continue`, rerun with
   `--from <next layer>`.
4. Between rounds, run the light check on the fixed source only (its tree
   equals the top layer): typecheck, lint and format on the round's changed
   files, and `vitest run --changed <previous fixed source>`, as one host-check
   job. The other layers wait for the publish step. A preview rebuild for the
   user also comes from the fixed source.
5. Publish when the user asks to push or a round comes back without accepted
   findings: run `layer_gates.sh` under `bg-job` (see `host-validation.md`),
   then `refresh_stack.py --gates "$LOG_DIR" --update-prs`, then
   `gh stack push` once.

For a single later fix, change and push only the layer that owns the code;
restack descendants only when their dependency changed or the user asks.

## 8. Restack onto a moved base

When the base moved ("we fell behind nightly"), restack every open layer at
once, chained stacks included, bottom to top:

```bash
python3 "$SKILL_DIR/scripts/restack.py" start --base origin/nightly "$branch_1" "$branch_2" "$branch_3" --push
```

It rebases each layer onto the new tip of the one below in a scratch worktree,
which also moves seams `gh stack rebase` skips, reports any layer whose own
diff changed, runs `layer_gates.sh` (add `--tests` for the top layer's tests), and pushes
every branch in one atomic leased push only when the gates pass. Exit 3 is a
conflict: resolve it in the printed worktree, `git rebase --continue`, then
`restack.py resume STATE_DIR --push`. Pass `--old-base` when a lower layer was
squash-merged into the base. Finish with `restack.py clean STATE_DIR`.

## 9. Report the result

Return the stack bottom to top with PR links, parents, commits, weighted size,
raw churn, test churn, excluded churn, validation status, the reason for any
layer under 12 KB and any `Size-Exception` trailer. State the disposition of the original PR, source branch,
temporary worktree and safety branch.
