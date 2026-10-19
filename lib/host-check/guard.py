"""Catch common unqueued validation commands, development servers, PR merges
that squash or rebase (merge_method.py), and agent commits that put a
file over the size cap (commit_guard.py).

    python3 guard.py [claude|codex|cursor|opencode] < hook-payload.json

jobclass.py classifies host-check jobs with the same shell parsing.

Not a shell security boundary: it recognizes the common spellings. Package
scripts (`pnpm review:coverage`, `pnpm --filter X test`, `pnpm web build`) are
resolved to their bodies through the nearest package.json and the workspace,
and shell script files (`bash gates.sh`, `./gates.sh`) are read, so both are
judged by the commands they run. Script names remain the fallback.
"""
import functools
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "file-size")]
import commit_guard  # noqa: E402
import hostconf  # noqa: E402
import merge_method  # noqa: E402
from packages import expansions  # noqa: E402
from shell import (  # noqa: E402
    ASSIGNMENT, MAX_DEPTH, PREFIXES, SHELLS, WRAPPERS, bg_job_command, read_script, segments, shell_invocation,
    shell_script, unwrapped_commands, walk,
)

REASON = (
    f"Shared CPU queue: run validation through {hostconf.HOST_CHECK}. "
    "For a pipeline, use host-check bash -lc 'pnpm lint && pnpm test'. "
    f"Read {hostconf.HOST_VALIDATION}; wait for the queue instead of bypassing it."
)
DEV_REASON = (
    "Development servers are not allowed on this host: they compile on demand and burn CPU the "
    "host does not have. Build once and serve production: host-check pnpm build, then next start. "
    "Gate scripts that boot a dev server (a11y-pages.ts, smoke-local.ts) need A11Y_BASE_URL "
    f"pointing at a production server. See {hostconf.HOST_VALIDATION} for this host's preview workflow."
)
DEV_TASK = re.compile(r"^dev([:.-].*)?$")
# Gate scripts that boot `next dev` themselves unless given a server.
DEV_BOOTING_SCRIPTS = {"a11y-pages.ts", "smoke-local.ts"}
TASK = re.compile(r"^(build|test|lint|typecheck|type-check|check|format|fmt|bench|benchmark|verify|validate|precommit|pre-commit)([:.-].*)?$")
DIRECT = {"vitest", "jest", "tsc", "eslint", "oxlint", "prettier", "biome", "vue-tsc", "tsgo", "hyperfine"}
# Script runners, and the script paths that boot a Next server and a browser
# (axe page gates, smoke runs, visual and screenshot captures).
RUNNERS = {"tsx", "node", "ts-node", "vite-node", "bun", "deno"}
BROWSER_SCRIPT = re.compile(r"(^|/)(a11y|smoke|visual|screenshots?|shots|e2e|playwright)[^/]*(/|$)")
PLAYWRIGHT_RUNS = {"test", "screenshot", "pdf"}
# Benchmarks, perf harnesses, and throwaway debug harnesses, by file name.
BENCH_SCRIPT = re.compile(r"^(debug-|bench|perf)")
# Runner options that take a value, so the value is not mistaken for the script.
RUNNER_VALUE_OPTIONS = {"--import", "-r", "--require", "--loader", "--experimental-loader", "--env-file", "--tsconfig", "--conditions", "-C"}
# Words before a runner that still leave it in command position (`pnpm exec tsx x.ts`).
RUNNER_LEADS = {"exec", "dlx", "x", "npx", "bunx", "pnpm", "yarn", "run"}
HELP = {"--help", "-h", "--version", "-v"}


def runs_browser_script(words):
    """A runner followed by a browser-script path, or `playwright test`, anywhere in the words."""
    for i, word in enumerate(words):
        name = os.path.basename(word)
        rest = [arg for arg in words[i + 1:] if not arg.startswith("-")]
        if name in RUNNERS and rest and BROWSER_SCRIPT.search(rest[0]):
            return True
        if name == "playwright" and rest and rest[0] in PLAYWRIGHT_RUNS:
            return True
    return False


