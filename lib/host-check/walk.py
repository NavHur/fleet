"""The command walk: each command a shell string runs, as a Leaf with the
directory it runs in.

    leaves(command, cwd) -> Iterator[Leaf]

Every shell-command judge reads leaves: guard.py, jobclass.py,
merge_method.py, commit_guard.py, the pre-commit skill's ci_covers.py, and
the workbox hooks. The walk sees past keywords, assignments, wrappers
(`env -u NAME`, `timeout -s KILL 60`, `setsid`, `host-check`), exec runners
(`uv run`), `bg-job start`, and `bash -c` strings; follows `cd`; expands a
command word stored in a variable; and reads the shell scripts and package
scripts a command runs, up to MAX_DEPTH levels deep. What it cannot see into
is an opaque leaf. Not a shell implementation: it recognizes the common
spellings (docs/adr/0001-command-walk-recognizes-spellings.md).
"""
from __future__ import annotations

import dataclasses
import functools
import os
import re
import shlex

from packages import expansions
from shell import ASSIGNMENT, PREFIXES, SHELLS, commands, read_script, shell_invocation, shell_script

# How far shell strings, script files, and package scripts are followed.
MAX_DEPTH = 6
# Arguments that ask a command about itself, so it runs nothing it names.
HELP = {"--help", "-h", "--version", "-v"}
PACKAGE_RUNNERS = {"pnpm", "npm", "yarn", "bun", "npx", "bunx", "turbo"}


@dataclasses.dataclass(frozen=True)
class Leaf:
    """A command a shell string runs.

    words: the command and its arguments, past keywords and assignments.
    cwd: the directory it runs in.
    via: how the walk reached it, outermost first: ("wrapper", "host-check"), ("runner", "uv run"),
        ("shell", "bash") for a -c string, ("script", PATH), ("package", DIRECTORY).
    subshell: it runs inside `$(...)`.
    background: it, or the command that runs it, ends in a lone `&`.
    env: the assignments it sees: its prefixes, `env NAME=VALUE`, and those made before it.
    opaque: why the walk cannot see what it runs ("eval", "variable", "stdin", "unreadable",
        "unparseable", "too-deep"), or None.
    expanded: the leaves after it include what it runs: a script's commands, a package script's body.
    """
    words: list
    cwd: str
    via: tuple = ()
    subshell: bool = False
    background: bool = False
    env: dict = dataclasses.field(default_factory=dict)
    opaque: str | None = None
    expanded: bool = False


@dataclasses.dataclass(frozen=True)
class Frame:
    """What the leaves of one walk inherit from the command that started it."""
    via: tuple = ()
    env: tuple = ()
    subshell: bool = False
    background: bool = False
    depth: int = 0

    def inside(self, segment, variables):
        """The frame of one simple command, with the variables set before it."""
        return dataclasses.replace(self, env=self.env + tuple(variables.items()),
                                   subshell=self.subshell or segment.subshell,
                                   background=self.background or segment.background)

    def through(self, kind, name, assigned=None):
        """The frame past a wrapper or runner, with the assignments it makes."""
        return dataclasses.replace(self.assigning(assigned or {}), via=self.via + ((kind, name),))

    def assigning(self, assigned):
        return dataclasses.replace(self, env=self.env + tuple(assigned.items()))

    def deeper(self, kind, name):
        """The frame of a shell string, script, or package script this one runs."""
        return dataclasses.replace(self.through(kind, name), depth=self.depth + 1)

    def leaf(self, words, cwd, opaque=None, expanded=False):
        return Leaf(list(words), cwd, self.via, self.subshell, self.background, dict(self.env), opaque, expanded)


def leaves(command, cwd):
    """Each command a shell string runs, in order.

    Raises ValueError when shlex cannot parse the string or a `bash -c` string
    in it; text read from a script or package script that cannot be parsed is
    an opaque leaf instead.
    """
    return walk_text(command, cwd, Frame())


def walk_text(text, cwd, frame):
    for segment, words, here, variables in sequence(text, cwd):
        yield from follow(words, here, frame.inside(segment, variables))


def follow(words, cwd, frame):
    """The leaves one simple command ends in, past its keywords, assignments, wrappers, and runners."""
    words, assigned = command_part(words)
    if not words:
        return
    passed = passed_through(words, cwd)
    if passed:
        kind, name, command, here, made = passed
        yield from follow(command, here, frame.through(kind, name, {**assigned, **made}))
    else:
        yield from ends(words, cwd, frame.assigning(assigned))


def command_part(words):
    """The words from the command itself, past keywords such as `then` and `!`, and the assignments before it."""
    assigned, start = {}, 0
    while start < len(words) and (ASSIGNMENT.match(words[start]) or words[start] in PREFIXES):
        name, eq, value = words[start].partition("=")
        if eq:
            assigned[name.rstrip("+")] = value
        start += 1
    return words[start:], assigned


