"""Shell parsing for the host-check guard: heredocs and comments stripped,
`$(...)` substitutions split out, simple commands with the directory each runs
in, wrappers, `bg-job`, and `bash -c` strings unwrapped, and script files read.

Not a shell implementation: it recognizes the common spellings.
"""
import os
import re
import shlex

WRAPPERS = {"env", "nice", "timeout", "nohup", "setsid", "host-check", "time", "exec", "command"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*(\[[^]]*\])?\+?=")
# Words that precede the command itself; `$` is what is left of `$(`.
PREFIXES = {"!", "then", "do", "if", "elif", "else", "while", "until", "{", "$"}
SHELLS = {"bash", "sh", "zsh", "dash"}
# How far package scripts, shell strings, and script files are followed.
MAX_DEPTH = 6
MAX_SCRIPT_BYTES = 256 * 1024


def bg_job_command(args):
    """The command `bg-job start NAME -- COMMAND...` runs, or [] for its other verbs."""
    if len(args) < 2 or args[0] != "start":
        return []
    rest = args[2:]
    return rest[1:] if rest[:1] == ["--"] else rest


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


def shell_string_commands(args, here, depth):
    """The commands in the `-c` string of a shell invocation, up to MAX_DEPTH levels deep."""
    kind, code = shell_invocation(args)
    if kind != "string" or depth >= MAX_DEPTH:
        return
    yield from walk_unwrapped(code, here, depth + 1)


def unwrapped(words, here, depth):
    """The (command, directory) a simple command ends in, found past keywords, assignments, wrappers, and `bg-job`."""
    words = leading_command(words)
    name = os.path.basename(words[0]) if words else ""
    if name in WRAPPERS:
        yield from unwrapped(wrapped_command(words[1:]), here, depth)
    elif name == "bg-job":
        yield from unwrapped(bg_job_command(words[1:]), here, depth)
    elif name in SHELLS:
        yield from shell_string_commands(words[1:], here, depth)
    elif words:
        yield words, here


def walk_unwrapped(command, cwd, depth=0):
    """Each command a shell command runs, as (words, directory), and the commands in its `bash -c`
    strings, which start in the directory the shell runs in, so a `cd` inside one carries."""
    for words, here in walk(command, cwd):
        yield from unwrapped(words, here, depth)


def unwrapped_commands(command, depth=0):
    """Each command a shell command runs, as words, and the commands in its `bash -c` strings."""
    for words, _ in walk_unwrapped(command, os.getcwd(), depth):
        yield words


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
