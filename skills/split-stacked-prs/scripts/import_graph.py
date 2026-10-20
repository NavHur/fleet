#!/usr/bin/env python3
"""Print each changed file's size and its imports among the changed files.

Sizes are bytes of added and deleted lines, as diff_budget.py counts them;
weighted counts deletions at a quarter and tests as zero. A renamed file is
listed under its new path, and a binary file counts as zero bytes.

Use it to design whole-file layers: a file's layer must sit at or above the
layers of every changed file it imports. Only JS/TS import, export-from,
dynamic import() and vi.mock() specifiers are followed.

Usage:
  import_graph.py BASE TIP [--alias '@/=apps/web/src/'] [--json OUT]
"""

import argparse
import json
import os
import re
import subprocess
import sys

from diff_budget import DELETION_WEIGHT, DIFF_OPTIONS, changed_files

TEST = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")
IMPORT = re.compile(
    r"""(?:import|export)\s[^'"]*?from\s+['"]([^'"]+)['"]"""
    r"""|import\(\s*['"]([^'"]+)['"]\s*\)"""
    r"""|vi\.mock\(\s*['"]([^'"]+)['"]""",
    re.S,
)
SUFFIXES = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.tsx", "/index.js"]


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base")
    parser.add_argument("tip")
    parser.add_argument("--alias", action="append", default=[], help="PREFIX=DIR, e.g. '@/=apps/web/src/'")
    parser.add_argument("--json", help="also write the graph as JSON to this path")
    args = parser.parse_args()

    aliases = [a.split("=", 1) for a in args.alias]
    sizes = {path: (added or 0, deleted or 0) for _, path, added, deleted in changed_files(args.base, args.tip)}
    status = {}
    fields = git("diff", "--name-status", "-z", *DIFF_OPTIONS, args.base, args.tip).split("\0")
    index = 0
    while index < len(fields) and fields[index]:
        code = fields[index]
        step = 3 if code[0] in "RC" else 2
        status[fields[index + step - 1]] = code[0]
        index += step
    changed = set(sizes)

    def resolve(src, spec):
        candidate = None
        for prefix, target in aliases:
            if spec.startswith(prefix):
                candidate = target + spec[len(prefix):]
                break
        if candidate is None and spec.startswith("."):
            candidate = os.path.normpath(os.path.join(os.path.dirname(src), spec))
        if candidate is None:
            return None
        for suffix in SUFFIXES:
            if candidate + suffix in changed:
                return candidate + suffix
        return None

    graph = {}
    for path in sorted(changed):
        deps = set()
        if status.get(path) != "D":
            text = git("show", f"{args.tip}:{path}")
            for match in IMPORT.finditer(text):
                spec = next(g for g in match.groups() if g)
                target = resolve(path, spec)
                if target and target != path:
                    deps.add(target)
        added, deleted = sizes[path]
        is_test = bool(TEST.search(path))
        graph[path] = {
            "status": status.get(path, "?"),
            "test": is_test,
            "added": added,
            "deleted": deleted,
            "weighted": 0 if is_test else added + deleted * DELETION_WEIGHT,
            "deps": sorted(deps),
        }

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(graph, fh, indent=1)
    for path, v in graph.items():
        deps = ", ".join(v["deps"])
        print(
            f"{v['status']} {'T' if v['test'] else ' '} +{v['added']:7,d} -{v['deleted']:7,d}"
            f" w{v['weighted']:9,.0f}  {path}" + (f"  <- {deps}" if deps else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
