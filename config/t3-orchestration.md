# T3 orchestrator v2

Read this reference before delegating agent work in T3 Code. Tool names may
have an MCP prefix. Use the live tool schema when it differs from an example.

## Review skills

Use `code-review` for Standards and Spec review, and `pedro-best-practices` for
Pedro's code audit (React, Svelte, Godot, Python, PHP). The user selects
reviewer models, effort, and agent roles at invocation time. These are the
retained general review workflows. `review-loop` runs both in rounds with fixes
between them, re-reviewing only the delta until a round is clean.

## Choose and launch

Call `orchestrator_capabilities` before selecting a provider, model, or model
option. It uses the composer's live catalog, including custom models. Check
`canRunChildTask`, constraints, and available options. Preserve a requested
model and effort; report an unavailable choice instead of substituting it.

In T3, use `delegate_task` for these personal workflows so children appear as
app-owned tasks. Native same-provider subagents remain appropriate outside
these workflows when they support the chosen model. Cross-provider work and
models absent from native tools use `delegate_task`.

Use `mode: "async"`, a meaningful title, the appropriate role, and a stable
`clientRequestId` for each logical launch. Retries of that launch reuse its ID.
Runtime, interaction mode, provider, model, and options inherit unless supplied.
Override only what the task requires, within the parent's permission ceiling.
The child gets only `task`, without parent conversation history.
If a workflow needs nested delegation, verify that the child exposes T3 tools
or the supported ACP fallback. A capable provider and a successful leaf task
do not prove nested tool access. If unavailable, return a dispatch packet for
the owning parent to launch; preserve the requested worker models and keep
semantic review in its assigned role. Leaf tasks execute their assigned work
without recursively invoking the same delegation workflow.

```json
{
  "title": "Investigate the persistence boundary",
  "role": "research",
  "mode": "async",
  "clientRequestId": "<unique-task-and-round-id>",
  "target": {
    "providerInstanceId": "<live-provider-id>",
    "model": "<live-model-id>",
    "options": {"<live-option-id>": "<supported-value>"}
  },
  "task": "<complete brief>"
}
```

Independent tasks can launch together. Retain each `taskId`, `childNodeId`,
`childThreadId`, and `childRunId`; these are different identifiers. There is no
need for a shell runner, detached process, or watcher agent to make a T3 card.
This also covers provider subprocesses hidden inside skill evaluation or
helper scripts: dispatch their model work as tasks instead of executing a
bundled CLI loop in T3. Third-party skill caches follow this global routing
contract without editing their upstream packages.

## Brief and ownership

Include the goal, completion criterion, repository path and pinned revisions
when relevant, permitted files, decisions already made, relevant instructions
or accessible context pointers, validation, and the expected report. State
read-only constraints explicitly for investigations and reviews. Model options
and `role` select behavior; they do not enforce filesystem restrictions.

Design briefs list candidates from more than one family, including one that
removes the requirement instead of serving it faster. A brief for a layer that
changes rendered UI makes a preview check part of its completion criterion
(`homes-preview deploy`, `receipt-hub-preview`); the layer is not done, and no
merge is offered, until someone has looked at the rendered page.

Workers share the checkout. Give each explicit file ownership and say that
other workers are present: preserve their edits and accommodate concurrent
changes. For validation, include `~/.config/host-validation.md` and
require `~/.local/bin/host-check`. Authorize commits, pushes, PRs, or
service operations only when those actions belong to the user's task. A commit
still requires format, lint, and typecheck on its changed files, and the top
head of a push the pre-commit skill with every prescribed check passing.

## Workspace binding

`delegate_task` inherits the caller's project, branch, and worktree. It has no
workspace override. A path in a prompt, `cd`, or `git worktree add` does not
change the child thread's T3 workspace binding.

For child implementation tasks, use the bound checkout with disjoint file
ownership, or serialize overlapping work. Independent design candidates can
return sketches as text or write separate artifact directories outside the
repository; keep source read-only. When independent worktrees are essential,
use a native tool that actually supports isolated child worktrees, or obtain
the user's request for separate top-level work. A native worktree's isolation
guard refuses any Bash it can't prove stays in the worktree: heredocs, loops,
`cd` chains, and `$(…)`. Brief those workers to write files with Write or Edit
and run one plain command per Bash call, and give them commands in that form.
For that requested top-level work, use `t3_thread_launch` with
`workspaceStrategy` before the agent starts. Omitting workspaceStrategy selects
the project root, not the caller's worktree. Retain the returned threadId;
inspect thread_list after a lost launch response before retrying because launch
has no idempotency key.

## Completion and follow-up

### Background jobs

A shell job's completion notice lives only as long as the session. When a turn
ends while a `bg-job` (see `host-validation.md`) is still running, first arm a
fallback wake: `schedule_task` bound to this thread, `{"type":"interval",
"everyMs":1800000}`, titled `bg-job NAME`, with the prompt: "Run `bg-job status
NAME`. Still running: end the turn. Finished or lost: delete this scheduled
task, then continue from the result." When the normal notice arrives first,
delete the scheduled task before continuing. Tell the user the job name so
`bg-job status` answers "what's the status?" without a turn.

### Child tasks

Async completion automatically wakes the parent. Continue independent work;
when only children remain, end the turn and resume on the notification. Do not
poll, spawn watchers, or schedule a recurring task to wait for children.
Use `task_status(taskId)` when a result is needed during an active turn or to
recover state. A terminal result read acknowledges automatic delivery.
`workState: "waiting_for_children"` means nested work remains. Accept completion
only from a terminal task result (`workState: "result_available"`), then inspect
the actual artifacts. `summary` is the stable result of the original task;
`hasPendingChildRuns` and `latestTerminal*` describe later child-thread turns
and do not reopen that task.

`mode: "wait"` is for short dependent work. Set a wait budget of at most 60
seconds. `waitTimedOut` only ends the parent's wait; the child keeps running.
Keep its taskId and await notification instead of duplicating the launch.

Each follow-up or delegated review round is a new `delegate_task` call with a
new clientRequestId and taskId. Include the original brief, previous findings,
responses, decisions, and unresolved objections. Fresh independent primary
reviewers receive scope and requirements without sibling findings; follow-up
reviewers need the full round history. Do not start a new review round by
sending to the old childThreadId. For an in-flight correction, thread_send with
`mode: "steer"` can target the active child; it does not create a new task.

Cancel active work with `task_cancel(taskId)` and a stable cancellation request
ID. Cancellation of a terminal task disposes its automatic delivery without
interrupting later child-thread runs. Use `t3_thread_interrupt` for such a later
run. Preserve successful sibling results and exact provider failures.

## Missing tools

Search the current tool catalog, then make one bounded direct call to the
known `mcp__t3_code__orchestrator_capabilities` name before concluding T3 is
absent. ACP can hide injected MCP tools. When `T3_ACP_MCP_NODE` exists, use the
supported transport:

```sh
ELECTRON_RUN_AS_NODE=1 "$T3_ACP_MCP_NODE" ${T3_ACP_MCP_ENTRYPOINT:+"$T3_ACP_MCP_ENTRYPOINT"} acp-mcp-call orchestrator_capabilities '{}'
```

The same transport accepts `delegate_task`, `task_status`, and `task_cancel`.
Pass arguments as properly shell-quoted JSON or through a helper that preserves
literal data. This is an MCP transport, not a provider CLI agent launch.
Outside T3, use available native subagent tools with complete briefs and their
actual lifecycle API. If the required model cannot be selected, report that
limitation. Do not quietly turn delegation into a provider CLI subprocess.
