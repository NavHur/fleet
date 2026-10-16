# Shared host validation policy

Every agent on this machine shares one validation queue, so checks leave
capacity for interactive work and previews. The last section describes this
machine.

## Run checks

- Run full builds, test suites, lint, typechecks, formatting checks, and
  benchmarks with `~/.local/bin/host-check COMMAND [ARGS...]` from the
  repository directory: `host-check pnpm build`.
- Queue a pipeline once:
  `host-check bash -lc 'pnpm lint && pnpm typecheck && pnpm test'`. host-check
  refuses nested calls, so leave a pipeline whose scripts already call it
  unwrapped.
- Targeted tests and browser-driven scripts (axe gates, smoke runs, visual or
  screenshot captures, e2e, `playwright test`) go through the queue too. A
  server you start in the background for later runs stays outside it, because
  a queued job holds its worktree lock until it exits.
- One job runs per Git worktree at a time, and a wrapped pipeline stays in its
  worktree. Builds and whole test suites are heavy and wait for their own
  slots; target tests at files or directories while iterating.
- Wait for queued jobs instead of starting duplicates. Keep reads and edits
  outside the queue. The queue changes scheduling, not which checks must pass.
- Run benchmarks only when requested: one measured run, no warmup, a timeout
  inside the queue (`host-check timeout --kill-after=10s 10m pnpm test`).
  Inspect a failure before repeating.
- Leave application services running, and route the builds of preview and
  production workflows through host-check.
- A misdetected class takes `HOST_CHECK_CLASS=build|heavy|light` before
  `host-check`; `host-check env HOST_CHECK_CLASS=…` has no effect. The wrapper
  sets `VITEST_MAX_WORKERS`; keep Vitest at or below it, with `--maxWorkers=N`
  if the version ignores the variable. `host-check --help` prints this
  machine's limits.
- A hook rejects common unwrapped checks: wrap the whole check and retry. The
  policy also covers commands the hook cannot see, such as aliases. Leave the
  lock files under `~/.cache/host-check/` alone.
- When delegating validation, include this file's path.

## Long jobs

A job expected to outlast about ten minutes (per-layer gates, a full `check`, a
build plus restart) runs through `~/.local/bin/bg-job`, so it survives the
session that started it. Launch it as one background command:
`bg-job start NAME -- host-check pnpm check && bg-job wait NAME`. After a
restart or a lost notification, `bg-job status NAME` reports running or the exit
code, and `bg-job log NAME` shows the tail. Then arm the fallback wake in
`~/.config/t3-orchestration.md` ("Background jobs").