def passed_through(words, cwd):
    """(kind, name, command, directory, assignments) when the words start with a wrapper or runner, else None."""
    name = os.path.basename(words[0])
    if name in WRAPPERS and not (name == "command" and LOOKUPS & set(words[1:2])):
        return ("wrapper", name, *wrapped(name, words[1:], cwd))
    if name == "bg-job":
        return "wrapper", name, bg_job_command(words[1:]), cwd, {}
    verb = runner_verb(words)
    return ("runner", verb, *run_by(words, cwd), {}) if verb else None


def ends(words, cwd, frame):
    """The leaf a command is, then what it runs when it runs a shell string, a script, or a package script."""
    name, hidden = os.path.basename(words[0]), hidden_command(words)
    if hidden or (words[1:] and all(arg in HELP for arg in words[1:])):
        yield frame.leaf(words, cwd, opaque=hidden)
        return
    if name in SHELLS:
        yield from shell_leaves(words, cwd, frame)
        return
    path = script_path(words, cwd)
    if path:
        yield from script_leaves(words, path, cwd, frame)
    elif name in PACKAGE_RUNNERS:
        yield from package_leaves(words, cwd, frame)
    else:
        yield frame.leaf(words, cwd)


def hidden_command(words):
    """Why the command a command runs cannot be seen: `eval`, or a `$` word the walk could not expand."""
    if os.path.basename(words[0]) == "eval":
        return "eval"
    return "variable" if "$" in words[0] else None


def script_path(words, cwd):
    """The script `source FILE`, `. FILE`, or `./script.sh` runs, or None."""
    if words[0] in {"source", "."}:
        return words[1] if words[1:] else None
    return shell_script(words[0], cwd)


# --- Shell strings, scripts, and package scripts ---------------------------------

def shell_leaves(words, cwd, frame):
    """What a shell runs: its -c string, a script file, or stdin, which the walk cannot see."""
    kind, value = shell_invocation(words[1:])
    if kind == "string" and frame.depth >= MAX_DEPTH:
        yield frame.leaf(words, cwd, opaque="too-deep")
    elif kind == "string":
        yield from walk_text(value, cwd, frame.deeper("shell", os.path.basename(words[0])))
    elif kind == "file":
        yield from script_leaves(words, value, cwd, frame)
    else:
        yield frame.leaf(words, cwd, opaque="stdin" if kind == "stdin" else None)


def script_leaves(words, path, cwd, frame):
    """A script's own leaf, then its commands and the commands it stores in variables."""
    text = read_script(path, cwd) if frame.depth < MAX_DEPTH else None
    if text is None:
        yield frame.leaf(words, cwd, opaque="unreadable" if frame.depth < MAX_DEPTH else "too-deep")
        return
    inner = frame.deeper("script", os.path.normpath(os.path.join(cwd, os.path.expanduser(path))))
    try:
        found = read_leaves((text,) + tuple(stored_commands(text)), cwd, inner)
    except ValueError:
        yield frame.leaf(words, cwd, opaque="unparseable")
        return
    yield frame.leaf(words, cwd, expanded=True)
    yield from found


def package_leaves(words, cwd, frame):
    """A package runner's own leaf, then the body of each package script it runs, in that script's package."""
    runs = expansions(os.path.basename(words[0]), words[1:], cwd) if frame.depth < MAX_DEPTH else []
    yield frame.leaf(words, cwd, expanded=bool(runs))
    for body, directory in runs:
        try:
            yield from read_leaves((body,), directory, frame.deeper("package", directory))
        except ValueError:
            yield frame.leaf(words, cwd, opaque="unparseable")


@functools.lru_cache(maxsize=None)  # a script that runs another many times reads it once
def read_leaves(texts, cwd, frame):
    return tuple(leaf for text in texts for leaf in walk_text(text, cwd, frame))


DEFAULT_EXPANSION = re.compile(r"\$\{[A-Za-z_][A-Za-z_0-9]*:?[-=]([^}]*)\}")
# The first words of a stored string worth reading as a command.
COMMAND_WORDS = {
    "pnpm", "npm", "yarn", "bun", "npx", "bunx", "turbo", "nx", "make", "just", "next", "vite", "webpack", "rollup",
    "astro", "tsup", "playwright", "jest", "vitest", "tsc", "eslint", "oxlint", "prettier", "biome", "vue-tsc", "tsgo",
    "tsrs", "svelte-check", "oxfmt", "hyperfine", "tsx", "node", "ts-node", "vite-node", "deno",
} | SHELLS


def stored_commands(text):
    """Commands a script keeps in variables: `${CMD:-pnpm test}` defaults and `cmd="pnpm lint"`."""
    found = [m.group(1) for m in DEFAULT_EXPANSION.finditer(text)]
    for segment in commands(text):
        found += [word.partition("=")[2] for word in segment.words if ASSIGNMENT.match(word)]
    return [command for command in found if command.split() and os.path.basename(command.split()[0]) in COMMAND_WORDS]


