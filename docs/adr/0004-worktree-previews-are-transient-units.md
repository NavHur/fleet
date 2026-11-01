# Worktree previews are transient units, not a guard exception

Agents on devbox work in worktrees, but each supervised preview service builds
from the project's main checkout, which other sessions share. The guard denies
`wrangler dev` and treats a background `node e2e/...` launcher as an unqueued
browser script, so an agent could see its branch only by packing a server and
its captures into one host-check job. `bin/preview-worktree` serves a
worktree's build as a transient systemd user service, `wtpreview-NAME`. It
builds through host-check, keeps a port from a fixed range across restarts,
caps memory, stops itself after a lifetime, and prunes previews whose worktree
is gone. The T3 browser runs on devbox and opens the port directly.

## Considered options

- **Point the shared service at a worktree with a drop-in** (pnav's
  `worktree-override.conf` does this today): one slot per project, the main
  preview disappears for everyone, and nothing restores it.
- **Let the guard allow servers that serve a prebuilt artifact** (`wrangler dev`
  without a build step, `next start`, `vite preview` off the default port): the
  hook cannot tell a prebuilt `main` from `src/index.ts`, and the servers would
  run as loose background processes with no port allocation, memory ceiling,
  or end.
- **Deploy each branch to a Cloudflare preview URL** (`wrangler versions upload
  --preview-alias`): it removes the local server, but it covers only Workers
  projects, shares the remote preview database between branches, and
  publishes every branch.

## Consequences

Recipes (install, build, setup, serve) live in `hosts/devbox/previews.json`
and are copied into each preview's state when it starts, so the unit needs
nothing else. A project without a recipe is refused by name until one is
added. The served origin is `http://localhost:PORT`, which recipes pass to the
app (`AUTH_ORIGIN` for LeetWiz). Worktree previews get no public hostname;
that needs a tunnel route per preview or a wildcard, which is a Cloudflare
change.

Cleanup after `git worktree remove` is lazy. The preview keeps running, with
its memory ceiling, until the next `start` or `prune` stops it, or its
lifetime ends it. A preview whose worktree is gone does not count against the
limit, so it never blocks a new one. A watcher or timer would stop it sooner
at the cost of another process or unit per host.
