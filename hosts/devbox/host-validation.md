## This machine: devbox

devbox has eight EPYC vCPUs and about 15 GiB of RAM, shared by interactive
coding tools, T3, and previews.

- Limits: 6 jobs, with no separate heavy or build caps. Vitest defaults to 2
  workers. Jobs run at nice +10.
- Each job runs in its own scope under `builds.slice`
  (`~/.config/systemd/user/builds.slice`): CPU weight 20 with no CPU ceiling, so
  jobs use all eight vCPUs when the host is idle and yield when it is busy;
  memory reclaim above 10 GiB, and a 12 GiB hard ceiling. If a build is
  killed with exit 137, inspect memory pressure and retry when the host is
  quieter. Without a user systemd bus, jobs still queue and run at nice +10
  outside the slice, and its ceilings do not apply.
- If a supervised service builds on restart, queue the whole `systemctl`
  restart through host-check so other queued checks wait. That build runs in
  the service's own unit, outside `builds.slice`. Do not launch a separate build
  alongside a service startup that builds the same output.
- Never start a development server (`next dev`, `vite`, `pnpm dev`, and the
  like). The guard denies them. Build through the queue and serve the
  production build.
- `bg-job` runs each job as a transient systemd user service, `bgjob-NAME`.
