#!/usr/bin/env python3
"""Print each changed file's size and its imports among the changed files.

Sizes are bytes of added and deleted lines, as diff_budget.py counts them.
weighted is added bytes plus a quarter of deleted bytes, and zero for a test
file (marked T) and for an excluded lockfile or generated file (marked X), so
the column sums to diff_budget.py's weighted size. A binary file counts as zero
bytes. A renamed or copied file is listed under its new path, followed by
"(from old/path)"; --json records the old path as old_path (null when none).

Use it to design whole-file layers: a file's layer must sit at or above the
layers of every changed file it imports. Only JS/TS import, export-from,
dynamic import() and vi.mock() specifiers are followed.

Usage:
  import_graph.py BASE TIP [--alias '@/=apps/web/src/'] [--generated GLOB]
                  [--test GLOB] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from diff_budget import DELETION_WEIGHT, DiffEntry, changed_files, classify, git, name_status

IMPORT = re.compile(
    r"""(?:import|export)\s[^'"]*?from\s+['"]([^'"]+)['"]"""
    r"""|import\(\s*['"]([^'"]+)['"]\s*\)"""
    r"""|vi\.mock\(\s*['"]([^'"]+)['"]""",
    re.S,
)
SUFFIXES = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.tsx", "/index.js"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base")
    parser.add_argument("tip")
    parser.add_argument("--alias", action="append", default=[], help="PREFIX=DIR, e.g. '@/=apps/web/src/'")
    parser.add_argument(
        "--generated", action="append", default=[], metavar="GLOB",
        help="verified generated path glob to exclude, as in diff_budget.py; repeat as needed",
    )
    parser.add_argument(
        "--test", action="append", default=[], metavar="GLOB",
        help="verified test-file glob that weighs zero, as in diff_budget.py; repeat as needed",
    )
    parser.add_argument("--json", help="also write the graph as JSON to this path")
    return parser.parse_args()


def candidate_path(src: str, spec: str, aliases: list[list[str]]) -> str | None:
    for prefix, target in aliases:
        if spec.startswith(prefix):
            return target + spec[len(prefix):]
    if spec.startswith("."):
        return os.path.normpath(os.path.join(os.path.dirname(src), spec))
    return None


def resolve(src: str, spec: str, aliases: list[list[str]], changed: set[str]) -> str | None:
    candidate = candidate_path(src, spec, aliases)
    if candidate is None:
        return None
    return next((candidate + suffix for suffix in SUFFIXES if candidate + suffix in changed), None)


def dependencies(path: str, tip: str, aliases: list[list[str]], changed: set[str]) -> list[str]:
    text = git("show", f"{tip}:{path}", text=False).decode("utf-8", errors="replace")
    deps = set()
    for match in IMPORT.finditer(text):
        spec = next(group for group in match.groups() if group)
        target = resolve(path, spec, aliases, changed)
        if target and target != path:
            deps.add(target)
    return sorted(deps)


def weigh(entry: DiffEntry) -> float:
    if entry.excluded or entry.test:
        return 0
    return (entry.added_bytes or 0) + (entry.deleted_bytes or 0) * DELETION_WEIGHT


def build_node(entry: DiffEntry, status: str, deps: list[str]) -> dict[str, object]:
    return {
        "status": status,
        "old_path": entry.old_path,
        "test": entry.test,
        "excluded": entry.excluded,
        "reason": entry.reason,
        "added": entry.added_bytes or 0,
        "deleted": entry.deleted_bytes or 0,
        "weighted": weigh(entry),
        "deps": deps,
    }


def print_node(path: str, node: dict[str, object]) -> None:
    marker = "X" if node["excluded"] else "T" if node["test"] else " "
    origin = f" (from {node['old_path']})" if node["old_path"] else ""
    deps = ", ".join(node["deps"])
    print(
        f"{node['status']} {marker} +{node['added']:7,d} -{node['deleted']:7,d}"
        f" w{node['weighted']:9,.0f}  {path}{origin}" + (f"  <- {deps}" if deps else "")
    )


def main() -> int:
    args = parse_args()
    aliases = [alias.split("=", 1) for alias in args.alias]
    try:
        entries = classify(changed_files(args.base, args.tip), args.generated, args.test)
        statuses = name_status(args.base, args.tip)
        changed = {entry.path for entry in entries}
        graph = {}
        for entry in sorted(entries, key=lambda entry: entry.path):
            status = statuses.get(entry.path, "?")
            deps = [] if status == "D" else dependencies(entry.path, args.tip, aliases, changed)
            graph[entry.path] = build_node(entry, status, deps)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(graph, fh, indent=1)
    for path, node in graph.items():
        print_node(path, node)
    return 0


if __name__ == "__main__":
    sys.exit(main())
