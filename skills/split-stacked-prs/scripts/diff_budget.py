#!/usr/bin/env python3
"""Measure review churn in bytes between two Git revisions.

A change's size is the bytes of its added and deleted lines, about four bytes
per token, the unit the 20,000-byte file cap uses. Tests count toward raw churn
only. Lockfiles and verified generated files are
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
from collections.abc import Iterator
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
# (weighted, raw) bytes: a pull request or stack layer, and one commit in it
PR_CEILINGS = (48_000, 96_000)
COMMIT_CEILINGS = (12_000, 24_000)
DELETION_WEIGHT = 0.25
BYTES_PER_TOKEN = 4
# --numstat and the patch list the same files in the same order, one entry per path
# (a type change is one entry but two adjacent patch sections), so the two zip together
DIFF_OPTIONS = ("--find-renames", "--find-copies", "--no-ext-diff", "--no-textconv", "--no-color")
# maps a hunk marker to its [added, deleted] slot
CHANGE_SIDES = {b"+": 0, b"-": 1}
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


@dataclass
class DiffEntry:
    path: str
    old_path: str | None
    added_bytes: int | None
    deleted_bytes: int | None
    bytes: int
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


def parse_numstat(raw: bytes) -> list[tuple[str | None, str, bool]]:
    """(old path, path, binary) per changed file; old path only for a rename or copy."""
    parts = raw.split(b"\0")
    entries: list[tuple[str | None, str, bool]] = []
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
        entries.append((old_path, path, added_raw == "-" and deleted_raw == "-"))
    return entries


def name_status(start: str, head: str) -> dict[str, str]:
    """Status letter per changed path; a rename or copy is keyed by its new path."""
    fields = git("diff", "--name-status", "-z", *DIFF_OPTIONS, start, head, "--", text=False).split(b"\0")
    statuses: dict[str, str] = {}
    index = 0
    while index < len(fields) and fields[index]:
        step = 3 if fields[index].startswith((b"R", b"C")) else 2
        path = fields[index + step - 1].decode("utf-8", errors="surrogateescape")
        statuses[path] = fields[index][:1].decode()
        index += step
    return statuses


def file_sections(raw: bytes) -> Iterator[list[bytes]]:
    """The lines of each file's section of a patch, in git's file order."""
    section: list[bytes] = []
    previous_header = None
    for line in raw.split(b"\n"):
        if line.startswith(b"diff --git "):
            # a type change (file to symlink or submodule) is two sections under one header
            if previous_header is not None and line != previous_header:
                yield section
                section = []
            previous_header = line
        section.append(line)
    if previous_header is not None:
        yield section


def section_bytes(section: list[bytes]) -> list[int]:
    """[added bytes, deleted bytes] of the hunk lines in one file's section."""
    sizes = [0, 0]
    in_hunk = False
    for line in section:
        if line.startswith(b"diff --git "):
            in_hunk = False
        elif line.startswith(b"@@ "):
            in_hunk = True
        elif in_hunk and line[:1] in CHANGE_SIDES:
            # the marker stands in for the newline git strips from the line
            sizes[CHANGE_SIDES[line[:1]]] += len(line)
    return sizes


def parse_patch(raw: bytes) -> list[list[int]]:
    """[added bytes, deleted bytes] per file of a -U0 patch, in git's file order."""
    return [section_bytes(section) for section in file_sections(raw)]


def changed_files(start: str, head: str) -> list[tuple[str | None, str, int | None, int | None]]:
    """(old path, path, added bytes, deleted bytes) per file; a binary file has no byte counts."""
    listed = parse_numstat(git("diff", "--numstat", "-z", *DIFF_OPTIONS, start, head, "--", text=False))
    sizes = parse_patch(git("diff", "-U0", *DIFF_OPTIONS, start, head, "--", text=False))
    if len(sizes) != len(listed):
        raise RuntimeError(f"git listed {len(listed)} changed files but patched {len(sizes)}")
    return [
        (old_path, path, None, None) if binary else (old_path, path, added, deleted)
        for (old_path, path, binary), (added, deleted) in zip(listed, sizes)
    ]


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
    for old_path, path, added, deleted in parsed:
        candidates = [candidate for candidate in (old_path, path) if candidate]
        reason: str | None = None
        if all(is_lockfile(candidate) for candidate in candidates):
            reason = "lockfile"
        elif all(candidate in attributed for candidate in candidates):
            reason = "linguist-generated"
        elif all(matches_any(candidate, generated_patterns) for candidate in candidates):
            reason = "verified-generated-pattern"
        entries.append(
            DiffEntry(
                path=path,
                old_path=old_path,
                added_bytes=added,
                deleted_bytes=deleted,
                bytes=(added or 0) + (deleted or 0),
                excluded=reason is not None,
                reason=reason,
                test=all(is_test(candidate, test_patterns) for candidate in candidates),
            )
        )
    return entries


