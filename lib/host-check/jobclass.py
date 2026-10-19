"""Classify host-check jobs as build, heavy, or light.

    python3 jobclass.py COMMAND [ARG ...]    # prints build, heavy, or light

Uses the guard's shell parsing (shell.py, packages.py): package scripts and
shell script files are judged by the commands they run, and script names
remain the fallback.
"""
import functools
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from guard import BENCH_SCRIPT, COMMAND_WORDS, HELP, guarded, runner_invocations, stored_commands  # noqa: E402
from packages import expansions  # noqa: E402
from shell import (  # noqa: E402
    ASSIGNMENT, MAX_DEPTH, PREFIXES, SHELLS, WRAPPERS, bg_job_command, read_script, shell_invocation, shell_script,
    walk,
)

GLOB = re.compile(r"[*?[]")

# Job classes for host-check admission. Builds and whole suites are CPU-heavy
# (2.5 to 3.3 cores each); targeted tests, lint, format, and typecheck are light.
BUILD_TASK = re.compile(r"^build([:.-].*)?$")
SUITE_TASK = re.compile(r"^(check|test|verify|validate|precommit|pre-commit)([:.-].*)?$")
TEST_RUNNERS = {"vitest", "jest"}
PACKAGE_RUNNERS = {"pnpm", "npm", "yarn", "bun", "npx", "bunx", "turbo", "nx"}
RANK = {"light": 0, "heavy": 1, "build": 2}


def strongest(classes):
    return max(classes, key=RANK.get, default="light")


def targeted(args):
    """Whether the arguments name specific test files or directories."""
    return any(not a.startswith("-") and ("/" in a or re.search(r"\.(test|spec)\.|\.[cm]?[jt]sx?$", a)) for a in args)


def name_class(name, args):
    """The class a command's own words imply, without looking inside scripts."""
    if name in PACKAGE_RUNNERS or name in {"make", "just"}:
        for i, arg in enumerate(args):
            if BUILD_TASK.fullmatch(arg):
                return "build"
            if SUITE_TASK.fullmatch(arg) or os.path.basename(arg) in TEST_RUNNERS:
                return "light" if targeted(args[i + 1:]) else "heavy"
        return "light"
    if name in {"next", "vite", "webpack", "rollup", "astro", "tsup"} and "build" in args:
        return "build"
    if name in TEST_RUNNERS:
        return "light" if targeted(args) else "heavy"
    if name == "playwright" and args[:1] == ["test"]:
        return "heavy"
    return "light"


@functools.lru_cache(maxsize=None)  # a script that runs another many times reads it once
def file_class(path, cwd, depth, unreadable="heavy"):
    """A shell script's strongest command, or `unreadable` when it cannot be read or parsed."""
    text = read_script(path, cwd) if depth < MAX_DEPTH else None
    if text is None:
        return unreadable
    try:
        return strongest(job_class(code, cwd, depth + 1) for code in [text] + stored_commands(text))
    except ValueError:
        return unreadable


def segment_class(words, cwd=None, depth=0):
    cwd = cwd or os.getcwd()
    words = list(words)
    while words and (ASSIGNMENT.match(words[0]) or words[0] in PREFIXES):
        words.pop(0)
    if not words:
        return "light"
    name = os.path.basename(words[0])
    args = words[1:]
    if name in WRAPPERS:
        while args and (args[0].startswith("-") or ASSIGNMENT.match(args[0]) or re.match(r"^\d+[smhd]?$", args[0])):
            args.pop(0)
        return segment_class(args, cwd, depth)
    if name == "bg-job":
        return segment_class(bg_job_command(args), cwd, depth)
    if any(os.path.basename(w).startswith("njhomes-page-gates") for w in words):
        return "build"  # builds the app, then audits it
    if "$" in name or name == "eval":
        return "heavy"  # runs a command that cannot be seen here
    if args and all(arg in HELP for arg in args):
        return "light"
    if name in SHELLS:
        kind, value = shell_invocation(args)
        if kind == "string":
            return guarded(job_class, value, cwd, depth + 1, "heavy") if depth < MAX_DEPTH else "heavy"
        if kind == "file":
            return file_class(value, cwd, depth)
        return "heavy" if kind == "stdin" else "light"  # stdin hides its commands; -n only parses
    if name in {"source", "."}:
        return file_class(args[0], cwd, depth, unreadable="light") if args else "light"
    if name == "wait":
        return "heavy"  # a fan-out of background jobs
    script = shell_script(words[0], cwd)
    classes = [name_class(name, args), runner_class(words, cwd, depth)]
    if script:
        classes.append(file_class(script, cwd, depth))
    if name in PACKAGE_RUNNERS and depth < MAX_DEPTH:
        classes += [guarded(job_class, body, directory, depth + 1, "light") for body, directory in expansions(name, args, cwd)]
    return strongest(classes)


def job_class(command, cwd=None, depth=0):
    """The costliest class among a command's segments: build, heavy, or light."""
    return strongest(segment_class(words, here, depth) for words, here in walk(command, cwd or os.getcwd()))


SUITE_API = re.compile(r"\b(startVitest|createVitest)\b|[\"']vitest/node[\"']")
STRING = re.compile(r"\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`")
SPAWN = re.compile(r"[\"'`]([\w.-]+)[\"'`]\s*,\s*\[([^\]]*)\]")


def harness_class(path, cwd, depth):
    """A benchmark or debug harness is light unless it runs a suite or build itself."""
    text = read_script(path, cwd) if depth < MAX_DEPTH else None
    if text is None:
        return "light"
    if SUITE_API.search(text):
        return "heavy"
    commands = ["".join(m.groups(default="")) for m in STRING.finditer(text)]
    commands += [m.group(1) + " " + " ".join(re.findall(r"[\"'`]([^\"'`]*)[\"'`]", m.group(2))) for m in SPAWN.finditer(text)]
    commands = [c for c in commands if c.split() and os.path.basename(c.split()[0]) in COMMAND_WORDS]
    return strongest(guarded(job_class, command, cwd, depth + 1, "light") for command in commands)


def runner_class(words, cwd, depth):
    """`node --test` suites are heavy unless they name files; harnesses per harness_class."""
    classes = []
    for options, positional in runner_invocations(words):
        if "--test" in options:
            classes.append("light" if positional and not any(GLOB.search(p) for p in positional) else "heavy")
        elif positional and BENCH_SCRIPT.match(os.path.basename(positional[0])):
            classes.append(harness_class(positional[0], cwd, depth))
    return strongest(classes)


if __name__ == "__main__":
    print(job_class(shlex.join(sys.argv[1:])))