def command_starts_dev(words, command):
    """A dev server: `next dev`, a `dev` package script, bare `vite`, or a gate script that boots one."""
    words = list(words)
    while words and (re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", words[0]) or words[0] in {"!", "then", "do", "if", "elif"}):
        words.pop(0)
    if not words:
        return False
    name = os.path.basename(words[0])
    args = words[1:]
    if name in WRAPPERS:
        while args and (args[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", args[0]) or re.match(r"^\d+[smhd]?$", args[0])):
            args.pop(0)
        return command_starts_dev(args, command)
    if name == "bg-job":
        return command_starts_dev(bg_job_command(args), command)
    if name in {"bash", "sh", "zsh", "dash"}:
        for i, arg in enumerate(args[:-1]):
            if arg.startswith("-") and "c" in arg:
                return starts_dev(args[i + 1])
        return False
    if args and all(arg in {"--help", "-h", "--version", "-v"} for arg in args):
        return False
    for i, word in enumerate(words):
        script = next((a for a in words[i + 1:] if not a.startswith("-")), "")
        if os.path.basename(word) in RUNNERS and os.path.basename(script) in DEV_BOOTING_SCRIPTS:
            # a11y-pages honors A11Y_BASE_URL; smoke-local always finds its own server.
            if os.path.basename(script) == "smoke-local.ts" or "A11Y_BASE_URL=" not in command:
                return True
    if name in {"pnpm", "npm", "yarn", "bun", "npx", "bunx", "turbo", "nx"}:
        return any(DEV_TASK.fullmatch(arg) for arg in args)
    if name in {"next", "nuxt", "astro", "remix", "svelte-kit"}:
        return "dev" in args
    if name == "vite":
        return not args or args[0] in {"dev", "serve"} or args[0].startswith("-")
    if name == "webpack":
        return "serve" in args
    return name in {"webpack-dev-server", "react-scripts"} and (name != "react-scripts" or "start" in args)


# --- Stored commands --------------------------------------------------------

DEFAULT_EXPANSION = re.compile(r"\$\{[A-Za-z_][A-Za-z_0-9]*:?[-=]([^}]*)\}")
# Command words worth classifying when a script stores a command in a string.
COMMAND_WORDS = (
    {"pnpm", "npm", "yarn", "bun", "npx", "bunx", "turbo", "nx", "make", "just", "next", "vite",
     "webpack", "rollup", "astro", "tsup", "playwright", "jest", "vitest"} | DIRECT | RUNNERS | SHELLS
)


def stored_commands(text):
    """Commands a script keeps in variables: `${CMD:-pnpm test}` defaults and `cmd="pnpm lint"`."""
    found = [m.group(1) for m in DEFAULT_EXPANSION.finditer(text)]
    for words in segments(text):
        found += [word.partition("=")[2] for word in words if ASSIGNMENT.match(word)]
    return [command for command in found if command.split() and os.path.basename(command.split()[0]) in COMMAND_WORDS]



# --- Script runners -----------------------------------------------------------


def runner_invocations(words):
    """Each script runner in command position: (its options, its positional arguments)."""
    for i, word in enumerate(words):
        name = os.path.basename(word)
        if name not in RUNNERS or (i and os.path.basename(words[i - 1]) not in RUNNER_LEADS):
            continue
        rest, options, j = words[i + 1:], [], 0
        while j < len(rest) and rest[j].startswith("-"):
            options.append(rest[j])
            j += 2 if rest[j] in RUNNER_VALUE_OPTIONS else 1
        positional = rest[j:]
        if name in {"bun", "deno"} and positional[:1] == ["run"]:
            positional = positional[1:]
        yield options, positional


def runs_queued_script(words):
    """`node --test`, or a runner on a benchmark, perf, or debug harness."""
    return any("--test" in options or (positional and BENCH_SCRIPT.match(os.path.basename(positional[0])))
               for options, positional in runner_invocations(words))


# --- Queue detection ----------------------------------------------------------


def guarded(check, command, cwd, depth, fallback):
    """Run a nested check, using the fallback for code shlex cannot parse."""
    try:
        return check(command, cwd, depth)
    except ValueError:
        return fallback


@functools.lru_cache(maxsize=None)  # a script that runs another many times reads it once
def file_needs_queue(path, cwd, depth):
    text = read_script(path, cwd) if depth < MAX_DEPTH else None
    if text is None:
        return False
    try:
        codes = [text] + stored_commands(text)
        # Scripts such as njhomes-page-gates queue their own work.
        if any(os.path.basename(word) == "host-check" for words in segments(text) for word in words):
            return False
    except ValueError:
        return False
    return any(guarded(needs_queue, code, cwd, depth + 1, False) for code in codes)


def command_needs_queue(words, cwd=None, depth=0):
    cwd = cwd or os.getcwd()
    words = list(words)
    while words and (ASSIGNMENT.match(words[0]) or words[0] in PREFIXES | {"time", "exec", "command"}):
        words.pop(0)
    if not words:
        return False
    name = os.path.basename(words[0])
    args = words[1:]
    if name == "host-check":
        return False
    if name == "bg-job":
        return command_needs_queue(bg_job_command(args), cwd, depth)
    if name in {"env", "nice", "timeout", "nohup"}:
        while args and (args[0].startswith("-") or ASSIGNMENT.match(args[0]) or re.match(r"^\d+[smhd]?$", args[0])):
            args.pop(0)
        return command_needs_queue(args, cwd, depth)
    if name in SHELLS:
        kind, value = shell_invocation(args)
        if kind == "string":
            return needs_queue(value, cwd, depth + 1)
        return kind == "file" and file_needs_queue(value, cwd, depth)
    if name in {"source", "."}:
        return bool(args) and file_needs_queue(args[0], cwd, depth)
    if args and all(arg in HELP for arg in args):
        return False
    script = shell_script(words[0], cwd)
    if script and file_needs_queue(script, cwd, depth):
        return True
    if runs_browser_script(words) or runs_queued_script(words):
        return True
    if name in DIRECT:
        return True
    if name in {"pnpm", "npm", "yarn", "bun", "npx", "bunx", "turbo", "nx"}:
        # Includes recursive/filter forms and named validation scripts.
        if any(TASK.fullmatch(arg) or os.path.basename(arg) in DIRECT for arg in args):
            return True
        return depth < MAX_DEPTH and any(guarded(needs_queue, body, directory, depth + 1, False)
                                         for body, directory in expansions(name, args, cwd))
    if name in {"next", "vite", "webpack", "rollup", "astro"}:
        return "build" in args or "check" in args or "lint" in args
    if name in {"make", "just"}:
        return any(TASK.fullmatch(arg) for arg in args)
    return False


def needs_queue(command, cwd=None, depth=0):
    """Whether a shell command runs validation that belongs in the host-check queue."""
    return any(command_needs_queue(words, here, depth) for words, here in walk(command, cwd or os.getcwd()))


def starts_dev(command):
    return any(command_starts_dev(segment, command) for segment in segments(command))


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
    if merge_method.refuses(command, unwrapped_commands(command)):
        return True, merge_method.REASON
    if hostconf.load()["deny_dev_servers"] and starts_dev(command):
        return True, DEV_REASON
    cwd = hook_cwd(payload, tool_input)
    if needs_queue(command, cwd):
        return True, REASON
    refusal = commit_guard.commit_refusal(walk(command, cwd))
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
