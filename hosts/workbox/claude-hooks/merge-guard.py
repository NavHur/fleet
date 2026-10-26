"""Hold PR merges until Pedro approves them.

PreToolUse on Bash denies `gh pr merge`, `gh stack merge`, and REST
`PUT .../pulls/N/merge` unless Pedro approved every PR number the command names,
in one of two ways:

- his latest chat message says "merge" and names each number ("merge 652 653 654"),
  with no negation such as "don't" or "wait"; or
- `allow-merge <N>...`, run from an interactive terminal, left a live approval in
  APPROVALS.

Chat approval is read from the session transcript and applies only on the main
thread; subagents must hand merges back. Claude Code and Codex both run this hook.
A Codex call carries `turn_id`, and its transcript is the thread's rollout JSONL
(found by session_id when transcript_path is empty). A Codex thread counts as a
subagent when Codex spawned it, it came from `codex exec`, or its first message is
a T3 brief ("Act as the review sub-agent for this task."). An "ask" decision is not used because
T3 runs sessions in bypassPermissions and approves it without showing a prompt.
GraphQL merge mutations, `gh api .../merges`, and curl merge calls are denied
outright: they don't name PRs by number. PreToolUse on file tools, and on Bash,
denies touching the approvals and transcripts. Draft-to-ready changes are not
gated, nor is `--help`. Catches common forms only; this is a habit guard, not a security boundary.
"""
import glob
import importlib.util
import json
import os
import re
import sys
import time

APPROVALS = os.path.expanduser("~/.local/state/merge-approvals")
TRANSCRIPTS = os.path.expanduser("~/.claude/projects")
GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-cli-guard.py")
MUTATIONS = re.compile(r"\b(mergePullRequest|enablePullRequestAutoMerge|enqueuePullRequest|mergeBranch)\b")
PR_URL = re.compile(r"/pull/(\d+)")
MERGE_PATH = re.compile(r"pulls/(\d+)/merge\b")
NEGATION = re.compile(r"\b(don'?t|do not|never|not yet|wait|hold|stop|no)\b", re.I)
NOT_HUMAN = ("<task-notification", "<local-command", "<command-name>", "<command-message>")
HELP = {"-h", "--help"}
USE_GH = "use `gh pr merge <N> --merge` or `gh stack merge <N> --yes --merge`"
CODEX_SESSIONS = os.path.expanduser("~/.codex/sessions")
# T3 notices and context injections that Codex records as user messages.
CODEX_NOT_HUMAN = ("Delegated task ", "The user supplied replacement AGENTS.md guidance", "<")
CODEX_T3_BRIEF = re.compile(r"\s*Act as the [\w-]+ sub-agent for this task\.")
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$", re.M)

spec = importlib.util.spec_from_file_location("agent_cli_guard", GUARD)
agent_cli_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_cli_guard)


def approved_in_terminal(number):
    try:
        with open(os.path.join(APPROVALS, str(number))) as f:
            return float(f.read().strip()) > time.time()
    except (OSError, ValueError):
        return False


def last_human_message(transcript_path):
    """Return the text of Pedro's latest chat message, or None."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4_000_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        attachment = entry.get("attachment") or {}
        if entry.get("type") == "attachment" and attachment.get("type") == "queued_command" \
                and attachment.get("commandMode") == "prompt":
            content = attachment.get("prompt")  # A message Pedro sent mid-turn.
        elif entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta") \
                or entry.get("isCompactSummary") or entry.get("isVisibleInTranscriptOnly"):
            continue
        else:
            content = (entry.get("message") or {}).get("content")
        if isinstance(content, list):
            if any(isinstance(part, dict) and part.get("type") == "tool_result" for part in content):
                continue
            content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip() or content.lstrip().startswith(NOT_HUMAN):
            continue
        return content
    return None


def codex_rollout(payload):
    """Return the Codex rollout path for a Codex call, "" if it can't be found, or None for Claude."""
    path = payload.get("transcript_path")
    if isinstance(path, str) and os.path.basename(path).startswith("rollout-"):
        return path
    if "turn_id" not in payload:
        return None
    session = glob.escape(str(payload.get("session_id") or "")) or "-"
    found = glob.glob(os.path.join(CODEX_SESSIONS, "*", "*", "*", f"rollout-*-{session}.jsonl"))
    return max(found, key=os.path.getmtime) if found else ""


