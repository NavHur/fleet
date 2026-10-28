"""Restart OpenCode servers that started before the current plugins.

    python3 opencode_servers.py [--apply]

A long-running `opencode serve` keeps the plugin modules it imported at startup,
so a plugin that changed under it (bin/sync links plugins into the repo, so a
`git pull` is enough) never takes effect. Prints one plan line per stale server,
in bin/sync's format. With --apply, restarts each one that has no client
connected: a systemd unit through systemctl, a detached `serve --service`
daemon by SIGTERM (the next OpenCode client starts a fresh one). A busy or
unmanaged server gets a warning with the command to run later.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

PLUGINS = Path.home() / ".config" / "opencode" / "plugins"


def say(verb, text):
    print(f"  {verb:<10} {text}")


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def seconds(etime):
    """ps etime, [[dd-]hh:]mm:ss, as seconds."""
    days, _, clock = etime.strip().rpartition("-")
    total = 0
    for part in clock.split(":"):
        total = total * 60 + int(part)
    return total + int(days or 0) * 86400


def is_server(args):
    words = args.split()
    return any(Path(w).name == "opencode" and "serve" in words[i + 1:] for i, w in enumerate(words))


def servers():
    """(pid, start time, args) for each running `opencode serve`."""
    now = time.time()
    for line in run("ps", "-Ao", "pid=,etime=,args=").splitlines():
        pid, etime, args = line.split(None, 2)
        if is_server(args):
            yield int(pid), now - seconds(etime), args


def plugins_changed():
    """Newest modification time among the plugin files, following links."""
    times = [path.stat().st_mtime for path in PLUGINS.glob("*") if path.exists()]
    return max(times, default=0)


def clients(pid):
    """Inbound TCP connections to the server's listening ports."""
    lsof = ("lsof", "-nP", "-a", "-p", str(pid), "-iTCP")
    ports = {line.split()[8].rsplit(":", 1)[1] for line in run(*lsof, "-sTCP:LISTEN").splitlines()[1:]}
    established = [line.split()[8] for line in run(*lsof, "-sTCP:ESTABLISHED").splitlines()[1:]]
    return [conn for conn in established if conn.split("->")[0].rsplit(":", 1)[1] in ports]


def unit(pid):
    """The systemd user unit whose main process is pid, if any."""
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return None
    name = cgroup.strip().rsplit("/", 1)[-1]
    if not name.endswith(".service"):
        return None
    main = run("systemctl", "--user", "show", "-p", "MainPID", "--value", name).strip()
    return name if main == str(pid) else None


def restart_command(pid, args):
    name = unit(pid)
    if name:
        return ["systemctl", "--user", "restart", name]
    if "--service" in args.split():
        return ["kill", str(pid)]
    return None


def restart(pid, command):
    if command[0] == "kill":
        os.kill(pid, signal.SIGTERM)
    else:
        subprocess.run(command, check=True)


def main(argv):
    apply = "--apply" in argv
    changed = plugins_changed()
    for pid, started, args in servers():
        if started >= changed:
            continue
        command = restart_command(pid, args)
        if not command:
            say("warning", f"OpenCode server {pid} predates its plugins; restart it by hand: {args}")
            continue
        say("restart", f"OpenCode server {pid} (plugins changed since it started): {' '.join(command)}")
        if not apply:
            continue
        if clients(pid):
            say("warning", f"OpenCode server {pid} has a client connected; run `{' '.join(command)}` when it is idle")
            continue
        restart(pid, command)


if __name__ == "__main__":
    main(sys.argv[1:])
