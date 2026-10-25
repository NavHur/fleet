#!/usr/bin/env python3
"""Does CI on self-hosted runners run tests on a pull request into BASE?

Reads the checkout's .github/workflows and prints each workflow that runs on
`pull_request` for BASE with a counted job that runs tests (a step running
pytest, vitest, jest, playwright test, or a test or coverage script), adding
"(full set after ready for review)" when some of those jobs skip drafts. When
in doubt a workflow does not count: GitHub-hosted jobs (Actions minutes are
spent), `paths` filters, `types` without `opened` or `synchronize`, and job
`if` conditions other than a draft guard all leave it out. A job counts only
if it is self-hosted and every job in its `needs` counts. Draft-guarded jobs
count only when the trigger's `types` include `ready_for_review`.

Exit 0 when one covers it, 1 when none does, 2 on an error (usage, missing
PyYAML, or a workflow that cannot be read or has an unexpected shape).

Usage: ci_covers.py --base BRANCH [--root DIR]
"""

import argparse
import io
import os
import pathlib
import re
import shlex
import sys

try:
    import yaml
except ImportError:
    print("ci_covers: PyYAML is not installed", file=sys.stderr)
    sys.exit(2)

DRAFT_GUARDS = {
    "!github.event.pull_request.draft",
    "github.event.pull_request.draft == false",
}
PUSH_PREFIX = "github.event_name != 'pull_request' || "
QUANTIFIERS = {"?": "?", "+": "+"}
DEFAULT_TYPES = ["opened", "synchronize", "reopened"]
REQUIRED_TYPES = {"opened", "synchronize"}
SHELL_PUNCTUATION = "();<>|&\n"
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
TEST_TOOLS = {"pytest", "vitest", "jest"}
PYTEST_MODULE = ["-m", "pytest"]
MODULE_RUNNERS = {
    "python": PYTEST_MODULE,
    "python3": PYTEST_MODULE,
    "coverage": ["run", *PYTEST_MODULE],
}
RUNNER_PREFIXES = {
    "uv": ["run"],
    "poetry": ["run"],
    "pipenv": ["run"],
    "uvx": [],
    "npx": [],
    "bunx": [],
}
PACKAGE_MANAGERS = {"pnpm", "npm", "yarn", "bun"}
SCRIPT_RUNNERS = PACKAGE_MANAGERS | {"turbo"}
EXEC_VERBS = {"exec", "dlx"}
FLAGS_WITH_VALUE = {"--filter", "-F", "--dir", "-C"}
SKIPPED_WORDS = {"run", "turbo"}
TEST_PARTS = {"test", "coverage"}
NOT_TEST_PARTS = {"lint", "types", "typecheck", "format"}


class WorkflowError(Exception):
    """A workflow cannot be read or does not have the expected shape."""


def mapping(value, what):
    if not isinstance(value, dict):
        raise WorkflowError(f"{what} must be a mapping")
    return value


def load(path):
    try:
        data = yaml.safe_load(path.read_text())
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as err:
        raise WorkflowError(" ".join(str(err).split())) from err
    return mapping({} if data is None else data, "workflow")


def triggers(workflow):
    """The `on:` block as a dict; YAML 1.1 reads a bare `on` key as True."""
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return mapping(on or {}, "on")


def char_class(body):
    """A GitHub `[...]` character class as a regex class."""
    body = body.replace("\\", "\\\\").replace("[", "\\[")
    return "[" + re.sub(r"^\^", r"\\^", body) + "]"


def token(pattern, i):
    """The regex for the pattern element at I, and the index after it."""
    if pattern.startswith("**", i):
        return ".*", i + 2
    char = pattern[i]
    if char == "*":
        return "[^/]*", i + 1
    end = pattern.find("]", i + 2)
    if char == "[" and end > 0:
        return char_class(pattern[i + 1 : end]), end + 1
    return re.escape(char), i + 1


def pattern_regex(pattern):
    """Translate a GitHub filter pattern to a regex source."""
    parts = []
    i = 0
    while i < len(pattern):
        if pattern[i] in QUANTIFIERS and parts:
            parts[-1] = f"(?:{parts[-1]}){QUANTIFIERS[pattern[i]]}"
            i += 1
            continue
        part, i = token(pattern, i)
        parts.append(part)
    return "".join(parts)


