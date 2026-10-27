---
name: review-loop
description: Review a PR or stack in two passes, Terra then Opus, from a fresh orchestrator thread, fixing between rounds until each pass converges.
disable-model-invocation: true
---

# Review loop

A review loop reviews a PR or stack in rounds, fixes what reviewers confirm,
and re-reviews the **delta** until a round is clean. It runs two **passes**,
each with its own ledger: Terra reviewers catch most bugs cheaply, then Opus
reviewers read the converged code fresh. One comment per PR reports both.

This session is the **launcher**: it settles the settings and starts the
**orchestrator**, a new T3 thread that follows `orchestrate.md` in this
directory, so each reviewer wake reloads only the loop's context. Without T3
thread tools, follow `orchestrate.md` here instead.

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

Call `orchestrator_capabilities` once; launch only with offered settings and
report any that is not.

## Launch

1. **Pin the target**: its PRs bottom to top, branches, base, and the
   **checkout**, the worktree holding the branch (a stack's top branch). Done
   when every change there is committed, since reviewers read commits;
   uncommitted work goes back to the user. Pick a slug.
2. **Launch** with `t3_thread_launch`:
   - `title`: `Review loop: <repo> #<PR>`
   - `modelSelection`, the orchestrator setting: `{"provider": "claudeAgent", "model": "claude-opus-5-5", "options": [{"id": "effort", "value": "medium"}]}`
   - `workspaceStrategy`: `{"type": "existing_worktree", "worktreePath": "<checkout>"}`
   - `message`: the brief below

   Done when it returns the thread's link. After an error or a lost reply,
   check `t3_thread_list` before launching again.
3. **Hand off**: give the user the link and the settings. Decisions are asked
   in that thread, and the checkout is the orchestrator's until it reports.

### Brief

The thread knows only this message, so carry over the spec and what this
session settled.

```text
You are the orchestrator of a review loop. Read <SKILL_DIR>/orchestrate.md in full, then follow it from the top.

Target: <repo>, <PR, or stack PRs bottom to top>, branches <...>, base <...>
Checkout: <path>
Ledgers: ~/.cache/review-loop/<slug>-p1 and -p2; resume either if it exists
Pass 1 reviewers: <provider model option>
Pass 2 reviewers: <provider model option>
Workers: <provider model option>
Round cap: <N> per pass. Push: <yes | stop locally and report>
Spec: <path, issue, or "the PR bodies">
Settled in the launching session: <decisions and constraints, or "none">
```
