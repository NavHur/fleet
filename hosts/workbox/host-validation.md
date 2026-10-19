## This machine: workbox

workbox has eight vCPUs (t3.2xlarge) and 30 GiB of RAM, shared by interactive
coding tools, T3, and production previews.

- Limits: 6 jobs, 3 heavy, 2 builds. Vitest defaults to 5 workers.
- Each job runs in its own scope under `builds.slice`
  (`~/.config/systemd/user/builds.slice`), which the kernel enforces: CPU weight
  250 against 1000 for `app.slice` (T3, agent sessions, previews), so on a
  saturated host jobs keep about 20% of the CPU and still finish, and on an
  idle host they may use all eight vCPUs. Within `app.slice`, T3 has weight
  1000 and its agent sessions (`app-t3code.slice`) 500. Build memory is
  reclaimed above 18G and hard-capped at 22G. If a build is OOM-killed (exit
  137), rerun it once the host is quieter. These limits apply only to
  host-check jobs; `t3code.service` has `MemoryLow=2G` and agent sessions
  `MemoryLow=4G`.
- Never start a development server (`next dev`, `vite`, `pnpm dev`, and the
  like), for any purpose. They compile on demand and burn CPU this host does not
  have. Build through the queue and serve production with `next start`, or
  restart the mapped `*-prod` service. The guard denies dev servers, including
  `a11y-pages.ts` without `A11Y_BASE_URL` and `smoke-local.ts`, which boot one.
  For nj-homes-choice-next page gates run
  `~/.local/bin/njhomes-page-gates [FILE...]`.
- `bg-job` runs each job as a transient systemd user service, `bgjob-NAME`.