def matches(pattern, base):
    try:
        return re.fullmatch(pattern_regex(pattern), base) is not None
    except re.error as err:
        raise WorkflowError(f"bad branch pattern {pattern!r}: {err}") from err


def pattern_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(p) for p in value]
    raise WorkflowError(f"expected a string or a list, got {value!r}")


def admitted(patterns, base):
    """Evaluate a `branches` list in order; the last matching pattern wins."""
    included = False
    for pattern in patterns:
        if matches(pattern.removeprefix("!"), base):
            included = not pattern.startswith("!")
    return included


def matches_base(trigger, base):
    """Whether a pull_request trigger's branch filters admit BASE."""
    if "branches" in trigger:
        return admitted(pattern_list(trigger["branches"]), base)
    ignored = pattern_list(trigger.get("branches-ignore"))
    return not any(matches(p, base) for p in ignored)


def pr_types(trigger):
    """The activity types a pull_request trigger fires on (GitHub's defaults
    when `types` is absent)."""
    if trigger is None or "types" not in trigger:
        return DEFAULT_TYPES
    return pattern_list(trigger["types"])


def covers_base(trigger, base):
    """Whether a pull_request trigger certainly runs on every update of a PR."""
    if trigger is None:
        return True
    mapping(trigger, "pull_request")
    if {"paths", "paths-ignore"} & trigger.keys():
        return False
    if not REQUIRED_TYPES <= set(pr_types(trigger)):
        return False
    return matches_base(trigger, base)


def labels(runs_on):
    """A job's runner labels; an unexpanded `${{ }}` expression is one opaque
    label, so it never counts as self-hosted."""
    if isinstance(runs_on, str):
        return [runs_on]
    if isinstance(runs_on, dict):
        return labels(runs_on.get("labels", []))
    return runs_on if isinstance(runs_on, list) else []


def is_draft_guard(condition):
    """Whether a job `if` is a DRAFT_GUARDS entry, optionally after PUSH_PREFIX,
    ignoring whitespace, quote style and a `${{ }}` wrapper."""
    text = " ".join(str(condition).split()).replace('"', "'")
    text = re.sub(r"^\$\{\{(.*)\}\}$", r"\1", text).strip()
    return text.removeprefix(PUSH_PREFIX) in DRAFT_GUARDS


def self_hosted_on_prs(job):
    """Whether a job is self-hosted with no `if`, or only a draft guard."""
    if "self-hosted" not in labels(job.get("runs-on")):
        return False
    return "if" not in job or is_draft_guard(job["if"])


def resolve(name, jobs, path):
    """None when a job does not count, else whether drafts skip it. A job
    counts only if it is self-hosted on PRs and all its needs count."""
    job = jobs.get(name)
    if job is None or name in path or not self_hosted_on_prs(job):
        return None
    needs = [resolve(n, jobs, path | {name}) for n in pattern_list(job.get("needs"))]
    if None in needs:
        return None
    return "if" in job or any(needs)


def steps_of(name, job):
    """A job's `steps` list; absent means none. Each step must be a mapping
    whose `run`, when present, is a string."""
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        raise WorkflowError(f"job {name} steps must be a list")
    for step in steps:
        mapping(step, f"job {name} step")
        if not isinstance(step.get("run", ""), str):
            raise WorkflowError(f"job {name} step run must be a string")
    return steps


class CommentStream(io.StringIO):
    """A stream whose `readline` leaves the newline, so a comment ends a command."""

    def readline(self, *args):
        line = super().readline(*args)
        if line.endswith("\n"):
            self.seek(self.tell() - 1)
        return line


def is_separator(token):
    """Whether a lexed token is only shell operator characters."""
    return bool(token) and all(char in SHELL_PUNCTUATION for char in token)