# --- Wrappers and runners ------------------------------------------------------

# Commands that run their arguments as a command, and their options that take the next word as a value.
WRAPPERS = {
    "env": {"-u", "--unset", "-C", "--chdir"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "exec": {"-a"},
    "nohup": set(), "setsid": set(), "time": set(), "command": set(), "host-check": set(),
}
# `command -v NAME` looks a command up instead of running it.
LOOKUPS = {"-v", "-V"}
# Exec runners: the verb that runs a command, and their options that take a value.
RUNNERS = {
    "uv": (["run"], {"--with", "--with-requirements", "--python", "-p", "--project", "--directory", "--package",
                     "--env-file", "--extra", "--group", "--index", "--from"}),
    "uvx": ([], {"--from", "--with", "--with-requirements", "--python", "-p", "--index"}),
    "poetry": (["run"], {"-C", "--directory", "-P", "--project"}),
    "pipenv": (["run"], set()),
}
CHDIR_OPTIONS = {"-C", "--chdir", "--directory"}


def options_end(args, values, cwd):
    """(index of the first argument past the options, directory they set)."""
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        key, value, i = option(args, i, values)
        if key in CHDIR_OPTIONS:
            cwd = os.path.join(cwd, os.path.expanduser(value))
    return i + (args[i:i + 1] == ["--"]), cwd


def option(args, i, values):
    """(name, value, next index) of the option at i; a name in values takes the next word unless given `=VALUE`."""
    key, eq, value = args[i].partition("=")
    if key in values and not eq:
        return key, args[i + 1] if i + 1 < len(args) else "", i + 2
    return key, value, i + 1


def wrapped(name, args, cwd):
    """(command, directory, assignments) a wrapper runs: past its options, `env`'s assignments, `timeout`'s duration."""
    start, cwd = options_end(args, WRAPPERS[name], cwd)
    command, assigned = args[start:], {}
    if name == "env":
        while command and ASSIGNMENT.match(command[0]):
            key, _, value = command.pop(0).partition("=")
            assigned[key] = value
    if name == "timeout":
        command = command[1:]
    return command, os.path.normpath(cwd), assigned


def runner_verb(words):
    """`uv run`, `uvx`, and the like when the words start with one, else None."""
    name = os.path.basename(words[0])
    if name not in RUNNERS:
        return None
    verb = RUNNERS[name][0]
    return " ".join([name] + verb) if words[1:1 + len(verb)] == verb else None


def run_by(words, cwd):
    """(command, directory) an exec runner runs."""
    verb, values = RUNNERS[os.path.basename(words[0])]
    args = words[1 + len(verb):]
    start, cwd = options_end(args, values, cwd)
    return args[start:], os.path.normpath(cwd)


def bg_job_command(args):
    """The command `bg-job start NAME -- COMMAND...` runs, or [] for its other verbs."""
    if len(args) < 2 or args[0] != "start":
        return []
    rest = args[2:]
    return rest[1:] if rest[:1] == ["--"] else rest


# --- Sequence -------------------------------------------------------------------

VARIABLE = re.compile(r"^\$\{?([A-Za-z_][A-Za-z_0-9]*)\}?(.*)$")
NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
DECLARATIONS = {"export", "local", "declare", "readonly"}


def sequence(text, cwd):
    """Each simple command as (segment, words, directory, variables set before it).

    Follows `cd DIR`, and expands a command word set earlier by a plain
    assignment (`H=/path/host-check; "$H" pnpm lint`, `G="git -C dir"; $G log`).
    """
    variables = {}
    for segment in commands(text):
        remember(segment.words, variables)
        words = expand_command_word(segment.words, variables)
        yield segment, words, cwd, dict(variables)
        if words[:1] in (["cd"], ["pushd"]) and not segment.subshell:
            cwd = moved(cwd, words)


def remember(words, variables):
    """Record the variables a command made only of assignments sets."""
    lead = 1 if words[:1] and words[0] in DECLARATIONS else 0
    if not words[lead:] or not all(ASSIGNMENT.match(word) for word in words[lead:]):
        return
    for word in words[lead:]:
        name, _, value = word.partition("=")
        if NAME.fullmatch(name):
            variables[name] = value


def expand_command_word(words, variables):
    start = next((i for i, word in enumerate(words) if not (ASSIGNMENT.match(word) or word in PREFIXES)), len(words))
    found = VARIABLE.match(words[start]) if start < len(words) else None
    if not found or found.group(1) not in variables:
        return words
    try:
        return words[:start] + shlex.split(variables[found.group(1)] + found.group(2)) + words[start + 1:]
    except ValueError:
        return words


def moved(cwd, words):
    """The directory after `cd TARGET`; a target built from `$` leaves it unchanged."""
    target = next((word for word in words[1:] if not word.startswith("-")), "~")
    return cwd if "$" in target else os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))