def kilobytes(size: float) -> str:
    return f"{size / 1000:.1f} KB"


def summarize(
    entries: list[DiffEntry], cap: int, raw_cap: int, exemption: str | None = None
) -> dict[str, object]:
    included = [entry for entry in entries if not entry.excluded]
    tests = [entry for entry in included if entry.test]
    weighted = [entry for entry in included if not entry.test]
    excluded = [entry for entry in entries if entry.excluded]
    raw_churn = sum(entry.bytes for entry in included)
    weighted_size = sum(
        (entry.added_bytes or 0) + (entry.deleted_bytes or 0) * DELETION_WEIGHT for entry in weighted
    )
    if exemption:
        status = exemption
    elif weighted_size > cap or raw_churn > raw_cap:
        status = "cap-violation"
    else:
        status = "within-cap"
    return {
        "status": status,
        "hard_cap": cap,
        "raw_cap": raw_cap,
        "weighted_size": weighted_size,
        "raw_churn": raw_churn,
        "test_churn": sum(entry.bytes for entry in tests),
        "weighted_added_bytes": sum(entry.added_bytes or 0 for entry in weighted),
        "weighted_deleted_bytes": sum(entry.deleted_bytes or 0 for entry in weighted),
        "budgeted_added_bytes": sum(entry.added_bytes or 0 for entry in included),
        "budgeted_deleted_bytes": sum(entry.deleted_bytes or 0 for entry in included),
        "excluded_bytes": sum(entry.bytes for entry in excluded),
        "excluded_added_bytes": sum(entry.added_bytes or 0 for entry in excluded),
        "excluded_deleted_bytes": sum(entry.deleted_bytes or 0 for entry in excluded),
        "included_binary_files": sum(
            entry.added_bytes is None and not entry.excluded for entry in entries
        ),
        "excluded_binary_files": sum(
            entry.added_bytes is None and entry.excluded for entry in entries
        ),
        "files": [asdict(entry) for entry in entries],
    }


def print_text(summary: dict[str, object]) -> None:
    weighted = summary["weighted_size"]
    print(
        f"Weighted: {kilobytes(weighted)}/{kilobytes(summary['hard_cap'])} "
        f"(~{weighted / BYTES_PER_TOKEN / 1000:.1f}k tokens, tests excluded)\nRaw churn: "
        f"{kilobytes(summary['raw_churn'])} "
        f"(+{summary['budgeted_added_bytes']:,} / -{summary['budgeted_deleted_bytes']:,} bytes, "
        f"cap {kilobytes(summary['raw_cap'])}, tests {kilobytes(summary['test_churn'])})"
    )
    print(
        "Excluded: "
        f"{kilobytes(summary['excluded_bytes'])} "
        f"(+{summary['excluded_added_bytes']:,} / -{summary['excluded_deleted_bytes']:,} bytes)"
    )
    print(f"Status: {summary['status']}")
    if summary["included_binary_files"] or summary["excluded_binary_files"]:
        print(
            "Binary files (not measured): "
            f"{summary['included_binary_files']} included, "
            f"{summary['excluded_binary_files']} excluded"
        )
    print("Files:")
    for raw_entry in summary["files"]:
        entry = raw_entry
        path = entry["path"]
        if entry["old_path"]:
            path = f"{entry['old_path']} -> {path}"
        churn = "binary" if entry["added_bytes"] is None else f"{entry['bytes']:,}"
        if entry["excluded"]:
            classification = f"excluded:{entry['reason']}"
        elif entry["test"]:
            classification = "test:raw-only"
        else:
            classification = "weighted-and-raw"
        print(f"  {churn:>9}  {classification:<36} {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure weighted size and raw churn in bytes between two Git revisions."
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
        help="weighted size ceiling in bytes (default: 48000, or 12000 with --per-commit)",
    )
    parser.add_argument(
        "--raw-cap", type=int,
        help="raw churn ceiling in bytes (default: 96000, or 24000 with --per-commit)",
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
    entries = classify(changed_files(start, head), args.generated, args.test)
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
    print(f"Commits: {len(summaries)} (ceilings: weighted {kilobytes(cap)}, raw {kilobytes(raw_cap)})")
    for summary in summaries:
        print(
            f"  {str(summary['commit'])[:9]}  weighted {kilobytes(summary['weighted_size']):>9}"
            f"  raw {kilobytes(summary['raw_churn']):>9}  {summary['status']:<17} {summary['subject']}"
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
