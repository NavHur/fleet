#!/usr/bin/env python3
"""Does CI on self-hosted runners check a pull request into BASE?

Reads the checkout's .github/workflows and prints each workflow that runs on
`pull_request` for BASE with at least one self-hosted job, adding "(full set
after ready for review)" when some of its jobs skip drafts. GitHub-hosted jobs
do not count: the organization's Actions minutes are spent.

Exit 0 when one covers it, 1 when none does, 2 on a usage error.

Usage: ci_covers.py --base BRANCH [--root DIR]
"""

import argparse
import fnmatch
import pathlib
import sys

import yaml


def triggers(workflow):
    """The `on:` block as a dict; YAML 1.1 reads a bare `on` key as True."""
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return on or {}


def matches_base(trigger, base):
    """Whether a pull_request trigger's branch filters admit BASE."""
    trigger = trigger or {}
    if "branches" in trigger:
        return any(fnmatch.fnmatchcase(base, p) for p in trigger["branches"])
    ignored = trigger.get("branches-ignore", [])
    return not any(fnmatch.fnmatchcase(base, p) for p in ignored)


def labels(runs_on):
    """A job's runner labels; an expression yields none."""
    if isinstance(runs_on, str):
        return [runs_on]
    if isinstance(runs_on, dict):
        return labels(runs_on.get("labels", []))
    return runs_on or []


def self_hosted_jobs(workflow):
    jobs = (workflow.get("jobs") or {}).values()
    return [job for job in jobs if "self-hosted" in labels(job.get("runs-on"))]


def skips_drafts(jobs):
    return any("pull_request.draft" in str(job.get("if", "")) for job in jobs)


def covering(root, base):
    """(file name, skips drafts) for each workflow that covers BASE."""
    found = []
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text()) or {}
        on = triggers(workflow)
        jobs = self_hosted_jobs(workflow)
        if "pull_request" in on and matches_base(on["pull_request"], base) and jobs:
            found.append((path.name, skips_drafts(jobs)))
    return found


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    found = covering(pathlib.Path(args.root), args.base)
    for name, drafts in found:
        print(name + (" (full set after ready for review)" if drafts else ""))
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
