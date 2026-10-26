"""Shell lexing for the command walk (walk.py): heredocs and comments
stripped, `$(...)` substitutions split out, simple commands lexed into
segments, the arguments of a shell invocation read, and script files found
and read.

Not a shell implementation: it recognizes the common spellings.
"""
import os
import re
import shlex
from typing import NamedTuple

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*(\[[^]]*\])?\+?=")
# Words that precede the command itself; `$` is what is left of `$(`.
PREFIXES = {"!", "then", "do", "if", "elif", "else", "while", "until", "{", "$"}
SHELLS = {"bash", "sh", "zsh", "dash"}
MAX_SCRIPT_BYTES = 256 * 1024


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


def commands(command):
    """Each simple command as a Segment; commands inside `$(...)` come first, marked subshell."""
    command, bodies = split_substitutions(strip_comments(strip_heredocs(command)))
    for body in bodies:
        yield from (segment._replace(subshell=True) for segment in commands(body))
    yield from simple_commands(command)


class Segment(NamedTuple):
    """A simple command's words, whether it runs inside `$(...)`, and whether a lone `&` ends it."""
    words: list
    subshell: bool = False
    background: bool = False


SEPARATOR = ";&|()\n"
# A lone `&`, not `&&`, `|&`, or a redirection's `>&`.
BACKGROUND = re.compile(r"(?<![&|])&(?!&)")


def is_separator(token):
    return bool(token) and all(char in SEPARATOR for char in token)


def lexed(command):
    """The command's words and separators; shlex splits `2>&1` and `&>log` at the `&`, so they are rejoined."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SEPARATOR)
    lexer.commenters = ""
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    tokens = list(lexer)
    out, i = [], 0
    while i < len(tokens):
        token, after = tokens[i], tokens[i + 1] if i + 1 < len(tokens) else ""
        if token == "&" and out and out[-1].endswith((">", "<")) and after and not is_separator(after):
            out[-1] += "&" + after  # `2>&1`, `>&2`
            i += 1
        elif not (token == "&" and after.startswith(">")):  # `&>log` writes both streams to a file
            out.append(token)
        i += 1
    return out


def paren_change(token):
    return token.count("(") - token.count(")") if is_separator(token) else 0


def without_arrays(tokens):
    """The tokens with each `NAME=(...)` array's elements replaced by `;`, which ends the assignment."""
    out, depth = [], 0
    for token in tokens:
        opens = not depth and is_separator(token) and token.startswith("(") and out and ARRAY_START.match(out[-1])
        if not (depth or opens):
            out.append(token)
            continue
        depth = max(depth + paren_change(token), 0)
        if not depth:
            out.append(";")
    return out


def simple_commands(command):
    """Each simple command as a Segment, without redirections or `NAME=(...)` array elements."""
    segment = []
    for token in without_arrays(lexed(command)):
        if is_separator(token):
            yield Segment(without_redirects(segment), background=bool(BACKGROUND.search(token)))
            segment = []
        else:
            segment.append(token)
    yield Segment(without_redirects(segment))


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
