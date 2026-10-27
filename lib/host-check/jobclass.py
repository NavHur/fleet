"""The validation catalogue: the job class of each leaf a command runs.

    python3 jobclass.py COMMAND [ARG ...]    # prints none, light, heavy, or build

A job class is none (no validation), light (lint, format, typecheck, targeted
tests), heavy (whole suites), or build. host-check admits a job by its
strongest leaf, and the guard (guard.py) sends a command to the queue when a
leaf it can see is anything but none. They agree on every leaf the walk can
see that host-check does not already run. Exceptions: opaque leaves are heavy
here but never queued (docs/adr/0002), a script or gate that queues itself
is classed here but left to queue, and fan-out is judged per job by host-check.
Leaves come from the command walk (walk.py): package scripts and shell script
files are judged by the commands they run, and script names remain the fallback.
"""
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from shell import read_script  # noqa: E402
import walk  # noqa: E402
from walk import COMMAND_WORDS, HELP, MAX_DEPTH, leaves  # noqa: E402

# Builds and whole suites are CPU-heavy (2.5 to 3.3 cores each); targeted
# tests, lint, format, and typecheck are light.
RANK = {"none": 0, "light": 1, "heavy": 2, "build": 3}
BUILD_TASK = re.compile(r"^build([:.-].*)?$")
SUITE_TASK = re.compile(r"^(check|test|verify|validate|precommit|pre-commit)([:.-].*)?$")
LIGHT_TASK = re.compile(r"^(lint|typecheck|type-check|format|fmt|bench|benchmark)([:.-].*)?$")
# The walk's set is the runners whose package.json scripts it expands; nx runs
# project targets instead, so only the catalogue adds it.
PACKAGE_RUNNERS = walk.PACKAGE_RUNNERS | {"nx"}
# Commands whose arguments name a validation task: `pnpm test`, `make lint`.
TASK_RUNNERS = PACKAGE_RUNNERS | {"make", "just"}
GLOB = re.compile(r"[*?[]")


def strongest(classes):
    return max(classes, key=RANK.get, default="none")


def targeted(args):
    """Whether the arguments name specific test files or directories."""
    return any(not a.startswith("-") and ("/" in a or re.search(r"\.(test|spec)\.|\.[cm]?[jt]sx?$", a)) for a in args)


def suite_class(args):
    """A test suite is heavy unless it names files or directories."""
    return "light" if targeted(args) else "heavy"


def light(args):
    return "light"


def heavy(args):
    return "heavy"


def framework_class(args):
    """`next build` builds; `next lint` and `astro check` are light."""
    if "build" in args:
        return "build"
    if "check" in args or "lint" in args:
        return "light"
    return "none"


def tsup_class(args):
    """tsup builds when run at all, unless it watches or prints help."""
    watching = any(arg in {"--watch", "-w"} or arg.startswith("--watch=") for arg in args)
    return "none" if watching or any(arg in HELP for arg in args) else "build"


def playwright_class(args):
    verb = next((arg for arg in args if not arg.startswith("-")), None)
    if verb == "test":
        return "heavy"
    return "light" if verb in {"screenshot", "pdf"} else "none"


def godot_guard_class(args):
    if args[:1] == ["gate"]:
        return "light" if "--fast" in args else "heavy"  # a full gate fans out about 4 GB of Godot
    return "light" if args[:1] == ["check"] else "none"


# Validation tools a package runner may name among its arguments (`pnpm exec eslint`).
TOOLS = {
    **dict.fromkeys(["tsc", "eslint", "oxlint", "prettier", "biome", "vue-tsc", "tsgo", "tsrs", "svelte-check",
                     "oxfmt"], light),
    "vitest": suite_class, "jest": suite_class, "hyperfine": heavy,  # a benchmark pins every core it can
    **dict.fromkeys(["next", "vite", "webpack", "rollup", "astro"], framework_class),
    "playwright": playwright_class, "godot-guard": godot_guard_class,
}
# Tools judged only as the leaf itself: `pnpm add tsup` installs it.
LEAF_TOOLS = {**TOOLS, "tsup": tsup_class}


def task_class(args, i):
    """The class the task or tool named at args[i] implies, judged on the arguments after it."""
    arg = args[i]
    if BUILD_TASK.fullmatch(arg):
        return "build"
    if SUITE_TASK.fullmatch(arg):
        return suite_class(args[i + 1:])
    if LIGHT_TASK.fullmatch(arg):
        return "light"
    judge = TOOLS.get(os.path.basename(arg))
    return judge(args[i + 1:]) if judge else "none"


