"""Hold schema migrations on a shared database until Pedro approves them.

PreToolUse on Bash denies `prisma migrate deploy|dev|reset|resolve`, `prisma db
push`, and package scripts named `db:deploy`, `db:migrate`, `db:push`, or
`db:reset` (or whose body runs one of those), unless the database they target
is local or Pedro's latest chat message approves a migration ("I authorize the
migration", "migrate"), with no negation such as "don't" or "wait".

The target is DATABASE_URL or DIRECT_URL set inline in the command, else the
first .env.local or .env that sets one, from the directory the command runs in
up to /. localhost, 127.0.0.1, ::1, and socket URLs are local; anything else,
or no URL at all, counts as shared. Some work worktrees point at the
production database, so a migration there is a production change.

Chat approval applies only on the main thread; subagents hand migrations back.
Claude Code and Codex both run this hook, through merge-guard.py's transcript
readers. The shell scripts and package scripts a command runs are read with
fleet's command walk (lib/host-check/walk.py); helpers in other languages that
migrate internally, such as test-database and preview deploy helpers, are not
seen. A habit guard, not a security boundary.
"""
import importlib.util
import itertools
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HOOKS = os.path.dirname(os.path.abspath(__file__))
# This file is linked from ~/.claude/hooks; the fleet repo it lives in has host-check.
HOST_CHECK = str(Path(os.path.realpath(__file__)).parents[3] / "lib" / "host-check")
PRISMA_WRITES = {("migrate", "deploy"), ("migrate", "dev"), ("migrate", "reset"), ("migrate", "resolve"), ("db", "push")}
SCRIPT_NAME = re.compile(r"db:(deploy|migrate|push|reset)(:[\w-]+)?")
RAW_MIGRATION = re.compile(r"prisma\s+(migrate\s+(deploy|dev|reset|resolve)|db\s+push)|\bdb:(deploy|migrate|push|reset)\b")
INLINE_URL = re.compile(r"\b(?:DATABASE_URL|DIRECT_URL)=(\"[^\"]*\"|'[^']*'|[^\s;&|]+)")
ENV_LINE = re.compile(r"^\s*(?:export\s+)?(?:DATABASE_URL|DIRECT_URL)\s*=\s*(.*?)\s*$", re.M)
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
RUNNERS = {"pnpm", "npm", "yarn", "bun", "npx", "bunx", "turbo"}
HELP = {"-h", "--help"}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, HOST_CHECK)  # guard.py imports hostconf beside it
guard = load("host_check_guard", os.path.join(HOST_CHECK, "guard.py"))
from walk import leaves  # noqa: E402
merge_guard = load("merge_guard", os.path.join(HOOKS, "merge-guard.py"))


def runs_prisma_write(words):
    return any(os.path.basename(word) == "prisma" and tuple(words[i + 1:i + 3]) in PRISMA_WRITES
               for i, word in enumerate(words))


def migrates(words):
    """A prisma write, or a package script named for a migration; the walk also yields the body it runs."""
    if HELP & set(words):
        return False
    script = os.path.basename(words[0]) in RUNNERS and any(SCRIPT_NAME.fullmatch(arg) for arg in words[1:])
    return script or runs_prisma_write(words)


def migration_dirs(command, cwd):
    """Each directory a migration in the command runs from, through wrappers, shells, scripts, and package scripts."""
    found = list(leaves(command, cwd))
    return [d for i, leaf in enumerate(found) if migrates(leaf.words) for d in leaf_dirs(leaf, found[i + 1:])]


def leaf_dirs(leaf, after):
    """A runner the walk expanded is left to its body when that migrates, else held in the packages it ran in."""
    if not leaf.expanded:
        return [leaf.cwd]
    depth = len(leaf.via)
    body = list(itertools.takewhile(lambda inner: len(inner.via) > depth and inner.via[:depth] == leaf.via, after))
    if any(migrates(inner.words) for inner in body):
        return []
    return sorted({inner.via[depth][1] for inner in body if inner.via[depth][0] == "package"}) or [leaf.cwd]


def file_urls(directory):
    """The database URLs set in a directory's .env.local, else its .env."""
    for name in (".env.local", ".env"):
        try:
            urls = ENV_LINE.findall(Path(directory, name).read_text())
        except OSError:
            continue
        if urls:
            return urls
    return []


def env_urls(directory):
    """The database URLs in the nearest .env.local or .env that sets one, from directory up."""
    start = Path(directory)
    return next(filter(None, map(file_urls, [start, *start.parents])), [])


def is_local(url):
    parts = urlsplit(url.strip().strip("\"'"))
    socket = parse_qs(parts.query).get("host", [""])[0].startswith("/")
    return (parts.hostname or "") in LOCAL_HOSTS or socket


def describe(directory, urls):
    """The shared database among urls, or None when all are local."""
    if not urls:
        return f"an unknown database (no DATABASE_URL in {directory} or above)"
    remote = next((u for u in urls if not is_local(u)), None)
    return remote and (urlsplit(remote.strip("\"'")).hostname or "a remote database")


def shared_target(command, directories):
    """The shared database the migration would hit, or None when every target is local."""
    inline = INLINE_URL.findall(command)
    targets = [("the command", inline)] if inline else [(d, env_urls(d)) for d in directories]
    return next(filter(None, (describe(d, urls) for d, urls in targets)), None)


def approved_in_chat(message):
    if not message:
        return False
    text = re.sub(r"<t3_context.*?</t3_context>", "", message, flags=re.S)
    return bool(re.search(r"\bmigrat", text, re.I)) and not merge_guard.NEGATION.search(text)


def latest_message(payload):
    """(is_subagent, Pedro's latest message) for Claude Code or Codex."""
    rollout = merge_guard.codex_rollout(payload)
    if rollout is not None:
        subagent, message = merge_guard.codex_thread(rollout)
        return subagent, message
    return bool(payload.get("agent_id")), merge_guard.last_human_message(payload.get("transcript_path"))


def reason(command, payload):
    cwd = guard.hook_cwd(payload, payload.get("tool_input") or {})
    try:
        directories = migration_dirs(command, cwd)
    except ValueError:
        directories = [cwd] if RAW_MIGRATION.search(command) else []
    if not directories:
        return None
    target = shared_target(command, directories)
    if not target:
        return None
    subagent, message = latest_message(payload)
    if subagent:
        return (f"Subagents can't run migrations against {target}. Report back to the main thread, "
                "which asks Pedro to approve the migration.")
    if approved_in_chat(message):
        return None
    return (f"This migrates {target}, which is shared and may be production. "
            "Pedro's latest message doesn't approve a migration. Stop and end your turn: tell him which "
            "migrations would apply and what they change, and ask him to reply `migrate`. After he does, "
            "retry the same command. Use a local database for anything else.")


def main():
    payload = json.load(sys.stdin)
    command = (payload.get("tool_input") or {}).get("command")
    if payload.get("hook_event_name") != "PreToolUse" or not isinstance(command, str):
        return 0
    denial = reason(command, payload)
    if denial:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": denial,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
