## This machine: devbox

devbox has eight EPYC vCPUs and about 15 GiB of RAM, shared by interactive
coding tools, T3, and previews. It runs every self-hosted CI runner and light
web work; game development (hexstead, wingmen) happens on homebox.

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
- Never start a development server (`next dev`, `vite`, `pnpm dev`,
  `wrangler dev`, and the like). The guard denies them. Build through the
  queue and serve the production build: a supervised service for the main
  checkout, `preview-worktree` for a worktree (below).
- `bg-job` runs each job as a transient systemd user service, `bgjob-NAME`.

### Previews

Pick the route by checkout. The main checkout under `~/src` has a supervised
service and a public tunnel; any other worktree, including T3's under
`~/.t3/worktrees`, gets a worktree preview. Never point a shared service at a
worktree. Previews use test data, never production.

#### Main checkout: supervised service

A browser outside devbox cannot reach `localhost`. Restart the project's
service (its pre-start builds for production; start no separate build
alongside it), confirm it is active, and check its journal if startup fails.
Then open the tunnel URL in the T3 browser (`preview_status`, `preview_open`
if nothing is attached) and test the public route. Report the tunnel URL, the
service status, and what you checked. A loopback `curl` is diagnosis only.

| Project | Service | Tunnel |
| --- | --- | --- |
| HiveFront | `hivefront-test-server` | `https://hive-dev.pnav.dev` |
| pnav | `pnav-dev-server` | `https://dev.pnav.dev` |
| LeetWiz | `leetwiz-preview` | `https://leetwiz-dev.pnav.dev` |
| LiteQuiz | `litequiz-preview` (system: `sudo systemctl`, `journalctl -u`) | `https://quiz-dev.pnav.dev` |
| NJ Impact | `nj-impact-dev-server` | `https://nj-impact-dev.pnav.dev` |
| GovStructure | `govstructure-preview` | `https://govstructure.pnav.dev` |
| Fonema | `fonema-preview` (the `fonema-prototype` worktree for now) | `https://fonema-dev.pnav.dev` |

The rest are user services: `systemctl --user restart NAME.service`,
`journalctl --user -u NAME.service`. A project with no service and tunnel gets
one set up before it is previewed.

#### A worktree: `preview-worktree`

Run `preview-worktree start` in the worktree. It builds through host-check
(`--no-build` serves the last build), then serves that build on a loopback
port as the transient user service `wtpreview-NAME`, and prints the URL. Open
it in the T3 browser, which runs on devbox, as an environment port:
`preview_open` with `target: {kind: "environment-port", port: PORT}`. The app
sees the origin `http://localhost:PORT`.

- `start` is idempotent: run it again after a change to rebuild and restart on
  the same port. `preview-worktree status` lists previews; `preview-worktree
  stop` ends yours when you are done.
- Each preview keeps its own local state (D1 under the worktree's `.wrangler`),
  copies untracked local files such as `.dev.vars` from the main checkout once,
  and never touches the main checkout or its service.
- At most 3 run at once, each under a 1.5 GB memory ceiling, on ports
  4400-4419, and each stops itself after 8 hours. A preview whose worktree was
  removed is pruned on the next `start`, or with `preview-worktree prune`.
  `previews.json` sets these limits.
- Recipes live in fleet's `hosts/devbox/previews.json`, keyed by the main
  checkout's directory name. A project without one gets one there, derived
  from its supervised service, before its worktrees are previewed.
- No public URL: the tunnel hostnames serve the main checkout. Use the T3
  browser, or a loopback URL from a script queued through host-check.
