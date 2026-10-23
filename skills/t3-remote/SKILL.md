---
name: t3-remote
description: "Read or message T3 threads on another machine (devbox, homebox, workbox, any SSH host) through that host's own t3 CLI. Use when checking, prioritizing, or replying to threads on a host the local t3-code MCP cannot see."
---

# T3 threads on another host

The `t3-code` MCP tools reach only the server on this machine. Every other host runs its own T3 server bound to `127.0.0.1`, so Tailscale alone cannot reach it; SSH plus that host's `t3` CLI can. Hosts are SSH aliases: from the Mac, `workbox`, `devbox`, and `homebox`.

Run everything through the helper, which picks the binary of the host's running `t3 serve` so the CLI matches the server:

```sh
H=~/.agents/skills/t3-remote/scripts/t3-remote
$H <host> open                                   # unsettled top-level threads, every project
$H <host> projects                               # project ids for `thread list` and `thread start`
$H <host> thread show --messages 3 <threadId>    # a thread's state and latest messages
$H <host> thread --help                          # the rest of the CLI
```

## Check a host's threads

1. Run `open` on each host the user named; "all hosts" means every fleet host.
2. Run `thread show` on every thread `open` listed, with enough messages to see what the thread last asked for. A thread's status says only whether a turn is running; the latest messages say what it waits on.
3. Report per thread: host, project, what it waits on, and what the user should do. Done when every listed thread has that line.

## Message a thread

`thread send <threadId> <message>` and `thread start <project> <message>` start an agent turn on that host, so run them only when the user asked to message or start that thread. `--wait` prints the reply; `-` as the message reads it from stdin.

## Limits

- `open` lists threads the user or an agent launched. Delegated subagent threads are left out.
- The CLI cannot settle, archive, or interrupt a thread; the user does that in the T3 app.
- A `t3-thread://` link opens only when the user's app is connected to that host's environment. Name the host beside every link.
