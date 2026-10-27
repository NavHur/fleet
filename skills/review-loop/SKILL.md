---
name: review-loop
description: Review a PR or stack in two passes, Terra then Opus, from a fresh orchestrator thread, fixing between rounds until each pass converges.
disable-model-invocation: true
---

# Review loop

A review loop reviews a PR or stack in rounds, fixes what the reviewers
confirm, and re-reviews only the **delta** until a round comes back clean. It
runs in two **passes**, each a loop with its own ledger: Terra reviewers first,
which catch most bugs at a fraction of the quota, then Opus reviewers, who read
the converged code fresh. One comment per PR reports both passes.

This session is the **launcher**. It settles the invocation and starts a new T3
thread, the **orchestrator**, which runs both passes from `orchestrate.md` in
this skill's directory. Every reviewer completion wakes the orchestrator, and a
fresh thread keeps each wake's context to the loop's own.

## Invocation

Take each setting from the user's message, else from the ledgers of an earlier
run on the same target, else its default:

| Setting | Default |
| --- | --- |
| Target | Ask once: a PR, a stack (its top PR or branch), or a local branch with its base |
| Orchestrator | `claudeAgent` `claude-opus-5-5`, `effort` medium |
| Pass 1 reviewers | `codex` `gpt-6.1-terra`, `reasoningEffort` medium (Terra's own default is low, so set it) |
| Pass 2 reviewers | `claudeAgent` `claude-opus-5-5`, `effort` medium |
| Workers, both passes | `claudeAgent` `claude-sonnet-5-5`, `effort` medium |
| Round cap | 5 per pass, the first full round included |
| Push | Yes, once both passes converge. Pedro's own branches push without asking, in work repos too; a coworker's branch waits for his say |

Call `orchestrator_capabilities` once and confirm every model and option is
offered. Launch only with the requested settings; report an unavailable one to
the user.

## Launch

1. **Pin the target**: its PRs bottom to top, branches, base, and the
   **checkout**, the worktree where the branch (for a stack, the top branch)
   is checked out. Pick a slug for the target; the ledgers are
   `~/.cache/review-loop/<slug>-p1/` and `~/.cache/review-loop/<slug>-p2/`,
   and the orchestrator resumes either one that already exists. Done when the
   checkout holds the branch with every change committed (reviewers read
   commits); uncommitted work goes to the user to commit or set aside.
2. **Launch the orchestrator** with `t3_thread_launch`:
   - `title`: `Review loop: <repo> #<PR>`
   - `modelSelection`: the orchestrator setting, as
     `{"provider": "claudeAgent", "model": "claude-opus-5-5", "options": [{"id": "effort", "value": "medium"}]}`
   - `workspaceStrategy`: `{"type": "existing_worktree", "worktreePath": "<checkout>"}`,
     so the thread works in the PR's checkout rather than the project root
   - `message`: the brief below, filled in

   Done when the call returns the thread's link. After an error or a lost
   reply, check `t3_thread_list` before launching again.
3. **Hand off**: give the user the thread's link and the settings, and say the
   loop's decisions will be asked in that thread. The checkout belongs to the
   orchestrator until it reports.

Without T3 thread tools, follow `orchestrate.md` in this session instead.

### Orchestrator brief

The new thread knows only this message. Carry over what this session settled
that reviewers need: the spec or issue, and decisions already made.

```text
You are the orchestrator of a review loop. Read <SKILL_DIR>/orchestrate.md in full, then follow it from the top.

Target: <repo>, <PR, or stack PRs bottom to top>, branches <...>, base <...>
Checkout: <path>
Ledgers: pass 1 <~/.cache/review-loop/SLUG-p1>, pass 2 <~/.cache/review-loop/SLUG-p2>; resume either if it exists
Pass 1 reviewers: <provider model option>
Pass 2 reviewers: <provider model option>
Workers: <provider model option>
Round cap: <N> per pass. Push: <yes | stop locally and report>
Spec: <path, issue, or "the PR bodies">
Settled in the launching session: <decisions and constraints, or "none">
```
