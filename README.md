# fleet

Agent skills shared by my machines: the MacBook, `workbox`, `devbox`, and `homebox`.

## Layout

- `skills/<name>/`: my own skills. Each one has a single `SKILL.md`, which Claude Code, Codex, OpenCode, and Cursor all read. Codex-only metadata lives in `agents/openai.yaml` next to it.
- `third-party.json`: skills from other repositories, grouped by source. Their files stay out of this repo. Each machine installs them with `npx skills add <source> -g -s <skill>`.
- `claude-plugins.json`: Claude Code plugins (with their marketplaces) that `bin/sync` installs, enables, and updates on every machine. impeccable lives here rather than in `third-party.json`: design work happens in Claude Code, and the plugin brings its subagents and design-check hook.

## Principles

The `principle-*` skills come from [pstack](https://github.com/backnotprop/pstack) (a mirror of `cursor/plugins/pstack`), listed in `third-party.json`. Upstream marks them `disable-model-invocation: true`, so agents don't load them on their own. After each install, `bin/sync`:

- gives each such skill an `agents/openai.yaml` with `allow_implicit_invocation: false`, because Codex ignores the frontmatter key;
- writes `~/.config/principles.md`, one line per principle with when it applies and its path;
- writes a marked block into `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, and `~/.config/opencode/AGENTS.md`: the shared instructions in `config/instructions.md` plus a pointer to that index. Edit the shared rules there, never inside the block; a host's own instructions go outside it.

`skills/principle-reach-for-what-exists` is fleet's own principle, written in the same format: the dependency ladder and `ceiling:` comments for deliberate shortcuts.

Skills in this repo cite principles by path (`~/.agents/skills/principle-x/SKILL.md`), not by name, because a principle hidden from the model cannot be found by name.

## Sync a machine

```sh
git clone https://github.com/PedroNavHur/fleet   # once: ~/dev on the Mac, ~/code on workbox, ~/src on devbox and homebox
fleet/bin/sync            # show the plan
fleet/bin/sync --apply    # pull, link own skills, install and update third-party skills
```

`bin/sync` links each skill in `skills/` into `~/.agents/skills` (read by Codex, Cursor, and OpenCode) and `~/.claude/skills` (read by Claude Code). Any other entry in those folders, or a copy in `~/.codex/skills`, `~/.cursor/skills`, or `~/.config/opencode/skills`, is moved to `~/.skills-backups/fleet-<timestamp>/`. To add or change a skill, edit it here, push, and run `bin/sync --apply` on each machine.

## Shared host files

`bin/sync` also installs the machine-level tooling that skills rely on:

| On each machine | From this repo |
| --- | --- |
| `~/.local/bin/host-check` | `bin/host-check`: the shared validation queue |
| `~/.local/bin/bg-job` | `bin/bg-job`: long jobs that outlive the agent session |
| `~/.local/bin/idle-compact` | `bin/idle-compact`: idle Claude threads in T3 to compact before their prompt cache expires |
| `~/.local/lib/host-check/` | `lib/host-check/`: `guard.py` (command guard and job classes), tests, OpenCode plugin |
| `~/.config/t3-orchestration.md` | `config/t3-orchestration.md` |
| `~/.config/host-validation.md` | generated from `config/host-validation.md` plus `hosts/<machine>/host-validation.md` |
| `~/.config/fleet/host.json` | `hosts/<machine>/host.json`: queue limits and CPU policy |
| `~/.config/systemd/user/builds.slice` | `hosts/<machine>/builds.slice` (Linux) |

The full list of links is in `links`. `bin/sync` also adds the guard to Claude Code, Codex, Cursor, and OpenCode as a pre-command hook. On Linux, host-check runs jobs in `builds.slice`; on macOS it runs them under `taskpolicy -c utility`, which yields the CPU to interactive work and does not limit memory.

Run the tests on any machine with:

```sh
cd lib/host-check && python3 -m unittest test_guard test_scheduler test_bg_job
cd bin && python3 -m unittest test_idle_compact
cd lib/fleet && python3 -m unittest test_opencode_servers
cd skills/pedro-best-practices/tests && python3 -m unittest test_complexity test_long_comments
cd skills/review-loop/scripts && python3 -m unittest test_loop
```

A skill with a `package.json` gets its dependencies from `bin/sync` (`pnpm install --frozen-lockfile`); `pedro-best-practices` uses that for its own oxlint. Its GDScript and PHP tests skip, with a reason, on machines without gdtoolkit or `php`; set `PBP_GDTOOLKIT_PYTHON` to a Python that has gdtoolkit to run them. Its godot-guard tests skip without godot-guard 0.2 or newer; set `PBP_GODOT_GUARD` to one, such as a godot-guard checkout's `.venv/bin/godot-guard`.

## Idle compaction

Claude Code caches a conversation for an hour after each request. Compacting a large Claude thread after that hour writes its whole context to the cache again, so each machine runs a janitor: a Claude Haiku 5.5 thread in T3 Code that sends `/compact` to the threads `idle-compact due` lists, a few minutes before their cache expires. The rules for which threads qualify are in `bin/idle-compact`; the minimum is 100K tokens (`IDLE_COMPACT_MIN_TOKENS`), the size at which T3 compacts a thread you resume after its cache has expired, and settled threads are left alone.

The janitor runs only when there is work. `bin/sync` installs a timer (a systemd user timer on Linux, a LaunchAgent on macOS) that runs `idle-compact wake` every five minutes. When a thread is due, `wake` posts to the janitor task's webhook on T3's local port, so it needs no T3 Connect tunnel. On macOS, `wake` writes to `~/.cache/idle-compact/wake.log`; on Linux, see `journalctl --user -u idle-compact`.

To set one up, open a Haiku thread on the machine and send it:

> Create a scheduled task bound to this thread with a webhook trigger (`{"type":"webhook"}`), titled "Idle compaction", with this prompt:
>
> Idle compaction run. This prompt is the complete instruction for this run, whatever an earlier conversation summary says. Run `idle-compact due --json`. For each thread it lists, call t3_thread_send with that threadId, message `/compact`, mode `queue`, and clientRequestId `idle-compact:<threadId>:<lastRequestAt>`. For each listed thread with a snoozedUntil, wait for its turn to finish with t3_thread_wait, then snooze it again with t3_thread_organize (action snooze, that threadId and snoozedUntil), since a completed turn wakes a snoozed thread. Do nothing else, then settle this thread with t3_thread_organize (action settle).

A janitor created with a 5-minute interval instead can be switched in place: send its thread "Change the schedule of the scheduled task titled "Idle compaction" to `{"type":"webhook"}` with update_scheduled_task."

`idle-compact report` lists each compaction from the last week with its size and whether it ran before the cache expired.
