---
name: update-t3-tools
description: Update T3 Code, Codex, Claude Code, OpenCode, and Cursor Agent on the host; preserve the persistent T3 service and verify T3 Connect after restart. Use for host maintenance, not application deployments or desktop app updates.
disable-model-invocation: true
---

For T3 agent dispatch and lifecycle, read
`~/.config/t3-orchestration.md` before launching children.


# Update T3 tools

First identify the host type:

- **Server host** (Linux with a systemd user unit `t3code.service`, such as workbox, devbox, or homebox): follow this whole workflow.
- **Desktop host** (macOS running T3 Code Desktop): update only `codex`, `claude`, `opencode`, and `cursor-agent`, then restart their standalone running instances. Keep T3 Desktop running. Skip the service, duplicate-server, and T3 Connect sections; desktop app updates are outside this workflow.

A full maintenance request covers all five CLIs, duplicate-server cleanup, and loading the updated runtime into the persistent T3 service. For a narrower request, perform only the requested operations. Existing restart authorization covers the brief interruption; announce it without asking again. Editing this skill does not itself authorize running updates.

## Discover installations and service ownership

Record executable paths, resolved symlinks, versions, installation methods, and release channels for `t3`, `codex`, `claude`, `opencode`, and `cursor-agent`. Check whether `agent` is the same Cursor installation. Use installed help and package metadata to select supported update commands.

On a server host, the intended owner is the enabled systemd user unit `t3code.service`, using `~/.t3`. Clients use T3 Connect. Preserve this arrangement through upgrades; an SSH-scoped server is an obsolete duplicate, not the replacement supervisor.

Inspect:

```sh
command -v t3 codex claude opencode cursor-agent agent
npm list -g --depth=0
systemctl --user cat t3code.service
systemctl --user show t3code.service -p MainPID -p ControlGroup -p ActiveState -p UnitFileState -p Restart -p RestartUSec
loginctl show-user "$USER" -p Linger
ps -eo pid,ppid,lstart,cgroup,args
ss -ltnp
ss -tnp
```

Filter process output to T3 and its ancestors/children. For every T3 server, identify its base directory, start time, listener, supervisor, and active connections. The service MainPID can be the launcher, with the listener owned by its child. Inspect `/proc/<pid>/cgroup` to distinguish `app.slice/t3code.service` from an SSH `session-*.scope`. Read environment variables or launcher metadata only as needed, without exposing credentials.

Check the service's effective PATH against the CLI paths above. An interactive shell finding a new CLI does not prove the service can find it. Preserve existing service configuration and drop-ins, including:

- `Linger=yes`, an enabled unit, and `Restart=always` with its existing delay. Linger allows startup at boot and operation after logout. Keep systemd's crash-loop limits.
- `~/.config/systemd/user/t3code.service.d/listen.conf`, which pins `T3CODE_HOST=127.0.0.1` and the host's fixed `T3CODE_PORT` (3773 on workbox, 3776 on devbox and homebox). Read the drop-in rather than assuming the port.

The provisioned relay forwards to that fixed origin. A random service port previously let the homepage respond locally while T3 Connect failed with `endpoint_request_failed`. Preserve agreement between the service listener and relay origin; do not select a fallback port to bypass a conflict.

Proceed when every server for the target base directory has an identified owner. Discover each host's intended supervisor and port rather than copying another host's settings.

## Update all requested CLIs

Use each installation's supported updater and preserve its channel. Confirm flags with local help before execution.

| Tool | Update method |
| --- | --- |
| T3 Code managed runtime | `t3 update --base-dir ~/.t3 --channel <discovered channel> --yes` (workbox uses `nightly`). This downloads the runtime and switches the installed background service. |
| Codex standalone | `codex update` |
| Claude Code native | `claude update` |
| OpenCode npm | `npm install -g opencode-ai@latest`, preserving any explicitly pinned version/channel. |
| Cursor Agent | `cursor-agent update`; update once when `agent` is an alias of the same installation. |

