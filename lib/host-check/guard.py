"""Catch common unqueued validation commands, development servers, and PR
merges that squash or rebase (merge_method.py).

    python3 guard.py [claude|codex|cursor|opencode] < hook-payload.json

jobclass.py classifies host-check jobs with the same shell parsing.

Not a shell security boundary: it recognizes the common spellings. Package
scripts (`pnpm review:coverage`, `pnpm --filter X test`, `pnpm web build`) are
resolved to their bodies through the nearest package.json and the workspace,
and shell script files (`bash gates.sh`, `./gates.sh`) are read, so both are
judged by the commands they run. Script names remain the fallback.
"""
import fnmatch
import functools
import glob
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import hostconf  # noqa: E402
import merge_method  # noqa: E402

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
WRAPPERS = {"env", "nice", "timeout", "nohup", "setsid", "host-check", "time", "exec", "command"}
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
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*(\[[^]]*\])?\+?=")
# Words that precede the command itself; `$` is what is left of `$(`.
PREFIXES = {"!", "then", "do", "if", "elif", "else", "while", "until", "{", "$"}
SHELLS = {"bash", "sh", "zsh", "dash"}
HELP = {"--help", "-h", "--version", "-v"}
GLOB = re.compile(r"[*?[]")
# How far package scripts, shell strings, and script files are followed.
MAX_DEPTH = 6
MAX_SCRIPT_BYTES = 256 * 1024


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


def bg_job_command(args):
    """The command `bg-job start NAME -- COMMAND...` runs, or [] for its other verbs."""
    if len(args) < 2 or args[0] != "start":
        return []
    rest = args[2:]
    return rest[1:] if rest[:1] == ["--"] else rest


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


# --- Shell source -----------------------------------------------------------

# A heredoc operator, not a `<<<` here-string, plus any descriptor that begins
# its word (`0<<EOF`, `'0<<EOF`) but not digits ending another word (`a1<<EOF`).
HEREDOC = re.compile(
    r"(?:(?<![^\s;|&('\"])(?<![<>]&)(?:\d+|\{[A-Za-z_][A-Za-z_0-9]*\}))?"
    r"(?<!<)<<-?\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\1"
)


def strip_heredocs(command):
    """Drop heredocs, such as subagent briefs; their apostrophes break shlex.

    The operator, body, and closing line all go, so a delimiter never reads as
    a command. A closing line that goes on, as `EOF'` ends a quoted `ssh` or
    `bash -c` argument, keeps what follows the delimiter.
    """
    kept, pending = [], []
    for line in command.split("\n"):
        line, pending = close_heredoc(line, pending)
        if line is None:
            continue
        kept.append(HEREDOC.sub("", line))
        pending = [m.group(2) for m in HEREDOC.finditer(line)]
    return "\n".join(kept)


def close_heredoc(line, pending):
    """Return the part of `line` outside heredoc bodies, or None, and the delimiters still open."""
    if not pending:
        return line, pending
    end = line.strip()
    if end == pending[0]:
        return None, pending[1:]
    if end.startswith((pending[0] + "'", pending[0] + '"')):
        return end[len(pending[0]):], []
    return None, pending


def strip_comments(command):
    """Drop shell comments and line continuations, keeping each newline.

    shlex ends a comment by swallowing its newline, which merged the next
    command into the commented one, and it read `#` inside a word as a comment.
    """
    out, quote, i = [], None, 0
    while i < len(command):
        char = command[i]
        if quote == "'":
            quote = None if char == "'" else quote
        elif char == "\\" and i + 1 < len(command):
            if command[i + 1] != "\n":
                out.append(command[i:i + 2])
            i += 2
            continue
        elif quote == '"':
            quote = None if char == '"' else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (not out or out[-1][-1] in " \t\r\n;&|()"):
            end = command.find("\n", i)
            i = len(command) if end < 0 else end
            continue
        out.append(char)
        i += 1
    return "".join(out)


REDIRECT = re.compile(r"^(\d*|&)(>>?|>\||<>?|<<<?-?)$")
ATTACHED_REDIRECT = re.compile(r"^(\d*|&)(>>?|<<?<?)\S")
ARRAY_START = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*\+?=$")


