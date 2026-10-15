"""Route coding-agent work through T3 tasks or supported native subagents.

The parser remains available to agents audit for historical CLI-run evidence.
This is a habit guard, not a security boundary. MCP transport, normal shell
commands, and provider maintenance commands are not agent launches.
"""
import json
import os
import re
import shlex
import sys

MUSE_SHIM = "/home/ubuntu/.local/bin/muse-delegate"
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\1")
HELP = {"--help", "-h", "help", "--version", "-v"}
CLI_NAMES = {"opencode": "muse", "codex": "codex", "cursor-agent": "cursor", "claude": "claude"}


def strip_heredocs(command):
    """Drop heredoc bodies: briefs are prose, and their quotes break shlex."""
    kept, pending = [], []
    for line in command.split("\n"):
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        kept.append(line)
        pending = [m.group(2) for m in HEREDOC.finditer(line.replace("<<<", "   "))]
    return "\n".join(kept)


def segments(command, detached=False):
    """Yield (words, detached) per simple command; detached means it ends in a lone `&`."""
    lexer = shlex.shlex(strip_heredocs(command), posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    segment = []
    try:
        for token in lexer:
            if token and all(c in ";&|()\n" for c in token):
                yield from unwrap(segment, detached or ("&" in token and "&&" not in token))
                segment = []
            else:
                segment.append(token)
    except ValueError:
        return  # Unparseable: let the command through rather than guess.
    yield from unwrap(segment, detached)


def unwrap(words, detached):
    """Yield the effective command words, looking through wrappers and `bash -c`."""
    words = list(words)
    while words and (re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", words[0]) or words[0] in {"!", "then", "do", "if", "elif", "time", "exec", "command"}):
        words.pop(0)
    if not words:
        return
    name, args = os.path.basename(words[0]), words[1:]
    if name in {"env", "nice", "timeout", "nohup", "setsid", "stdbuf"}:
        while args and (args[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", args[0]) or re.match(r"^\d+[smhd]?$", args[0])):
            args.pop(0)
        yield from unwrap(args, detached)
    elif name in {"bash", "sh", "zsh", "dash"}:
        for i, arg in enumerate(args[:-1]):
            if arg.startswith("-") and "c" in arg:
                yield from segments(args[i + 1], detached)
                return
    else:
        yield words, detached


def find(command):
    """Return (kind, value, detached, words) for each agent CLI launch in a shell command."""
    return [(*hit, detached, words) for words, detached in segments(command) if (hit := classify(words))]


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
    found = find(command)
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
