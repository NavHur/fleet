## This machine: homebox

homebox is a 2018 laptop on home Wi-Fi: an i7-8750H (6 cores, 12 threads),
16 GiB of RAM, and a GTX 1070 that Godot does not use yet. It runs T3 and the
agents it starts.

- Limits: 6 jobs, with no separate heavy or build caps. Vitest defaults to 3
  workers. Jobs run at nice +10.
- Each job runs in its own scope under `builds.slice`
  (`~/.config/systemd/user/builds.slice`): CPU weight 20, an aggregate 900% CPU
  ceiling, memory reclaim above 10 GiB, and a 12 GiB hard ceiling. If a build is
  killed with exit 137, inspect memory pressure and retry when the host is
  quieter. Without a user systemd bus, jobs still queue and run at nice +10
  outside the slice, and its ceilings do not apply.
- Sustained all-core load heats a laptop chassis and throttles it, so a long
  job slowing down partway through is the CPU, not a hang.
- Never start a development server (`next dev`, `vite`, `pnpm dev`, and the
  like). The guard denies them. Build through the queue and serve the
  production build.
- `bg-job` runs each job as a transient systemd user service, `bgjob-NAME`.