def without_redirects(words):
    """Drop `> FILE`, `2>/dev/null`, and the like, so a log path does not read as a test target."""
    kept, skip = [], False
    for word in words:
        if skip:
            skip = False
        elif REDIRECT.match(word):
            skip = True
        elif not ATTACHED_REDIRECT.match(word):
            kept.append(word)
    return kept


class Substituted(list):
    """A command's words from inside `$(...)`, which runs in a subshell."""


# The quote state after a quote character, keyed by (state before, character).
QUOTE_TOGGLES = {(None, "'"): "'", (None, '"'): '"', ("'", "'"): None, ('"', '"'): None}
PAREN_DEPTH = {"(": 1, ")": -1}


def shell_step(command, i, quote):
    """Read one unit at i: a character, an escape, or a whole `$(...)`. Return (end, quote after it)."""
    char = command[i]
    if (quote, char) in QUOTE_TOGGLES:
        return i + 1, QUOTE_TOGGLES[quote, char]
    if quote == "'":
        return i + 1, quote
    if char == "\\":
        return i + 2, quote
    if command.startswith("$(", i):
        return closing_paren(command, i + 1) + 1, quote
    return i + 1, quote


def closing_paren(command, start):
    """The index of the `)` closing the `(` at start; quotes inside open a new shell context."""
    depth, quote, i = 0, None, start
    while i < len(command):
        if quote is None:
            depth += PAREN_DEPTH.get(command[i], 0)
        if depth == 0:
            return i
        i, quote = shell_step(command, i, quote)
    raise ValueError("No closing parenthesis")


def split_substitutions(command):
    """The command with each `$(...)` replaced by a placeholder word, and the substituted bodies.

    shlex reads a quote inside `"$(...)"` as the end of the outer string; the
    shell starts a new quoting context there instead.
    """
    out, bodies, quote, i = [], [], None, 0
    while i < len(command):
        end, after = shell_step(command, i, quote)
        if command.startswith("$(", i) and end > i + 1:
            bodies.append(command[i + 2:end - 1])
            out.append("__substitution__")
        else:
            out.append(command[i:end])
        i, quote = end, after
    return "".join(out), bodies


def segments(command):
    """Each simple command's words; commands inside `$(...)` come first, as Substituted lists."""
    command, bodies = split_substitutions(strip_comments(strip_heredocs(command)))
    for body in bodies:
        yield from (Substituted(words) for words in segments(body))
    yield from simple_commands(command)


def simple_commands(command):
    """Each simple command's words, without redirections or `NAME=(...)` array elements."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.commenters = ""
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    segment, array = [], 0
    for token in lexer:
        punctuation = token and all(c in ";&|()\n" for c in token)
        if array:
            array += (token.count("(") - token.count(")")) if punctuation else 0
            if array <= 0:
                array = 0
                yield without_redirects(segment)
                segment = []
        elif punctuation and token.startswith("(") and segment and ARRAY_START.match(segment[-1]):
            array = token.count("(") - token.count(")")
            if array <= 0:
                array = 0
                yield without_redirects(segment)
                segment = []
        elif punctuation:
            yield without_redirects(segment)
            segment = []
        else:
            segment.append(token)
    yield without_redirects(segment)


VARIABLE = re.compile(r"^\$\{?([A-Za-z_][A-Za-z_0-9]*)\}?(.*)$")


def changes_directory(words):
    """`cd` and `pushd` do, except inside `$(...)`, which runs in a subshell."""
    return words[:1] in (["cd"], ["pushd"]) and not isinstance(words, Substituted)


def walk(command, cwd):
    """Each command's words with the directory it runs in.

    Follows `cd DIR`, and expands a command word set earlier by a plain
    assignment (`H=/path/host-check; "$H" pnpm lint`, `G="git -C dir"; $G log`).
    """
    variables = {}
    for words in segments(command):
        lead = 1 if words[:1] in (["export"], ["local"], ["declare"], ["readonly"]) else 0
        if words[lead:] and all(ASSIGNMENT.match(word) for word in words[lead:]):
            for word in words[lead:]:
                name, _, value = word.partition("=")
                if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
                    variables[name] = value
        start = next((i for i, word in enumerate(words) if not (ASSIGNMENT.match(word) or word in PREFIXES)), len(words))
        found = VARIABLE.match(words[start]) if start < len(words) else None
        if found and found.group(1) in variables:
            try:
                words = words[:start] + shlex.split(variables[found.group(1)] + found.group(2)) + words[start + 1:]
            except ValueError:
                pass
        yield words, cwd
        if changes_directory(words):
            target = next((word for word in words[1:] if not word.startswith("-")), "~")
            if "$" not in target:
                cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))


def shell_invocation(args):
    """What a shell runs: ("string", CODE) for -c, ("file", PATH), ("stdin", None), or ("noexec", None) for -n."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            i += 1
            break
        if arg in {"--rcfile", "--init-file"}:
            i += 2
        elif arg.startswith("--"):
            i += 1
        elif arg[:1] in {"-", "+"}:
            if "c" in arg[1:]:
                return "string", args[i + 1] if i + 1 < len(args) else ""
            if "n" in arg[1:] and arg[0] == "-":
                return "noexec", None
            i += 2 if arg[-1] in "oO" else 1  # -o pipefail, -euo pipefail
        else:
            break
    return ("file", args[i]) if i < len(args) else ("stdin", None)