def codex_thread(rollout):
    """Return (is_subagent, latest human message or None) for a Codex rollout."""
    subagent, first, latest = False, None, None
    try:
        with open(rollout, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i == 0 and '"session_meta"' in line:
                    meta = (json.loads(line).get("payload") or {})
                    source = meta.get("source")
                    subagent = source == "exec" or meta.get("thread_source") == "subagent" \
                        or (isinstance(source, dict) and "subagent" in source)
                if '"UserMessage"' not in line:
                    continue
                item = (json.loads(line).get("payload") or {}).get("item") or {}
                if item.get("type") != "UserMessage":
                    continue
                text = " ".join(part.get("text", "") for part in item.get("content") or []
                                if isinstance(part, dict) and part.get("type") == "text")
                if first is None:
                    first = text
                if text.strip() and not text.lstrip().startswith(CODEX_NOT_HUMAN):
                    latest = text
    except (OSError, ValueError, TypeError, AttributeError):
        return False, None
    return subagent or bool(first and CODEX_T3_BRIEF.match(first)), latest


def approved_in_chat(numbers, message):
    if not message:
        return False
    text = re.sub(r"<t3_context.*?</t3_context>", "", message, flags=re.S)
    if not re.search(r"\bmerge\b", text, re.I) or NEGATION.search(text):
        return False
    return all(re.search(rf"(?<![\d.]){n}(?!\d)", text) for n in numbers)


def pr_numbers(args):
    numbers = []
    for arg in args:
        if re.fullmatch(r"#?\d+", arg):
            numbers.append(arg.lstrip("#"))
        elif match := PR_URL.search(arg):
            numbers.append(match.group(1))
    return numbers


def method(args):
    for i, arg in enumerate(args):
        if arg in {"-X", "--method"} and i + 1 < len(args):
            return args[i + 1].upper()
        if arg.startswith("--method="):
            return arg.split("=", 1)[1].upper()
        if arg.startswith("-X") and len(arg) > 2:
            return arg[2:].upper()
    return "GET"


def graphql_text(args):
    """Return inline query text plus any `query=@file` the call reads."""
    texts = list(args)
    for arg in args:
        if "=@" in arg:
            try:
                with open(os.path.expanduser(arg.split("=@", 1)[1])) as f:
                    texts.append(f.read())
            except OSError:
                pass
    return "\n".join(texts)


def classify(words):
    """Return ("gated", numbers), ("blocked", what), ("approval",), or None."""
    name, args = os.path.basename(words[0]), words[1:]
    if name == "allow-merge" or any(APPROVALS in os.path.expanduser(w) or "merge-approvals" in w for w in words):
        return ("approval",)
    if name != "gh":
        return None
    if args[:2] in (["pr", "merge"], ["stack", "merge"]):
        return classify_merge(args)
    if args[:1] == ["api"]:
        return classify_api(args[1:])
    return None


def classify_merge(args):
    """A `gh pr merge` or `gh stack merge` is gated unless it only asks for help."""
    if HELP & set(args):
        return None
    return "gated", pr_numbers(args[2:])


def classify_api(rest):
    """Classify the arguments after `gh api`: merge mutations, PUT pulls/N/merge, REST merges."""
    if "graphql" in rest and MUTATIONS.search(graphql_text(rest)):
        return "blocked", "a GraphQL merge mutation"
    if method(rest) == "PUT" and (match := next(filter(None, map(MERGE_PATH.search, rest)), None)):
        return "gated", [match.group(1)]
    if any(re.search(r"repos/[^/\s]+/[^/\s]+/merges\b", a) for a in rest) and method(rest) != "GET":
        return "blocked", "a branch merge through the REST merges endpoint"
    return None


def bash_reason(command, payload):
    if "api.github.com" in command and (MERGE_PATH.search(command) or "/merges" in command or MUTATIONS.search(command)):
        return f"Merging through curl is off limits; {USE_GH} once Pedro approves."
    if "gh" in command and "graphql" in command and MUTATIONS.search(command):
        return f"GraphQL merge mutations are off limits because they name PRs by node ID; {USE_GH} once Pedro approves."
    message = None
    cwd = agent_cli_guard.hook_cwd(payload, payload.get("tool_input") or {})
    for words, _ in agent_cli_guard.segments(command, cwd):
        hit = classify(words)
        if not hit:
            continue
        if hit[0] == "approval":
            return ("Merge approvals belong to Pedro alone. Don't run allow-merge or read or write "
                    f"{APPROVALS}; ask Pedro to approve the merge in chat.")
        if hit[0] == "blocked":
            return f"This command runs {hit[1]}, which is off limits; {USE_GH} once Pedro approves."
        numbers = hit[1]
        if not numbers:
            return f"Name the PR number explicitly ({USE_GH}) so the merge guard can check Pedro's approval."
        missing = [n for n in numbers if not approved_in_terminal(n)]
        if not missing:
            continue
        rollout = codex_rollout(payload)
        subagent, codex_message = codex_thread(rollout) if rollout is not None else (False, None)
        if payload.get("agent_id") or subagent:
            return ("Subagents can't merge. Report back to the main thread, which asks Pedro to approve "
                    f"merging PR {', '.join('#' + n for n in missing)}.")
        if message is None:
            message = (codex_message if rollout is not None
                       else last_human_message(payload.get("transcript_path"))) or ""
        if not approved_in_chat(missing, message):
            listed = " ".join(missing)
            return (f"Pedro hasn't approved merging PR {', '.join('#' + n for n in missing)} in his latest "
                    "message; earlier chat about merging doesn't count. Stop and end your turn: tell Pedro exactly "
                    f"what the merge includes and why, and ask him to reply `merge {listed}`. After he does, retry "
                    "the same command. Don't look for another way to merge.")
    return None


def file_reason(path):
    real = os.path.realpath(os.path.expanduser(path))
    if real.startswith(APPROVALS):
        return f"Merge approvals belong to Pedro alone; don't edit files in {APPROVALS}."
    if real.startswith(TRANSCRIPTS) and real.endswith(".jsonl"):
        return "Session transcripts are read-only."
    return None


def codex_file_reason(path):
    real = os.path.realpath(os.path.expanduser(path))
    if real.startswith(CODEX_SESSIONS) and real.endswith(".jsonl"):
        return "Session transcripts are read-only."
    return None


def main():
    payload = json.load(sys.stdin)
    if payload.get("hook_event_name") != "PreToolUse":
        return 0
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command")
    if payload.get("tool_name") == "apply_patch":
        # Codex sends the patch text as `command`; check each file it touches.
        paths = [p.strip() for m in PATCH_PATH.finditer(str(command or "")) for p in m.groups() if p]
        reason = next(filter(None, (file_reason(p) or codex_file_reason(p) for p in paths)), None)
    elif isinstance(command, str):
        reason = bash_reason(command, payload)
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or ""
        reason = file_reason(path) if path else None
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
