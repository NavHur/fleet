---
name: review-loop
description: Review a PR or stack in rounds, Terra then Opus, fixing until each pass is clean; then merge it or mark it ready.
disable-model-invocation: true
---

# Review loop

A review loop reviews a PR or stack in rounds, fixes what reviewers confirm,
and re-reviews the delta until a round is clean: one pass with Terra
reviewers, which catch most bugs cheaply, then one with Opus reviewers reading
the result fresh. Then it pushes, posts one comment per PR, and merges the PRs
or marks them ready.

This session is the **launcher**: it settles the settings, starts the
**orchestrator**, a T3 child task per pass that follows `orchestrate.md` in
this directory so each reviewer wake reloads only that pass's context, relays
its questions, and merges. Without `delegate_task`, follow `orchestrate.md` here
instead.

## Settings

Each comes from the user's message, else an earlier run's ledgers on the same
target, else:

| Setting | Default |
| --- | --- |
| Target | Ask once: a PR, a stack (its top PR or branch), or a local branch and its base |
| Orchestrator | `claudeAgent` `claude-opus-5-5`, `effort` medium |
| Pass 1 reviewers | `codex` `gpt-6.1-terra`, `reasoningEffort` medium (set it: Terra defaults to low) |
| Pass 2 reviewers | `claudeAgent` `claude-opus-5-5`, `effort` medium |
| Workers | `claudeAgent` `claude-sonnet-5-5`, `effort` medium |
| Round cap | 5 per pass, the first round included |
| Push | Yes, after pass 2 |
| Finish | `merge` when the `origin` owner is `PedroNavHur`; `ready` (mark ready for review) for any other owner; `none` when Push stops locally |

Call `orchestrator_capabilities` once; launch only with offered settings and
report any that is not.

## Launch

1. **Pin the target**: its PRs bottom to top, branches, base, `origin`
   owner, and the **checkout**, the worktree holding the branch (a stack's top
   branch). Done when every change there is committed, since reviewers read
   commits; uncommitted work goes back to the user. Pick a slug.
2. **Launch** a pass with `delegate_task`, pass 1 first:
   - `title`: `Review loop: <repo> #<PR>, pass <N>`
   - `mode`: `async`, `role`: `review`, `clientRequestId`:
     `review-loop-<slug>-p<N>`, reused by any retry of this launch
   - `target`, the orchestrator setting: `{"providerInstanceId": "claudeAgent", "model": "claude-opus-5-5", "options": {"effort": "medium"}}`
   - `task`: the brief below, with `Pass: <N>`

   The child shares this session's workspace; the brief's `Checkout` line
   points it at the target. Done when it returns the task's link.
3. **Hand off**: give the user the link and the settings, Finish first,
   since it merges or marks ready without another prompt. The checkout is the
   orchestrators' until pass 2 reports. End the turn: their questions and
   reports wake this session.
4. **Relay questions**: on a wake saying the task is blocked on a question,
   read it with `t3_pending_request` `read`, put it to the user unchanged in
   one `AskUserQuestion`, options in their order, and pass the answer back with
   `respond`. Every question goes to the user, however settled it looks here.
   "Already answered" means the user answered in the child thread.
5. **Pass 2** on pass 1's report: relay it to the user in a line, launch
   pass 2 as in step 2, and end the turn.
6. **Finish** on pass 2's report: relay it to the user. When it hands the merge
   back (Finish `merge`), **merge**: read each listed PR head's checks over
   REST (`repos/<owner>/<repo>/commits/<head>/check-runs`). While any is running,
   call `watch_pull_request` on the top PR and end the turn; its wake resumes
   here. Once all pass, merge a PR with
   `gh pr merge N --merge --match-head-commit <head>`, a stack with
   `gh stack merge --yes --merge` on its top PR, then unwatch the PR. Done
   when each PR is merged, or its failed check or refused merge is reported
   to the user.

### Brief

The task knows only this message, so carry over the spec and what this
session settled.

```text
You are the orchestrator of a review loop. Read <SKILL_DIR>/orchestrate.md in full, then follow it from the top. This task authorizes you to start reviewer and worker tasks with delegate_task.

Target: <repo>, <PR, or stack PRs bottom to top>, branches <...>, base <...>
Checkout: <path>
Pass: <1 | 2>
Ledgers: ~/.cache/review-loop/<slug>-p1 and -p2; resume either if it exists
Pass 1 reviewers: <provider model option>
Pass 2 reviewers: <provider model option>
Workers: <provider model option>
Round cap: <N> per pass. Push: <yes | stop locally and report>. Finish: <merge | ready | none>
Spec: <path, issue, or "the PR bodies">
Settled in the launching session: <decisions and constraints, or "none">
```
