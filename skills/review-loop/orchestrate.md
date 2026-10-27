# Review loop: orchestrator

You run a review loop that `review-loop`'s launcher handed you; your brief
holds the target, the checkout, and the settings. Run `code-review` and
`pedro-best-practices` in rounds, fix what they confirm, and re-review only the
**delta**, until a round comes back clean. The user is asked only for the
decisions that are theirs. Code stays local until the finish; the results go on
each PR as one generated comment.

`scripts/loop.py` owns everything reviewers and readers see: the reviewer
briefs, the findings check, the triage record, and the PR comment. Reviewers
follow `reviewer.md`. Set `SKILL_DIR` to this file's directory and `LOOP` to the
current pass's ledger directory. Read before starting:
`~/.config/t3-orchestration.md` (dispatch),
`~/.config/host-validation.md` (checks, `bg-job`), and for a stack
`split-stacked-prs` section 7, which owns carrying fixes and pushing.

## Passes

The loop runs twice, each run a **pass** with its own ledger, so the second
pass's reviewers read the code without the first pass's verdicts:

| Pass | `LOOP` | Reviewers |
| --- | --- | --- |
| 1 | `<slug>-p1` | Pass 1 reviewers (Terra) |
| 2 | `<slug>-p2` | Pass 2 reviewers (Opus) |

Each pass runs steps 1 to 5 with its own round cap; step 6 runs once, after
pass 2.

## The ledger

`LOOP` is `~/.cache/review-loop/<slug>-pN/`. Reviewers read its ledger and
outcomes every round, so a lost session resumes from the files, not from
memory:

- `ledger.md`: the target, the settings, standing decisions and user rulings,
  and one line per round.
- `outcomes.jsonl`: each finding's triage result, written only by
  `loop.py outcome`. A finding with an outcome is settled; reviewers never
  re-raise it.
- `rN/heads.tsv`: one line per PR, bottom to top,
  `PR<TAB>LAYER<TAB>BASE_SHA<TAB>HEAD_SHA` (layer = manifest name; for a single
  branch, one line). Use the PR number when the PR exists; the comment goes
  only to numbered PRs.
- `rN/reviewers.tsv` and `rN/<reviewer>.json`: written by `loop.py brief` and
  by the reviewers.
- `rN/context.md`: rewritten by every `loop.py brief`. It quotes
  `reviewer.md`, `rN/common.md`, and the ledger, then lists the round's
  reviewers and the settled findings: the one file each reviewer reads before
  its role's own, so the shared reading costs one turn.

Update the ledger at the end of every step that changes it. To resume, find the
pass and step the ledgers reached and continue from there.

## Steps

### 1. Pin the round

Record `rN/heads.tsv` from the local branches. A pass's round 1, or any PR new
since the last round, is reviewed whole. Later rounds compute the delta:

```bash
bash "$SKILL_DIR/scripts/delta.sh" --prev rN-1/heads.tsv --heads rN/heads.tsv \
  --out rN [--manifests "$plan/layers"] --repo "$checkout"
```

A PR with no delta is skipped this round. Done when every PR is marked whole,
delta, or skipped.

### 2. Dispatch reviewers

Write the round's facts to `rN/common.md`: the checkout path, the pinned
base and heads, the spec path, the repository's standards sources, the gates
already passed, operational constraints, and the principles from
`~/.config/principles.md` that match the diff. `reviewer.md` carries the rules,
methods, and output format; the packet holds only what is true of this run.

Pick the reviewers:

