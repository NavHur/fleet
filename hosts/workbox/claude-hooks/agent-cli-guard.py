"""Route coding-agent work through T3 tasks or supported native subagents.

Commands are read with fleet's command walk (lib/host-check/walk.py), so a
launch behind wrappers, `bash -c`, scripts, or package scripts is found.
segments() and find() remain available to agents audit for historical CLI-run
evidence.
This is a habit guard, not a security boundary. MCP transport, normal shell
commands, and provider maintenance commands are not agent launches.
"""
import json
import os
from pathlib import Path
import sys

MUSE_SHIM = "/home/ubuntu/.local/bin/muse-delegate"
HELP = {"--help", "-h", "help", "--version", "-v"}
CLI_NAMES = {"opencode": "muse", "codex": "codex", "cursor-agent": "cursor", "claude": "claude"}

# This file is linked from ~/.claude/hooks; the fleet repo it lives in has the command walk.
sys.path.insert(0, str(Path(os.path.realpath(__file__)).parents[3] / "lib" / "host-check"))
from walk import leaves  # noqa: E402


def segments(command, cwd=None):
    """Yield (words, detached) per command the walk finds; detached means it, or what runs it, ends in a lone `&`."""
    try:
        found = list(leaves(command, cwd or os.getcwd()))
    except ValueError:
        return  # Unparseable: let the command through rather than guess.
    for leaf in found:
        yield leaf.words, leaf.background


def find(command, cwd=None):
    """Return (kind, value, detached, words) for each agent CLI launch in a shell command."""
    return [(*hit, detached, words) for words, detached in segments(command, cwd) if (hit := classify(words))]


def classify(words):
    """Return ("direct", cli), ("launch", id or None), or None."""
    name, args = os.path.basename(words[0]), words[1:]
    if any(arg in HELP for arg in args):
        return None
    if name == "claude" and any(arg in {"-p", "--print"} for arg in args):
        return "direct", "claude"
    if (name == "opencode" and args[:1] == ["run"]) or (name == "codex" and args[:1] in (["exec"], ["e"])) \
            or (name == "cursor-agent" and any(arg in {"-p", "--print"} for arg in args)):
        return "direct", CLI_NAMES[name]
    if name.startswith("muse-delegate") and os.path.realpath(os.path.expanduser(words[0])) != MUSE_SHIM \
            and "/" in words[0]:
        return "copy", words[0]
    if (name == "agents" and args[:1] == ["run"]) or name == "muse-delegate":
        run_id = None
        for i, arg in enumerate(args):
            if arg == "--":
                break
            if arg == "--id" and i + 1 < len(args):
                run_id = args[i + 1]
            elif arg.startswith("--id="):
                run_id = arg[len("--id="):]
        return "launch", run_id
    return None


def pre_tool_use(payload, found):
    if os.environ.get("T3_SERVICE_LAUNCHER_CONTEXT") or os.environ.get("T3_ACP_MCP_NODE"):
        return ("Use T3 orchestrator v2: read /home/ubuntu/.config/t3-orchestration.md, "
                "select the live provider/model with orchestrator_capabilities, and launch "
                "an app-owned delegate_task with a complete brief. T3 delivers completion "
                "automatically; provider CLI runners and watcher agents are retired in T3.")
    return ("Use the available native subagent tool with the requested model and a complete brief. "
            "Read /home/ubuntu/.config/t3-orchestration.md for the non-T3 path. "
            "If that model cannot be selected, report the limitation instead of launching a provider CLI.")


def main():
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command")
    if not isinstance(command, str):
        return 0
    cwd = payload.get("cwd")
    found = find(command, cwd if isinstance(cwd, str) and os.path.isabs(cwd) else None)
    if not found:
        return 0
    event = payload.get("hook_event_name")
    if event == "PreToolUse":
        reason = pre_tool_use(payload, found)
        if reason:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
