#!/usr/bin/env python3
"""Does CI on self-hosted runners check a pull request into BASE?

Reads the checkout's .github/workflows and prints each workflow that runs on
`pull_request` for BASE with at least one self-hosted job, adding "(full set
after ready for review)" when some of its counted jobs skip drafts. When in
doubt a workflow does not count: GitHub-hosted jobs (the organization's Actions
minutes are spent), `paths` filters, `types` without `synchronize`, and job
`if` conditions other than a draft guard all leave it out.

Exit 0 when one covers it, 1 when none does, 2 on an error (usage, missing
PyYAML, or a workflow that cannot be read or has an unexpected shape).

Usage: ci_covers.py --base BRANCH [--root DIR]
"""

import argparse
import pathlib
import re
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
    return [value] if isinstance(value, str) else [str(p) for p in value or []]


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


def covers_base(trigger, base):
    """Whether a pull_request trigger certainly runs on every update of a PR."""
    if trigger is None:
        return True
    if not isinstance(trigger, dict) or {"paths", "paths-ignore"} & trigger.keys():
        return False
    if "synchronize" not in pattern_list(trigger.get("types", ["synchronize"])):
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
    """Whether a job `if` is exactly a draft guard, however spelled."""
    text = " ".join(str(condition).split()).replace('"', "'")
    text = re.sub(r"^\$\{\{(.*)\}\}$", r"\1", text).strip()
    return text.removeprefix(PUSH_PREFIX) in DRAFT_GUARDS


def counted_jobs(workflow):
    """Self-hosted jobs with no `if`, or only a draft guard."""
    jobs = mapping(workflow.get("jobs", {}), "jobs")
    counted = []
    for name, job in jobs.items():
        job = mapping(job, f"job {name}")
        guarded = "if" not in job or is_draft_guard(job["if"])
        if "self-hosted" in labels(job.get("runs-on")) and guarded:
            counted.append(job)
    return counted


def skips_drafts(jobs):
    return any("if" in job for job in jobs)


def covered_jobs(workflow, base):
    """The counted jobs of a workflow, or none when it misses BASE's PRs."""
    jobs = counted_jobs(workflow)
    on = triggers(workflow)
    if "pull_request" in on and covers_base(on["pull_request"], base):
        return jobs
    return []


def covering(root, base):
    """(file name, skips drafts) for each workflow that covers BASE."""
    found = []
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        try:
            jobs = covered_jobs(load(path), base)
        except WorkflowError as err:
            raise WorkflowError(f"{path}: {err}") from err
        if jobs:
            found.append((path.name, skips_drafts(jobs)))
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
