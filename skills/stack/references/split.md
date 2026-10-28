# Split a branch into a stack

Split a large branch into dependency-ordered layers that each meet the size
contract in `SKILL.md`, build them in a scratch worktree, and gate every one.
The split is done when every layer passes its gates and measures within the
ceilings; then open the PRs per [`publish.md`](publish.md).

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
python3 "$SKILL_DIR/scripts/import_graph.py" "$merge_base" "$source_tip" --alias '@/=apps/web/src/' --generated 'src/generated/**'
```

`import_graph.py` (JS/TS) prints each changed file's size in bytes, counted as
`diff_budget.py` does (weighted is zero for tests and excluded files; pass it
the same `--generated` and `--test` globs as `diff_budget.py`), a renamed
file's old path, and its imports among the changed files; a file's layer sits
at or above the layers of what it imports.

## 3. Design atomic layers

Prefer cohesive vertical slices: preparation and moves, then contracts,
schemas and migrations, then domain behavior, then consumers, wiring and
cleanup. Within a layer, order its commits the same way, with refactors and
behavior changes in separate commits. Keep a migration with its
minimum compatible code unless rollout safety needs expand, migrate, contract.
Put generated output and lockfile updates in the layer that changes their
inputs. Avoid temporary breakage, forward references and layers that exist
only to meet a number. When an indivisible change exceeds a ceiling and no
module boundary helps, stop and report the blocker.

When the source's commits already follow that order and each passes
`diff_budget.py --per-commit "$merge_base" "$source_tip"`, cut the layers at
commit boundaries instead of rebuilding: see step 4.

Otherwise write the plan as a manifest directory outside the worktree: one
file per layer, named in stack order (`01-contract`, `02-domain`, ...), listing
its paths, deletions included. Split each layer into commits with
`# commit: SUBJECT` lines, each followed by the paths of that commit, within
the commit ceilings. A plain path is taken whole from the source. A file
that needs in-between versions (expand, then contract) is `~path` in each
earlier layer and plain in its final layer; each layer with a `~path` gets an
executable `hooks/<layer>` that writes those versions from `$SOURCE`.

```bash
python3 "$SKILL_DIR/scripts/check_manifests.py" "$merge_base" "$source_tip" "$plan/layers" --require-hooks
```

It must pass: no missing, duplicated, unchanged or misplaced path.

Show the user a plan table: order, branch, purpose, dependencies, commits,
paths, weighted size, raw churn, test churn, excluded churn, validation. Continue when
the user asked for execution; otherwise stop here.

## 4. Build in an isolated worktree

A stack cut at commit boundaries skips this step: put each layer's branch on
its last commit, derive the manifests, and verify as in step 5. The top layer
is the source, so the tree check holds by construction.

```bash
git branch "<source>-01-domain" <sha>   # one per layer, bottom to top
python3 "$SKILL_DIR/scripts/derive_manifests.py" --base "$base_branch" \
  --branches "<source>-01-domain" "<source>-02-ui" --out "$plan/layers"
```

1. Create the worktree at the merge-base and prepare it with the script
   ([`repos.md`](repos.md) lists what it installs and each repository's hook):

   ```bash
   wt=$(mktemp -d /tmp/<source>-stack-XXXX) && git worktree add -q --detach "$wt" "$merge_base"
   bash "$SKILL_DIR/scripts/setup_worktree.sh" "$wt"
   ```

2. Build every layer from the manifests; rerun after any manifest change:

   ```bash
   bash "$SKILL_DIR/scripts/build_layers.sh" --base "$merge_base" --source "$source_tip" \
     --manifests "$plan/layers" --prefix "<source>-" --msgs "$plan/msgs"
   ```

   It commits each layer, one commit per `# commit:` section, without hooks
   and fails unless the top tree equals the source, so the gates in step 5
   are mandatory.
3. Only when a layer needs hunks of one file that no hook can express, build
   it by hand with non-interactive patches and keep a hunk ledger mapping
   every source change to exactly one layer.

Keep the worktree and safety branch until the stack is published and verified.

## 5. Verify every layer

1. Run the gates on every layer, each against its parent. Each commit but a
   layer's tip also gets typecheck, lint and format on its own changed files
   (`commits=OK|FAIL`, or `none` for a one-commit layer). Tests run once, on
   the top layer against the base; lower layers report `tests=deferred`. Add
   `--tests-each` only to find the layer that broke a test failing at the top.

   ```bash
   bash "$SKILL_DIR/scripts/layer_gates.sh" --manifests "$plan/layers" --prefix "<source>-" \
     --base "$merge_base" --app <app dir>
   ```

   It queues itself once under `HOST_CHECK_CLASS=heavy host-check`, so call it
   unwrapped, through `bg-job start NAME -- bash .../layer_gates.sh ...`, since
   it outlasts ten minutes. It prints its log directory first; follow `LOG_DIR/progress`
   until a line starting `done`. Before each layer it reruns
   `setup_worktree.sh`, which reinstalls or regenerates only when their inputs
   changed. Its default commands and their overrides are in [`repos.md`](repos.md).
2. Measure every layer:

   ```bash
   python3 "$SKILL_DIR/scripts/refresh_stack.py" --manifests "$plan/layers" --prefix "<source>-" \
     --base "$merge_base" --gates "$LOG_DIR"
   ```

   Exit 2 means a layer or one of its commits exceeds a ceiling; revise it
   unless it is a retirement. A `small` layer passes but needs its reason.
3. Review the log and diffs bottom to top as a reviewer would.

If the stack rebases onto a newer base, tree equality no longer applies:
compare the source and reconstructed patches and record base-induced differences.
