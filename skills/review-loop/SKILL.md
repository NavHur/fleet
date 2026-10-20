---
name: review-loop
description: Review, fix, and re-review a PR or stack until it converges, with no user prompt between rounds.
disable-model-invocation: true
---

# Review loop

Run `code-review` and `pedro-best-practices` in rounds, fix what they confirm,
and re-review only the **delta**, until a round comes back clean. The user is
asked only for the decisions that are theirs. Code stays local until the push
step; the loop's results go on each PR as one generated comment.

`scripts/loop.py` owns everything reviewers and readers see: the reviewer
briefs, the findings check, the triage record, and the PR comment. Reviewers
follow `reviewer.md`. Set `SKILL_DIR` to this skill's absolute directory and
`LOOP` to the loop directory. Read before starting:
`~/.config/t3-orchestration.md` (dispatch),
`~/.config/host-validation.md` (checks, `bg-job`), and for a stack
`split-stacked-prs` section 7, which owns carrying fixes and pushing.

## Invocation

Take from the user's message, else from the ledger of an earlier run on the
same target, else ask once:

- **Target**: a PR, a stack (its top PR or branch), or a local branch with its base.
- **Reviewer** model and effort, and **worker** model and effort for fixes.
- **Push**: whether a converged loop pushes (default: push; the user can ask
  to stop locally and report). Invoking the loop is the ask to push, in work
  repos too.
- **Round cap**: default 5, the first full round included.

## The ledger

`LOOP` is `~/.cache/review-loop/<target-slug>/`. Reviewers read its ledger and
outcomes every round, so a lost session resumes from the files, not from
memory:

- `ledger.md`: the target, the invocation settings, standing decisions and
  user rulings, and one line per round.
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

Update the ledger at the end of every step that changes it.

## Steps

### 1. Pin the round

Record `rN/heads.tsv` from the local branches. Round 1, or any PR new since the
last round, is reviewed whole. Later rounds compute the delta:

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

- **Whole** (round 1, or a PR new since the last round): one `standards` and
  one `spec` reviewer for the stack or branch, and one `audit` per PR.
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
reviewer model, `clientRequestId` `<slug>-rN-<reviewer name>`, and the brief's
output, verbatim, as the task. Done when every reviewer is launched and its
`taskId` is in `rN/tasks.tsv`. End the turn; completions wake you.

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

The round is **clean** when it has no Fix items. Clean, or at the round cap:
go to step 5. Otherwise:

1. Brief workers (worker model, `delegate_task`) to edit the fixed source:
   the stack's source branch, or the branch itself. Give each disjoint file
   ownership, its findings, and the ledger; workers run no checks.
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

Post one short progress line to the user per round: round number, reviewers,
confirmed findings, and fixes made.

### 5. Finish

- **Open decisions**: ask them all in one `AskUserQuestion`, recommendation
  first. Record each ruling with `loop.py outcome "$LOOP" ID ruled --note RULING`.
  A ruling that changes code reopens the loop at step 4 with one more delta
  round, without counting against the cap.
- **Push** (unless the invocation said to stop locally): for a stack,
  follow `split-stacked-prs` section 7 step 5; for a branch, run its gates and
  push.
- **Comment**: run
  `python3 "$SKILL_DIR/scripts/loop.py" publish "$LOOP" --checkout "$checkout"`.
  It posts each PR's comment when GitHub's head is the head the last round
  reviewed, once per round, and says which PRs it skipped. A PR skipped for
  local fixes gets its comment by running `publish` again after the push. The
  comment covers the audits, so post no separate `pedro-best-practices`
  comment.
- **Report**: whether the loop converged or hit the cap, what is still open,
  each PR's comment URL or why it was skipped, local versus pushed heads, and
  the gate results. `loop.py render "$LOOP" PR --checkout "$checkout"` prints a
  PR's rounds and findings tables.

Merging and marking PRs ready stay with the user.
