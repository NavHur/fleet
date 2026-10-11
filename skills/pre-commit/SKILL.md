---
name: pre-commit
description: "Deterministic pre-commit validation. Use before a required commit gate or when the user requests format, lint, typecheck, and tests. Do not use for remote CI diagnosis or code review."
---

# Pre-commit

Run deterministic repository checks directly. Do not spawn subagents or launch external coding agents for this workflow.

## Prepare

1. Resolve the target Git repository root and inspect `git status --short --branch`. Preserve unrelated user changes.
2. Resolve the four commands from the repository's own scripts, using the check mapping below: format, lint, typecheck, tests. A step with no command in the repository is missing, not passed.
3. Do not edit files or run Git operations while checks are active. The formatter may change files through the repository's format command.

## Run sequence

1. From the repository root, run all four checks as one job, in order, stopping at the first failure. When `~/.local/bin/host-check` exists (workbox, devbox, homebox), queue the job through it and follow `~/.config/host-validation.md`:

   ```sh
   ~/.local/bin/host-check bash -lc '<format> && <lint> && <typecheck> && <tests>'
   ```

   For a pnpm repository this is `host-check bash -lc 'pnpm format && pnpm lint && pnpm typecheck && pnpm test'`. host-check admits one job per worktree, so this single command is the whole gate; wait for it to exit. Read its output when it exits rather than polling logs. On a host without `host-check`, run the same `bash -lc '…'` chain directly.
2. If a command cannot start or a step has no command, inspect only the configuration relevant to that step and run the repository-supported equivalent with existing tools and environments, again as one job (through `host-check` when available). Do not install packages.
3. Pass a step only when a real check ran and returned success. Fail the gate if any step fails, is missing, cannot start, or cannot be verified. A missing check is not a pass. After fixing a failure, rerun the whole chain once.
4. Inspect the final worktree status. Report the command, each step's result, any missing tooling or manual equivalent, and formatter-created changes. Do not commit or push unless asked.

## Check mapping

- format: package script `format`, then `fmt`; Make target `format`; Python `ruff format .`
- lint: package script or Make target `lint`; Python `ruff check .`
- typecheck: package script `typecheck`, then `type-check`; Make target `typecheck`; Python `mypy .`, then `pyright .`
- tests: package script `test`, or `test:run` when `test` starts a watcher (bare `vitest`); Make target `test`; Python `pytest`

Godot repositories with a `.godot-guard.yml` use godot-guard from the repository's `.venv` (`tools/setup_lint_tools.sh` creates it): format is `.venv/bin/godot-guard format`, and lint, typecheck (the GDScript analyzer), and tests are all inside `.venv/bin/godot-guard gate`. The gate is `host-check bash -lc '.venv/bin/godot-guard format && .venv/bin/godot-guard gate'`. When the gate's check step fails only because the ratchet baseline has stale or loose entries, run `.venv/bin/godot-guard baseline`, which only removes or lowers entries, and rerun the gate. Never raise or add an entry by hand.

For Node projects, detect the package manager by lockfile. Run Make targets only when they exist. Use existing Python environments and tools only.

## nj-homes-choice-next

On workbox, Husky hooks (`~/.config/husky/init.sh`) run lint-staged on commit and lint, format check, and the browser page gates on push. The four checks above are the whole pre-commit gate; leave the axe and smoke page gates to the push hook, and run `~/.local/bin/njhomes-page-gates` only when the user asks for them.