DURATION = re.compile(r"^\d+[smhd]?$")
# Wrapper options that take the next argument as their value (`env -u NAME`, `timeout -s KILL 60`).
WRAPPER_VALUE_OPTIONS = {"-u", "-C", "-s", "-k", "-a", "--unset", "--chdir", "--signal", "--kill-after"}


def leading_command(words):
    """The words from the command itself, after assignments and keywords such as `then` and `!`."""
    start = next((i for i, word in enumerate(words) if not (ASSIGNMENT.match(word) or word in PREFIXES)), len(words))
    return words[start:]


def wrapped_command(args):
    """What a wrapper (`env`, `timeout 60`, `nice -n 5`) runs: its arguments after its options, assignments, and durations."""
    while args and (args[0].startswith("-") or ASSIGNMENT.match(args[0]) or DURATION.match(args[0])):
        args = args[2:] if args[0] in WRAPPER_VALUE_OPTIONS else args[1:]
    return args


def shell_string_commands(args, depth):
    """The commands in the `-c` string of a shell invocation, up to MAX_DEPTH levels deep."""
    kind, code = shell_invocation(args)
    if kind != "string" or depth >= MAX_DEPTH:
        return
    yield from unwrapped_commands(code, depth + 1)


def unwrapped(words, depth):
    """The command a simple command ends in, found past keywords, assignments, wrappers, and `bg-job`."""
    words = leading_command(words)
    name = os.path.basename(words[0]) if words else ""
    if name in WRAPPERS:
        yield from unwrapped(wrapped_command(words[1:]), depth)
    elif name == "bg-job":
        yield from unwrapped(bg_job_command(words[1:]), depth)
    elif name in SHELLS:
        yield from shell_string_commands(words[1:], depth)
    elif words:
        yield words


def unwrapped_commands(command, depth=0):
    """Each command a shell command runs, as words, and the commands in its `bash -c` strings."""
    for words, _ in walk(command, os.getcwd()):
        yield from unwrapped(words, depth)


def shell_script(word, cwd):
    """The path of a shell script run directly by path (`./gates.sh`), or None."""
    if "/" not in word or "$" in word or "node_modules/.bin/" in word:
        return None
    path = os.path.join(cwd, os.path.expanduser(word))
    if word.endswith(".sh"):
        return path
    try:
        with open(path, "rb") as handle:
            first = handle.readline(200)
    except OSError:
        return None
    return path if re.match(rb"#!\s*\S*/(env\s+)?(ba|z|da)?sh\b", first) else None