def commands(run):
    """The commands of a `run` script as token lists, up to any heredoc; an
    unbalanced quote leaves none."""
    stream = CommentStream(run.replace("\\\n", " "))
    lexer = shlex.shlex(stream, posix=True, punctuation_chars=SHELL_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    found, current = [], []
    for item in tokens:
        if not is_separator(item):
            current.append(item)
            continue
        if "<<" in item:
            break
        found.append(current)
        current = []
    return [*found, current]


def words(tokens):
    """A command's tokens without its leading VAR=value assignments."""
    start = 0
    while start < len(tokens) and ENV_ASSIGNMENT.match(tokens[start]):
        start += 1
    return tokens[start:]


def runs_tool(args):
    """Whether ARGS start with a test tool: `vitest ...`, `playwright test`."""
    if args[:1] and args[0] in TEST_TOOLS:
        return True
    return args[:2] == ["playwright", "test"]


def script_names(args):
    """The script-like words of a package manager's ARGS, before any `--`."""
    skip = False
    for arg in args:
        if arg == "--":
            return
        if skip:
            skip = False
        elif arg in FLAGS_WITH_VALUE:
            skip = True
        elif not arg.startswith("-") and arg not in SKIPPED_WORDS:
            yield arg


def is_test_script(name):
    parts = set(name.split(":"))
    return bool(parts & TEST_PARTS) and not parts & NOT_TEST_PARTS


def package_manager_runs_tests(args):
    """Whether a package manager's ARGS run a test script or a test tool."""
    names = list(script_names(args))
    if names and names[0] in EXEC_VERBS:
        names = names[1:]
    elif names and is_test_script(names[0]):
        return True
    return runs_tool(names)


def wrapped_args(program, args):
    """The command a runner like `uv run` wraps, or None for another program."""
    prefix = RUNNER_PREFIXES.get(program)
    if prefix is None or args[: len(prefix)] != prefix:
        return None
    return args[len(prefix) :]


def command_runs_tests(tokens):
    """Whether a tokenized shell command runs tests."""
    if not tokens:
        return False
    program, args = os.path.basename(tokens[0]), tokens[1:]
    if runs_tool([program, *args]):
        return True
    if program in MODULE_RUNNERS:
        return args[: len(MODULE_RUNNERS[program])] == MODULE_RUNNERS[program]
    wrapped = wrapped_args(program, args)
    if wrapped is not None:
        return command_runs_tests(wrapped)
    return program in SCRIPT_RUNNERS and package_manager_runs_tests(args)


def script_runs_tests(run):
    """Whether any command of a `run` script runs tests."""
    return any(command_runs_tests(words(command)) for command in commands(run))


def runs_tests(name, job):
    """Whether any step of a job runs a test command."""
    return any(script_runs_tests(step.get("run", "")) for step in steps_of(name, job))


def counted_jobs(workflow):
    """Map each counted job to whether drafts skip it, directly or by needs."""
    jobs = mapping(workflow.get("jobs", {}), "jobs")
    for name, job in jobs.items():
        steps_of(name, mapping(job, f"job {name}"))
    skips = {name: resolve(name, jobs, frozenset()) for name in jobs}
    return {name: skip for name, skip in skips.items() if skip is not None}


def covered_jobs(workflow, base):
    """The counted jobs that run tests on BASE's PRs: none when the trigger misses
    them, only the unguarded ones when its types omit ready_for_review."""
    jobs = counted_jobs(workflow)
    on = triggers(workflow)
    if "pull_request" not in on or not covers_base(on["pull_request"], base):
        return {}
    if "ready_for_review" not in pr_types(on["pull_request"]):
        jobs = {name: skip for name, skip in jobs.items() if not skip}
    return {
        name: skip
        for name, skip in jobs.items()
        if runs_tests(name, workflow["jobs"][name])
    }


def covering(root, base):
    """(file name, skips drafts) for each workflow that covers BASE."""
    found = []
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        try:
            jobs = covered_jobs(load(path), base)
        except WorkflowError as err:
            raise WorkflowError(f"{path}: {err}") from err
        if jobs:
            found.append((path.name, any(jobs.values())))
    return found


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    try:
        found = covering(pathlib.Path(args.root), args.base)
    except WorkflowError as err:
        print(f"ci_covers: {err}", file=sys.stderr)
        return 2
    for name, drafts in found:
        print(name + (" (full set after ready for review)" if drafts else ""))
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
