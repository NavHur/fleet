# Review loop: orchestrator

Your brief from `review-loop`'s launcher holds the target, the checkout, and
the settings. Run two **passes**, each a loop with its own ledger: review in
rounds, fix what is confirmed, and re-review only the **delta** until a round
is **clean**. Pass 2's reviewers read the code without pass 1's verdicts. Code
stays local until the finish; ask the user only for the decisions that are
theirs.

`SKILL_DIR` is this file's directory, `loop.py` is
`python3 "$SKILL_DIR/scripts/loop.py"` (briefs, findings checks, outcomes, the
PR comment; `--help` gives the ledger's file formats), and reviewers follow
`reviewer.md`. Read first: `~/.config/t3-orchestration.md`,
`~/.config/host-validation.md`, and for a stack `split-stacked-prs` section 7,
which owns carrying fixes and pushing.

## The ledger

`LOOP` is the current pass's ledger, `~/.cache/review-loop/<slug>-pN/`
(`PASS1`, `PASS2`). A lost session resumes from the pass and step the ledgers
reached:

- `ledger.md`: the target, the settings, standing decisions and rulings, and
  one line per round. Update it at the end of every step that changes it.
- `outcomes.jsonl`: written only by `loop.py outcome`. A finding with an
  outcome is **settled**.
- `rN/heads.tsv`: `PR<TAB>LAYER<TAB>FORK<TAB>HEAD` per PR, bottom to top,
  from `stack_layers.py heads` (step 1). FORK is the layer's fork point, so
  `git diff FORK HEAD` is its own change. PR is the number, or the branch
  while no PR is open; only numbered PRs get a comment.

## Steps

Each pass runs steps 1 to 5 under its own round cap; step 6 runs once, after
pass 2.

### 1. Pin the round

Write `rN/heads.tsv` from the local branches, for a split-stacked-prs stack or
a branch list (one branch for a single PR):

```bash
stack_layers="$SKILL_DIR/../split-stacked-prs/scripts/stack_layers.py"
python3 "$stack_layers" heads --manifests "$plan/layers" --prefix "<source>-" >rN/heads.tsv
python3 "$stack_layers" heads --base "$base" "$branch_1" "$branch_2" >rN/heads.tsv
```

A pass's round 1, or a PR new since the last round, is reviewed **whole**;
otherwise compute the delta:

```bash
python3 "$SKILL_DIR/scripts/delta.py" --prev rN-1/heads.tsv --heads rN/heads.tsv \
  --out rN [--manifests "$plan/layers"] --repo "$checkout"
```

Done when every PR is whole, delta, or skipped (no delta).

### 2. Dispatch reviewers

Write `rN/common.md` with only what is true of this run: the checkout, the
pinned base and heads, the spec path, the standards sources, the gates already
passed, operational constraints, and the principles from
`~/.config/principles.md` that match the diff.

- **Whole**: one `standards` and one `spec` reviewer for the stack or branch,
  and one `audit` per PR.
- **Delta**: one `delta` reviewer for the PRs with a delta, and one
  `audit --delta` per PR whose delta has `audit=yes`.

Update the ledger, then brief every reviewer before launching any, since each
brief rewrites the round's shared context file:

```bash
loop.py brief "$LOOP" N ROLE --model "MODEL EFFORT" [--pr PR ...] [--delta] --checkout "$checkout"
```

Launch them all at once: `delegate_task`, `mode: "async"`, the pass's reviewer
setting, `clientRequestId` `<slug>-pN-rN-<reviewer name>`, and the brief's
output verbatim as the task. Done when every `taskId` is in `rN/tasks.tsv`.
End the turn; completions wake you.

### 3. Triage

`loop.py check "$LOOP" N --checkout "$checkout"` validates every reviewer's
file and lists the findings. A failing file goes back to its reviewer with the
output, as a new `delegate_task` with a new `clientRequestId`.

Verify every finding against the code at its pinned SHA, then classify it:

- **Fix**: a confirmed P1 or P2, or a confirmed P3 that needs no design
  decision. Its outcome is recorded at commit.
- **Decline**: unconfirmed, settled, pre-existing outside the change, or
  contradicted by a ruling: `loop.py outcome "$LOOP" ID declined --note REASON`.
- **Decision**: product behavior, copy, scope, or a design or architecture
  choice: `loop.py outcome "$LOOP" ID decision --note RECOMMENDATION`. Keep
  going with the rest.

Done when `check` passes and every finding is a Fix or has an outcome.

### 4. Converge or fix

Clean (no Fix items) or at the round cap: go to step 5. Otherwise:

1. Brief workers (the worker setting, `delegate_task`) to edit the fixed
   source: the stack's source branch, or the branch itself. Each gets disjoint
   files, its findings, and the ledger, and runs no checks.
2. Read each worker's diff as a reviewer would. Run the light check from
   `split-stacked-prs` section 7 step 4 (on a branch, the same check), and in
   the same host-check job measure the uncommitted fixes, with `PBP` the
   `pedro-best-practices` scripts directory and `$fixed` the fixed source's
   checkout:

   ```bash
   python3 "$PBP/measure_complexity.py" HEAD --repo "$fixed" --over-only
   python3 "$PBP/long_comments.py" HEAD --repo "$fixed"
   ```

   An excess or long comment the fixes introduced or worsened goes back to the
   worker, unless it is already a recorded decision.
3. Commit; for a stack, carry the fixes into their layers with
   `fix_layers.sh`. Record each with
   `loop.py outcome "$LOOP" ID fixed --commit SHA`, the commit on the PR's own
   branch (for a stack, the layer commit). Start the next round at step 1.

Post the user one line per round: pass, round, reviewers, confirmed findings,
fixes.

### 5. Close the pass

Ask the pass's decisions in one `AskUserQuestion`, recommendation first, and
record each answer with `loop.py outcome "$LOOP" ID ruled --note RULING`. A
ruling that changes code reopens step 4 for one more delta round, outside the
cap. Done when every decision is ruled.

After pass 1, write pass 2's ledger with only pass 1's target, settings, spec,
standing decisions, and rulings, and an empty `outcomes.jsonl`; pass 2's
round 1 reviews pass 1's final heads whole.

### 6. Finish

- **Push**, unless the brief says to stop locally: for a stack,
  `split-stacked-prs` section 7 step 5; for a branch, its gates, then push. On
  a coworker's branch, ask the user first.
- **Comment**: `loop.py publish "$PASS2" --earlier "$PASS1" --checkout "$checkout"`
  posts one comment per PR covering both passes and the audits, so post no
  separate `pedro-best-practices` comment. It skips a PR whose GitHub head is
  not pass 2's last reviewed head; run it again after that PR's push.
- **Close out**, only when both passes converged (neither hit its cap), the
  PRs are pushed, and every PR's comment is posted at its reviewed head. Touch
  only PRs Pedro opened (author `PedroNavHur` or `PedroNavHurDCA`). The brief's
  `Finish` line is his approval, given in the launching session:
  - `merge`: read each PR head's checks over REST
    (`repos/<owner>/<repo>/commits/<head>/check-runs`). While any is running,
    call `watch_pull_request` on the top PR and end the turn; its wake resumes
    here. Once all pass, merge a PR with
    `gh pr merge N --merge --match-head-commit <head>`, a stack with
    `gh stack merge --yes --merge` on its top PR, then `unwatch_pull_request`.
    A failed check or a refused merge goes in the report, unmerged.
  - `ready`: `gh pr ready N` for each draft PR, bottom to top.
  - `none`: leave the PRs as they are.
- **Report**: per pass, converged or capped; what is still open; each PR's
  comment URL or why it was skipped; local versus pushed heads; the gate
  results; each PR merged, marked ready, or why it was left. `loop.py render "$PASS2" PR --earlier "$PASS1" --checkout "$checkout"`
  prints one PR's comment.
