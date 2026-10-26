"""Classify host-check jobs as build, heavy, or light.

    python3 jobclass.py COMMAND [ARG ...]    # prints build, heavy, or light

Judges the leaves of the command walk (walk.py), as the guard does: package
scripts and shell script files are judged by the commands they run, and
script names remain the fallback.
"""
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from guard import BENCH_SCRIPT, runner_invocations  # noqa: E402
from shell import read_script  # noqa: E402
from walk import COMMAND_WORDS, HELP, MAX_DEPTH, leaves  # noqa: E402

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
    if name == "godot-guard" and args[:1] == ["gate"]:
        return "light" if "--fast" in args else "heavy"  # a full gate fans out about 4 GB of Godot
    return "light"


def leaf_class(leaf, depth=0):
    """The class one leaf of a job implies."""
    if leaf.opaque:
        # A sourced file only sets up the shell; anything else hides what it runs.
        return "light" if os.path.basename(leaf.words[0]) in {"source", "."} else "heavy"
    words = leaf.words
    name = os.path.basename(words[0])
    args = words[1:]
    if any(os.path.basename(w).startswith("njhomes-page-gates") for w in words):
        return "build"  # builds the app, then audits it
    if args and all(arg in HELP for arg in args):
        return "light"
    if name == "wait":
        return "heavy"  # a fan-out of background jobs
    return strongest([name_class(name, args), runner_class(words, leaf.cwd, depth)])


def job_class(command, cwd=None, depth=0):
    """The costliest class among a command's leaves: build, heavy, or light."""
    return strongest(leaf_class(leaf, depth) for leaf in leaves(command, cwd or os.getcwd()))


def guarded_class(command, cwd, depth):
    """A harness string's class; light when shlex cannot parse it."""
    try:
        return job_class(command, cwd, depth)
    except ValueError:
        return "light"


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
    return strongest(guarded_class(command, cwd, depth + 1) for command in commands)


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