- **Whole** (a pass's round 1, or a PR new since the last round): one
  `standards` and one `spec` reviewer for the stack or branch, and one `audit`
  per PR.
- **Delta**: one `delta` reviewer for the PRs with a delta, and one
  `audit --delta` per PR whose delta has `audit=yes`.

Update the ledger for the round first, then generate every reviewer's task
before launching any, so the context file every brief rewrites carries the
same ledger and the full reviewer list:

```bash
python3 "$SKILL_DIR/scripts/loop.py" brief "$LOOP" N ROLE --model "MODEL EFFORT" \
  [--pr PR ...] [--delta] --checkout "$checkout"
```

Launch them all at once through `delegate_task`, `mode: "async"`, with the
pass's reviewer provider, model, and options, `clientRequestId`
`<slug>-pN-rN-<reviewer name>`, and the brief's output, verbatim, as the task.
Done when every reviewer is launched and its `taskId` is in `rN/tasks.tsv`.
End the turn; completions wake you.

### 3. Triage

Run `python3 "$SKILL_DIR/scripts/loop.py" check "$LOOP" N --checkout "$checkout"`.
It validates every reviewer's file and lists the round's findings. A reviewer
whose file fails goes back to its task with the check's output, through
`delegate_task` with a new `clientRequestId`.

Verify every finding against the code at its pinned SHA before it counts, and
classify it:

- **Fix**: a confirmed bug (any P1 or P2), or any confirmed P3 that needs no
  design or architecture decision. Its outcome is recorded once it is committed.
- **Decline**: unconfirmed, settled, pre-existing outside the change, or
  contradicted by a ruling: `loop.py outcome "$LOOP" ID declined --note REASON`.
- **Decision**: product behavior, copy, scope, or a design or architecture
  choice (including a P3 whose fix needs one):
  `loop.py outcome "$LOOP" ID decision --note RECOMMENDATION`. Keep going with
  the rest.

Done when `check` passes and every finding is a Fix or has an outcome.

### 4. Converge or fix

The round is **clean** when it has no Fix items. Clean, or at the pass's round
cap: go to step 5. Otherwise:

1. Brief workers (the worker setting, `delegate_task`) to edit the fixed
   source: the stack's source branch, or the branch itself. Give each disjoint
   file ownership, its findings, and the ledger; workers run no checks.
2. Read each worker's diff as a reviewer would, then run the light check from
   `split-stacked-prs` section 7 step 4 (for a single branch, the same check
   on that branch). Before committing, measure Pedro's two mechanical rules
   on the uncommitted fixes, in the same host-check job, with `PBP` the
   `pedro-best-practices` scripts directory and `$fixed` the fixed source's
   checkout (`HEAD` as the base measures only the uncommitted edits):

   ```bash
   python3 "$PBP/measure_complexity.py" HEAD --repo "$fixed" --over-only
   python3 "$PBP/long_comments.py" HEAD --repo "$fixed"
   ```

   An excess or long comment the fixes introduced or worsened goes back to the
   worker, so the next round's audit spends no turn on it. One already
   recorded as a decision stays with that decision.
3. Commit. For a stack, carry the fixes into their layers with
   `fix_layers.sh`. Record each fix with
   `loop.py outcome "$LOOP" ID fixed --commit SHA`, using the commit on the
   PR's own branch (for a stack, the layer commit). Then start the next round
   at step 1.

Post one short progress line to the user per round: pass and round number,
reviewers, confirmed findings, and fixes made.

### 5. Close the pass

Ask the pass's open decisions in one `AskUserQuestion`, recommendation first,
and record each ruling with `loop.py outcome "$LOOP" ID ruled --note RULING`.
A ruling that changes code reopens the pass at step 4 with one more delta
round, outside the cap. Done when every decision of the pass is ruled.

After pass 1, write pass 2's ledger, carrying over only pass 1's target,
settings, spec, standing decisions, and rulings, with an empty
`outcomes.jsonl`. Start pass 2 at step 1 with a whole review of pass 1's final
heads. After pass 2, go to step 6.

### 6. Finish

- **Push** (unless the brief said to stop locally): for a stack, follow
  `split-stacked-prs` section 7 step 5; for a branch, run its gates and push.
  On a coworker's branch, ask the user before pushing.
- **Comment**: post one comment per PR covering both passes:

  ```bash
  python3 "$SKILL_DIR/scripts/loop.py" publish "$PASS2" --earlier "$PASS1" --checkout "$checkout"
  ```

  It posts each PR's comment when GitHub's head is the head pass 2's last
  round reviewed, once per round, and says which PRs it skipped. A PR skipped
  for local fixes gets its comment by running `publish` again after the push.
  The comment covers the audits, so post no separate `pedro-best-practices`
  comment.
- **Report**: for each pass, whether it converged or hit the cap; what is
  still open; each PR's comment URL or why it was skipped; local versus pushed
  heads; and the gate results. `loop.py render "$PASS2" PR --earlier "$PASS1"
  --checkout "$checkout"` prints a PR's comment.

Merging and marking PRs ready stay with the user.
