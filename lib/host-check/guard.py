"""Catch common unqueued validation commands, development servers, PR merges
that squash or rebase (merge_method.py), and agent commits that put a
file over the size cap (commit_guard.py).

    python3 guard.py [claude|codex|cursor|opencode] < hook-payload.json

Each check judges the leaves of the command walk (walk.py). A leaf the walk
can see, and host-check does not already run, needs the queue when the
validation catalogue (jobclass.py) gives it a job class other than none.
Opaque leaves are never queued (docs/adr/0002), a script or gate that queues
itself is left to queue, and background fan-out is judged per job by
host-check only. Not a shell security boundary: it recognizes the common
spellings.
Package scripts (`pnpm review:coverage`, `pnpm --filter X test`, `pnpm web
build`) are resolved to their bodies through the nearest package.json and the
workspace, and shell script files (`bash gates.sh`, `./gates.sh`) are read, so
both are judged by the commands they run. Script names remain the fallback.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "file-size")]
import commit_guard  # noqa: E402
import hostconf  # noqa: E402
import merge_method  # noqa: E402
from jobclass import PACKAGE_RUNNERS, RUNNERS, leaf_class, queues_itself  # noqa: E402
from walk import HELP, leaves  # noqa: E402

REASON = (
    f"Shared CPU queue: run validation through {hostconf.HOST_CHECK}. "
    "For a pipeline, use host-check bash -lc 'pnpm lint && pnpm test'. "
    f"Read {hostconf.HOST_VALIDATION}; wait for the queue instead of bypassing it."
)
DEV_REASON = (
    "Development servers are not allowed on this host: they compile on demand and burn CPU the "
    "host does not have. {route} "
    "Gate scripts that boot a dev server (a11y-pages.ts, smoke-local.ts) need A11Y_BASE_URL "
    f"pointing at a production server. See {hostconf.HOST_VALIDATION} for this host's preview workflow."
)
# Where to look at a branch instead: the worktree preview command on hosts with recipes for it.
PREVIEW_ROUTE = (
    "To browse a worktree, run preview-worktree start in it: it builds through host-check and serves "
    "that build on a loopback port for the T3 browser."
)
SERVE_ROUTE = "Build once and serve production: host-check pnpm build, then next start."
DEV_TASK = re.compile(r"^dev([:.-].*)?$")
# Gate scripts that boot `next dev` themselves unless given a server.
DEV_BOOTING_SCRIPTS = {"a11y-pages.ts", "smoke-local.ts"}


def dev_reason():
    route = PREVIEW_ROUTE if os.path.exists(hostconf.previews_path()) else SERVE_ROUTE
    return DEV_REASON.format(route=route)


def command_starts_dev(leaf):
    """A dev server: `next dev`, a `dev` package script, bare `vite`, or a gate script that boots one."""
    words = leaf.words
    name = os.path.basename(words[0])
    args = words[1:]
    if args and all(arg in HELP for arg in args):
        return False
    return boots_dev_server(words, leaf.env) or names_dev_server(name, args)


def boots_dev_server(words, env):
    """A runner on a gate script that boots one: a11y-pages honors A11Y_BASE_URL; smoke-local always finds its own."""
    for i, word in enumerate(words):
        if os.path.basename(word) not in RUNNERS:
            continue
        script = os.path.basename(next((a for a in words[i + 1:] if not a.startswith("-")), ""))
        if script == "smoke-local.ts" or (script in DEV_BOOTING_SCRIPTS and "A11Y_BASE_URL" not in env):
            return True
    return False


def names_dev_server(name, args):
    if name in PACKAGE_RUNNERS:
        return any(DEV_TASK.fullmatch(arg) for arg in args)
    if name in {"next", "nuxt", "astro", "remix", "svelte-kit"}:
        return "dev" in args
    if name == "vite":
        return not args or args[0] in {"dev", "serve"} or args[0].startswith("-")
    if name == "webpack":
        return "serve" in args
    return name in {"webpack-dev-server", "react-scripts"} and (name != "react-scripts" or "start" in args)


# --- Queue detection ----------------------------------------------------------


def self_queued_scripts(found):
    """The scripts that call host-check themselves, such as njhomes-page-gates, so queue their own work."""
    return {script for leaf in found if (script := queueing_script(leaf.via))}


def queueing_script(via):
    """The innermost script around a host-check wrapper in a leaf's via, or None."""
    script = None
    for kind, name in via:
        if kind == "script":
            script = name
        elif (kind, name) == ("wrapper", "host-check") and script:
            return script
    return None


def queued(leaf, scripts):
    """Whether host-check already runs a leaf: directly, as a gate that queues itself, or through a script that does."""
    if ("wrapper", "host-check") in leaf.via or queues_itself(leaf.words):
        return True
    return any(step[0] == "script" and step[1] in scripts for step in leaf.via)


def leaves_need_queue(found):
    """Whether a leaf the walk can see, and host-check does not already run, has a job class other than none.

    Opaque leaves are heavy for the queue but never send a command to it: the
    guard does not deny what it cannot see (docs/adr/0002).
    """
    scripts = self_queued_scripts(found)
    return any(leaf_class(leaf) != "none" for leaf in found if not (leaf.opaque or queued(leaf, scripts)))


def needs_queue(command, cwd=None):
    """Whether a shell command runs validation that belongs in the host-check queue."""
    return leaves_need_queue(list(leaves(command, cwd or os.getcwd())))


def starts_dev(command, cwd=None):
    return any(command_starts_dev(leaf) for leaf in leaves(command, cwd or os.getcwd()) if not leaf.opaque)


def hook_cwd(payload, tool_input):
    """The directory the hooked command starts in."""
    for value in (tool_input.get("workdir"), tool_input.get("cwd"), payload.get("cwd")):
        if isinstance(value, str) and os.path.isabs(value):
            return value
    return os.getcwd()


def decision(payload):
    """(denied, reason) for the hooked shell command."""
    tool_input = payload.get("tool_input", payload)
    command = tool_input.get("command", tool_input.get("cmd"))
    if not isinstance(command, str):
        raise ValueError("missing shell command")
    cwd = hook_cwd(payload, tool_input)
    found = list(leaves(command, cwd))
    if merge_method.refuses(command, [leaf.words for leaf in found]):
        return True, merge_method.REASON
    if hostconf.load()["deny_dev_servers"] and any(command_starts_dev(leaf) for leaf in found if not leaf.opaque):
        return True, dev_reason()
    if leaves_need_queue(found):
        return True, REASON
    # A script's or package script's own leaf is the commands after it.
    refusal = commit_guard.commit_refusal([leaf for leaf in found if not leaf.expanded])
    return refusal is not None, refusal


def main():
    adapter = sys.argv[1] if len(sys.argv) > 1 else "claude"
    try:
        denied, reason = decision(json.load(sys.stdin))
    except (ValueError, TypeError, AttributeError) as exc:
        denied = True
        reason = "Host validation guard could not read the command: " + str(exc)
    if adapter == "cursor":
        result = {"permission": "deny" if denied else "allow"}
        if denied:
            result.update(user_message=reason, agent_message=reason)
        print(json.dumps(result))
    elif adapter == "opencode":
        if denied:
            print(reason, file=sys.stderr)
            return 2
    else:
        # No allow decision: preserve the tool's normal permission checks.
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }} if denied else {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
