# T3 orchestrator v2

T3's system prompt covers `delegate_task` versus thread launches, review
rounds, workspace binding, and the ACP fallback. This file adds Pedro's rules
for delegating in T3. Tool names may carry an MCP prefix; the live schema wins
over anything here.

## Review skills

`code-review` runs Standards and Spec review, `pedro-best-practices` runs
Pedro's code audit, and `review-loop` runs both in rounds with fixes between
them, re-reviewing only the delta until a round is clean. The user picks
reviewer models, effort, and roles at invocation.

## Launch

- Call `orchestrator_capabilities` before choosing a provider, model, or
  option, and check `canRunChildTask` and its constraints. Keep a requested
  model and effort; report an unavailable one instead of substituting it.
- Launch with `delegate_task` so children appear as app-owned tasks:
  `mode: "async"`, a meaningful title, the right `role`, and one stable
  `clientRequestId` per logical launch, reused by its retries. Override only
  what the task needs, within the parent's permission ceiling.
- Model work inside skills or helper scripts (a bundled provider CLI loop)
  dispatches as tasks too. A T3 card needs no shell runner, detached process,
  or watcher agent.
- Before nested delegation, verify that the child exposes T3 tools; a capable
  provider proves nothing. Without them, the child returns a dispatch packet,
  with the requested worker models, for its parent to launch. Leaf tasks do
  their assigned work without re-invoking the same delegation workflow.

## Brief and ownership

The child gets only `task`. Include the goal, completion criterion, repository
path and pinned revisions, permitted files, decisions already made, context
pointers, validation, and the expected report. State read-only constraints for
investigations and reviews: `role` and model options restrict no files.

Design briefs list candidates from more than one family, including one that
removes the requirement instead of serving it faster. A brief for a layer that
changes rendered UI makes a preview check part of its completion criterion
(`homes-preview deploy`, `receipt-hub-preview`); the layer is not done, and no
merge is offered, until someone has looked at the rendered page.

Workers share the checkout. Give each explicit file ownership and say that
other workers are present, so it preserves their edits. For validation,
include `~/.config/host-validation.md` and require `~/.local/bin/host-check`.
Authorize commits, pushes, PRs, or service operations only when they belong to
the user's task; a commit still needs format, lint, and typecheck on its
changed files, and a push's top head the pre-commit skill.

A native worktree subagent's isolation guard refuses Bash it cannot prove stays
in the worktree: heredocs, loops, `cd` chains, and `$(…)`. Brief those workers
to write files with Write or Edit and run one plain command per Bash call.

## Background jobs

A shell job's completion notice lives only as long as the session. When a turn
ends while a `bg-job` (see `host-validation.md`) is still running, first arm a
fallback wake: `schedule_task` bound to this thread, `{"type":"interval",
"everyMs":1800000}`, titled `bg-job NAME`, with the prompt: "Run `bg-job status
NAME`. Still running: end the turn. Finished or lost: delete this scheduled
task, then continue from the result." When the normal notice arrives first,
delete the scheduled task before continuing. Tell the user the job name so
`bg-job status` answers "what's the status?" without a turn.

## Child tasks

- Async completion wakes the parent. Continue independent work; when only
  children remain, end the turn. Use `task_status(taskId)` only when a result
  is needed mid-turn or to recover state.
- Accept completion only from `workState: "result_available"`, then inspect the
  artifacts. `waiting_for_children` means nested work remains. `summary` is the
  original task's result; `hasPendingChildRuns` and `latestTerminal*` describe
  later child-thread turns and do not reopen it.
- `mode: "wait"` is for short dependent work, with a wait budget of at most 60
  seconds. `waitTimedOut` ends only the wait: keep the taskId and await the
  notification.
- Fresh primary reviewers get scope and requirements without sibling findings;
  follow-up reviewers get the full round history. Correct an active child with
  `t3_thread_send` `mode: "steer"`.
- Cancel with `task_cancel(taskId)` and a stable request ID;
  `t3_thread_interrupt` stops a later child-thread run. Keep successful sibling
  results and exact provider failures.

Outside T3, use native subagents with complete briefs. When the required model
cannot be selected there, report it; delegation stays out of provider CLI
subprocesses.