T3 may have both an npm launcher and a managed runtime. Updating npm alone does not establish that the service runtime changed. If the npm launcher itself needs updating, use its existing channel from `npm view t3 dist-tags --json`, then use the supported runtime updater and verify both resolutions. Do not replace the managed installation with a second server or hard-code a new runtime path into the unit.

Update provider CLIs before T3 so the service restart can load the finished set. Serialize npm global mutations; independent native updaters may run concurrently. Account for every requested tool even if one fails. Capture each exit status and before/after version, distinguishing updated, already current, failed, and missing. A failed provider update does not justify skipping the remaining independent updates, but the overall run remains partial.

If npm prerelease peer-resolution warnings repeat without progress, terminate only that installer and wait for its exit. Retry once with command-local `--legacy-peer-deps`; report failure if that retry fails. If install scripts are blocked, inspect the affected package and use a package-specific rebuild or supported command-scoped allowlist. Verify affected native dependencies such as `node-pty` or `msgpackr-extract`; preserve global script policy.

## Keep one supervisor and complete the restart

On a server host, retain `t3code.service`. Inspect `~/.t3/ssh-launch/*/{pid,port,managed,run-t3.sh}` if an SSH duplicate exists. The desktop can recreate it and overwrite launcher metadata. Have the user disable the saved SSH connection for that host and use T3 Connect if necessary; editing SSH launcher files alone is not a durable fix. Stop only a revalidated duplicate for the same base directory, using its supervisor or graceful signal. Leave unrelated servers and work outside the authorized interruption scope alone.

T3's updater can restart the server and disconnect this very conversation. Before invoking it, arrange the update and post-start verification in a separate systemd unit or equivalent supervisor outside `t3code.service` and the SSH session cgroup. Record private logs and a result file with update exit status and health checks. Merely backgrounding a child or using `nohup` inside the service cgroup does not protect it from the service restart. Save a handoff path before the interruption.

Let the supported updater own the runtime switch. If it already restarted successfully, avoid a second restart. If it reports a pending restart, use the supported `t3 service restart` for the target installation or restart the verified existing unit. Inspect effective configuration afterward, including the fixed-port drop-in and runtime selection. Do not manually edit the service's runtime state or database to force an upgrade or bypass rollback.

Use a bounded shutdown wait of at most 60 seconds. If the old server remains, report the failure rather than starting another process or killing all Node/Codex processes. A scheduled update or restart is not a completed operation; read its results after reconnecting.

## Verify the running server and T3 Connect

After startup, verify:

- Every requested CLI has a recorded update result and works with `--version`; the service can resolve the intended provider binaries.
- When a restart occurred, the old server exited and the listener belongs to the new server. Determine its version from its resolved executable and startup/version evidence, not just the shell's `t3 --version`. Detect and report a rollback or pending update.
- Exactly one server uses the target base directory. Its listener process belongs to `t3code.service`, and its launcher matches MainPID. Repeat after the old launcher's retry delay to catch respawning SSH duplicates.
- The service is enabled and active, linger remains enabled, and the fixed loopback listener returns HTTP 200.
- Recent `~/.t3/userdata/logs/boot-service.log` and the unit journal show successful startup with no unresolved relay, address-in-use, or active-writer failure.
- The configured public relay endpoint returns HTTP 200 after tunnel registration. Use bounded retries during startup; an early 530 can precede registration. Discover the configured endpoint rather than embedding its hostname in this skill.
- A real T3 Connect reconnect succeeds. Inspect recent `server.trace.ndjson` for successful `/api/t3-connect/mint-credential`, `/oauth/token`, and `/api/auth/session` requests from the desktop/relay, then confirm the desktop loads the environment. Extract only timestamps, paths, statuses, and non-secret client identifiers; never dump request headers or credentials.

A homepage 200 or an unauthenticated credential probe only proves reachability. It does not prove authenticated reconnect or provider-session recovery. If desktop access is unavailable, report transport health separately and ask the user to confirm reconnect; do not claim full verification. Persistent service ownership prevents SSH logout from stopping T3, but service restarts and host reboots can interrupt active agents.

Report the five CLI outcomes, the actual running T3 version, supervisor and port, relay/reconnect evidence, and any unresolved issue. Host maintenance does not update the user's desktop application.
