---
name: split-stacked-prs
description: Native GitHub stacked PRs within Pedro's weighted and raw churn ceilings. Use to split a large branch into dependency-ordered layers, or to carry review fixes through, gate, or re-measure an existing stack. Not for code review.
---

# Split Stacked PRs

For agent dispatch in T3 Code, read `~/.config/t3-orchestration.md`.
Every check runs through the shared queue in `~/.config/host-validation.md`;
include that path in any handoff that validates.

Set `SKILL_DIR` to this skill's absolute directory. The scripts are in
`$SKILL_DIR/scripts`; each prints its usage with `--help`. The manifest format
and the hook contract are in the header of `scripts/lib.sh`.

## Enforce the contract

Read `references/size-policy.md` for the canonical personal policy: test-file
classification, generated-data exemptions, retirement exceptions, the
five-layer limit, whole-file splits.
Apply it only to Pedro's pull requests.

- Measure each layer against its direct parent: weighted size at most 1000,
  raw churn at most 2000, unless the retirement exception applies. Target
  weighted size below 500; explain any layer from 500 through 1000.
- Keep each behavior change with its tests. Fixtures, helpers, setup and test
  infrastructure count toward both ceilings.
- Every layer builds and passes its checks alone, is independently
  understandable and revertible, and the top reproduces the source exactly.

`scripts/diff_budget.py BASE HEAD` measures one pair (exit 2: a ceiling is
exceeded). It recognizes JS/TS `*.test.*`/`*.spec.*`, Python and Go test names,
lockfiles and `linguist-generated` files; add `--test GLOB` for other verified
test files and `--generated GLOB` for verified generated paths, including the
data exemptions in the policy's command. Both paths of a rename must qualify.

## 1. Establish the source and recovery points

1. Resolve the repository root and read the applicable `AGENTS.md` files and contribution guidance.
2. Inspect `git status`, branch, remotes, commits and any current PR. Refuse to mix unrelated dirty changes into the split; ask the user to commit or stash them.
3. Resolve the base: explicit user base, then the existing PR base, then the remote default branch. Record base branch, merge-base SHA, source branch, source tip SHA and PR URL.
4. Create a local safety branch at the source tip, such as `backup/<source>-before-stack-<timestamp>`.
5. Leave the source branch and original PR unchanged until the new stack is validated.

## 2. Inventory the complete change

From the commits and the full merge-base-to-source diff, identify reusable
commits, mixed commits, dependency edges (contracts, migrations, code, wiring,
tests, docs, generated output), renames, modes, binaries, deletions, and
generated files with the evidence for each.

```bash
python3 "$SKILL_DIR/scripts/diff_budget.py" "$merge_base" "$source_tip" --generated 'src/generated/**'
python3 "$SKILL_DIR/scripts/import_graph.py" "$merge_base" "$source_tip" --alias '@/=apps/web/src/'
```

`import_graph.py` (JS/TS) prints each changed file's size and its imports among
the changed files; a file's layer sits at or above the layers of what it imports.

## 3. Design atomic layers

Prefer cohesive vertical slices: preparation and moves, then contracts,
schemas and migrations, then domain behavior, then consumers, wiring and
cleanup. Separate refactors from behavior changes. Keep a migration with its
minimum compatible code unless rollout safety needs expand, migrate, contract.
Put generated output and lockfile updates in the layer that changes their
inputs. Avoid temporary breakage, forward references and layers that exist
only to meet a number. When an indivisible change exceeds a ceiling and no
module boundary helps, stop and report the blocker.

Write the plan as a manifest directory outside the worktree: one file per
layer, named in stack order (`01-contract`, `02-domain`, ...), listing its
paths, deletions included. A plain path is taken whole from the source. A file
that needs in-between versions (expand, then contract) is `~path` in each
earlier layer and plain in its final layer; each layer with a `~path` gets an
executable `hooks/<layer>` that writes those versions from `$SOURCE`.

```bash
python3 "$SKILL_DIR/scripts/check_manifests.py" "$merge_base" "$source_tip" "$plan/layers" --require-hooks
```

It must pass: no missing, duplicated, unchanged or misplaced path.

Show the user a plan table: order, branch, purpose, dependencies, paths,
weighted size, raw churn, test churn, excluded churn, validation. Continue when
the user asked for execution; otherwise stop here.

## 4. Build in an isolated worktree

1. Create the worktree at the merge-base and prepare it with the script
   (a symlinked `node_modules` breaks pnpm):

   ```bash
   wt=$(mktemp -d /tmp/<source>-stack-XXXX) && git worktree add -q --detach "$wt" "$merge_base"
   bash "$SKILL_DIR/scripts/setup_worktree.sh" "$wt"
   ```

   It runs `pnpm install --frozen-lockfile`, `prisma generate` when a schema
   exists, and the repository hook (`njhomes-sync-env`, `receipt-hub-test-db`).
2. Build every layer from the manifests; rerun after any manifest change:

   ```bash
   bash "$SKILL_DIR/scripts/build_layers.sh" --base "$merge_base" --source "$source_tip" \
     --manifests "$plan/layers" --prefix "<source>-" --msgs "$plan/msgs"
   ```

   It commits each layer without hooks and fails unless the top tree equals
   the source, so the gates in step 5 are mandatory.
3. Only when a layer needs hunks of one file that no hook can express, build
   it by hand with non-interactive patches and keep a hunk ledger mapping
   every source change to exactly one layer.

Keep the worktree and safety branch until the stack is published and verified.

## 5. Verify every layer

1. Run the gates on every layer, each against its parent:

   ```bash
   bash "$SKILL_DIR/scripts/layer_gates.sh" --manifests "$plan/layers" --prefix "<source>-" \
     --base "$merge_base" --app apps/web
   ```

   It queues itself once under `HOST_CHECK_CLASS=heavy host-check`, so call it
   unwrapped, through `bg-job start NAME -- bash .../layer_gates.sh ...`, since
   it outlasts ten minutes. It prints its log directory first; follow `LOG_DIR/progress`
   until a line starting `done`. Before each layer it reruns
   `setup_worktree.sh`, which reinstalls or regenerates the Prisma client only
   when their inputs changed. Override a step with `TYPECHECK_CMD`, `LINT_CMD`,
   `FORMAT_CMD` or `TEST_CMD`.
2. Measure every layer:

   ```bash
   python3 "$SKILL_DIR/scripts/refresh_stack.py" --manifests "$plan/layers" --prefix "<source>-" \
     --base "$merge_base" --gates "$LOG_DIR"
   ```

   Exit 2 means a layer exceeds a ceiling; revise it unless it is a retirement.
3. Review the log and diffs bottom to top as a reviewer would.

If the stack rebases onto a newer base, tree equality no longer applies:
compare the source and reconstructed patches and record base-induced differences.

## 6. Publish with native GitHub stacks

```bash
gh stack init --base "$base_branch" "$branch_1" "$branch_2" "$branch_3"
gh stack submit --auto
gh stack view
```

`--auto` opens drafts; keep them draft. Give every PR body a one-sentence
purpose and why the boundary is atomic, its parent and next layer, a change
summary, gate results, and reviewer notes on migrations, rollout order,
generated output or risk. Then write the size and gate lines into every body:

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
   posts its results after the push (`review-loop` step 5).
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

## 8. Report the result

Return the stack bottom to top with PR links, parents, weighted size, raw
churn, test churn, excluded churn, validation status and any justification for
500 through 1000. State the disposition of the original PR, source branch,
temporary worktree and safety branch.
