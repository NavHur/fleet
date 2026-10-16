---
name: delegate
description: Delegate scoped implementation, codebase research, or review through T3 app-owned child tasks, then verify the result. Use for delegate requests or a requested worker model/provider.
---

# Delegate

Read `~/.config/t3-orchestration.md` before dispatch. Use its live
catalog, complete brief, workspace ownership, and task lifecycle contract.

## Worker model

Keep the user's explicit model and effort. Otherwise choose from these
workers, each on the subscription it runs under:

| Worker | Target | Use for |
| --- | --- | --- |
| Claude Haiku 5.5 | `claudeAgent`, `claude-haiku-5-5` | Scoped execution and research the parent is waiting on, or that relies on Claude Code tools, skills, and hooks. |
| Muse Spark 1.3 Contributor | `opencode`, `opencode-go/muse-spark-1.3-contributor` | Scoped execution and research that can run in the background; it is slower and close to free on the OpenCode Go plan. |
| GPT-6.1 Sol | `codex`, `gpt-6.1-sol`, medium | Reviews of work a Claude model wrote, so the reviewer brings a different model's blind spots. |
| Claude Opus 5.5 | `claudeAgent`, `claude-opus-5-5` | Work that must start with a large context (a long review packet, a big log) or needs more judgment than Haiku brings. |

The catalog from `orchestrator_capabilities` lists every OpenCode model,
including ones Pedro hid in T3's picker and ones billed per token. Take Claude
models from the Claude provider and GPT models from Codex, and use another
OpenCode model only when the user names it.

Haiku bills a whole request at 5× once its prompt passes 100K tokens, and its
sessions compact near 100K. Keep its brief lean: point to files and commands
rather than pasting their contents.

Keep ambiguous requirements and design decisions in the parent until the brief
has a clear finish line.

## Launch and verify

Launch directly with `delegate_task`, `role: "implementation"` (or research or
review), and `mode: "async"`. Store the taskId. Give workers disjoint ownership
in the bound checkout; serialize tasks that need the same files. Continue other
work, or end the turn while waiting for automatic completion.

After delivery, inspect the diff or research artifact against the brief.
Reword any worker commit carrying an AI co-author trailer or generated-by
line before it is pushed.
Verify the meaningful completion criterion through host-check when it matters.
Report actual changes, validation results, and unfinished work. For another
attempt, create a fresh delegated task carrying the full prior context.
Take over if a second scoped attempt still misses the finish line.
