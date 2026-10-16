"""Register the host-check guard as a pre-command hook for each agent, and write
the Claude Code settings fleet manages (config/claude-settings.json, overridden
per key by hosts/<host>/claude-settings.json).

    python3 hooks.py BACKUP_DIR [--apply]

Prints one plan line per change, in bin/sync's format. With --apply, copies
each settings file into BACKUP_DIR before rewriting it. Only the guard entry and
the managed Claude Code keys are written; every other setting and hook stays
as it was. New entries are appended, because Codex keys hook trust by position.
"""
import json
import os
from pathlib import Path
import shutil
import sys

HOME = Path.home()
GUARD_PATH = HOME / ".local" / "lib" / "host-check" / "guard.py"
MARKER = "host-check/guard.py"
MANAGED_CLAUDE = Path("/etc/claude-code/managed-settings.json")
CLAUDE_SETTINGS = Path(__file__).resolve().parents[2] / "config" / "claude-settings.json"
HOST_CONF = HOME / ".config" / "fleet" / "host.json"  # bin/sync links it to hosts/<host>/host.json
# Hooks that call scripts from skills fleet no longer installs for every agent.
RETIRED_HOOKS = ["/skills/impeccable/"]
# Managed keys merged one entry at a time, so a machine's own entries (a gateway's token) survive.
MERGED_KEYS = {"env"}
MESSAGES = {
    "Claude Code": ("hook", "Claude Code: add the guard to {}"),
    "Claude settings": ("set", "Claude Code: write {keys} in {path}"),
    "Codex": ("hook", "Codex: add the guard to {}"),
    "Codex cleanup": ("unhook", "Codex: remove impeccable skill hooks from {}"),
    "Cursor": ("hook", "Cursor: add the guard to {}"),
}


def command(agent):
    return f"/usr/bin/python3 {GUARD_PATH} {agent}"


def short(path):
    path = str(path)
    return "~/" + path[len(str(HOME)) + 1:] if path.startswith(str(HOME) + "/") else path


def say(verb, text):
    print(f"  {verb:<10} {text}")


def load(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def has_guard(data):
    return MARKER in json.dumps((data or {}).get("hooks", {}))


def claude():
    managed = load(MANAGED_CLAUDE)
    if has_guard(managed):
        return None  # already enforced machine-wide
    if (managed or {}).get("allowManagedHooksOnly"):
        say("warning", f"Claude Code ignores user hooks here; add the guard to {MANAGED_CLAUDE} as root")
        return None
    path = HOME / ".claude" / "settings.json"
    data = load(path) or {}
    if has_guard(data):
        return None
    data.setdefault("hooks", {}).setdefault("PreToolUse", []).append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": command("claude"), "timeout": 5}]})
    return path, data


def managed_claude_settings():
    """config/claude-settings.json, with keys from hosts/<host>/claude-settings.json replacing it."""
    managed = json.loads(CLAUDE_SETTINGS.read_text())
    host = HOST_CONF.resolve().parent / "claude-settings.json" if HOST_CONF.exists() else None
    if host and host.is_file():
        managed.update(json.loads(host.read_text()))
    return {k: v for k, v in managed.items() if not k.startswith("$")}


def merged(data, managed):
    """The managed values, with each MERGED_KEYS dict laid over the one already in data."""
    return {k: {**data.get(k, {}), **v} if k in MERGED_KEYS else v for k, v in managed.items()}


def claude_settings():
    path = HOME / ".claude" / "settings.json"
    data = load(path) or {}
    managed = merged(data, managed_claude_settings())
    changed = [k for k, v in managed.items() if data.get(k) != v]
    if "includeCoAuthoredBy" in data:  # deprecated; attribution replaces it
        changed.append("includeCoAuthoredBy")
    if not changed:
        return None
    data.update(managed)
    data.pop("includeCoAuthoredBy", None)
    return path, data, {"keys": ", ".join(changed)}


def codex():
    if not (HOME / ".codex").is_dir():
        return None
    path = HOME / ".codex" / "hooks.json"
    data = load(path) or {}
    if has_guard(data):
        return None
    data.setdefault("hooks", {}).setdefault("PreToolUse", []).append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": command("codex"), "timeout": 5,
                                       "statusMessage": "Checking shared CPU queue"}]})
    return path, data


def cursor():
    if not (HOME / ".cursor").is_dir():
        return None
    path = HOME / ".cursor" / "hooks.json"
    data = load(path) or {"version": 1}
    if has_guard(data):
        return None
    data.setdefault("hooks", {}).setdefault("beforeShellExecution", []).append(
        {"command": command("cursor"), "timeout": 5})
    return path, data


def retired(group):
    commands = [h.get("command", "") for h in group.get("hooks", [group])]
    return bool(commands) and all(any(m in c for m in RETIRED_HOOKS) for c in commands)


def codex_cleanup():
    """Drop Codex hook groups that only run retired skills' scripts."""
    path = HOME / ".codex" / "hooks.json"
    data = load(path)
    if not data:
        return None
    hooks, changed, shifted = data.get("hooks", {}), False, False
    for event in list(hooks):
        kept = [g for g in hooks[event] if not retired(g)]
        if len(kept) != len(hooks[event]):
            changed = True
            # Codex keys trust by position; a removal before a kept group moves it.
            first = next(i for i, g in enumerate(hooks[event]) if retired(g))
            shifted |= any(hooks[event].index(g) > first for g in kept)
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if not changed:
        return None
    if shifted:
        say("note", "Codex: a kept hook moved position; open /hooks once to re-trust it")
    return path, data


def main(argv):
    backup, apply = Path(argv[0]), "--apply" in argv
    plans = (("Claude Code", claude), ("Claude settings", claude_settings), ("Codex", codex),
             ("Codex cleanup", codex_cleanup), ("Cursor", cursor))
    for agent, plan in plans:
        change = plan()
        if not change:
            continue
        path, data, *details = change
        verb, text = MESSAGES[agent]
        say(verb, text.format(short(path), path=short(path), **(details[0] if details else {})))
        if not apply:
            continue
        saved = backup / path.relative_to(HOME)
        if path.exists() and not saved.exists():  # keep the original when two plans touch one file
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".fleet-tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        temporary.replace(path)
        if agent == "Codex":
            say("note", "Codex: open /hooks once to review and trust the new hook")


if __name__ == "__main__":
    main(sys.argv[1:])
