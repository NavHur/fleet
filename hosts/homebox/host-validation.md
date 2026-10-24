## This machine: homebox

homebox is a 2018 laptop on home Wi-Fi: an i7-8750H (6 cores, 12 threads),
16 GiB of RAM, and a GTX 1070 that Godot does not use yet. It runs T3, the
agents it starts, and all game development (hexstead, wingmen); CI runs on
devbox.

- Limits: 6 jobs, 2 of them heavy (whole suites, builds, and full Godot
  gates). A full `godot-guard gate` holds about 4 GiB, so a third would thrash
  the slice's memory. Vitest defaults to 3 workers. Jobs run at nice +10.
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

### Previews

The game web previews are served from here behind Cloudflare tunnels. Each
server serves a `current` symlink, so a deploy is live without a restart.

| Game | Server | Tunnel |
| --- | --- | --- |
| wingmen | `wingmen-web` (`tools/web/deploy.sh` publishes) | `https://angels.pnav.dev` |
| hexstead | `hexstead-night-web` (`~/srv/hexstead-night/current`) | `https://night.pnav.dev` |
| hexstead | `hexstead-web` (`~/.local/share/hexstead-web/current`) | `https://stead.pnav.dev` |

They are user services: `systemctl --user restart NAME.service`,
`journalctl --user -u NAME.service`.
