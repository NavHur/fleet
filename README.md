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
- writes a marked block into `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, and `~/.config/opencode/AGENTS.md`: the shared instructions in `config/instructions.md`, then the agent's own in `config/instructions.<agent>.md` when there is one, then the same principle lines without their paths. Edit the shared rules there, never inside the block; a host's own instructions go outside it.

Fleet's own principles are written in the same format:

- `skills/principle-reach-for-what-exists`: the dependency ladder and `ceiling:` comments for deliberate shortcuts.
- `skills/principle-fail-loudly`: failure classes, purposeful catches, kept causes, and no plausible defaults for required values.
- `skills/principle-name-the-meaning`: names that carry purpose, units, and effects; named constants; mode flags split into functions; comments kept true.

Skills in this repo cite principles by path (`~/.agents/skills/principle-x/SKILL.md`), not by name, because a principle hidden from the model cannot be found by name.

## Sync a machine

```sh
git clone https://github.com/PedroNavHur/fleet   # once, at the checkout in hosts/<machine>/host.json
fleet/bin/sync            # show the plan
fleet/bin/sync --apply    # pull, link own skills, install and update third-party skills
fleet/bin/sync --all --apply   # the same on every machine, over SSH from the Mac
```

`--apply` runs only from the machine's own checkout (a worktree's links would vanish with it), refuses a checkout that lacks `origin/main`, holds a per-machine lock, and re-runs the pulled copy of itself when the pull changed it. `--all` prints one line per machine and writes each one's output to `~/.cache/fleet/sync/<machine>.log`.

`bin/sync` links each skill in `skills/` into `~/.agents/skills` (read by Codex, Cursor, and OpenCode) and `~/.claude/skills` (read by Claude Code). Any other entry in those folders, or a copy in `~/.codex/skills`, `~/.cursor/skills`, or `~/.config/opencode/skills`, is moved to `~/.skills-backups/fleet-<timestamp>/`. To add or change a skill, edit it here, merge it, and run `bin/sync --all --apply`.

## Shared host files

`bin/sync` also installs the machine-level tooling that skills rely on:

| On each machine | From this repo |
| --- | --- |
| `~/.local/bin/host-check` | `bin/host-check`: the shared validation queue |
| `~/.local/bin/bg-job` | `bin/bg-job`: long jobs that outlive the agent session |
| `~/.local/bin/idle-compact` | `bin/idle-compact`: idle Claude threads in T3 to compact before their prompt cache expires |
| `~/.local/bin/actions-runners` | `bin/actions-runners`: a self-hosted GitHub Actions runner per repository |
| `~/.local/bin/shots` | `lib/shots/shots.mjs`: screenshots of a running app as small JPEGs, queued through host-check |
| `~/.local/bin/pr-assets` | `lib/pr-assets/pr_assets.py`: pushes screenshot folders to a repo's `pr-assets` branch without a checkout and prints their embed links |
| `~/.local/bin/transcripts` | `lib/transcripts/`: this machine's Claude Code and Codex sessions. `list` filters them by age, agent, directory, prompt, or text; `show` prints one condensed to a few percent of its file; `usage` totals tokens and list-price cost by model, agent, directory, day, or week, priced with T3's `usage-model-rates.json` |
| `~/.local/lib/host-check/` | `lib/host-check/`: `guard.py` (command guard), `walk.py` (the command walk every shell-command judge reads, over `shell.py` lexing and `packages.py` package scripts), `jobclass.py` (the validation catalogue: each command's job class), `merge_method.py` (squash and rebase merge refusal), tests, OpenCode plugin |
| `~/.config/t3-orchestration.md` | `config/t3-orchestration.md` |
| `~/.config/host-validation.md` | generated from `config/host-validation.md` plus `hosts/<machine>/host-validation.md` |
| `~/.config/fleet/host.json` | `hosts/<machine>/host.json`: queue limits, CPU policy, the fleet checkout, and the SSH host `--all` reaches it by |
| `~/.config/systemd/user/builds.slice` | `hosts/<machine>/builds.slice` (Linux) |
| `~/.config/systemd/user/app-t3code*.slice.d/priority.conf` | `hosts/<machine>/systemd/`: CPU weight and memory floor for T3 agent sessions (workbox) |
| `~/.claude/hooks/*-guard.py` | `hosts/workbox/claude-hooks/`: workbox's merge, migration, and agent-CLI guards, which `/etc/claude-code/managed-settings.json` and `~/.codex/hooks.json` run |

The full list of links is in `links`. `bin/sync` also adds the guard to Claude Code, Codex, Cursor, and OpenCode as a pre-command hook. The guard also refuses PR merges that squash or rebase, and a `gh stack merge` that doesn't name `--merge`, since that one reuses the last method used. On Linux, host-check runs jobs in `builds.slice`; on macOS it runs them under `taskpolicy -c utility`, which yields the CPU to interactive work and does not limit memory.

### How the queue works

Agents read `~/.config/host-validation.md`, which keeps only what they act on. The mechanism behind it:

- Each physical Git worktree has one lock; subdirectories and symlinks share it, and outside Git the physical working directory is the key. Waiters take their worktree lock before a global slot, so they hold no global capacity. Slot acquisition is not FIFO. Locks release when the command and every child that inherited them exit. The owner files under `~/.cache/host-check/` name the last holders and may be stale when idle.
- Host-wide caps apply to all jobs, to heavy jobs (builds, a full `check`, and `test` or `vitest run` without file or directory arguments), and to builds. A heavy job waits for its class without holding a global slot, so targeted tests, lint, format, and typecheck keep running.
- One catalogue (`lib/host-check/jobclass.py`) gives every command a job class: none, light, heavy, or build. The wrapper takes the strongest class among the commands a job runs, reading package scripts and shell scripts for the commands inside; a job that runs no validation takes a light slot. A script it cannot read, or one that runs hidden commands (`"$@"`, `$cmd`, `eval`), is heavy, and so is a job that sends commands to the background. If the catalogue itself fails, host-check stops before the job runs.
- The guard (`lib/host-check/guard.py`) sends a command to the queue when it runs anything the catalogue does not class as none, so the guard and the wrapper agree. One exception: it skips opaque leaves (`eval`, `$cmd`, a shell reading stdin, an unreadable script), which are heavy for the wrapper ([ADR 0002](docs/adr/0002-guard-does-not-queue-opaque-leaves.md)). Background fan-out is a property of the job, so only the wrapper judges it. The guard recognizes package scripts (by their package.json bodies, through workspace filters), shell scripts, validation executables, pipelines, and benchmark or debug harnesses (`tsx`/`node` on `bench*`, `perf*`, `debug-*`). It trusts scripts that call host-check themselves, and misses aliases, generated commands, and commands sent to an already-open interactive shell. Hook changes take effect in new tool sessions; Codex needs `/hooks` once to trust the guard.
- Scheduling is cooperative: a command run directly bypasses the queue.

Run the tests on any machine with `bin/test`, which runs every unittest suite; CI runs it on each push to main and each pull request.

A skill with a `package.json` gets its dependencies from `bin/sync` (`pnpm install --frozen-lockfile`); `pedro-best-practices` uses that for its own oxlint. Its analyzer tests skip, with a reason, without the Rust analyzers: `bin/sync` installs the pinned `pbp-complexity` release and godot-guard (`cargo build --release` in fleet builds a local `pbp-complexity`; set `PBP_COMPLEXITY` to test it ahead of the pinned one) (set `PBP_GODOT_GUARD` to another build with `complexity --json`). Its godot-guard tests skip without godot-guard 0.2 or newer; set `PBP_GODOT_GUARD` to one, such as a godot-guard checkout's `.venv/bin/godot-guard`.

## Idle compaction

Claude Code caches a conversation for an hour after each request. Compacting a large Claude thread after that hour writes its whole context to the cache again, so each machine runs a janitor: a Claude Haiku 5.5 thread in T3 Code that sends `/compact` to the threads `idle-compact due` lists, a few minutes before their cache expires. The rules for which threads qualify are in `bin/idle-compact`; the minimum is 100K tokens (`IDLE_COMPACT_MIN_TOKENS`), the size at which T3 compacts a thread you resume after its cache has expired, and settled threads are left alone.

The janitor runs only when there is work. `bin/sync` installs a timer (a systemd user timer on Linux, a LaunchAgent on macOS) that runs `idle-compact wake` every five minutes. When a thread is due, `wake` posts to the janitor task's webhook on T3's local port, so it needs no T3 Connect tunnel. On macOS, `wake` writes to `~/.cache/idle-compact/wake.log`; on Linux, see `journalctl --user -u idle-compact`.

To set one up, open a Haiku thread on the machine and send it:

> Create a scheduled task bound to this thread with a webhook trigger (`{"type":"webhook"}`), titled "Idle compaction", with this prompt:
>
> Idle compaction run. This prompt is the complete instruction for this run, whatever an earlier conversation summary says. Run `idle-compact due --json`. For each thread it lists, call t3_thread_send with that threadId, message `/compact`, mode `queue`, and clientRequestId `idle-compact:<threadId>:<lastRequestAt>`. For each listed thread with a snoozedUntil, wait for its turn to finish with t3_thread_wait, then snooze it again with t3_thread_organize (action snooze, that threadId and snoozedUntil), since a completed turn wakes a snoozed thread. Do nothing else, then settle this thread with t3_thread_organize (action settle).

A janitor created with a 5-minute interval instead can be switched in place: send its thread "Change the schedule of the scheduled task titled "Idle compaction" to `{"type":"webhook"}` with update_scheduled_task."

`idle-compact report` lists each compaction from the last week with its size and whether it ran before the cache expired.

## File-size cap

Agents read a whole file before editing it, so files stay under 20,000 bytes, about 5,000 tokens at four bytes per token. `lib/file-size/file_size.py` (linked as `~/.local/bin/file-size`) is a ratchet: it fails on a file over the cap that is new or grew, and warns about one already over that did not grow. It skips binary and minified files, lockfiles, files with an `@generated` or Go `Code generated ... DO NOT EDIT.` line in their first five lines, and paths marked `linguist-generated` or `linguist-vendored` in `.gitattributes`. Its failure message explains how to split a file.

- **Agent commits.** The host-check guard runs the check on what each agent `git commit` (or `git commit -a`) records and refuses the commit when it fails. It follows wrappers and `bash -c` strings, and checks a commit only when every command before it in the same command line is `cd` or `pushd` to a path it can read, `true`, a shell keyword, read-only git (`status`, `log`, `show`, `diff`, `rev-parse`, `ls-files`, without `--output`), or a modelled `git add`, `git restore --staged`, `git rm --cached`, or `git reset`, which it replays, with shell globs expanded for `git add`, on a copy of the index. Any other command ends the check there, and so does an index command whose paths or source come from a `$` expansion, and a `git reset` that moves HEAD or rewrites the worktree, a `git restore` or `git rm` that writes the worktree, globs taken from another revision, paths read from a file, or an option the replay does not model (for that repository). It misses pathspec commits (`git commit FILE`), commits whose paths a `$` expansion builds (`git commit $F`), commands inside `$(...)` (taken as read-only), output redirections, quoted globs in `git add` that match below the current directory, unquoted globs in `git reset`, `git restore --staged`, and `git rm --cached` (passed to git as typed, so the replay also unstages their matches below the current directory), and a commit in a directory that is not yet a repository when the hook runs.
- **Branches.** The `pre-commit` skill runs `file-size check --base <branch>`.
- **CI in personal repositories.** `.github/actions/file-size` checks a pull request against its base and a push against the commit it replaced. Fleet runs it in `test.yml`; another repository adds this workflow, a private repository on its devbox runner, `runs-on: [self-hosted, devbox]` (see Actions runners):

```yaml
name: file size
on:
  pull_request:
  push:
    branches: [main]
jobs:
  file-size:
    name: max 5k tokens per file
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: PedroNavHur/fleet/.github/actions/file-size@main
```

## Actions runners

A machine with `hosts/<machine>/runners.json` (today only devbox) runs a self-hosted GitHub Actions runner for each repository listed there, so pushes and pull requests get CI without GitHub-hosted minutes. A personal account has no account-level runners, so each repository registers its own. `bin/sync` registers any that are missing and refreshes any whose job environment changed.

`actions-runners install` downloads the latest runner release, registers it with a token from `gh` as `<host>-<name>` with the file's labels, and starts `actions-runner@<name>.service`. That systemd user unit runs in `builds.slice` at nice +10, so CI jobs share the CPU weight and memory ceiling of host-check jobs instead of competing with interactive work. Jobs see `~/.local/bin` on their PATH, use the machine's pnpm store, and run Node with `--use-openssl-ca`, so the runner's bundled Node and setup-node builds trust the system CA store rather than the copy compiled into Node. A workflow picks a runner by the machine's label: `runs-on: [self-hosted, devbox]`. All CI runs on devbox, which is otherwise mostly idle, so homebox's memory stays free for game development; a private repository gets an entry in `hosts/devbox/runners.json` when one of its workflows targets devbox. Removing a host's `runners.json` stops `bin/sync` from installing runners there; run `actions-runners remove <name>` for each runner first, while the file still lists it. `actions-runners status` shows each runner's service and GitHub state, and `actions-runners remove <name>` deregisters one.

A runner runs whatever code a job checks out, on a machine that also holds my work. Only private repositories get one: GitHub never runs their fork pull requests' workflows, and public repositories require my approval for every outside contributor's run.

Runners keep their disk between jobs, so `.github/actions/ci-cache` (`lib/ci-cache/ci_cache.py`) keeps CI state there, under `~/.cache/fleet-ci/<owner>/<repo>`. `passed-check KEY` sets `hit` when the checked-out tree already passed under that key, and `passed-record KEY` records a pass. A merge commit whose tree its pull request already tested then skips the work; the key names whatever outside the tree the result depends on, such as the Godot version. `godot-restore PREFIX` pins a Godot project's imported assets to mtime 0, so Godot skips re-importing them, and restores the `.godot` directory and `.import` files saved under `PREFIX-<assets hash>` (its `key` output). `godot-save KEY` saves them after the job. That replaces `actions/cache`, whose upload took up to 76 s on a miss. hexstead's and heavenrest's `quality.yml` show the steps.
