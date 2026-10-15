#!/usr/bin/env python3
"""Measure review-line churn between two Git revisions.

Tests count toward raw churn only. Lockfiles and verified generated files are
excluded from both ceilings. With --per-commit, every commit in the range is
measured against its parent under the commit ceilings; a commit carrying a
`Size-Exception: <reason>` trailer is exempt. Exit with status 2 when a ceiling
is exceeded.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath


LOCKFILE_NAMES = {
    "bun.lock",
    "bun.lockb",
    "cargo.lock",
    "composer.lock",
    "flake.lock",
    "gemfile.lock",
    "go.sum",
    "mix.lock",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "package.resolved",
    "pipfile.lock",
    "podfile.lock",
    "poetry.lock",
    "pnpm-lock.yaml",
    "pubspec.lock",
    "uv.lock",
    "yarn.lock",
}
PR_CEILINGS = (1000, 2000)
COMMIT_CEILINGS = (300, 600)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


@dataclass
class DiffEntry:
    path: str
    old_path: str | None
    additions: int | None
    deletions: int | None
    lines: int
    excluded: bool
    reason: str | None
    test: bool


def git(*args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    if result.returncode != 0:
        error = result.stderr.strip() if text else result.stderr.decode().strip()
        raise RuntimeError(error or f"git {' '.join(args)} failed")
    return result.stdout


def parse_numstat(raw: bytes) -> list[tuple[str | None, str, int | None, int | None]]:
    parts = raw.split(b"\0")
    entries: list[tuple[str | None, str, int | None, int | None]] = []
    index = 0
    while index < len(parts) and parts[index]:
        fields = parts[index].decode("utf-8", errors="surrogateescape").split("\t", 2)
        if len(fields) != 3:
            raise RuntimeError("unexpected git --numstat output")
        added_raw, deleted_raw, path = fields
        index += 1
        old_path: str | None = None
        if path == "":
            if index + 1 >= len(parts):
                raise RuntimeError("truncated rename/copy in git --numstat output")
            old_path = parts[index].decode("utf-8", errors="surrogateescape")
            path = parts[index + 1].decode("utf-8", errors="surrogateescape")
            index += 2
        additions = None if added_raw == "-" else int(added_raw)
        deletions = None if deleted_raw == "-" else int(deleted_raw)
        entries.append((old_path, path, additions, deletions))
    return entries


def is_lockfile(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name in LOCKFILE_NAMES or name.endswith(".lockfile")


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def is_test(path: str, patterns: list[str]) -> bool:
    name = PurePosixPath(path).name
    stem, _, extension = name.rpartition(".")
    return (
        (extension in {"js", "jsx", "ts", "tsx", "mjs", "cjs", "mts", "cts"}
         and stem.endswith((".test", ".spec")))
        or (extension == "py" and (name.startswith("test_") or stem.endswith("_test")))
        or (extension == "go" and stem.endswith("_test"))
        or matches_any(path, patterns)
    )


def linguist_generated(paths: list[str]) -> set[str]:
    if not paths:
        return set()
    raw = git("check-attr", "-z", "linguist-generated", "--", *paths, text=False)
    fields = raw.split(b"\0")
    generated: set[str] = set()
    for index in range(0, len(fields) - 2, 3):
        path, attribute, value = fields[index : index + 3]
        if attribute == b"linguist-generated" and value.lower() in {b"set", b"true"}:
            generated.add(path.decode("utf-8", errors="surrogateescape"))
    return generated


def classify(
    parsed: list[tuple[str | None, str, int | None, int | None]],
    generated_patterns: list[str],
    test_patterns: list[str],
) -> list[DiffEntry]:
    paths = sorted({path for old, new, _, _ in parsed for path in (old, new) if path})
    attributed = linguist_generated(paths)
    entries: list[DiffEntry] = []
    for old_path, path, additions, deletions in parsed:
        candidates = [candidate for candidate in (old_path, path) if candidate]
        reason: str | None = None
        if all(is_lockfile(candidate) for candidate in candidates):
            reason = "lockfile"
        elif all(candidate in attributed for candidate in candidates):
            reason = "linguist-generated"
        elif all(matches_any(candidate, generated_patterns) for candidate in candidates):
            reason = "verified-generated-pattern"
        lines = 0 if additions is None or deletions is None else additions + deletions
        entries.append(
            DiffEntry(
                path=path,
                old_path=old_path,
                additions=additions,
                deletions=deletions,
                lines=lines,
                excluded=reason is not None,
                reason=reason,
                test=all(is_test(candidate, test_patterns) for candidate in candidates),
            )
        )
    return entries


def summarize(
    entries: list[DiffEntry], cap: int, raw_cap: int, exemption: str | None = None
) -> dict[str, object]:
    included = [entry for entry in entries if not entry.excluded]
    tests = [entry for entry in included if entry.test]
    weighted = [entry for entry in included if not entry.test]
    excluded = [entry for entry in entries if entry.excluded]
    budgeted_lines = sum(entry.lines for entry in included)
    excluded_lines = sum(entry.lines for entry in excluded)
    weighted_size = sum(
        (entry.additions or 0) + (entry.deletions or 0) / 4 for entry in weighted
    )
    if exemption:
        status = exemption
    elif weighted_size > cap or budgeted_lines > raw_cap:
        status = "cap-violation"
    else:
        status = "within-cap"
    return {
        "status": status,
        "hard_cap": cap,
        "raw_cap": raw_cap,
        "weighted_size": weighted_size,
        "raw_churn": budgeted_lines,
        "test_churn": sum(entry.lines for entry in tests),
        "weighted_additions": sum(entry.additions or 0 for entry in weighted),
        "weighted_deletions": sum(entry.deletions or 0 for entry in weighted),
        "budgeted_lines": budgeted_lines,
        "budgeted_additions": sum(entry.additions or 0 for entry in included),
        "budgeted_deletions": sum(entry.deletions or 0 for entry in included),
        "excluded_lines": excluded_lines,
        "excluded_additions": sum(entry.additions or 0 for entry in excluded),
        "excluded_deletions": sum(entry.deletions or 0 for entry in excluded),
        "included_binary_files": sum(
            entry.additions is None and not entry.excluded for entry in entries
        ),
        "excluded_binary_files": sum(
            entry.additions is None and entry.excluded for entry in entries
        ),
        "files": [asdict(entry) for entry in entries],
    }


def print_text(summary: dict[str, object]) -> None:
    print(
        f"Weighted: {summary['weighted_size']:g}/{summary['hard_cap']} "
        "(tests excluded)\nRaw churn: "
        f"{summary['budgeted_lines']} lines "
        f"(+{summary['budgeted_additions']} / -{summary['budgeted_deletions']}, "
        f"cap {summary['raw_cap']}, tests {summary['test_churn']})"
    )
    print(
        "Excluded: "
        f"{summary['excluded_lines']} lines "
        f"(+{summary['excluded_additions']} / -{summary['excluded_deletions']})"
    )
    print(f"Status: {summary['status']}")
    if summary["included_binary_files"] or summary["excluded_binary_files"]:
        print(
            "Binary files (not line-counted): "
            f"{summary['included_binary_files']} included, "
            f"{summary['excluded_binary_files']} excluded"
        )
    print("Files:")
    for raw_entry in summary["files"]:
        entry = raw_entry
        path = entry["path"]
        if entry["old_path"]:
            path = f"{entry['old_path']} -> {path}"
        churn = "binary" if entry["additions"] is None else str(entry["lines"])
        if entry["excluded"]:
            classification = f"excluded:{entry['reason']}"
        elif entry["test"]:
            classification = "test:raw-only"
        else:
            classification = "weighted-and-raw"
        print(f"  {churn:>7}  {classification:<36} {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure weighted size and raw churn between two Git revisions."
    )
    parser.add_argument(
        "base", help="parent/base revision; commits measure from merge-base(base, head)",
    )
    parser.add_argument("head", help="child/head revision")
    parser.add_argument(
        "--test",
        action="append",
        default=[],
        metavar="GLOB",
        help="verified test-file glob to exclude from weighted size only; repeat as needed",
    )
    parser.add_argument(
        "--generated",
        action="append",
        default=[],
        metavar="GLOB",
        help="verified generated path glob to exclude; repeat as needed",
    )
    parser.add_argument(
        "--per-commit", action="store_true",
        help="measure each non-merge commit in the range against its parent",
    )
    parser.add_argument(
        "--cap", type=int,
        help="weighted size ceiling (default: 1000, or 300 with --per-commit)",
    )
    parser.add_argument(
        "--raw-cap", type=int,
        help="raw churn ceiling (default: 2000, or 600 with --per-commit)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()
    cap, raw_cap = COMMIT_CEILINGS if args.per_commit else PR_CEILINGS
    args.cap = cap if args.cap is None else args.cap
    args.raw_cap = raw_cap if args.raw_cap is None else args.raw_cap
    if args.cap < 0 or args.raw_cap < 0:
        parser.error("require cap >= 0 and raw-cap >= 0")
    return args


def diff_start(base: str, head: str) -> str:
    """merge-base(base, head) for commits, as a PR diff shows it; a tree is compared directly."""
    kinds = {git("cat-file", "-t", revision).strip() for revision in (base, head)}
    return git("merge-base", base, head).strip() if kinds == {"commit"} else base


def retirement_only(base: str, head: str) -> bool:
    fields = git(
        "diff", "--name-status", "-z", "--find-renames", base, head, "--", text=False,
    ).split(b"\0")
    index = 0
    statuses = []
    while index < len(fields) and fields[index]:
        status = fields[index]
        statuses.append(status)
        index += 3 if status.startswith((b"R", b"C")) else 2
    return bool(statuses) and (
        all(status == b"D" for status in statuses)
        or all(status == b"R100" for status in statuses)
    )


def measure(
    start: str, head: str, args: argparse.Namespace, exemption: str | None = None
) -> dict[str, object]:
    raw = git(
        "diff", "--numstat", "-z", "--find-renames", "--find-copies", start, head, "--",
        text=False,
    )
    entries = classify(parse_numstat(raw), args.generated, args.test)
    if exemption is None and retirement_only(start, head):
        exemption = "exempt-retirement"
    return summarize(entries, args.cap, args.raw_cap, exemption)


def measure_commits(start: str, head: str, args: argparse.Namespace) -> list[dict[str, object]]:
    """Each non-merge commit in start..head against its first parent."""
    summaries = []
    for sha in git("rev-list", "--reverse", "--no-merges", f"{start}..{head}").split():
        parents = git("rev-list", "--parents", "-n", "1", sha).split()[1:]
        reason = git(
            "log", "-1", "--format=%(trailers:key=Size-Exception,valueonly,separator=%x20)", sha,
        ).strip()
        summary = measure(parents[0] if parents else EMPTY_TREE, sha, args,
                          "exempt-trailer" if reason else None)
        subject = git("log", "-1", "--format=%s", sha).strip()
        summary.update(commit=sha, subject=subject, exception=reason or None)
        summaries.append(summary)
    return summaries


def print_commits(summaries: list[dict[str, object]], cap: int, raw_cap: int) -> None:
    print(f"Commits: {len(summaries)} (ceilings: weighted {cap}, raw {raw_cap})")
    for summary in summaries:
        print(
            f"  {str(summary['commit'])[:9]}  weighted {summary['weighted_size']:>7g}"
            f"  raw {summary['raw_churn']:>5}  {summary['status']:<17} {summary['subject']}"
        )


def emit(summaries: list[dict[str, object]], args: argparse.Namespace) -> None:
    if args.json:
        report = {"commits": summaries} if args.per_commit else summaries[0]
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.per_commit:
        print_commits(summaries, args.cap, args.raw_cap)
    else:
        print_text(summaries[0])


def main() -> int:
    args = parse_args()
    try:
        start = diff_start(args.base, args.head)
        if args.per_commit:
            summaries = measure_commits(start, args.head, args)
        else:
            summaries = [measure(start, args.head, args)]
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    emit(summaries, args)
    over = any(summary["status"] == "cap-violation" for summary in summaries)
    return 2 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