def name_class(name, args):
    """The class a command's own words imply, without looking inside scripts."""
    if name in TASK_RUNNERS:
        return strongest(task_class(args, i) for i in range(len(args)))
    judge = LEAF_TOOLS.get(name)
    return judge(args) if judge else "none"


def queues_itself(words):
    """A gate that calls host-check itself, such as njhomes-page-gates, run as the command."""
    return os.path.basename(words[0]).startswith("njhomes-page-gates")


def leaf_class(leaf, depth=0):
    """The class one leaf implies: none, light, heavy, or build."""
    if leaf.opaque:
        # A sourced file only sets up the shell; anything else hides what it runs.
        return "none" if os.path.basename(leaf.words[0]) in {"source", "."} else "heavy"
    words = leaf.words
    name = os.path.basename(words[0])
    args = words[1:]
    if queues_itself(words):
        return "build"  # builds the app, then audits it
    if args and all(arg in HELP for arg in args):
        return "none"
    return strongest([name_class(name, args), runner_class(words, leaf.cwd, depth)])


def job_class(command, cwd=None):
    """The strongest class among a command's leaves; heavy when shlex cannot parse it."""
    return command_class(command, cwd or os.getcwd(), 0, unparseable="heavy")


def command_class(command, cwd, depth, unparseable):
    try:
        found = list(leaves(command, cwd))
    except ValueError:
        return unparseable
    # Commands sent to the background run side by side: a fan-out.
    return strongest([leaf_class(leaf, depth) for leaf in found] + ["heavy" for leaf in found if leaf.background])


# --- Script runners -----------------------------------------------------------

RUNNERS = {"tsx", "node", "ts-node", "vite-node", "bun", "deno"}
# Runner options that take a value, so the value is not mistaken for the script.
RUNNER_VALUE_OPTIONS = {"--import", "-r", "--require", "--loader", "--experimental-loader", "--env-file", "--tsconfig", "--conditions", "-C"}
# Script paths that boot a Next server and a browser (axe page gates, smoke
# runs, visual and screenshot captures).
BROWSER_SCRIPT = re.compile(r"(^|/)(a11y|smoke|visual|screenshots?|shots|e2e|playwright)[^/]*(/|$)")
# Benchmarks, perf harnesses, and throwaway debug harnesses, by file name.
BENCH_SCRIPT = re.compile(r"^(debug-|bench|perf)")
SUITE_API = re.compile(r"\b(startVitest|createVitest)\b|[\"']vitest/node[\"']")
STRING = re.compile(r"\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`")
SPAWN = re.compile(r"[\"'`]([\w.-]+)[\"'`]\s*,\s*\[([^\]]*)\]")


def runner_invocations(words):
    """The script runner a command is: (its options, its positional arguments), or none."""
    name = os.path.basename(words[0]) if words else ""
    if name not in RUNNERS:
        return
    rest, options, j = words[1:], [], 0
    while j < len(rest) and rest[j].startswith("-"):
        options.append(rest[j])
        j += 2 if rest[j] in RUNNER_VALUE_OPTIONS else 1
    positional = rest[j:]
    if name in {"bun", "deno"} and positional[:1] == ["run"]:
        positional = positional[1:]
    yield options, positional


def runs_browser_script(words):
    """A runner followed by a browser-script path anywhere in the words."""
    for i, word in enumerate(words):
        rest = [arg for arg in words[i + 1:] if not arg.startswith("-")]
        if os.path.basename(word) in RUNNERS and rest and BROWSER_SCRIPT.search(rest[0]):
            return True
    return False


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
    return strongest(["light"] + [command_class(command, cwd, depth + 1, unparseable="light") for command in commands])


def runner_class(words, cwd, depth):
    """A script runner's class: browser scripts are light, then per invocation_class."""
    classes = [invocation_class(options, positional, cwd, depth) for options, positional in runner_invocations(words)]
    return strongest(classes + (["light"] if runs_browser_script(words) else []))


def invocation_class(options, positional, cwd, depth):
    """`node --test` suites are heavy unless they name files; harnesses per harness_class."""
    if "--test" in options:
        return "light" if positional and not any(GLOB.search(p) for p in positional) else "heavy"
    if positional and BENCH_SCRIPT.match(os.path.basename(positional[0])):
        return harness_class(positional[0], cwd, depth)
    return "none"


if __name__ == "__main__":
    print(job_class(shlex.join(sys.argv[1:])))
