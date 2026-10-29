"""Restart OpenCode servers that started before their current plugins or binary.

    python3 opencode_servers.py [--apply]

A long-running `opencode serve` keeps the plugin modules it imported at startup,
so a plugin that changed under it (bin/sync links plugins into the repo, so a
`git pull` is enough) never takes effect. It also keeps running the binary it
started from, so an upgrade leaves it on the old version, and T3 Code, which
asks that server for its version, reports the upgrade as not taken. Prints one
plan line per stale server, in bin/sync's format. With --apply, restarts each
one that has no client connected: a systemd unit through systemctl, a detached
`serve --service` daemon by SIGTERM (the next OpenCode client starts a fresh
one). A busy or unmanaged server gets a warning with the command to run later.
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
    """(pid, start time, args) for each `opencode serve` this user runs, the only
    ones it can inspect or restart."""
    now = time.time()
    for line in run("ps", "-U", str(os.getuid()), "-o", "pid=,etime=,args=").splitlines():
        pid, etime, args = line.split(None, 2)
        if is_server(args):
            yield int(pid), now - seconds(etime), args


def plugins_changed():
    """Newest modification time among the plugin files, following links."""
    times = [path.stat().st_mtime for path in PLUGINS.glob("*") if path.exists()]
    return max(times, default=0)


def running_executable(pid):
    """Path of the file the process is running; Linux marks a replaced one " (deleted)"."""
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except FileNotFoundError:  # no /proc (macOS), or the process exited
        # lsof, not ps: ps shows the path the process was launched by, maybe relative
        listing = run("lsof", "-a", "-p", str(pid), "-d", "txt", "-Fn").splitlines()
        return next((line[1:] for line in listing if line.startswith("n")), "")


def binary_replaced(pid, started):
    """Whether the executable the server runs was installed after it started.

    ctime, not mtime: the install script keeps the release tarball's mtime, but
    any install creates or renames the file, which sets its ctime. A binary that
    vanished was removed or replaced, so it counts as replaced.
    """
    path = running_executable(pid)
    if not path:  # the process exited
        return False
    if path.endswith(" (deleted)"):
        return True
    try:
        return os.stat(path).st_ctime > started
    except FileNotFoundError:
        return True


def stale_reason(pid, started, plugins_mtime):
    if started < plugins_mtime:
        return "plugins changed since it started"
    if binary_replaced(pid, started):
        return "its binary was replaced since it started"
    return None


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


def plan(pid, started, args, plugins_mtime):
    """Print the plan line for a stale server; the restart command, if it has one."""
    reason = stale_reason(pid, started, plugins_mtime)
    if not reason:
        return None
    command = restart_command(pid, args)
    if not command:
        say("warning", f"OpenCode server {pid} is stale ({reason}); restart it by hand: {args}")
        return None
    say("restart", f"OpenCode server {pid} ({reason}): {' '.join(command)}")
    return command


def restart_when_idle(pid, command):
    if clients(pid):
        say("warning", f"OpenCode server {pid} has a client connected; run `{' '.join(command)}` when it is idle")
        return
    restart(pid, command)


def main(argv):
    apply = "--apply" in argv
    plugins_mtime = plugins_changed()
    for pid, started, args in servers():
        command = plan(pid, started, args, plugins_mtime)
        if command and apply:
            restart_when_idle(pid, command)


if __name__ == "__main__":
    main(sys.argv[1:])
