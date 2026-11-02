#!/usr/bin/env python3
"""Run fleet's unittest suites: all of them, or only those a diff touches.

  changed_tests.py run [--changed BASE]    run the suites, as bin/test does
  changed_tests.py plan [--changed BASE]   print suites=... and rust=true|false

A suite is a directory of test_*.py modules, run with `python3 -m unittest`
from that directory. It runs when a changed path falls under its directory or
one of the paths it watches: code it imports from elsewhere, data it reads, and
binaries it builds. A change to anything in EVERYTHING runs every suite and the
Rust checks. Without --changed, everything runs.

The changes are what differs from the merge base of BASE and HEAD: commits,
staged and unstaged edits, and untracked files. A path no suite watches, such
as a doc, runs nothing. test_changed_tests.py checks each suite's imports stay
inside what it watches, so a new import cannot silently drop a suite.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = "lib/changed-tests"

RUST = ("crates/", "Cargo.toml", "Cargo.lock", "rust-toolchain.toml")
HOST_CHECK = ("lib/host-check/", "lib/file-size/")  # each imports the other
EVERYTHING = ("bin/test", "Makefile", ".github/workflows/test.yml", f"{HERE}/")


def covers(prefix: str, path: str) -> bool:
    """A prefix ending in / covers its directory's files; any other covers that one file."""
    return path.startswith(prefix) if prefix.endswith("/") else path == prefix


@dataclass(frozen=True)
class Suite:
    directory: str
    watches: tuple[str, ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        return (f"{self.directory}/", *self.watches)

    def covers(self, path: str) -> bool:
        return any(covers(prefix, path) for prefix in self.paths)

    def modules(self) -> list[str]:
        return sorted(test.stem for test in (ROOT / self.directory).glob("test_*.py"))


SUITES = (
    Suite("lib/host-check", HOST_CHECK),
    Suite("bin", HOST_CHECK),
    Suite("lib/file-size", HOST_CHECK),
    Suite("lib/ci-cache"),
    Suite("lib/pr-assets"),
    Suite("lib/transcripts"),
    Suite("lib/fleet", ("config/", "hosts/", "bin/sync")),
    # The analyzers it tests: pbp-complexity built from this checkout, godot-guard as binaries.json pins it.
    Suite("skills/pedro-best-practices/tests", ("skills/pedro-best-practices/", *RUST, "binaries.json")),
    Suite("skills/review-loop/scripts", ("skills/review-loop/", "skills/stack/", "skills/pedro-best-practices/")),
    Suite("skills/pre-commit/scripts", ("skills/pre-commit/", *HOST_CHECK)),
    Suite("hosts/workbox/claude-hooks", HOST_CHECK),
    Suite("skills/stack/scripts", ("skills/stack/",)),
)
# This suite checks every other suite's imports, so any of their changes runs it.
SUITES += (Suite(HERE, tuple(prefix for suite in SUITES for prefix in suite.paths)),)


@dataclass(frozen=True)
class Plan:
    suites: tuple[Suite, ...]
    rust: bool


def plan_for(changed: list[str] | None) -> Plan:
    """What to run for these changed paths; None means run everything."""
    if changed is None or any(covers(prefix, path) for prefix in EVERYTHING for path in changed):
        return Plan(SUITES, rust=True)
    suites = tuple(suite for suite in SUITES if any(suite.covers(path) for path in changed))
    rust = any(covers(prefix, path) for prefix in RUST for path in changed)
    return Plan(suites, rust)


def git(*args: str) -> list[str]:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.splitlines()


def changed_since(base: str) -> list[str]:
    """Paths that differ from the merge base of BASE and HEAD, the worktree and untracked files included."""
    [fork] = git("merge-base", base, "HEAD")
    return git("diff", "--name-only", "--no-renames", fork) + git("ls-files", "--others", "--exclude-standard")


def run(plan: Plan) -> int:
    status = 0
    for suite in plan.suites:
        print(f"== {suite.directory}", flush=True)
        command = [sys.executable, "-m", "unittest", *suite.modules()]
        status |= subprocess.run(command, cwd=ROOT / suite.directory).returncode != 0
    skipped = [suite.directory for suite in SUITES if suite not in plan.suites]
    if skipped:
        print(f"== skipped, untouched by the changes: {' '.join(skipped)}")
    return status


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("run", "plan"))
    parser.add_argument("--changed", metavar="BASE", help="select by the changes since BASE's merge base")
    args = parser.parse_args(argv)
    plan = plan_for(changed_since(args.changed) if args.changed else None)
    if args.command == "run":
        return run(plan)
    print(f"suites={' '.join(suite.directory for suite in plan.suites)}")
    print(f"rust={str(plan.rust).lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