def read_script(path, cwd):
    """A script file's text, or None when it cannot be read as one."""
    try:
        with open(os.path.join(cwd, os.path.expanduser(path)), "rb") as handle:
            data = handle.read(MAX_SCRIPT_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_SCRIPT_BYTES or b"\0" in data:
        return None
    return data.decode("utf-8", "replace")


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


# --- Package scripts ----------------------------------------------------------


@functools.lru_cache(maxsize=None)
def manifest(directory):
    """The parsed package.json in a directory, or None."""
    try:
        with open(os.path.join(directory, "package.json")) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def scripts(directory):
    found = (manifest(directory) or {}).get("scripts")
    return found if isinstance(found, dict) else {}


def package_name(directory):
    name = (manifest(directory) or {}).get("name")
    return name if isinstance(name, str) else ""


def nearest_package(cwd):
    directory = os.path.abspath(cwd)
    while manifest(directory) is None:
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent
    return directory


def workspace_patterns(directory):
    """The package globs of a pnpm, npm, or yarn workspace rooted here, or None."""
    try:
        with open(os.path.join(directory, "pnpm-workspace.yaml")) as handle:
            text = handle.read()
    except OSError:
        found = (manifest(directory) or {}).get("workspaces")
        found = found.get("packages") if isinstance(found, dict) else found
        return [p for p in found if isinstance(p, str)] if isinstance(found, list) else None
    # Only the top-level `packages:` list matters, so no YAML parser is needed.
    patterns, inside = [], False
    for line in text.splitlines():
        if re.match(r"^packages\s*:", line):
            inside = True
        elif inside and (item := re.match(r"^\s*-\s*['\"]?([^'\"#\s]+)", line)):
            patterns.append(item.group(1))
        elif inside and line.strip() and not line[0].isspace():
            inside = False
    return patterns


@functools.lru_cache(maxsize=None)
def workspace(cwd):
    """(root, package directories) of the workspace containing cwd, or None."""
    directory = os.path.abspath(cwd)
    while (patterns := workspace_patterns(directory)) is None:
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent
    found = [directory]
    for pattern in patterns:
        if not pattern.startswith("!"):
            found += [os.path.normpath(match) for match in sorted(glob.glob(os.path.join(directory, pattern), recursive=True))
                      if manifest(os.path.normpath(match)) is not None]
    return directory, tuple(dict.fromkeys(found))


def selected(cwd, selectors, recursive):
    """Package directories a selection names (pnpm/turbo filters, npm/yarn workspaces); the nearest package by default."""
    found = workspace(cwd) if selectors or recursive else None
    if not found:
        home = nearest_package(cwd)
        return [home] if home else []
    root, directories = found
    members = [d for d in directories if d != root] or [root]
    chosen = []
    for selector in selectors:
        if selector.startswith("!"):
            continue
        if "[" in selector:
            return members  # changed-since selections: any package may run
        pattern = re.sub(r"^\.\.\.\^?|\^?\.\.\.$", "", selector).strip("{}")
        if pattern.startswith((".", "/")) or ("/" in pattern and not pattern.startswith("@")):
            path = os.path.normpath(os.path.join(cwd, pattern))
            chosen += [d for d in directories if fnmatch.fnmatch(d, path)]
        else:
            chosen += [d for d in directories if fnmatch.fnmatch(package_name(d), pattern)]
    return list(dict.fromkeys(chosen)) if selectors else members


# Value-taking options, then those that select packages, set the directory, or recurse.
MANAGER_OPTIONS = {
    "pnpm": ({"-F", "--filter", "--filter-prod", "-C", "--dir", "--reporter", "--workspace-concurrency", "--loglevel",
              "--test-pattern", "--changed-files-ignore-pattern", "--resume-from"},
             {"-F", "--filter", "--filter-prod"}, {"-C", "--dir"}, {"-r", "--recursive"}),
    "npm": ({"-w", "--workspace", "--prefix", "--loglevel", "--script-shell"},
            {"-w", "--workspace"}, {"--prefix"}, {"--workspaces", "-ws"}),
    "yarn": ({"--cwd"}, set(), {"--cwd"}, set()),
    "bun": ({"--cwd", "-F", "--filter"}, {"-F", "--filter"}, {"--cwd"}, set()),
}
RUN_VERBS = {"run", "run-script", "rum", "urn"}
SCRIPT_VERBS = {"test": "test", "t": "test", "tst": "test", "start": "start", "stop": "stop", "restart": "restart"}
EXEC_VERBS = {"pnpm": {"exec", "dlx"}, "npm": {"exec", "x"}, "yarn": {"exec", "dlx"}, "bun": {"x"}}
# Built-in commands that never name a package script.
BUILTINS = {
    "add", "install", "i", "ci", "update", "up", "upgrade", "remove", "rm", "uninstall", "link", "unlink",
    "import", "rebuild", "rb", "prune", "fetch", "patch", "patch-commit", "audit", "list", "ls", "ll",
    "outdated", "why", "licenses", "create", "init", "publish", "pack", "store", "root", "bin", "config",
    "c", "setup", "env", "deploy", "doctor", "server", "help", "info", "cache", "workspaces", "version",
    "set", "node", "approve-builds", "self-update", "login", "logout", "whoami", "view", "search",
}
TURBO_VALUE_OPTIONS = {"--concurrency", "--cache-dir", "--output-logs", "--log-order", "--env-mode", "--cache",
                       "--log-prefix", "--profile", "--ui", "--token", "--team", "--api", "--cwd"}


def manager_options(name, args, cwd, selectors, recursive):
    """Consume leading package-manager options: (rest, cwd, selectors, recursive)."""
    values, selects, directories, recursives = MANAGER_OPTIONS[name]
    selectors, i = list(selectors), 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        key, eq, value = args[i].partition("=")
        if key in values and not eq:
            value = args[i + 1] if i + 1 < len(args) else ""
            i += 1
        if key in selects:
            selectors.append(value)
        elif key in directories:
            cwd = os.path.join(cwd, os.path.expanduser(value))
        elif key in recursives:
            recursive = True
        i += 1
    return args[i:], cwd, selectors, recursive


def script_runs(name, args, cwd):
    """The commands `pnpm|npm|yarn|bun [OPTIONS] [run] SCRIPT [ARGS]` runs, each with its directory.

    Arguments are appended to the script body as the package manager does.
    `exec`, `dlx`, and pnpm or yarn names without a script run an executable.
    An unresolved script gives [], leaving its name to decide.
    """
    args, cwd, selectors, recursive = manager_options(name, args, cwd, [], False)
    if not args:
        return []
    verb, rest = args[0], args[1:]
    if name == "yarn" and verb == "workspace" and len(rest) >= 2:
        selectors, verb, rest = selectors + [rest[0]], rest[1], rest[2:]
    if verb in EXEC_VERBS[name]:
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return [(shlex.join(rest), d) for d in selected(cwd, selectors, recursive) or [cwd]] if rest else []
    if verb in RUN_VERBS:
        rest, cwd, selectors, recursive = manager_options(name, rest, cwd, selectors, recursive)
        if not rest:
            return []
        script, extra = rest[0], rest[1:]
    elif verb in SCRIPT_VERBS:
        script, extra = SCRIPT_VERBS[verb], rest
    elif name in {"npm", "bun"} or verb in BUILTINS:
        return []
    else:
        script, extra = verb, rest
    extra = extra[1:] if extra[:1] == ["--"] else extra
    suffix = "".join(" " + shlex.quote(arg) for arg in extra)
    runs = [(scripts(d)[script] + suffix, d) for d in selected(cwd, selectors, recursive)
            if isinstance(scripts(d).get(script), str)]
    if runs or selectors or recursive or verb in RUN_VERBS or verb in SCRIPT_VERBS or name not in {"pnpm", "yarn"}:
        return runs
    return [(shlex.join([script] + extra), cwd)]  # `pnpm vitest run` runs the executable


def turbo_runs(args, cwd):
    """The package scripts `turbo run TASK... [--filter X]` runs, each with its directory."""
    selectors, tasks, i = [], [], 0
    while i < len(args) and args[i] != "--":
        key, eq, value = args[i].partition("=")
        if key.startswith("-"):
            if (key in TURBO_VALUE_OPTIONS or key in {"-F", "--filter"}) and not eq:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if key in {"-F", "--filter"}:
                selectors.append(value)
            elif key == "--cwd":
                cwd = os.path.join(cwd, value)
        elif tasks or args[i] != "run":
            tasks.append(args[i])
        i += 1
    found = workspace(cwd)
    if not found:
        return []
    directories = selected(found[0], selectors, True)
    runs = []
    for task in tasks:
        package, _, task = task.rpartition("#")
        runs += [(scripts(d)[task], d) for d in directories
                 if isinstance(scripts(d).get(task), str) and package in {"", package_name(d)}]
    return runs


def expansions(name, args, cwd):
    """What a package runner runs, as (command, directory) pairs; [] when unknown."""
    if name in MANAGER_OPTIONS:
        return script_runs(name, args, cwd)
    if name == "turbo":
        return turbo_runs(args, cwd)
    if name in {"npx", "bunx"}:
        while args and args[0].startswith("-"):
            args = args[2:] if args[0] in {"-p", "--package"} else args[1:]
        return [(shlex.join(args), cwd)] if args else []
    return []


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
    return needs_queue(command, hook_cwd(payload, tool_input)), REASON


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
